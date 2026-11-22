"""Round 7: TrackingLoop.on_image tap used by the Enstrüman window (camera image)."""
from __future__ import annotations

from test_tracking import FakeCam, FakeClock, FakeFrame, FakeLandmarker, make_tracker, model, wait_until  # noqa: F401
from handcontrol.tracking import TrackingLoop


def test_image_tap_gets_every_processed_frame_after_the_callback(model):
    t = make_tracker(model, FakeLandmarker())
    frames = [FakeFrame(i) for i in range(1, 4)]
    cam = FakeCam([(f, float(i * 10)) for i, f in enumerate(frames, 1)])
    order: list[str] = []
    taps: list[tuple[object, float]] = []
    loop = TrackingLoop(cam, t, lambda s: order.append("cb"), clock=FakeClock(0.0, step=1.0))
    loop.on_image = lambda img, ms: (order.append("tap"), taps.append((img, ms)))
    loop.start()
    assert wait_until(lambda: len(taps) == 3)
    loop.stop()
    assert [ms for _, ms in taps] == [10.0, 20.0, 30.0] and [img for img, _ in taps] == frames
    assert order == ["cb", "tap"] * 3


def test_image_tap_errors_are_swallowed_and_default_is_none(model):
    t = make_tracker(model, FakeLandmarker())
    cam = FakeCam([(FakeFrame(i), float(i)) for i in range(1, 3)])
    out = []
    loop = TrackingLoop(cam, t, out.append, clock=FakeClock(0.0, step=1.0))
    assert loop.on_image is None

    def boom(img, ms):
        raise RuntimeError("tap")
    loop.on_image = boom
    loop.start()
    assert wait_until(lambda: len(out) == 2)
    loop.stop()
    assert loop.last_error is None
