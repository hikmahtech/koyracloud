# Disaster recovery (SQLite control-plane)

The control-plane state — apps, domains, deploys, secrets, cron jobs — lives in
one SQLite file, `DB_URL=sqlite:////data/koyracloud.db`. `/data` is a host/NFS
volume, so it **survives container crashes and redeploys** (the data is not in
the container). You only need a restore when the file itself is lost or
corrupted, or the volume dies.

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

# 2. from a container/host that mounts /data, list and restore the newest snapshot
docker run --rm -v /mnt/koyracloud/cp:/data -e DB_URL=sqlite:////data/koyracloud.db \
  -e KOYRA_BACKUP_DIR=/data/backups <koyra-image> \
  python -m koyracloud.backup list
docker run --rm -v /mnt/koyracloud/cp:/data -e DB_URL=sqlite:////data/koyracloud.db \
  -e KOYRA_BACKUP_DIR=/data/backups <koyra-image> \
  python -m koyracloud.backup restore                 # newest, or: restore <path>

# 3. bring it back
docker --context <ctx> service scale koyracloud_control-plane=1
```

`restore` copies the snapshot over `koyracloud.db` and deletes any stale
`-wal`/`-shm` sidecars so SQLite doesn't replay a half-written log over the
restored data. Then the health-gated `start-first` rollout brings the API back
once `/api/health` answers.

## Full rebuild from scratch

If the box is gone, redeploy the stack (`deploy/deploy.sh`) onto a fresh node
with the same secrets, restore the latest off-volume snapshot into the new
`/data`, then scale up. The deploy-time `create_all`/migrations are idempotent,
so an empty or restored DB both boot cleanly.

## Bigger durability (when you outgrow this)

SQLite + nightly off-volume snapshots is fine for a single-node homelab. When
you want point-in-time recovery or multi-node HA, switch `DB_URL` to Postgres —
the app already supports it (the SQLite-only backup loop just no-ops).
