"""System tray icon and menu for Holoscobe.

All icons are generated procedurally with QPainter.
All user-visible strings are in Turkish.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, Signal, Slot
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from handcontrol.contracts import Mode
from handcontrol.ui.viewmodel import (
    COMMANDS_GUIDE_TITLE_TR,
    COMMANDS_GUIDE_TR,
    GESTURE_GUIDE_TR,
    MODE_LABELS_TR,
    TRAY_ICON_STATE_LABELS_TR,
    TrayIconState,
    UiBridge,
    UiState,
)


def create_tray_pixmap(state: TrayIconState, size: int = 64) -> QPixmap:
    """Render a procedural tray icon pixmap for the given TrayIconState."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    margin = size * 0.08
    outer_rect = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)

    palette = {
        TrayIconState.PAUSED: (QColor(217, 155, 38), QColor(255, 214, 102)),
        TrayIconState.ACTIVE: (QColor(26, 163, 92), QColor(110, 242, 168)),
        TrayIconState.CALIBRATING: (QColor(33, 130, 214), QColor(122, 201, 255)),
        TrayIconState.CAMERA_UNAVAILABLE: (QColor(186, 45, 50), QColor(245, 132, 136)),
    }
    fill_color, border_color = palette.get(
        state,
        (QColor(110, 118, 129), QColor(180, 188, 198)),
    )

    painter.setPen(QPen(border_color, max(2.0, size * 0.05)))
    painter.setBrush(fill_color)
    painter.drawEllipse(outer_rect)

    fg_pen = QPen(QColor(255, 255, 255), max(2.5, size * 0.075))
    fg_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    fg_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(fg_pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    if state == TrayIconState.PAUSED:
        # Two vertical pause bars
        bar_w = size * 0.09
        bar_h = size * 0.34
        top_y = (size - bar_h) * 0.5
        left_x = size * 0.34
        right_x = size * 0.57
        painter.setBrush(QColor(255, 255, 255))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(QRectF(left_x, top_y, bar_w, bar_h), 2.0, 2.0)
        painter.drawRoundedRect(QRectF(right_x, top_y, bar_w, bar_h), 2.0, 2.0)

    elif state == TrayIconState.ACTIVE:
        # Stylized open palm / active checkmark + dot
        center = QPointF(size * 0.5, size * 0.54)
        palm_r = size * 0.13
        painter.setBrush(QColor(255, 255, 255))
        painter.drawEllipse(center, palm_r, palm_r)
        # Five finger rays
        finger_tips = [
            QPointF(size * 0.26, size * 0.44),
            QPointF(size * 0.36, size * 0.26),
            QPointF(size * 0.50, size * 0.22),
            QPointF(size * 0.64, size * 0.26),
            QPointF(size * 0.73, size * 0.38),
        ]
        for tip in finger_tips:
            painter.drawLine(center, tip)

    elif state == TrayIconState.CALIBRATING:
        # Crosshair target reticle
        c = size * 0.5
        inner_r = size * 0.18
        painter.drawEllipse(QPointF(c, c), inner_r, inner_r)
        painter.drawLine(QPointF(c, size * 0.20), QPointF(c, size * 0.34))
        painter.drawLine(QPointF(c, size * 0.66), QPointF(c, size * 0.80))
        painter.drawLine(QPointF(size * 0.20, c), QPointF(size * 0.34, c))
        painter.drawLine(QPointF(size * 0.66, c), QPointF(size * 0.80, c))

    elif state == TrayIconState.CAMERA_UNAVAILABLE:
        # Cross / slash indicating unavailable camera
        p1 = size * 0.32
        p2 = size * 0.68
        painter.drawLine(QPointF(p1, p1), QPointF(p2, p2))
        painter.drawLine(QPointF(p2, p1), QPointF(p1, p2))

    painter.end()
    return pixmap


def create_tray_icon(state: TrayIconState, size: int = 64) -> QIcon:
    """Create a QIcon for the given TrayIconState."""
    return QIcon(create_tray_pixmap(state, size=size))


MODE_ICON_COLORS: dict[Mode, QColor] = {
    Mode.POINTER: QColor(72, 172, 242),
    Mode.SCROLL: QColor(82, 214, 148),
    Mode.ZOOM: QColor(255, 198, 88),
    Mode.VOLUME: QColor(178, 132, 255),
    Mode.WINDOWS: QColor(240, 148, 72),
    Mode.COMMANDS: QColor(236, 94, 140),
    Mode.DRAWING: QColor(94, 83, 164),
    Mode.INSTRUMENT: QColor(38, 198, 218),
}


def create_mode_pixmap(mode: Mode, size: int = 32) -> QPixmap:
    """Procedural glyph per mode (arrow, scroll, magnifier, speaker, window, keys, guitar)."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    s = float(size)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(MODE_ICON_COLORS.get(mode, QColor(150, 160, 170)))
    p.drawRoundedRect(QRectF(s * 0.04, s * 0.04, s * 0.92, s * 0.92), s * 0.22, s * 0.22)
    pen = QPen(QColor(255, 255, 255), max(1.6, s * 0.08))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    def pt(x: float, y: float) -> QPointF:
        return QPointF(s * x, s * y)

    if mode == Mode.POINTER:
        p.setBrush(QColor(255, 255, 255))
        p.drawPolygon([pt(0.32, 0.22), pt(0.32, 0.74), pt(0.45, 0.61), pt(0.56, 0.80),
                       pt(0.64, 0.76), pt(0.54, 0.57), pt(0.71, 0.57)])
    elif mode == Mode.SCROLL:
        p.drawLine(pt(0.5, 0.22), pt(0.5, 0.78))
        p.drawPolyline([pt(0.34, 0.36), pt(0.5, 0.22), pt(0.66, 0.36)])
        p.drawPolyline([pt(0.34, 0.64), pt(0.5, 0.78), pt(0.66, 0.64)])
    elif mode == Mode.ZOOM:
        p.drawEllipse(pt(0.44, 0.44), s * 0.18, s * 0.18)
        p.drawLine(pt(0.57, 0.57), pt(0.76, 0.76))
        p.drawLine(pt(0.36, 0.44), pt(0.52, 0.44))
        p.drawLine(pt(0.44, 0.36), pt(0.44, 0.52))
    elif mode == Mode.VOLUME:
        p.setBrush(QColor(255, 255, 255))
        p.drawPolygon([pt(0.22, 0.42), pt(0.34, 0.42), pt(0.50, 0.28), pt(0.50, 0.72),
                       pt(0.34, 0.58), pt(0.22, 0.58)])
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRectF(s * 0.46, s * 0.34, s * 0.24, s * 0.32), -60 * 16, 120 * 16)
        p.drawArc(QRectF(s * 0.44, s * 0.24, s * 0.38, s * 0.52), -60 * 16, 120 * 16)
    elif mode == Mode.WINDOWS:
        p.drawRoundedRect(QRectF(s * 0.22, s * 0.26, s * 0.56, s * 0.48), s * 0.06, s * 0.06)
        p.drawLine(pt(0.22, 0.38), pt(0.78, 0.38))
    elif mode == Mode.COMMANDS:
        p.drawRoundedRect(QRectF(s * 0.18, s * 0.30, s * 0.64, s * 0.40), s * 0.08, s * 0.08)
        p.drawPolyline([pt(0.40, 0.42), pt(0.30, 0.50), pt(0.40, 0.58)])
        p.drawPolyline([pt(0.60, 0.42), pt(0.70, 0.50), pt(0.60, 0.58)])
    elif mode == Mode.DRAWING:
        p.drawLine(pt(0.46, 0.55), pt(0.76, 0.24))
        p.setBrush(QColor(255, 255, 255))
        p.drawPolygon([pt(0.28, 0.74), pt(0.35, 0.53), pt(0.44, 0.50), pt(0.49, 0.59), pt(0.43, 0.70)])
    elif mode == Mode.INSTRUMENT:
        # Guitar body (two circles), neck and three strings.
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(pt(0.36, 0.64), s * 0.15, s * 0.15)
        p.drawEllipse(pt(0.48, 0.52), s * 0.11, s * 0.11)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(pt(0.50, 0.50), pt(0.78, 0.22))
        thin = QPen(MODE_ICON_COLORS[Mode.INSTRUMENT], max(1.0, s * 0.035))
        p.setPen(thin)
        for off in (-0.035, 0.0, 0.035):
            p.drawLine(pt(0.30 + off, 0.66 + off), pt(0.56 + off, 0.40 + off))
    p.end()
    return pixmap


def create_mode_icon(mode: Mode, size: int = 32) -> QIcon:
    """QIcon for a Mode (tray mode menu, settings default-mode list)."""
    return QIcon(create_mode_pixmap(mode, size=size))


class HandControlTray(QSystemTrayIcon):
    """System tray icon controller bound to a UiBridge."""

    # Tray-level request signal ("Eğitimi başlat"); the same click also calls bridge.request_tutorial().
    tutorial_requested = Signal()

    def __init__(
        self,
        bridge: UiBridge,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._bridge = bridge
        self._icon_state: TrayIconState = TrayIconState.CAMERA_UNAVAILABLE
        self._icon_cache: dict[TrayIconState, QIcon] = {
            st: create_tray_icon(st) for st in TrayIconState
        }

        self.menu = QMenu(parent)

        # Primary required actions
        self.action_pause_resume = QAction("Sürdür", self.menu)
        self.action_camera_toggle = QAction("Kamerayı Başlat", self.menu)
        self.action_settings = QAction("Ayarlar", self.menu)
        self.action_calibrate = QAction("Kalibre Et", self.menu)
        self.action_instrument_window = QAction(
            create_mode_icon(Mode.INSTRUMENT), "Enstrüman penceresi", self.menu)
        self.action_tutorial = QAction("Eğitimi başlat", self.menu)
        self.action_exit = QAction("Çıkış", self.menu)

        # Equivalent tray mode selection submenu (per spec §5)
        self.mode_menu = QMenu("Mod Seçimi", self.menu)
        self.mode_action_group = QActionGroup(self.mode_menu)
        self.mode_action_group.setExclusive(True)
        self.mode_actions: dict[Mode, QAction] = {}
        for mode in Mode:
            act = QAction(create_mode_icon(mode), MODE_LABELS_TR[mode], self.mode_menu)
            act.setCheckable(True)
            act.setData(mode)
            act.triggered.connect(self._make_mode_trigger(mode))
            self.mode_action_group.addAction(act)
            self.mode_menu.addAction(act)
            self.mode_actions[mode] = act

        # Read-only gesture guide: one disabled entry per gesture.
        self.guide_menu = QMenu("Hareket Rehberi", self.menu)
        for gesture, result in GESTURE_GUIDE_TR:
            entry = QAction(f"{gesture} → {result}", self.guide_menu)
            entry.setEnabled(False)
            self.guide_menu.addAction(entry)
        self.guide_commands_section = self.guide_menu.addSection(
            create_mode_icon(Mode.COMMANDS), COMMANDS_GUIDE_TITLE_TR)
        for gesture, result in COMMANDS_GUIDE_TR:
            entry = QAction(f"{gesture} → {result}", self.guide_menu)
            entry.setEnabled(False)
            self.guide_menu.addAction(entry)

        self.menu.addAction(self.action_pause_resume)
        self.menu.addAction(self.action_camera_toggle)
        self.menu.addSeparator()
        self.menu.addMenu(self.mode_menu)
        self.menu.addMenu(self.guide_menu)
        self.menu.addAction(self.action_instrument_window)
        self.menu.addAction(self.action_settings)
        self.menu.addAction(self.action_calibrate)
        self.menu.addAction(self.action_tutorial)
        self.menu.addSeparator()
        self.menu.addAction(self.action_exit)

        self.setContextMenu(self.menu)

        # Wire menu actions to UiBridge request emitters
        self.action_pause_resume.triggered.connect(self._bridge.request_pause_resume)
        self.action_camera_toggle.triggered.connect(self._bridge.request_camera_toggle)
        self.action_settings.triggered.connect(self._bridge.request_settings)
        self.action_calibrate.triggered.connect(self._bridge.request_calibration)
        self.action_exit.triggered.connect(self._bridge.request_exit)
        self.action_instrument_window.triggered.connect(self._bridge.request_instrument_window)
        self.action_tutorial.triggered.connect(self._on_tutorial)

        self._bridge.state_changed.connect(self.apply_state)
        self.apply_state(self._bridge.state)

    @Slot()
    def _on_tutorial(self) -> None:
        self.tutorial_requested.emit()
        self._bridge.request_tutorial()

    def _make_mode_trigger(self, mode: Mode):
        def _on_triggered() -> None:
            self._bridge.select_mode(mode)

        return _on_triggered

    @property
    def icon_state(self) -> TrayIconState:
        """Current tray icon state."""
        return self._icon_state

    @property
    def state_label_tr(self) -> str:
        """Turkish label for the current tray icon state."""
        return TRAY_ICON_STATE_LABELS_TR[self._icon_state]

    @Slot(object)
    def apply_state(self, state: UiState) -> None:
        """Synchronize icon, tooltip, and menu labels with the given UiState."""
        new_icon_state = state.tray_icon_state
        self._icon_state = new_icon_state
        self.setIcon(self._icon_cache[new_icon_state])
        self.setToolTip(state.tooltip_text)

        self.action_pause_resume.setText(state.pause_resume_action_text)
        self.action_camera_toggle.setText(state.camera_toggle_action_text)

        mode_act = self.mode_actions.get(state.mode)
        if mode_act is not None and not mode_act.isChecked():
            mode_act.setChecked(True)


# Alias for convenience
SystemTray = HandControlTray
TrayController = HandControlTray
