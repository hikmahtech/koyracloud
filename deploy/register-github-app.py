#!/usr/bin/env python3
"""Register the koyracloud GitHub App through GitHub's App Manifest flow.

    python3 deploy/register-github-app.py --host https://koyra.example.com [--org my-org]
        [--bind 0.0.0.0] [--port 8765] [--redirect-host <this machine as the browser sees it>]

Serves a page with one button. Click it in a browser signed in to GitHub (as an
owner of --org, or your own account without --org); GitHub shows the pre-filled
"Create GitHub App" form; on Create it redirects back here with a one-time code
that is exchanged for the App's credentials. The script then writes, next to
itself in the current directory:

    github-app.json               id, slug, client_id, html_url, owner (no secrets)
    github-app-client-secret.txt  the OAuth client secret, mode 0600 — feed it to
                                  `docker secret create koyra_github_client_secret -`

and exits. The private key and webhook secret GitHub also returns are discarded:
koyracloud uses user tokens only, never the App's own JWT.

If the browser runs on another machine, pass --bind 0.0.0.0 and --redirect-host
<this host's name or IP>, and open the firewall for --port while it runs. If the
redirect page fails to load anyway, run `register-github-app.py --code <code>`
with the code from the address bar.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

OUT_JSON = "github-app.json"
OUT_SECRET = "github-app-client-secret.txt"


def manifest(host: str, redirect: str) -> dict:
    return {
        "name": "koyracloud",
        "url": host,
        "description": "Deploy your repositories to koyracloud. Read-only access to the repos you choose.",
        "redirect_url": redirect,
        "callback_urls": [f"{host}/api/auth/callback"],
        "setup_url": f"{host}/new",
        "setup_on_update": True,
        "public": True,
        "default_permissions": {"contents": "read", "metadata": "read"},
        "default_events": [],
        # A webhook URL is required by the manifest schema; koyracloud's push-to-deploy
        # uses per-repo webhooks instead, so the App's own hook stays inactive.
        "hook_attributes": {"url": f"{host}/api/webhooks/github", "active": False},
    }


def convert(code: str) -> dict:
    req = urllib.request.Request(
        f"https://api.github.com/app-manifests/{code}/conversions", method="POST",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "koyracloud-register"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def save(app: dict) -> dict:
    public = {k: app.get(k) for k in ("id", "slug", "name", "client_id", "html_url")}
    public["owner"] = (app.get("owner") or {}).get("login")
    with open(OUT_JSON, "w") as f:
        json.dump(public, f, indent=2)
    fd = os.open(OUT_SECRET, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(app["client_secret"])
    return public


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", help="public base URL of this koyracloud, e.g. https://koyra.example.com")
    ap.add_argument("--org", default="", help="GitHub organisation to own the App (default: your user)")
    ap.add_argument("--bind", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--redirect-host", default="localhost",
                    help="how the browser reaches this machine (name or IP)")
    ap.add_argument("--code", help="skip the server: exchange a code copied from the address bar")
    args = ap.parse_args()

    if args.code:
        print(json.dumps(save(convert(args.code)), indent=2))
        print(f"client secret written to ./{OUT_SECRET} (mode 600)")
        return
    if not args.host:
        ap.error("--host is required")
    host = args.host.rstrip("/")
    state = secrets.token_urlsafe(12)
    redirect = f"http://{args.redirect_host}:{args.port}/callback"
    action = (f"https://github.com/organizations/{args.org}/settings/apps/new" if args.org
              else "https://github.com/settings/apps/new") + f"?state={state}"
    form = f"""<!doctype html><meta charset=utf-8><title>Register the koyracloud GitHub App</title>
<body style="font:16px system-ui;max-width:40em;margin:4em auto">
<h1>Register the koyracloud GitHub App</h1>
<p>Owner: <b>{args.org or "your GitHub account"}</b>. GitHub will show a pre-filled form; check
the name (it must be unique on GitHub) and click <b>Create GitHub App</b>.</p>
<form method="post" action="{action}">
<input type="hidden" name="manifest" value='{json.dumps(manifest(host, redirect)).replace("'", "&#39;")}'>
<button style="font-size:1.2em;padding:.6em 1.2em">Create the GitHub App on GitHub &rarr;</button>
</form>
<p style="color:#666">If the page after creation does not load, copy the <code>code=</code>
value from the address bar and run <code>register-github-app.py --code &lt;code&gt;</code>.</p>
</body>"""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):  # keep the terminal quiet
            pass

        def _send(self, body: str, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode())

        def do_GET(self):
            u = urlparse(self.path)
            if u.path != "/callback":
                return self._send(form)
            q = parse_qs(u.query)
            code, got_state = q.get("code", [""])[0], q.get("state", [""])[0]
            if not code or not secrets.compare_digest(got_state, state):
                return self._send("<h1>missing code or bad state</h1>", 400)
            try:
                public = save(convert(code))
            except Exception as exc:  # noqa: BLE001
                return self._send(f"<h1>conversion failed</h1><pre>{exc}</pre>", 500)
            self._send("<h1>Done. The App is registered; you can close this tab.</h1>")
            print(json.dumps(public, indent=2))
            print(f"client secret written to ./{OUT_SECRET} (mode 600)", flush=True)
            os._exit(0)

    print(f"open http://{args.redirect_host}:{args.port}/ in a browser signed in to GitHub", flush=True)
    HTTPServer((args.bind, args.port), Handler).serve_forever()


if __name__ == "__main__":
    sys.exit(main())
