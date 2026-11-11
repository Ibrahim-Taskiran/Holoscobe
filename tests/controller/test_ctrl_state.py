from __future__ import annotations

from ctrl_helpers import G, K, RIGHT, Rig, hand, tcfg

from handcontrol.contracts import CameraState, ControlState, Mode


def test_starts_paused_and_resume_needs_running_camera():
    r = Rig(camera=False, active=False)
    s = r.ctl.snapshot()
    assert s.state is ControlState.PAUSED and s.camera_state is CameraState.OFF
    assert r.ctl.resume() is False
    assert r.ctl.snapshot().state is ControlState.PAUSED
    r.ctl.set_camera_state(CameraState.RUNNING)
    assert r.ctl.snapshot().state is ControlState.PAUSED  # never auto-activate
    assert r.ctl.resume() is True
    assert r.ctl.snapshot().state is ControlState.ACTIVE


def test_no_os_action_while_paused():
    r = Rig(active=False)
    for i in range(20):
        r.frame(hand(tip=(100 + 10 * i, 200)))
    assert r.kinds() == []


def test_clap_toggles_and_pause_releases():
    r = Rig(active=False)
    r.frame(hand(), events=[(G.CLAP,)])
    assert r.ctl.snapshot().state is ControlState.ACTIVE
    assert r.kinds() == []
    r.frame(hand(), events=[(G.CLAP,)])
    assert r.ctl.snapshot().state is ControlState.PAUSED
    assert r.kinds() == [K.RELEASE_ALL]


def test_clap_ignored_when_camera_not_running():
    for cam in (CameraState.OFF, CameraState.STARTING):
        r = Rig(camera=False, active=False)
        r.ctl.set_camera_state(cam)
        r.frame(hand(), events=[(G.CLAP,)])
        assert r.ctl.snapshot().state is ControlState.PAUSED


def test_clap_ignored_in_calibrating_and_fault():
    r = Rig(active=False)
    assert r.ctl.begin_calibration()
    r.frame(hand(), events=[(G.CLAP,)])
    assert r.ctl.snapshot().state is ControlState.CALIBRATING
    r.ctl.end_calibration()
    assert r.ctl.snapshot().state is ControlState.PAUSED

    r.ctl.set_camera_state(CameraState.ERROR)
    assert r.ctl.snapshot().state is ControlState.FAULT
    r.frame(hand(), events=[(G.CLAP,)])
    assert r.ctl.snapshot().state is ControlState.FAULT
    assert r.ctl.resume() is False


def test_camera_error_faults_and_recovery_lands_in_paused():
    r = Rig()
    r.ctl.set_camera_state(CameraState.ERROR)
    s = r.ctl.snapshot()
    assert s.state is ControlState.FAULT and s.last_fault_reason
    assert r.kinds() == [K.RELEASE_ALL]
    r.ctl.set_camera_state(CameraState.RUNNING)
    assert r.ctl.snapshot().state is ControlState.PAUSED


def test_camera_off_while_active_pauses():
    r = Rig()
    r.ctl.set_camera_state(CameraState.OFF)
    assert r.ctl.snapshot().state is ControlState.PAUSED
    assert r.kinds() == [K.RELEASE_ALL]


def test_emergency_stop_pauses_releases_and_bumps_epoch():
    r = Rig()
    e0 = r.ctl.snapshot().epoch
    r.ctl.emergency_stop()
    s = r.ctl.snapshot()
    assert s.state is ControlState.PAUSED and s.epoch > e0
    assert r.kinds() == [K.RELEASE_ALL]


def test_session_lock_and_suspend_pause():
    for call in ("on_session_lock", "on_suspend"):
        r = Rig()
        getattr(r.ctl, call)()
        assert r.ctl.snapshot().state is ControlState.PAUSED
        assert r.kinds() == [K.RELEASE_ALL]


def test_epoch_increments_on_every_reset():
    r = Rig()
    seen = [r.ctl.snapshot().epoch]
    for op in (lambda: r.ctl.pause(), lambda: r.ctl.resume(), lambda: r.ctl.set_mode(Mode.SCROLL),
               lambda: r.ctl.emergency_stop(), lambda: r.ctl.on_display_change()):
        op()
        seen.append(r.ctl.snapshot().epoch)
    assert all(b > a for a, b in zip(seen, seen[1:]))


def test_mode_change_requires_fresh_neutral():
    r = Rig()
    r.settle(hand())
    r.ctl.set_mode(Mode.SCROLL)
    assert r.ctl.snapshot().needs_neutral
    r.frame(hand(tip=(100, 100)))
    assert r.kinds() == []


def test_display_change_refreshes_and_releases():
    r = Rig()
    r.ctl.on_display_change()
    assert r.kinds() == [K.RELEASE_ALL]
    assert r.ctl.snapshot().state is ControlState.ACTIVE


def test_internal_error_enters_fault_and_releases():
    class Boom:
        def reset(self):
            pass

        def filter(self, t, x, y):
            raise RuntimeError("x")

    r = Rig(smoother=Boom())
    r.frame(hand())
    s = r.ctl.snapshot()
    assert s.state is ControlState.FAULT and "RuntimeError" in s.last_fault_reason
    assert r.kinds() == [K.RELEASE_ALL]
    r.ctl.clear_fault()
    assert r.ctl.snapshot().state is ControlState.PAUSED


def test_listener_receives_snapshots_and_errors_are_swallowed():
    r = Rig()
    got = []
    r.ctl.add_listener(lambda s: (_ for _ in ()).throw(ValueError()))
    r.ctl.add_listener(got.append)
    r.ctl.pause("x")
    assert got and got[-1].state is ControlState.PAUSED


def test_calibration_blocks_actions_and_ends_paused():
    r = Rig()
    r.settle(hand())
    assert r.ctl.begin_calibration()
    r.sink.clear()
    for i in range(10):
        r.frame(hand(tip=(100 + 20 * i, 200)))
    assert r.kinds() == []
    r.ctl.end_calibration()
    assert r.ctl.snapshot().state is ControlState.PAUSED


def test_clap_candidate_abort_requires_neutral():
    r = Rig(cfg=tcfg())
    r.settle(hand())
    r.frame(hand(), events=[(G.CLAP_CANDIDATE_START,)])
    assert r.ctl.snapshot().clap_pending
    r.frame(hand(tip=(200, 200)), events=[(G.CLAP_CANDIDATE_ABORT,)])
    s = r.ctl.snapshot()
    assert not s.clap_pending and s.needs_neutral
    assert r.count(K.MOVE_POINTER) == 0
