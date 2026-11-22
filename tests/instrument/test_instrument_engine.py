from __future__ import annotations

import math

import pytest

from handcontrol.contracts import Handedness, Quality
from handcontrol.instrument import engine as eng
from handcontrol.instrument.engine import InstrumentConfig, InstrumentEngine
from handcontrol.instrument.events import AllOff, Bend, NoteOn
from handcontrol.instrument.music import chord_voicing, scale_pitches

from instr_synth import frame, pick_hand, run, string_hand, sweep, two_hands

X = 315.0          # pick tip x: over the middle of the default string (250..380)


def notes(results):
    return [e for evs, _ in results for e in evs if isinstance(e, NoteOn)]


def bends(results):
    return [e for evs, _ in results for e in evs if isinstance(e, Bend)]


# ---------------------------------------------------------------- solo basics

def test_solo_downstroke_plays_one_scale_note(solo_engine):
    res = run(solo_engine, [(0.0, (X, 200.0)), (33.0, (X, 300.0))])
    ns = notes(res)
    assert len(ns) == 1
    n = ns[0]
    assert n.string == 0 and n.delay_ms == 0.0 and n.t_ms == 33.0
    assert n.midi in scale_pitches("e_minor_pentatonic", 52, 76)
    assert n.midi == 59                                  # 1.3 pu -> 59.7 -> B3
    assert 0.0 < n.velocity <= 1.0
    view = res[-1][1]
    assert view.playing and view.status == eng.STATUS_READY
    assert view.note_label == "B3" and view.strings[0].label == "B3"
    assert len(view.hits) == 1 and view.hits[0].direction == 1
    assert view.hits[0].y == pytest.approx(250.0) and view.hits[0].x == pytest.approx(X)
    assert view.strings[0].amplitude == pytest.approx(n.velocity)
    assert view.pick_tip == pytest.approx((X, 300.0))
    assert view.string_hand_id == 1 and view.pick_hand_id == 2


def test_note_ids_increase(solo_engine):
    res = run(solo_engine, [(0.0, (X, 200.0)), (33.0, (X, 300.0)), (100.0, (X, 300.0)), (133.0, (X, 200.0))])
    ns = notes(res)
    assert len(ns) == 2 and ns[1].note_id > ns[0].note_id


def test_free_pitch_when_not_quantized():
    e = InstrumentEngine(InstrumentConfig(quantize=False))
    ns = notes(run(e, [(0.0, (X, 200.0)), (33.0, (X, 300.0))]))
    assert len(ns) == 1
    assert ns[0].midi == pytest.approx(76 - (1.3 - 0.35) / 1.4 * 24, abs=1e-6)


def test_longer_string_is_lower_pitch():
    def pitch(index_x):
        e = InstrumentEngine()
        ns = notes(run(e, [(0.0, (X - 20, 200.0)), (33.0, (X - 20, 300.0))], s_kw={"index": (index_x, 250.0)}))
        return ns[0].midi
    assert pitch(300.0) > pitch(350.0) > pitch(400.0)


def test_velocity_grows_with_speed_and_upstroke_is_softer(solo_engine):
    def vel(dy, up=False):
        e = InstrumentEngine()
        a, b = (250.0 - dy / 2, 250.0 + dy / 2)
        if up:
            a, b = b, a
        return notes(run(e, [(0.0, (X, a)), (33.0, (X, b))]))[0].velocity
    assert vel(20) < vel(60) < vel(150)
    assert vel(150) == pytest.approx(1.0)
    assert vel(200, up=True) == pytest.approx(0.85)
    assert vel(60, up=True) < vel(60)


def test_direction_down_and_up_in_view(solo_engine):
    res = run(solo_engine, [(0.0, (X, 200.0)), (33.0, (X, 300.0)), (133.0, (X, 300.0)), (166.0, (X, 200.0))])
    dirs = [h.direction for _, v in res for h in v.hits]
    assert dirs == [1, -1]


def test_amplitude_decays_after_a_strike(solo_engine):
    res = run(solo_engine, [(0.0, (X, 200.0)), (33.0, (X, 300.0)), (633.0, (X, 300.0))])
    a0 = res[1][1].strings[0].amplitude
    a1 = res[2][1].strings[0].amplitude
    assert a1 == pytest.approx(a0 * math.exp(-1.0), rel=1e-6)


