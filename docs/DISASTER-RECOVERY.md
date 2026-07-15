# Disaster recovery (SQLite control-plane)

The control-plane state — apps, domains, deploys, secrets, cron jobs — lives in
one SQLite file, `DB_URL=sqlite:////data/koyracloud.db`. `/data` is a host
volume (`KOYRA_DB_DIR`, local disk on the control node), so it **survives
container crashes and redeploys** (the data is not in the container). You only
need a restore when the file itself is lost or corrupted, or the volume dies.

**The DB must live on local disk, not NFS.** SQLite runs in WAL mode, which is
unsupported on network filesystems — the `-shm` sidecar needs real
shared-memory mmap semantics — so on NFS, concurrent writers hit intermittent
`database is locked` failures (#67). Backups are the NFS's job, not the live
file.

> Running Postgres (`DB_URL=postgresql://…`) instead? This doc doesn't apply —
> use your Postgres backup/PITR tooling.

## What protects you

A `BackupLoop` takes a consistent online snapshot every `KOYRA_BACKUP_INTERVAL_HOURS`
(default 12) and keeps the newest `KOYRA_BACKUP_KEEP` (default 14) in
`KOYRA_BACKUP_DIR` (default `/data/backups`, i.e. **the same volume as the DB**).

**Do this:** point `KOYRA_BACKUP_DIR` at a *different* mount (another disk, or an
NFS export backed elsewhere) so one volume failure can't take the DB and every
backup with it. Same-volume backups only protect against corruption/`rm`, not
volume loss.

## Restore

The control-plane must be **stopped** during a restore (offline file swap).

```bash
# 1. stop the service (frees the DB file; snapshots keep their own copy)
docker --context <ctx> service scale koyracloud_control-plane=0

# 2. on the control node, mount the DB dir + the NFS backup dir, list and
#    restore the newest snapshot
docker run --rm -v /var/lib/koyracloud:/data -v /mnt/koyracloud/cp/backups:/backups \
  -e DB_URL=sqlite:////data/koyracloud.db -e KOYRA_BACKUP_DIR=/backups \
  <koyra-image> python -m koyracloud.backup list
docker run --rm -v /var/lib/koyracloud:/data -v /mnt/koyracloud/cp/backups:/backups \
  -e DB_URL=sqlite:////data/koyracloud.db -e KOYRA_BACKUP_DIR=/backups \
  <koyra-image> python -m koyracloud.backup restore   # newest, or: restore <path>

# 3. bring it back
docker --context <ctx> service scale koyracloud_control-plane=1
```

`restore` copies the snapshot over `koyracloud.db` and deletes any stale
`-wal`/`-shm` sidecars so SQLite doesn't replay a half-written log over the
restored data. Then the health-gated `start-first` rollout brings the API back
once `/api/health` answers.

## Moving the DB off NFS

Installs that predate `KOYRA_DB_DIR` have the DB on the NFS export
(`<KOYRA_NFS_BASE>/cp`). Migrate it to the control node's local disk:

```bash
# 0. in deploy/koyracloud.env, set:
#      KOYRA_DB_DIR=/var/lib/koyracloud
#      KOYRA_BACKUP_DIR=<KOYRA_NFS_BASE>/cp/backups   # backups stay on NFS
#    and create the dir on the control node:
ssh <control-node> sudo mkdir -p /var/lib/koyracloud

# 1. stop the control plane so nothing writes the DB during the copy
docker --context <ctx> service scale koyracloud_control-plane=0

# 2. on the control node, copy with SQLite's .backup — NOT cp. .backup takes a
#    consistent snapshot and folds the pending -wal into the copy; a plain cp
#    of the bare .db silently drops committed transactions still in the WAL.
#    Do NOT copy koyracloud.db-shm / koyracloud.db-wal alongside — a restored
#    sidecar pair from another filesystem is exactly what corrupts a WAL db.
ssh <control-node> "sqlite3 <KOYRA_NFS_BASE>/cp/koyracloud.db \
  '.backup /var/lib/koyracloud/koyracloud.db'"

# 3. redeploy the stack with the new env (also scales the service back up)
bash deploy/deploy.sh

# 4. verify: /api/health answers, then run a test deploy and watch its log
#    stream in the UI
curl -fsS https://<KOYRA_HOST>/api/health

# 5. once happy, the old NFS copy at <KOYRA_NFS_BASE>/cp/koyracloud.db* is a
#    fallback — leave it for a few days, then delete it (keep backups/).
```

## Full rebuild from scratch

If the box is gone, redeploy the stack (`deploy/deploy.sh`) onto a fresh node
with the same secrets, restore the latest off-volume snapshot into the new
`/data`, then scale up. The deploy-time `create_all`/migrations are idempotent,
so an empty or restored DB both boot cleanly.

## Bigger durability (when you outgrow this)

SQLite + nightly off-volume snapshots is fine for a single-node homelab. When
you want point-in-time recovery or multi-node HA, switch `DB_URL` to Postgres —
the app already supports it (the SQLite-only backup loop just no-ops).
