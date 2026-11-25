from __future__ import annotations

import threading
import time

import pytest
from _fakes import FakeCapture, FakeClock, FakeFrame, Factory, wait_until

from handcontrol.camera import (
    MSG_BUSY, MSG_LOST, MSG_NOT_FOUND, MSG_PERMISSION,
    Camera, CameraConfig, CameraOpenError, backend_order,
)
from handcontrol.contracts import CameraState


def make(factory, **kw):
    kw.setdefault("backoff_base_s", 0.0)
    return Camera(kw.pop("config", CameraConfig()), capture_factory=factory, **kw)


def test_backend_order():
    assert backend_order("msmf") == ("msmf",)
    assert backend_order("dshow") == ("dshow",)
    assert backend_order("auto") == ("msmf", "dshow")


def test_auto_falls_back_to_dshow():
    def beh(n, i, b):
        if b == "msmf":
            raise CameraOpenError("not_found")
        return FakeCapture(endless=True, delay=0.002)
    f = Factory(beh)
    cam = make(f, config=CameraConfig(backend="auto"))
    cam.start()
    assert cam.wait_for_state(CameraState.RUNNING)
    cam.stop()
    assert f.calls[:2] == [(0, "msmf"), (0, "dshow")]


def test_msmf_first_by_default_no_dshow():
    f = Factory(lambda n, i, b: FakeCapture(endless=True, delay=0.002))
    cam = make(f)
    cam.start()
    assert cam.wait_for_state(CameraState.RUNNING)
    cam.stop()
    assert f.calls == [(0, "msmf")]


def test_retry_then_error_with_message():
    f = Factory(lambda n, i, b: (_ for _ in ()).throw(CameraOpenError("busy")))
    states = []
    cam = make(f, max_open_attempts=3, on_state_change=lambda s, e: states.append((s, e)))
    cam.start()
    assert cam.wait_for_state(CameraState.ERROR)
    assert len(f.calls) == 3
    assert cam.last_error == MSG_BUSY
    assert states[0][0] == CameraState.STARTING and states[-1] == (CameraState.ERROR, MSG_BUSY)
    cam.stop()
    assert cam.state == CameraState.OFF


@pytest.mark.parametrize("kind,msg", [("permission", MSG_PERMISSION), ("busy", MSG_BUSY), ("not_found", MSG_NOT_FOUND)])
def test_error_messages(kind, msg):
    f = Factory(lambda n, i, b: (_ for _ in ()).throw(CameraOpenError(kind)))
    cam = make(f, max_open_attempts=1)
    cam.start()
    assert cam.wait_for_state(CameraState.ERROR)
    assert cam.last_error == msg
    cam.stop()


def test_succeeds_after_failed_attempt():
    def beh(n, i, b):
        if n == 0:
            raise CameraOpenError("busy")
        return FakeCapture(endless=True, delay=0.002)
    f = Factory(beh)
    cam = make(f)
    cam.start()
    assert cam.wait_for_state(CameraState.RUNNING)
    assert cam.last_error is None
    cam.stop()


def test_newest_frame_only_and_no_duplicates():
    frames = [FakeFrame(i) for i in range(1, 6)]
    cap = FakeCapture(frames)
    clock = FakeClock(100.0, step=1.0)
    cam = make(Factory(lambda n, i, b: cap), clock=clock)
    cam.start()
    assert wait_until(lambda: cam.frames_captured >= 5)
    got = cam.read_latest()
    assert got is not None and got[0].tag == 5          # older frames dropped
    assert cam.read_latest() is None                    # same frame never twice
    assert cam.frames_dropped == 4
    cam.stop()


def test_capture_timestamp_monotonic_from_clock():
    cap = FakeCapture([FakeFrame(1)])
    clock = FakeClock(500.0, step=10.0)
    cam = make(Factory(lambda n, i, b: cap), clock=clock)
    cam.start()
    assert wait_until(lambda: cam.frames_captured >= 1)
    frame, ms = cam.read_latest()
    assert ms == 500.0
    cam.stop()


