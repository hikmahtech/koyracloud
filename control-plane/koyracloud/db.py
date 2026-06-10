"""SQLAlchemy engine/session wiring. SQLite by default, Postgres via DB_URL."""
from __future__ import annotations

from sqlalchemy import create_engine
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

    def session(self) -> Session:
        return self._factory()
