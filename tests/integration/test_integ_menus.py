"""Windows mode (drag vs overlay, close confirmation) and the mode menu through the real chain."""
from __future__ import annotations

from handcontrol.contracts import ActionKind as A, Mode
from handcontrol.controller import MenuKind

from integ_synth import OPEN, PINCH, POINT, Rig, TARGET, hand, lerp
from integ_synth import FIST, V

R0 = (220.0, 260.0)
LP = (440.0, 300.0)            # non-dominant palm


def _windows(rig: Rig) -> Rig:
    rig.pipe.set_mode(Mode.WINDOWS)
    rig.activate([hand(POINT, R0)])
    return rig


def _menu(rig: Rig):
    return rig.ctl.snapshot().menu


def test_hold_250ms_drags_window_without_overlay(rig):
    _windows(rig)
    rig.run(400, [hand(PINCH, R0)])                                   # 70 ms debounce + 250 ms hold
    assert rig.count(A.WINDOW_DRAG_BEGIN) == 1
    t0 = rig.t
    rig.run(500, lambda u: [hand(PINCH, (lerp(220, 320, u), 260))])
    moves = rig.count(A.WINDOW_DRAG_MOVE)
    assert 3 <= moves <= 1 + (rig.t - t0) * 30 / 1000
    rig.run(200, [hand(POINT, (320, 260))])
    assert rig.count(A.WINDOW_DRAG_END) == 1
    assert _menu(rig) is None
    assert rig.count(A.LEFT_CLICK) == 0
    drag = [a for a in rig.sink.actions if a.kind.value.startswith("window_drag")]
    assert drag[0].kind is A.WINDOW_DRAG_BEGIN and drag[-1].kind is A.WINDOW_DRAG_END
    assert all(a.target == TARGET for a in drag)


def test_short_pinch_opens_overlay_without_click_or_drag(rig):
    _windows(rig)
    rig.run(120, [hand(PINCH, R0)])
    rig.run(150, [hand(POINT, R0)])
    m = _menu(rig)
    assert m is not None and m.kind is MenuKind.WINDOW and m.target == TARGET
    assert set(rig.kinds()) <= {A.MOVE_POINTER}


def _open_overlay(rig: Rig) -> None:
    _windows(rig)
    rig.run(120, [hand(PINCH, R0)])
    rig.run(150, [hand(POINT, R0)])
    assert _menu(rig) is not None


def test_close_needs_release_then_fresh_1s_hold(rig):
    _open_overlay(rig)
    low = (220.0, 340.0)                                              # pointer to the bottom item (close)
    rig.run(200, lambda u: [hand(POINT, (220, lerp(260, 340, u)))])
    assert _menu(rig).items[_menu(rig).hovered].key == "close"
    rig.run(150, [hand(PINCH, low)])                                  # arm the confirmation
    assert _menu(rig).close_armed
    rig.run(1200, [hand(PINCH, low)])                                 # holding the arming pinch: no close
    assert rig.count(A.WINDOW_CLOSE) == 0
    rig.run(150, [hand(POINT, low)])                                  # release
    rig.run(600, [hand(PINCH, low)])                                  # too short
    rig.run(150, [hand(POINT, low)])                                  # release cancels the confirmation
    assert rig.count(A.WINDOW_CLOSE) == 0 and not _menu(rig).close_armed
    rig.run(150, [hand(PINCH, low)])                                  # arm again
    rig.run(150, [hand(POINT, low)])                                  # release
    rig.run(1200, [hand(PINCH, low)])                                 # fresh 1 s hold
    assert rig.count(A.WINDOW_CLOSE) == 1
    assert rig.sink.of(A.WINDOW_CLOSE)[0].target == TARGET
    rig.run(1500, [hand(PINCH, low)])
    assert rig.count(A.WINDOW_CLOSE) == 1


def test_overlay_minimize_executes_once(rig):
    _open_overlay(rig)
    rig.run(200, lambda u: [hand(POINT, (220, lerp(260, 180, u)))])   # top item
    assert _menu(rig).items[_menu(rig).hovered].key == "minimize"
    rig.run(150, [hand(PINCH, (220, 180))])
    rig.run(300, [hand(POINT, (220, 180))])
    assert rig.count(A.WINDOW_MINIMIZE) == 1
    assert _menu(rig) is None


def test_overlay_times_out_after_5s(rig):
    _open_overlay(rig)
    rig.run(5200, [hand(POINT, R0)])
    assert _menu(rig) is None


def test_overlay_times_out_on_tick_without_frames(rig):
    _open_overlay(rig)
    rig.clock.advance(5100)
    rig.pipe.tick()
    assert _menu(rig) is None


