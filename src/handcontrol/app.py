"""Desktop composition root. Real OS output requires explicit --live opt-in."""
from __future__ import annotations

import argparse
import ctypes
import json
import logging
import sys
from dataclasses import asdict, fields, replace
from pathlib import Path
from typing import Any, Callable, Optional

from PySide6.QtCore import QLockFile, QObject, Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import QApplication

from handcontrol.background import MonotonicClock
from handcontrol.config import CalibrationBounds, Settings, SettingsStore, app_data_dir, migrate, validate
from handcontrol.contracts import CANVAS_MODES, CameraState, ControlState, Mode
from handcontrol.controller import MenuKind
from handcontrol.dryrun import DryRunSink, FakeVolume
from handcontrol.gestures import GestureRecognizer
from handcontrol.pipeline import (Pipeline, calibration_rect, controller_config, dominant_of, gesture_config,
    run_camera_pipeline)
from handcontrol.telemetry import SessionRecorder, TelemetrySink
from handcontrol.ui import (UiBridge, UiState, OverlayState, OverlayMenuKind,
    OverlayMenuItem, VirtualCursorState, HandControlTray,
    OverlayWindow, CursorFeedbackOverlay, FeedbackToast, StatusIndicator, DryRunPanel, SettingsDialog, SettingsData, CalibrationWizard)
from handcontrol.windows import (enable_per_monitor_v2, WindowsDisplayProvider,
    WindowsWindowQuery, WindowsVolumeControl, WindowsActionSink, WindowsHotkey, WindowsSession)
from handcontrol.windows import startup as windows_startup
from handcontrol.windows.hotkey import HotkeyConflictError


def hotkey_binding(text: str) -> tuple[int, int]:
    parts = text.upper().split('+')
    modifiers = 0
    for part in parts[:-1]:
        flag = {'CTRL': 2, 'ALT': 1, 'SHIFT': 4, 'WIN': 8}.get(part.strip())
        if flag is None:
            raise ValueError('Geçersiz acil durdurma kısayolu')
        modifiers |= flag
    key = parts[-1]
    if key.startswith('F') and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        return modifiers, 0x70 + int(key[1:]) - 1
    if len(key) == 1 and key.isascii() and key.isalnum():
        return modifiers, ord(key)
    raise ValueError('Geçersiz acil durdurma kısayolu')


CursorSource = Callable[[], Optional[tuple[int, int]]]


def read_os_cursor(*, api: Any = None) -> Optional[tuple[int, int]]:
    """Real OS cursor in physical px via GetCursorPos; None ("unknown") on any failure."""
    try:
        from handcontrol.windows._win32 import POINT, user32
        point = POINT()
        if not (api if api is not None else user32()).GetCursorPos(ctypes.byref(point)):
            return None
        return int(point.x), int(point.y)
    except Exception:
        return None


log = logging.getLogger(__name__)

STARTUP_SOURCE_TR = 'Windows ile başlatma yalnızca paketlenmiş sürümde kullanılabilir'
STARTUP_FAILED_TR = 'Windows ile başlatma ayarı değiştirilemedi'


_DIRECTIONS = {'natural': 'normal', 'reverse': 'reversed'}           # dialog value -> stored value
_BACKENDS = {'media_foundation': 'msmf', 'directshow': 'dshow'}
_MONITORS = {'all': ('virtual_desktop', 0), 'primary': ('primary', 0), 'secondary': ('monitor', 1)}
# dialog field -> stored field, where the values are the same
_SAME = {f.name: f.name for f in fields(SettingsData) if f.name in {s.name for s in fields(Settings)} - {
    'scroll_direction', 'zoom_direction', 'monitor_mapping', 'start_with_windows'}}
_SAME |= {'mirror': 'mirror_preview', 'pointer_sensitivity': 'sensitivity', 'show_overlay': 'overlay_visible',
    'show_mascot': 'mascot_visible'}


def _key_of(table: dict, value, default: str) -> str:
    return next((k for k, v in table.items() if v == value), default)


def audio_device_names() -> tuple[str, ...]:
    """Output device names for the settings dialog; () when the audio backend is unavailable."""
    try:
        from handcontrol.instrument.audio import list_output_devices
        names: list[str] = []
        for dev in list_output_devices():
            if dev.name not in names:
                names.append(dev.name)
        return tuple(names)
    except Exception:
        return ()


