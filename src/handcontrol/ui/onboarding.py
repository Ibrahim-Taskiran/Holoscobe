"""First-run interactive tutorial with large practice targets.

Steps: welcome + posture tips, point at 3 targets, click (2x), double click, right click,
drag & drop, Kaydırma / Komutlar intro, done. Progress comes from controller actions fed
through `on_action(kind, x, y)` (physical virtual-desktop px) and from real Qt mouse events
on the practice area (live mode: the OS clicks land here). The two sources are de-duplicated.
All user-visible text is Turkish.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from PySide6.QtCore import QElapsedTimer, QPoint, QPointF, QRectF, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QSizePolicy,
    QStackedWidget,
    QWidget,
)

from handcontrol.ui import icons, theme
from handcontrol.ui.dpi import physical_to_logical
from handcontrol.ui.illustrations import Illustration
from handcontrol.ui.viewmodel import COMMANDS_GUIDE_TR
from handcontrol.ui.widgets import DarkTitleBar, hbox, vbox, Banner, button, label
from handcontrol.ui.painted import PaintedWidget


class OnboardingStep(Enum):
    WELCOME = "welcome"
    POINT = "point"
    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    RIGHT_CLICK = "right_click"
    DRAG = "drag"
    MODES = "modes"
    DONE = "done"


STEP_ORDER: tuple[OnboardingStep, ...] = tuple(OnboardingStep)
REQUIRED_SUCCESSES: dict[OnboardingStep, int] = {
    OnboardingStep.POINT: 3,
    OnboardingStep.CLICK: 2,
    OnboardingStep.DOUBLE_CLICK: 1,
    OnboardingStep.RIGHT_CLICK: 1,
    OnboardingStep.DRAG: 1,
}
# Normalized target centers inside the practice area.
TARGET_POSITIONS: dict[OnboardingStep, tuple[tuple[float, float], ...]] = {
    OnboardingStep.POINT: ((0.18, 0.30), (0.82, 0.34), (0.50, 0.74)),
    OnboardingStep.CLICK: ((0.30, 0.50), (0.70, 0.50)),
    OnboardingStep.DOUBLE_CLICK: ((0.50, 0.50),),
    OnboardingStep.RIGHT_CLICK: ((0.50, 0.50),),
}
TARGET_DIAMETER = 112.0          # >= 96 px
HIT_TOLERANCE = 8.0
BOX_SIZE = 104.0
ZONE_SIZE = 176.0
BOX_START = (0.22, 0.50)
ZONE_CENTER = (0.78, 0.50)
HINT_HIDE_AFTER = 2              # hint hides after this many successes in a step
HINT_IDLE_MS = 10_000            # ... and returns after this long without progress
DEDUPE_MS = 300.0                # same kind from the other source within this window = one event
DEDUPE_PX = 60.0
CLICK_MOVE_PX = 12.0
AUTO_ADVANCE_MS = 900

ACCENT = QColor(theme.ACCENT)
SUCCESS = QColor(theme.SUCCESS)
WARN = QColor(theme.WARNING)
TEXT = QColor(theme.TEXT)
MUTED = QColor(theme.MUTED)

_HAND_TR = {"right": "Sağ", "left": "Sol"}


@dataclass(frozen=True)
class _StepText:
    title: str
    subtitle: str
    hint: str


def _step_texts(hand: str) -> dict[OnboardingStep, _StepText]:
    return {
        OnboardingStep.WELCOME: _StepText(
            "Holoscobe'a hoş geldin",
            "Birkaç dakikada el hareketleriyle bilgisayarını kontrol etmeyi öğreneceksin.",
            ""),
        OnboardingStep.POINT: _StepText(
            "İmleci hedeflere götür",
            "Parlayan hedefin üstüne gel. Üç hedefi sırayla yakala.",
            f"{hand} elinin işaret parmağını uzat, diğer parmakları kapat. Hızlı hareket uzağa, "
            "yavaş hareket hassas gider."),
        OnboardingStep.CLICK: _StepText(
            "Hedefe tıkla",
            "Hedefin içine iki kez tıkla.",
            "Başparmak ile işaret parmağını kısa bir an birleştir (pinch). Pinch sırasında imleç durur."),
        OnboardingStep.DOUBLE_CLICK: _StepText(
            "Çift tıkla",
            "Hedefe çift tıkla.",
            "Art arda iki hızlı pinch yap."),
        OnboardingStep.RIGHT_CLICK: _StepText(
            "Sağ tık",
            "Hedefe sağ tıkla.",
            "Pinch'i 0,8 sn yerinde tut; imlecin yanındaki halka dolunca bırak. "
            "Alternatif: açık elden başparmak + orta parmak."),
        OnboardingStep.DRAG: _StepText(
            "Kutuyu sürükle bırak",
            "Turuncu kutuyu yeşil alana taşı ve bırak.",
            "Başparmak, işaret ve orta parmak uçlarını birleştir, eli taşı, bırak. "
            "Alternatif: pinch'i kapalı tutup eli taşı."),
        OnboardingStep.MODES: _StepText(
            "Kaydırma ve Komutlar",
            "İki kullanışlı mod daha var. Mod çarkından istediğin zaman geçebilirsin.",
            ""),
        OnboardingStep.DONE: _StepText(
            "Hazırsın!",
            "Temel hareketlerin hepsini denedin.",
            ""),
    }


class _IconTile(PaintedWidget):
    """Small tinted square with an icon."""

    def __init__(self, icon: str, tone: str = theme.ACCENT) -> None:
        super().__init__()
        self._icon, self._tone = icon, tone
        self.setFixedSize(38, 38)

    def _paint(self, p: QPainter, rect: QRectF) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.color(self._tone, 0.15))
        p.drawRoundedRect(QRectF(self.rect()), 11, 11)
        icons.paint(p, self._icon, QRectF(9, 9, 20, 20), self._tone)


def _tip(icon: str, title: str, body: str, tone: str = theme.ACCENT) -> QWidget:
    w = QWidget()
    row = hbox(w, 14, 0, 0, 0, 0)
    row.addWidget(_IconTile(icon, tone), 0, Qt.AlignmentFlag.AlignTop)
    col = vbox(None, 2, 0, 1, 0, 0)
    col.addWidget(label(title, "row", True))
    col.addWidget(label(body, "caption", True))
    row.addLayout(col, 1)
    return w


def _scene_page(scene: str, tips: tuple[tuple[str, str, str], ...], spacing: int = 16) -> QWidget:
    """Illustration on the left, explained points on the right."""
    page = QWidget()
    row = hbox(page, 32, 0, 4, 0, 0)
    art = Illustration(scene)
    art.setFixedWidth(340)
    row.addWidget(art)
    col = vbox(None, spacing)
    col.addStretch(1)
    for icon, title, body in tips:
        col.addWidget(_tip(icon, title, body))
    col.addStretch(1)
    row.addLayout(col, 1)
    return page


class ProgressDots(PaintedWidget):
    """One dot per step: done = mint, current = accent pill, upcoming = grey."""

    def __init__(self, count: int, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._count = count
        self._current = 0
        self.setFixedHeight(14)
        self.setMinimumWidth(count * 22)

    @property
    def current(self) -> int:
        return self._current

    def set_current(self, index: int) -> None:
        self._current = max(0, min(self._count - 1, index))
        self.update()

    def _paint(self, p: QPainter, rect: QRectF) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        x, mid = 0.0, self.height() / 2.0
        for i in range(self._count):
            w = 28.0 if i == self._current else 8.0
            p.setBrush(QColor(theme.ACCENT) if i == self._current else QColor(theme.SUCCESS) if i < self._current
                       else QColor(theme.STROKE))
            p.drawRoundedRect(QRectF(x, mid - 4.0, w, 8.0), 4.0, 4.0)
            x += w + 8.0


class PracticeArea(PaintedWidget):
    """Painted practice surface; forwards real mouse events to the dialog."""

    def __init__(self, dialog: "OnboardingDialog") -> None:
        super().__init__(dialog)
        self._dialog = dialog
        self._press_pos: Optional[QPointF] = None
        self.setMouseTracking(True)
        self.setMinimumSize(560, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    # ---- real mouse events ("qt" source) ----

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._dialog._handle("move_pointer", event.position(), "qt")

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position()
            self._dialog._handle("left_down", event.position(), "qt")

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position()
            self._dialog._handle("left_down", event.position(), "qt")
            self._dialog._handle("double_click", event.position(), "qt")

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position()
        if event.button() == Qt.MouseButton.LeftButton:
            self._dialog._handle("left_up", pos, "qt")
            start = self._press_pos
            self._press_pos = None
            if start is not None and math.hypot(pos.x() - start.x(), pos.y() - start.y()) <= CLICK_MOVE_PX:
                self._dialog._handle("left_click", pos, "qt")
        elif event.button() == Qt.MouseButton.RightButton:
            self._dialog._handle("right_click", pos, "qt")

    # ---- painting ----

    def _paint(self, p: QPainter, rect: QRectF) -> None:
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(QColor(theme.HAIRLINE), 1.0))
        p.setBrush(QColor(theme.SURFACE))
        p.drawRoundedRect(r, theme.RADIUS_XL, theme.RADIUS_XL)
        # subtle dot grid
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.color(theme.WHITE, 0.06))
        for gx in range(24, int(r.width()), 32):
            for gy in range(24, int(r.height()), 32):
                p.drawEllipse(QPointF(gx, gy), 1.2, 1.2)
        d = self._dialog
        if d.current_step == OnboardingStep.DRAG:
            self._paint_drag(p)
        else:
            self._paint_targets(p)

    def _paint_targets(self, p: QPainter) -> None:
        d = self._dialog
        positions = TARGET_POSITIONS.get(d.current_step, ())
        active = d.active_target_index
        rad = TARGET_DIAMETER / 2.0
        for i, _ in enumerate(positions):
            c = d.target_center(i)
            done = d.current_step == OnboardingStep.POINT and i < d.successes
            if i == active and not d.step_complete:
                hover = d.cursor_inside_target
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(theme.color(theme.ACCENT, 0.22 if hover else 0.11))
                p.drawEllipse(c, rad + 14, rad + 14)
                p.setPen(QPen(ACCENT, 3))
                p.setBrush(theme.mix(theme.RAISED, ACCENT, 0.34 if hover else 0.12))
                p.drawEllipse(c, rad, rad)
                p.setPen(QPen(QColor(theme.ACCENT_TEXT), 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(c, rad * 0.55, rad * 0.55)
                p.setBrush(QColor(theme.ACCENT_TEXT))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(c, 6, 6)
            elif done or (d.step_complete and i == active):
                p.setPen(QPen(SUCCESS, 3))
                p.setBrush(theme.mix(theme.RAISED, SUCCESS, 0.22))
                p.drawEllipse(c, rad * 0.7, rad * 0.7)
                self._check(p, c, rad * 0.32)
            elif d.current_step == OnboardingStep.POINT:
                p.setPen(QPen(QColor(theme.STROKE), 2, Qt.PenStyle.DashLine))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(c, rad * 0.7, rad * 0.7)
        if d.flash_miss_pos is not None:
            p.setPen(QPen(WARN, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(d.flash_miss_pos, 14, 14)

    def _paint_drag(self, p: QPainter) -> None:
        d = self._dialog
        zone = d.zone_rect()
        ok = d.step_complete
        p.setPen(QPen(SUCCESS, 2.5, Qt.PenStyle.SolidLine if ok else Qt.PenStyle.DashLine))
        fill = QColor(SUCCESS)
        fill.setAlpha(60 if ok else 26)
        p.setBrush(fill)
        p.drawRoundedRect(zone, 18, 18)
        p.setPen(MUTED if not ok else SUCCESS)
        p.setFont(theme.bold(theme.TEXT_PX["body"]))
        p.drawText(zone.adjusted(0, 0, 0, -10), int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom),
                   "Buraya bırak" if not ok else "Bırakıldı")
        box = d.box_rect()
        p.setPen(QPen(QColor(theme.ACCENT_HOVER) if d.dragging else ACCENT, 3))
        p.setBrush(theme.mix(theme.RAISED, ACCENT, 0.42 if d.dragging else 0.20))
        p.drawRoundedRect(box, 14, 14)
        if ok:
            self._check(p, box.center(), 18)
        else:
            icons.paint(p, "hand", QRectF(box.center().x() - 18, box.center().y() - 18, 36, 36), theme.ACCENT_TEXT)

    @staticmethod
    def _check(p: QPainter, c: QPointF, s: float) -> None:
        pen = QPen(SUCCESS, 4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPolyline([QPointF(c.x() - s, c.y()), QPointF(c.x() - s * 0.3, c.y() + s * 0.7),
                        QPointF(c.x() + s, c.y() - s * 0.6)])


class OnboardingDialog(DarkTitleBar, QDialog):
    """Interactive first-run tutorial (about 900x600, not always on top)."""

    completed = Signal()
    skipped = Signal()

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        hotkey: str,
        dominant_hand: str = "right",
        live: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Onboarding")
        self.setWindowTitle("Holoscobe — Eğitim")
        theme.install()
        self.resize(900, 600)
        self.hotkey = hotkey or "Ctrl+Alt+Shift+F12"
        self.dominant_hand = dominant_hand if dominant_hand in _HAND_TR else "right"
        self.live = bool(live)
        self.auto_advance_ms: Optional[int] = AUTO_ADVANCE_MS
        self._texts = _step_texts(_HAND_TR[self.dominant_hand])
        self._clock = QElapsedTimer()
        self._clock.start()

        self._index = 0
        self._successes = 0
        self._complete = False
        self._hint_forced = False
        self._cursor: Optional[QPointF] = None
        self._dragging = False
        self._drag_offset = QPointF()
        self._box_center_n: tuple[float, float] = BOX_START
        self._miss_pos: Optional[QPointF] = None
        self._last_counted: dict[str, tuple[float, QPointF, str]] = {}
        self._finished = False

        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.setInterval(HINT_IDLE_MS)
        self._idle_timer.timeout.connect(self._on_idle)
        self._miss_timer = QTimer(self)
        self._miss_timer.setSingleShot(True)
        self._miss_timer.setInterval(450)
        self._miss_timer.timeout.connect(self._clear_miss)

        self._build_ui()
        self._enter_step(0)

    # ---------- layout ----------

    def _build_ui(self) -> None:
        root = vbox(self, 14, 32, 22, 32, 20)

        top = QHBoxLayout()
        self.dots = ProgressDots(len(STEP_ORDER))
        self.step_label = label("", "caption")
        top.addWidget(self.dots, 0, Qt.AlignmentFlag.AlignVCenter)
        top.addStretch(1)
        top.addWidget(self.step_label)
        root.addLayout(top)

        head = QHBoxLayout()
        titles = vbox(None, 4)
        self.title_label = label("", "display")
        self.subtitle_label = label("", "lead", True)
        titles.addWidget(self.title_label)
        titles.addWidget(self.subtitle_label)
        head.addLayout(titles, 1)
        self.counter_label = label("", "counter")
        head.addWidget(self.counter_label, 0, Qt.AlignmentFlag.AlignBottom)
        root.addLayout(head)

        self.stack = QStackedWidget()
        self.page_welcome = self._build_welcome_page()
        self.practice = PracticeArea(self)
        self.page_modes = self._build_modes_page()
        self.page_done = self._build_done_page()
        for w in (self.page_welcome, self.practice, self.page_modes, self.page_done):
            self.stack.addWidget(w)
        root.addWidget(self.stack, 1)

        self.hint_label = Banner("", theme.ACCENT, "hand")
        root.addWidget(self.hint_label)

        foot = hbox(None, 8)
        self.btn_skip = button("Atla", "ghost", auto_default=False)
        self.status_label = label("", "success")
        self.btn_back = button("Geri", width=92, auto_default=False)
        self.btn_next = button("İleri", "primary", width=112)
        self.btn_next.setDefault(True)
        foot.addWidget(self.btn_skip)
        foot.addStretch(1)
        foot.addWidget(self.status_label)
        foot.addSpacing(16)
        foot.addWidget(self.btn_back)
        foot.addWidget(self.btn_next)
        root.addLayout(foot)

        self.btn_skip.clicked.connect(self.skip)
        self.btn_back.clicked.connect(self.go_back)
        self.btn_next.clicked.connect(self.go_next)

    def _build_welcome_page(self) -> QWidget:
        return _scene_page("welcome", (
            ("elbow", "Dirseğini masaya daya", "Kolun yorulmaz, imleç daha az titrer."),
            ("distance", "Elini kameradan 40–70 cm uzakta tut", "Elin kadrajda tam görünsün."),
            ("light", "Yüzün önden aydınlık olsun", "Arkanda pencere ya da güçlü ışık olmasın."),
            ("shield", f"Acil durdurma: {self.hotkey}", "Her an tüm girdileri bırakır ve kontrolü duraklatır."),
            ("clap", "İki elle bir kez el çırp", "Kontrolü etkinleştirir; yeniden çırpınca duraklatır."),
            ("play", "Hazır olunca Başla'ya bas", "Her adımı istediğin zaman Atla ile geçebilirsin."),
        ))

    def _build_modes_page(self) -> QWidget:
        return _scene_page("modes", (
            ("more", "Mod çarkı", "Sol elinle V yap ve yarım saniye tut; V ile dilime yönel, yumrukla seç."),
            ("scroll", "Kaydırma modu", "Pinch yap ve eli yukarı ya da aşağı taşı: sayfa dikey kayar."),
            ("commands", "Komutlar modu", "\n".join(
                ["Sola ya da sağa kaydır: önceki / sonraki (sunum, tarayıcı, medya, masaüstü)",
                 *(f"{g}: {r}" for g, r in COMMANDS_GUIDE_TR[2:])])),
            ("timer", "Bekleyerek tıkla",
             "Ayarlar > İmleç'ten açarsan imleci sabit tutman sol tık yapar; halka dolunca tıklar."),
        ))

    def _build_done_page(self) -> QWidget:
        return _scene_page("done", (
            ("check", "Öğrendiklerin",
             "İmleç · Tık · Çift tık · Sağ tık · Sürükle bırak · Kaydırma ve Komutlar modları."),
            ("guide", "Unutursan",
             "Tepsi menüsündeki Hareket Rehberi tüm hareketleri listeler. Eğitimi \"Eğitimi başlat\" "
             "ile yeniden açabilirsin."),
            ("shield", "Güvenlik", f"Bir şey ters giderse {self.hotkey} ile hemen durdur."),
        ), 28)

    # ---------- public state ----------

    @property
    def current_step(self) -> OnboardingStep:
        return STEP_ORDER[self._index]

    @property
    def successes(self) -> int:
        return self._successes

    @property
    def required(self) -> int:
        return REQUIRED_SUCCESSES.get(self.current_step, 0)

    @property
    def step_complete(self) -> bool:
        return self._complete

    @property
    def hint_visible(self) -> bool:
        return not self.hint_label.isHidden()

    @property
    def dragging(self) -> bool:
        return self._dragging

    @property
    def flash_miss_pos(self) -> Optional[QPointF]:
        return self._miss_pos

    @property
    def active_target_index(self) -> int:
        positions = TARGET_POSITIONS.get(self.current_step, ())
        if not positions:
            return -1
        if self.current_step == OnboardingStep.POINT:
            return min(self._successes, len(positions) - 1)
        return self._successes % len(positions)

    @property
    def cursor_inside_target(self) -> bool:
        return self._cursor is not None and self._in_target(self._cursor)

    def target_center(self, index: Optional[int] = None) -> QPointF:
        """Center of a target in practice-area coordinates (active target by default)."""
        positions = TARGET_POSITIONS.get(self.current_step, ((0.5, 0.5),))
        i = self.active_target_index if index is None else index
        nx, ny = positions[max(0, min(len(positions) - 1, i))]
        return QPointF(nx * self.practice.width(), ny * self.practice.height())

    def box_rect(self) -> QRectF:
        return self._square(self._box_center_n, BOX_SIZE)

    def zone_rect(self) -> QRectF:
        return self._square(ZONE_CENTER, ZONE_SIZE)

    def _square(self, center: tuple[float, float], size: float) -> QRectF:
        cx, cy = center[0] * self.practice.width(), center[1] * self.practice.height()
        return QRectF(cx - size / 2, cy - size / 2, size, size)

    # ---------- navigation ----------

    @Slot()
    def go_next(self) -> None:
        if self.current_step == OnboardingStep.DONE:
            self.finish()
            return
        self._enter_step(self._index + 1)

    @Slot()
    def go_back(self) -> None:
        if self._index > 0:
            self._enter_step(self._index - 1)

    def _end(self, signal) -> bool:
        """Report the outcome once."""
        first, self._finished = not self._finished, True
        if first:
            self._idle_timer.stop()
            signal.emit()
        return first

    @Slot()
    def skip(self) -> None:
        self.reject()

    @Slot()
    def finish(self) -> None:
        if self._end(self.completed):
            self.accept()

    def reject(self) -> None:  # window close / Esc counts as skip
        self._end(self.skipped)
        super().reject()

    def _enter_step(self, index: int) -> None:
        self._index = max(0, min(len(STEP_ORDER) - 1, index))
        step = self.current_step
        self._successes = 0
        self._complete = False
        self._hint_forced = False
        self._dragging = False
        self._box_center_n = BOX_START
        self._miss_pos = None
        self._last_counted.clear()
        text = self._texts[step]
        self.title_label.setText(text.title)
        self.subtitle_label.setText(text.subtitle)
        self.hint_label.setText(text.hint)
        self.step_label.setText(f"Adım {self._index + 1} / {len(STEP_ORDER)}")
        self.dots.set_current(self._index)
        self.status_label.setText("")
        page = {
            OnboardingStep.WELCOME: self.page_welcome,
            OnboardingStep.MODES: self.page_modes,
            OnboardingStep.DONE: self.page_done,
        }.get(step, self.practice)
        policy = self.hint_label.sizePolicy()          # a vanishing hint must not move the targets
        policy.setRetainSizeWhenHidden(step in REQUIRED_SUCCESSES)
        self.hint_label.setSizePolicy(policy)
        self.stack.setCurrentWidget(page)
        self.btn_back.setEnabled(self._index > 0)
        self.btn_next.setText("Bitir" if step == OnboardingStep.DONE else
                              ("Başla" if step == OnboardingStep.WELCOME else "İleri"))
        self.btn_skip.setVisible(True)
        self._update_counter()
        self._update_hint()
        if step in REQUIRED_SUCCESSES:
            self._idle_timer.start()
        else:
            self._idle_timer.stop()
        self.practice.update()

    # ---------- input ----------

    @Slot(str, int, int)
    def on_action(self, kind: str, x: int, y: int) -> None:
        """Controller action (ActionKind value) at physical virtual-desktop px."""
        if self._finished:
            return
        kind = str(getattr(kind, "value", kind))
        if kind == "key_command":
            return
        logical = physical_to_logical(int(x), int(y))
        local = QPointF(self.practice.mapFromGlobal(QPoint(logical.x(), logical.y())))
        self._handle(kind, local, "action")

    def _now(self) -> float:
        return float(self._clock.elapsed())

    def _is_duplicate(self, kind: str, pos: QPointF, source: str) -> bool:
        if kind == "move_pointer":
            return False
        prev = self._last_counted.get(kind)
        now = self._now()
        if prev is not None:
            t, ppos, psrc = prev
            if psrc != source and now - t <= DEDUPE_MS and \
                    math.hypot(pos.x() - ppos.x(), pos.y() - ppos.y()) <= DEDUPE_PX:
                return True
        self._last_counted[kind] = (now, QPointF(pos), source)
        return False

    def _in_target(self, pos: QPointF) -> bool:
        if self.active_target_index < 0:
            return False
        c = self.target_center()
        return math.hypot(pos.x() - c.x(), pos.y() - c.y()) <= TARGET_DIAMETER / 2 + HIT_TOLERANCE

    def _inside_practice(self, pos: QPointF) -> bool:
        return QRectF(self.practice.rect()).contains(pos)

    def _handle(self, kind: str, pos: QPointF, source: str) -> None:
        step = self.current_step
        if step not in REQUIRED_SUCCESSES or self._finished:
            return
        if self._is_duplicate(kind, pos, source):
            return
        if kind == "move_pointer":
            self._cursor = QPointF(pos) if self._inside_practice(pos) else None
        if step == OnboardingStep.DRAG:
            self._handle_drag(kind, pos)
            self.practice.update()
            return
        if self._complete:
            self.practice.update()
            return
        wanted = {
            OnboardingStep.POINT: ("move_pointer", "left_click", "left_down"),
            OnboardingStep.CLICK: ("left_click",),
            OnboardingStep.DOUBLE_CLICK: ("double_click",),
            OnboardingStep.RIGHT_CLICK: ("right_click",),
        }[step]
        if kind in wanted:
            if self._in_target(pos):
                self._register_success()
            elif kind != "move_pointer" and self._inside_practice(pos):
                self._miss(pos)
        self.practice.update()

    def _handle_drag(self, kind: str, pos: QPointF) -> None:
        if self._complete:
            return
        w, h = max(1, self.practice.width()), max(1, self.practice.height())
        if kind == "left_down":
            if self.box_rect().adjusted(-HIT_TOLERANCE, -HIT_TOLERANCE, HIT_TOLERANCE, HIT_TOLERANCE).contains(pos):
                self._dragging = True
                self._drag_offset = self.box_rect().center() - pos
            elif self._inside_practice(pos):
                self._miss(pos)
        elif self._dragging and kind in ("move_pointer", "left_up"):
            c = pos + self._drag_offset
            self._box_center_n = (min(1.0, max(0.0, c.x() / w)), min(1.0, max(0.0, c.y() / h)))
            self._dragging = kind == "move_pointer"
            if not self._dragging and self.zone_rect().contains(self.box_rect().center()):
                self._box_center_n = ZONE_CENTER
                self._register_success()

    def _miss(self, pos: QPointF) -> None:
        self._miss_pos = QPointF(pos)
        self._miss_timer.start()

    @Slot()
    def _clear_miss(self) -> None:
        self._miss_pos = None
        self.practice.update()

    def _register_success(self) -> None:
        self._successes += 1
        self._hint_forced = False
        self._idle_timer.start()
        if self._successes >= self.required:
            self._complete = True
            self._idle_timer.stop()
            self.status_label.setText("Harika! ✓")
            if self.auto_advance_ms is not None:
                token = self._index
                QTimer.singleShot(int(self.auto_advance_ms), lambda: self._auto_advance(token))
        else:
            self.status_label.setText("Güzel!")
        self._update_counter()
        self._update_hint()

    def _auto_advance(self, token: int) -> None:
        if not self._finished and self._index == token and self._complete:
            self.go_next()

    @Slot()
    def _on_idle(self) -> None:
        if self.current_step in REQUIRED_SUCCESSES and not self._complete:
            self._hint_forced = True
            self._update_hint()

    def _update_hint(self) -> None:
        text = self._texts[self.current_step].hint
        show = bool(text) and not self._complete and (self._hint_forced or self._successes < HINT_HIDE_AFTER)
        self.hint_label.setVisible(show)

    def _update_counter(self) -> None:
        req = self.required
        self.counter_label.setText(f"{min(self._successes, req)} / {req}" if req else "")
