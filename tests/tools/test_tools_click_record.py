from __future__ import annotations

import csv
import json
from dataclasses import replace

import pytest

from _tools_fakes import FakeConsole, FakeSource, frame, hand
from handcontrol.contracts import FingerState, Handedness, Landmark, Quality
from handcontrol.tools import click_record as cr


def sample(t=0, *, index=1.0, middle=.8, shift=0.0, **kwargs):
    landmarks = [Landmark(.2 + shift / 640, .2) for _ in range(21)]
    landmarks[8] = Landmark(.2 + (shift + index * 100) / 640, .2)
    landmarks[12] = Landmark(.2 + (shift + middle * 100) / 640, .2)
    return frame(t, hand(landmarks=tuple(landmarks), center=(320 + shift, 240), **kwargs))


def cycle_rows(phase="left_pinch", repeat=1):
    values = [1, 1, 1, .9, .6, .3, .1, .1, .3, .6, .9, 1, 1, 1]
    rows = []
    for i, value in enumerate(values):
        segment = "baseline" if i < 3 else "action" if i < 11 else "recovery"
        rows.append(cr.frame_row(sample(i * 100, index=value, middle=value,
                                       default=FingerState.BENT if 5 <= i <= 9 else FingerState.EXTENDED),
                                 phase, repeat, segment))
    return rows


def test_raw_distances_pixels_and_palm_units():
    row = cr.frame_row(sample(index=.25, middle=.5), "left_pinch", 1, "action", 30)
    assert row["status"] == "ok" and row["quality"] == "usable"
    assert row["index_distance_px"] == pytest.approx(25)
    assert row["middle_distance_pu"] == pytest.approx(.5)
    assert row["index_x_px"] == pytest.approx(153)
    assert row["landmark5_x_px"] == pytest.approx(128)
    assert row["fps"] == 30
    assert set(cr.FIELDS) == set(row)


@pytest.mark.parametrize("f,status", [
    (frame(10), "missing"), (frame(10, hand(Handedness.LEFT)), "missing"),
    (frame(10, hand(), hand(hand_id=2)), "ambiguous"),
    (frame(10, hand(), ambiguous=True), "ambiguous"),
])
def test_missing_or_ambiguous_hand_keeps_metadata_only(f, status):
    row = cr.frame_row(f, "still", 1, "action")
    assert row["status"] == status and row["t_ms"] == 10
    assert all(row[key] is None for key in ("palm_x_px", "index_distance_px", "index", "hand_id"))


@pytest.mark.parametrize("scale,quality", [(0, Quality.USABLE), (float("nan"), Quality.USABLE), (1, Quality.DEGRADED)])
def test_invalid_scale_and_degraded_frames_excluded(scale, quality):
    f = sample(scale=scale, quality=quality)
    row = cr.frame_row(f, "still", 1, "action")
    assert row["status"] == "degraded"
    assert cr.summarize([row])["usable_frames"] == 0
    json.dumps(cr.summarize([row]), allow_nan=False)


def test_invalid_landmarks_are_not_measured():
    assert cr.frame_row(frame(0, hand(landmarks=(Landmark(.2, .2),))), "still", 1, "action")["status"] == "invalid"
    f = sample()
    bad = replace(f.hands[0], landmarks=tuple(Landmark(float("nan"), 0) for _ in range(21)))
    assert cr.frame_row(replace(f, hands=(bad,)), "still", 1, "action")["status"] == "invalid"


@pytest.mark.parametrize("phase,distance", [("left_pinch", "index"), ("right_pinch", "middle"), ("drag", "index")])
def test_trial_cycle_times_minimum_and_finger_distribution(phase, distance):
    result = cr.trial_summary(cycle_rows(phase), distance)
    assert result["complete_cycle"]
    assert result["minimum_pu"] == pytest.approx(.1)
    assert result["open_typical_pu"] == pytest.approx(1)
    assert result["closing_ms"] == 100 and result["opening_ms"] == 100
    assert result["pinch_ms"] == 500
    assert result["pinch_fingers"]["index_bent_frames"] == 5
    assert result["pinch_fingers"]["all_bent_frames"] == 5
    assert result["index_drift_pu"] == pytest.approx(.6)
    assert result["palm_drift_pu"] == 0
    ranges = cr.recommend_thresholds([result])
    assert ranges["status"] == "aday"
    assert .1 < ranges["close_range_pu"][0] < ranges["close_range_pu"][1] < ranges["open_range_pu"][0] < ranges["open_range_pu"][1] < 1


@pytest.mark.parametrize("fault", ["missing", "degraded", "identity", "gap"])
def test_tracking_discontinuities_never_create_timing_or_thresholds(fault):
    rows = cycle_rows()
    if fault in ("missing", "degraded"):
        rows[7]["status"] = fault
    elif fault == "identity":
        rows[7]["hand_id"] = 2
    else:
        for row in rows[7:]:
            row["t_ms"] += 500
    result = cr.trial_summary(rows, "index")
    assert not result["complete_cycle"] and result["pinch_ms"] is None
    assert cr.recommend_thresholds([result])["close_range_pu"] is None


