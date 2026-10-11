"""Turn recorded selector candidates into Playwright selector strings."""

from __future__ import annotations

from typing import Optional

from .models import SelectorCandidate

_EQUALS_ESCAPES = ('"', "\\")


def _escape(value: str) -> str:
    out = value
    for ch in _EQUALS_ESCAPES:
        out = out.replace(ch, "\\" + ch)
    return out


def to_playwright(candidate: SelectorCandidate) -> Optional[str]:
    """Return a Playwright selector string, or None when unusable."""
    kind = (candidate.kind or "css").lower()
    value = (candidate.value or "").strip()
    if not value:
        return None

    if kind == "css":
        if value.startswith(("css=", "xpath=", "text=", "role=", "id=", "data-testid=")):
            return value
        if value.startswith("//") or value.startswith("(//"):
            return f"xpath={value}"
        return value

    if kind == "xpath":
        value = value.removeprefix("xpath=")
        return f"xpath={value}"

    if kind == "text":
        value = value.removeprefix("text=")
        return f"text={value}"

    if kind == "role":
        value = value.removeprefix("role=")
        if "[" in value:
            return f"internal:role={value}"
        return f"role={value}"

    if kind == "label":
        return f"internal:label={_escape(value.removeprefix('label='))}"

    if kind in ("placeholder", "alt", "title"):
        attr = {"placeholder": "placeholder", "alt": "alt", "title": "title"}[kind]
        return f'internal:attr=[{attr}="{_escape(value)}"i]'

    if kind == "testid":
        return f"[data-testid={_css_string(value)}]"

    return value


def _css_string(value: str) -> str:
    if '"' not in value:
        return f'"{value}"'
    if "'" not in value:
        return f"'{value}'"
    return '"' + value.replace('"', '\\"') + '"'


def preview(selector: str, *, selector_kind: str = "css", index: int = 0) -> str:
    """Human readable preview used by the script editor."""
    candidate = SelectorCandidate(kind=selector_kind, value=selector, index=index)
    return to_playwright(candidate) or selector


def split_selector(selector: str) -> tuple[str, str]:
    """Split ``kind=value`` into ``(kind, value)`` for the editor."""
    for kind in ("css", "xpath", "text", "role", "label", "placeholder", "testid", "alt", "title"):
        prefix = f"{kind}="
        if selector.startswith(prefix):
            return kind, selector[len(prefix):]
    if selector.startswith("//"):
        return "xpath", selector
    return "css", selector
