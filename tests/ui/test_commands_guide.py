"""The Komutlar guide text is derived from swipe.py and must match it for every profile."""
from handcontrol.swipe import COMMAND_LABELS, PROFILES, SwipeDirection, pinch_command, swipe_command
from handcontrol.ui.viewmodel import COMMANDS_GUIDE_TR, SWIPE_PROFILE_LABELS_TR

GUIDE = dict(COMMANDS_GUIDE_TR)


def _entry(text: str, label: str) -> str:
    return text.split(f"{label}: ")[1].split(" · ")[0]


def test_horizontal_guide_matches_swipe_profiles() -> None:
    for prof in PROFILES:
        label = SWIPE_PROFILE_LABELS_TR[prof]
        assert _entry(GUIDE["Sola kaydır"], label) == COMMAND_LABELS[swipe_command(prof, SwipeDirection.LEFT)]
        assert _entry(GUIDE["Sağa kaydır"], label) == COMMAND_LABELS[swipe_command(prof, SwipeDirection.RIGHT)]


def test_slides_left_is_next_and_browser_left_is_forward() -> None:
    assert _entry(GUIDE["Sola kaydır"], "Sunum") == "Sonraki"
    assert _entry(GUIDE["Sola kaydır"], "Tarayıcı") == "İleri"


def test_vertical_and_pinch_guide() -> None:
    assert GUIDE["Yukarı kaydır"] == COMMAND_LABELS[swipe_command("slides", SwipeDirection.UP)]
    assert GUIDE["Aşağı kaydır"] == COMMAND_LABELS[swipe_command("media", SwipeDirection.DOWN)]
    assert COMMAND_LABELS[pinch_command("desktops")] in GUIDE["Kısa pinch"]
    assert COMMAND_LABELS[pinch_command("slides")] in GUIDE["Kısa pinch"]
