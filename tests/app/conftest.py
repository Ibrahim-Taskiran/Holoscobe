from __future__ import annotations
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

import pytest


@pytest.fixture(autouse=True)
def _no_real_cursor(monkeypatch):
    """Runtime defaults to the real GetCursorPos reader; tests must never read the OS cursor."""
    import handcontrol.app as app
    monkeypatch.setattr(app, 'read_os_cursor', lambda **_: None)
