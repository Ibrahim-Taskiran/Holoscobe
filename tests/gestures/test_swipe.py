"""swipe.SwipeRecognizer thresholds and the COMMANDS profile tables."""
from __future__ import annotations

from typing import Optional

import pytest

from handcontrol.contracts import (FingerInfo, FingerName, FingerState, HandFeatures, Handedness, KeyCommand,
                                   Landmark, Quality)
from handcontrol.swipe import (SwipeDirection as D, SwipeRecognizer, direction_of, open_palm, pinch_command,
                               profile_for_process, resolve_profile, swipe_command)

S = 100.0   # palm scale px
DT = 33.3
REST = 250.0   # palm still long enough to arm the recognizer (rest_arm_ms = 180)


def palm(x: float, y: float, *, hid: int = 1, extended: int = 4, quality: Quality = Quality.USABLE) -> HandFeatures:
    order = (FingerName.INDEX, FingerName.MIDDLE, FingerName.RING, FingerName.LITTLE)
    states = {n: FingerState.EXTENDED if i < extended else FingerState.BENT for i, n in enumerate(order)}
    fingers = tuple(FingerInfo(n, states.get(n, FingerState.EXTENDED), 0.1) for n in FingerName)
    return HandFeatures(hid, Handedness.RIGHT, quality, (x, y), S, fingers, 1.0, (x, y - 80.0),
                        tuple(Landmark(0.5, 0.5) for _ in range(21)))


class Run:
    def __init__(self) -> None:
        self.r = SwipeRecognizer()
        self.t = 1000.0
        self.x, self.y = 320.0, 240.0
        self.fired: list[tuple[float, D]] = []

    def step(self, h: Optional[HandFeatures], dt: float = DT) -> Optional[D]:
        self.t += dt
        d = self.r.update(self.t, h)
        if d is not None:
            self.fired.append((self.t, d))
        return d

    def hold(self, ms: float, **kw) -> None:
        end = self.t + ms
        while self.t < end:
            self.step(palm(self.x, self.y, **kw))

    def move(self, dx_pu: float, dy_pu: float, ms: float, **kw) -> list[D]:
        n = max(1, round(ms / DT))
        x0, y0 = self.x, self.y
        out = []
        for i in range(1, n + 1):
            self.x, self.y = x0 + dx_pu * S * i / n, y0 + dy_pu * S * i / n
            d = self.step(palm(self.x, self.y, **kw), ms / n)
            if d is not None:
                out.append(d)
        return out


def test_user_left_is_increasing_image_x_on_the_unmirrored_frame():
    """Landmarks are on the UNMIRRORED camera frame and the camera faces the user: a hand moving to
    the user's own left appears moving to the image right (x grows)."""
    assert direction_of(+50, 0) is D.LEFT
    assert direction_of(-50, 0) is D.RIGHT
    assert direction_of(0, -50) is D.UP
    assert direction_of(0, +50) is D.DOWN
    w = Run()
    w.hold(REST)
    assert w.move(+1.6, 0.0, 200) == [D.LEFT]


@pytest.mark.parametrize("dx,dy,want", [(-1.6, 0, D.RIGHT), (0, -1.8, D.UP), (0, 1.8, D.DOWN), (1.6, 0.3, D.LEFT)])
def test_each_direction_fires_once(dx, dy, want):
    w = Run()
    w.hold(REST)
    assert w.move(dx, dy, 250) == [want]


def test_short_travel_does_not_fire():
    w = Run()
    w.hold(REST)
    assert w.move(1.0, 0.0, 200) == []


def test_slow_drift_does_not_fire():
    w = Run()
    w.hold(REST)
    assert w.move(3.0, 0.0, 1500) == []      # 2 pu/s: never 1.2 pu inside 400 ms


def test_travel_just_inside_the_window_fires_but_spread_over_longer_does_not():
    w = Run()
    w.hold(REST)
    assert w.move(1.3, 0.0, 370) == [D.LEFT]
    w2 = Run()
    w2.hold(REST)
    assert w2.move(1.3, 0.0, 600) == []


def test_diagonal_motion_fails_the_axis_ratio():
    w = Run()
    w.hold(REST)
    assert w.move(1.5, 1.0, 250) == []       # 1.5 : 1.0 < 2 : 1


def test_closed_hand_does_not_swipe():
    w = Run()
    w.hold(100, extended=2)
    assert w.move(1.6, 0.0, 200, extended=2) == []
    w2 = Run()
    w2.hold(REST, extended=3)
    assert w2.move(1.6, 0.0, 200, extended=3) == [D.LEFT]   # 3 of 4 open is enough


