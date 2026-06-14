"""Unit tests for the pure modules: manifest, crypto, auth, stack_render."""
import pytest

from koyracloud import auth
from koyracloud.config import Settings, _secret
from koyracloud.crypto import CryptoBox, generate_key
from koyracloud.manifest import parse_manifest
from koyracloud.stack_render import app_host, auto_subdomain, render_stack

VALID = """
name: demo
runtime: python+node
port: 8000
start: uvicorn app:app
healthcheck: /health
subdomain: demo.apps.example.com
env: {A: "1"}
secrets: [SECRET_KEY]
"""


# --- manifest ---------------------------------------------------------------
def test_parse_manifest_ok():
    m = parse_manifest(VALID)
    assert m.name == "demo"
    assert m.port == 8000
    assert m.secrets == ["SECRET_KEY"]


def test_parse_manifest_static_ok():
    m = parse_manifest("name: site\nruntime: static\n")  # no start needed
    assert m.runtime == "static"
    assert m.healthcheck == "/"   # defaulted


def test_parse_manifest_bad_runtime():
    with pytest.raises(Exception):
        parse_manifest("name: x\nstart: y\nruntime: ruby\n")


def test_parse_manifest_missing_start():
    with pytest.raises(Exception):
        parse_manifest("name: x\n")


def test_parse_manifest_not_mapping():
    with pytest.raises(ValueError):
        parse_manifest("- a\n- b\n")


# --- crypto -----------------------------------------------------------------
def test_crypto_roundtrip():
    box = CryptoBox(generate_key())
    assert box.decrypt(box.encrypt("s3cr3t")) == "s3cr3t"


def test_crypto_ciphertext_differs_from_plaintext():
    box = CryptoBox(generate_key())
    assert box.encrypt("hello") != "hello"


def test_crypto_ephemeral_flag():
    assert CryptoBox("").ephemeral is True
    assert CryptoBox(generate_key()).ephemeral is False


# --- config secret resolution ----------------------------------------------
def test_secret_prefers_file(tmp_path, monkeypatch):
    f = tmp_path / "sk"
    f.write_text("from-file\n")
    monkeypatch.setenv("KOYRA_SECRET_KEY_FILE", str(f))
    monkeypatch.setenv("KOYRA_SECRET_KEY", "from-env")
    assert _secret("KOYRA_SECRET_KEY") == "from-file"  # file wins, stripped


def test_secret_falls_back_to_env(tmp_path, monkeypatch):
    monkeypatch.delenv("KOYRA_SECRET_KEY_FILE", raising=False)
    monkeypatch.setenv("KOYRA_SECRET_KEY", "from-env")
    assert _secret("KOYRA_SECRET_KEY") == "from-env"


# --- auth -------------------------------------------------------------------
def test_is_allowed():
    assert auth.is_allowed("Arshad", ["arshad", "bob"]) is True
    assert auth.is_allowed("eve", ["arshad"]) is False
    assert auth.is_allowed("anyone", []) is False  # fail-closed


def test_session_roundtrip():
    tok = auth.make_session("arshad", "secret")
    assert auth.read_session(tok, "secret") == "arshad"


def test_session_wrong_secret():
    tok = auth.make_session("arshad", "secret")
    assert auth.read_session(tok, "other") is None


def test_session_expired():
    tok = auth.make_session("arshad", "secret")
    assert auth.read_session(tok, "secret", max_age=-1) is None


def test_authorize_url():
    url = auth.authorize_url("cid", "https://x/cb", "st")
    assert url.startswith("https://github.com/login/oauth/authorize?")
    assert "client_id=cid" in url and "state=st" in url


# --- webhooks ---------------------------------------------------------------
def test_webhook_signature_roundtrip():
    import hashlib
    import hmac

    from koyracloud import webhooks
    body = b'{"ref":"refs/heads/main"}'
    sig = "sha256=" + hmac.new(b"shh", body, hashlib.sha256).hexdigest()
    assert webhooks.verify_signature("shh", body, sig) is True
    assert webhooks.verify_signature("shh", body, "sha256=deadbeef") is False
    assert webhooks.verify_signature("", body, sig) is False
    assert webhooks.verify_signature("shh", body, None) is False


