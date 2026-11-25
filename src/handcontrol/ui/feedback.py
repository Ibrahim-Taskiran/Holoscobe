"""Short notifications and the panel with the commands a dry run would have sent."""
from __future__ import annotations

from collections import deque
from typing import Optional

from PySide6.QtCore import QRectF, Qt, QTimer, QVariantAnimation, Slot
from PySide6.QtGui import QColor, QFontMetrics, QGuiApplication, QPainter
from PySide6.QtWidgets import QWidget

from handcontrol.ui import icons, theme
from handcontrol.ui.painted import ClickThroughWindow
from handcontrol.ui.viewmodel import FeedbackKind, FeedbackMessage, UiBridge


TOAST_MARGIN = 14                # room for the soft shadow around the panel
TOAST_LIFT = 44                  # distance from the bottom edge of the screen
_LOOKS: dict[FeedbackKind, tuple[str, str]] = {
    FeedbackKind.INFO: ("info", theme.TEXT_SOFT),
    FeedbackKind.WARNING: ("warning", theme.WARNING),
}


class FeedbackToast(ClickThroughWindow):
    """Short, non-focus-stealing OSD toast that disappears automatically."""

    def __init__(
        self,
        bridge: Optional[UiBridge] = None,
        auto_show_window: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(340, 84, parent)
        self._auto_show_window = bool(auto_show_window)
        self._fade = 1.0
        self._anim = QVariantAnimation(self)
        self._anim.setEasingCurve(theme.EASE)
        self._anim.valueChanged.connect(self._on_fade)
        self._anim.finished.connect(self._on_fade_done)

        self.current_message: Optional[FeedbackMessage] = None
        self._active: bool = False

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.dismiss)

        if bridge is not None:
            bridge.feedback_triggered.connect(self.show_feedback_message)

    @Slot(object)
    def show_feedback_message(self, message: FeedbackMessage) -> None:
        """Display a FeedbackMessage and start the auto-hide countdown."""
        self.current_message = message
        self._active = True
        self._hide_timer.start(message.duration_ms)
        self._fit(message)
        if self._auto_show_window:
            self._place()
            if not self.isVisible() or self._fade < 1.0:
                self._run_fade(self._fade if self.isVisible() else 0.0, 1.0, theme.NORMAL_MS)
            self.show()
        self.update()

    def _fit(self, message: FeedbackMessage) -> None:
        """Size the toast to its text (one or two lines)."""
        metrics = QFontMetrics(theme.bold(theme.TEXT_PX["section"]))
        text_w = metrics.horizontalAdvance(message.text)
        w = max(230, min(430, text_w + 94)) + 2 * TOAST_MARGIN
        lines = 1 if text_w + 94 <= 430 else 2
        self.resize(w, 2 * TOAST_MARGIN + 60 + (lines - 1) * 18)

    def _place(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            self.move(area.center().x() - self.width() // 2, area.bottom() - self.height() - TOAST_LIFT)

    def _run_fade(self, start: float, end: float, ms: int) -> None:
        self._anim.stop()
        self._anim.setDuration(ms)
        self._anim.setStartValue(float(start))
        self._anim.setEndValue(float(end))
        self._fade = start
        self._anim.start()

    @Slot(object)
    def _on_fade(self, value: object) -> None:
        self._fade = float(value)  # type: ignore[arg-type]
        self.update()

    @Slot()
    def _on_fade_done(self) -> None:
        if not self._active:
            self.hide()
            self._fade = 1.0

    @Slot()
    def dismiss(self) -> None:
        """Dismiss the notification; a visible window fades out and hides."""
        self._hide_timer.stop()
        was_active, self._active = self._active, False
        if self.isVisible() and was_active:
            self._run_fade(self._fade, 0.0, theme.FAST_MS)
        self.update()

    def _paint(self, painter: QPainter, rect: QRectF) -> None:
        msg = self.current_message
        fading = self._anim.state() == QVariantAnimation.State.Running
        if msg is None or not (self._active or fading):
            return
        painter.setOpacity(self._fade)
        icon, tone = _LOOKS[msg.kind]
        m = float(TOAST_MARGIN)
        box = rect.adjusted(m, m, -m, -m)
        theme.paint_glass(painter, box, theme.RADIUS_XL, alpha=0.95, blur=TOAST_MARGIN - 2)

        tile = QRectF(box.left() + 12.0, box.center().y() - 18.0, 36.0, 36.0)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.color(tone, 0.18))
        painter.drawRoundedRect(tile, 10.0, 10.0)
        icons.paint(painter, icon, tile.adjusted(8, 8, -8, -8), tone)

        text_rect = QRectF(tile.right() + 14.0, box.top() + 6.0, box.right() - tile.right() - 30.0, box.height() - 12.0)
        painter.setFont(theme.bold(theme.TEXT_PX["section"]))
        painter.setPen(QColor(theme.TEXT))
        painter.drawText(text_rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                                        | Qt.TextFlag.TextWordWrap), msg.text)


class DryRunPanel(ClickThroughWindow):
    """Compact non-focus-stealing panel displaying the 'Üretilecek komut' text in dry-run mode."""

    def __init__(
        self,
        bridge: Optional[UiBridge] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(440, 140, parent)
        self._history: deque[str] = deque(maxlen=3)
        self._placed = False
        if bridge is not None:
            bridge.dry_run_updated.connect(self.set_command_text)
            if bridge.state.dry_run_command_text:
                self.set_command_text(bridge.state.dry_run_command_text)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        screen = QGuiApplication.primaryScreen()
        if screen is not None and not self._placed:
            self._placed = True
            area = screen.availableGeometry()
            self.move(area.left() + 16, area.bottom() - self.height() - 16)

    @property
    def current_command_text(self) -> str:
        return self._history[-1] if self._history else "Henüz komut yok"

    @Slot(str)
    def set_command_text(self, text: str) -> None:
        self._history.append(text)
        self.update()

    def _paint(self, painter: QPainter, rect: QRectF) -> None:
        m = float(TOAST_MARGIN)
        box = rect.adjusted(m, m, -m, -m)
        theme.paint_glass(painter, box, theme.RADIUS_L, alpha=0.93, blur=TOAST_MARGIN - 2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.WARNING))
        painter.drawEllipse(QRectF(box.left() + 16.0, box.top() + 16.0, 8.0, 8.0))
        align = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        left, width = box.left() + 16.0, box.width() - 32.0

        def line(text: str, y: float, font, color: str, indent: float = 0.0) -> None:
            painter.setFont(font)
            painter.setPen(QColor(color))
            painter.drawText(QRectF(left + indent, y, width - indent, 20.0), align, painter.fontMetrics().elidedText(
                text, Qt.TextElideMode.ElideRight, int(width - indent)))

        line("DRY-RUN (Sınama Kipi) — Üretilecek Komut Paneli", box.top() + 10.0, theme.font(11), theme.MUTED, 16.0)
        line(self.current_command_text, box.top() + 34.0, theme.bold(), theme.TEXT)
        for i, item in enumerate(list(self._history)[-2::-1]):
            line(item, box.top() + 62.0 + 20.0 * i, theme.font(11), theme.MUTED)
