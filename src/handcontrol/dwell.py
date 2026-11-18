"""Dwell click helper for the engaged relative pointer (pure, stdlib only).

Arming: the cursor has moved at least `arm_move_px` (displacement) from where tracking of it began
or from the last dwell click. Armed, the cursor resting within `radius_px` of an anchor for
`dwell_ms` fires one click at the anchor; leaving the radius re-anchors. After a click the
helper disarms again, so a second click needs the cursor to leave the radius (by arm_move_px).
cancel() (disengage, tracking gap, pinch, menu) forgets everything: arming starts over.
"""
from __future__ import annotations

import math
from typing import Optional


class DwellClicker:
    def __init__(self, radius_px: float = 14.0, arm_move_px: float = 40.0) -> None:
        self.radius_px = radius_px
        self.arm_move_px = arm_move_px
        self.cancel()

    def cancel(self) -> None:
        self._origin: Optional[tuple[int, int]] = None
        self._armed = False
        self._anchor: Optional[tuple[int, int]] = None
        self._anchor_t = 0.0

    @property
    def armed(self) -> bool:
        return self._armed

    def update(self, t_ms: float, pos: Optional[tuple[int, int]], dwell_ms: float) -> Optional[tuple[int, int]]:
        """One frame of the cursor position. Returns the click point when the dwell completes."""
        if pos is None:
            self.cancel()
            return None
        if self._origin is None:
            self._origin = pos
        if not self._armed:
            if math.dist(pos, self._origin) < self.arm_move_px:
                return None
            self._armed = True
            self._anchor, self._anchor_t = pos, t_ms
            return None
        if self._anchor is None or math.dist(pos, self._anchor) > self.radius_px:
            self._anchor, self._anchor_t = pos, t_ms
            return None
        if t_ms - self._anchor_t >= dwell_ms:
            hit = self._anchor
            self._origin, self._armed, self._anchor = hit, False, None
            return hit
        return None

    def progress(self, t_ms: float, dwell_ms: float) -> float:
        """0..1 of the running dwell (0 when not armed / no anchor)."""
        if not self._armed or self._anchor is None or dwell_ms <= 0:
            return 0.0
        return max(0.0, min(1.0, (t_ms - self._anchor_t) / dwell_ms))

    def held_ms(self, t_ms: float) -> float:
        if not self._armed or self._anchor is None:
            return 0.0
        return max(0.0, t_ms - self._anchor_t)


__all__ = ["DwellClicker"]
