# koyracloud background tasks — workers, cron, and a shared Redis bus

**Status:** approved design · 2026-06-16
**Scope:** one spec, phased build (A → B → C)

## Problem

Today a koyracloud App is **one git repo → one built image → one HTTP service** behind
Traefik. There is no way to run an always-on background process, a scheduled job, or to
pass messages from a web app to a background consumer. This blocks any app that needs a
queue worker, a poller, a bot, or a nightly job.

## Goal

Let an app, from the **same repo and the same built image**, additionally run:

- **workers** — always-on processes with no HTTP port (queue consumers, bots, pollers),
- **cron jobs** — a command on a schedule, run to completion each tick, with run history,

and reach a **shared, per-app-isolated Redis** as the message bus between them.

Native primitives only — no Inngest, no Redpanda. Stays framework-agnostic: a worker/cron
is just another command run inside the app's image.

## Non-goals

- No durable step-functions / fan-out / retries-as-a-service (that was the Inngest path,
  explicitly declined). Retries are the app's concern atop Redis.
- No per-app Redis instance (shared instance, ACL-isolated, was chosen over per-app).
- No Redpanda/Kafka.
- No autoscaling. Workers default to 1 replica (manifest may override).

## The process model

An App's one image can back three **process types**, all sharing the image/commit, the
app's env, decrypted secrets, persist mounts, and the injected `REDIS_URL`:

| Type | Declared by | Runs as | Router? | Predeploy? |
|------|-------------|---------|---------|-----------|
| **web** (existing) | top-level `start` + `port` | one Swarm service | yes (Traefik) | yes |
| **worker** (new) | `workers:` list | one Swarm service per worker | no | no |
| **cron** (new) | `cron:` list | a Swarm run-to-completion job per tick | no | no |

Workers and cron do **not** run the web's `predeploy` (migrations belong to the web start).

## Manifest (additive — `manifest.py`)

New optional fields on `Manifest`. Existing manifests are unchanged and keep working.

```yaml
name: my-app
runtime: python
start: uvicorn app.main:app --host 0.0.0.0 --port 8000   # web (implicit), unchanged
port: 8000

redis: true            # provision a shared-Redis ACL user; inject REDIS_URL

workers:
  - name: events       # -> service koyra-my-app_my-app-events
    start: python -m app.worker
    replicas: 1        # optional, default 1
    cpu: "0.25"        # optional, falls back to instance default
    memory: "128M"     # optional

cron:
  - name: nightly
    schedule: "0 2 * * *"          # 5-field cron, UTC
    command: python -m app.jobs.nightly
```

New Pydantic models:

- `Worker { name: str, start: str, replicas: int = 1, cpu: str = "", memory: str = "" }`
- `CronJob { name: str, schedule: str, command: str }`
- `Manifest.redis: bool = False`, `Manifest.workers: list[Worker] = []`,
  `Manifest.cron: list[CronJob] = []`

**Validation** (fail the deploy with a clear message):

- worker/cron `name`: matches `^[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?$` (DNS-label, same rule
  as app names — it becomes a Swarm service-name suffix), and is **unique across the union
  of worker + cron names**, and is not the reserved word `web`.
- `start` (worker) / `command` (cron) non-empty.
- cron `schedule`: a valid 5-field cron expression, validated with `croniter`.
- A worker/cron block is allowed for any runtime (it just runs a command in the image).

## Shared Redis with per-app ACL isolation

### The instance (`deploy/koyracloud-stack.yml`)

One koyracloud-owned `redis:7` service on `traefik_public`, reachable by services as
`redis:6379`:

- AOF persistence on a Docker NFS-driver volume (`koyra_redis`, same pattern as
  `koyra_registry`) so the queue survives a reschedule.
- `--maxmemory <cap> --maxmemory-policy noeviction` so a full instance returns write
  errors (back-pressure) rather than silently evicting another app's queued messages.
- `--requirepass <admin>` from a Docker secret; the default user is the admin used only by
  the control plane to manage ACLs. Per-app users are created with scoped permissions.
- Unpinned (NFS volume), `restart_policy: on-failure`, like the registry.

New config (`config.py`): `redis_host` (`KOYRA_REDIS_HOST`, default `redis`),
`redis_port` (`KOYRA_REDIS_PORT`, default `6379`),
`redis_admin_password` (`_secret("KOYRA_REDIS_ADMIN_PASSWORD")`),
`redis_maxmemory` (`KOYRA_REDIS_MAXMEMORY`, default `256mb`).

### Per-app provisioning (`redis.py`)

A thin module wrapping the `redis` py client, with a `RedisAdmin` Protocol so tests inject a
fake (mirroring `DockerControl`).

On deploy of an app with `redis: true`:

1. Look up / create an `AppRedis` row `{app_id, username, password_encrypted}`. The username
   is `app-<name>`; the password is generated **once** and stored Fernet-encrypted, so
   `REDIS_URL` is **stable across redeploys**.
