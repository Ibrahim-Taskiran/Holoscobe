"""One stroke icon set on a 24 x 24 grid (1.8 px round strokes), drawn with QPainterPath: no image files, no QtSvg.

Each icon is a list of parts: absolute path data ("M L H V C Q Z"), ("c", cx, cy, r) circle, ("r", x, y, w, h, radius)
rounded rectangle, ("a", cx, cy, r, start, span) arc in degrees. A part starting with "fill" is filled, not stroked.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from handcontrol.contracts import Mode
from handcontrol.ui import theme

GRID = 24.0
STROKE = 1.8

CAT_HEAD = ("M4.6 10.6 L4.4 4.2 C4.4 3.5 5.2 3.2 5.7 3.6 L9.1 6.4 C11 5.9 13 5.9 14.9 6.4 L18.3 3.6 "
            "C18.8 3.2 19.6 3.5 19.6 4.2 L19.4 10.6 C20.2 11.8 20.5 13 20.5 14.2 C20.5 18 16.7 20.6 12 20.6 "
            "C7.3 20.6 3.5 18 3.5 14.2 C3.5 13 3.8 11.8 4.6 10.6 Z")
CAT_FACE = ("M10.8 15.4 L12 16.4 L13.2 15.4", "M12 16.4 L12 17.4")

ICONS: dict[str, tuple[Any, ...]] = {
    # modes
    "pointer": ("M6 3.6 L18.8 10.9 L12.9 12.6 L10 18.4 Z", "M13.6 13.4 L18 19.4"),
    "scroll": (("r", 7, 2.8, 10, 18.4, 5), "M12 6.6 L12 10.4"),
    "zoom": (("c", 10.6, 10.6, 6.8), "M15.6 15.6 L20.6 20.6", "M7.8 10.6 L13.4 10.6", "M10.6 7.8 L10.6 13.4"),
    "volume": ("M3.6 9.4 L3.6 14.6 L7 14.6 L11.6 18.6 L11.6 5.4 L7 9.4 Z", ("a", 12.4, 12, 4, -48, 96),
               ("a", 12.4, 12, 7.6, -48, 96)),
    "windows": (("r", 3.2, 4.4, 17.6, 15.2, 2.6), "M3.4 9 L20.6 9", "M6.4 6.7 L6.5 6.7"),
    "commands": ("M4 8 L19.4 8", "M15.6 4.2 L19.6 8 L15.6 11.8", "M20 16 L4.6 16", "M8.4 12.2 L4.4 16 L8.4 19.8"),
    "instrument": ("M9.2 17.6 L9.2 5.4 L19.6 3.4 L19.6 15.4", ("c", 6.6, 17.6, 2.6), ("c", 17, 15.4, 2.6),
                   "M9.2 9.4 L19.6 7.4"),
    "drawing": ("M4 20 L5.2 15.4 L16.2 4.4 C17 3.6 18.4 3.6 19.2 4.4 L19.6 4.8 C20.4 5.6 20.4 7 19.6 7.8 "
                "L8.6 18.8 Z", "M14 6.8 L17.2 10"),
    "more": (("fill", ("c", 5.4, 12, 1.5)), ("fill", ("c", 12, 12, 1.5)), ("fill", ("c", 18.6, 12, 1.5))),
    # controls
    "play": (("fill", "M8 5.4 C8 4.5 9 4 9.7 4.5 L19 11.1 C19.6 11.5 19.6 12.5 19 12.9 L9.7 19.5 C9 20 8 19.5 8 18.6 Z"),),
    "pause": (("fill", ("r", 6.4, 4.8, 4, 14.4, 1.4)), ("fill", ("r", 13.6, 4.8, 4, 14.4, 1.4))),
    "cat": (CAT_HEAD, *CAT_FACE, ("fill", ("c", 8.7, 12.6, 1.15)), ("fill", ("c", 15.3, 12.6, 1.15))),
    "settings": ("M4 7 L12.4 7", "M18 7 L20 7", ("c", 15.2, 7, 2.6), "M4 17 L6 17", "M11.6 17 L20 17",
                 ("c", 8.8, 17, 2.6)),
    "details": ("M3.4 12.4 L7 12.4 L9.6 5.4 L14 18.8 L16.6 12.4 L20.6 12.4",),
    "trash": ("M4.4 6.6 L19.6 6.6", "M9.4 6.4 L9.4 4 L14.6 4 L14.6 6.4", "M6.4 6.8 L7.2 20 L16.8 20 L17.6 6.8",
              "M10.2 10.6 L10.2 16.4", "M13.8 10.6 L13.8 16.4"),
    "undo": ("M8.4 4.6 L4 9 L8.4 13.4", "M4.4 9 L14.6 9 C17.6 9 20 11.4 20 14.4 C20 17.4 17.6 19.8 14.6 19.8 L9 19.8"),
    "back": ("M11 5.4 L4.4 12 L11 18.6", "M4.8 12 L19.6 12"),
    "camera": (("r", 2.8, 6, 12.8, 12, 2.6), "M15.8 10.8 L21.2 7.4 L21.2 16.6 L15.8 13.2"),
    "camera_off": ("M5.2 6.2 C3.8 6.4 2.8 7.4 2.8 8.8 L2.8 15.4 C2.8 16.8 4 18 5.4 18 L13 18 C14.4 18 15.6 16.8 15.6 15.4",
                   "M9.4 6 L13 6 C14.4 6 15.6 7.2 15.6 8.6 L15.6 10.8 L21.2 7.4 L21.2 16.6", "M3.4 3.4 L20.6 20.6"),
    "hand": ("M8.2 12.6 L8.2 5.8 C8.2 4.8 9 4.2 9.8 4.2 C10.6 4.2 11.3 4.8 11.3 5.8 L11.3 10.6", "M11.3 10.4 L11.3 4.4 "
             "C11.3 3.4 12 2.8 12.8 2.8 C13.6 2.8 14.4 3.4 14.4 4.4 L14.4 10.6", "M14.4 10.6 L14.4 6.2 C14.4 5.2 15.1 4.6 "
             "15.9 4.6 C16.7 4.6 17.4 5.2 17.4 6.2 L17.4 11.4", "M17.4 11.4 L17.4 9 C17.4 8 18 7.4 18.8 7.4 C19.6 7.4 "
             "20.3 8 20.3 9 L20.3 14.2 C20.3 18.2 17.8 21.2 13.8 21.2 C10.8 21.2 9.2 19.8 7.8 17.6 L4.4 12.8 C3.9 12 4.1 "
             "11.1 4.8 10.6 C5.5 10.1 6.4 10.3 7 11 L8.2 12.6"),
    "warning": ("M12 4 L21 19.4 L3 19.4 Z", "M12 10 L12 13.8", ("fill", ("c", 12, 16.6, 1.0))),
    "info": (("c", 12, 12, 8.8), "M12 11.2 L12 16.2", ("fill", ("c", 12, 8, 1.1))),
    "check": ("M5 12.6 L9.8 17.4 L19.2 7",),
    "close": ("M6 6 L18 18", "M18 6 L6 18"),
    "minimize": ("M5.4 12 L18.6 12",),
    "maximize": (("r", 5, 5, 14, 14, 2.4),),
    "monitor": (("r", 2.8, 4, 18.4, 12.6, 2.4), "M12 16.8 L12 20.2", "M8 20.2 L16 20.2"),
    "move_monitor": (("r", 2.6, 7, 10.4, 10, 2), "M16 12 L21.4 12", "M18.8 9 L21.6 12 L18.8 15"),
    "target": (("c", 12, 12, 8.2), ("c", 12, 12, 3.4), "M12 1.8 L12 5", "M12 19 L12 22.2", "M1.8 12 L5 12",
               "M19 12 L22.2 12"),
    "guide": ("M12 6.4 C10 4.8 7 4.4 3.4 4.8 L3.4 18.4 C7 18 10 18.4 12 20 C14 18.4 17 18 20.6 18.4 L20.6 4.8 "
              "C17 4.4 14 4.8 12 6.4 Z", "M12 6.6 L12 19.6"),
    "learn": ("M2.6 9.2 L12 4.6 L21.4 9.2 L12 13.8 Z", "M6.4 11.2 L6.4 16 C9.6 18.8 14.4 18.8 17.6 16 L17.6 11.2",
              "M21.4 9.4 L21.4 14.6"),
    "power": ("M12 3 L12 11.4", ("a", 12, 12.8, 8, -56, -248)),
    "chevron_down": ("M7 10 L12 15 L17 10",),
    "chevron_up": ("M7 14.4 L12 9.4 L17 14.4",),
    "chevron_right": ("M10 7 L15 12 L10 17",),
    "light": (("c", 12, 12, 4), "M12 2.6 L12 4.8", "M12 19.2 L12 21.4", "M2.6 12 L4.8 12", "M19.2 12 L21.4 12",
              "M5.4 5.4 L6.9 6.9", "M17.1 17.1 L18.6 18.6", "M18.6 5.4 L17.1 6.9", "M6.9 17.1 L5.4 18.6"),
    "distance": ("M3.4 12 L20.6 12", "M7 8.4 L3.4 12 L7 15.6", "M17 8.4 L20.6 12 L17 15.6"),
    "elbow": ("M4 19.6 L20 19.6", "M6.4 19.2 L10.4 10.8 L17.4 6.2", ("c", 18.6, 5.2, 1.9)),
    "shield": ("M12 3 L19.6 5.8 L19.6 11.4 C19.6 16 16.6 19.4 12 21 C7.4 19.4 4.4 16 4.4 11.4 L4.4 5.8 Z",
               "M8.8 12 L11.2 14.4 L15.4 9.6"),
    "clap": ("M3.4 8.4 L9 13.4 L3.4 18.4", "M20.6 8.4 L15 13.4 L20.6 18.4", "M12 3 L12 6.6", "M7.6 3.8 L9.2 6.8",
             "M16.4 3.8 L14.8 6.8"),
    "timer": (("c", 12, 13.2, 7.6), "M12 9 L12 13.4 L15 15", "M9.6 2.8 L14.4 2.8"),
    "sound_test": ("M3.6 9.4 L3.6 14.6 L7 14.6 L11.6 18.6 L11.6 5.4 L7 9.4 Z", "M15.4 9 L20.2 12 L15.4 15 Z"),
    "export": ("M12 14.8 L12 3.8", "M7.8 7.8 L12 3.6 L16.2 7.8", "M4 14.6 L4 19.6 L20 19.6 L20 14.6"),
    "import": ("M12 3.6 L12 14.4", "M7.8 10.4 L12 14.6 L16.2 10.4", "M4 14.6 L4 19.6 L20 19.6 L20 14.6"),
    "report": ("M6 3.4 L14 3.4 L18.6 8 L18.6 20.6 L6 20.6 Z", "M13.8 3.6 L13.8 8.2 L18.4 8.2", "M9 12.4 L15.4 12.4",
               "M9 16.2 L13.4 16.2"),
    "advanced": ("M9 3.4 L9 8.6 L4.4 17.6 C3.8 19 4.6 20.4 6.2 20.4 L17.8 20.4 C19.4 20.4 20.2 19 19.6 17.6 L15 8.6 "
                 "L15 3.4", "M7.6 3.4 L16.4 3.4", "M6.8 14.6 L17.2 14.6"),
}

MODE_ICONS: dict[Mode, str] = {
    Mode.POINTER: "pointer", Mode.SCROLL: "scroll", Mode.ZOOM: "zoom", Mode.VOLUME: "volume",
    Mode.WINDOWS: "windows", Mode.COMMANDS: "commands", Mode.INSTRUMENT: "instrument", Mode.DRAWING: "drawing",
}

_TOKEN = re.compile(r"[MLHVCQZ]|-?\d+(?:\.\d+)?")


def _svg(data: str) -> QPainterPath:
    tokens, i, path, cmd = _TOKEN.findall(data), 0, QPainterPath(), ""
    take = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "Q": 4}
    while i < len(tokens):
        if tokens[i].isalpha():
            cmd, i = tokens[i], i + 1
            if cmd == "Z":
                path.closeSubpath()
                continue
        n = [float(t) for t in tokens[i:i + take[cmd]]]
        i += take[cmd]
        at = path.currentPosition()
        if cmd == "M":
            path.moveTo(*n)
            cmd = "L"
        elif cmd == "L":
            path.lineTo(*n)
        elif cmd == "H":
            path.lineTo(n[0], at.y())
        elif cmd == "V":
            path.lineTo(at.x(), n[0])
        elif cmd == "C":
            path.cubicTo(*n)
        else:
            path.quadTo(*n)
    return path


def _part(part: Any) -> QPainterPath:
    if isinstance(part, str):
        return _svg(part)
    kind, path = part[0], QPainterPath()
    if kind == "c":
        path.addEllipse(QPointF(part[1], part[2]), part[3], part[3])
    elif kind == "r":
        path.addRoundedRect(QRectF(*part[1:5]), part[5], part[5])
    else:
        _, cx, cy, r, start, span = part
        box = QRectF(cx - r, cy - r, 2 * r, 2 * r)
        path.arcMoveTo(box, start)
        path.arcTo(box, start, span)
    return path


@lru_cache(maxsize=None)
def _shapes(name: str) -> tuple[QPainterPath, QPainterPath]:
    """(stroked, filled) paths of an icon."""
    stroked, filled = QPainterPath(), QPainterPath()
    for part in ICONS[name]:
        if not isinstance(part, str) and part[0] == "fill":
            filled.addPath(_part(part[1]))
        else:
            stroked.addPath(_part(part))
    return stroked, filled


def paint(p: QPainter, name: str, rect: QRectF, color: QColor | str = theme.TEXT, stroke: float = STROKE) -> None:
    """Draw an icon into a square rect with the painter's current device."""
    stroked, filled = _shapes(name)
    c = QColor(color)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.translate(rect.topLeft())
    p.scale(rect.width() / GRID, rect.height() / GRID)
    pen = QPen(c, stroke)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(stroked)
    if not filled.isEmpty():
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawPath(filled)
    p.restore()


