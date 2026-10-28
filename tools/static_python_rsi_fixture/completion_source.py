"""Pinned, explicitly selected source preparation for producer completion.

No producer, observer, compiler or target is executed here. These source bytes
are not an original-attempt acquisition or an accepted static installation.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from lunar_evolution.static_python_producer_completion_source import (
    COMPLETION_LAUNCHER_PATH,
    FIXED_PRODUCER_COMPLETION_FD,
    FIXED_PRODUCER_COMPLETION_PROTOCOL,
    FIXED_PRODUCER_LIFECYCLE_PROFILE,
    MAX_FIXED_PRODUCER_COMPLETION_BYTES,
    SOURCE_PINS,
    FixedProducerCompletionSourceError,
    FixedProducerCompletionSources,
    compose_fixed_producer_completion_entrypoint,
    compose_fixed_producer_completion_sources,
)
from tools.static_python_rsi_fixture.live_module_source import prepare_fixed_live_main

_ROOT = Path(__file__).resolve().parents[2]
_PINS = dict(SOURCE_PINS)

__all__ = [
    "COMPLETION_LAUNCHER_PATH",
    "FIXED_PRODUCER_COMPLETION_FD",
    "FIXED_PRODUCER_COMPLETION_PROTOCOL",
    "FIXED_PRODUCER_LIFECYCLE_PROFILE",
    "MAX_FIXED_PRODUCER_COMPLETION_BYTES",
    "FixedProducerCompletionSourceError",
    "FixedProducerCompletionSources",
    "prepare_fixed_producer_completion_entrypoint",
    "prepare_fixed_producer_completion_sources",
]


def _source(relative: str) -> bytes:
    size, digest = _PINS[relative]
    path = _ROOT / relative
    try:
        if any(part.is_symlink() for part in (path, *path.parents)):
            raise ValueError
        with path.open("rb") as handle:
            raw = handle.read(size + 1)
        if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError
    except (OSError, ValueError):
        raise FixedProducerCompletionSourceError("fixed_producer_completion_source_pin") from None
    return raw


def prepare_fixed_producer_completion_sources(
    solver: str, *, frozen_names: tuple[str, ...], builtin_names: tuple[str, ...],
    aliases: tuple[tuple[str, str], ...], frozen_packages: tuple[str, ...],
    profile: str | None = None,
) -> FixedProducerCompletionSources:
    """Read pinned source and invoke the pure separately versioned composer."""
    if (type(profile) is not str or profile != FIXED_PRODUCER_LIFECYCLE_PROFILE
            or type(solver) is not str or solver not in {"openevolve", "shinka"}):
        raise FixedProducerCompletionSourceError("fixed_producer_completion_source_profile")
    original = _source("tools/" + solver + "_fixed_profile/assets/fixed_entrypoint.py")
    supplement = _source("tools/static_python_rsi_fixture/assets/fixed_producer_lifecycle.py")
    launcher = _source("tools/static_python_rsi_fixture/assets/launcher_producer_completion.c")
    main = prepare_fixed_live_main(
        solver, frozen_names=frozen_names, builtin_names=builtin_names,
        aliases=aliases, frozen_packages=frozen_packages, runtime_observation=True,
    )
    return compose_fixed_producer_completion_sources(
        solver, original_producer_source=original, lifecycle_source=supplement,
        launcher_source=launcher, startup_main_source=main, frozen_names=frozen_names,
        builtin_names=builtin_names, aliases=aliases, frozen_packages=frozen_packages, profile=profile,
    )


def prepare_fixed_producer_completion_entrypoint(
    solver: str, original_producer_source: bytes, *, profile: str | None = None,
) -> bytes:
    """Supply the new imports before the closure's finite traversal starts."""
    if (type(profile) is not str or profile != FIXED_PRODUCER_LIFECYCLE_PROFILE
            or type(solver) is not str or solver not in {"openevolve", "shinka"}):
        raise FixedProducerCompletionSourceError("fixed_producer_completion_source_profile")
    return compose_fixed_producer_completion_entrypoint(
        solver, original_producer_source=original_producer_source,
        lifecycle_source=_source("tools/static_python_rsi_fixture/assets/fixed_producer_lifecycle.py"),
        profile=profile,
    )
