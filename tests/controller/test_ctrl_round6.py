"""Round 6 click rules from the 2026-11-14 session: drag starts on palm travel only, a still pinch
released before the round 7 long press (800 ms) clicks, quick double taps re-arm, right pinches tolerate long holds, curl flicker and short
DEGRADED spans, and refused pinch starts leave a last_cancel reason. Absolute and relative pointer."""
from __future__ import annotations

from dataclasses import replace

import pytest
from ctrl_helpers import RIGHT, G, K, Rig, tcfg
from test_ctrl_pinch_mouse import PALM, mh, tap

from handcontrol.contracts import Quality

MODES = pytest.mark.parametrize("rel", [False, True], ids=["absolute", "relative"])


def rig(rel: bool) -> Rig:
    r = Rig(cfg=tcfg(pinch_mouse=True, pointer_relative=rel))
    r.settle(mh())
    for _ in range(8):
        r.frame(mh())
    r.sink.clear()
    return r


def hold_left(r: Rig, ms: float, palm=PALM, dt: float = 33.4) -> None:
    for _ in range(int(ms / dt)):
        r.frame(mh(palm=palm, idx=.1, bent="i"), dt=dt)


def release_left(r: Rig, palm=PALM) -> None:
    r.frame(mh(palm=palm), events=[(G.PINCH_END, RIGHT)])
    for _ in range(3):
        r.frame(mh(palm=palm))


def right_frames(r: Rig, n: int, *, bent: str = "m", dt: float = 33.4, **kw) -> None:
    for _ in range(n):
        r.frame(mh(mid=.1, bent=bent, **kw), dt=dt)


def right_release(r: Rig) -> None:
    for _ in range(5):
        r.frame(mh(mid=1.2))


def last_cancel(r: Rig) -> str:
    return r.ctl.snapshot().last_cancel


# ---------------------------------------------------------------- left: click vs drag


@MODES
@pytest.mark.parametrize("ms", [300, 500, 650])   # round 7: was 600/1000/1400; 800 ms is the long press
def test_still_pinch_up_to_the_limit_clicks_at_the_latched_point(rel, ms):
    r = rig(rel)
    p = r.ctl.snapshot().pointer
    r.frame(mh(idx=.1, bent="i"), events=[(G.PINCH_START, RIGHT)])
    hold_left(r, ms)
    assert r.count(K.LEFT_DOWN) == 0
    release_left(r)
    clicks = r.sink.of(K.LEFT_CLICK)
    assert len(clicks) == 1 and (clicks[0].x, clicks[0].y) == p
    assert r.count(K.LEFT_DOWN) == r.count(K.RIGHT_CLICK) == 0


@MODES
def test_resting_hand_drift_below_the_threshold_still_clicks(rel):
    """Still holds of the session drifted up to 0.39 palm units; 0.5 pu (30 px) must not drag.
    Round 7: the drift is made within 670 ms (was 1 s), under the 800 ms long press."""
    r = rig(rel)
    r.frame(mh(idx=.1, bent="i"), events=[(G.PINCH_START, RIGHT)])
    for k in range(20):
        r.frame(mh(palm=(PALM[0] + 1.5 * k, PALM[1]), idx=.1, bent="i"))
    release_left(r, (PALM[0] + 28.5, PALM[1]))
    assert r.count(K.LEFT_CLICK) == 1 and r.count(K.LEFT_DOWN) == 0


