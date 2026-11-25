"""Ten-finger gate (spec section 9): 400 labeled presentations, >= 19/20 in EVERY finger/state group.

Run: python -m handcontrol.tools.finger_test
Pure cores: build_plan, TrialEvaluator, evaluate_gate, decide. Console/camera live in FingerTestRun.
"""
from __future__ import annotations

import argparse
import math
import random
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

from ..contracts import FingerName, FingerState, FrameFeatures, Handedness
from . import report as rp
from .common import (
    Console,
    FrameSource,
    RealConsole,
    ToolRun,
    add_camera_args,
    ask_conditions,
    live_source,
    pump_source,
    run_tool,
)

TOOL = "finger_test"
HANDS = ("left", "right")
FINGERS = ("thumb", "index", "middle", "ring", "little")
STATES = ("extended", "bent")
FULL_TRIALS = 20
GATE_RATIO = 0.95                      # 19/20

HAND_TR = {"left": "SOL", "right": "SAĞ"}
FINGER_TR = {
    "thumb": "BAŞ PARMAK", "index": "İŞARET", "middle": "ORTA", "ring": "YÜZÜK", "little": "SERÇE",
}
STATE_TR = {"extended": "AÇIK (uzatılmış)", "bent": "BÜKÜLÜ"}
# Block conditions cycle so near/far and palm-forward/oblique alternate.
CONDITIONS = (
    ("yakın", "avuç içi kameraya"),
    ("uzak", "avuç içi kameraya"),
    ("yakın", "eğik"),
    ("uzak", "eğik"),
)

OUTCOME_OK = "dogru"
OUTCOME_TR = {
    "dogru": "doğru",
    "yanlis": "yanlış durum",
    "bilinmiyor": "bilinmiyor (parmak durumu belirsiz)",
    "el_yok": "el görünmüyor",
    "belirsiz": "aynı etiketli birden çok el",
    "yerlesmedi": "poz yerleşmedi",
}


# ------------------------------------------------------------------ pure core


@dataclass(frozen=True)
class Trial:
    index: int
    block: int
    hand: str
    finger: str
    state: str
    distance: str
    view: str

    @property
    def group(self) -> tuple[str, str, str]:
        return (self.hand, self.finger, self.state)


def instruction(t: Trial) -> str:
    return f"{HAND_TR[t.hand]} el, {FINGER_TR[t.finger]} parmağı: {STATE_TR[t.state]} tut"


def build_plan(hands: tuple[str, ...], trials: int, seed: Optional[int] = None) -> list[Trial]:
    """`trials` blocks; each block shows every hand/finger/state group once in random order."""
    rng = random.Random(seed)
    groups = [(h, f, s) for h in hands for f in FINGERS for s in STATES]
    plan: list[Trial] = []
    for b in range(trials):
        block = groups[:]
        rng.shuffle(block)
        dist, view = CONDITIONS[b % len(CONDITIONS)]
        for h, f, s in block:
            plan.append(Trial(len(plan), b, h, f, s, dist, view))
    return plan


@dataclass(frozen=True)
class TrialOutcome:
    outcome: str
    observed: str                      # finger state seen at scoring time, or "-"
    settle_ms: Optional[float]         # settle time relative to the first frame, None if never settled

    @property
    def correct(self) -> bool:
        return self.outcome == OUTCOME_OK


_HAND_ENUM = {"left": Handedness.LEFT, "right": Handedness.RIGHT}
_FINGER_ENUM = {f.value: f for f in FingerName}
_STATE_ENUM = {s.value: s for s in FingerState}


