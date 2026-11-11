"""Shared report writer: JSON raw results + Turkish Markdown report (roadmap template rows).

No camera frames and no raw landmark traces are ever stored: only aggregate counts and
per-trial outcomes. Files: Docs/reports/hw_<tool>_<YYYYMMDD-HHMMSS>.(md|json).
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
from dataclasses import dataclass, field
from datetime import datetime
from importlib import metadata
from pathlib import Path
from typing import Any, Optional

KARAR_GECTI = "geçti"
KARAR_KALDI = "kaldı"
KARAR_YAPILMADI = "yapılmadı"
KARARLAR = (KARAR_GECTI, KARAR_KALDI, KARAR_YAPILMADI)

STATUS_TAMAM = "tamam"
STATUS_YARIM = "yarım"
STATUS_PROVA = "prova, kabul sayılmaz"

PACKAGES = ("mediapipe", "opencv-contrib-python", "numpy")


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_reports_dir() -> Path:
    return project_root() / "Docs" / "reports"


def timestamp_stem(tool: str, when: Optional[datetime] = None) -> str:
    when = when or datetime.now()
    return f"hw_{tool}_{when.strftime('%Y%m%d-%H%M%S')}"


# ---------------------------------------------------------------- environment


def _cpu_name() -> str:
    try:
        import winreg  # type: ignore[import-not-found]

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
        ) as key:
            return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
    except Exception:
        return platform.processor() or "bilinmiyor"


def package_versions() -> dict[str, str]:
    out: dict[str, str] = {}
    for name in PACKAGES:
        try:
            out[name] = metadata.version(name)
        except Exception:
            out[name] = "kurulu değil"
    out["python"] = platform.python_version()
    return out


def sha256_file(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def model_info(root: Optional[Path] = None) -> dict[str, Any]:
    """Model SHA-256 from assets/model_manifest.json, plus the real file hash for comparison."""
    root = root or project_root()
    info: dict[str, Any] = {"manifest_sha256": None, "file_sha256": None, "eslesiyor": None}
    try:
        manifest = json.loads((root / "assets" / "model_manifest.json").read_text(encoding="utf-8"))
        model = manifest["models"][0]
        info["manifest_sha256"] = model.get("sha256")
        local = root / model.get("local_path", "assets/models/hand_landmarker.task")
        info["file_sha256"] = sha256_file(local)
    except Exception as exc:  # manifest missing or malformed
        info["hata"] = str(exc)
    if info["manifest_sha256"] and info["file_sha256"]:
        info["eslesiyor"] = info["manifest_sha256"] == info["file_sha256"]
    return info


def collect_environment(camera_info: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    return {
        "cpu": _cpu_name(),
        "cpu_cekirdek": os.cpu_count(),
        "windows": f"{platform.system()} {platform.release()} ({platform.version()})",
        "kamera": camera_info or {},
    }


def collect_software(root: Optional[Path] = None) -> dict[str, Any]:
    return {"paketler": package_versions(), "model": model_info(root)}


# ---------------------------------------------------------------- report


@dataclass
class Report:
    tool: str                                   # e.g. "finger_test"
    title: str                                  # Turkish title
    stem: str                                   # hw_<tool>_<timestamp>
    status: str = STATUS_TAMAM                  # tamam | yarım | prova, kabul sayılmaz
    environment: dict[str, Any] = field(default_factory=dict)
    software: dict[str, Any] = field(default_factory=dict)
    conditions: dict[str, str] = field(default_factory=dict)   # Koşul (asked from the user)
    experiment: list[str] = field(default_factory=list)        # Deney lines
    result_lines: list[str] = field(default_factory=list)      # Sonuç lines (summary)
    raw: dict[str, Any] = field(default_factory=dict)          # tool specific raw results
    details_md: str = ""                                       # extra Markdown below the table
    decision: str = KARAR_YAPILMADI
    decision_note: str = ""

    def __post_init__(self) -> None:
        if self.decision not in KARARLAR:
            raise ValueError(f"Karar şunlardan biri olmalı: {KARARLAR}")


def _cell(lines: list[str]) -> str:
    text = "<br>".join(line.replace("|", "\\|") for line in lines if line)
    return text or "-"


def _camera_line(cam: dict[str, Any]) -> str:
    if not cam:
        return "kamera: bilinmiyor"
    parts = [f"{k}={v}" for k, v in cam.items()]
    return "kamera: " + ", ".join(parts)


def render_markdown(report: Report) -> str:
    env = report.environment
    sw = report.software
    pk = sw.get("paketler", {})
    model = sw.get("model", {})
    ortam = [
        f"CPU: {env.get('cpu', 'bilinmiyor')} ({env.get('cpu_cekirdek', '?')} çekirdek)",
        f"Windows: {env.get('windows', 'bilinmiyor')}",
        _camera_line(env.get("kamera", {})),
    ]
    yazilim = [
        "Paketler: " + ", ".join(f"{k} {v}" for k, v in pk.items()),
        f"Model SHA-256 (manifest): {model.get('manifest_sha256') or 'yok'}",
        f"Model SHA-256 (dosya): {model.get('file_sha256') or 'dosya yok'}"
        + (
            "" if model.get("eslesiyor") is None
            else (" (eşleşiyor)" if model["eslesiyor"] else " (EŞLEŞMİYOR)")
        ),
    ]
    kosul = [f"{k}: {v}" for k, v in report.conditions.items()] or ["girilmedi"]
    karar = [f"**{report.decision}**"]
    if report.decision_note:
        karar.append(report.decision_note)

    lines = [
        f"# {report.title}",
        "",
        f"Dosya: `{report.stem}` - Durum: **{report.status}**",
        "",
        "| Alan | Kaydedilen bilgi |",
        "|---|---|",
        f"| Ortam | {_cell(ortam)} |",
        f"| Yazılım | {_cell(yazilim)} |",
        f"| Koşul | {_cell(kosul)} |",
        f"| Deney | {_cell(report.experiment)} |",
        f"| Sonuç | {_cell(report.result_lines)} |",
        f"| Karar | {_cell(karar)} |",
        "",
    ]
    if report.details_md:
        lines += [report.details_md.rstrip(), ""]
    lines += [
        "Not: Görüntü karesi ve ham landmark izi kaydedilmedi. "
        "Ayar yapılan denemeler ile kabul denemeleri farklı diziler olmalıdır.",
        "",
    ]
    return "\n".join(lines)


def report_to_json(report: Report) -> dict[str, Any]:
    return {
        "tool": report.tool,
        "title": report.title,
        "stem": report.stem,
        "status": report.status,
        "environment": report.environment,
        "software": report.software,
        "conditions": report.conditions,
        "experiment": report.experiment,
        "result_lines": report.result_lines,
        "decision": report.decision,
        "decision_note": report.decision_note,
        "raw": report.raw,
    }


def save_report(report: Report, out_dir: Optional[Path] = None) -> tuple[Path, Path]:
    """Write <stem>.json and <stem>.md. Returns (md_path, json_path). Overwrites the same stem."""
    out = Path(out_dir) if out_dir else default_reports_dir()
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / f"{report.stem}.json"
    md_path = out / f"{report.stem}.md"
    json_path.write_text(
        json.dumps(report_to_json(report), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return md_path, json_path


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
