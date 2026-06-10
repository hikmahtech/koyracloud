"""Minimal in-memory fixed-window rate limiter for the unauthenticated public
endpoints. Per-process (one control-plane replica), good enough to blunt abuse."""
from __future__ import annotations

import threading


class RateLimiter:
    def __init__(self, limit: int, window: int = 60):
        self.limit = limit
        self.window = window
        self._counts: dict = {}
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        import time
        now = time.time() if now is None else now
        w = int(now // self.window)
        with self._lock:
            if len(self._counts) > 20000:  # prune stale windows
                self._counts = {k: v for k, v in self._counts.items() if k[1] >= w}
            ck = (key, w)
            c = self._counts.get(ck, 0)
            if c >= self.limit:
                return False
            self._counts[ck] = c + 1
            return True
