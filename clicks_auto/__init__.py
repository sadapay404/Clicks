"""Clicks-Auto - a Windows desktop automation studio for repetitive web tasks.

Combines a Playwright powered playback engine with a DOM level session
recorder.  The package is import safe: importing :mod:`clicks_auto` never
imports PyQt or Playwright, so the core can be unit tested headlessly.
"""

from __future__ import annotations

APP_NAME = "Clicks-Auto"
APP_ID = "clicks-auto"
APP_AUTHOR = "sadapay404"
APP_URL = "https://github.com/sadapay404/Clicks"
__version__ = "1.0.0"
__all__ = ["APP_NAME", "APP_ID", "APP_AUTHOR", "APP_URL", "__version__"]
