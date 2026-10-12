"""Engine tests that do not need a browser (dry runs, helpers, error mapping)."""

from __future__ import annotations

import time

from clicks_auto.engine import (
    AutomationEngine,
    RunRequest,
    compare_text,
    _friendly_error,
)
from clicks_auto.models import Script, Step


def make_engine(script, **kwargs):
    logs: list[tuple[str, str]] = []
    request = RunRequest(script=script, **kwargs)
    engine = AutomationEngine(request, on_log=lambda level, message: logs.append((level, message)))
    return engine, logs


def test_dry_run_walks_every_step_without_a_browser():
    script = Script(name="dry", steps=[
        Step(type="goto", value="https://example.com"),
        Step(type="click", selector="#a", description="A button"),
        Step(type="wait", value="500"),
    ])
    engine, logs = make_engine(script, dry_run=True)
    result = engine.run()
    assert result.outcome == "completed"
    assert any("Dry run checked 3 step" in message for _, message in logs)
    assert any(level == "debug" and "selector" in message for level, message in logs)


def test_run_request_total_loops():
    script = Script(steps=[Step(type="note", options={"text": "hi"})])
    assert RunRequest(script=script, loop_mode="count", loop_count=7).total_loops == 7
    assert RunRequest(script=script, loop_mode="infinite").total_loops == 0
    assert RunRequest(script=script, loop_mode="duration", duration_minutes=5).total_loops == 0


def test_compare_text_modes():
    assert compare_text("Hello World", "world", "contains")
    assert not compare_text("Hello World", "mars", "contains")
    assert compare_text("abc", "abc", "equals")
    assert not compare_text("abc ", "abcd", "equals")
    assert compare_text("abc", "a.c", "regex")
    assert not compare_text("abc", "[", "regex")
    assert compare_text("abc", "z", "not_contains")


def test_friendly_error_translations():
    class FakeTimeout(Exception):
        message = "Timeout 30000ms exceeded.\n=========================== logs ===========================\nwaiting for locator('#go')"

    text = _friendly_error(FakeTimeout("Timeout 30000ms exceeded."))
    assert "timed out" in text.lower()

    class FakeDns(Exception):
        pass

    assert "could not be reached" in _friendly_error(FakeDns("net::ERR_NAME_NOT_RESOLVED at https://x"))
    assert "browser window was closed" in _friendly_error(
        FakeDns("Target page, context or browser has been closed"))


def test_stop_flag_before_the_run_is_honoured():
    script = Script(steps=[Step(type="wait", value="60000")])
    engine, logs = make_engine(script, dry_run=False, action_timeout_ms=1000)
    engine.stop()
    started = time.time()
    result = engine.run()          # must return immediately, without launching a browser
    assert time.time() - started < 5
    assert result.outcome == "stopped"
    assert result.stopped_by_user is True
    assert result.loops_completed == 0


def test_engine_reports_friendly_browser_error():
    script = Script(steps=[Step(type="goto", value="https://example.com")])
    engine, logs = make_engine(script, browser_kind="custom", browser_executable="")
    result = engine.run()
    assert result.outcome == "failed"
    assert any(level == "error" for level, _ in logs)
    assert any("custom browser path" in message.lower() or "browser" in message.lower()
               for _, message in logs)


def test_missing_script_steps_is_reported():
    engine, logs = make_engine(Script(name="empty", steps=[]), dry_run=True)
    result = engine.run()
    assert result.outcome == "failed"          # an empty script cannot run
    assert any("no steps" in message.lower() for _, message in logs)


def test_run_result_to_dict_shape():
    script = Script(name="shape", steps=[Step(type="note")])
    engine, _ = make_engine(script, dry_run=True)
    result = engine.run()
    data = result.to_dict()
    for key in ("script", "started_at", "duration", "loops_completed", "steps_ok", "outcome"):
        assert key in data
    assert data["script"] == "shape"


