"""Live camera canvas. Scene mutation and painting both run on the GUI thread."""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from handcontrol.contracts import CameraState, ControlState, Mode
from handcontrol.drawing import CLEAR_MS, ERASER_RADIUS, projected_y, turn
from handcontrol.drawing_gestures import DrawingControls, HOLD_MS

DRAWING_HINT_TR = ("Sağ işaretle çiz · Sağ avucu açıp taşı · Sağ yumrukla ön yüzeyi sil · "
                   "Sol avucu açık tutarak döndür · Temizlemek için ön kollarını X yapıp tut")
GROW_MS = 165.0        # a fresh dab swells for this long
INK = [QColor(v, v, v + 2) for v in range(9, 46)]


def now_ms():
    return time.monotonic() * 1000


class DrawingView(QWidget):
    _sample = Signal(object, int, bool)

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
        self._sample.connect(self._accept, Qt.ConnectionType.QueuedConnection)
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._animate)
        self.setAccessibleName("Üç boyutlu mürekkep çizim alanı")

    def bind(self, pipeline):
        self._pipeline = pipeline
        pipeline.add_frame_observer(self._observe)

    def _observe(self, frame, events, snap):
        if snap.mode is Mode.DRAWING:
            usable = (snap.state is ControlState.ACTIVE and snap.camera_state is CameraState.RUNNING
                      and snap.menu is None and not snap.clap_pending)
            self._sample.emit(frame, snap.epoch, usable)

    @Slot(object, int, bool)
    def _accept(self, frame, epoch, usable):
        if epoch != self._pipeline.controller.current_epoch():
            return
        if self._epoch != epoch or not usable or now_ms() - frame.capture_ms > self._pipeline.controller.config.stale_ms:
            self.controls.reset()
            self._epoch = epoch
            if not usable or now_ms() - frame.capture_ms > self._pipeline.controller.config.stale_ms:
                self._dirty = True
                return
        self._pose_available = getattr(frame, "forearms_crossed", None) is not None
        self.controls.update(frame)
        self._dirty = True

    def set_state(self, state):
        self._mirrored = state.mirrored
        active = (state.mode is Mode.DRAWING and state.control_state is ControlState.ACTIVE
                  and state.camera_state is CameraState.RUNNING)
        if self._active and not active:
            self.controls.reset()
        self._dirty = True
        self._active = active

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
        if scene.clear_start is not None:
            scene.advance(now_ms())
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
            p.restore()
            self._paint_status(p, rect)
        finally:
            p.end()

    def _paint_ink(self, p, w, h, now):
        scene = self.controls.scene
        dabs = scene.dabs
        if scene.clear_start is None:
            dabs = self._settled_layer(p, w, h, now)
        self._paint_dabs(p, dabs, w, h, now)

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
        clearing = scene.clear_start is not None
        elapsed = (now - scene.clear_start)/CLEAR_MS if clearing else 0
        p.setPen(Qt.PenStyle.NoPen)
        for dab in sorted(dabs, key=lambda d: d.z*c - d.x*s):
            x, depth = turn(dab.x, dab.z, c, s)
            y = projected_y(dab.y, depth) * w
            growth = max(0, min(1, (now - dab.born) / GROW_MS))
            radius = w*dab.radius*(1 - 0.55*(1-growth)**2)
            ry = radius*dab.stretch
            if clearing:
                # Neighbouring dabs share a fall time so a band separates into rivulets.
                phase = (0.5 + 0.5*math.sin(92*x + 5*math.sin(x*27))) * 0.19
                flow = max(0, min(1, (elapsed-phase)/(1-phase)))
                radius *= 1 - 0.94*flow
                tail = w*(0.012 + 0.075*dab.grain)*math.sin(flow*math.pi)
                ry += tail
                y += tail + h*1.55*flow**2
                p.setOpacity(1-flow**2)
            shade = max(0, min(len(INK)-1, round(12 - depth*63 + dab.grain*2)))
            p.setBrush(INK[shade])
            p.drawEllipse(QPointF(x*w, y), max(0.45, radius), ry)
        p.setOpacity(1)

    def _paint_cursor(self, p, w):
        ctl = self.controls
        if ctl.cursor is None or not self._active:
            return
        at = QPointF(ctl.cursor[0]*w, ctl.cursor[1]*w)
        erase = ctl.tool == "erase"
        radius = ERASER_RADIUS*w if erase else 7
        p.setBrush(Qt.BrushStyle.NoBrush)
        for color, width in ((QColor(20, 24, 30, 210), 4), (QColor("#ffcd81" if erase else "#ffffff"), 1.5)):
            pen = QPen(color, width)
            if ctl.tool == "carry":
                pen.setStyle(Qt.PenStyle.DotLine)
            p.setPen(pen)
            p.drawEllipse(at, radius, radius)

    def _paint_status(self, p, rect):
        ctl = self.controls
        if self._image is None:
            text = "Kamera görüntüsü bekleniyor"
        elif not self._active:
            text = "Çizim duraklatıldı"
        elif ctl.scene.clear_start is not None:
            text = "Mürekkep akıyor"
        elif ctl.cross_since is not None:
            progress = min(100, int(100*(ctl.last_time-ctl.cross_since)/HOLD_MS))
            text = f"X hareketini tut · %{progress}"
        else:
            text = {"carry": "Taşı", "erase": "Silgi · Ön yüzey", "brush": "Fırça"}[ctl.tool]
            if ctl.spinning:
                text += "  ·  Dönüyor"
            if not self._pose_available:
                text += "  ·  X için poz modelini kur"
        bounds = QRectF(rect.left()+10, rect.top()+10, p.fontMetrics().horizontalAdvance(text)+24, 30)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(18, 22, 28, 230))
        p.drawRoundedRect(bounds, 7, 7)
        p.setPen(QColor("#f3f5f8"))
        p.drawText(bounds, Qt.AlignmentFlag.AlignCenter, text)
