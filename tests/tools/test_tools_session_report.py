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
