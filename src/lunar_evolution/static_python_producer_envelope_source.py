"""Pure pinned source composition for the opt-in generic-envelope delivery successor.

No filesystem access, source execution, process launch or runtime acceptance.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from types import MappingProxyType

from .static_python_fixed_live_modules import (
    FIXED_LIVE_COLLECTOR_SOURCE_BYTES,
    FIXED_LIVE_RUNTIME_SOURCE_BYTES,
    FIXED_LIVE_RUNTIME_SOURCE_SHA256,
    compose_fixed_python_live_main,
)

FIXED_PRODUCER_ENVELOPE_PROFILE = "fixed-producer-lifecycle-v2"
FIXED_PRODUCER_ENVELOPE_PROTOCOL = "lunar-fixed-producer-completion-v2"
FIXED_PRODUCER_ENVELOPE_FD = 197
MAX_FIXED_PRODUCER_ENVELOPE_COMPLETION_BYTES = 16 * 1024
ENVELOPE_LAUNCHER_PATH = "runtime/launcher_producer_envelope.c"
FIXED_PRODUCER_ENVELOPE_SOURCE_BYTES = 10551
FIXED_PRODUCER_ENVELOPE_SOURCE_SHA256 = "d4b1b50b6d635a03697cf26c7999325632e267d8062c819f0373864bdfd6fc97"
FIXED_PRODUCER_ENVELOPE_LAUNCHER_SOURCE_BYTES = 5983
FIXED_PRODUCER_ENVELOPE_LAUNCHER_SOURCE_SHA256 = "2b0abb75dceef5dc45d1693326a69f62e2dc1ace6829ae635633f36d6f3e0ac3"
SOURCE_PINS = MappingProxyType({
    "tools/openevolve_fixed_profile/assets/fixed_entrypoint.py": (
        16734, "d5b2009c225c68f06a4cea0d12a580a2b3619e905ab70b5a14cc4d6df9ab3c72",
    ),
    "tools/shinka_fixed_profile/assets/fixed_entrypoint.py": (
        20091, "b42fe9f7876888784332ec9605e332a043db4ec6be380a5dd0a87ed901cdfeb9",
    ),
    "tools/static_python_rsi_fixture/assets/fixed_producer_envelope.py": (
        FIXED_PRODUCER_ENVELOPE_SOURCE_BYTES, FIXED_PRODUCER_ENVELOPE_SOURCE_SHA256,
    ),
    "tools/static_python_rsi_fixture/assets/launcher_producer_envelope.c": (
        FIXED_PRODUCER_ENVELOPE_LAUNCHER_SOURCE_BYTES, FIXED_PRODUCER_ENVELOPE_LAUNCHER_SOURCE_SHA256,
    ),
})
ENVELOPE_ENTRYPOINT_PINS = MappingProxyType({
    "openevolve": (27327, "a7375b97903f5ac1f4184b24a61d4bad5160663d9edf85674411b007c45431c0"),
    "shinka": (30680, "d7ed075587e29f1d24d93409127e3b48e3b45393fc5e875690da3b5b0cae068b"),
})


class FixedProducerEnvelopeSourceError(ValueError):
    """Fixed source-preparation refusal without caller paths or source prose."""


@dataclass(frozen=True, slots=True)
class FixedProducerEnvelopeSources:
    """Source material only; not acquired computation or runtime authority."""

    profile: str
    solver: str
    producer_source: bytes
    frozen_main_source: bytes
    launcher_source: bytes


def _selection(solver: str, profile: str | None) -> None:
    if (type(profile) is not str or profile != FIXED_PRODUCER_ENVELOPE_PROFILE
            or type(solver) is not str or solver not in {"openevolve", "shinka"}):
        raise FixedProducerEnvelopeSourceError("fixed_producer_envelope_source_profile")


def _pinned(raw: bytes, relative: str) -> None:
    size, digest = SOURCE_PINS[relative]
    if type(raw) is not bytes or len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
        raise FixedProducerEnvelopeSourceError("fixed_producer_envelope_source_pin")


def compose_fixed_producer_envelope_entrypoint(
    solver: str, *, original_producer_source: bytes, envelope_source: bytes,
    profile: str | None = None,
) -> bytes:
    """Append the new callable without changing the original main or propose."""
    _selection(solver, profile)
    _pinned(original_producer_source, "tools/" + solver + "_fixed_profile/assets/fixed_entrypoint.py")
    _pinned(envelope_source, "tools/static_python_rsi_fixture/assets/fixed_producer_envelope.py")
    result = (original_producer_source
              + f"\n_LUNAR_COMPLETION_SOLVER = {solver!r}\n\n".encode("ascii") + envelope_source)
    size, digest = ENVELOPE_ENTRYPOINT_PINS[solver]
    if len(result) != size or hashlib.sha256(result).hexdigest() != digest:
        raise FixedProducerEnvelopeSourceError("fixed_producer_envelope_source_pin")
    return result


def compose_fixed_producer_envelope_sources(
    solver: str, *, original_producer_source: bytes, envelope_source: bytes,
    launcher_source: bytes, startup_main_source: bytes,
    frozen_names: tuple[str, ...], builtin_names: tuple[str, ...],
    aliases: tuple[tuple[str, str], ...], frozen_packages: tuple[str, ...],
    profile: str | None = None,
) -> FixedProducerEnvelopeSources:
    """Pure comparison/composition; supplied bytes never acquire authority."""
    producer = compose_fixed_producer_envelope_entrypoint(
        solver, original_producer_source=original_producer_source,
        envelope_source=envelope_source, profile=profile,
    )
    _pinned(launcher_source, "tools/static_python_rsi_fixture/assets/launcher_producer_envelope.c")
    main = compose_fixed_producer_envelope_main(
        solver, startup_main_source=startup_main_source, frozen_names=frozen_names,
        builtin_names=builtin_names, aliases=aliases, frozen_packages=frozen_packages,
        profile=profile,
    )
    return FixedProducerEnvelopeSources(
        FIXED_PRODUCER_ENVELOPE_PROFILE, solver, producer, main, launcher_source,
    )


def compose_fixed_producer_envelope_main(
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
        raise FixedProducerEnvelopeSourceError("fixed_producer_envelope_source_startup")
    expected = compose_fixed_python_live_main(
        solver, frozen_names=frozen_names, builtin_names=builtin_names,
        aliases=aliases, frozen_packages=frozen_packages,
        collector_source=startup_main_source[-offset:][:FIXED_LIVE_COLLECTOR_SOURCE_BYTES],
        runtime_observation_source=startup_main_source[-FIXED_LIVE_RUNTIME_SOURCE_BYTES:],
    )
    if startup_main_source != expected:
        raise FixedProducerEnvelopeSourceError("fixed_producer_envelope_source_startup")
    old = (
        "def _rsi_launch(manifest_sha256):\n"
        '    if (type(manifest_sha256) is not str or len(manifest_sha256) != 64\n'
        '            or any(c not in "0123456789abcdef" for c in manifest_sha256)):\n'
        '        raise ValueError("invalid RSI manifest digest syntax")\n'
        f"    from {solver}.lunar_fixed import main\n"
        '    return main(["--lunar-rsi-input-v1", manifest_sha256])\n'
    ).encode("ascii")
    new = (
        "def _rsi_launch(manifest_sha256, deadline_monotonic_ns, run_id, producer_fingerprint):\n"
        '    if (type(manifest_sha256) is not str or len(manifest_sha256) != 64\n'
        '            or any(c not in "0123456789abcdef" for c in manifest_sha256)\n'
        '            or type(deadline_monotonic_ns) is not int\n'
        '            or not 0 < deadline_monotonic_ns < 2 ** 64\n'
        '            or type(run_id) is not str or not 1 <= len(run_id) <= 128\n'
        '            or run_id[0] not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"\n'
        '            or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-" for c in run_id)\n'
        '            or type(producer_fingerprint) is not str or len(producer_fingerprint) != 64\n'
        '            or any(c not in "0123456789abcdef" for c in producer_fingerprint)):\n'
        '        raise ValueError("invalid RSI completion launch input")\n'
        f"    from {solver}.lunar_fixed import _lunar_envelope_main\n"
        "    return _lunar_envelope_main(manifest_sha256, deadline_monotonic_ns, run_id, producer_fingerprint)\n"
    ).encode("ascii")
    if expected.count(old) != 1:
        raise FixedProducerEnvelopeSourceError("fixed_producer_envelope_source_dispatch")
    return expected.replace(old, new, 1)


FIXED_PRODUCER_ENVELOPE_ARGV_MARKER = "--lunar-fixed-producer-envelope-v1"
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_DIGEST = re.compile(r"[0-9a-f]{64}")


def fixed_producer_envelope_launch_argv(
    executable: str, *, run_id: str, producer_fingerprint: str, manifest_sha256: str,
) -> tuple[str, ...]:
    """Prepare exact non-secret argv; matching fields alone confer no authority.

    The host must separately match these values to its original intent and
    attestation, which bind the complete argv before target gate release.
    The existing input-marker tail remains unchanged; no file grant is added.
    """
    if (type(executable) is not str or not executable or len(executable) > 4096
            or any(character in executable for character in ("\\", "\0", "\n", "\r"))
            or type(run_id) is not str or _IDENTIFIER.fullmatch(run_id) is None
            or type(producer_fingerprint) is not str or _DIGEST.fullmatch(producer_fingerprint) is None
            or type(manifest_sha256) is not str or _DIGEST.fullmatch(manifest_sha256) is None):
        raise FixedProducerEnvelopeSourceError("fixed_producer_envelope_source_argv")
    return (executable, FIXED_PRODUCER_ENVELOPE_ARGV_MARKER, run_id, producer_fingerprint,
            "--lunar-rsi-input-v1", manifest_sha256)


def validate_fixed_producer_envelope_argv(
    argv: tuple[str, ...], *, run_id: str,
    producer_fingerprint: str, manifest_sha256: str,
) -> None:
    """Strictly compare argv with original expected values; never infer them."""
    if type(argv) is not tuple or len(argv) != 6 or any(type(item) is not str for item in argv):
        raise FixedProducerEnvelopeSourceError("fixed_producer_envelope_source_argv")
    expected = fixed_producer_envelope_launch_argv(
        argv[0], run_id=run_id, producer_fingerprint=producer_fingerprint,
        manifest_sha256=manifest_sha256,
    )
    if argv != expected:
        raise FixedProducerEnvelopeSourceError("fixed_producer_envelope_source_argv")
