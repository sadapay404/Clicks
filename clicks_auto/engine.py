"""The playback engine: runs a :class:`~clicks_auto.models.Script` in a browser.

Designed to run inside a worker thread.  Every interesting thing that happens
is reported through callbacks so the GUI can stay responsive:

* ``on_log(level, message)``                - console line
* ``on_status(status)``                     - idle/preparing/running/paused/stopping
* ``on_loop(index, total)``                 - loop counters
* ``on_step(start_index, total, step)``     - a step is about to run
* ``on_step_result(index, step, status, message)``
* ``on_progress(done, total)``              - within the current loop
* ``on_finish(result)``                     - run summary
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from .browser import BrowserError, BrowserSession, LaunchRequest
from .datafeed import DataFeed, DataFeedError
from .locator import to_playwright
from .models import Script, SelectorCandidate, Step, substitute_variables
from .paths import screenshots_dir
from .timeutil import human_duration

# --------------------------------------------------------------------------


@dataclass
class RunRequest:
    script: Script
    loop_mode: str = "count"          # count | infinite | duration
    loop_count: int = 1
    duration_minutes: int = 10
    headless: bool = False
    slow_mo_ms: int = 0
    stop_on_error: bool = False
    restart_browser_each_loop: bool = False
    close_browser_when_done: bool = False
    keep_browser_open: bool = False
    browser_kind: str = "brave"
    browser_executable: str = ""
    user_data_dir: str = ""
    window_width: int = 1280
    window_height: int = 860
    extra_args: list[str] = field(default_factory=list)
    download_dir: str = ""
    action_timeout_ms: int = 20000
    navigation_timeout_ms: int = 45000
    step_retries: int = 2
    retry_delay_ms: int = 700
    delay_between_steps_ms: int = 250
    delay_between_loops_ms: int = 1200
    type_delay_ms: int = 40
    restart_browser_after_loops: int = 0
    data_file: str = ""
    variables: dict[str, str] = field(default_factory=dict)
    screenshot_on_error: bool = True
    dry_run: bool = False

    @property
    def total_loops(self) -> int:
        if self.loop_mode == "infinite":
            return 0
        if self.loop_mode == "duration":
            return 0
        return max(1, int(self.loop_count))


@dataclass
class StepResult:
    index: int
    step: Step
    status: str            # ok | retried | error | skipped
    message: str = ""
    duration_ms: int = 0
    fallback_used: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "type": self.step.type,
            "label": self.step.label,
            "description": self.step.description,
            "selector": self.step.selector,
            "status": self.status,
            "message": self.message,
            "duration_ms": self.duration_ms,
            "fallback_used": self.fallback_used,
        }


@dataclass
class RunResult:
    script_name: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    loops_completed: int = 0
    loops_attempted: int = 0
    steps_ok: int = 0
    steps_failed: int = 0
    healed: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    stopped_by_user: bool = False
    outcome: str = "idle"          # completed | completed_with_errors | failed | stopped
    step_results: list[StepResult] = field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        return max(0.0, (self.finished_at or time.time()) - self.started_at)

    def to_dict(self) -> dict[str, Any]:
        return {
            "script": self.script_name,
            "started_at": datetime.fromtimestamp(self.started_at).isoformat(timespec="seconds"),
            "finished_at": datetime.fromtimestamp(self.finished_at or time.time()).isoformat(timespec="seconds"),
            "duration_seconds": round(self.duration_seconds, 1),
            "duration": human_duration(self.duration_seconds),
            "loops_completed": self.loops_completed,
            "loops_attempted": self.loops_attempted,
            "steps_ok": self.steps_ok,
            "steps_failed": self.steps_failed,
            "errors": self.errors[:50],
            "healed": self.healed[:50],
            "stopped_by_user": self.stopped_by_user,
            "outcome": self.outcome,
        }


class StepError(Exception):
    """A step failed in a way that is worth retrying."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class StopRequested(Exception):
    pass


# --------------------------------------------------------------------------


