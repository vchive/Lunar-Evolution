"""Provider-free adapter for the sealed static-Python fixture observation.

The static fixture emits a deliberately small JSON record.  This module is the
boundary between those bytes and Feature191's runtime-observation DTO.  It does
not start Python, inspect a host installation, discover imports, or turn any
fixture claim into a production-admission claim.  The caller must provide the
raw broker transcript and the independent ``pycache_absent`` observation; this
keeps those facts tied to bytes observed by the fixture rather than inferred
from the descriptor.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any, NoReturn

from .python_producer_lifecycle import (
    PythonProducerLifecycleError,
    PythonProducerRuntimeObservation,
    build_python_producer_runtime_observation,
)

STATIC_PYTHON_OBSERVATION_SCHEMA = "lunar-static-python-observation-v1"
MAX_STATIC_PYTHON_OBSERVATION_BYTES = 256 * 1024
MAX_STATIC_PYTHON_BROKER_BYTES = 64 * 1024

_SHA = re.compile(r"^[0-9a-f]{64}$")
_FLAGS = frozenset({
    "isolated", "ignore_environment", "no_site", "no_user_site", "utf8_mode",
    "dont_write_bytecode", "safe_path", "dev_mode", "optimize", "hash_randomization",
})
_RAW_FIELDS = frozenset({
    "schema", "fixture_case", "computed", "version_info", "cache_tag", "flags", "origins",
    "builtin_names", "frozen_names", "sys_path", "executable", "prefix", "base_prefix",
    "exec_prefix", "base_exec_prefix", "stdlib_dir", "argv", "orig_argv",
    "filesystem_encoding", "filesystem_errors", "stdio_encoding", "stdio_errors",
    "stderr_errors", "loader_negative", "broker_response_bytes", "runtime_load_protection",
    "production_admission", "general_code_origin_protection",
})
_NEGATIVE_FIELDS = frozenset({"direct", "ordinary"})
_SAFE_ORIGINS = frozenset({None, "built-in", "frozen"})
_PATH_FIELDS = frozenset({"executable", "prefix", "base_prefix", "exec_prefix", "base_exec_prefix", "stdlib_dir"})
_EXPECTED_PATH = "/lunar-static-python-fixture"
_BROKER_PROTOCOL = b'"protocol":"lunar-producer-broker-ipc-v1"'


class PythonFixtureObservationError(PythonProducerLifecycleError):
    """Fixed refusal code for an untrusted static-fixture observation."""

    def __init__(self, code: str) -> None:
        super().__init__("fixture_observation_" + code)


def _fail(code: str) -> NoReturn:
    raise PythonFixtureObservationError(code)


def _canonical(value: object) -> bytes:
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        raise PythonFixtureObservationError("json_invalid") from exc
    if len(raw) > MAX_STATIC_PYTHON_OBSERVATION_BYTES:
        _fail("record_too_large")
    return raw


def _strict_json(value: bytes | str) -> dict[str, Any]:
    if type(value) not in {bytes, str}:
        _fail("json_invalid")
    raw = value if type(value) is bytes else value.encode("utf-8")
    if len(raw) > MAX_STATIC_PYTHON_OBSERVATION_BYTES:
        _fail("record_too_large")

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in items:
            if key in result:
                _fail("duplicate_json_key")
            result[key] = item
        return result

    try:
        parsed = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                            parse_constant=lambda _: _fail("json_invalid"))
    except PythonFixtureObservationError:
        raise
    except (UnicodeDecodeError, TypeError, ValueError, RecursionError) as exc:
        raise PythonFixtureObservationError("json_invalid") from exc
    if type(parsed) is not dict or set(parsed) != _RAW_FIELDS:
        _fail("schema_invalid")
    if _canonical(parsed) != raw:
        _fail("noncanonical_json")
    return parsed


def _sha(value: object, code: str = "digest_invalid") -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        _fail(code)
    return value


def _text(value: object, code: str = "text_invalid", *, empty: bool = False) -> str:
    if type(value) is not str or (not empty and not value) or len(value.encode("utf-8")) > 4096:
        _fail(code)
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        _fail(code)
    return value


def _strings(value: object, code: str, *, exact: tuple[str, ...] | None = None) -> tuple[str, ...]:
    if type(value) is not list or len(value) > 256 or any(type(item) is not str for item in value):
        _fail(code)
    result = tuple(_text(item, code) for item in value)
    if exact is not None and result != exact:
        _fail(code)
    return result


def _validate_negative(value: object) -> None:
    if type(value) is not dict or set(value) != _NEGATIVE_FIELDS:
        _fail("loader_negative_schema")
    direct, ordinary = value["direct"], value["ordinary"]
    if (type(direct) is not list or len(direct) != 8 or any(type(item) is not bool for item in direct)
            or type(ordinary) is not list or len(ordinary) != 7
            or any(type(item) is not bool for item in ordinary)
            or not all(direct) or not all(ordinary)):
        _fail("loader_negative_failed")


def _validate_origins(value: object) -> tuple[str, ...]:
    if type(value) is not dict or not value or len(value) > 256:
        _fail("origins_invalid")
    names = tuple(sorted(value))
    for name in names:
        _text(name, "origin_name_invalid")
        item = value[name]
        if type(item) is not dict or set(item) != {"origin", "file"}:
            _fail("origin_record_invalid")
        if (item["origin"] is not None and type(item["origin"]) is not str) or (
            item["origin"] not in _SAFE_ORIGINS
        ) or item["file"] is not None:
            _fail("origin_external")
    return names


def adapt_static_python_observation(
    value: bytes | str | Mapping[str, object],
    *,
    binding_sha256: str,
    broker_transcript: bytes,
    pycache_absent: bool,
    abi_profile: str = "cp313-static-fixture",
) -> PythonProducerRuntimeObservation:
    """Validate one fixture record and project it into Feature191's DTO.

    ``broker_transcript`` and ``pycache_absent`` are intentionally separate
    inputs.  The static fixture's stdout record is not allowed to self-attest
    either fact.  This helper remains provider-free and has no filesystem or
    subprocess effects.
    """
    if isinstance(value, Mapping):
        if type(value) is not dict:
            _fail("json_invalid")
        raw = dict(value)
        if set(raw) != _RAW_FIELDS:
            _fail("schema_invalid")
    else:
        raw = _strict_json(value)
    _sha(binding_sha256, "binding_invalid")
    if type(pycache_absent) is not bool or not pycache_absent:
        _fail("pycache_missing")
    if type(broker_transcript) is not bytes or not 1 <= len(broker_transcript) <= MAX_STATIC_PYTHON_BROKER_BYTES:
        _fail("broker_transcript_invalid")
    if (not broker_transcript.endswith(b"\n") or _BROKER_PROTOCOL not in broker_transcript
            or b'"request_id":"req-1"' not in broker_transcript
            or b'"status":"completed"' not in broker_transcript
            or raw["broker_response_bytes"] != len(broker_transcript)):
        _fail("broker_transcript_mismatch")
    if raw["schema"] != STATIC_PYTHON_OBSERVATION_SCHEMA:
        _fail("schema_invalid")
    if raw["fixture_case"] not in {"baseline", "loader-negative"} or raw["computed"] != 285:
        _fail("fixture_result_invalid")
    version = raw["version_info"]
    if (type(version) is not list or len(version) < 3
            or any(type(item) is not int or isinstance(item, bool) for item in version[:3])
            or tuple(version[:2]) != (3, 13) or version[2] < 1):
        _fail("version_invalid")
    if raw["cache_tag"] != "cpython-313":
        _fail("cache_tag_invalid")
    flags = raw["flags"]
    if type(flags) is not dict or set(flags) != _FLAGS or any(type(item) is not int or item not in {0, 1} for item in flags.values()):
        _fail("flags_invalid")
    expected_flags = {"isolated": 1, "ignore_environment": 1, "no_site": 1, "no_user_site": 1,
                      "utf8_mode": 1, "dont_write_bytecode": 1, "safe_path": 1,
                      "dev_mode": 0, "optimize": 0, "hash_randomization": 0}
    if flags != expected_flags:
        _fail("flags_policy_invalid")
    for field in _PATH_FIELDS:
        if raw[field] != _EXPECTED_PATH:
            _fail("path_identity_invalid")
    argv = _strings(raw["argv"], "argv_invalid", exact=("lunar-static-python-fixture",))
    orig_argv = _strings(raw["orig_argv"], "orig_argv_invalid", exact=argv)
    if raw["sys_path"] != []:
        _fail("sys_path_external")
    modules = _validate_origins(raw["origins"])
    builtin_names = _strings(raw["builtin_names"], "builtin_inventory_invalid")
    frozen_names = _strings(raw["frozen_names"], "frozen_inventory_invalid")
    if (builtin_names != tuple(sorted(set(builtin_names)))
            or frozen_names != tuple(sorted(set(frozen_names)))
            or set(builtin_names) & set(frozen_names)
            or not (set(builtin_names) | set(frozen_names)) <= set(modules)):
        _fail("module_inventory_drift")
    negative = raw["loader_negative"]
    if raw["fixture_case"] == "loader-negative":
        _validate_negative(negative)
    elif negative is not None:
        _fail("baseline_negative_present")
    for field in ("filesystem_encoding", "filesystem_errors", "stdio_encoding", "stdio_errors", "stderr_errors"):
        _text(raw[field], field + "_invalid")
    if (raw["filesystem_encoding"], raw["filesystem_errors"], raw["stdio_encoding"], raw["stdio_errors"], raw["stderr_errors"]) != (
        "utf-8", "surrogateescape", "utf-8", "strict", "strict",
    ):
        _fail("encoding_policy_invalid")
    for field in ("runtime_load_protection", "production_admission", "general_code_origin_protection"):
        if raw[field] is not False:
            _fail("unsupported_protection_claim")
    if type(raw["broker_response_bytes"]) is not int or not 1 <= raw["broker_response_bytes"] <= MAX_STATIC_PYTHON_BROKER_BYTES:
        _fail("broker_response_size_invalid")
    flags_wire = tuple(f"{name}={flags[name]}" for name in sorted(flags))
    return build_python_producer_runtime_observation(
        binding_sha256=binding_sha256,
        execution_performed=True,
        version_major=version[0], version_minor=version[1], version_micro=version[2],
        cache_tag=raw["cache_tag"], abi_profile=_text(abi_profile, "abi_profile_invalid"),
        argv=argv, orig_argv=orig_argv, flags=flags_wire,
        filesystem_encoding=raw["filesystem_encoding"], filesystem_errors=raw["filesystem_errors"],
        stdio_encoding=raw["stdio_encoding"], stdio_errors=raw["stdio_errors"], sys_path=(),
        startup_modules=modules,
        broker_transcript_sha256=hashlib.sha256(broker_transcript).hexdigest(),
        pycache_absent=pycache_absent,
        computation_sha256=hashlib.sha256(b"285").hexdigest(),
    )


__all__ = ["PythonFixtureObservationError", "adapt_static_python_observation"]
