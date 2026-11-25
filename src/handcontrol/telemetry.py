"""Opt-in session telemetry: one numeric CSV row per processed frame, local file only.

No images and no landmarks are stored. The recorder never raises into the pipeline: on any I/O
error it disables itself. See Docs/reports/telemetry.md.
"""
from __future__ import annotations

import csv
import math
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Union

from handcontrol.config import app_data_dir
from handcontrol.contracts import ActionKind, FingerName, Handedness

FINGERS = tuple(f.value for f in FingerName)
COLUMNS = (
    "t_ms", "age_ms", "hands", "dom_present", "dom_quality",
    *(f"finger_{n}" for n in FINGERS),
    "pinch_pu", "palm_x_px", "palm_y_px", "palm_scale_px",
    "events", "actions", "moves",
    "state", "mode", "pending_action", "notice", "pointer_x", "pointer_y", "dropped_actions",
    "pointer_engaged", "tracking_ok", "last_cancel",
    "dom_reasons", "mid_pinch_pu",
)


def default_telemetry_dir() -> Path:
    return app_data_dir() / "telemetry"


def default_session_path(when: Optional[datetime] = None) -> Path:
    when = when or datetime.now()
    return default_telemetry_dir() / f"session_{when.strftime('%Y%m%d-%H%M%S')}.csv"


def _num(value: Any, digits: int = 3) -> Any:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return ""
    return round(v, digits) if math.isfinite(v) else ""


def _enum(value: Any) -> str:
    return str(getattr(value, "value", value) if value is not None else "")


def _reasons(ff: Any, dom: Any) -> str:
    """Reason codes attached by FeatureExtractor (FrameFeatures.reasons, a non-field attribute)."""
    try:
        per_hand, frame = getattr(ff, "reasons", ({}, ()))
        codes = list(per_hand.get(getattr(dom, "hand_id", None), ())) if dom else []
        codes += [c for c in frame if c not in codes]
        return "|".join(codes)
    except Exception:  # noqa: BLE001
        return ""


def _mid_pinch(ff: Any, dom: Any) -> Any:
    """Thumb tip (4) to middle fingertip (12) distance in palm units, like pinch_pu."""
    try:
        lms = dom.landmarks
        scale = float(dom.palm_scale_px)
        if len(lms) < 13 or not scale > 0:
            return ""
        return _num(math.hypot((lms[4].x - lms[12].x) * ff.width, (lms[4].y - lms[12].y) * ff.height) / scale)
    except Exception:  # noqa: BLE001
        return ""


