"""Round 7: Enstrüman mode wiring in the app (InstrumentRuntime + Runtime). Fake audio and window; no devices."""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from handcontrol.app import Runtime, dialog_data_to_values, settings_to_dialog_data
from handcontrol.config import Settings, validate
from handcontrol.contracts import (ActionKind, CameraState, ControlState, FingerInfo, FingerName, FingerState,
                                   FrameFeatures, HandFeatures, Handedness, Landmark, Mode, Quality)
from handcontrol.dryrun import FakeDisplays, FakeVolume, FakeWindows
from handcontrol.instrument.events import AllOff, NoteOn
from handcontrol.instrument_runtime import InstrumentRuntime, frame_to_qimage, instrument_config
from handcontrol.ui import SettingsData, UiBridge


@pytest.fixture
def qt():
    return QApplication.instance() or QApplication([])


class FakeAudio:
    instances: list["FakeAudio"] = []

    def __init__(self, synth, settings, on_error, ok=True):
        self.synth, self.settings, self.on_error, self.ok = synth, settings, on_error, ok
        self.running = False
        self.events: list = []
        self.started = self.stopped = self.tones = 0
        self.volume = self.tone = None
        FakeAudio.instances.append(self)

    def start(self):
        self.started += 1
        if not self.ok:
            self.on_error("Ses çıkışı açılamadı: test")
            return False
        self.running = True
        return True

    def stop(self):
        self.stopped += 1
        self.running = False

    def push(self, event):
        self.events.append(event)

    def set_volume(self, v):
        self.volume = v

    def set_tone(self, t):
        self.tone = t

    def play_test_tone(self):
        self.tones += 1
        return True

    def stats(self):
        return SimpleNamespace(running=self.running)


class FakeWindow(QObject):
    closed = Signal()

    def __init__(self, bridge):
        super().__init__()
        self.bridge = bridge
        self.views: list = []
        self.images: list = []
        self.visible = False
        self.mirrored = self.particles = None

    def update_view(self, view):
        self.views.append(view)

    def set_camera_image(self, image):
        self.images.append(image)

    def set_mirrored(self, v):
        self.mirrored = v

    def set_particles_enabled(self, v):
        self.particles = v

    def show(self):
        self.visible = True

    def hide(self):
        self.visible = False

    def close(self):
        self.visible = False


def make_runtime(qt, *, audio_ok=True, settings=None, notes=None):
    FakeAudio.instances = []
    displays = FakeDisplays()
    displays.start = Mock()
    displays.close = Mock()
    notes = notes if notes is not None else []
    store = SimpleNamespace(load=lambda: settings or Settings(instrument_layout="solo"), save=Mock())

    def factory(rt):
        return InstrumentRuntime(rt.pipeline, rt.settings, bridge=rt.bridge, notify=notes.append,
                                 persist=rt.save_instrument_area,
                                 synth_factory=lambda s: SimpleNamespace(settings=s),
                                 audio_factory=lambda synth, s, err: FakeAudio(synth, s, err, ok=audio_ok),
                                 window_factory=FakeWindow, parent=rt)
    rt = Runtime(UiBridge(), store, displays=displays, windows=FakeWindows(), volume=FakeVolume(),
                 session_factory=Mock(), instrument_factory=factory)
    return rt, notes


def activate_instrument(rt):
    rt.pipeline.set_camera_state(CameraState.RUNNING)
    assert rt.pipeline.resume()
    rt.pipeline.set_mode(Mode.INSTRUMENT)
    QApplication.processEvents()


def _hand(hid, side, thumb, index, palm, scale=100.0):
    pts = [palm] * 21
    pts[4], pts[8] = thumb, index
    lms = tuple(Landmark(x / 640, y / 480) for x, y in pts)
    fingers = tuple(FingerInfo(n, FingerState.EXTENDED, 0.0) for n in FingerName)
    d = ((thumb[0] - index[0]) ** 2 + (thumb[1] - index[1]) ** 2) ** 0.5 / scale
    return HandFeatures(hid, side, Quality.USABLE, palm, scale, fingers, d, index, lms)


