from __future__ import annotations

import ctypes as C

import pytest

from _tools_fakes import FakeConsole
from handcontrol.contracts import Monitor, Rect
from handcontrol.tools import pointer_probe as pp


def monitors():
    return [Monitor(Rect(-1920, -100, 0, 980), Rect(-1920, -100, 0, 940), 1.5, False),
            Monitor(Rect(0, 0, 1920, 1080), Rect(0, 0, 1920, 1040), 1, True)]


class FakePointer:
    def __init__(self, offset=(0, 0)):
        self.position = (111, 222)
        self.moves = []
        self.offset = offset
        self.failure = None
        self.reject = False

    def move_pointer(self, x, y):
        self.moves.append((x, y))
        if len(self.moves) == 3 and self.failure:
            raise self.failure
        if self.reject:
            return False
        self.position = (x + self.offset[0], y + self.offset[1])
        return True

    def read(self):
        return self.position


def test_targets_use_physical_negative_bounds_and_exclusive_edges():
    targets = pp.monitor_targets(monitors()[0])
    assert targets == [("merkez", -961, 439), ("sol üst", -1900, -80),
                       ("sağ üst", -21, -80), ("sağ alt", -21, 959), ("sol alt", -1900, 959)]


def test_tiny_display_targets_stay_inside_bounds():
    m = Monitor(Rect(10, 20, 12, 22), Rect(10, 20, 12, 22), 1, True)
    assert all(10 <= x < 12 and 20 <= y < 22 for _, x, y in pp.monitor_targets(m))


def test_all_monitors_reached_and_pointer_restored():
    pointer = FakePointer()
    waits = []
    result = pp.measure_pointer(monitors(), pointer, pointer.read, sleep=waits.append)
    assert len(pointer.moves) == 11 and pointer.moves[-1] == (111, 222)
    assert result["restored"] and all(m["reached"] for m in result["monitors"])
    assert all(m["max_deviation_px"] == 0 for m in result["monitors"])
    assert len(waits) == 11


def test_offset_is_measured_not_mistaken_for_success():
    pointer = FakePointer(offset=(3, 4))
    result = pp.measure_pointer(monitors(), pointer, pointer.read, sleep=lambda _: None)
    assert not result["restored"]
    assert all(not m["reached"] and m["max_deviation_px"] == 5 for m in result["monitors"])
    step = result["monitors"][0]["steps"][0]
    assert (step["dx"], step["dy"]) == (3, 4)


def test_rejected_moves_are_failures_even_if_actual_matches_target():
    pointer = FakePointer()
    pointer.reject = True
    targets = [point[1:] for m in monitors() for point in pp.monitor_targets(m)]
    readings = iter([(111, 222), *targets, (111, 222)])
    result = pp.measure_pointer(monitors(), pointer, lambda: next(readings), sleep=lambda _: None)
    assert not result["restored"]
    assert all(not m["reached"] and m["max_deviation_px"] == 0 for m in result["monitors"])


@pytest.mark.parametrize("failure", [OSError("Move rejected"), KeyboardInterrupt()])
def test_failure_or_interrupt_always_attempts_restore(failure):
    pointer = FakePointer()
    pointer.failure = failure
    result = pp.measure_pointer(monitors(), pointer, pointer.read, sleep=lambda _: None)
    assert pointer.moves[-1] == (111, 222) and result["restored"]
    assert not result["monitors"][0]["reached"]
    assert result["interrupted"] == isinstance(failure, KeyboardInterrupt)


def test_initial_read_failure_never_moves_pointer():
    pointer = FakePointer()
    def broken():
        raise OSError("Okuma hatası")
    result = pp.measure_pointer(monitors(), pointer, broken, sleep=lambda _: None)
    assert not pointer.moves and result["error"] and not result["restored"]


def test_step_read_failure_still_restores_and_is_not_reached():
    pointer = FakePointer()
    calls = 0
    def read():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("Okuma hatası")
        return pointer.read()
    result = pp.measure_pointer(monitors(), pointer, read, sleep=lambda _: None)
    assert result["restored"] and not result["monitors"][0]["reached"]
    assert result["monitors"][0]["steps"][0]["deviation_px"] is None


def test_restore_failure_is_reported():
    pointer = FakePointer()
    def move(x, y):
        if (x, y) == (111, 222):
            raise OSError("Dönüş engellendi")
        return pointer.move_pointer(x, y)
    from types import SimpleNamespace
    result = pp.measure_pointer(monitors(), SimpleNamespace(move_pointer=move), pointer.read, sleep=lambda _: None)
    assert not result["restored"] and "Dönüş engellendi" in result["restore_error"]


def test_prompt_countdown_precede_all_movement_and_report_written(out_dir):
    pointer = FakePointer()
    console = FakeConsole()
    waits = []
    def sleep(seconds):
        if not waits:
            assert console.asked and not pointer.moves and seconds == 3
        waits.append(seconds)
    result = pp.run_probe(monitors(), pointer, pointer.read, console, sleep=sleep, out_dir=out_dir)
    assert result["restored"]
    report = next(out_dir.glob("hw_pointer_probe_*.md")).read_text(encoding="utf-8")
    assert "ulaşıldı" in report and "1.5" in report and "-1920" in report
    assert "doğrulandı" in report and "Sapma px" in report


def test_cancel_before_movement_creates_no_report(out_dir):
    pointer = FakePointer()
    console = FakeConsole({"Hazırsanız": "q"})
    assert pp.run_probe(monitors(), pointer, pointer.read, console, out_dir=out_dir,
                        sleep=lambda _: pytest.fail("No countdown on cancellation")) is None
    assert not pointer.moves and not out_dir.exists()


def test_getcursorpos_adapter_uses_injected_api():
    from types import SimpleNamespace
    from handcontrol.windows._win32 import POINT
    def get_position(pointer):
        point = C.cast(pointer, C.POINTER(POINT)).contents
        point.x, point.y = -2000, 42
        return 1
    assert pp.read_cursor(api=SimpleNamespace(GetCursorPos=get_position)) == (-2000, 42)
    with pytest.raises(OSError):
        pp.read_cursor(api=SimpleNamespace(GetCursorPos=lambda _: 0))


@pytest.mark.parametrize("kwargs", [{"settle_seconds": -1}, {"tolerance_px": float("nan")}])
def test_invalid_parameters_never_move_pointer(kwargs):
    pointer = FakePointer()
    with pytest.raises(ValueError):
        pp.measure_pointer(monitors(), pointer, pointer.read, **kwargs)
    assert not pointer.moves


def test_invalid_monitor_never_moves_pointer():
    pointer = FakePointer()
    invalid = Monitor(Rect(10, 10, 5, 5), Rect(10, 10, 5, 5), 1, True)
    with pytest.raises(ValueError):
        pp.measure_pointer([invalid], pointer, pointer.read)
    assert not pointer.moves
