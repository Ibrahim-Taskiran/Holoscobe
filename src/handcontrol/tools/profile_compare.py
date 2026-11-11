"""Compare camera profiles (640x480 vs 1280x720) with one fixed pose checklist.

Run: python -m handcontrol.tools.profile_compare [--seconds-per-pose 5]
Measurement only: there is no acceptance gate here, the report just puts the numbers side by side.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from ..contracts import FrameFeatures, Quality
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

TOOL = "profile_compare"
PROFILES = ((640, 480), (1280, 720))
# (instruction, expected number of hands)
CHECKLIST = (
    ("SAĞ el açık avuç, kameraya dönük", 1),
    ("SOL el açık avuç, kameraya dönük", 1),
    ("İKİ el açık avuç", 2),
    ("İKİ el yumruk", 2),
    ("SAĞ el baş parmak + işaret parmağı tutuşu (pinch)", 1),
)


def pose_usable(frame: FrameFeatures, expected: int) -> bool:
    return len(frame.hands) == expected and all(
        h.quality == Quality.USABLE and len(h.landmarks) == 21 for h in frame.hands
    )


@dataclass
class ProfileStats:
    width: int
    height: int
    samples: int = 0
    usable: int = 0
    first_ms: Optional[float] = None
    last_ms: Optional[float] = None
    last_capture: float = -1.0
    infer: list[float] = field(default_factory=list)
    frame_wh: Optional[tuple[int, int]] = None
    per_pose: list[tuple[int, int]] = field(default_factory=list)       # (usable, samples) per pose

    def add(self, obs: Observation, expected: int) -> bool:
        f = obs.frame
        if f.capture_ms <= self.last_capture:
            return False                                                 # never count repeats
        self.last_capture = f.capture_ms
        self.samples += 1
        self.usable += 1 if pose_usable(f, expected) else 0
        self.infer.append(obs.inference_ms)
        self.frame_wh = (f.width, f.height)
        if self.first_ms is None:
            self.first_ms = f.capture_ms
        self.last_ms = f.capture_ms
        return True

    @property
    def coverage_pct(self) -> float:
        return 100.0 * self.usable / self.samples if self.samples else 0.0

    @property
    def processed_fps(self) -> float:
        if self.samples < 2 or self.first_ms is None or self.last_ms is None or self.last_ms <= self.first_ms:
            return 0.0
        return 1000.0 * (self.samples - 1) / (self.last_ms - self.first_ms)

    def summary(self) -> dict[str, Any]:
        return {
            "istenen": f"{self.width}x{self.height}",
            "gercek_cozunurluk": f"{self.frame_wh[0]}x{self.frame_wh[1]}" if self.frame_wh else "-",
            "ornek": self.samples,
            "islenen_fps": round(self.processed_fps, 1),
            "cikarim_ms_p50": round(percentile(self.infer, 0.5), 1),
            "cikarim_ms_p95": round(percentile(self.infer, 0.95), 1),
            "kullanilabilir_kapsama_yuzde": round(self.coverage_pct, 1),
        }


def comparison_table(rows: list[dict[str, Any]]) -> str:
    cols = [
        ("İstenen", "istenen"), ("Gerçek çözünürlük", "gercek_cozunurluk"), ("Kamera FPS", "kamera_fps"),
        ("İşlenen FPS", "islenen_fps"), ("Çıkarım p50 ms", "cikarim_ms_p50"),
        ("Çıkarım p95 ms", "cikarim_ms_p95"), ("Kullanılabilir kapsama %", "kullanilabilir_kapsama_yuzde"),
    ]
    head = "| " + " | ".join(c[0] for c in cols) + " |"
    sep = "|" + "---|" * len(cols)
    body = ["| " + " | ".join(str(r.get(c[1], "-")) for c in cols) + " |" for r in rows]
    return "\n".join(["## Yan yana karşılaştırma", "", head, sep, *body])


class ProfileRun:
    def __init__(
        self, source_factory: Callable[[int, int], FrameSource], console: Console, *,
        seconds_per_pose: float = 5.0, profiles: tuple[tuple[int, int], ...] = PROFILES,
        out_dir: Optional[Path] = None, software: Optional[dict[str, Any]] = None,
    ) -> None:
        self.factory, self.console, self.seconds = source_factory, console, seconds_per_pose
        self.profiles, self.out_dir = profiles, out_dir
        self.rows: list[dict[str, Any]] = []
        self.pose_rows: list[dict[str, Any]] = []
        self.conditions: dict[str, str] = {}
        self.error: Optional[str] = None
        self._software = software
        self._cam_info: dict[str, Any] = {}
        self.stem = rp.timestamp_stem(TOOL)
        self.md_path: Optional[Path] = None
        self.json_path: Optional[Path] = None

    def _run_profile(self, w: int, h: int) -> None:
        say = self.console.say
        say(f"\n=== Profil {w}x{h} ===")
        source = self.factory(w, h)
        stats = ProfileStats(w, h)
        try:
            source.open()
            for idx, (text, expected) in enumerate(CHECKLIST, 1):
                self.console.ask(f"  [{idx}/{len(CHECKLIST)}] {text} - hazırsanız Enter: ", pump_source(source))
                start = source.now_ms()
                before = (stats.usable, stats.samples)
                while source.now_ms() - start < self.seconds * 1000.0:
                    obs = source.next(0.1)
                    if obs is not None and obs.frame.capture_ms >= start:
                        stats.add(obs, expected)
                stats.per_pose.append((stats.usable - before[0], stats.samples - before[1]))
            info = source.camera_info()
        finally:
            try:
                source.close()
            except Exception:
                pass
        row = stats.summary()
        row["kamera_fps"] = info.get("kamera_fps", "-")
        self._cam_info[f"{w}x{h}"] = info
        self.rows.append(row)
        for (text, expected), (u, n) in zip(CHECKLIST, stats.per_pose):
            self.pose_rows.append({"profil": f"{w}x{h}", "poz": text, "kullanilabilir": u, "ornek": n})

    def build_report(self, complete: bool) -> rp.Report:
        sw = self._software if self._software is not None else rp.collect_software()
        self._software = sw
        status = rp.STATUS_TAMAM if complete else rp.STATUS_YARIM
        karar = rp.KARAR_GECTI if complete else rp.KARAR_YAPILMADI
        note = (
            "Ölçüm tamamlandı (bilgi amaçlı; kabul kapısı yok)."
            if complete else "Ölçüm yarım kaldı."
        )
        if self.error:
            note += f" Hata: {self.error}"
        pose_md = ["", "## Poz bazında kullanılabilir örnek", "", "| Profil | Poz | Kullanılabilir/Örnek |", "|---|---|---|"]
        pose_md += [f"| {r['profil']} | {r['poz']} | {r['kullanilabilir']}/{r['ornek']} |" for r in self.pose_rows]
        return rp.Report(
            tool=TOOL, title="Kamera profili karşılaştırması", stem=self.stem, status=status,
            environment=rp.collect_environment({"profiller": self._cam_info}), software=sw,
            conditions=self.conditions,
            experiment=[
                f"Sabit poz listesi ({len(CHECKLIST)} poz) x {self.seconds:.0f} sn, her profilde aynı sırayla.",
                "Profiller: " + ", ".join(f"{w}x{h}" for w, h in self.profiles),
                "Kullanılabilir kapsama: beklenen sayıda el, hepsi USABLE ve 21 nokta olan örnek oranı.",
            ],
            result_lines=[
                f"{r['istenen']} -> gerçek {r['gercek_cozunurluk']}; kamera {r['kamera_fps']} FPS, işlenen {r['islenen_fps']} FPS, "
                f"çıkarım {r['cikarim_ms_p50']}/{r['cikarim_ms_p95']} ms, kapsama %{r['kullanilabilir_kapsama_yuzde']}"
                for r in self.rows
            ] or ["veri yok"],
            raw={"profiller": self.rows, "pozlar": self.pose_rows, "checklist": [c[0] for c in CHECKLIST]},
            details_md=comparison_table(self.rows) + "\n" + "\n".join(pose_md),
            decision=karar, decision_note=note,
        )

    def _save(self, complete: bool) -> rp.Report:
        r = self.build_report(complete)
        self.md_path, self.json_path = rp.save_report(r, self.out_dir)
        return r

    def execute(self) -> rp.Report:
        say = self.console.say
        complete = False
        try:
            self.conditions = ask_conditions(self.console)
            for w, h in self.profiles:
                self._run_profile(w, h)
                self._save(False)
            complete = True
        except KeyboardInterrupt:
            say("\nDurduruldu (Ctrl+C). Kısmi sonuç kaydediliyor...")
        except ToolError as exc:
            self.error = str(exc)
            say(f"HATA: {exc}")
        report = self._save(complete)
        say(f"Karar: {report.decision} ({report.status})")
        say(f"Rapor: {self.md_path}")
        return report


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="handcontrol.tools.profile_compare", description="Kamera profili karşılaştırması")
    p.add_argument("--seconds-per-pose", type=float, default=5.0)
    p.add_argument("--swap-handedness", action="store_true")
    add_camera_args(p)
    args = p.parse_args(argv)

    def factory(w: int, h: int) -> FrameSource:
        return LiveSource(w, h, index=args.camera_index, backend=args.backend, swap_handedness=args.swap_handedness)

    run = ProfileRun(factory, RealConsole(), seconds_per_pose=args.seconds_per_pose,
                     out_dir=Path(args.out_dir) if args.out_dir else None)

    def go() -> int:
        run.execute()
        return 2 if run.error else 0

    run_main(go)
    return 0


if __name__ == "__main__":
    main()
