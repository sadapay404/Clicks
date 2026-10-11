"""GUI entry point: environment setup, splash screen and the main window."""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path
from typing import Optional

from . import APP_ID, APP_NAME, __version__
from .paths import app_data_dir, is_frozen, logs_dir


def configure_environment() -> None:
    """Environment tweaks that must happen before Qt starts."""
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
    os.environ.setdefault("PYTHONUTF8", "1")

    if is_frozen():
        # Keep Playwright's bundled node + browsers inside the app folder so the
        # portable build stays self contained.
        root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        os.environ.setdefault("PLAYWRIGHT_NODEJS_PATH", str(root / "playwright" / "driver" / "node.exe"))
        os.environ.setdefault("PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD", "1")
        if (root / "ms-playwright").exists():
            # A Chromium was shipped inside this build - prefer it (read only, no download).
            os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(root / "ms-playwright"))
        else:
            # Otherwise anything the user downloads lands in their own data folder.
            from .paths import playwright_browsers_dir

            os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(playwright_browsers_dir()))

    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"sadapay404.{APP_ID}.{__version__}")
        except Exception:
            pass


def excepthook(exc_type, exc_value, exc_tb) -> None:
    """Show unexpected errors instead of dying silently."""
    text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    try:
        log_file = logs_dir() / "crash.log"
        with log_file.open("a", encoding="utf-8") as handle:
            handle.write(text + "\n" + "-" * 70 + "\n")
    except Exception:
        log_file = None
    sys.stderr.write(text)
    try:
        from PyQt6.QtWidgets import QApplication, QMessageBox

        if QApplication.instance() is not None:
            box = QMessageBox()
            box.setIcon(QMessageBox.Icon.Critical)
            box.setWindowTitle(f"{APP_NAME} hit a problem")
            box.setText("Something unexpected happened.")
            box.setInformativeText(str(exc_value)[:400])
            if log_file:
                box.setDetailedText(f"Details were written to:\n{log_file}\n\n{text[-2000:]}")
            box.exec()
    except Exception:
        pass


def run_gui(argv: Optional[list[str]] = None) -> int:
    configure_environment()
    argv = list(sys.argv if argv is None else argv)

    from PyQt6.QtCore import QTimer
    from PyQt6.QtGui import QFont
    from PyQt6.QtWidgets import QApplication

    from .settings import Settings
    from .store import ScriptStore
    from .ui.context import AppContext
    from .ui.main_window import MainWindow, app_icon
    from .ui.theme import apply_stylesheet

    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName("sadapay404")
    app.setApplicationVersion(__version__)
    app.setWindowIcon(app_icon())
    app.setStyle("Fusion")

    base_font = QFont("Segoe UI Variable Display" if sys.platform == "win32" else "Noto Sans", 10)
    base_font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(base_font)

    if "--reset-settings" in argv:
        from .paths import settings_file

        try:
            settings_file().unlink()
        except OSError:
            pass

    settings = Settings.load().clamp()
    if "--no-animations" in argv:
        settings.ui.animations = False
    if "--light" in argv:
        settings.ui.theme = "daylight"

    apply_stylesheet(app, context_palette(settings), compact=settings.ui.compact)

    store = ScriptStore()
    store.ensure_example()

    context = AppContext(settings, store)
    window = MainWindow(context)

    self_test = "--self-test" in argv
    splash = None if self_test else (SplashScreen() if settings.ui.animations else None)
    if splash is not None:
        splash.show_animated()

    def reveal() -> None:
        window.show()
        window.raise_()
        if splash is not None:
            splash.finish(window)

    QTimer.singleShot(0 if self_test else (650 if splash is not None else 0), reveal)
    if self_test:
        QTimer.singleShot(1200, lambda: _run_self_test(app, window, context))
    sys.excepthook = excepthook
    return app.exec()


def _run_self_test(app, window, context) -> None:
    """Headless(-ish) self check used by CI to prove the packaged GUI really works."""
    import traceback

    report: list[str] = []
    ok = True
    try:
        for key in ("dashboard", "run", "recorder", "scripts", "schedules", "history", "settings"):
            window.show_page(key)
            app.processEvents()
            report.append(f"page {key}: ok")
        window.show_page("run")
        window.run_page.refresh_library()
        entries = context.store.list_entries()
        if entries:
            window.run_page.load_script(entries[0].path)
            window.run_page.start_run(dry_run=True)
            worker = window.run_page.worker
            deadline = 30_000
            waited = 0
            while worker is not None and worker.isRunning() and waited < deadline:
                app.processEvents()
                worker.wait(120)
                waited += 120
            report.append(f"dry run finished: {'yes' if worker and not worker.isRunning() else 'TIMEOUT'}")
        window.toasts.success("Self test finished")
        app.processEvents()
        report.append("toasts: ok")
    except Exception:
        ok = False
        report.append("EXCEPTION:\n" + traceback.format_exc())

    message = "\n".join(["Clicks-Auto self test", f"result: {'PASS' if ok else 'FAIL'}", *report])
    try:
        marker = app_data_dir() / "self-test-report.txt"
        marker.write_text(message, encoding="utf-8")
        print(message)
    except Exception:
        pass
    sys.stdout.flush()
    if window.recorder_page.busy():
        window.recorder_page.shutdown()
    app.exit(0 if ok else 1)


