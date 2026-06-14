"""Deploy orchestration: clone/pull → read manifest → render stack → deploy →
record. Runs in a background thread; appends log lines to the Deploy row so the
SSE endpoint can stream them.
"""
from __future__ import annotations

import base64
import datetime as dt
import re
import secrets
import shutil
import subprocess
import sys
import threading
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from koyracloud.config import Settings
from koyracloud.crypto import CryptoBox
from koyracloud.db import Database
from koyracloud.docker_ctl import DockerControl
from koyracloud.dockerfile import render_dockerfile
from koyracloud.manifest import Manifest, parse_manifest
from koyracloud.models import AppAnalytics, Deploy
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


_STATIC_DIRS = ("dist", "build", "public", "out", "_site")


def is_static_repo(repo: Path) -> bool:
    """Heuristic: a repo with an index.html (at root or in a common build dir)
    and no manifest is treated as a static site."""
    if (repo / "index.html").is_file():
        return True
    return any((repo / d / "index.html").is_file() for d in _STATIC_DIRS)


def resolve_manifest(dest: Path, app_name: str) -> tuple[Manifest, bool]:
    """Read .paas/app.yaml, or — if absent and the repo looks static —
    synthesize a static manifest on the volume. Returns (manifest, synthesized).
    Raises FileNotFoundError with guidance if neither applies."""
    mp = dest / ".paas" / "app.yaml"
    if mp.is_file():
        return parse_manifest(mp.read_text()), False
    if is_static_repo(dest):
        mp.parent.mkdir(parents=True, exist_ok=True)
        mp.write_text(f"name: {app_name}\nruntime: static\n")
        return parse_manifest(mp.read_text()), True
    raise FileNotFoundError(
        "No .paas/app.yaml in the repo, and it doesn't look like a static site "
        "(no index.html found). Add a manifest — see the docs at /docs.")


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
    _locks: dict = field(default_factory=dict)
    _locks_guard: threading.Lock = field(default_factory=threading.Lock)

    def _lock_for(self, app_id: int) -> threading.Lock:
        with self._locks_guard:
            lk = self._locks.get(app_id)
            if lk is None:
                lk = threading.Lock()
                self._locks[app_id] = lk
            return lk

    def run_deploy(self, db: Database, deploy_id: int) -> None:
        """Serialize deploys per app so concurrent deploys can't race the shared
        volume; different apps still deploy in parallel."""
        with db.session() as s:
            d = s.get(Deploy, deploy_id)
            if d is None:
                return
            app_id = d.app_id
        with self._lock_for(app_id):
            self._run_deploy(db, deploy_id)

    def _fire(self, app_id: int, event: str, detail: str, host: str) -> None:
        if self.on_event:
            try:
                self.on_event(app_id, event, detail, host)
            except Exception:  # noqa: BLE001
                pass

    def _run_deploy(self, db: Database, deploy_id: int) -> None:
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
            if an is None:  # backfill for apps created before analytics existed
                an = AppAnalytics(app_id=app.id, token=secrets.token_urlsafe(12), enabled=True)
                s.add(an)
                s.commit()
            analytics_site = an.token if an.enabled else ""

        def emit(line: str, status: str | None = None) -> None:
            with db.session() as s:
                d = s.get(Deploy, deploy_id)
                d.log = (d.log or "") + line + "\n"
                if status:
                    d.status = status
                s.add(d)
                s.commit()

        dest: Path | None = None
        try:
            emit(f"[koyra] deploy #{deploy_id} for {app_name} @ {ref}", "building")
            # Clone to LOCAL disk (build_dir), never NFS: the build runs here and
            # its result goes into an image, so NFS small-file I/O never touches a
            # build (that's what made npm ci glacial and stalled the control plane).
            dest = Path(self.settings.build_dir) / f"{app_name}-{deploy_id}"
            commit = self.cloner(repo_url, ref, self.settings.github_pat, dest)
            with db.session() as s:
                d = s.get(Deploy, deploy_id)
                d.commit = commit
                s.add(d)
                s.commit()
            emit(f"[koyra] checked out {commit[:12]}")

            manifest, synthesized = resolve_manifest(dest, app_name)
            if synthesized:
                emit("[koyra] no manifest found; repo looks static → runtime: static")
            emit(f"[koyra] manifest ok: {manifest.name} (runtime={manifest.runtime})")

            # Build a per-app image: either the repo's OWN Dockerfile, or one we
            # generate from the manifest. Build-time-inlined vars (NEXT_PUBLIC_*/
            # VITE_*) go in as build-args; secrets stay runtime-only (not baked).
            if manifest.uses_dockerfile:
                dockerfile = manifest.dockerfile or "Dockerfile"
                if not (dest / dockerfile).is_file():
                    raise FileNotFoundError(
                        f"manifest references {dockerfile} but it's not in the repo")
                emit(f"[koyra] building image from {dockerfile}", "building")
            else:
                dockerfile = ".koyra.Dockerfile"
                (dest / dockerfile).write_text(
                    render_dockerfile(manifest, self.settings.runtime_image))
                emit("[koyra] building image (generated Dockerfile)", "building")

            base = f"{self.settings.registry}/koyra-app-{app_name}"
            image = f"{base}:{commit[:12]}"
            build_args = {**manifest.env, **env_overrides}
            for line in self.docker.image_build(image, str(dest), build_args,
                                                str(dest / dockerfile)):
                emit(line)
            self.docker.image_tag(image, f"{base}:latest")
            emit(f"[koyra] pushing {image} → registry", "building")
            for line in self.docker.image_push(image):
                emit(line)
            for line in self.docker.image_push(f"{base}:latest"):
                emit(line)

            # Ensure each persist dir exists on the NFS so its volume's device
            # path resolves (the control plane has the NFS base mounted).
            for d in manifest.persist:
                (Path(self.settings.nfs_base) / app_name / d).mkdir(
                    parents=True, exist_ok=True)

            stack = render_stack(
                manifest,
                app_name=app_name,
                image=image,
                env_overrides=env_overrides,
                secret_values=secret_values,
                settings=self.settings,
                hosts=hosts or None,
                analytics_site=analytics_site,
            )
            emit("[koyra] image ready; deploying service to swarm", "deploying")
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
            if dest is not None:
                shutil.rmtree(dest, ignore_errors=True)   # free the local build dir
            with db.session() as s:
                d = s.get(Deploy, deploy_id)
                d.finished_at = dt.datetime.now(dt.timezone.utc)
                s.add(d)
                s.commit()
