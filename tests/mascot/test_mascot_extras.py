"""Music notes around the cat and the paint brush in its paw."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import random
import time

import numpy as np
import pytest
from PySide6.QtCore import QPoint
from PySide6.QtGui import QImage
from test_mascot import BODY, FakeBridge, FakePerception, FakeWindow, app, rig, state  # noqa: F401

from handcontrol.contracts import CameraState, ControlState, Mode
from handcontrol.mascot.notes import MOST, NoteCloud
from handcontrol.mascot.renderer import Brush, CatRenderer, RendererError
from handcontrol.mascot.retarget import HandInfo, Retargeter
from handcontrol.mascot.rig import ARMS, MascotPose, PawTarget, apply
from handcontrol.mascot.window import Mascot, MascotWindow

RED, BLUE = (226, 44, 48), (40, 110, 230)
DRAWING = MascotPose(paws=(PawTarget(), PawTarget(.4, .6, .7, 0.0, 1.0, .5)), present=1.0)


# ---------- notes

def test_notes_trickle_while_playing_and_finish_afterwards(app):  # noqa: F811
    cloud, t = NoteCloud(random.Random(1)), 0.0
    assert not cloud.step(t)
    cloud.set_playing(True)
    for _ in range(150):
        t += 0.033
        cloud.step(t)
    assert 2 <= len(cloud.notes) <= 8
    cloud.set_playing(False)
    assert cloud.step(t) and not cloud.step(t + 3.0)


def test_plucked_strings_add_notes_but_never_too_many(app):  # noqa: F811
    cloud = NoteCloud(random.Random(2))
    cloud.pluck(0.0)
    assert not cloud.notes                                 # not playing
    cloud.set_playing(True)
    for _ in range(6):
        cloud.pluck(0.0)                                   # one strummed chord
    assert len(cloud.notes) == 1
    for i in range(200):
        cloud.pluck(0.1 + i * 0.06)
    assert len(cloud.notes) == MOST


def test_notes_start_behind_the_cat_rise_outwards_and_stay_in_the_window(app):  # noqa: F811
    cloud = NoteCloud(random.Random(3))
    cloud.set_playing(True)
    for i in range(MOST):
        cloud.pluck(i)
    for n in cloud.notes:
        x0, y0, a0, _ = n.at(n.born)
        x1, y1, a1, _ = n.at(n.born + n.life)
        assert a0 == 0 and a1 == pytest.approx(0) and n.at(n.born + n.life / 3)[2] == 1
        assert 0.25 < x0 < 0.75 and abs(x1 - 0.5) > abs(x0 - 0.5) and y1 < y0
        assert 0 < x1 < 1 and y1 > 0.08
    assert {n.side for n in cloud.notes} == {-1, 1}


# ---------- which mode drives what

def test_only_running_instrument_mode_plays(app):  # noqa: F811
    bridge, window = FakeBridge(), FakeWindow()
    cat = Mascot(bridge, window=window, perception=FakePerception())
    active = ControlState.ACTIVE
    for s, wanted in ((state(mode=Mode.INSTRUMENT, control=active), True), (state(mode=Mode.INSTRUMENT), False),
                      (state(mode=Mode.DRAWING, control=active), False),
                      (state(mode=Mode.INSTRUMENT, control=active), True),
                      (state(camera=CameraState.OFF, mode=Mode.INSTRUMENT, control=active), False)):
        bridge.state_changed.emit(s)
        assert window.playing is wanted
    cat.close()


def test_right_hand_decides_the_paw_with_the_brush():
    r = Retargeter()
    r.set_body(BODY, 0.0)
    r.set_hands([HandInfo((1.4, 0.3), 0, 0, True), HandInfo((0.4, 0.3), 0, 0)], 0.0)
    r.pose(0.01)
    assert r.right_side == 1
    r.set_hands([HandInfo((0.4, 0.3), 0, 0, True), HandInfo((1.4, 0.3), 0, 0)], 0.1)      # crossed over
    r.pose(0.11)
    assert r.right_side == 0
    r.set_hands([HandInfo((1.4, 0.3), 0, 0)], 0.2)
    r.pose(0.21)
    assert r.right_side == 0                               # unknown: keep


class Recorder:
    def __init__(self):
        self.brushes = []

    def render(self, *a, brush=None, **k):
        self.brushes.append(brush)
        return QImage()

    def close(self):
        pass


@pytest.fixture
def window(app, monkeypatch):  # noqa: F811
    now = [100.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    recorder = Recorder()
    w = MascotWindow(lambda t: DRAWING, renderer_factory=lambda: recorder, cursor=lambda: QPoint(0, 0))
    w.set_visible(True)
    w._timer.stop()

    def run(seconds):
        for _ in range(round(seconds / 0.033)):
            now[0] += 0.033
            w._tick()
        return recorder.brushes[-1]
    w.run = run
    yield w
    w.close_renderer()


def test_brush_appears_while_drawing_follows_the_color_and_goes_away(window):
    assert window.run(0.5) is None
    window.set_brush(RED, True)
    b = window.run(0.8)
    assert b.side == 1 and b.size > 0.95 and b.color == pytest.approx(RED, abs=1)
    window.set_brush(BLUE, True)
    assert window.run(0.8).color == pytest.approx(BLUE, abs=1)
    window.set_brush(BLUE, False)
    assert window.run(0.8).size > 0.95                     # between two strokes
    assert window.run(2.0) is None


def test_color_picked_after_the_stroke_is_still_shown(window):
    window.set_brush(RED, True)
    window.run(0.8)
    window.set_brush(BLUE, False)                          # the wheel closes with the pick
    assert window.run(0.6).color == pytest.approx(BLUE, abs=3)


def test_no_brush_in_a_resting_paw(window):
    window._source = lambda t: MascotPose()
    window.set_brush(RED, True)
    assert window.run(1.0) is None


def test_hiding_the_cat_drops_brush_and_notes(window):
    window.set_playing(True)
    window.set_brush(RED, True)
    window.run(1.0)
    assert window._notes.notes
    window.set_visible(False)
    assert not window._notes.notes and window._brush_size == 0


# ---------- geometry and one real frame

def test_hand_frame_sits_at_the_wrist_and_points_along_the_toes(rig):  # noqa: F811
    skin = rig.solve(DRAWING, 0.0)
    m = rig.hand(skin, 1)
    assert m[:3, 3] == pytest.approx(apply(skin[ARMS[1][2]], rig.arm_rest[1][2]))
    assert m[:3, :3] @ m[:3, :3].T == pytest.approx(np.eye(3), abs=1e-6)
    assert m[1, 2] > 0.3 and m[2, 1] < 0                   # toes up, pads (-Y) towards the viewer


def test_brush_is_drawn_in_its_color(app):  # noqa: F811
    try:
        r = CatRenderer()
    except RendererError as exc:
        pytest.skip(f"no OpenGL here: {exc}")

    def pixels(brush):
        img = r.render(DRAWING, 0.0, 380, 342, wait=True, brush=brush)
        raw = np.frombuffer(img.constBits(), np.uint8).reshape(342, 380, 4).astype(int)
        return raw[..., 2], raw[..., 1], raw[..., 0]
    try:
        for brush, strong, weak in ((None, 0, 2), (Brush(1, RED), 0, 2), (Brush(1, BLUE), 2, 0)):
            c = pixels(brush)
            colored = int(((c[strong] > 120) & (c[strong] > 2 * c[weak]) & (c[strong] > 1.6 * c[1])).sum())
            assert colored == 0 if brush is None else colored > 150
    finally:
        r.close()
