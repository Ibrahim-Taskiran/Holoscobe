# Windows Hand Gesture Control — Implementation Specification

**Status:** v1.1 reviewed build specification, 2026-11-12. **Target:** Windows 11 x64, HP Victus laptop with its built-in webcam and two monitors. The defaults below are implementation proposals and should be tuned on the owner's actual hardware. No hardware performance or dependency compatibility has yet been verified. See [Turkish implementation roadmap](ROADMAP_TR.md) and [review decisions](DOKUMAN_INCELEME_TR.md).

## 1. Assignment for the implementation agent

Build a working Windows desktop application from this document. Inspect the project directory before scaffolding and preserve existing work. Implement the milestones in order, validating input in preview or dry-run before enabling Windows actions. Deliver a runnable source checkout, dependency lock, model setup, Windows launch and build scripts, a README with the gesture map and troubleshooting, automated tests for critical logic, and a record of manual tests. If running outside an interactive Windows session, implement and test portable logic there, then provide the exact Windows verification steps and mark hardware checks pending. Never report hardware verification based on mocks.

## 2. Product requirements

- Start paused. With the camera running, a single two-handed clap toggles control on or off. Detect the clap visually. Keep a tray control and keyboard fallback.
- Track both hands and individual fingers with the built-in webcam. Let the user select an external camera later.
- Finger tracking is a release gate, not an optional visual effect: independently identify thumb, index, middle, ring and little finger on each hand, with 21 landmarks per hand (42 total), joint geometry and per-finger extended/bent/unknown state. All ten fingers must be represented even when only thumb/index drive desktop commands. Hidden fingers are model estimates, not verified observations; a single RGB camera cannot guarantee correct tracking through full occlusion. Suspend affected commands when available quality checks fail, and measure remaining errors with real camera tests.
- Zero additional software/service cost is mandatory for setup, development, packaging and normal use on the existing Windows laptop. No trial, subscription, usage quota, paid SDK, required cloud GPU, API key, mandatory certificate purchase or additional camera/sensor. Existing hardware, Windows licensing, electricity and initial internet access are prerequisites, not newly supplied free resources. Use locally runnable free dependencies and assets with compatible distribution terms. No paid fallback if accuracy is insufficient.
- Move the pointer, left-click, scroll vertically, change zoom and system volume, minimize, maximize/restore, close, and drag whole application windows across monitors. A browser window moves as a unit with its tabs.
- Provide a system tray indicator, settings and camera preview. A small optional mascot can mirror hand motion once the core is stable. It should work with a user-supplied 3D model in the future.
- Process frames locally. Runtime requires no internet, account, API key, cloud model, or token budget. Initial dependency and model installation may require a download. The language model is unnecessary for these controls.
- Support normal Windows desktop apps in the user's interactive session. Browser zoom uses the target application's shortcuts. Protected Windows screens and elevated applications are outside the supported scope. Use normal user privileges.

## 3. Technical baseline and repository

Use Python 3.11 x64 as the first compatibility candidate. Confirm compatible Windows wheels for MediaPipe Tasks, OpenCV, PySide6, and any audio dependency, then lock the tested versions. Use MediaPipe Hand Landmarker with a local .task model, OpenCV camera capture, PySide6 tray/settings UI, ctypes for Win32 APIs, and Windows Core Audio via a maintained binding such as pycaw/comtypes. Use pytest for recognizers and platform-independent geometry. Prefer a PyInstaller one-folder build after the source launch works.

Use PySide6 Community packages and only the Qt modules whose open-source terms the distribution satisfies. Record exact package versions, transitive dependencies, license texts and notices; do not assume all Qt modules share a license. A replaceable shared-library one-folder distribution is the baseline; include required corresponding-source access and license materials for shipped LGPL components. Keep the initial mascot procedural; select and audit a free renderer separately before promising GLB support. Record the model artifact's own license evidence separately from the MediaPipe repository license. Missing model redistribution evidence blocks bundling and release until resolved with a suitable free artifact. Maintain a model manifest with immutable URL/version, SHA-256, license source and retrieval date. Verify against a previously reviewed hash, not a hash newly computed and trusted from the same download. Confirm the project's own source license before public distribution; do not silently assign one during implementation.

