"""GitHub App repo access (Vercel-style): the login token is kept per user,
refreshed on expiry, lists the repos the App is installed on, and clones them
ahead of the platform PAT (with a fallback when it cannot see the repo)."""
import datetime as dt
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from koyracloud import auth, github
from koyracloud.app import create_app
from koyracloud.deployer import GIT_TOKEN_SECRET, Deployer
from koyracloud.models import App, Deploy, Secret, User

MANIFEST = "name: priv\nruntime: python\nstart: uvicorn app:app\nport: 8000\n"
TOKEN = {"access_token": "ghu_live", "refresh_token": "ghr_1", "expires_in": 28800}
REPOS = [
    {"full_name": "tester/old", "private": True, "default_branch": "main",
     "html_url": "https://github.com/tester/old", "pushed_at": "2026-01-01T00:00:00Z"},
    {"full_name": "tester/new", "private": False, "default_branch": "develop",
     "html_url": "https://github.com/tester/new", "pushed_at": "2026-09-01T00:00:00Z"},
]


class FakeResp:
    def __init__(self, data):
        self._d = data

    def json(self):
        return self._d

    def raise_for_status(self):
        pass


class FakeGitHub:
    """Stands in for httpx.Client: token exchange/refresh + installations API."""

    def __init__(self, repos=()):
        self.posts = []
        self.repos = list(repos)

    def post(self, url, headers=None, data=None):
        self.posts.append(data)
        if data.get("grant_type") == "refresh_token":
            return FakeResp(dict(TOKEN, access_token="ghu_refreshed", refresh_token="ghr_2"))
        return FakeResp(TOKEN)

    def get(self, url, headers=None, params=None):
        if url.endswith("/user"):
            return FakeResp({"login": "tester"})
        if url.endswith("/user/installations"):
            return FakeResp({"installations": [{"id": 7}]})
        if url.endswith("/user/installations/7/repositories"):
            return FakeResp({"repositories": self.repos})
        raise AssertionError(url)

    def close(self):
        pass


@pytest.fixture
def gh_env(env):
    env["settings"] = replace(env["settings"], github_app_slug="koyra-test",
                              github_client_id="cid", github_client_secret="csec")
    return env


def _client(env):
    deployer = Deployer(settings=env["settings"], docker=env["docker"], crypto=env["crypto"])
    return TestClient(create_app(settings=env["settings"], db=env["db"], docker=env["docker"],
                                 deployer=deployer, run_async=False))


def _callback(env, monkeypatch):
    monkeypatch.setattr(auth, "exchange_code", lambda *a, **k: ("tester", TOKEN))
    c = _client(env)
    c.cookies.set(auth.OAUTH_STATE_COOKIE, "xyz")
    r = c.get("/api/auth/callback?code=abc&state=xyz", follow_redirects=False)
    assert r.status_code == 307
    with env["db"].session() as s:
        return s.query(User).filter_by(github_login="tester").one()


# --- login ------------------------------------------------------------------
def test_login_keeps_github_app_token_encrypted(gh_env, monkeypatch):
    u = _callback(gh_env, monkeypatch)
    assert gh_env["crypto"].decrypt(u.github_token_encrypted) == "ghu_live"
    assert gh_env["crypto"].decrypt(u.github_refresh_encrypted) == "ghr_1"
    assert u.github_token_expires_at is not None
    assert "ghu_live" not in u.github_token_encrypted


def test_login_without_github_app_stores_nothing(env, monkeypatch):
    u = _callback(env, monkeypatch)
    assert u.github_token_encrypted == "" and u.github_token_expires_at is None


def test_authorize_url_drops_scope_for_github_app():
    assert "scope=read%3Auser" in auth.authorize_url("cid", "https://k/cb", "st")
    assert "scope" not in auth.authorize_url("cid", "https://k/cb", "st", scope="")


def test_exchange_code_returns_login_and_token():
    fc = FakeGitHub()
    login, tok = auth.exchange_code("code", "cid", "csec", client=fc)
    assert login == "tester" and tok["access_token"] == "ghu_live"
    assert fc.posts[0]["code"] == "code"


# --- token freshness ----------------------------------------------------------
def _seed_user(env, tok, expires_at=None):
    with env["db"].session() as s:
        u = User(github_login="tester")
        github.store_token(u, tok, env["crypto"])
        if expires_at is not None:
            u.github_token_expires_at = expires_at
        s.add(u)
        s.commit()


def test_user_token_refreshes_when_expired(gh_env):
    _seed_user(gh_env, TOKEN, expires_at=dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1))
    fc = FakeGitHub()
    tok = github.user_token(gh_env["db"], gh_env["crypto"], gh_env["settings"], "tester", client=fc)
    assert tok == "ghu_refreshed"
    assert fc.posts[0]["grant_type"] == "refresh_token" and fc.posts[0]["refresh_token"] == "ghr_1"
    with gh_env["db"].session() as s:
        u = s.query(User).filter_by(github_login="tester").one()
        assert gh_env["crypto"].decrypt(u.github_refresh_encrypted) == "ghr_2"
        assert u.github_token_expires_at > dt.datetime.now()  # naive from SQLite


def test_user_token_uses_stored_token_when_fresh(gh_env):
    _seed_user(gh_env, TOKEN)
    fc = FakeGitHub()
    assert github.user_token(gh_env["db"], gh_env["crypto"], gh_env["settings"], "tester", client=fc) == "ghu_live"
    assert fc.posts == []


