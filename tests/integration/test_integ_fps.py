"""Timing windows at 30 fps with jitter and at 10 fps (DirectShow fallback on the target laptop).

Synthetic frame timing only; the real DirectShow interval distribution is not measured here.
"""
from __future__ import annotations

import pytest
from dataclasses import replace

from handcontrol.contracts import ActionKind as A, ControlState, Mode
from handcontrol.controller import MenuKind

from integ_synth import OPEN, PINCH, POINT, Rig, clap, hand, pair

RATES = [(30, 8), (10, 0), (10, 25)]
SEEDS = range(4)
R0 = (220.0, 260.0)


def _rig(fps: float, jitter: float, seed: int) -> Rig:
    return Rig(fps=fps, jitter_ms=jitter, seed=seed)


@pytest.mark.parametrize("fps,jitter", RATES)
@pytest.mark.parametrize("seed", SEEDS)
def test_clap_toggles_at_rate(fps, jitter, seed):
    rig = _rig(fps, jitter, seed)
    rig.camera_on()
    clap(rig, merge_frames=1 if fps <= 10 else 2, approach_ms=300, separate_ms=300)
    assert rig.state is ControlState.ACTIVE
    rig.run(800, pair(3.0))
    clap(rig, merge_frames=1 if fps <= 10 else 2, approach_ms=300, separate_ms=300)
    assert rig.state is ControlState.PAUSED


@pytest.mark.parametrize("fps,jitter", RATES)
@pytest.mark.parametrize("seed", SEEDS)
def test_legacy_pinch_click_at_rate(fps, jitter, seed):
    rig = _rig(fps, jitter, seed)
    rig.ctl._cfg = replace(rig.ctl.config, index_tap_click=False)
    rig.activate([hand(POINT, R0)])
    rig.run(200, [hand(PINCH, R0)])
    rig.run(400, [hand(POINT, R0)])
    assert rig.count(A.LEFT_CLICK) == 1


@pytest.mark.parametrize("fps,jitter", RATES)
@pytest.mark.parametrize("seed", SEEDS)
def test_menu_dwell_at_rate(fps, jitter, seed):
    rig = _rig(fps, jitter, seed)
    rig.activate([hand(POINT, R0), hand(POINT, (440, 300), side="left")])
    rig.run(500, [hand(POINT, R0), hand(OPEN, (440, 300), side="left")])
    assert rig.ctl.snapshot().menu is None                   # 600 ms not reached
    rig.run(500, [hand(POINT, R0), hand(OPEN, (440, 300), side="left")])
    m = rig.ctl.snapshot().menu
    assert m is not None and m.kind is MenuKind.MODE


@pytest.mark.parametrize("fps,jitter", RATES)
@pytest.mark.parametrize("seed", SEEDS)
def test_windows_overlay_vs_drag_at_rate(fps, jitter, seed):
    rig = _rig(fps, jitter, seed)
    rig.pipe.set_mode(Mode.WINDOWS)
    rig.activate([hand(POINT, R0)])
    rig.run(150, [hand(PINCH, R0)])                          # short pinch -> overlay
    rig.run(300, [hand(POINT, R0)])
    assert rig.ctl.snapshot().menu is not None and rig.count(A.WINDOW_DRAG_BEGIN) == 0
    rig.pipe.set_mode(Mode.WINDOWS)                          # tray re-select closes the overlay
    rig.run(400, [hand(POINT, R0)])
    rig.run(500, [hand(PINCH, R0)])                          # long hold -> drag
    rig.run(300, [hand(POINT, R0)])
    assert rig.count(A.WINDOW_DRAG_BEGIN) == 1 and rig.count(A.WINDOW_DRAG_END) == 1


@pytest.mark.parametrize("fps,jitter", RATES)
def test_close_hold_at_rate(fps, jitter):
    rig = _rig(fps, jitter, 0)
    rig.pipe.set_mode(Mode.WINDOWS)
    rig.activate([hand(POINT, R0)])
    rig.run(150, [hand(PINCH, R0)])
    rig.run(300, [hand(POINT, R0)])
    low = (220.0, 345.0)
    rig.run(300, [hand(POINT, low)])
    rig.run(150, [hand(PINCH, low)])
    rig.run(300, [hand(POINT, low)])
    rig.run(1300, [hand(PINCH, low)])
    assert rig.count(A.WINDOW_CLOSE) == 1
