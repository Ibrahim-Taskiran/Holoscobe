"""Round 6 UI: Komutlar mode labels, cursor hold ring, command toast, settings schema 3,
tray tutorial entry and the onboarding tutorial. Offscreen only."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from handcontrol.contracts import KeyCommand, Mode
from handcontrol.ui.dpi import logical_to_physical
from handcontrol.ui.onboarding import OnboardingDialog, OnboardingStep
from handcontrol.ui.overlay import HOLD_KIND_COLORS, CursorFeedbackOverlay
from handcontrol.ui.settings import SENSITIVITY_PRESETS, SettingsData, SettingsDialog
from handcontrol.ui.tray import HandControlTray
from handcontrol.ui.viewmodel import (
    COMMAND_LABELS_TR,
    MODE_LABELS_TR,
    CursorFeedbackState,
    UiBridge,
    create_mode_menu_items,
)


@dataclass(frozen=True)
class FakeSnapshot:
    hold_kind: str = ""
    hold_progress: float = 0.0
    pointer: Optional[tuple[int, int]] = (500, 400)
    last_command: str = ""
    command_seq: int = 0


# ---------- labels ----------

def test_commands_mode_labels_everywhere() -> None:
    assert MODE_LABELS_TR[Mode.COMMANDS] == "Komutlar"
    assert set(MODE_LABELS_TR) == set(Mode)
    assert "Komutlar" in [i.label for i in create_mode_menu_items()]
    tray = HandControlTray(UiBridge())
    assert tray.mode_actions[Mode.COMMANDS].text() == "Komutlar"
    assert not tray.mode_actions[Mode.COMMANDS].icon().isNull()
    dlg = SettingsDialog()
    assert dlg.combo_mode.findData("commands") >= 0
    assert SettingsData.from_dict({"default_mode": "commands"}).default_mode == "commands"


def test_command_labels_cover_every_key_command() -> None:
    assert set(COMMAND_LABELS_TR) == {c.value for c in KeyCommand}
    assert COMMAND_LABELS_TR["task_view"] == "Görev görünümü"
    assert COMMAND_LABELS_TR["volume_mute"] == "Sesi kapat/aç"


# ---------- cursor ring + command toast ----------

def _ring(enabled: list[bool] | None = None) -> tuple[UiBridge, CursorFeedbackOverlay]:
    bridge = UiBridge()
    flag = enabled if enabled is not None else [True]
    ring = CursorFeedbackOverlay(bridge, enabled_fn=lambda: flag[0], follow_os_cursor=False,
                                 auto_show_window=False)
    return bridge, ring


def test_ring_progress_kind_color_and_smoothing() -> None:
    bridge, ring = _ring()
    assert not ring.ring_visible
    bridge.update_snapshot(FakeSnapshot(hold_kind="right_click", hold_progress=0.5))
    assert ring.ring_visible and ring.hold_kind == "right_click"
    assert ring.target_progress == pytest.approx(0.5)
    assert ring.ring_color == HOLD_KIND_COLORS["right_click"]
    QTest.qWait(150)
    assert 0.3 < ring.displayed_progress <= 0.5          # eased toward target, no jump
    assert not ring.render_to_image().isNull()
    bridge.update_snapshot(FakeSnapshot(hold_kind="grab", hold_progress=0.2))
    assert ring.ring_color == HOLD_KIND_COLORS["grab"]


def test_ring_survives_brief_dropout_then_fades() -> None:
    bridge, ring = _ring()
    bridge.update_snapshot(FakeSnapshot(hold_kind="dwell", hold_progress=0.6))
    bridge.update_snapshot(FakeSnapshot(hold_progress=0.0))
    assert ring.ring_visible                               # grace period: no flicker
    QTest.qWait(500)
    assert not ring.ring_visible and not ring.is_animating


def test_ring_hidden_when_cursor_feedback_off() -> None:
    flag = [False]
    bridge, ring = _ring(flag)
    bridge.update_snapshot(FakeSnapshot(hold_kind="fist", hold_progress=0.7))
    assert not ring.ring_visible
    flag[0] = True
    bridge.update_snapshot(FakeSnapshot(hold_kind="fist", hold_progress=0.8))
    assert ring.ring_visible


def test_bridge_cursor_feedback_only_on_change() -> None:
    bridge = UiBridge()
    seen: list[CursorFeedbackState] = []
    bridge.cursor_feedback_updated.connect(seen.append)
    bridge.update_snapshot(FakeSnapshot(hold_kind="grab", hold_progress=0.25))
    bridge.update_snapshot(FakeSnapshot(hold_kind="grab", hold_progress=0.25))
    assert len(seen) == 1 and seen[0].kind == "grab" and (seen[0].x, seen[0].y) == (500, 400)


def test_command_toast_on_seq_change() -> None:
    bridge, ring = _ring()
    fired: list[str] = []
    bridge.command_triggered.connect(fired.append)
    bridge.update_snapshot(FakeSnapshot(last_command="next", command_seq=4))   # baseline: no toast
    assert fired == [] and not ring.toast_visible
    bridge.update_snapshot(FakeSnapshot(last_command="task_view", command_seq=5))
    assert fired == ["task_view"]
    assert ring.toast_text == "Görev görünümü"
    bridge.update_snapshot(FakeSnapshot(last_command="task_view", command_seq=5))
    assert fired == ["task_view"]                           # same seq: no repeat
    bridge.update_snapshot(FakeSnapshot(last_command="task_view", command_seq=6))
    assert fired == ["task_view", "task_view"]              # repeated command still toasts
    QTest.qWait(1100)
    assert not ring.toast_visible


# ---------- settings ----------

def test_settings_new_fields_defaults_and_round_trip() -> None:
    d = SettingsData()
    assert (d.swipe_profile, d.auto_pause_s, d.dwell_click, d.dwell_ms, d.click_sound,
            d.cursor_feedback) == ("auto", 0, False, 1000, False, True)
    custom = SettingsData(swipe_profile="desktops", auto_pause_s=300, dwell_click=True,
                          dwell_ms=2200, click_sound=True, cursor_feedback=False)
    dlg = SettingsDialog(initial=custom)
    assert dlg.get_settings() == custom
    assert SettingsData.from_dict(custom.to_dict()) == custom
    assert dlg.combo_swipe_profile.currentText() == "Sanal masaüstleri"
    assert dlg.combo_auto_pause.currentText() == "5 dk"
    # off-list auto pause from config is kept, too-small values clamp to 10
    dlg.set_values({"auto_pause_s": 45})
    assert dlg.get_settings().auto_pause_s == 45
    assert SettingsData.from_dict({"auto_pause_s": 3}).auto_pause_s == 10
    assert SettingsData.from_dict({"dwell_ms": 99}).dwell_ms == 400
    assert SettingsData.from_dict({"swipe_profile": "bogus"}).swipe_profile == "auto"


def test_settings_labels_and_tabs() -> None:
    dlg = SettingsDialog()
    assert [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())] == ["Genel", "İmleç", "Hareketler", "Gelişmiş"]
    assert [dlg.combo_swipe_profile.itemText(i) for i in range(dlg.combo_swipe_profile.count())] == [
        "Otomatik", "Sunum", "Tarayıcı", "Medya", "Sanal masaüstleri"]
    assert [dlg.combo_auto_pause.itemText(i) for i in range(dlg.combo_auto_pause.count())] == [
        "Kapalı", "30 sn", "1 dk", "2 dk", "5 dk"]
    assert not dlg.slider_dwell_ms.isEnabled()
    dlg.chk_dwell_click.setChecked(True)
    assert dlg.slider_dwell_ms.isEnabled()
    dlg.set_dwell_ms(1500)
    assert dlg.label_dwell_ms.text() == "1,5 sn"


def test_sensitivity_preset_logic() -> None:
    dlg = SettingsDialog()
    assert dlg.current_preset() == "normal"
    assert dlg.combo_preset.currentText() == "Normal"
    dlg.apply_preset("precise")
    assert (dlg.pointer_speed(), dlg.spin_sensitivity.value()) == (0.7, 0.8)
    dlg.apply_preset("fast")
    assert (dlg.get_settings().pointer_speed, dlg.get_settings().pointer_sensitivity) == SENSITIVITY_PRESETS["fast"]
    dlg.slider_pointer_speed.setValue(dlg.slider_pointer_speed.value() + 1)   # user edit
    assert dlg.combo_preset.currentText() == "Özel"
    assert dlg.pointer_speed() == 1.6                                         # edit kept
    dlg.slider_pointer_speed.setValue(15)
    assert dlg.current_preset() == "fast"                                      # matches again
    dlg2 = SettingsDialog(initial=SettingsData(pointer_speed=0.7, pointer_sensitivity=0.8))
    assert dlg2.current_preset() == "precise"


def test_settings_tool_signals(monkeypatch: pytest.MonkeyPatch) -> None:
    dlg = SettingsDialog()
    got: dict[str, list] = {"exp": [], "imp": [], "diag": [], "tut": []}
    dlg.export_settings_requested.connect(got["exp"].append)
    dlg.import_settings_requested.connect(got["imp"].append)
    dlg.diagnostics_requested.connect(lambda: got["diag"].append(1))
    dlg.tutorial_requested.connect(lambda: got["tut"].append(1))
    monkeypatch.setattr(dlg, "_ask_export_path", lambda: "C:/x/out.json")
    monkeypatch.setattr(dlg, "_ask_import_path", lambda: "")
    dlg.btn_export.click()
    dlg.btn_import.click()                                   # cancelled dialog: no signal
    dlg.btn_diagnostics.click()
    dlg.btn_tutorial.click()
    assert got == {"exp": ["C:/x/out.json"], "imp": [], "diag": [1], "tut": [1]}


# ---------- tray ----------

def test_tray_tutorial_entry_emits() -> None:
    bridge = UiBridge()
    tray = HandControlTray(bridge)
    tray_hits: list[int] = []
    bridge_hits: list[int] = []
    tray.tutorial_requested.connect(lambda: tray_hits.append(1))
    bridge.tutorial_requested.connect(lambda: bridge_hits.append(1))
    assert tray.action_tutorial.text() == "Eğitimi başlat"
    assert tray.action_tutorial in tray.menu.actions()
    tray.action_tutorial.trigger()
    assert tray_hits == [1] and bridge_hits == [1]


# ---------- onboarding ----------

@pytest.fixture
def onboarding():
    dlg = OnboardingDialog(hotkey="Ctrl+Alt+Shift+F12", dominant_hand="left")
    dlg.auto_advance_ms = None
    dlg.show()                       # offscreen platform: nothing appears on the real screen
    QTest.qWaitForWindowExposed(dlg)
    yield dlg
    dlg.close()


def _act(dlg: OnboardingDialog, kind: str, local) -> None:
    g = dlg.practice.mapToGlobal(QPoint(round(local.x()), round(local.y())))
    x, y = logical_to_physical(g)
    dlg.on_action(kind, x, y)


def test_onboarding_welcome_texts_and_window(onboarding: OnboardingDialog) -> None:
    dlg = onboarding
    assert dlg.current_step == OnboardingStep.WELCOME
    assert not bool(dlg.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
    assert (dlg.width(), dlg.height()) == (900, 600)
    assert not dlg.btn_back.isEnabled() and dlg.btn_skip.isVisible()
    texts = " ".join(lbl.text() for lbl in dlg.page_welcome.findChildren(type(dlg.title_label)))
    for needle in ("Dirseğini masaya daya", "40–70 cm", "aydınlık", "Ctrl+Alt+Shift+F12", "el çırp"):
        assert needle in texts
    dlg.go_next()
    assert "Sol elinin" in dlg.hint_label.text()


def test_onboarding_progression_via_on_action(onboarding: OnboardingDialog) -> None:
    dlg = onboarding
    dlg.go_next()
    assert dlg.current_step == OnboardingStep.POINT and dlg.required == 3
    assert dlg.hint_visible
    _act(dlg, "move_pointer", dlg.practice.rect().topLeft() + QPoint(5, 5))   # outside targets
    assert dlg.successes == 0
    for i in range(3):
        _act(dlg, "move_pointer", dlg.target_center())
        assert dlg.successes == i + 1
        if i == 1:
            assert not dlg.hint_visible          # hidden after 2 successes
    assert dlg.step_complete and dlg.counter_label.text() == "3 / 3"

    dlg.go_next()
    assert dlg.current_step == OnboardingStep.CLICK
    _act(dlg, "left_click", dlg.target_center())
    _act(dlg, "left_click", dlg.target_center())
    assert dlg.step_complete

    dlg.go_next()
    _act(dlg, "left_click", dlg.target_center())
    assert dlg.successes == 0
    _act(dlg, "double_click", dlg.target_center())
    assert dlg.step_complete

    dlg.go_next()
    assert dlg.current_step == OnboardingStep.RIGHT_CLICK
    _act(dlg, "right_click", dlg.target_center())
    assert dlg.step_complete

    dlg.go_next()
    assert dlg.current_step == OnboardingStep.DRAG
    box = dlg.box_rect().center()
    zone = dlg.zone_rect().center()
    _act(dlg, "left_down", box)
    assert dlg.dragging
    _act(dlg, "move_pointer", (box + zone) / 2)
    _act(dlg, "left_up", zone)
    assert dlg.step_complete and not dlg.dragging

    dlg.go_next()
    assert dlg.current_step == OnboardingStep.MODES
    dlg.go_next()
    assert dlg.current_step == OnboardingStep.DONE and dlg.btn_next.text() == "Bitir"
    done: list[int] = []
    dlg.completed.connect(lambda: done.append(1))
    dlg.btn_next.click()
    assert done == [1]


def test_onboarding_real_mouse_clicks(onboarding: OnboardingDialog) -> None:
    dlg = onboarding
    dlg.go_next()
    dlg.go_next()
    assert dlg.current_step == OnboardingStep.CLICK
    for _ in range(2):
        QTest.mouseClick(dlg.practice, Qt.MouseButton.LeftButton, pos=dlg.target_center().toPoint())
    assert dlg.step_complete
    dlg.go_next()
    QTest.mouseDClick(dlg.practice, Qt.MouseButton.LeftButton, pos=dlg.target_center().toPoint())
    assert dlg.step_complete
    dlg.go_next()
    QTest.mouseClick(dlg.practice, Qt.MouseButton.RightButton, pos=dlg.target_center().toPoint())
    assert dlg.step_complete
    dlg.go_next()
    start = dlg.box_rect().center().toPoint()
    end = dlg.zone_rect().center().toPoint()
    QTest.mousePress(dlg.practice, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(dlg.practice, end)
    QTest.mouseRelease(dlg.practice, Qt.MouseButton.LeftButton, pos=end)
    assert dlg.step_complete


def test_onboarding_dedupes_action_and_qt_click(onboarding: OnboardingDialog) -> None:
    dlg = onboarding
    dlg.go_next()
    dlg.go_next()
    spot = dlg.target_center()
    _act(dlg, "left_click", spot)                                       # controller action ...
    QTest.mouseClick(dlg.practice, Qt.MouseButton.LeftButton, pos=spot.toPoint())  # ... its OS click
    assert dlg.successes == 1


def test_onboarding_back_and_hint_idle_return(onboarding: OnboardingDialog) -> None:
    dlg = onboarding
    dlg.go_next()
    for _ in range(2):
        _act(dlg, "move_pointer", dlg.target_center())
    assert not dlg.hint_visible
    dlg._on_idle()                                   # 10 s without progress
    assert dlg.hint_visible
    dlg.go_back()
    assert dlg.current_step == OnboardingStep.WELCOME and dlg.successes == 0


def test_onboarding_auto_advance(onboarding: OnboardingDialog) -> None:
    dlg = onboarding
    dlg.auto_advance_ms = 10
    dlg.go_next()
    for _ in range(3):
        _act(dlg, "move_pointer", dlg.target_center())
    QTest.qWait(80)
    assert dlg.current_step == OnboardingStep.CLICK


def test_onboarding_skip_signal() -> None:
    dlg = OnboardingDialog(hotkey="F12")
    events: list[str] = []
    dlg.skipped.connect(lambda: events.append("skip"))
    dlg.completed.connect(lambda: events.append("done"))
    dlg.btn_skip.click()
    assert events == ["skip"]
    dlg.reject()                                      # no second emission
    assert events == ["skip"]