def settings_to_dialog_data(s, *, startup_enabled: bool | None = None) -> SettingsData:
    """Map stored Settings to dialog values so saving does not reset untouched fields.

    startup_enabled overrides the stored flag with the real registry state when known."""
    return SettingsData(**{k: getattr(s, stored) for k, stored in _SAME.items()},
        camera_index=s.camera.index, camera_backend=_key_of(_BACKENDS, s.camera.backend, 'media_foundation'),
        scroll_direction=_key_of(_DIRECTIONS, s.scroll_direction, 'natural'),
        zoom_direction=_key_of(_DIRECTIONS, s.zoom_direction, 'natural'),
        monitor_mapping=_key_of(_MONITORS, (s.monitor_mapping.mode, s.monitor_mapping.monitor_index),
            'primary' if s.monitor_mapping.mode == 'primary' else 'all'),
        start_with_windows=s.start_with_windows if startup_enabled is None else startup_enabled)


def dialog_data_to_values(values: dict, data) -> dict:
    """Write the dialog fields into a settings dict (validate() checks the result)."""
    values.update({stored: getattr(data, k) for k, stored in _SAME.items()})
    values.update(scroll_direction=_DIRECTIONS[data.scroll_direction], zoom_direction=_DIRECTIONS[data.zoom_direction],
        monitor_mapping=dict(zip(('mode', 'monitor_index'), _MONITORS[data.monitor_mapping])))
    values['camera'] = {**values.get('camera', {}), 'index': data.camera_index, 'backend': _BACKENDS.get(data.camera_backend, 'auto')}
    return values


def snapshot_to_viewmodel(snapshot, *, dry_run: bool = True, mirrored: bool = True) -> UiState:
    menu = snapshot.menu
    overlay = OverlayState()
    if menu:
        items = tuple(OverlayMenuItem(item.key, item.label, item.enabled, item.selected,
            index == menu.hovered, item.key == 'close' and menu.close_armed,
            menu.hold_progress if item.key == 'close' else 0) for index, item in enumerate(menu.items))
        overlay = OverlayState(visible=True,
            kind=OverlayMenuKind.MODE_MENU if menu.kind == MenuKind.MODE else OverlayMenuKind.WINDOW_ACTION_MENU,
            title='Mod Çarkı' if menu.kind == MenuKind.MODE else 'Pencere Eylemleri', items=items,
            cursor=VirtualCursorState(*menu.pointer, visible=True, hold_progress=menu.hold_progress),
            inactivity_ms=max(0, 5000 - menu.remaining_ms))
    elif snapshot.menu_dwell >= 0.2:          # V held: the ring that fills before the wheel opens
        overlay = OverlayState(visible=True, kind=OverlayMenuKind.MODE_MENU,
            cursor=VirtualCursorState(hold_progress=snapshot.menu_dwell))
    return UiState(control_state=snapshot.state, camera_state=snapshot.camera_state,
        mode=snapshot.mode, overlay=overlay,
        error_text=snapshot.last_fault_reason or snapshot.notice, dry_run=dry_run, mirrored=mirrored)


class EpochSink:
    """Synchronize the native sink before dispatch, including same-frame epochs."""
    def __init__(self, inner, bridge):
        self.inner, self.bridge = inner, bridge

    def set_epoch(self, epoch):
        setter = getattr(self.inner, 'set_epoch', None)
        if setter:
            setter(epoch)

    def dispatch(self, action):
        self.set_epoch(action.epoch)
        result = self.inner.dispatch(action)
        if isinstance(self.inner, DryRunSink):
            self.bridge.record_dry_run_action(action)
        return result

    def release_all(self):
        self.inner.release_all()

    def close(self):
        self.release_all()
        close = getattr(self.inner, 'close', None)
        if close:
            close()


CLICK_KINDS = ('left_click', 'right_click', 'double_click')


def sound_kind_for(kind: str) -> str | None:
    if kind in CLICK_KINDS:
        return 'click'
    return 'command' if kind == 'key_command' else None


class TapSink:
    """Forward dispatch() unchanged; report successfully dispatched actions to a callback.

    Sits below the controller's GuardedSink, so epoch/age-rejected actions never reach it, and a falsy
    inner result is not reported. Runs on the pipeline thread: the callback must be thread-safe."""
    def __init__(self, inner, on_action):
        self._inner, self._on_action = inner, on_action

    def dispatch(self, action):
        result = self._inner.dispatch(action)
        if result:
            try:
                kind = getattr(action.kind, 'value', str(action.kind))
                self._on_action(kind, int(action.x or 0), int(action.y or 0))
            except Exception:
                log.debug('action tap failed', exc_info=True)
        return result

    def __getattr__(self, name):
        return getattr(self._inner, name)


