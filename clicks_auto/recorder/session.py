"""Playwright glue for the interactive session recorder.

Runs inside the automation worker thread; every action the user performs in the
recorder browser arrives here through an exposed binding, is translated by
:class:`~clicks_auto.recorder.builder.ActionBuilder` and streamed to the UI.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Optional

from ..browser import BrowserError, BrowserSession, LaunchRequest
from ..models import Script, Step
from ..paths import resource_path
from .builder import ActionBuilder, RecorderOptions

LogFn = Callable[[str, str], None]
StepFn = Callable[[int, Step], None]

DEFAULT_RECORDER_NOTICE = "Recorded with Clicks-Auto"


def recorder_script() -> str:
    """Return the injected JavaScript (bundled next to this module)."""
    return resource_path("clicks_auto", "recorder", "recorder.js").read_text(encoding="utf-8")


class RecorderSession:
    """Owns the recorder browser and accumulates the recorded steps."""

    def __init__(
        self,
        launch: LaunchRequest,
        *,
        name: str = "Recorded session",
        options: RecorderOptions | None = None,
        start_url: str = "",
        on_log: Optional[LogFn] = None,
        on_step: Optional[StepFn] = None,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.launch = launch
        self.name = name
        self.options = options or RecorderOptions()
        self.start_url = start_url
        self.on_log = on_log or (lambda level, message: None)
        self.on_step = on_step or (lambda count, step: None)
        self.on_status = on_status or (lambda text: None)

        self.session = BrowserSession(launch, logger=lambda m: self.on_log("info", m))
        self.builder = ActionBuilder(self.options)
        self.script: Script | None = None
        self.finished = False
        self.attached: set[int] = set()
        self._visible_page_id: int | None = None
        self._last_new_tab = (0.0, 0)
        self._page_listeners: dict[int, Any] = {}
        self._nav_seen: set[str] = set()
        self._paused = False
        self._stop_requested = False
        self._count = 0

    # ----------------------------------------------------------------- start
    def start(self) -> None:
        try:
            context = self.session.start()
        except BrowserError as exc:
            self.on_log("error", str(exc))
            raise
        context.expose_binding("__clicksAutoSend", self._on_binding)
        context.add_init_script(recorder_script())
        context.on("page", self._on_new_page)
        context.on("close", lambda: self._mark_finished("recorder browser closed"))
        for page in context.pages:
            self._attach_page(page)

        page = self.session.page()
        try:
            page.wait_for_timeout(300)
        except Exception:
            pass
        if self.start_url:
            self.on_log("info", f"Opening {self.start_url}")
            try:
                page.goto(self.start_url, wait_until="domcontentloaded")
            except Exception as exc:
                self.on_log("warn", f"Could not open the start page: {exc}")
        self.apply_options()
        self.on_log("ok", "Recorder is live - interact with the browser, then press Stop recording.")
        self.on_status("recording")

    # ---------------------------------------------------------------- events
    def _on_binding(self, source: Any, payload: str) -> None:
        try:
            event = json.loads(payload)
            event.setdefault("ts", int(time.time() * 1000))
            event.setdefault("frame_url", getattr(source, "frame_url", "") or "")
            if event.get("kind") == "navigation":
                url = str(event.get("url") or "")
                if event.get("spa") and url in self._nav_seen:
                    return
                self._nav_seen.add(url)
            self._ingest(event)
        except Exception as exc:  # pragma: no cover - defensive
            self.on_log("warn", f"recorder event dropped: {exc}")

    def _ingest(self, event: dict[str, Any]) -> None:
        steps = self.builder.handle(event)
        for step in steps:
            self._count += 1
            self.on_step(self._count, step)
        kind = event.get("kind")
        if kind == "click":
            el = event.get("el") or {}
            label = el.get("accessible_name") or el.get("text") or el.get("tag", "element")
            self.on_log("action", f"click -> {label}")

    def _attach_page(self, page: Any) -> None:
        key = id(page)
        if key in self.attached:
            return
        self.attached.add(key)
        try:
            page.on("framenavigated", lambda frame: self._on_frame_navigated(page, frame))
            page.on("dialog", lambda dialog: self._on_dialog(page, dialog))
            page.on("popup", lambda popup: self._on_new_page(popup))
            page.on("close", lambda: self._on_page_closed(page))
        except Exception:
            pass
        self._apply_options_to_page(page)

    def _on_frame_navigated(self, page: Any, frame: Any) -> None:
        try:
            if frame != page.main_frame:
                return
            url = frame.url
            if not url or url.startswith("about:"):
                return
            self._ingest({"kind": "navigation", "url": url, "ts": int(time.time() * 1000)})
        except Exception:
            pass

    def _on_new_page(self, page: Any) -> None:
        self._attach_page(page)
        self.on_log("action", "new tab opened")
        self._last_new_tab = (time.time(), id(page))
        try:
            pages = self.session.pages()
            index = pages.index(page) + 1 if page in pages else len(pages)
        except Exception:
            index = 1

        def report() -> None:
            try:
                self._ingest({
                    "kind": "newtab",
                    "url": page.url,
                    "index": index,
                    "ts": int(time.time() * 1000),
                })
            except Exception:
                pass

        try:
            page.wait_for_timeout(250)
        except Exception:
            pass
        report()

    def _on_page_closed(self, page: Any) -> None:
        try:
            if not self.session.pages():
                self._mark_finished("all tabs closed")
        except Exception:
            pass

    def _on_dialog(self, page: Any, dialog: Any) -> None:
        try:
            dialog_type = dialog.type
            message = (dialog.message or "")[:200]
            accepted = dialog_type != "beforeunload"  # beforeunload should not block closing
            self.on_log("action", f"{dialog_type} dialog: {message}")
            if dialog_type == "prompt":
                try:
                    dialog.accept(message.split(":")[-1].strip() or "text")
                except Exception:
                    pass
            else:
                try:
                    dialog.accept() if accepted else dialog.dismiss()
                except Exception:
                    pass
            self._ingest({
                "kind": "dialog",
                "dialog_type": dialog_type,
                "message": message,
                "accepted": True,
                "ts": int(time.time() * 1000),
            })
        except Exception:
            pass

    # ------------------------------------------------------------------ pump
    def pump(self, timeout_ms: int = 200) -> None:
        """Let Playwright dispatch pending events (call in a loop)."""
        if self._stop_requested:
            return
        pages = self.session.pages()
        if not pages:
            self._mark_finished("recorder browser closed")
            return
        self._check_visible_page(pages)
        try:
            pages[-1].wait_for_timeout(timeout_ms)
        except Exception:
            for page in pages:
                try:
                    page.wait_for_timeout(timeout_ms)
                    break
                except Exception:
                    continue
            else:
                self._mark_finished("browser went away")

    def _check_visible_page(self, pages: list[Any]) -> None:
        """Record manual tab switches by watching document visibility."""
        if len(pages) < 2:
            self._visible_page_id = id(pages[0]) if pages else None
            return
        for index, page in enumerate(pages):
            try:
                state = page.evaluate("document.visibilityState")
            except Exception:
                continue
            if state == "visible":
                key = id(page)
                if self._visible_page_id is not None and key != self._visible_page_id:
                    new_tab_ts, new_tab_id = self._last_new_tab
                    if new_tab_id == key and time.time() - new_tab_ts < 2.0:
                        pass  # the tab was opened by the previous click - already recorded
                    else:
                        self._ingest({
                            "kind": "switchtab",
                            "index": index + 1,
                            "ts": int(time.time() * 1000),
                        })
                        self.on_log("action", f"switched to tab {index + 1}")
                self._visible_page_id = key
                break

    # --------------------------------------------------------------- control
    def apply_options(self) -> None:
        for page in self.session.pages():
            self._apply_options_to_page(page)

    def _apply_options_to_page(self, page: Any) -> None:
        payload = {
            "enabled": not self._paused,
            "recordScroll": self.options.record_scroll,
            "recordHover": self.options.record_hover,
            "typingMode": self.options.typing_mode,
            "typingDelayMs": self.options.typing_delay_ms,
        }
        try:
            for frame in page.frames:
                try:
                    frame.evaluate("window.__clicksAuto && window.__clicksAuto.setOptions(arguments[0])", payload)
                except Exception:
                    continue
        except Exception:
            pass

    def set_options(self, options: RecorderOptions) -> None:
        self.options = options
        self.builder.options = options
        self.apply_options()

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        self.on_log("info", "Recording paused" if paused else "Recording resumed")
        self.apply_options()

    @property
    def paused(self) -> bool:
        return self._paused

    def add_manual_step(self, step: Step) -> None:
        self.builder.steps.append(step)
        self._count += 1
        self.on_step(self._count, step)
        self.on_log("action", f"manual step added: {step.label}")

    def note(self, message: str) -> None:
        self.builder._notes.append(message)

    def request_stop(self) -> None:
        self._stop_requested = True

    def _mark_finished(self, reason: str) -> None:
        if not self.finished:
            self.finished = True
            self.on_log("info", f"Recording finished ({reason}).")

    # ----------------------------------------------------------------- close
    def finish(self) -> Script:
        self.builder.finish()
        self.script = self.builder.build_script(self.name)
        self.script.description = self.script.description or DEFAULT_RECORDER_NOTICE
        if self.options.step_retries or self.options.action_timeout_ms:
            self.script.defaults.retries = self.options.step_retries
            self.script.defaults.step_timeout_ms = self.options.action_timeout_ms
        self.finished = True
        return self.script

    def stop_browser(self) -> None:
        try:
            self.session.stop()
        except Exception:
            pass

    def close(self) -> None:
        self.stop_browser()


def record_session(
    launch: LaunchRequest,
    *,
    name: str = "Recorded session",
    options: RecorderOptions | None = None,
    start_url: str = "",
    on_log: Optional[LogFn] = None,
    on_step: Optional[StepFn] = None,
    stop_event: Optional[Callable[[], bool]] = None,
) -> Script:
    """Blocking convenience wrapper (used by tests / CLI)."""
    session = RecorderSession(
        launch, name=name, options=options, start_url=start_url,
        on_log=on_log, on_step=on_step,
    )
    session.start()
    try:
        while not session.finished:
            if stop_event and stop_event():
                break
            session.pump(200)
    finally:
        script = session.finish()
        session.close()
    return script


def default_recorder_js_path() -> Path:
    return resource_path("clicks_auto", "recorder", "recorder.js")
