"""Finger-state hysteresis and time-based dwell."""
from __future__ import annotations

from feat_synth import make_frame, make_hand
from handcontrol.contracts import FingerState
from handcontrol.features import FeatureConfig, FeatureExtractor
from handcontrol.filters import DwellLatch

EXT, BENT, UNK = FingerState.EXTENDED, FingerState.BENT, FingerState.UNKNOWN


def index_state(fx, t, c):
    hf = fx.update(make_frame(t, [make_hand([0.0, c, 0.0, 0.0, 0.0])])).hands[0]
    return hf.fingers[1]


def test_fresh_track_waits_acquire_dwell():
    fx = FeatureExtractor()
    assert index_state(fx, 0.0, 0.0).state is UNK
    assert index_state(fx, 20.0, 0.0).state is UNK
    assert index_state(fx, 60.0, 0.0).state is EXT


def test_alternating_poses_faster_than_dwell_do_not_flicker():
    fx = FeatureExtractor()
    t = 0.0
    for _ in range(4):
        index_state(fx, t, 0.0)
        t += 33.0
    seen = set()
    for k in range(30):
        seen.add(index_state(fx, t, 1.0 if k % 2 else 0.0).state)
        t += 33.0
    assert seen == {EXT}


def test_values_inside_band_hold_state():
    cfg = FeatureConfig()
    fx = FeatureExtractor(cfg)
    t = 0.0
    for _ in range(4):
        index_state(fx, t, 0.0)
        t += 33.0
    # wobble around the middle of the band for 2 s: stays EXTENDED
    for k in range(60):
        info = index_state(fx, t, 0.40 + (0.04 if k % 2 else -0.04))
        assert cfg.extend_curl < info.curl < cfg.bend_curl
        assert info.state is EXT
        t += 33.0
    for _ in range(5):
        index_state(fx, t, 1.0)
        t += 33.0
    assert index_state(fx, t, 1.0).state is BENT
    for k in range(60):
        t += 33.0
        assert index_state(fx, t, 0.40 + (0.04 if k % 2 else -0.04)).state is BENT


def test_dwell_is_time_based_not_frame_based():
    def run(step):
        fx = FeatureExtractor()
        t = 0.0
        for _ in range(4):
            index_state(fx, t, 0.0)
            t += 33.0
        state = None
        for _ in range(3):              # same frame count, different elapsed time
            state = index_state(fx, t, 1.0).state
            t += step
        return state

    assert run(10.0) is EXT             # 20 ms elapsed < 80 ms dwell
    assert run(50.0) is BENT            # 100 ms elapsed >= 80 ms dwell


def test_dwell_latch_basic():
    latch = DwellLatch("a", dwell_ms=100)
    assert latch.update("b", 0) == "a"
    assert latch.update("b", 99) == "a"
    assert latch.update("b", 100) == "b"
    assert latch.update("a", 110) == "b"
    assert latch.update("b", 120) == "b"      # proposing current state cancels pending change
    assert latch.update("a", 150) == "b"
    assert latch.update("a", 140) == "b"      # time went backwards: timer restarts
    assert latch.update("a", 239) == "b"
    assert latch.update("a", 240) == "a"
    assert latch.force("z") == "z" and latch.state == "z"
