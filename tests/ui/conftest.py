"""Pytest configuration for Holoscobe UI tests.

Enforces QT_QPA_PLATFORM=offscreen so no test ever opens a real window on screen.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "manual: interactive/manual UI showcase tests (skipped by default)",
    )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    markexpr = config.getoption("-m", default="")
    if "manual" in str(markexpr):
        return
    skip_manual = pytest.mark.skip(reason="Manual test skipped by default")
    for item in items:
        if "manual" in item.keywords:
            item.add_marker(skip_manual)


@pytest.fixture(scope="session", autouse=True)
def qapp() -> QApplication:
    """Provide an offscreen QApplication instance for all UI tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    assert os.environ.get("QT_QPA_PLATFORM") == "offscreen"
    return app
