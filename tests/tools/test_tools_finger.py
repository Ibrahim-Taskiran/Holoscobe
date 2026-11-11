from __future__ import annotations

import json

import pytest
from _tools_fakes import FakeConsole, FakeSource, frame, hand

from handcontrol.contracts import FingerName, FingerState, Handedness, Quality
from handcontrol.tools import finger_test as ft
from handcontrol.tools import report as rp

L, R = Handedness.LEFT, Handedness.RIGHT
IDX = FingerName.INDEX
EXT, BENT, UNK = FingerState.EXTENDED, FingerState.BENT, FingerState.UNKNOWN


def trial(hand_="right", finger="index", state="bent"):
    return ft.Trial(0, 0, hand_, finger, state, "yakın", "eğik")


def evaluate(provider, tr=None, step=50.0, n=400, **kw):
    ev = ft.TrialEvaluator(tr or trial(), **kw)
    t = 0.0
    for _ in range(n):
        out = ev.feed(provider(t))
        if out:
            return out
        t += step
    return None


# ---------------------------------------------------------------- scoring


def test_scores_state_at_500ms_after_settle():
    # still from t=0 -> settle at 300 ms -> score frame at >= 800 ms.
    right_until_800 = lambda t: frame(t, hand(R, {IDX: BENT if t < 800 else EXT}))
    wrong_from_800 = lambda t: frame(t, hand(R, {IDX: BENT if t < 800 else EXT}))
    assert evaluate(right_until_800).outcome == "yanlis"      # state at 800 ms is EXT -> wrong
    right_from_800 = lambda t: frame(t, hand(R, {IDX: EXT if t < 800 else BENT}))
    out = evaluate(right_from_800)
    assert out.outcome == "dogru" and out.correct               # early wrong state is ignored
    assert out.settle_ms == 300.0
    assert wrong_from_800(0).hands[0].handedness == R


def test_unknown_state_is_failure():
    out = evaluate(lambda t: frame(t, hand(R, {IDX: UNK})))
    assert out.outcome == "bilinmiyor" and not out.correct


def test_missing_hand_after_settle_is_failure():
    out = evaluate(lambda t: frame(t, hand(R, {IDX: BENT})) if t < 600 else frame(t))
    assert out.outcome == "el_yok" and not out.correct


def test_wrong_label_hand_never_settles_and_times_out():
    out = evaluate(lambda t: frame(t, hand(L, {IDX: BENT})), timeout_ms=2000)
    assert out.outcome == "yerlesmedi" and out.settle_ms is None


def test_moving_hand_never_settles():
    out = evaluate(lambda t: frame(t, hand(R, {IDX: BENT}, center=(100 + t, 200))), timeout_ms=2000)
    assert out.outcome == "yerlesmedi"


def test_two_hands_same_label_is_ambiguous():
    out = evaluate(lambda t: frame(t, hand(R, {IDX: BENT}), hand(R, {IDX: BENT}, hand_id=2)), timeout_ms=1500)
    assert out.outcome == "yerlesmedi"      # ambiguous hands cannot settle, so nothing is ever scored


def test_other_hand_is_ignored():
    out = evaluate(lambda t: frame(t, hand(R, {IDX: BENT}), hand(L, {IDX: EXT}, hand_id=2)))
    assert out.outcome == "dogru"


def test_zero_palm_scale_does_not_settle():
    out = evaluate(lambda t: frame(t, hand(R, {IDX: BENT}, quality=Quality.DEGRADED)), timeout_ms=1000)
    assert out.outcome == "yerlesmedi"


# ---------------------------------------------------------------- gate


def results_with(counts: dict[tuple[str, str, str], int], trials=20):
    rows = []
    for h in ft.HANDS:
        for f in ft.FINGERS:
            for s in ft.STATES:
                ok = counts.get((h, f, s), trials)
                rows += [dict(hand=h, finger=f, state=s, outcome="dogru" if i < ok else "yanlis") for i in range(trials)]
    return rows


def test_gate_all_19_of_20_passes():
    counts = {(h, f, s): 19 for h in ft.HANDS for f in ft.FINGERS for s in ft.STATES}
    g = ft.evaluate_gate(results_with(counts), ft.HANDS, 20)
    assert g.all_groups_ok and g.complete and g.accepted_config
    assert ft.decide(g, False)[1] == rp.KARAR_GECTI


