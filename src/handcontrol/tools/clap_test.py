"""Clap gate: 20 deliberate claps (>= 18 with exactly one CLAP event each) and zero accidental CLAP events
in a five-minute ordinary-movement session.

Run: python -m handcontrol.tools.clap_test [--claps 20] [--seconds 300]
"""
from __future__ import annotations

import argparse
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from ..contracts import GestureEvent, GestureKind
from . import report as rp
from .common import (
    Console,
    FrameSource,
    LiveSource,
    Observation,
    RealConsole,
    ToolError,
    add_camera_args,
    ask_conditions,
    run_main,
)

TOOL = "clap_test"
FULL_CLAPS = 20
FULL_SECONDS = 300.0
MIN_EXACT_RATIO = 0.9              # 18/20
CLAP_WINDOW_MS = 3500.0            # window after Enter; late second events still count as a double


def required_exact(claps: int) -> int:
    return math.ceil(MIN_EXACT_RATIO * claps - 1e-9)


@dataclass
class ClapStats:
    per_clap: list[int] = field(default_factory=list)      # CLAP events inside each prompted window
    stray_between: int = 0                                  # CLAP events outside any prompted window
    accidental: int = 0                                     # CLAP events in the ordinary-movement session
    candidate_starts: int = 0                               # near-misses during the session
    candidate_aborts: int = 0
    session_ms: float = 0.0

    @property
    def exactly_one(self) -> int:
        return sum(1 for n in self.per_clap if n == 1)

    @property
    def recognized_any(self) -> int:
        return sum(1 for n in self.per_clap if n >= 1)

    @property
    def doubles(self) -> int:
        return sum(1 for n in self.per_clap if n >= 2)

    @property
    def missed(self) -> int:
        return sum(1 for n in self.per_clap if n == 0)

    def summary(self) -> dict[str, Any]:
        return {
            "istenen_alkis": len(self.per_clap),
            "tam_bir_olay": self.exactly_one,
            "en_az_bir_olay": self.recognized_any,
            "cift_olay": self.doubles,
            "kacirilan": self.missed,
            "istenmeyen_olay_istem_arasi": self.stray_between,
            "kazara_alkis_oturum": self.accidental,
            "aday_baslangic_oturum": self.candidate_starts,
            "aday_iptal_oturum": self.candidate_aborts,
            "oturum_s": round(self.session_ms / 1000.0, 1),
        }


def count_events(events: list[GestureEvent], kind: GestureKind) -> int:
    return sum(1 for e in events if e.kind == kind)


def decide(
    stats: ClapStats, claps: int, seconds: float, phase1_done: bool, phase2_done: bool, interrupted: bool
) -> tuple[str, str, str]:
    rehearsal = claps < FULL_CLAPS or seconds < FULL_SECONDS
    prompted_ok = phase1_done and stats.exactly_one >= required_exact(claps)
    session_ok = phase2_done and stats.accidental == 0
    if interrupted or not (phase1_done and phase2_done):
        note = "Koşu yarım kaldı."
        if rehearsal:
            note += " Ayrıca prova ayarları (20 alkıştan az ya da 300 sn'den kısa): kabul sayılmaz."
        return rp.STATUS_YARIM, rp.KARAR_YAPILMADI, note
    if rehearsal:
        verdict = "geçerdi" if prompted_ok and session_ok else "geçmezdi"
        return rp.STATUS_PROVA, rp.KARAR_YAPILMADI, f"prova, kabul sayılmaz (gösterge: kapı {verdict})."
    if prompted_ok and session_ok:
        return (
            rp.STATUS_TAMAM, rp.KARAR_GECTI,
            f"{stats.exactly_one}/{claps} alkış tam bir olay (>= {required_exact(claps)}); kazara alkış 0.",
        )
    why = []
    if not prompted_ok:
        why.append(f"tam bir olay {stats.exactly_one}/{claps} (gerekli {required_exact(claps)})")
    if not session_ok:
        why.append(f"kazara alkış {stats.accidental} (gerekli 0)")
    return rp.STATUS_TAMAM, rp.KARAR_KALDI, "; ".join(why) + ". Ayar sonrası farklı dizide yeniden test."


