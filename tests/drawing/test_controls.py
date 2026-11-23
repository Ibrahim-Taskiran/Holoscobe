import math
from dataclasses import replace
from types import SimpleNamespace

from handcontrol.contracts import (FingerInfo, FingerName, FingerState, PoseFrameFeatures,
                                   HandFeatures, Handedness, Landmark, Quality)
from handcontrol.drawing import PALETTE
from handcontrol.drawing_gestures import DrawingControls, crossed_forearms


def hand(side, pose, x=460, y=200, tilt=0.0, hand_id=None, quality=Quality.USABLE, curls=None,
         pinch=0.8):
    """tilt: degrees towards +x in the image. curls: raw finger curls while the states still lag behind."""
    fingers = tuple(FingerInfo(n, FingerState.EXTENDED if v else FingerState.BENT, float(not v))
                    for n, v in zip(FingerName, (False, *pose)))
    if curls:
        fingers = (fingers[0], *(replace(f, curl=c) for f, c in zip(fingers[1:], curls)))
    a = math.radians(tilt)
    marks = [Landmark(.5, .5)]*21
    marks[9] = Landmark(.5 + .1*math.sin(a)*480/640, .5 - .1*math.cos(a))
    return HandFeatures(side is Handedness.RIGHT if hand_id is None else hand_id, side, quality, (x, y), 40,
                        fingers, pinch, (x, y), tuple(marks))


def frame(t, *hands, crossed=False):
    return PoseFrameFeatures(t, t, 640, 480, hands, False, crossed)


PEN, OPEN, FIST = [1, 0, 0, 0], [1]*4, [0]*4
RIGHT, LEFT = Handedness.RIGHT, Handedness.LEFT


def feed(controls, t, *hands, frames=6, step=30, **kw):
    for _ in range(frames):
        controls.update(frame(t, *hands, **kw))
        t += step
    return t


def test_draw_carry_loss_and_erase():
    c = DrawingControls()
    t = feed(c, 0, hand(RIGHT, PEN))
    assert c.tool == "brush" and c.scene.dabs
    before = c.scene.dabs.copy()
    t = feed(c, t, hand(RIGHT, OPEN), frames=1)
    assert c.tool == "carry"
    t = feed(c, t, frames=2)
    t = feed(c, t, hand(RIGHT, PEN, 120))
    assert c.scene.dabs[:len(before)] == before and all(d.x < 0 for d in c.scene.dabs[len(before):])
    t = feed(c, t, hand(RIGHT, FIST, 120))
    assert c.tool == "erase" and c.scene.dabs == before


def test_short_false_poses_leave_no_mark():
    c = DrawingControls()
    t = feed(c, 0, hand(RIGHT, OPEN))
    t = feed(c, t, hand(RIGHT, PEN), frames=4)            # 90 ms
    t = feed(c, t, hand(RIGHT, OPEN))
    assert not c.scene.dabs
    t = feed(c, t, hand(RIGHT, PEN))
    ink = c.scene.dabs.copy()
    t = feed(c, t, hand(RIGHT, FIST), frames=4)
    feed(c, t, hand(RIGHT, OPEN))
    assert ink and c.scene.dabs == ink


def test_opening_hand_stops_the_ink_before_the_finger_states_change():
    c = DrawingControls()
    t = feed(c, 0, hand(RIGHT, PEN))
    ink = c.scene.dabs.copy()
    feed(c, t, hand(RIGHT, PEN, 480, curls=(0, .3, .3, .3)), frames=2)
    assert c.scene.dabs == ink


def test_brief_loss_continues_the_stroke_but_long_loss_ends_it():
    c = DrawingControls()
    t = feed(c, 0, hand(RIGHT, PEN, 400))
    t = feed(c, t, hand(RIGHT, PEN, 405, quality=Quality.DEGRADED), frames=1)
    t = feed(c, t, frames=3)
    n = len(c.scene.dabs)
    t = feed(c, t, hand(RIGHT, PEN, 440), frames=1)
    assert c.tool == "brush" and all(d.radius < .0105 for d in c.scene.dabs[n:]) and len(c.scene.dabs) > n + 4
    t = feed(c, t, frames=7)
    feed(c, t, hand(RIGHT, PEN, 440), frames=1)
    assert c.tool == "carry"


def test_left_palm_tilt_spins_both_ways_and_upright_stops():
    def turned(tilt):
        c = DrawingControls()
        feed(c, 0, hand(LEFT, OPEN, 100, tilt=tilt), frames=20)
        a = c.scene.angle
        return a - math.tau if a > math.pi else a
    assert turned(30) > 0.1 and turned(-30) < -0.1      # positive: the front surface follows the lean to +x
    assert turned(0) == turned(12) == turned(-12) == 0
    assert turned(45) > turned(20) > 0


def test_spin_bridges_short_loss_and_coasts_to_a_stop():
    c = DrawingControls()
    t = feed(c, 0, hand(LEFT, OPEN, 100, tilt=30), frames=10)
    t = feed(c, t, frames=4)
    assert c.spin > 0
    t = feed(c, t, hand(LEFT, FIST, 100), frames=1)
    assert c.spin == 0 and c.scene.spin_speed > 0
    feed(c, t, hand(LEFT, OPEN, 100), frames=30)
    assert c.scene.spin_speed == 0


