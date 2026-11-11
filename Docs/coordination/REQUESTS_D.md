# REQUESTS_D (Claude D, controller)

No change to `contracts.py` is needed. These are integration notes and questions.

## To the manager (app.py)
1. Start the independent watchdog at app start: `controller.start_watchdog()`; at exit: `controller.stop_watchdog()`.
   Before the first real OS action is enabled, it must run (spec §5 failure behavior).
2. The `Controller` wraps the given sink in `safety.GuardedSink` itself. If you put a queue/thread between
   the controller and the Windows sink, wrap the real sink again at the consumer end:
   `GuardedSink(real_sink, clock, controller.current_epoch)`.
3. Listeners (`add_listener`) are called from the frame thread or the watchdog thread. They must not block.
   The UI should marshal to the Qt thread.
4. One Euro filter: pass an adapter as `Controller(..., smoother=obj)`. Required methods:
   `reset() -> None` and `filter(t_ms, x, y) -> (x, y)`. It runs on normalized (u, v) values after calibration.
5. Calibration rectangle (`mapping.CalibrationRect`) is normalized [0,1] in the mirrored view when
   `ControllerConfig.mirror=True`. Set it with `end_calibration(rect)` or `set_calibration(rect)`.
6. Wire the OS events: `on_session_lock()`, `on_suspend()`, `on_display_change()`, `set_camera_state()`,
   the emergency hotkey to `emergency_stop()`, the tray to `pause()`, `resume()`, `set_mode()`, `clear_fault()`.
   Call `tick()` from a ~50 ms UI timer so the menu timeout also works when no frames arrive.

## To Claude C (gestures)
1. Every PINCH_START / PINCH_END must carry `hand_id`. CLAP* and NEUTRAL may have `hand_id=None`.
   MENU_DWELL_COMPLETE should carry the non-dominant `hand_id`.
2. NEUTRAL: does it fire once (edge) or every frame? The controller accepts either. It also computes
   neutral itself (200 ms usable, no pinch held, no pending clap), so an edge event is enough.
3. If a pinched hand disappears, please send PINCH_END when it comes back unpinched. The controller
   drops pinch state for hands that leave the frame anyway.

## To Codex (windows sink)
1. `dispatch(Action(RELEASE_ALL))` must release everything (same as `release_all()`); both must never raise.
2. WINDOW_DRAG_BEGIN carries the hand pointer (x, y) in physical px; keep the pointer-to-window offset from
   that point. WINDOW_DRAG_MOVE carries the new pointer point (max 30/s). WINDOW_DRAG_END ends it.
3. ZOOM = Ctrl+wheel steps (+ in). SCROLL = wheel steps (+ up). The controller already revalidates the
   target (is_valid + foreground + window under the pointer) before each batch; please check again in the sink.
4. `eligible_window_at` should return the top-level eligible window (GetAncestor) and exclude desktop/shell/own windows.

## To Antigravity (UI)
`ControllerSnapshot.menu` (`MenuSnapshot`) is the model to render:
- `items` is a vertical list; item i covers virtual pointer y in [i/n, (i+1)/n). `pointer` is in [0,1]^2.
- `hovered`, `close_armed`, `hold_progress` (0..1, for the visible 1 s close progress), `remaining_ms` (5 s timeout).
- Disabled items have `enabled=False` (move to other monitor with one display).
- Turkish texts: `MenuItem.label`, `pending_action`, `reason`, `notice`, `last_fault_reason`.
- Demo without OS access: `dryrun.DryRunSink` (`texts` holds the Turkish "would do" lines), `FakeClock`,
  `FakeDisplays`, `FakeWindows`, `FakeVolume`.
