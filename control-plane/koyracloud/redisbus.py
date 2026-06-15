"""Shared-Redis provisioning: one koyracloud-owned Redis instance, isolated per
app with an ACL user scoped to a ``<app>:*`` key + channel prefix.

The pure helpers (``acl_setuser_args``, ``redis_url``) are unit-tested. A
``RedisAdmin`` Protocol lets tests inject a fake instead of a live Redis, the
same way ``DockerControl`` is faked.
"""
from __future__ import annotations

import secrets
from typing import Protocol

from koyracloud.config import Settings
from koyracloud.crypto import CryptoBox
from koyracloud.db import Database
from koyracloud.models import AppRedis


def acl_setuser_args(username: str, password: str, prefix: str) -> list[str]:
    """Args after ``ACL SETUSER <username>`` that create/replace a per-app user:
    enabled, this password only, access limited to keys and pub/sub channels
    under ``<prefix>:``, all commands EXCEPT the dangerous/admin ones (so an app
    can't FLUSHALL the shared instance or read another app's keyspace)."""
    return [
        "reset",                 # start from a clean, no-access user
        "on",
        f">{password}",
        f"~{prefix}:*",          # keys under <prefix>:
        f"&{prefix}:*",          # pub/sub channels under <prefix>:
        "+@all",
        "-@dangerous",
        "-@admin",
    ]


def redis_url(username: str, password: str, host: str, port: int, db: int = 0) -> str:
    return f"redis://{username}:{password}@{host}:{port}/{db}"


class RedisAdmin(Protocol):
    def set_user(self, username: str, password: str, prefix: str) -> None:
        """Create/replace the scoped ACL user. Raises on failure."""

    def delete_user(self, username: str) -> None:
        """Drop the ACL user (best-effort teardown)."""


class RedisClientAdmin:
    """Live implementation against the shared Redis, authenticated as the admin
    (``default``) user. The client is created lazily so importing this module
    never opens a connection (tests + unconfigured instances stay inert)."""

    def __init__(self, host: str, port: int, admin_password: str):
        self._host, self._port, self._admin = host, port, admin_password
        self._client = None

    def _conn(self):
        if self._client is None:
            import redis  # local import: only needed when actually provisioning
            self._client = redis.Redis(
                host=self._host, port=self._port, username="default",
                password=self._admin, socket_timeout=5, decode_responses=True)
        return self._client

    def set_user(self, username: str, password: str, prefix: str) -> None:
        self._conn().execute_command(
            "ACL", "SETUSER", username, *acl_setuser_args(username, password, prefix))

    def delete_user(self, username: str) -> None:
        self._conn().execute_command("ACL", "DELUSER", username)


def provision(db: Database, crypto: CryptoBox, settings: Settings,
              admin: RedisAdmin, app_id: int, app_name: str) -> str:
    """Ensure the app's scoped ACL user exists and return its stable REDIS_URL.

    The password is generated once and stored encrypted, so the URL is identical
    across redeploys. Raises if the instance has no admin password configured —
    the app asked for a bus the instance can't provide."""
    if not settings.redis_admin_password:
        raise RuntimeError(
            "manifest sets `redis: true` but this koyracloud instance has no "
            "Redis configured (KOYRA_REDIS_ADMIN_PASSWORD is unset)")
    username = f"app-{app_name}"
    with db.session() as s:
        row = s.get(AppRedis, app_id)
        if row is None:
            password = secrets.token_urlsafe(24)
            row = AppRedis(app_id=app_id, username=username,
                           password_encrypted=crypto.encrypt(password))
            s.add(row)
            s.commit()
        else:
            password = crypto.decrypt(row.password_encrypted)
            if row.username != username:   # app renamed: keep the URL in sync
                row.username = username
                s.commit()
    # The key/channel prefix is the app name (the contract surfaced to authors).
    admin.set_user(username, password, app_name)
    return redis_url(username, password, settings.redis_host, settings.redis_port)


def deprovision(db: Database, admin: RedisAdmin, app_id: int) -> None:
    """Drop the app's ACL user + stored credential (best-effort)."""
    with db.session() as s:
        row = s.get(AppRedis, app_id)
        if row is None:
            return
        username = row.username
        s.delete(row)
        s.commit()
    try:
        admin.delete_user(username)
    except Exception:  # noqa: BLE001 — teardown is best-effort
        pass
