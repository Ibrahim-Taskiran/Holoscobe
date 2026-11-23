import math

import pytest

from handcontrol.drawing import CLEAR_MS, WORK_DEPTH, InkScene, projected_y, turn


def test_spinning_brush_stays_at_tip_and_builds_a_helix():
    scene = InkScene()
    for i in range(121):
        scene.angle = math.tau*i/120
        scene.paint(0.18, i/1000, i*33)
        last = scene._last
        assert turn(last[0], last[2], math.cos(scene.angle), math.sin(scene.angle)) == pytest.approx((0.18, WORK_DEPTH))
    assert min(d.z for d in scene.dabs) < -0.18
    assert max(d.z for d in scene.dabs) > 0.18
    assert scene._last[1] == pytest.approx(0.12)


def test_lift_and_repeated_front_erase_preserve_rear_ink():
    scene = InkScene()
    scene.paint(-0.2, 0.1, 0)
    rear = scene.dabs.copy()
    scene.lift()
    scene.angle = math.pi
    scene.paint(0.2, 0.1, 100)
    assert len(scene.dabs) > len(rear)
    assert all(abs(d.x) > 0.15 for d in scene.dabs)
    for _ in range(10):
        scene.erase(0.2, 0.1)
    assert scene.dabs == rear


def test_rear_ink_needs_its_own_stroke_and_rotated_ink_is_erasable():
    scene = InkScene()
    scene.paint(-0.2, 0.0, 0)
    scene.lift()
    scene.angle = math.pi
    scene.paint(0.2, 0.0, 100)
    for _ in range(5):
        scene.erase(0.2, 0.0)
    assert scene.erase_front and scene.dabs
    scene.lift()                                # fist opened and closed again on the rear ink
    for _ in range(2):
        scene.erase(0.2, 0.036)                 # the elevated view shows the rear a little lower
    assert scene.erase_front is False and len(scene.dabs) < 3
    scene.dabs.clear()
    scene.angle = 0.0
    scene.paint(0.2, 0.0, 200)
    scene.lift()
    scene.angle = -0.3                          # no longer in the work plane, still in front
    d = scene.dabs[0]
    x, depth = turn(d.x, d.z, math.cos(scene.angle), math.sin(scene.angle))
    scene.erase(x, projected_y(d.y, depth))
    assert d not in scene.dabs


def test_local_erase_breaks_band_and_clear_blocks_deposits():
    scene = InkScene()
    scene.paint(-0.12, 0, 0)
    scene.paint(0.12, 0, 100)
    scene.erase(0, 0)
    assert scene.dabs and all(abs(d.x) > 0.032 for d in scene.dabs)
    scene.clear(200)
    before = scene.dabs.copy()
    scene.paint(0, 0, 250)
    assert scene.dabs == before
    scene.advance(200 + CLEAR_MS)
    assert not scene.dabs
    scene.paint(0, 0, 2500)
    assert scene.dabs
