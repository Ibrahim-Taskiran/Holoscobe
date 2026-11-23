"""Free layout ("Serbest teller"): the user draws, moves, resizes, stacks and deletes strings by pinching."""
from __future__ import annotations

from dataclasses import replace

import pytest

from handcontrol.config import validate
from handcontrol.contracts import FingerInfo, FingerName, FingerState, FrameFeatures, HandFeatures, Handedness, Landmark, Quality
from handcontrol.instrument.engine import (
    STATUS_EDITING, STATUS_FULL, STATUS_NO_STRINGS, STATUS_READY, InstrumentConfig, InstrumentEngine,
)
from handcontrol.instrument.events import NoteOn
from handcontrol.instrument.freeform import MAX_STRINGS, normalize_free_strings, pitch_order, snap_segment

W, H = 640, 480
ASPECT = W / H


def hand(hid: int, side: Handedness, tip: tuple[float, float], *, pinch: bool = False,
         scale: float = 80.0) -> HandFeatures:
    """Index tip at `tip`; when pinching the thumb touches it, so the pinch point is ~tip."""
    x, y = tip
    thumb = (x, y) if pinch else (x + 60.0, y + 50.0)
    palm = (x + 30.0, y + 90.0)
    pts = [palm] * 21
    pts[4], pts[8] = thumb, tip
    lms = tuple(Landmark(px / W, py / H) for px, py in pts)
    fingers = tuple(FingerInfo(n, FingerState.EXTENDED, 0.0) for n in FingerName)
    d = ((thumb[0] - x) ** 2 + (thumb[1] - y) ** 2) ** 0.5 / scale
    return HandFeatures(hid, side, Quality.USABLE, palm, scale, fingers, d, tip, lms)


def frame(t: float, *hands: HandFeatures) -> FrameFeatures:
    return FrameFeatures(t, t + 5.0, W, H, tuple(hands), False)


def engine(strings=(), **kw) -> InstrumentEngine:
    return InstrumentEngine(InstrumentConfig(layout="free", free_strings=tuple(strings), **kw))


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def step(self, eng: InstrumentEngine, *hands: HandFeatures, dt: float = 33.0):
        self.t += dt
        return eng.update(frame(self.t, *hands), True)


def drag(eng: InstrumentEngine, clock: Clock, path: list[tuple[float, float]], *, hid: int = 2,
         side: Handedness = Handedness.RIGHT, hold_frames: int = 14):
    """Pinch at path[0], hold past 400 ms, follow the path pinched, then release. Returns the views."""
    views = []
    for _ in range(hold_frames):
        views.append(clock.step(eng, hand(hid, side, path[0], pinch=True))[1])
    for p in path[1:]:
        views.append(clock.step(eng, hand(hid, side, p, pinch=True))[1])
    views.append(clock.step(eng, hand(hid, side, path[-1]))[1])
    return views


def line(a, b, n=6):
    return [(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n) for i in range(n + 1)]


def test_no_strings_at_start_and_status_explains_how_to_draw():
    _, view = engine().update(frame(0.0, hand(2, Handedness.RIGHT, (300.0, 300.0))), True)
    assert view.layout == "free" and view.strings == () and view.free_strings == ()
    assert view.status == STATUS_NO_STRINGS and not view.playing


def test_pinch_hold_and_pull_draws_a_string_that_then_plays():
    eng, clock = engine(), Clock()
    views = drag(eng, clock, line((100.0, 200.0), (500.0, 204.0)))
    assert any(v.adjusting and v.status == STATUS_EDITING for v in views)
    assert views[-1].adjusting is False and len(eng.free_strings) == 1
    x0, y0, x1, y1 = eng.free_strings[0]
    assert y0 == y1 == pytest.approx(202.0 / H, abs=0.002)                  # near-horizontal: straightened
    assert (x0, x1) == pytest.approx((100.0 / W, 500.0 / W), abs=0.01)
    events = []
    for y in (150.0, 170.0, 190.0, 210.0, 230.0, 250.0):
        events += clock.step(eng, hand(2, Handedness.RIGHT, (300.0, y)))[0]
    notes = [e for e in events if isinstance(e, NoteOn)]
    assert len(notes) == 1 and notes[0].midi == 52.0
    assert clock.step(eng, hand(2, Handedness.RIGHT, (300.0, 260.0)))[1].status == STATUS_READY


