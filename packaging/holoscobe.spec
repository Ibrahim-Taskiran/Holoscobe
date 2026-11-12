# -*- mode: python ; coding: utf-8 -*-
"""Windowed one-folder build using only the already installed environment."""
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

root = Path(SPECPATH).parent
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
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Holoscobe")
