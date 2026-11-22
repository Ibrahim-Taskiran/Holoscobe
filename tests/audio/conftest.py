"""Audio test config: manual marker handling (real-device tests are skipped by default)."""
from __future__ import annotations

import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "manual: needs real hardware or UI; skipped by default")


def pytest_collection_modifyitems(config, items):
    if config.getoption("-m"):
        return
    skip = pytest.mark.skip(reason="manual test (use -m manual)")
    for item in items:
        if "manual" in item.keywords:
            item.add_marker(skip)
