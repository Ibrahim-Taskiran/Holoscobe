"""System tray icon and menu for Holoscobe.

All icons are generated procedurally with QPainter.
All user-visible strings are in Turkish.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRectF, Qt, Signal, Slot
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QMenu, QSystemTrayIcon, QWidget, QWidgetAction

from handcontrol.contracts import ControlState, Mode
from handcontrol.ui import icons, theme
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
from handcontrol.ui.widgets import label

GUIDE_WIDTHS = (230, 330)         # gesture and result columns of the guide menu

_TRAY_COLORS: dict[TrayIconState, str] = {
    TrayIconState.PAUSED: theme.WARNING,
    TrayIconState.ACTIVE: theme.SUCCESS,
    TrayIconState.CALIBRATING: theme.ACCENT,
    TrayIconState.CAMERA_UNAVAILABLE: theme.DANGER,
}
_TRAY_GLYPHS: dict[TrayIconState, str] = {
    TrayIconState.PAUSED: "pause",
    TrayIconState.ACTIVE: "hand",
    TrayIconState.CALIBRATING: "target",
    TrayIconState.CAMERA_UNAVAILABLE: "camera_off",
}


def create_tray_pixmap(state: TrayIconState, size: int = 64) -> QPixmap:
    """Rounded tile in the state color with a dark glyph (readable at 16 px on light and dark taskbars)."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    s = float(size)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(_TRAY_COLORS[state]))
    p.drawRoundedRect(QRectF(s * 0.03, s * 0.03, s * 0.94, s * 0.94), s * 0.28, s * 0.28)
    icons.paint(p, _TRAY_GLYPHS[state], QRectF(s * 0.16, s * 0.16, s * 0.68, s * 0.68), theme.ON_ACCENT, 2.4)
    p.end()
    return pixmap


def create_tray_icon(state: TrayIconState, size: int = 64) -> QIcon:
    """Create a QIcon for the given TrayIconState."""
    return QIcon(create_tray_pixmap(state, size=size))


# One accent for every mode: the glyph tells them apart, not the hue.
MODE_ICON_COLORS: dict[Mode, QColor] = {mode: QColor(theme.ACCENT) for mode in Mode}


def create_mode_pixmap(mode: Mode, size: int = 32, color: QColor | str = theme.TEXT) -> QPixmap:
    """Stroke glyph of a mode on a transparent background."""
    return icons.pixmap(icons.MODE_ICONS.get(mode, "info"), size, color)


def create_mode_icon(mode: Mode, size: int = 32) -> QIcon:
    """QIcon for a Mode (tray mode menu, settings default-mode list); accent colored while checked."""
    return icons.icon(icons.MODE_ICONS.get(mode, "info"), size=size)


def _guide_entry(gesture: str, result: str, parent: QMenu) -> QWidgetAction:
    """Read-only guide line: gesture on the left, its result wrapped on the right."""
    entry = QWidgetAction(parent)
    entry.setText(f"{gesture} → {result}")
    entry.setEnabled(False)
    box = QWidget()
    row = QHBoxLayout(box)
    row.setContentsMargins(12, 5, 12, 5)
    row.setSpacing(16)
    for text, role, width in ((gesture, "row", GUIDE_WIDTHS[0]), (result, "caption", GUIDE_WIDTHS[1])):
        part = label(text, role, True)
        part.ensurePolished()
        part.setFixedSize(width, part.heightForWidth(width))
        row.addWidget(part, 0, Qt.AlignmentFlag.AlignTop)
    entry.setDefaultWidget(box)
    return entry


def _guide_title(text: str, parent: QMenu) -> QWidgetAction:
    """Section separator that shows its title."""
    entry = QWidgetAction(parent)
    entry.setText(text)
    entry.setSeparator(True)
    title = label(text, "accent")
    title.setContentsMargins(12, 12, 12, 4)
    entry.setDefaultWidget(title)
    return entry


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
        self._active = False
        self._icon_cache: dict[TrayIconState, QIcon] = {
            st: create_tray_icon(st) for st in TrayIconState
        }

        theme.install()
        self.menu = theme.menu(parent)

        # Primary required actions
        self.action_pause_resume = QAction(icons.icon("play"), "Sürdür", self.menu)
        self.action_camera_toggle = QAction(icons.icon("camera"), "Kamerayı Başlat", self.menu)
        self.action_settings = QAction(icons.icon("settings"), "Ayarlar", self.menu)
        self.action_calibrate = QAction(icons.icon("target"), "Kalibre Et", self.menu)
        self.action_instrument_window = QAction(
            create_mode_icon(Mode.INSTRUMENT), "Enstrüman penceresi", self.menu)
        self.action_tutorial = QAction(icons.icon("learn"), "Eğitimi başlat", self.menu)
        self.action_mascot = QAction(icons.icon("cat", checked_name="check"), "Kediyi göster", self.menu)
        self.action_mascot.setCheckable(True)
        self.action_mascot.setChecked(bridge.mascot_visible)
        self.action_exit = QAction(icons.icon("power"), "Çıkış", self.menu)

        # Equivalent tray mode selection submenu (per spec §5)
        self.mode_menu = theme.menu(self.menu, "Mod Seçimi")
        self.mode_menu.setIcon(icons.icon("hand"))
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
        self.guide_menu = theme.menu(self.menu, "Hareket Rehberi")
        self.guide_menu.setIcon(icons.icon("guide"))
        for gesture, result in GESTURE_GUIDE_TR:
            self.guide_menu.addAction(_guide_entry(gesture, result, self.guide_menu))
        self.guide_commands_section = _guide_title(COMMANDS_GUIDE_TITLE_TR, self.guide_menu)
        self.guide_menu.addAction(self.guide_commands_section)
        for gesture, result in COMMANDS_GUIDE_TR:
            self.guide_menu.addAction(_guide_entry(gesture, result, self.guide_menu))

        self.menu.addAction(self.action_pause_resume)
        self.menu.addAction(self.action_camera_toggle)
        self.menu.addSeparator()
        self.menu.addMenu(self.mode_menu)
        self.menu.addMenu(self.guide_menu)
        self.menu.addAction(self.action_instrument_window)
        self.menu.addAction(self.action_mascot)
        self.menu.addSeparator()
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
        self.action_mascot.triggered.connect(self._bridge.request_mascot)      # user clicks only
        self._bridge.mascot_visible_changed.connect(self.action_mascot.setChecked)

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

        active = state.control_state is ControlState.ACTIVE
        if active is not self._active:
            self._active = active
            self.action_pause_resume.setIcon(icons.icon("pause" if active else "play"))
        self.action_pause_resume.setText(state.pause_resume_action_text)
        self.action_camera_toggle.setText(state.camera_toggle_action_text)

        mode_act = self.mode_actions.get(state.mode)
        if mode_act is not None and not mode_act.isChecked():
            mode_act.setChecked(True)


# Alias for convenience
SystemTray = HandControlTray
TrayController = HandControlTray
