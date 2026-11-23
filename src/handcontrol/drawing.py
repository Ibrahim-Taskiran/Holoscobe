"""Rotating ink volume. Coordinates are camera-width units (y measured in the same units)."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass


WORK_DEPTH = 0.075
ERASER_RADIUS = 0.038
CLEAR_MS = 1750.0
SPACING = 0.005


@dataclass(frozen=True, slots=True)
class Dab:
    x: float
    y: float
    z: float
    radius: float
    stretch: float
    born: float
    grain: float


def turn(x: float, z: float, cosine: float, sine: float) -> tuple[float, float]:
    return x * cosine + z * sine, z * cosine - x * sine


class InkScene:
    def __init__(self, seed: int = 72):
        self.dabs: list[Dab] = []
        self.angle = 0.0
        self.clear_start: float | None = None
        self._rng = random.Random(seed)
        self._last: tuple[float, float, float] | None = None
        self._distance = 0.0

    def lift(self):
        self._last = None
        self._distance = 0.0

    def clear(self, now: float):
        self.lift()
        if self.dabs and self.clear_start is None:
            self.clear_start = now

    def advance(self, now: float):
        if self.clear_start is not None and now - self.clear_start >= CLEAR_MS:
            self.dabs.clear()
            self.clear_start = None

    def _stamp(self, x, y, z, radius, stretch, now):
        self.dabs.append(Dab(x, y, z, radius, stretch, now, self._rng.random()))

    def _ink(self, x, y, z, now, first):
        r = self._rng
        width = 0.006 + 0.0015 * math.sin(self._distance * 65)
        radius = (0.012 if first else width) * r.uniform(0.85, 1.15)
        self._stamp(x, y, z, radius, r.uniform(0.88, 1.14), now)
        # Offsets are deposited in the current brush plane, including when already rotated.
        c, s = math.cos(self.angle), math.sin(self.angle)
        if first or r.random() < 0.09:
            for _ in range(r.randint(1, 3)):
                dx = r.uniform(-0.024, 0.024)
                self._stamp(x + dx*c, y + r.uniform(-0.021, 0.021), z + dx*s,
                            r.uniform(0.0012, 0.0032), 1.0, now)
        if r.random() < (0.5 if first else 0.025):
            length = r.uniform(0.013, 0.049)
            self._stamp(x, y + length/2, z, 0.0018, length/0.0036, now)
            self._stamp(x, y + length, z, 0.0027, 1.3, now)

    def paint(self, x: float, y: float, now: float):
        """Invert the current yaw at deposition, resample in 3D, including a stationary spinning brush."""
        if self.clear_start is not None:
            return
        lx, lz = turn(x, WORK_DEPTH, math.cos(self.angle), -math.sin(self.angle))
        target = (lx, y, lz)
        if self._last is None:
            self._ink(*target, now, first=True)
            self._last = target
            return
        start = self._last
        distance = math.dist(start, target)
        if distance < SPACING:
            return
        steps = math.ceil(distance / SPACING)
        for i in range(1, steps + 1):
            t = i / steps
            self._distance += distance / steps
            self._ink(*(v + (w-v)*t for v, w in zip(start, target)), now, first=False)
        self._last = target

    def erase(self, x: float, y: float, previous: tuple[float, float] | None = None):
        """Sweep a local eraser through the front work plane. Holding it cannot tunnel into the back."""
        self.lift()
        if self.clear_start is not None:
            return
        c, s = math.cos(self.angle), math.sin(self.angle)
        ax, ay = previous or (x, y)
        dx, dy = x - ax, y - ay
        length2 = dx*dx + dy*dy

        def hit(d: Dab) -> bool:
            px, depth = turn(d.x, d.z, c, s)
            if abs(depth - WORK_DEPTH) > 0.009:
                return False
            t = min(1.0, max(0.0, ((px-ax)*dx + (d.y-ay)*dy)/length2)) if length2 else 0.0
            # The elongated body of a drip is pickable along its full height.
            ry = max(0.0, abs(d.y - ay - t*dy) - d.radius * max(0.0, d.stretch - 1))
            return math.hypot(px - ax - t*dx, ry) <= ERASER_RADIUS + d.radius

        self.dabs = [d for d in self.dabs if not hit(d)]
