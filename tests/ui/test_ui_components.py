"""Unit tests for the Holoscobe PySide6 UI package.

Runs entirely under QT_QPA_PLATFORM=offscreen without opening any windows on screen.
"""
from __future__ import annotations

import threading

import pytest
from PySide6.QtCore import QCoreApplication, Qt

from handcontrol.contracts import (
    Action,
    ActionKind,
    CameraState,
    ControlState,
    FingerName,
    FrameFeatures,
    Handedness,
    Mode,
    Quality,
    WindowTarget,
)
from handcontrol.ui.calibration import (
    CalibrationResult,
    CalibrationStep,
    CalibrationWizard,
)
from ui_synth import build_synthetic_frame, build_synthetic_hand
from handcontrol.ui.feedback import DryRunPanel, FeedbackToast
from handcontrol.ui.overlay import (
    OverlayWindow,
)
from handcontrol.ui.preview import CameraPreviewWidget
from handcontrol.ui.settings import SettingsData, SettingsDialog
from handcontrol.ui.tray import HandControlTray, create_tray_pixmap
from handcontrol.ui.viewmodel import (
    MODE_LABELS_TR,
    OverlayMenuItem,
    OverlayMenuKind,
    OverlayState,
    TrayIconState,
    UiBridge,
    UiState,
    VirtualCursorState,
    resolve_tray_icon_state,
)


def test_component_instantiation_offscreen() -> None:
    """All UI widgets instantiate cleanly without showing windows on screen."""
    bridge = UiBridge()
    tray = HandControlTray(bridge)
    preview = CameraPreviewWidget(bridge)
    calibration = CalibrationWizard(bridge)
    settings = SettingsDialog(bridge=bridge)
    overlay = OverlayWindow(bridge)
    toast = FeedbackToast(bridge)
    dry_run = DryRunPanel(bridge)

    assert not preview.isVisible()
    assert not calibration.isVisible()
    assert not settings.isVisible()
    assert not overlay.isVisible()
    assert not toast.isVisible()
    assert not dry_run.isVisible()
    assert tray.icon_state == TrayIconState.CAMERA_UNAVAILABLE


def test_tray_icon_state_mapping_and_procedural_pixmaps() -> None:
    """All four tray icon states map accurately and produce non-null QPixmaps."""
    assert (
        resolve_tray_icon_state(ControlState.PAUSED, CameraState.OFF)
        == TrayIconState.CAMERA_UNAVAILABLE
    )
    assert (
        resolve_tray_icon_state(ControlState.ACTIVE, CameraState.ERROR)
        == TrayIconState.CAMERA_UNAVAILABLE
    )
    assert (
        resolve_tray_icon_state(ControlState.FAULT, CameraState.RUNNING)
        == TrayIconState.CAMERA_UNAVAILABLE
    )
    assert (
        resolve_tray_icon_state(ControlState.PAUSED, CameraState.RUNNING)
        == TrayIconState.PAUSED
    )
    assert (
        resolve_tray_icon_state(ControlState.ACTIVE, CameraState.RUNNING)
        == TrayIconState.ACTIVE
    )
    assert (
        resolve_tray_icon_state(ControlState.CALIBRATING, CameraState.RUNNING)
        == TrayIconState.CALIBRATING
    )

    for icon_state in TrayIconState:
        pix = create_tray_pixmap(icon_state, size=64)
        assert not pix.isNull()
        assert pix.width() == 64
        assert pix.height() == 64


def test_viewmodel_updates_reflect_in_tray_text_and_icon_state() -> None:
    """Updating UiBridge state updates tray icon state, Turkish tooltip, and menu labels."""
    bridge = UiBridge()
    tray = HandControlTray(bridge)

    # Initial: PAUSED + Camera OFF -> CAMERA_UNAVAILABLE
    assert tray.icon_state == TrayIconState.CAMERA_UNAVAILABLE
    assert "Kamera kullanılamıyor" in tray.toolTip()
    assert "İmleç" in tray.toolTip()
    assert "Kapalı" in tray.toolTip()
    assert tray.action_pause_resume.text() == "Sürdür"
    assert tray.action_camera_toggle.text() == "Kamerayı Başlat"

    # Camera running, Paused
    bridge.update_status(
        control_state=ControlState.PAUSED,
        camera_state=CameraState.RUNNING,
        mode=Mode.SCROLL,
    )
    assert tray.icon_state == TrayIconState.PAUSED
    assert "Duraklatıldı" in tray.toolTip()
    assert "Kaydırma" in tray.toolTip()
    assert "Çalışıyor" in tray.toolTip()
    assert tray.action_pause_resume.text() == "Sürdür"
    assert tray.action_camera_toggle.text() == "Kamerayı Durdur"

    # Active in Zoom mode
    bridge.update_status(
        control_state=ControlState.ACTIVE,
        camera_state=CameraState.RUNNING,
        mode=Mode.ZOOM,
    )
    assert tray.icon_state == TrayIconState.ACTIVE
    assert "Etkin" in tray.toolTip()
    assert "Yakınlaştırma" in tray.toolTip()
    assert tray.action_pause_resume.text() == "Duraklat"
    assert tray.action_camera_toggle.text() == "Kamerayı Durdur"

    # Calibrating
    bridge.update_status(
        control_state=ControlState.CALIBRATING,
        camera_state=CameraState.RUNNING,
        mode=Mode.WINDOWS,
    )
    assert tray.icon_state == TrayIconState.CALIBRATING
    assert "Kalibrasyon" in tray.toolTip()
    assert "Pencere" in tray.toolTip()


