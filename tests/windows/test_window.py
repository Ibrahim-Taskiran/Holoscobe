from __future__ import annotations

from types import SimpleNamespace

import pytest

from handcontrol.contracts import Monitor, Rect, WindowTarget
from handcontrol.windows.window import SWP_FLAGS, WindowsWindowQuery


class FakeWindowAPI:
    def __init__(self):
        self.pid = 100
        self.exists = True
        self.visible = True
        self.class_name = "TestWindow"
        self.owner = 0
        self.exstyle = 0
        self.maximized = False
        self.rect = Rect(-900, 50, -500, 350)
        self.calls = []

    def GetWindowThreadProcessId(self, hwnd, pid):
        pid._obj.value = self.pid if self.exists else 0
        return 10 if self.exists else 0

    def IsWindow(self, hwnd): return self.exists
    def IsWindowVisible(self, hwnd): return self.visible
    def IsIconic(self, hwnd): return False
    def IsZoomed(self, hwnd): return self.maximized
    def GetAncestor(self, hwnd, flags): return 10
    def GetDesktopWindow(self): return 1
    def GetShellWindow(self): return 2
    def GetForegroundWindow(self): return 10
    def WindowFromPoint(self, point): return 11
    def GetWindow(self, hwnd, flags): return self.owner
    def window_style(self, hwnd, index): return self.exstyle if index == -20 else 0

    def GetClassNameW(self, hwnd, buffer, length):
        buffer.value = self.class_name
        return len(self.class_name)

    def GetWindowRect(self, hwnd, pointer):
        for field in ("left", "top", "right", "bottom"):
            setattr(pointer._obj, field, getattr(self.rect, field))
        return 1

    def GetWindowPlacement(self, hwnd, pointer):
        for field, value in zip(("left", "top", "right", "bottom"), (-800, 100, -400, 400)):
            setattr(pointer._obj.rcNormalPosition, field, value)
        return 1

    def SetWindowPos(self, *args):
        self.calls.append(("position", args))
        return 1

    def ShowWindowAsync(self, *args):
        self.calls.append(("show", args))
        return 1

    def PostMessageW(self, *args):
        self.calls.append(("post", args))
        return 1


@pytest.fixture
def window():
    api = FakeWindowAPI()
    displays = SimpleNamespace(monitors=lambda: [
        Monitor(Rect(-1000, 0, 0, 800), Rect(-1000, 0, 0, 760), 1, False),
        Monitor(Rect(0, -100, 1920, 980), Rect(0, -100, 1920, 940), 1.5, True)])
    return WindowsWindowQuery(displays, api=api, own_pid=999), api, WindowTarget(10, 100)


@pytest.mark.parametrize("operation", ["minimize", "toggle_maximize", "move_to_other_monitor", "close_window",
                                        "drag_begin", "drag_move", "drag_end"])
@pytest.mark.parametrize("invalidity", ["destroyed", "recycled"])
def test_invalid_identity_never_mutates_other_window(window, operation, invalidity):
    adapter, api, target = window
    assert adapter.drag_begin(target, -800, 100)
    if invalidity == "destroyed":
        api.exists = False
    else:
        api.pid = 101
    args = (target, 0, 0) if operation in ("drag_begin", "drag_move") else (target,)
    assert not getattr(adapter, operation)(*args)
    assert api.calls == []


@pytest.mark.parametrize("name", ["Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "#32768", "tooltips_class32"])
def test_transient_and_shell_classes_excluded(window, name):
    adapter, api, target = window
    api.class_name = name
    assert adapter.eligible_window_at(0, 0) is None


@pytest.mark.parametrize("attribute,value", [("pid", 999), ("owner", 12), ("exstyle", 0x80), ("exstyle", 0x08000000)])
def test_own_and_transient_windows_excluded(window, attribute, value):
    adapter, api, target = window
    setattr(api, attribute, value)
    assert not adapter.is_valid(target)
    assert adapter.foreground_window() is None


def test_child_resolves_to_latched_top_level(window):
    adapter, api, target = window
    assert adapter.eligible_window_at(10, 20) == target


def test_drag_does_not_activate_and_clears_on_release(window):
    adapter, api, target = window
    assert adapter.drag_begin(target, -800, 100)
    assert adapter.drag_move(target, -700, 200)
    call = api.calls[-1][1]
    assert call[0] == target.hwnd and call[2:4] == (-800, 150)
    assert call[-1] & SWP_FLAGS == SWP_FLAGS
    assert adapter.drag_end(target)
    assert not adapter.drag_move(target, 0, 0)


def test_maximized_drag_restores_relative_pointer_position(window):
    adapter, api, target = window
    api.maximized = True
    api.rect = Rect(-1000, 0, 0, 800)
    assert adapter.drag_begin(target, -500, 40)
    assert api.calls[0] == ("show", (10, 4))
    assert api.calls[1][1][2:6] == (-700, 25, 400, 300)


def test_move_monitor_preserves_maximized_state(window):
    adapter, api, target = window
    api.maximized = True
    assert adapter.move_to_other_monitor(target)
    assert [call[0] for call in api.calls] == ["show", "position", "show"]
    assert api.calls[-1] == ("show", (10, 3))


def test_single_monitor_move_disabled(window):
    adapter, api, target = window
    monitor = adapter.displays.monitors()[0]
    adapter.displays = SimpleNamespace(monitors=lambda: [monitor])
    assert not adapter.move_to_other_monitor(target)
    assert api.calls == []


def test_close_only_posts_normal_close(window):
    adapter, api, target = window
    assert adapter.close_window(target)
    assert api.calls == [("post", (10, 0x10, 0, 0))]


def test_drag_end_uses_latest_queued_position(window):
    adapter, api, target = window
    assert adapter.drag_begin(target, -800, 100)
    assert adapter.drag_move(target, 500, 200)
    # Fake GetWindowRect intentionally still returns the old location.
    assert adapter.drag_end(target)
    assert api.calls[-1][1][2:4] == (400, 150)
