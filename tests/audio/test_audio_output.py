"""AudioOutput with a fake sounddevice backend (no real device)."""
from __future__ import annotations

import threading
import time

import numpy as np
import pytest
from _audio_support import FakeBackend, FakeFlags

from handcontrol.instrument import audio as audio_mod
from handcontrol.instrument.audio import AudioOutput, list_output_devices
from handcontrol.instrument.events import AllOff, Bend, NoteOn
from handcontrol.instrument.synth import GuitarSynth


def make(backend=None, errors=None, **kw):
    errors = errors if errors is not None else []
    kw.setdefault("stall_timeout_s", None)
    out = AudioOutput(backend=backend or FakeBackend(), on_error=errors.append, **kw)
    return out, errors


def note(i=1, t_ms=0.0, **kw):
    return NoteOn(string=kw.pop("string", 0), midi=kw.pop("midi", 52.0), velocity=0.9, note_id=i, t_ms=t_ms, **kw)


# ---------- device listing ----------

def test_list_output_devices_unique_wasapi_first():
    devs = list_output_devices(FakeBackend())
    names = [d.name for d in devs]
    assert len(names) == len(set(names))
    assert devs[0].hostapi == "Windows WASAPI" and devs[0].default and devs[0].name == "Hoparlör (Realtek(R) Audio)"
    assert "Mikrofon (USB)" not in names
    assert "Kulaklık (Soundcore Life Q30" not in names          # MME-truncated duplicate dropped
    assert "Kulaklık (Soundcore Life Q30)" in names
    assert all(d.hostapi != "Windows WDM-KS" for d in devs)


def test_list_output_devices_never_raises():
    class Broken:
        def query_hostapis(self):
            raise RuntimeError("boom")
    assert list_output_devices(Broken()) == []


# ---------- stream opening ----------

def test_start_prefers_wasapi_low_latency():
    be = FakeBackend()
    out, errors = make(be)
    assert out.start() is True
    kw = be.stream.kw
    assert be.hostapi_of(kw["device"]) == "Windows WASAPI" and kw["device"] == 5
    assert kw["samplerate"] == 48000 and kw["blocksize"] == 128 and kw["latency"] == "low"
    assert kw["channels"] == 2 and kw["dtype"] == "float32"
    assert kw["extra_settings"].auto_convert is True
    st = out.stats()
    assert st.running and st.hostapi == "Windows WASAPI" and st.output_latency_ms == pytest.approx(10.0)
    out.stop()
    assert errors == []


def test_normal_latency_blocksize():
    be = FakeBackend()
    out, _ = make(be, latency="normal")
    assert out.start()
    assert be.stream.kw["blocksize"] == 256
    out.stop()


def test_fallback_directsound_then_mme():
    be = FakeBackend(fail=lambda kw: kw["device"] in (5, 6))
    out, errors = make(be)
    assert out.start()
    assert be.hostapi_of(be.stream.kw["device"]) == "Windows DirectSound"
    assert "extra_settings" not in be.stream.kw
    out.stop()
    be2 = FakeBackend(fail=lambda kw: kw["device"] in (3, 4, 5, 6))
    out2, errors2 = make(be2)
    assert out2.start()
    assert be2.hostapi_of(be2.stream.kw["device"]) == "MME"
    assert out2.stats().hostapi == "MME"
    out2.stop()
    assert errors == [] and errors2 == []


def test_samplerate_fallback_resizes_synth():
    be = FakeBackend(fail=lambda kw: kw["device"] in (5, 6) or kw["samplerate"] == 48000)
    synth = GuitarSynth(volume=0.7, tone="electric")
    out, _ = make(be, synth=synth)
    assert out.start()
    assert be.stream.kw["samplerate"] == 44100
    assert out.synth.sample_rate == 44100 and out.synth.volume == 0.7 and out.synth.tone == "electric"
    assert out.stats().sample_rate == 44100
    out.push(note())
    assert np.any(be.stream.drive() != 0)
    out.stop()


