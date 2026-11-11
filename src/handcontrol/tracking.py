"""MediaPipe Tasks HandLandmarker wrapper, tracking stats and the camera->tracker loop.

mediapipe / numpy / cv2 are imported lazily; tests inject ``landmarker_factory`` and ``image_factory``.
"""
from __future__ import annotations

import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Optional

from .contracts import FrameSample, Handedness, HandSample, Landmark

MODEL_RELATIVE = Path("assets") / "models" / "hand_landmarker.task"
MSG_MODEL_MISSING = "El izleme modeli bulunamadı: {path}"


class ModelNotFoundError(FileNotFoundError):
    """Hand landmarker model file is missing."""


def project_root() -> Path:
    """Project root in a source checkout, or the packaged app dir when frozen."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


def default_model_path() -> Path:
    return project_root() / MODEL_RELATIVE


class _MonotonicClock:
    def now_ms(self) -> float:
        return time.monotonic() * 1000.0


def _default_image_factory(frame_bgr: Any) -> Any:
    import mediapipe as mp  # lazy
    import numpy as np  # lazy

    rgb = np.ascontiguousarray(frame_bgr[:, :, ::-1])  # BGR -> RGB
    return mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)


def _default_landmarker_factory(model_path: str, num_hands: int, conf: float) -> Any:
    import mediapipe as mp  # lazy
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision

    options = vision.HandLandmarkerOptions(
        base_options=mp_python.BaseOptions(
            # Buffer, not path: MediaPipe cannot open non-ASCII paths (e.g. Turkish user folders).
            model_asset_buffer=Path(model_path).read_bytes(),
            delegate=mp_python.BaseOptions.Delegate.CPU,
        ),
        running_mode=vision.RunningMode.VIDEO,
        num_hands=num_hands,
        min_hand_detection_confidence=conf,
        min_hand_presence_confidence=conf,
        min_tracking_confidence=conf,
    )
    return vision.HandLandmarker.create_from_options(options)


class HandTracker:
    """Runs HandLandmarker in VIDEO mode on UNMIRRORED BGR frames and returns FrameSample.

    swap_handedness: MediaPipe assumes a mirrored (selfie) input; on unmirrored input labels may be
    inverted. Default False (raw label); verify on real hands and flip via this flag if needed.
    """

    def __init__(
        self,
        model_path: Optional[str | Path] = None,
        *,
        clock: Any = None,
        landmarker_factory: Optional[Callable[[str, int, float], Any]] = None,
        image_factory: Optional[Callable[[Any], Any]] = None,
        num_hands: int = 2,
        confidence: float = 0.55,
        swap_handedness: bool = False,
    ) -> None:
        self.model_path = Path(model_path) if model_path else default_model_path()
        self._clock = clock or _MonotonicClock()
        self._landmarker_factory = landmarker_factory or _default_landmarker_factory
        self._image_factory = image_factory or _default_image_factory
        self._num_hands = num_hands
        self._confidence = confidence
        self._swap = swap_handedness
        self._landmarker: Any = None
        self._last_ts = -1

    def load(self) -> None:
        """Create the landmarker. Raises ModelNotFoundError if the model file is missing."""
        if self._landmarker is not None:
            return
        if not self.model_path.is_file():
            raise ModelNotFoundError(MSG_MODEL_MISSING.format(path=self.model_path))
        self._landmarker = self._landmarker_factory(
            str(self.model_path), self._num_hands, self._confidence
        )

    def close(self) -> None:
        lm, self._landmarker = self._landmarker, None
        if lm is not None:
            try:
                lm.close()
            except Exception:
                pass

    def _next_timestamp(self, capture_ms: float) -> int:
        ts = int(capture_ms)
        if ts <= self._last_ts:
            ts = self._last_ts + 1
        self._last_ts = ts
        return ts

    def process(self, frame_bgr: Any, capture_ms: float) -> FrameSample:
        self.load()
        shape = getattr(frame_bgr, "shape", None)
        height, width = (int(shape[0]), int(shape[1])) if shape is not None else (0, 0)
        image = self._image_factory(frame_bgr)
        ts = self._next_timestamp(capture_ms)
        result = self._landmarker.detect_for_video(image, ts)
        hands = self._convert(result)
        return FrameSample(
            capture_ms=capture_ms,
            inference_done_ms=self._clock.now_ms(),
            width=width,
            height=height,
            hands=hands,
        )

    def _convert(self, result: Any) -> tuple[HandSample, ...]:
        lms = getattr(result, "hand_landmarks", None) or []
        handed = getattr(result, "handedness", None) or []
        worlds = getattr(result, "hand_world_landmarks", None) or []
        hands: list[HandSample] = []
        for i, pts in enumerate(lms):
            if len(pts) != 21:
                continue
            label, score = Handedness.UNKNOWN, 0.0
            if i < len(handed) and handed[i]:
                cat = handed[i][0]
                name = str(getattr(cat, "category_name", "") or "").lower()
                score = float(getattr(cat, "score", 0.0) or 0.0)
                if name in ("left", "right"):
                    if self._swap:
                        name = "right" if name == "left" else "left"
                    label = Handedness.LEFT if name == "left" else Handedness.RIGHT
            world = None
            if i < len(worlds) and len(worlds[i]) == 21:
                world = tuple(Landmark(float(p.x), float(p.y), float(p.z)) for p in worlds[i])
            hands.append(
                HandSample(
                    handedness=label,
                    handedness_score=score,
                    landmarks=tuple(Landmark(float(p.x), float(p.y), float(p.z)) for p in pts),
                    world_landmarks=world,
                )
            )
        return tuple(hands)


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * q
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


class TrackingStats:
    """Rolling capture age, inference time and output rate (p50/p95)."""

    def __init__(self, window: int = 120) -> None:
        self._lock = threading.Lock()
        self._age: deque[float] = deque(maxlen=window)
        self._infer: deque[float] = deque(maxlen=window)
        self._done: deque[float] = deque(maxlen=window)

    def record(self, sample: FrameSample, inference_ms: float) -> None:
        with self._lock:
            self._age.append(sample.inference_done_ms - sample.capture_ms)
            self._infer.append(inference_ms)
            self._done.append(sample.inference_done_ms)

    def snapshot(self) -> dict[str, float]:
        with self._lock:
            age, infer, done = list(self._age), list(self._infer), list(self._done)
        intervals = [b - a for a, b in zip(done, done[1:]) if b > a]
        rates = [1000.0 / d for d in intervals]
        return {
            "capture_age_ms_p50": _percentile(age, 0.5),
            "capture_age_ms_p95": _percentile(age, 0.95),
            "inference_ms_p50": _percentile(infer, 0.5),
            "inference_ms_p95": _percentile(infer, 0.95),
            "output_fps": (len(done) - 1) * 1000.0 / (done[-1] - done[0])
            if len(done) > 1 and done[-1] > done[0]
            else 0.0,
            "output_fps_p50": _percentile(rates, 0.5),
            "output_fps_p95": _percentile(rates, 0.95),
            "samples": float(len(done)),
        }


class TrackingLoop:
    """Thread: camera.read_latest -> tracker.process -> callback(FrameSample). Newest frame only."""

    def __init__(
        self,
        camera: Any,
        tracker: HandTracker,
        callback: Callable[[FrameSample], None],
        *,
        clock: Any = None,
        stats: Optional[TrackingStats] = None,
        on_error: Optional[Callable[[str], None]] = None,
        max_consecutive_errors: int = 5,
        poll_timeout_s: float = 0.05,
    ) -> None:
        self._camera = camera
        self._tracker = tracker
        self._callback = callback
        self._clock = clock or _MonotonicClock()
        self.stats = stats or TrackingStats()
        self._on_error = on_error
        self._max_errors = max_consecutive_errors
        self._poll = poll_timeout_s
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.last_error: Optional[str] = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self.last_error = None
        self._thread = threading.Thread(target=self._run, name="tracking-loop", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        t = self._thread
        if t is not None and t is not threading.current_thread():
            t.join(timeout)
        self._thread = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _fail(self, message: str) -> None:
        self.last_error = message
        if self._on_error is not None:
            try:
                self._on_error(message)
            except Exception:
                pass

    def _run(self) -> None:
        errors = 0
        try:
            self._tracker.load()
        except ModelNotFoundError as exc:
            self._fail(str(exc))
            return
        except Exception as exc:
            self._fail(f"İzleme başlatılamadı: {exc}")
            return
        try:
            while not self._stop.is_set():
                item = self._camera.read_latest(self._poll)
                if item is None:
                    continue
                frame, capture_ms = item
                t0 = self._clock.now_ms()
                try:
                    sample = self._tracker.process(frame, capture_ms)
                except Exception as exc:
                    errors += 1
                    if errors >= self._max_errors:
                        self._fail(f"İzleme durdu: {exc}")
                        return
                    continue
                errors = 0
                self.stats.record(sample, sample.inference_done_ms - t0)
                try:
                    self._callback(sample)
                except Exception:
                    pass
        finally:
            self._tracker.close()
