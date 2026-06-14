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


def deploy_target(event: str, payload: dict) -> tuple[str, str, str] | None:
    """Map a GitHub webhook to (repo_full_name, branch, commit_sha) to deploy,
    or None if this event shouldn't trigger one. Pure + unit-tested.

    - ``push``: deploy immediately (for repos with no gating CI).
    - ``workflow_run`` completed+success: deploy AFTER CI passes (repos with CI
      send this event instead of push). Failed/in-progress runs never deploy.
    """
    repo = (payload.get("repository") or {}).get("full_name", "").lower()
    if event == "push":
        branch = branch_from_ref(payload.get("ref", ""))
        sha = payload.get("after", "")
        return (repo, branch, sha) if repo and branch else None
    if event == "workflow_run":
        run = payload.get("workflow_run") or {}
        if payload.get("action") != "completed" or run.get("conclusion") != "success":
            return None
        branch = run.get("head_branch") or ""
        sha = run.get("head_sha", "")
        return (repo, branch, sha) if repo and branch else None
    return None
