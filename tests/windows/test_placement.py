from __future__ import annotations

import pytest

from handcontrol.contracts import Monitor, Rect
from handcontrol.windows.placement import (desktop_bounds, ensure_title_visible,
    monitor_for_rect, nearest_point, normalize_pointer, proportional_placement)


def monitor(rect: Rect, scale: float = 1.0) -> Monitor:
    return Monitor(rect, rect, scale, rect.left == 0)


@pytest.fixture
def displays():
    return (monitor(Rect(-1200, -400, 0, 1520)), monitor(Rect(300, 0, 2220, 1080), 1.5))


def test_negative_portrait_offset_bounds(displays):
    assert desktop_bounds(displays) == Rect(-1200, -400, 2220, 1520)


@pytest.mark.parametrize("point,expected", [((-1200, -400), (0, 0)),
    ((2219, 1079), (65535, round(1479 * 65535 / 1919))),
    ((-1200, 1519), (0, 65535)), ((150, 500), (round(1500 * 65535 / 3419), round(900 * 65535 / 1919)))])
def test_normalization_and_gap_projection(displays, point, expected):
    assert normalize_pointer(*point, displays) == expected


def test_gap_projects_to_nearest_real_pixel(displays):
    assert nearest_point(100, 500, [m.bounds for m in displays]) == (-1, 500)
    assert nearest_point(2500, 2000, [m.bounds for m in displays]) == (2219, 1079)


def test_single_pixel_normalization():
    assert normalize_pointer(100, -20, [monitor(Rect(1, 2, 2, 3))]) == (0, 0)


def test_proportional_cross_dpi():
    source = monitor(Rect(-1000, 0, 0, 800))
    dest = monitor(Rect(200, -200, 2200, 1400), 1.5)
    assert proportional_placement(Rect(-700, 200, -300, 600), source, dest) == Rect(900, 300, 1500, 900)


def test_proportional_oversize_is_fitted():
    source = monitor(Rect(0, 0, 100, 100))
    dest = monitor(Rect(-50, 50, 0, 150), 2)
    assert proportional_placement(Rect(0, 0, 200, 200), source, dest) == dest.work_area


def test_title_visibility():
    area = Rect(-1000, 40, 0, 800)
    rect = ensure_title_visible(Rect(500, 900, 900, 1200), [area])
    assert rect == Rect(-120, 768, 280, 1068)
    assert ensure_title_visible(rect, [area]) == rect


def test_title_chooses_nearest_work_area(displays):
    rect = Rect(400, -200, 800, 100)
    assert ensure_title_visible(rect, [m.work_area for m in displays]) == Rect(400, 0, 800, 300)
    assert monitor_for_rect(Rect(400, 10, 500, 100), displays) == displays[1]


@pytest.mark.parametrize("scale", [0, -1, float("nan"), float("inf")])
def test_invalid_dpi_rejected(scale):
    with pytest.raises(ValueError):
        proportional_placement(Rect(0, 0, 20, 20), monitor(Rect(0, 0, 100, 100), scale), monitor(Rect(0, 0, 100, 100)))


def test_empty_monitor_list_rejected():
    with pytest.raises(ValueError):
        normalize_pointer(0, 0, [])
