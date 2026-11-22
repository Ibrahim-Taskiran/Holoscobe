"""Offline DSP tests for GuitarSynth (no audio device)."""
from __future__ import annotations

import math

import numpy as np
import pytest
from _audio_support import SR, fundamental_hz, render_blocks, rms, spectral_centroid

from handcontrol.instrument.events import AllOff, Bend, NoteOn
from handcontrol.instrument.synth import GuitarSynth, midi_to_hz

CEIL = 10 ** (-3 / 20)


def pluck(midi, vel=0.8, seconds=2.0, **kw):
    s = GuitarSynth(**kw)
    s.note_on(midi, vel, 1)
    return render_blocks(s, int(seconds * SR))


@pytest.mark.parametrize("midi", [40, 45, 52, 59, 64, 76, 88])
def test_fundamental_within_one_percent(midi):
    y = pluck(midi)
    f = fundamental_hz(y, SR, midi_to_hz(midi))
    err = f / midi_to_hz(midi) - 1.0
    print(f"midi {midi}: {f:.3f} Hz, error {err * 100:+.4f} %")
    assert abs(err) < 0.01


@pytest.mark.parametrize("midi,sr", [(40, 44100), (64, 44100), (52, 96000)])
def test_tuning_other_sample_rates(midi, sr):
    s = GuitarSynth(sample_rate=sr)
    s.note_on(midi, 0.8, 1)
    y = render_blocks(s, 2 * sr)
    assert abs(fundamental_hz(y, sr, midi_to_hz(midi)) / midi_to_hz(midi) - 1.0) < 0.01


def _decay_ratio(y):
    return rms(y[int(1.5 * SR):int(2.0 * SR)]) / rms(y[int(0.05 * SR):int(0.3 * SR)])


def test_decay_present_and_low_notes_ring_longer():
    low, mid, high = (_decay_ratio(pluck(m)) for m in (40, 52, 76))
    assert low < 0.3          # clearly decaying
    assert low > mid > high


def test_voice_released_after_silence():
    s = GuitarSynth()
    s.note_on(84, 1.0, 1)
    render_blocks(s, 6 * SR)
    assert s.active_voices == 0
    assert np.all(s.render(256) == 0.0)


def test_no_nan_inf_under_fuzz():
    rng = np.random.default_rng(7)
    s = GuitarSynth(volume=1.0)
    for b in range(1500):
        r = rng.random()
        if r < 0.25:
            s.note_on(float(rng.uniform(10, 120)), float(rng.uniform(-0.5, 1.5)), b, int(rng.integers(0, 6)),
                      int(rng.integers(0, 2000)))
        elif r < 0.35:
            s.bend(int(rng.integers(max(0, b - 20), b + 1)), float(rng.uniform(-3, 3)))
        elif r < 0.37:
            s.all_off(float(rng.uniform(0, 50)))
        elif r < 0.38:
            s.set_tone("electric" if rng.random() < 0.5 else "clean")
        if b == 700:
            s.note_on(float("nan"), 1.0, 99999)
            s.bend(99999, float("inf"))
            s.set_volume(float("nan"))
        y = s.render(int(rng.integers(1, 600)))
        assert np.all(np.isfinite(y))
        assert np.max(np.abs(y), initial=0.0) <= CEIL
        assert s.active_voices <= 8


@pytest.mark.parametrize("tone", ["clean", "electric"])
def test_limiter_ceiling_never_exceeded(tone):
    s = GuitarSynth(volume=1.0, tone=tone)
    peak = 0.0
    for b in range(400):
        if b % 25 == 0:
            for i, m in enumerate((40, 45, 50, 55, 59, 64, 69, 76)):
                s.note_on(m, 1.0, b * 10 + i, string=i)
        y = s.render(128)
        peak = max(peak, float(np.max(np.abs(y))))
    assert peak <= CEIL
    assert peak > 0.5          # the limiter limits, it does not mute


def test_default_volume_half():
    assert GuitarSynth().volume == 0.5


