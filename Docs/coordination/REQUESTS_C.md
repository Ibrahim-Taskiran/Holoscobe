# REQUESTS_C (Claude C, gestures)

No contract change requested. `contracts.py` is used as is.

## Integration notes for the controller (D) and UI

- `GestureRecognizer.update(frame)` per-frame event order: forced ends (loss/ambiguity/stall), `PINCH_END`,
  clap events, `PINCH_START`, `MENU_DWELL_COMPLETE`, `NEUTRAL`. A clap abort caused by a pinch comes before that `PINCH_START`.
- `reset()` emits nothing. It keeps the clap cooldown (900 ms) and requires the non-dominant palm to be released
  before the next menu dwell. Call it after CLAP or a mode change without risking a double clap.
- After `CLAP` or `CLAP_CANDIDATE_ABORT`, the menu needs a palm release. Wait for `NEUTRAL` before ordinary gestures.
- A new hand id must be seen open (pinch distance >= 0.42) before its first pinch. Hand loss, `identity_ambiguous`,
  a frame gap > 200 ms, or a pinched hand DEGRADED/UNKNOWN for 200 ms emits `PINCH_END`.
- `identity_ambiguous` (or duplicate hand ids) outside a clap candidate ends everything (PINCH_END, dwell, neutral).
  Inside an active candidate it is treated as palm contact: the candidate survives, per-hand pinch state is
  dropped silently (ids may swap), and finger states are not read. Only frames with no hand at all count toward
  the 120 ms dropout. Separation needs two consecutive clean frames with two USABLE hands (any ids).
- `menu_dwell_progress` is 0..1 while dwelling and 0 after completion (until release).
- Clap accuracy on real camera footage: bekliyor (pending). Synthetic tests prove logic only.
