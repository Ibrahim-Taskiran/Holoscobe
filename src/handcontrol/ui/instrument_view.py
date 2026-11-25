"""Enstrüman window: camera, hand skeleton, glowing guitar strings and spark particles.

GUI thread only. The instrument engine produces `InstrumentView` render states (camera px on the
UNMIRRORED frame); this module maps them through the camera preview's normalized mapping so the
strings line up with the skeleton for both mirror settings.

`SparkSystem` is Qt-free and deterministic for a given seed, so it can be tested without a display.
"""
from __future__ import annotations

import math
import random
import time
from typing import Callable, Optional

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QVBoxLayout, QWidget

from handcontrol.contracts import FrameFeatures
from handcontrol.instrument.engine import STATUS_PAUSED
from handcontrol.instrument.events import HitView, InstrumentView, StringView
from handcontrol.instrument.freeform import MAX_STRINGS, Seg, drop_short, fit_seg, hit_test, move_seg, put_seg
from handcontrol.instrument.geometry import Rect, normalize_fixed_rect
from handcontrol.ui import theme
from handcontrol.ui.preview import CameraPreviewWidget, paint_stage_card
from handcontrol.ui.viewmodel import UiBridge

INSTRUMENT_WINDOW_TITLE_TR = "Holoscobe — Enstrüman"
LAYOUT_LABELS_TR: dict[str, str] = {"solo": "Solo", "chord": "Akor", "fixed": "Sabit teller",
                                    "free": "Serbest teller"}
WAITING_STATUS_TR = "Enstrüman modunu seçin ve iki elinizi gösterin"
FIXED_HINT_TR = "Fareyle sürükle / köşeden boyutlandır · ya da iki elle çimdikle, tut, gerdir"
FREE_HINT_TR = "Çimdikle, tut, çek: tel çiz · uçtan tut: boyutlandır · ortadan: taşı · sağ tık: sil"
FREE_EMPTY_TR = ("İlk telini çiz", "Başparmak ve işaret parmağını birleştir · yarım saniye tut · çek · bırak")
PAUSED_HINT_TR = ("Duraklatıldı", "Başlamak için Sürdür'e bas ya da el çırp")
NO_CAMERA_HINT_TR = ("Kamera bekleniyor", "Görüntü gelince teller çalınabilir")
SNAPPED_TR = "hizalandı"
HANDLE_PX = 14.0                  # grab distance of a corner handle (widget px)
AREA_COLOR = QColor(theme.AREA)

FRAME_INTERVAL_MS = 33            # ~30 fps repaint while visible
MAX_WAVE_PX = 14.0                # peak string displacement at amplitude 1
WAVE_HZ = 7.0                     # visual (slowed) vibration frequency
WAVE_SEGMENTS = 24

# String colors (enabled): thumb side to index side, warm to cool.
STRING_COLORS: tuple[QColor, ...] = tuple(QColor(c) for c in theme.STRING_COLORS)
DISABLED_STRING_COLOR = QColor(theme.STRING_DISABLED)
SPARK_COLOR = QColor(theme.SPARK)
# Glow passes: (width scale, alpha scale), wide/faint first, thin/bright core last.
GLOW_PASSES: tuple[tuple[float, float], ...] = ((5.0, 0.10), (3.0, 0.22), (1.7, 0.50), (1.0, 1.0))


class Spark:
    """One particle. Positions in camera px (unmirrored), velocities in px/s."""

    __slots__ = ("x", "y", "vx", "vy", "born_ms", "life_ms", "size", "brightness")

    def __init__(self, x: float, y: float, vx: float, vy: float, born_ms: float, life_ms: float,
                 size: float, brightness: float) -> None:
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.born_ms = born_ms
        self.life_ms = life_ms
        self.size = size
        self.brightness = brightness

    def alpha(self, now_ms: float) -> float:
        """1 at birth, 0 at end of life."""
        return max(0.0, min(1.0, 1.0 - (now_ms - self.born_ms) / self.life_ms))


