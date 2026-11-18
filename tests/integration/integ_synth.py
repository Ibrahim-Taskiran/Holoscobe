"""RAW landmark timelines for integration tests: FrameSample -> real features -> gestures ->
controller -> DryRunSink. Proves logic only, never real-camera behavior.

The hand generator is copied from tests/features/feat_synth.py (no cross-folder imports).
Local hand frame (palm units, right hand): wrist at origin, fingers point to -y (image up),
thumb side is +x, palm faces the camera (-z).
"""
from __future__ import annotations

import math
import random
from typing import Callable, Mapping, Optional, Sequence, Union

from handcontrol.config import Settings
from handcontrol.contracts import (
    ActionKind,
    CameraState,
    ControlState,
    FrameSample,
    HandSample,
    Handedness,
    Landmark,
    Mode,
    Rect,
    WindowTarget,
)
from handcontrol.dryrun import DryRunSink, FakeClock, FakeDisplays, FakeVolume, FakeWindows, make_monitor
from handcontrol.pipeline import Pipeline

FINGER_NAMES = ("thumb", "index", "middle", "ring", "little")
_FINGERS = (                        # index, middle, ring, little: (MCP xy, bone lengths)
    ((0.30, -0.92), (0.38, 0.24, 0.20)),
    ((0.08, -1.00), (0.42, 0.27, 0.21)),
    ((-0.13, -0.95), (0.39, 0.25, 0.20)),
    ((-0.32, -0.84), (0.30, 0.19, 0.18)),
)
_FLEX = (75.0, 100.0, 65.0)
Vec3 = tuple[float, float, float]
W, H = 640, 480
SCALE = 100.0                       # wrist..MCP9 px; features palm_scale_px is ~96 px

# poses (curl per finger)
OPEN = {n: 0.0 for n in FINGER_NAMES}
POINT = {"thumb": 1.0, "index": 0.0, "middle": 1.0, "ring": 1.0, "little": 1.0}
PINCH = {"thumb": 0.5, "index": 0.65, "middle": 0.0, "ring": 0.0, "little": 0.0}   # pinch ~0.12 pu
FIST = {n: 1.0 for n in FINGER_NAMES}


def _curl_map(curls: Union[Mapping[str, float], float]) -> dict[str, float]:
    if isinstance(curls, (int, float)):
        return {n: float(curls) for n in FINGER_NAMES}
    out = {n: 0.0 for n in FINGER_NAMES}
    out.update(curls)
    return out


def local_hand(curls: Union[Mapping[str, float], float] = 0.0) -> list[Vec3]:
    c = _curl_map(curls)
    pts: list[Vec3] = [(0.0, 0.0, 0.0)] * 21
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


def hand(pose: Union[Mapping[str, float], float] = OPEN, center: tuple[float, float] = (320.0, 300.0), *,
         side: str = "right", label: Optional[Handedness] = None, score: float = 0.95,
         scale: float = SCALE, roll: float = 0.0) -> HandSample:
    """21-landmark HandSample. side = anatomical hand (geometry), label = what the tracker reports."""
    mirror = -1.0 if side == "left" else 1.0
    a = math.radians(roll)
    pts = []
    for x, y, z in local_hand(pose):
        x *= mirror
        pts.append((x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a), z))
    pcx = sum(pts[i][0] for i in (5, 9, 13, 17)) / 4.0
    pcy = sum(pts[i][1] for i in (5, 9, 13, 17)) / 4.0
    lms = tuple(Landmark((center[0] + (x - pcx) * scale) / W, (center[1] + (y - pcy) * scale) / H,
                         (z * scale) / W) for x, y, z in pts)
    if label is None:
        label = Handedness.LEFT if side == "left" else Handedness.RIGHT
    return HandSample(label, score, lms)


def sample(t_ms: float, hands: Sequence[HandSample] = (), latency_ms: float = 20.0) -> FrameSample:
    return FrameSample(t_ms, t_ms + latency_ms, W, H, tuple(hands))


def lerp(a: float, b: float, u: float) -> float:
    return a + (b - a) * u


HandsFn = Union[Sequence[HandSample], Callable[[float], Sequence[HandSample]]]

TARGET = WindowTarget(0xA1, 100)
TARGET_RECT = Rect(0, 0, 1920, 1040)


