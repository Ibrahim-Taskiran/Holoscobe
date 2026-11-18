from __future__ import annotations

import json
import os

import pytest

from handcontrol import config as C
from handcontrol.config import Settings, SettingsStore, validate


def test_defaults():
    s = Settings()
    assert s.schema_version == C.SCHEMA_VERSION == 3 and s.emergency_hotkey == "Ctrl+Alt+Shift+F12"
    assert s.pointer_mode == "relative" and s.pointer_speed == 1.0
    assert s.monitor_mapping.mode == "virtual_desktop"
    assert (s.pinch_on_threshold, s.pinch_off_threshold) == (0.33, 0.48)
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


@pytest.mark.parametrize("on,off", [(0.28, 0.42), (0.30, 0.45)])
def test_v1_file_with_old_defaults_migrates_to_relative_pointer_defaults(settings_path, on, off):
    """Schema 1 wrote its defaults explicitly; 'primary' kept the pointer off the second monitor."""
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(json.dumps({
        "schema_version": 1, "monitor_mapping": {"mode": "primary", "monitor_index": 0},
        "pinch_on_threshold": on, "pinch_off_threshold": off, "sensitivity": 1.4,
        "calibration": {"left": 0.2, "top": 0.15, "right": 0.85, "bottom": 0.85}}), encoding="utf-8")
    s = SettingsStore(settings_path).load()
    assert s.monitor_mapping.mode == "virtual_desktop"
    assert (s.pinch_on_threshold, s.pinch_off_threshold) == (0.33, 0.48)
    assert s.sensitivity == 1.4 and s.calibration.left == 0.2 and s.pointer_mode == "relative"


def test_v1_migration_keeps_customized_values(settings_path):
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(json.dumps({
        "schema_version": 1, "monitor_mapping": {"mode": "monitor", "monitor_index": 1},
        "pinch_on_threshold": 0.25, "pinch_off_threshold": 0.45}), encoding="utf-8")
    s = SettingsStore(settings_path).load()
    assert (s.monitor_mapping.mode, s.monitor_mapping.monitor_index) == ("monitor", 1)
    assert (s.pinch_on_threshold, s.pinch_off_threshold) == (0.25, 0.45)


def test_v2_primary_is_kept(settings_path):
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(json.dumps({"schema_version": 2, "monitor_mapping": {"mode": "primary"}}),
                             encoding="utf-8")
    assert SettingsStore(settings_path).load().monitor_mapping.mode == "primary"


def test_pointer_settings_validation_and_round_trip(settings_path):
    s = validate({"pointer_mode": "ABSOLUTE", "pointer_speed": 9})
    assert s.pointer_mode == "absolute" and s.pointer_speed == 2.0
    s = validate({"pointer_mode": "warp", "pointer_speed": 0.1})
    assert s.pointer_mode == "relative" and s.pointer_speed == 0.5
    assert validate({"pointer_speed": "fast"}).pointer_speed == 1.0
    assert validate({"pointer_speed": True}).pointer_speed == 1.0
    st = SettingsStore(settings_path)
    s = Settings()
    s.pointer_speed = 1.6
    s.pointer_mode = "absolute"
    st.save(s)
    loaded = st.load()
    assert loaded.pointer_speed == 1.6 and loaded.pointer_mode == "absolute"
    assert json.loads(settings_path.read_text(encoding="utf-8"))["schema_version"] == C.SCHEMA_VERSION


def test_bad_schema_version_treated_as_v1(settings_path):
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(json.dumps({"schema_version": "x", "sensitivity": 2}), encoding="utf-8")
    assert SettingsStore(settings_path).load().sensitivity == 2.0


def test_default_path_uses_localappdata(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Yerel Veri"))
    assert C.default_settings_path() == tmp_path / "Yerel Veri" / "Holoscobe" / "settings.json"


# ---------- schema 3 (round 6) ----------

def test_schema3_defaults_and_clamps():
    from handcontrol.config import validate
    s = validate({})
    assert (s.swipe_profile, s.auto_pause_s, s.dwell_click, s.dwell_ms) == ("auto", 0, False, 1000)
    assert s.cursor_feedback and not s.click_sound and not s.onboarding_done
    s = validate({"swipe_profile": "SLIDES", "auto_pause_s": 3, "dwell_ms": 50, "default_mode": "commands"})
    assert (s.swipe_profile, s.auto_pause_s, s.dwell_ms, s.default_mode) == ("slides", 10, 400, "commands")
    assert validate({"swipe_profile": "bogus", "auto_pause_s": 99999}).swipe_profile == "auto"
    assert validate({"auto_pause_s": 99999}).auto_pause_s == 3600


def test_schema2_file_migrates_with_onboarding_done(tmp_path):
    import json
    from handcontrol.config import SCHEMA_VERSION, SettingsStore
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"schema_version": 2, "pointer_speed": 1.5}), encoding="utf-8")
    s = SettingsStore(p).load()
    assert s.onboarding_done is True and s.pointer_speed == 1.5 and s.schema_version == SCHEMA_VERSION == 3
    assert SettingsStore(tmp_path / "new.json").load().onboarding_done is False
