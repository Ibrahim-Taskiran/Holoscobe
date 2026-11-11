"""Transparent, frameless, always-on-top, non-focus-stealing, click-through overlay
for the Mode Menu and Window Action Menu.

Features:
- Custom virtual cursor rendered via QPainter.
- 1-second (1,000 ms) visible progress ring for the Close ("Kapat") action.
- 5-second (5,000 ms) inactivity closing animation driven by external timing.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, Slot
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget

from handcontrol.contracts import Mode
from handcontrol.ui.viewmodel import (
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


# Alias for convenience
OverlayWidget = OverlayWindow
