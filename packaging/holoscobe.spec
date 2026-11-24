# -*- mode: python ; coding: utf-8 -*-
"""Windowed one-folder build using only the already installed environment."""
from pathlib import Path

import hashlib
import json

from PyInstaller.utils.hooks import collect_all, collect_submodules, get_module_file_attribute

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

# Enstrüman mode audio: sounddevice loads _sounddevice_data/portaudio-binaries/libportaudio64bit.dll
# (next to its module) when no system PortAudio exists. Ship only that non-ASIO 64-bit DLL.
_PA_DIR = "_sounddevice_data/portaudio-binaries"
_PA_DLL = "libportaudio64bit.dll"
_pa_src = Path(get_module_file_attribute("sounddevice")).parent / _PA_DIR / _PA_DLL
if not _pa_src.is_file():
    raise SystemExit(f"PortAudio DLL missing: {_pa_src}")

a = Analysis(
    [str(root / "packaging" / "entrypoint.py")],
    pathex=[str(root / "src")],
    binaries=[*mp_binaries, (str(_pa_src), _PA_DIR)],
    datas=[(str(root / "assets"), "assets"),
           (str(root / "THIRD_PARTY_NOTICES.md"), "."), *mp_data],
    hiddenimports=["handcontrol.app", "handcontrol.windows.startup", "cv2",
                   "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets", "PySide6.QtOpenGL", "handcontrol.mascot.window",
                   "sounddevice", "_cffi_backend",
                   "handcontrol.instrument.synth", "handcontrol.instrument.audio",
                   *mp_imports, *collect_submodules("pycaw"),
                   *collect_submodules("comtypes")],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PyQt5", "PyQt6", "PySide2", "tkinter", "pytest"],
    noarchive=False,
)


def _only_wanted_portaudio(entries):
    # The sounddevice contrib hook collects every PortAudio variant (ASIO, 32-bit, arm64, dylib) and README.
    keep = f"{_PA_DIR}/{_PA_DLL}"
    return [e for e in entries
            if "_sounddevice_data" not in e[0].replace("\\", "/") or e[0].replace("\\", "/") == keep]


a.binaries = _only_wanted_portaudio(a.binaries)
a.datas = _only_wanted_portaudio(a.datas)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="Holoscobe",
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, disable_windowed_traceback=False, uac_admin=False,
    icon=str(_icon) if _icon.is_file() else None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Holoscobe")