def test_x_accumulates_over_flicker_and_works_with_occluded_hands():
    c = DrawingControls()
    t = feed(c, 0, hand(RIGHT, PEN))
    for i in range(40):                                  # every third pose frame is missed
        c.update(replace(frame(t, crossed=i % 3 != 2), identity_ambiguous=True), i % 5 != 0)
        t += 30
        if c.scene.clear_start is not None:
            break
    assert c.scene.clear_start is not None
    feed(c, t, hand(RIGHT, PEN))
    assert c.tool == "carry"


def test_single_false_x_and_long_gaps_do_not_clear():
    c = DrawingControls()
    t = feed(c, 0, hand(RIGHT, PEN))
    for _ in range(10):
        t = feed(c, t, crossed=True, frames=2)
        t = feed(c, t, hand(RIGHT, PEN), frames=4)
        t = feed(c, t + 250, crossed=True, frames=1)
    assert c.scene.clear_start is None


def test_x_needs_visible_interior_intersection_near_chest():
    def joint(x, y):
        return SimpleNamespace(x=x, y=y, presence=1, visibility=1)
    joints = [None]*11 + [joint(.32,.3), joint(.68,.3), joint(.3,.64), joint(.7,.64),
                          joint(.62,.34), joint(.38,.34)]
    assert crossed_forearms(joints, 4/3)
    joints[-1].visibility = .2
    assert not crossed_forearms(joints, 4/3)
    joints[-1].visibility = 1
    for elbow in joints[13:15]:                          # elbows below the picture: swapped wrists are enough
        elbow.visibility = elbow.presence = .1
    assert crossed_forearms(joints, 4/3)
    joints[-2:] = [joint(.38, .34), joint(.62, .34)]     # hands up, not crossed
    assert not crossed_forearms(joints, 4/3)
    joints[-2:] = [joint(.62, .75), joint(.38, .75)]     # hands crossed on the lap
    assert not crossed_forearms(joints, 4/3)
    joints[-2:] = [joint(.495, .4), joint(.505, .4)]     # praying hands
    assert not crossed_forearms(joints, 4/3)


OK = [0, 1, 1, 1]
PU = 40


def slice_at(i, n=len(PALETTE), x=300, y=240):
    a = math.tau*i/n
    return x + 1.2*PU*math.sin(a), y - 1.2*PU*math.cos(a)


def test_pinch_opens_the_palette_and_letting_go_picks_every_color():
    for i in range(len(PALETTE)):
        c = DrawingControls()
        t = feed(c, 0, hand(RIGHT, OK, 300, 240, pinch=.1), frames=9)
        assert c.palette is not None and c.palette.hovered is None and not c.scene.dabs
        x, y = slice_at(i)
        t = feed(c, t, hand(RIGHT, OK, x, y, pinch=.1))
        assert c.palette.hovered == i
        t = feed(c, t, hand(RIGHT, OPEN, x, y))
        assert c.palette is None and c.scene.color == i
        feed(c, t, hand(RIGHT, PEN, x, y))
        assert c.scene.dabs and all(d.color == i for d in c.scene.dabs)


def test_palette_cancels_in_the_middle_on_loss_and_on_x():
    def opened():
        c = DrawingControls()
        c.scene.color = 3
        return c, feed(c, 0, hand(RIGHT, OK, 300, 240, pinch=.1), frames=9)
    c, t = opened()
    feed(c, t, hand(RIGHT, OPEN, 300, 240))
    assert c.palette is None and c.scene.color == 3
    c, t = opened()
    t = feed(c, t, hand(RIGHT, OK, *slice_at(5), pinch=.1))
    t = feed(c, t, frames=6)                               # short loss keeps it open
    assert c.palette is not None
    t = feed(c, t, frames=9)
    assert c.palette is None and c.scene.color == 3
    c, t = opened()
    feed(c, t, hand(RIGHT, OK, *slice_at(5), pinch=.1), crossed=True)
    assert c.palette is None and c.scene.color == 3


def test_fist_point_and_short_pinch_never_open_the_palette():
    for pose in (FIST, PEN, [0, 1, 0, 0]):
        c = DrawingControls()
        feed(c, 0, hand(RIGHT, pose, pinch=.1), frames=20)
        assert c.palette is None
    c = DrawingControls()
    t = feed(c, 0, hand(RIGHT, OK, pinch=.1), frames=5)
    feed(c, t, hand(RIGHT, OPEN), frames=2)
    assert c.palette is None
    feed(c, t, hand(LEFT, OK, pinch=.1), frames=20)        # left hand only spins
    assert c.palette is None


def test_jitter_while_letting_go_does_not_change_the_pick():
    c = DrawingControls()
    t = feed(c, 0, hand(RIGHT, OK, 300, 240, pinch=.1), frames=9)
    t = feed(c, t, hand(RIGHT, OK, *slice_at(2), pinch=.1))
    t = feed(c, t, hand(RIGHT, OK, *slice_at(6), pinch=.6), frames=1)
    feed(c, t, hand(RIGHT, OPEN, *slice_at(6)))
    assert c.scene.color == 2
