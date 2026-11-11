from __future__ import annotations

import time

from ctrl_helpers import G, K, RIGHT, Rig, hand

from handcontrol.contracts import Mode, Quality


def _scroll_engaged(r: Rig) -> None:
    r.ctl.set_mode(Mode.SCROLL)
    r.settle(hand(palm=(320, 300)))
    r.frame(hand(palm=(320, 300)), events=[(G.PINCH_START, RIGHT)])
    for y in (280, 260, 240):
        r.frame(hand(palm=(320, y)))
    assert r.count(K.SCROLL) >= 1


def test_hand_loss_releases_immediately_and_no_replay_after_recovery():
    r = Rig()
    _scroll_engaged(r)
    before = r.count(K.SCROLL)
    r.frame()  # no hands
    assert r.kinds()[-1] is K.RELEASE_ALL
    assert r.count(K.RELEASE_ALL) == 1
    # recover far away with the pinch still held: no accumulated motion is replayed
    for _ in range(10):
        r.frame(hand(palm=(320, 60)))
    assert r.count(K.SCROLL) == before
    assert r.count(K.RELEASE_ALL) == 1


def test_degraded_tracking_freezes_engagement():
    r = Rig()
    _scroll_engaged(r)
    before = r.count(K.SCROLL)
    r.frame(hand(palm=(320, 100), quality=Quality.DEGRADED))
    r.frame(hand(palm=(320, 80)))
    assert r.count(K.SCROLL) == before
    assert r.count(K.RELEASE_ALL) == 1


def test_identity_ambiguous_cancels():
    r = Rig()
    _scroll_engaged(r)
    r.frame(hand(palm=(320, 200)), ambiguous=True)
    assert r.count(K.RELEASE_ALL) == 1
    assert r.ctl.snapshot().needs_neutral


def test_watchdog_releases_within_200ms_when_loop_stalls():
    r = Rig()
    _scroll_engaged(r)
    last_cap = r.ctl.watchdog.last_usable_ms
    assert last_cap is not None
    # on_frame is never called again
    assert r.ctl.watchdog.check(last_cap + 199.0) is False
    assert r.count(K.RELEASE_ALL) == 0
    assert r.ctl.watchdog.check(last_cap + 200.0) is True
    assert r.count(K.RELEASE_ALL) == 1
    assert r.ctl.watchdog.check(last_cap + 400.0) is False  # fires once per loss
    assert r.ctl.snapshot().needs_neutral
    assert r.ctl.snapshot().pending_action == ""


def test_watchdog_thread_fires_without_frames():
    r = Rig()
    _scroll_engaged(r)
    r.ctl.start_watchdog()
    try:
        r.clock.advance(250.0)
        deadline = time.monotonic() + 2.0
        while r.count(K.RELEASE_ALL) == 0 and time.monotonic() < deadline:
            time.sleep(0.005)
    finally:
        r.ctl.stop_watchdog()
    assert r.count(K.RELEASE_ALL) == 1


def test_watchdog_after_pointer_only_activity_releases_once():
    r = Rig()
    r.settle(hand())
    r.frame(hand(tip=(100, 100)))
    for _ in range(8):
        r.frame()  # no hands for ~270 ms
    assert r.count(K.RELEASE_ALL) == 1
    assert r.count(K.MOVE_POINTER) == 1


def test_fresh_engagement_required_after_loss():
    r = Rig()
    _scroll_engaged(r)
    r.frame()
    n = len(r.kinds())
    # pinch released and re-pressed immediately: neutral not yet satisfied -> ignored
    r.frame(hand(palm=(320, 300)), events=[(G.PINCH_END, RIGHT)])
    r.frame(hand(palm=(320, 300)), events=[(G.PINCH_START, RIGHT)])
    for y in (250, 200, 150):
        r.frame(hand(palm=(320, y)))
    assert len(r.kinds()) == n


def test_epoch_invalidation_in_guard():
    from handcontrol.contracts import Action
    r = Rig()
    old = r.ctl.current_epoch()
    r.ctl.set_mode(Mode.SCROLL)
    r.sink.clear()
    ok = r.ctl.guard.dispatch(Action(K.MOVE_POINTER, old, r.clock.now_ms(), x=1, y=1))
    assert ok is False and r.kinds() == []
    assert r.ctl.snapshot().dropped_actions == 1


def test_pause_during_engagement_invalidates_queued_epoch():
    r = Rig()
    _scroll_engaged(r)
    epoch_before = r.ctl.current_epoch()
    r.ctl.pause()
    assert r.ctl.current_epoch() > epoch_before
    assert r.kinds()[-1] is K.RELEASE_ALL
    n = len(r.kinds())
    r.frame(hand(palm=(320, 100)))
    assert len(r.kinds()) == n
