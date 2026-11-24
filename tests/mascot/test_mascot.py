"""Cat mascot: mirror mapping, rig, smoothing, visibility rules and (when OpenGL exists) one real frame."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QObject, QPoint, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QMainWindow

from handcontrol.app import ControlHider, fan_out
from handcontrol.contracts import CameraState, ControlState, Mode
from handcontrol.mascot.renderer import CatRenderer, RendererError, asset_dir, load_cat
from handcontrol.mascot.retarget import BodyInfo, FaceInfo, HandInfo, Retargeter, body_info, face_info, hand_info
from handcontrol.mascot.rig import ARMS, BONES, EYE_CENTERS, HEAD, SPINE, CatRig, MascotPose, PawTarget, PoseSmoother, apply, pack, unpack
from handcontrol.mascot.window import Mascot, MascotWindow

FACE = FaceInfo((0.9, 0.35), 0.25, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, (0.0, 0.0), (0.0, 0.0))
BODY = BodyInfo(((0.6, 0.6), (1.2, 0.6)), (None, None), (None, None))


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def rig():
    return CatRig()


def points(n, **at):
    pts = [SimpleNamespace(x=0.5, y=0.5, z=0.0, visibility=1.0, presence=1.0) for _ in range(n)]
    for k, (x, y) in at.items():
        pts[int(k[1:])] = SimpleNamespace(x=x, y=y, z=0.0, visibility=1.0, presence=1.0)
    return pts


# ---------- retargeting ----------

def test_the_hand_on_the_right_of_the_mirror_moves_the_right_paw():
    r = Retargeter()
    r.set_body(BODY, 0.0)
    r.set_hands([HandInfo((1.4, 0.3), 0.0, 0.0)], 0.0)
    left, right = r.pose(0.01).paws
    assert left.weight == 0 and right.weight == 1
    assert right.x == pytest.approx(0.2 / 0.6) and right.y == pytest.approx(0.5)


def test_raw_camera_coordinates_are_mirrored():
    lm = points(21, p0=(0.2, 0.6), p9=(0.2, 0.4))
    assert hand_info(lm, [0, 0, 0, 0], 16 / 9).wrist == pytest.approx((0.8 * 16 / 9, 0.6))
    pose = points(33, p11=(0.7, 0.5), p12=(0.3, 0.5), p15=(0.9, 0.8), p16=(0.1, 0.8))
    b = body_info(pose, 1.0)
    assert b.shoulders[0][0] < b.shoulders[1][0] and b.wrists[0] == pytest.approx((0.1, 0.8))


def test_two_hands_keep_their_sides_and_a_single_hand_does_not_jump():
    r = Retargeter()
    r.set_body(BODY, 0.0)
    r.set_hands([HandInfo((1.3, 0.4), 0, 0), HandInfo((0.5, 0.4), 0, 0)], 0.0)
    left, right = r.pose(0.01).paws
    assert left.x > 0 and right.x > 0                      # both outwards, not crossed
    r.set_hands([HandInfo((1.0, 0.4), 0, 0)], 0.02)
    r.pose(0.03)
    r.set_hands([HandInfo((0.85, 0.4), 0, 0)], 0.04)       # slightly over the middle: still the right paw
    assert r.pose(0.05).paws[1].weight == 1


def test_body_wrists_are_used_when_the_hand_tracker_sees_nothing():
    r = Retargeter()
    r.set_body(replace(BODY, wrists=((0.5, 0.9), None)), 0.0)
    left, right = r.pose(0.01).paws
    assert left.weight == 1 and right.weight == 0


def test_everything_expires():
    r = Retargeter()
    r.set_face(FACE, 0.0)
    r.set_body(BODY, 0.0)
    r.set_hands([HandInfo((1.3, 0.4), 0, 0)], 0.0)
    assert r.pose(0.1).present == 1
    assert r.pose(0.5).paws[1].weight == 0
    assert r.pose(2.0) == MascotPose()


def test_face_directions_and_expressions():
    c, s = np.cos(0.4), np.sin(0.4)
    matrix = np.eye(4)
    matrix[:3, :3] = [[c, 0, s], [0, 1, 0], [-s, 0, c]]     # nose towards the right of the raw picture
    f = face_info(points(5, p0=(0.4, 0.3), p1=(0.6, 0.6)), {"jawOpen": 0.7, "eyeBlinkLeft": 0.9, "browDownLeft": 0.5,
                  "browDownRight": 0.5, "mouthSmileLeft": 0.9, "mouthSmileRight": 0.9}, matrix, 1.0)
    assert f.yaw == pytest.approx(-0.4, abs=1e-6)           # = left of the mirror
    assert f.jaw > 0.9 and f.blink[0] == 1 and f.blink[1] == 0 and f.smile == 1
    assert f.brow == 0                                      # a smile is not a frown
    r = Retargeter()
    r.set_face(replace(f, yaw=0.0), 0.0)
    r.set_face(f, 0.01)
    assert r.pose(0.02).yaw < -0.3


def test_the_usual_head_pitch_becomes_neutral():
    r = Retargeter()
    r.set_face(replace(FACE, pitch=-0.3), 0.0)
    assert r.pose(0.01).pitch == pytest.approx(0.0)


# ---------- rig ----------

def test_bundled_cat_mesh_matches_the_rig():
    v, triangles = load_cat(asset_dir() / "cat.npz")
    assert np.isfinite(v["position"]).all() and triangles.shape[1] == 3 and triangles.max() < len(v)
    assert np.array_equal(np.unique(v["joints"][v["weights"] > 0]), np.arange(BONES))
    assert np.all(v["weights"].sum(axis=1) == 255)
    lids = v[v["normal"][:, 3] != 0]                        # closing lids stay outside the eyeball
    centers = EYE_CENTERS[(lids["position"][:, 0] > 0).astype(int)]
    assert len(lids) and np.linalg.norm(lids["closed"] - centers, axis=1).min() > 0.305


def test_resting_paws_keep_the_modelled_pose(rig):
    skin = rig.solve(MascotPose(), 0.0)
    for arm in ARMS:
        assert np.allclose(skin[list(arm)], skin[SPINE], atol=1e-6)


@pytest.mark.parametrize("pose", [
    MascotPose(), MascotPose(yaw=1, pitch=-.6, roll=.7, sway=-1, lean=1, shoulders=.5, jaw=1, smile=1, brow=-1),
    MascotPose(paws=(PawTarget(5, 5, 1, 1, 1, 1.3), PawTarget(-5, -5, 1, -1, 1))),
    MascotPose(paws=(PawTarget(0, 0, 0, 0, .5), PawTarget(0, 1, 0, 0, 1)))])
def test_bones_stay_finite_and_rigid(rig, pose):
    skin = rig.solve(pose, 3.0)
    assert np.isfinite(skin).all()
    for k, m in enumerate(skin):
        scale = np.cbrt(np.linalg.det(m[:3, :3]))
        assert np.allclose(m[:3, :3] @ m[:3, :3].T, np.eye(3) * scale ** 2, atol=1e-6), k


def test_paw_follows_the_wrist_and_limbs_stay_connected(rig):
    def paw(y):
        skin = rig.solve(MascotPose(paws=(PawTarget(), PawTarget(0.4, y, 0, 0, 1))), 0.0)
        arm, rest = ARMS[1], rig.arm_rest[1]
        assert np.allclose(apply(skin[SPINE], rest[0]), apply(skin[arm[0]], rest[0]), atol=1e-6)
        for i in range(2):
            assert np.allclose(apply(skin[arm[i]], rest[i + 1]), apply(skin[arm[i + 1]], rest[i + 1]), atol=1e-6)
        return apply(skin[arm[2]], rest[2])
    low, high = paw(-0.6), paw(0.9)
    assert high[1] > low[1] + 1.2 and low[0] > 0 and high[0] > 0


def test_head_turns_to_the_same_side_as_the_mirror(rig):
    assert (rig.solve(MascotPose(yaw=0.5), 0)[HEAD][:3, :3] @ [0, 0, 1])[0] > 0.3
    assert (rig.solve(MascotPose(pitch=0.4), 0)[HEAD][:3, :3] @ [0, 0, 1])[1] > 0.2
    assert (rig.solve(MascotPose(roll=0.4), 0)[HEAD][:3, :3] @ [0, 1, 0])[0] > 0.2


def test_smoother_converges_without_overshoot_and_round_trips():
    target = MascotPose(yaw=0.6, jaw=1.0, paws=(PawTarget(), PawTarget(0.5, 0.7, 0.2, 0.1, 1.0, 0.4)), present=1.0)
    assert unpack(pack(target)) == target
    s, seen = PoseSmoother(), []
    for _ in range(90):
        seen.append(s.step(target, 1 / 30))
    assert seen[-1].yaw == pytest.approx(0.6, abs=1e-3) and max(p.yaw for p in seen) < 0.61
    assert seen[0].paws[1].x == pytest.approx(0.5)          # starts at the hand, only the weight fades in
    last = s.step(MascotPose(), 1 / 30).paws[1]
    assert last.x == pytest.approx(0.5, abs=0.02) and last.weight < 1


# ---------- window and wiring ----------

class FakeBridge(QObject):
    state_changed = Signal(object)

    def __init__(self):
        super().__init__()
        self.state = state()


def state(camera=CameraState.RUNNING, mode=Mode.POINTER, control=ControlState.PAUSED):
    return SimpleNamespace(camera_state=camera, mode=mode, control_state=control)


class FakeWindow:
    def __init__(self, ok=True):
        self.ok, self.visible, self.closed = ok, False, False

    def set_visible(self, on):
        self.visible = on and self.ok
        return self.ok or not on

    def close_renderer(self):
        self.closed = True


class FakePerception:
    enabled, closed = False, False

    def set_enabled(self, on):
        self.enabled = on

    def tap(self, frame, ms):
        pass

    def close(self):
        self.closed = True


def test_cat_is_shown_only_while_the_camera_runs_in_a_desktop_mode(app):
    bridge, window, perception = FakeBridge(), FakeWindow(), FakePerception()
    cat = Mascot(bridge, window=window, perception=perception)
    assert window.visible and perception.enabled
    for hidden in (state(camera=CameraState.OFF), state(mode=Mode.DRAWING), state(mode=Mode.INSTRUMENT)):
        bridge.state_changed.emit(hidden)
        assert not window.visible and not perception.enabled
        bridge.state_changed.emit(state(mode=Mode.SCROLL))
        assert window.visible and perception.enabled
    cat.set_enabled(False)
    assert not window.visible
    cat.close()
    assert perception.closed and window.closed


def test_a_machine_without_opengl_is_told_once(app):
    told = []
    cat = Mascot(FakeBridge(), window=FakeWindow(ok=False), perception=FakePerception(), notify=told.append)
    cat.set_enabled(True)
    assert len(told) == 1 and not cat.perception.enabled


def test_window_never_takes_input_and_survives_a_broken_renderer(app):
    class Broken:
        def render(self, *a, **k):
            raise RuntimeError("gpu lost")

        def close(self):
            self.closed = True
    broken = Broken()
    w = MascotWindow(lambda now: MascotPose(), renderer_factory=lambda: broken, cursor=lambda: QPoint(0, 0))
    flags = w.windowFlags()
    for flag in (flags.WindowTransparentForInput, flags.WindowDoesNotAcceptFocus, flags.WindowStaysOnTopHint):
        assert flags & flag
    assert w.set_visible(True)
    w._tick()
    assert broken.closed and not w.isVisible() and w.error and not w.set_visible(True)


def test_window_reports_a_missing_renderer(app):
    def fail():
        raise RendererError("no gl")
    w = MascotWindow(lambda now: MascotPose(), renderer_factory=fail)
    assert not w.set_visible(True) and w.set_visible(False)


def test_fan_out_reaches_every_reader():
    seen = []

    def bad(*_):
        raise ValueError
    fan_out([bad, lambda f, ms: seen.append((f, ms))])("frame", 5.0)
    assert seen == [("frame", 5.0)] and fan_out([]) is None and fan_out([bad]) is bad


def test_main_window_minimizes_once_when_live_control_starts(app):
    bridge, window, on = FakeBridge(), QMainWindow(), [True]
    ControlHider(bridge, window, live=True, enabled=lambda: on[0])
    active = state(control=ControlState.ACTIVE)
    window.show()
    bridge.state_changed.emit(active)
    assert window.isMinimized()
    window.showNormal()
    bridge.state_changed.emit(active)                       # already controlling: the user reopened it on purpose
    assert not window.isMinimized()
    bridge.state_changed.emit(state())
    on[0] = False
    bridge.state_changed.emit(active)
    assert not window.isMinimized()
    bridge.state_changed.emit(state(mode=Mode.DRAWING, control=ControlState.ACTIVE))
    assert not window.isMinimized()
    window.close()


def test_dry_run_never_minimizes(app):
    bridge, window = FakeBridge(), QMainWindow()
    ControlHider(bridge, window, live=False, enabled=lambda: True)
    window.show()
    bridge.state_changed.emit(state(control=ControlState.ACTIVE))
    assert not window.isMinimized()
    window.close()


def test_real_frame(app):
    try:
        r = CatRenderer()
    except RendererError as exc:
        pytest.skip(f"no OpenGL here: {exc}")
    try:
        img = r.render(MascotPose(), 0.0, 190, 171, wait=True)
        assert img.format() == QImage.Format.Format_ARGB32_Premultiplied and img.size().width() == 190
        assert img.pixelColor(2, 2).alpha() == 0 and img.pixelColor(95, 90).alpha() == 255
        assert r.render(MascotPose(), 0.0, 190, 171).isNull()
        assert not r.render(MascotPose(), 0.1, 190, 171).isNull()
    finally:
        r.close()
