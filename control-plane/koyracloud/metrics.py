"""Prometheus metrics for the control plane, rendered as text on each scrape.

``render`` is pure w.r.t. process state: everything is computed from a DB session
(+ an injected Redis pinger), so there is no background metric state to keep, it
is restart-safe, and it is unit-tested. It exposes ONLY what the platform
uniquely knows — per-app external uptime (from ``monitor``), app/deploy counts,
and Redis reachability. Container CPU/memory/restarts and task-replica health
already come from cadvisor / node-exporter / swarm-exporter on the swarm.
"""
from __future__ import annotations

import datetime as dt
from typing import Callable

from sqlalchemy import distinct, func

from koyracloud.db import Database
from koyracloud.models import App, Deploy, Hit, UptimeState
from koyracloud.monitor import _primary_host

# A Redis pinger returns True when the control plane can reach the shared Redis.
# None means Redis isn't configured on this instance — the metric is then omitted.
RedisPing = Callable[[], bool]


def _esc(v: str) -> str:
    return str(v).replace("\\", "\\\\").replace('"', '\\"')


def _metric(name: str, value, labels: dict[str, str] | None = None) -> str:
    if labels:
        inner = ",".join(f'{k}="{_esc(v)}"' for k, v in labels.items())
        return f"{name}{{{inner}}} {value}"
    return f"{name} {value}"


def render(db: Database, *, redis_ping: RedisPing | None = None,
           now: dt.datetime | None = None) -> str:
    """Render the full /metrics body (text exposition format 0.0.4)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    out: list[str] = []
    with db.session() as s:
        apps = s.query(App).all()
        live = sum(1 for a in apps if any(d.status == "live" for d in a.deploys))

        out += ["# HELP koyracloud_apps_total Apps known to the control plane.",
                "# TYPE koyracloud_apps_total gauge",
                _metric("koyracloud_apps_total", len(apps))]
        out += ["# HELP koyracloud_apps_live Apps with at least one live deploy.",
                "# TYPE koyracloud_apps_live gauge",
                _metric("koyracloud_apps_live", live)]

        # Per-app external uptime, from the monitor's debounced state. Only apps
        # with a known state (up is not None) are emitted, so a never-probed app
        # never looks "down".
        out += ["# HELP koyracloud_app_up Hosted app reachable on its public URL (1/0).",
                "# TYPE koyracloud_app_up gauge"]
        states = {st.app_id: st for st in s.query(UptimeState).all()}
        for a in apps:
            st = states.get(a.id)
            host = _primary_host(a)
            if st is None or st.up is None or not host:
                continue
            out.append(_metric("koyracloud_app_up", 1 if st.up else 0,
                               {"app": a.name, "host": host}))

        # Deploy rows by status (append-only table → counter semantics).
        out += ["# HELP koyracloud_deploys_total Deploy attempts by status.",
                "# TYPE koyracloud_deploys_total counter"]
        for status, count in s.query(Deploy.status, func.count()).group_by(Deploy.status):
            out.append(_metric("koyracloud_deploys_total", count, {"status": status}))

        # Per-app usage from the built-in analytics beacon. Only apps that embed
        # /_k/a.js report hits; every app gets a series (0 when none) so each is
        # visible. Visitors are the cookieless daily-rotating hash → a privacy-
        # safe "active users" proxy.
        views = dict(s.query(Hit.app_id, func.count()).group_by(Hit.app_id).all())
        visitors = dict(s.query(Hit.app_id, func.count(distinct(Hit.visitor)))
                        .filter(Hit.ts >= now - dt.timedelta(hours=24))
                        .group_by(Hit.app_id).all())
        out += ["# HELP koyracloud_app_views_total Pageviews from the analytics beacon (all time).",
                "# TYPE koyracloud_app_views_total counter"]
        for a in apps:
            out.append(_metric("koyracloud_app_views_total", views.get(a.id, 0), {"app": a.name}))
        out += ["# HELP koyracloud_app_visitors_24h Unique cookieless visitors in the last 24h.",
                "# TYPE koyracloud_app_visitors_24h gauge"]
        for a in apps:
            out.append(_metric("koyracloud_app_visitors_24h", visitors.get(a.id, 0), {"app": a.name}))

    if redis_ping is not None:
        out += ["# HELP koyracloud_redis_up Control plane can reach the shared Redis (1/0).",
                "# TYPE koyracloud_redis_up gauge",
                _metric("koyracloud_redis_up", 1 if redis_ping() else 0)]

    return "\n".join(out) + "\n"
