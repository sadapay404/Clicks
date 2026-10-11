"""Worker threads: everything that touches Playwright runs inside one of these.

Qt widgets must only be touched from the GUI thread, Playwright's sync API only
from the thread that created it - these workers bridge the two with signals and
a small command queue.
"""

from __future__ import annotations

import queue
from typing import Any, Optional

from PyQt6.QtCore import QThread, pyqtSignal

from ..engine import AutomationEngine, RunRequest, RunResult
from ..models import Script, Step
from ..recorder.builder import RecorderOptions
from ..recorder.session import RecorderSession


class RunWorker(QThread):
    """Runs a script through :class:`~clicks_auto.engine.AutomationEngine`."""

    log = pyqtSignal(str, str)
    status = pyqtSignal(str)
    loop_changed = pyqtSignal(int, int)
    step_started = pyqtSignal(int, int, object)
    step_result = pyqtSignal(int, object)
    progress = pyqtSignal(int, int)
    finished_run = pyqtSignal(object)
    session_kept_alive = pyqtSignal()
    session_closed = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, request: RunRequest, parent=None) -> None:
        super().__init__(parent)
        self.request = request
        self.engine: Optional[AutomationEngine] = None
        self.result: Optional[RunResult] = None
        self._close_requested = False
        self._abort = False

    # ------------------------------------------------------------------ thread
    def run(self) -> None:  # noqa: D401
        self.engine = AutomationEngine(
            self.request,
            on_log=lambda level, message: self.log.emit(level, str(message)),
            on_status=lambda status: self.status.emit(status),
            on_loop=lambda index, total: self.loop_changed.emit(index, total),
            on_step=lambda index, total, step: self.step_started.emit(index, total, step),
            on_step_result=lambda index, result: self.step_result.emit(index, result),
            on_progress=lambda done, total: self.progress.emit(done, total),
        )
        try:
            self.result = self.engine.run()
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
        self.finished_run.emit(self.result)

        if self.engine is not None and self.engine.session is not None and not self._abort:
            # The browser was deliberately left open - stay alive so the user can
            # browse, then close it from this same thread when asked.
            self.session_kept_alive.emit()
            while not self._close_requested and not self._abort:
                self.msleep(150)
            self.engine.close_browser_now()
            self.session_closed.emit()

    # ---------------------------------------------------------------- control
    def stop(self) -> None:
        if self.engine is not None:
            self.engine.stop()

    def pause(self) -> None:
        if self.engine is not None:
            self.engine.pause()

    def resume(self) -> None:
        if self.engine is not None:
            self.engine.resume()

    def close_browser(self) -> None:
        self._close_requested = True
        if self.engine is not None:
            self.engine.stop()

    def abort(self) -> None:
        """Hard stop used when the app is quitting."""
        self._abort = True
        self._close_requested = True
        if self.engine is not None:
            self.engine.stop()

    @property
    def browser_open(self) -> bool:
        return bool(self.engine is not None and self.engine.session is not None)


