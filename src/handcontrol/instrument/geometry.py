"""2D vector helpers for the instrument engine. Stdlib only, pure, safe for zero-length segments.

Points are (x, y) tuples in camera pixels (image y grows downward).
"""
from __future__ import annotations

import math
from typing import Optional

Vec = tuple[float, float]

EPS = 1e-9


def add(a: Vec, b: Vec) -> Vec:
    return (a[0] + b[0], a[1] + b[1])


def sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1])


def scale(a: Vec, k: float) -> Vec:
    return (a[0] * k, a[1] * k)


def dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1]


def cross(a: Vec, b: Vec) -> float:
    """z component of the 3D cross product (a.x*b.y - a.y*b.x)."""
    return a[0] * b[1] - a[1] * b[0]


def length(a: Vec) -> float:
    return math.hypot(a[0], a[1])


def dist(a: Vec, b: Vec) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def lerp(a: Vec, b: Vec, t: float) -> Vec:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def normalize(a: Vec) -> Vec:
    n = length(a)
    if n < EPS:
        return (0.0, 0.0)
    return (a[0] / n, a[1] / n)


def normal(a: Vec, b: Vec) -> Vec:
    """Unit normal of the directed segment a->b, rotated so that cross(b-a, p-a) > 0 means
    dot(p-a, normal) > 0. (0, 0) for a zero-length segment."""
    e = normalize(sub(b, a))
    return (-e[1], e[0])


def is_finite(p: Vec) -> bool:
    return math.isfinite(p[0]) and math.isfinite(p[1])


def signed_distance(p: Vec, a: Vec, b: Vec) -> float:
    """Signed perpendicular distance of p to the infinite line a->b (positive on the
    cross(b-a, p-a) > 0 side). 0.0 for a zero-length segment."""
    e = sub(b, a)
    n = length(e)
    if n < EPS:
        return 0.0
    return cross(e, sub(p, a)) / n


def project_param(p: Vec, a: Vec, b: Vec) -> float:
    """Parameter u of the projection of p onto a->b (0 at a, 1 at b), unclamped.
    0.0 for a zero-length segment."""
    e = sub(b, a)
    n2 = dot(e, e)
    if n2 < EPS:
        return 0.0
    return dot(sub(p, a), e) / n2


def point_segment_distance(p: Vec, a: Vec, b: Vec) -> float:
    u = min(1.0, max(0.0, project_param(p, a, b)))
    return dist(p, lerp(a, b, u))


def segment_intersection(p0: Vec, p1: Vec, q0: Vec, q1: Vec) -> Optional[tuple[float, float]]:
    """Intersection of segments p0->p1 and q0->q1 as (t, u): point = lerp(p0,p1,t) = lerp(q0,q1,u),
    both in [0, 1]. None when they do not intersect, are parallel/collinear or degenerate."""
    r = sub(p1, p0)
    s = sub(q1, q0)
    den = cross(r, s)
    if abs(den) < EPS:
        return None
    qp = sub(q0, p0)
    t = cross(qp, s) / den
    u = cross(qp, r) / den
    if -EPS <= t <= 1.0 + EPS and -EPS <= u <= 1.0 + EPS:
        return (min(1.0, max(0.0, t)), min(1.0, max(0.0, u)))
    return None


Rect = tuple[float, float, float, float]
FIXED_MIN_W = 0.10      # smallest string area, fraction of the frame width
FIXED_MIN_H = 0.08      # ... and of the frame height


def normalize_fixed_rect(r: object, default: Rect = (0.25, 0.35, 0.75, 0.65)) -> Rect:
    """Normalized (x0, y0, x1, y1): sorted, inside [0, 1], at least FIXED_MIN_W x FIXED_MIN_H.
    Anything that is not 4 finite numbers gives `default`. A too small area grows around its centre."""
    try:
        vals = [float(v) for v in r]  # type: ignore[union-attr]
    except (TypeError, ValueError):
        return default
    if len(vals) != 4 or not all(math.isfinite(v) for v in vals):
        return default
    x0, x1 = sorted((min(1.0, max(0.0, vals[0])), min(1.0, max(0.0, vals[2]))))
    y0, y1 = sorted((min(1.0, max(0.0, vals[1])), min(1.0, max(0.0, vals[3]))))

    def grow(lo: float, hi: float, size: float) -> tuple[float, float]:
        if hi - lo >= size:
            return lo, hi
        c = min(1.0 - size / 2.0, max(size / 2.0, (lo + hi) / 2.0))
        return c - size / 2.0, c + size / 2.0

    x0, x1 = grow(x0, x1, FIXED_MIN_W)
    y0, y1 = grow(y0, y1, FIXED_MIN_H)
    return (round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4))


__all__ = [
    "EPS", "FIXED_MIN_H", "FIXED_MIN_W", "Rect", "normalize_fixed_rect", "Vec", "add", "cross", "dist", "dot", "is_finite", "length", "lerp", "normal", "normalize",
    "point_segment_distance", "project_param", "scale", "segment_intersection", "signed_distance", "sub",
]
