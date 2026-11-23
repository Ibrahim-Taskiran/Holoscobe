"""COMMANDS mode (swipes / short pinch -> KEY_COMMAND), dwell click, auto pause and the snapshot hold
progress fields. Synthetic HandFeatures; relative pointer defaults unless noted."""
from __future__ import annotations

from typing import Optional

import pytest
from ctrl_helpers import LEFT, RIGHT, WIN_A, G, K, Rig, tcfg
from ctrl_helpers import posed
from test_ctrl_relative import FPS, hold, rcfg, rh, rig, stroke

from handcontrol.contracts import ControlState, KeyCommand, Mode
from handcontrol.controller import AUTO_PAUSE_REASON

PALM = (320.0, 300.0)
PU = 60.0          # rh() palm scale


class Names:
    def __init__(self, by_pid: dict[int, str]) -> None:
        self.by_pid = by_pid
        self.calls = 0

    def process_name(self, pid: int) -> Optional[str]:
        self.calls += 1
        return self.by_pid.get(pid)


def crig(profile: str = "auto", exe: Optional[str] = None, active: bool = True, **kw) -> Rig:
    names = Names({WIN_A.pid: exe}) if exe is not None else None
    r = Rig(cfg=rcfg(swipe_profile=profile, **kw), process_names=names, active=active)
    r.ctl.set_mode(Mode.COMMANDS)
    if active:
        r.settle(rh(PALM, "open"))
        hold(r, PALM, 250, 33.4, "open")     # palm at rest arms the swipe recognizer
    r.sink.clear()
    return r


def swipe(r: Rig, dx_pu: float, dy_pu: float = 0.0, ms: float = 200.0, dt: float = 33.4, start=PALM, **kw):
    end = (start[0] + dx_pu * PU, start[1] + dy_pu * PU)
    stroke(r, start, end, ms, dt, "open", **kw)
    return end


def cmds(r: Rig) -> list[str]:
    return [a.command for a in r.sink.of(K.KEY_COMMAND)]


def test_mode_label_and_profile_shown_only_in_commands_mode():
    r = crig("slides")
    s = r.ctl.snapshot()
    assert s.reason == "Kip: Komutlar" and s.swipe_profile_active == "slides"
    r.ctl.set_mode(Mode.POINTER)
    assert r.ctl.snapshot().swipe_profile_active == ""


@FPS
def test_auto_profile_swipe_left_in_browser_goes_forward_without_pointer_motion(dt):
    r = crig("auto", "chrome.exe")
    swipe(r, +1.8, dt=dt)            # image x grows = the user's left
    assert cmds(r) == [KeyCommand.BROWSER_FORWARD.value]
    assert r.count(K.MOVE_POINTER) == 0
    s = r.ctl.snapshot()
    assert s.last_command == "browser_forward" and s.command_seq == 1 and s.swipe_profile_active == "browser"
    assert s.notice.startswith("Komut:")


def test_auto_profile_follows_the_foreground_process():
    r = crig("auto", "powerpnt.exe")
    end = swipe(r, -1.8)
    assert cmds(r) == ["previous"]
    hold(r, end, 800, 33.4, "open")
    swipe(r, 0.0, -1.8, start=end)
    assert cmds(r) == ["previous", "task_view"]
    assert r.ctl.snapshot().command_seq == 2


def test_auto_without_process_names_uses_desktops():
    r = crig("auto")
    swipe(r, +1.8)
    assert cmds(r) == ["desktop_right"]


def test_explicit_profile_ignores_the_process():
    r = crig("media", "powerpnt.exe")
    swipe(r, +1.8)
    assert cmds(r) == ["media_next"]


def test_return_stroke_does_not_fire():
    r = crig("slides")
    end = swipe(r, +1.8)
    swipe(r, -1.8, start=end, ms=250)
    hold(r, PALM, 600, 33.4, "open")
    assert cmds(r) == ["next"]


def _sway(r: Rig, at, ms: float, amp_pu: float = 0.05) -> None:
    """Hand held up after a swipe but never still (frame-to-frame tremor ~1.5 pu/s)."""
    for k in range(int(round(ms / 33.4))):
        r.frame(rh((at[0] + (amp_pu * PU if k % 2 else 0.0), at[1]), "open"))


def test_swipe_hold_then_lowering_the_hand_sends_one_command():
    """Reported bug: browser swipe left, hand kept up ~0.7 s, then lowered -> Show Desktop fired."""
    r = crig("browser")
    end = swipe(r, +1.8)
    _sway(r, end, 700)
    low = swipe(r, 0.0, +2.0, ms=300, start=end)
    assert cmds(r) == ["browser_forward"]
    swipe(r, 0.0, -2.0, ms=300, start=low)            # raising it again
    assert cmds(r) == ["browser_forward"]


@pytest.mark.parametrize("dy", [-2.0, 2.0], ids=["raise", "drop"])
def test_swipe_then_immediate_vertical_motion_sends_one_command(dy):
    r = crig("browser")
    end = swipe(r, +1.8)
    swipe(r, 0.0, dy, ms=300, start=end)
    assert cmds(r) == ["browser_forward"]


