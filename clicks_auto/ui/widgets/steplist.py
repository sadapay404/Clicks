"""Scrollable, status-aware list of script steps."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...models import Step
from ..anim import MOTION, HoverGlow, fade_in, pulse, stagger
from ..theme import Palette, rgba
from .common import IconButton, Pill, SearchBox

STATE_GLYPHS = {
    "idle": "\u25cb",
    "running": "\u25cf",
    "ok": "\u2713",
    "error": "\u2716",
    "retry": "\u21bb",
    "skipped": "\u2298",
    "disabled": "\u2296",
}


class StepRow(QFrame):
    clicked = pyqtSignal(int)
    activated = pyqtSignal(int)
    move_requested = pyqtSignal(int, int)
    delete_requested = pyqtSignal(int)
    duplicate_requested = pyqtSignal(int)
    edit_requested = pyqtSignal(int)

    def __init__(self, index: int, step: Step, parent: Optional[QWidget] = None,
                 *, palette: Palette, editable: bool = True) -> None:
        super().__init__(parent)
        self.setObjectName("StepRow")
        self.setProperty("state", "disabled" if not step.enabled else "idle")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.index = index
        self.step = step
        self._palette = palette
        self._pulse = None

        self.setMinimumHeight(58)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(12, 9, 10, 9)
        outer.setSpacing(11)

        self.number = QLabel(str(index + 1))
        self.number.setFixedWidth(26)
        self.number.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.number.setStyleSheet(
            f"color: {palette.text_faint}; font-weight: 700; font-size: 12px;"
            f"background: {rgba(palette.text_faint, 0.10)}; border-radius: 9px; padding: 3px 0;"
        )
        outer.addWidget(self.number)

        self.glyph = QLabel(step.info.icon_glyph() if hasattr(step.info, "icon_glyph") else _glyph(step))
        self.glyph.setFixedWidth(22)
        self.glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.glyph.setStyleSheet(f"color: {palette.accent}; font-size: 15px;")
        outer.addWidget(self.glyph)

        column = QVBoxLayout()
        column.setSpacing(2)
        column.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.type_label = QLabel(step.label)
        font = self.type_label.font()
        font.setBold(True)
        self.type_label.setFont(font)
        top.addWidget(self.type_label)
        self.summary = QLabel(step.summary())
        self.summary.setProperty("role", "muted")
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        top.addWidget(self.summary, 1)
        column.addLayout(top)

        self.detail = QLabel(_detail_text(step))
        self.detail.setProperty("role", "faint")
        self.detail.setFont(self.detail.font())
        self.detail.setStyleSheet(f"color: {palette.text_faint}; font-size: 11px;")
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        column.addWidget(self.detail)
        outer.addLayout(column, 1)

        self.state_glyph = QLabel(STATE_GLYPHS["disabled" if not step.enabled else "idle"])
        self.state_glyph.setFixedWidth(18)
        self.state_glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(self.state_glyph)

        self.message = QLabel("")
        self.message.setVisible(False)
        self.message.setWordWrap(True)
        self.message.setProperty("role", "faint")

        self.actions: list[QPushButton] = []
        if editable:
            for glyph, tip, slot in (
                ("\u2191", "Move up", lambda: self.move_requested.emit(self.index, -1)),
                ("\u2193", "Move down", lambda: self.move_requested.emit(self.index, 1)),
                ("\u29c9", "Duplicate", lambda: self.duplicate_requested.emit(self.index)),
                ("\u270e", "Edit", lambda: self.edit_requested.emit(self.index)),
                ("\u2715", "Delete", lambda: self.delete_requested.emit(self.index)),
            ):
                button = IconButton(glyph, tooltip=tip, size=26)
                button.clicked.connect(slot)
                outer.addWidget(button)
                self.actions.append(button)

        self._glow = HoverGlow(self, palette.accent, alpha=26, radius=10)
        self._glow.lower()
        self.installEventFilter(self)

    # ------------------------------------------------------------------ events
    def eventFilter(self, obj, event):  # noqa: N802
        if obj is self:
            if event.type() == QEvent.Type.Enter:
                self._glow.animate_to(True)
            elif event.type() == QEvent.Type.Leave:
                self._glow.animate_to(False)
            elif event.type() == QEvent.Type.Resize:
                self._glow.setGeometry(0, 0, self.width(), self.height())
                self._glow.lower()
            elif event.type() == QEvent.Type.MouseButtonRelease:
                if self.rect().contains(event.position().toPoint()):
                    self.clicked.emit(self.index)
            elif event.type() == QEvent.Type.MouseButtonDblClick:
                self.activated.emit(self.index)
        return super().eventFilter(obj, event)

    # --------------------------------------------------------------------- api
    def set_palette(self, palette: Palette) -> None:
        self._palette = palette
        self._glow.set_color(palette.accent)

    def set_index(self, index: int) -> None:
        self.index = index
        self.number.setText(str(index + 1))

    def set_step(self, step: Step) -> None:
        self.step = step
        self.type_label.setText(step.label)
        self.summary.setText(step.summary())
        self.detail.setText(_detail_text(step))
        self.glyph.setText(step.info.icon_glyph() if hasattr(step.info, "icon_glyph") else _glyph(step))
        if not step.enabled:
            self.set_state("disabled")

    def set_state(self, state: str, message: str = "") -> None:
        self.setProperty("state", state)
        style = self.style()
        if style:
            style.unpolish(self)
            style.polish(self)
        self.state_glyph.setText(STATE_GLYPHS.get(state, "\u25cb"))
        colors = {
            "running": self._palette.accent,
            "ok": self._palette.success,
            "error": self._palette.danger,
            "retry": self._palette.warning,
            "skipped": self._palette.text_faint,
            "disabled": self._palette.text_faint,
            "idle": self._palette.text_faint,
        }
        self.state_glyph.setStyleSheet(f"color: {colors.get(state, self._palette.text_faint)}; font-size: 13px;")
        if message:
            self.message.setText(message)
            self.detail.setText(message[:200])
        if state == "running" and MOTION.enabled:
            if self._pulse is None:
                self._pulse = pulse(self.state_glyph, low=0.25, high=1.0, period=800)
        elif self._pulse is not None:
            self._pulse.stop()
            self._pulse = None
            self.state_glyph.setGraphicsEffect(None)

    def flash(self) -> None:
        if MOTION.enabled:
            fade_in(self, 220)


class StepList(QWidget):
    """Container that owns :class:`StepRow` widgets."""

    step_selected = pyqtSignal(int)
    step_activated = pyqtSignal(int)
    move_requested = pyqtSignal(int, int)
    delete_requested = pyqtSignal(int)
    duplicate_requested = pyqtSignal(int)
    edit_requested = pyqtSignal(int)

    def __init__(self, parent: Optional[QWidget] = None, *, palette: Palette,
                 editable: bool = True, searchable: bool = True) -> None:
        super().__init__(parent)
        self._palette = palette
        self._editable = editable
        self._rows: list[StepRow] = []
        self._selected = -1
        self._query = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        if searchable:
            header = QHBoxLayout()
            header.setContentsMargins(0, 0, 0, 0)
            header.setSpacing(8)
            self.search = SearchBox("Filter steps (type, text, selector)...")
            self.search.textChanged.connect(self._on_search)
            header.addWidget(self.search, 1)
            self.count_pill = Pill("0 steps", level="muted")
            header.addWidget(self.count_pill)
            layout.addLayout(header)

        from ..anim import SmoothScrollArea

        self.scroll = SmoothScrollArea(self)
        self.scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.container = QWidget()
        self.rows_layout = QVBoxLayout(self.container)
        self.rows_layout.setContentsMargins(2, 2, 6, 2)
        self.rows_layout.setSpacing(6)
        self.rows_layout.addStretch(1)
        self.scroll.setWidget(self.container)
        layout.addWidget(self.scroll, 1)

        self.empty_label = QLabel("No steps yet.")
        self.empty_label.setProperty("role", "faint")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty_label)

    # ------------------------------------------------------------------- build
    def populate(self, steps: list[Step], *, animate: bool = True) -> None:
        while self.rows_layout.count() > 1:
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._rows = []
        for index, step in enumerate(steps):
            row = StepRow(index, step, self.container, palette=self._palette, editable=self._editable)
            row.clicked.connect(self._on_row_clicked)
            row.activated.connect(self.step_activated.emit)
            row.move_requested.connect(self.move_requested.emit)
            row.delete_requested.connect(self.delete_requested.emit)
            row.duplicate_requested.connect(self.duplicate_requested.emit)
            row.edit_requested.connect(self.edit_requested.emit)
            self.rows_layout.insertWidget(index, row)
            self._rows.append(row)
        self._update_count()
        self._apply_filter()
        self.empty_label.setVisible(not steps)
        if animate and MOTION.enabled:
            stagger(self._rows[:10], step=26, duration=200)

    def refresh_row(self, index: int, step: Step) -> None:
        if 0 <= index < len(self._rows):
            self._rows[index].set_step(step)

    def set_state(self, index: int, state: str, message: str = "") -> None:
        if 0 <= index < len(self._rows):
            self._rows[index].set_state(state, message)

    def reset_states(self) -> None:
        for row in self._rows:
            row.set_state("disabled" if not row.step.enabled else "idle", "")

    def select(self, index: int, *, scroll: bool = True, animate: bool = True) -> None:
        self._selected = index
        for position, row in enumerate(self._rows):
            row.setProperty("selected", "true" if position == index else "false")
            row.style().unpolish(row)
            row.style().polish(row)
        if scroll and 0 <= index < len(self._rows):
            row = self._rows[index]
            target = row.y() - 40
            if animate and MOTION.enabled:
                self.scroll.animate_to(max(0, target), 320)
            else:
                self.scroll.verticalScrollBar().setValue(max(0, target))
        self.step_selected.emit(index)

    def scroll_to_step(self, index: int, *, animated: bool = True) -> None:
        if 0 <= index < len(self._rows):
            row = self._rows[index]
            target = row.y() - max(0, (self.scroll.viewport().height() - row.height()) // 2)
            if animated and MOTION.enabled:
                self.scroll.animate_to(max(0, target), 360)
            else:
                self.scroll.verticalScrollBar().setValue(max(0, target))

    def selected(self) -> int:
        return self._selected

    def rows(self) -> list[StepRow]:
        return self._rows

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette
        for row in self._rows:
            row.set_palette(palette)

    # ------------------------------------------------------------------ filter
    def _on_search(self, text: str) -> None:
        self._query = text.strip().lower()
        self._apply_filter()

    def _apply_filter(self) -> None:
        shown = 0
        for row in self._rows:
            haystack = f"{row.step.type} {row.step.label} {row.step.summary()} {row.step.description} {row.step.selector}".lower()
            visible = not self._query or self._query in haystack
            row.setVisible(visible)
            shown += int(visible)
        if hasattr(self, "count_pill"):
            total = len(self._rows)
            self.count_pill.setText(f"{shown}/{total} steps" if shown != total else f"{total} steps")

    def _update_count(self) -> None:
        if hasattr(self, "count_pill"):
            self.count_pill.setText(f"{len(self._rows)} steps")

    def _on_row_clicked(self, index: int) -> None:
        self.select(index, scroll=False, animate=False)


# --------------------------------------------------------------------- helpers


def _glyph(step: Step) -> str:
    return {
        "goto": "\u25c8", "click": "\u25b8", "fill": "\u2338", "type": "\u2328",
        "select": "\u2630", "check": "\u2713", "wait": "\u25f4", "screenshot": "\u25f1",
        "assert_text": "\u2261", "press": "\u21b5", "hover": "\u2723", "scroll": "\u21c5",
        "repeat": "\u21bb", "if_visible": "\u2440", "note": "\u270e", "extract": "\u2193",
        "upload": "\u21e7", "new_tab": "\uff0b", "switch_tab": "\u21c4", "close_tab": "\u2715",
        "wait_for": "\u231b", "set_var": "\u2261", "run_js": "\u2632", "reload": "\u21bb",
        "go_back": "\u2190", "go_forward": "\u2192", "clear": "\u2327", "dblclick": "\u2352",
        "assert_url": "\u224b", "assert_visible": "\u25c9", "dialog": "\u26a0", "uncheck": "\u2610",
    }.get(step.type, "\u2022")


def _detail_text(step: Step) -> str:
    parts: list[str] = []
    if step.selector:
        kind = "" if step.selector_kind == "css" else f"{step.selector_kind}="
        parts.append(f"{kind}{step.selector}")
        if len(step.fallbacks) and step.fallbacks:
            parts.append(f"+{len(step.fallbacks)} fallback")
    if step.description and step.description not in step.summary():
        parts.append(step.description)
    if step.type == "note":
        parts = [str(step.parameter("text", ""))]
    return "   ".join(part for part in parts if part)[:220]
