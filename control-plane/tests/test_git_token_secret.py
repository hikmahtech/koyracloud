"""KOYRA_GIT_TOKEN: a per-app clone token that never reaches the container."""
from dataclasses import replace

from koyracloud.deployer import GIT_TOKEN_SECRET, Deployer
from koyracloud.models import App, Deploy, Secret

MANIFEST = "name: priv\nruntime: python\nstart: uvicorn app:app\nport: 8000\n"


def _app_with_secrets(env, secrets):
    with env["db"].session() as s:
        app = App(name="priv", repo_url="https://github.com/o/r", branch="main",
                  owner_login="tester", subdomain_token="priv01")
        s.add(app)
        s.flush()
        for k, v in secrets.items():
            s.add(Secret(app_id=app.id, key=k, value_encrypted=env["crypto"].encrypt(v)))
        dep = Deploy(app_id=app.id, ref="main", status="pending")
        s.add(dep)
        s.commit()
        return dep.id


def _run(env, deploy_id, settings=None):
    seen = {}

    def cloner(repo_url, ref, token, dest):
        seen["token"] = token
        (dest / ".paas").mkdir(parents=True, exist_ok=True)
        (dest / ".paas" / "app.yaml").write_text(MANIFEST)
        return "deadbeefcafef00dba5eba11c0ffee0011223344"

    Deployer(settings=settings or env["settings"], docker=env["docker"],
             crypto=env["crypto"], cloner=cloner,
             redis_admin=env["redis_admin"]).run_deploy(env["db"], deploy_id)
    with env["db"].session() as s:
        assert s.get(Deploy, deploy_id).status == "live"
    _, stack = env["docker"].deployed[-1]
    return seen["token"], stack["services"]["priv"]["environment"]


def test_app_token_used_for_clone_and_kept_out_of_container(env):
    dep = _app_with_secrets(env, {GIT_TOKEN_SECRET: "ghp_app", "DB_PASS": "pw"})
    token, container_env = _run(env, dep)
    assert token == "ghp_app"
    assert GIT_TOKEN_SECRET not in container_env
    assert container_env["DB_PASS"] == "pw"


def test_falls_back_to_platform_pat_without_app_token(env):
    dep = _app_with_secrets(env, {"DB_PASS": "pw"})
    token, _ = _run(env, dep, replace(env["settings"], github_pat="ghp_platform"))
    assert token == "ghp_platform"
