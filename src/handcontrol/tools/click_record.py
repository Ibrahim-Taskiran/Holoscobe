"""Local, input-free click measurements; analysis depends only on recorded features."""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from typing import Any, Sequence

from ..contracts import FingerName, FingerState, FrameFeatures, Handedness, Quality
from .common import Console, FrameSource, LiveSource, RealConsole, add_camera_args, percentile, pump_source
from .report import default_reports_dir

Row = dict[str, Any]
FINGERS = tuple(f.value for f in FingerName)
FIELDS = (
    "t_ms", "phase", "repeat", "segment", "status", "hand_id", "quality",
    *FINGERS, "palm_x_px", "palm_y_px", "palm_scale_px", "index_distance_px",
    "index_distance_pu", "middle_distance_px", "middle_distance_pu", "index_x_px",
    "index_y_px", "landmark5_x_px", "landmark5_y_px", "width", "height", "fps",
)
PHASES = {
    "still": "Sağ elinizle işaret pozu yapın ve sabit tutun (titreme).",
    "range": "Sağ işaret pozuyla elinizi rahat aralıkta sola-sağa, yukarı-aşağı gezdirin.",
    "left_pinch": "Başparmak + işaret pinch'ini BİR KEZ yapın ve bırakın.",
    "right_pinch": "Başparmak + orta parmak pinch'ini BİR KEZ yapın ve bırakın.",
    "drag": "Başparmak + işaret pinch'ini {hold:g} sn tutun, elinizi taşıyın ve bırakın.",
    "fist": "Sağ yumruk yapın, {hold:g} sn tutun ve elinizi açın.",
}


def frame_row(frame: FrameFeatures, phase: str, repeat: int, segment: str,
              fps: float | None = None) -> Row:
    """Keep frame metadata when the requested hand is absent; never synthesize coordinates."""
    row = dict.fromkeys(FIELDS)
    row.update(t_ms=frame.capture_ms, phase=phase, repeat=repeat, segment=segment,
               width=frame.width, height=frame.height, fps=fps, status="missing")
    hands = [h for h in frame.hands if h.handedness == Handedness.RIGHT]
    if frame.identity_ambiguous or len(hands) > 1:
        row["status"] = "ambiguous"
        return row
    if not hands:
        return row
    hand = hands[0]
    row.update(hand_id=hand.hand_id, quality=hand.quality.value, status="invalid")
    row.update({f.name.value: f.state.value for f in hand.fingers})
    if len(hand.landmarks) != 21 or frame.width <= 0 or frame.height <= 0:
        return row
    lm = hand.landmarks
    points = [(lm[i].x * frame.width, lm[i].y * frame.height) for i in (4, 8, 12, 5)]
    scale = hand.palm_scale_px
    if not all(math.isfinite(v) for point in (*points, hand.palm_center_px) for v in point):
        return row
    index_distance, middle_distance = math.dist(points[0], points[1]), math.dist(points[0], points[2])
    usable_scale = math.isfinite(scale) and scale > 0
    row.update(palm_x_px=hand.palm_center_px[0], palm_y_px=hand.palm_center_px[1],
               palm_scale_px=scale if math.isfinite(scale) else None,
               index_distance_px=index_distance, middle_distance_px=middle_distance,
               index_distance_pu=index_distance / scale if usable_scale else None,
               middle_distance_pu=middle_distance / scale if usable_scale else None,
               index_x_px=points[1][0], index_y_px=points[1][1],
               landmark5_x_px=points[3][0], landmark5_y_px=points[3][1],
               status="ok" if usable_scale and hand.quality == Quality.USABLE else "degraded")
    return row


def _good(rows: Sequence[Row]) -> list[Row]:
    return [r for r in rows if r["status"] == "ok"]


