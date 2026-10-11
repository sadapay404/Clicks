"""Data driven runs: one CSV/JSON row per loop iteration."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


class DataFeedError(Exception):
    pass


class DataFeed:
    """Loads a table of variables from CSV, TSV or JSON/JSONL.

    Supports two shapes:

    * **row mode** - first line holds the column names, every following line is
      one iteration::

            username,password
            alice,secret1
            bob,secret2

    * **json list** - ``[{"username": "alice"}, ...]``
    """

    def __init__(self, rows: list[dict[str, Any]] | None = None, source: str = "") -> None:
        self.rows: list[dict[str, Any]] = rows or []
        self.source = source
        self.columns: list[str] = []
        if self.rows:
            seen: list[str] = []
            for row in self.rows:
                for key in row:
                    if key not in seen:
                        seen.append(key)
            self.columns = seen
        self._cursor = 0
        self.loop = True  # restart from the top when rows run out

    # ------------------------------------------------------------------ loads
    @classmethod
    def from_file(cls, path: str | Path) -> "DataFeed":
        target = Path(path)
        if not target.exists():
            raise DataFeedError(f"Data file not found: {target}")
        text = target.read_text(encoding="utf-8-sig")
        suffix = target.suffix.lower()
        if suffix in (".json",):
            return cls.from_json(text, str(target))
        if suffix in (".jsonl", ".ndjson"):
            rows = [json.loads(line) for line in text.splitlines() if line.strip()]
            return cls(rows, str(target))
        return cls.from_csv(text, str(target))

    @classmethod
    def from_csv(cls, text: str, source: str = "") -> "DataFeed":
        sample = text[:4096]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except Exception:
            dialect = csv.excel
        reader = csv.DictReader(text.splitlines(), dialect=dialect)
        rows = [{k: (v or "").strip() for k, v in row.items() if k is not None} for row in reader]
        if not rows:
            raise DataFeedError("Data file has no rows below the header line.")
        return cls(rows, source)

    @classmethod
    def from_json(cls, text: str, source: str = "") -> "DataFeed":
        data = json.loads(text)
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            raise DataFeedError("JSON data must be a list of objects or a single object.")
        rows: list[dict[str, Any]] = []
        for item in data:
            if isinstance(item, dict):
                rows.append(item)
            else:
                rows.append({"value": item})
        if not rows:
            raise DataFeedError("JSON data file is empty.")
        return cls(rows, source)

    # ------------------------------------------------------------------- read
    def __len__(self) -> int:
        return len(self.rows)

    @property
    def position(self) -> int:
        return self._cursor

    def next_row(self) -> dict[str, Any]:
        """Return the row for the next iteration (loops back at the end)."""
        if not self.rows:
            return {}
        row = dict(self.rows[self._cursor % len(self.rows)])
        self._cursor += 1
        return row

    def peek(self, offset: int = 0) -> dict[str, Any]:
        if not self.rows:
            return {}
        return dict(self.rows[(self._cursor + offset) % len(self.rows)])

    def reset(self) -> None:
        self._cursor = 0

    def preview(self, count: int = 8) -> list[dict[str, Any]]:
        return [dict(r) for r in self.rows[:count]]

    def summary(self) -> str:
        if not self.rows:
            return "No data loaded"
        name = Path(self.source).name if self.source else "inline"
        return f"{len(self.rows)} rows x {len(self.columns)} columns from {name}"
