"""Round 7 gesture set (user decision 2026-11-14), POINTER pinch mouse, dominant hand:
short thumb+index pinch = left click; held still right_long_press_ms = right click at once;
grab (thumb tip with index AND middle tips) = left-button drag until it opens; motion drag stays a
fallback; a fist is never a grab. Absolute and relative pointer."""
from __future__ import annotations

from dataclasses import replace

import pytest
from ctrl_helpers import RIGHT, G, K, Rig
from test_ctrl_pinch_mouse import PALM, mh, released_after_down
from test_ctrl_round6 import MODES, hold_left, last_cancel, release_left, rig

from handcontrol.contracts import FingerInfo, FingerName, FingerState, Quality
from handcontrol.controller import ControllerConfig


def pending(r: Rig) -> str:
    return r.ctl.snapshot().pending_action


def grab(palm=PALM, *, curl: float = 0.1, all_bent: bool = False, **kw):
    """Thumb tip on the index and middle tips. all_bent: every finger reads BENT with `curl`."""
    h = mh(palm=palm, idx=kw.pop("idx", .1), mid=kw.pop("mid", .1), **kw)
    if all_bent:
        h = replace(h, fingers=tuple(FingerInfo(n, FingerState.BENT, curl) for n in FingerName))
    elif curl != 0.1:
        h = replace(h, fingers=tuple(FingerInfo(f.name, f.state, curl) if f.name in (FingerName.INDEX, FingerName.MIDDLE)
                                     else f for f in h.fingers))
    return h


def start_grab(r: Rig, ms: float = 200.0, **kw) -> None:
    """Index contact first, the middle tip 40 ms later, held `ms`."""
    r.frame(mh(idx=.1), events=[(G.PINCH_START, RIGHT)])
    r.frame(grab(**kw), dt=40.0)
    for _ in range(int(ms / 33.4)):
        r.frame(grab(**kw))


def open_all(r: Rig, palm=PALM) -> None:
    r.frame(mh(palm=palm), events=[(G.PINCH_END, RIGHT)])
    for _ in range(4):
        r.frame(mh(palm=palm))


def test_round7_defaults():
    c = ControllerConfig()
    assert c.right_long_press_ms == 800.0 and c.grab_confirm_ms == 120.0 and c.pinch_decide_ms == 60.0
    assert c.mouse_drag_move_palm == 0.6


# ---------------------------------------------------------------- left click vs long press


@MODES
def test_release_at_700_ms_is_a_left_click_with_the_hold_hint(rel):
    r = rig(rel)
    p = r.ctl.snapshot().pointer
    r.frame(mh(idx=.1), events=[(G.PINCH_START, RIGHT)])
    hold_left(r, 400, dt=100)
    assert pending(r) == "Sağ tık için tutun"
    hold_left(r, 200, dt=100)
    r.frame(mh(), events=[(G.PINCH_END, RIGHT)], dt=100)
    clicks = r.sink.of(K.LEFT_CLICK)
    assert len(clicks) == 1 and (clicks[0].x, clicks[0].y) == p
    assert r.count(K.RIGHT_CLICK) == r.count(K.LEFT_DOWN) == 0


@MODES
@pytest.mark.parametrize("pose", ["open", "pointing"])
def test_hold_900_ms_right_clicks_once_at_800_ms_and_the_release_adds_nothing(rel, pose):
    r = rig(rel)
    p = r.ctl.snapshot().pointer
    bent = "imrl" if pose == "pointing" else "i"   # pointing pose: middle, ring, little curled
    kw = dict(idx=.1, mid=.7, bent=bent) if pose == "pointing" else dict(idx=.1, bent=bent)
    t0 = r.frame(mh(**kw), events=[(G.PINCH_START, RIGHT)])
    fired = None
    for _ in range(27):                                 # 900 ms
        t = r.frame(mh(**kw))
        if fired is None and r.count(K.RIGHT_CLICK):
            fired = t
    assert fired is not None and 800.0 <= fired - t0 < 800.0 + 34.0
    clicks = r.sink.of(K.RIGHT_CLICK)
    assert len(clicks) == 1 and (clicks[0].x, clicks[0].y) == p
    assert pending(r) == "Sağ tık" and last_cancel(r) == ""
    release_left(r)
    assert r.count(K.RIGHT_CLICK) == 1 and r.count(K.LEFT_CLICK) == r.count(K.LEFT_DOWN) == 0
    assert pending(r) == ""


