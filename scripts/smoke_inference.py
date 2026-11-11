"""Phase 0 smoke test: load the local hand_landmarker.task on CPU and time inference on synthetic frames.

Headless: no camera, no window. Usage: .venv\\Scripts\\python.exe scripts\\smoke_inference.py [--frames N]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python import vision

ROOT = Path(__file__).resolve().parent.parent
MODEL = ROOT / "assets" / "models" / "hand_landmarker.task"
MANIFEST = ROOT / "assets" / "model_manifest.json"


def synthetic_frames(n: int, width: int, height: int) -> list[np.ndarray]:
    rng = np.random.default_rng(0)
    frames = []
    for i in range(n):
        # gradient + noise; changes every frame so the detector actually runs
        base = np.linspace(0, 255, width, dtype=np.float32)[None, :, None]
        img = np.broadcast_to(base, (height, width, 3)).copy()
        img += rng.normal(0, 20, img.shape).astype(np.float32) + (i * 7) % 60
        frames.append(np.clip(img, 0, 255).astype(np.uint8))
    return frames


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=60)
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--use-path", action="store_true", help="load via model_asset_path (fails on non-ASCII paths)")
    args = ap.parse_args()

    if not MODEL.is_file():
        print(f"ERROR: model missing: {MODEL}  (run scripts\\setup.ps1)")
        return 2
    expected = json.loads(MANIFEST.read_text(encoding="utf-8"))["models"][0]["sha256"]
    actual = hashlib.sha256(MODEL.read_bytes()).hexdigest()
    if actual != expected:
        print(f"ERROR: model SHA-256 mismatch: {actual} != manifest {expected}")
        return 3

    print(f"python {sys.version.split()[0]} {platform.machine()} | mediapipe {mp.__version__} | numpy {np.__version__}")
    print(f"model {MODEL.name} sha256 OK ({actual[:16]}...)")

    # MediaPipe's native loader cannot open model_asset_path when the path has non-ASCII characters
    # (e.g. a Turkish user folder): FileNotFoundError. Passing the bytes avoids it. --use-path shows the issue.
    if args.use_path:
        base = BaseOptions(model_asset_path=str(MODEL), delegate=BaseOptions.Delegate.CPU)
    else:
        base = BaseOptions(model_asset_buffer=MODEL.read_bytes(), delegate=BaseOptions.Delegate.CPU)
    print(f"model loaded via {'model_asset_path' if args.use_path else 'model_asset_buffer'}")
    options = vision.HandLandmarkerOptions(
        base_options=base,
        running_mode=vision.RunningMode.VIDEO,
        num_hands=2,
    )
    t0 = time.perf_counter()
    landmarker = vision.HandLandmarker.create_from_options(options)
    load_ms = (time.perf_counter() - t0) * 1000
    print(f"load_ms {load_ms:.1f}")

    frames = synthetic_frames(args.frames, args.width, args.height)
    times: list[float] = []
    hands_seen = 0
    with landmarker:
        for i, rgb in enumerate(frames):
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            t = time.perf_counter()
            result = landmarker.detect_for_video(image, i * 33)  # ~30 fps timestamps, monotonic
            times.append((time.perf_counter() - t) * 1000)
            hands_seen += len(result.hand_landmarks)

    warm = times[5:] if len(times) > 10 else times
    q = statistics.quantiles(warm, n=20) if len(warm) >= 20 else [max(warm)] * 19
    print(f"frames {len(times)} @ {args.width}x{args.height} | first_ms {times[0]:.1f}")
    print(f"warm_ms mean {statistics.mean(warm):.2f} median {statistics.median(warm):.2f} "
          f"p95 {q[18]:.2f} max {max(warm):.2f}")
    print(f"hands_detected_total {hands_seen} (synthetic frames, 0 expected)")
    print("RESULT: OK (CPU delegate, VIDEO mode, num_hands=2)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