class ClapRun:
    def __init__(
        self, source: FrameSource, console: Console, *, claps: int = FULL_CLAPS,
        seconds: float = FULL_SECONDS, out_dir: Optional[Path] = None,
        software: Optional[dict[str, Any]] = None, recognizer: Any = None,
        window_ms: float = CLAP_WINDOW_MS,
    ) -> None:
        if recognizer is None:
            from ..gestures import GestureRecognizer

            recognizer = GestureRecognizer()
        self.source, self.console, self.claps, self.seconds = source, console, claps, seconds
        self.out_dir, self.recognizer, self.window_ms = out_dir, recognizer, window_ms
        self.stats = ClapStats()
        self.conditions: dict[str, str] = {}
        self.error: Optional[str] = None
        self.phase1_done = False
        self.phase2_done = False
        self._software = software
        self._last_capture = -1.0
        self.stem = rp.timestamp_stem(TOOL)
        self.md_path: Optional[Path] = None
        self.json_path: Optional[Path] = None
        self._idle_stray = True       # pump counts strays only while waiting for Enter

    # one unique frame -> gesture events; repeated capture times are ignored
    def _process(self, obs: Observation, min_ms: float = -1.0) -> list[GestureEvent]:
        t = obs.frame.capture_ms
        if t <= self._last_capture or t < min_ms:
            return []
        self._last_capture = t
        return list(self.recognizer.update(obs.frame))

    def _pump(self) -> None:
        obs = self.source.next(0.03)
        if obs is None:
            return
        n = count_events(self._process(obs), GestureKind.CLAP)
        if self._idle_stray:
            self.stats.stray_between += n

    def _prompted_phase(self) -> None:
        say = self.console.say
        say(f"AŞAMA 1: {self.claps} kasıtlı alkış. Her istemde Enter'a basın, sonra TEK bir alkış yapın.")
        for i in range(1, self.claps + 1):
            self._idle_stray = True
            self.console.ask(f"  [{i}/{self.claps}] Hazır olunca Enter, sonra tek alkış: ", self._pump)
            self._idle_stray = False
            start = self.source.now_ms()
            n = 0
            while self.source.now_ms() - start < self.window_ms:
                obs = self.source.next(0.1)
                if obs is not None:
                    n += count_events(self._process(obs, start), GestureKind.CLAP)
            self.stats.per_clap.append(n)
            say("    -> " + ("tam 1 olay" if n == 1 else ("KAÇIRILDI" if n == 0 else f"ÇİFT OLAY ({n})")))
        self.phase1_done = True

    def _session_phase(self) -> None:
        say = self.console.say
        say(f"AŞAMA 2: {self.seconds:.0f} sn sıradan kullanım (işaret etme, tutuş, el sallama, ellere yaklaşma). ALKIŞ YAPMAYIN.")
        self._idle_stray = True
        self.console.ask("  Hazırsanız Enter: ", self._pump)
        self._idle_stray = False
        start = self.source.now_ms()
        next_note = start + 60000.0
        while self.source.now_ms() - start < self.seconds * 1000.0:
            obs = self.source.next(0.2)
            if obs is not None:
                ev = self._process(obs, start)
                self.stats.accidental += count_events(ev, GestureKind.CLAP)
                self.stats.candidate_starts += count_events(ev, GestureKind.CLAP_CANDIDATE_START)
                self.stats.candidate_aborts += count_events(ev, GestureKind.CLAP_CANDIDATE_ABORT)
            self.stats.session_ms = self.source.now_ms() - start
            now = self.source.now_ms()
            if now >= next_note:
                next_note += 60000.0
                say(f"  {int((now - start) / 1000)} sn, kazara alkış: {self.stats.accidental}")
        self.phase2_done = True

    def build_report(self, interrupted: bool) -> rp.Report:
        st = self.stats
        status, karar, note = decide(st, self.claps, self.seconds, self.phase1_done, self.phase2_done, interrupted)
        if self.error:
            note = f"{note} Hata: {self.error}"
        sw = self._software if self._software is not None else rp.collect_software()
        self._software = sw
        try:
            cam = self.source.camera_info()
        except Exception:
            cam = {}
        s = st.summary()
        rehearsal = self.claps < FULL_CLAPS or self.seconds < FULL_SECONDS
        return rp.Report(
            tool=TOOL,
            title="Alkış kapısı" + (" - PROVA" if rehearsal else ""),
            stem=self.stem, status=status, environment=rp.collect_environment(cam), software=sw,
            conditions=self.conditions,
            experiment=[
                f"Aşama 1: {self.claps} kasıtlı alkış, tek tek istemli; her pencere {self.window_ms / 1000:.1f} sn.",
                f"Aşama 2: {self.seconds:.0f} sn sıradan hareket (alkış yok); CLAP olayı = kazara.",
                "Sayım: tam 1 CLAP olayı = tanındı; 0 = kaçırıldı; 2+ = çift olay (geçerli sayılmaz).",
            ],
            result_lines=[
                f"Tam bir olay: {s['tam_bir_olay']}/{s['istenen_alkis']} (gerekli {required_exact(self.claps)}); "
                f"kaçırılan {s['kacirilan']}, çift olay {s['cift_olay']}",
                f"İstemler arası istenmeyen CLAP: {s['istenmeyen_olay_istem_arasi']}",
                f"Kazara alkış (oturum {s['oturum_s']} sn): {s['kazara_alkis_oturum']} (gerekli 0)",
                f"Yakın kaçırma (aday başlangıç/iptal): {s['aday_baslangic_oturum']}/{s['aday_iptal_oturum']}",
            ],
            raw={"claps": self.claps, "seconds": self.seconds, "per_clap": st.per_clap, "stats": s,
                 "phase1_done": self.phase1_done, "phase2_done": self.phase2_done},
            decision=karar, decision_note=note,
        )

    def _save(self, interrupted: bool) -> rp.Report:
        r = self.build_report(interrupted)
        self.md_path, self.json_path = rp.save_report(r, self.out_dir)
        return r

    def execute(self) -> rp.Report:
        say = self.console.say
        interrupted = True
        try:
            self.source.open()
            self.conditions = ask_conditions(self.console)
            self._prompted_phase()
            self._session_phase()
            interrupted = False
        except KeyboardInterrupt:
            say("\nDurduruldu (Ctrl+C). Kısmi sonuç kaydediliyor...")
        except ToolError as exc:
            self.error = str(exc)
            say(f"HATA: {exc}")
        finally:
            try:
                self.source.close()
            except Exception:
                pass
        report = self._save(interrupted)
        say(f"Karar: {report.decision} ({report.status})")
        say(f"Rapor: {self.md_path}")
        return report


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="handcontrol.tools.clap_test", description="Alkış kabul kapısı")
    p.add_argument("--claps", type=int, default=FULL_CLAPS, help="alkış sayısı (20 altı = prova)")
    p.add_argument("--seconds", type=float, default=FULL_SECONDS, help="sıradan oturum süresi (300 altı = prova)")
    p.add_argument("--swap-handedness", action="store_true")
    add_camera_args(p)
    args = p.parse_args(argv)
    run = ClapRun(
        LiveSource(index=args.camera_index, backend=args.backend, swap_handedness=args.swap_handedness),
        RealConsole(), claps=args.claps, seconds=args.seconds,
        out_dir=Path(args.out_dir) if args.out_dir else None,
    )

    def go() -> int:
        run.execute()
        return 2 if run.error else 0

    run_main(go)
    return 0


if __name__ == "__main__":
    main()
