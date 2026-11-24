"""Offscreen OpenGL 3.3 renderer: the skinned furry cat with shader eyes -> QImage with alpha.

Draws into a framebuffer at twice the output size and lets the GPU average it down, so single hairs stay clean on any
desktop background. GUI thread only. Raises RendererError when the machine has no usable OpenGL.
"""
from __future__ import annotations

import ctypes
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
    QOpenGLShaderProgram, QOpenGLVersionFunctionsFactory, QOpenGLVersionProfile, QOpenGLVertexArrayObject,
)

from shiboken6 import VoidPtr

from handcontrol.mascot.rig import BONES, EYE_CENTERS, HEAD, CatRig, MascotPose

SUPERSAMPLE = 2
EYE_RADIUS = 0.305
GL_FLOAT, GL_BYTE, GL_UBYTE, GL_UINT, GL_TRIANGLES, GL_DEPTH_TEST, GL_CULL_FACE = 0x1406, 0x1400, 0x1401, 0x1405, 0x0004, 0x0B71, 0x0B44
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
layout(location=1) in vec3 aClosed;          // eyelids: position when the eye is shut
layout(location=2) in vec4 aNormal;          // w: +1 upper lid, -1 lower lid, 0 everything else
layout(location=3) in vec4 aColor;           // a: gloss
layout(location=4) in vec4 aJoints;
layout(location=5) in vec4 aWeights;
uniform float uSmile;
uniform vec2 uBlink;
uniform float uFrown;
uniform vec3 uEyes[2];
out vec3 vNormal; out vec3 vWorld; out vec4 vColor;
void main() {
    vec3 rest = aPos, n = aNormal.xyz;
    if (aNormal.w != 0.0) {                  // the lids turn around the eyeball
        int s = aPos.x < 0.0 ? 0 : 1;
        float shut = aNormal.w > 0.0 ? max(uBlink[s], 0.34 * uFrown) : max(uBlink[s], 0.42 * uSmile);
        vec3 a = aPos - uEyes[s], b = aClosed - uEyes[s];
        rest = uEyes[s] + normalize(mix(normalize(a), normalize(b), shut)) * mix(length(a), length(b), shut);
        n = normalize(rest - uEyes[s]);
    }
    vec2 lip = (vec2(abs(rest.x), rest.y) - vec2(0.27, 1.57)) / vec2(0.15, 0.13);      // smiling pulls the mouth corners
    if (aColor.a == 0.0) rest += vec3(sign(rest.x) * 0.05, 0.10, -0.02) * exp(-dot(lip, lip)) * smoothstep(0.55, 0.85, rest.z) * uSmile;
    ivec4 j = ivec4(aJoints * 255.0 + 0.5);
    mat4x3 skin = bone(j.x) * aWeights.x + bone(j.y) * aWeights.y + bone(j.z) * aWeights.z + bone(j.w) * aWeights.w;
    vWorld = skin * vec4(rest, 1.0);
    vNormal = mat3(skin) * n;
    vColor = aColor;
    gl_Position = uViewProj * vec4(vWorld, 1.0);
}
"""

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
    return 1.0 - 0.45 * (1.0 - smoothstep(0.45, 1.15, miss)) * smoothstep(0.55, 1.2, along);
}
vec3 toSrgb(vec3 c) { return pow(clamp(c, 0.0, 1.0), vec3(1.0 / 2.2)); }
vec3 tone(vec3 c) { c *= 1.12; return c * (1.0 + c * 0.12) / (1.0 + c * 0.42); }
"""

FUR_FS = """
#version 330 core
in vec3 vNormal; in vec3 vWorld; in vec4 vColor;
out vec4 fragColor;
""" + LIGHT_GLSL + """
void main() {
    vec3 n = normalize(vNormal), v = normalize(uEye - vWorld);
    vec3 light = shade(pow(vColor.rgb, vec3(2.2)), n, vWorld, 0.35, headShadow(vWorld));
    light += vColor.a * 0.35 * pow(max(0.0, dot(n, normalize(normalize(KEY) + v))), 40.0);
    fragColor = vec4(toSrgb(tone(light)), 1.0);
}
"""

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