def _frame(t, tip_y):
    s = _hand(1, Handedness.LEFT, (250.0, 250.0), (380.0, 250.0), (300.0, 380.0))
    p = _hand(2, Handedness.RIGHT, (355.0, tip_y + 50), (315.0, tip_y), (435.0, tip_y + 60))
    return FrameFeatures(t, t + 5, 640, 480, (s, p), False)


def test_audio_and_window_follow_the_mode(qt):
    rt, _ = make_runtime(qt)
    try:
        ins = rt.instrument
        assert ins.audio is None and ins.window is None and FakeAudio.instances == []
        activate_instrument(rt)
        audio = ins.audio
        assert audio.running and audio.started == 1 and ins.window.visible
        assert ins.window.mirrored is True and ins.window.particles is True
        rt.pipeline.set_mode(Mode.SCROLL)
        QApplication.processEvents()
        assert ins.audio is None and audio.stopped == 1 and not audio.running and not ins.window.visible
        assert any(isinstance(e, AllOff) for e in audio.events)
    finally:
        rt.close()


@pytest.mark.parametrize("stop", ["pause", "emergency", "camera_error", "session_lock", "mode"])
def test_every_stop_path_sends_allof_at_once(qt, stop):
    rt, _ = make_runtime(qt)
    try:
        activate_instrument(rt)
        audio = rt.instrument.audio
        audio.events.clear()
        {"pause": lambda: rt.pipeline.pause("test"), "emergency": rt.pipeline.emergency_stop,
         "camera_error": lambda: rt.pipeline.set_camera_state(CameraState.ERROR),
         "session_lock": lambda: rt._session_event("lock"),
         "mode": lambda: rt.pipeline.set_mode(Mode.POINTER)}[stop]()
        # AllOff is pushed synchronously from the controller listener (no frame, no event loop needed)
        offs = [e for e in audio.events if isinstance(e, AllOff)]
        assert len(offs) == 1 and offs[0].fade_ms == pytest.approx(20.0)
    finally:
        rt.close()


def test_strikes_reach_audio_and_view_while_sink_gets_no_input(qt):
    rt, _ = make_runtime(qt)
    try:
        activate_instrument(rt)
        ins = rt.instrument
        snap = rt.pipeline.controller.snapshot()
        assert snap.state is ControlState.ACTIVE and snap.mode is Mode.INSTRUMENT
        t0 = 1000.0
        for i, y in enumerate([150, 180, 210, 240, 270, 300, 330]):
            ins.session.on_frame(_frame(t0 + 33 * i, float(y)), (), rt.pipeline.controller.snapshot())
        QApplication.processEvents()
        notes = [e for e in ins.audio.events if isinstance(e, NoteOn)]
        assert len(notes) == 1 and 0 < notes[0].velocity <= 1
        assert ins.window.views and ins.window.views[-1].layout == "solo"
        assert any(v.hits for v in ins.window.views)
        kinds = set(rt.sink.inner.kinds())
        assert ActionKind.RELEASE_ALL in kinds and kinds <= {ActionKind.RELEASE_ALL}
    finally:
        rt.close()


def test_audio_failure_keeps_the_strings_notifies_once_and_retries(qt):
    rt, notes = make_runtime(qt, audio_ok=False)
    try:
        activate_instrument(rt)
        QApplication.processEvents()
        ins = rt.instrument
        snap = rt.pipeline.controller.snapshot()
        assert snap.mode is Mode.INSTRUMENT and snap.state is ControlState.ACTIVE
        assert ins.audio is None and ins.window.visible and ins.window.views
        assert len(notes) == 1 and "Ses çıkışı açılamadı" in notes[0]
        assert ins._retry.isActive()
        ins._retry_audio()                                    # still broken: no second toast
        assert len(notes) == 1 and ins._retry.isActive()
        ins._audio_factory = lambda synth, s, err: FakeAudio(synth, s, err)
        ins._retry_audio()                                    # device is back
        assert ins.audio.running
        rt.pipeline.set_mode(Mode.POINTER)
        QApplication.processEvents()
        assert ins.audio is None and not ins._retry.isActive()
    finally:
        rt.close()


