from __future__ import annotations

import pytest

from handcontrol.contracts import Rect
from handcontrol.dryrun import make_monitor
from handcontrol.mapping import (
    CalibrationRect,
    bounding_rect,
    contains,
    map_camera_point,
    map_normalized,
    normalize_camera_point,
    project_to_monitors,
    threshold_physical_px,
)

PRIMARY = make_monitor(0, 0, 1920, 1080, 1.0, primary=True)
LEFT_NEG = make_monitor(-2560, -360, 2560, 1440, 1.5)          # left of primary, taller, negative origin
PORTRAIT = make_monitor(1920, -420, 1080, 1920, 1.0)            # portrait right of primary


def _on_some_monitor(p, mons):
    return any(contains(m.bounds, p[0], p[1]) for m in mons)


def test_single_monitor_corners_and_center():
    mons = [PRIMARY]
    assert map_normalized(0, 0, mons) == (0, 0)
    assert map_normalized(1, 1, mons) == (1919, 1079)
    assert map_normalized(0.5, 0.5, mons) == (960, 540)


def test_bounding_rect_with_negative_origin():
    assert bounding_rect([PRIMARY, LEFT_NEG]) == Rect(-2560, -360, 1920, 1080)
    assert bounding_rect([]) is None
    assert map_normalized(0.5, 0.5, []) is None


def test_negative_coordinates_reachable():
    mons = [PRIMARY, LEFT_NEG]
    p = map_normalized(0.0, 0.0, mons)
    assert p == (-2560, -360)
    assert _on_some_monitor(p, mons)


def test_mismatched_heights_gap_projects_to_nearest_monitor():
    mons = [PRIMARY, LEFT_NEG]
    # bottom-right of the bounding box is on primary; top-right lies in the gap above primary
    p = map_normalized(1.0, 0.0, mons)
    assert p == (1919, 0)
    for u in [i / 20 for i in range(21)]:
        for v in [j / 20 for j in range(21)]:
            assert _on_some_monitor(map_normalized(u, v, mons), mons)


def test_portrait_monitor_and_gap_below_it():
    mons = [PRIMARY, PORTRAIT]
    box = bounding_rect(mons)
    assert box == Rect(0, -420, 3000, 1500)
    # gap below primary (y > 1079, x < 1920) -> nearest primary bottom edge
    assert project_to_monitors(500, 1400, mons) == (500, 1079)
    assert project_to_monitors(2500, 1400, mons) == (2500, 1400)  # on portrait
    for u in [i / 10 for i in range(11)]:
        for v in [j / 10 for j in range(11)]:
            assert _on_some_monitor(map_normalized(u, v, mons), mons)


def test_calibration_and_mirror():
    cal = CalibrationRect(0.25, 0.25, 0.75, 0.75)
    # unmirrored camera x=0.25 -> mirrored 0.75 -> right edge
    assert normalize_camera_point(160, 240, 640, 480, cal, mirror=True) == (1.0, 0.5)
    assert normalize_camera_point(160, 240, 640, 480, cal, mirror=False) == (0.0, 0.5)
    # outside the calibrated region clamps
    assert normalize_camera_point(0, 0, 640, 480, cal, mirror=False) == (0.0, 0.0)
    assert map_camera_point(320, 240, 640, 480, [PRIMARY], cal, mirror=True) == (960, 540)
    assert normalize_camera_point(1, 1, 0, 480) is None
    with pytest.raises(ValueError):
        CalibrationRect(0.5, 0.5, 0.5, 0.9)


@pytest.mark.parametrize("x,y,expected", [(100, 100, 15.0), (-100, 100, 22.5), (-5000, 0, 22.5)])
def test_dpi_threshold_scaling(x, y, expected):
    assert threshold_physical_px(15.0, x, y, [PRIMARY, LEFT_NEG]) == pytest.approx(expected)
