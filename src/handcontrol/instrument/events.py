"""Shared types of the instrument package (round 7). FROZEN for the round: only the manager edits.

Stdlib only. The engine (tracking thread) produces these, the synth/audio side (audio thread) and the
instrument window (GUI thread) consume them. All values are immutable, so they cross threads safely.

Units:
- time: monotonic milliseconds (float), the capture_ms of the frame that produced the value.
- positions: camera pixels on the UNMIRRORED frame (same as HandFeatures.*_px). The UI mirrors.
- midi: MIDI note number as float (69.0 = A4 = 440 Hz); fractional values are allowed (free pitch).
- velocity: 0..1 (strike strength after the speed curve).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Union

# Names the settings may store. music.py must support every one of them.
SCALE_NAMES: tuple[str, ...] = (
    "e_minor_pentatonic",   # default
    "a_minor_pentatonic",
    "e_blues",
    "e_minor",
    "a_minor",
    "c_major",
    "g_major",
    "d_dorian",
    "chromatic",
)
CHORD_NAMES: tuple[str, ...] = (
    "Em", "Am", "Dm", "Bm",
    "E", "A", "D", "G", "C", "F", "B",
    "E7", "A7", "D7", "G7", "C7", "B7",
    "Cmaj7", "Fmaj7", "Am7", "Em7", "Dm7",
)
DEFAULT_CHORDS: tuple[str, str, str, str] = ("Em", "C", "G", "D")
LAYOUTS: tuple[str, ...] = ("solo", "chord")
TONES: tuple[str, ...] = ("clean", "electric")
LATENCIES: tuple[str, ...] = ("low", "normal")
DEFAULT_FADE_MS = 20.0


# ---------- audio events (engine -> audio queue -> synth) ----------

@dataclass(frozen=True)
class NoteOn:
    string: int          # 0-based string index (solo: always 0)
    midi: float          # pitch at the moment of the strike
    velocity: float      # 0..1
    note_id: int         # unique, increasing per engine; Bend.voice refers to it
    t_ms: float          # capture_ms of the frame with the strike (latency measurement)


@dataclass(frozen=True)
class Bend:
    voice: int           # NoteOn.note_id of the sounding note
    semitones: float     # absolute offset from the NoteOn pitch, clamped by the engine to +-2
    t_ms: float


@dataclass(frozen=True)
class AllOff:
    fade_ms: float = DEFAULT_FADE_MS   # every voice fades out over this time, then is silent
    t_ms: float = 0.0


InstrumentEvent = Union[NoteOn, Bend, AllOff]


# ---------- render state (engine -> GUI) ----------

@dataclass(frozen=True)
class StringView:
    index: int
    p0: tuple[float, float]       # string end at the thumb side (camera px, unmirrored)
    p1: tuple[float, float]       # string end at the index side
    amplitude: float              # 0..1 vibration envelope (decays after a strike)
    label: str                    # note name the string plays now, e.g. "E3"
    enabled: bool                 # False: shown dimmed, strikes do not count (quality/identity/too close)


@dataclass(frozen=True)
class HitView:
    string: int
    x: float                      # strike point on the string (camera px, unmirrored)
    y: float
    velocity: float               # 0..1, drives spark count and brightness
    direction: int                # +1 down / -1 up (image y grows downward)
    t_ms: float


@dataclass(frozen=True)
class InstrumentView:
    t_ms: float
    width: int                    # camera frame size the positions refer to
    height: int
    layout: str                   # "solo" | "chord"
    strings: tuple[StringView, ...]
    hits: tuple[HitView, ...]     # new strikes in this frame only
    note_label: str               # last played note ("A3", "A3 +0.7"), "" if none
    chord_label: str              # chord layout: current chord ("Em"), "" in solo
    playing: bool                 # True when new notes may be produced now
    status: str                   # short Turkish status, e.g. "Tel elini gösterin"
    pick_tip: Optional[tuple[float, float]] = None   # playing index fingertip (camera px)
    string_hand_id: Optional[int] = None
    pick_hand_id: Optional[int] = None


__all__ = [
    "AllOff", "Bend", "CHORD_NAMES", "DEFAULT_CHORDS", "DEFAULT_FADE_MS", "HitView", "InstrumentEvent",
    "InstrumentView", "LATENCIES", "LAYOUTS", "NoteOn", "SCALE_NAMES", "StringView", "TONES",
]
