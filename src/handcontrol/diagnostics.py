"""Diagnostics bundle: settings, logs, recent telemetry, system info. Never images."""
from __future__ import annotations

import os
import platform
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Optional

PACKAGES = ("mediapipe", "opencv-contrib-python", "PySide6-Essentials")


def default_dest_dir() -> Path:
    desktop = Path.home() / "Desktop"
    return desktop if desktop.is_dir() else Path.home()


def _package_versions() -> dict[str, str]:
    from importlib import metadata
    out = {}
    for name in PACKAGES:
        try:
            out[name] = metadata.version(name)
        except Exception:
            out[name] = "yok"
    return out


def system_text(extra: Optional[Mapping[str, Any]] = None) -> str:
    lines = [f"Windows: {platform.platform()} ({platform.version()})",
             f"Python: {sys.version.split()[0]}"]
    lines += [f"{k}: {v}" for k, v in _package_versions().items()]
    for key, value in (extra or {}).items():
        if isinstance(value, (list, tuple)):
            lines.append(f"{key}:")
            lines += [f"  - {item}" for item in value]
        else:
            lines.append(f"{key}: {value}")
    return "\n".join(lines) + "\n"


def _add(z: zipfile.ZipFile, path: Path, name: str) -> None:
    try:
        z.write(path, name)
    except ValueError:  # mtime before 1980
        z.writestr(name, Path(path).read_bytes())


def build_diagnostics_zip(dest_dir: Optional[Path] = None, *, settings_path: Optional[Path] = None,
                          logs_dir: Optional[Path] = None, telemetry_dir: Optional[Path] = None,
                          extra: Optional[Mapping[str, Any]] = None, now: Optional[datetime] = None) -> Path:
    dest = Path(dest_dir) if dest_dir is not None else default_dest_dir()
    dest.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    out = dest / f"Holoscobe-tanilama-{stamp}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        if settings_path and Path(settings_path).is_file():
            _add(z, Path(settings_path), "settings.json")
        if logs_dir and Path(logs_dir).is_dir():
            for f in sorted(Path(logs_dir).glob("holoscobe.log*")):
                if f.is_file():
                    _add(z, f, f"logs/{f.name}")
        if telemetry_dir and Path(telemetry_dir).is_dir():
            files = [f for f in Path(telemetry_dir).glob("session_*.csv") if f.is_file()]
            for f in sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[:3]:
                _add(z, f, f"telemetry/{f.name}")
        z.writestr("system.txt", system_text(extra))
    return out
