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
from typing import Any, Mapping, Optional

from PySide6.QtCore import QPointF, QRectF, Qt, Signal, Slot
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from handcontrol.contracts import (
    ControlState,
    FrameFeatures,
    Handedness,
    Quality,
)
from handcontrol.ui.preview import CameraPreviewWidget
from handcontrol.ui.viewmodel import UiBridge


class CalibrationStep(Enum):
    """Sequential steps of the calibration wizard."""

    NEUTRAL_POSE = "neutral_pose"
    MOVEMENT_CORNERS = "movement_corners"
    PINCH_REPEATS = "pinch_repeats"
    CLAP_REPEATS = "clap_repeats"
    SUMMARY = "summary"


STEP_ORDER: tuple[CalibrationStep, ...] = (
    CalibrationStep.NEUTRAL_POSE,
    CalibrationStep.MOVEMENT_CORNERS,
    CalibrationStep.PINCH_REPEATS,
    CalibrationStep.CLAP_REPEATS,
    CalibrationStep.SUMMARY,
)

STEP_TITLES_TR: dict[CalibrationStep, str] = {
    CalibrationStep.NEUTRAL_POSE: "1. Adım: Nötr Duruş",
    CalibrationStep.MOVEMENT_CORNERS: "2. Adım: Hareket Alanının Köşeleri",
    CalibrationStep.PINCH_REPEATS: "3. Adım: Rahat Kıstırma (Pinch) Tekrarları",
    CalibrationStep.CLAP_REPEATS: "4. Adım: El Çırpma Tekrarları",
    CalibrationStep.SUMMARY: "Kalibrasyon Özeti ve Tamamlama",
}

STEP_INSTRUCTIONS_TR: dict[CalibrationStep, str] = {
    CalibrationStep.NEUTRAL_POSE: (
        "Elinizi kameranın ortasında rahat ve açık bir nötr duruşta tutun. "
        "Avuç içi ölçeği ve temel referans kaydedilecektir."
    ),
    CalibrationStep.MOVEMENT_CORNERS: (
        "Baskın elinizin işaret parmağıyla ekrandaki dört köşe hedefini "
        "(Sol-Üst, Sağ-Üst, Sağ-Alt, Sol-Alt) sırasıyla işaret edin."
    ),
    CalibrationStep.PINCH_REPEATS: (
        "Başparmak ve işaret parmağınızı rahat bir şekilde birkaç kez birleştirip "
        "bırakın (kıstırma / pinch tekrarı)."
    ),
    CalibrationStep.CLAP_REPEATS: (
        "İki elinizi kameranın görebileceği şekilde rahatça yaklaştırıp "
        "el çırpma hareketini birkaç kez tekrarlayın."
    ),
    CalibrationStep.SUMMARY: (
        "Kalibrasyon ölçümleri tamamlandı. Hesaplanan hareket sınırları ve "
        "eşik değerlerini onaylayarak kaydedilmeleri için gönderebilirsiniz."
    ),
}


