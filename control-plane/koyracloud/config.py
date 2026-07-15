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


def _int(name: str, default: int) -> int:
    """Like int(os.environ[name]) but treats unset/blank as the default — the
    swarm stack passes optional vars through as empty strings (${VAR:-})."""
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw else default


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
    # Registry-qualified by default: the buildpack image is a build-time-only
    # FROM, so a local-only tag is deleted by any image prune and every
    # manifest build then fails with "pull access denied" (#66). From the
    # instance registry, docker build re-pulls it on demand (install.sh pushes
    # it there).
    runtime_image: str = field(default_factory=lambda: os.environ.get(
        "KOYRA_RUNTIME_IMAGE", "127.0.0.1:5000/koyracloud-runtime:latest"))
    # Internal Docker registry (a swarm service koyracloud owns). Per-app images
    # are built locally, pushed here, and pulled by swarm on whichever node runs
    # the service — so apps aren't pinned to the build node. Published on the
    # ingress mesh; 127.0.0.1 is an insecure-OK registry by default and is never
    # reachable from outside the swarm.
    registry: str = field(default_factory=lambda: os.environ.get(
        "KOYRA_REGISTRY", "127.0.0.1:5000"))
    # Where to clone + build (LOCAL disk, not the NFS base — NFS small-file I/O
    # makes npm ci/builds glacial and can starve the control-plane's own DB).
    build_dir: str = field(default_factory=lambda: os.environ.get(
        "KOYRA_BUILD_DIR", "/tmp/koyra-build"))
    nfs_base: str = field(default_factory=lambda: os.environ.get(
        "KOYRA_NFS_BASE", "/mnt/koyracloud"))
    # NFS server for persist volumes. When set, persist dirs use Docker's NFS
    # volume driver (Docker mounts the NFS on whichever node runs the app), so
    # apps need no node pinning. Empty → plain bind mounts (local/dev).
    nfs_server: str = field(default_factory=lambda: os.environ.get("KOYRA_NFS_SERVER", ""))
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
    # How long a deploy waits for the swarm service(s) to actually converge
    # (every desired replica Running — which, with a healthcheck, means healthy)
    # before marking the deploy failed. Must exceed healthcheck_start_period:
    # a buildless runtime legitimately sits in Starting for the whole start
    # period. Hard failures (rollback, restart attempts exhausted) fail early
    # regardless of this ceiling.
    deploy_converge_timeout: int = field(default_factory=lambda: _int(
        "KOYRA_DEPLOY_CONVERGE_TIMEOUT", 660))
    deploy_converge_poll: int = field(default_factory=lambda: _int(
        "KOYRA_DEPLOY_CONVERGE_POLL", 3))
    apps_domain: str = field(default_factory=lambda: os.environ.get(
        "KOYRA_APPS_DOMAIN", "apps.example.com"))
    # When the apps_domain sits behind a TLS-terminating proxy — e.g. Cloudflare
    # with a proxied ``*.<apps_domain>`` record over a tunnel — Traefik must NOT
    # ACME-mint certs for the in-zone auto-subdomains: the edge already serves
    # the cert and there is no inbound HTTP-01 path, so an attempt only fails and
    # burns Let's Encrypt rate limits. Self-hosters with open 80/443 leave this
    # off and Traefik gets Let's Encrypt certs for auto-subdomains as usual.
    apps_domain_proxied: bool = field(
        default_factory=lambda: os.environ.get("KOYRA_APPS_DOMAIN_PROXIED", "") == "1")
    # Default per-app resource limits (a manifest may lower; capped so one app
    # can't starve a node).
    default_cpu: str = field(default_factory=lambda: os.environ.get("KOYRA_DEFAULT_CPU", "1.0"))
    default_memory: str = field(
        default_factory=lambda: os.environ.get("KOYRA_DEFAULT_MEMORY", "512M"))
    # Public IP the homelab edge answers on — shown as the DNS hint for custom
    # domains and used to check whether a domain already points here.
    public_ip: str = field(default_factory=lambda: os.environ.get("KOYRA_PUBLIC_IP", ""))
    # Hosts a user may never attach (control-plane host + apps apex are reserved
    # automatically; this adds extras).
    reserved_hosts: list[str] = field(default_factory=lambda: _csv("KOYRA_RESERVED_HOSTS"))
    # Uptime monitor
    uptime_enabled: bool = field(
        default_factory=lambda: os.environ.get("KOYRA_UPTIME_ENABLED", "1") != "0")
    uptime_interval: int = field(
        default_factory=lambda: int(os.environ.get("KOYRA_UPTIME_INTERVAL", "120")))
    # DB backup (SQLite only)
    backup_enabled: bool = field(
        default_factory=lambda: os.environ.get("KOYRA_BACKUP_ENABLED", "1") != "0")
    backup_interval_hours: int = field(
        default_factory=lambda: _int("KOYRA_BACKUP_INTERVAL_HOURS", 12))
    backup_keep: int = field(
        default_factory=lambda: _int("KOYRA_BACKUP_KEEP", 14))
    # Where snapshots land. Defaults to <db>/backups (same volume as the DB),
    # but point this at a separate mount so a volume loss doesn't take the DB
    # and its backups together. Empty => the <db-dir>/backups default.
    backup_dir: str = field(
        default_factory=lambda: os.environ.get("KOYRA_BACKUP_DIR", ""))
    # Optional: pin deployed apps to a single node (e.g. "node-1"). Needed when
    # the runtime image is only present locally on that node (no registry push).
    # Empty = no placement constraint (apps schedule anywhere; image must be
    # pullable from a registry).
    app_node: str = field(default_factory=lambda: os.environ.get("KOYRA_APP_NODE", ""))
    # Pass --resolve-image=never to `docker stack deploy` so swarm uses the
    # local image instead of resolving a digest from a registry.
    resolve_image_never: bool = field(
        default_factory=lambda: os.environ.get("KOYRA_RESOLVE_IMAGE_NEVER", "") == "1")
    # Shared Redis bus. One koyracloud-owned instance apps reach as
    # ``redis:6379`` on the traefik network. Each app with ``redis: true`` gets a
    # scoped ACL user (managed by the control plane via the admin password) and a
    # stable injected REDIS_URL. The admin password being empty disables the
    # feature: a manifest asking for redis then fails the deploy loudly.
    redis_host: str = field(default_factory=lambda: os.environ.get("KOYRA_REDIS_HOST", "redis"))
    redis_port: int = field(default_factory=lambda: int(os.environ.get("KOYRA_REDIS_PORT", "6379")))
    redis_admin_password: str = field(
        default_factory=lambda: _secret("KOYRA_REDIS_ADMIN_PASSWORD", ""))
    # Cron scheduler
    cron_enabled: bool = field(
        default_factory=lambda: os.environ.get("KOYRA_CRON_ENABLED", "1") != "0")
    cron_tick_seconds: int = field(
        default_factory=lambda: int(os.environ.get("KOYRA_CRON_TICK_SECONDS", "30")))
    cron_job_timeout: int = field(
        default_factory=lambda: int(os.environ.get("KOYRA_CRON_JOB_TIMEOUT", "600")))
    # GitHub
    github_client_id: str = field(default_factory=lambda: os.environ.get("GITHUB_CLIENT_ID", ""))
    github_client_secret: str = field(
        default_factory=lambda: _secret("GITHUB_CLIENT_SECRET", ""))
    github_pat: str = field(default_factory=lambda: _secret("GITHUB_PAT", ""))
    # Shared secret for verifying GitHub push webhooks (push-to-deploy).
    webhook_secret: str = field(default_factory=lambda: _secret("KOYRA_WEBHOOK_SECRET", ""))
    # Email alerts via Resend (inert until an API key is set).
    resend_api_key: str = field(default_factory=lambda: _secret("RESEND_API_KEY", ""))
    email_from: str = field(default_factory=lambda: os.environ.get(
        "KOYRA_EMAIL_FROM", "koyracloud <alerts@example.com>"))
    default_notify_email: str = field(
        default_factory=lambda: os.environ.get("KOYRA_DEFAULT_NOTIFY_EMAIL", ""))
    # Admin logins (always allowed; can manage the invite list). Invited members
    # live in the allowed_users table.
    allowed_logins: list[str] = field(default_factory=lambda: _csv("KOYRA_ALLOWED_LOGINS"))
    # Local-dev login bypass: set to a github login to skip OAuth entirely.
    dev_login: str = field(default_factory=lambda: os.environ.get("KOYRA_DEV_LOGIN", ""))
    base_url: str = field(default_factory=lambda: os.environ.get(
        "KOYRA_BASE_URL", "http://localhost:8000"))
    # Cloudflare for SaaS — registers user-supplied custom domains as custom
    # hostnames so the edge mints/renews their certs. Active only when both
    # token and zone_id are set; otherwise every Cloudflare call is a graceful
    # no-op (local/dev + existing deploys keep working unchanged).
    cloudflare_api_token: str = field(
        default_factory=lambda: _secret("CLOUDFLARE_API_TOKEN", ""))
    cloudflare_zone_id: str = field(
        default_factory=lambda: os.environ.get("KOYRA_CLOUDFLARE_ZONE_ID", ""))
    # The proxied CNAME customers point their domain at (your SaaS fallback
    # origin). No default — set it per instance via KOYRA_CLOUDFLARE_SAAS_ORIGIN.
    cloudflare_saas_origin: str = field(default_factory=lambda: os.environ.get(
        "KOYRA_CLOUDFLARE_SAAS_ORIGIN", ""))


def get_settings() -> Settings:
    return Settings()
