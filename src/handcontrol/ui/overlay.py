"""Click-through windows over the desktop: mode wheel and window menu, status pill, cursor ring and command toast."""
from __future__ import annotations

import math
from typing import Callable, Optional

from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, Qt, QTimer, Slot
from PySide6.QtGui import QColor, QCursor, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from handcontrol.ui import icons, theme
from handcontrol.ui.dpi import physical_to_logical
from handcontrol.ui.painted import ClickThroughWindow
from handcontrol.ui.viewmodel import (
    COMMAND_TOAST_MS,
    CursorFeedbackState,
    command_label_tr,
    IndicatorKind,
    IndicatorState,
    OverlayMenuItem,
    OverlayMenuKind,
    OverlayState,
    UiBridge,
    VirtualCursorState,
)

_INDICATOR_COLORS: dict[IndicatorKind, QColor] = {
    IndicatorKind.PAUSED: QColor(theme.WARNING),
    IndicatorKind.NO_TRACKING: QColor(theme.DANGER),
    IndicatorKind.PENDING: QColor(theme.ACCENT),
    IndicatorKind.ENGAGED: QColor(theme.SUCCESS),
    IndicatorKind.PARKED: QColor(theme.MUTED),
}
_INDICATOR_ICONS: dict[IndicatorKind, str] = {
    IndicatorKind.PAUSED: "pause",
    IndicatorKind.NO_TRACKING: "camera_off",
    IndicatorKind.PENDING: "timer",
    IndicatorKind.ENGAGED: "pointer",
    IndicatorKind.PARKED: "hand",
}
_WINDOW_ICONS: dict[str, str] = {
    "minimize": "minimize",
    "maximize": "maximize",
    "other_monitor": "move_monitor",
    "close": "close",
}
_LEFT = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
_CENTER = int(Qt.AlignmentFlag.AlignCenter)
_WHEEL_ICONS: dict[str, str] = {**{m.value: name for m, name in icons.MODE_ICONS.items()}, "more": "more", "back": "back"}
ANIM_TICK_MS = 16


class StatusIndicator(ClickThroughWindow):
    """Small always-on-top, click-through pill showing the one current pointer status."""

    def __init__(
        self,
        bridge: Optional[UiBridge] = None,
        enabled_fn: Optional[Callable[[], bool]] = None,
        auto_show_window: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(300, 36, parent)
        self._enabled_fn = enabled_fn
        self._auto_show_window = bool(auto_show_window)
        self._state = IndicatorState()
        if bridge is not None:
            bridge.indicator_updated.connect(self.apply_indicator)

    @property
    def indicator_state(self) -> IndicatorState:
        return self._state

    @property
    def color(self) -> QColor:
        return _INDICATOR_COLORS[self._state.kind]

    def is_enabled(self) -> bool:
        return True if self._enabled_fn is None else bool(self._enabled_fn())

    @Slot(object)
    def apply_indicator(self, state: IndicatorState) -> None:
        """Repaint only when the state changed; respect the overlay_visible setting."""
        if self._auto_show_window:
            want = self.is_enabled()
            if want != self.isVisible():
                self.setVisible(want)
        if state == self._state:
            return
        self._state = state
        self.update()

    def _paint(self, painter: QPainter, rect: QRectF) -> None:
        """Pill as wide as its text, flush with the right edge (the widget sits in the top right corner)."""
        accent = self.color
        painter.setFont(theme.bold(theme.TEXT_PX["caption"]))
        w = min(self.width() - 2.0, painter.fontMetrics().horizontalAdvance(self._state.text) + 54.0)
        box = QRectF(self.width() - w - 1.0, 2.0, w, self.height() - 4.0)
        theme.paint_glass(painter, box, box.height() / 2, alpha=0.90, blur=0)
        tile = QRectF(box.left() + 4.0, box.top() + 4.0, box.height() - 8.0, box.height() - 8.0)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.color(accent.name(), 0.20))
        painter.drawEllipse(tile)
        icons.paint(painter, _INDICATOR_ICONS[self._state.kind], tile.adjusted(5, 5, -5, -5), accent, 2.2)
        painter.setPen(QColor(theme.TEXT))
        painter.drawText(box.adjusted(tile.width() + 12.0, 0, -8.0, 0), _LEFT, self._state.text)


