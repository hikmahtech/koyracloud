"""Runtime configuration, sourced entirely from environment variables.

No secrets are hardcoded. Only non-sensitive values carry defaults; sensitive
values (Fernet key, OAuth secret, PAT) default to empty and the app fails loudly
when a feature needing them is used.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _csv(name: str, default: str = "") -> list[str]:
    return [x.strip() for x in os.environ.get(name, default).split(",") if x.strip()]


def _secret(name: str, default: str = "") -> str:
    """Read a sensitive value from ``<NAME>_FILE`` (a mounted Docker secret) if
    set, else from ``<NAME>``. Keeps secrets out of the process env / inspect."""
    path = os.environ.get(f"{name}_FILE")
    if path:
        try:
            return Path(path).read_text().strip()
        except OSError:
            return default
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    # State
    db_url: str = field(default_factory=lambda: os.environ.get(
        "DB_URL", "sqlite:///./data/koyracloud.db"))
    # Crypto / sessions
    secret_key: str = field(default_factory=lambda: _secret("KOYRA_SECRET_KEY", ""))
    session_secret: str = field(default_factory=lambda: _secret(
        "KOYRA_SESSION_SECRET", "dev-session-secret-change-me"))
    # Swarm / Traefik / NFS
    runtime_image: str = field(default_factory=lambda: os.environ.get(
        "KOYRA_RUNTIME_IMAGE", "koyracloud-runtime:latest"))
    nfs_base: str = field(default_factory=lambda: os.environ.get(
        "KOYRA_NFS_BASE", "/mnt/koyracloud"))
    traefik_network: str = field(default_factory=lambda: os.environ.get(
        "KOYRA_TRAEFIK_NETWORK", "traefik_public"))
    cert_resolver: str = field(default_factory=lambda: os.environ.get(
        "KOYRA_CERT_RESOLVER", "letsencrypt"))
    https_entrypoint: str = field(default_factory=lambda: os.environ.get(
        "KOYRA_HTTPS_ENTRYPOINT", "websecure"))
    # Healthcheck grace period before failures count. Must exceed the first
    # build-on-start time (pip install + npm ci + frontend build), else swarm
    # kills the container mid-build and it never converges.
    healthcheck_start_period: str = field(default_factory=lambda: os.environ.get(
        "KOYRA_HEALTHCHECK_START_PERIOD", "600s"))
    apps_domain: str = field(default_factory=lambda: os.environ.get(
        "KOYRA_APPS_DOMAIN", "apps.koyracloud.com"))
    # Public IP the homelab edge answers on — shown as the DNS hint for custom
    # domains and used to check whether a domain already points here.
    public_ip: str = field(default_factory=lambda: os.environ.get("KOYRA_PUBLIC_IP", ""))
    # Uptime monitor
    uptime_enabled: bool = field(
        default_factory=lambda: os.environ.get("KOYRA_UPTIME_ENABLED", "1") != "0")
    uptime_interval: int = field(
        default_factory=lambda: int(os.environ.get("KOYRA_UPTIME_INTERVAL", "120")))
    # Optional: pin deployed apps to a single node (e.g. "baa"). Needed when the
    # runtime image is only present locally on that node (no registry push).
    # Empty = no placement constraint (apps schedule anywhere; image must be
    # pullable from a registry).
    app_node: str = field(default_factory=lambda: os.environ.get("KOYRA_APP_NODE", ""))
    # Pass --resolve-image=never to `docker stack deploy` so swarm uses the
    # local image instead of resolving a digest from a registry.
    resolve_image_never: bool = field(
        default_factory=lambda: os.environ.get("KOYRA_RESOLVE_IMAGE_NEVER", "") == "1")
    # GitHub
    github_client_id: str = field(default_factory=lambda: os.environ.get("GITHUB_CLIENT_ID", ""))
    github_client_secret: str = field(
        default_factory=lambda: _secret("GITHUB_CLIENT_SECRET", ""))
    github_pat: str = field(default_factory=lambda: _secret("GITHUB_PAT", ""))
    # Shared secret for verifying GitHub push webhooks (push-to-deploy).
    webhook_secret: str = field(default_factory=lambda: _secret("KOYRA_WEBHOOK_SECRET", ""))
    # Admin logins (always allowed; can manage the invite list). Invited members
    # live in the allowed_users table.
    allowed_logins: list[str] = field(default_factory=lambda: _csv("KOYRA_ALLOWED_LOGINS"))
    # Local-dev login bypass: set to a github login to skip OAuth entirely.
    dev_login: str = field(default_factory=lambda: os.environ.get("KOYRA_DEV_LOGIN", ""))
    base_url: str = field(default_factory=lambda: os.environ.get(
        "KOYRA_BASE_URL", "http://localhost:8000"))


def get_settings() -> Settings:
    return Settings()
