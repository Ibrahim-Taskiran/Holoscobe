"""POINTER pinch mouse: thumb+index tap = LEFT_CLICK, hold = LEFT_DOWN/MOVE/LEFT_UP,
thumb+middle tap = RIGHT_CLICK. Synthetic HandFeatures; left pinch events are injected, the
thumb+middle pinch is measured by the controller from landmarks 4 and 12."""
from __future__ import annotations

from dataclasses import replace

import pytest
from ctrl_helpers import LEFT, RIGHT, G, K, Rig, W, hand, tcfg

from handcontrol.contracts import CameraState, FingerInfo, FingerName, FingerState, Handedness, Landmark, Mode, Quality
from handcontrol.controller import ControllerConfig

FPS = pytest.mark.parametrize("dt", [33.4, 100.0], ids=["30fps", "10fps"])
PALM = (320.0, 300.0)
SCALE = 60.0
_ORDER = (FingerName.THUMB, FingerName.INDEX, FingerName.MIDDLE, FingerName.RING, FingerName.LITTLE)


def mh(tip=(320.0, 240.0), palm=PALM, *, mid: float = 1.5, idx: float = 1.0, hid: int = RIGHT, bent: str = "",
       **kw):
    """Right hand with thumb-middle distance `mid` and thumb-index distance `idx` (palm units).
    `bent`: letters t i m r l."""
    h = hand(hid, tip=tip, palm=palm, scale=SCALE, **kw)
    fingers = tuple(FingerInfo(n, FingerState.BENT, 0.95) if "timrl"[k] in bent else
                    FingerInfo(n, FingerState.EXTENDED, 0.1) for k, n in enumerate(_ORDER))
    lms = [Landmark(0.5, 0.5)] * 21
    lms[12] = Landmark(0.5 + mid * SCALE / W, 0.5)
    return replace(h, fingers=fingers, landmarks=tuple(lms), pinch_distance=idx)


def rig() -> Rig:
    r = Rig(cfg=tcfg(pinch_mouse=True))
    r.settle(mh())
    return r


def pointer_at(r: Rig, tip=(320.0, 240.0), dt: float = 33.4):
    r.frame(mh(tip), dt=dt)
    return r.ctl.snapshot().pointer


def tap(r: Rig, dt: float, frames: int = 2, tip=(330.0, 250.0), **kw) -> None:
    """PINCH_START, `frames` pinched frames (fingertip drifting), PINCH_END."""
    r.frame(mh(tip, **kw), events=[(G.PINCH_START, RIGHT)], dt=dt)
    for k in range(frames):
        r.frame(mh((tip[0] + 3 * k, tip[1] + 5 * k), **kw), dt=dt)
    r.frame(mh(tip, **kw), events=[(G.PINCH_END, RIGHT)], dt=dt)


def released_after_down(r: Rig) -> bool:
    ks = r.kinds()
    i = ks.index(K.LEFT_DOWN)
    return any(k in (K.LEFT_UP, K.RELEASE_ALL) for k in ks[i + 1:])


def test_defaults_pinch_mouse_on_and_depth_tap_off():
    cfg = ControllerConfig()
    assert cfg.pinch_mouse is True and cfg.index_tap_click is False
    assert cfg.mouse_hold_ms == 480.0 and cfg.double_click_window_ms == 500.0


@FPS
def test_tap_clicks_once_at_latched_point_and_pointer_holds(dt):
    r = rig()
    p = pointer_at(r, dt=dt)
    r.sink.clear()
    tap(r, dt)
    assert r.kinds() == [K.LEFT_CLICK]
    c = r.sink.of(K.LEFT_CLICK)[0]
    assert (c.x, c.y) == p


@FPS
def test_two_quick_taps_click_twice_at_the_same_point(dt):
    r = rig()
    p = pointer_at(r, dt=dt)
    tap(r, dt, frames=1)
    r.frame(mh((300.0, 200.0)), dt=dt)      # finger reopens: the pointer moves in between
    tap(r, dt, frames=1, tip=(310.0, 210.0))
    clicks = r.sink.of(K.LEFT_CLICK)
    assert len(clicks) == 2
    assert {(c.x, c.y) for c in clicks} == {p}
    assert r.count(K.DOUBLE_CLICK) == 0     # Windows forms the double click itself


