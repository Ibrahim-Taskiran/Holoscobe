from __future__ import annotations

import json
import os

import pytest

from handcontrol import config as C
from handcontrol.config import Settings, SettingsStore, validate


def test_defaults():
    s = Settings()
    assert s.schema_version == 1 and s.emergency_hotkey == "Ctrl+Alt+Shift+F12"
    assert s.start_with_windows is False
    assert (s.camera.width, s.camera.height, s.camera.fps) == (640, 480, 30)


def test_missing_file_gives_defaults(settings_path):
    assert SettingsStore(settings_path).load() == Settings()


def test_round_trip_unicode_path(settings_path):
    st = SettingsStore(settings_path)
    s = Settings()
    s.camera.index = 2
    s.camera.backend = "dshow"
    s.mirror_preview = False
    s.dominant_hand = "left"
    s.sensitivity = 1.7
    s.default_mode = "scroll"
    s.monitor_mapping.mode = "monitor"
    s.monitor_mapping.monitor_index = 1
    s.calibration.left = 0.2
    s.emergency_hotkey = "Ctrl+Alt+Ş"
    s.start_with_windows = True
    st.save(s)
    assert settings_path.exists()
    assert st.load() == s
    assert "Ş" in settings_path.read_text(encoding="utf-8")   # ensure_ascii off


def test_clamping_and_bad_types():
    s = validate({
        "camera": {"index": -5, "backend": "weird", "width": 99999, "fps": "x"},
        "sensitivity": 99, "pinch_on_threshold": -1, "dominant_hand": "both",
        "scroll_direction": 3, "default_mode": "fly", "emergency_hotkey": "",
        "mirror_preview": "yes", "start_with_windows": 1,
        "calibration": {"left": 0.8, "right": 0.82},
    })
    assert s.camera.index == 0 and s.camera.backend == "msmf"
    assert s.camera.width == 3840 and s.camera.fps == 30
    assert s.sensitivity == 3.0
    assert s.pinch_on_threshold == 0.05 and s.pinch_off_threshold > s.pinch_on_threshold
    assert s.dominant_hand == "right" and s.scroll_direction == "normal" and s.default_mode == "pointer"
    assert s.emergency_hotkey == "Ctrl+Alt+Shift+F12"
    assert s.mirror_preview is True and s.start_with_windows is False
    c = s.calibration
    assert c.right - c.left >= 0.1


def test_pinch_hysteresis_enforced():
    s = validate({"pinch_on_threshold": 0.6, "pinch_off_threshold": 0.4})
    assert s.pinch_off_threshold > s.pinch_on_threshold


def test_unknown_keys_ignored(settings_path):
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(json.dumps({"schema_version": 1, "future_thing": 1, "camera": {"index": 1, "zzz": 2}}), encoding="utf-8")
    s = SettingsStore(settings_path).load()
    assert s.camera.index == 1 and not hasattr(s, "future_thing")


@pytest.mark.parametrize("content", [b"{not json", b"", b"[1,2]", b"\xff\xfe\x00bad", b'"str"'])
def test_corrupt_file_recovery(settings_path, content):
    settings_path.parent.mkdir(parents=True)
    settings_path.write_bytes(content)
    st = SettingsStore(settings_path, clock=lambda: 1_700_000_000.123)
    assert st.load() == Settings()
    copies = list(settings_path.parent.glob("settings.corrupt-*.json"))
    assert len(copies) == 1 and st.last_recovery == copies[0]
    assert copies[0].read_bytes() == content


def test_atomic_save_failure_keeps_old_file(settings_path, monkeypatch):
    st = SettingsStore(settings_path)
    s = Settings()
    s.sensitivity = 2.0
    st.save(s)
    old = settings_path.read_bytes()

    def boom(a, b):
        raise OSError("disk")
    monkeypatch.setattr(os, "replace", boom)
    s2 = Settings()
    s2.sensitivity = 0.5
    with pytest.raises(OSError):
        st.save(s2)
    monkeypatch.undo()
    assert settings_path.read_bytes() == old
    assert [p.name for p in settings_path.parent.iterdir()] == ["settings.json"]   # temp cleaned


def test_save_uses_same_dir_temp_and_fsync(settings_path, monkeypatch):
    calls = {"fsync": 0, "replace": None}
    real_fsync, real_replace = os.fsync, os.replace
    monkeypatch.setattr(os, "fsync", lambda fd: (calls.__setitem__("fsync", calls["fsync"] + 1), real_fsync(fd))[1])
    monkeypatch.setattr(os, "replace", lambda a, b: (calls.__setitem__("replace", (a, b)), real_replace(a, b))[1])
    SettingsStore(settings_path).save(Settings())
    src, dst = calls["replace"]
    assert calls["fsync"] >= 1
    assert os.path.dirname(src) == os.path.dirname(str(dst)) and str(dst) == str(settings_path)


def test_migration_hook(settings_path, monkeypatch):
    monkeypatch.setattr(C, "SCHEMA_VERSION", 2)
    monkeypatch.setitem(C.MIGRATIONS, 1, lambda d: {**d, "sensitivity": d.get("old_sens", 1.0) * 2})
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(json.dumps({"schema_version": 1, "old_sens": 0.75}), encoding="utf-8")
    s = SettingsStore(settings_path).load()
    assert s.sensitivity == 1.5


def test_bad_schema_version_treated_as_v1(settings_path):
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(json.dumps({"schema_version": "x", "sensitivity": 2}), encoding="utf-8")
    assert SettingsStore(settings_path).load().sensitivity == 2.0


def test_default_path_uses_localappdata(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Yerel Veri"))
    assert C.default_settings_path() == tmp_path / "Yerel Veri" / "Holoscobe" / "settings.json"
