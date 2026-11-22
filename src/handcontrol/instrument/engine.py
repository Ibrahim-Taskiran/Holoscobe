"""Instrument engine: FrameFeatures -> (audio events, render view). Pure and deterministic.

All timing comes from FrameFeatures.capture_ms. Runs on the tracking thread; never touches audio or Qt.

Design constants (InstrumentConfig defaults, documented here):
- Solo pitch: string length 0.35..1.75 string-hand palm units maps linearly (in semitones) to
  E5 (76) .. E3 (52); longer string = lower pitch, clamped outside the range. Quantize hysteresis 0.3 st.
- Chord layout: 4 strings, 0.30 pu apart, offset away from the string-hand palm. Chord zone from the
  string-hand palm centre y over [0.15, 0.85] of the frame height, 4 zones, hysteresis 0.03.
- Strike: Schmitt band +-0.06 string-hand pu around each string, end margin 4 % of the string length,
  min speed 2.0 pick-hand pu/s (full velocity at 25 pu/s, curve floor + (1-floor) * x^0.6, floor 0.12),
  upstrokes x0.85, per-string cooldown 60 ms. Strum spacing inside one frame clamped to [5, 25] ms.
- Too close (no strike, strings dimmed): pick tip within 0.5 string-hand pu of the string-hand palm
  centre or within 0.15 pu of its thumb/index tip, or the two palm centres within 0.9 pu.
- Safety: no new notes and side state reset on a DEGRADED/UNKNOWN hand, invalid palm scale,
  identity_ambiguous, missing/duplicate roles, hand id change or a frame gap > 150 ms.
- Solo bend: One Euro smoothed continuous pitch minus its value at the strike, clamped +-2 st,
  sent when it changed by > 0.02 st, for 2.5 s after the strike (or until the next strike).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Optional

from handcontrol.contracts import FrameFeatures, HandFeatures, Handedness, Quality
from handcontrol.filters import OneEuroFilter
from handcontrol.instrument import music
from handcontrol.instrument.events import (
    CHORD_NAMES, DEFAULT_CHORDS, DEFAULT_FADE_MS, LAYOUTS, SCALE_NAMES, AllOff, Bend, HitView,
    InstrumentEvent, InstrumentView, NoteOn, StringView,
)
from handcontrol.instrument.geometry import Vec, dist, is_finite
from handcontrol.instrument.strings import CrossingDetector, Layout, Strike, StringLayout

THUMB_TIP = 4
INDEX_TIP = 8

STATUS_READY = "Hazır"
STATUS_PAUSED = "Duraklatıldı"
STATUS_NEED_STRING = "Tel elini gösterin"
STATUS_NEED_PICK = "Çalan eli gösterin"
STATUS_TOO_CLOSE = "Eller çok yakın"
STATUS_UNCERTAIN = "Takip belirsiz"


@dataclass(frozen=True)
class InstrumentConfig:
    layout: str = "solo"                    # "solo" | "chord"
    scale: str = "e_minor_pentatonic"       # one of events.SCALE_NAMES
    quantize: bool = True
    chords: tuple[str, str, str, str] = DEFAULT_CHORDS   # each one of events.CHORD_NAMES
    dominant: Handedness = Handedness.RIGHT  # pick hand
    # --- tuning ---
    low_midi: float = 52.0                  # E3, longest string
    high_midi: float = 76.0                 # E5, shortest string
    min_length_pu: float = 0.35
    max_length_pu: float = 1.75
    quantize_hysteresis: float = 0.3        # semitones past the midpoint between degrees
    chord_spacing_pu: float = 0.30
    zone_top: float = 0.15
    zone_bottom: float = 0.85
    zone_hysteresis: float = 0.03
    band_pu: float = 0.06                   # half width of the Schmitt band, string-hand pu
    end_margin: float = 0.04                # fraction of the string length ignored at each end
    min_string_pu: float = 0.08             # shorter main string: no geometry
    min_speed_pu_s: float = 2.0
    full_speed_pu_s: float = 25.0
    velocity_floor: float = 0.12
    velocity_gamma: float = 0.6
    upstroke_gain: float = 0.85
    cooldown_ms: float = 60.0
    strum_min_ms: float = 5.0
    strum_max_ms: float = 25.0
    max_gap_ms: float = 150.0
    too_close_palm_pu: float = 0.5
    too_close_tip_pu: float = 0.15
    too_close_hands_pu: float = 0.9
    sustain_ms: float = 2500.0
    bend_limit: float = 2.0
    bend_epsilon: float = 0.02
    bend_min_cutoff: float = 4.0            # Hz: tremor (8-12 Hz) is damped, not removed -> vibrato
    bend_beta: float = 0.05
    amp_tau_ms: float = 600.0


def normalize_config(cfg: InstrumentConfig) -> InstrumentConfig:
    """Replace unknown names with defaults (settings can be hand-edited)."""
    layout = cfg.layout if cfg.layout in LAYOUTS else "solo"
    scale = cfg.scale if cfg.scale in SCALE_NAMES else "e_minor_pentatonic"
    chords = tuple(cfg.chords) if len(tuple(cfg.chords)) == 4 else DEFAULT_CHORDS
    chords = tuple(c if c in CHORD_NAMES else DEFAULT_CHORDS[i] for i, c in enumerate(chords))
    dominant = cfg.dominant if cfg.dominant in (Handedness.LEFT, Handedness.RIGHT) else Handedness.RIGHT
    if (layout, scale, chords, dominant) == (cfg.layout, cfg.scale, tuple(cfg.chords), cfg.dominant):
        return cfg
    return replace(cfg, layout=layout, scale=scale, chords=chords, dominant=dominant)  # type: ignore[arg-type]


@dataclass
class _Voice:
    note_id: int
    base: float          # smoothed continuous pitch at the strike
    t_ms: float
    last_sent: float = 0.0


@dataclass
class _Prev:
    t_ms: float
    tip: Vec
    lines: dict[int, tuple[Vec, Vec]] = field(default_factory=dict)


def _px(hand: HandFeatures, i: int, w: int, h: int) -> Optional[Vec]:
    if len(hand.landmarks) <= i:
        return None
    lm = hand.landmarks[i]
    p = (lm.x * w, lm.y * h)
    return p if is_finite(p) else None


def _scale_ok(hand: HandFeatures) -> bool:
    s = hand.palm_scale_px
    return isinstance(s, (int, float)) and math.isfinite(s) and s > 0.0


class InstrumentEngine:
    def __init__(self, config: InstrumentConfig = InstrumentConfig()) -> None:
        self._next_id = 1
        self.configure(config)

    @property
    def config(self) -> InstrumentConfig:
        return self._cfg

    def configure(self, config: InstrumentConfig) -> None:
        self._cfg = normalize_config(config)
        count = 4 if self._cfg.layout == "chord" else 1
        self._detectors = [CrossingDetector(k) for k in range(count)]
        self._pitches = music.scale_pitches(self._cfg.scale, self._cfg.low_midi, self._cfg.high_midi)
        self._voicings = tuple(music.chord_voicing(c) for c in self._cfg.chords)
        self._filter = OneEuroFilter(self._cfg.bend_min_cutoff, self._cfg.bend_beta, 1.0,
                                     self._cfg.max_gap_ms)
        self.reset()

    def reset(self) -> None:
        self._layout = StringLayout()
        for d in self._detectors:
            d.reset()
        self._filter.reset()
        self._prev: Optional[_Prev] = None
        self._ids: Optional[tuple[int, int]] = None
        self._last_t: Optional[float] = None
        self._qpitch: Optional[float] = None
        self._zone: Optional[int] = None
        self._voice: Optional[_Voice] = None
        self._amps: dict[int, tuple[float, float]] = {}
        self._note_name = ""
        self._note_bend = 0.0

    def all_off(self, t_ms: float, fade_ms: float = DEFAULT_FADE_MS) -> AllOff:
        self.reset()
        return AllOff(fade_ms=fade_ms, t_ms=t_ms)

    # ------------------------------------------------------------------ main step

    def update(self, frame: FrameFeatures, active: bool) -> tuple[list[InstrumentEvent], InstrumentView]:
        cfg = self._cfg
        t = frame.capture_ms
        w, h = frame.width, frame.height
        events: list[InstrumentEvent] = []
        hits: list[HitView] = []

        pick_label = cfg.dominant
        string_label = Handedness.LEFT if pick_label is Handedness.RIGHT else Handedness.RIGHT
        s_cands = [x for x in frame.hands if x.handedness is string_label]
        p_cands = [x for x in frame.hands if x.handedness is pick_label]
        s_hand = s_cands[0] if len(s_cands) == 1 else None
        p_hand = p_cands[0] if len(p_cands) == 1 else None
        roles_ok = s_hand is not None and p_hand is not None

        # --- geometry of the string hand (also shown when not playable)
        thumb = index = palm = None
        s_scale = 0.0
        if s_hand is not None and _scale_ok(s_hand):
            thumb, index = _px(s_hand, THUMB_TIP, w, h), _px(s_hand, INDEX_TIP, w, h)
            palm = s_hand.palm_center_px if is_finite(s_hand.palm_center_px) else None
            s_scale = float(s_hand.palm_scale_px)
            if thumb is None or index is None or palm is None or dist(thumb, index) < cfg.min_string_pu * s_scale:
                thumb = index = palm = None
        geometry = thumb is not None
        tip = _px(p_hand, INDEX_TIP, w, h) if p_hand is not None else None

        # --- safety
        ids = (s_hand.hand_id, p_hand.hand_id) if roles_ok else None   # type: ignore[union-attr]
        swapped = ids is not None and self._ids is not None and ids != self._ids
        self._ids = ids
        gap = self._last_t is not None and t - self._last_t > cfg.max_gap_ms
        duplicate = self._last_t is not None and t <= self._last_t
        if not duplicate:
            self._last_t = t
        safe = (roles_ok and geometry and tip is not None and not frame.identity_ambiguous and not swapped
                and not gap and s_hand.quality is Quality.USABLE and p_hand.quality is Quality.USABLE  # type: ignore[union-attr]
                and _scale_ok(p_hand))  # type: ignore[arg-type]

        too_close = False
        if safe:
            p_scale = float(p_hand.palm_scale_px)  # type: ignore[union-attr]
            too_close = (dist(tip, palm) < cfg.too_close_palm_pu * s_scale                     # type: ignore[arg-type]
                         or dist(tip, thumb) < cfg.too_close_tip_pu * s_scale                  # type: ignore[arg-type]
                         or dist(tip, index) < cfg.too_close_tip_pu * s_scale                  # type: ignore[arg-type]
                         or (is_finite(p_hand.palm_center_px)                                  # type: ignore[union-attr]
                             and dist(p_hand.palm_center_px, palm) < cfg.too_close_hands_pu * s_scale))  # type: ignore[union-attr,arg-type]

        # --- layout and per-string pitch
        layout: Optional[Layout] = None
        string_pitch: dict[int, float] = {}
        chord_label = ""
        smooth = None
        if geometry:
            count = len(self._detectors)
            layout = self._layout.build(thumb, index, palm, s_scale, count, cfg.chord_spacing_pu)  # type: ignore[arg-type]
            if cfg.layout == "solo":
                length_pu = dist(thumb, index) / s_scale  # type: ignore[arg-type]
                cont = music.continuous_pitch(length_pu, low=cfg.low_midi, high=cfg.high_midi,
                                              min_len=cfg.min_length_pu, max_len=cfg.max_length_pu)
                smooth = self._filter.filter(cont, t)
                if cfg.quantize:
                    self._qpitch = music.quantize_pitch(smooth, self._pitches, self._qpitch,
                                                        cfg.quantize_hysteresis)
                    string_pitch[0] = self._qpitch
                else:
                    string_pitch[0] = smooth
            else:
                y_norm = palm[1] / h if h > 0 else 0.5  # type: ignore[index]
                self._zone = music.chord_zone(y_norm, self._zone, zones=4, top=cfg.zone_top,
                                              bottom=cfg.zone_bottom, hysteresis=cfg.zone_hysteresis)
                voicing = self._voicings[self._zone]
                for i in range(4):
                    string_pitch[i] = voicing[i]
                chord_label = cfg.chords[self._zone]
        else:
            self._filter.reset()
            if s_hand is None:
                self._layout.reset()

        playing = bool(active and safe and not too_close)

        # --- strikes
        if active and safe and layout is not None and not duplicate:
            lines_now = {ln.slot: (ln.p0, ln.p1) for ln in layout.lines}
            prev = self._prev
            strikes: list[Strike] = []
            p_scale = float(p_hand.palm_scale_px)  # type: ignore[union-attr]
            for det in self._detectors:
                line = lines_now[det.slot]
                if prev is None or det.slot not in prev.lines:
                    pl, tip0, t0 = line, tip, t
                else:
                    pl, tip0, t0 = prev.lines[det.slot], prev.tip, prev.t_ms
                st = det.update(pl, line, tip0, tip, t0, t, band_px=cfg.band_pu * s_scale,  # type: ignore[arg-type]
                                end_margin=cfg.end_margin, pick_scale_px=p_scale,
                                min_speed_pu_s=cfg.min_speed_pu_s, cooldown_ms=cfg.cooldown_ms,
                                allow=not too_close)
                if st is not None:
                    strikes.append(st)
            self._prev = _Prev(t, tip, lines_now)  # type: ignore[arg-type]
            if strikes:
                self._emit_strikes(strikes, layout, string_pitch, smooth, t, events, hits)
        elif not duplicate:
            # unsafe or inactive: forget sides, require a fresh observation; sounding notes decay on
            for det in self._detectors:
                det.reset_side()
            self._prev = None
            self._voice = None

        # --- solo bend of the sounding voice
        if active and safe and cfg.layout == "solo" and self._voice is not None and smooth is not None:
            v = self._voice
            if t - v.t_ms > cfg.sustain_ms:
                self._voice = None
            elif v.t_ms < t:
                bend = max(-cfg.bend_limit, min(cfg.bend_limit, smooth - v.base))
                if abs(bend - v.last_sent) > cfg.bend_epsilon:
                    events.append(Bend(voice=v.note_id, semitones=bend, t_ms=t))
                    v.last_sent = bend
                self._note_bend = bend
        elif not (active and safe):
            self._voice = None

        # --- view
        status = self._status(active, frame, s_cands, p_cands, roles_ok, safe, too_close, swapped, gap)
        strings: list[StringView] = []
        if layout is not None:
            for ln in sorted(layout.lines, key=lambda x: x.index):
                pitch = string_pitch.get(0 if cfg.layout == "solo" else ln.index)
                strings.append(StringView(ln.index, ln.p0, ln.p1, self._amplitude(ln.index, t),
                                          music.midi_to_name(pitch) if pitch is not None else "", playing))
        label = self._note_name
        if label and cfg.layout == "solo" and abs(self._note_bend) >= 0.05:
            label = f"{label} {self._note_bend:+.1f}"
        view = InstrumentView(
            t_ms=t, width=w, height=h, layout=cfg.layout, strings=tuple(strings), hits=tuple(hits),
            note_label=label, chord_label=chord_label, playing=playing, status=status,
            pick_tip=tip, string_hand_id=s_hand.hand_id if s_hand is not None else None,
            pick_hand_id=p_hand.hand_id if p_hand is not None else None,
        )
        return events, view

    # ------------------------------------------------------------------ helpers

    def _velocity(self, speed: float, direction: int) -> float:
        cfg = self._cfg
        span = max(1e-6, cfg.full_speed_pu_s - cfg.min_speed_pu_s)
        x = min(1.0, max(0.0, (speed - cfg.min_speed_pu_s) / span))
        v = cfg.velocity_floor + (1.0 - cfg.velocity_floor) * x ** cfg.velocity_gamma
        if direction < 0:
            v *= cfg.upstroke_gain
        return min(1.0, max(0.0, v))

    def _emit_strikes(self, strikes: list[Strike], layout: Layout, string_pitch: dict[int, float],
                      smooth: Optional[float], t: float, events: list[InstrumentEvent],
                      hits: list[HitView]) -> None:
        cfg = self._cfg
        strikes.sort(key=lambda s: (s.t_ms, s.slot))
        delay = 0.0
        prev_t: Optional[float] = None
        for st in strikes:
            if prev_t is not None:
                delay += min(cfg.strum_max_ms, max(cfg.strum_min_ms, st.t_ms - prev_t))
            prev_t = st.t_ms
            idx = layout.lines[st.slot].index
            direction = st.direction * layout.down_sign
            vel = self._velocity(st.speed_pu_s, direction)
            midi = string_pitch[0] if cfg.layout == "solo" else string_pitch[idx]
            nid = self._next_id
            self._next_id += 1
            events.append(NoteOn(string=idx, midi=midi, velocity=vel, note_id=nid, t_ms=t, delay_ms=delay))
            hits.append(HitView(idx, st.point[0], st.point[1], vel, direction, t))
            self._amps[idx] = (vel, t + delay)
            self._note_name = music.midi_to_name(midi)
            self._note_bend = 0.0
            if cfg.layout == "solo":
                self._voice = _Voice(nid, smooth if smooth is not None else midi, t)

    def _amplitude(self, idx: int, t: float) -> float:
        a = self._amps.get(idx)
        if a is None:
            return 0.0
        vel, t0 = a
        if t <= t0:
            return vel
        amp = vel * math.exp(-(t - t0) / self._cfg.amp_tau_ms)
        if amp < 1e-3:
            del self._amps[idx]
            return 0.0
        return amp

    @staticmethod
    def _status(active: bool, frame: FrameFeatures, s_cands: list, p_cands: list, roles_ok: bool,
                safe: bool, too_close: bool, swapped: bool, gap: bool) -> str:
        if not active:
            return STATUS_PAUSED
        if len(s_cands) > 1 or len(p_cands) > 1 or (not roles_ok and len(frame.hands) >= 2):
            return STATUS_UNCERTAIN
        if not s_cands:
            return STATUS_NEED_STRING
        if not p_cands:
            return STATUS_NEED_PICK
        if not safe:
            return STATUS_UNCERTAIN
        if too_close:
            return STATUS_TOO_CLOSE
        return STATUS_READY


__all__ = [
    "InstrumentConfig", "InstrumentEngine", "STATUS_NEED_PICK", "STATUS_NEED_STRING", "STATUS_PAUSED",
    "STATUS_READY", "STATUS_TOO_CLOSE", "STATUS_UNCERTAIN", "normalize_config",
]
