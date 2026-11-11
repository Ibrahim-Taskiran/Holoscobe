"""Integration fixtures. The raw-landmark generator and rig live in integ_synth.py
(a uniquely named module, so it never collides with other folders' helpers)."""
from __future__ import annotations

import pytest

from integ_synth import Rig


@pytest.fixture
def rig() -> Rig:
    return Rig()
