"""Control state machine and action arbitration (spec §5 control model, failure behavior, §6).

Inputs: FrameFeatures + GestureEvents (contracts). OS access only through contract Protocols.
Every action goes through safety.GuardedSink (epoch + 150 ms staleness). An independent
safety.Watchdog releases owned input 200 ms after the last usable capture.

Imports: stdlib, contracts and this team's own stdlib-only modules (mapping, safety).
User-visible texts are Turkish.
"""
from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional, Protocol, Sequence

from handcontrol.contracts import (
    Action,
    ActionKind,
    ActionSink,
    CameraState,
    Clock,
    ControlState,
    DisplayProvider,
    FingerName,
    FingerState,
    FrameFeatures,
    GestureEvent,
    GestureKind,
    HandFeatures,
    Handedness,
    Mode,
    Monitor,
    Quality,
    VolumeControl,
    WindowQuery,
    WindowTarget,
)
from handcontrol.mapping import (CalibrationRect, map_normalized, normalize_camera_point, project_to_monitors,
                                 threshold_physical_px)
from handcontrol.safety import GuardedSink, Watchdog
from handcontrol.index_tap import IndexTapRecognizer
from handcontrol.middle_pinch import CANCEL as MID_CANCEL, END as MID_END, START as MID_START, MiddlePinchRecognizer


# ---------------------------------------------------------------- config / snapshot


@dataclass(frozen=True)
class ControllerConfig:
    dominant: Handedness = Handedness.RIGHT
    mirror: bool = True
    calibration: CalibrationRect = CalibrationRect(0.15, 0.15, 0.85, 0.85)
    # safety
    stale_ms: float = 150.0
    loss_timeout_ms: float = 200.0
    neutral_ms: float = 200.0
    # timings
    click_max_ms: float = 450.0
    click_max_move_logical_px: float = 15.0
    zoom_pair_window_ms: float = 300.0
    drag_hold_ms: float = 250.0
    close_hold_ms: float = 1000.0
    menu_timeout_ms: float = 5000.0
    # rate limits
    scroll_steps_per_s: float = 12.0
    zoom_steps_per_s: float = 12.0
    volume_updates_per_s: float = 10.0
    drag_moves_per_s: float = 30.0
    # scroll: displacement in normalized frame height
    scroll_step_norm: float = 0.04
    scroll_dead_zone_norm: float = 0.02
    scroll_max_pending: int = 3
    scroll_invert: bool = False
    # zoom: change of hand distance in palm units
    zoom_step_palm: float = 0.35
    zoom_dead_zone_palm: float = 0.25
    zoom_max_pending: int = 3
    zoom_invert: bool = False
    # volume: level change per normalized frame height
    volume_gain: float = 2.0
    volume_dead_zone_norm: float = 0.01
    volume_min_delta: float = 0.005
    # menus: virtual pointer gain relative to hand motion (normalized)
    menu_gain: float = 2.0
    # default pointer smoother time constant
    pointer_tau_ms: float = 35.0
    # pointer mapping target (config.MonitorMapping): "virtual_desktop" | "primary" | "monitor"
    monitor_mode: str = "virtual_desktop"
    monitor_index: int = 0
    camera_error_paused: bool = False
    # POINTER click source. index_tap_click (z-depth index tap, noisy on real cameras) wins when on and
    # disables pinch clicks. Otherwise pinch_mouse: thumb+index tap = left click, hold = left-button
    # drag, thumb+middle tap = right click. pinch_mouse=False keeps the legacy pinch-release click.
    index_tap_click: bool = False
    pinch_mouse: bool = True
    mouse_hold_ms: float = 350.0            # thumb+index pinch held this long -> LEFT_DOWN (drag)
    double_click_window_ms: float = 500.0   # a tap starting this soon after a click reuses its point
    mouse_drag_move_palm: float = 0.35      # palm travel (palm units) that turns a tap into a drag
    pinch_latch_open_pu: float = 0.5        # latch the pointer of the last frame the hand was this open
    pinch_latch_lookback_ms: float = 250.0  # ... if that frame is at most this old at pinch start
    right_pinch_on_pu: float = 0.28         # thumb+middle hysteresis (palm units), same as thumb+index
    right_pinch_off_pu: float = 0.42
    right_pinch_debounce_ms: float = 70.0


class MenuKind(Enum):
    MODE = "mode"
    WINDOW = "window"


@dataclass(frozen=True)
class MenuItem:
    key: str              # mode value ("pointer", ...) or "minimize"/"maximize"/"other_monitor"/"close"
    label: str            # Turkish
    enabled: bool = True
    selected: bool = False


@dataclass(frozen=True)
class MenuSnapshot:
    """Layout rule for renderers: items are a vertical list; item i covers pointer y in
    [i/n, (i+1)/n). `pointer` is the virtual pointer in [0,1]^2 of the menu panel."""

    kind: MenuKind
    items: tuple[MenuItem, ...]
    hovered: Optional[int]
    pointer: tuple[float, float]
    hold_progress: float          # 0..1 of the close confirmation hold
    close_armed: bool
    target: Optional[WindowTarget]
    remaining_ms: float           # until the 5 s inactivity timeout


@dataclass(frozen=True)
class ControllerSnapshot:
    state: ControlState
    camera_state: CameraState
    mode: Mode
    epoch: int
    menu: Optional[MenuSnapshot]
    pending_action: str           # Turkish text of the engagement in progress, "" if none
    reason: str                   # Turkish reason of the last state change
    last_fault_reason: str
    notice: str                   # last Turkish hint (e.g. "focus the window first")
    needs_neutral: bool
    clap_pending: bool
    pointer: Optional[tuple[int, int]]
    dropped_actions: int
    t_ms: float


# ---------------------------------------------------------------- smoothing / rate


class PointSmoother(Protocol):
    """Injectable pointer filter working on normalized (u, v). The shared One Euro filter
    can be adapted to this."""

    def reset(self) -> None: ...
    def filter(self, t_ms: float, x: float, y: float) -> tuple[float, float]: ...


class ExpSmoother:
    """Time-aware exponential smoother; resets itself after a gap."""

    def __init__(self, tau_ms: float = 35.0, reset_gap_ms: float = 150.0) -> None:
        self.tau_ms = tau_ms
        self.reset_gap_ms = reset_gap_ms
        self._t: Optional[float] = None
        self._x = 0.0
        self._y = 0.0

    def reset(self) -> None:
        self._t = None

    def filter(self, t_ms: float, x: float, y: float) -> tuple[float, float]:
        if self._t is None or t_ms < self._t or t_ms - self._t > self.reset_gap_ms:
            self._t, self._x, self._y = t_ms, x, y
            return x, y
        dt = t_ms - self._t
        a = 1.0 if self.tau_ms <= 0 else 1.0 - math.exp(-dt / self.tau_ms)
        self._x += a * (x - self._x)
        self._y += a * (y - self._y)
        self._t = t_ms
        return self._x, self._y


class _Rate:
    """Token bucket. burst=1 means at most 1 + T*rate events in any T window (plus a 5% frame
    jitter tolerance; the long-run rate never exceeds `per_s`)."""

    def __init__(self, per_s: float, burst: float = 1.0) -> None:
        self._per_ms = per_s / 1000.0
        self._burst = burst
        self._tokens = burst
        self._t: Optional[float] = None

    def available(self, now: float) -> int:
        if self._t is not None and now > self._t:
            self._tokens = min(self._burst, self._tokens + (now - self._t) * self._per_ms)
        if self._t is None or now > self._t:
            self._t = now
        return int(self._tokens + 0.05)

    def take(self, n: int) -> None:
        self._tokens -= n


