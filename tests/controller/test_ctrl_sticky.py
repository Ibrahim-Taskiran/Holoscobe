"""Sticky pointer engagement (release hysteresis), short DEGRADED tolerance of the pointer hand,
the snapshot fields pointer_engaged / tracking_ok / last_cancel, and the pointing -> open hand ->
right click -> pointing transition. Relative pointer defaults, synthetic hands at 30 and 10 FPS."""
from __future__ import annotations

import dataclasses

import pytest
from ctrl_helpers import LEFT, RIGHT, G, K, Rig, tcfg
from test_ctrl_relative import FPS, _right_tap, hold, ptr, rh, rig, stroke

from handcontrol.contracts import FingerState, Mode, Quality
from handcontrol.controller import ControllerConfig, ControllerSnapshot

E, B, U = FingerState.EXTENDED, FingerState.BENT, FingerState.UNKNOWN
MIXED = (B, E, E, E, B)          # index up, middle and ring up: neither pointing nor a clear release
INDEX_BENT = (B, B, E, E, E)     # fist-like release without the fist gesture


def snap(r: Rig) -> ControllerSnapshot:
    return r.ctl.snapshot()


def deg(palm, **kw):
    return rh(palm, quality=Quality.DEGRADED, **kw)


# ---------------------------------------------------------------- config / snapshot fields


def test_new_defaults_and_snapshot_fields_are_appended_with_defaults():
    assert ControllerConfig().clutch_release_ms == 200.0
    tail = [(f.name, f.default) for f in dataclasses.fields(ControllerSnapshot)[-3:]]
    assert tail == [("pointer_engaged", False), ("tracking_ok", True), ("last_cancel", "")]


@FPS
def test_pointer_engaged_only_in_pointer_mode_with_the_relative_pointer(dt):
    r = rig(dt)
    assert snap(r).pointer_engaged and snap(r).tracking_ok
    r.ctl.set_mode(Mode.SCROLL)
    r.settle(rh())
    hold(r, (320.0, 300.0), 150, dt)
    assert not snap(r).pointer_engaged
    a = Rig(cfg=tcfg())
    a.settle(rh())
    assert not a.ctl.snapshot().pointer_engaged


# ---------------------------------------------------------------- sticky engagement


@FPS
@pytest.mark.parametrize("states", [(U, U, U, U, U), MIXED, (B, E, U, B, U)], ids=["unknown", "mixed", "partly"])
def test_unknown_or_mixed_fingers_keep_the_pointer_moving(dt, states):
    r = rig(dt, palm=(300.0, 300.0))
    p = ptr(r)
    stroke(r, (300.0, 300.0), (360.0, 300.0), 400, dt, states=states)
    assert ptr(r)[0] > p[0] + 20 and snap(r).pointer_engaged


@FPS
@pytest.mark.parametrize("states", [(E, E, E, E, E), INDEX_BENT], ids=["open", "index_bent"])
def test_short_release_flicker_freezes_then_resumes_without_reengage(dt, states):
    real = [(500, 500)]
    r = rig(dt, palm=(300.0, 300.0), cursor_source=lambda: real[0])
    stroke(r, (300.0, 300.0), (330.0, 300.0), 200, dt)
    p, n = ptr(r), r.count(K.MOVE_POINTER)
    real[0] = (1700, 100)                        # would show up if the pointer re-engaged
    r.frame(rh((345.0, 300.0), states=states), dt=dt)   # one release frame: frozen at once
    assert ptr(r) == p and r.count(K.MOVE_POINTER) == n and snap(r).pointer_engaged
    r.frame(rh((350.0, 300.0)), dt=dt)           # pointing again: resumes from the last frame, no replay
    q = ptr(r)
    assert q[0] > p[0] and q[0] - p[0] < 60 and abs(q[1] - p[1]) <= 1
    assert snap(r).pointer_engaged


@FPS
@pytest.mark.parametrize("states", [(E, E, E, E, E), INDEX_BENT], ids=["open", "index_bent"])
def test_clear_release_must_hold_the_release_time(dt, states):
    r = rig(dt, palm=(300.0, 300.0))
    n = r.count(K.MOVE_POINTER)
    hold(r, (300.0, 300.0), 150 if dt < 50 else 100, dt, states=states)
    assert snap(r).pointer_engaged                # below clutch_release_ms
    stroke(r, (300.0, 300.0), (380.0, 300.0), 300, dt, states=states)
    assert not snap(r).pointer_engaged and r.count(K.MOVE_POINTER) == n


