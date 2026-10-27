"""Read the fixed collector asset only for the explicitly selected source profile."""

from __future__ import annotations

import hashlib
from pathlib import Path

from lunar_evolution.static_python_fixed_live_modules import (
    FIXED_LIVE_COLLECTOR_SOURCE_BYTES,
    FIXED_LIVE_COLLECTOR_SOURCE_SHA256,
    compose_fixed_python_live_main,
)


def prepare_fixed_live_main(
    solver: str, *, frozen_names: tuple[str, ...], builtin_names: tuple[str, ...],
    aliases: tuple[tuple[str, str], ...], frozen_packages: tuple[str, ...],
) -> bytes:
    """Return pinned source bytes, never execute a collector or authorize a sink."""
    path = Path(__file__).parent / "assets/fixed_live_modules.py"
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("static_python_fixed_live_source_symlink")
    with path.open("rb") as handle:
        raw = handle.read(FIXED_LIVE_COLLECTOR_SOURCE_BYTES + 1)
    if (len(raw) != FIXED_LIVE_COLLECTOR_SOURCE_BYTES
            or hashlib.sha256(raw).hexdigest() != FIXED_LIVE_COLLECTOR_SOURCE_SHA256):
        raise ValueError("static_python_fixed_live_source_pin")
    return compose_fixed_python_live_main(
        solver, frozen_names=frozen_names, builtin_names=builtin_names,
        aliases=aliases, frozen_packages=frozen_packages, collector_source=raw,
    )
