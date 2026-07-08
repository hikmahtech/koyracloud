"""Workers + cron + shared-Redis: provisioning, scheduler, and a full deploy."""
import datetime as dt
from dataclasses import replace

import pytest

from koyracloud import redisbus, scheduler
from koyracloud.deployer import Deployer
from koyracloud.models import App, AppPin, AppRedis, CronJob, CronRun, Deploy

from conftest import make_fake_cloner

BG_MANIFEST = """
name: bg
runtime: python
start: uvicorn app:app
port: 8000
redis: true
persist: [data]
workers:
  - name: events
    start: python -m app.worker
cron:
  - name: nightly
    schedule: "0 2 * * *"
    command: python -m app.jobs.nightly
"""


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _make_app(db, name="bg", *, live=False):
    with db.session() as s:
        app = App(name=name, repo_url="https://github.com/o/r", branch="main",
                  owner_login="tester", subdomain_token="abc123")
        s.add(app)
        s.flush()
        if live:
            s.add(Deploy(app_id=app.id, ref="main", status="live",
                         commit="deadbeefcafef00dba5eba11c0ffee0011223344"))
        s.commit()
        return app.id


# --- redisbus (pure) --------------------------------------------------------
def test_acl_args_scope_and_deny_dangerous():
    args = redisbus.acl_setuser_args("app-bg", "pw", "bg")
    assert "~bg:*" in args and "&bg:*" in args
    assert "-@dangerous" in args and "-@admin" in args
    assert ">pw" in args and "on" in args and args[0] == "reset"


def test_redis_url_format():
    assert redisbus.redis_url("app-bg", "pw", "redis", 6379) == "redis://app-bg:pw@redis:6379/0"


# --- redisbus.provision -----------------------------------------------------
def test_provision_creates_user_and_is_stable(env):
    app_id = _make_app(env["db"])
    admin = env["redis_admin"]
    url1 = redisbus.provision(env["db"], env["crypto"], env["settings"], admin, app_id, "bg")
    url2 = redisbus.provision(env["db"], env["crypto"], env["settings"], admin, app_id, "bg")
    assert url1 == url2                       # stable across redeploys
    assert url1.startswith("redis://app-bg:") and url1.endswith("@redis:6379/0")
    assert admin.users["app-bg"]["prefix"] == "bg"
    with env["db"].session() as s:
        assert s.get(AppRedis, app_id) is not None  # one stored credential


def test_provision_fails_without_instance_redis(env):
    app_id = _make_app(env["db"])
    s = replace(env["settings"], redis_admin_password="")
    with pytest.raises(RuntimeError):
        redisbus.provision(env["db"], env["crypto"], s, env["redis_admin"], app_id, "bg")


# --- scheduler.due_jobs (pure w.r.t. now) -----------------------------------
def _add_cron(db, app_id, schedule="* * * * *", *, last_run=None, created=None):
    with db.session() as s:
        j = CronJob(app_id=app_id, name="nightly", schedule=schedule,
                    command="run", created_at=created or _now(), last_run_at=last_run)
        s.add(j)
        s.commit()
        return j.id


def test_due_jobs_fires_when_overdue(env):
    app_id = _make_app(env["db"])
    jid = _add_cron(env["db"], app_id, created=_now() - dt.timedelta(minutes=5))
    assert scheduler.due_jobs(env["db"], _now()) == [jid]


def test_due_jobs_not_due_before_schedule(env):
    app_id = _make_app(env["db"])
    # next 2am is in the future relative to a just-created job at an off hour
    base = dt.datetime(2026, 6, 16, 3, 0, tzinfo=dt.timezone.utc)
    _add_cron(env["db"], app_id, schedule="0 2 * * *", created=base)
    assert scheduler.due_jobs(env["db"], base + dt.timedelta(hours=1)) == []


def test_due_jobs_respects_last_run(env):
    app_id = _make_app(env["db"])
    jid = _add_cron(env["db"], app_id, last_run=_now() - dt.timedelta(minutes=5),
                    created=_now() - dt.timedelta(days=1))
    assert scheduler.due_jobs(env["db"], _now()) == [jid]
    # after running this minute, the next fire is in the future
    with env["db"].session() as s:
        s.get(CronJob, jid).last_run_at = _now()
        s.commit()
    assert scheduler.due_jobs(env["db"], _now()) == []


def test_due_jobs_skips_running(env):
    app_id = _make_app(env["db"])
    jid = _add_cron(env["db"], app_id, created=_now() - dt.timedelta(minutes=5))
    with env["db"].session() as s:
        s.add(CronRun(cron_job_id=jid, status="running", started_at=_now()))
        s.commit()
    assert scheduler.due_jobs(env["db"], _now()) == []


