"""The one main window: control and Enstrüman pages, mode buttons, instrument bar."""
from __future__ import annotations

from dataclasses import replace

import pytest
from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QApplication

from handcontrol.config import Settings
from handcontrol.contracts import CameraState, ControlState, Mode
from handcontrol.instrument_runtime import idle_view, instrument_config
from handcontrol.ui import UiBridge, UiState
from handcontrol.ui.instrument_view import FREE_EMPTY_TR, NO_CAMERA_HINT_TR, PAUSED_HINT_TR
from handcontrol.ui.main_window import MainWindow


@pytest.fixture
def win():
    QApplication.instance() or QApplication([])
    w = MainWindow(UiBridge(), live=True)
    yield w
    w.close()
    w.deleteLater()


def state(mode=Mode.POINTER, **kw):
    return UiState(mode=mode, control_state=ControlState.ACTIVE, camera_state=CameraState.RUNNING, **kw)


def test_instrument_is_a_page_of_the_same_window(win):
    assert not win.instrument.isWindow() and win.instrument.window() is win
    win.apply_state(state())
    assert win.stack.currentWidget() is win.preview and win.instrument_bar.isHidden()
    win.show()
    place = win.pos()
    win.apply_state(state(Mode.INSTRUMENT))
    assert win.stack.currentWidget() is win.instrument and not win.instrument_bar.isHidden()
    assert win.pos() == place and win.isVisible()          # same place, brought up if it was closed
    assert win.mode_buttons[Mode.INSTRUMENT].isChecked()
    win.apply_state(state(Mode.WINDOWS))
    assert win.stack.currentWidget() is win.preview and win.more_button.isChecked()


def test_mode_buttons_and_start_button_emit_requests(win):
    modes, pauses = [], []
    win._bridge.mode_selected.connect(modes.append)
    win._bridge.pause_resume_requested.connect(lambda: pauses.append(1))
    for button in win.mode_buttons.values():
        button.click()
    for action in win.more_actions.values():
        action.trigger()
    win.start_button.click()
    assert set(modes) == set(Mode) and len(modes) == len(Mode) and pauses == [1]
    assert len(win.mode_buttons) == 4


def test_every_mode_has_its_own_hint_and_more_shows_the_mode(win):
    hints = set()
    for m in Mode:
        win.apply_state(state(m))
        hints.add(win.hint.text())
        assert "V yap" in win.hint.text()
        assert win.more_button.isChecked() is (m not in win.mode_buttons)
    assert len(hints) == len(Mode)
    win.apply_state(state(Mode.ZOOM))
    assert win.more_button.text() == "Yakınlaştırma"
    win.apply_state(state(Mode.POINTER))
    assert win.more_button.text() == "Diğer" and win.mode_buttons[Mode.POINTER].isChecked()


def test_instrument_bar_mirrors_settings_and_emits_single_changes(win):
    changes, strings = [], []
    win.instrument_changed.connect(changes.append)
    win.free_strings_changed.connect(strings.append)
    two = [[0.1, 0.2, 0.5, 0.2], [0.1, 0.4, 0.5, 0.4]]
    win.apply_instrument_settings(replace(Settings(), instrument_free_strings=two, instrument_volume=0.7))
    assert changes == [] and win.layout_buttons["free"].isChecked() and win.volume_slider.value() == 70
    assert not win.undo_button.isHidden() and win.count_spin.isHidden()
    win.undo_button.click()
    win.clear_button.click()
    assert strings == [((0.1, 0.2, 0.5, 0.2),), ()]
    win.layout_buttons["fixed"].click()
    win.volume_slider.setValue(40)
    win.tone_combo.setCurrentIndex(1)
    assert changes == [{"instrument_layout": "fixed"}, {"instrument_volume": 0.4}, {"instrument_tone": "electric"}]
    win.apply_instrument_settings(replace(Settings(), instrument_layout="fixed"))
    assert win.undo_button.isHidden() and not win.count_spin.isHidden()


def test_dry_run_banner_only_without_live(win):
    assert win.banner.isHidden()
    dry = MainWindow(UiBridge(), live=False)
    assert not dry.banner.isHidden()
    dry.deleteLater()


def test_camera_picture_is_never_stretched(win):
    for widget in (win.preview, win.instrument.canvas):
        for size in ((1000, 400), (400, 900)):
            r = widget.canvas_rect_for(QRectF(0, 0, *size))
            assert r.width() / r.height() == pytest.approx(4 / 3)
            assert r.left() >= 0 and r.right() <= size[0] and r.top() >= 0 and r.bottom() <= size[1]


def test_center_hints_explain_why_nothing_sounds(win):
    c = win.instrument.canvas
    assert c.center_hint() == NO_CAMERA_HINT_TR
    view = idle_view(instrument_config(Settings()))
    c.set_view(view)
    assert c.center_hint() == NO_CAMERA_HINT_TR
    c.set_view(replace(view, t_ms=5.0))
    assert c.center_hint() == PAUSED_HINT_TR
    c.set_view(replace(view, t_ms=5.0, status="Hazır"))
    assert c.center_hint() == FREE_EMPTY_TR
    c.set_view(replace(view, t_ms=5.0, status="Hazır", free_pending=(((0.5, 0.5), 0.3),)))
    assert c.center_hint() is None
