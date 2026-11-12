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

## Round 3: startup and packaging handoff (Claude, 2026-11-12)

- New API: `from handcontrol.windows.startup import is_enabled, set_enabled, default_command`. No `windows/__init__.py` change is needed. These functions use HKCU only; registry injection is available through the keyword-only `registry` argument on read/write operations.
- In `app.py`'s `settings_dialog()`, populate `SettingsData.start_with_windows` using `is_enabled()` so the checkbox reflects the actual Run value. Reading startup state does not register it.
- In `Runtime.save_settings(data)`, call `set_enabled(data.start_with_windows)` for an explicit user change before saving settings. If it returns False, report the failure through `bridge.show_feedback(...)` and do not persist the requested state as a successful change. Include the successful `start_with_windows` value in `values` before `validate()` / `store.save()`. Default startup command contains no `--live`; retain dry-run and paused controller defaults. Do not automatically write the Run key merely because the application starts.
- Source-mode command is the requested quoted `pythonw.exe -m handcontrol.app`. This venv does not expose `handcontrol` without `PYTHONPATH` (isolated `find_spec` returned None). A source installation needs module discoverability at logon; the current `launch.ps1` sets `PYTHONPATH` only for its own child process. Resolve the source-install environment on the owning side or offer startup registration for the frozen distribution. Codex installed no package and changed no environment/registry settings.
- `scripts/build.ps1` and `packaging/holoscobe.spec` produced `dist/Holoscobe/Holoscobe.exe` in one build. Window-free `--packaging-check <absolute-json-output-path>` passed; this diagnostic switch imports dependencies and validates assets without invoking app.main(), Qt windows, camera, input or audio services.
- Full results and remaining hardware/release checks: `Docs/reports/windows_startup_packaging.md`. No changes were made to app.py, ui/**, controller.py, contracts.py, .gitignore or README.md for this task.

## Round 4: measurement tools handoff (Claude, 2026-11-12)

- New tools: `python -m handcontrol.tools.click_record` and `python -m handcontrol.tools.pointer_probe`; PowerShell wrappers are `scripts/click_record.ps1` and `scripts/pointer_probe.ps1`. Both wrappers support `--help` and argument forwarding. No GUI/controller wiring is required to use these standalone tools.
- Click recording uses the unchanged `tools.common.LiveSource` camera/tracker/FeatureExtractor path and contracts only, with no Controller/Pipeline dependency or OS output. CSV contains per-frame measurements, phase/repeat/segment labels and blank hand fields when missing; JSON/Markdown summarize cycles, drift, finger states, jitter, area and FPS. Preserve these interfaces while refactoring the controller.
- Threshold ranges are diagnostic candidates from observed open/closed distances, not applied configuration. Incomplete cycles, tracking discontinuities and multiple pinches per cue invalidate recommendations. Fist/other-pinch distance overlap is reported separately; do not use a distance-only threshold when negatives overlap. Capture timing is frame-sampled at adaptive 35%/65% amplitude levels.
- Have the user run both wrappers after stopping camera/live control in the main app. Real hand/camera/second-monitor validation remains pending. Compare `hw_pointer_probe_*.md` actual GetCursorPos errors with `hw_click_*.json` range/landmark5/palm movement before tuning relative pointer mapping or pinch gates.
- Full commands, output schema, test totals and limitations: `Docs/reports/windows_measure_tools.md`. Tests: 96 passed, 0 failed (tools suite, fake hardware only). No existing source, common.py, controller.py, mapping.py, config.py or pipeline.py was changed for this task.