@MODES
def test_too_long_still_pinch_is_a_long_press_and_later_travel_does_not_drag(rel):
    """Round 7 (was: 1.7 s still pinch cancelled "uzun tutuldu", travel after it dragged): the
    still pinch right-clicks at 800 ms, the release adds nothing, travel after it never drags;
    travel before 800 ms still drags and then never right-clicks."""
    r = rig(rel)
    r.frame(mh(idx=.1, bent="i"), events=[(G.PINCH_START, RIGHT)])
    hold_left(r, 1700)
    for k in range(1, 7):
        r.frame(mh(palm=(PALM[0] + 10 * k, PALM[1]), idx=.1, bent="i"))
    release_left(r, (PALM[0] + 60, PALM[1]))
    assert r.count(K.RIGHT_CLICK) == 1
    assert r.count(K.LEFT_CLICK) == r.count(K.LEFT_DOWN) == 0
    assert last_cancel(r) == ""
    for _ in range(25):          # reopen wide, then a pinch with early travel drags
        r.frame(mh())
    r.frame(mh(idx=.1, bent="i"), events=[(G.PINCH_START, RIGHT)])
    hold_left(r, 300)
    for k in range(1, 7):
        r.frame(mh(palm=(PALM[0] + 10 * k, PALM[1]), idx=.1, bent="i"))
    assert r.count(K.LEFT_DOWN) == 1
    hold_left(r, 1500, palm=(PALM[0] + 60, PALM[1]))
    release_left(r, (PALM[0] + 60, PALM[1]))
    assert r.count(K.LEFT_UP) == 1 and r.count(K.LEFT_CLICK) == 0 and r.count(K.RIGHT_CLICK) == 1


# ---------------------------------------------------------------- left: double click


@MODES
@pytest.mark.parametrize("open_frames,clicks", [(9, 2), (12, 2), (3, 1)])
def test_quick_second_tap_after_a_narrow_reopening(rel, open_frames, clicks):
    """Session second taps reopened to 0.53-0.78 pu for 281-485 ms and were all refused; a
    re-contact within 250 ms (flicker: 125-140 ms observed) stays one click."""
    r = rig(rel)
    tap(r, 33.4, idx=.1)
    for _ in range(open_frames):
        r.frame(mh(idx=.6))
    tap(r, 33.4, idx=.1)
    got = r.sink.of(K.LEFT_CLICK)
    assert len(got) == clicks
    assert len({(c.x, c.y) for c in got}) == 1          # same point: Windows forms the double click
    assert r.count(K.LEFT_DOWN) == r.count(K.RIGHT_CLICK) == 0
    if clicks == 1:
        assert last_cancel(r) == "Tıklama iptal: önce parmakları açın"


# ---------------------------------------------------------------- right click


@MODES
@pytest.mark.parametrize("n", [20, 45, 85])     # 0.7 s, 1.5 s, 2.8 s (session holds were 1.6-2.8 s)
def test_long_still_right_pinch_from_an_open_hand_right_clicks(rel, n):
    r = rig(rel)
    p = r.ctl.snapshot().pointer
    right_frames(r, n)
    right_release(r)
    clicks = r.sink.of(K.RIGHT_CLICK)
    assert len(clicks) == 1 and (clicks[0].x, clicks[0].y) == p
    assert r.count(K.LEFT_CLICK) == r.count(K.LEFT_DOWN) == 0


@MODES
def test_right_pinch_over_the_limit_is_cancelled(rel):
    r = rig(rel)
    right_frames(r, 95)                          # 3.2 s
    right_release(r)
    assert r.count(K.RIGHT_CLICK) == 0
    assert last_cancel(r) == "Sağ tık iptal: uzun tutuldu"


@MODES
@pytest.mark.parametrize("flicker", ["rl", "imrl", "tmrl"])
def test_short_finger_state_flicker_during_contact_keeps_the_right_click(rel, flicker):
    r = rig(rel)
    right_frames(r, 5)
    right_frames(r, 2, bent=flicker)            # 67 ms of curled ring+little
    right_frames(r, 4)
    right_release(r)
    assert r.count(K.RIGHT_CLICK) == 1 and r.count(K.LEFT_CLICK) == 0


@MODES
def test_right_pinch_turning_into_the_pointing_pose_never_right_clicks(rel):
    r = rig(rel)
    right_frames(r, 5)
    right_frames(r, 6, bent="tmrl")             # 200 ms curled: going into the pointing pose
    assert last_cancel(r) == "Sağ tık iptal: parmaklar büküldü"
    for _ in range(8):
        r.frame(mh(mid=1.2, bent="tmrl"))
    right_release(r)
    assert r.count(K.RIGHT_CLICK) == r.count(K.LEFT_CLICK) == 0


