"""Headless command line interface: ``clicks-auto run script.json``.

Handy for testing a script without opening the GUI and for Task Scheduler based
automation on a machine without a desktop session.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import APP_NAME, __version__
from .datafeed import DataFeed
from .engine import AutomationEngine, RunRequest
from .history import HistoryRecord, append as append_history
from .models import Script
from .store import ScriptStore


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="clicks-auto", description=f"{APP_NAME} command line runner")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="run a script")
    run.add_argument("script", help="path to a .json script (or a name from the library)")
    run.add_argument("--loops", type=int, default=1, help="number of repetitions (0 = forever)")
    run.add_argument("--forever", action="store_true", help="keep running until stopped (Ctrl+C)")
    run.add_argument("--duration", type=int, default=0, help="run for this many minutes")
    run.add_argument("--headless", action="store_true", help="run without a visible browser window")
    run.add_argument("--browser", default="brave", choices=["brave", "chrome", "edge", "chromium", "custom"])
    run.add_argument("--browser-path", default="", help="explicit browser executable")
    run.add_argument("--profile", default="", help="browser user data dir (profile folder)")
    run.add_argument("--data", default="", help="CSV/JSON file with one row per loop")
    run.add_argument("--var", action="append", default=[], metavar="NAME=VALUE", help="set a variable")
    run.add_argument("--stop-on-error", action="store_true")
    run.add_argument("--slow-mo", type=int, default=0, help="slow down every action by N ms")
    run.add_argument("--quiet", action="store_true", help="only print errors")
    run.add_argument("--json", action="store_true", help="print the run result as JSON")

    validate = sub.add_parser("validate", help="check a script without running it")
    validate.add_argument("script")

    record = sub.add_parser("record", help="record a new session from the terminal")
    record.add_argument("--name", default="Recorded session")
    record.add_argument("--url", default="")
    record.add_argument("--browser", default="brave", choices=["brave", "chrome", "edge", "chromium", "custom"])
    record.add_argument("--browser-path", default="")
    record.add_argument("--profile", default="")
    record.add_argument("--save-to", default="")
    record.add_argument("--record-scroll", action="store_true")
    record.add_argument("--record-hover", action="store_true")

    sub.add_parser("list", help="list the scripts in the library")
    sub.add_parser("browsers", help="show which browsers were detected")
    return parser


def _resolve_script(argument: str) -> Path:
    path = Path(argument)
    if path.exists():
        return path
    store = ScriptStore()
    candidate = store.path_for(argument)
    if candidate.exists():
        return candidate
    raise SystemExit(f"Script not found: {argument}")


def _print(level: str, message: str, quiet: bool = False) -> None:
    if quiet and level not in ("error",):
        return
    stream = sys.stderr if level in ("error", "warn") else sys.stdout
    prefix = {"error": "ERROR", "warn": "WARN ", "ok": "OK   ", "action": "  ..  "}.get(level, "  -  ")
    stream.write(f"{prefix} {message}\n")
    stream.flush()


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    command = args.command or "run"

    if command == "run":
        return _cmd_run(args)
    if command == "validate":
        return _cmd_validate(args)
    if command == "record":
        return _cmd_record(args)
    if command == "list":
        return _cmd_list()
    if command == "browsers":
        return _cmd_browsers()
    parser.print_help()
    return 1


def _cmd_run(args) -> int:
    path = _resolve_script(args.script)
    script = Script.from_dict(json.loads(path.read_text(encoding="utf-8")))
    variables: dict[str, str] = {}
    for item in args.var or []:
        if "=" in item:
            key, value = item.split("=", 1)
            variables[key.strip()] = value
        else:
            variables[item.strip()] = ""

    loop_mode = "count"
    if args.forever:
        loop_mode = "infinite"
    elif args.duration:
        loop_mode = "duration"
    request = RunRequest(
        script=script,
        loop_mode=loop_mode,
        loop_count=args.loops or 1,
        duration_minutes=args.duration or 10,
        headless=args.headless,
        browser_kind=args.browser,
        browser_executable=args.browser_path,
        user_data_dir=args.profile,
        data_file=args.data,
        slow_mo_ms=args.slow_mo,
        stop_on_error=args.stop_on_error,
        variables=variables,
        keep_browser_open=False,
        close_browser_when_done=True,
    )
    engine = AutomationEngine(
        request,
        on_log=lambda level, message: _print(level, message, args.quiet),
        on_status=lambda status: None,
        on_loop=lambda index, total: None,
    )
    try:
        result = engine.run()
    except KeyboardInterrupt:
        engine.stop()
        print("\nInterrupted.")
        return 130
    data = result.to_dict()
    append_history(HistoryRecord.from_result(data, trigger="cli"))
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(
            f"\n{result.outcome}: {result.loops_completed} loop(s), "
            f"{result.steps_ok} step(s) ok, {result.steps_failed} failed "
            f"in {data.get('duration')}"
        )
    return 0 if result.outcome in ("completed", "completed_with_errors", "stopped") else 1


def _cmd_validate(args) -> int:
    path = _resolve_script(args.script)
    script = Script.from_dict(json.loads(path.read_text(encoding="utf-8")))
    problems = script.validate()
    print(f"{script.name}: {script.step_count} step(s), {len(script.used_variables())} variable(s)")
    if problems:
        for problem in problems:
            print(f"  ! {problem}")
        return 1
    print("  no problems found")
    return 0


def _cmd_record(args) -> int:
    from .browser import LaunchRequest
    from .recorder.session import RecorderSession
    from .recorder.builder import RecorderOptions

    options = RecorderOptions(record_scroll=args.record_scroll, record_hover=args.record_hover)
    session = RecorderSession(
        LaunchRequest(kind=args.browser, executable=args.browser_path, user_data_dir=args.profile),
        name=args.name,
        options=options,
        start_url=args.url,
        on_log=lambda level, message: _print(level, message),
        on_step=lambda count, step: print(f"  {count:>3}. {step.label:<22} {step.summary()}"),
    )
    session.start()
    print("Recording... close the browser window (or press Ctrl+C) to finish.")
    try:
        while not session.finished:
            session.pump(200)
    except KeyboardInterrupt:
        pass
    script = session.finish()
    session.close()
    store = ScriptStore()
    target = Path(args.save_to) if args.save_to else store.unique_path_for(script.name)
    store.save(script, target)
    print(f"Saved {script.step_count} step(s) to {target}")
    return 0


def _cmd_list() -> int:
    store = ScriptStore()
    entries = store.list_entries()
    if not entries:
        print("No scripts yet - record one from the app or the CLI.")
        return 0
    for entry in entries:
        print(f"{entry.display_name:<40} {entry.step_count:>4} steps  {entry.updated_at[:19]}  {entry.path.name}")
    return 0


def _cmd_browsers() -> int:
    from .browser import detect_all

    for kind, choice in detect_all().items():
        print(f"{kind:<10} {choice.display}")
    return 0


def try_feed(path: str):
    try:
        return DataFeed.from_file(path)
    except Exception as exc:  # pragma: no cover
        print(f"Could not read {path}: {exc}", file=sys.stderr)
        return None


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
