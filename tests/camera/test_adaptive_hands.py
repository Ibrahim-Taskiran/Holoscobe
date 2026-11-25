"""Lone hand on the one-hand model, second hand found by the scout, and the resting rate of TrackingLoop."""
from __future__ import annotations

from concurrent.futures import Future
from types import SimpleNamespace

import pytest
from test_tracking import FakeCam, FakeClock, FakeFrame, hand_result, make_tracker, model, wait_until  # noqa: F401

from handcontrol.adaptive_hands import AdaptiveLandmarker, same_hand
from handcontrol.tracking import HandTracker, TrackingLoop


def hand(x=0.3, y=0.5, size=0.2):
    """21 points; only the wrist (0) and the middle knuckle (9) matter here."""
    return [SimpleNamespace(x=x, y=y - (size if i == 9 else 0.0), z=0.0) for i in range(21)]


def result(*hands):
    return SimpleNamespace(hand_landmarks=list(hands), handedness=[], hand_world_landmarks=[])


NONE, ONE, TWO = result(), result(hand()), result(hand(), hand(x=0.8))


class Model:
    def __init__(self, answer):
        self.answer, self.stamps, self.closed = answer, [], False

    def detect_for_video(self, image, ts):
        assert not self.stamps or ts > self.stamps[-1], "MediaPipe needs rising timestamps"
        self.stamps.append(ts)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer

    def close(self):
        self.closed = True


class Pool:
    """Executor whose jobs run only on run(); cancel works until then."""

    def __init__(self):
        self.jobs, self.down = [], False

    def submit(self, fn, *args):
        future = Future()
        self.jobs.append((future, fn, args))
        return future

    def run(self):
        for future, fn, args in self.jobs:
            if future.set_running_or_notify_cancel():
                try:
                    future.set_result(fn(*args))
                except Exception as exc:
                    future.set_exception(exc)
        self.jobs.clear()

    def shutdown(self, wait=True):
        self.down = True


class Rig:
    def __init__(self, full=ONE, single=ONE, **kw):
        self.full, self.single, self.pool, self.t = Model(full), Model(single), Pool(), 0
        self.lm = AdaptiveLandmarker(self.full, self.single, executor=self.pool, **kw)

    def frames(self, n, run=True):
        out = None
        for _ in range(n):
            self.t += 33
            out = self.lm.detect_for_video("img", self.t)
            if run:
                self.pool.run()
        return out


def fast_rig(**kw):
    rig = Rig(**kw)
    rig.frames(20)
    assert rig.lm.fast
    return rig


def test_lone_hand_moves_to_the_single_model_after_the_settle_time():
    rig = Rig()
    rig.frames(16)                       # 495 ms after the first frame
    assert not rig.lm.fast and not rig.single.stamps
    rig.frames(1)
    assert rig.lm.fast
    before = len(rig.full.stamps)
    rig.frames(30)                       # about 1 s: the full model only scouts
    assert 6 <= len(rig.full.stamps) - before <= 8
    assert rig.lm.fast


@pytest.mark.parametrize("seen", [NONE, TWO])
def test_no_hand_or_two_hands_stay_on_the_full_model(seen):
    rig = Rig(full=seen)
    rig.frames(60)
    assert not rig.lm.fast and not rig.single.stamps


def test_short_overlap_of_two_hands_does_not_switch():
    rig = Rig(full=TWO)
    for _ in range(5):                   # clap: palms merge into one hand for 400 ms
        rig.full.answer = ONE
        rig.frames(12)
        rig.full.answer = TWO
        rig.frames(3)
    assert not rig.lm.fast and not rig.single.stamps


def test_single_model_that_sees_another_place_is_not_used():
    rig = Rig(single=result(hand(x=0.9)))
    rig.frames(60)
    assert not rig.lm.fast
    assert len(rig.single.stamps) <= 4   # retried, but not on every frame


def test_second_hand_brings_the_full_model_back_within_one_scout_interval():
    rig = fast_rig()
    rig.full.answer = TWO
    seen = [len(rig.frames(1).hand_landmarks) for _ in range(6)]
    assert seen[-1] == 2 and not rig.lm.fast


def test_lost_hand_is_searched_by_the_full_model_in_the_same_frame():
    rig = fast_rig()
    rig.single.answer = NONE
    assert len(rig.frames(1).hand_landmarks) == 1
    assert not rig.lm.fast and rig.full.stamps[-1] == rig.t


