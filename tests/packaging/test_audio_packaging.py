"""Offline checks for the Enstrüman audio packaging (sounddevice + PortAudio). No streams are opened."""
import importlib.util
import re
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _lock_block(name: str) -> str:
    text = (ROOT / "requirements.lock").read_text(encoding="utf-8")
    m = re.search(rf"^{re.escape(name)}==(.+?) [\\]\n(.*?)(?=^\S)", text, re.M | re.S)
    assert m, f"{name} missing from requirements.lock"
    return m.group(0)


def _load_entrypoint():
    spec = importlib.util.spec_from_file_location("hc_entrypoint", ROOT / "packaging" / "entrypoint.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_requirements_and_pyproject_pin_sounddevice():
    assert re.search(r"^sounddevice==0\.5\.6$", (ROOT / "requirements.txt").read_text(encoding="utf-8"), re.M)
    assert '"sounddevice==0.5.6"' in (ROOT / "pyproject.toml").read_text(encoding="utf-8")


def test_lock_lists_sounddevice_as_direct_with_hashes():
    block = _lock_block("sounddevice")
    assert block.startswith("sounddevice==0.5.6")
    assert "-r requirements.txt" in block
    assert len(re.findall(r"--hash=sha256:[0-9a-f]{64}", block)) == 6
    assert "cffi==" in (ROOT / "requirements.lock").read_text(encoding="utf-8")


def test_spec_hidden_imports_and_only_non_asio_dll():
    spec = (ROOT / "packaging" / "holoscobe.spec").read_text(encoding="utf-8")
    for name in ("sounddevice", "_cffi_backend", "handcontrol.instrument.audio", "handcontrol.instrument.synth"):
        assert f'"{name}"' in spec
    assert 'libportaudio64bit.dll"' in spec
    assert set(re.findall(r"libportaudio\w*\.(?:dll|dylib)", spec)) == {"libportaudio64bit.dll"}
    assert "_sounddevice_data/portaudio-binaries" in spec


def test_notices_document_bundled_portaudio():
    text = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert "Copyright (c) 1999-2011 Ross Bencina and Phil Burk" in text
    assert "libportaudio64bit.dll" in text


def test_audio_check_records_fields_without_opening_streams(monkeypatch):
    fake = types.SimpleNamespace(
        get_portaudio_version=lambda: (1970, "PortAudio V19.7.0 fake"),
        query_hostapis=lambda: [{"name": "MME"}, {"name": "Windows WASAPI"}],
        query_devices=lambda: [{"max_output_channels": 2}, {"max_output_channels": 0}],
    )
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    info = _load_entrypoint().audio_check()
    assert info == {"portaudio": "PortAudio V19.7.0 fake", "hostapis": ["MME", "Windows WASAPI"], "output_devices": 1}


def test_audio_check_zero_outputs_is_not_a_failure(monkeypatch):
    fake = types.SimpleNamespace(
        get_portaudio_version=lambda: (1970, "x"), query_hostapis=lambda: [], query_devices=lambda: [])
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    assert _load_entrypoint().audio_check()["output_devices"] == 0


def test_audio_check_real_portaudio_loads():
    info = _load_entrypoint().audio_check()
    assert "PortAudio" in info["portaudio"] and isinstance(info["hostapis"], list)


def test_self_test_ok_line_format_and_release_parser():
    src = (ROOT / "packaging" / "entrypoint.py").read_text(encoding="utf-8")
    assert "OK self-test hands={hands} frozen=" in src and "audio=ok outputs={outputs}" in src
    assert "-notlike 'OK*'" in (ROOT / "scripts" / "release.ps1").read_text(encoding="utf-8")
