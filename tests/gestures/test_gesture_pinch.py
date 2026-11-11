from __future__ import annotations

from handcontrol.contracts import GestureKind as K, Quality
from handcontrol.gestures import GestureRecognizer

FRAME = 1000.0 / 30 + 4.0   # worst-case frame interval incl. jitter


def _k(events):
    """Kinds without NEUTRAL (covered by its own tests)."""
    return [e.kind for e in events if e.kind is not K.NEUTRAL]


def _h(tl, pinch, **kw):
    return (tl.hand(2, pinch=pinch, **kw),)


def test_pinch_start_and_end_after_debounce(tl, rec):
    tl.add(200, _h(tl, 0.8))
    tl.run(rec)
    t0 = tl.t
    tl.add(300, _h(tl, 0.2))
    ev = [e for e in tl.run(rec) if e.kind is not K.NEUTRAL]
    assert _k(ev) == [K.PINCH_START]
    assert ev[0].hand_id == 2
    assert 70 <= ev[0].t_ms - t0 < 70 + FRAME
    assert rec.is_pinched(2)
    t1 = tl.t
    tl.add(300, _h(tl, 0.7))
    ev = [e for e in tl.run(rec) if e.kind is not K.NEUTRAL]
    assert tl.of(ev, K.PINCH_END)[0].hand_id == 2
    assert 70 <= tl.of(ev, K.PINCH_END)[0].t_ms - t1 < 70 + FRAME
    assert not rec.is_pinched(2)


def test_hysteresis_band_holds_state(tl, rec):
    tl.add(200, _h(tl, 0.8)).add(500, _h(tl, 0.33))          # between on and off: no start
    assert K.PINCH_START not in _k(tl.run(rec))
    tl.add(200, _h(tl, 0.25))
    assert _k(tl.run(rec)).count(K.PINCH_START) == 1
    tl.add(500, _h(tl, 0.38))                                 # between on and off: stays pinched
    assert K.PINCH_END not in _k(tl.run(rec))
    assert rec.is_pinched(2)
    tl.add(200, _h(tl, 0.45))
    assert _k(tl.run(rec)).count(K.PINCH_END) == 1


def test_short_blip_shorter_than_debounce_is_ignored(tl, rec):
    tl.add(200, _h(tl, 0.8)).add(40, _h(tl, 0.1)).add(300, _h(tl, 0.8))
    assert K.PINCH_START not in _k(tl.run(rec))


def test_flicker_near_thresholds(tl, rec):
    tl.add(200, _h(tl, 0.8))
    tl.add(1000, lambda u: _h(tl, 0.27 if len(tl.frames) % 2 else 0.30))
    assert K.PINCH_START not in _k(tl.run(rec))
    tl.add(200, _h(tl, 0.2))
    assert _k(tl.run(rec)) == [K.PINCH_START]
    tl.add(1000, lambda u: _h(tl, 0.43 if len(tl.frames) % 2 else 0.40))
    assert K.PINCH_END not in _k(tl.run(rec))
    assert rec.is_pinched(2)


def test_hand_loss_ends_pinch_and_requires_reengagement(tl, rec):
    tl.add(200, _h(tl, 0.8)).add(200, _h(tl, 0.2))
    assert _k(tl.run(rec)) == [K.PINCH_START]
    tl.add(1, ())                                             # one frame without the hand
    ev = [e for e in tl.run(rec) if e.kind is not K.NEUTRAL]
    assert _k(ev) == [K.PINCH_END] and ev[0].hand_id == 2
    tl.add(500, _h(tl, 0.2))                                  # back, still pinched: no restart
    assert K.PINCH_START not in _k(tl.run(rec))
    tl.add(100, _h(tl, 0.8)).add(200, _h(tl, 0.2))            # release, then pinch again
    assert _k(tl.run(rec)).count(K.PINCH_START) == 1


def test_identity_ambiguous_ends_pinch(tl, rec):
    tl.add(200, _h(tl, 0.8)).add(200, _h(tl, 0.2))
    tl.run(rec)
    tl.add(1, _h(tl, 0.2), ambiguous=True)
    assert _k(tl.run(rec)) == [K.PINCH_END]
    tl.add(300, _h(tl, 0.2), ambiguous=True)
    assert _k(tl.run(rec)) == []
    tl.add(300, _h(tl, 0.2))
    assert _k(tl.run(rec)) == []                                  # needs release first
    assert not rec.is_pinched(2)


def test_new_hand_appearing_pinched_needs_release(tl, rec):
    tl.add(400, _h(tl, 0.15))
    assert _k(tl.run(rec)) == []
    tl.add(100, _h(tl, 0.6)).add(200, _h(tl, 0.15))
    assert _k(tl.run(rec)) == [K.PINCH_START]


def test_degraded_hand_cannot_start_and_grace_then_end(tl, rec):
    tl.add(200, _h(tl, 0.8)).add(400, _h(tl, 0.15, quality=Quality.DEGRADED))
    tl.add(300, _h(tl, 0.15, quality=Quality.UNKNOWN))
    assert _k(tl.run(rec)) == []
    tl.add(200, _h(tl, 0.15))
    assert _k(tl.run(rec)) == [K.PINCH_START]
    tl.add(120, _h(tl, 0.15, quality=Quality.DEGRADED)).add(100, _h(tl, 0.15))
    assert _k(tl.run(rec)) == [] and rec.is_pinched(2)          # short degrade: pinch held
    t0 = tl.t
    tl.add(400, _h(tl, 0.15, quality=Quality.DEGRADED))
    ev = [e for e in tl.run(rec) if e.kind is not K.NEUTRAL]
    assert _k(ev) == [K.PINCH_END]
    assert 200 <= ev[0].t_ms - t0 < 200 + 40


def test_two_hands_pinch_independently(tl, rec):
    both = lambda pl, pr: (tl.hand(1, (300, 300), pinch=pl), tl.hand(2, (900, 300), pinch=pr))
    tl.add(200, both(0.8, 0.8)).add(200, both(0.2, 0.8))
    ev = [e for e in tl.run(rec) if e.kind is not K.NEUTRAL]
    assert [(e.kind, e.hand_id) for e in ev if e.kind is not K.NEUTRAL] == [(K.PINCH_START, 1)]
    tl.add(200, both(0.2, 0.2))
    assert [(e.kind, e.hand_id) for e in tl.run(rec) if e.kind is not K.NEUTRAL] == [(K.PINCH_START, 2)]
    assert rec.is_pinched(1) and rec.is_pinched(2)


def test_non_increasing_timestamps_do_not_double_fire(tl):
    tl.add(200, _h(tl, 0.8)).add(300, _h(tl, 0.2)).add(300, _h(tl, 0.8))
    clean = GestureRecognizer()
    expected = [e for f in tl.frames for e in clean.update(f)]
    noisy = GestureRecognizer()
    got = []
    for i, f in enumerate(tl.frames):
        got += noisy.update(f)
        got += noisy.update(f)                                # duplicate
        if i:
            got += noisy.update(tl.frames[i - 1])             # small step back
    assert got == expected
    assert [e.kind for e in got].count(K.PINCH_START) == 1


def test_large_frame_gap_ends_pinch(tl, rec):
    tl.add(200, _h(tl, 0.8)).add(200, _h(tl, 0.2))
    tl.run(rec)
    tl.t += 400
    tl.add(200, _h(tl, 0.2))
    assert _k(tl.run(rec)) == [K.PINCH_END]