Suggested modules under src/handcontrol:
- camera.py and tracking.py — device lifecycle, capture, inference and diagnostics.
- features.py and gestures.py — geometry, identity, filtering and recognizers.
- controller.py — action arbitration, mode selection and state resets.
- windows/input.py, windows/window.py and windows/audio.py — OS adapters.
- ui/ — tray, preview, calibration and settings. mascot/ — optional renderer and retargeting.
- config.py — versioned settings validation and atomic persistence.
- tests/ — fake adapters, timed landmark fixtures and coordinate tests.
- scripts/ — setup, launch and package scripts. assets/ — local model and licensing metadata.

Flow: camera → newest-frame buffer → tracker → features → state machine → typed action → Windows adapter. The preview and mascot consume tracking state separately. Keep Qt widgets and tray operations on the GUI thread. Serialize actions on one execution path and give emergency stop priority. Initialize COM on the audio adapter's owning thread and release interfaces there. Use an injectable monotonic clock and fake action sink for replay. The recognizer must be independent of camera and Win32 imports.

## 4. Tracking and calibration

1. Request 640×480 at 30 fps initially, verify actual capture properties, and benchmark before raising resolution. Try Media Foundation first and DirectShow as a selectable fallback. On startup and after device failure, show explicit camera status. Use bounded retries and release the capture on exit.
2. Capture BGR frames and convert to RGB for inference. Use Hand Landmarker in VIDEO mode with two hands and strictly increasing monotonic millisecond timestamps. Start with detection, presence and tracking thresholds of 0.55. Process the latest available frame only. Track capture age, inference time and output rate.
3. Represent a sample as capture timestamp, inference completion timestamp, hand ID, handedness and its classification score, 21 normalized landmarks and optional world landmarks. The handedness score is not landmark accuracy; do not invent a per-finger confidence score from it. Derive an explicit usable/degraded/unknown quality state from sample age, geometry plausibility, temporal discontinuity and identity ambiguity. These checks cannot prove visibility of every finger. Pair detections frame to frame using palm proximity, scale and handedness as a soft signal. Reset continuous actions if identity becomes ambiguous. Expose dominant hand and mirrored preview settings. Infer on unmirrored input and mirror only display/mapping as configured; verify labels against the user's actual left/right hands on the pinned Tasks version rather than copying legacy Solutions handedness rules.
4. For image-space distances convert normalized x/y to pixel units first. Estimate palm scale using wrist to middle MCP and index MCP to pinky MCP. Normalize pinch distances by palm scale. Use joint angles and relative geometry for finger extension to support rotated hands. Start pinch on at 0.28 palm units and off at 0.42, pending calibration. Treat single-camera depth as approximate. Avoid computing metric distance between different hands from their independent world origins.
5. Smooth the pointer with a time-aware adaptive filter such as One Euro. Keep separate, lighter smoothing for clap velocity. Add hysteresis and time-based dwell, using timestamps instead of frame counts as the main criterion. Do not use extrapolated points to start commands.
6. Calibration shows handedness, landmarks, frame rate and guide marks. Ask the user to hold a neutral pose, point toward the corners of a comfortable movement area, then repeat relaxed pinches and claps. Persist bounds and thresholds locally. Provide quick recalibration after a camera change. Keep the preview free of live OS input during calibration.

7. Name landmark chains explicitly: wrist 0, thumb 1–4, index 5–8, middle 9–12, ring 13–16 and little finger 17–20. Use thumb-specific joint/opposition geometry; do not apply the other fingers' extension rule unchanged to the thumb. Preview each finger's name, state and curl. Never label uncertain estimates as confidently visible.
8. Benchmark 640×480 and, if the camera supports it, 1280×720 on the same pose set. Select the profile that passes finger accuracy and latency gates together; higher resolution alone is not proof of improvement. CPU is the baseline. Record actual resolution/FPS, camera backend, lighting, hand distance and usable movement bounds. Start testing at 40–80 cm with both hands fully in frame, then publish the measured supported range. Dim light, motion blur, edge-on hands and overlap are separate stress cases, not silently excluded successful trials.

## 5. Control model

