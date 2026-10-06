"""Placement constraints and reservations in the rendered stack (#139, phase 1).

KOYRA_APP_CONSTRAINTS goes into every service of every app's stack; a pin
(per-app or KOYRA_APP_NODE) still wins. ``cpu_reserve``/``memory_reserve`` in
the manifest become swarm reservations so the scheduler counts them."""
from dataclasses import replace

from koyracloud.config import Settings
from koyracloud.manifest import parse_manifest
from koyracloud.stack_render import render_stack

MANIFEST = """
name: demo
start: uvicorn app:app
memory: 1G
memory_reserve: 384M
cpu_reserve: "0.25"
workers:
  - name: jobs
    start: celery -A app worker
    memory: 768M
    memory_reserve: 256M
  - name: beat
    start: celery -A app beat
"""

POWER_A = ["node.labels.power==a"]


def _settings(**kw):
    return replace(Settings(apps_domain="apps.example.com", nfs_base="/nfs/koyracloud",
                            nfs_server="", traefik_network="traefik_public"), **kw)


def _render(settings, pin_node=""):
    return render_stack(parse_manifest(MANIFEST), app_name="demo", image="img",
                        env_overrides={}, secret_values={}, settings=settings,
                        pin_node=pin_node)["services"]


def _constraints(svc):
    return (svc["deploy"].get("placement") or {}).get("constraints")


def test_instance_constraints_reach_every_service():
    services = _render(_settings(app_constraints=POWER_A + ["node.role==worker"]))
    assert set(services) == {"demo", "demo-jobs", "demo-beat"}
    for name, svc in services.items():
        assert _constraints(svc) == POWER_A + ["node.role==worker"], name


def test_no_constraints_by_default():
    for svc in _render(_settings()).values():
        assert "placement" not in svc["deploy"]


def test_per_app_pin_wins_over_instance_constraints():
    services = _render(_settings(app_constraints=POWER_A), pin_node="lam")
    for svc in services.values():
        assert _constraints(svc) == ["node.hostname == lam"]


def test_instance_pin_wins_over_instance_constraints():
    services = _render(_settings(app_constraints=POWER_A, app_node="baa"))
    for svc in services.values():
        assert _constraints(svc) == ["node.hostname == baa"]


def test_reservations_from_the_manifest():
    services = _render(_settings())
    web = services["demo"]["deploy"]["resources"]
    assert web["limits"]["memory"] == "1G"
    assert web["reservations"] == {"cpus": "0.25", "memory": "384M"}
    assert services["demo-jobs"]["deploy"]["resources"]["reservations"] == {"memory": "256M"}
    # No reservation asked for: none rendered (swarm reserves nothing).
    assert "reservations" not in services["demo-beat"]["deploy"]["resources"]


def test_constraints_env_var_is_parsed(monkeypatch):
    monkeypatch.setenv("KOYRA_APP_CONSTRAINTS", " node.labels.power==a , node.role==worker,")
    assert Settings().app_constraints == ["node.labels.power==a", "node.role==worker"]
    monkeypatch.setenv("KOYRA_APP_CONSTRAINTS", "")
    assert Settings().app_constraints == []
