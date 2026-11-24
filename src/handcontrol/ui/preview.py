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
    QImage,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from handcontrol.contracts import (
    CameraState,
    ControlState,
    FingerInfo,
    FingerName,
    FingerState,
    FrameFeatures,
    Handedness,
    HandFeatures,
    Landmark,
    Quality,
)
from handcontrol.ui import icons, theme
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


STAGE_RADIUS = 14.0
NO_HAND_TR = "El algılanmadı — Kameraya ellerinizi gösterin"
PAUSED_CARD_TR = ("Duraklatıldı", "Başlamak için Sürdür'e bas ya da el çırp")
CAMERA_CARDS_TR: dict[CameraState, tuple[str, str]] = {
    CameraState.OFF: ("Kamera kapalı", "Tepsi menüsünden Kamerayı Başlat'ı seç"),
    CameraState.STARTING: ("Kamera başlatılıyor", "Görüntü birazdan burada olacak"),
    CameraState.ERROR: ("Kamera kullanılamıyor", "Bağlantıyı ve başka bir uygulamanın kamerayı kullanmadığını denetle"),
}


def paint_stage_card(p: QPainter, canvas: QRectF, title: str, text: str, icon: str = "", tone: str = theme.ACCENT,
                     center: bool = False) -> None:
    """Message card on the camera stage (bottom middle, or the middle of an empty stage)."""
    flags = int(Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap)
    side = 74.0 if icon else 20.0
    room = canvas.width() - 32.0 - side - 22.0
    p.setFont(theme.font(theme.TEXT_PX["caption"]))
    need = p.fontMetrics().boundingRect(0, 0, int(max(120.0, min(room, 430.0))), 200, flags, text)
    w = min(canvas.width() - 32.0, max(300.0, need.width() + side + 24.0))
    h = 58.0 + need.height()
    top = canvas.center().y() - h / 2 if center else canvas.bottom() - h - 20.0
    box = QRectF(canvas.center().x() - w / 2, top, w, h)
    theme.paint_glass(p, box, theme.RADIUS_XL, alpha=0.92)
    left = box.left() + side
    if icon:
        tile = QRectF(box.left() + 16, box.center().y() - 21, 42, 42)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.color(tone, 0.16))
        p.drawRoundedRect(tile, 12, 12)
        icons.paint(p, icon, tile.adjusted(10, 10, -10, -10), tone)
    p.setFont(theme.font(theme.TEXT_PX["caption"]))
    p.setPen(QColor(theme.MUTED))
    p.drawText(QRectF(left, box.top() + 40, box.right() - left - 16, need.height() + 4), flags, text)
    p.setFont(theme.bold(theme.TEXT_PX["subtitle"], True))
    p.setPen(QColor(theme.TEXT))
    p.drawText(QRectF(left, box.top() + 13, box.right() - left - 14, 24), int(Qt.AlignmentFlag.AlignVCenter), title)


def paint_empty_stage(p: QPainter, canvas: QRectF) -> None:
    """Stage without a camera picture: quiet surface with viewfinder marks."""
    p.setPen(QPen(QColor(theme.HAIRLINE), 1.0))
    p.setBrush(QColor(theme.SURFACE))
    p.drawRoundedRect(canvas.adjusted(0.5, 0.5, -0.5, -0.5), STAGE_RADIUS, STAGE_RADIUS)
    pen = QPen(QColor(theme.STROKE), 2.0)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    box, arm = canvas.adjusted(28, 28, -28, -28), 26.0
    for corner, sx, sy in ((box.topLeft(), 1, 1), (box.topRight(), -1, 1), (box.bottomLeft(), 1, -1),
                           (box.bottomRight(), -1, -1)):
        p.drawPolyline([QPointF(corner.x(), corner.y() + sy * arm), corner, QPointF(corner.x() + sx * arm, corner.y())])