def fan_out(taps):
    """One image tap for several readers; a failing reader must not silence the others."""
    if len(taps) < 2:
        return taps[0] if taps else None

    def tap(frame, capture_ms):
        for t in taps:
            try:
                t(frame, capture_ms)
            except Exception:
                log.debug('image tap failed', exc_info=True)
    return tap


def make_process_names():
    """Read-only process name lookup; None when the windows layer does not provide it yet."""
    try:
        from handcontrol.windows.process import WindowsProcessNames
        return WindowsProcessNames()
    except Exception:
        return None


def acquire_single_instance(lock_dir: Path | None = None):
    """Return a held QLockFile, or None when another instance already runs."""
    lock_dir = lock_dir or app_data_dir()
    try:
        Path(lock_dir).mkdir(parents=True, exist_ok=True)
        lock = QLockFile(str(Path(lock_dir) / 'holoscobe.lock'))
    except OSError as exc:
        print(f'Tek örnek kilidi oluşturulamadı, kilitsiz devam ediliyor: {exc}', file=sys.stderr)
        return _NO_LOCK
    lock.setStaleLockTime(0)  # a lock whose process is gone is stale at once
    return lock if lock.tryLock(0) else None


class _NoLock:
    """Stand-in when the lock file cannot be created: the app runs without single-instance protection."""
    def unlock(self) -> None:
        pass


_NO_LOCK = _NoLock()


class ErrorNotifier(QObject):
    """Thread-safe error toast: notify() may be called from any thread; show_fn runs on this object's (GUI) thread."""
    error = Signal(str)

    def __init__(self, show_fn=None, parent=None):
        super().__init__(parent)
        self.show_fn = show_fn
        self.error.connect(self._show)

    def notify(self, text: str) -> None:
        self.error.emit(text)

    @Slot(str)
    def _show(self, text: str) -> None:
        if self.show_fn is not None:
            self.show_fn(text)


ALREADY_RUNNING_TR = 'Holoscobe zaten çalışıyor'
IMPORT_FAILED_TR = 'Ayarlar içe aktarılamadı'
EXPORT_FAILED_TR = 'Ayarlar dışa aktarılamadı'


