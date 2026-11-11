"""Synthetic timeline builder for gesture tests (~30 fps with frame-timing jitter).

Tests use the `tl` fixture only; helpers are static methods so no test imports conftest.
"""
from __future__ import annotations

import math
import random
from typing import Callable, Iterable, Iterator, Optional, Union

import pytest

from handcontrol.contracts import (
    FingerInfo,
    FingerName,
    FingerState,
    FrameFeatures,
    GestureEvent,
    GestureKind,
    HandFeatures,
    Handedness,
    Landmark,
    Quality,
)
from handcontrol.gestures import GestureRecognizer

SCALE = 100.0                      # palm_scale_px used everywhere
ORIGIN = (640.0, 360.0)
_LANDMARKS = tuple(Landmark(0.5, 0.5) for _ in range(21))
_NON_THUMB = (FingerName.INDEX, FingerName.MIDDLE, FingerName.RING, FingerName.LITTLE)

Hands = tuple[HandFeatures, ...]
HandsSpec = Union[Hands, Callable[[float], Iterable[HandFeatures]]]

LEFT_ID, RIGHT_ID = 1, 2


def lerp(a: float, b: float, u: float) -> float:
    return a + (b - a) * u


class Timeline:
    def __init__(self, seed: int = 7, fps: float = 30.0, jitter_ms: float = 4.0,
                 start_ms: float = 10_000.0) -> None:
        self.frames: list[FrameFeatures] = []
        self.t = start_ms                 # timestamp of the next frame
        self._dt = 1000.0 / fps
        self._jitter = jitter_ms
        self._rng = random.Random(seed)
        self._cursor = 0

    # ---------------- hands
    @staticmethod
    def hand(hand_id: int = RIGHT_ID, center: tuple[float, float] = ORIGIN, *,
             handedness: Optional[Handedness] = None, scale: float = SCALE, pinch: float = 0.8,
             extended: int = 4, thumb: bool = True, quality: Quality = Quality.USABLE) -> HandFeatures:
        if handedness is None:
            handedness = Handedness.LEFT if hand_id == LEFT_ID else Handedness.RIGHT
        fingers = [FingerInfo(FingerName.THUMB,
                              FingerState.EXTENDED if thumb else FingerState.BENT, 0.1 if thumb else 0.8)]
        for i, name in enumerate(_NON_THUMB):
            ext = i < extended
            fingers.append(FingerInfo(name, FingerState.EXTENDED if ext else FingerState.BENT,
                                      0.05 if ext else 0.9))
        return HandFeatures(
            hand_id=hand_id, handedness=handedness, quality=quality, palm_center_px=center,
            palm_scale_px=scale, fingers=tuple(fingers), pinch_distance=pinch,
            index_tip_px=(center[0], center[1] - scale), landmarks=_LANDMARKS,
        )

    @staticmethod
    def overlap_hand(hand_id: int, center: tuple[float, float],
                     quality: Quality = Quality.DEGRADED) -> HandFeatures:
        """Hand as features.py reports it during palm overlap: fingers UNKNOWN, curl 0.0;
        UNKNOWN quality also means pinch_distance = inf and palm_scale_px = 0.0."""
        unknown = quality is Quality.UNKNOWN
        fingers = tuple(FingerInfo(n, FingerState.UNKNOWN, 0.0) for n in (FingerName.THUMB, *_NON_THUMB))
        return HandFeatures(
            hand_id=hand_id, handedness=Handedness.UNKNOWN if unknown else
            (Handedness.LEFT if hand_id == LEFT_ID else Handedness.RIGHT),
            quality=quality, palm_center_px=center, palm_scale_px=0.0 if unknown else SCALE * 0.9,
            fingers=fingers, pinch_distance=math.inf if unknown else 0.6,
            index_tip_px=center, landmarks=_LANDMARKS,
        )

    @staticmethod
    def pair(d_pu: float, *, dy_pu: float = 0.0, pinch: float = 0.8, extended: int = 4,
             left: Optional[dict] = None, right: Optional[dict] = None) -> Hands:
        """Left hand (id 1) and right hand (id 2), palm centers d_pu apart horizontally."""
        cx, cy = ORIGIN
        base = {"pinch": pinch, "extended": extended}
        lh = Timeline.hand(LEFT_ID, (cx - d_pu * SCALE / 2, cy), **{**base, **(left or {})})
        rh = Timeline.hand(RIGHT_ID, (cx + d_pu * SCALE / 2, cy + dy_pu * SCALE),
                           **{**base, **(right or {})})
        return (lh, rh)

    # ---------------- frames
    def add(self, duration_ms: float, hands: HandsSpec = (), *, ambiguous: bool = False) -> "Timeline":
        """Append frames covering duration_ms. `hands` is fixed or a function of u in [0, 1)."""
        start = self.t
        while self.t - start < duration_ms:
            u = (self.t - start) / duration_ms
            hs = tuple(hands(u)) if callable(hands) else tuple(hands)
            self.frame(hs, ambiguous=ambiguous)
        return self

    def frame(self, hands: Hands = (), *, ambiguous: bool = False, t: Optional[float] = None) -> "Timeline":
        ts = self.t if t is None else t
        self.frames.append(FrameFeatures(ts, ts + 12.0, 1280, 720, tuple(hands), ambiguous))
        if t is None:
            self.t += self._dt + self._rng.uniform(-self._jitter, self._jitter)
        return self

    def feed(self, rec: GestureRecognizer) -> Iterator[tuple[FrameFeatures, list[GestureEvent]]]:
        """Feed frames not yet fed one by one, yielding (frame, events) for per-frame checks."""
        while self._cursor < len(self.frames):
            f = self.frames[self._cursor]
            self._cursor += 1
            yield f, rec.update(f)

    def run(self, rec: GestureRecognizer) -> list[GestureEvent]:
        """Feed frames not yet fed; return their events."""
        return [e for _, ev in self.feed(rec) for e in ev]

    # ---------------- scripted claps
    def clap(self, *, start_d: float = 2.6, hold_ms: float = 300.0, approach_ms: float = 250.0,
             near_d: float = 0.3, contact_ms: float = 60.0, separate_ms: float = 300.0,
             end_d: float = 2.4, end_hold_ms: float = 200.0, **pair_kw) -> "Timeline":
        self.add(hold_ms, Timeline.pair(start_d, **pair_kw))
        self.add(approach_ms, lambda u: Timeline.pair(lerp(start_d, near_d, u), **pair_kw))
        self.add(contact_ms, Timeline.pair(near_d, **pair_kw))
        self.add(separate_ms, lambda u: Timeline.pair(lerp(near_d, end_d, u), **pair_kw))
        self.add(end_hold_ms, Timeline.pair(end_d, **pair_kw))
        return self

    # ---------------- assertions helpers
    @staticmethod
    def kinds(events: Iterable[GestureEvent]) -> list[GestureKind]:
        return [e.kind for e in events]

    @staticmethod
    def of(events: Iterable[GestureEvent], kind: GestureKind) -> list[GestureEvent]:
        return [e for e in events if e.kind is kind]


@pytest.fixture
def tl() -> Timeline:
    return Timeline()


@pytest.fixture
def make_tl() -> type[Timeline]:
    """The Timeline class itself, for tests that need a custom seed / fps."""
    return Timeline


@pytest.fixture
def rec() -> GestureRecognizer:
    return GestureRecognizer()
