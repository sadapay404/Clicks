"""Translate raw DOM action events into Clicks-Auto script steps.

This module is deliberately free of any Playwright / PyQt import so it can be
unit tested on its own; :mod:`clicks_auto.recorder.session` feeds it events.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from ..models import Script, SelectorCandidate, Step, utc_now_iso

# Elements for which a "click" is better expressed as a higher level step.
_TYPE_ALIASES = {
    "text": "fill",
    "search": "fill",
    "email": "fill",
    "password": "fill",
    "tel": "fill",
    "url": "fill",
    "number": "fill",
    "textarea": "fill",
}


@dataclass
class RecorderOptions:
    record_waits: bool = True
    min_wait_ms: int = 1200
    max_wait_ms: int = 12000
    drop_navigation_after_link_click: bool = True
    record_scroll: bool = False
    record_hover: bool = False
    typing_mode: str = "fill"  # fill | keystrokes
    typing_delay_ms: int = 45
    secret_fields: bool = True
    capture_double_click: bool = True
    merge_typing: bool = True
    step_retries: int = 2
    action_timeout_ms: int = 20000


def merge_type_chunks(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse ``type_chunk`` streams so each field has one final value."""
    out: list[dict[str, Any]] = []
    for event in events:
        if (
            event.get("kind") == "type_chunk"
            and out
            and out[-1].get("kind") == "type_chunk"
            and _same_element(out[-1], event)
        ):
            merged = dict(out[-1])
            merged.update(event)
            out[-1] = merged
            continue
        out.append(dict(event))
    return out


def _same_element(a: dict[str, Any], b: dict[str, Any]) -> bool:
    ea, eb = a.get("el") or {}, b.get("el") or {}
    if ea.get("id") and ea.get("id") == eb.get("id"):
        return True
    key_a = (ea.get("tag"), ea.get("type"), (ea.get("candidates") or [{}])[0].get("value"))
    key_b = (eb.get("tag"), eb.get("type"), (eb.get("candidates") or [{}])[0].get("value"))
    return key_a == key_b


