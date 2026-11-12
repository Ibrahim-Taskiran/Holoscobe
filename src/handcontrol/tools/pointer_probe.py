"""Opt-in physical-desktop pointer measurements with unconditional restore attempts."""
from __future__ import annotations

import argparse
import ctypes as C
import math
import time
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from ..contracts import Monitor
from .common import Console, RealConsole
from .report import default_reports_dir


class PointerInput(Protocol):
    def move_pointer(self, x: int, y: int) -> bool: ...


def monitor_targets(monitor: Monitor) -> list[tuple[str, int, int]]:
    bounds = monitor.bounds
    if bounds.right <= bounds.left or bounds.bottom <= bounds.top:
        raise ValueError("Monitör sınırları geçersiz.")
    inset_x = min(20, (bounds.right - bounds.left - 1) // 2)
    inset_y = min(20, (bounds.bottom - bounds.top - 1) // 2)
    left, right = bounds.left + inset_x, bounds.right - 1 - inset_x
    top, bottom = bounds.top + inset_y, bounds.bottom - 1 - inset_y
    return [("merkez", (bounds.left + bounds.right - 1) // 2, (bounds.top + bounds.bottom - 1) // 2),
            ("sol üst", left, top), ("sağ üst", right, top),
            ("sağ alt", right, bottom), ("sol alt", left, bottom)]


def read_cursor(*, api: Any = None) -> tuple[int, int]:
    from ..windows._win32 import POINT, user32
    point = POINT()
    if not (api if api is not None else user32()).GetCursorPos(C.byref(point)):
        raise OSError("Windows imleç konumu okunamadı.")
    return point.x, point.y


def measure_pointer(monitors: Sequence[Monitor], adapter: PointerInput,
                    get_cursor: Callable[[], tuple[int, int]], *,
                    sleep: Callable[[float], None] = time.sleep, settle_seconds: float = .25,
                    tolerance_px: float = 2, console: Console | None = None) -> dict[str, Any]:
    """The injectable measurement core never constructs real Windows adapters."""
    if not math.isfinite(settle_seconds) or settle_seconds < 0 or not math.isfinite(tolerance_px) or tolerance_px < 0:
        raise ValueError("Bekleme ve tolerans sonlu, negatif olmayan değerler olmalı.")
    result: dict[str, Any] = {"monitors": [], "restored": False, "restore_error": None,
                              "restore_deviation_px": None, "interrupted": False, "error": None,
                              "tolerance_px": tolerance_px}
    # Validate before any movement; an invalid monitor must not leave a partial run.
    plans = [monitor_targets(monitor) for monitor in monitors]
    origin: tuple[int, int] | None = None
    try:
        origin = get_cursor()
        result["origin"] = origin
        for index, (monitor, targets) in enumerate(zip(monitors, plans), 1):
            record: dict[str, Any] = {"index": index, "bounds": vars(monitor.bounds),
                "work_area": vars(monitor.work_area), "dpi_scale": monitor.dpi_scale,
                "primary": monitor.is_primary, "steps": [], "reached": False,
                "max_deviation_px": None}
            result["monitors"].append(record)
            for name, x, y in targets:
                step: dict[str, Any] = {"name": name, "target": (x, y), "actual": None,
                    "dx": None, "dy": None, "deviation_px": None, "accepted": False, "error": None}
                record["steps"].append(step)
                try:
                    step["accepted"] = bool(adapter.move_pointer(x, y))
                    sleep(settle_seconds)
                    actual = get_cursor()
                    dx, dy = actual[0] - x, actual[1] - y
                    step.update(actual=actual, dx=dx, dy=dy, deviation_px=math.hypot(dx, dy))
                except Exception as exc:
                    step["error"] = str(exc)
                if console:
                    console.say(f"Monitör {index}, {name}: hedef {(x, y)}, okunan {step['actual']}, fark ({step['dx']}, {step['dy']}) px; kabul {step['accepted']}.")
            deviations = [s["deviation_px"] for s in record["steps"] if s["deviation_px"] is not None]
            record["max_deviation_px"] = max(deviations, default=None)
            record["reached"] = all(s["accepted"] and s["error"] is None
                                    and s["deviation_px"] is not None and s["deviation_px"] <= tolerance_px
                                    for s in record["steps"])
    except KeyboardInterrupt:
        result["interrupted"] = True
    except Exception as exc:
        result["error"] = str(exc)
    finally:
        if origin is not None:
            try:
                accepted = adapter.move_pointer(*origin)
                sleep(settle_seconds)
                actual = get_cursor()
                deviation = math.dist(actual, origin)
                result.update(restored=bool(accepted and deviation <= tolerance_px),
                              restore_actual=actual, restore_deviation_px=deviation)
                if not result["restored"]:
                    result["restore_error"] = "Başlangıç konumuna dönüş doğrulanamadı."
            except (Exception, KeyboardInterrupt) as exc:
                result["restore_error"] = str(exc) or "Dönüş kesildi."
    for record in result["monitors"]:
        deviations = [s["deviation_px"] for s in record["steps"] if s["deviation_px"] is not None]
        record["max_deviation_px"] = max(deviations, default=None)
        record["reached"] = len(record["steps"]) == 5 and all(
            s["accepted"] and s["error"] is None and s["deviation_px"] is not None
            and s["deviation_px"] <= tolerance_px for s in record["steps"])
    return result


def write_report(result: dict[str, Any], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / ("hw_pointer_probe_" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".md")
    lines = ["# Windows imleç/monitör sondası", "",
             f"Tolerans: {result['tolerance_px']} px (Öklid uzaklığı). Tıklama gönderilmedi.",
             f"Kesildi: {result['interrupted']}; hata: {result['error'] or 'yok'}.",
             f"Başlangıca dönüş: {'doğrulandı' if result['restored'] else 'doğrulanamadı'}; fark {result['restore_deviation_px']} px; hata {result['restore_error'] or 'yok'}.", ""]
    for monitor in result["monitors"]:
        reached = "ulaşıldı" if monitor["reached"] else "ulaşılamadı"
        lines += [f"## Monitör {monitor['index']}: {reached}", "",
                  f"Sınırlar: {monitor['bounds']}; çalışma alanı: {monitor['work_area']}; DPI ölçeği: {monitor['dpi_scale']}; birincil: {monitor['primary']}.",
                  f"En büyük ölçülen sapma: {monitor['max_deviation_px']} px.", "",
                  "| Nokta | Hedef | Okunan | dx / dy px | Sapma px | Kabul | Hata |", "|---|---|---|---|---|---|---|"]
        for s in monitor["steps"]:
            error = (s["error"] or "yok").replace("|", "/").replace("\n", " ")
            lines.append(f"| {s['name']} | {s['target']} | {s['actual']} | {s['dx']} / {s['dy']} | {s['deviation_px']} | {s['accepted']} | {error} |")
        lines.append("")
    lines += ["Bu sonda yalnız Windows fiziksel hareket katmanını ölçer; el-hareket eşlemesini ölçmez.",
              "Kullanıcının/proseslerin eşzamanlı imleç hareketi sonucu etkileyebilir."]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def run_probe(monitors: Sequence[Monitor], adapter: PointerInput,
              get_cursor: Callable[[], tuple[int, int]], console: Console, *,
              out_dir: Path, sleep: Callable[[float], None] = time.sleep,
              delay_seconds: float = 3, settle_seconds: float = .25,
              tolerance_px: float = 2) -> dict[str, Any] | None:
    if not math.isfinite(delay_seconds) or delay_seconds < 0:
        raise ValueError("Geri sayım süresi sonlu ve negatif olmayan değer olmalı.")
    if not monitors:
        raise ValueError("Etkin monitör bulunamadı.")
    for i, monitor in enumerate(monitors, 1):
        console.say(f"Monitör {i}: sınırlar {monitor.bounds}, çalışma alanı {monitor.work_area}, DPI {monitor.dpi_scale:g}, birincil {monitor.is_primary}.")
    console.say("Ölçümden önce Holoscobe canlı kontrolünü duraklatın; başka bir süreç imleci taşımamalı.")
    answer = console.ask("İmleç her monitörde 5 noktaya taşınacak, tıklama yapılmayacak. Hazırsanız Enter; iptal için q: ")
    if answer.strip():
        console.say("İptal edildi; imleç taşınmadı.")
        return None
    console.say(f"{delay_seconds:g} sn sonra başlıyor; fareye dokunmayın. Ctrl+C ile durdurabilirsiniz.")
    sleep(delay_seconds)
    result = measure_pointer(monitors, adapter, get_cursor, sleep=sleep,
                             settle_seconds=settle_seconds, tolerance_px=tolerance_px, console=console)
    path = write_report(result, out_dir)
    for monitor in result["monitors"]:
        console.say(f"Monitör {monitor['index']}: {'ulaşıldı' if monitor['reached'] else 'ulaşılamadı'}; en büyük sapma {monitor['max_deviation_px']} px.")
    console.say(f"Başlangıca dönüş: {'doğrulandı' if result['restored'] else 'doğrulanamadı'}. Rapor: {path}")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Windows monitör erişimi; yalnız imleç hareketi, tıklama yok.")
    parser.add_argument("--out-dir", type=Path, default=None, help="Rapor klasörü")
    parser.add_argument("--delay-seconds", type=float, default=3, help="Enter sonrası geri sayım")
    parser.add_argument("--settle-seconds", type=float, default=.25, help="Hareket sonrası okuma beklemesi")
    parser.add_argument("--tolerance-px", type=float, default=2, help="İzin verilen ölçüm sapması")
    args = parser.parse_args(argv)
    for name in ("delay_seconds", "settle_seconds", "tolerance_px"):
        if not math.isfinite(getattr(args, name)) or getattr(args, name) < 0:
            parser.error("Süre ve tolerans sonlu, negatif olmayan değerler olmalı.")
    try:
        from ..windows.dpi import enable_per_monitor_v2
        from ..windows.displays import WindowsDisplayProvider
        from ..windows.input import WindowsInput
        if not enable_per_monitor_v2():
            raise OSError("Fiziksel piksel ölçümü için DPI awareness v2 ayarlanamadı.")
        displays = WindowsDisplayProvider()
        result = run_probe(displays.monitors(), WindowsInput(displays), read_cursor, RealConsole(),
                           out_dir=args.out_dir or default_reports_dir(), delay_seconds=args.delay_seconds,
                           settle_seconds=args.settle_seconds, tolerance_px=args.tolerance_px)
        return 0 if result is None or (result["restored"] and not result["interrupted"] and not result["error"]
                  and all(m["reached"] for m in result["monitors"])) else 2
    except KeyboardInterrupt:
        print("İptal edildi.")
        return 2
    except Exception as exc:
        print(f"HATA: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
