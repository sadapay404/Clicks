"""Record page: launch a test browser and capture every action at the DOM level."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...browser import LaunchRequest, detect_browser
from ...models import Script, Step
from ...recorder.builder import RecorderOptions
from ...timeutil import human_duration
from ..anim import MOTION, fade_in, pulse, stop_pulse
from ..dialogs import BrowserPickerDialog
from ..runner import RecorderWorker
from ..widgets.common import (
    AnimatedButton,
    Card,
    Pill,
    ScrollPage,
    SectionHeader,
    ToggleSwitch,
)
from ..widgets.console import LogConsole
from ..widgets.steplist import StepList


class RecorderPage(ScrollPage):
    state_changed = pyqtSignal(str, str, str)
    script_saved = pyqtSignal(str)

    def __init__(self, context, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent, margin=22)
        self.ctx = context
        self.worker: Optional[RecorderWorker] = None
        self.steps: list[Step] = []
        self._pulse = None
        self._started_at = 0.0
        self.script: Optional[Script] = None
        self.saved_path: Optional[Path] = None
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._update_elapsed)

        self.add(SectionHeader(
            "Record Session",
            "A dedicated browser opens; every click, keystroke, dropdown and navigation is captured as editable steps.",
        ))
        self.add(self._build_setup_card())
        self.add(self._build_control_card())

        columns = QHBoxLayout()
        columns.setSpacing(16)
        left = QVBoxLayout()
        left.addWidget(self._build_steps_card(), 1)
        right = QVBoxLayout()
        right.addWidget(self._build_tips_card())
        right.addStretch(1)
        left_holder = QWidget()
        left_holder.setLayout(left)
        right_holder = QWidget()
        right_holder.setLayout(right)
        columns.addWidget(left_holder, 4)
        columns.addWidget(right_holder, 2)
        holder = QWidget()
        holder.setLayout(columns)
        self.add(holder)

        self.console = LogConsole(palette=context.palette, max_lines=2000)
        self.console.setMinimumHeight(200)
        self.add(self.console)
        self.console.log("system", "Recorder idle. Press 'Record Session' to open the test browser.")

    # ------------------------------------------------------------------ build
    def _build_setup_card(self) -> QWidget:
        card = Card(padding=16, spacing=12)
        title = QLabel("Session setup")
        title.setProperty("role", "h3")
        card.layout.addWidget(title)

        row = QHBoxLayout()
        row.setSpacing(12)
        name_column = QVBoxLayout()
        name_column.setSpacing(4)
        name_column.addWidget(QLabel("Session name"))
        self.name_edit = QLineEdit("Recorded session")
        self.name_edit.setPlaceholderText("e.g. Daily invoice check-in")
        name_column.addWidget(self.name_edit)
        row.addLayout(name_column, 3)

        url_column = QVBoxLayout()
        url_column.setSpacing(4)
        url_column.addWidget(QLabel("Start page (optional)"))
        self.url_edit = QLineEdit("")
        self.url_edit.setPlaceholderText("https://example.com - or leave empty for a blank tab")
        url_column.addWidget(self.url_edit)
        row.addLayout(url_column, 4)
        card.layout.addLayout(row)

        browser_row = QHBoxLayout()
        browser_row.setSpacing(10)
        self.browser_label = QLabel("")
        self.browser_label.setProperty("role", "muted")
        browser_row.addWidget(self.browser_label, 1)
        change = AnimatedButton("Change browser / profile", kind="ghost", icon_text="\u2699")
        change.clicked.connect(self.change_browser)
        browser_row.addWidget(change)
        card.layout.addLayout(browser_row)

        options_row = QHBoxLayout()
        options_row.setSpacing(18)
        self.scroll_toggle = self._toggle("Record scrolling", False)
        self.hover_toggle = self._toggle("Record hovering", False)
        self.keystroke_toggle = self._toggle("Type like a human (keystroke by keystroke)", False)
        self.keep_open_toggle = self._toggle("Keep browser open after saving", False)
        for widget in (self.scroll_toggle, self.hover_toggle, self.keystroke_toggle, self.keep_open_toggle):
            options_row.addWidget(widget)
        options_row.addStretch(1)
        card.layout.addLayout(options_row)

        typing_row = QHBoxLayout()
        typing_row.setSpacing(10)
        typing_row.addWidget(QLabel("Typing delay"))
        self.typing_delay = QSpinBox()
        self.typing_delay.setRange(0, 500)
        self.typing_delay.setValue(self.ctx.settings.timeouts.type_delay_ms)
        self.typing_delay.setSuffix(" ms/key")
        self.typing_delay.setMinimumWidth(140)
        typing_row.addWidget(self.typing_delay)
        typing_row.addWidget(QLabel("Recorded pauses"))
        self.wait_toggle = self._toggle("Insert wait steps for my thinking pauses", True)
        typing_row.addWidget(self.wait_toggle)
        typing_row.addStretch(1)
        card.layout.addLayout(typing_row)
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

    def _build_control_card(self) -> QWidget:
        card = Card(tone="alt", padding=18, spacing=14)
        row = QHBoxLayout()
        row.setSpacing(14)

        self.record_button = AnimatedButton("Record Session", kind="danger", icon_text="\u25cf",
                                            accent=self.ctx.palette.danger)
        self.record_button.setMinimumHeight(52)
        self.record_button.setMinimumWidth(210)
        self.record_button.clicked.connect(self.toggle_recording)
        row.addWidget(self.record_button)

        self.pause_button = AnimatedButton("Pause recording", kind="ghost", icon_text="\u23f8")
        self.pause_button.setMinimumHeight(52)
        self.pause_button.setEnabled(False)
        self.pause_button.clicked.connect(self.toggle_pause)
        row.addWidget(self.pause_button)

        self.mark_button = AnimatedButton("Add wait step", kind="ghost", icon_text="\u231b")
        self.mark_button.setMinimumHeight(52)
        self.mark_button.setEnabled(False)
        self.mark_button.setToolTip("Insert a wait step at the current point - handy before slow pages settle")
        self.mark_button.clicked.connect(self.add_manual_wait)
        row.addWidget(self.mark_button)

        self.stop_button = AnimatedButton("Stop & save", kind="success", icon_text="\u25a0",
                                          accent=self.ctx.palette.success)
        self.stop_button.setMinimumHeight(52)
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_recording)
        row.addWidget(self.stop_button)

        row.addStretch(1)

        status_column = QVBoxLayout()
        status_column.setSpacing(4)
        self.rec_indicator = QLabel("\u25cf  idle")
        self.rec_indicator.setStyleSheet(f"color: {self.ctx.palette.text_faint}; font-weight: 700;")
        status_column.addWidget(self.rec_indicator)
        self.elapsed_label = QLabel("00:00")
        self.elapsed_label.setProperty("role", "muted")
        status_column.addWidget(self.elapsed_label)
        self.count_label = QLabel("0 steps recorded")
        self.count_label.setProperty("role", "muted")
        status_column.addWidget(self.count_label)
        row.addLayout(status_column)
        card.layout.addLayout(row)

        self.post_row = QWidget()
        post_layout = QHBoxLayout(self.post_row)
        post_layout.setContentsMargins(0, 0, 0, 0)
        post_layout.setSpacing(10)
        self.saved_label = QLabel("")
        self.saved_label.setProperty("role", "muted")
        post_layout.addWidget(self.saved_label, 1)
        self.open_button = AnimatedButton("Open in editor", kind="primary", icon_text="\u270e",
                                          accent=self.ctx.palette.accent)
        self.open_button.clicked.connect(self._open_in_editor)
        post_layout.addWidget(self.open_button)
        self.run_now_button = AnimatedButton("Run it now", kind="ghost", icon_text="\u25b6")
        self.run_now_button.clicked.connect(self._run_now)
        post_layout.addWidget(self.run_now_button)
        self.post_row.setVisible(False)
        card.layout.addWidget(self.post_row)
        return card

    def _build_steps_card(self) -> QWidget:
        card = Card(padding=14, spacing=10)
        header = QHBoxLayout()
        title = QLabel("Captured steps")
        title.setProperty("role", "h3")
        header.addWidget(title)
        header.addStretch(1)
        self.steps_pill = Pill("0 steps", level="muted")
        header.addWidget(self.steps_pill)
        card.layout.addLayout(header)
        self.step_list = StepList(card, palette=self.ctx.palette, editable=False, searchable=True)
        self.step_list.setMinimumHeight(320)
        card.layout.addWidget(self.step_list, 1)
        return card

    def _build_tips_card(self) -> QWidget:
        card = Card(padding=16, spacing=8)
        title = QLabel("Recording tips")
        title.setProperty("role", "h3")
        card.layout.addWidget(title)
        for glyph, text in (
            ("\u25b8", "Click like a user: buttons, links, dropdowns and typing are all captured."),
            ("\u21b5", "Press Enter after typing and the recorded step remembers to submit."),
            ("\u231b", "Slow pages? Add a wait step, or keep the recorded pauses."),
            ("\u25c8", "Popup tabs are recorded as their own step and playback follows them."),
            ("\u26a0", "Uploads need real file paths - set them in the script editor afterwards."),
            ("\u2713", "Passwords are stored as ${password} style secrets and masked in logs."),
        ):
            row = QHBoxLayout()
            row.setSpacing(8)
            glyph_label = QLabel(glyph)
            glyph_label.setStyleSheet(f"color: {self.ctx.palette.accent};")
            row.addWidget(glyph_label, alignment=Qt.AlignmentFlag.AlignTop)
            body = QLabel(text)
            body.setWordWrap(True)
            body.setProperty("role", "muted")
            row.addWidget(body, 1)
            holder = QWidget()
            holder.setLayout(row)
            card.layout.addWidget(holder)
        return card

    # ------------------------------------------------------------------ setup
    def change_browser(self) -> None:
        dialog = BrowserPickerDialog(
            self.ctx.window or self,
            palette=self.ctx.palette,
            current_kind=self.ctx.settings.browser.kind,
            current_profile=self.ctx.settings.browser.user_data_dir,
        )
        if dialog.exec():
            kind, profile = dialog.values()
            self.ctx.settings.browser.kind = kind
            self.ctx.settings.browser.user_data_dir = profile
            self.ctx.save()
            self.refresh_browser_label()
            self.ctx.toast("Browser settings updated.", level="success")

    def refresh_browser_label(self) -> None:
        browser = self.ctx.settings.browser
        choice = detect_browser(browser.kind)
        state = f"found: {choice.path}" if choice.found else "NOT FOUND - click Change browser"
        profile = browser.user_data_dir or "isolated Clicks-Auto profile"
        self.browser_label.setText(f"{choice.label} \u2022 {state}\nProfile: {profile}")

    def _recorder_options(self) -> RecorderOptions:
        return RecorderOptions(
            record_waits=self.wait_toggle.switch.isChecked(),      # type: ignore[attr-defined]
            record_scroll=self.scroll_toggle.switch.isChecked(),   # type: ignore[attr-defined]
            record_hover=self.hover_toggle.switch.isChecked(),     # type: ignore[attr-defined]
            typing_mode="keystrokes" if self.keystroke_toggle.switch.isChecked() else "fill",  # type: ignore[attr-defined]
            typing_delay_ms=self.typing_delay.value(),
            step_retries=self.ctx.settings.timeouts.step_retries,
            action_timeout_ms=self.ctx.settings.timeouts.action_ms,
        )

    def _launch_request(self) -> LaunchRequest:
        browser = self.ctx.settings.browser
        return LaunchRequest(
            kind=browser.kind,
            executable=browser.custom_path if browser.kind == "custom" else "",
            user_data_dir=browser.user_data_dir,
            headless=False,
            slow_mo_ms=0,
            window_width=max(1024, browser.window_width),
            window_height=max(700, browser.window_height),
            start_maximized=browser.start_maximized,
            extra_args=list(browser.extra_args),
            download_dir=browser.download_dir,
            navigation_timeout_ms=self.ctx.settings.timeouts.navigation_ms,
        )

    # ------------------------------------------------------------- recording
    def toggle_recording(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.stop_recording()
        else:
            self.start_recording()

    def start_recording(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        choice = detect_browser(self.ctx.settings.browser.kind)
        if not choice.found and self.ctx.settings.browser.kind != "custom":
            self.ctx.toast(
                f"{choice.label} was not found. Open 'Change browser / profile' and pick another browser.",
                level="error", title="Browser missing",
            )
            return

        self.steps = []
        self.script = None
        self.saved_path = None
        self.step_list.populate([])
        self.steps_pill.set_level("info")
        self.steps_pill.setText("0 steps")
        self.post_row.setVisible(False)
        self.console.log("system", "Starting the recorder browser...")

        name = self.name_edit.text().strip() or "Recorded session"
        worker = RecorderWorker(
            self._launch_request(),
            name=name,
            options=self._recorder_options(),
            start_url=self.url_edit.text().strip(),
            keep_browser_open=self.keep_open_toggle.switch.isChecked(),  # type: ignore[attr-defined]
            parent=self,
        )
        worker.log.connect(self.console.log)
        worker.step_added.connect(self._on_step_added)
        worker.counter.connect(self._on_counter)
        worker.recording_status.connect(self._on_recording_status)
        worker.finished_recording.connect(self._on_finished)
        worker.session_closed.connect(lambda: self.console.log("info", "Recorder browser closed."))
        worker.failed.connect(self._on_failed)
        worker.start()
        self.worker = worker

        self._started_at = time.time()
        self._tick.start()
        self.record_button.setText("\u25cf  Recording... click Stop & save")
        self.record_button.setProperty("kind", "ghost")
        self._repolish(self.record_button)
        self.pause_button.setEnabled(True)
        self.mark_button.setEnabled(True)
        self.stop_button.setEnabled(True)
        self.rec_indicator.setText("\u25cf  RECORDING")
        self.rec_indicator.setStyleSheet(f"color: {self.ctx.palette.danger}; font-weight: 700;")
        if MOTION.enabled:
            self._pulse = pulse(self.rec_indicator, low=0.25, high=1.0, period=1000)
        self.state_changed.emit("Recording", "Interact with the recorder browser.", "warning")

    def stop_recording(self) -> None:
        if self.worker is None:
            return
        self.console.log("info", "Finishing up and saving the recorded script...")
        self.stop_button.setEnabled(False)
        self.worker.finish_recording()

    def toggle_pause(self) -> None:
        if self.worker is None:
            return
        paused = not self._is_paused()
        self._paused_flag = paused
        self.worker.set_paused(paused)
        self.pause_button.setText("\u25b6  Resume recording" if paused else "\u23f8  Pause recording")

    def _is_paused(self) -> bool:
        return bool(getattr(self, "_paused_flag", False))

    def add_manual_wait(self) -> None:
        if self.worker is None:
            return
        step = Step(type="wait", value="1500", description="Manual pause")
        self.worker.add_manual_step(step)

    def _on_step_added(self, count: int, step: Step) -> None:
        self.steps.append(step)
        self.step_list.populate(self.steps, animate=False)
        self.step_list.scroll_to_step(len(self.steps) - 1)
        self.steps_pill.set_level("info")
        self.steps_pill.setText(f"{count} steps")

    def _on_counter(self, count: int) -> None:
        self.count_label.setText(f"{count} step(s) recorded")

    def _on_recording_status(self, state: str, detail: str) -> None:
        if state == "paused":
            self.rec_indicator.setText("\u23f8  PAUSED")
            self.rec_indicator.setStyleSheet(f"color: {self.ctx.palette.warning}; font-weight: 700;")
            if self._pulse is not None:
                stop_pulse(self._pulse, self.rec_indicator)
                self._pulse = None
            self.state_changed.emit("Recorder paused", "Actions are not being captured.", "warning")
        elif state == "recording":
            self.rec_indicator.setText("\u25cf  RECORDING")
            self.rec_indicator.setStyleSheet(f"color: {self.ctx.palette.danger}; font-weight: 700;")
            if MOTION.enabled and self._pulse is None:
                self._pulse = pulse(self.rec_indicator, low=0.25, high=1.0, period=1000)
            self.state_changed.emit("Recording", detail or "Interact with the recorder browser.", "warning")
        elif state == "saved":
            self.state_changed.emit("Saved", detail, "success")
        elif state == "failed":
            self.state_changed.emit("Recorder failed", detail, "error")

    def _on_failed(self, message: str) -> None:
        self._reset_ui()
        self.console.log("error", message)
        self.ctx.toast(message.split("\n")[0], level="error", title="Recorder could not start")

    def _on_finished(self, script: Optional[Script]) -> None:
        self._reset_ui()
        if script is None or not script.steps:
            self.ctx.toast(
                "Nothing was recorded. Did you interact with the browser before stopping?",
                level="warning",
            )
            self.console.log("warn", "Recorder finished without any steps.")
            return
        self.script = script
        try:
            path = self.ctx.store.save(script, self.ctx.store.unique_path_for(script.name))
        except Exception as exc:  # noqa: BLE001
            self.ctx.toast(str(exc), level="error")
            return
        self.saved_path = path
        self.saved_label.setText(
            f"Saved {script.step_count} steps as '{script.name}' \u2192 {path.name}"
        )
        self.post_row.setVisible(True)
        if MOTION.enabled:
            fade_in(self.post_row, 260)
        self.ctx.toast(f"Recorded {script.step_count} steps into '{script.name}'.", level="success",
                       title="Session saved")
        self.console.log("ok", f"Saved to {path}")
        self.state_changed.emit("Saved", f"{script.step_count} steps saved as {path.name}", "success")
        self.script_saved.emit(str(path))
        self.ctx.goto("recorder")

    def _reset_ui(self) -> None:
        self._tick.stop()
        self._started_at = 0.0
        self.record_button.setText("\u25cf  Record Session")
        self.record_button.setProperty("kind", "danger")
        self._repolish(self.record_button)
        self.pause_button.setEnabled(False)
        self.pause_button.setText("\u23f8  Pause recording")
        self.mark_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.rec_indicator.setText("\u25cf  idle")
        self.rec_indicator.setStyleSheet(f"color: {self.ctx.palette.text_faint}; font-weight: 700;")
        if self._pulse is not None:
            stop_pulse(self._pulse, self.rec_indicator)
            self._pulse = None
        self._paused_flag = False

    def _repolish(self, widget: QWidget) -> None:
        style = widget.style()
        if style:
            style.unpolish(widget)
            style.polish(widget)

    def _open_in_editor(self) -> None:
        if self.saved_path:
            self.ctx.settings.last_script = str(self.saved_path)
            self.ctx.save()
            self.ctx.goto("scripts")

    def _run_now(self) -> None:
        if self.saved_path:
            self.ctx.settings.last_script = str(self.saved_path)
            self.ctx.save()
            self.ctx.goto("run")

    def _update_elapsed(self) -> None:
        if not self._started_at:
            return
        elapsed = time.time() - self._started_at
        self.elapsed_label.setText(human_duration(elapsed))

    # ------------------------------------------------------------------ misc
    def apply_palette(self, palette) -> None:
        self.console.set_palette(palette)
        self.step_list.set_palette(palette)
        self.record_button.set_accent(palette.danger)
        self.stop_button.set_accent(palette.success)
        self.open_button.set_accent(palette.accent)

    def busy(self) -> bool:
        return bool(self.worker is not None and self.worker.isRunning())

    def shutdown(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.worker.abort()
            self.worker.wait(6000)
