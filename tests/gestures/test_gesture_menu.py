from __future__ import annotations

import math

from handcontrol.contracts import GestureKind as K, Handedness, Quality
from handcontrol.gestures import GestureRecognizer

FRAME = 1000.0 / 30 + 4.0
LEFT_AT = (400.0, 360.0)


def _menus(events):
    return [e for e in events if e.kind is K.MENU_DWELL_COMPLETE]


def _left(tl, center=LEFT_AT, **kw):
    return tl.hand(1, center, **kw)


def _pointer(tl, x=1000.0):
    """Dominant right hand pointing: one finger, no clap geometry."""
    return tl.hand(2, (x, 360.0), extended=1, thumb=False)


def test_dwell_completes_at_600ms(tl, rec):
    t0 = tl.t
    progress = []

    def still(u):
        wobble = 2.0 * math.sin(40 * u)                      # 0.02 palm units of jitter
        return (_left(tl, (LEFT_AT[0] + wobble, LEFT_AT[1])), _pointer(tl))

    tl.add(1500, still)
    events = []
    for _, ev in tl.feed(rec):
        if not _menus(events):
            progress.append(rec.menu_dwell_progress)
        events += ev
    m = _menus(events)
    assert len(m) == 1 and m[0].hand_id == 1
    assert 600 <= m[0].t_ms - t0 < 600 + FRAME
    before = progress[:-1]
    assert before == sorted(before) and 0.85 < max(before) < 1.0
    assert rec.menu_dwell_progress == 0.0                      # latched until release


def test_four_fingers_without_thumb_is_open(tl, rec):
    tl.add(800, (_left(tl, thumb=False),))
    assert len(_menus(tl.run(rec))) == 1


def test_three_fingers_plus_thumb_is_open_but_three_alone_is_not(tl, rec, make_tl):
    tl.add(800, (_left(tl, extended=3, thumb=True),))
    assert len(_menus(tl.run(rec))) == 1
    tl2, rec2 = make_tl(), GestureRecognizer()
    tl2.add(1200, (_left(tl2, extended=3, thumb=False),))
    assert _menus(tl2.run(rec2)) == []


def test_moving_palm_cancels(tl, rec):
    tl.add(2000, lambda u: (_left(tl, (LEFT_AT[0] + 100.0 * u, LEFT_AT[1])),))  # 0.5 pu/s drift
    assert _menus(tl.run(rec)) == []


def test_approaching_hands_cancel_dwell(tl, rec):
    tl.add(400, (_left(tl), _pointer(tl, 1000.0)))
    t_stop = None
    tl.add(300, lambda u: (_left(tl), _pointer(tl, 1000.0 - 450.0 * u)))   # 1.5 pu/s toward left
    t_stop = tl.t
    tl.add(900, (_left(tl), _pointer(tl, 550.0)))
    m = _menus(tl.run(rec))
    assert len(m) == 1
    assert m[0].t_ms >= t_stop + 600 - FRAME * 3              # restarted after the approach


def test_no_refire_without_release(tl, rec):
    tl.add(2500, (_left(tl),))
    assert len(_menus(tl.run(rec))) == 1
    tl.add(100, (_left(tl, extended=1, thumb=False),))       # fist = release
    tl.add(800, (_left(tl),))
    assert len(_menus(tl.run(rec))) == 1


def test_hand_gone_counts_as_release(tl, rec):
    tl.add(800, (_left(tl),)).add(100, ()).add(800, (_left(tl),))
    assert len(_menus(tl.run(rec))) == 2


def test_degraded_open_palm_neither_dwells_nor_releases(tl, rec):
    tl.add(1000, (_left(tl, quality=Quality.DEGRADED),))
    assert _menus(tl.run(rec)) == []
    tl.add(800, (_left(tl),)).add(200, (_left(tl, quality=Quality.DEGRADED),)).add(800, (_left(tl),))
    assert len(_menus(tl.run(rec))) == 1


def test_active_pinch_blocks_dwell(tl, rec):
    tl.add(100, (_left(tl), tl.hand(2, (1000, 360), pinch=0.8)))
    tl.add(1200, (_left(tl), tl.hand(2, (1000, 360), pinch=0.15)))
    assert _menus(tl.run(rec)) == []


def test_dominant_hand_never_opens_menu(tl, rec):
    tl.add(1500, (tl.hand(2, (900, 360)),))
    assert _menus(tl.run(rec)) == []


def test_left_dominant_uses_right_palm(tl):
    rec = GestureRecognizer(dominant=Handedness.LEFT)
    tl.add(800, (tl.hand(2, (900, 360)),))
    m = _menus(tl.run(rec))
    assert len(m) == 1 and m[0].hand_id == 2


def test_unknown_dominant_disables_menu(tl):
    rec = GestureRecognizer(dominant=Handedness.UNKNOWN)
    tl.add(1500, (_left(tl),))
    assert _menus(tl.run(rec)) == []


def test_clap_candidate_reserves_input(tl, rec):
    """Left palm held still while the right hand claps onto it: no menu, even afterwards."""
    tl.add(300, (_left(tl), tl.hand(2, (LEFT_AT[0] + 260, 360))))
    tl.add(250, lambda u: (_left(tl), tl.hand(2, (LEFT_AT[0] + 260 - 230 * u, 360))))
    tl.add(60, (_left(tl), tl.hand(2, (LEFT_AT[0] + 30, 360))))
    tl.add(300, lambda u: (_left(tl), tl.hand(2, (LEFT_AT[0] + 30 + 220 * u, 360))))
    tl.add(1200, (_left(tl), tl.hand(2, (LEFT_AT[0] + 250, 360))))
    events = []
    for _, ev in tl.feed(rec):
        events += ev
        if rec.clap_candidate_active:
            assert rec.menu_dwell_progress == 0.0
    kinds = [e.kind for e in events]
    assert kinds.count(K.CLAP) == 1
    assert K.MENU_DWELL_COMPLETE not in kinds
    tl.add(100, (_left(tl, extended=0, thumb=False), tl.hand(2, (LEFT_AT[0] + 250, 360))))
    tl.add(800, (_left(tl), tl.hand(2, (LEFT_AT[0] + 250, 360))))
    assert len(_menus(tl.run(rec))) == 1                      # released, so allowed again
