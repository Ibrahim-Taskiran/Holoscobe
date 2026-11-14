"""Relative pointer (default): palm anchor, clutch, acceleration, monitor clamping, and the pinch
click fixes (flicker re-arm, hold time, pinch-vs-fist, closest finger) at 30 and 10 FPS.
Synthetic HandFeatures; pinch events are injected, thumb+middle is measured from landmarks 4/12."""
from __future__ import annotations

import math

import pytest
from ctrl_helpers import LEFT, RIGHT, G, K, Rig, W

from handcontrol.contracts import (FingerInfo, FingerName, FingerState, HandFeatures, Handedness, Landmark, Mode,
                                   Quality)
from handcontrol.controller import ControllerConfig
from handcontrol.dryrun import make_monitor
from handcontrol.mapping import contains

FPS = pytest.mark.parametrize("dt", [33.4, 100.0], ids=["30fps", "10fps"])
SCALE = 60.0
E, B, U = FingerState.EXTENDED, FingerState.BENT, FingerState.UNKNOWN
_ORDER = (FingerName.THUMB, FingerName.INDEX, FingerName.MIDDLE, FingerName.RING, FingerName.LITTLE)
POSES = {
    "point": (B, E, B, B, B),
    "open": (E, E, E, E, E),
    "closed": (B, B, B, B, B),     # pinch3 / fist: told apart by index curl and pinch distance
}
TWO = [make_monitor(0, 0, 1920, 1080, primary=True), make_monitor(1920, 0, 1920, 1080)]


def rh(palm=(320.0, 300.0), pose="point", *, idx: float = 1.0, mid: float = 1.5, hid: int = RIGHT,
       states=None, index_curl=None, handed=None, quality=Quality.USABLE) -> HandFeatures:
    st = states if states is not None else POSES[pose]
    fingers = tuple(FingerInfo(n, s, index_curl if (n is FingerName.INDEX and index_curl is not None) else 0.95 if s is B else 0.1)
                    for n, s in zip(_ORDER, st))
    lms = [Landmark(0.5, 0.5)] * 21
    lms[12] = Landmark(0.5 + mid * SCALE / W, 0.5)
    if handed is None:
        handed = Handedness.RIGHT if hid == RIGHT else Handedness.LEFT
    return HandFeatures(hand_id=hid, handedness=handed, quality=quality, palm_center_px=palm, palm_scale_px=SCALE,
                        fingers=fingers, pinch_distance=idx, index_tip_px=(palm[0], palm[1] - 60.0),
                        landmarks=tuple(lms))


def rcfg(**kw) -> ControllerConfig:
    base = dict(mirror=False)   # relative pointer and pinch mouse are the defaults
    base.update(kw)
    return ControllerConfig(**base)


def rig(dt: float = 33.4, monitors=None, cursor_source=None, pose="point", palm=(320.0, 300.0), **kw) -> Rig:
    r = Rig(cfg=rcfg(**kw), monitors=monitors, cursor_source=cursor_source)
    r.settle(rh(palm, pose))
    hold(r, palm, 150, dt, pose)        # pose debounce: engaged (pointing) or clutched (open)
    r.sink.clear()
    return r


def ptr(r: Rig):
    return r.ctl.snapshot().pointer


def hold(r: Rig, palm, ms: float, dt: float, pose="point", **kw) -> None:
    for _ in range(max(1, int(round(ms / dt)))):
        r.frame(rh(palm, pose, **kw), dt=dt)


def stroke(r: Rig, a, b, ms: float, dt: float, pose="point", **kw):
    """Raised-cosine velocity profile from palm a to palm b; returns b."""
    n = max(1, int(round(ms / dt)))
    for k in range(1, n + 1):
        u = k / n
        s = u - math.sin(2 * math.pi * u) / (2 * math.pi)
        r.frame(rh((a[0] + (b[0] - a[0]) * s, a[1] + (b[1] - a[1]) * s), pose, **kw), dt=dt)
    return b