def test_webhook_repo_slug():
    from koyracloud import webhooks
    for url in ["https://github.com/Owner/Repo", "https://github.com/Owner/Repo.git",
                "git@github.com:Owner/Repo.git", "https://github.com/Owner/Repo/"]:
        assert webhooks.repo_slug(url) == "owner/repo"


def test_webhook_branch_from_ref():
    from koyracloud import webhooks
    assert webhooks.branch_from_ref("refs/heads/main") == "main"
    assert webhooks.branch_from_ref("refs/tags/v1") is None


# --- static heuristic -------------------------------------------------------
def test_resolve_manifest_synthesizes_static(tmp_path):
    from koyracloud.deployer import resolve_manifest
    (tmp_path / "index.html").write_text("<html></html>")   # static, no manifest
    m, synthesized = resolve_manifest(tmp_path, "mysite")
    assert synthesized is True and m.runtime == "static" and m.name == "mysite"
    assert (tmp_path / ".paas" / "app.yaml").is_file()      # written to the volume


def test_resolve_manifest_prefers_real(tmp_path):
    from koyracloud.deployer import resolve_manifest
    (tmp_path / ".paas").mkdir()
    (tmp_path / ".paas" / "app.yaml").write_text("name: a\nruntime: python\nstart: x\n")
    m, synthesized = resolve_manifest(tmp_path, "a")
    assert synthesized is False and m.runtime == "python"


def test_resolve_manifest_errors_when_not_static(tmp_path):
    import pytest as _pytest
    from koyracloud.deployer import resolve_manifest
    (tmp_path / "server.py").write_text("print('hi')")       # no manifest, not static
    with _pytest.raises(FileNotFoundError):
        resolve_manifest(tmp_path, "a")


# --- notifier ---------------------------------------------------------------
def test_render_event():
    from koyracloud import notifier
    subj, html = notifier.render_event("deploy_failed", "myapp", "boom", "myapp.example.com")
    assert "myapp" in subj and "failed" in subj.lower()
    assert "boom" in html
    subj2, _ = notifier.render_event("down", "myapp", host="myapp.example.com")
    assert "down" in subj2.lower()


def test_render_event_escapes_html():
    from koyracloud import notifier
    _, body = notifier.render_event("deploy_failed", "app",
                                    detail="<script>alert(1)</script>", host="")
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body


def test_send_email_inert_without_key():
    from koyracloud import notifier
    s = Settings(resend_api_key="")
    assert notifier.send_email(s, "to@x.com", "s", "<b>") is False


def test_send_email_posts_with_key():
    from koyracloud import notifier

    class FakeResp:
        status_code = 200

    class FakeClient:
        def __init__(self):
            self.calls = []

        def post(self, url, headers=None, json=None):
            self.calls.append((url, headers, json))
            return FakeResp()

        def close(self):
            pass

    fc = FakeClient()
    s = Settings(resend_api_key="re_test", email_from="koyracloud <d@k.com>")
    assert notifier.send_email(s, "to@x.com", "subj", "<b>hi</b>", client=fc) is True
    url, headers, payload = fc.calls[0]
    assert url.endswith("/emails")
    assert headers["Authorization"] == "Bearer re_test"
    assert payload["to"] == ["to@x.com"] and payload["from"] == "koyracloud <d@k.com>"


# --- analytics --------------------------------------------------------------
def test_visitor_hash_stable_and_daily_rotation():
    from koyracloud import analytics
    a = analytics.visitor_hash("sec", "site", "1.2.3.4", "ua", day="2026-06-11")
    b = analytics.visitor_hash("sec", "site", "1.2.3.4", "ua", day="2026-06-11")
    c = analytics.visitor_hash("sec", "site", "1.2.3.4", "ua", day="2026-06-12")
    assert a == b and a != c and len(a) == 16


def test_visitor_hash_differs_by_visitor():
    from koyracloud import analytics
    a = analytics.visitor_hash("sec", "site", "1.2.3.4", "ua", day="d")
    b = analytics.visitor_hash("sec", "site", "9.9.9.9", "ua", day="d")
    assert a != b


