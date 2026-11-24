"""Small reusable controls of the Holoscobe look (toggle switch, setting rows, mode rail, hint chips, status pill)."""
from __future__ import annotations

import re
from typing import Callable, Optional

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractSpinBox, QCheckBox, QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout, QLabel, QLayout, QListView, QPushButton,
    QSizePolicy, QSpinBox, QStyledItemDelegate, QToolButton, QVBoxLayout, QWidget,
)

from handcontrol.ui import icons, theme


def capitalize_tr(text: str) -> str:
    """First letter upper case with the Turkish dotted i."""
    return {"i": "İ"}.get(text[:1], text[:1].upper()) + text[1:]


def label(text: str = "", role: str = "", wrap: bool = False) -> QLabel:
    w = QLabel(text)
    if role:
        w.setProperty("role", role)
    w.setWordWrap(wrap)
    return w


def button(text: str, kind: str = "", icon: str = "") -> QPushButton:
    w = QPushButton(text)
    if kind:
        w.setProperty("kind", kind)
    if icon:
        set_icon(w, icon, theme.ON_ACCENT if kind == "primary" else theme.TEXT_SOFT)
    w.setCursor(Qt.CursorShape.PointingHandCursor)
    return w


def set_icon(w: QAbstractButton, name: str, color: str = theme.TEXT_SOFT) -> None:
    """18 px icon followed by a small gap before the label."""
    w.setIcon(icons.icon(name, color, size=18, pad=6))
    w.setIconSize(QSize(24, 18))


def tool(text: str, icon: str) -> QToolButton:
    w = QToolButton()
    w.setProperty("tool", True)
    w.setText(text)
    set_icon(w, icon)
    w.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    w.setCursor(Qt.CursorShape.PointingHandCursor)
    return w


def line(vertical: bool = False) -> QFrame:
    w = QFrame()
    w.setProperty("role", "vline" if vertical else "line")
    return w


def _animation(owner: QWidget, ms: int, slot: Callable[[float], None]) -> QVariantAnimation:
    a = QVariantAnimation(owner)
    a.setDuration(ms)
    a.setEasingCurve(theme.EASE)
    a.valueChanged.connect(slot)
    return a


