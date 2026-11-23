"""Mode.INSTRUMENT through the real chain (raw landmarks -> features -> gestures -> controller -> sink):
no OS input at all, clap / menu still work, the recognizer profile follows the controller mode."""
from __future__ import annotations

import math
import threading

from handcontrol.contracts import ActionKind as A, ControlState, GestureKind as K, Mode
from handcontrol.gestures import GestureRecognizer
from handcontrol.pipeline import dominant_of, gesture_config

from integ_synth import FIST, OPEN, PINCH, POINT, Rig, clap, hand, lerp, pair

STRING = {"thumb": 0.0, "index": 0.0, "middle": 1.0, "ring": 1.0, "little": 1.0}   # thumb+index spread
LOOSE = {"thumb": 1.0, "index": 0.0, "middle": 0.0, "ring": 0.0, "little": 1.0}    # 3 non-thumb fingers
ND = (470.0, 300.0)
PU = 96.0
CLAPS = {K.CLAP, K.CLAP_CANDIDATE_START, K.CLAP_CANDIDATE_ABORT}


def right(d_pu: float, pose=POINT, y: float = 300.0):
    return hand(pose, (ND[0] - d_pu * PU, y), side="right")


def string_hand(pose=STRING):
    return hand(pose, ND, side="left")


def strum(rig: Rig, ms: float, pick=POINT, period_ms: float = 260.0, events: list | None = None) -> None:
    t0 = rig.t

    def frame(u: float):
        ph = (u * ms / period_ms) * 2.0 * math.pi
        d = lerp(2.6, 0.5, 0.5 - 0.5 * math.cos(ph))
        return [right(d, pick, 300.0 + 60.0 * math.sin(ph)), string_hand()]
    while rig.t < t0 + ms:
        u = min(1.0, (rig.t - t0) / ms)
        rig.frame(frame(u))
        if events is not None:
            events.extend(rig.pipe.last_events)


def approach(rig: Rig, pose_r=POINT, pose_l=STRING) -> None:
    rig.run(250, [right(3.0, pose_r), string_hand(pose_l)])
    rig.run(240, lambda u: [right(lerp(3.0, 0.45, u), pose_r), string_hand(pose_l)])
    rig.run(240, lambda u: [right(lerp(0.45, 3.0, u), pose_r), string_hand(pose_l)])


def instrument_rig() -> Rig:
    rig = Rig()
    rig.pipe.set_mode(Mode.INSTRUMENT)
    rig.activate([right(2.6), string_hand()])
    rig.sink.clear()
    return rig


def test_instrument_session_sends_no_os_input():
    rig = instrument_rig()
    assert rig.pipe.gestures.instrument_profile
    events: list = []
    strum(rig, 2500, events=events)
    approach(rig)
    approach(rig, LOOSE, LOOSE)
    strum(rig, 1500, pick=LOOSE, period_ms=200.0, events=events)
    rig.run(400, [right(2.6, PINCH), string_hand()])                  # pinches of both hands
    rig.run(400, [right(2.6, POINT), string_hand(PINCH)])
    rig.run(300, [right(2.6, OPEN), string_hand()])
    rig.run(700, [right(2.6, FIST), string_hand()])                   # fist hold
    rig.run(300, lambda u: [right(lerp(4.0, 1.0, u), OPEN)])         # swipe-like sweep
    assert not {e.kind for e in events} & (CLAPS | {K.MENU_DWELL_COMPLETE})
    assert rig.state is ControlState.ACTIVE and rig.mode is Mode.INSTRUMENT
    assert set(rig.sink.kinds()) <= {A.RELEASE_ALL}


def test_clap_pauses_and_resumes_in_instrument_mode():
    rig = instrument_rig()
    strum(rig, 1000)
    rig.run(600, pair(3.0))                  # open palms apart (the jump from the strum degrades a few frames)
    clap(rig)
    assert rig.state is ControlState.PAUSED and rig.mode is Mode.INSTRUMENT
    rig.run(700, pair(3.0))
    clap(rig)
    assert rig.state is ControlState.ACTIVE and rig.mode is Mode.INSTRUMENT
    assert rig.pipe.gestures.instrument_profile
    assert set(rig.sink.kinds()) <= {A.RELEASE_ALL}


