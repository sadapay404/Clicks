"""Live log console with filtering, highlighting and animated appends."""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..anim import MOTION, fade_in
from ..theme import Palette, rgba
from .common import IconButton, Pill, SearchBox, ToggleSwitch

LEVEL_GLYPHS = {
    "info": "\u2022",
    "action": "\u27a4",
    "ok": "\u2713",
    "warn": "\u26a0",
    "error": "\u2716",
    "debug": "\u00b7",
    "system": "\u2699",
}

FILTERS = ["All", "Actions", "Warnings", "Errors"]


class ConsoleView(QPlainTextEdit):
    """Monospace log view that flashes newly appended lines."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("Console")
        self.setReadOnly(True)
        self.setUndoRedoEnabled(False)
        self.setMaximumBlockCount(0)
        self.setWordWrapMode(self.wordWrapMode())
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setFont(QFont("Cascadia Mono", 9))
        self._flash_blocks: list[tuple[int, int]] = []
        self._flash_timer = QTimer(self)
        self._flash_timer.setInterval(45)
        self._flash_timer.timeout.connect(self._fade_flash)

    def flash_last(self, block_count: int = 1) -> None:
        if not MOTION.enabled:
            return
        document = self.document()
        total = document.blockCount()
        start = max(0, total - block_count)
        self._flash_blocks.append((start, 6))
        if not self._flash_timer.isActive():
            self._flash_timer.start()

    def _fade_flash(self) -> None:
        if not self._flash_blocks:
            self._flash_timer.stop()
            self.setExtraSelections([])
            return
        selections = []
        remaining: list[tuple[int, int]] = []
        document = self.document()
        for block_index, ticks in self._flash_blocks:
            block = document.findBlockByNumber(block_index)
            if not block.isValid() or ticks <= 0:
                continue
            selection = QTextEdit.ExtraSelection()
            cursor = QTextCursor(block)
            cursor.select(QTextCursor.SelectionType.LineUnderCursor)
            selection.cursor = cursor
            color = QColor("#ffffff")
            color.setAlpha(max(0, int(18 * (ticks / 6.0))))
            selection.format.setBackground(color)
            selection.format.setProperty(QTextCharFormat.Property.FullWidthSelection, True)
            selections.append(selection)
            remaining.append((block_index, ticks - 1))
        self._flash_blocks = remaining
        self.setExtraSelections(selections)


class LogConsole(QWidget):
    """Console panel: filter chips, search, autoscroll, export."""

    def __init__(self, parent: Optional[QWidget] = None, *, palette: Palette,
                 max_lines: int = 5000, compact_header: bool = False) -> None:
        super().__init__(parent)
        self._palette = palette
        self._max_lines = max_lines
        self._entries: list[tuple[str, str, str]] = []   # (level, timestamp, message)
        self._filter = "All"
        self._search = ""
        self._autoscroll = True
        self._counts = {"info": 0, "action": 0, "ok": 0, "warn": 0, "error": 0, "debug": 0, "system": 0}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        if not compact_header:
            layout.addWidget(self._build_toolbar())

        self.view = ConsoleView(self)
        self.view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.view, 1)

    # --------------------------------------------------------------- toolbar
    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("ConsoleToolbar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.title = QLabel("Console")
        font = self.title.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 1)
        self.title.setFont(font)
        layout.addWidget(self.title)

        self.count_pill = Pill("0 lines", level="muted")
        layout.addWidget(self.count_pill)
        layout.addStretch(1)

        self.filter_buttons: dict[str, QPushButton] = {}
        for name in FILTERS:
            button = QPushButton(name)
            button.setProperty("kind", "chip")
            button.setCheckable(True)
            button.setChecked(name == "All")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, n=name: self.set_filter(n))
            layout.addWidget(button)
            self.filter_buttons[name] = button

        self.search = SearchBox("Filter text...")
        self.search.setFixedWidth(180)
        self.search.textChanged.connect(self._on_search)
        layout.addWidget(self.search)

        self.autoscroll_switch = ToggleSwitch(checked=True, accent=self._palette.accent,
                                              track_off=self._palette.border)
        self.autoscroll_switch.setToolTip("Auto-scroll to the newest line")
        self.autoscroll_switch.toggled.connect(self._set_autoscroll)
        layout.addWidget(self.autoscroll_switch)

        self.copy_button = IconButton("\u2398", tooltip="Copy the visible log")
        self.copy_button.clicked.connect(self.copy_all)
        layout.addWidget(self.copy_button)

        self.save_button = IconButton("\u2913", tooltip="Save the log to a file")
        self.save_button.clicked.connect(self.save_to_file)
        layout.addWidget(self.save_button)

        self.clear_button = IconButton("\u232b", tooltip="Clear the console")
        self.clear_button.clicked.connect(self.clear)
        layout.addWidget(self.clear_button)
        return bar

    # ------------------------------------------------------------------ data
    def set_palette(self, palette: Palette) -> None:
        self._palette = palette
        self.autoscroll_switch.set_colors(palette.accent, palette.border)
        self._rerender()

    def log(self, level: str, message: str, *, timestamp: Optional[str] = None) -> None:
        level = level if level in LEVEL_GLYPHS else "info"
        stamp = timestamp or datetime.now().strftime("%H:%M:%S")
        message = str(message).rstrip()
        self._entries.append((level, stamp, message))
        self._counts[level] = self._counts.get(level, 0) + 1
        if len(self._entries) > self._max_lines:
            self._entries = self._entries[-self._max_lines:]
            self._rerender(animate=False)
            return
        if self._matches(level, message):
            self._append_line(level, stamp, message)
            self.view.flash_last(1)
        self._update_counts()

    def _matches(self, level: str, message: str) -> bool:
        if self._search and self._search.lower() not in message.lower():
            return False
        if self._filter == "Actions":
            return level in ("action", "ok")
        if self._filter == "Warnings":
            return level in ("warn", "error")
        if self._filter == "Errors":
            return level == "error"
        return True

    def _append_line(self, level: str, stamp: str, message: str) -> None:
        color = self._level_color(level)
        glyph = LEVEL_GLYPHS.get(level, "\u2022")
        safe = (
            message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )
        html = (
            f'<span style="color:{rgba(self._palette.text_faint, 1.0)}">{stamp}</span> '
            f'<span style="color:{color}">{glyph}</span> '
            f'<span style="color:{self._text_color(level)}">{safe}</span>'
        )
        self.view.appendHtml(html)
        if self._autoscroll:
            bar = self.view.verticalScrollBar()
            if MOTION.enabled:
                from ..anim import animate_value

                animate_value(bar.value(), bar.maximum(), 180,
                              lambda v: bar.setValue(int(v)), easing_name="out", parent=self.view)
            else:
                bar.setValue(bar.maximum())

    def _text_color(self, level: str) -> str:
        if level == "error":
            return self._palette.danger
        if level == "warn":
            return self._palette.warning
        if level in ("debug", "system"):
            return self._palette.text_faint
        if level == "action":
            return self._palette.text
        return self._palette.text_dim

    def _level_color(self, level: str) -> str:
        return {
            "info": self._palette.info,
            "action": self._palette.accent_hi,
            "ok": self._palette.success,
            "warn": self._palette.warning,
            "error": self._palette.danger,
            "debug": self._palette.text_faint,
            "system": self._palette.info,
        }.get(level, self._palette.text_dim)

    def _rerender(self, *, animate: bool = True) -> None:
        self.view.clear()
        for level, stamp, message in self._entries:
            if self._matches(level, message):
                self._append_line(level, stamp, message)
        self._update_counts()
        if animate:
            fade_in(self.view, 160)

    def _update_counts(self) -> None:
        total = len(self._entries)
        shown = sum(1 for level, _, message in self._entries if self._matches(level, message))
        if shown == total:
            self.count_pill.setText(f"{total} lines")
            self.count_pill.set_level("muted")
        else:
            self.count_pill.setText(f"{shown}/{total} lines")
            self.count_pill.set_level("info")
        errors = self._counts.get("error", 0)
        warnings = self._counts.get("warn", 0)
        if errors:
            self.count_pill.set_level("danger")
            self.count_pill.setText(f"{errors} error(s)")
        elif warnings:
            self.count_pill.set_level("warning")
            self.count_pill.setText(f"{warnings} warning(s)")

    # --------------------------------------------------------------- controls
    def set_filter(self, name: str) -> None:
        self._filter = name
        for key, button in self.filter_buttons.items():
            button.setChecked(key == name)
        self._rerender()

    def _on_search(self, text: str) -> None:
        self._search = text.strip()
        self._rerender(animate=False)

    def _set_autoscroll(self, value: bool) -> None:
        self._autoscroll = value
        if value:
            self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().maximum())

    def clear(self) -> None:
        self._entries.clear()
        self._counts = {key: 0 for key in self._counts}
        self.view.clear()
        self._update_counts()

    def copy_all(self) -> str:
        text = self.view.toPlainText()
        from PyQt6.QtWidgets import QApplication

        QApplication.clipboard().setText(text)
        return text

    def save_to_file(self) -> Optional[Path]:
        from ..paths import logs_dir

        suggested = logs_dir() / f"console-{time.strftime('%Y%m%d-%H%M%S')}.log"
        path, _ = QFileDialog.getSaveFileName(self, "Save console log", str(suggested), "Log files (*.log *.txt)")
        if not path:
            return None
        Path(path).write_text(self.view.toPlainText(), encoding="utf-8")
        return Path(path)

    def plain_text(self) -> str:
        return self.view.toPlainText()

    # ----------------------------------------------------------------- misc
    def entry_count(self) -> int:
        return len(self._entries)

    def errors(self) -> int:
        return self._counts.get("error", 0)