class TrialEvaluator:
    """Feeds frames after Enter. Settle = target hand present and still for settle_ms.
    Score = finger state in the first frame at/after settle + score_delay_ms.
    Unknown, missing hand, wrong state or never settling all count as failure."""

    def __init__(
        self,
        trial: Trial,
        *,
        settle_ms: float = 300.0,
        score_delay_ms: float = 500.0,
        timeout_ms: float = 10000.0,
        still_palm: float = 0.3,
    ) -> None:
        self.trial = trial
        self.settle_ms = settle_ms
        self.score_delay_ms = score_delay_ms
        self.timeout_ms = timeout_ms
        self.still_palm = still_palm
        self._t0: Optional[float] = None
        self._settle_t: Optional[float] = None
        self._window: deque[tuple[float, float, float]] = deque()   # (t, x, y)

    def _pick(self, frame: FrameFeatures) -> tuple[Optional[Any], int]:
        want = _HAND_ENUM[self.trial.hand]
        hands = [h for h in frame.hands if h.handedness == want]
        return (hands[0] if len(hands) == 1 else None), len(hands)

    def _still(self, latest: tuple[float, float, float], scale: float) -> bool:
        lim = self.still_palm * scale
        return all(math.hypot(x - latest[1], y - latest[2]) <= lim for _, x, y in self._window)

    def feed(self, frame: FrameFeatures) -> Optional[TrialOutcome]:
        t = frame.capture_ms
        if self._t0 is None:
            self._t0 = t
        hand, n = self._pick(frame)

        if self._settle_t is None:
            if hand is not None and math.isfinite(hand.palm_scale_px) and hand.palm_scale_px > 0:
                cx, cy = hand.palm_center_px
                self._window.append((t, cx, cy))
                latest = self._window[-1]
                while len(self._window) > 1 and not self._still(latest, hand.palm_scale_px):
                    self._window.popleft()
                if t - self._window[0][0] >= self.settle_ms:
                    self._settle_t = t
            else:
                self._window.clear()
            if self._settle_t is None:
                if t - self._t0 >= self.timeout_ms:
                    return TrialOutcome("yerlesmedi", "-", None)
                return None

        if t < self._settle_t + self.score_delay_ms:
            return None
        settle_rel = self._settle_t - (self._t0 or 0.0)
        if n == 0:
            return TrialOutcome("el_yok", "-", settle_rel)
        if hand is None:
            return TrialOutcome("belirsiz", "-", settle_rel)
        info = next((f for f in hand.fingers if f.name == _FINGER_ENUM[self.trial.finger]), None)
        state = info.state if info is not None else FingerState.UNKNOWN
        if state == FingerState.UNKNOWN:
            return TrialOutcome("bilinmiyor", state.value, settle_rel)
        if state == _STATE_ENUM[self.trial.state]:
            return TrialOutcome(OUTCOME_OK, state.value, settle_rel)
        return TrialOutcome("yanlis", state.value, settle_rel)


def required_correct(trials_per_group: int) -> int:
    """19 for 20 trials; the same 95% ratio (rounded up) for rehearsals."""
    return math.ceil(GATE_RATIO * trials_per_group - 1e-9)


@dataclass
class GroupStat:
    hand: str
    finger: str
    state: str
    total: int
    correct: int
    required: int
    complete: bool

    @property
    def ok(self) -> bool:
        return self.complete and self.correct >= self.required


@dataclass
class GateResult:
    groups: list[GroupStat]
    complete: bool                     # every group has all its trials
    all_groups_ok: bool                # complete and every group >= required
    pooled_correct: int
    pooled_total: int
    rehearsal: bool
    accepted_config: bool              # 20 trials, both hands: result may count as acceptance


def is_rehearsal(trials: int, hands: tuple[str, ...]) -> bool:
    return trials < FULL_TRIALS or tuple(sorted(hands)) != tuple(sorted(HANDS))


def evaluate_gate(results: list[dict[str, Any]], hands: tuple[str, ...], trials: int) -> GateResult:
    """Per-group gate. A pooled average never rescues a group below the requirement."""
    req = required_correct(trials)
    tally: dict[tuple[str, str, str], list[int]] = {
        (h, f, s): [0, 0] for h in hands for f in FINGERS for s in STATES
    }
    for r in results:
        key = (r["hand"], r["finger"], r["state"])
        if key in tally:
            tally[key][0] += 1
            tally[key][1] += 1 if r["outcome"] == OUTCOME_OK else 0
    groups = [
        GroupStat(h, f, s, tot, cor, req, tot >= trials) for (h, f, s), (tot, cor) in tally.items()
    ]
    complete = all(g.complete for g in groups)
    return GateResult(
        groups=groups,
        complete=complete,
        all_groups_ok=complete and all(g.ok for g in groups),
        pooled_correct=sum(g.correct for g in groups),
        pooled_total=sum(g.total for g in groups),
        rehearsal=is_rehearsal(trials, hands),
        accepted_config=not is_rehearsal(trials, hands),
    )


