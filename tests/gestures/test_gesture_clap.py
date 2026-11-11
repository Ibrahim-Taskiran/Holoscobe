from __future__ import annotations

from dataclasses import replace

import pytest

from handcontrol.contracts import GestureKind as K, Quality
from handcontrol.gestures import GestureRecognizer


def lerp(a: float, b: float, u: float) -> float:
    return a + (b - a) * u

CLAPPY = (K.CLAP, K.CLAP_CANDIDATE_START, K.CLAP_CANDIDATE_ABORT)


def _c(events):
    return [e.kind for e in events if e.kind in CLAPPY]


def _intro(tl):
    """Hands appear open and far apart (release observed, arm hold satisfied)."""
    tl.add(300, tl.pair(2.6))


@pytest.mark.parametrize("seed", range(6))
@pytest.mark.parametrize("fps", [24.0, 30.0, 60.0])
def test_clean_clap_fires_exactly_once(make_tl, seed, fps):
    tl = make_tl(seed=seed, fps=fps)
    rec = GestureRecognizer()
    _intro(tl)
    tl.clap()
    seen_active = False
    events = []
    for f in tl.frames:
        events += rec.update(f)
        seen_active |= rec.clap_candidate_active
    assert _c(events) == [K.CLAP_CANDIDATE_START, K.CLAP]
    assert seen_active and not rec.clap_candidate_active


def test_slow_approach_never_starts(tl, rec):
    _intro(tl)
    tl.add(1500, lambda u: tl.pair(2.6 - 1.2 * u))           # 0.8 pu/s, below entry speed
    tl.add(300, lambda u: tl.pair(1.4 - 1.1 * u))
    tl.add(400, lambda u: tl.pair(0.3 + 2.2 * u))
    assert K.CLAP_CANDIDATE_START not in _c(tl.run(rec))


def test_moderate_approach_too_slow_for_near_zone_aborts(tl, rec):
    _intro(tl)
    tl.add(1500, lambda u: tl.pair(2.6 - 2.25 * u))          # 1.5 pu/s: candidate, but 2.0->0.85 takes ~770 ms
    tl.add(400, lambda u: tl.pair(0.35 + 2.2 * u))
    ev = _c(tl.run(rec))
    assert K.CLAP not in ev
    assert ev[:2] == [K.CLAP_CANDIDATE_START, K.CLAP_CANDIDATE_ABORT]


def test_approach_without_separation(tl, rec):
    _intro(tl)
    tl.clap(contact_ms=1200, separate_ms=60, end_d=0.4, end_hold_ms=300)
    ev = _c(tl.run(rec))
    assert ev == [K.CLAP_CANDIDATE_START, K.CLAP_CANDIDATE_ABORT]
    assert not rec.clap_candidate_active


def test_separation_must_exceed_threshold(tl, rec):
    _intro(tl)
    tl.clap(end_d=1.5, end_hold_ms=800)                       # never above 1.6
    assert K.CLAP not in _c(tl.run(rec))


def test_dropout_alone_never_claps(tl, rec):
    _intro(tl)
    tl.add(100, ())                                           # vanish while armed
    tl.add(400, tl.pair(2.6))
    tl.add(90, lambda u: tl.pair(2.6 - 1.0 * u))              # approach starts...
    tl.add(100, ())                                           # ...dropout before near zone
    tl.add(400, tl.pair(2.4))
    assert K.CLAP not in _c(tl.run(rec))


def test_dropout_up_to_120ms_after_near_zone_still_claps(tl, rec):
    _intro(tl)
    tl.add(250, lambda u: tl.pair(2.6 - 2.3 * u))
    tl.add(30, tl.pair(0.3))
    tl.add(80, ())                                            # overlap dropout in near zone
    tl.add(300, lambda u: tl.pair(0.5 + 2.0 * u))
    assert _c(tl.run(rec)) == [K.CLAP_CANDIDATE_START, K.CLAP]


def test_dropout_one_hand_only_after_near_zone_still_claps(tl, rec):
    _intro(tl)
    tl.add(250, lambda u: tl.pair(2.6 - 2.3 * u))
    tl.add(30, tl.pair(0.3))
    tl.add(80, (tl.pair(0.3)[0],))
    tl.add(300, lambda u: tl.pair(0.5 + 2.0 * u))
    assert _c(tl.run(rec)) == [K.CLAP_CANDIDATE_START, K.CLAP]


def test_dropout_longer_than_120ms_aborts(tl, rec):
    _intro(tl)
    tl.add(250, lambda u: tl.pair(2.6 - 2.3 * u))
    tl.add(30, tl.pair(0.3))
    tl.add(200, ())
    tl.add(300, lambda u: tl.pair(0.5 + 2.0 * u))
    assert _c(tl.run(rec)) == [K.CLAP_CANDIDATE_START, K.CLAP_CANDIDATE_ABORT]


