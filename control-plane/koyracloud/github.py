"""GitHub App user tokens (Vercel-style private repo access).

Active only when ``GITHUB_APP_SLUG`` is set, i.e. the login OAuth belongs to a
GitHub App. A user's login token then carries the App's read-only *Contents*
permission on exactly the repos they installed the App on. It is stored
encrypted on the ``users`` row, refreshed here when it expires, and used to
list those repos (New app picker) and to clone them at deploy time.
"""
from __future__ import annotations

import datetime as dt
import logging

import httpx

from koyracloud import auth
from koyracloud.config import Settings
from koyracloud.crypto import CryptoBox
from koyracloud.db import Database
from koyracloud.models import User

API = "https://api.github.com"
_REFRESH_SLACK = dt.timedelta(seconds=60)


def install_url(settings: Settings) -> str:
    """Where a user installs the App on (or re-configures it for) their repos."""
    return f"https://github.com/apps/{settings.github_app_slug}/installations/new"


def store_token(user: User, tok: dict, crypto: CryptoBox) -> None:
    """Persist a token response (from exchange_code / refresh_token) encrypted."""
    user.github_token_encrypted = crypto.encrypt(tok["access_token"])
    refresh = tok.get("refresh_token")
    user.github_refresh_encrypted = crypto.encrypt(refresh) if refresh else ""
    exp = tok.get("expires_in")
    user.github_token_expires_at = (
        dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=int(exp)) if exp else None)


def user_token(db: Database, crypto: CryptoBox, settings: Settings, login: str,
               client: httpx.Client | None = None) -> str:
    """The user's current GitHub token, refreshed first if it is about to
    expire. "" when the user never connected (signed in before the App was
    configured) or the refresh failed (authorization revoked / GitHub down);
    callers then fall back to the platform PAT."""
    if not login:
        return ""
    with db.session() as s:
        u = s.query(User).filter_by(github_login=login).first()
        if u is None or not u.github_token_encrypted:
            return ""
        exp = u.github_token_expires_at
        if exp is not None and exp.tzinfo is None:
            exp = exp.replace(tzinfo=dt.timezone.utc)  # SQLite hands back naive
        if exp is not None and exp <= dt.datetime.now(dt.timezone.utc) + _REFRESH_SLACK:
            if not u.github_refresh_encrypted:
                return ""
            try:
                tok = auth.refresh_token(crypto.decrypt(u.github_refresh_encrypted),
                                         settings.github_client_id,
                                         settings.github_client_secret, client)
            except (httpx.HTTPError, ValueError) as exc:
                logging.warning("github token refresh for %s failed: %s", login, exc)
                return ""
            store_token(u, tok, crypto)
            s.commit()
        return crypto.decrypt(u.github_token_encrypted)


def list_repos(token: str, client: httpx.Client | None = None) -> list[dict]:
    """Repos the user can reach through the App's installations, newest push
    first. ponytail: first 100 installations x 100 repos each; add pagination
    when someone actually has more."""
    owns = client is None
    client = client or httpx.Client(timeout=15)
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    repos: list[dict] = []
    try:
        r = client.get(f"{API}/user/installations", headers=headers,
                       params={"per_page": 100})
        r.raise_for_status()
        for inst in r.json().get("installations", []):
            rr = client.get(f"{API}/user/installations/{inst['id']}/repositories",
                            headers=headers, params={"per_page": 100})
            rr.raise_for_status()
            repos += rr.json().get("repositories", [])
    finally:
        if owns:
            client.close()
    repos.sort(key=lambda x: x.get("pushed_at") or "", reverse=True)
    return [{"full_name": x["full_name"], "private": bool(x.get("private")),
             "default_branch": x.get("default_branch") or "main",
             "url": x.get("html_url") or f"https://github.com/{x['full_name']}"}
            for x in repos]