class Runtime(QObject):
    """Own services; workers emit data, GUI slots own widget changes."""
    snapshot_received = Signal(object)
    action_performed = Signal(str, int, int)   # queued to the GUI thread
    settings_changed = Signal(object)          # Settings, after any change (GUI thread)

    def __init__(self, bridge, store, *, live=False, displays=None, windows=None,
                 volume=None, hotkey_factory=WindowsHotkey, session_factory=WindowsSession,
                 sink_factory=WindowsActionSink, camera_factory=run_camera_pipeline,
                 startup=windows_startup, packaged: bool | None = None,
                 cursor_source: CursorSource | None = None, telemetry: SessionRecorder | None = None,
                 process_names=None, sound_player=None, logs_dir: Path | None = None,
                 instrument_factory: Callable[['Runtime'], Any] | None = None):
        super().__init__()
        self.telemetry = telemetry
        self.process_names = process_names if process_names is not None else make_process_names()
        self.sound_player = sound_player
        self.logs_dir = logs_dir
        self.action_listeners: list = []
        self.bridge, self.store, self.live = bridge, store, live
        # Relative pointer starts from, and re-syncs to, the real cursor; injected in tests.
        self.cursor_source: CursorSource = cursor_source if cursor_source is not None else read_os_cursor
        # startup provides is_enabled()/set_enabled(); injected so tests never touch the registry.
        self.startup = startup
        self.packaged = getattr(sys, 'frozen', False) if packaged is None else packaged
        self.settings = store.load()
        self.displays = displays if displays is not None else WindowsDisplayProvider()
        self.windows = windows if windows is not None else WindowsWindowQuery(self.displays)
        self.volume = volume if volume is not None else (WindowsVolumeControl() if live else FakeVolume())
        self.camera_factory = camera_factory
        self.camera = None
        self.hotkey = self.session = self.pipeline = self.sink = None
        self.instrument = None
        self.image_taps: list[Callable[[Any, float], None]] = []   # extra camera image readers (the cat)
        self.closed = False
        self._auto_active = False              # control runs because a canvas mode started it, not the user
        self._auto_resume = False              # start the instrument as soon as the camera runs
        self.timer = QTimer(self)
        self.snapshot_received.connect(self._snapshot)
        self.action_performed.connect(self._dispatch_action_listeners)
        try:
            self.hotkey = hotkey_factory(self._emergency)
            try:
                self.hotkey.start(*hotkey_binding(self.settings.emergency_hotkey))
            except (HotkeyConflictError, ValueError, KeyError) as exc:
                if live:
                    raise RuntimeError('Canlı kontrol reddedildi: acil durdurma kısayolu kaydedilemedi') from exc
                bridge.show_feedback(message='Acil durdurma kısayolu kullanılamıyor; komutsuz deneme sürüyor')
            inner = sink_factory(displays=self.displays, windows=self.windows, volume=self.volume) if live else DryRunSink(max_history=200)
            self.sink = EpochSink(inner, bridge)
            tap = TapSink(self.sink, self.action_performed.emit)
            pipeline_sink = TelemetrySink(tap, telemetry) if telemetry else tap
            self.pipeline = Pipeline(MonotonicClock(), pipeline_sink, self.displays, self.windows, self.volume,
                self.settings, cursor_source=self.cursor_source, process_names=self.process_names)
            self.pipeline.controller._cfg = controller_config(self.settings, camera_error_paused=True)
            self.pipeline.controller.add_listener(self._on_snapshot)
            if telemetry:
                telemetry.dominant = lambda: dominant_of(self.settings)
                self.pipeline.add_frame_observer(telemetry.on_frame)
            # Enstrüman mode: audio + window, fed by a frame observer; the controller only knows the mode.
            self.instrument = (instrument_factory or _make_instrument)(self)
            self.pipeline.start()
            self.session = session_factory(self._session_event)
            self.session.start()
            self.displays.start(lambda _: self.pipeline.controller.on_display_change())
            self.timer.timeout.connect(self.pipeline.tick)
            self.timer.start(50)
            self._connect()
            self._on_snapshot(self.pipeline.controller.snapshot())
        except Exception:
            self.close()
            raise

    def _connect(self):
        b, p = self.bridge, self.pipeline
        b.pause_resume_requested.connect(self.toggle_pause)
        b.mode_selected.connect(self.select_mode)
        b.camera_toggle_requested.connect(self.toggle_camera)
        b.settings_saved.connect(self.save_settings)
        b.calibration_completed.connect(self.calibrated)
        b.calibration_cancelled.connect(p.controller.end_calibration)

    @Slot(object)
    def select_mode(self, mode):
        """Mode picked with the mouse (window button or tray)."""
        self._auto_resume = False
        self.pipeline.set_mode(mode)
        if mode in CANVAS_MODES:
            self.ensure_canvas_active()
        elif self._auto_active:                # the mouse is never taken over before the user resumes
            self.pipeline.pause()

    def ensure_canvas_active(self):
        """Choosing the instrument or drawing also starts it: these modes never send OS input, so nothing can
        go wrong on the desktop, and a paused canvas looks like a broken mode."""
        snap = self.pipeline.controller.snapshot()
        if snap.mode not in CANVAS_MODES or snap.state is not ControlState.PAUSED:
            return
        if snap.camera_state is CameraState.RUNNING:
            self._auto_active = self.pipeline.resume()
            return
        self._auto_resume = True
        if self.camera is None:
            self.start_camera()

    def update_instrument(self, values: dict) -> bool:
        """Instrument bar change: apply and save at once, without pausing or restarting the camera."""
        settings = validate({**asdict(self.settings), **values})
        self.settings = self.pipeline.settings = settings
        if self.instrument is not None:
            self.instrument.apply_settings(settings)
        self._keep(settings)
        return True

    def _keep(self, settings) -> None:
        """Save and use settings that change nothing in the running control."""
        try:
            self.store.save(settings)
        except Exception:
            log.warning('could not save the settings', exc_info=True)
        self.settings = self.pipeline.settings = settings
        self.settings_changed.emit(settings)

    def set_mascot(self, on: bool) -> None:
        """Cat button or tray: apply and save at once, without pausing control."""
        self._keep(replace(self.settings, mascot_visible=bool(on)))

    def _emergency(self):
        self._auto_resume = False
        if self.pipeline:
            self.pipeline.emergency_stop()

    def _session_event(self, event):
        if self.pipeline:
            if event == 'suspend':
                self.pipeline.controller.on_suspend()
            elif event in ('lock', 'remote_disconnect', 'console_disconnect', 'logoff'):
                self.pipeline.controller.on_session_lock()

    def _on_snapshot(self, snapshot):
        self.sink.set_epoch(self.pipeline.controller.current_epoch())
        self.snapshot_received.emit(snapshot)

    @Slot(object)
    def _snapshot(self, snapshot):
        if self._auto_resume:
            self._try_auto_resume()
        if snapshot.epoch != self.pipeline.controller.current_epoch():
            return
        if snapshot.state is not ControlState.ACTIVE:
            self._auto_active = False
        previous = self.bridge.state
        state = snapshot_to_viewmodel(snapshot, dry_run=not self.live, mirrored=self.settings.mirror_preview)
        self.bridge.update_state(replace(state, latest_frame=previous.latest_frame,
            dry_run_command_text=previous.dry_run_command_text))
        self.bridge.update_overlay(state.overlay)
        self.bridge.update_snapshot(snapshot)

    def _try_auto_resume(self):
        snap = self.pipeline.controller.snapshot()
        if snap.mode not in CANVAS_MODES or snap.state is ControlState.ACTIVE:
            self._auto_resume = False
        elif snap.state is ControlState.PAUSED and snap.camera_state is CameraState.RUNNING:
            self._auto_resume = False
            self._auto_active = self.pipeline.resume()

    def toggle_pause(self):
        if self.pipeline.controller.snapshot().state == ControlState.ACTIVE:
            self.pipeline.pause()
        else:
            self.pipeline.resume()

    def toggle_camera(self):
        running = self.pipeline.controller.snapshot().camera_state in (CameraState.RUNNING, CameraState.STARTING)
        self.stop_camera()                     # also drops a handle left behind by a camera error
        if not running:
            self.start_camera()

    def start_camera(self):
        if self.camera or self.closed:
            return
        try:
            self.camera = self.camera_factory(self.pipeline, start=False)
            loop = getattr(self.camera, 'loop', None)
            if loop is not None:
                taps = [*([self.instrument.tap_image] if self.instrument is not None else []), *self.image_taps]
                loop.on_image = fan_out(taps)       # camera image for the Enstrüman window and the cat
            self.camera.start()
        except Exception as exc:
            self.stop_camera()
            self.pipeline.set_camera_state(CameraState.ERROR)
            self.bridge.show_feedback(message=f'Kamera başlatılamadı: {exc}')

    def stop_camera(self):
        camera, self.camera = self.camera, None
        if camera:
            camera.loop.stop()
            camera.camera.stop()
        if self.pipeline:
            self.pipeline.set_camera_state(CameraState.OFF)

    def save_settings(self, data):
        self.pipeline.pause('Ayarlar değiştirildi')
        values = dialog_data_to_values(asdict(self.settings), data)
        values['start_with_windows'] = self._apply_startup(bool(data.start_with_windows))
        self.apply_settings(validate(values))

    def apply_settings(self, settings) -> bool:
        """Persist and apply validated settings (shared by dialog save and import)."""
        try:
            self.hotkey.reassign(*hotkey_binding(settings.emergency_hotkey))
            self.store.save(settings)
            self._replace_pipeline(settings)
            return True
        except Exception as exc:
            self.bridge.show_feedback(message=f'Ayarlar kaydedilemedi: {exc}')
            return False

    def export_settings(self, path) -> bool:
        try:
            payload = json.dumps(asdict(validate(asdict(self.settings))), indent=2, ensure_ascii=False)
            Path(path).write_text(payload, encoding='utf-8')
        except Exception as exc:
            log.warning('settings export failed: %s', exc)
            self.bridge.show_feedback(message=f'{EXPORT_FAILED_TR}: {exc}')
            return False
        self.bridge.show_feedback(message='Ayarlar dışa aktarıldı')
        return True

    def import_settings(self, path) -> bool:
        try:
            data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
            if not isinstance(data, dict):
                raise ValueError('dosya bir ayar nesnesi değil')
            imported = validate(migrate(data))
        except Exception as exc:
            log.warning('settings import failed: %s', exc)
            self.bridge.show_feedback(message=f'{IMPORT_FAILED_TR}: {exc}')
            return False
        self.pipeline.pause('Ayarlar içe aktarıldı')
        # Windows startup stays whatever the registry says; an imported file must not flip it silently.
        imported = replace(imported, start_with_windows=self.settings.start_with_windows,
            onboarding_done=self.settings.onboarding_done or imported.onboarding_done)
        if not self.apply_settings(imported):
            return False
        self.bridge.show_feedback(message='Ayarlar içe aktarıldı')
        return True

    def add_action_listener(self, listener) -> None:
        self.action_listeners.append(listener)

    def remove_action_listener(self, listener) -> None:
        if listener in self.action_listeners:
            self.action_listeners.remove(listener)

    @Slot(str, int, int)
    def _dispatch_action_listeners(self, kind, x, y):
        sound = sound_kind_for(kind)
        if sound and self.settings.click_sound:
            try:
                player = self.sound_player
                if player is None:
                    from handcontrol.windows import sound as player_module
                    player = player_module.play
                player(sound)
            except Exception:
                log.debug('click sound failed', exc_info=True)
        for listener in list(self.action_listeners):
            try:
                listener(kind, x, y)
            except Exception:
                log.debug('action listener failed', exc_info=True)

    def mark_onboarding_done(self) -> None:
        if not self.settings.onboarding_done:
            self._keep(replace(self.settings, onboarding_done=True))

    def save_instrument_area(self, instrument_settings) -> None:
        """Keep the "Sabit teller" area the user placed (window drag or two-hand pinch)."""
        rect = list(instrument_settings.instrument_fixed_rect)
        free = [list(s) for s in instrument_settings.instrument_free_strings]
        if list(self.settings.instrument_fixed_rect) == rect and self.settings.instrument_free_strings == free:
            return
        self._keep(replace(self.settings, instrument_fixed_rect=rect, instrument_free_strings=free))

    def build_diagnostics(self, dest_dir: Path | None = None) -> Path | None:
        from handcontrol import diagnostics, logsetup, telemetry as telemetry_module
        try:
            monitors = [f'{m.bounds} dpi={m.dpi_scale} primary={m.is_primary}' for m in self.displays.monitors()]
        except Exception:
            monitors = []
        camera = self.settings.camera
        extra = {'Kamera': f'index={camera.index} backend={camera.backend} {camera.width}x{camera.height}@{camera.fps}',
            'Monitörler': monitors, 'Mod': 'canlı' if self.live else 'komutsuz deneme'}
        try:
            return diagnostics.build_diagnostics_zip(dest_dir, settings_path=self.store.path,
                logs_dir=self.logs_dir or logsetup.default_logs_dir(),
                telemetry_dir=telemetry_module.default_telemetry_dir(), extra=extra)
        except Exception as exc:
            log.warning('diagnostics failed: %s', exc)
            self.bridge.show_feedback(message=f'Tanılama dosyası oluşturulamadı: {exc}')
            return None

    def startup_enabled(self) -> bool:
        return self.startup.is_enabled()

    def _apply_startup(self, wanted: bool) -> bool:
        """Change HKCU Run only when the user toggled it; return the real resulting state."""
        current = self.startup.is_enabled()
        if wanted == current:
            return current
        # Source checkouts need PYTHONPATH=src, which a Run entry cannot provide.
        if wanted and not self.packaged:
            self.bridge.show_feedback(message=STARTUP_SOURCE_TR)
            return current
        if not self.startup.set_enabled(wanted):
            self.bridge.show_feedback(message=STARTUP_FAILED_TR)
            return current
        return wanted

    def _replace_pipeline(self, settings):
        # Keep controller epoch monotonic; configuration changes happen while paused.
        camera_was_running = self.camera is not None
        previous_mode = self.pipeline.controller.snapshot().mode
        self.stop_camera()
        with self.pipeline._lock, self.pipeline.controller._lock:
            self.settings = self.pipeline.settings = settings
            self.pipeline.controller._cfg = controller_config(settings, camera_error_paused=True)
            # Pipeline and controller are reused, not rebuilt: keep the real-cursor reader wired.
            self.pipeline.controller._cursor_source = self.cursor_source
            self.pipeline.controller.set_calibration(calibration_rect(settings))
            self.pipeline.gestures = GestureRecognizer(gesture_config(settings), dominant_of(settings))
            self.pipeline.request_gesture_reset(full=True)
            # Saving from the Enstrüman tab must not throw the user out of the instrument.
            keep = previous_mode in CANVAS_MODES
            self.pipeline.set_mode(previous_mode if keep else Mode(settings.default_mode))
        if self.instrument is not None:
            self.instrument.apply_settings(settings)
        if camera_was_running:
            self.start_camera()
        self.settings_changed.emit(settings)

    def calibrated(self, result):
        b = result.bounds
        # Wizard consumes the unmirrored landmark frame.
        settings = replace(self.settings, calibration=CalibrationBounds(b.left, b.top, b.right, b.bottom),
            dominant_hand=result.dominant_hand.value, pinch_on_threshold=result.thresholds.pinch_on,
            pinch_off_threshold=result.thresholds.pinch_off)
        self.pipeline.controller.end_calibration()
        self.store.save(settings)
        self._replace_pipeline(settings)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.timer.stop()
        if self.camera:
            self.camera.loop.stop()
        if self.pipeline:
            self.pipeline.emergency_stop()
            self.pipeline.stop()
        if self.instrument is not None:
            try:
                self.instrument.close()
            except Exception:
                log.debug('instrument close failed', exc_info=True)
        if self.telemetry:
            self.telemetry.close()
        for service in (self.sink, self.hotkey, self.session, self.displays):
            if service:
                try:
                    service.close()
                except Exception:
                    pass
        if self.camera:
            self.camera.camera.stop()
            self.camera = None