# ---------------------------------------------------------------- internal state


class _EngKind(Enum):
    CLICK = "click"
    SCROLL = "scroll"
    ZOOM_WAIT = "zoom_wait"
    ZOOM = "zoom"
    VOLUME = "volume"
    WIN_PINCH = "win_pinch"
    DRAG = "drag"
    MOUSE_TAP = "mouse_tap"      # thumb+index pinch: tap candidate (pointer held at the latch)
    MOUSE_DRAG = "mouse_drag"    # left button held, pointer follows the hand
    RIGHT_TAP = "right_tap"      # thumb+middle pinch: right click candidate
    BLOCKED = "blocked"      # cancelled or refused; waits for the pinch release


_MOUSE_KINDS = (_EngKind.MOUSE_TAP, _EngKind.MOUSE_DRAG, _EngKind.RIGHT_TAP)

_ENG_TEXT = {
    _EngKind.MOUSE_TAP: "Tıklama bekleniyor",
    _EngKind.MOUSE_DRAG: "Sürükleniyor (sol tuş basılı)",
    _EngKind.RIGHT_TAP: "Sağ tık bekleniyor",
    _EngKind.CLICK: "Tıklama bekleniyor",
    _EngKind.SCROLL: "Kaydırma",
    _EngKind.ZOOM_WAIT: "Yakınlaştırma: ikinci el bekleniyor",
    _EngKind.ZOOM: "Yakınlaştırma",
    _EngKind.VOLUME: "Ses ayarı",
    _EngKind.WIN_PINCH: "Pencere seçiliyor",
    _EngKind.DRAG: "Pencere taşınıyor",
    _EngKind.BLOCKED: "Bırakmanız bekleniyor",
}


@dataclass
class _Eng:
    kind: _EngKind
    hand_id: int
    t0: float
    other_hand: Optional[int] = None
    latched: Optional[tuple[int, int]] = None
    raw_start: Optional[tuple[int, int]] = None
    moved: bool = False
    target: Optional[WindowTarget] = None
    base: float = 0.0
    base_level: float = 0.0
    emitted: int = 0
    rate: Optional[_Rate] = None
    dispatched: int = 0
    last_value: Optional[float] = None
    last_pos: Optional[tuple[int, int]] = None
    palm0: Optional[tuple[float, float]] = None   # palm center (camera px) at pinch start
    pos0: Optional[tuple[int, int]] = None        # mapped fingertip at pinch start (drag reference)
    middle: bool = False                          # thumb+middle engagement (BLOCKED waits for its release)

    def hands(self) -> tuple[int, ...]:
        return (self.hand_id,) if self.other_hand is None else (self.hand_id, self.other_hand)


@dataclass
class _Menu:
    kind: MenuKind
    items: list[MenuItem]
    target: Optional[WindowTarget]
    opened_ms: float
    last_interaction_ms: float
    armed: bool
    anchor: Optional[tuple[float, float]] = None
    pointer: tuple[float, float] = (0.5, 0.5)
    hovered: Optional[int] = None
    close_armed: bool = False
    confirm_needs_release: bool = False
    hold_t0: Optional[float] = None
    hold_now: float = 0.0


_MODE_LABELS = {
    Mode.POINTER: "İşaretçi",
    Mode.SCROLL: "Kaydırma",
    Mode.ZOOM: "Yakınlaştırma",
    Mode.VOLUME: "Ses",
    Mode.WINDOWS: "Pencereler",
}
_WINDOW_ACTIONS = {
    "minimize": ActionKind.WINDOW_MINIMIZE,
    "maximize": ActionKind.WINDOW_TOGGLE_MAXIMIZE,
    "other_monitor": ActionKind.WINDOW_MOVE_TO_OTHER_MONITOR,
}
CLOSE_LABEL = "Kapat"
CLOSE_CONFIRM_LABEL = "Kapatmayı onayla (1 sn basılı tut)"


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def _steps(d: float, dead: float, step: float) -> int:
    if abs(d) <= dead or step <= 0:
        return 0
    n = int((abs(d) - dead) / step)
    return n if d > 0 else -n


def _index_extended(h: HandFeatures) -> bool:
    for f in h.fingers:
        if f.name is FingerName.INDEX:
            return f.state is FingerState.EXTENDED
    return False


def _right_pose(h: HandFeatures, strict: bool) -> bool:
    """Thumb+middle right-click pose: index extended and ring or little not curled. The pointing
    pose (thumb tucked over the curled middle finger, ring and little curled) also brings the thumb
    tip near the middle tip and must never right click. strict (at pinch start): index EXTENDED and
    ring or little EXTENDED; otherwise (while held) only a clearly BENT index or ring+little cancel."""
    s = {f.name: f.state for f in h.fingers}
    if strict:
        return s.get(FingerName.INDEX) is FingerState.EXTENDED and FingerState.EXTENDED in (
            s.get(FingerName.RING), s.get(FingerName.LITTLE))
    return s.get(FingerName.INDEX) is not FingerState.BENT and not (
        s.get(FingerName.RING) is FingerState.BENT and s.get(FingerName.LITTLE) is FingerState.BENT)


# ---------------------------------------------------------------- controller


