"""Pure camera-to-desktop mapping helpers (spec §6 "Pointer and display mapping").

Stdlib + contracts only. No OS calls: monitor geometry comes from a DisplayProvider.

Conventions:
- Rect right/bottom are exclusive (Win32 RECT); the last valid pixel is right-1 / bottom-1.
- Camera input is normalized [0,1] on the UNMIRRORED frame. With mirror=True the x axis is
  flipped first, so the calibration rectangle is expressed in the mirrored ("selfie") view.
- Output is physical virtual-desktop pixels, which may be negative.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from handcontrol.contracts import Monitor, Rect


@dataclass(frozen=True)
class CalibrationRect:
    """Usable camera region, normalized [0,1] in the (optionally mirrored) view."""

    left: float = 0.0
    top: float = 0.0
    right: float = 1.0
    bottom: float = 1.0

    def __post_init__(self) -> None:
        if not (self.right > self.left and self.bottom > self.top):
            raise ValueError(f"degenerate calibration rect: {self}")


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def bounding_rect(monitors: Sequence[Monitor]) -> Optional[Rect]:
    """Bounding rectangle of all monitor bounds, or None without monitors."""
    if not monitors:
        return None
    return Rect(
        left=min(m.bounds.left for m in monitors),
        top=min(m.bounds.top for m in monitors),
        right=max(m.bounds.right for m in monitors),
        bottom=max(m.bounds.bottom for m in monitors),
    )


def contains(rect: Rect, x: int, y: int) -> bool:
    return rect.left <= x < rect.right and rect.top <= y < rect.bottom


def clamp_to_rect(rect: Rect, x: float, y: float) -> tuple[int, int]:
    return (
        int(round(_clamp(x, rect.left, rect.right - 1))),
        int(round(_clamp(y, rect.top, rect.bottom - 1))),
    )


def nearest_monitor(x: float, y: float, monitors: Sequence[Monitor]) -> Optional[Monitor]:
    """Monitor containing (x, y), else the one whose bounds are closest."""
    best: Optional[Monitor] = None
    best_d = float("inf")
    for m in monitors:
        cx, cy = clamp_to_rect(m.bounds, x, y)
        d = (cx - x) ** 2 + (cy - y) ** 2
        if d < best_d:
            best, best_d = m, d
    return best


def project_to_monitors(x: float, y: float, monitors: Sequence[Monitor]) -> Optional[tuple[int, int]]:
    """Keep a point inside real monitor pixels; points in gaps go to the nearest valid point."""
    m = nearest_monitor(x, y, monitors)
    if m is None:
        return None
    return clamp_to_rect(m.bounds, x, y)


def normalize_camera_point(
    x_px: float,
    y_px: float,
    width: int,
    height: int,
    calibration: CalibrationRect = CalibrationRect(),
    mirror: bool = True,
) -> Optional[tuple[float, float]]:
    """Camera pixels -> (u, v) in [0,1] relative to the calibration rect (clamped)."""
    if width <= 0 or height <= 0:
        return None
    u = x_px / width
    v = y_px / height
    if mirror:
        u = 1.0 - u
    c = calibration
    u = (u - c.left) / (c.right - c.left)
    v = (v - c.top) / (c.bottom - c.top)
    return _clamp(u, 0.0, 1.0), _clamp(v, 0.0, 1.0)


def map_normalized(u: float, v: float, monitors: Sequence[Monitor]) -> Optional[tuple[int, int]]:
    """(u, v) in [0,1] -> bounding desktop rect -> nearest real monitor pixel."""
    box = bounding_rect(monitors)
    if box is None:
        return None
    u = _clamp(u, 0.0, 1.0)
    v = _clamp(v, 0.0, 1.0)
    x = box.left + u * (box.right - 1 - box.left)
    y = box.top + v * (box.bottom - 1 - box.top)
    return project_to_monitors(x, y, monitors)


def map_camera_point(
    x_px: float,
    y_px: float,
    width: int,
    height: int,
    monitors: Sequence[Monitor],
    calibration: CalibrationRect = CalibrationRect(),
    mirror: bool = True,
) -> Optional[tuple[int, int]]:
    uv = normalize_camera_point(x_px, y_px, width, height, calibration, mirror)
    if uv is None:
        return None
    return map_normalized(uv[0], uv[1], monitors)


def logical_to_physical(logical_px: float, dpi_scale: float) -> float:
    return logical_px * (dpi_scale if dpi_scale > 0 else 1.0)


def threshold_physical_px(logical_px: float, x: float, y: float, monitors: Sequence[Monitor]) -> float:
    """A logical-pixel threshold scaled by the DPI of the monitor at (x, y)."""
    m = nearest_monitor(x, y, monitors)
    return logical_to_physical(logical_px, m.dpi_scale if m else 1.0)
