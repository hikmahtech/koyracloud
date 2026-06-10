"""GitHub push-webhook helpers (push-to-deploy). Pure + unit-tested."""
from __future__ import annotations

import hashlib
import hmac


def verify_signature(secret: str, body: bytes, signature_header: str | None) -> bool:
    """Constant-time check of GitHub's X-Hub-Signature-256 (HMAC-SHA256)."""
    if not secret or not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def repo_slug(url: str) -> str:
    """Normalize a repo URL to ``owner/repo`` (lowercased), for matching against
    a webhook's repository.full_name."""
    s = url.strip().lower()
    for p in ("https://github.com/", "http://github.com/",
              "ssh://git@github.com/", "git@github.com:"):
        if s.startswith(p):
            s = s[len(p):]
            break
    if s.endswith(".git"):
        s = s[:-4]
    return s.strip("/")


def branch_from_ref(ref: str) -> str | None:
    """refs/heads/main -> main; tags/other refs -> None."""
    prefix = "refs/heads/"
    return ref[len(prefix):] if ref and ref.startswith(prefix) else None
