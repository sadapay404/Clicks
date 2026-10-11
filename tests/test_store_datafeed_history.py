"""Library storage, data feed and history tests."""

from __future__ import annotations

import json

import pytest

from clicks_auto.datafeed import DataFeed, DataFeedError
from clicks_auto.history import HistoryRecord, append, clear, load, stats
from clicks_auto.models import Script, Step
from clicks_auto.store import ScriptStore, slugify


def test_slugify():
    assert slugify("My Script! v2") == "My_Script_v2"
    assert slugify("   ") == "script"


def test_store_save_list_load_delete(tmp_home):
    store = ScriptStore()
    script = Script(name="Daily check", steps=[Step(type="click", selector="#go")])
    path = store.save(script)
    assert path.exists()

    entries = store.list_entries()
    assert len(entries) == 1
    assert entries[0].name == "Daily check"
    assert entries[0].step_count == 1

    loaded = store.load(path)
    assert loaded.name == "Daily check"
    assert loaded.steps[0].selector == "#go"

    store.delete(path)
    assert not path.exists()
    assert store.list_entries() == []


def test_store_unique_paths_and_copy(tmp_home):
    store = ScriptStore()
    script = Script(name="Thing", steps=[Step(type="note", options={"text": "hi"})])
    first = store.save(script)
    second = store.save(script, store.unique_path_for("Thing"))
    assert first != second
    copy = store.save_copy(script)
    assert copy.exists()
    assert "copy" in copy.name
    assert len(store.list_entries()) == 3


def test_store_import_export(tmp_home, tmp_path):
    store = ScriptStore()
    source = tmp_path / "external.json"
    source.write_text(Script(name="External", steps=[Step(type="wait", value="100")]).to_json())
    script, target = store.import_file(source)
    assert target.exists() and script.name == "External"
    export = tmp_path / "exported.json"
    store.export_file(script, export)
    assert json.loads(export.read_text())["name"] == "External"


def test_store_handles_unreadable_file(tmp_home):
    store = ScriptStore()
    (store.dir / "broken.json").write_text("{not json")
    entries = store.list_entries()
    assert entries and entries[0].description == "(unreadable)"


def test_store_creates_example_once(tmp_home):
    store = ScriptStore()
    assert store.ensure_example().exists()
    before = len(store.list_entries())
    store.ensure_example()
    assert len(store.list_entries()) == before


# ------------------------------------------------------------------ data feed


def test_datafeed_csv():
    feed = DataFeed.from_csv("user,pass\nalice,one\nbob,two\n")
    assert len(feed) == 2
    assert feed.columns == ["user", "pass"]
    assert feed.next_row()["user"] == "alice"
    assert feed.next_row()["user"] == "bob"
    assert feed.next_row()["user"] == "alice"  # loops back


def test_datafeed_semicolon_delimiter():
    feed = DataFeed.from_csv("a;b\n1;2\n3;4\n")
    assert feed.next_row() == {"a": "1", "b": "2"}


def test_datafeed_json_list():
    feed = DataFeed.from_json('[{"n": 1}, {"n": 2}]')
    assert len(feed) == 2
    assert feed.preview(1) == [{"n": 1}]


def test_datafeed_single_object_json():
    feed = DataFeed.from_json('{"only": "row"}')
    assert len(feed) == 1


def test_datafeed_errors():
    with pytest.raises(DataFeedError):
        DataFeed.from_csv("header\n")
    with pytest.raises(DataFeedError):
        DataFeed.from_json("[]")
    with pytest.raises(DataFeedError):
        DataFeed.from_json("42")


def test_datafeed_from_file(tmp_path):
    path = tmp_path / "rows.csv"
    path.write_text("x,y\n1,2\n")
    feed = DataFeed.from_file(path)
    assert len(feed) == 1
    assert "1 rows" in feed.summary()


def test_datafeed_reset():
    feed = DataFeed([{"a": 1}, {"a": 2}])
    feed.next_row()
    feed.reset()
    assert feed.next_row() == {"a": 1}


# -------------------------------------------------------------------- history


def test_history_append_load_stats_clear(tmp_home):
    append(HistoryRecord(script="A", started_at="2024-01-01T10:00:00", outcome="completed",
                         loops_completed=2, steps_ok=10, duration_seconds=12.5, duration="12s"))
    append(HistoryRecord(script="B", started_at="2024-01-01T11:00:00", outcome="completed_with_errors",
                         loops_completed=1, steps_failed=3, duration_seconds=5, duration="5s"))
    rows = load()
    assert len(rows) == 2
    assert rows[0]["script"] == "B"  # newest first

    summary = stats()
    assert summary["runs"] == 2
    assert summary["runs_with_errors"] == 1
    assert summary["loops"] == 3
    assert summary["success_rate"] == 50

    clear()
    assert load() == []


def test_history_record_from_result():
    record = HistoryRecord.from_result({
        "script": "X", "started_at": "now", "outcome": "completed", "duration_seconds": 3.0,
        "loops_completed": 1, "steps_ok": 4, "steps_failed": 0, "extra_thing": 7,
    }, trigger="schedule")
    assert record.trigger == "schedule"
    assert record.extras.get("extra_thing") == 7
    assert record.to_dict()["script"] == "X"


def test_history_tolerates_corrupt_lines(tmp_home, monkeypatch):
    from clicks_auto.paths import history_file

    path = history_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"script": "ok"}\nnot json\n{"script": "fine"}\n')
    rows = load()
    assert [row["script"] for row in rows] == ["fine", "ok"]