def swipe_right(r: Rig, dt: float, px: float = 160.0, ms: float = 200.0, y: float = 300.0, x0: float = 240.0) -> None:
    """One brisk pointing stroke, then clutch (open hand) and bring the hand back."""
    stroke(r, (x0, y), (x0 + px, y), ms, dt)
    hold(r, (x0 + px, y), 150, dt, "open")
    stroke(r, (x0 + px, y), (x0, y), 300, dt, "open")
    hold(r, (x0, y), 150, dt)


def swipe_left(r: Rig, dt: float, px: float = 160.0, ms: float = 200.0, y: float = 300.0, x0: float = 400.0) -> None:
    stroke(r, (x0, y), (x0 - px, y), ms, dt)
    hold(r, (x0 - px, y), 150, dt, "open")
    stroke(r, (x0 - px, y), (x0, y), 300, dt, "open")
    hold(r, (x0, y), 150, dt)


# ---------------------------------------------------------------- motion


def test_defaults_are_relative_with_new_click_timings():
    c = ControllerConfig()
    assert c.pointer_relative is True and c.pointer_speed == 1.0 and c.monitor_mode == "virtual_desktop"
    assert c.tap_max_ms == 1500.0 and c.clutch_debounce_ms == 100.0
    assert c.rel_min_gain < c.rel_max_gain and c.rel_dead_zone > 0


@FPS
def test_start_at_primary_centre_without_a_cursor_source(dt):
    r = rig(dt, monitors=TWO)
    assert ptr(r) == (960, 540)
    assert r.count(K.MOVE_POINTER) == 0


@FPS
def test_still_hand_with_jitter_keeps_the_cursor_still(dt):
    r = rig(dt)
    for k in range(40):
        j = 0.8 if k % 2 else -0.8
        r.frame(rh((320.0 + j, 300.0 - j)), dt=dt)
    assert r.count(K.MOVE_POINTER) == 0


@FPS
def test_slow_and_fast_motion_use_different_gains(dt):
    r = rig(dt, palm=(200.0, 300.0))
    p0 = ptr(r)
    stroke(r, (200.0, 300.0), (232.0, 300.0), 1000, dt)          # 0.05 frame widths, slowly
    p1 = ptr(r)
    hold(r, (232.0, 300.0), 150, dt, "open")
    stroke(r, (232.0, 300.0), (200.0, 300.0), 300, dt, "open")
    hold(r, (200.0, 300.0), 150, dt)
    assert ptr(r) == p1                                           # clutched return moved nothing
    stroke(r, (200.0, 300.0), (232.0, 300.0), 100, dt)            # same distance, briskly
    p2 = ptr(r)
    slow, fast = p1[0] - p0[0], p2[0] - p1[0]
    assert 20 < slow < 120                                        # precise: ~1.8 px per camera px
    assert fast > 2.5 * slow
    assert p0[1] == p1[1] == p2[1]


@FPS
def test_mirror_flips_relative_direction(dt):
    r = rig(dt, mirror=True)
    p0 = ptr(r)
    stroke(r, (320.0, 300.0), (380.0, 300.0), 300, dt)
    assert ptr(r)[0] < p0[0]


@FPS
@pytest.mark.parametrize("clutch", ["open_hand", "hand_lost", "out_of_frame"])   # unknown: test_ctrl_sticky.py
def test_clutch_freezes_and_reengage_continues_without_jump(dt, clutch):
    r = rig(dt, palm=(300.0, 300.0))
    stroke(r, (300.0, 300.0), (360.0, 300.0), 300, dt)
    p = ptr(r)
    assert p[0] > 960
    n = r.count(K.MOVE_POINTER)
    if clutch == "open_hand":
        hold(r, (360.0, 300.0), 150, dt, "open")
        stroke(r, (360.0, 300.0), (250.0, 200.0), 300, dt, "open")
    elif clutch == "hand_lost":
        for _ in range(3):
            r.frame(dt=dt)
    else:
        stroke(r, (360.0, 300.0), (636.0, 300.0), 200, dt)        # palm runs off the right edge
        p = ptr(r)
        n = r.count(K.MOVE_POINTER)
        hold(r, (636.0, 250.0), 200, dt)
        r.frame(rh((250.0, 200.0)), dt=dt)                         # comes back in elsewhere
    assert ptr(r) == p and r.count(K.MOVE_POINTER) == n
    hold(r, (250.0, 200.0), 150, dt)                              # re-engage: no jump
    assert ptr(r) == p and r.count(K.MOVE_POINTER) == n
    stroke(r, (250.0, 200.0), (210.0, 200.0), 200, dt)
    q = ptr(r)
    assert q[0] < p[0] and abs(q[1] - p[1]) <= 1


