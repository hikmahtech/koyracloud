"""Render a Docker Swarm stack (compose v3.8) from an app + its manifest.

Pure function: no I/O, fully unit-tested. The control plane writes the returned
dict to YAML and runs ``docker stack deploy`` against it.

The stack holds the **web** service (behind Traefik) plus one service per
**worker** (always-on, no router) — both run the same prebuilt image. Cron jobs
are NOT in the stack; the scheduler launches them as run-to-completion jobs.
"""
from __future__ import annotations

import json

from koyracloud.config import Settings
from koyracloud.manifest import Manifest


def auto_subdomain(app_name: str, token: str, settings: Settings) -> str:
    """The app's default in-zone host: ``<name>-<token>.<apps_domain>``.

    The random per-app token keeps two apps' default URLs from ever colliding
    and stops them being trivially enumerable. ``apps_domain`` is one label deep
    (e.g. ``koyracloud.com``) so a single free ``*.<apps_domain>`` wildcard cert
    covers every app. Falls back to the bare name when no token is set (apps
    created before the token existed)."""
    label = f"{app_name}-{token}" if token else app_name
    return f"{label}.{settings.apps_domain}"


def app_host(manifest: Manifest, app_name: str, settings: Settings, token: str = "") -> str:
    return manifest.subdomain or auto_subdomain(app_name, token, settings)


def worker_service_name(app_name: str, worker_name: str) -> str:
    """The stack-service key for a worker (the live Swarm service is then
    ``koyra-<app>_<app>-<worker>``)."""
    return f"{app_name}-{worker_name}"