def test_variable_substitution_inside_engine():
    script = Script(name="vars", steps=[Step(type="note", options={"text": "loop ${__loop__}"})])
    engine, logs = make_engine(script, dry_run=True)
    engine.variables = {"__loop__": 3}
    assert engine._sub("loop ${__loop__}") == "loop 3"
    assert engine._sub("nothing here") == "nothing here"

def test_stop_on_error_is_reported_as_failure_not_user_stop():
    script = Script(name="fail fast", steps=[Step(type="not_a_real_step")])
    engine, _ = make_engine(script, stop_on_error=True)
    # Keep this a unit test: the unsupported step exercises error handling, not Playwright.
    engine._start_browser = lambda: setattr(engine, "page", object())

    result = engine.run()

    assert result.outcome == "failed"
    assert result.stopped_by_user is False
    assert result.steps_failed == 1
    assert result.loops_completed == 0


def test_repeat_mode_completes_exactly_the_requested_loop_count():
    script = Script(name="counted", steps=[Step(type="note", options={"text": "tick"})])
    engine, _ = make_engine(
        script,
        loop_mode="count",
        loop_count=4,
        delay_between_steps_ms=0,
        delay_between_loops_ms=0,
    )
    engine._start_browser = lambda: setattr(engine, "page", object())

    result = engine.run()

    assert result.outcome == "completed"
    assert result.loops_attempted == 4
    assert result.loops_completed == 4
    assert result.steps_ok == 4


def test_infinite_mode_stop_button_is_recorded_as_user_stop():
    script = Script(name="unlimited", steps=[Step(type="note", options={"text": "tick"})])
    holder = {}

    def stop_on_third_loop(index, _total):
        if index == 3:
            holder["engine"].stop()

    engine = AutomationEngine(
        RunRequest(
            script=script,
            loop_mode="infinite",
            delay_between_steps_ms=0,
            delay_between_loops_ms=0,
        ),
        on_loop=stop_on_third_loop,
    )
    holder["engine"] = engine
    engine._start_browser = lambda: setattr(engine, "page", object())

    result = engine.run()

    assert result.outcome == "stopped"
    assert result.stopped_by_user is True
    assert result.loops_completed == 2


def test_stop_on_error_in_repeat_block_is_reported_as_failure():
    script = Script(name="nested fail fast", steps=[
        Step(type="repeat", steps=[Step(type="not_a_real_step")]),
    ])
    engine, _ = make_engine(script, stop_on_error=True)
    engine._start_browser = lambda: setattr(engine, "page", object())

    result = engine.run()

    assert result.outcome == "failed"
    assert result.stopped_by_user is False
    assert result.steps_failed == 1
    assert result.errors


def test_keep_open_browser_session_remains_available_until_explicit_close():
    class FakeSession:
        def __init__(self):
            self.stop_calls = 0

        def stop(self):
            self.stop_calls += 1

    script = Script(name="keep browser", steps=[Step(type="note")])
    engine, _ = make_engine(script, keep_browser_open=True, close_browser_when_done=False)
    session = FakeSession()
    engine.session = session
    engine.context = object()
    engine.page = object()
    engine._loop_pages = [engine.page]

    engine._shutdown_browser()

    assert engine.session is session
    assert engine.context is not None
    assert engine.page is not None
    assert session.stop_calls == 0

    engine.close_browser_now()
    assert session.stop_calls == 1
    assert engine.session is None


def test_close_when_done_overrides_keep_browser_open():
    class FakeSession:
        def __init__(self):
            self.stop_calls = 0

        def stop(self):
            self.stop_calls += 1

    engine, _ = make_engine(
        Script(name="close precedence", steps=[Step(type="note")]),
        keep_browser_open=True,
        close_browser_when_done=True,
    )
    session = FakeSession()
    engine.session = session

    engine._shutdown_browser()

    assert session.stop_calls == 1
    assert engine.session is None
