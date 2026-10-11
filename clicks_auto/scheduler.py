"""Simple built-in scheduler: run a script at a time of day / every N minutes."""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

from .paths import schedules_file
from .timeutil import next_occurrence, parse_hhmm

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
MODES = ("once", "daily", "weekly", "interval")


@dataclass
class Schedule:
    id: str = field(default_factory=lambda: f"sch_{uuid.uuid4().hex[:8]}")
    name: str = "New schedule"
    script_path: str = ""
    mode: str = "daily"              # once | daily | weekly | interval
    time_of_day: str = "09:00"
    days: list[str] = field(default_factory=lambda: list(WEEKDAYS[:5]))
    interval_minutes: int = 60
    enabled: bool = True
    loop_mode: str = "count"
    loop_count: int = 1
    headless: bool = True
    last_run_at: str = ""
    next_run_at: str = ""
    run_count: int = 0

    # ------------------------------------------------------------------ logic
    def compute_next(self, now: datetime | None = None) -> Optional[datetime]:
        now = now or datetime.now()
        if not self.enabled:
            return None
        if self.mode == "interval":
            minutes = max(1, int(self.interval_minutes))
            base = now
            if self.last_run_at:
                try:
                    base = datetime.fromisoformat(self.last_run_at)
                except ValueError:
                    base = now
            target = base + timedelta(minutes=minutes)
            return max(target, now + timedelta(seconds=5))
        parsed = parse_hhmm(self.time_of_day)
        if parsed is None:
            return None
        hour, minute = parsed
        if self.mode == "once":
            return next_occurrence(hour, minute, now)
        if self.mode == "daily":
            return next_occurrence(hour, minute, now)
        # weekly
        wanted = [d for d in self.days if d in WEEKDAYS] or ["mon"]
        for offset in range(0, 15):
            candidate_day = (now + timedelta(days=offset))
            if WEEKDAYS[candidate_day.weekday()] not in wanted:
                continue
            candidate = candidate_day.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate > now:
                return candidate
        return None

    def refresh_next(self) -> None:
        target = self.compute_next()
        self.next_run_at = target.isoformat(timespec="seconds") if target else ""

    def due(self, now: datetime | None = None) -> bool:
        if not self.enabled:
            return False
        now = now or datetime.now()
        if not self.next_run_at:
            self.refresh_next()
            return False
        try:
            target = datetime.fromisoformat(self.next_run_at)
        except ValueError:
            return False
        return now >= target

    def mark_ran(self) -> None:
        self.last_run_at = datetime.now().isoformat(timespec="seconds")
        self.run_count += 1
        if self.mode == "once":
            self.enabled = False
            self.next_run_at = ""
        else:
            self.refresh_next()

    # --------------------------------------------------------------------- io
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Schedule":
        known = {f for f in cls().to_dict()}
        clean = {k: v for k, v in (data or {}).items() if k in known}
        schedule = cls(**clean)
        if schedule.mode not in MODES:
            schedule.mode = "daily"
        schedule.days = [d for d in schedule.days if d in WEEKDAYS]
        return schedule

    def describe(self) -> str:
        if self.mode == "interval":
            return f"every {self.interval_minutes} min"
        if self.mode == "daily":
            return f"daily at {self.time_of_day}"
        if self.mode == "weekly":
            return f"{'/'.join(self.days) or 'mon'} at {self.time_of_day}"
        return f"once at {self.time_of_day}"


class ScheduleManager:
    """Loads schedules and fires a callback when one becomes due."""

    def __init__(
        self,
        on_due: Callable[[Schedule], None],
        *,
        path: Path | None = None,
        poll_seconds: float = 20.0,
    ) -> None:
        self.path = Path(path) if path else schedules_file()
        self.on_due = on_due
        self.poll_seconds = poll_seconds
        self.schedules: list[Schedule] = []
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self.load()

    # ------------------------------------------------------------------ crud
    def load(self) -> None:
        with self._lock:
            if not self.path.exists():
                self.schedules = []
                return
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.schedules = [Schedule.from_dict(item) for item in data]
            except Exception:
                self.schedules = []
            for schedule in self.schedules:
                schedule.refresh_next()

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps([s.to_dict() for s in self.schedules], indent=2)
            self.path.write_text(payload, encoding="utf-8")

    def add(self, schedule: Schedule) -> Schedule:
        with self._lock:
            schedule.refresh_next()
            self.schedules.append(schedule)
            self.save()
        return schedule

    def update(self, schedule: Schedule) -> None:
        with self._lock:
            schedule.refresh_next()
            for index, existing in enumerate(self.schedules):
                if existing.id == schedule.id:
                    self.schedules[index] = schedule
                    break
            self.save()

    def remove(self, schedule_id: str) -> None:
        with self._lock:
            self.schedules = [s for s in self.schedules if s.id != schedule_id]
            self.save()

    def get(self, schedule_id: str) -> Schedule | None:
        return next((s for s in self.schedules if s.id == schedule_id), None)

    # --------------------------------------------------------------- running
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="clicks-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None

    def _loop(self) -> None:
        while not self._stop.wait(self.poll_seconds):
            try:
                self.tick()
            except Exception:
                continue

    def tick(self, now: datetime | None = None) -> None:
        now = now or datetime.now()
        for schedule in list(self.schedules):
            if schedule.due(now):
                schedule.mark_ran()
                self.save()
                try:
                    self.on_due(schedule)
                except Exception:
                    continue

    def upcoming(self, limit: int = 5) -> list[tuple[Schedule, str]]:
        rows: list[tuple[Schedule, str]] = []
        for schedule in self.schedules:
            if not schedule.enabled:
                continue
            target = schedule.compute_next()
            if target:
                rows.append((schedule, target.isoformat(timespec="seconds")))
        rows.sort(key=lambda item: item[1])
        return rows[:limit]
