"""Shared contracts between all modules. Change them deliberately: everything depends on this file.

Stdlib only. No camera, Qt, MediaPipe or Win32 imports here.

Units:
- time: monotonic milliseconds (float).
- Landmark x/y: normalized [0,1] on the UNMIRRORED camera frame. z: MediaPipe relative depth.
- *_px: camera pixels (x * width, y * height).
- "palm units": pixel distance divided by HandFeatures.palm_scale_px.
- Desktop coordinates: physical virtual-desktop pixels (may be negative).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Protocol, Sequence


class Handedness(Enum):
    LEFT = "left"
    RIGHT = "right"
    UNKNOWN = "unknown"


class Quality(Enum):
    USABLE = "usable"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


class FingerName(Enum):
    THUMB = "thumb"      # landmarks 1-4
    INDEX = "index"      # 5-8
    MIDDLE = "middle"    # 9-12
    RING = "ring"        # 13-16
    LITTLE = "little"    # 17-20


class FingerState(Enum):
    EXTENDED = "extended"
    BENT = "bent"
    UNKNOWN = "unknown"


class ControlState(Enum):
    PAUSED = "paused"
    ACTIVE = "active"
    CALIBRATING = "calibrating"
    FAULT = "fault"


class CameraState(Enum):
    OFF = "off"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"


class Mode(Enum):
    POINTER = "pointer"
    SCROLL = "scroll"
    ZOOM = "zoom"
    VOLUME = "volume"
    WINDOWS = "windows"
    COMMANDS = "commands"     # swipe/pinch -> keyboard and media commands (round 6)
    INSTRUMENT = "instrument" # virtual guitar strings -> audio only; never any OS input (round 7)
    DRAWING = "drawing"       # rotating 3D ink over the camera picture; never any OS input


# These modes never send OS input: the hands play or draw inside the app.
CANVAS_MODES = (Mode.INSTRUMENT, Mode.DRAWING)


class KeyCommand(Enum):
    """Named keyboard/media commands. Action.command carries the .value; the sink owns the key mapping."""
    NEXT = "next"                         # Right arrow (slides, PDF, photos)
    PREVIOUS = "previous"                 # Left arrow
    BROWSER_BACK = "browser_back"         # Alt+Left
    BROWSER_FORWARD = "browser_forward"   # Alt+Right
    TASK_VIEW = "task_view"               # Win+Tab
    SHOW_DESKTOP = "show_desktop"         # Win+D
    DESKTOP_LEFT = "desktop_left"         # Ctrl+Win+Left
    DESKTOP_RIGHT = "desktop_right"       # Ctrl+Win+Right
    MEDIA_PLAY_PAUSE = "media_play_pause"
    MEDIA_NEXT = "media_next"
    MEDIA_PREVIOUS = "media_previous"
    VOLUME_MUTE = "volume_mute"


# ---------- tracking output (camera.py / tracking.py produce) ----------

@dataclass(frozen=True)
class Landmark:
    x: float
    y: float
    z: float = 0.0


@dataclass(frozen=True)
class HandSample:
    handedness: Handedness
    handedness_score: float                 # classification score, NOT landmark accuracy
    landmarks: tuple[Landmark, ...]         # exactly 21
    world_landmarks: Optional[tuple[Landmark, ...]] = None


@dataclass(frozen=True)
class FrameSample:
    capture_ms: float
    inference_done_ms: float
    width: int
    height: int
    hands: tuple[HandSample, ...]           # 0..2, no stable identity yet
    forearms_crossed: Optional[bool] = None  # None when pose tracking is unavailable or disabled


# ---------- features output (features.py produces) ----------

@dataclass(frozen=True)
class FingerInfo:
    name: FingerName
    state: FingerState
    curl: float                             # 0.0 straight .. 1.0 fully curled


@dataclass(frozen=True)
class HandFeatures:
    hand_id: int                            # stable across frames while identity is certain
    handedness: Handedness
    quality: Quality
    palm_center_px: tuple[float, float]     # mean of MCP landmarks 5, 9, 13, 17
    palm_scale_px: float                    # > 0 when quality is USABLE
    fingers: tuple[FingerInfo, ...]         # 5 items, order: THUMB, INDEX, MIDDLE, RING, LITTLE
    pinch_distance: float                   # thumb tip to index tip, palm units
    index_tip_px: tuple[float, float]
    landmarks: tuple[Landmark, ...]         # the 21 source landmarks


@dataclass(frozen=True)
class FrameFeatures:
    capture_ms: float
    inference_done_ms: float
    width: int
    height: int
    hands: tuple[HandFeatures, ...]
    identity_ambiguous: bool                # True -> consumers reset continuous actions


@dataclass(frozen=True)
class PoseFrameFeatures(FrameFeatures):
    forearms_crossed: bool


# ---------- gesture output (gestures.py produces) ----------

class GestureKind(Enum):
    CLAP = "clap"
    CLAP_CANDIDATE_START = "clap_candidate_start"   # suppress ordinary output
    CLAP_CANDIDATE_ABORT = "clap_candidate_abort"
    PINCH_START = "pinch_start"                     # after debounce
    PINCH_END = "pinch_end"
    NEUTRAL = "neutral"                             # 200 ms usable, pinches released, no pending clap
    MENU_DWELL_COMPLETE = "menu_dwell_complete"     # non-dominant V pose held 500 ms


@dataclass(frozen=True)
class GestureEvent:
    kind: GestureKind
    t_ms: float                             # capture_ms of the sample that produced it
    hand_id: Optional[int] = None


# ---------- actions (controller.py produces, sinks consume) ----------

@dataclass(frozen=True)
class WindowTarget:
    hwnd: int
    pid: int


class ActionKind(Enum):
    MOVE_POINTER = "move_pointer"                   # x, y
    LEFT_CLICK = "left_click"                       # x, y latched at pinch start
    RIGHT_CLICK = "right_click"                     # x, y
    DOUBLE_CLICK = "double_click"                   # x, y
    LEFT_DOWN = "left_down"                         # x, y; left button held (drag start)
    LEFT_UP = "left_up"                             # x, y; left button released (drag end)
    SCROLL = "scroll"                               # steps (+ up), target
    ZOOM = "zoom"                                   # steps (+ in), target
    SET_VOLUME = "set_volume"                       # value 0.0..1.0
    WINDOW_DRAG_BEGIN = "window_drag_begin"         # target, x, y
    WINDOW_DRAG_MOVE = "window_drag_move"           # target, x, y
    WINDOW_DRAG_END = "window_drag_end"             # target
    WINDOW_MINIMIZE = "window_minimize"             # target
    WINDOW_RESTORE = "window_restore"               # restore a previously minimized target
    WINDOW_TOGGLE_MAXIMIZE = "window_toggle_maximize"
    WINDOW_MOVE_TO_OTHER_MONITOR = "window_move_to_other_monitor"
    WINDOW_CLOSE = "window_close"                   # normal close request only
    RELEASE_ALL = "release_all"                     # release every app-owned input
    KEY_COMMAND = "key_command"                     # command (KeyCommand value); press+release, never held


@dataclass(frozen=True)
class Action:
    kind: ActionKind
    epoch: int                              # sink drops actions whose epoch is not current
    capture_ms: float                       # sink drops actions older than 150 ms
    x: Optional[int] = None
    y: Optional[int] = None
    steps: int = 0
    value: float = 0.0
    target: Optional[WindowTarget] = None
    command: str = ""                       # KeyCommand value for KEY_COMMAND


class Clock(Protocol):
    def now_ms(self) -> float: ...


class ActionSink(Protocol):
    """Dry-run sink and the real Windows sink both implement this."""

    def dispatch(self, action: Action) -> bool: ...   # False = rejected or failed
    def release_all(self) -> None: ...                # must never raise


# ---------- OS adapters (windows/ implements, controller + ui consume) ----------

@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int


@dataclass(frozen=True)
class Monitor:
    bounds: Rect                            # physical pixels
    work_area: Rect
    dpi_scale: float                        # 1.0 = 96 DPI
    is_primary: bool


class DisplayProvider(Protocol):
    def monitors(self) -> Sequence[Monitor]: ...


class WindowQuery(Protocol):
    def eligible_window_at(self, x: int, y: int) -> Optional[WindowTarget]: ...
    def foreground_window(self) -> Optional[WindowTarget]: ...
    def is_valid(self, target: WindowTarget) -> bool: ...


class VolumeControl(Protocol):
    def get_volume(self) -> float: ...                # 0.0..1.0 of current default render endpoint
    def set_volume(self, value: float) -> bool: ...


class ProcessNames(Protocol):
    def process_name(self, pid: int) -> Optional[str]: ...   # lower-case exe name, e.g. "chrome.exe"
