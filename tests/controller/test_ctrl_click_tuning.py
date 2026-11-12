"""Finger arbitration, bounce re-arm, watchdog-bounded gaps and recorded regressions."""
from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

import pytest

from ctrl_helpers import G, K, RIGHT, Rig, tcfg
from test_ctrl_pinch_mouse import _dragging, mh, rig, tap
from click_record_replay import feature, read_fixture, replay, short_tap
from handcontrol.contracts import Quality
from handcontrol.middle_pinch import middle_pinch_distance


def right_tap(r: Rig, *, idx: float = 1, mid: float = .1, bent: str = "m") -> None:
    for i in range(6):
        r.frame(mh(idx=idx, mid=mid, bent=bent), events=[(G.PINCH_START, RIGHT)] if i == 0 and idx < .33 else [])
    for i in range(4):
        r.frame(mh(), events=[(G.PINCH_END, RIGHT)] if i == 0 and idx < .33 else [])


@pytest.mark.parametrize("idx,mid,bent,expected", [
    (.10, .22, "m", K.RIGHT_CLICK),  # middle BENT beats the closer index tip
    (.22, .10, "i", K.LEFT_CLICK),   # index BENT beats the closer middle tip
    (.28, .10, "", K.RIGHT_CLICK),   # no decisive states: clearly nearer middle
    (.10, .28, "", K.LEFT_CLICK),
    (.18, .13, "im", K.RIGHT_CLICK), # recorded right repeat 6: both states BENT
])
def test_finger_state_first_then_distance(idx, mid, bent, expected):
    r = rig()
    right_tap(r, idx=idx, mid=mid, bent=bent)
    assert r.count(expected) == 1
    assert r.count(K.RIGHT_CLICK if expected is K.LEFT_CLICK else K.LEFT_CLICK) == 0
    assert r.count(K.LEFT_DOWN) == 0


def test_decision_uses_state_change_inside_three_frame_window_then_locks():
    r = rig()
    r.frame(mh(idx=.15, mid=.28, bent="i"), events=[(G.PINCH_START, RIGHT)])
    r.frame(mh(idx=.2, mid=.22, bent="m"))
    r.frame(mh(idx=.2, mid=.22, bent="m"))
    assert r.ctl._eng.decision_done
    # Middle debounce may complete next frame; later left-looking frames must not change the vote.
    for _ in range(3):
        r.frame(mh(idx=.1, mid=.15, bent="i"))
    for i in range(4):
        r.frame(mh(), events=[(G.PINCH_END, RIGHT)] if i == 0 else [])
    assert r.count(K.RIGHT_CLICK) == 1 and r.count(K.LEFT_CLICK) == 0


@pytest.mark.parametrize("side", ["left", "right"])
def test_recontact_without_full_opening_is_merged_but_wide_open_double_survives(side):
    r = rig()
    if side == "left":
        tap(r, 33.4, idx=.1)
        for _ in range(15):
            r.frame(mh(idx=.8))
        tap(r, 33.4, idx=.1)
        kind = K.LEFT_CLICK
    else:
        for d in ([.1] * 5 + [.8] * 18 + [.1] * 5 + [1.2] * 4):
            r.frame(mh(mid=d, bent="m"))
        kind = K.RIGHT_CLICK
    assert r.count(kind) == 1
    for _ in range(3):
        r.frame(mh())
    if side == "left":
        tap(r, 33.4, idx=.1)
    else:
        right_tap(r)
    assert r.count(kind) == 2


def test_deliberate_right_double_click_is_not_blanket_suppressed_for_600_ms():
    r = rig()
    right_tap(r)
    right_tap(r)
    clicks = r.sink.of(K.RIGHT_CLICK)
    assert len(clicks) == 2 and clicks[1].capture_ms - clicks[0].capture_ms < 600


def test_relative_drag_recovery_reanchors_instead_of_replaying_hidden_motion():
    from test_ctrl_relative import rig as relative_rig, rh, hold
    r = relative_rig(33.4)
    r.frame(rh(idx=.1), events=[(G.PINCH_START, RIGHT)])
    hold(r, (320, 300), 520, 33.4, idx=.1)
    assert r.count(K.LEFT_DOWN) == 1
    r.sink.clear()
    r.frame(replace(rh(), quality=Quality.DEGRADED), dt=60)
    r.frame(rh((450, 300), idx=.1), dt=60)
    assert r.count(K.MOVE_POINTER) == 0 and r.count(K.LEFT_UP) == 0
    r.frame(rh((455, 300), idx=.1))
    assert r.count(K.MOVE_POINTER) == 1


def test_rejected_ambiguous_contact_does_not_disarm_later_right_tap():
    r = rig()
    right_tap(r, idx=.2, mid=.2, bent="")
    assert r.count(K.LEFT_CLICK) == r.count(K.RIGHT_CLICK) == 0
    right_tap(r, idx=.25, mid=.1, bent="m")
    assert r.count(K.RIGHT_CLICK) == 1 and r.count(K.LEFT_CLICK) == 0


def test_release_crossing_hold_deadline_between_frames_is_not_silently_lost():
    r = rig()
    r.frame(mh(idx=.1, bent="i"), events=[(G.PINCH_START, RIGHT)])
    for _ in range(4):
        r.frame(mh(idx=.1, bent="i"), dt=100)
    r.frame(mh(), events=[(G.PINCH_END, RIGHT)], dt=100)
    assert r.count(K.LEFT_DOWN) == r.count(K.LEFT_UP) == 1
    assert r.count(K.LEFT_CLICK) == r.count(K.RIGHT_CLICK) == 0


