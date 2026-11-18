from __future__ import annotations

import pytest

from handcontrol.windows import sound


@pytest.fixture(autouse=True)
def _reset():
    sound.reset_throttle()


def test_kinds_play_with_alias():
    got = []
    for i, kind in enumerate(("click", "command", "error")):
        sound.play(kind, backend=got.append, clock=lambda i=i: 10.0 + i)
    assert got == ["SystemDefault", "SystemAsterisk", "SystemHand"]


def test_unknown_kind_silent():
    got = []
    sound.play("zzz", backend=got.append)
    assert got == []


def test_throttle_80ms():
    got = []
    for t in (1.0, 1.05, 1.09):
        sound.play("click", backend=got.append, clock=lambda t=t: t)
    assert len(got) == 2


def test_backend_error_swallowed():
    def boom(_):
        raise RuntimeError("x")
    sound.play("error", backend=boom)
