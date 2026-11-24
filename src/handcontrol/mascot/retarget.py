"""Turns face, pose and hand landmarks into a MascotPose (pure math, no Qt, no MediaPipe).

Landmarks come from the unmirrored camera frame; everything here is mirrored once, so "right" always means the right
side of the screen and the cat moves like a mirror image. x is multiplied by the frame aspect, so x and y share a unit.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any, Optional, Sequence

from handcontrol.mascot.rig import MascotPose, PawTarget

FACE_TIMEOUT_S, BODY_TIMEOUT_S, HAND_TIMEOUT_S = 0.7, 0.8, 0.35
SIDE_KEEP = 0.35                             # a lone hand keeps its paw until it is this far (shoulder widths) over the middle
Point = tuple[float, float]


def clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if v < lo else hi if v > hi else v


@dataclass(frozen=True)
class FaceInfo:
    center: Point                            # mirrored, aspect-corrected
    width: float
    yaw: float
    pitch: float
    roll: float
    jaw: float
    smile: float
    brow: float
    blink: Point
    gaze: Point


@dataclass(frozen=True)
class BodyInfo:
    """Shoulders, elbows, wrists ordered (screen left, screen right); None when not visible."""
    shoulders: tuple[Point, Point]
    elbows: tuple[Optional[Point], Optional[Point]]
    wrists: tuple[Optional[Point], Optional[Point]]


@dataclass(frozen=True)
class HandInfo:
    wrist: Point
    curl: float
    lean: float


def face_info(landmarks: Sequence[Any], shapes: dict[str, float], matrix: Any, aspect: float) -> FaceInfo:
    xs = [(1.0 - p.x) * aspect for p in landmarks]
    ys = [p.y for p in landmarks]
    left, right, top, bottom = min(xs), max(xs), min(ys), max(ys)
    r = [[float(matrix[i][j]) for j in range(3)] for i in range(3)]
    scale = math.sqrt(sum(r[i][2] ** 2 for i in range(3))) or 1.0
    fx, fy, fz = (r[i][2] / scale for i in range(3))
    ux, uy = r[0][1] / scale, r[1][1] / scale

    def g(name: str) -> float:
        return float(shapes.get(name, 0.0))
    raised = g("browInnerUp") * 0.6 + (g("browOuterUpLeft") + g("browOuterUpRight")) * 0.35
    gx = (g("eyeLookOutRight") + g("eyeLookInLeft") - g("eyeLookOutLeft") - g("eyeLookInRight")) * 0.75
    gy = (g("eyeLookUpLeft") + g("eyeLookUpRight") - g("eyeLookDownLeft") - g("eyeLookDownRight")) * 0.6
    smile = (g("mouthSmileLeft") + g("mouthSmileRight")) * 0.6
    # A smile also pulls the brows down; only what is left counts as a frown.
    frown = max(0.0, (g("browDownLeft") + g("browDownRight")) * 0.6 - 0.2 - 0.6 * smile)

    def lid(name: str) -> float:
        return clamp((g(name) - 0.22 - 0.12 * smile) / 0.38)
    return FaceInfo(
        center=((left + right) / 2, (top + bottom) / 2), width=max(1e-3, right - left),
        yaw=math.atan2(-fx, fz), pitch=math.asin(clamp(fy, -1.0, 1.0)), roll=-math.atan2(ux, uy),
        jaw=clamp(g("jawOpen") * 1.45 - 0.06), smile=clamp(smile), brow=clamp(raised * 1.3 - frown, -1.0, 1.0),
        blink=(lid("eyeBlinkLeft"), lid("eyeBlinkRight")),         # mirrored: the left eye is on the screen's left
        gaze=(clamp(gx, -1.0, 1.0), clamp(gy, -1.0, 1.0)))


def body_info(landmarks: Sequence[Any], aspect: float) -> Optional[BodyInfo]:
    if len(landmarks) < 17:
        return None

    def point(i: int, level: float) -> Optional[Point]:
        p = landmarks[i]
        if (p.visibility or 0.0) < level or (p.presence or 0.0) < level or not (-0.05 < p.x < 1.05 and -0.05 < p.y < 1.02):
            return None
        return (1.0 - p.x) * aspect, p.y
    raw = [landmarks[i] for i in (11, 12)]
    if min((p.visibility or 0.0) for p in raw) < 0.5:
        return None
    shoulders = tuple(((1.0 - p.x) * aspect, p.y) for p in raw)
    if abs(shoulders[0][0] - shoulders[1][0]) < 0.05:              # side view: no usable shoulder line
        return None
    return BodyInfo(shoulders, (point(13, 0.5), point(14, 0.5)), (point(15, 0.6), point(16, 0.6)))


def hand_info(landmarks: Sequence[Any], curls: Sequence[float], aspect: float) -> HandInfo:
    w, m = landmarks[0], landmarks[9]
    dx, dy = (w.x - m.x) * aspect, w.y - m.y                       # mirrored x, y up
    fingers = [float(c) for c in curls]
    return HandInfo(((1.0 - w.x) * aspect, w.y), clamp((sum(fingers) / max(1, len(fingers)) - 0.15) / 0.6),
                    math.atan2(dx, max(1e-6, abs(dy))) if dy > 0 else 0.0)


@dataclass
class Retargeter:
    """Keeps the newest observation of each kind and builds the pose for any moment."""
    face: Optional[FaceInfo] = None
    body: Optional[BodyInfo] = None
    hands: tuple[HandInfo, ...] = ()
    face_at: float = -1e9
    body_at: float = -1e9
    hands_at: float = -1e9
    aspect: float = 16 / 9
    _pitch0: float = 0.0
    _yaw0: float = 0.0
    _sides: dict[int, Point] = field(default_factory=dict)

    def set_face(self, face: Optional[FaceInfo], now: float) -> None:
        if face is None:
            return
        if now - self.face_at > 3.0:                               # new person or a fresh start
            self._pitch0, self._yaw0 = clamp(face.pitch, -0.45, 0.45), clamp(face.yaw, -0.4, 0.4)
        else:                                                      # laptop cameras sit low: learn the usual view slowly
            k = clamp((now - self.face_at) / 25.0, 0.0, 0.1)
            self._pitch0 += (clamp(face.pitch, -0.45, 0.45) - self._pitch0) * k
            self._yaw0 += (clamp(face.yaw, -0.4, 0.4) - self._yaw0) * k * 0.5
        self.face, self.face_at = face, now

    def set_body(self, body: Optional[BodyInfo], now: float) -> None:
        if body is not None:
            self.body, self.body_at = body, now

    def set_hands(self, hands: Sequence[HandInfo], now: float) -> None:
        if hands:
            self.hands, self.hands_at = tuple(hands)[:2], now

    def _shoulders(self, now: float) -> Optional[tuple[Point, Point]]:
        if self.body is not None and now - self.body_at < BODY_TIMEOUT_S:
            return self.body.shoulders
        if self.face is not None and now - self.face_at < FACE_TIMEOUT_S:
            (cx, cy), w = self.face.center, self.face.width
            return (cx - 1.05 * w, cy + 1.45 * w), (cx + 1.05 * w, cy + 1.45 * w)
        if self.body is not None and now - self.body_at < 4.0:
            return self.body.shoulders
        a = self.aspect                                            # only hands in view: assume somebody in the middle
        return (a / 2 - 0.2, 0.75), (a / 2 + 0.2, 0.75)

    def _assign(self, hands: Sequence[HandInfo], middle: float, span: float) -> dict[int, HandInfo]:
        if len(hands) == 2:
            a, b = sorted(hands, key=lambda h: h.wrist[0])
            return {0: a, 1: b}
        hand = hands[0]
        wrists = self.body.wrists if self.body is not None else (None, None)
        near = {s: math.dist(w, hand.wrist) for s, w in enumerate(wrists) if w is not None}
        if len(near) == 2 and abs(near[0] - near[1]) > 0.5 * span:
            return {min(near, key=near.get): hand}
        for s, last in self._sides.items():                        # same paw while the hand moves continuously
            if math.dist(last, hand.wrist) < 0.8 * span:
                over = (middle - hand.wrist[0]) * (1 if s == 1 else -1) / span
                if over < SIDE_KEEP or len(self._sides) == 1 and over < 1.2:
                    return {s: hand}
        return {0 if hand.wrist[0] < middle else 1: hand}

    def pose(self, now: float) -> MascotPose:
        face = self.face if self.face is not None and now - self.face_at < FACE_TIMEOUT_S else None
        hands = self.hands if now - self.hands_at < HAND_TIMEOUT_S else ()
        body = self.body if self.body is not None and now - self.body_at < BODY_TIMEOUT_S else None
        if face is None and body is None and not hands:
            self._sides = {}
            return MascotPose()
        left, right = self._shoulders(now)
        if left[0] > right[0]:
            left, right = right, left
        span = max(0.08, math.dist(left, right))
        middle = (left[0] + right[0]) / 2
        paws = [PawTarget(), PawTarget()]
        placed = self._assign(hands, middle, span) if hands else {}
        self._sides = {s: h.wrist for s, h in placed.items()}
        for s, origin in enumerate((left, right)):
            side = -1 if s == 0 else 1
            elbow = body.elbows[s] if body is not None else None
            lift = clamp((origin[1] - elbow[1]) / span + 0.85, 0.0, 1.3) if elbow is not None else 0.0
            if s in placed:
                h = placed[s]
                paws[s] = PawTarget(side * (h.wrist[0] - origin[0]) / span, (origin[1] - h.wrist[1]) / span, h.curl,
                                    clamp(h.lean, -1.2, 1.2), 1.0, lift)
            elif body is not None and body.wrists[s] is not None:
                w = body.wrists[s]
                paws[s] = PawTarget(side * (w[0] - origin[0]) / span, (origin[1] - w[1]) / span, 0.25, 0.0, 1.0, lift)
        pose = MascotPose(paws=(paws[0], paws[1]), present=1.0)
        if body is not None:
            tilt = math.atan2(right[1] - left[1], right[0] - left[0])
            pose = replace(pose, shoulders=clamp(tilt, -0.5, 0.5), sway=clamp((middle / self.aspect - 0.5) * 2.2, -1.0, 1.0))
        if face is not None:
            pose = replace(
                pose, yaw=clamp((face.yaw - self._yaw0) * 1.15, -1.0, 1.0), pitch=clamp((face.pitch - self._pitch0) * 1.2, -0.6, 0.6),
                roll=clamp(face.roll * 1.05, -0.7, 0.7), jaw=face.jaw, smile=face.smile, brow=face.brow,
                blink=face.blink, gaze=face.gaze, lean=clamp((face.width - 0.22) / 0.22, -0.3, 1.0),
                sway=pose.sway if body is not None else clamp((face.center[0] / self.aspect - 0.5) * 2.2, -1.0, 1.0))
        return pose


__all__ = ["BodyInfo", "FaceInfo", "HandInfo", "Retargeter", "body_info", "face_info", "hand_info"]