def test_analytics_render_injects_env():
    m = parse_manifest("name: site\nruntime: static\n")
    stack = render_stack(m, app_name="site", image="img", env_overrides={}, secret_values={},
                         settings=_settings(), analytics_site="tok123")
    env = stack["services"]["site"]["environment"]
    assert env["KOYRA_ANALYTICS_SITE"] == "tok123" and "KOYRA_ANALYTICS_URL" in env


# --- stack_render -----------------------------------------------------------
def _settings():
    return Settings(apps_domain="apps.example.com", nfs_base="/nfs/koyracloud",
                    nfs_server="10.0.0.9",
                    runtime_image="img:latest", traefik_network="traefik_public",
                    cert_resolver="letsencrypt", https_entrypoint="websecure")


def test_app_host_uses_manifest_subdomain():
    m = parse_manifest(VALID)
    assert app_host(m, "demo", _settings()) == "demo.apps.example.com"


def test_app_host_derives_when_blank():
    m = parse_manifest("name: x\nstart: y\nport: 8000\n")
    assert app_host(m, "x", _settings()) == "x.apps.example.com"


def test_auto_subdomain_appends_token():
    assert auto_subdomain("demo", "ab12cd", _settings()) == "demo-ab12cd.apps.example.com"
    # no token (pre-token apps) → bare name
    assert auto_subdomain("demo", "", _settings()) == "demo.apps.example.com"


def test_app_host_derives_with_token():
    m = parse_manifest("name: x\nstart: y\nport: 8000\n")
    assert app_host(m, "x", _settings(), token="ab12cd") == "x-ab12cd.apps.example.com"


def test_render_stack_traefik_and_image():
    m = parse_manifest(VALID)
    stack = render_stack(m, app_name="demo", image="reg/koyra-app-demo:abc",
                         env_overrides={"B": "2"},
                         secret_values={"SECRET_KEY": "v"}, settings=_settings())
    svc = stack["services"]["demo"]
    labels = svc["deploy"]["labels"]
    assert "traefik.enable=true" in labels
    assert any("Host(`demo.apps.example.com`)" in l for l in labels)
    assert any("loadbalancer.server.port=8000" in l for l in labels)
    assert svc["image"] == "reg/koyra-app-demo:abc"   # runs the prebuilt image
    assert "volumes" not in svc                         # no persist dirs → no NFS mount
    assert svc["deploy"]["update_config"]["order"] == "start-first"
    assert stack["networks"]["traefik_public"]["external"] is True


def test_render_stack_persist_nfs_volumes_no_pinning():
    # With an NFS server configured, persist dirs are NFS-driver volumes (Docker
    # mounts the NFS on whichever node runs the app), and the app is NOT pinned.
    m = parse_manifest("name: x\nstart: y\nport: 8000\npersist: [data, uploads]\n")
    stack = render_stack(m, app_name="x", image="img", env_overrides={},
                         secret_values={}, settings=_settings())
    svc = stack["services"]["x"]
    assert svc["volumes"] == ["koyra-x-data:/app/data", "koyra-x-uploads:/app/uploads"]
    assert "placement" not in svc["deploy"]      # no node pin
    vol = stack["volumes"]["koyra-x-data"]
    assert vol["driver"] == "local"
    assert vol["driver_opts"]["type"] == "nfs"
    assert vol["driver_opts"]["o"] == "addr=10.0.0.9,rw,nfsvers=4"
    assert vol["driver_opts"]["device"] == ":/nfs/koyracloud/x/data"


def test_render_stack_persist_bind_fallback_without_nfs_server():
    from dataclasses import replace
    s = replace(_settings(), nfs_server="")
    m = parse_manifest("name: x\nstart: y\nport: 8000\npersist: [data]\n")
    stack = render_stack(m, app_name="x", image="img", env_overrides={},
                         secret_values={}, settings=s)
    assert stack["services"]["x"]["volumes"] == ["/nfs/koyracloud/x/data:/app/data"]
    assert "volumes" not in stack                # no named NFS volumes


