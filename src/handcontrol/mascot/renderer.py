"""Offscreen OpenGL 3.3 renderer: skinned cat with shell fur, shader eyes and whiskers -> QImage with alpha.

Draws into a framebuffer at twice the output size and lets the GPU average it down, so single hairs stay clean on any
desktop background. GUI thread only. Raises RendererError when the machine has no usable OpenGL.
"""
from __future__ import annotations

import ctypes
import logging
import math
from pathlib import Path
from typing import Optional

import numpy as np
from PySide6.QtCore import QSize
from PySide6.QtGui import (
    QGuiApplication, QImage, QMatrix4x4, QOffscreenSurface, QOpenGLContext, QSurfaceFormat, QVector2D, QVector3D,
)
from PySide6.QtOpenGL import (
    QOpenGLBuffer, QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat, QOpenGLFunctions_3_3_Core, QOpenGLShader,
    QOpenGLShaderProgram, QOpenGLTexture, QOpenGLVersionFunctionsFactory, QOpenGLVersionProfile, QOpenGLVertexArrayObject,
)

from shiboken6 import VoidPtr

from handcontrol.mascot.rig import (
    ARMS, BONES, EAR_L, EAR_R, EYE_CENTERS, HEAD, JAW, NECK, TAIL, CatRig, MascotPose,
)

log = logging.getLogger(__name__)

SHELLS = 17
STRAND_CELLS, STRAND_TEXELS = 16, 96
PICTURE_BOTTOM = 3.7                         # everything of the resting cat below this height is outside the picture
SUPERSAMPLE = 2
EYE_RADIUS = 0.215
GL_FLOAT, GL_UINT, GL_TRIANGLES, GL_DEPTH_TEST, GL_CULL_FACE = 0x1406, 0x1405, 0x0004, 0x0B71, 0x0B44
GL_COLOR_DEPTH, GL_COLOR, GL_LINEAR = 0x4100, 0x4000, 0x2601
GL_READ_FRAMEBUFFER, GL_BGRA, GL_UNSIGNED_INT_8888_REV = 0x8CA8, 0x80E1, 0x8367

SKIN_GLSL = """
#version 330 core
uniform vec4 uBones[%d];
uniform mat4 uViewProj;
mat4x3 bone(int i) {
    return transpose(mat3x4(uBones[i * 3], uBones[i * 3 + 1], uBones[i * 3 + 2]));
}
""" % (BONES * 3)

FUR_VS = SKIN_GLSL + """
layout(location=0) in vec3 aPos;
layout(location=1) in vec3 aNormal;
layout(location=2) in vec2 aUv;
layout(location=3) in vec4 aJoints;
layout(location=4) in vec4 aWeights;
layout(location=5) in vec3 aExtra;
layout(location=6) in vec3 aComb;
uniform float uShells;
uniform float uFirst;
uniform float uSmile;
out vec3 vRest; out vec3 vNormal; out vec3 vWorld; out vec2 vUv; out float vH; out float vLen; out float vEar; out float vJaw;
void main() {
    float h = 1.0 - (float(gl_InstanceID) + uFirst) / uShells;      // outside in: covered layers fail the depth test early
    vec3 rest = aPos, n = normalize(aNormal);
    // Smiling pulls the mouth corners up and out.
    float corner = exp(-pow((abs(rest.x) - 0.27) / 0.17, 2.0) - pow((rest.y - 3.55) / 0.15, 2.0)) * smoothstep(1.1, 1.5, rest.z);
    rest += vec3(sign(rest.x) * 0.06, 0.12, -0.02) * corner * uSmile;
    vec3 comb = aComb - n * dot(aComb, n);
    vec3 hair = rest + (n * h * 0.80 + comb * h * h * 0.95 + vec3(0.0, -0.16, 0.0) * h * h) * aExtra.y;
    mat4x3 m = bone(int(aJoints.x)) * aWeights.x + bone(int(aJoints.y)) * aWeights.y
             + bone(int(aJoints.z)) * aWeights.z + bone(int(aJoints.w)) * aWeights.w;
    if (aExtra.x > 0.0) m = m * (1.0 - aExtra.x) + bone(%d) * aExtra.x;
    if (aExtra.z < 0.0) m = m * (1.0 + aExtra.z) + bone(%d) * -aExtra.z;
    if (aExtra.z > 0.0) m = m * (1.0 - aExtra.z) + bone(%d) * aExtra.z;
    vWorld = m * vec4(hair, 1.0);
    vNormal = mat3(m) * n;
    vRest = aPos; vUv = aUv; vH = h; vLen = aExtra.y; vEar = abs(aExtra.z); vJaw = aExtra.x;
    gl_Position = uViewProj * vec4(vWorld, 1.0);
}
""" % (JAW, EAR_L, EAR_R)

