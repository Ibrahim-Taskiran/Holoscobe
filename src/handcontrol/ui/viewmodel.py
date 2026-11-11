"""ViewModel data structures and thread-safe Qt bridge for the Holoscobe UI.

All user-facing labels are in Turkish. Code and comments are in English.
Only stdlib, handcontrol.contracts, and PySide6 (QtCore) are imported here.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Optional

from PySide6.QtCore import QObject, QThread, Signal, Slot

from handcontrol.contracts import (
    Action,
    ActionKind,
    CameraState,
    ControlState,
    FingerName,
    FingerState,
    FrameFeatures,
    Handedness,
    Mode,
    Quality,
)


class TrayIconState(Enum):
    """Four tray icon states required by the specification."""

    PAUSED = "paused"
    ACTIVE = "active"
    CALIBRATING = "calibrating"
    CAMERA_UNAVAILABLE = "camera_unavailable"


class OverlayMenuKind(Enum):
    """Overlay menu type currently displayed."""

    NONE = "none"
    MODE_MENU = "mode_menu"
    WINDOW_ACTION_MENU = "window_action_menu"


class WindowActionKind(Enum):
    """Actions available in the window action overlay menu."""

    MINIMIZE = "minimize"
    MAXIMIZE_RESTORE = "maximize_restore"
    MOVE_OTHER_MONITOR = "move_other_monitor"
    CLOSE = "close"


class FeedbackKind(Enum):
    """Short notification types displayed by the feedback OSD."""

    ACTIVATED = "activated"
    PAUSED = "paused"
    MODE_CHANGED = "mode_changed"
    VOLUME = "volume"
    CLOSE_CONFIRM = "close_confirm"
    INFO = "info"
    WARNING = "warning"


# ---------- Turkish user-facing label mappings ----------

MODE_LABELS_TR: dict[Mode, str] = {
    Mode.POINTER: "İmleç",
    Mode.SCROLL: "Kaydırma",
    Mode.ZOOM: "Yakınlaştırma",
    Mode.VOLUME: "Ses",
    Mode.WINDOWS: "Pencere",
}

CONTROL_STATE_LABELS_TR: dict[ControlState, str] = {
    ControlState.PAUSED: "Duraklatıldı",
    ControlState.ACTIVE: "Etkin",
    ControlState.CALIBRATING: "Kalibrasyon",
    ControlState.FAULT: "Hata",
}

CAMERA_STATE_LABELS_TR: dict[CameraState, str] = {
    CameraState.OFF: "Kapalı",
    CameraState.STARTING: "Başlatılıyor",
    CameraState.RUNNING: "Çalışıyor",
    CameraState.ERROR: "Kullanılamıyor",
}

TRAY_ICON_STATE_LABELS_TR: dict[TrayIconState, str] = {
    TrayIconState.PAUSED: "Duraklatıldı",
    TrayIconState.ACTIVE: "Etkin",
    TrayIconState.CALIBRATING: "Kalibrasyon",
    TrayIconState.CAMERA_UNAVAILABLE: "Kamera kullanılamıyor",
}

FINGER_NAME_LABELS_TR: dict[FingerName, str] = {
    FingerName.THUMB: "Başparmak",
    FingerName.INDEX: "İşaret",
    FingerName.MIDDLE: "Orta",
    FingerName.RING: "Yüzük",
    FingerName.LITTLE: "Serçe",
}

FINGER_STATE_LABELS_TR: dict[FingerState, str] = {
    FingerState.EXTENDED: "Açık",
    FingerState.BENT: "Bükülü",
    FingerState.UNKNOWN: "Belirsiz",
}

HANDEDNESS_LABELS_TR: dict[Handedness, str] = {
    Handedness.LEFT: "Sol El",
    Handedness.RIGHT: "Sağ El",
    Handedness.UNKNOWN: "Belirsiz El",
}

QUALITY_LABELS_TR: dict[Quality, str] = {
    Quality.USABLE: "Kullanılabilir",
    Quality.DEGRADED: "Düşük Kalite",
    Quality.UNKNOWN: "Belirsiz",
}

WINDOW_ACTION_LABELS_TR: dict[WindowActionKind, str] = {
    WindowActionKind.MINIMIZE: "Küçült",
    WindowActionKind.MAXIMIZE_RESTORE: "Büyüt / Geri Yükle",
    WindowActionKind.MOVE_OTHER_MONITOR: "Diğer Ekrana Taşı",
    WindowActionKind.CLOSE: "Kapat",
}

ACTION_KIND_LABELS_TR: dict[ActionKind, str] = {
    ActionKind.MOVE_POINTER: "İmleci Taşı",
    ActionKind.LEFT_CLICK: "Sol Tık",
    ActionKind.SCROLL: "Kaydır",
    ActionKind.ZOOM: "Yakınlaştır",
    ActionKind.SET_VOLUME: "Ses Seviyesini Ayarla",
    ActionKind.WINDOW_DRAG_BEGIN: "Pencere Sürüklemeyi Başlat",
    ActionKind.WINDOW_DRAG_MOVE: "Pencereyi Taşı",
    ActionKind.WINDOW_DRAG_END: "Pencere Sürüklemeyi Bitir",
    ActionKind.WINDOW_MINIMIZE: "Pencereyi Küçült",
    ActionKind.WINDOW_TOGGLE_MAXIMIZE: "Pencereyi Büyüt/Geri Yükle",
    ActionKind.WINDOW_MOVE_TO_OTHER_MONITOR: "Pencereyi Diğer Ekrana Taşı",
    ActionKind.WINDOW_CLOSE: "Pencereyi Kapat",
    ActionKind.RELEASE_ALL: "Tüm Girdileri Bırak",
}


def resolve_tray_icon_state(
    control_state: ControlState,
    camera_state: CameraState,
) -> TrayIconState:
    """Map control state and camera state to one of the four tray icon states."""
    if camera_state in (CameraState.OFF, CameraState.ERROR) or control_state == ControlState.FAULT:
        return TrayIconState.CAMERA_UNAVAILABLE
    if control_state == ControlState.CALIBRATING:
        return TrayIconState.CALIBRATING
    if control_state == ControlState.ACTIVE and camera_state == CameraState.RUNNING:
        return TrayIconState.ACTIVE
    return TrayIconState.PAUSED


def format_action_tr(action: Action) -> str:
    """Format a contracts.Action into a concise Turkish dry-run command description."""
    label = ACTION_KIND_LABELS_TR.get(action.kind, action.kind.value)
    parts: list[str] = [label]
    if action.x is not None and action.y is not None:
        parts.append(f"konum=({action.x}, {action.y})")
    if action.steps:
        parts.append(f"adım={action.steps:+d}")
    if action.kind == ActionKind.SET_VOLUME:
        pct = max(0, min(100, round(action.value * 100)))
        parts.append(f"değer=%{pct}")
    if action.target is not None:
        parts.append(f"hedef=0x{action.target.hwnd:X}")
    return f"Üretilecek komut: {' | '.join(parts)}"


# ---------- ViewModel state dataclasses ----------

@dataclass(frozen=True)
class VirtualCursorState:
    """Virtual pointer rendered inside overlay menus."""

    x: float = 0.5                  # Normalized [0.0, 1.0] within the overlay
    y: float = 0.5                  # Normalized [0.0, 1.0] within the overlay
    visible: bool = False
    pinching: bool = False
    hold_progress: float = 0.0      # [0.0, 1.0] dwell/hold progress


@dataclass(frozen=True)
class OverlayMenuItem:
    """A single selectable item in the mode or window action overlay."""

    item_id: str
    label: str
    enabled: bool = True
    active: bool = False
    hovered: bool = False
    armed: bool = False
    hold_progress: float = 0.0      # [0.0, 1.0] hold ring progress (e.g. 1s Close hold)


@dataclass(frozen=True)
class OverlayState:
    """Complete state for the mode menu and window action overlay."""

    visible: bool = False
    kind: OverlayMenuKind = OverlayMenuKind.NONE
    title: str = ""
    items: tuple[OverlayMenuItem, ...] = ()
    cursor: VirtualCursorState = field(default_factory=VirtualCursorState)
    inactivity_ms: float = 0.0
    timeout_ms: float = 5000.0
    closing_progress: float = 0.0   # [0.0, 1.0] closing animation progress
    target_window_title: str = ""

    @property
    def is_expired(self) -> bool:
        return self.inactivity_ms >= self.timeout_ms or self.closing_progress >= 1.0


@dataclass(frozen=True)
class FeedbackMessage:
    """Short OSD notification data."""

    kind: FeedbackKind
    text: str
    volume_percent: Optional[int] = None
    hold_progress: Optional[float] = None
    duration_ms: int = 1800


@dataclass(frozen=True)
class UiState:
    """Aggregated UI viewmodel state."""

    control_state: ControlState = ControlState.PAUSED
    camera_state: CameraState = CameraState.OFF
    mode: Mode = Mode.POINTER
    menu_items: tuple[OverlayMenuItem, ...] = ()
    virtual_cursor: VirtualCursorState = field(default_factory=VirtualCursorState)
    hold_progress: float = 0.0
    fps: float = 0.0
    sample_age_ms: float = 0.0
    error_text: str = ""
    mirrored: bool = True
    dry_run: bool = False
    dry_run_command_text: str = ""
    overlay: OverlayState = field(default_factory=OverlayState)
    latest_frame: Optional[FrameFeatures] = None

    @property
    def tray_icon_state(self) -> TrayIconState:
        return resolve_tray_icon_state(self.control_state, self.camera_state)

    @property
    def tray_state_label_tr(self) -> str:
        return TRAY_ICON_STATE_LABELS_TR[self.tray_icon_state]

    @property
    def mode_label_tr(self) -> str:
        return MODE_LABELS_TR.get(self.mode, self.mode.value)

    @property
    def camera_state_label_tr(self) -> str:
        return CAMERA_STATE_LABELS_TR.get(self.camera_state, self.camera_state.value)

    @property
    def control_state_label_tr(self) -> str:
        return CONTROL_STATE_LABELS_TR.get(self.control_state, self.control_state.value)

    @property
    def tooltip_text(self) -> str:
        base = (
            f"Durum: {self.tray_state_label_tr} | "
            f"Mod: {self.mode_label_tr} | "
            f"Kamera: {self.camera_state_label_tr}"
        )
        if self.error_text:
            return f"{base} ({self.error_text})"
        return base

    @property
    def pause_resume_action_text(self) -> str:
        return "Duraklat" if self.control_state == ControlState.ACTIVE else "Sürdür"

    @property
    def camera_toggle_action_text(self) -> str:
        if self.camera_state in (CameraState.RUNNING, CameraState.STARTING):
            return "Kamerayı Durdur"
        return "Kamerayı Başlat"


def create_mode_menu_items(
    active_mode: Mode = Mode.POINTER,
    hovered_mode: Optional[Mode] = None,
    hold_progress: float = 0.0,
) -> tuple[OverlayMenuItem, ...]:
    """Create the 5 standard mode menu items in Turkish."""
    items: list[OverlayMenuItem] = []
    for mode in Mode:
        is_hovered = mode == hovered_mode
        items.append(
            OverlayMenuItem(
                item_id=mode.value,
                label=MODE_LABELS_TR[mode],
                enabled=True,
                active=(mode == active_mode),
                hovered=is_hovered,
                armed=False,
                hold_progress=max(0.0, min(1.0, hold_progress)) if is_hovered else 0.0,
            )
        )
    return tuple(items)


def create_window_action_menu_items(
    hovered_action: Optional[WindowActionKind] = None,
    close_armed: bool = False,
    close_hold_progress: float = 0.0,
    multi_monitor: bool = True,
) -> tuple[OverlayMenuItem, ...]:
    """Create the 4 standard window action menu items in Turkish."""
    clamped_close = max(0.0, min(1.0, close_hold_progress))
    items: list[OverlayMenuItem] = []
    for action_kind in WindowActionKind:
        is_hovered = action_kind == hovered_action
        is_close = action_kind == WindowActionKind.CLOSE
        enabled = multi_monitor if action_kind == WindowActionKind.MOVE_OTHER_MONITOR else True
        label = WINDOW_ACTION_LABELS_TR[action_kind]
        if is_close and close_armed:
            label = "Kapat (1 sn Basılı Tutun)"
        items.append(
            OverlayMenuItem(
                item_id=action_kind.value,
                label=label,
                enabled=enabled,
                active=False,
                hovered=is_hovered,
                armed=close_armed if is_close else False,
                hold_progress=clamped_close if is_close else 0.0,
            )
        )
    return tuple(items)


class UiBridge(QObject):
    """Thread-safe bridge between controller/worker threads and GUI widgets.

    Qt widgets must only be touched from the GUI thread. Worker threads may emit
    into this bridge or call its update methods; if called from a non-GUI thread,
    updates are marshalled onto the bridge's thread via queued Qt signals.
    """

    # Outbound state signals (GUI components subscribe to these)
    state_changed = Signal(object)              # UiState
    frame_updated = Signal(object)              # Optional[FrameFeatures]
    overlay_updated = Signal(object)            # OverlayState
    feedback_triggered = Signal(object)         # FeedbackMessage
    dry_run_updated = Signal(str)               # str

    # User request signals (controller / application coordinator subscribes to these)
    pause_resume_requested = Signal()
    pause_requested = Signal()
    resume_requested = Signal()
    camera_toggle_requested = Signal()
    camera_start_requested = Signal()
    camera_stop_requested = Signal()
    settings_requested = Signal()
    calibration_requested = Signal()
    exit_requested = Signal()
    mode_selected = Signal(object)              # Mode
    window_action_selected = Signal(str)        # WindowActionKind.value
    settings_saved = Signal(object)             # SettingsData or dict
    calibration_completed = Signal(object)      # CalibrationResult
    calibration_cancelled = Signal()

    # Internal cross-thread marshalling signals
    _marshal_state = Signal(object)
    _marshal_patch = Signal(object)
    _marshal_frame = Signal(object, object, object)
    _marshal_overlay = Signal(object)
    _marshal_feedback = Signal(object)
    _marshal_dry_run = Signal(str)

    def __init__(
        self,
        initial_state: Optional[UiState] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._state: UiState = initial_state or UiState()

        self._marshal_state.connect(self._apply_state_on_gui_thread)
        self._marshal_patch.connect(self._apply_patch_on_gui_thread)
        self._marshal_frame.connect(self._apply_frame_on_gui_thread)
        self._marshal_overlay.connect(self._apply_overlay_on_gui_thread)
        self._marshal_feedback.connect(self._apply_feedback_on_gui_thread)
        self._marshal_dry_run.connect(self._apply_dry_run_on_gui_thread)

    @property
    def state(self) -> UiState:
        """Return the latest immutable UiState snapshot."""
        return self._state

    def _is_gui_thread(self) -> bool:
        return QThread.currentThread() == self.thread()

    # ---------- State update slots ----------

    @Slot(object)
    def update_state(self, new_state: UiState) -> None:
        """Replace the entire UiState safely from any thread."""
        if self._is_gui_thread():
            self._apply_state_on_gui_thread(new_state)
        else:
            self._marshal_state.emit(new_state)

    @Slot(object)
    def _apply_state_on_gui_thread(self, new_state: UiState) -> None:
        self._state = new_state
        self.state_changed.emit(self._state)

    def update_status(
        self,
        *,
        control_state: Optional[ControlState] = None,
        camera_state: Optional[CameraState] = None,
        mode: Optional[Mode] = None,
        menu_items: Optional[tuple[OverlayMenuItem, ...]] = None,
        virtual_cursor: Optional[VirtualCursorState] = None,
        hold_progress: Optional[float] = None,
        fps: Optional[float] = None,
        sample_age_ms: Optional[float] = None,
        error_text: Optional[str] = None,
        mirrored: Optional[bool] = None,
        dry_run: Optional[bool] = None,
        dry_run_command_text: Optional[str] = None,
    ) -> None:
        """Partially update fields of UiState safely from any thread."""
        changes: dict[str, Any] = {}
        if control_state is not None:
            changes["control_state"] = control_state
        if camera_state is not None:
            changes["camera_state"] = camera_state
        if mode is not None:
            changes["mode"] = mode
        if menu_items is not None:
            changes["menu_items"] = tuple(menu_items)
        if virtual_cursor is not None:
            changes["virtual_cursor"] = virtual_cursor
        if hold_progress is not None:
            changes["hold_progress"] = max(0.0, min(1.0, float(hold_progress)))
        if fps is not None:
            changes["fps"] = float(fps)
        if sample_age_ms is not None:
            changes["sample_age_ms"] = float(sample_age_ms)
        if error_text is not None:
            changes["error_text"] = str(error_text)
        if mirrored is not None:
            changes["mirrored"] = bool(mirrored)
        if dry_run is not None:
            changes["dry_run"] = bool(dry_run)
        if dry_run_command_text is not None:
            changes["dry_run_command_text"] = str(dry_run_command_text)

        if not changes:
            return

        if self._is_gui_thread():
            self._apply_patch_on_gui_thread(changes)
        else:
            self._marshal_patch.emit(changes)

    @Slot(object)
    def _apply_patch_on_gui_thread(self, changes: dict[str, Any]) -> None:
        self._state = replace(self._state, **changes)
        self.state_changed.emit(self._state)

    @Slot(object)
    def update_frame(
        self,
        frame: Optional[FrameFeatures],
        fps: Optional[float] = None,
        sample_age_ms: Optional[float] = None,
    ) -> None:
        """Update the latest camera/tracking FrameFeatures safely from any thread."""
        if self._is_gui_thread():
            self._apply_frame_on_gui_thread(frame, fps, sample_age_ms)
        else:
            self._marshal_frame.emit(frame, fps, sample_age_ms)

    @Slot(object, object, object)
    def _apply_frame_on_gui_thread(
        self,
        frame: Optional[FrameFeatures],
        fps: Optional[float],
        sample_age_ms: Optional[float],
    ) -> None:
        changes: dict[str, Any] = {"latest_frame": frame}
        if fps is not None:
            changes["fps"] = float(fps)
        if sample_age_ms is not None:
            changes["sample_age_ms"] = float(sample_age_ms)
        elif frame is not None and frame.inference_done_ms >= frame.capture_ms:
            changes["sample_age_ms"] = float(frame.inference_done_ms - frame.capture_ms)
        self._state = replace(self._state, **changes)
        self.frame_updated.emit(frame)
        self.state_changed.emit(self._state)

    @Slot(object)
    def update_overlay(self, overlay: OverlayState) -> None:
        """Update overlay state (mode menu or window action menu) safely."""
        if self._is_gui_thread():
            self._apply_overlay_on_gui_thread(overlay)
        else:
            self._marshal_overlay.emit(overlay)

    @Slot(object)
    def _apply_overlay_on_gui_thread(self, overlay: OverlayState) -> None:
        self._state = replace(
            self._state,
            overlay=overlay,
            menu_items=overlay.items,
            virtual_cursor=overlay.cursor,
        )
        self.overlay_updated.emit(overlay)
        self.state_changed.emit(self._state)

    @Slot(float, float, bool, bool, float)
    def update_virtual_cursor(
        self,
        x: float,
        y: float,
        visible: bool = True,
        pinching: bool = False,
        hold_progress: float = 0.0,
    ) -> None:
        """Update the virtual cursor position and hold progress."""
        cursor = VirtualCursorState(
            x=max(0.0, min(1.0, float(x))),
            y=max(0.0, min(1.0, float(y))),
            visible=bool(visible),
            pinching=bool(pinching),
            hold_progress=max(0.0, min(1.0, float(hold_progress))),
        )
        overlay = replace(self._state.overlay, cursor=cursor)
        self.update_overlay(overlay)

    @Slot(object)
    def show_feedback(
        self,
        message: FeedbackMessage | str,
        kind: FeedbackKind = FeedbackKind.INFO,
        volume_percent: Optional[int] = None,
        hold_progress: Optional[float] = None,
        duration_ms: int = 1800,
    ) -> None:
        """Trigger a short non-focus-stealing notification."""
        if isinstance(message, FeedbackMessage):
            msg = message
        else:
            msg = FeedbackMessage(
                kind=kind,
                text=str(message),
                volume_percent=volume_percent,
                hold_progress=hold_progress,
                duration_ms=duration_ms,
            )
        if self._is_gui_thread():
            self._apply_feedback_on_gui_thread(msg)
        else:
            self._marshal_feedback.emit(msg)

    @Slot(object)
    def _apply_feedback_on_gui_thread(self, msg: FeedbackMessage) -> None:
        self.feedback_triggered.emit(msg)

    @Slot(object)
    def record_dry_run_action(self, action: Action | str) -> None:
        """Format and publish a dry-run action string."""
        if isinstance(action, Action):
            text = format_action_tr(action)
        else:
            raw = str(action).strip()
            text = raw if raw.startswith("Üretilecek komut:") else f"Üretilecek komut: {raw}"
        if self._is_gui_thread():
            self._apply_dry_run_on_gui_thread(text)
        else:
            self._marshal_dry_run.emit(text)

    @Slot(str)
    def _apply_dry_run_on_gui_thread(self, text: str) -> None:
        self._state = replace(self._state, dry_run=True, dry_run_command_text=text)
        self.dry_run_updated.emit(text)
        self.state_changed.emit(self._state)

    # ---------- User request emitters (called by GUI widgets) ----------

    @Slot()
    def request_pause_resume(self) -> None:
        """Emit pause/resume request signals based on current control state."""
        self.pause_resume_requested.emit()
        if self._state.control_state == ControlState.ACTIVE:
            self.pause_requested.emit()
        else:
            self.resume_requested.emit()

    @Slot()
    def request_camera_toggle(self) -> None:
        """Emit camera start/stop request signals based on current camera state."""
        self.camera_toggle_requested.emit()
        if self._state.camera_state in (CameraState.RUNNING, CameraState.STARTING):
            self.camera_stop_requested.emit()
        else:
            self.camera_start_requested.emit()

    @Slot()
    def request_settings(self) -> None:
        """Emit settings dialog request."""
        self.settings_requested.emit()

    @Slot()
    def request_calibration(self) -> None:
        """Emit calibration wizard request."""
        self.calibration_requested.emit()

    @Slot()
    def request_exit(self) -> None:
        """Emit application exit request."""
        self.exit_requested.emit()

    @Slot(object)
    def select_mode(self, mode: Mode | str) -> None:
        """Emit mode selection request."""
        resolved = Mode(mode) if isinstance(mode, str) else mode
        self.mode_selected.emit(resolved)

    @Slot(str)
    def select_window_action(self, action_id: str) -> None:
        """Emit window action selection request."""
        self.window_action_selected.emit(str(action_id))