class SparkSystem:
    """Cheap, bounded, deterministic spark particles for string hits."""

    def __init__(
        self,
        seed: int = 0,
        max_particles: int = 200,
        min_count: int = 4,
        max_count: int = 28,
        life_ms: tuple[float, float] = (250.0, 500.0),
        gravity: float = 900.0,        # px/s^2, image y grows downward
        drag: float = 3.0,             # 1/s, velocity decay rate
    ) -> None:
        self._rng = random.Random(seed)
        self.max_particles = max(1, int(max_particles))
        self.min_count = max(0, int(min_count))
        self.max_count = max(self.min_count, int(max_count))
        self.life_ms = (float(life_ms[0]), float(max(life_ms[0], life_ms[1])))
        self.gravity = float(gravity)
        self.drag = float(drag)
        self._particles: list[Spark] = []
        self._last_ms: Optional[float] = None

    @property
    def particles(self) -> tuple[Spark, ...]:
        return tuple(self._particles)

    def __len__(self) -> int:
        return len(self._particles)

    def count_for(self, velocity: float) -> int:
        """Particles per hit: grows linearly with strike velocity (0..1)."""
        v = max(0.0, min(1.0, float(velocity)))
        return int(round(self.min_count + (self.max_count - self.min_count) * v))

    def emit(self, hit: HitView, now_ms: float) -> int:
        """Spawn sparks at the hit point; returns how many were spawned. Oldest drop past the cap."""
        n = self.count_for(hit.velocity)
        if n <= 0:
            return 0
        v = max(0.0, min(1.0, float(hit.velocity)))
        rng = self._rng
        direction = 1.0 if hit.direction >= 0 else -1.0
        base_speed = 180.0 + 520.0 * v
        lo, hi = self.life_ms
        for _ in range(n):
            # Mostly along the strike direction, fanned sideways.
            angle = rng.uniform(-1.25, 1.25)
            speed = base_speed * rng.uniform(0.35, 1.0)
            vx = math.sin(angle) * speed
            vy = math.cos(angle) * speed * direction
            self._particles.append(Spark(
                float(hit.x), float(hit.y), vx, vy, float(now_ms), rng.uniform(lo, hi),
                rng.uniform(1.4, 2.6) + 1.2 * v, 0.55 + 0.45 * v,
            ))
        overflow = len(self._particles) - self.max_particles
        if overflow > 0:
            del self._particles[:overflow]
        if self._last_ms is None:
            self._last_ms = float(now_ms)
        return n

    def step(self, now_ms: float) -> None:
        """Advance physics to now_ms and drop dead particles."""
        now = float(now_ms)
        last = self._last_ms if self._last_ms is not None else now
        self._last_ms = now
        dt = max(0.0, min(0.1, (now - last) / 1000.0))
        damp = max(0.0, 1.0 - self.drag * dt)
        g = self.gravity * dt
        alive: list[Spark] = []
        for p in self._particles:
            if now - p.born_ms >= p.life_ms:
                continue
            p.vx *= damp
            p.vy = p.vy * damp + g
            p.x += p.vx * dt
            p.y += p.vy * dt
            alive.append(p)
        self._particles = alive

    def clear(self) -> None:
        self._particles = []
        self._last_ms = None


def _string_color(s: StringView) -> QColor:
    if not s.enabled:
        return DISABLED_STRING_COLOR
    return STRING_COLORS[s.index % len(STRING_COLORS)]