LIGHT_GLSL = """
uniform vec3 uEye;
uniform vec3 uHeadPos;
const vec3 KEY = vec3(-0.46, 0.66, 0.60);
vec3 shade(vec3 albedo, vec3 n, vec3 world, float wrap, float ao) {
    vec3 v = normalize(uEye - world);
    float key = max(0.0, (dot(n, normalize(KEY)) + wrap) / (1.0 + wrap));
    float fill = max(0.0, dot(n, normalize(vec3(0.75, 0.15, 0.55))) * 0.5 + 0.5);
    float sky = n.y * 0.5 + 0.5;
    float rim = pow(1.0 - max(0.0, dot(n, v)), 2.6) * smoothstep(-0.3, 0.7, n.y + 0.35);
    vec3 light = vec3(1.16, 1.07, 0.96) * key * 0.92 + vec3(0.50, 0.55, 0.66) * fill * 0.40
               + mix(vec3(0.30, 0.25, 0.23), vec3(0.46, 0.49, 0.55), sky) * 0.55;
    return albedo * light * ao + (albedo * 0.55 + 0.10) * rim * 0.62 * ao;
}
// Soft shadow of the head on the chest.
float headShadow(vec3 world) {
    vec3 d = uHeadPos - world, l = normalize(KEY);
    float along = dot(d, l);
    float miss = length(d - l * along);
    return 1.0 - 0.45 * smoothstep(1.15, 0.45, miss) * smoothstep(0.55, 1.2, along);
}
vec3 toSrgb(vec3 c) { return pow(clamp(c, 0.0, 1.0), vec3(1.0 / 2.2)); }
vec3 tone(vec3 c) { c *= 1.12; return c * (1.0 + c * 0.12) / (1.0 + c * 0.42); }
"""

FUR_FS = """
#version 330 core
in vec3 vRest; in vec3 vNormal; in vec3 vWorld; in vec2 vUv; in float vH; in float vLen; in float vEar; in float vJaw;
uniform sampler2D uAlbedo;
uniform sampler3D uStrands;          // r: strand height, g: distance to the strand, b: random, a: clump noise
uniform float uJaw;
out vec4 fragColor;
""" + LIGHT_GLSL + """
void main() {
    vec3 texel = texture(uAlbedo, vUv).rgb;
    float black = 1.0 - smoothstep(0.10, 0.24, max(texel.r, max(texel.g, texel.b)));
    vec3 n = normalize(vNormal);
    if (!gl_FrontFacing && vH == 0.0) n = -n;
    // Skin that spans the open mouth becomes its inside: dark above, tongue below.
    float gap = smoothstep(0.04, 0.12, vJaw) * smoothstep(0.999, 0.985, vJaw) * smoothstep(1.40, 1.48, vRest.z) * smoothstep(0.04, 0.16, uJaw);
    if (vH > 0.0) {
        if (gap > 0.3) discard;
        if (vLen < 0.006 || black > 0.5) discard;
        float density = mix(46.0, 62.0, smoothstep(0.08, 0.02, vLen));
        vec3 s = texture(uStrands, vRest * density / CELLS).rgb;
        float clump = texture(uStrands, vRest * 0.41).a;
        float height = s.x * (0.62 + 0.55 * clump);
        float radius = 0.62 * (1.0 - vH / max(height, 0.05));
        if (s.y * 1.3 > radius) discard;
        texel *= 0.93 + 0.14 * s.z;
    }
    vec3 albedo = pow(texel, vec3(2.2));
    float white = smoothstep(0.40, 0.68, min(texel.r, min(texel.g, texel.b)));
    albedo = mix(albedo * vec3(1.16, 1.02, 0.86), min(albedo * vec3(1.50, 1.45, 1.36), vec3(0.95)), white);
    float nose = smoothstep(1.25, 0.8, length((vRest - vec3(0.0, 3.735, 1.93)) / vec3(0.105, 0.075, 0.12)));
    albedo = mix(albedo, vec3(0.60, 0.21, 0.20), nose * 0.75);
    // Inside of the mouth and the sockets.
    float mouth = black * step(vRest.y, 3.72) * step(1.0, vRest.z);
    vec3 gum = mix(vec3(0.30, 0.05, 0.06), vec3(0.62, 0.19, 0.20), smoothstep(0.35, 1.0, vJaw));
    albedo = mix(albedo, gum * (0.25 + 0.75 * uJaw), mouth);
    albedo = mix(albedo, vec3(0.012, 0.009, 0.008), black * (1.0 - mouth));
    vec3 tongue = mix(vec3(0.07, 0.012, 0.014), vec3(0.62, 0.20, 0.22), smoothstep(0.42, 0.72, vJaw) * smoothstep(0.26, 0.12, abs(vRest.x)));
    albedo = mix(albedo, tongue, gap);
    float ao = vLen > 0.006 ? mix(mix(0.62, 0.80, white), 1.05, pow(vH, 0.8)) : 1.0;
    ao = mix(ao, 1.0, gap);
    ao *= headShadow(vWorld);
    vec3 c = shade(albedo, n, vWorld, 0.45, ao);
    if (nose > 0.3) { vec3 hv = normalize(normalize(KEY) + normalize(uEye - vWorld)); c += pow(max(0.0, dot(n, hv)), 40.0) * 0.30 * nose; }
    fragColor = vec4(toSrgb(tone(c)), 1.0);
}
""".replace("CELLS", f"{STRAND_CELLS}.0")

