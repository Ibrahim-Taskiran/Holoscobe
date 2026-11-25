"""The cat on the desktop: a transparent, click-through window in the bottom-right corner (GUI thread only)."""
from __future__ import annotations

import logging
import math
import random
import time
from dataclasses import replace
from typing import Any, Callable, Optional

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, QTimer, Slot
from PySide6.QtGui import QCursor, QGuiApplication, QImage, QPainter
from PySide6.QtWidgets import QWidget

from handcontrol.contracts import CameraState, ControlState, Handedness, Mode
from handcontrol.mascot.notes import NoteCloud
from handcontrol.mascot.perception import Perception
from handcontrol.mascot.renderer import Brush, CatRenderer, RendererError
from handcontrol.mascot.retarget import Retargeter, hand_info
from handcontrol.mascot.rig import MascotPose, PoseSmoother, pack

log = logging.getLogger(__name__)

SIZE = (380, 342)                            # logical pixels
ACTIVE_MS, IDLE_MS = 33, 66
MAX_PIXELS = 620                             # device pixels of the longer side: keeps the cost flat on 4K screens
UNDER_CURSOR_OPACITY = 0.28
BRUSH_LINGER_S = 1.2                         # the brush stays in the paw between two strokes
START_FAILED_TR = "Kedi gösterilemiyor (OpenGL 3.3 gerekli)"


