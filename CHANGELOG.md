# Changelog

Notable changes to koyracloud. The project is in **alpha** (`0.1.0`); these notes
track functional changes by theme rather than tagged semver releases. Newest first.

## 2026-07

### Added

- **Single-node installs work out of the box** — the registry/redis NFS volumes and the
  homelab `monitoring` network are now opt-in overlays (`deploy/koyracloud-nfs.yml` when
  `KOYRA_NFS_SERVER` is set, `deploy/koyracloud-monitoring.yml` when `KOYRA_MONITORING=1`)
  instead of hard requirements baked into the stack; the base stack runs on one machine
  with local volumes and no NFS. `install.sh` now refuses placeholder config that used to
  fail silently (empty control node / allowlist / host / OAuth client id), verifies the
  context is a swarm manager and the secret generators exist, creates the host dirs on
  the control node, and stores skipped optional secrets as a single space (some Docker
  versions reject empty secrets). `KOYRA_TRAEFIK_NETWORK` now actually renames the edge
  network in the core stack. New [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md)
  maps every known first-run error to its fix.
- **Webhook connectivity tracking** (#64) — the control plane records whether a repo's
  GitHub webhook has ever reached it and the Settings tab warns when auto-deploy is on
  with no webhook delivering.
- **Deploys wait for convergence before "live"** (#65) — a deploy is marked live only
  once every replica is Running (and healthy) on the new image; a task that can't start
  fails the deploy with the real task error instead of reporting success.
- **Static-site example manifests** (#56) — `examples/` ships runnable `.paas/app.yaml`
  starters (FastAPI+React, and a static Vite/Astro/Hugo-style site).
- **Opt-in per-app node pinning** (#62) — a **Pin to node** toggle in the app's Settings
  tab keeps a stateful app (one with data on the node's local disk rather than an NFS
  `persist:` volume) on the single Swarm node it's already running on, so a reschedule
  can't orphan that data. The default is unchanged — apps still run on any node and
  reschedule freely unless pinned. Enabling it records the node and enforces the
  constraint on the app's next deploy (it doesn't move a running container); web and
  workers co-locate, and a per-app pin takes precedence over the operator-wide
  `KOYRA_APP_NODE`. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

### Fixed

- **Intermittent `database is locked` deploy failures** (#67, #68) — the control-plane
  SQLite now lives on the control node's **local disk** (`KOYRA_DB_DIR`; WAL mode is
  unsupported on NFS) with periodic backups on the NFS (`KOYRA_BACKUP_DIR`), and deploy
  log writes are batched (~25 lines/1s per UPDATE, status changes immediate) instead of
  one write per docker output line. Migration runbook:
  [`docs/DISASTER-RECOVERY.md`](docs/DISASTER-RECOVERY.md) § "Moving the DB off NFS".
- **Friendlier build-failure messages** (#58, #60) — known failure signatures (pnpm/node
  version mismatch, missing `NEXT_PUBLIC_*`/`VITE_*` build args, python3-less alpine
  healthchecks) surface a one-line `Hint:` in the deploy log.

## 2026-06

### Added

- **Background workers, cron jobs & a shared Redis bus** (#12) — declare `workers:`,
  `cron:` and `redis: true` in `.paas/app.yaml`, all running from the same repo and
  built image as the web process:
  - `workers:` — always-on background processes (no HTTP port), one Swarm service each.
  - `cron:` — commands on a 5-field UTC schedule, launched to completion by a
    control-plane scheduler as Swarm run-to-completion jobs, with per-run status + logs
    and a **Run now** trigger.
  - `redis: true` — one koyracloud-owned Redis, **isolated per app** by an ACL user
    scoped to `<app>:*` keys/channels (stable injected `REDIS_URL`, `noeviction`).
  - A new **Background** tab surfaces worker status/logs, cron schedules + run history,
    and Redis status. Documented in the in-app Docs and the README.
- **Prometheus metrics + monitoring** (#17) — the control plane exposes `/metrics` and
  joins the `monitoring` overlay; adds per-app end-to-end reachability metrics, a
  `koyracloud-health` alert group, and a Grafana dashboard. Reuses the swarm's existing
  cadvisor / node-exporter / swarm-exporter / blackbox-exporter rather than reinventing
  them. See [`docs/MONITORING.md`](docs/MONITORING.md).
- **Self-host onboarding** (#15) — [`docs/SELF-HOST-TUTORIAL.md`](docs/SELF-HOST-TUTORIAL.md)
  (bare machines → swarm → Traefik → NFS → DNS → OAuth → first app), a guided idempotent
  installer [`deploy/install.sh`](deploy/install.sh), and a sample Traefik v3 edge
  [`deploy/examples/traefik-stack.yml`](deploy/examples/traefik-stack.yml).
- **SEO / AEO** (#13, #18) — Open Graph + Twitter Card tags with a branded 1200×630 PNG
  image, `SoftwareApplication` + `FAQPage` JSON-LD, `robots.txt`, `sitemap.xml`, and an
  `llms.txt` (answer-engine standard).
- **Optional Google Analytics 4** (#16) — a static gtag baked into the SPA at build time
  only when `KOYRA_GA_MEASUREMENT_ID` is set; **off by default**, so a self-hosted build
  ships no analytics and never inherits another instance's property.

### Fixed

- **Redis NFS volume** (#14) — `nocopy: true` on the Redis volume so Docker's first-use
  `/data` copy-up doesn't trip an NFS `root_squash` chown rejection (which otherwise left
  the service stuck at `0/1`).
- **Redis service name** (#19) — default `KOYRA_REDIS_HOST` to the fully-qualified
  `koyracloud_redis` instead of the bare `redis` alias, avoiding a DNS collision with the
  homelab's standalone redis once the control plane joined the `monitoring` overlay.

### Changed

- **Dependency cleanup** (#33, #34) — dropped three unused/avoidable dependencies with no
  behaviour change: `authlib` and `python-multipart` from the control plane (OAuth is plain
  `httpx`; nothing parses form data), and `axios` from the web app — replaced by a ~25-line
  native `fetch` wrapper that keeps the same `err.response` error shape callers rely on.
  Smaller image and a smaller JS bundle.
- **Front-end CSS dedup** (#35) — collapsed the bare text-button utility soup
  (`bg-transparent border-0 cursor-pointer`, repeated across 15 buttons) into a single
  `.linkbtn` class, matching the existing `.btn` / `.card` / `.input` convention. Purely
  presentational; no visual change.
- **CI on Node 24** (#36) — bumped every GitHub Action to its latest Node 24 major
  (`checkout` v7, `setup-node` v6, `setup-uv` v7, `docker/*` v4–v7), clearing the Node 20
  runtime deprecation warnings on each run.
- **CI lint gate** (#38) — added a `ruff` job that blocks build + deploy on lint failures,
  and cleaned up the pre-existing lint it surfaced (two unused imports in `monitor.py`, plus
  test-style fixes). Keeps unused imports / dead code from creeping back in.
- **Dead-code removal** (#39) — deleted three verified-unused items: the `deprovision()`
  Redis helper (redundant with `delete_app`'s inline teardown), the uncalled
  `CronScheduler.stop()`, and the never-read `redis_maxmemory` setting (Redis maxmemory is
  set in the deploy stack via `KOYRA_REDIS_MAXMEMORY`).
- **Open-source hygiene** (#13) — removed homelab-specific identifiers (node names,
  private IPs, the swarm-context name, a client domain, a personal ACME email) from the
  deploy templates and docs in favour of env vars / placeholders. Application source was
  already fully env-driven.
- **Docs/copy refresh** (#13, #15) — rewrote the landing, in-app Docs and blog copy to
  the current build-into-image architecture (per-app image → built-in registry → run on
  any node), and surfaced the GitHub repo across the nav, hero, CTA and footer.
- **Per-user app scoping** (#11) — clarified + tested the admin vs. invited-member access
  model (admins see every app; members see only the apps they own).