EYE_VS = """
#version 330 core
layout(location=0) in vec3 aPos;
uniform mat4 uViewProj; uniform mat4 uHead; uniform vec3 uCenter; uniform float uRadius;
out vec3 vDir; out vec3 vWorld; out vec3 vNormal;
void main() {
    vDir = aPos;
    vWorld = (uHead * vec4(uCenter + aPos * uRadius, 1.0)).xyz;
    vNormal = mat3(uHead) * aPos;
    gl_Position = uViewProj * vec4(vWorld, 1.0);
}
"""

EYE_FS = """
#version 330 core
in vec3 vDir; in vec3 vWorld; in vec3 vNormal;
uniform vec2 uGaze; uniform float uBlink; uniform float uSide; uniform float uPupil; uniform float uSmile;
out vec4 fragColor;
""" + LIGHT_GLSL + """
float hash1(float x) { return fract(sin(x * 127.1) * 43758.5453); }
float vnoise(float x) { float i = floor(x), f = fract(x); f = f * f * (3.0 - 2.0 * f); return mix(hash1(i), hash1(i + 1.0), f); }
void main() {
    vec3 n = normalize(vNormal), d = normalize(vDir), v = normalize(uEye - vWorld);
    // Almond opening: the inner corner sits lower. x runs from the nose outwards.
    float x = d.x * uSide / 0.80 + 0.05;
    float slant = 0.16 * x - 0.03;
    float shape = sqrt(max(0.0, 1.0 - x * x));
    float top = slant + shape * (0.74 - 0.04 * x);
    float bottom = slant * 0.6 - shape * (0.66 - 0.32 * uSmile);
    float closeLine = slant + shape * mix(-0.26, 0.16, uSmile);
    top = mix(top, closeLine - 0.03, uBlink);
    bottom = mix(bottom, closeLine - 0.005, uBlink * 0.95);
    float open = min(top - d.y, d.y - bottom);
    vec2 g = vec2(uGaze.x, uGaze.y);
    vec3 look = normalize(vec3(g.x * 0.42, g.y * 0.34, 1.0));
    vec3 right = normalize(cross(vec3(0, 1, 0), look)), up = cross(look, right);
    vec2 p = vec2(dot(d, right), dot(d, up)) / 0.80;
    float r = length(p), a = atan(p.y, p.x);
    float fibers = vnoise(a * 24.0 + r * 3.0) * 0.6 + vnoise(a * 61.0) * 0.4;
    vec3 iris = mix(vec3(0.62, 0.43, 0.07), vec3(0.33, 0.42, 0.10), smoothstep(0.28, 0.85, r + 0.12 * fibers));
    iris *= 0.62 + 0.75 * fibers * smoothstep(0.1, 0.5, r);
    iris *= 1.0 - 0.80 * smoothstep(0.74, 0.97, r);
    float pw = mix(0.085, 0.40, uPupil), ph = mix(0.66, 0.60, uPupil);
    float pupil = 1.0 - smoothstep(0.90, 1.06, length(p / vec2(pw, ph)));
    vec3 c = mix(iris, vec3(0.004), pupil);
    c = mix(c, vec3(0.10, 0.07, 0.05), smoothstep(0.96, 1.02, r));
    float lit = 0.55 + 0.75 * max(0.0, dot(n, normalize(KEY)));
    lit *= mix(0.30, 1.0, smoothstep(0.0, 0.34, top - d.y));            // the lid throws a shadow
    c *= lit * 1.35;
    vec3 bulge = normalize(n + 0.18 * (mat3(1.0) * n));
    vec3 hv = normalize(normalize(KEY) + v);
    c += pow(max(0.0, dot(bulge, hv)), 220.0) * 1.6;
    c += pow(max(0.0, dot(bulge, normalize(normalize(vec3(0.65, 0.2, 0.7)) + v))), 70.0) * 0.22 * vec3(0.8, 0.9, 1.0);
    c += pow(1.0 - max(0.0, dot(n, v)), 4.0) * vec3(0.10, 0.12, 0.15);
    // Lids: dark rim, then short fur.
    float upper = step(0.0, d.y - closeLine);
    vec3 fur = mix(vec3(0.52, 0.30, 0.17), vec3(0.40, 0.145, 0.050), upper);
    fur *= 0.82 + 0.36 * vnoise(d.x * 46.0 - d.y * 16.0);
    fur = shade(fur * 0.60, n, vWorld, 0.4, 0.85);
    vec3 rim = vec3(0.022, 0.014, 0.012);
    float edge = smoothstep(0.13, 0.06, -open);
    vec3 lid = mix(fur, rim, edge);
    float isLid = smoothstep(0.012, -0.012, open);
    c = mix(c, lid, isLid);
    fragColor = vec4(toSrgb(tone(c)), 1.0);
}
"""

