"""Little music notes that rise from behind the cat while the instrument is on (GUI thread only)."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen

COLORS = tuple(QColor(*c) for c in ((255, 190, 112), (255, 241, 216), (246, 148, 132), (148, 214, 196)))
OUTLINE = QColor(34, 28, 30, 170)            # keeps the notes readable on a bright desktop
EVERY_S = (0.45, 0.85)                       # the quiet trickle
PLUCK_GAP_S = 0.05                           # a strummed chord gives a few notes, not six at once
MOST = 24
FADE_IN, FADE_OUT = 0.12, 0.45               # parts of a note's life


def _part(*, ellipse: Optional[QRectF] = None, polygon: tuple = ()) -> QPainterPath:
    path = QPainterPath()
    if ellipse is not None:
        path.addEllipse(ellipse)
    if polygon:
        path.addPolygon([QPointF(x, y) for x, y in polygon])
        path.closeSubpath()
    return path


def _stem(x: float) -> QPainterPath:
    """Note head at x with its stem."""
    head = _part(ellipse=QRectF(x - 0.22, -0.16, 0.44, 0.32))
    return head.united(_part(polygon=((x + 0.12, 0.0), (x + 0.12, -0.86), (x + 0.22, -0.86), (x + 0.22, 0.0))))


def _glyphs() -> tuple[QPainterPath, ...]:
    """Eighth note, beamed pair, quarter note: about one unit tall, y downwards."""
    flag = QPainterPath(QPointF(0.14, -0.86))
    flag.cubicTo(0.24, -0.58, 0.62, -0.54, 0.46, -0.18)
    flag.cubicTo(0.46, -0.40, 0.30, -0.46, 0.14, -0.50)
    flag.closeSubpath()
    beam = _part(polygon=((-0.18, -0.86), (-0.18, -0.64), (0.52, -0.64), (0.52, -0.86)))
    return _stem(0.0).united(flag), _stem(-0.30).united(_stem(0.30)).united(beam), _stem(0.0)


@dataclass(frozen=True)
class Note:
    born: float
    life: float
    side: int                                # -1 left, 1 right of the cat
    x: float                                 # start, in window sizes
    y: float
    out: float                               # sideways way over the whole life
    rise: float
    phase: float
    size: float                              # pixels of a 342 px high window
    glyph: int
    color: int

    def at(self, now: float) -> tuple[float, float, float, float]:
        """x, y (window sizes), opacity, tilt (degrees)."""
        k = min(1.0, max(0.0, (now - self.born) / self.life))
        sway = math.sin(self.phase + k * 7.0)
        fade = min(1.0, k / FADE_IN, (1.0 - k) / FADE_OUT)
        return (self.x + self.side * self.out * math.sqrt(k) + 0.012 * sway, self.y - self.rise * k, max(0.0, fade),
                10.0 * sway)


class NoteCloud:
    def __init__(self, rng: Optional[random.Random] = None) -> None:
        self._rng = rng or random.Random()
        self._glyphs = _glyphs()
        self.notes: list[Note] = []
        self.playing = False
        self._next = 0.0
        self._last_pluck = -1e9
        self._side = 1

    def set_playing(self, on: bool) -> None:
        """While on, notes keep coming by themselves. Off lets the visible ones finish."""
        self.playing = on

    def pluck(self, now: float) -> None:
        """A string was really struck."""
        if self.playing and now - self._last_pluck >= PLUCK_GAP_S:
            self._last_pluck = now
            self._spawn(now)

    def clear(self) -> None:
        self.notes.clear()

    def step(self, now: float) -> bool:
        """Advance; True while something has to be painted."""
        self.notes = [n for n in self.notes if now - n.born < n.life]
        if self.playing and now >= self._next:
            self._next = now + self._rng.uniform(*EVERY_S)
            self._spawn(now)
        return bool(self.notes)

    def _spawn(self, now: float) -> None:
        if len(self.notes) >= MOST:
            return
        r, self._side = self._rng, -self._side
        self.notes.append(Note(now, r.uniform(1.8, 2.8), self._side, 0.5 + self._side * r.uniform(0.15, 0.22),
                               r.uniform(0.48, 0.78), r.uniform(0.10, 0.22), r.uniform(0.22, 0.36),
                               r.uniform(0.0, math.tau), r.uniform(19.0, 28.0), r.randrange(len(self._glyphs)),
                               r.randrange(len(COLORS))))

    def paint(self, p: QPainter, rect: QRectF, now: float, opacity: float = 1.0) -> None:
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for n in self.notes:
            x, y, alpha, tilt = n.at(now)
            p.save()
            p.setOpacity(alpha * opacity)
            p.translate(QPointF(rect.left() + x * rect.width(), rect.top() + y * rect.height()))
            p.rotate(tilt)
            size = n.size * rect.height() / 342.0
            p.scale(size, size)
            p.setPen(QPen(OUTLINE, 0.05))
            p.setBrush(COLORS[n.color])
            p.drawPath(self._glyphs[n.glyph])
            p.restore()


__all__ = ["Note", "NoteCloud"]
