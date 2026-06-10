#!/usr/bin/env python3
"""koyracloud static-site server.

Serves a directory (Netlify-style) with SPA fallback, logs each request to
stdout (so runtime logs show traffic), and — when analytics env is set —
injects the koyracloud analytics beacon into HTML responses.

stdlib only, so it runs in the shared runtime image with no extra deps.
"""
from __future__ import annotations

import argparse
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

ANALYTICS_URL = os.environ.get("KOYRA_ANALYTICS_URL", "").rstrip("/")
ANALYTICS_SITE = os.environ.get("KOYRA_ANALYTICS_SITE", "")


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

    def _resolve(self) -> Path | None:
        rel = unquote(self.path.split("?", 1)[0].split("#", 1)[0]).lstrip("/")
        target = (self.root / rel).resolve()
        # containment: stay inside root
        if target != self.root and not str(target).startswith(str(self.root) + os.sep):
            return None
        if target.is_dir():
            target = target / "index.html"
        if target.is_file():
            return target
        # SPA fallback
        index = self.root / "index.html"
        return index if index.is_file() else None

    def _serve(self, write_body: bool):
        target = self._resolve()
        if target is None:
            self.send_error(404, "Not Found")
            return
        data = target.read_bytes()
        ctype = self.guess_type(str(target))
        if ctype.startswith("text/html"):
            data = _inject(data)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if write_body:
            self.wfile.write(data)

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
    print(f"=== [koyra:static] serving {Handler.root} on :{args.port} "
          f"(analytics={'on' if beacon_tag() else 'off'})", flush=True)
    ThreadingHTTPServer(("0.0.0.0", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