Use global states Paused, Active, Calibrating and Fault. When active, select one tool mode at a time: Pointer, Scroll, Zoom, Volume or Windows. Default to Pointer. To select a mode without a keyboard, use a small overlay menu opened by holding the non-dominant open palm for 600 ms while no manipulation is underway. Point at a menu item and pinch to choose it. While the menu is open, gestures go only to the menu. Provide equivalent tray settings. A change of mode clears gesture baselines. Begin a continuous gesture only after the relevant hands have returned to neutral and re-engaged.

Camera lifecycle (Off, Starting, Running, Error) is separate from control state. Camera-off cannot accept a clap or Resume; start the camera from tray/keyboard, recover into Paused, then explicitly activate. Claps toggle only Paused/Active with a healthy camera, never Calibrating/Fault. Define neutral as 200 ms of usable tracking with relevant pinches released and no pending clap; do not require a special fist pose. Pending candidates reserve their input so they cannot also open a menu. Menu entry requires a stable non-dominant palm (less than 0.15 palm units displacement during dwell); approaching hands cancel the dwell. Menus have their own virtual pointer, freeze OS pointer/actions, close after 5 seconds without interaction and require release before reuse. Pause/fault cancels them immediately.

For Zoom, require the second pinch within 300 ms of the first; start only when both are usable and released since the last gesture. Releasing either hand cancels zoom. In Scroll, Zoom and Volume, allow index pointing to position the OS pointer before engagement, but never pointer-mode clicks. Freeze the pointer during engagement. Scroll and Zoom latch the eligible foreground window under the pointer; if it is not foreground, ask the user to focus it explicitly first. Revalidate foreground and hovered target before each wheel batch, cancel on changes, and never silently refocus another app. This prevents wheel routing to an unintended window under Windows' inactive-window scrolling setting.

| Mode | Gesture | Action |
|---|---|---|
| All | One visual clap | Toggle Active/Paused and reset transient state. |
| Pointer | Dominant index extended | Move pointer within the calibrated desktop mapping. |
| Pointer | Brief thumb/index pinch, then release with minimal movement | Left-click at the location latched at pinch start. |
| Scroll | Dominant pinch and move vertically | Emit vertical wheel steps from accumulated displacement; release to stop. |
| Zoom | Pinch with both hands, move hands apart or together | Send Ctrl+wheel steps to a compatible app. Freeze the pointer and require the original target to remain valid. |
| Volume | Dominant pinch and move vertically | Raise or lower system output volume relative to its level at engagement. Up increases. |
| Windows | Point at an eligible window and hold pinch for 250 ms | Grab the whole window and move it with the hand until release. |
| Windows | Choose an action from the window overlay with a pinch | Minimize, maximize/restore, move to the other monitor, or close the latched target. Close requires a deliberate hold. |

In Windows mode, index pointing moves the OS pointer before engagement. A pinch released before the 250 ms drag threshold, within 15 logical pixels, selects/latches that window and opens its action overlay without sending a desktop click. A pinch held to 250 ms starts drag only and cannot open the overlay on release. Overlay interaction uses its virtual pointer and the original target. Choosing Close arms a confirmation item; require a release followed by a fresh 1,000 ms hold on that item to send one normal close request. Other overlay actions execute once on selection. The overlay expires/cancels under the menu rules above.

Starting timing: pinch debounce 70 ms; click release within 450 ms and within 15 logical pixels of the latched point, scaled for monitor DPI; confirm Close with a continuous 1,000 ms pinch and visible progress. A release, a change of target, tracking ambiguity or pause cancels confirmation. Overlay commands emit once per engagement. Begin with volume rate-limited to 10 updates per second, window moves to 30 per second, and scroll/zoom to 12 steps per second. Use dead zones and bounded accumulators to avoid jumps when the user re-engages. Set scroll and zoom direction in settings.

### Visual clap recognizer

Use both palm centers (mean of MCP landmarks) with the average palm scale. Seek a trajectory from separated hands through approach to near contact, followed by separation. Starting thresholds: distance above 2.0 palm units for 120 ms to arm, descending through 0.85 within 450 ms with clear inward velocity, then above 1.6 within 650 ms of near contact. Require evidence of both hands on approach and again during separation. Allow up to 120 ms of overlap-related dropout only after a verified approach has already reached a near zone. A dropout alone never completes the gesture. After a recognized clap, wait at least 900 ms and observe a fresh separated pose before rearming. Tune on real footage, especially edge-on hands and bright backgrounds.

