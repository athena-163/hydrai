"""Route-local concurrency control."""

from __future__ import annotations

import threading
from contextlib import contextmanager


class RouteBusyError(RuntimeError):
    """Raised when a route is saturated."""


class RouteLimiter:
    def __init__(self, max_concurrency: int):
        self._sem = threading.BoundedSemaphore(max_concurrency)
        self._active = 0
        self._lock = threading.Lock()

    @contextmanager
    def slot(self):
        acquired = self._sem.acquire(blocking=False)
        if not acquired:
            raise RouteBusyError("route busy")
        with self._lock:
            self._active += 1
        try:
            yield
        finally:
            with self._lock:
                self._active -= 1
            self._sem.release()

    @property
    def active(self) -> int:
        with self._lock:
            return self._active

