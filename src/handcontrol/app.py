"""Desktop composition root. Real OS output requires explicit --live opt-in."""
from __future__ import annotations

import argparse
import ctypes
import sys
import time
from dataclasses import asdict, replace
from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtWidgets import QApplication, QMainWindow, QLabel, QPushButton, QToolBar

from handcontrol.config import SettingsStore, CalibrationBounds, validate
from handcontrol.contracts import CameraState, ControlState, Mode
from handcontrol.controller import MenuKind
from handcontrol.dryrun import DryRunSink, FakeVolume
from handcontrol.pipeline import Pipeline, dominant_of, run_camera_pipeline
from handcontrol.telemetry import SessionRecorder, TelemetrySink
from handcontrol.ui import (UiBridge, UiState, OverlayState, OverlayMenuKind,
    OverlayMenuItem, VirtualCursorState, HandControlTray, CameraPreviewWidget,
    OverlayWindow, FeedbackToast, StatusIndicator, DryRunPanel, SettingsDialog, SettingsData, CalibrationWizard)
from handcontrol.windows import (enable_per_monitor_v2, WindowsDisplayProvider,
    WindowsWindowQuery, WindowsVolumeControl, WindowsActionSink, WindowsHotkey, WindowsSession)
from handcontrol.windows import startup as windows_startup
from handcontrol.windows.hotkey import HotkeyConflictError


class Clock:
    def now_ms(self) -> float:
        return time.monotonic() * 1000


def hotkey_binding(text: str) -> tuple[int, int]:
    parts = text.upper().split('+')
    modifiers = 0
    for part in parts[:-1]:
        modifiers |= {'CTRL': 2, 'ALT': 1, 'SHIFT': 4, 'WIN': 8}[part]
    key = parts[-1]
    if key.startswith('F') and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        return modifiers, 0x70 + int(key[1:]) - 1
    if len(key) == 1 and key.isascii() and key.isalnum():
        return modifiers, ord(key)
    raise ValueError('Geçersiz acil durdurma kısayolu')


STATUS_HINT_TR = ('Önce Sürdür. İşaret açık: imleç (hızlı = uzak, yavaş = hassas) | El açık: imleç durur | '
    'Kısa pinch: sol tık, iki hızlı pinch: çift tık, ~yarım sn tut: sürükle | Başparmak+orta: sağ tık | '
    'Sağ/sol yumruk: küçült/geri aç. Tümü: tepside Hareket Rehberi.')


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


STARTUP_SOURCE_TR = 'Windows ile başlatma yalnızca paketlenmiş sürümde kullanılabilir'
STARTUP_FAILED_TR = 'Windows ile başlatma ayarı değiştirilemedi'


def settings_to_dialog_data(s, *, startup_enabled: bool | None = None) -> SettingsData:
    """Map stored Settings to dialog values so saving does not reset untouched fields.

    startup_enabled overrides the stored flag with the real registry state when known."""
    mm = s.monitor_mapping
    monitor = ('primary' if mm.mode == 'primary' else 'secondary' if mm.mode == 'monitor' and mm.monitor_index == 1
        else 'all')
    return SettingsData(mirror=s.mirror_preview, dominant_hand=s.dominant_hand,
        camera_index=s.camera.index, camera_backend='directshow' if s.camera.backend == 'dshow' else 'media_foundation',
        emergency_hotkey=s.emergency_hotkey, pinch_on_threshold=s.pinch_on_threshold,
        pinch_off_threshold=s.pinch_off_threshold, pointer_sensitivity=s.sensitivity, default_mode=s.default_mode,
        scroll_direction='reverse' if s.scroll_direction == 'reversed' else 'natural',
        zoom_direction='reverse' if s.zoom_direction == 'reversed' else 'natural',
        pointer_mode=s.pointer_mode, pointer_speed=s.pointer_speed,
        show_overlay=s.overlay_visible, show_mascot=s.mascot_visible, monitor_mapping=monitor,
        start_with_windows=s.start_with_windows if startup_enabled is None else startup_enabled)


