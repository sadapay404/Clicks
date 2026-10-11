"""Recorder event -> script translation tests."""

from __future__ import annotations

from clicks_auto.recorder.builder import ActionBuilder, RecorderOptions, events_to_script


def click_event(selector="#submit", text="Submit", ts=1000, **kwargs):
    el = {
        "tag": "button",
        "type": "submit",
        "id": "",
        "name": "",
        "text": text,
        "accessible_name": text,
        "role": "button",
        "candidates": [
            {"kind": "css", "value": selector, "score": 0.96},
            {"kind": "text", "value": text, "score": 0.7},
        ],
        "frame": [],
        "href": "",
        "target": "",
    }
    event = {"kind": "click", "click_count": 1, "button": "left", "expect_popup": False, "el": el, "ts": ts}
    event.update(kwargs)
    return event


def type_event(value="hello", selector="#name", ts=2000, **kwargs):
    el = {
        "tag": "input",
        "type": "text",
        "id": "name",
        "name": "name",
        "text": "",
        "accessible_name": "Your name",
        "candidates": [{"kind": "css", "value": selector, "score": 0.9}],
        "frame": [],
    }
    event = {"kind": "type", "el": el, "value": value, "ts": ts}
    event.update(kwargs)
    return event


def test_click_becomes_click_step_with_fallbacks():
    builder = ActionBuilder()
    builder.handle(click_event())
    assert len(builder.steps) == 1
    step = builder.steps[0]
    assert step.type == "click"
    assert step.selector == "#submit"
    assert step.fallbacks and step.fallbacks[0].kind == "text"
    assert step.description == "Submit"


def test_navigation_is_recorded_and_sets_start_url():
    builder = ActionBuilder()
    builder.handle({"kind": "navigation", "url": "https://example.com", "ts": 500})
    steps = builder.finish()
    assert steps[0].type == "goto"
    script = builder.build_script("nav")
    assert script.start_url == "https://example.com"


def test_navigation_after_link_click_is_not_duplicated():
    builder = ActionBuilder(RecorderOptions(record_waits=False))
    builder.handle({"kind": "navigation", "url": "https://example.com/start", "ts": 100})
    builder.handle(click_event(selector="#next", text="Next", ts=1500,
                              el={**click_event()["el"], "tag": "a", "href": "https://example.com/second"}))
    builder.handle({"kind": "navigation", "url": "https://example.com/second", "ts": 2200})
    steps = builder.finish()
    assert [step.type for step in steps] == ["goto", "click"]


def test_typing_is_merged_and_marked_secret_for_passwords():
    builder = ActionBuilder()
    builder.handle(type_event("a", ts=1000))
    builder.handle(type_event("ab", ts=1100))
    builder.handle(type_event("abc", ts=1200))
    password_el = {**type_event()["el"], "type": "password", "id": "password",
                   "candidates": [{"kind": "css", "value": "#password", "score": 0.9}]}
    builder.handle({"kind": "type", "el": password_el, "value": "hunter2", "ts": 4000})
    steps = builder.finish()
    fills = [step for step in steps if step.type == "fill"]
    assert fills[0].value == "abc"
    assert fills[1].options.get("secret") is True
    assert fills[1].value == "hunter2"


def test_enter_after_typing_becomes_press_enter_option():
    builder = ActionBuilder()
    builder.handle(type_event("hello", ts=1000))
    builder.handle({"kind": "key", "key": "Enter", "el": type_event()["el"], "ts": 1400})
    steps = builder.finish()
    assert [step.type for step in steps] == ["fill"]
    assert steps[0].options.get("press_enter") is True


def test_control_shortcut_is_recorded_as_press():
    builder = ActionBuilder()
    builder.handle({"kind": "key", "key": "Control+k", "el": None, "ts": 1000})
    builder.finish()
    assert builder.steps[0].type == "press"
    assert builder.steps[0].value == "Control+k"


def test_select_check_and_scroll_options():
    builder = ActionBuilder(RecorderOptions(record_scroll=True))
    builder.handle({
        "kind": "select",
        "el": {"tag": "select", "candidates": [{"kind": "css", "value": "#colour", "score": 0.9}],
               "accessible_name": "Favourite colour"},
        "label": "Blue", "value": "blue", "ts": 1000,
    })
    builder.handle({"kind": "check", "el": {"tag": "input", "type": "checkbox",
                                            "candidates": [{"kind": "css", "value": "#terms", "score": 0.9}]},
                    "checked": True, "ts": 1600})
    builder.handle({"kind": "scroll", "dx": 0, "dy": 700, "ts": 2600})
    steps = builder.finish()
    assert [step.type for step in steps] == ["select", "check", "scroll"]
    assert steps[0].value == "Blue"
    assert steps[0].options["by"] == "label"
    assert steps[2].options["dy"] == 700