def test_speed_threshold_slow_crossing_never_plays(solo_engine):
    steps = [(i * 33.0, (X, 240.0 + i * 0.5)) for i in range(60)]     # ~0.15 pu/s
    res = run(solo_engine, steps)
    assert notes(res) == []
    # continue fast on the far side: still nothing (side already updated)
    res2 = run(solo_engine, [(60 * 33.0, (X, 290.0)), (61 * 33.0, (X, 320.0))])
    assert notes(res2) == []


def test_trembling_finger_on_the_string_never_double_plays(solo_engine):
    steps = [(0.0, (X, 200.0)), (33.0, (X, 260.0))]          # real strike, then tremble inside the band
    steps += [(33.0 + 10.0 * i, (X, 250.0 + (5.0 if i % 2 else -4.0))) for i in range(1, 60)]
    ns = notes(run(solo_engine, steps))
    assert len(ns) == 1


def test_repeated_crossings_respect_the_cooldown(solo_engine):
    steps = [(10.0 * i, (X, 250.0 + (12.0 if i % 2 else -12.0))) for i in range(40)]
    ns = notes(run(solo_engine, steps))
    assert ns
    # each NoteOn t is the frame time; the crossings are ~10 ms apart, cooldown 60 ms
    assert all(b.t_ms - a.t_ms >= 50.0 for a, b in zip(ns, ns[1:]))
    assert len(ns) <= 400 / 60 + 1


def test_tip_passing_beyond_the_string_end_does_not_play(solo_engine):
    assert notes(run(solo_engine, [(0.0, (420.0, 200.0)), (33.0, (420.0, 300.0))])) == []


# ---------------------------------------------------------------- chord layout

def test_chord_fast_strum_crosses_all_four_strings_in_one_frame(chord_engine):
    res = run(chord_engine, [(0.0, (X, 100.0)), (33.0, (X, 300.0))])
    ns = notes(res)
    assert [n.string for n in ns] == [0, 1, 2, 3]
    assert [n.delay_ms for n in ns] == pytest.approx([0.0, 5.0, 10.0, 15.0])   # 4.95 ms spacing -> 5 min
    zone_chord = res[-1][1].chord_label
    assert zone_chord == "D"                                 # palm y 380/480 -> bottom zone
    assert [n.midi for n in ns] == list(chord_voicing("D"))
    assert len({n.note_id for n in ns}) == 4
    hits = res[-1][1].hits
    assert [h.y for h in hits] == pytest.approx([160.0, 190.0, 220.0, 250.0])
    assert all(h.direction == 1 for h in hits)


def test_chord_strum_spacing_follows_crossing_times(chord_engine):
    res = run(chord_engine, [(0.0, (X, 140.0)), (33.0, (X, 270.0))])
    ns = notes(res)
    step = 30.0 / 130.0 * 33.0
    assert [n.delay_ms for n in ns] == pytest.approx([0.0, step, 2 * step, 3 * step])


def test_chord_strum_spacing_is_clamped_to_25ms(chord_engine):
    res = run(chord_engine, [(0.0, (X, 145.0)), (100.0, (X, 265.0))])
    ns = notes(res)
    assert len(ns) == 4
    assert [n.delay_ms for n in ns] == pytest.approx([0.0, 25.0, 50.0, 75.0])


def test_chord_upstroke_reverses_order_and_is_softer(chord_engine):
    res = run(chord_engine, [(0.0, (X, 300.0)), (33.0, (X, 100.0))])
    ns = notes(res)
    assert [n.string for n in ns] == [3, 2, 1, 0]
    assert all(h.direction == -1 for h in res[-1][1].hits)
    assert all(n.velocity == pytest.approx(0.85) for n in ns)


def test_chord_strum_split_over_frames_plays_every_string_once(chord_engine):
    steps = sweep(X, 100.0, 300.0, 8, dt=16.0)
    ns = notes(run(chord_engine, steps))
    assert sorted(n.string for n in ns) == [0, 1, 2, 3]


