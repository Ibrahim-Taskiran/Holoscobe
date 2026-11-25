from __future__ import annotations

import math

import pytest

from handcontrol.instrument import geometry as g
from handcontrol.instrument import music as m
from handcontrol.instrument.events import CHORD_NAMES, DEFAULT_CHORDS, SCALE_NAMES


# ---------------------------------------------------------------- geometry

def test_cross_and_signed_distance_sign():
    assert g.cross((1, 0), (0, 1)) == 1
    a, b = (0.0, 0.0), (10.0, 0.0)
    assert g.signed_distance((5, 3), a, b) == pytest.approx(3.0)    # image y down -> positive below
    assert g.signed_distance((5, -2), a, b) == pytest.approx(-2.0)
    assert g.normal(a, b) == pytest.approx((0.0, 1.0))


def test_zero_length_segments_are_safe():
    p = (1.0, 1.0)
    assert g.signed_distance((3, 4), p, p) == 0.0
    assert g.project_param((3, 4), p, p) == 0.0
    assert g.point_segment_distance((4, 5), p, p) == pytest.approx(5.0)
    assert g.normal(p, p) == (0.0, 0.0)
    assert g.normalize((0.0, 0.0)) == (0.0, 0.0)
    assert g.segment_intersection(p, p, (0, 0), (2, 2)) is None


def test_segment_intersection_parameters():
    hit = g.segment_intersection((0, -1), (0, 3), (-2, 0), (2, 0))
    assert hit == pytest.approx((0.25, 0.5))
    assert g.segment_intersection((0, 1), (0, 3), (-2, 0), (2, 0)) is None       # stops short
    assert g.segment_intersection((0, 0), (1, 0), (0, 1), (1, 1)) is None        # parallel
    assert g.segment_intersection((3, -1), (3, 1), (-2, 0), (2, 0)) is None      # beyond the end


def test_point_segment_distance_and_projection():
    a, b = (0.0, 0.0), (10.0, 0.0)
    assert g.point_segment_distance((5, 4), a, b) == pytest.approx(4.0)
    assert g.point_segment_distance((13, 4), a, b) == pytest.approx(5.0)
    assert g.project_param((15, 1), a, b) == pytest.approx(1.5)
    assert g.lerp(a, b, 0.3) == pytest.approx((3.0, 0.0))


# ---------------------------------------------------------------- music

def test_note_names_and_hz():
    assert m.midi_to_name(52) == "E3"
    assert m.midi_to_name(69) == "A4"
    assert m.midi_to_name(61.4) == "C#4"
    assert m.midi_to_name(59.6) == "C4"
    assert m.midi_to_name(float("nan")) == ""
    assert m.midi_to_hz(69) == pytest.approx(440.0)
    assert m.midi_to_hz(57) == pytest.approx(220.0)


@pytest.mark.parametrize("name", SCALE_NAMES)
def test_every_scale_name_is_supported(name):
    p = m.scale_pitches(name, 52, 76)
    assert p and all(52 <= x <= 76 for x in p) and list(p) == sorted(p)
    root_pc = m.SCALES[name][0]
    assert any(x % 12 == root_pc for x in p)


def test_scale_contents():
    assert m.scale_pitches("e_minor_pentatonic", 52, 64) == (52, 55, 57, 59, 62, 64)
    assert len(m.scale_pitches("chromatic", 52, 76)) == 25
    with pytest.raises(ValueError):
        m.scale_pitches("nope", 0, 10)


@pytest.mark.parametrize("name", CHORD_NAMES)
def test_every_chord_name_has_an_ascending_guitar_voicing(name):
    v = m.chord_voicing(name)
    assert len(v) == 4 and list(v) == sorted(v) and len(set(v)) == 4
    assert 40 <= v[0] <= 51                      # root in E2..D#3
    pc, quality = m.parse_chord(name)
    assert int(v[0]) % 12 == pc
    third = 3 if quality in ("m", "m7") else 4
    assert any((int(x) - int(v[0])) % 12 == third for x in v)
    assert any((int(x) - int(v[0])) % 12 == 7 for x in v)


def test_default_chords_and_examples():
    assert DEFAULT_CHORDS == ("Em", "C", "G", "D")
    assert m.chord_voicing("Em") == (40.0, 47.0, 52.0, 55.0)     # E2 B2 E3 G3
    assert m.chord_voicing("C") == (48.0, 55.0, 60.0, 64.0)
    assert m.chord_voicing("G7") == (43.0, 50.0, 53.0, 59.0)
    with pytest.raises(ValueError):
        m.chord_voicing("Hm")
    with pytest.raises(ValueError):
        m.chord_voicing("Csus9")


def test_continuous_pitch_longer_is_lower_and_clamped():
    kw = dict(low=52, high=76, min_len=0.35, max_len=1.75)
    assert m.continuous_pitch(0.35, **kw) == pytest.approx(76)
    assert m.continuous_pitch(1.75, **kw) == pytest.approx(52)
    assert m.continuous_pitch(0.1, **kw) == pytest.approx(76)
    assert m.continuous_pitch(3.0, **kw) == pytest.approx(52)
    vals = [m.continuous_pitch(0.35 + i * 0.1, **kw) for i in range(15)]
    assert all(a > b for a, b in zip(vals, vals[1:]))


def test_quantize_hysteresis_holds_near_the_boundary():
    pitches = (52, 55, 57)
    cur = m.quantize_pitch(53.0, pitches)
    assert cur == 52
    # midpoint 52/55 is 53.5: small excursions past it keep the degree
    for p in (53.4, 53.6, 53.7, 53.5, 53.75):
        cur = m.quantize_pitch(p, pitches, cur, hysteresis=0.3)
        assert cur == 52
    cur = m.quantize_pitch(53.9, pitches, cur, hysteresis=0.3)
    assert cur == 55
    for p in (53.4, 53.3, 53.25):                  # coming back needs < 53.2
        cur = m.quantize_pitch(p, pitches, cur, hysteresis=0.3)
        assert cur == 55
    assert m.quantize_pitch(53.1, pitches, cur, hysteresis=0.3) == 52
    assert m.quantize_pitch(60.0, (), None) == 60.0


def test_chord_zone_mapping_and_hysteresis():
    assert [m.chord_zone(y) for y in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)] == [0, 0, 1, 2, 3, 3]
    boundary = 0.15 + 0.175          # zone 0 | 1
    z = m.chord_zone(boundary - 0.01)
    assert z == 0
    z = m.chord_zone(boundary + 0.02, z)
    assert z == 0                     # inside hysteresis
    z = m.chord_zone(boundary + 0.04, z)
    assert z == 1
    z = m.chord_zone(boundary - 0.02, z)
    assert z == 1
    z = m.chord_zone(boundary - 0.04, z)
    assert z == 0
    assert m.chord_zone(math.nan, 2) == 2