def test_deliberate_down_swipe_from_rest_shows_the_desktop():
    r = crig("browser")
    swipe(r, 0.0, +1.8, ms=250)
    assert cmds(r) == ["show_desktop"]


def test_two_swipes_separated_by_rest_send_two_commands():
    r = crig("slides")
    end = swipe(r, +1.8)
    hold(r, end, 600, 33.4, "open")
    swipe(r, +1.8, start=end)
    assert cmds(r) == ["next", "next"]


def test_hand_entering_the_frame_moving_down_sends_nothing():
    r = crig("browser")
    for _ in range(5):
        r.frame()                                      # no hand
    swipe(r, 0.0, +2.0, ms=300, start=(PALM[0], PALM[1] - 120.0))
    assert cmds(r) == []


def test_slow_drift_sends_nothing():
    r = crig("slides")
    stroke(r, PALM, (PALM[0] + 3 * PU, PALM[1]), 3000, 33.4, "open")   # peak 2 pu/s
    assert cmds(r) == []


def test_pointing_hand_does_not_swipe():
    r = crig("slides")
    stroke(r, PALM, (PALM[0] + 2 * PU, PALM[1]), 200, 33.4, "point")
    assert cmds(r) == [] and r.count(K.MOVE_POINTER) == 0


@pytest.mark.parametrize("profile,want", [("slides", "next"), ("browser", "media_play_pause"), ("auto", "media_play_pause")])
def test_short_pinch_sends_the_profile_pinch_command(profile, want):
    r = crig(profile)
    r.frame(rh(PALM, "open", idx=0.1), events=[(G.PINCH_START, RIGHT)])
    hold(r, PALM, 150, 33.4, "open", idx=0.1)
    assert cmds(r) == []
    r.frame(rh(PALM, "open"), events=[(G.PINCH_END, RIGHT)])
    assert cmds(r) == [want]


def test_long_pinch_sends_nothing():
    r = crig("slides")
    r.frame(rh(PALM, "open", idx=0.1), events=[(G.PINCH_START, RIGHT)])
    hold(r, PALM, 700, 33.4, "open", idx=0.1)
    r.frame(rh(PALM, "open"), events=[(G.PINCH_END, RIGHT)])
    assert cmds(r) == []


def test_moving_pinch_sends_nothing_and_never_swipes():
    r = crig("slides")
    r.frame(rh(PALM, "open", idx=0.1), events=[(G.PINCH_START, RIGHT)])
    stroke(r, PALM, (PALM[0] + 2 * PU, PALM[1]), 200, 33.4, "open", idx=0.1)
    r.frame(rh((PALM[0] + 2 * PU, PALM[1]), "open"), events=[(G.PINCH_END, RIGHT)])
    assert cmds(r) == []


def test_nothing_when_paused():
    r = crig("slides", active=False)
    for _ in range(8):
        r.frame(rh(PALM, "open"))
    swipe(r, +1.8)
    r.frame(rh(PALM, "open", idx=0.1), events=[(G.PINCH_START, RIGHT)])
    r.frame(rh(PALM, "open"), events=[(G.PINCH_END, RIGHT)])
    assert r.count(K.KEY_COMMAND) == 0


def test_clap_candidate_suppresses_and_resets_a_swipe():
    r = crig("slides")
    mid = swipe(r, +0.9, ms=100)
    r.frame(rh(mid, "open"), events=[(G.CLAP_CANDIDATE_START,)])
    swipe(r, +0.9, ms=100, start=mid)
    assert cmds(r) == []


def test_identity_ambiguity_resets_a_swipe():
    r = crig("slides")
    mid = swipe(r, +0.9, ms=100)
    r.frame(rh(mid, "open"), ambiguous=True)
    swipe(r, +0.7, ms=100, start=mid)
    assert cmds(r) == []


def test_no_commands_while_the_mode_menu_is_open():
    r = crig("slides")
    left = rh((500.0, 300.0), "open", hid=LEFT)
    r.settle(rh(PALM, "open"), left)
    r.frame(rh(PALM, "open"), posed("v"), events=[(G.MENU_DWELL_COMPLETE, LEFT)])
    assert r.ctl.snapshot().menu is not None
    stroke(r, PALM, (PALM[0] + 2 * PU, PALM[1]), 200, 33.4, "open")
    assert cmds(r) == []


def test_refused_command_does_not_count():
    r = crig("slides")
    r.sink.accept = False
    swipe(r, +1.8)
    s = r.ctl.snapshot()
    assert s.command_seq == 0 and s.last_command == "" and s.notice == "Komut gönderilemedi"


# ---------------------------------------------------------------- dwell click


def _dwell_rig(dt: float, **kw) -> Rig:
    return rig(dt, dwell_click=True, dwell_ms=1000.0, **kw)