class ToggleSwitch(QCheckBox):
    """Animated switch. A plain QCheckBox for callers; `show_text` paints its label on the right."""

    W, H = 40, 22

    def __init__(self, text: str = "", parent: Optional[QWidget] = None, show_text: bool = False) -> None:
        super().__init__(text, parent)
        self._show_text = show_text
        self._pos = 0.0
        self._anim = _animation(self, theme.NORMAL_MS, self._move)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.toggled.connect(self._start)

    def _move(self, value: float) -> None:
        self._pos = float(value)
        self.update()

    def _start(self, on: bool) -> None:
        self._anim.stop()
        if not self.isVisible():
            self._pos = 1.0 if on else 0.0
            return
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def sizeHint(self) -> QSize:  # noqa: N802
        w = self.W + 4
        if self._show_text and self.text():
            w += 10 + self.fontMetrics().horizontalAdvance(self.text()) + 2
        return QSize(w, self.H + 6)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def hitButton(self, pos: QPoint) -> bool:  # noqa: N802
        return self.rect().contains(pos)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = self._pos if self._anim.state() == QVariantAnimation.State.Running else float(self.isChecked())
        track = QRectF(2, (self.height() - self.H) / 2, self.W, self.H)
        on = self.isEnabled()
        if self.hasFocus():
            p.setPen(QPen(QColor(theme.TEXT), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(track.adjusted(-1, -1.5, 1, 1.5), 13, 13)
            track = track.adjusted(1, 1, -1, -1)
        hover = on and self.underMouse()
        off_fill = theme.HOVER if hover else theme.RAISED
        on_fill = (theme.ACCENT_HOVER if hover else theme.ACCENT) if on else theme.STROKE
        edge = theme.mix(theme.CONTROL_STROKE if on else theme.STROKE, on_fill, t)
        p.setPen(QPen(edge, 1.4))
        p.setBrush(theme.mix(off_fill if on else theme.SURFACE, on_fill, t))
        p.drawRoundedRect(track.adjusted(0.7, 0.7, -0.7, -0.7), self.H / 2, self.H / 2)
        r = 5.6 + 1.6 * t + (0.6 if hover else 0.0)
        x = track.left() + 11 + t * (track.width() - 22)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.mix(theme.TEXT_SOFT if on else theme.FAINT, theme.ON_ACCENT if on else theme.FAINT, t))
        p.drawEllipse(QPointF(x, track.center().y()), r, r)
        if self._show_text:
            p.setPen(QColor(theme.TEXT_SOFT if on else theme.FAINT))
            p.drawText(self.rect().adjusted(self.W + 12, 0, 0, 0), int(Qt.AlignmentFlag.AlignVCenter), self.text())
        p.end()


class ComboBox(QComboBox):
    """Themed combo: own chevron, rounded list, ignores the wheel until it has focus (safe inside scroll areas)."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMaxVisibleItems(12)
        self.setView(QListView(self))                       # the plain list view honors the stylesheet's items
        self.setItemDelegate(QStyledItemDelegate(self))
        popup = self.view().window()
        popup.setObjectName("comboPopup")
        popup.setStyleSheet("#comboPopup { background: transparent; border: none; }")     # see-through corners
        theme.round_popup(popup)

    def wheelEvent(self, event) -> None:  # noqa: N802
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        p = QPainter(self)
        icons.paint(p, "chevron_down", QRectF(self.width() - 26, self.height() / 2 - 8, 16, 16),
                    theme.MUTED if self.isEnabled() else theme.FAINT, 2.2)
        p.end()


class _Steps:
    """Paints the up/down chevrons of a spin box and ignores the wheel until focused."""

    def _prepare(self) -> None:
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.lineEdit().setTextMargins(10, 0, 0, 0)

    def wheelEvent(self, event) -> None:  # noqa: N802
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        p = QPainter(self)
        can = self.stepEnabled()
        x, mid = self.width() - 20, self.height() / 2
        for name, y, flag in (("chevron_up", mid - 13.5, QAbstractSpinBox.StepEnabledFlag.StepUpEnabled),
                              ("chevron_down", mid + 0.5, QAbstractSpinBox.StepEnabledFlag.StepDownEnabled)):
            icons.paint(p, name, QRectF(x, y, 13, 13), theme.TEXT_SOFT if can & flag else theme.FAINT, 2.2)
        p.end()


class SpinBox(_Steps, QSpinBox):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._prepare()


class DoubleSpinBox(_Steps, QDoubleSpinBox):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._prepare()


class FlowLayout(QLayout):
    """Left to right, wrapping onto new lines; items of one line share its vertical middle."""

    def __init__(self, parent: Optional[QWidget] = None, h: int = 8, v: int = 8) -> None:
        super().__init__(parent)
        self._items: list = []
        self._h, self._v = h, v
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, i: int):  # noqa: N802
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i: int):  # noqa: N802
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._arrange(QRect(0, 0, width, 0), False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            if not item.isEmpty():
                size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._arrange(rect, True)

    def _arrange(self, rect: QRect, apply: bool) -> int:
        m = self.contentsMargins()
        area = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        rows: list[tuple[list, int]] = []
        row: list = []
        x = height = 0
        for item in self._items:
            if item.isEmpty():
                continue
            size = item.sizeHint()
            size.setWidth(min(size.width(), max(1, area.width())))
            if row and x + size.width() > area.width():
                rows.append((row, height))
                row, x, height = [], 0, 0
            row.append((item, x, size))
            x += size.width() + self._h
            height = max(height, size.height())
        if row:
            rows.append((row, height))
        y = area.top()
        for row, height in rows:
            if apply:
                for item, left, size in row:
                    item.setGeometry(QRect(QPoint(area.left() + left, y + (height - size.height()) // 2), size))
            y += height + self._v
        return y - (self._v if rows else 0) - rect.top() + m.bottom()


class Card(QFrame):
    """Rounded surface with rows separated by hairlines."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "card")
        self._column = QVBoxLayout(self)
        self._column.setContentsMargins(0, 4, 0, 4)
        self._column.setSpacing(0)

    def add(self, row: QWidget) -> QWidget:
        if self._column.count():
            holder = QWidget()
            inset = QHBoxLayout(holder)
            inset.setContentsMargins(16, 0, 16, 0)
            inset.addWidget(line())
            self._column.addWidget(holder)
        self._column.addWidget(row)
        return row


class SettingRow(QWidget):
    """Title and one-line description on the left, the control on the right."""

    def __init__(self, title: str, description: str, control: QWidget, width: int = 0) -> None:
        super().__init__()
        self.control = control
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 11, 16, 11)
        row.setSpacing(20)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        texts.addWidget(label(title, "row", True))
        if description:
            texts.addWidget(label(description, "caption", True))
        row.addLayout(texts, 1)
        if width:
            control.setFixedWidth(width)
        row.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        if not control.accessibleName():
            control.setAccessibleName(title)
        if description:
            control.setAccessibleDescription(description)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if isinstance(self.control, ToggleSwitch) and self.control.isEnabled() \
                and event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.control.click()
        super().mouseReleaseEvent(event)


