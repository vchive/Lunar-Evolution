"""Pure comparison of a bounded static-Python startup/import graph.

The input is caller-owned JSON. A valid result means only that the supplied
graph is canonical, pinned, and internally consistent with the fixed
installation profile. It does not establish that the graph is complete or
that CPython was built or started from it.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import deque
from dataclasses import dataclass
from typing import NoReturn

from lunar_evolution.static_python_installation import (
    MAX_DESCRIPTOR_BYTES,
    StaticPythonInstallationError,
    parse_static_python_installation_descriptor,
)

STARTUP_CLOSURE_SCHEMA = "lunar-static-python-startup-closure-v1"
MAX_STARTUP_CLOSURE_BYTES = 256 * 1024
_MAX_NODES = 8192
_MAX_DEPTH = 12
_MAX_TEXT_BYTES = 192 * 1024
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_LABEL = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}\Z")
_MODULE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*\Z")
_TOP_FIELDS = frozenset({
    "schema", "evidence_scope", "installation_version", "source_tree_sha256",
    "patch_set_sha256", "initialization_profile_sha256", "frozen_inventory_sha256",
    "builtin_inventory_sha256", "alias_inventory_sha256", "startup_roots", "modules",
    "import_edges", "unresolved_imports", "unsupported_import_sites", "claims",
})
_MODULE_FIELDS = frozenset({"name", "route", "target"})
_EDGE_FIELDS = frozenset({"source", "target", "kind"})
_CLAIMS = frozenset({
    "source_graph_verified", "configured_closure_verified", "build_performed",
    "runtime_startup_performed", "loader_policy_verified", "owner_verified",
    "installation_accepted", "runtime_load_protection", "general_code_origin_protection",
    "production_admission",
})
_ROUTES = frozenset({"frozen", "builtin", "alias", "interpreter-created"})
_EDGE_KINDS = frozenset({"import", "from-import", "literal-import", "bootstrap-alias"})
_REFUSALS = frozenset({
    "invalid", "raw", "descriptor", "pin", "json", "duplicate_key", "canonical",
    "schema", "bounds", "shape", "digest", "profile", "roots", "module", "route",
    "alias", "edge", "reachability", "unresolved", "unsupported", "claims",
})


class StaticPythonStartupClosureError(ValueError):
    """Fixed context-free refusal code for a caller-supplied startup graph."""

    def __init__(self, reason: str) -> None:
        if type(reason) is not str or reason not in _REFUSALS:
            reason = "invalid"
        self.reason = "static_python_startup_closure_" + reason
        super().__init__(self.reason)


class _Refusal(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _fail(reason: str) -> NoReturn:
    raise _Refusal(reason)


def _sha(value: object) -> str:
    if (type(value) is not str or len(value) != 64 or _SHA.fullmatch(value) is None
            or value in {"0" * 64, "f" * 64}):
        _fail("pin")
    return value


def _label(value: object) -> str:
    if type(value) is not str or _LABEL.fullmatch(value) is None:
        _fail("pin")
    return value


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, item in pairs:
        if key in result:
            _fail("duplicate_key")
        result[key] = item
    return result


def _constant(_: str) -> NoReturn:
    _fail("json")


def _scan(value: object) -> None:
    nodes = text_bytes = 0
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if nodes > _MAX_NODES or depth > _MAX_DEPTH:
            _fail("bounds")
        if type(item) is dict:
            pending.extend((key, depth + 1) for key in item)
            pending.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            pending.extend((child, depth + 1) for child in item)
        elif type(item) is str:
            try:
                size = len(item.encode("utf-8"))
            except UnicodeError:
                _fail("json")
            text_bytes += size
            if text_bytes > _MAX_TEXT_BYTES:
                _fail("bounds")
        elif type(item) not in (int, bool):
            _fail("json")


def _object(value: object, fields: frozenset[str], reason: str = "shape") -> dict:
    if type(value) is not dict or frozenset(value) != fields:
        _fail(reason)
    return value


def _module_name(value: object) -> str:
    if type(value) is not str or len(value) > 128 or _MODULE_NAME.fullmatch(value) is None:
        _fail("module")
    return value


def _same_typed(value: object, expected: object) -> bool:
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


def _validate_graph(value: dict, descriptor: dict) -> tuple[tuple[str, ...], tuple[str, ...], int]:
    if value["evidence_scope"] != "synthetic-dto-comparison-only":
        _fail("schema")
    expected_roots = descriptor["initialization_profile"]["expected_startup_modules"]
    roots = value["startup_roots"]
    if (type(roots) is not list or not 1 <= len(roots) <= 64
            or any(_module_name(name) != name for name in roots)
            or roots != sorted(set(roots))
            or not _same_typed(roots, expected_roots)):
        _fail("roots")

    frozen = {item["name"] for item in descriptor["frozen_modules"]}
    builtins = {item["name"] for item in descriptor["builtin_modules"]}
    aliases = {item["alias"]: item["name"] for item in descriptor["aliases"]}
    records = value["modules"]
    if type(records) is not list or not 1 <= len(records) <= 256:
        _fail("bounds")
    by_name: dict[str, dict] = {}
    ordered_names: list[str] = []
    for raw in records:
        item = _object(raw, _MODULE_FIELDS, "module")
        name = _module_name(item["name"])
        route, target = item["route"], item["target"]
        if type(route) is not str or route not in _ROUTES:
            _fail("route")
        if type(target) is not str:
            _fail("route")
        if name in by_name:
            _fail("module")
        if route == "frozen":
            if name not in frozen or target != "":
                _fail("route")
        elif route == "builtin":
            if name not in builtins or target != "":
                _fail("route")
        elif route == "alias":
            if aliases.get(name) != target:
                _fail("alias")
        elif name != "__main__" or target != "":
            _fail("route")
        by_name[name] = item
        ordered_names.append(name)
    if ordered_names != sorted(ordered_names):
        _fail("module")
    for name in roots:
        if name not in by_name:
            _fail("roots")
    for alias, target in aliases.items():
        if alias not in by_name:
            continue
        target_record = by_name.get(target)
        if target_record is None or target_record["route"] != "frozen":
            _fail("alias")

    edges = value["import_edges"]
    if type(edges) is not list or len(edges) > 2048:
        _fail("bounds")
    edge_keys: list[tuple[str, str, str]] = []
    adjacency: dict[str, list[str]] = {name: [] for name in by_name}
    alias_targets: set[str] = set()
    for raw in edges:
        edge = _object(raw, _EDGE_FIELDS, "edge")
        source = _module_name(edge["source"])
        target = _module_name(edge["target"])
        kind = edge["kind"]
        if type(kind) is not str or kind not in _EDGE_KINDS:
            _fail("edge")
        if source not in by_name or target not in by_name:
            _fail("edge")
        if kind == "bootstrap-alias":
            target_record = by_name[target]
            source_record = by_name[source]
            canonical_name = target_record["target"]
            if (target_record["route"] != "alias"
                    or aliases.get(target) != canonical_name
                    or source != canonical_name
                    or source_record["route"] != "frozen"):
                _fail("alias")
            alias_targets.add(target)
        elif by_name[target]["route"] == "alias":
            _fail("alias")
        edge_keys.append((source, target, kind))
        adjacency[source].append(target)
    if edge_keys != sorted(set(edge_keys)):
        _fail("edge")
    if any(name not in alias_targets for name, item in by_name.items() if item["route"] == "alias"):
        _fail("alias")

    reachable = set(roots)
    pending = deque(roots)
    while pending:
        source = pending.popleft()
        for target in adjacency[source]:
            if target not in reachable:
                reachable.add(target)
                pending.append(target)
    if reachable != set(by_name) or any(source not in reachable for source, _, _ in edge_keys):
        _fail("reachability")

    for name in ("unresolved_imports", "unsupported_import_sites"):
        values = value[name]
        if type(values) is not list or len(values) > 256:
            _fail("bounds")
        if values:
            _fail("unresolved" if name == "unresolved_imports" else "unsupported")
    claims = _object(value["claims"], _CLAIMS, "claims")
    if any(type(claim) is not bool or claim is not False for claim in claims.values()):
        _fail("claims")
    return tuple(roots), tuple(ordered_names), len(edges)


@dataclass(frozen=True, slots=True)
class StaticPythonStartupClosure:
    """Detached comparison result; it carries no source or runtime authority."""

    canonical_bytes: bytes
    closure_sha256: str
    descriptor_sha256: str
    installation_version: str
    source_tree_sha256: str
    frozen_inventory_sha256: str
    builtin_inventory_sha256: str
    alias_inventory_sha256: str
    startup_roots: tuple[str, ...]
    module_names: tuple[str, ...]
    import_edge_count: int

    def to_json(self) -> bytes:
        return self.canonical_bytes

    def to_dict(self) -> dict:
        return json.loads(self.canonical_bytes)


def parse_static_python_startup_closure(
    raw: bytes, *, installation_descriptor_raw: bytes, expected_closure_sha256: str,
    expected_installation_descriptor_sha256: str, expected_installation_version: str,
    expected_artifact_sha256: str, expected_source_tree_sha256: str,
    expected_patch_set_sha256: str, expected_initialization_profile_sha256: str,
    expected_frozen_inventory_sha256: str, expected_builtin_inventory_sha256: str,
    expected_alias_inventory_sha256: str,
) -> StaticPythonStartupClosure:
    """Check one canonical pinned graph and its existing installation contract.

    The caller supplies every digest independently. This function reads no path,
    environment, network, process, compiler, freezer, ELF image or Python runtime.
    """
    reason = "invalid"
    try:
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_STARTUP_CLOSURE_BYTES:
            _fail("raw")
        if (type(installation_descriptor_raw) is not bytes
                or not 0 < len(installation_descriptor_raw) <= MAX_DESCRIPTOR_BYTES):
            _fail("descriptor")
        pins = {
            "expected_closure_sha256": expected_closure_sha256,
            "expected_installation_descriptor_sha256": expected_installation_descriptor_sha256,
            "expected_artifact_sha256": expected_artifact_sha256,
            "expected_source_tree_sha256": expected_source_tree_sha256,
            "expected_patch_set_sha256": expected_patch_set_sha256,
            "expected_initialization_profile_sha256": expected_initialization_profile_sha256,
            "expected_frozen_inventory_sha256": expected_frozen_inventory_sha256,
            "expected_builtin_inventory_sha256": expected_builtin_inventory_sha256,
            "expected_alias_inventory_sha256": expected_alias_inventory_sha256,
        }
        for pin in pins.values():
            _sha(pin)
        version = _label(expected_installation_version)

        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                             parse_float=_constant, parse_constant=_constant)
        _scan(payload)
        value = _object(payload, _TOP_FIELDS)
        if value["schema"] != STARTUP_CLOSURE_SCHEMA:
            _fail("schema")
        canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                               allow_nan=False).encode("utf-8")
        if canonical != raw:
            _fail("canonical")
        closure_sha = hashlib.sha256(raw).hexdigest()
        if closure_sha != expected_closure_sha256:
            _fail("pin")
        descriptor = parse_static_python_installation_descriptor(
            installation_descriptor_raw,
            expected_descriptor_sha256=expected_installation_descriptor_sha256,
            expected_installation_version=version,
            expected_artifact_sha256=expected_artifact_sha256,
        ).to_dict()

        descriptor_fields = {
            "installation_version": version,
            "source_tree_sha256": expected_source_tree_sha256,
            "patch_set_sha256": expected_patch_set_sha256,
            "initialization_profile_sha256": expected_initialization_profile_sha256,
            "frozen_inventory_sha256": expected_frozen_inventory_sha256,
            "builtin_inventory_sha256": expected_builtin_inventory_sha256,
            "alias_inventory_sha256": expected_alias_inventory_sha256,
        }
        if any(not _same_typed(descriptor.get(key), expected)
               for key, expected in descriptor_fields.items()):
            _fail("profile")
        for name, expected in descriptor_fields.items():
            if not _same_typed(value.get(name), expected):
                _fail("profile")
        roots, modules, edge_count = _validate_graph(value, descriptor)
        return StaticPythonStartupClosure(
            canonical, closure_sha, expected_installation_descriptor_sha256, version,
            expected_source_tree_sha256, expected_frozen_inventory_sha256,
            expected_builtin_inventory_sha256, expected_alias_inventory_sha256,
            roots, modules, edge_count,
        )
    except _Refusal as exc:
        reason = exc.reason
    except StaticPythonInstallationError:
        reason = "descriptor"
    except (UnicodeError, ValueError, TypeError, KeyError, RecursionError, OverflowError):
        reason = "json"
    # Raise outside the handlers so arbitrary parse exceptions are not retained.
    raise StaticPythonStartupClosureError(reason)


__all__ = [
    "MAX_STARTUP_CLOSURE_BYTES", "STARTUP_CLOSURE_SCHEMA", "StaticPythonStartupClosure",
    "StaticPythonStartupClosureError", "parse_static_python_startup_closure",
]
