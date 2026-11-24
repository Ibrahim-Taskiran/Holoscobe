"""Settings dataclass and configuration dialog for Holoscobe.

All user-visible strings are in Turkish.
Supports round-trip serialization as both a dataclass (`SettingsData`) and a
plain dictionary (`dict[str, Any]`).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Optional, Sequence

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from handcontrol.contracts import Handedness, Mode
from handcontrol.instrument.events import (
    CHORD_NAMES, DEFAULT_CHORDS, DEFAULT_FIXED_STRINGS, FIXED_STRINGS_RANGE, LATENCIES, LAYOUTS, SCALE_NAMES, TONES,
)
from handcontrol.ui import theme
from handcontrol.ui.tray import create_mode_icon
from handcontrol.ui.viewmodel import MODE_LABELS_TR, SWIPE_PROFILE_LABELS_TR, UiBridge
from handcontrol.ui.widgets import (
    Card, ComboBox, DoubleSpinBox, SettingRow, SideItem, SpinBox, ToggleSwitch, button, label,
)

CONTROL_WIDTH = 270              # every combo / field column on the right of a setting row
NUMBER_WIDTH = 112


POINTER_MODES: tuple[str, ...] = ("relative", "absolute")
POINTER_MODE_LABELS_TR: dict[str, str] = {
    "relative": "Göreli (dokunmatik yüzey gibi)",
    "absolute": "Mutlak (kamera alanı = ekran)",
}
POINTER_SPEED_MIN, POINTER_SPEED_MAX = 0.5, 2.0
_SPEED_STEPS = 10  # slider ticks per 1.0 of speed -> step 0.1

SWIPE_PROFILES: tuple[str, ...] = tuple(SWIPE_PROFILE_LABELS_TR)   # mirrors config.SWIPE_PROFILES

AUTO_PAUSE_CHOICES: tuple[tuple[int, str], ...] = (
    (0, "Kapalı"),
    (30, "30 sn"),
    (60, "1 dk"),
    (120, "2 dk"),
    (300, "5 dk"),
)
AUTO_PAUSE_MAX_S = 3600

DWELL_MS_MIN, DWELL_MS_MAX = 400, 3000
_DWELL_UNIT_MS = 50   # slider unit

# Sensitivity presets: key -> (pointer_speed, pointer_sensitivity). "custom" = Özel.
SENSITIVITY_PRESETS: dict[str, tuple[float, float]] = {
    "precise": (0.7, 0.8),
    "normal": (1.0, 1.0),
    "fast": (1.5, 1.3),
}
SENSITIVITY_PRESET_LABELS_TR: dict[str, str] = {
    "precise": "Hassas",
    "normal": "Normal",
    "fast": "Hızlı",
    "custom": "Özel",
}


INSTRUMENT_LAYOUT_LABELS_TR: dict[str, str] = {"solo": "Solo", "chord": "Akor", "fixed": "Sabit teller",
                                               "free": "Serbest teller"}
INSTRUMENT_SCALE_LABELS_TR: dict[str, str] = {
    "e_minor_pentatonic": "Mi minör pentatonik",
    "a_minor_pentatonic": "La minör pentatonik",
    "e_blues": "Mi blues",
    "e_minor": "Mi minör",
    "a_minor": "La minör",
    "c_major": "Do majör",
    "g_major": "Sol majör",
    "d_dorian": "Re dorian",
    "chromatic": "Kromatik",
}
INSTRUMENT_TONE_LABELS_TR: dict[str, str] = {"clean": "Temiz", "electric": "Elektro"}
AUDIO_LATENCY_LABELS_TR: dict[str, str] = {"low": "Düşük", "normal": "Normal"}
CHORD_ZONE_LABELS_TR: tuple[str, str, str, str] = ("Üst bölge", "Üst orta bölge", "Alt orta bölge", "Alt bölge")
AUDIO_DEFAULT_DEVICE_LABEL_TR = "Sistem varsayılanı"


def _clean_chords(value: Any) -> tuple[str, str, str, str]:
    """Exactly four known chord names; a bad entry falls back to the default chord of its zone."""
    items = list(value) if isinstance(value, (list, tuple)) else []
    out = [str(items[i]) if i < len(items) and str(items[i]) in CHORD_NAMES else DEFAULT_CHORDS[i]
           for i in range(4)]
    return (out[0], out[1], out[2], out[3])


def preset_for(pointer_speed: float, pointer_sensitivity: float) -> str:
    """Preset key matching the two values, or "custom"."""
    for key, (speed, sens) in SENSITIVITY_PRESETS.items():
        if abs(pointer_speed - speed) < 1e-6 and abs(pointer_sensitivity - sens) < 1e-6:
            return key
    return "custom"


def _int_or(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class SettingsData:
    """Typed representation of all user-configurable settings."""

    camera_index: int = 0
    camera_backend: str = "media_foundation"
    mirror: bool = True
    dominant_hand: str = "right"                # "right" or "left"
    pointer_sensitivity: float = 1.0            # 0.1 .. 3.0
    smoothing_factor: float = 0.50              # 0.0 .. 1.0
    pointer_mode: str = "relative"              # "relative" (touchpad-like) or "absolute"
    pointer_speed: float = 1.0                  # 0.5 .. 2.0, step 0.1 (relative mode)
    pinch_on_threshold: float = 0.33            # 0.10 .. 0.60
    pinch_off_threshold: float = 0.48           # 0.15 .. 0.85
    detection_threshold: float = 0.55           # 0.10 .. 0.95
    tracking_threshold: float = 0.55            # 0.10 .. 0.95
    scroll_direction: str = "natural"           # "natural" or "reverse"
    zoom_direction: str = "natural"             # "natural" or "reverse"
    default_mode: str = "pointer"               # Mode.value
    emergency_hotkey: str = "Ctrl+Alt+Shift+F12"
    show_overlay: bool = True
    show_feedback_osd: bool = True
    show_mascot: bool = True
    hide_on_control: bool = True                # minimize the main window while the desktop is controlled
    show_dry_run_panel: bool = False
    monitor_mapping: str = "all"                # "all", "primary", "secondary"
    start_with_windows: bool = False            # Default False per spec
    swipe_profile: str = "auto"                 # config.SWIPE_PROFILES
    auto_pause_s: int = 0                       # 0 = off, else 10 .. 3600
    dwell_click: bool = False
    dwell_ms: int = 1000                        # 400 .. 3000
    click_sound: bool = False
    cursor_feedback: bool = True                # hold ring next to the cursor
    # Schema 4 (Enstrüman). Names match config.Settings exactly.
    instrument_layout: str = "free"             # LAYOUTS
    instrument_scale: str = "e_minor_pentatonic"  # SCALE_NAMES
    instrument_quantize: bool = True
    instrument_chords: tuple[str, ...] = DEFAULT_CHORDS   # 4 zones, top first
    instrument_volume: float = 0.5              # 0..1
    instrument_tone: str = "clean"              # TONES
    audio_device: str = ""                      # "" = system default
    audio_latency: str = "low"                  # LATENCIES
    instrument_particles: bool = True
    instrument_fixed_strings: int = DEFAULT_FIXED_STRINGS   # FIXED_STRINGS_RANGE
    instrument_free_snap: bool = True                       # "Serbest teller": snap near-aligned strings
    # Display only: output device names offered in the Ses cihazı list (not persisted).
    audio_device_choices: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # Settings stores lists; keep the frozen dataclass hashable and comparable.
        if not isinstance(self.instrument_chords, tuple):
            object.__setattr__(self, "instrument_chords", tuple(self.instrument_chords))
        if not isinstance(self.audio_device_choices, tuple):
            object.__setattr__(self, "audio_device_choices", tuple(self.audio_device_choices))

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dictionary copy of all settings."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SettingsData:
        """Construct SettingsData from a dictionary with safe fallbacks and clamping."""
        defaults = cls()

        raw_dom = data.get("dominant_hand", defaults.dominant_hand)
        if isinstance(raw_dom, Handedness):
            dom_str = raw_dom.value
        else:
            dom_str = str(raw_dom).lower()
        if dom_str not in ("left", "right"):
            dom_str = defaults.dominant_hand

        raw_mode = data.get("default_mode", data.get("mode", defaults.default_mode))
        if isinstance(raw_mode, Mode):
            mode_str = raw_mode.value
        else:
            mode_str = str(raw_mode).lower()
        valid_modes = {m.value for m in Mode}
        if mode_str not in valid_modes:
            mode_str = defaults.default_mode

        scroll_dir = str(data.get("scroll_direction", defaults.scroll_direction)).lower()
        if scroll_dir not in ("natural", "reverse"):
            scroll_dir = defaults.scroll_direction

        zoom_dir = str(data.get("zoom_direction", defaults.zoom_direction)).lower()
        if zoom_dir not in ("natural", "reverse"):
            zoom_dir = defaults.zoom_direction

        mon_map = str(data.get("monitor_mapping", defaults.monitor_mapping)).lower()
        if mon_map not in ("all", "primary", "secondary"):
            mon_map = defaults.monitor_mapping

        pointer_mode = str(data.get("pointer_mode", defaults.pointer_mode)).lower()
        if pointer_mode not in POINTER_MODES:
            pointer_mode = defaults.pointer_mode

        try:
            speed = float(data.get("pointer_speed", defaults.pointer_speed))
        except (TypeError, ValueError):
            speed = defaults.pointer_speed
        if speed != speed:  # NaN
            speed = defaults.pointer_speed
        pointer_speed = round(max(POINTER_SPEED_MIN, min(POINTER_SPEED_MAX, speed)), 1)

        backend = str(data.get("camera_backend", defaults.camera_backend)).lower()
        if backend not in ("media_foundation", "directshow"):
            backend = defaults.camera_backend

        pinch_on = round(
            max(0.10, min(0.60, float(data.get("pinch_on_threshold", defaults.pinch_on_threshold)))),
            2,
        )
        pinch_off = round(
            max(0.15, min(0.85, float(data.get("pinch_off_threshold", defaults.pinch_off_threshold)))),
            2,
        )

        hotkey = str(data.get("emergency_hotkey", defaults.emergency_hotkey)).strip()
        if not hotkey:
            hotkey = defaults.emergency_hotkey

        swipe = str(data.get("swipe_profile", defaults.swipe_profile)).lower()
        if swipe not in SWIPE_PROFILES:
            swipe = defaults.swipe_profile

        auto_pause = max(0, min(AUTO_PAUSE_MAX_S, _int_or(data.get("auto_pause_s"), defaults.auto_pause_s)))
        if 0 < auto_pause < 10:
            auto_pause = 10

        dwell_ms = max(DWELL_MS_MIN, min(DWELL_MS_MAX, _int_or(data.get("dwell_ms"), defaults.dwell_ms)))
        dwell_ms = int(round(dwell_ms / _DWELL_UNIT_MS) * _DWELL_UNIT_MS)

        layout = str(data.get("instrument_layout", defaults.instrument_layout)).lower()
        if layout not in LAYOUTS:
            layout = defaults.instrument_layout
        scale = str(data.get("instrument_scale", defaults.instrument_scale))
        if scale not in SCALE_NAMES:
            scale = defaults.instrument_scale
        tone = str(data.get("instrument_tone", defaults.instrument_tone)).lower()
        if tone not in TONES:
            tone = defaults.instrument_tone
        latency = str(data.get("audio_latency", defaults.audio_latency)).lower()
        if latency not in LATENCIES:
            latency = defaults.audio_latency
        try:
            volume = float(data.get("instrument_volume", defaults.instrument_volume))
        except (TypeError, ValueError):
            volume = defaults.instrument_volume
        if volume != volume:  # NaN
            volume = defaults.instrument_volume
        raw_dev = data.get("audio_device", defaults.audio_device)
        device = raw_dev.strip()[:200] if isinstance(raw_dev, str) else ""
        lo, hi = FIXED_STRINGS_RANGE
        fixed_strings = max(lo, min(hi, _int_or(data.get("instrument_fixed_strings"),
                                                defaults.instrument_fixed_strings)))
        raw_choices = data.get("audio_device_choices", ())
        choices = tuple(str(c) for c in raw_choices) if isinstance(raw_choices, (list, tuple)) else ()

        return cls(
            camera_index=max(0, int(data.get("camera_index", defaults.camera_index))),
            camera_backend=backend,
            mirror=bool(data.get("mirror", defaults.mirror)),
            dominant_hand=dom_str,
            pointer_sensitivity=round(
                max(0.10, min(3.00, float(data.get("pointer_sensitivity", defaults.pointer_sensitivity)))),
                2,
            ),
            smoothing_factor=round(
                max(0.00, min(1.00, float(data.get("smoothing_factor", defaults.smoothing_factor)))),
                2,
            ),
            pointer_mode=pointer_mode,
            pointer_speed=pointer_speed,
            pinch_on_threshold=pinch_on,
            pinch_off_threshold=pinch_off,
            detection_threshold=round(
                max(0.10, min(0.95, float(data.get("detection_threshold", defaults.detection_threshold)))),
                2,
            ),
            tracking_threshold=round(
                max(0.10, min(0.95, float(data.get("tracking_threshold", defaults.tracking_threshold)))),
                2,
            ),
            scroll_direction=scroll_dir,
            zoom_direction=zoom_dir,
            default_mode=mode_str,
            emergency_hotkey=hotkey,
            show_overlay=bool(data.get("show_overlay", defaults.show_overlay)),
            show_feedback_osd=bool(data.get("show_feedback_osd", defaults.show_feedback_osd)),
            show_mascot=bool(data.get("show_mascot", defaults.show_mascot)),
            hide_on_control=bool(data.get("hide_on_control", defaults.hide_on_control)),
            show_dry_run_panel=bool(data.get("show_dry_run_panel", defaults.show_dry_run_panel)),
            monitor_mapping=mon_map,
            start_with_windows=bool(data.get("start_with_windows", defaults.start_with_windows)),
            swipe_profile=swipe,
            auto_pause_s=auto_pause,
            dwell_click=bool(data.get("dwell_click", defaults.dwell_click)),
            dwell_ms=dwell_ms,
            click_sound=bool(data.get("click_sound", defaults.click_sound)),
            cursor_feedback=bool(data.get("cursor_feedback", defaults.cursor_feedback)),
            instrument_layout=layout,
            instrument_scale=scale,
            instrument_quantize=bool(data.get("instrument_quantize", defaults.instrument_quantize)),
            instrument_chords=_clean_chords(data.get("instrument_chords", defaults.instrument_chords)),
            instrument_volume=round(max(0.0, min(1.0, volume)), 2),
            instrument_tone=tone,
            audio_device=device,
            audio_latency=latency,
            instrument_particles=bool(data.get("instrument_particles", defaults.instrument_particles)),
            instrument_fixed_strings=fixed_strings,
            instrument_free_snap=bool(data.get("instrument_free_snap", defaults.instrument_free_snap)),
            audio_device_choices=choices,
        )


def _format_auto_pause(seconds: int) -> str:
    if seconds % 60 == 0:
        return f"{seconds // 60} dk"
    return f"{seconds} sn"


class SettingsDialog(QDialog):
    """Settings window with a category sidebar: Genel, İmleç, Hareketler, Enstrüman, Gelişmiş."""

    settings_applied = Signal(object)       # SettingsData
    settings_dict_applied = Signal(dict)    # dict[str, Any]
    export_settings_requested = Signal(str)  # target JSON path chosen in QFileDialog
    import_settings_requested = Signal(str)  # source JSON path chosen in QFileDialog
    diagnostics_requested = Signal()
    tutorial_requested = Signal()
    test_sound_requested = Signal(str)      # "Test sesi çal": selected audio device name ("" = default)

    def __init__(
        self,
        initial: SettingsData | Mapping[str, Any] | None = None,
        available_cameras: Optional[Sequence[tuple[int, str]]] = None,
        bridge: Optional[UiBridge] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._bridge = bridge
        self._syncing_preset = False
        self._available_cameras: list[tuple[int, str]] = (
            list(available_cameras)
            if available_cameras
            else [
                (0, "Kamera 0 (Varsayılan)"),
                (1, "Kamera 1 (Harici)"),
                (2, "Kamera 2"),
            ]
        )

        self.setWindowTitle("Holoscobe — Ayarlar")
        theme.install()
        self.resize(940, 720)
        self.setMinimumSize(760, 520)

        self._build_ui()

        if initial is not None:
            self.set_values(initial)
        else:
            self.set_values(SettingsData())

    # ---------- layout ----------

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        side = QFrame()
        side.setProperty("role", "sidebar")
        side.setFixedWidth(212)
        side_column = QVBoxLayout(side)
        side_column.setContentsMargins(12, 22, 12, 16)
        side_column.setSpacing(4)
        title = label("Ayarlar", "title")
        title.setContentsMargins(12, 0, 0, 12)
        side_column.addWidget(title)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().hide()
        self.side_group = QButtonGroup(self)
        for name, icon, build in (("Genel", "settings", self._build_general_tab),
                                  ("İmleç", "pointer", self._build_pointer_tab),
                                  ("Hareketler", "hand", self._build_gestures_tab),
                                  ("Enstrüman", "instrument", self._build_instrument_tab),
                                  ("Gelişmiş", "advanced", self._build_advanced_tab)):
            index = self.tabs.addTab(self._scroll(build()), name)
            item = SideItem(name, icon)
            item.clicked.connect(lambda _=False, i=index: self.tabs.setCurrentIndex(i))
            self.side_group.addButton(item, index)
            side_column.addWidget(item)
        self.tabs.currentChanged.connect(lambda i: self.side_group.button(i).setChecked(True))
        self.side_group.button(0).setChecked(True)
        side_column.addStretch(1)
        root.addWidget(side)

        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(0)
        content.addWidget(self.tabs, 1)
        footer = QFrame()
        footer.setProperty("role", "footer")
        btn_row = QHBoxLayout(footer)
        btn_row.setContentsMargins(20, 12, 24, 12)
        btn_row.setSpacing(8)
        self.btn_defaults = button("Varsayılanlara Sıfırla", "ghost", "undo")
        self.btn_save = button("Kaydet", "primary")
        self.btn_cancel = button("İptal")
        self.btn_save.setMinimumWidth(112)
        self.btn_cancel.setMinimumWidth(96)
        for b in (self.btn_defaults, self.btn_cancel):
            b.setAutoDefault(False)
        self.btn_save.setDefault(True)

        self.btn_defaults.clicked.connect(self.reset_to_defaults)
        self.btn_save.clicked.connect(self.save_and_accept)
        self.btn_cancel.clicked.connect(self.reject)

        btn_row.addWidget(self.btn_defaults)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_cancel)
        btn_row.addWidget(self.btn_save)
        content.addWidget(footer)
        root.addLayout(content, 1)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        theme.dark_title_bar(self)

    @staticmethod
    def _scroll(page: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setWidget(page)
        area.viewport().setAutoFillBackground(False)
        page.setAutoFillBackground(False)
        return area

    @staticmethod
    def _page(title: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        page.setProperty("role", "page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 22, 24, 28)
        layout.setSpacing(10)
        layout.addWidget(label(title, "title"))
        return page, layout

    @staticmethod
    def _section(layout: QVBoxLayout, title: str) -> Card:
        """Section heading and its card."""
        heading = label(title, "section")
        heading.setContentsMargins(2, 12, 0, 0)
        layout.addWidget(heading)
        card = Card()
        layout.addWidget(card)
        return card

    @staticmethod
    def _hint(text: str) -> QLabel:
        hint = label(text, "caption", True)
        hint.setContentsMargins(16, 11, 16, 12)
        return hint

    @staticmethod
    def _row(card: Card, title: str, description: str, control: QWidget, width: int = 0) -> None:
        if not width and isinstance(control, (QComboBox, QLineEdit)):
            width = CONTROL_WIDTH
        elif not width and isinstance(control, (SpinBox, DoubleSpinBox)):
            width = NUMBER_WIDTH
        card.add(SettingRow(title, description, control, width))

    @staticmethod
    def _slider_row(slider: QSlider, value: QLabel) -> QWidget:
        value.setProperty("role", "value")
        value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        value.setFixedWidth(52)
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(slider, 1)
        row.addWidget(value)
        box.setFixedWidth(CONTROL_WIDTH)
        return box

    def _build_general_tab(self) -> QWidget:
        page, layout = self._page("Genel")

        card = self._section(layout, "Kamera ve El")
        self.combo_camera = ComboBox()
        for idx, text in self._available_cameras:
            self.combo_camera.addItem(text, idx)
        self._row(card, "Kamera", "El hareketlerinin izlendiği kamera", self.combo_camera)
        self.chk_mirror = ToggleSwitch("Önizleme ve eşlemeyi aynala")
        self._row(card, "Ayna görüntüsü", "Önizleme ve eşlemeyi aynala", self.chk_mirror)
        self.combo_dominant_hand = ComboBox()
        self.combo_dominant_hand.addItem("Sağ El", "right")
        self.combo_dominant_hand.addItem("Sol El", "left")
        self._row(card, "Baskın el", "İmleci yöneten elin", self.combo_dominant_hand)

        card = self._section(layout, "Kontrol")
        self.combo_mode = ComboBox()
        for mode in Mode:
            self.combo_mode.addItem(create_mode_icon(mode, 16), MODE_LABELS_TR[mode], mode.value)
        self._row(card, "Varsayılan mod", "Uygulama açılınca seçili olan mod", self.combo_mode)
        self.combo_auto_pause = ComboBox()
        for seconds, text in AUTO_PAUSE_CHOICES:
            self.combo_auto_pause.addItem(text, seconds)
        self._row(card, "Otomatik duraklat", "El bu süre görünmezse kontrol kendiliğinden duraklar.",
                  self.combo_auto_pause)
        self.edit_hotkey = QLineEdit("Ctrl+Alt+Shift+F12")
        self.edit_hotkey.setPlaceholderText("Örn: Ctrl+Alt+Shift+F12")
        self._row(card, "Acil durdurma kısayolu", "Tüm girdileri bırakır ve kontrolü duraklatır", self.edit_hotkey)

        card = self._section(layout, "Görünüm ve Sistem")
        self.combo_monitor = ComboBox()
        self.combo_monitor.addItem("Tüm Ekranlar (Sanal Masaüstü)", "all")
        self.combo_monitor.addItem("Yalnız Birincil Ekran", "primary")
        self.combo_monitor.addItem("Yalnız İkincil Ekran", "secondary")
        self._row(card, "Monitör eşlemesi", "İmlecin gezebildiği ekranlar", self.combo_monitor)
        self.chk_overlay = ToggleSwitch("Mod ve pencere eylem katmanını göster")
        self._row(card, "Mod ve pencere eylem katmanını göster", "Mod çarkı, pencere menüsü ve durum göstergesi",
                  self.chk_overlay)
        self.chk_feedback = ToggleSwitch("Kısa durum bildirimlerini göster")
        self._row(card, "Kısa durum bildirimlerini göster", "Mod değişince ya da kontrol açılınca kısa mesaj",
                  self.chk_feedback)
        self.chk_mascot = ToggleSwitch("Sağ alttaki kediyi göster")
        self._row(card, "Sağ alttaki kediyi göster", "El hareketlerini taklit eden küçük kedi", self.chk_mascot)
        self.chk_hide_on_control = ToggleSwitch("Kontrol başlayınca ana pencereyi küçült")
        self._row(card, "Kontrol başlayınca ana pencereyi küçült",
                  "Masaüstünü kullanırken kamera paneli gizlenir, kedi sağ altta kalır", self.chk_hide_on_control)
        self.chk_startup = ToggleSwitch("Windows açılışında otomatik başlat")
        self._row(card, "Windows açılışında otomatik başlat", "Oturum açınca Holoscobe hazır olur", self.chk_startup)

        layout.addStretch(1)
        return page

    def _build_pointer_tab(self) -> QWidget:
        page, layout = self._page("İmleç")

        card = self._section(layout, "Hareket")
        self.combo_preset = ComboBox()
        for key in (*SENSITIVITY_PRESETS, "custom"):
            self.combo_preset.addItem(SENSITIVITY_PRESET_LABELS_TR[key], key)
        self.combo_preset.currentIndexChanged.connect(self._on_preset_selected)
        self._row(card, "Hassasiyet ön ayarı", "Hız ve hassasiyeti birlikte değiştirir", self.combo_preset)

        self.combo_pointer_mode = ComboBox()
        for mode_key in POINTER_MODES:
            self.combo_pointer_mode.addItem(POINTER_MODE_LABELS_TR[mode_key], mode_key)
        self._row(card, "İmleç türü", "El hareketinin imlece nasıl aktarıldığı", self.combo_pointer_mode)

        self.slider_pointer_speed = QSlider(Qt.Orientation.Horizontal)
        self.slider_pointer_speed.setRange(round(POINTER_SPEED_MIN * _SPEED_STEPS),
                                           round(POINTER_SPEED_MAX * _SPEED_STEPS))
        self.slider_pointer_speed.setSingleStep(1)
        self.slider_pointer_speed.setPageStep(1)
        self.label_pointer_speed = QLabel()
        self.slider_pointer_speed.valueChanged.connect(self._update_speed_label)
        self._row(card, "İmleç hızı", "Yalnız göreli imleçte geçerli",
                  self._slider_row(self.slider_pointer_speed, self.label_pointer_speed))
        self.set_pointer_speed(1.0)

        self.spin_sensitivity = self._make_double_spin(0.10, 3.00, 0.05, 1.00)
        self.spin_sensitivity.valueChanged.connect(self._sync_preset_from_values)
        self._row(card, "İmleç hassasiyeti", "Büyük değer: küçük hareket daha uzağa gider", self.spin_sensitivity)

        self.spin_smoothing = self._make_double_spin(0.00, 1.00, 0.05, 0.50)
        self._row(card, "Yumuşatma oranı", "Büyük değer: daha az titreme, biraz daha gecikme", self.spin_smoothing)

        card = self._section(layout, "Tıklama ve Geri Bildirim")
        self.chk_dwell_click = ToggleSwitch("Bekleyerek tıkla (imleç sabit kalınca sol tık)")
        self.chk_dwell_click.toggled.connect(self._update_dwell_enabled)
        self._row(card, "Bekleyerek tıkla", "İmleç sabit kalınca sol tık", self.chk_dwell_click)

        self.slider_dwell_ms = QSlider(Qt.Orientation.Horizontal)
        self.slider_dwell_ms.setRange(DWELL_MS_MIN // _DWELL_UNIT_MS, DWELL_MS_MAX // _DWELL_UNIT_MS)
        self.slider_dwell_ms.setSingleStep(2)
        self.slider_dwell_ms.setPageStep(4)
        self.label_dwell_ms = QLabel()
        self.slider_dwell_ms.valueChanged.connect(self._update_dwell_label)
        self._row(card, "Bekleme süresi", "İmlecin sabit kalması gereken süre",
                  self._slider_row(self.slider_dwell_ms, self.label_dwell_ms))
        self.set_dwell_ms(1000)

        self.chk_click_sound = ToggleSwitch("Tık ve komutlarda kısa ses çal")
        self._row(card, "Tık sesi", "Tık ve komutlarda kısa ses çal", self.chk_click_sound)
        self.chk_cursor_feedback = ToggleSwitch("Basılı tutma sırasında imlecin yanında ilerleme halkası göster")
        self._row(card, "İmleç halkası", "Basılı tutma sırasında imlecin yanında ilerleme halkası göster",
                  self.chk_cursor_feedback)

        layout.addStretch(1)
        return page

    def _build_gestures_tab(self) -> QWidget:
        page, layout = self._page("Hareketler")

        card = self._section(layout, "Pinch")
        self.spin_pinch_on = self._make_double_spin(0.10, 0.60, 0.01, 0.33)
        self._row(card, "Başlatma eşiği", "Parmaklar bu kadar yaklaşınca pinch başlar (avuç birimi)",
                  self.spin_pinch_on)
        self.spin_pinch_off = self._make_double_spin(0.15, 0.85, 0.01, 0.48)
        self._row(card, "Bırakma eşiği", "Parmaklar bu kadar ayrılınca pinch biter (avuç birimi)",
                  self.spin_pinch_off)

        card = self._section(layout, "Yönler ve Komutlar")
        self.combo_scroll_dir = ComboBox()
        self.combo_scroll_dir.addItem("Doğal (Yukarı = Yukarı)", "natural")
        self.combo_scroll_dir.addItem("Ters (Yukarı = Aşağı)", "reverse")
        self._row(card, "Kaydırma yönü", "Kaydırma modunda elin yönü", self.combo_scroll_dir)

        self.combo_zoom_dir = ComboBox()
        self.combo_zoom_dir.addItem("Doğal (Eller Açılınca Yakınlaş)", "natural")
        self.combo_zoom_dir.addItem("Ters (Eller Açılınca Uzaklaş)", "reverse")
        self._row(card, "Yakınlaştırma yönü", "Yakınlaştırma modunda ellerin yönü", self.combo_zoom_dir)

        self.combo_swipe_profile = ComboBox()
        for key, text in SWIPE_PROFILE_LABELS_TR.items():
            self.combo_swipe_profile.addItem(text, key)
        self._row(card, "Kaydırma profili", "Komutlar modunda sola/sağa kaydırmanın anlamı. Otomatik: ön plandaki "
                  "uygulamaya göre seçilir (sunum, tarayıcı, medya ya da sanal masaüstleri).", self.combo_swipe_profile)

        layout.addStretch(1)
        return page

    def _build_instrument_tab(self) -> QWidget:
        page, layout = self._page("Enstrüman")

        card = self._section(layout, "Çalış")
        self.combo_instrument_layout = ComboBox()
        for key in LAYOUTS:
            self.combo_instrument_layout.addItem(INSTRUMENT_LAYOUT_LABELS_TR.get(key, key), key)
        self._row(card, "Düzen", "Solo: tek tel, eller arası uzaklık perdeyi belirler. Akor: dört tel, tel eli "
                  "yüksekliği akoru seçer. Sabit teller: teller ekranda durur, iki elle de çalınır. "
                  "Serbest teller: telleri kendin çizersin, istediğin yere ve boyda.", self.combo_instrument_layout)
        self.combo_instrument_scale = ComboBox()
        for key in SCALE_NAMES:
            self.combo_instrument_scale.addItem(INSTRUMENT_SCALE_LABELS_TR.get(key, key), key)
        self._row(card, "Dizi", "Çalınabilecek notalar", self.combo_instrument_scale)
        self.chk_instrument_quantize = ToggleSwitch("Diziye kilitle")
        self._row(card, "Diziye kilitle", "Perdeler dizinin en yakın notasına oturur", self.chk_instrument_quantize)

        card = self._section(layout, "Teller")
        self.spin_instrument_fixed_strings = SpinBox()
        self.spin_instrument_fixed_strings.setRange(*FIXED_STRINGS_RANGE)
        self._row(card, "Tel sayısı (sabit)", "Sabit teller düzenindeki tel sayısı", self.spin_instrument_fixed_strings)
        card.add(self._hint(
            "Telleri taşımak ya da boyutlandırmak için: Enstrüman penceresinde fareyle sürükle (köşeden "
            "boyutlandır) ya da iki elinle çimdikle, yarım saniye tut, gerdir ve bırak."))
        self.chk_instrument_free_snap = ToggleSwitch("Serbest tellerde hizalama yardımı")
        self._row(card, "Serbest tellerde hizalama yardımı", "Açıksa yakın getirdiğin tel düzleşir ve diğer telin "
                  "üstüne hizalanır; kapalıysa tel tam bıraktığın yerde kalır.", self.chk_instrument_free_snap)
        card.add(self._hint(
            "Serbest teller: boş yerde çimdikle, yarım saniye tut, çekerek tel çiz. Telin ucunu tutup boyutlandır, "
            "ortasından tutup taşı. İki elle bir telin iki ucunu tutabilirsin. Teli çok kısaltıp bırakırsan silinir."))

        card = self._section(layout, "Akorlar (Akor düzeni)")
        self.combo_chords: list[QComboBox] = []
        for zone_label in CHORD_ZONE_LABELS_TR:
            combo = ComboBox()
            for name in CHORD_NAMES:
                combo.addItem(name, name)
            self._row(card, zone_label, "", combo, NUMBER_WIDTH)
            self.combo_chords.append(combo)

        card = self._section(layout, "Ses")
        self.slider_instrument_volume = QSlider(Qt.Orientation.Horizontal)
        self.slider_instrument_volume.setRange(0, 100)
        self.slider_instrument_volume.setSingleStep(5)
        self.slider_instrument_volume.setPageStep(10)
        self.label_instrument_volume = QLabel()
        self.slider_instrument_volume.valueChanged.connect(self._update_volume_label)
        self._row(card, "Ses düzeyi", "Enstrümanın sesi; sistem sesini değiştirmez",
                  self._slider_row(self.slider_instrument_volume, self.label_instrument_volume))
        self.combo_instrument_tone = ComboBox()
        for key in TONES:
            self.combo_instrument_tone.addItem(INSTRUMENT_TONE_LABELS_TR.get(key, key), key)
        self._row(card, "Tını", "Telin ses rengi", self.combo_instrument_tone)
        self.combo_audio_device = ComboBox()
        self._row(card, "Ses cihazı", "Enstrümanın çaldığı çıkış", self.combo_audio_device)
        self.btn_test_sound = button("Test sesi çal", "", "sound_test")
        self.btn_test_sound.clicked.connect(self.request_test_sound)
        self._row(card, "Cihazı dene", "Seçili cihazdan kısa bir nota çalar", self.btn_test_sound)
        self.combo_audio_latency = ComboBox()
        for key in LATENCIES:
            self.combo_audio_latency.addItem(AUDIO_LATENCY_LABELS_TR.get(key, key), key)
        self._row(card, "Gecikme", "Ses kesik kesik gelirse gecikmeyi Normal yapın.", self.combo_audio_latency)

        card = self._section(layout, "Görünüm")
        self.chk_instrument_particles = ToggleSwitch("Kıvılcım efektleri")
        self._row(card, "Kıvılcım efektleri", "Tele vurunca kıvılcım saçar", self.chk_instrument_particles)

        layout.addStretch(1)
        return page

    # ---------- instrument ----------

    def instrument_volume(self) -> float:
        return round(self.slider_instrument_volume.value() / 100.0, 2)

    @Slot()
    def _update_volume_label(self, *_: Any) -> None:
        self.label_instrument_volume.setText(f"%{self.slider_instrument_volume.value()}")

    def _set_audio_devices(self, choices: Sequence[str], selected: str) -> None:
        """Fill Ses cihazı: Sistem varsayılanı first, then choices; a stored unknown device is kept."""
        self._audio_device_choices = tuple(choices)
        combo = self.combo_audio_device
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(AUDIO_DEFAULT_DEVICE_LABEL_TR, "")
        for name in choices:
            if name and combo.findData(name) < 0:
                combo.addItem(name, name)
        if selected and combo.findData(selected) < 0:
            combo.addItem(f"{selected} (bulunamadı)", selected)
        idx = combo.findData(selected)
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.blockSignals(False)

    def selected_audio_device(self) -> str:
        return str(self.combo_audio_device.currentData() or "")

    @Slot()
    def request_test_sound(self) -> None:
        self.test_sound_requested.emit(self.selected_audio_device())

    def _build_advanced_tab(self) -> QWidget:
        page, layout = self._page("Gelişmiş")

        card = self._section(layout, "Kamera ve Takip")
        self.combo_backend = ComboBox()
        self.combo_backend.addItem("Media Foundation (Önerilen)", "media_foundation")
        self.combo_backend.addItem("DirectShow (Yedek)", "directshow")
        self._row(card, "Kamera altyapısı", "Kamera açılmıyorsa diğerini dene", self.combo_backend)
        self.spin_detection = self._make_double_spin(0.10, 0.95, 0.05, 0.55)
        self._row(card, "Algılama güven eşiği", "Elin ilk bulunması için gereken güven", self.spin_detection)
        self.spin_tracking = self._make_double_spin(0.10, 0.95, 0.05, 0.55)
        self._row(card, "Takip güven eşiği", "Elin izlenmeye devam etmesi için gereken güven", self.spin_tracking)
        self.chk_dry_run = ToggleSwitch("Dry-run komut panelini göster")
        self._row(card, "Dry-run komut panelini göster", "Komutsuz denemede üretilecek komutları listeler",
                  self.chk_dry_run)

        card = self._section(layout, "Araçlar")
        self.btn_export = button("Ayarları dışa aktar…", "", "export")
        self.btn_import = button("Ayarları içe aktar…", "", "import")
        self.btn_diagnostics = button("Tanılama raporu oluştur", "", "report")
        self.btn_tutorial = button("Eğitimi başlat", "", "learn")
        for title, description, b in (
                ("Yedekle", "Bütün ayarları bir dosyaya yazar", self.btn_export),
                ("Geri yükle", "Daha önce dışa aktarılan ayarları okur", self.btn_import),
                ("Tanılama", "Tanılama raporu kamera, ekran ve ayar bilgilerini paylaşılabilir bir dosyaya yazar.",
                 self.btn_diagnostics),
                ("Eğitim", "Temel el hareketlerini adım adım gösterir", self.btn_tutorial)):
            b.setAutoDefault(False)
            self._row(card, title, description, b, CONTROL_WIDTH - 24)
        self.btn_test_sound.setAutoDefault(False)

        self.btn_export.clicked.connect(self.request_export)
        self.btn_import.clicked.connect(self.request_import)
        self.btn_diagnostics.clicked.connect(self.diagnostics_requested.emit)
        self.btn_tutorial.clicked.connect(self.tutorial_requested.emit)

        layout.addStretch(1)
        return page

    @staticmethod
    def _make_double_spin(
        minimum: float,
        maximum: float,
        step: float,
        value: float,
    ) -> QDoubleSpinBox:
        spin = DoubleSpinBox()
        spin.setDecimals(2)
        spin.setRange(minimum, maximum)
        spin.setSingleStep(step)
        spin.setValue(value)
        return spin

    # ---------- pointer speed / preset ----------

    def pointer_speed(self) -> float:
        """Current slider value as a speed multiplier (0.5 .. 2.0, step 0.1)."""
        return round(self.slider_pointer_speed.value() / _SPEED_STEPS, 1)

    def set_pointer_speed(self, speed: float) -> None:
        clamped = max(POINTER_SPEED_MIN, min(POINTER_SPEED_MAX, float(speed)))
        self.slider_pointer_speed.setValue(round(clamped * _SPEED_STEPS))
        self._update_speed_label()

    @Slot()
    def _update_speed_label(self, *_: Any) -> None:
        self.label_pointer_speed.setText(f"{self.pointer_speed():.1f}×")
        self._sync_preset_from_values()

    def current_preset(self) -> str:
        """Selected Hassasiyet ön ayarı key: precise, normal, fast or custom."""
        return str(self.combo_preset.currentData() or "custom") if hasattr(self, "combo_preset") else "custom"

    def apply_preset(self, key: str) -> None:
        """Select a preset; non-custom presets set pointer_speed and pointer_sensitivity."""
        self._set_combo_by_data(self.combo_preset, key)

    @Slot(int)
    def _on_preset_selected(self, _index: int) -> None:
        if self._syncing_preset:
            return
        values = SENSITIVITY_PRESETS.get(self.current_preset())
        if values is None:
            return
        self._syncing_preset = True
        try:
            self.set_pointer_speed(values[0])
            self.spin_sensitivity.setValue(values[1])
        finally:
            self._syncing_preset = False

    @Slot()
    def _sync_preset_from_values(self, *_: Any) -> None:
        """User edited speed or sensitivity: show the matching preset, or Özel."""
        if self._syncing_preset or not hasattr(self, "spin_sensitivity") or not hasattr(self, "combo_preset"):
            return
        key = preset_for(self.pointer_speed(), round(float(self.spin_sensitivity.value()), 2))
        self._syncing_preset = True
        try:
            self._set_combo_by_data(self.combo_preset, key)
        finally:
            self._syncing_preset = False

    # ---------- dwell ----------

    def dwell_ms(self) -> int:
        return int(self.slider_dwell_ms.value() * _DWELL_UNIT_MS)

    def set_dwell_ms(self, ms: int) -> None:
        clamped = max(DWELL_MS_MIN, min(DWELL_MS_MAX, int(ms)))
        self.slider_dwell_ms.setValue(round(clamped / _DWELL_UNIT_MS))
        self._update_dwell_label()

    @Slot()
    def _update_dwell_label(self, *_: Any) -> None:
        self.label_dwell_ms.setText(f"{self.dwell_ms() / 1000:.2f}".rstrip("0").rstrip(".").replace(".", ",") + " sn")

    @Slot(bool)
    def _update_dwell_enabled(self, *_: Any) -> None:
        on = self.chk_dwell_click.isChecked()
        self.slider_dwell_ms.setEnabled(on)
        self.label_dwell_ms.setEnabled(on)

    # ---------- auto pause ----------

    def _set_auto_pause(self, seconds: int) -> None:
        idx = self.combo_auto_pause.findData(int(seconds))
        if idx < 0:   # value from config not in the preset list: keep it (round-trip safe)
            self.combo_auto_pause.addItem(_format_auto_pause(int(seconds)), int(seconds))
            idx = self.combo_auto_pause.count() - 1
        self.combo_auto_pause.setCurrentIndex(idx)

    # ---------- file dialogs (overridable in tests) ----------

    def _ask_export_path(self) -> str:
        path, _ = QFileDialog.getSaveFileName(
            self, "Ayarları dışa aktar", "holoscobe-ayarlar.json", "JSON dosyası (*.json)")
        return path

    def _ask_import_path(self) -> str:
        path, _ = QFileDialog.getOpenFileName(
            self, "Ayarları içe aktar", "", "JSON dosyası (*.json)")
        return path

    @Slot()
    def request_export(self) -> None:
        path = self._ask_export_path()
        if path:
            self.export_settings_requested.emit(path)

    @Slot()
    def request_import(self) -> None:
        path = self._ask_import_path()
        if path:
            self.import_settings_requested.emit(path)

    # ---------- values ----------

    def _set_combo_by_data(self, combo: QComboBox, data_value: Any) -> None:
        idx = combo.findData(data_value)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        elif isinstance(data_value, int):
            combo.addItem(f"Kamera {data_value}", data_value)
            combo.setCurrentIndex(combo.count() - 1)

    def set_values(self, values: SettingsData | Mapping[str, Any]) -> None:
        """Populate UI controls from a SettingsData instance or dictionary."""
        cfg = (
            values
            if isinstance(values, SettingsData)
            else SettingsData.from_dict(values)
        )
        self._set_combo_by_data(self.combo_camera, cfg.camera_index)
        self._set_combo_by_data(self.combo_backend, cfg.camera_backend)
        self.chk_mirror.setChecked(cfg.mirror)
        self._set_combo_by_data(self.combo_dominant_hand, cfg.dominant_hand)
        self._set_combo_by_data(self.combo_pointer_mode, cfg.pointer_mode)
        self.set_pointer_speed(cfg.pointer_speed)
        self.spin_sensitivity.setValue(cfg.pointer_sensitivity)
        self._sync_preset_from_values()
        self.spin_smoothing.setValue(cfg.smoothing_factor)
        self.spin_pinch_on.setValue(cfg.pinch_on_threshold)
        self.spin_pinch_off.setValue(cfg.pinch_off_threshold)
        self.spin_detection.setValue(cfg.detection_threshold)
        self.spin_tracking.setValue(cfg.tracking_threshold)
        self._set_combo_by_data(self.combo_scroll_dir, cfg.scroll_direction)
        self._set_combo_by_data(self.combo_zoom_dir, cfg.zoom_direction)
        self._set_combo_by_data(self.combo_mode, cfg.default_mode)
        self.edit_hotkey.setText(cfg.emergency_hotkey)
        self.chk_overlay.setChecked(cfg.show_overlay)
        self.chk_feedback.setChecked(cfg.show_feedback_osd)
        self.chk_mascot.setChecked(cfg.show_mascot)
        self.chk_hide_on_control.setChecked(cfg.hide_on_control)
        self.chk_dry_run.setChecked(cfg.show_dry_run_panel)
        self._set_combo_by_data(self.combo_monitor, cfg.monitor_mapping)
        self.chk_startup.setChecked(cfg.start_with_windows)
        self._set_combo_by_data(self.combo_swipe_profile, cfg.swipe_profile)
        self._set_auto_pause(cfg.auto_pause_s)
        self.chk_dwell_click.setChecked(cfg.dwell_click)
        self.set_dwell_ms(cfg.dwell_ms)
        self._update_dwell_enabled()
        self.chk_click_sound.setChecked(cfg.click_sound)
        self.chk_cursor_feedback.setChecked(cfg.cursor_feedback)
        self._set_combo_by_data(self.combo_instrument_layout, cfg.instrument_layout)
        self._set_combo_by_data(self.combo_instrument_scale, cfg.instrument_scale)
        self.chk_instrument_quantize.setChecked(cfg.instrument_quantize)
        for combo, name in zip(self.combo_chords, _clean_chords(cfg.instrument_chords)):
            self._set_combo_by_data(combo, name)
        self.slider_instrument_volume.setValue(round(max(0.0, min(1.0, cfg.instrument_volume)) * 100))
        self._update_volume_label()
        self._set_combo_by_data(self.combo_instrument_tone, cfg.instrument_tone)
        # An empty choice list (e.g. reset to defaults) keeps the devices already listed.
        choices = cfg.audio_device_choices or getattr(self, "_audio_device_choices", ())
        self._set_audio_devices(choices, cfg.audio_device)
        self._set_combo_by_data(self.combo_audio_latency, cfg.audio_latency)
        self.chk_instrument_particles.setChecked(cfg.instrument_particles)
        self.spin_instrument_fixed_strings.setValue(int(cfg.instrument_fixed_strings))
        self.chk_instrument_free_snap.setChecked(bool(cfg.instrument_free_snap))

    def get_settings(self) -> SettingsData:
        """Read current UI control values as a validated SettingsData instance."""
        hotkey = self.edit_hotkey.text().strip() or "Ctrl+Alt+Shift+F12"
        return SettingsData(
            camera_index=int(self.combo_camera.currentData() or 0),
            camera_backend=str(self.combo_backend.currentData() or "media_foundation"),
            mirror=bool(self.chk_mirror.isChecked()),
            dominant_hand=str(self.combo_dominant_hand.currentData() or "right"),
            pointer_mode=str(self.combo_pointer_mode.currentData() or "relative"),
            pointer_speed=self.pointer_speed(),
            pointer_sensitivity=round(float(self.spin_sensitivity.value()), 2),
            smoothing_factor=round(float(self.spin_smoothing.value()), 2),
            pinch_on_threshold=round(float(self.spin_pinch_on.value()), 2),
            pinch_off_threshold=round(float(self.spin_pinch_off.value()), 2),
            detection_threshold=round(float(self.spin_detection.value()), 2),
            tracking_threshold=round(float(self.spin_tracking.value()), 2),
            scroll_direction=str(self.combo_scroll_dir.currentData() or "natural"),
            zoom_direction=str(self.combo_zoom_dir.currentData() or "natural"),
            default_mode=str(self.combo_mode.currentData() or Mode.POINTER.value),
            emergency_hotkey=hotkey,
            show_overlay=bool(self.chk_overlay.isChecked()),
            show_feedback_osd=bool(self.chk_feedback.isChecked()),
            show_mascot=bool(self.chk_mascot.isChecked()),
            hide_on_control=bool(self.chk_hide_on_control.isChecked()),
            show_dry_run_panel=bool(self.chk_dry_run.isChecked()),
            monitor_mapping=str(self.combo_monitor.currentData() or "all"),
            start_with_windows=bool(self.chk_startup.isChecked()),
            swipe_profile=str(self.combo_swipe_profile.currentData() or "auto"),
            auto_pause_s=int(self.combo_auto_pause.currentData() or 0),
            dwell_click=bool(self.chk_dwell_click.isChecked()),
            dwell_ms=self.dwell_ms(),
            click_sound=bool(self.chk_click_sound.isChecked()),
            cursor_feedback=bool(self.chk_cursor_feedback.isChecked()),
            instrument_layout=str(self.combo_instrument_layout.currentData() or "free"),
            instrument_scale=str(self.combo_instrument_scale.currentData() or "e_minor_pentatonic"),
            instrument_quantize=bool(self.chk_instrument_quantize.isChecked()),
            instrument_chords=_clean_chords([c.currentData() for c in self.combo_chords]),
            instrument_volume=self.instrument_volume(),
            instrument_tone=str(self.combo_instrument_tone.currentData() or "clean"),
            audio_device=self.selected_audio_device(),
            audio_latency=str(self.combo_audio_latency.currentData() or "low"),
            instrument_particles=bool(self.chk_instrument_particles.isChecked()),
            instrument_fixed_strings=int(self.spin_instrument_fixed_strings.value()),
            instrument_free_snap=bool(self.chk_instrument_free_snap.isChecked()),
            audio_device_choices=tuple(getattr(self, "_audio_device_choices", ())),
        )

    def get_values_dict(self) -> dict[str, Any]:
        """Read current UI control values as a plain dictionary."""
        return self.get_settings().to_dict()

    @Slot()
    def reset_to_defaults(self) -> None:
        """Reset all controls to safe default SettingsData values."""
        self.set_values(SettingsData())

    @Slot()
    def save_and_accept(self) -> SettingsData:
        """Emit settings_applied / settings_dict_applied signals and close dialog."""
        data = self.get_settings()
        as_dict = data.to_dict()
        self.settings_applied.emit(data)
        self.settings_dict_applied.emit(as_dict)
        if self._bridge is not None:
            self._bridge.settings_saved.emit(data)
            self._bridge.update_status(
                mirrored=data.mirror,
                mode=Mode(data.default_mode),
                dry_run=data.show_dry_run_panel,
            )
        self.accept()
        return data


# Alias for convenience
SettingsWindow = SettingsDialog