def test_read_latest_timeout_wakes_on_frame():
    cap = FakeCapture(endless=True, delay=0.005)
    cam = make(Factory(lambda n, i, b: cap))
    cam.start()
    assert cam.wait_for_state(CameraState.RUNNING)
    first = cam.read_latest(timeout=1.0)
    second = cam.read_latest(timeout=1.0)
    assert first is not None and second is not None and second[0].tag > first[0].tag
    cam.stop()


def test_release_on_stop():
    cap = FakeCapture(endless=True, delay=0.002)
    cam = make(Factory(lambda n, i, b: cap))
    cam.start()
    assert cam.wait_for_state(CameraState.RUNNING)
    cam.stop()
    assert cap.released and cam.state == CameraState.OFF
    assert cam.read_latest() is None


def test_stop_during_retry_backoff_releases_nothing_open():
    f = Factory(lambda n, i, b: (_ for _ in ()).throw(CameraOpenError("not_found")))
    cam = make(f, max_open_attempts=50, backoff_base_s=5.0, backoff_max_s=5.0)
    cam.start()
    assert wait_until(lambda: len(f.calls) >= 1)
    t0 = time.monotonic()
    cam.stop()
    assert time.monotonic() - t0 < 2.0 and cam.state == CameraState.OFF


def test_reconnect_after_device_loss():
    caps = []

    def beh(n, i, b):
        c = FakeCapture([FakeFrame(1)]) if n == 0 else FakeCapture(endless=True, delay=0.002)
        caps.append(c)
        return c
    cam = make(Factory(beh), max_read_failures=3)
    cam.start()
    assert wait_until(lambda: len(caps) >= 2)       # first capture ran dry -> lost -> reopened
    assert wait_until(lambda: cam.state == CameraState.RUNNING and caps[0].released)
    assert wait_until(lambda: cam.frames_captured >= 3)
    cam.stop()
    assert caps[1].released


def test_connection_lost_goes_to_error_after_reconnects():
    cam = make(Factory(lambda n, i, b: FakeCapture([])), max_read_failures=2, max_reconnects=1)
    cam.start()
    assert cam.wait_for_state(CameraState.ERROR)
    assert cam.last_error == MSG_LOST
    cam.stop()


def test_manual_reconnect_from_error():
    mode = {"ok": False}

    def beh(n, i, b):
        if not mode["ok"]:
            raise CameraOpenError("not_found")
        return FakeCapture(endless=True, delay=0.002)
    cam = make(Factory(beh), max_open_attempts=1)
    cam.start()
    assert cam.wait_for_state(CameraState.ERROR)
    mode["ok"] = True
    cam.reconnect()
    assert cam.wait_for_state(CameraState.RUNNING)
    cam.stop()


def test_reported_and_measured_properties():
    cap = FakeCapture(endless=True, delay=0.01, props=(640, 480, 30.0))
    clock = FakeClock(0.0, step=33.3)
    cam = make(Factory(lambda n, i, b: cap), clock=clock)
    cam.start()
    assert wait_until(lambda: cam.frames_captured >= 5)
    cam.stop()
    assert (cam.reported_width, cam.reported_height, cam.reported_fps) == (640, 480, 30.0)
    assert (cam.measured_width, cam.measured_height) == (640, 480)
    assert 29 < cam.measured_fps < 31


def test_start_is_idempotent_and_callback_errors_ignored():
    def bad_cb(s, e):
        raise RuntimeError("boom")
    f = Factory(lambda n, i, b: FakeCapture(endless=True, delay=0.002))
    cam = make(f, on_state_change=bad_cb)
    cam.start()
    cam.start()
    assert cam.wait_for_state(CameraState.RUNNING)
    cam.stop()
    assert len(f.calls) == 1


@pytest.mark.manual
def test_real_camera_runs():
    cam = Camera()
    cam.start()
    assert cam.wait_for_state({CameraState.RUNNING, CameraState.ERROR}, 10)
    assert cam.state == CameraState.RUNNING, cam.last_error
    cam.stop()
