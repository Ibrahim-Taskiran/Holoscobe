"""Transparent, frameless, always-on-top, non-focus-stealing, click-through overlay
for the Mode Menu and Window Action Menu.

Features:
- Custom virtual cursor rendered via QPainter.
- 1-second (1,000 ms) visible progress ring for the Close ("Kapat") action.
- 5-second (5,000 ms) inactivity closing animation driven by external timing.
"""
from __future__ import annotations

import math
from dataclasses import replace
from typing import Callable, Optional

from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, Qt, QTimer, Slot
from PySide6.QtGui import QColor, QCursor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget

from handcontrol.contracts import Mode
from handcontrol.ui.dpi import physical_to_logical
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
    WindowActionKind,
    create_mode_menu_items,
    create_window_action_menu_items,
)

CLOSE_HOLD_DURATION_MS: float = 1000.0
INACTIVITY_TIMEOUT_MS: float = 5000.0
CLOSING_ANIMATION_SPAN_MS: float = 1000.0


def compute_closing_progress(
    inactivity_ms: float,
    timeout_ms: float = INACTIVITY_TIMEOUT_MS,
    animation_span_ms: float = CLOSING_ANIMATION_SPAN_MS,
) -> float:
    """Compute [0.0, 1.0] closing animation progress from external inactivity timing.

    Animation begins during the final `animation_span_ms` before `timeout_ms`
    (e.g., from 4,000 ms to 5,000 ms for a 5-second timeout).
    """
    if timeout_ms <= 0.0:
        return 1.0
    if inactivity_ms >= timeout_ms:
        return 1.0
    start_ms = max(0.0, timeout_ms - max(1.0, animation_span_ms))
    if inactivity_ms <= start_ms:
        return 0.0
    return max(0.0, min(1.0, (inactivity_ms - start_ms) / (timeout_ms - start_ms)))


def build_mode_overlay_state(
    active_mode: Mode = Mode.POINTER,
    hovered_mode: Optional[Mode] = None,
    hold_progress: float = 0.0,
    cursor: Optional[VirtualCursorState] = None,
    inactivity_ms: float = 0.0,
    timeout_ms: float = INACTIVITY_TIMEOUT_MS,
) -> OverlayState:
    """Construct an OverlayState for the Mode Menu."""
    closing = compute_closing_progress(inactivity_ms, timeout_ms)
    return OverlayState(
        visible=closing < 1.0,
        kind=OverlayMenuKind.MODE_MENU,
        title="Mod Seçimi Menüsü",
        items=create_mode_menu_items(
            active_mode=active_mode,
            hovered_mode=hovered_mode,
            hold_progress=hold_progress,
        ),
        cursor=cursor or VirtualCursorState(x=0.5, y=0.5, visible=True),
        inactivity_ms=float(inactivity_ms),
        timeout_ms=float(timeout_ms),
        closing_progress=closing,
    )


def build_window_action_overlay_state(
    hovered_action: Optional[WindowActionKind] = None,
    close_armed: bool = False,
    close_hold_progress: float = 0.0,
    multi_monitor: bool = True,
    cursor: Optional[VirtualCursorState] = None,
    inactivity_ms: float = 0.0,
    timeout_ms: float = INACTIVITY_TIMEOUT_MS,
    target_window_title: str = "",
) -> OverlayState:
    """Construct an OverlayState for the Window Action Menu."""
    closing = compute_closing_progress(inactivity_ms, timeout_ms)
    return OverlayState(
        visible=closing < 1.0,
        kind=OverlayMenuKind.WINDOW_ACTION_MENU,
        title="Pencere Eylemleri",
        items=create_window_action_menu_items(
            hovered_action=hovered_action,
            close_armed=close_armed,
            close_hold_progress=close_hold_progress,
            multi_monitor=multi_monitor,
        ),
        cursor=cursor or VirtualCursorState(x=0.5, y=0.5, visible=True),
        inactivity_ms=float(inactivity_ms),
        timeout_ms=float(timeout_ms),
        closing_progress=closing,
        target_window_title=target_window_title,
    )


