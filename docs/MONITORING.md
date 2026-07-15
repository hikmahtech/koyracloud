# Monitoring koyracloud

koyracloud runs on the homelab Docker Swarm, which already has Prometheus +
Alertmanager + Grafana (the `monitoring` stack). This doc describes how
koyracloud plugs into it. The guiding rule is **reuse, don't reinvent**: the
swarm's existing exporters already watch the control plane and every hosted app
at the infrastructure level — koyracloud only adds the one thing nothing else
knows.

## What the swarm already gives us (no koyracloud code)

- **cadvisor + node-exporter** scrape CPU / memory / restarts for every
  container, including the control plane, the registry, redis, and every
  `koyra-*` hosted app.
- **swarm-exporter** exposes `docker_service_running_tasks` /
  `docker_service_desired_tasks`; the existing `swarm-health` alert group fires
  when any service (apps included) runs fewer tasks than desired.
- **blackbox-exporter** already probes `https://koyracloud.com` end-to-end (HTTP
  + TLS-cert-expiry).

## What koyracloud adds: `/metrics`

The one gap is **end-to-end reachability of each hosted app**: a task can be
"running" (so swarm-exporter is happy) while the app returns 5xx or the
Cloudflare→Traefik edge path is broken. koyracloud's `monitor.py` already probes
every live app's public URL and records `UptimeState.up` — so the control plane
is the authoritative, *dynamic* source of per-app health (no hardcoded target
lists that rot as apps come and go).

The control plane exposes `GET /metrics` (Prometheus text; hand-rendered, no
extra dependency) computed from the DB on each scrape. It is **not
authenticated, but it is not publicly routable**: the Traefik router rule
(`… && !PathPrefix(/metrics)`) returns 404 for `koyracloud.com/metrics`, so only
in-cluster scrapers reach it. The metrics below include per-app traffic/visitor
counts that must stay internal — keep `/metrics` off any public ingress.

| Metric | Type | Labels | Meaning |
|--------|------|--------|---------|
| `koyracloud_apps_total` | gauge | — | apps known to the control plane |
| `koyracloud_apps_live` | gauge | — | apps with at least one `live` deploy |
| `koyracloud_app_up` | gauge | `app`, `host` | 1/0 from the uptime monitor (apps with a known state only) |
| `koyracloud_deploys_total` | counter | `status` | deploy rows by status (`live`/`failed`/…) |
| `koyracloud_redis_up` | gauge | — | control plane can reach the shared Redis (omitted if Redis isn't configured) |
| `koyracloud_app_views_total` | counter | `app` | pageviews from the built-in analytics beacon (all time) |
| `koyracloud_app_visitors_24h` | gauge | `app` | unique cookieless visitors in the last 24h |

No `owner` label is emitted; the endpoint is reached only in-cluster by
Prometheus (the public path is blocked at the edge, above).

**Per-app usage.** "How each app is doing" comes from two sources. Traffic,
latency and error rate are read straight from **Traefik's** already-scraped
per-router metrics (`traefik_service_*{service="koyra-<app>@docker"}`) — always
available, no app changes. "How many users" comes from `koyracloud_app_views_total`
/ `koyracloud_app_visitors_24h`, which only count apps that embed the `/_k/a.js`
beacon (a per-app opt-in). koyracloud has no visibility into apps' *internal*
registered users — each app owns its own database.

## Wiring into Prometheus (homelab-gitops)

The monitoring join is **opt-in**: set `KOYRA_MONITORING=1` in
`deploy/koyracloud.env` so `deploy.sh` applies the
`deploy/koyracloud-monitoring.yml` overlay — the control plane then joins the
external `monitoring` overlay (which must already exist:
`docker network create --driver overlay --attachable monitoring`) so Prometheus
can reach it. Without the flag the stack never references that network, so
fresh installs don't need it. It's scraped by a dedicated static job —
mirroring how grafana / postgres-exporter are scraped:

```yaml
# prometheus.yml.j2
- job_name: 'koyracloud'
  metrics_path: /metrics
  static_configs:
    - targets: ['tasks.koyracloud_control-plane:8000']
```

A static job (rather than the `prometheus.scrape=true` label job) gives a single
clean target and avoids the label job emitting one target per attached overlay
(the control plane is on several), which would create unreachable targets and
false "down" alerts.

## Alerts (homelab-gitops `alert-rules.yml.j2`, group `koyracloud`)

Routed by `severity` through the existing Alertmanager (Slack `#infra-alerts`,
plus the aegis webhook for critical) — no routing changes.

- **KoyracloudControlPlaneDown** — `up{job="koyracloud"} == 0` for 5m → critical.
  The control plane (deploys, management, the dashboard) is unreachable.
- **KoyracloudHostedAppDown** — `koyracloud_app_up == 0` for 10m → warning.
  A hosted app is failing its external probe. The monitor already debounces
  (2 consecutive failures) before reporting down.
- **KoyracloudRedisDown** — `koyracloud_redis_up == 0` for 5m → warning.

Per-service task-down (control plane, redis, any app) is already covered by the
generic `swarm-health` group, so it is not duplicated here.

## Redis on the `monitoring` overlay (gotcha)

Joining the `monitoring` overlay (so Prometheus can scrape) has a side effect:
the bare hostname `redis` becomes ambiguous, because the homelab standalone redis
is also on that overlay aliased `redis`. The control plane therefore targets the
**fully-qualified** service name — `KOYRA_REDIS_HOST` defaults to `koyracloud_redis`,
not `redis`. On any container attached to multiple overlays, use `<stack>_<service>`
names, never bare service aliases.

## Grafana

`koyracloud.json` (Infrastructure folder) shows control-plane up, apps
total/live, per-app up/down, deploys by status, redis up, and per-`koyra-*` task
health — plus a **Usage** row: per-app requests/sec, p95 latency and 5xx rate from
**Traefik's** already-scraped `traefik_service_*{service="koyra-<app>@docker"}`
(always-on, no app changes), and per-app unique visitors from the beacon. The
dashboard is hosted on `daal` (a CI-reachable node) — see the homelab-gitops
`docs/infrastructure/logging-monitoring.md` for the node/CI details.

## Deploying

The **control plane has no auto-deploy** — `ci.yml` only runs tests + builds the
UI. Ship it with `deploy/deploy.sh`:

- **Code change** (e.g. `metrics.py`): `DOCKER_CONTEXT=swarm-baa bash deploy/deploy.sh`
  rebuilds the image, loads it onto the manager and rolls the service.
- **Stack-env / label-only change** (e.g. `KOYRA_REDIS_HOST`, the Traefik rule): no
  rebuild needed — re-apply the stack:
  `set -a; . deploy/koyracloud.env; set +a;
  KOYRA_IMAGE=koyracloud:local docker --context swarm-baa stack deploy
  --resolve-image=never -c deploy/koyracloud-stack.yml koyracloud`

The **homelab-gitops** side (scrape job, alerts, dashboard) **auto-deploys on
merge** to main (the on-merge Ansible pipeline maps changed files to the
`prometheus` / `grafana` playbooks).

**Order:** deploy koyracloud first (so the control plane is on the `monitoring`
network and `tasks.koyracloud_control-plane` resolves), then the homelab side —
otherwise the scrape target won't resolve and `KoyracloudControlPlaneDown` fires
until the next koyracloud deploy.
