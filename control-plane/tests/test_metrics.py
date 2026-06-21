"""Prometheus /metrics exposition."""
import datetime as dt

from koyracloud import metrics
from koyracloud.models import App, Deploy, Domain, Hit, UptimeState


def _seed(db):
    with db.session() as s:
        # alpha: live + failed deploy, probed UP, has a primary host
        a = App(name="alpha", repo_url="https://github.com/o/a")
        s.add(a)
        s.flush()
        s.add(Domain(app_id=a.id, host="alpha.example.com", is_primary=True))
        s.add(Deploy(app_id=a.id, status="live", ref="main"))
        s.add(Deploy(app_id=a.id, status="failed", ref="main"))
        s.add(UptimeState(app_id=a.id, up=True))
        # beta: probed DOWN
        b = App(name="beta", repo_url="https://github.com/o/b")
        s.add(b)
        s.flush()
        s.add(Domain(app_id=b.id, host="beta.example.com", is_primary=True))
        s.add(UptimeState(app_id=b.id, up=False))
        # gamma: never probed (up is None) -> must NOT emit an app_up line
        c = App(name="gamma", repo_url="https://github.com/o/c")
        s.add(c)
        s.flush()
        s.add(Domain(app_id=c.id, host="gamma.example.com", is_primary=True))
        s.commit()


def test_render_counts_uptime_and_deploys(env):
    _seed(env["db"])
    text = metrics.render(env["db"], redis_ping=lambda: True)

    assert "koyracloud_apps_total 3" in text
    assert "koyracloud_apps_live 1" in text                      # only alpha is live
    assert 'koyracloud_app_up{app="alpha",host="alpha.example.com"} 1' in text
    assert 'koyracloud_app_up{app="beta",host="beta.example.com"} 0' in text
    assert text.count("koyracloud_app_up{") == 2                 # gamma omitted (unknown)
    assert 'koyracloud_deploys_total{status="live"} 1' in text
    assert 'koyracloud_deploys_total{status="failed"} 1' in text
    assert "koyracloud_redis_up 1" in text
    # proper exposition: every series has a TYPE line
    assert "# TYPE koyracloud_app_up gauge" in text


def test_app_usage_views_and_visitors(env):
    now = dt.datetime(2026, 6, 17, 12, 0, tzinfo=dt.timezone.utc)
    with env["db"].session() as s:
        a = App(name="alpha", repo_url="https://github.com/o/a")
        s.add(a)
        s.flush()
        # 3 views in the last 24h from 2 distinct visitors, + 1 old view (>24h)
        s.add(Hit(app_id=a.id, ts=now - dt.timedelta(hours=1), path="/", visitor="v1"))
        s.add(Hit(app_id=a.id, ts=now - dt.timedelta(hours=2), path="/x", visitor="v1"))
        s.add(Hit(app_id=a.id, ts=now - dt.timedelta(hours=3), path="/", visitor="v2"))
        s.add(Hit(app_id=a.id, ts=now - dt.timedelta(hours=30), path="/", visitor="v3"))
        # beta exists but has no hits -> must still emit 0 for both
        b = App(name="beta", repo_url="https://github.com/o/b")
        s.add(b)
        s.commit()

    text = metrics.render(env["db"], now=now)
    assert 'koyracloud_app_views_total{app="alpha"} 4' in text      # all-time
    assert 'koyracloud_app_views_total{app="beta"} 0' in text       # every app visible
    assert 'koyracloud_app_visitors_24h{app="alpha"} 2' in text     # v1,v2 (v3 is >24h)
    assert 'koyracloud_app_visitors_24h{app="beta"} 0' in text
    assert "# TYPE koyracloud_app_visitors_24h gauge" in text


def test_redis_metric_omitted_when_unconfigured(env):
    _seed(env["db"])
    text = metrics.render(env["db"], redis_ping=None)
    assert "koyracloud_redis_up" not in text


def test_redis_down_renders_zero(env):
    _seed(env["db"])
    text = metrics.render(env["db"], redis_ping=lambda: False)
    assert "koyracloud_redis_up 0" in text


def test_metrics_route_is_unauthenticated_text(client, env):
    _seed(env["db"])
    r = client.get("/metrics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert "koyracloud_apps_total 3" in r.text