class RecorderWorker(QThread):
    """Owns the recorder browser and streams recorded steps to the UI."""

    log = pyqtSignal(str, str)
    recording_status = pyqtSignal(str, str)      # state, detail
    step_added = pyqtSignal(int, object)
    counter = pyqtSignal(int)
    finished_recording = pyqtSignal(object)
    session_kept_alive = pyqtSignal()
    session_closed = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, launch, *, name: str, options: RecorderOptions, start_url: str = "",
                 keep_browser_open: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.launch = launch
        self.name = name
        self.options = options
        self.start_url = start_url
        self.keep_browser_open = keep_browser_open
        self.session: Optional[RecorderSession] = None
        self.script: Optional[Script] = None
        self._commands: "queue.Queue[tuple[str, Any]]" = queue.Queue()
        self._abort = False
        self._close_requested = False

    # ------------------------------------------------------------------ thread
    def run(self) -> None:  # noqa: D401
        self.session = RecorderSession(
            self.launch,
            name=self.name,
            options=self.options,
            start_url=self.start_url,
            on_log=lambda level, message: self.log.emit(level, str(message)),
            on_step=lambda count, step: (self.step_added.emit(count, step), self.counter.emit(count)),
            on_status=lambda state: self.recording_status.emit(state, ""),
        )
        try:
            self.session.start()
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
            self.recording_status.emit("failed", str(exc))
            return

        self.recording_status.emit("recording", "Recorder browser is running")
        while not self.session.finished and not self._abort:
            self._drain_commands()
            if self.session.finished or self._abort:
                break
            try:
                self.session.pump(180)
            except Exception as exc:  # noqa: BLE001
                self.log.emit("warn", f"recorder loop: {exc}")
                break
        self._drain_commands()

        try:
            self.script = self.session.finish()
        except Exception as exc:  # noqa: BLE001
            self.script = Script(name=self.name)
            self.log.emit("error", f"could not build the script: {exc}")

        if self.keep_browser_open and not self._abort:
            self.session_kept_alive.emit()
            self.recording_status.emit("saved", "Script saved - browser left open")
            while not self._close_requested and not self._abort:
                self._drain_commands()
                try:
                    self.session.pump(180)
                except Exception:
                    break
        self.session.close()
        self.session_closed.emit()
        self.finished_recording.emit(self.script)

    def _drain_commands(self) -> None:
        while True:
            try:
                command, payload = self._commands.get_nowait()
            except queue.Empty:
                return
            try:
                if command == "pause":
                    if self.session:
                        self.session.set_paused(bool(payload))
                        self.recording_status.emit("paused" if payload else "recording", "")
                elif command == "options":
                    if self.session:
                        self.session.set_options(payload)
                elif command == "manual_step":
                    if self.session:
                        self.session.add_manual_step(payload)
                elif command == "note":
                    if self.session:
                        self.session.note(str(payload))
                elif command == "stop":
                    if self.session:
                        self.session.request_stop()
                elif command == "close_browser":
                    self._close_requested = True
                    if self.session:
                        self.session.request_stop()
                elif command == "abort":
                    self._abort = True
                    if self.session:
                        self.session.request_stop()
            except Exception as exc:  # noqa: BLE001
                self.log.emit("warn", f"recorder command '{command}' failed: {exc}")

    # ---------------------------------------------------------------- control
    def send(self, command: str, payload: Any = None) -> None:
        self._commands.put((command, payload))

    def set_paused(self, paused: bool) -> None:
        self.send("pause", paused)

    def set_options(self, options: RecorderOptions) -> None:
        self.send("options", options)

    def add_manual_step(self, step: Step) -> None:
        self.send("manual_step", step)

    def finish_recording(self) -> None:
        self.send("stop")

    def close_browser(self) -> None:
        self.send("close_browser")

    def abort(self) -> None:
        self.send("abort")

    @property
    def browser_open(self) -> bool:
        return bool(self.session is not None and not self.session.finished)


class BrowserProbe(QThread):
    """Detects installed browsers off the GUI thread."""

    found = pyqtSignal(dict)

    def run(self) -> None:  # noqa: D401
        from ..browser import detect_all

        try:
            self.found.emit(detect_all())
        except Exception:
            self.found.emit({})


class ChromiumInstaller(QThread):
    """Downloads Playwright's Chromium build (Settings -> Browser)."""

    log = pyqtSignal(str)
    done = pyqtSignal(bool, str)

    def run(self) -> None:  # noqa: D401
        from ..browser import install_playwright_chromium

        try:
            code = install_playwright_chromium(log=lambda message: self.log.emit(str(message)))
            self.done.emit(code == 0, "" if code == 0 else f"installer exited with code {code}")
        except Exception as exc:  # noqa: BLE001
            self.done.emit(False, str(exc))
