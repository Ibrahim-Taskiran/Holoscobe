"""Mode wheel: one-hand aiming, fist to pick, cancel paths, and its place in the controller."""
from __future__ import annotations

import math
from dataclasses import replace

import pytest
from ctrl_helpers import G, K, LEFT, RIGHT, Rig, hand, posed

from handcontrol.contracts import FingerState, Mode
from handcontrol.controller import MenuKind
from handcontrol.mode_wheel import AIM_OFF, BACK, CANCEL, MAIN_PAGE, MORE, MORE_PAGE, ModeWheel

C, PU = (200.0, 300.0), 60.0
STEP = 33.0


def at(index, n, r=1.2, sign=1.0):
    a = math.tau * index / n
    return C[0] + sign * r * PU * math.sin(a), C[1] - r * PU * math.cos(a)


class Driver:
    def __init__(self, mirror=False):
        self.t = 0.0
        self.sign = -1.0 if mirror else 1.0
        self.wheel = ModeWheel(posed("v", C), 0.0, mirror)

    def feed(self, pose, palm=C, frames=6):
        for _ in range(frames):
            self.t += STEP
            out = self.wheel.update(posed(pose, palm) if pose else None, self.t)
            if out is not None:
                return out
        return None


@pytest.mark.parametrize("mirror", [False, True])
@pytest.mark.parametrize("index", range(5))
def test_aim_and_fist_pick_every_mode(index, mirror):
    d = Driver(mirror)
    p = at(index, 6, sign=d.sign)
    assert d.feed("v", p) is None and d.wheel.hovered == index
    assert d.feed("fist", p) == MAIN_PAGE[index]


def test_more_page_needs_a_new_v_and_back_returns():
    d = Driver()
    p = at(5, 6)
    d.feed("v", p)
    assert d.feed("fist", p, frames=30) is None and d.wheel.keys is MORE_PAGE
    assert d.feed("open", p, frames=30) is None           # opening the picking fist is not a cancel
    d.feed("v", p)                                        # new centre here
    assert d.wheel.hovered is None
    down = (p[0], p[1] + 1.2 * PU)
    d.feed("v", down)
    assert d.wheel.keys[d.wheel.hovered] == "windows"
    left = (p[0] - 1.2 * PU, p[1])
    d.feed("v", left)
    assert d.wheel.keys[d.wheel.hovered] == BACK
    assert d.feed("fist", left) is None and d.wheel.keys is MAIN_PAGE


def test_cancel_paths_and_short_poses():
    d = Driver()
    assert d.feed("fist") == CANCEL                       # fist in the middle
    d = Driver()
    d.feed("v", at(1, 6))
    assert d.feed("open", at(1, 6), frames=3) is None     # short
    assert d.feed("v", at(1, 6)) is None
    assert d.feed("fist", at(1, 6), frames=2) is None     # one flicker frame never picks
    assert d.feed("v", at(1, 6)) is None
    assert d.feed(None, frames=10) is None
    assert d.feed("open", at(1, 6)) == CANCEL


def test_closing_hand_and_borders_do_not_move_the_aim():
    d = Driver()
    d.feed("v", at(1, 6))
    closing = posed("v", at(3, 6))
    closing = replace(closing, fingers=tuple(replace(f, curl=0.45) if f.state is FingerState.EXTENDED else f
                                             for f in closing.fingers))
    d.wheel.update(closing, d.t + STEP)
    assert d.wheel.hovered == 1
    d.feed("v", at(1.55, 6))                              # just past the border: sticky
    assert d.wheel.hovered == 1
    d.feed("v", at(1.7, 6))
    assert d.wheel.hovered == 2
    d.feed("v", at(2, 6, r=AIM_OFF - 0.05))
    assert d.wheel.hovered is None


def test_pointer_stays_inside_the_wheel():
    d = Driver()
    d.feed("v", at(2, 6, r=6))
    assert math.dist(d.wheel.pointer, (0.5, 0.5)) == pytest.approx(0.5)


def test_controller_opens_switches_and_needs_neutral():
    r = Rig()
    r.settle(hand(RIGHT, tip=(420, 240)), posed("v"))
    r.frame(hand(RIGHT, tip=(420, 240)), posed("v"), events=[(G.MENU_DWELL_COMPLETE, LEFT)])
    m = r.ctl.snapshot().menu
    assert m is not None and m.kind is MenuKind.MODE
    assert [i.key for i in m.items] == list(MAIN_PAGE) and [i.key for i in m.items if i.selected] == ["pointer"]
    assert m.items[-1].label == "Diğer" and m.items[-1].key == MORE
    e = r.ctl.current_epoch()
    sign = -1.0 if r.ctl.config.mirror else 1.0
    p = at(1, 6, sign=sign)
    r.frame(hand(RIGHT, tip=(420, 240)), posed("v", p))
    assert r.ctl.snapshot().menu.hovered == 1
    for _ in range(4):
        r.frame(hand(RIGHT, tip=(420, 240)), posed("fist", p))
    s = r.ctl.snapshot()
    assert s.mode is Mode.SCROLL and s.menu is None and s.epoch > e and s.needs_neutral
    assert r.kinds() == []


@pytest.mark.parametrize("mode", list(Mode))
def test_wheel_opens_in_every_mode_without_os_input(mode):
    r = Rig()
    r.ctl.set_mode(mode)
    r.settle(posed("v"))
    r.sink.clear()
    r.frame(posed("v"), events=[(G.MENU_DWELL_COMPLETE, LEFT)])
    m = r.ctl.snapshot().menu
    assert m is not None and sum(i.selected for i in m.items) == 1
    for _ in range(10):
        r.frame(posed("fist"))                            # middle: cancel, window restore must not fire
    assert r.ctl.snapshot().menu is None and r.ctl.snapshot().mode is mode
    assert set(r.kinds()) <= {K.RELEASE_ALL}


def test_lost_hand_closes_and_dwell_is_reported_only_when_allowed():
    r = Rig()
    r.settle(hand(RIGHT), posed("v"))
    r.ctl.set_menu_dwell(0.5)
    assert r.ctl.snapshot().menu_dwell == 0.5
    r.frame(hand(RIGHT), posed("v"), events=[(G.MENU_DWELL_COMPLETE, LEFT)])
    assert r.ctl.snapshot().menu_dwell == 0.0
    for _ in range(30):
        r.frame(hand(RIGHT))
    assert r.ctl.snapshot().menu is None
    r.ctl.pause()
    assert r.ctl.snapshot().menu_dwell == 0.0
    r.frame(posed("v"), events=[(G.MENU_DWELL_COMPLETE, LEFT)])
    assert r.ctl.snapshot().menu is None
