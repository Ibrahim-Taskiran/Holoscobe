"""Versioned settings stored as JSON under %LOCALAPPDATA%\\Holoscobe\\settings.json.

Validation clamps ranges, ignores unknown keys, migrates by schema_version, saves atomically and
recovers from corrupt files by keeping a diagnostic copy and loading safe defaults.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Callable, Optional

from handcontrol.instrument.events import (
    CHORD_NAMES, DEFAULT_CHORDS, DEFAULT_FIXED_RECT, DEFAULT_FIXED_STRINGS, FIXED_STRINGS_RANGE, LATENCIES, LAYOUTS,
    SCALE_NAMES, TONES,
)
from handcontrol.instrument.freeform import normalize_free_strings
from handcontrol.instrument.geometry import normalize_fixed_rect

SCHEMA_VERSION = 4
APP_DIR_NAME = "Holoscobe"
SETTINGS_FILE = "settings.json"

BACKENDS = ("msmf", "dshow", "auto")
HANDS = ("right", "left")
DIRECTIONS = ("normal", "reversed")
MODES = ("pointer", "scroll", "zoom", "volume", "windows", "commands", "instrument", "drawing")
MONITOR_MODES = ("primary", "virtual_desktop", "monitor")
POINTER_MODES = ("relative", "absolute")
SWIPE_PROFILES = ("auto", "slides", "browser", "media", "desktops")
PINCH_ON_DEFAULT, PINCH_OFF_DEFAULT = 0.33, 0.48
# (on, off) pairs that were written as defaults by schema 1 (settings defaults and the dialog defaults)
_V1_DEFAULT_PINCH = ((0.30, 0.45), (0.28, 0.42))
DEFAULT_HOTKEY = "Ctrl+Alt+Shift+F12"
_HOTKEY_MODS = ("Ctrl", "Alt", "Shift", "Win")


def normalize_hotkey(value) -> str:
    """Canonical "Ctrl+Alt+Shift+Win+KEY" or DEFAULT_HOTKEY; needs Ctrl/Alt/Win and exactly one F1-F24/A-Z/0-9 key."""
    if not isinstance(value, str) or not 0 < len(value.strip()) <= 64:
        return DEFAULT_HOTKEY
    tokens = [t.strip().upper() for t in value.split("+")]
    key = tokens[-1]
    mods = {t for t in tokens[:-1]}
    names = {m.upper(): m for m in _HOTKEY_MODS}
    if len(mods) != len(tokens) - 1 or not mods <= set(names) or not mods & {"CTRL", "ALT", "WIN"}:
        return DEFAULT_HOTKEY
    is_f = key.startswith("F") and key[1:].isdigit() and key[1:].isascii() and 1 <= int(key[1:]) <= 24 and key[1:] == str(int(key[1:]))
    if not (is_f or (len(key) == 1 and key.isascii() and key.isalnum())):
        return DEFAULT_HOTKEY
    return "+".join([m for m in _HOTKEY_MODS if m.upper() in mods] + [key])


@dataclass
class CameraSettings:
    index: int = 0
    backend: str = "msmf"
    width: int = 640
    height: int = 480
    fps: int = 30


@dataclass
class MonitorMapping:
    mode: str = "virtual_desktop"
    monitor_index: int = 0


@dataclass
class CalibrationBounds:
    """Active region of the camera frame (normalized, unmirrored) mapped to the screen."""
    left: float = 0.15
    top: float = 0.15
    right: float = 0.85
    bottom: float = 0.85


@dataclass
class Settings:
    schema_version: int = SCHEMA_VERSION
    camera: CameraSettings = field(default_factory=CameraSettings)
    mirror_preview: bool = True
    dominant_hand: str = "right"
    pinch_on_threshold: float = PINCH_ON_DEFAULT    # palm units: pinch starts below this
    pinch_off_threshold: float = PINCH_OFF_DEFAULT  # palm units: pinch ends above this (hysteresis)
    sensitivity: float = 1.0
    pointer_mode: str = "relative"        # "relative" (clutch + acceleration) | "absolute" (calibration rect)
    pointer_speed: float = 1.0            # relative pointer speed multiplier, 0.5..2.0
    scroll_direction: str = "normal"
    zoom_direction: str = "normal"
    default_mode: str = "pointer"
    emergency_hotkey: str = DEFAULT_HOTKEY
    overlay_visible: bool = True
    mascot_visible: bool = True
    monitor_mapping: MonitorMapping = field(default_factory=MonitorMapping)
    calibration: CalibrationBounds = field(default_factory=CalibrationBounds)
    start_with_windows: bool = False
    # schema 3 (round 6)
    swipe_profile: str = "auto"           # Komutlar mode swipe meaning; "auto" picks by foreground app
    auto_pause_s: int = 0                 # pause after this many seconds without a usable hand; 0 = off
    dwell_click: bool = False             # left click when the engaged cursor rests still for dwell_ms
    dwell_ms: int = 1000
    click_sound: bool = False             # short system sound on click/command
    cursor_feedback: bool = True          # progress ring next to the cursor for hold gestures
    onboarding_done: bool = False         # first-run tutorial finished or skipped
    # schema 4 (round 7, Enstrüman mode)
    instrument_layout: str = "free"       # "free" (user draws) | "fixed" | "solo" (length = pitch) | "chord"
    instrument_scale: str = "e_minor_pentatonic"
    instrument_quantize: bool = True      # True: pitch locked to the scale; False: continuous
    instrument_chords: list[str] = field(default_factory=lambda: list(DEFAULT_CHORDS))   # 4 vertical zones, top first
    instrument_volume: float = 0.5        # 0..1
    instrument_tone: str = "clean"        # "clean" | "electric"
    audio_device: str = ""                # output device name; "" = system default
    audio_latency: str = "low"            # "low" | "normal"
    instrument_particles: bool = True     # spark particles in the Enstrüman window
    # "fixed" layout: string area (normalized x0, y0, x1, y1 on the unmirrored frame) and string count
    instrument_fixed_rect: list[float] = field(default_factory=lambda: list(DEFAULT_FIXED_RECT))
    instrument_fixed_strings: int = DEFAULT_FIXED_STRINGS
    # "free" layout: the user's own strings (normalized x0, y0, x1, y1 each) and optional snapping
    instrument_free_strings: list[list[float]] = field(default_factory=list)
    instrument_free_snap: bool = True


# ---------- validation helpers ----------

def _num(v: Any, default: float, lo: float, hi: float) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:
        return default
    return min(hi, max(lo, float(v)))


def _int(v: Any, default: int, lo: int, hi: int) -> int:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:
        return default
    return int(min(hi, max(lo, round(v))))


def _bool(v: Any, default: bool) -> bool:
    return v if isinstance(v, bool) else default


def _choice(v: Any, options: tuple[str, ...], default: str) -> str:
    if isinstance(v, str) and v.lower() in options:
        return v.lower()
    return default


def _dict(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _exact(v: Any, options: tuple[str, ...], default: str) -> str:
    """Case-sensitive choice (chord and scale names)."""
    return v if isinstance(v, str) and v in options else default


def _chords(v: Any) -> list[str]:
    """Exactly four known chord names; a bad entry falls back to the default chord of its zone."""
    items = v if isinstance(v, (list, tuple)) else []
    return [_exact(items[i] if i < len(items) else None, CHORD_NAMES, DEFAULT_CHORDS[i]) for i in range(4)]


_CHOICES: dict[str, tuple[str, ...]] = {
    "dominant_hand": HANDS, "pointer_mode": POINTER_MODES, "scroll_direction": DIRECTIONS, "zoom_direction": DIRECTIONS,
    "default_mode": MODES, "swipe_profile": SWIPE_PROFILES, "instrument_layout": LAYOUTS, "instrument_tone": TONES,
    "audio_latency": LATENCIES,
}
_RANGES: dict[str, tuple[float, float]] = {
    "pinch_on_threshold": (0.05, 1.5), "pinch_off_threshold": (0.05, 2.0), "sensitivity": (0.2, 3.0),
    "pointer_speed": (0.5, 2.0), "auto_pause_s": (0, 3600), "dwell_ms": (400, 3000), "instrument_volume": (0.0, 1.0),
    "instrument_fixed_strings": FIXED_STRINGS_RANGE,
}


def validate(data: Any) -> Settings:
    """Build a valid Settings from arbitrary data; bad values fall back to defaults, ranges clamp."""
    d = _dict(data)
    s = Settings()
    c, cd = s.camera, _dict(d.get("camera"))
    c.index = _int(cd.get("index"), c.index, 0, 16)
    c.backend = _choice(cd.get("backend"), BACKENDS, c.backend)
    c.width = _int(cd.get("width"), c.width, 160, 3840)
    c.height = _int(cd.get("height"), c.height, 120, 2160)
    c.fps = _int(cd.get("fps"), c.fps, 5, 120)

    for f in fields(s):
        default = getattr(s, f.name)
        if isinstance(default, bool):
            setattr(s, f.name, _bool(d.get(f.name), default))
    for name, options in _CHOICES.items():
        setattr(s, name, _choice(d.get(name), options, getattr(s, name)))
    for name, (lo, hi) in _RANGES.items():
        default = getattr(s, name)
        setattr(s, name, (_int if isinstance(default, int) else _num)(d.get(name), default, lo, hi))
    if s.pinch_off_threshold <= s.pinch_on_threshold:  # hysteresis must be real
        s.pinch_off_threshold = min(2.0, s.pinch_on_threshold + 0.05)
        if s.pinch_off_threshold <= s.pinch_on_threshold:
            s.pinch_on_threshold = s.pinch_off_threshold - 0.05
    s.emergency_hotkey = normalize_hotkey(d.get("emergency_hotkey"))
    if 0 < s.auto_pause_s < 10:
        s.auto_pause_s = 10
    s.instrument_scale = _exact(d.get("instrument_scale"), SCALE_NAMES, s.instrument_scale)
    s.instrument_chords = _chords(d.get("instrument_chords"))
    dev = d.get("audio_device")
    s.audio_device = dev.strip()[:200] if isinstance(dev, str) else ""
    s.instrument_fixed_rect = list(normalize_fixed_rect(d.get("instrument_fixed_rect"), DEFAULT_FIXED_RECT))
    s.instrument_free_strings = [list(x) for x in normalize_free_strings(d.get("instrument_free_strings") or ())]

    m, md = s.monitor_mapping, _dict(d.get("monitor_mapping"))
    m.mode = _choice(md.get("mode"), MONITOR_MODES, m.mode)
    m.monitor_index = _int(md.get("monitor_index"), m.monitor_index, 0, 15)

    b, bd = s.calibration, _dict(d.get("calibration"))
    left = _num(bd.get("left"), b.left, 0.0, 0.9)
    top = _num(bd.get("top"), b.top, 0.0, 0.9)
    right = _num(bd.get("right"), b.right, 0.1, 1.0)
    bottom = _num(bd.get("bottom"), b.bottom, 0.1, 1.0)
    if right - left < 0.1 or bottom - top < 0.1:  # degenerate region -> defaults
        left, top, right, bottom = b.left, b.top, b.right, b.bottom
    b.left, b.top, b.right, b.bottom = left, top, right, bottom
    return s


# ---------- migration ----------

def _migrate_v1(data: dict[str, Any]) -> dict[str, Any]:
    """Schema 1 -> 2 (relative pointer). Schema 1 saved its defaults explicitly, so values equal to
    an old default are treated as never chosen: monitor mode "primary" (which kept the pointer off
    the other monitors) becomes "virtual_desktop", and the old default pinch thresholds become the
    new, wider ones. Other values are kept."""
    md = data.get("monitor_mapping")
    if isinstance(md, dict) and md.get("mode") == "primary":
        data["monitor_mapping"] = {**md, "mode": "virtual_desktop"}
    on, off = data.get("pinch_on_threshold"), data.get("pinch_off_threshold")
    if any(on == a and off == b for a, b in _V1_DEFAULT_PINCH):
        data["pinch_on_threshold"], data["pinch_off_threshold"] = PINCH_ON_DEFAULT, PINCH_OFF_DEFAULT
    return data


# Maps a stored schema_version to a function upgrading its dict to version + 1.
def _migrate_v2(data: dict[str, Any]) -> dict[str, Any]:
    """Schema 2 -> 3: new fields only. An existing user has already used the app, so skip onboarding."""
    data.setdefault("onboarding_done", True)
    return data


# Schema 3 -> 4 only added fields: validate() fills their defaults.
MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {1: _migrate_v1, 2: _migrate_v2}


def migrate(data: dict[str, Any]) -> dict[str, Any]:
    version = data.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        version = 1
    while version < SCHEMA_VERSION:
        step = MIGRATIONS.get(version)
        if step is not None:
            data = step(dict(data))
        version += 1
        data["schema_version"] = version
    return data


# ---------- storage ----------

def default_settings_path() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Local"
    return root / APP_DIR_NAME / SETTINGS_FILE


class SettingsStore:
    def __init__(self, path: Optional[str | os.PathLike[str]] = None, *, clock: Optional[Callable[[], float]] = None) -> None:
        self.path = Path(path) if path else default_settings_path()
        self._time = clock or time.time
        self.last_recovery: Optional[Path] = None   # diagnostic copy made by the last load, if any

    def load(self) -> Settings:
        """Load settings; missing file -> defaults. Corrupt/unreadable -> diagnostic copy + defaults."""
        self.last_recovery = None
        if not self.path.exists():
            return Settings()
        try:
            raw = self.path.read_bytes()
            data = json.loads(raw.decode("utf-8-sig"))
            if not isinstance(data, dict):
                raise ValueError("settings root is not an object")
        except (OSError, ValueError):  # JSONDecodeError and UnicodeDecodeError are ValueErrors
            self._keep_diagnostic_copy()
            return Settings()
        return validate(migrate(data))

    def _keep_diagnostic_copy(self) -> None:
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(self._time()))
        ms = int((self._time() % 1) * 1000)
        target = self.path.with_name(f"settings.corrupt-{stamp}-{ms:03d}.json")
        try:
            shutil.copy2(self.path, target)
            self.last_recovery = target
        except OSError:
            self.last_recovery = None

    def save(self, settings: Settings) -> None:
        """Atomic write: temp file in the same directory, fsync, os.replace."""
        valid = validate(asdict(settings))
        valid.schema_version = SCHEMA_VERSION
        payload = json.dumps(asdict(valid), indent=2, ensure_ascii=False).encode("utf-8")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".settings-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
