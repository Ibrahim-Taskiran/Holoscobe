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


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--packaging-check":
        return packaging_check(Path(sys.argv[2]))
    from handcontrol.app import main as app_main
    return app_main()


if __name__ == "__main__":
    raise SystemExit(main())
