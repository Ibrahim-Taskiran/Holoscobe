from __future__ import annotations

import ctypes as C
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from handcontrol.contracts import Action, ActionKind, KeyCommand
from handcontrol.windows._win32 import INPUT
from handcontrol.windows.commands import COMMAND_KEYS, COMMAND_KEYS_TR, COMMAND_LABELS_TR
from handcontrol.windows.input import KEYEXTENDED, KEYUP, WindowsInput
from handcontrol.windows.sink import WindowsActionSink


class BatchAPI:
    def __init__(self, accept=None, down=()):
        self.events, self.accept, self.down = [], accept, set(down)

    def SendInput(self, count, pointer, size):
        assert size == C.sizeof(INPUT)
        batch = [INPUT.from_buffer_copy(C.string_at((C.addressof(getattr(pointer, '_obj', None) or pointer[0])) + i * size, size))
                 for i in range(count)]
        n = self.accept.pop(0) if self.accept else count
        self.events.extend(batch[:n])
        return n

    def GetAsyncKeyState(self, vk):
        return 0x8000 if vk in self.down else 0


def adapter(api):
    return WindowsInput(SimpleNamespace(monitors=lambda: []), api=api)


def seq(api):
    return [(e.ki.wVk, bool(e.ki.dwFlags & KEYUP), bool(e.ki.dwFlags & KEYEXTENDED)) for e in api.events]


def test_every_command_mapped():
    for cmd in KeyCommand:
        assert COMMAND_KEYS[cmd] and COMMAND_LABELS_TR[cmd] and COMMAND_KEYS_TR[cmd]


def test_combo_order_and_extended_flags():
    api = BatchAPI()
    assert adapter(api).key_combo(COMMAND_KEYS[KeyCommand.DESKTOP_LEFT])
    assert seq(api) == [(0x11, False, False), (0x5B, False, True), (0x25, False, True),
                        (0x25, True, True), (0x5B, True, True), (0x11, True, False)]


def test_single_batch_and_empty_ledger():
    api = BatchAPI()
    a = adapter(api)
    assert a.key_combo((0x12, 0x25)) and a.ledger == ()
    assert len(api.events) == 4


@pytest.mark.parametrize("accepted", [0, 1, 2, 3])
def test_partial_failure_releases_pressed_keys(accepted):
    api = BatchAPI(accept=[accepted])
    a = adapter(api)
    assert not a.key_combo((0x5B, 0x44))
    assert a.ledger == ()
    state = {}
    for vk, up, _ in seq(api):
        state[vk] = not up
    assert not any(state.values())


def test_total_send_exception_leaves_nothing_held():
    class Boom(BatchAPI):
        def SendInput(self, *a):
            raise OSError("x")
    a = adapter(Boom())
    assert not a.key_combo((0x27,)) and a.ledger == ()


def test_failed_release_stays_in_ledger_for_retry():
    api = BatchAPI(accept=[2, 0, 0])
    a = adapter(api)
    assert not a.key_combo((0x5B, 0x44))
    assert a.ledger == (("key", 0x5B), ("key", 0x44))
    a.release_all()
    assert a.ledger == () and seq(api)[-1] == (0x5B, True, True)


@pytest.mark.parametrize("held", [0x10, 0x11, 0x12, 0xA2, 0x5B, 0x5C])
def test_refused_when_modifier_held(held):
    api = BatchAPI(down={held})
    assert not adapter(api).key_combo((0x27,)) and api.events == []


def test_refused_when_mouse_button_held():
    api = BatchAPI()
    a = adapter(api)
    a._ledger.append(("mouse", 1))
    assert not a.key_combo((0x27,)) and api.events == []


@pytest.mark.parametrize("vks", [(), (0x27, 0x27), (0,), (300,)])
def test_invalid_input_rejected(vks):
    api = BatchAPI()
    assert not adapter(api).key_combo(vks) and api.events == []


def make_sink():
    return WindowsActionSink(epoch=1, clock=SimpleNamespace(now_ms=lambda: 100.0), displays=Mock(),
                             input_adapter=Mock(), windows=Mock(), volume=Mock(), on_error=Mock())


def test_sink_dispatches_key_command():
    s = make_sink()
    assert s.dispatch(Action(ActionKind.KEY_COMMAND, 1, 100.0, command="show_desktop"))
    s.input.key_combo.assert_called_once_with((0x5B, 0x44))


@pytest.mark.parametrize("cmd", ["", "nope"])
def test_sink_rejects_unknown_command(cmd):
    s = make_sink()
    assert not s.dispatch(Action(ActionKind.KEY_COMMAND, 1, 100.0, command=cmd))
    s.input.key_combo.assert_not_called()
    s.on_error.assert_called_once()


def test_sink_keeps_epoch_and_age_checks():
    s = make_sink()
    assert not s.dispatch(Action(ActionKind.KEY_COMMAND, 2, 100.0, command="next"))
    assert not s.dispatch(Action(ActionKind.KEY_COMMAND, 1, -100.0, command="next"))
    s.input.key_combo.assert_not_called()


def test_sink_false_from_input_propagates():
    s = make_sink()
    s.input.key_combo.return_value = False
    assert not s.dispatch(Action(ActionKind.KEY_COMMAND, 1, 100.0, command="next"))

