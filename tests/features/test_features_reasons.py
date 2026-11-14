"""Reason codes for DEGRADED/UNKNOWN hands (diagnostics only; output must stay identical)."""
from __future__ import annotations

import hashlib
from dataclasses import fields

from feat_synth import make_frame, make_hand
from handcontrol.contracts import FrameFeatures, HandSample, Handedness, Landmark, Quality
from handcontrol.features import FeatureExtractor


def reasons_of(fx: FeatureExtractor, hf) -> tuple[str, ...]:
    return fx.last_reasons.get(hf.hand_id, ())


def test_usable_hand_has_no_reasons():
    fx = FeatureExtractor()
    out = fx.update(make_frame(0.0, [make_hand(0.0)]))
    assert out.hands[0].quality is Quality.USABLE
    assert fx.last_reasons == {} and fx.last_frame_reasons == ()


def test_palm_small_and_palm_tiny():
    fx = FeatureExtractor()
    hf = fx.update(make_frame(0.0, [make_hand(scale=20.0)])).hands[0]
    assert "palm_small" in reasons_of(fx, hf)
    fx = FeatureExtractor()
    hf = fx.update(make_frame(0.0, [make_hand(scale=8.0)])).hands[0]
    assert hf.quality is Quality.UNKNOWN and reasons_of(fx, hf) == ("palm_tiny",)


def test_palm_edge_on():
    fx = FeatureExtractor()
    hf = fx.update(make_frame(0.0, [make_hand(yaw=85)])).hands[0]
    assert "palm_edge_on" in reasons_of(fx, hf)


def test_bone_ratio():
    hand = make_hand(0.0)
    lm = list(hand.landmarks)
    lm[8] = Landmark(lm[8].x + 0.5, lm[8].y - 0.5, lm[8].z)
    bad = HandSample(hand.handedness, hand.handedness_score, tuple(lm), hand.world_landmarks)
    fx = FeatureExtractor()
    hf = fx.update(make_frame(0.0, [bad])).hands[0]
    assert "bone_ratio" in reasons_of(fx, hf)


def test_slow_processing():
    fx = FeatureExtractor()
    hf = fx.update(make_frame(0.0, [make_hand()], latency_ms=400.0)).hands[0]
    assert reasons_of(fx, hf) == ("slow_processing",)


def test_discontinuity_speed_then_hold():
    fx = FeatureExtractor()
    t = 0.0
    for _ in range(4):
        fx.update(make_frame(t, [make_hand(0.0, center=(250.0, 240.0))]))
        t += 33.0
    hf = fx.update(make_frame(t, [make_hand(0.0, center=(370.0, 240.0))])).hands[0]
    assert reasons_of(fx, hf) == ("discontinuity_speed",)
    t += 33.0
    hf = fx.update(make_frame(t, [make_hand(0.0, center=(370.0, 240.0))])).hands[0]
    assert reasons_of(fx, hf) == ("discontinuity_hold",)


def test_discontinuity_scale():
    fx = FeatureExtractor()
    fx.update(make_frame(0.0, [make_hand(scale=100.0)]))
    hf = fx.update(make_frame(33.0, [make_hand(scale=170.0)])).hands[0]
    assert "discontinuity_scale" in reasons_of(fx, hf)


def test_overlap_and_same_handedness_frame_reasons():
    a = make_hand(center=(330.0, 240.0))
    b = make_hand(side="left", center=(300.0, 240.0))
    fx = FeatureExtractor()
    out = fx.update(make_frame(0.0, [a, b]))
    assert "overlap" in fx.last_frame_reasons
    assert all("identity_ambiguous" in reasons_of(fx, h) for h in out.hands)
    fx = FeatureExtractor()
    fx.update(make_frame(0.0, [make_hand(center=(450.0, 240.0)),
                               make_hand(side="left", center=(150.0, 240.0), handedness=Handedness.RIGHT)]))
    assert "same_handedness" in fx.last_frame_reasons


def test_reasons_cleared_every_update():
    fx = FeatureExtractor()
    fx.update(make_frame(0.0, [make_hand(scale=20.0)]))
    assert fx.last_reasons
    fx.update(make_frame(500.0, [make_hand(0.0)]))
    assert fx.last_reasons == {} and fx.last_frame_reasons == ()


def test_reasons_travel_on_frame_without_changing_equality():
    fx = FeatureExtractor()
    ff = fx.update(make_frame(0.0, [make_hand(scale=20.0)]))
    per_hand, frame = ff.reasons
    assert per_hand == fx.last_reasons and frame == fx.last_frame_reasons
    assert [f.name for f in fields(FrameFeatures)] == [
        "capture_ms", "inference_done_ms", "width", "height", "hands", "identity_ambiguous"]
    plain = FrameFeatures(ff.capture_ms, ff.inference_done_ms, ff.width, ff.height, ff.hands, ff.identity_ambiguous)
    assert ff == plain


def _scenario(fx: FeatureExtractor) -> str:
    out = []
    t = 0.0
    for i in range(12):   # motion, a jump (i=5), latency spike (i=3), curl change, scale change (i=9)
        hand = make_hand(0.0 if i < 8 else 0.9, center=(250.0 + 12 * i + (120 if i == 5 else 0), 240.0),
                         scale=100.0 if i != 9 else 170.0)
        out.append(fx.update(make_frame(t, [hand], latency_ms=20.0 if i != 3 else 300.0)))
        t += 33.0
    for i in range(6):    # two crossing hands, one same-handedness frame
        out.append(fx.update(make_frame(t, [
            make_hand(0.0, center=(300.0 + 40 * i, 240.0)),
            make_hand(0.3, side="left", center=(500.0 - 40 * i, 240.0),
                      handedness=Handedness.RIGHT if i == 2 else None)])))
        t += 33.0
    out.append(fx.update(make_frame(t, [make_hand(scale=8.0)])))
    out.append(fx.update(make_frame(t + 500, [make_hand(yaw=85)])))
    out.append(fx.update(make_frame(float("nan"), [])))
    return hashlib.sha256(chr(10).join(repr(o) for o in out).encode()).hexdigest()


def test_output_unchanged_for_scenario():
    """Digest recorded from the pre-diagnostics implementation: FrameFeatures output must not change."""
    assert _scenario(FeatureExtractor()) == "a08c96373129db0d1368e7fb7eb0d6c8b3b6e583eb7d15d75943512b8b2afb4e"
