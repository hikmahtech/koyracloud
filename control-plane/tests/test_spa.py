"""SPA serving: the control plane dogfoods the single-container model by serving
the built React app, with client-side routes falling back to index.html."""
import pytest

from koyracloud.app import WEB_DIST


@pytest.mark.skipif(not WEB_DIST.is_dir(), reason="web/dist not built")
def test_root_serves_index_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "<div id=\"root\">" in r.text


@pytest.mark.skipif(not WEB_DIST.is_dir(), reason="web/dist not built")
def test_client_route_falls_back_to_index(client):
    r = client.get("/apps/123")
    assert r.status_code == 200
    assert "<!doctype html>" in r.text.lower()


@pytest.mark.skipif(not WEB_DIST.is_dir(), reason="web/dist not built")
def test_api_not_shadowed_by_spa(client):
    # /api routes still resolve even with the SPA catch-all registered
    assert client.get("/api/health").json() == {"status": "ok"}


@pytest.mark.skipif(
    not (WEB_DIST / "blog" / "self-hosted-paas-docker-swarm" / "index.html").is_file(),
    reason="blog not prerendered",
)
def test_prerendered_route_serves_directory_index(client):
    # A prerendered directory route (/blog/<slug>) serves its <dir>/index.html
    # — real server-side content + per-route title — not the bare SPA shell.
    r = client.get("/blog/self-hosted-paas-docker-swarm")
    assert r.status_code == 200
    assert "<title>Self-hosting a PaaS on your Docker Swarm" in r.text
    assert '"@type":"BlogPosting"' in r.text
