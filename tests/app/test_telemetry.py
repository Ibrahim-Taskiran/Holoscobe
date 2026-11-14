from __future__ import annotations
import csv
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from PySide6.QtWidgets import QApplication
from handcontrol.app import Runtime, main
from handcontrol.config import Settings
from handcontrol.contracts import (Action, ActionKind, FingerInfo, FingerName, FingerState, FrameFeatures,
                                   FrameSample, GestureEvent, GestureKind, HandFeatures, Handedness, Quality)
from handcontrol.dryrun import FakeDisplays, FakeVolume, FakeWindows
from handcontrol.telemetry import COLUMNS, SessionRecorder, TelemetrySink
from handcontrol.ui import UiBridge


def hand(hid=1, side=Handedness.RIGHT, quality=Quality.USABLE, pinch=0.8):
    fingers = tuple(FingerInfo(n, FingerState.UNKNOWN if n is FingerName.RING else FingerState.EXTENDED, 0.0)
                    for n in FingerName)
    return HandFeatures(hid, side, quality, (100.0, 50.0), 80.0, fingers, pinch, (0.0, 0.0), ())


def frame(t, hands):
    return FrameFeatures(t, t + 5, 640, 480, tuple(hands), False)


def snap(**kw):
    base = dict(state=SimpleNamespace(value="active"), mode=SimpleNamespace(value="pointer"),
                pending_action="", notice="", pointer=(10, 20), dropped_actions=0)
    base.update(kw)
    return SimpleNamespace(**base)


