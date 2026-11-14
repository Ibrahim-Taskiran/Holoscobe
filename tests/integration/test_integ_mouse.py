"""Pinch mouse (default POINTER config) through the real chain at 30 and 10 FPS.
Proves logic only, never real-camera behavior."""
from __future__ import annotations

from dataclasses import replace

import pytest

from handcontrol.contracts import ActionKind as A, Landmark
from handcontrol.controller import MenuKind

from integ_synth import DOM_C, FIST, OPEN, PINCH, POINT, Rig, clap, hand, lerp

FPS = pytest.mark.parametrize("fps", [30.0, 10.0], ids=["30fps", "10fps"])
# thumb tip on the middle tip, index ring and little extended (thumb-middle ~0.04 pu, thumb-index ~1 pu)
RIGHT_PINCH = {"thumb": 0.75, "index": 0.0, "middle": 0.85, "ring": 0.0, "little": 0.0}
CLICKS = (A.LEFT_CLICK, A.RIGHT_CLICK, A.LEFT_DOWN, A.DOUBLE_CLICK)


def _r(pose=POINT, x: float = 250.0):
    return [hand(pose, (x, 300.0))]


def _no_clicks(rig: Rig) -> bool:
    return all(rig.count(k) == 0 for k in CLICKS)


@FPS
def test_tap_clicks_once_at_the_point_before_the_pinch(fps):
    """The fingertip travels while the pinch closes; the click lands where the hand was open."""
    rig = Rig(fps=fps)
    rig.activate(_r())
    aim = rig.ctl.snapshot().pointer
    rig.run(150, _r(PINCH)).run(400, _r())
    clicks = rig.sink.of(A.LEFT_CLICK)
    assert len(clicks) == 1 and rig.count(A.LEFT_DOWN) == 0
    assert (clicks[0].x, clicks[0].y) == aim


@FPS
def test_double_tap_clicks_twice_at_one_point(fps):
    rig = Rig(fps=fps)
    rig.activate(_r())
    step = 200.0 if fps < 20 else 120.0
    rig.run(step, _r(PINCH)).run(step, _r()).run(step, _r(PINCH)).run(400, _r())
    clicks = rig.sink.of(A.LEFT_CLICK)
    assert len(clicks) == 2
    assert (clicks[0].x, clicks[0].y) == (clicks[1].x, clicks[1].y)
    assert clicks[1].capture_ms - clicks[0].capture_ms < 500       # inside the Windows double-click time
    assert rig.count(A.LEFT_DOWN) == 0


@FPS
def test_pinch_and_move_drags_with_the_left_button(fps):
    # Round 6: a still 700 ms pinch no longer presses the button; palm travel starts the drag.
    rig = Rig(fps=fps)
    rig.activate(_r())
    aim = rig.ctl.snapshot().pointer
    rig.run(700, _r(PINCH))
    assert rig.count(A.LEFT_DOWN) == 0 and rig.count(A.MOVE_POINTER) == 0   # still hand: no press, no creep
    rig.run(900, lambda u: [hand(PINCH, (lerp(250, 340, u), 300.0))])
    assert rig.count(A.LEFT_DOWN) == 1 and rig.count(A.LEFT_UP) == 0
    down = rig.sink.of(A.LEFT_DOWN)[0]
    assert (down.x, down.y) == aim
    rig.run(300, _r(POINT, 340))
    ks = rig.kinds()
    i, j = ks.index(A.LEFT_DOWN), ks.index(A.LEFT_UP)
    moves = [a for a in rig.sink.actions[i:j] if a.kind is A.MOVE_POINTER]
    assert len(moves) >= 3 and moves[-1].x < down.x          # mirrored: hand right -> pointer left
    up = rig.sink.of(A.LEFT_UP)[0]
    assert (up.x, up.y) == (moves[-1].x, moves[-1].y)
    assert rig.count(A.LEFT_CLICK) == 0 and rig.count(A.LEFT_UP) == 1


@FPS
def test_hand_leaving_mid_drag_releases_the_button(fps):
    rig = Rig(fps=fps)
    rig.activate(_r())
    rig.run(200, _r(PINCH))
    rig.run(500, lambda u: [hand(PINCH, (lerp(250, 410, u), 300.0))])   # round 6: travel starts the drag
    assert rig.count(A.LEFT_DOWN) == 1
    rig.run(300, [])
    ks = rig.kinds(skip_release=False)
    assert A.LEFT_UP in ks[ks.index(A.LEFT_DOWN):]
    rig.run(300, _r(PINCH)).run(300, _r())                         # re-enters pinched: nothing
    assert rig.count(A.LEFT_DOWN) == 1 and rig.count(A.LEFT_CLICK) == 0


