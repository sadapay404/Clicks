"""Shared application context passed to every page."""

from __future__ import annotations

from typing import Any, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from ..settings import Settings
from ..store import ScriptStore
from .anim import MOTION
from .theme import Palette, get_palette


class AppContext(QObject):
    """Settings, palette, script library and cross page notifications."""

    palette_changed = pyqtSignal(object)      # Palette
    settings_saved = pyqtSignal()
    navigate = pyqtSignal(str)                # page key
    status_message = pyqtSignal(str, str)     # text, level

    def __init__(self, settings: Optional[Settings] = None, store: Optional[ScriptStore] = None,
                 parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.settings = (settings or Settings.load()).clamp()
        self.store = store or ScriptStore()
        self.palette: Palette = get_palette(self.settings.ui.theme)
        self.toasts: Any = None
        self.tray: Any = None
        self.window: Any = None
        MOTION.update_from(self.settings.ui)

    # ---------------------------------------------------------------- palette
    def set_theme(self, key: str) -> None:
        self.settings.ui.theme = key
        self.palette = get_palette(key)
        self.save()
        self.palette_changed.emit(self.palette)

    def save(self) -> None:
        if self.toasts is not None and self.settings.ui.toasts is False:
            pass
        self.settings.clamp()
        MOTION.update_from(self.settings.ui)
        try:
            self.settings.save()
        except Exception:
            pass
        self.settings_saved.emit()

    # ---------------------------------------------------------------- helpers
    def toast(self, message: str, *, level: str = "info", title: str = "") -> None:
        if self.toasts is None or not self.settings.ui.toasts:
            return
        if level == "success":
            self.toasts.success(message, title)
        elif level == "error":
            self.toasts.error(message, title)
        elif level == "warning":
            self.toasts.warning(message, title)
        else:
            self.toasts.info(message, title)

    def goto(self, page_key: str) -> None:
        self.navigate.emit(page_key)

    def status(self, text: str, level: str = "info") -> None:
        self.status_message.emit(text, level)

    def refresh_library(self) -> list:
        return self.store.list_entries()

    # ------------------------------------------------------------------ run prefs
    def run_defaults(self) -> dict[str, Any]:
        run = self.settings.run
        return {
            "loop_mode": run.loop_mode,
            "loop_count": run.loop_count,
            "duration_minutes": run.loop_duration_min,
            "headless": run.headless,
            "slow_mo_ms": run.slow_mo_ms,
            "stop_on_error": run.stop_on_error,
            "restart_browser_each_loop": run.restart_browser_each_loop,
            "close_browser_when_done": run.close_browser_when_done,
            "data_file": run.data_file,
            "screenshot_on_error": run.screenshot_on_error,
        }
