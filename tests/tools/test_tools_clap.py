from __future__ import annotations

from _tools_fakes import FakeRecognizer, FakeSource, clap, frame, hand

from handcontrol.contracts import GestureEvent, GestureKind
from handcontrol.tools import clap_test as ct
from handcontrol.tools import report as rp


def build(console, out_dir, plan, *, accidental=0, claps=None, seconds=300.0, interrupt_after=None):
    """plan[i] = CLAP events emitted inside prompted window i (0, 1 or 2)."""
    state = {"idx": -1, "frames_in": 0, "seen_len": 0, "sess": 0}
    holder = {}

    def fn(f):
        run = holder["run"]
        n = len(run.stats.per_clap)
        if n != state["seen_len"] or state["idx"] < 0:
            state.update(seen_len=n, idx=n, frames_in=0)
        state["frames_in"] += 1
        ev = []
        if not run.phase1_done:
            if run._idle_stray is False and state["idx"] < len(plan):
                k = state["frames_in"]
                if (k == 10 and plan[state["idx"]] >= 1) or (k == 25 and plan[state["idx"]] >= 2):
                    ev.append(clap(f.capture_ms))
        elif not run.phase2_done and run._idle_stray is False:
            state["sess"] += 1
            if state["sess"] in (100, 200, 300)[:accidental]:
                ev.append(clap(f.capture_ms))
            if state["sess"] == 50:
                ev.append(GestureEvent(GestureKind.CLAP_CANDIDATE_START, f.capture_ms))
                ev.append(GestureEvent(GestureKind.CLAP_CANDIDATE_ABORT, f.capture_ms))
        return ev

    src = FakeSource(lambda t: frame(t, hand()), interrupt_after=interrupt_after)
    run = ct.ClapRun(src, console, claps=claps or len(plan), seconds=seconds, out_dir=out_dir,
                     software={}, recognizer=FakeRecognizer(fn))
    holder["run"] = run
    return run, src


def test_counting_exact_missed_and_double(console, out_dir):
    run, _ = build(console, out_dir, [1, 1, 0, 2, 1], seconds=5.0)
    run.execute()
    s = run.stats
    assert s.per_clap == [1, 1, 0, 2, 1]
    assert (s.exactly_one, s.recognized_any, s.doubles, s.missed) == (3, 4, 1, 1)


def test_full_gate_pass(console, out_dir):
    run, _ = build(console, out_dir, [1] * 18 + [0, 0])
    report = run.execute()
    assert report.decision == rp.KARAR_GECTI and report.status == rp.STATUS_TAMAM
    assert run.stats.accidental == 0 and run.stats.candidate_starts == 1 and run.stats.candidate_aborts == 1


def test_double_events_do_not_count_as_recognized(console, out_dir):
    # 20 claps recognized at least once, but 3 doubles -> only 17 exactly-one -> fail
    run, _ = build(console, out_dir, [1] * 17 + [2, 2, 2])
    report = run.execute()
    assert run.stats.recognized_any == 20 and run.stats.exactly_one == 17
    assert report.decision == rp.KARAR_KALDI and "17/20" in report.decision_note


def test_one_accidental_clap_fails_even_with_perfect_prompted(console, out_dir):
    run, _ = build(console, out_dir, [1] * 20, accidental=1)
    report = run.execute()
    assert run.stats.accidental == 1
    assert report.decision == rp.KARAR_KALDI and "kazara" in report.decision_note


def test_stray_clap_between_prompts_counted_separately(console, out_dir):
    run, _ = build(console, out_dir, [1], claps=1, seconds=2.0)
    run._idle_stray = True
    from _tools_fakes import FakeSource as FS  # direct pump path
    run.source = FS(lambda t: frame(t, hand()))
    run.recognizer = FakeRecognizer(lambda f: [clap(f.capture_ms)])
    run._pump()
    assert run.stats.stray_between == 1 and run.stats.per_clap == []


def test_repeated_frame_time_not_reprocessed(console, out_dir):
    calls = []
    run, _ = build(console, out_dir, [1], claps=1, seconds=1.0)
    run.recognizer = FakeRecognizer(lambda f: calls.append(f.capture_ms) or [])
    from handcontrol.tools.common import Observation

    o = Observation(frame(500.0, hand()), 5.0)
    run._process(o)
    run._process(o)
    assert calls == [500.0]


def test_rehearsal_never_accepted(console, out_dir):
    run, _ = build(console, out_dir, [1, 1, 1], seconds=5.0)
    report = run.execute()
    assert report.decision == rp.KARAR_YAPILMADI and report.status == rp.STATUS_PROVA
    assert "prova, kabul sayılmaz" in report.status


def test_ctrl_c_during_session_saves_partial(console, out_dir):
    run, src = build(console, out_dir, [1] * 3, claps=3, seconds=300.0, interrupt_after=400)
    report = run.execute()
    assert run.phase1_done and not run.phase2_done
    assert report.status == rp.STATUS_YARIM and report.decision == rp.KARAR_YAPILMADI
    assert src.closed >= 1 and run.json_path.exists()


def test_required_exact():
    assert ct.required_exact(20) == 18
