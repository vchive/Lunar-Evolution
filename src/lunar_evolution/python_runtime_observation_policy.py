"""Compare observed Python facts with an independently pinned installation.

OS launch arguments, named sys.flags and PyConfig argv are separate domains.
This pure comparison supports only the reviewed Feature189 static profile and
does not establish runtime execution, executable ownership or admission.
"""

from __future__ import annotations

import re
from typing import NoReturn

from .python_producer_binding import PythonProducerBinding, parse_python_producer_binding
from .python_producer_lifecycle import (
    PythonProducerRuntimeObservation,
    parse_python_producer_runtime_observation,
)

# The expanded fixed-solver policy deliberately has a separate entry point.
# Its startup facts cannot supply the old lifecycle's transcript/computation or
# pycache claims, and the legacy exact-type gate below remains unchanged.
from .static_python_fixed_runtime_observation import (
    FixedPythonRuntimeFacts,
    FixedPythonRuntimeObservationError,
    validate_fixed_python_runtime_observation_policy,
)
from .static_python_installation import (
    StaticPythonInstallationDescriptor,
    StaticPythonInstallationError,
    parse_static_python_installation_descriptor,
)

_SHA = re.compile(r"[0-9a-f]{64}")
_VERSION = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}")


class PythonRuntimeObservationPolicyError(ValueError):
    """Fixed local comparison refusal; no child-controlled text is reported."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> NoReturn:
    raise PythonRuntimeObservationPolicyError(code)


def _pin(value: object) -> bool:
    return type(value) is str and _SHA.fullmatch(value) is not None and value != "0" * 64


def validate_python_runtime_observation_policy(
    binding: PythonProducerBinding,
    observation: PythonProducerRuntimeObservation,
    *,
    installation_descriptor: StaticPythonInstallationDescriptor | None = None,
    installation_descriptor_sha256: str | None = None,
    installation_version: str | None = None,
    initialization_profile_sha256: str | None = None,
) -> None:
    """Reparse original descriptor bytes and compare facts without I/O.

    Every expected pin is supplied separately. Neither a descriptor DTO's current
    fields nor the child's ABI/argv can choose the expected installation. Missing
    pins refuse; historical token-shaped observation wires are still inspectable
    by their parser but cannot satisfy this comparison.
    """
    if (not _pin(installation_descriptor_sha256) or not _pin(initialization_profile_sha256)
            or type(installation_version) is not str or _VERSION.fullmatch(installation_version) is None):
        _fail("installation_pin_unverified")
    if type(installation_descriptor) is not StaticPythonInstallationDescriptor:
        _fail("installation_invalid")
    if type(binding) is not PythonProducerBinding or type(observation) is not PythonProducerRuntimeObservation:
        _fail("observation_target_mismatch")
    try:
        parsed_binding = parse_python_producer_binding(binding.to_json())
        parsed_observation = parse_python_producer_runtime_observation(observation.to_json())
        if parsed_binding != binding or parsed_observation != observation:
            _fail("observation_target_mismatch")
    except (ValueError, TypeError, AttributeError, RecursionError, OverflowError) as exc:
        raise PythonRuntimeObservationPolicyError("observation_target_mismatch") from exc
    # Exact field types precede any DTO equality or caller method. The existing
    # descriptor parser bounds and validates the entire canonical profile.
    if (type(installation_descriptor.canonical_bytes) is not bytes
            or type(installation_descriptor.descriptor_sha256) is not str
            or type(installation_descriptor.installation_version) is not str
            or type(installation_descriptor.artifact_sha256) is not str
            or type(installation_descriptor.artifact_size) is not int):
        _fail("installation_invalid")
    try:
        descriptor = parse_static_python_installation_descriptor(
            installation_descriptor.canonical_bytes,
            expected_descriptor_sha256=installation_descriptor_sha256,
            expected_installation_version=installation_version,
            expected_artifact_sha256=parsed_binding.interpreter.sha256,
        )
    except StaticPythonInstallationError as exc:
        raise PythonRuntimeObservationPolicyError("installation_invalid") from exc
    if descriptor != installation_descriptor:
        _fail("installation_invalid")
    profile = descriptor.to_dict()
    if profile["initialization_profile_sha256"] != initialization_profile_sha256:
        _fail("installation_invalid")
    target = parsed_binding.target
    if (target.platform != profile["platform"] or target.architecture != profile["architecture"]
            or target.python_version != ".".join(profile["python_version"].split(".")[:2])
            or target.abi_tag != profile["abi_profile"].split("-", 1)[0]
            or parsed_binding.interpreter.size != descriptor.artifact_size
            or parsed_binding.interpreter.mode != profile["artifact_mode"]):
        _fail("installation_binding_mismatch")

    initialization = profile["initialization_profile"]
    config, preconfig = initialization["config"], initialization["preconfig"]
    flags = {
        "isolated": config["isolated"], "ignore_environment": 1 - config["use_environment"],
        "no_site": 1 - config["site_import"], "no_user_site": 1 - config["user_site_directory"],
        "utf8_mode": preconfig["utf8_mode"], "dont_write_bytecode": 1 - config["write_bytecode"],
        "safe_path": config["safe_path"], "dev_mode": config["dev_mode"],
        "optimize": config["optimization_level"],
        "hash_randomization": int(not (config["use_hash_seed"] and config["hash_seed"] == 0)),
    }
    expected_flags = tuple(f"{name}={flags[name]}" for name in sorted(flags))
    actual = parsed_observation
    expected_version = tuple(int(part) for part in profile["python_version"].split("."))
    if (
        actual.binding_sha256 != parsed_binding.binding_sha256
        or (actual.version_major, actual.version_minor, actual.version_micro) != expected_version
        or actual.cache_tag != profile["cache_tag"] or actual.abi_profile != profile["abi_profile"]
        or actual.flags != expected_flags
        or actual.argv != tuple(config["argv"]) or actual.orig_argv != tuple(config["orig_argv"])
        or actual.sys_path != tuple(config["module_search_paths"])
        or actual.startup_modules != tuple(initialization["expected_startup_modules"])
        or actual.filesystem_encoding != config["filesystem_encoding"]
        or actual.filesystem_errors != config["filesystem_errors"]
        or actual.stdio_encoding != config["stdio_encoding"] or actual.stdio_errors != config["stdio_errors"]
        or actual.execution_performed is not True or actual.pycache_absent is not True
        or actual.runtime_load_protection is not False or actual.production_admission is not False
        or actual.general_code_origin_protection is not False
    ):
        _fail("observation_target_mismatch")


__all__ = [
    "FixedPythonRuntimeFacts",
    "FixedPythonRuntimeObservationError",
    "PythonRuntimeObservationPolicyError",
    "validate_fixed_python_runtime_observation_policy",
    "validate_python_runtime_observation_policy",
]
