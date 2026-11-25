"""One click on the pause/resume or camera button must act exactly once, in every mode."""
from __future__ import annotations

from unittest.mock import Mock

import pytest
from test_integration_s import make, qt  # noqa: F401

from handcontrol.contracts import CameraState, ControlState, Mode


@pytest.fixture
def runtime(qt, tmp_path):  # noqa: F811
    cameras = []

    def factory(pipeline, start=True):
        handle = Mock()
        handle.start.side_effect = lambda: pipeline.set_camera_state(CameraState.STARTING)
        cameras.append(handle)
        return handle
    r = make(qt, tmp_path, camera_factory=factory)
    r.cameras = cameras
    yield r
    r.close()


def state(r):
    return r.pipeline.controller.snapshot().state


@pytest.mark.parametrize("mode", list(Mode))
def test_resume_button_resumes_and_pause_button_pauses(runtime, mode):
    runtime.pipeline.set_camera_state(CameraState.RUNNING)
    runtime.pipeline.set_mode(mode)
    assert state(runtime) is ControlState.PAUSED
    runtime.bridge.pause_resume_requested.emit()
    assert state(runtime) is ControlState.ACTIVE
    runtime.bridge.pause_resume_requested.emit()
    assert state(runtime) is ControlState.PAUSED


def camera_state(r):
    return r.pipeline.controller.snapshot().camera_state


def test_camera_button_starts_and_stops(runtime):
    runtime.bridge.camera_toggle_requested.emit()
    assert camera_state(runtime) is CameraState.STARTING and runtime.camera is not None
    runtime.bridge.camera_toggle_requested.emit()
    assert camera_state(runtime) is CameraState.OFF and runtime.camera is None


def test_camera_button_restarts_after_an_error(runtime):
    runtime.bridge.camera_toggle_requested.emit()
    runtime.pipeline.set_camera_state(CameraState.ERROR)
    runtime.bridge.camera_toggle_requested.emit()
    assert camera_state(runtime) is CameraState.STARTING and len(runtime.cameras) == 2


def test_desktop_mode_waits_for_the_user_after_an_automatic_canvas_start(runtime):
    runtime.pipeline.set_camera_state(CameraState.RUNNING)
    for canvas in (Mode.INSTRUMENT, Mode.DRAWING):
        runtime.bridge.select_mode(canvas)
        assert state(runtime) is ControlState.ACTIVE
        runtime.bridge.select_mode(Mode.POINTER)
        assert state(runtime) is ControlState.PAUSED


def test_control_resumed_by_the_user_survives_a_visit_to_a_canvas(runtime):
    runtime.pipeline.set_camera_state(CameraState.RUNNING)
    runtime.bridge.pause_resume_requested.emit()
    runtime.bridge.select_mode(Mode.DRAWING)
    runtime.bridge.select_mode(Mode.SCROLL)
    assert state(runtime) is ControlState.ACTIVE


def test_struck_string_reaches_the_cat(runtime):
    from handcontrol.instrument.events import AllOff, NoteOn
    struck = []
    runtime.instrument.note_played.connect(lambda: struck.append(1))
    runtime.instrument._emit_audio(Mock(spec=NoteOn))
    runtime.instrument._emit_audio(Mock(spec=AllOff))
    assert struck == [1]
