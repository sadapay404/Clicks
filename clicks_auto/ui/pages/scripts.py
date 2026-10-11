"""Scripts page: library browser + full step editor + raw JSON view."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ...models import Script, Step, new_id
from ...paths import human_path
from ...timeutil import human_duration
from ..anim import MOTION, fade_in
from ..dialogs import StepEditorDialog
from ..widgets.common import (
    AnimatedButton,
    Card,
    EmptyState,
    Pill,
    ScrollPage,
    SearchBox,
    SegmentControl,
)
from ..widgets.steplist import StepList


class ScriptsPage(ScrollPage):
    run_requested = pyqtSignal(str)

    def __init__(self, context, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent, margin=20)
        self.ctx = context
        self.script: Optional[Script] = None
        self.path: Optional[Path] = None
        self.dirty = False

        self.add(self._build_header())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_library_card())
        splitter.addWidget(self._build_editor_card())
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 5)
        splitter.setSizes([300, 780])
        self.add(splitter, 1)

    # ------------------------------------------------------------------ build
    def _build_header(self) -> QWidget:
        holder = QWidget()
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(6, 0, 6, 0)
        layout.setSpacing(10)
        column = QVBoxLayout()
        column.setSpacing(2)
        title = QLabel("Scripts")
        title.setObjectName("PageTitle")
        column.addWidget(title)
        subtitle = QLabel("Every recorded session is a plain JSON file you can edit, copy or share.")
        subtitle.setObjectName("PageSubtitle")
        column.addWidget(subtitle)
        layout.addLayout(column, 1)

        self.view_segment = SegmentControl([("steps", "Steps"), ("json", "JSON")],
                                           accent=self.ctx.palette.accent)
        self.view_segment.changed.connect(self._on_view_changed)
        layout.addWidget(self.view_segment)

        self.new_button = AnimatedButton("New", kind="ghost", icon_text="\uff0b")
        self.new_button.clicked.connect(self.new_script)
        layout.addWidget(self.new_button)

        self.import_button = AnimatedButton("Import", kind="ghost", icon_text="\u2913")
        self.import_button.clicked.connect(self.import_script)
        layout.addWidget(self.import_button)

        self.save_button = AnimatedButton("Save", kind="primary", icon_text="\U0001f4be",
                                          accent=self.ctx.palette.accent)
        self.save_button.clicked.connect(lambda: self.save_script())
        layout.addWidget(self.save_button)

        self.run_button = AnimatedButton("Run", kind="success", icon_text="\u25b6",
                                         accent=self.ctx.palette.success)
        self.run_button.clicked.connect(self._run)
        layout.addWidget(self.run_button)
        return holder

    def _build_library_card(self) -> QWidget:
        card = Card(padding=14, spacing=10)
        header = QHBoxLayout()
        title = QLabel("Library")
        title.setProperty("role", "h3")
        header.addWidget(title)
        header.addStretch(1)
        self.library_pill = Pill("0", level="muted")
        header.addWidget(self.library_pill)
        card.layout.addLayout(header)

        self.library_search = SearchBox("Search scripts...")
        self.library_search.textChanged.connect(lambda _text: self.refresh_library())
        card.layout.addWidget(self.library_search)

        self.library_list = QListWidget()
        self.library_list.currentItemChanged.connect(self._on_library_selection)
        card.layout.addWidget(self.library_list, 1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        refresh = AnimatedButton("Refresh", kind="ghost", icon_text="\u21bb")
        refresh.clicked.connect(self.refresh_library)
        actions.addWidget(refresh)
        duplicate = AnimatedButton("Duplicate", kind="ghost", icon_text="\u29c9")
        duplicate.clicked.connect(self.duplicate_script)
        actions.addWidget(duplicate)
        delete = AnimatedButton("Delete", kind="ghost", icon_text="\u2715")
        delete.clicked.connect(self.delete_script)
        actions.addWidget(delete)
        actions.addStretch(1)
        card.layout.addLayout(actions)

        open_folder = AnimatedButton("Open scripts folder", kind="flat")
        open_folder.clicked.connect(self._open_folder)
        card.layout.addWidget(open_folder)
        return card

    def _build_editor_card(self) -> QWidget:
        card = Card(padding=16, spacing=12)

        self.empty_state = EmptyState(
            "No script selected",
            "Pick one from the library on the left, record a new session, or create a script by hand.",
            glyph="\u2637",
            action_text="Record a session",
            on_action=lambda: self.ctx.goto("recorder"),
            accent=self.ctx.palette.accent,
        )
        card.layout.addWidget(self.empty_state)

        self.editor = QWidget()
        editor_layout = QVBoxLayout(self.editor)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(12)

        details = QHBoxLayout()
        details.setSpacing(10)
        name_column = QVBoxLayout()
        name_column.setSpacing(4)
        name_column.addWidget(QLabel("Name"))
        self.name_edit = QLineEdit()
        self.name_edit.textChanged.connect(self._mark_dirty)
        name_column.addWidget(self.name_edit)
        details.addLayout(name_column, 3)

        url_column = QVBoxLayout()
        url_column.setSpacing(4)
        url_column.addWidget(QLabel("Start URL"))
        self.url_edit = QLineEdit()
        self.url_edit.textChanged.connect(self._mark_dirty)
        url_column.addWidget(self.url_edit)
        details.addLayout(url_column, 4)
        editor_layout.addLayout(details)

        desc_column = QVBoxLayout()
        desc_column.setSpacing(4)
        desc_column.addWidget(QLabel("Description"))
        self.desc_edit = QLineEdit()
        self.desc_edit.textChanged.connect(self._mark_dirty)
        desc_column.addWidget(self.desc_edit)
        editor_layout.addLayout(desc_column)

        self.tabs = SegmentControl([("steps", "Steps"), ("settings", "Settings"),
                                    ("variables", "Variables"), ("json", "JSON")],
                                   accent=self.ctx.palette.accent)
        self.tabs.changed.connect(self._on_tab_changed)
        editor_layout.addWidget(self.tabs)

        from PyQt6.QtWidgets import QStackedWidget

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_steps_tab())
        self.stack.addWidget(self._build_settings_tab())
        self.stack.addWidget(self._build_variables_tab())
        self.stack.addWidget(self._build_json_tab())
        editor_layout.addWidget(self.stack, 1)

        footer = QHBoxLayout()
        footer.setSpacing(10)
        self.status_label = QLabel("")
        self.status_label.setProperty("role", "faint")
        footer.addWidget(self.status_label, 1)
        self.validate_button = AnimatedButton("Validate", kind="ghost", icon_text="\u2713")
        self.validate_button.clicked.connect(self.validate_script)
        footer.addWidget(self.validate_button)
        self.export_button = AnimatedButton("Export...", kind="ghost", icon_text="\u2913")
        self.export_button.clicked.connect(self.export_script)
        footer.addWidget(self.export_button)
        self.save_as_button = AnimatedButton("Save as...", kind="ghost")
        self.save_as_button.clicked.connect(self.save_script_as)
        footer.addWidget(self.save_as_button)
        editor_layout.addLayout(footer)

        card.layout.addWidget(self.editor)
        self.editor.setVisible(False)
        return card

    def _build_steps_tab(self) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(10)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.add_button = AnimatedButton("Add step", kind="primary", icon_text="\uff0b",
                                         accent=self.ctx.palette.accent)
        self.add_button.clicked.connect(self.add_step)
        toolbar.addWidget(self.add_button)
        self.add_wait_button = AnimatedButton("Add wait", kind="ghost", icon_text="\u231b")
        self.add_wait_button.clicked.connect(lambda: self.add_step(preferred="wait"))
        toolbar.addWidget(self.add_wait_button)
        self.add_assert_button = AnimatedButton("Add check", kind="ghost", icon_text="\u2713")
        self.add_assert_button.clicked.connect(lambda: self.add_step(preferred="assert_text"))
        toolbar.addWidget(self.add_assert_button)
        toolbar.addStretch(1)
        self.steps_pill = Pill("0 steps", level="muted")
        toolbar.addWidget(self.steps_pill)
        layout.addLayout(toolbar)

        self.step_list = StepList(holder, palette=self.ctx.palette, editable=True, searchable=True)
        self.step_list.step_activated.connect(self.edit_step)
        self.step_list.edit_requested.connect(self.edit_step)
        self.step_list.delete_requested.connect(self.delete_step)
        self.step_list.duplicate_requested.connect(self.duplicate_step)
        self.step_list.move_requested.connect(self.move_step)
        self.step_list.step_selected.connect(self._on_step_selected)
        layout.addWidget(self.step_list, 1)
        return holder

    def _build_settings_tab(self) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(12)

        card = Card(tone="alt", padding=14, spacing=10)
        card.layout.addWidget(QLabel("Timeouts and retries for this script"))
        grid = QHBoxLayout()
        grid.setSpacing(16)
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(1000, 600_000)
        self.timeout_spin.setSingleStep(1000)
        self.timeout_spin.setSuffix(" ms")
        self.timeout_spin.valueChanged.connect(self._mark_dirty)
        grid.addWidget(QLabel("Step timeout"))
        grid.addWidget(self.timeout_spin)

        self.nav_timeout_spin = QSpinBox()
        self.nav_timeout_spin.setRange(1000, 900_000)
        self.nav_timeout_spin.setSingleStep(1000)
        self.nav_timeout_spin.setSuffix(" ms")
        self.nav_timeout_spin.valueChanged.connect(self._mark_dirty)
        grid.addWidget(QLabel("Navigation timeout"))
        grid.addWidget(self.nav_timeout_spin)

        self.retries_spin = QSpinBox()
        self.retries_spin.setRange(0, 10)
        self.retries_spin.valueChanged.connect(self._mark_dirty)
        grid.addWidget(QLabel("Retries per step"))
        grid.addWidget(self.retries_spin)
        grid.addStretch(1)
        card.layout.addLayout(grid)

        grid2 = QHBoxLayout()
        grid2.setSpacing(16)
        self.retry_delay_spin = QSpinBox()
        self.retry_delay_spin.setRange(0, 30_000)
        self.retry_delay_spin.setSingleStep(100)
        self.retry_delay_spin.setSuffix(" ms")
        self.retry_delay_spin.valueChanged.connect(self._mark_dirty)
        grid2.addWidget(QLabel("Retry delay"))
        grid2.addWidget(self.retry_delay_spin)

        self.step_delay_spin = QSpinBox()
        self.step_delay_spin.setRange(0, 60_000)
        self.step_delay_spin.setSingleStep(50)
        self.step_delay_spin.setSuffix(" ms")
        self.step_delay_spin.valueChanged.connect(self._mark_dirty)
        grid2.addWidget(QLabel("Pause between steps"))
        grid2.addWidget(self.step_delay_spin)

        self.loop_delay_spin = QSpinBox()
        self.loop_delay_spin.setRange(0, 600_000)
        self.loop_delay_spin.setSingleStep(100)
        self.loop_delay_spin.setSuffix(" ms")
        self.loop_delay_spin.valueChanged.connect(self._mark_dirty)
        grid2.addWidget(QLabel("Pause between loops"))
        grid2.addWidget(self.loop_delay_spin)
        grid2.addStretch(1)
        card.layout.addLayout(grid2)
        layout.addWidget(card)

        info = QLabel(
            "Step level overrides win over these defaults. Leave a step's timeout empty to inherit "
            "the value above. Retries make playback resilient to slow pages and animations."
        )
        info.setWordWrap(True)
        info.setProperty("role", "muted")
        layout.addWidget(info)
        layout.addStretch(1)
        return holder

    def _build_variables_tab(self) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(10)
        info = QLabel(
            "One per line as name=value. Use ${name} inside any step. "
            "Built-ins: ${__loop__}, ${__date__}, ${__time__}, ${__timestamp__} and every CSV column."
        )
        info.setWordWrap(True)
        info.setProperty("role", "muted")
        layout.addWidget(info)
        self.variables_edit = QPlainTextEdit()
        self.variables_edit.setPlaceholderText("username=alice\npassword=supersecret\nsearch_term=automation")
        self.variables_edit.setProperty("mono", "true")
        self.variables_edit.textChanged.connect(self._mark_dirty)
        layout.addWidget(self.variables_edit, 1)
        return holder

    def _build_json_tab(self) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(10)
        self.json_edit = QPlainTextEdit()
        self.json_edit.setProperty("mono", "true")
        layout.addWidget(self.json_edit, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        format_button = AnimatedButton("Reformat", kind="ghost")
        format_button.clicked.connect(self._format_json)
        row.addWidget(format_button)
        revert = AnimatedButton("Reload from script", kind="ghost")
        revert.clicked.connect(self._load_json)
        row.addWidget(revert)
        apply_button = AnimatedButton("Apply JSON", kind="primary", icon_text="\u2713",
                                      accent=self.ctx.palette.accent)
        apply_button.clicked.connect(self._apply_json)
        row.addWidget(apply_button)
        layout.addLayout(row)
        return holder

    # ---------------------------------------------------------------- library
    def refresh_library(self) -> None:
        query = self.library_search.text().strip().lower()
        self.library_list.blockSignals(True)
        self.library_list.clear()
        entries = self.ctx.store.list_entries()
        for entry in entries:
            if query and query not in entry.display_name.lower():
                continue
            item = QListWidgetItem(f"{entry.display_name}\n{entry.step_count} steps \u2022 {entry.updated_at[:16]}")
            item.setData(Qt.ItemDataRole.UserRole, str(entry.path))
            self.library_list.addItem(item)
        self.library_list.blockSignals(False)
        self.library_pill.setText(f"{len(entries)} script(s)")
        if self.path is not None:
            for row in range(self.library_list.count()):
                item = self.library_list.item(row)
                if item.data(Qt.ItemDataRole.UserRole) == str(self.path):
                    self.library_list.setCurrentItem(item)
                    break

    def _on_library_selection(self, current: Optional[QListWidgetItem], _previous=None) -> None:
        if current is None:
            return
        path = Path(current.data(Qt.ItemDataRole.UserRole))
        if self.path is not None and self.dirty and path != self.path:
            answer = QMessageBox.question(
                self, "Unsaved changes",
                f"Save changes to '{self.script.name if self.script else self.path.name}' before switching?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                self.refresh_library()
                return
            if answer == QMessageBox.StandardButton.Save:
                self.save_script()
        self.load_script(path)

    def load_script(self, path: Path) -> None:
        try:
            script = self.ctx.store.load(path)
        except Exception as exc:  # noqa: BLE001
            self.ctx.toast(f"Could not open {path.name}: {exc}", level="error")
            return
        self.script = script
        self.path = Path(path)
        self.dirty = False
        self._populate_editor()
        self.empty_state.setVisible(False)
        self.editor.setVisible(True)
        if MOTION.enabled:
            fade_in(self.editor, 220)

    def new_script(self) -> None:
        script = Script(name="New script", description="Created by hand", source="manual")
        path = self.ctx.store.save(script, self.ctx.store.unique_path_for("New script"))
        self.refresh_library()
        self.load_script(path)
        self.ctx.toast("New script created - add some steps.", level="success")

    def duplicate_script(self) -> None:
        if self.script is None:
            return
        path = self.ctx.store.save_copy(self.script, f"{self.script.name} (copy)")
        self.refresh_library()
        self.load_script(path)
        self.ctx.toast(f"Duplicated to {path.name}.", level="success")

    def delete_script(self) -> None:
        if self.path is None:
            return
        answer = QMessageBox.question(
            self, "Delete script",
            f"Move '{self.path.name}' to the _deleted folder?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.ctx.store.delete(self.path)
        self.path = None
        self.script = None
        self.editor.setVisible(False)
        self.empty_state.setVisible(True)
        self.refresh_library()
        self.ctx.toast("Script deleted.", level="info")

    def import_script(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import a script", "", "Clicks-Auto scripts (*.json)")
        if not path:
            return
        try:
            script, target = self.ctx.store.import_file(path)
        except Exception as exc:  # noqa: BLE001
            self.ctx.toast(f"Import failed: {exc}", level="error")
            return
        self.refresh_library()
        self.load_script(target)
        self.ctx.toast(f"Imported '{script.name}'.", level="success")

    def export_script(self) -> None:
        if self.script is None:
            return
        suggested = self.path.name if self.path else f"{self.script.name}.json"
        path, _ = QFileDialog.getSaveFileName(self, "Export script", suggested, "JSON (*.json)")
        if not path:
            return
        self.ctx.store.export_file(self.script, path)
        self.ctx.toast(f"Exported to {human_path(path)}", level="success")

    def _open_folder(self) -> None:
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.ctx.store.dir)))

    # ----------------------------------------------------------------- editor
    def _populate_editor(self) -> None:
        if self.script is None:
            return
        script = self.script
        for widget in (self.name_edit, self.url_edit, self.desc_edit):
            widget.blockSignals(True)
        self.name_edit.setText(script.name)
        self.url_edit.setText(script.start_url)
        self.desc_edit.setText(script.description)
        for widget in (self.name_edit, self.url_edit, self.desc_edit):
            widget.blockSignals(False)

        defaults = script.defaults
        for spin, value in (
            (self.timeout_spin, defaults.step_timeout_ms),
            (self.nav_timeout_spin, defaults.navigation_timeout_ms),
            (self.retries_spin, defaults.retries),
            (self.retry_delay_spin, defaults.retry_delay_ms),
            (self.step_delay_spin, defaults.delay_between_steps_ms),
            (self.loop_delay_spin, defaults.delay_between_loops_ms),
        ):
            spin.blockSignals(True)
            spin.setValue(int(value))
            spin.blockSignals(False)

        self.variables_edit.blockSignals(True)
        self.variables_edit.setPlainText(
            "\n".join(f"{key}={value}" for key, value in script.variables.items())
        )
        self.variables_edit.blockSignals(False)

        self.step_list.populate(script.steps)
        self._update_steps_pill()
        self._load_json()
        self._update_status()

    def _update_steps_pill(self) -> None:
        if self.script is None:
            return
        problems = self.script.validate()
        if problems:
            self.steps_pill.set_level("warning", f"{len(problems)} issue(s)")
        else:
            self.steps_pill.set_level("success", f"{self.script.step_count} steps")

    def _update_status(self) -> None:
        if self.script is None:
            return
        parts = [
            f"{len(self.script.steps)} top-level steps",
            f"~{human_duration(self.script.estimated_seconds())} per loop",
        ]
        if self.path:
            parts.append(f"file: {self.path.name}")
        if self.dirty:
            parts.append("unsaved changes")
        variables = self.script.used_variables()
        if variables:
            parts.append("vars: " + ", ".join(variables[:5]))
        self.status_label.setText("  \u2022  ".join(parts))

    def _mark_dirty(self, *args) -> None:
        if self.script is None:
            return
        self.dirty = True
        self._sync_from_fields()
        self._update_status()

    def _sync_from_fields(self) -> None:
        if self.script is None:
            return
        self.script.name = self.name_edit.text().strip() or "Untitled script"
        self.script.start_url = self.url_edit.text().strip()
        self.script.description = self.desc_edit.text().strip()
        self.script.defaults.step_timeout_ms = self.timeout_spin.value()
        self.script.defaults.navigation_timeout_ms = self.nav_timeout_spin.value()
        self.script.defaults.retries = self.retries_spin.value()
        self.script.defaults.retry_delay_ms = self.retry_delay_spin.value()
        self.script.defaults.delay_between_steps_ms = self.step_delay_spin.value()
        self.script.defaults.delay_between_loops_ms = self.loop_delay_spin.value()
        self.script.variables = self._parse_variables()

    def _parse_variables(self) -> dict[str, str]:
        variables: dict[str, str] = {}
        for line in self.variables_edit.toPlainText().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                variables[key.strip()] = value.strip()
            else:
                variables[line] = ""
        return variables

    def _on_tab_changed(self, key: str) -> None:
        index = {"steps": 0, "settings": 1, "variables": 2, "json": 3}.get(key, 0)
        self.stack.setCurrentIndex(index)
        if key == "json":
            self._load_json()
        if MOTION.enabled:
            fade_in(self.stack.currentWidget(), 200)

    def _on_view_changed(self, key: str) -> None:
        self._on_tab_changed(key)

    # ------------------------------------------------------------------ steps
    def _selected_step_index(self) -> int:
        return self.step_list.selected()

    def add_step(self, *, preferred: Optional[str] = None) -> None:
        if self.script is None:
            return
        template = Step(type=preferred) if preferred else None
        dialog = StepEditorDialog(self.ctx.window or self, step=template, palette=self.ctx.palette)
        if dialog.exec() and dialog.result_step is not None:
            index = self._selected_step_index()
            position = len(self.script.steps) if index < 0 else index + 1
            self.script.steps.insert(position, dialog.result_step)
            self._after_steps_changed(select=position)

    def edit_step(self, index: int) -> None:
        if self.script is None or not (0 <= index < len(self.script.steps)):
            return
        dialog = StepEditorDialog(self.ctx.window or self, step=self.script.steps[index],
                                  palette=self.ctx.palette)
        if dialog.exec() and dialog.result_step is not None:
            self.script.steps[index] = dialog.result_step
            self._after_steps_changed(select=index)

    def delete_step(self, index: int) -> None:
        if self.script is None or not (0 <= index < len(self.script.steps)):
            return
        step = self.script.steps.pop(index)
        self._after_steps_changed(select=min(index, len(self.script.steps) - 1))
        self.ctx.toast(f"Removed '{step.label}'.", level="info")

    def duplicate_step(self, index: int) -> None:
        if self.script is None or not (0 <= index < len(self.script.steps)):
            return
        clone = self.script.steps[index].clone()
        clone.id = new_id('s')
        self.script.steps.insert(index + 1, clone)
        self._after_steps_changed(select=index + 1)

    def move_step(self, index: int, delta: int) -> None:
        if self.script is None:
            return
        target = index + delta
        if not (0 <= index < len(self.script.steps)) or not (0 <= target < len(self.script.steps)):
            return
        steps = self.script.steps
        steps[index], steps[target] = steps[target], steps[index]
        self._after_steps_changed(select=target)

    def _after_steps_changed(self, *, select: int = -1) -> None:
        self.dirty = True
        if self.script is not None:
            self.step_list.populate(self.script.steps, animate=True)
            if select >= 0:
                self.step_list.select(select, scroll=True)
        self._update_steps_pill()
        self._update_status()
        self._load_json()

    def _on_step_selected(self, _index: int) -> None:
        pass

    # ------------------------------------------------------------------- json
    def _load_json(self) -> None:
        if self.script is None:
            return
        self.json_edit.blockSignals(True)
        self.json_edit.setPlainText(self.script.to_json())
        self.json_edit.blockSignals(False)

    def _format_json(self) -> None:
        try:
            data = json.loads(self.json_edit.toPlainText())
        except json.JSONDecodeError as exc:
            self.ctx.toast(f"Invalid JSON: {exc}", level="error")
            return
        self.json_edit.setPlainText(json.dumps(data, indent=2, ensure_ascii=False))
        self.ctx.toast("Reformatted.", level="success")

    def _apply_json(self) -> None:
        try:
            script = Script.from_dict(json.loads(self.json_edit.toPlainText()))
        except Exception as exc:  # noqa: BLE001
            self.ctx.toast(f"Could not apply JSON: {exc}", level="error")
            return
        script.id = self.script.id if self.script else script.id
        self.script = script
        self.dirty = True
        self._populate_editor()
        self.ctx.toast("JSON applied to the script.", level="success")

    # ------------------------------------------------------------------ tools
    def validate_script(self) -> None:
        if self.script is None:
            return
        self._sync_from_fields()
        problems = self.script.validate()
        if problems:
            self.ctx.toast(" \u2022 ".join(problems[:2]), level="warning",
                           title=f"{len(problems)} problem(s) found")
            self.status_label.setText(" \u2022 ".join(problems[:3]))
        else:
            self.ctx.toast(f"{self.script.step_count} steps look good.", level="success")

    def save_script(self, *, quiet: bool = False) -> Optional[Path]:
        if self.script is None:
            return None
        self._sync_from_fields()
        target = self.path or self.ctx.store.unique_path_for(self.script.name)
        self.ctx.store.save(self.script, target)
        self.path = target
        self.dirty = False
        self.refresh_library()
        self._update_status()
        if not quiet:
            self.ctx.toast(f"Saved '{self.script.name}'.", level="success")
        return target

    def save_script_as(self) -> None:
        if self.script is None:
            return
        from PyQt6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(self, "Save as", "New name:", text=f"{self.script.name} (copy)")
        if not ok or not name.strip():
            return
        self.script.name = name.strip()
        self.name_edit.setText(self.script.name)
        self.path = self.ctx.store.unique_path_for(self.script.name)
        self.save_script()

    def _run(self) -> None:
        if self.script is None:
            return
        self.save_script(quiet=True)
        if self.path:
            self.ctx.settings.last_script = str(self.path)
            self.ctx.save()
            self.run_requested.emit(str(self.path))
            self.ctx.goto("run")

    # ------------------------------------------------------------------ misc
    def apply_palette(self, palette) -> None:
        self.step_list.set_palette(palette)
        self.save_button.set_accent(palette.accent)
        self.run_button.set_accent(palette.success)
        self.add_button.set_accent(palette.accent)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.refresh_library()

    def open_script(self, path: str | Path) -> None:
        target = Path(path)
        if target.exists():
            self.load_script(target)
            self.refresh_library()