def degraded(h: HandFeatures) -> HandFeatures:
    return replace(h, quality=Quality.DEGRADED)


@pytest.mark.parametrize("glitch", ["missing", "degraded", "ambiguous", "new_id"])
def test_short_tracking_failures_do_not_cut_a_string(glitch):
    eng, clock = engine(), Clock()
    R = Handedness.RIGHT
    for _ in range(14):
        clock.step(eng, hand(2, R, (100.0, 200.0), pinch=True))
    for p in line((100.0, 200.0), (300.0, 200.0)):
        clock.step(eng, hand(2, R, p, pinch=True))
    hid = 2
    if glitch == "missing":
        for _ in range(5):
            assert clock.step(eng)[1].adjusting
    elif glitch == "degraded":
        for _ in range(12):
            assert clock.step(eng, degraded(hand(2, R, (300.0, 200.0), pinch=True)))[1].adjusting
    elif glitch == "ambiguous":
        for _ in range(4):
            clock.t += 33.0
            assert eng.update(replace(frame(clock.t, hand(2, R, (300.0, 200.0), pinch=True)),
                                      identity_ambiguous=True), True)[1].adjusting
    else:
        hid = 7
        assert clock.step(eng, hand(7, R, (306.0, 200.0), pinch=True))[1].adjusting
    for p in line((300.0, 200.0), (500.0, 200.0)):
        clock.step(eng, hand(hid, R, p, pinch=True))
    clock.step(eng, hand(hid, R, (500.0, 200.0)))
    assert len(eng.free_strings) == 1
    assert eng.free_strings[0][0] == pytest.approx(100.0 / W, abs=0.01)
    assert eng.free_strings[0][2] == pytest.approx(500.0 / W, abs=0.01)


def test_a_long_loss_drops_the_string_where_it_is():
    eng, clock = engine(), Clock()
    for _ in range(14):
        clock.step(eng, hand(2, Handedness.RIGHT, (100.0, 200.0), pinch=True))
    for p in line((100.0, 200.0), (300.0, 200.0)):
        clock.step(eng, hand(2, Handedness.RIGHT, p, pinch=True))
    for _ in range(10):
        _, view = clock.step(eng)
    assert not view.adjusting and len(eng.free_strings) == 1


def test_without_snap_the_string_stays_where_it_was_dropped():
    eng, clock = engine(free_snap=False), Clock()
    drag(eng, clock, line((100.0, 200.0), (500.0, 214.0)))
    _, y0, _, y1 = eng.free_strings[0]
    assert y1 - y0 == pytest.approx(14.0 / H, abs=0.003)


def test_a_short_pinch_or_a_tiny_line_adds_nothing():
    eng, clock = engine(), Clock()
    drag(eng, clock, [(200.0, 200.0)], hold_frames=5)                      # released before 400 ms
    drag(eng, clock, line((200.0, 200.0), (210.0, 202.0)))                 # shorter than MIN_LENGTH
    assert eng.free_strings == ()


def test_drag_an_end_resizes_and_drag_the_middle_moves():
    s = (0.2, 0.5, 0.6, 0.5)
    eng, clock = engine([s]), Clock()
    drag(eng, clock, line((0.6 * W, 0.5 * H), (0.8 * W, 0.5 * H)))          # right end
    assert eng.free_strings[0] == pytest.approx((0.2, 0.5, 0.8, 0.5), abs=0.005)
    drag(eng, clock, line((0.5 * W, 0.5 * H), (0.5 * W, 0.3 * H)))          # middle
    assert eng.free_strings[0] == pytest.approx((0.2, 0.3, 0.8, 0.3), abs=0.005)