# The same layers as the eye texture of Kedi_Maskot.blend, but the pupil can look around and grow.
EYE_FS = """
#version 330 core
in vec3 vDir; in vec3 vWorld; in vec3 vNormal;
uniform vec2 uGaze; uniform float uSide; uniform float uPupil;
out vec4 fragColor;
""" + LIGHT_GLSL + """
float disc(float edge, float soft, float r) { return clamp((edge - r) / soft + 0.5, 0.0, 1.0); }
vec2 onEye(vec3 d, vec3 look) {
    vec3 right = normalize(cross(vec3(0, 1, 0), look));
    return vec2(dot(d, right), dot(d, cross(look, right)));
}
void main() {
    vec3 n = normalize(vNormal), d = normalize(vDir), v = normalize(uEye - vWorld);
    vec3 ahead = normalize(vec3(0.20 * uSide, 0.0, 1.0));
    vec3 look = normalize(ahead + vec3(uGaze.x * 0.32, uGaze.y * 0.25, 0.0));
    vec2 p = onEye(d, look);
    float r = dot(d, look) < 0.0 ? 1.0 : length(p), a = atan(p.y, p.x);
    vec3 outer = vec3(0.235, 0.250, 0.041), inner = vec3(0.521, 0.515, 0.122);
    vec3 c = vec3(0.008);
    c = mix(c, outer, disc(0.93, 0.05, r));
    c = mix(c, inner, disc(0.78, 0.30, r));
    c = mix(c, outer * 0.4, disc(0.90, 0.03, r) * (0.5 + 0.5 * sin(a * 52.0 + 3.0 * sin(a * 7.0))) * 0.25);
    c = mix(c, vec3(0.004, 0.004, 0.006), disc(0.46 + 0.28 * uPupil, 0.03, length(p * vec2(1.08, 1.0))));
    c *= 0.75 + 0.45 * max(0.0, dot(n, normalize(KEY)));
    vec2 h = onEye(d, ahead);
    float glint = disc(0.16, 0.03, length(h - vec2(-0.24, 0.30))) + 0.8 * disc(0.07, 0.03, length(h - vec2(0.22, -0.26)));
    c += pow(1.0 - max(0.0, dot(n, v)), 4.0) * vec3(0.08, 0.09, 0.11);
    c = mix(c, vec3(2.4), min(glint, 1.0));
    fragColor = vec4(toSrgb(tone(c)), 1.0);
}
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


class _Mesh:
    """Interleaved vertices + indices in a vertex array object. Layout: (OpenGL type, components) per attribute."""

    def __init__(self, gl, vertices: np.ndarray, indices: np.ndarray, layout: tuple[tuple[int, int], ...]) -> None:
        self.vao = QOpenGLVertexArrayObject()
        self.vao.create()
        self.vao.bind()
        self.vbo = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        self.ibo = QOpenGLBuffer(QOpenGLBuffer.Type.IndexBuffer)
        for buf, data in ((self.vbo, vertices), (self.ibo, indices.astype(np.uint32))):
            buf.create()
            buf.bind()
            raw = data.tobytes()
            buf.allocate(raw, len(raw))
        self.count = int(indices.size)
        sizes = [size * (4 if kind == GL_FLOAT else 1) for kind, size in layout]
        self._attr = [(loc, kind, sum(sizes[:loc]), size, sum(sizes)) for loc, (kind, size) in enumerate(layout)]
        self.vao.release()

    def setup(self, program: QOpenGLShaderProgram) -> None:
        self.vao.bind()
        self.vbo.bind()
        for loc, kind, offset, size, stride in self._attr:
            program.enableAttributeArray(loc)
            program.setAttributeBuffer(loc, kind, offset, size, stride)
        self.ibo.bind()
        self.vao.release()


def load_cat(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Vertices (one record each, in the order of the shader's attributes) and triangles."""
    with np.load(path) as m:
        start = int(m["lid_start"])
        v = np.zeros(len(m["position"]), [("position", "f4", 3), ("closed", "f4", 3), ("normal", "i1", 4),
                                          ("color", "u1", 4), ("joints", "u1", 4), ("weights", "u1", 4)])
        for name in ("position", "color", "joints", "weights"):
            v[name] = m[name]
        v["normal"][:, :3] = m["normal"]
        v["closed"][start:], v["normal"][start:, 3] = m["lid_closed"], m["lid_upper"] * 127
        return v, m["triangles"]


