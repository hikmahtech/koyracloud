"""End-to-end API tests with injected fake docker + cloner and synchronous deploy."""
import json


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

    r = client.post(f"/api/apps/{app_id}/deploys", json={})
    assert r.status_code == 201
    deploy_id = r.json()["id"]

    # synchronous deploy already ran (run_async=False)
    d = client.get(f"/api/deploys/{deploy_id}").json()
    assert d["status"] == "live", client.get(f"/api/deploys/{deploy_id}/log").json()
    assert d["commit"].startswith("deadbeef")

    # one-off build ran BEFORE the service deploy
    assert env["docker"].events == ["build", "deploy"]
    build_image, build_env, build_vol = env["docker"].builds[0]
    assert build_image == env["settings"].runtime_image
    assert build_env["KOYRA_REF"].startswith("deadbeef")
    assert build_vol.endswith("/lens-inventory:/workspace")

    # fake docker received a rendered stack with the secret injected
    assert len(env["docker"].deployed) == 1
    stack_name, stack = env["docker"].deployed[0]
    assert stack_name == "koyra-lens-inventory"
    assert stack["services"]["lens-inventory"]["environment"]["SECRET_KEY"] == "sk"

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
    assert domains[0]["host"] == "demo-app.apps.koyracloud.com"
    assert domains[0]["is_primary"] is True


def test_domain_add_setprimary_delete(client):
    aid = client.post("/api/apps", json={"name": "shop",
                      "repo_url": "https://github.com/o/r"}).json()["id"]
    # add a custom domain
    d = client.post(f"/api/apps/{aid}/domains", json={"host": "shop.example.com"})
    assert d.status_code == 201
    did = d.json()["id"]
    assert {x["host"] for x in client.get(f"/api/apps/{aid}/domains").json()} == \
        {"shop.apps.koyracloud.com", "shop.example.com"}
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
    client.post(f"/api/apps/{aid}/domains", json={"host": "shop.example.com"})
    client.post(f"/api/apps/{aid}/deploys", json={})
    _, stack = env["docker"].deployed[-1]
    rule = next(l for l in stack["services"]["shop"]["deploy"]["labels"] if ".rule=" in l)
    assert "shop.apps.koyracloud.com" in rule and "shop.example.com" in rule


def _rule_of(env, service):
    _, stack = env["docker"].deployed[-1]
    return next(lbl for lbl in stack["services"][service]["deploy"]["labels"]
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
    did = client.post(f"/api/apps/{aid}/domains",
                      json={"host": "shop.example.com"}).json()["id"]
    client.post(f"/api/apps/{aid}/deploys", json={})          # live with both hosts
    n = len(env["docker"].deployed)
    assert client.delete(f"/api/apps/{aid}/domains/{did}").status_code == 204
    assert len(env["docker"].deployed) == n + 1              # auto-redeployed
    rule = _rule_of(env, "shop")
    assert "shop.example.com" not in rule and "shop.apps.koyracloud.com" in rule


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
