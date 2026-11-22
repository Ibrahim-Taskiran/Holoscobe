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
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from handcontrol.contracts import Handedness, Mode
from handcontrol.instrument.events import CHORD_NAMES, DEFAULT_CHORDS, LATENCIES, LAYOUTS, SCALE_NAMES, TONES
from handcontrol.ui.tray import create_mode_icon
from handcontrol.ui.viewmodel import MODE_LABELS_TR, SWIPE_PROFILE_LABELS_TR, UiBridge


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


INSTRUMENT_LAYOUT_LABELS_TR: dict[str, str] = {"solo": "Solo", "chord": "Akor"}
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
    show_mascot: bool = False
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
    instrument_layout: str = "solo"             # LAYOUTS
    instrument_scale: str = "e_minor_pentatonic"  # SCALE_NAMES
    instrument_quantize: bool = True
    instrument_chords: tuple[str, ...] = DEFAULT_CHORDS   # 4 zones, top first
    instrument_volume: float = 0.5              # 0..1
    instrument_tone: str = "clean"              # TONES
    audio_device: str = ""                      # "" = system default
    audio_latency: str = "low"                  # LATENCIES
    instrument_particles: bool = True
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
            audio_device_choices=choices,
        )


def _format_auto_pause(seconds: int) -> str:
    if seconds % 60 == 0:
        return f"{seconds // 60} dk"
    return f"{seconds} sn"


