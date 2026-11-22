"""Qt wiring of the Enstrüman mode (round 7). Owned by the manager.

Threads:
- tracking thread: Pipeline frame observer -> InstrumentSession.on_frame -> engine. Audio events go to the
  AudioOutput deque (lock-free append), render states to the GUI through the queued `view_ready` signal.
- any thread (hotkey, watchdog, GUI, tracking): controller listener -> InstrumentSession.on_snapshot, which
  sends AllOff at once when the mode stops being active (pause, emergency stop, mode change, camera error,
  session lock). Mode changes are forwarded to the GUI thread with a queued signal.
- GUI thread: opens/closes the audio stream (only while the mode is INSTRUMENT), owns the window and every
  Qt object, converts the newest camera frame to a QImage at most once per repaint tick.

The controller never sees any of this: in INSTRUMENT mode it produces no actions (only RELEASE_ALL).
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtGui import QImage

from handcontrol.contracts import Handedness, Mode
from handcontrol.instrument.engine import InstrumentConfig, InstrumentEngine
from handcontrol.instrument.events import DEFAULT_FIXED_RECT, DEFAULT_FIXED_STRINGS
from handcontrol.instrument.geometry import normalize_fixed_rect
from handcontrol.instrument.session import InstrumentSession

log = logging.getLogger(__name__)

AUDIO_FAILED_SUFFIX_TR = "Enstrüman modu kapatıldı, kontrol duraklatıldı."
AUDIO_LOAD_FAILED_TR = "Ses motoru yüklenemedi"


def instrument_config(settings: Any) -> InstrumentConfig:
    """Settings (schema 4) -> engine config. The pick hand is the dominant hand."""
    dominant = Handedness.LEFT if getattr(settings, "dominant_hand", "right") == "left" else Handedness.RIGHT
    return InstrumentConfig(
        layout=settings.instrument_layout,
        scale=settings.instrument_scale,
        quantize=bool(settings.instrument_quantize),
        chords=tuple(settings.instrument_chords),
        dominant=dominant,
        fixed_rect=tuple(getattr(settings, "instrument_fixed_rect", DEFAULT_FIXED_RECT)),  # type: ignore[arg-type]
        fixed_strings=int(getattr(settings, "instrument_fixed_strings", DEFAULT_FIXED_STRINGS)),
    )


def _default_synth_factory(settings: Any) -> Any:
    from handcontrol.instrument.synth import GuitarSynth
    return GuitarSynth(volume=float(settings.instrument_volume), tone=settings.instrument_tone)


def _default_audio_factory(synth: Any, settings: Any, on_error: Callable[[str], None]) -> Any:
    from handcontrol.instrument.audio import AudioOutput
    return AudioOutput(synth, device=settings.audio_device, latency=settings.audio_latency, on_error=on_error)


def _default_window_factory(bridge: Any) -> Any:
    from handcontrol.ui.instrument_view import InstrumentWindow
    return InstrumentWindow(bridge)


def frame_to_qimage(frame: Any) -> Optional[QImage]:
    """BGR uint8 HxWx3 array (OpenCV camera frame) -> independent QImage copy, or None."""
    try:
        h, w, c = frame.shape
        if c != 3 or w <= 0 or h <= 0:
            return None
        if not frame.flags["C_CONTIGUOUS"]:
            frame = frame.copy()
        return QImage(frame.data, w, h, 3 * w, QImage.Format.Format_BGR888).copy()
    except Exception:
        return None


class InstrumentRuntime(QObject):
    view_ready = Signal(object)        # InstrumentView (queued to the GUI thread)
    _mode_seen = Signal(object)        # Mode, from any thread
    _audio_failed = Signal(str)        # Turkish message, from the audio side

    def __init__(self, pipeline: Any, settings: Any, *, bridge: Any = None,
                 notify: Optional[Callable[[str], None]] = None,
                 persist: Optional[Callable[[Any], None]] = None,
                 synth_factory: Callable[[Any], Any] = _default_synth_factory,
                 audio_factory: Callable[[Any, Any, Callable[[str], None]], Any] = _default_audio_factory,
                 window_factory: Callable[[Any], Any] = _default_window_factory,
                 repaint_ms: int = 33, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.pipeline = pipeline
        self.settings = settings
        self.bridge = bridge
        self._notify = notify or (lambda text: None)
        self._persist = persist or (lambda settings: None)
        self._was_adjusting = False
        self._synth_factory = synth_factory
        self._audio_factory = audio_factory
        self._window_factory = window_factory
        self.audio: Any = None
        self.window: Any = None
        self._tests: list[Any] = []            # temporary test-tone outputs kept alive until they finish
        self._failing = False
        self._closed = False
        self._last_mode: Optional[Mode] = None
        self._image: Any = None                # newest camera frame (tracking thread writes, GUI reads)
        self._image_seq = 0
        self._image_shown = 0
        self.engine = InstrumentEngine(instrument_config(settings))
        self.session = InstrumentSession(self.engine, self._emit_audio, self.view_ready.emit)
        self._mode_seen.connect(self._on_mode)
        self.view_ready.connect(self._on_view)
        self._audio_failed.connect(self._on_audio_failed)
        self._timer = QTimer(self)
        self._timer.setInterval(max(10, int(repaint_ms)))
        self._timer.timeout.connect(self._push_image)
        pipeline.add_frame_observer(self.session.on_frame)
        pipeline.controller.add_listener(self._on_snapshot)
        self._on_snapshot(pipeline.controller.snapshot())

    # ------------------------------------------------------------ any thread

    def _emit_audio(self, event: Any) -> None:
        audio = self.audio
        if audio is not None:
            audio.push(event)

    def _on_snapshot(self, snap: Any) -> None:
        self.session.on_snapshot(snap)
        if snap.mode is not self._last_mode:
            self._last_mode = snap.mode
            self._mode_seen.emit(snap.mode)

    def tap_image(self, frame: Any, capture_ms: float) -> None:
        """TrackingLoop.on_image: keep only a reference to the newest frame while the window is shown."""
        if self._timer.isActive():
            self._image = frame
            self._image_seq += 1

    # ------------------------------------------------------------ GUI thread

    @property
    def mode_active(self) -> bool:
        return self._last_mode is Mode.INSTRUMENT

    @Slot(object)
    def _on_mode(self, mode: Mode) -> None:
        if self._closed:
            return
        if mode is Mode.INSTRUMENT:
            self._failing = False
            self.open_audio()
            if not self._failing:
                self.show_window()
        else:
            self.close_audio()
            if self.window is not None:
                self.window.hide()
                self._timer.stop()

    def open_audio(self) -> bool:
        if self.audio is not None and self.audio.running:
            return True
        self.close_audio()
        try:
            synth = self._synth_factory(self.settings)
            audio = self._audio_factory(synth, self.settings, self._audio_failed.emit)
        except Exception as exc:          # numpy / sounddevice / PortAudio DLL missing
            log.warning("instrument audio unavailable: %s", exc)
            self._on_audio_failed(f"{AUDIO_LOAD_FAILED_TR}: {exc}")
            return False
        self.audio = audio
        if not audio.start():
            if not self._failing:          # start() normally reported the reason through on_error
                self._on_audio_failed("Ses çıkışı açılamadı.")
            return False
        return True

    def close_audio(self) -> None:
        audio, self.audio = self.audio, None
        if audio is not None:
            try:
                audio.stop()
            except Exception:
                log.debug("audio stop failed", exc_info=True)

    @Slot(str)
    def _on_audio_failed(self, message: str) -> None:
        """Device error: tell the user, stop audio, pause and leave the mode. Desktop control is untouched."""
        if self._failing or self._closed:
            return
        self._failing = True
        self.close_audio()
        self._notify(f"{message} {AUDIO_FAILED_SUFFIX_TR}")
        if self.window is not None:
            self.window.hide()
            self._timer.stop()
        if self._last_mode is Mode.INSTRUMENT:
            self.pipeline.pause("Ses cihazı hatası")
            self.pipeline.set_mode(Mode.POINTER)

    def show_window(self) -> Any:
        if self.window is None:
            self.window = self._window_factory(self.bridge)
            self.view_ready.connect(self.window.update_view)
            closed = getattr(self.window, "closed", None)
            if closed is not None:
                closed.connect(self._timer.stop)
            edited = getattr(self.window, "fixed_rect_changed", None)
            if edited is not None:
                edited.connect(self.set_fixed_rect)
            self._apply_window_settings()
        self.window.show()
        for name in ("raise_", "activateWindow"):
            fn = getattr(self.window, name, None)
            if fn is not None:
                fn()
        self._timer.start()
        return self.window

    def _apply_window_settings(self) -> None:
        w = self.window
        if w is None:
            return
        for name, value in (("set_mirrored", bool(self.settings.mirror_preview)),
                            ("set_particles_enabled", bool(self.settings.instrument_particles))):
            fn = getattr(w, name, None)
            if fn is not None:
                fn(value)

    @Slot(object)
    def _on_view(self, view: Any) -> None:
        """Two-hand placement finished in the engine: keep the new string area in the settings."""
        adjusting = bool(getattr(view, "adjusting", False))
        if self._was_adjusting and not adjusting and getattr(view, "fixed_rect", None) is not None:
            self.set_fixed_rect(view.fixed_rect, reconfigure=False)
        self._was_adjusting = adjusting

    @Slot(object)
    def set_fixed_rect(self, rect: Any, reconfigure: bool = True) -> None:
        """New "Sabit teller" area (window drag or two-hand pinch): apply and save it."""
        if self._closed:
            return
        new = list(normalize_fixed_rect(rect, tuple(self.settings.instrument_fixed_rect)))
        if new == [float(v) for v in self.settings.instrument_fixed_rect]:
            return
        from dataclasses import replace
        self.settings = replace(self.settings, instrument_fixed_rect=new)
        if reconfigure:            # the engine already holds a rect it placed itself
            self.session.configure(instrument_config(self.settings))
        try:
            self._persist(self.settings)
        except Exception:
            log.warning("could not save the string area", exc_info=True)

    @Slot()
    def _push_image(self) -> None:
        if self.window is None or self._image_seq == self._image_shown:
            return
        self._image_shown = self._image_seq
        image = frame_to_qimage(self._image)
        if image is not None:
            self.window.set_camera_image(image)

    def apply_settings(self, settings: Any) -> None:
        previous, self.settings = self.settings, settings
        self.session.configure(instrument_config(settings))
        self._apply_window_settings()
        audio = self.audio
        if audio is None:
            return
        if (previous.audio_device, previous.audio_latency) != (settings.audio_device, settings.audio_latency):
            self.close_audio()
            if self._last_mode is Mode.INSTRUMENT:
                self.open_audio()
            return
        audio.set_volume(float(settings.instrument_volume))
        audio.set_tone(settings.instrument_tone)

    def play_test_tone(self, device: Optional[str] = None) -> bool:
        """Settings dialog button: use the running stream when it plays on that device, else a temporary one."""
        dev = self.settings.audio_device if device is None else device
        audio = self.audio
        if audio is not None and audio.running and dev == self.settings.audio_device:
            return bool(audio.play_test_tone())
        self._tests = [t for t in self._tests if getattr(t, "running", False)]
        try:
            from dataclasses import replace
            temp_settings = replace(self.settings, audio_device=dev)
            tmp = self._audio_factory(self._synth_factory(temp_settings), temp_settings,
                                      lambda text: self._notify(f"Test sesi çalınamadı: {text}"))
        except Exception as exc:
            self._notify(f"Test sesi çalınamadı: {exc}")
            return False
        self._tests.append(tmp)
        return bool(tmp.play_test_tone())

    def stats(self) -> dict[str, Any]:
        audio = self.audio
        return {"session": self.session.stats(), "audio": audio.stats() if audio is not None else None}

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._timer.stop()
        try:
            self.session.stop()
        except Exception:
            log.debug("session stop failed", exc_info=True)
        self.close_audio()
        for tmp in self._tests:
            try:
                tmp.stop()
            except Exception:
                pass
        self._tests.clear()
        if self.window is not None:
            try:
                self.window.close()
            except Exception:
                pass


__all__ = ["InstrumentRuntime", "frame_to_qimage", "instrument_config"]
