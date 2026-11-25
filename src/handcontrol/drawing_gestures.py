"""Hand roles and arm-cross geometry for the drawing mode."""
from __future__ import annotations

import math
from typing import Optional

from .contracts import FingerName, FingerState, FrameFeatures, Handedness, HandSample, Quality
from .drawing import PALETTE, InkScene
from .mode_wheel import RadialAim

HOLD_MS = 480            # X evidence needed to clear
CROSS_BLOCK_MS = 90      # this much evidence stops the pen and the spin
CROSS_DECAY = 0.25       # evidence lost per ms without X: the pose model misses many frames of crossed arms
MAX_GAP_MS = 180
# Recorded hands (4 sessions): false point/fist runs last up to 90 ms, real ones are broken by 50-150 ms gaps.
CONFIRM_MS = 100
TOOL_GAP_MS = 160
SPIN_GAP_MS = 220
BENT_CURL, STRAIGHT_CURL = 0.40, 0.42    # raw curls: react before the 80 ms state dwell of features.py
TILT_ON, TILT_OFF, TILT_FULL = (math.radians(a) for a in (16, 10, 42))
SPIN_SLOW, SPIN_FAST = math.tau/9000, math.tau/2800
MAX_STEP = 0.16
PINCH_ON, PINCH_OFF = 0.33, 0.48          # thumb-index distance, palm units (as in gestures.py)
PALETTE_HOLD_MS, PALETTE_PICK_MS, PALETTE_LOST_MS = 180, 60, 350


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


def _hands_swapped(sl, sr, a, b, elbows) -> bool:
    """Each hand on the other side in front of the chest. Works when a laptop camera cuts the elbows off."""
    span = abs(sl[0] - sr[0])
    if span < 0.1:
        return False
    side = math.copysign(1, sl[0] - sr[0])
    cx, cy = (sl[0]+sr[0])/2, (sl[1]+sr[1])/2
    return (0.16*span < (b[0] - a[0])*side < 1.4*span and
            abs((a[0]+b[0])/2 - cx) < 0.6*span and abs(a[1] - b[1]) < 0.7*span and
            all(-1.2*span < h[1] - cy < 0.4*span for h in (a, b)) and
            all(e[1] - h[1] > 0.25*span for h, e in zip((a, b), elbows) if e))       # forearms up, not folded


def _seen(p, level) -> bool:
    return (p.visibility or 0) >= level and (p.presence or 0) >= level


def crossed_forearms(points, aspect: float) -> bool:
    """X in front of the chest: crossing forearms, or swapped hands when the elbows are not visible.
    Crossed arms hide each other, so wrists and elbows count from a low visibility on."""
    if len(points) < 17:
        return False
    joints = points[11:17]
    if not all(_seen(p, 0.45) for p in joints[:2]) or not all(_seen(p, 0.3) for p in joints[4:]):
        return False
    xy = [(p.x * aspect, p.y) for p in joints]
    if all(_seen(p, 0.3) for p in joints[2:4]) and _arm_segments_cross(*xy):
        return True

    def hand(wrist, *tips):
        """Middle of wrist and knuckles: further out than the wrist, so also swapped when the wrists touch."""
        seen = [points[wrist], *(points[i] for i in tips if i < len(points) and _seen(points[i], 0.3))]
        return sum(p.x for p in seen) * aspect / len(seen), sum(p.y for p in seen) / len(seen)
    elbows = [p if _seen(j, 0.3) else None for p, j in zip(xy[2:4], joints[2:4])]
    return _hands_swapped(xy[0], xy[1], hand(15, 17, 19), hand(16, 18, 20), elbows)


def arms_apart(points, aspect: float) -> bool:
    """Both wrists clearly seen on their own sides: no X, whatever the hand model says."""
    if len(points) < 17 or not all(_seen(points[i], 0.6) for i in (11, 12, 15, 16)):
        return False
    shoulders = points[11].x - points[12].x
    return abs(shoulders) * aspect >= 0.1 and (points[15].x - points[16].x) / shoulders > 0.35


