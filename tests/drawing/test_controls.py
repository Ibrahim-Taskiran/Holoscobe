from dataclasses import replace
from types import SimpleNamespace

from handcontrol.contracts import (FingerInfo, FingerName, FingerState, PoseFrameFeatures,
                                   HandFeatures, Handedness, Quality)
from handcontrol.drawing_gestures import DrawingControls, crossed_forearms


def hand(side, pose, x=460, y=200):
    fingers = tuple(FingerInfo(n, FingerState.EXTENDED if v else FingerState.BENT, float(not v))
                    for n, v in zip(FingerName, (False, *pose)))
    return HandFeatures(side is Handedness.RIGHT, side, Quality.USABLE, (x, y), 40, fingers,
                        0.8, (x, y), ())


def frame(t, *hands, crossed=False):
    return PoseFrameFeatures(t, t, 640, 480, hands, False, crossed)


def test_draw_spin_carry_loss_and_erase():
    controls = DrawingControls()
    right = hand(Handedness.RIGHT, [1, 0, 0, 0])
    left = hand(Handedness.LEFT, [1]*4)
    controls.update(frame(0, right, left))
    controls.update(frame(100, right, left))
    assert controls.scene.angle > 0 and controls.tool == "brush"
    before = controls.scene.dabs.copy()
    controls.update(frame(130, hand(Handedness.RIGHT, [1]*4)))
    controls.update(frame(160))
    controls.update(frame(190, replace(right, index_tip_px=(120, 200))))
    assert controls.scene.dabs == before + [d for d in controls.scene.dabs if d.x < 0]
    controls.update(frame(230, hand(Handedness.RIGHT, [0]*4, 120)))
    assert controls.scene.dabs == before


def test_x_requires_continuity_and_works_with_occluded_hands():
    controls = DrawingControls()
    controls.update(frame(0, hand(Handedness.RIGHT, [1, 0, 0, 0])))
    for t in (30, 150, 400, 500, 600, 700, 800):
        controls.update(replace(frame(t, crossed=True), identity_ambiguous=True))
        assert controls.scene.clear_start is None
    controls.update(frame(900, crossed=True))
    assert controls.scene.clear_start == 900
    controls.update(frame(1000, hand(Handedness.RIGHT, [1, 0, 0, 0])))
    assert controls.tool == "carry"


def test_x_needs_visible_interior_intersection_near_chest():
    def joint(x, y):
        return SimpleNamespace(x=x, y=y, presence=1, visibility=1)
    joints = [None]*11 + [joint(.32,.3), joint(.68,.3), joint(.3,.64), joint(.7,.64),
                          joint(.62,.34), joint(.38,.34)]
    assert crossed_forearms(joints, 4/3)
    joints[-1].visibility = .2
    assert not crossed_forearms(joints, 4/3)
    joints[-2:] = [joint(.495,.4), joint(.505,.4)]
    assert not crossed_forearms(joints, 4/3)
