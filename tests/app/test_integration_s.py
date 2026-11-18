from __future__ import annotations

import json
import logging
import os
import sys
import threading
import zipfile
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QApplication

from handcontrol import diagnostics, logsetup
from handcontrol.app import (Runtime, TapSink, acquire_single_instance, extend_controller_config,
    settings_to_dialog_data, sound_kind_for)
from handcontrol.config import Settings, SettingsStore, validate
from handcontrol.contracts import Action, ActionKind
from handcontrol.controller import ControllerConfig
from handcontrol.dryrun import FakeDisplays, FakeVolume, FakeWindows
from handcontrol.ui import UiBridge


@pytest.fixture
def qt():
    return QApplication.instance() or QApplication([])


def make(qt, tmp_path, settings=None, **kw) -> Runtime:
    displays = FakeDisplays()
    displays.start = Mock()
    displays.close = Mock()
    store = SettingsStore(tmp_path / 'settings.json')
    if settings is not None:
        store.save(settings)
    r = Runtime(UiBridge(), store, displays=displays, windows=FakeWindows(), volume=FakeVolume(),
        session_factory=Mock(), hotkey_factory=Mock(), startup=SimpleNamespace(is_enabled=lambda: False,
        set_enabled=lambda v: True), packaged=True, process_names=object(), **kw)
    r.bridge.show_feedback = Mock()
    return r


# ---- mapping

def test_controller_config_gets_schema3_fields() -> None:
    cfg = extend_controller_config(ControllerConfig(), validate({'auto_pause_s': 5, 'dwell_click': True,
        'dwell_ms': 800, 'swipe_profile': 'media'}))
    names = set(ControllerConfig.__dataclass_fields__)
    if 'auto_pause_ms' in names:
        assert cfg.auto_pause_ms == 5000.0
    if 'dwell_ms' in names:
        assert cfg.dwell_ms == 800.0 and cfg.dwell_click is True and cfg.swipe_profile == 'media'


def test_dialog_data_carries_known_schema3_fields() -> None:
    d = settings_to_dialog_data(validate({'click_sound': True, 'auto_pause_s': 10}))
    if hasattr(d, 'click_sound'):
        assert d.click_sound is True and d.auto_pause_s == 10


def test_save_settings_writes_schema3_fields(qt, tmp_path) -> None:
    r = make(qt, tmp_path)
    data = SimpleNamespace(**{**vars(settings_to_dialog_data(r.settings)), 'click_sound': True,
        'dwell_click': True, 'dwell_ms': 900, 'auto_pause_s': 10, 'swipe_profile': 'slides', 'cursor_feedback': False})
    r.save_settings(data)
    s = r.store.load()
    assert (s.click_sound, s.dwell_click, s.dwell_ms, s.auto_pause_s, s.swipe_profile, s.cursor_feedback) == (
        True, True, 900, 10, 'slides', False)
    r.close()


# ---- tap sink

def act(kind=ActionKind.LEFT_CLICK, x=3, y=4):
    return Action(kind, 0, 0.0, x=x, y=y)


def test_tap_reports_success_only() -> None:
    seen = []
    ok = TapSink(SimpleNamespace(dispatch=lambda a: True), lambda *a: seen.append(a))
    bad = TapSink(SimpleNamespace(dispatch=lambda a: False), lambda *a: seen.append(a))
    assert ok.dispatch(act()) is True and bad.dispatch(act()) is False
    assert seen == [('left_click', 3, 4)]


def test_tap_forwards_attributes_and_survives_listener_error() -> None:
    inner = SimpleNamespace(dispatch=lambda a: True, release_all=Mock())

    def boom(*a):
        raise RuntimeError
    tap = TapSink(inner, boom)
    assert tap.dispatch(act()) is True
    tap.release_all()
    inner.release_all.assert_called_once()


def test_sound_kinds() -> None:
    assert sound_kind_for('right_click') == 'click' and sound_kind_for('key_command') == 'command'
    assert sound_kind_for('scroll') is None


def test_runtime_actions_reach_listener_and_sound(qt, tmp_path) -> None:
    played, heard = [], []
    r = make(qt, tmp_path, replace(Settings(), click_sound=True), sound_player=played.append)
    r.add_action_listener(lambda *a: heard.append(a))
    t = threading.Thread(target=lambda: r.action_performed.emit('left_click', 1, 2))
    t.start()
    t.join()
    qt.processEvents()
    assert heard == [('left_click', 1, 2)] and played == ['click']
    r.close()


def test_no_sound_when_disabled(qt, tmp_path) -> None:
    played = []
    r = make(qt, tmp_path, sound_player=played.append)
    r.action_performed.emit('left_click', 0, 0)
    qt.processEvents()
    assert played == []
    r.close()


# ---- import / export