def test_render_stack_env_precedence_no_koyra_runtime_vars():
    m = parse_manifest(VALID)  # manifest env A=1
    stack = render_stack(m, app_name="demo", image="img",
                         env_overrides={"A": "override"},
                         secret_values={"SECRET_KEY": "v"}, settings=_settings())
    env = stack["services"]["demo"]["environment"]
    assert env["A"] == "override"            # control-plane env overrides manifest
    assert env["SECRET_KEY"] == "v"          # secret injected
    # runtime no longer clones — no KOYRA_REPO_URL/REF/GIT_TOKEN/WORKSPACE leak
    assert not any(k.startswith("KOYRA_REPO") or k.startswith("KOYRA_REF")
                   or k.startswith("KOYRA_GIT") or k.startswith("KOYRA_WORK") for k in env)


def test_render_stack_no_constraint_by_default():
    m = parse_manifest(VALID)
    stack = render_stack(m, app_name="demo", image="img", env_overrides={},
                         secret_values={}, settings=_settings())
    assert "placement" not in stack["services"]["demo"]["deploy"]


def test_render_stack_pins_to_app_node():
    from dataclasses import replace
    s = replace(_settings(), app_node="node1")
    m = parse_manifest(VALID)
    stack = render_stack(m, app_name="demo", image="img", env_overrides={},
                         secret_values={}, settings=s)
    assert stack["services"]["demo"]["deploy"]["placement"]["constraints"] == \
        ["node.hostname == node1"]


def test_docker_control_resolve_image_never_flag():
    from koyracloud.docker_ctl import CLIDockerControl
    calls = []
    dc = CLIDockerControl(resolve_image_never=True)
    dc._stream = lambda args: calls.append(args) or iter(())
    list(dc.deploy("demo", {"services": {}}))
    assert any("--resolve-image=never" in a for a in calls)


def test_render_stack_multi_host_rule():
    m = parse_manifest(VALID)
    stack = render_stack(m, app_name="demo", image="img", env_overrides={}, secret_values={},
                         settings=_settings(), hosts=["a.example.com", "b.example.com"])
    labels = stack["services"]["demo"]["deploy"]["labels"]
    rule = next(l for l in labels if ".rule=" in l)
    assert "Host(`a.example.com`) || Host(`b.example.com`)" in rule


def test_render_stack_splits_saas_and_apps_routers():
    # The in-zone auto-subdomain keeps the Let's Encrypt resolver; a custom
    # (Cloudflare-for-SaaS) host gets its OWN router with TLS but no resolver —
    # CF terminates its TLS at the edge, so Traefik must not ACME-mint for it.
    m = parse_manifest(VALID)
    stack = render_stack(m, app_name="demo", image="img",
                         env_overrides={}, secret_values={}, settings=_settings(),
                         hosts=["demo.apps.example.com", "shop.example.com"])
    labels = stack["services"]["demo"]["deploy"]["labels"]
    apps_rule = next(l for l in labels if l.startswith("traefik.http.routers.koyra-demo.rule="))
    assert "Host(`demo.apps.example.com`)" in apps_rule and "shop.example.com" not in apps_rule
    assert any("routers.koyra-demo.tls.certresolver=letsencrypt" in l for l in labels)
    saas_rule = next(l for l in labels if l.startswith("traefik.http.routers.koyra-demo-saas.rule="))
    assert "Host(`shop.example.com`)" in saas_rule and "apps.example.com" not in saas_rule
    assert not any("koyra-demo-saas.tls.certresolver" in l for l in labels)
    assert any("routers.koyra-demo-saas.tls=true" in l for l in labels)
    # both routers share the one service definition carrying the app port
    assert any("services.koyra-demo.loadbalancer.server.port=8000" in l for l in labels)
    assert any("routers.koyra-demo-saas.service=koyra-demo" in l for l in labels)


def test_render_stack_custom_only_host_has_no_certresolver():
    m = parse_manifest(VALID)
    stack = render_stack(m, app_name="demo", image="img",
                         env_overrides={}, secret_values={}, settings=_settings(),
                         hosts=["shop.example.com"])
    labels = stack["services"]["demo"]["deploy"]["labels"]
    assert not any("certresolver" in l for l in labels)
    assert any("Host(`shop.example.com`)" in l for l in labels)


