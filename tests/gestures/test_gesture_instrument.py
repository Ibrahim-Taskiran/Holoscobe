"""Instrument profile (Mode.INSTRUMENT): the playing pose never claps or opens the mode menu.

Landmark hands through the real FeatureExtractor, capture_ms timeline at 30 fps (and 15 fps).
"""
from __future__ import annotations

import pytest

from gest_landmarks import (CLAP_KINDS, FOUR, LOOSE, ND, OPEN, PICK, STRING, Chain, clap_path, hand, left, lerp,
                            right_at, strum)
from handcontrol.contracts import GestureKind as G, Handedness
from handcontrol.gestures import GestureConfig, GestureRecognizer

V = {"thumb": 1.0, "index": 0.0, "middle": 0.0, "ring": 1.0, "little": 1.0}
FPS = pytest.mark.parametrize("fps", [30.0, 15.0], ids=["30fps", "15fps"])


def test_profile_switch_api_defaults_off():
    gr = GestureRecognizer()
    assert gr.instrument_profile is False
    gr.set_instrument_profile(True)
    assert gr.instrument_profile is True
    gr.reset()
    assert gr.instrument_profile is True        # reset() keeps the profile; the pipeline owns it
    gr.set_instrument_profile(False)
    assert gr.instrument_profile is False
    cfg = GestureConfig()
    assert cfg.instrument_clap_min_extended_non_thumb == 4 and cfg.menu_dwell_ms == 500.0


# ---------------------------------------------------------------- (a) strum


@FPS
def test_fast_strum_never_claps_or_opens_menu(fps):
    ch = Chain(instrument=True, fps=fps)
    ch.run(400, [right_at(2.6, PICK), left(STRING)])
    strum(ch, 3000)
    assert ch.min_pair_pu < 0.8                  # the hands really came close
    assert not ch.kinds() & (CLAP_KINDS | {G.MENU_DWELL_COMPLETE})


@pytest.mark.parametrize("pick", [PICK, LOOSE, OPEN], ids=["pick", "loose_pick", "open_pick"])
def test_strum_with_noisy_pick_hand_finger_reads_never_claps(pick):
    """The pick hand may read 3 or even 4 fingers open while strumming; the string hand never does."""
    ch = Chain(instrument=True)
    ch.run(400, [right_at(2.6, pick), left(STRING)])
    strum(ch, 3000, pick=pick, period_ms=220.0)
    assert not ch.kinds() & (CLAP_KINDS | {G.MENU_DWELL_COMPLETE})


def test_strum_legacy_profile_also_silent():
    """Same fixture with the profile OFF: the legacy recognizer does not clap on it either."""
    ch = Chain(instrument=False)
    ch.run(400, [right_at(2.6, PICK), left(STRING)])
    strum(ch, 3000)
    assert not ch.kinds() & {G.CLAP, G.CLAP_CANDIDATE_START, G.MENU_DWELL_COMPLETE}


# ---------------------------------------------------------------- (b) approach while playing


@pytest.mark.parametrize("poses", [(PICK, STRING), (LOOSE, LOOSE), (OPEN, STRING), (LOOSE, FOUR)],
                         ids=["pick_string", "loose_loose", "open_string", "loose_four"])
def test_fast_approach_in_playing_poses_no_clap_events(poses):
    ch = clap_path(Chain(instrument=True), *poses)
    assert not ch.kinds() & CLAP_KINDS


def test_loose_pose_approach_claps_in_legacy_profile_only():
    """Proves the switch: 3 non-thumb fingers is a clap for the legacy profile, not for instrument."""
    assert G.CLAP in clap_path(Chain(instrument=False), LOOSE, LOOSE).kinds()
    assert not clap_path(Chain(instrument=True), LOOSE, LOOSE).kinds() & CLAP_KINDS


def test_arm_open_then_switch_to_playing_pose_before_approach_does_not_clap():
    """Armed with open palms, then the hands take the playing pose and come together fast."""
    ch = Chain(instrument=True)
    ch.run(300, [right_at(3.0, OPEN), left(OPEN)])
    ch.run(200, [right_at(3.0, LOOSE), left(STRING)])
    ch.run(240, lambda u: [right_at(lerp(3.0, 0.45, u), LOOSE), left(STRING)])
    ch.run(240, lambda u: [right_at(lerp(0.45, 3.0, u), LOOSE), left(STRING)])
    assert not ch.kinds() & CLAP_KINDS


