"""Relative pointer motion: leash dead zone, speed-dependent gain, sub-pixel friendly float deltas,
and clamping of a float cursor onto real monitor pixels. Stdlib + contracts + mapping only.

Units: anchor positions are camera pixels divided by the frame WIDTH on both axes ("frame widths",
fw), so travel does not depend on camera resolution and both axes share one scale. Deltas are
desktop (physical) pixels as floats; the caller keeps the float cursor, so sub-pixel remainders
accumulate instead of being rounded away.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

from handcontrol.contracts import Monitor
from handcontrol.mapping import bounding_rect, project_to_monitors


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


@dataclass(frozen=True)
class AccelCurve:
    """Gain in desktop px per frame width of hand travel, as a smooth function of hand speed."""

    min_gain: float = 1200.0     # slow, precise motion
    max_gain: float = 9000.0     # brisk motion: ~0.25 fw crosses a 1920 px monitor
    slow_speed: float = 0.08     # fw/s at or below which min_gain applies
    fast_speed: float = 0.80     # fw/s at or above which max_gain applies

    def gain(self, speed: float) -> float:
        lo, hi = self.slow_speed, self.fast_speed
        if not math.isfinite(speed) or hi <= lo:
            return self.min_gain
        u = _clamp((speed - lo) / (hi - lo), 0.0, 1.0)
        s = u * u * (3.0 - 2.0 * u)            # smoothstep: no step, zero slope at both ends
        return self.min_gain + (self.max_gain - self.min_gain) * s


class RelativeMotion:
    """Turns successive anchor positions (fw) into desktop pixel deltas.

    - `reset()` forgets the reference (clutch): the next `step` only re-anchors, so re-engaging
      never jumps.
    - Leash dead zone: the reference trails the anchor by at most `dead_zone` fw. Jitter inside it
      is absorbed (a still hand gives a still cursor); motion beyond it passes continuously.
    - Speed is an exponential average of the leash-filtered speed; the gain follows `curve`.
    """

    def __init__(self, curve: AccelCurve = AccelCurve(), dead_zone: float = 0.003, speed_tau_ms: float = 40.0,
                 max_gap_ms: float = 250.0) -> None:
        self.curve = curve
        self.dead_zone = max(0.0, dead_zone)
        self.speed_tau_ms = speed_tau_ms
        self.max_gap_ms = max_gap_ms
        self.reset()

    def reset(self) -> None:
        self._ref: Optional[tuple[float, float]] = None
        self._t: Optional[float] = None
        self.speed = 0.0

    @property
    def anchored(self) -> bool:
        return self._ref is not None

    def anchor(self, t_ms: float, x: float, y: float) -> None:
        """Set the reference explicitly (e.g. the hand position at pinch start)."""
        self._ref, self._t, self.speed = (x, y), t_ms, 0.0

    def step(self, t_ms: float, x: float, y: float, multiplier: float = 1.0) -> tuple[float, float]:
        if not (math.isfinite(t_ms) and math.isfinite(x) and math.isfinite(y)):
            self.reset()
            return 0.0, 0.0
        if self._ref is None or self._t is None or not 0.0 < t_ms - self._t <= self.max_gap_ms:
            self.anchor(t_ms, x, y)
            return 0.0, 0.0
        dt = t_ms - self._t
        self._t = t_ms
        rx, ry = self._ref
        ddx, ddy = x - rx, y - ry
        d = math.hypot(ddx, ddy)
        a = 1.0 if self.speed_tau_ms <= 0 else 1.0 - math.exp(-dt / self.speed_tau_ms)
        if d <= self.dead_zone:
            self.speed += a * (0.0 - self.speed)
            return 0.0, 0.0
        k = (d - self.dead_zone) / d
        ex, ey = ddx * k, ddy * k
        self._ref = (x - ddx / d * self.dead_zone, y - ddy / d * self.dead_zone)
        inst = math.hypot(ex, ey) / (dt / 1000.0)
        self.speed += a * (inst - self.speed)
        g = self.curve.gain(self.speed) * (multiplier if multiplier > 0 else 1.0)
        return ex * g, ey * g


def advance(pos: tuple[float, float], delta: tuple[float, float], monitors: Sequence[Monitor]
            ) -> tuple[tuple[float, float], Optional[tuple[int, int]]]:
    """Move a float cursor by `delta`; return (new float position, real pixel to show).

    The float position may sit in a void of the bounding box (gap between monitors, area beside a
    shorter monitor) so a stroke can cross a gap. Motion that does not go deeper into the void
    first snaps the float position back to the shown pixel, so reversing or sliding along an edge
    responds at once. The bounding box always clamps.
    """
    box = bounding_rect(monitors)
    if box is None:
        return pos, None
    fx, fy = pos
    dx, dy = delta
    shown = project_to_monitors(fx, fy, monitors)
    if shown is not None:
        vx, vy = shown[0] - fx, shown[1] - fy           # from the float position back to real pixels
        dn, vn = math.hypot(dx, dy), math.hypot(vx, vy)
        # vn > 1 px: a void, not rounding; the motion is not mostly going deeper into it
        if vn > 1.0 and dn > 0.0 and -(dx * vx + dy * vy) <= 0.5 * dn * vn:
            fx, fy = float(shown[0]), float(shown[1])
    fx = _clamp(fx + dx, box.left, box.right - 1)
    fy = _clamp(fy + dy, box.top, box.bottom - 1)
    return (fx, fy), project_to_monitors(fx, fy, monitors)


__all__ = ["AccelCurve", "RelativeMotion", "advance"]
