"""The one application window: control page (camera + skeleton) and Enstrüman page share the same place.

GUI thread only. The window follows `UiBridge.state_changed`; changing the mode (button, tray or hand menu)
only swaps the page, so the instrument never opens somewhere else. Instrument options are reported through
`instrument_changed` (settings field names -> values) and applied by the runtime at once.
"""
from __future__ import annotations

from typing import Any, Optional

from PySide6.QtCore import QSize, Qt, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton, QSlider, QSpinBox,
    QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from handcontrol.contracts import CameraState, ControlState, Mode
from handcontrol.instrument.events import FIXED_STRINGS_RANGE, TONES
from handcontrol.ui.instrument_view import FIXED_HINT_TR, FREE_HINT_TR, LAYOUT_LABELS_TR, InstrumentWindow
from handcontrol.ui.preview import CameraPreviewWidget
from handcontrol.ui.settings import INSTRUMENT_TONE_LABELS_TR
from handcontrol.ui.tray import create_mode_icon
from handcontrol.ui.viewmodel import MODE_LABELS_TR, UiBridge, UiState

WINDOW_SIZE = (1120, 800)
LAYOUT_ORDER = ("free", "fixed", "solo", "chord")      # the user's own strings first
DRY_RUN_BANNER_TR = "Komutsuz deneme: imleç gerçekten oynamaz. Gerçek kontrol için masaüstü kısayoluyla (--live) aç."
CONTROL_HINT_TR = ("İşaret parmağı: imleç  ·  El açık: imleç durur  ·  Kısa pinch: sol tık  ·  Uzun pinch: sağ tık  ·  "
                   "Üç parmak kavrama: sürükle  ·  Yumruk: küçült")
INSTRUMENT_HINTS_TR = {"free": FREE_HINT_TR, "fixed": FIXED_HINT_TR,
                       "solo": "Sol elin başparmak-işaret arası teldir, sağ işaret parmağınla vur",
                       "chord": "Sol elin yüksekliği akoru seçer, sağ işaret parmağınla tellere vur"}
BACK_HINT_TR = "İmlece dönmek için: İmleç düğmesi ya da sol avucunu açıp bekle"

STYLE = """
#root { background: #12161c; }
#root QWidget { font-family: "Segoe UI"; font-size: 9pt; }
#root QLabel { color: #c8d0dc; }
#root QLabel#banner { background: #4a3410; color: #ffd28a; border-radius: 8px; padding: 6px 12px; }
#root QLabel#hint { color: #7f8a9a; padding: 0 6px 4px 6px; }
#root QFrame#bar { background: #1a2029; border: 1px solid #28303c; border-radius: 10px; }
#root QPushButton, #root QToolButton {
    color: #d5dce6; background: #232b36; border: 1px solid #303a48; border-radius: 8px; padding: 6px 10px; }
#root QPushButton:hover, #root QToolButton:hover { background: #2d3745; }
#root QPushButton:focus, #root QToolButton:focus { border-color: #26c6da; }
#root QPushButton:disabled { color: #5f6875; }
#root QToolButton:checked, #root QPushButton:checked {
    background: #0f5561; border-color: #26c6da; color: #ffffff; }
#root QPushButton#start { font-weight: bold; min-width: 84px; background: #17663f; border-color: #2fbf78; color: #fff; }
#root QPushButton#start[active="true"] { background: #6b4a12; border-color: #e0a53c; }
#root QCheckBox { color: #c8d0dc; spacing: 6px; }
#root QComboBox, #root QSpinBox {
    color: #d5dce6; background: #232b36; border: 1px solid #303a48; border-radius: 6px; padding: 4px 8px; }
#root QComboBox QAbstractItemView { color: #d5dce6; background: #232b36; selection-background-color: #0f5561; }
"""


def _bar() -> tuple[QFrame, QHBoxLayout]:
    frame = QFrame()
    frame.setObjectName("bar")
    row = QHBoxLayout(frame)
    row.setContentsMargins(10, 6, 10, 6)
    row.setSpacing(6)
    return frame, row