def test_slow_second_tap_uses_its_own_point():
    r = rig()
    pointer_at(r)
    tap(r, 33.4)
    for _ in range(20):
        r.frame(mh((200.0, 150.0)))
    p2 = r.ctl.snapshot().pointer
    tap(r, 33.4, tip=(200.0, 150.0))
    clicks = r.sink.of(K.LEFT_CLICK)
    assert len(clicks) == 2 and (clicks[1].x, clicks[1].y) == p2 != (clicks[0].x, clicks[0].y)


@FPS
def test_hold_drags_with_left_button(dt):
    r = rig()
    p = pointer_at(r, dt=dt)
    r.sink.clear()
    r.frame(mh(), events=[(G.PINCH_START, RIGHT)], dt=dt)
    t = 0.0
    while t < 500:
        r.frame(mh(), dt=dt)
        t += dt
    assert r.kinds() == [K.LEFT_DOWN]
    d = r.sink.of(K.LEFT_DOWN)[0]
    assert (d.x, d.y) == p
    for k in range(1, 6):                    # whole hand moves right
        r.frame(mh((320.0 + 10 * k, 240.0), (320.0 + 10 * k, 300.0)), dt=dt)
    r.frame(mh((370.0, 240.0), (370.0, 300.0)), events=[(G.PINCH_END, RIGHT)], dt=dt)
    ks = r.kinds()
    assert ks[0] is K.LEFT_DOWN and ks[-1] is K.LEFT_UP
    moves = r.sink.of(K.MOVE_POINTER)
    assert len(moves) >= 4 and moves[-1].x > p[0]
    up = r.sink.of(K.LEFT_UP)[0]
    assert (up.x, up.y) == (moves[-1].x, moves[-1].y)
    assert r.count(K.LEFT_CLICK) == 0 and r.count(K.RELEASE_ALL) == 0


def test_hand_motion_during_tap_starts_a_drag_not_a_click():
    r = rig()
    pointer_at(r)
    r.frame(mh(), events=[(G.PINCH_START, RIGHT)])
    r.frame(mh((350.0, 240.0), (350.0, 300.0)))      # 30 px palm travel = 0.5 palm units
    r.frame(mh((355.0, 240.0), (355.0, 300.0)), events=[(G.PINCH_END, RIGHT)])
    assert r.count(K.LEFT_CLICK) == 0
    assert K.LEFT_DOWN in r.kinds() and released_after_down(r)


def _dragging(dt: float = 33.4) -> Rig:
    r = rig()
    pointer_at(r, dt=dt)
    r.frame(mh(), events=[(G.PINCH_START, RIGHT)], dt=dt)
    for _ in range(int(520 / dt) + 1):
        r.frame(mh(), dt=dt)
    assert r.count(K.LEFT_DOWN) == 1
    return r


def _clap(r: Rig) -> None:
    r.frame(mh(), events=[(G.CLAP_CANDIDATE_START,)])


def _watchdog(r: Rig) -> None:
    r.ctl.watchdog.check(r.ctl.watchdog.last_usable_ms + 250.0)


CANCELS = {
    "tracking_loss": lambda r: r.frame(),
    "degraded": lambda r: r.frame(replace(mh(), quality=Quality.DEGRADED)),
    "pause": lambda r: r.ctl.pause(),
    "mode_change": lambda r: r.ctl.set_mode(Mode.SCROLL),
    "identity_ambiguous": lambda r: r.frame(mh(), ambiguous=True),
    "clap_candidate": _clap,
    "stale_sample": lambda r: r.frame(mh(), latency=400.0),
    "hand_change": lambda r: r.frame(mh(hid=7, handed=Handedness.RIGHT)),
    "two_right_hands": lambda r: r.frame(mh(), mh(hid=7, handed=Handedness.RIGHT)),
    "emergency_stop": lambda r: r.ctl.emergency_stop(),
    "watchdog": _watchdog,
    "fist": lambda r: r.frame(mh(bent="timrl")),
    "camera_off": lambda r: r.ctl.set_camera_state(CameraState.OFF),
}


@pytest.mark.parametrize("cancel", sorted(CANCELS))
def test_every_cancel_path_releases_the_left_button(cancel):
    r = _dragging()
    CANCELS[cancel](r)
    if cancel == "degraded":
        # Same-ID degraded samples freeze a drag; the unchanged 200 ms watchdog still releases it.
        assert not released_after_down(r)
        r.ctl.watchdog.check(r.ctl.watchdog.last_usable_ms + 200.0)
    assert released_after_down(r), r.kinds()
    # the pinch release afterwards never re-presses or clicks
    for _ in range(3):
        r.frame(mh(), events=[(G.PINCH_END, RIGHT)])
        r.frame(mh())
    assert r.count(K.LEFT_DOWN) == 1 and r.count(K.LEFT_CLICK) == 0


