"""Local source preparation CLI, deliberately without build or execution options."""

from __future__ import annotations

import argparse
from pathlib import Path

from .recipe import RSILaunchSourceError, emit_rsi_launch_source_plan


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare fixed RSI marker source assets only")
    parser.add_argument("--destination", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        path = emit_rsi_launch_source_plan(arguments.destination)
    except RSILaunchSourceError as exc:
        parser.exit(1, str(exc) + "\n")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