class AutomationEngine:
    def __init__(
        self,
        request: RunRequest,
        *,
        on_log: Optional[Callable[[str, str], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
        on_loop: Optional[Callable[[int, int], None]] = None,
        on_step: Optional[Callable[[int, int, Step], None]] = None,
        on_step_result: Optional[Callable[[int, StepResult], None]] = None,
        on_progress: Optional[Callable[[int, int], None]] = None,
        on_finish: Optional[Callable[[RunResult], None]] = None,
    ) -> None:
        self.request = request
        self.script = request.script
        self.on_log = on_log or (lambda level, message: None)
        self.on_status = on_status or (lambda status: None)
        self.on_loop = on_loop or (lambda index, total: None)
        self.on_step = on_step or (lambda index, total, step: None)
        self.on_step_result = on_step_result or (lambda index, result: None)
        self.on_progress = on_progress or (lambda done, total: None)
        self.on_finish = on_finish or (lambda result: None)

        self._stop = threading.Event()
        self._pause = threading.Event()
        self._pause.set()  # set == running
        self.session: BrowserSession | None = None
        self.page = None
        self.context = None
        self.variables: dict[str, Any] = {}
        self.feed: DataFeed | None = None
        self.result = RunResult(script_name=self.script.name)
        self._pending_dialog: dict[str, Any] | None = None
        self._loop_pages: list[Any] = []

    # ---------------------------------------------------------------- control
    def stop(self) -> None:
        self._stop.set()
        self._pause.set()

    def pause(self) -> None:
        self._pause.clear()

    def resume(self) -> None:
        self._pause.set()

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    # ------------------------------------------------------------------- run
    def run(self) -> RunResult:
        request = self.request
        self.result = RunResult(script_name=self.script.name)
        problems = self.script.validate()
        if problems:
            for problem in problems:
                self.on_log("warn", problem)
            if request.dry_run:
                self.on_log("info", "Dry run finished - fix the warnings above.")
                return self._finish("failed", stopped=False)

        if request.dry_run:
            return self._dry_run()

        if self.stopped:
            self.on_log("warn", "Stop was requested before playback began.")
            return self._finish("stopped", stopped=True)

        self._load_data_feed()
        self.on_status("preparing")
        stop_reason = "completed"

        try:
            if request.loop_mode == "duration":
                self._run_duration()
            elif request.loop_mode == "infinite":
                self._run_loops(None)
            else:
                self._run_loops(max(1, int(request.loop_count)))
        except StopRequested:
            stop_reason = "stopped"
            self.on_log("warn", "Stop requested - shutting the browser down.")
        except BrowserError as exc:
            self.on_log("error", str(exc))
            self.result.errors.append(str(exc))
            stop_reason = "failed"
        except Exception as exc:  # noqa: BLE001 - the worker must never die silently
            self.on_log("error", f"Unexpected failure: {exc}")
            self.result.errors.append(str(exc))
            stop_reason = "failed"
        finally:
            self._shutdown_browser()

        return self._finish(stop_reason, stopped=self.result.stopped_by_user)

    # ------------------------------------------------------------------ loops
    def _run_loops(self, total: Optional[int]) -> None:
        loop_index = 0
        while not self.stopped:
            if total is not None and loop_index >= total:
                break
            loop_index += 1
            self._run_single_loop(loop_index, total)

            if self.request.restart_browser_after_loops and loop_index % self.request.restart_browser_after_loops == 0:
                self.on_log("info", "Restarting the browser (periodic refresh).")
                self._shutdown_browser()

            if total is not None and loop_index >= total:
                break
            if self.request.delay_between_loops_ms:
                self.on_log("debug", f"Waiting {self.request.delay_between_loops_ms} ms before the next loop.")
                self._sleep(self.request.delay_between_loops_ms)

    def _run_duration(self) -> None:
        minutes = max(1, int(self.request.duration_minutes))
        deadline = time.time() + minutes * 60
        self.on_log("info", f"Running continuously for {minutes} minute(s) - press Stop to finish early.")
        loop_index = 0
        while not self.stopped and time.time() < deadline:
            loop_index += 1
            self._run_single_loop(loop_index, None)
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            if self.request.delay_between_loops_ms:
                self._sleep(min(self.request.delay_between_loops_ms, int(remaining * 1000)))

    def _run_single_loop(self, loop_index: int, total: Optional[int]) -> None:
        request = self.request
        self.result.loops_attempted = loop_index
        variables = self._loop_variables(loop_index)
        self.variables = variables
        self.on_loop(loop_index, total or 0)
        label = f"Loop {loop_index}" + (f"/{total}" if total else "")
        self.on_log("info", f"--- {label} --- {'-' * 12}")

        if not self.page or (hasattr(self.page, "is_closed") and self.page.is_closed()):
            self._start_browser()
        if not self._loop_pages:
            self._loop_pages = [self.page]

        steps = self.script.steps
        total_steps = len(steps)
        failed = False
        for index, step in enumerate(steps, start=1):
            self._wait_if_paused()
            if self.stopped:
                raise StopRequested()
            if not step.enabled:
                self.on_log("debug", f"[{index}/{total_steps}] skipped (disabled) {step.label}")
                continue
            self.on_step(index, total_steps, step)
            self.on_progress(index - 1, total_steps)
            result = self._execute_with_retries(step, index)
            self.on_step_result(index, result)
            self.result.step_results.append(result)
            if result.status == "error":
                failed = True
                self.result.steps_failed += 1
                self.result.errors.append(f"{label} step {index} ({step.label}): {result.message}")
                if request.stop_on_error:
                    self.on_log("error", "Stopping because 'stop on error' is enabled.")
                    self.result.outcome = "failed"
                    raise StopRequested()
            else:
                self.result.steps_ok += 1
            self.on_progress(index, total_steps)
            if request.delay_between_steps_ms and index < total_steps:
                self._sleep(request.delay_between_steps_ms)

        self.result.loops_completed += 1
        state = "with errors" if failed else "successfully"
        self.on_log("ok" if not failed else "warn", f"{label} finished {state}.")

    # ------------------------------------------------------------------ steps
    def _execute_with_retries(self, step: Step, index: int) -> StepResult:
        attempts = 1 + max(0, int(step.retries if step.retries is not None else self.request.step_retries))
        last_error = ""
        started = time.time()
        for attempt in range(1, attempts + 1):
            if self.stopped:
                return StepResult(index, step, "skipped", "run stopped", 0)
            try:
                used = self._execute_step(step, index)
                duration = int((time.time() - started) * 1000)
                status = "retried" if attempt > 1 else "ok"
                message = f"attempt {attempt}" if attempt > 1 else ""
                return StepResult(index, step, status, message, duration, used)
            except StopRequested:
                raise
            except StepError as exc:
                last_error = str(exc)
                if not exc.retryable and not step.optional:
                    break
            except Exception as exc:  # noqa: BLE001
                last_error = _friendly_error(exc)
            if attempt < attempts:
                delay = max(150, int(self.request.retry_delay_ms * attempt))
                self.on_log(
                    "warn",
                    f"[{index}] {step.label} failed (attempt {attempt}/{attempts}): {last_error}"
                    f" - retrying in {delay} ms",
                )
                self._sleep(delay)
        duration = int((time.time() - started) * 1000)
        if step.optional:
            self.on_log("warn", f"[{index}] {step.label} skipped (optional): {last_error}")
            return StepResult(index, step, "skipped", last_error, duration)
        self.on_log("error", f"[{index}] {step.label} failed: {last_error}")
        self._screenshot_on_error(index, step)
        return StepResult(index, step, "error", last_error, duration)

    def _execute_step(self, step: Step, index: int) -> int:
        """Execute one step; returns the fallback index that was used (0 = primary)."""
        handler = getattr(self, f"_do_{step.type}", None)
        if handler is None:
            raise StepError(f"Unsupported step type '{step.type}'", retryable=False)
        started = time.time()
        used = handler(step, index)
        elapsed = int((time.time() - started) * 1000)
        if elapsed > 150:
            self.on_log("debug", f"[{index}] {step.label} ok in {elapsed} ms")
        if step.wait_after_ms:
            self._sleep(step.wait_after_ms)
        return used or 0

    # ------------------------------------------------------------ locator glue
    @property
    def active_page(self):
        if self._loop_pages:
            for page in reversed(self._loop_pages):
                try:
                    if not page.is_closed():
                        return page
                except Exception:
                    continue
        return self.page

    def _locator_base(self, step: Step):
        page = self.active_page
        frame_chain = step.options.get("frame") or []
        locator = page
        for frame_selector in frame_chain:
            try:
                locator = locator.frame_locator(str(frame_selector))
            except Exception:
                break
        return locator

    def _find(self, step: Step, *, timeout_ms: Optional[int] = None, state: str = "visible"):
        """Resolve *step*'s element, walking the fallback chain (self healing).

        Returns ``(locator, fallback_index, candidate)``.
        """
        candidates = step.candidates()
        if not candidates:
            raise StepError(f"{step.label} has no selector recorded.", retryable=False)
        timeout = int(step.timeout_ms or timeout_ms or self._default_timeout(step))
        deadline = time.time() + timeout / 1000.0
        base = self._locator_base(step)
        errors: list[str] = []
        primary_probe = min(3.5, max(0.8, timeout / 1000.0 * 0.5))

        for order, candidate in enumerate(candidates):
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            selector = to_playwright(candidate)
            if not selector:
                continue
            probe = min(remaining, primary_probe if order == 0 else max(0.4, remaining * 0.4))
            try:
                locator = base.locator(selector)
                if candidate.index:
                    locator = locator.nth(candidate.index)
                locator.first.wait_for(state="attached", timeout=int(probe * 1000))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{candidate.display()} -> {_short_error(exc)}")
                continue
            if order:
                self.on_log(
                    "warn",
                    f"primary selector missed; used fallback #{order} ({candidate.display()}) - script healed",
                )
                self._heal(step, order, candidate)
            return locator, order, candidate
        detail = "; ".join(errors[:3]) or "element not found"
        raise StepError(f"could not find {step.description or step.selector} ({detail})")

    def _heal(self, step: Step, order: int, candidate: SelectorCandidate) -> None:
        """Promote the candidate that actually worked (self healing selectors)."""
        if order <= 0 or candidate.value == step.selector:
            return
        old_primary = SelectorCandidate(
            kind=step.selector_kind, value=step.selector, index=step.selector_index,
            score=1.0, label="previous primary",
        )
        remaining = [c for c in step.fallbacks if c.display() != candidate.display()]
        step.selector = candidate.value
        step.selector_kind = candidate.kind
        step.selector_index = candidate.index
        step.fallbacks = [old_primary] + remaining
        self.result.healed.append({
            "step": step.label,
            "description": step.description,
            "new_selector": candidate.display(),
            "old_selector": old_primary.display(),
        })

    def _default_timeout(self, step: Step) -> int:
        if step.type in ("goto", "reload", "go_back", "go_forward"):
            return int(self.request.navigation_timeout_ms)
        if step.type in ("wait",):
            return int(step.parameter("ms", 1000)) or 1000
        if step.type in ("wait_for", "assert_visible"):
            return int(step.parameter("timeout_ms", self.request.action_timeout_ms))
        return int(self.request.action_timeout_ms)

    # ------------------------------------------------------------- browser life
    def _start_browser(self) -> None:
        request = self.request
        launch = LaunchRequest(
            kind=request.browser_kind,
            executable=request.browser_executable,
            user_data_dir=request.user_data_dir,
            headless=request.headless,
            slow_mo_ms=request.slow_mo_ms,
            window_width=request.window_width,
            window_height=request.window_height,
            extra_args=request.extra_args,
            download_dir=request.download_dir,
            navigation_timeout_ms=request.navigation_timeout_ms,
        )
        self.session = BrowserSession(launch, logger=lambda message: self.on_log("info", message))
        self.context = self.session.start()
        self.context.on("close", lambda: self.on_log("warn", "Browser window was closed."))
        self.page = self.session.page()
        try:
            self.page.set_default_timeout(self.request.action_timeout_ms)
            self.page.set_default_navigation_timeout(self.request.navigation_timeout_ms)
        except Exception:
            pass
        self._loop_pages = [self.page]
        self.on_log("ok", "Browser ready.")

    def _shutdown_browser(self) -> None:
        if self.session is None:
            return
        keep_open = self.request.keep_browser_open
        if not self.request.close_browser_when_done:
            keep_open = True
        if self.stopped and self.request.close_browser_when_done:
            keep_open = False
        try:
            if keep_open and not self.stopped:
                self.on_log("info", "Leaving the browser window open.")
                # Playwright must keep running for the browser to stay alive, so
                # we intentionally skip stop() here; the worker keeps the
                # session object until the app closes.
                return
            self.session.stop()
            self.on_log("info", "Browser closed.")
        except Exception as exc:  # noqa: BLE001
            self.on_log("debug", f"browser shutdown: {exc}")
        finally:
            self.session = None
            self.context = None
            self.page = None
            self._loop_pages = []

    def close_browser_now(self) -> None:
        """Force the browser shut (called from the worker thread)."""
        try:
            if self.session is not None:
                self.session.stop()
                self.on_log("info", "Browser closed.")
        except Exception as exc:  # noqa: BLE001
            self.on_log("debug", f"browser shutdown: {exc}")
        finally:
            self.session = None
            self.context = None
            self.page = None
            self._loop_pages = []

    # --------------------------------------------------------------- variables
    def _loop_variables(self, loop_index: int) -> dict[str, Any]:
        now = datetime.now()
        variables: dict[str, Any] = dict(self.script.variables)
        variables.update(self.request.variables or {})
        variables.update({
            "__loop__": loop_index,
            "__loop_index__": loop_index - 1,
            "__loop_number__": loop_index,
            "__timestamp__": int(now.timestamp()),
            "__date__": now.strftime("%Y-%m-%d"),
            "__time__": now.strftime("%H:%M:%S"),
            "__datetime__": now.strftime("%Y-%m-%d %H:%M:%S"),
            "__script__": self.script.name,
        })
        if self.feed and len(self.feed):
            row = self.feed.next_row()
            for key, value in row.items():
                variables[str(key)] = value
            variables["__row__"] = self.feed.position
        total = self.request.total_loops
        if total:
            variables["__total_loops__"] = total
        return variables

    def _load_data_feed(self) -> None:
        path = self.request.data_file
        if not path:
            # script level data file (stored in options-less form: variables only)
            return
        try:
            self.feed = DataFeed.from_file(path)
            self.on_log("info", f"Data feed loaded: {self.feed.summary()}")
        except DataFeedError as exc:
            self.on_log("error", str(exc))
            self.result.errors.append(str(exc))

    def _sub(self, text: Any, *, secret: bool = False) -> str:
        if text is None:
            return ""
        resolved = substitute_variables(str(text), self.variables)
        if resolved != str(text) and not secret:
            self.on_log("debug", f"variable -> {resolved}")
        return resolved

    # ------------------------------------------------------------------ steps
    def _do_goto(self, step: Step, index: int) -> int:
        url = self._sub(step.value or step.parameter("url", ""))
        if not url:
            raise StepError("no URL given", retryable=False)
        if "://" not in url and not url.startswith(("about:", "data:")):
            url = "https://" + url
        page = self.active_page
        self.on_log("action", f"goto {url}")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=self.request.navigation_timeout_ms)
        except Exception as exc:  # noqa: BLE001
            message = _friendly_error(exc)
            if "ERR_ABORTED" in _raw_error(exc):
                self.on_log("warn", f"Navigation to {url} was aborted by the page (likely a redirect or download).")
            else:
                raise StepError(message) from exc
        self._wait_for_network(page)
        return 0

    def _do_click(self, step: Step, index: int) -> int:
        locator, used, _ = self._find(step)
        button = str(step.parameter("button", "left") or "left")
        click_count = int(step.parameter("click_count", 1) or 1)
        expect_popup = bool(step.parameter("expect_popup", False)) or step.options.get("expect_popup")
        self.on_log("action", f"click {step.description or step.selector}")
        timeout = int(step.timeout_ms or self.request.action_timeout_ms)
        if expect_popup:
            try:
                with self.active_page.expect_popup(timeout=timeout) as popup_info:
                    locator.click(timeout=timeout, button=button, click_count=click_count)
                popup = popup_info.value
                self._loop_pages.append(popup)
                try:
                    popup.wait_for_load_state("domcontentloaded", timeout=8000)
                except Exception:
                    pass
                return used
            except Exception as exc:  # noqa: BLE001
                if "Timeout" not in type(exc).__name__:
                    raise
                self.on_log("warn", "No popup opened - falling back to a normal click.")
        try:
            locator.click(timeout=timeout, button=button, click_count=click_count)
        except Exception as exc:  # noqa: BLE001
            if "intercepts pointer events" in _raw_error(exc) or "not stable" in _raw_error(exc):
                self.on_log("warn", "Element was covered - forcing the click.")
                locator.click(timeout=timeout, button=button, click_count=click_count, force=True)
            elif "outside of the viewport" in _raw_error(exc):
                locator.scroll_into_view_if_needed(timeout=timeout)
                locator.click(timeout=timeout, button=button, click_count=click_count)
            else:
                raise
        return used

    def _do_dblclick(self, step: Step, index: int) -> int:
        locator, used, _ = self._find(step)
        self.on_log("action", f"double click {step.description or step.selector}")
        locator.dblclick(timeout=int(step.timeout_ms or self.request.action_timeout_ms))
        return used

    def _do_fill(self, step: Step, index: int) -> int:
        locator, used, _ = self._find(step)
        secret = bool(step.parameter("secret", False))
        value = self._sub(step.value, secret=secret)
        shown = "********" if secret else value
        self.on_log("action", f"type '{shown}' into {step.description or step.selector}")
        clear_first = bool(step.parameter("clear_first", True))
        timeout = int(step.timeout_ms or self.request.action_timeout_ms)
        try:
            if clear_first:
                locator.fill(value, timeout=timeout)
            else:
                locator.click(timeout=timeout)
                locator.press_sequentially(value, delay=int(self.request.type_delay_ms), timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            if "contenteditable" in _raw_error(exc) or "not an <input>" in _raw_error(exc) or "Element is not an" in _raw_error(exc):
                self.on_log("warn", "Falling back to keyboard typing for this element.")
                locator.click(timeout=timeout)
                if clear_first:
                    self.active_page.keyboard.press("Control+a")
                    self.active_page.keyboard.press("Delete")
                locator.press_sequentially(value, delay=int(self.request.type_delay_ms), timeout=timeout)
            else:
                raise
        if step.parameter("press_enter", False):
            self.on_log("action", "press Enter")
            locator.press("Enter", timeout=timeout)
        return used

    def _do_type(self, step: Step, index: int) -> int:
        locator, used, _ = self._find(step)
        value = self._sub(step.value, secret=bool(step.parameter("secret", False)))
        delay = int(step.parameter("delay_ms", self.request.type_delay_ms) or 0)
        self.on_log("action", f"type {len(value)} character(s) slowly into {step.description or step.selector}")
        timeout = int(step.timeout_ms or self.request.action_timeout_ms)
        if step.parameter("clear_first", True):
            locator.fill("", timeout=timeout)
        locator.click(timeout=timeout)
        locator.press_sequentially(value, delay=delay, timeout=timeout)
        if step.parameter("press_enter", False):
            locator.press("Enter", timeout=timeout)
        return used

    def _do_clear(self, step: Step, index: int) -> int:
        locator, used, _ = self._find(step)
        self.on_log("action", f"clear {step.description or step.selector}")
        locator.fill("", timeout=int(step.timeout_ms or self.request.action_timeout_ms))
        return used

    def _do_select(self, step: Step, index: int) -> int:
        locator, used, _ = self._find(step)
        value = self._sub(step.value)
        by = str(step.parameter("by", "label") or "label")
        self.on_log("action", f"select '{value}' ({by}) in {step.description or step.selector}")
        timeout = int(step.timeout_ms or self.request.action_timeout_ms)
        if by == "label":
            try:
                locator.select_option(label=value, timeout=timeout)
                return used
            except Exception:  # noqa: BLE001 - fall back to value match
                self.on_log("debug", "no option matched by label - trying by value")
        if by == "index":
            locator.select_option(index=int(value or 0), timeout=timeout)
        else:
            locator.select_option(value=value, timeout=timeout)
        return used

    def _do_check(self, step: Step, index: int) -> int:
        return self._set_checked(step, True)

    def _do_uncheck(self, step: Step, index: int) -> int:
        return self._set_checked(step, False)

    def _set_checked(self, step: Step, wanted: bool) -> int:
        locator, used, _ = self._find(step)
        timeout = int(step.timeout_ms or self.request.action_timeout_ms)
        self.on_log("action", f"{'tick' if wanted else 'untick'} {step.description or step.selector}")
        try:
            (locator.check if wanted else locator.uncheck)(timeout=timeout)
            return used
        except Exception:  # noqa: BLE001 - custom widgets
            state = locator.get_attribute("aria-checked")
            target_state = "true" if wanted else "false"
            if state is None:
                state = "true" if locator.is_checked() else "false"
            if state != target_state:
                locator.click(timeout=timeout)
            return used

    def _do_hover(self, step: Step, index: int) -> int:
        locator, used, _ = self._find(step)
        self.on_log("action", f"hover {step.description or step.selector}")
        locator.hover(timeout=int(step.timeout_ms or self.request.action_timeout_ms))
        return used

    def _do_press(self, step: Step, index: int) -> int:
        key = self._sub(step.value or step.parameter("key", "Enter"))
        timeout = int(step.timeout_ms or self.request.action_timeout_ms)
        if step.selector:
            locator, used, _ = self._find(step)
            locator.press(key, timeout=timeout)
            self.on_log("action", f"press {key} in {step.description or step.selector}")
            return used
        self.active_page.keyboard.press(key)
        self.on_log("action", f"press {key}")
        return 0

    def _do_upload(self, step: Step, index: int) -> int:
        locator, used, _ = self._find(step)
        raw = self._sub(step.value or "")
        files = [line.strip().strip('"') for line in raw.splitlines() if line.strip()]
        if not files:
            raise StepError(
                "no files configured for this upload step - open the script editor and add the file paths",
                retryable=False,
            )
        missing = [f for f in files if not Path(f).exists()]
        if missing:
            raise StepError(
                "file(s) not found: " + ", ".join(missing[:3])
                + " - uploads use full paths on this computer",
                retryable=False,
            )
        self.on_log("action", f"upload {', '.join(Path(f).name for f in files[:3])}")
        locator.set_input_files(files, timeout=int(step.timeout_ms or self.request.action_timeout_ms))
        return used

    def _do_scroll(self, step: Step, index: int) -> int:
        timeout = int(step.timeout_ms or self.request.action_timeout_ms)
        if step.parameter("into_view", False) and step.selector:
            locator, used, _ = self._find(step, state="attached")
            locator.scroll_into_view_if_needed(timeout=timeout)
            self.on_log("action", f"scroll {step.description or step.selector} into view")
            return used
        dx = int(step.parameter("dx", 0) or 0)
        dy = int(step.parameter("dy", 600) or 0)
        self.on_log("action", f"scroll by ({dx}, {dy})")
        page = self.active_page
        if step.selector:
            locator, used, _ = self._find(step, state="attached")
            locator.hover(timeout=timeout)
            page.mouse.wheel(dx, dy)
            return used
        page.mouse.move(200, 300)
        page.mouse.wheel(dx, dy)
        return 0

    def _do_wait(self, step: Step, index: int) -> int:
        ms = int(self._sub(step.value or step.parameter("ms", 1000)) or 0)
        ms = max(0, min(ms, 3_600_000))
        self.on_log("action", f"wait {ms} ms")
        self._sleep(ms)
        return 0

    def _do_wait_for(self, step: Step, index: int) -> int:
        state = str(step.parameter("state", "visible") or "visible")
        timeout = int(step.parameter("timeout_ms", self.request.action_timeout_ms) or self.request.action_timeout_ms)
        locator, used, _ = self._find(step, timeout_ms=timeout, state=state)
        self.on_log("action", f"wait for {step.description or step.selector} to be {state}")
        locator.first.wait_for(state=state, timeout=timeout)
        self._wait_for_network(self.active_page)
        return used

    def _do_assert_text(self, step: Step, index: int) -> int:
        locator, used, _ = self._find(step)
        expected = self._sub(step.value)
        mode = str(step.parameter("match", "contains") or "contains")
        actual = get_text(locator)
        ok = compare_text(actual, expected, mode)
        label = step.description or step.selector
        if not ok:
            message = f"expected text of {label} to {mode} '{expected}' but found '{actual[:120]}'"
            if step.parameter("optional", False):
                self.on_log("warn", f"check failed (non fatal): {message}")
                return used
            raise StepError(message, retryable=False)
        self.on_log("ok", f"text check passed for {label}")
        return used

    def _do_assert_url(self, step: Step, index: int) -> int:
        expected = self._sub(step.value)
        mode = str(step.parameter("match", "contains") or "contains")
        actual = self.active_page.url
        if not compare_text(actual, expected, mode):
            raise StepError(f"expected URL to {mode} '{expected}' but the page is at '{actual}'", retryable=False)
        self.on_log("ok", f"URL check passed ({actual[:90]})")
        return 0

    def _do_assert_visible(self, step: Step, index: int) -> int:
        timeout = int(step.parameter("timeout_ms", 8000) or 8000)
        locator, used, _ = self._find(step, timeout_ms=timeout)
        locator.first.wait_for(state="visible", timeout=timeout)
        self.on_log("ok", f"{step.description or step.selector} is visible")
        return used

    def _do_extract(self, step: Step, index: int) -> int:
        locator, used, _ = self._find(step)
        name = str(step.parameter("variable", "") or "").strip()
        if not name:
            raise StepError("no variable name set for this extract step", retryable=False)
        attribute = str(step.parameter("attribute", "") or "").strip()
        if attribute:
            value = locator.get_attribute(attribute) or ""
        else:
            value = get_text(locator)
        self.variables[name] = value
        self.on_log("ok", f"stored '{_shorten(value, 60)}' in ${{{name}}}")
        return used

    def _do_set_var(self, step: Step, index: int) -> int:
        name = str(step.parameter("variable", "") or "").strip()
        value = self._sub(step.value)
        if not name:
            raise StepError("no variable name set", retryable=False)
        self.variables[name] = value
        self.on_log("ok", f"${{{name}}} = {_shorten(value, 60)}")
        return 0

    def _do_screenshot(self, step: Step, index: int) -> int:
        raw_name = self._sub(str(step.parameter("path", "") or "")).strip()
        if not raw_name:
            raw_name = f"shot_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{self.result.loops_attempted}.png"
        path = Path(raw_name)
        if not path.is_absolute():
            path = screenshots_dir() / path.name
        path.parent.mkdir(parents=True, exist_ok=True)
        full_page = bool(step.parameter("full_page", False))
        page = self.active_page
        if step.selector:
            locator, used, _ = self._find(step)
            locator.screenshot(path=str(path))
        else:
            page.screenshot(path=str(path), full_page=full_page)
        self.on_log("ok", f"screenshot saved to {path}")
        return 0

    def _do_run_js(self, step: Step, index: int) -> int:
        code = self._sub(step.value)
        if not code.strip():
            raise StepError("no JavaScript given", retryable=False)
        result = self.active_page.evaluate(code)
        variable = str(step.parameter("variable", "") or "").strip()
        if variable:
            self.variables[variable] = result
            self.on_log("ok", f"JavaScript returned {_shorten(result, 80)} -> ${{{variable}}}")
        else:
            self.on_log("ok", f"JavaScript finished ({_shorten(result, 80)})")
        return 0

    def _do_if_visible(self, step: Step, index: int) -> int:
        timeout = int(step.parameter("timeout_ms", 2500) or 2500)
        try:
            locator, used, _ = self._find(step, timeout_ms=timeout)
            locator.first.wait_for(state="visible", timeout=timeout)
            visible = True
        except StepError:
            visible = False
            used = 0
        branch = step.steps if visible else step.else_steps
        self.on_log("action", f"{step.description or step.selector} is {'visible' if visible else 'not visible'}")
        self._run_nested(branch)
        return used

    def _do_repeat(self, step: Step, index: int) -> int:
        times = max(0, min(int(self._sub(step.parameter("times", 1)) or 0), 10_000))
        self.on_log("action", f"repeat block {times} time(s)")
        for i in range(times):
            self._wait_if_paused()
            if self.stopped:
                raise StopRequested()
            self.on_log("debug", f"repeat {i + 1}/{times}")
            self._run_nested(step.steps)
        return 0

    def _run_nested(self, steps: list[Step]) -> None:
        if not steps:
            return
        for sub_index, sub_step in enumerate(steps, start=1):
            self._wait_if_paused()
            if self.stopped:
                raise StopRequested()
            if not sub_step.enabled:
                continue
            result = self._execute_with_retries(sub_step, sub_index)
            self.result.step_results.append(result)
            if result.status == "error":
                self.result.steps_failed += 1
                if self.request.stop_on_error:
                    raise StopRequested()

    def _do_go_back(self, step: Step, index: int) -> int:
        self.on_log("action", "go back")
        self.active_page.go_back(wait_until="domcontentloaded", timeout=self.request.navigation_timeout_ms)
        return 0

    def _do_go_forward(self, step: Step, index: int) -> int:
        self.on_log("action", "go forward")
        self.active_page.go_forward(wait_until="domcontentloaded", timeout=self.request.navigation_timeout_ms)
        return 0

    def _do_reload(self, step: Step, index: int) -> int:
        self.on_log("action", "reload page")
        self.active_page.reload(wait_until="domcontentloaded", timeout=self.request.navigation_timeout_ms)
        return 0

    def _do_new_tab(self, step: Step, index: int) -> int:
        url = self._sub(step.value or step.parameter("url", "") or "")
        self.on_log("action", f"open new tab{' ' + url if url else ''}")
        page = self.context.new_page()
        self._loop_pages.append(page)
        if url:
            page.goto(url, wait_until="domcontentloaded", timeout=self.request.navigation_timeout_ms)
        return 0

    def _do_switch_tab(self, step: Step, index: int) -> int:
        try:
            wanted = int(self._sub(step.value or step.parameter("index", 1)) or 1)
        except ValueError:
            wanted = 1
        pages = [p for p in self._loop_pages if not p.is_closed()]
        if not pages:
            pages = self.session.pages() if self.session else []
        if not pages:
            raise StepError("no tabs are open", retryable=False)
        wanted = max(1, min(wanted, len(pages)))
        page = pages[wanted - 1]
        try:
            page.bring_to_front()
        except Exception:
            pass
        self._loop_pages = pages[wanted - 1:] + pages[: wanted - 1]
        self.on_log("action", f"switch to tab {wanted}")
        return 0

    def _do_close_tab(self, step: Step, index: int) -> int:
        page = self.active_page
        self.on_log("action", "close tab")
        try:
            page.close()
        except Exception:
            pass
        self._loop_pages = [p for p in self._loop_pages if p is not page]
        if not self._loop_pages and self.session:
            self._loop_pages = self.session.pages() or []
        if not self._loop_pages:
            page = self.context.new_page()
            self._loop_pages = [page]
        return 0

    def _do_dialog(self, step: Step, index: int) -> int:
        action = str(step.parameter("action", "accept") or "accept")
        prompt = self._sub(step.parameter("prompt_text", "") or "")
        fires_next = bool(step.parameter("fires_next", True))
        self.on_log("action", f"handle the next dialog ({action})")

        def handler(dialog) -> None:
            try:
                if action == "accept":
                    dialog.accept(prompt if dialog.type == "prompt" and prompt else None)
                else:
                    dialog.dismiss()
            except Exception:
                pass

        page = self.active_page
        if fires_next:
            page.once("dialog", handler)
            self._pending_dialog = {"action": action, "prompt": prompt}
        else:
            page.once("dialog", handler)
        return 0

    def _do_note(self, step: Step, index: int) -> int:
        text = self._sub(step.parameter("text", "") or step.value)
        if text:
            self.on_log("info", f"note: {text}")
        return 0

    # ------------------------------------------------------------------ helpers
    def _wait_if_paused(self) -> None:
        while not self._pause.is_set():
            if self.stopped:
                raise StopRequested()
            time.sleep(0.1)

    def _sleep(self, ms: int) -> None:
        """Sleep that still reacts to Stop and Pause."""
        if ms <= 0:
            return
        end = time.time() + ms / 1000.0
        while time.time() < end:
            if self.stopped:
                raise StopRequested()
            self._wait_if_paused()
            time.sleep(min(0.1, max(0.01, end - time.time())))

    def _wait_for_network(self, page, timeout_ms: int = 12000) -> None:
        """Best effort 'wait until the page settles' (never fatal)."""
        try:
            page.wait_for_load_state("domcontentloaded", timeout=min(timeout_ms, 5000))
        except Exception:
            pass
        try:
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except Exception:
            pass

    def _screenshot_on_error(self, index: int, step: Step) -> None:
        if not self.request.screenshot_on_error:
            return
        try:
            page = self.active_page
            if page is None:
                return
            path = screenshots_dir() / (
                f"error_{self.result.loops_attempted}_{index}_{datetime.now().strftime('%H%M%S')}.png"
            )
            page.screenshot(path=str(path))
            self.on_log("info", f"error screenshot: {path}")
        except Exception:
            pass

    # --------------------------------------------------------------- dry run
    def _dry_run(self) -> RunResult:
        self.on_status("dry-run")
        total = len(self.script.steps)
        for index, step in enumerate(self.script.steps, start=1):
            self.on_step(index, total, step)
            self.on_log("info", f"[{index}/{total}] {step.label}: {step.summary() or step.description}")
            for candidate in step.candidates():
                self.on_log("debug", f"    selector {candidate.display()} (score {candidate.score})")
            if step.steps:
                self.on_log("debug", f"    {len(step.steps)} nested step(s)")
        self.on_log("ok", f"Dry run checked {total} step(s) with no browser.")
        return self._finish("completed", stopped=False, dry_run=True)

    def _finish(self, outcome: str, *, stopped: bool, dry_run: bool = False) -> RunResult:
        self.result.finished_at = time.time()
        self.result.stopped_by_user = stopped
        if stopped:
            self.result.outcome = "stopped"
        elif outcome == "completed" and self.result.steps_failed:
            self.result.outcome = "completed_with_errors"
        else:
            self.result.outcome = outcome
        if self.result.healed and not dry_run:
            self.on_log("warn", f"{len(self.result.healed)} step(s) were healed with fallback selectors.")
        self.on_status("idle")
        self.on_finish(self.result)
        return self.result


# --------------------------------------------------------------------------
# small helpers (module level so tests can reach them)
# --------------------------------------------------------------------------


def get_text(locator) -> str:
    """Return the visible text of a locator, tolerating inputs/selects."""
    try:
        tag = locator.evaluate("el => el.tagName.toLowerCase()")
    except Exception:
        tag = ""
    try:
        if tag in ("input", "textarea"):
            value = locator.input_value()
            return value or ""
        if tag == "select":
            return locator.evaluate("el => el.options[el.selectedIndex] ? el.options[el.selectedIndex].textContent : ''") or ""
    except Exception:
        pass
    try:
        return locator.inner_text() or ""
    except Exception:
        return locator.text_content() or ""


def compare_text(actual: str, expected: str, mode: str) -> bool:
    actual = (actual or "").strip()
    expected = (expected or "").strip()
    if mode == "equals":
        return actual == expected
    if mode == "not_contains":
        return expected not in actual
    if mode == "regex":
        try:
            return re.search(expected, actual) is not None
        except re.error:
            return False
    if mode == "equals_ci":
        return actual.casefold() == expected.casefold()
    return expected.casefold() in actual.casefold()


def _raw_error(exc: Exception) -> str:
    text = str(exc)
    message = getattr(exc, "message", "")
    return f"{text} {message}"


def _short_error(exc: Exception) -> str:
    text = _raw_error(exc).strip().splitlines()
    first = next((line.strip() for line in text if line.strip()), type(exc).__name__)
    return _shorten(first, 110)


def _friendly_error(exc: Exception) -> str:
    raw = _raw_error(exc)
    lowered = raw.lower()
    if "timeout" in lowered and "exceeded" in lowered:
        target = ""
        match = re.search(r"waiting for (.*?)(?:\.|$)", raw, re.IGNORECASE | re.DOTALL)
        if match:
            target = " " + match.group(1).strip()[:120]
        return f"timed out waiting for{target} (increase the timeout in Settings if the site is slow)"
    if "net::err_name_not_resolved" in lowered:
        return "the site could not be reached (DNS lookup failed)"
    if "net::err_connection" in lowered:
        return "could not connect to the site"
    if "net::err_internet_disconnected" in lowered:
        return "no internet connection"
    if "execution context was destroyed" in lowered:
        return "the page navigated away while the action was running"
    if "target page, context or browser has been closed" in lowered:
        return "the browser window was closed"
    return _shorten(raw.replace("\n", " "), 260)


def _shorten(value: Any, limit: int) -> str:
    text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"
