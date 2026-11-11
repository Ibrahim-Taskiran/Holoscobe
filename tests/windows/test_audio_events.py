from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import Mock

from handcontrol.windows.audio import WindowsVolumeControl
from handcontrol.windows.hotkey import DEFAULT_KEY, DEFAULT_MODIFIERS, MOD_NOREPEAT, HotkeyConflictError, WindowsHotkey
from handcontrol.windows.session import WindowsSession


def test_volume_clamp_switch_and_worker_affinity():
    thread_ids, writes = [], []
    endpoints = []
    for identifier in ("a", "b"):
        def write(value, context, identifier=identifier):
            thread_ids.append(threading.get_ident())
            writes.append((identifier, value))
        endpoints.append(SimpleNamespace(SetMasterVolumeLevelScalar=write, GetMasterVolumeLevelScalar=lambda: 0.4))
    active = [0]
    def speakers():
        thread_ids.append(threading.get_ident())
        index = active[0]
        return SimpleNamespace(id=str(index), EndpointVolume=endpoints[index])
    def factory():
        thread_ids.append(threading.get_ident())
        return SimpleNamespace(GetSpeakers=speakers)
    volume = WindowsVolumeControl(backend_factory=factory)
    try:
        assert volume.set_volume(-1)
        active[0] = 1
        assert volume.set_volume(2)
        assert volume.get_volume() == 0.4
        assert not volume.set_volume(float("nan"))
        assert writes == [("a", 0), ("b", 1)]
        assert len(set(thread_ids)) == 1 and thread_ids[0] != threading.get_ident()
    finally:
        volume.close()
    assert not volume._thread.is_alive()
    assert not volume.set_volume(0.5)


def test_audio_expired_write_never_replayed():
    backend = Mock()
    volume = WindowsVolumeControl(backend_factory=lambda: backend)
    try:
        assert not volume.set_volume(0.3, deadline_ms=0)
        backend.GetSpeakers.assert_not_called()
    finally:
        volume.close()


def test_session_notifications_are_passive():
    callback = Mock()
    session = WindowsSession(callback)
    for message, wp in [(0x2B1, 7), (0x2B1, 8), (0x218, 4), (0x218, 18)]:
        session._message(message, wp, 0)
    assert [call.args[0] for call in callback.call_args_list] == ["lock", "unlock", "suspend", "resume"]


def test_hotkey_reassignment_retains_previous_on_conflict(monkeypatch):
    import handcontrol.windows.hotkey as module
    api = Mock()
    api.RegisterHotKey.return_value = 0
    monkeypatch.setattr(module, "user32", lambda: api)
    hotkey = WindowsHotkey(Mock())
    hotkey._events = SimpleNamespace(hwnd=42, call=lambda fn: fn())
    hotkey._binding = (DEFAULT_MODIFIERS, DEFAULT_KEY)
    try:
        hotkey.reassign(2, 0x79)
    except HotkeyConflictError:
        pass
    else:
        raise AssertionError("Conflict was not reported")
    assert hotkey._binding == (DEFAULT_MODIFIERS, DEFAULT_KEY)
    api.UnregisterHotKey.assert_not_called()
    api.RegisterHotKey.assert_called_once_with(42, 2, 2 | MOD_NOREPEAT, 0x79)


def test_audio_invalid_endpoint_reacquired():
    failed, healthy = Mock(), Mock()
    failed.GetMasterVolumeLevelScalar.side_effect = OSError("invalidated endpoint")
    healthy.GetMasterVolumeLevelScalar.return_value = 0.75
    backend = Mock()
    backend.GetSpeakers.side_effect = [SimpleNamespace(id="same", EndpointVolume=failed),
                                      SimpleNamespace(id="same", EndpointVolume=healthy)]
    volume = WindowsVolumeControl(backend_factory=lambda: backend)
    try:
        assert volume.get_volume() == 0.75
        assert backend.GetSpeakers.call_count == 2
    finally:
        volume.close()


def test_com_initializes_and_uninitializes_on_worker(monkeypatch):
    import sys
    calls = []
    com = SimpleNamespace(CoInitializeEx=lambda: calls.append(("init", threading.get_ident())),
                          CoUninitialize=lambda: calls.append(("uninit", threading.get_ident())))
    endpoint = SimpleNamespace(GetMasterVolumeLevelScalar=lambda: 0.5)
    backend = SimpleNamespace(GetSpeakers=lambda: SimpleNamespace(id="fake", EndpointVolume=endpoint))
    monkeypatch.setitem(sys.modules, "comtypes", com)
    monkeypatch.setitem(sys.modules, "pycaw", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "pycaw.pycaw", SimpleNamespace(AudioUtilities=backend))
    volume = WindowsVolumeControl()
    try:
        assert volume.get_volume() == 0.5
    finally:
        volume.close()
    assert [name for name, _ in calls] == ["init", "uninit"]
    assert calls[0][1] == calls[1][1] != threading.get_ident()


def test_display_change_callback_only_when_geometry_changes():
    from handcontrol.contracts import Monitor, Rect
    from handcontrol.windows.displays import WindowsDisplayProvider
    callback = Mock()
    provider = WindowsDisplayProvider(callback)
    monitor = Monitor(Rect(-100, 0, 0, 100), Rect(-100, 0, 0, 90), 1.5, True)
    provider.monitors = lambda: (monitor,)
    provider._message(0x7E, 0, 0)
    provider._message(0x1A, 0, 0)
    callback.assert_called_once_with((monitor,))
