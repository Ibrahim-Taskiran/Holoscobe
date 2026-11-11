"""Physical monitor enumeration and topology/work-area change notifications."""
from __future__ import annotations

import ctypes as C
import logging
import threading
from collections.abc import Callable, Sequence

from ..contracts import Monitor, Rect
from ._events import EventWindow
from ._win32 import DWORD, HANDLE, MONITORENUMPROC, MONITORINFO, bind, last_error, user32


class WindowsDisplayProvider:
    def __init__(self, on_change: Callable[[Sequence[Monitor]], None] | None = None) -> None:
        self._lock = threading.RLock()
        self._callbacks = [on_change] if on_change else []
        self._monitors: tuple[Monitor, ...] = ()
        self._events: EventWindow | None = None

    def monitors(self) -> tuple[Monitor, ...]:
        api = user32()
        shcore = C.WinDLL("shcore", use_last_error=True)
        get_dpi = bind(shcore, "GetDpiForMonitor", C.c_int32, HANDLE, C.c_int,
                       C.POINTER(DWORD), C.POINTER(DWORD))
        result: list[Monitor] = []
        errors: list[Exception] = []

        @MONITORENUMPROC
        def collect(handle, dc, rect, data):
            info = MONITORINFO(cbSize=C.sizeof(MONITORINFO))
            if not api.GetMonitorInfoW(handle, C.byref(info)):
                errors.append(OSError(last_error(), "GetMonitorInfoW failed"))
                return False
            dx, dy = DWORD(), DWORD()
            hr = get_dpi(handle, 0, C.byref(dx), C.byref(dy))
            if hr < 0 or not dx.value:
                errors.append(OSError(hr, "GetDpiForMonitor failed"))
                return False
            def convert(r):
                return Rect(r.left, r.top, r.right, r.bottom)
            result.append(Monitor(convert(info.rcMonitor), convert(info.rcWork), dx.value / 96, bool(info.dwFlags & 1)))
            return True

        success = api.EnumDisplayMonitors(None, None, collect, 0)
        if errors:
            raise errors[0]
        if not success or not result:
            raise OSError(last_error(), "EnumDisplayMonitors failed or no active monitors")
        return tuple(sorted(result, key=lambda m: (m.bounds.left, m.bounds.top)))

    def start(self, on_change: Callable[[Sequence[Monitor]], None] | None = None) -> None:
        """Callbacks run on the event thread; marshal GUI updates to the UI thread."""
        with self._lock:
            if on_change and on_change not in self._callbacks:
                self._callbacks.append(on_change)
            if self._events:
                return
            self._monitors = self.monitors()
            self._events = EventWindow(self._message)

    def _message(self, message: int, wp: int, lp: int) -> int | None:
        if message in (0x7E, 0x1A, 0x2E0):  # display, settings/work area, DPI
            current = self.monitors()
            if current != self._monitors:
                self._monitors = current
                for callback in tuple(self._callbacks):
                    try:
                        callback(current)
                    except Exception:
                        logging.getLogger(__name__).exception("Display change callback failed")
            return 0
        return None

    def close(self) -> None:
        events, self._events = self._events, None
        if events:
            events.close()
