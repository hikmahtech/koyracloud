"""Service tokens (#135, phase 1): ``Authorization: Bearer <token>`` resolves
to ``token:<name>``, and a token made by an admin acts as an admin.

Uses the ``scoped`` fixture (real cookie auth, ``operator`` the sole admin) so
the token is the only thing that gets a request in."""
import logging

from fastapi.testclient import TestClient

from koyracloud.models import ApiToken


def _mktoken(scoped, name="provisioner"):
    r = scoped["as_user"]("operator").post("/api/tokens", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()


def _bearer(scoped, token):
    c = TestClient(scoped["app"])
    c.headers["Authorization"] = f"Bearer {token}"
    return c


def test_token_is_accepted_and_acts_as_admin(scoped):
    made = _mktoken(scoped)
    assert made["token"].startswith("koyra_")
    bot = _bearer(scoped, made["token"])

    assert bot.get("/api/me").json() == {"login": "token:provisioner", "is_admin": True}

    # Sees a member's app, like any admin.
    scoped["invite"]("alice")
    r = scoped["as_user"]("alice").post("/api/apps", json={
        "name": "alice-app", "repo_url": "https://github.com/example/app"})
    assert r.status_code == 201
    assert [a["name"] for a in bot.get("/api/apps").json()] == ["alice-app"]

    # Creates its own app, owned by the token identity.
    r = bot.post("/api/apps", json={"name": "aep-acme",
                                    "repo_url": "https://github.com/example/app"})
    assert r.status_code == 201
    assert r.json()["owner_login"] == "token:provisioner"

    rows = scoped["as_user"]("operator").get("/api/tokens").json()
    assert rows[0]["name"] == "provisioner" and rows[0]["last_used_at"]
    assert "token" not in rows[0]


def test_revoked_token_is_refused(scoped):
    made = _mktoken(scoped)
    bot = _bearer(scoped, made["token"])
    assert bot.get("/api/apps").status_code == 200

    r = scoped["as_user"]("operator").delete(f"/api/tokens/{made['id']}")
    assert r.status_code == 204
    assert bot.get("/api/apps").status_code == 401
    assert scoped["as_user"]("operator").get("/api/tokens").json()[0]["revoked_at"]
    # The name stays taken: it is the identity that owns the token's apps.
    r = scoped["as_user"]("operator").post("/api/tokens", json={"name": "provisioner"})
    assert r.status_code == 409


def test_bad_token_is_refused(scoped):
    _mktoken(scoped)
    for header in ("Bearer koyra_not-a-real-token", "Bearer "):
        c = TestClient(scoped["app"])
        c.headers["Authorization"] = header
        assert c.get("/api/apps").status_code == 401, header


def test_bad_token_never_falls_back_to_dev_login(client):
    # The dev-login bypass must not turn a wrong token into an admin session.
    client.headers["Authorization"] = "Bearer koyra_wrong"
    assert client.get("/api/apps").status_code == 401


def test_token_stops_working_when_its_creator_stops_being_admin(scoped):
    made = _mktoken(scoped)
    with scoped["db"].session() as s:
        s.query(ApiToken).update({"created_by": "former-admin"})
        s.commit()
    assert _bearer(scoped, made["token"]).get("/api/apps").status_code == 403


def test_only_signed_in_admins_manage_tokens(scoped):
    scoped["invite"]("alice")
    alice = scoped["as_user"]("alice")
    assert alice.get("/api/tokens").status_code == 403
    assert alice.post("/api/tokens", json={"name": "x"}).status_code == 403

    # A token acts as an admin but cannot mint or revoke tokens.
    made = _mktoken(scoped)
    bot = _bearer(scoped, made["token"])
    assert bot.post("/api/tokens", json={"name": "child"}).status_code == 403
    assert bot.delete(f"/api/tokens/{made['id']}").status_code == 403
    assert bot.get("/api/tokens").status_code == 403


def test_token_name_must_be_a_slug(scoped):
    op = scoped["as_user"]("operator")
    assert op.post("/api/tokens", json={"name": "has space"}).status_code == 422
    assert op.post("/api/tokens", json={"name": ""}).status_code == 422


def test_token_never_logged_or_stored(scoped, caplog):
    caplog.set_level(logging.DEBUG)
    made = _mktoken(scoped)
    token = made["token"]
    bot = _bearer(scoped, token)
    bot.get("/api/apps")
    bot.post("/api/apps", json={"name": "logged-app",
                                "repo_url": "https://github.com/example/app"})
    scoped["as_user"]("operator").delete(f"/api/tokens/{made['id']}")
    bot.get("/api/apps")   # now revoked: the 401 must not echo it either
    r = _bearer(scoped, token + "x").get("/api/apps")
    assert token not in r.text

    assert caplog.records, "expected the create/revoke audit lines"
    assert all(token not in rec.getMessage() for rec in caplog.records)
    assert "provisioner" in caplog.text   # the name is what gets logged

    with scoped["db"].session() as s:
        row = s.query(ApiToken).one()
        assert token not in (row.token_sha256, row.name)
        assert len(row.token_sha256) == 64
