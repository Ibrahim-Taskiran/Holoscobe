from __future__ import annotations

from ctrl_helpers import G, K, LEFT, RIGHT, WIN_A, Rig, hand

from handcontrol.contracts import ControlState, Mode
from handcontrol.controller import MenuKind
from handcontrol.dryrun import FakeWindows, make_monitor

TWO = [make_monitor(0, 0, 1920, 1080, 1.0, primary=True), make_monitor(1920, 0, 1920, 1080, 1.5)]

# virtual pointer rows for the 4-item window overlay when anchored at tip y=240
Y_MINIMIZE, Y_MAXIMIZE, Y_OTHER, Y_CLOSE = 170, 220, 245, 310


def _win_rig(**kw) -> Rig:
    r = Rig(**kw)
    r.ctl.set_mode(Mode.WINDOWS)
    r.settle(hand())
    return r


def _open_overlay(r: Rig) -> None:
    r.frame(hand(), events=[(G.PINCH_START, RIGHT)])
    r.frame(hand())
    r.frame(hand(), events=[(G.PINCH_END, RIGHT)])
    m = r.ctl.snapshot().menu
    assert m is not None and m.kind is MenuKind.WINDOW and m.target == WIN_A


def _hover(r: Rig, y: float, events=()) -> None:
    r.frame(hand(tip=(320, y)), events=events)


def test_short_pinch_opens_overlay_without_click():
    r = _win_rig()
    _open_overlay(r)
    assert r.kinds() == []


def test_hold_250ms_starts_drag_and_cannot_open_overlay():
    r = _win_rig()
    r.frame(hand(), events=[(G.PINCH_START, RIGHT)])
    for _ in range(8):  # ~267 ms
        r.frame(hand())
    assert r.kinds() == [K.WINDOW_DRAG_BEGIN]
    for i in range(5):
        r.frame(hand(tip=(330 + 10 * i, 240)))
    r.frame(hand(tip=(380, 240)), events=[(G.PINCH_END, RIGHT)])
    kinds = r.kinds()
    assert kinds[0] is K.WINDOW_DRAG_BEGIN and kinds[-1] is K.WINDOW_DRAG_END
    assert set(kinds[1:-1]) == {K.WINDOW_DRAG_MOVE}
    assert all(a.target == WIN_A for a in r.sink.actions)
    assert r.ctl.snapshot().menu is None


def test_drag_move_rate_limited_to_30_per_second():
    r = _win_rig()
    r.frame(hand(), events=[(G.PINCH_START, RIGHT)])
    for _ in range(8):
        r.frame(hand())
    start = r.clock.now_ms()
    for i in range(100):
        r.frame(hand(tip=(100 + 4 * i, 240)), dt=10.0)
    elapsed = r.clock.now_ms() - start
    n = r.count(K.WINDOW_DRAG_MOVE)
    assert 25 <= n <= 1 + elapsed * 30 / 1000 + 0.05


def test_drag_target_vanishes_cancels_with_release():
    r = _win_rig()
    r.frame(hand(), events=[(G.PINCH_START, RIGHT)])
    for _ in range(8):
        r.frame(hand())
    r.frame(hand(tip=(340, 240)))
    r.windows.remove(WIN_A)
    r.frame(hand(tip=(360, 240)))
    r.frame(hand(tip=(380, 240)), events=[(G.PINCH_END, RIGHT)])
    assert r.kinds()[-1] is K.RELEASE_ALL
    assert r.count(K.WINDOW_DRAG_END) == 0


def test_pause_during_drag_releases_and_stops():
    r = _win_rig()
    r.frame(hand(), events=[(G.PINCH_START, RIGHT)])
    for _ in range(8):
        r.frame(hand())
    r.frame(hand(tip=(340, 240)))
    r.ctl.pause()
    assert r.kinds()[-1] is K.RELEASE_ALL
    n = len(r.kinds())
    r.frame(hand(tip=(400, 240)), events=[(G.PINCH_END, RIGHT)])
    assert len(r.kinds()) == n and r.count(K.WINDOW_DRAG_END) == 0


