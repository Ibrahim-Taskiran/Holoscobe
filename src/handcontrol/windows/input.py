"""SendInput adapter with explicit ownership and best-effort release retry."""
from __future__ import annotations

import ctypes as C
import logging
import threading
from collections.abc import Callable

from ..contracts import DisplayProvider
from ._win32 import INPUT, KEYBDINPUT, MOUSEINPUT, last_error, user32
from .placement import normalize_pointer

log = logging.getLogger(__name__)
MOVE, LEFTDOWN, LEFTUP, WHEEL = 0x1, 0x2, 0x4, 0x800
RIGHTDOWN, RIGHTUP = 0x8, 0x10
VIRTUALDESK, ABSOLUTE, KEYUP = 0x4000, 0x8000, 0x2
VK_CONTROL = 0x11
KEYEXTENDED = 0x1
# Keys that need KEYEVENTF_EXTENDEDKEY: arrows, Win keys, media and volume keys.
EXTENDED_VKS = frozenset({0x25, 0x26, 0x27, 0x28, 0x5B, 0x5C, 0xAD, 0xAE, 0xAF, 0xB0, 0xB1, 0xB2, 0xB3})
# Win keys are not covered by modifiers_down(); a held Win key would corrupt a chord.
WIN_VKS = (0x5B, 0x5C)


def mouse(flags: int, x: int = 0, y: int = 0, data: int = 0) -> INPUT:
    event = INPUT(type=0)
    event.mi = MOUSEINPUT(x, y, data & 0xFFFFFFFF, flags, 0, 0)
    return event


def key(vk: int, up: bool = False) -> INPUT:
    event = INPUT(type=1)
    flags = (KEYUP if up else 0) | (KEYEXTENDED if vk in EXTENDED_VKS else 0)
    event.ki = KEYBDINPUT(vk, 0, flags, 0, 0)
    return event


