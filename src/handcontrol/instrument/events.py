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
LAYOUTS: tuple[str, ...] = ("solo", "chord", "fixed", "free")
TONES: tuple[str, ...] = ("clean", "electric")
LATENCIES: tuple[str, ...] = ("low", "normal")
DEFAULT_FADE_MS = 20.0
# "fixed" layout: strings fixed on the screen; normalized (x0, y0, x1, y1) on the UNMIRRORED frame.
DEFAULT_FIXED_RECT: tuple[float, float, float, float] = (0.25, 0.35, 0.75, 0.65)
DEFAULT_FIXED_STRINGS = 6
FIXED_STRINGS_RANGE: tuple[int, int] = (3, 8)


# ---------- audio events (engine -> audio queue -> synth) ----------

@dataclass(frozen=True)
class NoteOn:
    string: int          # 0-based string index (solo: always 0)
    midi: float          # pitch at the moment of the strike
    velocity: float      # 0..1
    note_id: int         # unique, increasing per engine; Bend.voice refers to it
    t_ms: float          # capture_ms of the frame with the strike (latency measurement)
    delay_ms: float = 0.0   # start this long after the event is consumed (strum spacing inside one frame)


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
    layout: str                   # "solo" | "chord" | "fixed" | "free"
    strings: tuple[StringView, ...]
    hits: tuple[HitView, ...]     # new strikes in this frame only
    note_label: str               # last played note ("A3", "A3 +0.7"), "" if none
    chord_label: str              # chord layout: current chord ("Em"), "" in solo
    playing: bool                 # True when new notes may be produced now
    status: str                   # short Turkish status, e.g. "Tel elini gösterin"
    pick_tip: Optional[tuple[float, float]] = None   # playing index fingertip (camera px)
    string_hand_id: Optional[int] = None
    pick_hand_id: Optional[int] = None
    fixed_rect: Optional[tuple[float, float, float, float]] = None   # "fixed": current string area
    adjusting: bool = False       # "fixed"/"free": a pinch gesture is moving strings (no strikes)
    # "free" layout: the user's own strings, normalized (x0, y0, x1, y1) on the unmirrored frame
    free_strings: Optional[tuple[tuple[float, float, float, float], ...]] = None
    free_active: Optional[int] = None     # index in free_strings of the string being edited
    free_snapped: bool = False            # the edited string is snapped (straightened / stacked)
    free_pending: tuple[tuple[tuple[float, float], float], ...] = ()   # pinches waiting: (normalized point, 0..1)
    free_full: bool = False               # a new string was refused (limit reached)


__all__ = [
    "AllOff", "Bend", "CHORD_NAMES", "DEFAULT_CHORDS", "DEFAULT_FADE_MS", "DEFAULT_FIXED_RECT",
    "DEFAULT_FIXED_STRINGS", "FIXED_STRINGS_RANGE", "HitView", "InstrumentEvent",
    "InstrumentView", "LATENCIES", "LAYOUTS", "NoteOn", "SCALE_NAMES", "StringView", "TONES",
]