2. `ACL SETUSER app-<name> on ><password> ~<name>:* &<name>:* +@all` — the user may touch
   only keys prefixed `<name>:` and pub/sub channels prefixed `<name>:`. (`+@all` commands,
   minus the dangerous admin ones excluded by also adding `-@admin -@dangerous`.)
3. Compute `REDIS_URL = redis://app-<name>:<password>@<redis_host>:<redis_port>/0` and inject
   it into web + workers + cron environments.

When `redis: false` (or absent): no ACL, no `REDIS_URL`. On app delete: `ACL DELUSER` best-effort.

If Redis is unconfigured at the instance level (`redis_admin_password` empty) but a manifest
sets `redis: true`, the deploy **fails** with a clear message — the app asked for a bus that
the instance can't provide.

**The key-prefix contract (documented loudly):** an app with `redis: true` MUST namespace its
keys and channels as `<name>:...`; other keys are rejected by the ACL. This is the ergonomic
cost of shared-with-isolation and is called out in the README + migrating guide + the UI panel.

## Stack render (`stack_render.py`)

`render_stack` gains `redis_url: str = ""` and emits, in the same single stack:

- the **web** service (unchanged), plus `REDIS_URL` in its environment when set;
- one service per **worker**, named `<app_name>-<worker.name>`:
  - same `image`, same `environment` (incl. `REDIS_URL`), same persist volumes,
  - **no Traefik labels, no healthcheck**,
  - `command: ["sh", "-c", "<worker.start>"]` (override the image CMD; no predeploy),
  - resources from the worker's `cpu`/`memory` or the instance defaults; `replicas` from the
    worker (default 1); the same `restart_policy`/`update_config` block as web.

Cron jobs are **not** rendered into the stack — they are launched on demand by the scheduler
(below). The stack render is still a pure function and is unit-tested.

`deployer.py` computes `redis_url` (via `redis.py`) before calling `render_stack`, after the
ACL user is ensured, and passes it through. It also **persists the manifest's cron jobs** to
the DB on a successful deploy (upsert by `(app_id, name)`, delete rows whose names are no
longer in the manifest) so the scheduler can read them without re-cloning.

## Cron scheduler (`scheduler.py`)

A background loop modeled on `monitor.UptimeMonitor`:

- `due_jobs(db, now)` — **pure** w.r.t. time: returns `[(cron_job_id, app, job)]` for jobs
  whose `croniter` next-fire after `last_run_at` (or after `created_at` if never run) is `<= now`,
  **excluding** jobs whose previous `CronRun` is still `running` (skip-if-running overlap policy).
- `launch(db, docker, settings, crypto, cron_job_id)`:
  1. resolve the app's **current live image** from its latest `Deploy` with `status == "live"`
     (`{registry}/koyra-app-<name>:<commit[:12]>`); if there is none, skip (nothing deployed yet).
  2. create a `CronRun(status="running", started_at=now)`.
  3. launch a Swarm **run-to-completion job**: `docker service create --mode replicated-job
     --restart-condition none --name koyra-cron-<app>-<job>-<run_id>` with the image, env +
     secrets + `REDIS_URL` + persist mounts, `sh -c "<command>"`.
  4. poll the job to completion (bounded by a timeout), collect exit code + `service logs`,
     `service rm` it, and update the `CronRun` to `success`/`failed` with `exit_code`, `log`,
     `finished_at`. Set the job's `last_run_at`.
- `CronScheduler.run` ticks every `cron_tick_seconds` (default 30), each tick try/except-wrapped
  so one bad job never kills the loop (same discipline as the uptime monitor).

New `DockerControl` methods (with CLI impls + fakes):

- `run_job(name, image, command, env, volumes, ...) -> None` — `service create --mode
  replicated-job --restart-condition none ...` (detached).
- `job_wait(name, timeout) -> int` — poll `service ps`/`inspect` until the task reaches a
  terminal state; return its exit code (or raise on timeout).
- `remove_service(name) -> None` — `service rm`.

`launch` is also the **manual-trigger** path (`POST …/cron/{job}/run`), so "run now" reuses it.

Time zone: schedules are **UTC** (documented). `last_run_at` records the tick that fired.

## Data model (`models.py`) — all own-table, no `apps` ALTER

Matches the existing pattern (`UptimeState`, `AppAnalytics`, … each in its own table keyed by
`app_id` so `create_all` adds them without altering `apps`).

```python
class AppRedis(Base):                 # stable per-app Redis credential
    app_id: int (pk, fk apps.id)
    username: str
    password_encrypted: str           # Fernet token

class CronJob(Base):                  # manifest-derived, persisted each deploy
    id: int (pk)
    app_id: int (fk apps.id, index)
    name: str
    schedule: str
    command: str (Text)
    enabled: bool = True
    last_run_at: datetime | None
    __table_args__ = (UniqueConstraint("app_id", "name"),)

class CronRun(Base):                  # one row per launch
    id: int (pk)
    cron_job_id: int (fk cron_jobs.id, index)
    status: str                       # running | success | failed
    exit_code: int | None
    log: str (Text) = ""
    started_at: datetime
    finished_at: datetime | None
```

