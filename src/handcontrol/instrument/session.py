"""Glue between the pipeline/controller and the instrument engine. Qt-free.

on_frame runs on the tracking thread (Pipeline.add_frame_observer), on_snapshot on any thread
(Controller.add_listener). One lock guards the engine and the active flag. Audio events are emitted
while holding the lock: emit_audio is a non-blocking deque append, and emitting under the lock keeps
the order strict (no NoteOn can ever slip in after the AllOff of a pause seen on another thread).
The view is emitted after the lock is released; its exceptions are swallowed.

Stale snapshots: a snapshot older (t_ms) than the newest one seen does not change the active flag,
so a frame observer holding a snapshot taken just before a hotkey pause cannot re-activate the engine.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Optional

from handcontrol.contracts import CameraState, ControlState, FrameFeatures, Mode
from handcontrol.instrument.engine import InstrumentConfig, InstrumentEngine
from handcontrol.instrument.events import DEFAULT_FADE_MS, InstrumentEvent, InstrumentView, NoteOn

log = logging.getLogger(__name__)

STATS_WINDOW = 1000   # frame durations kept for mean/p95/max


@dataclass(frozen=True)
class SessionStats:
    frames: int          # frames processed in INSTRUMENT mode
    mean_ms: float       # over the last STATS_WINDOW frames
    p95_ms: float
    max_ms: float
    notes: int           # NoteOns emitted


def snapshot_active(snap: Any) -> bool:
    if snap is None:
        return False
    return (snap.mode is Mode.INSTRUMENT and snap.state is ControlState.ACTIVE
            and snap.camera_state is CameraState.RUNNING and snap.menu is None and not snap.clap_pending)


class InstrumentSession:
    def __init__(self, engine: InstrumentEngine, emit_audio: Callable[[InstrumentEvent], None],
                 emit_view: Callable[[InstrumentView], None], *, perf_clock: Callable[[], float] = time.perf_counter,
                 fade_ms: float = DEFAULT_FADE_MS) -> None:
        self._engine = engine
        self._emit_audio = emit_audio
        self._emit_view = emit_view
        self._clock = perf_clock
        self._fade_ms = fade_ms
        self._lock = threading.Lock()
        self._active = False
        self._snap_t = -math.inf
        self._last_frame_t = 0.0
        self._frames = 0
        self._notes = 0
        self._durations: deque[float] = deque(maxlen=STATS_WINDOW)

    @property
    def active(self) -> bool:
        return self._active

    # ------------------------------------------------------------------ callbacks

    def on_frame(self, ff: FrameFeatures, events: tuple, snap: Any) -> None:
        if snap is None or (snap.mode is not Mode.INSTRUMENT and not self._active):
            return
        start = self._clock()
        view: Optional[InstrumentView] = None
        with self._lock:
            active = self._observe(snap)
            if snap.mode is not Mode.INSTRUMENT:
                # left the mode: _observe already sent the AllOff; no view, no work
                return
            try:
                out, view = self._engine.update(ff, active)
            except Exception:
                log.exception("instrument engine update failed")
                out, view = [], None
                self._engine.reset()
            self._last_frame_t = ff.capture_ms
            for ev in out:
                if isinstance(ev, NoteOn):
                    if not active:
                        continue
                    self._notes += 1
                self._send(ev)
            self._frames += 1
            self._durations.append((self._clock() - start) * 1000.0)
        if view is not None:
            try:
                self._emit_view(view)
            except Exception:
                log.debug("instrument view emit failed", exc_info=True)

    def on_snapshot(self, snap: Any) -> None:
        if snap is None:
            return
        with self._lock:
            self._observe(snap)

    def configure(self, config: InstrumentConfig) -> None:
        with self._lock:
            if self._active:
                self._send(self._engine.all_off(self._last_frame_t, self._fade_ms))
            self._engine.configure(config)

    def stop(self, t_ms: float = 0.0) -> None:
        with self._lock:
            self._active = False
            self._send(self._engine.all_off(t_ms, self._fade_ms))

    def stats(self) -> SessionStats:
        with self._lock:
            d = sorted(self._durations)
            frames, notes = self._frames, self._notes
        if not d:
            return SessionStats(frames, 0.0, 0.0, 0.0, notes)
        p95 = d[min(len(d) - 1, int(math.ceil(0.95 * len(d))) - 1)]
        return SessionStats(frames, sum(d) / len(d), p95, d[-1], notes)

    # ------------------------------------------------------------------ internals (lock held)

    def _observe(self, snap: Any) -> bool:
        """Update the active flag from a snapshot (ignored when older than the newest seen).
        On an active -> inactive transition send exactly one AllOff and reset the engine."""
        t = getattr(snap, "t_ms", None)
        t = float(t) if isinstance(t, (int, float)) and math.isfinite(t) else self._snap_t
        if t < self._snap_t:
            return self._active
        self._snap_t = t
        now = snapshot_active(snap)
        if self._active and not now:
            self._send(self._engine.all_off(t if math.isfinite(t) else 0.0, self._fade_ms))
        self._active = now
        return now

    def _send(self, ev: InstrumentEvent) -> None:
        try:
            self._emit_audio(ev)
        except Exception:
            log.debug("instrument audio emit failed", exc_info=True)


__all__ = ["InstrumentSession", "STATS_WINDOW", "SessionStats", "snapshot_active"]
