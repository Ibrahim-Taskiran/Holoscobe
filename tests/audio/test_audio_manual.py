"""Real-device checks (audible). Skipped by default; run with:

    .venv/Scripts/python.exe -m pytest -q -s -p no:cacheprovider -m manual tests/audio/test_audio_manual.py

A human must listen: these tests only prove that a stream opens and the callback keeps up.
"""
from __future__ import annotations

import time

import pytest

from handcontrol.instrument.audio import AudioOutput, list_output_devices
from handcontrol.instrument.events import NoteOn
from handcontrol.instrument.synth import GuitarSynth

pytestmark = pytest.mark.manual


def test_list_real_devices():
    devs = list_output_devices()
    for d in devs:
        print(d)
    assert devs


@pytest.mark.parametrize("latency", ["low", "normal"])
def test_real_stream_strum_and_stats(latency):
    errors: list[str] = []
    out = AudioOutput(GuitarSynth(volume=0.3), latency=latency, on_error=errors.append)
    assert out.start(), errors
    try:
        now = time.monotonic() * 1000.0
        for i, m in enumerate((40, 45, 50, 55, 59, 64)):          # E-minor-ish strum, 25 ms apart
            out.push(NoteOn(string=i, midi=float(m), velocity=0.8, note_id=i, t_ms=now, delay_ms=25.0 * i))
        time.sleep(2.0)
        st = out.stats()
        print(st)
        assert st.callbacks > 0 and errors == []
        assert st.load_max < 1.0
    finally:
        out.stop()


def test_real_test_tone_temporary_stream():
    errors: list[str] = []
    out = AudioOutput(GuitarSynth(volume=0.3), on_error=errors.append)
    assert out.play_test_tone(), errors
    time.sleep(2.0)
    assert not out.running and errors == []
