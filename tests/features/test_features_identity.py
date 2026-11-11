"""Stable hand IDs, loss/recovery, crossing hands, ambiguity flag."""
from __future__ import annotations

from feat_synth import make_frame, make_hand
from handcontrol.contracts import Handedness, Quality
from handcontrol.features import FeatureExtractor

STEP = 33.0


def ids_by_x(out):
    return [h.hand_id for h in sorted(out.hands, key=lambda h: h.palm_center_px[0])]


def two_hands(x_right, x_left, y=240.0, right_label=Handedness.RIGHT, left_label=Handedness.LEFT, **kw):
    return [make_hand(0.0, center=(x_right, y), handedness=right_label, **kw),
            make_hand(0.0, side="left", center=(x_left, y), handedness=left_label, **kw)]


def test_stable_ids_over_moving_sequence():
    fx = FeatureExtractor()
    first = None
    for k in range(60):
        out = fx.update(make_frame(k * STEP, two_hands(420.0 + 3 * k, 120.0 - 1 * k, y=200.0 + 2 * k)))
        assert len(out.hands) == 2 and not out.identity_ambiguous
        first = first or ids_by_x(out)
        assert ids_by_x(out) == first
    assert len(set(first)) == 2


def test_detection_order_does_not_matter():
    fx = FeatureExtractor()
    a = fx.update(make_frame(0.0, two_hands(450.0, 150.0)))
    hands = two_hands(452.0, 148.0)
    b = fx.update(make_frame(STEP, hands[::-1]))
    assert ids_by_x(a) == ids_by_x(b)


def test_hand_lost_briefly_keeps_id_long_loss_gets_new_id():
    fx = FeatureExtractor()
    out = fx.update(make_frame(0.0, two_hands(450.0, 150.0)))
    right_id, left_id = ids_by_x(out)[1], ids_by_x(out)[0]
    t = STEP
    for _ in range(6):                      # right hand leaves for ~200 ms
        out = fx.update(make_frame(t, two_hands(450.0, 150.0)[1:]))
        assert [h.hand_id for h in out.hands] == [left_id]   # no extrapolated ghost
        t += STEP
    out = fx.update(make_frame(t, two_hands(455.0, 150.0)))
    assert ids_by_x(out) == [left_id, right_id]
    for _ in range(30):                     # ~1 s away: identity is no longer assumed
        t += STEP
        fx.update(make_frame(t, two_hands(450.0, 150.0)[1:]))
    out = fx.update(make_frame(t + STEP, two_hands(455.0, 150.0)))
    new_ids = ids_by_x(out)
    assert new_ids[0] == left_id and new_ids[1] not in (left_id, right_id)


def test_recovered_hand_restarts_finger_states():
    fx = FeatureExtractor()
    for k in range(4):
        fx.update(make_frame(k * STEP, [make_hand(0.0)]))
    fx.update(make_frame(4 * STEP, []))
    out = fx.update(make_frame(4 * STEP + 300.0, [make_hand(0.0)]))
    assert all(f.state.value == "unknown" for f in out.hands[0].fingers)


def crossing(right_label, left_label, frames=40):
    """Right hand moves left, left hand moves right, same height; they cross mid-sequence."""
    fx = FeatureExtractor()
    seq = []
    for k in range(frames):
        xr = 500.0 - 10.0 * k
        xl = 110.0 + 10.0 * k
        out = fx.update(make_frame(k * STEP, two_hands(xr, xl, right_label=right_label, left_label=left_label)))
        truth = {}
        for h in out.hands:
            truth[h.hand_id] = "R" if abs(h.palm_center_px[0] - xr) < 1e-6 else "L"
        seq.append((out, truth))
    return seq


def assert_no_silent_swap(seq):
    """Every change of the id->physical-hand mapping must happen on an ambiguous frame."""
    prev = None
    swaps = 0
    for out, truth in seq:
        if prev is not None:
            for hid, who in truth.items():
                if hid in prev and prev[hid] != who:
                    swaps += 1
                    assert out.identity_ambiguous, "silent identity swap"
        prev = truth
    return swaps


def test_crossing_hands_flags_ambiguity_and_keeps_ids_with_handedness():
    seq = crossing(Handedness.RIGHT, Handedness.LEFT)
    assert any(out.identity_ambiguous for out, _ in seq)
    assert assert_no_silent_swap(seq) == 0          # handedness resolves the crossing
    flagged = [out for out, _ in seq if out.identity_ambiguous]
    assert all(h.quality is not Quality.USABLE for out in flagged for h in out.hands)
    assert not seq[0][0].identity_ambiguous and not seq[-1][0].identity_ambiguous


def test_crossing_without_handedness_never_swaps_silently():
    seq = crossing(Handedness.UNKNOWN, Handedness.UNKNOWN)
    assert any(out.identity_ambiguous for out, _ in seq)
    assert_no_silent_swap(seq)


def test_same_handedness_pair_is_ambiguous():
    fx = FeatureExtractor()
    out = fx.update(make_frame(0.0, two_hands(450.0, 150.0, left_label=Handedness.RIGHT)))
    assert out.identity_ambiguous
    assert all(h.quality is Quality.DEGRADED for h in out.hands)


def test_overlapping_hands_are_ambiguous():
    fx = FeatureExtractor()
    out = fx.update(make_frame(0.0, two_hands(330.0, 300.0)))
    assert out.identity_ambiguous


def test_ambiguity_hold_then_clears():
    fx = FeatureExtractor()
    fx.update(make_frame(0.0, two_hands(450.0, 150.0, left_label=Handedness.RIGHT)))
    assert fx.update(make_frame(50.0, two_hands(450.0, 150.0))).identity_ambiguous      # held
    assert not fx.update(make_frame(150.0, two_hands(450.0, 150.0))).identity_ambiguous


def test_one_detection_between_two_remembered_tracks_is_ambiguous():
    fx = FeatureExtractor()
    fx.update(make_frame(0.0, two_hands(380.0, 260.0, right_label=Handedness.UNKNOWN,
                                        left_label=Handedness.UNKNOWN)))
    out = fx.update(make_frame(STEP, [make_hand(0.0, center=(320.0, 240.0), handedness=Handedness.UNKNOWN)]))
    assert out.identity_ambiguous


def test_extra_hands_flag_ambiguity():
    hands = two_hands(500.0, 100.0) + [make_hand(0.0, center=(300.0, 240.0))]
    out = FeatureExtractor().update(make_frame(0.0, hands))
    assert out.identity_ambiguous and len(out.hands) == 2


def test_ids_never_reused_after_reset():
    fx = FeatureExtractor()
    a = fx.update(make_frame(0.0, [make_hand()])).hands[0].hand_id
    fx.reset()
    b = fx.update(make_frame(STEP, [make_hand()])).hands[0].hand_id
    assert b != a


def test_far_teleport_creates_new_identity():
    fx = FeatureExtractor()
    a = fx.update(make_frame(0.0, [make_hand(center=(100.0, 240.0))])).hands[0].hand_id
    b = fx.update(make_frame(STEP, [make_hand(center=(560.0, 240.0))])).hands[0].hand_id
    assert a != b