@pytest.mark.parametrize("cancel", ["tracking_loss", "clap_candidate", "fist", "identity_ambiguous", "hand_change"])
def test_cancel_during_tap_candidate_never_clicks(cancel):
    r = rig()
    pointer_at(r)
    r.frame(mh(), events=[(G.PINCH_START, RIGHT)])
    CANCELS[cancel](r)
    for _ in range(10):
        r.frame(mh())
    r.frame(mh(), events=[(G.PINCH_END, RIGHT)])
    assert r.count(K.LEFT_CLICK) == 0 and r.count(K.LEFT_DOWN) == 0


@FPS
def test_thumb_middle_tap_right_clicks_once(dt):
    r = rig()
    p = pointer_at(r, dt=dt)
    r.sink.clear()
    for d in ((1.0, 0.2, 0.15) if dt > 50 else (1.0, 0.2, 0.15, 0.15, 0.15)):
        r.frame(mh(mid=d), dt=dt)
    for d in (0.6, 0.8, 1.0, 1.2):
        r.frame(mh(mid=d), dt=dt)
    assert r.count(K.RIGHT_CLICK) == 1 and r.count(K.LEFT_CLICK) == 0
    c = r.sink.of(K.RIGHT_CLICK)[0]
    assert (c.x, c.y) == p
    i = r.kinds().index(K.RIGHT_CLICK)
    assert K.MOVE_POINTER not in r.kinds()[:i]        # pointer held while the tap was a candidate


def test_long_thumb_middle_hold_does_not_right_click():
    r = rig()
    pointer_at(r)
    for _ in range(20):
        r.frame(mh(mid=0.1))
    for _ in range(5):
        r.frame(mh(mid=1.2))
    assert r.count(K.RIGHT_CLICK) == 0


def test_pointing_pose_with_thumb_on_middle_never_right_clicks():
    """Pointing pose: thumb tucked over the curled middle finger, ring and little curled."""
    r = rig()
    pointer_at(r)
    for _ in range(3):
        r.frame(mh(mid=0.15, bent="tmrl"))
    for _ in range(5):
        r.frame(mh(mid=1.2))
    assert r.count(K.RIGHT_CLICK) == 0


def test_middle_finger_entering_already_pinched_does_not_fire():
    r = Rig(cfg=tcfg(pinch_mouse=True))
    r.settle(mh(mid=0.1))
    for _ in range(3):
        r.frame(mh(mid=1.2))
    assert r.count(K.RIGHT_CLICK) == 0


def test_decided_pinches_ignore_other_contact_until_release():
    r = rig()
    pointer_at(r)
    # A late overlapping index contact does not replace the already decided right session.
    for _ in range(4):
        r.frame(mh(mid=0.1))
    r.frame(mh(mid=0.1, idx=0.12), events=[(G.PINCH_START, RIGHT)])
    r.frame(mh(mid=0.1, idx=0.12))
    r.frame(mh(mid=1.2), events=[(G.PINCH_END, RIGHT)])
    for _ in range(8):
        r.frame(mh(mid=1.2))
    assert r.count(K.RIGHT_CLICK) == 1 and r.count(K.LEFT_CLICK) == 0
    # thumb+index first, then thumb+middle: index wins, still a single tap
    r.frame(mh(idx=0.1), events=[(G.PINCH_START, RIGHT)])
    for _ in range(4):
        r.frame(mh(mid=0.1, idx=0.1))
    r.frame(mh(mid=1.2), events=[(G.PINCH_END, RIGHT)])
    for _ in range(4):
        r.frame(mh(mid=1.2))
    assert r.count(K.RIGHT_CLICK) == 1
    assert r.count(K.LEFT_CLICK) == 1 and r.count(K.LEFT_DOWN) == 0


def test_same_frame_equal_distances_without_decisive_states_do_not_guess():
    r = rig()
    pointer_at(r)
    r.frame(mh(mid=0.1, idx=0.1))
    r.frame(mh(mid=0.1, idx=0.1), events=[(G.PINCH_START, RIGHT)], dt=100.0)   # middle debounce completes too
    r.frame(mh(mid=0.1, idx=0.1))
    r.frame(mh(mid=1.2), events=[(G.PINCH_END, RIGHT)])
    for _ in range(4):
        r.frame(mh(mid=1.2))
    assert r.count(K.RIGHT_CLICK) == 0 and r.count(K.LEFT_CLICK) == 0
    assert r.count(K.LEFT_DOWN) == 0


