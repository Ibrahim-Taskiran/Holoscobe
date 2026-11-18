"""Headless wiring: FrameSample -> features -> gestures -> controller -> sink. No Qt, no Win32.

    Pipeline(clock, sink, displays, windows, volume, settings)
        .process(sample)   one tracking-thread step, returns the FrameFeatures
        .tick()            ~50 ms UI timer (menu timeout, watchdog check without frames)
        .start()/.stop()   independent loss watchdog thread
        .pause()/.resume()/.emergency_stop()/.set_mode()/.reset()   safe entry points

Gesture reset protocol (the two state machines must agree on which hands are pinched):
- The controller keeps its own pinch set, fed only by PINCH_START/PINCH_END events.
  GestureRecognizer.reset() drops pinch state silently (no PINCH_END), so every recognizer
  reset is paired with a synthetic PINCH_END, delivered to the controller in the same frame,
  for each hand the recognizer had pinched. The recognizer then requires a visible release
  before that hand can pinch again; the controller requires a fresh 200 ms neutral.
- When: after every controller state change (CLAP toggle, pause, resume, fault, calibration,
  camera loss) and every mode change (menu pick or tray), and on reset()/emergency_stop().
  Detection runs in a controller listener, so changes made from any thread (hotkey, tray,
  watchdog) are seen. The reset itself is applied at the start of the next process() call on
  the tracking thread, before the recognizer sees that frame. The recognizer keeps its 900 ms
  clap cooldown across resets, so a reset after CLAP cannot cause a double toggle.
- Not on soft resets (clap candidate start, hand loss, watchdog): the recognizer already ends
  pinches itself there and a reset would kill the running clap candidate.

Settings mapping notes:
- config.CalibrationBounds is in the UNMIRRORED camera frame; mapping.CalibrationRect is in the
  mirrored view when mirror is on. Pipeline converts (left/right swapped and flipped).
- mirror_preview drives the pointer mapping mirror (spec: mirror only display/mapping).
- sensitivity s: scroll/zoom step size / s, volume gain * s.
- pointer_mode "relative" (default): the cursor follows the palm anchor with acceleration and a
  clutch; calibration only matters for "absolute". pointer_speed scales the relative gain.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Optional

from handcontrol.config import Settings
from handcontrol.contracts import (
    ActionSink,
    CameraState,
    Clock,
    ControlState,
    DisplayProvider,
    FrameFeatures,
    FrameSample,
    GestureEvent,
    GestureKind,
    Handedness,
    Mode,
    ProcessNames,
    VolumeControl,
    WindowQuery,
)
from handcontrol.controller import Controller, ControllerConfig, ControllerSnapshot
from handcontrol.features import FeatureConfig, FeatureExtractor
from handcontrol.filters import OneEuroFilter2D
from handcontrol.gestures import GestureConfig, GestureRecognizer
from handcontrol.mapping import CalibrationRect, bounding_rect


class OneEuroPointerSmoother:
    """Adapter: filters.OneEuroFilter2D -> controller.PointSmoother.

    The controller smooths normalized (u, v). One Euro beta is unit dependent and its defaults
    suit pixels, so values are scaled to `scale_px` (desktop width) before filtering.
    """

    def __init__(self, scale_px: float = 1920.0, min_cutoff: float = 1.0, beta: float = 0.007,
                 d_cutoff: float = 1.0, max_gap_ms: float = 200.0) -> None:
        self.scale_px = scale_px if scale_px > 0 else 1920.0
        self._f = OneEuroFilter2D(min_cutoff, beta, d_cutoff, max_gap_ms)

    def reset(self) -> None:
        self._f.reset()

    def filter(self, t_ms: float, x: float, y: float) -> tuple[float, float]:
        s = self.scale_px
        fx, fy = self._f.filter((x * s, y * s), t_ms)
        return fx / s, fy / s


# ---------------------------------------------------------------- settings mapping


def dominant_of(settings: Settings) -> Handedness:
    return Handedness.LEFT if settings.dominant_hand == "left" else Handedness.RIGHT


def calibration_rect(settings: Settings) -> CalibrationRect:
    """config.CalibrationBounds (unmirrored) -> mapping.CalibrationRect (mirrored view if mirror)."""
    b = settings.calibration
    if settings.mirror_preview:
        return CalibrationRect(1.0 - b.right, b.top, 1.0 - b.left, b.bottom)
    return CalibrationRect(b.left, b.top, b.right, b.bottom)


def feature_config(settings: Settings) -> FeatureConfig:
    return FeatureConfig()          # no user-facing feature settings yet


def gesture_config(settings: Settings) -> GestureConfig:
    return GestureConfig(pinch_on_pu=settings.pinch_on_threshold, pinch_off_pu=settings.pinch_off_threshold)


def controller_config(settings: Settings) -> ControllerConfig:
    base = ControllerConfig()
    s = settings.sensitivity if settings.sensitivity > 0 else 1.0
    mm = settings.monitor_mapping
    return ControllerConfig(
        dominant=dominant_of(settings),
        mirror=settings.mirror_preview,
        calibration=calibration_rect(settings),
        scroll_invert=settings.scroll_direction == "reversed",
        zoom_invert=settings.zoom_direction == "reversed",
        scroll_step_norm=base.scroll_step_norm / s,
        zoom_step_palm=base.zoom_step_palm / s,
        volume_gain=base.volume_gain * s,
        monitor_mode=mm.mode,
        monitor_index=mm.monitor_index,
        pointer_relative=settings.pointer_mode != "absolute",
        pointer_speed=settings.pointer_speed,
        # thumb+middle uses the same pinch thresholds as thumb+index
        right_pinch_on_pu=settings.pinch_on_threshold,
        right_pinch_off_pu=settings.pinch_off_threshold,
    )


# ---------------------------------------------------------------- pipeline


class Pipeline:
    def __init__(
        self,
        clock: Clock,
        sink: ActionSink,
        displays: DisplayProvider,
        windows: WindowQuery,
        volume: VolumeControl,
        settings: Optional[Settings] = None,
        *,
        smoother: Optional[Any] = None,
        cursor_source: Optional[Callable[[], Optional[tuple[int, int]]]] = None,
        process_names: Optional[ProcessNames] = None,
    ) -> None:
        """cursor_source: optional reader of the real OS cursor (physical px), used by the relative
        pointer to start and re-engage from where the cursor really is.
        process_names: optional foreground process lookup for the COMMANDS mode "auto" profile."""
        self.settings = settings if settings is not None else Settings()
        self._clock = clock
        self._lock = threading.RLock()          # serializes process()/reset() (tracking thread)
        self._flag_lock = threading.Lock()
        self.features = FeatureExtractor(feature_config(self.settings))
        self.gestures = GestureRecognizer(gesture_config(self.settings), dominant_of(self.settings))
        if smoother is None:
            box = None
            try:
                box = bounding_rect(tuple(displays.monitors()))
            except Exception:
                pass
            smoother = OneEuroPointerSmoother(float(box.right - box.left) if box else 1920.0)
        # Controller wraps `sink` in safety.GuardedSink itself: do not wrap it here.
        self.controller = Controller(clock, sink, displays, windows, volume, controller_config(self.settings),
                                     smoother=smoother, cursor_source=cursor_source,
                                     process_names=process_names)
        self.last_features: Optional[FrameFeatures] = None
        self.last_events: tuple[GestureEvent, ...] = ()
        self.gesture_resets = 0
        self._frame_observers: list[Callable[[FrameFeatures, tuple[GestureEvent, ...], ControllerSnapshot], None]] = []
        self._reset_pending = False
        self._full_reset_pending = False
        snap = self.controller.snapshot()
        self._seen = (snap.state, snap.mode)
        self.controller.add_listener(self._on_snapshot)
        try:
            default_mode = Mode(self.settings.default_mode)
        except ValueError:
            default_mode = Mode.POINTER
        if default_mode is not Mode.POINTER:
            self.controller.set_mode(default_mode)

    # ------------------------------------------------------------ frame path (tracking thread)

    def process(self, sample: FrameSample) -> FrameFeatures:
        with self._lock:
            pre = self._take_pending_reset()
            ff = self.features.update(sample)
            events = pre + self.gestures.update(ff)
            self.last_features = ff
            self.last_events = tuple(events)
            self.controller.on_frame(ff, events)
            if self._frame_observers:
                self._notify_observers(ff, self.last_events)
            return ff

    def add_frame_observer(self, observer: Callable[[FrameFeatures, tuple[GestureEvent, ...], ControllerSnapshot], None]) -> None:
        """Optional hook called after the controller handled each frame (tracking thread).
        Observer exceptions are swallowed."""
        self._frame_observers.append(observer)

    def _notify_observers(self, ff: FrameFeatures, events: tuple[GestureEvent, ...]) -> None:
        try:
            snap = self.controller.snapshot()
        except Exception:
            return
        for observer in tuple(self._frame_observers):
            try:
                observer(ff, events, snap)
            except Exception:
                pass

    def tick(self) -> None:
        self.controller.tick()

    # ------------------------------------------------------------ lifecycle / commands (any thread)

    def start(self) -> None:
        self.controller.start_watchdog()

    def stop(self) -> None:
        self.controller.stop_watchdog()

    def request_gesture_reset(self, full: bool = False) -> None:
        """Ask for a recognizer reset (full=True also forgets feature tracks) before the next frame."""
        with self._flag_lock:
            self._reset_pending = True
            self._full_reset_pending = self._full_reset_pending or full

    def pause(self, reason: str = "") -> None:
        self.controller.pause(reason)
        self.request_gesture_reset()

    def resume(self) -> bool:
        ok = self.controller.resume()
        self.request_gesture_reset()
        return ok

    def emergency_stop(self) -> None:
        self.controller.emergency_stop()
        self.request_gesture_reset()

    def set_mode(self, mode: Mode) -> None:
        self.controller.set_mode(mode)
        self.request_gesture_reset()

    def set_camera_state(self, state: CameraState) -> None:
        self.controller.set_camera_state(state)
        if state is not CameraState.RUNNING:
            self.request_gesture_reset(full=True)

    def reset(self, reason: str = "Sıfırlandı") -> None:
        """Pause-class reset of the whole chain: controller paused (RELEASE_ALL, new epoch),
        recognizer and feature tracks cleared before the next frame."""
        self.controller.pause(reason)
        self.request_gesture_reset(full=True)

    # ------------------------------------------------------------ internals

    def _on_snapshot(self, snap: ControllerSnapshot) -> None:
        key = (snap.state, snap.mode)
        with self._flag_lock:
            if key != self._seen:
                self._seen = key
                self._reset_pending = True

    def _take_pending_reset(self) -> list[GestureEvent]:
        with self._flag_lock:
            pending, full = self._reset_pending, self._full_reset_pending
            self._reset_pending = self._full_reset_pending = False
        if not pending:
            return []
        prev = self.last_features
        t = prev.capture_ms if prev is not None else 0.0
        ends = [GestureEvent(GestureKind.PINCH_END, t, h.hand_id)
                for h in (prev.hands if prev is not None else ()) if self.gestures.is_pinched(h.hand_id)]
        self.gestures.reset()
        if full:
            self.features.reset()
        self.gesture_resets += 1
        return ends


# ---------------------------------------------------------------- camera wiring


class _MonotonicClock:
    def now_ms(self) -> float:
        return time.monotonic() * 1000.0


class CameraPipeline:
    """camera.Camera + tracking.TrackingLoop feeding Pipeline.process on the tracking thread."""

    def __init__(self, pipeline: Pipeline, camera: Any, loop: Any) -> None:
        self.pipeline = pipeline
        self.camera = camera
        self.loop = loop
        self._stopped = False

    def start(self) -> None:
        self._stopped = False
        self.pipeline.start()
        self.camera.start()
        self.loop.start()

    def stop(self) -> None:
        """Stop producing first, then the device, then pause the controller (RELEASE_ALL)."""
        if self._stopped:
            return
        self._stopped = True
        try:
            self.loop.stop()
        finally:
            try:
                self.camera.stop()
            finally:
                self.pipeline.set_camera_state(CameraState.OFF)
                self.pipeline.stop()

    @property
    def running(self) -> bool:
        return bool(self.loop.running)


def run_camera_pipeline(
    pipeline: Pipeline,
    *,
    clock: Optional[Clock] = None,
    camera: Any = None,
    tracker: Any = None,
    capture_factory: Optional[Callable[..., Any]] = None,
    swap_handedness: bool = False,
    on_error: Optional[Callable[[str], None]] = None,
    start: bool = True,
) -> CameraPipeline:
    """Build (and by default start) camera -> tracker -> pipeline.

    `clock` must be the same monotonic clock the pipeline/controller use, because capture_ms is
    compared with controller time for the 150 ms stale rule. Camera state changes go to the
    controller; a fatal tracking error is reported as CameraState.ERROR (controller -> Fault).
    """
    from handcontrol.camera import Camera, CameraConfig
    from handcontrol.tracking import HandTracker, TrackingLoop

    clk = clock if clock is not None else _MonotonicClock()

    def on_state(state: CameraState, message: Optional[str]) -> None:
        pipeline.set_camera_state(state)
        if message and on_error is not None:
            try:
                on_error(message)
            except Exception:
                pass

    if camera is None:
        cs = pipeline.settings.camera
        cfg = CameraConfig(index=cs.index, backend=cs.backend, width=cs.width, height=cs.height, fps=cs.fps)
        kwargs: dict[str, Any] = {"clock": clk, "on_state_change": on_state}
        if capture_factory is not None:
            kwargs["capture_factory"] = capture_factory
        camera = Camera(cfg, **kwargs)
    if tracker is None:
        tracker = HandTracker(clock=clk, swap_handedness=swap_handedness)

    def on_loop_error(message: str) -> None:
        pipeline.set_camera_state(CameraState.ERROR)
        if on_error is not None:
            try:
                on_error(message)
            except Exception:
                pass

    loop = TrackingLoop(camera, tracker, pipeline.process, clock=clk, on_error=on_loop_error)
    handle = CameraPipeline(pipeline, camera, loop)
    if start:
        handle.start()
    return handle


__all__ = [
    "CameraPipeline",
    "OneEuroPointerSmoother",
    "Pipeline",
    "calibration_rect",
    "controller_config",
    "dominant_of",
    "feature_config",
    "gesture_config",
    "run_camera_pipeline",
]
