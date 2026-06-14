"""End-to-end API tests with injected fake docker + cloner and synchronous deploy."""
import json
import re


def test_health_unauthenticated(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_me_dev_login(client):
    assert client.get("/api/me").json()["login"] == "tester"


def test_public_config(client):
    cfg = client.get("/api/config").json()
    assert "apps_domain" in cfg and "public_ip" in cfg


def test_app_crud(client):
    r = client.post("/api/apps", json={"name": "lens-inventory",
                    "repo_url": "https://github.com/example/app",
                    "branch": "main"})
    assert r.status_code == 201, r.text
    app_id = r.json()["id"]

    assert client.get("/api/apps").json()[0]["name"] == "lens-inventory"
    assert client.get(f"/api/apps/{app_id}").json()["latest_status"] is None

    # duplicate name rejected
    assert client.post("/api/apps", json={"name": "lens-inventory",
                       "repo_url": "https://github.com/o/r"}).status_code == 409


def test_env_and_secrets(client):
    app_id = client.post("/api/apps", json={"name": "a", "repo_url": "https://github.com/o/r"}).json()["id"]

    client.put(f"/api/apps/{app_id}/env",
               json=[{"key": "CORS_ORIGINS", "value": "https://a"}])
    assert client.get(f"/api/apps/{app_id}/env").json() == \
        [{"key": "CORS_ORIGINS", "value": "https://a"}]

    client.put(f"/api/apps/{app_id}/secrets", json={"key": "SECRET_KEY", "value": "top"})
    # secret keys are listed; values never returned
    assert client.get(f"/api/apps/{app_id}/secrets").json() == ["SECRET_KEY"]


def test_secret_encrypted_at_rest(client, env):
    app_id = client.post("/api/apps", json={"name": "a", "repo_url": "https://github.com/o/r"}).json()["id"]
    client.put(f"/api/apps/{app_id}/secrets", json={"key": "SECRET_KEY", "value": "top"})
    from koyracloud.models import Secret
    with env["db"].session() as s:
        row = s.query(Secret).first()
        assert row.value_encrypted != "top"
        assert env["crypto"].decrypt(row.value_encrypted) == "top"


def test_deploy_flow_renders_and_calls_docker(client, env):
    app_id = client.post("/api/apps", json={"name": "lens-inventory",
                         "repo_url": "https://github.com/example/app"}
                         ).json()["id"]
    client.put(f"/api/apps/{app_id}/secrets", json={"key": "SECRET_KEY", "value": "sk"})
    client.put(f"/api/apps/{app_id}/env", json=[{"key": "NEXT_PUBLIC_FOO", "value": "bar"}])

    r = client.post(f"/api/apps/{app_id}/deploys", json={})
    assert r.status_code == 201
    deploy_id = r.json()["id"]

    # synchronous deploy already ran (run_async=False)
    d = client.get(f"/api/deploys/{deploy_id}").json()
    assert d["status"] == "live", client.get(f"/api/deploys/{deploy_id}/log").json()
    assert d["commit"].startswith("deadbeef")

    # image is built + pushed BEFORE the service deploy
    assert env["docker"].events == ["build", "push", "push", "deploy"]
    tag, context_dir, build_args, dockerfile = env["docker"].builds[0]
    # image is tagged for the internal registry, by commit
    assert tag.startswith("reg:5000/koyra-app-lens-inventory:")
    # built from a LOCAL dir (off NFS), not the app's /workspace volume
    assert "/build/lens-inventory-" in context_dir and "/workspace" not in context_dir
    # build-time-inlined vars (NEXT_PUBLIC_*/VITE_*) go in as build-args...
    assert build_args["NEXT_PUBLIC_FOO"] == "bar"
    # ...but secrets are NOT baked into the image
    assert "SECRET_KEY" not in build_args
    # both commit + latest tags are pushed
    assert any(p.endswith(":latest") for p in env["docker"].pushed)

    # the deployed service runs the registry image, and gets the secret at RUNTIME
    assert len(env["docker"].deployed) == 1
    stack_name, stack = env["docker"].deployed[0]
    assert stack_name == "koyra-lens-inventory"
    svc = stack["services"]["lens-inventory"]
    assert svc["image"] == tag
    assert svc["environment"]["SECRET_KEY"] == "sk"

    # deploy log captured
    log = client.get(f"/api/deploys/{deploy_id}/log").json()
    assert "deploying service to swarm" in log["log"]


def test_rollback_redeploys_target_commit(client, env):
    app_id = client.post("/api/apps", json={"name": "lens-inventory",
                         "repo_url": "https://github.com/example/app"}
                         ).json()["id"]
    first_id = client.post(f"/api/apps/{app_id}/deploys", json={}).json()["id"]
    # commit is populated during the (synchronous) deploy — re-fetch to read it
    first = client.get(f"/api/deploys/{first_id}").json()
    assert first["commit"]

    r = client.post(f"/api/apps/{app_id}/rollback", json={"deploy_id": first_id})
    assert r.status_code == 201
    rolled = r.json()
    assert rolled["ref"] == first["commit"]
    assert len(env["docker"].deployed) == 2


def test_create_app_rejects_flag_injection_repo(client):
    r = client.post("/api/apps", json={"name": "evil", "repo_url": "--upload-pack=x"})
    assert r.status_code == 422


def test_create_app_rejects_bad_branch(client):
    r = client.post("/api/apps", json={"name": "evil", "repo_url":
                    "https://github.com/o/r", "branch": "--evil"})
    assert r.status_code == 422


def test_create_seeds_primary_domain(client):
    aid = client.post("/api/apps", json={"name": "demo-app",
                      "repo_url": "https://github.com/o/r"}).json()["id"]
    domains = client.get(f"/api/apps/{aid}/domains").json()
    assert len(domains) == 1
    # <name>-<random token>.<apps_domain>
    assert re.fullmatch(r"demo-app-[0-9a-f]{6}\.apps\.example\.com", domains[0]["host"])
    assert domains[0]["is_primary"] is True


def test_domain_add_setprimary_delete(client):
    aid = client.post("/api/apps", json={"name": "shop",
                      "repo_url": "https://github.com/o/r"}).json()["id"]
    # the seeded auto-subdomain carries a random token, so capture it
    auto_host = client.get(f"/api/apps/{aid}/domains").json()[0]["host"]
    # add a custom domain
    d = client.post(f"/api/apps/{aid}/domains", json={"host": "shop.example.com"})
    assert d.status_code == 201
    did = d.json()["id"]
    assert {x["host"] for x in client.get(f"/api/apps/{aid}/domains").json()} == \
        {auto_host, "shop.example.com"}
    # invalid host rejected
    assert client.post(f"/api/apps/{aid}/domains", json={"host": "not a domain"}).status_code == 422
    # duplicate host rejected
    assert client.post(f"/api/apps/{aid}/domains", json={"host": "shop.example.com"}).status_code == 409
    # set the custom one primary
    client.post(f"/api/apps/{aid}/domains/{did}/primary")
    prim = [x for x in client.get(f"/api/apps/{aid}/domains").json() if x["is_primary"]]
    assert len(prim) == 1 and prim[0]["host"] == "shop.example.com"
    # app's primary_host reflects it
    assert client.get(f"/api/apps/{aid}").json()["primary_host"] == "shop.example.com"
    # delete it → primary falls back to the remaining domain
    assert client.delete(f"/api/apps/{aid}/domains/{did}").status_code == 204
    rest = client.get(f"/api/apps/{aid}/domains").json()
    assert len(rest) == 1 and rest[0]["is_primary"] is True


def test_deploy_uses_configured_domains(client, env):
    aid = client.post("/api/apps", json={"name": "shop",
                      "repo_url": "https://github.com/o/r"}).json()["id"]
    auto_host = client.get(f"/api/apps/{aid}/domains").json()[0]["host"]
    client.post(f"/api/apps/{aid}/domains", json={"host": "shop.example.com"})
    client.post(f"/api/apps/{aid}/deploys", json={})
    rule = _rule_of(env, "shop")  # union of all router rules (apps + saas split)
    assert auto_host in rule and "shop.example.com" in rule


def test_redeploy_same_commit_skips_build(client, env):
    # A redeploy at the same commit (e.g. re-rendering routing after a domain
    # change) reuses the registry image instead of rebuilding on the control
    # plane — it's a pure swarm service deploy.
    aid = client.post("/api/apps", json={"name": "shop",
                      "repo_url": "https://github.com/o/r"}).json()["id"]
    client.post(f"/api/apps/{aid}/deploys", json={})
    assert len(env["docker"].builds) == 1          # first deploy builds + pushes
    client.post(f"/api/apps/{aid}/deploys", json={})
    assert len(env["docker"].builds) == 1          # same commit → no rebuild
    assert len(env["docker"].deployed) == 2        # but it re-deploys the service


def _rule_of(env, service):
    # The host may be split across the apps router and the SaaS router, so join
    # every router rule label to assert a host is routed somewhere.
    _, stack = env["docker"].deployed[-1]
    return " ".join(lbl for lbl in stack["services"][service]["deploy"]["labels"]
                    if ".rule=" in lbl)


def test_add_domain_redeploys_live_app(client, env):
    # A live app must re-render its Traefik route when a domain is attached,
    # otherwise the new host 404s until someone manually redeploys.
    aid = client.post("/api/apps", json={"name": "shop",
                      "repo_url": "https://github.com/o/r"}).json()["id"]
    client.post(f"/api/apps/{aid}/deploys", json={})          # make it live
    n = len(env["docker"].deployed)
    client.post(f"/api/apps/{aid}/domains", json={"host": "shop.example.com"})
    assert len(env["docker"].deployed) == n + 1              # auto-redeployed
    assert "shop.example.com" in _rule_of(env, "shop")


def test_delete_domain_redeploys_live_app(client, env):
    aid = client.post("/api/apps", json={"name": "shop",
                      "repo_url": "https://github.com/o/r"}).json()["id"]
    auto_host = client.get(f"/api/apps/{aid}/domains").json()[0]["host"]
    did = client.post(f"/api/apps/{aid}/domains",
                      json={"host": "shop.example.com"}).json()["id"]
    client.post(f"/api/apps/{aid}/deploys", json={})          # live with both hosts
    n = len(env["docker"].deployed)
    assert client.delete(f"/api/apps/{aid}/domains/{did}").status_code == 204
    assert len(env["docker"].deployed) == n + 1              # auto-redeployed
    rule = _rule_of(env, "shop")
    assert "shop.example.com" not in rule and auto_host in rule


def test_domain_change_skips_redeploy_when_not_live(client, env):
    # No running service yet → nothing to update; the first real deploy will
    # pick the domain up. Don't surprise-deploy a never-deployed app.
    aid = client.post("/api/apps", json={"name": "shop",
                      "repo_url": "https://github.com/o/r"}).json()["id"]
    client.post(f"/api/apps/{aid}/domains", json={"host": "shop.example.com"})
    assert env["docker"].deployed == []


def test_uptime_monitor_debounce_and_transitions(client, env):
    from koyracloud import monitor
    db = env["db"]
    # an app must be live to be probed
    aid = client.post("/api/apps", json={"name": "mon",
                      "repo_url": "https://github.com/o/r"}).json()["id"]
    client.post(f"/api/apps/{aid}/deploys", json={})  # -> live (fake docker)

    up = lambda url: True       # noqa: E731
    down = lambda url: False    # noqa: E731

    assert monitor.check_once(db, up) == []                   # initial healthy → no alert
    assert monitor.check_once(db, up) == []                   # still up, no transition
    assert monitor.check_once(db, down) == []                 # 1 fail < threshold → no flip
    assert monitor.check_once(db, down) == [(aid, "down")]    # 2nd fail → down (debounce)
    assert monitor.check_once(db, up) == [(aid, "up")]        # recovers (False→True)

    summ = client.get(f"/api/apps/{aid}/uptime").json()
    assert summ["up"] is True and summ["samples_24h"] >= 5


def test_uptime_skips_never_deployed(client, env):
    from koyracloud import monitor
    client.post("/api/apps", json={"name": "ndep", "repo_url": "https://github.com/o/r"})
    assert monitor.check_once(env["db"], lambda url: False) == []  # not live → not probed


def test_apps_status_bulk(client, env):
    aid = client.post("/api/apps", json={"name": "lens-inventory",
                      "repo_url": "https://github.com/example/app"}).json()["id"]
    # before deploy: not running
    before = client.get("/api/apps/status").json()
    assert before[str(aid)]["exists"] is False
    # after a deploy: running 1/1
    client.post(f"/api/apps/{aid}/deploys", json={})
    after = client.get("/api/apps/status").json()
    assert after[str(aid)] == {"exists": True, "running": 1, "desired": 1}


def test_runtime_status_and_logs(client):
    aid = client.post("/api/apps", json={"name": "rt",
                      "repo_url": "https://github.com/o/r"}).json()["id"]
    st = client.get(f"/api/apps/{aid}/status").json()
    assert st["running"] == 1 and st["desired"] == 1 and st["tasks"][0]["node"] == "node1"
    logs = client.get(f"/api/apps/{aid}/runtime-logs?tail=50").json()
    assert "log line for koyra-rt_rt" in logs["logs"]


def test_test_email_inert_without_key(client):
    # dev login is admin; no resend key in tests → reports not configured
    r = client.post("/api/test-email", json={"to": "me@x.com"})
    assert r.status_code == 200 and r.json()["sent"] is False
    assert client.post("/api/test-email", json={"to": ""}).status_code == 400


def test_notify_get_set(client):
    aid = client.post("/api/apps", json={"name": "n", "repo_url": "https://github.com/o/r"}).json()["id"]
    g = client.get(f"/api/apps/{aid}/notify").json()
    assert g["owner_login"] == "tester" and g["notify_email"] == ""
    assert client.put(f"/api/apps/{aid}/notify", json={"notify_email": "me@x.com"}).status_code == 204
    assert client.get(f"/api/apps/{aid}/notify").json()["notify_email"] == "me@x.com"


def test_patch_app(client):
    aid = client.post("/api/apps", json={"name": "p",
                      "repo_url": "https://github.com/o/r"}).json()["id"]
    r = client.patch(f"/api/apps/{aid}", json={"branch": "dev", "auto_deploy": True})
    assert r.status_code == 200
    body = r.json()
    assert body["branch"] == "dev" and body["auto_deploy"] is True


def test_analytics_beacon_served(client):
    r = client.get("/_k/a.js")
    assert r.status_code == 200 and "data-site" in r.text
    assert "javascript" in r.headers["content-type"]


def _site_token(client, aid):
    snip = client.get(f"/api/apps/{aid}/analytics").json()["snippet"]
    return snip.split('data-site="', 1)[1].split('"', 1)[0]


def test_analytics_collect_and_dashboard(client):
    aid = client.post("/api/apps", json={"name": "site",
                      "repo_url": "https://github.com/o/r"}).json()["id"]
    token = _site_token(client, aid)
    for path in ["/", "/", "/about"]:
        client.post("/_k/e", content=json.dumps({"site": token, "path": path, "ref": "https://google.com/x"}))
    data = client.get(f"/api/apps/{aid}/analytics").json()
    assert data["views"] == 3
    assert data["top_paths"][0]["path"] == "/" and data["top_paths"][0]["views"] == 2
    assert any(r["source"] == "google.com" for r in data["top_referrers"])


def test_analytics_optout_ignores_hits(client):
    aid = client.post("/api/apps", json={"name": "site",
                      "repo_url": "https://github.com/o/r"}).json()["id"]
    token = _site_token(client, aid)
    client.put(f"/api/apps/{aid}/analytics", json={"enabled": False})
    client.post("/_k/e", content=json.dumps({"site": token, "path": "/"}))
    assert client.get(f"/api/apps/{aid}/analytics").json()["views"] == 0


def test_analytics_collect_unknown_token_noop(client):
    r = client.post("/_k/e", content=json.dumps({"site": "nope", "path": "/"}))
    assert r.status_code == 204


def test_me_reports_admin(client):
    # dev_login is treated as admin
    assert client.get("/api/me").json() == {"login": "tester", "is_admin": True}


def test_invite_member_flow(client):
    # add an invited member
    r = client.post("/api/allowed-users", json={"login": "Octocat"})
    assert r.status_code == 201
    listing = client.get("/api/allowed-users").json()
    assert "octocat" in [m["login"] for m in listing["members"]]
    # idempotent-ish: duplicate rejected
    assert client.post("/api/allowed-users", json={"login": "octocat"}).status_code == 409
    # invalid login rejected
    assert client.post("/api/allowed-users", json={"login": "bad login!"}).status_code == 422
    # remove
    assert client.delete("/api/allowed-users/octocat").status_code == 204
    assert "octocat" not in [m["login"] for m in client.get("/api/allowed-users").json()["members"]]


def test_webhook_push_triggers_autodeploy(client, env):
    import hashlib
    import hmac
    aid = client.post("/api/apps", json={"name": "hooky",
                      "repo_url": "https://github.com/acme/hooky", "branch": "main",
                      "auto_deploy": True}).json()["id"]
    body = json.dumps({"ref": "refs/heads/main",
                       "repository": {"full_name": "acme/hooky"}}).encode()
    sig = "sha256=" + hmac.new(env["settings"].webhook_secret.encode(), body,
                               hashlib.sha256).hexdigest()
    r = client.post("/api/webhooks/github", content=body,
                    headers={"X-Hub-Signature-256": sig, "X-GitHub-Event": "push",
                             "content-type": "application/json"})
    assert r.status_code == 200 and r.json()["triggered"] == ["hooky"]
    # a deploy was created + ran (fake docker)
    assert client.get(f"/api/apps/{aid}/deploys").json()[0]["status"] == "live"


def test_webhook_bad_signature_rejected(client):
    r = client.post("/api/webhooks/github", content=b"{}",
                    headers={"X-Hub-Signature-256": "sha256=nope", "X-GitHub-Event": "push"})
    assert r.status_code == 401


def _hdr(login, secret="sek"):
    from koyracloud import auth
    return {"Cookie": f"koyra_session={auth.make_session(login, secret)}"}


def test_ownership_isolation(env):
    """A member cannot see or touch another member's app (CRITICAL-1)."""
    from dataclasses import replace

    from fastapi.testclient import TestClient
    from koyracloud.app import create_app
    from koyracloud.models import AllowedUser
    s = replace(env["settings"], dev_login="", session_secret="sek", allowed_logins=[])
    with env["db"].session() as sess:
        sess.add(AllowedUser(login="alice"))
        sess.add(AllowedUser(login="bob"))
        sess.commit()
    app = create_app(settings=s, db=env["db"], docker=env["docker"],
                     deployer=env["deployer"], run_async=False)
    c = TestClient(app)
    aid = c.post("/api/apps", json={"name": "alice-app", "repo_url": "https://github.com/o/r"},
                 headers=_hdr("alice")).json()["id"]
    # bob is blind to it
    assert c.get("/api/apps", headers=_hdr("bob")).json() == []
    for path, method in [(f"/api/apps/{aid}", "get"), (f"/api/apps/{aid}", "delete"),
                         (f"/api/apps/{aid}/secrets", "get"),
                         (f"/api/apps/{aid}/env", "get"),
                         (f"/api/apps/{aid}/deploys", "get")]:
        r = getattr(c, method)(path, headers=_hdr("bob"))
        assert r.status_code == 404, f"{method} {path} -> {r.status_code}"
    # bob can't trigger a deploy on alice's app either
    assert c.post(f"/api/apps/{aid}/deploys", json={}, headers=_hdr("bob")).status_code == 404
    # alice still can
    assert c.get(f"/api/apps/{aid}", headers=_hdr("alice")).status_code == 200


def test_create_app_rejects_bad_name(client):
    for bad in ["Bad_Name", "UPPER", "-lead", "has.dot", "a/b", "x" * 41]:
        r = client.post("/api/apps", json={"name": bad, "repo_url": "https://github.com/o/r"})
        assert r.status_code == 422, f"{bad} accepted"


def test_add_domain_rejects_reserved(client):
    aid = client.post("/api/apps", json={"name": "site",
                      "repo_url": "https://github.com/o/r"}).json()["id"]
    # apps-domain apex and a *.apps subdomain that isn't this app's own are reserved
    for host in ["apps.example.com", "foreign.apps.example.com"]:
        r = client.post(f"/api/apps/{aid}/domains", json={"host": host})
        assert r.status_code == 400, f"{host} -> {r.status_code}"
    # a normal custom domain is fine
    assert client.post(f"/api/apps/{aid}/domains", json={"host": "site.example.com"}).status_code == 201


def test_set_notify_validates_email(client):
    aid = client.post("/api/apps", json={"name": "n", "repo_url": "https://github.com/o/r"}).json()["id"]
    assert client.put(f"/api/apps/{aid}/notify", json={"notify_email": "nope"}).status_code == 422
    assert client.put(f"/api/apps/{aid}/notify", json={"notify_email": "a@b.com"}).status_code == 204
    assert client.put(f"/api/apps/{aid}/notify", json={"notify_email": ""}).status_code == 204


def test_oauth_callback_rejects_missing_state(client):
    # No state cookie set → CSRF check must reject before any token exchange
    r = client.get("/api/auth/callback?code=abc&state=xyz", follow_redirects=False)
    assert r.status_code == 400


def test_auth_required_without_dev_login(env):
    # rebuild app with no dev_login and empty allowlist → 401 on protected routes
    from dataclasses import replace

    from fastapi.testclient import TestClient
    from koyracloud.app import create_app
    s = replace(env["settings"], dev_login="")
    app = create_app(settings=s, db=env["db"], docker=env["docker"],
                     deployer=env["deployer"], run_async=False)
    c = TestClient(app)
    assert c.get("/api/health").status_code == 200      # public
    assert c.get("/api/apps").status_code == 401        # protected


# --- Cloudflare for SaaS custom hostnames -----------------------------------
class _FakeCF:
    """Stand-in for koyracloud.cloudflare.Cloudflare (configured), recording
    calls and returning canned custom-hostname state."""
    configured = True

    def __init__(self):
        self.created = []
        self.deleted = []

    def dcv_uuid(self):
        return "bc21f3"

    def create_custom_hostname(self, host):
        self.created.append(host)
        return {"id": f"ch_{host}", "status": "pending",
                "ssl_status": "pending_validation", "ownership": {}}

    def get_custom_hostname(self, hostname_id):
        return {"id": hostname_id, "status": "active",
                "ssl_status": "active", "ownership": {}}

    def delete_custom_hostname(self, hostname_id):
        self.deleted.append(hostname_id)
        return True

    def records_for(self, host):
        from koyracloud import cloudflare
        return cloudflare.customer_records(host, "origin.example.com", self.dcv_uuid())


def _cf_client(env, cf):
    from fastapi.testclient import TestClient

    from koyracloud.app import create_app
    app = create_app(settings=env["settings"], db=env["db"], docker=env["docker"],
                     deployer=env["deployer"], cloudflare=cf, run_async=False)
    return TestClient(app)


def test_add_domain_no_op_when_cf_disabled(client):
    # Default client has no Cloudflare token → custom-hostname fields stay inert.
    aid = client.post("/api/apps", json={"name": "shop",
                      "repo_url": "https://github.com/o/r"}).json()["id"]
    body = client.post(f"/api/apps/{aid}/domains", json={"host": "shop.example.com"}).json()
    assert body["records"] == [] and body["ssl_status"] is None and body["verified"] is False
    # verify is a graceful 200 no-op for a CF-unmanaged domain
    r = client.post(f"/api/apps/{aid}/domains/{body['id']}/verify")
    assert r.status_code == 200 and r.json()["records"] == []


def test_add_domain_creates_cf_hostname_and_returns_records(env):
    cf = _FakeCF()
    c = _cf_client(env, cf)
    aid = c.post("/api/apps", json={"name": "shop",
                 "repo_url": "https://github.com/o/r"}).json()["id"]
    # creating the app must NOT register the in-zone auto-subdomain with CF
    assert cf.created == []
    body = c.post(f"/api/apps/{aid}/domains", json={"host": "shop.example.com"}).json()
    assert cf.created == ["shop.example.com"]
    recs = {r["name"]: r["value"] for r in body["records"]}
    assert recs["shop.example.com"] == "origin.example.com"
    assert recs["_acme-challenge.shop.example.com"] == "shop.example.com.bc21f3.dcv.cloudflare.com"
    assert body["ssl_status"] == "pending_validation" and body["verified"] is False


def test_apps_subdomain_skips_cf(env):
    cf = _FakeCF()
    c = _cf_client(env, cf)
    aid = c.post("/api/apps", json={"name": "shop",
                 "repo_url": "https://github.com/o/r"}).json()["id"]
    doms = c.get(f"/api/apps/{aid}/domains").json()
    auto = next(d for d in doms if d["host"].endswith(".apps.example.com"))
    assert cf.created == [] and auto["records"] == [] and auto["ssl_status"] is None


def test_delete_domain_removes_cf_hostname(env):
    cf = _FakeCF()
    c = _cf_client(env, cf)
    aid = c.post("/api/apps", json={"name": "shop",
                 "repo_url": "https://github.com/o/r"}).json()["id"]
    did = c.post(f"/api/apps/{aid}/domains", json={"host": "shop.example.com"}).json()["id"]
    assert c.delete(f"/api/apps/{aid}/domains/{did}").status_code == 204
    assert cf.deleted == ["ch_shop.example.com"]


def test_verify_domain_reflects_live_status(env):
    cf = _FakeCF()
    c = _cf_client(env, cf)
    aid = c.post("/api/apps", json={"name": "shop",
                 "repo_url": "https://github.com/o/r"}).json()["id"]
    did = c.post(f"/api/apps/{aid}/domains", json={"host": "shop.example.com"}).json()["id"]
    body = c.post(f"/api/apps/{aid}/domains/{did}/verify").json()
    assert body["ssl_status"] == "active" and body["verified"] is True


def test_verify_adopts_cert_for_preexisting_domain(env):
    # A custom Domain with no DomainCert (added before the feature / while CF
    # was off) gets registered + status-polled when verify runs.
    cf = _FakeCF()
    c = _cf_client(env, cf)
    aid = c.post("/api/apps", json={"name": "shop",
                 "repo_url": "https://github.com/o/r"}).json()["id"]
    from koyracloud.models import Domain
    with env["db"].session() as s:
        d = Domain(app_id=aid, host="legacy.example.com", is_primary=False)
        s.add(d)
        s.commit()
        did = d.id
    body = c.post(f"/api/apps/{aid}/domains/{did}/verify").json()
    assert cf.created == ["legacy.example.com"]              # adopted/created on verify
    assert any(r["name"] == "legacy.example.com" for r in body["records"])
    assert body["ssl_status"] == "active" and body["verified"] is True


def test_cf_managed_domain_suppresses_ip_dns_check(env):
    # A SaaS host CNAMEs to Cloudflare anycast, not the WAN IP — dns_ok (the
    # IP check) must be suppressed so the badge reflects the edge cert instead.
    from dataclasses import replace

    from fastapi.testclient import TestClient

    from koyracloud.app import create_app
    cf = _FakeCF()
    s = replace(env["settings"], public_ip="203.0.113.10")
    app = create_app(settings=s, db=env["db"], docker=env["docker"],
                     deployer=env["deployer"], cloudflare=cf, run_async=False)
    c = TestClient(app)
    aid = c.post("/api/apps", json={"name": "shop",
                 "repo_url": "https://github.com/o/r"}).json()["id"]
    body = c.post(f"/api/apps/{aid}/domains", json={"host": "shop.example.com"}).json()
    assert body["dns_ok"] is None
    assert body["verified"] is False and body["ssl_status"] == "pending_validation"


def test_pending_ownership_surfaces_txt_record(env):
    # When Cloudflare can't auto-validate ownership over HTTP, the extra TXT
    # record it returns must be surfaced so the customer can complete validation.
    class _PendingCF(_FakeCF):
        def create_custom_hostname(self, host):
            self.created.append(host)
            return {"id": f"ch_{host}", "status": "pending",
                    "ssl_status": "pending_validation",
                    "ownership": {"type": "txt",
                                  "name": f"_cf-custom-hostname.{host}", "value": "tok123"}}

    cf = _PendingCF()
    c = _cf_client(env, cf)
    aid = c.post("/api/apps", json={"name": "shop",
                 "repo_url": "https://github.com/o/r"}).json()["id"]
    body = c.post(f"/api/apps/{aid}/domains", json={"host": "shop.example.com"}).json()
    txts = [r for r in body["records"] if r["type"] == "TXT"]
    assert len(txts) == 1
    assert txts[0]["name"] == "_cf-custom-hostname.shop.example.com"
    assert txts[0]["value"] == "tok123"
    assert body["verified"] is False


def test_active_ownership_hides_txt_record(env):
    # Default _FakeCF auto-validates (get → active): no extra TXT once verified.
    cf = _FakeCF()
    c = _cf_client(env, cf)
    aid = c.post("/api/apps", json={"name": "shop",
                 "repo_url": "https://github.com/o/r"}).json()["id"]
    did = c.post(f"/api/apps/{aid}/domains", json={"host": "shop.example.com"}).json()["id"]
    body = c.post(f"/api/apps/{aid}/domains/{did}/verify").json()
    assert body["verified"] is True
    assert not any(r["type"] == "TXT" for r in body["records"])


def test_deploy_uses_repo_dockerfile(env):
    # An app whose manifest opts into runtime: dockerfile builds the repo's OWN
    # Dockerfile, not a generated one.
    from fastapi.testclient import TestClient

    from koyracloud.app import create_app
    from koyracloud.deployer import Deployer
    from tests.conftest import FakeDocker

    def cloner(repo_url, ref, token, dest):
        dest.mkdir(parents=True, exist_ok=True)
        (dest / ".paas").mkdir(parents=True, exist_ok=True)
        (dest / ".paas" / "app.yaml").write_text(
            "name: dock\nruntime: dockerfile\nport: 8000\nhealthcheck: /health\n")
        (dest / "Dockerfile").write_text("FROM python:3.12-slim\nCMD echo hi\n")
        return "deadbeefcafef00dba5eba11c0ffee0011223344"

    docker = FakeDocker()
    deployer = Deployer(settings=env["settings"], docker=docker, crypto=env["crypto"],
                        cloner=cloner)
    app = create_app(settings=env["settings"], db=env["db"], docker=docker,
                     deployer=deployer, run_async=False)
    c = TestClient(app)
    aid = c.post("/api/apps", json={"name": "dock",
                 "repo_url": "https://github.com/o/r"}).json()["id"]
    assert c.post(f"/api/apps/{aid}/deploys", json={}).status_code == 201
    tag, context_dir, build_args, dockerfile = docker.builds[0]
    # built the repo's own Dockerfile (not the generated .koyra.Dockerfile)
    assert dockerfile.endswith("/Dockerfile") and not dockerfile.endswith(".koyra.Dockerfile")