@FPS
def test_pointing_with_the_thumb_tucked_on_the_middle_finger_moves_after_an_open_hand(dt):
    """The tucked thumb reads as a thumb+middle pinch; it must not clutch the pointing pose."""
    r = rig(dt, pose="open")
    hold(r, (300.0, 300.0), 150, dt, mid=0.15)
    p = ptr(r)
    stroke(r, (300.0, 300.0), (340.0, 300.0), 300, dt, mid=0.15)
    assert ptr(r)[0] > p[0] and r.count(K.RIGHT_CLICK) == 0


@FPS
def test_pose_flicker_neither_freezes_nor_jerks(dt):
    r = rig(dt, palm=(200.0, 300.0))
    xs = []
    for k in range(1, 16):
        pose = "open" if k == 7 else "point"                        # one-frame flicker mid-stroke
        r.frame(rh((200.0 + 4.0 * k, 300.0), pose), dt=dt)
        xs.append(ptr(r)[0])
    steps = [b - a for a, b in zip(xs, xs[1:])]
    assert all(s >= 0 for s in steps)
    assert steps[6] > 0                                            # still moving through the flicker frame
    assert max(steps) < 4 * max(1, sorted(steps)[len(steps) // 2]) + 10


@FPS
def test_short_strokes_with_clutch_travel_across_two_monitors(dt):
    r = rig(dt, monitors=TWO, palm=(240.0, 300.0))
    assert ptr(r) == (960, 540)
    swipe_right(r, dt)
    assert ptr(r)[0] >= 1920                                       # a brisk quarter frame crosses a monitor
    swipe_right(r, dt)
    swipe_right(r, dt)
    assert ptr(r)[0] == 3839                                       # clamped at the right edge
    for _ in range(4):
        swipe_left(r, dt)
    assert ptr(r)[0] == 0
    ys = {a.y for a in r.sink.of(K.MOVE_POINTER)}
    assert ys == {540}


@FPS
def test_vertical_clamp_at_the_top_and_bottom(dt):
    r = rig(dt, palm=(320.0, 100.0))
    stroke(r, (320.0, 100.0), (320.0, 300.0), 150, dt)
    hold(r, (320.0, 300.0), 150, dt, "open")
    stroke(r, (320.0, 300.0), (320.0, 100.0), 300, dt, "open")
    hold(r, (320.0, 100.0), 150, dt)
    stroke(r, (320.0, 100.0), (320.0, 300.0), 150, dt)
    assert ptr(r)[1] == 1079
    stroke(r, (320.0, 300.0), (320.0, 100.0), 150, dt)            # reversing responds at once
    assert ptr(r)[1] < 1079


@FPS
def test_crossing_a_gap_between_monitors_and_back(dt):
    mons = [make_monitor(0, 0, 1920, 1080, primary=True), make_monitor(2000, 0, 1920, 1080)]
    r = rig(dt, monitors=mons, palm=(240.0, 300.0))
    for _ in range(2):
        swipe_right(r, dt)
    assert ptr(r)[0] >= 2000
    for _ in range(2):
        swipe_left(r, dt)
    assert ptr(r)[0] < 1920
    assert all(any(contains(m.bounds, a.x, a.y) for m in mons) for a in r.sink.of(K.MOVE_POINTER))


@FPS
def test_monitors_of_different_heights_keep_real_pixels(dt):
    mons = [make_monitor(0, 0, 1920, 1080, primary=True), make_monitor(1920, 0, 1920, 1440)]
    once = iter([(2600, 1400)])                                    # start there, no later re-sync
    r = rig(dt, monitors=mons, cursor_source=lambda: next(once, None), palm=(400.0, 300.0))
    assert ptr(r) == (2600, 1400)
    for _ in range(2):
        swipe_left(r, dt)
    p = ptr(r)
    assert p[0] < 1920 and p[1] == 1079                            # slid onto the shorter monitor's edge
    stroke(r, (400.0, 300.0), (400.0, 280.0), 150, dt)             # small upward move: responds at once
    assert ptr(r)[1] < 1079
    assert all(any(contains(m.bounds, a.x, a.y) for m in mons) for a in r.sink.of(K.MOVE_POINTER))


def _travel(dt: float, speed: float) -> int:
    r = rig(dt, palm=(200.0, 300.0), pointer_speed=speed)
    p0 = ptr(r)
    stroke(r, (200.0, 300.0), (260.0, 300.0), 400, dt)
    return ptr(r)[0] - p0[0]


@FPS
def test_pointer_speed_scales_travel(dt):
    base = _travel(dt, 1.0)
    assert 1.85 <= _travel(dt, 2.0) / base <= 2.15
    assert 0.45 <= _travel(dt, 0.5) / base <= 0.55
    assert _travel(dt, 9.0) == _travel(dt, 2.0)                     # clamped to 0.5..2.0


@FPS
def test_cursor_source_sets_start_and_resyncs_on_reengage(dt):
    real = [(100, 200)]
    r = rig(dt, cursor_source=lambda: real[0])
    assert ptr(r) == (100, 200)
    hold(r, (320.0, 300.0), 300, dt, "open")                         # release needs clutch_release_ms
    real[0] = (1500, 900)                                          # the physical mouse moved meanwhile
    hold(r, (320.0, 300.0), 150, dt)
    assert ptr(r) == (1500, 900)
    stroke(r, (320.0, 300.0), (350.0, 300.0), 200, dt)
    assert ptr(r)[0] > 1500
    assert r.count(K.MOVE_POINTER) > 0


@FPS
def test_fist_never_moves_the_cursor(dt):
    r = rig(dt, palm=(300.0, 300.0))
    stroke(r, (300.0, 300.0), (400.0, 300.0), 300, dt, "closed", index_curl=0.95)
    assert r.count(K.MOVE_POINTER) == 0


# ---------------------------------------------------------------- left click


def _tap(r: Rig, dt: float, ms: float, palm=(320.0, 300.0), pose="point", **kw) -> None:
    r.frame(rh(palm, pose, idx=0.1, **kw), events=[(G.PINCH_START, RIGHT)], dt=dt)
    hold(r, palm, ms - dt, dt, pose, idx=0.1, **kw)
    r.frame(rh(palm, pose, idx=1.0, **kw), events=[(G.PINCH_END, RIGHT)], dt=dt)


@FPS
def test_threshold_flicker_gives_exactly_one_click(dt):
    r = rig(dt)
    p = ptr(r)
    r.frame(rh(idx=0.2), events=[(G.PINCH_START, RIGHT)], dt=dt)
    r.frame(rh(idx=0.2), dt=dt)
    r.frame(rh(idx=0.45), events=[(G.PINCH_END, RIGHT)], dt=dt)     # distance bounced just over off
    r.frame(rh(idx=0.45), dt=dt)
    r.frame(rh(idx=0.2), events=[(G.PINCH_START, RIGHT)], dt=dt)    # ... and closed again
    hold(r, (320.0, 300.0), 100, dt, idx=0.2)
    r.frame(rh(idx=1.0), events=[(G.PINCH_END, RIGHT)], dt=dt)
    hold(r, (320.0, 300.0), 300, dt)
    clicks = r.sink.of(K.LEFT_CLICK)
    assert len(clicks) == 1 and (clicks[0].x, clicks[0].y) == p
    assert r.count(K.LEFT_DOWN) == 0


@FPS
def test_deliberate_double_pinch_clicks_twice_at_one_point(dt):
    r = rig(dt)
    p = ptr(r)
    _tap(r, dt, dt)
    hold(r, (320.0, 300.0), dt, dt, idx=1.0)                      # fingers clearly apart in between
    _tap(r, dt, dt)
    clicks = r.sink.of(K.LEFT_CLICK)
    assert len(clicks) == 2 and {(c.x, c.y) for c in clicks} == {p}
    assert clicks[1].capture_ms - clicks[0].capture_ms < 500


@FPS
def test_slow_pinch_clicks_and_a_still_hold_never_drags(dt):
    # Round 6: a still 1 s hold is a click on release (was: LEFT_DOWN after 480 ms).
    r = rig(dt)
    _tap(r, dt, 400)
    assert r.kinds() == [K.LEFT_CLICK]
    hold(r, (320.0, 300.0), 400, dt)
    r.sink.clear()
    r.frame(rh(idx=0.1), events=[(G.PINCH_START, RIGHT)], dt=dt)
    hold(r, (320.0, 300.0), 1000, dt, idx=0.1)
    assert r.kinds() == []
    r.frame(rh(idx=1.0), events=[(G.PINCH_END, RIGHT)], dt=dt)
    assert r.kinds() == [K.LEFT_CLICK]


@FPS
def test_pinch_with_three_fingers_bent_clicks_and_never_minimizes(dt):
    r = rig(dt, pose="open")                                       # open hand arms the fist gesture
    p = ptr(r)
    _tap(r, dt, 420, pose="closed", index_curl=0.6)                # all five read BENT, held > fist time
    hold(r, (320.0, 300.0), 300, dt, "open")
    assert r.count(K.WINDOW_MINIMIZE) == 0
    clicks = r.sink.of(K.LEFT_CLICK)
    assert len(clicks) == 1 and (clicks[0].x, clicks[0].y) == p


@FPS
def test_real_fist_still_minimizes(dt):
    r = rig(dt, pose="open")
    hold(r, (320.0, 300.0), 600, dt, "closed", idx=0.37, index_curl=0.95)   # tips close, index fully curled
    hold(r, (320.0, 300.0), 300, dt, "open")
    assert r.count(K.WINDOW_MINIMIZE) == 1
    assert r.count(K.LEFT_CLICK) == 0 and r.count(K.LEFT_DOWN) == 0 and r.count(K.MOVE_POINTER) == 0


@FPS
def test_real_fist_cancels_a_running_tap(dt):
    r = rig(dt, pose="open")
    r.frame(rh(pose="open", idx=0.2), events=[(G.PINCH_START, RIGHT)], dt=dt)
    hold(r, (320.0, 300.0), 200, dt, "closed", idx=0.37, index_curl=0.95)
    r.frame(rh(pose="open"), events=[(G.PINCH_END, RIGHT)], dt=dt)
    hold(r, (320.0, 300.0), 300, dt, "open")
    assert r.count(K.LEFT_CLICK) == 0 and r.count(K.LEFT_DOWN) == 0


@FPS
def test_curled_fingers_left_after_a_pinch_do_not_minimize(dt):
    """Pinch with three fingers bent, release the thumb but keep the fingers curled: no fist."""
    r = rig(dt, pose="open")
    _tap(r, dt, 200, pose="closed", index_curl=0.6)
    hold(r, (320.0, 300.0), 600, dt, "closed", index_curl=0.6)
    assert r.count(K.LEFT_CLICK) == 1 and r.count(K.WINDOW_MINIMIZE) == 0


@FPS
def test_cursor_stays_still_during_a_tap_and_after_it(dt):
    r = rig(dt)
    p = ptr(r)
    r.frame(rh(idx=0.1), events=[(G.PINCH_START, RIGHT)], dt=dt)
    stroke(r, (320.0, 300.0), (335.0, 310.0), 200, dt, idx=0.1)     # hand drifts 0.3 palm units
    r.frame(rh((335.0, 310.0)), events=[(G.PINCH_END, RIGHT)], dt=dt)
    hold(r, (335.0, 310.0), 200, dt)
    assert r.kinds() == [K.LEFT_CLICK]
    c = r.sink.of(K.LEFT_CLICK)[0]
    assert (c.x, c.y) == p == ptr(r)


@FPS
def test_drag_follows_the_anchor_whatever_the_fingers_do(dt):
    r = rig(dt)
    p = ptr(r)
    r.frame(rh(idx=0.1), events=[(G.PINCH_START, RIGHT)], dt=dt)
    stroke(r, (320.0, 300.0), (360.0, 300.0), 200, dt, idx=0.1)     # 0.67 palm units: the drag starts
    assert r.kinds()[0] is K.LEFT_DOWN
    stroke(r, (360.0, 300.0), (420.0, 300.0), 300, dt, "open", idx=0.1)
    stroke(r, (420.0, 300.0), (440.0, 300.0), 100, dt, states=(U, U, U, U, U), idx=0.1)
    r.frame(rh((440.0, 300.0), idx=1.0), events=[(G.PINCH_END, RIGHT)], dt=dt)
    moves = r.sink.of(K.MOVE_POINTER)
    assert len(moves) >= 3 and moves[-1].x > p[0] + 100
    up = r.sink.of(K.LEFT_UP)[0]
    assert (up.x, up.y) == (moves[-1].x, moves[-1].y)
    assert r.count(K.LEFT_CLICK) == 0


def test_fast_motion_during_tap_candidate_starts_a_drag_with_its_travel():
    r = rig()
    p = ptr(r)
    r.frame(rh(idx=0.1), events=[(G.PINCH_START, RIGHT)])
    r.frame(rh((340.0, 300.0), idx=0.1))                            # 0.33 palm units: still a candidate
    r.frame(rh((360.0, 300.0), idx=0.1))                            # 0.67 palm units: drag
    ks = r.kinds()
    assert ks[0] is K.LEFT_DOWN and K.MOVE_POINTER in ks
    assert r.sink.of(K.LEFT_DOWN)[0].x == p[0] and ptr(r)[0] > p[0]


@FPS
def test_left_hand_pinch_never_clicks(dt):
    r = rig(dt)
    left = rh((480.0, 300.0), "open", hid=LEFT)
    hold_two = lambda ms, **kw: [r.frame(rh(), rh((480.0, 300.0), "open", hid=LEFT, **kw), dt=dt)
                                 for _ in range(max(1, int(ms / dt)))]
    hold_two(200)
    r.frame(rh(), left, events=[(G.PINCH_START, LEFT)], dt=dt)
    hold_two(200, idx=0.1)
    r.frame(rh(), left, events=[(G.PINCH_END, LEFT)], dt=dt)
    hold_two(200)
    assert set(r.kinds()) <= {K.MOVE_POINTER}


# ---------------------------------------------------------------- right click


def _right_tap(r: Rig, dt: float, pose="open", states=None, palm=(320.0, 300.0)) -> None:
    for d in (1.0, 0.2, 0.15, 0.15, 0.15)[: (3 if dt > 50 else 5)]:
        r.frame(rh(palm, pose, mid=d, states=states), dt=dt)
    for d in (0.6, 0.8, 1.0, 1.2):
        r.frame(rh(palm, pose, mid=d, states=states), dt=dt)


@FPS
def test_right_click_from_an_open_hand(dt):
    r = rig(dt, pose="open")
    p = ptr(r)
    _right_tap(r, dt)
    clicks = r.sink.of(K.RIGHT_CLICK)
    assert len(clicks) == 1 and (clicks[0].x, clicks[0].y) == p
    assert r.count(K.LEFT_CLICK) == 0 and r.count(K.MOVE_POINTER) == 0


@FPS
@pytest.mark.parametrize("states", [(B, E, B, B, U), (B, U, B, E, E), (E, E, B, B, E)],
                         ids=["ring_bent_little_unknown", "index_unknown", "index_extended_ring_bent"])
def test_right_click_tolerates_unsure_fingers_right_after_an_open_hand(dt, states):
    r = rig(dt, pose="open")
    _right_tap(r, dt, states=states)
    assert r.count(K.RIGHT_CLICK) == 1


@FPS
def test_unsure_right_pose_without_a_recent_open_hand_does_not_click(dt):
    r = rig(dt, pose="point")
    hold(r, (320.0, 300.0), 600, dt)
    _right_tap(r, dt, states=(B, E, B, B, U))
    assert r.count(K.RIGHT_CLICK) == 0


@FPS
def test_right_click_from_an_extended_index_with_outer_fingers_open(dt):
    r = rig(dt, pose="point")
    hold(r, (320.0, 300.0), 600, dt)
    _right_tap(r, dt, states=(B, E, B, E, E))
    assert r.count(K.RIGHT_CLICK) == 1


@FPS
def test_right_click_flicker_gives_one_click(dt):
    r = rig(dt, pose="open")
    n = 2 if dt > 50 else 4
    for d in (0.15,) * n + (0.5,) * n + (0.15,) * n + (1.2,) * 6:  # reopened only to 0.5 pu, briefly
        r.frame(rh(pose="open", mid=d), dt=dt)
    assert r.count(K.RIGHT_CLICK) == 1


@FPS
@pytest.mark.parametrize("case", ["pointing", "fist", "left_hand", "clap", "entering"])
def test_no_right_click_from_unsafe_poses(dt, case):
    if case == "entering":
        r = Rig(cfg=rcfg())
        r.settle(rh(pose="open", mid=0.1))
        hold(r, (320.0, 300.0), 300, dt, "open", mid=1.2)
        assert r.count(K.RIGHT_CLICK) == 0
        return
    r = rig(dt, pose="open")
    if case == "pointing":
        hold(r, (320.0, 300.0), 600, dt)
        for _ in range(6):
            r.frame(rh(mid=0.15), dt=dt)
        hold(r, (320.0, 300.0), 300, dt, mid=1.2)
    elif case == "fist":
        _right_tap(r, dt, pose="closed")
    elif case == "left_hand":
        for d in (1.0, 0.15, 0.15, 0.15, 0.15, 0.6, 1.0, 1.2):
            r.frame(rh((480.0, 300.0), "open", mid=d, hid=LEFT), dt=dt)
    else:
        for d in (1.0, 0.15, 0.15):
            r.frame(rh(pose="open", mid=d), dt=dt)
        r.frame(rh(pose="open", mid=0.15), events=[(G.CLAP_CANDIDATE_START,)], dt=dt)
        for d in (0.15, 0.6, 1.0, 1.2):
            r.frame(rh(pose="open", mid=d), dt=dt)
    assert r.count(K.RIGHT_CLICK) == 0


# ---------------------------------------------------------------- other modes


@FPS
def test_window_drag_follows_the_anchor_in_relative_mode(dt):
    r = rig(dt)
    r.ctl.set_mode(Mode.WINDOWS)
    r.settle(rh())
    p = ptr(r)
    r.frame(rh(idx=0.1), events=[(G.PINCH_START, RIGHT)], dt=dt)
    hold(r, (320.0, 300.0), 300, dt, idx=0.1)
    assert r.kinds() == [K.WINDOW_DRAG_BEGIN]
    b = r.sink.of(K.WINDOW_DRAG_BEGIN)[0]
    assert (b.x, b.y) == p
    stroke(r, (320.0, 300.0), (380.0, 300.0), 300, dt, idx=0.1)
    r.frame(rh((380.0, 300.0)), events=[(G.PINCH_END, RIGHT)], dt=dt)
    moves = r.sink.of(K.WINDOW_DRAG_MOVE)
    assert moves and moves[-1].x > p[0] and r.kinds()[-1] is K.WINDOW_DRAG_END


@FPS
def test_pointer_moves_in_scroll_mode_and_freezes_while_scrolling(dt):
    r = rig(dt)
    r.ctl.set_mode(Mode.SCROLL)
    r.settle(rh())
    hold(r, (320.0, 300.0), 150, dt)
    stroke(r, (320.0, 300.0), (360.0, 300.0), 200, dt)
    assert r.count(K.MOVE_POINTER) > 0
    n = r.count(K.MOVE_POINTER)
    r.frame(rh((360.0, 300.0), idx=0.1), events=[(G.PINCH_START, RIGHT)], dt=dt)
    stroke(r, (360.0, 300.0), (360.0, 200.0), 300, dt, idx=0.1)
    assert r.count(K.MOVE_POINTER) == n and r.count(K.SCROLL) > 0
