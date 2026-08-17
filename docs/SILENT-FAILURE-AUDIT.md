<!-- Point-in-time audit. Snapshot of commit 4c9ab1a, 17 August 2026. -->
# koyracloud silent-failure audit

A control-plane restart quietly switches parts of koyracloud off, and the homelab's power fault schedules a restart every few weeks. That is the audit's most important result. Four findings share the trigger: a restart during a cron run wedges that job forever (C1); a restart during a deploy leaves a stuck row that then blocks webhook re-delivery (C2); a Redis restart drops the app ACL users while `koyracloud_redis_up` stays 1 (B2, issue #88's mechanism plus the metric that denied it for three days); and after a power event the backup loop can write snapshots under an unmounted NFS mountpoint while recording nothing at all (A4). A4 is the single worst finding: backups can fail for months with no log line, no metric and no DB row, and `restore` copies a snapshot over the live database without ever opening it. Everything else in this report is recoverable. That one is not.

Scope: commit 4c9ab1a, four agents, disjoint slices. 42 raw findings merged to 33 unique, plus 4 adjacent items that are not silent failures but worth filing. Several findings were reproduced by running the real code; those are marked. Eight findings were reached independently by more than one agent. Three agents separately found B1, where a failed `docker service ls` renders the whole fleet offline; treat that convergence as a severity signal. The calibration set was the four known bugs (PRs #82 and #83 fixed, issues #86 and #88 open), and the audit found new instances of every one of their shapes.

## Tracking

Every finding below is filed. Fix them against the issue, not against this file: this
document is a point-in-time snapshot of the audit and is not updated as work lands.

| Issue | Covers |
|-------|--------|
| [#89](https://github.com/hikmahtech/koyracloud/issues/89) | A4 — backups leave no evidence; restore does not validate |
| [#90](https://github.com/hikmahtech/koyracloud/issues/90) | C1, C2, B2 — the startup reconciler. Finishes [#88](https://github.com/hikmahtech/koyracloud/issues/88) |
| [#91](https://github.com/hikmahtech/koyracloud/issues/91) | B1 — `docker service ls` failure renders the fleet offline |
| [#92](https://github.com/hikmahtech/koyracloud/issues/92) | A1, F1 — swallowed API errors, and the env-var wipe they enable |
| [#93](https://github.com/hikmahtech/koyracloud/issues/93) | A2 — misspelled manifest keys prune what they configure |
| [#94](https://github.com/hikmahtech/koyracloud/issues/94) | E1, E2 — stale base image, and secrets that never reach the build |
| [#95](https://github.com/hikmahtech/koyracloud/issues/95) | A5 — empty session secret allows a forged admin cookie |
| [#96](https://github.com/hikmahtech/koyracloud/issues/96) | `DeployTrigger.ref` argument injection |
| [#97](https://github.com/hikmahtech/koyracloud/issues/97) | D1, D2, D3 — alerting fails open |
| [#98](https://github.com/hikmahtech/koyracloud/issues/98) | A3 — delete returns 204 while the app keeps serving |
| [#99](https://github.com/hikmahtech/koyracloud/issues/99) | C4, E3, E4, F4, F5, F6, F7 — endpoints reporting work they did not do |
| [#100](https://github.com/hikmahtech/koyracloud/issues/100) | B3, B4, C3, G1 — probes vouching for the wrong thing |
| [#101](https://github.com/hikmahtech/koyracloud/issues/101) | H1, H2 — wrong bytes with a 200 |
| [#102](https://github.com/hikmahtech/koyracloud/issues/102) | I1, I2, I3 — docs and installer drift |
| [#103](https://github.com/hikmahtech/koyracloud/issues/103) | F2, F3 — log panes that lie |
| [#104](https://github.com/hikmahtech/koyracloud/issues/104) | `tasks[:6]` breaks convergence above 6 replicas |
| [#105](https://github.com/hikmahtech/koyracloud/issues/105) | CI leaves the swarm private key on the runner |

The root cause for [#86](https://github.com/hikmahtech/koyracloud/issues/86) is in that
issue's comments: the cron timeout path reads `exc.stdout` and never `exc.stderr`.

One item is not filed: `scheduler.launch` (`scheduler.py:79-83`) picks the highest-id
`BuiltImage` matching the live commit prefix, which can differ from the live deploy's
`args_hash` when the same commit was built twice with different build args. Low impact,
noted here so nobody re-derives it.

## The eight shapes

The individual bugs matter less than the mechanisms behind them. Fixing a finding without fixing its shape invites the next instance; three of the four calibration bugs already have new siblings below.

1. **The error path and the empty path produce the same bytes.** A failed lookup returns the exact value that means "nothing exists": `{}`, `[]`, `None`, `""`. Everything downstream then renders an authoritative empty state. Instances: B1 (`service ls` failure becomes "no services"; its sibling `service inspect` collapses "daemon unreachable" into `{"exists": false}`), A1 (a failed env GET renders an empty editor), G1 (every Cloudflare failure returns `None`; `dcv_uuid()` returns `""`), F2 (an empty log renders as "loading…"). Calibration bugs #1 and #3 were both this shape.

2. **Best-effort actions leave no record.** An action that exists to be seen runs inside `except Exception: pass`, and neither success nor failure is written anywhere. Afterwards, "never fired", "fired and failed" and "fired fine" are identical. Instances: A4 (backup loop), D1 (failure webhook), D2 (email result discarded by every caller), A3 (delete teardown), A5 (`_secret` swallows the file-read error), G1 (no logging in the whole module).

3. **Restart amnesia.** In-flight or in-memory state has no startup reconciler, so a restart switches a subsystem off and nothing notices. Instances: C1 (a `running` CronRun excludes the job forever), C2 (a non-terminal Deploy then blocks webhook re-delivery), A5 (ephemeral Fernet key), B2 and issue #88 (Redis ACL users). The power fault makes this shape scheduled, not hypothetical.

4. **The success response is decided before the work.** The 2xx is a constant, or is computed without checking that anything matched or happened. Instances: C4 (`{"launched": true}` is a fixed literal), F5 (204 for an unmatched delete), A3 (204 after a swallowed teardown), D3 and F6 (204 while storing the opposite of what was asked), F4 (200 with `[]` after a successful write), B4 (`/api/health` returns a constant).

5. **A key omits one of its inputs.** A cache or dedup key misses a dimension that changes the output, so a real change fails to invalidate. Instances: E1 (the image tag omits the base image), C2 (the webhook dedup matches an arbitrarily old orphan row), E4 (the hash includes build args the Dockerfile drops), and the `scheduler.launch` image pick (adjacent list). Calibration bug #2 lived here.

6. **Parsers that never say no.** Raw `dict` bodies, models without `extra="forbid"`, coercion instead of rejection. A typo parses clean, becomes a default, and the default drives a destructive action. Instances: A2 (a misspelled manifest key prunes workers, crons and volumes), D3 (any JSON object wipes the alert address), F6 (`bool("false")` is true), E3 (`secrets:` validates and does nothing), E4 (untrimmed env keys), DeployTrigger.ref (adjacent list).

7. **Green probes that vouch for the wrong thing.** A health signal authenticates or measures a path that stays healthy through the outage it exists to catch. Instances: B2 (pings as the `default` user, whose password survives the restart that kills the ACL users), B3 (any non-5xx counts as up, including Traefik's own 404), B4 (the healthcheck touches nothing the rollback is meant to protect), H1 (the uptime monitor sees 200 for wrong bytes).

8. **The client already has the error and throws it away.** `web/src/api.js:17-21` attaches the API's error detail on every non-2xx. Nine `AppDetail.jsx` call sites discard it, and `LiveLogs` closes its stream on the first error instead of reconnecting. Instances: F1, F3, A1. `NewApp.jsx`, `Team.jsx` and DomainsTab already render the error correctly, so the fix pattern exists in the repo.

## All findings at a glance

| ID | Finding | Severity | Found by | Issue |
|----|---------|----------|----------|-------|
| A1 | Env editor wipes every var after a failed read | HIGH | | #92 |
| A2 | Misspelled manifest key prunes workers/crons/volumes on a green deploy | HIGH | | #93 |
| A3 | `DELETE /api/apps/{id}` returns 204 while the app keeps serving | HIGH | | #98 |
| A4 | Backups produce no evidence of success or failure, ever | HIGH | | #89 |
| A5 | Empty session secret / Fernet key boots clean; forgeable admin cookie | HIGH impact, MEDIUM likelihood | | #95 |
| B1 | `docker service ls` failure renders every app "offline" | HIGH | 3 agents | #91 |
| B2 | `koyracloud_redis_up` stays 1 during the ACL-loss outage (#88) | HIGH | | #90 |
| B3 | Uptime prober counts Traefik's 404 as "up" | MEDIUM | | #100 |
| B4 | Control-plane healthcheck is a constant; rollback can't trigger | MEDIUM | | #100 |
| C1 | Restart during a cron run wedges that job forever | HIGH | | #90 |
| C2 | Orphaned deploys stay non-terminal, then block webhook re-delivery | MEDIUM | 2 agents | #90 |
| C3 | Cron jobs with no live deploy no-op every tick, invisibly | MEDIUM | | #100 |
| C4 | "Run now" always answers `{"launched": true}` | MEDIUM | 2 agents | #99 |
| D1 | Deploy-failure webhook: response unchecked, nothing logged | MEDIUM-HIGH | 2 agents | #97 |
| D2 | Email alert failures discarded; UI still says "configured" | MEDIUM | 2 agents | #97 |
| D3 | `PUT .../notify` with a wrong key silently wipes the alert address | MEDIUM | | #97 |
| E1 | New runtime base image never reaches apps; log says "reusing the image" | HIGH | 2 agents | #94 |
| E2 | Secret used as build-time env never reaches the build; README says it does | HIGH | 2 agents | #94 |
| E3 | `secrets:` in the manifest is a no-op | MEDIUM | | #99 |
| E4 | Invalid build-arg keys dropped but still hashed (PR #83's shape, again) | MEDIUM-LOW | | #99 |
| F1 | Every dashboard save/action swallows its API error | HIGH | | #92 |
| F2 | An empty log renders as a permanent "loading…" | MEDIUM | | #103 |
| F3 | The live deploy log freezes silently | MEDIUM | | #103 |
| F4 | `PUT .../env` returns `[]` after successfully writing the vars | MEDIUM | | #99 |
| F5 | Deleting a non-existent secret or member returns 204 | MEDIUM / LOW-MEDIUM | | #99 |
| F6 | `PUT .../analytics` coerces bad input; missing key defaults to enabled | MEDIUM-LOW | | #99 |
| F7 | SPA catch-all answers 200 + HTML for unknown `/api/...` GETs | MEDIUM-LOW | | #99 |
| G1 | Every Cloudflare API failure is silent; UI then shows wrong instructions | MEDIUM | 2 agents | #100 |
| H1 | Static server: no trailing-slash redirect; missing assets served as 200 HTML | MEDIUM | | #101 |
| H2 | Analytics injection deletes non-UTF-8 bytes from served HTML | LOW | | #101 |
| I1 | MONITORING.md says no auto-deploy; CI deploys on every merge | MEDIUM-HIGH | | #102 |
| I2 | `KOYRA_APPS_DOMAIN` placeholder never validated by install.sh | LOW-MEDIUM | | #102 |
| I3 | Editing the apex Caddyfile without bumping the config version deploys nothing | LOW | | #102 |

The four "found by 2/3 agents" rows deserve weight. The slices were disjoint, so two agents reaching the same defect means it is visible from unrelated directions. C4 was found from both sides of its boundary: api/data found the API lying, runtime/ops found the scheduler doing nothing.

## Group A — Data loss and destructive silence

What to do across this group: destructive paths must refuse to act on unverified input, and the backup loop must leave evidence.

### A1. The env editor destroys env vars after a failed read  ·  #92

- **Where:** `web/src/main.jsx:13-15` (`retry: false`) + `web/src/pages/AppDetail.jsx:594-600` (`EnvEditor`); server side `control-plane/koyracloud/app.py:658` (`put_env`).
- **What happens:** a failed GET renders as an authoritative empty editor; saving from it wipes every var. A session cookie expires or one GET 500s. `GET /apps/{id}/env` fails, the query defaults to `[]`, and only `isLoading` is checked, so the editor renders blank with no error. The operator concludes the vars were lost, retypes the two they remember, hits Save. `put_env` does `obj.env_vars.clear()` then writes only the submitted list. Every other var is permanently deleted, and the UI then displays the truncated list as truth. The app breaks on its next deploy. A second path to the same clobber: clicking "+ add variable" before the GET resolves seeds `rows` from `[]`.
- **Severity:** HIGH. Irreversible data loss reachable from a plain 401, no confirmation step.
- **Fix:** surface `isError` on every list query and block the editor when its GET failed. Do not let `EnvEditor` submit off an unsuccessful read.

### A2. A misspelled manifest key prunes the thing it was configuring  ·  #93

- **Where:** `control-plane/koyracloud/manifest.py:96` (`class Manifest`, no `extra="forbid"`), via `deployer.py:411`.
- **What happens:** a typo parses clean and yields a default; the deploy then removes the real thing and reports `live`. Write `worker:` for `workers:` (or `crons:`, `persists:`, `healtcheck:`): `docker stack deploy --prune` (`docker_ctl.py:108`, unconditional) deletes the worker services; `_sync_cron_jobs` (`deployer.py:245-247`) deletes the CronJob rows and their run history; the web service loses its `volumes:` mount and starts writing into the container layer instead of the NFS volume. `_wait_converged` only waits on services derived from `manifest.workers`, so an empty list means nothing is left to notice.
- **Evidence:** verified against the real parser. `workers: []  cron: []  persist: []  healthcheck: ''`, all typos accepted. A nested `replica:` typo silently gives 1 replica when 5 were asked for. The repo already has the right warning in `cli.py:48` (`_unknown_top_level_keys`), but it is gated behind `--strict` on an opt-in local CLI and the control plane never calls it.
- **Severity:** HIGH. Silent data loss and silent removal of background work, on a green deploy.
- **Fix:** `model_config = ConfigDict(extra="forbid")` on `Manifest`/`Worker`/`CronJob`, or have `_run_deploy` call the existing `_unknown_top_level_keys` and emit a warning per unknown key.

### A3. `DELETE /api/apps/{id}` returns 204 while the app keeps serving traffic  ·  #98

- **Where:** `control-plane/koyracloud/app.py:624` (`delete_app`), swallow at `:639-648`.
- **What happens:** the DB row is deleted and committed first, then teardown runs inside `try: ... except Exception: pass`. Any teardown failure still returns 204. If the docker daemon is unreachable, the node was demoted, or `stack rm` half-fails, `_stream` raises (`docker_ctl.py:69-70`), the error is swallowed, and the app vanishes from the dashboard while `https://<app>.<apps_domain>` keeps answering. The Redis ACL user survives too, still scoped to `<app>:*`. Because the row went first, nothing is left to reconcile against: the orphan stack is now invisible to koyracloud.
- **Severity:** HIGH. A deleted app that keeps serving is a security surprise with no record.
- **Fix:** tear down before deleting the row. On failure return 409/207 with the docker error, or park the app as `status=deleting` so a retry is possible.

### A4. Backups produce no evidence of success or failure, ever  ·  #89

- **Where:** `control-plane/koyracloud/backup.py:76` (`BackupLoop.run`).
- **What happens:** the loop swallows every exception and records nothing. No log line, no DB row, no metric. A control plane whose backups have failed for months is indistinguishable from one whose backups are perfect. Concrete trigger: the stack bind-mounts the host's NFS base (`deploy/koyracloud-stack.yml:96`). After a power event the host's NFS mount is not restored, so `${KOYRA_NFS_BASE}` is an empty local dir; `mkdir(parents=True, exist_ok=True)` succeeds and snapshots land under an unmounted mountpoint, invisible after remount. Equally reachable via `database is locked`, a full disk, or a permission error. Discovered at restore time.
- **Also:** `restore` (`backup.py:55`) copies the snapshot over the live DB and prints "restored ..." without ever opening it. A truncated snapshot from a killed backup restores "successfully" over the good data.
- **Severity:** HIGH. Silent loss of the only copy of all platform state. The power fault makes the trigger routine, not hypothetical.
- **Fix:** persist `last_backup_at`/`last_error`, export `koyracloud_backup_age_seconds`, and `stat()` the written file so a 0-byte cycle fails. Open the snapshot before restoring over the live DB.

### A5. No boot-time validation of the session secret or the Fernet key  ·  #95

- **Where:** `control-plane/koyracloud/config.py:25-34` (`_secret`), `:43-45`; `crypto.py:20-26`; `app.py:66`.
- **What happens (reproduced):** a control plane with no signing key and no encryption key boots, logs nothing, and looks healthy. `.env.example` ships `KOYRA_SECRET_KEY=` and `KOYRA_SESSION_SECRET=` empty; an env var present but empty beats the default, so `session_secret` is `''`. `itsdangerous` accepts an empty key, so anyone who knows a login in `KOYRA_ALLOWED_LOGINS` (a public GitHub username) can forge a valid admin cookie. When the var is unset instead, the fallback is the hardcoded public constant `"dev-session-secret-change-me"` from this repo: same outcome. Separately, `CryptoBox.__init__` generates a throwaway Fernet key and sets `ephemeral=True`; `crypto.py:16` says "the caller is expected to warn" and `create_app` never reads the flag. Existing secrets become undecryptable and new ones die at restart.
- **Also:** `_secret` swallows `OSError` on the `<NAME>_FILE` read (`config.py:31-32`) and returns the default with no log, so a secret mapping lost by a hand `docker service update` degrades silently.
- **Reach:** `deploy/install.sh` refuses to create empty secrets, so the supported path is guarded. This bites self-hosters who wire the container up themselves, which for an open-source PaaS is a first-class path.
- **Severity:** HIGH impact, MEDIUM likelihood. Full auth bypass with zero signal.
- **Fix:** fail fast in `create_app` when `session_secret` is empty or equals the dev constant and `dev_login` is unset. Refuse to start (or warn loudly) when `crypto.ephemeral` and the DB already holds `Secret` rows. Log at WARNING on the `_secret` OSError branch.

## Group B — Health and status signals that lie

What to do across this group: give every probe a distinct error state, and make it touch the thing it vouches for.

### B1. `docker service ls` failing makes every app read "offline" — found independently by 3 agents  ·  #91

- **Where:** `control-plane/koyracloud/docker_ctl.py:164-188` (`services_overview`); consumed at `app.py:605` (`apps_status`) and `app.py:864` (`_worker_status`); rendered at `web/src/pages/AppsList.jsx:35-46` (`RunningDot`) and `web/src/pages/AppDetail.jsx:99`.
- **What happens:** the exit code of `docker service ls` is never checked. A failed call yields `{}`, indistinguishable from "no services exist", and it is cached for 5 seconds. When the docker daemon restarts, the socket briefly 403s, or the node is demoted from manager, `service ls` exits 1 with "Cannot connect to the Docker daemon" on stderr, which is discarded. Empty stdout becomes `{}` becomes cached. The dashboard renders every app "offline" and each app detail "· not deployed" while every app runs normally. The Background tab is worse: `_worker_status` filters an empty dict and returns `[]`, so the app displays as having no workers at all, and that view has no error state. The operator's natural next move is to redeploy things that were fine.
- **Second trigger:** the same function has `timeout=15` and no try/except, and its own comment notes that during a deploy `service ls` crawls toward its timeout. A `TimeoutExpired` propagates, `/api/apps/status` 500s, the client's `status` stays `{}`, and again everything renders offline on a 30s poll.
- **Same conflation:** `docker_ctl.py:133-135`: `service inspect` returning non-zero yields `{"exists": False}`, so "daemon unreachable" and "service does not exist" produce byte-identical output.
- **Severity:** HIGH. This is calibration bug #1's exact shape, and it fires during an incident or a deploy, precisely when the operator is trusting the dashboard.
- **Fix:** return a distinct error on non-zero exit and do not cache it. Render a third "unknown" state (grey dot, "—") rather than fabricating "offline" or zero workers.

### B2. `koyracloud_redis_up` reports 1 during exactly the outage it exists to catch  ·  #90

- **Where:** `control-plane/koyracloud/app.py:194` (`_redis_ping`), consumed at `metrics.py:90`.
- **What happens:** the probe authenticates as Redis's `default` user, whose password comes from `--requirepass` on the command line and always survives a restart. The per-app ACL users (`ACL SETUSER`, memory-only, no `--aclfile`) do not. Issue #88 verbatim: Redis restarts, all app ACL users vanish, Swarm shows every service `1/1`, and `/metrics` publishes `koyracloud_redis_up 1`. Three days of total breakage with the health signal pinned green.
- **Evidence:** `deploy/koyracloud-stack.yml:172` runs `redis-server --requirepass ... --appendonly yes` with no `--aclfile`. `redisbus.provision` is called only from `deployer._run_deploy:512`.
- **Severity:** HIGH. The metric does not cause the outage, it denies it. That is what turned #88 into three days.
- **Fix:** ping as a real app ACL user (or `ACL GETUSER` each provisioned username), export `koyracloud_redis_acl_users_missing`, and re-provision from `AppRedis` on startup.

### B3. The uptime prober counts any non-5xx as "up", including Traefik's own 404  ·  #100

- **Where:** `control-plane/koyracloud/monitor.py:24` (`http_prober`).
- **What happens:** "up" means "some server answered with < 500", and on this platform the answering server is Traefik, which returns 404 when no router matches the Host. If the app's swarm stack is removed or pruned out from under the control plane (issue #81 shows stack/app-row drift is real here) while the `App` row and its live `Deploy` remain, DNS still resolves to the tunnel, Traefik answers 404, and `r.status_code < 500` is true. The app shows green at 100% 24h uptime with `koyracloud_app_up 1` and no down email. Contrast: a running app whose replicas are all dead gets a 503 and is correctly reported down. It is precisely the "app has vanished entirely" case that reads as healthy.
- **Severity:** MEDIUM. Narrow trigger, but the platform's primary health signal is inverted when it hits.
- **Fix:** treat 404 as down when the app declares a `healthcheck` path, or cross-check `services_overview()` (already called for the dashboard) before recording `ok=True`. Store the status code on the sample.

### B4. Control-plane healthcheck cannot fail while the app is broken  ·  #100

- **Where:** `deploy/koyracloud-stack.yml:13-18` and `:130-132` vs `control-plane/koyracloud/app.py:187-189`.
- **What happens:** the probe fetches `/api/health`, which is `return {"status": "ok"}`: a constant that touches no DB, no docker socket, nothing. The stack's `update_config: {order: start-first, failure_action: rollback}` therefore promises an automatic rollback that only triggers on "uvicorn didn't bind a port". An image that boots fine but cannot use the docker socket or its DB dir (permissions, full disk, wrong `KOYRA_DB_DIR`) passes the healthcheck; swarm shifts traffic, marks the service `1/1` healthy, no rollback fires, and every deploy and dashboard call 500s behind a green service.
- **Note:** `/metrics` is the only DB-touching probe and it is opt-in (`KOYRA_MONITORING=1` plus an external Prometheus), so a default self-host has no signal that can go red.
- **Severity:** MEDIUM. The misleading part is the documented rollback guarantee.
- **Fix:** have `/api/health` do a `SELECT 1` and a cached `docker info` so the probe covers what the rollback is meant to protect.

## Group C — Work that stops happening, and never says so

What to do across this group: a startup pass that closes interrupted work, and a row for every skipped or launched run.

### C1. A control-plane restart during a cron run wedges that job forever  ·  #90

- **Where:** `control-plane/koyracloud/scheduler.py:43` (`due_jobs`); run opened at `:96`, closed at `:113`.
- **What happens:** `due_jobs` skips any job with a `CronRun` at `status="running"`, with no age limit and no startup reaper. If the process dies mid-run, the job is permanently excluded from every future tick while the UI shows it enabled, scheduled and "running". The window is the whole job duration, because the run is committed before `docker.run_job` starts and closed after it returns. For an hourly job that times out at 600s, that is about 17% of the clock. Any redeploy, OOM kill or power event inside the window wedges the job. Afterwards the Background tab shows the schedule, a "running" badge and a `last_run_at` that keeps ageing. No failed run, no alert, no log line. "Run now" still works (`launch` never consults the running check), so a manual test succeeds and reinforces the impression that the job is fine.
- **Evidence:** `grep -rn '"running"'` finds only the model default, these two scheduler sites, and unrelated replica counts. Nothing reaps stale rows; `Database._migrate` never touches `cron_runs`.
- **Severity:** HIGH. One restart permanently and invisibly disables a cron job, and the failure mode is "nothing ever happens again". Given the power fault, this is a when, not an if.
- **Fix:** at startup mark every `running` CronRun as `failed` with "interrupted by restart". Also treat a run older than `cron_job_timeout` plus slack as not-running in `due_jobs`.

### C2. Deploys orphaned by a restart stay non-terminal forever, then block re-delivery — 2 agents  ·  #90

- **Where:** `control-plane/koyracloud/app.py:74` (`schedule`, daemon thread), rows at `:314`/`:945`, dedup at `:310`, SSE at `:969`; `deployer.py:600-607`.
- **What happens:** deploy workers are daemon threads with no startup reconciler, so the interpreter exits without running `_run_deploy`'s `finally`. The row stays `pending`/`building`/`deploying` with `finished_at` NULL, permanently. A push creates the row, the webhook returns `{"triggered": ["myapp"]}`, GitHub records a green delivery, and the control plane restarts mid-build. The UI shows a deploy stuck at "building"; the SSE stream never sees a terminal status and spins forever, each open tab pinning a server thread polling SQLite every 0.5s. The operator redelivers the webhook from GitHub to retry and gets `{"triggered": []}`, because the dedup check `latest.commit == sha and latest.status != "failed"` matches the orphan. Nothing runs, and nothing explains why.
- **Evidence:** `TERMINAL = {"live","failed","rolled_back","superseded"}` (`app.py:41`) is used only by the log stream. `_migrate` demotes stale `live` rows but leaves the non-terminal ones. The stuck row also permanently inflates the deploy-status gauge (`metrics.py:70`).
- **Severity:** MEDIUM. Recoverable via the UI, but push-to-deploy silently drops the deploy and then silently refuses the retry.
- **Fix:** on startup fail every non-terminal Deploy with "interrupted by a control-plane restart". Scope the webhook dedup to rows younger than the converge timeout.

### C3. Cron jobs on an app with no live deploy no-op every tick, forever  ·  #100

- **Where:** `control-plane/koyracloud/scheduler.py:71` (`launch`).
- **What happens:** `launch` returns `None` before creating any CronRun and without touching `last_run_at`. The job is due again 30s later, spawns another thread, does nothing again. Identical in the UI to a job that has never come due. Reachable on any new app whose manifest declares cron: `_sync_cron_jobs` (`deployer.py:519`) writes the CronJob rows before the stack deploy, so a first deploy that fails to converge leaves the jobs persisted with no live deploy. The Background tab lists the job (name, schedule, command, enabled) with no badge and no last run, exactly as it looks five minutes after a successful deploy.
- **Evidence:** `tests/test_background.py:164` locks in the silent return but asserts nothing about visibility.
- **Severity:** MEDIUM. A cron job the operator believes is scheduled will never run and will never say so.
- **Fix:** record a `skipped` CronRun (or a per-job `last_skip_reason`) and surface it in `/background`.

### C4. `POST .../cron/{job}/run` always answers `{"launched": true}` — 2 agents, from both sides  ·  #99

- **Where:** `control-plane/koyracloud/app.py:926` (`cron_run_now`), thread launch at `:81-86`.
- **What happens (reproduced):** the 202 body is a fixed literal, returned regardless of what `scheduler.launch` did, and in production before the thread has done anything. For a job whose app has no live deploy: `POST .../cron/1/run` gives `202 {'launched': True}`, then `CronRun rows: 0`, `docker jobs launched: []`. The user clicks "Run now", gets a success toast, opens the run history, and sees nothing new. Second path: `launch` builds env with `crypto.decrypt(...)` (`scheduler.py:84`) before inserting the CronRun row and outside the try, so a secret that fails to decrypt kills the daemon thread with a stderr traceback and zero DB rows.
- **Severity:** MEDIUM. Indistinguishable from a job that ran and produced nothing.
- **Fix:** create the CronRun row synchronously in the endpoint (status `queued`) and return its id so the UI can poll it.

## Group D — Alerting that fails open

What to do across this group: write one line per notification attempt with its result, and validate the config writes. Alerting that fails open is worse than none, because it is trusted.

### D1. The deploy-failure webhook never checks its response and never logs — 2 agents  ·  #97

- **Where:** `control-plane/koyracloud/deployer.py:212-228` (`_post_failure_webhook`), called at `:596`.
- **What happens:** `httpx.post` has no `raise_for_status()` and the whole call sits in `except Exception: pass`. Nothing is written to the deploy log: not the attempt, not the outcome. An app sets `notify.on_failure: https://hooks.slack.com/workflows/...` and the workflow is later revoked (404), or the URL is a typo, or the receiver 500s. httpx does not raise on 4xx/5xx, so the function returns normally. The deploy page shows `[koyra] FAILED: ...` exactly as it would if the webhook had delivered. The on-call channel goes quiet and everyone assumes there were no failures.
- **Evidence:** `tests/test_background.py:434` asserts only that `httpx.post` was called with the right body. It never exercises a non-2xx or an exception.
- **Severity:** MEDIUM-HIGH. The feature exists solely to make failures loud (issue #61), and it fails quietly.
- **Fix:** keep the `except`, but `emit` one line either way: `[koyra] notify.on_failure → 404`.

### D2. Email alerts are one-shot, their failure is discarded, and the UI still says "configured" — 2 agents  ·  #97

- **Where:** `control-plane/koyracloud/notifier.py:50` (`send_email`), fired from `app.py:88` (`notify_event`), `monitor.py:112`, `deployer.py:205` (`_fire`); status reported at `app.py:822`.
- **What happens:** `send_email` returns `False` on a non-2xx or any exception; every caller discards it and nothing is logged. `GET /api/apps/{id}/notify` reports `email_configured: true` based only on the API key string being non-empty. Rotate the Resend key, let the sending domain's DNS lapse, or hit a rate limit, and every send 401/403/422s. Deploy-failure and down alerts stop arriving permanently. The server log shows `[koyra:uptime] app 7 -> down`, proof the platform detected the outage, with no hint the email died. The operator concludes the app never went down.
- **Compounding:** `monitor.check_once` commits the state transition before notifying (`monitor.py:74`), so a lost "down" alert can never be retried. `st.up` is already `False` and the transition cannot fire again.
- **Severity:** MEDIUM.
- **Fix:** log the Resend status/body, count `koyracloud_notifications_failed_total`, record `last_notify_error` on `AppNotify`, and base `email_configured` on the last send result rather than the key being set.

### D3. `PUT /api/apps/{id}/notify` with a wrong or absent key silently wipes the alert address  ·  #97

- **Where:** `control-plane/koyracloud/app.py:825` (`set_notify`).
- **What happens (reproduced):** the handler takes `body: dict`, so any JSON object is accepted. `PUT {'email': 'new@x.com'}` returns 204 and the stored address becomes `''`. Same for `{}`, `{"notifyEmail": ...}`, `{"notify_email": null}`. `notify_event` then falls back to `settings.default_notify_email`, which the shipped stack leaves empty, so alerting goes fully dark with a success response. The web UI sends the right key, so this bites API and script clients.
- **Severity:** MEDIUM. Quietly disables the only alerting channel for an app.
- **Fix:** a pydantic model with a required `notify_email: str`; a missing key becomes 422.

## Group E — Builds that go green while delivering the wrong thing

What to do across this group: put every build input in the cache key, and warn whenever a declared input is dropped.

### E1. A new runtime base image never reaches apps, and the log says "reusing the image" — 2 agents, 3 mechanisms  ·  #94

- **Where:** `control-plane/koyracloud/deployer.py:470-483` (`args_hash` / `already_built`); `docker_ctl.py:75-82` (`image_build`); `deploy/deploy.sh:30-34`.
- **Mechanism 1, the cache key:** the image cache key is `<commit12>-<sha256(build_args)>` and omits the base image entirely. `runtime_image` defaults to the mutable tag `127.0.0.1:5000/koyracloud-runtime:latest` (`config.py:52`); `render_dockerfile` puts it in the `FROM`, but it appears nowhere in the tag. The reuse check is a pure DB lookup on `BuiltImage.tag` with no registry or digest verification. The log reads `already in the registry → reusing the image (no rebuild)`, the deploy goes live in seconds, and the container still runs the old base.
- **Mechanism 2, no `--pull`:** `image_build` builds `["build", "-t", tag]` with no `--pull`, so even on the rebuild path `FROM ...:latest` resolves against the build node's local cache. That cache is stale whenever the runtime image was pushed from a different machine, which is the workflow `deploy/README.md:57` documents.
- **Mechanism 3, `deploy.sh` never rebuilds it:** the documented "ship a code change" path (`deploy/deploy.sh:30-34`) builds only `control-plane/Dockerfile`. `install.sh:140-147` builds the runtime image; `deploy.sh` does not.
- **Concrete scenario:** an operator reads the CHANGELOG for PR #76 ("static server sends real 404s + security headers"), runs `git pull && deploy/deploy.sh`, sees the new UI, and redeploys a static app. The app still soft-404s and still ships no `X-Content-Type-Options`. The deploy is green. Same shape for a patched Node or OpenSSL base.
- **Evidence:** every doc mentions rebuilding the runtime image only for a missing image (`pull access denied`, #66); no doc covers a stale one, and the README has no upgrade section.
- **Severity:** HIGH. Platform and security updates to the base image silently do not land, and the log asserts the opposite.
- **Fix:** fold the resolved base-image digest into `args_hash`, pass `--pull` on `docker build`, and have `deploy.sh` rebuild and push the runtime image, or warn when its digest differs from `runtime-image/`.

### E2. Build-time env set as a secret never reaches the build, and the README says it does — 2 agents  ·  #94

- **Where:** `control-plane/koyracloud/deployer.py:438` (`build_args = {**manifest.env, **env_overrides}`); `README.md:58`.
- **What happens:** secrets are deliberately excluded from build args, but nothing warns when a secret's key is one of the build-time-inlined prefixes the whole mechanism exists for. An operator stores `VITE_SUPABASE_ANON_KEY` or `NEXT_PUBLIC_STRIPE_KEY` as a secret. It looks like a key, and `README.md:58` says `secrets: [SECRET_KEY]  # values set in the UI, injected at build + run`. Vite replaces the missing `import.meta.env.VITE_*` with `undefined` without erroring; the build passes, the healthcheck returns 200, the deploy is `live`, and the app is broken in the browser only.
- **Why the existing safety net misses it:** `build_hints.py:24` (`_missing_public_build_arg`) fires only on `"Failed to collect page data"`, a Next.js build-failure signature. It cannot fire here, because nothing failed.
- **Doc drift:** `README.md:58` contradicts `README.md:104`, the Features list, and `web/src/pages/Docs.jsx:160-161`, which all state the correct run-time-only behaviour. This is PR #83's failure shape re-introduced by a doc comment.
- **Severity:** HIGH. A green deploy ships a broken client bundle, and the documentation steers operators into it.
- **Fix:** emit a warning when any secret key matches `^(VITE_|NEXT_PUBLIC_|REACT_APP_|PUBLIC_)`; fix the README line.

### E3. `secrets:` in the manifest is a no-op  ·  #99

- **Where:** `control-plane/koyracloud/manifest.py:120` (`secrets: list[str]`); only reader is `cli.py:63`.
- **What happens:** the field parses and validates, but nothing requires, checks or injects the named secrets. Manifest says `secrets: [DATABASE_URL]` (verbatim from `README.md:70`) and the operator forgets to set the value in the UI. `render_stack` injects only the secrets that exist in the DB, so the container starts without it. If the app tolerates that at import and fails on first request, the deploy converges and reports `live`; `koyra validate` prints `secrets: 1` and exits 0.
- **Evidence:** grepping `manifest.secrets` across the whole control plane returns exactly one hit, the CLI's summary line. `docs/MIGRATING-FROM-VERCEL.md:122` presents the field as meaningful.
- **Severity:** MEDIUM. A declared contract that is never enforced, with output implying it was.
- **Fix:** diff `manifest.secrets` against the resolved secret keys in `_run_deploy` and fail, or warn per missing name.

### E4. Build-arg keys that are not valid identifiers are dropped but still hashed  ·  #99

- **Where:** `control-plane/koyracloud/dockerfile.py:34-39` (`_arg_lines`); `docker_ctl.py:78-79`; `deployer.py:470`.
- **What happens:** `_arg_lines` correctly filters keys failing `^[A-Za-z_][A-Za-z0-9_]*$` (the Dockerfile-injection defence from PR #83), but `image_build` still passes `--build-arg` for them and `args_hash` still includes them. Changing such a value forces a visible full rebuild that still does not deliver the value: PR #83's misleading confirmation signal, recurring. Concrete path: an operator pastes a line from a `.env` and the key carries a trailing space (`"VITE_API_URL "`). `EnvVarIn` has no key validation (`schemas.py:78-80`), `put_env` stores it verbatim, and the UI only filters falsy keys (`AppDetail.jsx:598`, no `trim()`). The var appears correctly in the env tab and is set at runtime, but is absent from the client bundle. Editing it produces a new tag and a genuine multi-minute rebuild, confirming to the operator that the change took effect.
- **Severity:** MEDIUM-LOW. Narrower reach than PR #83, same misleading signal, on a path with no input validation at any layer.
- **Fix:** apply the `_ARG_NAME` filter once in `_run_deploy` before computing `args_hash` and calling `image_build`, and emit a warning naming each dropped key. Strip keys in `EnvVarIn`.

## Group F — The dashboard tells the operator things that are not true

What to do across this group: render the errors the client already receives, and return 404/422 where the API currently fabricates success.

### F1. Every dashboard save/action swallows its API error  ·  #92

- **Where:** `web/src/pages/AppDetail.jsx`: NotifyCard save (651), SettingsTab save (682), EnvEditor (597), SecretsEditor (623-624), deployMut/rollbackMut (34-41), AnalyticsTab (128), DomainsTab (500-502), CronRow run (421).
- **What happens:** no mutation's `isError` is rendered. The button returns from "Saving…" to "Save" and the input keeps the typed value, so a rejected write is visually identical to a successful one. Two exact 4xx paths verified:
  - **Email alerts.** `PUT .../notify` 422s on `_EMAIL_RE` (`app.py:42,828`). The input is `type="email"` but Save is a plain `onClick`, not a form submit, so HTML5 validation never runs, and HTML5 accepts dotless domains anyway. Type `ops@internal`, click Save, the field still shows it. The operator believes alerts are on.
  - **Branch.** `PATCH /api/apps/{id}` 422s on `_SAFE_REF` (`schemas.py:10,31`) for an empty field or `feat/new thing`. The one PATCH carries `{branch, auto_deploy, pinned}` together, so a bad branch also silently discards the Auto-deploy and Pin-to-node toggles just flipped. The checkboxes stay checked from local state and push-to-deploy is simply off.
  - **Deploy button.** `POST .../deploys` can 404 or 500 (`database is locked`, the documented #67 condition). Click Deploy, nothing happens, no message, no new row.
- **Evidence:** the codebase already knows how. `NewApp.jsx:53`, `Team.jsx:73` and DomainsTab (`AppDetail.jsx:546`) render `mut.error?.response?.data?.detail`, and `api.js:17-21` attaches it on every non-2xx. It is available at all nine call sites and thrown away.
- **Severity:** HIGH. Silently-unsaved alerting config and auto-deploy settings are exactly what nobody discovers until the incident they were meant to catch.
- **Fix:** a shared `<MutError mut={...}/>` next to each button; make the notify Save a real form submit.

### F2. An empty log renders as a permanent "loading…"  ·  #103

- **Where:** `web/src/pages/AppDetail.jsx:230` (RuntimeLogs), `:413` (WorkerLogs), `:486` (CronRunLog).
- **What happens:** `{data?.logs || "loading…"}` means a successful response whose log is `""` is indistinguishable from a request in flight. A cron run that produced no output returns `{"log": ""}` (`app.py:924`) with the run badge showing `failed / exit 1` directly above, and the log pane says "loading…" forever. The operator waits for output that will never render instead of reading "the job wrote nothing". Same shape as issue #86, now on the UI side. The runtime-logs pane also keeps advancing its "updated <time>" header while the body says "loading…".
- **Severity:** MEDIUM. Hides the diagnostic signal in the one place an operator goes to debug.
- **Fix:** `data ? (data.log || "(no output)") : "loading…"` in all three.

### F3. The live deploy log freezes silently  ·  #103

- **Where:** `web/src/pages/AppDetail.jsx:236-247` (`LiveLogs`).
- **What happens:** `es.onerror = () => es.close()` overrides EventSource's built-in reconnect. On any transient error the stream closes permanently, the pane keeps its partial output with no notice, `done` never arrives, and `onDone` never fires, so the header StatusBadge and the deploy list stay stale. The operator's laptop sleeps or wifi blips during a build; the log stops mid-line and sits there. The deploy may have succeeded, failed, or still be running, and the pane gives no way to tell, while the header badge still shows the previous deploy's status.
- **Compounding:** `stream_deploy_logs` (`app.py:964-985`) only yields when new bytes appear, no heartbeat frames, so a long silent step (`pip install`, the converge wait) leaves the connection idle and eligible for any proxy idle-timeout.
- **Severity:** MEDIUM. Misleads during the highest-attention moment.
- **Fix:** let EventSource reconnect, show "connection lost — reconnecting", and emit a periodic `: keepalive` comment from `gen()`.

### F4. `PUT /api/apps/{id}/env` returns an empty list after successfully writing the vars  ·  #99

- **Where:** `control-plane/koyracloud/app.py:658` (`put_env`).
- **What happens (reproduced):** `PUT [{FOO:1},{BAR:2}]` returns `200 []`, then `GET` returns `[BAR, FOO]`. `obj.env_vars.clear()` empties the loaded collection; the replacements are added as standalone `EnvVar(app_id=...)` rows that never populate the reverse collection, and `expire_on_commit=False` means the commit does not refresh it. The docs and the koyracloud-deploy skill both describe this endpoint as read-modify-write ("REPLACES the whole list; never drop keys"), so a client that trusts the PUT response concludes the app has zero env vars, and the next read-modify-write built on that wipes everything.
- **Why nobody noticed:** the web UI ignores the body and refetches. `test_api.py:60-63` PUTs then GETs separately, so it never covers the PUT body.
- **Severity:** MEDIUM. The documented contract lies, and the lie is data-destructive if believed.
- **Fix:** re-query `EnvVar` by `app_id` for the response, or append through the relationship.

### F5. Deleting a non-existent secret or member returns 204 "deleted"  ·  #99

- **Where:** `control-plane/koyracloud/app.py:689` (`delete_secret`), `:397` (`remove_allowed_user`).
- **What happens (reproduced):** both are `if <found>:` with no `else`, then an unconditional 204. `DELETE /secrets/api_key` (case mismatch) returns 204 and the key is still present and still injected at every deploy. `DELETE /allowed-users/octocatt` (typo) returns 204 and the person keeps platform access. The second is an access-revocation path: an operator revoking someone over the API gets a success and the person keeps their session and their apps. Because `current_login` re-checks `access_allowed` on every request, a real removal takes effect immediately, which makes the false success more convincing, not less.
- **Severity:** MEDIUM for the member path, LOW-MEDIUM for secrets.
- **Fix:** 404 when no row matched.

### F6. `PUT /api/apps/{id}/analytics` coerces bad input and defaults a missing key to enabled  ·  #99

- **Where:** `control-plane/koyracloud/app.py:849` (`set_analytics`).
- **What happens (reproduced):** `body: dict`, then `bool(body.get("enabled", True))`. `PUT {"enabled": "false"}` returns 204, still enabled (`bool("false")` is True). `PUT {"enable": false}` returns 204, still enabled (missing key defaults to True). Someone opting an app out of first-party analytics over the API keeps collecting visitor hashes for that site.
- **Severity:** MEDIUM-LOW. API and script clients only, but the failure direction is "keeps collecting", which is privacy-relevant.
- **Fix:** pydantic model with a required `enabled: bool`.

### F7. The SPA catch-all answers 200 + HTML for any unknown `/api/...` GET  ·  #99

- **Where:** `control-plane/koyracloud/app.py:1006` (`spa`).
- **What happens (reproduced against a real `WEB_DIST`, i.e. production; the test suite skips these because `web/dist` is not built):** `GET /api/nonexistent` returns 200 text/html; `GET /api/apps/1/enviroment` returns 200 text/html; `GET /api/apps` returns 401 JSON, so real routes are unaffected. No `/api` guard, no auth dependency. A script or agent that typo'd a path gets a 200 and an HTML body, surfacing later as a confusing JSON parse error, or not at all if it only checks `res.ok`.
- **Evidence:** `test_spa.py:23` asserts real API routes are not shadowed but never tests an unknown one.
- **Severity:** MEDIUM-LOW. Confusion and masked client bugs.
- **Fix:** `raise HTTPException(404)` when `full_path.startswith("api/")`.

## Group G — Custom domains

### G1. Every Cloudflare API failure is silent, and the UI then shows the wrong instructions — 2 agents  ·  #100

- **Where:** `control-plane/koyracloud/cloudflare.py:53` (`_request`); consumed at `app.py:517` (`_ensure_cert`), `app.py:769` (`verify_domain`), `_domain_out` at `:496`.
- **What happens:** `_request` returns `None` for network errors, non-2xx and `success: false`, with no logging anywhere in the module. The Cloudflare token expires or loses the SSL:Edit scope. A user adds `www.theircompany.com`: the API returns 201 Created, no error, no log line. With no `DomainCert` row, `_domain_out` takes the `else` branch and shows the plain `dns_ok` check against `settings.public_ip`, so the customer is told to point an A record at the homelab WAN IP, the wrong instruction for a Cloudflare-for-SaaS host, and no cert is ever minted. Clicking Verify re-runs `_ensure_cert`, fails silently again, and returns 200 with unchanged state; `last_checked` is not touched and is not in `DomainOut` anyway, so the badge stays PENDING and the user clicks Verify forever.
- **Variant:** `dcv_uuid()` returns `""` on error, so `customer_records` omits the `_acme-challenge` CNAME. Certs are issued with `ssl.method: "txt"`, so that record is the one that makes validation work. A token that can create custom hostnames but 403s on `dcv_delegation/uuid` produces a UI saying "add these CNAME records" that lists exactly one. The customer adds it and the cert never issues.
- **Also:** `delete_custom_hostname`'s bool return is discarded at `app.py:764`, so removed domains leak hostnames against the zone quota. `_backfill_certs` prints only if the whole sweep raises; a 403 per domain is not an exception.
- **Severity:** MEDIUM. A broken token is invisible and the resulting UI actively misdirects the customer.
- **Fix:** log method, path and Cloudflare's `errors[]` on every `None`-returning path; persist a `last_error` on the domain; return 502 (or a `check_failed` flag) from Verify when `_request` yields None; refuse to render the record list when `dcv_uuid()` is empty.

## Group H — Serving the wrong bytes with a 200

### H1. Static server: no trailing-slash redirect, and missing assets are served as 200 HTML  ·  #101

- **Where:** `runtime-image/koyra_static.py:67-79` (`_resolve`).
- **What happens (empirically verified):** `/docs` is served as `/docs/index.html` with 200 and no redirect, so the page's relative asset URLs resolve one directory too high; those misses hit the SPA fallback and return `index.html` as `200 text/html` for what the browser requested as an image or script. Against a fixture with `site/index.html`, `site/docs/index.html` (containing `<img src="logo.png">`) and `site/docs/logo.png`:

  ```
  '/docs'       (200, 'text/html', b'<html><body>DOCS PAGE <img src="logo.png">...')  # no 301
  '/logo.png'   (200, 'text/html', b'<html><head></head><body>ROOT</body></html>')    # wrong body, wrong type
  '/missing.js' (200, 'text/html', b'<html><head></head><body>ROOT</body></html>')
  ```

  A visitor landing on `example.com/docs` gets every image broken and every script throwing `Unexpected token '<'`. koyracloud's own uptime monitor probes the URL, sees 200, and reports the app up.
- **Evidence:** `SimpleHTTPRequestHandler`, which this class overrides, 301-redirects directory paths precisely to avoid this; `_resolve` replaces that with `if target.is_dir(): target = target / "index.html"` and never redirects.
- **Severity:** MEDIUM. 200-with-wrong-content is invisible to every monitor, including koyracloud's own.
- **Fix:** 301 `/<dir>` to `/<dir>/` before falling through; skip the SPA fallback for paths with a non-HTML file extension.

### H2. Analytics injection silently deletes non-UTF-8 bytes from served HTML  ·  #101

- **Where:** `runtime-image/koyra_static.py:43-51` (`_inject`), `html.decode("utf-8", "ignore")`.
- **What happens (empirically verified):** characters vanish from the page with a 200, a correct `Content-Length`, and no log line. A latin-1/cp1252 file served with analytics on: `b'Caf\xe9 na\xefve ... pr\xeat'` on disk becomes `b'Caf nave ... prt'` served, 200, Content-Length 123. Only happens when analytics is on, so the file looks fine locally.
- **Reach:** analytics is on by default for every new app (`app.py:578`), and static sites get the beacon auto-injected, so a legacy non-UTF-8 site is corrupted from its first deploy, and turning analytics off "fixes" it for no discoverable reason.
- **Severity:** LOW. Needs non-UTF-8 source files, but the corruption is undetectable from the platform side.
- **Fix:** operate on bytes (`html.replace(b"</head>", ...)`) so unknown encodings pass through untouched.

## Group I — Docs and installer drift

### I1. `docs/MONITORING.md` says the control plane has no auto-deploy; CI deploys it on every merge  ·  #102

- **Where:** `docs/MONITORING.md` § Deploying vs `.github/workflows/ci.yml:41-108`.
- **What happens:** two live deploy paths overwrite each other, with the docs asserting one of them does not exist. Both report success. CI runs `docker service update --image arshadansari27/koyracloud:<sha> --force koyracloud_control-plane` on every push to main. An operator following MONITORING.md then runs `deploy/deploy.sh`, which builds `koyracloud:local` from their working tree and does `stack deploy --resolve-image=never` plus `service update --force`, silently reverting the service to whatever commit their checkout is on. Both commands print success; nothing shows which image is live.
- **Evidence:** the doc line landed in `d45fc0a (#24)`, the deploy job in `06d9ffa (#28)`: the doc was true when written and the CI job made it false. The same doc's "stack-env / label-only change" command deploys with `-c deploy/koyracloud-stack.yml` only, dropping the monitoring overlay that `deploy.sh` applies when `KOYRA_MONITORING=1`, and pins `KOYRA_IMAGE=koyracloud:local` while it's at it.
- **Severity:** MEDIUM-HIGH. Silently shipping older code to production, on the instructions in the repo.
- **Fix:** update the doc to describe CI as the deploy path; have `deploy.sh` print the image it is replacing, or refuse when the live image is a registry tag.

### I2. `KOYRA_APPS_DOMAIN` placeholder is never validated  ·  #102

- **Where:** `deploy/install.sh:59-89` vs `deploy/koyracloud.env.example:13`.
- **What happens:** the installer refuses three other placeholders by name (`KOYRA_ALLOWED_LOGINS`, `KOYRA_HOST`, `GITHUB_CLIENT_ID`) but lets this one through. An operator edits the host and login lines, misses the apps domain, and installs. Every app gets `<name>-<token>.apps.example.com`, a hostname they do not control and which never resolves. The first deploy converges and the dashboard shows the app live with `1/1 running` and a clickable green link to `apps.example.com`. Traefik also starts requesting Let's Encrypt certs for a domain that cannot pass HTTP-01.
- **Severity:** LOW-MEDIUM. First-run only, but it presents as a working deploy.
- **Fix:** add `apps.example.com` to the existing placeholder `case` block.

### I3. Editing the apex Caddyfile without bumping the config version deploys nothing  ·  #102

- **Where:** `deploy/apex-redirect-stack.yml:15-17, 33-37`.
- **What happens:** docker configs are immutable. `docker stack deploy` with an existing `apex_caddyfile_v1` references it without comparing contents, no error, no warning, so the service keeps serving the old Caddyfile. An operator adds a new apex block, redeploys, sees `Updating service apex-redirect_caddy` and `1/1`, and the new apex simply does not redirect. Indistinguishable from a DNS propagation delay.
- **Evidence:** the file's own comment documents the requirement, but nothing enforces or detects it. This is the only stack in the repo where a config edit is a no-op by default.
- **Severity:** LOW. Documented in-file, single-service blast radius.
- **Fix:** name the config by a content hash, or fail the deploy when the file's checksum differs from the version suffix.

## Not silent, but worth filing

Four adjacent findings that fall outside the silent-failure definition:

- **Argument injection in `DeployTrigger.ref`.** `AppCreate.branch` runs `_check_ref` (`schemas.py:31-34`) but `DeployTrigger.ref` is a bare `str | None` (`:88-89`) with no validator. Reproduced: `POST {"ref": "--upload-pack=touch /tmp/pwn"}` returns 201, stored verbatim, handed to the cloner. One-line fix: `_v_ref = field_validator("ref")(_check_ref)`.
- **`tasks[:6]` truncation** (`docker_ctl.py:161`): a worker with `replicas > 6` can never satisfy `_running_new(st, image) >= desired`, so the deploy times out even though it converged. A false failure, not a silent success.
- **CI leaves the private key on the runner.** If the ssh step fails, `rm -f ~/.ssh/swarm_key` never runs (no `if: always()`).
- **`scheduler.launch` image resolution** (`scheduler.py:79-83`) picks the highest-id `BuiltImage` matching the live commit prefix, which can differ from the live deploy's `args_hash` if the same commit was built twice with different build args.

## Checked and cleared

These were audited and found sound. Do not re-derive them.

- **`_wait_converged`** (`deployer.py:285-358`): the strongest code in the repo, per the auditor. It verifies convergence by image identity, not replica count, so a start-first update still serving the old task, and a post-rollback old-image-only state, both fail correctly. Handles swarm rollback/pause (guarded on having seen `updating` first), restart-policy exhaustion, and timeout, each with the real `service ps --no-trunc` task error.
- **`_DeployLog`** (`deployer.py:118-169`): no lost tail. Status changes force an immediate flush, and `_run_deploy` flushes before the completion write, before the failure webhook, and in `finally` on every path. The single-statement UPDATE avoids the WAL read-then-write upgrade deadlock as documented.
- **Build failures themselves:** `_stream` checks `proc.wait()` and raises with the exit code; stderr is merged into the deploy log. Build and push failures are loud.
- **`git_clone` / `_git`:** raises with the real stderr, scrubbing the token.
- **Build-context escape** (`deployer.py:421-431`, `manifest.py:172-178`): `resolve()` plus an explicit prefix check blocks a crafted `root:` with an in-repo symlink.
- **Path traversal in the static server:** empirically confirmed blocked for `/../../etc/passwd`, `/%2e%2e/...`, `/docs/../index.html`, including symlinks out of the root. Security headers do apply to 404s.
- **`auth.py`:** `is_allowed` is fail-closed on an empty allowlist; `read_session` returns None on both `BadSignature` and `SignatureExpired`; `exchange_code` raises rather than returning an empty string.
- **`ratelimit.py`:** fails closed, prunes correctly, holds the lock for the whole read-modify-write.
- **`schemas.py`:** `_check_name`, `_check_repo_url`, `_check_ref`, `DomainIn._vh`, `WaitlistIn`, `AllowedUserIn._vl` all reject rather than coerce. Only `DeployTrigger.ref` is unguarded.
- **`db.py` `_migrate` / `models.py`:** every post-release column addition has a matching migration; cascades are correct; `delete_app` explicitly cleans the two relationships that are not cascaded.
- **No missing commits anywhere in `app.py`**, and no commit inside a swallowing `except`.
- **All three background loops** (`CronScheduler.run`, `UptimeMonitor.run`, `BackupLoop.run`) wrap their body in `try/except Exception`, so none of the threads can die.
- **`monitor.check_once` state machine:** `consecutive_fail` debounce, the `was_down` guard against spurious recovery alerts, and the 7-day prune all behave as documented.
- **`metrics.render`:** restart-safe, DB-derived, deliberately omits never-probed apps rather than defaulting them to 0. Only the Redis gauge misleads.
- **`webhooks.py`:** constant-time HMAC; `payload_repo` is clearly marked untrusted and used only for the rejection stamp; `deploy_target` refuses to deploy on a failed or in-progress `workflow_run`. PR #82's fix is in place and correct.
- **`stack_render.py`:** env precedence, Traefik zone/SaaS router split, NFS volume rendering vs bind fallback, per-app pin over `app_node`, resource limits: all covered by tests.
- **Stack secrets:** all eight are `external: true`, so a missing one fails the deploy loudly. `install.sh` refuses to create an empty generated secret.
- **`deploy.sh` / `install.sh` shell hygiene:** both `set -euo pipefail`; the one `|| true` is deliberate.
- **All 30+ interpolated stack env vars** cross-checked against the example env; every one either appears there or has a `:-` default, and the two without defaults are guarded by `${VAR:?}`.
- **`NewApp.jsx`, `Team.jsx`, the waitlist form:** all render the API error correctly. The dashboard's error handling exists; it is just not applied on `AppDetail.jsx`.

## What to fix first

Ordered by blast radius times likelihood, not by a generic severity ladder. The power fault is the likelihood multiplier: anything triggered by "the process restarts" fires every few weeks on a schedule you do not control.

1. **A4 — backup evidence, and restore validation.** Highest blast radius in the audit: the only copy of all platform state, with zero evidence either way, and a restore path that can overwrite the good copy with a truncated one. The NFS-unmounted trigger is exactly what a power event produces. Small change: `last_backup_at`/`last_error`, an age metric, `stat()` the file, open the snapshot before restore.
2. **The startup reconciler — C1, C2, B2 in one pass.** At boot: fail `running` CronRuns and non-terminal Deploys as "interrupted by restart", re-provision Redis ACL users from `AppRedis`, and switch `_redis_ping` to a real ACL user. One PR closes three findings, finishes issue #88, and converts every future power event from "silent partial outage" into a set of visible failed rows.
3. **B1 — a distinct error state for `services_overview`.** Fires during deploys, daemon restarts and incidents, exactly when the dashboard is being trusted, and pushes the operator toward redeploying healthy apps. Three agents found it independently. Check the exit code, catch the timeout, never cache a failure, render "unknown" as its own state.
4. **A1 + F1 — block the env editor on a failed read, render mutation errors.** One expired cookie away from irreversible env loss, and the fix pattern already exists in `NewApp.jsx`/`Team.jsx`. Do F1's shared `<MutError/>` in the same PR; it covers the notify, branch and deploy-button paths too.
5. **A2 — `extra="forbid"` on the manifest models.** A one-word typo deletes workers, cron history and volume mounts on a green deploy. The fix is one config line, or one call to the `_unknown_top_level_keys` helper that already exists.
6. **E1 + E2 — base image in the cache key, `--pull`, fix `README.md:58`.** Every future base-image update, including security patches, hits E1 until this lands. E2 is PR #83's shape reintroduced by a doc line; the warning on `VITE_`/`NEXT_PUBLIC_` secret keys is cheap.
7. **A5 — fail fast on an empty or default session secret.** Full auth bypass for self-hosters who bypass `install.sh`. A guard in `create_app` plus a warning on `crypto.ephemeral` with existing `Secret` rows.
8. **D1 + D2 + D3 — the alerting ledger.** One emitted line per webhook and email attempt, `last_notify_error` on `AppNotify`, and a pydantic model on `set_notify`. Alerting is the layer that turns every other silent failure loud; while it fails open, fixes 1-7 have no backstop.
9. **A3 — teardown before row delete.** High severity but needs a design choice (`status=deleting` vs 409), so it sits behind the one-liners.
10. **The validation batch.** F4, F5, F6, F7, C3, C4, E3, E4, B3, B4, G1, H1, H2, I1, I2, I3, and `DeployTrigger.ref` from the adjacent list. Mostly one-liners: 404 on no match, required pydantic fields, a `skipped` CronRun row, a warning per dropped key, a log line per Cloudflare failure. Two or three small PRs clear the whole tail.
