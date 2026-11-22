from __future__ import annotations

import math
import threading
import time

import pytest

from handcontrol.contracts import CameraState, ControlState, Mode
from handcontrol.instrument.engine import InstrumentConfig, InstrumentEngine
from handcontrol.instrument.events import AllOff, Bend, NoteOn
from handcontrol.instrument.session import InstrumentSession, SessionStats, snapshot_active

from instr_synth import snap, two_hands

X = 315.0


class Sink:
    def __init__(self):
        self.audio = []
        self.views = []

    def a(self, ev):
        self.audio.append(ev)

    def v(self, view):
        self.views.append(view)

    def of(self, cls):
        return [e for e in self.audio if isinstance(e, cls)]


def make(layout="solo", clock=None):
    sink = Sink()
    kw = {"perf_clock": clock} if clock is not None else {}
    s = InstrumentSession(InstrumentEngine(InstrumentConfig(layout=layout)), sink.a, sink.v, **kw)
    return s, sink


INACTIVE = {
    "paused": dict(state=ControlState.PAUSED),
    "fault": dict(state=ControlState.FAULT),
    "mode_change": dict(mode=Mode.POINTER),
    "camera_error": dict(camera=CameraState.ERROR),
    "camera_off": dict(camera=CameraState.OFF),
    "menu_open": dict(menu=object()),
    "clap_pending": dict(clap_pending=True),
}


def test_snapshot_active_rule():
    assert snapshot_active(snap())
    for kw in INACTIVE.values():
        assert not snapshot_active(snap(**kw))
    assert not snapshot_active(None)


@pytest.mark.parametrize("kind", list(INACTIVE))
def test_alloff_exactly_once_per_inactive_transition_via_snapshot(kind):
    s, sink = make()
    s.on_snapshot(snap(t_ms=1.0))
    assert s.active and sink.audio == []
    s.on_snapshot(snap(t_ms=2.0, **INACTIVE[kind]))
    s.on_snapshot(snap(t_ms=3.0, **INACTIVE[kind]))
    s.on_frame(two_hands(40.0, (X, 200.0)), (), snap(t_ms=4.0, **INACTIVE[kind]))
    offs = sink.of(AllOff)
    assert len(offs) == 1 and offs[0].fade_ms == pytest.approx(20.0)
    assert not s.active
    # reactivate and leave again -> one more
    s.on_snapshot(snap(t_ms=5.0))
    s.on_snapshot(snap(t_ms=6.0, **INACTIVE[kind]))
    assert len(sink.of(AllOff)) == 2


@pytest.mark.parametrize("kind", list(INACTIVE))
def test_alloff_exactly_once_when_seen_first_in_on_frame(kind):
    s, sink = make()
    s.on_frame(two_hands(0.0, (X, 200.0)), (), snap(t_ms=1.0))
    s.on_frame(two_hands(33.0, (X, 210.0)), (), snap(t_ms=2.0, **INACTIVE[kind]))
    s.on_frame(two_hands(66.0, (X, 220.0)), (), snap(t_ms=3.0, **INACTIVE[kind]))
    s.on_snapshot(snap(t_ms=4.0, **INACTIVE[kind]))
    assert len(sink.of(AllOff)) == 1


def test_never_alloff_without_being_active_first():
    s, sink = make()
    s.on_snapshot(snap(state=ControlState.PAUSED, t_ms=1.0))
    s.on_frame(two_hands(0.0, (X, 200.0)), (), snap(state=ControlState.PAUSED, t_ms=2.0))
    assert sink.audio == []


def test_no_note_while_inactive_and_view_every_frame():
    s, sink = make()
    paused = dict(state=ControlState.PAUSED)
    for i, y in enumerate((200.0, 300.0, 200.0, 300.0)):
        s.on_frame(two_hands(33.0 * i, (X, y)), (), snap(t_ms=float(i), **paused))
    assert sink.of(NoteOn) == [] and sink.of(Bend) == []
    assert len(sink.views) == 4
    assert all(not v.playing and v.status == "Duraklatıldı" for v in sink.views)


def test_active_session_plays_and_counts_notes():
    s, sink = make()
    s.on_frame(two_hands(0.0, (X, 200.0)), (), snap(t_ms=1.0))
    s.on_frame(two_hands(33.0, (X, 300.0)), (), snap(t_ms=2.0))
    assert len(sink.of(NoteOn)) == 1
    st = s.stats()
    assert isinstance(st, SessionStats) and st.frames == 2 and st.notes == 1


def test_resume_does_not_produce_a_phantom_strike():
    s, sink = make()
    s.on_frame(two_hands(0.0, (X, 200.0)), (), snap(t_ms=1.0))
    s.on_snapshot(snap(state=ControlState.PAUSED, t_ms=2.0))
    s.on_frame(two_hands(33.0, (X, 300.0)), (), snap(state=ControlState.PAUSED, t_ms=3.0))
    s.on_snapshot(snap(t_ms=4.0))
    s.on_frame(two_hands(66.0, (X, 300.0)), (), snap(t_ms=5.0))
    assert sink.of(NoteOn) == []


