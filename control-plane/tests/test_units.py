"""Unit tests for the pure modules: manifest, crypto, auth, stack_render."""
import pytest

from koyracloud import auth
from koyracloud.config import Settings, _secret
from koyracloud.crypto import CryptoBox, generate_key
from koyracloud.manifest import parse_manifest
from koyracloud.stack_render import app_host, render_stack

VALID = """
name: demo
runtime: python+node
port: 8000
start: uvicorn app:app
healthcheck: /health
subdomain: demo.apps.koyracloud.com
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


# --- stack_render -----------------------------------------------------------
def _settings():
    return Settings(apps_domain="apps.koyracloud.com", nfs_base="/nfs/koyracloud",
                    runtime_image="img:latest", traefik_network="traefik_public",
                    cert_resolver="letsencrypt", https_entrypoint="websecure")


def test_app_host_uses_manifest_subdomain():
    m = parse_manifest(VALID)
    assert app_host(m, "demo", _settings()) == "demo.apps.koyracloud.com"


def test_app_host_derives_when_blank():
    m = parse_manifest("name: x\nstart: y\nport: 8000\n")
    assert app_host(m, "x", _settings()) == "x.apps.koyracloud.com"


def test_render_stack_traefik_and_mounts():
    m = parse_manifest(VALID)
    stack = render_stack(m, app_name="demo", repo_url="https://github.com/o/r",
                         ref="abc", git_token="tok", env_overrides={"B": "2"},
                         secret_values={"SECRET_KEY": "v"}, settings=_settings())
    svc = stack["services"]["demo"]
    labels = svc["deploy"]["labels"]
    assert "traefik.enable=true" in labels
    assert any("Host(`demo.apps.koyracloud.com`)" in l for l in labels)
    assert any("loadbalancer.server.port=8000" in l for l in labels)
    assert svc["volumes"] == ["/nfs/koyracloud/demo:/workspace"]
    assert svc["deploy"]["update_config"]["order"] == "start-first"
    assert stack["networks"]["traefik_public"]["external"] is True


def test_render_stack_env_precedence_and_injection():
    m = parse_manifest(VALID)  # manifest env A=1
    stack = render_stack(m, app_name="demo", repo_url="https://github.com/o/r",
                         ref="sha1", git_token="tok", env_overrides={"A": "override"},
                         secret_values={"SECRET_KEY": "v"}, settings=_settings())
    env = stack["services"]["demo"]["environment"]
    assert env["A"] == "override"            # control-plane env overrides manifest
    assert env["SECRET_KEY"] == "v"          # secret injected
    assert env["KOYRA_REPO_URL"] == "https://github.com/o/r"
    assert env["KOYRA_REF"] == "sha1"
    assert env["KOYRA_GIT_TOKEN"] == "tok"


def test_render_stack_no_constraint_by_default():
    m = parse_manifest(VALID)
    stack = render_stack(m, app_name="demo", repo_url="https://github.com/o/r",
                         ref="abc", git_token="", env_overrides={},
                         secret_values={}, settings=_settings())
    assert "placement" not in stack["services"]["demo"]["deploy"]


def test_render_stack_pins_to_app_node():
    from dataclasses import replace
    s = replace(_settings(), app_node="node1")
    m = parse_manifest(VALID)
    stack = render_stack(m, app_name="demo", repo_url="https://github.com/o/r",
                         ref="abc", git_token="", env_overrides={},
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
    stack = render_stack(m, app_name="demo", repo_url="https://github.com/o/r",
                         ref="abc", git_token="", env_overrides={}, secret_values={},
                         settings=_settings(), hosts=["a.example.com", "b.example.com"])
    labels = stack["services"]["demo"]["deploy"]["labels"]
    rule = next(l for l in labels if ".rule=" in l)
    assert "Host(`a.example.com`) || Host(`b.example.com`)" in rule


def test_render_stack_healthcheck_optional():
    m = parse_manifest("name: x\nstart: y\nport: 9000\n")  # no healthcheck
    stack = render_stack(m, app_name="x", repo_url="r", ref="s", git_token="",
                         env_overrides={}, secret_values={}, settings=_settings())
    assert "healthcheck" not in stack["services"]["x"]
