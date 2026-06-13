"""Database models for the control plane's own state."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from koyracloud.db import Base


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# Deploy lifecycle states.
DEPLOY_STATUSES = ("pending", "building", "deploying", "live", "failed", "rolled_back")


class App(Base):
    __tablename__ = "apps"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    repo_url: Mapped[str] = mapped_column(String(512))
    branch: Mapped[str] = mapped_column(String(128), default="main")
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