class Controller:
    def __init__(
        self,
        clock: Clock,
        sink: ActionSink,
        displays: DisplayProvider,
        windows: WindowQuery,
        volume: VolumeControl,
        config: ControllerConfig = ControllerConfig(),
        smoother: Optional[PointSmoother] = None,
    ) -> None:
        self._lock = threading.RLock()
        self._cfg = config
        self._clock = clock
        self._displays = displays
        self._windows = windows
        self._volume = volume
        self._epoch = 0
        self._guard = GuardedSink(sink, clock, self.current_epoch, config.stale_ms)
        self._smoother: PointSmoother = smoother if smoother is not None else ExpSmoother(config.pointer_tau_ms)
        self.watchdog = Watchdog(clock, self._on_watchdog_timeout, config.loss_timeout_ms)
        self._listeners: list[Callable[[ControllerSnapshot], None]] = []

        self._state = ControlState.PAUSED
        self._camera = CameraState.OFF
        self._mode = Mode.POINTER
        self._calib = config.calibration
        self._monitors: tuple[Monitor, ...] = self._read_monitors()

        self._eng: Optional[_Eng] = None
        self._menu: Optional[_Menu] = None
        self._pinched: dict[int, float] = {}
        self._need_neutral = True
        self._neutral_since: Optional[float] = None
        self._clap_pending = False
        self._zoom_needs_release = False
        self._pointer: Optional[tuple[int, int]] = None
        self._dirty = False
        self._reason = "Başlangıç: duraklatıldı"
        self._fault_reason = ""
        self._fault_from_camera = False
        self._notice = ""
        self._in_call = 0
        self._fist_open: dict[int, float] = {}
        self._fist_ready: set[int] = set()
        self._fist_candidate: Optional[tuple[int, Handedness, float, Optional[WindowTarget]]] = None
        self._minimized_history: list[WindowTarget] = []
        self._index_tap = IndexTapRecognizer()
        self._middle = MiddlePinchRecognizer(config.right_pinch_on_pu, config.right_pinch_off_pu,
                                             config.right_pinch_debounce_ms)
        # (release ms, point, palm center px) of the last pinch left click
        self._last_tap: Optional[tuple[float, tuple[int, int], tuple[float, float]]] = None
        # "index" / "middle": (capture ms, pointer) of the last frame that pinch was open
        self._open_ptr: dict[str, tuple[float, tuple[int, int]]] = {}

    # ------------------------------------------------------------ public API

    def current_epoch(self) -> int:
        return self._epoch

    @property
    def guard(self) -> GuardedSink:
        return self._guard

    @property
    def config(self) -> ControllerConfig:
        return self._cfg

    def on_frame(self, frame: FrameFeatures, events: Sequence[GestureEvent]) -> None:
        with self._lock:
            self._in_call += 1
            try:
                self._frame(frame, tuple(events))
            except Exception as exc:  # never let a bug keep input owned
                self._enter_fault(f"Denetleyici hatası: {type(exc).__name__}: {exc}")
            finally:
                self._in_call -= 1
        self._notify()

    def tick(self) -> None:
        """Time-based expiry without a frame (menu timeout, watchdog). Safe to call from a UI timer."""
        with self._lock:
            self._in_call += 1
            try:
                now = self._clock.now_ms()
                self.watchdog.check(now)
                if self._state is ControlState.ACTIVE:
                    self._expire_menu(now)
            finally:
                self._in_call -= 1
        self._notify()

    def pause(self, reason: str = "") -> None:
        with self._lock:
            self._do_pause(reason or "Duraklatıldı")
        self._notify()

    def resume(self) -> bool:
        with self._lock:
            ok = self._state is ControlState.PAUSED and self._camera is CameraState.RUNNING
            if ok:
                self._activate("Etkinleştirildi")
            else:
                self._notice = "Etkinleştirilemedi: kamera çalışmıyor" if self._camera is not CameraState.RUNNING \
                    else "Etkinleştirilemedi"
        self._notify()
        return ok

    def emergency_stop(self) -> None:
        with self._lock:
            if self._state is not ControlState.FAULT:
                self._state = ControlState.PAUSED
            self._hard_reset("Acil durdurma")
        self._notify()

    def set_mode(self, mode: Mode) -> None:
        with self._lock:
            self._set_mode(mode)
        self._notify()

    def set_camera_state(self, state: CameraState) -> None:
        with self._lock:
            prev, self._camera = self._camera, state
            if state is not prev:
                if state is CameraState.ERROR:
                    if self._cfg.camera_error_paused:
                        self._state = ControlState.PAUSED
                        self._hard_reset("Kamera hatası: duraklatıldı")
                    elif self._state is not ControlState.FAULT:
                        self._enter_fault("Kamera hatası", camera=True)
                elif state is CameraState.RUNNING:
                    if self._state is ControlState.FAULT and self._fault_from_camera:
                        self._state = ControlState.PAUSED
                        self._fault_from_camera = False
                        self._hard_reset("Kamera yeniden hazır: duraklatıldı")
                else:  # OFF / STARTING
                    if self._state is ControlState.FAULT and self._fault_from_camera:
                        self._state = ControlState.PAUSED
                        self._fault_from_camera = False
                        self._hard_reset("Kamera kapalı")
                    elif self._state in (ControlState.ACTIVE, ControlState.CALIBRATING):
                        self._state = ControlState.PAUSED
                        self._hard_reset("Kamera kapalı")
        self._notify()

    def begin_calibration(self) -> bool:
        with self._lock:
            ok = self._state is not ControlState.FAULT and self._camera is CameraState.RUNNING
            if ok:
                self._state = ControlState.CALIBRATING
                self._hard_reset("Kalibrasyon")
        self._notify()
        return ok

    def end_calibration(self, calibration: Optional[CalibrationRect] = None) -> None:
        with self._lock:
            if self._state is ControlState.CALIBRATING:
                if calibration is not None:
                    self._calib = calibration
                self._state = ControlState.PAUSED
                self._hard_reset("Kalibrasyon bitti: duraklatıldı")
        self._notify()

    def set_calibration(self, calibration: CalibrationRect) -> None:
        with self._lock:
            self._calib = calibration
            self._hard_reset("Kalibrasyon güncellendi")
        self._notify()

    def clear_fault(self) -> None:
        """Acknowledge a non-camera fault; lands in Paused (never auto-activates)."""
        with self._lock:
            if self._state is ControlState.FAULT and not (
                self._fault_from_camera and self._camera is CameraState.ERROR
            ):
                self._state = ControlState.PAUSED
                self._fault_from_camera = False
                self._hard_reset("Hata onaylandı: duraklatıldı")
        self._notify()

    def on_session_lock(self) -> None:
        self.pause("Oturum kilitlendi")

    def on_suspend(self) -> None:
        self.pause("Sistem uykuya geçiyor")

    def on_display_change(self) -> None:
        with self._lock:
            self._monitors = self._read_monitors()
            self._hard_reset("Ekran düzeni değişti")
        self._notify()

    def start_watchdog(self) -> None:
        self.watchdog.start()

    def stop_watchdog(self) -> None:
        self.watchdog.stop()

    def add_listener(self, callback: Callable[[ControllerSnapshot], None]) -> None:
        """Called after every change, from the frame thread or the watchdog thread. Must not
        block; UI code should marshal to its own thread."""
        with self._lock:
            self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[ControllerSnapshot], None]) -> None:
        with self._lock:
            if callback in self._listeners:
                self._listeners.remove(callback)

    def snapshot(self) -> ControllerSnapshot:
        with self._lock:
            now = self._clock.now_ms()
            return ControllerSnapshot(
                state=self._state,
                camera_state=self._camera,
                mode=self._mode,
                epoch=self._epoch,
                menu=self._menu_snapshot(now),
                pending_action=self._pending_text(now),
                reason=self._reason,
                last_fault_reason=self._fault_reason,
                notice=self._notice,
                needs_neutral=self._need_neutral,
                clap_pending=self._clap_pending,
                pointer=self._pointer,
                dropped_actions=self._guard.dropped_total,
                t_ms=now,
            )

    # ------------------------------------------------------------ state transitions

    def _read_monitors(self) -> tuple[Monitor, ...]:
        try:
            return tuple(self._displays.monitors())
        except Exception:
            return ()

    def _mapping_monitors(self) -> tuple[Monitor, ...]:
        """Monitors the pointer maps onto (settings monitor_mapping); all monitors as fallback."""
        mons, mode = self._monitors, self._cfg.monitor_mode
        if mode == "primary":
            sel = tuple(m for m in mons if m.is_primary)[:1]
        elif mode == "monitor":
            sel = mons[self._cfg.monitor_index:self._cfg.monitor_index + 1]
        else:
            sel = mons
        return sel or mons

    def _bump(self) -> None:
        self._epoch += 1

    def _release(self) -> None:
        self._guard.dispatch(Action(ActionKind.RELEASE_ALL, self._epoch, self._clock.now_ms()))
        self._dirty = False

    def _clear_transient(self) -> None:
        self._index_tap.reset()
        self._reset_mouse_memory()
        self._reset_fists()
        self._eng = None   # a held left button is released by the caller's RELEASE_ALL
        self._menu = None
        self._need_neutral = True
        self._neutral_since = None
        self._clap_pending = False
        self._smoother.reset()

    def _hard_reset(self, reason: str) -> None:
        """Pause-class reset: new epoch, drop everything, always RELEASE_ALL."""
        self._bump()
        self._clear_transient()
        self._reason = reason
        self._release()
        self.watchdog.disarm()

    def _do_pause(self, reason: str) -> None:
        if self._state is not ControlState.FAULT:
            self._state = ControlState.PAUSED
        self._hard_reset(reason)

    def _activate(self, reason: str) -> None:
        self._bump()
        self._clear_transient()
        self._state = ControlState.ACTIVE
        self._reason = reason
        self._notice = ""

    def _enter_fault(self, reason: str, camera: bool = False) -> None:
        self._state = ControlState.FAULT
        self._fault_reason = reason
        self._fault_from_camera = camera
        self._hard_reset(reason)

    def _set_mode(self, mode: Mode) -> None:
        if mode is self._mode:
            self._menu = None
            return
        self._mode = mode
        self._bump()
        self._cancel_engagement(release=True)
        self._menu = None
        self._need_neutral = True
        self._neutral_since = None
        self._smoother.reset()
        self._reason = f"Kip: {_MODE_LABELS[mode]}"

    def _cancel_engagement(self, release: bool) -> None:
        e, self._eng = self._eng, None
        if e is not None and e.kind is _EngKind.MOUSE_DRAG:
            self._left_up(e, self._clock.now_ms())   # the left button never stays held
        if e is not None and release and e.dispatched > 0:
            self._release()

    def _reset_mouse_memory(self) -> None:
        self._middle.reset()
        self._last_tap = None
        self._open_ptr.clear()

    def _soft_reset(self, cancel_menu_hold: bool = True) -> None:
        """Loss / clap-candidate reset: freeze, drop engagement, need fresh neutral."""
        self._index_tap.reset()
        self._reset_mouse_memory()
        had = self._eng is not None
        self._cancel_engagement(release=True)
        if cancel_menu_hold and self._menu is not None:
            self._cancel_confirmation(self._menu)
        self._need_neutral = True
        self._neutral_since = None
        self._smoother.reset()
        if had:
            self._bump()

    def _on_watchdog_timeout(self) -> None:
        with self._lock:
            self._reset_fists()
            nested = self._in_call > 0  # on_frame/tick notify on their own
            if self._state is ControlState.ACTIVE:
                self._soft_reset()
                self._bump()
                if self._dirty:
                    self._release()
                self._notice = "İz kaybedildi: girdiler bırakıldı"
        if not nested:
            self._notify()

    def _notify(self) -> None:
        with self._lock:
            listeners = list(self._listeners)
        if not listeners:
            return
        snap = self.snapshot()
        for cb in listeners:
            try:
                cb(snap)
            except Exception:
                pass

    # ------------------------------------------------------------ dispatch helpers

    def _dispatch(self, kind: ActionKind, capture_ms: float, *, x: Optional[int] = None, y: Optional[int] = None,
                  steps: int = 0, value: float = 0.0, target: Optional[WindowTarget] = None) -> bool:
        ok = self._guard.dispatch(Action(kind, self._epoch, capture_ms, x=x, y=y, steps=steps, value=value,
                                         target=target))
        if ok:
            if kind is ActionKind.WINDOW_MINIMIZE and target is not None:
                self._minimized_history = [t for t in self._minimized_history if t != target]
                self._minimized_history.append(target)
                self._minimized_history = self._minimized_history[-32:]
            elif kind is ActionKind.WINDOW_RESTORE and target is not None:
                self._minimized_history = [t for t in self._minimized_history if t != target]
            self._dirty = True
            if self._eng is not None:
                self._eng.dispatched += 1
        return ok

    def _target_ok(self, target: Optional[WindowTarget], pos: Optional[tuple[int, int]]) -> bool:
        if target is None or pos is None:
            return False
        try:
            return (self._windows.is_valid(target)
                    and self._windows.foreground_window() == target
                    and self._windows.eligible_window_at(pos[0], pos[1]) == target)
        except Exception:
            return False

    def _valid(self, target: Optional[WindowTarget]) -> bool:
        if target is None:
            return False
        try:
            return bool(self._windows.is_valid(target))
        except Exception:
            return False

    # ------------------------------------------------------------ frame processing

    def _dominant(self, hands: Sequence[HandFeatures]) -> Optional[HandFeatures]:
        # The OS pointer and its click gestures always belong to the right hand.
        doms = [h for h in hands if h.handedness is Handedness.RIGHT]
        return doms[0] if len(doms) == 1 else None

    def _frame(self, frame: FrameFeatures, events: tuple[GestureEvent, ...]) -> None:
        now = self._clock.now_ms()
        self.watchdog.check(now)

        for ev in events:
            if ev.hand_id is None:
                continue
            if ev.kind is GestureKind.PINCH_START:
                self._pinched[ev.hand_id] = ev.t_ms
            elif ev.kind is GestureKind.PINCH_END:
                self._pinched.pop(ev.hand_id, None)
        kinds = {ev.kind for ev in events}

        # priority 1: clap (emergency / camera faults arrive through their own methods)
        if GestureKind.CLAP in kinds:
            self._clap_pending = False
            if self._camera is CameraState.RUNNING and self._state in (ControlState.PAUSED, ControlState.ACTIVE):
                if self._state is ControlState.ACTIVE:
                    self._do_pause("El çırpma: duraklatıldı")
                else:
                    self._activate("El çırpma: etkin")
                return
        if GestureKind.CLAP_CANDIDATE_START in kinds:
            self._reset_fists()
            self._clap_pending = True
            if self._state is ControlState.ACTIVE:
                self._soft_reset()
                self._bump()
        if GestureKind.CLAP_CANDIDATE_ABORT in kinds:
            self._clap_pending = False
            self._need_neutral = True
            self._neutral_since = None

        if self._state is not ControlState.ACTIVE:
            return
        self._expire_menu(now)

        stale = now - frame.capture_ms > self._cfg.stale_ms
        hands = [h for h in frame.hands if h.quality is Quality.USABLE and h.palm_scale_px > 0]
        if stale or frame.identity_ambiguous or not hands:
            self._tracking_lost()
            return
        self.watchdog.feed(frame.capture_ms)

        present = {h.hand_id for h in hands}
        for hid in [h for h in self._pinched if h not in present]:
            del self._pinched[hid]
        if not self._pinched:
            self._zoom_needs_release = False

        # neutral: usable, nothing pinched, no pending clap, for neutral_ms
        if self._pinched or self._clap_pending:
            self._neutral_since = None
        else:
            if self._neutral_since is None:
                self._neutral_since = frame.capture_ms
            if frame.capture_ms - self._neutral_since >= self._cfg.neutral_ms or GestureKind.NEUTRAL in kinds:
                self._need_neutral = False

        if self._clap_pending:
            return

        if self._menu is not None:
            self._reset_fists()
            self._index_tap.reset()
        elif self._fist_frame(frame, hands):
            self._index_tap.reset()
            self._mouse_interrupt("Yumruk: tıklama iptal")   # a fist never clicks or keeps a drag
            return

        if self._eng is not None and not all(h in present for h in self._eng.hands()):
            self._soft_reset()
            return

        dom = self._dominant(hands)
        uv = pos = raw = palm_uv = None
        if dom is not None:
            uv = normalize_camera_point(dom.index_tip_px[0], dom.index_tip_px[1], frame.width, frame.height,
                                        self._calib, self._cfg.mirror)
            # Move checks (click / window pinch) and the menu pointer use the palm center: the index
            # tip itself travels while a pinch closes and opens, which cancelled every click and moved
            # the menu pointer onto a neighbouring item at the selecting pinch.
            palm_uv = self._palm_uv(dom, frame)
        if uv is not None:
            su = self._smoother.filter(frame.capture_ms, uv[0], uv[1])
            targets = self._mapping_monitors()
            pos = map_normalized(su[0], su[1], targets)
            raw = map_normalized(palm_uv[0], palm_uv[1], targets) if palm_uv is not None else None
        else:
            self._smoother.reset()

        mid_ev = None
        if self._mouse_on() and self._menu is None and dom is not None:
            mid_ev = self._middle.update(dom, frame.capture_ms, frame.width, frame.height)
        else:
            self._middle.reset()

        if self._menu is not None:
            self._menu_frame(frame, events, dom, palm_uv, now)
            return

        if self._eng is not None:
            if self._eng.kind in _MOUSE_KINDS or (self._eng.kind is _EngKind.BLOCKED and self._eng.middle):
                self._mouse_frame(frame, events, dom, pos, mid_ev)
            else:
                self._eng_frame(frame, events, hands, dom, pos, raw, now)
            return

        if GestureKind.MENU_DWELL_COMPLETE in kinds and not self._need_neutral:
            self._open_mode_menu(dom, palm_uv, now)
            return

        if self._need_neutral or dom is None or pos is None:
            self._index_tap.reset()
            return

        if self._mode is Mode.POINTER and self._cfg.index_tap_click:
            latched = self._pointer if self._pointer is not None else pos
            suppress, click = self._index_tap.update(dom, frame.capture_ms, frame.width, latched)
            if click is not None:
                self._dispatch(ActionKind.LEFT_CLICK, frame.capture_ms, x=click[0], y=click[1])
                self._notice = 'Sağ işaret parmağı: sol tık'
            if suppress:
                return

        for ev in events:
            if ev.kind is GestureKind.PINCH_START and ev.hand_id is not None:
                if self._start_engagement(ev, events, frame, hands, dom, pos, raw):
                    return

        # thumb+middle right click; a thumb+index pinch in the same frame already won above
        if mid_ev == MID_START and dom.hand_id not in self._pinched and _right_pose(dom, strict=True):
            self._eng = _Eng(_EngKind.RIGHT_TAP, dom.hand_id, frame.capture_ms, latched=self._mouse_latch(
                frame.capture_ms, pos, dom, left=False), palm0=dom.palm_center_px, middle=True)
            return

        if (dom.hand_id not in self._pinched or (self._mode is Mode.POINTER and self._cfg.index_tap_click)) and _index_extended(dom) and pos != self._pointer:
            if self._dispatch(ActionKind.MOVE_POINTER, frame.capture_ms, x=pos[0], y=pos[1]):
                self._pointer = pos
        if self._mouse_on() and self._pointer is not None:
            open_pu = self._cfg.pinch_latch_open_pu
            if dom.hand_id not in self._pinched and dom.pinch_distance >= open_pu:
                self._open_ptr["index"] = (frame.capture_ms, self._pointer)
            if not self._middle.pinched and self._middle.distance >= open_pu:
                self._open_ptr["middle"] = (frame.capture_ms, self._pointer)

    def _tracking_lost(self) -> None:
        self._index_tap.reset()
        self._reset_mouse_memory()
        self._reset_fists()
        if self._eng is not None:
            self._soft_reset()
            self._notice = "İz kaybedildi: hareket iptal"
        elif self._menu is not None:
            self._cancel_confirmation(self._menu)
        self._neutral_since = None
        self._smoother.reset()

    # ------------------------------------------------------------ engagements

    def _reset_fists(self) -> None:
        self._fist_open.clear()
        self._fist_ready.clear()
        self._fist_candidate = None

    def _fist_frame(self, frame: FrameFeatures, hands: Sequence[HandFeatures]) -> bool:
        """Open 200 ms to arm; closed 350 ms to fire once, in every tool mode."""
        present = {h.hand_id for h in hands}
        self._fist_ready.intersection_update(present)
        self._fist_open = {k: v for k, v in self._fist_open.items() if k in present}
        fists = []
        for hand in hands:
            states = {f.name: f.state for f in hand.fingers}
            if hand.handedness is Handedness.UNKNOWN or len(states) != 5:
                self._fist_ready.discard(hand.hand_id)
                continue
            opened = all(state is FingerState.EXTENDED for state in states.values())
            closed = all(state is FingerState.BENT for state in states.values())
            if opened:
                since = self._fist_open.setdefault(hand.hand_id, frame.capture_ms)
                if frame.capture_ms - since >= 200:
                    self._fist_ready.add(hand.hand_id)
            else:
                self._fist_open.pop(hand.hand_id, None)
            if any(state is FingerState.UNKNOWN for state in states.values()):
                self._fist_ready.discard(hand.hand_id)
            if closed:
                fists.append(hand)
        if len(fists) != 1:
            self._fist_candidate = None
            if len(fists) > 1:
                self._fist_ready.clear()
                return True
            return False
        hand = fists[0]
        if hand.hand_id not in self._fist_ready:
            self._fist_candidate = None
            return True
        candidate = self._fist_candidate
        if candidate is None or candidate[:2] != (hand.hand_id, hand.handedness):
            self._cancel_engagement(release=True)
            target = self._windows.foreground_window() if hand.handedness is Handedness.RIGHT else None
            self._fist_candidate = (hand.hand_id, hand.handedness, frame.capture_ms, target)
            self._notice = 'Sağ yumruk: küçültmek için tut' if hand.handedness is Handedness.RIGHT else 'Sol yumruk: geri açmak için tut'
            return True
        if frame.capture_ms - candidate[2] < 350:
            return True
        self._fist_ready.discard(hand.hand_id)
        self._fist_candidate = None
        if hand.handedness is Handedness.RIGHT:
            target = candidate[3]
            if target is None or self._windows.foreground_window() != target or not self._valid(target):
                self._notice = 'Küçültülecek pencere yok veya hedef değişti'
                return True
            ok = self._dispatch(ActionKind.WINDOW_MINIMIZE, frame.capture_ms, target=target)
            self._notice = 'Sağ yumruk: pencere küçültüldü' if ok else 'Pencere küçültülemedi'
        else:
            while self._minimized_history and not self._valid(self._minimized_history[-1]):
                self._minimized_history.pop()
            if not self._minimized_history:
                self._notice = 'Bu oturumda geri açılacak pencere yok'
                return True
            ok = self._dispatch(ActionKind.WINDOW_RESTORE, frame.capture_ms, target=self._minimized_history[-1])
            self._notice = 'Sol yumruk: pencere geri açıldı' if ok else 'Pencere geri açılamadı'
        return True

    def _palm_uv(self, h: HandFeatures, frame: FrameFeatures) -> Optional[tuple[float, float]]:
        return normalize_camera_point(h.palm_center_px[0], h.palm_center_px[1], frame.width, frame.height,
                                      self._calib, self._cfg.mirror)

    def _palm_y(self, h: HandFeatures, frame: FrameFeatures) -> float:
        return h.palm_center_px[1] / frame.height if frame.height > 0 else 0.0

    @staticmethod
    def _palm_distance(a: HandFeatures, b: HandFeatures) -> float:
        d = math.dist(a.palm_center_px, b.palm_center_px)
        s = (a.palm_scale_px + b.palm_scale_px) / 2.0
        return d / s if s > 0 else 0.0

    def _block(self, e: _Eng, notice: str) -> None:
        e.kind = _EngKind.BLOCKED
        self._notice = notice

    # ------------------------------------------------------------ pinch mouse (POINTER)

    def _mouse_on(self) -> bool:
        return self._mode is Mode.POINTER and self._cfg.pinch_mouse and not self._cfg.index_tap_click

    def _mouse_latch(self, t: float, pos: tuple[int, int], dom: HandFeatures, left: bool) -> tuple[int, int]:
        """Click point for a pinch starting at t: the previous click's point for a quick second tap
        from the same place (Windows then forms the double click), else the pointer from the last
        frame the hand was open (the fingertip travels while the pinch closes), else the pointer."""
        cfg = self._cfg
        lt = self._last_tap
        if (left and lt is not None and 0.0 <= t - lt[0] <= cfg.double_click_window_ms
                and math.dist(dom.palm_center_px, lt[2]) / dom.palm_scale_px <= cfg.mouse_drag_move_palm):
            return lt[1]
        op = self._open_ptr.get("index" if left else "middle")
        if op is not None and 0.0 <= t - op[0] <= cfg.pinch_latch_lookback_ms:
            return op[1]
        return self._pointer if self._pointer is not None else pos

    def _left_up(self, e: _Eng, capture_ms: float) -> None:
        p = e.last_pos if e.last_pos is not None else self._pointer
        if p is None or not self._dispatch(ActionKind.LEFT_UP, capture_ms, x=p[0], y=p[1]):
            self._release()   # a dropped LEFT_UP must still free the button

    def _mouse_interrupt(self, notice: str) -> None:
        """End a pinch-mouse engagement without a click; a held button is released."""
        e = self._eng
        if e is None or e.kind not in _MOUSE_KINDS:
            return
        if e.kind is _EngKind.MOUSE_DRAG:
            self._left_up(e, self._clock.now_ms())
        middle = e.kind is _EngKind.RIGHT_TAP
        self._eng = _Eng(_EngKind.BLOCKED, e.hand_id, e.t0, middle=middle)
        self._last_tap = None
        self._notice = notice

    def _begin_drag(self, e: _Eng, t: float) -> None:
        assert e.latched is not None
        e.kind = _EngKind.MOUSE_DRAG   # set first: any failure below takes the release path
        e.last_pos = e.latched
        self._last_tap = None
        if self._dispatch(ActionKind.LEFT_DOWN, t, x=e.latched[0], y=e.latched[1]):
            self._pointer = e.latched
            self._notice = "Sürükleme: sol tuş basılı"
        else:
            self._mouse_interrupt("Sürükleme başlatılamadı")

    def _mouse_frame(self, frame: FrameFeatures, events: tuple[GestureEvent, ...], dom: Optional[HandFeatures],
                     pos: Optional[tuple[int, int]], mid_ev: Optional[str]) -> None:
        e = self._eng
        assert e is not None
        cfg = self._cfg
        t = frame.capture_ms
        same = dom is not None and dom.hand_id == e.hand_id
        if e.kind is _EngKind.BLOCKED:   # thumb+middle refused: wait for its release
            if not same or not self._middle.pinched:
                self._eng = None
            return
        if not same:
            self._mouse_interrupt("İşaretçi eli belirsiz: tıklama iptal")
            return
        assert dom is not None
        moved = (e.palm0 is not None
                 and math.dist(dom.palm_center_px, e.palm0) / dom.palm_scale_px > cfg.mouse_drag_move_palm)
        ends = [ev for ev in events if ev.kind is GestureKind.PINCH_END and ev.hand_id == e.hand_id]

        if e.kind is _EngKind.RIGHT_TAP:
            index_pinch = dom.hand_id in self._pinched or any(
                ev.kind is GestureKind.PINCH_START and ev.hand_id == e.hand_id for ev in events)
            if mid_ev == MID_CANCEL or (mid_ev is None and not self._middle.pinched):
                self._eng = None
                self._notice = "Sağ tık iptal edildi"
            elif index_pinch:
                self._mouse_interrupt("İki parmak birden: tıklama yok")
            elif not _right_pose(dom, strict=False):
                self._mouse_interrupt("Sağ tık iptal edildi")
            elif mid_ev == MID_END:
                self._eng = None
                if not moved and t - e.t0 < cfg.mouse_hold_ms and e.latched is not None:
                    if self._dispatch(ActionKind.RIGHT_CLICK, t, x=e.latched[0], y=e.latched[1]):
                        self._pointer = e.latched
                    self._notice = "Sağ tık"
                else:
                    self._notice = "Sağ tık iptal edildi"
            elif moved or t - e.t0 >= cfg.mouse_hold_ms:
                self._mouse_interrupt("Sağ tık iptal edildi")
            return

        if e.kind is _EngKind.MOUSE_TAP:
            if ends:
                self._eng = None
                if not moved and ends[0].t_ms - e.t0 < cfg.mouse_hold_ms and e.latched is not None:
                    if self._dispatch(ActionKind.LEFT_CLICK, t, x=e.latched[0], y=e.latched[1]):
                        self._pointer = e.latched
                        self._last_tap = (ends[0].t_ms, e.latched, e.palm0 or dom.palm_center_px)
                    self._notice = "Sol tık"
                else:
                    self._notice = "Tıklama iptal edildi"
            elif moved:
                self._begin_drag(e, t)          # keep the travel made during the candidate
            elif t - e.t0 >= cfg.mouse_hold_ms:
                e.pos0 = pos if pos is not None else e.pos0   # hand was still: no creep from smoother lag
                self._begin_drag(e, t)
            return

        # MOUSE_DRAG: the pointer follows the fingertip relative to its drag reference (pos0)
        if ends:
            self._eng = None
            self._left_up(e, t)
            self._notice = "Sürükleme bitti"
            return
        if pos is None or e.pos0 is None or e.latched is None:
            return
        target = project_to_monitors(e.latched[0] + pos[0] - e.pos0[0], e.latched[1] + pos[1] - e.pos0[1],
                                     self._mapping_monitors())
        if target is None or target == e.last_pos:
            return
        if self._dispatch(ActionKind.MOVE_POINTER, t, x=target[0], y=target[1]):
            e.last_pos = target
            self._pointer = target
        else:
            self._mouse_interrupt("Sürükleme iptal: imleç taşınamadı")

    def _start_engagement(self, ev: GestureEvent, events: tuple[GestureEvent, ...], frame: FrameFeatures,
                          hands: Sequence[HandFeatures], dom: HandFeatures, pos: tuple[int, int],
                          raw: Optional[tuple[int, int]]) -> bool:
        mode = self._mode
        if mode is not Mode.ZOOM and ev.hand_id != dom.hand_id:
            return False
        latched = self._pointer if self._pointer is not None else pos
        if mode is Mode.POINTER:
            if self._cfg.index_tap_click:
                return False
            if self._mouse_on():
                mid_t = self._middle.start_ms
                if self._middle.pinched and mid_t is not None and mid_t < frame.capture_ms:
                    # thumb+middle came first: neither pinch may click (same frame: the left click wins)
                    self._eng = _Eng(_EngKind.BLOCKED, dom.hand_id, ev.t_ms, middle=True)
                    self._notice = "İki parmak birden: tıklama yok"
                else:
                    self._eng = _Eng(_EngKind.MOUSE_TAP, dom.hand_id, ev.t_ms,
                                     latched=self._mouse_latch(ev.t_ms, pos, dom, left=True),
                                     palm0=dom.palm_center_px, pos0=pos)
                return True
            self._eng = _Eng(_EngKind.CLICK, dom.hand_id, ev.t_ms, latched=latched, raw_start=raw)
        elif mode is Mode.SCROLL:
            e = _Eng(_EngKind.SCROLL, dom.hand_id, ev.t_ms, latched=latched, base=self._palm_y(dom, frame),
                     rate=_Rate(self._cfg.scroll_steps_per_s))
            e.target = self._latch_foreground(latched)
            if e.target is None:
                self._block(e, "Kaydırmak için önce pencereyi odaklayın")
            self._eng = e
        elif mode is Mode.VOLUME:
            e = _Eng(_EngKind.VOLUME, dom.hand_id, ev.t_ms, base=self._palm_y(dom, frame),
                     rate=_Rate(self._cfg.volume_updates_per_s))
            try:
                e.base_level = _clamp(float(self._volume.get_volume()), 0.0, 1.0)
            except Exception:
                self._block(e, "Ses düzeyi okunamadı")
            self._eng = e
        elif mode is Mode.WINDOWS:
            try:
                target = self._windows.eligible_window_at(latched[0], latched[1])
            except Exception:
                target = None
            self._eng = _Eng(_EngKind.WIN_PINCH, dom.hand_id, ev.t_ms, latched=latched, raw_start=raw,
                             target=target)
        elif mode is Mode.ZOOM:
            if self._zoom_needs_release:
                return False
            self._eng = _Eng(_EngKind.ZOOM_WAIT, ev.hand_id, ev.t_ms, latched=latched)
            # a second pinch in the same batch pairs immediately
            for ev2 in events:
                if ev2.kind is GestureKind.PINCH_START and ev2.hand_id is not None and ev2.hand_id != ev.hand_id:
                    self._try_zoom_pair(ev2, frame, hands)
                    break
        return True

    def _latch_foreground(self, pos: Optional[tuple[int, int]]) -> Optional[WindowTarget]:
        if pos is None:
            return None
        try:
            fg = self._windows.foreground_window()
            under = self._windows.eligible_window_at(pos[0], pos[1])
        except Exception:
            return None
        return fg if fg is not None and under == fg else None

    def _try_zoom_pair(self, ev: GestureEvent, frame: FrameFeatures, hands: Sequence[HandFeatures]) -> None:
        e = self._eng
        if e is None or e.kind is not _EngKind.ZOOM_WAIT or ev.hand_id == e.hand_id:
            return
        if ev.t_ms - e.t0 > self._cfg.zoom_pair_window_ms:
            return
        by_id = {h.hand_id: h for h in hands}
        a, b = by_id.get(e.hand_id), by_id.get(ev.hand_id)
        e.other_hand = ev.hand_id
        if a is None or b is None:
            self._block(e, "Yakınlaştırma için iki el de görünmeli")
            return
        e.target = self._latch_foreground(e.latched)
        if e.target is None:
            self._block(e, "Yakınlaştırmak için önce pencereyi odaklayın")
            return
        e.kind = _EngKind.ZOOM
        e.base = self._palm_distance(a, b)
        e.rate = _Rate(self._cfg.zoom_steps_per_s)

    def _eng_frame(self, frame: FrameFeatures, events: tuple[GestureEvent, ...], hands: Sequence[HandFeatures],
                   dom: Optional[HandFeatures], pos: Optional[tuple[int, int]], raw: Optional[tuple[int, int]],
                   now: float) -> None:
        e = self._eng
        assert e is not None
        cfg = self._cfg
        ends = [ev for ev in events if ev.kind is GestureKind.PINCH_END and ev.hand_id in e.hands()]
        by_id = {h.hand_id: h for h in hands}
        hand = by_id.get(e.hand_id)

        if e.kind is _EngKind.ZOOM_WAIT:
            if ends:
                self._eng = None
                return
            for ev in events:
                if ev.kind is GestureKind.PINCH_START and ev.hand_id is not None and ev.hand_id != e.hand_id:
                    self._try_zoom_pair(ev, frame, hands)
                    if self._eng is None or self._eng.kind is not _EngKind.ZOOM_WAIT:
                        if self._eng is not None and self._eng.kind is _EngKind.BLOCKED:
                            self._zoom_needs_release = True
                        return
            if frame.capture_ms - e.t0 > cfg.zoom_pair_window_ms:
                self._block(e, "Yakınlaştırma: ikinci el geç kaldı")
                self._zoom_needs_release = True
            return

        if e.kind is _EngKind.BLOCKED:
            if ends:
                self._eng = None
            return

        if e.kind in (_EngKind.CLICK, _EngKind.WIN_PINCH):
            if raw is not None and e.raw_start is not None and e.latched is not None:
                thr = threshold_physical_px(cfg.click_max_move_logical_px, e.latched[0], e.latched[1], self._monitors)
                if math.dist(raw, e.raw_start) > thr:
                    e.moved = True

        if e.kind is _EngKind.CLICK:
            if ends:
                dur = ends[0].t_ms - e.t0
                self._eng = None
                if not e.moved and dur <= cfg.click_max_ms and e.latched is not None:
                    self._dispatch(ActionKind.LEFT_CLICK, frame.capture_ms, x=e.latched[0], y=e.latched[1])
                else:
                    self._notice = "Tıklama iptal edildi"
            elif frame.capture_ms - e.t0 > cfg.click_max_ms:
                self._block(e, "Tıklama iptal edildi (uzun tutma)")
            return

        if e.kind is _EngKind.WIN_PINCH:
            if ends:
                dur = ends[0].t_ms - e.t0
                self._eng = None
                if dur < cfg.drag_hold_ms and not e.moved and e.target is not None and self._valid(e.target):
                    self._open_window_menu(e.target, dom, frame, now)
                return
            if frame.capture_ms - e.t0 >= cfg.drag_hold_ms:
                if e.target is None or pos is None or not self._valid(e.target):
                    self._block(e, "Taşınabilir pencere yok")
                    return
                e.kind = _EngKind.DRAG
                e.rate = _Rate(cfg.drag_moves_per_s)
                e.rate.available(now)
                e.rate.take(1)
                e.last_pos = pos
                self._dispatch(ActionKind.WINDOW_DRAG_BEGIN, frame.capture_ms, x=pos[0], y=pos[1], target=e.target)
            return

        if e.kind is _EngKind.DRAG:
            if ends:
                if self._valid(e.target):
                    self._dispatch(ActionKind.WINDOW_DRAG_END, frame.capture_ms, target=e.target)
                    self._eng = None
                else:
                    self._cancel_engagement(release=True)
                return
            if pos is None or pos == e.last_pos or e.rate is None or e.rate.available(now) < 1:
                return
            if not self._valid(e.target):
                self._cancel_engagement(release=True)
                self._eng = _Eng(_EngKind.BLOCKED, e.hand_id, e.t0)
                self._notice = "Pencere kayboldu: taşıma iptal"
                return
            e.rate.take(1)
            e.last_pos = pos
            self._dispatch(ActionKind.WINDOW_DRAG_MOVE, frame.capture_ms, x=pos[0], y=pos[1], target=e.target)
            return

        if e.kind is _EngKind.SCROLL:
            if ends:
                self._eng = None
                return
            if hand is None:
                return
            d = e.base - self._palm_y(hand, frame)
            self._accumulate(e, d, cfg.scroll_dead_zone_norm, cfg.scroll_step_norm, cfg.scroll_max_pending,
                             -1 if cfg.scroll_invert else 1, ActionKind.SCROLL, frame, now)
            return

        if e.kind is _EngKind.ZOOM:
            if ends:
                self._cancel_engagement(release=True)
                self._zoom_needs_release = True
                return
            other = by_id.get(e.other_hand) if e.other_hand is not None else None
            if hand is None or other is None:
                return
            d = self._palm_distance(hand, other) - e.base
            self._accumulate(e, d, cfg.zoom_dead_zone_palm, cfg.zoom_step_palm, cfg.zoom_max_pending,
                             -1 if cfg.zoom_invert else 1, ActionKind.ZOOM, frame, now)
            return

        if e.kind is _EngKind.VOLUME:
            if ends:
                self._eng = None
                return
            if hand is None or e.rate is None:
                return
            d = e.base - self._palm_y(hand, frame)
            dz = cfg.volume_dead_zone_norm
            eff = 0.0 if abs(d) <= dz else math.copysign(abs(d) - dz, d)
            value = _clamp(e.base_level + eff * cfg.volume_gain, 0.0, 1.0)
            ref = e.last_value if e.last_value is not None else e.base_level
            if value == ref or (abs(value - ref) < cfg.volume_min_delta and value not in (0.0, 1.0)):
                return
            if e.rate.available(now) < 1:
                return
            e.rate.take(1)
            e.last_value = value
            self._dispatch(ActionKind.SET_VOLUME, frame.capture_ms, value=value)
            return

    def _accumulate(self, e: _Eng, d: float, dead: float, step: float, max_pending: int, sign: int,
                    kind: ActionKind, frame: FrameFeatures, now: float) -> None:
        total = _steps(d, dead, step)
        pending = total - e.emitted
        if pending > max_pending:
            e.emitted = total - max_pending
            pending = max_pending
        elif pending < -max_pending:
            e.emitted = total + max_pending
            pending = -max_pending
        if pending == 0 or e.rate is None:
            return
        n = min(abs(pending), e.rate.available(now))
        if n <= 0:
            return
        if not self._target_ok(e.target, e.latched):
            self._cancel_engagement(release=True)
            if kind is ActionKind.ZOOM:
                self._zoom_needs_release = True
            self._eng = _Eng(_EngKind.BLOCKED, e.hand_id, e.t0, other_hand=e.other_hand)
            self._notice = "Hedef pencere değişti: iptal edildi"
            return
        direction = 1 if pending > 0 else -1
        e.rate.take(n)
        e.emitted += direction * n
        self._dispatch(kind, frame.capture_ms, steps=sign * direction * n, target=e.target)

    # ------------------------------------------------------------ menus

    def _open_mode_menu(self, dom: Optional[HandFeatures], uv: Optional[tuple[float, float]], now: float) -> None:
        items = [MenuItem(m.value, _MODE_LABELS[m], True, m is self._mode) for m in Mode]
        armed = dom is not None and dom.hand_id not in self._pinched
        self._menu = _Menu(MenuKind.MODE, items, None, now, now, armed, anchor=uv)
        self._notice = ""

    def _window_items(self, close_armed: bool) -> list[MenuItem]:
        multi = len(self._monitors) >= 2
        return [
            MenuItem("minimize", "Simge durumuna küçült"),
            MenuItem("maximize", "Büyüt / geri al"),
            MenuItem("other_monitor", "Diğer ekrana taşı", enabled=multi),
            MenuItem("close", CLOSE_CONFIRM_LABEL if close_armed else CLOSE_LABEL),
        ]

    def _open_window_menu(self, target: WindowTarget, dom: Optional[HandFeatures], frame: FrameFeatures,
                          now: float) -> None:
        uv = self._palm_uv(dom, frame) if dom is not None else None
        armed = dom is not None and dom.hand_id not in self._pinched
        self._menu = _Menu(MenuKind.WINDOW, self._window_items(False), target, now, now, armed, anchor=uv)

    def _close_menu(self, notice: str = "") -> None:
        # release before reuse: OS output resumes only after a fresh neutral
        self._menu = None
        self._need_neutral = True
        self._neutral_since = None
        self._smoother.reset()
        if notice:
            self._notice = notice

    def _expire_menu(self, now: float) -> None:
        m = self._menu
        if m is not None and m.hold_t0 is None and now - m.last_interaction_ms >= self._cfg.menu_timeout_ms:
            self._close_menu("Menü zaman aşımı")

    def _cancel_confirmation(self, m: _Menu) -> None:
        if m.close_armed or m.hold_t0 is not None:
            m.close_armed = False
            m.confirm_needs_release = False
            m.hold_t0 = None
            if m.kind is MenuKind.WINDOW:
                m.items = self._window_items(False)

    def _menu_frame(self, frame: FrameFeatures, events: tuple[GestureEvent, ...], dom: Optional[HandFeatures],
                    uv: Optional[tuple[float, float]], now: float) -> None:
        m = self._menu
        assert m is not None
        if m.kind is MenuKind.WINDOW and not self._valid(m.target):
            self._close_menu("Hedef pencere kayboldu")
            return
        if dom is None or uv is None:
            self._cancel_confirmation(m)
            return
        if m.anchor is None:
            m.anchor = uv
        g = self._cfg.menu_gain
        m.pointer = (_clamp(0.5 + (uv[0] - m.anchor[0]) * g, 0.0, 1.0),
                     _clamp(0.5 + (uv[1] - m.anchor[1]) * g, 0.0, 1.0))
        n = len(m.items)
        idx = min(n - 1, int(m.pointer[1] * n))
        if idx != m.hovered:
            m.hovered = idx
            m.last_interaction_ms = now
            if m.hold_t0 is not None:
                self._cancel_confirmation(m)
                self._notice = "Kapatma onayı iptal"
        dom_pinched = dom.hand_id in self._pinched

        for ev in events:
            if ev.hand_id != dom.hand_id:
                continue
            if ev.kind is GestureKind.PINCH_START:
                m.last_interaction_ms = now
                if m.armed:
                    self._menu_select(m, ev, frame)
                    if self._menu is not m:
                        return
            elif ev.kind is GestureKind.PINCH_END:
                m.last_interaction_ms = now
                m.armed = True
                if m.hold_t0 is not None:
                    self._cancel_confirmation(m)
                    self._notice = "Kapatma onayı iptal"
                elif m.close_armed:
                    m.confirm_needs_release = False
        if not dom_pinched:
            m.armed = True

        if m.hold_t0 is not None:
            m.hold_now = frame.capture_ms
            if dom_pinched and frame.capture_ms - m.hold_t0 >= self._cfg.close_hold_ms:
                target = m.target
                self._close_menu()
                if self._valid(target):
                    self._dispatch(ActionKind.WINDOW_CLOSE, frame.capture_ms, target=target)
                    self._notice = "Kapatma isteği gönderildi"
                else:
                    self._notice = "Hedef pencere kayboldu"

    def _menu_select(self, m: _Menu, ev: GestureEvent, frame: FrameFeatures) -> None:
        if m.hovered is None:
            return
        item = m.items[m.hovered]
        if not item.enabled:
            self._notice = f"{item.label}: kullanılamıyor"
            return
        if m.kind is MenuKind.MODE:
            self._close_menu()
            self._set_mode(Mode(item.key))
            return
        if item.key == "close":
            if not m.close_armed:
                m.close_armed = True
                m.confirm_needs_release = True
                m.items = self._window_items(True)
                self._notice = "Onay için bırakın, sonra 1 sn basılı tutun"
            elif not m.confirm_needs_release:
                m.hold_t0 = ev.t_ms
                m.hold_now = ev.t_ms
            return
        target = m.target
        self._close_menu()
        if not self._valid(target):
            self._notice = "Hedef pencere kayboldu"
            return
        self._dispatch(_WINDOW_ACTIONS[item.key], frame.capture_ms, target=target)

    def _menu_snapshot(self, now: float) -> Optional[MenuSnapshot]:
        m = self._menu
        if m is None:
            return None
        prog = 0.0
        if m.hold_t0 is not None and self._cfg.close_hold_ms > 0:
            prog = _clamp((max(now, m.hold_now) - m.hold_t0) / self._cfg.close_hold_ms, 0.0, 1.0)
        return MenuSnapshot(
            kind=m.kind,
            items=tuple(m.items),
            hovered=m.hovered,
            pointer=m.pointer,
            hold_progress=prog,
            close_armed=m.close_armed,
            target=m.target,
            remaining_ms=max(0.0, self._cfg.menu_timeout_ms - (now - m.last_interaction_ms)),
        )

    def _pending_text(self, now: float) -> str:
        m = self._menu
        if m is not None:
            if m.hold_t0 is not None:
                return "Kapatma onayı: basılı tutun"
            if m.close_armed:
                return "Kapatma onayı bekleniyor"
            return "Menü açık"
        if self._eng is not None:
            return _ENG_TEXT[self._eng.kind]
        return ""
