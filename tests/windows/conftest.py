"""Windows tests never invoke real desktop adapters."""
from __future__ import annotations

import sys

import pytest

# Also protect shared source paths from bytecode writes during collection.
sys.dont_write_bytecode = True


def pytest_configure(config) -> None:
    config.addinivalue_line("markers", "manual: interacts with the real Windows desktop")


def pytest_collection_modifyitems(config, items) -> None:
    for item in items:
        if "manual" in item.keywords:
            item.add_marker(pytest.mark.skip(reason="Hardware checks must be performed separately"))