def context_palette(settings):
    from .ui.theme import get_palette

    return get_palette(settings.ui.theme)


def _splash_class():
    from PyQt6.QtCore import QEasingCurve, Qt, QTimer, QVariantAnimation
    from PyQt6.QtGui import QColor, QFont, QPainter, QPen
    from PyQt6.QtWidgets import QWidget

    class Splash(QWidget):
        """Frameless splash with an animated ring + logo."""

        def __init__(self) -> None:
            super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.SplashScreen)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setFixedSize(360, 220)
            self._angle = 0
            self._progress = 0.0
            self._palette = None
            self._timer = QTimer(self)
            self._timer.setInterval(16)
            self._timer.timeout.connect(self._tick)
            self._fade = None

        def set_palette_colors(self, palette) -> None:
            self._palette = palette

        def show_animated(self) -> None:
            screen = self.screen()
            if screen is not None:
                geometry = screen.availableGeometry()
                self.move(geometry.center().x() - self.width() // 2,
                          geometry.center().y() - self.height() // 2)
            self.setWindowOpacity(0.0)
            self.show()
            self._timer.start()
            animation = QVariantAnimation(self)
            animation.setStartValue(0.0)
            animation.setEndValue(1.0)
            animation.setDuration(320)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            animation.valueChanged.connect(lambda value: self.setWindowOpacity(float(value)))
            animation.start()
            self._fade = animation

        def _tick(self) -> None:
            self._angle = (self._angle + 6) % 360
            self._progress = min(1.0, self._progress + 0.02)
            self.update()

        def finish(self, window) -> None:
            if self._fade is not None:
                self._fade.stop()
            animation = QVariantAnimation(self)
            animation.setStartValue(self.windowOpacity())
            animation.setEndValue(0.0)
            animation.setDuration(260)
            animation.setEasingCurve(QEasingCurve.Type.InCubic)
            animation.valueChanged.connect(lambda value: self.setWindowOpacity(float(value)))
            animation.finished.connect(self.close)
            animation.start()
            self._fade = animation

        def paintEvent(self, event) -> None:  # noqa: N802
            from PyQt6.QtCore import QRectF

            palette = self._palette
            accent = QColor(palette.accent if palette else "#5b8cff")
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setBrush(QColor(palette.surface if palette else "#141b33"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(self.rect(), 20, 20)

            painter.save()
            painter.translate(self.width() / 2, 84)
            pen = QPen(accent)
            pen.setWidth(4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawArc(QRectF(-34, -34, 68, 68), self._angle * 16, 110 * 16)
            ghost = QColor(accent)
            ghost.setAlpha(60)
            pen.setColor(ghost)
            painter.setPen(pen)
            painter.drawEllipse(QRectF(-34, -34, 68, 68))
            painter.restore()

            font = QFont(self.font())
            font.setPointSize(font.pointSize() + 8)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor(palette.text if palette else "#eef2ff"))
            painter.drawText(QRectF(0, 132, self.width(), 34), Qt.AlignmentFlag.AlignCenter, APP_NAME)

            font.setPointSize(font.pointSize() - 10)
            font.setBold(False)
            painter.setFont(font)
            painter.setPen(QColor(palette.text_faint if palette else "#6f79a0"))
            painter.drawText(QRectF(0, 164, self.width(), 24), Qt.AlignmentFlag.AlignCenter,
                             f"v{__version__}  \u2022  starting up")
            painter.end()

    return Splash


def SplashScreen():  # noqa: N802 - factory used by run_gui
    klass = _splash_class()
    splash = klass()
    try:
        from .settings import Settings
        from .ui.theme import get_palette

        splash.set_palette_colors(get_palette(Settings.load().ui.theme))
    except Exception:
        pass
    return splash


def main(argv: Optional[list[str]] = None) -> int:
    return run_gui(argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
