"""Tiny time helpers shared by the engine, history and UI."""

from __future__ import annotations

from datetime import datetime, timedelta


def human_duration(seconds: float | int) -> str:
    seconds = int(max(0, seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {sec:02d}s" if sec else f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes:02d}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours:02d}h"


def human_time(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S")


def human_datetime(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def timestamp_slug() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def parse_hhmm(text: str) -> tuple[int, int] | None:
    text = (text or "").strip()
    for fmt in ("%H:%M", "%H.%M", "%I:%M %p", "%I%p", "%H"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.hour, parsed.minute
        except ValueError:
            continue
    return None


def next_occurrence(hour: int, minute: int, when: datetime | None = None) -> datetime:
    now = when or datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def countdown(target: datetime | None) -> str:
    if target is None:
        return ""
    delta = target - datetime.now()
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return "due now"
    if seconds < 60:
        return f"in {seconds}s"
    if seconds < 3600:
        return f"in {seconds // 60}m"
    if seconds < 86400:
        return f"in {seconds // 3600}h {(seconds % 3600) // 60}m"
    return f"in {seconds // 86400}d"
