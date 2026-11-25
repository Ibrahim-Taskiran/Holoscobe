"""MediaPipe Tasks HandLandmarker wrapper, tracking stats and the camera->tracker loop.

mediapipe / numpy / cv2 are imported lazily; tests inject ``landmarker_factory`` and ``image_factory``.
"""
from __future__ import annotations

import logging
import sys
import threading
from collections import deque
from pathlib import Path
from typing import Any, Callable, Optional

from .filters import percentile
from .background import MonotonicClock, Worker
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


def _default_image_factory(frame_bgr: Any) -> Any:
    import cv2  # lazy
    import mediapipe as mp  # lazy

    return mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))


DEFAULT_DETECTION_CONFIDENCE = 0.5
DEFAULT_PRESENCE_CONFIDENCE = 0.35
DEFAULT_TRACKING_CONFIDENCE = 0.35


def _default_landmarker_factory(
    model_path: str,
    num_hands: int,
    detection: float,
    presence: Optional[float] = None,
    tracking: Optional[float] = None,
) -> Any:
    """Presence/tracking default to the detection value (old 3-argument call shape)."""
    presence = detection if presence is None else presence
    tracking = detection if tracking is None else tracking
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
        min_hand_detection_confidence=detection,
        min_hand_presence_confidence=presence,
        min_tracking_confidence=tracking,
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
        confidence: Optional[float] = None,
        detection_confidence: Optional[float] = None,
        presence_confidence: Optional[float] = None,
        tracking_confidence: Optional[float] = None,
        swap_handedness: bool = False,
        pose_enabled: Optional[Callable[[], bool]] = None,
        fast_single_hand: Optional[Callable[[], bool]] = None,
    ) -> None:
        """``confidence`` sets all three thresholds; the specific arguments override it.

        fast_single_hand: when given, a lone hand is tracked by a one-hand model while it returns True
        (see adaptive_hands.py). None keeps the plain two-hand model (the measuring tools).

        Injected ``landmarker_factory`` keeps the legacy ``(model_path, num_hands, conf)`` call
        and receives the detection value; only the built-in factory gets all three.
        """
        self.model_path = Path(model_path) if model_path else default_model_path()
        self._clock = clock or MonotonicClock()
        self._landmarker_factory = landmarker_factory or _default_landmarker_factory
        self._image_factory = image_factory or _default_image_factory
        self._num_hands = num_hands
        self._custom_factory = landmarker_factory is not None
        self._detection = self._pick(detection_confidence, confidence, DEFAULT_DETECTION_CONFIDENCE)
        self._presence = self._pick(presence_confidence, confidence, DEFAULT_PRESENCE_CONFIDENCE)
        self._tracking = self._pick(tracking_confidence, confidence, DEFAULT_TRACKING_CONFIDENCE)
        self._swap = swap_handedness
        self._pose_enabled = pose_enabled
        self._fast_single_hand = fast_single_hand
        self._pose = None
        self._pose_failed = False
        self._landmarker: Any = None
        self._last_ts = -1

    @staticmethod
    def _pick(specific: Optional[float], general: Optional[float], default: float) -> float:
        if specific is not None:
            return float(specific)
        return float(general) if general is not None else default

    @property
    def confidences(self) -> tuple[float, float, float]:
        """(detection, presence, tracking)."""
        return (self._detection, self._presence, self._tracking)

    def load(self) -> None:
        """Create the landmarker. Raises ModelNotFoundError if the model file is missing."""
        if self._landmarker is not None:
            return
        if not self.model_path.is_file():
            raise ModelNotFoundError(MSG_MODEL_MISSING.format(path=self.model_path))
        full = self._create(self._num_hands)
        if self._fast_single_hand is None or self._num_hands < 2:
            self._landmarker = full
            return
        from .adaptive_hands import AdaptiveLandmarker
        try:
            single = self._create(1)
        except Exception:
            full.close()
            raise
        self._landmarker = AdaptiveLandmarker(full, single, allowed=self._fast_single_hand)

    def _create(self, num_hands: int) -> Any:
        if self._custom_factory:
            return self._landmarker_factory(str(self.model_path), num_hands, self._detection)
        return self._landmarker_factory(
            str(self.model_path), num_hands, self._detection, self._presence, self._tracking
        )

    def close(self) -> None:
        if self._pose is not None:
            self._pose.close()
            self._pose = None
        self._pose_failed = False
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
        crossed = None
        if self._pose_enabled and self._pose_enabled() and not self._pose_failed:
            crossed = self._crossed(image, ts, width / max(1, height), hands)
        return FrameSample(
            capture_ms=capture_ms,
            inference_done_ms=self._clock.now_ms(),
            width=width,
            height=height,
            hands=hands,
            forearms_crossed=crossed,
        )

    def _crossed(self, image, ts, aspect, hands):
        from .drawing_gestures import arms_apart, crossed_forearms, crossed_hands
        try:
            if self._pose is None:
                from mediapipe.tasks.python import BaseOptions, vision
                path = project_root() / "assets/models/pose_landmarker_lite.task"
                options = vision.PoseLandmarkerOptions(
                    base_options=BaseOptions(model_asset_buffer=path.read_bytes()),
                    running_mode=vision.RunningMode.VIDEO)
                self._pose = vision.PoseLandmarker.create_from_options(options)
            poses = self._pose.detect_for_video(image, ts).pose_landmarks
            points = poses[0] if poses else ()
            return crossed_forearms(points, aspect) or crossed_hands(hands, aspect) and not arms_apart(points, aspect)
        except Exception:
            logging.getLogger(__name__).exception("Drawing arm tracking unavailable")
            self._pose_failed = True
            return None

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


