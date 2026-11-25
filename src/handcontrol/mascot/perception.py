"""Background face and arm tracking for the cat. Hand tracking always comes first: this runs on its own thread, at a low
rate, on the newest camera frame only, and it stops completely while the cat is hidden."""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from handcontrol.mascot.retarget import BodyInfo, FaceInfo, body_info, face_info

log = logging.getLogger(__name__)

FACE_INTERVAL_S = 1 / 15
BODY_INTERVAL_S = 1 / 8
WIDTH = 640


class Perception:
    """tap() on the tracking thread; on_face / on_body are called on the worker thread."""

    def __init__(self, on_face: Callable[[Optional[FaceInfo], float], None],
                 on_body: Callable[[Optional[BodyInfo], float], None], *, models: Optional[Path] = None) -> None:
        self._on_face, self._on_body, self._models = on_face, on_body, models
        self._wake = threading.Condition()
        self._frame: Any = None
        self._enabled = False
        self._stop = False
        self._thread: Optional[threading.Thread] = None
        self._last_tap = 0.0
        self.failed: set[str] = set()

    def set_enabled(self, on: bool) -> None:
        with self._wake:
            self._enabled = bool(on)
            if not on:
                self._frame = None
            elif self._thread is None and not self._stop:
                self._thread = threading.Thread(target=self._run, name="mascot-perception", daemon=True)
                self._thread.start()
            self._wake.notify()

    def tap(self, frame_bgr: Any, capture_ms: float) -> None:
        """TrackingLoop.on_image: keep a small copy when the worker is ready for the next one."""
        now = time.monotonic()
        if not self._enabled or now - self._last_tap < FACE_INTERVAL_S or self._frame is not None:
            return
        self._last_tap = now
        import cv2  # lazy
        h, w = frame_bgr.shape[:2]
        small = cv2.resize(frame_bgr, (WIDTH, max(1, round(WIDTH * h / w))), interpolation=cv2.INTER_LINEAR)
        with self._wake:
            self._frame = small
            self._wake.notify()

    def close(self) -> None:
        with self._wake:
            self._stop = True
            self._enabled = False
            self._frame = None
            self._wake.notify()
        if self._thread is not None:
            self._thread.join(2.0)
            self._thread = None

    # ---------- worker thread ----------

    def _model(self, name: str) -> bytes:
        if self._models is None:
            from handcontrol.tracking import project_root
            self._models = project_root() / "assets" / "models"
        return (self._models / name).read_bytes()           # buffer, not path: MediaPipe cannot open non-ASCII paths

    def _create(self, kind: str) -> Any:
        from mediapipe.tasks.python import BaseOptions, vision
        if kind == "face":
            options = vision.FaceLandmarkerOptions(
                base_options=BaseOptions(model_asset_buffer=self._model("face_landmarker.task")),
                running_mode=vision.RunningMode.VIDEO, num_faces=1, output_face_blendshapes=True,
                output_facial_transformation_matrixes=True)
            return vision.FaceLandmarker.create_from_options(options)
        options = vision.PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_buffer=self._model("pose_landmarker_lite.task")),
            running_mode=vision.RunningMode.VIDEO)
        return vision.PoseLandmarker.create_from_options(options)

    def _run(self) -> None:
        tools: dict[str, Any] = {}
        next_body, stamp = 0.0, 0
        try:
            while True:
                with self._wake:
                    while not self._stop and self._frame is None:
                        self._wake.wait(1.0)
                    if self._stop:
                        return
                    frame = self._frame
                now = time.monotonic()
                stamp = max(stamp + 1, int(now * 1000))
                try:
                    self._handle(tools, frame, stamp, now, now >= next_body)
                    if now >= next_body:
                        next_body = now + BODY_INTERVAL_S
                finally:
                    with self._wake:
                        self._frame = None
        except Exception:
            log.exception("mascot tracking stopped")
        finally:
            for tool in tools.values():
                try:
                    tool.close()
                except Exception:
                    pass

    def _handle(self, tools: dict[str, Any], frame: Any, stamp: int, now: float, with_body: bool) -> None:
        import cv2  # lazy
        import mediapipe as mp  # lazy
        h, w = frame.shape[:2]
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        for kind in ("face", "body"):
            if kind in self.failed or kind == "body" and not with_body:
                continue
            try:
                if kind not in tools:
                    tools[kind] = self._create(kind)
                result = tools[kind].detect_for_video(image, stamp)
                if kind == "face":
                    self._on_face(self._face(result, w / h), now)
                else:
                    poses = result.pose_landmarks
                    self._on_body(body_info(poses[0], w / h) if poses else None, now)
            except Exception:
                log.exception("mascot %s tracking unavailable", kind)
                self.failed.add(kind)

    @staticmethod
    def _face(result: Any, aspect: float) -> Optional[FaceInfo]:
        if not result.face_landmarks or not result.facial_transformation_matrixes or not result.face_blendshapes:
            return None
        shapes = {c.category_name: c.score for c in result.face_blendshapes[0]}
        return face_info(result.face_landmarks[0], shapes, result.facial_transformation_matrixes[0], aspect)


__all__ = ["Perception"]
