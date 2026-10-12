"""Recorder session lifecycle tests without launching a real browser."""

from __future__ import annotations

import json
from types import SimpleNamespace

from clicks_auto.browser import LaunchRequest
from clicks_auto.recorder.builder import RecorderOptions
from clicks_auto.recorder.session import RecorderSession


class FakeFrame:
    def __init__(self, recorder: RecorderSession) -> None:
        self.recorder = recorder
        self.options: dict[str, object] = {}

    def evaluate(self, expression: str, payload=None):
        if ".flush()" in expression:
            self.recorder._on_binding(
                SimpleNamespace(frame_url="https://example.test/"),
                json.dumps({
                    "kind": "type",
                    "el": {
                        "tag": "input",
                        "type": "text",
                        "id": "query",
                        "accessible_name": "Search",
                        "candidates": [{"kind": "css", "value": "#query", "score": 0.9}],
                    },
                    "value": "final query",
                    "is_contenteditable": False,
                    "ts": 1234,
                }),
            )
        elif "setOptions" in expression:
            self.options = dict(payload or {})
        return None


class FakePage:
    def __init__(self, recorder: RecorderSession) -> None:
        self.frame = FakeFrame(recorder)
        self.frames = [self.frame]
        self.waits: list[int] = []

    def is_closed(self) -> bool:
        return False

    def wait_for_timeout(self, timeout_ms: int) -> None:
        self.waits.append(timeout_ms)


def session_with_fake_page() -> tuple[RecorderSession, FakePage]:
    recorder = RecorderSession(
        LaunchRequest(kind="custom"),
        name="Stop test",
        options=RecorderOptions(record_waits=False),
    )
    page = FakePage(recorder)
    recorder.session.context = SimpleNamespace(pages=[page])
    return recorder, page


def test_request_stop_flushes_final_text_and_marks_recording_finished():
    recorder, page = session_with_fake_page()

    recorder.request_stop()

    assert recorder.finished is True
    assert recorder.paused is True
    assert page.frame.options["enabled"] is False
    script = recorder.finish()
    assert len(script.steps) == 1
    assert script.steps[0].type == "fill"
    assert script.steps[0].value == "final query"


def test_stopped_keep_open_session_continues_pumping_browser():
    recorder, page = session_with_fake_page()
    recorder.request_stop()

    recorder.pump(25)

    assert page.waits == [25]
