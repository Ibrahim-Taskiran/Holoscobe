# -*- mode: python ; coding: utf-8 -*-
"""Windowed one-folder build using only the already installed environment."""
from pathlib import Path

import hashlib
import json

from PyInstaller.utils.hooks import collect_all, collect_submodules

root = Path(SPECPATH).parent

# Fail the build if a model listed in the manifest is missing or its SHA-256 differs.
for _m in json.loads((root / "assets" / "model_manifest.json").read_text(encoding="utf-8"))["models"]:
    _p = root / _m["local_path"]
    if hashlib.sha256(_p.read_bytes()).hexdigest().lower() != _m["sha256"].lower():
        raise SystemExit(f"Model SHA-256 mismatch or missing: {_m['id']}")

# Qt plugins (platforms/styles/imageformats) come from PySide6's own hooks; the
# whole assets/ folder (models, manifest, icon) is bundled as data.
_icon = root / "assets" / "icon.ico"
mp_data, mp_binaries, mp_imports = collect_all(
    "mediapipe", filter_submodules=lambda name: ".test" not in name,
    exclude_datas=["**/test/**", "**/tests/**"],
)

a = Analysis(
    [str(root / "packaging" / "entrypoint.py")],
    pathex=[str(root / "src")],
    binaries=mp_binaries,
    datas=[(str(root / "assets"), "assets"),
           (str(root / "THIRD_PARTY_NOTICES.md"), "."), *mp_data],
    hiddenimports=["handcontrol.app", "handcontrol.windows.startup", "cv2",
                   "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets",
                   *mp_imports, *collect_submodules("pycaw"),
                   *collect_submodules("comtypes")],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PyQt5", "PyQt6", "PySide2", "tkinter", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="Holoscobe",
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, disable_windowed_traceback=False, uac_admin=False,
    icon=str(_icon) if _icon.is_file() else None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Holoscobe")