# ---------------------------------------------------------------- (c) real clap still works


@FPS
def test_open_palm_clap_with_profile_on(fps):
    ch = clap_path(Chain(instrument=True, fps=fps))
    assert ch.count(G.CLAP) == 1 and ch.count(G.CLAP_CANDIDATE_START) == 1


# ---------------------------------------------------------------- (d) menu dwell


def _hold_left(ch: Chain, pose, ms: float) -> Chain:
    return ch.run(ms, [right_at(2.6, PICK), left(pose)])


@pytest.mark.parametrize("instrument", [True, False], ids=["instrument", "legacy"])
def test_v_opens_the_wheel(instrument):
    ch = _hold_left(Chain(instrument=instrument), V, 900)
    assert ch.count(G.MENU_DWELL_COMPLETE) == 1


def test_string_pose_held_never_opens_menu():
    for instrument in (True, False):
        ch = _hold_left(Chain(instrument=instrument), STRING, 1500)
        assert ch.count(G.MENU_DWELL_COMPLETE) == 0
        assert ch.gr.menu_dwell_progress == 0.0


@pytest.mark.parametrize("pose", [FOUR, OPEN], ids=["four", "open"])
def test_open_hands_never_open_the_wheel(pose):
    for instrument in (True, False):
        assert _hold_left(Chain(instrument=instrument), pose, 1500).count(G.MENU_DWELL_COMPLETE) == 0


def test_menu_dwell_needs_a_still_hand_in_instrument_profile():
    """A 0.13 pu wobble every 300 ms keeps restarting the stricter dwell (legacy 0.15 pu tolerates it)."""
    def drift(u: float):
        return [right_at(2.6, PICK), left(V, (ND[0], 300.0 + 13.0 * (int(u * 1500 // 300) % 2)))]
    assert Chain(instrument=True).run(1500, drift).count(G.MENU_DWELL_COMPLETE) == 0
    assert Chain(instrument=False).run(1500, drift).count(G.MENU_DWELL_COMPLETE) == 1


def test_menu_dwell_not_advanced_while_strumming():
    ch = Chain(instrument=True)
    strum(ch, 1500)
    assert ch.count(G.MENU_DWELL_COMPLETE) == 0 and ch.gr.menu_dwell_progress == 0.0
    _hold_left(ch, V, 900)                       # stop playing, left V: wheel
    assert ch.count(G.MENU_DWELL_COMPLETE) == 1


# ---------------------------------------------------------------- (e) crossing


@pytest.mark.parametrize("pose", [OPEN, PICK], ids=["open", "pick"])
def test_hands_crossing_never_clap(pose):
    ch = Chain(instrument=True)
    ch.run(300, [right_at(3.0, pose), left(OPEN)])
    ch.run(400, lambda u: [right_at(lerp(3.0, -2.5, u), pose), left(OPEN)])   # right hand passes the left
    ch.run(300, [right_at(-2.5, pose), left(OPEN)])
    assert G.CLAP not in ch.kinds()


# ---------------------------------------------------------------- (f) identity swap / ambiguity mid-strum


def test_identity_swap_and_merged_frames_mid_strum():
    ch = Chain(instrument=True)
    ch.run(400, [right_at(2.6, PICK), left(STRING)])
    strum(ch, 800)
    for _ in range(3):                           # tracker swaps the labels
        ch.frame([hand(PICK, (ND[0] - 80.0, 300.0), side="right", label=Handedness.LEFT),
                  hand(STRING, ND, side="left", label=Handedness.RIGHT)])
    for _ in range(3):                           # palms overlap: one merged hand
        ch.frame([hand(STRING, ND, side="left", score=0.6)])
    ch.frame([right_at(0.4, PICK), left(STRING), hand(OPEN, (100.0, 100.0))])   # 3 hands
    strum(ch, 800)
    for _ in range(4):
        ch.frame([hand(OPEN, ND, side="left", label=Handedness.UNKNOWN)])
    strum(ch, 600)
    assert ch.ambiguous_frames > 0
    assert not ch.kinds() & (CLAP_KINDS | {G.MENU_DWELL_COMPLETE})