@FPS
def test_release_interrupted_by_unknown_frames_still_clutches_on_a_clear_release(dt):
    r = rig(dt, palm=(300.0, 300.0))
    n = r.count(K.MOVE_POINTER)
    r.frame(rh((300.0, 300.0), "open"), dt=dt)
    stroke(r, (300.0, 300.0), (340.0, 300.0), 200, dt, states=(U, U, U, U, U))   # stays frozen
    assert r.count(K.MOVE_POINTER) == n
    r.frame(rh((340.0, 300.0), "open"), dt=dt)
    assert not snap(r).pointer_engaged


@FPS
def test_release_then_reengage_rereads_the_cursor_without_a_jump(dt):
    real = [(400, 400)]
    r = rig(dt, palm=(300.0, 300.0), cursor_source=lambda: real[0])
    stroke(r, (300.0, 300.0), (340.0, 300.0), 200, dt)
    hold(r, (340.0, 300.0), 300, dt, "open")
    assert not snap(r).pointer_engaged
    stroke(r, (340.0, 300.0), (260.0, 300.0), 300, dt, "open")
    real[0] = (1200, 700)
    n = r.count(K.MOVE_POINTER)
    hold(r, (260.0, 300.0), 150, dt)
    assert snap(r).pointer_engaged and ptr(r) == (1200, 700) and r.count(K.MOVE_POINTER) == n
    stroke(r, (260.0, 300.0), (280.0, 300.0), 200, dt)
    assert 1200 < ptr(r)[0] < 1300


@FPS
def test_held_fist_clutches_like_an_open_hand(dt):
    r = rig(dt, palm=(300.0, 300.0))
    hold(r, (300.0, 300.0), 300, dt, "closed", index_curl=0.95)
    assert not snap(r).pointer_engaged and r.count(K.MOVE_POINTER) == 0


@FPS
def test_pinch_with_index_bent_does_not_release(dt):
    r = rig(dt, palm=(300.0, 300.0))
    r.frame(rh((300.0, 300.0), states=INDEX_BENT, idx=0.1), events=[(G.PINCH_START, RIGHT)], dt=dt)
    hold(r, (300.0, 300.0), 300, dt, states=INDEX_BENT, idx=0.1)
    assert snap(r).pointer_engaged


@FPS
def test_hand_id_change_and_missing_hand_disengage_at_once(dt):
    r = rig(dt)
    r.frame(rh(hid=7), dt=dt)
    assert not snap(r).pointer_engaged
    r = rig(dt)
    r.frame(dt=dt)
    assert not snap(r).pointer_engaged and not snap(r).tracking_ok


# ---------------------------------------------------------------- short DEGRADED tolerance


