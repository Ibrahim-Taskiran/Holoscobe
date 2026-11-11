"""Conservative HWND+PID targeting and asynchronous window mutations."""
from __future__ import annotations

import ctypes as C
import logging
import os
import threading
from collections.abc import Callable, Iterable

from ..contracts import DisplayProvider, Rect, WindowTarget
from ._win32 import DWORD, POINT, RECT, WINDOWPLACEMENT, last_error, user32
from .placement import ensure_title_visible, monitor_for_rect, proportional_placement, size

log = logging.getLogger(__name__)
EXCLUDED_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
                    "#32768", "tooltips_class32", "SysShadow", "MultitaskingViewFrame",
                    "TaskListThumbnailWnd", "XamlExplorerHostIslandWindow"}
SWP_FLAGS = 0x4 | 0x10 | 0x200 | 0x4000  # NOZORDER, NOACTIVATE, NOOWNERZORDER, ASYNCWINDOWPOS


class WindowsWindowQuery:
    def __init__(self, displays: DisplayProvider, *, api=None, own_pid: int | None = None,
                 own_windows: Iterable[int] = (), on_error: Callable[[str], None] | None = None) -> None:
        self.displays = displays
        self.api = api if api is not None else user32()
        self.own_pid = os.getpid() if own_pid is None else own_pid
        self.own_windows = set(own_windows)
        self.on_error = on_error
        self._lock = threading.RLock()
        self._drag: tuple[WindowTarget, int, int, int, int] | None = None
        self._drag_position: tuple[int, int] | None = None

    def _fail(self, operation: str) -> bool:
        message = f"{operation} rejected or failed (Win32 error={last_error()})"
        log.warning(message)
        if self.on_error:
            try:
                self.on_error(message)
            except Exception:
                log.exception("Window error callback failed")
        return False

    def _pid(self, hwnd: int) -> int:
        pid = DWORD()
        if not self.api.GetWindowThreadProcessId(hwnd, C.byref(pid)):
            return 0
        return pid.value

    def _eligible(self, hwnd: int) -> bool:
        api = self.api
        if not hwnd or not api.IsWindow(hwnd) or not api.IsWindowVisible(hwnd):
            return False
        if hwnd in self.own_windows or hwnd in (api.GetDesktopWindow(), api.GetShellWindow()):
            return False
        pid = self._pid(hwnd)
        if not pid or pid == self.own_pid or api.GetAncestor(hwnd, 2) != hwnd:
            return False
        name = C.create_unicode_buffer(256)
        if not api.GetClassNameW(hwnd, name, len(name)) or name.value in EXCLUDED_CLASSES:
            return False
        style, exstyle = api.window_style(hwnd, -16), api.window_style(hwnd, -20)
        # Owned popups, tool windows and no-activate overlays are transient targets.
        if api.GetWindow(hwnd, 4) or exstyle & (0x80 | 0x08000000) or style & 0x40000000:
            return False
        return True

    def _target(self, hwnd: int) -> WindowTarget | None:
        if not self._eligible(hwnd):
            return None
        target = WindowTarget(hwnd, self._pid(hwnd))
        return target if self.is_valid(target) else None

    def eligible_window_at(self, x: int, y: int) -> WindowTarget | None:
        hwnd = self.api.WindowFromPoint(POINT(x, y))
        return self._target(self.api.GetAncestor(hwnd, 2)) if hwnd else None

    def foreground_window(self) -> WindowTarget | None:
        return self._target(self.api.GetForegroundWindow())

    def is_valid(self, target: WindowTarget) -> bool:
        return bool(target and target.pid > 0 and self._pid(target.hwnd) == target.pid and self._eligible(target.hwnd))

    def can_receive_input(self, target: WindowTarget) -> bool:
        """Do not redirect global wheel input by changing focus.

        Require both foreground and pointer target, covering Windows' inactive
        window scrolling preference. Global SendInput cannot atomically pin HWND.
        """
        point = POINT()
        return bool(self.is_valid(target) and self.foreground_window() == target
                    and self.api.GetCursorPos(C.byref(point))
                    and self.eligible_window_at(point.x, point.y) == target)

    def _rect(self, target: WindowTarget) -> Rect | None:
        if not self.is_valid(target):
            return None
        rect = RECT()
        if not self.api.GetWindowRect(target.hwnd, C.byref(rect)):
            return None
        return Rect(rect.left, rect.top, rect.right, rect.bottom)

    def _normal_rect(self, target: WindowTarget, current: Rect) -> Rect | None:
        if not self.is_valid(target):
            return None
        placement = WINDOWPLACEMENT(length=C.sizeof(WINDOWPLACEMENT))
        if not self.api.GetWindowPlacement(target.hwnd, C.byref(placement)):
            return None
        r = placement.rcNormalPosition
        # WINDOWPLACEMENT is in workspace coordinates for normal top-level windows.
        monitor = monitor_for_rect(current, self.displays.monitors())
        dx = monitor.work_area.left - monitor.bounds.left
        dy = monitor.work_area.top - monitor.bounds.top
        return Rect(r.left + dx, r.top + dy, r.right + dx, r.bottom + dy)

    def _position(self, target: WindowTarget, rect: Rect, *, resize: bool = False) -> bool:
        if not self.is_valid(target):
            return self._fail("SetWindowPos identity check")
        width, height = size(rect)
        flags = SWP_FLAGS | (0 if resize else 0x1)
        return bool(self.api.SetWindowPos(target.hwnd, None, rect.left, rect.top, width, height, flags)) or self._fail("SetWindowPos")

    def _show(self, target: WindowTarget, command: int) -> bool:
        if not self.is_valid(target):
            return self._fail("ShowWindowAsync identity check")
        return bool(self.api.ShowWindowAsync(target.hwnd, command)) or self._fail("ShowWindowAsync")

    def drag_begin(self, target: WindowTarget, x: int, y: int) -> bool:
        with self._lock:
            self._drag = None
            self._drag_position = None
            rect = self._rect(target)
            if rect is None or self.api.IsIconic(target.hwnd):
                return self._fail("Drag begin")
            width, height = size(rect)
            if width <= 0 or height <= 0:
                return False
            if self.api.IsZoomed(target.hwnd):
                normal = self._normal_rect(target, rect)
                if normal is None:
                    return self._fail("GetWindowPlacement")
                nw, nh = size(normal)
                ox = round(max(0, min(1, (x - rect.left) / width)) * nw)
                oy = round(max(0, min(1, (y - rect.top) / height)) * nh)
                rect = Rect(x - ox, y - oy, x - ox + nw, y - oy + nh)
                if not self._show(target, 4) or not self._position(target, rect, resize=True):
                    return False
            self._drag = (target, x - rect.left, y - rect.top, *size(rect))
            self._drag_position = (rect.left, rect.top)
            return True

    def drag_move(self, target: WindowTarget, x: int, y: int) -> bool:
        with self._lock:
            if not self._drag or self._drag[0] != target:
                return False
            _, ox, oy, width, height = self._drag
            if not self._position(target, Rect(x - ox, y - oy, x - ox + width, y - oy + height)):
                self._drag = None
                self._drag_position = None
                return False
            self._drag_position = (x - ox, y - oy)
            return True

    def drag_end(self, target: WindowTarget) -> bool:
        with self._lock:
            if not self._drag or self._drag[0] != target:
                return False
            self._drag = None
            position, self._drag_position = self._drag_position, None
            rect = self._rect(target)
            if rect is None:
                return False
            # A queued ASYNCWINDOWPOS move may not yet be reflected by GetWindowRect.
            # Keep its intended position, but use the app's current DPI-adjusted size.
            if position:
                width, height = size(rect)
                x, y = position
                rect = Rect(x, y, x + width, y + height)
            return self._position(target, ensure_title_visible(rect, [m.work_area for m in self.displays.monitors()]))

    def cancel_drag(self) -> None:
        """Cancel without further target mutation (pause/lock/release path)."""
        with self._lock:
            self._drag = None
            self._drag_position = None

    def minimize(self, target: WindowTarget) -> bool:
        return self._show(target, 6)

    def restore(self, target: WindowTarget) -> bool:
        """Restore the latched target; never substitute the foreground window."""
        return self._show(target, 9)

    def toggle_maximize(self, target: WindowTarget) -> bool:
        if not self.is_valid(target):
            return False
        return self._show(target, 9 if self.api.IsZoomed(target.hwnd) else 3)

    def move_to_other_monitor(self, target: WindowTarget) -> bool:
        with self._lock:
            monitors = self.displays.monitors()
            if len(monitors) < 2:
                return False
            rect = self._rect(target)
            if rect is None or self.api.IsIconic(target.hwnd):
                return False
            source = monitor_for_rect(rect, monitors)
            destination = monitors[(list(monitors).index(source) + 1) % len(monitors)]
            maximized = bool(self.api.IsZoomed(target.hwnd))
            normal = self._normal_rect(target, rect) if maximized else rect
            if normal is None:
                return False
            mapped = proportional_placement(normal, source, destination)
            if maximized and not self._show(target, 4):
                return False
            if not self._position(target, mapped, resize=True):
                return False
            return self._show(target, 3) if maximized else True

    def close_window(self, target: WindowTarget) -> bool:
        if not self.is_valid(target):
            return self._fail("WM_CLOSE identity check")
        return bool(self.api.PostMessageW(target.hwnd, 0x10, 0, 0)) or self._fail("WM_CLOSE")