class OverlayWindow(ClickThroughWindow):
    """Frameless, transparent, always-on-top, non-focus, click-through overlay widget."""

    def __init__(
        self,
        bridge: Optional[UiBridge] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(480, 460, parent)
        self._overlay_state = OverlayState()
        self._hover: dict[str, float] = {}       # eased hover amount per item
        self._appear = 1.0
        self._still = False                      # render_to_image: no animation, final look
        self._tick_ms = 0.0
        self._clock = QElapsedTimer()
        self._clock.start()
        self._timer = QTimer(self)
        self._timer.setInterval(ANIM_TICK_MS)
        self._timer.timeout.connect(self._tick)

        if bridge is not None:
            bridge.overlay_updated.connect(self.apply_overlay_state)

    @property
    def overlay_state(self) -> OverlayState:
        return self._overlay_state

    @Slot(object)
    def apply_overlay_state(self, state: OverlayState) -> None:
        """Update the overlay state without stealing focus."""
        opened = bool(state.items) and not self._overlay_state.items
        self._overlay_state = state
        if self.isVisible():
            self._animate(opened)
        self.update()

    # ---------- transitions (painting only; the state itself changes at once) ----------

    def _animate(self, appear: bool) -> None:
        if appear:
            self._appear = 0.0
        if not self._timer.isActive() and self._moving():
            self._tick_ms = float(self._clock.elapsed())
            self._timer.start()

    def _moving(self) -> bool:
        return self._appear < 1.0 or any(abs(self._hover.get(i.item_id, 0.0) - float(i.hovered)) > 0.001
                                         for i in self._overlay_state.items)

    @Slot()
    def _tick(self) -> None:
        now = float(self._clock.elapsed())
        dt, self._tick_ms = now - self._tick_ms, now
        self._appear = min(1.0, self._appear + dt / theme.NORMAL_MS)
        step = dt / theme.FAST_MS
        for item in self._overlay_state.items:
            at, goal = self._hover.get(item.item_id, 0.0), float(item.hovered)
            self._hover[item.item_id] = min(goal, at + step) if goal > at else max(goal, at - step)
        self.update()
        if not self._moving() or not self.isVisible():
            self._timer.stop()

    def _hover_of(self, item: OverlayMenuItem) -> float:
        if self._still or not self.isVisible():
            return float(item.hovered)
        t = self._hover.get(item.item_id, 0.0)
        return t * t * (3.0 - 2.0 * t)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._hover = {i.item_id: float(i.hovered) for i in self._overlay_state.items}
        self._animate(True)

    def render_to_image(self, width: int = 480, height: int = 360) -> QImage:
        self._still = True
        image = super().render_to_image(width, height)
        self._still = False
        return image

    def _paint(self, painter: QPainter, rect: QRectF) -> None:
        appear = 1.0 if self._still or not self.isVisible() else 1.0 - (1.0 - self._appear) ** 3
        painter.setOpacity(appear)
        scale = 0.94 + 0.06 * appear
        if scale < 0.999:
            cx, cy = rect.center().x(), rect.center().y()
            painter.translate(cx, cy)
            painter.scale(scale, scale)
            painter.translate(-cx, -cy)

        if self._overlay_state.kind is OverlayMenuKind.MODE_MENU:
            self._paint_wheel(painter, rect)
            return

        state = self._overlay_state
        panel = rect.adjusted(16.0, 16.0, -16.0, -16.0)
        theme.paint_glass(painter, panel, 18.0, alpha=0.93, blur=14)

        painter.setFont(theme.bold(15, True))
        painter.setPen(QColor(theme.TEXT))
        header = QRectF(panel.left() + 18.0, panel.top() + 10.0, panel.width() - 36.0, 26.0)
        painter.drawText(header, _LEFT, state.title or "Menü Katmanı")
        left_ms = state.timeout_ms - state.inactivity_ms
        painter.setFont(theme.font(11))
        painter.setPen(QColor(theme.MUTED))
        painter.drawText(header, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                         f"Kapanma: {max(0.0, left_ms / 1000.0):.1f} sn")

        rows = QRectF(panel.left() + 16.0, header.bottom() + 10.0, panel.width() - 32.0, 0.0)
        rows.setHeight(max(60.0, panel.bottom() - 26.0 - rows.top()))
        row_h = rows.height() / max(1, len(state.items))
        for i, item in enumerate(state.items):
            self._draw_menu_item(painter, QRectF(rows.left(), rows.top() + i * row_h, rows.width(),
                                                 max(1.0, row_h - 8.0)), item)
        theme.paint_bar(painter, QRectF(rows.left(), panel.bottom() - 15.0, rows.width(), 4.0),
                        max(0.0, min(1.0, left_ms / max(1.0, state.timeout_ms))), theme.ACCENT)
        if state.cursor.visible:
            self._draw_virtual_cursor(painter, rows if state.items else panel, state.cursor)

    def _paint_wheel(self, painter: QPainter, rect: QRectF) -> None:
        """Mode wheel: slice i is centred i/n of a turn clockwise from the top (mode_wheel.py)."""
        state = self._overlay_state
        c = rect.center()
        outer = min(rect.width(), rect.height()) / 2.0 - 18.0
        inner = outer * 0.36
        if not state.items:                              # V is being held: only the filling ring
            theme.paint_glass(painter, QRectF(c.x() - 42.0, c.y() - 42.0, 84.0, 84.0), 42.0, alpha=0.92, blur=12)
            theme.paint_ring(painter, c, 32.0, state.cursor.hold_progress, theme.ACCENT, 5.0)
            painter.setFont(theme.bold(24, True))
            painter.setPen(QColor(theme.TEXT))
            painter.drawText(QRectF(c.x() - 30.0, c.y() - 30.0, 60.0, 60.0), _CENTER, "V")
            return
        disc = QRectF(c.x() - outer, c.y() - outer, 2 * outer, 2 * outer)
        theme.paint_shadow(painter, disc, outer, 16, 0.5, 1.0)
        ring = QPainterPath()
        ring.addEllipse(c, outer, outer)
        ring.addEllipse(c, inner, inner)                 # odd-even fill: a donut
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.color(theme.SURFACE, 0.93))
        painter.drawPath(ring)
        painter.setPen(QPen(theme.color(theme.WHITE, 0.14), 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(disc.adjusted(0.5, 0.5, -0.5, -0.5))
        step = 360.0 / len(state.items)
        painter.setPen(QPen(theme.color(theme.WHITE, 0.10), 1.0))
        for i in range(len(state.items)):
            a = math.radians((i + 0.5) * step)
            painter.drawLine(QPointF(c.x() + (inner + 10) * math.sin(a), c.y() - (inner + 10) * math.cos(a)),
                             QPointF(c.x() + (outer - 12) * math.sin(a), c.y() - (outer - 12) * math.cos(a)))
        for i, item in enumerate(state.items):
            hot = self._hover_of(item)
            r = outer + 10.0 * hot
            start = 90.0 - (i - 0.5) * step - 1.2        # Qt: degrees counter-clockwise from 3 o'clock
            span = -(step - 2.4)
            if hot > 0.0 or item.active:
                path = QPainterPath()
                path.arcMoveTo(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r), start)
                path.arcTo(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r), start, span)
                path.arcTo(QRectF(c.x() - inner, c.y() - inner, 2 * inner, 2 * inner), start + span, -span)
                path.closeSubpath()
                pen = QPen(theme.color(theme.ACCENT, hot), 4.0)     # rounds the slice corners
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                painter.setPen(pen if hot > 0.0 else Qt.PenStyle.NoPen)
                painter.setBrush(theme.mix(theme.color(theme.ACCENT, 0.14 if item.active else 0.0), theme.ACCENT, hot))
                painter.drawPath(path)
            if item.active:
                rim = outer - 4.0
                pen = QPen(theme.mix(theme.ACCENT, theme.ON_ACCENT, hot), 3.0)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                painter.drawArc(QRectF(c.x() - rim, c.y() - rim, 2 * rim, 2 * rim), int((start - step * 0.3) * 16),
                                int((span + step * 0.6) * 16))
            a = math.radians(i * step)
            mid = (inner + r) / 2.0
            at = QPointF(c.x() + mid * math.sin(a), c.y() - mid * math.cos(a))
            size = 30.0 + 4.0 * hot
            icon = QRectF(at.x() - size / 2, at.y() - size / 2 - 11.0, size, size)
            base = theme.FAINT if not item.enabled else theme.ACCENT_TEXT if item.active else theme.TEXT
            tone = theme.mix(base, theme.ON_ACCENT, hot)
            icons.paint(painter, _WHEEL_ICONS.get(item.item_id, "info"), icon, tone)
            painter.setFont(theme.bold(theme.TEXT_PX["body"]) if hot > 0.5 else theme.font(theme.TEXT_PX["body"]))
            painter.setPen(tone)
            painter.drawText(QRectF(at.x() - 60.0, icon.bottom() + 4.0, 120.0, 20.0), _CENTER, item.label)
        hub = inner - 6.0
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.color(theme.BG, 0.95))
        painter.drawEllipse(c, hub, hub)
        left = 1.0 - state.inactivity_ms / max(1.0, state.timeout_ms)
        theme.paint_ring(painter, c, hub - 2.0, left, theme.ACCENT, 3.0)
        hovered = next((i.label for i in state.items if i.hovered), "")
        if hovered:
            painter.setFont(theme.bold(theme.TEXT_PX["body"]))
            painter.setPen(QColor(theme.TEXT))
            painter.drawText(QRectF(c.x() - hub, c.y() - hub, 2 * hub, 2 * hub), _CENTER, "Yumruk: seç")
        else:                                            # around the resting cursor dot in the middle
            icons.paint(painter, "hand", QRectF(c.x() - 12.0, c.y() - hub * 0.68, 24.0, 24.0), theme.ACCENT_TEXT)
            painter.setFont(theme.font(theme.TEXT_PX["caption"]))
            painter.setPen(QColor(theme.TEXT_SOFT))
            painter.drawText(QRectF(c.x() - hub * 0.7, c.y() + 10.0, hub * 1.4, 40.0),
                             int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap),
                             "Elini bir dilime götür")
        cursor = state.cursor
        if cursor.visible:
            at = QPointF(c.x() + (cursor.x - 0.5) * 2 * outer, c.y() + (cursor.y - 0.5) * 2 * outer)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme.color(theme.INK, 0.45))
            painter.drawEllipse(at, 11.0, 11.0)
            painter.setPen(QPen(QColor(theme.INK), 2.0))
            painter.setBrush(QColor(theme.WHITE))
            painter.drawEllipse(at, 7.0, 7.0)

    def _draw_menu_item(
        self,
        painter: QPainter,
        item_rect: QRectF,
        item: OverlayMenuItem,
    ) -> None:
        is_close = item.item_id == "close"
        hot = self._hover_of(item) if item.enabled else 0.0
        danger = is_close and (item.armed or item.hold_progress > 0.0)
        tone = theme.DANGER if danger else theme.ACCENT
        level = 1.0 if danger else hot
        painter.setPen(QPen(theme.mix(theme.color(theme.WHITE, 0.08), theme.color(tone, 0.85), level), 1.0 + 0.4 * level))
        painter.setBrush(theme.mix(theme.color(theme.WHITE, 0.05 if item.enabled else 0.02), theme.color(tone, 0.20),
                                   level))
        painter.drawRoundedRect(item_rect, theme.RADIUS_L, theme.RADIUS_L)

        mark = theme.mix(QColor(theme.TEXT_SOFT if item.enabled else theme.FAINT), tone, level)
        icons.paint(painter, _WINDOW_ICONS.get(item.item_id, "windows"),
                    QRectF(item_rect.left() + 16.0, item_rect.center().y() - 11.0, 22.0, 22.0), mark)
        strong = item.hovered or item.armed
        painter.setFont(theme.bold(theme.TEXT_PX["section"]) if strong else theme.font(theme.TEXT_PX["section"]))
        painter.setPen(QColor(theme.TEXT if item.enabled else theme.FAINT))
        painter.drawText(item_rect.adjusted(52.0, 0.0, -54.0, 0.0), _LEFT, item.label)
        if is_close:                                     # fills while the pinch confirms the close
            theme.paint_ring(painter, QPointF(item_rect.right() - 28.0, item_rect.center().y()),
                             min(13.0, item_rect.height() * 0.34), item.hold_progress, theme.DANGER, 3.0)

    def _draw_virtual_cursor(self, painter: QPainter, bounds: QRectF, cursor: VirtualCursorState) -> None:
        at = QPointF(bounds.left() + cursor.x * bounds.width(), bounds.top() + cursor.y * bounds.height())
        ring = QColor(theme.WHITE)
        for pen, brush, r in ((QPen(theme.color(theme.INK, 0.5), 4.5), Qt.BrushStyle.NoBrush, 16.0),    # readable on light rows too
                              (QPen(ring, 2.2), theme.color(ring.name(), 0.16), 16.0),
                              (Qt.PenStyle.NoPen, ring, 3.5)):
            painter.setPen(pen)
            painter.setBrush(brush)
            painter.drawEllipse(at, r, r)
        if cursor.hold_progress > 0.0:
            theme.paint_ring(painter, at, 21.0, cursor.hold_progress, theme.WARNING, 2.8, theme.color(theme.WHITE, 0.0))


