from __future__ import annotations

from types import SimpleNamespace

import pytest
from _fakes import FakeClock, FakeFrame, make_landmarks, wait_until

from handcontrol.contracts import Handedness
from handcontrol.tracking import (
    HandTracker, ModelNotFoundError, TrackingLoop, TrackingStats, default_model_path,
)


class FakeLandmarker:
    def __init__(self, results=None):
        self.calls = []
        self.results = results or []
        self.closed = False

    def detect_for_video(self, image, ts):
        self.calls.append((image, ts))
        if self.results:
            return self.results.pop(0)
        return SimpleNamespace(hand_landmarks=[], handedness=[], hand_world_landmarks=[])

    def close(self):
        self.closed = True


def hand_result(labels, world=True):
    return SimpleNamespace(
        hand_landmarks=[make_landmarks() for _ in labels],
        handedness=[[SimpleNamespace(category_name=l, score=0.9)] for l in labels],
        hand_world_landmarks=[make_landmarks(base=0.0) for _ in labels] if world else [],
    )


@pytest.fixture
def model(tmp_path):
    p = tmp_path / "Modeller ığ" / "hand_landmarker.task"
    p.parent.mkdir()
    p.write_bytes(b"x")
    return p


def make_tracker(model, lm, clock=None, **kw):
    seen = {}

    def factory(path, n, conf):
        seen.update(path=path, n=n, conf=conf)
        return lm
    t = HandTracker(model, clock=clock or FakeClock(2000.0), landmarker_factory=factory,
                    image_factory=lambda f: ("img", f.tag), **kw)
    t.seen = seen
    return t


def test_default_model_path_location():
    p = default_model_path()
    assert p.parts[-3:] == ("assets", "models", "hand_landmarker.task")


def test_missing_model_clear_error(tmp_path):
    t = HandTracker(tmp_path / "yok.task", landmarker_factory=lambda *a: FakeLandmarker())
    with pytest.raises(ModelNotFoundError) as e:
        t.process(FakeFrame(1), 1.0)
    assert "yok.task" in str(e.value)


def test_params_passed(model):
    lm = FakeLandmarker()
    t = make_tracker(model, lm)
    t.process(FakeFrame(1), 10.0)
    assert t.seen["n"] == 2 and t.seen["conf"] == 0.5 and t.seen["path"] == str(model)


@pytest.mark.parametrize("labels", [[], ["Right"], ["Left", "Right"]])
def test_conversion_counts(model, labels):
    lm = FakeLandmarker([hand_result(labels)])
    t = make_tracker(model, lm, FakeClock(2000.0))
    s = t.process(FakeFrame(1, 640, 480), 1234.5)
    assert len(s.hands) == len(labels)
    assert (s.width, s.height, s.capture_ms, s.inference_done_ms) == (640, 480, 1234.5, 2000.0)
    for h, l in zip(s.hands, labels):
        assert h.handedness == (Handedness.LEFT if l == "Left" else Handedness.RIGHT)
        assert h.handedness_score == 0.9
        assert len(h.landmarks) == 21 and len(h.world_landmarks) == 21


def test_no_world_landmarks_and_unknown_label(model):
    r = hand_result(["???"], world=False)
    t = make_tracker(model, FakeLandmarker([r]))
    h = t.process(FakeFrame(1), 1.0).hands[0]
    assert h.handedness == Handedness.UNKNOWN and h.world_landmarks is None


def test_swap_handedness(model):
    t = make_tracker(model, FakeLandmarker([hand_result(["Left"])]), swap_handedness=True)
    assert t.process(FakeFrame(1), 1.0).hands[0].handedness == Handedness.RIGHT


def test_wrong_landmark_count_skipped(model):
    r = hand_result(["Right"])
    r.hand_landmarks[0] = r.hand_landmarks[0][:20]
    t = make_tracker(model, FakeLandmarker([r]))
    assert t.process(FakeFrame(1), 1.0).hands == ()


def test_timestamps_strictly_increasing(model):
    lm = FakeLandmarker()
    t = make_tracker(model, lm)
    for ms in (100.2, 100.9, 100.0, 99.0, 105.0, 105.4):
        t.process(FakeFrame(1), ms)
    ts = [c[1] for c in lm.calls]
    assert ts == [100, 101, 102, 103, 105, 106]
    assert all(isinstance(x, int) for x in ts)


def test_inference_on_unmirrored_frame(model):
    lm = FakeLandmarker()
    t = make_tracker(model, lm)
    f = FakeFrame("orig")
    t.process(f, 1.0)
    assert lm.calls[0][0] == ("img", "orig")      # frame passed through, no flip applied


def test_close_closes_landmarker(model):
    lm = FakeLandmarker()
    t = make_tracker(model, lm)
    t.process(FakeFrame(1), 1.0)
    t.close()
    assert lm.closed


def test_stats_percentiles():
    st = TrackingStats()
    from handcontrol.contracts import FrameSample
    for i in range(11):
        st.record(FrameSample(capture_ms=i * 100.0, inference_done_ms=i * 100.0 + 10 + i, width=1, height=1, hands=()), 5.0 + i)
    s = st.snapshot()
    assert s["capture_age_ms_p50"] == 15.0
    assert s["inference_ms_p95"] == pytest.approx(14.5)
    assert 9 < s["output_fps"] < 10.5 and s["samples"] == 11


class FakeCam:
    def __init__(self, frames):
        self.frames = list(frames)

    def read_latest(self, timeout=0.0):
        if self.frames:
            return self.frames.pop(0)
        import time
        time.sleep(0.005)
        return None


def test_loop_processes_and_stops_cleanly(model):
    lm = FakeLandmarker()
    t = make_tracker(model, lm)
    cam = FakeCam([(FakeFrame(i), float(i * 10)) for i in range(1, 4)])
    out = []
    loop = TrackingLoop(cam, t, out.append, clock=FakeClock(0.0, step=1.0))
    loop.start()
    assert wait_until(lambda: len(out) == 3)
    loop.stop()
    assert not loop.running and lm.closed
    assert [s.capture_ms for s in out] == [10.0, 20.0, 30.0]
    assert loop.stats.snapshot()["samples"] == 3


def test_loop_missing_model_reports_once_no_spin(tmp_path):
    t = HandTracker(tmp_path / "yok.task", landmarker_factory=lambda *a: FakeLandmarker())
    errs = []
    loop = TrackingLoop(FakeCam([]), t, lambda s: None, on_error=errs.append)
    loop.start()
    assert wait_until(lambda: not loop.running)
    assert len(errs) == 1 and "yok.task" in loop.last_error


def test_loop_stops_after_repeated_errors(model):
    class Boom(FakeLandmarker):
        def detect_for_video(self, image, ts):
            raise RuntimeError("x")
    t = make_tracker(model, Boom())
    cam = FakeCam([(FakeFrame(i), float(i)) for i in range(10)])
    errs = []
    loop = TrackingLoop(cam, t, lambda s: None, on_error=errs.append, max_consecutive_errors=3)
    loop.start()
    assert wait_until(lambda: not loop.running)
    assert len(errs) == 1


@pytest.mark.manual
def test_real_model_loads():
    t = HandTracker()
    t.load()
    t.close()
