"""String layout (solo: 1 string, chord: 4 parallel strings) and the per-string crossing detector.

Crossing detection never looks at the last position only. Per string and frame it compares the side
(signed distance) of the previous fingertip to the previous string with the side of the current
fingertip to the current string; the zero crossing is interpolated in time (the string moves too), and
the along-string parameter at that moment decides whether the tip passed over the string or around
its end. A Schmitt-trigger band around the string confirms the side change: a strike fires only when
the tip has left the band on the opposite side, so a trembling finger inside the band never re-fires.
Stdlib only, deterministic (times come from the caller).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from handcontrol.instrument.geometry import (
    Vec, add, dist, dot, lerp, normal, project_param, scale, segment_intersection, signed_distance, sub,
)

# The "down" orientation of the string normal flips only after the normal's y component passed
# this far to the other side (~15 deg past horizontal-normal), so string order / strum direction
# do not flicker for a near-vertical string.
DOWN_FLIP_Y = 0.26
# The side away from the palm is re-decided only when the palm centre is clearly off the string line.
SIDE_DECIDE_PU = 0.15


@dataclass(frozen=True)
class StringLine:
    slot: int        # physical slot: 0 = main string (thumb tip -> index tip), 1.. = offsets away from the palm
    index: int       # note order: 0 = lowest note = the string a downstroke hits first
    p0: Vec          # thumb side end (camera px)
    p1: Vec          # index side end


@dataclass(frozen=True)
class Layout:
    lines: tuple[StringLine, ...]     # ordered by slot
    down_sign: int                    # +1: canonical normal of thumb->index points down in the image
    side_sign: int                    # offsets go along side_sign * canonical normal


class StringLayout:
    """Builds the string lines from the string hand. Keeps two small hysteresis states."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._down: Optional[int] = None
        self._side: Optional[int] = None

    def build(self, thumb: Vec, index: Vec, palm: Vec, scale_px: float, count: int,
              spacing_pu: float) -> Layout:
        n = normal(thumb, index)
        if self._down is None:
            self._down = 1 if n[1] >= 0.0 else -1
        elif n[1] * self._down < -DOWN_FLIP_Y:
            self._down = -self._down
        d_palm = dot(sub(palm, thumb), n)
        if self._side is None or abs(d_palm) > SIDE_DECIDE_PU * scale_px:
            if d_palm != 0.0:
                self._side = -1 if d_palm > 0.0 else 1
            elif self._side is None:
                self._side = self._down
        down, side = self._down, self._side
        lines = []
        for k in range(count):
            off = scale(n, side * k * spacing_pu * scale_px)
            idx = k if side * down > 0 else count - 1 - k
            lines.append(StringLine(k, idx, add(thumb, off), add(index, off)))
        return Layout(tuple(lines), down, side)


@dataclass(frozen=True)
class Strike:
    slot: int
    t_ms: float          # interpolated crossing time
    fraction: float      # 0..1 position of the crossing inside the frame step
    u: float             # along-string parameter at the crossing (0 = thumb end, 1 = index end)
    point: Vec           # crossing point on the string (camera px)
    speed_pu_s: float    # fingertip speed of that step, pick-hand palm units per second
    direction: int       # +1 down / -1 up (in the layout's down orientation)


@dataclass(frozen=True)
class _Candidate:
    t_ms: float
    fraction: float
    u: float
    point: Vec
    speed: float
    in_extent: bool
    rel_sign: int        # +1 the tip moved along +canonical normal relative to the string


def _sign(x: float) -> int:
    return 1 if x > 0.0 else (-1 if x < 0.0 else 0)


class CrossingDetector:
    """One string. update() returns a Strike or None.

    State: confirmed side (+1/-1, None = needs a fresh observation outside the band), the raw sign of the
    previous frame, the pending zero crossing toward the other side, and the time of the last strike.
    """

    def __init__(self, slot: int) -> None:
        self.slot = slot
        self.reset()

    def reset(self) -> None:
        self.side: Optional[int] = None
        self._raw: int = 0
        self._pending: Optional[_Candidate] = None
        self._last_fire: Optional[float] = None

    def reset_side(self) -> None:
        """Forget the side (fresh observation required) but keep the cooldown clock."""
        last = self._last_fire
        self.reset()
        self._last_fire = last

    def update(self, prev_line: tuple[Vec, Vec], line: tuple[Vec, Vec], tip0: Vec, tip1: Vec,
               t0: float, t1: float, *, band_px: float, end_margin: float, pick_scale_px: float,
               min_speed_pu_s: float, cooldown_ms: float, allow: bool = True) -> Optional[Strike]:
        a, b = line
        d1 = signed_distance(tip1, a, b)
        if self.side is None:
            if abs(d1) > band_px:
                self.side = _sign(d1)
            self._raw = _sign(d1)
            self._pending = None
            return None
        raw1 = _sign(d1) or self._raw
        if raw1 != self._raw and self._raw != 0:
            cand = self._candidate(prev_line, line, tip0, tip1, t0, t1, end_margin, pick_scale_px, d1)
            self._pending = cand if raw1 == -self.side else None
        self._raw = raw1
        if abs(d1) > band_px and _sign(d1) == -self.side:
            c = self._pending
            self.side = -self.side
            self._pending = None
            if (c is not None and allow and c.in_extent and c.speed >= min_speed_pu_s
                    and (self._last_fire is None or c.t_ms - self._last_fire >= cooldown_ms)):
                self._last_fire = c.t_ms
                return Strike(self.slot, c.t_ms, c.fraction, c.u, c.point, c.speed, c.rel_sign)
        return None

    @staticmethod
    def _candidate(prev_line: tuple[Vec, Vec], line: tuple[Vec, Vec], tip0: Vec, tip1: Vec, t0: float,
                   t1: float, end_margin: float, pick_scale_px: float, d1: float) -> _Candidate:
        a0, b0 = prev_line
        a, b = line
        d0 = signed_distance(tip0, a0, b0)
        f = d0 / (d0 - d1) if d0 != d1 else 1.0
        f = min(1.0, max(0.0, f)) if math.isfinite(f) else 1.0
        af, bf = lerp(a0, a, f), lerp(b0, b, f)
        pf = lerp(tip0, tip1, f)
        u = project_param(pf, af, bf)
        lo, hi = end_margin, 1.0 - end_margin
        ok = lo <= u <= hi
        point = lerp(af, bf, min(1.0, max(0.0, u)))
        if not ok:
            # fallback: plain swept-segment test against the current or previous string
            for qa, qb in ((a, b), (a0, b0)):
                hit = segment_intersection(tip0, tip1, qa, qb)
                if hit is not None and lo <= hit[1] <= hi:
                    f, u, ok = hit[0], hit[1], True
                    point = lerp(qa, qb, u)
                    break
        dt_s = (t1 - t0) / 1000.0
        speed = dist(tip0, tip1) / dt_s / pick_scale_px if dt_s > 0 and pick_scale_px > 0 else 0.0
        rel = 1 if d1 > d0 else -1
        return _Candidate(t0 + f * (t1 - t0), f, u, point, speed, ok, rel)


__all__ = ["CrossingDetector", "DOWN_FLIP_Y", "Layout", "Strike", "StringLayout", "StringLine"]