def test_gate_pooled_97_percent_with_one_group_at_18_fails():
    keys = [(h, f, s) for h in ft.HANDS for f in ft.FINGERS for s in ft.STATES]
    counts = {k: 19 for k in keys[:10]}                 # ten groups at 19/20, the rest perfect
    counts[("left", "ring", "bent")] = 18               # one group at 18/20
    g = ft.evaluate_gate(results_with(counts), ft.HANDS, 20)
    assert g.pooled_correct / g.pooled_total == pytest.approx(0.97, abs=0.005)
    assert not g.all_groups_ok
    status, karar, note = ft.decide(g, False)
    assert karar == rp.KARAR_KALDI and "SOL YÜZÜK" in note and "18/20" in note


def test_gate_incomplete_group_is_not_pass():
    rows = results_with({})
    rows = [r for r in rows if not (r["hand"] == "right" and r["finger"] == "little" and r["state"] == "bent")]
    g = ft.evaluate_gate(rows, ft.HANDS, 20)
    assert not g.complete and not g.all_groups_ok
    assert ft.decide(g, False)[1] == rp.KARAR_YAPILMADI


def test_rehearsal_never_accepted():
    g = ft.evaluate_gate(results_with({}, trials=3), ft.HANDS, 3)
    assert g.complete and g.all_groups_ok and g.rehearsal and not g.accepted_config
    status, karar, note = ft.decide(g, False)
    assert karar == rp.KARAR_YAPILMADI and status == rp.STATUS_PROVA and "prova, kabul sayılmaz" in note
    # single hand with 20 trials is a partial gate -> also rehearsal
    one = [r for r in results_with({}) if r["hand"] == "right"]
    g1 = ft.evaluate_gate(one, ("right",), 20)
    assert g1.rehearsal and ft.decide(g1, False)[1] == rp.KARAR_YAPILMADI


def test_required_correct():
    assert ft.required_correct(20) == 19
    assert ft.required_correct(5) == 5


# ---------------------------------------------------------------- plan


def test_plan_has_400_trials_in_balanced_random_blocks():
    plan = ft.build_plan(ft.HANDS, 20, seed=7)
    assert len(plan) == 400
    groups = {}
    for t in plan:
        groups[t.group] = groups.get(t.group, 0) + 1
    assert len(groups) == 20 and set(groups.values()) == {20}
    for b in range(20):
        block = [t for t in plan if t.block == b]
        assert len({t.group for t in block}) == 20          # each group exactly once per block
    assert [t.group for t in plan[:20]] != [t.group for t in plan[20:40]]    # randomized
    conds = [(plan[b * 20].distance, plan[b * 20].view) for b in range(4)]
    assert len(set(conds)) == 4                              # near/far x forward/oblique alternate
    assert ft.build_plan(ft.HANDS, 20, seed=7) == plan


# ---------------------------------------------------------------- runs


def perfect_provider(run, wrong=lambda tr: False):
    opposite = {"extended": BENT, "bent": EXT}

    def provider(t):
        tr = run.current_trial
        if tr is None:
            return frame(t, hand(R))
        want = FingerState(tr.state)
        if wrong(tr):
            want = opposite[tr.state]
        return frame(t, hand(L if tr.hand == "left" else R, {FingerName(tr.finger): want}))

    return provider


def make_run(console, out_dir, *, wrong=lambda tr: False, trials=2, hands=("right",), source_kw=None, **kw):
    holder = {}
    src = FakeSource(lambda t: holder["p"](t), **(source_kw or {}))
    run = ft.FingerTestRun(src, console, hands=hands, trials=trials, seed=1, out_dir=out_dir, software={}, **kw)
    holder["p"] = perfect_provider(run, wrong)
    return run, src


