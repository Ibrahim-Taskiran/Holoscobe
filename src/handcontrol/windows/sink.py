"""Serialized action routing with epoch and capture-age checks at execution."""
from __future__ import annotations

import logging
import math
import threading
import time
from collections.abc import Callable

from ..contracts import Action, ActionKind, Clock, DisplayProvider, VolumeControl
from .audio import WindowsVolumeControl
from .displays import WindowsDisplayProvider
from .input import WindowsInput
from .window import WindowsWindowQuery

log = logging.getLogger(__name__)


class WindowsActionSink:
    def __init__(self, *, epoch: int = 0, clock: Clock | None = None,
                 displays: DisplayProvider | None = None, input_adapter=None,
                 windows=None, volume: VolumeControl | None = None,
                 on_error: Callable[[str], None] | None = None) -> None:
        self._lock = threading.RLock()
        self._epoch = epoch
        self.clock = clock
        self.on_error = on_error
        self.displays = displays if displays is not None else WindowsDisplayProvider()
        self.input = input_adapter if input_adapter is not None else WindowsInput(self.displays, on_error=on_error)
        self.windows = windows if windows is not None else WindowsWindowQuery(self.displays, on_error=on_error)
        self.volume = volume if volume is not None else WindowsVolumeControl(on_error=on_error)
        self._closed = False

    @property
    def epoch(self) -> int:
        with self._lock:
            return self._epoch

    def set_epoch(self, epoch: int) -> None:
        """Call on every controller cancellation before allowing new actions."""
        with self._lock:
            if epoch != self._epoch:
                self._epoch = epoch
                self.release_all()

    def _now(self) -> float:
        return self.clock.now_ms() if self.clock else time.monotonic() * 1000

    def dispatch(self, action: Action) -> bool:
        with self._lock:
            if action.kind == ActionKind.RELEASE_ALL:
                self.release_all()
                return True
            age = self._now() - action.capture_ms
            if self._closed or action.epoch != self._epoch or not math.isfinite(age) or not 0 <= age <= 150:
                return False
            try:
                kind, target = action.kind, action.target
                if kind in (ActionKind.MOVE_POINTER, ActionKind.LEFT_CLICK,
                            ActionKind.WINDOW_DRAG_BEGIN, ActionKind.WINDOW_DRAG_MOVE):
                    if action.x is None or action.y is None:
                        return False
                if kind == ActionKind.MOVE_POINTER:
                    return self.input.move_pointer(action.x, action.y)
                if kind == ActionKind.LEFT_CLICK:
                    return self.input.left_click(action.x, action.y)
                if kind == ActionKind.SET_VOLUME:
                    if isinstance(self.volume, WindowsVolumeControl) and self.clock is None:
                        return self.volume.set_volume(action.value, deadline_ms=action.capture_ms + 150)
                    return self.volume.set_volume(action.value)
                if target is None or not self.windows.is_valid(target):
                    return False
                if kind in (ActionKind.SCROLL, ActionKind.ZOOM):
                    if not self.windows.can_receive_input(target):
                        return False
                    return (self.input.scroll if kind == ActionKind.SCROLL else self.input.zoom)(action.steps)
                if kind == ActionKind.WINDOW_DRAG_BEGIN:
                    return self.windows.drag_begin(target, action.x, action.y)
                if kind == ActionKind.WINDOW_DRAG_MOVE:
                    return self.windows.drag_move(target, action.x, action.y)
                routes = {
                    ActionKind.WINDOW_DRAG_END: self.windows.drag_end,
                    ActionKind.WINDOW_MINIMIZE: self.windows.minimize,
                    ActionKind.WINDOW_TOGGLE_MAXIMIZE: self.windows.toggle_maximize,
                    ActionKind.WINDOW_MOVE_TO_OTHER_MONITOR: self.windows.move_to_other_monitor,
                    ActionKind.WINDOW_CLOSE: self.windows.close_window,
                }
                return bool(routes[kind](target)) if kind in routes else False
            except Exception as exc:
                log.exception("Windows action failed: %s", action.kind)
                self.release_all()
                if self.on_error:
                    try:
                        self.on_error(str(exc))
                    except Exception:
                        log.exception("Sink error callback failed")
                return False

    def release_all(self) -> None:
        try:
            with self._lock:
                for cleanup in (self.input.release_all, self.windows.cancel_drag):
                    try:
                        cleanup()
                    except Exception:
                        log.exception("Sink cleanup failed")
        except Exception:
            log.exception("Sink release_all failed")

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self.release_all()
            close = getattr(self.volume, "close", None)
            if close:
                close()
