"""Camera and hand-landmark preview widget for Holoscobe.

Draws up to two hands (42 landmarks), handedness labels, per-finger name, state
(extended/bent/unknown) and curl bars, quality state, FPS, and sample age.
Mirroring only flips visual coordinates/image; handedness labels remain as inferred.
Uncertain estimates (Quality != USABLE, FingerState.UNKNOWN, or identity_ambiguous)
are rendered with dashed lines and distinct muted/amber colors, never as solid/certain.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, Slot
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from handcontrol.contracts import (
    FingerInfo,
    FingerName,
    FingerState,
    FrameFeatures,
    Handedness,
    HandFeatures,
    Landmark,
    Quality,
)
from handcontrol.ui.viewmodel import (
    FINGER_NAME_LABELS_TR,
    FINGER_STATE_LABELS_TR,
    HANDEDNESS_LABELS_TR,
    QUALITY_LABELS_TR,
    UiBridge,
    UiState,
)

# Explicit landmark chains per specification §4 item 7:
# wrist 0, thumb 1-4, index 5-8, middle 9-12, ring 13-16, little 17-20
WRIST_LANDMARK: int = 0

FINGER_LANDMARK_CHAINS: dict[FingerName, tuple[tuple[int, int], ...]] = {
    FingerName.THUMB: ((0, 1), (1, 2), (2, 3), (3, 4)),
    FingerName.INDEX: ((5, 6), (6, 7), (7, 8)),
    FingerName.MIDDLE: ((9, 10), (10, 11), (11, 12)),
    FingerName.RING: ((13, 14), (14, 15), (15, 16)),
    FingerName.LITTLE: ((17, 18), (18, 19), (19, 20)),
}

FINGER_LANDMARK_INDICES: dict[FingerName, tuple[int, ...]] = {
    FingerName.THUMB: (1, 2, 3, 4),
    FingerName.INDEX: (5, 6, 7, 8),
    FingerName.MIDDLE: (9, 10, 11, 12),
    FingerName.RING: (13, 14, 15, 16),
    FingerName.LITTLE: (17, 18, 19, 20),
}

PALM_CONNECTIONS: tuple[tuple[int, int], ...] = (
    (0, 5),
    (5, 9),
    (9, 13),
    (13, 17),
    (17, 0),
)

FINGER_ORDER: tuple[FingerName, ...] = (
    FingerName.THUMB,
    FingerName.INDEX,
    FingerName.MIDDLE,
    FingerName.RING,
    FingerName.LITTLE,
)


class CameraPreviewWidget(QWidget):
    """Widget that visualizes FrameFeatures without opening any hardware camera."""

    def __init__(
        self,
        bridge: Optional[UiBridge] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._bridge = bridge
        self._frame: Optional[FrameFeatures] = None
        self._camera_image: Optional[QImage] = None
        self._mirrored: bool = True
        self._fps: float = 0.0
        self._sample_age_ms: float = 0.0

        # Diagnostic counters updated on paint for verification
        self._last_rendered_hand_count: int = 0
        self._last_rendered_landmark_count: int = 0
        self._last_had_uncertain_elements: bool = False

        self.setMinimumSize(560, 380)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        if self._bridge is not None:
            self._bridge.state_changed.connect(self._on_state_changed)
            self._bridge.frame_updated.connect(self._on_frame_updated)
            self._on_state_changed(self._bridge.state)

    @property
    def frame(self) -> Optional[FrameFeatures]:
        return self._frame

    @property
    def mirrored(self) -> bool:
        return self._mirrored

    @property
    def fps(self) -> float:
        return self._fps

    @property
    def sample_age_ms(self) -> float:
        return self._sample_age_ms

    @property
    def last_rendered_hand_count(self) -> int:
        return self._last_rendered_hand_count

    @property
    def last_rendered_landmark_count(self) -> int:
        return self._last_rendered_landmark_count

    @property
    def last_had_uncertain_elements(self) -> bool:
        return self._last_had_uncertain_elements

    @Slot(bool)
    def set_mirrored(self, mirrored: bool) -> None:
        """Enable or disable horizontal display mirroring."""
        self._mirrored = bool(mirrored)
        self.update()

    @Slot(object)
    def set_camera_image(self, image: Optional[QImage]) -> None:
        """Set optional background camera QImage."""
        self._camera_image = image
        self.update()

    def set_frame(
        self,
        frame: Optional[FrameFeatures],
        fps: Optional[float] = None,
        sample_age_ms: Optional[float] = None,
    ) -> None:
        """Update the preview with a new FrameFeatures sample."""
        self._frame = frame
        if fps is not None:
            self._fps = float(fps)
        if sample_age_ms is not None:
            self._sample_age_ms = float(sample_age_ms)
        elif frame is not None and frame.inference_done_ms >= frame.capture_ms:
            self._sample_age_ms = float(frame.inference_done_ms - frame.capture_ms)
        self.update()

    @Slot(object)
    def _on_state_changed(self, state: UiState) -> None:
        self._mirrored = state.mirrored
        self._fps = state.fps
        self._sample_age_ms = state.sample_age_ms
        if state.latest_frame is not None:
            self._frame = state.latest_frame
        self.update()

    @Slot(object)
    def _on_frame_updated(self, frame: Optional[FrameFeatures]) -> None:
        self._frame = frame
        self.update()

    def map_normalized_point(
        self,
        norm_x: float,
        norm_y: float,
        canvas_rect: Optional[QRectF] = None,
    ) -> QPointF:
        """Map normalized [0, 1] landmark coordinates to widget canvas coordinates.

        Mirroring only flips the horizontal coordinate visually.
        """
        rect = canvas_rect if canvas_rect is not None else self._canvas_rect()
        display_x = (1.0 - norm_x) if self._mirrored else norm_x
        px = rect.left() + display_x * rect.width()
        py = rect.top() + norm_y * rect.height()
        return QPointF(px, py)

    def _canvas_rect(self) -> QRectF:
        top_bar_h = 38.0
        w = max(100.0, float(self.width()))
        h = max(100.0, float(self.height()))
        return QRectF(8.0, top_bar_h + 6.0, w - 16.0, h - top_bar_h - 14.0)

    def render_to_image(self, width: int = 640, height: int = 480) -> QImage:
        """Render the preview directly into an offscreen QImage (useful for tests)."""
        self.resize(width, height)
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor(18, 22, 28))
        painter = QPainter(image)
        self._paint_contents(painter, QRectF(0.0, 0.0, float(width), float(height)))
        painter.end()
        return image

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        self._paint_contents(
            painter,
            QRectF(0.0, 0.0, float(self.width()), float(self.height())),
        )
        painter.end()

    def _paint_contents(self, painter: QPainter, full_rect: QRectF) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(full_rect, QColor(18, 22, 28))

        self._last_rendered_hand_count = 0
        self._last_rendered_landmark_count = 0
        self._last_had_uncertain_elements = False

        top_bar = QRectF(full_rect.left() + 8.0, full_rect.top() + 6.0, full_rect.width() - 16.0, 32.0)
        canvas = QRectF(
            full_rect.left() + 8.0,
            top_bar.bottom() + 6.0,
            full_rect.width() - 16.0,
            max(60.0, full_rect.height() - top_bar.height() - 18.0),
        )

        self._draw_top_hud(painter, top_bar)
        self._draw_canvas_background(painter, canvas)

        if self._frame is None or len(self._frame.hands) == 0:
            self._draw_empty_notice(painter, canvas)
            return

        if self._frame.identity_ambiguous:
            self._last_had_uncertain_elements = True

        hands = self._frame.hands[:2]
        for idx, hand in enumerate(hands):
            self._last_rendered_hand_count += 1
            self._draw_hand_skeleton(painter, canvas, hand, self._frame.identity_ambiguous)
            self._draw_hand_info_card(painter, canvas, hand, idx, self._frame.identity_ambiguous)

    def _draw_top_hud(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(28, 34, 44, 230))
        painter.drawRoundedRect(rect, 6.0, 6.0)

        font = QFont("Segoe UI", 9)
        font.setBold(True)
        painter.setFont(font)

        mirror_text = "Ayna: Açık" if self._mirrored else "Ayna: Kapalı"
        fps_text = f"FPS: {self._fps:.1f}"
        age_text = f"Örnek Yaşı: {self._sample_age_ms:.1f} ms"

        if self._frame is None:
            quality_summary = "Kalite: Veri Yok"
        elif not self._frame.hands:
            quality_summary = "Kalite: El Algılanmadı"
        else:
            qualities = [QUALITY_LABELS_TR.get(h.quality, "Belirsiz") for h in self._frame.hands[:2]]
            quality_summary = "Kalite: " + " / ".join(qualities)

        hud_line = f"{fps_text}   |   {age_text}   |   {quality_summary}   |   {mirror_text}"
        painter.setPen(QColor(225, 232, 240))
        painter.drawText(
            rect.adjusted(12.0, 0.0, -12.0, 0.0),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            hud_line,
        )

        if self._frame is not None and self._frame.identity_ambiguous:
            warn_font = QFont("Segoe UI", 9)
            warn_font.setBold(True)
            painter.setFont(warn_font)
            painter.setPen(QColor(255, 184, 77))
            painter.drawText(
                rect.adjusted(12.0, 0.0, -12.0, 0.0),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight),
                "Uyarı: El Kimliği Belirsiz",
            )

    def _draw_canvas_background(self, painter: QPainter, canvas: QRectF) -> None:
        painter.setPen(QPen(QColor(48, 56, 70), 1.2))
        painter.setBrush(QColor(13, 17, 23))
        painter.drawRoundedRect(canvas, 8.0, 8.0)

        if self._camera_image is not None and not self._camera_image.isNull():
            img = (
                self._camera_image.mirrored(True, False)
                if self._mirrored
                else self._camera_image
            )
            painter.drawImage(canvas, img)

        # Subtle center guide lines
        grid_pen = QPen(QColor(38, 45, 58), 1.0, Qt.PenStyle.DotLine)
        painter.setPen(grid_pen)
        painter.drawLine(
            QPointF(canvas.center().x(), canvas.top()),
            QPointF(canvas.center().x(), canvas.bottom()),
        )
        painter.drawLine(
            QPointF(canvas.left(), canvas.center().y()),
            QPointF(canvas.right(), canvas.center().y()),
        )

    def _draw_empty_notice(self, painter: QPainter, canvas: QRectF) -> None:
        font = QFont("Segoe UI", 11)
        painter.setFont(font)
        painter.setPen(QColor(145, 155, 170))
        msg = "El algılanmadı — Kameraya ellerinizi gösterin"
        painter.drawText(canvas, int(Qt.AlignmentFlag.AlignCenter), msg)

    def _is_hand_uncertain(self, hand: HandFeatures, identity_ambiguous: bool) -> bool:
        return (
            identity_ambiguous
            or hand.quality != Quality.USABLE
            or hand.handedness == Handedness.UNKNOWN
        )

    def _draw_hand_skeleton(
        self,
        painter: QPainter,
        canvas: QRectF,
        hand: HandFeatures,
        identity_ambiguous: bool,
    ) -> None:
        landmarks: tuple[Landmark, ...] = hand.landmarks
        if not landmarks:
            return

        points: list[QPointF] = [
            self.map_normalized_point(lm.x, lm.y, canvas) for lm in landmarks
        ]
        self._last_rendered_landmark_count += len(points)

        hand_uncertain = self._is_hand_uncertain(hand, identity_ambiguous)
        if hand_uncertain:
            self._last_had_uncertain_elements = True

        # Base color per handedness (muted/amber when uncertain)
        if hand_uncertain:
            base_color = QColor(240, 173, 78)
        elif hand.handedness == Handedness.LEFT:
            base_color = QColor(74, 187, 255)
        else:
            base_color = QColor(82, 224, 148)

        # Map FingerName -> FingerInfo
        finger_map: dict[FingerName, FingerInfo] = {f.name: f for f in hand.fingers}

        # Draw palm connections
        palm_pen = QPen(
            base_color,
            2.2,
            Qt.PenStyle.DashLine if hand_uncertain else Qt.PenStyle.SolidLine,
        )
        painter.setPen(palm_pen)
        for i_start, i_end in PALM_CONNECTIONS:
            if i_start < len(points) and i_end < len(points):
                painter.drawLine(points[i_start], points[i_end])

        # Draw each finger chain with explicit uncertainty differentiation
        for finger_name in FINGER_ORDER:
            f_info = finger_map.get(finger_name)
            finger_uncertain = (
                hand_uncertain
                or f_info is None
                or f_info.state == FingerState.UNKNOWN
            )
            if finger_uncertain:
                self._last_had_uncertain_elements = True
                chain_color = QColor(235, 168, 68)
                pen_style = Qt.PenStyle.DashLine
            elif f_info is not None and f_info.state == FingerState.BENT:
                chain_color = base_color.darker(125)
                pen_style = Qt.PenStyle.SolidLine
            else:
                chain_color = base_color
                pen_style = Qt.PenStyle.SolidLine

            painter.setPen(QPen(chain_color, 2.4, pen_style))
            for idx_a, idx_b in FINGER_LANDMARK_CHAINS[finger_name]:
                if idx_a < len(points) and idx_b < len(points):
                    painter.drawLine(points[idx_a], points[idx_b])

            # Draw finger landmarks (hollow dashed ring when uncertain, solid dot when certain)
            for lm_idx in FINGER_LANDMARK_INDICES[finger_name]:
                if lm_idx < len(points):
                    pt = points[lm_idx]
                    if finger_uncertain:
                        painter.setPen(QPen(chain_color, 1.6, Qt.PenStyle.DashLine))
                        painter.setBrush(Qt.BrushStyle.NoBrush)
                        painter.drawEllipse(pt, 4.5, 4.5)
                    else:
                        painter.setPen(QPen(QColor(20, 24, 30), 1.2))
                        painter.setBrush(chain_color)
                        painter.drawEllipse(pt, 4.0, 4.0)

        # Draw wrist landmark (index 0)
        if len(points) > WRIST_LANDMARK:
            wrist_pt = points[WRIST_LANDMARK]
            painter.setPen(
                QPen(
                    base_color,
                    1.8,
                    Qt.PenStyle.DashLine if hand_uncertain else Qt.PenStyle.SolidLine,
                )
            )
            painter.setBrush(Qt.BrushStyle.NoBrush if hand_uncertain else base_color)
            painter.drawEllipse(wrist_pt, 5.5, 5.5)

            # Label above wrist/palm
            hand_label = HANDEDNESS_LABELS_TR.get(hand.handedness, "Belirsiz El")
            qual_label = QUALITY_LABELS_TR.get(hand.quality, "Belirsiz")
            tag_text = f"{hand_label} (#{hand.hand_id}) [{qual_label}]"
            font = QFont("Segoe UI", 9)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(base_color)
            painter.drawText(QPointF(wrist_pt.x() - 45.0, wrist_pt.y() + 18.0), tag_text)

    def _draw_hand_info_card(
        self,
        painter: QPainter,
        canvas: QRectF,
        hand: HandFeatures,
        slot_index: int,
        identity_ambiguous: bool,
    ) -> None:
        card_w = min(230.0, canvas.width() * 0.44)
        card_h = 152.0
        margin = 10.0
        card_x = (
            canvas.left() + margin
            if slot_index == 0
            else canvas.right() - card_w - margin
        )
        card_y = canvas.top() + margin
        card_rect = QRectF(card_x, card_y, card_w, card_h)

        hand_uncertain = self._is_hand_uncertain(hand, identity_ambiguous)
        border_pen = QPen(
            QColor(235, 168, 68) if hand_uncertain else QColor(72, 92, 118),
            1.4,
            Qt.PenStyle.DashLine if hand_uncertain else Qt.PenStyle.SolidLine,
        )
        painter.setPen(border_pen)
        painter.setBrush(QColor(22, 28, 38, 215))
        painter.drawRoundedRect(card_rect, 6.0, 6.0)

        header_font = QFont("Segoe UI", 9)
        header_font.setBold(True)
        painter.setFont(header_font)

        hand_label = HANDEDNESS_LABELS_TR.get(hand.handedness, "Belirsiz El")
        qual_label = QUALITY_LABELS_TR.get(hand.quality, "Belirsiz")
        header_text = f"{hand_label} — {qual_label}"
        painter.setPen(QColor(240, 185, 90) if hand_uncertain else QColor(230, 238, 248))
        painter.drawText(
            QRectF(card_x + 8.0, card_y + 5.0, card_w - 16.0, 18.0),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            header_text,
        )

        # Finger rows: name + state (Açık / Bükülü / Belirsiz) + curl bar
        row_font = QFont("Segoe UI", 8)
        painter.setFont(row_font)
        finger_map: dict[FingerName, FingerInfo] = {f.name: f for f in hand.fingers}

        y_cursor = card_y + 28.0
        row_h = 22.0
        for finger_name in FINGER_ORDER:
            f_info = finger_map.get(
                finger_name,
                FingerInfo(name=finger_name, state=FingerState.UNKNOWN, curl=0.0),
            )
            f_name_tr = FINGER_NAME_LABELS_TR[finger_name]
            f_state_tr = FINGER_STATE_LABELS_TR.get(f_info.state, "Belirsiz")
            curl_val = max(0.0, min(1.0, float(f_info.curl)))
            is_unknown = f_info.state == FingerState.UNKNOWN or hand_uncertain

            if is_unknown:
                self._last_had_uncertain_elements = True
                text_color = QColor(240, 178, 84)
                bar_color = QColor(210, 145, 55, 160)
                bar_pen = QPen(QColor(240, 178, 84), 1.0, Qt.PenStyle.DashLine)
            elif f_info.state == FingerState.EXTENDED:
                text_color = QColor(215, 230, 242)
                bar_color = QColor(58, 196, 125)
                bar_pen = QPen(QColor(80, 110, 130), 1.0, Qt.PenStyle.SolidLine)
            else:
                text_color = QColor(200, 212, 226)
                bar_color = QColor(72, 148, 224)
                bar_pen = QPen(QColor(80, 110, 130), 1.0, Qt.PenStyle.SolidLine)

            painter.setPen(text_color)
            label_rect = QRectF(card_x + 8.0, y_cursor, card_w * 0.56, row_h)
            painter.drawText(
                label_rect,
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                f"{f_name_tr}: {f_state_tr}",
            )

            # Curl bar
            bar_x = card_x + card_w * 0.58
            bar_w = card_w * 0.36
            bar_h = 9.0
            bar_y = y_cursor + (row_h - bar_h) * 0.5
            bar_bg_rect = QRectF(bar_x, bar_y, bar_w, bar_h)

            painter.setPen(bar_pen)
            painter.setBrush(QColor(35, 43, 56))
            painter.drawRoundedRect(bar_bg_rect, 3.0, 3.0)

            fill_w = bar_w * curl_val
            if fill_w > 1.0:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(bar_color)
                painter.drawRoundedRect(
                    QRectF(bar_x, bar_y, fill_w, bar_h),
                    3.0,
                    3.0,
                )

            y_cursor += row_h


# Alias for convenience
PreviewWidget = CameraPreviewWidget
