from __future__ import annotations

from ctrl_helpers import G, K, RIGHT, Rig, hand

from handcontrol.contracts import Mode


def _vol_rig(level: float) -> Rig:
    r = Rig(volume=level)
    r.ctl.set_mode(Mode.VOLUME)
    r.settle(hand(palm=(320, 300)))
    r.frame(hand(palm=(320, 300)), events=[(G.PINCH_START, RIGHT)])
    return r


def test_volume_relative_to_engagement_level_up_increases():
    r = _vol_rig(0.5)
    for _ in range(6):
        r.frame(hand(palm=(320, 252)))  # up 0.1 -> +0.09*2
    vals = [a.value for a in r.sink.of(K.SET_VOLUME)]
    assert vals and abs(vals[-1] - 0.68) < 1e-6
    assert r.count(K.SET_VOLUME) == 1  # unchanged value is not resent


def test_volume_down_decreases():
    r = _vol_rig(0.5)
    for _ in range(6):
        r.frame(hand(palm=(320, 348)))
    assert r.sink.of(K.SET_VOLUME)[-1].value < 0.5


def test_volume_clamped():
    r = _vol_rig(0.9)
    for _ in range(6):
        r.frame(hand(palm=(320, 20)))
    assert r.sink.of(K.SET_VOLUME)[-1].value == 1.0
    r2 = _vol_rig(0.1)
    for _ in range(6):
        r2.frame(hand(palm=(320, 470)))
    assert r2.sink.of(K.SET_VOLUME)[-1].value == 0.0


def test_volume_rate_limited_to_10_per_second():
    r = _vol_rig(0.0)
    start = r.clock.now_ms()
    y = 300.0
    for _ in range(100):  # 1 s at 10 ms frames, continuous upward motion
        y -= 1.5
        r.frame(hand(palm=(320, y)), dt=10.0)
    elapsed = r.clock.now_ms() - start
    n = r.count(K.SET_VOLUME)
    assert 8 <= n <= 1 + elapsed * 10 / 1000 + 0.05
    vals = [a.value for a in r.sink.of(K.SET_VOLUME)]
    assert vals == sorted(vals) and all(0.0 <= v <= 1.0 for v in vals)


def test_volume_no_action_after_release():
    r = _vol_rig(0.5)
    r.frame(hand(palm=(320, 250)))
    n = r.count(K.SET_VOLUME)
    r.frame(hand(palm=(320, 250)), events=[(G.PINCH_END, RIGHT)])
    for _ in range(5):
        r.frame(hand(palm=(320, 100)))
    assert r.count(K.SET_VOLUME) == n
