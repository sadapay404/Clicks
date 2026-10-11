"""Script library: load/save/duplicate scripts on disk as plain JSON files."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .models import Script, make_example_script, utc_now_iso
from .paths import scripts_dir

_SLUG_RE = re.compile(r"[^A-Za-z0-9._\- ]+")


def slugify(name: str, fallback: str = "script") -> str:
    slug = _SLUG_RE.sub("", (name or "").strip()).strip().replace(" ", "_")
    slug = re.sub(r"_+", "_", slug)
    return slug or fallback


@dataclass
class ScriptEntry:
    path: Path
    name: str
    description: str
    step_count: int
    updated_at: str
    start_url: str = ""

    @property
    def display_name(self) -> str:
        return self.name or self.path.stem


class ScriptStore:
    """A folder of ``*.json`` scripts with tiny helpers for the UI."""

    def __init__(self, directory: Path | None = None) -> None:
        self.dir = Path(directory) if directory else scripts_dir()
        self.dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ paths
    def path_for(self, name: str) -> Path:
        return self.dir / f"{slugify(name)}.json"

    def unique_path_for(self, name: str) -> Path:
        base = slugify(name)
        candidate = self.dir / f"{base}.json"
        n = 2
        while candidate.exists():
            candidate = self.dir / f"{base}_{n}.json"
            n += 1
        return candidate

    # ------------------------------------------------------------------- read
    def list_entries(self) -> list[ScriptEntry]:
        entries: list[ScriptEntry] = []
        for path in sorted(self.dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                steps = data.get("steps") or []
                entries.append(
                    ScriptEntry(
                        path=path,
                        name=str(data.get("name") or path.stem),
                        description=str(data.get("description") or ""),
                        step_count=_count_steps(steps),
                        updated_at=str(data.get("updated_at") or ""),
                        start_url=str(data.get("start_url") or ""),
                    )
                )
            except Exception:
                entries.append(
                    ScriptEntry(path=path, name=path.stem, description="(unreadable)",
                                step_count=0, updated_at="")
                )
        entries.sort(key=lambda e: e.updated_at or "", reverse=True)
        return entries

    def load(self, path: str | Path) -> Script:
        return Script.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def load_by_name(self, name: str) -> Script | None:
        path = self.path_for(name)
        return self.load(path) if path.exists() else None

    def exists(self, name: str) -> bool:
        return self.path_for(name).exists()

    # ------------------------------------------------------------------ write
    def save(self, script: Script, path: str | Path | None = None) -> Path:
        target = Path(path) if path else self.path_for(script.name)
        target.parent.mkdir(parents=True, exist_ok=True)
        script.touch()
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(script.to_json(), encoding="utf-8")
        tmp.replace(target)
        return target

    def save_copy(self, script: Script, name: str | None = None) -> Path:
        from .models import new_id

        clone = Script.from_dict(script.to_dict())
        clone.id = new_id("sc")
        clone.name = name or f"{script.name} (copy)"
        clone.created_at = utc_now_iso()
        return self.save(clone, self.unique_path_for(clone.name))

    def delete(self, path: str | Path) -> None:
        target = Path(path)
        if target.exists():
            trash = self.dir / "_deleted"
            trash.mkdir(exist_ok=True)
            shutil.move(str(target), str(trash / target.name))

    def import_file(self, source: str | Path) -> tuple[Script, Path]:
        data = json.loads(Path(source).read_text(encoding="utf-8"))
        script = Script.from_dict(data)
        return script, self.save(script, self.unique_path_for(script.name))

    def export_file(self, script: Script, destination: str | Path) -> Path:
        dest = Path(destination)
        dest.write_text(script.to_json(), encoding="utf-8")
        return dest

    def ensure_example(self) -> Path:
        """Drop a demo script in the library the very first time."""
        target = self.path_for("Example - Wikipedia search")
        if not target.exists() and not any(self.dir.glob("*.json")):
            return self.save(make_example_script(), target)
        return target

    def all_scripts(self) -> Iterable[Script]:
        for entry in self.list_entries():
            try:
                yield self.load(entry.path)
            except Exception:
                continue


def _count_steps(steps: list[dict]) -> int:
    total = 0
    for step in steps:
        if not isinstance(step, dict):
            continue
        total += 1
        nested = step.get("steps") or []
        else_steps = step.get("else_steps") or []
        total += _count_steps(nested) + _count_steps(else_steps)
    return total