def decide(gate: GateResult, interrupted: bool) -> tuple[str, str, str]:
    """Returns (status, karar, note). Rehearsals are never accepted."""
    if interrupted or not gate.complete:
        note = "Koşu yarım kaldı; kabul için baştan ya da --resume ile tamamlanmalı."
        if gate.rehearsal:
            note += " Ayrıca bu bir prova, kabul sayılmaz."
        return rp.STATUS_YARIM, rp.KARAR_YAPILMADI, note
    if gate.rehearsal:
        verdict = "tüm gruplar eşiği geçti" if gate.all_groups_ok else "en az bir grup eşiğin altında"
        return (
            rp.STATUS_PROVA,
            rp.KARAR_YAPILMADI,
            f"prova, kabul sayılmaz (gösterge: {verdict}). Kabul için 20 deneme ve iki el gerekir.",
        )
    if gate.all_groups_ok:
        return rp.STATUS_TAMAM, rp.KARAR_GECTI, "Her parmak/durum grubunda en az 19/20."
    bad = [g for g in gate.groups if not g.ok]
    names = ", ".join(
        f"{HAND_TR[g.hand]} {FINGER_TR[g.finger]} {STATE_TR[g.state].split()[0]} {g.correct}/{g.total}"
        for g in bad[:8]
    )
    return rp.STATUS_TAMAM, rp.KARAR_KALDI, f"Eşiğin altındaki gruplar: {names}. Ayar sonrası farklı dizide yeniden test."


# ------------------------------------------------------------------ handedness check


