"""Offline Turkish Markdown report from a telemetry session CSV (see handcontrol.telemetry)."""
from __future__ import annotations

import argparse
import csv
import math
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Sequence

from .report import default_reports_dir

NO_DATA = "veri yok"
PINCH_ON, PINCH_OFF = 0.33, 0.48
GAP_BUCKETS = (("< 100 ms", 0, 100), ("100-200 ms", 100, 200), ("200-500 ms", 200, 500), ("> 500 ms", 500, math.inf))
FLICKER_MAX_MS = 500.0
STALL_MS = 200.0
STALL_MOVE_SCALE = 0.25
FINGERS = ("thumb", "index", "middle", "ring", "little")
CLICK_KINDS = (("left_click", "sol tık"), ("right_click", "sağ tık"), ("double_click", "çift tık"), ("left_down", "sürükleme başlangıcı"))

Row = dict[str, str]


def load_rows(path: Path) -> tuple[list[str], list[Row]]:
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        header = list(reader.fieldnames or [])
        return header, [r for r in reader]


def _f(row: Row, key: str) -> Optional[float]:
    try:
        v = float(row.get(key, ""))
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _flag(row: Row, key: str) -> bool:
    return (row.get(key) or "").strip() in ("1", "True", "true")


def _pct(a: float, b: float) -> str:
    return f"%{100.0 * a / b:.1f}" if b else NO_DATA


def _has(header: Sequence[str], *cols: str) -> bool:
    return all(c in header for c in cols)


def _tracking(header: list[str], rows: list[Row]) -> list[str]:
    out = ["## Takip", ""]
    if not _has(header, "t_ms", "dom_quality"):
        return out + [f"- Kullanılabilir oran: {NO_DATA}", ""]
    usable = [(_f(r, "t_ms"), (r.get("dom_quality") == "usable")) for r in rows]
    ok = sum(1 for _, u in usable if u)
    out.append(f"- Kullanılabilir kare oranı: {_pct(ok, len(rows))} ({ok}/{len(rows)})")
    hist = Counter()
    last_t: Optional[float] = None
    dropout = False
    for t, u in usable:
        if t is None:
            continue
        if u:
            if last_t is not None and dropout:
                gap = t - last_t
                for name, lo, hi in GAP_BUCKETS:
                    if lo <= gap < hi:
                        hist[name] += 1
                        break
            last_t, dropout = t, False
        else:
            dropout = True
    out.append("- Kullanılabilir kareler arası kopukluk dağılımı (yalnız kopma olan aralıklar):")
    for name, _, _ in GAP_BUCKETS:
        out.append(f"  - {name}: {hist[name]}")
    if _has(header, "tracking_ok"):
        bad = sum(1 for r in rows if not _flag(r, "tracking_ok"))
        out.append(f"- Denetleyicinin takibi kötü saydığı kare oranı: {_pct(bad, len(rows))}")
    else:
        out.append(f"- Denetleyici takip durumu: {NO_DATA}")
    out.append("")
    return out


def _pointer(header: list[str], rows: list[Row]) -> list[str]:
    out = ["## İşaretçi", ""]
    if not _has(header, "pointer_engaged", "t_ms"):
        return out + [f"- Bağlı kalma oranı: {NO_DATA}", ""]
    eng = [_flag(r, "pointer_engaged") for r in rows]
    out.append(f"- İşaretçi bağlı (engaged) kare oranı: {_pct(sum(eng), len(rows))}")
    # Pose flicker: engaged -> not engaged -> engaged within 500 ms while the hand stayed present.
    flickers = 0
    i, n = 0, len(rows)
    while i < n:
        if eng[i] and i + 1 < n and not eng[i + 1]:
            j = i + 1
            while j < n and not eng[j]:
                j += 1
            ti, tj = _f(rows[i], "t_ms"), _f(rows[j], "t_ms") if j < n else None
            present = all(_flag(rows[k], "dom_present") for k in range(i, j)) if "dom_present" in header else False
            if tj is not None and ti is not None and tj - ti < FLICKER_MAX_MS and present:
                flickers += 1
            i = j
        else:
            i += 1
    out.append(f"- 500 ms'den kısa bağlantı kopması (el yerinde, poz titremesi): {flickers if 'dom_present' in header else NO_DATA}")
    if _has(header, "pointer_x", "pointer_y", "palm_x_px", "palm_y_px", "palm_scale_px"):
        stalls, last_change_t, anchor, counted = 0, None, None, False
        prev_ptr = None
        for r in rows:
            t, px, py = _f(r, "t_ms"), _f(r, "pointer_x"), _f(r, "pointer_y")
            if not _flag(r, "pointer_engaged") or t is None or px is None or py is None:
                last_change_t, anchor, prev_ptr, counted = None, None, None, False
                continue
            ptr = (px, py)
            palm = (_f(r, "palm_x_px"), _f(r, "palm_y_px"))
            if ptr != prev_ptr or anchor is None:
                prev_ptr, last_change_t, anchor, counted = ptr, t, palm, False
                continue
            scale = _f(r, "palm_scale_px")
            if (not counted and None not in palm and None not in anchor and scale
                    and t - last_change_t >= STALL_MS
                    and math.dist(palm, anchor) >= STALL_MOVE_SCALE * scale):
                stalls += 1
                counted = True
        out.append(f"- İmleç durması (bağlı iken el >= {STALL_MOVE_SCALE} avuç boyu oynadı, imleç >= {STALL_MS:.0f} ms kıpırdamadı): {stalls}")
    else:
        out.append(f"- İmleç durması: {NO_DATA}")
    out.append("")
    return out


