from __future__ import annotations

from ctrl_helpers import G, K, LEFT, RIGHT, WIN_A, WIN_B, Rig, hand, tcfg

from handcontrol.contracts import Mode, Rect
from handcontrol.dryrun import FakeWindows


def _scroll_rig(**cfg) -> Rig:
    r = Rig(cfg=tcfg(**cfg))
    r.ctl.set_mode(Mode.SCROLL)
    r.settle(hand(palm=(320, 300)))
    return r


def _total_steps(r: Rig, kind=K.SCROLL) -> int:
    return sum(a.steps for a in r.sink.of(kind))


def test_scroll_accumulator_steps_and_dead_zone():
    r = _scroll_rig()
    r.frame(hand(palm=(320, 300)), events=[(G.PINCH_START, RIGHT)])
    r.frame(hand(palm=(320, 294)))  # 0.0125 < dead zone
    assert r.count(K.SCROLL) == 0
    for _ in range(10):  # move up 50 px = 0.104 -> 2 steps total
        r.frame(hand(palm=(320, 250)))
    assert _total_steps(r) == 2
    assert all(a.target == WIN_A for a in r.sink.of(K.SCROLL))
    r.frame(hand(palm=(320, 250)), events=[(G.PINCH_END, RIGHT)])
    for _ in range(5):
        r.frame(hand(palm=(320, 100)))
    assert _total_steps(r) == 2  # release stops


def test_scroll_direction_setting():
    r = _scroll_rig(scroll_invert=True)
    r.frame(hand(palm=(320, 300)), events=[(G.PINCH_START, RIGHT)])
    for _ in range(10):
        r.frame(hand(palm=(320, 250)))
    assert _total_steps(r) == -2


def test_scroll_rate_limit_and_bounded_accumulator():
    r = _scroll_rig()
    r.frame(hand(palm=(320, 470)), events=[(G.PINCH_START, RIGHT)])
    t_start = r.clock.now_ms()
    y = 470.0
    for _ in range(100):  # 1 s of very fast upward motion at 10 ms frames
        y -= 4.6
        r.frame(hand(palm=(320, y)), dt=10.0)
    elapsed = r.clock.now_ms() - t_start
    total = _total_steps(r)
    assert total <= 1 + elapsed * 12 / 1000 + 0.05
    assert total >= 10
    # stop moving: bounded backlog drains at most scroll_max_pending more steps
    for _ in range(100):
        r.frame(hand(palm=(320, y)), dt=10.0)
    assert _total_steps(r) - total <= 3


def test_pointer_frozen_during_scroll_but_positions_before():
    r = _scroll_rig()
    r.frame(hand(tip=(200, 200), palm=(320, 300)))
    assert r.kinds() == [K.MOVE_POINTER]
    r.frame(hand(tip=(200, 200), palm=(320, 300)), events=[(G.PINCH_START, RIGHT)])
    for i in range(10):
        r.frame(hand(tip=(100 + 10 * i, 100), palm=(320, 250)))
    assert r.count(K.MOVE_POINTER) == 1
    assert r.count(K.LEFT_CLICK) == 0


def test_scroll_refused_when_window_under_pointer_not_foreground():
    wins = FakeWindows([(WIN_B, Rect(-5000, -5000, 5000, 5000)), (WIN_A, Rect(-5000, -5000, 5000, 5000))],
                       foreground=WIN_A)
    r = Rig(windows=wins)
    r.ctl.set_mode(Mode.SCROLL)
    r.settle(hand(palm=(320, 300)))
    r.frame(hand(palm=(320, 300)), events=[(G.PINCH_START, RIGHT)])
    for _ in range(10):
        r.frame(hand(palm=(320, 200)))
    assert r.count(K.SCROLL) == 0
    assert "odakla" in r.ctl.snapshot().notice


