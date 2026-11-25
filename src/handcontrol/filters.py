"""Time-aware smoothing, hysteresis and percentile helpers. Stdlib only.

All timestamps are monotonic milliseconds (float), matching handcontrol.contracts.
"""
from __future__ import annotations

import math
from typing import Generic, Optional, TypeVar

T = TypeVar("T")


def _alpha(cutoff_hz: float, dt_s: float) -> float:
    tau = 1.0 / (2.0 * math.pi * cutoff_hz)
    return 1.0 / (1.0 + tau / dt_s)


def percentile(values: list[float], q: float) -> float:
    """Linear interpolation between the sorted values; 0 without values."""
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * q
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


class OneEuroFilter2D:
    """One Euro filter (Casiez et al. 2012) for 2D points; the cutoff adapts to the speed of the vector.

    - dt <= 0 (duplicate or out-of-order timestamp): state is unchanged, the last output is returned.
    - gap > max_gap_ms or a non-finite value/timestamp: the filter resets and passes the value through.
    min_cutoff/beta are unit dependent; the defaults suit pixel-scale pointer input.
    """

    def __init__(self, min_cutoff: float = 1.0, beta: float = 0.007, d_cutoff: float = 1.0,
                 max_gap_ms: float = 250.0) -> None:
        if min_cutoff <= 0 or d_cutoff <= 0 or beta < 0 or max_gap_ms <= 0:
            raise ValueError("invalid One Euro parameters")
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self.max_gap_ms = max_gap_ms
        self.reset()

    def reset(self) -> None:
        self._p: Optional[tuple[float, float]] = None
        self._d = (0.0, 0.0)
        self._t: Optional[float] = None

    def filter(self, point: tuple[float, float], t_ms: float) -> tuple[float, float]:
        x, y = point
        if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(t_ms)):
            self.reset()
            return (x, y)
        dt_ms = math.inf if self._p is None or self._t is None else t_ms - self._t
        if dt_ms <= 0:
            return self._p
        if dt_ms > self.max_gap_ms:
            self._p, self._d, self._t = (x, y), (0.0, 0.0), t_ms
            return (x, y)
        dt = dt_ms / 1000.0
        px, py = self._p
        a_d = _alpha(self.d_cutoff, dt)
        dx = self._d[0] + a_d * ((x - px) / dt - self._d[0])
        dy = self._d[1] + a_d * ((y - py) / dt - self._d[1])
        self._d = (dx, dy)
        a = _alpha(self.min_cutoff + self.beta * math.hypot(dx, dy), dt)
        self._p = (px + a * (x - px), py + a * (y - py))
        self._t = t_ms
        return self._p

    __call__ = filter


class OneEuroFilter(OneEuroFilter2D):
    """Scalar signal."""

    def filter(self, value: float, t_ms: float) -> float:
        return super().filter((value, 0.0), t_ms)[0]

    __call__ = filter


class DwellLatch(Generic[T]):
    """Holds a discrete state; a different proposal must persist for dwell_ms (by timestamp) to win.

    Proposing the current state cancels any pending change. A timestamp that goes backwards
    restarts the pending timer. Frame counts are never used.
    """

    def __init__(self, initial: T, dwell_ms: float = 0.0) -> None:
        self._initial = initial
        self.dwell_ms = dwell_ms
        self.reset()

    @property
    def state(self) -> T:
        return self._state

    def reset(self, state: Optional[T] = None) -> None:
        self._state: T = self._initial if state is None else state
        self._pending: Optional[T] = None
        self._since = 0.0

    def force(self, state: T) -> T:
        """Set the state immediately (e.g. drop to UNKNOWN) and clear any pending change."""
        self._state = state
        self._pending = None
        return state

    def update(self, proposal: T, t_ms: float, dwell_ms: Optional[float] = None) -> T:
        if proposal == self._state:
            self._pending = None
            return self._state
        if not math.isfinite(t_ms):
            return self._state
        if self._pending is None or self._pending != proposal or t_ms < self._since:
            self._pending = proposal
            self._since = t_ms
        need = self.dwell_ms if dwell_ms is None else dwell_ms
        if t_ms - self._since >= need:
            self._state = proposal
            self._pending = None
        return self._state
