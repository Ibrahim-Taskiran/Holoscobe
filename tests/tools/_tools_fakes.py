"""Fakes for the acceptance tools: virtual-clock frame source, scripted console, feature builders."""
from __future__ import annotations

from typing import Any, Callable, Optional

from handcontrol.contracts import (
    FingerInfo,
    FingerName,
    FingerState,
    FrameFeatures,
    GestureEvent,
    GestureKind,
    Handedness,
    HandFeatures,
    Landmark,
    Quality,
)
from handcontrol.tools.common import Observation, ToolError

ORDER = (FingerName.THUMB, FingerName.INDEX, FingerName.MIDDLE, FingerName.RING, FingerName.LITTLE)
LM21 = tuple(Landmark(0.5, 0.5) for _ in range(21))


def hand(
    label: Handedness = Handedness.RIGHT,
    states: Optional[dict[FingerName, FingerState]] = None,
    default: FingerState = FingerState.EXTENDED,
    quality: Quality = Quality.USABLE,
    center: tuple[float, float] = (320.0, 240.0),
    scale: float = 100.0,
    landmarks: tuple[Landmark, ...] = LM21,
    hand_id: int = 1,
) -> HandFeatures:
    states = states or {}
    fingers = tuple(FingerInfo(n, states.get(n, default), 0.0) for n in ORDER)
    return HandFeatures(
        hand_id=hand_id, handedness=label, quality=quality, palm_center_px=center,
        palm_scale_px=scale if quality == Quality.USABLE else 0.0, fingers=fingers,
        pinch_distance=1.0, index_tip_px=center, landmarks=landmarks,
    )


def frame(t: float, *hands: HandFeatures, ambiguous: bool = False, latency: float = 20.0) -> FrameFeatures:
    return FrameFeatures(
        capture_ms=t, inference_done_ms=t + latency, width=640, height=480,
        hands=tuple(hands), identity_ambiguous=ambiguous,
    )


class FakeConsole:
    def __init__(self, answers: Optional[dict[str, str]] = None) -> None:
        self.said: list[str] = []
        self.asked: list[str] = []
        self.answers = answers or {}

    def say(self, text: str = "") -> None:
        self.said.append(text)

    def ask(self, prompt: str, pump: Optional[Callable[[], None]] = None) -> str:
        self.asked.append(prompt)
        for key, val in self.answers.items():
            if key in prompt:
                return val
        return ""


class FakeSource:
    """Virtual clock: every next() advances `step_ms` and asks `provider(t)` for the frame."""

    def __init__(
        self,
        provider: Callable[[float], Optional[FrameFeatures]],
        *,
        step_ms: float = 33.0,
        interrupt_after: Optional[int] = None,
        open_error: Optional[str] = None,
        infer_ms: float = 8.0,
        info: Optional[dict[str, Any]] = None,
        start_ms: float = 1000.0,
    ) -> None:
        self.provider, self.step, self.t = provider, step_ms, start_ms
        self.interrupt_after, self.open_error, self.infer_ms = interrupt_after, open_error, infer_ms
        self.info = info or {"arka_uc": "fake", "kamera_fps": 30.0}
        self.calls = 0
        self.opened = False
        self.closed = 0

    def now_ms(self) -> float:
        return self.t

    def open(self) -> None:
        if self.open_error:
            raise ToolError(self.open_error)
        self.opened = True

    def next(self, timeout_s: float = 0.2) -> Optional[Observation]:
        self.t += self.step
        self.calls += 1
        if self.interrupt_after is not None and self.calls > self.interrupt_after:
            raise KeyboardInterrupt
        f = self.provider(self.t)
        return None if f is None else Observation(f, self.infer_ms)

    def close(self) -> None:
        self.closed += 1

    def camera_info(self) -> dict[str, Any]:
        return dict(self.info)


class FakeRecognizer:
    """update(frame) -> events chosen by a callback."""

    def __init__(self, fn: Callable[[FrameFeatures], list[GestureEvent]]) -> None:
        self.fn = fn

    def update(self, frame: FrameFeatures) -> list[GestureEvent]:
        return self.fn(frame)


def clap(t: float) -> GestureEvent:
    return GestureEvent(GestureKind.CLAP, t)