def test_chord_zone_selection_and_labels():
    e = InstrumentEngine(InstrumentConfig(layout="chord"))
    view = e.update(two_hands(0.0, (X, 100.0), s_kw={"palm": (300.0, 100.0)}), True)[1]
    assert view.chord_label == "Em"
    assert [s.label for s in view.strings] == ["E2", "B2", "E3", "G3"]
    assert [s.index for s in view.strings] == [0, 1, 2, 3]
    # palm above the string: offsets go down, the main string is on top (index 0)
    assert view.strings[0].p0 == pytest.approx((250.0, 250.0))
    assert view.strings[3].p0[1] == pytest.approx(340.0)
    view = e.update(two_hands(33.0, (X, 100.0), s_kw={"palm": (300.0, 160.0)}), True)[1]   # 0.333: hysteresis
    assert view.chord_label == "Em"
    view = e.update(two_hands(66.0, (X, 100.0), s_kw={"palm": (300.0, 190.0)}), True)[1]   # 0.396
    assert view.chord_label == "C"


def test_custom_chords_and_bad_names_fall_back():
    e = InstrumentEngine(InstrumentConfig(layout="chord", chords=("Am", "nope", "G7", "B7")))
    assert e.config.chords == ("Am", "C", "G7", "B7")
    e2 = InstrumentEngine(InstrumentConfig(layout="weird", scale="nope"))
    assert e2.config.layout == "solo" and e2.config.scale == "e_minor_pentatonic"


# ---------------------------------------------------------------- roles

def test_dominant_left_swaps_roles():
    e = InstrumentEngine(InstrumentConfig(dominant=Handedness.LEFT))
    s_kw = {"handedness": Handedness.RIGHT}
    p_kw = {"handedness": Handedness.LEFT}
    ns = notes(run(e, [(0.0, (X, 200.0)), (33.0, (X, 300.0))], s_kw=s_kw, p_kw=p_kw))
    assert len(ns) == 1
    # default roles with those labels: the hands swap roles -> nothing plays at this tip
    d = InstrumentEngine()
    assert notes(run(d, [(0.0, (X, 200.0)), (33.0, (X, 300.0))], s_kw=s_kw, p_kw=p_kw)) == []


@pytest.mark.parametrize("label", [Handedness.LEFT, Handedness.RIGHT, Handedness.UNKNOWN])
def test_same_label_hands_do_not_play(solo_engine, label):
    res = run(solo_engine, [(0.0, (X, 200.0)), (33.0, (X, 300.0))],
              s_kw={"handedness": label}, p_kw={"handedness": label})
    assert notes(res) == []
    assert res[-1][1].status == eng.STATUS_UNCERTAIN and not res[-1][1].playing


def test_missing_hand_status(solo_engine):
    _, v = solo_engine.update(frame(0.0, (string_hand(),)), True)
    assert v.status == eng.STATUS_NEED_PICK and not v.playing
    assert len(v.strings) == 1 and not v.strings[0].enabled
    _, v = solo_engine.update(frame(33.0, (pick_hand((X, 200.0)),)), True)
    assert v.status == eng.STATUS_NEED_STRING and v.strings == ()
    _, v = solo_engine.update(frame(66.0, ()), True)
    assert v.status == eng.STATUS_NEED_STRING


# ---------------------------------------------------------------- safety

def _fault(kind):
    """(s_kw, p_kw, ambiguous, t_offset) for the faulty frame."""
    return {
        "degraded_string": ({"quality": Quality.DEGRADED}, {}, False, 0.0),
        "unknown_string": ({"quality": Quality.UNKNOWN}, {}, False, 0.0),
        "degraded_pick": ({}, {"quality": Quality.DEGRADED}, False, 0.0),
        "zero_scale_string": ({"scale": 0.0}, {}, False, 0.0),
        "nan_scale_string": ({"scale": float("nan")}, {}, False, 0.0),
        "zero_scale_pick": ({}, {"scale": 0.0}, False, 0.0),
        "inf_scale_pick": ({}, {"scale": float("inf")}, False, 0.0),
        "ambiguous": ({}, {}, True, 0.0),
        "swap": ({"hand_id": 7}, {"hand_id": 8}, False, 0.0),
        "gap": ({}, {}, False, 200.0),
    }[kind]


FAULTS = ["degraded_string", "unknown_string", "degraded_pick", "zero_scale_string", "nan_scale_string",
          "zero_scale_pick", "inf_scale_pick", "ambiguous", "swap", "gap"]


