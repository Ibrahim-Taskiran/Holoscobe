from __future__ import annotations
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from PySide6.QtWidgets import QApplication
from handcontrol.app import Runtime, snapshot_to_viewmodel, hotkey_binding
from handcontrol.config import Settings
from handcontrol.contracts import Action, ActionKind, ControlState, FrameSample
from handcontrol.dryrun import DryRunSink, FakeDisplays, FakeWindows, FakeVolume
from handcontrol.ui import UiBridge
from handcontrol.windows.hotkey import HotkeyConflictError

@pytest.fixture
def qt():
    return QApplication.instance() or QApplication([])

def runtime(qt, **kwargs):
    displays = FakeDisplays()
    displays.start = Mock()
    displays.close = Mock()
    return Runtime(UiBridge(), SimpleNamespace(load=lambda: Settings(), save=Mock()),
        displays=displays, windows=FakeWindows(), volume=FakeVolume(),
        session_factory=Mock(), **kwargs)

def test_dry_run_lifecycle_and_no_native_sink(qt):
    factory = Mock(side_effect=AssertionError('Native sink must never be constructed'))
    r = runtime(qt, hotkey_factory=Mock(), sink_factory=factory)
    try:
        assert isinstance(r.sink.inner, DryRunSink)
        assert r.pipeline.controller.snapshot().state == ControlState.PAUSED
        r.sink.dispatch(Action(ActionKind.LEFT_CLICK, 0, 0, x=1, y=2))
        assert r.bridge.state.dry_run_command_text
        assert r.camera is None
    finally:
        r.close()
    r.close()
    assert r.closed
    factory.assert_not_called()

def test_live_rejected_before_native_sink_without_hotkey(qt):
    hotkey, sink = Mock(), Mock()
    hotkey.return_value.start.side_effect = HotkeyConflictError('occupied')
    with pytest.raises(RuntimeError, match='Canlı kontrol reddedildi'):
        runtime(qt, live=True, hotkey_factory=hotkey, sink_factory=sink)
    sink.assert_not_called()

def test_snapshot_mapping_and_worker_delivery(qt):
    r = runtime(qt, hotkey_factory=Mock())
    try:
        state = snapshot_to_viewmodel(r.pipeline.controller.snapshot())
        assert state.dry_run and state.control_state == ControlState.PAUSED
        import threading
        thread = threading.Thread(target=r.pipeline.process, args=(FrameSample(0, 1, 640, 480, ()),))
        thread.start()
        thread.join(2)
        assert not thread.is_alive()
        qt.processEvents()
        assert r.bridge.state.control_state == ControlState.PAUSED
    finally:
        r.close()

def test_camera_start_stop_is_injected(qt):
    camera = Mock()
    factory = Mock(return_value=camera)
    r = runtime(qt, hotkey_factory=Mock(), camera_factory=factory)
    try:
        r.start_camera()
        camera.start.assert_called_once()
        r.stop_camera()
        camera.loop.stop.assert_called_once()
        camera.camera.stop.assert_called_once()
    finally:
        r.close()

def test_epoch_synchronization_and_emergency(qt):
    native = Mock()
    r = runtime(qt, live=True, hotkey_factory=Mock(), sink_factory=Mock(return_value=native))
    try:
        r.pipeline.pause()
        native.set_epoch.assert_called_with(r.pipeline.controller.current_epoch())
        r._session_event('suspend')
        assert r.pipeline.controller.snapshot().state == ControlState.PAUSED
    finally:
        r.close()
    native.close.assert_called_once()

def test_hotkey_parser():
    assert hotkey_binding('Ctrl+Alt+Shift+F12') == (7, 0x7B)
    with pytest.raises(ValueError):
        hotkey_binding('Ctrl+F99')


def test_camera_failure_stays_paused_and_cannot_resume(qt):
    from handcontrol.contracts import CameraState
    r = runtime(qt, hotkey_factory=Mock())
    try:
        r.pipeline.set_camera_state(CameraState.ERROR)
        assert r.pipeline.controller.snapshot().state == ControlState.PAUSED
        assert not r.pipeline.resume()
        r.pipeline.set_camera_state(CameraState.RUNNING)
        assert r.pipeline.controller.snapshot().state == ControlState.PAUSED
    finally:
        r.close()


def test_window_menu_maps_disabled_and_close_progress(qt):
    from dataclasses import replace
    from handcontrol.controller import MenuSnapshot, MenuItem, MenuKind
    r = runtime(qt, hotkey_factory=Mock())
    try:
        menu = MenuSnapshot(MenuKind.WINDOW, (MenuItem('other_monitor', 'Taşı', False),
            MenuItem('close', 'Kapat')), 1, (0.5, 0.75), 0.7, True, None, 3000)
        state = snapshot_to_viewmodel(replace(r.pipeline.controller.snapshot(), menu=menu))
        assert not state.overlay.items[0].enabled
        assert state.overlay.items[1].hovered and state.overlay.items[1].armed
        assert state.overlay.items[1].hold_progress == 0.7
        assert state.overlay.cursor.y == 0.75 and state.overlay.inactivity_ms == 2000
    finally:
        r.close()
