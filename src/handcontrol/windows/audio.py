"""Default endpoint volume; all COM objects live and die on one worker."""
from __future__ import annotations

import logging
import math
import queue
import sys
import threading
import time
from concurrent.futures import Future
from collections.abc import Callable

log = logging.getLogger(__name__)


class WindowsVolumeControl:
    def __init__(self, *, on_error: Callable[[str], None] | None = None,
                 backend_factory: Callable | None = None) -> None:
        self.on_error = on_error
        self._backend_factory = backend_factory
        self._queue: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._closed = False
        self._thread: threading.Thread | None = None

    def _run(self) -> None:
        com = endpoint = device = backend = current = None
        initialized = 0
        startup_error: Exception | None = None
        try:
            if self._backend_factory:
                backend = self._backend_factory()
            else:
                # comtypes initializes the importing thread on its first import.
                # Use Python 3.11's reentrant module lock so two adapters cannot
                # both claim that automatic initialization during concurrent import.
                from importlib._bootstrap import _ModuleLockManager
                with _ModuleLockManager("comtypes"):
                    first_import = "comtypes" not in sys.modules
                    import comtypes
                    com = comtypes
                    if first_import:
                        initialized += 1
                com.CoInitializeEx()  # Use its configured apartment consistently.
                initialized += 1
                from pycaw.pycaw import AudioUtilities
                backend = AudioUtilities
        except Exception as exc:
            startup_error = RuntimeError(str(exc))
        try:
            while True:
                item = self._queue.get()
                if item is None:
                    break
                future, value, deadline = item
                if not future.set_running_or_notify_cancel():
                    continue
                try:
                    if startup_error:
                        raise RuntimeError(f"Audio backend unavailable: {startup_error}")
                    if time.monotonic() > deadline:
                        raise TimeoutError("Expired audio request")
                    # Requery the default endpoint on EVERY operation. No device
                    # switch can leave a permanently cached obsolete endpoint.
                    for attempt in range(2):
                        try:
                            current = backend.GetSpeakers()
                            if device is None or current.id != device.id:
                                endpoint = None
                                device = current
                            current = None
                            if endpoint is None:
                                endpoint = device.EndpointVolume
                            if time.monotonic() > deadline:
                                raise TimeoutError("Expired audio request")
                            if value is None:
                                result = max(0.0, min(1.0, float(endpoint.GetMasterVolumeLevelScalar())))
                            else:
                                endpoint.SetMasterVolumeLevelScalar(value, None)
                                result = True
                            future.set_result(result)
                            break
                        except Exception:
                            endpoint = device = None
                            if attempt:
                                raise
                except Exception as exc:
                    # Do not transfer a traceback retaining COM locals to callers.
                    future.set_exception(RuntimeError(str(exc)))
        finally:
            endpoint = device = backend = current = None
            startup_error = None
            if self._backend_factory and hasattr(self._backend_factory, "close"):
                self._backend_factory.close()
            if com:
                for _ in range(initialized):
                    com.CoUninitialize()

    def _request(self, value: float | None, deadline_ms: float | None = None):
        with self._lock:
            if self._closed:
                raise RuntimeError("Volume adapter closed")
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="WindowsAudio", daemon=True)
                self._thread.start()
            future: Future = Future()
            deadline = time.monotonic() + (2.0 if value is None else 0.150)
            if deadline_ms is not None:
                deadline = min(deadline, deadline_ms / 1000)
            self._queue.put((future, value, deadline))
        try:
            return future.result(timeout=2 if value is None else max(0, deadline - time.monotonic()))
        except TimeoutError:
            future.cancel()
            raise

    def get_volume(self) -> float:
        return float(self._request(None))

    def set_volume(self, value: float, *, deadline_ms: float | None = None) -> bool:
        try:
            if not math.isfinite(value):
                return False
            return bool(self._request(max(0.0, min(1.0, value)), deadline_ms))
        except Exception as exc:
            log.warning("Could not set endpoint volume: %s", exc)
            if self.on_error:
                try:
                    self.on_error(str(exc))
                except Exception:
                    log.exception("Audio error callback failed")
            return False

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            while True:
                try:
                    item = self._queue.get_nowait()
                except queue.Empty:
                    break
                if item:
                    item[0].cancel()
            self._queue.put(None)
        if self._thread and threading.current_thread() is not self._thread:
            self._thread.join(timeout=2)