class Rig:
    """Real chain with fake OS adapters and a fake clock. Frames are timestamped by capture time;
    the clock is set to capture + `dispatch_delay_ms` before each process() call."""

    def __init__(self, settings: Optional[Settings] = None, *, fps: float = 30.0, jitter_ms: float = 0.0,
                 seed: int = 1, dispatch_delay_ms: float = 25.0, monitors=None,
                 windows: Optional[FakeWindows] = None, cursor_source=None, process_names=None) -> None:
        self.clock = FakeClock(10_000.0)
        self.sink = DryRunSink()
        self.displays = FakeDisplays(monitors)
        self.windows = windows if windows is not None else FakeWindows([(TARGET, TARGET_RECT)], foreground=TARGET)
        self.volume = FakeVolume(0.5)
        self.pipe = Pipeline(self.clock, self.sink, self.displays, self.windows, self.volume, settings,
                             cursor_source=cursor_source, process_names=process_names)
        self.ctl = self.pipe.controller
        self.t = 10_000.0
        self.fps = fps
        self.jitter_ms = jitter_ms
        self.rng = random.Random(seed)
        self.delay = dispatch_delay_ms
        self.frames = 0

    # ---------------- driving
    def frame(self, hands: Sequence[HandSample], *, age_ms: Optional[float] = None) -> None:
        """One frame at the current time; then advance by one (jittered) frame interval."""
        delay = self.delay if age_ms is None else age_ms
        self.clock.set(self.t + delay)
        self.pipe.process(sample(self.t, hands))
        self.frames += 1
        step = 1000.0 / self.fps
        if self.jitter_ms:
            step += self.rng.uniform(-self.jitter_ms, self.jitter_ms)
        self.t += max(1.0, step)

    def run(self, duration_ms: float, hands: HandsFn) -> "Rig":
        """Frames for `duration_ms`. hands may be a callable of u in [0, 1] over the segment."""
        t0 = self.t
        end = t0 + duration_ms
        while self.t < end:
            u = min(1.0, (self.t - t0) / duration_ms) if duration_ms > 0 else 1.0
            self.frame(hands(u) if callable(hands) else hands)
        return self

    def gap(self, ms: float) -> None:
        self.t += ms
        self.clock.set(self.t)

    # ---------------- state
    @property
    def state(self) -> ControlState:
        return self.ctl.snapshot().state

    @property
    def mode(self) -> Mode:
        return self.ctl.snapshot().mode

    def kinds(self, skip_release: bool = True) -> list[ActionKind]:
        return [k for k in self.sink.kinds() if not (skip_release and k is ActionKind.RELEASE_ALL)]

    def count(self, kind: ActionKind) -> int:
        return self.sink.count(kind)

    def camera_on(self) -> None:
        self.pipe.set_camera_state(CameraState.RUNNING)

    def activate(self, hands: Sequence[HandSample] = ()) -> None:
        """Camera on + tray resume, then 300 ms of `hands` for a fresh neutral."""
        self.camera_on()
        assert self.pipe.resume()
        if hands:
            self.run(300, hands)


# ---------------- common hand placements (unmirrored image: the user's right hand appears on the left)

DOM_C = (250.0, 300.0)       # right (dominant) hand position
ND_C = (470.0, 300.0)        # left hand position


def pair(d_pu: float, *, pose: Mapping[str, float] = OPEN, y: float = 300.0, cx: float = 320.0,
         dom_label: Handedness = Handedness.RIGHT, nd_label: Handedness = Handedness.LEFT) -> list[HandSample]:
    """Right hand on the image left, left hand on the image right, palm centers d_pu apart."""
    half = d_pu * 96.0 / 2.0
    return [hand(pose, (cx - half, y), side="right", label=dom_label),
            hand(pose, (cx + half, y), side="left", label=nd_label)]


def clap(rig: Rig, *, merge_frames: int = 2, approach_ms: float = 240.0, separate_ms: float = 240.0,
         hold_ms: float = 200.0, far: float = 3.0) -> None:
    """Separated hold, fast approach, contact where the tracker reports one merged hand,
    then separation and a separated hold."""
    rig.run(hold_ms, pair(far))
    rig.run(approach_ms, lambda u: pair(lerp(far, 0.45, u)))
    for _ in range(merge_frames):
        rig.frame([hand(OPEN, (320.0, 300.0), side="right", label=Handedness.RIGHT, score=0.6)])
    rig.run(separate_ms, lambda u: pair(lerp(0.45, far, u)))
    rig.run(hold_ms, pair(far))