def test_scroll_ignored_when_disabled():
    builder = ActionBuilder(RecorderOptions(record_scroll=False))
    builder.handle({"kind": "scroll", "dx": 0, "dy": 900, "ts": 1000})
    assert builder.steps == []


def test_hover_only_when_enabled():
    hover = {"kind": "hover", "el": {"tag": "a", "candidates": [{"kind": "css", "value": "#menu", "score": 0.9}],
                                     "accessible_name": "Menu"}, "ts": 1000}
    assert ActionBuilder(RecorderOptions(record_hover=True)).handle(hover)[0].type == "hover"
    assert ActionBuilder(RecorderOptions(record_hover=False)).handle(hover) == []


def test_pauses_become_wait_steps():
    builder = ActionBuilder(RecorderOptions(record_waits=True, min_wait_ms=1000))
    builder.handle(click_event(ts=1000))
    builder.handle(click_event(selector="#two", text="Two", ts=5000))
    types = [step.type for step in builder.steps]
    assert types == ["click", "wait", "click"]
    assert builder.steps[1].value == "4000"


def test_long_pauses_are_capped():
    builder = ActionBuilder(RecorderOptions(record_waits=True, min_wait_ms=1000, max_wait_ms=5000))
    builder.handle(click_event(ts=1000))
    builder.handle(click_event(selector="#two", text="Two", ts=90_000))
    assert builder.steps[1].type == "wait"
    assert int(builder.steps[1].value) <= 5000


def test_double_click_is_captured():
    builder = ActionBuilder()
    builder.handle(click_event(ts=1000))
    builder.handle(click_event(ts=1200, click_count=2))
    builder.finish()
    assert builder.steps[0].type == "dblclick"


def test_popup_click_sets_expect_popup():
    builder = ActionBuilder()
    builder.handle(click_event(selector="#pop", text="Open", ts=1000, expect_popup=True))
    builder.finish()
    assert builder.steps[0].options.get("expect_popup") is True


def test_new_tab_and_switch_tab_events():
    builder = ActionBuilder()
    builder.handle({"kind": "newtab", "url": "https://example.com/x", "index": 2, "ts": 1000})
    builder.handle({"kind": "switchtab", "index": 1, "ts": 2000})
    steps = builder.finish()
    assert steps[0].type == "new_tab"
    assert steps[0].value == "https://example.com/x"
    assert steps[1].type == "switch_tab"


def test_upload_step_keeps_file_names():
    builder = ActionBuilder()
    builder.handle({"kind": "upload",
                    "el": {"tag": "input", "type": "file",
                           "candidates": [{"kind": "css", "value": "#file", "score": 0.9}]},
                    "files": ["report.pdf"], "ts": 1000})
    builder.finish()
    assert builder.steps[0].type == "upload"
    assert builder.steps[0].value == "report.pdf"
    assert builder.steps[0].options["needs_files"] is True


def test_same_url_navigation_is_filtered():
    builder = ActionBuilder(RecorderOptions(record_waits=False))
    builder.handle({"kind": "navigation", "url": "https://example.com/a", "ts": 1000})
    builder.handle({"kind": "navigation", "url": "https://example.com/a/", "ts": 2000})
    assert len(builder.finish()) == 1


def test_browser_internal_urls_are_ignored():
    builder = ActionBuilder()
    builder.handle({"kind": "navigation", "url": "about:blank", "ts": 1000})
    assert builder.finish() == []


def test_bad_event_does_not_break_the_session():
    builder = ActionBuilder()
    builder.handle({"kind": "click", "el": None, "ts": 1000})
    builder.handle({"kind": "totally-unknown", "ts": 1100})
    builder.handle(click_event(ts=2000))
    assert any(step.type == "click" for step in builder.finish())


def test_events_to_script_helper():
    script = events_to_script([
        {"kind": "navigation", "url": "https://example.com", "ts": 100},
        click_event(ts=1500),
    ], name="helper", options=RecorderOptions(record_waits=False))
    assert script.name == "helper"
    assert [step.type for step in script.steps] == ["goto", "click"]
    assert script.step_count == 2


def test_typing_mode_keystrokes_uses_type_steps():
    options = RecorderOptions(typing_mode="keystrokes", typing_delay_ms=30)
    builder = ActionBuilder(options)
    builder.handle({"kind": "type_chunk", "el": type_event()["el"], "value": "h", "ts": 1000})
    builder.finish()
    assert builder.steps[0].type == "type"
    assert builder.steps[0].options["delay_ms"] == 30