def check_handedness(
    source: FrameSource, console: Console, *, tries: int = 3, frames_needed: int = 15,
    window_ms: float = 4000.0, swap_used: bool = False,
) -> dict[str, Any]:
    """Ask for the RIGHT hand only and read the tracker label (unmirrored input)."""
    last: dict[str, Any] = {"sonuc": "belirsiz", "sag": 0, "sol": 0, "deneme": 0}
    for attempt in range(1, tries + 1):
        console.ask(
            "ADIM 0 - El etiketi kontrolü: yalnız SAĞ elinizi kaldırın (sol el görünmesin), Enter: ",
            pump_source(source),
        )
        start = source.now_ms()
        right = left = 0
        while source.now_ms() - start < window_ms and right + left < frames_needed:
            obs = source.next(0.2)
            if obs is None or obs.frame.capture_ms < start or len(obs.frame.hands) != 1:
                continue
            label = obs.frame.hands[0].handedness
            if label == Handedness.RIGHT:
                right += 1
            elif label == Handedness.LEFT:
                left += 1
        total = right + left
        last = {"sag": right, "sol": left, "deneme": attempt, "swap_kullanildi": swap_used}
        if total >= max(3, frames_needed // 3):
            if right >= 0.8 * total:
                last["sonuc"] = "dogru"
                return last
            if left >= 0.8 * total:
                last["sonuc"] = "ters"
                return last
        console.say("  El etiketi okunamadı, tekrar deneyin.")
    last["sonuc"] = "belirsiz"
    return last


# ------------------------------------------------------------------ runner


class FingerTestRun(ToolRun):
    tool = TOOL

    def __init__(
        self,
        source: FrameSource,
        console: Console,
        *,
        hands: tuple[str, ...] = HANDS,
        trials: int = FULL_TRIALS,
        seed: Optional[int] = None,
        out_dir: Optional[Path] = None,
        swap_handedness: bool = False,
        resume: Optional[dict[str, Any]] = None,
        software: Optional[dict[str, Any]] = None,
        evaluator_kwargs: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(source, console, out_dir, software)
        self.swap = swap_handedness
        self.evaluator_kwargs = evaluator_kwargs or {}
        self.current_trial: Optional[Trial] = None
        self.handedness: dict[str, Any] = {}
        self.results: list[dict[str, Any]] = []
        self._stopped_note = ""

        if resume:
            raw = resume["raw"]
            cfg = raw["config"]
            self.hands = tuple(cfg["hands"])
            self.trials = int(cfg["trials"])
            self.seed = cfg.get("seed")
            self.plan = [Trial(**t) for t in raw["plan"]]
            self.results = list(raw["results"])
            self.stem = resume["stem"]
            self.conditions = dict(resume.get("conditions", {}))
            self.handedness = dict(raw.get("handedness_check", {}))
            self.swap = swap_handedness or bool(cfg.get("swap_handedness", False))
        else:
            self.hands, self.trials, self.seed = hands, trials, seed
            self.plan = build_plan(hands, trials, seed)
        self.rehearsal = is_rehearsal(self.trials, self.hands)

    # ---- report assembly (called after every trial so a crash loses nothing)
    def build_report(self, interrupted: bool) -> rp.Report:
        gate = evaluate_gate(self.results, self.hands, self.trials)
        status, karar, note = decide(gate, interrupted)
        if self._stopped_note:
            status, karar, note = rp.STATUS_YARIM, rp.KARAR_YAPILMADI, self._stopped_note
        done = len(self.results)
        fails: dict[str, int] = {}
        for r in self.results:
            if r["outcome"] != OUTCOME_OK:
                fails[r["outcome"]] = fails.get(r["outcome"], 0) + 1
        label = self.handedness.get("sonuc", "yapılmadı")
        return rp.Report(
            tool=TOOL,
            title="On parmak doğruluk kapısı (kamera)" + (" - PROVA" if self.rehearsal else ""),
            stem=self.stem,
            status=status,
            environment=rp.collect_environment(self.camera_info()),
            software=self.software(),
            conditions=self.conditions,
            experiment=[
                f"Eller: {', '.join(HAND_TR[h] for h in self.hands)}; parmak x durum x {self.trials} deneme "
                f"= {len(self.plan)} sunum; her poz 1 sn tutulur.",
                "Elle verilen etiket: ekrandaki komut. Ölçüm: poz yerleştikten 500 ms sonra canlı "
                "özelliklerden parmak durumu.",
                "Mesafe (yakın/uzak) ve görünüm (avuç içi kameraya/eğik) blok başına dönüşümlü.",
                f"El etiketi kontrolü (sağ el): {label}"
                + (", --swap-handedness kullanıldı" if self.swap else ""),
                "Rastgele sıralı bloklar" + (f", seed={self.seed}" if self.seed is not None else "")
                + (" - PROVA: kabul sayılmaz" if self.rehearsal else ""),
            ],
            result_lines=[
                f"Tamamlanan: {done}/{len(self.plan)}; toplam doğru {gate.pooled_correct}/{gate.pooled_total} "
                f"(yalnız bilgi; kapı grup bazında)",
                f"Eşik: her grupta en az {required_correct(self.trials)}/{self.trials}",
                "Hatalar: " + (", ".join(f"{OUTCOME_TR[k]}={v}" for k, v in fails.items()) or "yok"),
                f"Eşiğin altındaki grup sayısı: {sum(1 for g in gate.groups if g.complete and not g.ok)}",
            ],
            raw={
                "config": {
                    "hands": list(self.hands), "trials": self.trials, "seed": self.seed,
                    "swap_handedness": self.swap, "rehearsal": self.rehearsal,
                },
                "plan": [asdict(t) for t in self.plan],
                "results": self.results,
                "handedness_check": self.handedness,
                "gate": {
                    "complete": gate.complete, "all_groups_ok": gate.all_groups_ok,
                    "pooled_correct": gate.pooled_correct, "pooled_total": gate.pooled_total,
                    "groups": [asdict(g) for g in gate.groups],
                },
            },
            details_md=self._details(gate),
            decision=karar,
            decision_note=self.with_error(note),
        )

    def _details(self, gate: GateResult) -> str:
        lines = ["## Grup sonuçları", "", "| El | Parmak | Durum | Doğru/Toplam | Gerekli | Sonuç |", "|---|---|---|---|---|---|"]
        for g in gate.groups:
            res = "geçti" if g.ok else ("kaldı" if g.complete else "eksik")
            lines.append(
                f"| {HAND_TR[g.hand]} | {FINGER_TR[g.finger]} | {STATE_TR[g.state].split()[0]} "
                f"| {g.correct}/{g.total} | {g.required} | {res} |"
            )
        lines += ["", "## Koşul dağılımı (mesafe / görünüm)", "", "| Mesafe | Görünüm | Doğru/Toplam |", "|---|---|---|"]
        for dist, view in CONDITIONS:
            rows = [r for r in self.results if r["distance"] == dist and r["view"] == view]
            lines.append(f"| {dist} | {view} | {sum(1 for r in rows if r['outcome'] == OUTCOME_OK)}/{len(rows)} |")
        return "\n".join(lines)

    # ---- trial loop
    def _wait_enter(self, prompt: str) -> float:
        self.console.ask(prompt, pump_source(self.source))
        return self.source.now_ms()

    def _run_trial(self, trial: Trial) -> TrialOutcome:
        enter_ms = self._wait_enter("  Pozu aldıysanız Enter: ")
        ev = TrialEvaluator(trial, **self.evaluator_kwargs)
        limit = ev.timeout_ms + ev.settle_ms + ev.score_delay_ms + 3000.0
        while True:
            obs = self.source.next(0.2)
            if obs is not None and obs.frame.capture_ms >= enter_ms:
                out = ev.feed(obs.frame)
                if out is not None:
                    return out
            if self.source.now_ms() - enter_ms > limit:
                return TrialOutcome("yerlesmedi", "-", None)

    def measure(self) -> bool:
        say = self.console.say
        self.source.open()
        if not self.conditions:
            self.conditions = ask_conditions(self.console)
        self.handedness = check_handedness(self.source, self.console, swap_used=self.swap)
        outcome = self.handedness["sonuc"]
        if outcome != "dogru":
            if outcome != "ters":
                hint = "El etiketi doğrulanamadı. Işığı/mesafeyi düzeltip yeniden deneyin."
            elif self.swap:
                hint = "Sağ el hâlâ SOL okunuyor. --swap-handedness olmadan yeniden deneyin."
            else:
                hint = ("Sağ el SOL olarak okundu. Etiketler ters. Yeniden çalıştırın: "
                        "python -m handcontrol.tools.finger_test --swap-handedness")
            say(hint)
            self._stopped_note = f"El etiketi kontrolü başarısız ({outcome}). {hint}"
            return False

        say(f"Başlıyoruz: {len(self.plan) - len(self.results)} sunum kaldı. Durdurmak için Ctrl+C (kısmi sonuç kaydedilir).")
        if self.rehearsal:
            say("UYARI: Bu bir PROVA; kabul sayılmaz.")
        for trial in self.plan[len(self.results):]:
            self.current_trial = trial
            if trial.index == 0 or trial.block != self.plan[trial.index - 1].block:
                say("")
                say(f"=== BLOK {trial.block + 1}/{self.trials}: mesafe {trial.distance.upper()}, görünüm {trial.view.upper()} ===")
                self._wait_enter("  Bu konuma geçtiyseniz Enter: ")
            say(f"[{trial.index + 1}/{len(self.plan)}] {instruction(trial)}")
            out = self._run_trial(trial)
            self.results.append({**asdict(trial), "outcome": out.outcome, "observed": out.observed,
                                 "settle_ms": out.settle_ms, "correct": out.correct})
            say("  -> " + ("DOĞRU" if out.correct else f"HATA: {OUTCOME_TR[out.outcome]}"))
            self.save(True)
        self.current_trial = None
        return True


# ------------------------------------------------------------------ CLI


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="handcontrol.tools.finger_test", description="On parmak kabul kapısı")
    p.add_argument("--trials", type=int, default=FULL_TRIALS, help="grup başına deneme (20 altı = prova)")
    p.add_argument("--hand", choices=("left", "right", "both"), default="both")
    p.add_argument("--resume", default=None, help="yarım kalan sonuç dosyası (.json)")
    p.add_argument("--seed", type=int, default=None)
    add_camera_args(p)
    args = p.parse_args(argv)
    if args.trials < 1:
        p.error("--trials en az 1 olmalı")

    resume = rp.load_json(Path(args.resume)) if args.resume else None
    if resume and resume.get("tool") != TOOL:
        p.error("--resume dosyası finger_test sonucu değil")
    hands = HANDS if args.hand == "both" else (args.hand,)
    swap = args.swap_handedness or bool(resume and resume["raw"]["config"].get("swap_handedness"))
    run_tool(lambda: FingerTestRun(
        live_source(args, swap=swap), RealConsole(), hands=hands, trials=args.trials, seed=args.seed,
        out_dir=args.out_dir, swap_handedness=swap, resume=resume,
    ))


if __name__ == "__main__":
    main()
