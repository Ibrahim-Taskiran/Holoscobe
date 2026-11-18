"""pid -> lower-case executable name via QueryFullProcessImageNameW. Never raises."""
from __future__ import annotations

import ctypes as C
import logging
import ntpath
import os
import threading
import time
from collections.abc import Callable
from functools import lru_cache

from ._win32 import BOOL, DWORD, HANDLE, bind

log = logging.getLogger(__name__)
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
CACHE_SECONDS = 2.0


@lru_cache(maxsize=1)
def _kernel32():
    if os.name != "nt":
        raise OSError("Windows adapters require Windows")
    dll = C.WinDLL("kernel32", use_last_error=True)
    bind(dll, "OpenProcess", HANDLE, DWORD, BOOL, DWORD)
    bind(dll, "QueryFullProcessImageNameW", BOOL, HANDLE, DWORD, C.c_wchar_p, C.POINTER(DWORD))
    bind(dll, "CloseHandle", BOOL, HANDLE)
    return dll


class WindowsProcessNames:
    def __init__(self, *, api=None, clock: Callable[[], float] = time.monotonic) -> None:
        self._api = api
        self._clock = clock
        self._cache: dict[int, tuple[float, str | None]] = {}
        self._lock = threading.Lock()

    def process_name(self, pid: int) -> str | None:
        try:
            pid = int(pid)
            if pid <= 0:
                return None
            now = self._clock()
            with self._lock:
                hit = self._cache.get(pid)
                if hit and now - hit[0] < CACHE_SECONDS:
                    return hit[1]
            name = self._query(pid)
            with self._lock:
                if len(self._cache) > 256:
                    self._cache = {k: v for k, v in self._cache.items() if now - v[0] < CACHE_SECONDS}
                self._cache[pid] = (now, name)
            return name
        except Exception:
            log.exception("Process name lookup failed")
            return None

    def _query(self, pid: int) -> str | None:
        api = self._api if self._api is not None else _kernel32()
        handle = api.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return None
        try:
            size = DWORD(1024)
            buffer = C.create_unicode_buffer(size.value)
            if not api.QueryFullProcessImageNameW(handle, 0, buffer, C.byref(size)):
                return None
            base = ntpath.basename(buffer.value[:size.value]).lower()
            return base or None
        finally:
            api.CloseHandle(handle)