def _gap_frames(dt: float, ms: float) -> int:
    return max(1, int(ms // dt))


GAP_DT = 40.0   # gap frames arrive at 25 FPS: one 10 FPS frame gap already spans the 200 ms watchdog


@FPS
@pytest.mark.parametrize("left", [False, True], ids=["alone", "with_left_hand"])
def test_short_degraded_gap_keeps_engagement_without_motion_or_replay(dt, left):
    extra = (rh((520.0, 300.0), "open", hid=LEFT),) if left else ()
    r = rig(dt, palm=(300.0, 300.0))
    for k in range(1, 7):
        r.frame(rh((300.0 + 5.0 * k, 300.0)), *extra, dt=dt)
    p, n = ptr(r), r.count(K.MOVE_POINTER)
    x = 330.0
    for _ in range(_gap_frames(GAP_DT, 120.0)):       # hand keeps moving while DEGRADED (< 200 ms)
        x += 15.0
        r.frame(deg((x, 300.0)), *extra, dt=GAP_DT)
        s = snap(r)
        assert s.pointer_engaged and s.tracking_ok
    assert ptr(r) == p and r.count(K.MOVE_POINTER) == n
    r.frame(rh((x, 300.0)), *extra, dt=GAP_DT)      # recovery frame re-anchors: no jump
    assert ptr(r) == p
    r.frame(rh((x + 5.0, 300.0)), *extra, dt=dt)    # moves on at once, no re-engage debounce
    q = ptr(r)
    assert q[0] > p[0] and q[0] - p[0] < 60 and snap(r).pointer_engaged


@FPS
@pytest.mark.parametrize("left", [False, True], ids=["alone", "with_left_hand"])
def test_long_degraded_gap_disengages_as_before(dt, left):
    extra = (rh((520.0, 300.0), "open", hid=LEFT),) if left else ()
    r = rig(dt, palm=(300.0, 300.0))
    r.frame(rh((300.0, 300.0)), *extra, dt=dt)
    for _ in range(_gap_frames(dt, 210.0) + 1):
        r.frame(deg((320.0, 300.0)), *extra, dt=dt)
    s = snap(r)
    assert not s.pointer_engaged and not s.tracking_ok
    n = r.count(K.MOVE_POINTER)
    r.frame(rh((330.0, 300.0)), *extra, dt=dt)
    assert r.count(K.MOVE_POINTER) == n             # needs the engage debounce again


@FPS
def test_degraded_frame_of_another_hand_id_or_ambiguous_frame_still_disengages(dt):
    r = rig(dt)
    r.frame(rh(hid=9, quality=Quality.DEGRADED), dt=dt)
    assert not snap(r).pointer_engaged
    r = rig(dt)
    r.frame(deg((320.0, 300.0)), dt=dt, ambiguous=True)
    assert not snap(r).pointer_engaged


# ---------------------------------------------------------------- last_cancel


@FPS
def test_last_cancel_reasons_and_clear_on_dispatch(dt):
    r = rig(dt, pose="open")
    for d in (1.0, 0.15, 0.15) + (0.15,) * int(3100 // dt):        # right pinch held too long (> 3 s)
        r.frame(rh(pose="open", mid=d), dt=dt)
    assert snap(r).last_cancel == "Sağ tık iptal: uzun tutuldu"
    for d in (0.6, 1.2, 1.2, 1.2, 1.2, 1.2, 1.2, 1.2, 1.2):
        r.frame(rh(pose="open", mid=d), dt=dt)
    hold(r, (320.0, 300.0), 800, dt, "open")
    _right_tap(r, dt)
    assert r.count(K.RIGHT_CLICK) == 1 and snap(r).last_cancel == ""


@FPS
def test_last_cancel_on_tracking_loss_and_ambiguous_contact(dt):
    r = rig(dt)
    r.frame(rh(idx=0.1), events=[(G.PINCH_START, RIGHT)], dt=dt)
    r.frame(dt=dt)
    assert snap(r).last_cancel == "Tıklama iptal: takip koptu"
    r = rig(dt, pose="open")
    r.frame(rh(pose="open", idx=0.2, mid=0.2), events=[(G.PINCH_START, RIGHT)], dt=dt)
    hold(r, (320.0, 300.0), 100, dt, "open", idx=0.2, mid=0.2)
    assert snap(r).last_cancel == "Kararsız: iki parmak da temas etti"
    assert r.count(K.LEFT_CLICK) == 0 and r.count(K.RIGHT_CLICK) == 0


@FPS
def test_left_click_clears_last_cancel(dt):
    r = rig(dt)
    r.frame(rh(idx=0.1), events=[(G.PINCH_START, RIGHT)], dt=dt)
    r.frame(dt=dt)
    assert snap(r).last_cancel
    r.frame(rh(), events=[(G.PINCH_END, RIGHT)], dt=dt)
    r.settle(rh())
    hold(r, (320.0, 300.0), 150, dt)
    r.frame(rh(idx=0.1), events=[(G.PINCH_START, RIGHT)], dt=dt)
    r.frame(rh(idx=0.1), dt=dt)
    r.frame(rh(idx=1.0), events=[(G.PINCH_END, RIGHT)], dt=dt)
    assert r.count(K.LEFT_CLICK) == 1 and snap(r).last_cancel == ""


# ---------------------------------------------------------------- pointing -> right click -> pointing


@FPS
@pytest.mark.parametrize("open_ms", [300.0, 100.0], ids=["released", "quick"])
@pytest.mark.parametrize("states", [None, (B, E, B, E, E)], ids=["open_pinch", "middle_bent_pinch"])
def test_pointing_open_right_click_and_back_to_pointing(dt, open_ms, states):
    r = rig(dt, palm=(300.0, 300.0))
    stroke(r, (300.0, 300.0), (340.0, 300.0), 300, dt)            # engaged and moving
    p, n = ptr(r), r.count(K.MOVE_POINTER)
    assert p[0] > 960
    stroke(r, (340.0, 300.0), (350.0, 300.0), open_ms, dt, "open")  # hand opens and drifts a little
    _right_tap(r, dt, states=states, palm=(350.0, 300.0))
    clicks = r.sink.of(K.RIGHT_CLICK)
    assert len(clicks) == 1 and (clicks[0].x, clicks[0].y) == p
    assert r.count(K.MOVE_POINTER) == n and ptr(r) == p
    assert r.count(K.LEFT_CLICK) == 0 and r.count(K.LEFT_DOWN) == 0
    hold(r, (350.0, 300.0), 150, dt)                               # back to pointing
    assert snap(r).pointer_engaged and ptr(r) == p and r.count(K.MOVE_POINTER) == n
    stroke(r, (350.0, 300.0), (370.0, 300.0), 200, dt)
    q = ptr(r)
    assert p[0] < q[0] < p[0] + 120 and abs(q[1] - p[1]) <= 1
