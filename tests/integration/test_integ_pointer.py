"""Pointer mode through the real chain."""
from __future__ import annotations

import math

from handcontrol.config import Settings
from handcontrol.contracts import ActionKind as A, Handedness
from handcontrol.dryrun import make_monitor

from integ_synth import DOM_C, OPEN, PINCH, POINT, Rig, hand, lerp


def _point(x: float, y: float = 300.0, **kw):
    return [hand(POINT, (x, y), **kw)]


def test_pointing_sweep_moves_only(rig):
    rig.activate(_point(150))
    rig.run(900, lambda u: _point(lerp(150, 450, u), lerp(250, 350, u)))
    moves = rig.sink.of(A.MOVE_POINTER)
    assert len(moves) > 15
    assert set(rig.kinds()) == {A.MOVE_POINTER}
    xs = [m.x for m in moves]
    assert xs[-1] < xs[0]                          # mirror: hand to image right -> pointer left


def _last_move_before(rig: Rig, idx: int):
    for a in reversed(rig.sink.actions[:idx]):
        if a.kind is A.MOVE_POINTER:
            return a
    return None


def test_pinch_release_clicks_once_at_latched_point(rig):
    rig.activate(_point(250))
    rig.run(150, [hand(PINCH, DOM_C)])
    rig.run(400, _point(250))
    clicks = rig.sink.of(A.LEFT_CLICK)
    assert len(clicks) == 1
    i = rig.sink.actions.index(clicks[0])
    before = _last_move_before(rig, i)
    assert before is not None and (before.x, before.y) == (clicks[0].x, clicks[0].y)


def test_pinch_onset_drift_of_latched_point_is_bounded(rig):
    """The index tip moves while the pinch closes; the click latches the pointer at PINCH_START.
    Synthetic pose change (index curl 0 -> 0.65) is a worst case; this measures, not proves, drift."""
    rig.activate(_point(250))
    rest = rig.sink.of(A.MOVE_POINTER)[-1]
    rig.run(150, [hand(PINCH, DOM_C)])
    rig.run(300, _point(250))
    click = rig.sink.of(A.LEFT_CLICK)[0]
    drift = math.dist((rest.x, rest.y), (click.x, click.y))
    assert drift < 400                             # documented in the report; see integration notes


def test_long_pinch_does_not_click(rig):
    rig.activate(_point(250))
    rig.run(700, [hand(PINCH, DOM_C)])
    rig.run(300, _point(250))
    assert rig.count(A.LEFT_CLICK) == 0


def test_pinch_with_motion_does_not_click(rig):
    rig.activate(_point(250))
    rig.run(100, [hand(PINCH, DOM_C)])
    rig.run(200, lambda u: [hand(PINCH, (lerp(250, 330, u), 300))])
    rig.run(300, _point(330))
    assert rig.count(A.LEFT_CLICK) == 0


def test_pointer_frozen_while_pinched(rig):
    rig.activate(_point(250))
    rig.run(120, [hand(PINCH, DOM_C)])
    n = rig.count(A.MOVE_POINTER)
    rig.run(250, lambda u: [hand(PINCH, (lerp(250, 400, u), 300))])
    assert rig.count(A.MOVE_POINTER) == n


def test_mirror_off_reverses_pointer_direction():
    s = Settings()
    s.mirror_preview = False
    rig = Rig(s)
    rig.activate(_point(150))
    rig.run(600, lambda u: _point(lerp(150, 450, u)))
    xs = [m.x for m in rig.sink.of(A.MOVE_POINTER)]
    assert xs[-1] > xs[0]


def test_calibration_bounds_are_unmirrored_settings():
    """Regression: config.CalibrationBounds is unmirrored, mapping.CalibrationRect is in the
    mirrored view. Active region = left half of the camera image."""
    s = Settings()
    s.calibration.left, s.calibration.right = 0.0, 0.5
    rig = Rig(s)
    rig.activate(_point(160))
    tip_u = 1.0 - rig.pipe.last_features.hands[0].index_tip_px[0] / 640.0      # mirrored view
    expected = (tip_u - 0.5) / 0.5 * 1919                                    # rect (0.5, 1.0) mirrored
    x = rig.sink.of(A.MOVE_POINTER)[-1].x
    assert 0.1 < tip_u - 0.5 < 0.4 and abs(x - expected) < 20                # unconverted rect clamps to 1919


def test_left_dominant_hand_drives_pointer():
    s = Settings()
    s.dominant_hand = "left"
    rig = Rig(s)
    rig.activate([hand(POINT, (450, 300), side="left")])
    rig.run(500, lambda u: [hand(POINT, (lerp(450, 300, u), 300), side="left"),
                            hand(POINT, (150, 300), side="right")])
    assert rig.count(A.MOVE_POINTER) > 5
    rig.sink.clear()
    rig.run(500, lambda u: [hand(POINT, (lerp(150, 300, u), 300), side="right")])   # right hand only
    assert rig.count(A.MOVE_POINTER) == 0


def test_left_dominant_pinch_clicks_with_left_hand():
    s = Settings()
    s.dominant_hand = "left"
    rig = Rig(s)
    rig.activate([hand(POINT, (450, 300), side="left")])
    rig.run(150, [hand(PINCH, (450, 300), side="left")])
    rig.run(300, [hand(POINT, (450, 300), side="left")])
    assert rig.count(A.LEFT_CLICK) == 1
    rig.run(150, [hand(PINCH, (150, 300), side="right")])
    rig.run(300, [hand(POINT, (150, 300), side="right")])
    assert rig.count(A.LEFT_CLICK) == 1


def test_primary_monitor_mapping_keeps_pointer_on_primary():
    """Regression: settings monitor_mapping 'primary' (the default) had no consumer; the pointer
    spanned the whole virtual desktop."""
    mons = [make_monitor(0, 0, 1920, 1080, primary=True), make_monitor(1920, 0, 1920, 1080)]
    rig = Rig(Settings(), monitors=mons)
    rig.activate(_point(150))
    rig.run(600, lambda u: _point(lerp(500, 60, u))).run(300, _point(60))
    xs = [m.x for m in rig.sink.of(A.MOVE_POINTER)]
    assert max(xs) <= 1919 and max(xs) > 1800
    s = Settings()
    s.monitor_mapping.mode = "virtual_desktop"
    rig2 = Rig(s, monitors=mons)
    rig2.activate(_point(150))
    rig2.run(600, lambda u: _point(lerp(500, 60, u))).run(300, _point(60))
    assert max(m.x for m in rig2.sink.of(A.MOVE_POINTER)) > 3000


def test_unknown_label_hand_never_drives_pointer(rig):
    rig.activate([hand(POINT, (250, 300), label=Handedness.UNKNOWN)])
    rig.run(500, lambda u: [hand(POINT, (lerp(250, 400, u), 300), label=Handedness.UNKNOWN)])
    assert rig.kinds() == []


def test_open_palm_also_points(rig):
    rig.activate([hand(OPEN, (250, 300))])
    rig.run(400, lambda u: [hand(OPEN, (lerp(250, 350, u), 300))])
    assert rig.count(A.MOVE_POINTER) > 3
