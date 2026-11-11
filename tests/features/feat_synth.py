"""Synthetic hand generator for feature tests. Proves logic only, not real-camera accuracy.

Local hand frame (palm units, right hand): wrist at origin, fingers point to -y (image up),
thumb side is +x, palm faces the camera (-z). Curling moves fingertips toward the camera first.
"""
from __future__ import annotations

import math
from typing import Mapping, Optional, Sequence

from handcontrol.contracts import FrameSample, HandSample, Handedness, Landmark

FINGER_NAMES = ("thumb", "index", "middle", "ring", "little")
_FINGERS = (
    ((0.30, -0.92), (0.38, 0.24, 0.20)),
    ((0.08, -1.00), (0.42, 0.27, 0.21)),
    ((-0.13, -0.95), (0.39, 0.25, 0.20)),
    ((-0.32, -0.84), (0.30, 0.19, 0.18)),
)
_FLEX = (75.0, 100.0, 65.0)          # MCP, PIP, DIP flexion at curl 1.0 (degrees)
Vec3 = tuple[float, float, float]


def _curl_map(curls: Mapping[str, float] | Sequence[float] | float) -> dict[str, float]:
    if isinstance(curls, (int, float)):
        return {n: float(curls) for n in FINGER_NAMES}
    if isinstance(curls, Mapping):
        out = {n: 0.0 for n in FINGER_NAMES}
        out.update(curls)
        return out
    return dict(zip(FINGER_NAMES, curls))


def local_hand(curls: Mapping[str, float] | Sequence[float] | float = 0.0) -> list[Vec3]:
    c = _curl_map(curls)
    pts: list[Vec3] = [(0.0, 0.0, 0.0)] * 21
    # thumb: CMC base, abducts across the palm and flexes MCP/IP as curl grows
    ct = c["thumb"]
    cur = (0.20, -0.15, 0.0)
    pts[1] = cur
    phi = 55.0 - 45.0 * ct
    phis = (phi, phi - 50.0 * ct, phi - 110.0 * ct)
    tilts = (0.0, 15.0 * ct, 30.0 * ct)
    for k, length in enumerate((0.30, 0.25, 0.22)):
        p, t = math.radians(phis[k]), math.radians(tilts[k])
        d = (math.sin(p) * math.cos(t), -math.cos(p) * math.cos(t), -math.sin(t))
        cur = (cur[0] + length * d[0], cur[1] + length * d[1], cur[2] + length * d[2])
        pts[2 + k] = cur
    for i, ((mx, my), bones) in enumerate(_FINGERS):
        cf = c[FINGER_NAMES[i + 1]]
        start = 5 + 4 * i
        cur = (mx, my, 0.0)
        pts[start] = cur
        n = math.hypot(mx * 0.4, 1.0)
        dx, dy = mx * 0.4 / n, -1.0 / n
        acc = 0.0
        for k, length in enumerate(bones):
            acc += math.radians(_FLEX[k] * cf)
            d = (dx * math.cos(acc), dy * math.cos(acc), -math.sin(acc))
            cur = (cur[0] + length * d[0], cur[1] + length * d[1], cur[2] + length * d[2])
            pts[start + 1 + k] = cur
    return pts


def _rotate(p: Vec3, roll: float, yaw: float, pitch: float) -> Vec3:
    x, y, z = p
    a = math.radians(pitch)
    y, z = y * math.cos(a) - z * math.sin(a), y * math.sin(a) + z * math.cos(a)
    a = math.radians(yaw)
    x, z = x * math.cos(a) + z * math.sin(a), -x * math.sin(a) + z * math.cos(a)
    a = math.radians(roll)
    x, y = x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)
    return (x, y, z)


def make_hand(curls: Mapping[str, float] | Sequence[float] | float = 0.0, *, side: str = "right",
              roll: float = 0.0, yaw: float = 0.0, pitch: float = 0.0, scale: float = 100.0,
              center: tuple[float, float] = (320.0, 240.0), width: int = 640, height: int = 480,
              handedness: Optional[Handedness] = None, score: float = 0.95, depth: bool = True,
              world: bool = False) -> HandSample:
    """Build a 21-landmark HandSample. scale = wrist..middle-MCP length in pixels.
    center = palm center (mean of MCP 5, 9, 13, 17) in pixels. side='left' mirrors the hand."""
    mirror = -1.0 if side == "left" else 1.0
    pts = [_rotate((mirror * x, y, z), roll, yaw, pitch) for x, y, z in local_hand(curls)]
    pcx = sum(pts[i][0] for i in (5, 9, 13, 17)) / 4.0
    pcy = sum(pts[i][1] for i in (5, 9, 13, 17)) / 4.0
    lms = tuple(
        Landmark((center[0] + (x - pcx) * scale) / width,
                 (center[1] + (y - pcy) * scale) / height,
                 (z * scale) / width if depth else 0.0)
        for x, y, z in pts
    )
    wl = tuple(Landmark(x * 0.085, y * 0.085, z * 0.085) for x, y, z in pts) if world else None
    if handedness is None:
        handedness = Handedness.LEFT if side == "left" else Handedness.RIGHT
    return HandSample(handedness, score, lms, wl)


def make_frame(t_ms: float, hands: Sequence[HandSample] = (), width: int = 640, height: int = 480,
               latency_ms: float = 20.0) -> FrameSample:
    return FrameSample(t_ms, t_ms + latency_ms, width, height, tuple(hands))