def test_audio_device_error_while_playing(qt):
    rt, notes = make_runtime(qt)
    try:
        activate_instrument(rt)
        audio = rt.instrument.audio
        audio.on_error("Ses cihazı hatası: çıkarıldı")
        QApplication.processEvents()
        audio.on_error("Ses cihazı hatası: çıkarıldı")    # a second report is ignored
        QApplication.processEvents()
        snap = rt.pipeline.controller.snapshot()
        assert snap.mode is Mode.INSTRUMENT and audio.stopped >= 1 and rt.instrument.audio is None
        assert rt.instrument._retry.isActive() and len(notes) == 1
    finally:
        rt.close()


def test_choosing_the_instrument_starts_it_even_before_the_camera_runs(qt):
    """Regression: the first opening showed no (or dead) strings because control was still paused."""
    cam = SimpleNamespace(loop=SimpleNamespace(on_image=None, stop=Mock()), camera=Mock(), start=Mock())
    rt, _ = make_runtime(qt, settings=Settings(instrument_free_strings=[[0.1, 0.2, 0.5, 0.2]]))
    try:
        rt.camera_factory = lambda pipeline, start=False: cam
        rt.bridge.select_mode(Mode.INSTRUMENT)
        QApplication.processEvents()
        assert cam.start.called                                             # camera was off: started
        assert rt.pipeline.controller.snapshot().state is ControlState.PAUSED
        assert len(rt.instrument.window.views[-1].strings) == 1             # saved strings at once, no frame needed
        rt.pipeline.set_camera_state(CameraState.RUNNING)
        QApplication.processEvents()
        assert rt.pipeline.controller.snapshot().state is ControlState.ACTIVE
        rt.pipeline.pause("test")                                           # an explicit pause stays paused
        QApplication.processEvents()
        assert rt.pipeline.controller.snapshot().state is ControlState.PAUSED
    finally:
        rt.close()


def test_pending_start_is_cancelled_by_another_mode_or_emergency(qt):
    rt, _ = make_runtime(qt)
    try:
        rt.camera = SimpleNamespace(loop=Mock(), camera=Mock())
        for cancel in (lambda: rt.bridge.select_mode(Mode.POINTER), rt._emergency):
            rt.bridge.select_mode(Mode.INSTRUMENT)
            cancel()
            rt.pipeline.set_camera_state(CameraState.RUNNING)
            QApplication.processEvents()
            assert rt.pipeline.controller.snapshot().state is ControlState.PAUSED
            rt.pipeline.set_camera_state(CameraState.OFF)
            rt.pipeline.set_mode(Mode.POINTER)
            QApplication.processEvents()
    finally:
        rt.close()


def test_default_instrument_mode_waits_for_the_main_window(qt):
    """Regression: with default mode = Enstrüman the runtime opened its own window before the main one."""
    rt, _ = make_runtime(qt, settings=Settings(default_mode="instrument"))
    try:
        assert rt.instrument.window is None
        page = FakeWindow(None)
        rt.instrument.attach(page)
        QApplication.processEvents()
        assert rt.instrument.window is page and not page.visible            # a page, never shown on its own
        assert page.views and rt.instrument.audio.running
    finally:
        rt.close()


def test_instrument_bar_changes_apply_without_pausing(qt):
    rt, _ = make_runtime(qt)
    try:
        activate_instrument(rt)
        seen = []
        rt.settings_changed.connect(seen.append)
        rt.update_instrument({"instrument_layout": "free", "instrument_volume": 0.8, "instrument_tone": "electric"})
        ins = rt.instrument
        assert ins.engine.config.layout == "free" and ins.audio.volume == 0.8 and ins.audio.tone == "electric"
        assert rt.settings.instrument_layout == "free" and rt.store.save.called and seen == [rt.settings]
        assert rt.pipeline.controller.snapshot().state is ControlState.ACTIVE
    finally:
        rt.close()


def test_settings_apply_volume_tone_and_device_restart(qt):
    rt, _ = make_runtime(qt)
    try:
        activate_instrument(rt)
        ins = rt.instrument
        first = ins.audio
        ins.apply_settings(replace(rt.settings, instrument_volume=0.8, instrument_tone="electric",
                                   instrument_layout="chord", instrument_particles=False))
        assert ins.audio is first and first.volume == 0.8 and first.tone == "electric"
        assert ins.engine.config.layout == "chord" if hasattr(ins.engine, "config") else True
        assert ins.window.particles is False
        ins.apply_settings(replace(ins.settings, audio_device="USB Kulaklık"))
        assert first.stopped == 1 and ins.audio is not first and ins.audio.running
        assert ins.audio.settings.audio_device == "USB Kulaklık"
    finally:
        rt.close()