@FPS
def test_dwell_clicks_once_after_moving_and_resting(dt):
    r = _dwell_rig(dt)
    end = stroke(r, PALM, (380.0, 300.0), 300, dt)
    assert r.count(K.LEFT_CLICK) == 0
    hold(r, end, 700, dt)
    assert r.count(K.LEFT_CLICK) == 0
    hold(r, end, 500, dt)
    clicks = r.sink.of(K.LEFT_CLICK)
    assert len(clicks) == 1
    hold(r, end, 2000, dt)
    assert r.count(K.LEFT_CLICK) == 1            # re-arming needs leaving the radius
    end2 = stroke(r, end, (440.0, 300.0), 300, dt)
    hold(r, end2, 1300, dt)
    assert r.count(K.LEFT_CLICK) == 2


def test_dwell_needs_movement_first():
    r = _dwell_rig(33.4)
    hold(r, PALM, 2500, 33.4)
    assert r.count(K.LEFT_CLICK) == 0


def test_dwell_off_by_default():
    r = rig(33.4)
    end = stroke(r, PALM, (380.0, 300.0), 300, 33.4)
    hold(r, end, 2000, 33.4)
    assert r.count(K.LEFT_CLICK) == 0


def test_dwell_cancelled_by_disengage():
    r = _dwell_rig(33.4)
    end = stroke(r, PALM, (380.0, 300.0), 300, 33.4)
    hold(r, end, 600, 33.4)
    hold(r, end, 400, 33.4, "open")               # clutch: disengaged
    hold(r, end, 1200, 33.4)                      # re-engaged, but never moved since
    assert r.count(K.LEFT_CLICK) == 0


def test_dwell_cancelled_by_tracking_gap():
    r = _dwell_rig(33.4)
    end = stroke(r, PALM, (380.0, 300.0), 300, 33.4)
    hold(r, end, 600, 33.4)
    r.frame()                                     # no hand
    hold(r, end, 1200, 33.4)
    assert r.count(K.LEFT_CLICK) == 0


def test_dwell_snapshot_progress():
    r = _dwell_rig(33.4)
    end = stroke(r, PALM, (380.0, 300.0), 300, 33.4)
    hold(r, end, 100, 33.4)
    assert r.ctl.snapshot().hold_kind == ""
    hold(r, end, 400, 33.4)
    s = r.ctl.snapshot()
    assert s.hold_kind == "dwell" and 0.3 < s.hold_progress < 0.7


# ---------------------------------------------------------------- auto pause


def test_auto_pause_after_no_hand():
    r = Rig(cfg=tcfg(auto_pause_ms=3000.0))
    r.settle(rh(PALM))
    for _ in range(80):                            # ~2.7 s
        r.frame()
    assert r.ctl.snapshot().state is ControlState.ACTIVE
    for _ in range(15):
        r.frame()
    s = r.ctl.snapshot()
    assert s.state is ControlState.PAUSED and s.reason == AUTO_PAUSE_REASON


def test_auto_pause_on_tick_without_frames():
    r = Rig(cfg=tcfg(auto_pause_ms=3000.0))
    r.settle(rh(PALM))
    r.clock.advance(3100)
    r.ctl.tick()
    assert r.ctl.snapshot().state is ControlState.PAUSED


def test_seen_hand_keeps_active_and_zero_is_off():
    r = Rig(cfg=tcfg(auto_pause_ms=3000.0))
    for _ in range(150):
        r.frame(rh(PALM))
    assert r.ctl.snapshot().state is ControlState.ACTIVE
    off = Rig(cfg=tcfg())
    for _ in range(300):
        off.frame()
    off.clock.advance(20000)
    off.ctl.tick()
    assert off.ctl.snapshot().state is ControlState.ACTIVE


# ---------------------------------------------------------------- hold progress


def test_long_press_right_click_hold_progress():
    dt = 33.4
    r = rig(dt)
    r.frame(rh(PALM, idx=0.1), events=[(G.PINCH_START, RIGHT)], dt=dt)
    hold(r, PALM, 66, dt, idx=0.1)
    assert r.ctl.snapshot().hold_kind == ""        # shown only after 150 ms
    hold(r, PALM, 334, dt, idx=0.1)
    s = r.ctl.snapshot()
    assert s.hold_kind == "right_click" and 0.4 < s.hold_progress < 0.6
    hold(r, PALM, 500, dt, idx=0.1)
    assert r.count(K.RIGHT_CLICK) == 1
    assert r.ctl.snapshot().hold_kind == ""


def test_fist_hold_progress():
    from dataclasses import replace

    from handcontrol.contracts import FingerInfo, FingerState
    r = Rig()
    for _ in range(8):
        r.frame(rh(PALM, "open"))
    f = rh(PALM, "open")
    f = replace(f, fingers=tuple(FingerInfo(x.name, FingerState.BENT, 0.95) for x in f.fingers))
    for _ in range(5):
        r.frame(f)
    s = r.ctl.snapshot()
    assert s.hold_kind == "fist" and 0.3 < s.hold_progress < 1.0