WHISKER_VS = """
#version 330 core
layout(location=0) in vec3 aPos;
layout(location=1) in vec3 aTangent;
layout(location=2) in vec2 aSide;
uniform mat4 uViewProj; uniform mat4 uHead; uniform vec3 uEye; uniform float uWidth;
out float vT;
void main() {
    vec3 w = (uHead * vec4(aPos, 1.0)).xyz;
    vec3 side = normalize(cross(mat3(uHead) * aTangent, uEye - w));
    vT = aSide.y;
    gl_Position = uViewProj * vec4(w + side * aSide.x * uWidth * (1.0 - 0.75 * aSide.y), 1.0);
}
"""

WHISKER_FS = """
#version 330 core
in float vT;
out vec4 fragColor;
void main() { fragColor = vec4(mix(vec3(0.72, 0.68, 0.64), vec3(0.92), vT), 1.0); }
"""


class RendererError(RuntimeError):
    """OpenGL or the cat model is not usable on this machine."""


def asset_dir() -> Path:
    from handcontrol.tracking import project_root
    return project_root() / "assets" / "mascot"


def _sphere(rows: int = 28, cols: int = 36) -> tuple[np.ndarray, np.ndarray]:
    """Front-facing part of a unit sphere (pole towards +Z)."""
    theta = np.linspace(0, math.radians(115), rows)
    phi = np.linspace(0, 2 * math.pi, cols + 1)
    tt, pp = np.meshgrid(theta, phi, indexing="ij")
    pos = np.stack((np.sin(tt) * np.cos(pp), np.sin(tt) * np.sin(pp), np.cos(tt)), -1).reshape(-1, 3)
    quad = np.array([[r * (cols + 1) + c, (r + 1) * (cols + 1) + c, r * (cols + 1) + c + 1, (r + 1) * (cols + 1) + c + 1]
                     for r in range(rows - 1) for c in range(cols)])
    return pos, np.concatenate((quad[:, [0, 1, 3]], quad[:, [0, 3, 2]]))