The clap candidate temporarily suppresses ordinary gesture output as soon as the two hands rapidly approach with appropriate clap geometry. Candidate entry requires both hands unpinched, at least three extended non-thumb fingers per hand, and decreasing palm separation by at least 1.0 palm units/second over an 80 ms window, in addition to the armed trajectory. These are initial calibration values. Two sustained pinches cannot become a clap, including in Zoom. Entering a clap candidate cancels any ongoing manipulation and discards buffered output; it does not replay it later. After a clap, require neutral hands before any ordinary gesture. If an attempted clap is abandoned, reset baselines before resuming. Record events without recording footage by default.

### Failure behavior

- Start and recover from camera failure in Paused. Losing hands briefly freezes continuous commands; invalidate the gesture and release app-held input by 200 ms at the latest. Fresh engagement is required.
- A global emergency hotkey, proposed Ctrl+Alt+Shift+F12, immediately pauses and cancels pending work. Use RegisterHotKey with a non-repeat flag, detect conflicts, and allow reassignment. Always expose Pause and Exit from the tray. Provide an explicit control to turn the camera off.
- Cancel on session lock, system suspend, stale tracking, settings preview or display topology change. Keep only inputs owned by the app in the release ledger. Ensure modifiers are released even on partial adapter failure. Preserve physical keyboard input by skipping synthetic modifier chords when conflicting physical keys are down.
- Prioritize emergency stop, camera/session faults, clap, active gesture completion, mode menu, then normal commands. Use an epoch or equivalent cancellation mechanism to discard queued actions after pause/reset.
- Reject samples older than 150 ms at action dispatch, freeze immediately on invalid tracking, and clear the engagement/release owned inputs within 200 ms of the last usable capture. Evaluate this with an independent watchdog even if capture/inference stalls; a frame-processing loop alone is insufficient. No accumulated motion may be replayed on recovery. Emergency hotkey/tray and watchdog must work before the first real OS action is enabled.

## 6. Windows integration

### Pointer and display mapping

Set per-monitor DPI awareness v2 before creating UI windows, preferably via the application manifest for the packaged build. Keep OS geometry in physical desktop pixels and convert Qt coordinates at the UI boundary. Enumerate monitor and work-area rectangles; never assume the primary starts the full desktop, the second display is to the right, or scaling is uniform. Map calibrated camera coordinates into the bounding rectangle of both screens. For gaps, project to the nearest valid monitor point. Handle portrait monitors, negative coordinates and mismatched heights. Use SetCursorPos or SendInput with correctly normalized virtual desktop coordinates. If using SendInput absolute motion include MOUSEEVENTF_VIRTUALDESK. Keep motion within real monitor pixels. Refresh geometry after display changes.

### Window targeting and dragging

Resolve the top-level eligible window under the pointer (WindowFromPoint and GetAncestor), or use the active eligible window when opening the window action overlay. Exclude the desktop, shell, tray, own windows and transient surfaces. Latch HWND and process identity when selecting a target. Recheck existence and process identity before each mutation. Capture the target before displaying an overlay. Surface failures without redirecting commands to another application.

For drag, store the pointer-to-window offset and move the same HWND using SetWindowPos without activating it on every update. For maximized windows, restore on grab and place the restored window using the pointer's relative position in the original bounds. During a drag allow the window to cross the monitor boundary. On release ensure a usable title-bar portion is inside an active monitor work area. The separate “Move to other monitor” command should preserve window placement proportionally within work areas and preserve maximized state by restoring, moving, then maximizing on the destination. Support the two-monitor case directly; disable the command with one display. Validate cross-DPI behavior with the real app and do not fight an application's own DPI resize handling.

Use normal minimize and maximize/restore commands. Close with a normal close request so the target can prompt for unsaved work. Never terminate a process. Verify that minimized apps remain on the taskbar and that close affects only the selected window. Use timeout-bounded or asynchronous APIs where appropriate so a hung target cannot block the control loop. Inspect Win32 return values and report unsupported or blocked input rather than trying to bypass UIPI.

