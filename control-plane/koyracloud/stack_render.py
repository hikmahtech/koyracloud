"""Render a Docker Swarm stack (compose v3.8) from an app + its manifest.

Pure function: no I/O, fully unit-tested. The control plane writes the returned
dict to YAML and runs ``docker stack deploy`` against it.
"""
from __future__ import annotations

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
) -> dict:
    # ``image`` is the per-app image already built + pushed to the internal
    # registry; the container serves the app from it (no NFS workspace).
    # Control-plane-managed domains take precedence; fall back to the manifest
    # subdomain (or a derived default) when none are configured.
    effective_hosts = list(hosts) if hosts else [app_host(manifest, app_name, settings)]
    router = f"koyra-{app_name}"

    # Runtime environment: manifest defaults < control-plane env < decrypted
    # secrets. (Build-time vars are baked into the image at build; these are the
    # values read at runtime.)
    environment: dict[str, str] = {}
    environment.update(manifest.env)
    environment.update(env_overrides)
    environment.update(secret_values)
    # Native analytics: the static server auto-injects the beacon when these are
    # set (only meaningful for runtime: static; dynamic apps paste the snippet).
    if analytics_site:
        environment["KOYRA_ANALYTICS_URL"] = settings.base_url
        environment["KOYRA_ANALYTICS_SITE"] = analytics_site

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
    # dev), fall back to a plain bind mount.
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

    service: dict = {
        "image": image,
        "environment": environment,
        "networks": [settings.traefik_network],
        "deploy": {
            "replicas": 1,
            "labels": labels,
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
                    "cpus": manifest.cpu or settings.default_cpu,
                    "memory": manifest.memory or settings.default_memory,
                },
            },
        },
    }

    if service_volumes:
        service["volumes"] = service_volumes

    # No placement constraint by default: the image is pulled from the internal
    # registry, so swarm can run (and reschedule) the app on any node. Pin only
    # if an operator explicitly sets app_node.
    if settings.app_node:
        service["deploy"]["placement"] = {
            "constraints": [f"node.hostname == {settings.app_node}"]
        }

    if manifest.healthcheck:
        url = f"http://localhost:{manifest.port}{manifest.healthcheck}"
        service["healthcheck"] = {
            "test": ["CMD", "python3", "-c",
                     f"import urllib.request;urllib.request.urlopen('{url}')"],
            "interval": "30s",
            "timeout": "10s",
            "retries": 3,
            "start_period": settings.healthcheck_start_period,
        }

    stack = {
        "version": "3.8",
        "services": {app_name: service},
        "networks": {settings.traefik_network: {"external": True}},
    }
    if named_volumes:
        stack["volumes"] = named_volumes
    return stack
