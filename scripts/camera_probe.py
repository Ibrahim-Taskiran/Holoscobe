"""Phase 0 headless camera probe. Opens the real camera, never opens a window, always releases it.

Tries Media Foundation then DirectShow; requests 640x480@30 then 1280x720@30 and measures the
actual frame size and the real delivered FPS over ~3 s each.
Usage: .venv\\Scripts\\python.exe scripts\\camera_probe.py [--index 0] [--seconds 3] [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

# Faster MSMF open on many laptops; must be set before cv2 is imported.
os.environ.setdefault("OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS", "0")

import cv2  # noqa: E402

BACKENDS = [("MSMF", cv2.CAP_MSMF), ("DSHOW", cv2.CAP_DSHOW)]
REQUESTS = [(640, 480, 30), (1280, 720, 30)]


def fourcc_str(value: float) -> str:
    v = int(value)
    s = "".join(chr((v >> (8 * i)) & 0xFF) for i in range(4)).strip("\x00")
    return s if s and s.isprintable() else f"0x{v:08X}"  # MSMF often reports a non-FOURCC code


def probe(index: int, name: str, api: int, w: int, h: int, fps: int, seconds: float) -> dict:
    row: dict = {"backend": name, "requested": f"{w}x{h}@{fps}"}
    t0 = time.perf_counter()
    cap = cv2.VideoCapture(index, api)
    try:
        if not cap.isOpened():
            row["status"] = "open_failed (busy, denied by privacy settings, or no device)"
            return row
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
        cap.set(cv2.CAP_PROP_FPS, fps)
        ok, frame = cap.read()
        row["open_to_first_frame_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        if not ok or frame is None:
            row["status"] = "opened_but_no_frames (busy or denied)"
            return row
        row["reported_fps"] = round(cap.get(cv2.CAP_PROP_FPS), 2)
        row["fourcc"] = fourcc_str(cap.get(cv2.CAP_PROP_FOURCC))
        # warm-up: drop a few frames so auto-exposure / pipeline settles
        for _ in range(5):
            cap.read()
        n, fails, shape = 0, 0, frame.shape
        start = time.perf_counter()
        while time.perf_counter() - start < seconds:
            ok, frame = cap.read()
            if ok and frame is not None:
                n += 1
                shape = frame.shape
            else:
                fails += 1
        elapsed = time.perf_counter() - start
        row.update(
            status="ok",
            actual=f"{shape[1]}x{shape[0]}",
            frames=n,
            read_failures=fails,
            seconds=round(elapsed, 2),
            measured_fps=round(n / elapsed, 2),
        )
        return row
    except Exception as exc:  # report, never crash the probe
        row["status"] = f"error: {type(exc).__name__}: {exc}"
        return row
    finally:
        cap.release()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", type=int, default=0)
    ap.add_argument("--seconds", type=float, default=3.0)
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    print(f"opencv {cv2.__version__} | camera index {args.index} | no window is opened")
    rows = []
    for name, api in BACKENDS:
        for w, h, fps in REQUESTS:
            row = probe(args.index, name, api, w, h, fps, args.seconds)
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"opencv": cv2.__version__, "index": args.index, "results": rows}, f, indent=2)
    print("camera released")
    return 0 if any(r.get("status") == "ok" for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