def test_render_stack_apps_domain_proxied_skips_certresolver():
    # When apps_domain is fronted by a TLS-terminating proxy, even the in-zone
    # auto-subdomain must NOT carry a Let's Encrypt resolver — the edge serves it.
    from dataclasses import replace
    s = replace(_settings(), apps_domain_proxied=True)
    m = parse_manifest(VALID)
    stack = render_stack(m, app_name="demo", image="img",
                         env_overrides={}, secret_values={}, settings=s,
                         hosts=["demo.apps.example.com"])
    labels = stack["services"]["demo"]["deploy"]["labels"]
    assert not any("certresolver" in l for l in labels)
    assert any("routers.koyra-demo.tls=true" in l for l in labels)
    assert any("Host(`demo.apps.example.com`)" in l for l in labels)


def test_render_stack_resource_limits_default_and_override():
    s = _settings()
    m = parse_manifest(VALID)
    lim = render_stack(m, app_name="demo", image="img",
                       env_overrides={}, secret_values={}, settings=s
                       )["services"]["demo"]["deploy"]["resources"]["limits"]
    assert lim == {"cpus": s.default_cpu, "memory": s.default_memory}
    m2 = parse_manifest("name: x\nstart: y\nport: 8000\ncpu: '0.25'\nmemory: 128M\n")
    lim2 = render_stack(m2, app_name="x", image="img",
                        env_overrides={}, secret_values={}, settings=s
                        )["services"]["x"]["deploy"]["resources"]["limits"]
    assert lim2 == {"cpus": "0.25", "memory": "128M"}


def test_db_backup_once_and_prune(tmp_path):
    import sqlite3

    from koyracloud import backup
    src = tmp_path / "koyracloud.db"
    sqlite3.connect(str(src)).execute("create table t(x)")
    bdir = tmp_path / "backups"
    for i in range(5):
        backup.backup_once(src, bdir, keep=3, stamp=f"2026010{i}-000000")
    files = sorted(bdir.glob("koyracloud-*.db"))
    assert len(files) == 3                       # pruned to keep=3
    assert files[0].name == "koyracloud-20260102-000000.db"  # oldest kept


def test_sqlite_file_parsing():
    from koyracloud import backup
    assert str(backup.sqlite_file("sqlite:////data/koyracloud.db")) == "/data/koyracloud.db"
    assert backup.sqlite_file("postgresql://x/y") is None


def test_rate_limiter():
    from koyracloud.ratelimit import RateLimiter
    rl = RateLimiter(limit=2, window=60)
    assert rl.allow("ip", now=0) and rl.allow("ip", now=1)  # 2 allowed
    assert not rl.allow("ip", now=2)                        # 3rd blocked
    assert rl.allow("other", now=2)                         # different key ok
    assert rl.allow("ip", now=61)                           # next window resets


def test_deployer_lock_per_app():
    from koyracloud.config import Settings
    from koyracloud.deployer import Deployer
    d = Deployer(settings=Settings(), docker=None, crypto=None)
    assert d._lock_for(1) is d._lock_for(1)      # same app → same lock
    assert d._lock_for(1) is not d._lock_for(2)  # different app → different lock


def test_render_stack_healthcheck_optional():
    m = parse_manifest("name: x\nstart: y\nport: 9000\n")  # no healthcheck
    stack = render_stack(m, app_name="x", image="img",
                         env_overrides={}, secret_values={}, settings=_settings())
    assert "healthcheck" not in stack["services"]["x"]


# --- cloudflare (for SaaS custom hostnames) ---------------------------------
class _FakeCFResp:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


class _FakeCFClient:
    """Pops one queued (status_code, json_body) per request; records calls."""
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, headers=None, json=None, params=None):
        self.calls.append((method, url, headers, json, params))
        return _FakeCFResp(*self.responses.pop(0))

    def close(self):
        pass