def finger_distribution(rows: Sequence[Row]) -> Row:
    return {
        "frames": len(rows),
        "index_bent_frames": sum(r["index"] == FingerState.BENT.value for r in rows),
        "all_bent_frames": sum(all(r[f] == FingerState.BENT.value for f in FINGERS) for r in rows),
        "states": {f: dict(Counter(r[f] for r in rows)) for f in FINGERS},
    }


def trial_summary(rows: Sequence[Row], distance: str) -> Row:
    """Estimate a single cycle from its own amplitude, never from production thresholds.

    Low/high diagnostic levels are 35%/65% of the baseline-to-minimum span.
    Times are frame-sampled (no precision beyond capture intervals is claimed).
    """
    valid = _good(rows)
    action = [r for r in valid if r["segment"] == "action"]
    baseline = [r for r in valid if r["segment"] == "baseline"]
    key = distance + "_distance_pu"
    result: Row = {
        "repeat": rows[0]["repeat"] if rows else None,
        "frames": len(rows), "usable_frames": len(valid), "complete_cycle": False,
        "minimum_pu": min((r[key] for r in action), default=None),
        "minimum_px": min((r[distance + "_distance_px"] for r in action), default=None),
        "open_typical_pu": median([r[key] for r in baseline]) if baseline else None,
        "closing_ms": None, "opening_ms": None, "pinch_ms": None,
        "index_drift_pu": None, "palm_drift_pu": None,
        "pinch_fingers": finger_distribution([]),
        "reason": "Açık poz veya hareket verisi yetersiz.",
    }
    if len(baseline) < 3 or len(action) < 3:
        return result
    opened = [r[key] for r in baseline]
    minimum = min(action, key=lambda r: r[key])
    span = median(opened) - minimum[key]
    noise = percentile(opened, .95) - percentile(opened, .05)
    resolution = median([1 / r["palm_scale_px"] for r in baseline])
    if span <= max(3 * noise, 2 * resolution):
        result["reason"] = "Kapanma hareketi açık poz gürültüsünden güvenle ayrılamadı."
        return result
    low, high = minimum[key] + .35 * span, minimum[key] + .65 * span
    armed, cycles = True, 0
    for row in valid:
        if row[key] >= high:
            armed = True
        elif row[key] <= low and armed:
            cycles += 1
            armed = False
    result["cycle_count"] = cycles
    if cycles != 1:
        result["reason"] = "Tek yönergede birden çok kapanma görüldü; tekrarı yeniden kaydedin."
        return result
    before = [r for r in valid if r["t_ms"] <= minimum["t_ms"]]
    # Begin at the last open sample before the minimum, excluding earlier accidental cycles.
    open_before = [r for r in before if r[key] >= high]
    after = [r for r in valid if r["t_ms"] >= minimum["t_ms"]]
    if not open_before:
        return result
    start = open_before[-1]
    descending = [r for r in before if r["t_ms"] >= start["t_ms"]]
    down_high = next((r for r in descending if r[key] <= high), None)
    down_low = next((r for r in descending if r[key] <= low), None)
    up_low = next((r for r in after if r[key] >= low), None)
    up_high = next((r for r in after if r[key] >= high), None)
    if any(r is None for r in (down_high, down_low, up_low, up_high)):
        result["reason"] = "Tam kapanma-açılma döngüsü görülmedi."
        return result
    cycle = [r for r in rows if start["t_ms"] <= r["t_ms"] <= up_high["t_ms"]]
    if (any(r["status"] != "ok" for r in cycle)
            or len({r["hand_id"] for r in cycle}) != 1
            or any(b["t_ms"] - a["t_ms"] > 250 for a, b in zip(cycle, cycle[1:]))):
        result["reason"] = "Döngüde takip boşluğu, kalite kaybı veya el kimliği değişimi var."
        return result
    pinched = [r for r in cycle if down_low["t_ms"] <= r["t_ms"] <= up_high["t_ms"]]
    origin = down_low
    scale = origin["palm_scale_px"]
    result.update(
        complete_cycle=True, reason=None,
        closing_ms=down_low["t_ms"] - down_high["t_ms"],
        opening_ms=up_high["t_ms"] - up_low["t_ms"],
        pinch_ms=up_high["t_ms"] - down_low["t_ms"],
        index_drift_pu=max(math.hypot(r["index_x_px"] - origin["index_x_px"],
                                    r["index_y_px"] - origin["index_y_px"]) / scale for r in pinched),
        palm_drift_pu=max(math.hypot(r["palm_x_px"] - origin["palm_x_px"],
                                   r["palm_y_px"] - origin["palm_y_px"]) / scale for r in pinched),
        pinch_fingers=finger_distribution(pinched), diagnostic_low_pu=low, diagnostic_high_pu=high,
        closed_upper_pu=percentile([r[key] for r in action if r[key] <= minimum[key] + .2 * span], .9),
        open_lower_pu=percentile(opened, .05), baseline_noise_pu=noise,
    )
    return result


