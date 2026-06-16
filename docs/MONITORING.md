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

The control plane exposes an **unauthenticated** `GET /metrics` (Prometheus text;
hand-rendered, no extra dependency) computed from the DB on each scrape:

| Metric | Type | Labels | Meaning |
|--------|------|--------|---------|
| `koyracloud_apps_total` | gauge | — | apps known to the control plane |
| `koyracloud_apps_live` | gauge | — | apps with at least one `live` deploy |
| `koyracloud_app_up` | gauge | `app`, `host` | 1/0 from the uptime monitor (apps with a known state only) |
| `koyracloud_deploys_total` | counter | `status` | deploy rows by status (`live`/`failed`/…) |
| `koyracloud_redis_up` | gauge | — | control plane can reach the shared Redis (omitted if Redis isn't configured) |

No `owner` label — the endpoint is reachable at `koyracloud.com/metrics`, and app
hostnames are already public sites, so nothing sensitive is exposed.

## Wiring into Prometheus (homelab-gitops)

The control plane joins the external `monitoring` overlay (so Prometheus can
reach it) and is scraped by a dedicated static job — mirroring how grafana /
postgres-exporter are scraped:

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

## Grafana

`koyracloud.json` (Infrastructure folder) shows control-plane up, apps
total/live, per-app up/down, deploys by status, redis up, and per-`koyra-*`
task health from swarm-exporter.

## Deploy order

Deploy koyracloud first (so the control plane is on the `monitoring` network and
`tasks.koyracloud_control-plane` resolves), then apply the Prometheus/Grafana
changes — otherwise the scrape target won't resolve and `KoyracloudControlPlaneDown`
fires until the next koyracloud deploy.