def test_reappearing_already_separated_needs_two_samples(tl, rec):
    _intro(tl)
    tl.add(250, lambda u: tl.pair(2.6 - 2.3 * u))
    tl.add(30, tl.pair(0.3))
    tl.add(80, ())
    tl.frame(tl.pair(2.0))                                    # single sample after dropout
    tl.add(300, ())
    assert K.CLAP not in _c(tl.run(rec))


def test_double_clap_needs_cooldown_and_fresh_separation(tl, rec):
    _intro(tl)
    tl.clap(end_hold_ms=100)
    tl.clap(hold_ms=200)                                      # second clap well inside 900 ms
    ev = _c(tl.run(rec))
    assert ev.count(K.CLAP) == 1
    tl.add(1000, tl.pair(2.6))
    tl.clap()
    assert _c(tl.run(rec)).count(K.CLAP) == 1


def test_rearm_requires_fresh_separated_pose(tl, rec):
    _intro(tl)
    tl.clap(end_d=1.8, end_hold_ms=1500)                      # stays between 1.6 and 2.0
    tl.clap(start_d=1.8, hold_ms=200)
    assert _c(tl.run(rec)).count(K.CLAP) == 1


def test_clap_events_carry_frame_time(tl, rec):
    _intro(tl)
    tl.clap()
    ev = [e for e in tl.run(rec) if e.kind in CLAPPY]
    times = {f.capture_ms for f in tl.frames}
    assert all(e.t_ms in times and e.hand_id is None for e in ev)
    assert ev[0].t_ms < ev[1].t_ms


def test_two_sustained_pinches_never_clap(tl, rec):
    tl.add(300, tl.pair(2.6))
    tl.add(300, tl.pair(2.6, pinch=0.15))
    tl.clap(pinch=0.15)
    assert _c(tl.run(rec)) == []


def test_one_pinched_hand_blocks_clap(tl, rec):
    tl.add(300, tl.pair(2.6))
    tl.add(300, tl.pair(2.6, left={"pinch": 0.15}))
    tl.clap(left={"pinch": 0.15})
    assert _c(tl.run(rec)) == []


def test_pinch_during_candidate_aborts_before_pinch_start(tl, rec):
    _intro(tl)
    tl.add(150, lambda u: tl.pair(2.6 - 1.2 * u))
    tl.add(200, lambda u: tl.pair(1.4 - 0.3 * u, pinch=0.1))  # pinch fires mid-approach
    tl.add(300, tl.pair(2.4))
    kinds = [e.kind for e in tl.run(rec) if e.kind is not K.NEUTRAL]
    assert K.CLAP not in kinds
    i = kinds.index(K.CLAP_CANDIDATE_ABORT)
    assert kinds[i + 1] is K.PINCH_START


@pytest.mark.parametrize("ext", [0, 1, 2])
def test_fewer_than_three_extended_fingers(tl, rec, ext):
    tl.add(300, tl.pair(2.6, extended=ext))
    tl.clap(extended=ext)
    assert _c(tl.run(rec)) == []


def test_three_extended_fingers_is_enough(tl, rec):
    tl.add(300, tl.pair(2.6, extended=3))
    tl.clap(extended=3)
    assert _c(tl.run(rec)).count(K.CLAP) == 1


def test_hands_crossing_at_different_heights(tl, rec):
    """Near miss: hands sweep past each other 1.1 palm units apart vertically."""
    tl.add(300, tl.pair(3.0, dy_pu=1.1))
    tl.add(400, lambda u: tl.pair(3.0 - 6.0 * u, dy_pu=1.1))
    tl.add(400, tl.pair(-3.0, dy_pu=1.1))
    ev = _c(tl.run(rec))
    assert K.CLAP not in ev
    assert ev.count(K.CLAP_CANDIDATE_START) == ev.count(K.CLAP_CANDIDATE_ABORT)
    assert not rec.clap_candidate_active


def test_unarmed_start_cannot_clap(tl, rec):
    tl.clap(start_d=1.9, hold_ms=500)                         # never separated beyond 2.0
    assert _c(tl.run(rec)) == []


def test_ambiguous_flag_with_both_centers_does_not_abort_candidate(tl, rec):
    _intro(tl)
    tl.add(150, lambda u: tl.pair(2.6 - 1.5 * u))
    tl.add(1, tl.pair(1.0), ambiguous=True)
    tl.add(300, lambda u: tl.pair(0.4 + 2.0 * u))
    assert _c(tl.run(rec)) == [K.CLAP_CANDIDATE_START, K.CLAP]


