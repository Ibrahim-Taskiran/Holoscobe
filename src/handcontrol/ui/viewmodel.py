"""ViewModel data structures and thread-safe Qt bridge for the Holoscobe UI.

All user-facing labels are in Turkish. Code and comments are in English.
Only stdlib, handcontrol.contracts, and PySide6 (QtCore) are imported here.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from functools import partial, wraps
from typing import Any, Optional

from PySide6.QtCore import QObject, QThread, Signal, Slot

from handcontrol.swipe import COMMAND_LABELS as SWIPE_COMMAND_LABELS
from handcontrol.swipe import PROFILES as SWIPE_PROFILES
from handcontrol.swipe import SwipeDirection, pinch_command, swipe_command

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


class FeedbackKind(Enum):
    """Looks of the short notifications."""

    INFO = "info"
    WARNING = "warning"


# ---------- Turkish user-facing label mappings ----------

MODE_LABELS_TR: dict[Mode, str] = {
    Mode.POINTER: "İmleç",
    Mode.SCROLL: "Kaydırma",
    Mode.ZOOM: "Yakınlaştırma",
    Mode.VOLUME: "Ses",
    Mode.WINDOWS: "Pencere",
    Mode.COMMANDS: "Komutlar",
    Mode.INSTRUMENT: "Enstrüman",
    Mode.DRAWING: "Çizim",
}

# Short Turkish labels for contracts.KeyCommand values (keyed by value; ui never imports windows/).
COMMAND_LABELS_TR: dict[str, str] = {
    "next": "Sonraki",
    "previous": "Önceki",
    "browser_back": "Tarayıcı geri",
    "browser_forward": "Tarayıcı ileri",
    "task_view": "Görev görünümü",
    "show_desktop": "Masaüstünü göster",
    "desktop_left": "Sol masaüstü",
    "desktop_right": "Sağ masaüstü",
    "media_play_pause": "Oynat/Duraklat",
    "media_next": "Sonraki parça",
    "media_previous": "Önceki parça",
    "volume_mute": "Sesi kapat/aç",
}

# Settings swipe_profile values (config.SWIPE_PROFILES) -> Turkish labels.
SWIPE_PROFILE_LABELS_TR: dict[str, str] = {
    "auto": "Otomatik",
    "slides": "Sunum",
    "browser": "Tarayıcı",
    "media": "Medya",
    "desktops": "Sanal masaüstleri",
}

COMMAND_TOAST_MS = 900


def command_label_tr(command: Any) -> str:
    """Turkish label for a KeyCommand (enum or value string); unknown values pass through."""
    value = str(getattr(command, "value", command) or "")
    return COMMAND_LABELS_TR.get(value, value)

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

ACTION_KIND_LABELS_TR: dict[ActionKind, str] = {
    ActionKind.MOVE_POINTER: "İmleci Taşı",
    ActionKind.LEFT_CLICK: "Sol Tık",
    ActionKind.RIGHT_CLICK: "Sağ Tık",
    ActionKind.DOUBLE_CLICK: "Çift Tık",
    ActionKind.LEFT_DOWN: "Sol Tuş Basılı (Sürükle)",
    ActionKind.LEFT_UP: "Sol Tuş Bırakıldı",
    ActionKind.SCROLL: "Kaydır",
    ActionKind.ZOOM: "Yakınlaştır",
    ActionKind.SET_VOLUME: "Ses Seviyesini Ayarla",
    ActionKind.WINDOW_DRAG_BEGIN: "Pencere Sürüklemeyi Başlat",
    ActionKind.WINDOW_DRAG_MOVE: "Pencereyi Taşı",
    ActionKind.WINDOW_DRAG_END: "Pencere Sürüklemeyi Bitir",
    ActionKind.WINDOW_MINIMIZE: "Pencereyi Küçült",
    ActionKind.WINDOW_RESTORE: "Son Küçültülen Pencereyi Geri Aç",
    ActionKind.WINDOW_TOGGLE_MAXIMIZE: "Pencereyi Büyüt/Geri Yükle",
    ActionKind.WINDOW_MOVE_TO_OTHER_MONITOR: "Pencereyi Diğer Ekrana Taşı",
    ActionKind.WINDOW_CLOSE: "Pencereyi Kapat",
    ActionKind.RELEASE_ALL: "Tüm Girdileri Bırak",
    ActionKind.KEY_COMMAND: "Klavye Komutu",
}


# User-facing gesture guide (gesture, result). Mirrors README "Ne yapar"; keep both in sync.
GESTURE_GUIDE_TR: tuple[tuple[str, str], ...] = (
    ("İki elle bir kez el çırp", "Kontrolü aç / duraklat"),
    ("İşaret açık, diğer parmaklar kapalı", "İmleç hareket eder (hızlı hareket uzağa, yavaş hareket hassas gider); bir kez işaret etmek yeter, el açılana ya da yumruk olana kadar sürer"),
    ("Eli aç ya da kadrajdan çıkar", "Bırakmak için eli belirgin aç; imleç yerinde kalır. Eli geri getirip yeniden işaret et, kaldığı yerden devam eder"),
    ("Kısa pinch (başparmak + işaret)", "Sol tık (imleç pinch sırasında durur)"),
    ("İki hızlı pinch", "Çift tık"),
    ("Pinch'i 0,8 sn yerinde tut", "Sağ tık"),
    ("Başparmak, işaret ve orta parmak uçlarını birleştir, taşı, bırak", "Sürükle bırak (sol tuş basılı)"),
    ("İşaret pinch kapalıyken eli 0,6 avuçtan fazla taşı", "Sürükle bırak (alternatif; sağ tıktan önce hareket et)"),
    ("Açık elden başparmak + orta parmak", "Sağ tık (alternatif)"),
    ("Sağ yumruk tut (önce el açık olmalı)", "Ön plandaki pencereyi küçült"),
    ("Sol yumruk tut (önce el açık olmalı)", "Son küçültülen pencereyi geri aç"),
    ("Sol elle V yap, yarım saniye tut", "Mod çarkı: V ile yönel, yumrukla seç, avucu açınca vazgeç"),
    ("İmleci yerinde sabit tut (Bekleyerek tıkla açıksa)", "Sol tık; imlecin yanındaki halka dolunca tıklar"),
    ("Kalibrasyon dikdörtgeni", "Yalnız mutlak imleç türünde geçerli"),
)

# Komutlar mode section of the gesture guide (gesture, result). Built from swipe.py so it cannot drift.
def _build_commands_guide() -> tuple[tuple[str, str], ...]:
    profs = [(p, SWIPE_PROFILE_LABELS_TR[p]) for p in SWIPE_PROFILES]

    def horizontal(direction: SwipeDirection) -> str:
        return " · ".join(
            f"{label}: {SWIPE_COMMAND_LABELS[swipe_command(p, direction)]}" for p, label in profs)

    pinch = {SWIPE_COMMAND_LABELS[pinch_command(p)] for p in SWIPE_PROFILES}
    default = SWIPE_COMMAND_LABELS[pinch_command("desktops")]
    pinch_text = f"{default} (Sunum profilinde {SWIPE_COMMAND_LABELS[pinch_command('slides')]})"         if len(pinch) > 1 else default
    return (
        ("Sola kaydır", horizontal(SwipeDirection.LEFT)),
        ("Sağa kaydır", horizontal(SwipeDirection.RIGHT)),
        ("Yukarı kaydır", SWIPE_COMMAND_LABELS[swipe_command("desktops", SwipeDirection.UP)]),
        ("Aşağı kaydır", SWIPE_COMMAND_LABELS[swipe_command("desktops", SwipeDirection.DOWN)]),
        ("Kısa pinch", pinch_text),
    )


COMMANDS_GUIDE_TR: tuple[tuple[str, str], ...] = _build_commands_guide()
COMMANDS_GUIDE_TITLE_TR = "Komutlar modu"


class IndicatorKind(Enum):
    """Single status the user should currently see, in priority order."""

    PAUSED = "paused"
    NO_TRACKING = "no_tracking"
    PENDING = "pending"
    ENGAGED = "engaged"
    PARKED = "parked"


@dataclass(frozen=True)
class IndicatorState:
    kind: IndicatorKind = IndicatorKind.PAUSED
    text: str = "Duraklatıldı"


INDICATOR_TEXT_TR: dict[IndicatorKind, str] = {
    IndicatorKind.PAUSED: "Duraklatıldı",
    IndicatorKind.NO_TRACKING: "Takip yok (el görünmüyor)",
    IndicatorKind.ENGAGED: "İmleç aktif",
    IndicatorKind.PARKED: "İmleç beklemede (işaret pozu yap)",
}

CANCEL_TOAST_MS = 1500


def resolve_indicator(snapshot: Any) -> IndicatorState:
    """Pick the one status to show. New snapshot fields are read via getattr (old snapshots work)."""
    if getattr(snapshot, "state", None) != ControlState.ACTIVE:
        return IndicatorState(IndicatorKind.PAUSED, INDICATOR_TEXT_TR[IndicatorKind.PAUSED])
    if not getattr(snapshot, "tracking_ok", True):
        return IndicatorState(IndicatorKind.NO_TRACKING, INDICATOR_TEXT_TR[IndicatorKind.NO_TRACKING])
    pending = str(getattr(snapshot, "pending_action", "") or "").strip()
    if pending:
        return IndicatorState(IndicatorKind.PENDING, pending)
    if getattr(snapshot, "pointer_engaged", False):
        return IndicatorState(IndicatorKind.ENGAGED, INDICATOR_TEXT_TR[IndicatorKind.ENGAGED])
    return IndicatorState(IndicatorKind.PARKED, INDICATOR_TEXT_TR[IndicatorKind.PARKED])


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
    command = str(getattr(action, "command", "") or "")
    if command:
        parts.append(f"komut={command_label_tr(command)}")
    return " | ".join(parts)


# ---------- ViewModel state dataclasses ----------

@dataclass(frozen=True)
class VirtualCursorState:
    """Virtual pointer rendered inside overlay menus."""

    x: float = 0.5                  # Normalized [0.0, 1.0] within the overlay
    y: float = 0.5                  # Normalized [0.0, 1.0] within the overlay
    visible: bool = False
    hold_progress: float = 0.0      # [0.0, 1.0] ring that fills while the V is held


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


@dataclass(frozen=True)
class CursorFeedbackState:
    """Hold ring next to the real cursor. x/y are physical virtual-desktop px (snapshot.pointer)."""

    kind: str = ""                  # ControllerSnapshot.hold_kind, "" = no hold
    progress: float = 0.0           # [0.0, 1.0]
    x: Optional[int] = None
    y: Optional[int] = None

    @property
    def active(self) -> bool:
        return self.progress > 0.0


def resolve_cursor_feedback(snapshot: Any) -> CursorFeedbackState:
    """Read hold_kind / hold_progress / pointer from a snapshot (missing fields -> no ring)."""
    try:
        progress = float(getattr(snapshot, "hold_progress", 0.0) or 0.0)
    except (TypeError, ValueError):
        progress = 0.0
    if progress != progress:  # NaN
        progress = 0.0
    progress = max(0.0, min(1.0, progress))
    kind = str(getattr(snapshot, "hold_kind", "") or "")
    pointer = getattr(snapshot, "pointer", None)
    x = y = None
    if pointer is not None:
        try:
            x, y = int(pointer[0]), int(pointer[1])
        except (TypeError, ValueError, IndexError):
            x = y = None
    if progress <= 0.0:
        kind = ""
    return CursorFeedbackState(kind=kind, progress=round(progress, 3), x=x, y=y)


@dataclass(frozen=True)
class FeedbackMessage:
    """Short OSD notification data."""

    kind: FeedbackKind
    text: str
    duration_ms: int = 1800


@dataclass(frozen=True)
class UiState:
    """Aggregated UI viewmodel state."""

    control_state: ControlState = ControlState.PAUSED
    camera_state: CameraState = CameraState.OFF
    mode: Mode = Mode.POINTER
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


def _on_gui(method):
    """Callable from any thread; runs on the thread of the bridge (GUI)."""
    @wraps(method)
    def call(self, *args, **kwargs):
        if QThread.currentThread() == self.thread():
            method(self, *args, **kwargs)
        else:
            self._queued.emit(partial(method, self, *args, **kwargs))
    return call


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
    indicator_updated = Signal(object)          # IndicatorState
    cursor_feedback_updated = Signal(object)    # CursorFeedbackState (only on change)
    command_triggered = Signal(str)             # KeyCommand value, once per command_seq change
    mascot_visible_changed = Signal(bool)       # the cat was shown or hidden (button and tray mirror it)

    # User request signals: buttons and menus connect to or emit them, the application listens
    pause_resume_requested = Signal()
    camera_toggle_requested = Signal()
    settings_requested = Signal()
    calibration_requested = Signal()
    tutorial_requested = Signal()
    exit_requested = Signal()
    instrument_window_requested = Signal()      # tray "Enstrüman penceresi"
    mascot_toggle_requested = Signal(bool)      # user asked to show / hide the cat
    mode_selected = Signal(object)              # Mode
    settings_saved = Signal(object)             # SettingsData or dict
    calibration_completed = Signal(object)      # CalibrationResult
    calibration_cancelled = Signal()

    _queued = Signal(object)                    # calls from other threads

    def __init__(
        self,
        initial_state: Optional[UiState] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._state: UiState = initial_state or UiState()
        self._indicator: Optional[IndicatorState] = None
        self._last_cancel: str = ""
        self._cursor_feedback: CursorFeedbackState = CursorFeedbackState()
        self._command_seq: Optional[int] = None
        self._mascot_visible: bool = True
        self._queued.connect(self._run)

    @Slot(object)
    def _run(self, job) -> None:
        job()

    @property
    def state(self) -> UiState:
        """Return the latest immutable UiState snapshot."""
        return self._state

    # ---------- updates (safe from any thread) ----------

    def _change(self, **fields: Any) -> None:
        self._state = replace(self._state, **fields)
        self.state_changed.emit(self._state)

    @_on_gui
    def update_state(self, new_state: UiState) -> None:
        """Replace the entire UiState."""
        self._state = new_state
        self.state_changed.emit(new_state)

    @_on_gui
    def update_status(self, **fields: Any) -> None:
        """Change single UiState fields."""
        self._change(**fields)

    @_on_gui
    def update_frame(self, frame: Optional[FrameFeatures]) -> None:
        """Latest tracking result."""
        age = {}
        if frame is not None and frame.inference_done_ms >= frame.capture_ms:
            age = {"sample_age_ms": float(frame.inference_done_ms - frame.capture_ms)}
        self._state = replace(self._state, latest_frame=frame, **age)
        self.frame_updated.emit(frame)
        self.state_changed.emit(self._state)

    @_on_gui
    def update_snapshot(self, snapshot: Any) -> None:
        """Feed a ControllerSnapshot: refreshes the status indicator, cursor ring and toasts."""
        indicator = resolve_indicator(snapshot)
        if indicator != self._indicator:
            self._indicator = indicator
            self.indicator_updated.emit(indicator)
        cancel = str(getattr(snapshot, "last_cancel", "") or "")
        if cancel != self._last_cancel:
            self._last_cancel = cancel
            if cancel:
                self.feedback_triggered.emit(
                    FeedbackMessage(FeedbackKind.WARNING, cancel, duration_ms=CANCEL_TOAST_MS))
        feedback = resolve_cursor_feedback(snapshot)
        if feedback != self._cursor_feedback:
            self._cursor_feedback = feedback
            self.cursor_feedback_updated.emit(feedback)
        try:
            seq = int(getattr(snapshot, "command_seq", 0) or 0)
        except (TypeError, ValueError):
            seq = 0
        if self._command_seq is None:
            self._command_seq = seq          # first snapshot: baseline, no stale toast
        elif seq != self._command_seq:
            self._command_seq = seq
            command = str(getattr(snapshot, "last_command", "") or "")
            if command:
                self.command_triggered.emit(command)

    @property
    def mascot_visible(self) -> bool:
        return self._mascot_visible

    @Slot(bool)
    def set_mascot_visible(self, on: bool) -> None:
        """Store whether the cat is shown and tell the controls that mirror it."""
        self._mascot_visible = bool(on)
        self.mascot_visible_changed.emit(self._mascot_visible)

    @_on_gui
    def update_overlay(self, overlay: OverlayState) -> None:
        """Mode wheel or window action menu."""
        self._state = replace(self._state, overlay=overlay)
        self.overlay_updated.emit(overlay)
        self.state_changed.emit(self._state)

    @_on_gui
    def show_feedback(self, message: str) -> None:
        """Short notification that never takes the focus."""
        self.feedback_triggered.emit(FeedbackMessage(FeedbackKind.INFO, str(message)))

    @_on_gui
    def record_dry_run_action(self, action: Action | str) -> None:
        """Publish the command a dry run would have sent."""
        text = format_action_tr(action) if isinstance(action, Action) else str(action).strip()
        self._state = replace(self._state, dry_run=True, dry_run_command_text=text)
        self.dry_run_updated.emit(text)
        self.state_changed.emit(self._state)

    def select_mode(self, mode: Mode | str) -> None:
        """Emit mode selection request."""
        self.mode_selected.emit(Mode(mode))