def test_test_tone_uses_running_stream_or_a_temporary_one(qt):
    rt, _ = make_runtime(qt)
    try:
        ins = rt.instrument
        assert ins.play_test_tone("") is True
        tmp = FakeAudio.instances[-1]
        assert tmp.tones == 1 and ins.audio is None
        activate_instrument(rt)
        assert ins.play_test_tone("") is True and ins.audio.tones == 1
        assert ins.play_test_tone("Başka cihaz") is True
        assert FakeAudio.instances[-1].settings.audio_device == "Başka cihaz"
    finally:
        rt.close()


def test_camera_image_tap_only_while_window_shown(qt):
    rt, _ = make_runtime(qt)
    try:
        ins = rt.instrument
        frame = np.zeros((48, 64, 3), dtype=np.uint8)
        frame[:, :, 2] = 255                                  # BGR red
        ins.tap_image(frame, 1.0)
        assert ins._image is None                             # no window: nothing kept
        ins.show_window()
        ins.tap_image(frame, 2.0)
        ins._push_image()
        ins._push_image()                                     # same frame is not converted twice
        assert len(ins.window.images) == 1
        img = ins.window.images[0]
        assert (img.width(), img.height()) == (64, 48) and img.pixelColor(3, 3).red() == 255
        assert frame_to_qimage(np.zeros((4, 4), dtype=np.uint8)) is None
    finally:
        rt.close()


def test_camera_loop_gets_the_image_tap(qt):
    loop = SimpleNamespace(on_image=None, stop=Mock())
    cam = SimpleNamespace(loop=loop, camera=Mock(), start=Mock())
    rt, _ = make_runtime(qt)
    try:
        rt.camera_factory = lambda pipeline, start=False: cam
        rt.start_camera()
        assert loop.on_image == rt.instrument.tap_image
    finally:
        rt.close()


def test_saving_settings_keeps_instrument_mode_and_restarts_camera(qt):
    """Regression: saving the Enstrüman tab (e.g. tone -> Elektro) stopped the camera and left the mode."""
    cams = []

    def camera_factory(pipeline, start=False):
        cam = SimpleNamespace(loop=SimpleNamespace(on_image=None, stop=Mock()), camera=Mock(), start=Mock())
        cams.append(cam)
        return cam

    rt, _ = make_runtime(qt)
    try:
        rt.camera_factory = camera_factory
        rt.start_camera()
        activate_instrument(rt)
        window = rt.instrument.window
        rt.apply_settings(replace(rt.settings, instrument_tone="electric"))
        QApplication.processEvents()
        assert rt.pipeline.controller.snapshot().mode is Mode.INSTRUMENT
        assert len(cams) == 2 and rt.camera is cams[1] and cams[1].start.called
        assert cams[0].loop.stop.called and cams[1].loop.on_image == rt.instrument.tap_image
        assert rt.instrument.audio is not None and rt.instrument.audio.tone == "electric"
        assert window.visible
        rt.apply_settings(replace(rt.settings, default_mode="scroll"))   # other modes: old behaviour
        rt.pipeline.set_mode(Mode.POINTER)
        rt.apply_settings(rt.settings)
        assert rt.pipeline.controller.snapshot().mode is Mode.SCROLL
    finally:
        rt.close()


def test_close_stops_audio_and_window(qt):
    rt, _ = make_runtime(qt)
    activate_instrument(rt)
    audio, window = rt.instrument.audio, rt.instrument.window
    rt.close()
    assert not audio.running and not window.visible
    assert any(isinstance(e, AllOff) for e in audio.events)


