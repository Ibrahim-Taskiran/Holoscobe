"""Shared parts of the background threads. Stdlib only."""
from __future__ import annotations

import threading
import time
from typing import Optional


class MonotonicClock:
    def now_ms(self) -> float:
        return time.monotonic() * 1000.0


class Worker:
    """One restartable daemon thread running _run() until `_stop` is set."""

    thread_name = "handcontrol-worker"

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=self.thread_name, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        t = self._thread
        if t is not None and t is not threading.current_thread():
            t.join(timeout)
        self._thread = None

    def _run(self) -> None:
        raise NotImplementedError


__all__ = ["MonotonicClock", "Worker"]
