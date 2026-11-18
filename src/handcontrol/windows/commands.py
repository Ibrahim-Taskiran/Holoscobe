"""KeyCommand -> virtual-key chord table. Pure data: no ctypes, no desktop access."""
from __future__ import annotations

from ..contracts import KeyCommand

VK_TAB, VK_CONTROL, VK_MENU = 0x09, 0x11, 0x12
VK_LEFT, VK_RIGHT = 0x25, 0x27
VK_D, VK_LWIN = 0x44, 0x5B
VK_VOLUME_MUTE = 0xAD
VK_MEDIA_NEXT_TRACK, VK_MEDIA_PREV_TRACK, VK_MEDIA_PLAY_PAUSE = 0xB0, 0xB1, 0xB3

# Pressed in order, released in reverse.
COMMAND_KEYS: dict[KeyCommand, tuple[int, ...]] = {
    KeyCommand.NEXT: (VK_RIGHT,),
    KeyCommand.PREVIOUS: (VK_LEFT,),
    KeyCommand.BROWSER_BACK: (VK_MENU, VK_LEFT),
    KeyCommand.BROWSER_FORWARD: (VK_MENU, VK_RIGHT),
    KeyCommand.TASK_VIEW: (VK_LWIN, VK_TAB),
    KeyCommand.SHOW_DESKTOP: (VK_LWIN, VK_D),
    KeyCommand.DESKTOP_LEFT: (VK_CONTROL, VK_LWIN, VK_LEFT),
    KeyCommand.DESKTOP_RIGHT: (VK_CONTROL, VK_LWIN, VK_RIGHT),
    KeyCommand.MEDIA_PLAY_PAUSE: (VK_MEDIA_PLAY_PAUSE,),
    KeyCommand.MEDIA_NEXT: (VK_MEDIA_NEXT_TRACK,),
    KeyCommand.MEDIA_PREVIOUS: (VK_MEDIA_PREV_TRACK,),
    KeyCommand.VOLUME_MUTE: (VK_VOLUME_MUTE,),
}

COMMAND_LABELS_TR: dict[KeyCommand, str] = {
    KeyCommand.NEXT: "Sonraki",
    KeyCommand.PREVIOUS: "Önceki",
    KeyCommand.BROWSER_BACK: "Tarayıcı geri",
    KeyCommand.BROWSER_FORWARD: "Tarayıcı ileri",
    KeyCommand.TASK_VIEW: "Görev görünümü",
    KeyCommand.SHOW_DESKTOP: "Masaüstünü göster",
    KeyCommand.DESKTOP_LEFT: "Sol masaüstü",
    KeyCommand.DESKTOP_RIGHT: "Sağ masaüstü",
    KeyCommand.MEDIA_PLAY_PAUSE: "Oynat/Duraklat",
    KeyCommand.MEDIA_NEXT: "Sonraki parça",
    KeyCommand.MEDIA_PREVIOUS: "Önceki parça",
    KeyCommand.VOLUME_MUTE: "Sesi kapat/aç",
}

COMMAND_KEYS_TR: dict[KeyCommand, str] = {
    KeyCommand.NEXT: "Sağ ok",
    KeyCommand.PREVIOUS: "Sol ok",
    KeyCommand.BROWSER_BACK: "Alt+Sol ok",
    KeyCommand.BROWSER_FORWARD: "Alt+Sağ ok",
    KeyCommand.TASK_VIEW: "Win+Tab",
    KeyCommand.SHOW_DESKTOP: "Win+D",
    KeyCommand.DESKTOP_LEFT: "Ctrl+Win+Sol ok",
    KeyCommand.DESKTOP_RIGHT: "Ctrl+Win+Sağ ok",
    KeyCommand.MEDIA_PLAY_PAUSE: "Medya oynat/duraklat",
    KeyCommand.MEDIA_NEXT: "Medya sonraki",
    KeyCommand.MEDIA_PREVIOUS: "Medya önceki",
    KeyCommand.VOLUME_MUTE: "Sesi kapat",
}


def parse_command(value: str) -> KeyCommand | None:
    """KeyCommand for an Action.command string, or None when unknown/empty."""
    try:
        return KeyCommand(value)
    except ValueError:
        return None