def snapshot_to_viewmodel(snapshot, *, dry_run: bool = True, mirrored: bool = True) -> UiState:
    menu = snapshot.menu
    overlay = OverlayState()
    if menu:
        items = tuple(OverlayMenuItem(item.key, item.label, item.enabled, item.selected,
            index == menu.hovered, item.key == 'close' and menu.close_armed,
            menu.hold_progress if item.key == 'close' else 0) for index, item in enumerate(menu.items))
        overlay = OverlayState(visible=True,
            kind=OverlayMenuKind.MODE_MENU if menu.kind == MenuKind.MODE else OverlayMenuKind.WINDOW_ACTION_MENU,
            title='Mod Seçimi' if menu.kind == MenuKind.MODE else 'Pencere Eylemleri', items=items,
            cursor=VirtualCursorState(*menu.pointer, visible=True, hold_progress=menu.hold_progress),
            inactivity_ms=max(0, 5000 - menu.remaining_ms))
    return UiState(control_state=snapshot.state, camera_state=snapshot.camera_state,
        mode=snapshot.mode, menu_items=overlay.items, virtual_cursor=overlay.cursor,
        hold_progress=menu.hold_progress if menu else 0, overlay=overlay,
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


class Runtime(QObject):
    """Own services; workers emit data, GUI slots own widget changes."""
    snapshot_received = Signal(object)

    def __init__(self, bridge, store, *, live=False, displays=None, windows=None,
                 volume=None, hotkey_factory=WindowsHotkey, session_factory=WindowsSession,
                 sink_factory=WindowsActionSink, camera_factory=run_camera_pipeline,
                 startup=windows_startup, packaged: bool | None = None,
                 cursor_source: CursorSource | None = None, telemetry: SessionRecorder | None = None):
        super().__init__()
        self.telemetry = telemetry
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
        self.closed = False
        self.timer = QTimer(self)
        self.snapshot_received.connect(self._snapshot)
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
            pipeline_sink = TelemetrySink(self.sink, telemetry) if telemetry else self.sink
            self.pipeline = Pipeline(Clock(), pipeline_sink, self.displays, self.windows, self.volume, self.settings,
                cursor_source=self.cursor_source)
            self.pipeline.controller._cfg = replace(self.pipeline.controller.config, camera_error_paused=True)
            self.pipeline.controller.add_listener(self._on_snapshot)
            if telemetry:
                telemetry.dominant = lambda: dominant_of(self.settings)
                self.pipeline.add_frame_observer(telemetry.on_frame)
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
        b.pause_requested.connect(p.pause)
        b.resume_requested.connect(p.resume)
        b.pause_resume_requested.connect(self.toggle_pause)
        b.mode_selected.connect(p.set_mode)
        b.camera_start_requested.connect(self.start_camera)
        b.camera_stop_requested.connect(self.stop_camera)
        b.camera_toggle_requested.connect(self.toggle_camera)
        b.settings_saved.connect(self.save_settings)
        b.calibration_completed.connect(self.calibrated)
        b.calibration_cancelled.connect(p.controller.end_calibration)

    def _emergency(self):
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
        if snapshot.epoch != self.pipeline.controller.current_epoch():
            return
        previous = self.bridge.state
        state = snapshot_to_viewmodel(snapshot, dry_run=not self.live, mirrored=self.settings.mirror_preview)
        self.bridge.update_state(replace(state, latest_frame=previous.latest_frame,
            dry_run_command_text=previous.dry_run_command_text))
        self.bridge.update_overlay(state.overlay)
        self.bridge.update_snapshot(snapshot)

    def toggle_pause(self):
        if self.pipeline.controller.snapshot().state == ControlState.ACTIVE:
            self.pipeline.pause()
        else:
            self.pipeline.resume()

    def toggle_camera(self):
        self.stop_camera() if self.camera else self.start_camera()

    def start_camera(self):
        if self.camera or self.closed:
            return
        try:
            self.camera = self.camera_factory(self.pipeline, start=False)
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
        values = asdict(self.settings)
        values.update(mirror_preview=data.mirror, dominant_hand=data.dominant_hand,
            sensitivity=data.pointer_sensitivity, pinch_on_threshold=data.pinch_on_threshold,
            pinch_off_threshold=data.pinch_off_threshold, default_mode=data.default_mode,
            pointer_mode=data.pointer_mode, pointer_speed=data.pointer_speed,
            emergency_hotkey=data.emergency_hotkey, overlay_visible=data.show_overlay,
            mascot_visible=data.show_mascot, scroll_direction='reversed' if data.scroll_direction == 'reverse' else 'normal',
            zoom_direction='reversed' if data.zoom_direction == 'reverse' else 'normal')
        values['camera'].update(index=data.camera_index, backend={'media_foundation':'msmf', 'directshow':'dshow'}.get(data.camera_backend, 'auto'))
        values['monitor_mapping'] = {'mode': 'primary' if data.monitor_mapping == 'primary' else 'monitor' if data.monitor_mapping == 'secondary' else 'virtual_desktop', 'monitor_index': 1 if data.monitor_mapping == 'secondary' else 0}
        values['start_with_windows'] = self._apply_startup(bool(data.start_with_windows))
        settings = validate(values)
        try:
            self.hotkey.reassign(*hotkey_binding(settings.emergency_hotkey))
            self.store.save(settings)
            self._replace_pipeline(settings)
        except Exception as exc:
            self.bridge.show_feedback(message=f'Ayarlar kaydedilemedi: {exc}')

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
        from handcontrol.pipeline import controller_config, gesture_config, dominant_of, calibration_rect
        # Keep controller epoch monotonic; configuration changes happen while paused.
        self.stop_camera()
        with self.pipeline._lock, self.pipeline.controller._lock:
            self.settings = self.pipeline.settings = settings
            self.pipeline.controller._cfg = replace(controller_config(settings), camera_error_paused=True)
            # Pipeline and controller are reused, not rebuilt: keep the real-cursor reader wired.
            self.pipeline.controller._cursor_source = self.cursor_source
            self.pipeline.controller.set_calibration(calibration_rect(settings))
            from handcontrol.gestures import GestureRecognizer
            self.pipeline.gestures = GestureRecognizer(gesture_config(settings), dominant_of(settings))
            self.pipeline.request_gesture_reset(full=True)
            self.pipeline.set_mode(Mode(settings.default_mode))

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


def main(argv=None) -> int:
    if not enable_per_monitor_v2():
        print('Başlatılamadı: per-monitor DPI awareness v2 ayarlanamadı.', file=sys.stderr)
        return 1
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true', help='Gerçek Windows komutlarını etkinleştir')
    parser.add_argument('--telemetry', action='store_true', help='Oturum telemetrisini yerel CSV dosyasına kaydet (görüntü yok)')
    args = parser.parse_args(argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    bridge = UiBridge()
    try:
        telemetry = SessionRecorder() if args.telemetry else None
        if telemetry:
            print(f'Telemetri kaydı: {telemetry.path}')
        runtime = Runtime(bridge, SettingsStore(), live=args.live, telemetry=telemetry)
    except Exception as exc:
        print(f'Başlatılamadı: {exc}', file=sys.stderr)
        return 1
    window = QMainWindow()
    window.setWindowTitle('Holoscobe' + (' — Canlı' if args.live else ' — Komutsuz Deneme'))
    window.setCentralWidget(CameraPreviewWidget(bridge))
    controls = QToolBar('Kontrol', window)
    controls.setMovable(False)
    activate = QPushButton('Sürdür')
    activate.clicked.connect(runtime.toggle_pause)
    controls.addWidget(activate)
    status = QLabel('Duraklatıldı')
    controls.addWidget(status)
    window.addToolBar(controls)
    def update_controls(state):
        activate.setText(state.pause_resume_action_text)
        status.setText(f'  {state.control_state_label_tr} | {state.mode_label_tr} | {state.camera_state_label_tr}')
        window.statusBar().showMessage(state.error_text or STATUS_HINT_TR)
    bridge.state_changed.connect(update_controls)
    update_controls(bridge.state)
    tray = HandControlTray(bridge, window)
    overlay = OverlayWindow(bridge)
    toast = FeedbackToast(bridge, auto_show_window=True)
    indicator = StatusIndicator(bridge, enabled_fn=lambda: runtime.settings.overlay_visible, auto_show_window=True)
    screen = app.primaryScreen()
    if screen:
        area = screen.availableGeometry()
        indicator.move(area.right() - indicator.width() - 16, area.top() + 16)
    bridge.settings_saved.connect(lambda _data: indicator.apply_indicator(indicator.indicator_state))
    panel = DryRunPanel(bridge)
    def frames():
        if runtime.pipeline.last_features is not None:
            bridge.update_frame(runtime.pipeline.last_features)
    runtime.timer.timeout.connect(frames)
    bridge.overlay_updated.connect(lambda state: overlay.setVisible(state.visible and runtime.settings.overlay_visible))
    def settings_dialog():
        runtime.pipeline.pause('Ayarlar')
        s = runtime.settings
        dialog = SettingsDialog(initial=settings_to_dialog_data(s, startup_enabled=runtime.startup_enabled()),
            bridge=bridge, parent=window)
        dialog.exec()
    def calibration_dialog():
        if runtime.pipeline.controller.begin_calibration():
            CalibrationWizard(bridge=bridge, parent=window).exec()
    bridge.settings_requested.connect(settings_dialog)
    bridge.calibration_requested.connect(calibration_dialog)
    bridge.exit_requested.connect(app.quit)
    app.aboutToQuit.connect(runtime.close)
    tray.show()
    window.show()
    if not args.live:
        panel.show()
    runtime.start_camera()
    try:
        return app.exec()
    finally:
        runtime.close()


if __name__ == '__main__':
    raise SystemExit(main())

