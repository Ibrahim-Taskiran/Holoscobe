"""Step-by-step calibration wizard and result dataclasses for Holoscobe.

Steps:
1. Neutral pose (Nötr duruş)
2. Movement area corners (Hareket alanının köşeleri)
3. Relaxed pinch repetitions (Rahat kıstırma / pinch tekrarları)
4. Clap repetitions (El çırpma tekrarları)
5. Summary & result emission (Özet ve sonuç)

During calibration, live OS commands are strictly suppressed.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from statistics import fmean
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, Signal, Slot
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QProgressBar,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from handcontrol.contracts import (
    ControlState,
    FrameFeatures,
    Handedness,
    Quality,
)
from handcontrol.ui import icons, theme
from handcontrol.ui.illustrations import Illustration
from handcontrol.ui.preview import CameraPreviewWidget
from handcontrol.ui.viewmodel import HANDEDNESS_LABELS_TR, UiBridge
from handcontrol.ui.widgets import DarkTitleBar, hbox, vbox, Banner, Card, SettingRow, button, label
from handcontrol.ui.painted import PaintedWidget


class CalibrationStep(Enum):
    """Sequential steps of the calibration wizard."""

    NEUTRAL_POSE = "neutral_pose"
    MOVEMENT_CORNERS = "movement_corners"
    PINCH_REPEATS = "pinch_repeats"
    CLAP_REPEATS = "clap_repeats"
    SUMMARY = "summary"


STEP_ORDER: tuple[CalibrationStep, ...] = tuple(CalibrationStep)


@dataclass(frozen=True)
class _StepInfo:
    short: str
    title: str
    text: str
    count: str = ""                  # name of the counted samples
    required: int = 0


_STEPS: dict[CalibrationStep, _StepInfo] = {
    CalibrationStep.NEUTRAL_POSE: _StepInfo(
        "Nötr duruş", "1. Adım: Nötr Duruş",
        "Elinizi kameranın ortasında rahat ve açık bir nötr duruşta tutun. "
        "Avuç içi ölçeği ve temel referans kaydedilecektir.", "Nötr duruş örnekleri", 5),
    CalibrationStep.MOVEMENT_CORNERS: _StepInfo(
        "Köşeler", "2. Adım: Hareket Alanının Köşeleri",
        "Baskın elinizin işaret parmağıyla ekrandaki dört köşe hedefini "
        "(Sol-Üst, Sağ-Üst, Sağ-Alt, Sol-Alt) sırasıyla işaret edin.", "Kaydedilen köşe noktaları", 4),
    CalibrationStep.PINCH_REPEATS: _StepInfo(
        "Pinch", "3. Adım: Rahat Kıstırma (Pinch) Tekrarları",
        "Başparmak ve işaret parmağınızı rahat bir şekilde birkaç kez birleştirip "
        "bırakın (kıstırma / pinch tekrarı).", "Kıstırma (Pinch) tekrarları", 3),
    CalibrationStep.CLAP_REPEATS: _StepInfo(
        "El çırpma", "4. Adım: El Çırpma Tekrarları",
        "İki elinizi kameranın görebileceği şekilde rahatça yaklaştırıp "
        "el çırpma hareketini birkaç kez tekrarlayın.", "El çırpma tekrarları", 3),
    CalibrationStep.SUMMARY: _StepInfo(
        "Özet", "Kalibrasyon Özeti ve Tamamlama",
        "Kalibrasyon ölçümleri tamamlandı. Hesaplanan hareket sınırları ve "
        "eşik değerlerini onaylayarak kaydedilmeleri için gönderebilirsiniz."),
}


@dataclass(frozen=True)
class MovementBounds:
    """Normalized [0, 1] comfortable movement area bounds."""

    left: float = 0.15
    top: float = 0.15
    right: float = 0.85
    bottom: float = 0.85


@dataclass(frozen=True)
class CalibrationThresholds:
    """Calibrated gesture thresholds in palm units."""

    pinch_on: float = 0.28
    pinch_off: float = 0.42
    clap_arm_distance: float = 2.0
    clap_contact_distance: float = 0.85
    clap_separate_distance: float = 1.6
    neutral_palm_scale_px: float = 80.0


@dataclass(frozen=True)
class CalibrationResult:
    """Returned by CalibrationWizard when calibration finishes.

    Persistence is handled by the caller/manager.
    """

    bounds: MovementBounds = field(default_factory=MovementBounds)
    thresholds: CalibrationThresholds = field(default_factory=CalibrationThresholds)
    dominant_hand: Handedness = Handedness.RIGHT


class CalibrationPreviewCanvas(CameraPreviewWidget):
    """CameraPreviewWidget extended with calibration guide marks."""

    def __init__(
        self,
        bridge: Optional[UiBridge] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(bridge=bridge, parent=parent)
        self._step: CalibrationStep = CalibrationStep.NEUTRAL_POSE
        self._corner_points: list[tuple[float, float]] = []
        self._notice_top = True

    def set_calibration_step(
        self,
        step: CalibrationStep,
        corner_points: Optional[list[tuple[float, float]]] = None,
    ) -> None:
        self._step = step
        if corner_points is not None:
            self._corner_points = list(corner_points)
        self.update()

    def _paint(self, painter: QPainter, full_rect: QRectF) -> None:
        super()._paint(painter, full_rect)
        canvas = self._canvas_rect()
        self._draw_guide_marks(painter, canvas)

    def _draw_guide_marks(self, painter: QPainter, canvas: QRectF) -> None:
        painter.save()
        guide_pen = QPen(theme.color(theme.ACCENT, 0.9), 2.0, Qt.PenStyle.DashLine)
        painter.setPen(guide_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if self._step == CalibrationStep.NEUTRAL_POSE:
            target_rect = QRectF(0.0, 0.0, canvas.width() * 0.34, canvas.height() * 0.44)
            target_rect.moveCenter(canvas.center())
            painter.drawRoundedRect(target_rect, 12.0, 12.0)
            self._mark_label(painter, QPointF(target_rect.center().x(), target_rect.top() - 20.0), "Nötr Duruş Alanı",
                             theme.ACCENT_TEXT)

        elif self._step == CalibrationStep.MOVEMENT_CORNERS:
            corners = [
                (0.18, 0.18, "Sol-Üst"),
                (0.82, 0.18, "Sağ-Üst"),
                (0.82, 0.82, "Sağ-Alt"),
                (0.18, 0.82, "Sol-Alt"),
            ]
            for idx, (nx, ny, name) in enumerate(corners):
                pt = QPointF(
                    canvas.left() + nx * canvas.width(),
                    canvas.top() + ny * canvas.height(),
                )
                done = idx < len(self._corner_points)
                now = idx == len(self._corner_points)
                tone = theme.SUCCESS if done else theme.ACCENT if now else theme.TEXT_SOFT
                painter.setPen(QPen(QColor(tone), 2.4))
                painter.setBrush(theme.color(tone, 0.25) if done or now else Qt.BrushStyle.NoBrush)
                painter.drawEllipse(pt, 15.0, 15.0)
                if done:
                    icons.paint(painter, "check", QRectF(pt.x() - 9.0, pt.y() - 9.0, 18.0, 18.0), tone, 2.6)
                self._mark_label(painter, QPointF(pt.x(), pt.y() + 32.0), name, tone)
                painter.setBrush(Qt.BrushStyle.NoBrush)

        elif self._step == CalibrationStep.PINCH_REPEATS:
            c = canvas.center()
            painter.setPen(QPen(theme.color(theme.ACCENT, 0.9), 2.2, Qt.PenStyle.DotLine))
            painter.drawEllipse(c, 42.0, 42.0)
            painter.drawEllipse(c, 16.0, 16.0)

        elif self._step == CalibrationStep.CLAP_REPEATS:
            cy = canvas.center().y()
            left_pt = QPointF(canvas.left() + canvas.width() * 0.30, cy)
            right_pt = QPointF(canvas.left() + canvas.width() * 0.70, cy)
            painter.setPen(QPen(theme.color(theme.ACCENT, 0.9), 2.2, Qt.PenStyle.DashLine))
            painter.drawEllipse(left_pt, 28.0, 28.0)
            painter.drawEllipse(right_pt, 28.0, 28.0)
            painter.drawLine(left_pt, right_pt)

        painter.restore()

    @staticmethod
    def _mark_label(painter: QPainter, center: QPointF, text: str, tone: str) -> None:
        painter.save()
        painter.setFont(theme.bold(theme.TEXT_PX["caption"]))
        w = painter.fontMetrics().horizontalAdvance(text) + 20.0
        box = QRectF(center.x() - w / 2, center.y() - 12.0, w, 24.0)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.color(theme.BG, 0.78))
        painter.drawRoundedRect(box, 12.0, 12.0)
        painter.setPen(QColor(tone))
        painter.drawText(box, int(Qt.AlignmentFlag.AlignCenter), text)
        painter.restore()


class StepBar(PaintedWidget):
    """Numbered steps with their names; done steps show a check mark."""

    def __init__(self, names: tuple[str, ...], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._names, self._current = names, 0
        self.setFixedHeight(54)

    def set_current(self, index: int) -> None:
        if index != self._current:
            self._current = index
            self.update()

    def _paint(self, p: QPainter, rect: QRectF) -> None:
        n = len(self._names)
        cell = self.width() / n
        for i in range(n - 1):
            p.setPen(QPen(QColor(theme.SUCCESS if i < self._current else theme.HAIRLINE), 2))
            p.drawLine(QPointF(cell * (i + 0.5) + 20, 16), QPointF(cell * (i + 1.5) - 20, 16))
        for i, name in enumerate(self._names):
            c = QPointF(cell * (i + 0.5), 16)
            done, now = i < self._current, i == self._current
            p.setPen(QPen(QColor(theme.ACCENT if now else theme.SUCCESS if done else theme.STROKE), 1.6))
            p.setBrush(QColor(theme.ACCENT) if now else theme.color(theme.SUCCESS, 0.16) if done
                       else QColor(theme.SURFACE))
            p.drawEllipse(c, 13, 13)
            if done:
                icons.paint(p, "check", QRectF(c.x() - 8, c.y() - 8, 16, 16), theme.SUCCESS, 2.6)
            else:
                p.setFont(theme.bold(theme.TEXT_PX["caption"]))
                p.setPen(QColor(theme.ON_ACCENT if now else theme.MUTED))
                p.drawText(QRectF(c.x() - 13, c.y() - 13, 26, 26), int(Qt.AlignmentFlag.AlignCenter), str(i + 1))
            p.setFont(theme.bold(theme.TEXT_PX["caption"]) if now else theme.font(theme.TEXT_PX["caption"]))
            p.setPen(QColor(theme.TEXT if now else theme.MUTED))
            p.drawText(QRectF(cell * i, 34, cell, 18), int(Qt.AlignmentFlag.AlignCenter), name)


class CalibrationWizard(DarkTitleBar, QDialog):
    """Step-by-step hand gesture calibration dialog.

    The controller is in its calibration state meanwhile, so no OS command is produced.
    """

    step_changed = Signal(object)               # CalibrationStep

    def __init__(
        self,
        bridge: Optional[UiBridge] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._bridge = bridge
        self._step_index: int = 0

        # Collected calibration measurements
        self._neutral_scales: list[float] = []
        self._dominant_hand: Handedness = Handedness.RIGHT
        self._corner_points: list[tuple[float, float]] = []
        self._pinch_min_distances: list[float] = []
        self._pinch_open_distances: list[float] = []
        self._pinch_currently_closed: bool = False
        self._current_pinch_min: float = 1.0
        self._clap_min_distances: list[float] = []
        self._clap_max_distances: list[float] = []
        self._clap_currently_near: bool = False

        self.setWindowTitle("Holoscobe — El Hareketi Kalibrasyonu")
        theme.install()
        self.resize(860, 720)
        self.setMinimumSize(700, 560)

        self._build_ui()
        self._refresh_step_ui()

        if self._bridge is not None:
            self._bridge.frame_updated.connect(self._on_bridge_frame)

    @property
    def current_step(self) -> CalibrationStep:
        return STEP_ORDER[self._step_index]

    def _build_ui(self) -> None:
        root = vbox(self, 0, 0, 0, 0, 0)
        body = vbox(None, 12, 32, 22, 32, 18)
        root.addLayout(body, 1)

        self.step_bar = StepBar(tuple(_STEPS[step].short for step in STEP_ORDER))
        body.addWidget(self.step_bar)
        self.step_title_label = label("", "title")
        self.instruction_label = label("", "lead", True)
        body.addWidget(self.step_title_label)
        body.addWidget(self.instruction_label)

        self.preview = CalibrationPreviewCanvas(bridge=self._bridge, parent=self)
        self.preview.set_show_details(False)
        self.preview.setMinimumSize(360, 200)
        self._stage = QStackedWidget()
        self._stage.addWidget(self.preview)
        self._stage.addWidget(self._build_summary())
        body.addWidget(self._stage, 1)

        progress_row = hbox(None, 16)
        self.step_status_label = label("", "value")
        self.step_progress_bar = QProgressBar()
        self.step_progress_bar.setRange(0, 100)
        self.step_progress_bar.setTextVisible(False)
        progress_row.addWidget(self.step_status_label)
        progress_row.addWidget(self.step_progress_bar, 1)
        body.addLayout(progress_row)

        self.safety_banner = Banner("Kalibrasyon Modu: İşletim sistemi fare/klavye komutları devre dışıdır.",
                                    theme.SUCCESS, "shield")
        body.addWidget(self.safety_banner)

        footer = QFrame()
        footer.setProperty("role", "footer")
        button_row = hbox(footer, 8, 24, 12, 32, 12)
        self.btn_reset = button("Baştan Başla", "ghost", "undo", auto_default=False)
        self.btn_cancel = button("İptal", "ghost", auto_default=False)
        self.btn_prev = button("Geri", width=92, auto_default=False)
        self.btn_sample = button("Örnek Kaydet", auto_default=False)
        self.btn_next = button("İleri", "primary", width=112)
        self.btn_finish = button("Kalibrasyonu Tamamla", "primary")
        for b, slot in ((self.btn_reset, self.reset_calibration), (self.btn_cancel, self.cancel_calibration),
                        (self.btn_prev, self.previous_step), (self.btn_sample, self.record_manual_step_sample),
                        (self.btn_next, self.next_step), (self.btn_finish, self.finish_calibration)):
            b.clicked.connect(slot)
            button_row.addWidget(b)
        button_row.insertStretch(2, 1)
        root.addWidget(footer)

    def _build_summary(self) -> QWidget:
        page = QWidget()
        row = hbox(page, 20, 0, 0, 0, 0)
        row.addWidget(Illustration("done"), 1)
        self._metrics = {}
        card = Card()
        for key, title, text in (("area", "Hareket alanı", "Kamera görüntüsünün kullanılan kısmı"),
                                 ("pinch", "Pinch aç / kapa", "Parmak uçları arası, avuç birimi"),
                                 ("clap", "El çırpma", "Temas / ayrılma, avuç birimi"),
                                 ("hand", "Baskın el", "Nötr duruşta görülen el")):
            self._metrics[key] = label("", "counter")
            card.add(SettingRow(title, text, self._metrics[key]))
        column = QVBoxLayout()
        column.addStretch(1)
        column.addWidget(card)
        column.addStretch(1)
        row.addLayout(column, 1)
        return page

    @Slot(object)
    def _on_bridge_frame(self, frame: Optional[FrameFeatures]) -> None:
        if frame is not None:
            self.feed_frame(frame)

    def feed_frame(
        self,
        frame: FrameFeatures,
        fps: Optional[float] = None,
        sample_age_ms: Optional[float] = None,
    ) -> None:
        """Process a FrameFeatures sample for the current calibration step."""
        self.preview.set_frame(frame, fps=fps, sample_age_ms=sample_age_ms)
        usable_hands = [h for h in frame.hands if h.quality == Quality.USABLE]
        if not usable_hands:
            return

        step = self.current_step
        primary = usable_hands[0]

        if step == CalibrationStep.NEUTRAL_POSE:
            if primary.palm_scale_px > 0:
                self.record_neutral_sample(
                    palm_scale_px=primary.palm_scale_px,
                    handedness=primary.handedness,
                )

        elif step == CalibrationStep.MOVEMENT_CORNERS:
            if frame.width > 0 and frame.height > 0:
                norm_x = max(0.0, min(1.0, primary.index_tip_px[0] / frame.width))
                norm_y = max(0.0, min(1.0, primary.index_tip_px[1] / frame.height))
                if len(self._corner_points) < _STEPS[step].required:
                    self.record_corner_point(norm_x, norm_y)

        elif step == CalibrationStep.PINCH_REPEATS:
            dist = primary.pinch_distance
            if dist <= 0.34:
                self._pinch_currently_closed = True
                self._current_pinch_min = min(self._current_pinch_min, dist)
            elif dist >= 0.45:
                self._pinch_open_distances.append(dist)
                if self._pinch_currently_closed:
                    self.record_pinch_sample(
                        closed_distance=self._current_pinch_min,
                        open_distance=dist,
                    )
                    self._pinch_currently_closed = False
                    self._current_pinch_min = 1.0

        elif step == CalibrationStep.CLAP_REPEATS and len(usable_hands) >= 2:
            h1, h2 = usable_hands[0], usable_hands[1]
            avg_scale = max(1.0, (h1.palm_scale_px + h2.palm_scale_px) * 0.5)
            dx = h1.palm_center_px[0] - h2.palm_center_px[0]
            dy = h1.palm_center_px[1] - h2.palm_center_px[1]
            palm_dist = math.hypot(dx, dy) / avg_scale
            if palm_dist <= 0.95:
                self._clap_currently_near = True
                self._clap_min_distances.append(palm_dist)
            elif palm_dist >= 1.55 and self._clap_currently_near:
                self.record_clap_sample(
                    contact_distance=min(self._clap_min_distances[-1:], default=0.85),
                    separate_distance=palm_dist,
                )
                self._clap_currently_near = False

    def record_neutral_sample(
        self,
        palm_scale_px: float = 82.0,
        handedness: Handedness = Handedness.RIGHT,
    ) -> None:
        """Record a neutral pose sample."""
        self._neutral_scales.append(max(10.0, float(palm_scale_px)))
        if handedness != Handedness.UNKNOWN:
            self._dominant_hand = handedness
        self._refresh_step_ui()

    def record_corner_point(self, norm_x: float, norm_y: float) -> None:
        """Record a normalized corner point (x, y) in [0, 1]."""
        self._corner_points.append(
            (max(0.0, min(1.0, float(norm_x))), max(0.0, min(1.0, float(norm_y))))
        )
        self._refresh_step_ui()

    def record_pinch_sample(
        self,
        closed_distance: float = 0.24,
        open_distance: float = 0.48,
    ) -> None:
        """Record one completed relaxed pinch cycle."""
        self._pinch_min_distances.append(max(0.05, float(closed_distance)))
        self._pinch_open_distances.append(max(0.20, float(open_distance)))
        self._refresh_step_ui()

    def record_clap_sample(
        self,
        contact_distance: float = 0.80,
        separate_distance: float = 1.75,
    ) -> None:
        """Record one completed visual clap cycle."""
        self._clap_min_distances.append(max(0.20, float(contact_distance)))
        self._clap_max_distances.append(max(1.0, float(separate_distance)))
        self._refresh_step_ui()

    @Slot()
    def record_manual_step_sample(self) -> None:
        """Record a default sample for the current step (for guided/manual progression)."""
        step = self.current_step
        if step == CalibrationStep.NEUTRAL_POSE:
            self.record_neutral_sample(82.0, self._dominant_hand)
        elif step == CalibrationStep.MOVEMENT_CORNERS:
            self.record_corner_point(*((0.14, 0.16), (0.86, 0.16), (0.86, 0.84), (0.14, 0.84))[len(self._corner_points) % 4])
        elif step == CalibrationStep.PINCH_REPEATS:
            self.record_pinch_sample(0.23, 0.46)
        elif step == CalibrationStep.CLAP_REPEATS:
            self.record_clap_sample(0.78, 1.72)

    @Slot()
    def next_step(self) -> None:
        self._go(self._step_index + 1)

    @Slot()
    def previous_step(self) -> None:
        self._go(self._step_index - 1)

    def _go(self, index: int) -> None:
        if 0 <= index < len(STEP_ORDER) and index != self._step_index:
            self._step_index = index
            self._refresh_step_ui()
            self.step_changed.emit(self.current_step)

    @Slot()
    def reset_calibration(self) -> None:
        """Clear collected samples and restart at Step 1."""
        self._step_index = 0
        for samples in (self._neutral_scales, self._corner_points, self._pinch_min_distances,
                        self._pinch_open_distances, self._clap_min_distances, self._clap_max_distances):
            samples.clear()
        self._pinch_currently_closed = False
        self._clap_currently_near = False
        self._refresh_step_ui()
        self.step_changed.emit(self.current_step)

    def compute_result(self) -> CalibrationResult:
        """Compute MovementBounds and CalibrationThresholds from collected samples."""
        bounds = MovementBounds()
        if len(self._corner_points) >= 2:
            xs, ys = zip(*self._corner_points)
            left, top, right, bottom = min(xs), min(ys), max(xs), max(ys)
            if right - left < 0.15:
                left, right = bounds.left, bounds.right
            if bottom - top < 0.15:
                top, bottom = bounds.top, bounds.bottom
            bounds = MovementBounds(left, top, right, bottom)

        base = CalibrationThresholds()
        pinch_on, pinch_off = base.pinch_on, base.pinch_off
        if self._pinch_min_distances and self._pinch_open_distances:
            closed, opened = fmean(self._pinch_min_distances), fmean(self._pinch_open_distances)
            pinch_on = round(max(0.15, min(0.40, closed + (opened - closed) * 0.25)), 3)
            pinch_off = round(max(pinch_on + 0.08, min(0.65, closed + (opened - closed) * 0.65)), 3)
        contact, apart = base.clap_contact_distance, base.clap_separate_distance
        if self._clap_min_distances and self._clap_max_distances:
            contact = round(max(0.45, min(1.15, fmean(self._clap_min_distances) * 1.08)), 3)
            apart = round(max(contact + 0.40, min(2.20, fmean(self._clap_max_distances) * 0.95)), 3)
        thresholds = CalibrationThresholds(pinch_on, pinch_off, max(1.8, round(apart + 0.35, 2)), contact, apart,
                                           round(fmean(self._neutral_scales or [base.neutral_palm_scale_px]), 2))
        return CalibrationResult(bounds, thresholds, self._dominant_hand)

    @Slot()
    def finish_calibration(self) -> CalibrationResult:
        """Finalize calibration, emit CalibrationResult, and close dialog."""
        result = self.compute_result()
        if self._bridge is not None:
            self._bridge.calibration_completed.emit(result)
            self._bridge.update_status(control_state=ControlState.PAUSED)
        self.accept()
        return result

    @Slot()
    def cancel_calibration(self) -> None:
        """Cancel calibration without emitting a result."""
        if self._bridge is not None:
            self._bridge.calibration_cancelled.emit()
            self._bridge.update_status(control_state=ControlState.PAUSED)
        self.reject()

    def _refresh_step_ui(self) -> None:
        step = self.current_step
        info = _STEPS[step]
        self.step_title_label.setText(info.title)
        self.instruction_label.setText(info.text)
        self.preview.set_calibration_step(step, self._corner_points)

        samples = {CalibrationStep.NEUTRAL_POSE: self._neutral_scales, CalibrationStep.MOVEMENT_CORNERS: self._corner_points,
                   CalibrationStep.PINCH_REPEATS: self._pinch_min_distances,
                   CalibrationStep.CLAP_REPEATS: self._clap_min_distances}.get(step)
        if samples is not None:
            pct = min(100, int((len(samples) / info.required) * 100))
            status = f"{info.count}: {len(samples)} / {info.required}"
        else:
            res = self.compute_result()
            pct, status = 100, ""
            numbers = {
                "area": f"%{round((res.bounds.right - res.bounds.left) * 100)} × "
                        f"%{round((res.bounds.bottom - res.bounds.top) * 100)}",
                "pinch": f"{res.thresholds.pinch_on:.2f} / {res.thresholds.pinch_off:.2f}",
                "clap": f"{res.thresholds.clap_contact_distance:.2f} / {res.thresholds.clap_separate_distance:.2f}",
                "hand": HANDEDNESS_LABELS_TR[res.dominant_hand],
            }
            for key, text in numbers.items():
                self._metrics[key].setText(text.replace(".", ","))

        self.step_status_label.setText(status)
        self.step_progress_bar.setValue(pct)

        last = step == CalibrationStep.SUMMARY
        self.step_bar.set_current(self._step_index)
        self._stage.setCurrentIndex(1 if last else 0)
        self.btn_prev.setEnabled(self._step_index > 0)
        self.btn_next.setEnabled(not last)
        self.btn_next.setVisible(not last)
        self.btn_finish.setVisible(last)
        self.btn_sample.setVisible(not last)
        for w in (self.step_status_label, self.step_progress_bar):
            w.setVisible(not last)
        (self.btn_finish if last else self.btn_next).setDefault(True)
