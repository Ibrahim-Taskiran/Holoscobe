"""Hand loss, watchdog, stale samples and ID swaps through the real chain."""
from __future__ import annotations

from handcontrol.contracts import ActionKind as A, ControlState, Mode

from integ_synth import PINCH, POINT, Rig, hand, lerp

R0 = (220.0, 260.0)
DRAG = (A.WINDOW_DRAG_BEGIN, A.WINDOW_DRAG_MOVE, A.WINDOW_DRAG_END)


def _dragging(rig: Rig) -> None:
    rig.pipe.set_mode(Mode.WINDOWS)
    rig.activate([hand(POINT, R0)])
    rig.run(400, [hand(PINCH, R0)])
    rig.run(300, lambda u: [hand(PINCH, (lerp(220, 300, u), 260))])
    assert rig.count(A.WINDOW_DRAG_BEGIN) == 1 and rig.count(A.WINDOW_DRAG_MOVE) >= 2


def test_hand_lost_mid_drag_releases_and_never_replays(rig):
    _dragging(rig)
    mark = len(rig.sink.actions)
    rig.frame([])                                         # tracker loses the hand
    assert A.RELEASE_ALL in [a.kind for a in rig.sink.actions[mark:]]
    rig.run(300, [])
    mark = len(rig.sink.actions)
    rig.run(600, lambda u: [hand(PINCH, (lerp(300, 380, u), 260))])   # back, still pinched, moving
    assert not [a for a in rig.sink.actions[mark:] if a.kind in DRAG + (A.LEFT_CLICK,)]
    rig.run(300, [hand(POINT, (380, 260))])               # release + fresh neutral
    rig.run(400, [hand(PINCH, (380, 260))])
    assert rig.count(A.WINDOW_DRAG_BEGIN) == 2            # fresh engagement works again


def test_watchdog_releases_within_200ms_without_frames(rig):
    _dragging(rig)
    last_capture = rig.t - 1000.0 / rig.fps
    mark = len(rig.sink.actions)
    rig.clock.set(last_capture + 190)
    rig.pipe.tick()
    assert A.RELEASE_ALL not in [a.kind for a in rig.sink.actions[mark:]]
    rig.clock.set(last_capture + 205)
    rig.pipe.tick()
    assert A.RELEASE_ALL in [a.kind for a in rig.sink.actions[mark:]]
    rig.gap(300)
    mark = len(rig.sink.actions)
    rig.run(500, [hand(PINCH, (300, 260))])               # frames resume, hand still pinched
    assert not [a for a in rig.sink.actions[mark:] if a.kind in DRAG]


def test_watchdog_thread_runs_and_stops(rig):
    rig.pipe.start()
    try:
        assert rig.ctl.watchdog.running
    finally:
        rig.pipe.stop()
    assert not rig.ctl.watchdog.running


def test_stale_samples_produce_no_action(rig):
    rig.activate([hand(POINT, R0)])
    rig.sink.clear()
    t0 = rig.t
    while rig.t < t0 + 600:
        u = (rig.t - t0) / 600
        rig.frame([hand(POINT, (lerp(220, 420, u), 260))], age_ms=180)
    assert rig.kinds() == []


def test_single_stale_frame_freezes_then_fresh_frames_resume(rig):
    rig.activate([hand(POINT, R0)])
    rig.run(200, lambda u: [hand(POINT, (lerp(220, 260, u), 260))])
    n = rig.count(A.MOVE_POINTER)
    rig.frame([hand(POINT, (300, 260))], age_ms=160)
    assert rig.count(A.MOVE_POINTER) == n
    rig.run(300, lambda u: [hand(POINT, (lerp(300, 360, u), 260))])
    assert rig.count(A.MOVE_POINTER) > n


def test_slow_inference_degrades_quality_and_blocks_actions(rig):
    rig.activate([hand(POINT, R0)])
    rig.sink.clear()
    from integ_synth import sample
    for i in range(15):
        x = 220 + 10 * i
        rig.clock.set(rig.t + 30)
        rig.pipe.process(sample(rig.t, [hand(POINT, (x, 260))], latency_ms=170))   # inference 170 ms
        rig.t += 33.3
    assert rig.kinds() == []


def test_crossing_mid_scroll_cancels_and_needs_re_engagement(rig):
    """Identity may swap at the crossing; nothing may continue from the old engagement."""
    rig.pipe.set_mode(Mode.SCROLL)
    rig.activate([hand(POINT, (150, 300)), hand(POINT, (490, 300), side="left")])
    rig.run(150, [hand(PINCH, (150, 300)), hand(POINT, (490, 300), side="left")])
    rig.run(500, lambda u: [hand(PINCH, (lerp(150, 490, u), lerp(300, 250, u))),
                            hand(POINT, (lerp(490, 150, u), 300), side="left")])
    mark = len(rig.sink.actions)
    rig.run(600, lambda u: [hand(PINCH, (490, lerp(250, 150, u))), hand(POINT, (150, 300), side="left")])
    assert not [a for a in rig.sink.actions[mark:] if a.kind is A.SCROLL]
    assert rig.state is ControlState.ACTIVE
