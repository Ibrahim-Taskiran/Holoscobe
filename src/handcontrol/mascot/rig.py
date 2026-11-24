"""Cat skeleton: turns a MascotPose into skinning matrices (numpy only, no Qt).

Model space: +Y up, +Z towards the viewer, x = 0 on the midline; the head is about 1.5 units wide.
Index 0 of a pair is the limb on the left of the screen, 1 the one on the right (the cat is a mirror image).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

SPINE, SPINE2, CHEST, NECK, HEAD = 1, 2, 3, 4, 5
ARMS = ((7, 8, 9, 10), (12, 13, 14, 15))
HINDS = ((24, 25, 26, 27), (29, 30, 31, 32))
TAIL = (17, 18, 19, 20, 21, 22)
JAW, EAR_L, EAR_R = 34, 35, 36               # virtual bones appended to the 34 of the model
BONES = 37
JAW_PIVOT = np.array([0.0, 3.68, 1.12])
EAR_PIVOTS = np.array([[-0.42, 4.42, 0.78], [0.42, 4.42, 0.78]])
EYE_CENTERS = np.array([[-0.258, 3.985, 1.415], [0.258, 3.985, 1.415]])

UPRIGHT = (-44.0, -9.0, -7.0)              # spine, spine2, chest pitch: standing cat -> sitting up
NECK_PITCH = 34.0
REACH = 2.95
HEAD_SCALE = 1.16


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


class CatRig:
    def __init__(self, heads: np.ndarray, parents) -> None:
        self.heads = np.asarray(heads, float)
        self.parents = [int(p) for p in parents]
        self.arm_rest = [np.array([self.heads[b] for b in arm]) for arm in ARMS]

    def solve(self, pose: MascotPose, t: float) -> np.ndarray:
        """Skinning matrices (BONES, 4, 4) for the pose at time t (seconds, for breathing and the tail)."""
        breathe = math.sin(t * 1.9)
        local: dict[int, np.ndarray] = {}
        body = rot((0, 0, 1), -0.16 * pose.sway - 0.55 * pose.shoulders) @ rx(6.0 * pose.lean)
        local[SPINE] = body @ rx(UPRIGHT[0])
        local[SPINE2] = rot((0, 0, 1), -0.05 * pose.sway) @ rx(UPRIGHT[1] - 0.5 * breathe)
        local[CHEST] = rx(UPRIGHT[2] - 0.9 * breathe)
        part = (rot((0, 1, 0), pose.yaw * 0.35) @ rot((1, 0, 0), -pose.pitch * 0.25)
                @ rot((0, 0, 1), -pose.roll * 0.35))
        torso = rx(sum(UPRIGHT))                              # the neck turns around the axes of the viewer
        local[NECK] = torso.T @ part @ torso @ rx(NECK_PITCH + 0.4 * breathe)
        raised = max(p.weight * min(1.0, max(0.0, p.y + 0.1)) for p in pose.paws)
        stretch = np.array([0.0, 0.30 + 0.26 * raised, 0.26 + 0.18 * raised])
        for s, hind in enumerate(HINDS):
            side = -1 if s == 0 else 1
            local[hind[0]] = rot((0, 0, 1), side * 0.18) @ rx(-38.0)
            local[hind[1]] = rx(62.0)
            local[hind[2]] = rx(-55.0)
        skin = np.tile(np.eye(4), (BONES, 1, 1))
        for k in range(len(self.heads)):                      # parents always come before their children
            if k in (HEAD, *ARMS[0], *ARMS[1], *TAIL):
                continue
            p = self.parents[k]
            base = skin[p] if p >= 0 else np.eye(4)
            skin[k] = base @ about(self.heads[k], local[k]) if k in local else base
        pivot = apply(skin[NECK], self.heads[HEAD])           # the head keeps its own orientation, not the one of the body
        look = rot((0, 1, 0), pose.yaw) @ rot((1, 0, 0), -pose.pitch) @ rot((0, 0, 1), -pose.roll)
        head = np.eye(4)
        head[:3, :3] = HEAD_SCALE * rot((0, 0, 1), -0.10 * pose.sway - 0.25 * pose.shoulders) @ look
        head[:3, 3] = pivot + stretch - head[:3, :3] @ self.heads[HEAD]
        skin[HEAD] = skin[6] = head
        skin[JAW] = head @ about(JAW_PIVOT, rx(26.0 * pose.jaw))
        for s, bone in enumerate((EAR_L, EAR_R)):
            side = -1 if s == 0 else 1
            twitch = max(0.0, math.sin(t * 0.83 + s * 2.1) - 0.965) * 6.0
            frown, raised = max(0.0, -pose.brow), max(0.0, pose.brow)
            turn = rot((0, 1, 0), side * (0.10 + 0.70 * frown + twitch))
            flat = rot((0, 0, 1), -side * (0.28 * frown + 0.12 * pose.smile - 0.16 * raised))
            skin[bone] = head @ about(EAR_PIVOTS[s], flat @ turn @ rx(-8.0 * raised))
        for s in (0, 1):
            self._arm(s, pose.paws[s], skin)
        self._tail(skin, t, pose.smile)
        return skin

    def _tail(self, skin: np.ndarray, t: float, smile: float) -> None:
        """The tail curls up beside the body and sways."""
        base = skin[SPINE]
        for i, b in enumerate(TAIL):
            sway = math.sin(t * (1.3 + 0.9 * smile) - i * 0.6) * (3.0 + 3.2 * i)
            a = math.radians((-8, 22, 52, 78, 92, 108)[i] + sway)
            wanted = np.array([math.cos(a), math.sin(a), -0.15])
            end = self.heads[TAIL[i + 1]] if i + 1 < len(TAIL) else self.heads[b] * 2 - self.heads[TAIL[i - 1]]
            m = np.eye(4)
            m[:3, :3] = between(base[:3, :3] @ (end - self.heads[b]), wanted) @ base[:3, :3]
            m[:3, 3] = apply(base, self.heads[b]) - m[:3, :3] @ self.heads[b]
            skin[b] = base = m
        skin[TAIL[-1] + 1] = base

    def _arm(self, s: int, paw: PawTarget, skin: np.ndarray) -> None:
        side = -1.0 if s == 0 else 1.0
        chest, arm, rest = skin[CHEST], ARMS[s], self.arm_rest[s]
        root = apply(chest, rest[0])
        resting = root + np.array([side * 0.10, -1.82, 1.95])
        x, y = np.clip(paw.x, -0.9, 1.7), np.clip(paw.y, -1.2, 1.7)
        flat = np.array([side * x * 1.75, 0.35 + y * 1.85])
        n = float(np.linalg.norm(flat))
        if n > REACH * 0.92:
            flat *= REACH * 0.92 / n
            n = REACH * 0.92
        depth = max(0.75, 0.8 * math.sqrt(max(0.0, (REACH * 0.95) ** 2 - n * n)))
        wanted = root + np.array([flat[0], flat[1], depth])
        w = float(np.clip(paw.weight, 0, 1))
        w = w * w * (3 - 2 * w)
        arc = math.sin(math.pi * w)
        target = resting + (wanted - resting) * w + np.array([0, 0.5 * arc, 0.25 * arc])
        joints = self._reach(root, rest, chest, target, side, paw.elbow * w, 0.17 * w + 0.09)
        base = chest
        for i in range(3):
            direction = base[:3, :3] @ (rest[i + 1] - rest[i])
            m = np.eye(4)
            m[:3, :3] = between(direction, joints[i + 1] - joints[i]) @ base[:3, :3]
            m[:3, 3] = apply(base, rest[i]) - m[:3, :3] @ rest[i]
            skin[arm[i]] = base = m
        fore = joints[3] - joints[2]
        fore = fore / np.linalg.norm(fore)
        up = float(np.clip((fore[1] + 0.25) / 0.9, 0, 1)) * w
        toes = fore * (0.35 + 0.65 * up) + np.array([0, -0.1, 0.9]) * (1 - up)
        sole = np.array([0, -1.0, 0.0]) * (1 - up) + np.array([0, -0.15, 1.0]) * up
        f = rot((0, 0, 1), -paw.lean * up * 0.8) @ frame(toes, sole) @ rx(72.0 * paw.curl * (0.35 + 0.65 * up))
        m = np.eye(4)
        m[:3, :3] = f
        m[:3, 3] = apply(base, rest[3]) - f @ rest[3]
        skin[arm[3]] = skin[arm[3] + 1] = m

    @staticmethod
    def _reach(root, rest, chest, target, side, elbow=0.0, out=0.26) -> np.ndarray:
        """FABRIK over shoulder, elbow and wrist; the shoulder blade may only swing a limited amount."""
        lengths = np.linalg.norm(np.diff(rest, axis=0), axis=1)
        pts = np.array([apply(chest, p) for p in rest])
        natural = pts[1] - pts[0]
        natural = natural / np.linalg.norm(natural)
        pts[2] = pts[2] + np.array([side * (out + 0.35 * elbow), -0.36 + 0.95 * elbow, 0.06])  # elbows prefer to stay low and outside
        delta = target - root
        d, total = float(np.linalg.norm(delta)), float(lengths.sum()) * 0.985
        if d > total:
            target = root + delta * (total / d)
        limit = math.radians(34)
        for _ in range(8):
            pts[3] = target
            for i in (2, 1, 0):
                v = pts[i] - pts[i + 1]
                pts[i] = pts[i + 1] + v * (lengths[i] / max(1e-6, float(np.linalg.norm(v))))
            pts[0] = root
            for i in (0, 1, 2):
                v = pts[i + 1] - pts[i]
                v = v / max(1e-6, float(np.linalg.norm(v)))
                if i == 0 and math.acos(float(np.clip(np.dot(v, natural), -1, 1))) > limit:
                    axis = np.cross(natural, v)
                    v = rot(axis, limit) @ natural if np.linalg.norm(axis) > 1e-6 else natural
                pts[i + 1] = pts[i] + v * lengths[i]
        return pts


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
