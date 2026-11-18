"""Delegate to the application, with an explicit window-free packaging check."""
from __future__ import annotations

import hashlib
import importlib
import json
import sys
import traceback
from pathlib import Path


def packaging_check(output: Path) -> int:
    """Load dependencies and verify bundled assets without opening devices or UI."""
    result: dict[str, object] = {"ok": False}
    try:
        for name in ("handcontrol.app", "handcontrol.windows.startup", "cv2",
                     "PySide6.QtWidgets", "pycaw.pycaw"):
            importlib.import_module(name)
        from handcontrol.tracking import default_model_path, project_root
        from mediapipe.tasks.python.core import mediapipe_c_bindings

        mediapipe_c_bindings.load_raw_library()
        root = project_root()
        manifest = json.loads((root / "assets" / "model_manifest.json").read_text(encoding="utf-8"))
        for model in manifest["models"]:
            digest = hashlib.sha256((root / model["local_path"]).read_bytes()).hexdigest()
            if digest != model["sha256"]:
                raise ValueError(f"Bundled model hash mismatch: {model['id']}")
        for plugin in ("qwindows.dll", "qoffscreen.dll"):
            if not (root / "PySide6" / "plugins" / "platforms" / plugin).is_file():
                raise FileNotFoundError(f"Missing Qt platform plugin: {plugin}")
        result.update(ok=True, model_path=str(default_model_path()), frozen=bool(getattr(sys, "frozen", False)))
    except Exception:
        result["error"] = traceback.format_exc()
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if result["ok"] else 1


def self_test(report: Path) -> int:
    """Window-free, camera-free check: packaging check + model inference on a blank image.

    The exe is windowed (no stdout), so the result line is written to `report`.
    """
    import tempfile

    def finish(line: str, code: int) -> int:
        report.write_text(line + "\n", encoding="utf-8")
        if sys.stdout is not None:
            print(line)
        return code

    check = Path(tempfile.gettempdir()) / "holoscobe_packaging_check.json"
    if packaging_check(check) != 0:
        return finish("SELF-TEST FAILED: " + check.read_text(encoding="utf-8"), 1)
    try:
        import mediapipe as mp
        import numpy as np
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision
        from handcontrol.tracking import default_model_path

        # Load from bytes: MediaPipe cannot open non-ASCII paths on Windows.
        options = vision.HandLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_buffer=default_model_path().read_bytes()),
            num_hands=1)
        with vision.HandLandmarker.create_from_options(options) as landmarker:
            frame = np.zeros((240, 320, 3), dtype=np.uint8)
            result = landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=frame))
        hands = len(result.hand_landmarks)
    except Exception:
        return finish("SELF-TEST FAILED: " + traceback.format_exc(), 1)
    return finish(f"OK self-test hands={hands} frozen={bool(getattr(sys, 'frozen', False))}", 0)


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        return self_test(Path(sys.argv[2]))
    if len(sys.argv) == 3 and sys.argv[1] == "--packaging-check":
        return packaging_check(Path(sys.argv[2]))
    from handcontrol.app import main as app_main
    return app_main()


if __name__ == "__main__":
    raise SystemExit(main())
