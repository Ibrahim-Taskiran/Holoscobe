from __future__ import annotations

import json

from _tools_fakes import FakeSource, frame, hand

from handcontrol.contracts import Handedness, Landmark, Quality
from handcontrol.tools import report as rp
from handcontrol.tools import stability_test as st
from handcontrol.tools.common import Observation

L, R = Handedness.LEFT, Handedness.RIGHT


def good(t, **kw):
    return frame(t, hand(L), hand(R, hand_id=2), **kw)


def obs(f, infer=8.0):
    return Observation(f, infer)


def test_both_hands_good_rules():
    assert st.both_hands_good(good(0))
    assert not st.both_hands_good(frame(0, hand(R)))                                   # one hand
    assert not st.both_hands_good(frame(0, hand(L), hand(R, quality=Quality.DEGRADED)))
    assert not st.both_hands_good(frame(0, hand(R), hand(R, hand_id=2)))               # two right labels
    short = hand(R, landmarks=tuple(Landmark(0, 0) for _ in range(20)))
    assert not st.both_hands_good(frame(0, hand(L), short))


def test_sample_and_time_weighted_coverage():
    s = st.StabilityStats()
    # 10 samples at 100 ms; sample 5 is bad (one hand).
    for i in range(10):
        f = frame(i * 100.0, hand(R)) if i == 5 else good(i * 100.0)
        s.add(obs(f))
    assert s.samples == 10 and s.good == 9
    assert s.sample_coverage_pct == 90.0
    # intervals i->i+1 count as covered iff sample i is good: 8 of 9 intervals (sample 5 bad)
    assert round(s.time_coverage_pct, 2) == round(100 * 800 / 900, 2)
    assert round(s.processed_fps, 1) == 10.0


def test_gaps_are_not_covered_and_counted():
    s = st.StabilityStats()
    for t in (0, 100, 200, 1200, 1300):       # one 1000 ms gap
        s.add(obs(good(float(t))))
    assert s.gaps == 1 and s.max_gap_ms == 1000.0
    assert s.sample_coverage_pct == 100.0          # all samples good...
    assert s.time_coverage_pct < 50.0              # ...but the gap is lost time


def test_repeated_samples_never_counted():
    s = st.StabilityStats()
    assert s.add(obs(good(100.0)))
    assert not s.add(obs(good(100.0)))
    assert not s.add(obs(good(50.0)))
    assert s.samples == 1 and s.ignored_repeats == 2


def test_identity_ambiguous_and_latency_stats():
    s = st.StabilityStats()
    for i in range(20):
        s.add(Observation(good(i * 33.0, ambiguous=(i % 10 == 0), latency=10.0 + i), float(i)))
    assert s.identity_ambiguous == 2
    summ = s.summary()
    assert summ["cikarim_ms_p50"] == 9.5 and summ["cikarim_ms_p95"] > summ["cikarim_ms_p50"]
    assert summ["yakalama_yasi_ms_p95"] > summ["yakalama_yasi_ms_p50"]


def test_decision_thresholds():
    def stats(good_n, total):
        s = st.StabilityStats()
        for i in range(total):
            s.add(obs(good(i * 33.0) if i < good_n else frame(i * 33.0, hand(R))))
        return s

    full = 300.0
    ok = stats(950, 1000)
    ok.total_time_ms = 300000.0
    assert st.decide(ok, 300, full, False)[1] == rp.KARAR_GECTI
    low = stats(940, 1000)
    low.total_time_ms = 300000.0
    assert st.decide(low, 300, full, False)[1] == rp.KARAR_KALDI
    short = stats(1000, 1000)
    assert st.decide(short, 33, 30.0, False)[0] == rp.STATUS_PROVA
    assert st.decide(ok, 300, full, True)[0] == rp.STATUS_YARIM


def run_for(console, out_dir, seconds, provider, **kw):
    src = FakeSource(provider, **kw)
    run = st.StabilityRun(src, console, seconds=seconds, out_dir=out_dir, software={})
    return run, src, run.execute()


def test_full_five_minute_run_passes(console, out_dir):
    run, src, report = run_for(console, out_dir, 300.0, lambda t: good(t))
    assert report.decision == rp.KARAR_GECTI and report.status == rp.STATUS_TAMAM
    assert run.stats.samples > 8000 and src.closed >= 1
    assert "hw_stability_test_" in run.md_path.name


def test_short_run_is_rehearsal(console, out_dir):
    _, _, report = run_for(console, out_dir, 20.0, lambda t: good(t))
    assert report.decision == rp.KARAR_YAPILMADI and report.status == rp.STATUS_PROVA


def test_poor_run_fails(console, out_dir):
    # one hand disappears for every 10th frame cluster -> ~85% coverage
    def prov(t):
        return frame(t, hand(R)) if int(t / 33) % 7 == 0 else good(t)

    _, _, report = run_for(console, out_dir, 300.0, prov)
    assert report.decision == rp.KARAR_KALDI


def test_ctrl_c_partial_saved(console, out_dir):
    run, src, report = run_for(console, out_dir, 300.0, lambda t: good(t), interrupt_after=500)
    assert report.status == rp.STATUS_YARIM and report.decision == rp.KARAR_YAPILMADI
    assert src.closed >= 1
    data = json.loads(run.json_path.read_text(encoding="utf-8"))
    assert data["status"] == "yarım" and data["raw"]["stats"]["ornek_sayisi"] > 0
