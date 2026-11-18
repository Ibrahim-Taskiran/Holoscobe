"""COMMANDS mode through the real chain: raw landmarks -> features -> gestures -> controller."""
from __future__ import annotations

from handcontrol.contracts import ActionKind as A, Mode

from integ_synth import OPEN, PINCH, Rig, TARGET, hand, lerp


class Names:
    def __init__(self, exe: str) -> None:
        self.exe = exe

    def process_name(self, pid: int):
        return self.exe if pid == TARGET.pid else None


def _commands(exe: str = "chrome.exe") -> Rig:
    rig = Rig(process_names=Names(exe))
    rig.pipe.set_mode(Mode.COMMANDS)
    rig.activate([hand(OPEN, (220.0, 300.0))])
    rig.sink.clear()
    return rig


def _cmds(rig: Rig) -> list[str]:
    return [a.command for a in rig.sink.of(A.KEY_COMMAND)]


def test_open_palm_swipe_to_the_users_left_goes_forward_in_a_browser():
    rig = _commands("chrome.exe")
    rig.run(200, lambda u: [hand(OPEN, (lerp(220, 400, u), 300.0))])   # image x grows = user's left
    rig.run(600, lambda u: [hand(OPEN, (lerp(400, 220, u), 300.0))])   # slower return stroke
    rig.run(300, [hand(OPEN, (220.0, 300.0))])
    assert _cmds(rig) == ["browser_forward"]
    assert rig.count(A.MOVE_POINTER) == 0
    assert rig.ctl.snapshot().swipe_profile_active == "browser"


def test_short_pinch_plays_or_pauses_media():
    rig = _commands("spotify.exe")
    rig.run(150, [hand(PINCH, (220.0, 300.0))])
    rig.run(200, [hand(OPEN, (220.0, 300.0))])
    assert _cmds(rig) == ["media_play_pause"]


def test_paused_chain_sends_no_command():
    rig = _commands("powerpnt.exe")
    rig.pipe.pause()
    rig.sink.clear()
    rig.run(200, lambda u: [hand(OPEN, (lerp(220, 400, u), 300.0))])
    rig.run(150, [hand(PINCH, (400.0, 300.0))])
    rig.run(200, [hand(OPEN, (400.0, 300.0))])
    assert rig.count(A.KEY_COMMAND) == 0
