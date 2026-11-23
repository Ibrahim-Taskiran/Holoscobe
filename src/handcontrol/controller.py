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
    KeyCommand,
    Mode,
    Monitor,
    ProcessNames,
    Quality,
    VolumeControl,
    WindowQuery,
    WindowTarget,
)
from handcontrol.dwell import DwellClicker
from handcontrol.swipe import (COMMAND_LABELS, PROFILES, SwipeRecognizer, pinch_command, resolve_profile,
                               swipe_command)
from handcontrol.mapping import (CalibrationRect, map_normalized, normalize_camera_point, project_to_monitors,
                                 threshold_physical_px)
from handcontrol.safety import GuardedSink, Watchdog
from handcontrol.index_tap import IndexTapRecognizer
from handcontrol.relative_pointer import AccelCurve, RelativeMotion, advance
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
    # disables pinch clicks. Otherwise pinch_mouse: thumb+index tap = left click, long hold = right
    # click, grab = left-button drag, thumb+middle tap = right click. False keeps the legacy click.
    index_tap_click: bool = False
    pinch_mouse: bool = True
    # A motion drag starts on palm travel only, never on time (session 2026-11-14: 5 of 14 hold-time
    # drags were still-hand pinches of 531-1938 ms, real drags travelled 1.37-3.30 palm units, still
    # holds drifted up to 0.39).
    tap_max_ms: float = 1500.0              # round 6 only; the pinch mouse long press replaced it (unused)
    # Round 7 gesture set (user decision 2026-11-14). A still thumb+index pinch released before
    # right_long_press_ms is a left click; held that long it right-clicks at once (the release adds
    # nothing). Grab: the thumb tip with the index AND middle tips together, held grab_confirm_ms,
    # presses the left button for a drag until the grab opens. The second fingertip may join during
    # pinch_decide_ms after the pinch onset (the click fires at release).
    right_long_press_ms: float = 800.0
    grab_confirm_ms: float = 120.0
    right_hold_max_ms: float = 3000.0       # longer thumb+middle pinch: no right click (real holds 1.6-2.8 s)
    right_curl_cancel_ms: float = 150.0     # ring+little curled this long during a right pinch cancels it
    double_click_window_ms: float = 500.0   # a tap starting this soon after a click reuses its point
    double_tap_min_gap_ms: float = 250.0    # ... and is re-armed without a wide opening if apart this long
    mouse_drag_move_palm: float = 0.6       # palm travel that starts a left drag
    right_cancel_move_palm: float = 0.6    # recorded right release drift exceeds .45 without a drag
    pinch_latch_open_pu: float = 0.5        # absolute mode: latch the pointer of the last frame the hand was this open
    pinch_latch_lookback_ms: float = 250.0  # ... if that frame is at most this old at pinch start
    right_pinch_on_pu: float = 0.33         # thumb+middle hysteresis (palm units), same as thumb+index
    right_pinch_off_pu: float = 0.48
    right_pinch_debounce_ms: float = 70.0
    # one physical pinch = one click: after a pinch ends, a new pinch of the same finger only counts
    # once the fingers were this far apart (palm units) or apart for this long (threshold flicker)
    pinch_rearm_open_pu: float = 0.9        # observed bounce peaks .776/.899; clear opening is about 1 pu
    pinch_rearm_ms: float = 700.0          # narrow recontacts within this window are one physical pinch
    # Left/right decision. A pinch onset (first thumb+index or thumb+middle start) opens a window of
    # pinch_decide_ms; at its end (or at a release inside it) the last contact frame decides: finger
    # states when they are decisive, else the clearly nearer tip (by pinch_resolve_margin_pu). Both
    # tips touching is the grab (checked first); a near tie without contact stays unresolved. Once decided the other pinch is ignored
    # until both are released. The decided finger's own pinch must start within pinch_decide_max_ms.
    pinch_resolve_margin_pu: float = 0.02
    pinch_decide_ms: float = 60.0           # 3 frames at 30 FPS (onset frame + 2)
    pinch_decide_max_ms: float = 300.0
    right_open_lookback_ms: float = 500.0   # right click tolerates unsure fingers if the hand was open this recently
    # a closed hand with thumb+index tips this close and the index not fully curled is a pinch, not a fist
    pinch_not_fist_pu: float = 0.45
    pinch_not_fist_index_curl: float = 0.80
    # relative pointer (default). False = legacy absolute fingertip mapping through `calibration`.
    pointer_relative: bool = True
    pointer_speed: float = 1.0              # user multiplier 0.5..2.0 (config.Settings.pointer_speed)
    rel_min_gain: float = 1200.0            # desktop px per frame width of anchor travel, slow hand
    rel_max_gain: float = 9000.0            # ... brisk hand (quarter frame ~ one 1920 px monitor)
    rel_slow_speed: float = 0.08            # frame widths / s
    rel_fast_speed: float = 0.80
    rel_dead_zone: float = 0.003            # frame widths (~2 px of a 640 px frame)
    rel_speed_tau_ms: float = 40.0
    clutch_debounce_ms: float = 100.0       # pointing pose must hold this long to engage
    # sticky engagement: once engaged only a clear release (open hand or index BENT) held this long
    # clutches; unknown or mixed finger states keep the pointer engaged
    clutch_release_ms: float = 200.0
    frame_margin: float = 0.03             # palm center this close to the frame edge = out of frame (clutch)
    # schema 3 (round 6 features); the app maps config.Settings onto these
    swipe_profile: str = "auto"            # COMMANDS mode: "auto" (by foreground process) or a swipe.PROFILES item
    auto_pause_ms: float = 0.0             # ACTIVE without any usable hand this long -> paused; 0 = off
    dwell_click: bool = False              # POINTER: the engaged cursor resting still dwell_ms left-clicks
    dwell_ms: float = 1000.0


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
    pointer_engaged: bool = False  # POINTER mode, relative pointer: the cursor follows the hand
    tracking_ok: bool = True       # dominant hand usable in the last frame (or inside the short-gap tolerance)
    last_cancel: str = ""          # Turkish reason of the last cancelled/refused click, drag or right click
    # hold feedback: "right_click" | "grab" | "fist" | "dwell" | "window_drag" | "" and its 0..1 progress
    hold_kind: str = ""
    hold_progress: float = 0.0
    last_command: str = ""         # KeyCommand value of the last dispatched command
    command_seq: int = 0           # +1 per dispatched command (toast repeats of the same command)
    swipe_profile_active: str = "" # COMMANDS mode: concrete profile in use ("slides", ...), else ""


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
    MOUSE_PENDING = "mouse_pending"   # pinch onset: left or right not decided yet (pointer held)
    MOUSE_TAP = "mouse_tap"      # thumb+index pinch: tap candidate (pointer held at the latch)
    MOUSE_DRAG = "mouse_drag"    # left button held, pointer follows the hand
    RIGHT_TAP = "right_tap"      # thumb+middle pinch: right click candidate
    GRAB = "grab"                # thumb with index and middle tips together: drag being confirmed
    BLOCKED = "blocked"      # cancelled or refused; waits for the pinch release
    CMD_PINCH = "cmd_pinch"  # COMMANDS mode: a short dominant pinch sends the profile's pinch command


_MOUSE_KINDS = (_EngKind.MOUSE_PENDING, _EngKind.MOUSE_TAP, _EngKind.MOUSE_DRAG, _EngKind.RIGHT_TAP,
                _EngKind.GRAB)
_CLICK_KINDS = _MOUSE_KINDS + (_EngKind.CLICK,)   # engagements whose cancellation sets last_cancel
_LONG_PRESS_HINT_MS = 300.0   # a still thumb+index pinch held this long shows the long press hint