class MainWindow(QMainWindow):
    instrument_changed = Signal(dict)          # settings fields to change, e.g. {"instrument_layout": "free"}
    free_strings_changed = Signal(object)      # new "Serbest teller" list (delete buttons)

    def __init__(self, bridge: UiBridge, *, live: bool = False, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._bridge = bridge
        self._mode: Optional[Mode] = None
        self._free: list[Any] = []
        self._layout = "free"
        self._loading = False
        self.setWindowTitle("Holoscobe" + (" — Canlı" if live else " — Komutsuz Deneme"))
        root = QWidget()
        root.setObjectName("root")
        root.setStyleSheet(STYLE)
        self.setCentralWidget(root)
        column = QVBoxLayout(root)
        column.setContentsMargins(10, 10, 10, 6)
        column.setSpacing(8)

        column.addWidget(self._build_header())
        self.banner = QLabel(DRY_RUN_BANNER_TR)
        self.banner.setObjectName("banner")
        self.banner.setWordWrap(True)
        self.banner.setVisible(not live)
        column.addWidget(self.banner)
        self.instrument_bar = self._build_instrument_bar()
        column.addWidget(self.instrument_bar)

        self.preview = CameraPreviewWidget(bridge)
        self.preview.set_show_details(False)
        self.instrument = InstrumentWindow(bridge)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.preview)
        self.stack.addWidget(self.instrument)
        column.addWidget(self.stack, 1)
        self.hint = QLabel()
        self.hint.setObjectName("hint")
        self.hint.setWordWrap(True)
        column.addWidget(self.hint)

        self.resize(*WINDOW_SIZE)
        self._center()
        bridge.state_changed.connect(self.apply_state)
        self.apply_state(bridge.state)

    # ---------- building ----------

    def _build_header(self) -> QWidget:
        frame, row = _bar()
        self.start_button = QPushButton("Sürdür")
        self.start_button.setObjectName("start")
        self.start_button.clicked.connect(self._bridge.request_pause_resume)
        row.addWidget(self.start_button)
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_buttons: dict[Mode, QToolButton] = {}
        for mode in Mode:
            b = QToolButton()
            b.setText(MODE_LABELS_TR[mode])
            b.setIcon(create_mode_icon(mode))
            b.setIconSize(QSize(18, 18))
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, m=mode: self._bridge.select_mode(m))
            self.mode_group.addButton(b)
            self.mode_buttons[mode] = b
            row.addWidget(b)
        row.addStretch(1)
        self.status = QLabel()
        row.addWidget(self.status)
        self.details_button = QToolButton()
        self.details_button.setText("Ayrıntı")
        self.details_button.setCheckable(True)
        self.details_button.toggled.connect(lambda on: self.preview.set_show_details(on))
        row.addWidget(self.details_button)
        settings = QToolButton()
        settings.setText("Ayarlar")
        settings.clicked.connect(self._bridge.request_settings)
        row.addWidget(settings)
        return frame

    def _build_instrument_bar(self) -> QWidget:
        frame, row = _bar()
        self.layout_group = QButtonGroup(self)
        self.layout_group.setExclusive(True)
        self.layout_buttons: dict[str, QPushButton] = {}
        for key in LAYOUT_ORDER:
            b = QPushButton(LAYOUT_LABELS_TR[key])
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=key: self._emit(instrument_layout=k))
            self.layout_group.addButton(b)
            self.layout_buttons[key] = b
            row.addWidget(b)
        row.addSpacing(12)
        self.undo_button = QPushButton("Son teli sil")
        self.undo_button.clicked.connect(lambda: self.free_strings_changed.emit(tuple(self._free[:-1])))
        self.clear_button = QPushButton("Hepsini sil")
        self.clear_button.clicked.connect(lambda: self.free_strings_changed.emit(()))
        self.snap_check = QCheckBox("Hizala")
        self.snap_check.setToolTip("Birbirine yakın telleri hizalar; istersen kapat")
        self.snap_check.toggled.connect(lambda on: self._emit(instrument_free_snap=bool(on)))
        self.count_label = QLabel("Tel sayısı")
        self.count_spin = QSpinBox()
        self.count_spin.setRange(*FIXED_STRINGS_RANGE)
        self.count_spin.valueChanged.connect(lambda n: self._emit(instrument_fixed_strings=int(n)))
        for w in (self.undo_button, self.clear_button, self.snap_check, self.count_label, self.count_spin):
            row.addWidget(w)
        row.addStretch(1)
        row.addWidget(QLabel("Tını"))
        self.tone_combo = QComboBox()
        for tone in TONES:
            self.tone_combo.addItem(INSTRUMENT_TONE_LABELS_TR.get(tone, tone), tone)
        self.tone_combo.currentIndexChanged.connect(
            lambda _: self._emit(instrument_tone=self.tone_combo.currentData()))
        row.addWidget(self.tone_combo)
        row.addWidget(QLabel("Ses"))
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setFixedWidth(120)
        self.volume_slider.setTracking(False)            # one save per drag
        self.volume_slider.valueChanged.connect(lambda v: self._emit(instrument_volume=round(v / 100.0, 2)))
        row.addWidget(self.volume_slider)
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
        if self.start_button.property("active") != active:
            self.start_button.setProperty("active", active)
            self.start_button.style().unpolish(self.start_button)
            self.start_button.style().polish(self.start_button)
        color = "#52d694" if active else "#ffce78"
        if state.camera_state is not CameraState.RUNNING:
            color = "#ff7a7a"
        self.status.setText(f'<span style="color:{color}">●</span> {state.control_state_label_tr} · '
                            f'Kamera: {state.camera_state_label_tr}')
        instrument = state.mode is Mode.INSTRUMENT
        self._show_hint(state)
        if state.mode is self._mode:
            return
        entered = instrument and self._mode is not None
        self._mode = state.mode
        self.mode_buttons[state.mode].setChecked(True)
        self.instrument_bar.setVisible(instrument)
        self.details_button.setVisible(not instrument)
        self.stack.setCurrentWidget(self.instrument if instrument else self.preview)
        if entered:
            self.bring_up(focus=False)

    def _show_hint(self, state: UiState) -> None:
        tip = (f"{INSTRUMENT_HINTS_TR.get(self._layout, '')}  ·  {BACK_HINT_TR}"
               if state.mode is Mode.INSTRUMENT else CONTROL_HINT_TR)
        self.hint.setText(state.error_text or tip)

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
            for w in (self.undo_button, self.clear_button, self.snap_check):
                w.setVisible(layout == "free")
            for w in (self.undo_button, self.clear_button):
                w.setEnabled(bool(self._free))
            for w in (self.count_label, self.count_spin):
                w.setVisible(layout == "fixed")
            self.snap_check.setChecked(bool(settings.instrument_free_snap))
            self.count_spin.setValue(int(settings.instrument_fixed_strings))
            self.tone_combo.setCurrentIndex(max(0, self.tone_combo.findData(settings.instrument_tone)))
            self.volume_slider.setValue(round(float(settings.instrument_volume) * 100))
            self._show_hint(self._bridge.state)
        finally:
            self._loading = False


__all__ = ["MainWindow"]
