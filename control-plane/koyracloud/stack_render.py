"""Render a Docker Swarm stack (compose v3.8) from an app + its manifest.

Pure function: no I/O, fully unit-tested. The control plane writes the returned
dict to YAML and runs ``docker stack deploy`` against it.
"""
from __future__ import annotations

from koyracloud.config import Settings
from koyracloud.manifest import Manifest


def app_host(manifest: Manifest, app_name: str, settings: Settings) -> str:
    return manifest.subdomain or f"{app_name}.{settings.apps_domain}"


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

    # Split hosts by zone. In-zone hosts (the *.apps auto-subdomain) get a
    # Let's Encrypt cert from Traefik as before. Custom Cloudflare-for-SaaS
    # hosts are TLS-terminated at the Cloudflare edge and reach Traefik over the
    # tunnel (noTLSVerify), so Traefik must NOT try to ACME-mint a cert for them
    # — there is no inbound HTTP-01 path, so it would only fail and burn
    # Let's Encrypt rate limits. They get a sibling router with TLS but no
    # resolver, pointing at the same service.
    apps_domain = settings.apps_domain.lower()

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
        labels += _router_labels(router, zone_hosts, cert=True)
    if saas_hosts:
        labels += _router_labels(f"{router}-saas", saas_hosts, cert=False)
    if not zone_hosts and not saas_hosts:  # defensive; effective_hosts is never empty
        labels += _router_labels(router, effective_hosts, cert=True)

    # NFS is used only for persisted data dirs (shared across nodes), never for
    # code. Mounted at the same paths the image expects under /app.
    volumes = [f"{settings.nfs_base}/{app_name}/{d}:/app/{d}" for d in manifest.persist]

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

    if volumes:
        service["volumes"] = volumes

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

    return {
        "version": "3.8",
        "services": {app_name: service},
        "networks": {settings.traefik_network: {"external": True}},
    }
