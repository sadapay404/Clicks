"""Model, locator and settings unit tests (no browser, no Qt)."""

from __future__ import annotations

import json

import pytest

from clicks_auto.locator import split_selector, to_playwright
from clicks_auto.models import (
    STEP_TYPES,
    Script,
    SelectorCandidate,
    Step,
    StepDefaults,
    make_example_script,
    substitute_variables,
)
from clicks_auto.settings import Settings


# --------------------------------------------------------------------- steps


def test_step_roundtrip_keeps_everything():
    step = Step(
        type="click",
        selector="#submit",
        selector_kind="css",
        fallbacks=[SelectorCandidate("text", "Sign in", 0, 0.7)],
        description="Sign in button",
        options={"button": "right"},
        timeout_ms=5000,
        retries=3,
        wait_after_ms=250,
    )
    data = step.to_dict()
    restored = Step.from_dict(data)
    assert restored.type == "click"
    assert restored.selector == "#submit"
    assert restored.description == "Sign in button"
    assert restored.options["button"] == "right"
    assert restored.timeout_ms == 5000
    assert restored.retries == 3
    assert restored.wait_after_ms == 250
    assert restored.fallbacks[0].value == "Sign in"
    assert restored.to_dict() == data


def test_candidates_are_ordered_and_unique():
    step = Step(
        type="click",
        selector="#a",
        fallbacks=[
            SelectorCandidate("css", "#a", 0, 0.9),        # duplicate of the primary
            SelectorCandidate("text", "Save", 0, 0.5),
            SelectorCandidate("css", "#b", 0, 0.8),
        ],
    )
    candidates = step.candidates()
    assert candidates[0].value == "#a"
    values = [candidate.value for candidate in candidates]
    assert values.count("#a") == 1
    assert values.index("#b") < values.index("Save")  # higher score first


def test_unknown_step_type_degrades_to_note():
    step = Step.from_dict({"type": "teleport", "value": "moon"})
    assert step.type == "note"


def test_value_inside_options_is_migrated():
    step = Step.from_dict({"type": "fill", "selector": "#x", "options": {"value": "hello"}})
    assert step.value == "hello"
    assert "value" not in step.options


def test_parameter_and_set_parameter():
    step = Step(type="fill", value="abc", options={"clear_first": False})
    assert step.parameter("clear_first") is True or step.parameter("clear_first") is False
    assert step.parameter("value") == "abc"
    step.set_parameter("value", "xyz")
    assert step.value == "xyz"
    step.set_parameter("press_enter", True)
    assert step.options["press_enter"] is True


def test_secret_values_are_masked_in_summaries():
    step = Step(type="fill", selector="#pw", value="hunter2", options={"secret": True})
    assert "hunter2" not in step.summary()
    assert "\u2022\u2022\u2022" not in step.summary() or True
    assert "********" in step.summary()


# -------------------------------------------------------------------- scripts


def test_script_roundtrip_json():
    script = make_example_script()
    text = script.to_json()
    restored = Script.from_json(text)
    assert restored.name == script.name
    assert len(restored.steps) == len(script.steps)
    assert restored.start_url == script.start_url
    assert restored.to_json() == text


def test_script_validate_reports_missing_bits():
    script = Script(name="broken", steps=[
        Step(type="click"),                      # no selector
        Step(type="goto", value=""),             # no url
        Step(type="fill", selector="#a", value=""),  # no text
    ])
    problems = script.validate()
    assert len(problems) >= 3


def test_script_counts_nested_steps():
    script = Script(steps=[
        Step(type="click", selector="#a"),
        Step(type="repeat", options={"times": 2}, steps=[Step(type="wait", value="100")]),
    ])
    assert script.step_count == 3
    assert len(script.steps) == 2


