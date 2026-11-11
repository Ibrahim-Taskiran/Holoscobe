# Third-party notices and license inventory

Status: Phase 0 inventory, 2026-11-12. Source: installed package metadata in `.venv` (Python 3.11.18, Windows x64),
exact versions = `requirements.lock`. This is an engineering inventory, not legal advice. Re-run it whenever the lock changes.

The project's own source license is NOT chosen yet (spec §3: confirm before public distribution).

## Zero-cost check

- No paid SDK, trial, subscription, API key, account, usage quota or cloud service is used. All packages come from PyPI under
  open-source licenses; the model is downloaded once from Google's public storage and runs locally on CPU.
- Network is only needed at setup (PyPI + model download). Runtime is offline.

## Model artifact (licensed separately from the MediaPipe library)

| Artifact | Version | License | Evidence | Ship? |
|---|---|---|---|---|
| hand_landmarker.task (HandLandmarker full, float16) | float16/1, GCS generation 1682480004222387 | Apache-2.0 | Official model card "MediaPipe Hands (Lite/Full)" p.2 "LICENSED UNDER Apache License, Version 2.0", linked from the official Hand Landmarker docs "Models" table. Details: `assets/model_manifest.json` | License permits redistribution. Release bundling HELD until the SHA-256 is independently reviewed; setup downloads it meanwhile. |

## Python packages (35, incl. transitive)

Legend for "Ship": **runtime** = goes into the one-folder build; **exclude** = pulled in transitively but not imported by the
app, exclude it in the PyInstaller spec; **dev** = development/build only, never shipped.

| Package | Version | License (metadata) | Pulled in by | Ship |
|---|---|---|---|---|
| absl-py | 2.5.1 | Apache-2.0 | mediapipe | runtime |
| altgraph | 0.17.5 | MIT | pyinstaller | dev |
| certifi | 2026.10.23 | MPL-2.0 | mediapipe | exclude (no network at runtime); if shipped: unmodified + MPL notice |
| cffi | 2.1.1 | MIT-0 | sounddevice | exclude |
| colorama | 0.4.6 | BSD-3-Clause | pytest | dev |
| comtypes | 1.5.0 | MIT | direct | runtime |
| contourpy | 1.3.3 | BSD-3-Clause | matplotlib | exclude |
| cycler | 0.12.1 | BSD-3-Clause | matplotlib | exclude |
| flatbuffers | 25.12.19 | Apache-2.0 | mediapipe | runtime |
| fonttools | 4.68.0 | MIT | matplotlib | exclude |
| iniconfig | 2.3.1 | MIT | pytest | dev |
| kiwisolver | 1.5.1 | BSD-3-Clause | matplotlib | exclude |
| matplotlib | 3.11.2 | PSF-based (matplotlib license) | mediapipe | exclude |
| mediapipe | 1.2.2 | Apache-2.0 | direct | runtime (bundles `libmediapipe.dll`) |
| numpy | 2.4.6 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 (bundles OpenBLAS BSD, gfortran runtime GPL-3 with GCC Runtime Library Exception) | mediapipe/opencv | runtime |
| opencv-contrib-python | 5.0.0.93 | Apache-2.0 (+ bundled FFmpeg **LGPL-2.1**, see below) | mediapipe | runtime |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | pytest/pyinstaller | dev |
| pefile | 2024.8.26 | MIT | pyinstaller | dev |
| pillow | 13.0.0 | MIT-CMU (HPND) | matplotlib | exclude |
| pluggy | 1.7.0 | MIT | pytest | dev |
| psutil | 7.2.2 | BSD-3-Clause | pycaw | runtime |
| pycaw | 20260927 | MIT | direct | runtime |
| pycparser | 3.12 | BSD-3-Clause | cffi | exclude |
| pygments | 2.21.0 | BSD-2-Clause | pytest | dev |
| pyinstaller | 6.22.3 | GPL-2.0-or-later **with bootloader exception** | direct (dev) | dev; the exception allows shipping the bootloader with any app |
| pyinstaller-hooks-contrib | 2026.10 | GPL-2.0 (hooks) / Apache-2.0 (runtime hooks) | pyinstaller | dev (only Apache-2.0 runtime hooks end up in the build) |
| pyparsing | 3.3.3 | MIT | matplotlib | exclude |
| PySide6-Essentials | 6.12.0 | **LGPL-3.0-only** OR GPL-2.0-only OR GPL-3.0-only (Qt for Python Community) | direct | runtime (only the modules below) |
| pytest | 9.2.0 | MIT | direct (dev) | dev |
| python-dateutil | 4.0.0 | BSD-3-Clause | matplotlib | exclude |
| pywin32-ctypes | 0.2.3 | BSD-3-Clause | pyinstaller | dev |
| setuptools | 84.2.1 | MIT | pyinstaller | dev |
| shiboken6 | 6.12.0 | **LGPL-3.0-only** OR GPL-2.0-only OR GPL-3.0-only | PySide6 | runtime |
| sounddevice | 0.5.6 | MIT (bundles PortAudio MIT; `*-asio.dll` variants also involve the Steinberg ASIO SDK) | mediapipe | exclude (never imported; do NOT ship `_sounddevice_data`) |
| tzdata | 2026.6 | Apache-2.0 | python-dateutil | exclude |

