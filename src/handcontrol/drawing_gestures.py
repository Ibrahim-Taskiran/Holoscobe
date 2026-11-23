"""Hand roles and arm-cross geometry for the drawing mode."""
from __future__ import annotations

import math
from typing import Optional

from .contracts import FingerName, FingerState, FrameFeatures, Handedness, Quality
from .drawing import InkScene

HOLD_MS = 420            # X evidence needed to clear
CROSS_BLOCK_MS = 90      # this much evidence stops the pen and the spin
CROSS_DECAY = 0.6        # evidence lost per ms without X: single missed pose frames do not matter
MAX_GAP_MS = 180
# Recorded hands (4 sessions): false point/fist runs last up to 90 ms, real ones are broken by 50-150 ms gaps.
CONFIRM_MS = 100
TOOL_GAP_MS = 160
SPIN_GAP_MS = 220
BENT_CURL, STRAIGHT_CURL = 0.40, 0.42    # raw curls: react before the 80 ms state dwell of features.py
TILT_ON, TILT_OFF, TILT_FULL = (math.radians(a) for a in (16, 10, 42))
SPIN_SLOW, SPIN_FAST = math.tau/9000, math.tau/2800
MAX_STEP = 0.16


def _arm_segments_cross(sl, sr, a, b, aw, bw) -> bool:
    u = aw[0] - a[0], aw[1] - a[1]
    v = bw[0] - b[0], bw[1] - b[1]
    det = u[0]*v[1] - u[1]*v[0]
    if min(-u[1], -v[1]) < 0.0 or abs(det) < max(0.001, 0.3*math.hypot(*u)*math.hypot(*v)):
        return False
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = (dx*v[1] - dy*v[0]) / det
    s = (dx*u[1] - dy*u[0]) / det
    span = math.dist(sl, sr)
    return (0.08 < t < 1.05 and 0.08 < s < 1.05 and
            abs(a[0] + t*u[0] - (sl[0]+sr[0])/2) < 0.75*span and
            -0.8*span < a[1] + t*u[1] - (sl[1]+sr[1])/2 < 1.35*span)


def _wrists_swapped(sl, sr, aw, bw) -> bool:
    """Each wrist on the other side in front of the chest. Works when a laptop camera cuts the elbows off."""
    span = abs(sl[0] - sr[0])
    if span < 0.1:
        return False
    side = math.copysign(1, sl[0] - sr[0])
    cx, cy = (sl[0]+sr[0])/2, (sl[1]+sr[1])/2
    return (0.12*span < (bw[0] - aw[0])*side < 1.3*span and
            abs((aw[0]+bw[0])/2 - cx) < 0.5*span and abs(aw[1] - bw[1]) < 0.6*span and
            all(-0.9*span < w[1] - cy < 0.75*span for w in (aw, bw)))


def crossed_forearms(points, aspect: float) -> bool:
    """X in front of the chest: crossing forearms, or swapped wrists when the elbows are not visible."""
    if len(points) < 17:
        return False
    joints = points[11:17]

    def seen(p, level):
        return (p.visibility or 0) >= level and (p.presence or 0) >= level
    if not all(seen(p, 0.45) for p in (*joints[:2], *joints[4:])):
        return False
    xy = [(p.x * aspect, p.y) for p in joints]
    if all(seen(p, 0.45) for p in joints[2:4]) and _arm_segments_cross(*xy):
        return True
    return _wrists_swapped(xy[0], xy[1], xy[4], xy[5])


def hand_pose(hand) -> Optional[str]:
    """"brush" (only the index), "erase" (fist), "open" (four fingers) or None (between poses)."""
    f = {i.name: i for i in hand.fingers}
    index, *rest = [f.get(n) for n in (FingerName.INDEX, FingerName.MIDDLE, FingerName.RING, FingerName.LITTLE)]
    if index is None or None in rest:
        return None
    bent = [i.state is not FingerState.EXTENDED and i.curl >= BENT_CURL for i in (index, *rest)]
    straight = [i.state is not FingerState.BENT and i.curl <= STRAIGHT_CURL for i in (index, *rest)]
    known = sum(i.state is not FingerState.UNKNOWN for i in (index, *rest))
    if known < 3:
        return None
    if straight[0] and index.state is FingerState.EXTENDED and all(bent[1:]):
        return "brush"
    if all(bent):
        return "erase"
    return "open" if all(straight) else None


def _tilt(hand, frame) -> float:
    """Roll of the hand in the image: 0 upright, positive towards +x."""
    if len(hand.landmarks) < 10:
        return 0.0
    wrist, knuckle = hand.landmarks[0], hand.landmarks[9]
    return math.atan2((knuckle.x - wrist.x)*frame.width, (wrist.y - knuckle.y)*frame.height)