def _strand_volume() -> np.ndarray:
    """Tiling 3D texture (n, n, n, 4): nearest hair of a jittered grid, plus smooth low-frequency noise."""
    rng = np.random.default_rng(3)
    cells, n = STRAND_CELLS, STRAND_TEXELS
    jitter, value = rng.uniform(0.2, 0.8, (cells, cells, cells, 3)), rng.random((cells, cells, cells, 2))
    axis = (np.arange(n) + 0.5) * cells / n
    p = np.stack(np.meshgrid(axis, axis, axis, indexing="ij"), -1)
    base = np.floor(p).astype(int)
    best = np.full((n, n, n), 9.0)
    picked = np.zeros((n, n, n, 2))
    for off in np.ndindex(3, 3, 3):
        c = base + np.array(off) - 1
        w = c % cells
        d = np.linalg.norm(p - c - jitter[w[..., 0], w[..., 1], w[..., 2]], axis=-1)
        near = d < best
        best = np.where(near, d, best)
        picked[near] = value[w[..., 0], w[..., 1], w[..., 2]][near]
    out = np.empty((n, n, n, 4), np.uint8)
    out[..., 0] = (0.45 + 0.55 * picked[..., 0]) * 255
    out[..., 1] = np.clip(best / 1.3, 0, 1) * 255
    out[..., 2] = picked[..., 1] * 255
    coarse = rng.random((8, 8, 8))
    for ax in range(3):                                       # smooth periodic upsampling
        m = coarse.shape[ax]
        x = (np.arange(n) + 0.5) * m / n - 0.5
        i, f = np.floor(x).astype(int), x - np.floor(x)
        f = (f * f * (3 - 2 * f)).reshape([-1 if k == ax else 1 for k in range(3)])
        coarse = np.take(coarse, i % m, ax) * (1 - f) + np.take(coarse, (i + 1) % m, ax) * f
    out[..., 3] = coarse * 255
    return np.ascontiguousarray(out)


def _whiskers() -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(7)
    rows, tris = [], []

    def strand(root, direction, length, droop, steps=10):
        pts = np.array([root + direction * length * u + np.array([0, -droop * u * u, -0.18 * length * u * u])
                        for u in np.linspace(0, 1, steps)])
        tan = np.gradient(pts, axis=0)
        base = len(rows)
        for i, (p, t) in enumerate(zip(pts, tan)):
            for s in (-1.0, 1.0):
                rows.append([*p, *t, s, i / (steps - 1)])
        for i in range(steps - 1):
            a = base + 2 * i
            tris.extend(([a, a + 1, a + 2], [a + 1, a + 3, a + 2]))

    for side in (-1, 1):
        for row in range(3):
            for k in range(4):
                root = np.array([side * (0.15 + 0.045 * k), 3.70 - 0.05 * row, 1.865 - 0.045 * k - 0.01 * row])
                d = np.array([side * (0.95 + 0.04 * rng.normal()), 0.34 - 0.27 * row + 0.03 * rng.normal(), 0.22])
                strand(root, d / np.linalg.norm(d), 0.62 + 0.13 * k + 0.05 * rng.normal() - 0.08 * row, 0.20 + 0.05 * rng.random())
        for k in range(2):
            root = np.array([side * (0.20 + 0.05 * k), 4.24 + 0.01 * k, 1.60])
            d = np.array([side * (0.35 + 0.22 * k), 0.95, 0.30])
            strand(root, d / np.linalg.norm(d), 0.30, 0.04)
    return np.array(rows, np.float32), np.array(tris)


class _Mesh:
    """Interleaved float vertices + indices in a vertex array object."""

    def __init__(self, gl, vertices: np.ndarray, indices: np.ndarray, layout: tuple[int, ...]) -> None:
        self.vao = QOpenGLVertexArrayObject()
        self.vao.create()
        self.vao.bind()
        self.vbo = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        self.ibo = QOpenGLBuffer(QOpenGLBuffer.Type.IndexBuffer)
        for buf, data in ((self.vbo, vertices.astype(np.float32)), (self.ibo, indices.astype(np.uint32))):
            buf.create()
            buf.bind()
            raw = data.tobytes()
            buf.allocate(raw, len(raw))
        self.count = int(indices.size)
        stride, offset = 4 * sum(layout), 0
        self._attr = []
        for loc, size in enumerate(layout):
            self._attr.append((loc, offset, size, stride))
            offset += 4 * size
        self.vao.release()

    def setup(self, program: QOpenGLShaderProgram) -> None:
        self.vao.bind()
        self.vbo.bind()
        for loc, offset, size, stride in self._attr:
            program.enableAttributeArray(loc)
            program.setAttributeBuffer(loc, GL_FLOAT, offset, size, stride)
        self.ibo.bind()
        self.vao.release()