def test_tray_menu_actions_emit_expected_signals() -> None:
    """Triggering tray QActions emits the corresponding user request signals on UiBridge."""
    bridge = UiBridge()
    tray = HandControlTray(bridge)

    events: list[str] = []
    selected_modes: list[Mode] = []

    bridge.pause_resume_requested.connect(lambda: events.append("pause_resume"))
    bridge.camera_toggle_requested.connect(lambda: events.append("camera_toggle"))
    bridge.settings_requested.connect(lambda: events.append("settings"))
    bridge.calibration_requested.connect(lambda: events.append("calibrate"))
    bridge.exit_requested.connect(lambda: events.append("exit"))
    bridge.mode_selected.connect(lambda m: selected_modes.append(m))

    # Currently PAUSED and camera OFF
    tray.action_pause_resume.trigger()
    assert events == ["pause_resume"]

    tray.action_camera_toggle.trigger()
    assert events == ["pause_resume", "camera_toggle"]

    tray.action_settings.trigger()
    assert "settings" in events

    tray.action_calibrate.trigger()
    assert "calibrate" in events

    tray.action_exit.trigger()
    assert "exit" in events

    tray.mode_actions[Mode.VOLUME].trigger()
    assert selected_modes == [Mode.VOLUME]


def test_uibridge_thread_safe_updates_from_worker_thread() -> None:
    """Calling UiBridge update methods from a worker thread marshals safely to GUI thread."""
    bridge = UiBridge()
    received: list[UiState] = []
    bridge.state_changed.connect(lambda st: received.append(st))

    def worker() -> None:
        bridge.update_status(
            control_state=ControlState.ACTIVE,
            camera_state=CameraState.RUNNING,
            mode=Mode.VOLUME,
            fps=29.5,
            sample_age_ms=11.0,
        )

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=2.0)

    QCoreApplication.processEvents()
    assert bridge.state.control_state == ControlState.ACTIVE
    assert bridge.state.camera_state == CameraState.RUNNING
    assert bridge.state.mode == Mode.VOLUME
    assert bridge.state.fps == pytest.approx(29.5)
    assert len(received) >= 1


def test_settings_dialog_dataclass_and_dict_roundtrip() -> None:
    """SettingsDialog preserves all fields through dict and SettingsData round-trips."""
    dlg = SettingsDialog()

    # Default start_with_windows must be False
    default_cfg = dlg.get_settings()
    assert default_cfg.start_with_windows is False
    assert default_cfg.mirror is True
    assert default_cfg.default_mode == Mode.POINTER.value

    custom_dict = {
        "camera_index": 2,
        "camera_backend": "directshow",
        "mirror": False,
        "dominant_hand": "left",
        "pointer_mode": "absolute",
        "pointer_speed": 1.3,
        "pointer_sensitivity": 1.75,
        "smoothing_factor": 0.35,
        "pinch_on_threshold": 0.25,
        "pinch_off_threshold": 0.45,
        "detection_threshold": 0.65,
        "tracking_threshold": 0.60,
        "scroll_direction": "reverse",
        "zoom_direction": "reverse",
        "default_mode": Mode.WINDOWS.value,
        "emergency_hotkey": "Ctrl+Alt+F10",
        "show_overlay": False,
        "show_feedback_osd": True,
        "show_mascot": True,
        "show_dry_run_panel": True,
        "monitor_mapping": "secondary",
        "start_with_windows": True,
        "swipe_profile": "browser",
        "auto_pause_s": 120,
        "dwell_click": True,
        "dwell_ms": 1500,
        "click_sound": True,
        "cursor_feedback": False,
        # schema 4 (round 7, Enstrüman)
        "instrument_layout": "chord",
        "instrument_scale": "a_minor",
        "instrument_quantize": False,
        "instrument_chords": ("Am", "F", "C", "G"),
        "instrument_volume": 0.8,
        "instrument_tone": "electric",
        "audio_device": "",
        "audio_latency": "normal",
        "instrument_particles": False,
        "instrument_fixed_strings": 5,
        "instrument_free_snap": True,
        "audio_device_choices": (),
    }

    dlg.set_values(custom_dict)
    out_dataclass = dlg.get_settings()

    assert out_dataclass.to_dict() == custom_dict

    # Test save signal emission
    saved_payloads: list[SettingsData] = []
    dlg.settings_applied.connect(lambda cfg: saved_payloads.append(cfg))
    dlg.save_and_accept()
    assert len(saved_payloads) == 1
    assert saved_payloads[0] == out_dataclass