CAT_LAYOUT = ((GL_FLOAT, 3), (GL_FLOAT, 3), (GL_BYTE, 4), (GL_UBYTE, 4), (GL_UBYTE, 4), (GL_UBYTE, 4))


class CatRenderer:
    def __init__(self, directory: Optional[Path] = None) -> None:
        directory = directory or asset_dir()
        try:
            vertices, triangles = load_cat(directory / "cat.npz")
        except (OSError, ValueError, KeyError) as exc:
            raise RendererError(f"Kedi modeli okunamadı: {exc}") from exc
        self.rig = CatRig()
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
            self._body = _Mesh(self._gl, vertices, triangles, CAT_LAYOUT)
            self._body.setup(self._fur)
            pos, tri = _sphere()
            self._ball = _Mesh(self._gl, pos.astype(np.float32), tri, ((GL_FLOAT, 3),))
            self._ball.setup(self._eye)
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
            eye = QVector3D(0.0, 2.05, 12.5)
            vp = QMatrix4x4()
            vp.perspective(20.6, w / h, 1.0, 60.0)
            vp.lookAt(eye, QVector3D(0.0, 1.30, 0.0), QVector3D(0, 1, 0))
            head_q = QMatrix4x4(*[float(x) for x in head.ravel()])
            center = head[:3, :3] @ np.array([0.0, 2.05, .1]) + head[:3, 3]
            head_pos = QVector3D(*[float(x) for x in center])

            p = self._fur
            p.bind()
            p.setUniformValue(p.uniformLocation("uViewProj"), vp)
            p.setUniformValueArray(p.uniformLocation("uBones"), skin[:, :3, :].astype(np.float32).ravel().tolist(), BONES * 3, 4)
            self._common(p, eye, head_pos)
            gl.glUniform1f(p.uniformLocation("uSmile"), float(pose.smile))
            gl.glUniform1f(p.uniformLocation("uFrown"), max(0.0, -float(pose.brow)))
            p.setUniformValue(p.uniformLocation("uBlink"), QVector2D(*(min(1.0, max(0.0, float(b))) for b in pose.blink)))
            p.setUniformValueArray(p.uniformLocation("uEyes"), EYE_CENTERS.astype(np.float32).ravel().tolist(), 2, 3)
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
            p.setUniformValue(p.uniformLocation("uGaze"), QVector2D(*pose.gaze))
            self._ball.vao.bind()
            for s in (0, 1):
                p.setUniformValue(p.uniformLocation("uCenter"), QVector3D(*[float(v) for v in EYE_CENTERS[s]]))
                gl.glUniform1f(p.uniformLocation("uSide"), -1.0 if s == 0 else 1.0)
                gl.glDrawElements(GL_TRIANGLES, self._ball.count, GL_UINT, VoidPtr(0))
            self._ball.vao.release()
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
            for m in (self._body, self._ball):
                m.vao.destroy()
                m.vbo.destroy()
                m.ibo.destroy()
            self._pack.destroy()
            self._pack_spare.destroy()
            self._fbo = self._small = None
            for p in (self._fur, self._eye):
                p.removeAllShaders()
            self._ctx.doneCurrent()
        self._surface.destroy()


def _rect(w: int, h: int):
    from PySide6.QtCore import QRect
    return QRect(0, 0, w, h)


__all__ = ["CatRenderer", "RendererError", "asset_dir"]