def _clicks(header: list[str], rows: list[Row]) -> list[str]:
    out = ["## Tıklamalar", ""]
    if _has(header, "pinch_pu"):
        attempts, armed = 0, True
        for r in rows:
            d = _f(r, "pinch_pu")
            if d is None:
                continue
            if armed and d < PINCH_ON:
                attempts += 1
                armed = False
            elif not armed and d > PINCH_OFF:
                armed = True
        out.append(f"- Pinch denemesi (mesafe {PINCH_ON} altına inip {PINCH_OFF} üstüne çıkma): {attempts}")
    else:
        out.append(f"- Pinch denemesi: {NO_DATA}")
    if _has(header, "actions"):
        counts: Counter[str] = Counter()
        for r in rows:
            for k in (r.get("actions") or "").split("|"):
                if k:
                    counts[k] += 1
        out.append("- Gönderilen eylemler: " + ", ".join(f"{label} {counts[k]}" for k, label in CLICK_KINDS))
    else:
        out.append(f"- Gönderilen eylemler: {NO_DATA}")
    if _has(header, "last_cancel"):
        cancels: Counter[str] = Counter()
        prev = ""
        for r in rows:
            cur = (r.get("last_cancel") or "").strip()
            if cur and cur != prev:
                cancels[cur] += 1
            prev = cur
        out.append("- İptaller (son iptal nedeni değişimlerine göre):")
        out.extend([f"  - {text}: {c}" for text, c in cancels.most_common()] or ["  - yok"])
    else:
        out.append(f"- İptaller: {NO_DATA}")
    out.append("")
    return out


def _fingers(header: list[str], rows: list[Row]) -> list[str]:
    out = ["## Parmak durumu (baskın el, UNKNOWN oranı)", ""]
    present = [r for r in rows if _flag(r, "dom_present")] if "dom_present" in header else None
    for name in FINGERS:
        col = f"finger_{name}"
        if present is None or col not in header:
            out.append(f"- {name}: {NO_DATA}")
            continue
        unk = sum(1 for r in present if (r.get(col) or "").lower() == "unknown")
        out.append(f"- {name}: {_pct(unk, len(present))} ({unk}/{len(present)})")
    out.append("")
    return out


def _notices(header: list[str], rows: list[Row], top: int = 8) -> list[str]:
    out = ["## En sık uyarılar", ""]
    if "notice" not in header:
        return out + [NO_DATA, ""]
    counts: Counter[str] = Counter()
    prev = ""
    for r in rows:
        cur = (r.get("notice") or "").strip()
        if cur and cur != prev:
            counts[cur] += 1
        prev = cur
    out.extend([f"- {text}: {c}" for text, c in counts.most_common(top)] or ["- yok"])
    out.append("")
    return out


def render_report(header: list[str], rows: list[Row], source: str = "") -> str:
    lines = ["# Oturum telemetri raporu", ""]
    if source:
        lines += [f"Kaynak: `{source}`", ""]
    lines += ["## Genel", ""]
    times = [t for t in (_f(r, "t_ms") for r in rows) if t is not None] if "t_ms" in header else []
    if len(times) >= 2 and times[-1] > times[0]:
        dur = (times[-1] - times[0]) / 1000.0
        lines.append(f"- Süre: {dur:.1f} sn")
        lines.append(f"- Kare sayısı: {len(rows)}, ortalama fps: {(len(times) - 1) / dur:.1f}")
    else:
        lines.append(f"- Süre / fps: {NO_DATA}")
    if "age_ms" in header:
        ages = sorted(a for a in (_f(r, "age_ms") for r in rows) if a is not None)
        lines.append(f"- Yakalama-işleme gecikmesi (medyan / p95): "
                     + (f"{ages[len(ages) // 2]:.1f} / {ages[min(len(ages) - 1, int(len(ages) * 0.95))]:.1f} ms" if ages else NO_DATA))
    lines.append("")
    if not rows:
        return "\n".join(lines + ["Dosyada kare yok."]) + "\n"
    for section in (_tracking, _pointer, _clicks, _fingers, _notices):
        lines += section(header, rows)
    return "\n".join(lines).rstrip() + "\n"


def build_report(csv_path: Path, out_path: Optional[Path] = None) -> Path:
    header, rows = load_rows(csv_path)
    if out_path is None:
        out_path = default_reports_dir() / f"hw_session_{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_report(header, rows, csv_path.name), encoding="utf-8")
    return out_path


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Oturum telemetri CSV dosyasından Türkçe rapor üretir.")
    parser.add_argument("csv", type=Path, help="session_*.csv dosyası")
    parser.add_argument("--out", type=Path, default=None, help="çıktı .md yolu (varsayılan Docs/reports/hw_session_<damga>.md)")
    args = parser.parse_args(argv)
    if not args.csv.is_file():
        print(f"Dosya bulunamadı: {args.csv}")
        return 1
    print(f"Rapor yazıldı: {build_report(args.csv, args.out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
