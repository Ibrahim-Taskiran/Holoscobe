"""Rotating ink volume. Coordinates are camera-width units (y measured in the same units)."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass


WORK_DEPTH = 0.075
ERASER_RADIUS = 0.05
FRONT_DEPTH = -0.02      # ink behind this depth is the rear surface
SPIN_EASE_MS = 120.0
CLEAR_MS = 1750.0
SPACING = 0.005
MAX_DABS = 4000        # repaint budget: 18 camera widths of stroke, oldest ink goes first


def projected_y(y: float, depth: float) -> float:
    """A slightly elevated view reveals the rear arc of a level ring. The work plane maps 1:1."""
    return y - 0.24 * (depth - WORK_DEPTH)


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
        self.spin_target = 0.0   # rad/ms; the real speed eases towards it
        self.spin_speed = 0.0
        self._spin_t: float | None = None
        self.revision = 0        # bumped whenever existing ink goes away (appending does not count)
        self.clear_start: float | None = None
        self._rng = random.Random(seed)
        self._last: tuple[float, float, float] | None = None
        self._distance = 0.0
        self.erase_front: bool | None = None      # surface of the running eraser stroke

    def lift(self):
        self._last = None
        self._distance = 0.0
        self.erase_front = None

    def clear(self, now: float):
        self.lift()
        if self.dabs and self.clear_start is None:
            self.clear_start = now

    def advance(self, now: float):
        """Called with capture times and with repaint times; whichever is newer moves the scene."""
        dt = 0.0 if self._spin_t is None else min(100.0, now - self._spin_t)
        if dt >= 0:
            self._spin_t = now
        if dt > 0 and (self.spin_target or self.spin_speed):
            self.spin_speed += (self.spin_target - self.spin_speed) * (1 - math.exp(-dt/SPIN_EASE_MS))
            if not self.spin_target and abs(self.spin_speed) < 4e-5:
                self.spin_speed = 0.0
            self.angle = (self.angle + self.spin_speed*dt) % math.tau
        if self.clear_start is not None and now - self.clear_start >= CLEAR_MS:
            self.dabs.clear()
            self.revision += 1
            self.clear_start = None

    def _stamp(self, x, y, z, radius, stretch, now):
        self.dabs.append(Dab(x, y, z, radius, stretch, now, self._rng.random()))
        if len(self.dabs) > MAX_DABS:
            del self.dabs[:MAX_DABS // 20]
            self.revision += 1

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
        """Sweep a local eraser. The first ink it meets picks the surface (front wins) for the whole stroke,
        so holding it cannot tunnel into the back; ink that is only in the back needs a new stroke."""
        self._last = None
        if self.clear_start is not None:
            return
        c, s = math.cos(self.angle), math.sin(self.angle)
        ax, ay = previous or (x, y)
        dx, dy = x - ax, y - ay
        length2 = dx*dx + dy*dy

        hits: dict[bool, set[int]] = {True: set(), False: set()}
        for i, d in enumerate(self.dabs):
            px, depth = turn(d.x, d.z, c, s)
            py = projected_y(d.y, depth)
            t = min(1.0, max(0.0, ((px-ax)*dx + (py-ay)*dy)/length2)) if length2 else 0.0
            # The elongated body of a drip is pickable along its full height.
            ry = max(0.0, abs(py - ay - t*dy) - d.radius * max(0.0, d.stretch - 1))
            if math.hypot(px - ax - t*dx, ry) <= ERASER_RADIUS + d.radius:
                hits[depth >= FRONT_DEPTH].add(i)
        if self.erase_front is None and (hits[True] or hits[False]):
            self.erase_front = bool(hits[True])
        gone = hits[self.erase_front] if self.erase_front is not None else ()
        if gone:
            self.dabs = [d for i, d in enumerate(self.dabs) if i not in gone]
            self.revision += 1
