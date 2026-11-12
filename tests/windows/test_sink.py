from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from handcontrol.contracts import Action, ActionKind, WindowTarget
from handcontrol.windows.sink import WindowsActionSink


@pytest.fixture
def sink():
    return WindowsActionSink(epoch=7, clock=SimpleNamespace(now_ms=lambda: 1000.0),
        displays=Mock(), input_adapter=Mock(), windows=Mock(), volume=Mock())


@pytest.mark.parametrize("epoch,capture", [(6, 1000), (8, 1000), (7, 849.9),
    (7, 1000.1), (7, float("nan")), (7, float("inf"))])
def test_stale_wrong_epoch_and_invalid_time_rejected(sink, epoch, capture):
    assert not sink.dispatch(Action(ActionKind.MOVE_POINTER, epoch, capture, x=0, y=0))
    assert sink.input.mock_calls == []


@pytest.mark.parametrize("capture", [850, 1000])
def test_fresh_boundary_accepted(sink, capture):
    assert sink.dispatch(Action(ActionKind.MOVE_POINTER, 7, capture, x=-1, y=20))
    sink.input.move_pointer.assert_called_once_with(-1, 20)


def test_release_ignores_epoch_age_and_closed_state(sink):
    sink._closed = True
    assert sink.dispatch(Action(ActionKind.RELEASE_ALL, -100, float("nan")))
    sink.input.release_all.assert_called_once()
    sink.windows.cancel_drag.assert_called_once()


def test_epoch_update_releases_and_invalidates(sink):
    sink.set_epoch(8)
    assert sink.epoch == 8
    sink.input.release_all.assert_called_once()
    assert not sink.dispatch(Action(ActionKind.LEFT_CLICK, 7, 1000, x=1, y=1))


@pytest.mark.parametrize("kind,owner,method,args", [
    (ActionKind.MOVE_POINTER, "input", "move_pointer", (12, 34)),
    (ActionKind.LEFT_CLICK, "input", "left_click", (12, 34)),
    (ActionKind.RIGHT_CLICK, "input", "right_click", (12, 34)),
    (ActionKind.DOUBLE_CLICK, "input", "double_click", (12, 34)),
    (ActionKind.LEFT_DOWN, "input", "left_down", (12, 34)),
    (ActionKind.LEFT_UP, "input", "left_up", (12, 34)),
    (ActionKind.SCROLL, "input", "scroll", (2,)),
    (ActionKind.ZOOM, "input", "zoom", (2,)),
    (ActionKind.SET_VOLUME, "volume", "set_volume", (0.5,)),
    (ActionKind.WINDOW_DRAG_BEGIN, "windows", "drag_begin", (WindowTarget(10, 20), 12, 34)),
    (ActionKind.WINDOW_DRAG_MOVE, "windows", "drag_move", (WindowTarget(10, 20), 12, 34)),
    (ActionKind.WINDOW_DRAG_END, "windows", "drag_end", (WindowTarget(10, 20),)),
    (ActionKind.WINDOW_MINIMIZE, "windows", "minimize", (WindowTarget(10, 20),)),
    (ActionKind.WINDOW_RESTORE, "windows", "restore", (WindowTarget(10, 20),)),
    (ActionKind.WINDOW_TOGGLE_MAXIMIZE, "windows", "toggle_maximize", (WindowTarget(10, 20),)),
    (ActionKind.WINDOW_MOVE_TO_OTHER_MONITOR, "windows", "move_to_other_monitor", (WindowTarget(10, 20),)),
    (ActionKind.WINDOW_CLOSE, "windows", "close_window", (WindowTarget(10, 20),)),
])
def test_every_action_routes(sink, kind, owner, method, args):
    assert sink.dispatch(Action(kind, 7, 1000, x=12, y=34, steps=2, value=0.5, target=WindowTarget(10, 20)))
    getattr(getattr(sink, owner), method).assert_called_once_with(*args)


