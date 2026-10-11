"""Filesystem helpers: application data locations and bundled resources."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import APP_ID


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """Directory that holds bundled read-only resources."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def resource_path(*parts: str) -> Path:
    return resource_root().joinpath(*parts)


def app_data_dir() -> Path:
    """Per-user writable directory for settings, scripts, logs and profiles."""
    override = os.environ.get("CLICKS_AUTO_HOME")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Clicks-Auto"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "Clicks-Auto"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_ID
    base.mkdir(parents=True, exist_ok=True)
    return base


def sub_dir(*parts: str) -> Path:
    path = app_data_dir().joinpath(*parts)
    path.mkdir(parents=True, exist_ok=True)
    return path


def scripts_dir() -> Path:
    return sub_dir("scripts")


def logs_dir() -> Path:
    return sub_dir("logs")


def profiles_dir() -> Path:
    return sub_dir("browser-profiles")


def screenshots_dir() -> Path:
    return sub_dir("screenshots")


def settings_file() -> Path:
    return app_data_dir() / "settings.json"


def history_file() -> Path:
    return app_data_dir() / "history.jsonl"


def schedules_file() -> Path:
    return app_data_dir() / "schedules.json"


def playwright_browsers_dir() -> Path:
    """Writable folder for a Chromium downloaded by the user at run time."""
    return sub_dir("ms-playwright")


def default_user_data_dir() -> Path:
    """Isolated browser profile used by automations (keeps logins separate)."""
    return sub_dir("browser-profiles", "default")


def ensure_ascii_safe_path(path: Path) -> Path:
    """Windows tooling dislikes very long/non-ascii paths - normalise a bit."""
    return Path(os.path.abspath(str(path)))


def human_path(path: Path | str) -> str:
    text = str(path)
    home = str(Path.home())
    if text.startswith(home):
        text = "~" + text[len(home):]
    return text