def _longest_gap_ms(times: list[float], empty: list[bool]) -> float:
    """Longest zero-hand run: from the last frame that had a hand (or the run start) to the run's last frame."""
    best = 0.0
    start: Optional[float] = None
    for i, (t, e) in enumerate(zip(times, empty)):
        if e:
            if start is None:
                start = times[i - 1] if i > 0 else t
            best = max(best, t - start)
        else:
            start = None
    return best


class TrackingStats:
    """Rolling capture age, inference time and output rate (p50/p95)."""

    def __init__(self, window: int = 120) -> None:
        self._lock = threading.Lock()
        self._age: deque[float] = deque(maxlen=window)
        self._infer: deque[float] = deque(maxlen=window)
        self._done: deque[float] = deque(maxlen=window)
        self._empty: deque[bool] = deque(maxlen=window)    # True = frame had zero hands

    def record(self, sample: FrameSample, inference_ms: float) -> None:
        with self._lock:
            self._age.append(sample.inference_done_ms - sample.capture_ms)
            self._infer.append(inference_ms)
            self._done.append(sample.inference_done_ms)
            self._empty.append(len(sample.hands) == 0)

    def snapshot(self) -> dict[str, float]:
        with self._lock:
            age, infer, done = list(self._age), list(self._infer), list(self._done)
            empty = list(self._empty)
        intervals = [b - a for a, b in zip(done, done[1:]) if b > a]
        rates = [1000.0 / d for d in intervals]
        return {
            "capture_age_ms_p50": percentile(age, 0.5),
            "capture_age_ms_p95": percentile(age, 0.95),
            "inference_ms_p50": percentile(infer, 0.5),
            "inference_ms_p95": percentile(infer, 0.95),
            "output_fps": (len(done) - 1) * 1000.0 / (done[-1] - done[0])
            if len(done) > 1 and done[-1] > done[0]
            else 0.0,
            "output_fps_p50": percentile(rates, 0.5),
            "output_fps_p95": percentile(rates, 0.95),
            "samples": float(len(done)),
            "no_hand_ratio": (sum(empty) / len(empty)) if empty else 0.0,
            "no_hand_longest_ms": _longest_gap_ms(done, empty),
        }


class TrackingLoop(Worker):
    """Thread: camera.read_latest -> tracker.process -> callback(FrameSample). Newest frame only.

    While `idle()` is True and no hand was seen for `idle_after_ms`, frames that come sooner than
    `idle_interval_ms` after the last processed one are skipped (image tap only). The first frame with a
    hand restores the full rate.
    """

    thread_name = "tracking-loop"

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
        idle: Optional[Callable[[], bool]] = None,
        idle_after_ms: float = 2000.0,
        idle_interval_ms: float = 90.0,     # every third frame at 30 fps: 100 ms, under the 150 ms loss rule
    ) -> None:
        super().__init__()
        self._camera = camera
        self._tracker = tracker
        self._callback = callback
        self._clock = clock or MonotonicClock()
        self.stats = stats or TrackingStats()
        self._on_error = on_error
        self._max_errors = max_consecutive_errors
        self._poll = poll_timeout_s
        self._idle = idle
        self._idle_after = idle_after_ms
        self._idle_interval = idle_interval_ms
        self._last_hand_ms: Optional[float] = None
        self._last_processed_ms = 0.0
        self.last_error: Optional[str] = None
        # Optional image tap (frame_bgr, capture_ms), called after `callback` on the tracking thread.
        # The Enstrüman window sets it to show the camera image; it must be cheap and must not keep a lock.
        self.on_image: Optional[Callable[[Any, float], None]] = None

    def start(self) -> None:
        if not self.running:
            self.last_error = None
        super().start()

    def _fail(self, message: str) -> None:
        self.last_error = message
        if self._on_error is not None:
            try:
                self._on_error(message)
            except Exception:
                pass

    def _resting(self, capture_ms: float) -> bool:
        return (self._idle is not None and self._last_hand_ms is not None
                and capture_ms - self._last_hand_ms >= self._idle_after
                and capture_ms - self._last_processed_ms < self._idle_interval
                and self._idle())

    def _tap(self, frame: Any, capture_ms: float) -> None:
        tap = self.on_image
        if tap is not None:
            try:
                tap(frame, capture_ms)
            except Exception:
                pass

    def _run(self) -> None:
        errors = 0
        self._last_hand_ms = None
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
                if self._resting(capture_ms):
                    self._tap(frame, capture_ms)
                    continue
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
                self._last_processed_ms = capture_ms
                if sample.hands or self._last_hand_ms is None:
                    self._last_hand_ms = capture_ms
                self.stats.record(sample, sample.inference_done_ms - t0)
                try:
                    self._callback(sample)
                except Exception:
                    pass
                self._tap(frame, capture_ms)
        finally:
            self._tracker.close()
