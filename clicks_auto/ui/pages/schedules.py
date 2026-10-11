"""Schedules page: run scripts automatically at a time of day or every N minutes."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...scheduler import WEEKDAYS, Schedule
from ...timeutil import countdown, human_datetime
from ..anim import MOTION, fade_in
from ..widgets.common import (
    AnimatedButton,
    Card,
    EmptyState,
    ScrollPage,
    ToggleSwitch,
)


class ScheduleDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None, *, schedule: Optional[Schedule] = None,
                 scripts: list[tuple[str, str]] | None = None, palette=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Schedule")
        self.setModal(True)
        self.resize(520, 420)
        self.schedule = schedule or Schedule()
        self.scripts = scripts or []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)
        title = QLabel("Edit schedule" if schedule else "New schedule")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        form = QFormLayout()
        form.setSpacing(10)
        self.name_edit = QLineEdit(self.schedule.name)
        form.addRow("Name", self.name_edit)

        self.script_combo = QComboBox()
        for label, path in self.scripts:
            self.script_combo.addItem(label, path)
        index = self.script_combo.findData(self.schedule.script_path)
        if index >= 0:
            self.script_combo.setCurrentIndex(index)
        form.addRow("Script", self.script_combo)

        self.mode = QComboBox()
        for key, label in (("once", "Once"), ("daily", "Every day"), ("weekly", "Certain weekdays"),
                           ("interval", "Every N minutes")):
            self.mode.addItem(label, key)
        index = self.mode.findData(self.schedule.mode)
        self.mode.setCurrentIndex(max(0, index))
        self.mode.currentIndexChanged.connect(self._update_visibility)
        form.addRow("Repeat", self.mode)

        self.time_edit = QLineEdit(self.schedule.time_of_day)
        self.time_edit.setPlaceholderText("HH:MM, e.g. 09:30")
        form.addRow("Time", self.time_edit)

        self.days_row = QWidget()
        days_layout = QHBoxLayout(self.days_row)
        days_layout.setContentsMargins(0, 0, 0, 0)
        days_layout.setSpacing(4)
        self.day_buttons: dict[str, ToggleSwitch] = {}
        for day in WEEKDAYS:
            holder = QWidget()
            holder_layout = QVBoxLayout(holder)
            holder_layout.setContentsMargins(0, 0, 0, 0)
            holder_layout.setSpacing(2)
            switch = ToggleSwitch(checked=day in self.schedule.days, accent=palette.accent if palette else "#5b8cff",
                                  track_off=palette.border if palette else "#333")
            switch.setFixedSize(34, 20)
            label = QLabel(day.capitalize()[:2])
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setProperty("role", "faint")
            holder_layout.addWidget(switch, alignment=Qt.AlignmentFlag.AlignCenter)
            holder_layout.addWidget(label)
            days_layout.addWidget(holder)
            self.day_buttons[day] = switch
        form.addRow("Days", self.days_row)

        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 1440)
        self.interval_spin.setSuffix(" min")
        self.interval_spin.setValue(self.schedule.interval_minutes)
        form.addRow("Interval", self.interval_spin)

        self.loop_combo = QComboBox()
        for key, label in (("count", "Repeat N times"), ("infinite", "Until stopped"), ("duration", "Duration")):
            self.loop_combo.addItem(label, key)
        index = self.loop_combo.findData(self.schedule.loop_mode)
        self.loop_combo.setCurrentIndex(max(0, index))
        form.addRow("Loops", self.loop_combo)

        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 100000)
        self.count_spin.setValue(self.schedule.loop_count)
        form.addRow("Repetitions", self.count_spin)

        self.headless_toggle = ToggleSwitch(checked=self.schedule.headless,
                                            accent=palette.accent if palette else "#5b8cff",
                                            track_off=palette.border if palette else "#333")
        form.addRow("Run headless", self.headless_toggle)
        layout.addLayout(form)
        layout.addStretch(1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = AnimatedButton("Cancel", kind="ghost")
        cancel.clicked.connect(self.reject)
        save = AnimatedButton("Save", kind="primary", accent=palette.accent if palette else "#5b8cff")
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)
        self._update_visibility()

    def _update_visibility(self) -> None:
        mode = self.mode.currentData()
        self.time_edit.setVisible(mode in ("once", "daily", "weekly"))
        self.days_row.setVisible(mode == "weekly")
        self.interval_spin.setVisible(mode == "interval")

    def _save(self) -> None:
        schedule = self.schedule
        schedule.name = self.name_edit.text().strip() or "Schedule"
        schedule.script_path = self.script_combo.currentData() or ""
        schedule.mode = self.mode.currentData()
        schedule.time_of_day = self.time_edit.text().strip() or "09:00"
        schedule.days = [day for day, switch in self.day_buttons.items() if switch.isChecked()] or ["mon"]
        schedule.interval_minutes = self.interval_spin.value()
        schedule.loop_mode = self.loop_combo.currentData()
        schedule.loop_count = self.count_spin.value()
        schedule.headless = self.headless_toggle.isChecked()
        self.accept()


class SchedulesPage(ScrollPage):
    run_now = pyqtSignal(object)

    def __init__(self, context, scheduler, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent, margin=22)
        self.ctx = context
        self.scheduler = scheduler
        self.add(self._build_header())
        self.add(self._build_list_card())

        self._timer = QTimer(self)
        self._timer.setInterval(5000)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()

    def _build_header(self) -> QWidget:
        holder = QWidget()
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(6, 0, 6, 0)
        layout.setSpacing(10)
        column = QVBoxLayout()
        column.setSpacing(2)
        title = QLabel("Schedules")
        title.setObjectName("PageTitle")
        column.addWidget(title)
        self.subtitle = QLabel("Clicks-Auto keeps running while this window is open.")
        self.subtitle.setObjectName("PageSubtitle")
        column.addWidget(self.subtitle)
        layout.addLayout(column, 1)

        new_button = AnimatedButton("New schedule", kind="primary", icon_text="\uff0b",
                                    accent=self.ctx.palette.accent)
        new_button.clicked.connect(self.add_schedule)
        layout.addWidget(new_button)
        refresh_button = AnimatedButton("Refresh", kind="ghost", icon_text="\u21bb")
        refresh_button.clicked.connect(self.refresh)
        layout.addWidget(refresh_button)
        return holder

    def _build_list_card(self) -> QWidget:
        card = Card(padding=14, spacing=10)
        self.list_widget = QListWidget()
        self.list_widget.setMinimumHeight(320)
        self.list_widget.itemDoubleClicked.connect(lambda _item: self.edit_selected())
        card.layout.addWidget(self.list_widget, 1)

        self.empty_state = EmptyState(
            "No schedules yet",
            "Create a schedule to run a script automatically every morning, every hour, or on "
            "chosen weekdays - perfect for repetitive check-ins.",
            glyph="\u23f0",
            action_text="Create the first schedule",
            on_action=self.add_schedule,
            accent=self.ctx.palette.accent,
        )
        card.layout.addWidget(self.empty_state)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        edit_button = AnimatedButton("Edit", kind="ghost", icon_text="\u270e")
        edit_button.clicked.connect(self.edit_selected)
        actions.addWidget(edit_button)
        toggle_button = AnimatedButton("Enable / disable", kind="ghost", icon_text="\u23fb")
        toggle_button.clicked.connect(self.toggle_selected)
        actions.addWidget(toggle_button)
        run_button = AnimatedButton("Run now", kind="success", icon_text="\u25b6",
                                    accent=self.ctx.palette.success)
        run_button.clicked.connect(self.run_selected)
        actions.addWidget(run_button)
        actions.addStretch(1)
        delete_button = AnimatedButton("Delete", kind="ghost", icon_text="\u2715")
        delete_button.clicked.connect(self.delete_selected)
        actions.addWidget(delete_button)
        card.layout.addLayout(actions)
        return card

    # ------------------------------------------------------------------- data
    def refresh(self) -> None:
        schedules = self.scheduler.schedules if self.scheduler else []
        selected_id = None
        current = self.list_widget.currentItem()
        if current is not None:
            selected_id = current.data(Qt.ItemDataRole.UserRole)
        self.list_widget.clear()
        for schedule in schedules:
            next_run = schedule.compute_next()
            when = f"next {human_datetime(next_run.timestamp())[:16]} ({countdown(next_run)})" if next_run else "disabled"
            state = "\u2713" if schedule.enabled else "\u2298"
            text = (
                f"{state}  {schedule.name}\n"
                f"     {schedule.describe()}  \u2022  {Path(schedule.script_path).name if schedule.script_path else 'no script'}"
                f"  \u2022  {when}"
            )
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, schedule.id)
            self.list_widget.addItem(item)
            if schedule.id == selected_id:
                self.list_widget.setCurrentItem(item)
        self.empty_state.setVisible(not schedules)
        self.list_widget.setVisible(bool(schedules))
        upcoming = self.scheduler.upcoming(3) if self.scheduler else []
        if upcoming:
            parts = [f"{s.name}: {countdown(datetime.fromisoformat(when))}" for s, when in upcoming]
            self.subtitle.setText("Upcoming \u2022 " + "  |  ".join(parts))
        else:
            self.subtitle.setText("Clicks-Auto keeps running while this window is open.")

    def _selected_schedule(self) -> Optional[Schedule]:
        item = self.list_widget.currentItem()
        if item is None:
            return None
        return self.scheduler.get(item.data(Qt.ItemDataRole.UserRole))

    def _script_choices(self) -> list[tuple[str, str]]:
        return [(entry.display_name, str(entry.path)) for entry in self.ctx.store.list_entries()]

    def add_schedule(self) -> None:
        if not self._script_choices():
            self.ctx.toast("Record or create a script first.", level="warning")
            return
        dialog = ScheduleDialog(self.ctx.window or self, scripts=self._script_choices(),
                                palette=self.ctx.palette)
        if dialog.exec():
            schedule = dialog.schedule
            if not schedule.script_path:
                schedule.script_path = self._script_choices()[0][1]
            self.scheduler.add(schedule)
            self.refresh()
            self.ctx.toast(f"Schedule '{schedule.name}' created.", level="success")

    def edit_selected(self) -> None:
        schedule = self._selected_schedule()
        if schedule is None:
            return
        dialog = ScheduleDialog(self.ctx.window or self, schedule=schedule,
                                scripts=self._script_choices(), palette=self.ctx.palette)
        if dialog.exec():
            self.scheduler.update(dialog.schedule)
            self.refresh()
            self.ctx.toast("Schedule updated.", level="success")

    def toggle_selected(self) -> None:
        schedule = self._selected_schedule()
        if schedule is None:
            return
        schedule.enabled = not schedule.enabled
        schedule.refresh_next()
        self.scheduler.update(schedule)
        self.refresh()
        self.ctx.toast(f"'{schedule.name}' {'enabled' if schedule.enabled else 'disabled'}.", level="info")

    def run_selected(self) -> None:
        schedule = self._selected_schedule()
        if schedule is None:
            return
        self.run_now.emit(schedule)

    def delete_selected(self) -> None:
        schedule = self._selected_schedule()
        if schedule is None:
            return
        self.scheduler.remove(schedule.id)
        self.refresh()
        self.ctx.toast(f"Deleted '{schedule.name}'.", level="info")

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.refresh()
        if MOTION.enabled:
            fade_in(self.list_widget, 200)