def test_export_then_import_round_trip(qt, tmp_path) -> None:
    r = make(qt, tmp_path, replace(Settings(), sensitivity=1.5, click_sound=True))
    out = tmp_path / 'out.json'
    assert r.export_settings(out)
    assert json.loads(out.read_text(encoding='utf-8'))['sensitivity'] == 1.5
    r.close()
    (tmp_path / 'b').mkdir()
    r2 = make(qt, tmp_path / 'b')
    assert r2.import_settings(out)
    assert r2.settings.sensitivity == 1.5 and r2.store.load().click_sound is True
    r2.close()


def test_import_migrates_old_schema(qt, tmp_path) -> None:
    r = make(qt, tmp_path)
    f = tmp_path / 'old.json'
    f.write_text(json.dumps({'schema_version': 1, 'sensitivity': 2.0}), encoding='utf-8')
    assert r.import_settings(f) and r.settings.sensitivity == 2.0
    r.close()


def test_import_bad_file_reports_turkish_error(qt, tmp_path) -> None:
    r = make(qt, tmp_path)
    f = tmp_path / 'bad.json'
    f.write_text('not json', encoding='utf-8')
    before = r.settings
    assert r.import_settings(f) is False and r.settings is before
    assert 'içe aktarılamadı' in r.bridge.show_feedback.call_args.kwargs['message']
    assert r.import_settings(tmp_path / 'missing.json') is False
    r.close()


def test_onboarding_flag_saved(qt, tmp_path) -> None:
    r = make(qt, tmp_path)
    r.mark_onboarding_done()
    assert r.store.load().onboarding_done is True and r.settings.onboarding_done
    r.close()


# ---- diagnostics

def test_diagnostics_zip_contents(tmp_path) -> None:
    settings = tmp_path / 'settings.json'
    settings.write_text('{}')
    logs = tmp_path / 'logs'
    logs.mkdir()
    (logs / 'holoscobe.log').write_text('x')
    (logs / 'shot.png').write_bytes(b'img')
    tel = tmp_path / 'tel'
    tel.mkdir()
    for i in range(5):
        p = tel / f'session_{i}.csv'
        p.write_text('a')
        os.utime(p, (1.7e9 + i, 1.7e9 + i))
    out = diagnostics.build_diagnostics_zip(tmp_path / 'dest', settings_path=settings, logs_dir=logs,
        telemetry_dir=tel, extra={'Monitörler': ['a', 'b'], 'Kamera': 'index=0'})
    assert out.name.startswith('Holoscobe-tanilama-') and out.suffix == '.zip'
    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
        assert {'settings.json', 'logs/holoscobe.log', 'system.txt'} <= names
        assert {n for n in names if n.startswith('telemetry/')} == {f'telemetry/session_{i}.csv' for i in (4, 3, 2)}
        assert not any(n.endswith('.png') for n in names)
        text = z.read('system.txt').decode('utf-8')
        assert 'Python:' in text and 'mediapipe' in text and 'Kamera: index=0' in text


def test_runtime_build_diagnostics(qt, tmp_path) -> None:
    r = make(qt, tmp_path, logs_dir=tmp_path / 'logs')
    out = r.build_diagnostics(tmp_path / 'dest')
    assert out and out.exists()
    r.close()


# ---- logging

def test_logsetup_writes_and_cleans_up(tmp_path) -> None:
    root = logging.getLogger()
    before, level = list(root.handlers), root.level
    try:
        path = logsetup.setup_logging(tmp_path / 'logs', 'DEBUG', install_hooks=False)
        logging.getLogger('t').info('merhaba ğüş')
        for h in root.handlers:
            h.flush()
        assert 'merhaba ğüş' in path.read_text(encoding='utf-8')
        logsetup.setup_logging(tmp_path / 'logs', install_hooks=False)
        assert len([h for h in root.handlers if h not in before]) == 1
    finally:
        logsetup.teardown_logging()
        root.setLevel(level)
    assert root.handlers == before


def test_excepthooks_log_and_notify(tmp_path) -> None:
    root = logging.getLogger()
    old_hook, old_thread, level = sys.excepthook, threading.excepthook, root.level
    notes = []
    try:
        path = logsetup.setup_logging(tmp_path, notify=notes.append)

        def work():
            raise ValueError('thread boom')
        t = threading.Thread(target=work)
        t.start()
        t.join()
        try:
            raise KeyError('main boom')
        except KeyError:
            sys.excepthook(*sys.exc_info())
        for h in root.handlers:
            h.flush()
        text = path.read_text(encoding='utf-8')
        assert 'thread boom' in text and 'main boom' in text and len(notes) == 2
    finally:
        logsetup.teardown_logging()
        sys.excepthook, threading.excepthook = old_hook, old_thread
        root.setLevel(level)


# ---- single instance

def test_single_instance_lock(tmp_path) -> None:
    first = acquire_single_instance(tmp_path)
    assert first is not None
    assert acquire_single_instance(tmp_path) is None
    first.unlock()
    again = acquire_single_instance(tmp_path)
    assert again is not None
    again.unlock()