class WindowsInput:
    def __init__(self, displays: DisplayProvider, *, api=None,
                 on_error: Callable[[str], None] | None = None) -> None:
        self.displays = displays
        self.api = api if api is not None else user32()
        self.on_error = on_error
        self._ledger: list[tuple[str, int]] = []
        self._lock = threading.RLock()

    @property
    def ledger(self) -> tuple[tuple[str, int], ...]:
        with self._lock:
            return tuple(self._ledger)

    def _report(self, message: str) -> None:
        log.warning(message)
        if self.on_error:
            try:
                self.on_error(message)
            except Exception:
                log.exception("Input error callback failed")

    def _send(self, event: INPUT) -> bool:
        try:
            count = int(self.api.SendInput(1, C.byref(event), C.sizeof(INPUT)))
            if count == 1:
                return True
            self._report(f"SendInput rejected input (count={count}, error={last_error()}); UIPI may block it")
        except Exception as exc:
            self._report(f"SendInput failed: {exc}")
        return False

    def _press(self, token: tuple[str, int], event: INPUT) -> bool:
        if token in self._ledger:
            return False
        if not self._send(event):
            return False
        self._ledger.append(token)
        return True

    def _release(self, token: tuple[str, int]) -> bool:
        if token not in self._ledger:
            return True
        event = mouse({1: LEFTUP, 2: RIGHTUP}[token[1]]) if token[0] == "mouse" else key(token[1], up=True)
        if not self._send(event):
            return False
        self._ledger.remove(token)
        return True

    def move_pointer(self, x: int, y: int) -> bool:
        with self._lock:
            nx, ny = normalize_pointer(x, y, self.displays.monitors())
            return self._send(mouse(MOVE | ABSOLUTE | VIRTUALDESK, nx, ny))

    def left_click(self, x: int, y: int) -> bool:
        with self._lock:
            if ("mouse", 1) in self._ledger:
                return False
            if not self.move_pointer(x, y):
                return False
            token = ("mouse", 1)
            if not self._press(token, mouse(LEFTDOWN)):
                return False
            return self._release(token)

    def right_click(self, x: int, y: int) -> bool:
        with self._lock:
            token = ("mouse", 2)
            if token in self._ledger or not self.move_pointer(x, y):
                return False
            if not self._press(token, mouse(RIGHTDOWN)):
                return False
            return self._release(token)

    def double_click(self, x: int, y: int) -> bool:
        with self._lock:
            token = ("mouse", 1)
            if token in self._ledger or not self.move_pointer(x, y):
                return False
            for _ in range(2):
                if not self._press(token, mouse(LEFTDOWN)) or not self._release(token):
                    return False
            return True

    def left_down(self, x: int, y: int) -> bool:
        with self._lock:
            token = ("mouse", 1)
            if token in self._ledger or not self.move_pointer(x, y):
                return False
            return self._press(token, mouse(LEFTDOWN))

    def left_up(self, x: int, y: int) -> bool:
        with self._lock:
            token = ("mouse", 1)
            try:
                moved = self.move_pointer(x, y)
            finally:
                released = self._release(token)
            return moved and released

    def scroll(self, steps: int) -> bool:
        with self._lock:
            delta = int(steps) * 120
            if not -(2 ** 31) <= delta < 2 ** 31:
                return False
            return self._send(mouse(WHEEL, data=delta)) if delta else True

    def modifiers_down(self) -> bool:
        # Include generic and left/right Shift, Ctrl and Alt. Never take ownership
        # of a modifier that was down before our chord.
        return any(self.api.GetAsyncKeyState(vk) & 0x8000
                   for vk in (0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5))

    def zoom(self, steps: int) -> bool:
        with self._lock:
            if self.modifiers_down() or self._ledger:
                self._report("Synthetic Ctrl chord skipped: a modifier is already down or cleanup is pending")
                return False
            token = ("key", VK_CONTROL)
            if not self._press(token, key(VK_CONTROL)):
                return False
            success = False
            try:
                success = self.scroll(steps)
            finally:
                released = self._release(token)
            return success and released

    def _send_batch(self, events: list[INPUT]) -> int:
        """Send events in one SendInput call; return how many were accepted (0 on failure)."""
        array = (INPUT * len(events))(*events)
        try:
            count = int(self.api.SendInput(len(events), array, C.sizeof(INPUT)))
            if count != len(events):
                self._report(f"SendInput accepted {count}/{len(events)} key events (error={last_error()})")
            return max(0, count)
        except Exception as exc:
            self._report(f"SendInput failed: {exc}")
            return 0

    def key_combo(self, vks: tuple[int, ...] | list[int]) -> bool:
        """Press vks in order, release in reverse, as one SendInput batch.

        Refused (False, nothing sent) when empty, when a Shift/Ctrl/Alt/Win key is already
        physically down (same semantics as zoom: never merge with a user-held modifier),
        or when the ledger is non-empty (app-held mouse button or pending cleanup).
        On partial acceptance every key left down is recorded in the ledger and released
        immediately; failed releases stay in the ledger so release_all() retries them.
        """
        vks = tuple(int(v) for v in vks)
        if not vks or len(set(vks)) != len(vks) or any(not 0 < v < 0xFF for v in vks):
            return False
        with self._lock:
            if self._ledger or self.modifiers_down() or any(
                    self.api.GetAsyncKeyState(vk) & 0x8000 for vk in WIN_VKS):
                self._report("Key command skipped: a modifier or app-held input is already down")
                return False
            events = [key(v) for v in vks] + [key(v, up=True) for v in reversed(vks)]
            sent = self._send_batch(events)
            if sent == len(events):
                return True
            downs_sent = vks[:min(sent, len(vks))]
            ups_sent = set(tuple(reversed(vks))[:max(0, sent - len(vks))])
            for vk in downs_sent:
                if vk not in ups_sent:
                    self._ledger.append(("key", vk))
            for token in reversed(tuple(self._ledger)):
                try:
                    self._release(token)
                except Exception:
                    log.exception("Key combo cleanup failed")
            return False

    def release_all(self) -> None:
        """Never raise; retain failed releases so the next cleanup can retry them."""
        try:
            with self._lock:
                for token in reversed(tuple(self._ledger)):
                    try:
                        self._release(token)
                    except Exception:
                        log.exception("Owned input release failed")
        except Exception:
            log.exception("Input cleanup failed")
