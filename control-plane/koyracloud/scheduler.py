"""Cron scheduler: launches each app's manifest cron jobs on their schedule as
Swarm run-to-completion jobs from the app's current live image.

``due_jobs`` is pure w.r.t. time (``now`` injected) so it's unit-tested;
``launch`` runs one job over the injected ``DockerControl`` and records a
``CronRun``; ``CronScheduler.run`` is the background loop (modeled on
``monitor.UptimeMonitor``). Schedules are UTC. No catch-up: a job overdue after
downtime fires once, not once per missed slot.
"""
from __future__ import annotations

import datetime as dt
import threading

from croniter import croniter

from koyracloud import redisbus
from koyracloud.config import Settings
from koyracloud.crypto import CryptoBox
from koyracloud.db import Database
from koyracloud.docker_ctl import DockerControl
from koyracloud.models import App, AppRedis, CronJob, CronRun, Deploy


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _as_utc(d: dt.datetime) -> dt.datetime:
    """SQLite returns naive datetimes; treat naive as UTC so cron math + the
    ``<= now`` comparison stay timezone-consistent."""
    return d.replace(tzinfo=dt.timezone.utc) if d.tzinfo is None else d.astimezone(dt.timezone.utc)


def due_jobs(db: Database, now: dt.datetime | None = None) -> list[int]:
    """IDs of enabled cron jobs whose next fire (after the last run, or creation
    if never run) is at/before ``now`` — excluding jobs whose previous run is
    still in flight (skip-if-running overlap policy)."""
    now = now or _utcnow()
    out: list[int] = []
    with db.session() as s:
        for job in s.query(CronJob).filter_by(enabled=True).all():
            still_running = s.query(CronRun.id).filter_by(
                cron_job_id=job.id, status="running").first()
            if still_running:
                continue
            base = _as_utc(job.last_run_at or job.created_at)
            try:
                nxt = croniter(job.schedule, base).get_next(dt.datetime)
            except Exception:  # noqa: BLE001 — a malformed schedule never fires
                continue
            if _as_utc(nxt) <= now:
                out.append(job.id)
    return out


def launch(db: Database, docker: DockerControl, settings: Settings,
           crypto: CryptoBox, cron_job_id: int, *,
           now: dt.datetime | None = None) -> int | None:
    """Run one cron job to completion from the app's live image and record a
    ``CronRun``. Returns the run id, or None if the app has no live deploy yet
    (nothing to run) or the job/app vanished."""
    now = now or _utcnow()
    with db.session() as s:
        job = s.get(CronJob, cron_job_id)
        if job is None:
            return None
        app = s.get(App, job.app_id)
        if app is None:
            return None
        live = (s.query(Deploy).filter_by(app_id=app.id, status="live")
                .order_by(Deploy.id.desc()).first())
        if live is None or not live.commit:
            return None  # never successfully deployed → no image to run
        image = f"{settings.registry}/koyra-app-{app.name}:{live.commit[:12]}"
        command = job.command
        env = {e.key: e.value for e in app.env_vars}
        env.update({sec.key: crypto.decrypt(sec.value_encrypted) for sec in app.secrets})
        ar = s.get(AppRedis, app.id)
        if ar is not None:
            env["REDIS_URL"] = redisbus.redis_url(
                ar.username, crypto.decrypt(ar.password_encrypted),
                settings.redis_host, settings.redis_port)
        # Mark the fire time + open the run BEFORE launching so a concurrent tick
        # (or manual trigger) sees it as running and skips.
        job.last_run_at = now
        run = CronRun(cron_job_id=job.id, status="running", started_at=now)
        s.add(run)
        s.commit()
        run_id = run.id

    name = f"koyra-cron-{cron_job_id}-{run_id}"
    status, exit_code, log = "success", 0, ""
    try:
        docker.run_job(name, image, command, env=env,
                       networks=[settings.traefik_network])
        exit_code = docker.job_wait(name, timeout=settings.cron_job_timeout)
        log = docker.service_logs(name, tail=400)
        status = "success" if exit_code == 0 else "failed"
    except Exception as exc:  # noqa: BLE001 — record the failure, never raise out
        status, exit_code = "failed", None
        log = f"[koyra] cron run error: {exc}"
    finally:
        try:
            docker.remove_service(name)
        except Exception:  # noqa: BLE001 — reaping is best-effort
            pass

    with db.session() as s:
        run = s.get(CronRun, run_id)
        if run is not None:
            run.status, run.exit_code, run.log = status, exit_code, log
            run.finished_at = _utcnow()
            s.commit()
    return run_id


class CronScheduler:
    def __init__(self, db: Database, docker: DockerControl, settings: Settings,
                 crypto: CryptoBox, tick_seconds: int = 30):
        self.db = db
        self.docker = docker
        self.settings = settings
        self.crypto = crypto
        self.tick = tick_seconds
        self._stop = threading.Event()

    def _spawn(self, cron_job_id: int) -> None:
        # Each job runs in its own thread so a long job never blocks the loop or
        # other jobs; the running-status check keeps it from double-firing.
        threading.Thread(
            target=launch,
            args=(self.db, self.docker, self.settings, self.crypto, cron_job_id),
            daemon=True).start()

    def run(self) -> None:
        self._stop.wait(min(self.tick, 30))   # let startup settle
        while not self._stop.is_set():
            try:
                for jid in due_jobs(self.db):
                    self._spawn(jid)
            except Exception:  # noqa: BLE001 — never let the loop die
                pass
            self._stop.wait(self.tick)

    def start(self) -> None:
        threading.Thread(target=self.run, daemon=True).start()