def paint_stage_pill(p: QPainter, at: QPointF, text: str, icon: str = "", tone: str = theme.ACCENT,
                     max_width: float = 10_000.0) -> QRectF:
    """Small glass label on the picture; returns its rectangle."""
    p.setFont(theme.bold(theme.TEXT_PX["caption"]))
    left = 38.0 if icon else 16.0
    w = min(max_width, p.fontMetrics().horizontalAdvance(text) + left + 16.0)
    box = QRectF(at.x(), at.y(), w, 34.0)
    theme.paint_glass(p, box, 17.0, alpha=0.86, blur=0)
    if icon:
        icons.paint(p, icon, QRectF(box.left() + 13, box.top() + 8.5, 17, 17), tone)
    p.setPen(QColor(theme.TEXT))
    p.drawText(box.adjusted(left, 0, -10, 0), int(Qt.AlignmentFlag.AlignVCenter),
               p.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, int(w - left - 12)))
    return box


def paint_stage_corners(p: QPainter, canvas: QRectF, backdrop: QColor, radius: float = STAGE_RADIUS) -> None:
    """Round the live picture by covering its corners (far cheaper than clipping every frame)."""
    frame = QPainterPath()
    frame.addRect(canvas.adjusted(-1, -1, 1, 1))
    hole = QPainterPath()
    hole.addRoundedRect(canvas, radius, radius)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(backdrop)
    p.drawPath(frame.subtracted(hole))
    p.setPen(QPen(theme.color(theme.WHITE, 0.09), 1.0))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(canvas.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)


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
        self._show_details: bool = True    # top FPS bar, per-finger cards, long hand tags
        self._state_cards: bool = False    # "Duraklatıldı" / "Kamera kapalı" cards (main window only)
        self._notice_top: bool = False     # where "El algılanmadı" goes (guide marks need the bottom)
        self._control_state = ControlState.PAUSED
        self._camera_state = CameraState.OFF

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

    @property
    def show_details(self) -> bool:
        return self._show_details

    @Slot(bool)
    def set_show_details(self, enabled: bool) -> None:
        """Show the technical read-outs (FPS bar, finger cards). Off: a clean picture with the skeleton."""
        self._show_details = bool(enabled)
        self.update()

    def set_state_cards(self, enabled: bool) -> None:
        """Explain on the picture why nothing happens (paused, camera off or broken)."""
        self._state_cards = bool(enabled)
        self.update()

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
        self._control_state, self._camera_state = state.control_state, state.camera_state
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

    def _frame_aspect(self) -> float:
        f = self._frame
        return f.width / f.height if f is not None and f.width > 0 and f.height > 0 else 4.0 / 3.0

    def canvas_rect_for(self, full_rect: QRectF) -> QRectF:
        """Largest rect with the camera's aspect below the top bar: the picture is never stretched."""
        top = 44.0 if self._show_details else 1.0
        area = QRectF(full_rect.left() + 1.0, full_rect.top() + top, max(60.0, full_rect.width() - 2.0),
                      max(60.0, full_rect.height() - top - 1.0))
        aspect = self._frame_aspect()
        w = min(area.width(), area.height() * aspect)
        h = w / aspect
        return QRectF(area.center().x() - w / 2.0, area.center().y() - h / 2.0, w, h)

    def _canvas_rect(self) -> QRectF:
        return self.canvas_rect_for(QRectF(0.0, 0.0, max(100.0, float(self.width())),
                                           max(100.0, float(self.height()))))

    def render_to_image(self, width: int = 640, height: int = 480) -> QImage:
        """Render the preview directly into an offscreen QImage (useful for tests)."""
        self.resize(width, height)
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor(theme.BG))
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
        painter.fillRect(full_rect, QColor(theme.BG))

        self._last_rendered_hand_count = 0
        self._last_rendered_landmark_count = 0
        self._last_had_uncertain_elements = False

        top_bar = QRectF(full_rect.left() + 1.0, full_rect.top() + 1.0, full_rect.width() - 2.0, 34.0)
        canvas = self.canvas_rect_for(full_rect)

        if self._show_details:
            self._draw_top_hud(painter, top_bar)
        self._draw_canvas_background(painter, canvas)

        card = self._state_card()
        if self._frame is None or len(self._frame.hands) == 0 or (card is not None and card[-1]):
            if card is None:
                self._draw_empty_notice(painter, canvas)
        else:
            if self._frame.identity_ambiguous:
                self._last_had_uncertain_elements = True
            for idx, hand in enumerate(self._frame.hands[:2]):
                self._last_rendered_hand_count += 1
                self._draw_hand_skeleton(painter, canvas, hand, self._frame.identity_ambiguous)
                if self._show_details:
                    self._draw_hand_info_card(painter, canvas, hand, idx, self._frame.identity_ambiguous)
        if card is not None:
            paint_stage_card(painter, canvas, *card)

    def _state_card(self) -> Optional[tuple[str, str, str, str, bool]]:
        """(title, text, icon, tone, centered) of the card to show, None while everything works."""
        if not self._state_cards:
            return None
        if self._camera_state is not CameraState.RUNNING:
            starting = self._camera_state is CameraState.STARTING
            return (*CAMERA_CARDS_TR[self._camera_state], "camera" if starting else "camera_off",
                    theme.ACCENT if starting else theme.DANGER, True)
        if self._control_state is not ControlState.ACTIVE:
            return (*PAUSED_CARD_TR, "pause", theme.WARNING, False)
        return None

    def _draw_top_hud(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QPen(QColor(theme.HAIRLINE), 1.0))
        painter.setBrush(QColor(theme.SURFACE))
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), theme.RADIUS_M, theme.RADIUS_M)
        painter.setFont(theme.font(theme.TEXT_PX["caption"]))

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

        hud_line = f"{fps_text}     {age_text}     {quality_summary}     {mirror_text}"
        painter.setPen(QColor(theme.TEXT_SOFT))
        painter.drawText(
            rect.adjusted(12.0, 0.0, -12.0, 0.0),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            hud_line,
        )

        if self._frame is not None and self._frame.identity_ambiguous:
            painter.setFont(theme.bold(theme.TEXT_PX["caption"]))
            painter.setPen(QColor(theme.WARNING))
            painter.drawText(
                rect.adjusted(12.0, 0.0, -12.0, 0.0),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight),
                "Uyarı: El Kimliği Belirsiz",
            )

    def _draw_canvas_background(self, painter: QPainter, canvas: QRectF) -> None:
        if self._camera_image is not None and not self._camera_image.isNull():
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            if self._mirrored:
                # Flip with the painter transform: no full-image copy per paint.
                painter.save()
                painter.translate(canvas.left() + canvas.right(), 0.0)
                painter.scale(-1.0, 1.0)
                painter.drawImage(canvas, self._camera_image)
                painter.restore()
            else:
                painter.drawImage(canvas, self._camera_image)
            paint_stage_corners(painter, canvas, QColor(theme.BG))
            return

        paint_empty_stage(painter, canvas)

    def _draw_empty_notice(self, painter: QPainter, canvas: QRectF) -> None:
        painter.setFont(theme.font(theme.TEXT_PX["body"]))
        w = painter.fontMetrics().horizontalAdvance(NO_HAND_TR) + 58.0
        y = canvas.top() + 14.0 if self._notice_top else canvas.bottom() - 54.0
        box = QRectF(canvas.center().x() - w / 2, y, w, 38.0)
        theme.paint_glass(painter, box, 19.0, alpha=0.88)
        icons.paint(painter, "hand", QRectF(box.left() + 14, box.top() + 10, 18, 18), theme.ACCENT)
        painter.setPen(QColor(theme.TEXT_SOFT))
        painter.drawText(box.adjusted(42, 0, 0, 0), int(Qt.AlignmentFlag.AlignVCenter), NO_HAND_TR)

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
            base_color = QColor(theme.HAND_UNCERTAIN)
        elif hand.handedness == Handedness.LEFT:
            base_color = QColor(theme.HAND_LEFT)
        else:
            base_color = QColor(theme.HAND_RIGHT)

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
                chain_color = QColor(theme.HAND_UNCERTAIN)
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
                        painter.setPen(QPen(QColor(theme.INK), 1.2))
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
            tag_text = f"{hand_label} (#{hand.hand_id}) [{qual_label}]" if self._show_details else hand_label
            painter.setFont(theme.bold(theme.TEXT_PX["caption"]))
            w = painter.fontMetrics().horizontalAdvance(tag_text) + 20.0
            tag = QRectF(wrist_pt.x() - w / 2, wrist_pt.y() + 12.0, w, 24.0)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme.color(theme.BG, 0.78))
            painter.drawRoundedRect(tag, 12.0, 12.0)
            painter.setPen(base_color)
            painter.drawText(tag, int(Qt.AlignmentFlag.AlignCenter), tag_text)

    def _draw_hand_info_card(
        self,
        painter: QPainter,
        canvas: QRectF,
        hand: HandFeatures,
        slot_index: int,
        identity_ambiguous: bool,
    ) -> None:
        card_w = min(230.0, canvas.width() * 0.44)
        card_h = 156.0
        margin = 14.0
        card_x = (
            canvas.left() + margin
            if slot_index == 0
            else canvas.right() - card_w - margin
        )
        card_y = canvas.top() + margin
        card_rect = QRectF(card_x, card_y, card_w, card_h)

        hand_uncertain = self._is_hand_uncertain(hand, identity_ambiguous)
        border_pen = QPen(
            QColor(theme.HAND_UNCERTAIN) if hand_uncertain else theme.color(theme.WHITE, 0.13),
            1.2,
            Qt.PenStyle.DashLine if hand_uncertain else Qt.PenStyle.SolidLine,
        )
        painter.setPen(border_pen)
        painter.setBrush(theme.color(theme.SURFACE, 0.88))
        painter.drawRoundedRect(card_rect, theme.RADIUS_L, theme.RADIUS_L)
        painter.setFont(theme.bold(theme.TEXT_PX["caption"]))

        hand_label = HANDEDNESS_LABELS_TR.get(hand.handedness, "Belirsiz El")
        qual_label = QUALITY_LABELS_TR.get(hand.quality, "Belirsiz")
        header_text = f"{hand_label} — {qual_label}"
        painter.setPen(QColor(theme.HAND_UNCERTAIN if hand_uncertain else theme.TEXT))
        painter.drawText(
            QRectF(card_x + 14.0, card_y + 10.0, card_w - 28.0, 18.0),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            header_text,
        )

        # Finger rows: name + state (Açık / Bükülü / Belirsiz) + curl bar
        painter.setFont(theme.font(11))
        finger_map: dict[FingerName, FingerInfo] = {f.name: f for f in hand.fingers}

        y_cursor = card_y + 34.0
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
                text_color = QColor(theme.HAND_UNCERTAIN)
                bar_color = theme.color(theme.HAND_UNCERTAIN, 0.6)
                bar_pen = QPen(QColor(theme.HAND_UNCERTAIN), 1.0, Qt.PenStyle.DashLine)
            elif f_info.state == FingerState.EXTENDED:
                text_color = QColor(theme.TEXT)
                bar_color = QColor(theme.SUCCESS)
                bar_pen = QPen(Qt.PenStyle.NoPen)
            else:
                text_color = QColor(theme.TEXT_SOFT)
                bar_color = QColor(theme.ACCENT)
                bar_pen = QPen(Qt.PenStyle.NoPen)

            painter.setPen(text_color)
            label_rect = QRectF(card_x + 14.0, y_cursor, card_w * 0.56, row_h)
            painter.drawText(
                label_rect,
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                f"{f_name_tr}: {f_state_tr}",
            )

            # Curl bar
            bar_x = card_x + card_w * 0.62
            bar_w = card_w * 0.38 - 14.0
            bar_h = 6.0
            bar_y = y_cursor + (row_h - bar_h) * 0.5
            bar_bg_rect = QRectF(bar_x, bar_y, bar_w, bar_h)

            painter.setPen(bar_pen)
            painter.setBrush(theme.color(theme.WHITE, 0.12))
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