def recommend_thresholds(trials: Sequence[Row]) -> Row:
    complete = [t for t in trials if t["complete_cycle"]]
    if len(complete) != len(trials) or not complete:
        return {"status": "yetersiz", "reason": "Her tekrarda kesintisiz tam döngü gerekli.",
                "close_range_pu": None, "open_range_pu": None}
    closed, opened = max(t["closed_upper_pu"] for t in complete), min(t["open_lower_pu"] for t in complete)
    gap = opened - closed
    if gap <= 3 * max(t["baseline_noise_pu"] for t in complete):
        return {"status": "ayrışmıyor", "reason": "Açık ve kapalı uzaklıklar güvenle ayrışmıyor.",
                "close_range_pu": None, "open_range_pu": None}
    return {"status": "aday", "close_range_pu": [closed + .1 * gap, closed + .4 * gap],
            "open_range_pu": [closed + .6 * gap, closed + .9 * gap],
            "closed_upper_pu": closed, "open_lower_pu": opened,
            "note": "Yalnız bu kayıttan aday aralık; farklı kayıtta doğrulayın, ayarlar otomatik değişmez."}


def spatial_summary(rows: Sequence[Row]) -> Row:
    valid = _good(rows)
    result: Row = {"frames": len(rows), "usable_frames": len(valid)}
    for prefix in ("index", "palm", "landmark5"):
        if not valid:
            result[prefix] = None
            continue
        xs, ys = [r[prefix + "_x_px"] for r in valid], [r[prefix + "_y_px"] for r in valid]
        cx, cy = mean(xs), mean(ys)
        radii = [math.hypot(x - cx, y - cy) for x, y in zip(xs, ys)]
        scale = median([r["palm_scale_px"] for r in valid])
        nx, ny = [r[prefix + "_x_px"] / r["width"] for r in valid], [r[prefix + "_y_px"] / r["height"] for r in valid]
        result[prefix] = {"rms_px": math.sqrt(mean([r * r for r in radii])),
                          "p95_px": percentile(radii, .95),
                          "rms_pu": math.sqrt(mean([(r / scale) ** 2 for r in radii])),
                          "p95_pu": percentile(radii, .95) / scale,
                          "bounds_px": [min(xs), min(ys), max(xs), max(ys)],
                          "width_frame_pct": (max(nx) - min(nx)) * 100,
                          "height_frame_pct": (max(ny) - min(ny)) * 100,
                          "area_frame_pct": (max(nx) - min(nx)) * (max(ny) - min(ny)) * 100}
    return result