_INDICATOR_COLORS: dict[IndicatorKind, QColor] = {
    IndicatorKind.PAUSED: QColor(241, 196, 15),
    IndicatorKind.NO_TRACKING: QColor(231, 76, 60),
    IndicatorKind.PENDING: QColor(52, 152, 219),
    IndicatorKind.ENGAGED: QColor(46, 204, 113),
    IndicatorKind.PARKED: QColor(149, 165, 166),
}
_INDICATOR_GLYPHS: dict[IndicatorKind, str] = {
    IndicatorKind.PAUSED: "||",
    IndicatorKind.NO_TRACKING: "X",
    IndicatorKind.PENDING: "...",
    IndicatorKind.ENGAGED: "+",
    IndicatorKind.PARKED: "o",
}


class StatusIndicator(QWidget):
    """Small always-on-top, click-through pill showing the one current pointer status."""

    def __init__(
        self,
        bridge: Optional[UiBridge] = None,
        enabled_fn: Optional[Callable[[], bool]] = None,
        auto_show_window: bool = False,
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
        self._enabled_fn = enabled_fn
        self._auto_show_window = bool(auto_show_window)
        self._state = IndicatorState()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.resize(300, 36)
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

    def render_to_image(self) -> QImage:
        image = QImage(self.width(), self.height(), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        self._paint(painter)
        painter.end()
        return image

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        self._paint(painter)
        painter.end()

    def _paint(self, painter: QPainter) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        accent = self.color
        box = QRectF(2.0, 2.0, self.width() - 4.0, self.height() - 4.0)
        painter.setPen(QPen(accent, 2.0))
        painter.setBrush(QColor(20, 26, 36, 220))
        painter.drawRoundedRect(box, 16.0, 16.0)
        font = QFont("Segoe UI", 10)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(accent)
        painter.drawText(
            QRectF(box.left() + 10.0, box.top(), 30.0, box.height()),
            int(Qt.AlignmentFlag.AlignCenter),
            _INDICATOR_GLYPHS[self._state.kind],
        )
        painter.setPen(QColor(240, 245, 250))
        painter.drawText(
            QRectF(box.left() + 44.0, box.top(), box.width() - 54.0, box.height()),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            self._state.text,
        )


class OverlayWindow(QWidget):
    """Frameless, transparent, always-on-top, non-focus, click-through overlay widget."""

    def __init__(
        self,
        bridge: Optional[UiBridge] = None,
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

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.resize(480, 360)

        self._overlay_state: OverlayState = build_mode_overlay_state()
        self._last_drawn_close_progress: float = 0.0
        self._last_drawn_cursor_visible: bool = False

        if self._bridge is not None:
            self._bridge.overlay_updated.connect(self.apply_overlay_state)

    @property
    def overlay_state(self) -> OverlayState:
        return self._overlay_state

    @property
    def virtual_cursor(self) -> VirtualCursorState:
        return self._overlay_state.cursor

    @property
    def inactivity_ms(self) -> float:
        return self._overlay_state.inactivity_ms

    @property
    def timeout_ms(self) -> float:
        return self._overlay_state.timeout_ms

    @property
    def closing_progress(self) -> float:
        return self._overlay_state.closing_progress

    @property
    def is_expired(self) -> bool:
        return self._overlay_state.is_expired

    @property
    def effective_opacity(self) -> float:
        return max(0.0, min(1.0, 1.0 - self._overlay_state.closing_progress))

    @property
    def effective_scale(self) -> float:
        return max(0.80, min(1.0, 1.0 - 0.15 * self._overlay_state.closing_progress))

    @property
    def close_hold_progress(self) -> float:
        """Return [0.0, 1.0] 1-second hold progress for the Close item."""
        for item in self._overlay_state.items:
            if item.item_id == WindowActionKind.CLOSE.value:
                return item.hold_progress
        return 0.0

    @Slot(object)
    def apply_overlay_state(self, state: OverlayState) -> None:
        """Update the overlay state without stealing focus."""
        self._overlay_state = state
        self.update()

    def configure_mode_menu(
        self,
        active_mode: Mode = Mode.POINTER,
        hovered_mode: Optional[Mode] = None,
        hold_progress: float = 0.0,
        cursor: Optional[VirtualCursorState] = None,
        inactivity_ms: float = 0.0,
        timeout_ms: float = INACTIVITY_TIMEOUT_MS,
    ) -> OverlayState:
        """Configure the overlay to display the Mode Menu."""
        state = build_mode_overlay_state(
            active_mode=active_mode,
            hovered_mode=hovered_mode,
            hold_progress=hold_progress,
            cursor=cursor or self._overlay_state.cursor,
            inactivity_ms=inactivity_ms,
            timeout_ms=timeout_ms,
        )
        self.apply_overlay_state(state)
        return state

    def configure_window_action_menu(
        self,
        hovered_action: Optional[WindowActionKind] = None,
        close_armed: bool = False,
        close_hold_progress: float = 0.0,
        multi_monitor: bool = True,
        cursor: Optional[VirtualCursorState] = None,
        inactivity_ms: float = 0.0,
        timeout_ms: float = INACTIVITY_TIMEOUT_MS,
        target_window_title: str = "",
    ) -> OverlayState:
        """Configure the overlay to display the Window Action Menu."""
        state = build_window_action_overlay_state(
            hovered_action=hovered_action,
            close_armed=close_armed,
            close_hold_progress=close_hold_progress,
            multi_monitor=multi_monitor,
            cursor=cursor or self._overlay_state.cursor,
            inactivity_ms=inactivity_ms,
            timeout_ms=timeout_ms,
            target_window_title=target_window_title,
        )
        self.apply_overlay_state(state)
        return state

    def set_virtual_cursor(
        self,
        x: float,
        y: float,
        visible: bool = True,
        pinching: bool = False,
        hold_progress: float = 0.0,
    ) -> None:
        """Set virtual cursor coordinates (normalized [0, 1]) and state."""
        cursor = VirtualCursorState(
            x=max(0.0, min(1.0, float(x))),
            y=max(0.0, min(1.0, float(y))),
            visible=bool(visible),
            pinching=bool(pinching),
            hold_progress=max(0.0, min(1.0, float(hold_progress))),
        )
        self._overlay_state = replace(self._overlay_state, cursor=cursor)
        self.update()

    def set_close_hold_progress(
        self,
        progress: float,
        armed: bool = True,
    ) -> None:
        """Update the 1-second Close confirmation ring progress in [0.0, 1.0]."""
        clamped = max(0.0, min(1.0, float(progress)))
        new_items: list[OverlayMenuItem] = []
        for item in self._overlay_state.items:
            if item.item_id == WindowActionKind.CLOSE.value:
                label = "Kapat (1 sn Basılı Tutun)" if armed else "Kapat"
                new_items.append(
                    replace(
                        item,
                        label=label,
                        armed=armed,
                        hovered=True if clamped > 0.0 else item.hovered,
                        hold_progress=clamped,
                    )
                )
            else:
                new_items.append(item)
        self._overlay_state = replace(self._overlay_state, items=tuple(new_items))
        self.update()

    def set_close_hold_ms(
        self,
        elapsed_ms: float,
        total_ms: float = CLOSE_HOLD_DURATION_MS,
        armed: bool = True,
    ) -> None:
        """Update Close confirmation ring progress from elapsed milliseconds (1,000 ms default)."""
        ratio = 1.0 if total_ms <= 0.0 else max(0.0, min(1.0, elapsed_ms / total_ms))
        self.set_close_hold_progress(ratio, armed=armed)

    def set_inactivity_time(
        self,
        inactivity_ms: float,
        timeout_ms: float = INACTIVITY_TIMEOUT_MS,
    ) -> None:
        """Update inactivity elapsed time from external clock and compute closing animation."""
        closing = compute_closing_progress(inactivity_ms, timeout_ms)
        self._overlay_state = replace(
            self._overlay_state,
            inactivity_ms=max(0.0, float(inactivity_ms)),
            timeout_ms=max(1.0, float(timeout_ms)),
            closing_progress=closing,
            visible=(closing < 1.0),
        )
        self.update()

    def render_to_image(self, width: int = 480, height: int = 360) -> QImage:
        """Render the overlay into an offscreen ARGB32 QImage for verification."""
        self.resize(width, height)
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        self._paint_overlay(painter, QRectF(0.0, 0.0, float(width), float(height)))
        painter.end()
        return image

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        self._paint_overlay(
            painter,
            QRectF(0.0, 0.0, float(self.width()), float(self.height())),
        )
        painter.end()

    def _paint_overlay(self, painter: QPainter, rect: QRectF) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._last_drawn_close_progress = 0.0
        self._last_drawn_cursor_visible = False

        opacity = self.effective_opacity
        if opacity <= 0.001:
            return

        painter.setOpacity(opacity)
        scale = self.effective_scale
        if scale < 0.999:
            cx, cy = rect.center().x(), rect.center().y()
            painter.translate(cx, cy)
            painter.scale(scale, scale)
            painter.translate(-cx, -cy)

        panel_rect = rect.adjusted(16.0, 16.0, -16.0, -16.0)
        painter.setPen(QPen(QColor(86, 152, 224, 210), 2.0))
        painter.setBrush(QColor(18, 24, 34, 225))
        painter.drawRoundedRect(panel_rect, 14.0, 14.0)

        # Header
        title_font = QFont("Segoe UI", 11)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor(235, 242, 250))

        title = self._overlay_state.title or "Menü Katmanı"
        if self._overlay_state.target_window_title:
            title = f"{title} — {self._overlay_state.target_window_title}"

        header_rect = QRectF(panel_rect.left() + 14.0, panel_rect.top() + 10.0, panel_rect.width() - 28.0, 26.0)
        painter.drawText(
            header_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            title,
        )

        # Remaining time indicator (5-second timeout bar)
        rem_ratio = max(
            0.0,
            min(
                1.0,
                1.0 - (self._overlay_state.inactivity_ms / max(1.0, self._overlay_state.timeout_ms)),
            ),
        )
        rem_sec = max(0.0, (self._overlay_state.timeout_ms - self._overlay_state.inactivity_ms) / 1000.0)
        sub_font = QFont("Segoe UI", 8)
        painter.setFont(sub_font)
        painter.setPen(QColor(168, 184, 204))
        painter.drawText(
            header_rect,
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
            f"Kapanma: {rem_sec:.1f} sn",
        )

        # Menu Items
        items = self._overlay_state.items
        if items:
            top_y = header_rect.bottom() + 10.0
            bottom_limit = panel_rect.bottom() - 26.0
            avail_h = max(60.0, bottom_limit - top_y)
            row_h = avail_h / len(items)
            item_h = max(1.0, row_h - 8.0)

            for idx, item in enumerate(items):
                iy = top_y + idx * row_h
                item_rect = QRectF(
                    panel_rect.left() + 16.0,
                    iy,
                    panel_rect.width() - 32.0,
                    item_h,
                )
                self._draw_menu_item(painter, item_rect, item)

        # Bottom timeout bar
        bar_rect = QRectF(
            panel_rect.left() + 16.0,
            panel_rect.bottom() - 14.0,
            panel_rect.width() - 32.0,
            5.0,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(42, 52, 68))
        painter.drawRoundedRect(bar_rect, 2.5, 2.5)
        if rem_ratio > 0.0:
            bar_color = QColor(240, 148, 72) if self._overlay_state.closing_progress > 0.0 else QColor(72, 172, 242)
            painter.setBrush(bar_color)
            painter.drawRoundedRect(
                QRectF(bar_rect.left(), bar_rect.top(), bar_rect.width() * rem_ratio, bar_rect.height()),
                2.5,
                2.5,
            )

        # Draw custom virtual cursor on top
        cursor = self._overlay_state.cursor
        if cursor.visible:
            self._last_drawn_cursor_visible = True
            cursor_bounds = QRectF(panel_rect.left() + 16.0, top_y,
                                   panel_rect.width() - 32.0, avail_h) if items else panel_rect
            self._draw_virtual_cursor(painter, cursor_bounds, cursor)

    def _draw_menu_item(
        self,
        painter: QPainter,
        item_rect: QRectF,
        item: OverlayMenuItem,
    ) -> None:
        is_close = item.item_id == WindowActionKind.CLOSE.value
        if not item.enabled:
            bg = QColor(30, 35, 44, 150)
            border = QColor(65, 72, 84)
            text_color = QColor(115, 125, 138)
        elif is_close and (item.armed or item.hold_progress > 0.0):
            bg = QColor(92, 28, 34, 230)
            border = QColor(245, 98, 102)
            text_color = QColor(255, 230, 230)
        elif item.hovered:
            bg = QColor(38, 78, 122, 235)
            border = QColor(112, 198, 255)
            text_color = QColor(255, 255, 255)
        elif item.active:
            bg = QColor(28, 72, 58, 220)
            border = QColor(82, 214, 148)
            text_color = QColor(230, 255, 240)
        else:
            bg = QColor(28, 36, 48, 210)
            border = QColor(64, 82, 106)
            text_color = QColor(218, 228, 240)

        painter.setPen(QPen(border, 1.6))
        painter.setBrush(bg)
        painter.drawRoundedRect(item_rect, 8.0, 8.0)

        font = QFont("Segoe UI", 10)
        font.setBold(item.hovered or item.active or item.armed)
        painter.setFont(font)
        painter.setPen(text_color)

        label_text = item.label
        if item.active and not is_close:
            label_text = f"{label_text} (Etkin)"

        painter.drawText(
            item_rect.adjusted(14.0, 0.0, -54.0, 0.0),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            label_text,
        )

        # 1-second visible progress ring for Close ("Kapat") or item hold progress
        if is_close or item.hold_progress > 0.0 or item.armed:
            ring_r = min(14.0, item_rect.height() * 0.36)
            ring_center = QPointF(item_rect.right() - 26.0, item_rect.center().y())
            ring_box = QRectF(
                ring_center.x() - ring_r,
                ring_center.y() - ring_r,
                ring_r * 2.0,
                ring_r * 2.0,
            )
            # Track circle
            painter.setPen(QPen(QColor(80, 92, 110), 3.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(ring_box)

            prog = max(0.0, min(1.0, item.hold_progress))
            if is_close:
                self._last_drawn_close_progress = prog
            if prog > 0.0:
                arc_color = QColor(255, 92, 96) if is_close else QColor(92, 214, 255)
                arc_pen = QPen(arc_color, 3.4)
                arc_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(arc_pen)
                # Qt drawArc uses 1/16th of a degree; 90 deg is top (12 o'clock)
                start_angle = 90 * 16
                span_angle = -int(prog * 360 * 16)
                painter.drawArc(ring_box, start_angle, span_angle)

    def _draw_virtual_cursor(
        self,
        painter: QPainter,
        bounds: QRectF,
        cursor: VirtualCursorState,
    ) -> None:
        cx = bounds.left() + max(0.0, min(1.0, cursor.x)) * bounds.width()
        cy = bounds.top() + max(0.0, min(1.0, cursor.y)) * bounds.height()
        pt = QPointF(cx, cy)

        outer_r = 13.0 if cursor.pinching else 16.0
        ring_color = QColor(88, 238, 168) if cursor.pinching else QColor(112, 206, 255)

        painter.setPen(QPen(ring_color, 2.2))
        painter.setBrush(QColor(ring_color.red(), ring_color.green(), ring_color.blue(), 55))
        painter.drawEllipse(pt, outer_r, outer_r)

        # Center dot
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255))
        painter.drawEllipse(pt, 3.5, 3.5)

        # Optional hold progress arc around virtual cursor
        if cursor.hold_progress > 0.0:
            arc_r = outer_r + 5.0
            arc_box = QRectF(cx - arc_r, cy - arc_r, arc_r * 2.0, arc_r * 2.0)
            painter.setPen(QPen(QColor(255, 198, 88), 2.8))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawArc(arc_box, 90 * 16, -int(max(0.0, min(1.0, cursor.hold_progress)) * 360 * 16))


HOLD_KIND_COLORS: dict[str, QColor] = {
    "right_click": QColor(255, 159, 67),
    "grab": QColor(72, 172, 242),
    "fist": QColor(236, 94, 104),
    "dwell": QColor(88, 238, 168),
    "window_drag": QColor(178, 132, 255),
}
_DEFAULT_HOLD_COLOR = QColor(255, 198, 88)

RING_TICK_MS = 16            # ~60 Hz animation between 20 FPS snapshots
RING_SMOOTH_TAU_MS = 45.0    # display progress follows target with this time constant
RING_GRACE_MS = 140.0        # keep ring through brief progress dropouts (no flicker)
RING_FADE_MS = 180.0         # fade-out after the hold ends
TOAST_FADE_MS = 200.0


class CursorFeedbackOverlay(QWidget):
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
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowTransparentForInput
        )
        super().__init__(parent, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.resize(self.WIDTH, self.HEIGHT)

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
    def target_progress(self) -> float:
        return self._target

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
            if now - self._last_active_ms < RING_GRACE_MS:
                pass                                      # brief dropout: hold the ring as is
            else:
                if self._fade_start_ms is None:
                    self._fade_start_ms = now
                    if self._display >= 0.9:
                        self._display = 1.0               # completed hold: finish the circle
                k = (now - self._fade_start_ms) / RING_FADE_MS
                self._ring_opacity = max(0.0, 1.0 - k)
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

    def render_to_image(self) -> QImage:
        image = QImage(self.width(), self.height(), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        self._paint(painter)
        painter.end()
        return image

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        self._paint(painter)
        painter.end()

    def _paint(self, painter: QPainter) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
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
        painter.setPen(QPen(QColor(0, 0, 0, 110), 6.0))       # contrast halo on light backgrounds
        painter.drawEllipse(box)
        painter.setPen(QPen(QColor(255, 255, 255, 70), 3.0))  # empty track
        painter.drawEllipse(box)
        pen = QPen(self.ring_color, 3.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(box, 90 * 16, -int(max(0.0, min(1.0, self._display)) * 360 * 16))
        painter.setOpacity(1.0)

    def _paint_toast(self, painter: QPainter) -> None:
        left = self._toast_ms - (self._now() - self._toast_start_ms)
        opacity = max(0.0, min(1.0, left / TOAST_FADE_MS))
        font = QFont("Segoe UI", 11)
        font.setBold(True)
        painter.setFont(font)
        text_w = painter.fontMetrics().horizontalAdvance(self._toast_text)
        w = min(self.WIDTH - 8.0, text_w + 32.0)
        box = QRectF(self.ANCHOR.x() - w / 2.0, self.ANCHOR.y() + 52.0, w, 34.0)
        painter.setOpacity(opacity)
        painter.setPen(QPen(QColor(86, 152, 224, 210), 1.6))
        painter.setBrush(QColor(18, 24, 34, 230))
        painter.drawRoundedRect(box, 17.0, 17.0)
        painter.setPen(QColor(240, 245, 250))
        painter.drawText(box, int(Qt.AlignmentFlag.AlignCenter), self._toast_text)
        painter.setOpacity(1.0)


# Alias for convenience
OverlayWidget = OverlayWindow
