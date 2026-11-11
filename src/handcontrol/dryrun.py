"""Dry-run sink and fake OS adapters. Never touches the OS. Used by tests and the UI demo.

User-visible texts are Turkish.
"""
from __future__ import annotations

import threading
from typing import Optional, Sequence

from handcontrol.contracts import Action, ActionKind, Monitor, Rect, WindowTarget


def describe_action(action: Action) -> str:
    """Short Turkish text of the command that would be produced."""
    k = action.kind
    tgt = f" [pencere {action.target.hwnd:#x}]" if action.target is not None else ""
    if k is ActionKind.MOVE_POINTER:
        return f"İmleci taşı → ({action.x}, {action.y})"
    if k is ActionKind.LEFT_CLICK:
        return f"Sol tık ({action.x}, {action.y})"
    if k is ActionKind.SCROLL:
        yon = "yukarı" if action.steps > 0 else "aşağı"
        return f"Kaydır {yon} {abs(action.steps)} adım{tgt}"
    if k is ActionKind.ZOOM:
        yon = "Yakınlaştır" if action.steps > 0 else "Uzaklaştır"
        return f"{yon} {abs(action.steps)} adım{tgt}"
    if k is ActionKind.SET_VOLUME:
        return f"Ses düzeyi %{round(action.value * 100)}"
    if k is ActionKind.WINDOW_DRAG_BEGIN:
        return f"Pencereyi tut ({action.x}, {action.y}){tgt}"
    if k is ActionKind.WINDOW_DRAG_MOVE:
        return f"Pencereyi taşı → ({action.x}, {action.y}){tgt}"
    if k is ActionKind.WINDOW_DRAG_END:
        return f"Pencereyi bırak{tgt}"
    if k is ActionKind.WINDOW_MINIMIZE:
        return f"Pencereyi simge durumuna küçült{tgt}"
    if k is ActionKind.WINDOW_TOGGLE_MAXIMIZE:
        return f"Pencereyi büyüt / geri al{tgt}"
    if k is ActionKind.WINDOW_MOVE_TO_OTHER_MONITOR:
        return f"Pencereyi diğer ekrana taşı{tgt}"
    if k is ActionKind.WINDOW_CLOSE:
        return f"Pencereyi kapat (normal kapatma isteği){tgt}"
    if k is ActionKind.RELEASE_ALL:
        return "Tüm girdileri bırak"
    return k.value


class DryRunSink:
    """Records actions and their Turkish descriptions. Thread-safe. Never raises."""

    def __init__(self, accept: bool = True, max_history: Optional[int] = None) -> None:
        self.accept = accept
        self.max_history = max_history
        self._lock = threading.Lock()
        self.actions: list[Action] = []
        self.texts: list[str] = []
        self.release_calls = 0

    def _record(self, action: Action) -> None:
        with self._lock:
            self.actions.append(action)
            self.texts.append(describe_action(action))
            if self.max_history is not None and len(self.actions) > self.max_history:
                del self.actions[: -self.max_history]
                del self.texts[: -self.max_history]

    def dispatch(self, action: Action) -> bool:
        self._record(action)
        return self.accept

    def release_all(self) -> None:
        with self._lock:
            self.release_calls += 1
        self._record(Action(ActionKind.RELEASE_ALL, epoch=-1, capture_ms=0.0))

    # --- test helpers ---
    def kinds(self) -> list[ActionKind]:
        with self._lock:
            return [a.kind for a in self.actions]

    def of(self, kind: ActionKind) -> list[Action]:
        with self._lock:
            return [a for a in self.actions if a.kind is kind]

    def count(self, kind: ActionKind) -> int:
        return len(self.of(kind))

    @property
    def last_text(self) -> str:
        with self._lock:
            return self.texts[-1] if self.texts else ""

    def clear(self) -> None:
        with self._lock:
            self.actions.clear()
            self.texts.clear()
            self.release_calls = 0


class FakeClock:
    def __init__(self, start_ms: float = 10_000.0) -> None:
        self._t = float(start_ms)
        self._lock = threading.Lock()

    def now_ms(self) -> float:
        with self._lock:
            return self._t

    def advance(self, ms: float) -> float:
        with self._lock:
            self._t += ms
            return self._t

    def set(self, ms: float) -> None:
        with self._lock:
            self._t = float(ms)


def make_monitor(left: int, top: int, width: int, height: int, dpi_scale: float = 1.0,
                 primary: bool = False, taskbar: int = 40) -> Monitor:
    bounds = Rect(left, top, left + width, top + height)
    work = Rect(left, top, left + width, top + height - taskbar)
    return Monitor(bounds=bounds, work_area=work, dpi_scale=dpi_scale, is_primary=primary)


class FakeDisplays:
    def __init__(self, monitors: Optional[Sequence[Monitor]] = None) -> None:
        self._monitors = list(monitors) if monitors is not None else [
            make_monitor(0, 0, 1920, 1080, 1.0, primary=True)
        ]

    def monitors(self) -> Sequence[Monitor]:
        return tuple(self._monitors)

    def set_monitors(self, monitors: Sequence[Monitor]) -> None:
        self._monitors = list(monitors)


class FakeWindows:
    """Windows as (target, rect) in z-order, first = topmost."""

    def __init__(self, windows: Sequence[tuple[WindowTarget, Rect]] = (),
                 foreground: Optional[WindowTarget] = None) -> None:
        self._windows: list[tuple[WindowTarget, Rect]] = list(windows)
        self._valid: set[WindowTarget] = {t for t, _ in self._windows}
        self.foreground = foreground
        self.valid_checks = 0

    def add(self, target: WindowTarget, rect: Rect, top: bool = True) -> None:
        self._windows = [(t, r) for t, r in self._windows if t != target]
        if top:
            self._windows.insert(0, (target, rect))
        else:
            self._windows.append((target, rect))
        self._valid.add(target)

    def remove(self, target: WindowTarget) -> None:
        self._windows = [(t, r) for t, r in self._windows if t != target]
        self._valid.discard(target)
        if self.foreground == target:
            self.foreground = None

    def eligible_window_at(self, x: int, y: int) -> Optional[WindowTarget]:
        for t, r in self._windows:
            if t in self._valid and r.left <= x < r.right and r.top <= y < r.bottom:
                return t
        return None

    def foreground_window(self) -> Optional[WindowTarget]:
        return self.foreground if self.foreground in self._valid else None

    def is_valid(self, target: WindowTarget) -> bool:
        self.valid_checks += 1
        return target in self._valid


class FakeVolume:
    def __init__(self, level: float = 0.5) -> None:
        self.level = level
        self.set_calls: list[float] = []

    def get_volume(self) -> float:
        return self.level

    def set_volume(self, value: float) -> bool:
        self.level = min(1.0, max(0.0, value))
        self.set_calls.append(self.level)
        return True
