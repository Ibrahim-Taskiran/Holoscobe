"""Per-finger extended/bent on synthetic hands (logic only; real-camera accuracy pending)."""
from __future__ import annotations

import pytest

from feat_synth import FINGER_NAMES, make_frame, make_hand
from handcontrol.contracts import FingerName, FingerState, Quality
from handcontrol.features import FINGER_ORDER, FeatureExtractor, finger

EXT, BENT, UNK = FingerState.EXTENDED, FingerState.BENT, FingerState.UNKNOWN


def settle(hand, frames: int = 4, step: float = 33.0):
    fx = FeatureExtractor()
    out = None
    for k in range(frames):
        out = fx.update(make_frame(k * step, [hand]))
    assert out is not None and len(out.hands) == 1
    return out.hands[0]


def states(hf):
    return [f.state for f in hf.fingers]


def test_finger_order_and_names():
    hf = settle(make_hand(0.0))
    assert [f.name for f in hf.fingers] == list(FINGER_ORDER)
    assert FINGER_ORDER == (FingerName.THUMB, FingerName.INDEX, FingerName.MIDDLE, FingerName.RING, FingerName.LITTLE)
    assert finger(hf, FingerName.RING).name is FingerName.RING


@pytest.mark.parametrize("side", ["right", "left"])
@pytest.mark.parametrize("roll", [0, 45, 90, 180])
@pytest.mark.parametrize("which", range(5))
def test_single_finger_bent_in_open_hand(side, roll, which):
    curls = [0.0] * 5
    curls[which] = 1.0
    hf = settle(make_hand(curls, side=side, roll=roll))
    assert hf.quality is Quality.USABLE
    expected = [BENT if i == which else EXT for i in range(5)]
    assert states(hf) == expected, FINGER_NAMES[which]


@pytest.mark.parametrize("side", ["right", "left"])
@pytest.mark.parametrize("roll", [0, 45, 90, 180])
@pytest.mark.parametrize("which", range(5))
def test_single_finger_extended_in_fist(side, roll, which):
    curls = [1.0] * 5
    curls[which] = 0.0
    hf = settle(make_hand(curls, side=side, roll=roll))
    expected = [EXT if i == which else BENT for i in range(5)]
    assert states(hf) == expected, FINGER_NAMES[which]


@pytest.mark.parametrize("scale", [35.0, 60.0, 150.0, 300.0])
@pytest.mark.parametrize("curl,expected", [(0.0, EXT), (1.0, BENT)])
def test_scale_invariant(scale, curl, expected):
    hf = settle(make_hand(curl, scale=scale))
    assert states(hf) == [expected] * 5
    assert hf.palm_scale_px == pytest.approx(scale, rel=0.02)


@pytest.mark.parametrize("pose", [{"yaw": 50}, {"yaw": 180}, {"pitch": 40}, {"yaw": -40, "roll": 120},
                                  {"world": True, "yaw": 60}, {"side": "left", "yaw": 30, "pitch": -25}])
def test_oblique_hands_with_depth(pose):
    open_hand = settle(make_hand([0.0, 1.0, 0.0, 1.0, 0.0], **pose))
    assert states(open_hand) == [EXT, BENT, EXT, BENT, EXT]


def test_curl_is_monotonic_and_bounded():
    prev = [-1.0] * 5
    for c in (0.0, 0.25, 0.5, 0.75, 1.0):
        hf = settle(make_hand(c, roll=30))
        curls = [f.curl for f in hf.fingers]
        assert all(0.0 <= v <= 1.0 for v in curls)
        assert all(v > p for v, p in zip(curls, prev))
        prev = curls
    assert all(v > 0.9 for v in prev)


def test_half_bent_fingers_are_not_confident():
    # A half-curled finger sits in the hysteresis band: a fresh track must not guess.
    hf = settle(make_hand([0.0, 0.45, 0.45, 0.45, 0.45]))
    assert states(hf)[1:] == [UNK] * 4


def test_missing_depth_with_foreshortened_curl_is_unknown():
    # Palm facing camera, fingers curling toward the lens, z unavailable: 2D cues disagree.
    hf = settle(make_hand([0.0, 0.5, 0.5, 0.5, 0.5], depth=False))
    assert states(hf)[1:] == [UNK] * 4


# ---------- thumb: own joint / opposition geometry ----------

@pytest.mark.parametrize("roll", [0, 45, 90, 180])
@pytest.mark.parametrize("side", ["right", "left"])
def test_thumbs_up_and_tucked_thumb(roll, side):
    up = settle(make_hand([0.0, 1.0, 1.0, 1.0, 1.0], roll=roll, side=side))
    assert up.fingers[0].state is EXT
    tucked = settle(make_hand([1.0, 0.0, 0.0, 0.0, 0.0], roll=roll, side=side))
    assert tucked.fingers[0].state is BENT
    assert tucked.fingers[0].curl > 0.8 and up.fingers[0].curl < 0.1


def test_straight_thumb_lying_across_palm_is_not_extended():
    """Generic finger rules would call a straight thumb extended; opposition geometry must not."""
    hand = make_hand(0.0)
    lms = list(hand.landmarks)
    pc_x = sum(lms[i].x for i in (5, 9, 13, 17)) / 4
    pc_y = sum(lms[i].y for i in (5, 9, 13, 17)) / 4
    # translate the straight thumb chain so its tip sits on the palm center
    dx, dy = pc_x - lms[4].x, pc_y - lms[4].y
    for i in (1, 2, 3, 4):
        lms[i] = type(lms[i])(lms[i].x + dx, lms[i].y + dy, lms[i].z)
    moved = type(hand)(hand.handedness, hand.handedness_score, tuple(lms))
    hf = settle(moved)
    assert hf.fingers[0].state is not EXT


def test_pinch_distance_in_palm_units_uses_pixels():
    hand = make_hand(0.0, width=1280, height=480, center=(640.0, 240.0), scale=120.0)
    fx = FeatureExtractor()
    hf = fx.update(make_frame(0.0, [hand], width=1280, height=480)).hands[0]
    lm = hand.landmarks
    d = ((lm[4].x - lm[8].x) * 1280) ** 2 + ((lm[4].y - lm[8].y) * 480) ** 2
    assert hf.pinch_distance == pytest.approx(d ** 0.5 / hf.palm_scale_px)
    assert hf.palm_center_px == pytest.approx((640.0, 240.0))
    assert hf.index_tip_px == pytest.approx((lm[8].x * 1280, lm[8].y * 480))
