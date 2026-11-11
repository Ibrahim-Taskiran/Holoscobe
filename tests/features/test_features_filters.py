"""One Euro filter behaviour."""
from __future__ import annotations

import math
import random
import statistics

import pytest

from handcontrol.filters import OneEuroFilter, OneEuroFilter2D

STEP = 1000.0 / 30.0


def test_jitter_reduction_on_noisy_constant():
    rng = random.Random(7)
    f = OneEuroFilter()
    raw, out = [], []
    for k in range(300):
        v = 100.0 + rng.gauss(0.0, 2.0)
        y = f(v, k * STEP)
        if k >= 30:
            raw.append(v)
            out.append(y)
    assert statistics.pstdev(out) < 0.5 * statistics.pstdev(raw)
    assert abs(statistics.fmean(out) - 100.0) < 0.5


def test_low_lag_on_fast_motion():
    euro = OneEuroFilter(min_cutoff=1.0, beta=0.007)
    slow = OneEuroFilter(min_cutoff=1.0, beta=0.0)     # fixed low-pass at min_cutoff
    speed = 1000.0                                     # px/s
    for k in range(60):
        t = k * STEP
        x = speed * t / 1000.0
        e, s = euro(x, t), slow(x, t)
    lag_euro, lag_slow = x - e, x - s
    assert lag_euro < 0.3 * lag_slow
    assert lag_euro < 40.0


def test_dt_zero_and_backwards_keep_last_output():
    f = OneEuroFilter()
    f(0.0, 0.0)
    y = f(10.0, 33.0)
    assert f(50.0, 33.0) == y
    assert f(50.0, 20.0) == y
    assert f(10.0, 66.0) != y


def test_long_gap_resets():
    f = OneEuroFilter(max_gap_ms=250.0)
    for k in range(10):
        f(0.0, k * STEP)
    assert f(500.0, 10 * STEP + 1000.0) == 500.0


def test_non_finite_resets_and_reset_method():
    f = OneEuroFilter()
    f(1.0, 0.0)
    assert math.isnan(f(float("nan"), 33.0))
    assert f(7.0, 66.0) == 7.0
    f.reset()
    assert f(3.0, 100.0) == 3.0


def test_invalid_parameters():
    with pytest.raises(ValueError):
        OneEuroFilter(min_cutoff=0.0)
    with pytest.raises(ValueError):
        OneEuroFilter2D(beta=-1.0)


def test_2d_jitter_lag_gap():
    rng = random.Random(3)
    f = OneEuroFilter2D()
    errs_raw, errs_out = [], []
    for k in range(200):
        p = (50.0 + rng.gauss(0, 2), 80.0 + rng.gauss(0, 2))
        q = f(p, k * STEP)
        if k > 30:
            errs_raw.append(math.hypot(p[0] - 50, p[1] - 80))
            errs_out.append(math.hypot(q[0] - 50, q[1] - 80))
    assert statistics.fmean(errs_out) < 0.5 * statistics.fmean(errs_raw)
    g = OneEuroFilter2D()
    for k in range(60):                   # fast diagonal motion
        t = k * STEP
        p = (700.0 * t / 1000.0, 700.0 * t / 1000.0)
        q = g(p, t)
    assert math.hypot(p[0] - q[0], p[1] - q[1]) < 50.0
    assert g(p, t) == q                   # dt = 0
    assert g((1.0, 2.0), t + 5000.0) == (1.0, 2.0)
    g.reset()
    assert g((4.0, 5.0), 0.0) == (4.0, 5.0)
