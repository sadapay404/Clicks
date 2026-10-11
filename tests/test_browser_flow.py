"""Real browser integration: engine playback + recorder capture + replay.

These tests drive a genuine Chromium based browser (Edge on the Windows runner,
Playwright Chromium on Linux) against a local test site.
"""

from __future__ import annotations

import pytest

from clicks_auto.browser import LaunchRequest, detect_browser
from clicks_auto.engine import AutomationEngine, RunRequest
from clicks_auto.models import Script, SelectorCandidate, Step

pytestmark = pytest.mark.browser


def browser_kind_for(path: str) -> tuple[str, str]:
    for kind in ("chromium", "chrome", "brave", "edge"):
        choice = detect_browser(kind)
        if choice.found and choice.path == path:
            return kind, choice.path
    return "custom", path


def script_for(site_url: str) -> Script:
    return Script(
        name="Integration test",
        start_url=f"{site_url}/index.html",
        steps=[
            Step(type="goto", value=f"{site_url}/index.html"),
            Step(type="wait_for", selector="#name", description="name field",
                 fallbacks=[]),
            Step(type="fill", selector="#name", value="Clicks-Auto",
                 options={"clear_first": True}, description="name field"),
            Step(type="fill", selector="#email", value="bot@example.com",
                 options={"clear_first": True}, description="email field"),
            Step(type="select", selector="#colour", value="Blue",
                 options={"by": "label"}, description="colour dropdown"),
            Step(type="check", selector="#terms", description="terms checkbox"),
            Step(type="click", selector="#submit-btn", description="Submit"),
            Step(type="wait_for", selector="#output", description="result panel"),
            Step(type="assert_text", selector="#output", value="Clicks-Auto",
                 options={"match": "contains"}, description="result panel"),
            Step(type="assert_url", value="index.html", options={"match": "contains"}),
            Step(type="extract", selector="#output", options={"variable": "result"},
                 description="result panel"),
            Step(type="set_var", options={"variable": "marker"}, value="ok-${__loop__}"),
            Step(type="screenshot", options={"path": "integration.png"}),
            Step(type="click", selector="#next-link", description="second page link"),
            Step(type="wait_for", selector="#second-heading", description="second page heading"),
            Step(type="assert_text", selector="#second-heading", value="Second page",
                 options={"match": "contains"}, description="second page heading"),
            Step(type="click", selector="#magic-button", description="magic button"),
            Step(type="assert_text", selector="#magic", value="Magic happened",
                 options={"match": "contains"}, description="magic text"),
            Step(type="go_back", description="back to the form"),
        ],
    )


def test_engine_plays_a_script_end_to_end(chromium_path, site_url):
    kind, executable = browser_kind_for(chromium_path)
    logs: list[tuple[str, str]] = []
    request = RunRequest(
        script=script_for(site_url),
        loop_mode="count",
        loop_count=2,
        headless=True,
        browser_kind=kind,
        browser_executable=executable,
        close_browser_when_done=True,
        action_timeout_ms=15000,
        navigation_timeout_ms=30000,
        screenshot_on_error=True,
    )
    engine = AutomationEngine(request, on_log=lambda level, message: logs.append((level, message)))
    result = engine.run()

    assert result.outcome == "completed", f"errors: {result.errors}\nlogs: {logs[-12:]}"
    assert result.loops_completed == 2
    assert result.steps_failed == 0
    assert any("stored" in message for _, message in logs)


def test_engine_retries_and_reports_missing_element(chromium_path, site_url):
    kind, executable = browser_kind_for(chromium_path)
    script = Script(name="Missing element", steps=[
        Step(type="goto", value=f"{site_url}/index.html"),
        Step(type="click", selector="#does-not-exist", description="ghost button",
             timeout_ms=1500, retries=1),
        Step(type="note", options={"text": "still here"}),
    ])
    logs: list[tuple[str, str]] = []
    engine = AutomationEngine(
        RunRequest(script=script, headless=True, browser_kind=kind, browser_executable=executable,
                   close_browser_when_done=True),
        on_log=lambda level, message: logs.append((level, message)),
    )
    result = engine.run()
    assert result.steps_failed == 1
    assert result.outcome == "completed_with_errors"
    assert any(level == "warn" and "retrying" in message for level, message in logs)
    assert any(level == "error" for level, message in logs)


