"""Deploy orchestration: clone/pull → read manifest → render stack → deploy →
record. Runs in a background thread; appends log lines to the Deploy row so the
SSE endpoint can stream them.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from sqlalchemy import text

from koyracloud import redisbus
from koyracloud.build_hints import detect_log_hints
from koyracloud.config import Settings
from koyracloud.crypto import CryptoBox
from koyracloud.db import Database
from koyracloud.docker_ctl import DockerControl
from koyracloud.dockerfile import render_dockerfile
from koyracloud.healthcheck_preflight import detect_healthcheck_hint
from koyracloud.manifest import Manifest, parse_manifest
from koyracloud.models import AppAnalytics, AppPin, BuiltImage, CronJob, Deploy
from koyracloud.stack_render import render_stack, worker_service_name


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
    """Clone or fetch the repo at ``dest`` (a local build dir) and check out
    ``ref``. Returns the resolved commit sha. The checkout is the docker build
    context and is removed after the image is built."""
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
    # Provisions per-app Redis ACL users when a manifest sets `redis: true`.
    # None → built lazily from settings (a RedisClientAdmin) on first need.
    redis_admin: "redisbus.RedisAdmin | None" = None
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

    def _get_redis_admin(self) -> "redisbus.RedisAdmin":
        if self.redis_admin is None:
            self.redis_admin = redisbus.RedisClientAdmin(
                self.settings.redis_host, self.settings.redis_port,
                self.settings.redis_admin_password)
        return self.redis_admin

    def _sync_cron_jobs(self, db: Database, app_id: int, manifest: Manifest) -> None:
        """Mirror the manifest's cron jobs into the DB so the scheduler can read
        them without re-cloning: upsert by (app_id, name), delete dropped ones,
        and refresh schedule/command in place (preserving last_run_at + history)."""
        wanted = {c.name: c for c in manifest.cron}
        with db.session() as s:
            existing = {j.name: j for j in
                        s.query(CronJob).filter_by(app_id=app_id).all()}
            for name, job in existing.items():
                if name not in wanted:
                    s.delete(job)
            for name, spec in wanted.items():
                job = existing.get(name)
                if job is None:
                    s.add(CronJob(app_id=app_id, name=name,
                                  schedule=spec.schedule, command=spec.command))
                else:
                    job.schedule, job.command = spec.schedule, spec.command
            s.commit()

    def _service_node(self, app_name: str) -> str:
        """Hostname of the node the app's web task is placed on, or '' if the
        service isn't scheduled yet. Best-effort — any docker error returns ''."""
        try:
            st = self.docker.service_status(f"koyra-{app_name}_{app_name}")
        except Exception:  # noqa: BLE001
            return ""
        for t in st.get("tasks", []):
            if t.get("node"):
                return t["node"]
        return ""

    @staticmethod
    def _running_new(st: dict, image: str) -> int:
        """Running tasks of THIS deploy's image. During a start-first update the
        old task keeps serving (and counting as Running) until the new one is
        healthy, and after an automatic rollback only old-image tasks remain —
        so plain replica counting lies; image identity is what distinguishes
        \"new task live\" from \"previous deployment still serving\". A task
        with no image field (test fakes) counts as new."""
        n = 0
        for t in st.get("tasks", []):
            img = t.get("image", "")
            if t.get("state", "").startswith("Running") and (
                    not img or img == image or img.startswith(image + "@")):
                n += 1
        return n

    def _wait_converged(self, emit: Callable[[str], None],
                        app_name: str, manifest: Manifest, image: str) -> None:
        """Block until every service in the app's stack converges — all desired
        replicas Running ON THIS DEPLOY'S IMAGE (with a healthcheck, swarm only
        reports Running once the container is healthy) — or raise with the real
        task error from `service ps --no-trunc`.

        `docker stack deploy` returns as soon as tasks are *created*; whether
        they ever start is a separate question, and answering it here is what
        keeps the deploy status truthful. Failure modes:
        - swarm rolled back / paused THIS update (guarded on having seen it
          start, since UpdateStatus persists from previous deploys) → the
          previous deployment is still serving; fail immediately and say so.
        - no task left with desired-state Running but errors recorded → swarm
          exhausted the restart policy; fail immediately with the task error.
        - anything else (restart-looping, stuck Starting, never scheduled) →
          fail at the timeout, surfacing the last task error seen.
        """
        services = [f"koyra-{app_name}_{app_name}"] + [
            f"koyra-{app_name}_{worker_service_name(app_name, w.name)}"
            for w in manifest.workers]
        deadline = time.monotonic() + self.settings.deploy_converge_timeout
        last_err: dict[str, str] = {}
        emitted: set[str] = set()
        saw_updating: set[str] = set()
        pending = services
        while True:
            still = []
            for svc in pending:
                st = self.docker.service_status(svc)
                errs = st.get("errors") or [
                    t["error"] for t in st.get("tasks", []) if t.get("error")]
                if errs:
                    last_err[svc] = errs[0]
                    if errs[0] not in emitted:  # surface while still retrying
                        emitted.add(errs[0])
                        emit(f"[koyra] {svc} task error: {errs[0]}")
                update = st.get("update_state", "")
                if update == "updating":
                    saw_updating.add(svc)
                elif svc in saw_updating and (
                        update == "paused" or update.startswith("rollback")):
                    raise RuntimeError(
                        f"swarm rolled back the update to {svc} — the previous "
                        f"deployment is still running and serving traffic. "
                        f"Task error: {last_err.get(svc) or 'unknown'}")
                desired = st.get("desired", 0)
                if st.get("exists") and desired > 0 \
                        and self._running_new(st, image) >= desired:
                    emit(f"[koyra] {svc} converged ({desired}/{desired} running)")
                    continue
                if st.get("exists") and not st.get("tasks") and last_err.get(svc):
                    # No task is even trying anymore: restart attempts exhausted.
                    raise RuntimeError(
                        f"{svc} failed to start (swarm gave up retrying): "
                        f"{last_err[svc]}")
                still.append(svc)
            if not still:
                return
            if time.monotonic() >= deadline:
                svc = still[0]
                st = self.docker.service_status(svc)
                detail = last_err.get(svc) or (
                    "no task error reported — check the service logs (task "
                    f"state: {(st.get('tasks') or [{}])[0].get('state', 'not scheduled')})")
                old_serving = st.get("running", 0) > self._running_new(st, image)
                raise RuntimeError(
                    f"{svc} did not converge within "
                    f"{self.settings.deploy_converge_timeout}s "
                    f"({self._running_new(st, image)}/{st.get('desired', 0)} on the new "
                    f"image{'; the previous deployment is still serving traffic' if old_serving else ''}): "
                    f"{detail}")
            time.sleep(self.settings.deploy_converge_poll)
            pending = still

    def _save_pin_node(self, db: Database, app_id: int, node: str) -> None:
        """Record the node a pinned app landed on (no-op if it got unpinned)."""
        with db.session() as s:
            pin = s.get(AppPin, app_id)
            if pin is not None:
                pin.node = node
                s.commit()

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
            pinned = app.pin is not None
            pin_node = app.pin.node if app.pin else ""

        def emit(line: str, status: str | None = None) -> None:
            # Prefix every log line with a UTC wall-clock time so the build/deploy
            # log itself shows when each step ran (the deploy's date is in the
            # history row's created_at). ponytail: HH:MM:SS UTC — a deploy spans
            # seconds/minutes, so a per-line date would just repeat noise.
            line = f"{dt.datetime.now(dt.timezone.utc):%H:%M:%S} {line}"
            # Atomic single-statement UPDATE (no prior SELECT): a read-then-write
            # in one transaction can hit SQLite's WAL read->write upgrade
            # deadlock (SQLITE_BUSY_SNAPSHOT, which busy_timeout does NOT retry)
            # when a concurrent connection — e.g. an app's analytics ingest —
            # commits between the SELECT and the UPDATE. This is the deploy's
            # hot write path (one call per build/push log line).
            with db.session() as s:
                if status:
                    s.execute(text(
                        "UPDATE deploys SET log = COALESCE(log, '') || :l, "
                        "status = :st WHERE id = :i"),
                        {"l": line + "\n", "st": status, "i": deploy_id})
                else:
                    s.execute(text(
                        "UPDATE deploys SET log = COALESCE(log, '') || :l "
                        "WHERE id = :i"),
                        {"l": line + "\n", "i": deploy_id})
                s.commit()

        dest: Path | None = None
        build_log_lines: list[str] = []
        try:
            emit(f"[koyra] deploy #{deploy_id} for {app_name} @ {ref}", "building")
            # Clone to LOCAL disk (build_dir), never NFS: the build runs here and
            # its result goes into an image, so NFS small-file I/O never touches a
            # build (that's what made npm ci glacial and stalled the control plane).
            dest = Path(self.settings.build_dir) / f"{app_name}-{deploy_id}"
            commit = self.cloner(repo_url, ref, self.settings.github_pat, dest)
            with db.session() as s:
                s.execute(text('UPDATE deploys SET "commit" = :c WHERE id = :i'),
                          {"c": commit, "i": deploy_id})
                s.commit()
            emit(f"[koyra] checked out {commit[:12]}")

            manifest, synthesized = resolve_manifest(dest, app_name)
            if synthesized:
                emit("[koyra] no manifest found; repo looks static → runtime: static")
            emit(f"[koyra] manifest ok: {manifest.name} (runtime={manifest.runtime})")

            # Build context: the repo root, or a subdirectory for monorepo apps
            # (manifest.root). The Dockerfile path and any generated Dockerfile are
            # relative to this context. Resolve symlinks and assert the context
            # stays inside the clone, so a crafted manifest + an in-repo symlink
            # can't point the build context (and COPY) at the host filesystem.
            dest_real = dest.resolve()
            if manifest.root:
                build_ctx = (dest / manifest.root).resolve()
                if not build_ctx.is_dir():
                    raise FileNotFoundError(
                        f"manifest root '{manifest.root}' is not a directory in the repo")
                if build_ctx != dest_real and not str(build_ctx).startswith(str(dest_real) + os.sep):
                    raise ValueError(f"manifest root '{manifest.root}' escapes the repo")
                emit(f"[koyra] build context: {manifest.root}/")
            else:
                build_ctx = dest_real

            # Build a per-app image: either the repo's OWN Dockerfile, or one we
            # generate from the manifest. Build-time-inlined vars (NEXT_PUBLIC_*/
            # VITE_*) go in as build-args; secrets stay runtime-only (not baked).
            if manifest.uses_dockerfile:
                dockerfile = manifest.dockerfile or "Dockerfile"
                dockerfile_path = build_ctx / dockerfile
                if not dockerfile_path.is_file():
                    raise FileNotFoundError(
                        f"manifest references {dockerfile} but it's not in the build context")
                emit(f"[koyra] building image from {dockerfile}", "building")
                # Best-effort: a healthcheck against a python3-less alpine final
                # stage never fails the build/deploy, so this must fire on the
                # happy path, not just in the except block below (unlike
                # detect_log_hints) — swarm kills the container 30-60s later.
                try:
                    dockerfile_text = dockerfile_path.read_text(errors="replace")
                except OSError:
                    dockerfile_text = ""
                hint = detect_healthcheck_hint(manifest, dockerfile_text)
                if hint:
                    emit(f"[koyra] Hint: {hint}")
            else:
                dockerfile = ".koyra.Dockerfile"
                (build_ctx / dockerfile).write_text(
                    render_dockerfile(manifest, self.settings.runtime_image))
                emit("[koyra] building image (generated Dockerfile)", "building")

            base = f"{self.settings.registry}/koyra-app-{app_name}"
            # The image identity is the commit AND a hash of the build-args
            # (NEXT_PUBLIC_*/VITE_* etc. inlined at build time). Tagging by
            # commit alone meant an env-only change silently reused the stale
            # image; folding the build-args into the tag forces a rebuild when
            # any of them change, while an unchanged redeploy (e.g. re-rendering
            # routing after a domain change) still maps to the same tag.
            build_args = {**manifest.env, **env_overrides}
            args_hash = hashlib.sha256(
                json.dumps(build_args, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()[:12]
            image = f"{base}:{commit[:12]}-{args_hash}"
            # Skip the build only when this exact image (commit + build-args) was
            # already built + pushed by a prior deploy: it's in the registry, so
            # the redeploy is a pure swarm service deploy — no control-plane
            # rebuild.
            with db.session() as s:
                already_built = s.query(BuiltImage.id).filter(
                    BuiltImage.app_id == app_id, BuiltImage.tag == image).first() is not None
            if already_built:
                emit(f"[koyra] {commit[:12]} (build {args_hash}) already in the "
                     "registry → reusing the image (no rebuild)")
            else:
                for line in self.docker.image_build(image, str(build_ctx), build_args,
                                                    str(build_ctx / dockerfile)):
                    build_log_lines.append(line)
                    emit(line)
                self.docker.image_tag(image, f"{base}:latest")
                emit(f"[koyra] pushing {image} → registry", "building")
                for line in self.docker.image_push(image):
                    build_log_lines.append(line)
                    emit(line)
                for line in self.docker.image_push(f"{base}:latest"):
                    build_log_lines.append(line)
                    emit(line)
                with db.session() as s:
                    s.add(BuiltImage(app_id=app_id, tag=image))
                    s.commit()

            # Ensure each persist dir exists on the NFS so its volume's device
            # path resolves (the control plane has the NFS base mounted).
            for d in manifest.persist:
                (Path(self.settings.nfs_base) / app_name / d).mkdir(
                    parents=True, exist_ok=True)

            # Provision the shared-Redis ACL user (stable URL across redeploys)
            # when the manifest opts in; fail loudly if the instance has no Redis.
            redis_url = ""
            if manifest.redis:
                emit("[koyra] provisioning Redis (shared bus, scoped ACL user)")
                redis_url = redisbus.provision(
                    db, self.crypto, self.settings, self._get_redis_admin(),
                    app_id, app_name)
                emit(f"[koyra] Redis ready — REDIS_URL injected "
                     f"(namespace keys/channels as `{app_name}:`)")

            # Mirror manifest cron jobs into the DB for the scheduler.
            self._sync_cron_jobs(db, app_id, manifest)
            if manifest.cron:
                emit(f"[koyra] {len(manifest.cron)} cron job(s) scheduled (UTC)")
            if manifest.workers:
                emit(f"[koyra] {len(manifest.workers)} worker(s) in this stack")

            # Pinned but node not yet recorded: if the app is already running
            # (a redeploy), learn its current node now so this deploy pins it;
            # a brand-new app has no task yet and gets pinned after it converges.
            if pinned and not pin_node:
                pin_node = self._service_node(app_name)
                if pin_node:
                    self._save_pin_node(db, app_id, pin_node)
                    emit(f"[koyra] pinned to node {pin_node}")

            stack = render_stack(
                manifest,
                app_name=app_name,
                image=image,
                env_overrides=env_overrides,
                secret_values=secret_values,
                settings=self.settings,
                hosts=hosts or None,
                analytics_site=analytics_site,
                redis_url=redis_url,
                pin_node=pin_node,
            )
            emit("[koyra] image ready; deploying service to swarm", "deploying")
            for line in self.docker.deploy(f"koyra-{app_name}", stack):
                emit(line)
            # `stack deploy` only CREATES tasks — success means nothing until
            # the service actually converges (task Running + healthy). Wait for
            # it; on failure this raises with the real task error and the
            # except path below marks the deploy failed.
            emit("[koyra] stack deployed; waiting for the service to converge")
            self._wait_converged(emit, app_name, manifest, image)
            # Only the newest live deploy actually serves traffic — each deploy
            # replaces the running container — so demote any prior live row for
            # this app in the same transaction that marks this one live.
            with db.session() as s:
                s.execute(text("UPDATE deploys SET status = 'superseded' "
                               "WHERE app_id = :a AND status = 'live' AND id != :i"),
                          {"a": app_id, "i": deploy_id})
                s.execute(text("UPDATE deploys SET log = COALESCE(log, '') || :l, "
                               "status = 'live' WHERE id = :i"),
                          {"l": "[koyra] deploy complete — live\n", "i": deploy_id})
                s.commit()
            # Brand-new pinned app: record the node swarm just placed it on, so
            # future deploys carry the constraint. Swarm assigns the node at
            # schedule time (before the container is up), but `service ps` can lag
            # the deploy by a beat — retry briefly, else learn on the next deploy.
            if pinned and not pin_node:
                for _ in range(5):
                    pin_node = self._service_node(app_name)
                    if pin_node:
                        break
                    time.sleep(1.0)
                if pin_node:
                    self._save_pin_node(db, app_id, pin_node)
                    emit(f"[koyra] pinned to node {pin_node} (recorded for future deploys)")
            self._fire(app_id, "deploy_live", "", hosts[0] if hosts else "")
        except Exception as exc:  # noqa: BLE001 — surface a scrubbed error
            msg = str(exc)
            if self.settings.github_pat:
                msg = msg.replace(self.settings.github_pat, "***")
            emit(f"[koyra] FAILED: {msg}", "failed")
            for hint in detect_log_hints(build_log_lines):
                emit(f"[koyra] Hint: {hint}")
            # Full traceback goes to the server's stderr only, never the UI log.
            print(traceback.format_exc(), file=sys.stderr)
            self._fire(app_id, "deploy_failed", msg, hosts[0] if hosts else "")
        finally:
            if dest is not None:
                shutil.rmtree(dest, ignore_errors=True)   # free the local build dir
            with db.session() as s:
                s.execute(text("UPDATE deploys SET finished_at = :t WHERE id = :i"),
                          {"t": dt.datetime.now(dt.timezone.utc), "i": deploy_id})
                s.commit()
