"""Opt-in, current-user Windows startup registration; never enables live control."""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "Holoscobe"


def default_command() -> str:
    """Quote Unicode executable paths and leave live control explicitly disabled."""
    executable = Path(sys.executable)
    if getattr(sys, "frozen", False):
        return f'"{executable}"'
    return f'"{executable.with_name("pythonw.exe")}" -m handcontrol.app'


def _registry(registry: Any | None) -> Any:
    if registry is None:
        import winreg
        return winreg
    return registry


def is_enabled(*, registry: Any | None = None) -> bool:
    """Read the current user's Run value without creating or changing anything."""
    try:
        reg = _registry(registry)
        with reg.OpenKey(reg.HKEY_CURRENT_USER, RUN_KEY, 0, reg.KEY_QUERY_VALUE) as key:
            command, value_type = reg.QueryValueEx(key, VALUE_NAME)
        return value_type == reg.REG_SZ and isinstance(command, str) and bool(command.strip())
    except FileNotFoundError:
        return False
    except Exception:
        log.exception("Could not read current-user startup registration")
        return False


def set_enabled(enabled: bool, command: str | None = None, *, registry: Any | None = None) -> bool:
    """Update HKCU only. Missing values are already disabled; failures never raise."""
    try:
        reg = _registry(registry)
        if enabled:
            command = default_command() if command is None else command
            if not command.strip() or "\x00" in command or "--live" in command:
                log.warning("Refusing empty, invalid or live startup command")
                return False
            with reg.CreateKeyEx(reg.HKEY_CURRENT_USER, RUN_KEY, 0, reg.KEY_SET_VALUE) as key:
                reg.SetValueEx(key, VALUE_NAME, 0, reg.REG_SZ, command)
        else:
            try:
                with reg.OpenKey(reg.HKEY_CURRENT_USER, RUN_KEY, 0, reg.KEY_SET_VALUE) as key:
                    reg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                return True
        return True
    except Exception:
        log.exception("Could not update current-user startup registration")
        return False