class ActionBuilder:
    """Stateful event -> :class:`Step` translator."""

    def __init__(self, options: RecorderOptions | None = None) -> None:
        self.options = options or RecorderOptions()
        self.steps: list[Step] = []
        self.start_url: str = ""
        self._last_ts: int = 0
        self._last_click: dict[str, Any] = {}
        self._pending_typing: dict[str, Any] | None = None
        self._last_nav_url: str = ""
        self._notes: list[str] = []
        self._seen_urls: set[str] = set()

    # ------------------------------------------------------------------ api
    def handle(self, event: dict[str, Any]) -> list[Step]:
        """Feed one raw event; returns the steps it produced."""
        kind = str(event.get("kind") or "")
        before = len(self.steps)
        handler = getattr(self, f"_on_{kind}", None)
        if handler is not None:
            try:
                handler(event)
            except Exception as exc:  # never lose the session because of one bad event
                self._notes.append(f"skipped {kind}: {exc}")
        self._last_ts = int(event.get("ts") or self._last_ts or 0)
        return self.steps[before:]

    def handle_all(self, events: Iterable[dict[str, Any]]) -> list[Step]:
        for event in merge_type_chunks(events):
            self.handle(event)
        return self.steps

    def finish(self) -> list[Step]:
        self._flush_typing()
        if self._last_click and self._last_click.get("pending_nav"):
            self._last_click["pending_nav"] = False
        return self.steps

    def build_script(self, name: str = "Recorded session", **kwargs: Any) -> Script:
        self.finish()
        first_goto = next((s for s in self.steps if s.type == "goto"), None)
        script = Script(
            name=name,
            start_url=self.start_url or (first_goto.value if first_goto else ""),
            steps=self.steps,
            source="recorded",
            created_at=utc_now_iso(),
            **kwargs,
        )
        if self._notes:
            script.description = " / ".join(self._notes[:5])
        return script

    # -------------------------------------------------------------- helpers
    def _maybe_wait(self, event: dict[str, Any], *, extra_min: int = 0) -> None:
        if not self.options.record_waits:
            return
        ts = int(event.get("ts") or 0)
        if not ts or not self._last_ts:
            return
        gap = ts - self._last_ts
        floor = max(self.options.min_wait_ms, extra_min)
        if gap < floor:
            return
        gap = min(gap, self.options.max_wait_ms)
        # round to 100 ms to keep scripts tidy
        gap = int(round(gap / 100.0) * 100)
        if gap <= 0:
            return
        if self.steps and self.steps[-1].type == "wait":
            self.steps[-1].value = str(gap)
            return
        self.steps.append(Step(type="wait", value=str(gap), description="Pause recorded from you"))

    def _add(self, step: Step) -> Step:
        self.steps.append(step)
        return step

    def _flush_typing(self) -> Step | None:
        pending = self._pending_typing
        if not pending:
            return None
        self._pending_typing = None
        value = str(pending.get("value", ""))
        el = pending.get("el") or {}
        if value == "" and not pending.get("is_contenteditable"):
            return None
        step = self._step_from_element(el)
        step.type = "type" if self.options.typing_mode == "keystrokes" else "fill"
        step.value = value
        step.options["clear_first"] = True
        if step.type == "type":
            step.options["delay_ms"] = self.options.typing_delay_ms
        if self.options.secret_fields and (el.get("type") == "password"):
            step.options["secret"] = True
        step.description = step.description or "type text"
        self._add(step)
        return step

    def _step_from_element(self, el: dict[str, Any] | None, *, description: str | None = None) -> Step:
        el = el or {}
        candidates = [SelectorCandidate.from_dict(c) for c in (el.get("candidates") or [])]
        candidates = [c for c in candidates if c.value]
        step = Step(type="click")
        if candidates:
            primary = candidates[0]
            step.selector = primary.value
            step.selector_kind = primary.kind
            step.selector_index = primary.index
            step.fallbacks = candidates[1:]
        name = description or el.get("accessible_name") or el.get("text") or el.get("name") or ""
        step.description = str(name).strip()[:120]
        frame = el.get("frame") or []
        if frame:
            step.options["frame"] = list(frame)
        if el.get("href"):
            step.options["href"] = el["href"]
        return step

    # ------------------------------------------------------------- handlers
    def _on_ready(self, event: dict[str, Any]) -> None:
        if not self.start_url and event.get("url"):
            self.start_url = str(event["url"])

    def _on_navigation(self, event: dict[str, Any]) -> None:
        url = str(event.get("url") or "")
        if not url or url.startswith(("about:", "chrome:", "edge:", "brave:")):
            return
        # Browsers emit several navigation events for one visit (trailing slash,
        # hash, SPA route changes) - normalise before deduplicating.
        if self._last_nav_url and _same_url(url, self._last_nav_url):
            return
        self._flush_typing()
        if not self.start_url:
            self.start_url = url
        # A click on an <a href> is followed by its own navigation event - skip it.
        if self.options.drop_navigation_after_link_click and self._last_click.get("pending_nav"):
            href = str(self._last_click.get("href") or "")
            if href and _same_url(href, url):
                self._last_click["pending_nav"] = False
                self._last_nav_url = url
                return
        self._last_click["pending_nav"] = False
        if (
            self.steps
            and self.steps[-1].type == "goto"
            and _same_url(self.steps[-1].value, url)
        ):
            self._last_nav_url = url
            return
        self._maybe_wait(event, extra_min=150)
        self._add(Step(type="goto", value=url, description="Page navigation"))
        self._last_nav_url = url

    def _on_click(self, event: dict[str, Any]) -> None:
        el = event.get("el") or {}
        click_count = int(event.get("click_count") or 1)
        # A repeated click on the very same element right away is usually a
        # double-fire from the page, not a human double click.
        if (
            self._last_click.get("key") == _element_key(el)
            and int(event.get("ts") or 0) - int(self._last_click.get("ts") or 0) < 300
        ):
            if click_count == 2 and self.options.capture_double_click and self.steps:
                self.steps[-1].type = "dblclick"
            return

        self._flush_typing()
        self._maybe_wait(event)
        step = self._step_from_element(el)
        step.type = "dblclick" if (click_count == 2 and self.options.capture_double_click) else "click"
        button = str(event.get("button") or "left")
        if button != "left":
            step.options["button"] = button
        if event.get("expect_popup") or el.get("target") == "_blank":
            step.options["expect_popup"] = True
        step.description = step.description or "click"
        self._add(step)
        self._last_click = {
            "key": _element_key(el),
            "ts": int(event.get("ts") or 0),
            "pending_nav": bool(el.get("href")) or step.options.get("expect_popup", False),
            "href": el.get("href") or "",
        }

    def _on_type(self, event: dict[str, Any]) -> None:
        if not self.options.merge_typing:
            self._pending_typing = {
                "el": event.get("el"),
                "value": event.get("value"),
                "is_contenteditable": event.get("is_contenteditable"),
            }
            self._flush_typing()
            return
        pending = self._pending_typing
        if pending and _same_element(pending, event):
            pending["value"] = event.get("value", pending.get("value"))
            pending["el"] = event.get("el", pending.get("el"))
            return
        self._flush_typing()
        self._pending_typing = {
            "el": event.get("el"),
            "value": event.get("value"),
            "is_contenteditable": event.get("is_contenteditable"),
        }

    def _on_type_chunk(self, event: dict[str, Any]) -> None:
        pending = self._pending_typing
        if pending and _same_element(pending, event):
            pending["value"] = event.get("value", pending.get("value"))
            return
        self._flush_typing()
        self._pending_typing = {
            "el": event.get("el"),
            "value": event.get("value"),
            "is_contenteditable": event.get("is_contenteditable"),
        }
        # keystroke mode: emit incremental chunks so playback looks human
        if self.options.typing_mode == "keystrokes":
            step = self._flush_typing()
            if step is not None:
                step.type = "type"

    def _on_select(self, event: dict[str, Any]) -> None:
        self._flush_typing()
        self._maybe_wait(event)
        el = event.get("el") or {}
        step = self._step_from_element(el)
        step.type = "select"
        label = str(event.get("label") or "").strip()
        value = str(event.get("value") or "")
        if label:
            step.options["by"] = "label"
            step.value = label
        else:
            step.options["by"] = "value"
            step.value = value
        step.description = step.description or (label or value or "dropdown")
        self._add(step)

    def _on_check(self, event: dict[str, Any]) -> None:
        self._flush_typing()
        self._maybe_wait(event)
        step = self._step_from_element(event.get("el"))
        step.type = "check" if event.get("checked") else "uncheck"
        step.description = step.description or "checkbox"
        self._add(step)

    def _on_upload(self, event: dict[str, Any]) -> None:
        self._flush_typing()
        step = self._step_from_element(event.get("el"))
        step.type = "upload"
        step.value = "\n".join(str(f) for f in (event.get("files") or []))
        step.description = step.description or "file input"
        step.options["needs_files"] = True
        self._add(step)

    def _on_key(self, event: dict[str, Any]) -> None:
        key = str(event.get("key") or "")
        if not key:
            return
        # Enter right after typing = "press Enter on that field"
        if key == "Enter" and self._pending_typing:
            step = self._flush_typing()
            if step is not None:
                step.options["press_enter"] = True
                return
        if key in ("Tab",) and not self.steps:
            return
        if key.startswith(("Control+c", "Control+v", "Control+x", "Meta+c", "Meta+v", "Meta+x")):
            return
        if key.startswith(("Shift+", "Ctrl+")):
            pass
        self._flush_typing()
        el = event.get("el") or {}
        step = Step(type="press", value=key, description=f"Press {key}")
        if el and (el.get("candidates") or []):
            target = self._step_from_element(el)
            step.selector = target.selector
            step.selector_kind = target.selector_kind
            step.selector_index = target.selector_index
            step.fallbacks = target.fallbacks
            step.options["frame"] = target.options.get("frame", [])
            step.description = f"Press {key} in {el.get('accessible_name') or el.get('tag') or 'field'}"
        self._add(step)

    def _on_submit(self, event: dict[str, Any]) -> None:
        # Submitting is a consequence of the recorded click / Enter press.
        form = event.get("el") or {}
        if not self._last_click and not any(s.type in ("fill", "type", "press") for s in self.steps):
            step = self._step_from_element(form)
            step.type = "press"
            step.value = "Enter"
            step.description = "Submit form"
            self._add(step)

    def _on_scroll(self, event: dict[str, Any]) -> None:
        if not self.options.record_scroll:
            return
        dx = int(event.get("dx") or 0)
        dy = int(event.get("dy") or 0)
        if abs(dx) < 30 and abs(dy) < 30:
            return
        self._flush_typing()
        step = Step(type="scroll", description=f"Scroll {dy:+d} px" if dy else f"Scroll {dx:+d} px")
        step.options["dx"] = dx
        step.options["dy"] = dy
        self._add(step)

    def _on_hover(self, event: dict[str, Any]) -> None:
        if not self.options.record_hover:
            return
        el = event.get("el") or {}
        if not (el.get("candidates") or []):
            return
        step = self._step_from_element(el)
        step.type = "hover"
        step.description = step.description or "hover"
        self._add(step)

    def _on_newtab(self, event: dict[str, Any]) -> None:
        url = str(event.get("url") or "")
        if url and url != "about:blank":
            self._add(Step(type="new_tab", value=url, description="Open new tab"))
        else:
            self._add(Step(type="new_tab", description="Open new tab"))

    def _on_switchtab(self, event: dict[str, Any]) -> None:
        index = int(event.get("index") or 1)
        self._add(Step(type="switch_tab", value=str(index), description=f"Switch to tab {index}"))

    def _on_closetab(self, event: dict[str, Any]) -> None:
        self._add(Step(type="close_tab", description="Close tab"))

    def _on_dialog(self, event: dict[str, Any]) -> None:
        action = "accept" if event.get("accepted", True) else "dismiss"
        step = Step(type="dialog", description=f"Handle {event.get('dialog_type', 'dialog')}")
        step.options["action"] = action
        if event.get("prompt_text"):
            step.options["prompt_text"] = str(event["prompt_text"])
        self._add(step)

    def _on_dialog_trigger(self, event: dict[str, Any]) -> None:
        # informational only - the dialog itself is recorded via Playwright
        return


def _element_key(el: dict[str, Any]) -> str:
    candidates = el.get("candidates") or []
    first = candidates[0].get("value") if candidates else ""
    return f"{el.get('tag')}|{el.get('id')}|{first}"


def _same_url(a: str, b: str) -> bool:
    def norm(url: str) -> str:
        url = url.split("#", 1)[0]
        return url.rstrip("/")

    return norm(a) == norm(b)


def events_to_script(events: list[dict[str, Any]], name: str = "Recorded session",
                     options: RecorderOptions | None = None) -> Script:
    """Convenience helper (used by tests and the CLI import command)."""
    builder = ActionBuilder(options)
    builder.handle_all(events)
    return builder.build_script(name)
