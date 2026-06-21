"""Native uptime monitor: periodically probes each live app's public URL,
records samples, tracks up/down with debounce, and reports transitions.

``check_once`` is pure w.r.t. I/O (prober + now injected) so it's unit-tested;
``UptimeMonitor.run`` is the background loop.
"""
from __future__ import annotations

import datetime as dt
import threading
from typing import Callable

import httpx

from koyracloud.db import Database
from koyracloud.models import App, UptimeSample, UptimeState

# prober(url) -> ok: a server responded (any status < 500) within the timeout.
Prober = Callable[[str], bool]
SAMPLE_RETENTION = dt.timedelta(days=7)
DOWN_THRESHOLD = 2  # consecutive failures before declaring DOWN (debounce)


def http_prober(url: str, timeout: float = 10.0) -> bool:
    try:
        r = httpx.get(url, timeout=timeout, follow_redirects=True)
        return r.status_code < 500
    except Exception:
        return False


def _primary_host(app: App) -> str | None:
    d = next((d for d in app.domains if d.is_primary), None) or (
        app.domains[0] if app.domains else None)
    return d.host if d else None


def check_once(db: Database, prober: Prober, *, now: dt.datetime | None = None,
               down_threshold: int = DOWN_THRESHOLD) -> list[tuple[int, str]]:
    """Probe every app that has gone live + has a host. Returns transitions as
    (app_id, "up"|"down")."""
    now = now or dt.datetime.now(dt.timezone.utc)
    transitions: list[tuple[int, str]] = []
    with db.session() as s:
        apps = s.query(App).all()
        for app in apps:
            if not any(d.status == "live" for d in app.deploys):
                continue
            host = _primary_host(app)
            if not host:
                continue
            ok = prober(f"https://{host}/")
            s.add(UptimeSample(app_id=app.id, ts=now, ok=ok))
            st = s.get(UptimeState, app.id) or UptimeState(app_id=app.id)
            st.last_checked = now
            if ok:
                st.consecutive_fail = 0
                if st.up is not True:
                    was_down = st.up is False  # recovery only alerts after a down
                    st.up = True
                    st.up_since = now
                    if was_down:
                        transitions.append((app.id, "up"))
            else:
                st.consecutive_fail += 1
                if st.consecutive_fail >= down_threshold and st.up is not False:
                    st.up = False
                    st.up_since = now
                    transitions.append((app.id, "down"))
            s.add(st)
        # prune old samples
        cutoff = now - SAMPLE_RETENTION
        s.query(UptimeSample).filter(UptimeSample.ts < cutoff).delete()
        s.commit()
    return transitions


def uptime_summary(db: Database, app_id: int, now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    with db.session() as s:
        st = s.get(UptimeState, app_id)
        day = now - dt.timedelta(hours=24)
        samples = s.query(UptimeSample).filter(
            UptimeSample.app_id == app_id, UptimeSample.ts >= day).all()
        total = len(samples)
        okc = sum(1 for x in samples if x.ok)
        pct = round(100.0 * okc / total, 2) if total else None
        return {
            "up": st.up if st else None,
            "since": st.up_since.isoformat() if st and st.up_since else None,
            "last_checked": st.last_checked.isoformat() if st and st.last_checked else None,
            "uptime_24h": pct,
            "samples_24h": total,
        }


class UptimeMonitor:
    def __init__(self, db: Database, interval: int,
                 on_transition: Callable[[int, str], None] | None = None,
                 prober: Prober = http_prober):
        self.db = db
        self.interval = interval
        self.on_transition = on_transition
        self.prober = prober
        self._stop = threading.Event()

    def run(self):
        # initial delay so the app finishes starting before the first sweep
        self._stop.wait(min(self.interval, 30))
        while not self._stop.is_set():
            try:
                for app_id, state in check_once(self.db, self.prober):
                    if self.on_transition:
                        self.on_transition(app_id, state)
            except Exception:  # noqa: BLE001 — never let the loop die
                pass
            self._stop.wait(self.interval)

    def start(self):
        threading.Thread(target=self.run, daemon=True).start()