def test_scroll_target_change_cancels_without_refocus():
    r = _scroll_rig()
    r.frame(hand(palm=(320, 300)), events=[(G.PINCH_START, RIGHT)])
    for _ in range(4):
        r.frame(hand(palm=(320, 250)))
    n = r.count(K.SCROLL)
    assert n >= 1
    r.windows.add(WIN_B, Rect(-5000, -5000, 5000, 5000))
    r.windows.foreground = WIN_B
    for _ in range(10):
        r.frame(hand(palm=(320, 150)))
    assert r.count(K.SCROLL) == n
    assert r.kinds()[-1] is K.RELEASE_ALL and r.count(K.RELEASE_ALL) == 1


# ---------------------------------------------------------------- zoom

def _hands(spread: float = 100.0):
    return (hand(RIGHT, tip=(320 + spread, 240), palm=(320 + spread, 300)),
            hand(LEFT, tip=(320 - spread, 240), palm=(320 - spread, 300)))


def _zoom_rig() -> Rig:
    r = Rig()
    r.ctl.set_mode(Mode.ZOOM)
    r.settle(*_hands())
    return r


def test_zoom_two_pinches_within_300ms_then_apart_zooms_in():
    r = _zoom_rig()
    r.frame(*_hands(), events=[(G.PINCH_START, RIGHT)])
    r.frame(*_hands(), dt=120.0)
    r.frame(*_hands(), dt=120.0, events=[(G.PINCH_START, LEFT)])  # 240 ms after the first
    for _ in range(10):
        r.frame(*_hands(130.0))  # 260/60 - 200/60 = 1.0 palm units -> 2 steps
    assert _total_steps(r, K.ZOOM) == 2
    assert r.count(K.MOVE_POINTER) == 0


def test_zoom_together_zooms_out():
    r = _zoom_rig()
    r.frame(*_hands(), events=[(G.PINCH_START, RIGHT), (G.PINCH_START, LEFT)])
    for _ in range(10):
        r.frame(*_hands(70.0))
    assert _total_steps(r, K.ZOOM) == -2


def test_zoom_second_pinch_too_late_is_ignored():
    r = _zoom_rig()
    r.frame(*_hands(), events=[(G.PINCH_START, RIGHT)])
    r.frame(*_hands(), dt=110.0)
    r.frame(*_hands(), dt=110.0)
    r.frame(*_hands(), dt=110.0, events=[(G.PINCH_START, LEFT)])  # 330 ms after the first
    assert r.count(K.RELEASE_ALL) == 0  # not a watchdog artefact
    for _ in range(10):
        r.frame(*_hands(150.0))
    assert r.count(K.ZOOM) == 0


def test_zoom_one_hand_release_cancels():
    r = _zoom_rig()
    r.frame(*_hands(), events=[(G.PINCH_START, RIGHT), (G.PINCH_START, LEFT)])
    for _ in range(4):
        r.frame(*_hands(130.0))
    n = r.count(K.ZOOM)
    assert n >= 1
    r.frame(*_hands(130.0), events=[(G.PINCH_END, LEFT)])
    assert r.kinds()[-1] is K.RELEASE_ALL
    for _ in range(10):
        r.frame(*_hands(200.0))
    assert r.count(K.ZOOM) == n
    # re-pinching the released hand alone does not resume: both must release first
    r.frame(*_hands(200.0), events=[(G.PINCH_START, LEFT)])
    for _ in range(10):
        r.frame(*_hands(100.0))
    assert r.count(K.ZOOM) == n


def test_clap_candidate_cancels_zoom_and_discards_output():
    r = _zoom_rig()
    r.frame(*_hands(), events=[(G.PINCH_START, RIGHT), (G.PINCH_START, LEFT)])
    for _ in range(3):
        r.frame(*_hands(130.0))
    n = r.count(K.ZOOM)
    assert n >= 1
    e = r.ctl.current_epoch()
    r.frame(*_hands(200.0), events=[(G.CLAP_CANDIDATE_START,)])
    assert r.ctl.current_epoch() > e
    assert r.kinds()[-1] is K.RELEASE_ALL
    for _ in range(10):
        r.frame(*_hands(250.0))
    assert r.count(K.ZOOM) == n
