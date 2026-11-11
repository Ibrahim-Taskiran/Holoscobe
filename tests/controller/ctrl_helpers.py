"""Shared helpers for controller tests (imported as a plain module; prepend import mode)."""
from __future__ import annotations

from typing import Iterable, Optional, Sequence, Union

from handcontrol.contracts import (
    ActionKind,
    CameraState,
    FingerInfo,
    FingerName,
    FingerState,
    FrameFeatures,
    GestureEvent,
    GestureKind,
    HandFeatures,
    Handedness,
    Landmark,
    Monitor,
    Quality,
    Rect,
    WindowTarget,
)
from handcontrol.controller import Controller, ControllerConfig
from handcontrol.dryrun import DryRunSink, FakeClock, FakeDisplays, FakeVolume, FakeWindows
from handcontrol.mapping import CalibrationRect

W, H = 640, 480
RIGHT, LEFT = 1, 2  # hand ids
WIN_A = WindowTarget(hwnd=0xA, pid=100)
WIN_B = WindowTarget(hwnd=0xB, pid=200)

K = ActionKind
G = GestureKind


class Identity:
    def __init__(self) -> None:
        self.resets = 0

    def reset(self) -> None:
        self.resets += 1

    def filter(self, t_ms: float, x: float, y: float) -> tuple[float, float]:
        return x, y


def hand(hid: int = RIGHT, tip: tuple[float, float] = (320.0, 240.0), palm: Optional[tuple[float, float]] = None,
         handed: Optional[Handedness] = None, scale: float = 60.0, quality: Quality = Quality.USABLE,
         index: bool = True) -> HandFeatures:
    if handed is None:
        handed = Handedness.RIGHT if hid == RIGHT else Handedness.LEFT
    if palm is None:
        palm = (tip[0], tip[1] + 60.0)
    fingers = tuple(
        FingerInfo(n, FingerState.EXTENDED if (n is not FingerName.INDEX or index) else FingerState.BENT, 0.1)
        for n in FingerName
    )
    return HandFeatures(
        hand_id=hid, handedness=handed, quality=quality, palm_center_px=palm, palm_scale_px=scale,
        fingers=fingers, pinch_distance=1.0, index_tip_px=tip,
        landmarks=tuple(Landmark(0.5, 0.5) for _ in range(21)),
    )


EventSpec = Union[GestureEvent, tuple]


def tcfg(**kw) -> ControllerConfig:
    base = dict(mirror=False, calibration=CalibrationRect(), index_tap_click=False)  # Legacy pinch regression fixtures.
    base.update(kw)
    return ControllerConfig(**base)




def desktop(tip: tuple[float, float]) -> tuple[int, int]:
    """Expected mapping with tcfg on the default single 1920x1080 monitor."""
    return int(round(tip[0] / W * 1919)), int(round(tip[1] / H * 1079))


class Rig:
    def __init__(self, cfg: Optional[ControllerConfig] = None, monitors: Optional[Sequence[Monitor]] = None,
                 windows: Optional[FakeWindows] = None, volume: float = 0.5, smoother=None,
                 camera: bool = True, active: bool = True) -> None:
        self.clock = FakeClock()
        self.sink = DryRunSink()
        self.displays = FakeDisplays(monitors)
        if windows is None:
            windows = FakeWindows([(WIN_A, Rect(-10000, -10000, 10000, 10000))], foreground=WIN_A)
        self.windows = windows
        self.volume = FakeVolume(volume)
        self.smoother = smoother if smoother is not None else Identity()
        self.ctl = Controller(self.clock, self.sink, self.displays, self.windows, self.volume,
                              cfg or tcfg(), smoother=self.smoother)
        if camera:
            self.ctl.set_camera_state(CameraState.RUNNING)
        if active:
            assert self.ctl.resume()
        self.sink.clear()

    def ev(self, spec: Iterable[EventSpec], t: float) -> tuple[GestureEvent, ...]:
        out = []
        for s in spec:
            if isinstance(s, GestureEvent):
                out.append(s)
            else:
                kind, hid = (s[0], s[1]) if len(s) > 1 else (s[0], None)
                out.append(GestureEvent(kind, t, hid))
        return tuple(out)

    def frame(self, *hands: HandFeatures, events: Iterable[EventSpec] = (), dt: float = 33.4,
              latency: float = 5.0, ambiguous: bool = False) -> float:
        now = self.clock.advance(dt)
        cap = now - latency
        self.ctl.on_frame(FrameFeatures(cap, cap + 2.0, W, H, tuple(hands), ambiguous), self.ev(events, cap))
        return cap

    def settle(self, *hands: HandFeatures, frames: int = 8) -> None:
        """Satisfy the neutral requirement, then clear recorded actions."""
        for _ in range(frames):
            self.frame(*hands)
        assert not self.ctl.snapshot().needs_neutral
        self.sink.clear()

    def kinds(self) -> list[ActionKind]:
        return self.sink.kinds()

    def count(self, kind: ActionKind) -> int:
        return self.sink.count(kind)

    def non_pointer(self) -> list[ActionKind]:
        return [k for k in self.kinds() if k is not ActionKind.MOVE_POINTER]