class InstrumentCanvas(CameraPreviewWidget):
    """Camera preview (image + skeleton) with strings, sparks and HUD painted on top.

    "Sabit teller" layout: the string area can be moved (drag inside) and resized (drag a corner) with the
    mouse; `fixed_rect_edited` carries the new normalized rect (unmirrored frame) on release."""

    fixed_rect_edited = Signal(object)
    free_strings_edited = Signal(object)    # "Serbest teller": the whole new string list (normalized)

    def __init__(self, sparks: SparkSystem, clock: Callable[[], float],
                 bridge: Optional[UiBridge] = None, parent: Optional[QWidget] = None) -> None:
        super().__init__(bridge=bridge, parent=parent)
        self._sparks = sparks
        self._clock = clock
        self._view: Optional[InstrumentView] = None
        self._particles_enabled = True
        self._hud_font = theme.font(theme.TEXT_PX["body"])
        self._hud_big_font = theme.bold(24, True)
        self._label_font = theme.bold(11)
        self.setMinimumSize(480, 360)
        self._drag: Optional[tuple[str, tuple[float, float], Rect]] = None   # (kind, anchor/start, rect0)
        self._draft: Optional[Rect] = None
        # "Serbest teller" mouse edit: (kind, index, press point, strings at press)
        self._fdrag: Optional[tuple[str, Optional[int], tuple[float, float], tuple[Seg, ...]]] = None
        self._fdraft: Optional[tuple[Seg, ...]] = None
        self._fdraft_index: Optional[int] = None
        self._fdraft_snapped = False
        self._free_snap = True
        self._audio_error = ""
        self._show_details = False      # the instrument HUD replaces the technical read-outs
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    @property
    def view(self) -> Optional[InstrumentView]:
        return self._view

    def set_view(self, view: Optional[InstrumentView]) -> None:
        self._view = view

    def set_particles_enabled(self, enabled: bool) -> None:
        self._particles_enabled = bool(enabled)

    def set_free_snap(self, enabled: bool) -> None:
        self._free_snap = bool(enabled)

    def set_audio_error(self, text: str) -> None:
        self._audio_error = str(text)
        self.update()

    # ---------- geometry ----------

    def _frame_aspect(self) -> float:
        return self._aspect()

    def map_camera_point(self, x: float, y: float, canvas: QRectF) -> QPointF:
        """Camera px (unmirrored) -> widget point, honoring the mirror setting."""
        view = self._view
        w = float(view.width) if view is not None and view.width > 0 else 1.0
        h = float(view.height) if view is not None and view.height > 0 else 1.0
        return self.map_normalized_point(x / w, y / h, canvas)

    def to_normalized(self, pt: QPointF, canvas: QRectF) -> tuple[float, float]:
        """Widget point -> normalized unmirrored frame coordinates (inverse of map_normalized_point)."""
        nx = (pt.x() - canvas.left()) / max(1.0, canvas.width())
        ny = (pt.y() - canvas.top()) / max(1.0, canvas.height())
        if self.mirrored:
            nx = 1.0 - nx
        return (min(1.0, max(0.0, nx)), min(1.0, max(0.0, ny)))

    def fixed_rect(self) -> Optional[Rect]:
        """Area shown now: the draft while dragging, else the engine's."""
        if self._draft is not None:
            return self._draft
        view = self._view
        return view.fixed_rect if view is not None and view.layout == "fixed" else None

    def area_widget_rect(self, rect: Rect, canvas: QRectF) -> QRectF:
        a = self.map_normalized_point(rect[0], rect[1], canvas)
        b = self.map_normalized_point(rect[2], rect[3], canvas)
        return QRectF(a, b).normalized()

    def _canvas(self) -> QRectF:
        return self.canvas_rect_for(QRectF(self.rect()))

    # ---------- "Serbest teller" mouse editing ----------

    def free_strings(self) -> Optional[tuple[Seg, ...]]:
        """Strings shown now: the mouse draft while dragging, else the engine's (None: other layout)."""
        if self._fdraft is not None:
            return self._fdraft
        view = self._view
        if view is None or view.layout != "free":
            return None
        return tuple(view.free_strings or ())

    def _aspect(self) -> float:
        view = getattr(self, "_view", None)
        return view.width / view.height if view is not None and view.width > 0 and view.height > 0 else 4.0 / 3.0

    def _free_hit(self, pos: QPointF, strings: tuple[Seg, ...], canvas: QRectF):
        r = HANDLE_PX / max(1.0, canvas.height())
        return hit_test(strings, self.to_normalized(pos, canvas), self._aspect(), end_radius=r * 1.2,
                        grab_radius=r)

    def _free_press(self, event) -> bool:
        strings = self.free_strings()
        if strings is None or self._fdrag is not None:
            return False
        canvas = self._canvas()
        pos = event.position()
        if not canvas.contains(pos):
            return False
        hit = self._free_hit(pos, strings, canvas)
        if event.button() == Qt.MouseButton.RightButton:
            if hit is not None:
                self.free_strings_edited.emit(strings[:hit[0]] + strings[hit[0] + 1:])
            return True
        if event.button() != Qt.MouseButton.LeftButton:
            return False
        start = self.to_normalized(pos, canvas)
        if hit is None:
            if len(strings) >= MAX_STRINGS:
                return True
            self._fdrag = ("draw", None, start, strings)
        else:
            self._fdrag = (hit[1], hit[0], start, strings)
        self.setCursor(Qt.CursorShape.ClosedHandCursor if hit is not None and hit[1] == "body"
                       else Qt.CursorShape.CrossCursor)
        return True

    def _free_move(self, event) -> None:
        assert self._fdrag is not None
        kind, idx, start, base = self._fdrag
        p = self.to_normalized(event.position(), self._canvas())
        if kind == "draw":
            seg: Seg = (*start, *p)  # type: ignore[assignment]
        else:
            assert idx is not None
            x0, y0, x1, y1 = base[idx]
            dx, dy = p[0] - start[0], p[1] - start[1]
            seg = (move_seg(base[idx], dx, dy) if kind == "body" else (x0 + dx, y0 + dy, x1, y1) if kind == "p0"
                   else (x0, y0, x1 + dx, y1 + dy))
        seg, self._fdraft_snapped = fit_seg(seg, base, idx, self._aspect(), self._free_snap)
        self._fdraft, self._fdraft_index = put_seg(base, idx, seg)
        self.update()

    def _free_release(self) -> None:
        assert self._fdrag is not None
        base = self._fdrag[3]
        draft, idx = self._fdraft, self._fdraft_index
        self._fdrag = self._fdraft = self._fdraft_index = None
        self._fdraft_snapped = False
        self.unsetCursor()
        if draft is not None:
            draft = drop_short(draft, idx, self._aspect())
            if draft != base:
                self.free_strings_edited.emit(draft)
        self.update()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        strings = self.free_strings()
        if strings and self._fdrag is None and event.key() == Qt.Key.Key_Delete:
            self.free_strings_edited.emit(())                  # Delete: remove every string
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._free_press(event):
            event.accept()
            return
        rect = self.fixed_rect()
        if rect is None or event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        canvas = self._canvas()
        pos = event.position()
        x0, y0, x1, y1 = rect
        for cx, cy in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
            p = self.map_normalized_point(cx, cy, canvas)
            if math.hypot(p.x() - pos.x(), p.y() - pos.y()) <= HANDLE_PX:
                self._drag = ("corner", (x0 + x1 - cx, y0 + y1 - cy), rect)
                self.setCursor(Qt.CursorShape.SizeAllCursor)
                event.accept()
                return
        if self.area_widget_rect(rect, canvas).adjusted(-HANDLE_PX, -HANDLE_PX, HANDLE_PX, HANDLE_PX).contains(pos):
            self._drag = ("move", self.to_normalized(pos, canvas), rect)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._fdrag is not None:
            self._free_move(event)
            event.accept()
            return
        if self._drag is None:
            super().mouseMoveEvent(event)
            return
        kind, ref, r0 = self._drag
        nx, ny = self.to_normalized(event.position(), self._canvas())
        if kind == "corner":
            self._draft = normalize_fixed_rect((ref[0], ref[1], nx, ny), r0)
        else:
            w, h = r0[2] - r0[0], r0[3] - r0[1]
            x0 = min(1.0 - w, max(0.0, r0[0] + nx - ref[0]))
            y0 = min(1.0 - h, max(0.0, r0[1] + ny - ref[1]))
            self._draft = normalize_fixed_rect((x0, y0, x0 + w, y0 + h), r0)
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._fdrag is not None:
            self._free_release()
            event.accept()
            return
        if self._drag is None:
            super().mouseReleaseEvent(event)
            return
        r0 = self._drag[2]
        draft, self._draft, self._drag = self._draft, None, None
        self.unsetCursor()
        if draft is not None and draft != r0:
            self.fixed_rect_edited.emit(draft)
        self.update()
        event.accept()

    def string_points(self, s: StringView, canvas: QRectF) -> tuple[QPointF, QPointF]:
        return self.map_camera_point(*s.p0, canvas), self.map_camera_point(*s.p1, canvas)

    # ---------- painting ----------

    def _draw_hand_info_card(self, *args: object, **kwargs: object) -> None:
        """Per-finger cards are hidden here: the corner HUD owns that space."""
        return

    def _paint(self, painter: QPainter, full_rect: QRectF) -> None:
        super()._paint(painter, full_rect)
        canvas = self.canvas_rect_for(full_rect)
        now = self._clock()
        painter.save()
        painter.setClipRect(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        view = self._view
        area = self.fixed_rect()
        if area is not None:
            self._draw_area(painter, canvas, area, view)
        if self._fdraft is not None:
            self._draw_free_draft(painter, canvas)
        elif view is not None and self._draft is None:
            if view.layout == "free":
                self._draw_free_marks(painter, canvas, view)
            for s in view.strings:
                self._draw_string(painter, canvas, s, now)
            if view.pick_tip is not None:
                self._draw_pick(painter, self.map_camera_point(*view.pick_tip, canvas), view.playing)
        if self._particles_enabled and len(self._sparks):
            self._draw_sparks(painter, canvas, now)
        painter.restore()
        hint = self.center_hint()
        if hint is not NO_CAMERA_HINT_TR:
            self._draw_hud(painter, canvas)
        if hint is not None and self._fdraft is None:
            self._draw_center_hint(painter, canvas, *hint)

    def _draw_empty_notice(self, painter: QPainter, canvas: QRectF) -> None:
        return                                  # the HUD status line already says it

    def center_hint(self) -> Optional[tuple[str, str]]:
        """Big (title, text) card for the states in which nothing can be played yet."""
        view = self._view
        if view is None or (view.t_ms <= 0.0 and view.status == STATUS_PAUSED):     # only the idle view so far
            return NO_CAMERA_HINT_TR
        if view.status == STATUS_PAUSED:
            return PAUSED_HINT_TR
        if view.layout == "free" and not view.strings and not view.free_pending:
            return FREE_EMPTY_TR
        return None

    def _draw_center_hint(self, painter: QPainter, canvas: QRectF, title: str, text: str) -> None:
        icon = {NO_CAMERA_HINT_TR[0]: "camera", PAUSED_HINT_TR[0]: "pause"}.get(title, "instrument")
        paint_stage_card(painter, canvas, title, text, icon,
                         theme.WARNING if icon == "pause" else theme.ACCENT, icon == "camera")

    def _draw_string(self, painter: QPainter, canvas: QRectF, s: StringView, now_ms: float) -> None:
        a, b = self.string_points(s, canvas)
        dx, dy = b.x() - a.x(), b.y() - a.y()
        length = math.hypot(dx, dy)
        if length < 1.0:
            return
        amp = max(0.0, min(1.0, float(s.amplitude))) if s.enabled else 0.0
        color = QColor(_string_color(s))
        alpha_base = 0.35 if not s.enabled else 0.70 + 0.30 * amp
        base_w = 2.0 + 1.6 * amp

        path = QPainterPath(a)
        if amp > 0.01:
            # Standing wave: fundamental + a little 2nd harmonic, perpendicular to the string.
            nx, ny = -dy / length, dx / length
            phase = 2.0 * math.pi * WAVE_HZ * (now_ms / 1000.0) + s.index * 1.3
            disp = MAX_WAVE_PX * amp
            c1, c2 = math.sin(phase), 0.35 * math.sin(2.0 * phase + 0.7)
            for i in range(1, WAVE_SEGMENTS + 1):
                t = i / WAVE_SEGMENTS
                d = disp * (math.sin(math.pi * t) * c1 + math.sin(2.0 * math.pi * t) * c2)
                path.lineTo(a.x() + dx * t + nx * d, a.y() + dy * t + ny * d)
        else:
            path.lineTo(b)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        pen = QPen()
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        for i, (w_scale, a_scale) in enumerate(GLOW_PASSES):
            c = QColor(color) if i < len(GLOW_PASSES) - 1 else QColor(color).lighter(150 if s.enabled else 100)
            c.setAlphaF(max(0.0, min(1.0, alpha_base * a_scale * (1.0 + amp if i < 3 else 1.0))))
            pen.setColor(c)
            pen.setWidthF(base_w * w_scale)
            painter.setPen(pen)
            painter.drawPath(path)

        # End caps and the note label at the index side.
        painter.setPen(Qt.PenStyle.NoPen)
        cap = QColor(color)
        cap.setAlphaF(alpha_base)
        painter.setBrush(cap)
        painter.drawEllipse(a, 3.5, 3.5)
        painter.drawEllipse(b, 3.5, 3.5)
        if s.label:
            painter.setFont(self._label_font)
            label_c = QColor(theme.TEXT if s.enabled else theme.MUTED)
            painter.setPen(label_c)
            # Put the label beyond the index-side end, away from the string.
            if b.x() >= a.x():
                painter.drawText(QPointF(b.x() + 8.0, b.y() + 4.0), s.label)
            else:
                box = QRectF(b.x() - 68.0, b.y() - 10.0, 60.0, 20.0)
                painter.drawText(box, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), s.label)

    def _draw_area(self, painter: QPainter, canvas: QRectF, area: Rect, view: Optional[InstrumentView]) -> None:
        """Dashed frame and corner handles of the "Sabit teller" area; preview lines while dragging."""
        box = self.area_widget_rect(area, canvas)
        active = self._draft is not None or (view is not None and view.adjusting)
        c = QColor(AREA_COLOR)
        c.setAlphaF(0.85 if active else 0.35)
        pen = QPen(c, 1.5 if active else 1.0, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        fill = QColor(AREA_COLOR)
        fill.setAlphaF(0.10 if active else 0.04)
        painter.setBrush(fill)
        painter.drawRoundedRect(box, 6.0, 6.0)
        if self._draft is not None and view is not None and view.strings:
            n = len(view.strings)
            painter.setPen(QPen(c, 2.0))
            for k in range(n):
                y = box.top() + box.height() * (k / (n - 1) if n > 1 else 0.5)
                painter.drawLine(QPointF(box.left(), y), QPointF(box.right(), y))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(c)
        for p in (box.topLeft(), box.topRight(), box.bottomLeft(), box.bottomRight()):
            painter.drawEllipse(p, 5.0, 5.0)

    def _draw_free_draft(self, painter: QPainter, canvas: QRectF) -> None:
        """Mouse edit preview: every string as a plain line, the edited one bright."""
        assert self._fdraft is not None
        for i, s in enumerate(self._fdraft):
            a = self.map_normalized_point(s[0], s[1], canvas)
            b = self.map_normalized_point(s[2], s[3], canvas)
            edited = i == self._fdraft_index
            c = QColor(AREA_COLOR if edited else DISABLED_STRING_COLOR)
            c.setAlphaF(0.95 if edited else 0.6)
            painter.setPen(QPen(c, 3.0 if edited else 2.0))
            painter.drawLine(a, b)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(c)
            painter.drawEllipse(a, 5.0, 5.0)
            painter.drawEllipse(b, 5.0, 5.0)
            if edited and self._fdraft_snapped:
                self._draw_snap_label(painter, a, b)

    def _draw_snap_label(self, painter: QPainter, a: QPointF, b: QPointF) -> None:
        painter.setFont(self._label_font)
        painter.setPen(AREA_COLOR)
        painter.drawText(QPointF((a.x() + b.x()) / 2.0 - 24.0, (a.y() + b.y()) / 2.0 - 12.0), SNAPPED_TR)

    def _draw_free_marks(self, painter: QPainter, canvas: QRectF, view: InstrumentView) -> None:
        """Hand editing: halo on the grabbed string, end handles, and a ring filling up while a pinch is held."""
        strings = view.free_strings or ()
        c = QColor(AREA_COLOR)
        if view.free_active is not None and view.free_active < len(strings):
            s = strings[view.free_active]
            a = self.map_normalized_point(s[0], s[1], canvas)
            b = self.map_normalized_point(s[2], s[3], canvas)
            c.setAlphaF(0.30)
            pen = QPen(c, 16.0)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(a, b)
            if view.free_snapped:
                self._draw_snap_label(painter, a, b)
        c.setAlphaF(0.55)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(c)
        for s in strings:
            for x, y in ((s[0], s[1]), (s[2], s[3])):
                painter.drawEllipse(self.map_normalized_point(x, y, canvas), 5.0, 5.0)
        for (x, y), progress in view.free_pending:
            pt = self.map_normalized_point(x, y, canvas)
            ring = QColor(AREA_COLOR)
            ring.setAlphaF(0.9)
            painter.setPen(QPen(ring, 3.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawArc(QRectF(pt.x() - 14.0, pt.y() - 14.0, 28.0, 28.0), 90 * 16,
                            -int(360 * 16 * max(0.0, min(1.0, progress))))

    def _draw_pick(self, painter: QPainter, pt: QPointF, playing: bool) -> None:
        c = QColor(theme.WHITE if playing else theme.MUTED)
        painter.setPen(Qt.PenStyle.NoPen)
        glow = QColor(c)
        glow.setAlphaF(0.25)
        painter.setBrush(glow)
        painter.drawEllipse(pt, 11.0, 11.0)
        painter.setBrush(c)
        painter.drawEllipse(pt, 4.5, 4.5)

    def _draw_sparks(self, painter: QPainter, canvas: QRectF, now_ms: float) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        c = QColor(SPARK_COLOR)
        for p in self._sparks.particles:
            alpha = p.alpha(now_ms) * p.brightness
            if alpha <= 0.0:
                continue
            pt = self.map_camera_point(p.x, p.y, canvas)
            c.setAlphaF(alpha * 0.35)
            painter.setBrush(c)
            painter.drawEllipse(pt, p.size * 2.2, p.size * 2.2)
            c.setAlphaF(alpha)
            painter.setBrush(c)
            painter.drawEllipse(pt, p.size, p.size)

    def hud_lines(self) -> tuple[str, str, str]:
        """(note or chord, "Düzen: …", status) shown in the corner HUD."""
        view = self._view
        if view is None:
            return ("—", "Düzen: —", WAITING_STATUS_TR)
        if view.layout == "chord":
            main = view.chord_label or "—"
            if view.note_label:
                main = f"{main}  ·  {view.note_label}" if view.chord_label else view.note_label
        else:
            main = view.note_label or "—"
        layout = LAYOUT_LABELS_TR.get(view.layout, view.layout)
        status = view.status
        if view.layout == "fixed" and not view.adjusting and status == "Hazır":
            status = f"{status} · {FIXED_HINT_TR}"
        elif view.layout == "free" and not view.adjusting and status == "Hazır":
            status = f"{status} · {FREE_HINT_TR}"
        if self._audio_error:
            status = self._audio_error
        return (main, f"Düzen: {layout}", status)

    def _draw_hud(self, painter: QPainter, canvas: QRectF) -> None:
        """Compact pill: state dot, last note, short status (the long hints are in the window's hint line)."""
        main = self.hud_lines()[0]
        status = self._audio_error or (self._view.status if self._view is not None else WAITING_STATUS_TR)
        playing = self._view.playing if self._view is not None else False
        painter.setFont(self._hud_big_font)
        note_w = painter.fontMetrics().horizontalAdvance(main) if main != "—" else 0
        painter.setFont(self._hud_font)
        status_w = painter.fontMetrics().horizontalAdvance(status)
        box = QRectF(canvas.left() + 12.0, canvas.top() + 12.0,
                     min(canvas.width() - 24.0, 50.0 + (note_w + 14.0 if note_w else 0.0) + status_w), 40.0)
        theme.paint_glass(painter, box, 20.0, alpha=0.86, blur=0)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.SUCCESS if playing else theme.CONTROL_STROKE))
        painter.drawEllipse(QPointF(box.left() + 18.0, box.center().y()), 5.0, 5.0)
        align = int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        x = box.left() + 32.0
        if note_w:
            painter.setFont(self._hud_big_font)
            painter.setPen(QColor(theme.TEXT))
            painter.drawText(QRectF(x, box.top(), note_w + 4.0, box.height()), align, main)
            x += note_w + 14.0
        painter.setFont(self._hud_font)
        painter.setPen(QColor(theme.TEXT_SOFT if playing else theme.ACCENT_TEXT))
        painter.drawText(QRectF(x, box.top(), max(0.0, box.right() - x - 8.0), box.height()), align, status)


class InstrumentWindow(QWidget):
    """Top-level "Holoscobe — Enstrüman" window. Closing it hides it; the app keeps running."""

    closed = Signal()
    fixed_rect_changed = Signal(object)     # new "Sabit teller" area from a mouse drag
    free_strings_changed = Signal(object)   # new "Serbest teller" string list from a mouse edit

    def __init__(
        self,
        bridge: Optional[UiBridge] = None,
        parent: Optional[QWidget] = None,
        seed: int = 0,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowTitle(INSTRUMENT_WINDOW_TITLE_TR)
        self.resize(960, 620)
        self._clock: Callable[[], float] = clock or (lambda: time.monotonic() * 1000.0)
        self.sparks = SparkSystem(seed=seed)
        self.canvas = InstrumentCanvas(self.sparks, self._clock, bridge=bridge, parent=self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)
        self.canvas.fixed_rect_edited.connect(self.fixed_rect_changed)
        self.canvas.free_strings_edited.connect(self.free_strings_changed)

        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)

    # ---------- state ----------

    @property
    def view(self) -> Optional[InstrumentView]:
        return self.canvas.view

    @property
    def particles_enabled(self) -> bool:
        return self.canvas._particles_enabled

    @property
    def mirrored(self) -> bool:
        return self.canvas.mirrored

    @property
    def is_animating(self) -> bool:
        return self._timer.isActive()

    def hud_lines(self) -> tuple[str, str, str]:
        return self.canvas.hud_lines()

    # ---------- slots (GUI thread) ----------

    @Slot(object)
    def update_view(self, view: Optional[InstrumentView]) -> None:
        """New engine render state. Hits spawn sparks once; strings are redrawn on the next tick."""
        self.canvas.set_view(view)
        if view is not None and self.canvas._particles_enabled:
            now = self._clock()
            for hit in view.hits:
                self.sparks.emit(hit, now)
        if not self.is_animating:
            self.canvas.update()

    @Slot(object)
    def set_camera_image(self, image: Optional[QImage]) -> None:
        self.canvas.set_camera_image(image)

    @Slot(object)
    def set_frame(self, frame: Optional[FrameFeatures]) -> None:
        """Hand skeleton source when no bridge is given (the bridge feeds frame_updated itself)."""
        self.canvas.set_frame(frame)

    @Slot(bool)
    def set_mirrored(self, mirrored: bool) -> None:
        self.canvas.set_mirrored(mirrored)

    @Slot(bool)
    def set_free_snap(self, enabled: bool) -> None:
        self.canvas.set_free_snap(enabled)

    @Slot(str)
    def set_audio_error(self, text: str) -> None:
        self.canvas.set_audio_error(text)

    @Slot(bool)
    def set_particles_enabled(self, enabled: bool) -> None:
        self.canvas.set_particles_enabled(enabled)
        if not enabled:
            self.sparks.clear()
        self.canvas.update()

    # ---------- animation ----------

    @Slot()
    def _tick(self) -> None:
        self.sparks.step(self._clock())
        self.canvas.update()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._timer.isActive():
            self._timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        self.sparks.clear()
        event.accept()
        self.closed.emit()

    def render_to_image(self, width: int = 960, height: int = 620) -> QImage:
        """Render offscreen (tests, screenshots). Advances sparks to the current clock first."""
        self.sparks.step(self._clock())
        return self.canvas.render_to_image(width, height)


__all__ = [
    "INSTRUMENT_WINDOW_TITLE_TR", "InstrumentCanvas", "InstrumentWindow", "LAYOUT_LABELS_TR", "Spark",
    "SparkSystem",
]