def test_customer_records_pure():
    from koyracloud import cloudflare
    recs = cloudflare.customer_records("shop.example.com", "origin.example.com", "abc123")
    assert recs[0] == {"type": "CNAME", "name": "shop.example.com",
                       "value": "origin.example.com"}
    assert recs[1] == {"type": "CNAME", "name": "_acme-challenge.shop.example.com",
                       "value": "shop.example.com.abc123.dcv.cloudflare.com"}


def test_customer_records_traffic_only_without_dcv():
    from koyracloud import cloudflare
    recs = cloudflare.customer_records("shop.example.com", "origin.example.com", "")
    assert len(recs) == 1 and recs[0]["name"] == "shop.example.com"


def test_cloudflare_noop_when_unconfigured():
    from koyracloud import cloudflare
    cf = cloudflare.Cloudflare(Settings(cloudflare_api_token="", cloudflare_zone_id=""))
    assert cf.configured is False
    assert cf.create_custom_hostname("shop.example.com") is None
    assert cf.get_custom_hostname("ch_1") is None
    assert cf.delete_custom_hostname("ch_1") is False
    assert cf.dcv_uuid() == ""


def test_cloudflare_create_custom_hostname():
    from koyracloud import cloudflare
    fc = _FakeCFClient([
        (200, {"success": True, "result": []}),   # GET ?hostname= → none exists yet
        (200, {"success": True, "result": {       # POST → created
            "id": "ch_1", "status": "pending",
            "ssl": {"status": "pending_validation"},
            "ownership_verification": {"type": "txt", "name": "_cf", "value": "v"}}})])
    s = Settings(cloudflare_api_token="tok", cloudflare_zone_id="zoneid")
    cf = cloudflare.Cloudflare(s, client=fc)
    out = cf.create_custom_hostname("shop.example.com")
    assert out["id"] == "ch_1"
    assert out["status"] == "pending"
    assert out["ssl_status"] == "pending_validation"
    # checks existence first, then POSTs the create
    assert fc.calls[0][0] == "GET" and fc.calls[0][4] == {"hostname": "shop.example.com"}
    method, url, headers, body, _ = fc.calls[1]
    assert method == "POST" and url.endswith("/zones/zoneid/custom_hostnames")
    assert headers["Authorization"] == "Bearer tok"
    assert body["hostname"] == "shop.example.com"
    assert body["ssl"]["method"] == "txt" and body["ssl"]["type"] == "dv"


def test_cloudflare_create_adopts_existing():
    """Idempotent: when CF already has the hostname, adopt its id, don't POST."""
    from koyracloud import cloudflare
    fc = _FakeCFClient([(200, {"success": True, "result": [
        {"id": "ch_existing", "status": "active", "ssl": {"status": "active"}}]})])
    s = Settings(cloudflare_api_token="tok", cloudflare_zone_id="zoneid")
    cf = cloudflare.Cloudflare(s, client=fc)
    out = cf.create_custom_hostname("shop.example.com")
    assert out["id"] == "ch_existing" and out["status"] == "active"
    assert len(fc.calls) == 1 and fc.calls[0][0] == "GET"  # adopted; no POST


def test_cloudflare_error_returns_none():
    from koyracloud import cloudflare
    fc = _FakeCFClient([
        (200, {"success": True, "result": []}),                    # GET → none
        (400, {"success": False, "errors": [{"message": "bad"}]})])  # POST fails
    s = Settings(cloudflare_api_token="tok", cloudflare_zone_id="zoneid")
    cf = cloudflare.Cloudflare(s, client=fc)
    assert cf.create_custom_hostname("shop.example.com") is None


def test_cloudflare_get_custom_hostname():
    from koyracloud import cloudflare
    fc = _FakeCFClient([(200, {"success": True, "result": {
        "id": "ch_1", "status": "active", "ssl": {"status": "active"}}})])
    s = Settings(cloudflare_api_token="tok", cloudflare_zone_id="zoneid")
    cf = cloudflare.Cloudflare(s, client=fc)
    out = cf.get_custom_hostname("ch_1")
    assert out["status"] == "active" and out["ssl_status"] == "active"
    method, url, *_ = fc.calls[0]
    assert method == "GET" and url.endswith("/custom_hostnames/ch_1")


