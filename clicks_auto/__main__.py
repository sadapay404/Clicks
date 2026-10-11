"""``python -m clicks_auto`` - GUI by default, CLI for the documented commands."""

from __future__ import annotations

import sys

CLI_COMMANDS = {"run", "validate", "record", "list", "browsers", "-h", "--help", "--version"}


def main() -> int:
    args = sys.argv[1:]
    if args and args[0] in CLI_COMMANDS and args[0] not in ("-h", "--help", "--version"):
        from .cli import main as cli_main

        return cli_main(args)
    if args and args[0] in ("-h", "--help"):
        from .cli import _build_parser

        _build_parser().print_help()
        print("\nRunning without a command opens the graphical interface.")
        return 0
    if args and args[0] == "--version":
        from . import __version__

        print(f"clicks-auto {__version__}")
        return 0
    from .app import run_gui

    return run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
