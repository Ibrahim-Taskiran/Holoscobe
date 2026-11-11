"""Shared console + live-source plumbing for the acceptance tools.

Everything hardware-bound (camera, tracker) lives in LiveSource; the tool cores only see the
FrameSource protocol, so tests plug in fakes. No GUI windows and no OS input are used.
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional, Protocol

from ..contracts import CameraState, FrameFeatures


class ToolError(Exception):
    """User-facing (Turkish) failure: camera error, model missing, ..."""


@dataclass(frozen=True)
class Observation:
    """One UNIQUE inference result: features plus the measured inference time."""

    frame: FrameFeatures
    inference_ms: float


class FrameSource(Protocol):
    def open(self) -> None: ...
    def next(self, timeout_s: float = 0.2) -> Optional[Observation]: ...
    def close(self) -> None: ...
    def camera_info(self) -> dict[str, Any]: ...
    def now_ms(self) -> float: ...


class Console(Protocol):
    def say(self, text: str = "") -> None: ...
    def ask(self, prompt: str, pump: Optional[Callable[[], None]] = None) -> str: ...


class RealConsole:
    """stdin/stdout console. ask() keeps calling pump() so the camera pipeline stays warm."""

    def say(self, text: str = "") -> None:
        print(text, flush=True)

    def ask(self, prompt: str, pump: Optional[Callable[[], None]] = None) -> str:
        print(prompt, end="", flush=True)
        try:
            import msvcrt  # Windows only
        except ImportError:
            return input()
        if pump is None:
            return input()
        chars: list[str] = []
        while True:
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch == "\x03":
                    raise KeyboardInterrupt
                if ch in ("\r", "\n"):
                    print(flush=True)
                    return "".join(chars)
                if ch == "\b":
                    if chars:
                        chars.pop()
                        print("\b \b", end="", flush=True)
                    continue
                chars.append(ch)
                print(ch, end="", flush=True)
            else:
                pump()


def monotonic_ms() -> float:
    return time.monotonic() * 1000.0


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * q
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


class LiveSource:
    """Real camera -> HandTracker -> FeatureExtractor. Never reuses a frame (Camera guarantees it)."""

    def __init__(
        self,
        width: int = 640,
        height: int = 480,
        fps: int = 30,
        *,
        index: int = 0,
        backend: str = "msmf",
        swap_handedness: bool = False,
        camera: Any = None,
        tracker: Any = None,
        extractor: Any = None,
    ) -> None:
        from ..camera import Camera, CameraConfig
        from ..features import FeatureExtractor
        from ..tracking import HandTracker

        self.config = CameraConfig(index=index, backend=backend, width=width, height=height, fps=fps)
        self.swap_handedness = swap_handedness
        self.camera = camera or Camera(self.config)
        self.tracker = tracker or HandTracker(swap_handedness=swap_handedness)
        self.extractor = extractor or FeatureExtractor()
        self._opened = False

    def now_ms(self) -> float:
        return monotonic_ms()

    def open(self) -> None:
        self.camera.start()
        self.camera.wait_for_state({CameraState.RUNNING, CameraState.ERROR}, 12.0)
        if self.camera.state != CameraState.RUNNING:
            from ..camera import MSG_NOT_FOUND

            msg = self.camera.last_error or MSG_NOT_FOUND
            self.close()
            raise ToolError(msg)
        try:
            self.tracker.load()
        except FileNotFoundError as exc:
            self.close()
            raise ToolError(str(exc)) from exc
        self._opened = True

    def next(self, timeout_s: float = 0.2) -> Optional[Observation]:
        if self.camera.state == CameraState.ERROR:
            raise ToolError(self.camera.last_error or "Kamera hatası.")
        item = self.camera.read_latest(timeout_s)
        if item is None:
            return None
        frame_bgr, capture_ms = item
        t0 = time.perf_counter()
        sample = self.tracker.process(frame_bgr, capture_ms)
        inference_ms = (time.perf_counter() - t0) * 1000.0
        return Observation(self.extractor.update(sample), inference_ms)

    def close(self) -> None:
        for fn in (self.tracker.close, self.camera.stop):
            try:
                fn()
            except Exception:
                pass
        self._opened = False

    def camera_info(self) -> dict[str, Any]:
        cam = self.camera
        return {
            "arka_uc": self.config.backend,
            "istenen": f"{self.config.width}x{self.config.height}@{self.config.fps}",
            "gercek_cozunurluk": f"{cam.actual_width}x{cam.actual_height}",
            "kamera_fps": round(cam.actual_fps, 1),
            "el_etiketi_degisimi": self.swap_handedness,
        }


def add_camera_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--camera-index", type=int, default=0, help="kamera numarası")
    p.add_argument("--backend", choices=("msmf", "dshow", "auto"), default="msmf")
    p.add_argument("--out-dir", default=None, help="rapor klasörü (varsayılan Docs/reports)")


def ask_conditions(console: Console) -> dict[str, str]:
    """Koşul rows are asked from the user, never guessed."""
    console.say("Koşulları yazın (boş bırakmayın; Enter ile geçilir):")
    return {
        "Işık": console.ask("  Işık (ör. gün ışığı, tavan lambası, loş): ").strip() or "belirtilmedi",
        "Arka plan": console.ask("  Arka plan (ör. düz duvar, dağınık oda): ").strip() or "belirtilmedi",
        "Mesafe": console.ask("  Kameraya mesafe (ör. 50-70 cm): ").strip() or "belirtilmedi",
    }


def pump_source(source: FrameSource) -> Callable[[], None]:
    """Keeps the pipeline (and temporal filters) warm while the user types; frames are discarded."""

    def pump() -> None:
        source.next(0.03)

    return pump


def run_main(fn: Callable[[], int]) -> None:
    """Shared entry point: Turkish camera/tool errors print cleanly, exit code 2."""
    try:
        code = fn()
    except ToolError as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        code = 2
    sys.exit(code)
