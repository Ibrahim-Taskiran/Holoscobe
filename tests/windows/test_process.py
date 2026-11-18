from __future__ import annotations

from handcontrol.windows.process import WindowsProcessNames


class FakeK32:
    def __init__(self, path=r"C:\Apps\Chrome.EXE", handle=5, ok=True):
        self.path, self.handle, self.ok = path, handle, ok
        self.opened, self.closed = [], []

    def OpenProcess(self, access, inherit, pid):
        self.opened.append((access, pid))
        return self.handle

    def QueryFullProcessImageNameW(self, handle, flags, buf, size):
        if not self.ok:
            return 0
        buf.value = self.path
        size._obj.value = len(self.path)
        return 1

    def CloseHandle(self, handle):
        self.closed.append(handle)


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def test_lowercase_basename_and_handle_closed():
    api = FakeK32()
    assert WindowsProcessNames(api=api).process_name(42) == "chrome.exe"
    assert api.opened == [(0x1000, 42)] and api.closed == [5]


def test_open_failure_returns_none():
    assert WindowsProcessNames(api=FakeK32(handle=0)).process_name(42) is None


def test_query_failure_closes_handle():
    api = FakeK32(ok=False)
    assert WindowsProcessNames(api=api).process_name(42) is None and api.closed == [5]


def test_exception_never_raised():
    class Boom(FakeK32):
        def OpenProcess(self, *a):
            raise OSError("x")
    assert WindowsProcessNames(api=Boom()).process_name(1) is None


def test_invalid_pid():
    api = FakeK32()
    assert WindowsProcessNames(api=api).process_name(0) is None and api.opened == []


def test_cache_two_seconds():
    api, clock = FakeK32(), Clock()
    names = WindowsProcessNames(api=api, clock=clock)
    names.process_name(7)
    clock.t = 1.9
    names.process_name(7)
    assert len(api.opened) == 1
    clock.t = 2.1
    names.process_name(7)
    assert len(api.opened) == 2
