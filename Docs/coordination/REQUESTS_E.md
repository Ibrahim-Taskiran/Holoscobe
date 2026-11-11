# REQUESTS_E (Claude E, kamera)

1. A (assets): `assets/models/hand_landmarker.task` must exist; `HandTracker` raises `ModelNotFoundError` otherwise.
2. A (packages): mediapipe + opencv-python (+ numpy) in `.venv`; they are imported lazily, tests do not need them.
3. Manager: handedness labels. `HandTracker(swap_handedness=False)` passes the Tasks label as-is. MediaPipe assumes a mirrored input, so on our unmirrored input left/right may be inverted. Needs a real-hand check; flip the flag in app.py if inverted. Status: bekliyor.
4. Manager (app.py): Camera needs `CameraConfig` from `config.Settings.camera`; no contracts change required.
