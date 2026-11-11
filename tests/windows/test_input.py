from __future__ import annotations

import ctypes as C
from types import SimpleNamespace

import pytest

from handcontrol.contracts import Monitor, Rect
from handcontrol.windows._win32 import INPUT, KEYBDINPUT, MOUSEINPUT, MONITORINFO, POINT, RECT, WINDOWPLACEMENT
from handcontrol.windows.input import (ABSOLUTE, KEYUP, LEFTDOWN, LEFTUP, MOVE,
    VIRTUALDESK, WHEEL, WindowsInput, key, mouse)


class FakeInputAPI:
    def __init__(self, results=(), down=()):
        self.events = []
        self.results = list(results)
        self.down = set(down)

    def SendInput(self, count, pointer, size):
        assert count == 1 and size == C.sizeof(INPUT)
        event = INPUT.from_buffer_copy(C.string_at(pointer, size))
        self.events.append(event)
        result = self.results.pop(0) if self.results else 1
        if isinstance(result, Exception):
            raise result
        return result

    def GetAsyncKeyState(self, vk):
        return 0x8000 if vk in self.down else 0


def make_input(api):
    displays = SimpleNamespace(monitors=lambda: [Monitor(Rect(-100, -100, 100, 100), Rect(-100, -100, 100, 100), 1, True)])
    return WindowsInput(displays, api=api)


def test_ctypes_sizes_and_alignment():
    is64 = C.sizeof(C.c_void_p) == 8
    assert C.sizeof(INPUT) == (40 if is64 else 28)
    assert C.sizeof(MOUSEINPUT) == (32 if is64 else 24)
    assert C.sizeof(KEYBDINPUT) == (24 if is64 else 16)
    assert INPUT.data.offset == (8 if is64 else 4)
    assert C.sizeof(POINT) == 8
    assert C.sizeof(RECT) == 16
    assert C.sizeof(MONITORINFO) == 40
    assert C.sizeof(WINDOWPLACEMENT) == 44


def test_pointer_flags_and_extrema():
    api = FakeInputAPI()
    assert make_input(api).move_pointer(99, -100)
    assert (api.events[0].mi.dx, api.events[0].mi.dy) == (65535, 0)
    assert api.events[0].mi.dwFlags == MOVE | ABSOLUTE | VIRTUALDESK


def test_click_sequence_and_ledger():
    api = FakeInputAPI()
    adapter = make_input(api)
    assert adapter.left_click(0, 0)
    assert [e.mi.dwFlags for e in api.events] == [MOVE | ABSOLUTE | VIRTUALDESK, LEFTDOWN, LEFTUP]
    assert adapter.ledger == ()


@pytest.mark.parametrize("wheel_result", [0, OSError("blocked")])
def test_zoom_failure_always_releases_ctrl(wheel_result):
    api = FakeInputAPI([1, wheel_result, 1])
    adapter = make_input(api)
    assert not adapter.zoom(1)
    assert [e.type for e in api.events] == [1, 0, 1]
    assert api.events[0].ki.dwFlags == 0
    assert api.events[1].mi.dwFlags == WHEEL
    assert api.events[2].ki.dwFlags == KEYUP
    assert adapter.ledger == ()


@pytest.mark.parametrize("vk", [0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5])
def test_physical_modifiers_block_synthetic_chord(vk):
    api = FakeInputAPI(down=[vk])
    assert not make_input(api).zoom(1)
    assert api.events == []


def test_failed_down_is_not_owned():
    api = FakeInputAPI([0])
    adapter = make_input(api)
    assert not adapter.zoom(1)
    adapter.release_all()
    assert adapter.ledger == () and len(api.events) == 1


def test_failed_up_is_retained_and_retried():
    api = FakeInputAPI([1, 1, 0, 1])
    adapter = make_input(api)
    assert not adapter.zoom(1)
    assert adapter.ledger == (("key", 0x11),)
    adapter.release_all()
    assert adapter.ledger == () and len(api.events) == 4


def test_release_reverse_order_and_idempotence():
    api = FakeInputAPI()
    adapter = make_input(api)
    assert adapter._press(("mouse", 1), mouse(LEFTDOWN))
    assert adapter._press(("key", 0x11), key(0x11))
    assert not adapter._press(("key", 0x11), key(0x11))
    assert len(adapter.ledger) == 2 and len(api.events) == 2
    adapter.release_all()
    assert api.events[2].ki.dwFlags == KEYUP
    assert api.events[3].mi.dwFlags == LEFTUP
    adapter.release_all()
    assert len(api.events) == 4


def test_release_all_never_raises_even_callback_failure():
    api = FakeInputAPI([1, OSError("blocked")])
    adapter = make_input(api)
    adapter._press(("mouse", 1), mouse(LEFTDOWN))
    def broken(message):
        raise ValueError(message)
    adapter.on_error = broken
    adapter.release_all()
    assert adapter.ledger == (("mouse", 1),)


def test_negative_wheel_is_signed_dword():
    api = FakeInputAPI()
    assert make_input(api).scroll(-2)
    assert C.c_int32(api.events[0].mi.mouseData).value == -240