# --- scheduler.launch -------------------------------------------------------
def test_launch_runs_job_and_records_success(env):
    app_id = _make_app(env["db"], live=True)
    jid = _add_cron(env["db"], app_id)
    run_id = scheduler.launch(env["db"], env["docker"], env["settings"],
                              env["crypto"], jid)
    assert run_id is not None
    job = env["docker"].jobs[0]
    assert job["command"] == "run"
    assert job["image"] == "reg:5000/koyra-app-bg:deadbeefcafe"
    assert env["docker"].removed_services == [job["name"]]
    with env["db"].session() as s:
        run = s.get(CronRun, run_id)
        assert run.status == "success" and run.exit_code == 0
        assert s.get(CronJob, jid).last_run_at is not None


def test_launch_records_failure_on_nonzero_exit(env):
    app_id = _make_app(env["db"], live=True)
    jid = _add_cron(env["db"], app_id)
    env["docker"].job_exit = 1
    run_id = scheduler.launch(env["db"], env["docker"], env["settings"],
                              env["crypto"], jid)
    with env["db"].session() as s:
        assert s.get(CronRun, run_id).status == "failed"


def test_launch_skips_without_live_deploy(env):
    app_id = _make_app(env["db"], live=False)
    jid = _add_cron(env["db"], app_id)
    assert scheduler.launch(env["db"], env["docker"], env["settings"],
                            env["crypto"], jid) is None
    assert env["docker"].jobs == []


def test_launch_injects_redis_url_when_provisioned(env):
    app_id = _make_app(env["db"], live=True)
    redisbus.provision(env["db"], env["crypto"], env["settings"],
                       env["redis_admin"], app_id, "bg")
    jid = _add_cron(env["db"], app_id)
    scheduler.launch(env["db"], env["docker"], env["settings"], env["crypto"], jid)
    assert env["docker"].jobs[0]["env"]["REDIS_URL"].startswith("redis://app-bg:")


# --- full deploy: workers + cron + redis ------------------------------------
def test_deploy_renders_workers_provisions_redis_persists_cron(env):
    app_id = _make_app(env["db"])
    deployer = Deployer(settings=env["settings"], docker=env["docker"],
                        crypto=env["crypto"], cloner=make_fake_cloner(BG_MANIFEST),
                        redis_admin=env["redis_admin"])
    with env["db"].session() as s:
        dep = Deploy(app_id=app_id, ref="main", status="pending")
        s.add(dep)
        s.commit()
        deploy_id = dep.id

    deployer.run_deploy(env["db"], deploy_id)

    with env["db"].session() as s:
        assert s.get(Deploy, deploy_id).status == "live"

    stack_name, stack = env["docker"].deployed[-1]
    assert set(stack["services"]) == {"bg", "bg-events"}
    web_env = stack["services"]["bg"]["environment"]
    assert web_env["REDIS_URL"].startswith("redis://app-bg:")
    assert stack["services"]["bg-events"]["command"] == ["sh", "-c", "python -m app.worker"]
    # Redis user provisioned, cron job persisted
    assert "app-bg" in env["redis_admin"].users
    with env["db"].session() as s:
        assert s.get(AppRedis, app_id) is not None
        jobs = s.query(CronJob).filter_by(app_id=app_id).all()
        assert [j.name for j in jobs] == ["nightly"]


def test_deploy_pins_stateful_app_and_records_node(env):
    with env["db"].session() as s:
        app = App(name="pinned", repo_url="https://github.com/o/r", branch="main",
                  owner_login="tester", subdomain_token="pin123")
        s.add(app)
        s.flush()
        s.add(AppPin(app_id=app.id))  # pinned, node not yet learned
        dep = Deploy(app_id=app.id, ref="main", status="pending")
        s.add(dep)
        s.commit()
        app_id, deploy_id = app.id, dep.id

    deployer = Deployer(settings=env["settings"], docker=env["docker"],
                        crypto=env["crypto"],
                        cloner=make_fake_cloner("name: pinned\nruntime: python\n"
                                                "start: uvicorn app:app\nport: 8000\n"),
                        redis_admin=env["redis_admin"])
    deployer.run_deploy(env["db"], deploy_id)

    # The node the (fake) running service reports gets recorded...
    with env["db"].session() as s:
        assert s.get(Deploy, deploy_id).status == "live"
        assert s.get(AppPin, app_id).node == "node1"
    # ...and the deployed stack carries the swarm placement constraint.
    _, stack = env["docker"].deployed[-1]
    assert stack["services"]["pinned"]["deploy"]["placement"]["constraints"] == \
        ["node.hostname == node1"]