@FPS
def test_closest_finger_wins_regardless_of_arrival_order(dt):
    """Thumb clearly on the middle tip: an index PINCH_START in the same moment is not a left click."""
    r = rig()
    pointer_at(r, dt=dt)
    r.sink.clear()
    r.frame(mh(mid=0.1, idx=0.3), events=[(G.PINCH_START, RIGHT)], dt=dt)   # index event first
    for _ in range(3):
        r.frame(mh(mid=0.1, idx=0.3), dt=dt)
    r.frame(mh(mid=1.2, idx=1.0), events=[(G.PINCH_END, RIGHT)], dt=dt)
    for _ in range(4):
        r.frame(mh(mid=1.2), dt=dt)
    assert r.count(K.LEFT_CLICK) == 0 and r.count(K.RIGHT_CLICK) == 1 and r.count(K.LEFT_DOWN) == 0
    # thumb on the index tip with the middle tip nearby but farther: left click only
    for _ in range(4):
        r.frame(mh(), dt=dt)
    for _ in range(3):
        # Finger states select left inside the decision window, even if middle debounce starts first.
        r.frame(mh(mid=0.3, idx=0.4, bent="i"), dt=dt)
    r.frame(mh(mid=0.3, idx=0.05, bent="i"), events=[(G.PINCH_START, RIGHT)], dt=dt)
    r.frame(mh(mid=0.3, idx=0.05, bent="i"), dt=dt)
    r.frame(mh(mid=1.2), events=[(G.PINCH_END, RIGHT)], dt=dt)
    for _ in range(4):
        r.frame(mh(mid=1.2), dt=dt)
    assert r.count(K.LEFT_CLICK) == 1 and r.count(K.RIGHT_CLICK) == 1


def test_left_hand_pinch_never_clicks():
    r = rig()
    left = mh((420.0, 240.0), (420.0, 300.0), hid=LEFT)
    for _ in range(8):
        r.frame(mh(), left)
    r.sink.clear()
    r.frame(mh(), left, events=[(G.PINCH_START, LEFT)])
    for _ in range(15):
        r.frame(mh(), replace(left))
    r.frame(mh(), left, events=[(G.PINCH_END, LEFT)])
    assert set(r.kinds()) <= {K.MOVE_POINTER}


def test_menu_dwell_then_pinch_selects_without_clicking():
    r = rig()
    pointer_at(r)
    r.frame(mh(), events=[(G.MENU_DWELL_COMPLETE,)])
    assert r.ctl.snapshot().menu is not None
    tap(r, 33.4)
    for d in (0.1, 0.1, 0.1, 0.1, 1.2, 1.2, 1.2):
        r.frame(mh(mid=d))
    assert r.count(K.LEFT_CLICK) == 0 and r.count(K.RIGHT_CLICK) == 0 and r.count(K.LEFT_DOWN) == 0


def test_hand_reentering_after_loss_does_not_click():
    r = rig()
    pointer_at(r)
    r.frame(mh(), events=[(G.PINCH_START, RIGHT)])
    for _ in range(3):
        r.frame()
    r.frame(mh(), events=[(G.PINCH_END, RIGHT)])
    for _ in range(10):
        r.frame(mh())
    assert r.count(K.LEFT_CLICK) == 0 and r.count(K.LEFT_DOWN) == 0


def test_other_modes_keep_their_pinch_behavior():
    r = rig()
    r.ctl.set_mode(Mode.SCROLL)
    r.settle(mh())
    tap(r, 33.4)
    assert r.count(K.LEFT_CLICK) == 0 and r.count(K.LEFT_DOWN) == 0


def test_legacy_switch_restores_pinch_release_click_without_drag():
    r = Rig(cfg=tcfg(pinch_mouse=False))
    r.settle(mh())
    r.frame(mh(), events=[(G.PINCH_START, RIGHT)])
    for _ in range(20):
        r.frame(mh())
    r.frame(mh(), events=[(G.PINCH_END, RIGHT)])
    assert r.count(K.LEFT_DOWN) == 0 and r.count(K.LEFT_CLICK) == 0
