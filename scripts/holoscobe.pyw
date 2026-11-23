"""Console-free launcher of the current source (desktop shortcut target): always the newest code, no rebuild."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "src"))
# pythonw has no console: libraries that print must not fail on a missing stream
for name in ("stdout", "stderr"):
    if getattr(sys, name) is None:
        setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))

from handcontrol.app import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
