"""Emergency hotkey with transactional reassignment on its owning thread."""
from __future__ import annotations

from collections.abc import Callable

from ._events import EventOwner, EventWindow
from ._win32 import last_error, user32

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT = 1, 2, 4, 0x4000
DEFAULT_MODIFIERS = MOD_ALT | MOD_CONTROL | MOD_SHIFT
DEFAULT_KEY = 0x7B  # F12


class HotkeyConflictError(OSError):
    pass


class WindowsHotkey(EventOwner):
    def __init__(self, callback: Callable[[], None]) -> None:
        self.callback = callback
        self._id = 1
        self._binding: tuple[int, int] | None = None

    def _message(self, message: int, wp: int, lp: int) -> int | None:
        if message == 0x312 and wp == self._id:
            self.callback()
            return 0
        return None

    def start(self, modifiers: int = DEFAULT_MODIFIERS, key: int = DEFAULT_KEY) -> None:
        if self._events:
            self.reassign(modifiers, key)
            return
        def setup(hwnd: int) -> None:
            if not user32().RegisterHotKey(hwnd, self._id, modifiers | MOD_NOREPEAT, key):
                raise HotkeyConflictError(last_error(), "Emergency hotkey unavailable; choose another binding")
            self._binding = (modifiers, key)
        self._events = EventWindow(self._message, setup, self._unregister)

    def _unregister(self, hwnd: int) -> None:
        if self._binding:
            if not user32().UnregisterHotKey(hwnd, self._id):
                raise OSError(last_error(), "UnregisterHotKey failed")
            self._binding = None

    def reassign(self, modifiers: int, key: int) -> None:
        if not self._events:
            self.start(modifiers, key)
            return
        if self._binding == (modifiers, key):
            return
        def replace() -> None:
            api, hwnd = user32(), self._events.hwnd
            new_id = 2 if self._id == 1 else 1
            if not api.RegisterHotKey(hwnd, new_id, modifiers | MOD_NOREPEAT, key):
                raise HotkeyConflictError(last_error(), "Replacement hotkey unavailable; previous binding retained")
            if not api.UnregisterHotKey(hwnd, self._id):
                api.UnregisterHotKey(hwnd, new_id)
                raise OSError(last_error(), "Previous hotkey could not be unregistered")
            self._id, self._binding = new_id, (modifiers, key)
        self._events.call(replace)