def test_device_by_name_and_unknown_name_uses_default():
    be = FakeBackend()
    out, _ = make(be, device="Kulaklık (Soundcore Life Q30)")
    assert out.start()
    assert be.stream.kw["device"] == 6
    out.stop()
    be2 = FakeBackend()
    out2, _ = make(be2, device="Olmayan Cihaz")
    assert out2.start()
    assert be2.stream.kw["device"] == 5
    out2.stop()


def test_device_name_matches_truncated_mme_name():
    be = FakeBackend(fail=lambda kw: be.hostapi_of(kw["device"]) != "MME")
    out, _ = make(be, device="Kulaklık (Soundcore Life Q30)")
    assert out.start()
    assert be.stream.kw["device"] == 1
    out.stop()


def test_mono_device_gets_one_channel():
    devices = [("Mono Hoparlör", 2, 1, 48000.0)]
    be = FakeBackend(devices=devices, defaults={2: 0})
    out, _ = make(be)
    assert out.start()
    assert be.stream.kw["channels"] == 1
    out.push(note())
    assert np.any(be.stream.drive() != 0)
    out.stop()


def test_all_fail_returns_false_with_turkish_error():
    be = FakeBackend(fail=lambda kw: True)
    out, errors = make(be)
    assert out.start() is False
    assert not out.running
    assert len(errors) == 1 and errors[0].startswith("Ses çıkışı açılamadı")
    assert len(be.attempts) >= 3


def test_missing_backend_reports_error():
    class NoDevices:
        def query_hostapis(self):
            raise OSError("PortAudio yok")
        query_devices = query_hostapis
    out, errors = make(NoDevices())
    assert out.start() is False
    assert errors and "Ses" in errors[0]


# ---------- callback ----------

def test_events_consumed_in_callback_and_stereo_copy():
    be = FakeBackend()
    out, _ = make(be)
    out.start()
    out.push(note(1))
    out.push(Bend(voice=1, semitones=1.0, t_ms=0.0))
    data = be.stream.drive()
    assert len(out._queue) == 0
    assert np.any(data != 0) and np.array_equal(data[:, 0], data[:, 1])
    assert np.max(np.abs(data)) <= 10 ** (-3 / 20)
    out.push(AllOff(fade_ms=5.0))
    for _ in range(5):
        data = be.stream.drive()
    assert np.all(data == 0)
    out.stop()


def test_push_from_another_thread_while_callback_runs():
    handled = []

    class Spy(GuitarSynth):
        def handle(self, event):
            handled.append(event)
            super().handle(event)

    be = FakeBackend()
    out, errors = make(be, synth=Spy())
    out.start()
    total = 400

    def producer():
        for i in range(total):
            out.push(note(i, string=i % 6))
            if i % 50 == 0:
                time.sleep(0.001)

    t = threading.Thread(target=producer)
    t.start()
    deadline = time.monotonic() + 10
    while (t.is_alive() or out._queue) and time.monotonic() < deadline:
        be.stream.drive()
    t.join()
    be.stream.drive()
    assert len(handled) == total
    assert out.synth.active_voices <= 8
    out.stop()
    assert errors == []


def test_queue_is_bounded_and_keeps_alloff():
    out, _ = make()
    out.push(AllOff(fade_ms=10.0))
    for i in range(audio_mod.MAX_QUEUE + 100):
        out.push(note(i))
    assert len(out._queue) <= audio_mod.MAX_QUEUE
    assert out._overflow_alloff is not None


def test_stats_timing_latency_underflows():
    t = [0.0]

    def perf():
        t[0] += 0.0005
        return t[0]

    be = FakeBackend(stream_latency=0.010)
    out, _ = make(be, clock_ms=lambda: 1000.0, perf_clock=perf)
    out.start()
    out.push(note(1, t_ms=950.0))
    be.stream.drive()
    be.stream.drive(status=FakeFlags(output_underflow=True))
    st = out.stats()
    assert st.callbacks == 2 and st.underflows == 1
    assert st.callback_ms_mean == pytest.approx(0.5) and st.callback_ms_max == pytest.approx(0.5)
    assert st.load_max == pytest.approx(0.0005 * 48000 / 128)
    assert st.event_latency_ms_last == pytest.approx(60.0) and st.event_latency_ms_mean == pytest.approx(60.0)
    assert st.blocksize == 128 and st.device == "Hoparlör (Realtek(R) Audio)"
    out.stop()