# ---------------- mode menu


def _dwell(rig: Rig, ms: float = 900, dom=POINT) -> None:
    rig.run(ms, [hand(dom, R0), hand(V, LP, side="left")])


def test_left_v_opens_the_wheel_and_freezes_os(rig):
    rig.activate([hand(POINT, R0), hand(POINT, LP, side="left")])
    _dwell(rig)
    m = _menu(rig)
    assert m is not None and m.kind is MenuKind.MODE
    n = len(rig.sink.actions)
    rig.run(400, lambda u: [hand(POINT, (lerp(220, 300, u), 260)), hand(V, LP, side="left")])
    assert len(rig.sink.actions) == n                                 # OS pointer frozen


def test_wheel_pick_by_fist_then_pointer_recovers(rig):
    """Wheel -> Diğer -> Pencereler with the left hand only. The picking fist must not restore a window, and
    the new mode starts after a fresh neutral."""
    rig.activate([hand(POINT, R0), hand(POINT, LP, side="left")])
    _dwell(rig)

    def aim(dx, dy, pose, ms=250):
        rig.run(ms, [hand(POINT, R0), hand(pose, (LP[0] + dx, LP[1] + dy), side="left")])
    more = (-90.0, -52.0)                                            # slice 5 of 6, mirrored camera below
    sign = -1.0 if rig.ctl.config.mirror else 1.0
    aim(sign * more[0], more[1], V)
    assert _menu(rig).items[_menu(rig).hovered].key == "more"
    aim(sign * more[0], more[1], FIST)
    assert [i.key for i in _menu(rig).items] == ["zoom", "volume", "windows", "back"]
    aim(0, 0, V)
    aim(0, 95, V)                                                    # down = slice 2 of 4
    assert _menu(rig).items[_menu(rig).hovered].key == "windows"
    aim(0, 95, FIST, 400)
    assert rig.mode is Mode.WINDOWS and _menu(rig) is None
    aim(0, 95, FIST, 800)                                            # still a fist: nothing else happens
    assert set(rig.kinds()) <= {A.MOVE_POINTER}
    n = rig.count(A.MOVE_POINTER)
    rig.run(500, [hand(POINT, R0), hand(POINT, LP, side="left")])    # release + neutral
    rig.run(400, lambda u: [hand(POINT, (lerp(220, 320, u), 260))])
    assert rig.count(A.MOVE_POINTER) > n + 3
    assert rig.count(A.WINDOW_RESTORE) == 0 and rig.count(A.WINDOW_DRAG_BEGIN) == 0


def test_open_palm_cancels_and_a_lost_hand_never_picks(rig):
    rig.activate([hand(POINT, R0), hand(POINT, LP, side="left")])
    _dwell(rig)
    rig.run(200, [hand(POINT, R0), hand(V, (LP[0], LP[1] - 90), side="left")])
    rig.run(400, [hand(POINT, R0), hand(OPEN, (LP[0], LP[1] - 90), side="left")])
    assert _menu(rig) is None and rig.mode is Mode.POINTER
    rig.run(400, [hand(POINT, R0), hand(POINT, LP, side="left")])
    _dwell(rig)
    rig.run(200, [hand(POINT, R0), hand(V, (LP[0] + 90, LP[1] + 50), side="left")])
    rig.run(1200, [hand(POINT, R0)])
    assert _menu(rig) is None and rig.mode is Mode.POINTER


def test_tray_mode_change_while_pinched_does_not_stick(rig):
    rig.activate([hand(POINT, R0)])
    rig.run(120, [hand(PINCH, R0)])
    rig.pipe.set_mode(Mode.SCROLL)
    rig.run(300, [hand(PINCH, R0)])
    rig.run(400, [hand(POINT, R0)])
    n = rig.count(A.MOVE_POINTER)
    rig.run(400, lambda u: [hand(POINT, (lerp(220, 320, u), 260))])
    assert rig.count(A.MOVE_POINTER) > n + 3
    assert rig.count(A.SCROLL) == 0


def test_dominant_v_does_not_open_the_wheel(rig):
    rig.activate([hand(V, R0)])
    rig.run(1000, [hand(V, R0)])
    assert _menu(rig) is None


def test_wheel_needs_v_release_before_reopening(rig):
    rig.activate([hand(POINT, R0), hand(POINT, LP, side="left")])
    _dwell(rig)
    rig.clock.advance(0)
    rig.run(5300, [hand(POINT, R0), hand(V, LP, side="left")])       # timeout, V still held
    assert _menu(rig) is None
    rig.run(300, [hand(POINT, R0), hand(POINT, LP, side="left")])    # release
    _dwell(rig)
    assert _menu(rig) is not None