Plus the CPython 3.11 runtime embedded by PyInstaller: PSF License 2.0 (ship its LICENSE text).

## LGPL items (copyleft obligations for the one-folder build)

1. **Qt 6.12 via PySide6-Essentials + shiboken6 (LGPL-3.0)** — use only:
   QtCore, QtGui, QtWidgets, QtSvg (if needed), and the required plugins (`platforms/qwindows.dll`, `styles`, `imageformats`, `iconengines`).
   Do NOT ship: Designer/Designer components, QtHelp, Qt Quick/QML stack unless the UI really needs it, **Qt Lottie**,
   Qt Labs modules, and tool executables (`designer.exe`, `assistant.exe`, `linguist.exe`, `qml*.exe`, `uic.exe`, `rcc.exe`...).
   Reason: not all Qt modules share one license (some add-ons are GPL-3/commercial only, e.g. Qt Lottie — verify per module
   on doc.qt.io "Qt Licensing" before adding any module).
2. **FFmpeg inside OpenCV** (`cv2/opencv_videoio_ffmpeg500_64.dll`, LGPL-2.1) — the app captures through MSMF/DSHOW, not FFmpeg.
   Preferred: exclude this DLL from the build. If it is kept, treat it like Qt below.

What the one-folder distribution must ship for LGPL components:
- Keep them as separate, replaceable shared libraries (one-folder, no static linking, no one-file build for releases).
- `licenses/` folder with: LGPL-3.0 + GPL-3.0 texts (LGPL-3 references GPL-3), Qt and PySide6 license/notice files
  (`PySide6/` and `shiboken6/` dist-info LICENSE files), `cv2/LICENSE.txt` + `cv2/LICENSE-3RD-PARTY.txt` (includes FFmpeg LGPL-2.1),
  Apache-2.0 text + MediaPipe and model attribution, numpy/OpenBLAS/gfortran notices, PSF license, MIT/BSD texts of shipped packages.
- Source access info: exact versions and links to the corresponding source (Qt: download.qt.io / code.qt.io tag v6.12.0;
  PySide6/shiboken6: code.qt.io pyside-setup tag v6.12.0; FFmpeg: the source offer documented by opencv-python for 5.0.0.93),
  or ship the source archives. State that users may replace the Qt/PySide6 DLLs with their own builds.
- No license key, DRM, or anti-reverse-engineering terms that would block relinking/replacement.

## Pending

- Model SHA-256 independent review (see manifest) before release bundling.
- Per-module Qt license check when the UI module list is final (Antigravity owns UI).
- Generate the `licenses/` folder automatically at build time (Phase "packaging").
