# Deploy status: only the serving deploy is "live"

**Date:** 2026-06-18
**Status:** Approved — ready for implementation plan

## Problem

The deploy-history table on an app's detail page renders **every** past
successful deploy with the green "live" badge. Only the most recent deploy
actually serves traffic — each deploy is a Swarm rolling replace of a single
service (the running container is swapped, not added alongside), so older
deploys are no longer live.

### Root cause

A `Deploy` row stores a `status` string (`models.py:17`,
`DEPLOY_STATUSES`). When a deploy succeeds, the deployer sets that row to
`"live"` (`deployer.py:348`) but **never demotes the previously-live row**.
An app therefore accumulates many rows stuck at `"live"`, and
`DeployHistory` (`web/src/pages/AppDetail.jsx:274`) faithfully renders each
one's stored status through `StatusBadge`.

The status field is genuinely wrong on the old rows — not merely a display
preference. The fix is to make the data correct; the UI is already
data-driven and follows automatically.

## Decision

- **Fix location:** the stored data. When a deploy goes live, atomically
  demote the app's prior live row(s) so the `status` field stays truthful for
  every consumer (API, future queries, the badge).
- **New status value:** `"superseded"` — distinct from the existing (unused)
  `"rolled_back"`, and reads as "a newer deploy took over."

## Design

### 1. New status value — `models.py`

Add `"superseded"` to `DEPLOY_STATUSES`:

```python
DEPLOY_STATUSES = ("pending", "building", "deploying", "live",
                   "failed", "rolled_back", "superseded")
```

### 2. Demote on go-live (core fix) — `deployer.py`

At the live transition (currently `emit("[koyra] deploy complete — live",
"live")`, `deployer.py:348`), demote prior live rows **in the same
transaction** as marking the new row live, so there is never a window with
two live rows or zero live rows:

```python
# Only the newest live deploy actually serves traffic — each deploy
# replaces the running container — so demote any prior live row for the
# app in the same transaction that marks this one live.
with db.session() as s:
    s.execute(text("UPDATE deploys SET status = 'superseded' "
                   "WHERE app_id = :a AND status = 'live' AND id != :i"),
              {"a": app_id, "i": deploy_id})
    s.execute(text("UPDATE deploys SET log = COALESCE(log, '') || :l, "
                   "status = 'live' WHERE id = :i"),
              {"l": "[koyra] deploy complete — live\n", "i": deploy_id})
    s.commit()
```

Both statements are blind `UPDATE`s (no `SELECT`), so they avoid the SQLite
WAL read→write upgrade deadlock that the `emit` helper's comment warns about.
The newest row is never touched (`id != :i`), and only `live` rows are
demoted — so a **failed** deploy, which never reaches this transition,
correctly leaves the prior live deploy serving.

### 3. Backfill existing data — `db.py:_migrate()`

`_migrate()` already exists for idempotent lightweight migrations that run on
startup. Add a guarded statement so production history is corrected
immediately on deploy (not only after each app's next deploy):

```python
if "deploys" in insp.get_table_names():
    with self.engine.begin() as conn:
        conn.execute(text(
            "UPDATE deploys SET status = 'superseded' "
            "WHERE status = 'live' AND id NOT IN ("
            "  SELECT MAX(id) FROM deploys WHERE status = 'live' "
            "  GROUP BY app_id)"))
```

Idempotent: once each app has a single live row, re-running is a no-op. The
SQL is standard and runs on both SQLite (default) and Postgres.

### 4. Terminal set — `app.py`

Add `"superseded"` to `TERMINAL` (`app.py:37`) so the live-log SSE stream
(`app.py:896`) closes cleanly if a deploy being watched is superseded by a
concurrent deploy mid-stream.

```python
TERMINAL = {"live", "failed", "rolled_back", "superseded"}
```

### 5. Badge — `web/src/pages/AppsList.jsx`

Add one entry to the `STATUS` map so the new status renders as a dim,
de-emphasized badge (vs the acid-green of live):

```js
superseded: ["#5a6070", "superseded"],
```

**No change** to `DeployHistory` / `AppDetail.jsx` — it already renders each
row's `status` through `StatusBadge`, so once the backend stores
`"superseded"` the table picks it up automatically.

## Out of scope / unaffected (verified)

- `latest_status = deploys[0].status` (`app.py:371`) reads the **newest** row,
  which stays `"live"` — the per-app list/header badge is unchanged.
- `_redeploy_if_live` (`app.py:111`) uses `any(d.status == "live")`, still
  true for the single remaining live row.
- Same-commit redeploy and failed-deploy paths are untouched — demotion only
  ever affects *older* `live` rows.
- `RuntimePill` (live replica count) is independent of deploy-row status.

## Testing (TDD)

1. **Supersede on new deploy** (`tests/test_api.py`): trigger two synchronous
   deploys on one app; assert the first row flips to `"superseded"` and the
   second is `"live"`.
2. **Backfill** (`tests/test_api.py` or `tests/test_units.py`): insert two
   `"live"` deploy rows for one app directly, run `_migrate()`, assert only
   the newest stays `"live"` and the older becomes `"superseded"`.