@MODES
def test_motion_before_the_long_press_drags_and_never_right_clicks(rel):
    r = rig(rel)
    r.frame(mh(idx=.1), events=[(G.PINCH_START, RIGHT)])
    for k in range(1, 6):                               # 50 px = 0.83 pu within 170 ms
        r.frame(mh(palm=(PALM[0] + 10 * k, PALM[1]), idx=.1))
    assert r.count(K.LEFT_DOWN) == 1
    hold_left(r, 1200, palm=(PALM[0] + 50, PALM[1]))
    release_left(r, (PALM[0] + 50, PALM[1]))
    assert r.count(K.RIGHT_CLICK) == r.count(K.LEFT_CLICK) == 0 and r.count(K.LEFT_UP) == 1


# ---------------------------------------------------------------- grab


@MODES
def test_grab_40_ms_after_the_index_contact_drags_and_never_clicks(rel):
    r = rig(rel)
    p = r.ctl.snapshot().pointer
    start_grab(r, 70)
    assert r.count(K.LEFT_DOWN) == 0 and pending(r) == "Sürükleme hazırlanıyor"
    for _ in range(3):                                  # past grab_confirm_ms (120)
        r.frame(grab())
    downs = r.sink.of(K.LEFT_DOWN)
    assert len(downs) == 1 and (downs[0].x, downs[0].y) == p
    for k in range(1, 8):
        r.frame(grab(palm=(PALM[0] + 8 * k, PALM[1]), tip=(320.0 + 8 * k, 240.0)))
    assert r.count(K.MOVE_POINTER) >= 3 and r.count(K.LEFT_UP) == 0
    hold = r.ctl.snapshot().pointer
    for _ in range(30):                                 # a still grab held past the long press time
        r.frame(grab(palm=(PALM[0] + 56, PALM[1]), tip=(376.0, 240.0)))
    open_all(r, (PALM[0] + 56, PALM[1]))
    ups = r.sink.of(K.LEFT_UP)
    assert len(ups) == 1 and (ups[0].x, ups[0].y) == hold != p
    assert r.count(K.LEFT_CLICK) == r.count(K.RIGHT_CLICK) == 0


@MODES
def test_middle_first_then_index_is_a_grab_too(rel):
    r = rig(rel)
    for _ in range(3):                                  # thumb+middle from the open hand (RIGHT_TAP)
        r.frame(mh(mid=.1))
    r.frame(grab(), events=[(G.PINCH_START, RIGHT)])
    for _ in range(6):
        r.frame(grab())
    assert r.count(K.LEFT_DOWN) == 1
    open_all(r)
    assert r.count(K.LEFT_UP) == 1 and r.count(K.LEFT_CLICK) == r.count(K.RIGHT_CLICK) == 0


@MODES
def test_grab_losing_the_middle_for_one_frame_keeps_the_button_then_middle_opening_releases(rel):
    r = rig(rel)
    start_grab(r, 200)
    assert r.count(K.LEFT_DOWN) == 1
    r.frame(grab(mid=.6))                               # one slipped frame beyond pinch-off .48
    r.frame(grab())
    r.frame(grab(mid=.45))                              # inside the hysteresis
    assert r.count(K.LEFT_UP) == 0
    for _ in range(4):                                  # the middle tip opens, index still pinched
        r.frame(grab(mid=1.0))
    assert r.count(K.LEFT_UP) == 1
    release_left(r)                                     # the index release adds no click
    assert r.count(K.LEFT_CLICK) == r.count(K.RIGHT_CLICK) == 0 and r.count(K.LEFT_DOWN) == 1


@MODES
def test_grab_opening_before_the_confirm_time_does_nothing_and_says_why(rel):
    r = rig(rel)
    start_grab(r, 34)
    open_all(r)
    assert r.count(K.LEFT_DOWN) == r.count(K.LEFT_CLICK) == r.count(K.RIGHT_CLICK) == 0
    assert last_cancel(r) == "Sürükleme iptal: kavrama tamamlanmadı"