def test_volume_scales_level():
    def level(vol):
        s = GuitarSynth(volume=vol)
        s.note_on(52, 0.6, 1)
        return rms(render_blocks(s, SR // 2))
    assert level(0.25) == pytest.approx(level(0.5) / 2, rel=0.02)


def _bent(semis):
    s = GuitarSynth()
    s.note_on(57, 0.9, 5)                     # A3
    render_blocks(s, int(0.05 * SR))
    s.handle(Bend(voice=5, semitones=semis, t_ms=0.0))
    render_blocks(s, int(0.1 * SR))           # let the bend settle
    return render_blocks(s, int(1.5 * SR))


@pytest.mark.parametrize("semis", [2.0, -2.0, 0.5])
def test_bend_changes_frequency_by_expected_ratio(semis):
    y = _bent(semis)
    expected = midi_to_hz(57 + semis)
    f = fundamental_hz(y, SR, expected, skip_s=0.0)
    print(f"bend {semis:+}: {f:.3f} Hz, error {(f / expected - 1) * 100:+.4f} %")
    assert abs(f / expected - 1.0) < 0.01
    if semis > 0:
        assert f > midi_to_hz(57)
    else:
        assert f < midi_to_hz(57)


def _band_energy(y, f, width=0.01):
    mag = np.abs(np.fft.rfft(y.astype(np.float64) * np.hanning(len(y))))
    freqs = np.fft.rfftfreq(len(y), 1.0 / SR)
    sel = (freqs > f * (1 - width)) & (freqs < f * (1 + width))
    return float((mag[sel] ** 2).sum())


def test_voice_stealing_keeps_polyphony_and_newest_audible():
    outs = []
    for with_new in (False, True):
        s = GuitarSynth()
        for i in range(8):
            s.note_on(40 + 5 * i, 1.0, i, string=i)
        render_blocks(s, SR // 2)
        assert s.active_voices == 8
        if with_new:
            s.note_on(93.5, 1.0, 100, string=8)     # between the harmonics of the others
        outs.append(render_blocks(s, SR // 10))
        assert s.active_voices <= 8
    assert any(v.state == 1 and v.note_id == 100 for v in s._voices)
    f = midi_to_hz(93.5)
    assert _band_energy(outs[1], f) > 4 * _band_energy(outs[0], f)


def test_many_notes_never_exceed_polyphony():
    s = GuitarSynth()
    for i in range(30):
        s.note_on(45 + i % 20, 1.0, i, string=i)
        s.render(64)
        assert s.active_voices <= 8


def test_repluck_same_string_replaces_voice():
    s = GuitarSynth()
    s.note_on(40, 1.0, 1, string=2)
    render_blocks(s, SR // 4)
    s.note_on(52, 1.0, 2, string=2)
    y = render_blocks(s, SR)
    assert s.active_voices == 1
    assert [v.note_id for v in s._voices if v.state == 1] == [2]
    assert abs(fundamental_hz(y, SR, midi_to_hz(52), skip_s=0.02) / midi_to_hz(52) - 1) < 0.01


def test_repluck_has_no_click():
    s = GuitarSynth()
    s.note_on(40, 1.0, 1, string=0)
    before = render_blocks(s, SR // 4)
    s.note_on(40, 0.1, 2, string=0)           # soft re-pluck of a loud ringing string
    after = render_blocks(s, SR // 20)
    assert np.max(np.abs(np.diff(after))) <= 1.5 * np.max(np.abs(np.diff(before[-SR // 10:])))


def test_all_off_fades_to_silence_without_click():
    s = GuitarSynth(volume=1.0)
    for i, m in enumerate((40, 47, 52, 56, 59, 64)):
        s.note_on(m, 1.0, i, string=i)
    before = render_blocks(s, SR // 5, block=256)
    s.handle(AllOff(fade_ms=20.0, t_ms=0.0))
    fade_n = int(0.020 * SR)
    after = render_blocks(s, fade_n + 256, block=256)
    assert np.all(after[fade_n:] == 0.0)
    assert s.active_voices == 0
    jump_before = np.max(np.abs(np.diff(before[-SR // 10:])))
    jump_fade = np.max(np.abs(np.diff(np.concatenate([before[-1:], after]))))
    assert jump_fade <= 1.2 * jump_before
    assert np.all(render_blocks(s, 2048) == 0.0)


def test_all_off_drops_pending_delayed_notes():
    s = GuitarSynth()
    s.note_on(52, 1.0, 1, delay_samples=5000)
    s.all_off(10.0)
    assert np.all(render_blocks(s, 8000) == 0.0)


@pytest.mark.parametrize("delay", [0, 1, 127, 128, 300, 1000])
def test_delay_samples_sample_accurate_across_blocks(delay):
    ref = GuitarSynth()
    ref.note_on(52, 0.8, 1)
    a = render_blocks(ref, 4000, block=4000 if 4000 <= ref.max_block else ref.max_block)
    s = GuitarSynth()
    s.note_on(52, 0.8, 1, delay_samples=delay)
    b = render_blocks(s, 4000 + delay, block=128)
    assert np.all(b[:delay] == 0.0)
    assert b[delay] != 0.0
    np.testing.assert_allclose(b[delay:], a, atol=1e-6)


def test_handle_noteon_delay_ms():
    s = GuitarSynth()
    s.handle(NoteOn(string=0, midi=52.0, velocity=0.8, note_id=1, t_ms=0.0, delay_ms=10.0))
    y = render_blocks(s, 1000, block=128)
    assert int(np.flatnonzero(y)[0]) == 480


def test_strum_two_delayed_notes_same_block():
    s = GuitarSynth()
    s.note_on(40, 0.8, 1, string=0, delay_samples=10)
    s.note_on(45, 0.8, 2, string=1, delay_samples=50)
    y = s.render(256)
    assert np.all(y[:10] == 0.0) and y[10] != 0.0
    assert s.active_voices == 2


def test_velocity_affects_level_and_brightness():
    soft = pluck(52, vel=0.2, seconds=0.5)
    hard = pluck(52, vel=1.0, seconds=0.5)
    assert rms(hard) > 3 * rms(soft)
    seg = slice(0, SR // 5)
    assert spectral_centroid(hard[seg], SR) > 1.2 * spectral_centroid(soft[seg], SR)


def test_electric_differs_from_clean():
    clean = pluck(52, vel=0.9, seconds=1.0)
    elec = pluck(52, vel=0.9, seconds=1.0, tone="electric")
    assert np.max(np.abs(clean - elec)) > 0.02
    assert 0.3 < rms(elec) / rms(clean) < 4.0
    assert abs(fundamental_hz(elec, SR, midi_to_hz(52)) / midi_to_hz(52) - 1) < 0.01


def test_tone_switch_is_smooth():
    s = GuitarSynth()
    s.note_on(45, 0.9, 1)
    before = render_blocks(s, SR // 4)
    s.set_tone("electric")
    after = render_blocks(s, 1024)
    assert np.max(np.abs(np.diff(after))) < 3 * np.max(np.abs(np.diff(before[-4096:]))) + 0.02


def test_determinism_same_seed():
    def run(seed):
        s = GuitarSynth(seed=seed)
        s.note_on(45, 0.7, 1)
        s.note_on(57, 0.9, 2, string=1, delay_samples=333)
        s.bend(2, 1.0)
        return render_blocks(s, 20000, block=200)
    assert np.array_equal(run(3), run(3))
    assert not np.array_equal(run(3), run(4))


def test_render_out_param_and_large_frames():
    s = GuitarSynth(max_block=256)
    s.note_on(52, 0.8, 1)
    buf = np.zeros(1000, dtype=np.float32)
    y = s.render(1000, out=buf)
    assert y.dtype == np.float32 and len(y) == 1000 and np.shares_memory(y, buf)
    assert np.any(buf != 0)
    z = s.render(100)
    assert z.dtype == np.float32 and len(z) == 100


def test_set_volume_is_smoothed():
    s = GuitarSynth(volume=0.0)
    s.note_on(45, 1.0, 1)
    s.render(256)
    s.set_volume(1.0)
    y = s.render(256)
    assert abs(y[0]) < 0.05
    assert math.isclose(s._vol_cur, 1.0)


def test_with_sample_rate_keeps_settings():
    s = GuitarSynth(volume=0.3, tone="electric")
    t = s.with_sample_rate(44100)
    assert (t.sample_rate, t.volume, t.tone, t.polyphony) == (44100, 0.3, "electric", 8)
