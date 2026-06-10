"""Deploy orchestration: clone/pull → read manifest → render stack → deploy →
record. Runs in a background thread; appends log lines to the Deploy row so the
SSE endpoint can stream them.
"""
from __future__ import annotations

import base64
import datetime as dt
import re
import subprocess
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from koyracloud.config import Settings
from koyracloud.crypto import CryptoBox
from koyracloud.db import Database
from koyracloud.docker_ctl import DockerControl
from koyracloud.manifest import parse_manifest
from koyracloud.models import Deploy
from koyracloud.stack_render import render_stack


_SAFE_REF = re.compile(r"^[A-Za-z0-9._/-]+$")


def validate_repo_ref(repo_url: str, ref: str) -> None:
    """Reject values that could smuggle git flags or unexpected transports.
    Defense-in-depth alongside the API-layer schema validation."""
    if repo_url.startswith("-") or not (
            repo_url.startswith("https://") or repo_url.startswith("git@")):
        raise ValueError(f"unsafe repo_url: {repo_url!r}")
    if ref.startswith("-") or not _SAFE_REF.match(ref):
        raise ValueError(f"unsafe git ref: {ref!r}")


def _auth_args(token: str) -> list[str]:
    """git -c args that pass the token via an Authorization header instead of
    embedding it in the URL (keeps it out of argv / process listings)."""
    if not token:
        return []
    cred = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return ["-c", f"http.extraHeader=Authorization: Basic {cred}"]


def _git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    """Run a git command, raising with the actual stderr on failure (so deploy
    logs show the real error, not just an exit code). Token args are scrubbed
    from any raised message."""
    r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    if check and r.returncode != 0:
        shown = " ".join("-c http.extraHeader=***" if "extraHeader" in a else a
                         for a in args)
        raise RuntimeError(f"git {shown} failed: {(r.stderr or r.stdout).strip()}")
    return r


def git_clone(repo_url: str, ref: str, token: str, dest: Path) -> str:
    """Clone or fetch the repo at ``dest`` and check out ``ref``. Returns the
    resolved commit sha. Populates the SAME NFS path the container mounts, so
    the runtime entrypoint only has to fast-forward."""
    validate_repo_ref(repo_url, ref)
    auth = _auth_args(token)
    dest.mkdir(parents=True, exist_ok=True)
    if not (dest / ".git").is_dir():
        _git([*auth, "clone", "--no-single-branch", "--", repo_url, "."], dest)
    else:
        _git(["remote", "set-url", "origin", repo_url], dest)
        _git([*auth, "fetch", "--all", "--prune"], dest)
    _git(["checkout", ref], dest)
    _git([*auth, "pull", "--ff-only"], dest, check=False)
    return _git(["rev-parse", "HEAD"], dest).stdout.strip()


@dataclass
class Deployer:
    settings: Settings
    docker: DockerControl
    crypto: CryptoBox
    cloner: Callable[[str, str, str, Path], str] = git_clone
    # on_event(app_id, event, detail, host) — fired on deploy_live / deploy_failed.
    on_event: Callable[[int, str, str, str], None] | None = None

    def _fire(self, app_id: int, event: str, detail: str, host: str) -> None:
        if self.on_event:
            try:
                self.on_event(app_id, event, detail, host)
            except Exception:  # noqa: BLE001
                pass

    def run_deploy(self, db: Database, deploy_id: int) -> None:
        """Execute a deploy end-to-end, updating the Deploy row as it goes."""
        with db.session() as s:
            deploy = s.get(Deploy, deploy_id)
            if deploy is None:
                return
            app = deploy.app
            app_id = app.id
            app_name, repo_url, ref = app.name, app.repo_url, deploy.ref
            env_overrides = {e.key: e.value for e in app.env_vars}
            secret_values = {sec.key: self.crypto.decrypt(sec.value_encrypted)
                             for sec in app.secrets}
            # Primary host first, so it's the canonical one in the router rule.
            hosts = [d.host for d in sorted(
                app.domains, key=lambda d: (not d.is_primary, d.id))]
            an = app.analytics
            analytics_site = an.token if (an and an.enabled) else ""

        def emit(line: str, status: str | None = None) -> None:
            with db.session() as s:
                d = s.get(Deploy, deploy_id)
                d.log = (d.log or "") + line + "\n"
                if status:
                    d.status = status
                s.add(d)
                s.commit()

        try:
            emit(f"[koyra] deploy #{deploy_id} for {app_name} @ {ref}", "building")
            dest = Path(self.settings.nfs_base) / app_name / "repo"
            commit = self.cloner(repo_url, ref, self.settings.github_pat, dest)
            with db.session() as s:
                d = s.get(Deploy, deploy_id)
                d.commit = commit
                s.add(d)
                s.commit()
            emit(f"[koyra] checked out {commit[:12]}")

            manifest = parse_manifest((dest / ".paas" / "app.yaml").read_text())
            emit(f"[koyra] manifest ok: {manifest.name} (runtime={manifest.runtime})")

            # One-off build container: install deps + build frontend on the
            # volume ONCE, before the long-running service starts. This avoids
            # the served container racing its own healthcheck/restart and
            # multiple npm builds corrupting the shared NFS node_modules.
            build_env = {
                "KOYRA_REPO_URL": repo_url,
                "KOYRA_REF": commit,
                "KOYRA_WORKSPACE": "/workspace",
            }
            if self.settings.github_pat:
                build_env["KOYRA_GIT_TOKEN"] = self.settings.github_pat
            volume = f"{self.settings.nfs_base}/{app_name}:/workspace"
            emit("[koyra] building (one-off container)", "building")
            for line in self.docker.build(self.settings.runtime_image, build_env, volume):
                emit(line)

            stack = render_stack(
                manifest,
                app_name=app_name,
                repo_url=repo_url,
                ref=commit,
                git_token=self.settings.github_pat,
                env_overrides=env_overrides,
                secret_values=secret_values,
                settings=self.settings,
                hosts=hosts or None,
                analytics_site=analytics_site,
            )
            emit("[koyra] build ok; deploying service to swarm", "deploying")
            for line in self.docker.deploy(f"koyra-{app_name}", stack):
                emit(line)
            emit("[koyra] deploy complete — live", "live")
            self._fire(app_id, "deploy_live", "", hosts[0] if hosts else "")
        except Exception as exc:  # noqa: BLE001 — surface a scrubbed error
            msg = str(exc)
            if self.settings.github_pat:
                msg = msg.replace(self.settings.github_pat, "***")
            emit(f"[koyra] FAILED: {msg}", "failed")
            # Full traceback goes to the server's stderr only, never the UI log.
            print(traceback.format_exc(), file=sys.stderr)
            self._fire(app_id, "deploy_failed", msg, hosts[0] if hosts else "")
        finally:
            with db.session() as s:
                d = s.get(Deploy, deploy_id)
                d.finished_at = dt.datetime.now(dt.timezone.utc)
                s.add(d)
                s.commit()
