"""Mode.INSTRUMENT: the controller sends no OS input at all (only RELEASE_ALL from resets), while the
clap toggle, the mode menu and the safety paths keep working."""
from __future__ import annotations

from dataclasses import replace

import pytest

from ctrl_helpers import G, K, LEFT, RIGHT, W, WIN_A, Rig, hand, tcfg
from handcontrol.contracts import ControlState, FingerInfo, FingerName, FingerState, Landmark, Mode
from handcontrol.controller import AUTO_PAUSE_REASON, ControllerConfig, MenuKind

E, B = FingerState.EXTENDED, FingerState.BENT


def posed(hid: int, states, tip=(320.0, 240.0)):
    h = hand(hid, tip=tip)
    return replace(h, fingers=tuple(FingerInfo(n, s, 0.1 if s is E else 0.9) for n, s in zip(FingerName, states)))


def fist(hid, tip=(320.0, 240.0)):
    return posed(hid, (B, B, B, B, B), tip)


def pointing(hid=RIGHT, tip=(320.0, 240.0)):
    return posed(hid, (B, E, B, B, B), tip)


def string(tip=(200.0, 240.0)):
    return posed(LEFT, (E, E, B, B, B), tip)


def everything(r: Rig) -> None:
    """Every input path of every other mode: pointer moves, pinches (click, hold, drag), thumb+middle
    (identical landmarks read as a closed thumb+middle pinch), zoom pair, left pinch, fists, swipes,
    the pointing pose held still (dwell click / index tap)."""
    for i in range(20):                                        # pointing pose moving: pointer
        r.frame(pointing(tip=(200 + 15 * i, 240)), string())
    r.frame(hand(RIGHT), string(), events=[(G.PINCH_START, RIGHT)])   # short pinch: click
    for _ in range(3):
        r.frame(hand(RIGHT), string())
    r.frame(hand(RIGHT), string(), events=[(G.PINCH_END, RIGHT)])
    for _ in range(8):
        r.frame(hand(RIGHT), string())
    r.frame(hand(RIGHT), string(), events=[(G.PINCH_START, RIGHT)])   # long moving pinch: drag / long press
    for i in range(30):
        r.frame(hand(RIGHT, tip=(320 + 8 * i, 240 + 3 * i)), string())
    r.frame(hand(RIGHT, tip=(560, 330)), string(), events=[(G.PINCH_END, RIGHT)])
    for _ in range(8):
        r.frame(hand(RIGHT), hand(LEFT, tip=(200, 240)))
    r.frame(hand(RIGHT), hand(LEFT, tip=(200, 240)), events=[(G.PINCH_START, RIGHT), (G.PINCH_START, LEFT)])
    for i in range(15):                                        # zoom pair spreading
        r.frame(hand(RIGHT, tip=(320 + 10 * i, 240)), hand(LEFT, tip=(200 - 8 * i, 240)))
    r.frame(hand(RIGHT), hand(LEFT), events=[(G.PINCH_END, RIGHT), (G.PINCH_END, LEFT)])
    for _ in range(8):
        r.frame(hand(RIGHT), hand(LEFT, tip=(200, 240)))
    r.frame(hand(RIGHT), hand(LEFT, tip=(200, 240)), events=[(G.PINCH_START, LEFT)])   # left pinch moving
    for i in range(15):
        r.frame(hand(RIGHT), hand(LEFT, tip=(200, 240 - 10 * i)))
    r.frame(hand(RIGHT), hand(LEFT), events=[(G.PINCH_END, LEFT)])
    for hid in (RIGHT, LEFT):                                  # fists: minimize / restore
        for _ in range(10):
            r.frame(hand(hid))
        for _ in range(30):
            r.frame(fist(hid))
        for _ in range(10):
            r.frame(hand(hid))
    for _ in range(3):                                         # fast horizontal swipes, both directions
        for i in range(8):
            r.frame(hand(RIGHT, tip=(100 + 60 * i, 240)))
        for _ in range(10):
            r.frame(hand(RIGHT, tip=(520, 240)))
        for i in range(8):
            r.frame(hand(RIGHT, tip=(520 - 60 * i, 240)))
        for _ in range(10):
            r.frame(hand(RIGHT, tip=(100, 240)))
    for _ in range(60):                                        # pointing pose held still: dwell click
        r.frame(pointing(tip=(300, 200)), string())
    for i in range(20):                                        # index bending and straightening (taps)
        r.frame(posed(RIGHT, (B, B if i % 4 < 2 else E, B, B, B), tip=(300, 200)), string())


