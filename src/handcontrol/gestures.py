"""Time-stamped gesture recognizers: FrameFeatures in, GestureEvent out.

Pure logic: no camera, no OS access. Every timing decision uses FrameFeatures.capture_ms, so a
recorded or synthetic sequence replays deterministically. Spec: section 4 item 4/5, section 5
(control model, starting timing, visual clap recognizer).

Per-frame event order: forced ends (loss/ambiguity/gap), PINCH_END, clap events, PINCH_START,
MENU_DWELL_COMPLETE, NEUTRAL. A clap abort caused by a pinch therefore precedes that PINCH_START.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from handcontrol.contracts import (
    FingerName,
    FingerState,
    FrameFeatures,
    GestureEvent,
    GestureKind,
    HandFeatures,
    Handedness,
    Quality,
)
from handcontrol.mode_wheel import is_v


@dataclass(frozen=True)
class GestureConfig:
    """Starting thresholds from the spec. Distances in palm units, times in ms."""

    # pinch (per hand)
    pinch_on_pu: float = 0.28
    pinch_off_pu: float = 0.42
    pinch_debounce_ms: float = 70.0
    pinch_require_initial_release: bool = True   # a hand must be seen open before its first pinch
    pinch_nonusable_grace_ms: float = 200.0      # pinched hand DEGRADED/UNKNOWN this long -> PINCH_END

    # neutral
    neutral_hold_ms: float = 200.0

    # visual clap
    clap_arm_distance_pu: float = 2.0
    clap_arm_hold_ms: float = 120.0
    clap_near_distance_pu: float = 0.85
    clap_approach_max_ms: float = 450.0
    clap_separate_distance_pu: float = 1.6
    clap_separate_max_ms: float = 650.0
    clap_min_closing_speed_pu_s: float = 1.0     # candidate entry and near-zone "clear inward velocity"
    clap_velocity_window_ms: float = 80.0
    clap_min_extended_non_thumb: int = 3
    clap_dropout_max_ms: float = 120.0
    # longest interval between two consecutive samples that keeps a clap trajectory alive. Separate
    # from the dropout budget (missing hands): the DirectShow fallback delivers ~10 fps with jitter,
    # so normal sample intervals exceed 120 ms there.
    clap_max_frame_interval_ms: float = 160.0
    clap_cooldown_ms: float = 900.0
    clap_rebound_abort_pu: float = 0.3           # candidate aborts if distance grows this much before near zone
    # features.py flags identity_ambiguous when palms overlap (< 0.7 pu). During a fast verified approach an
    # ambiguous frame counts as reaching the near zone if the last clean pair distance was at most this.
    clap_ambiguous_near_max_pu: float = 1.3

    # mode-wheel dwell (V pose, see mode_wheel.py)
    menu_dwell_ms: float = 500.0
    menu_max_displacement_pu: float = 0.15
    menu_approach_cancel_speed_pu_s: float = 1.0

    # instrument profile (GestureRecognizer.set_instrument_profile(True), Mode.INSTRUMENT). The playing
    # pose (pick hand: index only; string hand: thumb+index spread) must never clap or open the menu.
    instrument_clap_min_extended_non_thumb: int = 4   # both hands, checked when arming and at candidate entry
    instrument_menu_max_displacement_pu: float = 0.12  # stricter stillness for the dwell

    # timing robustness
    max_frame_gap_ms: float = 200.0              # longer stall = tracking loss: end everything
    timestamp_rewind_reset_ms: float = 1000.0    # backwards jump larger than this = clock reset

    def __post_init__(self) -> None:
        if not 0.0 < self.pinch_on_pu < self.pinch_off_pu:
            raise ValueError("need 0 < pinch_on_pu < pinch_off_pu")
        if not 0.0 < self.clap_near_distance_pu < self.clap_separate_distance_pu:
            raise ValueError("need 0 < clap_near_distance_pu < clap_separate_distance_pu")
        if not self.clap_near_distance_pu < self.clap_arm_distance_pu:
            raise ValueError("need clap_near_distance_pu < clap_arm_distance_pu")
        if self.clap_ambiguous_near_max_pu < self.clap_near_distance_pu:
            raise ValueError("need clap_ambiguous_near_max_pu >= clap_near_distance_pu")
        for name in (
            "pinch_debounce_ms", "pinch_nonusable_grace_ms", "neutral_hold_ms", "clap_arm_hold_ms",
            "clap_approach_max_ms", "clap_separate_max_ms", "clap_velocity_window_ms",
            "clap_dropout_max_ms", "clap_max_frame_interval_ms", "clap_cooldown_ms", "menu_dwell_ms", "max_frame_gap_ms",
            "timestamp_rewind_reset_ms",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be >= 0")
        if self.menu_dwell_ms <= 0:
            raise ValueError("menu_dwell_ms must be > 0")


class _ClapPhase(Enum):
    IDLE = "idle"          # not armed; needs a separated pose held for clap_arm_hold_ms
    ARMED = "armed"
    APPROACH = "approach"  # left the arm zone, heading for near contact
    NEAR = "near"          # reached near contact, waiting for separation


class _HandState:
    __slots__ = ("pinched", "pending_since", "needs_release", "nonusable_since")

    def __init__(self, needs_release: bool) -> None:
        self.pinched = False
        self.pending_since: Optional[float] = None
        self.needs_release = needs_release
        self.nonusable_since: Optional[float] = None


_OTHER_HAND = {Handedness.RIGHT: Handedness.LEFT, Handedness.LEFT: Handedness.RIGHT}


def _finite(*values: float) -> bool:
    return all(math.isfinite(v) for v in values)


def _usable(h: HandFeatures) -> bool:
    return (
        h.quality is Quality.USABLE
        and _finite(h.palm_scale_px, h.pinch_distance, *h.palm_center_px)
        and h.palm_scale_px > 0.0
    )


def _located(h: HandFeatures) -> bool:
    """Palm center worth using even if the hand is not USABLE (contact frames)."""
    return h.quality is not Quality.UNKNOWN and _finite(*h.palm_center_px)


def _any_reported(frame: FrameFeatures) -> bool:
    """Any detected hand at all: counts as contact evidence, not dropout, in the near zone."""
    return any(_finite(*h.palm_center_px) for h in frame.hands)


def _extended(h: HandFeatures) -> tuple[int, int]:
    """(extended non-thumb fingers, extended thumb 0/1)."""
    non_thumb = thumb = 0
    for f in h.fingers:
        if f.state is FingerState.EXTENDED:
            if f.name is FingerName.THUMB:
                thumb = 1
            else:
                non_thumb += 1
    return non_thumb, thumb


class GestureRecognizer:
    def __init__(
        self, config: GestureConfig = GestureConfig(), dominant: Handedness = Handedness.RIGHT
    ) -> None:
        self._cfg = config
        self._dominant = dominant
        self._non_dominant = _OTHER_HAND.get(dominant)  # None (menu disabled) if dominant is UNKNOWN
        self._last_t: Optional[float] = None
        self._last_clap_ms: Optional[float] = None       # survives reset(): cooldown is never skipped
        self._instrument = False                         # survives reset(): set per frame by the pipeline
        self._clear(menu_latch=False)

    # ------------------------------------------------------------------ public API

    def reset(self) -> None:
        """Clear all baselines silently. Hands must show release / neutral again before acting."""
        self._clear(menu_latch=True)

    def set_instrument_profile(self, enabled: bool) -> None:
        """Mode-dependent thresholds: True = INSTRUMENT (stricter clap and menu poses). Cheap; safe to
        call every frame. A change drops a running menu dwell and a clap arm that is not a candidate."""
        enabled = bool(enabled)
        if enabled is self._instrument:
            return
        self._instrument = enabled
        self._cancel_dwell()
        if not self._candidate:
            self._phase = _ClapPhase.IDLE
            self._sep_since = None

    @property
    def instrument_profile(self) -> bool:
        return self._instrument

    def is_pinched(self, hand_id: int) -> bool:
        st = self._hands.get(hand_id)
        return bool(st and st.pinched)

    @property
    def clap_candidate_active(self) -> bool:
        return self._candidate

    @property
    def menu_dwell_progress(self) -> float:
        return self._menu_progress

    @property
    def is_neutral(self) -> bool:
        return self._neutral

    def update(self, frame: FrameFeatures) -> list[GestureEvent]:
        cfg = self._cfg
        t = frame.capture_ms
        if not _finite(t):
            return []
        forced: list[GestureEvent] = []
        prev_t = self._last_t
        if prev_t is not None:
            if t <= prev_t:
                if prev_t - t <= cfg.timestamp_rewind_reset_ms:
                    return []                         # duplicate / out-of-order frame: ignore
                self._drop_all(t, forced)             # clock reset: treat as tracking loss
                self._last_clap_ms = t                # restart cooldown on the new clock
                prev_t = None
            elif t - prev_t > cfg.max_frame_gap_ms:
                self._drop_all(t, forced)
                prev_t = None
        self._last_t = t

        if getattr(frame, "forearms_crossed", False):
            self._drop_all(t, forced)
            return forced

        gap_ok = prev_t is None or t - prev_t <= cfg.clap_max_frame_interval_ms
        ids = [h.hand_id for h in frame.hands]
        if frame.identity_ambiguous or len(ids) != len(set(ids)):
            if self._candidate:
                # Palm overlap at clap contact makes features.py flag ambiguity: tolerate it as contact.
                return forced + self._ambiguous_in_candidate(frame, t, gap_ok)
            self._drop_all(t, forced)
            return forced

        pinch_end, pinch_start = self._update_pinches(frame, t)
        usable = [h for h in frame.hands if _usable(h)]
        pair_d = self._pair_distance(usable)
        if pair_d is None or not gap_ok:
            self._pair_hist.clear()
        speed = None
        if pair_d is not None:
            self._pair_hist.append((t, pair_d))
            while self._pair_hist and t - self._pair_hist[0][0] > 1000.0:
                self._pair_hist.popleft()
            speed = self._closing_speed(t, pair_d)
            self._pair_scale = (usable[0].palm_scale_px + usable[1].palm_scale_px) / 2.0
            self._last_clean_d = pair_d
            self._last_speed = speed

        clap = self._update_clap(t, usable, pair_d, speed, gap_ok, _any_reported(frame))
        menu = self._update_menu(frame, t, speed)
        neutral = self._update_neutral(frame, t)
        return forced + pinch_end + clap + pinch_start + menu + neutral

    # ------------------------------------------------------------------ state helpers

    def _clear(self, menu_latch: bool) -> None:
        self._hands: dict[int, _HandState] = {}
        self._pair_hist: deque[tuple[float, float]] = deque()
        self._phase = _ClapPhase.IDLE
        self._candidate = False
        self._sep_since: Optional[float] = None
        self._last_sep_ms = 0.0
        self._approach_start = 0.0
        self._min_d = math.inf
        self._near_ms = 0.0
        self._prev_sep_d: Optional[float] = None
        self._missing_since: Optional[float] = None
        self._arm_vec: Optional[tuple[float, float]] = None   # RIGHT->LEFT palm vector while armed
        self._pair_scale = 0.0                       # last clean pair: average palm scale (px)
        self._last_clean_d = math.inf
        self._last_speed: Optional[float] = None
        self._neutral_since: Optional[float] = None
        self._neutral = False
        self._dwell_start: Optional[float] = None
        self._dwell_hand: Optional[int] = None
        self._dwell_anchor = (0.0, 0.0)
        self._menu_progress = 0.0
        self._menu_latch = menu_latch

    def _drop_all(self, t: float, out: list[GestureEvent]) -> None:
        """Tracking loss / identity ambiguity: end everything, require re-engagement."""
        for hid, st in self._hands.items():
            if st.pinched:
                out.append(GestureEvent(GestureKind.PINCH_END, t, hid))
        self._hands.clear()
        self._abort_clap(t, out)
        self._pair_hist.clear()
        self._cancel_dwell()
        self._neutral_since = None
        self._neutral = False

    def _cancel_dwell(self) -> None:
        self._dwell_start = None
        self._dwell_hand = None
        self._menu_progress = 0.0

    # ------------------------------------------------------------------ pinch

    def _update_pinches(
        self, frame: FrameFeatures, t: float
    ) -> tuple[list[GestureEvent], list[GestureEvent]]:
        cfg = self._cfg
        ends: list[GestureEvent] = []
        starts: list[GestureEvent] = []
        seen = set()
        for h in frame.hands:
            seen.add(h.hand_id)
            st = self._hands.get(h.hand_id)
            if st is None:
                st = self._hands[h.hand_id] = _HandState(cfg.pinch_require_initial_release)
            if not _usable(h):
                st.pending_since = None                      # never start from non-usable hands
                if st.pinched:
                    if st.nonusable_since is None:
                        st.nonusable_since = t
                    if t - st.nonusable_since >= cfg.pinch_nonusable_grace_ms:
                        st.pinched = False
                        st.needs_release = True
                        st.nonusable_since = None
                        ends.append(GestureEvent(GestureKind.PINCH_END, t, h.hand_id))
                continue
            st.nonusable_since = None
            d = h.pinch_distance
            if not st.pinched:
                if st.needs_release:
                    st.pending_since = None
                    if d >= cfg.pinch_off_pu:
                        st.needs_release = False
                elif d <= cfg.pinch_on_pu:
                    if st.pending_since is None:
                        st.pending_since = t
                    if t - st.pending_since >= cfg.pinch_debounce_ms:
                        st.pinched = True
                        st.pending_since = None
                        starts.append(GestureEvent(GestureKind.PINCH_START, t, h.hand_id))
                else:
                    st.pending_since = None
            else:
                if d >= cfg.pinch_off_pu:
                    if st.pending_since is None:
                        st.pending_since = t
                    if t - st.pending_since >= cfg.pinch_debounce_ms:
                        st.pinched = False
                        st.pending_since = None
                        ends.append(GestureEvent(GestureKind.PINCH_END, t, h.hand_id))
                else:
                    st.pending_since = None
        for hid in [hid for hid in self._hands if hid not in seen]:
            if self._hands.pop(hid).pinched:                 # hand lost: end, re-engage later
                ends.append(GestureEvent(GestureKind.PINCH_END, t, hid))
        return ends, starts

    def _any_pinched(self) -> bool:
        return any(st.pinched for st in self._hands.values())

    def _released(self, hand_id: int) -> bool:
        st = self._hands.get(hand_id)
        return bool(st) and not st.pinched and not st.needs_release and st.pending_since is None

    # ------------------------------------------------------------------ two-hand geometry

    @staticmethod
    def _pair_distance(usable: list[HandFeatures]) -> Optional[float]:
        if len(usable) != 2:
            return None
        a, b = usable
        scale = (a.palm_scale_px + b.palm_scale_px) / 2.0
        return math.dist(a.palm_center_px, b.palm_center_px) / scale

    @staticmethod
    def _oriented(usable: list[HandFeatures]) -> Optional[tuple[float, float]]:
        """RIGHT->LEFT palm vector, or None unless exactly one RIGHT and one LEFT label."""
        if len(usable) != 2:
            return None
        by = {h.handedness: h for h in usable}
        r, l = by.get(Handedness.RIGHT), by.get(Handedness.LEFT)
        if r is None or l is None:
            return None
        return (l.palm_center_px[0] - r.palm_center_px[0], l.palm_center_px[1] - r.palm_center_px[1])

    def _closing_speed(self, t: float, d_now: float) -> Optional[float]:
        """Palm-separation decrease rate (pu/s, positive = approaching) over the velocity window."""
        for t_old, d_old in reversed(self._pair_hist):
            if t - t_old >= self._cfg.clap_velocity_window_ms and t > t_old:
                return (d_old - d_now) * 1000.0 / (t - t_old)
        return None

    # ------------------------------------------------------------------ clap

    def _abort_clap(self, t: float, out: list[GestureEvent]) -> None:
        if self._candidate:
            out.append(GestureEvent(GestureKind.CLAP_CANDIDATE_ABORT, t))
            self._menu_latch = True        # the candidate reserved this input
        self._candidate = False
        self._phase = _ClapPhase.IDLE
        self._sep_since = None
        self._prev_sep_d = None
        self._missing_since = None
        self._min_d = math.inf

    def _clap_min_non_thumb(self) -> int:
        cfg = self._cfg
        return cfg.instrument_clap_min_extended_non_thumb if self._instrument else cfg.clap_min_extended_non_thumb

    def _clap_open(self, usable: list[HandFeatures]) -> bool:
        """Instrument profile arming check: both hands show an open palm."""
        need = self._clap_min_non_thumb()
        return len(usable) == 2 and all(_extended(h)[0] >= need for h in usable)

    def _clap_entry_ok(self, usable: list[HandFeatures]) -> bool:
        cfg = self._cfg
        need = self._clap_min_non_thumb()
        for h in usable:
            st = self._hands.get(h.hand_id)
            if st is None or st.pinched or h.pinch_distance <= cfg.pinch_on_pu:
                return False
            if _extended(h)[0] < need:
                return False
        return True

    def _update_clap(
        self,
        t: float,
        usable: list[HandFeatures],
        d: Optional[float],
        speed: Optional[float],
        gap_ok: bool,
        present: bool,
    ) -> list[GestureEvent]:
        cfg = self._cfg
        ev: list[GestureEvent] = []
        if not gap_ok and self._phase is not _ClapPhase.IDLE:
            self._abort_clap(t, ev)                   # frame stall longer than allowed dropout

        if self._phase is _ClapPhase.IDLE:
            cooled = self._last_clap_ms is None or t - self._last_clap_ms >= cfg.clap_cooldown_ms
            posed = not self._instrument or self._clap_open(usable)
            if d is not None and d > cfg.clap_arm_distance_pu and cooled and posed:
                if self._sep_since is None:
                    self._sep_since = t
                if t - self._sep_since >= cfg.clap_arm_hold_ms:
                    self._phase = _ClapPhase.ARMED
                    self._last_sep_ms = t
                    self._arm_vec = self._oriented(usable)
            else:
                self._sep_since = None
            return ev

        if self._phase is _ClapPhase.ARMED:
            if d is None or (self._instrument and not self._clap_open(usable)):
                self._phase = _ClapPhase.IDLE
                self._sep_since = None
                return ev
            if d > cfg.clap_arm_distance_pu:
                self._last_sep_ms = t
                self._arm_vec = self._oriented(usable)
                return ev
            self._phase = _ClapPhase.APPROACH
            self._approach_start = self._last_sep_ms
            self._min_d = d

        if self._phase is _ClapPhase.APPROACH:
            if d is None:                              # no dropout allowed before near zone
                self._abort_clap(t, ev)
                return ev
            if d > cfg.clap_arm_distance_pu:
                if self._candidate:
                    self._abort_clap(t, ev)
                    self._sep_since = t                # hands are separated again: start a fresh arm hold
                else:
                    self._phase = _ClapPhase.ARMED
                    self._last_sep_ms = t
                return ev
            self._min_d = min(self._min_d, d)
            if self._candidate and (
                self._any_pinched() or d > self._min_d + cfg.clap_rebound_abort_pu
            ):
                self._abort_clap(t, ev)
                return ev
            fast = speed is not None and speed >= cfg.clap_min_closing_speed_pu_s
            if not self._candidate and fast and self._clap_entry_ok(usable):
                self._candidate = True
                ev.append(GestureEvent(GestureKind.CLAP_CANDIDATE_START, t))
            in_time = t - self._approach_start <= cfg.clap_approach_max_ms
            if d <= cfg.clap_near_distance_pu:
                if self._candidate and in_time and fast:
                    self._phase = _ClapPhase.NEAR
                    self._near_ms = t
                    self._prev_sep_d = d
                    self._missing_since = None
                else:
                    self._abort_clap(t, ev)
            elif not in_time:
                self._abort_clap(t, ev)
            return ev

        # NEAR: wait for separation with both hands visible again
        if t - self._near_ms > cfg.clap_separate_max_ms or self._any_pinched():
            self._abort_clap(t, ev)
            return ev
        if d is None:
            self._near_contact_frame(t, present, ev)
            return ev
        if self._missing_since is not None and t - self._missing_since > cfg.clap_dropout_max_ms:
            self._abort_clap(t, ev)
            return ev
        self._missing_since = None
        prev = self._prev_sep_d
        self._prev_sep_d = d
        if prev is not None and d > cfg.clap_separate_distance_pu and d > prev:
            now_vec, arm_vec = self._oriented(usable), self._arm_vec
            if now_vec is not None and arm_vec is not None and (
                now_vec[0] * arm_vec[0] + now_vec[1] * arm_vec[1] < 0.0
            ):
                self._abort_clap(t, ev)               # hands passed each other (crossing), not a clap
                return ev
            ev.append(GestureEvent(GestureKind.CLAP, t))
            self._last_clap_ms = t
            self._candidate = False
            self._phase = _ClapPhase.IDLE
            self._sep_since = None
            self._prev_sep_d = None
            self._menu_latch = True                    # clap input cannot also open the menu
        return ev

    def _near_contact_frame(self, t: float, present: bool, ev: list[GestureEvent]) -> None:
        """NEAR phase frame without a clean pair. Only frames with no hands at all count as dropout."""
        self._prev_sep_d = None                       # separation needs consecutive clean pair frames
        if present:
            self._missing_since = None
            return
        if self._missing_since is None:
            self._missing_since = t
        if t - self._missing_since > self._cfg.clap_dropout_max_ms:
            self._abort_clap(t, ev)

    def _ambiguous_in_candidate(
        self, frame: FrameFeatures, t: float, gap_ok: bool
    ) -> list[GestureEvent]:
        """identity_ambiguous frame while a clap candidate is active (palms overlapping).

        Hand ids may be exchanged here, so per-hand state is dropped (hands must show release before
        pinching again) and finger states are not consulted. The candidate survives as contact.
        """
        cfg = self._cfg
        ev: list[GestureEvent] = []
        for hid, st in self._hands.items():
            if st.pinched:                             # cannot normally happen inside a candidate
                ev.append(GestureEvent(GestureKind.PINCH_END, t, hid))
        self._hands.clear()
        self._neutral_since = None
        self._neutral = False
        self._cancel_dwell()
        if not gap_ok:
            self._abort_clap(t, ev)
            self._pair_hist.clear()
            return ev

        if self._phase is _ClapPhase.APPROACH:
            located = [h for h in frame.hands if _located(h)]
            d = None
            if len(located) == 2 and self._pair_scale > 0.0:
                d = math.dist(located[0].palm_center_px, located[1].palm_center_px) / self._pair_scale
            if d is not None:
                speed = self._closing_speed(t, d)
                reached = d <= cfg.clap_near_distance_pu
            else:
                speed = self._last_speed
                reached = self._last_clean_d <= cfg.clap_ambiguous_near_max_pu
            fast = speed is not None and speed >= cfg.clap_min_closing_speed_pu_s
            in_time = t - self._approach_start <= cfg.clap_approach_max_ms
            if reached and fast and in_time:
                self._phase = _ClapPhase.NEAR
                self._near_ms = t
                self._near_contact_frame(t, _any_reported(frame), ev)
                self._pair_hist.clear()
            elif not in_time:
                self._abort_clap(t, ev)
            return ev

        if self._phase is _ClapPhase.NEAR:
            if t - self._near_ms > cfg.clap_separate_max_ms:
                self._abort_clap(t, ev)
            else:
                self._near_contact_frame(t, _any_reported(frame), ev)
        self._pair_hist.clear()
        return ev

    # ------------------------------------------------------------------ menu dwell

    def _update_menu(
        self, frame: FrameFeatures, t: float, speed: Optional[float]
    ) -> list[GestureEvent]:
        cfg = self._cfg
        if self._non_dominant is None:
            self._cancel_dwell()
            return []
        nd = [h for h in frame.hands if h.handedness is self._non_dominant]
        if self._menu_latch and all(_usable(h) and not is_v(h) for h in nd):
            self._menu_latch = False                  # V released or hand gone
        hand = nd[0] if len(nd) == 1 and _usable(nd[0]) and is_v(nd[0]) else None
        blocked = (
            hand is None
            or self._menu_latch
            or self._candidate
            or self._any_pinched()
            or (speed is not None and speed >= cfg.menu_approach_cancel_speed_pu_s)
        )
        if blocked:
            self._cancel_dwell()
            return []
        assert hand is not None
        if self._dwell_start is None or self._dwell_hand != hand.hand_id:
            self._dwell_start, self._dwell_hand = t, hand.hand_id
            self._dwell_anchor = hand.palm_center_px
        elif (
            math.dist(hand.palm_center_px, self._dwell_anchor) / hand.palm_scale_px
            >= (cfg.instrument_menu_max_displacement_pu if self._instrument else cfg.menu_max_displacement_pu)
        ):
            self._dwell_start = t                      # moved: restart the dwell here
            self._dwell_anchor = hand.palm_center_px
        elapsed = t - self._dwell_start
        if elapsed >= cfg.menu_dwell_ms:
            self._cancel_dwell()
            self._menu_latch = True
            return [GestureEvent(GestureKind.MENU_DWELL_COMPLETE, t, hand.hand_id)]
        self._menu_progress = max(0.0, min(1.0, elapsed / cfg.menu_dwell_ms))
        return []

    # ------------------------------------------------------------------ neutral

    def _update_neutral(self, frame: FrameFeatures, t: float) -> list[GestureEvent]:
        ok = (
            bool(frame.hands)
            and not self._candidate
            and all(_usable(h) and self._released(h.hand_id) for h in frame.hands)
        )
        if not ok:
            self._neutral_since = None
            self._neutral = False
            return []
        if self._neutral_since is None:
            self._neutral_since = t
        if not self._neutral and t - self._neutral_since >= self._cfg.neutral_hold_ms:
            self._neutral = True
            return [GestureEvent(GestureKind.NEUTRAL, t)]
        return []
