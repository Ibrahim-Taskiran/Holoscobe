"""Physical (native virtual-desktop px) <-> Qt logical global coordinate helpers.

Qt 6 on Windows keeps each screen's origin in native pixels and scales only the size:
logical = origin + (physical - origin) / devicePixelRatio.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QGuiApplication, QScreen


def _native_rect(screen: QScreen) -> QRect:
    geo = screen.geometry()
    dpr = max(0.01, float(screen.devicePixelRatio()))
    return QRect(geo.x(), geo.y(), round(geo.width() * dpr), round(geo.height() * dpr))


def screen_at_physical(x: int, y: int) -> Optional[QScreen]:
    for screen in QGuiApplication.screens():
        if _native_rect(screen).contains(int(x), int(y)):
            return screen
    return QGuiApplication.primaryScreen()


def physical_to_logical(x: int, y: int) -> QPoint:
    """Map a physical virtual-desktop point to a Qt logical global point."""
    screen = screen_at_physical(x, y)
    if screen is None:
        return QPoint(int(x), int(y))
    origin = screen.geometry().topLeft()
    dpr = max(0.01, float(screen.devicePixelRatio()))
    return QPoint(round(origin.x() + (x - origin.x()) / dpr), round(origin.y() + (y - origin.y()) / dpr))


def logical_to_physical(point: QPoint) -> tuple[int, int]:
    """Inverse of physical_to_logical for a Qt logical global point."""
    screen = QGuiApplication.screenAt(point) or QGuiApplication.primaryScreen()
    if screen is None:
        return point.x(), point.y()
    origin = screen.geometry().topLeft()
    dpr = max(0.01, float(screen.devicePixelRatio()))
    return (round(origin.x() + (point.x() - origin.x()) * dpr),
            round(origin.y() + (point.y() - origin.y()) * dpr))
