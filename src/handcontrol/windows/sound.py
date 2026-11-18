"""Non-blocking feedback sounds. Never raises; throttled to one sound per 80 ms."""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

log = logging.getLogger(__name__)
MIN_INTERVAL_S = 0.08
ALIASES = {"click": "SystemDefault", "command": "SystemAsterisk", "error": "SystemHand"}

_lock = threading.Lock()
_last = -1e9


def _winsound_backend(alias: str) -> None:
    import winsound
    winsound.PlaySound(alias, winsound.SND_ALIAS | winsound.SND_ASYNC | winsound.SND_NODEFAULT)


def play(kind: str, *, backend: Callable[[str], None] | None = None,
         clock: Callable[[], float] = time.monotonic) -> None:
    """Play a system sound for kind in {"click", "command", "error"} without blocking."""
    global _last
    try:
        alias = ALIASES.get(kind)
        if alias is None:
            return
        with _lock:
            now = clock()
            if now - _last < MIN_INTERVAL_S:
                return
            _last = now
        (backend or _winsound_backend)(alias)
    except Exception:
        log.debug("Sound playback failed", exc_info=True)


def reset_throttle() -> None:
    global _last
    with _lock:
        _last = -1e9
