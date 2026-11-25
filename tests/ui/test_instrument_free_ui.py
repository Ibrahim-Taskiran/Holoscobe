"""Serbest teller UI: draw, resize, stack and delete strings with the mouse (both mirror modes)."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from handcontrol.contracts import FrameFeatures
from handcontrol.instrument.engine import InstrumentConfig, InstrumentEngine
from handcontrol.ui.instrument_view import FREE_HINT_TR, InstrumentWindow
from handcontrol.ui.settings import INSTRUMENT_LAYOUT_LABELS_TR

S = (0.2, 0.3, 0.7, 0.3)


@pytest.fixture
def qt():
    return QApplication.instance() or QApplication([])


def _window(mirrored: bool, strings=(S,), snap: bool = True) -> tuple[InstrumentWindow, list]:
    win = InstrumentWindow(clock=lambda: 1000.0)
    win.resize(960, 620)
    win.canvas.resize(960, 620)
    win.set_mirrored(mirrored)
    win.set_free_snap(snap)
    _, view = InstrumentEngine(InstrumentConfig(layout="free", free_strings=strings)).update(
        FrameFeatures(0.0, 5.0, 640, 480, (), False), True)
    win.update_view(view)
    got: list = []
    win.free_strings_changed.connect(got.append)
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
def test_drag_on_empty_space_draws_and_stacks_a_string(qt, mirrored):
    win, got = _window(mirrored)
    try:
        _drag(win, _pt(win, 0.21, 0.42), _pt(win, 0.6, 0.43))
        assert len(got) == 1 and len(got[0]) == 2
        assert got[0][1] == pytest.approx((0.2, 0.425, 0.59, 0.425), abs=0.01)    # one end aligned under S
    finally:
        win.close()


def test_the_note_is_written_on_the_string_while_it_is_stretched(qt):
    win, _ = _window(True, strings=())
    asked: list = []
    win.set_free_note(lambda seg, aspect: asked.append((seg[2] - seg[0]) * aspect) or f"N{len(asked)}")
    c = win.canvas
    try:
        shown = []
        QTest.mousePress(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, _pt(win, 0.2, 0.5))
        for x in (0.5, 0.8):
            QTest.mouseMove(c, _pt(win, x, 0.5))
            shown.append(win.render_to_image(960, 620))
        assert [round(abs(v), 1) for v in asked] == [0.4, 0.8] and shown[0] != shown[1]
    finally:
        win.close()


def test_without_snap_the_drawn_string_is_kept_as_is(qt):
    win, got = _window(False, snap=False)
    try:
        _drag(win, _pt(win, 0.21, 0.42), _pt(win, 0.69, 0.47))
        x0, y0, x1, y1 = got[0][1]
        assert (x0, y1 - y0) == pytest.approx((0.21, 0.05), abs=0.01)
    finally:
        win.close()


@pytest.mark.parametrize("mirrored", [True, False])
def test_drag_an_end_resizes_and_right_click_deletes(qt, mirrored):
    win, got = _window(mirrored)
    try:
        _drag(win, _pt(win, 0.7, 0.3), _pt(win, 0.9, 0.3))
        assert got[-1] == (pytest.approx((0.2, 0.3, 0.9, 0.3), abs=0.01),)
        QTest.mouseClick(win.canvas, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, _pt(win, 0.45, 0.3))
        assert got[-1] == ()
    finally:
        win.close()


def test_delete_key_clears_and_hud_shows_the_hint(qt):
    win, got = _window(False)
    try:
        assert INSTRUMENT_LAYOUT_LABELS_TR["free"] == "Serbest teller"
        assert win.hud_lines()[1] == "Düzen: Serbest teller"
        QTest.keyClick(win.canvas, Qt.Key.Key_Delete)
        assert got == [()]
        assert not win.render_to_image(480, 320).isNull()
        assert FREE_HINT_TR
    finally:
        win.close()
