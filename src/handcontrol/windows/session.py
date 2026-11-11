"""Session lock/unlock and suspend/resume notifications; no automatic rearm."""
from __future__ import annotations

import ctypes as C
from collections.abc import Callable

from ._events import EventWindow
from ._win32 import BOOL, DWORD, HANDLE, bind, last_error


class WindowsSession:
    def __init__(self, callback: Callable[[str], None]) -> None:
        self.callback = callback
        self._events: EventWindow | None = None
        self._wts = None
        self._registered = False

    def _message(self, message: int, wp: int, lp: int) -> int | None:
        if message == 0x2B1:  # WM_WTSSESSION_CHANGE
            event = {7: "lock", 8: "unlock", 3: "remote_connect", 4: "remote_disconnect",
                     2: "console_disconnect", 6: "logoff"}.get(wp)
            if event:
                self.callback(event)
            return 0
        if message == 0x218:  # WM_POWERBROADCAST
            event = {4: "suspend", 7: "resume", 18: "resume"}.get(wp)
            if event:
                self.callback(event)
            return 1
        return None

    def start(self) -> None:
        if self._events:
            return
        self._wts = C.WinDLL("wtsapi32", use_last_error=True)
        bind(self._wts, "WTSRegisterSessionNotification", BOOL, HANDLE, DWORD)
        bind(self._wts, "WTSUnRegisterSessionNotification", BOOL, HANDLE)
        def setup(hwnd: int) -> None:
            if not self._wts.WTSRegisterSessionNotification(hwnd, 0):
                raise OSError(last_error(), "WTSRegisterSessionNotification failed")
            self._registered = True
        def teardown(hwnd: int) -> None:
            if self._registered:
                if not self._wts.WTSUnRegisterSessionNotification(hwnd):
                    raise OSError(last_error(), "WTSUnRegisterSessionNotification failed")
                self._registered = False
        self._events = EventWindow(self._message, setup, teardown)

    def close(self) -> None:
        events, self._events = self._events, None
        if events:
            events.close()