def test_full_400_run_passes_and_writes_report(console, out_dir):
    run, src = make_run(console, out_dir, trials=20, hands=ft.HANDS)
    report = run.execute()
    assert len(run.results) == 400
    assert report.decision == rp.KARAR_GECTI and report.status == rp.STATUS_TAMAM
    assert run.md_path.exists() and run.json_path.exists() and run.md_path.name.startswith("hw_finger_test_")
    assert src.closed >= 1
    assert any("SOL el, İŞARET parmağı" in s or "SAĞ el, İŞARET parmağı" in s for s in console.said)


def test_full_run_one_bad_group_fails(console, out_dir):
    bad = lambda tr: tr.group == ("left", "ring", "bent") and tr.block in (3, 11)
    run, _ = make_run(console, out_dir, trials=20, hands=ft.HANDS, wrong=bad)
    report = run.execute()
    g = next(x for x in run.build_report(False).raw["gate"]["groups"] if (x["hand"], x["finger"], x["state"]) == ("left", "ring", "bent"))
    assert g["correct"] < 19
    assert report.decision == rp.KARAR_KALDI


def test_rehearsal_run_labeled_not_accepted(console, out_dir):
    run, _ = make_run(console, out_dir, trials=2)
    report = run.execute()
    assert report.decision == rp.KARAR_YAPILMADI and "prova, kabul sayılmaz" in report.status
    text = run.md_path.read_text(encoding="utf-8")
    assert "PROVA" in text and "prova, kabul sayılmaz" in text


def test_handedness_reversed_aborts_and_offers_swap(console, out_dir):
    src = FakeSource(lambda t: frame(t, hand(L)))
    run = ft.FingerTestRun(src, console, hands=("right",), trials=1, out_dir=out_dir, software={})
    report = run.execute()
    assert run.handedness["sonuc"] == "ters" and not run.results
    assert any("--swap-handedness" in s for s in console.said)
    assert report.decision == rp.KARAR_YAPILMADI
    assert json.loads(run.json_path.read_text(encoding="utf-8"))["raw"]["handedness_check"]["sonuc"] == "ters"


def test_handedness_correct_is_recorded(console, out_dir):
    run, _ = make_run(console, out_dir, trials=1)
    run.execute()
    assert run.handedness["sonuc"] == "dogru"


def test_ctrl_c_saves_partial_marked_yarim_and_releases_source(console, out_dir):
    run, src = make_run(console, out_dir, trials=5, source_kw={"interrupt_after": 400})
    report = run.execute()
    assert 0 < len(run.results) < 50
    assert report.status == rp.STATUS_YARIM and report.decision == rp.KARAR_YAPILMADI
    assert src.closed >= 1
    assert "yarım" in run.md_path.read_text(encoding="utf-8")
    assert json.loads(run.json_path.read_text(encoding="utf-8"))["status"] == "yarım"


def test_resume_continues_without_repeating(console, out_dir):
    run1, _ = make_run(console, out_dir, trials=3, source_kw={"interrupt_after": 400})
    run1.execute()
    done = len(run1.results)
    assert 0 < done < 30
    data = rp.load_json(run1.json_path)

    holder = {}
    src2 = FakeSource(lambda t: holder["p"](t))
    run2 = ft.FingerTestRun(src2, FakeConsole(), out_dir=out_dir, software={}, resume=data)
    holder["p"] = perfect_provider(run2)
    report = run2.execute()
    assert run2.stem == run1.stem
    assert len(run2.results) == 30
    assert sorted(r["index"] for r in run2.results) == list(range(30))
    assert run2.results[:done] == run1.results
    assert report.status == rp.STATUS_PROVA     # 3 trials, one hand: rehearsal


def test_camera_error_message_printed_and_partial_saved(console, out_dir):
    src = FakeSource(lambda t: None, open_error="Kamera bulunamadı.")
    run = ft.FingerTestRun(src, console, hands=("right",), trials=1, out_dir=out_dir, software={})
    report = run.execute()
    assert run.error == "Kamera bulunamadı."
    assert any("Kamera bulunamadı." in s for s in console.said)
    assert report.status == rp.STATUS_YARIM and run.md_path.exists()


def test_report_stores_no_landmarks_or_frames(console, out_dir):
    run, _ = make_run(console, out_dir, trials=1)
    run.execute()
    raw = run.json_path.read_text(encoding="utf-8")
    assert "landmark" not in raw.lower() and "frame" not in raw.lower()