def test_scroll_never_retargets(sink):
    sink.windows.can_receive_input.return_value = False
    assert not sink.dispatch(Action(ActionKind.SCROLL, 7, 1000, steps=1, target=WindowTarget(10, 20)))
    sink.input.scroll.assert_not_called()


def test_release_all_survives_independent_failures(sink):
    sink.input.release_all.side_effect = OSError("input")
    sink.windows.cancel_drag.side_effect = OSError("window")
    sink.release_all()
    sink.windows.cancel_drag.assert_called_once()


def test_dispatch_exception_releases_owned_inputs(sink):
    sink.input.move_pointer.side_effect = OSError("input")
    assert not sink.dispatch(Action(ActionKind.MOVE_POINTER, 7, 1000, x=0, y=0))
    sink.input.release_all.assert_called_once()


def test_actions_serialized_and_rechecked_after_lock(sink):
    entered, finish = threading.Event(), threading.Event()
    now = [1000.0]
    sink.clock.now_ms = lambda: now[0]
    def move(x, y):
        entered.set()
        assert finish.wait(2)
        return True
    sink.input.move_pointer.side_effect = move
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(sink.dispatch, Action(ActionKind.MOVE_POINTER, 7, 1000, x=0, y=0))
        assert entered.wait(2)
        second = executor.submit(sink.dispatch, Action(ActionKind.LEFT_CLICK, 7, 1000, x=0, y=0))
        now[0] = 1200
        finish.set()
        assert first.result() and not second.result()
    sink.input.left_click.assert_not_called()


@pytest.mark.parametrize("kind", [ActionKind.RIGHT_CLICK, ActionKind.DOUBLE_CLICK,
    ActionKind.LEFT_DOWN, ActionKind.LEFT_UP])
@pytest.mark.parametrize("x,y", [(None, 3), (2, None), (None, None)])
def test_new_mouse_actions_require_both_coordinates(sink, kind, x, y):
    assert not sink.dispatch(Action(kind, 7, 1000, x=x, y=y))
    getattr(sink.input, kind.value).assert_not_called()
    if kind == ActionKind.LEFT_UP:
        sink.input.release_all.assert_called_once()


@pytest.mark.parametrize("kind", [ActionKind.RIGHT_CLICK, ActionKind.DOUBLE_CLICK,
    ActionKind.LEFT_DOWN, ActionKind.LEFT_UP])
@pytest.mark.parametrize("epoch,capture", [(6, 1000), (8, 1000), (7, 849.9),
    (7, 1000.1), (7, float("nan")), (7, float("inf"))])
def test_new_mouse_actions_preserve_epoch_and_age_guards(sink, kind, epoch, capture):
    assert not sink.dispatch(Action(kind, epoch, capture, x=12, y=34))
    getattr(sink.input, kind.value).assert_not_called()
    sink.input.move_pointer.assert_not_called()
    if kind == ActionKind.LEFT_UP:
        sink.input.release_all.assert_called_once()
    else:
        sink.input.release_all.assert_not_called()


@pytest.fixture
def mouse_sink(sink):
    from test_input import FakeInputAPI, make_input
    api = FakeInputAPI()
    sink.input = make_input(api)
    return sink, api


@pytest.mark.parametrize("epoch,capture,closed,x,y", [
    (6, 1000, False, 99, 99), (8, 1000, False, 99, 99),
    (7, 849.9, False, 99, 99), (7, 1000.1, False, 99, 99),
    (7, float("nan"), False, 99, 99), (7, float("inf"), False, 99, 99),
    (7, 1000, True, 99, 99), (7, 1000, False, None, 99),
    (7, 1000, False, 99, None),
])
def test_rejected_left_up_releases_without_moving(mouse_sink, epoch, capture, closed, x, y):
    from handcontrol.windows.input import LEFTUP
    sink, api = mouse_sink
    assert sink.dispatch(Action(ActionKind.LEFT_DOWN, 7, 1000, x=0, y=0))
    assert sink.input.ledger == (("mouse", 1),)
    sink._closed = closed
    assert not sink.dispatch(Action(ActionKind.LEFT_UP, epoch, capture, x=x, y=y))
    assert len(api.events) == 3 and api.events[-1].mi.dwFlags == LEFTUP
    assert sink.input.ledger == ()


