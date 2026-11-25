"""Drawing mode in the app: no OS input, mode routing, canvas page, safe pause, rendering."""
from __future__ import annotations

import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "integration"))

from integ_synth import FIST, OPEN, POINT, Rig, hand as raw_hand  # noqa: E402

from handcontrol import app as app_module  # noqa: E402
from handcontrol.app import Runtime  # noqa: E402
from handcontrol.config import MODES, Settings  # noqa: E402
from handcontrol.contracts import (  # noqa: E402
    ActionKind as A, CameraState, ControlState, FrameFeatures, Handedness, Mode, PoseFrameFeatures)
from handcontrol.drawing import MAX_DABS, InkScene  # noqa: E402
from handcontrol.drawing_raster import InkRaster  # noqa: E402
from handcontrol.dryrun import FakeDisplays, FakeVolume, FakeWindows  # noqa: E402
from handcontrol.ui import UiBridge, UiState  # noqa: E402
from handcontrol.ui import drawing_view  # noqa: E402
from handcontrol.ui.main_window import MainWindow  # noqa: E402

from test_controls import frame, hand  # noqa: E402

R, L = (220.0, 260.0), (470.0, 300.0)
PEN, PALM, KNUCKLES = [1, 0, 0, 0], [1]*4, [0]*4


@pytest.fixture
def qt():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def clock(monkeypatch):
    c = SimpleNamespace(t=10_000.0)
    monkeypatch.setattr(drawing_view, "now_ms", lambda: c.t)
    return c


def drawing_rig() -> Rig:
    rig = Rig()
    rig.pipe.set_mode(Mode.DRAWING)
    rig.activate([raw_hand(POINT, R), raw_hand(POINT, L, side="left")])
    rig.sink.clear()
    return rig


def test_drawing_session_sends_no_os_input_and_never_opens_the_menu():
    rig = drawing_rig()
    for pose, left in ((POINT, OPEN), (OPEN, OPEN), (FIST, OPEN), (OPEN, FIST)):
        rig.run(1500, lambda u: [raw_hand(pose, (R[0] + 60*u, R[1])), raw_hand(left, L, side="left")])
        assert rig.ctl.snapshot().menu is None
    assert rig.mode is Mode.DRAWING and rig.state is ControlState.ACTIVE
    assert set(rig.sink.kinds()) <= {A.RELEASE_ALL}


def test_left_v_leaves_drawing_with_the_wheel():
    rig = drawing_rig()
    v = {**POINT, "middle": 0.0}
    rig.run(900, [raw_hand(POINT, R), raw_hand(v, L, side="left")])
    assert rig.ctl.snapshot().menu is not None
    up = (L[0], L[1] - 90)
    rig.run(250, [raw_hand(POINT, R), raw_hand(v, up, side="left")])
    rig.run(350, [raw_hand(POINT, R), raw_hand(FIST, up, side="left")])
    assert rig.mode is Mode.POINTER and rig.ctl.snapshot().menu is None
    assert set(rig.sink.kinds()) <= {A.RELEASE_ALL}


def test_held_x_without_visible_hands_neither_pauses_nor_claps():
    rig = drawing_rig()
    t0 = rig.t
    while rig.t < t0 + 3000:
        rig.frame([])
        rig.ctl.on_frame(PoseFrameFeatures(rig.t, rig.t, 640, 480, (), True, True), ())
    s = rig.ctl.snapshot()
    assert s.state is ControlState.ACTIVE and not s.clap_pending


def test_ink_is_bounded_and_revision_tracks_removals():
    s = InkScene()
    s.paint(-0.3, 0, 0)
    s.paint(0.3, 0, 1)
    assert s.revision == 0
    s.erase(0, 0.4)                       # nothing there
    assert s.revision == 0
    s.erase(0, 0)
    assert s.revision == 1
    for i in range(80):
        s.paint(0.4 * (-1) ** i, 0.1, i)
    assert len(s.dabs) <= MAX_DABS and s.revision > 1


# ---------------- view


class FakePipeline:
    def __init__(self):
        self.epoch, self.observers = 1, []
        self.controller = SimpleNamespace(current_epoch=lambda: self.epoch, config=SimpleNamespace(stale_ms=200.0))

    def add_frame_observer(self, fn):
        self.observers.append(fn)

    def queue(self, ff, mode=Mode.DRAWING, state=ControlState.ACTIVE, clap_pending=False):
        self.observers[0](ff, (), SimpleNamespace(mode=mode, state=state, camera_state=CameraState.RUNNING,
                                                  menu=None, clap_pending=clap_pending, epoch=self.epoch))

    def send(self, ff, **kw):
        self.queue(ff, **kw)
        QApplication.processEvents()


