"""Script model: the JSON format that the recorder writes and the engine runs.

The format is intentionally flat and human editable::

    {
      "name": "Daily check-in",
      "start_url": "https://example.com",
      "defaults": {"step_timeout_ms": 20000, "retries": 2},
      "steps": [
        {"type": "goto", "url": "https://example.com"},
        {"type": "fill", "selector": "#email", "value": "${username}"},
        {"type": "click", "selector": "#submit",
         "fallbacks": [{"kind": "text", "value": "Sign in"}]}
      ]
    }
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

SCRIPT_VERSION = 1

# --------------------------------------------------------------------------
# Selector kinds understood by the engine (``selector_kind`` field)
# --------------------------------------------------------------------------
SELECTOR_KINDS = ("css", "xpath", "text", "role", "label", "placeholder", "testid", "alt", "title")

# --------------------------------------------------------------------------
# Step catalogue - single source of truth for engine, editor and docs.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ParamSpec:
    name: str
    label: str
    kind: str = "text"  # text|textarea|number|select|checkbox|selector|key|file|steps|secret
    options: tuple[str, ...] = ()
    placeholder: str = ""
    default: Any = ""
    help: str = ""


@dataclass(frozen=True)
class StepTypeInfo:
    key: str
    label: str
    icon: str
    category: str
    description: str
    params: tuple[ParamSpec, ...] = ()
    needs_selector: bool = False
    needs_value: bool = False
    nested: bool = False
    shortcut: str = ""

    @property
    def spec(self) -> dict[str, ParamSpec]:
        return {p.name: p for p in self.params}


def _p(*args, **kwargs) -> ParamSpec:
    return ParamSpec(*args, **kwargs)


STEP_TYPES: dict[str, StepTypeInfo] = {
    t.key: t
    for t in [
        StepTypeInfo(
            "goto", "Open URL", "globe", "Navigation",
            "Navigate the browser to a web address.",
            (_p("url", "URL", "text", placeholder="https://example.com", help="Supports ${variables}"),),
            needs_value=True,
        ),
        StepTypeInfo(
            "click", "Click", "cursor", "Interaction",
            "Click an element (button, link, icon...).",
            (
                _p("expect_popup", "Opens a new tab", "checkbox", default=False),
                _p("button", "Mouse button", "select", ("left", "right", "middle"), "left"),
                _p("click_count", "Click count", "number", default=1),
            ),
            needs_selector=True,
        ),
        StepTypeInfo(
            "dblclick", "Double click", "cursor", "Interaction",
            "Double click an element.",
            (), needs_selector=True,
        ),
        StepTypeInfo(
            "fill", "Type text", "keyboard", "Interaction",
            "Clear the field and type a value. Ideal for inputs.",
            (
                _p("value", "Text to type", "textarea"),
                _p("clear_first", "Clear field first", "checkbox", default=True),
                _p("press_enter", "Press Enter after", "checkbox", default=False),
                _p("secret", "Sensitive (hide in logs)", "checkbox", default=False),
            ),
            needs_selector=True, needs_value=True,
        ),
        StepTypeInfo(
            "type", "Type slowly (keystrokes)", "keyboard", "Interaction",
            "Type character by character; use when a site needs real keystrokes.",
            (
                _p("value", "Text to type", "textarea"),
                _p("clear_first", "Clear field first", "checkbox", default=True),
                _p("delay_ms", "Delay per key (ms)", "number", default=40),
            ),
            needs_selector=True, needs_value=True,
        ),
        StepTypeInfo(
            "clear", "Clear field", "eraser", "Interaction",
            "Empty an input field.", (), needs_selector=True,
        ),
        StepTypeInfo(
            "select", "Choose dropdown option", "list", "Interaction",
            "Pick an option from a <select> element.",
            (
                _p("by", "Match option by", "select", ("label", "value", "index"), "label"),
                _p("value", "Option", "text"),
            ),
            needs_selector=True, needs_value=True,
        ),
        StepTypeInfo(
            "check", "Tick checkbox", "check", "Interaction",
            "Ensure a checkbox/radio is ticked.", (), needs_selector=True,
        ),
        StepTypeInfo(
            "uncheck", "Untick checkbox", "check", "Interaction",
            "Ensure a checkbox/radio is unticked.", (), needs_selector=True,
        ),
        StepTypeInfo(
            "hover", "Hover", "cursor", "Interaction",
            "Move the pointer over an element (opens menus, tooltips).",
            (), needs_selector=True,
        ),
        StepTypeInfo(
            "press", "Press key", "keyboard", "Interaction",
            "Send a key or shortcut, e.g. Enter, Tab, Control+A.",
            (_p("key", "Key", "key", default="Enter"),),
            needs_value=True,
        ),
        StepTypeInfo(
            "upload", "Upload file", "upload", "Interaction",
            "Attach local files to a file input.",
            (_p("files", "Files (one per line)", "textarea"),),
            needs_selector=True, needs_value=True,
        ),
        StepTypeInfo(
            "scroll", "Scroll", "scroll", "Interaction",
            "Scroll the page or an element into view.",
            (
                _p("dx", "Horizontal (px)", "number", default=0),
                _p("dy", "Vertical (px)", "number", default=600),
                _p("into_view", "Just bring element into view", "checkbox", default=False),
            ),
        ),
        StepTypeInfo(
            "wait", "Wait", "clock", "Timing",
            "Pause for a fixed amount of time.",
            (_p("ms", "Milliseconds", "number", default=1500),),
            needs_value=True,
        ),
        StepTypeInfo(
            "wait_for", "Wait for element", "hourglass", "Timing",
            "Wait until an element appears / disappears.",
            (
                _p("state", "Wait until", "select", ("visible", "hidden", "attached", "detached"),
                   "visible"),
                _p("timeout_ms", "Timeout (ms)", "number", default=20000),
            ),
            needs_selector=True,
        ),
        StepTypeInfo(
            "assert_text", "Check text", "check-circle", "Verification",
            "Fail the step when the element text does not match.",
            (
                _p("value", "Expected text", "text"),
                _p("match", "Match", "select", ("contains", "equals", "regex", "not_contains"), "contains"),
                _p("optional", "Only warn, do not fail", "checkbox", default=False),
            ),
            needs_selector=True, needs_value=True,
        ),
        StepTypeInfo(
            "assert_url", "Check URL", "link", "Verification",
            "Fail the step when the page URL does not match.",
            (
                _p("value", "Expected URL part", "text"),
                _p("match", "Match", "select", ("contains", "equals", "regex"), "contains"),
            ),
            needs_value=True,
        ),
        StepTypeInfo(
            "assert_visible", "Check element visible", "eye", "Verification",
            "Fail the step when the element is not visible.",
            (_p("timeout_ms", "Timeout (ms)", "number", default=8000),),
            needs_selector=True,
        ),
        StepTypeInfo(
            "extract", "Extract text to variable", "download", "Data",
            "Read text (or an attribute) into a variable for later steps.",
            (
                _p("variable", "Variable name", "text", placeholder="price"),
                _p("attribute", "Attribute (optional)", "text", placeholder="href"),
            ),
            needs_selector=True, needs_value=True,
        ),
        StepTypeInfo(
            "set_var", "Set variable", "tag", "Data",
            "Create or overwrite a variable.",
            (
                _p("variable", "Variable name", "text"),
                _p("value", "Value", "textarea"),
            ),
            needs_value=True,
        ),
        StepTypeInfo(
            "screenshot", "Screenshot", "camera", "Data",
            "Save a PNG of the page (or of one element).",
            (
                _p("path", "File name", "text", placeholder="shot.png (blank = auto)"),
                _p("full_page", "Full page", "checkbox", default=False),
            ),
        ),
        StepTypeInfo(
            "run_js", "Run JavaScript", "code", "Advanced",
            "Execute a snippet of JavaScript and optionally store the result.",
            (
                _p("code", "JavaScript", "textarea"),
                _p("variable", "Store result in (optional)", "text"),
            ),
            needs_value=True,
        ),
        StepTypeInfo(
            "if_visible", "If element visible...", "branch", "Logic",
            "Run nested steps only when the element is visible.",
            (
                _p("timeout_ms", "Check timeout (ms)", "number", default=2500),
                _p("then", "Then run", "steps"),
                _p("else", "Otherwise run", "steps"),
            ),
            needs_selector=True, nested=True,
        ),
        StepTypeInfo(
            "repeat", "Repeat block", "repeat", "Logic",
            "Run nested steps several times.",
            (
                _p("times", "Times", "number", default=3),
                _p("steps", "Steps", "steps"),
            ),
            nested=True,
        ),
        StepTypeInfo(
            "go_back", "Back", "arrow-left", "Navigation", "Go back one page.", (),
        ),
        StepTypeInfo(
            "go_forward", "Forward", "arrow-right", "Navigation", "Go forward one page.", (),
        ),
        StepTypeInfo(
            "reload", "Reload page", "refresh", "Navigation", "Reload the current page.", (),
        ),
        StepTypeInfo(
            "new_tab", "New tab", "plus", "Tabs",
            "Open a new tab (optionally navigating to a URL).",
            (_p("url", "URL (optional)", "text"),),
        ),
        StepTypeInfo(
            "switch_tab", "Switch tab", "tabs", "Tabs",
            "Make another tab the active one.",
            (_p("index", "Tab number (1 = first)", "number", default=1),),
            needs_value=True,
        ),
        StepTypeInfo(
            "close_tab", "Close tab", "x", "Tabs", "Close the active tab.", (),
        ),
        StepTypeInfo(
            "dialog", "Handle popup dialog", "alert", "Advanced",
            "Choose what to do with alert/confirm/prompt dialogs.",
            (
                _p("action", "Action", "select", ("accept", "dismiss"), "accept"),
                _p("prompt_text", "Prompt answer", "text"),
                _p("fires_next", "Applies to the next action", "checkbox", default=True),
            ),
        ),
        StepTypeInfo(
            "note", "Comment", "note", "Logic",
            "A note for humans - does nothing at run time.",
            (_p("text", "Comment", "textarea"),),
        ),
    ]
}

STEP_CATEGORIES: list[str] = []
for _info in STEP_TYPES.values():
    if _info.category not in STEP_CATEGORIES:
        STEP_CATEGORIES.append(_info.category)

_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")

# Options that scripts/recorders normally store in the step's ``value`` field.
# ``parameter("ms")`` on a wait step therefore reads ``value`` when set.
VALUE_FALLBACK_PARAMS = frozenset(
    {"ms", "times", "index", "files", "code", "text", "key", "url"}
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_id(prefix: str = "s") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


@dataclass
class SelectorCandidate:
    """One way of finding an element, with a confidence score."""

    kind: str = "css"
    value: str = ""
    index: int = 0
    score: float = 0.5
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"kind": self.kind, "value": self.value}
        if self.index:
            data["index"] = self.index
        if self.label:
            data["label"] = self.label
        return data

    @classmethod
    def from_dict(cls, data: Any) -> "SelectorCandidate":
        if isinstance(data, str):
            return cls(kind=_guess_kind(data), value=data, score=0.4)
        kind = str(data.get("kind") or _guess_kind(str(data.get("value", ""))))
        if kind not in SELECTOR_KINDS:
            kind = "css"
        return cls(
            kind=kind,
            value=str(data.get("value", "")),
            index=int(data.get("index") or 0),
            score=float(data.get("score") or 0.4),
            label=str(data.get("label") or ""),
        )

    def display(self) -> str:
        prefix = "" if self.kind == "css" else f"{self.kind}="
        suffix = f"  [match #{self.index + 1}]" if self.index else ""
        return f"{prefix}{self.value}{suffix}"


def _guess_kind(value: str) -> str:
    value = value.strip()
    if value.startswith("//") or value.startswith("(//"):
        return "xpath"
    if value.startswith("xpath=") or value.startswith("//"):
        return "xpath"
    if value.startswith("text="):
        return "text"
    if value.startswith("role="):
        return "role"
    return "css"


@dataclass
class Step:
    type: str = "click"
    id: str = field(default_factory=lambda: new_id("s"))
    selector: str = ""
    selector_kind: str = "css"
    selector_index: int = 0
    fallbacks: list[SelectorCandidate] = field(default_factory=list)
    value: str = ""
    description: str = ""
    options: dict[str, Any] = field(default_factory=dict)
    timeout_ms: Optional[int] = None
    retries: Optional[int] = None
    optional: bool = False
    wait_after_ms: int = 0
    enabled: bool = True
    steps: list["Step"] = field(default_factory=list)
    else_steps: list["Step"] = field(default_factory=list)

    # ------------------------------------------------------------------ info
    @property
    def info(self) -> StepTypeInfo:
        return STEP_TYPES.get(self.type, STEP_TYPES["note"])

    @property
    def label(self) -> str:
        return self.info.label

    def parameter(self, name: str, default: Any = None) -> Any:
        if name == "url":
            return self.options.get("url", self.value)
        if name == "value":
            return self.value if self.value != "" else self.options.get("value", self.value)
        if name in self.options:
            return self.options[name]
        if name == "optional":
            return self.optional
        if self.value != "" and name in VALUE_FALLBACK_PARAMS:
            return self.value
        spec = self.info.spec.get(name)
        return spec.default if spec else default

    def set_parameter(self, name: str, value: Any) -> None:
        if name == "url":
            self.value = str(value)
            self.options.pop("url", None)
        elif name == "value":
            self.value = str(value)
            self.options.pop("value", None)
        elif name == "optional":
            self.optional = bool(value)
        else:
            self.options[name] = value

    def candidates(self) -> list[SelectorCandidate]:
        out: list[SelectorCandidate] = []
        if self.selector:
            out.append(
                SelectorCandidate(
                    kind=self.selector_kind if self.selector_kind in SELECTOR_KINDS else _guess_kind(self.selector),
                    value=self.selector,
                    index=self.selector_index,
                    score=1.0,
                    label=self.description or "primary",
                )
            )
        seen = {c.display() for c in out}
        for cand in sorted(self.fallbacks, key=lambda c: -c.score):
            key = cand.display()
            if key in seen or not cand.value:
                continue
            seen.add(key)
            out.append(cand)
        return out

    def summary(self) -> str:
        pieces: list[str] = []
        if self.value and self.type not in {"goto", "wait", "press"}:
            shown = "********" if self.options.get("secret") else self.value
            pieces.append(_short(shown, 46))
        if self.type == "goto":
            pieces.append(_short(self.value or self.options.get("url", ""), 60))
        if self.type == "wait":
            pieces.append(f"{self.parameter('ms', 1000)} ms")
        if self.type == "press":
            pieces.append(str(self.parameter("key", "Enter")))
        if self.type in ("repeat",):
            pieces.append(f"x{self.parameter('times', 1)}")
        if self.selector:
            shown = self.description or self.selector
            pieces.append(_short(shown, 40))
        return " - ".join(p for p in pieces if p)

    # ------------------------------------------------------------------ io
    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"type": self.type, "id": self.id}
        if self.description:
            data["description"] = self.description
        if self.selector:
            data["selector"] = self.selector
            if self.selector_kind != "css":
                data["selector_kind"] = self.selector_kind
            if self.selector_index:
                data["selector_index"] = self.selector_index
        if self.fallbacks:
            data["fallbacks"] = [c.to_dict() for c in self.fallbacks]
        if self.value != "":
            data["value"] = self.value
        if self.options:
            data["options"] = self.options
        if self.timeout_ms is not None:
            data["timeout_ms"] = self.timeout_ms
        if self.retries is not None:
            data["retries"] = self.retries
        if self.optional:
            data["optional"] = True
        if self.wait_after_ms:
            data["wait_after_ms"] = self.wait_after_ms
        if not self.enabled:
            data["enabled"] = False
        if self.steps:
            data["steps"] = [s.to_dict() for s in self.steps]
        if self.else_steps:
            data["else_steps"] = [s.to_dict() for s in self.else_steps]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Step":
        if not isinstance(data, dict):
            raise ValueError("step must be an object")
        stype = str(data.get("type") or "note").strip().lower()
        if stype not in STEP_TYPES:
            stype = "note"
        options = dict(data.get("options") or {})
        known_scalars = {
            "url", "value", "ms", "key", "variable", "code", "path", "files", "expected",
            "by", "match", "state", "action", "prompt_text", "dx", "dy", "into_view",
            "times", "full_page", "clear_first", "press_enter", "delay_ms", "secret",
            "expect_popup", "button", "click_count", "attribute", "timeout_ms", "index",
        }
        step = cls(
            type=stype,
            id=str(data.get("id") or new_id("s")),
            selector=str(data.get("selector") or ""),
            selector_kind=str(data.get("selector_kind") or _guess_kind(str(data.get("selector") or ""))),
            selector_index=int(data.get("selector_index") or 0),
            fallbacks=[SelectorCandidate.from_dict(c) for c in (data.get("fallbacks") or [])],
            value="" if data.get("value") is None else str(data.get("value")),
            description=str(data.get("description") or ""),
            options={k: v for k, v in options.items() if k in known_scalars or k in {
                "then", "else", "steps",
            }},
            timeout_ms=int(data["timeout_ms"]) if data.get("timeout_ms") is not None else None,
            retries=int(data["retries"]) if data.get("retries") is not None else None,
            optional=bool(data.get("optional", False)),
            wait_after_ms=int(data.get("wait_after_ms") or 0),
            enabled=bool(data.get("enabled", True)),
            steps=[cls.from_dict(s) for s in (data.get("steps") or [])],
            else_steps=[cls.from_dict(s) for s in (data.get("else_steps") or [])],
        )
        # tolerate value living inside options (hand written scripts)
        if not step.value and isinstance(step.options.get("value"), str):
            step.value = step.options.pop("value")
        return step

    def clone(self) -> "Step":
        return Step.from_dict(self.to_dict())


def _short(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


@dataclass
class StepDefaults:
    step_timeout_ms: int = 20000
    navigation_timeout_ms: int = 45000
    retries: int = 2
    retry_delay_ms: int = 700
    delay_between_steps_ms: int = 250
    delay_between_loops_ms: int = 1200

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_timeout_ms": self.step_timeout_ms,
            "navigation_timeout_ms": self.navigation_timeout_ms,
            "retries": self.retries,
            "retry_delay_ms": self.retry_delay_ms,
            "delay_between_steps_ms": self.delay_between_steps_ms,
            "delay_between_loops_ms": self.delay_between_loops_ms,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "StepDefaults":
        data = data or {}
        out = cls()
        for key in out.to_dict():
            if data.get(key) is not None:
                try:
                    setattr(out, key, int(data[key]))
                except (TypeError, ValueError):
                    pass
        return out


@dataclass
class Script:
    name: str = "Untitled script"
    version: int = SCRIPT_VERSION
    id: str = field(default_factory=lambda: new_id("sc"))
    start_url: str = ""
    description: str = ""
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    author: str = ""
    variables: dict[str, str] = field(default_factory=dict)
    defaults: StepDefaults = field(default_factory=StepDefaults)
    keep_alive: bool = True
    steps: list[Step] = field(default_factory=list)
    source: str = "recorded"  # recorded | manual | imported

    # ------------------------------------------------------------------ helpers
    def touch(self) -> None:
        self.updated_at = utc_now_iso()

    @property
    def step_count(self) -> int:
        return len(_flatten(self.steps))

    def action_count(self) -> int:
        return len(self.steps)

    def estimated_seconds(self) -> float:
        total = 0.0
        for step in _flatten(self.steps):
            total += 1.2
            if step.type == "wait":
                total += float(step.parameter("ms", 0) or 0) / 1000.0
            total += step.wait_after_ms / 1000.0
        return total

    def used_variables(self) -> list[str]:
        found: list[str] = []
        for step in _flatten(self.steps):
            for text in (step.value, step.selector, str(step.options.get("code", "")),
                         str(step.options.get("url", ""))):
                for name in _VAR_PATTERN.findall(text or ""):
                    if name not in found and not name.startswith("__"):
                        found.append(name)
        for row in [self.variables]:
            for name in row:
                if name not in found:
                    found.append(name)
        return found

    def validate(self) -> list[str]:
        """Return a list of human readable problems (empty = valid)."""
        problems: list[str] = []
        if not self.steps:
            problems.append("Script has no steps.")
        for step in _flatten(self.steps):
            info = STEP_TYPES.get(step.type)
            if info is None:
                problems.append(f"Unknown step type '{step.type}'.")
                continue
            if info.needs_selector and not step.selector:
                problems.append(f"[{step.label}] is missing a selector.")
            if step.type == "goto" and not (step.value or step.options.get("url")):
                problems.append("[Open URL] is missing a URL.")
            if step.type == "fill" and not step.value:
                problems.append(f"[{step.label}] for '{step.selector}' has no text to type.")
            if step.type == "if_visible" and not (step.steps or step.else_steps):
                problems.append("[If element visible] has no nested steps.")
        return problems

    # ------------------------------------------------------------------ io
    def to_dict(self) -> dict[str, Any]:
        return {
            "format": "clicks-auto-script",
            "version": self.version,
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "author": self.author,
            "start_url": self.start_url,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "source": self.source,
            "keep_alive": self.keep_alive,
            "variables": self.variables,
            "defaults": self.defaults.to_dict(),
            "steps": [s.to_dict() for s in self.steps],
        }

    def to_json(self, indent: int = 2) -> str:
        import json

        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Script":
        if not isinstance(data, dict):
            raise ValueError("script root must be an object")
        if data.get("format") and data["format"] != "clicks-auto-script":
            raise ValueError(f"unsupported script format: {data['format']}")
        steps = [Step.from_dict(s) for s in (data.get("steps") or [])]
        script = cls(
            name=str(data.get("name") or "Untitled script"),
            version=int(data.get("version") or SCRIPT_VERSION),
            id=str(data.get("id") or new_id("sc")),
            start_url=str(data.get("start_url") or ""),
            description=str(data.get("description") or ""),
            created_at=str(data.get("created_at") or utc_now_iso()),
            updated_at=str(data.get("updated_at") or utc_now_iso()),
            author=str(data.get("author") or ""),
            variables={str(k): str(v) for k, v in (data.get("variables") or {}).items()},
            defaults=StepDefaults.from_dict(data.get("defaults")),
            keep_alive=bool(data.get("keep_alive", True)),
            steps=steps,
            source=str(data.get("source") or "imported"),
        )
        if not script.start_url:
            for step in _flatten(script.steps):
                if step.type == "goto" and step.value:
                    script.start_url = step.value
                    break
        return script

    @classmethod
    def from_json(cls, text: str) -> "Script":
        import json

        return cls.from_dict(json.loads(text))


def _flatten(steps: Iterable[Step]) -> list[Step]:
    out: list[Step] = []
    for step in steps:
        out.append(step)
        if step.steps:
            out.extend(_flatten(step.steps))
        if step.else_steps:
            out.extend(_flatten(step.else_steps))
    return out


def iter_steps(steps: Iterable[Step]) -> Iterable[Step]:
    yield from _flatten(steps)


def substitute_variables(text: str, variables: dict[str, Any]) -> str:
    """Replace ``${name}`` placeholders using *variables*.

    Unknown placeholders are kept verbatim so mistakes are visible in the log.
    Built-ins ``__loop__``, ``__index__`` and ``__timestamp__`` are provided by
    the engine.
    """

    if not text or "${" not in text:
        return text

    def repl(match: re.Match[str]) -> str:
        name = match.group(1).strip()
        if name in variables and variables[name] is not None:
            return str(variables[name])
        return match.group(0)

    return _VAR_PATTERN.sub(repl, text)


def make_example_script() -> Script:
    return Script(
        name="Example - Wikipedia search",
        description="Opens Wikipedia, searches for a term and screenshots the result.",
        start_url="https://en.wikipedia.org/wiki/Main_Page",
        source="manual",
        variables={"term": "Automation"},
        steps=[
            Step(type="goto", value="https://en.wikipedia.org/wiki/Main_Page",
                 description="Open Wikipedia"),
            Step(type="wait_for", selector="input[name='search']", description="Search box",
                 fallbacks=[SelectorCandidate("css", "#searchInput", 0, 0.8)]),
            Step(type="fill", selector="input[name='search']", value="${term}",
                 description="Search box", options={"press_enter": True, "clear_first": True}),
            Step(type="wait_for", selector="#firstHeading", description="Result heading"),
            Step(type="assert_text", selector="#firstHeading", value="Automation",
                 options={"match": "contains"}, description="Result heading"),
            Step(type="screenshot", options={"path": "wikipedia.png", "full_page": False}),
        ],
    )
