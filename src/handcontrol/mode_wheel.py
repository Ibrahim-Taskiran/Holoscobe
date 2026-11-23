"""Radial menus aimed with one hand. The mode wheel: V pose aims, fist picks, open palm or a fist in the middle
cancels. Qt-free."""
from __future__ import annotations

import math
from typing import Optional

from .contracts import FingerName, FingerState, HandFeatures, Mode

MORE, BACK, CANCEL = "more", "back", "cancel"
MAIN_PAGE = (Mode.POINTER.value, Mode.SCROLL.value, Mode.DRAWING.value, Mode.INSTRUMENT.value,
             Mode.COMMANDS.value, MORE)
MORE_PAGE = (Mode.ZOOM.value, Mode.VOLUME.value, Mode.WINDOWS.value, BACK)

AIM_ON, AIM_OFF, AIM_FULL = 0.45, 0.30, 1.3      # distance from the opening point, palm units
STICKY = math.radians(8)                         # the aimed slice reaches this far into its neighbours
FIST_MS, OPEN_MS, LOST_MS = 80.0, 150.0, 800.0
STRAIGHT_CURL = 0.42                             # raw curl: a closing hand must not move the aim


def _states(hand: HandFeatures):
    by_name = {f.name: f for f in hand.fingers}
    return [by_name.get(n) for n in (FingerName.INDEX, FingerName.MIDDLE, FingerName.RING, FingerName.LITTLE)]


def is_v(hand: HandFeatures) -> bool:
    """Index and middle EXTENDED, ring and little BENT (thumb ignored)."""
    f = _states(hand)
    if None in f:
        return False
    return (all(i.state is FingerState.EXTENDED for i in f[:2])
            and all(i.state is FingerState.BENT for i in f[2:]))


def is_fist(hand: HandFeatures) -> bool:
    f = _states(hand)
    if None in f:
        return False
    bent = sum(i.state is FingerState.BENT for i in f)
    return bent >= 3 and all(i.state is FingerState.BENT or (i.state is FingerState.UNKNOWN and i.curl >= 0.5)
                             for i in f)


def is_open(hand: HandFeatures) -> bool:
    f = _states(hand)
    return None not in f and all(i.state is FingerState.EXTENDED for i in f)


class RadialAim:
    """Slice i of `n` is centred i/n of a turn clockwise from the top, around the point where aiming began."""

    def __init__(self, n: int, mirror: bool = False):
        self._sign = -1.0 if mirror else 1.0
        self.restart(n)

    def restart(self, n: int):
        self.n = n
        self.hovered: Optional[int] = None
        self.pointer = (0.5, 0.5)                # 0..1 square around the wheel
        self.anchor: Optional[tuple[float, float]] = None
        self._scale = 1.0

    def aim(self, hand: HandFeatures):
        if self.anchor is None:
            self.anchor, self._scale = hand.palm_center_px, max(1.0, hand.palm_scale_px)
        dx = self._sign * (hand.palm_center_px[0] - self.anchor[0]) / self._scale
        dy = (hand.palm_center_px[1] - self.anchor[1]) / self._scale
        r = math.hypot(dx, dy)
        k = min(1.0, AIM_FULL / r) / AIM_FULL / 2 if r else 0.0
        self.pointer = (0.5 + dx*k, 0.5 + dy*k)
        if r < (AIM_ON if self.hovered is None else AIM_OFF):
            self.hovered = None
            return
        angle, step = math.atan2(dx, -dy), math.tau / self.n
        if self.hovered is not None:
            off = math.remainder(angle - self.hovered*step, math.tau)
            if abs(off) < step/2 + STICKY:
                return
        self.hovered = round(angle / step) % self.n


class ModeWheel(RadialAim):
    """update() returns a mode value to switch to, CANCEL, or None. Slices run clockwise from the top."""

    def __init__(self, hand: HandFeatures, now: float, mirror: bool):
        self.side = hand.handedness
        self.hand_id = hand.hand_id
        super().__init__(len(MAIN_PAGE), mirror)
        self.seen_ms = now
        self._show(MAIN_PAGE)
        self.aim(hand)

    def _show(self, keys):
        self.keys = keys
        self.restart(len(keys))
        self._pose, self._pose_since = "", 0.0

    def pick_hand(self, hands) -> Optional[HandFeatures]:
        same = [h for h in hands if h.handedness is self.side]
        return same[0] if len(same) == 1 else None

    def update(self, hand: Optional[HandFeatures], now: float) -> Optional[str]:
        if hand is None:
            self._pose = ""
            return None
        self.seen_ms = now
        pose = "v" if is_v(hand) else "fist" if is_fist(hand) else "open" if is_open(hand) else ""
        if pose != self._pose:
            self._pose, self._pose_since = pose, now
        held = now - self._pose_since
        if pose == "v":
            if all(f.curl <= STRAIGHT_CURL for f in _states(hand)[:2]):
                self.aim(hand)
        elif self.anchor is None:
            return None                          # page just opened: the picking fist must open to a V first
        elif pose == "fist" and held >= FIST_MS:
            key = CANCEL if self.hovered is None else self.keys[self.hovered]
            if key in (MORE, BACK):
                self._show(MORE_PAGE if key == MORE else MAIN_PAGE)
                return None
            return key
        elif pose == "open" and held >= OPEN_MS:
            return CANCEL
        return None
