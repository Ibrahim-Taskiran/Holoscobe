"""Fixtures for feature tests. The synthetic hand generator lives in feat_synth.py
(a uniquely named module, so it never collides with other folders' conftest.py)."""
from __future__ import annotations

import pytest

from feat_synth import make_frame, make_hand


@pytest.fixture
def hand_factory():
    return make_hand


@pytest.fixture
def frame_factory():
    return make_frame
