from __future__ import annotations

from types import SimpleNamespace

from handcontrol.contracts import ControlState
from handcontrol.ui import FeedbackToast, StatusIndicator
from handcontrol.ui.viewmodel import IndicatorKind, UiBridge, resolve_indicator


def snap(**kw):
    base = dict(state=ControlState.ACTIVE, pending_action="")
    base.update(kw)
    return SimpleNamespace(**base)


def test_priority_order() -> None:
    full = dict(pointer_engaged=True, tracking_ok=False, pending_action="Sürükle")
    assert resolve_indicator(snap(state=ControlState.PAUSED, **full)).kind == IndicatorKind.PAUSED
    assert resolve_indicator(snap(**full)).kind == IndicatorKind.NO_TRACKING
    full["tracking_ok"] = True
    pending = resolve_indicator(snap(**full))
    assert pending.kind == IndicatorKind.PENDING and pending.text == "Sürükle"
    full["pending_action"] = ""
    assert resolve_indicator(snap(**full)).kind == IndicatorKind.ENGAGED
    full["pointer_engaged"] = False
    assert resolve_indicator(snap(**full)).kind == IndicatorKind.PARKED


def test_old_style_snapshot_falls_back() -> None:
    # No pointer_engaged / tracking_ok / last_cancel attributes at all.
    assert resolve_indicator(snap()).kind == IndicatorKind.PARKED
    bridge = UiBridge()
    bridge.update_snapshot(snap())  # must not raise


def test_cancel_toast_deduplicates() -> None:
    bridge = UiBridge()
    toast = FeedbackToast(bridge)
    seen: list[str] = []
    bridge.feedback_triggered.connect(lambda m: seen.append(m.text))
    bridge.update_snapshot(snap(last_cancel=""))
    bridge.update_snapshot(snap(last_cancel="Tıklama iptal: el kayboldu"))
    bridge.update_snapshot(snap(last_cancel="Tıklama iptal: el kayboldu"))
    assert seen == ["Tıklama iptal: el kayboldu"]
    assert toast.current_message.duration_ms == 1500
    bridge.update_snapshot(snap(last_cancel="Sürükleme iptal"))
    assert seen[-1] == "Sürükleme iptal" and len(seen) == 2


def test_indicator_updates_only_on_change() -> None:
    bridge = UiBridge()
    widget = StatusIndicator(bridge)
    emitted: list[object] = []
    bridge.indicator_updated.connect(emitted.append)
    bridge.update_snapshot(snap(pointer_engaged=True))
    bridge.update_snapshot(snap(pointer_engaged=True))
    assert len(emitted) == 1
    assert widget.indicator_state.kind == IndicatorKind.ENGAGED
    assert widget.render_to_image().width() == widget.width()


def test_respects_overlay_visible_setting() -> None:
    bridge = UiBridge()
    flag = {"on": False}
    widget = StatusIndicator(bridge, enabled_fn=lambda: flag["on"], auto_show_window=True)
    bridge.update_snapshot(snap(pointer_engaged=True))
    assert not widget.isVisible()
    flag["on"] = True
    bridge.update_snapshot(snap(pointer_engaged=False))
    assert widget.isVisible()
    widget.close()