def test_no_window_under_pointer_does_nothing():
    r = _win_rig(windows=FakeWindows([]))
    r.frame(hand(), events=[(G.PINCH_START, RIGHT)])
    for _ in range(10):
        r.frame(hand())
    r.frame(hand(), events=[(G.PINCH_END, RIGHT)])
    assert r.kinds() == [] and r.ctl.snapshot().menu is None


def test_overlay_minimize_fires_once():
    r = _win_rig()
    _open_overlay(r)
    _hover(r, Y_MINIMIZE)
    assert r.ctl.snapshot().menu.hovered == 0
    _hover(r, Y_MINIMIZE, events=[(G.PINCH_START, RIGHT)])
    _hover(r, Y_MINIMIZE)
    _hover(r, Y_MINIMIZE, events=[(G.PINCH_END, RIGHT)])
    _hover(r, Y_MINIMIZE, events=[(G.PINCH_START, RIGHT)])
    assert r.kinds() == [K.WINDOW_MINIMIZE]
    assert r.ctl.snapshot().menu is None


def test_overlay_maximize():
    r = _win_rig()
    _open_overlay(r)
    _hover(r, Y_MAXIMIZE)
    _hover(r, Y_MAXIMIZE, events=[(G.PINCH_START, RIGHT)])
    assert r.kinds() == [K.WINDOW_TOGGLE_MAXIMIZE]


def test_move_to_other_monitor_disabled_with_one_display():
    r = _win_rig()
    _open_overlay(r)
    m = r.ctl.snapshot().menu
    assert [i.enabled for i in m.items] == [True, True, False, True]
    _hover(r, Y_OTHER, events=[(G.PINCH_START, RIGHT)])
    assert r.kinds() == [] and r.ctl.snapshot().menu is not None

    r2 = _win_rig(monitors=TWO)
    _open_overlay(r2)
    _hover(r2, Y_OTHER, events=[(G.PINCH_START, RIGHT)])
    assert r2.kinds() == [K.WINDOW_MOVE_TO_OTHER_MONITOR]


def _arm_close(r: Rig) -> None:
    _hover(r, Y_CLOSE)
    _hover(r, Y_CLOSE, events=[(G.PINCH_START, RIGHT)])
    m = r.ctl.snapshot().menu
    assert m.close_armed and m.hovered == 3


def test_close_needs_release_then_fresh_1s_hold_exactly_one_close():
    r = _win_rig()
    _open_overlay(r)
    _arm_close(r)
    for _ in range(45):  # holding the arming pinch for 1.5 s does nothing
        _hover(r, Y_CLOSE)
    assert r.count(K.WINDOW_CLOSE) == 0
    _hover(r, Y_CLOSE, events=[(G.PINCH_END, RIGHT)])
    _hover(r, Y_CLOSE, events=[(G.PINCH_START, RIGHT)])
    for _ in range(25):  # ~835 ms
        _hover(r, Y_CLOSE)
    assert r.count(K.WINDOW_CLOSE) == 0
    assert 0.7 < r.ctl.snapshot().menu.hold_progress < 1.0
    for _ in range(10):
        _hover(r, Y_CLOSE)
    assert r.kinds() == [K.WINDOW_CLOSE]
    assert r.sink.actions[0].target == WIN_A
    assert r.ctl.snapshot().menu is None


def test_close_early_release_cancels():
    r = _win_rig()
    _open_overlay(r)
    _arm_close(r)
    _hover(r, Y_CLOSE, events=[(G.PINCH_END, RIGHT)])
    _hover(r, Y_CLOSE, events=[(G.PINCH_START, RIGHT)])
    for _ in range(15):  # 500 ms
        _hover(r, Y_CLOSE)
    _hover(r, Y_CLOSE, events=[(G.PINCH_END, RIGHT)])
    for _ in range(40):
        _hover(r, Y_CLOSE)
    assert r.count(K.WINDOW_CLOSE) == 0
    m = r.ctl.snapshot().menu
    assert m is not None and not m.close_armed