def test_user_token_empty_for_unknown_or_unconnected_user(gh_env):
    assert github.user_token(gh_env["db"], gh_env["crypto"], gh_env["settings"], "nobody") == ""
    assert github.user_token(gh_env["db"], gh_env["crypto"], gh_env["settings"], "") == ""


def test_user_token_empty_when_refresh_is_refused(gh_env):
    _seed_user(gh_env, TOKEN, expires_at=dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1))

    class Refusing(FakeGitHub):
        def post(self, url, headers=None, data=None):
            return FakeResp({"error": "bad_refresh_token"})

    assert github.user_token(gh_env["db"], gh_env["crypto"], gh_env["settings"], "tester",
                             client=Refusing()) == ""


# --- repo listing -------------------------------------------------------------
def test_list_repos_newest_push_first():
    out = github.list_repos("ghu_live", client=FakeGitHub(REPOS))
    assert [r["full_name"] for r in out] == ["tester/new", "tester/old"]
    assert out[1] == {"full_name": "tester/old", "private": True, "default_branch": "main",
                      "url": "https://github.com/tester/old"}


def test_repos_route_disabled_without_github_app(client):
    assert client.get("/api/github/repos").json() == {
        "enabled": False, "connected": False, "install_url": "", "repos": []}


def test_repos_route_not_connected_points_at_install(gh_env):
    r = _client(gh_env).get("/api/github/repos").json()
    assert r["enabled"] and not r["connected"]
    assert r["install_url"] == "https://github.com/apps/koyra-test/installations/new"


def test_repos_route_lists_repos_for_connected_user(gh_env, monkeypatch):
    _seed_user(gh_env, TOKEN)
    monkeypatch.setattr(github, "list_repos", lambda token, client=None: [{"full_name": "tester/new"}])
    r = _client(gh_env).get("/api/github/repos").json()
    assert r["connected"] and r["repos"] == [{"full_name": "tester/new"}]


# --- clone token order --------------------------------------------------------
def _seed_app(env, secrets=None, owner_token="ghu_owner"):
    with env["db"].session() as s:
        if owner_token:
            u = User(github_login="tester")
            github.store_token(u, {"access_token": owner_token}, env["crypto"])
            s.add(u)
        app = App(name="priv", repo_url="https://github.com/o/r", branch="main",
                  owner_login="tester", subdomain_token="priv01")
        s.add(app)
        s.flush()
        for k, v in (secrets or {}).items():
            s.add(Secret(app_id=app.id, key=k, value_encrypted=env["crypto"].encrypt(v)))
        dep = Deploy(app_id=app.id, ref="main", status="pending")
        s.add(dep)
        s.commit()
        return dep.id


def _run(env, deploy_id, fail_tokens=()):
    tried = []

    def cloner(repo_url, ref, token, dest):
        tried.append(token)
        if token in fail_tokens:
            raise RuntimeError("git clone failed: remote: Repository not found.")
        (dest / ".paas").mkdir(parents=True, exist_ok=True)
        (dest / ".paas" / "app.yaml").write_text(MANIFEST)
        return "deadbeefcafef00dba5eba11c0ffee0011223344"

    Deployer(settings=env["settings"], docker=env["docker"], crypto=env["crypto"],
             cloner=cloner, redis_admin=env["redis_admin"]).run_deploy(env["db"], deploy_id)
    with env["db"].session() as s:
        d = s.get(Deploy, deploy_id)
        return tried, d.status, d.log


def test_owner_token_clones_before_platform_pat(gh_env):
    gh_env["settings"] = replace(gh_env["settings"], github_pat="ghp_platform")
    tried, status, _ = _run(gh_env, _seed_app(gh_env))
    assert tried == ["ghu_owner"] and status == "live"


def test_falls_back_to_platform_pat_when_owner_token_cannot_see_repo(gh_env):
    gh_env["settings"] = replace(gh_env["settings"], github_pat="ghp_platform")
    tried, status, log = _run(gh_env, _seed_app(gh_env), fail_tokens={"ghu_owner"})
    assert tried == ["ghu_owner", "ghp_platform"] and status == "live"
    assert "retrying with the platform token" in log


def test_app_git_token_secret_overrides_owner_token(gh_env):
    gh_env["settings"] = replace(gh_env["settings"], github_pat="ghp_platform")
    tried, status, _ = _run(gh_env, _seed_app(gh_env, {GIT_TOKEN_SECRET: "ghp_app"}))
    assert tried == ["ghp_app"] and status == "live"


def test_platform_pat_alone_when_owner_never_connected(gh_env):
    gh_env["settings"] = replace(gh_env["settings"], github_pat="ghp_platform")
    tried, status, _ = _run(gh_env, _seed_app(gh_env, owner_token=""))
    assert tried == ["ghp_platform"] and status == "live"


def test_every_token_failing_fails_the_deploy_and_scrubs_tokens(gh_env):
    gh_env["settings"] = replace(gh_env["settings"], github_pat="ghp_platform")
    tried, status, log = _run(gh_env, _seed_app(gh_env), fail_tokens={"ghu_owner", "ghp_platform"})
    assert tried == ["ghu_owner", "ghp_platform"] and status == "failed"
    assert "Repository not found" in log and "GitHub App" in log
    assert "ghu_owner" not in log and "ghp_platform" not in log