### Audio and zoom

Use IAudioEndpointVolume for the current default render endpoint. Clamp normalized scalar values to [0, 1] and show a percentage. Reacquire the endpoint when the default audio device changes or an endpoint is invalidated. Leave mute state unchanged unless adding an explicit mute command later. Ctrl+wheel support depends on the app. Validate browser zoom in Edge or Chrome and document how other apps behave. Send modifier down, wheel and modifier up as a controlled sequence, with cleanup after failures.

## 7. UI, mascot and settings

Tray icon states: Paused, Active, Calibrating, Camera unavailable. Tooltip shows the current mode and camera status. Tray actions: Pause/Resume, Stop/Start Camera, Settings, Calibrate and Exit. Show brief feedback for activation, mode change, volume and close confirmation. Avoid stealing focus and keep visual feedback dismissible. Show camera activity while paused because clap detection still runs.

Settings include camera choice, mirror, dominant hand, thresholds and sensitivity, scrolling direction, mode selection, hotkey, overlay/mascot visibility and monitor mapping. Store versioned JSON under %LOCALAPPDATA% with validation and atomic replacement. On corrupt settings, preserve a diagnostic copy and load safe defaults. Start with Windows only as an opt-in feature. Store rotating local diagnostic logs containing state, timing and errors, without frames or raw landmark traces by default.

After the core passes acceptance, implement an optional bottom-right mascot. It idles seated when paused and mimics wrist position and finger curl when active. Start with a procedural placeholder so the feature can ship independently of an asset. Later accept a licensed rigged GLB/glTF supplied by the user. Specify arm, wrist and finger bone mappings in asset metadata, support missing bones gracefully, and map smoothed local joint angles onto the rig. Neutralize on tracking loss. Use a small, transparent, click-through overlay outside the window target set; let the tray disable it. A missing asset or renderer failure must leave desktop control working.

## 8. Build milestones and delivery

0. **Free stack feasibility.** Verify Windows wheels, local inference and package/model license evidence; record machine baseline. No paid dependencies.
1. **Camera and ten-finger quality.** Landmarks, finger states, handedness, camera selector, timing and calibration. Compare profiles and pass the finger gate before adding desktop actions. Test camera busy, permission denied and reconnect.
2. **Safety and dry-run.** Implement tray pause/exit, emergency hotkey, watchdog, session events, cancellation and clean shutdown first. Replay synthetic samples and validate real-camera clap/pinch/menu recognition without OS input.
3. **Desktop controls.** Add pointer/click, then scroll/zoom/volume, then window commands and cross-monitor drag, with separate acceptance gates. Use harmless test windows first.
4. **Hardening and offline package.** Finish settings, diagnostics, endurance tests, license notices, reproducible setup and clean-account offline verification.
5. **Optional mascot.** Only after core release acceptance, add a procedural placeholder and separately audit the future free renderer/import contract.

Provide a PowerShell setup script that creates a venv, installs locked packages and obtains the official model artifact with a recorded source and verified hash. Include an offline runtime path and the model's redistribution terms. Package all necessary Qt plugins and MediaPipe native libraries; check startup from a path containing spaces and on a clean Windows user account. Document exact commands for setup, dry run, tests, launch and build. Include dependency and asset notices and a user-facing gesture cheat sheet. Explain how to turn off camera access, exit, and remove optional startup registration.

## 9. Verification and release criteria

