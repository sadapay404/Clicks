"""Run history: a JSON-lines log of every execution."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .paths import history_file


@dataclass
class HistoryRecord:
    script: str
    started_at: str
    finished_at: str = ""
    duration: str = ""
    duration_seconds: float = 0.0
    loops_completed: int = 0
    steps_ok: int = 0
    steps_failed: int = 0
    outcome: str = "unknown"
    stopped_by_user: bool = False
    errors: list[str] = field(default_factory=list)
    trigger: str = "manual"          # manual | schedule
    extras: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_result(cls, data: dict[str, Any], *, trigger: str = "manual") -> "HistoryRecord":
        known = {f for f in cls.__dataclass_fields__ if f not in ("extras", "trigger")}
        payload = {k: v for k, v in data.items() if k in known}
        payload.setdefault("script", data.get("script", "unknown"))
        return cls(trigger=trigger, extras={k: v for k, v in data.items() if k not in known}, **payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "script": self.script,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration": self.duration,
            "duration_seconds": self.duration_seconds,
            "loops_completed": self.loops_completed,
            "steps_ok": self.steps_ok,
            "steps_failed": self.steps_failed,
            "outcome": self.outcome,
            "stopped_by_user": self.stopped_by_user,
            "errors": self.errors[:10],
            "trigger": self.trigger,
            **({"extras": self.extras} if self.extras else {}),
        }


def append(record: HistoryRecord | dict[str, Any], path: Path | None = None) -> Path:
    target = Path(path) if path else history_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    data = record.to_dict() if isinstance(record, HistoryRecord) else dict(record)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(data, ensure_ascii=False) + "\n")
    return target


def load(limit: int = 200, path: Path | None = None) -> list[dict[str, Any]]:
    target = Path(path) if path else history_file()
    if not target.exists():
        return []
    rows: list[dict[str, Any]] = []
    with target.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows[-limit:][::-1]


def clear(path: Path | None = None) -> None:
    target = Path(path) if path else history_file()
    if target.exists():
        target.unlink()


def stats(path: Path | None = None) -> dict[str, Any]:
    rows = load(limit=100000, path=path)
    total = len(rows)
    failed = sum(1 for r in rows if r.get("steps_failed"))
    stopped = sum(1 for r in rows if r.get("stopped_by_user"))
    loops = sum(int(r.get("loops_completed") or 0) for r in rows)
    seconds = sum(float(r.get("duration_seconds") or 0) for r in rows)
    return {
        "runs": total,
        "runs_with_errors": failed,
        "runs_stopped": stopped,
        "loops": loops,
        "time_spent_seconds": seconds,
        "success_rate": (0 if not total else round((total - failed) / total * 100)),
        "last_run": rows[0]["started_at"] if rows else "",
    }
