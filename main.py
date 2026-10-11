"""Clicks-Auto - Windows desktop studio for recording and replaying web automation.

This module is the graphical entry point (``Clicks-Auto.exe``).  Use
``clicks-auto-cli.exe`` or ``python -m clicks_auto run script.json`` for the
headless command line interface.
"""

from __future__ import annotations

import os
import sys


def main() -> int:
    if sys.platform == "win32":
        # Keep the taskbar icon and DPI behaviour predictable.
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    elif not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from clicks_auto.app import run_gui

    return run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
