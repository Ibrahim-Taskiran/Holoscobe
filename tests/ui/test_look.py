"""The look: tokens, shared controls, mascot controls and the responsive main window."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QCheckBox, QLabel

from handcontrol.contracts import CameraState, ControlState, Mode
from handcontrol.ui import HandControlTray, SettingsData, SettingsDialog, UiBridge, UiState, icons, theme
from handcontrol.ui.main_window import MainWindow
from handcontrol.ui.widgets import ComboBox, HintBar, SettingRow, ToggleSwitch

UI = Path(theme.__file__).parent


def _contrast(a: str, b: str) -> float:
    def lum(c: str) -> float:
        parts = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in QColor(c).getRgbF()[:3]]
        return 0.2126 * parts[0] + 0.7152 * parts[1] + 0.0722 * parts[2]
    x, y = sorted((lum(a), lum(b)), reverse=True)
    return (x + 0.05) / (y + 0.05)


@pytest.mark.parametrize("fg", [theme.TEXT, theme.TEXT_SOFT, theme.MUTED, theme.ACCENT_TEXT, theme.SUCCESS,
                                theme.WARNING, theme.DANGER])
@pytest.mark.parametrize("bg", [theme.BG, theme.SURFACE, theme.RAISED])
def test_text_colors_meet_wcag_aa(fg: str, bg: str) -> None:
    assert _contrast(fg, bg) >= 4.5


def test_primary_button_and_switch_outline_contrast() -> None:
    for fill in (theme.ACCENT, theme.ACCENT_HOVER, theme.ACCENT_PRESSED):
        assert _contrast(theme.ON_ACCENT, fill) >= 4.5
    assert _contrast(theme.CONTROL_STROKE, theme.SURFACE) >= 3.0


def test_theme_is_the_only_palette() -> None:
    for path in UI.glob("*.py"):
        if path.name != "theme.py":
            code = path.read_text(encoding="utf-8")
            assert not re.search(r"""["']#[0-9a-fA-F]{6}["']""", code), path.name
            assert not re.search(r"QColor\(\d", code), path.name


def test_every_icon_and_mode_icon_draws_something() -> None:
    assert set(icons.MODE_ICONS) == set(Mode)
    blank = icons.pixmap("check", 24, QColor(0, 0, 0, 0)).toImage()
    for name in icons.ICONS:
        assert icons.pixmap(name, 24).toImage() != blank, name


# ---------- mascot ----------

def test_bridge_mascot_request_and_visibility() -> None:
    bridge = UiBridge()
    asked, shown = [], []
    bridge.mascot_toggle_requested.connect(asked.append)
    bridge.mascot_visible_changed.connect(shown.append)
    assert bridge.mascot_visible is True
    bridge.request_mascot(False)
    assert asked == [False] and shown == [] and bridge.mascot_visible is True
    bridge.set_mascot_visible(False)
    assert shown == [False] and bridge.mascot_visible is False and asked == [False]


def test_mascot_button_and_tray_action_request_and_mirror() -> None:
    bridge = UiBridge()
    win = MainWindow(bridge, live=True)
    tray = HandControlTray(bridge)
    asked: list[bool] = []
    bridge.mascot_toggle_requested.connect(asked.append)
    assert win.mascot_button.text() == "Kedi" and tray.action_mascot.text() == "Kediyi göster"
    assert win.mascot_button.isChecked() and tray.action_mascot.isChecked()
    bridge.set_mascot_visible(False)                       # mirrors without asking again
    assert not win.mascot_button.isChecked() and not tray.action_mascot.isChecked() and asked == []
    win.mascot_button.click()
    assert asked == [True]
    tray.action_mascot.trigger()
    assert asked == [True, True]
    win.deleteLater()


def test_settings_mascot_and_hide_on_control() -> None:
    assert SettingsData().show_mascot is True and SettingsData().hide_on_control is True
    dlg = SettingsDialog(initial=SettingsData(show_mascot=False, hide_on_control=False))
    out = dlg.get_settings()
    assert out.show_mascot is False and out.hide_on_control is False
    assert SettingsData.from_dict(out.to_dict()) == out
    assert dlg.chk_mascot.text() == "Sağ alttaki kediyi göster"
    assert dlg.chk_hide_on_control.text() == "Kontrol başlayınca ana pencereyi küçült"
    dlg.reset_to_defaults()
    assert dlg.get_settings().hide_on_control is True


# ---------- shared controls ----------

def test_toggle_switch_is_a_checkbox_and_its_row_toggles_it() -> None:
    switch = ToggleSwitch("Deneme")
    row = SettingRow("Deneme", "Açıklama", switch)
    row.resize(500, 60)
    row.show()
    assert isinstance(switch, QCheckBox) and switch.accessibleName() == "Deneme"
    title = row.findChildren(QLabel)[0]
    QTest.mouseClick(title, Qt.MouseButton.LeftButton, pos=QPoint(5, 5))
    assert switch.isChecked()
    QTest.mouseClick(switch, Qt.MouseButton.LeftButton)
    assert not switch.isChecked()
    row.close()


def test_settings_sidebar_follows_the_pages() -> None:
    dlg = SettingsDialog()
    for i in range(dlg.tabs.count()):
        button = dlg.side_group.button(i)
        assert button.text() == dlg.tabs.tabText(i)
        button.click()
        assert dlg.tabs.currentIndex() == i
    dlg.tabs.setCurrentIndex(0)
    assert dlg.side_group.button(0).isChecked()


def test_combo_ignores_the_wheel_until_it_has_focus() -> None:
    combo = ComboBox()
    combo.addItems(["a", "b"])
    event = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, -120), Qt.MouseButton.NoButton,
                        Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    combo.wheelEvent(event)
    assert combo.currentIndex() == 0 and not event.isAccepted()


def test_hint_bar_splits_gestures_and_keeps_the_sentence() -> None:
    bar = HintBar()
    bar.setText("İşaret parmağı: imleç  ·  uçtan tut: boyutlandır · Sağ işaretle çiz")
    assert bar.parts() == [("İşaret parmağı", "imleç"), ("Uçtan tut", "boyutlandır"), ("Sağ işaretle çiz", "")]
    assert bar.text().startswith("İşaret parmağı: imleç")


def test_hints_move_beside_the_stage_on_a_wide_window() -> None:
    win = MainWindow(UiBridge(), live=True)
    win.apply_state(UiState(mode=Mode.POINTER, control_state=ControlState.ACTIVE, camera_state=CameraState.RUNNING))
    win.resize(900, 620)
    win._arrange()
    assert not win.hint.vertical
    win.resize(1600, 900)
    win._arrange()
    assert win.hint.vertical
    win.resize(900, 620)
    win._arrange()
    assert not win.hint.vertical
    win.deleteLater()
