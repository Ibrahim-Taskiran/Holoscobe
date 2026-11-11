"""Scroll, zoom and volume through the real chain."""
from __future__ import annotations

from handcontrol.config import Settings
from handcontrol.contracts import ActionKind as A, Mode

from integ_synth import PINCH, POINT, Rig, TARGET, hand, lerp

R0, L0 = (220.0, 300.0), (420.0, 300.0)


def _engaged(rig: Rig, mode: Mode, settings: Settings | None = None) -> Rig:
    rig.pipe.set_mode(mode)
    rig.activate([hand(POINT, R0)])
    return rig


def test_scroll_up_emits_steps_and_freezes_pointer(rig):
    _engaged(rig, Mode.SCROLL)
    rig.run(150, [hand(PINCH, R0)])
    start = len(rig.sink.actions)
    rig.run(600, lambda u: [hand(PINCH, (220, lerp(300, 160, u)))])     # hand up
    tail = [a for a in rig.sink.actions[start:] if a.kind is not A.RELEASE_ALL]
    assert tail and all(a.kind is A.SCROLL for a in tail)
    assert all(a.steps > 0 and a.target == TARGET for a in tail)
    total = sum(a.steps for a in tail)
    assert 3 <= total <= 8                         # 0.29 frame heights: (0.29-0.02)/0.04 = 6 steps
    rig.run(200, [hand(POINT, (220, 160))])
    assert rig.count(A.LEFT_CLICK) == 0


def test_scroll_reversed_direction_setting():
    s = Settings()
    s.scroll_direction = "reversed"
    rig = _engaged(Rig(s), Mode.SCROLL)
    rig.run(150, [hand(PINCH, R0)])
    rig.run(600, lambda u: [hand(PINCH, (220, lerp(300, 160, u)))])
    assert rig.sink.of(A.SCROLL) and all(a.steps < 0 for a in rig.sink.of(A.SCROLL))


def test_scroll_needs_foreground_target():
    rig = Rig()
    rig.windows.foreground = None
    _engaged(rig, Mode.SCROLL)
    rig.run(150, [hand(PINCH, R0)])
    rig.run(600, lambda u: [hand(PINCH, (220, lerp(300, 160, u)))])
    assert rig.count(A.SCROLL) == 0


def _two(pose_r, pose_l, dr=0.0):
    return [hand(pose_r, (R0[0] - dr, 300.0)), hand(pose_l, (L0[0] + dr, 300.0), side="left")]


def test_zoom_second_pinch_within_300ms_zooms_in(rig):
    rig.pipe.set_mode(Mode.ZOOM)
    rig.activate(_two(POINT, POINT))
    rig.run(100, _two(PINCH, POINT))
    rig.run(150, _two(PINCH, PINCH))               # second pinch ~150 ms later
    rig.run(600, lambda u: _two(PINCH, PINCH, dr=lerp(0, 100, u)))   # apart: +2.1 pu
    zooms = rig.sink.of(A.ZOOM)
    assert zooms and all(z.steps > 0 for z in zooms)
    assert 3 <= sum(z.steps for z in zooms) <= 6
    assert set(rig.kinds()) <= {A.MOVE_POINTER, A.ZOOM}


def test_zoom_second_pinch_too_late_does_nothing(rig):
    rig.pipe.set_mode(Mode.ZOOM)
    rig.activate(_two(POINT, POINT))
    rig.run(450, _two(PINCH, POINT))
    rig.run(150, _two(PINCH, PINCH))
    rig.run(600, lambda u: _two(PINCH, PINCH, dr=lerp(0, 100, u)))
    assert rig.count(A.ZOOM) == 0


def test_zoom_release_of_either_hand_cancels(rig):
    rig.pipe.set_mode(Mode.ZOOM)
    rig.activate(_two(POINT, POINT))
    rig.run(100, _two(PINCH, POINT))
    rig.run(150, _two(PINCH, PINCH))
    rig.run(300, lambda u: _two(PINCH, PINCH, dr=lerp(0, 50, u)))
    rig.run(150, _two(PINCH, POINT, dr=50))       # left release (70 ms debounce) cancels zoom
    n = rig.count(A.ZOOM)
    rig.run(400, lambda u: _two(PINCH, POINT, dr=lerp(50, 120, u)))
    assert rig.count(A.ZOOM) == n


def test_two_pinched_hands_approaching_are_not_a_clap(rig):
    rig.pipe.set_mode(Mode.ZOOM)
    rig.activate(_two(POINT, POINT, dr=-0.0))
    rig.run(100, _two(PINCH, POINT, dr=60))
    rig.run(150, _two(PINCH, PINCH, dr=60))
    rig.run(300, lambda u: _two(PINCH, PINCH, dr=lerp(60, -80, u)))
    rig.run(300, lambda u: _two(PINCH, PINCH, dr=lerp(-80, 60, u)))
    assert rig.state.value == "active"


def test_volume_up_is_clamped_and_rate_limited(rig):
    _engaged(rig, Mode.VOLUME)
    rig.run(150, [hand(PINCH, R0)])
    t0 = rig.t
    rig.run(1000, lambda u: [hand(PINCH, (220, lerp(300, 60, u)))])  # 0.5 frame heights * gain 2
    vols = rig.sink.of(A.SET_VOLUME)
    assert vols and all(0.0 <= v.value <= 1.0 for v in vols)
    assert vols[-1].value == 1.0
    assert [v.value for v in vols] == sorted(v.value for v in vols)
    assert len(vols) <= 1 + (rig.t - t0) / 100.0   # 10 updates / s
    assert set(rig.kinds()) <= {A.MOVE_POINTER, A.SET_VOLUME}


def test_volume_down_clamps_at_zero(rig):
    rig.activate([hand(POINT, (220, 150))])
    rig.pipe.set_mode(Mode.VOLUME)
    rig.run(300, [hand(POINT, (220, 150))])
    rig.run(150, [hand(PINCH, (220, 150))])
    rig.run(1000, lambda u: [hand(PINCH, (220, lerp(150, 420, u)))])
    assert rig.sink.of(A.SET_VOLUME)[-1].value == 0.0