@pytest.mark.parametrize("kind", FAULTS)
def test_unsafe_frame_plays_nothing_and_no_phantom_on_recovery(solo_engine, kind):
    s_kw, p_kw, amb, dt = _fault(kind)
    e = solo_engine
    ev0, _ = e.update(two_hands(0.0, (X, 200.0)), True)
    ev1, v1 = e.update(two_hands(33.0 + dt, (X, 300.0), ambiguous=amb, s_kw=s_kw, p_kw=p_kw), True)
    assert not [x for x in ev1 if isinstance(x, NoteOn)]
    assert not v1.playing and v1.status == eng.STATUS_UNCERTAIN
    assert all(not s.enabled for s in v1.strings)
    # recovery with the tip still below the string (same ids as the fault frame for "swap")
    rec_s = {"hand_id": 7} if kind == "swap" else {}
    rec_p = {"hand_id": 8} if kind == "swap" else {}
    ev2, v2 = e.update(two_hands(66.0 + dt, (X, 300.0), s_kw=rec_s, p_kw=rec_p), True)
    assert not [x for x in ev2 if isinstance(x, NoteOn)]
    assert v2.playing
    # a real crossing afterwards plays again
    ev3, _ = e.update(two_hands(99.0 + dt, (X, 200.0), s_kw=rec_s, p_kw=rec_p), True)
    assert len([x for x in ev3 if isinstance(x, NoteOn)]) == 1


def test_missing_hand_mid_strum_resets_side(solo_engine):
    e = solo_engine
    e.update(two_hands(0.0, (X, 200.0)), True)
    ev, _ = e.update(frame(33.0, (string_hand(),)), True)           # pick hand lost
    assert ev == []
    ev, _ = e.update(two_hands(66.0, (X, 300.0)), True)              # back, below the string
    assert ev == []


def test_degraded_frame_keeps_geometry_dimmed(solo_engine):
    _, v = solo_engine.update(two_hands(0.0, (X, 200.0), s_kw={"quality": Quality.DEGRADED}), True)
    assert len(v.strings) == 1 and not v.strings[0].enabled


def test_unsafe_frames_never_emit_alloff_or_cut_notes(solo_engine):
    res = run(solo_engine, [(0.0, (X, 200.0)), (33.0, (X, 300.0))])
    assert len(notes(res)) == 1
    ev, _ = solo_engine.update(two_hands(66.0, (X, 300.0), ambiguous=True), True)
    assert not any(isinstance(x, AllOff) for x in ev)


@pytest.mark.parametrize("tip_x,s_kw", [
    (X, {"palm": (315.0, 290.0)}),          # tip passes 0.4 pu from the string-hand palm
    (262.0, {}),                            # tip passes 0.12 pu from the thumb tip
])
def test_too_close_hands_do_not_play(solo_engine, tip_x, s_kw):
    res = run(solo_engine, [(0.0, (tip_x, 200.0)), (33.0, (tip_x, 252.0 + 6.5))], s_kw=s_kw)
    assert notes(res) == []
    assert res[-1][1].status == eng.STATUS_TOO_CLOSE and not res[-1][1].playing
    assert not res[-1][1].strings[0].enabled
    # moving away afterwards (still below) must not fire late
    res = run(solo_engine, [(66.0, (X, 320.0))])
    assert notes(res) == []


def test_pick_palm_overlapping_string_palm_is_too_close(solo_engine):
    p_kw = {"palm_offset": (-15.0, 130.0)}          # pick palm lands near the string-hand palm
    res = run(solo_engine, [(0.0, (X, 200.0)), (33.0, (X, 260.0))], p_kw=p_kw)
    assert notes(res) == [] and res[-1][1].status == eng.STATUS_TOO_CLOSE


def test_inactive_never_plays_and_resume_needs_fresh_observation(solo_engine):
    res = run(solo_engine, [(0.0, (X, 200.0)), (33.0, (X, 300.0))], active=False)
    assert all(evs == [] for evs, _ in res)
    v = res[-1][1]
    assert not v.playing and v.status == eng.STATUS_PAUSED and not v.strings[0].enabled
    solo_engine.update(two_hands(66.0, (X, 200.0)), False)
    ev, _ = solo_engine.update(two_hands(99.0, (X, 300.0)), True)    # first active frame observes
    assert ev == []


