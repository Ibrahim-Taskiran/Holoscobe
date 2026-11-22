"""Fixed layout ("Sabit teller"): strings fixed on the screen, placed and resized by the user."""
from __future__ import annotations

import pytest

from handcontrol.config import validate
from handcontrol.contracts import FingerInfo, FingerName, FingerState, FrameFeatures, HandFeatures, Handedness, Landmark, Quality
from handcontrol.instrument.engine import (
    STATUS_ADJUSTING, STATUS_NEED_HAND, STATUS_READY, InstrumentConfig, InstrumentEngine, fixed_lines, fixed_pitches,
)
from handcontrol.instrument.events import NoteOn
from handcontrol.instrument.geometry import normalize_fixed_rect

W, H = 640, 480
RECT = (0.25, 0.35, 0.75, 0.65)          # y 168..312 px, x 160..480 px


def hand(hid: int, side: Handedness, tip: tuple[float, float], *, pinch: bool = False,
         quality: Quality = Quality.USABLE, scale: float = 80.0) -> HandFeatures:
    x, y = tip
    thumb = (x + 4.0, y + 4.0) if pinch else (x + 60.0, y + 50.0)
    palm = (x + 30.0, y + 90.0)
    pts = [palm] * 21
    pts[4], pts[8] = thumb, tip
    lms = tuple(Landmark(px / W, py / H) for px, py in pts)
    fingers = tuple(FingerInfo(n, FingerState.EXTENDED, 0.0) for n in FingerName)
    d = ((thumb[0] - x) ** 2 + (thumb[1] - y) ** 2) ** 0.5 / scale
    return HandFeatures(hid, side, quality, palm, scale, fingers, d, tip, lms)


def frame(t: float, *hands: HandFeatures, ambiguous: bool = False) -> FrameFeatures:
    return FrameFeatures(t, t + 5.0, W, H, tuple(hands), ambiguous)


def engine(**kw) -> InstrumentEngine:
    return InstrumentEngine(InstrumentConfig(layout="fixed", fixed_rect=RECT, **kw))


def sweep(eng: InstrumentEngine, *, x: float = 320.0, y0: float = 120.0, y1: float = 360.0, steps: int = 6,
          dt: float = 33.0, t0: float = 0.0, side: Handedness = Handedness.RIGHT, hid: int = 2,
          active: bool = True, extra: tuple[HandFeatures, ...] = ()) -> tuple[list, list]:
    events, views = [], []
    for i in range(steps + 1):
        y = y0 + (y1 - y0) * i / steps
        ev, view = eng.update(frame(t0 + i * dt, hand(hid, side, (x, y)), *extra), active)
        events += ev
        views.append(view)
    return events, views


def notes(events: list) -> list[NoteOn]:
    return [e for e in events if isinstance(e, NoteOn)]


def test_strings_are_horizontal_inside_the_area_and_climb_the_scale():
    lines = fixed_lines(RECT, 6, W, H)
    assert lines[0] == ((160.0, 168.0), (480.0, 168.0)) and lines[-1] == ((160.0, 312.0), (480.0, 312.0))
    assert fixed_pitches("e_minor_pentatonic", 52.0, 6) == (52.0, 55.0, 57.0, 59.0, 62.0, 64.0)
    _, view = engine().update(frame(0.0), True)
    assert view.layout == "fixed" and len(view.strings) == 6 and view.fixed_rect == RECT
    assert [s.label for s in view.strings] == ["E3", "G3", "A3", "B3", "D4", "E4"]
    assert view.status == STATUS_NEED_HAND and not view.playing


def test_downward_sweep_strums_every_string_top_first():
    events, views = sweep(engine())
    ns = notes(events)
    assert [n.midi for n in ns] == [52.0, 55.0, 57.0, 59.0, 62.0, 64.0]
    assert all(b.delay_ms > a.delay_ms for a, b in zip(ns, ns[1:]) if b.t_ms == a.t_ms)
    assert sum(len(v.hits) for v in views) == 6 and all(h.direction == 1 for v in views for h in v.hits)
    assert views[-1].status == STATUS_READY and views[-1].note_label == "E4"


def test_upward_sweep_plays_bottom_first_and_softer():
    eng = engine()
    down = notes(sweep(eng)[0])
    up = notes(sweep(eng, y0=360.0, y1=120.0, t0=1000.0)[0])
    assert [n.midi for n in up] == [64.0, 62.0, 59.0, 57.0, 55.0, 52.0]
    assert max(n.velocity for n in up) < max(n.velocity for n in down) + 1e-9


def test_both_hands_play():
    eng = engine()
    left = notes(sweep(eng, side=Handedness.LEFT, hid=1, x=200.0)[0])
    assert len(left) == 6
    still = hand(1, Handedness.LEFT, (200.0, 100.0))
    both = notes(sweep(eng, t0=1000.0, extra=(still,))[0])
    assert len(both) == 6


def test_outside_the_area_slow_or_inactive_never_plays():
    assert notes(sweep(engine(), x=60.0)[0]) == []                       # left of the strings
    assert notes(sweep(engine(), steps=240, dt=33.0)[0]) == []           # far too slow
    assert notes(sweep(engine(), active=False)[0]) == []