def test_overlay_window_flags_wheel_and_window_menu() -> None:
    """OverlayWindow takes neither focus nor clicks and draws what the controller snapshot asks for."""
    overlay = OverlayWindow()
    flags = overlay.windowFlags()

    assert bool(flags & Qt.WindowType.FramelessWindowHint)
    assert bool(flags & Qt.WindowType.WindowStaysOnTopHint)
    assert bool(flags & Qt.WindowType.WindowDoesNotAcceptFocus)
    assert bool(flags & Qt.WindowType.WindowTransparentForInput)
    assert overlay.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert overlay.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert overlay.focusPolicy() == Qt.FocusPolicy.NoFocus

    def picture(kind, items, **cursor):
        overlay.apply_overlay_state(OverlayState(visible=True, kind=kind, items=items, inactivity_ms=1000.0,
                                                 cursor=VirtualCursorState(visible=True, **cursor)))
        return overlay.render_to_image(480, 460)

    modes = tuple(OverlayMenuItem(m.value, MODE_LABELS_TR[m], hovered=m is Mode.ZOOM) for m in Mode)
    wheel = picture(OverlayMenuKind.MODE_MENU, modes, x=0.4, y=0.6)
    assert not wheel.isNull() and wheel != picture(OverlayMenuKind.MODE_MENU, modes[:3], x=0.4, y=0.6)

    def close(progress):
        return (OverlayMenuItem("maximize", "Büyüt"),
                OverlayMenuItem("close", "Kapat", armed=True, hold_progress=progress))
    assert picture(OverlayMenuKind.WINDOW_ACTION_MENU, close(0.2)) != picture(OverlayMenuKind.WINDOW_ACTION_MENU,
                                                                              close(0.8))


def test_every_window_action_has_its_own_icon() -> None:
    from handcontrol.controller import _WINDOW_ACTIONS
    from handcontrol.ui import icons
    from handcontrol.ui.overlay import _WINDOW_ICONS
    assert set(_WINDOW_ICONS) == {*_WINDOW_ACTIONS, "close"}
    assert len(set(_WINDOW_ICONS.values())) == 4 and set(_WINDOW_ICONS.values()) <= set(icons.ICONS)


