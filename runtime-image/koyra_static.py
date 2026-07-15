#!/usr/bin/env python3
"""koyracloud static-site server.

Serves a directory (Netlify-style) with SPA fallback, logs each request to
stdout (so runtime logs show traffic), and — when analytics env is set —
injects the koyracloud analytics beacon into HTML responses.

stdlib only, so it runs in the shared runtime image with no extra deps.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

ANALYTICS_URL = os.environ.get("KOYRA_ANALYTICS_URL", "").rstrip("/")
ANALYTICS_SITE = os.environ.get("KOYRA_ANALYTICS_SITE", "")

# SPA-fallback mode for unmatched paths: "1" -> always index.html (200);
# "0" -> real 404s; unset -> auto (404.html present -> real 404, else SPA). #69
_SPA = os.environ.get("KOYRA_SPA", "")
SPA: bool | None = None if _SPA == "" else _SPA == "1"

# Response headers sent on every response: secure defaults + manifest overrides.
EXTRA_HEADERS = {"X-Content-Type-Options": "nosniff", "X-Frame-Options": "SAMEORIGIN"}
try:
    EXTRA_HEADERS.update(json.loads(os.environ.get("KOYRA_HEADERS") or "{}"))
except (ValueError, TypeError):
    pass


def beacon_tag() -> str:
    if ANALYTICS_URL and ANALYTICS_SITE:
        return (f'<script defer src="{ANALYTICS_URL}/_k/a.js" '
                f'data-site="{ANALYTICS_SITE}"></script>')
    return ""


def _inject(html: bytes) -> bytes:
    tag = beacon_tag()
    if not tag:
        return html
    text = html.decode("utf-8", "ignore")
    for anchor in ("</head>", "</body>"):
        if anchor in text:
            return text.replace(anchor, tag + anchor, 1).encode("utf-8")
    return (text + tag).encode("utf-8")


class Handler(SimpleHTTPRequestHandler):
    root = Path(".").resolve()

    def _resolve(self) -> tuple[Path, int] | None:
        """(file, status) to serve, or None for a bare 404. A direct file match
        is 200; with no match we fall back per SPA mode: force-SPA -> index/200,
        force-404 -> 404.html/404 (else bare), auto -> 404.html/404 when present
        else index/200 (preserving the old SPA behaviour)."""
        rel = unquote(self.path.split("?", 1)[0].split("#", 1)[0]).lstrip("/")
        target = (self.root / rel).resolve()
        # containment: stay inside root
        if target != self.root and not str(target).startswith(str(self.root) + os.sep):
            return None
        if target.is_dir():
            target = target / "index.html"
        if target.is_file():
            return target, 200
        index = self.root / "index.html"
        notfound = self.root / "404.html"
        if SPA is True:
            return (index, 200) if index.is_file() else None
        if SPA is False:
            return (notfound, 404) if notfound.is_file() else None
        if notfound.is_file():
            return notfound, 404
        return (index, 200) if index.is_file() else None

    def _serve(self, write_body: bool):
        resolved = self._resolve()
        if resolved is None:
            self.send_error(404, "Not Found")
            return
        target, status = resolved
        data = target.read_bytes()
        ctype = self.guess_type(str(target))
        if ctype.startswith("text/html"):
            data = _inject(data)
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if write_body:
            self.wfile.write(data)

    def end_headers(self):
        # Secure defaults + manifest headers, on every response incl. send_error.
        for k, v in EXTRA_HEADERS.items():
            self.send_header(k, v)
        super().end_headers()

    def do_GET(self):
        self._serve(write_body=True)

    def do_HEAD(self):
        self._serve(write_body=False)

    def log_message(self, fmt, *args):
        sys.stdout.write("%s - %s\n" % (self.address_string(), fmt % args))
        sys.stdout.flush()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=".")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    Handler.root = Path(args.dir).resolve()
    spa = "auto" if SPA is None else "on" if SPA else "off"
    print(f"=== [koyra:static] serving {Handler.root} on :{args.port} "
          f"(analytics={'on' if beacon_tag() else 'off'}, spa={spa})", flush=True)
    ThreadingHTTPServer(("0.0.0.0", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
