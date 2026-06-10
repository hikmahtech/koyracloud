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
subdomain: lens.apps.koyracloud.com
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
  CORS_ORIGINS: https://lens.apps.koyracloud.com
secrets:
  - SECRET_KEY
"""


class FakeDocker:
    def __init__(self):
        self.deployed = []
        self.removed = []
        self.builds = []
        self.events = []  # ordered record of calls

    def build(self, image, env, volume):
        self.builds.append((image, env, volume))
        self.events.append("build")
        yield f"fake-build {image}"

    def deploy(self, stack, stack_dict):
        self.deployed.append((stack, stack_dict))
        self.events.append("deploy")
        yield f"fake-deploy {stack}"

    def remove(self, stack):
        self.removed.append(stack)
        yield f"fake-rm {stack}"


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
        dev_login="tester",
        github_pat="",
    )


@pytest.fixture
def env(settings):
    db = Database(settings.db_url)
    db.create_all()
    docker = FakeDocker()
    crypto = CryptoBox(settings.secret_key)
    deployer = Deployer(settings=settings, docker=docker, crypto=crypto,
                        cloner=make_fake_cloner())
    return {"db": db, "docker": docker, "crypto": crypto, "deployer": deployer,
            "settings": settings}


@pytest.fixture
def client(env):
    from fastapi.testclient import TestClient

    from koyracloud.app import create_app
    app = create_app(settings=env["settings"], db=env["db"], docker=env["docker"],
                     deployer=env["deployer"], run_async=False)
    return TestClient(app)