def test_engine_uses_fallback_selector(chromium_path, site_url):
    kind, executable = browser_kind_for(chromium_path)
    script = Script(name="Self healing", steps=[
        Step(type="goto", value=f"{site_url}/index.html"),
        Step(type="click", selector="#stale-selector", description="Submit",
             fallbacks=[SelectorCandidate("text", "Submit", 0, 0.7)],
             timeout_ms=4000, retries=0),
    ])
    logs: list[tuple[str, str]] = []
    engine = AutomationEngine(
        RunRequest(script=script, headless=True, browser_kind=kind, browser_executable=executable,
                   close_browser_when_done=True),
        on_log=lambda level, message: logs.append((level, message)),
    )
    result = engine.run()
    assert result.steps_failed == 0, logs
    assert result.healed, "the fallback selector should have been promoted"
    assert any("script healed" in message for _, message in logs)


def test_recorder_captures_real_interactions_and_replays(chromium_path, site_url, tmp_path):
    from clicks_auto.recorder.builder import RecorderOptions
    from clicks_auto.recorder.session import RecorderSession

    kind, executable = browser_kind_for(chromium_path)
    steps: list[Step] = []
    session = RecorderSession(
        LaunchRequest(kind=kind, executable=executable, headless=True,
                      navigation_timeout_ms=30000),
        name="Recorded integration session",
        options=RecorderOptions(record_waits=False),
        start_url=f"{site_url}/index.html",
        on_step=lambda count, step: steps.append(step),
    )
    session.start()
    try:
        page = session.session.page()
        page.wait_for_selector("#name", timeout=15000)

        # These are real DOM interactions inside the recorder browser.
        page.fill("#name", "Arena Agent")
        session.pump(250)
        page.select_option("#colour", label="Green")
        session.pump(250)
        page.check("#terms")
        session.pump(250)
        page.click("#submit-btn")
        session.pump(400)
        page.click("#next-link")
        session.pump(500)
    finally:
        script = session.finish()
        session.close()

    types = [step.type for step in script.steps]
    assert "goto" in types, types
    assert "fill" in types, types
    assert "select" in types, types
    assert "check" in types, types
    assert "click" in types, types

    fill = next(step for step in script.steps if step.type == "fill")
    assert fill.value == "Arena Agent"
    assert fill.selector, "recorded steps must carry a selector"
    assert fill.fallbacks, "recorded steps should carry fallback selectors too"

    select = next(step for step in script.steps if step.type == "select")
    assert select.value == "Green"

    # ... and the recorded script must actually play back.
    result_logs: list[tuple[str, str]] = []
    engine = AutomationEngine(
        RunRequest(script=script, loop_mode="count", loop_count=1, headless=True,
                   browser_kind=kind, browser_executable=executable,
                   close_browser_when_done=True, action_timeout_ms=15000),
        on_log=lambda level, message: result_logs.append((level, message)),
    )
    result = engine.run()
    assert result.outcome == "completed", f"{result.errors}\n{result_logs[-10:]}"
    assert result.steps_failed == 0


def test_headless_flag_and_window_size(chromium_path, site_url):
    kind, executable = browser_kind_for(chromium_path)
    script = Script(name="Headless check", steps=[
        Step(type="goto", value=f"{site_url}/index.html"),
        Step(type="assert_visible", selector="#heading", options={"timeout_ms": 8000}),
    ])
    engine = AutomationEngine(RunRequest(
        script=script, headless=True, browser_kind=kind, browser_executable=executable,
        close_browser_when_done=True, window_width=1024, window_height=768,
    ))
    result = engine.run()
    assert result.outcome == "completed"
