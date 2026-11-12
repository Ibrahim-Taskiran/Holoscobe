"""Thumb + middle fingertip pinch detection (right click); no camera, GUI or OS imports.

Image-plane distance only (landmarks 4 and 12, x*width / y*height), normalized by
palm_scale_px; z is never used. Hysteresis + debounce like gestures.py's thumb+index pinch.
"""
from __future__ import annotations

import math
from typing import Optional

from handcontrol.contracts import HandFeatures, Quality

THUMB_TIP, MIDDLE_TIP = 4, 12

START, END, CANCEL = "start", "end", "cancel"


def middle_pinch_distance(hand: HandFeatures, width: int, height: int) -> float:
    """Thumb tip to middle tip in palm units; inf when it cannot be measured."""
    lms = hand.landmarks
    if len(lms) != 21 or hand.palm_scale_px <= 0 or width <= 0 or height <= 0:
        return math.inf
    a, b = lms[THUMB_TIP], lms[MIDDLE_TIP]
    d = math.hypot((a.x - b.x) * width, (a.y - b.y) * height) / hand.palm_scale_px
    return d if math.isfinite(d) else math.inf


class MiddlePinchRecognizer:
    """One hand at a time. `update` returns START / END / CANCEL or None.

    START after `debounce_ms` at or below `on_pu`, END after `debounce_ms` at or above `off_pu`.
    The hand must be seen open (>= off_pu) before its first pinch, so a hand that enters the
    frame already pinched never fires. A hand change, a frame gap above `max_gap_ms` or an
    unmeasurable sample while pinched gives CANCEL (never a click) and requires a new release.
    """

    def __init__(self, on_pu: float = 0.28, off_pu: float = 0.42, debounce_ms: float = 70.0,
                 max_gap_ms: float = 150.0) -> None:
        if not 0.0 < on_pu < off_pu:
            raise ValueError("need 0 < on_pu < off_pu")
        self.on_pu = on_pu
        self.off_pu = off_pu
        self.debounce_ms = debounce_ms
        self.max_gap_ms = max_gap_ms
        self.reset()

    def reset(self) -> None:
        self.hand_id: Optional[int] = None
        self.pinched = False
        self.start_ms: Optional[float] = None   # capture time of the last START
        self.needs_release = True
        self.pending_since: Optional[float] = None
        self.last_ms: Optional[float] = None
        self.distance = math.inf

    def update(self, hand: HandFeatures, t_ms: float, width: int, height: int) -> Optional[str]:
        d = middle_pinch_distance(hand, width, height) if hand.quality is Quality.USABLE else math.inf
        gap = self.last_ms is None or not 0.0 <= t_ms - self.last_ms <= self.max_gap_ms
        if self.hand_id != hand.hand_id or gap or not math.isfinite(t_ms) or not math.isfinite(d):
            was = self.pinched
            self.reset()
            if math.isfinite(t_ms):
                self.hand_id, self.last_ms = hand.hand_id, t_ms
            self.distance = d
            if math.isfinite(d) and d >= self.off_pu:
                self.needs_release = False
            return CANCEL if was else None
        self.last_ms = t_ms
        self.distance = d
        if not self.pinched:
            if self.needs_release:
                self.pending_since = None
                if d >= self.off_pu:
                    self.needs_release = False
            elif d <= self.on_pu:
                if self.pending_since is None:
                    self.pending_since = t_ms
                if t_ms - self.pending_since >= self.debounce_ms:
                    self.pinched, self.pending_since, self.start_ms = True, None, t_ms
                    return START
            else:
                self.pending_since = None
        else:
            if d >= self.off_pu:
                if self.pending_since is None:
                    self.pending_since = t_ms
                if t_ms - self.pending_since >= self.debounce_ms:
                    self.pinched, self.pending_since = False, None
                    return END
            else:
                self.pending_since = None
        return None
