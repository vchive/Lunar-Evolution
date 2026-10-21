"""Detached RSI marker installation descriptions, never build or runtime authority.

The caller supplies independent comparison pins. Reviewed source descriptions
and generated-header records cannot establish source-to-object correspondence,
actual execution, input consumption or installation acceptance.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import NoReturn

from lunar_evolution.static_python_installation import (
    StaticPythonInstallationError,
    parse_static_python_installation_descriptor,
)

MAX_CONTRACT_BYTES = 384 * 1024
_MAX_NODES = 16384
_MAX_DEPTH = 16
_MAX_TEXT_BYTES = 256 * 1024
_MAX_INPUT_BYTES = 1024 * 1024 * 1024
_SCHEMA = "lunar-static-python-rsi-installation-contract-v1"
_PROFILE = "rsi-marker-launch-v1"
_FIELDS = frozenset({
    "schema", "profile", "base_reviewed_inputs", "reviewed_overlay", "source_plan",
    "launch_policy", "launcher", "descriptor", "claims",
})
_REVIEWED_INPUTS = {
    "base_reviewed_inputs": {
        "size": 80050,
        "sha256": "c305d56956b75eda286b0e630ceeeaa0f37db2e9f669879eb30a563f8dd2bb31",
    },
    "reviewed_overlay": {
        "size": 2456,
        "sha256": "31e8e064dc5317b3297140f55f07e81ca1aa9c831a4e4bbbf46cc76db0667b8f",
    },
    "source_plan": {
        "size": 6706,
        "sha256": "3399f2f7e8ef9b7c2d6c7ff60985992c0dff1444e463a971ad2560cdbda410ee",
    },
}
_LAUNCH_POLICY = {
    "argc": 3, "marker": "--lunar-rsi-input-v1", "marker_index": 1,
    "manifest_digest_index": 2, "manifest_digest_syntax": "[0-9a-f]{64}",
    "frozen_entrypoint": "_rsi_launch", "baseline_case": "baseline",
    "environment_selector": False, "input_reads": [],
}
_LAUNCHER_SOURCE = {
    "path": "tools/static_python_rsi_fixture/assets/launcher.c",
    "size": 1740,
    "sha256": "3a81211b2869727469c1de3bfad79144d11f17c99ccc100c3c48015c0398a0e0",
}
# Literal projections of the reviewed nine freeze tasks. Only the reviewed
# expanded main source substitutes the original base source. Runtime imports
# must never read preparation files as authority for this comparison.
_FROZEN_SOURCES = {
    "_frozen_importlib": (
        "Lib/importlib/_bootstrap.py", 57082,
        "b84488f731914f6da30607e10f6f8d4c5c2ff7f4b0e913060aa66999c04f6252",
        "generated-sources/Python/frozen_modules/importlib._bootstrap.h",
    ),
    "_frozen_importlib_external": (
        "Lib/importlib/_bootstrap_external.py", 64722,
        "2928843477aef234477ac1968447370798e933c6dad39b9e5131e581b8c84eab",
        "generated-sources/Python/frozen_modules/importlib._bootstrap_external.h",
    ),
    "_lunar_static_main": (
        "assets/frozen_main.py", 7227,
        "2b30f4463db471419df601a0c7640a560d2be95aed08d69cdf0e8e10d6871d28",
        "generated-sources/Python/frozen_modules/_lunar_static_main.h",
    ),
    "abc": (
        "Lib/abc.py", 6468,
        "a6684b1a49cfbc9c64caeeac7e55ef8f35052b8e8ca93a091941817cdc510b1c",
        "generated-sources/Python/frozen_modules/abc.h",
    ),
    "codecs": (
        "Lib/codecs.py", 36978,
        "2f278497548b8313580b247a1097a0a304e5087a355ebb11a92ec685fa9e63ff",
        "generated-sources/Python/frozen_modules/codecs.h",
    ),
    "encodings": (
        "Lib/encodings/__init__.py", 1101,
        "47a11d930321492bca552eed29dad061ed6739bf84c919485453315d911b1c60",
        "generated-sources/Python/frozen_modules/encodings.h",
    ),
    "encodings.aliases": (
        "Lib/encodings/aliases.py", 802,
        "43aadac378861c1bbdaaf04be8e1bb7d878529a7641ec123b5df4eccdd4c6106",
        "generated-sources/Python/frozen_modules/encodings.aliases.h",
    ),
    "encodings.utf_8": (
        "Lib/encodings/utf_8.py", 1005,
        "ba0cac060269583523ca9506473a755203037c57d466a11aa89a30a5f6756f3d",
        "generated-sources/Python/frozen_modules/encodings.utf_8.h",
    ),
    "io": (
        "Lib/io.py", 3582,
        "7cec3cb8ac004058dd0a5af246e6d950fb59c7ddd0058fda48bcb3fcb98d8822",
        "generated-sources/Python/frozen_modules/io.h",
    ),
}
_CLAIMS = frozenset({
    "configured_closure_verified", "compilation_performed", "freezer_performed",
    "runtime_execution_performed", "installation_accepted", "input_consumption_verified",
    "runtime_load_protection", "production_admission", "general_code_origin_protection",
})
_REASONS = frozenset({
    "invalid", "raw", "pin", "json", "duplicate_key", "structure", "canonical", "digest",
    "schema", "reviewed_inputs", "launch_policy", "launcher", "descriptor",
    "frozen_inventory", "main_header", "claims",
})


class StaticPythonRSIInstallationError(ValueError):
    """A bounded fixed reason without caller data or retained parser errors."""

    def __init__(self, reason: str) -> None:
        if type(reason) is not str or reason not in _REASONS:
            reason = "invalid"
        self.reason = "static_python_rsi_installation_" + reason
        super().__init__(self.reason)


class _Refusal(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _fail(reason: str) -> NoReturn:
    raise _Refusal(reason)


def _sha(value: object, reason: str = "digest") -> str:
    if (type(value) is not str or len(value) != 64
            or re.fullmatch(r"[0-9a-f]{64}", value) is None
            or value in ("0" * 64, "f" * 64)):
        _fail(reason)
    return value


def _preflight(raw: object, digests: tuple[object, ...], version: object) -> None:
    # Exact built-ins and all caller bounds precede parsing, hashing and delegation.
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_CONTRACT_BYTES:
        _fail("raw")
    if any(type(pin) is not str or len(pin) != 64 for pin in digests):
        _fail("pin")
    if type(version) is not str or not 1 <= len(version) <= 128:
        _fail("pin")
    for pin in digests:
        _sha(pin, "pin")
    if re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", version) is None:
        _fail("pin")


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            _fail("duplicate_key")
        result[key] = value
    return result


def _constant(_: str) -> NoReturn:
    _fail("json")


def _scan(value: object) -> None:
    nodes = text_size = 0
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if nodes > _MAX_NODES or depth > _MAX_DEPTH:
            _fail("structure")
        if type(item) is dict:
            pending.extend((child, depth + 1) for child in item.values())
            pending.extend((key, depth + 1) for key in item)
        elif type(item) is list:
            pending.extend((child, depth + 1) for child in item)
        elif type(item) is str:
            text_size += len(item.encode("utf-8"))
            if text_size > _MAX_TEXT_BYTES:
                _fail("structure")
        elif type(item) not in (int, bool):
            _fail("json")


def _object(value: object, fields: frozenset[str]) -> dict:
    if type(value) is not dict or set(value) != fields:
        _fail("schema")
    return value


def _same_typed(value: object, expected: object) -> bool:
    # In particular, JSON true cannot substitute for the integer argc/index/size.
    if type(value) is not type(expected):
        return False
    if type(expected) is dict:
        return set(value) == set(expected) and all(
            _same_typed(value[key], item) for key, item in expected.items()
        )
    if type(expected) is list:
        return len(value) == len(expected) and all(
            _same_typed(left, right) for left, right in zip(value, expected, strict=True)
        )
    return value == expected


def _file_record(value: object) -> dict:
    item = _object(value, frozenset({"path", "size", "sha256"}))
    if (type(item["size"]) is not int or not 0 < item["size"] <= _MAX_INPUT_BYTES):
        _fail("launcher")
    _sha(item["sha256"])
    return item


def _inventory(descriptor: dict, inventory_pin: str, main_header_pin: str) -> None:
    if descriptor["frozen_inventory_sha256"] != inventory_pin:
        _fail("frozen_inventory")
    # The unchanged embedded parser has already checked the exact nine modules,
    # their package/table identities, all generated sizes/digests and manifest hash.
    for item in descriptor["frozen_modules"]:
        path, size, digest, output = _FROZEN_SOURCES[item["name"]]
        if (not _same_typed(item["source"], {"path": path, "size": size, "sha256": digest})
                or item["generated"]["path"] != output):
            _fail("frozen_inventory")
        if (item["name"] == "_lunar_static_main"
                and item["generated"]["sha256"] != main_header_pin):
            _fail("main_header")


@dataclass(frozen=True, slots=True)
class StaticPythonRSIInstallationDescriptor:
    """Immutable comparison result; all described admission claims remain false."""

    canonical_bytes: bytes
    contract_sha256: str
    descriptor_sha256: str
    installation_version: str
    artifact_sha256: str
    frozen_inventory_sha256: str
    main_header_sha256: str

    def to_json(self) -> bytes:
        return self.canonical_bytes

    def to_dict(self) -> dict:
        return json.loads(self.canonical_bytes)


def parse_static_python_rsi_installation_descriptor(
    raw: bytes, *, expected_contract_sha256: str, expected_descriptor_sha256: str,
    expected_installation_version: str, expected_artifact_sha256: str,
    expected_frozen_inventory_sha256: str, expected_main_header_sha256: str,
) -> StaticPythonRSIInstallationDescriptor:
    """Compare a bounded canonical wire to six mandatory independent caller pins.

    This parser performs no filesystem, network, environment, process, builder or
    runtime operations. Complete descriptions still do not verify actual bytes.
    """
    reason = "invalid"
    try:
        _preflight(raw, (
            expected_contract_sha256, expected_descriptor_sha256, expected_artifact_sha256,
            expected_frozen_inventory_sha256, expected_main_header_sha256,
        ), expected_installation_version)
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                             parse_float=_constant, parse_constant=_constant)
        _scan(payload)
        top = _object(payload, _FIELDS)
        if top["schema"] != _SCHEMA or top["profile"] != _PROFILE:
            _fail("schema")
        if _canonical(top) != raw:
            _fail("canonical")
        contract_sha = hashlib.sha256(raw).hexdigest()
        if contract_sha != expected_contract_sha256:
            _fail("pin")
        if any(not _same_typed(top[key], record) for key, record in _REVIEWED_INPUTS.items()):
            _fail("reviewed_inputs")
        if not _same_typed(top["launch_policy"], _LAUNCH_POLICY):
            _fail("launch_policy")
        claims = _object(top["claims"], _CLAIMS)
        if any(value is not False for value in claims.values()):
            _fail("claims")
        launcher = _object(top["launcher"], frozenset({"source", "object"}))
        if not _same_typed(launcher["source"], _LAUNCHER_SOURCE):
            _fail("launcher")
        launcher_object = _file_record(launcher["object"])
        if launcher_object["path"] != "installation-owned-launcher.o":
            _fail("launcher")
        descriptor = top["descriptor"]
        embedded = parse_static_python_installation_descriptor(
            _canonical(descriptor), expected_descriptor_sha256=expected_descriptor_sha256,
            expected_installation_version=expected_installation_version,
            expected_artifact_sha256=expected_artifact_sha256,
        )
        if sum(_same_typed(record, launcher_object)
               for record in descriptor["recipe"]["link_inputs"]) != 1:
            _fail("launcher")
        _inventory(descriptor, expected_frozen_inventory_sha256, expected_main_header_sha256)
        return StaticPythonRSIInstallationDescriptor(
            raw, contract_sha, embedded.descriptor_sha256, embedded.installation_version,
            embedded.artifact_sha256, expected_frozen_inventory_sha256, expected_main_header_sha256,
        )
    except _Refusal as exc:
        reason = exc.reason
    except StaticPythonInstallationError:
        reason = "descriptor"
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, OverflowError):
        reason = "json"
    # Raise outside every parser handler. Suppression with `from None` inside a
    # handler still retains __context__, which could disclose malformed input.
    raise StaticPythonRSIInstallationError(reason)
