"""Periodic consistent backup of the SQLite control-plane DB to NFS, pruned to
the last N. Postgres deployments use their own backup tooling (skipped here)."""
from __future__ import annotations

import datetime as dt
import sqlite3
import threading
from pathlib import Path


def sqlite_file(db_url: str) -> Path | None:
    prefix = "sqlite:///"
    return Path(db_url[len(prefix):]) if db_url.startswith(prefix) else None


def backup_once(db_file: Path, backup_dir: Path, keep: int,
                stamp: str | None = None) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = stamp or dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = backup_dir / f"koyracloud-{stamp}.db"
    src = sqlite3.connect(str(db_file))
    dst = sqlite3.connect(str(dest))
    try:
        with dst:
            src.backup(dst)   # online, consistent snapshot
    finally:
        src.close()
        dst.close()
    backups = sorted(backup_dir.glob("koyracloud-*.db"))
    for old in backups[:-keep] if keep > 0 else []:
        old.unlink(missing_ok=True)
    return dest


class BackupLoop:
    def __init__(self, db_file: Path, backup_dir: Path, interval_s: int, keep: int):
        self.db_file = db_file
        self.backup_dir = backup_dir
        self.interval_s = interval_s
        self.keep = keep
        self._stop = threading.Event()

    def run(self):
        while not self._stop.is_set():
            try:
                backup_once(self.db_file, self.backup_dir, self.keep)
            except Exception:  # noqa: BLE001 — never let backup kill the loop
                pass
            self._stop.wait(self.interval_s)

    def start(self):
        threading.Thread(target=self.run, daemon=True).start()