def test_grab_after_the_join_window_does_not_replace_a_decided_left_tap():
    r = rig(False)
    r.frame(mh(idx=.1), events=[(G.PINCH_START, RIGHT)])
    hold_left(r, 100)  # outside the existing 60 ms decision window
    for _ in range(5):
        r.frame(grab())
    release_left(r)
    assert r.count(K.LEFT_CLICK) == 1 and r.count(K.LEFT_DOWN) == 0


@MODES
def test_grab_confirmation_restarts_after_a_brief_contact_loss(rel):
    r = rig(rel)
    start_grab(r, 70)
    r.frame(grab(mid=.6))
    r.frame(grab())
    for _ in range(3):
        r.frame(grab())
    assert r.count(K.LEFT_DOWN) == 0
    r.frame(grab())
    assert r.count(K.LEFT_DOWN) == 1


@MODES
def test_index_distance_uses_grab_release_hysteresis_even_without_an_end_event(rel):
    r = rig(rel)
    start_grab(r)
    r.frame(grab(idx=.6))
    r.frame(grab(idx=.45))
    assert r.count(K.LEFT_UP) == 0
    for _ in range(4):
        r.frame(grab(idx=.6))
    assert r.count(K.LEFT_UP) == 1
    assert r.count(K.LEFT_CLICK) == r.count(K.RIGHT_CLICK) == 0


@pytest.mark.parametrize("failure", ["identity", "ambiguous", "stale", "epoch"])
def test_grab_safety_interruptions_release_without_clicking(failure):
    r = rig(False)
    start_grab(r)
    assert r.count(K.LEFT_DOWN) == 1
    if failure == "identity":
        r.frame(replace(grab(), hand_id=99))
    elif failure == "ambiguous":
        r.frame(grab(), ambiguous=True)
    elif failure == "stale":
        r.frame(grab(), latency=400.0)
    else:
        r.ctl.pause()
    assert released_after_down(r)
    assert r.count(K.LEFT_CLICK) == r.count(K.RIGHT_CLICK) == 0


@MODES
def test_tracking_loss_during_a_grab_releases_at_once_or_within_200_ms(rel):
    r = rig(rel)
    start_grab(r, 200)
    assert r.count(K.LEFT_DOWN) == 1
    r.frame()                                           # hand missing: immediate release
    assert released_after_down(r)
    r = rig(rel)
    start_grab(r, 200)
    last = r.frame(grab())
    held = True
    for _ in range(10):                                 # same hand DEGRADED: tolerated, then watchdog
        t = r.frame(grab(quality=Quality.DEGRADED))
        if released_after_down(r):
            held = False
            break
    assert not held and t - last <= 200.0 + 34.0
    assert r.count(K.LEFT_CLICK) == r.count(K.RIGHT_CLICK) == 0


# ---------------------------------------------------------------- grab vs fist


def test_grab_with_all_five_bent_but_not_fully_curled_is_not_a_fist():
    r = rig(False)                                      # rig() held the hand open: fist armed
    r.frame(grab(all_bent=True, curl=.6), events=[(G.PINCH_START, RIGHT)])
    for _ in range(20):                                 # 670 ms, past the 350 ms fist time
        r.frame(grab(all_bent=True, curl=.6))
    assert r.count(K.LEFT_DOWN) == 1 and r.count(K.WINDOW_MINIMIZE) == 0
    open_all(r)
    assert r.count(K.LEFT_UP) == 1


def test_fist_with_the_thumb_on_both_tips_minimizes_and_never_grabs():
    r = rig(False)
    r.frame(grab(all_bent=True, curl=.95, idx=.2, mid=.2), events=[(G.PINCH_START, RIGHT)])
    for _ in range(14):
        r.frame(grab(all_bent=True, curl=.95, idx=.2, mid=.2))
    assert r.count(K.WINDOW_MINIMIZE) == 1
    assert r.count(K.LEFT_DOWN) == r.count(K.LEFT_CLICK) == r.count(K.RIGHT_CLICK) == 0


def test_fully_curled_index_and_middle_without_a_full_fist_is_no_grab():
    r = rig(False)
    r.frame(grab(curl=.9), events=[(G.PINCH_START, RIGHT)])
    for _ in range(8):
        r.frame(grab(curl=.9))
    assert r.count(K.LEFT_DOWN) == 0
