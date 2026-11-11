"""Fakes for camera/tracking tests. No real camera, cv2 or mediapipe is used."""
from __future__ import annotations

import time
from types import SimpleNamespace


class FakeClock:
    def __init__(self, start: float = 1000.0, step: float = 0.0) -> None:
        self.t = start
        self.step = step

    def now_ms(self) -> float:
        v = self.t
        self.t += self.step
        return v


class FakeFrame:
    def __init__(self, tag, w=640, h=480):
        self.tag = tag
        self.shape = (h, w, 3)


class FakeCapture:
    """Scripted capture. frames: list of items; exhausted -> read fails (ok False)."""

    def __init__(self, frames=None, *, endless=False, delay=0.0, props=(640, 480, 30.0)):
        self.frames = list(frames or [])
        self.endless = endless
        self.delay = delay
        self.released = False
        self.reads = 0
        self.props = {3: props[0], 4: props[1], 5: props[2]}
        self._n = 0

    def isOpened(self):
        return not self.released

    def get(self, prop):
        return self.props.get(int(prop), 0)

    def set(self, prop, value):
        return True

    def read(self):
        self.reads += 1
        if self.delay:
            time.sleep(self.delay)
        if self.endless:
            self._n += 1
            return True, FakeFrame(self._n)
        if self.frames:
            return True, self.frames.pop(0)
        time.sleep(0.001)
        return False, None

    def release(self):
        self.released = True


class Factory:
    """capture_factory recording calls; behaviors maps call number (0-based) or backend to result."""

    def __init__(self, behavior):
        self.behavior = behavior   # callable(call_no, index, backend) -> capture or raises
        self.calls = []
        self.captures = []

    def __call__(self, index, backend, cfg):
        n = len(self.calls)
        self.calls.append((index, backend))
        cap = self.behavior(n, index, backend)
        self.captures.append(cap)
        return cap


def wait_until(pred, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.005)
    return pred()


def make_landmarks(n=21, base=0.5):
    return [SimpleNamespace(x=base + i * 0.001, y=base, z=0.01 * i) for i in range(n)]
