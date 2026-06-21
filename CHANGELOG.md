# Changelog

Notable changes to koyracloud. The project is in **alpha** (`0.1.0`); these notes
track functional changes by theme rather than tagged semver releases. Newest first.

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
- **Open-source hygiene** (#13) — removed homelab-specific identifiers (node names,
  private IPs, the swarm-context name, a client domain, a personal ACME email) from the
  deploy templates and docs in favour of env vars / placeholders. Application source was
  already fully env-driven.
- **Docs/copy refresh** (#13, #15) — rewrote the landing, in-app Docs and blog copy to
  the current build-into-image architecture (per-app image → built-in registry → run on
  any node), and surfaced the GitHub repo across the nav, hero, CTA and footer.
- **Per-user app scoping** (#11) — clarified + tested the admin vs. invited-member access
  model (admins see every app; members see only the apps they own).
