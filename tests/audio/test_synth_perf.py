"""Render-time budget: 8 sounding voices (E2..E6) must render in < 30 % of the block duration."""
from __future__ import annotations

import time

import numpy as np
import pytest

from handcontrol.instrument.synth import GuitarSynth

NOTES = (40, 45, 52, 59, 64, 76, 84, 88)   # E2 .. E6


@pytest.mark.parametrize("tone", ["clean", "electric"])
@pytest.mark.parametrize("block", [128, 256])
def test_render_time_under_30_percent_of_block(block, tone):
    s = GuitarSynth(tone=tone, volume=1.0)
    out = np.zeros(block, dtype=np.float32)
    times = []
    voices = []
    for b in range(1200):
        if b % 30 == 0:                         # keep all 8 strings sounding (re-pluck)
            for i, m in enumerate(NOTES):
                s.note_on(m, 1.0, b * 10 + i, string=i)
            s.bend(b * 10 + 7, 1.0)
        t0 = time.perf_counter()
        s.render(block, out=out)
        times.append(time.perf_counter() - t0)
        voices.append(s.active_voices)
    block_ms = block / s.sample_rate * 1000.0
    med = float(np.median(times)) * 1000.0
    p95 = float(np.percentile(times, 95)) * 1000.0
    print(f"\n{tone} {block} frames: median {med:.3f} ms, p95 {p95:.3f} ms, block {block_ms:.2f} ms, "
          f"load {med / block_ms * 100:.1f} %, min voices {min(voices)}")
    assert min(voices) == 8
    assert med < 0.3 * block_ms
