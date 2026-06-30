"""Periodic consistent backup of the SQLite control-plane DB to NFS, pruned to
the last N. Postgres deployments use their own backup tooling (skipped here).

CLI (run while the control-plane is stopped):
    python -m koyracloud.backup list                 # show available snapshots
    python -m koyracloud.backup restore              # restore the newest snapshot
    python -m koyracloud.backup restore <file.db>    # restore a specific snapshot
DB path comes from $DB_URL, snapshot dir from $KOYRA_BACKUP_DIR (else <db>/backups).
"""
from __future__ import annotations

import datetime as dt
import os
import shutil
import sqlite3
import sys
import threading
from pathlib import Path


def sqlite_file(db_url: str) -> Path | None:
    prefix = "sqlite:///"
    return Path(db_url[len(prefix):]) if db_url.startswith(prefix) else None


def backup_dir_for(db_file: Path, configured: str = "") -> Path:
    """Resolve the snapshot directory: KOYRA_BACKUP_DIR if set, else <db>/backups."""
    return Path(configured) if configured else db_file.parent / "backups"


def latest_backup(backup_dir: Path) -> Path | None:
    backups = sorted(backup_dir.glob("koyracloud-*.db"))
    return backups[-1] if backups else None


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


def restore(db_file: Path, src: Path) -> None:
    """Overwrite the live DB with a snapshot. Run while the control-plane is
    stopped — copies the snapshot over the DB and drops any stale WAL/SHM
    sidecars so SQLite doesn't replay a half-written log over restored data."""
    if not src.exists():
        raise FileNotFoundError(src)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, db_file)
    for sidecar in (db_file.with_name(db_file.name + "-wal"),
                    db_file.with_name(db_file.name + "-shm")):
        sidecar.unlink(missing_ok=True)


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


def _main(argv: list[str]) -> int:
    db_file = sqlite_file(os.environ.get("DB_URL", ""))
    if db_file is None:
        print("DB_URL is not a sqlite URL; nothing to restore", file=sys.stderr)
        return 2
    bdir = backup_dir_for(db_file, os.environ.get("KOYRA_BACKUP_DIR", ""))
    cmd = argv[0] if argv else "list"

    if cmd == "list":
        snaps = sorted(bdir.glob("koyracloud-*.db"))
        if not snaps:
            print(f"no snapshots in {bdir}")
            return 1
        for s in snaps:
            print(f"{s}  ({s.stat().st_size} bytes)")
        return 0

    if cmd == "restore":
        src = Path(argv[1]) if len(argv) > 1 else latest_backup(bdir)
        if src is None:
            print(f"no snapshots in {bdir}", file=sys.stderr)
            return 1
        restore(db_file, src)
        print(f"restored {src} -> {db_file}")
        return 0

    print("usage: python -m koyracloud.backup [list|restore [file]]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
