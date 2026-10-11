"""Run page: pick a script, choose how many times, watch it happen live."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...engine import RunRequest
from ...history import HistoryRecord, append as append_history
from ...models import Script, Step
from ...paths import human_path
from ...timeutil import human_duration
from ..anim import MOTION, fade_in, reveal_height
from ..runner import RunWorker
from ..widgets.common import (
    AnimatedButton,
    AnimatedProgressBar,
    Card,
    Pill,
    ScrollPage,
    SectionHeader,
    SegmentControl,
    ToggleSwitch,
)
from ..widgets.console import LogConsole
from ..widgets.steplist import StepList


class RunPage(ScrollPage):
    state_changed = pyqtSignal(str, str, str)   # title, detail, level
    run_finished = pyqtSignal(object)
    script_loaded = pyqtSignal(object)

    def __init__(self, context, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent, margin=22)
        self.ctx = context
        self.script: Optional[Script] = None
        self.script_path: Optional[Path] = None
        self.worker: Optional[RunWorker] = None
        self._trigger = "manual"
        self._pulse = None
        self._started_at = 0.0
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._update_elapsed)

        self.add(SectionHeader("Run", "Playback engine with loop control and live logging."))
        self.add(self._build_script_card())
        self.add(self._build_loop_card())

        columns = QHBoxLayout()
        columns.setSpacing(16)
        left = QVBoxLayout()
        left.setSpacing(14)
        left.addWidget(self._build_live_card(), 1)
        right = QVBoxLayout()
        right.setSpacing(14)
        right.addWidget(self._build_steps_card(), 1)
        left_holder = QWidget()
        left_holder.setLayout(left)
        right_holder = QWidget()
        right_holder.setLayout(right)
        columns.addWidget(left_holder, 3)
        columns.addWidget(right_holder, 4)
        holder = QWidget()
        holder.setLayout(columns)
        self.add(holder)

        self.console = LogConsole(palette=context.palette, max_lines=context.settings.ui.log_max_lines)
        self.console.setMinimumHeight(280)
        self.add(self.console)
        self.console.log("system", "Clicks-Auto ready. Pick a script and press Run.")

    # ---------------------------------------------------------------- sections
    def _build_script_card(self) -> QWidget:
        card = Card(padding=16, spacing=12)
        header = QHBoxLayout()
        title = QLabel("Script")
        title.setProperty("role", "h3")
        header.addWidget(title)
        header.addStretch(1)
        self.validation_pill = Pill("no script selected", level="muted")
        header.addWidget(self.validation_pill)
        card.layout.addLayout(header)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.script_combo = QComboBox()
        self.script_combo.setMinimumWidth(320)
        self.script_combo.currentIndexChanged.connect(self._on_combo_changed)
        row.addWidget(self.script_combo, 1)

        browse = AnimatedButton("Open file...", kind="ghost", icon_text="\u2913")
        browse.clicked.connect(self.browse_script)
        row.addWidget(browse)

        edit = AnimatedButton("Edit", kind="ghost", icon_text="\u270e")
        edit.clicked.connect(self._open_editor)
        row.addWidget(edit)
        card.layout.addLayout(row)

        self.script_summary = QLabel("Choose a script to see its steps.")
        self.script_summary.setProperty("role", "muted")
        self.script_summary.setWordWrap(True)
        card.layout.addWidget(self.script_summary)

        self.data_row = QWidget()
        data_layout = QHBoxLayout(self.data_row)
        data_layout.setContentsMargins(0, 0, 0, 0)
        data_layout.setSpacing(8)
        self.data_label = QLabel("No data file (CSV/JSON) - loops use the same values")
        self.data_label.setProperty("role", "faint")
        data_layout.addWidget(self.data_label, 1)
        pick = AnimatedButton("Attach data file...", kind="ghost")
        pick.clicked.connect(self.pick_data_file)
        data_layout.addWidget(pick)
        clear = AnimatedButton("Clear", kind="flat")
        clear.clicked.connect(self.clear_data_file)
        data_layout.addWidget(clear)
        card.layout.addWidget(self.data_row)
        return card

    def _build_loop_card(self) -> QWidget:
        card = Card(padding=16, spacing=14)
        header = QHBoxLayout()
        title = QLabel("Loop control")
        title.setProperty("role", "h3")
        header.addWidget(title)
        header.addStretch(1)
        self.mode_segment = SegmentControl(
            [("count", "Repeat N times"), ("duration", "Run for a duration"), ("infinite", "Until I stop")],
            accent=self.ctx.palette.accent,
        )
        self.mode_segment.changed.connect(self._on_mode_changed)
        header.addWidget(self.mode_segment)
        card.layout.addLayout(header)

        settings_row = QGridLayout()
        settings_row.setHorizontalSpacing(18)
        settings_row.setVerticalSpacing(10)

        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 1_000_000)
        self.count_spin.setValue(self.ctx.settings.run.loop_count)
        self.count_spin.setPrefix("x  ")
        self.count_spin.setMinimumWidth(130)
        settings_row.addWidget(QLabel("Repetitions"), 0, 0)
        settings_row.addWidget(self.count_spin, 0, 1)

        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(1, 1440)
        self.duration_spin.setValue(self.ctx.settings.run.loop_duration_min)
        self.duration_spin.setSuffix(" min")
        self.duration_spin.setMinimumWidth(130)
        self.duration_label = QLabel("Duration")
        settings_row.addWidget(self.duration_label, 0, 2)
        settings_row.addWidget(self.duration_spin, 0, 3)

        self.slow_mo_spin = QSpinBox()
        self.slow_mo_spin.setRange(0, 3000)
        self.slow_mo_spin.setSingleStep(50)
        self.slow_mo_spin.setSuffix(" ms")
        self.slow_mo_spin.setValue(self.ctx.settings.run.slow_mo_ms)
        settings_row.addWidget(QLabel("Slow motion"), 1, 0)
        settings_row.addWidget(self.slow_mo_spin, 1, 1)

        self.browser_state = QLabel("")
        self.browser_state.setProperty("role", "faint")
        settings_row.addWidget(self.browser_state, 1, 2, 1, 2)
        card.layout.addLayout(settings_row)

        toggles = QHBoxLayout()
        toggles.setSpacing(18)
        self.headless_toggle = self._toggle("Headless (no window)", self.ctx.settings.run.headless)
        self.stop_on_error_toggle = self._toggle("Stop on first error", self.ctx.settings.run.stop_on_error)
        self.restart_toggle = self._toggle("New browser each loop", self.ctx.settings.run.restart_browser_each_loop)
        self.close_toggle = self._toggle("Close browser when done", self.ctx.settings.run.close_browser_when_done)
        for widget in (self.headless_toggle, self.stop_on_error_toggle, self.restart_toggle, self.close_toggle):
            toggles.addWidget(widget)
        toggles.addStretch(1)
        card.layout.addLayout(toggles)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.run_button = AnimatedButton("Run", kind="primary", icon_text="\u25b6", accent=self.ctx.palette.accent)
        self.run_button.setMinimumHeight(44)
        self.run_button.setMinimumWidth(150)
        self.run_button.clicked.connect(self.start_run)
        actions.addWidget(self.run_button)

        self.pause_button = AnimatedButton("Pause", kind="ghost", icon_text="\u23f8")
        self.pause_button.setMinimumHeight(44)
        self.pause_button.setEnabled(False)
        self.pause_button.clicked.connect(self.toggle_pause)
        actions.addWidget(self.pause_button)

        self.stop_button = AnimatedButton("Stop", kind="danger", icon_text="\u25a0", accent=self.ctx.palette.danger)
        self.stop_button.setMinimumHeight(44)
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_run)
        actions.addWidget(self.stop_button)

        self.dry_button = AnimatedButton("Dry run", kind="ghost", icon_text="\u2713")
        self.dry_button.setMinimumHeight(44)
        self.dry_button.clicked.connect(lambda: self.start_run(dry_run=True))
        actions.addWidget(self.dry_button)

        self.close_browser_button = AnimatedButton("Close browser", kind="ghost", icon_text="\u2715")
        self.close_browser_button.setMinimumHeight(44)
        self.close_browser_button.setVisible(False)
        self.close_browser_button.clicked.connect(self.close_browser)
        actions.addWidget(self.close_browser_button)
        actions.addStretch(1)

        self.healed_button = AnimatedButton("Save healed selectors", kind="ghost", icon_text="\u2695")
        self.healed_button.setMinimumHeight(44)
        self.healed_button.setVisible(False)
        self.healed_button.clicked.connect(self.save_healed)
        actions.addWidget(self.healed_button)
        card.layout.addLayout(actions)
        return card

    def _toggle(self, label: str, checked: bool) -> QWidget:
        holder = QWidget()
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        switch = ToggleSwitch(checked=checked, accent=self.ctx.palette.accent,
                              track_off=self.ctx.palette.border)
        text = QLabel(label)
        text.setProperty("role", "muted")
        layout.addWidget(switch)
        layout.addWidget(text)
        layout.addStretch(1)
        holder.switch = switch  # type: ignore[attr-defined]
        return holder

    def _build_live_card(self) -> QWidget:
        card = Card(padding=16, spacing=10)
        header = QHBoxLayout()
        title = QLabel("Live status")
        title.setProperty("role", "h3")
        header.addWidget(title)
        header.addStretch(1)
        self.state_pill = Pill("idle", level="muted")
        header.addWidget(self.state_pill)
        card.layout.addLayout(header)

        self.status_label = QLabel("Nothing is running.")
        font = self.status_label.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 1)
        self.status_label.setFont(font)
        self.status_label.setWordWrap(True)
        card.layout.addWidget(self.status_label)

        self.detail_label = QLabel("Press Run to start playback.")
        self.detail_label.setProperty("role", "muted")
        self.detail_label.setWordWrap(True)
        card.layout.addWidget(self.detail_label)

        self.progress = AnimatedProgressBar()
        card.layout.addWidget(self.progress)

        counters = QHBoxLayout()
        self.loop_label = QLabel("Loop 0 / 0")
        self.loop_label.setProperty("role", "muted")
        self.step_label = QLabel("Step 0 / 0")
        self.step_label.setProperty("role", "muted")
        self.time_label = QLabel("00:00")
        self.time_label.setProperty("role", "muted")
        counters.addWidget(self.loop_label)
        counters.addStretch(1)
        counters.addWidget(self.step_label)
        counters.addStretch(1)
        counters.addWidget(self.time_label)
        card.layout.addLayout(counters)
        return card

    def _build_steps_card(self) -> QWidget:
        card = Card(padding=14, spacing=10)
        header = QHBoxLayout()
        title = QLabel("Steps")
        title.setProperty("role", "h3")
        header.addWidget(title)
        header.addStretch(1)
        self.steps_pill = Pill("0 steps", level="muted")
        header.addWidget(self.steps_pill)
        card.layout.addLayout(header)
        self.step_list = StepList(card, palette=self.ctx.palette, editable=False, searchable=True)
        self.step_list.setMinimumHeight(300)
        card.layout.addWidget(self.step_list, 1)
        return card

    # ------------------------------------------------------------------ data
    def refresh_library(self) -> None:
        current = self.script_path
        self.script_combo.blockSignals(True)
        self.script_combo.clear()
        self.script_combo.addItem("Select a script...", None)
        for entry in self.ctx.store.list_entries():
            self.script_combo.addItem(f"{entry.display_name}  \u2022  {entry.step_count} steps", str(entry.path))
        if current is not None:
            index = self.script_combo.findData(str(current))
            if index >= 0:
                self.script_combo.setCurrentIndex(index)
        self.script_combo.blockSignals(False)
        self._refresh_browser_state()

    def _refresh_browser_state(self) -> None:
        from ...browser import detect_browser

        browser = self.ctx.settings.browser
        choice = detect_browser(browser.kind)
        state = "found" if choice.found else "NOT FOUND - check Settings"
        profile = browser.user_data_dir or "isolated Clicks-Auto profile"
        self.browser_state.setText(f"Browser: {choice.label} ({state}) \u2022 profile: {human_path(profile)}")

    def _on_combo_changed(self, _index: int) -> None:
        path = self.script_combo.currentData()
        if path:
            self.load_script(Path(path))

    def browse_script(self) -> None:
        start = str(Path(self.ctx.settings.last_script).parent) if self.ctx.settings.last_script else str(self.ctx.store.dir)
        path, _ = QFileDialog.getOpenFileName(self, "Open a script", start, "Clicks-Auto scripts (*.json)")
        if path:
            self.load_script(Path(path))

    def _open_editor(self) -> None:
        if self.script_path:
            self.ctx.goto("scripts")
            self.script_loaded.emit(str(self.script_path))

    def load_script(self, path: Path) -> None:
        try:
            script = self.ctx.store.load(path)
        except Exception as exc:  # noqa: BLE001
            self.ctx.toast(f"Could not read {path.name}: {exc}", level="error")
            return
        self.script = script
        self.script_path = Path(path)
        self.ctx.settings.last_script = str(path)
        self.ctx.save()
        self.step_list.populate(script.steps)
        self.steps_pill.set_level("info")
        self.steps_pill.setText(f"{script.step_count} steps")
        problems = script.validate()
        if problems:
            self.validation_pill.set_level("warning", f"{len(problems)} issue(s)")
            self.script_summary.setText(" \u2022 ".join(problems[:3]))
        else:
            self.validation_pill.set_level("success", "ready to run")
            variables = script.used_variables()
            extra = f" \u2022 variables: {', '.join(variables[:6])}" if variables else ""
            estimate = human_duration(script.estimated_seconds())
            self.script_summary.setText(f"{script.name}: {script.step_count} steps \u2022 ~{estimate} per loop{extra}")
        self.console.log("system", f"Loaded '{script.name}' ({script.step_count} steps).")
        self.script_loaded.emit(str(path))
        if MOTION.enabled:
            fade_in(self.step_list, 220)

    def pick_data_file(self) -> None:
        start = str(Path(self.ctx.settings.run.data_file).parent) if self.ctx.settings.run.data_file else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a data file", start, "Data files (*.csv *.tsv *.json *.jsonl *.txt)")
        if path:
            self.set_data_file(path)

    def set_data_file(self, path: str) -> None:
        from ...datafeed import DataFeed

        try:
            feed = DataFeed.from_file(path)
        except Exception as exc:  # noqa: BLE001
            self.ctx.toast(str(exc), level="error")
            return
        self.ctx.settings.run.data_file = path
        self.ctx.save()
        self.data_label.setText(f"Data: {human_path(path)} \u2014 {feed.summary()}")
        self.data_label.setProperty("role", "muted")
        self.console.log("system", f"Data feed attached: {feed.summary()}")
        columns = ", ".join(f"${{{name}}}" for name in feed.columns[:8])
        self.console.log("info", f"Available per-row variables: {columns}")

    def clear_data_file(self) -> None:
        self.ctx.settings.run.data_file = ""
        self.ctx.save()
        self.data_label.setText("No data file (CSV/JSON) - loops use the same values")

    # ------------------------------------------------------------------- run
    def _loop_mode(self) -> str:
        return self.mode_segment.current()

    def _on_mode_changed(self, key: str) -> None:
        is_count = key == "count"
        is_duration = key == "duration"
        self.count_spin.setVisible(is_count)
        self.duration_spin.setVisible(is_duration)
        self.ctx.settings.run.loop_mode = key
        self.ctx.save()
        if MOTION.enabled:
            reveal_height(self.progress, 220)

    def _build_request(self, *, dry_run: bool = False) -> RunRequest:
        settings = self.ctx.settings
        browser = settings.browser
        timeouts = settings.timeouts
        return RunRequest(
            script=self.script,
            loop_mode=self._loop_mode(),
            loop_count=self.count_spin.value(),
            duration_minutes=self.duration_spin.value(),
            headless=self.headless_toggle.switch.isChecked(),   # type: ignore[attr-defined]
            slow_mo_ms=self.slow_mo_spin.value(),
            stop_on_error=self.stop_on_error_toggle.switch.isChecked(),  # type: ignore[attr-defined]
            restart_browser_each_loop=self.restart_toggle.switch.isChecked(),  # type: ignore[attr-defined]
            close_browser_when_done=self.close_toggle.switch.isChecked(),  # type: ignore[attr-defined]
            keep_browser_open=not self.close_toggle.switch.isChecked(),  # type: ignore[attr-defined]
            browser_kind=browser.kind,
            browser_executable=browser.custom_path if browser.kind == "custom" else "",
            user_data_dir=browser.user_data_dir,
            window_width=browser.window_width,
            window_height=browser.window_height,
            extra_args=list(browser.extra_args),
            download_dir=browser.download_dir,
            action_timeout_ms=timeouts.action_ms,
            navigation_timeout_ms=timeouts.navigation_ms,
            step_retries=timeouts.step_retries,
            retry_delay_ms=timeouts.retry_delay_ms,
            delay_between_steps_ms=timeouts.delay_between_steps_ms,
            delay_between_loops_ms=timeouts.delay_between_loops_ms,
            type_delay_ms=timeouts.type_delay_ms,
            restart_browser_after_loops=timeouts.loop_restart_browser_after,
            data_file=settings.run.data_file,
            screenshot_on_error=settings.run.screenshot_on_error,
            dry_run=dry_run,
        )

    def set_mode(self, loop_mode: str, loop_count: int = 1, *, headless: bool | None = None) -> None:
        """Apply loop settings coming from a schedule or the sidebar."""
        mapping = {"count": "count", "duration": "duration", "infinite": "infinite"}
        self.mode_segment.set_current(mapping.get(loop_mode, "count"))
        self.count_spin.setValue(max(1, int(loop_count or 1)))
        if headless is not None:
            holder = self.headless_toggle
            switch = getattr(holder, "switch", None)
            if switch is not None:
                switch.setChecked(bool(headless))

    def start_run(self, *, dry_run: bool = False, trigger: str = "manual") -> None:
        self._trigger = trigger
        if self.worker is not None and self.worker.isRunning():
            self.ctx.toast("A run is already in progress.", level="warning")
            return
        if self.script is None:
            self.ctx.toast("Choose a script first.", level="warning")
            return
        if not dry_run:
            problems = self.script.validate()
            if problems:
                self.ctx.toast(problems[0], level="warning", title="Script needs attention")
                self.console.log("warn", problems[0])

        request = self._build_request(dry_run=dry_run)
        self.step_list.reset_states()
        self.console.log("system", f"=== Run started: {self.script.name} ({request.loop_mode}) ===")
        self.healed_button.setVisible(False)
        self._started_at = time.time()
        self._tick.start()
        self._set_running_ui(True)

        worker = RunWorker(request, self)
        worker.log.connect(self.console.log)
        worker.status.connect(self._on_engine_status)
        worker.loop_changed.connect(self._on_loop)
        worker.step_started.connect(self._on_step_started)
        worker.step_result.connect(self._on_step_result)
        worker.progress.connect(self._on_progress)
        worker.finished_run.connect(self._on_finished)
        worker.session_kept_alive.connect(self._on_session_kept)
        worker.session_closed.connect(self._on_session_closed)
        worker.failed.connect(lambda message: self.ctx.toast(message, level="error"))
        worker.start()
        self.worker = worker

    def toggle_pause(self) -> None:
        if self.worker is None:
            return
        if self.pause_button.text().endswith("Pause"):
            self.worker.pause()
            self.pause_button.setText("\u25b6  Resume")
            self.state_pill.set_level("warning", "paused")
            self.state_changed.emit("Paused", "The run is paused - press Resume to continue.", "warning")
        else:
            self.worker.resume()
            self.pause_button.setText("\u23f8  Pause")
            self.state_pill.set_level("info", "running")
            self.state_changed.emit("Running", "Playback in progress.", "busy")

    def stop_run(self) -> None:
        if self.worker is None:
            return
        self.console.log("warn", "Stop requested...")
        self.state_pill.set_level("warning", "stopping")
        self.worker.stop()
        self.stop_button.setEnabled(False)

    def close_browser(self) -> None:
        if self.worker is None:
            return
        self.worker.close_browser()
        self.close_browser_button.setEnabled(False)

    def _set_running_ui(self, running: bool) -> None:
        self.run_button.setEnabled(not running)
        self.dry_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.pause_button.setEnabled(running)
        self.pause_button.setText("\u23f8  Pause")
        self.close_browser_button.setVisible(False)
        if running:
            self.state_pill.set_level("info", "starting")
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self.progress.set_tone("accent")
            self.progress.set_shimmer_accent(self.ctx.palette.accent)
            self.progress.start_indeterminate()
            self.status_label.setText("Starting the browser...")
            self.detail_label.setText("Playwright is launching your browser.")
            self.state_changed.emit("Running", "Playback engine started.", "busy")
        else:
            self.progress.stop_indeterminate()
            self._tick.stop()

    def _on_engine_status(self, status: str) -> None:
        if status == "preparing":
            self.status_label.setText("Preparing the run...")
        elif status == "idle":
            self.state_pill.set_level("muted", "idle")
        elif status == "dry-run":
            self.state_pill.set_level("info", "dry run")

    def _on_loop(self, index: int, total: int) -> None:
        total_label = str(total) if total else "\u221e"
        self.loop_label.setText(f"Loop {index} / {total_label}")
        self.progress.stop_indeterminate()
        self.progress.set_value_animated(0, 260)
        self.status_label.setText(f"Loop {index}" + (f" of {total}" if total else ""))
        self.detail_label.setText("Running steps...")

    def _on_step_started(self, index: int, total: int, step: Step) -> None:
        self.step_label.setText(f"Step {index} / {total}")
        self.step_list.set_state(index - 1, "running")
        self.step_list.scroll_to_step(index - 1)
        self.status_label.setText(f"{step.label}: {step.summary() or step.description or ''}"[:150])
        self.detail_label.setText(f"Step {index} of {total}")

    def _on_step_result(self, index: int, result) -> None:
        state = {"ok": "ok", "retried": "ok", "error": "error", "skipped": "skipped"}.get(result.status, "idle")
        self.step_list.set_state(index - 1, state, result.message)

    def _on_progress(self, done: int, total: int) -> None:
        if total:
            percent = int(done / total * 100)
            self.progress.set_value_animated(percent, 300)

    def _on_finished(self, result) -> None:
        self._set_running_ui(False)
        if result is None:
            self.ctx.toast("The run ended unexpectedly - check the console.", level="error")
            self.state_changed.emit("Error", "The run ended unexpectedly.", "error")
            return
        data = result.to_dict()
        append_history(HistoryRecord.from_result(data, trigger=getattr(self, "_trigger", "manual")))
        self.console.log("system", f"=== Finished: {result.outcome} ===")
        self.progress.stop_indeterminate()
        self.progress.set_tone("success" if not result.steps_failed else "danger")
        self.progress.set_value_animated(100 if result.outcome == "completed" else 60, 400)
        summary = (
            f"{result.loops_completed} loop(s) \u2022 {result.steps_ok} steps ok \u2022 "
            f"{result.steps_failed} failed \u2022 {data.get('duration')}"
        )
        self.detail_label.setText(summary)
        self.status_label.setText({
            "completed": "Finished successfully",
            "completed_with_errors": "Finished with errors",
            "failed": "Run failed",
            "stopped": "Stopped by you",
        }.get(result.outcome, result.outcome))
        level = {"completed": "success", "completed_with_errors": "warning",
                 "failed": "error", "stopped": "muted"}.get(result.outcome, "info")
        self.state_pill.set_level(level, result.outcome.replace("_", " "))
        if result.healed:
            self.healed_button.setVisible(True)
            self.healed_button.setToolTip(
                f"{len(result.healed)} step(s) used a fallback selector - save them to make the script faster next time."
            )
            self.ctx.toast(
                f"{len(result.healed)} step(s) healed with fallback selectors.", level="warning",
                title="Selectors were repaired",
            )
        self.ctx.toast(summary, level="success" if result.outcome == "completed" else "warning",
                       title=f"{result.outcome.replace('_', ' ').title()}: {result.script_name}")
        self.state_changed.emit(self.status_label.text(), summary,
                               "success" if result.outcome == "completed" else "warning")
        window = self.ctx.window
        if window is not None and result.outcome == "completed":
            try:
                window.play_finish_sound()
            except Exception:
                pass
        self.run_finished.emit(result)

    def _on_session_kept(self) -> None:
        self.close_browser_button.setVisible(True)
        self.close_browser_button.setEnabled(True)
        self.console.log("info", "Browser left open - press 'Close browser' when you are done.")

    def _on_session_closed(self) -> None:
        self.close_browser_button.setVisible(False)
        self.console.log("info", "Browser session closed.")
        self.ctx.status("idle")

    def save_healed(self) -> None:
        if self.script is None or self.script_path is None:
            return
        try:
            self.ctx.store.save(self.script, self.script_path)
            self.ctx.toast(f"Saved {self.script_path.name} with the healed selectors.", level="success")
            self.console.log("ok", f"Script saved to {self.script_path}")
            self.healed_button.setVisible(False)
            self.step_list.populate(self.script.steps)
        except Exception as exc:  # noqa: BLE001
            self.ctx.toast(str(exc), level="error")

    def _update_elapsed(self) -> None:
        if not self._started_at:
            return
        self.time_label.setText(human_duration(time.time() - self._started_at))

    # ----------------------------------------------------------------- misc
    def apply_palette(self, palette) -> None:
        self.console.set_palette(palette)
        self.step_list.set_palette(palette)
        self.mode_segment._accent = palette.accent
        self.run_button.set_accent(palette.accent)
        self.stop_button.set_accent(palette.danger)

    def busy(self) -> bool:
        return bool(self.worker is not None and self.worker.isRunning())

    def shutdown(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.worker.abort()
            self.worker.wait(6000)
