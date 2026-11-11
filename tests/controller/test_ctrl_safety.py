from __future__ import annotations

import time

from handcontrol.contracts import Action, ActionKind
from handcontrol.dryrun import DryRunSink, FakeClock, describe_action
from handcontrol.safety import GuardedSink, Watchdog

K = ActionKind


class Raising:
    def __init__(self):
        self.calls = 0

    def dispatch(self, action):
        self.calls += 1
        raise OSError("adapter failed")

    def release_all(self):
        raise OSError("release failed")


def _guard(inner=None, epoch=3):
    clock = FakeClock(1000.0)
    inner = inner or DryRunSink()
    state = {"epoch": epoch}
    return GuardedSink(inner, clock, lambda: state["epoch"]), inner, clock, state


def test_guard_passes_fresh_current_epoch():
    g, sink, clock, _ = _guard()
    assert g.dispatch(Action(K.MOVE_POINTER, 3, 1000.0 - 150.0, x=1, y=2))
    assert sink.kinds() == [K.MOVE_POINTER]


def test_guard_drops_stale_and_wrong_epoch_and_counts():
    g, sink, clock, state = _guard()
    assert not g.dispatch(Action(K.LEFT_CLICK, 3, 1000.0 - 150.1, x=1, y=2))
    assert not g.dispatch(Action(K.LEFT_CLICK, 2, 1000.0, x=1, y=2))
    state["epoch"] = 4
    assert not g.dispatch(Action(K.SCROLL, 3, 1000.0, steps=1))
    assert sink.kinds() == []
    assert (g.dropped_stale, g.dropped_epoch, g.dropped_total) == (1, 2, 3)


def test_release_all_always_passes():
    g, sink, clock, _ = _guard()
    assert g.dispatch(Action(K.RELEASE_ALL, 0, 0.0))  # wrong epoch and very old
    assert sink.kinds() == [K.RELEASE_ALL]


def test_release_never_raises_and_adapter_errors_are_contained():
    inner = Raising()
    g, _, _, _ = _guard(inner)
    g.release_all()
    assert g.release_failures == 1
    assert g.dispatch(Action(K.RELEASE_ALL, 3, 1000.0)) is True  # falls back to release_all
    assert g.release_failures == 2
    assert g.dispatch(Action(K.MOVE_POINTER, 3, 1000.0, x=0, y=0)) is False
    assert g.failed == 1


def test_watchdog_check_semantics():
    clock = FakeClock(0.0)
    fired = []
    wd = Watchdog(clock, lambda: fired.append(clock.now_ms()), timeout_ms=200.0)
    assert wd.check(10_000.0) is False  # never fed -> not armed
    wd.feed(100.0)
    assert wd.check(299.9) is False
    assert wd.check(300.0) is True
    assert wd.check(900.0) is False  # once per loss
    wd.feed(1000.0)
    assert wd.check(1200.0) is True
    wd.feed(2000.0)
    wd.disarm()
    assert wd.check(5000.0) is False
    assert len(fired) == 2 and wd.fired_count == 2


def test_watchdog_callback_errors_contained():
    clock = FakeClock(0.0)
    wd = Watchdog(clock, lambda: 1 / 0, timeout_ms=200.0)
    wd.feed(0.0)
    assert wd.check(200.0) is True
    assert wd.callback_errors == 1


def test_watchdog_thread_independent_of_loop():
    clock = FakeClock(0.0)
    fired = []
    wd = Watchdog(clock, lambda: fired.append(1), timeout_ms=200.0, poll_ms=2.0)
    wd.feed(0.0)
    wd.start()
    try:
        time.sleep(0.02)
        assert fired == []
        clock.advance(200.0)
        deadline = time.monotonic() + 2.0
        while not fired and time.monotonic() < deadline:
            time.sleep(0.002)
        assert fired == [1]
        assert wd.running
    finally:
        wd.stop()
    assert not wd.running


def test_dry_run_text_is_turkish_and_never_raises():
    s = DryRunSink()
    s.release_all()
    assert s.texts == ["Tüm girdileri bırak"]
    assert "Kaydır yukarı 2 adım" in describe_action(Action(K.SCROLL, 0, 0.0, steps=2))
    assert describe_action(Action(K.SET_VOLUME, 0, 0.0, value=0.45)) == "Ses düzeyi %45"
    for k in K:
        assert describe_action(Action(k, 0, 0.0, x=1, y=1, steps=1))