class SessionRecorder:
    """Thread-safe buffered CSV recorder. Use `on_frame` as a Pipeline frame observer and wrap the
    sink with `TelemetrySink` to also record dispatched action kinds."""

    def __init__(
        self,
        path: Optional[Union[str, Path]] = None,
        dominant: Union[Handedness, Callable[[], Handedness]] = Handedness.RIGHT,
        *,
        now_ms: Optional[Callable[[], float]] = None,
        flush_interval_s: float = 1.0,
        wall: Callable[[], float] = time.monotonic,
    ) -> None:
        self.path = Path(path) if path is not None else default_session_path()
        self.dominant = dominant
        self._now_ms = now_ms if now_ms is not None else (lambda: time.monotonic() * 1000.0)
        self._flush_interval = flush_interval_s
        self._wall = wall
        self._lock = threading.Lock()
        self._pending_actions: list[str] = []
        self._pending_moves = 0
        self._fh: Any = None
        self._writer: Any = None
        self._last_flush = wall()
        self.rows = 0
        self.last_error: Optional[str] = None
        self.enabled = True
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(self.path, "w", newline="", encoding="utf-8")
            self._writer = csv.writer(self._fh)
            self._writer.writerow(COLUMNS)
            self._fh.flush()
        except Exception as exc:  # noqa: BLE001 - telemetry must never break the app
            self._disable(exc)

    # ------------------------------------------------------------ public

    def record_action(self, kind: Any) -> None:
        """Remember a dispatched action kind; it is attached to the next frame row."""
        if not self.enabled:
            return
        with self._lock:
            if kind is ActionKind.MOVE_POINTER:
                self._pending_moves += 1
            else:
                self._pending_actions.append(_enum(kind))

    def on_frame(self, features: Any, events: Iterable[Any], snap: Any) -> None:
        """Pipeline frame observer: (FrameFeatures, events, ControllerSnapshot)."""
        if not self.enabled:
            return
        try:
            row = self._build_row(features, events, snap)
            with self._lock:
                if not self.enabled or self._writer is None:
                    return
                row[COLUMNS.index("actions")] = "|".join(self._pending_actions)
                row[COLUMNS.index("moves")] = self._pending_moves
                self._pending_actions.clear()
                self._pending_moves = 0
                self._writer.writerow(row)
                self.rows += 1
                now = self._wall()
                if now - self._last_flush >= self._flush_interval:
                    self._fh.flush()
                    self._last_flush = now
        except Exception as exc:  # noqa: BLE001
            self._disable(exc)

    def close(self) -> None:
        with self._lock:
            fh, self._fh, self._writer = self._fh, None, None
            self.enabled = False
        if fh is not None:
            try:
                fh.flush()
            except Exception:  # noqa: BLE001
                pass
            try:
                fh.close()
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------ internals

    def _disable(self, exc: BaseException) -> None:
        self.last_error = f"{type(exc).__name__}: {exc}"
        self.enabled = False
        fh, self._fh, self._writer = self._fh, None, None
        if fh is not None:
            try:
                fh.close()
            except Exception:  # noqa: BLE001
                pass

    def _dominant(self) -> Handedness:
        d = self.dominant
        return d() if callable(d) else d

    def _build_row(self, ff: Any, events: Iterable[Any], snap: Any) -> list[Any]:
        hands = tuple(getattr(ff, "hands", ()) or ())
        want = self._dominant()
        dom = next((h for h in hands if getattr(h, "handedness", None) == want), None)
        capture = float(getattr(ff, "capture_ms", 0.0))
        fingers = {_enum(getattr(f, "name", "")): _enum(getattr(f, "state", "")) for f in (dom.fingers if dom else ())}
        palm = getattr(dom, "palm_center_px", None) if dom else None
        pointer = getattr(snap, "pointer", None)
        return [
            _num(capture, 1), _num(self._now_ms() - capture, 1), len(hands), 1 if dom else 0,
            _enum(dom.quality) if dom else "",
            *(fingers.get(n, "") for n in FINGERS),
            _num(dom.pinch_distance) if dom else "",
            _num(palm[0], 1) if palm else "", _num(palm[1], 1) if palm else "",
            _num(dom.palm_scale_px, 1) if dom else "",
            "|".join(_enum(getattr(e, "kind", "")) for e in events), "", "",
            _enum(getattr(snap, "state", "")), _enum(getattr(snap, "mode", "")),
            getattr(snap, "pending_action", ""), getattr(snap, "notice", ""),
            pointer[0] if pointer else "", pointer[1] if pointer else "",
            getattr(snap, "dropped_actions", 0),
            1 if getattr(snap, "pointer_engaged", False) else 0,
            1 if getattr(snap, "tracking_ok", True) else 0,
            getattr(snap, "last_cancel", ""),
            _reasons(ff, dom), _mid_pinch(ff, dom) if dom else "",
        ]


class TelemetrySink:
    """ActionSink wrapper: records every action that reaches the sink, then forwards it."""

    def __init__(self, inner: Any, recorder: SessionRecorder) -> None:
        self._inner = inner
        self._recorder = recorder

    def dispatch(self, action: Any) -> Any:
        try:
            self._recorder.record_action(getattr(action, "kind", None))
        except Exception:  # noqa: BLE001
            pass
        return self._inner.dispatch(action)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


__all__ = ["COLUMNS", "SessionRecorder", "TelemetrySink", "default_session_path", "default_telemetry_dir"]
