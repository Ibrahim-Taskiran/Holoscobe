"""Round 3 click actions: Turkish labels, dry-run text and the tray gesture guide."""
from __future__ import annotations

import pytest

from handcontrol.contracts import Action, ActionKind
from handcontrol.ui.tray import HandControlTray
from handcontrol.ui.viewmodel import (
    ACTION_KIND_LABELS_TR,
    COMMANDS_GUIDE_TR,
    GESTURE_GUIDE_TR,
    UiBridge,
    format_action_tr,
    format_gesture_guide_tr,
)


@pytest.mark.parametrize(
    ("kind", "label"),
    [
        (ActionKind.LEFT_CLICK, "Sol Tık"),
        (ActionKind.RIGHT_CLICK, "Sağ Tık"),
        (ActionKind.DOUBLE_CLICK, "Çift Tık"),
        (ActionKind.LEFT_DOWN, "Sol Tuş Basılı (Sürükle)"),
        (ActionKind.LEFT_UP, "Sol Tuş Bırakıldı"),
    ],
)
def test_click_action_labels_and_dry_run_text(kind: ActionKind, label: str) -> None:
    assert ACTION_KIND_LABELS_TR[kind] == label
    text = format_action_tr(Action(kind=kind, epoch=1, capture_ms=0.0, x=120, y=340))
    assert text == f"Üretilecek komut: {label} | konum=(120, 340)"


def test_every_action_kind_has_turkish_label() -> None:
    assert set(ACTION_KIND_LABELS_TR) == set(ActionKind)


def test_gesture_guide_lists_new_click_gestures() -> None:
    text = format_gesture_guide_tr()
    for needle in ("Sol tık", "Çift tık", "Sürükle", "Sağ tık", "orta parmak", "küçült", "geri aç"):
        assert needle in text
    # The unreliable index push click is no longer advertised.
    assert "öne it" not in text
    assert len(text.splitlines()) == len(GESTURE_GUIDE_TR)


def test_tray_gesture_guide_submenu_is_read_only() -> None:
    tray = HandControlTray(UiBridge())
    assert tray.guide_menu.title() == "Hareket Rehberi"
    assert tray.guide_menu.menuAction() in tray.menu.actions()
    entries = [a for a in tray.guide_menu.actions() if not a.isSeparator()]
    expected = [f"{g} → {r}" for g, r in (*GESTURE_GUIDE_TR, *COMMANDS_GUIDE_TR)]
    assert [a.text() for a in entries] == expected
    assert not any(a.isEnabled() for a in entries)
    assert tray.guide_commands_section.text() == "Komutlar modu"