def test_mode_menu_leaves_instrument_and_profile_follows():
    rig = instrument_rig()
    rig.run(900, [right(2.6, POINT), string_hand(OPEN)])             # non-dominant open palm held still
    menu = rig.ctl.snapshot().menu
    assert menu is not None and any(i.key == "instrument" and i.selected for i in menu.items)
    # move the right palm up: row 0 = pointer
    rig.run(200, lambda u: [right(2.6, POINT, lerp(300, 200, u)), string_hand(FIST)])
    menu = rig.ctl.snapshot().menu
    assert menu.items[menu.hovered].key == "pointer"
    rig.run(150, [right(2.6, PINCH, 200), string_hand(FIST)])
    assert rig.mode is Mode.POINTER and rig.ctl.snapshot().menu is None
    assert set(rig.sink.kinds()) <= {A.RELEASE_ALL}
    rig.run(100, [right(2.6, PINCH, 200)])
    assert not rig.pipe.gestures.instrument_profile
    rig.run(400, [right(2.6, POINT, 200)])
    rig.run(600, lambda u: [right(lerp(2.6, 1.0, u), POINT, 200)])
    assert rig.count(A.MOVE_POINTER) > 3                             # normal behavior is back


def test_string_pose_or_four_fingers_never_open_menu_in_instrument():
    rig = instrument_rig()
    rig.run(1500, [right(2.6, POINT), string_hand(STRING)])
    rig.run(1500, [right(2.6, POINT), string_hand(FOUR)])
    assert rig.ctl.snapshot().menu is None


def test_profile_follows_tray_mode_from_another_thread_and_replaced_recognizer():
    rig = Rig()
    rig.activate([right(2.6), string_hand()])
    assert not rig.pipe.gestures.instrument_profile
    th = threading.Thread(target=rig.pipe.set_mode, args=(Mode.INSTRUMENT,))
    th.start()
    th.join()
    rig.frame([right(2.6), string_hand()])
    assert rig.pipe.gestures.instrument_profile
    # app._replace_pipeline style: a brand new recognizer object
    rig.pipe.gestures = GestureRecognizer(gesture_config(rig.pipe.settings), dominant_of(rig.pipe.settings))
    assert not rig.pipe.gestures.instrument_profile
    rig.frame([right(2.6), string_hand()])
    assert rig.pipe.gestures.instrument_profile
    rig.pipe.set_mode(Mode.SCROLL)
    rig.frame([right(2.6), string_hand()])
    assert not rig.pipe.gestures.instrument_profile


class _LegacyRecognizer(GestureRecognizer):
    def set_instrument_profile(self, enabled: bool) -> None:   # never switches
        pass


FOUR = {"thumb": 1.0, "index": 0.0, "middle": 0.0, "ring": 0.0, "little": 0.0}


def _pointer_session(rig: Rig) -> None:
    rig.activate([right(2.6), string_hand()])
    strum(rig, 2000)
    for pose in (LOOSE, OPEN):
        approach(rig, pose, pose)
    rig.run(900, [right(2.6, POINT), string_hand(FOUR)])       # legacy menu dwell (4 fingers)
    rig.run(300, [right(2.6, POINT), string_hand(FIST)])
    rig.run(600, pair(3.0))
    clap(rig)


def test_other_modes_unaffected_by_the_profile_plumbing():
    """POINTER mode: the same session gives identical actions with the real recognizer and one whose
    profile can never switch (legacy), so there is no new suppression outside INSTRUMENT."""
    a, b = Rig(), Rig()
    b.pipe.gestures = _LegacyRecognizer(gesture_config(b.pipe.settings), dominant_of(b.pipe.settings))
    _pointer_session(a)
    _pointer_session(b)
    assert not a.pipe.gestures.instrument_profile
    ka, kb = [(x.kind, x.x, x.y) for x in a.sink.actions], [(x.kind, x.x, x.y) for x in b.sink.actions]
    assert ka == kb
    assert a.count(A.MOVE_POINTER) > 0
    assert (a.state, a.mode, a.pipe.gesture_resets) == (b.state, b.mode, b.pipe.gesture_resets)
    assert a.pipe.gesture_resets > 1                 # claps / menu really changed state on the way
