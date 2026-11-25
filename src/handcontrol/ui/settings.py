"""Settings dataclass and configuration dialog for Holoscobe.

All user-visible strings are in Turkish.
Supports round-trip serialization as both a dataclass (`SettingsData`) and a
plain dictionary (`dict[str, Any]`).
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, fields
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

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

from handcontrol.contracts import Mode
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


def _number_or(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


_CHOICES: dict[str, tuple[str, ...]] = {
    "camera_backend": ("media_foundation", "directshow"), "dominant_hand": ("right", "left"),
    "pointer_mode": POINTER_MODES, "scroll_direction": ("natural", "reverse"), "zoom_direction": ("natural", "reverse"),
    "default_mode": tuple(m.value for m in Mode), "monitor_mapping": ("all", "primary", "secondary"),
    "swipe_profile": SWIPE_PROFILES, "instrument_layout": LAYOUTS, "instrument_scale": SCALE_NAMES,
    "instrument_tone": TONES, "audio_latency": LATENCIES,
}
_RANGES: dict[str, tuple[float, float, int]] = {      # lowest, highest, digits (0: whole number)
    "camera_index": (0, 16, 0), "pointer_sensitivity": (0.10, 3.00, 2), "smoothing_factor": (0.0, 1.0, 2),
    "pointer_speed": (POINTER_SPEED_MIN, POINTER_SPEED_MAX, 1), "pinch_on_threshold": (0.10, 0.60, 2),
    "pinch_off_threshold": (0.15, 0.85, 2), "detection_threshold": (0.10, 0.95, 2), "tracking_threshold": (0.10, 0.95, 2),
    "auto_pause_s": (0, AUTO_PAUSE_MAX_S, 0), "dwell_ms": (DWELL_MS_MIN, DWELL_MS_MAX, 0),
    "instrument_volume": (0.0, 1.0, 2), "instrument_fixed_strings": (*FIXED_STRINGS_RANGE, 0),
}


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
        raw = {"default_mode": data.get("mode", cls.default_mode), **data}
        out: dict[str, Any] = {}
        for f in fields(cls):
            value = raw.get(f.name, f.default)
            if f.name in _CHOICES:
                value = str(getattr(value, "value", value)).lower()
                out[f.name] = value if value in _CHOICES[f.name] else f.default
            elif f.name in _RANGES:
                lo, hi, digits = _RANGES[f.name]
                number = max(lo, min(hi, _number_or(value, f.default)))
                out[f.name] = round(number, digits) if digits else int(number)
            elif isinstance(f.default, bool):
                out[f.name] = bool(value)
            elif isinstance(f.default, str):
                out[f.name] = (value.strip()[:200] if isinstance(value, str) else "") or f.default
        if 0 < out["auto_pause_s"] < 10:
            out["auto_pause_s"] = 10
        out["dwell_ms"] = round(out["dwell_ms"] / _DWELL_UNIT_MS) * _DWELL_UNIT_MS
        out["instrument_chords"] = _clean_chords(raw.get("instrument_chords"))
        choices = raw.get("audio_device_choices")
        out["audio_device_choices"] = tuple(map(str, choices)) if isinstance(choices, (list, tuple)) else ()
        return cls(**out)


def _format_auto_pause(seconds: int) -> str:
    if seconds % 60 == 0:
        return f"{seconds // 60} dk"
    return f"{seconds} sn"


class SettingsDialog(QDialog):
    """Settings window with a category sidebar: Genel, İmleç, Hareketler, Enstrüman, Gelişmiş."""

    settings_applied = Signal(object)       # SettingsData
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
        self._available_cameras = available_cameras or (
            (0, "Kamera 0 (Varsayılan)"), (1, "Kamera 1 (Harici)"), (2, "Kamera 2"))

        self.setWindowTitle("Holoscobe — Ayarlar")
        theme.install()
        self.resize(940, 720)
        self.setMinimumSize(760, 520)

        self._audio_device_choices: tuple[str, ...] = ()
        self._fields: dict[str, QWidget] = {}          # SettingsData field -> control with the same value
        self._build_ui()
        self.set_values(initial if initial is not None else SettingsData())

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

    def _combo(self, card: Card, field: str, title: str, description: str,
               items: Iterable[tuple[str, Any]], width: int = 0) -> QComboBox:
        """Row with a list; items are (text, value)."""
        combo = ComboBox()
        for text, value in items:
            combo.addItem(text, value)
        self._row(card, title, description, combo, width)
        if field:
            self._fields[field] = combo
        return combo

    def _toggle(self, card: Card, field: str, title: str, description: str, name: str = "") -> ToggleSwitch:
        """Row with a switch; `name` is read out instead of the title."""
        toggle = ToggleSwitch(name or title)
        self._row(card, title, description, toggle)
        self._fields[field] = toggle
        return toggle

    def _number(self, card: Card, field: str, title: str, description: str, step: float) -> QDoubleSpinBox:
        spin = DoubleSpinBox()
        spin.setDecimals(2)
        spin.setRange(*_RANGES[field][:2])
        spin.setSingleStep(step)
        spin.setValue(getattr(SettingsData, field))
        self._row(card, title, description, spin)
        self._fields[field] = spin
        return spin

    def _slider(self, card: Card, title: str, description: str, lo: int, hi: int, step: int, page: int,
                changed: Callable[..., None]) -> tuple[QSlider, QLabel]:
        """Row with a slider and its value text, which `changed` keeps current."""
        slider, value = QSlider(Qt.Orientation.Horizontal), QLabel()
        slider.setRange(lo, hi)
        slider.setSingleStep(step)
        slider.setPageStep(page)
        slider.valueChanged.connect(changed)
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
        self._row(card, title, description, box)
        return slider, value

    def _build_general_tab(self) -> QWidget:
        page, layout = self._page("Genel")

        card = self._section(layout, "Kamera ve El")
        self.combo_camera = self._combo(card, "camera_index", "Kamera", "El hareketlerinin izlendiği kamera",
                                        ((text, idx) for idx, text in self._available_cameras))
        self.chk_mirror = self._toggle(card, "mirror", "Ayna görüntüsü", "Önizleme ve eşlemeyi aynala",
                                       "Önizleme ve eşlemeyi aynala")
        self.combo_dominant_hand = self._combo(card, "dominant_hand", "Baskın el", "İmleci yöneten elin",
                                               (("Sağ El", "right"), ("Sol El", "left")))

        card = self._section(layout, "Kontrol")
        self.combo_mode = self._combo(card, "default_mode", "Varsayılan mod", "Uygulama açılınca seçili olan mod",
                                      ((MODE_LABELS_TR[mode], mode.value) for mode in Mode))
        for i, mode in enumerate(Mode):
            self.combo_mode.setItemIcon(i, create_mode_icon(mode, 16))
        self.combo_auto_pause = self._combo(card, "", "Otomatik duraklat",
                                            "El bu süre görünmezse kontrol kendiliğinden duraklar.",
                                            ((text, seconds) for seconds, text in AUTO_PAUSE_CHOICES))
        self.edit_hotkey = QLineEdit(SettingsData.emergency_hotkey)
        self.edit_hotkey.setPlaceholderText(f"Örn: {SettingsData.emergency_hotkey}")
        self._row(card, "Acil durdurma kısayolu", "Tüm girdileri bırakır ve kontrolü duraklatır", self.edit_hotkey)

        card = self._section(layout, "Görünüm ve Sistem")
        self.combo_monitor = self._combo(card, "monitor_mapping", "Monitör eşlemesi", "İmlecin gezebildiği ekranlar", (
            ("Tüm Ekranlar (Sanal Masaüstü)", "all"), ("Yalnız Birincil Ekran", "primary"),
            ("Yalnız İkincil Ekran", "secondary")))
        self.chk_overlay = self._toggle(card, "show_overlay", "Mod ve pencere eylem katmanını göster",
                                        "Mod çarkı, pencere menüsü ve durum göstergesi")
        self.chk_feedback = self._toggle(card, "show_feedback_osd", "Kısa durum bildirimlerini göster",
                                         "Mod değişince ya da kontrol açılınca kısa mesaj")
        self.chk_mascot = self._toggle(card, "show_mascot", "Sağ alttaki kediyi göster",
                                       "El hareketlerini taklit eden küçük kedi")
        self.chk_startup = self._toggle(card, "start_with_windows", "Windows açılışında otomatik başlat",
                                        "Oturum açınca Holoscobe hazır olur")

        layout.addStretch(1)
        return page

    def _build_pointer_tab(self) -> QWidget:
        page, layout = self._page("İmleç")

        card = self._section(layout, "Hareket")
        self.combo_preset = self._combo(card, "", "Hassasiyet ön ayarı", "Hız ve hassasiyeti birlikte değiştirir", (
            (SENSITIVITY_PRESET_LABELS_TR[key], key) for key in (*SENSITIVITY_PRESETS, "custom")))
        self.combo_preset.currentIndexChanged.connect(self._on_preset_selected)
        self.combo_pointer_mode = self._combo(card, "pointer_mode", "İmleç türü",
                                              "El hareketinin imlece nasıl aktarıldığı",
                                              ((POINTER_MODE_LABELS_TR[key], key) for key in POINTER_MODES))
        self.slider_pointer_speed, self.label_pointer_speed = self._slider(
            card, "İmleç hızı", "Yalnız göreli imleçte geçerli", round(POINTER_SPEED_MIN * _SPEED_STEPS),
            round(POINTER_SPEED_MAX * _SPEED_STEPS), 1, 1, self._update_speed_label)
        self.set_pointer_speed(1.0)
        self.spin_sensitivity = self._number(card, "pointer_sensitivity", "İmleç hassasiyeti",
                                             "Büyük değer: küçük hareket daha uzağa gider", 0.05)
        self.spin_sensitivity.valueChanged.connect(self._sync_preset_from_values)
        self.spin_smoothing = self._number(card, "smoothing_factor", "Yumuşatma oranı",
                                           "Büyük değer: daha az titreme, biraz daha gecikme", 0.05)

        card = self._section(layout, "Tıklama ve Geri Bildirim")
        self.chk_dwell_click = self._toggle(card, "dwell_click", "Bekleyerek tıkla", "İmleç sabit kalınca sol tık",
                                            "Bekleyerek tıkla (imleç sabit kalınca sol tık)")
        self.chk_dwell_click.toggled.connect(self._update_dwell_enabled)
        self.slider_dwell_ms, self.label_dwell_ms = self._slider(
            card, "Bekleme süresi", "İmlecin sabit kalması gereken süre", DWELL_MS_MIN // _DWELL_UNIT_MS,
            DWELL_MS_MAX // _DWELL_UNIT_MS, 2, 4, self._update_dwell_label)
        self.set_dwell_ms(1000)
        self.chk_click_sound = self._toggle(card, "click_sound", "Tık sesi", "Tık ve komutlarda kısa ses çal",
                                            "Tık ve komutlarda kısa ses çal")
        self.chk_cursor_feedback = self._toggle(
            card, "cursor_feedback", "İmleç halkası", "Basılı tutma sırasında imlecin yanında ilerleme halkası göster",
            "Basılı tutma sırasında imlecin yanında ilerleme halkası göster")

        layout.addStretch(1)
        return page

    def _build_gestures_tab(self) -> QWidget:
        page, layout = self._page("Hareketler")

        card = self._section(layout, "Pinch")
        self.spin_pinch_on = self._number(card, "pinch_on_threshold", "Başlatma eşiği",
                                          "Parmaklar bu kadar yaklaşınca pinch başlar (avuç birimi)", 0.01)
        self.spin_pinch_off = self._number(card, "pinch_off_threshold", "Bırakma eşiği",
                                           "Parmaklar bu kadar ayrılınca pinch biter (avuç birimi)", 0.01)

        card = self._section(layout, "Yönler ve Komutlar")
        self.combo_scroll_dir = self._combo(card, "scroll_direction", "Kaydırma yönü", "Kaydırma modunda elin yönü", (
            ("Doğal (Yukarı = Yukarı)", "natural"), ("Ters (Yukarı = Aşağı)", "reverse")))
        self.combo_zoom_dir = self._combo(
            card, "zoom_direction", "Yakınlaştırma yönü", "Yakınlaştırma modunda ellerin yönü", (
                ("Doğal (Eller Açılınca Yakınlaş)", "natural"), ("Ters (Eller Açılınca Uzaklaş)", "reverse")))
        self.combo_swipe_profile = self._combo(
            card, "swipe_profile", "Kaydırma profili", "Komutlar modunda sola/sağa kaydırmanın anlamı. Otomatik: ön "
            "plandaki uygulamaya göre seçilir (sunum, tarayıcı, medya ya da sanal masaüstleri).",
            ((text, key) for key, text in SWIPE_PROFILE_LABELS_TR.items()))

        layout.addStretch(1)
        return page

    def _build_instrument_tab(self) -> QWidget:
        page, layout = self._page("Enstrüman")

        def named(keys: Sequence[str], labels: Mapping[str, str]) -> Iterable[tuple[str, str]]:
            return ((labels.get(key, key), key) for key in keys)

        card = self._section(layout, "Çalış")
        self.combo_instrument_layout = self._combo(
            card, "instrument_layout", "Düzen", "Solo: tek tel, eller arası uzaklık perdeyi belirler. Akor: dört tel, "
            "tel eli yüksekliği akoru seçer. Sabit teller: teller ekranda durur, iki elle de çalınır. "
            "Serbest teller: telleri kendin çizersin, istediğin yere ve boyda.",
            named(LAYOUTS, INSTRUMENT_LAYOUT_LABELS_TR))
        self.combo_instrument_scale = self._combo(card, "instrument_scale", "Dizi", "Çalınabilecek notalar",
                                                  named(SCALE_NAMES, INSTRUMENT_SCALE_LABELS_TR))
        self.chk_instrument_quantize = self._toggle(card, "instrument_quantize", "Diziye kilitle",
                                                    "Perdeler dizinin en yakın notasına oturur")

        card = self._section(layout, "Teller")
        self.spin_instrument_fixed_strings = SpinBox()
        self.spin_instrument_fixed_strings.setRange(*FIXED_STRINGS_RANGE)
        self._fields["instrument_fixed_strings"] = self.spin_instrument_fixed_strings
        self._row(card, "Tel sayısı (sabit)", "Sabit teller düzenindeki tel sayısı", self.spin_instrument_fixed_strings)
        card.add(self._hint(
            "Telleri taşımak ya da boyutlandırmak için: Enstrüman penceresinde fareyle sürükle (köşeden "
            "boyutlandır) ya da iki elinle çimdikle, yarım saniye tut, gerdir ve bırak."))
        self.chk_instrument_free_snap = self._toggle(
            card, "instrument_free_snap", "Serbest tellerde hizalama yardımı", "Açıksa yakın getirdiğin tel düzleşir "
            "ve diğer telin üstüne hizalanır; kapalıysa tel tam bıraktığın yerde kalır.")
        card.add(self._hint(
            "Serbest teller: boş yerde çimdikle, yarım saniye tut, çekerek tel çiz. Telin ucunu tutup boyutlandır, "
            "ortasından tutup taşı. İki elle bir telin iki ucunu tutabilirsin. Teli çok kısaltıp bırakırsan silinir."))

        card = self._section(layout, "Akorlar (Akor düzeni)")
        self.combo_chords = [self._combo(card, "", zone, "", ((name, name) for name in CHORD_NAMES), NUMBER_WIDTH)
                             for zone in CHORD_ZONE_LABELS_TR]

        card = self._section(layout, "Ses")
        self.slider_instrument_volume, self.label_instrument_volume = self._slider(
            card, "Ses düzeyi", "Enstrümanın sesi; sistem sesini değiştirmez", 0, 100, 5, 10, self._update_volume_label)
        self.combo_instrument_tone = self._combo(card, "instrument_tone", "Tını", "Telin ses rengi",
                                                 named(TONES, INSTRUMENT_TONE_LABELS_TR))
        self.combo_audio_device = self._combo(card, "", "Ses cihazı", "Enstrümanın çaldığı çıkış", ())
        self.btn_test_sound = button("Test sesi çal", "", "sound_test")
        self.btn_test_sound.clicked.connect(self.request_test_sound)
        self._row(card, "Cihazı dene", "Seçili cihazdan kısa bir nota çalar", self.btn_test_sound)
        self.combo_audio_latency = self._combo(card, "audio_latency", "Gecikme",
                                               "Ses kesik kesik gelirse gecikmeyi Normal yapın.",
                                               named(LATENCIES, AUDIO_LATENCY_LABELS_TR))

        card = self._section(layout, "Görünüm")
        self.chk_instrument_particles = self._toggle(card, "instrument_particles", "Kıvılcım efektleri",
                                                     "Tele vurunca kıvılcım saçar")

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
        self.combo_backend = self._combo(card, "camera_backend", "Kamera altyapısı", "Kamera açılmıyorsa diğerini dene", (
            ("Media Foundation (Önerilen)", "media_foundation"), ("DirectShow (Yedek)", "directshow")))
        self.spin_detection = self._number(card, "detection_threshold", "Algılama güven eşiği",
                                           "Elin ilk bulunması için gereken güven", 0.05)
        self.spin_tracking = self._number(card, "tracking_threshold", "Takip güven eşiği",
                                          "Elin izlenmeye devam etmesi için gereken güven", 0.05)
        self.chk_dry_run = self._toggle(card, "show_dry_run_panel", "Dry-run komut panelini göster",
                                        "Komutsuz denemede üretilecek komutları listeler")

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
        cfg = values if isinstance(values, SettingsData) else SettingsData.from_dict(values)
        for name, control in self._fields.items():
            value = getattr(cfg, name)
            if isinstance(control, QComboBox):
                self._set_combo_by_data(control, value)
            elif isinstance(control, ToggleSwitch):
                control.setChecked(value)
            else:
                control.setValue(value)
        self.set_pointer_speed(cfg.pointer_speed)
        self._sync_preset_from_values()
        self.edit_hotkey.setText(cfg.emergency_hotkey)
        self._set_auto_pause(cfg.auto_pause_s)
        self.set_dwell_ms(cfg.dwell_ms)
        self._update_dwell_enabled()
        for combo, name in zip(self.combo_chords, _clean_chords(cfg.instrument_chords)):
            self._set_combo_by_data(combo, name)
        self.slider_instrument_volume.setValue(round(cfg.instrument_volume * 100))
        self._update_volume_label()
        # An empty choice list (e.g. reset to defaults) keeps the devices already listed.
        self._set_audio_devices(cfg.audio_device_choices or self._audio_device_choices, cfg.audio_device)

    def get_settings(self) -> SettingsData:
        """Read current UI control values as a validated SettingsData instance."""
        values: dict[str, Any] = {}
        for name, control in self._fields.items():
            if isinstance(control, QComboBox):
                data = control.currentData()
                values[name] = getattr(SettingsData, name) if data is None else data
            elif isinstance(control, ToggleSwitch):
                values[name] = control.isChecked()
            else:
                values[name] = round(control.value(), 2)
        return SettingsData(
            **values,
            pointer_speed=self.pointer_speed(),
            emergency_hotkey=self.edit_hotkey.text().strip() or SettingsData.emergency_hotkey,
            auto_pause_s=int(self.combo_auto_pause.currentData() or 0),
            dwell_ms=self.dwell_ms(),
            instrument_chords=_clean_chords([c.currentData() for c in self.combo_chords]),
            instrument_volume=self.instrument_volume(),
            audio_device=self.selected_audio_device(),
            audio_device_choices=self._audio_device_choices,
        )

    @Slot()
    def reset_to_defaults(self) -> None:
        """Reset all controls to safe default SettingsData values."""
        self.set_values(SettingsData())

    @Slot()
    def save_and_accept(self) -> SettingsData:
        """Emit the settings and close the dialog."""
        data = self.get_settings()
        self.settings_applied.emit(data)
        if self._bridge is not None:
            self._bridge.settings_saved.emit(data)
            self._bridge.update_status(
                mirrored=data.mirror,
                mode=Mode(data.default_mode),
                dry_run=data.show_dry_run_panel,
            )
        self.accept()
        return data

