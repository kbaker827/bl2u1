"""Abuse guards for a public server: per-visitor upload rate and total upload storage."""

import os
import time
from collections import deque
from threading import Lock


class RateLimiter:
    """Allow at most `limit` events per `window` seconds for each key (e.g. client IP)."""

    def __init__(self, limit: int, window: float = 3600):
        self.limit  = limit
        self.window = window
        self._hits: dict[str, deque] = {}
        self._lock  = Lock()

    def allow(self, key: str) -> bool:
        """Record an event for key; return False if it is over the limit."""
        if self.limit <= 0:
            return True
        now = time.monotonic()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True

    def is_blocked(self, key: str) -> bool:
        """True if key has already used up its limit (does not record an event)."""
        if self.limit <= 0:
            return False
        now = time.monotonic()
        with self._lock:
            hits = self._hits.get(key)
            return bool(hits) and sum(1 for t in hits if now - t <= self.window) >= self.limit

    def prune(self) -> None:
        """Forget keys with no recent events (keeps memory bounded)."""
        now = time.monotonic()
        with self._lock:
            for key in [k for k, h in self._hits.items() if not h or now - h[-1] > self.window]:
                del self._hits[key]


def folder_size(path: str) -> int:
    """Total size in bytes of the regular files directly inside path."""
    total = 0
    try:
        with os.scandir(path) as entries:
            for entry in entries:
                try:
                    if entry.is_file(follow_symlinks=False):
                        total += entry.stat(follow_symlinks=False).st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total
