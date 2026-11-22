from __future__ import annotations

import pytest

from handcontrol.instrument.strings import CrossingDetector, StringLayout

LINE = ((0.0, 100.0), (200.0, 100.0))      # horizontal string, canonical normal points down (+y)
KW = dict(band_px=6.0, end_margin=0.04, pick_scale_px=100.0, min_speed_pu_s=2.0, cooldown_ms=60.0)


def drive(det: CrossingDetector, ys, *, x: float = 100.0, dt: float = 33.0, line=LINE, lines=None, **kw):
    """Move the tip through the y values (one per frame). Returns the strikes with frame numbers."""
    opts = {**KW, **kw}
    out = []
    prev_tip, prev_line, prev_t = None, None, None
    for i, y in enumerate(ys):
        ln = lines[i] if lines is not None else line
        tip = (x, y)
        t = i * dt
        st = det.update(prev_line or ln, ln, prev_tip or tip, tip, prev_t if prev_t is not None else t, t, **opts)
        if st is not None:
            out.append((i, st))
        prev_tip, prev_line, prev_t = tip, ln, t
    return out


def test_fast_crossing_fires_once_with_interpolated_time_point_and_direction():
    det = CrossingDetector(0)
    hits = drive(det, [40.0, 160.0, 200.0])
    assert len(hits) == 1
    i, st = hits[0]
    assert i == 1
    assert st.fraction == pytest.approx(0.5)
    assert st.t_ms == pytest.approx(16.5)
    assert st.point == pytest.approx((100.0, 100.0))
    assert st.u == pytest.approx(0.5)
    assert st.direction == 1                               # moved along +normal (down)
    assert st.speed_pu_s == pytest.approx(120.0 / 0.033 / 100.0)
    up = drive(CrossingDetector(0), [160.0, 40.0])
    assert len(up) == 1 and up[0][1].direction == -1


def test_first_frame_is_only_an_observation():
    det = CrossingDetector(0)
    assert drive(det, [160.0]) == []
    assert det.side == 1


def test_trembling_inside_the_band_never_fires():
    det = CrossingDetector(0)
    ys = [60.0] + [100.0 + (5.0 if i % 2 else -5.0) for i in range(30)]
    hits = drive(det, ys, dt=10.0)
    assert hits == []                                      # never left the band on the other side
    assert det.side == -1


def test_entering_the_band_then_leaving_on_the_same_side_does_not_fire():
    det = CrossingDetector(0)
    assert drive(det, [80.0, 103.0, 98.0, 104.0, 80.0, 60.0]) == []


def test_slow_crossing_in_steps_fires_at_band_exit_with_the_zero_crossing_step():
    det = CrossingDetector(0)
    hits = drive(det, [70.0, 97.0, 103.0, 140.0], dt=10.0)   # zero crossing in step 1->2 (6 px / 10 ms)
    assert len(hits) == 1
    i, st = hits[0]
    assert i == 3
    assert st.t_ms == pytest.approx(15.0)
    assert st.speed_pu_s == pytest.approx(6.0 / 0.010 / 100.0)


def test_slow_crossing_never_fires_not_even_later():
    det = CrossingDetector(0)
    ys = [90.0 + i * 1.0 for i in range(25)]              # 1 px / 33 ms = 0.3 pu/s
    assert drive(det, ys) == []
    assert det.side == 1
    # keeps moving away on the far side quickly: nothing fires late
    assert drive(det, [115.0, 160.0, 220.0]) == []


def test_crossing_beyond_the_string_end_does_not_fire():
    assert drive(CrossingDetector(0), [40.0, 160.0], x=230.0) == []
    assert drive(CrossingDetector(0), [40.0, 160.0], x=-20.0) == []
    assert drive(CrossingDetector(0), [40.0, 160.0], x=4.0) == []         # inside the 4 % end margin
    assert len(drive(CrossingDetector(0), [40.0, 160.0], x=12.0)) == 1


def test_cooldown_blocks_a_quick_second_crossing():
    det = CrossingDetector(0)
    hits = drive(det, [80.0, 120.0, 80.0, 120.0, 80.0], dt=20.0)
    times = [st.t_ms for _, st in hits]
    assert times and all(b - a >= 60.0 for a, b in zip(times, times[1:]))
    assert len(hits) == 2                                  # t=10 fires, 30/50 blocked, 70 fires


def test_string_moving_into_a_still_tip_does_not_fire():
    det = CrossingDetector(0)
    lines = [((0.0, y), (200.0, y)) for y in (60.0, 140.0, 160.0)]
    assert drive(det, [100.0, 100.0, 100.0], lines=lines) == []


def test_moving_string_uses_interpolated_geometry():
    # tip moves down 100 -> 140 while the string moves up 130 -> 90: they meet at f = 0.75 (y = 130 - 30)
    det = CrossingDetector(0)
    lines = [((0.0, 130.0), (200.0, 130.0)), ((0.0, 90.0), (200.0, 90.0))]
    hits = drive(det, [70.0, 140.0], lines=lines, dt=40.0)
    assert len(hits) == 1
    st = hits[0][1]
    assert st.fraction == pytest.approx((130 - 70) / ((130 - 70) + (140 - 90)))
    assert st.point[1] == pytest.approx(130 - 40 * st.fraction)


def test_disallowed_crossing_updates_side_without_firing():
    det = CrossingDetector(0)
    assert drive(det, [40.0, 160.0], allow=False) == []
    assert det.side == 1


def test_reset_side_requires_a_fresh_observation():
    det = CrossingDetector(0)
    drive(det, [40.0])
    det.reset_side()
    assert det.side is None
    assert drive(det, [160.0]) == []
    assert det.side == 1


def test_layout_solo_and_chord_ordering():
    lay = StringLayout()
    solo = lay.build((0.0, 100.0), (130.0, 100.0), (50.0, 230.0), 100.0, 1, 0.3)
    assert len(solo.lines) == 1 and solo.lines[0].index == 0
    lay.reset()
    chord = lay.build((0.0, 100.0), (130.0, 100.0), (50.0, 230.0), 100.0, 4, 0.3)
    ys = {ln.slot: ln.p0[1] for ln in chord.lines}
    assert ys == pytest.approx({0: 100.0, 1: 70.0, 2: 40.0, 3: 10.0})    # away from the palm (up)
    order = sorted(chord.lines, key=lambda ln: ln.index)
    assert [ln.p0[1] for ln in order] == pytest.approx([10.0, 40.0, 70.0, 100.0])   # index 0 on top
    lay.reset()
    below = lay.build((0.0, 100.0), (130.0, 100.0), (50.0, -30.0), 100.0, 4, 0.3)
    order = sorted(below.lines, key=lambda ln: ln.index)
    assert [ln.p0[1] for ln in order] == pytest.approx([100.0, 130.0, 160.0, 190.0])


def test_layout_down_orientation_has_hysteresis_near_vertical():
    lay = StringLayout()
    first = lay.build((0.0, 0.0), (100.0, 0.0), (50.0, 100.0), 100.0, 4, 0.3)
    assert first.down_sign == 1
    # nearly vertical string tilted slightly past vertical: orientation is kept
    tilted = lay.build((0.0, 0.0), (-10.0, -100.0), (60.0, -50.0), 100.0, 4, 0.3)
    assert tilted.down_sign == 1                           # normal y = -0.1: inside the hysteresis
    flipped = lay.build((0.0, 0.0), (-100.0, -100.0), (60.0, -50.0), 100.0, 4, 0.3)
    assert flipped.down_sign == -1                         # normal y = -0.7: clearly the other way
