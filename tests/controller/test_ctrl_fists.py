from __future__ import annotations

from dataclasses import replace

import pytest

from ctrl_helpers import Rig, hand, RIGHT, LEFT, WIN_A, WIN_B, K
from handcontrol.contracts import FingerInfo, FingerState, Mode, Quality, Rect


def fist(hid=RIGHT):
    opened = hand(hid)
    return replace(opened, fingers=tuple(FingerInfo(f.name, FingerState.BENT, 0.9) for f in opened.fingers))


def arm(r, hid):
    for _ in range(8):
        r.frame(hand(hid))


def hold(r, hid=RIGHT, frames=13):
    for _ in range(frames):
        r.frame(fist(hid))


# INSTRUMENT sends no OS input at all (fists included): covered by test_ctrl_instrument.py
@pytest.mark.parametrize('mode', [m for m in Mode if m is not Mode.INSTRUMENT])
def test_right_minimizes_once_and_left_restores_same_target(mode):
    r = Rig()
    r.ctl.set_mode(mode)
    arm(r, RIGHT)
    hold(r, RIGHT, 30)
    assert r.count(K.WINDOW_MINIMIZE) == 1
    assert r.sink.of(K.WINDOW_MINIMIZE)[0].target == WIN_A
    arm(r, LEFT)
    hold(r, LEFT, 30)
    assert r.count(K.WINDOW_RESTORE) == 1
    assert r.sink.of(K.WINDOW_RESTORE)[0].target == WIN_A
    assert not r.count(K.LEFT_CLICK)


def test_short_fist_and_closed_start_do_not_fire():
    r = Rig()
    hold(r, frames=20)
    assert r.count(K.WINDOW_MINIMIZE) == 0
    arm(r, RIGHT)
    hold(r, frames=5)
    r.frame(hand())
    assert r.count(K.WINDOW_MINIMIZE) == 0


def test_new_open_release_required_for_each_minimize():
    r = Rig()
    arm(r, RIGHT)
    hold(r)
    arm(r, RIGHT)
    hold(r)
    assert r.count(K.WINDOW_MINIMIZE) == 2


def test_foreground_change_during_hold_does_not_redirect():
    r = Rig()
    arm(r, RIGHT)
    hold(r, frames=3)
    r.windows.add(WIN_B, Rect(-1000, -1000, 1000, 1000))
    r.windows.foreground = WIN_B
    hold(r)
    assert r.count(K.WINDOW_MINIMIZE) == 0


def test_destroyed_history_does_not_restore_foreground():
    r = Rig()
    arm(r, RIGHT)
    hold(r)
    r.windows.remove(WIN_A)
    arm(r, LEFT)
    hold(r, LEFT)
    assert r.count(K.WINDOW_RESTORE) == 0


@pytest.mark.parametrize('failure', ['pause', 'loss', 'stale', 'ambiguous', 'quality'])
def test_unsafe_frames_cancel_hold(failure):
    r = Rig()
    arm(r, RIGHT)
    hold(r, frames=3)
    if failure == 'pause':
        r.ctl.pause()
    elif failure == 'loss':
        r.frame()
    elif failure == 'stale':
        r.frame(fist(), latency=151)
    elif failure == 'ambiguous':
        r.frame(fist(), ambiguous=True)
    else:
        r.frame(replace(fist(), quality=Quality.UNKNOWN))
    hold(r)
    assert r.count(K.WINDOW_MINIMIZE) == 0


def test_both_fists_cancel_and_empty_restore_is_harmless():
    r = Rig()
    arm(r, LEFT)
    hold(r, LEFT)
    assert r.count(K.WINDOW_RESTORE) == 0
    arm(r, RIGHT)
    for _ in range(20):
        r.frame(fist(RIGHT), fist(LEFT))
    hold(r)
    assert r.count(K.WINDOW_MINIMIZE) == 0


def test_failed_minimize_is_not_added_to_history():
    r = Rig()
    arm(r, RIGHT)
    r.sink.accept = False
    hold(r)
    r.sink.accept = True
    arm(r, LEFT)
    hold(r, LEFT)
    assert r.count(K.WINDOW_RESTORE) == 0
