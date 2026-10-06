"""Extra zones and chosen in-zone hosts (#138).

KOYRA_EXTRA_ZONES lists zones the operator owns besides apps_domain. A host
under one is in-zone: no Cloudflare for SaaS registration, dns_ok checked
against the zone's proxied wildcard, and only an admin may attach it, as the
app's primary domain. Members keep today's rules."""
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from koyracloud import auth
from koyracloud.app import create_app
from koyracloud.models import AllowedUser
from tests.test_api import _FakeCF, _rule_of

ZONE = "auditeasepro.com"
EDGE = ["104.21.0.1", "172.67.0.1"]


def _client(env, cf=None, **overrides):
    s = replace(env["settings"], extra_zones=[ZONE], **overrides)
    app = create_app(settings=s, db=env["db"], docker=env["docker"],
                     deployer=env["deployer"], cloudflare=cf or _FakeCF(), run_async=False)
    return TestClient(app)


def _mkapp(c, name="tenant"):
    r = c.post("/api/apps", json={"name": name, "repo_url": "https://github.com/o/r"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _fake_dns(monkeypatch, table):
    def gethostbyname_ex(host):
        if host not in table:
            raise OSError("NXDOMAIN")
        return host, [], table[host]
    monkeypatch.setattr("koyracloud.app.socket.gethostbyname_ex", gethostbyname_ex)


@pytest.fixture(autouse=True)
def _no_real_dns(monkeypatch):
    # An extra-zone host's dns_ok resolves names; never touch the network.
    _fake_dns(monkeypatch, {})


def test_admin_adds_extra_zone_host_as_primary_without_cloudflare(env):
    cf = _FakeCF()
    c = _client(env, cf)
    aid = _mkapp(c)
    auto = c.get(f"/api/apps/{aid}/domains").json()[0]["host"]

    r = c.post(f"/api/apps/{aid}/domains", json={"host": "acme.auditeasepro.com"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert cf.created == []                      # no Cloudflare for SaaS hostname
    assert body["is_primary"] is True and body["records"] == [] and body["ssl_status"] is None

    doms = {d["host"]: d["is_primary"] for d in c.get(f"/api/apps/{aid}/domains").json()}
    assert doms == {"acme.auditeasepro.com": True, auto: False}   # auto-subdomain kept
    assert c.get(f"/api/apps/{aid}").json()["primary_host"] == "acme.auditeasepro.com"

    # Verify never registers it either.
    c.post(f"/api/apps/{aid}/domains/{body['id']}/verify")
    assert cf.created == []


def test_extra_zone_host_is_routed_without_a_traefik_cert(env):
    c = _client(env)
    aid = _mkapp(c, "shop")
    c.post(f"/api/apps/{aid}/domains", json={"host": "acme.auditeasepro.com"})
    c.post(f"/api/apps/{aid}/deploys", json={})
    assert "Host(`acme.auditeasepro.com`)" in _rule_of(env, "shop")
    _, stack = env["docker"].deployed[-1]
    labels = stack["services"]["shop"]["deploy"]["labels"]
    # The zone is proxied: the edge serves the cert, so Traefik must not ACME it.
    assert not any("koyra-shop-saas.tls.certresolver" in lbl for lbl in labels)


def test_cloudflare_for_saas_host_still_registered(env):
    cf = _FakeCF()
    c = _client(env, cf)
    aid = _mkapp(c)
    body = c.post(f"/api/apps/{aid}/domains", json={"host": "audit.customer.com"}).json()
    assert cf.created == ["audit.customer.com"]
    assert body["records"] and body["is_primary"] is False
    # The zone apex is not under the zone (the wildcard does not cover it), so
    # an admin attaching it gets a Cloudflare for SaaS hostname as before.
    assert c.post(f"/api/apps/{aid}/domains", json={"host": ZONE}).status_code == 201
    assert cf.created == ["audit.customer.com", ZONE]


def test_reserved_hosts_stay_reserved_for_admins(env):
    c = _client(env)
    aid = _mkapp(c)
    for host in ["apps.example.com", "foreign.apps.example.com"]:
        assert c.post(f"/api/apps/{aid}/domains", json={"host": host}).status_code == 400, host


def test_extra_zone_host_taken_by_another_app_is_409(env):
    c = _client(env)
    a, b = _mkapp(c, "one"), _mkapp(c, "two")
    assert c.post(f"/api/apps/{a}/domains", json={"host": "acme.auditeasepro.com"}).status_code == 201
    assert c.post(f"/api/apps/{b}/domains", json={"host": "acme.auditeasepro.com"}).status_code == 409


def test_member_cannot_attach_extra_zone_host(env):
    # Real cookie auth: operator is the admin, alice an invited member.
    s = replace(env["settings"], extra_zones=[ZONE], dev_login="",
                session_secret="test-session-secret", allowed_logins=["operator"])
    cf = _FakeCF()
    app = create_app(settings=s, db=env["db"], docker=env["docker"],
                     deployer=env["deployer"], cloudflare=cf, run_async=False)
    with env["db"].session() as sess:
        sess.add(AllowedUser(login="alice", added_by="operator"))
        sess.commit()
    alice = TestClient(app)
    alice.cookies.set(auth.SESSION_COOKIE, auth.make_session("alice", s.session_secret))
    aid = _mkapp(alice)
    for host in ["acme.auditeasepro.com", ZONE]:   # the apex too: it is the product site
        r = alice.post(f"/api/apps/{aid}/domains", json={"host": host})
        assert r.status_code == 400 and r.json()["detail"] == "that host is reserved", host
    # A member's own external domain keeps working as before.
    assert alice.post(f"/api/apps/{aid}/domains",
                      json={"host": "audit.customer.com"}).status_code == 201
    assert cf.created == ["audit.customer.com"]


@pytest.mark.parametrize("table,expected", [
    # Proxied like the wildcard: same edge IPs.
    ({"koyra-wildcard-probe.auditeasepro.com": EDGE, "acme.auditeasepro.com": EDGE}, True),
    # Points somewhere else (e.g. an unproxied record to the WAN IP).
    ({"koyra-wildcard-probe.auditeasepro.com": EDGE, "acme.auditeasepro.com": ["203.0.113.10"]},
     False),
    # No record at all and no wildcard to route it.
    ({}, None),
])
def test_dns_ok_checks_the_zone_wildcard(env, monkeypatch, table, expected):
    _fake_dns(monkeypatch, table)
    c = _client(env, public_ip="203.0.113.10")
    aid = _mkapp(c)
    body = c.post(f"/api/apps/{aid}/domains", json={"host": "acme.auditeasepro.com"}).json()
    assert body["dns_ok"] is expected