_ENG_TEXT = {
    _EngKind.MOUSE_PENDING: "Tıklama bekleniyor",
    _EngKind.MOUSE_TAP: "Tıklama bekleniyor",
    _EngKind.MOUSE_DRAG: "Sürükleniyor (sol tuş basılı)",
    _EngKind.RIGHT_TAP: "Sağ tık bekleniyor",
    _EngKind.GRAB: "Sürükleme hazırlanıyor",
    _EngKind.CLICK: "Tıklama bekleniyor",
    _EngKind.SCROLL: "Kaydırma",
    _EngKind.ZOOM_WAIT: "Yakınlaştırma: ikinci el bekleniyor",
    _EngKind.ZOOM: "Yakınlaştırma",
    _EngKind.VOLUME: "Ses ayarı",
    _EngKind.WIN_PINCH: "Pencere seçiliyor",
    _EngKind.DRAG: "Pencere taşınıyor",
    _EngKind.BLOCKED: "Bırakmanız bekleniyor",
    _EngKind.CMD_PINCH: "Komut bekleniyor",
}
_HOLD_SHOW_MS = 150.0            # hold progress (long press right click, dwell) shows after this
_FIST_HOLD_MS = 350.0            # _fist_frame: closed this long fires
AUTO_PAUSE_REASON = "Otomatik duraklatıldı: el görülmedi"


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
    # pinch-mouse session: a BLOCKED engagement with middle=True waits until neither the thumb+index
    # nor the thumb+middle pinch is held any more
    middle: bool = False
    vote: Optional[str] = None                    # MOUSE_PENDING: "left"/"right" from the last contact frame
    state_vote: Optional[str] = None              # ... from finger states, when they were decisive
    decision_done: bool = False                  # freeze the side after the short decision window
    index_armed: bool = True                     # re-arm state at onset, before this session releases
    middle_armed: bool = True
    right_ok0: bool = False                      # thumb+middle pose check passed at the pinch onset
    curl_since: Optional[float] = None           # RIGHT_TAP: first frame of the current ring+little curl
    anchor0: Optional[tuple[float, float]] = None  # relative mode: filtered hand anchor at pinch start
    fpos: Optional[tuple[float, float]] = None     # relative mode: float position of a window drag
    onset: float = 0.0                           # pinch-mouse session onset (grab join window)
    grab: bool = False                           # MOUSE_DRAG started by a grab (ends when the grab opens)
    grab_since: Optional[float] = None           # GRAB: first frame of the three-tip contact
    open_since: Optional[float] = None           # grab: first frame of the current opening (debounce)
    text: str = ""                               # pending text override (BLOCKED after a long press)

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
    Mode.COMMANDS: "Komutlar",
    Mode.INSTRUMENT: "Enstrüman",
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


def _outer_curled(h: HandFeatures) -> bool:
    """Ring and little both BENT: the pointing pose (thumb tucked over the curled middle finger brings
    the thumb tip next to the middle tip, recorded thumb-middle median 0.33 pu, minimum 0.02) or a
    fist. Never a right click. The user's real right pinch keeps ring and little EXTENDED; the index
    may read BENT there (recording 2026-11-12, right repeat 6), so the index does not veto."""
    s = {f.name: f.state for f in h.fingers}
    return s.get(FingerName.RING) is FingerState.BENT and s.get(FingerName.LITTLE) is FingerState.BENT


def _state_vote(h: HandFeatures) -> Optional[str]:
    """Left/right from finger states alone, or None. Right: middle BENT, index EXTENDED and ring or
    little EXTENDED (index EXTENDED + middle BENT alone is also the pointing pose, which the state
    latch still reports for 100-300 ms after the hand changes). Left: index BENT, middle EXTENDED."""
    s = {f.name: f.state for f in h.fingers}
    idx, mid = s.get(FingerName.INDEX), s.get(FingerName.MIDDLE)
    if (mid is FingerState.BENT and idx is FingerState.EXTENDED
            and FingerState.EXTENDED in (s.get(FingerName.RING), s.get(FingerName.LITTLE))):
        return "right"
    if idx is FingerState.BENT and mid is FingerState.EXTENDED:
        return "left"
    return None


def _pointing_pose(h: HandFeatures) -> bool:
    """Relative pointer engage pose: index EXTENDED and at least two of middle/ring/little BENT."""
    s = {f.name: f.state for f in h.fingers}
    bent = sum(s.get(n) is FingerState.BENT for n in (FingerName.MIDDLE, FingerName.RING, FingerName.LITTLE))
    return s.get(FingerName.INDEX) is FingerState.EXTENDED and bent >= 2


def _open_hand(h: HandFeatures) -> bool:
    """Index, middle, ring and little all EXTENDED (thumb ignored)."""
    s = {f.name: f.state for f in h.fingers}
    return all(s.get(n) is FingerState.EXTENDED
               for n in (FingerName.INDEX, FingerName.MIDDLE, FingerName.RING, FingerName.LITTLE))


def _release_pose(h: HandFeatures) -> bool:
    """Clear clutch pose of an engaged pointer: open hand, or index BENT (fist-like)."""
    if _open_hand(h):
        return True
    return any(f.name is FingerName.INDEX and f.state is FingerState.BENT for f in h.fingers)