def test_stale_frame_snapshot_cannot_reactivate():
    s, sink = make()
    s.on_frame(two_hands(0.0, (X, 200.0)), (), snap(t_ms=10.0))
    s.on_snapshot(snap(state=ControlState.PAUSED, t_ms=20.0))    # hotkey pause on another thread
    s.on_frame(two_hands(33.0, (X, 300.0)), (), snap(t_ms=15.0))  # snapshot taken before the pause
    assert sink.of(NoteOn) == [] and not s.active
    assert len(sink.of(AllOff)) == 1


class Boom(InstrumentEngine):
    def update(self, frame, active):   # pragma: no cover - must never be called
        raise AssertionError("engine used outside INSTRUMENT mode")


def test_no_work_when_mode_is_not_instrument():
    sink = Sink()
    calls = []
    s = InstrumentSession(Boom(), sink.a, sink.v, perf_clock=lambda: calls.append(1) or 0.0)
    for i in range(5):
        s.on_frame(two_hands(33.0 * i, (X, 200.0)), (), snap(mode=Mode.POINTER, t_ms=float(i)))
    assert sink.audio == [] and sink.views == [] and calls == []
    assert s.stats().frames == 0


def test_emit_view_exceptions_are_swallowed():
    def bad(_):
        raise RuntimeError("gui gone")
    audio = []
    s = InstrumentSession(InstrumentEngine(), audio.append, bad)
    s.on_frame(two_hands(0.0, (X, 200.0)), (), snap(t_ms=1.0))
    s.on_frame(two_hands(33.0, (X, 300.0)), (), snap(t_ms=2.0))
    assert len([e for e in audio if isinstance(e, NoteOn)]) == 1


def test_configure_and_stop_send_alloff():
    s, sink = make()
    s.on_frame(two_hands(0.0, (X, 200.0)), (), snap(t_ms=1.0))
    s.configure(InstrumentConfig(layout="chord"))
    assert len(sink.of(AllOff)) == 1
    s.on_frame(two_hands(33.0, (X, 100.0)), (), snap(t_ms=2.0))
    assert len(sink.views[-1].strings) == 4
    s.stop(99.0)
    offs = sink.of(AllOff)
    assert len(offs) == 2 and offs[-1].t_ms == 99.0 and not s.active


def test_stats_with_fake_clock():
    ticks = iter([0.0, 0.001, 0.010, 0.013, 0.020, 0.030])
    s, _ = make(clock=lambda: next(ticks))
    for i in range(3):
        s.on_frame(two_hands(33.0 * i, (X, 200.0)), (), snap(t_ms=float(i)))
    st = s.stats()
    assert st.frames == 3
    assert st.mean_ms == pytest.approx((1.0 + 3.0 + 10.0) / 3)
    assert st.max_ms == pytest.approx(10.0) and st.p95_ms == pytest.approx(10.0)


def test_threads_do_not_break_alloff_accounting():
    s, sink = make()
    stop = threading.Event()

    def toggler():
        t = 1000.0
        while not stop.is_set():
            s.on_snapshot(snap(t_ms=t))
            s.on_snapshot(snap(state=ControlState.PAUSED, t_ms=t + 0.5))
            t += 1.0

    th = threading.Thread(target=toggler)
    th.start()
    for i in range(200):
        s.on_frame(two_hands(33.0 * i, (X, 200.0 if i % 2 else 300.0)), (), snap(t_ms=float(i)))
    stop.set()
    th.join()
    # smoke: concurrent callers neither deadlock nor raise; the pause toggles produced AllOffs
    assert sink.of(AllOff)
    assert len(sink.of(AllOff)) <= len(sink.audio)


def _strum_frames(n=300):
    frames = []
    for i in range(n):
        t = i * 33.0
        y = 205.0 + 95.0 * math.sin(i * 0.9)          # sweeps across all 4 strings (160..250)
        frames.append(two_hands(t, (X, y)))
    return frames


def test_performance_chord_strumming_300_frames(capsys):
    s, sink = make(layout="chord", clock=time.perf_counter)
    frames = _strum_frames()
    sn = snap(t_ms=0.0)
    for ff in frames:
        s.on_frame(ff, (), sn)
    st = s.stats()
    with capsys.disabled():
        print(f"\n[instrument perf] frames={st.frames} mean={st.mean_ms:.4f} ms p95={st.p95_ms:.4f} ms "
              f"max={st.max_ms:.4f} ms notes={st.notes}")
    assert st.frames == 300
    assert st.notes > 100
    assert st.mean_ms < 2.0