def pixmap(name: str, size: int = 20, color: QColor | str = theme.TEXT, dpr: float = 1.0, pad: int = 0) -> QPixmap:
    """Icon picture; `pad` adds empty space on the right (gap before a button label)."""
    pix = QPixmap(round((size + pad) * dpr), round(size * dpr))
    pix.setDevicePixelRatio(dpr)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    paint(p, name, QRectF(0, 0, size, size), color)
    p.end()
    return pix


def icon(name: str, color: str = theme.TEXT_SOFT, checked: str = theme.ACCENT_TEXT, size: int = 20,
         pad: int = 0, checked_name: str = "") -> QIcon:
    """QIcon with disabled and checked variants (optionally another glyph while checked), sharp up to 2x scaling."""
    out = QIcon()
    for dpr in (1.0, 2.0):
        out.addPixmap(pixmap(name, size, color, dpr, pad), QIcon.Mode.Normal, QIcon.State.Off)
        out.addPixmap(pixmap(checked_name or name, size, checked, dpr, pad), QIcon.Mode.Normal, QIcon.State.On)
        out.addPixmap(pixmap(name, size, theme.FAINT, dpr, pad), QIcon.Mode.Disabled, QIcon.State.Off)
    return out


def paint_cat(p: QPainter, rect: QRectF, happy: bool = False) -> None:
    """Front view of the mascot's head."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.translate(rect.topLeft())
    p.scale(rect.width() / GRID, rect.height() / GRID)
    dark = QColor(theme.ON_ACCENT)
    p.setPen(QPen(QColor(theme.CAT_EDGE), 0.5))
    p.setBrush(QColor(theme.CAT_FUR))
    p.drawPath(_svg(CAT_HEAD))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(theme.CAT_EAR))
    p.drawPath(_svg("M5.7 8.4 L5.6 5.3 L8.3 7.3 Z M18.3 8.4 L18.4 5.3 L15.7 7.3 Z"))
    p.setBrush(QColor(theme.CAT_EDGE))                            # muzzle
    p.drawEllipse(QPointF(10.5, 16.5), 2.3, 2.0)
    p.drawEllipse(QPointF(13.5, 16.5), 2.3, 2.0)
    pen = QPen(dark, 0.62)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    if happy:
        p.setPen(QPen(pen))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(_svg("M6.6 13 C7.1 11.6 9.3 11.6 9.8 13 M14.2 13 C14.7 11.6 16.9 11.6 17.4 13"))
    else:
        for color, r, dx, dy in ((theme.CAT_IRIS, 2.3, 0.0, 0.0), (theme.ON_ACCENT, 1.4, 0.0, 0.0), (theme.WHITE, 0.5, -0.5, -0.6)):
            p.setBrush(QColor(color))
            for x in (8.1, 15.9):
                p.drawEllipse(QPointF(x + dx, 12.4 + dy), r, r)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(dark)
    p.drawPath(_svg("M11.2 14.9 L12.8 14.9 L12 15.9 Z"))
    p.setBrush(QColor(theme.WHITE))                               # the fang
    p.drawPath(_svg("M9.9 17.3 L10.7 17.4 L10.3 18.6 Z"))
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(_svg("M12 15.9 L12 16.6 M12 16.6 C11.6 17.6 10.4 17.6 10.1 16.9 M12 16.6 C12.4 17.6 13.6 17.6 13.9 16.9"))
    pen.setWidthF(0.34)
    pen.setColor(theme.color(theme.WHITE, 0.8))
    p.setPen(pen)
    p.drawPath(_svg("M7 15.6 L3.6 14.9 M7 16.6 L3.8 17 M17 15.6 L20.4 14.9 M17 16.6 L20.2 17"))
    p.restore()


def brand_icon() -> QIcon:
    """Window icon: the cat's head."""
    out = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        k = size * 0.10                              # the head fills the icon
        paint_cat(p, QRectF(-k, -k, size + 2 * k, size + 2 * k))
        p.end()
        out.addPixmap(pix)
    return out