def test_duplicate_timestamp_does_not_fire(solo_engine):
    solo_engine.update(two_hands(0.0, (X, 200.0)), True)
    ev, _ = solo_engine.update(two_hands(0.0, (X, 300.0)), True)
    assert ev == []


# ---------------------------------------------------------------- bend

def _strike_then_index(engine, index_x, frames=20, start_t=33.0, dt=33.0):
    res = run(engine, [(0.0, (X, 200.0)), (start_t, (X, 300.0))])
    res += [engine.update(two_hands(start_t + dt * (i + 1), (X, 300.0), s_kw={"index": (index_x, 250.0)}), True)
            for i in range(frames)]
    return res


def test_longer_string_bends_down_and_is_clamped(solo_engine):
    res = _strike_then_index(solo_engine, 420.0)             # 1.7 pu: ~ -6.9 st raw -> clamp -2
    ns, bs = notes(res), bends(res)
    assert len(ns) == 1 and bs
    assert all(b.voice == ns[0].note_id for b in bs)
    assert all(-2.0 <= b.semitones < 0.0 for b in bs)
    assert bs[-1].semitones == pytest.approx(-2.0)
    assert res[-1][1].note_label == "B3 -2.0"


def test_shorter_string_bends_up_partial(solo_engine):
    res = _strike_then_index(solo_engine, 374.0, frames=40)  # 1.24 pu: +1.03 st
    bs = bends(res)
    assert bs and all(b.semitones > 0 for b in bs)
    assert bs[-1].semitones == pytest.approx((1.3 - 1.24) / 1.4 * 24, abs=0.05)
    assert res[-1][1].note_label.startswith("B3 +1.0")


def test_bend_is_sent_only_on_change_and_stops_after_sustain(solo_engine):
    res = _strike_then_index(solo_engine, 374.0, frames=40)
    n_before = len(bends(res))
    steady = [solo_engine.update(two_hands(33.0 * 42 + 33.0 * i, (X, 300.0), s_kw={"index": (374.0, 250.0)}), True)
              for i in range(5)]
    assert bends(steady) == []                               # converged: |change| <= 0.02
    late = [solo_engine.update(two_hands(3000.0 + 33.0 * i, (X, 300.0), s_kw={"index": (420.0, 250.0)}), True)
            for i in range(3)]
    assert bends(late) == [] and n_before > 0


def test_tremor_gives_small_vibrato_bends(solo_engine):
    res = run(solo_engine, [(0.0, (X, 200.0)), (33.0, (X, 300.0))])
    res += [solo_engine.update(two_hands(33.0 + 16.0 * (i + 1), (X, 300.0),
                                         s_kw={"index": (380.0 + 1.5 * math.sin(i * 1.3), 250.0)}), True)
            for i in range(40)]
    bs = bends(res)
    assert bs and max(abs(b.semitones) for b in bs) < 0.5


def test_no_bend_in_chord_layout(chord_engine):
    res = _strike_then_index(chord_engine, 420.0)
    assert bends(res) == []


def test_quantized_label_does_not_flicker_near_a_degree_boundary(solo_engine):
    boundary_len = 0.35 + (76 - 60.5) / 24 * 1.4            # between B3 (59) and D4 (62)
    xs = [250.0 + boundary_len * 100 + (0.6 if i % 2 else -0.6) for i in range(30)]
    labels = {solo_engine.update(two_hands(33.0 * i, (X, 150.0), s_kw={"index": (x, 250.0)}), True)[1]
              .strings[0].label for i, x in enumerate(xs)}
    assert len(labels) == 1


# ---------------------------------------------------------------- reset / all_off

def test_all_off_resets_and_returns_event(solo_engine):
    run(solo_engine, [(0.0, (X, 200.0))])
    off = solo_engine.all_off(50.0)
    assert off == AllOff(fade_ms=20.0, t_ms=50.0)
    ev, _ = solo_engine.update(two_hands(66.0, (X, 300.0)), True)     # fresh observation needed
    assert ev == []


def test_configure_switches_layout_and_resets(solo_engine):
    run(solo_engine, [(0.0, (X, 100.0))])
    solo_engine.configure(InstrumentConfig(layout="chord"))
    ev, v = solo_engine.update(two_hands(33.0, (X, 300.0)), True)
    assert ev == [] and v.layout == "chord" and len(v.strings) == 4
