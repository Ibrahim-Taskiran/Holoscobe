"""Tools test config: fakes only, nothing here touches a camera, window or the OS."""
from __future__ import annotations

import pytest
from _tools_fakes import FakeConsole


@pytest.fixture
def console():
    return FakeConsole()


@pytest.fixture
def out_dir(tmp_path):
    return tmp_path / "reports"
