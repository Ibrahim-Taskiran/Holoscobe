from __future__ import annotations
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from PySide6.QtWidgets import QApplication
from handcontrol.app import Runtime
from handcontrol.config import Settings
from handcontrol.dryrun import FakeDisplays, FakeVolume, FakeWindows
from handcontrol.ui import UiBridge


@pytest.fixture
def qt():
    return QApplication.instance() or QApplication([])


def test_snapshot_reaches_bridge_update_snapshot(qt):
    displays = FakeDisplays()
    displays.start = Mock()
    displays.close = Mock()
    bridge = UiBridge()
    r = Runtime(bridge, SimpleNamespace(load=lambda: Settings(), save=Mock()), displays=displays,
                windows=FakeWindows(), volume=FakeVolume(), session_factory=Mock(), hotkey_factory=Mock())
    try:
        bridge.update_snapshot = Mock()
        r._snapshot(r.pipeline.controller.snapshot())
        bridge.update_snapshot.assert_called_once()
    finally:
        r.close()
