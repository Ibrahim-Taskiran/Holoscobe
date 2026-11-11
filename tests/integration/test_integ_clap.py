"""Clap toggle through the real chain (raw landmarks -> features -> gestures -> controller)."""
from __future__ import annotations

from handcontrol.contracts import ActionKind as A, ControlState, GestureKind as K, Handedness

from integ_synth import OPEN, POINT, Rig, clap, hand, lerp, pair


def _toggles(rig: Rig) -> list[ControlState]:
    """State changes after now (the starting state is not listed)."""
    seen: list[ControlState] = []
    last = [rig.state]

    def cb(snap):
        if snap.state is not last[0]:
            last[0] = snap.state
            seen.append(snap.state)
    rig.ctl.add_listener(cb)
    return seen


def test_starts_paused_and_ignores_hands(rig):
    rig.camera_on()
    rig.run(600, lambda u: [hand(POINT, (lerp(150, 450, u), 300))])
    assert rig.state is ControlState.PAUSED
    assert rig.kinds() == []


def test_clap_with_merged_contact_toggles_active_then_paused(rig):
    rig.camera_on()
    seen = _toggles(rig)
    clap(rig, merge_frames=2)
    assert rig.state is ControlState.ACTIVE
    assert seen == [ControlState.ACTIVE]
    assert set(rig.kinds()) <= {A.MOVE_POINTER}   # only after neutral, never while paused
    rig.run(700, pair(3.0))                       # cooldown + fresh separated pose
    clap(rig, merge_frames=2)
    assert seen == [ControlState.ACTIVE, ControlState.PAUSED]
    assert rig.count(A.LEFT_CLICK) == 0
    assert set(rig.kinds()) <= {A.MOVE_POINTER}


def test_clap_with_missing_contact_frames(rig):
    rig.camera_on()
    rig.run(200, pair(3.0))
    rig.run(240, lambda u: pair(lerp(3.0, 0.45, u)))
    rig.frame([])                                 # tracker lost both hands at contact
    rig.frame([])
    rig.run(240, lambda u: pair(lerp(0.45, 3.0, u)))
    assert rig.state is ControlState.ACTIVE


def test_no_clap_without_camera(rig):
    clap(rig)
    assert rig.state is ControlState.PAUSED


def test_clap_waits_for_neutral_before_pointer(rig):
    rig.camera_on()
    clap(rig, hold_ms=0)
    first = len(rig.sink.actions)
    rig.frame(pair(3.0, pose=POINT))              # right after the clap: no neutral yet
    assert len(rig.sink.actions) == first


def test_hands_crossing_sideways_is_not_a_clap(rig):
    """Regression: palm distance alone made a fast open-palm crossing look like a clap."""
    rig.camera_on()
    events: list[K] = []
    orig = rig.pipe.gestures.update
    rig.pipe.gestures.update = lambda ff: [events.append(e.kind) or e for e in orig(ff)]
    for dur in (300, 600, 1500):
        rig.run(300, [hand(OPEN, (150, 300), side="right"), hand(OPEN, (490, 300), side="left")])
        rig.run(dur, lambda u: [hand(OPEN, (lerp(150, 490, u), 300), side="right"),
                                hand(OPEN, (lerp(490, 150, u), 300), side="left")])
        rig.run(300, [hand(OPEN, (490, 300), side="right"), hand(OPEN, (150, 300), side="left")])
        rig.run(1000, [hand(OPEN, (150, 300), side="right"), hand(OPEN, (490, 300), side="left")])
    assert K.CLAP not in events
    assert rig.state is ControlState.PAUSED
    assert rig.kinds() == []


def test_crossing_back_and_forth_while_active_sends_no_click(rig):
    rig.activate(pair(3.0, pose=POINT))
    rig.run(500, lambda u: [hand(POINT, (lerp(150, 490, u), 300), side="right"),
                            hand(POINT, (lerp(490, 150, u), 300), side="left")])
    rig.run(500, lambda u: [hand(POINT, (lerp(490, 150, u), 300), side="right"),
                            hand(POINT, (lerp(150, 490, u), 300), side="left")])
    assert rig.state is ControlState.ACTIVE
    assert set(rig.kinds()) <= {A.MOVE_POINTER}


def test_emergency_stop_during_clap_candidate_prevents_activation(rig):
    """Pipeline resets the recognizer on emergency stop: a clap already in flight cannot activate."""
    rig.camera_on()
    rig.run(200, pair(3.0))
    rig.run(160, lambda u: pair(lerp(3.0, 1.2, u)))
    assert rig.pipe.gestures.clap_candidate_active
    rig.pipe.emergency_stop()
    rig.run(120, lambda u: pair(lerp(1.2, 0.45, u)))
    rig.run(240, lambda u: pair(lerp(0.45, 3.0, u)))
    assert rig.state is ControlState.PAUSED


def test_unknown_handedness_labels_still_clap(rig):
    rig.camera_on()
    rig.run(200, pair(3.0, dom_label=Handedness.UNKNOWN, nd_label=Handedness.UNKNOWN))
    rig.run(240, lambda u: pair(lerp(3.0, 0.45, u), dom_label=Handedness.UNKNOWN, nd_label=Handedness.UNKNOWN))
    rig.run(240, lambda u: pair(lerp(0.45, 3.0, u), dom_label=Handedness.UNKNOWN, nd_label=Handedness.UNKNOWN))
    assert rig.state is ControlState.ACTIVE
