# REQUESTS_B (Claude B, features/filters)

## Contract change requests
None. `contracts.py` is sufficient.

## Interface notes for consumers (gestures C, controller D, ui Antigravity)
- `FeatureExtractor().update(FrameSample) -> FrameFeatures`; config in `features.FeatureConfig`.
- Hands are sorted by `hand_id`. IDs are never reused (not even after `reset()`).
- `quality is Quality.UNKNOWN` -> `palm_scale_px == 0.0`, `pinch_distance == inf`, all fingers UNKNOWN.
- Finger `curl` is the raw estimate; it is `0.0` when it could not be computed. Always check `state`.
- `identity_ambiguous=True` is held for 100 ms after the last ambiguous sample; affected hands are DEGRADED
  and their finger states restart (UNKNOWN until 50 ms acquire dwell).
- After two hands cross without reliable handedness, IDs may end up exchanged; this only happens on frames
  flagged `identity_ambiguous=True` (never silently).
- Landmarks, `index_tip_px` and curls are unfiltered. Smooth the pointer with `filters.OneEuroFilter2D`.
- Pinch hysteresis helper: `filters.HysteresisSwitch(on_threshold=0.28, off_threshold=0.42, ...)`.
- Not covered here: sample age vs. wall clock (no clock in features); only `inference_done_ms - capture_ms`
  above 150 ms degrades quality.
- Status: synthetic tests only. Real-camera finger accuracy: `bekliyor`.
