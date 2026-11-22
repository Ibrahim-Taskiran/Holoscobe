"""Landmark-level hands for gesture tests: 21 points -> real FeatureExtractor -> GestureRecognizer.

Generator copied from tests/integration/integ_synth.py (no cross-folder imports). Local hand frame
(palm units, right hand): wrist at origin, fingers point to -y (image up), thumb side is +x.
"""
from __future__ import annotations

import math
from typing import Callable, Mapping, Optional, Sequence, Union

from handcontrol.contracts import FrameFeatures, FrameSample, GestureEvent, GestureKind, HandSample, Handedness, Landmark
from handcontrol.features import FeatureExtractor
from handcontrol.gestures import GestureConfig, GestureRecognizer

FINGER_NAMES = ("thumb", "index", "middle", "ring", "little")
_FINGERS = (
    ((0.30, -0.92), (0.38, 0.24, 0.20)),
    ((0.08, -1.00), (0.42, 0.27, 0.21)),
    ((-0.13, -0.95), (0.39, 0.25, 0.20)),
    ((-0.32, -0.84), (0.30, 0.19, 0.18)),
)
_FLEX = (75.0, 100.0, 65.0)
W, H = 640, 480
SCALE = 100.0                     # features palm_scale_px ~100 px
PU = 100.0                        # px per palm unit for placement

# poses (curl per finger); FeatureExtractor reads them as noted (T I M R L)
OPEN = {n: 0.0 for n in FINGER_NAMES}                                             # E E E E E
PICK = {"thumb": 1.0, "index": 0.0, "middle": 1.0, "ring": 1.0, "little": 1.0}     # B E B B B
STRING = {"thumb": 0.0, "index": 0.0, "middle": 1.0, "ring": 1.0, "little": 1.0}   # E E B B B
FOUR = {"thumb": 1.0, "index": 0.0, "middle": 0.0, "ring": 0.0, "little": 0.0}     # B E E E E
LOOSE = {"thumb": 1.0, "index": 0.0, "middle": 0.0, "ring": 0.0, "little": 1.0}    # B E E E B (3 non-thumb)

CLAP_KINDS = {GestureKind.CLAP, GestureKind.CLAP_CANDIDATE_START, GestureKind.CLAP_CANDIDATE_ABORT}


def _local(curls: Mapping[str, float]) -> list[tuple[float, float, float]]:
    c = {n: 0.0 for n in FINGER_NAMES}
    c.update(curls)
    pts = [(0.0, 0.0, 0.0)] * 21
    ct = c["thumb"]
    cur = (0.20, -0.15, 0.0)
    pts[1] = cur
    phi = 55.0 - 45.0 * ct
    phis = (phi, phi - 50.0 * ct, phi - 110.0 * ct)
    tilts = (0.0, 15.0 * ct, 30.0 * ct)
    for k, length in enumerate((0.30, 0.25, 0.22)):
        p, t = math.radians(phis[k]), math.radians(tilts[k])
        d = (math.sin(p) * math.cos(t), -math.cos(p) * math.cos(t), -math.sin(t))
        cur = (cur[0] + length * d[0], cur[1] + length * d[1], cur[2] + length * d[2])
        pts[2 + k] = cur
    for i, ((mx, my), bones) in enumerate(_FINGERS):
        cf = c[FINGER_NAMES[i + 1]]
        start = 5 + 4 * i
        cur = (mx, my, 0.0)
        pts[start] = cur
        n = math.hypot(mx * 0.4, 1.0)
        dx, dy = mx * 0.4 / n, -1.0 / n
        acc = 0.0
        for k, length in enumerate(bones):
            acc += math.radians(_FLEX[k] * cf)
            d = (dx * math.cos(acc), dy * math.cos(acc), -math.sin(acc))
            cur = (cur[0] + length * d[0], cur[1] + length * d[1], cur[2] + length * d[2])
            pts[start + 1 + k] = cur
    return pts


def hand(pose: Mapping[str, float], center: tuple[float, float], *, side: str = "right",
         label: Optional[Handedness] = None, score: float = 0.95) -> HandSample:
    mirror = -1.0 if side == "left" else 1.0
    pts = [(x * mirror, y, z) for x, y, z in _local(pose)]
    pcx = sum(pts[i][0] for i in (5, 9, 13, 17)) / 4.0
    pcy = sum(pts[i][1] for i in (5, 9, 13, 17)) / 4.0
    lms = tuple(Landmark((center[0] + (x - pcx) * SCALE) / W, (center[1] + (y - pcy) * SCALE) / H,
                         (z * SCALE) / W) for x, y, z in pts)
    if label is None:
        label = Handedness.LEFT if side == "left" else Handedness.RIGHT
    return HandSample(label, score, lms)


