"""Relative pointer (default settings) and the click fixes through the real chain at 30 and 10 FPS.
Proves logic only, never real-camera behavior."""
from __future__ import annotations

import pytest

from handcontrol.config import Settings
from handcontrol.contracts import ActionKind as A
from handcontrol.dryrun import make_monitor
from handcontrol.pipeline import controller_config

from integ_synth import OPEN, PINCH, POINT, Rig, hand, lerp

FPS = pytest.mark.parametrize("fps", [30.0, 10.0], ids=["30fps", "10fps"])
TWO = [make_monitor(0, 0, 1920, 1080, primary=True), make_monitor(1920, 0, 1920, 1080)]
PINCH3 = {"thumb": 0.5, "index": 0.65, "middle": 1.0, "ring": 1.0, "little": 1.0}   # pinch, three fingers curled
CLICKS = (A.LEFT_CLICK, A.RIGHT_CLICK, A.LEFT_DOWN, A.DOUBLE_CLICK)


def _h(pose, x: float, y: float = 300.0):
    return [hand(pose, (x, y))]


def _mix(a, b, u: float):
    return {k: lerp(a[k], b[k], u) for k in a}


def _swipe(rig: Rig, x_from: float, x_to: float) -> None:
    """Brisk pointing stroke, clutch with an open hand, return with the hand open."""
    rig.run(200, lambda u: _h(POINT, lerp(x_from, x_to, u)))
    rig.run(250, _h(OPEN, x_to))
    rig.run(300, lambda u: _h(OPEN, lerp(x_to, x_from, u)))
    rig.run(300, _h(POINT, x_from))


def test_settings_reach_the_controller():
    s = Settings()
    c = controller_config(s)
    assert c.pointer_relative is True and c.pointer_speed == 1.0 and c.monitor_mode == "virtual_desktop"
    assert (c.right_pinch_on_pu, c.right_pinch_off_pu) == (s.pinch_on_threshold, s.pinch_off_threshold)
    s.pointer_speed, s.pointer_mode = 1.7, "absolute"
    c = controller_config(s)
    assert c.pointer_speed == 1.7 and c.pointer_relative is False


@FPS
def test_pointing_moves_open_hand_clutches_and_reengage_does_not_jump(fps):
    rig = Rig(fps=fps)
    rig.activate(_h(POINT, 300))
    rig.run(300, _h(POINT, 300))
    start = rig.ctl.snapshot().pointer
    assert start == (960, 540) and rig.count(A.MOVE_POINTER) == 0          # primary centre, still hand
    rig.run(400, lambda u: _h(POINT, lerp(300, 260, u)))
    p = rig.ctl.snapshot().pointer
    assert p[0] > start[0]                                                 # mirrored: hand left -> cursor right
    rig.run(300, _h(OPEN, 260))
    p = rig.ctl.snapshot().pointer
    n = rig.count(A.MOVE_POINTER)
    rig.run(400, lambda u: _h(OPEN, lerp(260, 380, u), lerp(300, 250, u)))  # clutched: free travel back
    rig.run(400, _h(POINT, 380, 250))                                      # re-engage still
    assert rig.ctl.snapshot().pointer == p and rig.count(A.MOVE_POINTER) == n
    rig.run(400, lambda u: _h(POINT, lerp(380, 340, u), 250))
    assert rig.ctl.snapshot().pointer[0] > p[0]
    assert all(rig.count(k) == 0 for k in CLICKS)


@FPS
def test_default_settings_cross_to_the_second_monitor(fps):
    rig = Rig(fps=fps, monitors=TWO)
    rig.activate(_h(POINT, 400))
    rig.run(300, _h(POINT, 400))
    _swipe(rig, 400, 240)
    assert rig.ctl.snapshot().pointer[0] >= 1920
    _swipe(rig, 400, 240)
    assert rig.ctl.snapshot().pointer[0] > 3000
    assert all(rig.count(k) == 0 for k in CLICKS)


@FPS
def test_pinch_with_three_fingers_curled_clicks_once_and_never_minimizes(fps):
    rig = Rig(fps=fps)
    rig.activate(_h(OPEN, 300))
    rig.run(400, _h(OPEN, 300))                                            # arms the fist gesture
    aim = rig.ctl.snapshot().pointer
    rig.run(100, lambda u: _h(_mix(OPEN, PINCH3, u), 300))
    rig.run(250, _h(PINCH3, 300))                                          # all five read BENT
    rig.run(100, lambda u: _h(_mix(PINCH3, OPEN, u), 300))
    rig.run(400, _h(OPEN, 300))
    clicks = rig.sink.of(A.LEFT_CLICK)
    assert len(clicks) == 1 and (clicks[0].x, clicks[0].y) == aim
    assert rig.count(A.WINDOW_MINIMIZE) == 0 and rig.count(A.LEFT_DOWN) == 0


@FPS
def test_pinch_threshold_flicker_gives_exactly_one_click(fps):
    rig = Rig(fps=fps)
    rig.activate(_h(POINT, 250))
    rig.run(300, _h(POINT, 250))
    flicker = _mix(PINCH, OPEN, 0.38)                                      # thumb-index ~0.52 palm units
    rig.run(150, _h(PINCH, 250)).run(200, _h(flicker, 250)).run(150, _h(PINCH, 250)).run(400, _h(POINT, 250))
    assert rig.count(A.LEFT_CLICK) == 1 and rig.count(A.LEFT_DOWN) == 0


@FPS
def test_slow_pinch_under_the_hold_time_still_clicks(fps):
    rig = Rig(fps=fps)
    rig.activate(_h(POINT, 250))
    rig.run(300, _h(POINT, 250))
    rig.run(380, _h(PINCH, 250)).run(400, _h(POINT, 250))
    assert rig.count(A.LEFT_CLICK) == 1 and rig.count(A.LEFT_DOWN) == 0


@FPS
def test_drag_moves_the_cursor_with_the_hand(fps):
    rig = Rig(fps=fps)
    rig.activate(_h(POINT, 300))
    rig.run(300, _h(POINT, 300))
    aim = rig.ctl.snapshot().pointer
    rig.run(700, _h(PINCH, 300))
    assert rig.count(A.LEFT_DOWN) == 1
    rig.run(400, lambda u: _h(PINCH, lerp(300, 240, u)))
    rig.run(300, _h(POINT, 240))
    moves = rig.sink.of(A.MOVE_POINTER)
    up = rig.sink.of(A.LEFT_UP)
    assert moves and moves[-1].x > aim[0] + 100 and len(up) == 1 and (up[0].x, up[0].y) == (moves[-1].x, moves[-1].y)


def test_cursor_source_gives_the_start_position():
    rig = Rig(monitors=TWO, cursor_source=lambda: (2500, 300))
    rig.activate(_h(POINT, 300))
    rig.run(300, _h(POINT, 300))
    assert rig.ctl.snapshot().pointer == (2500, 300)