def summarize(rows: Sequence[Row]) -> Row:
    groups: dict[tuple[str, int], list[Row]] = defaultdict(list)
    times: dict[tuple[str, int, str], list[float]] = defaultdict(list)
    for row in rows:
        groups[row["phase"], row["repeat"]].append(row)
        times[row["phase"], row["repeat"], row["segment"]].append(row["t_ms"])
    trials: Row = {}
    for phase, distance in (("left_pinch", "index"), ("right_pinch", "middle"), ("drag", "index")):
        items = [trial_summary(group, distance) for (name, _), group in sorted(groups.items()) if name == phase]
        trials[phase] = {"trials": items, "thresholds": recommend_thresholds(items)}
    intervals = sum(len(t) - 1 for t in times.values())
    elapsed = sum(t[-1] - t[0] for t in times.values() if len(t) > 1)
    valid = _good(rows)
    for phase, distance in (("left_pinch", "index"), ("right_pinch", "middle"), ("drag", "index")):
        thresholds = trials[phase]["thresholds"]
        negative_phases = ("fist", "left_pinch", "drag") if distance == "middle" else ("fist", "right_pinch")
        negatives = {name: [r[distance + "_distance_pu"] for r in valid
                            if r["phase"] == name and r["segment"] == "action"] for name in negative_phases}
        thresholds["negative_minima_pu"] = {name: min(values, default=None) for name, values in negatives.items()}
        limit = thresholds["close_range_pu"]
        if limit and any(min(values) <= limit[1] for values in negatives.values() if values):
            separated: bool | None = False
        elif limit and all(negatives.values()):
            separated = True
        else:
            separated = None
        thresholds["distance_only_separates_recorded_negatives"] = separated
    return {"frames": len(rows), "usable_frames": len(valid),
            "status_counts": dict(Counter(r["status"] for r in rows)),
            "processed_fps": intervals * 1000 / elapsed if elapsed else None,
            "pinches": trials,
            "still": spatial_summary([r for r in rows if r["phase"] == "still"]),
            "range": spatial_summary([r for r in rows if r["phase"] == "range"]),
            "fist": [{"repeat": repeat, "fingers": finger_distribution(_good(group)),
                       "index_min_pu": min((r["index_distance_pu"] for r in _good(group)), default=None),
                       "middle_min_pu": min((r["middle_distance_pu"] for r in _good(group)), default=None)}
                      for (phase, repeat), group in sorted(groups.items()) if phase == "fist"]}


@dataclass(frozen=True)
class RecordConfig:
    still_seconds: float = 10
    range_seconds: float = 10
    pinch_repeats: int = 10
    drag_repeats: int = 5
    fist_repeats: int = 5
    trial_seconds: float = 4
    open_seconds: float = 1
    hold_seconds: float = 1

    def validate(self) -> None:
        for value in (self.still_seconds, self.range_seconds, self.trial_seconds, self.open_seconds, self.hold_seconds):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("Süreler pozitif ve sonlu olmalı.")
        if min(self.pinch_repeats, self.drag_repeats, self.fist_repeats) < 1:
            raise ValueError("Tekrar sayıları en az 1 olmalı.")
        if self.trial_seconds <= self.hold_seconds:
            raise ValueError("Deneme süresi tutma süresinden uzun olmalı.")


