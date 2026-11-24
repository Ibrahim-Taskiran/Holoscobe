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

from PySide6.QtCore import QRectF, Qt, QTimer, QVariantAnimation, Slot
from PySide6.QtGui import QColor, QFontMetrics, QGuiApplication, QImage, QPainter
from PySide6.QtWidgets import QWidget

from handcontrol.contracts import Action, Mode
from handcontrol.ui import icons, theme
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


TOAST_MARGIN = 14                # room for the soft shadow around the panel
TOAST_LIFT = 44                  # distance from the bottom edge of the screen
_LOOKS: dict[FeedbackKind, tuple[str, str]] = {
    FeedbackKind.ACTIVATED: ("hand", theme.SUCCESS),
    FeedbackKind.PAUSED: ("pause", theme.WARNING),
    FeedbackKind.MODE_CHANGED: ("more", theme.ACCENT),
    FeedbackKind.VOLUME: ("volume", theme.ACCENT),
    FeedbackKind.CLOSE_CONFIRM: ("close", theme.DANGER),
    FeedbackKind.INFO: ("info", theme.TEXT_SOFT),
    FeedbackKind.WARNING: ("warning", theme.WARNING),
}


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
        self._fade = 1.0
        self._anim = QVariantAnimation(self)
        self._anim.setEasingCurve(theme.EASE)
        self._anim.valueChanged.connect(self._on_fade)
        self._anim.finished.connect(self._on_fade_done)

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
        self._fit(message)
        if self._auto_show_window:
            self._place()
            if not self.isVisible() or self._fade < 1.0:
                self._run_fade(self._fade if self.isVisible() else 0.0, 1.0, theme.NORMAL_MS)
            self.show()
        self.update()

    def _fit(self, message: FeedbackMessage) -> None:
        """Size the toast to its text (one or two lines) and optional bar."""
        metrics = QFontMetrics(theme.bold(theme.TEXT_PX["section"]))
        text_w = metrics.horizontalAdvance(message.text)
        w = max(230, min(430, text_w + 94)) + 2 * TOAST_MARGIN
        lines = 1 if text_w + 94 <= 430 else 2
        bar = message.volume_percent is not None or message.hold_progress is not None
        self.resize(w, 2 * TOAST_MARGIN + 60 + (lines - 1) * 18 + (14 if bar else 0))

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
        """Dismiss the notification; a visible window fades out and hides."""
        self._hide_timer.stop()
        was_active, self._active = self._active, False
        self._remaining_ms = 0
        if self.isVisible() and was_active:
            self._run_fade(self._fade, 0.0, theme.FAST_MS)
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
        msg = self._current_message
        fading = self._anim.state() == QVariantAnimation.State.Running
        if msg is None or not (self._active or fading):
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setOpacity(self._fade)
        icon, tone = _LOOKS.get(msg.kind, ("info", theme.ACCENT))
        if msg.kind is FeedbackKind.MODE_CHANGED:
            icon = next((icons.MODE_ICONS[m] for m, name in MODE_LABELS_TR.items() if msg.text.endswith(name)), icon)
        m = float(TOAST_MARGIN)
        box = rect.adjusted(m, m, -m, -m)
        theme.paint_glass(painter, box, theme.RADIUS_XL, alpha=0.95, blur=TOAST_MARGIN - 2)

        bar_ratio: Optional[float] = None
        if msg.volume_percent is not None:
            bar_ratio = max(0.0, min(1.0, msg.volume_percent / 100.0))
        elif msg.hold_progress is not None:
            bar_ratio = max(0.0, min(1.0, msg.hold_progress))

        tile = QRectF(box.left() + 12.0, box.center().y() - 18.0, 36.0, 36.0)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.color(tone, 0.18))
        painter.drawRoundedRect(tile, 10.0, 10.0)
        icons.paint(painter, icon, tile.adjusted(8, 8, -8, -8), tone)

        text_rect = QRectF(tile.right() + 14.0, box.top() + 6.0, box.right() - tile.right() - 30.0,
                           box.height() - 12.0 - (16.0 if bar_ratio is not None else 0.0))
        painter.setFont(theme.bold(theme.TEXT_PX["section"]))
        painter.setPen(QColor(theme.TEXT))
        painter.drawText(text_rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                                        | Qt.TextFlag.TextWordWrap), msg.text)
        if bar_ratio is not None:
            theme.paint_bar(painter, QRectF(text_rect.left(), box.bottom() - 18.0, text_rect.width(), 5.0), bar_ratio, tone)


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
        self.resize(440, 140)
        self._placed = False

        if self._bridge is not None:
            self._bridge.dry_run_updated.connect(self.set_command_text)
            if self._bridge.state.dry_run_command_text:
                self.set_command_text(self._bridge.state.dry_run_command_text)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        screen = QGuiApplication.primaryScreen()
        if screen is not None and not self._placed:
            self._placed = True
            area = screen.availableGeometry()
            self.move(area.left() + 16, area.bottom() - self.height() - 16)

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
        prefix = "Üretilecek komut: "
        line(self._current_command_text.removeprefix(prefix), box.top() + 34.0, theme.bold(), theme.TEXT)
        y = box.top() + 62.0
        for item in reversed(self._history[:-1][-2:]):
            line(item.removeprefix(prefix), y, theme.font(11), theme.MUTED)
            y += 20.0


# Alias for convenience
FeedbackOverlay = FeedbackToast