def _make_instrument(runtime: 'Runtime'):
    from handcontrol.instrument_runtime import InstrumentRuntime
    return InstrumentRuntime(runtime.pipeline, runtime.settings, bridge=runtime.bridge,
        notify=lambda text: runtime.bridge.show_feedback(message=text),
        persist=runtime.save_instrument_area, parent=runtime)


def show_or_reuse_dialog(ref: list, factory):
    """Raise the dialog held in `ref` if still open, else build one with `factory` and keep it there."""
    if ref and ref[0].isVisible():
        dlg = ref[0]
        if dlg.isMinimized():
            dlg.showNormal()
        dlg.raise_()
        dlg.activateWindow()
        return dlg
    dlg = factory()
    ref[:] = [dlg]
    dlg.show()
    return dlg


def build_onboarding_dialog(dialog_cls, runtime, parent, ref: list, live: bool):
    """Create the tutorial; it deletes itself on close and drops its listener and `ref` entry when destroyed."""
    dlg = dialog_cls(parent, hotkey=runtime.settings.emergency_hotkey,
        dominant_hand=runtime.settings.dominant_hand, live=live)
    for name in ('completed', 'skipped'):
        getattr(dlg, name).connect(runtime.mark_onboarding_done)
    listener = getattr(dlg, 'on_action', None)
    if listener is not None:
        runtime.add_action_listener(listener)
    dlg.setModal(False)
    dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

    def cleanup(*_):
        if listener is not None:
            runtime.remove_action_listener(listener)
        if ref and ref[0] is dlg:
            ref.clear()
    dlg.destroyed.connect(cleanup)
    return dlg


