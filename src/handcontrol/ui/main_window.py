"""The one application window: mode rail on the left, camera stage as the hero, gesture hints below or beside it.

GUI thread only. The window follows `UiBridge.state_changed`; changing the mode (button, tray or hand menu)
only swaps the page, so the instrument never opens somewhere else. Instrument options are reported through
`instrument_changed` (settings field names -> values) and applied by the runtime at once.
"""
from __future__ import annotations

from typing import Any, Optional

from PySide6.QtCore import QRectF, Qt, Signal, Slot
from PySide6.QtGui import QGuiApplication, QPainter
from PySide6.QtWidgets import (
    QBoxLayout, QButtonGroup, QFrame, QHBoxLayout, QMainWindow, QPushButton, QSlider, QStackedWidget, QToolButton,
    QWidget,
)

from handcontrol.contracts import CameraState, ControlState, Mode
from handcontrol.instrument.events import FIXED_STRINGS_RANGE, TONES
from handcontrol.ui import icons, theme
from handcontrol.ui.drawing_view import DRAWING_HINT_TR, DrawingView
from handcontrol.ui.instrument_view import FIXED_HINT_TR, FREE_HINT_TR, LAYOUT_LABELS_TR, InstrumentWindow
from handcontrol.ui.preview import CameraPreviewWidget
from handcontrol.ui.settings import INSTRUMENT_TONE_LABELS_TR
from handcontrol.ui.tray import create_mode_icon
from handcontrol.ui.viewmodel import MODE_LABELS_TR, UiBridge, UiState
from handcontrol.ui.widgets import (
    DarkTitleBar, hbox, vbox,
    Banner, ComboBox, FlowLayout, HintBar, ModeRail, NavButton, Segmented, SpinBox, StatusPill, ToggleSwitch, label,
    set_icon, tool,
)

WINDOW_SIZE = (1120, 800)
MIN_SIZE = (860, 580)
SIDE_WIDTH = 280                 # hint list beside the stage when that leaves a bigger picture
LAYOUT_ORDER = ("free", "fixed", "solo", "chord")      # the user's own strings first
DRY_RUN_BANNER_TR = "Komutsuz deneme: imleç gerçekten oynamaz. Gerçek kontrol için masaüstü kısayoluyla (--live) aç."
CONTROL_HINT_TR = ("İşaret parmağı: imleç  ·  El açık: imleç durur  ·  Kısa pinch: sol tık  ·  Uzun pinch: sağ tık  ·  "
                   "Üç parmak kavrama: sürükle  ·  Yumruk: küçült")
INSTRUMENT_HINTS_TR = {"free": FREE_HINT_TR, "fixed": FIXED_HINT_TR,
                       "solo": "Sol elin başparmak-işaret arası teldir, sağ işaret parmağınla vur",
                       "chord": "Sol elin yüksekliği akoru seçer, sağ işaret parmağınla tellere vur"}
WHEEL_HINT_TR = "Mod çarkı: sol elinle V yap, yarım saniye tut"
PRIMARY_MODES = (Mode.POINTER, Mode.SCROLL, Mode.INSTRUMENT, Mode.DRAWING)
MORE_MODES = tuple(m for m in Mode if m not in PRIMARY_MODES)
MODE_HINTS_TR = {
    Mode.POINTER: CONTROL_HINT_TR,
    Mode.SCROLL: "Sayfayı kaydır: başparmakla işareti birleştir, elini yukarı ya da aşağı taşı",
    Mode.ZOOM: "Yakınlaştır: iki elinde de başparmakla işareti birleştir, ellerini aç ya da kapat",
    Mode.VOLUME: "Sistem sesi: başparmakla işareti birleştir, elini yukarı ya da aşağı taşı",
    Mode.WINDOWS: "Başparmakla işareti kısa birleştir: pencere menüsü  ·  Basılı tut ve taşı: pencereyi sürükle",
    Mode.COMMANDS: "Açık avuçla kaydır: sağa ve sola önceki/sonraki, yukarı görev görünümü, aşağı masaüstü  ·  "
                   "Kısa pinch: oynat/duraklat",
    Mode.DRAWING: DRAWING_HINT_TR,
}