@pytest.mark.parametrize("cleanup", ["epoch", "close", "exception", "clock_exception"])
def test_cleanup_paths_release_real_adapter_ledger(mouse_sink, cleanup):
    from handcontrol.windows.input import LEFTUP
    sink, api = mouse_sink
    assert sink.dispatch(Action(ActionKind.LEFT_DOWN, 7, 1000, x=0, y=0))
    if cleanup == "epoch":
        sink.set_epoch(8)
    elif cleanup == "close":
        sink.close()
        assert not sink.dispatch(Action(ActionKind.LEFT_DOWN, 7, 1000, x=0, y=0))
    else:
        if cleanup == "clock_exception":
            sink.clock.now_ms = Mock(side_effect=OSError("clock failed"))
        else:
            sink.windows.is_valid.side_effect = OSError("window failed")
        assert not sink.dispatch(Action(ActionKind.WINDOW_MINIMIZE, 7, 1000, target=WindowTarget(10, 20)))
    assert sink.input.ledger == ()
    assert len(api.events) == 3 and api.events[-1].mi.dwFlags == LEFTUP
    sink.windows.cancel_drag.assert_called_once()


@pytest.mark.parametrize("kind", [ActionKind.RIGHT_CLICK, ActionKind.DOUBLE_CLICK, ActionKind.LEFT_UP])
def test_failed_mouse_up_is_retried_by_sink(mouse_sink, kind):
    from handcontrol.windows.input import LEFTUP, RIGHTUP
    sink, api = mouse_sink
    if kind == ActionKind.LEFT_UP:
        assert sink.dispatch(Action(ActionKind.LEFT_DOWN, 7, 1000, x=0, y=0))
        api.results = [1, 0, 1]
    else:
        api.results = [1, 1, 0, 1]
    assert not sink.dispatch(Action(kind, 7, 1000, x=99, y=99))
    up = RIGHTUP if kind == ActionKind.RIGHT_CLICK else LEFTUP
    assert [e.mi.dwFlags for e in api.events[-2:]] == [up, up]
    assert sink.input.ledger == ()


def test_close_cleans_input_before_volume_failure(mouse_sink):
    sink, _ = mouse_sink
    assert sink.dispatch(Action(ActionKind.LEFT_DOWN, 7, 1000, x=0, y=0))
    sink.volume.close.side_effect = OSError("audio failed")
    with pytest.raises(OSError, match="audio failed"):
        sink.close()
    assert sink.input.ledger == ()


def test_rejected_left_up_retains_failed_release_for_next_cleanup(mouse_sink):
    from handcontrol.windows.input import LEFTUP
    sink, api = mouse_sink
    assert sink.dispatch(Action(ActionKind.LEFT_DOWN, 7, 1000, x=0, y=0))
    api.results = [0, 1]
    assert not sink.dispatch(Action(ActionKind.LEFT_UP, 6, 1000, x=99, y=99))
    assert sink.input.ledger == (("mouse", 1),)
    sink.close()
    assert sink.input.ledger == ()
    assert [e.mi.dwFlags for e in api.events[-2:]] == [LEFTUP, LEFTUP]


def test_sink_drag_sequence_at_age_boundary(mouse_sink):
    from handcontrol.windows.input import ABSOLUTE, LEFTDOWN, LEFTUP, MOVE, VIRTUALDESK
    sink, api = mouse_sink
    for kind, x, y in [(ActionKind.LEFT_DOWN, -100, -100),
                       (ActionKind.MOVE_POINTER, 50, 50), (ActionKind.LEFT_UP, 99, 99)]:
        assert sink.dispatch(Action(kind, 7, 850, x=x, y=y))
    move = MOVE | ABSOLUTE | VIRTUALDESK
    assert [e.mi.dwFlags for e in api.events] == [move, LEFTDOWN, move, move, LEFTUP]
    assert sink.input.ledger == ()
