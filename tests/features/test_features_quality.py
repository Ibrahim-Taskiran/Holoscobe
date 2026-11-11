"""Quality: degenerate input, plausibility, temporal discontinuity, latency."""
from __future__ import annotations

import math

from feat_synth import make_frame, make_hand
from handcontrol.contracts import FingerState, HandSample, Landmark, Quality
from handcontrol.features import FeatureExtractor

UNK = FingerState.UNKNOWN


def replace(hand: HandSample, idx: int, lm: Landmark) -> HandSample:
    lms = list(hand.landmarks)
    lms[idx] = lm
    return HandSample(hand.handedness, hand.handedness_score, tuple(lms), hand.world_landmarks)


def test_zero_hands():
    out = FeatureExtractor().update(make_frame(0.0, []))
    assert out.hands == () and out.identity_ambiguous is False


def test_zero_size_palm_is_unknown_without_division_error():
    hand = HandSample(make_hand().handedness, 0.9, tuple(Landmark(0.5, 0.5, 0.0) for _ in range(21)))
    hf = FeatureExtractor().update(make_frame(0.0, [hand])).hands[0]
    assert hf.quality is Quality.UNKNOWN
    assert hf.palm_scale_px == 0.0
    assert math.isinf(hf.pinch_distance)
    assert all(f.state is UNK for f in hf.fingers)


def test_nan_fingertip_makes_hand_unknown():
    hand = replace(make_hand(0.0), 12, Landmark(float("nan"), 0.4, 0.0))
    fx = FeatureExtractor()
    for t in (0.0, 33.0, 66.0, 100.0):
        hf = fx.update(make_frame(t, [hand])).hands[0]
    assert hf.quality is Quality.UNKNOWN
    assert all(f.state is UNK for f in hf.fingers)


def test_nan_palm_landmark_drops_hand():
    hand = replace(make_hand(0.0), 0, Landmark(0.5, float("inf"), 0.0))
    assert FeatureExtractor().update(make_frame(0.0, [hand])).hands == ()


def test_wrong_landmark_count_drops_only_that_hand():
    good = make_hand(0.0, center=(450.0, 240.0))
    bad = make_hand(0.0, side="left", center=(150.0, 240.0))
    bad = HandSample(bad.handedness, bad.handedness_score, bad.landmarks[:20])
    out = FeatureExtractor().update(make_frame(0.0, [bad, good]))
    assert len(out.hands) == 1 and out.hands[0].palm_center_px[0] == 450.0


def test_invalid_frame_size_returns_no_hands():
    out = FeatureExtractor().update(make_frame(0.0, [make_hand()], width=0))
    assert out.hands == ()


def test_small_hand_degraded_tiny_hand_unknown():
    fx = FeatureExtractor()
    assert fx.update(make_frame(0.0, [make_hand(scale=20.0)])).hands[0].quality is Quality.DEGRADED
    fx = FeatureExtractor()
    assert fx.update(make_frame(0.0, [make_hand(scale=8.0)])).hands[0].quality is Quality.UNKNOWN


def test_edge_on_hand_degraded():
    hf = FeatureExtractor().update(make_frame(0.0, [make_hand(yaw=85)])).hands[0]
    assert hf.quality is Quality.DEGRADED


def test_implausible_bone_length_degraded():
    hand = make_hand(0.0)
    lm = hand.landmarks
    far = Landmark(lm[8].x + 3 * (lm[8].x - lm[7].x) * 10, lm[8].y + 30 * (lm[8].y - lm[7].y), lm[8].z)
    hf = FeatureExtractor().update(make_frame(0.0, [replace(hand, 8, far)])).hands[0]
    assert hf.quality is Quality.DEGRADED


def test_usable_hand():
    hf = FeatureExtractor().update(make_frame(0.0, [make_hand(0.0)])).hands[0]
    assert hf.quality is Quality.USABLE and hf.palm_scale_px > 0


def test_high_latency_degraded():
    hf = FeatureExtractor().update(make_frame(0.0, [make_hand()], latency_ms=400.0)).hands[0]
    assert hf.quality is Quality.DEGRADED


def test_temporal_jump_degraded_then_recovers():
    fx = FeatureExtractor()
    t = 0.0
    for _ in range(4):
        hf = fx.update(make_frame(t, [make_hand(0.0, center=(250.0, 240.0))])).hands[0]
        t += 33.0
    assert hf.quality is Quality.USABLE
    hid = hf.hand_id
    # 1.2 palm units in 33 ms = 36 palm/s: inside the matching gate but implausible
    jumped = fx.update(make_frame(t, [make_hand(0.0, center=(370.0, 240.0))])).hands[0]
    assert jumped.hand_id == hid
    assert jumped.quality is Quality.DEGRADED
    assert all(f.state is UNK for f in jumped.fingers)
    for _ in range(8):
        t += 33.0
        hf = fx.update(make_frame(t, [make_hand(0.0, center=(370.0, 240.0))])).hands[0]
    assert hf.quality is Quality.USABLE
    assert all(f.state is FingerState.EXTENDED for f in hf.fingers)


def test_sudden_scale_change_degraded():
    fx = FeatureExtractor()
    fx.update(make_frame(0.0, [make_hand(scale=100.0)]))
    hf = fx.update(make_frame(33.0, [make_hand(scale=170.0)])).hands[0]
    assert hf.quality is Quality.DEGRADED


def test_normal_motion_stays_usable():
    fx = FeatureExtractor()
    for k in range(30):     # 300 px/s with 100 px palm = 3 palm/s
        hf = fx.update(make_frame(k * 33.0, [make_hand(0.0, center=(150.0 + 10 * k, 240.0))])).hands[0]
        if k > 0:
            assert hf.quality is Quality.USABLE
