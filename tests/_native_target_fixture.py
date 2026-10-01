"""Compile provider-free targets without adding a production runtime allowlist."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def compile_native_target(source: Path, target: Path, *flags: str) -> None:
    compiler = shutil.which("clang") or shutil.which("cc")
    if compiler is None:
        raise RuntimeError("local native fixture compiler unavailable")
    # Linux's native policy permits only sealed target bytes and caller-owned
    # work/output dirs.  Static fixtures need no ELF interpreter/library reads.
    platform_flags = ("-static",) if sys.platform == "linux" else ()
    subprocess.run(
        [compiler, "-Wall", "-Wextra", "-Werror", *platform_flags, *flags,
         str(source), "-o", str(target)],
        check=True, capture_output=True, timeout=30, env={"PATH": os.defpath, "LANG": "C"},
    )