@pytest.mark.parametrize("gap_ms", [62, 109, 140, 190])
def test_same_identity_degraded_drag_freezes_then_recovers_before_deadline(gap_ms):
    r = _dragging()
    last = r.ctl.watchdog.last_usable_ms
    r.sink.clear()
    r.frame(replace(mh(), quality=Quality.DEGRADED), dt=gap_ms / 2)
    assert r.ctl.watchdog.last_usable_ms == last and r.kinds() == []
    r.frame(mh(), dt=gap_ms / 2)
    assert K.LEFT_UP not in r.kinds() and K.RELEASE_ALL not in r.kinds()
    r.frame(mh(), events=[(G.PINCH_END, RIGHT)])
    assert r.count(K.LEFT_UP) == 1 and r.count(K.LEFT_CLICK) == 0
    assert all(0 <= r.clock.now_ms() - a.capture_ms <= 150 for a in r.sink.actions)


def test_pending_left_click_survives_short_same_id_quality_gap():
    r = rig()
    r.frame(mh(idx=.1, bent="i"), events=[(G.PINCH_START, RIGHT)])
    r.frame(replace(mh(), quality=Quality.DEGRADED), dt=60)
    assert r.count(K.LEFT_CLICK) == 0
    r.frame(mh(idx=.1, bent="i"), dt=40)
    r.frame(mh(), events=[(G.PINCH_END, RIGHT)])
    assert r.count(K.LEFT_CLICK) == 1 and r.count(K.RIGHT_CLICK) == 0


def test_degraded_drag_is_released_at_exact_200_ms_without_a_new_frame():
    r = _dragging()
    last = r.ctl.watchdog.last_usable_ms
    r.frame(replace(mh(), quality=Quality.DEGRADED), dt=60)
    r.clock.set(last + 199)
    r.ctl.tick()
    assert r.count(K.LEFT_UP) == 0
    r.clock.set(last + 200)
    r.ctl.tick()
    assert r.count(K.LEFT_UP) == 1
    assert r.ctl.snapshot().needs_neutral


@pytest.mark.parametrize("fault", ["identity", "ambiguous", "missing", "stale"])
def test_grace_never_overrides_identity_or_staleness_safety(fault):
    r = _dragging()
    if fault == "identity":
        r.frame(replace(mh(), hand_id=99))
    elif fault == "ambiguous":
        r.frame(mh(), ambiguous=True)
    elif fault == "missing":
        r.frame()
    else:
        r.frame(mh(), latency=151)
    assert r.count(K.LEFT_UP) == 1 or r.count(K.RELEASE_ALL) > 0
    assert r.count(K.LEFT_CLICK) == r.count(K.RIGHT_CLICK) == 0


def groups():
    result = defaultdict(list)
    for row in read_fixture():
        result[row["phase"], int(row["repeat"])].append(row)
    return result


@pytest.mark.parametrize("phase,repeat", [("left_pinch", 1), ("left_pinch", 8),
    ("right_pinch", 2), ("right_pinch", 6), ("right_pinch", 8)])
def test_recorded_short_cadence_click_classification(phase, repeat):
    rows = groups()[phase, repeat]
    if (phase, repeat) == ("left_pinch", 1):
        r = replay(rows)  # Original timing: includes the narrow-open multi-contact bounce.
    else:
        r = replay(short_tap(rows, "middle" if phase == "right_pinch" else "index"), cadence_ms=33.4)
    if phase == "right_pinch":
        assert r.count(K.RIGHT_CLICK) == 1
        assert r.count(K.LEFT_CLICK) == r.count(K.LEFT_DOWN) == 0
    else:
        assert r.count(K.LEFT_CLICK) + r.count(K.LEFT_DOWN) >= 1
        assert r.count(K.RIGHT_CLICK) == 0


@pytest.mark.parametrize("repeat", [3, 5])
def test_recorded_drag_original_timing_and_safe_cleanup(repeat):
    r = replay(groups()["drag", repeat])
    assert r.count(K.LEFT_DOWN) >= 1 and r.count(K.LEFT_UP) >= 1
    assert r.count(K.RIGHT_CLICK) == 0


@pytest.mark.parametrize("repeat", [2, 6, 8])
def test_recorded_multi_second_right_hold_never_turns_into_left_activity(repeat):
    r = replay(groups()["right_pinch", repeat])
    assert r.count(K.LEFT_CLICK) == r.count(K.LEFT_DOWN) == 0
    # Long stationary right holds remain cancelled, as required by the existing safety regression.
    assert r.count(K.RIGHT_CLICK) == 0


def test_excerpt_is_small_and_geometry_matches_the_csv_distances():
    rows = read_fixture()
    manifest = json.loads((Path(__file__).parent / "data/click_record_excerpt.json").read_text())
    assert len(rows) == manifest["excerpt_rows"] < 800 and manifest["source_rows"] == 5914
    for row in rows:
        h = feature(row)
        if h is None or row["status"] != "ok":
            continue
        assert middle_pinch_distance(h, int(row["width"]), int(row["height"])) == pytest.approx(float(row["middle_distance_pu"]))
        a, b = h.landmarks[4], h.landmarks[8]
        distance = math.hypot((a.x - b.x) * int(row["width"]), (a.y - b.y) * int(row["height"])) / h.palm_scale_px
        assert distance == pytest.approx(float(row["index_distance_pu"]))
