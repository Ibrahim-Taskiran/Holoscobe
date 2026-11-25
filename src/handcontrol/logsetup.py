"""File logging for the desktop app: rotating log + unhandled-exception hooks."""
from __future__ import annotations

import logging
import logging.handlers
import sys
import threading
from pathlib import Path
from typing import Callable, Optional

from handcontrol.config import app_data_dir

LOG_NAME = "holoscobe.log"
_HANDLER_TAG = "_holoscobe_file_handler"


def default_logs_dir() -> Path:
    return app_data_dir() / "logs"


def parse_level(level: object) -> int:
    if isinstance(level, int):
        return level
    value = logging.getLevelName(str(level or "INFO").upper())
    return value if isinstance(value, int) else logging.INFO


def setup_logging(logs_dir: Optional[Path] = None, level: object = "INFO",
                  notify: Optional[Callable[[str], None]] = None, *, install_hooks: bool = True) -> Path:
    """Attach a rotating UTF-8 file handler (1 MB x 3) to the root logger; returns the log path.

    Safe to call twice: the previous handler is replaced. notify(text) is called on unhandled errors."""
    logs_dir = Path(logs_dir) if logs_dir is not None else default_logs_dir()
    logs_dir.mkdir(parents=True, exist_ok=True)
    path = logs_dir / LOG_NAME
    teardown_logging()
    handler = logging.handlers.RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(threadName)s %(name)s: %(message)s"))
    setattr(handler, _HANDLER_TAG, True)
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(parse_level(level))
    if install_hooks:
        _install_hooks(notify)
    return path


def teardown_logging() -> None:
    root = logging.getLogger()
    for h in list(root.handlers):
        if getattr(h, _HANDLER_TAG, False):
            root.removeHandler(h)
            try:
                h.close()
            except Exception:
                pass


def _report(exc_type, exc, tb, notify, where: str) -> None:
    logging.getLogger("holoscobe").critical("Unhandled exception (%s)", where, exc_info=(exc_type, exc, tb))
    if notify is not None:
        try:
            notify("Beklenmeyen hata oluştu; ayrıntılar günlük dosyasında.")
        except Exception:
            pass


def _install_hooks(notify: Optional[Callable[[str], None]]) -> None:
    previous = sys.excepthook

    def excepthook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            previous(exc_type, exc, tb)
            return
        _report(exc_type, exc, tb, notify, "main")

    def thread_hook(args):
        if args.exc_type is SystemExit:
            return
        _report(args.exc_type, args.exc_value, args.exc_traceback, notify, getattr(args.thread, "name", "thread"))

    sys.excepthook = excepthook
    threading.excepthook = thread_hook
