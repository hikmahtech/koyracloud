"""Database models for the control plane's own state."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from koyracloud.db import Base


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# Deploy lifecycle states.
DEPLOY_STATUSES = ("pending", "building", "deploying", "live", "failed", "rolled_back", "superseded")


class App(Base):
    __tablename__ = "apps"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    repo_url: Mapped[str] = mapped_column(String(512))
    branch: Mapped[str] = mapped_column(String(128), default="main")
    # Random slug appended to the default in-zone host (<name>-<token>.<apps_domain>)
    # so app names never collide and the URL isn't trivially enumerable.
    subdomain_token: Mapped[str] = mapped_column(String(16), default="", index=True)
    auto_deploy: Mapped[bool] = mapped_column(default=False)
    owner_login: Mapped[str] = mapped_column(String(128), default="", index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    env_vars: Mapped[list["EnvVar"]] = relationship(
        back_populates="app", cascade="all, delete-orphan")
    secrets: Mapped[list["Secret"]] = relationship(
        back_populates="app", cascade="all, delete-orphan")
    deploys: Mapped[list["Deploy"]] = relationship(
        back_populates="app", cascade="all, delete-orphan",
        order_by="Deploy.id.desc()")
    domains: Mapped[list["Domain"]] = relationship(
        back_populates="app", cascade="all, delete-orphan",
        order_by="Domain.is_primary.desc(), Domain.id")
    analytics: Mapped["AppAnalytics | None"] = relationship(
        cascade="all, delete-orphan", uselist=False)
    notify: Mapped["AppNotify | None"] = relationship(
        cascade="all, delete-orphan", uselist=False)


class Domain(Base):
    __tablename__ = "domains"
    __table_args__ = (UniqueConstraint("host"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    app_id: Mapped[int] = mapped_column(ForeignKey("apps.id"))
    host: Mapped[str] = mapped_column(String(255), index=True)
    is_primary: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    app: Mapped[App] = relationship(back_populates="domains")
    cert: Mapped["DomainCert | None"] = relationship(
        cascade="all, delete-orphan", uselist=False)


class EnvVar(Base):
    __tablename__ = "env_vars"
    __table_args__ = (UniqueConstraint("app_id", "key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    app_id: Mapped[int] = mapped_column(ForeignKey("apps.id"))
    key: Mapped[str] = mapped_column(String(128))
    value: Mapped[str] = mapped_column(Text, default="")
    app: Mapped[App] = relationship(back_populates="env_vars")


class Secret(Base):
    __tablename__ = "secrets"
    __table_args__ = (UniqueConstraint("app_id", "key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    app_id: Mapped[int] = mapped_column(ForeignKey("apps.id"))
    key: Mapped[str] = mapped_column(String(128))
    value_encrypted: Mapped[str] = mapped_column(Text)  # Fernet token, never plaintext
    app: Mapped[App] = relationship(back_populates="secrets")


class Deploy(Base):
    __tablename__ = "deploys"

    id: Mapped[int] = mapped_column(primary_key=True)
    app_id: Mapped[int] = mapped_column(ForeignKey("apps.id"))
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    ref: Mapped[str] = mapped_column(String(128), default="main")
    commit: Mapped[str] = mapped_column(String(40), default="")
    log: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    app: Mapped[App] = relationship(back_populates="deploys")


class BuiltImage(Base):
    """Registry images already built+pushed for an app, keyed by full tag.

    The tag encodes every build input — git commit AND a hash of the build-args
    (NEXT_PUBLIC_*/VITE_* etc. inlined at build time) — so a deploy can skip the
    rebuild only when an image with the *identical* inputs exists. Changing a
    build-time env var yields a new tag, forcing a rebuild even at the same
    commit. Its own table (create_all never ALTERs `deploys`).
    """
    __tablename__ = "built_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    app_id: Mapped[int] = mapped_column(ForeignKey("apps.id"), index=True)
    tag: Mapped[str] = mapped_column(String(255), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    github_login: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class UptimeState(Base):
    """Current up/down state per app (kept in its own table so create_all can
    add it without altering the apps table)."""
    __tablename__ = "uptime_state"

    app_id: Mapped[int] = mapped_column(ForeignKey("apps.id"), primary_key=True)
    up: Mapped[bool | None] = mapped_column(default=None)   # None = unknown
    up_since: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_checked: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    consecutive_fail: Mapped[int] = mapped_column(default=0)


class UptimeSample(Base):
    """Periodic probe results, for uptime % and a sparkline. Pruned over time."""
    __tablename__ = "uptime_samples"

    id: Mapped[int] = mapped_column(primary_key=True)
    app_id: Mapped[int] = mapped_column(ForeignKey("apps.id"), index=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    ok: Mapped[bool] = mapped_column()


class AppAnalytics(Base):
    """Per-app analytics site token + opt-out flag (own table; no apps ALTER)."""
    __tablename__ = "app_analytics"

    app_id: Mapped[int] = mapped_column(ForeignKey("apps.id"), primary_key=True)
    token: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(default=True)


class AppNotify(Base):
    """Per-app notification recipient + recorded owner (own table; no apps ALTER)."""
    __tablename__ = "app_notify"

    app_id: Mapped[int] = mapped_column(ForeignKey("apps.id"), primary_key=True)
    owner_login: Mapped[str] = mapped_column(String(128), default="")
    notify_email: Mapped[str] = mapped_column(String(255), default="")


class DomainCert(Base):
    """Cloudflare-for-SaaS custom-hostname state for a custom domain (own table
    keyed by domain_id so create_all can add it without altering ``domains``).
    Only created for domains registered with Cloudflare; the auto-subdomain and
    domains added while Cloudflare is unconfigured have no row."""
    __tablename__ = "domain_certs"

    domain_id: Mapped[int] = mapped_column(ForeignKey("domains.id"), primary_key=True)
    cf_hostname_id: Mapped[str] = mapped_column(String(64), default="")
    ssl_status: Mapped[str] = mapped_column(String(32), default="")
    ownership_status: Mapped[str] = mapped_column(String(32), default="")
    dcv_target: Mapped[str] = mapped_column(String(255), default="")
    # Fallback TXT record Cloudflare returns when HTTP ownership validation
    # doesn't auto-pass (rare with a proxied traffic CNAME). Surfaced to the
    # customer only while ownership is still pending.
    ownership_name: Mapped[str] = mapped_column(String(255), default="")
    ownership_value: Mapped[str] = mapped_column(String(255), default="")
    last_checked: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class Hit(Base):
    """A single pageview recorded by the first-party beacon."""
    __tablename__ = "hits"

    id: Mapped[int] = mapped_column(primary_key=True)
    app_id: Mapped[int] = mapped_column(ForeignKey("apps.id"), index=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    path: Mapped[str] = mapped_column(String(512), default="/")
    referrer: Mapped[str] = mapped_column(String(512), default="")
    visitor: Mapped[str] = mapped_column(String(32), index=True)  # daily-rotated hash


class AllowedUser(Base):
    """An invited member (in addition to the env-configured admins). Admins
    manage this list from the UI; members may sign in and use the platform."""
    __tablename__ = "allowed_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    added_by: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AppRedis(Base):
    """An app's stable shared-Redis credential. The password is generated once
    and stored encrypted so the injected ``REDIS_URL`` is the same across
    redeploys. Only apps with ``redis: true`` get a row (own table; no apps
    ALTER). The ACL user on the shared instance is named ``username`` and scoped
    to the ``<app>:*`` key + channel prefix."""
    __tablename__ = "app_redis"

    app_id: Mapped[int] = mapped_column(ForeignKey("apps.id"), primary_key=True)
    username: Mapped[str] = mapped_column(String(128))
    password_encrypted: Mapped[str] = mapped_column(Text)  # Fernet token, never plaintext


class CronJob(Base):
    """A cron job declared in the app's manifest, persisted on each successful
    deploy so the scheduler can read schedules without re-cloning the repo.
    Upserted by (app_id, name); rows whose name leaves the manifest are removed."""
    __tablename__ = "cron_jobs"
    __table_args__ = (UniqueConstraint("app_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    app_id: Mapped[int] = mapped_column(ForeignKey("apps.id"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    schedule: Mapped[str] = mapped_column(String(128))  # 5-field cron, UTC
    command: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_run_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    runs: Mapped[list["CronRun"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="CronRun.id.desc()")


class CronRun(Base):
    """One launch of a cron job: status, exit code, captured output."""
    __tablename__ = "cron_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    cron_job_id: Mapped[int] = mapped_column(ForeignKey("cron_jobs.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="running", index=True)
    exit_code: Mapped[int | None] = mapped_column(default=None)
    log: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    job: Mapped[CronJob] = relationship(back_populates="runs")
