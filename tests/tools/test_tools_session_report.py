from __future__ import annotations
import csv
from handcontrol.telemetry import COLUMNS
from handcontrol.tools import session_report as sr


def make_csv(path, specs, drop=()):
    cols = [c for c in COLUMNS if c not in drop]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for i, spec in enumerate(specs):
            row = dict.fromkeys(COLUMNS, "")
            row.update(t_ms=i * 100.0, age_ms=10, dom_present=1, dom_quality="usable", pinch_pu=0.8,
                       palm_x_px=100, palm_y_px=100, palm_scale_px=80, pointer_x=5, pointer_y=5,
                       pointer_engaged=1, tracking_ok=1, finger_thumb="extended", finger_ring="unknown")
            row.update(spec)
            w.writerow(row)


def test_report_numbers(tmp_path):
    specs = [{} for _ in range(25)]
    for i in (5, 6, 7):  # dropout: usable at 400 ms, back at 800 ms -> 400 ms gap
        specs[i].update(dom_present=0, dom_quality="", pointer_engaged=0)
    specs[12].update(pointer_engaged=0)  # one-frame flicker, hand present
    for i in (14, 15):
        specs[i]["pinch_pu"] = 0.2
    specs[16]["pinch_pu"] = 0.6
    specs[17]["pinch_pu"] = 0.2
    specs[18]["pinch_pu"] = 0.7
    specs[15]["actions"] = "left_click"
    specs[17]["actions"] = "left_down|right_click"
    specs[18]["last_cancel"] = "Poz bozuldu"
    specs[19]["last_cancel"] = "Poz bozuldu"
    specs[20]["last_cancel"] = ""
    specs[21]["last_cancel"] = "Poz bozuldu"
    for i in (3, 4):
        specs[i]["notice"] = "Pencereyi odaklayın"
    for i, x in zip((22, 23, 24), (100, 130, 160)):  # pointer fixed while palm moves
        specs[i].update(palm_x_px=x)
    p = tmp_path / "s.csv"
    make_csv(p, specs)
    text = sr.build_report(p, tmp_path / "r.md").read_text(encoding="utf-8")
    assert "Süre: 2.4 sn" in text
    assert "(22/25)" in text
    assert "- 200-500 ms: 1" in text
    assert "poz titremesi): 1" in text
    assert "çıkma): 2" in text
    assert "sol tık 1, sağ tık 1, çift tık 0, sürükleme başlangıcı 1" in text
    assert "Poz bozuldu: 2" in text
    assert "ring: %100.0 (22/22)" in text and "thumb: %0.0" in text
    assert "Pencereyi odaklayın: 1" in text
    assert "kıpırdamadı): 1" in text


def test_missing_columns_say_veri_yok(tmp_path):
    p = tmp_path / "s.csv"
    make_csv(p, [{} for _ in range(5)], drop=("pointer_engaged", "last_cancel", "actions", "notice", "finger_ring"))
    text = sr.build_report(p, tmp_path / "r.md").read_text(encoding="utf-8")
    assert "Bağlı kalma oranı: veri yok" in text
    assert "Gönderilen eylemler: veri yok" in text and "İptaller: veri yok" in text
    assert "ring: veri yok" in text


def test_cli_main_and_missing_file(tmp_path):
    p = tmp_path / "s.csv"
    make_csv(p, [{} for _ in range(3)])
    assert sr.main([str(p), "--out", str(tmp_path / "o.md")]) == 0
    assert (tmp_path / "o.md").is_file()
    assert sr.main([str(tmp_path / "none.csv")]) == 1


def test_reason_section_counts_and_gap_starts(tmp_path):
    specs = [{} for _ in range(20)]
    for i in (3, 4, 5, 6):   # 400 ms gap, first bad frame palm_small
        specs[i].update(dom_quality="degraded", dom_reasons="palm_small|slow_processing")
    specs[10].update(dom_quality="degraded", dom_reasons="overlap")   # 200 ms gap (9 -> 11)
    specs[14].update(dom_present=0, dom_quality="")                   # 200 ms gap, hand absent
    p = tmp_path / "s.csv"
    make_csv(p, specs)
    text = sr.build_report(p, tmp_path / "r.md").read_text(encoding="utf-8")
    assert "## Takip bozulma nedenleri" in text
    assert "  - palm_small: 4" in text and "  - overlap: 1" in text and "  - hand_absent: 1" in text
    assert "ve uzun kopukluklar (3)" in text
    sec = text.split("ilk bozuk karenin nedenleri:")[1]
    assert "  - palm_small: 1" in sec and "  - slow_processing: 1" in sec and "  - overlap: 1" in sec


def test_reason_section_without_column_and_old_csv(tmp_path):
    p = tmp_path / "s.csv"
    make_csv(p, [{} for _ in range(5)], drop=("dom_reasons", "mid_pinch_pu"))
    text = sr.build_report(p, tmp_path / "r.md").read_text(encoding="utf-8")
    assert "## Takip bozulma nedenleri" in text and "Neden kodları: veri yok" in text


def test_fps_median_interval_and_pinch_hold_table(tmp_path):
    specs = [{} for _ in range(30)]
    # 200 ms pinch -> left click; 600 ms -> drag; 400 ms -> cancel; 900 ms (cut by file end) -> nothing
    for i in (2, 3):
        specs[i]["pinch_pu"] = 0.2
    specs[3]["actions"] = "left_click"
    for i in range(6, 12):
        specs[i]["pinch_pu"] = 0.2
    specs[8]["actions"] = "left_down"
    for i in (14, 15, 16, 17):
        specs[i]["pinch_pu"] = 0.2
    specs[16]["last_cancel"] = "Poz bozuldu"
    specs[17]["last_cancel"] = "Poz bozuldu"
    for i in range(20, 30):
        specs[i]["pinch_pu"] = 0.2
    p = tmp_path / "s.csv"
    make_csv(p, specs)
    text = sr.build_report(p, tmp_path / "r.md").read_text(encoding="utf-8")
    assert "Kare sayısı: 30, ortalama fps: 10.3" in text and "medyan kare aralığı: 100.0 ms" in text
    # span = first frame below 0.33 .. first frame above 0.48 (release); last one is cut at the file end
    assert "  - < 200 ms: 0 / 0 / 0 / 0 / 0 (0)" in text
    assert "  - 200-480 ms: 1 / 0 / 0 / 1 / 0 (2)" in text       # rows 2..4 left click, rows 14..18 cancel
    assert "  - 480-1000 ms: 0 / 1 / 0 / 0 / 1 (2)" in text      # rows 6..12 drag, rows 20..29 nothing
    assert "  - > 1000 ms: 0 / 0 / 0 / 0 / 0 (0)" in text


def test_pinch_hold_table_missing_columns(tmp_path):
    p = tmp_path / "s.csv"
    make_csv(p, [{} for _ in range(5)], drop=("pinch_pu",))
    text = sr.build_report(p, tmp_path / "r.md").read_text(encoding="utf-8")
    assert "Pinch denemeleri süreye göre" in text and "  - veri yok" in text