def ui_state(mode=Mode.DRAWING, control=ControlState.ACTIVE, **kw):
    return UiState(mode=mode, control_state=control, camera_state=CameraState.RUNNING, **kw)


@pytest.fixture
def view(qt, clock):
    v = drawing_view.DrawingView()
    v.resize(640, 480)
    v.pipe = FakePipeline()
    v.bind(v.pipe)
    v.set_state(ui_state(mirrored=False))
    image = QImage(64, 48, QImage.Format.Format_RGB32)
    image.fill(QColor("#ffffff"))
    v.set_camera_image(image)
    yield v
    v.hide()
    v.deleteLater()


def shot(v):
    out = QImage(v.size(), QImage.Format.Format_RGB32)
    v.render(out)
    return out


def strokes(v, clock, *hands):
    for _ in range(6):
        clock.t += 33
        v.pipe.send(frame(clock.t, *hands))


def dark(image, x, y):
    return image.pixelColor(x, y).lightness() < 90


def test_stroke_is_painted_at_the_fingertip_and_mirrored(view, clock):
    for i in range(14):
        clock.t += 33
        view.pipe.send(frame(clock.t, hand(Handedness.RIGHT, PEN, 360 + 10*i, 300)))
    view.controls.cursor = None
    for _ in range(2):                    # fresh dabs, then the cached layer
        assert dark(shot(view), 450, 300) and not dark(shot(view), 190, 300)
        clock.t += 1000
    assert view._baked == len(view.controls.scene.dabs)
    view.set_state(ui_state(mirrored=True))
    assert dark(shot(view), 190, 300) and not dark(shot(view), 450, 300)


def test_cached_layer_matches_full_repaint_after_spin_and_erase(view, clock):
    for i in range(12):
        clock.t += 33
        view.pipe.send(frame(clock.t, hand(Handedness.RIGHT, PEN, 380 + 12*i, 300), hand(Handedness.LEFT, PALM, 100, tilt=30)))
        shot(view)
    clock.t += 1000
    shot(view)
    n = len(view.controls.scene.dabs)
    strokes(view, clock, hand(Handedness.RIGHT, KNUCKLES, 500, 300))
    assert len(view.controls.scene.dabs) < n
    view.controls.cursor = None
    clock.t += 1000
    cached = shot(view)
    view._layer_key = None
    assert shot(view) == cached


def test_clear_flows_away_and_canvas_is_reusable(view, clock):
    strokes(view, clock, hand(Handedness.RIGHT, PEN, 400, 100))
    for _ in range(12):
        clock.t += 60
        view.pipe.send(frame(clock.t, crossed=True))
    assert view.controls.scene.clear_start is not None
    shot(view)
    clock.t += drawing_view.CLEAR_MS + 50
    view._animate()
    assert not view.controls.scene.dabs and not dark(shot(view), 400, 100)
    strokes(view, clock, hand(Handedness.RIGHT, PEN, 400, 100))
    assert view.controls.scene.dabs


def test_pause_stale_epoch_and_other_modes_never_paint_but_keep_ink(view, clock):
    pen = hand(Handedness.RIGHT, PEN, 400, 100)
    far = replace(pen, index_tip_px=(420, 100))
    strokes(view, clock, pen)
    ink = view.controls.scene.dabs.copy()
    clock.t += 33
    view.pipe.send(frame(clock.t, far), state=ControlState.PAUSED)
    view.pipe.send(frame(clock.t, far), mode=Mode.POINTER)
    view.pipe.send(frame(clock.t, far), clap_pending=True)
    view.pipe.send(frame(clock.t - 500, far))
    view.pipe.queue(frame(clock.t, far))
    view.pipe.epoch = 2                   # the queued sample belongs to an older epoch
    QApplication.processEvents()
    assert view.controls.scene.dabs == ink
    strokes(view, clock, far)             # new epoch: a separate stroke, no bridge to the old one
    new = view.controls.scene.dabs[len(ink):]
    assert new and new[0].radius > 0.009
    view.set_state(ui_state(control=ControlState.PAUSED))
    assert view.controls.cursor is None and view.controls.scene.dabs


def test_x_survives_clap_candidates_and_epoch_bumps(view, clock):
    strokes(view, clock, hand(Handedness.RIGHT, PEN, 400, 100))
    for i in range(24):
        clock.t += 33
        view.pipe.epoch += i % 4 == 0
        view.pipe.send(frame(clock.t, crossed=i % 5 != 4), clap_pending=i % 3 == 0)
    assert view.controls.scene.clear_start is not None


