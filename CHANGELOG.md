# Changelog

Notable changes to koyracloud. The project is in **alpha** (`0.1.0`); these notes
track functional changes by theme rather than tagged semver releases. Newest first.

## 2026-09

### Added

- **Deploy your private repos with your own GitHub access, Vercel-style** — sign-in can
  now go through a **GitHub App** (`GITHUB_APP_SLUG`, see the self-host tutorial §7).
  Users install the app on the repos they choose and pick them from a list on the New
  app page; koyracloud clones with their read-only token, kept encrypted per user and
  refreshed automatically. The platform PAT is still the fallback (and `KOYRA_GIT_TOKEN`
  still wins per app), so a repo the user's token cannot see is retried with the platform
  token instead of failing. Nothing changes for installs that keep a plain OAuth App.
- **App members** — an app's owner (or an admin) can add teammates by GitHub login on the
  Settings tab. Members see the app in their list and operate it (deploy, env, secrets,
  domains); deleting it or changing members stays with the owner. Members still have to be
  on the instance allow-list to sign in.
- **Build hint for `X: not found` after `npm ci`** — with `NODE_ENV: production` in the
  manifest `env:` block, npm skips devDependencies at build time (typescript, drizzle-kit,
  vite…). The deploy log now says so and points at `npm ci --include=dev`.

## 2026-08

### Fixed

- **A webhook we reject no longer looks like a webhook that was never set up** (#82) — a
  repo hook configured with the wrong secret fails the HMAC check, and until now that left
  no trace anywhere: `webhook_seen_at` is only stamped *after* verification, so a
  wrong-secret hook and a missing hook were indistinguishable. Auto-deploy silently never
  fired while the UI insisted GitHub had never called, sending operators off to re-add a
  hook that already existed. Rejected deliveries now record `webhook_rejected_at` (repo
  read from the unverified body — a timestamp is all that's taken from it) and log a
  warning naming the repo; the next delivery that verifies clears it, so fixing the secret
  turns the UI green on GitHub's next call. Found in prod after a repo went two months
  without a single auto-deploy.
- **Build-args now reach buildpack builds** (#83) — generated Dockerfiles declared no
  `ARG`, and `docker build --build-arg` on an undeclared name is a *warning, not an error*,
  so every arg the deployer passed was silently discarded. Because the image tag is
  `<commit>-<sha256(build-args)>`, setting a `VITE_*`/`NEXT_PUBLIC_*` did force a full
  rebuild while the value still never reached the build — a rebuild that changed nothing,
  with no error. Each arg is now declared after `WORKDIR` and before `COPY` (in the
  `golang` stage for `runtime: go`, since `ARG` is per-stage). Env keys are unvalidated
  user input, so only `[A-Za-z_][A-Za-z0-9_]*` is emitted — a newline in a key would
  otherwise inject instructions into the generated Dockerfile. Apps with no env render
  byte-for-byte as before and their image tag is unchanged, so nothing rebuilds from this.
- **Cron jobs ran zero times** (#78, #79) — `scheduler.launch` built the job image as
  `koyra-app-<name>:<commit12>`, but since build-args-hash tagging the deployer only
  pushes `<commit12>-<argsHash>` (and `latest`). Every job was Rejected in ~2s with an
  empty log. The live tag is now resolved from `BuiltImage`, and jobs run synchronously
  via `docker run --rm` instead of a Swarm replicated job that multi-manager reconciliation
  re-executed across nodes and whose logs were lost.

## 2026-07

### Added

- **`runtime: go` buildpack** (#77) — go renders a two-stage Dockerfile of its own rather
  than layering on the shared python+node runtime image: `golang:1.23` runs the manifest's
  `build:` steps (defaulting to `CGO_ENABLED=0 go build -o /app/server .`), and a
  `gcr.io/distroless/static-debian12` runner copies in just the binary. `CMD` is exec-form
  because distroless has no shell, so a custom `start:` can be quoted but can't use `&&`,
  pipes or redirects, and a custom `build:` must still land the binary at `/app/server`.
  `healthcheck:` and `predeploy:` are rejected at manifest-parse time for this runtime —
  both need the `python3`/shell that distroless doesn't have, and without the guard the
  container would build and start cleanly and then be killed by swarm ~30-60s later.
- **Real 404s and response headers for static sites** (#76) — `koyra_static.py` used to
  SPA-fallback every unmatched path to `index.html` with HTTP 200, so crawlers probing
  invented URLs got soft-404s that cost crawl budget and read as duplicate content. An
  unmatched path now serves `404.html` with status 404 when the site ships one, and a new
  static-only `spa:` flag forces the choice (`true` = always SPA-fallback, `false` = always
  real 404s, unset = auto). `X-Content-Type-Options: nosniff` and `X-Frame-Options:
  SAMEORIGIN` are sent on every response including 404s, and an optional `headers:` map in
  the manifest is applied to every response and may override those defaults.
- **`notify.on_failure` webhook** (#61, #73) — a failed build correctly leaves the old
  service running, but nothing told anyone. A manifest `notify: { on_failure: <url> }`
  now gets a POST of `{app, deploy_id, status, error, log_tail}` (last ~50 log lines,
  read after the failure lines flush so the hints are included). Strictly best-effort with
  a 10s timeout and every exception swallowed, so a broken webhook can't delay or crash the
  failure path; a failure that happens before the manifest parses simply skips it. Only
  `http://`/`https://` URLs are accepted, rejected at parse time.
- **`koyra validate` — lint `.paas/app.yaml` before you push** (#74) — a CLI that reuses
  `manifest.parse_manifest` verbatim, so it enforces exactly what the control plane does
  with no second copy of the rules. Prints a one-screen summary and exits 0, or the parse
  error with its field path (`cron.0.schedule: invalid cron schedule: 'bad'`) and exits 1.
  `--strict` also warns on unknown top-level keys, which the parser otherwise ignores.
  Runs with no install:

  ```
  uvx --from "git+https://github.com/hikmahtech/koyracloud#subdirectory=control-plane" koyra validate
  ```
- **[`docs/PERMISSIONS.md`](docs/PERMISSIONS.md)** (#52, #59, #75) — first written by
  [@erikurt9](https://github.com/erikurt9) in #59, which reached the same conclusions
  against the same source files; #75 is the version that shipped. The minimum Docker socket,
  GitHub PAT/OAuth, webhook secret, Cloudflare token, Resend key, Redis password and
  filesystem access the control plane needs, each tied to the code path that uses it. Spells
  out that the Docker socket is root-equivalent on that node and that a socket proxy doesn't
  lower the ceiling, and that the Cloudflare token needs only `Zone → SSL and Certificates
  → Edit` — no DNS permission, since koyracloud never calls the DNS records API.
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

- **A `docker system prune` could break every buildpack build** (#66, #72) — the runtime
  image is a build-time-only `FROM`, so nothing running referenced it and a prune on the
  manager deleted it; every generated-Dockerfile build then failed with `pull access
  denied`. `install.sh` now pushes it to the instance registry and `KOYRA_RUNTIME_IMAGE`
  defaults to `127.0.0.1:5000/koyracloud-runtime:latest`, so `docker build` re-pulls the
  `FROM` on demand after any prune.
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