class DrawingControls:
    def __init__(self):
        self.scene = InkScene()
        self.reset()

    def reset(self):
        self.cross = 0.0                # ms of X evidence
        self.last_time = None
        self.cursor = None
        self._stop_spin()
        self.pen_up()

    @property
    def blocked(self) -> bool:
        return self.cross >= CROSS_BLOCK_MS

    @property
    def spin(self) -> float:
        return self.scene.spin_target

    def pen_up(self):
        self.scene.lift()
        self.tool = "carry"
        self._tool_seen = 0.0
        self._candidate = None
        self._candidate_since = 0.0
        self._point = None
        self._right_id = None

    def _stop_spin(self):
        self.scene.spin_target = 0.0
        self.spin_ready = False
        self._spin_seen = None

    def update(self, frame: FrameFeatures, hands_ok: bool = True):
        now = frame.capture_ms
        if self.last_time is not None and now <= self.last_time:
            return
        if self.last_time is not None and now - self.last_time > MAX_GAP_MS:
            self.reset()
        dt = 0 if self.last_time is None else now - self.last_time
        self.last_time = now
        self.scene.advance(now)
        self.cursor = None
        crossed = bool(getattr(frame, "forearms_crossed", False))
        self.cross = min(HOLD_MS, self.cross + dt) if crossed else max(0.0, self.cross - CROSS_DECAY*dt)
        if crossed and self.cross >= HOLD_MS:
            self.scene.clear(now)
        if (crossed or self.blocked or not hands_ok or self.scene.clear_start is not None
                or min(frame.width, frame.height) <= 0):
            self.pen_up()
            self._stop_spin()
            return
        hands = () if frame.identity_ambiguous else frame.hands
        self._left(frame, [h for h in hands if h.handedness is Handedness.LEFT and h.quality is Quality.USABLE], now)
        self._right(frame, [h for h in hands if h.handedness is Handedness.RIGHT], now)

    # ---------------- left hand: tilt to spin

    def _left(self, frame, hands, now):
        pose = hand_pose(hands[0]) if len(hands) == 1 else None
        if pose is None:
            if self._spin_seen is not None and now - self._spin_seen > SPIN_GAP_MS:
                self._stop_spin()
            return
        if pose != "open":
            self._stop_spin()
            return
        self._spin_seen, self.spin_ready = now, True
        tilt = _tilt(hands[0], frame)
        if abs(tilt) < (TILT_OFF if self.spin * tilt > 0 else TILT_ON):
            self.scene.spin_target = 0.0
            return
        # Positive angles carry the front surface towards +x, the side the palm leans to.
        amount = min(1.0, max(0.0, (abs(tilt) - TILT_OFF) / (TILT_FULL - TILT_OFF)))
        self.scene.spin_target = math.copysign(SPIN_SLOW + (SPIN_FAST - SPIN_SLOW)*amount, tilt)

    # ---------------- right hand: brush, eraser, carry

    def _right(self, frame, hands, now):
        if len(hands) != 1 or hands[0].quality is Quality.UNKNOWN:
            self._gap(now)
            return
        h = hands[0]
        pose = hand_pose(h)
        fist = "erase" in (pose, self.tool)
        px, py = h.palm_center_px if fist else h.index_tip_px
        self.cursor = (px / frame.width - 0.5, (py - frame.height/2) / frame.width)
        if self._right_id not in (None, h.hand_id):
            self.pen_up()
        self._right_id = h.hand_id
        if pose is None or (h.quality is not Quality.USABLE and pose != self.tool):
            self._gap(now)
        elif pose == "open":
            self.pen_up()
        elif pose == self.tool:
            self._apply(now)
        else:
            if self.tool != "carry":
                self.pen_up()
            if self._candidate != pose:
                self._candidate, self._candidate_since = pose, now
            if now - self._candidate_since >= CONFIRM_MS:
                self.tool, self._candidate = pose, None
                self._apply(now)

    def _gap(self, now):
        """Between poses or briefly lost: leave no mark, but keep the tool for a moment."""
        self._candidate = None
        if self.tool != "carry" and now - self._tool_seen > TOOL_GAP_MS:
            self.pen_up()

    def _apply(self, now):
        self._tool_seen = now
        near = self._point is not None and math.dist(self._point, self.cursor) <= MAX_STEP
        if self.tool == "brush":
            if not near:
                self.scene.lift()
            self.scene.paint(*self.cursor, now)
        else:
            self.scene.erase(*self.cursor, self._point if near else None)
        self._point = self.cursor
