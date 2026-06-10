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
    repo_url: str,
    ref: str,
    git_token: str,
    env_overrides: dict[str, str],
    secret_values: dict[str, str],
    settings: Settings,
    hosts: list[str] | None = None,
) -> dict:
    # Control-plane-managed domains take precedence; fall back to the manifest
    # subdomain (or a derived default) when none are configured.
    effective_hosts = list(hosts) if hosts else [app_host(manifest, app_name, settings)]
    rule = " || ".join(f"Host(`{h}`)" for h in effective_hosts)
    router = f"koyra-{app_name}"

    # Build the container environment: manifest defaults < control-plane env <
    # decrypted secrets < koyra-injected runtime vars.
    environment: dict[str, str] = {}
    environment.update(manifest.env)
    environment.update(env_overrides)
    environment.update(secret_values)
    environment["KOYRA_REPO_URL"] = repo_url
    environment["KOYRA_REF"] = ref
    environment["KOYRA_WORKSPACE"] = "/workspace"
    if git_token:
        environment["KOYRA_GIT_TOKEN"] = git_token

    labels = [
        "traefik.enable=true",
        f"traefik.http.routers.{router}.rule={rule}",
        f"traefik.http.routers.{router}.entrypoints={settings.https_entrypoint}",
        f"traefik.http.routers.{router}.tls.certresolver={settings.cert_resolver}",
        f"traefik.http.services.{router}.loadbalancer.server.port={manifest.port}",
    ]

    service: dict = {
        "image": settings.runtime_image,
        "environment": environment,
        "volumes": [f"{settings.nfs_base}/{app_name}:/workspace"],
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
        },
    }

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