CONFIGS = {
    "default": ControllerConfig(),                             # relative pointer + pinch mouse
    "absolute": tcfg(),
    "pinch_mouse_abs": tcfg(pinch_mouse=True),
    "index_tap": tcfg(index_tap_click=True),
    "dwell": ControllerConfig(dwell_click=True, dwell_ms=500.0),
}


@pytest.mark.parametrize("name", sorted(CONFIGS))
def test_instrument_mode_sends_nothing_but_release_all(name):
    r = Rig(CONFIGS[name])
    r.ctl.set_mode(Mode.INSTRUMENT)
    r.settle(hand(RIGHT), hand(LEFT))
    everything(r)
    s = r.ctl.snapshot()
    assert s.mode is Mode.INSTRUMENT and s.state is ControlState.ACTIVE
    assert set(r.kinds()) <= {K.RELEASE_ALL}
    assert s.hold_kind == "" and s.pending_action == "" and not s.pointer_engaged


@pytest.mark.parametrize("name", ["absolute", "default"])
def test_same_script_drives_the_os_in_pointer_mode(name):
    """Control: the script above really produces OS input outside INSTRUMENT."""
    r = Rig(CONFIGS[name])
    r.settle(hand(RIGHT), hand(LEFT))
    everything(r)
    assert set(r.kinds()) - {K.RELEASE_ALL}


@pytest.mark.parametrize("mode", [m for m in Mode if m is not Mode.INSTRUMENT])
def test_entering_instrument_from_any_mode_releases_and_bumps_epoch(mode):
    r = Rig(tcfg())
    r.ctl.set_mode(mode)
    r.sink.clear()
    e = r.ctl.current_epoch()
    r.ctl.set_mode(Mode.INSTRUMENT)
    assert r.kinds() == [K.RELEASE_ALL] and r.ctl.current_epoch() > e
    assert r.ctl.snapshot().needs_neutral


def _mh(tip=(320.0, 240.0)):
    """Open right hand with the thumb+middle pinch clearly open (landmark 12 1.5 pu from 4)."""
    h = hand(RIGHT, tip=tip, palm=(tip[0], tip[1] + 60.0))
    lms = [Landmark(0.5, 0.5)] * 21
    lms[12] = Landmark(0.5 + 1.5 * 60.0 / W, 0.5)
    return replace(h, landmarks=tuple(lms))


def test_held_drag_is_released_only_by_release_all_on_entry():
    """POINTER pinch-mouse drag holding the left button: switching to INSTRUMENT frees it with
    RELEASE_ALL; no LEFT_UP or other input is dispatched in the new mode."""
    r = Rig(tcfg(pinch_mouse=True))
    r.settle(_mh())
    r.frame(_mh())
    r.frame(_mh(), events=[(G.PINCH_START, RIGHT)])
    for _ in range(9):
        r.frame(_mh())
    for k in range(1, 10):
        r.frame(_mh((320.0 + 10 * k, 240.0)))
    assert K.LEFT_DOWN in r.kinds()
    r.sink.clear()
    r.ctl.set_mode(Mode.INSTRUMENT)
    for i in range(10):
        r.frame(_mh((410.0 - 10 * i, 240.0)))
    r.frame(_mh(), events=[(G.PINCH_END, RIGHT)])
    assert r.kinds() and set(r.kinds()) == {K.RELEASE_ALL}


def test_window_mode_leftovers_do_nothing_after_switch():
    r = Rig(tcfg())
    r.ctl.set_mode(Mode.WINDOWS)
    r.settle(hand(RIGHT))
    r.frame(hand(RIGHT), events=[(G.PINCH_START, RIGHT)])
    for i in range(12):                                        # window drag running
        r.frame(hand(RIGHT, tip=(320 + 5 * i, 240)))
    r.sink.clear()
    r.ctl.set_mode(Mode.INSTRUMENT)
    for i in range(12):
        r.frame(hand(RIGHT, tip=(380 + 5 * i, 240)))
    r.frame(hand(RIGHT), events=[(G.PINCH_END, RIGHT)])
    for _ in range(10):
        r.frame(hand(RIGHT))
    assert set(r.kinds()) <= {K.RELEASE_ALL}
    assert r.ctl.snapshot().menu is None