def rows(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def make_runtime(**kw):
    displays = FakeDisplays()
    displays.start = Mock()
    displays.close = Mock()
    return Runtime(UiBridge(), SimpleNamespace(load=lambda: Settings(), save=Mock()), displays=displays,
                   windows=FakeWindows(), volume=FakeVolume(), session_factory=Mock(), hotkey_factory=Mock(), **kw)


def test_recorder_rows_and_defaults(tmp_path):
    p = tmp_path / "s.csv"
    rec = SessionRecorder(p, now_ms=lambda: 120.0)
    rec.record_action(ActionKind.LEFT_CLICK)
    rec.record_action(ActionKind.MOVE_POINTER)
    ev = (GestureEvent(GestureKind.PINCH_START, 100.0, 1), GestureEvent(GestureKind.PINCH_END, 100.0, 1))
    rec.on_frame(frame(100.0, [hand(), hand(2, Handedness.LEFT)]), ev, snap())
    rec.on_frame(frame(133.0, []), (), snap(pointer_engaged=True, tracking_ok=False, last_cancel="x"))
    rec.close()
    r = rows(p)
    assert list(r[0].keys()) == list(COLUMNS)
    assert r[0]["hands"] == "2" and r[0]["dom_present"] == "1" and r[0]["dom_quality"] == "usable"
    assert r[0]["age_ms"] == "20.0" and r[0]["finger_ring"] == "unknown" and r[0]["finger_index"] == "extended"
    assert r[0]["events"] == "pinch_start|pinch_end" and r[0]["actions"] == "left_click" and r[0]["moves"] == "1"
    assert r[0]["pointer_engaged"] == "0" and r[0]["tracking_ok"] == "1" and r[0]["last_cancel"] == ""
    assert r[1]["dom_present"] == "0" and r[1]["pinch_pu"] == "" and r[1]["pointer_engaged"] == "1"
    assert r[1]["tracking_ok"] == "0" and r[1]["last_cancel"] == "x" and r[1]["actions"] == ""


def test_recorder_io_error_disables_without_raising(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    rec = SessionRecorder(blocker / "sub" / "s.csv")
    assert not rec.enabled and rec.last_error
    rec.on_frame(frame(1.0, []), (), snap())
    rec.record_action(ActionKind.LEFT_CLICK)
    rec.close()


def test_recorder_write_error_disables(tmp_path):
    rec = SessionRecorder(tmp_path / "s.csv")
    rec._writer = Mock(writerow=Mock(side_effect=OSError("disk")))
    rec.on_frame(frame(1.0, []), (), snap())
    assert not rec.enabled and "disk" in rec.last_error
    rec.on_frame(frame(2.0, []), (), snap())


def test_recorder_flushes_about_once_per_interval(tmp_path):
    t = [0.0]
    rec = SessionRecorder(tmp_path / "s.csv", wall=lambda: t[0], flush_interval_s=1.0)
    rec.on_frame(frame(1.0, []), (), snap())
    rec._fh.flush = Mock()
    rec.on_frame(frame(2.0, []), (), snap())
    rec._fh.flush.assert_not_called()
    t[0] = 1.5
    rec.on_frame(frame(3.0, []), (), snap())
    rec._fh.flush.assert_called_once()
    rec.close()


def test_sink_wrapper_records_and_forwards():
    inner = Mock()
    inner.dispatch.return_value = "ok"
    rec = Mock()
    sink = TelemetrySink(inner, rec)
    assert sink.dispatch(Action(ActionKind.RIGHT_CLICK, 0, 0)) == "ok"
    rec.record_action.assert_called_once_with(ActionKind.RIGHT_CLICK)
    sink.release_all()
    inner.release_all.assert_called_once()


@pytest.fixture
def qt():
    return QApplication.instance() or QApplication([])


def test_runtime_wiring_records_frames_and_closes(qt, tmp_path):
    rec = SessionRecorder(tmp_path / "s.csv")
    r = make_runtime(telemetry=rec)
    try:
        r.pipeline.process(FrameSample(0, 1, 640, 480, ()))
    finally:
        r.close()
    assert not rec.enabled
    assert len(rows(tmp_path / "s.csv")) == 1


def test_observer_exception_is_swallowed(qt):
    r = make_runtime()
    try:
        r.pipeline.add_frame_observer(Mock(side_effect=RuntimeError("boom")))
        r.pipeline.process(FrameSample(0, 1, 640, 480, ()))
    finally:
        r.close()


def test_main_flag_parsing(monkeypatch, tmp_path):
    import handcontrol.app as app
    seen = {}

    def fake_runtime(*a, **kw):
        seen.update(kw)
        raise RuntimeError("stop")

    monkeypatch.setattr(app, "enable_per_monitor_v2", lambda: True)
    monkeypatch.setattr(app, "Runtime", fake_runtime)
    monkeypatch.setattr(app, "SettingsStore", lambda: None)
    monkeypatch.setattr("handcontrol.telemetry.default_session_path", lambda *a: tmp_path / "t.csv")
    assert main([]) == 1 and seen["telemetry"] is None
    assert main(["--telemetry"]) == 1 and isinstance(seen["telemetry"], SessionRecorder)
    seen["telemetry"].close()


def test_recorder_reason_and_mid_pinch_columns(tmp_path):
    from handcontrol.contracts import Landmark
    assert COLUMNS[-2:] == ("dom_reasons", "mid_pinch_pu")
    lms = [Landmark(0.0, 0.0, 0.0)] * 21
    lms[4], lms[12] = Landmark(0.25, 0.5, 0.0), Landmark(0.25 + 40.0 / 640, 0.5, 0.0)
    h = HandFeatures(7, Handedness.RIGHT, Quality.DEGRADED, (100.0, 50.0), 80.0, (), 0.8, (0.0, 0.0), tuple(lms))
    ff = frame(100.0, [h])
    object.__setattr__(ff, "reasons", ({7: ("palm_small", "slow_processing")}, ("overlap",)))
    p = tmp_path / "s.csv"
    rec = SessionRecorder(p)
    rec.on_frame(ff, (), snap())
    rec.on_frame(frame(133.0, [hand()]), (), snap())   # no reasons attribute, no landmarks
    rec.on_frame(frame(166.0, []), (), snap())
    rec.close()
    r = rows(p)
    assert r[0]["dom_reasons"] == "palm_small|slow_processing|overlap" and r[0]["mid_pinch_pu"] == "0.5"
    assert r[1]["dom_reasons"] == "" and r[1]["mid_pinch_pu"] == ""
    assert r[2]["dom_present"] == "0" and r[2]["mid_pinch_pu"] == ""