def test_set_volume_and_tone_reach_synth():
    out, _ = make()
    out.set_volume(0.2)
    out.set_tone("electric")
    assert out.synth.volume == 0.2 and out.synth.tone == "electric"


# ---------- errors / lifecycle ----------

def test_device_lost_reports_once_and_stops():
    be = FakeBackend()
    out, errors = make(be)
    out.start()
    be.stream.drive()
    be.stream.die()
    out.stats()
    out.stats()
    assert not out.running
    assert len(errors) == 1 and errors[0].startswith("Ses cihazı hatası")
    assert be.stream.closed
    out.stop()
    out.stop()
    assert len(errors) == 1


def test_device_lost_reported_by_watchdog():
    be = FakeBackend()
    out, errors = make(be)
    out.start()
    be.stream.die()
    deadline = time.monotonic() + 3
    while not errors and time.monotonic() < deadline:
        time.sleep(0.02)
    assert len(errors) == 1 and not out.running
    out.stop()


def test_callback_exception_outputs_silence_and_reports():
    class Bad(GuitarSynth):
        def render(self, frames, out=None):
            raise RuntimeError("bozuk")

    be = FakeBackend()
    out, errors = make(be, synth=Bad())
    out.start()
    data = be.stream.drive()
    assert np.all(data == 0)
    out.stats()
    assert len(errors) == 1 and "Ses cihazı hatası" in errors[0] and "bozuk" in errors[0]
    out.stop()


def test_stall_detected():
    be = FakeBackend()
    out, errors = make(be, stall_timeout_s=0.1)
    out.start()
    deadline = time.monotonic() + 3
    while not errors and time.monotonic() < deadline:
        time.sleep(0.02)
    assert errors and errors[0].startswith("Ses cihazı hatası")
    out.stop()


def test_stop_idempotent_and_no_error_on_normal_stop():
    be = FakeBackend()
    out, errors = make(be)
    out.stop()                       # before start
    out.start()
    stream = be.stream
    stream.drive()
    out.stop()
    out.stop()
    assert stream.closed and not out.running and errors == []
    assert out.start()               # restart works
    assert len(be.opened) == 2
    out.stop()


def test_on_error_may_call_stop():
    be = FakeBackend()
    holder = {}
    calls = []

    def on_error(text):
        calls.append(text)
        holder["out"].stop()

    out = AudioOutput(backend=be, on_error=on_error, stall_timeout_s=None)
    holder["out"] = out
    out.start()
    be.stream.die()
    deadline = time.monotonic() + 3
    while not calls and time.monotonic() < deadline:
        time.sleep(0.02)
    assert len(calls) == 1 and not out.running


# ---------- test tone ----------

def test_test_tone_opens_temporary_stream(monkeypatch):
    monkeypatch.setattr(audio_mod, "TEST_TONE_S", 0.1)
    be = FakeBackend()
    out, errors = make(be)
    assert out.play_test_tone() is True
    stream = be.stream
    assert out.running
    assert sum(1 for e in out._queue if isinstance(e, NoteOn)) == 4
    heard = np.concatenate([stream.drive() for _ in range(40)])
    assert np.any(heard != 0)
    deadline = time.monotonic() + 3
    while out.running and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not out.running and stream.closed and errors == []
    assert out.stats().event_latency_ms_last == 0.0          # test tone does not skew latency stats


def test_test_tone_on_running_stream_reuses_it():
    be = FakeBackend()
    out, _ = make(be)
    out.start()
    assert out.play_test_tone()
    assert len(be.opened) == 1 and len(out._queue) == 4
    out.stop()


def test_start_during_test_tone_adopts_stream(monkeypatch):
    monkeypatch.setattr(audio_mod, "TEST_TONE_S", 0.05)
    be = FakeBackend()
    out, _ = make(be)
    out.play_test_tone()
    assert out.start()
    time.sleep(0.2)
    assert out.running and len(be.opened) == 1
    out.stop()


def test_test_tone_fails_without_device():
    be = FakeBackend(fail=lambda kw: True)
    out, errors = make(be)
    assert out.play_test_tone() is False
    assert errors
