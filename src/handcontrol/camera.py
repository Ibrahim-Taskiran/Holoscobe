"""Camera capture: background thread, newest-frame buffer (size 1), lifecycle states.

cv2 is imported lazily and can be replaced through ``capture_factory`` so tests run with fakes.
"""
from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Optional

from .background import MonotonicClock, Worker
from .contracts import CameraState

# Turkish user-facing messages.
MSG_PERMISSION = "Kamera izni reddedildi. Windows Gizlilik ayarlarından kamera erişimine izin verin."
MSG_BUSY = "Kamera meşgul. Başka bir uygulama kamerayı kullanıyor olabilir."
MSG_NOT_FOUND = "Kamera bulunamadı."
MSG_LOST = "Kamera bağlantısı koptu."

BACKENDS = ("msmf", "dshow", "auto")


class CameraOpenError(Exception):
    """Raised by a capture factory. kind: 'permission' | 'busy' | 'not_found'."""

    def __init__(self, kind: str, detail: str = "") -> None:
        super().__init__(detail or kind)
        self.kind = kind


_KIND_MESSAGES = {"permission": MSG_PERMISSION, "busy": MSG_BUSY, "not_found": MSG_NOT_FOUND}


@dataclass(frozen=True)
class CameraConfig:
    index: int = 0
    backend: str = "msmf"      # "msmf" | "dshow" | "auto" (msmf then dshow)
    width: int = 640
    height: int = 480
    fps: int = 30


def backend_order(backend: str) -> tuple[str, ...]:
    """Backends to try, in order. DirectShow is a selectable fallback; 'auto' tries MSMF then DSHOW."""
    if backend == "dshow":
        return ("dshow",)
    if backend == "auto":
        return ("msmf", "dshow")
    return ("msmf",)


def default_capture_factory(index: int, backend: str, cfg: CameraConfig) -> Any:
    """Open a cv2.VideoCapture (lazy cv2 import). Returns an opened capture or raises CameraOpenError."""
    import cv2  # lazy

    api = cv2.CAP_MSMF if backend == "msmf" else cv2.CAP_DSHOW
    cap = cv2.VideoCapture(index, api)
    if not cap.isOpened():
        cap.release()
        raise CameraOpenError("not_found", f"index {index} backend {backend}")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, cfg.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg.height)
    cap.set(cv2.CAP_PROP_FPS, cfg.fps)
    return cap


# cv2 property ids (stable constants) so fakes need no cv2.
PROP_WIDTH = 3
PROP_HEIGHT = 4
PROP_FPS = 5


def _safe_release(cap: Any) -> None:
    try:
        cap.release()
    except Exception:
        pass


