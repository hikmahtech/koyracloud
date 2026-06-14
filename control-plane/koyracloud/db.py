"""SQLAlchemy engine/session wiring. SQLite by default, Postgres via DB_URL."""
from __future__ import annotations

import secrets

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(self, db_url: str):
        connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}
        self.engine = create_engine(db_url, connect_args=connect_args, future=True)
        self._factory = sessionmaker(self.engine, expire_on_commit=False,
                                     class_=Session, future=True)

    def create_all(self) -> None:
        # Import models so they register on Base.metadata before create_all.
        from koyracloud import models  # noqa: F401
        Base.metadata.create_all(self.engine)
        self._migrate()

    def _migrate(self) -> None:
        """Idempotent lightweight migrations for columns added after release
        (create_all only creates missing tables, never alters existing ones)."""
        insp = inspect(self.engine)
        if "apps" not in insp.get_table_names():
            return
        cols = {c["name"] for c in insp.get_columns("apps")}
        # apps gained a random subdomain_token (default-URL uniqueness) after
        # release; add it and backfill a token for every existing app.
        if "subdomain_token" not in cols:
            with self.engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE apps ADD COLUMN subdomain_token VARCHAR(16) DEFAULT ''"))
                ids = [r[0] for r in conn.execute(text("SELECT id FROM apps")).all()]
                for app_id in ids:
                    conn.execute(
                        text("UPDATE apps SET subdomain_token = :t WHERE id = :i"),
                        {"t": secrets.token_hex(3), "i": app_id})
        if "owner_login" not in cols:
            with self.engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE apps ADD COLUMN owner_login VARCHAR(128) DEFAULT ''"))
                # backfill ownership from the recorded notify owner where known
                if "app_notify" in insp.get_table_names():
                    conn.execute(text(
                        "UPDATE apps SET owner_login = COALESCE("
                        "(SELECT owner_login FROM app_notify WHERE app_notify.app_id = apps.id), '')"
                        " WHERE owner_login = '' OR owner_login IS NULL"))

        # domain_certs gained ownership_verification columns after its release.
        if "domain_certs" in insp.get_table_names():
            dc_cols = {c["name"] for c in insp.get_columns("domain_certs")}
            for col in ("ownership_name", "ownership_value"):
                if col not in dc_cols:
                    with self.engine.begin() as conn:
                        conn.execute(text(
                            f"ALTER TABLE domain_certs ADD COLUMN {col} VARCHAR(255) DEFAULT ''"))

    def session(self) -> Session:
        return self._factory()
