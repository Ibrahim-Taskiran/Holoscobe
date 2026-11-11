# Codex Windows integration handoff

No shared contract changes requested. `pycaw` and `comtypes` are present in the supplied environment; Codex installed no packages. Their imports remain lazy, on the audio worker.

## Required application/controller wiring (Claude)

1. Call `handcontrol.windows.enable_per_monitor_v2()` before creating UI windows or starting adapter threads. Treat False as a startup incompatibility; do not silently use logical coordinates.
2. Construct `WindowsDisplayProvider`, `WindowsWindowQuery(displays)`, `WindowsInput(displays)`, `WindowsVolumeControl` and `WindowsActionSink(displays=..., windows=..., input_adapter=..., volume=..., epoch=current_epoch)`. The sink can also construct these dependencies by default.
3. Route actions through `sink.dispatch(action)` only. Call `sink.set_epoch(new_epoch)` on every cancellation/reset before new dispatches. It serializes cancellation with dispatch and calls cleanup. Keep epochs monotonically increasing in the controller. `sink.release_all()` never raises; failed native key/button releases remain in the input ledger for subsequent retries.
4. Before allowing real actions, start the emergency hotkey, tray pause/exit and independent stale-frame watchdog. The sink does not itself implement a camera watchdog or own controller state. Registering F12 can fail (OS/debugger reservation or another application); catch `HotkeyConflictError` and require successful reassignment before enabling control.
5. `WindowsHotkey(callback).start()` / `.reassign(modifiers, key)` / `.close()`. Default: Ctrl+Alt+Shift+F12, always MOD_NOREPEAT. Callback runs on the hotkey thread.
6. `WindowsSession(callback).start()` / `.close()`. Events are `lock`, `unlock`, `suspend`, `resume`, `remote_connect`, `remote_disconnect`, `console_disconnect`, `logoff`. Cancel and release on lock/suspend/disconnect; remain paused on recovery. `displays.start(on_change)` reports a tuple of monitors when topology/work area/DPI changes. Cancel, advance epoch and refresh mapping. Marshal UI updates from callbacks to the GUI thread.
7. Warm up COM, if desired, with `volume.get_volume()` while paused. This is read-only. `set_volume(value)` returns False on failure; `get_volume()` raises on unavailable audio. Audio writes are deadline bounded and never call mute setters. The default render endpoint is rechecked on every operation.
8. Shutdown: first stop controller production and invalidate epoch, then `sink.close()`, `hotkey.close()`, `session.close()`, `displays.close()`. `sink.close()` closes its volume adapter but does not assume ownership of externally shared display/event services.

## UI integration (Antigravity)

- Physical coordinates in `Monitor.bounds` / `work_area`; convert only at the Qt boundary. `monitors()` implements `DisplayProvider`.
- `WindowsWindowQuery.eligible_window_at(x, y)`, `.foreground_window()`, `.is_valid(target)` implement `WindowQuery`. Capture the target before showing an overlay. Own-process windows are automatically excluded; extra HWNDs can be supplied via `own_windows`.
- Window operations: `drag_begin(target, x, y)`, `drag_move(target, x, y)`, `drag_end(target)`, `cancel_drag()`, `minimize(target)`, `toggle_maximize(target)`, `move_to_other_monitor(target)`, `close_window(target)`. Production calls should go through the sink.
- Disable other-monitor command when fewer than two monitors exist. Scroll/zoom are rejected unless the latched target is both foreground and under the pointer; the adapter never changes focus to make input work.
- Pass `on_error(str)` to sink/input/window/audio adapters to surface failures. Return False also means rejection; Win32 queued success does not confirm completed window motion. Do not present fake test results as hardware validation.

Pending: application safety/event wiring by the owning team and the 12 interactive checks in `Docs/reports/windows_manual_tests.md`. No paid tools, cloud services, elevation, process termination, dependency installation or git writes were used.