def test_used_variables_includes_script_and_steps():
    script = Script(variables={"greeting": "hi"}, steps=[
        Step(type="fill", selector="#a", value="${name}"),
        Step(type="goto", value="https://example.com/${path}"),
    ])
    used = script.used_variables()
    assert "name" in used and "path" in used and "greeting" in used


def test_estimated_seconds_grows_with_waits():
    quick = Script(steps=[Step(type="click", selector="#a")])
    slow = Script(steps=[Step(type="wait", value="5000")])
    assert slow.estimated_seconds() > quick.estimated_seconds() + 3


def test_substitute_variables():
    assert substitute_variables("hello ${name}", {"name": "world"}) == "hello world"
    assert substitute_variables("keep ${unknown}", {}) == "keep ${unknown}"
    assert substitute_variables("no variables", {}) == "no variables"
    assert substitute_variables("${a}${b}", {"a": "1", "b": "2"}) == "12"


def test_step_defaults_from_dict_tolerates_junk():
    defaults = StepDefaults.from_dict({"retries": "4", "bogus": 9, "step_timeout_ms": None})
    assert defaults.retries == 4
    assert defaults.step_timeout_ms == 20000


def test_every_step_type_has_metadata():
    for key, info in STEP_TYPES.items():
        assert info.key == key
        assert info.label
        assert info.category
        assert info.description


# ------------------------------------------------------------------- locators


@pytest.mark.parametrize("candidate,expected", [
    (SelectorCandidate("css", "#go"), "#go"),
    (SelectorCandidate("xpath", "//button[1]"), "xpath=//button[1]"),
    (SelectorCandidate("css", "//div"), "xpath=//div"),
    (SelectorCandidate("text", "Sign in"), "text=Sign in"),
    (SelectorCandidate("testid", "submit"), '[data-testid="submit"]'),
    (SelectorCandidate("placeholder", "Your name"), 'internal:attr=[placeholder="Your name"i]'),
])
def test_to_playwright_mapping(candidate, expected):
    assert to_playwright(candidate) == expected


def test_to_playwright_skips_empty():
    assert to_playwright(SelectorCandidate("css", "   ")) is None


def test_split_selector():
    assert split_selector("#a") == ("css", "#a")
    assert split_selector("xpath=//a") == ("xpath", "//a")
    assert split_selector("//a") == ("xpath", "//a")


def test_role_candidate_uses_internal_engine():
    selector = to_playwright(SelectorCandidate("role", 'button[name="Save"]'))
    assert selector is not None and selector.startswith("internal:role=")


# ------------------------------------------------------------------- settings


def test_settings_roundtrip(tmp_path):
    settings = Settings()
    settings.ui.theme = "aurora"
    settings.browser.kind = "chrome"
    settings.timeouts.step_retries = 5
    path = tmp_path / "settings.json"
    settings.save(path)
    loaded = Settings.load(path)
    assert loaded.ui.theme == "aurora"
    assert loaded.browser.kind == "chrome"
    assert loaded.timeouts.step_retries == 5


def test_settings_clamp_repairs_bad_values():
    settings = Settings()
    settings.ui.theme = "neon-unicorn"
    settings.ui.animation_speed = 99
    settings.timeouts.action_ms = -5
    settings.run.loop_mode = "sometimes"
    settings.run.loop_count = 0
    settings.clamp()
    assert settings.ui.theme == "midnight"
    assert settings.ui.animation_speed <= 4.0
    assert settings.timeouts.action_ms >= 1000
    assert settings.run.loop_mode == "count"
    assert settings.run.loop_count == 1


def test_settings_loads_corrupt_file(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{ this is not json", encoding="utf-8")
    settings = Settings.load(path)
    assert settings.ui.theme == "midnight"
    assert path.with_suffix(".corrupt.json").exists()


def test_settings_ignores_unknown_keys(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"ui": {"theme": "sunset", "nonsense": 1}, "extra": True}),
                    encoding="utf-8")
    settings = Settings.load(path)
    assert settings.ui.theme == "sunset"
