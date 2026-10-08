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

from .producer_broker_ipc import ProducerBrokerIpcError, _body, _decode
from .python_producer_lifecycle import (
    PythonProducerLifecycleError,
    PythonProducerRuntimeObservation,
    build_python_producer_runtime_observation,
)
from .static_python_installation import (
    STATIC_PYTHON_BUILTIN_NAMES,
    STATIC_PYTHON_FROZEN_NAMES,
    STATIC_PYTHON_STARTUP_MODULES,
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
_EXPECTED_PATHS = {
    "executable": "/lunar-static-python-fixture",
    **{name: "/lunar-static-fixture" for name in (
        "prefix", "base_prefix", "exec_prefix", "base_exec_prefix", "stdlib_dir",
    )},
}


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


def _exact_object(value: object, fields: frozenset[str], code: str) -> dict[str, Any]:
    # Exact builtins only: never invoke a mapping subclass, iterator, arbitrary
    # key hash/equality, or a user-defined value serializer at this boundary.
    if (type(value) is not dict or len(value) != len(fields)
            or any(type(key) is not str or len(key) > 64 for key in value)
            or set(value) != fields):
        _fail(code)
    return value


def _shape(value: object) -> dict[str, Any]:
    """Cheap finite recursive shape gate before any canonicalization."""
    raw = _exact_object(value, _RAW_FIELDS, "schema_invalid")
    strings = _RAW_FIELDS - {
        "computed", "version_info", "flags", "origins", "builtin_names", "frozen_names",
        "sys_path", "argv", "orig_argv", "loader_negative", "broker_response_bytes",
        "runtime_load_protection", "production_admission", "general_code_origin_protection",
    }
    text_chars = 0
    for name in strings:
        if type(raw[name]) is not str or len(raw[name]) > 4096:
            _fail("schema_invalid")
        text_chars += len(raw[name])
    for name in ("computed", "broker_response_bytes"):
        if type(raw[name]) is not int or not 0 <= raw[name] <= MAX_STATIC_PYTHON_BROKER_BYTES:
            _fail("fixture_result_invalid" if name == "computed" else "broker_response_size_invalid")
    for name in ("runtime_load_protection", "production_admission", "general_code_origin_protection"):
        if type(raw[name]) is not bool:
            _fail("unsupported_protection_claim")
    version = raw["version_info"]
    if (type(version) is not list or len(version) != 5
            or any(type(version[index]) is not int for index in (0, 1, 2, 4))
            or any(not 0 <= version[index] <= 999 for index in (0, 1, 2, 4))
            or type(version[3]) is not str or len(version[3]) > 16):
        _fail("version_invalid")
    flags = _exact_object(raw["flags"], _FLAGS, "flags_invalid")
    for name, item in flags.items():
        if type(item) is not (bool if name in {"safe_path", "dev_mode"} else int) or item not in {0, 1}:
            _fail("flags_invalid")
    for name in ("builtin_names", "frozen_names", "sys_path", "argv", "orig_argv"):
        vector = raw[name]
        if (type(vector) is not list or len(vector) > 256
                or any(type(item) is not str or len(item) > 4096 for item in vector)):
            _fail("schema_invalid")
        text_chars += sum(len(item) for item in vector)
    origins = raw["origins"]
    if (type(origins) is not dict or len(origins) != len(STATIC_PYTHON_STARTUP_MODULES)
            or any(type(key) is not str or len(key) > 128 for key in origins)):
        _fail("module_inventory_drift")
    for item in origins.values():
        origin = _exact_object(item, frozenset({"origin", "file"}), "origin_record_invalid")
        if (origin["origin"] is not None and type(origin["origin"]) is not str
                or origin["origin"] is not None and len(origin["origin"]) > 16
                or origin["file"] is not None):
            _fail("origin_external")
    negative = raw["loader_negative"]
    if negative is not None:
        _validate_negative(negative)
    if text_chars > MAX_STATIC_PYTHON_OBSERVATION_BYTES:
        _fail("record_too_large")
    # Every child is now an exact bounded builtin, so encoding is safe. The
    # byte limit also applies to the direct-dict form of the detached contract.
    _canonical(raw)
    return raw


def _strict_json(value: bytes | str) -> dict[str, Any]:
    if type(value) not in {bytes, str}:
        _fail("json_invalid")
    try:
        raw = value if type(value) is bytes else value.encode("utf-8")
    except UnicodeError as exc:
        raise PythonFixtureObservationError("json_invalid") from exc
    if len(raw) > MAX_STATIC_PYTHON_OBSERVATION_BYTES:
        _fail("record_too_large")
    # frozen_main writes exactly one terminal newline. The JSON bytes may also
    # be supplied without the stream delimiter for detached DTO construction.
    if raw.endswith(b"\n"):
        raw = raw[:-1]

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
    parsed = _shape(parsed)
    if _canonical(parsed) != raw:
        _fail("noncanonical_json")
    return parsed


def _sha(value: object, code: str = "digest_invalid") -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None or value == "0" * 64:
        _fail(code)
    return value


def _text(value: object, code: str = "text_invalid", *, empty: bool = False) -> str:
    if type(value) is not str or (not empty and not value) or len(value) > 4096:
        _fail(code)
    try:
        if len(value.encode("utf-8")) > 4096:
            _fail(code)
    except UnicodeError as exc:
        raise PythonFixtureObservationError(code) from exc
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
    value = _exact_object(value, _NEGATIVE_FIELDS, "loader_negative_schema")
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
        expected = None if name == "__main__" else "built-in" if name in STATIC_PYTHON_BUILTIN_NAMES else "frozen"
        if item["origin"] != expected or item["file"] is not None:
            _fail("origin_external")
    return names


def _validate_broker_transcript(value: object, response_bytes: object) -> bytes:
    if type(value) is not bytes or not 1 <= len(value) <= MAX_STATIC_PYTHON_BROKER_BYTES:
        _fail("broker_transcript_invalid")
    if value.count(b"\n") != 1 or not value.endswith(b"\n"):
        _fail("broker_transcript_mismatch")
    if type(response_bytes) is not int or response_bytes != len(value):
        _fail("broker_transcript_mismatch")
    try:
        response = _decode(value, limit=MAX_STATIC_PYTHON_BROKER_BYTES)
        if (set(response) != {"protocol", "request_id", "status", "http_status", "body_base64"}
                or response["protocol"] != "lunar-producer-broker-ipc-v1"
                or response["request_id"] != "req-1" or response["status"] != "completed"
                or type(response["http_status"]) is not int
                or not 100 <= response["http_status"] <= 599):
            _fail("broker_transcript_mismatch")
        _body(response["body_base64"], maximum=MAX_STATIC_PYTHON_BROKER_BYTES)
    except ProducerBrokerIpcError as exc:
        raise PythonFixtureObservationError("broker_transcript_mismatch") from exc
    return value


def adapt_static_python_observation(
    value: bytes | str | Mapping[str, object],
    *,
    binding_sha256: str,
    broker_transcript: bytes,
    pycache_absent: bool,
    abi_profile: str = "cp313-release-gil",
) -> PythonProducerRuntimeObservation:
    """Validate one fixture record and project it into Feature191's DTO.

    ``broker_transcript`` and ``pycache_absent`` are intentionally separate
    inputs.  The static fixture's stdout record is not allowed to self-attest
    either fact.  This helper remains provider-free and has no filesystem or
    subprocess effects.
    """
    if type(value) is dict:
        raw = _shape(value)
    else:
        raw = _strict_json(value)
    _sha(binding_sha256, "binding_invalid")
    if type(pycache_absent) is not bool or not pycache_absent:
        _fail("pycache_missing")
    broker_transcript = _validate_broker_transcript(broker_transcript, raw["broker_response_bytes"])
    if raw["schema"] != STATIC_PYTHON_OBSERVATION_SCHEMA:
        _fail("schema_invalid")
    if raw["fixture_case"] not in {"baseline", "loader-negative"} or raw["computed"] != 285:
        _fail("fixture_result_invalid")
    version = raw["version_info"]
    if (type(version) is not list or len(version) != 5
            or any(type(version[index]) is not int for index in (0, 1, 2, 4))
            or type(version[3]) is not str or version != [3, 13, 12, "final", 0]):
        _fail("version_invalid")
    if raw["cache_tag"] != "cpython-313":
        _fail("cache_tag_invalid")
    flags = raw["flags"]
    if (type(flags) is not dict or set(flags) != _FLAGS
            or any(type(item) is not (bool if name in {"safe_path", "dev_mode"} else int)
                   or item not in {0, 1} for name, item in flags.items())):
        _fail("flags_invalid")
    expected_flags = {"isolated": 1, "ignore_environment": 1, "no_site": 1, "no_user_site": 1,
                      "utf8_mode": 1, "dont_write_bytecode": 1, "safe_path": True,
                      "dev_mode": False, "optimize": 0, "hash_randomization": 0}
    if flags != expected_flags:
        _fail("flags_policy_invalid")
    for field, expected in _EXPECTED_PATHS.items():
        if raw[field] != expected:
            _fail("path_identity_invalid")
    argv = _strings(raw["argv"], "argv_invalid", exact=("lunar-static-python-fixture",))
    orig_argv = _strings(raw["orig_argv"], "orig_argv_invalid", exact=argv)
    if raw["sys_path"] != []:
        _fail("sys_path_external")
    modules = _validate_origins(raw["origins"])
    builtin_names = _strings(raw["builtin_names"], "builtin_inventory_invalid")
    frozen_names = _strings(raw["frozen_names"], "frozen_inventory_invalid")
    if (builtin_names != STATIC_PYTHON_BUILTIN_NAMES
            or frozen_names != STATIC_PYTHON_FROZEN_NAMES
            or modules != STATIC_PYTHON_STARTUP_MODULES):
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
    abi_profile = _text(abi_profile, "abi_profile_invalid")
    if abi_profile != "cp313-release-gil":
        _fail("abi_profile_invalid")
    flags_wire = tuple(f"{name}={int(flags[name])}" for name in sorted(flags))
    return build_python_producer_runtime_observation(
        binding_sha256=binding_sha256,
        execution_performed=True,
        version_major=version[0], version_minor=version[1], version_micro=version[2],
        cache_tag=raw["cache_tag"], abi_profile=abi_profile,
        argv=argv, orig_argv=orig_argv, flags=flags_wire,
        filesystem_encoding=raw["filesystem_encoding"], filesystem_errors=raw["filesystem_errors"],
        stdio_encoding=raw["stdio_encoding"], stdio_errors=raw["stdio_errors"], sys_path=(),
        startup_modules=modules,
        broker_transcript_sha256=hashlib.sha256(broker_transcript).hexdigest(),
        pycache_absent=pycache_absent,
        computation_sha256=hashlib.sha256(b"285").hexdigest(),
    )


__all__ = ["PythonFixtureObservationError", "adapt_static_python_observation"]