class SettingsDialog(QDialog):
    """Settings window with tabs: Genel, İmleç, Hareketler, Enstrüman, Gelişmiş."""

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
        self.resize(560, 620)

        self._build_ui()

        if initial is not None:
            self.set_values(initial)
        else:
            self.set_values(SettingsData())

    # ---------- layout ----------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self._build_general_tab(), "Genel")
        self.tabs.addTab(self._build_pointer_tab(), "İmleç")
        self.tabs.addTab(self._build_gestures_tab(), "Hareketler")
        self.tabs.addTab(self._build_instrument_tab(), "Enstrüman")
        self.tabs.addTab(self._build_advanced_tab(), "Gelişmiş")
        root.addWidget(self.tabs, 1)

        btn_row = QHBoxLayout()
        self.btn_defaults = QPushButton("Varsayılanlara Sıfırla")
        self.btn_save = QPushButton("Kaydet")
        self.btn_cancel = QPushButton("İptal")
        self.btn_save.setDefault(True)

        self.btn_defaults.clicked.connect(self.reset_to_defaults)
        self.btn_save.clicked.connect(self.save_and_accept)
        self.btn_cancel.clicked.connect(self.reject)

        btn_row.addWidget(self.btn_defaults)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_save)
        btn_row.addWidget(self.btn_cancel)
        root.addLayout(btn_row)

    @staticmethod
    def _page() -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 10, 4, 4)
        layout.setSpacing(10)
        return page, layout

    @staticmethod
    def _hint(text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet("color: palette(mid);")
        return label

    def _build_general_tab(self) -> QWidget:
        page, layout = self._page()

        cam_group = QGroupBox("Kamera ve El")
        cam_form = QFormLayout(cam_group)
        self.combo_camera = QComboBox()
        for idx, label in self._available_cameras:
            self.combo_camera.addItem(label, idx)
        cam_form.addRow("Kamera:", self.combo_camera)

        self.chk_mirror = QCheckBox("Önizleme ve eşlemeyi aynala")
        cam_form.addRow("Ayna görüntüsü:", self.chk_mirror)

        self.combo_dominant_hand = QComboBox()
        self.combo_dominant_hand.addItem("Sağ El", "right")
        self.combo_dominant_hand.addItem("Sol El", "left")
        cam_form.addRow("Baskın el:", self.combo_dominant_hand)
        layout.addWidget(cam_group)

        control_group = QGroupBox("Kontrol")
        control_form = QFormLayout(control_group)
        self.combo_mode = QComboBox()
        for mode in Mode:
            self.combo_mode.addItem(create_mode_icon(mode, 16), MODE_LABELS_TR[mode], mode.value)
        control_form.addRow("Varsayılan mod:", self.combo_mode)

        self.combo_auto_pause = QComboBox()
        for seconds, label in AUTO_PAUSE_CHOICES:
            self.combo_auto_pause.addItem(label, seconds)
        control_form.addRow("Otomatik duraklat:", self.combo_auto_pause)
        control_form.addRow("", self._hint("El bu süre görünmezse kontrol kendiliğinden duraklar."))

        self.edit_hotkey = QLineEdit("Ctrl+Alt+Shift+F12")
        self.edit_hotkey.setPlaceholderText("Örn: Ctrl+Alt+Shift+F12")
        control_form.addRow("Acil durdurma kısayolu:", self.edit_hotkey)
        layout.addWidget(control_group)

        view_group = QGroupBox("Görünüm ve Sistem")
        view_form = QFormLayout(view_group)
        self.combo_monitor = QComboBox()
        self.combo_monitor.addItem("Tüm Ekranlar (Sanal Masaüstü)", "all")
        self.combo_monitor.addItem("Yalnız Birincil Ekran", "primary")
        self.combo_monitor.addItem("Yalnız İkincil Ekran", "secondary")
        view_form.addRow("Monitör eşlemesi:", self.combo_monitor)

        self.chk_overlay = QCheckBox("Mod ve pencere eylem katmanını göster")
        view_form.addRow(self.chk_overlay)
        self.chk_feedback = QCheckBox("Kısa durum bildirimlerini göster")
        view_form.addRow(self.chk_feedback)
        self.chk_mascot = QCheckBox("Sağ alt köşe maskotunu göster")
        view_form.addRow(self.chk_mascot)
        self.chk_startup = QCheckBox("Windows açılışında otomatik başlat")
        view_form.addRow(self.chk_startup)
        layout.addWidget(view_group)

        layout.addStretch(1)
        return page

    def _build_pointer_tab(self) -> QWidget:
        page, layout = self._page()

        motion_group = QGroupBox("Hareket")
        motion_form = QFormLayout(motion_group)

        self.combo_preset = QComboBox()
        for key in (*SENSITIVITY_PRESETS, "custom"):
            self.combo_preset.addItem(SENSITIVITY_PRESET_LABELS_TR[key], key)
        self.combo_preset.currentIndexChanged.connect(self._on_preset_selected)
        motion_form.addRow("Hassasiyet ön ayarı:", self.combo_preset)

        self.combo_pointer_mode = QComboBox()
        for mode_key in POINTER_MODES:
            self.combo_pointer_mode.addItem(POINTER_MODE_LABELS_TR[mode_key], mode_key)
        motion_form.addRow("İmleç türü:", self.combo_pointer_mode)

        speed_row = QWidget()
        speed_layout = QHBoxLayout(speed_row)
        speed_layout.setContentsMargins(0, 0, 0, 0)
        self.slider_pointer_speed = QSlider(Qt.Orientation.Horizontal)
        self.slider_pointer_speed.setRange(round(POINTER_SPEED_MIN * _SPEED_STEPS),
                                           round(POINTER_SPEED_MAX * _SPEED_STEPS))
        self.slider_pointer_speed.setSingleStep(1)
        self.slider_pointer_speed.setPageStep(1)
        self.slider_pointer_speed.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.slider_pointer_speed.setTickInterval(5)
        self.label_pointer_speed = QLabel()
        self.label_pointer_speed.setMinimumWidth(40)
        self.slider_pointer_speed.valueChanged.connect(self._update_speed_label)
        speed_layout.addWidget(self.slider_pointer_speed, 1)
        speed_layout.addWidget(self.label_pointer_speed)
        motion_form.addRow("İmleç hızı:", speed_row)
        self.set_pointer_speed(1.0)

        self.spin_sensitivity = self._make_double_spin(0.10, 3.00, 0.05, 1.00)
        self.spin_sensitivity.valueChanged.connect(self._sync_preset_from_values)
        motion_form.addRow("İmleç hassasiyeti:", self.spin_sensitivity)

        self.spin_smoothing = self._make_double_spin(0.00, 1.00, 0.05, 0.50)
        motion_form.addRow("Yumuşatma oranı:", self.spin_smoothing)
        layout.addWidget(motion_group)

        click_group = QGroupBox("Tıklama ve Geri Bildirim")
        click_form = QFormLayout(click_group)
        self.chk_dwell_click = QCheckBox("Bekleyerek tıkla (imleç sabit kalınca sol tık)")
        self.chk_dwell_click.toggled.connect(self._update_dwell_enabled)
        click_form.addRow(self.chk_dwell_click)

        dwell_row = QWidget()
        dwell_layout = QHBoxLayout(dwell_row)
        dwell_layout.setContentsMargins(0, 0, 0, 0)
        self.slider_dwell_ms = QSlider(Qt.Orientation.Horizontal)
        self.slider_dwell_ms.setRange(DWELL_MS_MIN // _DWELL_UNIT_MS, DWELL_MS_MAX // _DWELL_UNIT_MS)
        self.slider_dwell_ms.setSingleStep(2)
        self.slider_dwell_ms.setPageStep(4)
        self.label_dwell_ms = QLabel()
        self.label_dwell_ms.setMinimumWidth(48)
        self.slider_dwell_ms.valueChanged.connect(self._update_dwell_label)
        dwell_layout.addWidget(self.slider_dwell_ms, 1)
        dwell_layout.addWidget(self.label_dwell_ms)
        click_form.addRow("Bekleme süresi:", dwell_row)
        self.set_dwell_ms(1000)

        self.chk_click_sound = QCheckBox("Tık ve komutlarda kısa ses çal")
        click_form.addRow("Tık sesi:", self.chk_click_sound)
        self.chk_cursor_feedback = QCheckBox("Basılı tutma sırasında imlecin yanında ilerleme halkası göster")
        click_form.addRow("İmleç halkası:", self.chk_cursor_feedback)
        layout.addWidget(click_group)

        layout.addStretch(1)
        return page

    def _build_gestures_tab(self) -> QWidget:
        page, layout = self._page()

        pinch_group = QGroupBox("Pinch")
        pinch_form = QFormLayout(pinch_group)
        self.spin_pinch_on = self._make_double_spin(0.10, 0.60, 0.01, 0.33)
        pinch_form.addRow("Başlatma eşiği (avuç birimi):", self.spin_pinch_on)
        self.spin_pinch_off = self._make_double_spin(0.15, 0.85, 0.01, 0.48)
        pinch_form.addRow("Bırakma eşiği (avuç birimi):", self.spin_pinch_off)
        layout.addWidget(pinch_group)

        dir_group = QGroupBox("Yönler ve Komutlar")
        dir_form = QFormLayout(dir_group)
        self.combo_scroll_dir = QComboBox()
        self.combo_scroll_dir.addItem("Doğal (Yukarı = Yukarı)", "natural")
        self.combo_scroll_dir.addItem("Ters (Yukarı = Aşağı)", "reverse")
        dir_form.addRow("Kaydırma yönü:", self.combo_scroll_dir)

        self.combo_zoom_dir = QComboBox()
        self.combo_zoom_dir.addItem("Doğal (Eller Açılınca Yakınlaş)", "natural")
        self.combo_zoom_dir.addItem("Ters (Eller Açılınca Uzaklaş)", "reverse")
        dir_form.addRow("Yakınlaştırma yönü:", self.combo_zoom_dir)

        self.combo_swipe_profile = QComboBox()
        for key, label in SWIPE_PROFILE_LABELS_TR.items():
            self.combo_swipe_profile.addItem(label, key)
        dir_form.addRow("Kaydırma profili:", self.combo_swipe_profile)
        dir_form.addRow("", self._hint(
            "Komutlar modunda sola/sağa kaydırmanın anlamı. Otomatik: ön plandaki uygulamaya göre "
            "seçilir (sunum, tarayıcı, medya ya da sanal masaüstleri)."))
        layout.addWidget(dir_group)

        layout.addStretch(1)
        return page

    def _build_instrument_tab(self) -> QWidget:
        page, layout = self._page()

        play_group = QGroupBox("Çalış")
        play_form = QFormLayout(play_group)
        self.combo_instrument_layout = QComboBox()
        for key in LAYOUTS:
            self.combo_instrument_layout.addItem(INSTRUMENT_LAYOUT_LABELS_TR.get(key, key), key)
        play_form.addRow("Düzen:", self.combo_instrument_layout)
        play_form.addRow("", self._hint(
            "Solo: tek tel, eller arası uzaklık perdeyi belirler. Akor: dört tel, tel eli yüksekliği akoru seçer."))

        self.combo_instrument_scale = QComboBox()
        for key in SCALE_NAMES:
            self.combo_instrument_scale.addItem(INSTRUMENT_SCALE_LABELS_TR.get(key, key), key)
        play_form.addRow("Dizi:", self.combo_instrument_scale)
        self.chk_instrument_quantize = QCheckBox("Diziye kilitle")
        play_form.addRow("", self.chk_instrument_quantize)
        layout.addWidget(play_group)

        chord_group = QGroupBox("Akorlar (Akor düzeni)")
        chord_form = QFormLayout(chord_group)
        self.combo_chords: list[QComboBox] = []
        for zone_label in CHORD_ZONE_LABELS_TR:
            combo = QComboBox()
            for name in CHORD_NAMES:
                combo.addItem(name, name)
            chord_form.addRow(f"{zone_label}:", combo)
            self.combo_chords.append(combo)
        layout.addWidget(chord_group)

        sound_group = QGroupBox("Ses")
        sound_form = QFormLayout(sound_group)
        vol_row = QWidget()
        vol_layout = QHBoxLayout(vol_row)
        vol_layout.setContentsMargins(0, 0, 0, 0)
        self.slider_instrument_volume = QSlider(Qt.Orientation.Horizontal)
        self.slider_instrument_volume.setRange(0, 100)
        self.slider_instrument_volume.setSingleStep(5)
        self.slider_instrument_volume.setPageStep(10)
        self.label_instrument_volume = QLabel()
        self.label_instrument_volume.setMinimumWidth(40)
        self.slider_instrument_volume.valueChanged.connect(self._update_volume_label)
        vol_layout.addWidget(self.slider_instrument_volume, 1)
        vol_layout.addWidget(self.label_instrument_volume)
        sound_form.addRow("Ses düzeyi:", vol_row)

        self.combo_instrument_tone = QComboBox()
        for key in TONES:
            self.combo_instrument_tone.addItem(INSTRUMENT_TONE_LABELS_TR.get(key, key), key)
        sound_form.addRow("Tını:", self.combo_instrument_tone)

        device_row = QWidget()
        device_layout = QHBoxLayout(device_row)
        device_layout.setContentsMargins(0, 0, 0, 0)
        self.combo_audio_device = QComboBox()
        self.btn_test_sound = QPushButton("Test sesi çal")
        self.btn_test_sound.clicked.connect(self.request_test_sound)
        device_layout.addWidget(self.combo_audio_device, 1)
        device_layout.addWidget(self.btn_test_sound)
        sound_form.addRow("Ses cihazı:", device_row)

        self.combo_audio_latency = QComboBox()
        for key in LATENCIES:
            self.combo_audio_latency.addItem(AUDIO_LATENCY_LABELS_TR.get(key, key), key)
        sound_form.addRow("Gecikme:", self.combo_audio_latency)
        sound_form.addRow("", self._hint("Ses kesik kesik gelirse gecikmeyi Normal yapın."))
        layout.addWidget(sound_group)

        view_group = QGroupBox("Görünüm")
        view_form = QFormLayout(view_group)
        self.chk_instrument_particles = QCheckBox("Kıvılcım efektleri")
        view_form.addRow(self.chk_instrument_particles)
        layout.addWidget(view_group)

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
        page, layout = self._page()

        track_group = QGroupBox("Kamera ve Takip")
        track_form = QFormLayout(track_group)
        self.combo_backend = QComboBox()
        self.combo_backend.addItem("Media Foundation (Önerilen)", "media_foundation")
        self.combo_backend.addItem("DirectShow (Yedek)", "directshow")
        track_form.addRow("Kamera altyapısı:", self.combo_backend)
        self.spin_detection = self._make_double_spin(0.10, 0.95, 0.05, 0.55)
        track_form.addRow("Algılama güven eşiği:", self.spin_detection)
        self.spin_tracking = self._make_double_spin(0.10, 0.95, 0.05, 0.55)
        track_form.addRow("Takip güven eşiği:", self.spin_tracking)
        self.chk_dry_run = QCheckBox("Dry-run komut panelini göster")
        track_form.addRow(self.chk_dry_run)
        layout.addWidget(track_group)

        tools_group = QGroupBox("Araçlar")
        tools_layout = QVBoxLayout(tools_group)
        row1 = QHBoxLayout()
        self.btn_export = QPushButton("Ayarları dışa aktar…")
        self.btn_import = QPushButton("Ayarları içe aktar…")
        row1.addWidget(self.btn_export)
        row1.addWidget(self.btn_import)
        row2 = QHBoxLayout()
        self.btn_diagnostics = QPushButton("Tanılama raporu oluştur")
        self.btn_tutorial = QPushButton("Eğitimi başlat")
        row2.addWidget(self.btn_diagnostics)
        row2.addWidget(self.btn_tutorial)
        tools_layout.addLayout(row1)
        tools_layout.addLayout(row2)
        tools_layout.addWidget(self._hint(
            "Tanılama raporu kamera, ekran ve ayar bilgilerini paylaşılabilir bir dosyaya yazar."))
        layout.addWidget(tools_group)

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
        spin = QDoubleSpinBox()
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
            show_dry_run_panel=bool(self.chk_dry_run.isChecked()),
            monitor_mapping=str(self.combo_monitor.currentData() or "all"),
            start_with_windows=bool(self.chk_startup.isChecked()),
            swipe_profile=str(self.combo_swipe_profile.currentData() or "auto"),
            auto_pause_s=int(self.combo_auto_pause.currentData() or 0),
            dwell_click=bool(self.chk_dwell_click.isChecked()),
            dwell_ms=self.dwell_ms(),
            click_sound=bool(self.chk_click_sound.isChecked()),
            cursor_feedback=bool(self.chk_cursor_feedback.isChecked()),
            instrument_layout=str(self.combo_instrument_layout.currentData() or "solo"),
            instrument_scale=str(self.combo_instrument_scale.currentData() or "e_minor_pentatonic"),
            instrument_quantize=bool(self.chk_instrument_quantize.isChecked()),
            instrument_chords=_clean_chords([c.currentData() for c in self.combo_chords]),
            instrument_volume=self.instrument_volume(),
            instrument_tone=str(self.combo_instrument_tone.currentData() or "clean"),
            audio_device=self.selected_audio_device(),
            audio_latency=str(self.combo_audio_latency.currentData() or "low"),
            instrument_particles=bool(self.chk_instrument_particles.isChecked()),
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
