"""Hand roles and arm-cross geometry for the drawing mode."""
from __future__ import annotations

import math

from .contracts import FingerName, FingerState, FrameFeatures, Handedness, Quality
from .drawing import InkScene

HOLD_MS = 450
MAX_GAP_MS = 180
CROSS_GRACE_MS = 120   # the pose model may miss single frames of a held X


def crossed_forearms(points, aspect: float) -> bool:
    """Interior intersection of two visible, upward forearms near the shoulders."""
    if len(points) < 17:
        return False
    joints = points[11:17]
    if any((p.visibility or 0) < 0.55 or (p.presence or 0) < 0.55 for p in joints):
        return False
    sl, sr, a, b, aw, bw = [(p.x * aspect, p.y) for p in joints]
    u = aw[0] - a[0], aw[1] - a[1]
    v = bw[0] - b[0], bw[1] - b[1]
    det = u[0]*v[1] - u[1]*v[0]
    if min(-u[1], -v[1]) < 0.025 or abs(det) < max(0.001, 0.35*math.hypot(*u)*math.hypot(*v)):
        return False
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = (dx*v[1] - dy*v[0]) / det
    s = (dx*u[1] - dy*u[0]) / det
    span = math.dist(sl, sr)
    chest_x, shoulder_y = (sl[0]+sr[0])/2, (sl[1]+sr[1])/2
    return (0.08 < t < 0.92 and 0.08 < s < 0.92 and
            abs(a[0] + t*u[0] - chest_x) < 0.65*span and
            -0.4*span < a[1] + t*u[1] - shoulder_y < 1.35*span)


def finger_pose(hand):
    states = {f.name: f.state for f in hand.fingers}
    return tuple(states.get(name) for name in (FingerName.INDEX, FingerName.MIDDLE,
                                               FingerName.RING, FingerName.LITTLE))


class DrawingControls:
    def __init__(self):
        self.scene = InkScene()
        self.reset()

    def reset(self):
        self.scene.lift()
        self.cursor = None
        self.tool = "carry"
        self.spinning = False
        self.cross_since = None
        self.cross_seen = None
        self.last_time = None
        self.right_id = None

    def update(self, frame: FrameFeatures):
        now = frame.capture_ms
        if self.last_time is not None and now <= self.last_time:
            return
        if self.last_time is not None and now - self.last_time > MAX_GAP_MS:
            self.reset()
        dt = 0 if self.last_time is None else now - self.last_time
        self.last_time = now
        self.scene.advance(now)
        old_cursor, old_tool = self.cursor, self.tool
        self.cursor, self.tool, self.spinning = None, "carry", False
        if getattr(frame, "forearms_crossed", False):
            self.scene.lift()
            self.cross_seen = now
            if self.cross_since is None:
                self.cross_since = now
            elif now - self.cross_since >= HOLD_MS:
                self.scene.clear(now)
            return
        if self.cross_since is not None and now - self.cross_seen <= CROSS_GRACE_MS:
            self.scene.lift()
            return
        self.cross_since = None
        if self.scene.clear_start is not None or frame.identity_ambiguous or min(frame.width, frame.height) <= 0:
            self.scene.lift()
            return
        hands = [h for h in frame.hands if h.quality is Quality.USABLE]
        left = [h for h in hands if h.handedness is Handedness.LEFT]
        extended, bent = FingerState.EXTENDED, FingerState.BENT
        if len(left) == 1 and finger_pose(left[0]) == (extended,)*4:
            self.spinning = True
            self.scene.angle = (self.scene.angle + dt * math.tau / 4200) % math.tau
        right = [h for h in hands if h.handedness is Handedness.RIGHT]
        if len(right) != 1:
            self.scene.lift()
            self.right_id = None
            return
        h = right[0]
        pose = finger_pose(h)
        erasing = pose == (bent,)*4
        px, py = h.palm_center_px if erasing else h.index_tip_px
        self.cursor = (px / frame.width - 0.5, (py - frame.height/2) / frame.width)
        discontinuity = (old_cursor is None or h.hand_id != self.right_id or
                         math.dist(old_cursor, self.cursor) > 0.16)
        self.right_id = h.hand_id
        if discontinuity:
            self.scene.lift()
        if pose == (extended, bent, bent, bent):
            self.tool = "brush"
            self.scene.paint(*self.cursor, now)
        elif erasing:
            self.tool = "erase"
            previous = old_cursor if old_tool == "erase" and not discontinuity else None
            self.scene.erase(*self.cursor, previous)
        else:
            self.scene.lift()