def test_ambiguous_identity_or_degraded_hand_never_plays():
    eng = engine()
    events = []
    for i in range(7):
        ev, view = eng.update(frame(i * 33.0, hand(2, Handedness.RIGHT, (320.0, 120.0 + 40 * i)), ambiguous=True), True)
        events += ev
    assert notes(events) == [] and not view.playing
    events = []
    for i in range(7):
        ev, _ = eng.update(frame(1000 + i * 33.0, hand(2, Handedness.RIGHT, (320.0, 120.0 + 40 * i),
                                                    quality=Quality.DEGRADED)), True)
        events += ev
    assert notes(events) == []


def _pinch_frame(t: float, a: tuple[float, float], b: tuple[float, float]) -> FrameFeatures:
    return frame(t, hand(1, Handedness.LEFT, a, pinch=True), hand(2, Handedness.RIGHT, b, pinch=True))


def test_two_hand_pinch_moves_and_resizes_the_strings():
    eng = engine()
    for t in range(0, 391, 30):
        _, v = eng.update(_pinch_frame(float(t), (100.0, 100.0), (300.0, 200.0)), True)
    assert not v.adjusting and v.fixed_rect == RECT                       # held < 400 ms: nothing moves
    ev, v = eng.update(_pinch_frame(420.0, (100.0, 100.0), (300.0, 200.0)), True)
    assert v.adjusting and v.status == STATUS_ADJUSTING and notes(ev) == [] and not v.playing
    ev, v = eng.update(_pinch_frame(450.0, (64.0, 48.0), (576.0, 432.0)), True)   # stretch to the corners
    assert v.adjusting and notes(ev) == []
    # midpoint of thumb (+4, +4) and index tip
    assert v.fixed_rect == pytest.approx((66 / W, 50 / H, 578 / W, 434 / H), abs=1e-3)
    _, v = eng.update(frame(480.0, hand(1, Handedness.LEFT, (64.0, 48.0)), hand(2, Handedness.RIGHT, (576.0, 432.0))), True)
    assert not v.adjusting and v.fixed_rect == pytest.approx((66 / W, 50 / H, 578 / W, 434 / H), abs=1e-3)
    assert v.strings[0].p0[1] == pytest.approx(50.0, abs=0.5)
    # the strings now live in the new place
    ns = notes(sweep(eng, x=400.0, y0=-60.0, y1=470.0, t0=800.0, steps=10)[0])   # after a pause in tracking
    assert [n.midi for n in ns] == [52.0, 55.0, 57.0, 59.0, 62.0, 64.0]


def test_paused_or_one_hand_pinch_never_moves_the_strings():
    eng = engine()
    for t in range(0, 901, 30):
        _, v = eng.update(_pinch_frame(float(t), (64.0, 48.0), (576.0, 432.0)), False)
    assert not v.adjusting and v.fixed_rect == RECT
    eng = engine()
    for t in range(0, 901, 30):
        _, v = eng.update(frame(t, hand(1, Handedness.LEFT, (64.0, 48.0), pinch=True),
                                hand(2, Handedness.RIGHT, (576.0, 432.0))), True)
    assert not v.adjusting and v.fixed_rect == RECT


def test_configured_area_and_string_count():
    eng = InstrumentEngine(InstrumentConfig(layout="fixed", fixed_rect=(0.9, 0.9, 0.1, 0.1), fixed_strings=20))
    assert eng.config.fixed_strings == 8 and eng.config.fixed_rect == (0.1, 0.1, 0.9, 0.9)
    _, v = eng.update(frame(0.0), True)
    assert len(v.strings) == 8
    eng.configure(InstrumentConfig(layout="fixed", fixed_strings=4, scale="c_major"))
    _, v = eng.update(frame(10.0), True)
    assert [s.label for s in v.strings] == ["E3", "F3", "G3", "A3"]


def test_rect_normalization_and_settings():
    assert normalize_fixed_rect(None) == (0.25, 0.35, 0.75, 0.65)
    assert normalize_fixed_rect([0.1, float("nan"), 0.2, 0.3]) == (0.25, 0.35, 0.75, 0.65)
    assert normalize_fixed_rect((0.5, 0.5, 0.52, 0.51)) == pytest.approx((0.46, 0.465, 0.56, 0.545))
    assert normalize_fixed_rect((-1, -1, 2, 2)) == (0.0, 0.0, 1.0, 1.0)
    assert normalize_fixed_rect((0.99, 0.99, 1.0, 1.0)) == pytest.approx((0.9, 0.92, 1.0, 1.0))
    s = validate({"instrument_layout": "fixed", "instrument_fixed_rect": [0.6, 0.7, 0.2, 0.3],
                  "instrument_fixed_strings": 2})
    assert s.instrument_layout == "fixed" and s.instrument_fixed_rect == [0.2, 0.3, 0.6, 0.7]
    assert s.instrument_fixed_strings == 3
    d = validate({})
    assert d.instrument_fixed_rect == [0.25, 0.35, 0.75, 0.65] and d.instrument_fixed_strings == 6