@MODES
def test_right_release_on_a_curled_frame_never_right_clicks(rel):
    r = rig(rel)
    right_frames(r, 5)
    r.frame(mh(mid=.1, bent="tmrl"))
    for _ in range(4):
        r.frame(mh(mid=1.2, bent="tmrl"), dt=25.0)   # release inside the curl debounce
    right_release(r)
    assert r.count(K.RIGHT_CLICK) == 0


@MODES
def test_pointing_pose_entered_from_an_open_hand_never_right_clicks(rel):
    """Thumb tucked over the curled middle right after the hand was open (open-hand memory)."""
    r = rig(rel)
    for _ in range(3):
        r.frame(mh(mid=.5, bent="rl"))
    for _ in range(30):
        r.frame(mh(mid=.15, bent="tmrl"))
    for _ in range(10):
        r.frame(mh(mid=1.2))
    assert r.count(K.RIGHT_CLICK) == r.count(K.LEFT_CLICK) == 0


@MODES
@pytest.mark.parametrize("gap", [60.0, 120.0, 160.0])   # + 15 ms frame + 5 ms latency < 200 ms
def test_started_right_pinch_survives_short_same_id_degraded_frames(rel, gap):
    r = rig(rel)
    right_frames(r, 5)
    r.frame(replace(mh(mid=.1, bent="m"), quality=Quality.DEGRADED), dt=gap / 2)
    r.frame(replace(mh(mid=.1, bent="m"), quality=Quality.DEGRADED), dt=gap / 2)
    right_frames(r, 2, dt=15.0)
    right_release(r)
    assert r.count(K.RIGHT_CLICK) == 1 and r.count(K.RELEASE_ALL) == 0


@MODES
def test_right_pinch_closing_through_a_degraded_frame_still_starts(rel):
    r = rig(rel)
    r.frame(mh(mid=.2, bent="m"))                              # contact begins (debounce running)
    r.frame(replace(mh(mid=.1, bent="m"), quality=Quality.DEGRADED), dt=60.0)
    right_frames(r, 4)
    right_release(r)
    assert r.count(K.RIGHT_CLICK) == 1 and r.count(K.LEFT_CLICK) == 0


@MODES
def test_degraded_span_at_the_loss_timeout_still_resets(rel):
    r = rig(rel)
    r.frame(mh(mid=.2, bent="m"))
    for _ in range(4):
        r.frame(replace(mh(mid=.1, bent="m"), quality=Quality.DEGRADED), dt=60.0)   # 240 ms
    right_frames(r, 4)
    right_release(r)
    assert r.count(K.RIGHT_CLICK) == 0


@MODES
def test_missing_hand_still_cancels_a_right_pinch_at_once(rel):
    r = rig(rel)
    right_frames(r, 5)
    r.frame()
    right_frames(r, 2)
    right_release(r)
    assert r.count(K.RIGHT_CLICK) == 0
    assert last_cancel(r) == "Sağ tık iptal: takip koptu"


# ---------------------------------------------------------------- refused pinch starts are visible


@MODES
def test_pinch_refused_while_neutral_is_required_leaves_a_reason(rel):
    r = rig(rel)
    r.frame(mh(idx=.1, bent="i"), events=[(G.PINCH_START, RIGHT)])
    r.frame()                                                   # loss: needs a neutral hand again
    r.frame(mh(idx=.1, bent="i"), events=[(G.PINCH_START, RIGHT)])
    assert r.ctl.snapshot().needs_neutral
    assert last_cancel(r) == "Tıklama iptal: takip yeni döndü, eli bir an açık tutun"


@MODES
def test_pinch_start_inside_a_fist_leaves_a_reason(rel):
    r = rig(rel)
    r.frame(mh(idx=.1, bent="timrl"), events=[(G.PINCH_START, RIGHT)])
    assert last_cancel(r) == "Tıklama iptal: yumruk algılandı"
    assert r.count(K.LEFT_CLICK) == 0
