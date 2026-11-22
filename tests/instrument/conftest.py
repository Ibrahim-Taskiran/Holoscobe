"""Fixtures for instrument tests. Builders live in instr_synth.py (uniquely named module)."""
from __future__ import annotations

import pytest

from handcontrol.instrument.engine import InstrumentConfig, InstrumentEngine


@pytest.fixture
def solo_engine() -> InstrumentEngine:
    return InstrumentEngine(InstrumentConfig(layout="solo"))


@pytest.fixture
def chord_engine() -> InstrumentEngine:
    return InstrumentEngine(InstrumentConfig(layout="chord"))
