"""Windows adapters. Importing this package does not touch the desktop."""
from __future__ import annotations

from .audio import WindowsVolumeControl
from .displays import WindowsDisplayProvider
from .dpi import enable_per_monitor_v2
from .hotkey import WindowsHotkey
from .input import WindowsInput
from .session import WindowsSession
from .sink import WindowsActionSink
from .window import WindowsWindowQuery

__all__ = ["WindowsVolumeControl", "WindowsDisplayProvider", "enable_per_monitor_v2",
           "WindowsHotkey", "WindowsInput", "WindowsSession", "WindowsActionSink",
           "WindowsWindowQuery"]