class StatusPill(QWidget):
    """Dot + short state text."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._text, self._color = "", QColor(theme.MUTED)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._font = theme.font(theme.TEXT_PX["caption"])
        self.setFont(self._font)

    def text(self) -> str:
        return self._text

    def set_status(self, text: str, color: str) -> None:
        if (text, QColor(color)) == (self._text, self._color):
            return
        self._text, self._color = text, QColor(color)
        self.setAccessibleName(text)
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.fontMetrics().horizontalAdvance(self._text) + 40, 28)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(theme.HAIRLINE), 1))
        p.setBrush(QColor(theme.SURFACE))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        glow = QColor(self._color)
        glow.setAlphaF(0.24)
        at = QPointF(16, r.center().y())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(at, 7, 7)
        p.setBrush(self._color)
        p.drawEllipse(at, 3.6, 3.6)
        p.setPen(QColor(theme.TEXT_SOFT))
        p.setFont(self._font)
        p.drawText(self.rect().adjusted(28, 0, -8, 0), int(Qt.AlignmentFlag.AlignVCenter), self._text)
        p.end()


class NavButton(QToolButton):
    """Rail entry: icon above label. The rail paints the selected pill behind it."""

    def __init__(self, text: str, icon: str, parent: Optional[QWidget] = None, size: QSize = QSize(84, 62)) -> None:
        super().__init__(parent)
        self._icon_name = icon
        self.setText(text)
        self.setCheckable(True)
        self.setFixedSize(size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(text)

    def set_icon_name(self, name: str) -> None:
        if name != self._icon_name:
            self._icon_name = name
            self.update()

    def open_menu(self) -> None:
        self.menu().popup(self.mapToGlobal(QPoint(self.width() + 6, 0)))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self.menu() is not None and event.button() == Qt.MouseButton.LeftButton:
            self.open_menu()                        # beside the rail, not below the button
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if self.menu() is not None and event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.open_menu()
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        on = self.isChecked()
        if not on and (self.underMouse() or self.isDown()):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.HOVER if self.isDown() else theme.RAISED))
            p.drawRoundedRect(r, theme.RADIUS_L, theme.RADIUS_L)
        if self.hasFocus():
            p.setPen(QPen(QColor(theme.ACCENT), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r, theme.RADIUS_L, theme.RADIUS_L)
        c = QColor(theme.ACCENT if on else theme.TEXT if self.underMouse() else theme.MUTED)
        icons.paint(p, self._icon_name, QRectF(self.width() / 2 - 11, 10, 22, 22), c)
        f = theme.bold(11) if on else theme.font(11)
        p.setFont(f)
        p.setPen(QColor(theme.ACCENT_TEXT if on else theme.TEXT if self.underMouse() else theme.MUTED))
        p.drawText(QRectF(0, 36, self.width(), 18), int(Qt.AlignmentFlag.AlignCenter),
                   p.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, self.width() - 4))
        p.end()


class ModeRail(QWidget):
    """Left navigation column; a tinted pill slides to the checked NavButton."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(100)
        self.column = QVBoxLayout(self)
        self.column.setContentsMargins(8, 16, 8, 12)
        self.column.setSpacing(4)
        self._target: Optional[QWidget] = None
        self._y = 0.0
        self._anim = _animation(self, theme.NORMAL_MS, self._move)

    def _move(self, value: float) -> None:
        self._y = float(value)
        self.update()

    def select(self, target: QWidget) -> None:
        if target is self._target:
            return
        animate = self._target is not None and self.isVisible()
        self._anim.stop()
        self._anim.setStartValue(self._y)
        self._target = target
        if animate:
            self._anim.setEndValue(float(target.y()))
            self._anim.start()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(theme.SURFACE))
        p.fillRect(QRect(self.width() - 1, 0, 1, self.height()), QColor(theme.HAIRLINE))
        if self._target is not None:
            if self._anim.state() != QVariantAnimation.State.Running:
                self._y = float(self._target.y())
            pill = QRectF(self._target.x() + 1, self._y + 1, self._target.width() - 2, self._target.height() - 2)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.color(theme.ACCENT, 0.15))
            p.drawRoundedRect(pill, theme.RADIUS_L, theme.RADIUS_L)
            p.setBrush(QColor(theme.ACCENT))
            p.drawRoundedRect(QRectF(0, pill.center().y() - 12, 3, 24), 1.5, 1.5)
        p.end()