def test_cloudflare_delete_custom_hostname():
    from koyracloud import cloudflare
    fc = _FakeCFClient([(200, {"success": True, "result": {"id": "ch_1"}})])
    s = Settings(cloudflare_api_token="tok", cloudflare_zone_id="zoneid")
    cf = cloudflare.Cloudflare(s, client=fc)
    assert cf.delete_custom_hostname("ch_1") is True
    method, url, *_ = fc.calls[0]
    assert method == "DELETE" and url.endswith("/custom_hostnames/ch_1")


def test_cloudflare_dcv_uuid_cached():
    from koyracloud import cloudflare
    fc = _FakeCFClient([(200, {"success": True, "result": {"uuid": "bc21f3"}})])
    s = Settings(cloudflare_api_token="tok", cloudflare_zone_id="zoneid")
    cf = cloudflare.Cloudflare(s, client=fc)
    assert cf.dcv_uuid() == "bc21f3"
    assert cf.dcv_uuid() == "bc21f3"  # cached — no second API call
    assert len(fc.calls) == 1


def test_migrate_adds_domain_cert_ownership_columns(tmp_path):
    # Simulates the prod upgrade: an existing domain_certs table without the
    # ownership columns must be ALTERed in place (create_all never alters).
    from sqlalchemy import create_engine, inspect, text

    from koyracloud.db import Database
    url = f"sqlite:///{tmp_path / 'm.db'}"
    seed = create_engine(url)
    with seed.begin() as c:
        c.execute(text("CREATE TABLE apps (id INTEGER PRIMARY KEY, owner_login VARCHAR)"))
        c.execute(text("CREATE TABLE domain_certs (domain_id INTEGER PRIMARY KEY, "
                       "cf_hostname_id VARCHAR, ssl_status VARCHAR, ownership_status VARCHAR, "
                       "dcv_target VARCHAR, last_checked DATETIME)"))
    db = Database(url)
    db._migrate()
    cols = {col["name"] for col in inspect(db.engine).get_columns("domain_certs")}
    assert "ownership_name" in cols and "ownership_value" in cols
    db._migrate()  # idempotent — second run is a no-op


# --- webhook deploy_target (push + workflow_run) ----------------------------
def test_deploy_target_push():
    from koyracloud import webhooks
    assert webhooks.deploy_target("push", {
        "repository": {"full_name": "Owner/Repo"}, "ref": "refs/heads/main",
        "after": "abc123"}) == ("owner/repo", "main", "abc123")
    # a tag push doesn't deploy
    assert webhooks.deploy_target("push", {
        "repository": {"full_name": "o/r"}, "ref": "refs/tags/v1"}) is None


def test_deploy_target_workflow_run():
    from koyracloud import webhooks
    ok = {"action": "completed", "repository": {"full_name": "O/R"},
          "workflow_run": {"conclusion": "success", "head_branch": "main",
                           "head_sha": "deadbeef"}}
    assert webhooks.deploy_target("workflow_run", ok) == ("o/r", "main", "deadbeef")
    # failed CI does NOT deploy
    bad = {"action": "completed", "repository": {"full_name": "o/r"},
           "workflow_run": {"conclusion": "failure", "head_branch": "main"}}
    assert webhooks.deploy_target("workflow_run", bad) is None
    # in-progress run does NOT deploy
    pending = {"action": "requested", "repository": {"full_name": "o/r"},
               "workflow_run": {"head_branch": "main"}}
    assert webhooks.deploy_target("workflow_run", pending) is None
    assert webhooks.deploy_target("ping", {}) is None


# --- manifest: dockerfile runtime -------------------------------------------
def test_manifest_dockerfile_runtime_needs_no_start():
    m = parse_manifest("name: x\nruntime: dockerfile\nport: 8000\n")
    assert m.uses_dockerfile is True
    m2 = parse_manifest("name: y\ndockerfile: docker/Dockerfile\nport: 3000\n")
    assert m2.uses_dockerfile is True and m2.dockerfile == "docker/Dockerfile"
    m3 = parse_manifest("name: z\nstart: run\nport: 8000\n")
    assert m3.uses_dockerfile is False