def visible_triangles(rig: CatRig, data) -> tuple[np.ndarray, np.ndarray]:
    """(skin, coat) triangles: drop what the picture never shows, and fur where there is none or only a hidden back."""
    skin = rig.solve(MascotPose(), 0.0)
    joints, weights = data["joints"].astype(int), data["weights"].astype(float) / 255.0
    m = (skin[joints] * weights[..., None, None]).sum(1)
    world = np.einsum("nij,nj->ni", m[:, :3, :3], data["pos"]) + m[:, :3, 3]
    normal = np.einsum("nij,nj->ni", m[:, :3, :3], data["nrm"])
    moving = np.isin(joints, [NECK, HEAD, *ARMS[0], *ARMS[1], *TAIL])
    moves = (weights * moving).sum(1) > 0.35
    tri = data["tri"].astype(int)
    tri = tri[((world[:, 1] > PICTURE_BOTTOM) | moves)[tri].any(1)]
    furry = (data["extra"][:, 1] > 0.006) & (moves | (normal[:, 2] > -0.45))
    return tri, tri[furry[tri].any(1)]


def compact(vertices: np.ndarray, tri: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    used, inverse = np.unique(tri, return_inverse=True)
    return vertices[used], inverse.reshape(-1, 3)


class CatRenderer:
    def __init__(self, directory: Optional[Path] = None) -> None:
        directory = directory or asset_dir()
        try:
            data = np.load(directory / "cat.npz")
            albedo = QImage(str(directory / "cat_albedo.jpg"))
        except (OSError, ValueError) as exc:
            raise RendererError(f"Kedi modeli okunamadı: {exc}") from exc
        if albedo.isNull():
            raise RendererError("Kedi dokusu okunamadı")
        self.rig = CatRig(data["heads"], data["parents"])
        self._fbo: Optional[QOpenGLFramebufferObject] = None
        self._small: Optional[QOpenGLFramebufferObject] = None
        self._pending: Optional[tuple[int, int]] = None
        self._closed = False
        fmt = QSurfaceFormat()
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
        fmt.setDepthBufferSize(24)
        if QGuiApplication.instance() is None:
            raise RendererError("Qt uygulaması yok")
        self._ctx = QOpenGLContext()
        self._ctx.setFormat(fmt)
        if not self._ctx.create():
            raise RendererError("OpenGL bağlamı oluşturulamadı")
        self._surface = QOffscreenSurface()
        self._surface.setFormat(self._ctx.format())
        self._surface.create()
        if not self._ctx.makeCurrent(self._surface):
            raise RendererError("OpenGL etkinleştirilemedi")
        try:
            profile = QOpenGLVersionProfile()
            profile.setVersion(3, 3)
            profile.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
            self._gl: QOpenGLFunctions_3_3_Core = QOpenGLVersionFunctionsFactory.get(profile, self._ctx)
            if self._gl is None:
                raise RendererError("OpenGL 3.3 yok")
            self._gl.initializeOpenGLFunctions()
            self._fur = self._program(FUR_VS, FUR_FS)
            self._eye = self._program(EYE_VS, EYE_FS)
            self._hair = self._program(WHISKER_VS, WHISKER_FS)
            vertices = np.concatenate([data["pos"], data["nrm"], data["uv"], data["joints"].astype(np.float32),
                                       data["weights"].astype(np.float32) / 255.0, data["extra"], data["comb"]], axis=1)
            skin_tris, fur_tris = visible_triangles(self.rig, data)
            layout = (3, 3, 2, 4, 4, 3, 3)
            self._body = _Mesh(self._gl, *compact(vertices, skin_tris), layout)
            self._coat = _Mesh(self._gl, *compact(vertices, fur_tris), layout)
            for mesh in (self._body, self._coat):
                mesh.setup(self._fur)
            pos, tri = _sphere()
            self._ball = _Mesh(self._gl, pos, tri, (3,))
            self._ball.setup(self._eye)
            rows, tris = _whiskers()
            self._whisker = _Mesh(self._gl, rows, tris, (3, 3, 2))
            self._whisker.setup(self._hair)
            self._albedo = QOpenGLTexture(albedo)
            self._albedo.setMinificationFilter(QOpenGLTexture.Filter.LinearMipMapLinear)
            self._albedo.setMagnificationFilter(QOpenGLTexture.Filter.Linear)
            self._albedo.setWrapMode(QOpenGLTexture.WrapMode.Repeat)
            self._strands = QOpenGLTexture(QOpenGLTexture.Target.Target3D)
            self._strands.setFormat(QOpenGLTexture.TextureFormat.RGBA8_UNorm)
            self._strands.setSize(STRAND_TEXELS, STRAND_TEXELS, STRAND_TEXELS)
            self._strands.allocateStorage()
            self._strands.setData(QOpenGLTexture.PixelFormat.RGBA, QOpenGLTexture.PixelType.UInt8, _strand_volume().tobytes())
            self._strands.setMinMagFilters(QOpenGLTexture.Filter.Linear, QOpenGLTexture.Filter.Linear)
            self._strands.setWrapMode(QOpenGLTexture.WrapMode.Repeat)
            self._pack, self._pack_spare = (QOpenGLBuffer(QOpenGLBuffer.Type.PixelPackBuffer) for _ in range(2))
            for b in (self._pack, self._pack_spare):
                b.create()
                b.setUsagePattern(QOpenGLBuffer.UsagePattern.StreamRead)
        finally:
            self._ctx.doneCurrent()

    def _program(self, vs: str, fs: str) -> QOpenGLShaderProgram:
        p = QOpenGLShaderProgram()
        for kind, src in ((QOpenGLShader.ShaderTypeBit.Vertex, vs), (QOpenGLShader.ShaderTypeBit.Fragment, fs)):
            if not p.addShaderFromSourceCode(kind, src.strip()):
                raise RendererError(f"Shader derlenemedi: {p.log()}")
        if not p.link():
            raise RendererError(f"Shader bağlanamadı: {p.log()}")
        return p

    def _targets(self, w: int, h: int) -> None:
        if self._small is not None and self._small.size() == QSize(w, h):
            return
        big = QOpenGLFramebufferObjectFormat()
        big.setAttachment(QOpenGLFramebufferObject.Attachment.Depth)
        self._fbo = QOpenGLFramebufferObject(QSize(w * SUPERSAMPLE, h * SUPERSAMPLE), big)
        self._small = QOpenGLFramebufferObject(QSize(w, h), QOpenGLFramebufferObjectFormat())

    def render(self, pose: MascotPose, t: float, w: int, h: int, *, pupil: float = 0.35, wait: bool = False) -> QImage:
        """Draw one frame. Returns the previous frame (null right after a start or resize): the graphics card copies
        its pixels in the background, because waiting for them here would hold the GIL and slow hand tracking down.
        `wait=True` returns this frame instead (tests, screenshots)."""
        if self._closed or not self._ctx.makeCurrent(self._surface):
            return QImage()
        gl = self._gl
        try:
            self._targets(w, h)
            skin = self.rig.solve(pose, t)
            head = skin[HEAD]
            self._fbo.bind()
            gl.glViewport(0, 0, w * SUPERSAMPLE, h * SUPERSAMPLE)
            gl.glClearColor(0.0, 0.0, 0.0, 0.0)
            gl.glEnable(GL_DEPTH_TEST)
            gl.glDisable(GL_CULL_FACE)
            gl.glClear(GL_COLOR_DEPTH)
            eye = QVector3D(0.0, 7.1, 17.0)
            vp = QMatrix4x4()
            vp.perspective(16.4, w / h, 1.0, 60.0)
            vp.lookAt(eye, QVector3D(0.0, 6.72, 0.0), QVector3D(0, 1, 0))
            head_q = QMatrix4x4(*[float(x) for x in head.ravel()])
            center = head[:3, :3] @ np.array([0.0, 4.0, 1.1]) + head[:3, 3]
            head_pos = QVector3D(*[float(x) for x in center])

            p = self._fur
            p.bind()
            p.setUniformValue(p.uniformLocation("uViewProj"), vp)
            p.setUniformValueArray(p.uniformLocation("uBones"), skin[:, :3, :].astype(np.float32).ravel().tolist(), BONES * 3, 4)
            self._common(p, eye, head_pos)
            gl.glUniform1f(p.uniformLocation("uShells"), float(SHELLS))
            gl.glUniform1f(p.uniformLocation("uSmile"), float(pose.smile))
            gl.glUniform1f(p.uniformLocation("uJaw"), float(min(1.0, pose.jaw)))
            self._albedo.bind(0)
            gl.glUniform1i(p.uniformLocation("uAlbedo"), 0)
            self._strands.bind(1)
            gl.glUniform1i(p.uniformLocation("uStrands"), 1)
            first = p.uniformLocation("uFirst")
            gl.glUniform1f(first, 0.0)
            gl.glEnable(GL_CULL_FACE)
            self._coat.vao.bind()
            gl.glDrawElementsInstanced(GL_TRIANGLES, self._coat.count, GL_UINT, VoidPtr(0), SHELLS)
            self._coat.vao.release()
            gl.glDisable(GL_CULL_FACE)
            gl.glUniform1f(first, float(SHELLS))
            self._body.vao.bind()
            gl.glDrawElements(GL_TRIANGLES, self._body.count, GL_UINT, VoidPtr(0))
            self._body.vao.release()
            p.release()

            p = self._eye
            p.bind()
            p.setUniformValue(p.uniformLocation("uViewProj"), vp)
            p.setUniformValue(p.uniformLocation("uHead"), head_q)
            self._common(p, eye, head_pos)
            gl.glUniform1f(p.uniformLocation("uRadius"), EYE_RADIUS)
            gl.glUniform1f(p.uniformLocation("uPupil"), float(pupil))
            gl.glUniform1f(p.uniformLocation("uSmile"), float(pose.smile))
            p.setUniformValue(p.uniformLocation("uGaze"), QVector2D(*pose.gaze))
            self._ball.vao.bind()
            for s in (0, 1):
                p.setUniformValue(p.uniformLocation("uCenter"), QVector3D(*[float(v) for v in EYE_CENTERS[s]]))
                gl.glUniform1f(p.uniformLocation("uSide"), -1.0 if s == 0 else 1.0)
                gl.glUniform1f(p.uniformLocation("uBlink"), float(np.clip(pose.blink[s], 0, 1)))
                gl.glDrawElements(GL_TRIANGLES, self._ball.count, GL_UINT, VoidPtr(0))
            self._ball.vao.release()
            p.release()

            p = self._hair
            p.bind()
            p.setUniformValue(p.uniformLocation("uViewProj"), vp)
            p.setUniformValue(p.uniformLocation("uHead"), head_q)
            p.setUniformValue(p.uniformLocation("uEye"), eye)
            gl.glUniform1f(p.uniformLocation("uWidth"), 0.0062)
            self._whisker.vao.bind()
            gl.glDrawElements(GL_TRIANGLES, self._whisker.count, GL_UINT, VoidPtr(0))
            self._whisker.vao.release()
            p.release()
            self._fbo.release()
            QOpenGLFramebufferObject.blitFramebuffer(
                self._small, _rect(w, h), self._fbo, _rect(w * SUPERSAMPLE, h * SUPERSAMPLE), GL_COLOR, GL_LINEAR)
            if wait:
                return self._small.toImage().convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
            return self._swap_pixels(w, h)
        finally:
            self._ctx.doneCurrent()

    def _swap_pixels(self, w: int, h: int) -> QImage:
        size = w * h * 4
        ready, self._pack = self._pack, self._pack_spare
        self._pack_spare = ready
        gl = self._gl
        gl.glBindFramebuffer(GL_READ_FRAMEBUFFER, self._small.handle())
        self._pack.bind()
        if self._pack.size() != size:
            self._pack.allocate(size)
        gl.glReadPixels(0, 0, w, h, GL_BGRA, GL_UNSIGNED_INT_8888_REV, VoidPtr(0))
        self._pack.release()
        gl.glBindFramebuffer(GL_READ_FRAMEBUFFER, 0)
        if self._pending != (w, h):
            self._pending = (w, h)
            return QImage()
        ready.bind()
        address = ready.map(QOpenGLBuffer.Access.ReadOnly)
        try:
            if address is None:
                return QImage()
            raw = np.ctypeslib.as_array(ctypes.cast(int(address), ctypes.POINTER(ctypes.c_uint32)), (h, w))
            rows = raw[::-1].tobytes()
        finally:
            ready.unmap()
            ready.release()
        return QImage(rows, w, h, w * 4, QImage.Format.Format_ARGB32_Premultiplied).copy()

    def _common(self, p: QOpenGLShaderProgram, eye: QVector3D, head_pos: QVector3D) -> None:
        p.setUniformValue(p.uniformLocation("uEye"), eye)
        p.setUniformValue(p.uniformLocation("uHeadPos"), head_pos)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._ctx.makeCurrent(self._surface):
            self._albedo.destroy()
            self._strands.destroy()
            for m in (self._body, self._coat, self._ball, self._whisker):
                m.vao.destroy()
                m.vbo.destroy()
                m.ibo.destroy()
            self._pack.destroy()
            self._pack_spare.destroy()
            self._fbo = self._small = None
            for p in (self._fur, self._eye, self._hair):
                p.removeAllShaders()
            self._ctx.doneCurrent()
        self._surface.destroy()


def _rect(w: int, h: int):
    from PySide6.QtCore import QRect
    return QRect(0, 0, w, h)


__all__ = ["CatRenderer", "RendererError", "asset_dir"]
