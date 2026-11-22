"""Synthetic two-hand fixtures for instrument tests (uniquely named so it never collides with other
folders' helper modules). Proves logic only, not real-camera accuracy.

Default scene (640x480, palm scale 100 px for both hands):
- string hand (LEFT label): thumb tip (250, 250), index tip (380, 250): horizontal string, 1.3 pu;
  palm centre (300, 380) below it, so chord strings are offset upward (y = 220, 190, 160).
- pick hand (RIGHT label): index tip wherever the test puts it, palm centre at tip + (120, 60).
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Iterable, Optional

from handcontrol.contracts import (
    CameraState, ControlState, FingerInfo, FingerName, FingerState, FrameFeatures, HandFeatures, Handedness,
    Landmark, Mode, Quality,
)

W, H = 640, 480
Vec = tuple[float, float]


def make_hand(*, hand_id: int, handedness: Handedness, thumb: Vec, index: Vec, palm: Vec, scale: float = 100.0,
              quality: Quality = Quality.USABLE, width: int = W, height: int = H) -> HandFeatures:
    """21 landmarks consistent with the given thumb tip (4), index tip (8) and palm centre; the MCPs
    5/9/13/17 sit around the palm centre so their mean is the palm centre; wrist below the palm."""
    pts: list[Vec] = [palm] * 21
    pts[0] = (palm[0], palm[1] + 0.9 * scale)
    off = 0.35 * scale
    pts[5], pts[9], pts[13], pts[17] = ((palm[0] - off, palm[1]), (palm[0] - off / 3, palm[1]),
                                         (palm[0] + off / 3, palm[1]), (palm[0] + off, palm[1]))
    pts[4] = thumb
    pts[8] = index
    lms = tuple(Landmark(x / width, y / height, 0.0) for x, y in pts)
    fingers = tuple(FingerInfo(n, FingerState.EXTENDED, 0.0) for n in FingerName)
    pinch = (((thumb[0] - index[0]) ** 2 + (thumb[1] - index[1]) ** 2) ** 0.5 / scale) if scale > 0 else 0.0
    return HandFeatures(hand_id=hand_id, handedness=handedness, quality=quality, palm_center_px=palm,
                        palm_scale_px=scale, fingers=fingers, pinch_distance=pinch, index_tip_px=index,
                        landmarks=lms)


def string_hand(*, thumb: Vec = (250.0, 250.0), index: Vec = (380.0, 250.0), palm: Vec = (300.0, 380.0),
                scale: float = 100.0, hand_id: int = 1, handedness: Handedness = Handedness.LEFT,
                quality: Quality = Quality.USABLE) -> HandFeatures:
    return make_hand(hand_id=hand_id, handedness=handedness, thumb=thumb, index=index, palm=palm, scale=scale,
                     quality=quality)


def pick_hand(tip: Vec, *, scale: float = 100.0, hand_id: int = 2, handedness: Handedness = Handedness.RIGHT,
              quality: Quality = Quality.USABLE, palm_offset: Vec = (120.0, 60.0)) -> HandFeatures:
    palm = (tip[0] + palm_offset[0], tip[1] + palm_offset[1])
    thumb = (tip[0] + 40.0, tip[1] + 50.0)
    return make_hand(hand_id=hand_id, handedness=handedness, thumb=thumb, index=tip, palm=palm, scale=scale,
                     quality=quality)


def frame(t: float, hands: Iterable[HandFeatures], *, ambiguous: bool = False) -> FrameFeatures:
    return FrameFeatures(capture_ms=t, inference_done_ms=t + 5.0, width=W, height=H, hands=tuple(hands),
                         identity_ambiguous=ambiguous)


def two_hands(t: float, tip: Vec, *, ambiguous: bool = False, s_kw: Optional[dict] = None,
              p_kw: Optional[dict] = None) -> FrameFeatures:
    return frame(t, (string_hand(**(s_kw or {})), pick_hand(tip, **(p_kw or {}))), ambiguous=ambiguous)


def run(engine, steps: Iterable[tuple[float, Vec]], *, active: bool = True, s_kw: Optional[dict] = None,
        p_kw: Optional[dict] = None):
    """Feed (t_ms, pick tip) steps; returns [(events, view)] per frame."""
    return [engine.update(two_hands(t, tip, s_kw=s_kw, p_kw=p_kw), active) for t, tip in steps]


def sweep(x: float, y0: float, y1: float, n: int, t0: float = 0.0, dt: float = 33.0) -> list[tuple[float, Vec]]:
    """n+1 frames moving the tip linearly from (x, y0) to (x, y1)."""
    return [(t0 + i * dt, (x, y0 + (y1 - y0) * i / n)) for i in range(n + 1)]


def snap(mode: Mode = Mode.INSTRUMENT, state: ControlState = ControlState.ACTIVE,
         camera: CameraState = CameraState.RUNNING, menu: object = None, clap_pending: bool = False,
         t_ms: float = 0.0) -> SimpleNamespace:
    """Duck-typed ControllerSnapshot with the fields the session reads."""
    return SimpleNamespace(mode=mode, state=state, camera_state=camera, menu=menu, clap_pending=clap_pending,
                           t_ms=t_ms, epoch=0)
