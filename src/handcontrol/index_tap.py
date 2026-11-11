"""Palm-relative index depth pulse detection; no camera, GUI or OS imports."""
from __future__ import annotations

import math
from handcontrol.contracts import FingerName, FingerState, HandFeatures, Handedness, Quality


class IndexTapRecognizer:
    """Require a stable pointing pose, a forward stroke, then return within 450 ms.

    Depth is relative to the palm, in palm units, not a metric 3D measurement.
    The rest of the hand stays still; moving the whole hand cannot make a tap.
    """
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.hand_id = None
        self.baseline = None
        self.since = self.last = self.departed = None
        self.peak = 0.0
        self.latched = None
        self.cooldown_until = 0.0

    def update(self, hand: HandFeatures, t_ms: float, width: int,
               pointer: tuple[int, int]) -> tuple[bool, tuple[int, int] | None]:
        states = {f.name: f.state for f in hand.fingers}
        pose = (hand.handedness is Handedness.RIGHT and hand.quality is Quality.USABLE
                and states.get(FingerName.INDEX) is FingerState.EXTENDED
                and all(states.get(f) is FingerState.BENT for f in FingerName if f is not FingerName.INDEX))
        if not pose or len(hand.landmarks) != 21 or hand.palm_scale_px <= 0 or width <= 0:
            self.reset()
            return False, None
        depth = (hand.landmarks[8].z - sum(hand.landmarks[i].z for i in (5, 9, 13, 17)) / 4) * width / hand.palm_scale_px
        if not math.isfinite(depth) or not math.isfinite(t_ms):
            self.reset()
            return False, None
        palm = hand.palm_center_px
        if self.hand_id != hand.hand_id or self.last is None or not 0 < t_ms - self.last <= 150:
            self.reset()
            self.hand_id = hand.hand_id
        self.last = t_ms
        if t_ms < self.cooldown_until:
            return False, None
        if self.baseline is None:
            self.baseline = (depth, palm)
            self.since = t_ms
            return False, None
        base_depth, base_palm = self.baseline
        if math.dist(palm, base_palm) / hand.palm_scale_px > 0.25:
            self.baseline, self.since, self.departed = (depth, palm), t_ms, None
            self.peak = 0.0
            return False, None
        delta = base_depth - depth
        if self.departed is None:
            if t_ms - self.since < 200:
                if abs(delta) > 0.08:
                    self.baseline, self.since = (depth, palm), t_ms
                return False, None
            if delta < 0.12:
                return False, None
            self.departed, self.latched = t_ms, pointer
        self.peak = max(self.peak, delta)
        duration = t_ms - self.departed
        if duration > 450 or delta < -0.2:
            self.baseline, self.since, self.departed = None, None, None
            self.peak = 0.0
            return True, None
        if delta <= 0.08:
            click = self.latched if self.peak >= 0.30 and duration >= 40 else None
            self.baseline, self.since, self.departed = None, None, None
            self.peak = 0.0
            self.cooldown_until = t_ms + 450 if click else t_ms
            return True, click
        return True, None