class Camera(Worker):
    """Threaded capture with a one-slot newest-frame buffer.

    start() is non-blocking; the worker thread opens the device (with bounded retries and backoff),
    then reads frames. States: OFF -> STARTING -> RUNNING -> (ERROR | OFF).
    """

    thread_name = "camera-capture"

    def __init__(
        self,
        config: Optional[CameraConfig] = None,
        *,
        clock: Any = None,
        capture_factory: Optional[Callable[[int, str, CameraConfig], Any]] = None,
        max_open_attempts: int = 3,
        backoff_base_s: float = 0.25,
        backoff_max_s: float = 2.0,
        max_read_failures: int = 30,
        max_reconnects: int = 2,
        on_state_change: Optional[Callable[[CameraState, Optional[str]], None]] = None,
    ) -> None:
        super().__init__()
        self.config = config or CameraConfig()
        self._clock = clock or MonotonicClock()
        self._factory = capture_factory or default_capture_factory
        self._max_open_attempts = max(1, max_open_attempts)
        self._backoff_base = backoff_base_s
        self._backoff_max = backoff_max_s
        self._max_read_failures = max(1, max_read_failures)
        self._max_reconnects = max_reconnects
        self._callback = on_state_change

        self._state = CameraState.OFF
        self._last_error: Optional[str] = None
        self._state_lock = threading.Lock()
        self._state_cond = threading.Condition(self._state_lock)

        self._frame_cond = threading.Condition()
        self._latest: Optional[tuple[Any, float, int]] = None   # (frame, capture_ms, seq)
        self._seq = 0
        self._returned_seq = 0

        self._reported = (0, 0, 0.0)
        self._measured_wh: Optional[tuple[int, int]] = None
        self._capture_times: deque[float] = deque(maxlen=60)
        self.frames_captured = 0
        self.frames_dropped = 0

    # ---------- properties ----------
    @property
    def state(self) -> CameraState:
        with self._state_lock:
            return self._state

    @property
    def last_error(self) -> Optional[str]:
        with self._state_lock:
            return self._last_error

    @property
    def reported_width(self) -> int:
        return self._reported[0]

    @property
    def reported_height(self) -> int:
        return self._reported[1]

    @property
    def reported_fps(self) -> float:
        return self._reported[2]

    @property
    def measured_width(self) -> int:
        return self._measured_wh[0] if self._measured_wh else 0

    @property
    def measured_height(self) -> int:
        return self._measured_wh[1] if self._measured_wh else 0

    @property
    def measured_fps(self) -> float:
        times = list(self._capture_times)
        if len(times) < 2 or times[-1] <= times[0]:
            return 0.0
        return (len(times) - 1) * 1000.0 / (times[-1] - times[0])

    @property
    def actual_width(self) -> int:
        return self.measured_width or self.reported_width

    @property
    def actual_height(self) -> int:
        return self.measured_height or self.reported_height

    @property
    def actual_fps(self) -> float:
        return self.measured_fps or self.reported_fps

    # ---------- lifecycle ----------
    def start(self) -> None:
        if self.running:
            return
        with self._frame_cond:
            self._latest = None
        self._set_state(CameraState.STARTING, None)
        super().start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        with self._frame_cond:
            self._frame_cond.notify_all()
        super().stop(timeout)
        with self._frame_cond:
            self._latest = None
        self._set_state(CameraState.OFF, None)

    def reconnect(self) -> None:
        """Explicit recovery (e.g. from ERROR): stop and start again."""
        self.stop()
        self.start()

    def wait_for_state(self, states: Any, timeout: float = 5.0) -> bool:
        wanted = set(states) if not isinstance(states, CameraState) else {states}
        with self._state_cond:
            return self._state_cond.wait_for(lambda: self._state in wanted, timeout)

    def read_latest(self, timeout: float = 0.0) -> Optional[tuple[Any, float]]:
        """Newest frame as (frame_bgr, capture_ms), or None. Never returns the same frame twice."""
        with self._frame_cond:
            if timeout > 0 and (self._latest is None or self._latest[2] == self._returned_seq):
                self._frame_cond.wait_for(
                    lambda: self._stop.is_set()
                    or (self._latest is not None and self._latest[2] != self._returned_seq),
                    timeout,
                )
            item = self._latest
            if item is None or item[2] == self._returned_seq:
                return None
            self._returned_seq = item[2]
            return item[0], item[1]

    # ---------- internals ----------
    def _set_state(self, state: CameraState, error: Optional[str]) -> None:
        with self._state_cond:
            changed = state != self._state or error != self._last_error
            self._state = state
            self._last_error = error
            self._state_cond.notify_all()
        if changed and self._callback is not None:
            try:
                self._callback(state, error)
            except Exception:
                pass

    def _open_with_retries(self) -> tuple[Optional[Any], str]:
        """Try backends in order for up to N rounds with backoff. Returns (capture, error_message)."""
        message = MSG_NOT_FOUND
        for attempt in range(self._max_open_attempts):
            for backend in backend_order(self.config.backend):
                if self._stop.is_set():
                    return None, message
                try:
                    cap = self._factory(self.config.index, backend, self.config)
                    if cap is not None:
                        return cap, ""
                except Exception as exc:
                    message = _KIND_MESSAGES.get(getattr(exc, "kind", ""), MSG_NOT_FOUND)
            if attempt < self._max_open_attempts - 1:
                delay = min(self._backoff_max, self._backoff_base * (2 ** attempt))
                if delay > 0 and self._stop.wait(delay):
                    return None, message
        return None, message

    def _query_reported(self, cap: Any) -> None:
        try:
            self._reported = (
                int(cap.get(PROP_WIDTH) or 0),
                int(cap.get(PROP_HEIGHT) or 0),
                float(cap.get(PROP_FPS) or 0.0),
            )
        except Exception:
            self._reported = (0, 0, 0.0)

    def _run(self) -> None:
        cap: Optional[Any] = None
        reconnects = 0
        try:
            while not self._stop.is_set():
                cap, message = self._open_with_retries()
                if cap is None:
                    if not self._stop.is_set():
                        self._set_state(CameraState.ERROR, message)
                    return
                self._query_reported(cap)
                self._capture_times.clear()
                self._set_state(CameraState.RUNNING, None)
                lost = self._read_loop(cap)
                _safe_release(cap)
                cap = None
                if not lost or self._stop.is_set():
                    return
                reconnects += 1
                if reconnects > self._max_reconnects:
                    self._set_state(CameraState.ERROR, MSG_LOST)
                    return
                self._set_state(CameraState.STARTING, None)
        finally:
            if cap is not None:
                _safe_release(cap)

    def _read_loop(self, cap: Any) -> bool:
        """Returns True when the device was lost (caller may reconnect), False on stop."""
        failures = 0
        while not self._stop.is_set():
            try:
                ok, frame = cap.read()
            except Exception:
                ok, frame = False, None
            if not ok or frame is None:
                failures += 1
                if failures >= self._max_read_failures:
                    return True
                self._stop.wait(0.005)
                continue
            failures = 0
            capture_ms = self._clock.now_ms()
            self._publish(frame, capture_ms)
        return False

    def _publish(self, frame: Any, capture_ms: float) -> None:
        shape = getattr(frame, "shape", None)
        if shape is not None and len(shape) >= 2:
            self._measured_wh = (int(shape[1]), int(shape[0]))
        self._capture_times.append(capture_ms)
        with self._frame_cond:
            if self._latest is not None and self._latest[2] != self._returned_seq:
                self.frames_dropped += 1
            self._seq += 1
            self.frames_captured += 1
            self._latest = (frame, capture_ms, self._seq)
            self._frame_cond.notify_all()
