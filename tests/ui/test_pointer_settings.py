"""Round 4: pointer speed slider and pointer type choice in the settings dialog (never shown)."""
from __future__ import annotations

import pytest

from handcontrol.ui.settings import POINTER_MODE_LABELS_TR, SettingsData, SettingsDialog
from handcontrol.ui.viewmodel import format_gesture_guide_tr


def test_defaults_relative_speed_one_and_new_pinch_thresholds() -> None:
    d = SettingsData()
    assert (d.pointer_mode, d.pointer_speed) == ("relative", 1.0)
    assert (d.pinch_on_threshold, d.pinch_off_threshold) == (0.33, 0.48)
    dlg = SettingsDialog()
    out = dlg.get_settings()
    assert (out.pointer_mode, out.pointer_speed) == ("relative", 1.0)
    assert (out.pinch_on_threshold, out.pinch_off_threshold) == (0.33, 0.48)
    assert not dlg.isVisible()


def test_speed_slider_range_step_and_label() -> None:
    dlg = SettingsDialog()
    s = dlg.slider_pointer_speed
    assert (s.minimum(), s.maximum(), s.singleStep()) == (5, 20, 1)
    s.setValue(s.value() + s.singleStep())
    assert dlg.pointer_speed() == 1.1
    assert dlg.label_pointer_speed.text() == "1.1×"
    s.setValue(s.minimum())
    assert dlg.get_settings().pointer_speed == 0.5
    s.setValue(s.maximum())
    assert dlg.get_settings().pointer_speed == 2.0


def test_pointer_type_choice_labels_and_values() -> None:
    dlg = SettingsDialog()
    combo = dlg.combo_pointer_mode
    items = [(combo.itemText(i), combo.itemData(i)) for i in range(combo.count())]
    assert items == [("Göreli (dokunmatik yüzey gibi)", "relative"),
                     ("Mutlak (kamera alanı = ekran)", "absolute")]
    assert POINTER_MODE_LABELS_TR["absolute"] == "Mutlak (kamera alanı = ekran)"
    combo.setCurrentIndex(1)
    assert dlg.get_settings().pointer_mode == "absolute"


def test_pointer_values_round_trip_and_reset() -> None:
    dlg = SettingsDialog(initial=SettingsData(pointer_mode="absolute", pointer_speed=1.7))
    assert dlg.combo_pointer_mode.currentData() == "absolute"
    assert dlg.slider_pointer_speed.value() == 17
    saved: list[SettingsData] = []
    dlg.settings_applied.connect(saved.append)
    dlg.save_and_accept()
    assert (saved[0].pointer_mode, saved[0].pointer_speed) == ("absolute", 1.7)
    dlg.reset_to_defaults()
    assert (dlg.get_settings().pointer_mode, dlg.get_settings().pointer_speed) == ("relative", 1.0)


@pytest.mark.parametrize(("raw", "speed"), [(0.1, 0.5), (9, 2.0), ("x", 1.0), (float("nan"), 1.0), (1.24, 1.2)])
def test_from_dict_clamps_speed(raw: object, speed: float) -> None:
    assert SettingsData.from_dict({"pointer_speed": raw}).pointer_speed == speed


def test_from_dict_rejects_unknown_pointer_mode() -> None:
    assert SettingsData.from_dict({"pointer_mode": "warp"}).pointer_mode == "relative"
    assert SettingsData.from_dict({"pointer_mode": "ABSOLUTE"}).pointer_mode == "absolute"


def test_gesture_guide_describes_relative_pointer_and_clutch() -> None:
    text = format_gesture_guide_tr()
    for needle in ("İşaret açık, diğer parmaklar kapalı", "hızlı hareket uzağa", "yavaş hareket hassas",
                   "Eli aç", "kaldığı yerden devam", "imleç pinch sırasında durur", "belirgin aç",
                   "0,8 sn", "Başparmak, işaret ve orta parmak uçlarını birleştir",
                   "Açık elden başparmak + orta parmak", "önce el açık olmalı",
                   "Yalnız mutlak"):
        assert needle in text
