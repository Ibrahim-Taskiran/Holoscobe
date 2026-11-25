"""Base classes of the widgets that are drawn completely with a painter."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QWidget

CLICK_THROUGH = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
                 | Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.WindowTransparentForInput)


class PaintedWidget(QWidget):
    """Subclasses draw everything in _paint()."""

    def _paint(self, painter: QPainter, rect: QRectF) -> None:
        raise NotImplementedError

    def _paint_on(self, device) -> None:
        painter = QPainter(device)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._paint(painter, QRectF(self.rect()))
        painter.end()

    def paintEvent(self, event) -> None:  # noqa: N802
        self._paint_on(self)

    def render_to_image(self, width: int = 0, height: int = 0) -> QImage:
        """Offscreen picture of the widget, at its own size unless another one is given."""
        if width and height:
            self.resize(width, height)
        image = QImage(self.size(), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        self._paint_on(image)
        return image


class ClickThroughWindow(PaintedWidget):
    """Transparent always-on-top window that takes neither the focus nor the mouse."""

    def __init__(self, width: int, height: int, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent, CLICK_THROUGH)
        for attribute in (Qt.WidgetAttribute.WA_TranslucentBackground, Qt.WidgetAttribute.WA_ShowWithoutActivating,
                          Qt.WidgetAttribute.WA_TransparentForMouseEvents):
            self.setAttribute(attribute)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.resize(width, height)


__all__ = ["CLICK_THROUGH", "ClickThroughWindow", "PaintedWidget"]
