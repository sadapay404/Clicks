"""Modal dialogs: welcome, step editor, browser/profile pickers, about."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, APP_URL, __version__
from ..browser import app_profiles, available_profiles, detect_all
from ..models import STEP_CATEGORIES, STEP_TYPES, Step, StepTypeInfo
from ..paths import human_path
from ..store import ScriptStore
from .anim import MOTION, fade_in, stagger
from .theme import Palette
from .widgets.common import AnimatedButton, Card, Divider, Pill

KIND_CHOICES = [
    ("css", "CSS selector"),
    ("xpath", "XPath"),
    ("text", "Text on the page"),
    ("role", "Accessibility role"),
    ("label", "Field label"),
    ("placeholder", "Placeholder text"),
    ("testid", "data-testid"),
    ("alt", "Image alt text"),
    ("title", "Title attribute"),
]


def _title(label: str, text: str) -> QLabel:
    widget = QLabel(text)
    widget.setProperty("role", label)
    return widget


class AnimatedDialog(QDialog):
    """Dialog that fades + rises into place."""

    def __init__(self, parent: Optional[QWidget] = None, *, title: str = "", width: int = 620,
                 height: int = 0, palette: Optional[Palette] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title or APP_NAME)
        self.setModal(True)
        self.resize(width, height or 520)
        if palette is not None:
            self.setStyleSheet(parent.styleSheet() if parent else "")

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if MOTION.enabled:
            fade_in(self, 200)


# --------------------------------------------------------------------------
# Step editor
# --------------------------------------------------------------------------


class StepEditorDialog(AnimatedDialog):
    """Create / edit a single step with a picker for all step types."""

    def __init__(self, parent: Optional[QWidget] = None, *, step: Optional[Step] = None,
                 palette: Optional[Palette] = None, step_types: Optional[dict[str, StepTypeInfo]] = None) -> None:
        super().__init__(parent, title=("Edit step" if step else "Add step"), width=720, height=640,
                         palette=palette)
        self._palette = palette
        self._step = step.clone() if step else Step(type="click")
        self._original_type = self._step.type
        self.step_types = step_types or STEP_TYPES
        self.result_step: Optional[Step] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(13)

        header = QHBoxLayout()
        header.addWidget(_title("h2", "Edit step" if step else "Add a step"))
        header.addStretch(1)
        self.type_pill = Pill(self._step.label, level="info")
        header.addWidget(self.type_pill)
        layout.addLayout(header)

        self.type_combo = QComboBox()
        for category in STEP_CATEGORIES:
            for info in self.step_types.values():
                if info.category == category:
                    self.type_combo.addItem(f"{category}  \u2022  {info.label}", info.key)
        index = self.type_combo.findData(self._step.type)
        if index >= 0:
            self.type_combo.setCurrentIndex(index)
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        layout.addWidget(self.type_combo)

        self.description = QLineEdit(self._step.description)
        self.description.setPlaceholderText("Optional description, e.g. 'Login button'")
        layout.addWidget(self.description)

        form_host = QWidget()
        self.form = QFormLayout(form_host)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setSpacing(10)
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(form_host)
        layout.addStretch(1)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet(f"color: {palette.danger if palette else '#ff6188'};")
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel_button = AnimatedButton("Cancel", kind="ghost")
        self.cancel_button.clicked.connect(self.reject)
        self.save_button = AnimatedButton("Save step", kind="primary",
                                          accent=palette.accent if palette else "#5b8cff")
        self.save_button.clicked.connect(self._save)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.save_button)
        layout.addLayout(buttons)

        self._build_form()

    # ------------------------------------------------------------------ build
    def _current_info(self) -> StepTypeInfo:
        key = self.type_combo.currentData() or self._step.type
        return self.step_types.get(key, self.step_types["note"])

    def _on_type_changed(self, _index: int) -> None:
        self._step.type = self.type_combo.currentData() or self._step.type
        self.type_pill.setText(self._current_info().label)
        self._build_form()

    def _clear_form(self) -> None:
        while self.form.rowCount():
            self.form.removeRow(0)
        self.selector_kind = None
        self.selector_edit = None
        self.selector_index = None
        self.fallbacks_label = None
        self._field_widgets: dict[str, QWidget] = {}

    def _build_form(self) -> None:
        self._clear_form()
        info = self._current_info()
        self._field_widgets = {}

        if info.needs_selector:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            self.selector_kind = QComboBox()
            for key, label in KIND_CHOICES:
                self.selector_kind.addItem(label, key)
            index = self.selector_kind.findData(self._step.selector_kind)
            self.selector_kind.setCurrentIndex(max(0, index))
            row_layout.addWidget(self.selector_kind, 1)
            self.selector_edit = QLineEdit(self._step.selector)
            self.selector_edit.setProperty("mono", "true")
            self.selector_edit.setPlaceholderText("example: #login-button  or  //button[1]")
            row_layout.addWidget(self.selector_edit, 3)
            self.selector_index = QSpinBox()
            self.selector_index.setRange(0, 999)
            self.selector_index.setValue(self._step.selector_index)
            self.selector_index.setToolTip("Which match to use when the selector matches several elements (0 = first)")
            self.selector_index.setPrefix("#")
            row_layout.addWidget(self.selector_index)
            self.form.addRow("Element", row)
            self._field_widgets["selector"] = row

            self.fallbacks_label = QLabel(self._fallbacks_text())
            self.fallbacks_label.setProperty("role", "faint")
            self.fallbacks_label.setWordWrap(True)
            self.form.addRow("Fallbacks", self.fallbacks_label)

        if info.nested:
            self.form.addRow("Nested", _title("faint", "Nested steps are edited in the main step list after saving."))

        for spec in info.params:
            if spec.name in ("value", "url", "ms", "key", "then", "else", "steps", "text"):
                continue  # handled below (value/ui shared fields)
            widget = self._make_widget(spec)
            if widget is not None:
                self.form.addRow(spec.label, widget)
                self._field_widgets[spec.name] = widget

        # generic value field for every type that needs one
        if info.needs_value or info.key in ("goto", "wait", "set_var", "note", "press"):
            label = "Value"
            placeholder = ""
            if info.key == "goto":
                label, placeholder = "URL", "https://example.com"
            elif info.key == "wait":
                label, placeholder = "Milliseconds", "1500"
            elif info.key == "set_var":
                label, placeholder = "Value", "supports ${variables}"
            elif info.key == "note":
                label, placeholder = "Comment", "what is this step for?"
            elif info.key == "press":
                label, placeholder = "Key", "Enter / Control+A"
            else:
                spec = info.spec.get("value")
                if spec:
                    label = spec.label
                    placeholder = spec.placeholder
            if info.key in ("fill", "type", "run_js", "set_var", "note", "upload"):
                widget = QPlainTextEdit(self._step.value)
                widget.setPlaceholderText(placeholder or "supports ${variables}")
                widget.setFixedHeight(76)
                widget.setProperty("mono", "true")
            else:
                widget = QLineEdit(self._step.value)
                widget.setPlaceholderText(placeholder or "supports ${variables}")
                if info.key in ("goto", "press", "wait"):
                    widget.setProperty("mono", "true")
            self.form.addRow(label, widget)
            self._field_widgets["value"] = widget

        hint = QLabel(info.description)
        hint.setProperty("role", "faint")
        hint.setWordWrap(True)
        self.form.addRow("", hint)

    def _make_widget(self, spec) -> Optional[QWidget]:
        current = self._step.options.get(spec.name, spec.default)
        if spec.kind == "select":
            widget = QComboBox()
            for option in spec.options:
                widget.addItem(str(option).replace("_", " "), option)
            index = widget.findData(current)
            widget.setCurrentIndex(max(0, index))
            return widget
        if spec.kind == "checkbox":
            widget = QCheckBox()
            widget.setChecked(bool(current))
            return widget
        if spec.kind == "number":
            widget = QSpinBox()
            widget.setRange(0, 1_000_000)
            try:
                widget.setValue(int(current or 0))
            except (TypeError, ValueError):
                widget.setValue(0)
            return widget
        if spec.kind == "textarea":
            widget = QPlainTextEdit(str(current or ""))
            widget.setFixedHeight(76)
            widget.setProperty("mono", "true")
            return widget
        widget = QLineEdit(str(current if current is not None else ""))
        if spec.kind in ("key", "selector", "file"):
            widget.setProperty("mono", "true")
        return widget

    def _fallbacks_text(self) -> str:
        if not self._step.fallbacks:
            return "No fallback selectors (recorded steps usually have several)."
        lines = [f"{index + 1}. {candidate.display()}" for index, candidate in enumerate(self._step.fallbacks[:5])]
        if len(self._step.fallbacks) > 5:
            lines.append(f"... and {len(self._step.fallbacks) - 5} more")
        return "\n".join(lines)

    # ------------------------------------------------------------------- save
    def _save(self) -> None:
        info = self._current_info()
        step = self._step
        step.type = info.key
        step.description = self.description.text().strip()

        if info.needs_selector and self.selector_edit is not None:
            step.selector = self.selector_edit.text().strip()
            step.selector_kind = self.selector_kind.currentData() or "css"
            step.selector_index = self.selector_index.value()

        value_widget = self._field_widgets.get("value")
        if value_widget is not None:
            if isinstance(value_widget, QPlainTextEdit):
                step.value = value_widget.toPlainText()
            else:
                step.value = value_widget.text()
        for name, widget in self._field_widgets.items():
            if name in ("selector", "value"):
                continue
            if isinstance(widget, QComboBox):
                step.options[name] = widget.currentData()
            elif isinstance(widget, QCheckBox):
                step.options[name] = widget.isChecked()
            elif isinstance(widget, QSpinBox):
                step.options[name] = widget.value()
            elif isinstance(widget, QPlainTextEdit):
                step.options[name] = widget.toPlainText()
            elif isinstance(widget, QLineEdit):
                step.options[name] = widget.text()
        if not step.value and step.options.get("value"):
            step.value = str(step.options.pop("value"))
        if info.key == "wait":
            step.options["ms"] = int(step.value or 1000)

        problems = _validate_step(step)
        if problems:
            self.error_label.setText(" \u2022 ".join(problems))
            self.error_label.setVisible(True)
            if MOTION.enabled:
                fade_in(self.error_label, 200)
            return
        if step.type in ("if_visible", "repeat") and not step.steps and not step.else_steps:
            step.steps = [Step(type="wait", value="500", description="nested placeholder")]
        self.result_step = step
        self.accept()


def _validate_step(step: Step) -> list[str]:
    problems: list[str] = []
    info = STEP_TYPES.get(step.type)
    if info is None:
        return ["Unknown step type"]
    if info.needs_selector and not step.selector:
        problems.append("This step needs an element selector")
    if step.type == "goto" and not step.value:
        problems.append("Enter the URL to open")
    if step.type == "fill" and not step.value:
        problems.append("Enter the text to type")
    return problems


# --------------------------------------------------------------------------
# Profile / browser pickers
# --------------------------------------------------------------------------


class BrowserPickerDialog(AnimatedDialog):
    """Pick browser + profile (used by Run panel 'Advanced' and Settings)."""

    def __init__(self, parent: Optional[QWidget] = None, *, palette: Optional[Palette] = None,
                 current_kind: str = "brave", current_profile: str = "") -> None:
        super().__init__(parent, title="Browser settings", width=640, height=540, palette=palette)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)
        layout.addWidget(_title("h2", "Browser & profile"))

        self.detected = detect_all()
        self.kind_combo = QComboBox()
        labels = {"brave": "Brave", "chrome": "Google Chrome", "edge": "Microsoft Edge",
                  "chromium": "Playwright Chromium", "custom": "Custom executable..."}
        for kind, label in labels.items():
            choice = self.detected.get(kind)
            suffix = f"  \u2713 {shorten_path(choice.path)}" if choice and choice.found else "  \u2717 not found"
            if kind == "custom":
                suffix = ""
            self.kind_combo.addItem(f"{label}{suffix}", kind)
        index = self.kind_combo.findData(current_kind)
        self.kind_combo.setCurrentIndex(max(0, index))
        self.kind_combo.currentIndexChanged.connect(self._refresh_profiles)
        layout.addWidget(QLabel("Browser"))
        layout.addWidget(self.kind_combo)

        layout.addWidget(QLabel("Profile (keeps you signed in)"))
        self.profile_combo = QComboBox()
        layout.addWidget(self.profile_combo)
        self.profile_hint = _title("faint", "")
        self.profile_hint.setWordWrap(True)
        layout.addWidget(self.profile_hint)

        browse_row = QHBoxLayout()
        self.browse_button = AnimatedButton("Browse for a profile folder...", kind="ghost")
        self.browse_button.clicked.connect(self._browse_profile)
        browse_row.addWidget(self.browse_button)
        browse_row.addStretch(1)
        layout.addLayout(browse_row)
        layout.addStretch(1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = AnimatedButton("Cancel", kind="ghost")
        cancel.clicked.connect(self.reject)
        accept = AnimatedButton("Use these settings", kind="primary",
                                accent=palette.accent if palette else "#5b8cff")
        accept.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(accept)
        layout.addLayout(buttons)

        self._refresh_profiles()
        if current_profile:
            index = self.profile_combo.findData(current_profile)
            if index >= 0:
                self.profile_combo.setCurrentIndex(index)

    def _refresh_profiles(self) -> None:
        kind = self.kind_combo.currentData()
        self.profile_combo.clear()
        self.profile_combo.addItem("Clicks-Auto profile (isolated - recommended)", "")
        for path, label in app_profiles():
            self.profile_combo.addItem(f"Saved: {label}", path)
        for path, label in available_profiles(kind):
            self.profile_combo.addItem(f"Use my real {label}", path)
        self.profile_hint.setText(
            "The isolated profile keeps automation logins separate from your daily browsing. "
            "Using your real profile means you are already signed in - but that browser must be closed first."
        )

    def _browse_profile(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select a browser profile folder")
        if path:
            self.profile_combo.addItem(path, path)
            self.profile_combo.setCurrentIndex(self.profile_combo.count() - 1)

    def values(self) -> tuple[str, str]:
        return self.kind_combo.currentData(), self.profile_combo.currentData() or ""


class ScriptPickerDialog(AnimatedDialog):
    """Choose one (or several) scripts from the library."""

    def __init__(self, parent: Optional[QWidget] = None, *, palette: Optional[Palette] = None,
                 multi: bool = False, store: Optional[ScriptStore] = None) -> None:
        super().__init__(parent, title="Choose a script", width=560, height=480, palette=palette)
        self.store = store or ScriptStore()
        self.multi = multi
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)
        layout.addWidget(_title("h2", "Choose a script"))

        self.list = QListWidget()
        self.list.setSelectionMode(
            QListWidget.SelectionMode.MultiSelection if multi else QListWidget.SelectionMode.SingleSelection
        )
        for entry in self.store.list_entries():
            item = QListWidgetItem(f"{entry.display_name}   \u2022   {entry.step_count} steps")
            item.setData(Qt.ItemDataRole.UserRole, str(entry.path))
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)
        self.list.itemDoubleClicked.connect(lambda _item: self.accept())
        layout.addWidget(self.list, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = AnimatedButton("Cancel", kind="ghost")
        cancel.clicked.connect(self.reject)
        accept = AnimatedButton("Select", kind="primary", accent=palette.accent if palette else "#5b8cff")
        accept.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(accept)
        layout.addLayout(buttons)

    def selected_paths(self) -> list[str]:
        return [item.data(Qt.ItemDataRole.UserRole) for item in self.list.selectedItems()]


# --------------------------------------------------------------------------
# Welcome + about
# --------------------------------------------------------------------------


class WelcomeDialog(AnimatedDialog):
    def __init__(self, parent: Optional[QWidget] = None, *, palette: Palette) -> None:
        super().__init__(parent, title=f"Welcome to {APP_NAME}", width=660, height=520, palette=palette)
        layout = self.cards_layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 20)
        layout.setSpacing(14)
        # ``QWidget.layout`` is a method, so keep our own reference for the
        # staggered show animation below.
        self._body_layout = layout

        glyph = QLabel("\u25ce")
        glyph.setObjectName("HeroGlyph")
        glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(glyph)

        heading = QLabel(f"Welcome to {APP_NAME}")
        heading.setObjectName("PageTitle")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(heading)
        subtitle = QLabel("Record web actions once, then replay them as many times as you need.")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setProperty("role", "muted")
        layout.addWidget(subtitle)

        for title, body, glyph_text in [
            ("1. Record a session", "Press Record Session - a Brave window opens and every click, "
                                    "keystroke, dropdown and navigation is captured.", "\u25cf"),
            ("2. Fine tune", "Steps become an editable script: reorder, edit selectors, add waits, "
                             "checks, variables and screenshots.", "\u2637"),
            ("3. Run it", "Run once, N times, for a duration, or forever until you press Stop - "
                          "with live logs the whole way.", "\u25b6"),
        ]:
            card = Card(padding=12, spacing=4)
            row = QHBoxLayout()
            glyph_label = QLabel(glyph_text)
            glyph_label.setStyleSheet(f"color: {palette.accent}; font-size: 17px;")
            row.addWidget(glyph_label, alignment=Qt.AlignmentFlag.AlignTop)
            column = QVBoxLayout()
            column.setSpacing(2)
            heading_label = QLabel(title)
            font = heading_label.font()
            font.setBold(True)
            heading_label.setFont(font)
            column.addWidget(heading_label)
            body_label = QLabel(body)
            body_label.setProperty("role", "muted")
            body_label.setWordWrap(True)
            column.addWidget(body_label)
            row.addLayout(column, 1)
            card.layout.addLayout(row)
            layout.addWidget(card)

        layout.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        close = AnimatedButton("Let's go", kind="primary", accent=palette.accent)
        close.clicked.connect(self.accept)
        row.addWidget(close)
        layout.addLayout(row)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        layout = self.cards_layout
        cards = [layout.itemAt(i).widget() for i in range(layout.count())]
        stagger([w for w in cards if w is not None][:8], step=55, duration=280)


class AboutDialog(AnimatedDialog):
    def __init__(self, parent: Optional[QWidget] = None, *, palette: Palette) -> None:
        super().__init__(parent, title=f"About {APP_NAME}", width=520, height=420, palette=palette)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(12)
        glyph = QLabel("\u25ce")
        glyph.setObjectName("HeroGlyph")
        glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(glyph)
        heading = QLabel(f"{APP_NAME} {__version__}")
        heading.setObjectName("PageTitle")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(heading)
        text = QLabel(
            "A desktop studio for recording and replaying browser automation.\n"
            "Playwright drives a real Brave / Chrome / Edge window; "
            "sessions are recorded at the DOM level and stored as editable JSON scripts."
        )
        text.setWordWrap(True)
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text.setProperty("role", "muted")
        layout.addWidget(text)
        layout.addWidget(Divider())
        link = QLabel(f'<a style="color:{palette.accent}" href="{APP_URL}">{APP_URL}</a>')
        link.setOpenExternalLinks(True)
        link.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(link)
        layout.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        close = AnimatedButton("Close", kind="ghost")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        layout.addLayout(row)


def shorten_path(path: str) -> str:
    text = human_path(path)
    return text if len(text) <= 52 else "\u2026" + text[-49:]
