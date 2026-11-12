"""Reproducible numeric analysis of the untouched local click recording."""
from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any

RECORDING = Path(__file__).resolve().parents[2] / "Docs/reports/hw_click_20261112-152708-382361.csv"


def read_rows(path: Path = RECORDING) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def good(row: dict[str, str]) -> bool:
    return row["status"] == "ok" and row["quality"] == "usable"


def contacts(rows: list[dict[str, str]], column: str) -> list[dict[str, Any]]:
    """Raw .33/.48 hysteresis excursions; no gesture debounce or fabricated gap samples."""
    result: list[dict[str, Any]] = []
    start: int | None = None
    for i, row in enumerate(rows):
        if not good(row):
            continue
        distance = float(row[column])
        if start is None and distance <= .33:
            start = i
        elif start is not None and distance >= .48:
            result.append({"start": start, "end": i, "ms": round(float(row["t_ms"]) - float(rows[start]["t_ms"]), 1)})
            start = None
    return result


def analyze(rows: list[dict[str, str]]) -> dict[str, Any]:
    groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        groups[row["phase"], row["repeat"]].append(row)
    summary: dict[str, Any] = {"rows": len(rows), "status": dict(Counter(r["status"] for r in rows)), "trials": []}
    gaps: list[float] = []
    phase_gaps: dict[str, list[float]] = defaultdict(list)
    censored: list[dict[str, Any]] = []
    for (phase, repeat), group in groups.items():
        valid = [r for r in group if good(r)]
        bad_spans: list[float] = []
        transitions = 0
        last_good = None
        in_gap = False
        for row in group:
            if good(row):
                if in_gap and last_good is not None:
                    bad_spans.append(float(row["t_ms"]) - float(last_good["t_ms"]))
                    transitions += row["hand_id"] != last_good["hand_id"]
                in_gap = False
                last_good = row
            else:
                in_gap = True
        gaps.extend(bad_spans)
        phase_gaps[phase].extend(bad_spans)
        if in_gap and last_good is not None:
            censored.append({"phase": phase, "repeat": int(repeat),
                             "lower_bound_ms": round(float(group[-1]["t_ms"]) - float(last_good["t_ms"]), 1)})
        column = "middle_distance_pu" if phase == "right_pinch" else "index_distance_pu"
        runs = contacts(group, column)
        open_gaps = []
        for a, b in zip(runs, runs[1:]):
            between = [r for r in group[a["end"]:b["start"]] if good(r)]
            open_gaps.append([round(float(group[b["start"]]["t_ms"]) - float(group[a["end"]]["t_ms"]), 1),
                              round(max(float(r[column]) for r in between), 3) if between else None])
        if phase in ("left_pinch", "right_pinch", "drag"):
            contact = [r for r in valid if float(r[column]) <= .33]
            item = {"phase": phase, "repeat": int(repeat), "n": len(group), "bad": len(group)-len(valid),
                "min_i": round(min((float(r["index_distance_pu"]) for r in valid), default=0), 3),
                "min_m": round(min((float(r["middle_distance_pu"]) for r in valid), default=0), 3),
                "contact_states": dict(Counter((r["index"], r["middle"]) for r in contact)),
                "runs_ms": [r["ms"] for r in runs], "bounce_open_ms_peak": open_gaps,
                "gaps_ms": [round(v, 1) for v in bad_spans], "gap_id_changes": transitions}
            item["contact_states"] = {"/".join(k): v for k, v in item["contact_states"].items()}
            summary["trials"].append(item)
        elif phase in ("still", "range"):
            distances = [float(r["middle_distance_pu"]) for r in valid]
            summary[phase] = {"middle_median": round(median(distances), 3), "middle_min": round(min(distances), 3),
                              "poses": dict(Counter("/".join(r[f] for f in ("index", "middle", "ring", "little")) for r in valid))}
        elif phase == "fist":
            summary.setdefault("fist_all_bent_pct", []).append(round(100*sum(all(r[f] == "bent" for f in ("thumb", "index", "middle", "ring", "little")) for r in valid)/len(valid), 1))
    summary["gaps"] = {"count": len(gaps), "under_200": sum(v < 200 for v in gaps),
                       "median_ms": round(median(gaps), 1), "max_ms": round(max(gaps), 1)} if gaps else {}
    summary["gaps_by_phase"] = {phase: {"count": len(values), "under_200": sum(v < 200 for v in values),
        "median_ms": round(median(values), 1), "p95_ms": round(sorted(values)[math.ceil(.95 * len(values))-1], 1),
        "max_ms": round(max(values), 1)} for phase, values in phase_gaps.items() if values}
    summary["censored_gaps"] = censored
    return summary


def write_excerpt() -> None:
    """Keep every fourth sample plus extrema and transition neighborhoods, at original times."""
    import hashlib
    rows = read_rows()
    wanted = {("left_pinch", "1"), ("left_pinch", "8"), ("right_pinch", "2"),
              ("right_pinch", "6"), ("right_pinch", "8"), ("drag", "3"), ("drag", "5")}
    groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for i, row in enumerate(rows):
        if (row["phase"], row["repeat"]) in wanted:
            groups[row["phase"], row["repeat"]].append(i)
    keep: set[int] = set()
    for indices in groups.values():
        keep.update(indices[::4] + indices[:4] + indices[-4:])
        boundaries = set()
        for a, b in zip(indices, indices[1:]):
            ra, rb = rows[a], rows[b]
            changed = any(ra[k] != rb[k] for k in ("status", "hand_id", "segment", "index", "middle"))
            for column in ("index_distance_pu", "middle_distance_pu"):
                if ra[column] and rb[column]:
                    changed |= any((float(ra[column]) <= threshold) != (float(rb[column]) <= threshold) for threshold in (.33, .48, .9))
            if changed:
                boundaries.add(b)
        for column in ("index_distance_pu", "middle_distance_pu"):
            valid = [i for i in indices if good(rows[i])]
            boundaries.add(min(valid, key=lambda i: float(rows[i][column])))
        for index in boundaries:
            keep.update(i for i in range(index - 2, index + 3) if i in indices)
    data = Path(__file__).parent / "data"
    data.mkdir(exist_ok=True)
    with (data / "click_record_excerpt.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows[i] for i in sorted(keep))
    manifest = {"source": RECORDING.name, "sha256": hashlib.sha256(RECORDING.read_bytes()).hexdigest(),
                "source_rows": len(rows), "excerpt_rows": len(keep), "source_zero_based_rows": sorted(keep),
                "selection": "Every fourth row, group edges, minima and +/-2 around quality, identity, segment, finger-state and .33/.48/.9 distance transitions. Values/timestamps unchanged."}
    (data / "click_record_excerpt.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Excerpt rows: {len(keep)}; source SHA256: {manifest['sha256']}")


if __name__ == "__main__":
    print(json.dumps(analyze(read_rows()), ensure_ascii=False, separators=(",", ":")))
