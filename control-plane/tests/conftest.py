import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from koyracloud.config import Settings  # noqa: E402
from koyracloud.crypto import CryptoBox, generate_key  # noqa: E402
from koyracloud.db import Database  # noqa: E402
from koyracloud.deployer import Deployer  # noqa: E402

LENS_MANIFEST = """
name: lens-inventory
runtime: python+node
subdomain: lens.apps.example.com
port: 8000
build:
  - pip install -r requirements.txt
predeploy:
  - alembic upgrade head
start: uvicorn app.main:app --host 0.0.0.0 --port 8000
persist:
  - data
healthcheck: /health
env:
  CORS_ORIGINS: https://lens.apps.example.com
secrets:
  - SECRET_KEY
"""


class FakeDocker:
    def __init__(self):
        self.deployed = []
        self.removed = []
        self.builds = []   # (tag, context_dir, build_args, dockerfile)
        self.pushed = []
        self.tagged = []
        self.events = []   # ordered record of calls
        self.jobs = []     # run_job calls (cron)
        self.removed_services = []
        self.job_exit = 0  # exit code job_wait returns

    def image_build(self, tag, context_dir, build_args=None, dockerfile=None):
        self.builds.append((tag, context_dir, build_args or {}, dockerfile))
        self.events.append("build")
        yield f"fake-build {tag}"

    def image_tag(self, src, dst):
        self.tagged.append((src, dst))

    def image_push(self, tag):
        self.pushed.append(tag)
        self.events.append("push")
        yield f"fake-push {tag}"

    def deploy(self, stack, stack_dict):
        self.deployed.append((stack, stack_dict))
        self.events.append("deploy")
        yield f"fake-deploy {stack}"

    def remove(self, stack):
        self.removed.append(stack)
        yield f"fake-rm {stack}"

    def service_logs(self, service, tail=200):
        return f"log line for {service} (tail={tail})"

    def service_status(self, service):
        return {"exists": True, "running": 1, "desired": 1,
                "tasks": [{"state": "Running 2 minutes ago", "desired": "Running",
                           "error": "", "node": "node1"}]}

    def services_overview(self):
        # Every deployed stack's service shows running 1/1.
        out = {}
        for stack, sd in self.deployed:
            for svc in (sd.get("services") or {}):
                out[f"{stack}_{svc}"] = {"running": 1, "desired": 1}
        return out

    def run_job(self, name, image, command, env=None, networks=None):
        self.jobs.append({"name": name, "image": image, "command": command,
                          "env": env or {}, "networks": networks or []})

    def job_wait(self, name, timeout=600):
        return self.job_exit

    def remove_service(self, name):
        self.removed_services.append(name)


class FakeRedisAdmin:
    def __init__(self):
        self.users = {}      # username -> {password, prefix}
        self.deleted = []

    def set_user(self, username, password, prefix):
        self.users[username] = {"password": password, "prefix": prefix}

    def delete_user(self, username):
        self.deleted.append(username)


def make_fake_cloner(manifest_text=LENS_MANIFEST):
    def cloner(repo_url, ref, token, dest: Path) -> str:
        (dest / ".paas").mkdir(parents=True, exist_ok=True)
        (dest / ".paas" / "app.yaml").write_text(manifest_text)
        return "deadbeefcafef00dba5eba11c0ffee0011223344"
    return cloner


@pytest.fixture
def settings(tmp_path):
    return Settings(
        db_url=f"sqlite:///{tmp_path / 'koyra.db'}",
        secret_key=generate_key(),
        nfs_base=str(tmp_path / "nfs"),
        build_dir=str(tmp_path / "build"),
        registry="reg:5000",
        nfs_server="10.0.0.9",
        dev_login="tester",
        github_pat="",
        webhook_secret="testhooksecret",
        redis_admin_password="testredisadmin",
    )


@pytest.fixture
def env(settings):
    db = Database(settings.db_url)
    db.create_all()
    docker = FakeDocker()
    crypto = CryptoBox(settings.secret_key)
    redis_admin = FakeRedisAdmin()
    deployer = Deployer(settings=settings, docker=docker, crypto=crypto,
                        cloner=make_fake_cloner(), redis_admin=redis_admin)
    return {"db": db, "docker": docker, "crypto": crypto, "deployer": deployer,
            "settings": settings, "redis_admin": redis_admin}


@pytest.fixture
def client(env):
    from fastapi.testclient import TestClient

    from koyracloud.app import create_app
    app = create_app(settings=env["settings"], db=env["db"], docker=env["docker"],
                     deployer=env["deployer"], run_async=False)
    return TestClient(app)


@pytest.fixture
def scoped(tmp_path):
    """A control-plane with REAL session auth (no dev-login bypass) so the
    admin-vs-member scoping can be exercised. ``operator`` is the sole admin
    (KOYRA_ALLOWED_LOGINS); everyone else must be invited as a member to get in.
    Returns helpers to mint a per-login authenticated client and invite members."""
    from fastapi.testclient import TestClient

    from koyracloud import auth
    from koyracloud.app import create_app
    from koyracloud.models import AllowedUser

    settings = Settings(
        db_url=f"sqlite:///{tmp_path / 'koyra.db'}",
        secret_key=generate_key(),
        nfs_base=str(tmp_path / "nfs"),
        build_dir=str(tmp_path / "build"),
        registry="reg:5000",
        nfs_server="10.0.0.9",
        dev_login="",                 # no bypass: requests authenticate via cookie
        allowed_logins=["operator"],  # the single all-seeing admin
        github_pat="",
        webhook_secret="testhooksecret",
    )
    db = Database(settings.db_url)
    db.create_all()
    deployer = Deployer(settings=settings, docker=FakeDocker(),
                        crypto=CryptoBox(settings.secret_key),
                        cloner=make_fake_cloner())
    app = create_app(settings=settings, db=db, docker=FakeDocker(),
                     deployer=deployer, run_async=False)

    def as_user(login: str):
        c = TestClient(app)
        c.cookies.set(auth.SESSION_COOKIE,
                      auth.make_session(login, settings.session_secret))
        return c

    def invite(login: str) -> None:
        with db.session() as s:
            s.add(AllowedUser(login=login.lower(), added_by="operator"))
            s.commit()

    return {"as_user": as_user, "invite": invite, "db": db, "settings": settings}
