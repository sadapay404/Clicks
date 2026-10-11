"""History page: every run, its outcome and its errors."""

from __future__ import annotations

from typing import Any, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...history import clear as clear_history, load as load_history, stats as history_stats
from ...paths import history_file, human_path
from ...timeutil import human_duration
from ..anim import MOTION, fade_in, stagger
from ..widgets.common import (
    AnimatedButton,
    Card,
    EmptyState,
    Pill,
    ScrollPage,
    SegmentControl,
    StatTile,
)


class HistoryPage(ScrollPage):
    def __init__(self, context, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent, margin=22)
        self.ctx = context
        self.rows: list[dict[str, Any]] = []

        self.add(self._build_header())
        self.add(self._build_stats())

        columns = QHBoxLayout()
        columns.setSpacing(16)
        columns.addWidget(self._build_table_card(), 3)
        columns.addWidget(self._build_detail_card(), 2)
        holder = QWidget()
        holder.setLayout(columns)
        self.add(holder, 1)

    # ------------------------------------------------------------------ build
    def _build_header(self) -> QWidget:
        holder = QWidget()
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(6, 0, 0, 0)
        layout.setSpacing(10)
        column = QVBoxLayout()
        column.setSpacing(2)
        title = QLabel("History")
        title.setObjectName("PageTitle")
        column.addWidget(title)
        self.subtitle = QLabel("")
        self.subtitle.setObjectName("PageSubtitle")
        column.addWidget(self.subtitle)
        layout.addLayout(column, 1)

        self.filter = SegmentControl(
            [("all", "All runs"), ("errors", "With errors"), ("stopped", "Stopped")],
            accent=self.ctx.palette.accent,
        )
        self.filter.changed.connect(lambda _key: self.refresh())
        layout.addWidget(self.filter)

        export = AnimatedButton("Export CSV", kind="ghost", icon_text="\u2913")
        export.clicked.connect(self.export_csv)
        layout.addWidget(export)

        clear = AnimatedButton("Clear history", kind="ghost", icon_text="\u232b")
        clear.clicked.connect(self.clear)
        layout.addWidget(clear)
        return holder

    def _build_stats(self) -> QWidget:
        grid = QGridLayout()
        grid.setSpacing(14)
        self.tiles = {
            "runs": StatTile("Total runs", "0", "\u25b6", accent=self.ctx.palette.accent),
            "loops": StatTile("Loops played", "0", "\u21bb", accent=self.ctx.palette.info),
            "success": StatTile("Success rate", "0%", "\u2691", accent=self.ctx.palette.success),
            "time": StatTile("Time automated", "0s", "\u23f1", accent=self.ctx.palette.warning),
        }
        for index, tile in enumerate(self.tiles.values()):
            grid.addWidget(tile, 0, index)
        holder = QWidget()
        holder.setLayout(grid)
        return holder

    def _build_table_card(self) -> QWidget:
        card = Card(padding=14, spacing=10)
        header = QHBoxLayout()
        title = QLabel("Runs")
        title.setProperty("role", "h3")
        header.addWidget(title)
        header.addStretch(1)
        self.count_pill = Pill("0", level="muted")
        header.addWidget(self.count_pill)
        card.layout.addLayout(header)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["When", "Script", "Outcome", "Loops", "Failed", "Duration"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._on_selection)
        self.table.setMinimumHeight(320)
        card.layout.addWidget(self.table, 1)

        self.empty_state = EmptyState(
            "No runs recorded yet",
            "Every playbook execution - manual, scheduled or from the CLI - lands here with its outcome "
            "and error details.",
            glyph="\u21ba",
            accent=self.ctx.palette.accent,
        )
        card.layout.addWidget(self.empty_state)
        return card

    def _build_detail_card(self) -> QWidget:
        card = Card(padding=14, spacing=10)
        title = QLabel("Run details")
        title.setProperty("role", "h3")
        card.layout.addWidget(title)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setProperty("mono", "true")
        self.detail.setMinimumHeight(320)
        card.layout.addWidget(self.detail, 1)
        self.path_label = QLabel("")
        self.path_label.setProperty("role", "faint")
        self.path_label.setWordWrap(True)
        card.layout.addWidget(self.path_label)
        return card

    # ------------------------------------------------------------------- data
    def refresh(self) -> None:
        mode = self.filter.current()
        rows = load_history(limit=500)
        if mode == "errors":
            rows = [row for row in rows if row.get("steps_failed") or row.get("outcome") == "failed"]
        elif mode == "stopped":
            rows = [row for row in rows if row.get("stopped_by_user")]
        self.rows = rows

        stats = history_stats()
        self.tiles["runs"].set_value(str(stats.get("runs", 0)))
        self.tiles["loops"].set_value(str(stats.get("loops", 0)))
        self.tiles["success"].set_value(f"{stats.get('success_rate', 0)}%")
        self.tiles["time"].set_value(human_duration(stats.get("time_spent_seconds", 0)))
        self.tiles["time"].set_hint(f"{stats.get('runs_with_errors', 0)} run(s) had errors")

        self.table.setRowCount(0)
        for row in rows:
            index = self.table.rowCount()
            self.table.insertRow(index)
            outcome = str(row.get("outcome", "unknown")).replace("_", " ")
            values = [
                str(row.get("started_at", ""))[:19].replace("T", " "),
                str(row.get("script", "")),
                outcome,
                str(row.get("loops_completed", 0)),
                str(row.get("steps_failed", 0)),
                str(row.get("duration", "")),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 2:
                    item.setData(Qt.ItemDataRole.UserRole, outcome)
                self.table.setItem(index, column, item)
        self.count_pill.setText(f"{len(rows)} run(s)")
        self.empty_state.setVisible(not rows)
        self.table.setVisible(bool(rows))
        self.subtitle.setText(
            f"History file: {human_path(history_file())}" if rows else "Nothing here yet - results appear after each run."
        )
        if rows:
            self.table.selectRow(0)
        if MOTION.enabled:
            stagger(list(self.tiles.values()), step=50, duration=280)

    def _on_selection(self) -> None:
        indexes = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not indexes:
            return
        row_index = indexes[0].row()
        if row_index >= len(self.rows):
            return
        row = self.rows[row_index]
        lines = [
            f"Script      : {row.get('script')}",
            f"Started     : {row.get('started_at')}",
            f"Finished    : {row.get('finished_at')}",
            f"Duration    : {row.get('duration')}",
            f"Outcome     : {row.get('outcome')}",
            f"Triggered   : {row.get('trigger', 'manual')}",
            f"Loops       : {row.get('loops_completed')} completed / {row.get('loops_attempted', '?')} attempted",
            f"Steps ok    : {row.get('steps_ok')}",
            f"Steps failed: {row.get('steps_failed')}",
        ]
        errors = row.get("errors") or []
        if errors:
            lines.append("")
            lines.append("Errors:")
            lines.extend(f"  \u2022 {error}" for error in errors[:20])
        healed = row.get("healed") or []
        if healed:
            lines.append("")
            lines.append("Healed selectors:")
            lines.extend(f"  \u2022 {item.get('new_selector')} (was {item.get('old_selector')})" for item in healed[:10])
        self.detail.setPlainText("\n".join(str(line) for line in lines))
        if MOTION.enabled:
            fade_in(self.detail, 160)

    def export_csv(self) -> None:
        if not self.rows:
            self.ctx.toast("Nothing to export.", level="warning")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export history", "clicks-auto-history.csv", "CSV (*.csv)")
        if not path:
            return
        import csv

        keys = ["started_at", "script", "outcome", "loops_completed", "steps_ok", "steps_failed",
                "duration", "trigger", "stopped_by_user"]
        with open(path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=keys, extrasaction="ignore")
            writer.writeheader()
            for row in self.rows:
                writer.writerow({key: row.get(key, "") for key in keys})
        self.ctx.toast(f"Exported {len(self.rows)} run(s).", level="success")

    def clear(self) -> None:
        from PyQt6.QtWidgets import QMessageBox

        answer = QMessageBox.question(
            self, "Clear history", "Delete all recorded run history?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        clear_history()
        self.refresh()
        self.ctx.toast("History cleared.", level="info")

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.refresh()

    def apply_palette(self, palette) -> None:
        self.tiles["runs"].set_accent(palette.accent)
        self.tiles["loops"].set_accent(palette.info)
        self.tiles["success"].set_accent(palette.success)
        self.tiles["time"].set_accent(palette.warning)
