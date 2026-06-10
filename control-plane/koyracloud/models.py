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


class Domain(Base):
    __tablename__ = "domains"
    __table_args__ = (UniqueConstraint("host"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    app_id: Mapped[int] = mapped_column(ForeignKey("apps.id"))
    host: Mapped[str] = mapped_column(String(255), index=True)
    is_primary: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    app: Mapped[App] = relationship(back_populates="domains")


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
