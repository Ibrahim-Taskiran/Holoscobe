"""Settings dataclass and configuration dialog for Holoscobe.

All user-visible strings are in Turkish.
Supports round-trip serialization as both a dataclass (`SettingsData`) and a
plain dictionary (`dict[str, Any]`).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Optional, Sequence

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from handcontrol.contracts import Handedness, Mode
from handcontrol.ui.viewmodel import MODE_LABELS_TR, UiBridge


@dataclass(frozen=True)
class SettingsData:
    """Typed representation of all user-configurable settings."""

    camera_index: int = 0
    camera_backend: str = "media_foundation"
    mirror: bool = True
    dominant_hand: str = "right"                # "right" or "left"
    pointer_sensitivity: float = 1.0            # 0.1 .. 3.0
    smoothing_factor: float = 0.50              # 0.0 .. 1.0
    pinch_on_threshold: float = 0.28            # 0.10 .. 0.60
    pinch_off_threshold: float = 0.42           # 0.15 .. 0.85
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
        )


class SettingsDialog(QDialog):
    """Settings window exposing all camera, gesture, mode, overlay, and OS options."""

    settings_applied = Signal(object)       # SettingsData
    settings_dict_applied = Signal(dict)    # dict[str, Any]

    def __init__(
        self,
        initial: SettingsData | Mapping[str, Any] | None = None,
        available_cameras: Optional[Sequence[tuple[int, str]]] = None,
        bridge: Optional[UiBridge] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._bridge = bridge
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
        self.resize(520, 640)

        self._build_ui()

        if initial is not None:
            self.set_values(initial)
        else:
            self.set_values(SettingsData())

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        # 1. Camera & Hand Group
        cam_group = QGroupBox("Kamera ve El Seçimi")
        cam_form = QFormLayout(cam_group)

        self.combo_camera = QComboBox()
        for idx, label in self._available_cameras:
            self.combo_camera.addItem(label, idx)
        cam_form.addRow("Kamera Seçimi:", self.combo_camera)

        self.combo_backend = QComboBox()
        self.combo_backend.addItem("Media Foundation (Önerilen)", "media_foundation")
        self.combo_backend.addItem("DirectShow (Yedek)", "directshow")
        cam_form.addRow("Kamera Altyapısı:", self.combo_backend)

        self.chk_mirror = QCheckBox("Önizleme ve eşlemeyi aynala")
        cam_form.addRow("Ayna Görüntüsü:", self.chk_mirror)

        self.combo_dominant_hand = QComboBox()
        self.combo_dominant_hand.addItem("Sağ El", "right")
        self.combo_dominant_hand.addItem("Sol El", "left")
        cam_form.addRow("Baskın El:", self.combo_dominant_hand)

        root.addWidget(cam_group)

        # 2. Thresholds & Sensitivity Group
        thresh_group = QGroupBox("Eşikler ve Hassasiyet")
        thresh_form = QFormLayout(thresh_group)

        self.spin_sensitivity = self._make_double_spin(0.10, 3.00, 0.05, 1.00)
        thresh_form.addRow("İmleç Hassasiyeti:", self.spin_sensitivity)

        self.spin_smoothing = self._make_double_spin(0.00, 1.00, 0.05, 0.50)
        thresh_form.addRow("Yumuşatma Oranı:", self.spin_smoothing)

        self.spin_pinch_on = self._make_double_spin(0.10, 0.60, 0.01, 0.28)
        thresh_form.addRow("Pinch Başlatma Eşiği (avuç birimi):", self.spin_pinch_on)

        self.spin_pinch_off = self._make_double_spin(0.15, 0.85, 0.01, 0.42)
        thresh_form.addRow("Pinch Bırakma Eşiği (avuç birimi):", self.spin_pinch_off)

        self.spin_detection = self._make_double_spin(0.10, 0.95, 0.05, 0.55)
        thresh_form.addRow("Algılama Güven Eşiği:", self.spin_detection)

        self.spin_tracking = self._make_double_spin(0.10, 0.95, 0.05, 0.55)
        thresh_form.addRow("Takip Güven Eşiği:", self.spin_tracking)

        root.addWidget(thresh_group)

        # 3. Modes, Directions & Hotkey Group
        control_group = QGroupBox("Kontrol Modu, Yönler ve Kısayol")
        control_form = QFormLayout(control_group)

        self.combo_mode = QComboBox()
        for mode in Mode:
            self.combo_mode.addItem(MODE_LABELS_TR[mode], mode.value)
        control_form.addRow("Varsayılan Mod:", self.combo_mode)

        self.combo_scroll_dir = QComboBox()
        self.combo_scroll_dir.addItem("Doğal (Yukarı = Yukarı)", "natural")
        self.combo_scroll_dir.addItem("Ters (Yukarı = Aşağı)", "reverse")
        control_form.addRow("Kaydırma Yönü:", self.combo_scroll_dir)

        self.combo_zoom_dir = QComboBox()
        self.combo_zoom_dir.addItem("Doğal (Eller Açılınca Yakınlaş)", "natural")
        self.combo_zoom_dir.addItem("Ters (Eller Açılınca Uzaklaş)", "reverse")
        control_form.addRow("Yakınlaştırma (Zoom) Yönü:", self.combo_zoom_dir)

        self.edit_hotkey = QLineEdit("Ctrl+Alt+Shift+F12")
        self.edit_hotkey.setPlaceholderText("Örn: Ctrl+Alt+Shift+F12")
        control_form.addRow("Acil Durdurma Kısayolu:", self.edit_hotkey)

        root.addWidget(control_group)

        # 4. Overlay, Mascot, Monitor & Startup Group
        system_group = QGroupBox("Görünüm, Monitör ve Sistem")
        system_form = QFormLayout(system_group)

        self.combo_monitor = QComboBox()
        self.combo_monitor.addItem("Tüm Ekranlar (Sanal Masaüstü)", "all")
        self.combo_monitor.addItem("Yalnız Birincil Ekran", "primary")
        self.combo_monitor.addItem("Yalnız İkincil Ekran", "secondary")
        system_form.addRow("Monitör Eşlemesi:", self.combo_monitor)

        self.chk_overlay = QCheckBox("Mod ve pencere eylem katmanını göster")
        system_form.addRow("Katman Görünürlüğü:", self.chk_overlay)

        self.chk_feedback = QCheckBox("Kısa durum bildirimlerini göster")
        system_form.addRow("Bildirim Görünürlüğü:", self.chk_feedback)

        self.chk_mascot = QCheckBox("Sağ alt köşe maskotunu göster")
        system_form.addRow("Maskot Görünürlüğü:", self.chk_mascot)

        self.chk_dry_run = QCheckBox("Dry-run komut panelini göster")
        system_form.addRow("Dry-Run Paneli:", self.chk_dry_run)

        self.chk_startup = QCheckBox("Windows açılışında otomatik başlat (İsteğe bağlı)")
        system_form.addRow("Windows ile Başlat:", self.chk_startup)

        root.addWidget(system_group)

        # Action buttons
        btn_row = QHBoxLayout()
        self.btn_defaults = QPushButton("Varsayılanlara Sıfırla")
        self.btn_save = QPushButton("Kaydet")
        self.btn_cancel = QPushButton("İptal")

        self.btn_defaults.clicked.connect(self.reset_to_defaults)
        self.btn_save.clicked.connect(self.save_and_accept)
        self.btn_cancel.clicked.connect(self.reject)

        btn_row.addWidget(self.btn_defaults)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_save)
        btn_row.addWidget(self.btn_cancel)
        root.addLayout(btn_row)

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
        self.spin_sensitivity.setValue(cfg.pointer_sensitivity)
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

    def get_settings(self) -> SettingsData:
        """Read current UI control values as a validated SettingsData instance."""
        hotkey = self.edit_hotkey.text().strip() or "Ctrl+Alt+Shift+F12"
        return SettingsData(
            camera_index=int(self.combo_camera.currentData() or 0),
            camera_backend=str(self.combo_backend.currentData() or "media_foundation"),
            mirror=bool(self.chk_mirror.isChecked()),
            dominant_hand=str(self.combo_dominant_hand.currentData() or "right"),
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
