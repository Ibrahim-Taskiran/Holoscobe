from __future__ import annotations

from types import SimpleNamespace

from _fakes import FakeFrame

from handcontrol.contracts import FrameSample
from handcontrol.tracking import HandTracker, TrackingStats


class _Lm:
    def detect_for_video(self, image, ts):
        return SimpleNamespace(hand_landmarks=[], handedness=[], hand_world_landmarks=[])

    def close(self):
        pass


def _tracker(tmp_path, factory, **kw):
    p = tmp_path / "m.task"
    p.write_bytes(b"x")
    return HandTracker(p, landmarker_factory=factory, image_factory=lambda f: f, **kw)


def test_defaults_split():
    assert HandTracker().confidences == (0.5, 0.35, 0.35)


def test_confidence_sets_all_three():
    assert HandTracker(confidence=0.6).confidences == (0.6, 0.6, 0.6)


def test_specific_overrides_general():
    t = HandTracker(confidence=0.6, presence_confidence=0.2)
    assert t.confidences == (0.6, 0.2, 0.6)


def test_legacy_factory_gets_three_args_with_detection(tmp_path):
    calls = []

    def legacy(path, n, conf):
        calls.append((n, conf))
        return _Lm()

    _tracker(tmp_path, legacy, detection_confidence=0.45).process(FakeFrame(1), 1.0)
    assert calls == [(2, 0.45)]


def test_default_factory_receives_all_three(monkeypatch, tmp_path):
    import handcontrol.tracking as tr

    seen = {}

    def fake(path, n, det, pres, trk):
        seen.update(det=det, pres=pres, trk=trk)
        return _Lm()

    monkeypatch.setattr(tr, "_default_landmarker_factory", fake)
    t = HandTracker(tmp_path / "m.task", image_factory=lambda f: f)
    (tmp_path / "m.task").write_bytes(b"x")
    t.process(FakeFrame(1), 1.0)
    assert seen == {"det": 0.5, "pres": 0.35, "trk": 0.35}


def _sample(done_ms, n_hands):
    return FrameSample(capture_ms=done_ms, inference_done_ms=done_ms, width=1, height=1,
                       hands=tuple(object() for _ in range(n_hands)))


def test_no_hand_stats_empty():
    s = TrackingStats().snapshot()
    assert s["no_hand_ratio"] == 0.0 and s["no_hand_longest_ms"] == 0.0


def test_no_hand_ratio_and_longest_gap():
    st = TrackingStats()
    # hand at 0, empty 30..90 (gap measured from last hand frame), hand at 120, empty 150
    for t, n in [(0, 1), (30, 0), (60, 0), (90, 0), (120, 1), (150, 0)]:
        st.record(_sample(float(t), n), 5.0)
    s = st.snapshot()
    assert s["no_hand_ratio"] == 4 / 6
    assert s["no_hand_longest_ms"] == 90.0
    assert "output_fps" in s and "samples" in s


def test_profile_compare_confidence_parse_and_gaps():
    import pytest
    from handcontrol.tools import profile_compare as pc
    from handcontrol.tools.common import ToolError

    assert pc.parse_confidence_profiles("0.5/0.35/0.35, 0.4") == [(0.5, 0.35, 0.35), (0.4, 0.4, 0.4)]
    with pytest.raises(ToolError):
        pc.parse_confidence_profiles("0.5/0.3")
    with pytest.raises(ToolError):
        pc.parse_confidence_profiles("abc")

    def obs(t, n):
        f = SimpleNamespace(capture_ms=float(t), width=640, height=480, hands=[SimpleNamespace(quality="x", landmarks=())] * n)
        return SimpleNamespace(frame=f, inference_ms=5.0)

    g = pc.GapStats(640, 480)
    for t, n in [(0, 1), (30, 0), (60, 0), (90, 1)]:
        g.add(obs(t, n), 1)
    row = g.summary()
    assert row["bos_kare_orani"] == 0.5 and row["en_uzun_bosluk_ms"] == 60.0
    assert "| 0.5/0.35/0.35 |" in pc.confidence_table([{**row, "profil": "0.5/0.35/0.35"}])