def test_degraded_hand_does_not_swipe():
    w = Run()
    w.hold(100, quality=Quality.DEGRADED)
    assert w.move(1.6, 0.0, 200, quality=Quality.DEGRADED) == []


def test_return_stroke_is_locked_and_cooldown_blocks_repeats():
    w = Run()
    w.hold(REST)
    assert w.move(1.6, 0.0, 200) == [D.LEFT]
    assert w.move(-1.6, 0.0, 250) == []      # return stroke inside the 700 ms opposite lock
    w.hold(500)
    assert w.move(-1.6, 0.0, 200) == [D.RIGHT]   # a deliberate opposite swipe later fires


def test_same_direction_repeats_after_the_cooldown():
    w = Run()
    w.hold(REST)
    assert w.move(1.6, 0.0, 200) == [D.LEFT]
    assert w.move(1.6, 0.0, 200) == []       # inside the 500 ms cooldown
    w.hold(400)
    assert w.move(1.6, 0.0, 200) == [D.LEFT]
    assert len(w.fired) == 2


def test_vertical_swipe_inside_the_cooldown_is_blocked():
    w = Run()
    w.hold(REST)
    assert w.move(1.6, 0.0, 200) == [D.LEFT]
    assert w.move(0.0, -1.6, 200) == []


def test_tracking_gap_resets_history():
    w = Run()
    w.hold(REST)
    w.move(0.8, 0.0, 120)
    w.step(None)                               # hand lost for a frame
    assert w.move(0.8, 0.0, 120) == []
    w2 = Run()
    w2.hold(REST)
    w2.move(0.8, 0.0, 120)
    w2.t += 200.0                              # frame gap longer than max_gap_ms
    assert w2.move(0.8, 0.0, 120) == []


def test_new_hand_id_resets_history():
    w = Run()
    w.hold(REST)
    w.move(0.8, 0.0, 120)
    assert w.move(0.8, 0.0, 120, hid=2) == []


def test_reset_keeps_the_opposite_lock():
    w = Run()
    w.hold(REST)
    assert w.move(1.6, 0.0, 200) == [D.LEFT]
    w.r.reset()
    w.hold(300)                                # re-armed, still inside the 700 ms opposite lock
    assert w.move(-1.6, 0.0, 250) == []


# ---------------------------------------------------------------- rest arm / strict vertical


def sway(w: Run, ms: float, amp_pu: float = 0.05) -> None:
    """A raised hand that is held but never still: frame-to-frame tremor of ~1.5 pu/s."""
    end, k = w.t + ms, 0
    while w.t < end:
        k += 1
        w.x += (amp_pu if k % 2 else -amp_pu) * S
        w.step(palm(w.x, w.y))


def test_fresh_recognizer_needs_rest_before_the_first_swipe():
    w = Run()
    assert w.move(1.6, 0.0, 200) == []         # no rest seen yet
    w.hold(REST)
    assert w.move(1.6, 0.0, 200) == [D.LEFT]


def test_reset_requires_rest_again():
    w = Run()
    w.hold(REST)
    w.r.reset()
    assert w.move(1.6, 0.0, 200) == []
    w.hold(REST)
    assert w.move(1.6, 0.0, 200) == [D.LEFT]


def test_swipe_then_held_hand_then_drop_fires_once():
    """The reported bug: swipe left, keep the hand up ~0.7 s, then lower it -> only the swipe."""
    w = Run()
    w.hold(REST)
    assert w.move(1.6, 0.0, 200) == [D.LEFT]
    sway(w, 700)
    assert w.move(0.0, 2.0, 300) == []
    assert w.move(0.0, -2.0, 300) == []        # and raising it again
    assert [d for _, d in w.fired] == [D.LEFT]


@pytest.mark.parametrize("dy", [-2.0, 2.0], ids=["raise", "drop"])
def test_swipe_then_immediate_raise_or_drop_fires_once(dy):
    w = Run()
    w.hold(REST)
    assert w.move(1.6, 0.0, 200) == [D.LEFT]
    assert w.move(0.0, dy, 300) == []
    assert w.move(0.0, -dy, 600) == []         # slower way back, still no rest
    assert len(w.fired) == 1