HOLD_KIND_COLORS: dict[str, QColor] = {
    "right_click": QColor(theme.WARNING),
    "grab": QColor(theme.ACCENT),
    "fist": QColor(theme.DANGER),
    "dwell": QColor(theme.SUCCESS),
    "window_drag": QColor(theme.AREA),
}
_DEFAULT_HOLD_COLOR = QColor(theme.ACCENT)

RING_TICK_MS = 16            # ~60 Hz animation between 20 FPS snapshots
RING_SMOOTH_TAU_MS = 45.0    # display progress follows target with this time constant
RING_GRACE_MS = 140.0        # keep ring through brief progress dropouts (no flicker)
RING_FADE_MS = 180.0         # fade-out after the hold ends
TOAST_FADE_MS = 200.0


class CursorFeedbackOverlay(ClickThroughWindow):
    """Click-through window that follows the cursor: hold progress ring + command toast.

    Feed it via UiBridge (cursor_feedback_updated / command_triggered) or call
    apply_feedback() / show_command() directly. `enabled_fn` (e.g. settings.cursor_feedback)
    hides the ring only; command toasts stay. With follow_os_cursor=True the window tracks
    QCursor.pos() every tick (smooth in live mode); otherwise it uses the snapshot pointer.
    """

    WIDTH = 280
    HEIGHT = 150
    ANCHOR = QPointF(140.0, 40.0)          # cursor hotspot inside the window
    RING_OFFSET = QPointF(28.0, 26.0)       # ring center relative to the hotspot
    RING_RADIUS = 13.0

    def __init__(
        self,
        bridge: Optional[UiBridge] = None,
        enabled_fn: Optional[Callable[[], bool]] = None,
        follow_os_cursor: bool = True,
        auto_show_window: bool = True,
        toast_ms: int = COMMAND_TOAST_MS,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(self.WIDTH, self.HEIGHT, parent)
        self._enabled_fn = enabled_fn
        self._follow_os_cursor = bool(follow_os_cursor)
        self._auto_show_window = bool(auto_show_window)
        self._toast_ms = max(100, int(toast_ms))
        self._clock = QElapsedTimer()
        self._clock.start()

        self._feedback = CursorFeedbackState()
        self._kind = ""
        self._target = 0.0
        self._display = 0.0
        self._last_active_ms = -1e9
        self._fade_start_ms: Optional[float] = None
        self._ring_opacity = 0.0
        self._last_tick_ms = 0.0
        self._toast_text = ""
        self._toast_start_ms = -1e9

        self._timer = QTimer(self)
        self._timer.setInterval(RING_TICK_MS)
        self._timer.timeout.connect(self._tick)

        if bridge is not None:
            bridge.cursor_feedback_updated.connect(self.apply_feedback)
            bridge.command_triggered.connect(self.show_command)

    # ---------- state (read by tests and app) ----------

    @property
    def hold_kind(self) -> str:
        return self._kind

    @property
    def displayed_progress(self) -> float:
        return self._display

    @property
    def ring_visible(self) -> bool:
        return self._ring_opacity > 0.001 and self.is_enabled()

    @property
    def ring_color(self) -> QColor:
        return QColor(HOLD_KIND_COLORS.get(self._kind, _DEFAULT_HOLD_COLOR))

    @property
    def toast_text(self) -> str:
        return self._toast_text if self.toast_visible else ""

    @property
    def toast_visible(self) -> bool:
        return bool(self._toast_text) and self._now() - self._toast_start_ms < self._toast_ms

    @property
    def is_animating(self) -> bool:
        return self._timer.isActive()

    def is_enabled(self) -> bool:
        return True if self._enabled_fn is None else bool(self._enabled_fn())

    def _now(self) -> float:
        return float(self._clock.elapsed())

    # ---------- inputs ----------

    @Slot(object)
    def apply_feedback(self, state: CursorFeedbackState) -> None:
        """New hold state from the controller (about 20 per second)."""
        self._feedback = state
        now = self._now()
        if state.progress > 0.0 and self.is_enabled():
            if state.kind != self._kind:
                self._kind = state.kind          # a different hold starts from empty
                self._display = 0.0
            elif state.progress < self._display - 0.25:
                self._display = state.progress   # same kind restarted: no backwards sweep
            self._target = state.progress
            self._last_active_ms = now
            self._fade_start_ms = None
            self._ring_opacity = 1.0
        else:
            self._target = 0.0
        if not (self._timer.isActive() or self._needs_running(state)):
            return                                        # idle pointer move: stay hidden, no timer
        self._place()
        self._ensure_running()
        self._tick()

    def _needs_running(self, state: CursorFeedbackState) -> bool:
        return (state.progress > 0.0 and self.is_enabled()) or self._ring_opacity > 0.0 or self.toast_visible

    @Slot(str)
    def show_command(self, command: str) -> None:
        """Show the Turkish command label (Sonraki, Görev görünümü, ...) for ~900 ms."""
        text = command_label_tr(command)
        if not text:
            return
        self._toast_text = text
        self._toast_start_ms = self._now()
        self._place()
        self._ensure_running()
        self._tick()

    # ---------- animation ----------

    def _ensure_running(self) -> None:
        if not self._timer.isActive():
            self._last_tick_ms = self._now()
            self._timer.start()
        if self._auto_show_window and not self.isVisible():
            self.show()

    def _place(self) -> None:
        if self._follow_os_cursor:
            pos = QCursor.pos()
        elif self._feedback.x is not None and self._feedback.y is not None:
            pos = physical_to_logical(self._feedback.x, self._feedback.y)
        else:
            return
        self.move(round(pos.x() - self.ANCHOR.x()), round(pos.y() - self.ANCHOR.y()))

    @Slot()
    def _tick(self) -> None:
        now = self._now()
        dt = max(0.0, now - self._last_tick_ms)
        self._last_tick_ms = now
        if self._target > 0.0:
            alpha = 1.0 - math.exp(-dt / RING_SMOOTH_TAU_MS) if dt > 0 else 0.0
            self._display += (self._target - self._display) * alpha
            if self._target >= 1.0 and self._display > 0.98:
                self._display = 1.0
        elif self._ring_opacity > 0.0:
            if now - self._last_active_ms >= RING_GRACE_MS:   # a brief dropout holds the ring as is
                if self._fade_start_ms is None:
                    self._fade_start_ms = now
                    if self._display >= 0.9:
                        self._display = 1.0               # completed hold: finish the circle
                self._ring_opacity = max(0.0, 1.0 - (now - self._fade_start_ms) / RING_FADE_MS)
                if self._ring_opacity <= 0.0:
                    self._display = 0.0
                    self._kind = ""
                    self._fade_start_ms = None
        if not self.is_enabled():
            self._ring_opacity = 0.0
        if self._follow_os_cursor and (self._ring_opacity > 0.0 or self.toast_visible):
            self._place()
        self.update()
        if self._ring_opacity <= 0.0 and not self.toast_visible:
            self._timer.stop()
            if self._auto_show_window and self.isVisible():
                self.hide()

    # ---------- painting ----------

    def _paint(self, painter: QPainter, rect: QRectF) -> None:
        if self.ring_visible and self._display > 0.0:
            self._paint_ring(painter)
        if self.toast_visible:
            self._paint_toast(painter)

    def _paint_ring(self, painter: QPainter) -> None:
        c = self.ANCHOR + self.RING_OFFSET
        r = self.RING_RADIUS
        box = QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)
        painter.setOpacity(self._ring_opacity)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(theme.color(theme.INK, 0.55), 7.0))       # contrast halo on light backgrounds
        painter.drawEllipse(box)
        theme.paint_ring(painter, c, r, self._display, self.ring_color, 3.2, theme.color(theme.WHITE, 0.28))
        painter.setOpacity(1.0)

    def _paint_toast(self, painter: QPainter) -> None:
        left = self._toast_ms - (self._now() - self._toast_start_ms)
        opacity = max(0.0, min(1.0, left / TOAST_FADE_MS))
        painter.setFont(theme.bold(theme.TEXT_PX["section"]))
        text_w = painter.fontMetrics().horizontalAdvance(self._toast_text)
        w = min(self.WIDTH - 24.0, text_w + 36.0)
        box = QRectF(self.ANCHOR.x() - w / 2.0, self.ANCHOR.y() + 52.0, w, 34.0)
        painter.setOpacity(opacity)
        theme.paint_glass(painter, box, 17.0, alpha=0.93, blur=10)
        painter.setPen(QColor(theme.TEXT))
        painter.drawText(box, _CENTER, self._toast_text)
        painter.setOpacity(1.0)