Workers need **no** DB rows — they are services re-rendered each deploy; their status/logs come
from Docker, exactly like the web service.

## API + UI

### API (`app.py`, `schemas.py`, `api.js`)

App detail responses gain, derived from the live deploy's manifest + the DB:

- `redis: bool` (whether the app provisions Redis),
- `workers: [{name, replicas, running, desired}]` (status via `docker.service_status` on
  `koyra-<app>_<app>-<worker>`),
- `cron: [{id, name, schedule, command, enabled, last_run_at, last_status}]`.

New routes (owner/admin-scoped via the existing `get_app_or_404`):

- `GET /api/apps/{id}/cron` → list cron jobs + recent runs summary.
- `GET /api/apps/{id}/cron/{job_id}/runs` → run history (latest N).
- `GET /api/cron-runs/{run_id}/log` → a single run's captured log.
- `POST /api/apps/{id}/cron/{job_id}/run` → manual trigger (schedules `launch` off-thread),
  returns the new `CronRun`.
- `GET /api/apps/{id}/workers/{worker}/logs?tail=` → `docker.service_logs` of the worker
  service (reuses the existing runtime-logs plumbing).

The scheduler is started in `create_app` under `run_async` (like the uptime monitor), gated by
`cron_enabled` (`KOYRA_CRON_ENABLED`, default on).

### UI (`AppDetail.jsx`)

Three additions to the app page:

- **Workers** — table: name, replicas (running/desired), a logs button (reuses the runtime-log
  viewer pattern).
- **Cron** — table: name, schedule, last-run status + time, **Run now** button; expanding a job
  shows recent runs with per-run status/exit-code and a log view.
- **Redis** — a small panel: enabled/disabled, the `<name>:` key-prefix contract, and a note
  that `REDIS_URL` is injected (the password is never shown).

## Error handling

- Manifest validation errors → deploy fails with the message (existing pattern).
- `redis: true` but instance Redis unconfigured, or ACL provisioning fails → deploy **fails**
  (the app expects `REDIS_URL`).
- Cron launch/poll failure → `CronRun(status="failed", log=<error>)`; the scheduler continues.
- Job overrun (previous run still `running`) → skipped silently for that tick (no row).
- Scheduler tick wrapped in try/except so a single bad job can't kill the loop.

## Testing

Pure-function unit tests (mirroring the existing `test_units.py` for `stack_render`/`manifest`):

- **manifest**: workers/cron/redis parse; name uniqueness across workers∪cron; reserved `web`;
  bad cron expression; non-empty start/command.
- **stack_render**: worker services have no router/healthcheck, carry `REDIS_URL` + persist +
  command override; per-worker replicas/resources; web carries `REDIS_URL`; redis-off omits it.
- **redis**: `REDIS_URL` computation; ACL spec string for a user (`~<name>:* &<name>:* …`);
  stable password across calls (reuses the stored row).
- **scheduler**: `due_jobs` fires at/after the cron time, respects `last_run_at`, skips
  running jobs; `launch` over a `FakeDocker` records a `CronRun` with the right status/exit;
  resolves the live image (and skips when none).

API tests (`test_api.py`, over `FakeDocker` + a fake `RedisAdmin`):

- a deploy of a manifest with workers renders extra services + injects `REDIS_URL` (ACL
  provisioned on the fake); cron jobs persisted to the DB.
- `POST …/cron/{job}/run` launches via the fake and records a run; run/log endpoints return it.
- ownership isolation on the new routes.

`FakeDocker` gains `run_job` / `job_wait` / `remove_service`; conftest gains a `FakeRedisAdmin`
and wires it into the `Deployer`/scheduler.

## Build phasing (for the plan)

- **Phase A — workers.** Manifest `workers:`, `render_stack` worker services, deploy renders
  them, API/UI worker status + logs. No Redis, no cron. Smallest shippable slice.
- **Phase B — shared Redis.** Instance service in the stack, `redis.py` + `AppRedis`, deploy
  provisions the ACL + injects `REDIS_URL` into all process types, UI Redis panel, docs.
- **Phase C — cron.** `CronJob`/`CronRun` models, deploy persists jobs, `scheduler.py` +
  Docker job methods, API run history + manual trigger, UI cron section.

Each phase is independently deployable and independently tested.

## New dependencies

- `redis` (py client) — ACL provisioning + URL.
- `croniter` — schedule validation + next-fire computation.

Both are small, pure-Python-friendly, and added to the control-plane requirements.

## Docs

- README: a "Background workers, cron & Redis" section with the manifest example.
- `docs/MIGRATING-FROM-VERCEL.md`: note the equivalents (Vercel cron → `cron:`; a separate
  worker → `workers:`).
- `examples/`: extend the example manifest (or add one) showing a worker + cron + redis with
  the `<name>:` key-prefix contract.
