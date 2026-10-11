"""Persistent application settings."""

from __future__ import annotations

import copy
import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from .paths import settings_file

LOOP_MODES = ("infinite", "count", "duration")
THEMES = ("midnight", "aurora", "sunset", "graphite", "daylight")


@dataclass
class BrowserPrefs:
    """Which Chromium flavour Clicks-Auto should drive."""

    kind: str = "brave"  # brave | chrome | edge | chromium | custom
    custom_path: str = ""
    user_data_dir: str = ""  # empty -> isolated profile managed by the app
    use_existing_profile: bool = False
    window_width: int = 1280
    window_height: int = 860
    start_maximized: bool = False
    extra_args: list[str] = field(default_factory=list)
    download_dir: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TimeoutPrefs:
    action_ms: int = 20000
    navigation_ms: int = 45000
    step_retries: int = 2
    retry_delay_ms: int = 700
    delay_between_steps_ms: int = 250
    delay_between_loops_ms: int = 1200
    loop_restart_browser_after: int = 0  # 0 = never
    type_delay_ms: int = 40


@dataclass
class UiPrefs:
    theme: str = "midnight"
    animations: bool = True
    animation_speed: float = 1.0
    reduce_motion: bool = False
    native_titlebar: bool = False
    window_width: int = 1360
    window_height: int = 880
    sidebar_width: int = 232
    log_autoscroll: bool = True
    log_max_lines: int = 5000
    toasts: bool = True
    start_page: str = "dashboard"
    compact: bool = False


@dataclass
class RunDefaults:
    loop_mode: str = "count"
    loop_count: int = 1
    loop_duration_min: int = 10
    headless: bool = False
    slow_mo_ms: int = 0
    stop_on_error: bool = False
    restart_browser_each_loop: bool = False
    close_browser_when_done: bool = False
    data_file: str = ""
    screenshot_on_error: bool = True
    sound_on_finish: bool = True


@dataclass
class Settings:
    version: int = 1
    browser: BrowserPrefs = field(default_factory=BrowserPrefs)
    timeouts: TimeoutPrefs = field(default_factory=TimeoutPrefs)
    ui: UiPrefs = field(default_factory=UiPrefs)
    run: RunDefaults = field(default_factory=RunDefaults)
    last_script: str = ""
    recent_scripts: list[str] = field(default_factory=list)
    first_run_done: bool = False

    # ------------------------------------------------------------------ io
    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["version"] = self.version
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Settings":
        known = {f.name for f in fields(cls)}
        cleaned: dict[str, Any] = {k: v for k, v in (data or {}).items() if k in known}
        sections = {
            "browser": BrowserPrefs,
            "timeouts": TimeoutPrefs,
            "ui": UiPrefs,
            "run": RunDefaults,
        }
        for name, klass in sections.items():
            raw = cleaned.get(name)
            if isinstance(raw, dict):
                sub_known = {f.name for f in fields(klass)}
                cleaned[name] = klass(**{k: v for k, v in raw.items() if k in sub_known})
            elif raw is None:
                cleaned.pop(name, None)
        try:
            return cls(**cleaned)
        except TypeError:
            return cls()

    def save(self, path: Path | None = None) -> Path:
        target = Path(path) if path else settings_file()
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        tmp.replace(target)
        return target

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        target = Path(path) if path else settings_file()
        if not target.exists():
            return cls()
        try:
            return cls.from_dict(json.loads(target.read_text(encoding="utf-8")))
        except Exception:
            backup = target.with_suffix(".corrupt.json")
            try:
                backup.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
            except Exception:
                pass
            return cls()

    # --------------------------------------------------------------- helpers
    def clone(self) -> "Settings":
        return Settings.from_dict(copy.deepcopy(self.to_dict()))

    def clamp(self) -> "Settings":
        """Keep values inside sane bounds (defensive against hand editing)."""
        t, u, r, b = self.timeouts, self.ui, self.run, self.browser
        t.action_ms = max(1000, min(600_000, int(t.action_ms or 20000)))
        t.navigation_ms = max(1000, min(900_000, int(t.navigation_ms or 45000)))
        t.step_retries = max(0, min(10, int(t.step_retries or 0)))
        t.retry_delay_ms = max(0, min(30_000, int(t.retry_delay_ms or 0)))
        t.delay_between_steps_ms = max(0, min(60_000, int(t.delay_between_steps_ms or 0)))
        t.delay_between_loops_ms = max(0, min(600_000, int(t.delay_between_loops_ms or 0)))
        t.loop_restart_browser_after = max(0, int(t.loop_restart_browser_after or 0))
        t.type_delay_ms = max(0, min(1000, int(t.type_delay_ms or 0)))
        u.animation_speed = max(0.25, min(4.0, float(u.animation_speed or 1.0)))
        u.log_max_lines = max(200, min(200_000, int(u.log_max_lines or 5000)))
        if u.theme not in THEMES:
            u.theme = "midnight"
        r.loop_mode = r.loop_mode if r.loop_mode in LOOP_MODES else "count"
        r.loop_count = max(1, int(r.loop_count or 1))
        r.loop_duration_min = max(1, int(r.loop_duration_min or 10))
        r.slow_mo_ms = max(0, min(5000, int(r.slow_mo_ms or 0)))
        b.window_width = max(800, min(3840, int(b.window_width or 1280)))
        b.window_height = max(600, min(2160, int(b.window_height or 860)))
        return self
