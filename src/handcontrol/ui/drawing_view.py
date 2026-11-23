"""Live camera canvas. Scene mutation and painting both run on the GUI thread."""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from handcontrol.contracts import CameraState, ControlState, Mode
from handcontrol.drawing import (CLEAR_MS, DEPTH_STEP, ERASER_RADIUS, PALETTE, SHADES, depth_level, projected_y,
                                 shade_rgb, turn)
from handcontrol.drawing_gestures import DrawingControls, HOLD_MS
from handcontrol.drawing_raster import InkRaster

DRAWING_HINT_TR = ("Sağ işaretle çiz · Sağ avucu açıp taşı · Sağ yumrukla sil · "
                   "Sağ elle başparmak-işareti birleştirip tut: renk · Sol avucu sağa ya da sola yatırıp döndür · Temizlemek için ön kollarını X yapıp tut")
GROW_MS = 165.0        # a fresh dab swells for this long
FAST_DABS = 600         # above this a moving scene is painted by the fast rasterizer
FAST_SCALE = 0.7
FLOW_SCALE = 0.5
INK = [[QColor(*shade_rgb(c, k)) for k in range(SHADES)] for c in range(len(PALETTE))]


def now_ms():
    return time.monotonic() * 1000


class DrawingView(QWidget):
    _sample = Signal(object, int, bool, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.controls = DrawingControls()
        self._pipeline = None
        self._epoch = None
        self._mirrored = True
        self._active = False
        self._pose_available = True
        self._image = None
        self._aspect = 4/3
        self._dirty = False
        self._layer = None               # settled ink of the current angle
        self._layer_key = None
        self._baked = 0
        self._seen_key = None
        self._raster = InkRaster()
        self._sample.connect(self._accept, Qt.ConnectionType.QueuedConnection)
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._animate)
        self.setAccessibleName("Üç boyutlu mürekkep çizim alanı")

    def bind(self, pipeline):
        self._pipeline = pipeline
        pipeline.add_frame_observer(self._observe)

    def _observe(self, frame, events, snap):
        if snap.mode is Mode.DRAWING:
            usable = (snap.state is ControlState.ACTIVE and snap.camera_state is CameraState.RUNNING
                      and snap.menu is None)
            self._sample.emit(frame, snap.epoch, usable, not snap.clap_pending)

    @Slot(object, int, bool, bool)
    def _accept(self, frame, epoch, usable, hands_ok):
        if epoch != self._pipeline.controller.current_epoch():
            return
        self._dirty = True
        if not usable or now_ms() - frame.capture_ms > self._pipeline.controller.config.stale_ms:
            self.controls.reset()
            return
        if self._epoch != epoch:             # a clap candidate raises the epoch: a held X must survive it
            self._epoch = epoch
            self.controls.pen_up()
        self._pose_available = getattr(frame, "forearms_crossed", None) is not None
        self.controls.update(frame, hands_ok)

    def set_state(self, state):
        self._mirrored = state.mirrored
        active = (state.mode is Mode.DRAWING and state.control_state is ControlState.ACTIVE
                  and state.camera_state is CameraState.RUNNING)
        if self._active and not active:
            self.controls.reset()
        self._dirty = True
        self._active = active

    @Slot()
    def clear(self):
        self.controls.scene.clear(now_ms())
        self._dirty = True

    def set_camera_image(self, image: QImage | None):
        self._image = image
        if image and image.height():
            self._aspect = image.width() / image.height()
        self._dirty = True

    def showEvent(self, event):
        super().showEvent(event)
        self._timer.start()

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def _animate(self):
        scene = self.controls.scene
        scene.advance(now_ms())
        if scene.clear_start is not None or scene.spin_speed or scene.spin_target:
            pass
        elif not self._dirty and not (scene.dabs and now_ms() - scene.dabs[-1].born < GROW_MS + 75):
            return
        self._dirty = False              # camera image and hand samples share one repaint per tick
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.fillRect(self.rect(), QColor("#11151a"))
            w = min(self.width(), self.height()*self._aspect)
            if w <= 0:
                return
            h = w/self._aspect
            rect = QRectF((self.width()-w)/2, (self.height()-h)/2, w, h)
            p.save()
            p.setClipRect(rect)
            p.translate(rect.center())
            p.scale(-1 if self._mirrored else 1, 1)
            if self._image is not None:
                p.drawImage(QRectF(-w/2, -h/2, w, h), self._image)
            self._paint_ink(p, w, h, now_ms())
            self._paint_cursor(p, w)
            self._paint_palette(p, w, h)
            p.restore()
            self._paint_status(p, rect)
        finally:
            p.end()

    def _paint_ink(self, p, w, h, now):
        scene = self.controls.scene
        if scene.clear_start is not None:
            self._paint_fast(p, w, h, now, max(0.0, (now - scene.clear_start)/CLEAR_MS))
        else:
            key = (scene.revision, scene.angle, w, h)
            moved, self._seen_key = key != self._seen_key, key
            if moved and len(scene.dabs) > FAST_DABS:       # spinning or erasing: soft and fast, sharp once it rests
                self._paint_fast(p, w, h, now)
                self._dirty = True
                return
            self._paint_dabs(p, self._settled_layer(p, w, h, now), w, h, now)

    def _paint_fast(self, p, w, h, now, flow=None):
        k = FAST_SCALE if flow is None else FLOW_SCALE
        buf = self._raster.render(self.controls.scene, max(1, round(w*k)), max(1, round(h*k)), now, GROW_MS, flow)
        rows, cols = buf.shape
        image = QImage(buf.data, cols, rows, 4*cols, QImage.Format.Format_ARGB32_Premultiplied)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawImage(QRectF(-w/2, -h/2, w, h), image)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)

    def _settled_layer(self, p, w, h, now):
        """Draw the ink that no longer changes from a cached picture; return the dabs still to paint."""
        scene, ratio = self.controls.scene, self.devicePixelRatioF()
        key = (scene.revision, scene.angle, w, h, ratio)
        if key != self._layer_key or self._baked > len(scene.dabs):
            self._layer_key, self._baked = key, 0
            self._layer = QPixmap(max(1, round(w*ratio)), max(1, round(h*ratio)))
            self._layer.fill(Qt.GlobalColor.transparent)
        settled = self._baked
        while settled < len(scene.dabs) and now - scene.dabs[settled].born >= GROW_MS:
            settled += 1
        if settled > self._baked:
            q = QPainter(self._layer)
            q.setRenderHint(QPainter.RenderHint.Antialiasing)
            q.translate(self._layer.width()/2, self._layer.height()/2)
            q.scale(self._layer.width()/w, self._layer.height()/h)
            self._paint_dabs(q, scene.dabs[self._baked:settled], w, h, now)
            q.end()
            self._baked = settled
        p.drawPixmap(QRectF(-w/2, -h/2, w, h), self._layer, QRectF(self._layer.rect()))
        return scene.dabs[settled:]

    def _paint_dabs(self, p, dabs, w, h, now):
        scene = self.controls.scene
        c, s = math.cos(scene.angle), math.sin(scene.angle)
        p.setPen(Qt.PenStyle.NoPen)
        for dab in sorted(dabs, key=lambda d: round((d.z*c - d.x*s)/DEPTH_STEP)):
            x, depth = turn(dab.x, dab.z, c, s)
            y = projected_y(dab.y, depth) * w
            growth = max(0, min(1, (now - dab.born) / GROW_MS))
            radius = w*dab.radius*(1 - 0.55*(1-growth)**2)
            ry = radius*dab.stretch
            p.setBrush(INK[dab.color][depth_level(depth, dab.grain)])
            p.drawEllipse(QPointF(x*w, y), max(0.45, radius), ry)

    def _paint_cursor(self, p, w):
        ctl = self.controls
        if ctl.cursor is None or not self._active:
            return
        at = QPointF(ctl.cursor[0]*w, ctl.cursor[1]*w)
        erase = ctl.tool == "erase"
        radius = ERASER_RADIUS*w if erase else 7
        p.setBrush(INK[ctl.scene.color][0] if ctl.tool == "brush" else Qt.BrushStyle.NoBrush)
        for color, width in ((QColor(20, 24, 30, 210), 4), (QColor("#ffcd81" if erase else "#ffffff"), 1.5)):
            pen = QPen(color, width)
            if ctl.tool == "carry":
                pen.setStyle(Qt.PenStyle.DotLine)
            p.setPen(pen)
            p.drawEllipse(at, radius, radius)

    def _paint_palette(self, p, w, h):
        """Color wheel around the pinching hand, in (possibly mirrored) image coordinates."""
        wheel, frame = self.controls.palette, self.controls.frame_size
        if wheel is None or wheel.anchor is None or not self._active:
            return
        outer = 0.15*w
        inner = 0.42*outer
        fw, fh = frame
        edge = outer*1.1
        cx = max(-w/2 + edge, min(w/2 - edge, (wheel.anchor[0]/fw - 0.5)*w))
        cy = max(-h/2 + edge, min(h/2 - edge, (wheel.anchor[1] - fh/2)/fw*w))
        step = 360/wheel.n
        for i in range(wheel.n):
            hot = i == wheel.hovered
            r = outer*(1.1 if hot else 1)
            path = QPainterPath()
            start, span = 90 - (i - 0.5)*step - 1.5, -(step - 3)
            path.arcMoveTo(QRectF(cx - r, cy - r, 2*r, 2*r), start)
            path.arcTo(QRectF(cx - r, cy - r, 2*r, 2*r), start, span)
            path.arcTo(QRectF(cx - inner, cy - inner, 2*inner, 2*inner), start + span, -span)
            path.closeSubpath()
            p.setBrush(QColor(*PALETTE[i][1]))
            p.setPen(QPen(QColor("#26c6da") if hot else QColor(240, 244, 248) if i == self.controls.scene.color
                          else QColor(18, 22, 28, 220), 4 if hot else 2.5))
            p.drawPath(path)
        hub = inner - 5
        p.setBrush(QColor(18, 22, 28, 235))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), hub, hub)
        p.save()
        p.translate(cx, cy)
        p.scale(-1 if self._mirrored else 1, 1)            # upright text in the mirrored picture
        p.setPen(QColor("#f3f5f8"))
        p.drawText(QRectF(-hub, -hub, 2*hub, 2*hub), Qt.AlignmentFlag.AlignCenter,
                   "Renk" if wheel.hovered is None else PALETTE[wheel.hovered][0])
        p.restore()
        p.setPen(QPen(QColor(12, 16, 22), 2))
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QPointF(cx + (wheel.pointer[0] - 0.5)*2*outer, cy + (wheel.pointer[1] - 0.5)*2*outer), 6, 6)

    def _paint_status(self, p, rect):
        ctl = self.controls
        if self._image is None:
            text = "Kamera görüntüsü bekleniyor"
        elif not self._active:
            text = "Çizim duraklatıldı"
        elif ctl.scene.clear_start is not None:
            text = "Mürekkep akıyor"
        elif ctl.blocked:
            text = f"X hareketini tut · %{min(100, int(100*ctl.cross/HOLD_MS))}"
        else:
            text = {"carry": "Taşı", "erase": "Silgi", "brush": f"Fırça · {PALETTE[ctl.scene.color][0]}"}[ctl.tool]
            if ctl.palette is not None:
                text = "Renk · Dilime götür, parmaklarını ayır"
            if ctl.tool == "erase" and ctl.scene.erase_front is not None:
                text += " · Ön yüzey" if ctl.scene.erase_front else " · Arka yüzey"
            if ctl.spin:
                right = (ctl.spin > 0) is not self._mirrored
                text += "  ·  Sağa dönüyor" if right else "  ·  Sola dönüyor"
            elif ctl.spin_ready:
                text += "  ·  Döndürmek için sol avucu yana yatır"
            if not self._pose_available:
                text += "  ·  X için poz modelini kur"
        bounds = QRectF(rect.left()+10, rect.top()+10, p.fontMetrics().horizontalAdvance(text)+24, 30)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(18, 22, 28, 230))
        p.drawRoundedRect(bounds, 7, 7)
        p.setPen(QColor("#f3f5f8"))
        p.drawText(bounds, Qt.AlignmentFlag.AlignCenter, text)
