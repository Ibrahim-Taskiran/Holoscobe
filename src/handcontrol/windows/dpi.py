"""Call before constructing any UI window or starting adapter threads."""
from __future__ import annotations

from ._win32 import user32


def enable_per_monitor_v2() -> bool:
    """Return False if awareness cannot be set or was set incompatibly earlier."""
    api = user32()
    if api.SetProcessDpiAwarenessContext(-4):
        return True
    # A manifest or an earlier call may already have selected PMv2.
    return bool(api.AreDpiAwarenessContextsEqual(api.GetThreadDpiAwarenessContext(), -4))
