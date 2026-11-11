"""Pure physical-pixel geometry. Rectangles use exclusive right/bottom edges."""
from __future__ import annotations

import math
from collections.abc import Sequence

from ..contracts import Monitor, Rect


def size(rect: Rect) -> tuple[int, int]:
    return rect.right - rect.left, rect.bottom - rect.top


def valid_rect(rect: Rect) -> bool:
    return rect.right > rect.left and rect.bottom > rect.top


def desktop_bounds(monitors: Sequence[Monitor]) -> Rect:
    if not monitors or any(not valid_rect(m.bounds) for m in monitors):
        raise ValueError("At least one nonempty monitor is required")
    return Rect(min(m.bounds.left for m in monitors), min(m.bounds.top for m in monitors),
                max(m.bounds.right for m in monitors), max(m.bounds.bottom for m in monitors))


def nearest_point(x: int, y: int, rectangles: Sequence[Rect]) -> tuple[int, int]:
    candidates = [(max(r.left, min(x, r.right - 1)), max(r.top, min(y, r.bottom - 1)))
                  for r in rectangles if valid_rect(r)]
    if not candidates:
        raise ValueError("No usable rectangles")
    return min(candidates, key=lambda p: (p[0] - x) ** 2 + (p[1] - y) ** 2)


def normalize_pointer(x: int, y: int, monitors: Sequence[Monitor]) -> tuple[int, int]:
    """Project gaps to a real monitor and normalize the whole virtual desktop."""
    bounds = desktop_bounds(monitors)
    x, y = nearest_point(x, y, [m.bounds for m in monitors])
    width, height = size(bounds)
    return (round((x - bounds.left) * 65535 / max(1, width - 1)),
            round((y - bounds.top) * 65535 / max(1, height - 1)))


def fit_rect(rect: Rect, area: Rect) -> Rect:
    if not valid_rect(rect) or not valid_rect(area):
        raise ValueError("Nonempty rectangles are required")
    width, height = (min(a, b) for a, b in zip(size(rect), size(area)))
    x = max(area.left, min(rect.left, area.right - width))
    y = max(area.top, min(rect.top, area.bottom - height))
    return Rect(x, y, x + width, y + height)


def proportional_placement(rect: Rect, source: Monitor, destination: Monitor) -> Rect:
    """Preserve logical size and relative position in the available travel range."""
    if not valid_rect(rect) or not valid_rect(source.work_area) or not valid_rect(destination.work_area):
        raise ValueError("Nonempty rectangles are required")
    if any(not math.isfinite(m.dpi_scale) or m.dpi_scale <= 0 for m in (source, destination)):
        raise ValueError("DPI scales must be positive and finite")
    sw, sh = size(source.work_area)
    dw, dh = size(destination.work_area)
    rw, rh = size(rect)
    ratio = destination.dpi_scale / source.dpi_scale
    width, height = min(dw, max(1, round(rw * ratio))), min(dh, max(1, round(rh * ratio)))
    rx = max(0.0, min(1.0, (rect.left - source.work_area.left) / max(1, sw - rw)))
    ry = max(0.0, min(1.0, (rect.top - source.work_area.top) / max(1, sh - rh)))
    x, y = destination.work_area.left + round(rx * (dw - width)), destination.work_area.top + round(ry * (dh - height))
    return Rect(x, y, x + width, y + height)


def monitor_for_rect(rect: Rect, monitors: Sequence[Monitor]) -> Monitor:
    if not monitors:
        raise ValueError("No monitors")
    def score(m: Monitor) -> tuple[int, float]:
        r = m.work_area
        overlap = max(0, min(rect.right, r.right) - max(rect.left, r.left)) * max(0, min(rect.bottom, r.bottom) - max(rect.top, r.top))
        distance = (rect.left + rect.right - r.left - r.right) ** 2 + (rect.top + rect.bottom - r.top - r.bottom) ** 2
        return overlap, -distance
    return max(monitors, key=score)


def ensure_title_visible(rect: Rect, areas: Sequence[Rect], title_height: int = 32,
                         visible_width: int = 120) -> Rect:
    """Translate only, retaining at least a usable title strip in one work area."""
    width, height = size(rect)
    if width <= 0 or height <= 0 or title_height <= 0 or visible_width <= 0:
        raise ValueError("Invalid window or title dimensions")
    candidates = []
    for area in areas:
        if not valid_rect(area):
            continue
        strip = min(visible_width, width, area.right - area.left)
        x = max(area.left + strip - width, min(rect.left, area.right - strip))
        y = max(area.top, min(rect.top, area.bottom - min(title_height, height, area.bottom - area.top)))
        candidates.append(Rect(x, y, x + width, y + height))
    if not candidates:
        raise ValueError("No work areas")
    return min(candidates, key=lambda r: (r.left - rect.left) ** 2 + (r.top - rect.top) ** 2)
