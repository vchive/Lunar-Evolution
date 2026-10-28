"""Compare actually captured expanded-runtime facts; never synthesize lifecycle evidence.

The old nine-module observation policy remains exact and separate. These facts
are captured before solver entry, so they cannot establish solver completion,
transcript/computation digests, pycache absence, custody or admission.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from . import static_python_fixed_live_modules as live
from . import static_python_fixed_profile as profile
from .static_python_installation import _FIXED

_RUNTIME_FIELDS = frozenset({
    "version", "releaselevel", "serial", "implementation", "cache_tag", "abiflags",
    "debug_build", "gil_enabled", "platform", "architecture", "maxsize", "argv",
    "orig_argv", "hash_randomization", "filesystem_encoding", "filesystem_errors", "stdio",
})


class FixedPythonRuntimeObservationError(ValueError):
    """Fixed local comparison code without child-controlled content."""

    def __init__(self) -> None:
        super().__init__("fixed_python_runtime_observation_refused")


@dataclass(frozen=True, slots=True)
class FixedPythonRuntimeFacts:
    """Actual compared startup facts, retaining the original sink wire."""

    live_modules_observation: live.FixedPythonBoundLiveModules
    version_major: int
    version_minor: int
    version_micro: int
    cache_tag: str
    abi_profile: str
    argv: tuple[str, ...]
    orig_argv: tuple[str, ...]
    flags: tuple[str, ...]
    filesystem_encoding: str
    filesystem_errors: str
    stdio: tuple[tuple[str, str], ...]
    sys_path: tuple[str, ...]
    startup_modules: tuple[str, ...]
    live_runtime_authenticated: bool = False
    immutable_custody_verified: bool = False
    production_admission: bool = False
    online_publication: bool = False


def _runtime_facts(
    installed: profile.FixedPythonInstallation, observation: live.FixedPythonBoundLiveModules,
    payload: dict,
) -> FixedPythonRuntimeFacts:
    actual = profile._object(payload["runtime"], _RUNTIME_FIELDS)
    config = installed.to_dict()["initialization"]["config"]
    version = actual["version"]
    if (type(version) is not list or len(version) != 3
            or any(type(part) is not int or not 0 <= part <= 999 for part in version)
            or version != [int(part) for part in _FIXED["python_version"].split(".")]
            or actual["implementation"] != "cpython" or actual["releaselevel"] != "final"
            or type(actual["serial"]) is not int or actual["serial"] != 0
            or actual["cache_tag"] != _FIXED["cache_tag"] or actual["abiflags"] != ""
            or actual["debug_build"] is not False or actual["gil_enabled"] is not True
            or actual["platform"] != _FIXED["platform"]
            or actual["architecture"] != _FIXED["architecture"]
            or type(actual["maxsize"]) is not int or actual["maxsize"] != 2**63 - 1
            or type(actual["hash_randomization"]) is not int
            or actual["hash_randomization"] != int(not (config["use_hash_seed"] and config["hash_seed"] == 0))):
        raise ValueError
    for name in ("argv", "orig_argv"):
        if (type(actual[name]) is not list or not 0 < len(actual[name]) <= 32
                or any(type(value) is not str or not 0 < len(value) <= 512 for value in actual[name])
                or actual[name] != config[name]):
            raise ValueError
    if (actual["filesystem_encoding"] != config["filesystem_encoding"]
            or actual["filesystem_errors"] != config["filesystem_errors"]):
        raise ValueError
    streams = profile._vector(actual["stdio"], 3)
    if len(streams) != 3:
        raise ValueError
    for index, stream in enumerate(streams):
        profile._object(stream, {"encoding", "errors"})
        # CPython deliberately uses backslashreplace for stderr independently
        # of config.stdio_errors. stdin/stdout retain the selected PyConfig.
        if (stream["encoding"] != config["stdio_encoding"]
                or stream["errors"] != ("backslashreplace" if index == 2 else config["stdio_errors"])):
            raise ValueError
    if (profile._canonical(payload["flags"]) != profile._canonical(live._FLAGS)
            or payload["sys_path"] != config["module_search_paths"]):
        raise ValueError
    flags = {**payload["flags"], "hash_randomization": actual["hash_randomization"]}
    # ABI label derives from already observed and checked version/abiflags,
    # debug and GIL facts; an expected ABI label is never copied into the wire.
    abi = "cp" + str(version[0]) + str(version[1]) + "-release-gil"
    return FixedPythonRuntimeFacts(
        observation, *version, actual["cache_tag"], abi, tuple(actual["argv"]), tuple(actual["orig_argv"]),
        tuple(f"{name}={flags[name]}" for name in sorted(flags)),
        actual["filesystem_encoding"], actual["filesystem_errors"],
        tuple((stream["encoding"], stream["errors"]) for stream in streams),
        tuple(payload["sys_path"]), observation.module_names,
    )


def validate_fixed_python_runtime_observation_policy(
    installation: profile.FixedPythonInstallation, observation: live.FixedPythonBoundLiveModules, *,
    image: bytes, runtime_main_source: bytes,
    expected_installation_sha256: str, expected_observation_sha256: str,
    producer_lifecycle: bool = False,
) -> FixedPythonRuntimeFacts:
    """Recheck an original retained snapshot against original image/source and pins.

    Full original module metadata comparison is repeated; a DTO label cannot
    bypass it. This pure comparison does not authenticate acquisition or image
    custody. Detached JSON and self-chosen identities carry no authority.
    """
    try:
        profile._digest(expected_observation_sha256)
        if (type(observation) is not live.FixedPythonBoundLiveModules
                or any(type(value) is not str for value in (
                    observation.installation_sha256, observation.observation_sha256,
                    observation.manifest_sha256,
                ))
                or any(type(value) is not int for value in (
                    observation.image_device, observation.image_inode, observation.target_pid,
                ))
                or type(observation.module_names) is not tuple
                or any(type(value) is not str for value in observation.module_names)
                or observation.installation_sha256 != expected_installation_sha256
                or observation.observation_sha256 != expected_observation_sha256
                or type(observation.canonical_bytes) is not bytes
                or not 0 < len(observation.canonical_bytes) <= live.MAX_FIXED_LIVE_MODULES_BYTES
                or hashlib.sha256(observation.canonical_bytes).hexdigest() != expected_observation_sha256
                or any(value is not False for value in (
                    observation.live_runtime_authenticated, observation.immutable_custody_verified,
                    observation.production_admission,
                ))):
            raise ValueError
        result = map_fixed_python_runtime_observation(
            installation, observation.canonical_bytes, image=image, runtime_main_source=runtime_main_source,
            expected_installation_sha256=expected_installation_sha256,
            expected_image_device=observation.image_device, expected_image_inode=observation.image_inode,
            expected_target_pid=observation.target_pid, expected_manifest_sha256=observation.manifest_sha256,
            producer_lifecycle=producer_lifecycle,
        )
        if result.live_modules_observation != observation:
            raise ValueError
        return result
    except (ValueError, TypeError, AttributeError, KeyError, IndexError, UnicodeError,
            OverflowError, RecursionError, StopIteration):
        pass
    raise FixedPythonRuntimeObservationError() from None


def map_fixed_python_runtime_observation(
    installation: profile.FixedPythonInstallation, raw: bytes, *, image: bytes,
    runtime_main_source: bytes, expected_installation_sha256: str, expected_image_device: int,
    expected_image_inode: int, expected_target_pid: int, expected_manifest_sha256: str,
    producer_lifecycle: bool = False,
) -> FixedPythonRuntimeFacts:
    """Compare expanded source/image/original owner and actual captured runtime facts."""
    try:
        if type(raw) is not bytes or not 0 < len(raw) <= live.MAX_FIXED_LIVE_MODULES_BYTES:
            raise ValueError
        observed = live.compare_fixed_python_bound_live_modules(
            installation, raw, image=image, runtime_main_source=runtime_main_source,
            expected_installation_sha256=expected_installation_sha256,
            expected_image_device=expected_image_device, expected_image_inode=expected_image_inode,
            expected_target_pid=expected_target_pid, expected_manifest_sha256=expected_manifest_sha256,
            runtime_observation=True, producer_lifecycle=producer_lifecycle,
        )
        installed = profile._reparse(installation, expected_installation_sha256)
        payload = profile._json(observed.canonical_bytes[:-1], live.MAX_FIXED_LIVE_MODULES_BYTES)
        return _runtime_facts(installed, observed, payload)
    except (ValueError, TypeError, AttributeError, UnicodeError, OverflowError, RecursionError):
        pass
    raise FixedPythonRuntimeObservationError() from None
