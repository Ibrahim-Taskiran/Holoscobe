"""Pure music helpers: note names, scales, string length -> pitch, chord voicings, chord zones.

MIDI numbers are floats (69.0 = A4 = 440 Hz). Stdlib only.
"""
from __future__ import annotations

import math
from typing import Optional, Sequence

from handcontrol.instrument.events import CHORD_NAMES, SCALE_NAMES

NOTE_NAMES: tuple[str, ...] = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}

# scale name -> (root pitch class, intervals from the root)
_MINOR_PENT = (0, 3, 5, 7, 10)
_NATURAL_MINOR = (0, 2, 3, 5, 7, 8, 10)
_MAJOR = (0, 2, 4, 5, 7, 9, 11)
SCALES: dict[str, tuple[int, tuple[int, ...]]] = {
    "e_minor_pentatonic": (4, _MINOR_PENT),
    "a_minor_pentatonic": (9, _MINOR_PENT),
    "e_blues": (4, (0, 3, 5, 6, 7, 10)),
    "e_minor": (4, _NATURAL_MINOR),
    "a_minor": (9, _NATURAL_MINOR),
    "c_major": (0, _MAJOR),
    "g_major": (7, _MAJOR),
    "d_dorian": (2, (0, 2, 3, 5, 7, 9, 10)),
    "chromatic": (0, tuple(range(12))),
}

# chord quality suffix -> 4-note guitar-like voicing (root, fifth, octave/7th, third above), low to high
_VOICINGS: dict[str, tuple[int, int, int, int]] = {
    "": (0, 7, 12, 16),
    "m": (0, 7, 12, 15),
    "7": (0, 7, 10, 16),
    "maj7": (0, 7, 11, 16),
    "m7": (0, 7, 10, 15),
}
CHORD_ROOT_LOW = 40   # E2: chord roots fall in E2..D#3 (the low guitar register)


def midi_to_hz(midi: float) -> float:
    return 440.0 * 2.0 ** ((midi - 69.0) / 12.0)


def midi_to_name(midi: float) -> str:
    """Nearest note name with octave, e.g. 52 -> "E3", 61.4 -> "C#4". "" if not finite."""
    if not math.isfinite(midi):
        return ""
    n = int(round(midi))
    return f"{NOTE_NAMES[n % 12]}{n // 12 - 1}"


def scale_pitches(scale: str, low: float, high: float) -> tuple[int, ...]:
    """Every MIDI note of `scale` within [low, high], ascending. Unknown scale -> ValueError."""
    if scale not in SCALES:
        raise ValueError(f"unknown scale {scale!r}")
    root, steps = SCALES[scale]
    pcs = {(root + s) % 12 for s in steps}
    return tuple(n for n in range(int(math.ceil(low)), int(math.floor(high)) + 1) if n % 12 in pcs)


def continuous_pitch(length_pu: float, *, low: float, high: float, min_len: float, max_len: float) -> float:
    """String length (palm units) -> continuous MIDI pitch; longer string = lower pitch.
    Linear in semitones over [min_len, max_len] -> [high, low], clamped at both ends."""
    if not math.isfinite(length_pu) or max_len <= min_len:
        return float(low)
    t = (length_pu - min_len) / (max_len - min_len)
    t = min(1.0, max(0.0, t))
    return high - t * (high - low)


def quantize_pitch(pitch: float, pitches: Sequence[float], current: Optional[float] = None,
                   hysteresis: float = 0.3) -> float:
    """Snap to the nearest of `pitches`. With `current` given (and in `pitches`), stay on it until the
    pitch is closer to another degree by more than 2*hysteresis semitones, i.e. it passed the midpoint
    between the degrees by more than `hysteresis`. Empty `pitches` -> pitch unchanged."""
    if not pitches:
        return pitch
    best = min(pitches, key=lambda p: abs(pitch - p))
    if current is None or current == best or current not in pitches:
        return float(best)
    if abs(pitch - current) - abs(pitch - best) > 2.0 * hysteresis:
        return float(best)
    return float(current)


def parse_chord(name: str) -> tuple[int, str]:
    """"F#m7" -> (6, "m7"). ValueError for an unknown root or quality."""
    if not name or name[0] not in _PC:
        raise ValueError(f"unknown chord {name!r}")
    pc = _PC[name[0]]
    rest = name[1:]
    if rest[:1] == "#":
        pc, rest = pc + 1, rest[1:]
    elif rest[:1] == "b":
        pc, rest = pc - 1, rest[1:]
    if rest not in _VOICINGS:
        raise ValueError(f"unknown chord quality {name!r}")
    return pc % 12, rest


def chord_voicing(name: str) -> tuple[float, float, float, float]:
    """4-note voicing, lowest first (string 0 = lowest = the string a downstroke hits first).
    Root in E2..D#3, then fifth, octave (or 7th), third above. E.g. Em -> E2 B2 E3 G3."""
    pc, quality = parse_chord(name)
    root = CHORD_ROOT_LOW + (pc - 4) % 12
    a, b, c, d = _VOICINGS[quality]
    return (float(root + a), float(root + b), float(root + c), float(root + d))


def chord_zone(y_norm: float, current: Optional[int] = None, *, zones: int = 4, top: float = 0.15,
               bottom: float = 0.85, hysteresis: float = 0.03) -> int:
    """Vertical position (0 = top of the frame, 1 = bottom) -> zone 0..zones-1 (top to bottom).
    [top, bottom] is split evenly; outside it the edge zones hold. With `current`, a neighbour zone is
    entered only after passing the boundary by `hysteresis`."""
    if not math.isfinite(y_norm):
        return current if current is not None else 0
    w = (bottom - top) / zones
    raw = int(math.floor((y_norm - top) / w)) if w > 0 else 0
    raw = min(zones - 1, max(0, raw))
    if current is None or raw == current or not 0 <= current < zones:
        return raw
    if raw > current:
        boundary = top + (current + 1) * w
        return raw if y_norm > boundary + hysteresis else current
    boundary = top + current * w
    return raw if y_norm < boundary - hysteresis else current


def _self_check() -> None:   # pragma: no cover - import-time sanity, cheap
    for s in SCALE_NAMES:
        assert s in SCALES, s
    for c in CHORD_NAMES:
        parse_chord(c)


_self_check()

__all__ = [
    "CHORD_ROOT_LOW", "NOTE_NAMES", "SCALES", "chord_voicing", "chord_zone", "continuous_pitch",
    "midi_to_hz", "midi_to_name", "parse_chord", "quantize_pitch", "scale_pitches",
]
