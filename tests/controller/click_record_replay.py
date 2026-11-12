"""CSV feature replay. Only tip geometry and unavailable curl scores are synthetic.

    The CSV supplies finger states, palm, scale, hand ID, quality, distances and original timestamps.
    Thumb/index/middle landmarks are constructed to match the two measured distances exactly.
    Curl was not recorded: .6 for BENT, .1 otherwise; this cannot validate the fist curl threshold.
"""
from __future__ import annotations

import csv
from dataclasses import replace
from pathlib import Path

from ctrl_helpers import Rig
from handcontrol.contracts import FingerInfo, FingerName, FingerState, FrameFeatures, HandFeatures, Handedness, Landmark, Quality
from handcontrol.controller import ControllerConfig
from handcontrol.gestures import GestureConfig, GestureRecognizer


def feature(row: dict[str, str]) -> HandFeatures | None:
    if not row["hand_id"]:
        return None
    width, height = int(row["width"]), int(row["height"])
    scale = float(row["palm_scale_px"] or 0)
    x, y = float(row["index_x_px"] or 0), float(row["index_y_px"] or 0)
    di, dm = float(row["index_distance_pu"] or 1), float(row["middle_distance_pu"] or 1)
    thumb_x = x - di * scale
    landmarks = [Landmark(.5, .5) for _ in range(21)]
    landmarks[4] = Landmark(thumb_x / width, y / height)
    landmarks[8] = Landmark(x / width, y / height)
    landmarks[12] = Landmark(thumb_x / width, (y + dm * scale) / height)
    landmarks[5] = Landmark(float(row["landmark5_x_px"] or 0) / width, float(row["landmark5_y_px"] or 0) / height)
    fingers = tuple(FingerInfo(f, FingerState(row[f.value] or "unknown"), .6 if row[f.value] == "bent" else .1) for f in FingerName)
    quality = Quality.USABLE if row["status"] == "ok" and row["quality"] == "usable" else Quality.DEGRADED
    return HandFeatures(int(row["hand_id"]), Handedness.RIGHT, quality,
                        (float(row["palm_x_px"] or 0), float(row["palm_y_px"] or 0)),
                        scale, fingers, di, (x, y), tuple(landmarks))


def read_fixture() -> list[dict[str, str]]:
    with (Path(__file__).parent / "data/click_record_excerpt.csv").open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def replay(rows: list[dict[str, str]], *, trace: bool = False, cadence_ms: float | None = None) -> Rig:
    r = Rig(cfg=ControllerConfig(mirror=False))
    recognizer = GestureRecognizer(GestureConfig(pinch_on_pu=.33, pinch_off_pu=.48))
    first = next(feature(row) for row in rows if row["status"] == "ok")
    assert first is not None
    opened = replace(first, pinch_distance=1.2, fingers=tuple(FingerInfo(f, FingerState.EXTENDED, .1) for f in FingerName))
    # Initialize both hysteresis detectors and the neutral interlock, without replaying stale input.
    for _ in range(9):
        r.clock.advance(33.4)
        t = r.clock.now_ms()
        f = FrameFeatures(t, t + 2, int(rows[0]["width"]), int(rows[0]["height"]), (opened,), False)
        r.ctl.on_frame(f, recognizer.update(f))
    r.sink.clear()
    offset = r.clock.now_ms() + 33.4 - float(rows[0]["t_ms"])
    last_trace = None
    for i, row in enumerate(rows):
        t = float(row["t_ms"]) + offset if cadence_ms is None else float(rows[0]["t_ms"]) + offset + i * cadence_ms
        r.clock.set(t + 5)
        h = feature(row)
        f = FrameFeatures(t, t + 2, int(row["width"]), int(row["height"]),
                          (h,) if h else (), row["status"] == "ambiguous")
        events = recognizer.update(f)
        r.ctl.on_frame(f, events)
        e = r.ctl._eng
        state = (e.kind.value, e.vote, e.state_vote, e.decision_done) if e else None
        if trace and (events or state != last_trace):
            print(round(t - offset - float(rows[0]["t_ms"])), row["segment"],
                  round(float(row["index_distance_pu"] or 0), 3), round(float(row["middle_distance_pu"] or 0), 3),
                  row["index"], row["middle"], state, [event.kind.value for event in events])
        last_trace = state
    return r


def short_tap(rows: list[dict[str, str]], distance: str) -> list[dict[str, str]]:
    """Classifier replay, not a timing experiment: crop the multi-second hold to six contact frames.

    Four pre-open and four post-release frames remain. Call replay(..., cadence_ms=33.4).
    Distances/states/palm positions remain recorded values; source time is retained in the fixture.
    """
    key = distance + "_distance_pu"
    valid = [i for i, row in enumerate(rows) if row["status"] == "ok"]
    # Use the final contact before release, rather than teleporting the palm from a multi-second
    # minimum to a distant release pose. This preserves the recorded release motion.
    contacts = [i for i in valid if float(rows[i][key]) <= .33][-6:]
    before = [i for i in valid if i < contacts[0] and float(rows[i][key]) >= .48][-4:]
    after = [i for i in valid if i > contacts[-1] and float(rows[i][key]) >= .48][:4]
    assert len(before) == 4 and len(after) == 4 and len(contacts) == 6
    return [rows[i] for i in before + contacts + after]


if __name__ == "__main__":
    from collections import defaultdict
    from click_record_analysis import read_rows
    groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in read_rows():
        if row["phase"] in ("left_pinch", "right_pinch", "drag"):
            groups[row["phase"], row["repeat"]].append(row)
    for key, rows in groups.items():
        r = replay(rows)
        print(key, {kind.value: r.count(kind) for kind in set(r.non_pointer())}, r.ctl.snapshot().notice)
