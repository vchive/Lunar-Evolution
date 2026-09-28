#!/usr/bin/env python3
"""Launch one registered acceptance attempt in a fresh pinned interpreter.

This file intentionally imports only the standard library.  The child process loads
the product package through ``acceptance_pinned_loader`` after checking the complete
registered source inventory, so an installed package or cached bytecode cannot satisfy
the acceptance run by accident.
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

_ENV_NAMES = frozenset({
    "LUNAR_EVOLUTION_MODEL_ENDPOINT", "LUNAR_EVOLUTION_MODEL", "LUNAR_EVOLUTION_API_KEY",
})
_MAX_ENV_BYTES = 8192


def _configured_environment(checkout: Path) -> dict[str, str]:
    environment = os.environ.copy()
    path = checkout / ".env"
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        return environment
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > _MAX_ENV_BYTES
        ):
            raise ValueError("invalid env file")
        data = os.read(descriptor, _MAX_ENV_BYTES + 1)
        if len(data) != info.st_size:
            raise ValueError("changed env file")
    finally:
        os.close(descriptor)
    values: dict[str, str] = {}
    for line in data.decode("utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        name, separator, value = line.partition("=")
        if (
            separator != "=" or name not in _ENV_NAMES or name in values
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
        ):
            raise ValueError("invalid env setting")
        values[name] = value
    environment.update({name: value for name, value in values.items() if value})
    return environment


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run exactly one registered Lunar Evolution acceptance attempt."
    )
    parser.add_argument(
        "--registration", "--registration-path", dest="registration", required=True,
        type=Path, help="canonical acceptance registration JSON",
    )
    parser.add_argument(
        "--seal", "--seal-path", dest="seal", required=True, type=Path,
        help="canonical registration seal JSON",
    )
    parser.add_argument(
        "--checkout-root", required=True, type=Path,
        help="clean checkout whose registered source bytes will be executed",
    )
    parser.add_argument(
        "--campaign-parent", required=True, type=Path,
        help="private parent directory for the one fresh campaign root",
    )
    return parser


def _error(code: str) -> int:
    sys.stdout.write(json.dumps({"status": "failed", "error": code}, separators=(",", ":")))
    sys.stdout.write("\n")
    return 2


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    checkout = args.checkout_root.expanduser().absolute()
    registration = args.registration.expanduser().absolute()
    seal = args.seal.expanduser().absolute()
    campaign_parent = args.campaign_parent.expanduser().absolute()
    loader = checkout / "src" / "lunar_evolution" / "acceptance_pinned_loader.py"
    if not loader.is_file():
        return _error("acceptance_loader_missing")

    try:
        environment = _configured_environment(checkout)
    except (OSError, UnicodeError, ValueError):
        return _error("acceptance_env_invalid")

    # ``-I -S`` gives the child a clean import environment.  The environment is still
    # inherited for the provider endpoint/key; those values are never placed in argv.
    command = [
        sys.executable, "-I", "-S", str(loader), str(checkout), str(registration),
        str(seal), str(campaign_parent),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=checkout,
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return _error("acceptance_isolated_runner_unavailable")

    # The pinned child emits one fixed JSON result.  Preserve it for automation while
    # keeping diagnostics off stdout, where they could be mistaken for a result record.
    if completed.stdout:
        sys.stdout.buffer.write(completed.stdout)
        if not completed.stdout.endswith(b"\n"):
            sys.stdout.buffer.write(b"\n")
        sys.stdout.flush()
    else:
        return _error("acceptance_isolated_runner_failed")
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
