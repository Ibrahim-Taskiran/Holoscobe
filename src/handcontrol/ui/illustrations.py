"""Painted pictures for the tutorial and the calibration summary (vector, no image files)."""
from __future__ import annotations

import math
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QSizePolicy, QWidget

from handcontrol.contracts import Mode
from handcontrol.ui import icons, theme
from handcontrol.ui.preview import paint_viewfinder
from handcontrol.ui.painted import PaintedWidget

# An open right hand in a unit square (MediaPipe landmark order).
OPEN_HAND: tuple[tuple[float, float], ...] = (
    (.50, .97), (.35, .86), (.24, .73), (.15, .61), (.08, .50), (.37, .53), (.33, .35), (.31, .23), (.29, .12),
    (.50, .50), (.50, .29), (.50, .16), (.50, .04), (.62, .53), (.66, .34), (.68, .22), (.70, .12),
    (.73, .60), (.81, .46), (.86, .37), (.90, .28),
)
BONES = ((0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (5, 9), (9, 10), (10, 11), (11, 12), (9, 13),
         (13, 14), (14, 15), (15, 16), (13, 17), (17, 18), (18, 19), (19, 20), (17, 0))


def paint_hand(p: QPainter, rect: QRectF, color: str = theme.HAND_RIGHT, mirror: bool = False) -> None:
    pts = [QPointF(rect.left() + (1 - x if mirror else x) * rect.width(), rect.top() + y * rect.height())
           for x, y in OPEN_HAND]
    k = rect.width() / 160.0
    p.setPen(theme.round_pen(theme.color(color, 0.9), 3.4 * k))
    for a, b in BONES:
        p.drawLine(pts[a], pts[b])
    p.setPen(QPen(QColor(theme.SURFACE), 1.6 * k))
    p.setBrush(QColor(color))
    for i, pt in enumerate(pts):
        r = (6.4 if i in (0, 4, 8, 12, 16, 20) else 4.6) * k
        p.drawEllipse(pt, r, r)


class Illustration(PaintedWidget):
    """Card with one of the painted scenes: "welcome", "modes" or "done"."""

    def __init__(self, scene: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._scene = scene
        self.setMinimumSize(280, 240)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

    def _paint(self, p: QPainter, rect: QRectF) -> None:
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        clip = QPainterPath()
        clip.addRoundedRect(r, theme.RADIUS_XL, theme.RADIUS_XL)
        p.fillPath(clip, QColor(theme.SURFACE))
        glow = QRadialGradient(QPointF(r.center().x(), r.center().y() + r.height() * 0.1), r.width() * 0.75)
        glow.setColorAt(0.0, theme.color(theme.ACCENT, 0.20))
        glow.setColorAt(1.0, theme.color(theme.ACCENT, 0.0))
        p.fillPath(clip, glow)
        p.setPen(QPen(QColor(theme.HAIRLINE), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(clip)
        p.setClipPath(clip)
        {"welcome": self._welcome, "modes": self._modes, "done": self._done}[self._scene](p, r)

    def _welcome(self, p: QPainter, r: QRectF) -> None:
        s = min(r.width(), r.height() * 0.84)
        c = QPointF(r.center().x(), r.center().y() - r.height() * 0.05)
        frame = QRectF(c.x() - s * 0.37, c.y() - s * 0.40, s * 0.74, s * 0.74)
        paint_viewfinder(p, frame, theme.color(theme.TEXT, 0.55), 2.6, 22.0, corners=3)      # the cat sits on the fourth
        paint_hand(p, frame.adjusted(s * 0.10, s * 0.06, -s * 0.10, -s * 0.10))
        cat = s * 0.46
        box = QRectF(r.right() - cat - s * 0.05, r.bottom() - cat - s * 0.03, cat, cat)
        icons.paint_cat(p, box)

    def _modes(self, p: QPainter, r: QRectF) -> None:
        c = r.center()
        outer = min(r.width(), r.height()) * 0.41
        inner = outer * 0.36
        modes = (Mode.POINTER, Mode.SCROLL, Mode.DRAWING, Mode.INSTRUMENT, Mode.COMMANDS, None)
        ring = QPainterPath()
        ring.addEllipse(c, outer, outer)
        ring.addEllipse(c, inner, inner)
        p.setPen(QPen(theme.color(theme.WHITE, 0.14), 1))
        p.setBrush(theme.color(theme.BG, 0.92))
        p.drawPath(ring)
        step = 360.0 / len(modes)
        for i, mode in enumerate(modes):
            a = math.radians(i * step)
            hot = mode is Mode.SCROLL
            if hot:
                out = outer + 8.0
                start, span = 90.0 - (i - 0.5) * step - 1.2, -(step - 2.4)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(theme.ACCENT))
                p.drawPath(theme.ring_slice(c, inner, out, start, span))
            mid = (inner + outer) / 2
            at = QPointF(c.x() + mid * math.sin(a), c.y() - mid * math.cos(a))
            icons.paint(p, icons.MODE_ICONS[mode] if mode else "more", QRectF(at.x() - 13, at.y() - 13, 26, 26),
                        theme.ON_ACCENT if hot else theme.TEXT)
        p.setPen(QColor(theme.TEXT))
        p.setFont(theme.bold(26, True))
        p.drawText(QRectF(c.x() - inner, c.y() - inner, 2 * inner, 2 * inner), int(Qt.AlignmentFlag.AlignCenter), "V")
        theme.paint_ring(p, c, inner - 7, 0.7, theme.ACCENT, 3.0)

    def _done(self, p: QPainter, r: QRectF) -> None:
        s = min(r.width(), r.height())
        c = r.center()
        p.setPen(Qt.PenStyle.NoPen)
        tones = (theme.ACCENT, theme.SUCCESS, theme.WARNING, theme.CREAM)
        for i in range(18):                                       # confetti on a loose ring
            a = i * 2.399963
            d = s * (0.33 + 0.028 * (i % 5))
            at = QPointF(c.x() + d * math.cos(a), c.y() + d * math.sin(a) * 0.98)
            p.setBrush(QColor(tones[i % 4]))
            p.save()
            p.translate(at)
            p.rotate(i * 47)
            p.drawRoundedRect(QRectF(-4, -2, 8, 4) if i % 2 else QRectF(-3, -3, 6, 6), 2 if i % 2 else 3, 2 if i % 2 else 3)
            p.restore()
        cat = s * 0.48
        icons.paint_cat(p, QRectF(c.x() - cat / 2, c.y() - cat / 2 - s * 0.01, cat, cat), happy=True)
        badge = QPointF(c.x() + cat * 0.40, c.y() + cat * 0.36)
        p.setPen(QPen(QColor(theme.SURFACE), 5))
        p.setBrush(QColor(theme.SUCCESS))
        p.drawEllipse(badge, s * 0.075, s * 0.075)
        k = s * 0.05
        icons.paint(p, "check", QRectF(badge.x() - k, badge.y() - k, 2 * k, 2 * k), theme.ON_ACCENT, 2.8)
