"""One visible hand: track it with a one-hand model instead of the two-hand one.

A two-hand HandLandmarker runs palm detection on every frame while it tracks fewer hands than it may, so one
visible hand (the usual case) costs more than two. AdaptiveLandmarker keeps two models behind the same interface:
- "full" (two hands) runs on every frame until exactly one hand was visible for `settle_ms`;
- "single" (one hand) then takes over on the calling thread, while "full" looks for a second hand (the scout) on a
  worker thread every `scout_ms`.
The full model comes back at once when the scout sees two hands or a hand elsewhere, when the single model loses
its hand (same frame, so no frame is lost), or when `allowed()` turns False.
"""
from __future__ import annotations

import logging
import math
from concurrent.futures import Future, ThreadPoolExecutor, wait
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)

SETTLE_MS = 500          # longer than the palm overlap of a clap
SCOUT_MS = 125
SAME_HAND = 0.6          # palm centre distance, in wrist-to-middle-knuckle lengths


def _hands(result: Any) -> list:
    return list(getattr(result, "hand_landmarks", None) or [])


def same_hand(a: Any, b: Any) -> bool:
    """Both results hold exactly one hand, in about the same place."""
    first, second = _hands(a), _hands(b)
    if len(first) != 1 or len(second) != 1:
        return False
    p, q = first[0], second[0]
    size = math.hypot(p[9].x - p[0].x, p[9].y - p[0].y)
    apart = math.hypot(p[0].x + p[9].x - q[0].x - q[9].x, p[0].y + p[9].y - q[0].y - q[9].y) / 2
    return apart <= SAME_HAND * size


class AdaptiveLandmarker:
    """Drop-in for HandLandmarker (detect_for_video, close). Call it from one thread only."""

    def __init__(self, full: Any, single: Any, *, allowed: Optional[Callable[[], bool]] = None,
                 settle_ms: int = SETTLE_MS, scout_ms: int = SCOUT_MS, executor: Any = None) -> None:
        self._full, self._single, self._allowed = full, single, allowed
        self._settle, self._interval = settle_ms, scout_ms
        self._pool = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix="hand-scout")
        self._fast = False
        self._alone_since: Optional[int] = None
        self._scout: Optional[Future] = None
        self._scout_base: Any = None             # what the single model saw on the scouted frame
        self._next_scout = 0

    @property
    def fast(self) -> bool:
        """True while the one-hand model drives the output."""
        return self._fast

    def detect_for_video(self, image: Any, ts: int) -> Any:
        if self._fast:
            if self._permitted() and not self._scout_disagrees():
                result = self._single.detect_for_video(image, ts)
                if _hands(result):
                    if self._scout is None and ts >= self._next_scout:
                        self._scout_base, self._next_scout = result, ts + self._interval
                        self._scout = self._pool.submit(self._full.detect_for_video, image, ts)
                    return result
            self._leave()
        result = self._full.detect_for_video(image, ts)
        if len(_hands(result)) != 1 or not self._permitted():
            self._alone_since = None
        elif self._alone_since is None:
            self._alone_since = ts
        elif ts - self._alone_since >= self._settle:
            # The single model may still look where it last saw a hand: switch only when both agree.
            self._alone_since = None
            self._fast = same_hand(result, self._single.detect_for_video(image, ts))
            self._next_scout = ts + self._interval
        return result

    def close(self) -> None:
        self._leave()
        self._pool.shutdown(wait=True)
        try:
            self._full.close()
        finally:
            self._single.close()

    def _permitted(self) -> bool:
        return self._allowed is None or bool(self._allowed())

    def _scout_disagrees(self) -> bool:
        scout = self._scout
        if scout is None or not scout.done():
            return False
        self._scout = None
        if scout.exception() is not None:
            log.warning("second hand search failed: %s", scout.exception())
            return True
        found = scout.result()
        count = len(_hands(found))
        return count > 1 or count == 1 and not same_hand(self._scout_base, found)

    def _leave(self) -> None:
        """Back to the full model; afterwards no worker uses it (its timestamps must keep rising)."""
        self._fast, self._alone_since = False, None
        scout, self._scout = self._scout, None
        if scout is not None and not scout.cancel():
            wait([scout])


__all__ = ["AdaptiveLandmarker", "same_hand"]