class MascotWindow(QWidget):
    def __init__(self, pose_source: Callable[[float], MascotPose], *, renderer_factory: Callable[[], Any] = CatRenderer,
                 cursor: Callable[[], QPoint] = QCursor.pos, brush_side: Callable[[], int] = lambda: 1) -> None:
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.WindowTransparentForInput | Qt.WindowType.WindowDoesNotAcceptFocus
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setWindowTitle("Holoscobe Kedi")
        self.resize(*SIZE)
        self._source, self._factory, self._cursor = pose_source, renderer_factory, cursor
        self._renderer: Optional[Any] = None
        self.error: Optional[str] = None
        self._image = QImage()
        self._smooth = PoseSmoother()
        self._start = self._last = time.monotonic()
        self._previous: Any = None
        self._opacity = 1.0
        self._blink_at, self._blinking = self._start + 2.0, 0.0
        self._glance, self._glance_at = (0.0, 0.0), 0.0
        self._notes = NoteCloud()
        self._brush_side = brush_side
        self._brush_on, self._brush_until, self._brush_size = False, 0.0, 0.0
        self._brush_color: Optional[tuple[float, ...]] = None      # shown now, follows _brush_wanted
        self._brush_wanted: tuple[float, ...] = (0.0, 0.0, 0.0)
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)

    def set_visible(self, on: bool) -> bool:
        """Show or hide the cat; returns False when this machine cannot draw it."""
        if not on:
            self._timer.stop()
            self.hide()
            self._notes.clear()
            self._brush_on, self._brush_until, self._brush_size = False, 0.0, 0.0
            return True
        if self._renderer is None and self.error is None:
            try:
                self._renderer = self._factory()
            except RendererError as exc:
                self.error = str(exc)
                log.warning("mascot unavailable: %s", exc)
            except Exception as exc:
                self.error = str(exc)
                log.exception("mascot unavailable")
        if self._renderer is None:
            return False
        if not self.isVisible():
            self._place()
            self._last = time.monotonic()
            self.show()
            self._timer.start(ACTIVE_MS)
        return True

    def close_renderer(self) -> None:
        self._timer.stop()
        self.hide()
        renderer, self._renderer = self._renderer, None
        if renderer is not None:
            renderer.close()

    def set_playing(self, on: bool) -> None:
        """Instrument mode is running: notes rise around the cat."""
        self._notes.set_playing(on)

    @Slot()
    def pluck(self) -> None:
        if self.isVisible():
            self._notes.pluck(time.monotonic())

    @Slot(object, bool)
    def set_brush(self, color: tuple[int, int, int], drawing: bool) -> None:
        """Ink color of the drawing mode, and whether the pen or the color wheel is in use."""
        self._brush_wanted = tuple(float(c) for c in color)
        if self._brush_on and not drawing:
            self._brush_until = time.monotonic() + BRUSH_LINGER_S
        self._brush_on = drawing

    def _brush(self, pose: MascotPose, now: float, dt: float) -> Optional[Brush]:
        side = self._brush_side()
        held = (self._brush_on or now < self._brush_until) and pose.paws[side].weight > 0.5
        self._brush_size += (float(held) - self._brush_size) * min(1.0, dt * 11.0)
        if self._brush_size < 0.02:
            self._brush_color = None
            return None
        old = self._brush_color or self._brush_wanted
        k = min(1.0, dt * 14.0)
        self._brush_color = tuple(a + (b - a) * k for a, b in zip(old, self._brush_wanted))
        return Brush(side, self._brush_color, self._brush_size)

    def _place(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            self.setGeometry(QRect(area.right() - self.width() + 1, area.bottom() - self.height() + 1,
                                   self.width(), self.height()))

    def _tick(self) -> None:
        now = time.monotonic()
        dt, self._last = now - self._last, now
        self._place()                                          # follows taskbar, resolution and scale changes
        pose = self._smooth.step(self._idle(self._source(now), now), dt)
        values = pack(pose)
        moving = self._previous is None or float(abs(values - self._previous).max()) > 0.004
        self._previous = values
        notes, brush = self._notes.step(now), self._brush(pose, now, dt)
        wanted = ACTIVE_MS if moving or notes or brush is not None or pose.present > 0.5 else IDLE_MS
        if self._timer.interval() != wanted:
            self._timer.setInterval(wanted)
        self._fade(dt)
        ratio = self.devicePixelRatioF()
        ratio = min(ratio, MAX_PIXELS / max(SIZE))
        try:
            image = self._renderer.render(pose, now - self._start, round(self.width() * ratio), round(self.height() * ratio),
                                          pupil=0.30 + 0.30 * max(0.0, pose.brow) + 0.06 * math.sin(now * 0.6), brush=brush)
        except Exception:
            log.exception("mascot drawing stopped")
            self.error = START_FAILED_TR
            self.close_renderer()
            return
        if not image.isNull():
            self._image = image
        if notes or not image.isNull():
            self.update()

    def _idle(self, pose: MascotPose, now: float) -> MascotPose:
        """Life of its own when nobody is tracked: blinks and looks at the mouse cursor."""
        if pose.present > 0:
            return pose
        if now >= self._blink_at:
            self._blinking, self._blink_at = now + 0.16, now + random.uniform(2.2, 6.0)
        blink = 1.0 if now < self._blinking else 0.0
        centre = self.geometry().center()
        at = self._cursor()
        dx, dy = (at.x() - centre.x()) / 900.0, (centre.y() - at.y()) / 700.0
        dx, dy = max(-1.0, min(1.0, dx)), max(-1.0, min(1.0, dy))
        return replace(pose, blink=(blink, blink), gaze=(dx, dy * 0.8), yaw=dx * 0.42, pitch=dy * 0.22)

    def _fade(self, dt: float) -> None:
        box = self.geometry().adjusted(60, 20, -60, 0)
        target = UNDER_CURSOR_OPACITY if box.contains(self._cursor()) else 1.0
        self._opacity += (target - self._opacity) * min(1.0, dt * 9.0)

    def paintEvent(self, event) -> None:
        if self._image.isNull():
            return
        painter = QPainter(self)
        self._notes.paint(painter, QRectF(self.rect()), time.monotonic(), self._opacity)     # behind the cat
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setOpacity(self._opacity)
        painter.drawImage(self.rect(), self._image)
        painter.end()


class Mascot:
    """Connects camera, hands and settings with the cat window. Created once by the app, GUI thread only
    (except `tap` and `on_features`, which the tracking thread calls)."""

    def __init__(self, bridge: Any, *, enabled: bool = True, notify: Optional[Callable[[str], None]] = None,
                 window: Optional[MascotWindow] = None, perception: Optional[Any] = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._bridge, self._notify, self._clock = bridge, notify, clock
        self.retarget = Retargeter()
        self.perception = perception or Perception(self.retarget.set_face, self.retarget.set_body)
        self.window = window or MascotWindow(self.retarget.pose, brush_side=lambda: self.retarget.right_side)
        self.enabled = bool(enabled)
        self._shown = False
        self._warned = False
        bridge.state_changed.connect(self.apply_state)
        self.apply_state(bridge.state)

    def tap(self, frame_bgr: Any, capture_ms: float) -> None:
        self.perception.tap(frame_bgr, capture_ms)

    def on_features(self, features: Any, _events: Any = None, _snapshot: Any = None) -> None:
        if not self._shown:
            return
        aspect = features.width / max(1, features.height)
        self.retarget.aspect = aspect
        self.retarget.set_hands([hand_info(h.landmarks, [f.curl for f in h.fingers[1:]], aspect,
                                           h.handedness is Handedness.RIGHT)
                                 for h in features.hands if len(h.landmarks) == 21], self._clock())

    def set_enabled(self, on: bool) -> None:
        self.enabled = bool(on)
        self.apply_state(self._bridge.state)

    def apply_state(self, state: Any) -> None:
        wanted = self.enabled and state.camera_state is CameraState.RUNNING
        self.window.set_playing(wanted and state.mode is Mode.INSTRUMENT and state.control_state is ControlState.ACTIVE)
        if wanted == self._shown:
            return
        if not self.window.set_visible(wanted) and wanted:
            if not self._warned and self._notify is not None:
                self._warned = True
                self._notify(START_FAILED_TR)
            return
        self._shown = wanted
        self.perception.set_enabled(wanted)

    def close(self) -> None:
        self._shown = False
        self.perception.close()
        self.window.close_renderer()


__all__ = ["Mascot", "MascotWindow"]
