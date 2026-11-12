"""System tray icon and menu for Holoscobe.

All icons are generated procedurally with QPainter.
All user-visible strings are in Turkish.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, Slot
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from handcontrol.contracts import Mode
from handcontrol.ui.viewmodel import (
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


class HandControlTray(QSystemTrayIcon):
    """System tray icon controller bound to a UiBridge."""

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
        self.action_exit = QAction("Çıkış", self.menu)

        # Equivalent tray mode selection submenu (per spec §5)
        self.mode_menu = QMenu("Mod Seçimi", self.menu)
        self.mode_action_group = QActionGroup(self.mode_menu)
        self.mode_action_group.setExclusive(True)
        self.mode_actions: dict[Mode, QAction] = {}
        for mode in Mode:
            act = QAction(MODE_LABELS_TR[mode], self.mode_menu)
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

        self.menu.addAction(self.action_pause_resume)
        self.menu.addAction(self.action_camera_toggle)
        self.menu.addSeparator()
        self.menu.addMenu(self.mode_menu)
        self.menu.addMenu(self.guide_menu)
        self.menu.addAction(self.action_settings)
        self.menu.addAction(self.action_calibrate)
        self.menu.addSeparator()
        self.menu.addAction(self.action_exit)

        self.setContextMenu(self.menu)

        # Wire menu actions to UiBridge request emitters
        self.action_pause_resume.triggered.connect(self._bridge.request_pause_resume)
        self.action_camera_toggle.triggered.connect(self._bridge.request_camera_toggle)
        self.action_settings.triggered.connect(self._bridge.request_settings)
        self.action_calibrate.triggered.connect(self._bridge.request_calibration)
        self.action_exit.triggered.connect(self._bridge.request_exit)

        self._bridge.state_changed.connect(self.apply_state)
        self.apply_state(self._bridge.state)

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
