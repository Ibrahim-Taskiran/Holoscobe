"""Cat skeleton: turns a MascotPose into skinning matrices (numpy only, no Qt).

Model space: +Y up, +Z towards the viewer, x = 0 on the midline; the head is about 2 units wide.
Index 0 of a pair is the limb on the left of the screen, 1 the one on the right (the cat is a mirror image).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

# Bones of Kedi_Maskot.blend, in the order scripts/build_mascot.py writes them.
SPINE, NECK, HEAD, JAW, EAR_L, EAR_R = range(6)
ARMS = ((6, 7, 8), (9, 10, 11))
BONES = 12
SPINE_PIVOT, NECK_PIVOT, HEAD_PIVOT = np.array([0, -.8, -.3]), np.array([0, .8, -.25]), np.array([0, 1.35, -.12])
JAW_PIVOT = np.array([0.0, 1.58, 0.46])
EYE_CENTERS = np.array([[-0.41, 2.10, 0.555], [0.41, 2.10, 0.555]])
EAR_PIVOTS = np.array([[-0.56, 2.60, -0.04], [0.56, 2.60, -0.04]])
PALM_UP = (np.array([0.0, 0.97, 0.25]), np.array([0.0, -0.25, 0.97]))     # toes and sole of the modelled paws


@dataclass(frozen=True)
class PawTarget:
    """Wrist relative to its shoulder in shoulder widths: x outwards, y up. `curl` 0 open .. 1 fist."""
    x: float = 0.0
    y: float = 0.0
    curl: float = 0.0
    lean: float = 0.0                        # paw tilt in the screen plane, radians, + = to the right of the screen
    weight: float = 0.0                      # 0 = resting, 1 = follows the user
    elbow: float = 0.0                       # 0 = elbow hangs, about 1 = level with the shoulder


@dataclass(frozen=True)
class MascotPose:
    yaw: float = 0.0                         # radians, + = looks to the right of the screen
    pitch: float = 0.0                       # + = looks up
    roll: float = 0.0                        # + = tilts to the right of the screen
    sway: float = 0.0                        # body sideways, -1 .. 1
    lean: float = 0.0                        # 1 = close to the camera
    shoulders: float = 0.0                   # shoulder line tilt, radians
    jaw: float = 0.0
    smile: float = 0.0
    brow: float = 0.0                        # + raised, - frown
    blink: tuple[float, float] = (0.0, 0.0)  # screen left, screen right
    gaze: tuple[float, float] = (0.0, 0.0)   # + right, + up
    paws: tuple[PawTarget, PawTarget] = field(default_factory=lambda: (PawTarget(), PawTarget()))
    present: float = 0.0                     # 1 = somebody is tracked


def rot(axis, angle: float) -> np.ndarray:
    x, y, z = np.asarray(axis, float) / max(1e-9, float(np.linalg.norm(axis)))
    c, s, t = math.cos(angle), math.sin(angle), 1 - math.cos(angle)
    return np.array([[t*x*x + c, t*x*y - s*z, t*x*z + s*y],
                     [t*x*y + s*z, t*y*y + c, t*y*z - s*x],
                     [t*x*z - s*y, t*y*z + s*x, t*z*z + c]])


def rx(deg: float) -> np.ndarray:
    return rot((1, 0, 0), math.radians(deg))


def between(a, b) -> np.ndarray:
    """Smallest rotation that turns direction a into direction b."""
    a, b = a / np.linalg.norm(a), b / np.linalg.norm(b)
    v, c = np.cross(a, b), float(np.dot(a, b))
    s = float(np.linalg.norm(v))
    if s < 1e-6:
        return np.eye(3) if c > 0 else rot((1, 0, 0), math.pi)
    return rot(v / s, math.atan2(s, c))


def about(pivot, r: np.ndarray) -> np.ndarray:
    m = np.eye(4)
    m[:3, :3] = r
    m[:3, 3] = pivot - r @ pivot
    return m


def apply(m: np.ndarray, p) -> np.ndarray:
    return m[:3, :3] @ np.asarray(p, float) + m[:3, 3]


def frame(toes, sole) -> np.ndarray:
    """Rotation whose local +Z (toes) is `toes` and local -Y (sole) is as close to `sole` as possible."""
    z = toes / np.linalg.norm(toes)
    y = -(sole - z * np.dot(sole, z))
    n = np.linalg.norm(y)
    y = y / n if n > 1e-4 else np.array([0.0, 1.0, 0.0])
    return np.column_stack((np.cross(y, z), y, z))


def partial(r: np.ndarray, k: float) -> np.ndarray:
    """The rotation r, only the fraction k of it."""
    angle = math.acos(float(np.clip((np.trace(r) - 1) / 2, -1, 1)))
    axis = np.array([r[2, 1] - r[1, 2], r[0, 2] - r[2, 0], r[1, 0] - r[0, 1]])
    if angle < 1e-5 or np.linalg.norm(axis) < 1e-6:
        return np.eye(3)
    return rot(axis, angle * k)


class CatRig:
    def __init__(self) -> None:
        # Shoulder, elbow, wrist: the resting pose, and the half open arm of the mesh (see cat_model.py).
        self.arm_pose = [np.array([(side * .66, .72, -.10), (side * 1.0, -.12, 0.0), (side * .86, .16, .58)])
                         for side in (-1, 1)]
        self.arm_rest, self.fore_bind, self.hand_bind = [], [], []
        for shoulder, elbow, wrist in self.arm_pose:
            fore = rot(np.cross(elbow - shoulder, wrist - elbow), math.radians(-56))
            self.fore_bind.append(fore)
            self.hand_bind.append(fore @ rot(np.cross(wrist - elbow, PALM_UP[0]), math.radians(-25)))
            self.arm_rest.append(np.array([shoulder, elbow, elbow + fore @ (wrist - elbow)]))

    def solve(self, pose: MascotPose, t: float) -> np.ndarray:
        skin = np.tile(np.eye(4), (BONES, 1, 1))
        breathe = math.sin(t * 1.9)
        skin[SPINE] = about(SPINE_PIVOT, rot((0, 0, 1), -.09 * pose.sway - .35 * pose.shoulders) @ rx(4 * pose.lean + .6 * breathe))

        def look(k: float) -> np.ndarray:
            return rot((0, 1, 0), k * pose.yaw) @ rot((1, 0, 0), -k * pose.pitch) @ rot((0, 0, 1), -k * pose.roll)
        skin[NECK] = skin[SPINE] @ about(NECK_PIVOT, look(.3))
        head = skin[HEAD] = skin[NECK] @ about(HEAD_PIVOT, look(.7))
        skin[JAW] = head @ about(JAW_PIVOT, rx(24 * pose.jaw))
        for s, bone in enumerate((EAR_L, EAR_R)):
            side = -1 if s == 0 else 1
            twitch = max(0.0, math.sin(t * 0.83 + s * 2.1) - 0.965) * 6.0
            frown, raised = max(0.0, -pose.brow), max(0.0, pose.brow)
            turn = rot((0, 1, 0), side * (0.45 * frown + twitch))
            flat = rot((0, 0, 1), -side * (0.30 * frown + 0.10 * pose.smile - 0.10 * raised))
            skin[bone] = head @ about(EAR_PIVOTS[s], flat @ turn @ rx(-6.0 * raised))
        for s in (0, 1):
            self._arm(s, pose.paws[s], skin)
        return skin

    def hand(self, skin: np.ndarray, s: int) -> np.ndarray:
        """Frame of a paw: origin at the wrist, +Z towards the toes, -Y out of the pads."""
        m = np.eye(4)
        m[:3, :3] = skin[ARMS[s][2]][:3, :3] @ self.hand_bind[s] @ frame(*PALM_UP)
        m[:3, 3] = apply(skin[ARMS[s][2]], self.arm_rest[s][2])
        return m

    def _arm(self, s: int, paw: PawTarget, skin: np.ndarray) -> None:
        side = -1.0 if s == 0 else 1.0
        spine, arm, rest = skin[SPINE], ARMS[s], self.arm_rest[s]
        root, elbow, resting = (apply(spine, p) for p in self.arm_pose[s])
        upper, lower = (float(n) for n in np.linalg.norm(np.diff(rest, axis=0), axis=1))
        reach = (upper + lower) * .97
        w = float(np.clip(paw.weight, 0, 1))
        w = w * w * (3 - 2 * w)
        flat = np.array([side * np.clip(paw.x, -.45, 1.5) * 1.2, np.clip(paw.y, -.9, 1.4) * 1.25])
        n = float(np.linalg.norm(flat))
        if n > reach * .92:
            flat *= reach * .92 / n
            n = reach * .92
        # Paws stay in front of the body; a stretched arm has no depth left.
        wanted = root + np.array([*flat, max(.35, .85 * math.sqrt(reach ** 2 - n * n))])
        arc = math.sin(math.pi * w)
        target = resting + (wanted - resting) * w + np.array([0, 0, .25 * arc])
        natural = elbow - root
        free = np.array([side * (.75 + .25 * paw.elbow), -.85 + .75 * paw.elbow, -.15])
        pole = natural / np.linalg.norm(natural) * (1 - w) + free / np.linalg.norm(free) * w
        delta = target - root
        d = float(np.clip(np.linalg.norm(delta), abs(upper - lower) + .05, reach))
        axis = delta / np.linalg.norm(delta)
        bend = pole - axis * np.dot(pole, axis)
        bend = bend / max(1e-6, float(np.linalg.norm(bend)))
        along = (upper ** 2 - lower ** 2 + d * d) / (2 * d)
        joints = [root, root + axis * along + bend * math.sqrt(max(0.0, upper ** 2 - along ** 2)), root + axis * d]
        base = spine
        for i in range(2):
            m = np.eye(4)
            m[:3, :3] = between(base[:3, :3] @ (rest[i + 1] - rest[i]), joints[i + 1] - joints[i]) @ base[:3, :3]
            m[:3, 3] = apply(base, rest[i]) - m[:3, :3] @ rest[i]
            skin[arm[i]] = base = m
        # A raised paw shows its pads, a low one points forward and down.
        fore = (joints[2] - joints[1]) / lower
        up = float(np.clip((fore[1] + .35) / .6, 0, 1))
        toes = PALM_UP[0] * up + (fore * .6 + np.array([0, -.1, .8])) * (1 - up)
        sole = PALM_UP[1] * up + np.array([0, -1.0, 0]) * (1 - up)
        shown = rot((0, 0, 1), -paw.lean * up * .8) @ frame(toes, sole) @ rx(55 * paw.curl)
        m = np.eye(4)
        m[:3, :3] = partial(shown @ frame(*PALM_UP).T @ spine[:3, :3].T, w) @ spine[:3, :3] @ self.hand_bind[s].T
        m[:3, 3] = apply(base, rest[2]) - m[:3, :3] @ rest[2]
        skin[arm[2]] = m


class Spring:
    """Critically damped follower for a vector of values: smooth, no overshoot, frame rate independent."""

    def __init__(self, size: int, speed) -> None:
        self.value = np.zeros(size)
        self.velocity = np.zeros(size)
        self.speed = np.broadcast_to(np.asarray(speed, float), (size,))

    def step(self, target, dt: float) -> np.ndarray:
        dt = min(max(dt, 0.0), 0.1)
        w = self.speed
        x, e = self.value - target, np.exp(-w * dt)
        tmp = (self.velocity + w * x) * dt
        self.velocity = (self.velocity - w * tmp) * e
        self.value = target + (x + tmp) * e
        return self.value


_SPEEDS = [14, 14, 12, 7, 5, 8, 26, 12, 14, 34, 34, 22, 22] + [20, 20, 16, 14, 9, 10] * 2 + [6]
PAWS_AT = (13, 19)


def pack(p: MascotPose) -> np.ndarray:
    paws = [v for w in p.paws for v in (w.x, w.y, w.curl, w.lean, w.weight, w.elbow)]
    return np.array([p.yaw, p.pitch, p.roll, p.sway, p.lean, p.shoulders, p.jaw, p.smile, p.brow, *p.blink, *p.gaze,
                     *paws, p.present], float)


def unpack(values) -> MascotPose:
    v = [float(x) for x in values]
    return MascotPose(*v[:9], blink=(v[9], v[10]), gaze=(v[11], v[12]),
                      paws=(PawTarget(*v[13:19]), PawTarget(*v[19:25])), present=v[25])


class PoseSmoother:
    def __init__(self) -> None:
        self._spring = Spring(len(_SPEEDS), _SPEEDS)

    def step(self, pose: MascotPose, dt: float) -> MascotPose:
        s, target = self._spring, pack(pose)
        for base in PAWS_AT:
            if target[base + 4] <= 0:                          # going to rest: keep the last spot while it fades out
                target[base:base + 4] = s.value[base:base + 4]
            elif s.value[base + 4] < 0.02:                     # starting: do not fly in from an old spot
                s.value[base:base + 4], s.velocity[base:base + 4] = target[base:base + 4], 0.0
        return unpack(s.step(target, dt))


__all__ = ["BONES", "CatRig", "EYE_CENTERS", "EAR_L", "EAR_R", "HEAD", "JAW", "MascotPose", "PawTarget", "PoseSmoother",
           "Spring", "pack", "unpack"]
