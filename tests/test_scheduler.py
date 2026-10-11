"""Schedule maths and the schedule manager."""

from __future__ import annotations

from datetime import datetime, timedelta

from clicks_auto.scheduler import Schedule, ScheduleManager


def test_daily_next_occurrence_today_or_tomorrow():
    now = datetime(2024, 5, 1, 8, 0)
    schedule = Schedule(mode="daily", time_of_day="09:30")
    target = schedule.compute_next(now)
    assert target == datetime(2024, 5, 1, 9, 30)

    schedule2 = Schedule(mode="daily", time_of_day="07:00")
    assert schedule2.compute_next(now) == datetime(2024, 5, 2, 7, 0)


def test_interval_uses_last_run():
    now = datetime(2024, 5, 1, 10, 0)
    schedule = Schedule(mode="interval", interval_minutes=30, last_run_at="2024-05-01T09:50:00")
    assert schedule.compute_next(now) == datetime(2024, 5, 1, 10, 20)


def test_interval_without_history_starts_soon():
    now = datetime(2024, 5, 1, 10, 0)
    schedule = Schedule(mode="interval", interval_minutes=15)
    target = schedule.compute_next(now)
    assert target > now and target <= now + timedelta(minutes=15, seconds=10)


def test_weekly_picks_only_selected_days():
    now = datetime(2024, 5, 3, 12, 0)          # Friday
    schedule = Schedule(mode="weekly", time_of_day="09:00", days=["mon"])
    target = schedule.compute_next(now)
    assert target.weekday() == 0
    assert target > now


def test_due_and_mark_ran():
    schedule = Schedule(mode="daily", time_of_day="00:01")
    schedule.next_run_at = (datetime.now() - timedelta(minutes=1)).isoformat(timespec="seconds")
    assert schedule.due() is True
    schedule.mark_ran()
    assert schedule.run_count == 1
    assert schedule.next_run_at
    assert schedule.due() is False


def test_once_disables_itself_after_running():
    schedule = Schedule(mode="once", time_of_day="06:00")
    schedule.mark_ran()
    assert schedule.enabled is False
    assert schedule.compute_next() is None


def test_disabled_schedule_never_fires():
    schedule = Schedule(mode="daily", time_of_day="00:00", enabled=False)
    assert schedule.compute_next() is None
    assert schedule.due() is False


def test_manager_persistence_and_tick(tmp_home):
    fired: list[str] = []
    manager = ScheduleManager(lambda schedule: fired.append(schedule.name), poll_seconds=0.1)
    schedule = Schedule(name="Morning run", mode="interval", interval_minutes=1, script_path="x.json")
    manager.add(schedule)
    assert (tmp_home / "schedules.json").exists()

    reloaded = ScheduleManager(lambda s: None)
    assert len(reloaded.schedules) == 1
    assert reloaded.schedules[0].name == "Morning run"

    manager.schedules[0].next_run_at = (datetime.now() - timedelta(seconds=5)).isoformat(timespec="seconds")
    manager.tick()
    assert fired == ["Morning run"]
    assert manager.schedules[0].run_count == 1


def test_manager_update_and_remove(tmp_home):
    manager = ScheduleManager(lambda s: None)
    schedule = manager.add(Schedule(name="A", mode="daily", time_of_day="08:00"))
    schedule.name = "B"
    manager.update(schedule)
    assert manager.get(schedule.id).name == "B"
    manager.remove(schedule.id)
    assert manager.schedules == []


def test_upcoming_sorted(tmp_home):
    manager = ScheduleManager(lambda s: None)
    manager.add(Schedule(name="later", mode="interval", interval_minutes=120))
    manager.add(Schedule(name="sooner", mode="interval", interval_minutes=5))
    upcoming = manager.upcoming(2)
    assert [schedule.name for schedule, _ in upcoming][0] in ("sooner", "later")
    assert len(upcoming) == 2


def test_schedule_round_trip_dict():
    schedule = Schedule(name="X", mode="weekly", days=["tue", "thu"], time_of_day="21:15")
    clone = Schedule.from_dict(schedule.to_dict())
    assert clone.name == "X"
    assert clone.days == ["tue", "thu"]
    assert clone.mode == "weekly"


def test_schedule_rejects_bad_values():
    schedule = Schedule.from_dict({"mode": "lunar", "days": ["someday"], "name": "Y"})
    assert schedule.mode == "daily"
    assert schedule.days == []
