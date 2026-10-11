"""The application window: sidebar, animated pages, title bar, tray and wiring."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, __version__
from ..scheduler import Schedule, ScheduleManager
from . import theme
from .anim import MOTION, AnimatedStackedWidget, fade_in
from .context import AppContext
from .dialogs import WelcomeDialog
from .pages import (
    DashboardPage,
    HistoryPage,
    RecorderPage,
    RunPage,
    SchedulesPage,
    ScriptsPage,
    SettingsPage,
)
from .theme import Palette, apply_stylesheet
from .widgets.common import AnimatedButton, Pill, ToastManager
from .widgets.sidebar import Sidebar


class TitleBar(QWidget):
    """Custom frameless title bar with dragging, double click maximise and actions."""

    page_requested = pyqtSignal(str)

    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.window_ref = window
        self.setObjectName("TopBar")
        self.setFixedHeight(52)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 10, 8)
        layout.setSpacing(10)

        self.page_title = QLabel("Dashboard")
        font = self.page_title.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 2)
        self.page_title.setFont(font)
        layout.addWidget(self.page_title)

        self.status_pill = Pill("ready", level="muted")
        layout.addWidget(self.status_pill)
        layout.addStretch(1)

        self.quick_record = AnimatedButton("Record", kind="danger", icon_text="\u25cf",
                                           accent="#ff6188", ripple_alpha=70)
        self.quick_record.setToolTip("Open the recorder (Ctrl+R)")
        self.quick_record.clicked.connect(lambda: self.page_requested.emit("recorder"))
        layout.addWidget(self.quick_record)

        self.quick_run = AnimatedButton("Run", kind="primary", icon_text="\u25b6", accent="#5b8cff")
        self.quick_run.setToolTip("Open the run page (F9)")
        self.quick_run.clicked.connect(lambda: self.page_requested.emit("run"))
        layout.addWidget(self.quick_run)

        self.quick_stop = AnimatedButton("Stop", kind="ghost", icon_text="\u25a0")
        self.quick_stop.setToolTip("Stop the current run (F10)")
        self.quick_stop.clicked.connect(self.window_ref.stop_everything)
        layout.addWidget(self.quick_stop)

        self.theme_button = QPushButton("\u25d1")
        self.theme_button.setProperty("kind", "flat")
        self.theme_button.setFixedSize(34, 34)
        self.theme_button.setToolTip("Cycle theme (Ctrl+T)")
        self.theme_button.clicked.connect(self.window_ref.cycle_theme)
        layout.addWidget(self.theme_button)

        for glyph, tip, slot in (
            ("\u2013", "Minimise", self.window_ref.showMinimized),
            ("\u25a1", "Maximise / restore", self.window_ref.toggle_maximise),
            ("\u2715", "Close", self.window_ref.close),
        ):
            button = QPushButton(glyph)
            button.setProperty("kind", "flat")
            button.setFixedSize(34, 34)
            button.setToolTip(tip)
            button.clicked.connect(slot)
            if glyph == "\u2715":
                button.setObjectName("CloseButton")
            layout.addWidget(button)

    # ---------------------------------------------------------------- dragging
    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self.window_ref.toggle_maximise()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.window_ref.windowHandle()
            if handle is not None:
                handle.startSystemMove()

    def set_title(self, text: str) -> None:
        self.page_title.setText(text)


class MainWindow(QMainWindow):
    def __init__(self, context: AppContext, *, show_welcome: bool = True) -> None:
        super().__init__(None)
        self.ctx = context
        self._show_welcome = show_welcome
        context.window = self
        self.settings = context.settings
        self.toasts = ToastManager(self, palette=context.palette)
        context.toasts = self.toasts

        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.setMinimumSize(1040, 680)
        flags = Qt.WindowType.Window
        if not self.settings.ui.native_titlebar:
            flags |= Qt.WindowType.FramelessWindowHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setWindowIcon(app_icon())

        self._resize_edge = None
        self._drag_position: Optional[QPoint] = None
        self._recording_pulse = None

        self._build_ui()
        self._build_pages()
        self._wire()
        self._build_shortcuts()
        self._build_tray()
        self._build_scheduler()

        self.resize(self.settings.ui.window_width, self.settings.ui.window_height)
        self.setStyleSheet("")
        apply_stylesheet(QApplication.instance(), context.palette, compact=self.settings.ui.compact)
        self.statusBar().showMessage("Ready.")
        self.show_page(self.settings.ui.start_page or "dashboard", animate=False)
        self.allow_welcome = self._show_welcome
        QTimer.singleShot(90, self.sidebar.play_entrance)
        QTimer.singleShot(120, self._welcome_if_needed)
        QTimer.singleShot(80, lambda: fade_in(self.centralWidget(), 260) if MOTION.enabled else None)

    # ------------------------------------------------------------------- build
    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.sidebar = Sidebar(root, palette=self.ctx.palette, width=self.settings.ui.sidebar_width)
        self.sidebar.set_version(f"v{__version__}")
        root_layout.addWidget(self.sidebar)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self.title_bar = TitleBar(self)
        right_layout.addWidget(self.title_bar)

        self.page_host = AnimatedStackedWidget()
        self.page_host.setObjectName("PageHost")
        right_layout.addWidget(self.page_host, 1)
        root_layout.addWidget(right, 1)

        self.setCentralWidget(root)
        self.setContentsMargins(0, 0, 0, 0)

    def _build_pages(self) -> None:
        self.pages: dict[str, QWidget] = {
            "dashboard": DashboardPage(self.ctx, self),
            "run": RunPage(self.ctx, self),
            "recorder": RecorderPage(self.ctx, self),
            "scripts": ScriptsPage(self.ctx, self),
            "schedules": SchedulesPage(self.ctx, self.scheduler_placeholder(), self),
            "history": HistoryPage(self.ctx, self),
            "settings": SettingsPage(self.ctx, self),
        }
        for page in self.pages.values():
            self.page_host.addWidget(page)

    def scheduler_placeholder(self):
        """Real manager is created in _build_scheduler; pages are built first."""
        return getattr(self, "_scheduler", None)

    # -------------------------------------------------------------------- wire
    def _wire(self) -> None:
        self.dashboard: DashboardPage = self.pages["dashboard"]      # type: ignore[assignment]
        self.run_page: RunPage = self.pages["run"]                   # type: ignore[assignment]
        self.recorder_page: RecorderPage = self.pages["recorder"]    # type: ignore[assignment]
        self.scripts_page: ScriptsPage = self.pages["scripts"]       # type: ignore[assignment]
        self.schedules_page: SchedulesPage = self.pages["schedules"]  # type: ignore[assignment]
        self.history_page: HistoryPage = self.pages["history"]       # type: ignore[assignment]
        self.settings_page: SettingsPage = self.pages["settings"]    # type: ignore[assignment]

        self.sidebar.navigate.connect(lambda key: self.show_page(key))
        self.title_bar.page_requested.connect(lambda key: self.show_page(key))

        self.dashboard.record_requested.connect(lambda: self.show_page("recorder"))
        self.dashboard.run_requested.connect(lambda: self.show_page("run"))
        self.dashboard.script_activated.connect(self._open_script)
        self.scripts_page.run_requested.connect(self._run_script_path)
        self.recorder_page.script_saved.connect(self._on_script_saved)
        self.run_page.state_changed.connect(self._on_state_changed)
        self.recorder_page.state_changed.connect(self._on_state_changed)
        self.schedules_page.run_now.connect(self.run_schedule_now)
        self.ctx.navigate.connect(self.show_page)
        self.ctx.palette_changed.connect(self._on_palette_changed)
        self.ctx.status_message.connect(lambda text, level: self.set_status(text, level))
        self.ctx.settings_saved.connect(self._persist_window)

    def _build_shortcuts(self) -> None:
        shortcuts = [
            ("F9", lambda: self._run_current()),
            ("F10", self.stop_everything),
            ("Ctrl+R", lambda: self.show_page("recorder")),
            ("Ctrl+T", self.cycle_theme),
            ("Ctrl+,", lambda: self.show_page("settings")),
            ("Ctrl+S", self._save_current_script),
            ("Ctrl+1", lambda: self.show_page("dashboard")),
            ("Ctrl+2", lambda: self.show_page("run")),
            ("Ctrl+3", lambda: self.show_page("recorder")),
            ("Ctrl+4", lambda: self.show_page("scripts")),
            ("Ctrl+5", lambda: self.show_page("schedules")),
            ("Ctrl+6", lambda: self.show_page("history")),
            ("Ctrl+7", lambda: self.show_page("settings")),
            ("Ctrl+Q", self.close),
        ]
        for sequence, slot in shortcuts:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(slot)

    def _build_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = None
            return
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip(f"{APP_NAME} {__version__}")
        menu = QMenu(self)
        menu.addAction("Open Clicks-Auto", self._restore_from_tray)
        menu.addAction("Record a session", lambda: self._tray_goto("recorder"))
        menu.addAction("Run a script", lambda: self._tray_goto("run"))
        menu.addSeparator()
        menu.addAction("Stop everything", self.stop_everything)
        menu.addSeparator()
        menu.addAction("Quit", self.close)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self._restore_from_tray()
            if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None
        )
        self.tray.show()
        self.ctx.tray = self.tray

    def _build_scheduler(self) -> None:
        self._scheduler = ScheduleManager(self._on_schedule_due)
        self.scheduler = self._scheduler
        self.schedules_page.scheduler = self._scheduler
        self.schedules_page.refresh()
        self._scheduler.start()

    # -------------------------------------------------------------------- pages
    def show_page(self, key: str, *, animate: bool = True) -> None:
        if key not in self.pages:
            return
        index = list(self.pages).index(key)
        self.page_host.slide_to(index, duration=280)
        self.title_bar.set_title({
            "dashboard": "Dashboard",
            "run": "Run",
            "recorder": "Record Session",
            "scripts": "Scripts",
            "schedules": "Schedules",
            "history": "History",
            "settings": "Settings",
        }.get(key, key.title()))
        self.sidebar.set_active_key(key, animate=animate)
        window = self.pages[key]
        if hasattr(window, "refresh_library"):
            window.refresh_library()
        self.settings.ui.start_page = key
        self.statusBar().showMessage(f"{key.title()} ready", 2500)

    # ------------------------------------------------------------------ actions
    def toggle_maximise(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def cycle_theme(self) -> None:
        keys = list(theme.PALETTES)
        current = self.settings.ui.theme
        try:
            next_key = keys[(keys.index(current) + 1) % len(keys)]
        except ValueError:
            next_key = theme.DEFAULT_THEME
        self.ctx.set_theme(next_key)
        self.toasts.info(f"Theme: {theme.get_palette(next_key).label}", title="Appearance")

    def _on_palette_changed(self, palette: Palette) -> None:
        app = QApplication.instance()
        if app is not None:
            apply_stylesheet(app, palette, compact=self.settings.ui.compact)
        self.sidebar.set_palette(palette)
        self.title_bar.quick_record.set_accent(palette.danger)
        self.title_bar.quick_run.set_accent(palette.accent)
        self.title_bar.quick_stop.set_accent(palette.accent)
        for page in self.pages.values():
            if hasattr(page, "apply_palette"):
                page.apply_palette(palette)
        self.toasts.set_palette(palette)
        self.title_bar.status_pill.set_level(self.title_bar.status_pill.property("level") or "muted")
        self.update()

    def set_status(self, title: str, level: str = "info", detail: str = "") -> None:
        self.title_bar.status_pill.set_level(level, title)
        self.sidebar.set_status(title, detail or "Clicks-Auto", level=level)
        self.statusBar().showMessage(title, 4000)

    def _on_state_changed(self, title: str, detail: str, level: str) -> None:
        self.set_status(title, level, detail)

    def _open_script(self, path: str) -> None:
        self.scripts_page.open_script(path)
        self.show_page("scripts")

    def _run_script_path(self, path: str) -> None:
        self.run_page.refresh_library()
        if path:
            self.run_page.load_script(Path(path))

    def _run_current(self) -> None:
        if self.run_page.busy():
            self.toasts.warning("A run is already in progress.")
            return
        self.show_page("run")
        QTimer.singleShot(220, self.run_page.start_run)

    def _save_current_script(self) -> None:
        if self.sidebar.active() == "scripts" and self.scripts_page.script is not None:
            self.scripts_page.save_script()
        else:
            self.toasts.info("Open a script in the Scripts page to save it.")

    def _on_script_saved(self, path: str) -> None:
        self.run_page.refresh_library()
        self.scripts_page.refresh_library()
        self.dashboard.refresh()

    def stop_everything(self) -> None:
        stopped = False
        if self.run_page.busy():
            self.run_page.stop_run()
            stopped = True
        if self.recorder_page.busy():
            self.recorder_page.stop_recording()
            stopped = True
        if stopped:
            self.toasts.warning("Stopping - the browser will close in a moment.", title="Stop requested")
        else:
            self.toasts.info("Nothing is running right now.")

    def play_finish_sound(self) -> None:
        if not self.settings.run.sound_on_finish:
            return
        try:
            if sys.platform == "win32":
                import winsound

                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            else:
                QApplication.beep()
        except Exception:
            QApplication.beep()

    # --------------------------------------------------------------- schedules
    def _on_schedule_due(self, schedule: Schedule) -> None:
        self.toasts.info(f"Starting '{schedule.name}' ({schedule.describe()})",
                         title="Scheduled run")
        self.run_schedule(schedule, trigger="schedule")

    def run_schedule_now(self, schedule: Schedule) -> None:
        self.run_schedule(schedule, trigger="manual")

    def run_schedule(self, schedule: Schedule, *, trigger: str = "schedule") -> None:
        path = Path(schedule.script_path) if schedule.script_path else None
        if path is None or not path.exists():
            self.toasts.error(f"Script not found: {schedule.script_path}", title="Schedule failed")
            return
        if self.run_page.busy():
            self.toasts.warning("A run is already in progress - the schedule will be skipped.",
                                title="Busy")
            return
        self.show_page("run")
        self.run_page.load_script(path)
        self.run_page.set_mode(schedule.loop_mode, schedule.loop_count, headless=schedule.headless)
        QTimer.singleShot(260, lambda: self.run_page.start_run(trigger=trigger))

    # -------------------------------------------------------------------- tray
    def _restore_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _tray_goto(self, key: str) -> None:
        self._restore_from_tray()
        self.show_page(key)

    # ------------------------------------------------------------------ window
    def _persist_window(self) -> None:
        if self.isMaximized() or self.isFullScreen():
            return
        self.settings.ui.window_width = max(1040, self.width())
        self.settings.ui.window_height = max(680, self.height())
        try:
            self.settings.save()
        except Exception:
            pass

    def _welcome_if_needed(self) -> None:
        # ``allow_welcome`` lets headless tests and scripted launches opt out;
        # a modal dialog nobody can answer would otherwise block forever.
        if not self.allow_welcome:
            return
        if self.settings.first_run_done or not self.isVisible():
            return
        self.settings.first_run_done = True
        self.ctx.save()
        WelcomeDialog(self, palette=self.ctx.palette).exec()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._layout_toasts()

    def _layout_toasts(self) -> None:
        self.toasts.host = self
        for index, toast in enumerate(self.toasts.toasts):
            toast.move(self.width() - toast.width() - 20, 70 + index * (toast.height() + 10))

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        self._update_cursor(event.position().toPoint())

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self.settings.ui.native_titlebar or event.button() != Qt.MouseButton.LeftButton:
            return
        edge = self._edge_at(event.position().toPoint())
        if edge is not None:
            handle = self.windowHandle()
            if handle is not None:
                handle.startSystemResize(edge)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.unsetCursor()

    def _edge_at(self, point: QPoint):
        margin = 6
        left = point.x() <= margin
        right = point.x() >= self.width() - margin
        top = point.y() <= margin
        bottom = point.y() >= self.height() - margin
        if top and left:
            return Qt.Edge.TopEdge | Qt.Edge.LeftEdge
        if top and right:
            return Qt.Edge.TopEdge | Qt.Edge.RightEdge
        if bottom and left:
            return Qt.Edge.BottomEdge | Qt.Edge.LeftEdge
        if bottom and right:
            return Qt.Edge.BottomEdge | Qt.Edge.RightEdge
        if left:
            return Qt.Edge.LeftEdge
        if right:
            return Qt.Edge.RightEdge
        if top:
            return Qt.Edge.TopEdge
        if bottom:
            return Qt.Edge.BottomEdge
        return None

    def _update_cursor(self, point: QPoint) -> None:
        if self.settings.ui.native_titlebar or self.isMaximized():
            self.unsetCursor()
            return
        edge = self._edge_at(point)
        cursors = {
            Qt.Edge.LeftEdge: Qt.CursorShape.SizeHorCursor,
            Qt.Edge.RightEdge: Qt.CursorShape.SizeHorCursor,
            Qt.Edge.TopEdge: Qt.CursorShape.SizeVerCursor,
            Qt.Edge.BottomEdge: Qt.CursorShape.SizeVerCursor,
            Qt.Edge.TopEdge | Qt.Edge.LeftEdge: Qt.CursorShape.SizeFDiagCursor,
            Qt.Edge.BottomEdge | Qt.Edge.RightEdge: Qt.CursorShape.SizeFDiagCursor,
            Qt.Edge.TopEdge | Qt.Edge.RightEdge: Qt.CursorShape.SizeBDiagCursor,
            Qt.Edge.BottomEdge | Qt.Edge.LeftEdge: Qt.CursorShape.SizeBDiagCursor,
        }
        if edge in cursors:
            self.setCursor(cursors[edge])
        else:
            self.unsetCursor()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._persist_window()
        if self.run_page.busy() or self.recorder_page.busy():
            from PyQt6.QtWidgets import QMessageBox

            answer = QMessageBox.question(
                self, "Clicks-Auto is still working",
                "A run or recording is in progress. Stop it and quit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        try:
            self._scheduler.stop()
        except Exception:
            pass
        self.run_page.shutdown()
        self.recorder_page.shutdown()
        self.settings.ui.window_width = self.width()
        self.settings.ui.window_height = self.height()
        self.ctx.save()
        if self.tray is not None:
            self.tray.hide()
        event.accept()


def app_icon() -> QIcon:
    """Draw the app icon programmatically (no external asset needed)."""
    size = 128
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    gradient_color = QColor("#5b8cff")
    painter.setBrush(QColor("#141b33"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(6, 6, size - 12, size - 12, 28, 28)
    painter.setBrush(gradient_color)
    painter.drawEllipse(size // 2 - 16, size // 2 - 16, 32, 32)
    pen = painter.pen()
    pen.setColor(gradient_color)
    pen.setWidth(7)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(size // 2 - 40, size // 2 - 40, 80, 80)
    painter.end()
    return QIcon(pixmap)