# ---- real features.py contact behavior: identity_ambiguous while palms overlap (< 0.7 pu) + 100 ms tail

def _contact(tl):
    """Ambiguous contact frames: UNKNOWN fingers, DEGRADED/UNKNOWN quality, sometimes one hand only."""
    cx, cy = 640.0, 360.0

    def frame_hands(u):
        k = len(tl.frames) % 4
        a = tl.overlap_hand(1, (cx - 15, cy))
        b = tl.overlap_hand(2, (cx + 15, cy))
        if k == 0:
            return (a, b)
        if k == 1:
            return (tl.overlap_hand(2, (cx, cy), Quality.UNKNOWN),)
        if k == 2:
            return (a,)
        return (a, tl.overlap_hand(2, (cx + 15, cy), Quality.UNKNOWN))
    return frame_hands


def _swapped(hands):
    """Same pair with exchanged hand ids (allowed across ambiguous frames)."""
    a, b = hands
    return (replace(a, hand_id=b.hand_id), replace(b, hand_id=a.hand_id))


@pytest.mark.parametrize("last_clean_d", [0.9, 0.78])
@pytest.mark.parametrize("ambiguous_ms", [150, 200, 250])
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_real_contact_ambiguity_still_claps_once(make_tl, last_clean_d, ambiguous_ms, seed):
    tl = make_tl(seed=seed)
    rec = GestureRecognizer()
    _intro(tl)
    tl.add(200, lambda u: tl.pair(lerp(2.6, last_clean_d, u)))        # clean, verified approach
    tl.frame(tl.pair(last_clean_d))
    tl.add(ambiguous_ms, _contact(tl), ambiguous=True)
    tl.add(250, lambda u: _swapped(tl.pair(lerp(1.4, 2.5, u))))        # clean separation, ids exchanged
    tl.add(300, _swapped(tl.pair(2.5)))
    assert _c(tl.run(rec)) == [K.CLAP_CANDIDATE_START, K.CLAP]
    assert not rec.clap_candidate_active


def test_ambiguity_without_verified_approach_never_claps(tl, rec):
    _intro(tl)
    tl.add(200, _contact(tl), ambiguous=True)                          # no approach, no candidate
    tl.add(250, lambda u: tl.pair(lerp(1.4, 2.5, u)))
    tl.add(300, tl.pair(2.5))
    assert _c(tl.run(rec)) == []


def test_ambiguity_after_slow_approach_never_claps(tl, rec):
    _intro(tl)
    tl.add(1600, lambda u: tl.pair(lerp(2.6, 0.9, u)))                # ~1 pu/s and far too slow
    tl.add(200, _contact(tl), ambiguous=True)
    tl.add(250, lambda u: tl.pair(lerp(1.4, 2.5, u)))
    assert K.CLAP not in _c(tl.run(rec))


def test_ambiguous_contact_held_too_long_aborts(tl, rec):
    _intro(tl)
    tl.add(200, lambda u: tl.pair(lerp(2.6, 0.8, u)))
    tl.add(800, _contact(tl), ambiguous=True)
    tl.add(250, lambda u: tl.pair(lerp(1.4, 2.5, u)))
    assert _c(tl.run(rec)) == [K.CLAP_CANDIDATE_START, K.CLAP_CANDIDATE_ABORT]


def test_ambiguous_frames_without_any_hand_count_as_dropout(tl, rec):
    _intro(tl)
    tl.add(200, lambda u: tl.pair(lerp(2.6, 0.8, u)))
    tl.add(60, _contact(tl), ambiguous=True)
    tl.add(200, (), ambiguous=True)                                    # nothing reported > 120 ms
    tl.add(250, lambda u: tl.pair(lerp(1.4, 2.5, u)))
    assert _c(tl.run(rec)) == [K.CLAP_CANDIDATE_START, K.CLAP_CANDIDATE_ABORT]


def test_hands_need_release_after_contact_ambiguity(tl, rec):
    """Ids may swap during contact: per-hand pinch state restarts, so a closed pinch cannot carry over."""
    _intro(tl)
    tl.add(200, lambda u: tl.pair(lerp(2.6, 0.8, u)))
    tl.add(200, _contact(tl), ambiguous=True)
    closed = {"pinch": 0.1}                                            # comes out of contact pinched
    tl.add(250, lambda u: tl.pair(lerp(1.4, 2.5, u), left=closed))
    tl.add(400, tl.pair(2.5, left=closed))
    kinds = [e.kind for e in tl.run(rec)]
    assert kinds.count(K.CLAP) == 1 and K.PINCH_START not in kinds
