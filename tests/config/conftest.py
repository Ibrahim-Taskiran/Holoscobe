"""Config test config: manual marker handling and a unicode temp path."""
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


@pytest.fixture
def settings_path(tmp_path):
    return tmp_path / "Ayarlar klasörü çğış" / "settings.json"