@dataclass(frozen=True)
class MovementBounds:
    """Normalized [0, 1] comfortable movement area bounds."""

    left: float = 0.15
    top: float = 0.15
    right: float = 0.85
    bottom: float = 0.85

    def to_dict(self) -> dict[str, float]:
        return {
            "left": float(self.left),
            "top": float(self.top),
            "right": float(self.right),
            "bottom": float(self.bottom),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MovementBounds:
        left = max(0.0, min(0.9, float(data.get("left", 0.15))))
        top = max(0.0, min(0.9, float(data.get("top", 0.15))))
        right = max(left + 0.05, min(1.0, float(data.get("right", 0.85))))
        bottom = max(top + 0.05, min(1.0, float(data.get("bottom", 0.85))))
        return cls(left=left, top=top, right=right, bottom=bottom)


@dataclass(frozen=True)
class CalibrationThresholds:
    """Calibrated gesture thresholds in palm units."""

    pinch_on: float = 0.28
    pinch_off: float = 0.42
    clap_arm_distance: float = 2.0
    clap_contact_distance: float = 0.85
    clap_separate_distance: float = 1.6
    neutral_palm_scale_px: float = 80.0

    def to_dict(self) -> dict[str, float]:
        return {
            "pinch_on": float(self.pinch_on),
            "pinch_off": float(self.pinch_off),
            "clap_arm_distance": float(self.clap_arm_distance),
            "clap_contact_distance": float(self.clap_contact_distance),
            "clap_separate_distance": float(self.clap_separate_distance),
            "neutral_palm_scale_px": float(self.neutral_palm_scale_px),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CalibrationThresholds:
        pinch_on = max(0.10, min(0.60, float(data.get("pinch_on", 0.28))))
        pinch_off = max(pinch_on + 0.05, min(0.85, float(data.get("pinch_off", 0.42))))
        return cls(
            pinch_on=pinch_on,
            pinch_off=pinch_off,
            clap_arm_distance=float(data.get("clap_arm_distance", 2.0)),
            clap_contact_distance=float(data.get("clap_contact_distance", 0.85)),
            clap_separate_distance=float(data.get("clap_separate_distance", 1.6)),
            neutral_palm_scale_px=max(10.0, float(data.get("neutral_palm_scale_px", 80.0))),
        )


@dataclass(frozen=True)
class CalibrationResult:
    """Returned by CalibrationWizard when calibration finishes.

    Persistence is handled by the caller/manager.
    """

    bounds: MovementBounds = field(default_factory=MovementBounds)
    thresholds: CalibrationThresholds = field(default_factory=CalibrationThresholds)
    dominant_hand: Handedness = Handedness.RIGHT
    neutral_samples: int = 0
    corner_samples: int = 0
    pinch_count: int = 0
    clap_count: int = 0
    os_commands_suppressed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "bounds": self.bounds.to_dict(),
            "thresholds": self.thresholds.to_dict(),
            "dominant_hand": self.dominant_hand.value,
            "neutral_samples": self.neutral_samples,
            "corner_samples": self.corner_samples,
            "pinch_count": self.pinch_count,
            "clap_count": self.clap_count,
            "os_commands_suppressed": self.os_commands_suppressed,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CalibrationResult:
        raw_hand = str(data.get("dominant_hand", Handedness.RIGHT.value))
        try:
            dom = Handedness(raw_hand)
        except ValueError:
            dom = Handedness.RIGHT
        return cls(
            bounds=MovementBounds.from_dict(data.get("bounds", {})),
            thresholds=CalibrationThresholds.from_dict(data.get("thresholds", {})),
            dominant_hand=dom,
            neutral_samples=int(data.get("neutral_samples", 0)),
            corner_samples=int(data.get("corner_samples", 0)),
            pinch_count=int(data.get("pinch_count", 0)),
            clap_count=int(data.get("clap_count", 0)),
            os_commands_suppressed=bool(data.get("os_commands_suppressed", True)),
        )


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

    def set_calibration_step(
        self,
        step: CalibrationStep,
        corner_points: Optional[list[tuple[float, float]]] = None,
    ) -> None:
        self._step = step
        if corner_points is not None:
            self._corner_points = list(corner_points)
        self.update()

    def _paint_contents(self, painter: QPainter, full_rect: QRectF) -> None:
        super()._paint_contents(painter, full_rect)
        canvas = self._canvas_rect()
        self._draw_guide_marks(painter, canvas)

    def _draw_guide_marks(self, painter: QPainter, canvas: QRectF) -> None:
        painter.save()
        guide_pen = QPen(QColor(88, 188, 255, 200), 2.0, Qt.PenStyle.DashLine)
        painter.setPen(guide_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if self._step == CalibrationStep.NEUTRAL_POSE:
            box_w = canvas.width() * 0.34
            box_h = canvas.height() * 0.44
            target_rect = QRectF(
                canvas.center().x() - box_w * 0.5,
                canvas.center().y() - box_h * 0.5,
                box_w,
                box_h,
            )
            painter.drawRoundedRect(target_rect, 12.0, 12.0)
            painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            painter.drawText(
                QRectF(target_rect.left(), target_rect.top() - 24.0, target_rect.width(), 20.0),
                int(Qt.AlignmentFlag.AlignCenter),
                "Nötr Duruş Alanı",
            )

        elif self._step == CalibrationStep.MOVEMENT_CORNERS:
            corners = [
                (0.18, 0.18, "Sol-Üst"),
                (0.82, 0.18, "Sağ-Üst"),
                (0.82, 0.82, "Sağ-Alt"),
                (0.18, 0.82, "Sol-Alt"),
            ]
            painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            for idx, (nx, ny, name) in enumerate(corners):
                pt = QPointF(
                    canvas.left() + nx * canvas.width(),
                    canvas.top() + ny * canvas.height(),
                )
                done = idx < len(self._corner_points)
                color = QColor(72, 224, 138) if done else QColor(255, 196, 77)
                painter.setPen(QPen(color, 2.2))
                painter.drawEllipse(pt, 14.0, 14.0)
                painter.drawText(QPointF(pt.x() - 22.0, pt.y() + 28.0), name)

        elif self._step == CalibrationStep.PINCH_REPEATS:
            c = canvas.center()
            painter.setPen(QPen(QColor(122, 214, 255), 2.2, Qt.PenStyle.DotLine))
            painter.drawEllipse(c, 42.0, 42.0)
            painter.drawEllipse(c, 16.0, 16.0)

        elif self._step == CalibrationStep.CLAP_REPEATS:
            cy = canvas.center().y()
            left_pt = QPointF(canvas.left() + canvas.width() * 0.30, cy)
            right_pt = QPointF(canvas.left() + canvas.width() * 0.70, cy)
            painter.setPen(QPen(QColor(135, 225, 165), 2.2, Qt.PenStyle.DashLine))
            painter.drawEllipse(left_pt, 28.0, 28.0)
            painter.drawEllipse(right_pt, 28.0, 28.0)
            painter.drawLine(left_pt, right_pt)

        painter.restore()


class CalibrationWizard(QDialog):
    """Step-by-step hand gesture calibration dialog.

    OS commands are never produced during calibration (`suppress_os_commands == True`).
    """

    calibration_finished = Signal(object)       # CalibrationResult
    calibration_cancelled = Signal()
    step_changed = Signal(object)               # CalibrationStep

    REQUIRED_NEUTRAL_SAMPLES: int = 5
    REQUIRED_CORNERS: int = 4
    REQUIRED_PINCHES: int = 3
    REQUIRED_CLAPS: int = 3

    def __init__(
        self,
        bridge: Optional[UiBridge] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._bridge = bridge
        self._step_index: int = 0
        self._suppress_os_commands: bool = True

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
        self._last_result: Optional[CalibrationResult] = None

        self.setWindowTitle("Holoscobe — El Hareketi Kalibrasyonu")
        self.resize(720, 580)

        self._build_ui()
        self._refresh_step_ui()

        if self._bridge is not None:
            self._bridge.frame_updated.connect(self._on_bridge_frame)

    @property
    def suppress_os_commands(self) -> bool:
        """Always True while calibration is active so OS commands are never emitted."""
        return self._suppress_os_commands

    @property
    def os_commands_enabled(self) -> bool:
        """Always False during calibration."""
        return not self._suppress_os_commands

    @property
    def current_step(self) -> CalibrationStep:
        return STEP_ORDER[self._step_index]

    @property
    def last_result(self) -> Optional[CalibrationResult]:
        return self._last_result

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        self.safety_banner = QLabel(
            "Kalibrasyon Modu: İşletim sistemi fare/klavye komutları devre dışıdır."
        )
        self.safety_banner.setStyleSheet(
            "background-color: #1f3347; color: #9ad1ff; padding: 6px 10px; "
            "border-radius: 5px; font-weight: bold;"
        )
        layout.addWidget(self.safety_banner)

        self.step_title_label = QLabel()
        title_font = QFont("Segoe UI", 12)
        title_font.setBold(True)
        self.step_title_label.setFont(title_font)
        layout.addWidget(self.step_title_label)

        self.instruction_label = QLabel()
        self.instruction_label.setWordWrap(True)
        layout.addWidget(self.instruction_label)

        self.preview = CalibrationPreviewCanvas(bridge=self._bridge, parent=self)
        layout.addWidget(self.preview, stretch=1)

        progress_row = QHBoxLayout()
        self.step_status_label = QLabel()
        self.step_progress_bar = QProgressBar()
        self.step_progress_bar.setRange(0, 100)
        progress_row.addWidget(self.step_status_label, stretch=1)
        progress_row.addWidget(self.step_progress_bar, stretch=1)
        layout.addLayout(progress_row)

        button_row = QHBoxLayout()
        self.btn_reset = QPushButton("Baştan Başla")
        self.btn_prev = QPushButton("Geri")
        self.btn_sample = QPushButton("Örnek Kaydet")
        self.btn_next = QPushButton("İleri")
        self.btn_finish = QPushButton("Kalibrasyonu Tamamla")
        self.btn_cancel = QPushButton("İptal")

        self.btn_reset.clicked.connect(self.reset_calibration)
        self.btn_prev.clicked.connect(self.previous_step)
        self.btn_sample.clicked.connect(self.record_manual_step_sample)
        self.btn_next.clicked.connect(self.next_step)
        self.btn_finish.clicked.connect(self.finish_calibration)
        self.btn_cancel.clicked.connect(self.cancel_calibration)

        button_row.addWidget(self.btn_reset)
        button_row.addStretch(1)
        button_row.addWidget(self.btn_prev)
        button_row.addWidget(self.btn_sample)
        button_row.addWidget(self.btn_next)
        button_row.addWidget(self.btn_finish)
        button_row.addWidget(self.btn_cancel)
        layout.addLayout(button_row)

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
                if len(self._corner_points) < self.REQUIRED_CORNERS:
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
            preset_corners = [(0.14, 0.16), (0.86, 0.16), (0.86, 0.84), (0.14, 0.84)]
            idx = len(self._corner_points) % len(preset_corners)
            cx, cy = preset_corners[idx]
            self.record_corner_point(cx, cy)
        elif step == CalibrationStep.PINCH_REPEATS:
            self.record_pinch_sample(0.23, 0.46)
        elif step == CalibrationStep.CLAP_REPEATS:
            self.record_clap_sample(0.78, 1.72)

    @Slot()
    def next_step(self) -> None:
        """Advance to the next calibration step."""
        if self._step_index < len(STEP_ORDER) - 1:
            self._step_index += 1
            self._refresh_step_ui()
            self.step_changed.emit(self.current_step)

    @Slot()
    def previous_step(self) -> None:
        """Return to the previous calibration step."""
        if self._step_index > 0:
            self._step_index -= 1
            self._refresh_step_ui()
            self.step_changed.emit(self.current_step)

    @Slot()
    def reset_calibration(self) -> None:
        """Clear collected samples and restart at Step 1."""
        self._step_index = 0
        self._neutral_scales.clear()
        self._corner_points.clear()
        self._pinch_min_distances.clear()
        self._pinch_open_distances.clear()
        self._clap_min_distances.clear()
        self._clap_max_distances.clear()
        self._pinch_currently_closed = False
        self._clap_currently_near = False
        self._last_result = None
        self._refresh_step_ui()
        self.step_changed.emit(self.current_step)

    def compute_result(self) -> CalibrationResult:
        """Compute MovementBounds and CalibrationThresholds from collected samples."""
        if len(self._corner_points) >= 2:
            xs = [pt[0] for pt in self._corner_points]
            ys = [pt[1] for pt in self._corner_points]
            left = max(0.0, min(xs))
            right = min(1.0, max(xs))
            top = max(0.0, min(ys))
            bottom = min(1.0, max(ys))
            if right - left < 0.15:
                left, right = 0.15, 0.85
            if bottom - top < 0.15:
                top, bottom = 0.15, 0.85
            bounds = MovementBounds(left=left, top=top, right=right, bottom=bottom)
        else:
            bounds = MovementBounds()

        if self._neutral_scales:
            palm_scale = sum(self._neutral_scales) / len(self._neutral_scales)
        else:
            palm_scale = 80.0

        if self._pinch_min_distances and self._pinch_open_distances:
            avg_closed = sum(self._pinch_min_distances) / len(self._pinch_min_distances)
            avg_open = sum(self._pinch_open_distances) / len(self._pinch_open_distances)
            pinch_on = round(max(0.15, min(0.40, avg_closed + (avg_open - avg_closed) * 0.25)), 3)
            pinch_off = round(max(pinch_on + 0.08, min(0.65, avg_closed + (avg_open - avg_closed) * 0.65)), 3)
        else:
            pinch_on = 0.28
            pinch_off = 0.42

        if self._clap_min_distances and self._clap_max_distances:
            avg_contact = sum(self._clap_min_distances) / len(self._clap_min_distances)
            avg_sep = sum(self._clap_max_distances) / len(self._clap_max_distances)
            clap_contact = round(max(0.45, min(1.15, avg_contact * 1.08)), 3)
            clap_sep = round(max(clap_contact + 0.40, min(2.20, avg_sep * 0.95)), 3)
        else:
            clap_contact = 0.85
            clap_sep = 1.60

        thresholds = CalibrationThresholds(
            pinch_on=pinch_on,
            pinch_off=pinch_off,
            clap_arm_distance=max(1.8, round(clap_sep + 0.35, 2)),
            clap_contact_distance=clap_contact,
            clap_separate_distance=clap_sep,
            neutral_palm_scale_px=round(palm_scale, 2),
        )

        return CalibrationResult(
            bounds=bounds,
            thresholds=thresholds,
            dominant_hand=self._dominant_hand,
            neutral_samples=len(self._neutral_scales),
            corner_samples=len(self._corner_points),
            pinch_count=len(self._pinch_min_distances),
            clap_count=len(self._clap_min_distances),
            os_commands_suppressed=True,
        )

    @Slot()
    def finish_calibration(self) -> CalibrationResult:
        """Finalize calibration, emit CalibrationResult, and close dialog."""
        result = self.compute_result()
        self._last_result = result
        self.calibration_finished.emit(result)
        if self._bridge is not None:
            self._bridge.calibration_completed.emit(result)
            self._bridge.update_status(control_state=ControlState.PAUSED)
        self.accept()
        return result

    @Slot()
    def cancel_calibration(self) -> None:
        """Cancel calibration without emitting a result."""
        self.calibration_cancelled.emit()
        if self._bridge is not None:
            self._bridge.calibration_cancelled.emit()
            self._bridge.update_status(control_state=ControlState.PAUSED)
        self.reject()

    def _refresh_step_ui(self) -> None:
        step = self.current_step
        self.step_title_label.setText(STEP_TITLES_TR[step])
        self.instruction_label.setText(STEP_INSTRUCTIONS_TR[step])
        self.preview.set_calibration_step(step, self._corner_points)

        if step == CalibrationStep.NEUTRAL_POSE:
            done = len(self._neutral_scales)
            req = self.REQUIRED_NEUTRAL_SAMPLES
            pct = min(100, int((done / req) * 100))
            status = f"Nötr duruş örnekleri: {done} / {req}"
        elif step == CalibrationStep.MOVEMENT_CORNERS:
            done = len(self._corner_points)
            req = self.REQUIRED_CORNERS
            pct = min(100, int((done / req) * 100))
            status = f"Kaydedilen köşe noktaları: {done} / {req}"
        elif step == CalibrationStep.PINCH_REPEATS:
            done = len(self._pinch_min_distances)
            req = self.REQUIRED_PINCHES
            pct = min(100, int((done / req) * 100))
            status = f"Kıstırma (Pinch) tekrarları: {done} / {req}"
        elif step == CalibrationStep.CLAP_REPEATS:
            done = len(self._clap_min_distances)
            req = self.REQUIRED_CLAPS
            pct = min(100, int((done / req) * 100))
            status = f"El çırpma tekrarları: {done} / {req}"
        else:
            res = self.compute_result()
            pct = 100
            status = (
                f"Sınırlar: [{res.bounds.left:.2f}, {res.bounds.top:.2f}] - "
                f"[{res.bounds.right:.2f}, {res.bounds.bottom:.2f}] | "
                f"Pinch Aç/Kapa: {res.thresholds.pinch_on:.2f} / {res.thresholds.pinch_off:.2f}"
            )

        self.step_status_label.setText(status)
        self.step_progress_bar.setValue(pct)

        self.btn_prev.setEnabled(self._step_index > 0)
        self.btn_next.setEnabled(self._step_index < len(STEP_ORDER) - 1)
        self.btn_sample.setVisible(step != CalibrationStep.SUMMARY)


# Alias for convenience
CalibrationDialog = CalibrationWizard
