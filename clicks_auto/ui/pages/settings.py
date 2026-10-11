"""Settings page: appearance, browser, timeouts, run defaults and data folders."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ... import APP_URL, __version__
from ...browser import detect_all, refresh_browsers
from ...paths import (
    app_data_dir,
    human_path,
    logs_dir,
    profiles_dir,
    screenshots_dir,
    scripts_dir,
)
from ..anim import MOTION
from ..dialogs import AboutDialog
from ..runner import BrowserProbe, ChromiumInstaller
from ..theme import available_themes
from ..widgets.common import (
    AnimatedButton,
    Card,
    Pill,
    ScrollPage,
    SectionHeader,
    ToggleSwitch,
)


class SettingsPage(ScrollPage):
    theme_changed = pyqtSignal(str)

    def __init__(self, context, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent, margin=22)
        self.ctx = context
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(450)
        self._save_timer.timeout.connect(self._flush)

        self.add(SectionHeader("Settings", "Everything is stored in your user profile and applied immediately."))
        self.add(self._build_appearance_card())
        self.add(self._build_browser_card())
        self.add(self._build_timeouts_card())
        self.add(self._build_run_card())
        self.add(self._build_data_card())
        self.add(self._build_about_card())
        self._load_values()

        # Created on first show - probing the disk is pointless while the user
        # is still on the dashboard, and it keeps window construction cheap.
        self._probe: Optional[BrowserProbe] = None
        self._installer: Optional[ChromiumInstaller] = None

    # ---------------------------------------------------------------- control
    def start_probe(self) -> None:
        """Look for installed browsers (once) in the background."""
        if self._probe is not None and self._probe.isRunning():
            return
        self._probe = BrowserProbe(self)
        self._probe.found.connect(self._on_probe)
        self._probe.start()

    def shutdown(self) -> None:
        """Stop background work owned by this page (probe, installer)."""
        if self._probe is not None:
            self._probe.stop()
        if self._installer is not None and self._installer.isRunning():
            self._installer.requestInterruption()
            self._installer.wait(4000)

    # --------------------------------------------------------------- sections
    def _build_appearance_card(self) -> QWidget:
        card = Card(padding=16, spacing=12)
        title = QLabel("Appearance")
        title.setProperty("role", "h3")
        card.layout.addWidget(title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(10)

        grid.addWidget(QLabel("Theme"), 0, 0)
        self.theme_combo = QComboBox()
        for key, label in available_themes():
            self.theme_combo.addItem(label, key)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        grid.addWidget(self.theme_combo, 0, 1)

        self.theme_swatches = QWidget()
        swatch_layout = QHBoxLayout(self.theme_swatches)
        swatch_layout.setContentsMargins(0, 0, 0, 0)
        swatch_layout.setSpacing(6)
        self._swatch_labels: list[QLabel] = []
        for _ in range(5):
            swatch = QLabel()
            swatch.setFixedSize(20, 20)
            swatch_layout.addWidget(swatch)
            self._swatch_labels.append(swatch)
        swatch_layout.addStretch(1)
        grid.addWidget(self.theme_swatches, 0, 2, 1, 2)

        grid.addWidget(QLabel("Animations"), 1, 0)
        self.animations_toggle = ToggleSwitch(checked=True, accent=self.ctx.palette.accent,
                                              track_off=self.ctx.palette.border)
        self.animations_toggle.toggled.connect(self._on_animations)
        grid.addWidget(self.animations_toggle, 1, 1)

        grid.addWidget(QLabel("Reduce motion"), 1, 2)
        self.reduce_toggle = ToggleSwitch(accent=self.ctx.palette.accent, track_off=self.ctx.palette.border)
        self.reduce_toggle.toggled.connect(self._on_setting_changed)
        grid.addWidget(self.reduce_toggle, 1, 3)

        grid.addWidget(QLabel("Animation speed"), 2, 0)
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setRange(25, 400)
        self.speed_slider.setValue(100)
        self.speed_slider.setToolTip("Drag right for bouncier, slower motion")
        self.speed_slider.valueChanged.connect(self._on_speed)
        grid.addWidget(self.speed_slider, 2, 1)
        self.speed_label = QLabel("1.00x")
        self.speed_label.setProperty("role", "muted")
        grid.addWidget(self.speed_label, 2, 2)

        grid.addWidget(QLabel("Compact layout"), 3, 0)
        self.compact_toggle = ToggleSwitch(accent=self.ctx.palette.accent, track_off=self.ctx.palette.border)
        self.compact_toggle.toggled.connect(self._on_setting_changed)
        grid.addWidget(self.compact_toggle, 3, 1)

        grid.addWidget(QLabel("Toast notifications"), 3, 2)
        self.toast_toggle = ToggleSwitch(checked=True, accent=self.ctx.palette.accent,
                                         track_off=self.ctx.palette.border)
        self.toast_toggle.toggled.connect(self._on_setting_changed)
        grid.addWidget(self.toast_toggle, 3, 3)

        grid.addWidget(QLabel("Native title bar"), 4, 0)
        self.titlebar_toggle = ToggleSwitch(accent=self.ctx.palette.accent, track_off=self.ctx.palette.border)
        self.titlebar_toggle.setToolTip("Restart required. Useful on unusual DPI setups.")
        self.titlebar_toggle.toggled.connect(self._on_setting_changed)
        grid.addWidget(self.titlebar_toggle, 4, 1)

        grid.addWidget(QLabel("Console line limit"), 4, 2)
        self.log_lines_spin = QSpinBox()
        self.log_lines_spin.setRange(200, 200000)
        self.log_lines_spin.setSingleStep(500)
        self.log_lines_spin.valueChanged.connect(self._on_setting_changed)
        grid.addWidget(self.log_lines_spin, 4, 3)
        card.layout.addLayout(grid)
        self.appearance_card = card
        return card

    def _build_browser_card(self) -> QWidget:
        card = Card(padding=16, spacing=12)
        header = QHBoxLayout()
        title = QLabel("Browser")
        title.setProperty("role", "h3")
        header.addWidget(title)
        header.addStretch(1)
        self.browser_pill = Pill("detecting...", level="muted")
        header.addWidget(self.browser_pill)
        card.layout.addLayout(header)

        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(10)
        grid.addWidget(QLabel("Browser engine"), 0, 0)
        self.browser_combo = QComboBox()
        for key, label in (("brave", "Brave (recommended)"), ("chrome", "Google Chrome"),
                           ("edge", "Microsoft Edge"), ("chromium", "Playwright Chromium"),
                           ("custom", "Custom executable...")):
            self.browser_combo.addItem(label, key)
        self.browser_combo.currentIndexChanged.connect(self._on_browser_kind)
        grid.addWidget(self.browser_combo, 0, 1)

        grid.addWidget(QLabel("Profile folder"), 1, 0)
        self.profile_combo = QComboBox()
        self.profile_combo.setEditable(False)
        self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        grid.addWidget(self.profile_combo, 1, 1)

        browse_profile = AnimatedButton("Browse...", kind="ghost")
        browse_profile.clicked.connect(self._browse_profile)
        grid.addWidget(browse_profile, 1, 2)

        grid.addWidget(QLabel("Custom path"), 2, 0)
        self.custom_path_edit = QLineEdit()
        self.custom_path_edit.setPlaceholderText(r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe")
        self.custom_path_edit.textChanged.connect(self._on_setting_changed)
        grid.addWidget(self.custom_path_edit, 2, 1)
        browse_exe = AnimatedButton("Find .exe...", kind="ghost")
        browse_exe.clicked.connect(self._browse_exe)
        grid.addWidget(browse_exe, 2, 2)

        grid.addWidget(QLabel("Window size"), 3, 0)
        size_row = QWidget()
        size_layout = QHBoxLayout(size_row)
        size_layout.setContentsMargins(0, 0, 0, 0)
        size_layout.setSpacing(8)
        self.width_spin = QSpinBox()
        self.width_spin.setRange(800, 3840)
        self.width_spin.setSingleStep(20)
        self.width_spin.valueChanged.connect(self._on_setting_changed)
        self.height_spin = QSpinBox()
        self.height_spin.setRange(600, 2160)
        self.height_spin.setSingleStep(20)
        self.height_spin.valueChanged.connect(self._on_setting_changed)
        size_layout.addWidget(self.width_spin)
        size_layout.addWidget(QLabel("\u00d7"))
        size_layout.addWidget(self.height_spin)
        size_layout.addStretch(1)
        grid.addWidget(size_row, 3, 1, 1, 2)

        grid.addWidget(QLabel("Start maximised"), 4, 0)
        self.maximized_toggle = ToggleSwitch(accent=self.ctx.palette.accent, track_off=self.ctx.palette.border)
        self.maximized_toggle.toggled.connect(self._on_setting_changed)
        grid.addWidget(self.maximized_toggle, 4, 1)

        grid.addWidget(QLabel("Extra browser flags"), 5, 0)
        self.args_edit = QLineEdit()
        self.args_edit.setPlaceholderText("--lang=en-US --disable-notifications")
        self.args_edit.textChanged.connect(self._on_setting_changed)
        grid.addWidget(self.args_edit, 5, 1, 1, 2)

        grid.addWidget(QLabel("Download folder"), 6, 0)
        self.download_edit = QLineEdit()
        self.download_edit.setPlaceholderText("default")
        self.download_edit.textChanged.connect(self._on_setting_changed)
        grid.addWidget(self.download_edit, 6, 1)
        browse_downloads = AnimatedButton("Browse...", kind="ghost")
        browse_downloads.clicked.connect(self._browse_downloads)
        grid.addWidget(browse_downloads, 6, 2)
        card.layout.addLayout(grid)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        probe = AnimatedButton("Re-detect browsers", kind="ghost", icon_text="\u21bb")
        probe.clicked.connect(self._redetect)
        actions.addWidget(probe)
        self.chromium_button = AnimatedButton("Download Chromium", kind="ghost", icon_text="\u2913")
        self.chromium_button.clicked.connect(self._install_chromium)
        actions.addWidget(self.chromium_button)
        actions.addStretch(1)
        self.browser_state_label = QLabel("")
        self.browser_state_label.setProperty("role", "faint")
        actions.addWidget(self.browser_state_label)
        card.layout.addLayout(actions)
        return card

    def _build_timeouts_card(self) -> QWidget:
        card = Card(padding=16, spacing=12)
        title = QLabel("Timeouts, retries and pacing")
        title.setProperty("role", "h3")
        card.layout.addWidget(title)
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(10)
        specs = [
            ("Action timeout", "action_ms", 1000, 600000, 1000, " ms", "How long a click/fill may take before it fails"),
            ("Navigation timeout", "navigation_ms", 1000, 900000, 1000, " ms", "Page load budget"),
            ("Retries per step", "step_retries", 0, 10, 1, "", "Extra attempts when a step fails"),
            ("Retry delay", "retry_delay_ms", 0, 30000, 100, " ms", "Wait before a retry"),
            ("Pause between steps", "delay_between_steps_ms", 0, 60000, 50, " ms", "Extra breathing room"),
            ("Pause between loops", "delay_between_loops_ms", 0, 600000, 100, " ms", "Cool-down after each loop"),
            ("Typing speed", "type_delay_ms", 0, 1000, 5, " ms/key", "Used by slow-typing steps"),
            ("Restart browser every N loops", "loop_restart_browser_after", 0, 10000, 1, " loops", "0 = never"),
        ]
        self.timeout_spins: dict[str, QSpinBox] = {}
        for row, (label, key, low, high, step, suffix, tip) in enumerate(specs):
            grid.addWidget(QLabel(label), row // 2, (row % 2) * 2)
            spin = QSpinBox()
            spin.setRange(low, high)
            spin.setSingleStep(step)
            spin.setSuffix(suffix)
            spin.setToolTip(tip)
            spin.valueChanged.connect(self._on_setting_changed)
            grid.addWidget(spin, row // 2, (row % 2) * 2 + 1)
            self.timeout_spins[key] = spin
        card.layout.addLayout(grid)
        return card

    def _build_run_card(self) -> QWidget:
        card = Card(padding=16, spacing=12)
        title = QLabel("Run defaults")
        title.setProperty("role", "h3")
        card.layout.addWidget(title)
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(10)
        grid.addWidget(QLabel("Default loop mode"), 0, 0)
        self.loop_mode_combo = QComboBox()
        for key, label in (("count", "Repeat N times"), ("duration", "Run for a duration"),
                           ("infinite", "Until stopped")):
            self.loop_mode_combo.addItem(label, key)
        self.loop_mode_combo.currentIndexChanged.connect(self._on_setting_changed)
        grid.addWidget(self.loop_mode_combo, 0, 1)

        grid.addWidget(QLabel("Default repetitions"), 0, 2)
        self.loop_count_spin = QSpinBox()
        self.loop_count_spin.setRange(1, 1000000)
        self.loop_count_spin.valueChanged.connect(self._on_setting_changed)
        grid.addWidget(self.loop_count_spin, 0, 3)

        grid.addWidget(QLabel("Default duration"), 1, 0)
        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(1, 1440)
        self.duration_spin.setSuffix(" min")
        self.duration_spin.valueChanged.connect(self._on_setting_changed)
        grid.addWidget(self.duration_spin, 1, 1)

        grid.addWidget(QLabel("Slow motion"), 1, 2)
        self.slow_mo_spin = QSpinBox()
        self.slow_mo_spin.setRange(0, 5000)
        self.slow_mo_spin.setSingleStep(50)
        self.slow_mo_spin.setSuffix(" ms")
        self.slow_mo_spin.valueChanged.connect(self._on_setting_changed)
        grid.addWidget(self.slow_mo_spin, 1, 3)

        toggles = [
            ("Headless by default", "headless", "Run without showing the browser window"),
            ("Stop on first error", "stop_on_error", "Otherwise the engine continues with the next step"),
            ("New browser each loop", "restart_browser_each_loop", "Slower but cleaner state"),
            ("Close browser when done", "close_browser_when_done", "Unchecked leaves the window open for you"),
            ("Screenshot on error", "screenshot_on_error", "Saves a PNG and logs the path"),
            ("Play a sound when finished", "sound_on_finish", "Short chime - great for long loops"),
        ]
        self.run_toggles: dict[str, ToggleSwitch] = {}
        for index, (label, key, tip) in enumerate(toggles):
            row = 2 + index // 2
            column = (index % 2) * 2
            holder = QWidget()
            holder_layout = QHBoxLayout(holder)
            holder_layout.setContentsMargins(0, 0, 0, 0)
            holder_layout.setSpacing(8)
            switch = ToggleSwitch(accent=self.ctx.palette.accent, track_off=self.ctx.palette.border)
            switch.toggled.connect(self._on_setting_changed)
            text = QLabel(label)
            text.setProperty("role", "muted")
            text.setToolTip(tip)
            holder_layout.addWidget(switch)
            holder_layout.addWidget(text)
            holder_layout.addStretch(1)
            grid.addWidget(holder, row, column, 1, 2)
            self.run_toggles[key] = switch
        card.layout.addLayout(grid)
        return card

    def _build_data_card(self) -> QWidget:
        card = Card(padding=16, spacing=12)
        title = QLabel("Files and folders")
        title.setProperty("role", "h3")
        card.layout.addWidget(title)
        self.folder_label = QLabel("")
        self.folder_label.setProperty("role", "faint")
        self.folder_label.setWordWrap(True)
        card.layout.addWidget(self.folder_label)

        row = QHBoxLayout()
        row.setSpacing(8)
        for label, path in (
            ("Scripts", scripts_dir()),
            ("Logs", logs_dir()),
            ("Profiles", profiles_dir()),
            ("Screenshots", screenshots_dir()),
            ("Data folder", app_data_dir()),
        ):
            button = AnimatedButton(label, kind="ghost")
            button.clicked.connect(lambda _checked=False, p=path: self._open_folder(p))
            row.addWidget(button)
        row.addStretch(1)
        card.layout.addLayout(row)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        reset = AnimatedButton("Reset all settings", kind="ghost", icon_text="\u21ba")
        reset.clicked.connect(self._reset)
        row2.addWidget(reset)
        sound_test = AnimatedButton("Test chime", kind="ghost", icon_text="\u266b")
        sound_test.clicked.connect(lambda: self.ctx.window and self.ctx.window.play_finish_sound())
        row2.addWidget(sound_test)
        row2.addStretch(1)
        card.layout.addLayout(row2)
        return card

    def _build_about_card(self) -> QWidget:
        card = Card(tone="alt", padding=16, spacing=8)
        row = QHBoxLayout()
        column = QVBoxLayout()
        column.setSpacing(2)
        title = QLabel(f"Clicks-Auto {__version__}")
        font = title.font()
        font.setBold(True)
        title.setFont(font)
        column.addWidget(title)
        link = QLabel(f'<a style="color:{self.ctx.palette.accent}" href="{APP_URL}">{APP_URL}</a>')
        link.setOpenExternalLinks(True)
        column.addWidget(link)
        row.addLayout(column, 1)
        about = AnimatedButton("About", kind="ghost", icon_text="\u2139")
        about.clicked.connect(self._show_about)
        row.addWidget(about)
        card.layout.addLayout(row)
        return card

    # ------------------------------------------------------------------ load
    def _load_values(self) -> None:
        settings = self.ctx.settings
        ui = settings.ui
        browser = settings.browser
        self._loading = True

        index = self.theme_combo.findData(ui.theme)
        self.theme_combo.setCurrentIndex(max(0, index))
        self._refresh_swatches(ui.theme)
        self.animations_toggle.setChecked(ui.animations)
        self.reduce_toggle.setChecked(ui.reduce_motion)
        self.speed_slider.setValue(int(ui.animation_speed * 100))
        self.speed_label.setText(f"{ui.animation_speed:.2f}x")
        self.compact_toggle.setChecked(ui.compact)
        self.toast_toggle.setChecked(ui.toasts)
        self.titlebar_toggle.setChecked(ui.native_titlebar)
        self.log_lines_spin.setValue(ui.log_max_lines)

        index = self.browser_combo.findData(browser.kind)
        self.browser_combo.setCurrentIndex(max(0, index))
        self.custom_path_edit.setText(browser.custom_path)
        self.width_spin.setValue(browser.window_width)
        self.height_spin.setValue(browser.window_height)
        self.maximized_toggle.setChecked(browser.start_maximized)
        self.args_edit.setText(" ".join(browser.extra_args))
        self.download_edit.setText(browser.download_dir)
        self._reload_profiles(browser.user_data_dir)

        timeouts = settings.timeouts
        for key, spin in self.timeout_spins.items():
            spin.setValue(int(getattr(timeouts, key)))

        run = settings.run
        index = self.loop_mode_combo.findData(run.loop_mode)
        self.loop_mode_combo.setCurrentIndex(max(0, index))
        self.loop_count_spin.setValue(run.loop_count)
        self.duration_spin.setValue(run.loop_duration_min)
        self.slow_mo_spin.setValue(run.slow_mo_ms)
        for key, switch in self.run_toggles.items():
            switch.setChecked(bool(getattr(run, key)))

        self.folder_label.setText(f"Everything lives in {human_path(app_data_dir())}")
        self._loading = False
        self._on_browser_kind()

    def _reload_profiles(self, current: str) -> None:
        from ...browser import app_profiles, available_profiles

        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItem("Isolated Clicks-Auto profile (recommended)", "")
        for path, label in app_profiles():
            self.profile_combo.addItem(f"Saved profile: {label}", path)
        for path, label in available_profiles(self.browser_combo.currentData() or "brave"):
            self.profile_combo.addItem(f"My real {label}", path)
        if current:
            self.profile_combo.addItem(current, current)
        index = self.profile_combo.findData(current)
        self.profile_combo.setCurrentIndex(max(0, index))
        self.profile_combo.blockSignals(False)
        self._profile_value = current

    # --------------------------------------------------------------- handlers
    def _schedule_save(self) -> None:
        self._save_timer.start()

    def _flush(self) -> None:
        self.ctx.save()

    def _on_theme_changed(self, _index: int) -> None:
        if getattr(self, "_loading", False):
            return
        key = self.theme_combo.currentData()
        self.ctx.set_theme(key)
        self._refresh_swatches(key)
        self.ctx.toast(f"Theme set to {self.theme_combo.currentText()}.", level="info")

    def _refresh_swatches(self, key: str) -> None:
        from ..theme import theme_accent_preview

        colors = theme_accent_preview(key)
        for label, color in zip(self._swatch_labels, colors):
            label.setStyleSheet(f"background: {color}; border-radius: 5px; border: 1px solid rgba(0,0,0,0.25);")

    def _on_animations(self, enabled: bool) -> None:
        self.ctx.settings.ui.animations = enabled
        MOTION.update_from(self.ctx.settings.ui)
        self._schedule_save()

    def _on_speed(self, value: int) -> None:
        speed = value / 100.0
        self.speed_label.setText(f"{speed:.2f}x")
        self.ctx.settings.ui.animation_speed = speed
        MOTION.update_from(self.ctx.settings.ui)
        self._schedule_save()

    def _on_setting_changed(self, *args) -> None:
        if getattr(self, "_loading", False):
            return
        settings = self.ctx.settings
        ui = settings.ui
        ui.reduce_motion = self.reduce_toggle.isChecked()
        ui.compact = self.compact_toggle.isChecked()
        ui.toasts = self.toast_toggle.isChecked()
        ui.native_titlebar = self.titlebar_toggle.isChecked()
        ui.log_max_lines = self.log_lines_spin.value()

        browser = settings.browser
        browser.custom_path = self.custom_path_edit.text().strip()
        browser.window_width = self.width_spin.value()
        browser.window_height = self.height_spin.value()
        browser.start_maximized = self.maximized_toggle.isChecked()
        browser.extra_args = self.args_edit.text().split() if self.args_edit.text().strip() else []
        browser.download_dir = self.download_edit.text().strip()

        for key, spin in self.timeout_spins.items():
            setattr(settings.timeouts, key, spin.value())

        run = settings.run
        run.loop_mode = self.loop_mode_combo.currentData()
        run.loop_count = self.loop_count_spin.value()
        run.loop_duration_min = self.duration_spin.value()
        run.slow_mo_ms = self.slow_mo_spin.value()
        for key, switch in self.run_toggles.items():
            setattr(run, key, switch.isChecked())

        self._schedule_save()

    def _on_browser_kind(self, *_args) -> None:
        kind = self.browser_combo.currentData()
        detected = detect_all()
        choice = detected.get(kind)
        if choice is not None:
            if choice.found:
                self.browser_pill.set_level("success", f"{choice.label} found")
                self.browser_state_label.setText(choice.path)
            else:
                self.browser_pill.set_level("warning", f"{choice.label} not found")
                self.browser_state_label.setText("Install it, or pick another browser / set a custom path.")
        else:
            self.browser_pill.set_level("muted", "custom path")
        self.custom_path_edit.setEnabled(kind == "custom")
        if getattr(self, "_loading", False):
            return
        self.ctx.settings.browser.kind = kind
        self._reload_profiles(self._profile_value if hasattr(self, "_profile_value") else "")
        self._schedule_save()

    def _on_profile_changed(self, _index: int) -> None:
        if getattr(self, "_loading", False):
            return
        value = self.profile_combo.currentData() or ""
        self._profile_value = value
        self.ctx.settings.browser.user_data_dir = value
        self._schedule_save()

    def _on_probe(self, detected: dict) -> None:
        if detected:
            self._on_browser_kind()

    def _redetect(self) -> None:
        if hasattr(detect_all, "cache_clear"):
            detect_all.cache_clear()
        self._on_browser_kind()
        self.ctx.toast("Re-checked the installed browsers.", level="info")

    def _browse_profile(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select a profile folder", str(profiles_dir()))
        if path:
            self.profile_combo.addItem(path, path)
            self.profile_combo.setCurrentIndex(self.profile_combo.count() - 1)
            self._on_profile_changed(self.profile_combo.currentIndex())

    def _browse_exe(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select the browser executable", "", "Executables (*.exe);;All files (*)")
        if path:
            self.custom_path_edit.setText(path)
            index = self.browser_combo.findData("custom")
            self.browser_combo.setCurrentIndex(index)

    def _browse_downloads(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Download folder")
        if path:
            self.download_edit.setText(path)

    def _open_folder(self, path: Path) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _install_chromium(self) -> None:
        if self._installer is not None and self._installer.isRunning():
            self.ctx.toast("Chromium is already downloading...", level="warning")
            return
        self.chromium_button.setEnabled(False)
        self.chromium_button.setText("\u2913  Downloading...")
        installer = ChromiumInstaller(self)
        installer.log.connect(lambda message: self.ctx.window and self.ctx.window.console.log("debug", message))
        installer.done.connect(self._on_chromium_done)
        installer.start()
        self._installer = installer
        self.ctx.toast("Downloading Chromium for Playwright - this can take a few minutes.", level="info")

    def _on_chromium_done(self, ok: bool, message: str) -> None:
        self.chromium_button.setEnabled(True)
        self.chromium_button.setText("\u2913  Download Chromium")
        if ok:
            # Detection is memoised, so a freshly installed Chromium only shows
            # up after the cache is dropped.
            refresh_browsers()
            self.ctx.toast("Chromium is ready - select 'Playwright Chromium' above.", level="success")
            self._on_browser_kind()
        else:
            self.ctx.toast(message or "Chromium download failed.", level="error")

    def _reset(self) -> None:
        from ...settings import Settings

        defaults = Settings()
        current = self.ctx.settings
        current.browser = defaults.browser
        current.timeouts = defaults.timeouts
        current.ui = defaults.ui
        current.run = defaults.run
        self.ctx.save()
        self._load_values()
        self.ctx.set_theme(defaults.ui.theme)
        self.ctx.toast("Settings restored to their defaults.", level="success")

    def _show_about(self) -> None:
        AboutDialog(self.ctx.window or self, palette=self.ctx.palette).exec()

    # ------------------------------------------------------------------ misc
    def apply_palette(self, palette) -> None:
        self.animations_toggle.set_colors(palette.accent, palette.border)
        self.reduce_toggle.set_colors(palette.accent, palette.border)
        self.compact_toggle.set_colors(palette.accent, palette.border)
        self.toast_toggle.set_colors(palette.accent, palette.border)
        self.titlebar_toggle.set_colors(palette.accent, palette.border)
        self.maximized_toggle.set_colors(palette.accent, palette.border)
        for switch in self.run_toggles.values():
            switch.set_colors(palette.accent, palette.border)
        self._refresh_swatches(self.ctx.settings.ui.theme)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.start_probe()
        self._load_values()
