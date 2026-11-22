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
- Fixed layout: 3..8 horizontal strings fixed on the screen inside a normalized rectangle (top string =
  lowest note, then consecutive scale degrees upward from E3). The index fingertip of EVERY usable hand
  plays (per-hand detectors, band/speed in that hand's palm units). Moving/resizing: pinch with both
  hands (pinch < 0.35 pu, released above 0.55 pu) and hold 400 ms; the area then follows the two pinch
  points as opposite corners until a pinch is released. No strikes while adjusting.
- Free layout ("Serbest teller"): up to 10 strings the user draws, moves and resizes with pinch gestures
  (see instrument/freeform.py); playing works like the fixed layout, top string = lowest note. A pinching
  hand never strikes; nothing strikes while a string is being edited.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Optional

from handcontrol.contracts import FrameFeatures, HandFeatures, Handedness, Quality
from handcontrol.filters import OneEuroFilter
from handcontrol.instrument import music
from handcontrol.instrument.events import (
    CHORD_NAMES, DEFAULT_CHORDS, DEFAULT_FADE_MS, DEFAULT_FIXED_RECT, DEFAULT_FIXED_STRINGS, FIXED_STRINGS_RANGE,
    LAYOUTS, SCALE_NAMES, AllOff, Bend, HitView, InstrumentEvent, InstrumentView, NoteOn, StringView,
)
from handcontrol.instrument.geometry import Rect, Vec, dist, is_finite, lerp, normalize_fixed_rect
from handcontrol.instrument.freeform import FreeEditor, HandPinch, Seg, normalize_free_strings, pitch_order
from handcontrol.instrument.strings import CrossingDetector, Layout, Strike, StringLayout

THUMB_TIP = 4
INDEX_TIP = 8

STATUS_READY = "Hazır"
STATUS_PAUSED = "Duraklatıldı"
STATUS_NEED_STRING = "Tel elini gösterin"
STATUS_NEED_PICK = "Çalan eli gösterin"
STATUS_TOO_CLOSE = "Eller çok yakın"
STATUS_UNCERTAIN = "Takip belirsiz"
STATUS_NEED_HAND = "Elinizi gösterin"
STATUS_ADJUSTING = "Teller taşınıyor"
STATUS_EDITING = "Tel düzenleniyor"
STATUS_NO_STRINGS = "Tel çizmek için çimdikle, tut ve çek"
STATUS_FULL = "En fazla 10 tel"


@dataclass(frozen=True)
class InstrumentConfig:
    layout: str = "solo"                    # "solo" | "chord" | "fixed" | "free"
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
    # --- fixed layout ---
    fixed_rect: Rect = DEFAULT_FIXED_RECT
    fixed_strings: int = DEFAULT_FIXED_STRINGS
    fixed_low_midi: float = 52.0            # top string; the others climb the scale
    adjust_pinch_on_pu: float = 0.35
    adjust_pinch_off_pu: float = 0.55
    adjust_hold_ms: float = 400.0
    # --- free layout ---
    free_strings: tuple[Seg, ...] = ()
    free_snap: bool = True


def normalize_config(cfg: InstrumentConfig) -> InstrumentConfig:
    """Replace unknown names with defaults (settings can be hand-edited)."""
    layout = cfg.layout if cfg.layout in LAYOUTS else "solo"
    scale = cfg.scale if cfg.scale in SCALE_NAMES else "e_minor_pentatonic"
    chords = tuple(cfg.chords) if len(tuple(cfg.chords)) == 4 else DEFAULT_CHORDS
    chords = tuple(c if c in CHORD_NAMES else DEFAULT_CHORDS[i] for i, c in enumerate(chords))
    dominant = cfg.dominant if cfg.dominant in (Handedness.LEFT, Handedness.RIGHT) else Handedness.RIGHT
    rect = normalize_fixed_rect(cfg.fixed_rect, DEFAULT_FIXED_RECT)
    lo, hi = FIXED_STRINGS_RANGE
    try:
        count = int(min(hi, max(lo, int(cfg.fixed_strings))))
    except (TypeError, ValueError):
        count = DEFAULT_FIXED_STRINGS
    free = normalize_free_strings(cfg.free_strings)
    if (layout, scale, chords, dominant, rect, count, free) == (cfg.layout, cfg.scale, tuple(cfg.chords), cfg.dominant,
                                                                tuple(cfg.fixed_rect), cfg.fixed_strings,
                                                                tuple(tuple(x) for x in cfg.free_strings)):
        return cfg
    return replace(cfg, layout=layout, scale=scale, chords=chords, dominant=dominant,  # type: ignore[arg-type]
                   fixed_rect=rect, fixed_strings=count, free_strings=free)


def fixed_pitches(scale: str, low: float, count: int) -> tuple[float, ...]:
    """`count` consecutive degrees of `scale` from `low` upward (top string first)."""
    notes = music.scale_pitches(scale, low, low + 60.0)
    return tuple(float(n) for n in notes[:count])


def fixed_lines(rect: Rect, count: int, w: int, h: int) -> tuple[tuple[Vec, Vec], ...]:
    """Horizontal string lines (camera px), top first, evenly spread over the rectangle height."""
    x0, y0, x1, y1 = rect
    out = []
    for k in range(count):
        y = y0 + (y1 - y0) * (k / (count - 1) if count > 1 else 0.5)
        out.append(((x0 * w, y * h), (x1 * w, y * h)))
    return tuple(out)


@dataclass
class _Voice:
    note_id: int
    base: float          # smoothed continuous pitch at the strike
    t_ms: float
    last_sent: float = 0.0


@dataclass
class _Pick:
    detectors: list[CrossingDetector]
    tip: Vec
    t_ms: float


@dataclass
class _Adjust:
    since: float
    engaged: bool = False


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
        self._fixed_pitches = fixed_pitches(self._cfg.scale, self._cfg.fixed_low_midi, self._cfg.fixed_strings)
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
        self._rect: Rect = self._cfg.fixed_rect
        self._picks: dict[int, _Pick] = {}
        self._adjust: Optional[_Adjust] = None
        self._free: tuple[Seg, ...] = self._cfg.free_strings
        self._editor = FreeEditor(on_pu=self._cfg.adjust_pinch_on_pu, off_pu=self._cfg.adjust_pinch_off_pu,
                                  hold_ms=self._cfg.adjust_hold_ms)
        self._edit = None

    @property
    def fixed_rect(self) -> Rect:
        return self._rect

    @property
    def free_strings(self) -> tuple[Seg, ...]:
        return self._free

    def all_off(self, t_ms: float, fade_ms: float = DEFAULT_FADE_MS) -> AllOff:
        self.reset()
        return AllOff(fade_ms=fade_ms, t_ms=t_ms)

    # ------------------------------------------------------------------ main step

    def update(self, frame: FrameFeatures, active: bool) -> tuple[list[InstrumentEvent], InstrumentView]:
        if self._cfg.layout == "fixed":
            return self._update_fixed(frame, active)
        if self._cfg.layout == "free":
            return self._update_free(frame, active)
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

    # ------------------------------------------------------------------ fixed layout

    def _update_fixed(self, frame: FrameFeatures, active: bool) -> tuple[list[InstrumentEvent], InstrumentView]:
        cfg = self._cfg
        t = frame.capture_ms
        w, h = frame.width, frame.height
        events: list[InstrumentEvent] = []
        hits: list[HitView] = []
        gap = self._last_t is not None and t - self._last_t > cfg.max_gap_ms
        duplicate = self._last_t is not None and t <= self._last_t
        if not duplicate:
            self._last_t = t
        usable = [x for x in frame.hands
                  if x.quality is Quality.USABLE and _scale_ok(x) and _px(x, INDEX_TIP, w, h) is not None]
        ambiguous = frame.identity_ambiguous or len({x.hand_id for x in usable}) != len(usable)

        if not duplicate:
            self._step_adjust(usable, t, w, h, active and not ambiguous and not gap)
        adjusting = self._adjust is not None and self._adjust.engaged
        if not adjusting and self._rect != cfg.fixed_rect:
            self._cfg = cfg = replace(cfg, fixed_rect=self._rect)          # survives reset()/all_off()
        lines = fixed_lines(self._rect, cfg.fixed_strings, w, h)
        safe = not ambiguous and not gap and not adjusting
        playing = bool(active and safe and usable)

        if active and safe and not duplicate:
            strikes: list[Strike] = []
            seen = set()
            for hand in usable:
                tip = _px(hand, INDEX_TIP, w, h)
                assert tip is not None
                seen.add(hand.hand_id)
                pick = self._picks.get(hand.hand_id)
                if pick is None:
                    pick = _Pick([CrossingDetector(k) for k in range(len(lines))], tip, t)
                    self._picks[hand.hand_id] = pick
                p_scale = float(hand.palm_scale_px)
                for det in pick.detectors:
                    line = lines[det.slot]
                    st = det.update(line, line, pick.tip, tip, pick.t_ms, t, band_px=cfg.band_pu * p_scale,
                                    end_margin=cfg.end_margin, pick_scale_px=p_scale,
                                    min_speed_pu_s=cfg.min_speed_pu_s, cooldown_ms=cfg.cooldown_ms)
                    if st is not None:
                        strikes.append(st)
                pick.tip, pick.t_ms = tip, t
            for hid in [k for k in self._picks if k not in seen]:
                del self._picks[hid]
            if strikes:
                self._emit_fixed(strikes, t, events, hits)
        elif not duplicate:
            self._picks.clear()

        if adjusting:
            status = STATUS_ADJUSTING
        elif not active:
            status = STATUS_PAUSED
        elif ambiguous or gap:
            status = STATUS_UNCERTAIN
        elif not usable:
            status = STATUS_NEED_HAND
        else:
            status = STATUS_READY
        names = [music.midi_to_name(m) for m in self._fixed_pitches]
        strings = tuple(
            StringView(k, a, b, self._amplitude(k, t), names[k] if k < len(names) else "", playing)
            for k, (a, b) in enumerate(lines))
        tips = [x for x in usable if x.handedness is cfg.dominant] or usable
        tip = _px(tips[0], INDEX_TIP, w, h) if tips else None
        view = InstrumentView(
            t_ms=t, width=w, height=h, layout="fixed", strings=strings, hits=tuple(hits),
            note_label=self._note_name, chord_label="", playing=playing, status=status, pick_tip=tip,
            pick_hand_id=tips[0].hand_id if tips else None, fixed_rect=self._rect, adjusting=adjusting,
        )
        return events, view

    def _update_free(self, frame: FrameFeatures, active: bool) -> tuple[list[InstrumentEvent], InstrumentView]:
        cfg = self._cfg
        t = frame.capture_ms
        w, h = frame.width, frame.height
        events: list[InstrumentEvent] = []
        hits: list[HitView] = []
        gap = self._last_t is not None and t - self._last_t > cfg.max_gap_ms
        duplicate = self._last_t is not None and t <= self._last_t
        if not duplicate:
            self._last_t = t
        usable = [x for x in frame.hands
                  if x.quality is Quality.USABLE and _scale_ok(x) and _px(x, INDEX_TIP, w, h) is not None]
        ambiguous = frame.identity_ambiguous or len({x.hand_id for x in usable}) != len(usable)
        aspect = w / h if w > 0 and h > 0 else 4.0 / 3.0

        if not duplicate:
            pinches = []
            for x in usable:
                a, b = _px(x, THUMB_TIP, w, h), _px(x, INDEX_TIP, w, h)
                if a is not None and b is not None and w > 0 and h > 0:
                    m = lerp(a, b, 0.5)
                    pinches.append(HandPinch(x.hand_id, (m[0] / w, m[1] / h), float(x.pinch_distance)))
            self._edit = self._editor.step(self._free, pinches, t, aspect, cfg.free_snap,
                                           allowed=active and not ambiguous and not gap)
            if self._edit.committed:
                self._free = self._edit.strings
                self._cfg = replace(self._cfg, free_strings=self._free)   # survives reset()/all_off()
                self._picks.clear()
                self._amps.clear()
        edit = self._edit
        shown = edit.strings if edit is not None else self._free
        editing = edit is not None and edit.editing
        order = pitch_order(shown)
        pitches = fixed_pitches(cfg.scale, cfg.fixed_low_midi, len(shown))
        pitch_of = {i: pitches[rank] for rank, i in enumerate(order) if rank < len(pitches)}
        lines = tuple(((s[0] * w, s[1] * h), (s[2] * w, s[3] * h)) for s in shown)
        safe = not ambiguous and not gap and not editing
        playing = bool(active and safe and usable and lines)
        pinched = self._editor.pinched_ids()

        if active and safe and not duplicate:
            strikes: list[Strike] = []
            seen = set()
            for hand in usable:
                tip = _px(hand, INDEX_TIP, w, h)
                assert tip is not None
                if hand.hand_id in pinched:      # a pinching hand is grabbing, not playing
                    continue
                seen.add(hand.hand_id)
                pick = self._picks.get(hand.hand_id)
                if pick is None or len(pick.detectors) != len(lines):
                    pick = _Pick([CrossingDetector(k) for k in range(len(lines))], tip, t)
                    self._picks[hand.hand_id] = pick
                p_scale = float(hand.palm_scale_px)
                for det in pick.detectors:
                    line = lines[det.slot]
                    st = det.update(line, line, pick.tip, tip, pick.t_ms, t, band_px=cfg.band_pu * p_scale,
                                    end_margin=cfg.end_margin, pick_scale_px=p_scale,
                                    min_speed_pu_s=cfg.min_speed_pu_s, cooldown_ms=cfg.cooldown_ms)
                    if st is not None:
                        strikes.append(st)
                pick.tip, pick.t_ms = tip, t
            for hid in [k for k in self._picks if k not in seen]:
                del self._picks[hid]
            if strikes:
                self._emit_by_pitch(strikes, pitch_of, t, events, hits)
        elif not duplicate:
            self._picks.clear()

        if editing:
            status = STATUS_EDITING
        elif not active:
            status = STATUS_PAUSED
        elif ambiguous or gap:
            status = STATUS_UNCERTAIN
        elif edit is not None and edit.full:
            status = STATUS_FULL
        elif not lines:
            status = STATUS_NO_STRINGS
        elif not usable:
            status = STATUS_NEED_HAND
        else:
            status = STATUS_READY
        active_idx = edit.active if edit is not None else None
        strings = tuple(
            StringView(k, a, b, self._amplitude(k, t), music.midi_to_name(pitch_of[k]) if k in pitch_of else "",
                       playing or k == active_idx)
            for k, (a, b) in enumerate(lines))
        free_hands = [x for x in usable if x.hand_id not in pinched]
        tips = [x for x in free_hands if x.handedness is cfg.dominant] or free_hands
        tip = _px(tips[0], INDEX_TIP, w, h) if tips else None
        view = InstrumentView(
            t_ms=t, width=w, height=h, layout="free", strings=strings, hits=tuple(hits),
            note_label=self._note_name, chord_label="", playing=playing, status=status, pick_tip=tip,
            pick_hand_id=tips[0].hand_id if tips else None, adjusting=editing, free_strings=shown,
            free_active=active_idx, free_snapped=bool(edit is not None and edit.snapped),
            free_pending=edit.pending if edit is not None else (),
            free_full=bool(edit is not None and edit.full),
        )
        return events, view

    def _emit_by_pitch(self, strikes: list[Strike], pitch_of: dict[int, float], t: float,
                       events: list[InstrumentEvent], hits: list[HitView]) -> None:
        cfg = self._cfg
        strikes.sort(key=lambda s: (s.t_ms, s.slot))
        delay = 0.0
        prev_t: Optional[float] = None
        for st in strikes:
            midi = pitch_of.get(st.slot)
            if midi is None:
                continue
            if prev_t is not None:
                delay += min(cfg.strum_max_ms, max(cfg.strum_min_ms, st.t_ms - prev_t))
            prev_t = st.t_ms
            vel = self._velocity(st.speed_pu_s, st.direction)
            nid = self._next_id
            self._next_id += 1
            events.append(NoteOn(string=st.slot, midi=midi, velocity=vel, note_id=nid, t_ms=t, delay_ms=delay))
            hits.append(HitView(st.slot, st.point[0], st.point[1], vel, st.direction, t))
            self._amps[st.slot] = (vel, t + delay)
            self._note_name = music.midi_to_name(midi)

    def _step_adjust(self, usable: list[HandFeatures], t: float, w: int, h: int, allowed: bool) -> None:
        """Two-hand pinch: hold to grab the string area, move both hands to place/resize it, release."""
        cfg = self._cfg
        adj = self._adjust
        limit = cfg.adjust_pinch_off_pu if adj is not None and adj.engaged else cfg.adjust_pinch_on_pu
        pinched = [x for x in usable if math.isfinite(x.pinch_distance) and x.pinch_distance < limit]
        if not allowed or len(usable) != 2 or len(pinched) != 2 or w <= 0 or h <= 0:
            self._adjust = None
            return
        if adj is None:
            self._adjust = adj = _Adjust(t)
        if not adj.engaged and t - adj.since >= cfg.adjust_hold_ms:
            adj.engaged = True
            self._picks.clear()
        if not adj.engaged:
            return
        pts = []
        for x in pinched:
            a, b = _px(x, THUMB_TIP, w, h), _px(x, INDEX_TIP, w, h)
            if a is None or b is None:
                return
            pts.append(lerp(a, b, 0.5))
        (ax, ay), (bx, by) = pts
        self._rect = normalize_fixed_rect((ax / w, ay / h, bx / w, by / h), self._rect)

    def _emit_fixed(self, strikes: list[Strike], t: float, events: list[InstrumentEvent],
                    hits: list[HitView]) -> None:
        cfg = self._cfg
        strikes.sort(key=lambda s: (s.t_ms, s.slot))
        delay = 0.0
        prev_t: Optional[float] = None
        for st in strikes:
            if st.slot >= len(self._fixed_pitches):
                continue
            if prev_t is not None:
                delay += min(cfg.strum_max_ms, max(cfg.strum_min_ms, st.t_ms - prev_t))
            prev_t = st.t_ms
            vel = self._velocity(st.speed_pu_s, st.direction)
            midi = self._fixed_pitches[st.slot]
            nid = self._next_id
            self._next_id += 1
            events.append(NoteOn(string=st.slot, midi=midi, velocity=vel, note_id=nid, t_ms=t, delay_ms=delay))
            hits.append(HitView(st.slot, st.point[0], st.point[1], vel, st.direction, t))
            self._amps[st.slot] = (vel, t + delay)
            self._note_name = music.midi_to_name(midi)

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
    "InstrumentConfig", "InstrumentEngine", "STATUS_ADJUSTING", "STATUS_EDITING", "STATUS_FULL", "STATUS_NO_STRINGS", "STATUS_NEED_HAND", "STATUS_NEED_PICK", "STATUS_NEED_STRING", "STATUS_PAUSED",
    "STATUS_READY", "STATUS_TOO_CLOSE", "STATUS_UNCERTAIN", "fixed_lines", "fixed_pitches", "normalize_config",
]
