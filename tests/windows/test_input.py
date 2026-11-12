from __future__ import annotations

import ctypes as C
from types import SimpleNamespace

import pytest

from handcontrol.contracts import Monitor, Rect
from handcontrol.windows._win32 import INPUT, KEYBDINPUT, MOUSEINPUT, MONITORINFO, POINT, RECT, WINDOWPLACEMENT
from handcontrol.windows.input import (ABSOLUTE, KEYUP, LEFTDOWN, LEFTUP, MOVE, RIGHTDOWN, RIGHTUP,
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


@pytest.mark.parametrize("method,flags,ledger", [
    ("right_click", [RIGHTDOWN, RIGHTUP], ()),
    ("double_click", [LEFTDOWN, LEFTUP, LEFTDOWN, LEFTUP], ()),
    ("left_down", [LEFTDOWN], (("mouse", 1),)),
    ("left_up", [], ()),
])
def test_new_mouse_sequences(method, flags, ledger):
    api = FakeInputAPI()
    adapter = make_input(api)
    assert getattr(adapter, method)(99, -100)
    assert [e.mi.dwFlags for e in api.events] == [MOVE | ABSOLUTE | VIRTUALDESK, *flags]
    assert all(e.type == 0 for e in api.events)
    assert (api.events[0].mi.dx, api.events[0].mi.dy) == (65535, 0)
    assert all((e.mi.dx, e.mi.dy) == (0, 0) for e in api.events[1:])
    assert adapter.ledger == ledger


def test_drag_move_release_and_idempotence():
    api = FakeInputAPI()
    adapter = make_input(api)
    assert adapter.left_down(-100, -100)
    assert adapter.move_pointer(99, 99)
    assert adapter.ledger == (("mouse", 1),)
    assert adapter.left_up(99, 99)
    assert adapter.left_up(99, 99)
    move = MOVE | ABSOLUTE | VIRTUALDESK
    assert [e.mi.dwFlags for e in api.events] == [move, LEFTDOWN, move, move, LEFTUP, move]
    assert adapter.ledger == ()


@pytest.mark.parametrize("method", ["left_down", "left_click", "double_click"])
def test_held_left_blocks_repeated_down_and_clicks(method):
    api = FakeInputAPI()
    adapter = make_input(api)
    assert adapter.left_down(0, 0)
    assert not getattr(adapter, method)(99, 99)
    assert len(api.events) == 2
    assert adapter.ledger == (("mouse", 1),)
    assert adapter.move_pointer(99, 99)
    assert adapter.ledger == (("mouse", 1),)


@pytest.mark.parametrize("method,sequence,button", [
    ("left_click", [MOVE | ABSOLUTE | VIRTUALDESK, LEFTDOWN, LEFTUP], 1),
    ("right_click", [MOVE | ABSOLUTE | VIRTUALDESK, RIGHTDOWN, RIGHTUP], 2),
    ("double_click", [MOVE | ABSOLUTE | VIRTUALDESK, LEFTDOWN, LEFTUP, LEFTDOWN, LEFTUP], 1),
    ("left_down", [MOVE | ABSOLUTE | VIRTUALDESK, LEFTDOWN], 1),
])
@pytest.mark.parametrize("failure", [0, OSError("blocked")])
def test_mouse_failure_at_each_event(method, sequence, button, failure):
    for index in range(len(sequence)):
        api = FakeInputAPI([1] * index + [failure])
        adapter = make_input(api)
        assert not getattr(adapter, method)(0, 0)
        assert [e.mi.dwFlags for e in api.events] == sequence[:index + 1]
        held = sequence[index] in (LEFTUP, RIGHTUP)
        assert adapter.ledger == ((("mouse", button),) if held else ())
        adapter.release_all()
        assert adapter.ledger == ()
        if held:
            assert api.events[-1].mi.dwFlags == (LEFTUP if button == 1 else RIGHTUP)


@pytest.mark.parametrize("failure_index", [0, 1])
@pytest.mark.parametrize("failure", [0, OSError("blocked")])
def test_left_up_failure_releases_or_retains_for_retry(failure_index, failure):
    api = FakeInputAPI()
    adapter = make_input(api)
    assert adapter.left_down(0, 0)
    api.results = [1] * failure_index + [failure]
    assert not adapter.left_up(99, 99)
    assert [e.mi.dwFlags for e in api.events[-2:]] == [MOVE | ABSOLUTE | VIRTUALDESK, LEFTUP]
    assert adapter.ledger == ((("mouse", 1),) if failure_index == 1 else ())
    adapter.release_all()
    assert adapter.ledger == ()


def test_left_up_releases_even_when_display_lookup_raises():
    api = FakeInputAPI()
    adapter = make_input(api)
    assert adapter.left_down(0, 0)
    def broken_monitors():
        raise OSError("display unavailable")
    adapter.displays.monitors = broken_monitors
    with pytest.raises(OSError, match="display unavailable"):
        adapter.left_up(0, 0)
    assert api.events[-1].mi.dwFlags == LEFTUP
    assert adapter.ledger == ()


@pytest.mark.parametrize("failure", [0, OSError("blocked")])
def test_release_all_both_mouse_buttons_retries_independently(failure):
    api = FakeInputAPI()
    adapter = make_input(api)
    assert adapter.left_down(0, 0)
    assert adapter._press(("mouse", 2), mouse(RIGHTDOWN))
    api.results = [failure, failure]
    adapter.release_all()
    assert adapter.ledger == (("mouse", 1), ("mouse", 2))
    assert [e.mi.dwFlags for e in api.events[-2:]] == [RIGHTUP, LEFTUP]
    adapter.release_all()
    assert adapter.ledger == ()
    assert [e.mi.dwFlags for e in api.events[-2:]] == [RIGHTUP, LEFTUP]
    count = len(api.events)
    adapter.release_all()
    assert len(api.events) == count


def test_pending_right_release_blocks_another_right_click():
    api = FakeInputAPI([1, 1, 0])
    adapter = make_input(api)
    assert not adapter.right_click(0, 0)
    assert adapter.ledger == (("mouse", 2),)
    assert not adapter.right_click(99, 99)
    assert len(api.events) == 3
    adapter.release_all()
    assert api.events[-1].mi.dwFlags == RIGHTUP
    assert adapter.ledger == ()
