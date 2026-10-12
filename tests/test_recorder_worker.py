"""Recorder worker lifecycle tests using a fake Playwright session."""

from __future__ import annotations

from types import SimpleNamespace

from clicks_auto.browser import LaunchRequest
from clicks_auto.models import Script, Step
from clicks_auto.recorder.builder import RecorderOptions
import clicks_auto.ui.runner as runner


class FakeRecorderSession:
    def __init__(self, launch, *, name, options, start_url, on_log, on_step, on_status):
        self.name = name
        self.finished = False
        self.closed = False
        self.session = SimpleNamespace(is_running=True)
        self.script = Script(name=name, steps=[Step(type="note", options={"text": "saved"})])

    def start(self):
        return None

    def request_stop(self):
        self.finished = True

    def finish(self):
        return self.script

    def pump(self, timeout_ms=200):
        return None

    def close(self):
        self.closed = True
        self.session.is_running = False


def test_keep_open_worker_delivers_script_before_browser_closes(monkeypatch):
    monkeypatch.setattr(runner, "RecorderSession", FakeRecorderSession)
    worker = runner.RecorderWorker(
        LaunchRequest(kind="custom"),
        name="Keep-open lifecycle",
        options=RecorderOptions(),
        keep_browser_open=True,
    )
    delivered = []
    browser_state_at_delivery = []
    worker.finished_recording.connect(
        lambda script: (delivered.append(script), browser_state_at_delivery.append(worker.browser_open))
    )

    # Simulate Stop & save followed by the user's Close browser action.
    worker.finish_recording()
    worker.close_browser()
    worker.run()

    assert len(delivered) == 1
    assert delivered[0].name == "Keep-open lifecycle"
    assert browser_state_at_delivery == [True]
    assert worker.session.closed is True
    assert worker.browser_open is False


def test_unexpected_pump_error_disables_capture_before_worker_exit(monkeypatch):
    class PumpErrorSession(FakeRecorderSession):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.stop_calls = 0

        def request_stop(self):
            self.stop_calls += 1
            super().request_stop()

        def pump(self, timeout_ms=200):
            raise RuntimeError("simulated pump failure")

    monkeypatch.setattr(runner, "RecorderSession", PumpErrorSession)
    worker = runner.RecorderWorker(
        LaunchRequest(kind="custom"),
        name="Pump failure",
        options=RecorderOptions(),
        keep_browser_open=False,
    )

    worker.run()

    assert worker.session.stop_calls == 1
    assert worker.session.finished is True
    assert worker.session.closed is True
