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
