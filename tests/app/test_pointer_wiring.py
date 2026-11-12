"""Round 4: real-cursor source wiring and pointer mode/speed mapping between dialog and Settings."""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QApplication

import handcontrol.app as app
from handcontrol.app import Runtime, read_os_cursor, settings_to_dialog_data
from handcontrol.config import Settings, validate
from handcontrol.dryrun import FakeDisplays, FakeVolume, FakeWindows
from handcontrol.ui import UiBridge


@pytest.fixture
def qt():
    return QApplication.instance() or QApplication([])


def make(qt, **kwargs) -> Runtime:
    displays = FakeDisplays()
    displays.start = Mock()
    displays.close = Mock()
    return Runtime(UiBridge(), SimpleNamespace(load=lambda: Settings(), save=Mock()),
        displays=displays, windows=FakeWindows(), volume=FakeVolume(), session_factory=Mock(),
        hotkey_factory=Mock(), startup=SimpleNamespace(is_enabled=lambda: False), packaged=False, **kwargs)


class FakeUser32:
    def __init__(self, ok: bool = True, point: tuple[int, int] = (0, 0)) -> None:
        self.ok, self.point = ok, point

    def GetCursorPos(self, ref) -> int:
        ref._obj.x, ref._obj.y = self.point
        return 1 if self.ok else 0


def test_read_os_cursor_returns_point_from_api() -> None:
    assert read_os_cursor(api=FakeUser32(point=(-1280, 340))) == (-1280, 340)


def test_read_os_cursor_failure_is_unknown() -> None:
    assert read_os_cursor(api=FakeUser32(ok=False)) is None
    broken = SimpleNamespace(GetCursorPos=Mock(side_effect=OSError('denied')))
    assert read_os_cursor(api=broken) is None


def test_runtime_defaults_to_os_reader(qt) -> None:
    r = make(qt)
    try:
        assert r.cursor_source is app.read_os_cursor   # patched to a no-op by conftest
        assert r.pipeline.controller._cursor_source is r.cursor_source
    finally:
        r.close()


def test_injected_cursor_source_reaches_controller_and_survives_settings_save(qt) -> None:
    source = Mock(return_value=(40, 50))
    r = make(qt, cursor_source=source)
    try:
        assert r.pipeline.controller._cursor_source is source
        assert r.pipeline.controller._read_cursor() == (40, 50)
        r.save_settings(settings_to_dialog_data(r.settings))
        assert r.pipeline.controller._cursor_source is source
        source.reset_mock()
        assert r.pipeline.controller._read_cursor() == (40, 50)
        source.assert_called_once_with()
    finally:
        r.close()


def test_dialog_receives_pointer_mode_and_speed() -> None:
    d = settings_to_dialog_data(validate({'pointer_mode': 'absolute', 'pointer_speed': 1.6}))
    assert (d.pointer_mode, d.pointer_speed) == ('absolute', 1.6)
    d = settings_to_dialog_data(validate({}))
    assert (d.pointer_mode, d.pointer_speed) == ('relative', 1.0)
    assert (d.pinch_on_threshold, d.pinch_off_threshold) == (0.33, 0.48)


def test_saved_pointer_values_are_stored_and_reach_running_pipeline(qt) -> None:
    r = make(qt)
    try:
        r.save_settings(replace(settings_to_dialog_data(r.settings), pointer_mode='absolute', pointer_speed=1.7))
        stored = r.store.save.call_args.args[0]
        assert (stored.pointer_mode, stored.pointer_speed) == ('absolute', 1.7)
        cfg = r.pipeline.controller.config
        assert cfg.pointer_relative is False and cfg.pointer_speed == pytest.approx(1.7)
        # Round trip back into the dialog keeps the user's values.
        back = settings_to_dialog_data(r.settings)
        assert (back.pointer_mode, back.pointer_speed) == ('absolute', 1.7)
        r.save_settings(replace(back, pointer_mode='relative', pointer_speed=0.5))
        assert r.pipeline.controller.config.pointer_relative is True
        assert r.pipeline.controller.config.pointer_speed == pytest.approx(0.5)
    finally:
        r.close()
