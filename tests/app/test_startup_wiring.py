from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QApplication

from handcontrol.app import STARTUP_FAILED_TR, STARTUP_SOURCE_TR, Runtime, settings_to_dialog_data
from handcontrol.config import Settings
from handcontrol.dryrun import FakeDisplays, FakeVolume, FakeWindows
from handcontrol.ui import UiBridge


class FakeStartup:
    """In-memory stand-in for handcontrol.windows.startup; never touches the registry."""
    def __init__(self, enabled: bool = False, ok: bool = True) -> None:
        self.enabled, self.ok = enabled, ok
        self.set_enabled = Mock(side_effect=self._set)

    def is_enabled(self) -> bool:
        return self.enabled

    def _set(self, enabled: bool) -> bool:
        if self.ok:
            self.enabled = enabled
        return self.ok


@pytest.fixture
def qt():
    return QApplication.instance() or QApplication([])


def make(qt, startup: FakeStartup, *, packaged: bool) -> Runtime:
    displays = FakeDisplays()
    displays.start = Mock()
    displays.close = Mock()
    r = Runtime(UiBridge(), SimpleNamespace(load=lambda: Settings(), save=Mock()),
        displays=displays, windows=FakeWindows(), volume=FakeVolume(), session_factory=Mock(),
        hotkey_factory=Mock(), startup=startup, packaged=packaged)
    r.bridge.show_feedback = Mock()
    return r


def save(r: Runtime, start: bool) -> Settings:
    r.save_settings(replace(settings_to_dialog_data(r.settings), start_with_windows=start))
    return r.store.save.call_args.args[0]


def test_dialog_shows_registry_state_not_stored_flag() -> None:
    assert settings_to_dialog_data(Settings(), startup_enabled=True).start_with_windows is True
    stored = Settings()
    stored.start_with_windows = True
    assert settings_to_dialog_data(stored, startup_enabled=False).start_with_windows is False


def test_unchanged_value_does_not_write_registry(qt) -> None:
    startup = FakeStartup(enabled=True)
    r = make(qt, startup, packaged=True)
    try:
        assert save(r, True).start_with_windows is True
        startup.set_enabled.assert_not_called()
        r.bridge.show_feedback.assert_not_called()
    finally:
        r.close()


def test_packaged_enable_success_is_stored(qt) -> None:
    startup = FakeStartup()
    r = make(qt, startup, packaged=True)
    try:
        assert save(r, True).start_with_windows is True
        startup.set_enabled.assert_called_once_with(True)
        r.bridge.show_feedback.assert_not_called()
    finally:
        r.close()


def test_packaged_enable_failure_keeps_disabled_and_warns(qt) -> None:
    startup = FakeStartup(ok=False)
    r = make(qt, startup, packaged=True)
    try:
        assert save(r, True).start_with_windows is False
        r.bridge.show_feedback.assert_called_once_with(message=STARTUP_FAILED_TR)
    finally:
        r.close()


def test_source_checkout_refuses_enable(qt) -> None:
    startup = FakeStartup()
    r = make(qt, startup, packaged=False)
    try:
        assert save(r, True).start_with_windows is False
        startup.set_enabled.assert_not_called()
        r.bridge.show_feedback.assert_called_once_with(message=STARTUP_SOURCE_TR)
    finally:
        r.close()


def test_source_checkout_can_still_disable(qt) -> None:
    startup = FakeStartup(enabled=True)
    r = make(qt, startup, packaged=False)
    try:
        assert save(r, False).start_with_windows is False
        startup.set_enabled.assert_called_once_with(False)
    finally:
        r.close()