def test_squeezing_a_string_deletes_it():
    eng, clock = engine([(0.2, 0.5, 0.6, 0.5)]), Clock()
    drag(eng, clock, line((0.6 * W, 0.5 * H), (0.21 * W, 0.5 * H)))
    assert eng.free_strings == ()


def test_stacking_snaps_ends_and_gap_but_free_placement_elsewhere_stays():
    a = (0.2, 0.3, 0.7, 0.3)
    b, snapped = snap_segment((0.21, 0.4, 0.69, 0.41), [a], ASPECT)
    assert snapped and b == pytest.approx((0.2, 0.405, 0.7, 0.405), abs=1e-3)     # ends aligned, gap kept
    c, snapped = snap_segment((0.2, 0.52, 0.7, 0.52), [a, b], ASPECT)       # gap 0.115 -> stack gap 0.105
    assert snapped and c == pytest.approx((0.2, 0.51, 0.7, 0.51), abs=1e-3)
    far = (0.05, 0.8, 0.3, 0.95)                                             # tilted, far: untouched
    assert snap_segment(far, [a, b], ASPECT) == (far, False)


def test_stacked_strings_climb_the_scale_top_to_bottom():
    strings = ((0.2, 0.6, 0.7, 0.6), (0.2, 0.3, 0.7, 0.3), (0.2, 0.45, 0.7, 0.45))
    assert pitch_order(strings) == [1, 2, 0]
    _, view = engine(strings).update(frame(0.0), True)
    assert [s.label for s in view.strings] == ["A3", "E3", "G3"]


def test_two_hands_draw_a_string_between_them_and_a_pinching_hand_never_strikes():
    eng, clock = engine([(0.2, 0.5, 0.8, 0.5)]), Clock()
    left, right = (0.3 * W, 0.2 * H), (0.7 * W, 0.25 * H)
    events = []
    for _ in range(14):
        ev, view = clock.step(eng, hand(1, Handedness.LEFT, left, pinch=True),
                              hand(2, Handedness.RIGHT, right, pinch=True))
        events += ev
    assert view.adjusting and len(view.free_strings) == 2
    for y in (0.2, 0.4, 0.6, 0.7):                                          # pinched right hand crosses the string
        events += clock.step(eng, hand(1, Handedness.LEFT, left, pinch=True),
                             hand(2, Handedness.RIGHT, (0.7 * W, y * H), pinch=True))[0]
    clock.step(eng, hand(1, Handedness.LEFT, left), hand(2, Handedness.RIGHT, (0.7 * W, 0.7 * H)))
    assert not [e for e in events if isinstance(e, NoteOn)]
    assert len(eng.free_strings) == 2
    assert eng.free_strings[1][:2] == pytest.approx((0.3, 0.2), abs=0.01)


def test_limit_refuses_new_strings_with_a_status():
    strings = tuple((0.1, 0.05 + 0.09 * k, 0.9, 0.05 + 0.09 * k) for k in range(MAX_STRINGS))
    eng, clock = engine(strings), Clock()
    views = drag(eng, clock, [(0.95 * W, 0.97 * H), (0.6 * W, 0.97 * H)], hold_frames=14)
    assert len(eng.free_strings) == MAX_STRINGS and any(v.status == STATUS_FULL for v in views)


def test_edits_survive_all_off_and_settings_round_trip():
    eng, clock = engine(), Clock()
    drag(eng, clock, line((100.0, 200.0), (500.0, 200.0)))
    eng.all_off(clock.t)
    assert len(eng.free_strings) == 1
    s = validate({"instrument_free_strings": [[0.1, 0.2, 0.5, 0.2], [0, 0, 0.01, 0], "bad", [1, 2, 3]],
                  "instrument_free_snap": False})
    assert s.instrument_free_strings == [[0.1, 0.2, 0.5, 0.2]] and s.instrument_free_snap is False
    assert validate({}).instrument_free_strings == [] and validate({}).instrument_free_snap is True
    assert len(normalize_free_strings([[0.1, 0.1, 0.9, 0.1]] * 20)) == MAX_STRINGS