def crossed_hands(hands: tuple[HandSample, ...], aspect: float) -> bool:
    """X seen by the hand model alone: right hand on the left hand's side, close together, both leaning
    outwards, so that the forearms below them cross. A drawing (pointing) hand never counts."""
    by = {h.handedness: h for h in hands}
    if len(hands) != 2 or set(by) != {Handedness.LEFT, Handedness.RIGHT}:
        return False
    points = [[(p.x * aspect, p.y) for p in by[side].landmarks] for side in (Handedness.RIGHT, Handedness.LEFT)]
    size = sum(math.dist(p[0], p[9]) for p in points) / 2
    if size <= 0 or any(math.dist(p[8], p[0]) > 1.25 * math.dist(p[12], p[0]) for p in points):
        return False
    right, left = points
    lean = [math.degrees(math.atan2(p[9][0] - p[0][0], p[0][1] - p[9][1])) for p in points]
    return (15 < lean[0] < 85 and -85 < lean[1] < -15 and
            0.8 * size < right[9][0] - left[9][0] < 4.5 * size and right[0][0] - left[0][0] > 0.0 and
            abs(right[9][1] - left[9][1]) < 1.6 * size)


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


def ok_pinch(hand) -> bool:
    """Thumb and index together while at least two other fingers stay straight (a fist never matches)."""
    rest = (FingerName.MIDDLE, FingerName.RING, FingerName.LITTLE)
    return (hand.pinch_distance <= PINCH_ON and
            sum(f.name in rest and f.state is FingerState.EXTENDED for f in hand.fingers) >= 2)


def _tilt(hand, frame) -> float:
    """Roll of the hand in the image: 0 upright, positive towards +x."""
    if len(hand.landmarks) < 10:
        return 0.0
    wrist, knuckle = hand.landmarks[0], hand.landmarks[9]
    return math.atan2((knuckle.x - wrist.x)*frame.width, (wrist.y - knuckle.y)*frame.height)


class DrawingControls:
    def __init__(self):
        self.scene = InkScene()
        self.frame_size = (4, 3)
        self.reset()

    def reset(self):
        self.cross = 0.0                # ms of X evidence
        self.last_time = None
        self.cursor = None
        self._stop_spin()
        self._close_palette()
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

    def _close_palette(self):
        self.palette: Optional[RadialAim] = None
        self._pinch_since = self._release_since = None
        self._palette_seen = 0.0

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
        self.frame_size = frame.width, frame.height
        self.cursor = None
        # a drawing hand may reach across the other arm: that is no X
        crossed = bool(getattr(frame, "forearms_crossed", False)) and not any(
            h.handedness is Handedness.RIGHT and h.quality is Quality.USABLE and hand_pose(h) == "brush"
            for h in frame.hands)
        self.cross = min(HOLD_MS, self.cross + dt) if crossed else max(0.0, self.cross - CROSS_DECAY*dt)
        if crossed and self.cross >= HOLD_MS:
            self.scene.clear(now)
        if (crossed or self.blocked or not hands_ok or self.scene.clear_start is not None
                or min(frame.width, frame.height) <= 0):
            self.pen_up()
            self._stop_spin()
            self._close_palette()
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
            self._pinch_since = None
            self._gap(now)
            return
        h = hands[0]
        if self._palette_step(h, now):
            return
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

    def _palette_step(self, h, now) -> bool:
        """Hold an OK pinch: the color wheel opens around the hand. Move to a slice and let go to pick it."""
        if self.palette is None:
            if h.quality is not Quality.USABLE or not ok_pinch(h):
                self._pinch_since = None
                return False
            if self._pinch_since is None:
                self._pinch_since = now
            if now - self._pinch_since < PALETTE_HOLD_MS:
                return False
            self.pen_up()
            self.palette = RadialAim(len(PALETTE))
        self._palette_seen = now
        if h.pinch_distance <= PINCH_OFF:
            self._release_since = None
            if h.quality is Quality.USABLE:
                self.palette.aim(h)
            return True
        if self._release_since is None:
            self._release_since = now
        if now - self._release_since >= PALETTE_PICK_MS:
            if self.palette.hovered is not None:
                self.scene.color = self.palette.hovered
            self._close_palette()
        return True

    def _gap(self, now):
        """Between poses or briefly lost: leave no mark, but keep the tool for a moment."""
        self._candidate = None
        if self.palette is not None and now - self._palette_seen > PALETTE_LOST_MS:
            self._close_palette()                   # a lost hand never picks
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