def test_missing_release_and_multiple_cycles_are_not_recommended():
    rows = cycle_rows()
    for row in rows[8:]:
        row["index_distance_pu"] = .1
    assert not cr.trial_summary(rows, "index")["complete_cycle"]
    rows = cycle_rows()
    second = cycle_rows(repeat=1)
    for row in second:
        row["t_ms"] += 1400
    result = cr.trial_summary(rows + second, "index")
    assert not result["complete_cycle"] and result["cycle_count"] == 2


def test_overlapping_noisy_data_produces_no_threshold():
    rows = cycle_rows()
    for i, row in enumerate(rows):
        row["index_distance_pu"] = .5 + (.1 if i % 2 else -.1)
    assert not cr.trial_summary(rows, "index")["complete_cycle"]
    assert cr.recommend_thresholds([])["status"] == "yetersiz"
    a = {"complete_cycle": True, "closed_upper_pu": .6, "open_lower_pu": .5, "baseline_noise_pu": .01}
    assert cr.recommend_thresholds([a])["status"] == "ayrışmıyor"


def test_jitter_range_and_fps_exclude_user_prompt_pauses():
    rows = [cr.frame_row(sample(0, shift=0), "still", 1, "action"),
            cr.frame_row(sample(100, shift=2), "still", 1, "action"),
            cr.frame_row(sample(100000, shift=0), "range", 1, "action"),
            cr.frame_row(sample(100100, shift=64), "range", 1, "action")]
    result = cr.summarize(rows)
    assert result["processed_fps"] == 10
    assert result["still"]["index"]["rms_px"] == pytest.approx(1)
    assert result["still"]["index"]["rms_pu"] == pytest.approx(.01)
    assert result["range"]["index"]["width_frame_pct"] == pytest.approx(10)
    assert result["range"]["index"]["height_frame_pct"] == 0


def test_fist_and_other_pinch_overlap_is_explicitly_not_distance_safe():
    result = cr.summarize(cycle_rows("left_pinch") + cycle_rows("right_pinch") + cycle_rows("fist"))
    for phase in ("left_pinch", "right_pinch"):
        thresholds = result["pinches"][phase]["thresholds"]
        assert thresholds["status"] == "aday"
        assert thresholds["negative_minima_pu"]["fist"] == pytest.approx(.1)
        assert thresholds["distance_only_separates_recorded_negatives"] is False


def quick_config():
    return cr.RecordConfig(still_seconds=.06, range_seconds=.06, pinch_repeats=1,
                           drag_repeats=1, fist_repeats=1, trial_seconds=.08, open_seconds=.06, hold_seconds=.02)


def test_fake_run_writes_every_frame_and_all_three_artifacts(out_dir):
    source = FakeSource(lambda t: sample(t) if int(t) % 40 else frame(t), step_ms=20)
    run = cr.ClickRecordRun(source, FakeConsole(), config=quick_config(), out_dir=out_dir)
    summary = run.execute()
    assert source.closed == 1 and not summary["interrupted"]
    assert len(summary["completed"]) == 6 and summary["status_counts"]["missing"] > 0
    paths = list(out_dir.glob("hw_click_*"))
    assert {p.suffix for p in paths} == {".csv", ".json", ".md"}
    with next(out_dir.glob("*.csv")).open(encoding="utf-8-sig", newline="") as stream:
        raw = list(csv.DictReader(stream))
    assert len(raw) == summary["frames"]
    assert any(r["palm_x_px"] == "" for r in raw if r["status"] == "missing")
    assert len({r["t_ms"] for r in raw}) == len(raw)
    assert json.loads(next(out_dir.glob("*.json")).read_text(encoding="utf-8"))["frames"] == len(raw)


@pytest.mark.parametrize("fault", ["interrupt", "open", "close"])
def test_partial_reports_and_cleanup_are_preserved(out_dir, fault):
    source = FakeSource(lambda t: sample(t), step_ms=20,
                        interrupt_after=5 if fault == "interrupt" else None,
                        open_error="Kamera açılamadı" if fault == "open" else None)
    if fault == "close":
        def broken_close():
            raise OSError("Kamera kapanamadı")
        source.close = broken_close
    result = cr.ClickRecordRun(source, FakeConsole(), config=quick_config(), out_dir=out_dir).execute()
    assert result["interrupted"]
    assert len(list(out_dir.iterdir())) == 3
    assert all(g["thresholds"]["status"] == "yetersiz" for g in result["pinches"].values())


@pytest.mark.parametrize("kwargs", [{"still_seconds": 0}, {"open_seconds": float("nan")},
    {"trial_seconds": 1, "hold_seconds": 1}, {"pinch_repeats": 0}])
def test_invalid_configuration_rejected(kwargs):
    with pytest.raises(ValueError):
        cr.RecordConfig(**kwargs).validate()
