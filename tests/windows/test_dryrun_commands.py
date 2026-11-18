from __future__ import annotations

from handcontrol.contracts import Action, ActionKind, KeyCommand
from handcontrol.dryrun import DryRunSink, describe_action
from handcontrol.windows.commands import COMMAND_LABELS_TR


def act(cmd):
    return Action(ActionKind.KEY_COMMAND, 0, 0.0, command=cmd)


def test_next_text():
    assert describe_action(act("next")) == "Komut: Sonraki (Sağ ok)"


def test_all_commands_described_with_label():
    for cmd in KeyCommand:
        assert describe_action(act(cmd.value)).startswith(f"Komut: {COMMAND_LABELS_TR[cmd]}")


def test_unknown_command():
    assert "bilinmeyen" in describe_action(act("zz"))
    assert "boş" in describe_action(act(""))


def test_dryrun_records():
    s = DryRunSink()
    assert s.dispatch(act("volume_mute")) and s.last_text.startswith("Komut: Sesi kapat/aç")
