"""GitHub OAuth login, allowlist, and signed-cookie sessions.

OAuth is done with plain httpx calls (no extra session middleware needed). The
allowlist and session encode/decode are pure and unit-tested. A dev-login bypass
(``KOYRA_DEV_LOGIN``) skips OAuth entirely for local work.
"""
from __future__ import annotations

import httpx
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

SESSION_COOKIE = "koyra_session"
OAUTH_STATE_COOKIE = "koyra_oauth_state"
SESSION_MAX_AGE = 60 * 60 * 24 * 14  # 14 days
_SALT = "koyra-session"

GITHUB_AUTHORIZE = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN = "https://github.com/login/oauth/access_token"
GITHUB_USER = "https://api.github.com/user"


def is_allowed(login: str, allowed_logins: list[str]) -> bool:
    """A login is allowed only if it appears in the allowlist (case-insensitive).
    An empty allowlist denies everyone (fail-closed)."""
    return login.lower() in {x.lower() for x in allowed_logins}


def _serializer(secret: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret, salt=_SALT)


def make_session(login: str, secret: str) -> str:
    return _serializer(secret).dumps({"login": login})


def read_session(token: str, secret: str, max_age: int = SESSION_MAX_AGE) -> str | None:
    try:
        data = _serializer(secret).loads(token, max_age=max_age)
        return data.get("login")
    except (BadSignature, SignatureExpired):
        return None


def authorize_url(client_id: str, redirect_uri: str, state: str,
                  scope: str = "read:user") -> str:
    from urllib.parse import urlencode
    q = {"client_id": client_id, "redirect_uri": redirect_uri, "state": state}
    if scope:  # OAuth Apps need a scope; a GitHub App's permissions live on the app
        q["scope"] = scope
    return f"{GITHUB_AUTHORIZE}?{urlencode(q)}"


def _token_post(data: dict, client: httpx.Client) -> dict:
    tok = client.post(GITHUB_TOKEN, headers={"Accept": "application/json"},
                      data=data).json()
    if not tok.get("access_token"):
        raise ValueError(f"github token exchange failed: {tok}")
    return tok


def exchange_code(code: str, client_id: str, client_secret: str,
                  client: httpx.Client | None = None) -> tuple[str, dict]:
    """Exchange an OAuth code for (github login, token response). For a GitHub
    App with expiring user tokens the response also carries refresh_token and
    expires_in. ``client`` is injectable for tests."""
    owns = client is None
    client = client or httpx.Client(timeout=15)
    try:
        tok = _token_post({"client_id": client_id, "client_secret": client_secret,
                           "code": code}, client)
        user = client.get(
            GITHUB_USER,
            headers={"Authorization": f"Bearer {tok['access_token']}",
                     "Accept": "application/json"},
        ).json()
        login = user.get("login")
        if not login:
            raise ValueError(f"github user fetch failed: {user}")
        return login, tok
    finally:
        if owns:
            client.close()


def refresh_token(refresh: str, client_id: str, client_secret: str,
                  client: httpx.Client | None = None) -> dict:
    """Trade a GitHub App refresh token for a new access + refresh token pair."""
    owns = client is None
    client = client or httpx.Client(timeout=15)
    try:
        return _token_post({"client_id": client_id, "client_secret": client_secret,
                            "grant_type": "refresh_token", "refresh_token": refresh},
                           client)
    finally:
        if owns:
            client.close()