class ClickRecordRun:
    def __init__(self, source: FrameSource, console: Console, *, config: RecordConfig = RecordConfig(),
                 out_dir: Path | None = None) -> None:
        config.validate()
        self.source, self.console, self.config = source, console, config
        self.out_dir = out_dir or default_reports_dir()
        self.rows: list[Row] = []
        self.last_t = -math.inf
        self.error: str | None = None
        self.stem = "hw_click_" + datetime.now().strftime("%Y%m%d-%H%M%S-%f")

    def _capture(self, writer: Any, stream: Any, phase: str, repeat: int, segment: str, seconds: float) -> None:
        start = self.source.now_ms()
        previous: float | None = None
        while self.source.now_ms() - start < seconds * 1000:
            obs = self.source.next(.1)
            if obs is None or obs.frame.capture_ms < start or obs.frame.capture_ms <= self.last_t:
                continue
            t = obs.frame.capture_ms
            fps = 1000 / (t - previous) if previous is not None else None
            row = frame_row(obs.frame, phase, repeat, segment, fps)
            writer.writerow(row)
            stream.flush()
            self.rows.append(row)
            self.last_t = previous = t

    def execute(self) -> Row:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        interrupted = True
        completed: list[str] = []
        with (self.out_dir / (self.stem + ".csv")).open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            try:
                self.console.say("Tıklama ölçümü: yalnız yerel sayısal kayıt; fare/klavye girdisi ve görüntü kaydı yok.")
                self.console.say("Yalnız SAĞ elinizi gösterin. Etiket tersse --swap-handedness ile yeniden çalıştırın.")
                self.source.open()
                cfg = self.config
                for phase, seconds in (("still", cfg.still_seconds), ("range", cfg.range_seconds)):
                    self.console.ask(PHASES[phase] + f" Süre {seconds:g} sn. Hazırsanız Enter: ", pump_source(self.source))
                    self._capture(writer, stream, phase, 1, "action", seconds)
                    completed.append(phase)
                for phase, count in (("left_pinch", cfg.pinch_repeats), ("right_pinch", cfg.pinch_repeats),
                                     ("drag", cfg.drag_repeats), ("fist", cfg.fist_repeats)):
                    text = PHASES[phase].format(hold=cfg.hold_seconds)
                    self.console.ask(text + " Hazırlanın; henüz hareket yapmayın. Enter: ", pump_source(self.source))
                    for repeat in range(1, count + 1):
                        self.console.say(f"{repeat}/{count}: Pinch'i bırakın, işaret pozunda açık ve sabit bekleyin.")
                        self._capture(writer, stream, phase, repeat, "baseline", cfg.open_seconds)
                        self.console.say("ŞİMDİ: " + text)
                        self._capture(writer, stream, phase, repeat, "action", cfg.trial_seconds)
                        self.console.say("Şimdi bırakın, elinizi açın ve sabit tutun.")
                        self._capture(writer, stream, phase, repeat, "recovery", cfg.open_seconds)
                        completed.append(f"{phase}:{repeat}")
                interrupted = False
            except KeyboardInterrupt:
                self.console.say("Durduruldu; kısmi kayıt korunuyor.")
            except Exception as exc:
                self.error = str(exc)
                self.console.say(f"HATA: {exc}")
            finally:
                try:
                    self.source.close()
                except Exception as exc:
                    self.error = self.error or str(exc)
                    interrupted = True
        summary = summarize(self.rows)
        summary.update(interrupted=interrupted, error=self.error, completed=completed,
                       config=vars(self.config), schema_version=1,
                       timing_note="35/65% genlik seviyeleri; kare zamanıyla tahmin, 250 ms üzeri boşluk geçersiz.")
        try:
            summary["camera"] = self.source.camera_info()
        except Exception:
            summary["camera"] = {}
        for phase, group in summary["pinches"].items():
            expected = self.config.drag_repeats if phase == "drag" else self.config.pinch_repeats
            if interrupted or len(group["trials"]) != expected:
                group["thresholds"] = {"status": "yetersiz", "reason": "Kayıt yarım kaldı.",
                                       "close_range_pu": None, "open_range_pu": None}
        (self.out_dir / (self.stem + ".json")).write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        lines = ["# Tıklama ölçümü", "", f"Durum: {'yarım' if interrupted else 'tamam'}; kullanılabilir kare: {summary['usable_frames']}/{summary['frames']}.",
                 f"İşlenen FPS: {summary['processed_fps']}; hata: {self.error or 'yok'}.", "",
                 "Mesafeler avuç birimidir. Süreler 35/65% genlik seviyelerinden kare zamanıyla tahmin edilir.",
                 "Takip boşluğu/kimlik değişimi olan döngülerden öneri üretilmez. Ayarlar değiştirilmez.", ""]
        for phase, group in summary["pinches"].items():
            lines += [f"## {PHASES[phase].format(hold=self.config.hold_seconds)}", "",
                      "| Tekrar | Min | Açık tipik | Kapanma/açılma/tutma ms | İşaret/avuç kayma | İşaret BENT / tümü BENT kare |", "|---|---|---|---|---|---|"]
            for t in group["trials"]:
                f = t["pinch_fingers"]
                lines.append(f"| {t['repeat']} | {t['minimum_pu']} | {t['open_typical_pu']} | {t['closing_ms']} / {t['opening_ms']} / {t['pinch_ms']} | {t['index_drift_pu']} / {t['palm_drift_pu']} | {f['index_bent_frames']} / {f['all_bent_frames']} |")
            thresholds = group["thresholds"]
            lines += ["", f"Eşik önerisi: {thresholds['status']}; kapama {thresholds['close_range_pu']}, açma {thresholds['open_range_pu']}.",
                      f"Mesafe tek başına yumruk/diğer pinch'i ayırıyor mu: {thresholds.get('distance_only_separates_recorded_negatives')}. False: parmak durumu kapısı gerekli; None: veri yetersiz.", ""]
        lines += ["## Titreme ve kullanılan alan", "",
                  "| Aşama / nokta | RMS px / avuç birimi | P95 px / avuç birimi | Kare genişliği/yüksekliği/alanı % |", "|---|---|---|---|"]
        for name, label in (("still", "Sabit"), ("range", "Gezdirme")):
            for point in ("index", "palm", "landmark5"):
                metric = summary[name].get(point)
                if metric:
                    lines.append(f"| {label} / {point} | {metric['rms_px']:.3f} / {metric['rms_pu']:.4f} | {metric['p95_px']:.3f} / {metric['p95_pu']:.4f} | {metric['width_frame_pct']:.2f} / {metric['height_frame_pct']:.2f} / {metric['area_frame_pct']:.2f} |")
        lines += ["", "## Yumruk ayrımı", "", "| Tekrar | İşaret BENT | Beş parmak BENT | Kullanılabilir kare |", "|---|---|---|---|"]
        for trial in summary["fist"]:
            fingers = trial["fingers"]
            lines.append(f"| {trial['repeat']} | {fingers['index_bent_frames']} | {fingers['all_bent_frames']} | {fingers['frames']} |")
        lines += ["", "Tam parmak dağılımları, sınırlar ve başarısız tekrar nedenleri JSON dosyasındadır.",
                  "Titreme, ortalama konuma göre radyal RMS/P95; avuç birimi için aşamanın medyan ölçeği kullanılır.",
                  "Eşik aralıkları tüm tamamlanan tekrarların kapalı üst/açık alt mesafelerinin arasına marj bırakılarak hesaplanır."]
        (self.out_dir / (self.stem + ".md")).write_text("\n".join(lines), encoding="utf-8")
        self.console.say(f"CSV / JSON / Markdown: {self.out_dir / self.stem}")
        return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gerçek el verisiyle tıklama ölçümü (girdi göndermez).")
    add_camera_args(parser)
    parser.add_argument("--swap-handedness", action="store_true", help="Sağ/sol etiketlerini değiştir")
    for name, default in vars(RecordConfig()).items():
        parser.add_argument("--" + name.replace("_", "-"), type=int if name.endswith("repeats") else float, default=default)
    args = parser.parse_args(argv)
    config = RecordConfig(**{name: getattr(args, name) for name in vars(RecordConfig())})
    try:
        config.validate()
    except ValueError as exc:
        parser.error(str(exc))
    run = ClickRecordRun(LiveSource(index=args.camera_index, backend=args.backend, swap_handedness=args.swap_handedness),
                         RealConsole(), config=config, out_dir=Path(args.out_dir) if args.out_dir else None)
    result = run.execute()
    return 2 if result["interrupted"] or not result["usable_frames"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
