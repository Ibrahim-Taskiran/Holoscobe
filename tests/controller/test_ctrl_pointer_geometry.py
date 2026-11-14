"""Bounded pointer continuity for finger-only geometry failures; never gesture recovery."""
from __future__ import annotations

import pytest

from ctrl_helpers import G, K, RIGHT, H, W
from test_ctrl_relative import ptr, rh, rig
from handcontrol.contracts import FrameFeatures, Quality


def geometry_frame(r, x, *, reasons=("bone_ratio",), frame_reasons=(), dt=33.4,
                   latency=5.0, ambiguous=False, events=(), **kw):
    now = r.clock.advance(dt)
    t = now - latency
    h = rh((x, 300.0), quality=Quality.DEGRADED, **kw)
    ff = FrameFeatures(t, t + 2.0, W, H, (h,), ambiguous)
    object.__setattr__(ff, "reasons", ({h.hand_id: reasons}, frame_reasons))
    r.ctl.on_frame(ff, r.ev(events, t))


def test_short_bone_ratio_span_moves_instead_of_freezing_and_reanchoring():
    r = rig(33.4, palm=(300.0, 300.0))
    p = ptr(r)
    for x in (305.0, 310.0, 315.0):
        geometry_frame(r, x)
    assert r.count(K.MOVE_POINTER) == 3 and ptr(r)[0] > p[0]
    assert r.ctl.snapshot().pointer_engaged and r.ctl.snapshot().tracking_ok
    q = ptr(r)
    r.frame(rh((320.0, 300.0)))
    assert ptr(r)[0] > q[0] and ptr(r)[0] - q[0] < 60
    assert set(r.kinds()) == {K.MOVE_POINTER}


@pytest.mark.parametrize("kw", [
    {"reasons": ()}, {"reasons": ("palm_edge_on",)},
    {"reasons": ("bone_ratio", "discontinuity_speed")},
    {"frame_reasons": ("same_handedness",)}, {"ambiguous": True},
    {"hid": 99}, {"pose": "open"}, {"idx": .1}, {"latency": 151.0},
    {"events": [(G.PINCH_START, RIGHT)]},
])
def test_other_faults_or_gesture_candidates_never_use_pointer_geometry_continuity(kw):
    r = rig(33.4, palm=(300.0, 300.0))
    p = ptr(r)
    geometry_frame(r, 320.0, **kw)
    assert ptr(r) == p and r.count(K.MOVE_POINTER) == 0
    assert r.count(K.LEFT_CLICK) == r.count(K.RIGHT_CLICK) == r.count(K.LEFT_DOWN) == 0


def test_geometry_frames_do_not_extend_the_loss_watchdog():
    r = rig(33.4, palm=(300.0, 300.0))
    last = r.ctl.watchdog.last_usable_ms
    for k in range(1, 6):
        geometry_frame(r, 300 + k * 5, dt=30)
    assert r.ctl.watchdog.last_usable_ms == last
    assert r.ctl.snapshot().pointer_engaged
    n = r.count(K.MOVE_POINTER)
    for k in range(6, 10):
        geometry_frame(r, 300 + k * 5, dt=30)
    assert not r.ctl.snapshot().pointer_engaged
    assert r.count(K.MOVE_POINTER) <= n + 1


def test_missing_hand_still_disengages_immediately_after_geometry_motion():
    r = rig(33.4, palm=(300.0, 300.0))
    geometry_frame(r, 310.0)
    r.frame()
    assert not r.ctl.snapshot().pointer_engaged


def test_geometry_motion_cannot_start_from_a_disengaged_pointer():
    r = rig(33.4, pose="open", palm=(300.0, 300.0))
    geometry_frame(r, 320.0)
    assert not r.ctl.snapshot().pointer_engaged and r.count(K.MOVE_POINTER) == 0