def test_deploy_fails_when_redis_requested_but_unconfigured(env):
    app_id = _make_app(env["db"])
    s_no_redis = replace(env["settings"], redis_admin_password="")
    deployer = Deployer(settings=s_no_redis, docker=env["docker"],
                        crypto=env["crypto"], cloner=make_fake_cloner(BG_MANIFEST),
                        redis_admin=env["redis_admin"])
    with env["db"].session() as s:
        dep = Deploy(app_id=app_id, ref="main", status="pending")
        s.add(dep)
        s.commit()
        deploy_id = dep.id
    deployer.run_deploy(env["db"], deploy_id)
    with env["db"].session() as s:
        assert s.get(Deploy, deploy_id).status == "failed"


def test_sync_cron_removes_dropped_jobs(env):
    app_id = _make_app(env["db"], live=True)
    deployer = Deployer(settings=env["settings"], docker=env["docker"],
                        crypto=env["crypto"], redis_admin=env["redis_admin"])
    from koyracloud.manifest import parse_manifest
    deployer._sync_cron_jobs(env["db"], app_id, parse_manifest(BG_MANIFEST))
    deployer._sync_cron_jobs(env["db"], app_id,
                             parse_manifest("name: bg\nstart: y\nport: 8000\n"))
    with env["db"].session() as s:
        assert s.query(CronJob).filter_by(app_id=app_id).count() == 0


# --- API endpoints ----------------------------------------------------------
def _new_app(client, name):
    return client.post("/api/apps", json={
        "name": name, "repo_url": "https://github.com/o/r"}).json()["id"]


def test_background_endpoint_reports_redis_and_cron(client, env):
    app_id = _new_app(client, "bgapp")
    with env["db"].session() as s:
        s.add(AppRedis(app_id=app_id, username="app-bgapp",
                       password_encrypted=env["crypto"].encrypt("pw")))
        s.add(CronJob(app_id=app_id, name="nightly", schedule="0 2 * * *", command="run"))
        s.commit()
    bg = client.get(f"/api/apps/{app_id}/background").json()
    assert bg["redis"] == {"enabled": True, "prefix": "bgapp"}
    assert bg["cron"][0]["name"] == "nightly" and bg["cron"][0]["last_status"] is None


def test_cron_run_now_records_run_and_log(client, env):
    app_id = _new_app(client, "bgapp2")
    with env["db"].session() as s:
        s.add(Deploy(app_id=app_id, ref="main", status="live",
                     commit="deadbeefcafef00dba5eba11c0ffee0011223344"))
        s.add(CronJob(app_id=app_id, name="job", schedule="* * * * *", command="echo hi"))
        s.commit()
        job_id = s.query(CronJob).filter_by(app_id=app_id).first().id
    assert client.post(f"/api/apps/{app_id}/cron/{job_id}/run").status_code == 202
    # run_async=False → launch ran synchronously
    runs = client.get(f"/api/apps/{app_id}/cron/{job_id}/runs").json()
    assert len(runs) == 1 and runs[0]["status"] == "success"
    log = client.get(f"/api/apps/{app_id}/cron/{job_id}/runs/{runs[0]['id']}/log").json()
    assert log["status"] == "success"
    assert env["docker"].jobs[0]["command"] == "echo hi"


def test_worker_logs_endpoint(client):
    app_id = _new_app(client, "bgapp3")
    logs = client.get(f"/api/apps/{app_id}/workers/events/logs").json()
    assert "logs" in logs


def test_cron_run_log_404_for_foreign_run(client, env):
    a1 = _new_app(client, "bgone")
    a2 = _new_app(client, "bgtwo")
    with env["db"].session() as s:
        s.add(CronJob(app_id=a1, name="j", schedule="* * * * *", command="c"))
        s.commit()
        job_id = s.query(CronJob).filter_by(app_id=a1).first().id
    # job belongs to a1, not a2
    assert client.get(f"/api/apps/{a2}/cron/{job_id}/runs").status_code == 404


def test_delete_app_drops_cron_and_redis(client, env):
    app_id = _new_app(client, "bgdel")
    with env["db"].session() as s:
        s.add(AppRedis(app_id=app_id, username="app-bgdel",
                       password_encrypted=env["crypto"].encrypt("pw")))
        s.add(CronJob(app_id=app_id, name="j", schedule="* * * * *", command="c"))
        s.commit()
    assert client.delete(f"/api/apps/{app_id}").status_code == 204
    with env["db"].session() as s:
        assert s.get(AppRedis, app_id) is None
        assert s.query(CronJob).filter_by(app_id=app_id).count() == 0
    assert "app-bgdel" in env["redis_admin"].deleted
