"""End-to-end tests for the runtime static server (runtime-image/koyra_static.py):
real 404s vs SPA fallback, the spa flag, and security/custom response headers (#69).

The server is stdlib-only and lives outside the koyracloud package, so it's
imported by path and driven over a real ephemeral-port socket."""
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime-image"))
import koyra_static  # noqa: E402

INDEX = "<!doctype html><html><head><title>Home</title></head><body>home</body></html>"
NOTFOUND = "<!doctype html><html><head><title>404</title></head><body>gone</body></html>"


@pytest.fixture
def serve(tmp_path, monkeypatch):
    """Write `files` under a tmp root and serve them; returns the base URL.
    Module globals are monkeypatched so each test picks its own config."""
    servers = []

    def _start(files, *, spa=None, headers=None, analytics=("", "")):
        for rel, body in files.items():
            (tmp_path / rel).write_text(body)
        monkeypatch.setattr(koyra_static, "SPA", spa)
        eh = {"X-Content-Type-Options": "nosniff", "X-Frame-Options": "SAMEORIGIN"}
        eh.update(headers or {})
        monkeypatch.setattr(koyra_static, "EXTRA_HEADERS", eh)
        monkeypatch.setattr(koyra_static, "ANALYTICS_URL", analytics[0])
        monkeypatch.setattr(koyra_static, "ANALYTICS_SITE", analytics[1])
        koyra_static.Handler.root = tmp_path.resolve()
        srv = ThreadingHTTPServer(("127.0.0.1", 0), koyra_static.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
        return f"http://127.0.0.1:{srv.server_address[1]}"

    yield _start
    for s in servers:
        s.shutdown()


def test_existing_file_served_200(serve):
    base = serve({"index.html": INDEX, "about.html": "<p>about</p>"})
    r = httpx.get(base + "/about.html")
    assert r.status_code == 200 and "about" in r.text


def test_auto_serves_404_html_with_status_404(serve):
    base = serve({"index.html": INDEX, "404.html": NOTFOUND})
    r = httpx.get(base + "/does/not/exist")
    assert r.status_code == 404 and "gone" in r.text


def test_auto_spa_fallback_when_no_404_html(serve):
    base = serve({"index.html": INDEX})
    r = httpx.get(base + "/client/route")
    assert r.status_code == 200 and "home" in r.text


def test_spa_true_forces_index_even_with_404_html(serve):
    base = serve({"index.html": INDEX, "404.html": NOTFOUND}, spa=True)
    r = httpx.get(base + "/anything")
    assert r.status_code == 200 and "home" in r.text


def test_spa_false_serves_404_html(serve):
    base = serve({"index.html": INDEX, "404.html": NOTFOUND}, spa=False)
    r = httpx.get(base + "/anything")
    assert r.status_code == 404 and "gone" in r.text


def test_spa_false_bare_404_without_404_html(serve):
    base = serve({"index.html": INDEX}, spa=False)
    r = httpx.get(base + "/anything")
    assert r.status_code == 404 and "home" not in r.text


def test_default_security_headers(serve):
    base = serve({"index.html": INDEX})
    r = httpx.get(base + "/")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "SAMEORIGIN"


def test_security_headers_on_404(serve):
    base = serve({"index.html": INDEX}, spa=False)
    r = httpx.get(base + "/missing")
    assert r.status_code == 404
    assert r.headers["x-content-type-options"] == "nosniff"


def test_custom_headers_override_defaults(serve):
    base = serve({"index.html": INDEX},
                 headers={"X-Frame-Options": "DENY",
                          "Content-Security-Policy": "default-src 'self'"})
    r = httpx.get(base + "/")
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["content-security-policy"] == "default-src 'self'"


def test_beacon_still_injected_into_html(serve):
    base = serve({"index.html": INDEX}, analytics=("https://kc.example.com", "site123"))
    r = httpx.get(base + "/")
    assert 'data-site="site123"' in r.text and "/_k/a.js" in r.text
