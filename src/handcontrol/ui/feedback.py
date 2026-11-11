"""Non-focus-stealing transient feedback notifications and Dry-Run command panel.

Notifications supported:
- Activated ("Etkinleşti")
- Paused ("Duraklatıldı")
- Mode changed ("Mod Değişti")
- Volume % ("Ses %")
- Close confirmation ("Kapatma Onayı")

Also includes `DryRunPanel` showing the "Üretilecek komut" text for dry-run mode.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRectF, Qt, QTimer, Slot
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget

from handcontrol.contracts import Action, Mode
from handcontrol.ui.viewmodel import (
    MODE_LABELS_TR,
    FeedbackKind,
    FeedbackMessage,
    UiBridge,
    format_action_tr,
)


def _normalize_volume_percent(value: int | float) -> int:
    """Convert either a [0.0, 1.0] scalar or [0, 100] number into an integer percentage."""
    if isinstance(value, float) and 0.0 <= value <= 1.0:
        return max(0, min(100, round(value * 100)))
    return max(0, min(100, round(float(value))))


class FeedbackToast(QWidget):
    """Short, non-focus-stealing OSD toast that disappears automatically."""

    def __init__(
        self,
        bridge: Optional[UiBridge] = None,
        auto_show_window: bool = False,
        default_duration_ms: int = 1800,
        parent: Optional[QWidget] = None,
    ) -> None:
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowTransparentForInput
        )
        super().__init__(parent, flags)
        self._bridge = bridge
        self._auto_show_window = bool(auto_show_window)
        self._default_duration_ms = max(100, int(default_duration_ms))

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.resize(340, 84)

        self._current_message: Optional[FeedbackMessage] = None
        self._remaining_ms: int = 0
        self._active: bool = False

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.dismiss)

        if self._bridge is not None:
            self._bridge.feedback_triggered.connect(self.show_feedback_message)

    @property
    def current_message(self) -> Optional[FeedbackMessage]:
        return self._current_message

    @property
    def current_text(self) -> str:
        return self._current_message.text if self._current_message is not None else ""

    @property
    def is_notification_active(self) -> bool:
        return self._active

    @property
    def remaining_ms(self) -> int:
        return self._remaining_ms

    @Slot(object)
    def show_feedback_message(self, message: FeedbackMessage) -> None:
        """Display a FeedbackMessage and start the auto-hide countdown."""
        self._current_message = message
        duration = max(100, int(message.duration_ms or self._default_duration_ms))
        self._remaining_ms = duration
        self._active = True
        self._hide_timer.start(duration)
        if self._auto_show_window:
            self.show()
        self.update()

    def notify_activated(self, duration_ms: Optional[int] = None) -> FeedbackMessage:
        """Show 'Activated' notification in Turkish."""
        msg = FeedbackMessage(
            kind=FeedbackKind.ACTIVATED,
            text="El Kontrolü Etkinleşti",
            duration_ms=duration_ms or self._default_duration_ms,
        )
        self.show_feedback_message(msg)
        return msg

    def notify_paused(self, duration_ms: Optional[int] = None) -> FeedbackMessage:
        """Show 'Paused' notification in Turkish."""
        msg = FeedbackMessage(
            kind=FeedbackKind.PAUSED,
            text="El Kontrolü Duraklatıldı",
            duration_ms=duration_ms or self._default_duration_ms,
        )
        self.show_feedback_message(msg)
        return msg

    def notify_mode_changed(
        self,
        mode: Mode,
        duration_ms: Optional[int] = None,
    ) -> FeedbackMessage:
        """Show 'Mode Changed' notification in Turkish."""
        mode_tr = MODE_LABELS_TR.get(mode, mode.value)
        msg = FeedbackMessage(
            kind=FeedbackKind.MODE_CHANGED,
            text=f"Mod Değişti: {mode_tr}",
            duration_ms=duration_ms or self._default_duration_ms,
        )
        self.show_feedback_message(msg)
        return msg

    def notify_volume(
        self,
        volume: int | float,
        duration_ms: Optional[int] = None,
    ) -> FeedbackMessage:
        """Show 'Volume %' notification in Turkish."""
        pct = _normalize_volume_percent(volume)
        msg = FeedbackMessage(
            kind=FeedbackKind.VOLUME,
            text=f"Ses Seviyesi: %{pct}",
            volume_percent=pct,
            duration_ms=duration_ms or self._default_duration_ms,
        )
        self.show_feedback_message(msg)
        return msg

    def notify_close_confirmation(
        self,
        progress: float = 1.0,
        confirmed: bool = True,
        duration_ms: Optional[int] = None,
    ) -> FeedbackMessage:
        """Show 'Close Confirmation' notification in Turkish."""
        clamped = max(0.0, min(1.0, float(progress)))
        pct = round(clamped * 100)
        if confirmed or clamped >= 1.0:
            text = "Kapatma Onayı: Pencere kapatma isteği gönderildi"
        else:
            text = f"Kapatma Onayı: Basılı tutun (%{pct})"
        msg = FeedbackMessage(
            kind=FeedbackKind.CLOSE_CONFIRM,
            text=text,
            hold_progress=clamped,
            duration_ms=duration_ms or self._default_duration_ms,
        )
        self.show_feedback_message(msg)
        return msg

    def advance_time(self, elapsed_ms: int) -> None:
        """Advance countdown deterministically (used in tests without waiting on real time)."""
        if not self._active:
            return
        self._remaining_ms = max(0, self._remaining_ms - max(0, int(elapsed_ms)))
        if self._remaining_ms == 0:
            self.dismiss()

    @Slot()
    def dismiss(self) -> None:
        """Immediately dismiss and hide the notification."""
        self._hide_timer.stop()
        self._active = False
        self._remaining_ms = 0
        if self.isVisible():
            self.hide()
        self.update()

    def render_to_image(self, width: int = 340, height: int = 84) -> QImage:
        """Render the toast to an offscreen QImage."""
        self.resize(width, height)
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        self._paint_toast(painter, QRectF(0.0, 0.0, float(width), float(height)))
        painter.end()
        return image

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        self._paint_toast(
            painter,
            QRectF(0.0, 0.0, float(self.width()), float(self.height())),
        )
        painter.end()

    def _paint_toast(self, painter: QPainter, rect: QRectF) -> None:
        if not self._active or self._current_message is None:
            return

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        msg = self._current_message

        accent_colors = {
            FeedbackKind.ACTIVATED: QColor(46, 204, 113),
            FeedbackKind.PAUSED: QColor(241, 196, 15),
            FeedbackKind.MODE_CHANGED: QColor(52, 152, 219),
            FeedbackKind.VOLUME: QColor(155, 89, 182),
            FeedbackKind.CLOSE_CONFIRM: QColor(231, 76, 60),
            FeedbackKind.INFO: QColor(127, 140, 141),
            FeedbackKind.WARNING: QColor(230, 126, 34),
        }
        accent = accent_colors.get(msg.kind, QColor(82, 168, 242))

        box = rect.adjusted(6.0, 6.0, -6.0, -6.0)
        painter.setPen(QPen(accent, 2.0))
        painter.setBrush(QColor(20, 26, 36, 232))
        painter.drawRoundedRect(box, 10.0, 10.0)

        font = QFont("Segoe UI", 10)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(240, 245, 250))

        text_rect = QRectF(box.left() + 14.0, box.top() + 10.0, box.width() - 28.0, 28.0)
        painter.drawText(
            text_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            msg.text,
        )

        # Draw progress bar for volume or close confirmation
        bar_ratio: Optional[float] = None
        if msg.volume_percent is not None:
            bar_ratio = max(0.0, min(1.0, msg.volume_percent / 100.0))
        elif msg.hold_progress is not None:
            bar_ratio = max(0.0, min(1.0, msg.hold_progress))

        if bar_ratio is not None:
            bar_rect = QRectF(box.left() + 14.0, box.bottom() - 20.0, box.width() - 28.0, 8.0)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(45, 54, 68))
            painter.drawRoundedRect(bar_rect, 4.0, 4.0)
            if bar_ratio > 0.0:
                painter.setBrush(accent)
                painter.drawRoundedRect(
                    QRectF(bar_rect.left(), bar_rect.top(), bar_rect.width() * bar_ratio, bar_rect.height()),
                    4.0,
                    4.0,
                )


class DryRunPanel(QWidget):
    """Compact non-focus-stealing panel displaying the 'Üretilecek komut' text in dry-run mode."""

    def __init__(
        self,
        bridge: Optional[UiBridge] = None,
        max_history: int = 5,
        parent: Optional[QWidget] = None,
    ) -> None:
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowTransparentForInput
        )
        super().__init__(parent, flags)
        self._bridge = bridge
        self._max_history = max(1, int(max_history))
        self._current_command_text: str = "Üretilecek komut: Henüz komut yok"
        self._history: list[str] = []

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.resize(400, 120)

        if self._bridge is not None:
            self._bridge.dry_run_updated.connect(self.set_command_text)
            if self._bridge.state.dry_run_command_text:
                self.set_command_text(self._bridge.state.dry_run_command_text)

    @property
    def current_command_text(self) -> str:
        return self._current_command_text

    @property
    def command_history(self) -> tuple[str, ...]:
        return tuple(self._history)

    @Slot(str)
    def set_command_text(self, text: str) -> None:
        """Set the latest dry-run command text."""
        cleaned = str(text).strip()
        if not cleaned.startswith("Üretilecek komut:"):
            cleaned = f"Üretilecek komut: {cleaned}"
        self._current_command_text = cleaned
        self._history.append(cleaned)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history :]
        self.update()

    def set_action(self, action: Action | str) -> str:
        """Format a contracts.Action (or string) and display it in the panel."""
        if isinstance(action, Action):
            formatted = format_action_tr(action)
        else:
            formatted = str(action)
        self.set_command_text(formatted)
        return self._current_command_text

    def clear_commands(self) -> None:
        """Reset displayed dry-run command history."""
        self._history.clear()
        self._current_command_text = "Üretilecek komut: Henüz komut yok"
        self.update()

    def render_to_image(self, width: int = 400, height: int = 120) -> QImage:
        """Render the dry-run panel to an offscreen QImage."""
        self.resize(width, height)
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        self._paint_panel(painter, QRectF(0.0, 0.0, float(width), float(height)))
        painter.end()
        return image

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        self._paint_panel(
            painter,
            QRectF(0.0, 0.0, float(self.width()), float(self.height())),
        )
        painter.end()

    def _paint_panel(self, painter: QPainter, rect: QRectF) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        box = rect.adjusted(6.0, 6.0, -6.0, -6.0)

        painter.setPen(QPen(QColor(245, 176, 65, 220), 1.8))
        painter.setBrush(QColor(20, 24, 32, 230))
        painter.drawRoundedRect(box, 8.0, 8.0)

        header_font = QFont("Segoe UI", 9)
        header_font.setBold(True)
        painter.setFont(header_font)
        painter.setPen(QColor(245, 176, 65))
        painter.drawText(
            QRectF(box.left() + 10.0, box.top() + 6.0, box.width() - 20.0, 18.0),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            "DRY-RUN (Sınama Kipi) — Üretilecek Komut Paneli",
        )

        cmd_font = QFont("Segoe UI", 10)
        cmd_font.setBold(True)
        painter.setFont(cmd_font)
        painter.setPen(QColor(235, 242, 250))
        painter.drawText(
            QRectF(box.left() + 10.0, box.top() + 28.0, box.width() - 20.0, 24.0),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            self._current_command_text,
        )

        hist_font = QFont("Consolas", 8)
        painter.setFont(hist_font)
        painter.setPen(QColor(160, 175, 195))
        y = box.top() + 56.0
        for item in reversed(self._history[:-1][-2:]):
            painter.drawText(
                QRectF(box.left() + 10.0, y, box.width() - 20.0, 16.0),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                item,
            )
            y += 16.0


# Alias for convenience
FeedbackOverlay = FeedbackToast
