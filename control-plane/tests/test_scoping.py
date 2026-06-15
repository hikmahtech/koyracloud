"""Per-user project scoping.

koyracloud is single-operator by design: logins in KOYRA_ALLOWED_LOGINS are
admins and see every app, while invited members (the AllowedUser table) are
scoped to only the apps they own. These tests pin that contract so a member
can never see, read, or mutate another user's app.

The shared ``client`` fixture sets KOYRA_DEV_LOGIN, which forces admin and
bypasses this entirely — so these tests use the ``scoped`` fixture, which runs
real cookie-session auth with ``operator`` as the sole admin.
"""


def _mkapp(client, name):
    r = client.post("/api/apps", json={"name": name,
                    "repo_url": "https://github.com/example/app", "branch": "main"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_member_login_is_not_admin(scoped):
    scoped["invite"]("alice")
    me = scoped["as_user"]("alice").get("/api/me").json()
    assert me == {"login": "alice", "is_admin": False}


def test_unlisted_login_is_rejected(scoped):
    # Neither an admin nor an invited member: authenticated cookie, but no access.
    r = scoped["as_user"]("stranger").get("/api/apps")
    assert r.status_code == 403


def test_member_list_shows_only_own_apps(scoped):
    scoped["invite"]("alice")
    scoped["invite"]("bob")
    alice, bob = scoped["as_user"]("alice"), scoped["as_user"]("bob")

    _mkapp(alice, "alice-app")
    _mkapp(bob, "bob-app")

    assert [a["name"] for a in alice.get("/api/apps").json()] == ["alice-app"]
    assert [a["name"] for a in bob.get("/api/apps").json()] == ["bob-app"]

    # The admin sees every app regardless of owner.
    operator = scoped["as_user"]("operator")
    assert {a["name"] for a in operator.get("/api/apps").json()} == {"alice-app", "bob-app"}


def test_member_status_endpoint_is_scoped(scoped):
    scoped["invite"]("alice")
    scoped["invite"]("bob")
    alice, bob = scoped["as_user"]("alice"), scoped["as_user"]("bob")
    alice_id = _mkapp(alice, "alice-app")
    bob_id = _mkapp(bob, "bob-app")

    # /api/apps/status is a dict keyed by app id; a member only sees their own.
    assert set(alice.get("/api/apps/status").json()) == {str(alice_id)}
    assert set(bob.get("/api/apps/status").json()) == {str(bob_id)}
    assert set(scoped["as_user"]("operator").get("/api/apps/status").json()) == \
        {str(alice_id), str(bob_id)}


def test_member_cannot_touch_another_members_app(scoped):
    scoped["invite"]("alice")
    scoped["invite"]("bob")
    alice, bob = scoped["as_user"]("alice"), scoped["as_user"]("bob")
    app_id = _mkapp(alice, "alice-app")

    # Every owner-scoped sub-resource hides the app from a non-owner with 404
    # (not 403 — so existence isn't leaked).
    for path in (f"/api/apps/{app_id}",
                 f"/api/apps/{app_id}/env",
                 f"/api/apps/{app_id}/secrets",
                 f"/api/apps/{app_id}/domains",
                 f"/api/apps/{app_id}/deploys",
                 f"/api/apps/{app_id}/status"):
        assert bob.get(path).status_code == 404, path

    # ...and cannot mutate it either.
    assert bob.put(f"/api/apps/{app_id}/env",
                   json=[{"key": "X", "value": "1"}]).status_code == 404
    assert bob.delete(f"/api/apps/{app_id}").status_code == 404
    assert bob.post(f"/api/apps/{app_id}/deploys", json={}).status_code == 404

    # The owner still has full access; so does the admin.
    assert alice.get(f"/api/apps/{app_id}").status_code == 200
    assert scoped["as_user"]("operator").get(f"/api/apps/{app_id}").status_code == 200


def test_member_cannot_read_another_members_deploy(scoped):
    scoped["invite"]("alice")
    scoped["invite"]("bob")
    alice, bob = scoped["as_user"]("alice"), scoped["as_user"]("bob")
    app_id = _mkapp(alice, "alice-app")
    deploy_id = alice.post(f"/api/apps/{app_id}/deploys", json={}).json()["id"]

    assert bob.get(f"/api/deploys/{deploy_id}").status_code == 404
    assert bob.get(f"/api/deploys/{deploy_id}/log").status_code == 404
    assert alice.get(f"/api/deploys/{deploy_id}").status_code == 200


def test_team_management_is_admin_only(scoped):
    scoped["invite"]("alice")
    alice = scoped["as_user"]("alice")
    operator = scoped["as_user"]("operator")

    # Members can't view or manage the access list.
    assert alice.get("/api/allowed-users").status_code == 403
    assert alice.post("/api/allowed-users", json={"login": "carol"}).status_code == 403

    # The admin can, and sees alice listed as a member (not an admin).
    listing = operator.get("/api/allowed-users").json()
    assert listing["admins"] == ["operator"]
    assert [m["login"] for m in listing["members"]] == ["alice"]
