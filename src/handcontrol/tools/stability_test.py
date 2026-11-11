"""Two-hand stability gate: both hands with 21 points and USABLE quality on >= 95% of inference samples.

Run: python -m handcontrol.tools.stability_test [--seconds 300]
Repeated or fabricated samples are never counted: a sample whose capture time does not advance is ignored.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from ..contracts import FrameFeatures, Handedness, Quality
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
    percentile,
    pump_source,
    run_main,
)

TOOL = "stability_test"
FULL_SECONDS = 300.0
GATE_PCT = 95.0
GAP_MS = 250.0                    # interval between consecutive samples counted as a gap


def both_hands_good(frame: FrameFeatures) -> bool:
    """Two hands (one left, one right), each with 21 landmarks and USABLE quality."""
    if len(frame.hands) != 2:
        return False
    labels = {h.handedness for h in frame.hands}
    if labels != {Handedness.LEFT, Handedness.RIGHT}:
        return False
    return all(h.quality == Quality.USABLE and len(h.landmarks) == 21 for h in frame.hands)


@dataclass
class StabilityStats:
    gap_ms: float = GAP_MS
    samples: int = 0
    good: int = 0
    ignored_repeats: int = 0
    identity_ambiguous: int = 0
    gaps: int = 0
    max_gap_ms: float = 0.0
    first_ms: Optional[float] = None
    last_ms: Optional[float] = None
    good_time_ms: float = 0.0
    total_time_ms: float = 0.0
    _last_good: bool = False
    age: list[float] = field(default_factory=list)
    infer: list[float] = field(default_factory=list)

    def add(self, obs: Observation) -> bool:
        """Returns False when the sample is a repeat (not counted)."""
        f = obs.frame
        if self.last_ms is not None and f.capture_ms <= self.last_ms:
            self.ignored_repeats += 1
            return False
        good = both_hands_good(f)
        if self.last_ms is not None:
            dt = f.capture_ms - self.last_ms
            self.total_time_ms += dt
            if dt > self.gap_ms:
                self.gaps += 1
                self.max_gap_ms = max(self.max_gap_ms, dt)
            elif self._last_good:
                self.good_time_ms += dt            # gaps never count as covered time
        else:
            self.first_ms = f.capture_ms
        self.samples += 1
        self.good += 1 if good else 0
        self.identity_ambiguous += 1 if f.identity_ambiguous else 0
        self.age.append(f.inference_done_ms - f.capture_ms)
        self.infer.append(obs.inference_ms)
        self._last_good = good
        self.last_ms = f.capture_ms
        return True

    @property
    def sample_coverage_pct(self) -> float:
        return 100.0 * self.good / self.samples if self.samples else 0.0

    @property
    def time_coverage_pct(self) -> float:
        return 100.0 * self.good_time_ms / self.total_time_ms if self.total_time_ms > 0 else 0.0

    @property
    def processed_fps(self) -> float:
        return 1000.0 * (self.samples - 1) / self.total_time_ms if self.total_time_ms > 0 and self.samples > 1 else 0.0

    def summary(self) -> dict[str, Any]:
        return {
            "ornek_sayisi": self.samples,
            "iyi_ornek": self.good,
            "ornek_kapsama_yuzde": round(self.sample_coverage_pct, 2),
            "zaman_agirlikli_kapsama_yuzde": round(self.time_coverage_pct, 2),
            "islenen_fps": round(self.processed_fps, 1),
            "yakalama_yasi_ms_p50": round(percentile(self.age, 0.5), 1),
            "yakalama_yasi_ms_p95": round(percentile(self.age, 0.95), 1),
            "cikarim_ms_p50": round(percentile(self.infer, 0.5), 1),
            "cikarim_ms_p95": round(percentile(self.infer, 0.95), 1),
            "bosluk_sayisi": self.gaps,
            "en_uzun_bosluk_ms": round(self.max_gap_ms, 1),
            "kimlik_belirsiz": self.identity_ambiguous,
            "yok_sayilan_tekrar": self.ignored_repeats,
            "sure_s": round(self.total_time_ms / 1000.0, 1),
        }


def decide(stats: StabilityStats, seconds: float, requested: float, interrupted: bool) -> tuple[str, str, str]:
    """(status, karar, note). Needs the full five minutes and >= 95% of samples."""
    rehearsal = requested < FULL_SECONDS
    ran_full = stats.total_time_ms / 1000.0 >= 0.98 * requested
    if interrupted or not ran_full or stats.samples < 2:
        note = "Koşu yarım kaldı."
        if rehearsal:
            note += " Ayrıca süre 300 sn'den kısa: prova, kabul sayılmaz."
        return rp.STATUS_YARIM, rp.KARAR_YAPILMADI, note
    if rehearsal:
        return (
            rp.STATUS_PROVA, rp.KARAR_YAPILMADI,
            f"prova, kabul sayılmaz ({requested:.0f} sn < 300 sn). Gösterge kapsama %{stats.sample_coverage_pct:.1f}.",
        )
    if stats.sample_coverage_pct >= GATE_PCT:
        return rp.STATUS_TAMAM, rp.KARAR_GECTI, f"Örnek kapsama %{stats.sample_coverage_pct:.1f} >= %95."
    return (
        rp.STATUS_TAMAM, rp.KARAR_KALDI,
        f"Örnek kapsama %{stats.sample_coverage_pct:.1f} < %95. Ölçülen hata durumlarına göre ayar, sonra farklı dizide yeniden test.",
    )


class StabilityRun:
    def __init__(
        self, source: FrameSource, console: Console, *, seconds: float = FULL_SECONDS,
        out_dir: Optional[Path] = None, software: Optional[dict[str, Any]] = None,
    ) -> None:
        self.source, self.console, self.seconds, self.out_dir = source, console, seconds, out_dir
        self.stats = StabilityStats()
        self.conditions: dict[str, str] = {}
        self.error: Optional[str] = None
        self._software = software
        self.stem = rp.timestamp_stem(TOOL)
        self.md_path: Optional[Path] = None
        self.json_path: Optional[Path] = None

    def build_report(self, interrupted: bool) -> rp.Report:
        st = self.stats
        status, karar, note = decide(st, st.total_time_ms / 1000.0, self.seconds, interrupted)
        if self.error:
            note = f"{note} Hata: {self.error}"
        sw = self._software if self._software is not None else rp.collect_software()
        self._software = sw
        s = st.summary()
        try:
            cam = self.source.camera_info()
        except Exception:
            cam = {}
        return rp.Report(
            tool=TOOL,
            title="İki el kararlılık kapısı" + (" - PROVA" if self.seconds < FULL_SECONDS else ""),
            stem=self.stem, status=status, environment=rp.collect_environment(cam), software=sw,
            conditions=self.conditions,
            experiment=[
                f"{self.seconds:.0f} sn boyunca iki el görünür; parmaklar bağımsız oynatılır.",
                "İyi örnek: iki el (biri sol biri sağ), her biri 21 nokta ve USABLE kalite.",
                "Tekrarlanan/uydurma örnek sayılmaz; boşluk > 250 ms.",
            ],
            result_lines=[
                f"Örnek: {s['iyi_ornek']}/{s['ornek_sayisi']} = %{s['ornek_kapsama_yuzde']} (eşik %95)",
                f"Zaman ağırlıklı kapsama: %{s['zaman_agirlikli_kapsama_yuzde']}",
                f"Kamera FPS: {cam.get('kamera_fps', '?')}; işlenen FPS: {s['islenen_fps']}",
                f"Yakalama yaşı p50/p95: {s['yakalama_yasi_ms_p50']}/{s['yakalama_yasi_ms_p95']} ms",
                f"Çıkarım p50/p95: {s['cikarim_ms_p50']}/{s['cikarim_ms_p95']} ms",
                f"Boşluk: {s['bosluk_sayisi']} (en uzun {s['en_uzun_bosluk_ms']} ms); kimlik belirsiz: {s['kimlik_belirsiz']}",
            ],
            raw={"requested_seconds": self.seconds, "stats": s},
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
            self.console.ask(
                f"İki elinizi de kameraya gösterin; {self.seconds:.0f} sn parmaklarınızı bağımsız oynatın. Hazırsanız Enter: ",
                pump_source(self.source),
            )
            start = self.source.now_ms()
            next_note = start + 30000.0
            while self.source.now_ms() - start < self.seconds * 1000.0:
                obs = self.source.next(0.2)
                if obs is not None and obs.frame.capture_ms >= start:
                    self.stats.add(obs)
                now = self.source.now_ms()
                if now >= next_note:
                    next_note += 30000.0
                    say(f"  {int((now - start) / 1000)} sn, kapsama %{self.stats.sample_coverage_pct:.1f}")
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
    p = argparse.ArgumentParser(prog="handcontrol.tools.stability_test", description="İki el kararlılık kapısı")
    p.add_argument("--seconds", type=float, default=FULL_SECONDS, help="süre (300 altı = prova)")
    p.add_argument("--swap-handedness", action="store_true")
    add_camera_args(p)
    args = p.parse_args(argv)
    run = StabilityRun(
        LiveSource(index=args.camera_index, backend=args.backend, swap_handedness=args.swap_handedness),
        RealConsole(), seconds=args.seconds, out_dir=Path(args.out_dir) if args.out_dir else None,
    )

    def go() -> int:
        run.execute()
        return 2 if run.error else 0

    run_main(go)
    return 0


if __name__ == "__main__":
    main()
