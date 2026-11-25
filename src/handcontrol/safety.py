"""Safety layer: epoch/staleness guard around any ActionSink, and an independent loss watchdog.

Stdlib + contracts only.
"""
from __future__ import annotations

import threading
from typing import Callable, Optional

from handcontrol.background import Worker
from handcontrol.contracts import Action, ActionKind, ActionSink, Clock

DEFAULT_MAX_AGE_MS = 150.0
DEFAULT_LOSS_TIMEOUT_MS = 200.0


class GuardedSink:
    """ActionSink wrapper. Drops wrong-epoch and stale actions; RELEASE_ALL always passes.

    If dispatch is asynchronous (a queue between producer and OS), put a GuardedSink at the
    consumer end too, bound to the producer's current epoch.
    """

    def __init__(
        self,
        inner: ActionSink,
        clock: Clock,
        epoch_source: Callable[[], int],
        max_age_ms: float = DEFAULT_MAX_AGE_MS,
    ) -> None:
        self._inner = inner
        self._clock = clock
        self._epoch_source = epoch_source
        self._max_age_ms = max_age_ms
        self._lock = threading.Lock()
        self.dropped_epoch = 0
        self.dropped_stale = 0
        self.failed = 0
        self.release_failures = 0

    @property
    def inner(self) -> ActionSink:
        return self._inner

    @property
    def dropped_total(self) -> int:
        return self.dropped_epoch + self.dropped_stale

    def dispatch(self, action: Action) -> bool:
        if action.kind is ActionKind.RELEASE_ALL:
            try:
                ok = bool(self._inner.dispatch(action))
            except Exception:
                ok = False
            if not ok:
                self.release_all()
            return True
        if action.epoch != self._epoch_source():
            with self._lock:
                self.dropped_epoch += 1
            return False
        if self._clock.now_ms() - action.capture_ms > self._max_age_ms:
            with self._lock:
                self.dropped_stale += 1
            return False
        try:
            ok = bool(self._inner.dispatch(action))
        except Exception:
            ok = False
        if not ok:
            with self._lock:
                self.failed += 1
        return ok

    def release_all(self) -> None:
        try:
            self._inner.release_all()
        except Exception:
            with self._lock:
                self.release_failures += 1


class Watchdog(Worker):
    """Fires `on_timeout` once when no usable capture was fed for `timeout_ms`.

    Independent of the frame loop: `start()` runs a daemon thread that polls `check()`.
    Tests call `check(now_ms)` with a fake clock. After firing it stays quiet until the next
    `feed()`. `disarm()` stops it until the next feed (use while nothing can be owned).
    """

    thread_name = "handcontrol-watchdog"

    def __init__(
        self,
        clock: Clock,
        on_timeout: Callable[[], None],
        timeout_ms: float = DEFAULT_LOSS_TIMEOUT_MS,
        poll_ms: float = 10.0,
    ) -> None:
        super().__init__()
        self._clock = clock
        self._on_timeout = on_timeout
        self.timeout_ms = timeout_ms
        self._poll_s = max(poll_ms, 1.0) / 1000.0
        self._lock = threading.Lock()
        self._last_ms: Optional[float] = None
        self._armed = False
        self.fired_count = 0
        self.callback_errors = 0

    @property
    def armed(self) -> bool:
        return self._armed

    @property
    def last_usable_ms(self) -> Optional[float]:
        return self._last_ms

    def feed(self, capture_ms: float) -> None:
        with self._lock:
            if self._last_ms is None or capture_ms >= self._last_ms:
                self._last_ms = capture_ms
            self._armed = True

    def disarm(self) -> None:
        with self._lock:
            self._armed = False

    def check(self, now_ms: Optional[float] = None) -> bool:
        now = self._clock.now_ms() if now_ms is None else now_ms
        with self._lock:
            if not self._armed or self._last_ms is None:
                return False
            if now - self._last_ms < self.timeout_ms:
                return False
            self._armed = False
            self.fired_count += 1
        try:
            self._on_timeout()
        except Exception:
            self.callback_errors += 1
        return True

    def stop(self, timeout: float = 1.0) -> None:
        super().stop(timeout)

    def _run(self) -> None:
        while not self._stop.wait(self._poll_s):
            self.check()