@FPS
def test_thumb_middle_tap_right_clicks(fps):
    rig = Rig(fps=fps)
    rig.activate(_r(OPEN))
    aim = rig.ctl.snapshot().pointer
    rig.run(150, _r(RIGHT_PINCH)).run(400, _r(OPEN))
    clicks = rig.sink.of(A.RIGHT_CLICK)
    assert len(clicks) == 1 and rig.count(A.LEFT_CLICK) == 0 and rig.count(A.LEFT_DOWN) == 0
    assert (clicks[0].x, clicks[0].y) == aim


@FPS
def test_long_thumb_middle_hold_does_not_right_click(fps):
    rig = Rig(fps=fps)
    rig.activate(_r(OPEN))
    rig.run(3300, _r(RIGHT_PINCH)).run(400, _r(OPEN))      # round 6: limit 3000 ms (was 480 ms)
    assert _no_clicks(rig)


@FPS
def test_pointing_pose_never_right_clicks(fps):
    """Pointing tucks the thumb over the curled middle finger (thumb-middle ~0.2 pu)."""
    rig = Rig(fps=fps)
    rig.activate(_r(OPEN))
    for ms in (150, 250, 1000):
        rig.run(ms, _r(POINT)).run(300, _r(OPEN))
    rig.run(300, lambda u: _r({k: lerp(OPEN[k], POINT[k], u) for k in OPEN}))
    assert _no_clicks(rig)


@FPS
def test_fist_minimizes_without_clicking(fps):
    rig = Rig(fps=fps)
    rig.activate(_r(OPEN))
    rig.run(150, lambda u: _r({k: lerp(OPEN[k], FIST[k], u) for k in OPEN}))
    rig.run(600, _r(FIST))
    rig.run(150, lambda u: _r({k: lerp(FIST[k], OPEN[k], u) for k in OPEN}))
    rig.run(300, _r(OPEN))
    assert rig.count(A.WINDOW_MINIMIZE) == 1
    assert _no_clicks(rig)


def test_left_fist_and_left_pinch_never_click():
    rig = Rig()
    left = (450.0, 300.0)
    rig.activate([hand(POINT, DOM_C), hand(OPEN, left, side="left")])
    rig.run(150, [hand(POINT, DOM_C), hand(PINCH, left, side="left")])
    rig.run(300, [hand(POINT, DOM_C), hand(OPEN, left, side="left")])
    rig.run(600, [hand(POINT, DOM_C), hand(FIST, left, side="left")])
    rig.run(300, [hand(POINT, DOM_C), hand(OPEN, left, side="left")])
    assert _no_clicks(rig)


def test_clap_never_clicks(rig):
    rig.activate(_r())
    clap(rig)
    assert _no_clicks(rig)


def test_menu_dwell_then_pinch_selects_without_clicking(rig):
    rig.activate([hand(POINT, DOM_C), hand(POINT, (440, 300), side="left")])
    rig.run(1000, [hand(POINT, DOM_C), hand(OPEN, (440, 300), side="left")])
    m = rig.ctl.snapshot().menu
    assert m is not None and m.kind is MenuKind.MODE
    rig.run(150, [hand(PINCH, DOM_C)]).run(300, [hand(POINT, DOM_C)])
    assert _no_clicks(rig)


def test_hand_entering_pinched_does_not_click(rig):
    rig.activate(_r())
    rig.run(300, [])
    rig.run(150, _r(PINCH)).run(300, _r())
    rig.run(150, _r(RIGHT_PINCH)).run(300, _r(OPEN))
    assert rig.count(A.LEFT_CLICK) == 0 and rig.count(A.RIGHT_CLICK) == 0


def test_index_depth_tap_is_off_by_default(rig):
    rig.activate(_r())
    rig.run(500, _r())
    for depth in (0.14, 0.26, 0.38, 0.32, 0.17, 0.03):
        h = hand(POINT, (250, 300))
        points = list(h.landmarks)
        for index in (6, 7, 8):
            old = points[index]
            points[index] = Landmark(old.x, old.y, old.z - depth * 100 / 640 * (index - 5) / 3)
        rig.frame([replace(h, landmarks=tuple(points))])
    rig.run(300, _r())
    assert _no_clicks(rig)