def test_clap_toggles_pause_and_resume_in_instrument_mode():
    r = Rig(tcfg())
    r.ctl.set_mode(Mode.INSTRUMENT)
    r.settle(hand(RIGHT), hand(LEFT))
    r.frame(hand(RIGHT), hand(LEFT), events=[(G.CLAP_CANDIDATE_START,)])
    assert r.ctl.snapshot().clap_pending
    r.frame(hand(RIGHT), hand(LEFT), events=[(G.CLAP,)])
    s = r.ctl.snapshot()
    assert s.state is ControlState.PAUSED and s.mode is Mode.INSTRUMENT
    for _ in range(30):
        r.frame(hand(RIGHT), hand(LEFT))
    r.frame(hand(RIGHT), hand(LEFT), events=[(G.CLAP,)])
    s = r.ctl.snapshot()
    assert s.state is ControlState.ACTIVE and s.mode is Mode.INSTRUMENT
    everything(r)
    assert set(r.kinds()) <= {K.RELEASE_ALL}


def _both(tip_y: float = 240.0):
    return hand(RIGHT, tip=(420, tip_y)), hand(LEFT, tip=(200, 240))


def test_mode_menu_opens_and_leaves_instrument_then_pointer_works():
    r = Rig(tcfg())
    r.ctl.set_mode(Mode.INSTRUMENT)
    r.settle(*_both())
    r.frame(*_both(), events=[(G.MENU_DWELL_COMPLETE, LEFT)])
    m = r.ctl.snapshot().menu
    assert m is not None and m.kind is MenuKind.MODE and len(m.items) == len(Mode)
    assert m.items[-1].key == "instrument" and m.items[-1].label == "Enstrüman" and m.items[-1].selected
    r.frame(*_both(140.0))                                     # row 0 = pointer
    assert r.ctl.snapshot().menu.hovered == 0
    r.frame(*_both(140.0), events=[(G.PINCH_START, RIGHT)])
    s = r.ctl.snapshot()
    assert s.mode is Mode.POINTER and s.menu is None
    assert set(r.kinds()) <= {K.RELEASE_ALL}
    r.frame(*_both(140.0), events=[(G.PINCH_END, RIGHT)])
    r.settle(*_both(140.0))
    for i in range(10):
        r.frame(hand(RIGHT, tip=(300 + 10 * i, 240)))
    assert r.count(K.MOVE_POINTER) > 3


def test_mode_menu_blocked_by_need_neutral_and_times_out():
    r = Rig(tcfg())
    r.ctl.set_mode(Mode.INSTRUMENT)
    r.frame(*_both(), events=[(G.MENU_DWELL_COMPLETE, LEFT)])   # right after the mode change: no neutral yet
    assert r.ctl.snapshot().menu is None
    r.settle(*_both())
    r.frame(*_both(), events=[(G.MENU_DWELL_COMPLETE, LEFT)])
    assert r.ctl.snapshot().menu is not None
    for _ in range(170):                                       # 5 s menu timeout
        r.frame(*_both())
    assert r.ctl.snapshot().menu is None and r.ctl.snapshot().mode is Mode.INSTRUMENT
    assert set(r.kinds()) <= {K.RELEASE_ALL}


def test_auto_pause_watchdog_and_emergency_stop_unchanged():
    r = Rig(ControllerConfig(auto_pause_ms=1000.0))
    r.ctl.set_mode(Mode.INSTRUMENT)
    r.settle(hand(RIGHT))
    for _ in range(40):                                        # no hands
        r.frame()
    s = r.ctl.snapshot()
    assert s.state is ControlState.PAUSED and s.reason == AUTO_PAUSE_REASON
    assert r.ctl.resume()
    r.ctl.emergency_stop()
    assert r.ctl.snapshot().state is ControlState.PAUSED and r.kinds()[-1] is K.RELEASE_ALL
    assert set(r.kinds()) <= {K.RELEASE_ALL}
    r.ctl.on_session_lock()
    assert r.ctl.snapshot().state is ControlState.PAUSED


def test_identity_ambiguous_and_stale_frames_send_nothing():
    r = Rig(tcfg())
    r.ctl.set_mode(Mode.INSTRUMENT)
    r.settle(hand(RIGHT))
    for _ in range(5):
        r.frame(hand(RIGHT), hand(LEFT), ambiguous=True)
        r.frame(hand(RIGHT), latency=400.0)
        r.frame(hand(RIGHT, tip=(400, 200)), events=[(G.PINCH_START, RIGHT)])
        r.frame(hand(RIGHT), events=[(G.PINCH_END, RIGHT)])
    assert set(r.kinds()) <= {K.RELEASE_ALL}
    assert WIN_A not in [a.target for a in r.sink.actions if a.target is not None]
