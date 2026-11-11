from __future__ import annotations

from ctrl_helpers import G, K, RIGHT, Rig, desktop, hand, tcfg

from handcontrol.controller import ExpSmoother
from handcontrol.dryrun import make_monitor


def test_no_pointer_motion_before_neutral():
    r = Rig()
    r.frame(hand(tip=(100, 100)))
    r.frame(hand(tip=(120, 100)))
    assert r.kinds() == []
    for _ in range(8):
        r.frame(hand(tip=(140, 100)))
    assert r.count(K.MOVE_POINTER) >= 1


def test_pointer_moves_to_mapped_point_and_skips_duplicates():
    r = Rig()
    r.settle(hand(tip=(320, 240)))
    r.frame(hand(tip=(160, 120)))
    r.frame(hand(tip=(160, 120)))
    moves = r.sink.of(K.MOVE_POINTER)
    assert len(moves) == 1
    assert (moves[0].x, moves[0].y) == desktop((160, 120))


def test_no_move_when_index_not_extended():
    r = Rig()
    r.settle(hand(tip=(320, 240)))
    r.frame(hand(tip=(100, 100), index=False))
    assert r.kinds() == []


def test_zero_clicks_during_pointer_only_sweep():
    r = Rig()
    r.settle(hand())
    for i in range(60):
        r.frame(hand(tip=(20 + 10 * i, 50 + 6 * i)))
    assert r.count(K.LEFT_CLICK) == 0
    assert set(r.kinds()) == {K.MOVE_POINTER}


def test_brief_pinch_clicks_once_at_latched_point():
    r = Rig()
    r.settle(hand(tip=(300, 200)))
    r.frame(hand(tip=(320, 240)))
    latched = desktop((320, 240))
    r.frame(hand(tip=(320, 240)), events=[(G.PINCH_START, RIGHT)])
    r.frame(hand(tip=(322, 241)))
    r.frame(hand(tip=(323, 241)), events=[(G.PINCH_END, RIGHT)])
    clicks = r.sink.of(K.LEFT_CLICK)
    assert len(clicks) == 1 and (clicks[0].x, clicks[0].y) == latched
    assert r.kinds() == [K.MOVE_POINTER, K.LEFT_CLICK]  # pointer frozen during pinch


def test_long_pinch_cancels_click():
    r = Rig()
    r.settle(hand())
    r.frame(hand(), events=[(G.PINCH_START, RIGHT)])
    for _ in range(14):  # ~470 ms
        r.frame(hand())
    r.frame(hand(), events=[(G.PINCH_END, RIGHT)])
    assert r.count(K.LEFT_CLICK) == 0


def test_moving_pinch_cancels_click():
    r = Rig()
    r.settle(hand())
    r.frame(hand(), events=[(G.PINCH_START, RIGHT)])
    r.frame(hand(tip=(330, 240)))  # ~30 px desktop at 1.0 DPI > 15
    r.frame(hand(), events=[(G.PINCH_END, RIGHT)])
    assert r.count(K.LEFT_CLICK) == 0


def test_click_threshold_scales_with_dpi():
    # 6 camera px -> 18 physical px: over 15 at 100 %, under 22.5 at 150 %.
    for dpi, expected in ((1.0, 0), (1.5, 1)):
        r = Rig(monitors=[make_monitor(0, 0, 1920, 1080, dpi, primary=True)])
        r.settle(hand())
        r.frame(hand(), events=[(G.PINCH_START, RIGHT)])
        r.frame(hand(tip=(326, 240)))
        r.frame(hand(tip=(326, 240)), events=[(G.PINCH_END, RIGHT)])
        assert r.count(K.LEFT_CLICK) == expected, dpi


def test_clap_candidate_cancels_pending_click():
    r = Rig()
    r.settle(hand())
    r.frame(hand(), events=[(G.PINCH_START, RIGHT)])
    r.frame(hand(), events=[(G.CLAP_CANDIDATE_START,)])
    r.frame(hand(), events=[(G.PINCH_END, RIGHT)])
    assert r.count(K.LEFT_CLICK) == 0


def test_stale_frame_produces_no_action():
    r = Rig()
    r.settle(hand(tip=(320, 240)))
    r.frame(hand(tip=(100, 100)), latency=151)
    assert r.kinds() == []
    r.frame(hand(tip=(100, 100)), latency=149)
    assert r.kinds() == [K.MOVE_POINTER]


def test_dominant_hand_setting_and_ignored_other_hand():
    r = Rig()
    r.settle(hand())
    r.frame(hand(hid=2, tip=(100, 100)))  # left hand only
    assert r.kinds() == []


def test_injected_smoother_is_used():
    sm = ExpSmoother(tau_ms=1000.0)
    r = Rig(smoother=sm)
    r.settle(hand(tip=(320, 240)))
    r.frame(hand(tip=(0, 240)))
    m = r.sink.of(K.MOVE_POINTER)[-1]
    assert m.x > desktop((0, 240))[0] + 100  # heavily smoothed, not a jump


def test_mirror_flips_x():
    r = Rig(cfg=tcfg(mirror=True))
    r.settle(hand(tip=(320, 240)))
    r.frame(hand(tip=(0, 240)))
    m = r.sink.of(K.MOVE_POINTER)[-1]
    assert m.x == 1919