class SideItem(QToolButton):
    """Settings category: icon + label row with a filled selection."""

    def __init__(self, text: str, icon: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._icon_name = icon
        self.setText(text)
        self.setCheckable(True)
        self.setFixedHeight(40)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        on, hover = self.isChecked(), self.underMouse()
        p.setPen(QPen(QColor(theme.ACCENT), 1.5) if self.hasFocus() else Qt.PenStyle.NoPen)
        p.setBrush(theme.color(theme.ACCENT, 0.15) if on else QColor(theme.RAISED) if hover else Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, theme.RADIUS_M, theme.RADIUS_M)
        if on:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.ACCENT))
            p.drawRoundedRect(QRectF(1, r.center().y() - 9, 3, 18), 1.5, 1.5)
        c = QColor(theme.ACCENT_TEXT if on else theme.TEXT if hover else theme.TEXT_SOFT)
        icons.paint(p, self._icon_name, QRectF(14, self.height() / 2 - 10, 20, 20), c)
        p.setFont(theme.bold() if on else theme.font())
        p.setPen(c)
        p.drawText(self.rect().adjusted(46, 0, -8, 0), int(Qt.AlignmentFlag.AlignVCenter), self.text())
        p.end()


class Segmented(QFrame):
    """Row of exclusive choices inside one rounded track."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "segments")
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(3, 3, 3, 3)
        self.row.setSpacing(2)

    def add(self, text: str) -> QPushButton:
        b = QPushButton(text)
        b.setCheckable(True)
        b.setProperty("seg", True)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        self.row.addWidget(b)
        return b


class Banner(QLabel):
    """Tinted one-message strip with an icon."""

    def __init__(self, text: str = "", tone: str = theme.WARNING, icon: str = "info") -> None:
        super().__init__(text)
        self._tone, self._icon_name = tone, icon
        self.setWordWrap(True)
        self.setContentsMargins(42, 9, 14, 9)
        self.setProperty("role", "banner")

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(theme.color(self._tone, 0.32), 1))
        p.setBrush(theme.color(self._tone, 0.10))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), theme.RADIUS_M, theme.RADIUS_M)
        icons.paint(p, self._icon_name, QRectF(13, self.height() / 2 - 9, 18, 18), self._tone)
        p.end()
        super().paintEvent(event)


class HintBar(QWidget):
    """Gesture hints. `setText("jest: sonuç · jest: sonuç")` shows every part as a keycap chip; `text()` keeps the
    sentence. `set_vertical` turns the strip into a side list, `set_error` shows one warning instead."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._text, self._error, self._vertical = "", "", False
        self._flow: Optional[QLayout] = None
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        self._body = QWidget()
        column.addWidget(self._body)
        self._rebuild()

    def text(self) -> str:
        return self._text

    def setText(self, text: str) -> None:  # noqa: N802
        self.show_message(text, False)

    def show_message(self, text: str, error: bool) -> None:
        if (text, error) != (self._text, bool(self._error)):
            self._text, self._error = text, text if error else ""
            self._rebuild()

    @property
    def vertical(self) -> bool:
        return self._vertical

    def set_vertical(self, on: bool) -> None:
        if on != self._vertical:
            self._vertical = on
            self._rebuild()

    def parts(self) -> list[tuple[str, str]]:
        """(gesture, result) pairs; a part without ':' has an empty result."""
        out = []
        for piece in re.split(r"\s*·\s*", self._text):
            if piece.strip():
                gesture, _, result = piece.partition(":")
                out.append((capitalize_tr(gesture.strip()), result.strip()))
        return out

    def _rebuild(self) -> None:
        old = self._body
        self._body = QWidget()
        self.layout().replaceWidget(old, self._body)
        old.hide()
        old.deleteLater()
        if self._vertical or self._error:
            box: QLayout = QVBoxLayout(self._body)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(8)
        else:
            box = FlowLayout(self._body, 16, 8)
        if self._error:
            box.addWidget(Banner(self._error, theme.DANGER, "warning"))
        elif self._vertical:
            box.addWidget(label("Hareketler", "section"))
            for gesture, result in self.parts():
                box.addWidget(self._side_card(gesture, result))
        else:
            for gesture, result in self.parts():
                box.addWidget(self._chip(gesture, result))
        if self._vertical:
            box.addStretch(1)

    @staticmethod
    def _chip(gesture: str, result: str) -> QWidget:
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(label(gesture, "keycap"))
        if result:
            row.addWidget(label(result, "caption"))
        return w

    @staticmethod
    def _side_card(gesture: str, result: str) -> QWidget:
        w = QFrame()
        w.setProperty("role", "card")
        col = QVBoxLayout(w)
        col.setContentsMargins(14, 10, 14, 10)
        col.setSpacing(2)
        col.addWidget(label(gesture, "row", True))
        if result:
            col.addWidget(label(capitalize_tr(result), "caption", True))
        return w


__all__ = [
    "Banner", "Card", "ComboBox", "DoubleSpinBox", "FlowLayout", "HintBar", "ModeRail", "NavButton", "Segmented",
    "SettingRow", "SideItem", "SpinBox", "StatusPill", "ToggleSwitch", "button", "label", "line",
    "set_icon", "tool",
]