def _cancel_prefix(kind: Optional[_EngKind]) -> str:
    if kind is _EngKind.RIGHT_TAP:
        return "Sağ tık iptal"
    if kind in (_EngKind.MOUSE_DRAG, _EngKind.GRAB):
        return "Sürükleme iptal"
    return "Tıklama iptal"


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
        cursor_source: Optional[Callable[[], Optional[tuple[int, int]]]] = None,
        process_names: Optional[ProcessNames] = None,
    ) -> None:
        """cursor_source (optional): returns the real OS cursor position (physical px) or None.
        Relative mode starts from it and re-syncs to it whenever the pointer re-engages; without it
        the pointer starts at the centre of the primary monitor.
        process_names (optional): foreground process lookup for the COMMANDS "auto" profile; without
        it "auto" resolves to the "desktops" profile."""
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
        # frames skipped during a tolerated tracking gap must not cancel a held thumb+middle pinch; the
        # watchdog bounds the gap at loss_timeout_ms
        self._middle = MiddlePinchRecognizer(config.right_pinch_on_pu, config.right_pinch_off_pu,
                                             config.right_pinch_debounce_ms, max_gap_ms=config.loss_timeout_ms)
        # (release ms, point, palm center px) of the last pinch left click
        self._last_tap: Optional[tuple[float, tuple[int, int], tuple[float, float]]] = None
        # "index" / "middle": (capture ms, pointer) of the last frame that pinch was open
        self._open_ptr: dict[str, tuple[float, tuple[int, int]]] = {}
        # "index" / "middle": [hand id, end ms, widest opening since] of the last pinch end (re-arm)
        self._rearm: dict[str, list[float]] = {}
        self._open_seen: Optional[tuple[int, float]] = None   # (hand id, ms) dominant hand last fully open
        # relative pointer
        self._cursor_source = cursor_source
        self._rel = RelativeMotion(AccelCurve(config.rel_min_gain, config.rel_max_gain, config.rel_slow_speed,
                                              config.rel_fast_speed), config.rel_dead_zone, config.rel_speed_tau_ms)
        self._rel_used = False                 # set when this frame fed the relative motion
        self._fpos: Optional[tuple[float, float]] = None   # float cursor (sub-pixel remainders)
        self._anchor_now: Optional[tuple[float, float]] = None
        self._engaged = False                  # sticky engage state (cursor follows the hand)
        self._clutch_since: Optional[float] = None    # pointing pose seen since (engage debounce)
        self._release_since: Optional[float] = None   # clear release pose seen since (cursor frozen meanwhile)
        self._clutch_hand: Optional[int] = None
        self._dom_ok_ms: Optional[float] = None       # capture ms of the last frame the dominant hand was usable
        self._dom_ok_id: Optional[int] = None         # ... and its hand id
        self._tracking_ok = True
        self._last_cancel = ""
        # COMMANDS mode, dwell click, auto pause
        self._process_names = process_names
        self._swipe = SwipeRecognizer()
        self._swipe_fed = False                # set when this frame fed the swipe recognizer
        self._dwell = DwellClicker()
        self._dwell_fed = False                # set when this frame fed the dwell clicker
        self._last_command = ""
        self._command_seq = 0
        self._profile_active = ""
        self._hand_seen_ms: Optional[float] = None    # clock ms of the last frame with a usable hand

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
            self._rel_used = False
            self._swipe_fed = self._dwell_fed = False
            try:
                self._frame(frame, tuple(events))
            except Exception as exc:  # never let a bug keep input owned
                self._enter_fault(f"Denetleyici hatası: {type(exc).__name__}: {exc}")
            finally:
                if not self._rel_used:   # any frame without relative motion is a clutch: re-anchor later
                    self._rel.reset()
                if not self._swipe_fed:  # gap, ambiguity, pinch, menu, clap candidate, other mode
                    self._swipe.reset()
                if not self._dwell_fed:  # disengaged, pinched, gap, menu, other mode
                    self._dwell.cancel()
                self._in_call -= 1
        self._notify()

    def tick(self) -> None:
        """Time-based expiry without a frame (menu timeout, watchdog). Safe to call from a UI timer."""
        with self._lock:
            self._in_call += 1
            try:
                now = self._clock.now_ms()
                self.watchdog.check(now)
                if self._state is ControlState.ACTIVE and not self._auto_pause_check(now):
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
            hold_kind, hold_progress = self._hold(now)
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
                pointer_engaged=self._engaged and self._mode is Mode.POINTER and self._cfg.pointer_relative,
                tracking_ok=self._tracking_ok,
                last_cancel=self._last_cancel,
                hold_kind=hold_kind,
                hold_progress=hold_progress,
                last_command=self._last_command,
                command_seq=self._command_seq,
                swipe_profile_active=self._profile_active if self._mode is Mode.COMMANDS else "",
            )

    def _hold(self, now: float) -> tuple[str, float]:
        """(hold kind, 0..1 progress) of the hold running now, for UI feedback."""
        if self._state is not ControlState.ACTIVE or self._menu is not None:
            return "", 0.0
        cfg = self._cfg

        def frac(elapsed: float, total: float) -> float:
            return _clamp(elapsed / total, 0.0, 1.0) if total > 0 else 1.0

        e = self._eng
        if e is not None:
            if e.kind is _EngKind.MOUSE_TAP:
                held = now - e.t0
                return ("right_click", frac(held, cfg.right_long_press_ms)) if held >= _HOLD_SHOW_MS else ("", 0.0)
            if e.kind is _EngKind.GRAB and e.grab_since is not None:
                return "grab", frac(now - e.grab_since, cfg.grab_confirm_ms)
            if e.kind is _EngKind.WIN_PINCH:
                return "window_drag", frac(now - e.t0, cfg.drag_hold_ms)
            return "", 0.0
        c = self._fist_candidate
        if c is not None:
            return "fist", frac(now - c[2], _FIST_HOLD_MS)
        if cfg.dwell_click and self._mode is Mode.POINTER and self._dwell.held_ms(now) >= _HOLD_SHOW_MS:
            return "dwell", self._dwell.progress(now, cfg.dwell_ms)
        return "", 0.0

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
        self._note_cancel(self._eng, "kontrol durdu")
        self._eng = None   # a held left button is released by the caller's RELEASE_ALL
        self._tracking_ok = True
        self._menu = None
        self._need_neutral = True
        self._neutral_since = None
        self._clap_pending = False
        self._smoother.reset()
        self._swipe.reset()
        self._dwell.cancel()

    def _auto_pause_check(self, now: float) -> bool:
        """ACTIVE without any usable hand for auto_pause_ms -> Paused. True when it paused."""
        ms = self._cfg.auto_pause_ms
        if ms <= 0 or self._state is not ControlState.ACTIVE:
            return False
        if self._hand_seen_ms is None or now < self._hand_seen_ms:
            self._hand_seen_ms = now
            return False
        if now - self._hand_seen_ms < ms:
            return False
        self._do_pause(AUTO_PAUSE_REASON)
        return True

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
        self._hand_seen_ms = self._clock.now_ms()

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
        self._cancel_engagement(release=True, why="kip değişti")
        self._menu = None
        self._need_neutral = True
        self._neutral_since = None
        self._smoother.reset()
        self._swipe.reset()
        self._dwell.cancel()
        if mode is Mode.COMMANDS:
            self._profile_active = self._command_profile()
        if mode is Mode.INSTRUMENT:
            # audio-only mode: free every app-owned input on entry, held or not
            self._index_tap.reset()
            self._reset_mouse_memory()
            self._reset_fists()
            self._release()
        self._reason = f"Kip: {_MODE_LABELS[mode]}"

    def _note_cancel(self, e: Optional[_Eng], why: str) -> None:
        """Remember why a click / drag / right-click candidate ended without its action."""
        if e is not None and e.kind in _CLICK_KINDS:
            right = e.kind is _EngKind.MOUSE_PENDING and (e.state_vote or e.vote) == "right"
            self._last_cancel = f"{_cancel_prefix(_EngKind.RIGHT_TAP if right else e.kind)}: {why}"

    def _cancel_engagement(self, release: bool, why: str = "") -> None:
        e, self._eng = self._eng, None
        if why:
            self._note_cancel(e, why)
        if e is not None and e.kind is _EngKind.MOUSE_DRAG:
            self._left_up(e, self._clock.now_ms())   # the left button never stays held
        if e is not None and release and e.dispatched > 0:
            self._release()

    def _reset_mouse_memory(self) -> None:
        self._middle.reset()
        self._last_tap = None
        self._open_ptr.clear()
        self._rearm.clear()
        self._open_seen = None
        self._disengage()
        self._clutch_hand = None

    def _disengage(self) -> None:
        self._engaged = False
        self._clutch_since = None
        self._release_since = None
        self._dwell.cancel()

    # ------------------------------------------------------------ relative pointer

    def _set_pointer(self, p: Optional[tuple[int, int]]) -> None:
        self._pointer = p
        self._fpos = (float(p[0]), float(p[1])) if p is not None else None

    def _read_cursor(self) -> Optional[tuple[int, int]]:
        if self._cursor_source is None:
            return None
        try:
            p = self._cursor_source()
            if p is None:
                return None
            return project_to_monitors(float(p[0]), float(p[1]), self._mapping_monitors())
        except Exception:
            return None

    def _initial_pointer(self) -> Optional[tuple[int, int]]:
        """Real cursor when a source is wired, else the centre of the primary monitor."""
        p = self._read_cursor()
        if p is not None:
            return p
        mons = self._monitors
        prim = next((m for m in mons if m.is_primary), mons[0] if mons else None)
        if prim is None:
            return None
        b = prim.bounds
        return project_to_monitors((b.left + b.right - 1) / 2.0, (b.top + b.bottom - 1) / 2.0,
                                   self._mapping_monitors())

    def _anchor(self, h: HandFeatures, frame: FrameFeatures) -> Optional[tuple[float, float]]:
        """Filtered hand anchor in frame widths: palm center = mean of knuckles 5, 9, 13, 17, which
        does not move when a finger bends to pinch. None when the palm is at the frame edge."""
        w, ht = frame.width, frame.height
        x, y = h.palm_center_px
        m = self._cfg.frame_margin
        if w <= 0 or ht <= 0 or not (math.isfinite(x) and math.isfinite(y)):
            return None
        if not (m * w <= x <= (1.0 - m) * w and m * ht <= y <= (1.0 - m) * ht):
            return None
        nx = (w - x) / w if self._cfg.mirror else x / w
        return self._smoother.filter(frame.capture_ms, nx, y / w)

    def _update_clutch(self, dom: Optional[HandFeatures], t: float) -> None:
        """Sticky engage state. Engage: pointing pose held clutch_debounce_ms. Release: a clear release
        pose (open hand / index BENT) with no pointing frame in between for clutch_release_ms; the
        cursor is frozen from its first frame, so a short flicker only pauses it. Unknown or mixed
        finger states, and any pose while the hand pinches, keep the state. Hand lost, out of frame
        or a new hand id clutches at once."""
        if dom is None or self._anchor_now is None or dom.hand_id != self._clutch_hand:
            self._disengage()
            self._clutch_hand = dom.hand_id if dom is not None else None
            if dom is None or self._anchor_now is None:
                return
        cfg = self._cfg
        pointing = _pointing_pose(dom)
        if not self._engaged:
            if not pointing:
                self._clutch_since = None
                return
            if self._clutch_since is None:
                self._clutch_since = t
            if t - self._clutch_since >= cfg.clutch_debounce_ms:
                self._engaged = True
                self._clutch_since = None
                self._release_since = None
                if self._eng is None:
                    p = self._read_cursor()      # the physical mouse may have moved while clutched
                    if p is not None:
                        self._set_pointer(p)
            return
        if pointing:
            self._release_since = None
            return
        self._release_step(dom, t)

    def _release_step(self, h: HandFeatures, t: float) -> None:
        """One frame of the engaged hand in a non-pointing pose (also called on fist frames)."""
        if (not self._engaged or h.hand_id != self._clutch_hand or h.hand_id in self._pinched
                or self._eng is not None or not _release_pose(h)):
            return   # a pinch curls the index; unknown / mixed states keep (a pending release stays frozen)
        if self._release_since is None:
            self._release_since = t
        if t - self._release_since >= self._cfg.clutch_release_ms:
            self._disengage()

    def _rel_delta(self, t: float) -> Optional[tuple[float, float]]:
        a = self._anchor_now
        if a is None:
            return None
        self._rel_used = True
        return self._rel.step(t, a[0], a[1], _clamp(self._cfg.pointer_speed, 0.5, 2.0))

    def _rel_move_cursor(self, t: float) -> Optional[bool]:
        """Apply this frame's relative motion to the OS cursor. None: nothing to move, True: moved,
        False: the MOVE_POINTER was refused."""
        d = self._rel_delta(t)
        if d is None or self._fpos is None:
            return None
        self._fpos, target = advance(self._fpos, d, self._mapping_monitors())
        if target is None or target == self._pointer:
            return None
        if self._dispatch(ActionKind.MOVE_POINTER, t, x=target[0], y=target[1]):
            self._pointer = target
            return True
        return False

    # ------------------------------------------------------------ pinch re-arm / resolution

    def _rearm_track(self, key: str, hand_id: int, pinched: bool, distance: float) -> None:
        r = self._rearm.get(key)
        if r is not None and r[0] == hand_id and not pinched and math.isfinite(distance):
            r[2] = max(r[2], distance)

    def _pinch_ended(self, key: str, hand_id: int, t: float) -> None:
        # Rejected/unresolved contacts have produced no input and must not disarm a later real tap.
        if key in self._rearm:
            self._rearm[key] = [float(hand_id), t, 0.0]

    def _armed(self, key: str, hand_id: int, t: float) -> bool:
        """False for a re-close right after a release that never opened clearly (threshold flicker)."""
        r = self._rearm.get(key)
        if r is None or r[0] != hand_id:
            return True
        cfg = self._cfg
        return r[2] >= cfg.pinch_rearm_open_pu or t - r[1] >= cfg.pinch_rearm_ms

    def _pinch_vote(self, dom: HandFeatures) -> tuple[Optional[str], Optional[str]]:
        """(vote, state vote) of one frame, (None, None) when neither tip touches the thumb. Vote:
        decisive finger states, else the clearly nearer tip; ties retain the onset vote."""
        di, dm = dom.pinch_distance, self._middle.distance
        on = self._cfg.right_pinch_on_pu
        if not (min(di, dm) <= on):
            return None, None
        sv = _state_vote(dom)
        if sv is not None:
            return sv, sv
        m = self._cfg.pinch_resolve_margin_pu
        if di + m < dm:
            return "left", None
        if dm + m < di:
            return "right", None
        return None, None

    def _right_start_ok(self, dom: HandFeatures, t: float) -> bool:
        """Thumb+middle pose. Never the pointing pose or a fist (ring and little curled). Index
        EXTENDED or BENT with ring or little EXTENDED passes; unsure fingers pass when the hand was
        fully open just before."""
        s = {f.name: f.state for f in dom.fingers}
        idx, ring, lit = s.get(FingerName.INDEX), s.get(FingerName.RING), s.get(FingerName.LITTLE)
        if _outer_curled(dom):
            return False
        if idx in (FingerState.EXTENDED, FingerState.BENT) and FingerState.EXTENDED in (ring, lit):
            return True
        o = self._open_seen
        return o is not None and o[0] == dom.hand_id and 0.0 <= t - o[1] <= self._cfg.right_open_lookback_ms

    def _is_pinch_pose(self, h: HandFeatures) -> bool:
        """A pinch, even when the other three fingers are bent (all five may read BENT): the index is
        not fully curled (a real fist curls it fully) and either the thumb and index tips are
        together or this hand's left-button pinch is still running (release frames: tips apart
        before the debounced PINCH_END, fingers still curled)."""
        curl = next((f.curl for f in h.fingers if f.name is FingerName.INDEX), 1.0)
        if not curl < self._cfg.pinch_not_fist_index_curl:
            return False
        e = self._eng
        running = e is not None and e.hand_id == h.hand_id and e.kind in (
            _EngKind.MOUSE_PENDING, _EngKind.MOUSE_TAP, _EngKind.MOUSE_DRAG, _EngKind.GRAB)
        return running or h.pinch_distance <= self._cfg.pinch_not_fist_pu

    def _soft_reset(self, cancel_menu_hold: bool = True, why: str = "takip koptu") -> None:
        """Loss / clap-candidate reset: freeze, drop engagement, need fresh neutral."""
        self._index_tap.reset()
        self._reset_mouse_memory()
        had = self._eng is not None
        self._cancel_engagement(release=True, why=why)
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
                  steps: int = 0, value: float = 0.0, target: Optional[WindowTarget] = None,
                  command: str = "") -> bool:
        if self._mode is Mode.INSTRUMENT:
            return False   # defence in depth: INSTRUMENT never sends OS input (RELEASE_ALL uses _release)
        ok = self._guard.dispatch(Action(kind, self._epoch, capture_ms, x=x, y=y, steps=steps, value=value,
                                         target=target, command=command))
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
            if kind in (ActionKind.LEFT_CLICK, ActionKind.RIGHT_CLICK, ActionKind.LEFT_DOWN):
                self._last_cancel = ""
        elif kind in (ActionKind.LEFT_CLICK, ActionKind.RIGHT_CLICK, ActionKind.LEFT_DOWN):
            self._last_cancel = {ActionKind.LEFT_CLICK: "Tıklama iptal: komut reddedildi",
                                 ActionKind.RIGHT_CLICK: "Sağ tık iptal: komut reddedildi",
                                 ActionKind.LEFT_DOWN: "Sürükleme iptal: komut reddedildi"}[kind]
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
                self._disarm_fist(ev.hand_id)   # curled fingers left after a pinch are not a fist
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
                self._soft_reset(why="el çırpma algılandı")
                self._bump()
        if GestureKind.CLAP_CANDIDATE_ABORT in kinds:
            self._clap_pending = False
            self._need_neutral = True
            self._neutral_since = None

        if self._state is not ControlState.ACTIVE:
            return
        stale = now - frame.capture_ms > self._cfg.stale_ms
        if not stale and any(h.quality is Quality.USABLE for h in frame.hands):
            self._hand_seen_ms = now
        elif self._auto_pause_check(now):
            return
        self._expire_menu(now)

        if self._mode is Mode.INSTRUMENT:   # explicit early branch: no other mode's code runs here
            self._instrument_frame(frame, events, kinds, stale, now)
            return

        certain = not stale and not frame.identity_ambiguous
        if certain and self._pointer_geometry_frame(frame, events, now):
            return
        if certain and self._mouse_gap_frame(frame, events, now):
            self._tracking_ok = True
            return
        hands = [h for h in frame.hands if h.quality is Quality.USABLE and h.palm_scale_px > 0]
        if stale or frame.identity_ambiguous or not hands:
            if certain and self._pointer_gap_frame(frame, events, now):
                return
            self._tracking_lost()
            return
        self.watchdog.feed(frame.capture_ms)
        first = self._dominant(hands)
        dom_gap = first is None and self._dom_gap(frame, events)
        if first is not None:
            self._dom_ok_ms, self._dom_ok_id = frame.capture_ms, first.hand_id
        self._tracking_ok = first is not None or dom_gap

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
            if first is not None:
                self._release_step(first, frame.capture_ms)   # a held fist clutches like an open hand
            self._swallowed(events, first, None, "yumruk algılandı")
            self._mouse_interrupt("Yumruk: tıklama iptal", "yumruk algılandı")   # a fist never clicks or keeps a drag
            return

        if self._eng is not None and not all(h in present for h in self._eng.hands()):
            self._soft_reset()
            return

        dom = self._dominant(hands)
        rel = self._cfg.pointer_relative
        uv = pos = raw = palm_uv = None
        self._anchor_now = None
        targets = self._mapping_monitors()
        if dom is not None:
            if not rel:
                uv = normalize_camera_point(dom.index_tip_px[0], dom.index_tip_px[1], frame.width, frame.height,
                                            self._calib, self._cfg.mirror)
            # Move checks (click / window pinch) and the menu pointer use the palm center: the index
            # tip itself travels while a pinch closes and opens, which cancelled every click and moved
            # the menu pointer onto a neighbouring item at the selecting pinch.
            palm_uv = self._palm_uv(dom, frame)
            if palm_uv is not None:
                raw = map_normalized(palm_uv[0], palm_uv[1], targets)
        if rel:
            if dom is not None:
                if self._pointer is None:
                    self._set_pointer(self._initial_pointer())
                self._anchor_now = self._anchor(dom, frame)
                pos = self._pointer
            if self._anchor_now is None:
                self._smoother.reset()
            if not dom_gap:   # a short DEGRADED span of the engaged hand keeps the engagement (no motion)
                self._update_clutch(dom, frame.capture_ms)
        elif uv is not None:
            su = self._smoother.filter(frame.capture_ms, uv[0], uv[1])
            pos = map_normalized(su[0], su[1], targets)
        else:
            self._smoother.reset()

        mid_ev = None
        if self._mouse_on() and self._menu is None and dom is not None:
            mid_ev = self._middle.update(dom, frame.capture_ms, frame.width, frame.height)
            t = frame.capture_ms
            if any(ev.kind is GestureKind.PINCH_END and ev.hand_id == dom.hand_id for ev in events):
                self._pinch_ended("index", dom.hand_id, t)
            if mid_ev in (MID_END, MID_CANCEL):
                self._pinch_ended("middle", dom.hand_id, t)
                self._disarm_fist(dom.hand_id)
            self._rearm_track("index", dom.hand_id, dom.hand_id in self._pinched, dom.pinch_distance)
            self._rearm_track("middle", dom.hand_id, self._middle.pinched, self._middle.distance)
            if _open_hand(dom):
                self._open_seen = (dom.hand_id, t)
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

        if self._mode is Mode.COMMANDS:   # swipes and short pinches only; the pointer never moves
            self._commands_frame(frame, events, dom)
            return

        if self._need_neutral or dom is None or pos is None:
            if self._need_neutral:
                self._swallowed(events, dom, mid_ev, "takip yeni döndü, eli bir an açık tutun")
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

        # a thumb+middle start opens the same left/right decision; never from the pointing pose
        if mid_ev == MID_START and self._mouse_on():
            if self._right_start_ok(dom, frame.capture_ms):
                self._start_pending(dom, frame.capture_ms, pos)
                return
            if not _outer_curled(dom) and not _pointing_pose(dom):   # the pointing pose stays silent
                self._last_cancel = "Sağ tık iptal: parmaklar belirsiz, eli açıp yeniden deneyin"

        if rel:
            # the thumb tucked over the curled middle finger reads as a thumb+middle pinch in the
            # pointing pose itself, so only a thumb+index pinch (or an engagement) clutches here
            if self._engaged and dom.hand_id not in self._pinched:
                if self._release_since is None:
                    self._rel_move_cursor(frame.capture_ms)
                    self._dwell_step(frame.capture_ms)
                else:   # release candidate: frozen, but keep the reference current (no replay on resume)
                    self._rel_delta(frame.capture_ms)
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

    def _instrument_frame(self, frame: FrameFeatures, events: tuple[GestureEvent, ...], kinds: set[GestureKind],
                          stale: bool, now: float) -> None:
        """INSTRUMENT mode (ACTIVE): a separate engine turns the frames into sound. The controller only
        keeps loss / neutral bookkeeping and the mode menu, so the user can leave the mode. Nothing
        here dispatches OS input; only resets (RELEASE_ALL) reach the sink."""
        self._index_tap.reset()
        self._middle.reset()
        self._reset_fists()
        self._reset_mouse_memory()
        if self._eng is not None:            # cannot normally exist: _set_mode cancels engagements
            self._cancel_engagement(release=True, why="enstrüman kipi")
            self._release()
        if self._menu is not None and self._menu.kind is not MenuKind.MODE:
            self._close_menu()
        hands = [h for h in frame.hands if h.quality is Quality.USABLE and h.palm_scale_px > 0]
        if stale or frame.identity_ambiguous or not hands:
            self._tracking_lost()
            return
        self.watchdog.feed(frame.capture_ms)
        self._tracking_ok = True
        present = {h.hand_id for h in hands}
        for hid in [h for h in self._pinched if h not in present]:
            del self._pinched[hid]
        if not self._pinched:
            self._zoom_needs_release = False
        if self._pinched or self._clap_pending:
            self._neutral_since = None
        else:
            if self._neutral_since is None:
                self._neutral_since = frame.capture_ms
            if frame.capture_ms - self._neutral_since >= self._cfg.neutral_ms or GestureKind.NEUTRAL in kinds:
                self._need_neutral = False
        if self._clap_pending:
            return
        dom = self._dominant(hands)
        palm_uv = self._palm_uv(dom, frame) if dom is not None else None
        if self._menu is not None:
            self._menu_frame(frame, events, dom, palm_uv, now)
        elif GestureKind.MENU_DWELL_COMPLETE in kinds and not self._need_neutral and not self._pinched:
            # a pinching hand is drawing or moving a string: never interrupt it with the menu
            self._open_mode_menu(dom, palm_uv, now)

    def _pointer_geometry_frame(self, frame: FrameFeatures, events: tuple[GestureEvent, ...], now: float) -> bool:
        """Keep an already engaged pointer moving through a brief finger-only geometry failure.

        Session 2026-11-14 23:38: 82 bone_ratio frames, 73 still with index EXTENDED.
        Palm/identity faults remain excluded. This path never starts gestures or feeds the loss
        watchdog: a fully usable capture must still arrive within the original 200 ms limit.
        Untagged degraded frames retain the conservative freeze behavior.
        """
        if (not self._cfg.pointer_relative or self._mode is not Mode.POINTER or not self._engaged
                or self._eng is not None or self._menu is not None or self._need_neutral
                or self._clap_pending or self._release_since is not None or self._pinched or events):
            return False
        last = self.watchdog.last_usable_ms
        if (last is None or not self.watchdog.armed
                or not 0.0 <= now - last < self._cfg.loss_timeout_ms):
            return False
        dom = self._dominant(frame.hands)
        if (dom is None or dom.hand_id != self._clutch_hand or dom.quality is not Quality.DEGRADED
                or not math.isfinite(dom.palm_scale_px) or dom.palm_scale_px <= 0
                or not _pointing_pose(dom) or not math.isfinite(dom.pinch_distance)
                or dom.pinch_distance < self._cfg.right_pinch_off_pu
                or any(h.hand_id != dom.hand_id and h.handedness is not Handedness.LEFT for h in frame.hands)):
            return False
        reasons, frame_reasons = getattr(frame, "reasons", ({}, ()))
        if set(reasons.get(dom.hand_id, ())) != {"bone_ratio"} or frame_reasons:
            return False
        anchor = self._anchor(dom, frame)
        if anchor is None:
            return False
        self._anchor_now = anchor
        self._tracking_ok = True
        self._rel_move_cursor(frame.capture_ms)
        return True

    def _dom_gap(self, frame: FrameFeatures, events: tuple[GestureEvent, ...]) -> bool:
        """The engaged dominant hand is present with the same id but DEGRADED, its last usable frame
        is less than loss_timeout_ms old, no other right / unknown hand, no event of that hand, and
        no engagement or menu running. Such a short span keeps the pointer engaged without moving
        it; the relative motion re-anchors on recovery. Longer spans behave as before."""
        hid, last = self._clutch_hand, self._dom_ok_ms
        if (not self._engaged or not self._cfg.pointer_relative or hid is None or last is None
                or self._eng is not None or self._menu is not None
                or not 0.0 <= frame.capture_ms - last < self._cfg.loss_timeout_ms):
            return False
        mine = [h for h in frame.hands if h.hand_id == hid]
        if len(mine) != 1 or mine[0].quality is not Quality.DEGRADED or mine[0].handedness is not Handedness.RIGHT:
            return False
        if any(h.hand_id != hid and h.handedness is not Handedness.LEFT for h in frame.hands):
            return False
        return not any(ev.hand_id == hid for ev in events)

    def _idle_gap(self, frame: FrameFeatures, events: tuple[GestureEvent, ...]) -> bool:
        """POINTER pinch mouse, nothing running (no engagement, no menu): the last usable dominant hand
        is present with the same id but DEGRADED for less than loss_timeout_ms, no other right /
        unknown hand, no event of it. Skipping such a frame keeps the thumb+middle recognizer and the
        re-arm memory, so a pinch closing through it still starts (session 2026-11-14: 14 of 27 long
        gaps began while a pinch closed). Nothing is held here; longer spans reset as before."""
        hid, last = self._dom_ok_id, self._dom_ok_ms
        if (self._eng is not None or self._menu is not None or not self._mouse_on() or hid is None
                or last is None or not 0.0 <= frame.capture_ms - last < self._cfg.loss_timeout_ms):
            return False
        mine = [h for h in frame.hands if h.hand_id == hid]
        if len(mine) != 1 or mine[0].quality is not Quality.DEGRADED or mine[0].handedness is not Handedness.RIGHT:
            return False
        if any(h.hand_id != hid and h.handedness is not Handedness.LEFT for h in frame.hands):
            return False
        return not any(ev.hand_id == hid for ev in events)

    def _pointer_gap_frame(self, frame: FrameFeatures, events: tuple[GestureEvent, ...], now: float) -> bool:
        """True: no usable hand, but this is a tolerated short gap of the engaged pointer hand; the
        frame is skipped (identity certain, checked by the caller; the watchdog still bounds it)."""
        last = self.watchdog.last_usable_ms
        if last is None or not self.watchdog.armed or now - last >= self._cfg.loss_timeout_ms:
            return False
        if not (self._dom_gap(frame, events) or self._idle_gap(frame, events)):
            return False
        self._smoother.reset()
        self._rel.reset()
        self._tracking_ok = True
        return True

    def _tracking_lost(self) -> None:
        self._tracking_ok = False
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

    def _disarm_fist(self, hand_id: int) -> None:
        """A fist must again be made from a hand held open (200 ms) after any pinch."""
        self._fist_ready.discard(hand_id)
        self._fist_open.pop(hand_id, None)

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
            # a pinch with the other three fingers curled reads all five BENT: it is not a fist
            closed = all(state is FingerState.BENT for state in states.values()) and not self._is_pinch_pose(hand)
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
            self._cancel_engagement(release=True, why="yumruk algılandı")
            target = self._windows.foreground_window() if hand.handedness is Handedness.RIGHT else None
            self._fist_candidate = (hand.hand_id, hand.handedness, frame.capture_ms, target)
            self._notice = 'Sağ yumruk: küçültmek için tut' if hand.handedness is Handedness.RIGHT else 'Sol yumruk: geri açmak için tut'
            return True
        if frame.capture_ms - candidate[2] < _FIST_HOLD_MS:
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

    def _swallowed(self, events: tuple[GestureEvent, ...], dom: Optional[HandFeatures], mid_ev: Optional[str],
                   why: str) -> None:
        """A pinch start of the pointer hand that this frame refuses outright leaves its reason."""
        if dom is None or not self._mouse_on() or self._eng is not None:
            return
        if any(ev.kind is GestureKind.PINCH_START and ev.hand_id == dom.hand_id for ev in events):
            self._last_cancel = f"Tıklama iptal: {why}"
        elif mid_ev == MID_START and not _outer_curled(dom) and not _pointing_pose(dom):
            self._last_cancel = f"Sağ tık iptal: {why}"   # the pointing pose's thumb contact stays silent

    def _block(self, e: _Eng, notice: str) -> None:
        e.kind = _EngKind.BLOCKED
        self._notice = notice

    # ------------------------------------------------------------ COMMANDS mode / dwell click

    def _command_profile(self) -> str:
        """Concrete swipe profile: the configured one, or for "auto" the foreground process's."""
        setting = self._cfg.swipe_profile
        name: Optional[str] = None
        if setting not in PROFILES and self._process_names is not None:
            try:
                fg = self._windows.foreground_window()
                if fg is not None:
                    name = self._process_names.process_name(fg.pid)
            except Exception:
                name = None
        return resolve_profile(setting, name)

    def _send_command(self, cmd: KeyCommand, t: float, profile: str) -> None:
        self._profile_active = profile
        if self._dispatch(ActionKind.KEY_COMMAND, t, command=cmd.value):
            self._last_command = cmd.value
            self._command_seq += 1
            self._notice = f"Komut: {COMMAND_LABELS.get(cmd, cmd.value)}"
        else:
            self._notice = "Komut gönderilemedi"

    def _commands_frame(self, frame: FrameFeatures, events: tuple[GestureEvent, ...],
                        dom: Optional[HandFeatures]) -> None:
        """COMMANDS mode, ACTIVE, no menu / engagement / clap candidate: feed the swipe recognizer
        with the open dominant hand; a dominant PINCH_START opens a short-pinch command candidate."""
        if dom is None or self._need_neutral:
            return
        for ev in events:
            if ev.kind is GestureKind.PINCH_START and ev.hand_id == dom.hand_id:
                self._eng = _Eng(_EngKind.CMD_PINCH, dom.hand_id, ev.t_ms, palm0=dom.palm_center_px)
                return
        if dom.hand_id in self._pinched:
            return
        self._swipe_fed = True
        d = self._swipe.update(frame.capture_ms, dom)
        if d is not None:
            profile = self._command_profile()
            self._send_command(swipe_command(profile, d), frame.capture_ms, profile)

    def _cmd_pinch_frame(self, e: _Eng, ends: list[GestureEvent], hand: Optional[HandFeatures],
                         t: float) -> None:
        cfg = self._cfg
        moved = (hand is not None and e.palm0 is not None and hand.palm_scale_px > 0
                 and math.dist(hand.palm_center_px, e.palm0) / hand.palm_scale_px > cfg.mouse_drag_move_palm)
        if ends:
            self._eng = None
            if moved:
                self._notice = "Komut iptal: el fazla hareket etti"
            elif ends[0].t_ms - e.t0 > cfg.click_max_ms:
                self._notice = "Komut iptal: uzun tutuldu"
            else:
                profile = self._command_profile()
                self._send_command(pinch_command(profile), t, profile)
        elif moved:
            self._block(e, "Komut iptal: el fazla hareket etti")
        elif t - e.t0 > cfg.click_max_ms:
            self._block(e, "Komut iptal: uzun tutuldu")

    def _dwell_step(self, t: float) -> None:
        """POINTER, relative, engaged, cursor following, no pinch / engagement / menu (caller)."""
        cfg = self._cfg
        if not cfg.dwell_click or self._mode is not Mode.POINTER or self._eng is not None or self._menu is not None:
            return
        self._dwell_fed = True
        hit = self._dwell.update(t, self._pointer, cfg.dwell_ms)
        if hit is None:
            return
        if self._dispatch(ActionKind.LEFT_CLICK, t, x=hit[0], y=hit[1]):
            self._set_pointer(hit)
            self._notice = "Bekleme tıklaması: sol tık"

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
        if not cfg.pointer_relative:   # relative: the cursor was clutched while the pinch closed
            op = self._open_ptr.get("index" if left else "middle")
            if op is not None and 0.0 <= t - op[0] <= cfg.pinch_latch_lookback_ms:
                return op[1]
        return self._pointer if self._pointer is not None else pos

    def _double_tap(self, dom: HandFeatures, t: float) -> bool:
        """Second tap of a double click: a thumb+index pinch of the same hand starting
        double_tap_min_gap_ms..double_click_window_ms after a click's release, palm near the click
        place, is armed without the wide re-arm opening (session 2026-11-14: second taps reopened only
        to 0.53-0.78 pu after 281-485 ms and all were refused; threshold flicker re-closes within
        125-140 ms)."""
        lt, r, cfg = self._last_tap, self._rearm.get("index"), self._cfg
        return (lt is not None and r is not None and r[0] == dom.hand_id
                and cfg.double_tap_min_gap_ms <= t - lt[0] <= cfg.double_click_window_ms
                and math.dist(dom.palm_center_px, lt[2]) / dom.palm_scale_px <= cfg.mouse_drag_move_palm)

    def _start_pending(self, dom: HandFeatures, t: float, pos: tuple[int, int]) -> None:
        """Pinch onset (thumb+index or thumb+middle start): hold the pointer, decide left/right."""
        e = _Eng(_EngKind.MOUSE_PENDING, dom.hand_id, t, palm0=dom.palm_center_px, pos0=pos,
                 anchor0=self._anchor_now, middle=True, onset=t)
        e.vote, e.state_vote = self._pinch_vote(dom)
        e.index_armed = self._armed("index", dom.hand_id, t) or self._double_tap(dom, t)
        e.middle_armed = self._armed("middle", dom.hand_id, t)
        e.right_ok0 = self._right_start_ok(dom, t)
        if e.vote is None and self._middle.distance > self._cfg.right_pinch_on_pu:
            e.vote = "left" if dom.hand_id in self._pinched else "right"
        self._eng = e
        if self._grab_contact(dom):   # the grab is decided before any left/right logic
            self._start_grab(e, dom, t, pos)

    def _grab_contact(self, dom: HandFeatures, held: bool = False) -> bool:
        """Thumb tip at the index tip AND the middle tip (grab). Onset (and the confirming frame): the
        debounced thumb+index pinch is held and both distances are at or under the pinch-on
        threshold; held: the thumb+index pinch has not ended (its pinch-off hysteresis) and the
        middle distance is under the pinch-off threshold. Real left pinches kept thumb-middle >=
        0.62 pu and the pointing pose keeps thumb-index wide open (recording 2026-11-12), so neither
        is a grab; recorded right pinches touched the index tip for single frames at their release,
        which never reaches a debounced thumb+index pinch. A fist is not a grab either: index and
        middle must not be fully curled (pinch_not_fist_index_curl)."""
        cfg = self._cfg
        on, off = cfg.right_pinch_on_pu, cfg.right_pinch_off_pu
        di, dm = dom.pinch_distance, self._middle.distance
        if dom.hand_id not in self._pinched:
            return False
        if not (di < off and dm < off if held else (di <= on and dm <= on)):
            return False
        curls = {f.name: f.curl for f in dom.fingers}
        lim = cfg.pinch_not_fist_index_curl
        return curls.get(FingerName.INDEX, 0.0) < lim and curls.get(FingerName.MIDDLE, 0.0) < lim

    def _start_grab(self, e: _Eng, dom: HandFeatures, t: float, pos: Optional[tuple[int, int]]) -> None:
        """Pending / tap / right-tap candidate -> GRAB: never a click or a long press any more."""
        ref = e.pos0 if e.pos0 is not None else pos
        latched = e.latched
        if latched is None and ref is not None:
            latched = self._mouse_latch(e.onset, ref, dom, left=True)
        if latched is None:
            self._session_block(e, "Sürükleme iptal edildi", "Sürükleme iptal: imleç noktası yok")
            return
        e.kind, e.latched, e.grab_since, e.open_since = _EngKind.GRAB, latched, t, None
        e.t0 = e.onset
        self._last_tap = None
        self._notice = "Kavrama: sürükleme hazırlanıyor"

    def _grab_holds(self, e: _Eng, dom: HandFeatures, t: float) -> bool:
        """False once the grab opened: one fingertip beyond the pinch-off threshold for
        right_pinch_debounce_ms (a single slipped frame keeps the button down)."""
        if self._grab_contact(dom, held=True):
            e.open_since = None
            if e.kind is _EngKind.GRAB and e.grab_since is None:
                e.grab_since = t
            return True
        if e.kind is _EngKind.GRAB:
            e.grab_since = None  # confirmation requires continuous contact
        if e.open_since is None:
            e.open_since = t
        return t - e.open_since < self._cfg.right_pinch_debounce_ms

    def _long_press(self, e: _Eng, dom: HandFeatures, t: float) -> None:
        """Still thumb+index pinch held right_long_press_ms: RIGHT_CLICK now, the release adds nothing."""
        assert e.latched is not None
        ok = self._dispatch(ActionKind.RIGHT_CLICK, t, x=e.latched[0], y=e.latched[1])
        if ok:
            self._set_pointer(e.latched)
            self._rearm["index"] = [float(e.hand_id), t, dom.pinch_distance]
        self._last_tap = None
        self._eng = _Eng(_EngKind.BLOCKED, e.hand_id, e.t0, middle=True, text="Sağ tık" if ok else "")
        self._notice = "Sağ tık (uzun basma)" if ok else "Sağ tık gönderilemedi"

    def _session_block(self, e: _Eng, notice: str, cancel: str = "") -> None:
        """No click from this physical pinch: wait until both pinches are released."""
        self._eng = _Eng(_EngKind.BLOCKED, e.hand_id, e.t0, middle=True)
        self._notice = notice
        if cancel:
            self._last_cancel = cancel

    def _decide_pinch(self, e: _Eng, dom: HandFeatures, t: float, pos: Optional[tuple[int, int]],
                      index_ended: bool, mid_ev: Optional[str]) -> None:
        """MOUSE_PENDING -> MOUSE_TAP / RIGHT_TAP / BLOCKED / nothing (stays pending)."""
        cfg = self._cfg
        index_on = dom.hand_id in self._pinched
        middle_on = self._middle.pinched
        released = index_ended or mid_ev in (MID_END, MID_CANCEL)
        if not e.decision_done:
            v, sv = self._pinch_vote(dom)
            if v is not None:
                e.vote = v
            if sv is not None:
                e.state_vote = sv
            if not released and t - e.t0 < cfg.pinch_decide_ms:
                return
            e.decision_done = True
        side = e.state_vote or e.vote
        if side is None:
            self._session_block(e, "Parmak kararı belirsiz: tıklama yok", "Kararsız: iki parmak da temas etti")
            return
        ref = e.pos0 if e.pos0 is not None else pos
        if side == "left" and (index_on or index_ended) and ref is not None:
            if not e.index_armed:
                self._session_block(e, "Tek tık: önce parmakları açın",     # threshold flicker
                                    "Tıklama iptal: önce parmakları açın")
                return
            e.kind = _EngKind.MOUSE_TAP
            e.latched = self._mouse_latch(e.t0, ref, dom, left=True)
            return
        if side == "right" and (middle_on or mid_ev == MID_END) and ref is not None:
            # pose judged at the onset (or now); a later curl is handled by the RIGHT_TAP curl rule
            if not (e.right_ok0 or self._right_start_ok(dom, t)):
                self._session_block(e, "Sağ tık iptal edildi", "Sağ tık iptal: el duruşu uygun değil")
            elif not e.middle_armed:
                self._session_block(e, "Tek sağ tık: önce parmakları açın", "Sağ tık iptal: önce parmakları açın")
            else:
                e.kind = _EngKind.RIGHT_TAP
                e.latched = self._mouse_latch(e.t0, ref, dom, left=False)
                if self._middle.start_ms is not None:
                    e.t0 = self._middle.start_ms
            return
        # the decided finger's own pinch has not started (yet)
        if not index_on and not middle_on:
            self._eng = None
            self._notice = "Tıklama iptal edildi"
            self._last_cancel = "Tıklama iptal: parmak teması kısa kaldı"
        elif t - e.t0 >= cfg.pinch_decide_max_ms:
            self._session_block(e, "Tıklama iptal edildi", "Tıklama iptal: karar zaman aşımı")

    def _mouse_gap_frame(self, frame: FrameFeatures, events: tuple[GestureEvent, ...], now: float) -> bool:
        """True: this frame is a short tracking gap inside a pinch-mouse engagement and is skipped,
        keeping the pending tap, the held left button or the right tap. Only the same hand id, present
        and DEGRADED (identity certain, the caller checked ambiguity and staleness), no second right
        hand, no pinch event of that hand, and only while the watchdog has not expired (last usable
        capture less than loss_timeout_ms ago; the watchdog then releases everything as before). A
        missing hand or an ambiguous frame still cancels: continuity of identity is unproven there."""
        e = self._eng
        if e is None or not (e.kind in _MOUSE_KINDS or (e.kind is _EngKind.BLOCKED and e.middle)):
            return False
        last = self.watchdog.last_usable_ms
        if last is None or not self.watchdog.armed or now - last >= self._cfg.loss_timeout_ms:
            return False
        mine = [h for h in frame.hands if h.hand_id == e.hand_id]
        if len(mine) != 1 or mine[0].quality is not Quality.DEGRADED or mine[0].handedness is not Handedness.RIGHT:
            return False
        if any(h.hand_id != e.hand_id and h.handedness is not Handedness.LEFT for h in frame.hands):
            return False
        if any(ev.hand_id == e.hand_id for ev in events):
            return False
        self._smoother.reset()
        self._rel.reset()   # re-anchor on recovery; never replay movement across an invisible interval
        return True

    def _left_up(self, e: _Eng, capture_ms: float) -> None:
        p = e.last_pos if e.last_pos is not None else self._pointer
        if p is None or not self._dispatch(ActionKind.LEFT_UP, capture_ms, x=p[0], y=p[1]):
            self._release()   # a dropped LEFT_UP must still free the button

    def _mouse_interrupt(self, notice: str, why: str = "") -> None:
        """End a pinch-mouse engagement without a click; a held button is released."""
        e = self._eng
        if e is None or e.kind not in _MOUSE_KINDS:
            return
        if e.kind is _EngKind.MOUSE_DRAG:
            self._left_up(e, self._clock.now_ms())
        self._eng = _Eng(_EngKind.BLOCKED, e.hand_id, e.t0, middle=True)
        self._last_tap = None
        self._notice = notice
        self._note_cancel(e, why or "iptal edildi")

    def _begin_drag(self, e: _Eng, t: float) -> None:
        assert e.latched is not None
        e.kind = _EngKind.MOUSE_DRAG   # set first: any failure below takes the release path
        e.last_pos = e.latched
        self._last_tap = None
        if self._dispatch(ActionKind.LEFT_DOWN, t, x=e.latched[0], y=e.latched[1]):
            self._set_pointer(e.latched)
            self._notice = "Sürükleme: sol tuş basılı"
        else:
            self._mouse_interrupt("Sürükleme başlatılamadı", "komut reddedildi")

    def _rel_drag_step(self, e: _Eng, t: float) -> None:
        moved = self._rel_move_cursor(t)
        if moved:
            e.last_pos = self._pointer
        elif moved is False:
            self._mouse_interrupt("Sürükleme iptal: imleç taşınamadı", "imleç taşınamadı")

    def _mouse_frame(self, frame: FrameFeatures, events: tuple[GestureEvent, ...], dom: Optional[HandFeatures],
                     pos: Optional[tuple[int, int]], mid_ev: Optional[str]) -> None:
        e = self._eng
        assert e is not None
        cfg = self._cfg
        t = frame.capture_ms
        same = dom is not None and dom.hand_id == e.hand_id
        if e.kind is _EngKind.BLOCKED:   # pinch-mouse session refused: wait until both pinches are released
            # The guarded pointing pose tucks the thumb against the middle tip indefinitely;
            # that geometric contact is not a right pinch and must not block deliberate left doubles.
            if not same or ((not self._middle.pinched or _pointing_pose(dom)) and dom.hand_id not in self._pinched):
                self._eng = None
            return
        if not same:
            self._mouse_interrupt("İşaretçi eli belirsiz: tıklama iptal", "işaretçi eli belirsiz")
            return
        assert dom is not None
        moved = (e.palm0 is not None
                 and math.dist(dom.palm_center_px, e.palm0) / dom.palm_scale_px > cfg.mouse_drag_move_palm)
        ends = [ev for ev in events if ev.kind is GestureKind.PINCH_END and ev.hand_id == e.hand_id]

        # the second fingertip joining soon after the onset makes it a grab, before any click
        if (e.kind in (_EngKind.MOUSE_PENDING, _EngKind.MOUSE_TAP, _EngKind.RIGHT_TAP) and not ends
                and t - e.onset <= cfg.pinch_decide_ms and self._grab_contact(dom)):
            self._start_grab(e, dom, t, pos)
            if self._eng is not e:
                return

        if e.kind is _EngKind.GRAB:
            if ends or not self._grab_holds(e, dom, t):
                self._session_block(e, "Sürükleme iptal edildi", "Sürükleme iptal: kavrama tamamlanmadı")
                return
            if (e.grab_since is not None and t - e.grab_since >= cfg.grab_confirm_ms
                    and e.open_since is None and self._grab_contact(dom)):
                e.grab = True
                self._begin_drag(e, t)
                if cfg.pointer_relative and self._eng is e and e.anchor0 is not None:
                    self._rel.anchor(max(e.t0, t - 200.0), e.anchor0[0], e.anchor0[1])
                    self._rel_drag_step(e, t)
            return

        if e.kind is _EngKind.MOUSE_PENDING:
            self._decide_pinch(e, dom, t, pos, bool(ends), mid_ev)
            if self._eng is not e or e.kind is _EngKind.MOUSE_PENDING:
                return
            # decided: the chosen tap handles this frame too (a release inside the window clicks)

        if e.kind is _EngKind.RIGHT_TAP:
            # decided: the thumb+index pinch is ignored until release
            right_moved = (e.palm0 is not None and math.dist(dom.palm_center_px, e.palm0)
                           / dom.palm_scale_px > cfg.right_cancel_move_palm)
            # Ring+little curled: the hand is going into the pointing pose (every such cancel of the
            # 2026-11-14 session was followed by an engaged, moving pointer within 125-140 ms) or a
            # fist. A curl shorter than right_curl_cancel_ms is state flicker during contact; the
            # release frame itself must not be curled.
            curled = _outer_curled(dom)
            e.curl_since = (e.curl_since if e.curl_since is not None else t) if curled else None
            curl_long = e.curl_since is not None and t - e.curl_since >= cfg.right_curl_cancel_ms
            if mid_ev == MID_CANCEL or (mid_ev is None and not self._middle.pinched):
                self._eng = None
                self._notice = "Sağ tık iptal edildi"
                self._last_cancel = "Sağ tık iptal: temas koptu"
            elif curl_long or (curled and mid_ev == MID_END):
                self._mouse_interrupt("Sağ tık iptal edildi", "parmaklar büküldü")
            elif mid_ev == MID_END:
                self._eng = None
                if not right_moved and t - e.t0 <= cfg.right_hold_max_ms and e.latched is not None:
                    if self._dispatch(ActionKind.RIGHT_CLICK, t, x=e.latched[0], y=e.latched[1]):
                        self._set_pointer(e.latched)
                        self._rearm["middle"] = [float(e.hand_id), t, self._middle.distance]
                    self._notice = "Sağ tık"
                else:
                    self._notice = "Sağ tık iptal edildi"
                    self._last_cancel = ("Sağ tık iptal: el fazla hareket etti" if right_moved
                                         else "Sağ tık iptal: uzun tutuldu")
                if dom.hand_id in self._pinched:
                    self._session_block(e, self._notice)
            elif right_moved or t - e.t0 > cfg.right_hold_max_ms:
                self._mouse_interrupt("Sağ tık iptal edildi", "el fazla hareket etti" if right_moved else "uzun tutuldu")
            return

        if e.kind is _EngKind.MOUSE_TAP:
            if ends:
                self._eng = None
                if moved and e.latched is not None:
                    self._eng = e
                    self._begin_drag(e, t)
                    self._eng = None
                    self._left_up(e, t)
                    if e.dispatched:
                        self._rearm["index"] = [float(e.hand_id), t, dom.pinch_distance]
                elif e.latched is None:
                    self._notice = "Tıklama iptal edildi"
                    self._last_cancel = "Tıklama iptal: tıklama noktası yok"
                elif ends[0].t_ms - e.t0 < cfg.right_long_press_ms:
                    if self._dispatch(ActionKind.LEFT_CLICK, t, x=e.latched[0], y=e.latched[1]):
                        self._set_pointer(e.latched)
                        self._last_tap = (ends[0].t_ms, e.latched, e.palm0 or dom.palm_center_px)
                        self._rearm["index"] = [float(e.hand_id), t, dom.pinch_distance]
                    self._notice = "Sol tık"
                else:   # the hold reached the long press on its release frame (low frame rate)
                    self._eng = e
                    self._long_press(e, dom, t)
                    self._eng = None
                if self._middle.pinched and not _pointing_pose(dom):
                    self._session_block(e, self._notice)
            elif moved:
                # motion drag: palm travel while pinched, before the long press fired
                self._begin_drag(e, t)          # keep the travel made during the candidate
                if cfg.pointer_relative and self._eng is e and e.anchor0 is not None:
                    self._rel.anchor(max(e.t0, t - 200.0), e.anchor0[0], e.anchor0[1])
                    self._rel_drag_step(e, t)
            elif t - e.t0 >= cfg.right_long_press_ms and e.latched is not None:
                self._long_press(e, dom, t)     # still hand held long enough: right click now
            return

        # MOUSE_DRAG: the pointer follows the hand (relative: the anchor, whatever the fingers do;
        # absolute: the fingertip relative to its drag reference pos0)
        if ends or (e.grab and not self._grab_holds(e, dom, t)):
            self._eng = None
            self._left_up(e, t)
            if ends or dom.hand_id in self._pinched:
                self._rearm["index"] = [float(e.hand_id), t, dom.pinch_distance]
            self._notice = "Sürükleme bitti"
            if not ends and (dom.hand_id in self._pinched or self._middle.pinched):
                self._session_block(e, self._notice)   # a pinch still held after the grab opened: no click
            return
        if cfg.pointer_relative:
            self._rel_drag_step(e, t)
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
            self._mouse_interrupt("Sürükleme iptal: imleç taşınamadı", "imleç taşınamadı")

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
                # left or right is decided over the next frames (_decide_pinch), not by arrival order
                self._start_pending(dom, ev.t_ms, pos)
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

        if e.kind is _EngKind.CMD_PINCH:
            self._cmd_pinch_frame(e, ends, hand, frame.capture_ms)
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
                    self._last_cancel = ("Tıklama iptal: el fazla hareket etti" if e.moved
                                         else "Tıklama iptal: uzun tutuldu")
            elif frame.capture_ms - e.t0 > cfg.click_max_ms:
                self._block(e, "Tıklama iptal edildi (uzun tutma)")
                self._last_cancel = "Tıklama iptal: uzun tutuldu"
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
                e.fpos = (float(pos[0]), float(pos[1]))
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
            if cfg.pointer_relative:   # the window follows the hand anchor with the pointer gain
                d = self._rel_delta(frame.capture_ms)
                if d is not None and e.fpos is not None:
                    e.fpos, p = advance(e.fpos, d, self._monitors)
                    pos = p if p is not None else e.last_pos
                else:
                    pos = e.last_pos
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
        e = self._eng
        if e is not None:
            if e.text:
                return e.text
            if e.kind is _EngKind.MOUSE_TAP and now - e.t0 >= _LONG_PRESS_HINT_MS:
                return "Sağ tık için tutun"
            return _ENG_TEXT[e.kind]
        return ""