def main(argv=None) -> int:
    if not enable_per_monitor_v2():
        print('Başlatılamadı: per-monitor DPI awareness v2 ayarlanamadı.', file=sys.stderr)
        return 1
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true', help='Gerçek Windows komutlarını etkinleştir')
    parser.add_argument('--log-level', default='INFO', help='Günlük düzeyi (DEBUG, INFO, WARNING, ERROR)')
    parser.add_argument('--telemetry', action='store_true', help='Oturum telemetrisini yerel CSV dosyasına kaydet (görüntü yok)')
    args = parser.parse_args(argv)
    from handcontrol import logsetup
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    instance_lock = acquire_single_instance()
    if instance_lock is None:
        print(ALREADY_RUNNING_TR, file=sys.stderr)
        try:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(None, 'Holoscobe', ALREADY_RUNNING_TR)
        except Exception:
            pass
        return 0
    tray_ref: list = []
    error_notifier = ErrorNotifier(lambda text: tray_ref and tray_ref[0].showMessage('Holoscobe', text))
    try:
        logsetup.setup_logging(level=args.log_level, notify=error_notifier.notify)
    except OSError as exc:
        print(f'Günlük dosyası açılamadı: {exc}', file=sys.stderr)
    bridge = UiBridge()
    try:
        telemetry = SessionRecorder() if args.telemetry else None
        if telemetry:
            print(f'Telemetri kaydı: {telemetry.path}')
        runtime = Runtime(bridge, SettingsStore(), live=args.live, telemetry=telemetry)
    except Exception as exc:
        print(f'Başlatılamadı: {exc}', file=sys.stderr)
        return 1
    from handcontrol.ui.main_window import MainWindow
    window = MainWindow(bridge, live=args.live)
    window.apply_instrument_settings(runtime.settings)
    window.instrument_changed.connect(runtime.update_instrument)
    runtime.settings_changed.connect(window.apply_instrument_settings)
    if runtime.instrument is not None:
        runtime.instrument.attach(window.instrument, window.preview, window.drawing)
        window.free_strings_changed.connect(runtime.instrument.set_free_strings)
    window.drawing.bind(runtime.pipeline)
    tray = HandControlTray(bridge, window)
    tray_ref.append(tray)
    tray.activated.connect(lambda reason: window.bring_up()
        if reason in (tray.ActivationReason.Trigger, tray.ActivationReason.DoubleClick) else None)
    overlay = OverlayWindow(bridge)
    cursor_ring = CursorFeedbackOverlay(bridge, enabled_fn=lambda: runtime.settings.cursor_feedback,
        follow_os_cursor=args.live)
    toast = FeedbackToast(bridge, auto_show_window=True)
    indicator = StatusIndicator(bridge, enabled_fn=lambda: runtime.settings.overlay_visible, auto_show_window=True)
    screen = app.primaryScreen()
    if screen:
        area = screen.availableGeometry()
        overlay.move(area.center() - overlay.rect().center())
        indicator.move(area.right() - indicator.width() - 16, area.top() + 16)
    bridge.settings_saved.connect(lambda _data: indicator.apply_indicator(indicator.indicator_state))
    panel = DryRunPanel(bridge)
    def frames():
        if runtime.pipeline.last_features is not None:
            bridge.update_frame(runtime.pipeline.last_features)
    runtime.timer.timeout.connect(frames)
    bridge.overlay_updated.connect(lambda state: overlay.setVisible(state.visible and runtime.settings.overlay_visible))
    def settings_dialog():
        was_active = runtime.pipeline.controller.snapshot().state is ControlState.ACTIVE
        runtime.pipeline.pause('Ayarlar')
        s = runtime.settings
        initial = replace(settings_to_dialog_data(s, startup_enabled=runtime.startup_enabled()),
            audio_device_choices=audio_device_names())
        dialog = SettingsDialog(initial=initial, bridge=bridge, parent=window)
        wire_settings_dialog(dialog)
        dialog.exec()
        if was_active:
            runtime.ensure_canvas_active()     # Enstrüman/Çizim only; other modes stay paused
    onboarding_ref: list = []
    def open_onboarding():
        from handcontrol.ui.onboarding import OnboardingDialog
        show_or_reuse_dialog(onboarding_ref, lambda: build_onboarding_dialog(OnboardingDialog, runtime, window, onboarding_ref, args.live))
    def diagnostics_zip():
        path = runtime.build_diagnostics()
        if path:
            tray.showMessage('Holoscobe', f'Tanılama dosyası hazır: {path}')
    def wire_settings_dialog(dialog):
        dialog.export_settings_requested.connect(runtime.export_settings)
        dialog.import_settings_requested.connect(runtime.import_settings)
        dialog.diagnostics_requested.connect(diagnostics_zip)
        dialog.tutorial_requested.connect(open_onboarding)
        if runtime.instrument is not None:
            dialog.test_sound_requested.connect(runtime.instrument.play_test_tone)
    bridge.tutorial_requested.connect(open_onboarding)
    if runtime.instrument is not None:
        def open_instrument():
            bridge.select_mode(Mode.INSTRUMENT)
            window.bring_up()
        bridge.instrument_window_requested.connect(open_instrument)
    mascot = None
    try:
        from handcontrol.mascot.window import Mascot
        mascot = Mascot(bridge, enabled=runtime.settings.mascot_visible,
            notify=lambda text: bridge.show_feedback(message=text))
        runtime.image_taps.append(mascot.tap)
        runtime.pipeline.add_frame_observer(mascot.on_features)
        window.drawing.brush_changed.connect(mascot.window.set_brush)
        if runtime.instrument is not None:
            runtime.instrument.note_played.connect(mascot.window.pluck)
        runtime.settings_changed.connect(lambda s: mascot.set_enabled(s.mascot_visible))
        app.aboutToQuit.connect(mascot.close)
    except Exception:
        log.exception('mascot unavailable')      # the cat must never stop the app
    bridge.set_mascot_visible(runtime.settings.mascot_visible)
    runtime.settings_changed.connect(lambda s: bridge.set_mascot_visible(s.mascot_visible))
    bridge.mascot_toggle_requested.connect(runtime.set_mascot)
    def calibration_dialog():
        if runtime.pipeline.controller.begin_calibration():
            CalibrationWizard(bridge=bridge, parent=window).exec()
    bridge.settings_requested.connect(settings_dialog)
    bridge.calibration_requested.connect(calibration_dialog)
    bridge.exit_requested.connect(app.quit)
    app.aboutToQuit.connect(runtime.close)
    app.aboutToQuit.connect(cursor_ring.close)
    tray.show()
    window.show()
    if not args.live:
        panel.show()
    runtime.start_camera()
    runtime.ensure_canvas_active()             # default mode = Enstrüman or Çizim
    if not runtime.settings.onboarding_done:
        QTimer.singleShot(0, open_onboarding)
    try:
        return app.exec()
    finally:
        runtime.close()
        instance_lock.unlock()


if __name__ == '__main__':
    raise SystemExit(main())