def test_any_fire_blocks_every_direction_until_rest():
    w = Run()
    w.hold(REST)
    assert w.move(1.6, 0.0, 200) == [D.LEFT]
    sway(w, 700)                               # past cooldown and opposite lock, never still
    assert w.move(-1.6, 0.0, 200) == []
    assert w.move(1.6, 0.0, 200) == []
    w.hold(REST)
    assert w.move(-1.6, 0.0, 200) == [D.RIGHT]


def test_deliberate_vertical_swipe_from_rest_fires():
    w = Run()
    w.hold(REST)
    assert w.move(0.0, 1.8, 250) == [D.DOWN]
    assert swipe_command("browser", D.DOWN) is KeyCommand.SHOW_DESKTOP


def test_vertical_needs_more_travel_than_horizontal():
    w = Run()
    w.hold(REST)
    assert w.move(0.0, 1.4, 200) == []         # enough for a horizontal swipe, not a vertical one
    w2 = Run()
    w2.hold(REST)
    assert w2.move(1.4, 0.0, 200) == [D.LEFT]


def test_vertical_after_activity_without_a_fresh_rest_does_not_fire():
    w = Run()
    w.hold(REST)                               # armed
    w.move(0.6, 0.0, 300)                      # some activity, no swipe
    assert w.fired == []
    assert w.move(0.0, 2.0, 300) == []         # drop straight after: not from rest
    w.hold(REST)
    assert w.move(0.0, 1.8, 250) == [D.DOWN]


def test_two_left_swipes_separated_by_rest_fire_twice():
    w = Run()
    w.hold(REST)
    assert w.move(1.6, 0.0, 200) == [D.LEFT]
    w.hold(REST)
    w.move(-1.6, 0.0, 600)                     # slow return, no swipe
    w.hold(REST)
    assert w.move(1.6, 0.0, 200) == [D.LEFT]
    assert len(w.fired) == 2


def test_hand_entering_the_frame_moving_down_does_not_fire():
    w = Run()
    w.step(None)
    w.step(None)
    assert w.move(0.0, 2.0, 300) == []
    assert w.move(1.6, 0.0, 200) == []         # still never at rest
    assert w.fired == []


def test_open_palm_counts_index_to_little():
    assert open_palm(palm(0, 0, extended=3)) and not open_palm(palm(0, 0, extended=2))


# ---------------------------------------------------------------- profiles


@pytest.mark.parametrize("profile,left,right", [
    ("slides", KeyCommand.NEXT, KeyCommand.PREVIOUS),
    ("browser", KeyCommand.BROWSER_FORWARD, KeyCommand.BROWSER_BACK),
    ("media", KeyCommand.MEDIA_NEXT, KeyCommand.MEDIA_PREVIOUS),
    ("desktops", KeyCommand.DESKTOP_RIGHT, KeyCommand.DESKTOP_LEFT),
])
def test_profile_table(profile, left, right):
    assert swipe_command(profile, D.LEFT) is left
    assert swipe_command(profile, D.RIGHT) is right
    assert swipe_command(profile, D.UP) is KeyCommand.TASK_VIEW
    assert swipe_command(profile, D.DOWN) is KeyCommand.SHOW_DESKTOP
    assert pinch_command(profile) is (KeyCommand.NEXT if profile == "slides" else KeyCommand.MEDIA_PLAY_PAUSE)


@pytest.mark.parametrize("names,profile", [
    (("powerpnt.exe", "soffice.bin", "acrord32.exe", "acrobat.exe", "sumatrapdf.exe", "foxitpdfreader.exe",
      "microsoft.photos.exe", "photos.exe"), "slides"),
    (("chrome.exe", "msedge.exe", "firefox.exe", "opera.exe", "brave.exe", "vivaldi.exe", "explorer.exe"), "browser"),
    (("spotify.exe", "vlc.exe", "wmplayer.exe", "music.ui.exe", "applemusic.exe", "mpc-hc64.exe"), "media"),
    (("notepad.exe", "", None), "desktops"),
])
def test_profile_for_process(names, profile):
    for n in names:
        assert profile_for_process(n) == profile


def test_profile_for_process_ignores_case():
    assert profile_for_process("POWERPNT.EXE") == "slides"


def test_resolve_profile():
    assert resolve_profile("media", "powerpnt.exe") == "media"
    assert resolve_profile("auto", "powerpnt.exe") == "slides"
    assert resolve_profile("auto", None) == "desktops"
    assert resolve_profile("bogus", "chrome.exe") == "browser"


def test_unknown_profile_falls_back_to_desktops():
    assert swipe_command("bogus", D.LEFT) is KeyCommand.DESKTOP_RIGHT