def test_moving_scene_uses_the_fast_picture_and_sharpens_at_rest(view, clock, monkeypatch):
    s = view.controls.scene
    for i in range(220):
        s.angle = i * .1
        s.paint(0.2, -0.2 + i/700, 0)
    calls = []
    render = InkRaster.render
    monkeypatch.setattr(InkRaster, "render", lambda self, *a: calls.append(1) or render(self, *a))
    s.angle += .01
    fast = shot(view)
    assert calls and view._dirty                 # asks for the sharp repaint
    n = len(calls)
    sharp = shot(view)
    assert len(calls) == n
    pts = [(x, y) for x in range(0, 640, 8) for y in range(40, 480, 8)]
    assert sum(dark(fast, *p) != dark(sharp, *p) for p in pts) < 0.02*len(pts)


def test_colors_reach_both_painters_and_newer_ink_covers_older(view, clock):
    s = view.controls.scene
    for color in (2, 6):                                    # red, then blue over it on the same plane
        s.color = color
        s.lift()
        s.paint(0.0, 0.1, 0)
        s.paint(0.2, 0.1, 0)
    sharp = shot(view).pixelColor(380, 304)
    buf = InkRaster().render(s, 640, 480, 1000, 165)
    fast = QColor(int(buf[304, 380]) & 0xffffff)
    for c in (sharp, fast):
        assert c.blue() > 150 and c.red() < 90
    assert abs(sharp.blue() - fast.blue()) < 12


def test_palette_is_drawn_and_named(view, clock):
    ok = replace(hand(Handedness.RIGHT, [0, 1, 1, 1], 320, 240), pinch_distance=.1)
    for _ in range(10):
        clock.t += 33
        view.pipe.send(frame(clock.t, ok))
    assert view.controls.palette is not None
    wheel = shot(view)
    assert wheel.pixelColor(320 + 70, 240).saturation() > 100     # slice 2 of 8 = red on the +x side
    view.controls.palette = None
    assert shot(view).pixelColor(320 + 70, 240).saturation() < 20


def test_clear_button_flows_the_ink_away(view, clock):
    strokes(view, clock, hand(Handedness.RIGHT, PEN, 400, 100))
    view.clear()
    start = view.controls.scene.clear_start
    for part in (.1, .5, .9):
        clock.t = start + part*drawing_view.CLEAR_MS
        shot(view)
    clock.t += 1000
    view._animate()
    assert not view.controls.scene.dabs


def test_missing_pose_model_is_shown(view, clock):
    view.pipe.send(FrameFeatures(clock.t, clock.t, 640, 480, (), False))
    assert view._pose_available is False
    clock.t += 33
    view.pipe.send(frame(clock.t))
    assert view._pose_available is True


# ---------------- window and runtime


def test_drawing_is_a_page_of_the_main_window(qt):
    win = MainWindow(UiBridge(), live=True)
    win.apply_state(ui_state(Mode.POINTER))
    win.apply_state(ui_state())
    assert win.stack.currentWidget() is win.drawing and win.instrument_bar.isHidden()
    assert win.mode_buttons[Mode.DRAWING].isChecked() and win.hint.text().startswith(drawing_view.DRAWING_HINT_TR)
    assert not win.ink_clear_button.isHidden()
    win.apply_state(ui_state(Mode.INSTRUMENT))
    assert win.stack.currentWidget() is win.instrument and win.ink_clear_button.isHidden()
    win.close()


def test_choosing_drawing_starts_it(qt, monkeypatch):
    monkeypatch.setattr(app_module, "read_os_cursor", lambda **_: None)
    assert set(MODES) == {m.value for m in Mode}
    displays = FakeDisplays()
    displays.start, displays.close = Mock(), Mock()
    rt = Runtime(UiBridge(), SimpleNamespace(load=lambda: Settings(), save=Mock()), displays=displays,
                 windows=FakeWindows(), volume=FakeVolume(), session_factory=Mock(),
                 instrument_factory=lambda rt: None)
    rt.pipeline.set_camera_state(CameraState.RUNNING)
    rt.select_mode(Mode.DRAWING)
    snap = rt.pipeline.controller.snapshot()
    assert snap.mode is Mode.DRAWING and snap.state is ControlState.ACTIVE


def test_brush_signal_tells_color_and_use(view, clock):
    seen = []
    view.brush_changed.connect(lambda color, on: seen.append((color, on)))
    strokes(view, clock, hand(Handedness.RIGHT, PEN))
    assert seen[-1] == (drawing_view.PALETTE[0][1], True) and seen.count(seen[-1]) == 1
    view.controls.scene.color = 2
    strokes(view, clock, hand(Handedness.RIGHT, PEN))
    assert seen[-1] == (drawing_view.PALETTE[2][1], True)
    view.set_state(ui_state(control=ControlState.PAUSED))
    assert seen[-1] == (drawing_view.PALETTE[2][1], False)