def lerp(a: float, b: float, u: float) -> float:
    return a + (b - a) * u


# unmirrored image: the user's right (pick) hand appears on the image left
ND = (470.0, 300.0)              # left (string, non-dominant) hand


def right_at(d_pu: float, pose: Mapping[str, float], y: float = 300.0) -> HandSample:
    """Right hand d_pu palm units to the image left of the string hand."""
    return hand(pose, (ND[0] - d_pu * PU, y), side="right")


def left(pose: Mapping[str, float], center: tuple[float, float] = ND) -> HandSample:
    return hand(pose, center, side="left")


HandsFn = Union[Sequence[HandSample], Callable[[float], Sequence[HandSample]]]


class Chain:
    """FrameSample -> FeatureExtractor -> GestureRecognizer at a fixed frame rate (capture_ms timeline)."""

    def __init__(self, instrument: bool = True, fps: float = 30.0, t0: float = 10_000.0,
                 config: GestureConfig = GestureConfig()) -> None:
        self.fx = FeatureExtractor()
        self.gr = GestureRecognizer(config, Handedness.RIGHT)
        self.gr.set_instrument_profile(instrument)
        self.t = t0
        self.dt = 1000.0 / fps
        self.events: list[GestureEvent] = []
        self.ambiguous_frames = 0
        self.min_pair_pu = math.inf

    def frame(self, hands: Sequence[HandSample]) -> FrameFeatures:
        ff = self.fx.update(FrameSample(self.t, self.t + 20.0, W, H, tuple(hands)))
        self.events += self.gr.update(ff)
        if ff.identity_ambiguous:
            self.ambiguous_frames += 1
        if len(ff.hands) == 2 and all(h.palm_scale_px > 0 for h in ff.hands):
            a, b = ff.hands
            d = math.dist(a.palm_center_px, b.palm_center_px) / ((a.palm_scale_px + b.palm_scale_px) / 2.0)
            self.min_pair_pu = min(self.min_pair_pu, d)
        self.t += self.dt
        return ff

    def run(self, ms: float, hands: HandsFn) -> "Chain":
        t0, end = self.t, self.t + ms
        while self.t < end:
            u = min(1.0, (self.t - t0) / ms) if ms > 0 else 1.0
            self.frame(hands(u) if callable(hands) else hands)
        return self

    def kinds(self) -> set[GestureKind]:
        return {e.kind for e in self.events}

    def count(self, kind: GestureKind) -> int:
        return sum(e.kind is kind for e in self.events)


def strum(ch: Chain, ms: float, *, period_ms: float = 260.0, near_pu: float = 0.5, far_pu: float = 2.6,
          pick: Mapping[str, float] = PICK, string: Mapping[str, float] = STRING) -> Chain:
    """Pick hand sweeps fast across the string hand again and again (x in/out + y sweep)."""
    def frame(u: float) -> list[HandSample]:
        ph = (u * ms / period_ms) * 2.0 * math.pi
        d = lerp(far_pu, near_pu, 0.5 - 0.5 * math.cos(ph))
        y = 300.0 + 60.0 * math.sin(ph)
        return [right_at(d, pick, y), left(string)]
    return ch.run(ms, frame)


def clap_path(ch: Chain, pose_r: Mapping[str, float] = OPEN, pose_l: Mapping[str, float] = OPEN, *,
              far: float = 3.0, near: float = 0.45, approach_ms: float = 240.0, merge_frames: int = 2,
              hold_ms: float = 250.0) -> Chain:
    """Separated hold, fast approach, merged contact frames, separation, separated hold."""
    ch.run(hold_ms, [right_at(far, pose_r), left(pose_l)])
    ch.run(approach_ms, lambda u: [right_at(lerp(far, near, u), pose_r), left(pose_l)])
    for _ in range(merge_frames):
        ch.frame([hand(pose_r, (ND[0] - near * PU / 2.0, 300.0), side="right", score=0.6)])
    ch.run(approach_ms, lambda u: [right_at(lerp(near, far, u), pose_r), left(pose_l)])
    ch.run(hold_ms, [right_at(far, pose_r), left(pose_l)])
    return ch