def test_instrument_config_from_settings_and_dialog_round_trip():
    s = validate({"instrument_layout": "chord", "instrument_scale": "a_minor", "instrument_quantize": False,
                  "instrument_chords": ["Am", "F", "C", "G"], "dominant_hand": "left",
                  "instrument_volume": 0.3, "instrument_tone": "electric", "audio_device": "X",
                  "audio_latency": "normal", "instrument_particles": False})
    cfg = instrument_config(s)
    assert (cfg.layout, cfg.scale, cfg.quantize, tuple(cfg.chords)) == ("chord", "a_minor", False, ("Am", "F", "C", "G"))
    assert cfg.dominant is Handedness.LEFT and instrument_config(Settings()).dominant is Handedness.RIGHT
    data = settings_to_dialog_data(s)
    assert isinstance(data, SettingsData) and data.instrument_chords == ("Am", "F", "C", "G")
    values = dialog_data_to_values({}, data)
    assert list(values["instrument_chords"]) == ["Am", "F", "C", "G"] and "audio_device_choices" not in values
    back = validate({**values, "dominant_hand": "left"})
    for key in ("instrument_layout", "instrument_scale", "instrument_quantize", "instrument_chords",
                "instrument_volume", "instrument_tone", "audio_device", "audio_latency", "instrument_particles"):
        assert getattr(back, key) == getattr(s, key), key


def test_fixed_area_from_window_or_pinch_is_applied_and_saved(qt):
    rt, _ = make_runtime(qt, settings=Settings(instrument_layout="fixed"))
    try:
        ins = rt.instrument
        assert ins.engine.config.layout == "fixed"
        rt.store.save.reset_mock()
        ins.set_fixed_rect((0.1, 0.2, 0.5, 0.6))                     # mouse drag in the window
        assert ins.engine.config.fixed_rect == (0.1, 0.2, 0.5, 0.6)
        assert rt.settings.instrument_fixed_rect == [0.1, 0.2, 0.5, 0.6]
        assert rt.store.save.call_count == 1
        ins.set_fixed_rect((0.1, 0.2, 0.5, 0.6))                     # unchanged: nothing saved
        assert rt.store.save.call_count == 1
        # two-hand pinch: saved when the engine reports the end of the adjustment, engine not reset
        done = SimpleNamespace(adjusting=False, fixed_rect=(0.3, 0.3, 0.9, 0.8))
        ins._on_view(SimpleNamespace(adjusting=True, fixed_rect=(0.3, 0.3, 0.9, 0.7)))
        assert rt.store.save.call_count == 1
        ins._on_view(done)
        assert rt.settings.instrument_fixed_rect == [0.3, 0.3, 0.9, 0.8] and rt.store.save.call_count == 2
        assert ins.engine.config.fixed_rect == (0.1, 0.2, 0.5, 0.6)    # engine keeps the rect it placed
        ins._on_view(done)
        assert rt.store.save.call_count == 2
        # dialog save keeps the area and passes the string count
        rt.apply_settings(replace(rt.settings, instrument_fixed_strings=4))
        assert ins.engine.config.fixed_strings == 4 and ins.engine.config.fixed_rect == (0.3, 0.3, 0.9, 0.8)
    finally:
        rt.close()


def test_free_strings_from_window_or_gesture_are_applied_and_saved(qt):
    rt, _ = make_runtime(qt, settings=Settings(instrument_layout="free"))
    try:
        ins = rt.instrument
        assert ins.engine.config.layout == "free" and ins.engine.config.free_strings == ()
        rt.store.save.reset_mock()
        ins.set_free_strings(((0.1, 0.2, 0.5, 0.2),))                 # mouse edit in the window
        assert ins.engine.config.free_strings == ((0.1, 0.2, 0.5, 0.2),)
        assert rt.settings.instrument_free_strings == [[0.1, 0.2, 0.5, 0.2]] and rt.store.save.call_count == 1
        # hand gesture: saved when the engine reports the end of the edit
        two = ((0.1, 0.2, 0.5, 0.2), (0.1, 0.3, 0.5, 0.3))
        ins._on_view(SimpleNamespace(layout="free", adjusting=True, fixed_rect=None, free_strings=two))
        ins._on_view(SimpleNamespace(layout="free", adjusting=False, fixed_rect=None, free_strings=two))
        assert len(rt.settings.instrument_free_strings) == 2 and rt.store.save.call_count == 2
        # dialog save keeps the strings and passes the snap switch
        rt.apply_settings(replace(rt.settings, instrument_free_snap=False))
        assert ins.engine.config.free_snap is False and len(ins.engine.config.free_strings) == 2
    finally:
        rt.close()