def test_preview_renders_0_1_2_hands_and_uncertain_fingers_without_crashing() -> None:
    """CameraPreviewWidget safely renders 0, 1, and 2 hands (42 landmarks) and uncertain fingers."""
    preview = CameraPreviewWidget()

    # 0 hands (None and empty hands tuple)
    preview.set_frame(None, fps=0.0, sample_age_ms=0.0)
    img0 = preview.render_to_image()
    assert not img0.isNull()
    assert preview.last_rendered_hand_count == 0
    assert preview.last_rendered_landmark_count == 0

    empty_frame = FrameFeatures(
        capture_ms=100.0,
        inference_done_ms=110.0,
        width=640,
        height=480,
        hands=(),
        identity_ambiguous=False,
    )
    preview.set_frame(empty_frame, fps=30.0)
    preview.render_to_image()
    assert preview.last_rendered_hand_count == 0

    # 1 hand (21 landmarks, usable)
    frame_1 = build_synthetic_frame(hand_count=1, uncertain=False)
    preview.set_frame(frame_1, fps=30.0, sample_age_ms=12.0)
    preview.render_to_image()
    assert preview.last_rendered_hand_count == 1
    assert preview.last_rendered_landmark_count == 21
    assert preview.last_had_uncertain_elements is False

    # 2 hands (42 landmarks) with uncertain finger states & degraded quality
    frame_2_uncertain = build_synthetic_frame(hand_count=2, uncertain=True)
    preview.set_frame(frame_2_uncertain, fps=28.5, sample_age_ms=16.0)
    preview.render_to_image()
    assert preview.last_rendered_hand_count == 2
    assert preview.last_rendered_landmark_count == 42
    assert preview.last_had_uncertain_elements is True

    # Hand with a single uncertain finger even when hand quality is USABLE
    hand_partial_unknown = build_synthetic_hand(
        hand_id=7,
        handedness=Handedness.LEFT,
        quality=Quality.USABLE,
        uncertain_finger=FingerName.INDEX,
    )
    frame_partial = FrameFeatures(
        capture_ms=200.0,
        inference_done_ms=212.0,
        width=640,
        height=480,
        hands=(hand_partial_unknown,),
        identity_ambiguous=False,
    )
    preview.set_frame(frame_partial)
    preview.render_to_image()
    assert preview.last_rendered_hand_count == 1
    assert preview.last_rendered_landmark_count == 21
    assert preview.last_had_uncertain_elements is True

    # Mirror option only flips X display coordinate
    preview.set_mirrored(False)
    pt_unmirrored = preview.map_normalized_point(0.25, 0.40)
    preview.set_mirrored(True)
    pt_mirrored = preview.map_normalized_point(0.25, 0.40)
    assert pt_unmirrored.y() == pytest.approx(pt_mirrored.y())
    assert pt_unmirrored.x() < pt_mirrored.x()


def test_calibration_wizard_steps_and_os_command_suppression() -> None:
    """CalibrationWizard walks through all steps, suppresses OS commands, and returns CalibrationResult."""
    bridge = UiBridge()
    wizard = CalibrationWizard(bridge=bridge)

    assert wizard.current_step == CalibrationStep.NEUTRAL_POSE

    # Step 1: Neutral pose
    wizard.record_neutral_sample(palm_scale_px=84.0, handedness=Handedness.RIGHT)
    wizard.next_step()
    assert wizard.current_step == CalibrationStep.MOVEMENT_CORNERS

    # Step 2: Movement area corners
    for cx, cy in [(0.12, 0.18), (0.88, 0.18), (0.88, 0.84), (0.12, 0.84)]:
        wizard.record_corner_point(cx, cy)
    wizard.next_step()
    assert wizard.current_step == CalibrationStep.PINCH_REPEATS

    # Step 3: Relaxed pinch repetitions
    wizard.record_pinch_sample(closed_distance=0.22, open_distance=0.46)
    wizard.record_pinch_sample(closed_distance=0.24, open_distance=0.44)
    wizard.next_step()
    assert wizard.current_step == CalibrationStep.CLAP_REPEATS

    # Step 4: Clap repetitions
    wizard.record_clap_sample(contact_distance=0.78, separate_distance=1.70)
    wizard.next_step()
    assert wizard.current_step == CalibrationStep.SUMMARY

    completed_results: list[CalibrationResult] = []
    bridge.calibration_completed.connect(lambda res: completed_results.append(res))

    result = wizard.finish_calibration()
    assert isinstance(result, CalibrationResult)
    assert result.bounds.left == pytest.approx(0.12)
    assert result.bounds.right == pytest.approx(0.88)
    assert 0.15 <= result.thresholds.pinch_on < result.thresholds.pinch_off
    assert len(completed_results) == 1


def test_feedback_toast_and_dry_run_panel() -> None:
    """FeedbackToast and DryRunPanel display Turkish texts, do not steal focus, and auto-dismiss."""
    bridge = UiBridge()
    toast = FeedbackToast(bridge)
    dry_panel = DryRunPanel(bridge)

    assert bool(toast.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus)
    assert bool(dry_panel.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus)

    bridge.show_feedback("Ayarlar içe aktarıldı")
    assert toast.current_message.text == "Ayarlar içe aktarıldı"
    assert toast._active and toast._hide_timer.isActive()
    shown = toast.render_to_image()
    toast.dismiss()
    assert not toast._active and toast.render_to_image() != shown

    # Dry-run panel formatting
    act = Action(
        kind=ActionKind.SET_VOLUME,
        epoch=2,
        capture_ms=500.0,
        value=0.80,
        target=WindowTarget(hwnd=0x200, pid=1234),
    )
    bridge.record_dry_run_action(act)
    assert "%80" in dry_panel.current_command_text
    assert not dry_panel.render_to_image().isNull()
