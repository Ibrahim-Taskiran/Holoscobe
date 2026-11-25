"""A hidden top-level window receives broadcasts on a dedicated message thread."""
from __future__ import annotations

import ctypes as C
import logging
import queue
import threading
import uuid
from concurrent.futures import Future
from collections.abc import Callable

from ._win32 import HANDLE, MSG, WNDCLASSW, WNDPROC, bind, last_error, user32

log = logging.getLogger(__name__)
WM_COMMAND_QUEUE, WM_STOP = 0x8001, 0x8002


class EventWindow:
    def __init__(self, handler: Callable[[int, int, int], int | None],
                 setup: Callable[[int], None] | None = None,
                 teardown: Callable[[int], None] | None = None) -> None:
        self.handler, self.setup, self.teardown = handler, setup, teardown
        self.hwnd = 0
        self._queue: queue.Queue[tuple[Future, Callable]] = queue.Queue()
        self._ready = threading.Event()
        self._error: Exception | None = None
        self._thread = threading.Thread(target=self._run, name="Win32Events", daemon=True)
        self._thread.start()
        if not self._ready.wait(5):
            raise TimeoutError("Win32 event window did not start")
        if self._error:
            raise self._error

    def _run(self) -> None:
        api = None
        instance = None
        registered = False
        name = "HandControl_" + uuid.uuid4().hex
        try:
            api = user32()
            kernel = C.WinDLL("kernel32", use_last_error=True)
            instance = bind(kernel, "GetModuleHandleW", HANDLE, C.c_wchar_p)(None)

            @WNDPROC
            def procedure(hwnd, message, wp, lp):
                try:
                    if message == WM_COMMAND_QUEUE:
                        while True:
                            try:
                                future, operation = self._queue.get_nowait()
                            except queue.Empty:
                                break
                            if future.set_running_or_notify_cancel():
                                try:
                                    future.set_result(operation())
                                except Exception as exc:
                                    future.set_exception(exc)
                        return 0
                    if message == WM_STOP:
                        api.PostQuitMessage(0)
                        return 0
                    result = self.handler(message, wp, lp)
                    if result is not None:
                        return result
                except Exception:
                    log.exception("Win32 event callback failed")
                return api.DefWindowProcW(hwnd, message, wp, lp)

            self._procedure = procedure  # Keep the callback alive through destruction.
            cls = WNDCLASSW(lpfnWndProc=procedure, hInstance=instance, lpszClassName=name)
            if not api.RegisterClassW(C.byref(cls)):
                raise OSError(last_error(), "RegisterClassW failed")
            registered = True
            # Message-only windows do not receive display/power broadcasts.
            self.hwnd = api.CreateWindowExW(0x80, name, "", 0, 0, 0, 0, 0, None, None, instance, None)
            if not self.hwnd:
                raise OSError(last_error(), "CreateWindowExW failed")
            if self.setup:
                self.setup(self.hwnd)
            self._ready.set()
            msg = MSG()
            while True:
                result = api.GetMessageW(C.byref(msg), None, 0, 0)
                if result == -1:
                    raise OSError(last_error(), "GetMessageW failed")
                if result == 0:
                    break
                api.TranslateMessage(C.byref(msg))
                api.DispatchMessageW(C.byref(msg))
        except Exception as exc:
            self._error = exc
            log.exception("Win32 event thread stopped")
        finally:
            self._ready.set()
            if api and self.hwnd:
                try:
                    if self.teardown:
                        self.teardown(self.hwnd)
                except Exception:
                    log.exception("Event window teardown failed")
                api.DestroyWindow(self.hwnd)
                self.hwnd = 0
            if api and registered:
                api.UnregisterClassW(name, instance)
            while not self._queue.empty():
                future, _ = self._queue.get_nowait()
                if not future.done():
                    future.set_exception(RuntimeError("Event window closed"))

    def call(self, operation: Callable):
        if threading.current_thread() is self._thread:
            return operation()
        if not self.hwnd or not self._thread.is_alive():
            raise RuntimeError("Event window is closed")
        future: Future = Future()
        self._queue.put((future, operation))
        if not user32().PostMessageW(self.hwnd, WM_COMMAND_QUEUE, 0, 0):
            future.cancel()
            raise OSError(last_error(), "Could not queue event-thread command")
        try:
            return future.result(timeout=2)
        except TimeoutError:
            future.cancel()
            raise

    def close(self) -> None:
        if self.hwnd:
            if not user32().PostMessageW(self.hwnd, WM_STOP, 0, 0):
                log.error("Could not stop event window: %s", last_error())
        if threading.current_thread() is not self._thread:
            self._thread.join(timeout=2)


class EventOwner:
    """Base of the services that listen through one EventWindow."""

    _events: EventWindow | None = None

    def close(self) -> None:
        events, self._events = self._events, None
        if events:
            events.close()
