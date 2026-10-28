"""Pure pinned source composition for the opt-in completion successor.

No filesystem access, source execution, process launch or runtime acceptance.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from types import MappingProxyType

from .static_python_fixed_live_modules import (
    FIXED_LIVE_COLLECTOR_SOURCE_BYTES,
    FIXED_LIVE_RUNTIME_SOURCE_BYTES,
    FIXED_LIVE_RUNTIME_SOURCE_SHA256,
    compose_fixed_python_live_main,
)

FIXED_PRODUCER_LIFECYCLE_PROFILE = "fixed-producer-lifecycle-v1"
FIXED_PRODUCER_COMPLETION_PROTOCOL = "lunar-fixed-producer-completion-v1"
FIXED_PRODUCER_COMPLETION_FD = 197
MAX_FIXED_PRODUCER_COMPLETION_BYTES = 16 * 1024
COMPLETION_LAUNCHER_PATH = "runtime/launcher_producer_completion.c"
FIXED_PRODUCER_LIFECYCLE_SOURCE_BYTES = 8836
FIXED_PRODUCER_LIFECYCLE_SOURCE_SHA256 = "0a5ca9cb31a6f8e56aed0488fd905950b07d83ba8e2d6d3f86c66dfcb7e561b7"
FIXED_PRODUCER_COMPLETION_LAUNCHER_SOURCE_BYTES = 5178
FIXED_PRODUCER_COMPLETION_LAUNCHER_SOURCE_SHA256 = "84e90827793f27eddd03e36f291b8a1b496c0c6ca9a88b8d262cd882903d5c5c"
SOURCE_PINS = MappingProxyType({
    "tools/openevolve_fixed_profile/assets/fixed_entrypoint.py": (
        16734, "d5b2009c225c68f06a4cea0d12a580a2b3619e905ab70b5a14cc4d6df9ab3c72",
    ),
    "tools/shinka_fixed_profile/assets/fixed_entrypoint.py": (
        20091, "b42fe9f7876888784332ec9605e332a043db4ec6be380a5dd0a87ed901cdfeb9",
    ),
    "tools/static_python_rsi_fixture/assets/fixed_producer_lifecycle.py": (
        FIXED_PRODUCER_LIFECYCLE_SOURCE_BYTES, FIXED_PRODUCER_LIFECYCLE_SOURCE_SHA256,
    ),
    "tools/static_python_rsi_fixture/assets/launcher_producer_completion.c": (
        FIXED_PRODUCER_COMPLETION_LAUNCHER_SOURCE_BYTES, FIXED_PRODUCER_COMPLETION_LAUNCHER_SOURCE_SHA256,
    ),
})
COMPLETION_ENTRYPOINT_PINS = MappingProxyType({
    "openevolve": (25612, "c5d30376b10c7952bdd249067fab534ef20e0b7a5dbc5f955082428fc606f322"),
    "shinka": (28965, "858de23b1a1a5d7c02d09e7399549dab68c6ad52ddd70823424cad9d728083d7"),
})


class FixedProducerCompletionSourceError(ValueError):
    """Fixed source-preparation refusal without caller paths or source prose."""


@dataclass(frozen=True, slots=True)
class FixedProducerCompletionSources:
    """Source material only; not acquired computation or runtime authority."""

    profile: str
    solver: str
    producer_source: bytes
    frozen_main_source: bytes
    launcher_source: bytes


def _selection(solver: str, profile: str | None) -> None:
    if (type(profile) is not str or profile != FIXED_PRODUCER_LIFECYCLE_PROFILE
            or type(solver) is not str or solver not in {"openevolve", "shinka"}):
        raise FixedProducerCompletionSourceError("fixed_producer_completion_source_profile")


def _pinned(raw: bytes, relative: str) -> None:
    size, digest = SOURCE_PINS[relative]
    if type(raw) is not bytes or len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
        raise FixedProducerCompletionSourceError("fixed_producer_completion_source_pin")


def compose_fixed_producer_completion_entrypoint(
    solver: str, *, original_producer_source: bytes, lifecycle_source: bytes,
    profile: str | None = None,
) -> bytes:
    """Append the new callable without changing the original main or propose."""
    _selection(solver, profile)
    _pinned(original_producer_source, "tools/" + solver + "_fixed_profile/assets/fixed_entrypoint.py")
    _pinned(lifecycle_source, "tools/static_python_rsi_fixture/assets/fixed_producer_lifecycle.py")
    result = (original_producer_source
              + f"\n_LUNAR_COMPLETION_SOLVER = {solver!r}\n\n".encode("ascii") + lifecycle_source)
    size, digest = COMPLETION_ENTRYPOINT_PINS[solver]
    if len(result) != size or hashlib.sha256(result).hexdigest() != digest:
        raise FixedProducerCompletionSourceError("fixed_producer_completion_source_pin")
    return result


def compose_fixed_producer_completion_sources(
    solver: str, *, original_producer_source: bytes, lifecycle_source: bytes,
    launcher_source: bytes, startup_main_source: bytes,
    frozen_names: tuple[str, ...], builtin_names: tuple[str, ...],
    aliases: tuple[tuple[str, str], ...], frozen_packages: tuple[str, ...],
    profile: str | None = None,
) -> FixedProducerCompletionSources:
    """Pure comparison/composition; supplied bytes never acquire authority."""
    producer = compose_fixed_producer_completion_entrypoint(
        solver, original_producer_source=original_producer_source,
        lifecycle_source=lifecycle_source, profile=profile,
    )
    _pinned(launcher_source, "tools/static_python_rsi_fixture/assets/launcher_producer_completion.c")
    main = compose_fixed_producer_completion_main(
        solver, startup_main_source=startup_main_source, frozen_names=frozen_names,
        builtin_names=builtin_names, aliases=aliases, frozen_packages=frozen_packages,
        profile=profile,
    )
    return FixedProducerCompletionSources(
        FIXED_PRODUCER_LIFECYCLE_PROFILE, solver, producer, main, launcher_source,
    )


def compose_fixed_producer_completion_main(
    solver: str, *, startup_main_source: bytes,
    frozen_names: tuple[str, ...], builtin_names: tuple[str, ...],
    aliases: tuple[tuple[str, str], ...], frozen_packages: tuple[str, ...],
    profile: str | None = None,
) -> bytes:
    """Validate canonical expanded startup and change only explicit dispatch."""
    _selection(solver, profile)
    separator = f"\n_LUNAR_LIVE_RUNTIME_SHA256 = {FIXED_LIVE_RUNTIME_SOURCE_SHA256!r}\n\n".encode("ascii")
    offset = FIXED_LIVE_COLLECTOR_SOURCE_BYTES + len(separator) + FIXED_LIVE_RUNTIME_SOURCE_BYTES
    if type(startup_main_source) is not bytes or not offset < len(startup_main_source) <= 64 * 1024:
        raise FixedProducerCompletionSourceError("fixed_producer_completion_source_startup")
    expected = compose_fixed_python_live_main(
        solver, frozen_names=frozen_names, builtin_names=builtin_names,
        aliases=aliases, frozen_packages=frozen_packages,
        collector_source=startup_main_source[-offset:][:FIXED_LIVE_COLLECTOR_SOURCE_BYTES],
        runtime_observation_source=startup_main_source[-FIXED_LIVE_RUNTIME_SOURCE_BYTES:],
    )
    if startup_main_source != expected:
        raise FixedProducerCompletionSourceError("fixed_producer_completion_source_startup")
    old = (
        "def _rsi_launch(manifest_sha256):\n"
        '    if (type(manifest_sha256) is not str or len(manifest_sha256) != 64\n'
        '            or any(c not in "0123456789abcdef" for c in manifest_sha256)):\n'
        '        raise ValueError("invalid RSI manifest digest syntax")\n'
        f"    from {solver}.lunar_fixed import main\n"
        '    return main(["--lunar-rsi-input-v1", manifest_sha256])\n'
    ).encode("ascii")
    new = (
        "def _rsi_launch(manifest_sha256, deadline_monotonic_ns):\n"
        '    if (type(manifest_sha256) is not str or len(manifest_sha256) != 64\n'
        '            or any(c not in "0123456789abcdef" for c in manifest_sha256)\n'
        '            or type(deadline_monotonic_ns) is not int\n'
        '            or not 0 < deadline_monotonic_ns < 2 ** 64):\n'
        '        raise ValueError("invalid RSI completion launch input")\n'
        f"    from {solver}.lunar_fixed import _lunar_completion_main\n"
        "    return _lunar_completion_main(manifest_sha256, deadline_monotonic_ns)\n"
    ).encode("ascii")
    if expected.count(old) != 1:
        raise FixedProducerCompletionSourceError("fixed_producer_completion_source_dispatch")
    return expected.replace(old, new, 1)
