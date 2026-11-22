"""Sabit teller UI: the string area is drawn and can be moved/resized with the mouse (both mirror modes)."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from handcontrol.contracts import FrameFeatures
from handcontrol.instrument.engine import InstrumentConfig, InstrumentEngine
from handcontrol.ui.instrument_view import FIXED_HINT_TR, InstrumentWindow
from handcontrol.ui.settings import INSTRUMENT_LAYOUT_LABELS_TR, SettingsData, SettingsDialog

RECT = (0.25, 0.35, 0.75, 0.65)


@pytest.fixture
def qt():
    return QApplication.instance() or QApplication([])


def _window(mirrored: bool) -> tuple[InstrumentWindow, list]:
    win = InstrumentWindow(clock=lambda: 1000.0)
    win.resize(960, 620)
    win.canvas.resize(960, 620)
    win.set_mirrored(mirrored)
    _, view = InstrumentEngine(InstrumentConfig(layout="fixed", fixed_rect=RECT)).update(
        FrameFeatures(0.0, 5.0, 640, 480, (), False), True)
    win.update_view(view)
    got: list = []
    win.fixed_rect_changed.connect(got.append)
    return win, got


def _pt(win: InstrumentWindow, nx: float, ny: float) -> QPoint:
    c = win.canvas
    p = c.map_normalized_point(nx, ny, c.canvas_rect_for(QRectF(c.rect())))
    return QPoint(round(p.x()), round(p.y()))


def _drag(win: InstrumentWindow, a: QPoint, b: QPoint) -> None:
    c = win.canvas
    QTest.mousePress(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, a)
    QTest.mouseMove(c, QPoint((a.x() + b.x()) // 2, (a.y() + b.y()) // 2))
    QTest.mouseMove(c, b)
    QTest.mouseRelease(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, b)


@pytest.mark.parametrize("mirrored", [True, False])
def test_drag_inside_moves_the_area(qt, mirrored):
    win, got = _window(mirrored)
    try:
        _drag(win, _pt(win, 0.5, 0.5), _pt(win, 0.6, 0.3))
        assert len(got) == 1
        x0, y0, x1, y1 = got[0]
        assert (x1 - x0, y1 - y0) == pytest.approx((0.5, 0.3), abs=1e-3)       # size kept
        assert (x0, y0) == pytest.approx((0.35, 0.15), abs=0.01)
    finally:
        win.close()


@pytest.mark.parametrize("mirrored", [True, False])
def test_drag_a_corner_resizes_the_area(qt, mirrored):
    win, got = _window(mirrored)
    try:
        _drag(win, _pt(win, 0.75, 0.65), _pt(win, 0.9, 0.9))                  # bottom-right corner
        assert got and got[0] == pytest.approx((0.25, 0.35, 0.9, 0.9), abs=0.01)
    finally:
        win.close()


def test_move_is_clamped_to_the_frame_and_a_click_changes_nothing(qt):
    win, got = _window(True)
    try:
        _drag(win, _pt(win, 0.5, 0.5), _pt(win, 0.5, 0.5))
        assert got == []
        _drag(win, _pt(win, 0.5, 0.5), _pt(win, 0.99, 0.99))
        x0, y0, x1, y1 = got[0]
        assert x1 <= 1.0 and y1 <= 1.0 and (x1 - x0, y1 - y0) == pytest.approx((0.5, 0.3), abs=1e-3)
        _drag(win, _pt(win, 0.05, 0.05), _pt(win, 0.2, 0.2))                  # outside: no drag
        assert len(got) == 1
    finally:
        win.close()


def test_area_and_hint_are_painted(qt):
    win, _ = _window(False)
    try:
        main, layout, status = win.hud_lines()
        assert layout == "Düzen: Sabit teller"
        img = win.render_to_image(960, 620)
        c = win.canvas
        box = c.area_widget_rect(RECT, c.canvas_rect_for(QRectF(0, 0, 960, 620)))
        corner = img.pixelColor(round(box.left()), round(box.top()))
        assert corner.blue() - corner.red() > 15                              # bluish handle drawn
        assert FIXED_HINT_TR not in status                                    # no hands: "Elinizi gösterin"
    finally:
        win.close()


def test_settings_tab_offers_fixed_layout_and_string_count(qt):
    assert INSTRUMENT_LAYOUT_LABELS_TR["fixed"] == "Sabit teller"
    dlg = SettingsDialog()
    try:
        dlg.set_values(SettingsData(instrument_layout="fixed", instrument_fixed_strings=7))
        data = dlg.get_settings()
        assert data.instrument_layout == "fixed" and data.instrument_fixed_strings == 7
        assert dlg.combo_instrument_layout.findData("fixed") >= 0
        assert SettingsData.from_dict({"instrument_fixed_strings": 99}).instrument_fixed_strings == 8
    finally:
        dlg.close()
