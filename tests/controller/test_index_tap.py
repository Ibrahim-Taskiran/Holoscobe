from __future__ import annotations

from dataclasses import replace
import pytest
from ctrl_helpers import Rig, hand, RIGHT, LEFT, K, tcfg
from handcontrol.contracts import FingerInfo, FingerName, FingerState, Landmark


def pointing(depth=0.0, hid=RIGHT, palm=(320.0, 300.0)):
    h = hand(hid, palm=palm)
    fingers = tuple(FingerInfo(f, FingerState.EXTENDED if f is FingerName.INDEX else FingerState.BENT, 0 if f is FingerName.INDEX else 1) for f in FingerName)
    landmarks = list(h.landmarks)
    landmarks[8] = Landmark(0.5, 0.4, -depth * h.palm_scale_px / 640)
    return replace(h, fingers=fingers, landmarks=tuple(landmarks))


def rig():
    r = Rig(cfg=tcfg(index_tap_click=True))
    r.settle(pointing())
    for _ in range(8): r.frame(pointing())
    r.sink.clear()
    return r


def pulse(r, hid=RIGHT):
    for d in (0.14, 0.26, 0.38, 0.32, 0.17, 0.03):
        r.frame(pointing(d, hid))


def test_tap_clicks_once_at_frozen_pointer():
    r = rig()
    pointer = r.ctl.snapshot().pointer
    pulse(r)
    assert r.count(K.LEFT_CLICK) == 1
    click = r.sink.of(K.LEFT_CLICK)[0]
    assert (click.x, click.y) == pointer
    assert r.count(K.MOVE_POINTER) == 0
    for _ in range(20): r.frame(pointing())
    assert r.count(K.LEFT_CLICK) == 1


@pytest.mark.parametrize('values', [(0.04, 0.08, 0.06, 0), (0.2, 0.38, 0.4, 0.4)])
def test_jitter_or_no_return_does_not_click(values):
    r = rig()
    for d in values: r.frame(pointing(d))
    assert r.count(K.LEFT_CLICK) == 0


def test_slow_return_does_not_click():
    r = rig()
    r.frame(pointing(0.2))
    for _ in range(18): r.frame(pointing(0.38))
    r.frame(pointing())
    assert r.count(K.LEFT_CLICK) == 0


def test_left_hand_never_moves_or_clicks_even_with_left_dominance():
    from handcontrol.contracts import Handedness
    r = Rig(cfg=tcfg(index_tap_click=True, dominant=Handedness.LEFT))
    for _ in range(20): r.frame(pointing(hid=LEFT))
    pulse(r, LEFT)
    assert not r.count(K.MOVE_POINTER) and not r.count(K.LEFT_CLICK)


@pytest.mark.parametrize('failure', ['loss', 'pause', 'stale', 'ambiguous', 'pose'])
def test_interruption_cancels_tap(failure):
    r = rig()
    r.frame(pointing(0.2))
    r.frame(pointing(0.4))
    if failure == 'loss': r.frame()
    elif failure == 'pause': r.ctl.pause()
    elif failure == 'stale': r.frame(pointing(0.3), latency=151)
    elif failure == 'ambiguous': r.frame(pointing(0.3), ambiguous=True)
    else: r.frame(hand())
    r.frame(pointing())
    assert r.count(K.LEFT_CLICK) == 0


def test_palm_motion_cancels_tap():
    r = rig()
    r.frame(pointing(0.2))
    r.frame(pointing(0.4, palm=(350, 300)))
    r.frame(pointing())
    assert r.count(K.LEFT_CLICK) == 0


def test_pinch_no_longer_clicks_by_default():
    from ctrl_helpers import G
    r = rig()
    r.frame(hand(), events=[(G.PINCH_START, RIGHT)])
    r.frame(hand(), events=[(G.PINCH_END, RIGHT)])
    assert r.count(K.LEFT_CLICK) == 0


@pytest.mark.parametrize('dt', [33.4, 100])
def test_tap_timing_and_rearm_at_camera_rates(dt):
    r = rig()
    for depth in (0.2, 0.38, 0):
        r.frame(pointing(depth), dt=dt)
    assert r.count(K.LEFT_CLICK) == 1
    for _ in range(round(900 / dt)):
        r.frame(pointing(), dt=dt)
    for depth in (0.2, 0.38, 0):
        r.frame(pointing(depth), dt=dt)
    assert r.count(K.LEFT_CLICK) == 2