def test_close_hold_cancelled_by_hover_change_and_target_loss():
    r = _win_rig()
    _open_overlay(r)
    _arm_close(r)
    _hover(r, Y_CLOSE, events=[(G.PINCH_END, RIGHT)])
    _hover(r, Y_CLOSE, events=[(G.PINCH_START, RIGHT)])
    _hover(r, Y_MAXIMIZE)  # target item changed
    for _ in range(40):
        _hover(r, Y_CLOSE)
    assert r.count(K.WINDOW_CLOSE) == 0

    r2 = _win_rig()
    _open_overlay(r2)
    _arm_close(r2)
    _hover(r2, Y_CLOSE, events=[(G.PINCH_END, RIGHT)])
    _hover(r2, Y_CLOSE, events=[(G.PINCH_START, RIGHT)])
    r2.windows.remove(WIN_A)
    for _ in range(40):
        _hover(r2, Y_CLOSE)
    assert r2.count(K.WINDOW_CLOSE) == 0 and r2.ctl.snapshot().menu is None


def test_close_hold_cancelled_by_ambiguity_and_pause():
    r = _win_rig()
    _open_overlay(r)
    _arm_close(r)
    _hover(r, Y_CLOSE, events=[(G.PINCH_END, RIGHT)])
    _hover(r, Y_CLOSE, events=[(G.PINCH_START, RIGHT)])
    r.frame(hand(tip=(320, Y_CLOSE)), ambiguous=True)
    for _ in range(40):
        _hover(r, Y_CLOSE)
    assert r.count(K.WINDOW_CLOSE) == 0

    r2 = _win_rig()
    _open_overlay(r2)
    _arm_close(r2)
    r2.ctl.pause()
    assert r2.ctl.snapshot().menu is None
    assert r2.ctl.snapshot().state is ControlState.PAUSED


def test_menu_freezes_os_pointer():
    r = _win_rig()
    _open_overlay(r)
    for i in range(20):
        r.frame(hand(tip=(100 + 20 * i, 240)))
    assert r.kinds() == []


def test_menu_times_out_after_5s_without_interaction():
    r = _win_rig()
    _open_overlay(r)
    r.frame(hand())  # sets hovered (interaction)
    r.clock.advance(4990.0)
    r.ctl.tick()
    assert r.ctl.snapshot().menu is not None
    r.clock.advance(20.0)
    r.ctl.tick()
    assert r.ctl.snapshot().menu is None
    assert [k for k in r.kinds() if k is not K.RELEASE_ALL] == []  # watchdog may release


# ---------------------------------------------------------------- mode menu

def _both(tip_y: float = 240.0):
    return hand(RIGHT, tip=(420, tip_y)), hand(LEFT, tip=(200, 240))


def test_mode_menu_opens_on_dwell_and_selects_mode():
    r = Rig()
    r.settle(*_both())
    r.frame(*_both(), events=[(G.MENU_DWELL_COMPLETE, LEFT)])
    m = r.ctl.snapshot().menu
    assert m is not None and m.kind is MenuKind.MODE and len(m.items) == 5
    e = r.ctl.current_epoch()
    r.frame(*_both(192.0))  # row 1 = scroll
    assert r.ctl.snapshot().menu.hovered == 1
    r.frame(*_both(192.0), events=[(G.PINCH_START, RIGHT)])
    s = r.ctl.snapshot()
    assert s.mode is Mode.SCROLL and s.menu is None and s.epoch > e and s.needs_neutral
    assert r.kinds() == []


def test_mode_menu_blocked_while_engaged_and_freezes_pointer():
    r = Rig()
    r.settle(*_both())
    r.frame(*_both(), events=[(G.PINCH_START, RIGHT)])
    r.frame(*_both(), events=[(G.MENU_DWELL_COMPLETE, LEFT)])
    assert r.ctl.snapshot().menu is None
    r.frame(*_both(), events=[(G.PINCH_END, RIGHT)])
    r.frame(*_both(), events=[(G.MENU_DWELL_COMPLETE, LEFT)])
    assert r.ctl.snapshot().menu is not None
    r.sink.clear()
    for i in range(10):
        r.frame(hand(RIGHT, tip=(300 + 10 * i, 240)), hand(LEFT, tip=(200, 240)))
    assert r.kinds() == []
