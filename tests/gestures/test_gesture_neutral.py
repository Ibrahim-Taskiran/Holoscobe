from __future__ import annotations

import pytest

from handcontrol.contracts import GestureKind as K, Quality
from handcontrol.gestures import GestureConfig, GestureRecognizer

FRAME = 1000.0 / 30 + 4.0


def _n(events):
    return [e for e in events if e.kind is K.NEUTRAL]


def _open(tl, **kw):
    return (tl.hand(2, (900, 360), **kw),)


def test_neutral_after_200ms_once(tl, rec):
    t0 = tl.t
    tl.add(1000, _open(tl))
    n = _n(tl.run(rec))
    assert len(n) == 1 and 200 <= n[0].t_ms - t0 < 200 + FRAME
    assert rec.is_neutral


def test_pinch_breaks_neutral_and_release_needs_fresh_200ms(tl, rec):
    tl.add(400, _open(tl)).add(300, _open(tl, pinch=0.15)).add(600, _open(tl))
    ev = tl.run(rec)
    kinds = [e.kind for e in ev]
    assert kinds == [K.NEUTRAL, K.PINCH_START, K.PINCH_END, K.NEUTRAL]
    assert ev[3].t_ms - ev[2].t_ms >= 200
    assert rec.is_neutral


def test_pending_pinch_breaks_neutral(tl, rec):
    tl.add(400, _open(tl)).add(1, _open(tl, pinch=0.15))
    tl.run(rec)
    assert not rec.is_neutral


@pytest.mark.parametrize("hands", ["none", "degraded", "unknown"])
def test_no_neutral_without_usable_tracking(tl, rec, hands):
    spec = {"none": (), "degraded": _open(tl, quality=Quality.DEGRADED),
            "unknown": _open(tl, quality=Quality.UNKNOWN)}[hands]
    tl.add(1000, spec)
    assert _n(tl.run(rec)) == [] and not rec.is_neutral


def test_degraded_second_hand_blocks_neutral(tl, rec):
    tl.add(1000, (tl.hand(2, (900, 360)), tl.hand(1, (300, 360), quality=Quality.DEGRADED)))
    assert _n(tl.run(rec)) == []


def test_hand_entering_pinched_is_not_neutral_until_open(tl, rec):
    tl.add(600, _open(tl, pinch=0.15))
    assert _n(tl.run(rec)) == []
    tl.add(400, _open(tl))
    assert len(_n(tl.run(rec))) == 1


def test_clap_candidate_blocks_neutral_and_clap_requires_fresh_neutral(tl, rec):
    tl.add(400, tl.pair(2.6))
    tl.clap(end_hold_ms=600)
    neutral_during_candidate = False
    events = []
    for _, ev in tl.feed(rec):
        events += ev
        neutral_during_candidate |= rec.clap_candidate_active and rec.is_neutral
    assert not neutral_during_candidate
    kinds = [e.kind for e in events]
    i = kinds.index(K.CLAP)
    assert K.NEUTRAL in kinds[i + 1:]
    clap_t = events[i].t_ms
    after = [e for e in events[i + 1:] if e.kind is K.NEUTRAL][0]
    assert after.t_ms - clap_t >= 200 - FRAME                 # timer may start on the CLAP frame


def test_identity_ambiguous_clears_neutral(tl, rec):
    tl.add(400, _open(tl))
    tl.run(rec)
    assert rec.is_neutral
    tl.add(100, _open(tl), ambiguous=True)
    assert tl.run(rec) == [] and not rec.is_neutral
    t0 = tl.t
    tl.add(400, _open(tl))
    n = _n(tl.run(rec))
    assert len(n) == 1 and n[0].t_ms - t0 >= 200


def test_reset_clears_baselines(tl, rec):
    tl.add(300, _open(tl)).add(200, _open(tl, pinch=0.15))
    tl.run(rec)
    assert rec.is_pinched(2)
    rec.reset()
    assert not rec.is_pinched(2) and not rec.is_neutral and not rec.clap_candidate_active
    assert rec.menu_dwell_progress == 0.0
    tl.add(400, _open(tl, pinch=0.15))                        # still pinched: no new start
    assert tl.run(rec) == []
    t0 = tl.t
    tl.add(400, _open(tl))
    n = _n(tl.run(rec))
    assert len(n) == 1 and n[0].t_ms - t0 >= 200


def test_reset_during_candidate_is_silent(tl, rec):
    tl.add(400, tl.pair(2.6)).add(120, lambda u: tl.pair(2.6 - 1.0 * u))
    tl.run(rec)
    assert rec.clap_candidate_active
    rec.reset()
    assert not rec.clap_candidate_active
    tl.add(300, lambda u: tl.pair(1.6 - 1.3 * u)).add(300, lambda u: tl.pair(0.3 + 2.2 * u))
    assert K.CLAP not in [e.kind for e in tl.run(rec)]


def test_clap_cooldown_survives_reset(tl, rec):
    tl.add(400, tl.pair(2.6))
    tl.clap(end_hold_ms=100)
    assert [e.kind for e in tl.run(rec)].count(K.CLAP) == 1
    rec.reset()                                               # controller resets after a clap
    tl.clap(hold_ms=200)
    assert K.CLAP not in [e.kind for e in tl.run(rec)]


def test_reset_requires_menu_release(tl, rec):
    v = tl.hand(1, (300, 360), extended=2, thumb=False)
    tl.add(300, (v,))
    tl.run(rec)
    rec.reset()
    tl.add(1200, (v,))
    assert K.MENU_DWELL_COMPLETE not in [e.kind for e in tl.run(rec)]


def test_replay_is_deterministic_and_duplicates_are_ignored(tl):
    tl.add(400, tl.pair(2.6))
    tl.clap()
    tl.add(300, tl.pair(2.4, left={"pinch": 0.1}))
    a, b, c = GestureRecognizer(), GestureRecognizer(), GestureRecognizer()
    ev_a = [e for f in tl.frames for e in a.update(f)]
    ev_c = [e for f in tl.frames for e in c.update(f)]
    ev_b = []
    for f in tl.frames:
        ev_b += b.update(f)
        ev_b += b.update(f)
    assert ev_a == ev_b == ev_c
    assert [e.kind for e in ev_a].count(K.CLAP) == 1


def test_clock_rewind_beyond_limit_resets_safely(tl, rec):
    tl.add(300, _open(tl)).add(200, _open(tl, pinch=0.15))
    tl.run(rec)
    assert rec.is_pinched(2)
    tl.frame(_open(tl, pinch=0.15), t=tl.t - 5000)
    assert [e.kind for e in tl.run(rec)] == [K.PINCH_END]
    assert not rec.is_pinched(2)


def test_nan_timestamp_ignored(tl, rec):
    tl.add(300, _open(tl))
    tl.run(rec)
    tl.frame(_open(tl), t=float("nan"))
    assert tl.run(rec) == []


def test_config_validation():
    with pytest.raises(ValueError):
        GestureConfig(pinch_on_pu=0.5, pinch_off_pu=0.4)
    with pytest.raises(ValueError):
        GestureConfig(clap_near_distance_pu=1.8, clap_separate_distance_pu=1.6)
    with pytest.raises(ValueError):
        GestureConfig(clap_cooldown_ms=-1)