def test_scout_that_sees_the_hand_elsewhere_wins():
    rig = fast_rig()
    rig.full.answer = result(hand(x=0.9))
    rig.frames(6)
    assert not rig.lm.fast


def test_scout_that_misses_the_hand_changes_nothing():
    rig = fast_rig()
    rig.full.answer = NONE
    rig.frames(30)
    assert rig.lm.fast


def test_failed_scout_falls_back_and_the_error_reaches_the_caller():
    rig = fast_rig()
    rig.full.answer = RuntimeError("boom")
    with pytest.raises(RuntimeError):
        rig.frames(10)
    assert not rig.lm.fast


def test_waiting_scout_is_cancelled_so_timestamps_keep_rising():
    rig = fast_rig()
    rig.frames(6, run=False)
    assert rig.pool.jobs                 # submitted, not started
    rig.single.answer = NONE
    rig.frames(1, run=False)             # full model runs here with a newer timestamp
    rig.pool.run()                       # the old job must not run any more (Model asserts the order)
    rig.frames(3)


def test_mode_that_needs_two_hands_leaves_at_once():
    allowed = [True]
    rig = fast_rig(allowed=lambda: allowed[0])
    allowed[0] = False
    rig.frames(1)
    assert not rig.lm.fast
    rig.frames(60)
    assert not rig.lm.fast


def test_close_closes_both_models_and_the_worker():
    rig = fast_rig()
    rig.lm.close()
    assert rig.full.closed and rig.single.closed and rig.pool.down


def test_real_worker_thread_finds_the_second_hand():
    full, single = Model(ONE), Model(ONE)
    lm = AdaptiveLandmarker(full, single)
    ts = iter(range(0, 10 ** 6, 33))
    for _ in range(20):
        lm.detect_for_video("img", next(ts))
    full.answer = TWO

    def two():
        return len(lm.detect_for_video("img", next(ts)).hand_landmarks) == 2
    assert wait_until(two)
    lm.close()


def test_same_hand():
    assert same_hand(ONE, result(hand(x=0.35)))
    assert not same_hand(ONE, result(hand(x=0.6)))
    assert not same_hand(ONE, TWO) and not same_hand(NONE, ONE)


def test_tracker_uses_both_models_only_when_asked(model):  # noqa: F811
    made = []

    def factory(path, n, conf):
        made.append(n)
        return Model(NONE)
    plain = HandTracker(model, landmarker_factory=factory, image_factory=lambda f: f)
    plain.load()
    assert made == [2]
    made.clear()
    fast = HandTracker(model, landmarker_factory=factory, image_factory=lambda f: f, fast_single_hand=lambda: True)
    fast.load()
    assert made == [2, 1]
    fast.close()
    plain.close()


# ---------- resting rate ----------

class Scripted:
    def __init__(self, hands_at=()):
        self.hands_at, self.n = set(hands_at), 0

    def detect_for_video(self, image, ts):
        self.n += 1
        return hand_result(["Left"] if ts in self.hands_at else [])

    def close(self):
        pass


def run_loop(model_path, stamps, *, idle, hands_at=()):
    cam = FakeCam([(FakeFrame(i), float(s)) for i, s in enumerate(stamps, 1)])
    out, taps = [], []
    loop = TrackingLoop(cam, make_tracker(model_path, Scripted(hands_at)), out.append, clock=FakeClock(0.0, step=1.0), idle=idle)
    loop.on_image = lambda img, ms: taps.append(ms)
    loop.start()
    assert wait_until(lambda: len(taps) == len(stamps))
    loop.stop()
    return [s.capture_ms for s in out]


STAMPS = [1000 + 33 * i for i in range(150)]        # 5 s


def test_paused_without_hands_rests_after_two_seconds(model):  # noqa: F811
    done = run_loop(model, STAMPS, idle=lambda: True)
    early = [t for t in done if t < 3000]
    late = [t for t in done if t >= 3000]
    assert len(early) == sum(t < 3000 for t in STAMPS)
    gaps = {b - a for a, b in zip(late, late[1:])}
    assert gaps == {99.0}


def test_active_control_never_rests(model):  # noqa: F811
    assert run_loop(model, STAMPS, idle=lambda: False) == [float(s) for s in STAMPS]


def test_hand_restores_the_full_rate_at_once(model):  # noqa: F811
    seen = run_loop(model, STAMPS, idle=lambda: True, hands_at={t for t in STAMPS if t > 4000})
    late = [t for t in seen if t > 4100]
    assert {b - a for a, b in zip(late, late[1:])} == {33.0}
