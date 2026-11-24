"""Manual interactive showcase of all Holoscobe UI components using synthetic data.

Run manually with:
    .venv\\Scripts\\python.exe -m handcontrol.ui.demo

Does not execute automatically during pytest collection or test runs.
"""
from __future__ import annotations

import math
import sys
from typing import Optional

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from handcontrol.contracts import (
    Action,
    ActionKind,
    CameraState,
    ControlState,
    FingerInfo,
    FingerName,
    FingerState,
    FrameFeatures,
    Handedness,
    HandFeatures,
    Landmark,
    Mode,
    Quality,
    WindowTarget,
)
from handcontrol.ui.calibration import CalibrationWizard
from handcontrol.ui.feedback import DryRunPanel, FeedbackToast
from handcontrol.ui.overlay import OverlayWindow
from handcontrol.ui.preview import CameraPreviewWidget
from handcontrol.ui.settings import SettingsData, SettingsDialog
from handcontrol.ui.tray import HandControlTray
from handcontrol.ui.viewmodel import (
    MODE_LABELS_TR,
    UiBridge,
    VirtualCursorState,
    WindowActionKind,
)
from handcontrol.ui.widgets import ComboBox


def build_synthetic_hand(
    hand_id: int = 1,
    handedness: Handedness = Handedness.RIGHT,
    quality: Quality = Quality.USABLE,
    center_x: float = 0.35,
    center_y: float = 0.55,
    phase: float = 0.0,
    uncertain_finger: Optional[FingerName] = None,
) -> HandFeatures:
    """Create a synthetic 21-landmark HandFeatures instance for demos and tests."""
    # 21 landmarks: 0 wrist, 1-4 thumb, 5-8 index, 9-12 middle, 13-16 ring, 17-20 little
    sign = -1.0 if handedness == Handedness.LEFT else 1.0
    wrist_x = center_x + 0.03 * math.sin(phase)
    wrist_y = center_y + 0.02 * math.cos(phase)

    landmarks: list[Landmark] = [Landmark(x=wrist_x, y=wrist_y, z=0.0)]

    finger_offsets = [
        (-0.09 * sign, -0.04),  # Thumb
        (-0.04 * sign, -0.11),  # Index
        (0.00 * sign, -0.12),   # Middle
        (0.04 * sign, -0.11),   # Ring
        (0.08 * sign, -0.09),   # Little
    ]

    for f_idx, (dx, dy) in enumerate(finger_offsets):
        curl_wave = 0.5 + 0.4 * math.sin(phase + f_idx * 0.7)
        for joint in range(1, 5):
            scale = joint * (0.28 - 0.08 * curl_wave)
            lx = max(0.02, min(0.98, wrist_x + dx * scale * 1.4))
            ly = max(0.02, min(0.98, wrist_y + dy * scale * 1.4))
            landmarks.append(Landmark(x=lx, y=ly, z=-0.01 * joint))

    finger_Order = (
        FingerName.THUMB,
        FingerName.INDEX,
        FingerName.MIDDLE,
        FingerName.RING,
        FingerName.LITTLE,
    )
    fingers: list[FingerInfo] = []
    for f_idx, f_name in enumerate(finger_Order):
        curl_val = round(max(0.0, min(1.0, 0.45 + 0.45 * math.sin(phase + f_idx))), 2)
        if f_name == uncertain_finger or quality == Quality.UNKNOWN:
            state = FingerState.UNKNOWN
        elif curl_val < 0.45:
            state = FingerState.EXTENDED
        else:
            state = FingerState.BENT
        fingers.append(FingerInfo(name=f_name, state=state, curl=curl_val))

    width_px, height_px = 640.0, 480.0
    palm_cx = wrist_x * width_px
    palm_cy = (wrist_y - 0.06) * height_px
    index_tip = landmarks[8]
    thumb_tip = landmarks[4]
    pinch_px = math.hypot(
        (index_tip.x - thumb_tip.x) * width_px,
        (index_tip.y - thumb_tip.y) * height_px,
    )
    palm_scale = 85.0

    return HandFeatures(
        hand_id=hand_id,
        handedness=handedness,
        quality=quality,
        palm_center_px=(palm_cx, palm_cy),
        palm_scale_px=palm_scale,
        fingers=tuple(fingers),
        pinch_distance=round(pinch_px / palm_scale, 3),
        index_tip_px=(index_tip.x * width_px, index_tip.y * height_px),
        landmarks=tuple(landmarks),
    )


