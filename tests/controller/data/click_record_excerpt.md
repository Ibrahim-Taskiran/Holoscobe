# Recorded click excerpt and replay limits

`click_record_excerpt.csv` contains 728 untouched rows from the local 5,914-row recording
`hw_click_20261112-152708-382361.csv`. The JSON manifest records source SHA-256 and zero-based row
indices. Generate it with `click_record_analysis.write_excerpt()` (requires the uncommitted source).
Every fourth frame plus extrema and transition neighborhoods is retained; timestamps and values
are unchanged. Full recordings and images are not bundled.

Native-time replay covers left-repeat-1 bounce, drags 3/5 (including tracking failure), and the
multi-second right holds. Those long right holds still cancel, never becoming left activity.

Click classification also uses a **separate simulated short cadence**: four recorded pre-open
frames, the final six usable contact frames, then four release frames, clocked at 33.4 ms.
This deliberately removes the user's multi-second hold; it does not measure natural click timing,
gesture onset latency or quality coverage. Recorded distances, finger states and palm positions
are unchanged. Native-time tests retain real gaps and cancellation behavior.

CSV lacks full landmarks and joint curls. Replay constructs landmarks 4/8/12 to reproduce both
distances exactly and supplies recorded finger-state enums. Curl scores (.6 BENT/.1 otherwise)
are synthetic; these tests do not validate FeatureExtractor or the .80 pinch/fist curl boundary.
