"""Pinned, explicitly selected source preparation for producer generic-envelope delivery.

No producer, observer, compiler or target is executed here. These source bytes
are not an original-attempt acquisition or an accepted static installation.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from lunar_evolution.static_python_producer_envelope_source import (
    ENVELOPE_LAUNCHER_PATH,
    FIXED_PRODUCER_ENVELOPE_FD,
    FIXED_PRODUCER_ENVELOPE_PROFILE,
    FIXED_PRODUCER_ENVELOPE_PROTOCOL,
    MAX_FIXED_PRODUCER_ENVELOPE_COMPLETION_BYTES,
    SOURCE_PINS,
    FixedProducerEnvelopeSourceError,
    FixedProducerEnvelopeSources,
    compose_fixed_producer_envelope_entrypoint,
    compose_fixed_producer_envelope_sources,
)
from tools.static_python_rsi_fixture.live_module_source import prepare_fixed_live_main

_ROOT = Path(__file__).resolve().parents[2]
_PINS = dict(SOURCE_PINS)

__all__ = [
    "ENVELOPE_LAUNCHER_PATH",
    "FIXED_PRODUCER_ENVELOPE_FD",
    "FIXED_PRODUCER_ENVELOPE_PROFILE",
    "FIXED_PRODUCER_ENVELOPE_PROTOCOL",
    "MAX_FIXED_PRODUCER_ENVELOPE_COMPLETION_BYTES",
    "FixedProducerEnvelopeSourceError",
    "FixedProducerEnvelopeSources",
    "prepare_fixed_producer_envelope_entrypoint",
    "prepare_fixed_producer_envelope_sources",
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
        raise FixedProducerEnvelopeSourceError("fixed_producer_envelope_source_pin") from None
    return raw


def prepare_fixed_producer_envelope_sources(
    solver: str, *, frozen_names: tuple[str, ...], builtin_names: tuple[str, ...],
    aliases: tuple[tuple[str, str], ...], frozen_packages: tuple[str, ...],
    profile: str | None = None,
) -> FixedProducerEnvelopeSources:
    """Read pinned source and invoke the pure separately versioned composer."""
    if (type(profile) is not str or profile != FIXED_PRODUCER_ENVELOPE_PROFILE
            or type(solver) is not str or solver not in {"openevolve", "shinka"}):
        raise FixedProducerEnvelopeSourceError("fixed_producer_envelope_source_profile")
    original = _source("tools/" + solver + "_fixed_profile/assets/fixed_entrypoint.py")
    supplement = _source("tools/static_python_rsi_fixture/assets/fixed_producer_envelope.py")
    launcher = _source("tools/static_python_rsi_fixture/assets/launcher_producer_envelope.c")
    main = prepare_fixed_live_main(
        solver, frozen_names=frozen_names, builtin_names=builtin_names,
        aliases=aliases, frozen_packages=frozen_packages, runtime_observation=True,
    )
    return compose_fixed_producer_envelope_sources(
        solver, original_producer_source=original, envelope_source=supplement,
        launcher_source=launcher, startup_main_source=main, frozen_names=frozen_names,
        builtin_names=builtin_names, aliases=aliases, frozen_packages=frozen_packages, profile=profile,
    )


def prepare_fixed_producer_envelope_entrypoint(
    solver: str, original_producer_source: bytes, *, profile: str | None = None,
) -> bytes:
    """Supply the new imports before the closure's finite traversal starts."""
    if (type(profile) is not str or profile != FIXED_PRODUCER_ENVELOPE_PROFILE
            or type(solver) is not str or solver not in {"openevolve", "shinka"}):
        raise FixedProducerEnvelopeSourceError("fixed_producer_envelope_source_profile")
    return compose_fixed_producer_envelope_entrypoint(
        solver, original_producer_source=original_producer_source,
        envelope_source=_source("tools/static_python_rsi_fixture/assets/fixed_producer_envelope.py"),
        profile=profile,
    )