def render_stack(
    manifest: Manifest,
    *,
    app_name: str,
    image: str,
    env_overrides: dict[str, str],
    secret_values: dict[str, str],
    settings: Settings,
    hosts: list[str] | None = None,
    analytics_site: str = "",
    redis_url: str = "",
    pin_node: str = "",
) -> dict:
    # ``image`` is the per-app image already built + pushed to the internal
    # registry; the container serves the app from it (no NFS workspace).
    # Control-plane-managed domains take precedence; fall back to the manifest
    # subdomain (or a derived default) when none are configured.
    effective_hosts = list(hosts) if hosts else [app_host(manifest, app_name, settings)]
    router = f"koyra-{app_name}"

    # Runtime environment shared by web + workers: manifest defaults <
    # control-plane env < decrypted secrets, plus the injected REDIS_URL. (Build-
    # time vars are baked into the image at build; these are the runtime values.)
    base_env: dict[str, str] = {}
    base_env.update(manifest.env)
    base_env.update(env_overrides)
    base_env.update(secret_values)
    if redis_url:
        base_env["REDIS_URL"] = redis_url

    # Web environment additionally carries the native-analytics beacon config
    # (only meaningful for runtime: static; dynamic apps paste the snippet).
    web_env = dict(base_env)
    if analytics_site:
        web_env["KOYRA_ANALYTICS_URL"] = settings.base_url
        web_env["KOYRA_ANALYTICS_SITE"] = analytics_site
    # koyra_static.py reads its behaviour from env, same channel as the beacon:
    # SPA-fallback mode + extra response headers. Only meaningful for static.
    if manifest.runtime == "static":
        if manifest.spa is not None:
            web_env["KOYRA_SPA"] = "1" if manifest.spa else "0"
        if manifest.headers:
            web_env["KOYRA_HEADERS"] = json.dumps(manifest.headers)

    # Split hosts by zone. In-zone hosts are the app's own auto-subdomain under
    # apps_domain; custom Cloudflare-for-SaaS hosts are everything else. SaaS
    # hosts are TLS-terminated at the Cloudflare edge and reach Traefik over the
    # tunnel (noTLSVerify), so Traefik must NOT ACME-mint a cert for them — there
    # is no inbound HTTP-01 path, so it would only fail and burn Let's Encrypt
    # rate limits. The in-zone auto-subdomain gets a Traefik Let's Encrypt cert
    # UNLESS apps_domain itself sits behind the same proxy (apps_domain_proxied),
    # in which case the edge serves its cert too and Traefik must skip ACME.
    apps_domain = settings.apps_domain.lower()
    zone_cert = not settings.apps_domain_proxied

    def _in_zone(h: str) -> bool:
        h = h.lower()
        return h == apps_domain or h.endswith("." + apps_domain)

    zone_hosts = [h for h in effective_hosts if _in_zone(h)]
    saas_hosts = [h for h in effective_hosts if not _in_zone(h)]

    labels = [
        "traefik.enable=true",
        f"traefik.http.services.{router}.loadbalancer.server.port={manifest.port}",
    ]

    def _router_labels(name: str, rule_hosts: list[str], cert: bool) -> list[str]:
        rule = " || ".join(f"Host(`{h}`)" for h in rule_hosts)
        out = [
            f"traefik.http.routers.{name}.rule={rule}",
            f"traefik.http.routers.{name}.entrypoints={settings.https_entrypoint}",
            f"traefik.http.routers.{name}.service={router}",
            f"traefik.http.routers.{name}.tls=true",
        ]
        if cert:
            out.append(f"traefik.http.routers.{name}.tls.certresolver={settings.cert_resolver}")
        return out

    if zone_hosts:
        labels += _router_labels(router, zone_hosts, cert=zone_cert)
    if saas_hosts:
        labels += _router_labels(f"{router}-saas", saas_hosts, cert=False)
    if not zone_hosts and not saas_hosts:  # defensive; effective_hosts is never empty
        labels += _router_labels(router, effective_hosts, cert=zone_cert)

    # NFS is used only for persisted data dirs (shared across nodes), never for
    # code, mounted at the paths the image expects under /app. With an NFS server
    # configured, each dir is a Docker NFS-driver volume — Docker mounts the NFS
    # on whichever node runs the app, so nothing is pinned. Without one (local /
    # dev), fall back to a plain bind mount. Web + workers share these volumes.
    service_volumes: list[str] = []
    named_volumes: dict[str, dict] = {}
    for d in manifest.persist:
        device = f"{settings.nfs_base}/{app_name}/{d}"
        if settings.nfs_server:
            vol = f"koyra-{app_name}-{d}".replace("/", "-")
            service_volumes.append(f"{vol}:/app/{d}")
            named_volumes[vol] = {
                "driver": "local",
                "driver_opts": {
                    "type": "nfs",
                    "o": f"addr={settings.nfs_server},rw,nfsvers=4",
                    "device": f":{device}",
                },
            }
        else:
            service_volumes.append(f"{device}:/app/{d}")

    # Per-app pin (this app is stateful, keep it on its recorded node) takes
    # precedence over the operator-wide app_node pin. With neither set, swarm
    # runs/reschedules the image-from-registry app on any node.
    node = pin_node or settings.app_node
    placement = {"constraints": [f"node.hostname == {node}"]} if node else None

    def _deploy(replicas: int, cpu: str, memory: str,
                labels: list[str] | None = None) -> dict:
        block: dict = {
            "replicas": replicas,
            "update_config": {
                "parallelism": 1,
                "delay": "10s",
                "order": "start-first",
                "failure_action": "rollback",
            },
            "rollback_config": {"parallelism": 1, "delay": "10s"},
            "restart_policy": {
                "condition": "on-failure",
                "delay": "5s",
                "max_attempts": 3,
                "window": "120s",
            },
            "resources": {
                "limits": {
                    "cpus": cpu or settings.default_cpu,
                    "memory": memory or settings.default_memory,
                },
            },
        }
        if labels is not None:
            block["labels"] = labels
        if placement is not None:
            block["placement"] = placement
        return block

    web: dict = {
        "image": image,
        "environment": web_env,
        "networks": [settings.traefik_network],
        "deploy": _deploy(1, manifest.cpu, manifest.memory, labels=labels),
    }
    if service_volumes:
        web["volumes"] = service_volumes
    if manifest.healthcheck:
        url = f"http://localhost:{manifest.port}{manifest.healthcheck}"
        web["healthcheck"] = {
            "test": ["CMD", "python3", "-c",
                     f"import urllib.request;urllib.request.urlopen('{url}')"],
            "interval": "30s",
            "timeout": "10s",
            "retries": 3,
            "start_period": settings.healthcheck_start_period,
        }

    services: dict = {app_name: web}

    # One service per worker: same image + env (incl REDIS_URL) + persist, but no
    # Traefik router and no healthcheck. The CMD is overridden to the worker's
    # start command (the web's predeploy is NOT run — migrations belong to web).
    for w in manifest.workers:
        wsvc: dict = {
            "image": image,
            "environment": base_env,
            "networks": [settings.traefik_network],
            "command": ["sh", "-c", w.start],
            "deploy": _deploy(w.replicas, w.cpu, w.memory),
        }
        if service_volumes:
            wsvc["volumes"] = list(service_volumes)
        services[worker_service_name(app_name, w.name)] = wsvc

    stack = {
        "version": "3.8",
        "services": services,
        "networks": {settings.traefik_network: {"external": True}},
    }
    if named_volumes:
        stack["volumes"] = named_volumes
    return stack