class _Brand(QWidget):
    """App mark at the top of the rail."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(48, 46)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        icons.paint_cat(p, QRectF(-4, -5, 56, 56))
        p.end()


def _group(*widgets: QWidget, spacing: int = 8) -> QWidget:
    """Widgets that stay on one line when the instrument bar wraps."""
    w = QWidget()
    row = hbox(w, spacing, 0, 0, 0, 0)
    for child in widgets:
        row.addWidget(child)
    return w


class MainWindow(DarkTitleBar, QMainWindow):
    instrument_changed = Signal(dict)          # settings fields to change, e.g. {"instrument_layout": "free"}
    free_strings_changed = Signal(object)      # new "Serbest teller" list (delete buttons)

    def __init__(self, bridge: UiBridge, *, live: bool = False, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._bridge = bridge
        self._mode: Optional[Mode] = None
        self._active: Optional[bool] = None
        self._free: list[Any] = []
        self._layout = "free"
        self._loading = False
        self.setWindowTitle("Holoscobe" + (" — Canlı" if live else " — Komutsuz Deneme"))
        theme.install()
        self.setWindowIcon(icons.brand_icon())
        self.setMinimumSize(*MIN_SIZE)
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = hbox(root, 0, 0, 0, 0, 0)
        outer.addWidget(self._build_rail())
        column = vbox(None, 12, 20, 14, 20, 16)
        outer.addLayout(column, 1)

        column.addLayout(self._build_header())
        self.banner = Banner(DRY_RUN_BANNER_TR)
        self.banner.setVisible(not live)
        column.addWidget(self.banner)
        self.instrument_bar = self._build_instrument_bar()
        column.addWidget(self.instrument_bar)

        self.preview = CameraPreviewWidget(bridge)
        self.preview.set_show_details(False)
        self.preview.set_state_cards(True)
        self.instrument = InstrumentWindow(bridge)
        self.drawing = DrawingView()
        self.ink_clear_button.clicked.connect(self.drawing.clear)
        for stage in (self.preview, self.instrument.canvas, self.drawing):
            stage.setMinimumSize(320, 200)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.preview)
        self.stack.addWidget(self.instrument)
        self.stack.addWidget(self.drawing)
        self.hint = HintBar()
        self._body = QBoxLayout(QBoxLayout.Direction.TopToBottom)
        self._body.setSpacing(14)
        self._body.addWidget(self.stack, 1)
        self._body.addWidget(self.hint)
        column.addLayout(self._body, 1)

        self.resize(*WINDOW_SIZE)
        self._center()
        bridge.state_changed.connect(self.apply_state)
        bridge.mascot_visible_changed.connect(self.mascot_button.setChecked)
        self.apply_state(bridge.state)

    # ---------- building ----------

    def _build_rail(self) -> QWidget:
        self._rail = ModeRail()
        column = self._rail.column
        column.addWidget(_Brand(), 0, Qt.AlignmentFlag.AlignHCenter)
        column.addSpacing(10)
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_buttons: dict[Mode, QToolButton] = {}
        for mode in PRIMARY_MODES:
            b = NavButton(MODE_LABELS_TR[mode], icons.MODE_ICONS[mode])
            b.clicked.connect(lambda _=False, m=mode: self._bridge.select_mode(m))
            self.mode_group.addButton(b)
            self.mode_buttons[mode] = b
            column.addWidget(b)
        self.more_button = NavButton("Diğer", "more")
        self.more_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = theme.menu(self.more_button)
        self.more_actions = {}
        for mode in MORE_MODES:
            self.more_actions[mode] = action = menu.addAction(create_mode_icon(mode), MODE_LABELS_TR[mode])
            action.triggered.connect(lambda _=False, m=mode: self._bridge.select_mode(m))
        self.more_button.setMenu(menu)
        self.mode_group.addButton(self.more_button)
        column.addWidget(self.more_button)
        column.addStretch(1)
        self.settings_button = NavButton("Ayarlar", "settings")
        self.settings_button.setCheckable(False)
        self.settings_button.clicked.connect(self._bridge.settings_requested)
        column.addWidget(self.settings_button)
        return self._rail

    def _build_header(self) -> QHBoxLayout:
        row = hbox(None, 8)
        row.addWidget(label("Holoscobe", "title"))
        row.addSpacing(6)
        self.status = StatusPill()
        row.addWidget(self.status)
        row.addStretch(1)
        self.details_button = tool("Ayrıntı", "details")
        self.details_button.setCheckable(True)
        self.details_button.setToolTip("Parmak durumlarını ve kare hızını gösterir")
        self.details_button.toggled.connect(lambda on: self.preview.set_show_details(on))
        row.addWidget(self.details_button)
        self.ink_clear_button = tool("Temizle", "trash")
        self.ink_clear_button.setToolTip("Bütün mürekkebi akıtarak siler")
        self.ink_clear_button.hide()
        row.addWidget(self.ink_clear_button)
        self.mascot_button = tool("Kedi", "cat")
        self.mascot_button.setCheckable(True)
        self.mascot_button.setChecked(self._bridge.mascot_visible)
        self.mascot_button.setToolTip("Sağ alttaki kediyi gösterir ya da gizler")
        self.mascot_button.clicked.connect(self._bridge.mascot_toggle_requested)      # user clicks only, not setChecked
        row.addWidget(self.mascot_button)
        row.addSpacing(4)
        self.start_button = QPushButton("Sürdür")
        self.start_button.setObjectName("start")
        self.start_button.setProperty("kind", "primary")
        self.start_button.setMinimumSize(132, 40)
        self.start_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_button.clicked.connect(self._bridge.pause_resume_requested)
        row.addWidget(self.start_button)
        return row

    def _build_instrument_bar(self) -> QWidget:
        frame = QFrame()
        frame.setProperty("role", "card")
        flow = FlowLayout(frame, 14, 8)
        flow.setContentsMargins(10, 8, 12, 8)
        self.layout_group = QButtonGroup(self)
        self.layout_group.setExclusive(True)
        self.layout_buttons: dict[str, QPushButton] = {}
        segments = Segmented()
        for key in LAYOUT_ORDER:
            b = segments.add(LAYOUT_LABELS_TR[key])
            b.clicked.connect(lambda _=False, k=key: self._emit(instrument_layout=k))
            self.layout_group.addButton(b)
            self.layout_buttons[key] = b
        flow.addWidget(segments)
        self.undo_button = tool("Son teli sil", "undo")
        self.undo_button.clicked.connect(lambda: self.free_strings_changed.emit(tuple(self._free[:-1])))
        self.clear_button = tool("Hepsini sil", "trash")
        self.clear_button.clicked.connect(lambda: self.free_strings_changed.emit(()))
        for b in (self.undo_button, self.clear_button):
            b.setProperty("compact", True)
        self.snap_check = ToggleSwitch("Hizala", show_text=True)
        self.snap_check.setToolTip("Birbirine yakın telleri hizalar; istersen kapat")
        self.snap_check.toggled.connect(lambda on: self._emit(instrument_free_snap=bool(on)))
        self.count_label = label("Tel sayısı", "caption")
        self.count_spin = SpinBox()
        self.count_spin.setFixedWidth(84)
        self.count_spin.setRange(*FIXED_STRINGS_RANGE)
        self.count_spin.valueChanged.connect(lambda n: self._emit(instrument_fixed_strings=int(n)))
        self._free_group = _group(self.undo_button, self.clear_button, self.snap_check, spacing=2)
        self._fixed_group = _group(self.count_label, self.count_spin)
        self.tone_combo = ComboBox()
        self.tone_combo.setFixedWidth(104)
        for tone in TONES:
            self.tone_combo.addItem(INSTRUMENT_TONE_LABELS_TR.get(tone, tone), tone)
        self.tone_combo.currentIndexChanged.connect(
            lambda _: self._emit(instrument_tone=self.tone_combo.currentData()))
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setFixedWidth(96)
        self.volume_slider.setTracking(False)            # one save per drag
        self.volume_slider.valueChanged.connect(lambda v: self._emit(instrument_volume=round(v / 100.0, 2)))
        sound = _group(label("Tını", "caption"), self.tone_combo, label("Ses", "caption"), self.volume_slider)
        for w, name in ((self.tone_combo, "Tını"), (self.volume_slider, "Ses"), (self.count_spin, "Tel sayısı")):
            w.setAccessibleName(name)
        for w in (self._free_group, self._fixed_group, sound):
            flow.addWidget(w)
        return frame

    def _center(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        w, h = min(self.width(), area.width() - 40), min(self.height(), area.height() - 60)
        self.resize(w, h)
        self.move(area.center().x() - w // 2, area.center().y() - h // 2)

    def _emit(self, **values: Any) -> None:
        if not self._loading:
            self.instrument_changed.emit(values)

    # ---------- state ----------

    @Slot(object)
    def apply_state(self, state: UiState) -> None:
        active = state.control_state is ControlState.ACTIVE
        self.start_button.setText(state.pause_resume_action_text)
        if self._active is not active:
            self._active = active
            theme.set_prop(self.start_button, "kind", "" if active else "primary")
            set_icon(self.start_button, "pause" if active else "play", theme.TEXT if active else theme.ON_ACCENT)
        tone = theme.SUCCESS if active else theme.WARNING
        if state.camera_state is not CameraState.RUNNING or state.control_state is ControlState.FAULT:
            tone = theme.WARNING if state.camera_state is CameraState.STARTING else theme.DANGER
        self.status.set_status(f"{state.control_state_label_tr} · Kamera: {state.camera_state_label_tr}", tone)
        instrument = state.mode is Mode.INSTRUMENT
        drawing = state.mode is Mode.DRAWING
        self.drawing.set_state(state)
        self._show_hint(state)
        if state.mode is self._mode:
            return
        entered = (drawing or instrument) and self._mode is not None
        self._mode = state.mode
        more = state.mode in MORE_MODES
        button = self.mode_buttons.get(state.mode, self.more_button)
        button.setChecked(True)
        self._rail.select(button)
        self.more_button.setText(MODE_LABELS_TR[state.mode] if more else "Diğer")
        self.more_button.set_icon_name(icons.MODE_ICONS[state.mode] if more else "more")
        self.instrument_bar.setVisible(instrument)
        self.details_button.setVisible(not (drawing or instrument))
        self.ink_clear_button.setVisible(drawing)
        page = {Mode.DRAWING: self.drawing, Mode.INSTRUMENT: self.instrument}.get(state.mode, self.preview)
        self.stack.setCurrentWidget(page)
        if entered:
            self.bring_up(focus=False)

    def _show_hint(self, state: UiState) -> None:
        tip = MODE_HINTS_TR.get(state.mode) or INSTRUMENT_HINTS_TR.get(self._layout, "")
        self.hint.show_message(state.error_text or f"{tip}  ·  {WHEEL_HINT_TR}", bool(state.error_text))

    def _arrange(self) -> None:
        """Hints below the stage, or beside it when that leaves the 4:3 camera picture bigger."""
        w, h = self.width() - 140, self.height() - 82
        below = min(w, (h - 90) * 4 / 3)
        beside = min(w - SIDE_WIDTH - 20, h * 4 / 3)
        side = beside > below + (0 if self.hint.vertical else 24)
        if side is not self.hint.vertical:
            self.hint.set_vertical(side)
            self._body.setDirection(QBoxLayout.Direction.LeftToRight if side else QBoxLayout.Direction.TopToBottom)
            self._body.setSpacing(20 if side else 14)
            self.hint.setMinimumWidth(SIDE_WIDTH if side else 0)
            self.hint.setMaximumWidth(SIDE_WIDTH if side else 16777215)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._arrange()

    @Slot()
    def bring_up(self, focus: bool = True) -> None:
        """Show the window where it already is (restoring it when minimized or closed to the tray)."""
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        if focus:
            self.activateWindow()

    @Slot(object)
    def apply_instrument_settings(self, settings: Any) -> None:
        """Mirror the stored settings in the instrument bar without emitting changes."""
        self._loading = True
        try:
            layout = self._layout = settings.instrument_layout
            self.layout_buttons[layout].setChecked(True)
            self._free = [tuple(s) for s in settings.instrument_free_strings]
            for w in (self._free_group, self.undo_button, self.clear_button, self.snap_check):
                w.setVisible(layout == "free")
            for w in (self.undo_button, self.clear_button):
                w.setEnabled(bool(self._free))
            for w in (self._fixed_group, self.count_label, self.count_spin):
                w.setVisible(layout == "fixed")
            self.snap_check.setChecked(bool(settings.instrument_free_snap))
            self.count_spin.setValue(int(settings.instrument_fixed_strings))
            self.tone_combo.setCurrentIndex(max(0, self.tone_combo.findData(settings.instrument_tone)))
            self.volume_slider.setValue(round(float(settings.instrument_volume) * 100))
            self._show_hint(self._bridge.state)
        finally:
            self._loading = False


__all__ = ["MainWindow"]