| Area | Required check |
|---|---|
| Ten-finger accuracy | For each hand/finger, collect 20 labeled extended and 20 labeled bent presentations, each held 1 second: 400 presentations total. Spread trials between near/far supported distances and palm-forward/oblique views. Score each trial at 500 ms after the pose settles; unknown, missing or incorrect state counts as failure. Require at least 19/20 correct in each finger/state group (not just a pooled average). Use achievable natural poses rather than forced isolated ring-finger movement. These are proposed engineering gates, not measured model accuracy. |
| Two-hand stability | Run five minutes with both hands visible, including independent finger bends. Require both 21-point hands with usable quality on at least 95% of inference samples; report time-weighted coverage and frame rate as well. Zero observed hand-ID swaps may produce an OS command. Log sample counts, gaps and failures; do not count fabricated/repeated samples as successes. |
| Occlusion and quality | Test at least 10 trials each of hand crossing, one hand covering the other, leaving frame, rapid motion and poor light. Human-label errors separately from detected quality failures. Every detected invalid/stale input cancels safely and no unintended OS action may occur in these trials. A complete skeleton alone is not proof of accurate tracking. |
| Clap | On the target laptop, run at least 20 deliberate claps in normal indoor lighting. Initial target at least 18 recognized, one toggle per recognized clap. Run a five-minute ordinary-use session including gestures and near-misses with zero accidental toggles as the initial release target. Record sample size and conditions. |
| Gesture conflicts | Open-palm mode selection, two-handed zoom and incidental hand crossings do not double-dispatch. Test overlap, missing samples, identity swap, pause during drag, camera fault, and held poses. |
| Pointer | Reach all corners on both monitors with calibration. Target at least 18 intentional clicks out of 20, with zero clicks during a pointer-only sweep. Compare jitter with a stationary hand and report observed behavior. |
| Displays | Test both monitor directions, 100% and 150% scaling, negative origin, vertical offset, maximized windows and a disconnected second monitor. Verify tabs stay in their original window. |
| Window actions | Minimize, maximize/restore, move and close a test window; confirm a document with unsaved changes shows its native prompt. Cancel close by releasing early. Verify an invalid HWND or elevated target fails without mutating a different window. |
| Audio and zoom | Confirm direction, bounds, rate limits, device switch and no stuck Ctrl. Check browser zoom and report which apps were tested. |
| Pausing | Validate tray, clap, emergency hotkey, stale-frame timeout and session lock. Pause immediately stops further actions and cancels close confirmation. Verify no automatic rearm after recovery. |
| Performance | Aim for at least 20 processed frames/s and under 150 ms p95 capture-to-pointer-action delay in ordinary use on the target machine. Measure with monotonic timestamps and report camera FPS, processed FPS and p50/p95. Treat software timing as distinct from camera/display end-to-end latency. |
| Offline package | After setup, disconnect the network and launch the packaged app as a normal user. Verify model loading, camera, tray and controls. |

Unit tests should cover timed clap sequences, threshold hysteresis, zero-size palms, stale frames, loss/recovery, cancellation of latched actions, signed monitor coordinates, gaps, and window placement math. Use fake adapters to assert action count and order. Keep hardware tests manual where simulated inputs cannot validate camera quality or OS behavior. If release targets are missed, document results and tune against the measured failure cases. Do not mark v1 accepted until the mandatory gates pass; lower accuracy requires an explicit scope decision, not silent threshold weakening. For quality evaluation only, optionally record consented local clips/landmark traces with a delete control; normal runtime logging remains free of frames and raw traces. Store a test report with machine, versions/hash, conditions, sample sizes, failures and pass/fail/pending for every gate. Retest on a separate pose sequence after tuning.

## 10. Primary references

- [Google MediaPipe Hand Landmarker for Python](https://ai.google.dev/edge/mediapipe/solutions/vision/hand_landmarker/python)
- [HandLandmarkerResult API: available result fields](https://ai.google.dev/edge/api/mediapipe/python/mp/tasks/vision/HandLandmarkerResult)
- [MediaPipe repository license; verify model terms separately](https://github.com/google-ai-edge/mediapipe/blob/master/LICENSE)
- [Qt for Python licensing options](https://doc.qt.io/qtforpython-6/)
- [Qt module licensing](https://doc.qt.io/qt-6/licensing.html)
- [Microsoft SendInput](https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-sendinput)
- [Microsoft SetWindowPos](https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-setwindowpos)
- [Microsoft High DPI desktop development](https://learn.microsoft.com/windows/win32/hidpi/high-dpi-desktop-application-development-on-windows)
- [Microsoft IAudioEndpointVolume](https://learn.microsoft.com/windows/win32/api/endpointvolume/nn-endpointvolume-iaudioendpointvolume)
- [Microsoft RegisterHotKey](https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-registerhotkey)