def build_synthetic_frame(
    hand_count: int = 2,
    phase: float = 0.0,
    uncertain: bool = False,
    capture_ms: float = 1000.0,
    inference_done_ms: float = 1014.5,
) -> FrameFeatures:
    """Create a synthetic FrameFeatures with 0, 1, or 2 hands."""
    hands: list[HandFeatures] = []
    if hand_count >= 1:
        hands.append(
            build_synthetic_hand(
                hand_id=1,
                handedness=Handedness.RIGHT,
                quality=Quality.DEGRADED if uncertain else Quality.USABLE,
                center_x=0.34,
                center_y=0.62,
                phase=phase,
                uncertain_finger=FingerName.RING if uncertain else None,
            )
        )
    if hand_count >= 2:
        hands.append(
            build_synthetic_hand(
                hand_id=2,
                handedness=Handedness.LEFT,
                quality=Quality.USABLE,
                center_x=0.68,
                center_y=0.62,
                phase=phase + 1.2,
                uncertain_finger=FingerName.LITTLE if uncertain else None,
            )
        )
    return FrameFeatures(
        capture_ms=capture_ms,
        inference_done_ms=inference_done_ms,
        width=640,
        height=480,
        hands=tuple(hands),
        identity_ambiguous=uncertain,
    )


class DemoMainWindow(QMainWindow):
    """Interactive showcase window connecting all Holoscobe UI widgets."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Holoscobe — Arayüz Gösterimi (Sahte Veri)")
        self.resize(980, 680)

        self.bridge = UiBridge()
        self.settings_data = SettingsData()
        self._phase: float = 0.0
        self._hand_count: int = 2
        self._uncertain: bool = False

        self.tray = HandControlTray(self.bridge, self)
        self.overlay = OverlayWindow(self.bridge)
        self.toast = FeedbackToast(self.bridge, auto_show_window=True)
        self.dry_run_panel = DryRunPanel(self.bridge)

        self._build_ui()
        self._connect_signals()

        self.bridge.update_status(
            control_state=ControlState.ACTIVE,
            camera_state=CameraState.RUNNING,
            mode=Mode.POINTER,
            fps=30.0,
            sample_age_ms=14.2,
        )

        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._tick_synthetic_frame)
        self._anim_timer.start(50)

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)

        self.preview = CameraPreviewWidget(self.bridge, self)
        main_layout.addWidget(self.preview, stretch=2)

        side_panel = QGroupBox("Gösterim Denetimleri")
        side_layout = QVBoxLayout(side_panel)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        side_layout.addWidget(self.status_label)

        self.combo_hands = ComboBox()
        self.combo_hands.addItem("2 El Göster (42 Nokta)", 2)
        self.combo_hands.addItem("1 El Göster (21 Nokta)", 1)
        self.combo_hands.addItem("0 El Göster (El Yok)", 0)
        self.combo_hands.currentIndexChanged.connect(self._on_hand_count_changed)
        side_layout.addWidget(self.combo_hands)

        self.chk_uncertain = QCheckBox("Belirsiz Parmak / Düşük Kalite Simüle Et")
        self.chk_uncertain.toggled.connect(self._on_uncertain_toggled)
        side_layout.addWidget(self.chk_uncertain)

        self.chk_mirror = QCheckBox("Ayna Görüntüsü")
        self.chk_mirror.setChecked(True)
        self.chk_mirror.toggled.connect(lambda v: self.bridge.update_status(mirrored=v))
        side_layout.addWidget(self.chk_mirror)

        btn_pause = QPushButton("Duraklat / Sürdür Değiştir")
        btn_pause.clicked.connect(self.bridge.request_pause_resume)
        side_layout.addWidget(btn_pause)

        btn_cam = QPushButton("Kamerayı Aç / Kapat Değiştir")
        btn_cam.clicked.connect(self.bridge.request_camera_toggle)
        side_layout.addWidget(btn_cam)

        btn_mode_overlay = QPushButton("Mod Menüsü Katmanını Göster")
        btn_mode_overlay.clicked.connect(self._show_demo_mode_overlay)
        side_layout.addWidget(btn_mode_overlay)

        btn_win_overlay = QPushButton("Pencere Eylem Katmanını Göster (1 sn Kapat Halkası)")
        btn_win_overlay.clicked.connect(self._show_demo_window_overlay)
        side_layout.addWidget(btn_win_overlay)

        side_layout.addWidget(QLabel("Kapat Tutma İlerlemesi (0 - 1000 ms):"))
        self.slider_close_hold = QSlider()
        self.slider_close_hold.setOrientation(self.slider_close_hold.orientation().Horizontal)
        self.slider_close_hold.setRange(0, 1000)
        self.slider_close_hold.valueChanged.connect(self._on_close_hold_slider)
        side_layout.addWidget(self.slider_close_hold)

        side_layout.addWidget(QLabel("Katman Hareketsizlik Süresi (0 - 5000 ms):"))
        self.slider_inactivity = QSlider()
        self.slider_inactivity.setOrientation(self.slider_inactivity.orientation().Horizontal)
        self.slider_inactivity.setRange(0, 5000)
        self.slider_inactivity.valueChanged.connect(
            lambda ms: self.overlay.set_inactivity_time(float(ms), 5000.0)
        )
        side_layout.addWidget(self.slider_inactivity)

        btn_toast = QPushButton("Örnek Kısa Bildirim (Ses %75) Göster")
        btn_toast.clicked.connect(lambda: self.toast.notify_volume(75))
        side_layout.addWidget(btn_toast)

        btn_dry = QPushButton("Dry-Run Komut Panelini Göster / Güncelle")
        btn_dry.clicked.connect(self._emit_demo_dry_run)
        side_layout.addWidget(btn_dry)

        btn_settings = QPushButton("Ayarlar Penceresini Aç")
        btn_settings.clicked.connect(self._open_settings)
        side_layout.addWidget(btn_settings)

        btn_calib = QPushButton("Kalibrasyon Sihirbazını Aç")
        btn_calib.clicked.connect(self._open_calibration)
        side_layout.addWidget(btn_calib)

        side_layout.addStretch(1)
        main_layout.addWidget(side_panel, stretch=1)

    def _connect_signals(self) -> None:
        self.bridge.state_changed.connect(self._on_state_changed)
        self.bridge.pause_resume_requested.connect(self._toggle_pause_resume)
        self.bridge.camera_toggle_requested.connect(self._toggle_camera)
        self.bridge.mode_selected.connect(self._on_mode_selected)

    def _on_state_changed(self, state) -> None:
        self.status_label.setText(
            f"Tepsi Durumu: {state.tray_state_label_tr}\n"
            f"İpucu: {state.tooltip_text}"
        )

    def _on_hand_count_changed(self) -> None:
        self._hand_count = int(self.combo_hands.currentData() or 0)

    def _on_uncertain_toggled(self, checked: bool) -> None:
        self._uncertain = bool(checked)

    def _toggle_pause_resume(self) -> None:
        st = self.bridge.state
        if st.control_state == ControlState.ACTIVE:
            self.bridge.update_status(control_state=ControlState.PAUSED)
            self.toast.notify_paused()
        else:
            self.bridge.update_status(
                control_state=ControlState.ACTIVE,
                camera_state=CameraState.RUNNING,
            )
            self.toast.notify_activated()

    def _toggle_camera(self) -> None:
        st = self.bridge.state
        if st.camera_state == CameraState.RUNNING:
            self.bridge.update_status(
                camera_state=CameraState.OFF,
                control_state=ControlState.PAUSED,
            )
        else:
            self.bridge.update_status(camera_state=CameraState.RUNNING)

    def _on_mode_selected(self, mode: Mode) -> None:
        self.bridge.update_status(mode=mode)
        self.toast.notify_mode_changed(mode)

    def _show_demo_mode_overlay(self) -> None:
        self.overlay.configure_mode_menu(
            active_mode=self.bridge.state.mode,
            hovered_mode=Mode.SCROLL,
            cursor=VirtualCursorState(x=0.52, y=0.42, visible=True),
        )
        self.overlay.show()

    def _show_demo_window_overlay(self) -> None:
        self.overlay.configure_window_action_menu(
            hovered_action=WindowActionKind.CLOSE,
            close_armed=True,
            close_hold_progress=0.45,
            cursor=VirtualCursorState(x=0.60, y=0.80, visible=True, pinching=True, hold_progress=0.45),
            target_window_title="Not Defteri",
        )
        self.overlay.show()

    def _on_close_hold_slider(self, ms: int) -> None:
        self.overlay.set_close_hold_ms(float(ms), 1000.0, armed=True)

    def _emit_demo_dry_run(self) -> None:
        act = Action(
            kind=ActionKind.LEFT_CLICK,
            epoch=1,
            capture_ms=1200.0,
            x=640,
            y=360,
            target=WindowTarget(hwnd=0x104A, pid=4200),
        )
        self.bridge.record_dry_run_action(act)
        self.dry_run_panel.show()

    def _open_settings(self) -> None:
        dlg = SettingsDialog(initial=self.settings_data, bridge=self.bridge, parent=self)
        if dlg.exec():
            self.settings_data = dlg.get_settings()

    def _open_calibration(self) -> None:
        wiz = CalibrationWizard(bridge=self.bridge, parent=self)
        wiz.exec()

    def _tick_synthetic_frame(self) -> None:
        self._phase += 0.12
        t_ms = self._phase * 250.0
        frame = build_synthetic_frame(
            hand_count=self._hand_count,
            phase=self._phase,
            uncertain=self._uncertain,
            capture_ms=t_ms,
            inference_done_ms=t_ms + 13.8,
        )
        self.bridge.update_frame(frame, fps=30.0, sample_age_ms=13.8)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    win = DemoMainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
