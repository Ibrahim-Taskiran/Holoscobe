"""Fast picture of the whole ink volume (numpy only), used while the scene moves."""
from __future__ import annotations

from functools import lru_cache

import numpy as np

from .drawing import WORK_DEPTH, InkScene

MAX_COLUMN = 18


@lru_cache(maxsize=64)
def _stamp(half_px: int):
    """Anti-aliased disc of radius half_px/2: pixel offsets and coverage in the high byte."""
    r = half_px / 2
    k = int(np.ceil(r + 0.5))
    y, x = np.mgrid[-k:k+1, -k:k+1]
    a = np.clip(r + 0.5 - np.hypot(x, y), 0, 1)
    m = a > 0
    return k, y[m], x[m], (a[m] * 255).astype(np.uint16) << 8


class InkRaster:
    def __init__(self):
        self._rows = np.empty((0, 7))
        self._key = None

    def _sync(self, scene: InkScene):
        """Dabs are append-only within one revision: convert only the new ones."""
        key = (id(scene), scene.revision)
        if key != self._key or len(self._rows) > len(scene.dabs):
            self._key, self._rows = key, np.empty((0, 7))
        new = scene.dabs[len(self._rows):]
        if new:
            rows = [(d.x, d.y, d.z, d.radius, d.stretch, d.born, d.grain) for d in new]
            self._rows = np.concatenate((self._rows, np.array(rows)))
        return self._rows.T

    def render(self, scene: InkScene, w: int, h: int, now: float, grow_ms: float,
               flow: float | None = None) -> np.ndarray:
        """Premultiplied ARGB32 (h, w). Where dabs overlap, full coverage and then the front (darker) one wins.
        `flow` 0..1 is the progress of the clearing animation."""
        x, y, z, radius, stretch, born, grain = self._sync(scene)
        c, s = np.cos(scene.angle), np.sin(scene.angle)
        depth = z*c - x*s
        px = (x*c + z*s)*w + w/2
        py = (y - 0.24*(depth - WORK_DEPTH))*w + h/2
        growth = np.clip((now - born)/grow_ms, 0, 1)
        r = radius*w*(1 - 0.55*(1 - growth)**2)
        half = r*stretch                  # vertical half length
        fade = np.ones_like(r)
        if flow is not None:
            # Neighbouring dabs share a fall time so a band separates into rivulets.
            sx = px/w - 0.5
            phase = (0.5 + 0.5*np.sin(92*sx + 5*np.sin(sx*27))) * 0.19
            f = np.clip((flow - phase)/(1 - phase), 0, 1)
            tail = w*(0.012 + 0.075*grain)*np.sin(f*np.pi)
            r = np.maximum(0.7, r*(1 - 0.9*f))
            half, py, fade = half + tail, py + tail + h*1.55*f**2, 1 - f**2
        shade = np.clip(np.round(12 - depth*63 + grain*2), 0, 36).astype(np.int64) + 9
        long = np.flatnonzero(half > 1.6*r)            # drip bodies: a column of small dabs
        if long.size:
            n = np.minimum(MAX_COLUMN, np.ceil(half[long]/r[long])).astype(np.int64)
            src = np.repeat(long, n)
            step = np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n)
            at = (2*step/np.maximum(1, np.repeat(n, n) - 1) - 1) * (half[src] - r[src])
            px, py = np.concatenate((px, px[src])), np.concatenate((py, py[src] + at))
            r, shade, fade = (np.concatenate((v, v[src])) for v in (r, shade, fade))
        q = np.clip(np.round(r*2), 1, 120).astype(np.int64)
        margin = _stamp(int(q.max()))[0] if q.size else 0   # an invisible frame keeps every stamp in bounds
        fw, fh = w + 2*margin, h + 2*margin
        ix, iy = np.round(px - 0.5).astype(np.int64) + margin, np.round(py - 0.5).astype(np.int64) + margin
        keep = (ix >= margin) & (ix < w + margin) & (iy >= margin) & (iy < h + margin)
        order = np.flatnonzero(keep)[np.lexsort((-shade[keep], q[keep]))]
        fade = None if flow is None else fade[order]
        q, base, value = q[order], (iy*fw + ix)[order], (255 - shade[order]).astype(np.uint16)
        buf = np.zeros(fw*fh, np.uint16)
        cuts = np.flatnonzero(np.diff(q)) + 1 if q.size else ()
        for a, b in zip((0, *cuts), (*cuts, q.size)):
            if a == b:
                continue
            _, oy, ox, cover = _stamp(int(q[a]))
            for off, cov in zip((oy*fw + ox).tolist(), cover):
                i = base[a:b] + off       # sorted back to front: the last write of a repeated index is the maximum
                if fade is not None:
                    cov = ((cov >> 8)*fade[a:b]).astype(np.uint16) << 8
                buf[i] = np.maximum(buf[i], value[a:b] | cov)
        buf = buf.reshape(fh, fw)[margin:margin + h, margin:margin + w].astype(np.uint32)
        alpha = buf >> 8
        grey = (255 - (buf & 255)) * alpha // 255
        return np.ascontiguousarray((alpha << 24) | (grey * 0x010101))
