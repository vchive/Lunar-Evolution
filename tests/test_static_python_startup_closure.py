"""Synthetic startup-closure DTO checks; no build or runtime acceptance."""

from __future__ import annotations

import builtins
import copy
import hashlib
import json
import os
import socket
import subprocess
import urllib.request
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from lunar_evolution import static_python_startup_closure as startup_closure

_ROOT = Path(__file__).resolve().parents[1]
_WIRE = _ROOT / "specs/189-static-python-fixture/wire-v1-example.json"
_SOURCE_ROOTS = _ROOT / "specs/189-static-python-fixture/startup-roots-cpython-3.13.12.json"
_STARTUP_SCOPE_GRAPH = _ROOT / (
    "specs/189-static-python-fixture/startup-scope-graph-cpython-3.13.12-v1.json"
)
_SOURCE_ROOTS_SHA256 = "d1743e729bac34c5110a1d1373cc48c74a52b585034825227ed37d0178e39313"
_SCHEMA = "lunar-static-python-startup-closure-v2"
_CLAIMS = (
    "source_graph_verified",
    "configured_closure_verified",
    "build_performed",
    "runtime_startup_performed",
    "loader_policy_verified",
    "owner_verified",
    "installation_accepted",
    "runtime_load_protection",
    "general_code_origin_protection",
    "production_admission",
)
_PIN_NAMES = (
    "expected_closure_sha256",
    "expected_startup_roots_sha256",
    "expected_installation_descriptor_sha256",
    "expected_installation_version",
    "expected_artifact_sha256",
    "expected_source_tree_sha256",
    "expected_patch_set_sha256",
    "expected_initialization_profile_sha256",
    "expected_frozen_inventory_sha256",
    "expected_builtin_inventory_sha256",
    "expected_alias_inventory_sha256",
)
_ORDINARY_KINDS = ("import", "from-import", "literal-import")


def _encode(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture(scope="module")
def f01() -> dict:
    """The checked-in synthetic F01 installation descriptor fixture."""
    example = json.loads(_WIRE.read_bytes())
    assert example["kind"] == "synthetic-parser-and-ELF-format-only-never-executed"
    return example["descriptor"]


@pytest.fixture(scope="module")
def descriptor_raw(f01: dict) -> bytes:
    # The descriptor bytes are independently canonicalized from the fixture;
    # no parser helper or parsed DTO supplies any of the pins below.
    return _encode(f01)


def _payload(f01: dict) -> dict:
    descriptor = f01
    expected_modules = list(descriptor["initialization_profile"]["expected_startup_modules"])
    # Synthetic entry roots are deliberately separate from the expected module
    # inventory. The real roots remain an independent source-audit input.
    roots = ["_lunar_static_main"]
    frozen_names = {record["name"] for record in descriptor["frozen_modules"]}
    builtin_names = {record["name"] for record in descriptor["builtin_modules"]}
    aliases = descriptor["aliases"]

    modules = []
    for name in expected_modules:
        if name == "__main__":
            modules.append({"name": name, "route": "interpreter-created", "target": ""})
        elif name in frozen_names:
            modules.append({"name": name, "route": "frozen", "target": ""})
        else:
            assert name in builtin_names
            modules.append({"name": name, "route": "builtin", "target": ""})
    modules.extend(
        {"name": alias["alias"], "route": "alias", "target": alias["name"]}
        for alias in aliases
    )
    modules.sort(key=lambda item: item["name"])

    # Each alias node is reached from its fixed frozen startup module. Its
    # route target records the canonical frozen module, so no inferred module
    # names or source imports are introduced by this synthetic graph.
    edges = [
        {"source": alias["name"], "target": alias["alias"], "kind": "bootstrap-alias"}
        for alias in aliases
    ]
    # This is an artificial connected graph for parser tests, not the observed
    # CPython startup graph. A star from the one synthetic root makes missing
    # edge and disconnected-node refusals independently testable.
    edges.extend(
        {"source": roots[0], "target": name, "kind": "import"}
        for name in expected_modules if name != roots[0]
    )
    edges.sort(key=lambda item: (item["source"], item["target"], item["kind"]))

    payload = {
        "schema": _SCHEMA,
        "evidence_scope": "synthetic-dto-comparison-only",
        "installation_version": descriptor["installation_version"],
        "source_tree_sha256": descriptor["source_tree_sha256"],
        "patch_set_sha256": descriptor["patch_set_sha256"],
        "initialization_profile_sha256": descriptor["initialization_profile_sha256"],
        "frozen_inventory_sha256": descriptor["frozen_inventory_sha256"],
        "builtin_inventory_sha256": descriptor["builtin_inventory_sha256"],
        "alias_inventory_sha256": descriptor["alias_inventory_sha256"],
        "expected_startup_modules": expected_modules,
        "startup_roots": roots,
        "modules": modules,
        "import_edges": edges,
        "unresolved_imports": [],
        "unsupported_import_sites": [],
        "claims": dict.fromkeys(_CLAIMS, False),
    }
    assert roots == sorted(set(roots))
    return payload


@pytest.fixture
def vector(f01: dict) -> dict:
    return _payload(f01)


def _pins(payload: dict, f01: dict, descriptor_raw: bytes, raw: bytes | None = None) -> dict:
    return {
        "expected_closure_sha256": _sha(_encode(payload) if raw is None else raw),
        "expected_startup_roots_sha256": _sha(_encode(payload.get("startup_roots", []))),
        "expected_installation_descriptor_sha256": _sha(descriptor_raw),
        "expected_installation_version": f01["installation_version"],
        "expected_artifact_sha256": f01["artifact_sha256"],
        "expected_source_tree_sha256": f01["source_tree_sha256"],
        "expected_patch_set_sha256": f01["patch_set_sha256"],
        "expected_initialization_profile_sha256": f01["initialization_profile_sha256"],
        "expected_frozen_inventory_sha256": f01["frozen_inventory_sha256"],
        "expected_builtin_inventory_sha256": f01["builtin_inventory_sha256"],
        "expected_alias_inventory_sha256": f01["alias_inventory_sha256"],
    }


def _parse(payload: dict, f01: dict, descriptor_raw: bytes, *, raw: bytes | None = None, **overrides):
    encoded = _encode(payload) if raw is None else raw
    pins = _pins(payload, f01, descriptor_raw, encoded)
    pins.update(overrides)
    return startup_closure.parse_static_python_startup_closure(
        encoded,
        installation_descriptor_raw=descriptor_raw,
        **pins,
    )


def _refuse(operation):
    with pytest.raises(startup_closure.StaticPythonStartupClosureError) as caught:
        operation()
    error = caught.value
    assert type(error.reason) is str
    assert error.reason.startswith("static_python_startup_closure_")
    assert str(error) == error.reason
    assert error.args == (error.reason,)
    assert error.__cause__ is None
    assert error.__context__ is None
    return error


def _module(payload: dict, name: str) -> dict:
    return next(item for item in payload["modules"] if item["name"] == name)


def _node_limit_vector(f01: dict) -> dict:
    """A structurally valid, bounded graph whose decoded node count is high."""
    payload = _payload(f01)
    descriptor = f01
    records = {item["name"]: item for item in payload["modules"]}
    for item in descriptor["frozen_modules"]:
        records.setdefault(item["name"], {"name": item["name"], "route": "frozen", "target": ""})
    for item in descriptor["builtin_modules"]:
        records.setdefault(item["name"], {"name": item["name"], "route": "builtin", "target": ""})
    payload["modules"] = sorted(records.values(), key=lambda item: item["name"])
    names = list(records)
    roots = set(payload["startup_roots"])
    aliases = {name for name, item in records.items() if item["route"] == "alias"}
    edges = {
        (item["source"], item["target"], item["kind"])
        for item in payload["import_edges"]
    }
    # Make every non-root ordinary module reachable, and both alias routes
    # reachable by their fixed bootstrap-alias incoming edges.
    root = "_lunar_static_main"
    for name, item in records.items():
        if name not in roots and name not in aliases:
            edges.add((root, name, "import"))
    for alias in descriptor["aliases"]:
        edges.add((alias["name"], alias["alias"], "bootstrap-alias"))

    candidates = sorted(
        (source, target, kind)
        for source in names
        for target in names
        if source != target and target not in aliases
        for kind in _ORDINARY_KINDS
    )
    for edge in candidates:
        if len(edges) >= 2048:
            break
        edges.add(edge)
    assert len(edges) == 2048
    payload["import_edges"] = [
        {"source": source, "target": target, "kind": kind}
        for source, target, kind in sorted(edges)
    ]
    return payload


def test_minimal_current_profile_graph_is_only_synthetic_dto_comparison(
    vector: dict, f01: dict, descriptor_raw: bytes,
):
    raw = _encode(vector)
    result = _parse(vector, f01, descriptor_raw, raw=raw)

    assert result.canonical_bytes == raw
    assert type(result.canonical_bytes) is bytes
    assert result.to_dict() == vector
    assert result.to_dict()["evidence_scope"] == "synthetic-dto-comparison-only"
    assert result.to_dict()["expected_startup_modules"] == f01["initialization_profile"]["expected_startup_modules"]
    assert result.to_dict()["startup_roots"] == ["_lunar_static_main"]
    assert {item["route"] for item in vector["modules"]} == {
        "frozen", "builtin", "alias", "interpreter-created",
    }
    assert all(value is False for value in result.to_dict()["claims"].values())

    detached = result.to_dict()
    detached["claims"]["production_admission"] = True
    detached["modules"].clear()
    assert result.to_dict() == vector
    assert not hasattr(result, "__dict__")
    with pytest.raises(FrozenInstanceError):
        result.canonical_bytes = b"replacement"


def test_source_reviewed_roots_match_external_pin_and_profile_inventory(
    f01: dict, descriptor_raw: bytes,
):
    raw_roots = _SOURCE_ROOTS.read_bytes()
    roots = json.loads(raw_roots)
    assert _encode(roots) == raw_roots
    assert _sha(raw_roots) == _SOURCE_ROOTS_SHA256
    assert roots == sorted(set(roots))
    assert set(roots) < set(f01["initialization_profile"]["expected_startup_modules"])

    # Keep the edge graph intentionally synthetic. This confirms the source-root
    # pin composes with the v2 parser without presenting synthetic edges as a
    # source-complete or runtime-observed graph.
    payload = _payload(f01)
    payload["startup_roots"] = roots
    result = _parse(
        payload, f01, descriptor_raw,
        expected_startup_roots_sha256=_SOURCE_ROOTS_SHA256,
    )
    assert result.startup_roots == tuple(roots)
    assert result.to_dict()["evidence_scope"] == "synthetic-dto-comparison-only"


@pytest.mark.parametrize("pin", _PIN_NAMES)
def test_each_independent_pin_is_mandatory_and_mismatch_refuses(
    vector: dict, f01: dict, descriptor_raw: bytes, pin: str,
):
    pins = _pins(vector, f01, descriptor_raw)
    wrong = "different-synthetic-v1" if pin == "expected_installation_version" else "a" * 64
    _refuse(lambda: _parse(vector, f01, descriptor_raw, **{pin: wrong}))

    pins.pop(pin)
    with pytest.raises(TypeError):
        startup_closure.parse_static_python_startup_closure(
            _encode(vector), installation_descriptor_raw=descriptor_raw, **pins,
        )


@pytest.mark.parametrize("field", ["startup_roots", "modules", "import_edges"])
def test_canonical_wire_hash_is_an_independent_required_pin(vector, f01, descriptor_raw, field):
    changed = copy.deepcopy(vector)
    if field == "startup_roots":
        changed[field][0] = "replacement"
    elif field == "modules":
        changed[field][0]["name"] = "replacement"
    else:
        changed[field].append({"source": "abc", "target": "io", "kind": "import"})
    _refuse(lambda: _parse(changed, f01, descriptor_raw, expected_closure_sha256="b" * 64))


@pytest.mark.parametrize("mutation", ["missing", "extra", "unsorted", "duplicate", "all-modules"])
def test_startup_roots_are_a_pinned_proper_subset_of_the_expected_inventory(
    vector, f01, descriptor_raw, mutation,
):
    changed = copy.deepcopy(vector)
    if mutation == "missing":
        changed["startup_roots"] = []
    elif mutation == "extra":
        changed["startup_roots"].append("operator")
        changed["startup_roots"].sort()
    elif mutation == "unsorted":
        changed["startup_roots"] = ["_lunar_static_main", "_frozen_importlib"]
    else:
        if mutation == "duplicate":
            changed["startup_roots"].append(changed["startup_roots"][0])
            changed["startup_roots"].sort()
        else:
            changed["startup_roots"] = list(changed["expected_startup_modules"])
    _refuse(lambda: _parse(changed, f01, descriptor_raw))


def test_expected_startup_inventory_remains_exactly_descriptor_pinned(vector, f01, descriptor_raw):
    changed = copy.deepcopy(vector)
    changed["expected_startup_modules"].remove("io")
    _refuse(lambda: _parse(changed, f01, descriptor_raw))

    changed = copy.deepcopy(vector)
    changed["expected_startup_modules"].append("operator")
    changed["expected_startup_modules"].sort()
    _refuse(lambda: _parse(changed, f01, descriptor_raw))


def test_unreachable_expected_module_requires_a_real_edge_chain(vector, f01, descriptor_raw):
    changed = copy.deepcopy(vector)
    changed["import_edges"] = [
        edge for edge in changed["import_edges"] if edge["target"] != "io"
    ]
    _refuse(lambda: _parse(changed, f01, descriptor_raw))

    changed = copy.deepcopy(vector)
    changed["import_edges"] = [
        edge for edge in changed["import_edges"]
        if edge["target"] != "io" and edge["source"] != "io"
    ]
    _refuse(lambda: _parse(changed, f01, descriptor_raw))


def test_missing_startup_root_record_refuses(vector, f01, descriptor_raw):
    changed = copy.deepcopy(vector)
    root = changed["startup_roots"][0]
    changed["modules"] = [item for item in changed["modules"] if item["name"] != root]
    _refuse(lambda: _parse(changed, f01, descriptor_raw))


@pytest.mark.parametrize(
    "name,route",
    [
        ("operator", "builtin"),
        ("operator", "frozen"),
        ("importlib.unpinned_alias", "alias"),
        ("operator", "extension"),
        ("operator", "file"),
    ],
)
def test_new_or_external_module_routes_refuse_without_inventory_expansion(
    vector, f01, descriptor_raw, name, route,
):
    changed = copy.deepcopy(vector)
    changed["modules"].append({"name": name, "route": route, "target": ""})
    changed["modules"].sort(key=lambda item: item["name"])
    _refuse(lambda: _parse(changed, f01, descriptor_raw))


def test_conflicting_module_route_and_forged_alias_target_refuse(vector, f01, descriptor_raw):
    changed = copy.deepcopy(vector)
    changed["modules"].append({"name": "abc", "route": "builtin", "target": ""})
    changed["modules"].sort(key=lambda item: item["name"])
    _refuse(lambda: _parse(changed, f01, descriptor_raw))

    changed = copy.deepcopy(vector)
    alias = _module(changed, "importlib._bootstrap")
    alias["target"] = "_frozen_importlib_external"
    _refuse(lambda: _parse(changed, f01, descriptor_raw))


def test_non_alias_targets_must_be_empty_and_unlisted_targets_refuse(vector, f01, descriptor_raw):
    changed = copy.deepcopy(vector)
    _module(changed, "abc")["target"] = "_frozen_importlib"
    _refuse(lambda: _parse(changed, f01, descriptor_raw))

    changed = copy.deepcopy(vector)
    alias = _module(changed, "importlib._bootstrap")
    alias["target"] = "operator"
    _refuse(lambda: _parse(changed, f01, descriptor_raw))


def test_unreachable_inventory_member_and_missing_edge_endpoint_refuse(vector, f01, descriptor_raw):
    changed = copy.deepcopy(vector)
    changed["modules"] = [item for item in changed["modules"] if item["name"] != "io"]
    _refuse(lambda: _parse(changed, f01, descriptor_raw))

    changed = copy.deepcopy(vector)
    changed["import_edges"].append(
        {"source": "_lunar_static_main", "target": "operator", "kind": "import"},
    )
    changed["import_edges"].sort(key=lambda item: (item["source"], item["target"], item["kind"]))
    _refuse(lambda: _parse(changed, f01, descriptor_raw))


@pytest.mark.parametrize("mutation", ["duplicate", "unsorted", "kind", "alias-map"])
def test_edges_are_unique_sorted_typed_and_match_the_fixed_alias_mapping(
    vector, f01, descriptor_raw, mutation,
):
    changed = copy.deepcopy(vector)
    if mutation == "duplicate":
        changed["import_edges"].append(copy.deepcopy(changed["import_edges"][0]))
        changed["import_edges"].sort(key=lambda item: (item["source"], item["target"], item["kind"]))
    elif mutation == "unsorted":
        changed["import_edges"].reverse()
    elif mutation == "kind":
        changed["import_edges"][0]["kind"] = "dynamic-import"
        changed["import_edges"].sort(key=lambda item: (item["source"], item["target"], item["kind"]))
    else:
        alias_edge = next(edge for edge in changed["import_edges"] if edge["kind"] == "bootstrap-alias")
        alias_edge["target"] = "importlib._bootstrap_external"
        changed["import_edges"].sort(key=lambda item: (item["source"], item["target"], item["kind"]))
    _refuse(lambda: _parse(changed, f01, descriptor_raw))


@pytest.mark.parametrize("alias", ["importlib._bootstrap", "importlib._bootstrap_external"])
def test_bootstrap_alias_edge_requires_its_canonical_frozen_source(
    vector, f01, descriptor_raw, alias,
):
    changed = copy.deepcopy(vector)
    edge = next(
        item for item in changed["import_edges"]
        if item["kind"] == "bootstrap-alias" and item["target"] == alias
    )
    # _lunar_static_main is another reachable frozen startup root, so this
    # mutation isolates the alias-source binding rather than reachability.
    edge["source"] = "_lunar_static_main"
    changed["import_edges"].sort(
        key=lambda item: (item["source"], item["target"], item["kind"]),
    )
    error = _refuse(lambda: _parse(changed, f01, descriptor_raw))
    assert error.reason == "static_python_startup_closure_alias"


@pytest.mark.parametrize("field", ["unresolved_imports", "unsupported_import_sites"])
def test_unresolved_and_unsupported_import_arrays_are_required_and_empty(
    vector, f01, descriptor_raw, field,
):
    changed = copy.deepcopy(vector)
    changed[field] = ["operator"]
    _refuse(lambda: _parse(changed, f01, descriptor_raw))

    changed = copy.deepcopy(vector)
    changed.pop(field)
    _refuse(lambda: _parse(changed, f01, descriptor_raw))


def test_reviewed_source_audit_unsupported_sites_remain_refused(
    vector, f01, descriptor_raw,
):
    source_graph = json.loads(_STARTUP_SCOPE_GRAPH.read_bytes())
    changed = copy.deepcopy(vector)
    changed["unsupported_import_sites"] = [
        {
            key: item[key]
            for key in ("source", "line", "column", "reason")
        }
        for item in source_graph["unsupported_site_decisions"]
    ]
    error = _refuse(lambda: _parse(changed, f01, descriptor_raw))
    assert error.reason == "static_python_startup_closure_unsupported"


def test_deferred_out_of_profile_source_edge_remains_refused(
    vector, f01, descriptor_raw,
):
    source_graph = json.loads(_STARTUP_SCOPE_GRAPH.read_bytes())
    deferred = next(
        item for item in source_graph["python_source_edge_audit"]
        if item["target"] == "tokenize"
    )
    changed = copy.deepcopy(vector)
    changed["import_edges"].append({
        "source": deferred["source"],
        "target": deferred["target"],
        "kind": deferred["kind"],
    })
    changed["import_edges"].sort(
        key=lambda item: (item["source"], item["target"], item["kind"]),
    )
    error = _refuse(lambda: _parse(changed, f01, descriptor_raw))
    assert error.reason == "static_python_startup_closure_edge"


@pytest.mark.parametrize("claim", _CLAIMS)
def test_every_claim_must_remain_exact_false(vector, f01, descriptor_raw, claim):
    changed = copy.deepcopy(vector)
    changed["claims"][claim] = True
    _refuse(lambda: _parse(changed, f01, descriptor_raw))


@pytest.mark.parametrize("bad", [1, "false", None, 0])
def test_claims_reject_truthy_or_non_boolean_values(vector, f01, descriptor_raw, bad):
    changed = copy.deepcopy(vector)
    changed["claims"]["production_admission"] = bad
    _refuse(lambda: _parse(changed, f01, descriptor_raw))


def test_boolean_float_and_null_type_substitutions_refuse(vector, f01, descriptor_raw):
    changed = copy.deepcopy(vector)
    changed["startup_roots"][0] = False
    _refuse(lambda: _parse(changed, f01, descriptor_raw))

    for raw in (
        _encode(vector).replace(b'"production_admission":false', b'"production_admission":1.5'),
        _encode(vector).replace(b'"unsupported_import_sites":[]', b'"unsupported_import_sites":null'),
    ):
        _refuse(lambda raw=raw: _parse(vector, f01, descriptor_raw, raw=raw))


def test_duplicate_keys_unknown_fields_noncanonical_and_invalid_utf8_refuse(
    vector, f01, descriptor_raw,
):
    canonical = _encode(vector)
    duplicate = canonical[:-1] + b',"schema":"lunar-static-python-startup-closure-v2"}'
    _refuse(lambda: _parse(vector, f01, descriptor_raw, raw=duplicate))
    _refuse(lambda: _parse(vector, f01, descriptor_raw, raw=canonical + b" "))
    _refuse(lambda: _parse(vector, f01, descriptor_raw, raw=b"\xff"))

    changed = copy.deepcopy(vector)
    changed["unreviewed"] = "caller-controlled-context"
    error = _refuse(lambda: _parse(changed, f01, descriptor_raw))
    assert "caller-controlled-context" not in str(error)


@pytest.mark.parametrize("container", [bytearray, memoryview])
def test_raw_and_descriptor_require_exact_builtin_bytes(vector, f01, descriptor_raw, container):
    with pytest.raises((startup_closure.StaticPythonStartupClosureError, TypeError)):
        startup_closure.parse_static_python_startup_closure(
            container(_encode(vector)),
            installation_descriptor_raw=descriptor_raw,
            **_pins(vector, f01, descriptor_raw),
        )
    with pytest.raises((startup_closure.StaticPythonStartupClosureError, TypeError)):
        startup_closure.parse_static_python_startup_closure(
            _encode(vector),
            installation_descriptor_raw=container(descriptor_raw),
            **_pins(vector, f01, descriptor_raw),
        )


@pytest.mark.parametrize("pin,value", [("expected_closure_sha256", "0" * 64), ("expected_alias_inventory_sha256", "f" * 64)])
def test_sentinel_digest_pins_refuse(vector, f01, descriptor_raw, pin, value):
    _refuse(lambda: _parse(vector, f01, descriptor_raw, **{pin: value}))


def test_installation_descriptor_canonical_profile_and_inventory_drift_refuse(
    vector, f01, descriptor_raw,
):
    pins = _pins(vector, f01, descriptor_raw)
    _refuse(lambda: startup_closure.parse_static_python_startup_closure(
        _encode(vector),
        installation_descriptor_raw=descriptor_raw + b" ",
        **pins,
    ))

    changed_descriptor = copy.deepcopy(f01)
    changed_descriptor["initialization_profile"]["expected_startup_modules"].append("operator")
    changed_raw = _encode(changed_descriptor)
    _refuse(lambda: _parse(vector, f01, changed_raw))

    changed_descriptor = copy.deepcopy(f01)
    changed_descriptor["aliases"][0]["name"] = "operator"
    changed_raw = _encode(changed_descriptor)
    _refuse(lambda: _parse(vector, f01, changed_raw))

    # A separately valid descriptor can still conflict with the independently
    # pinned graph. Update its own descriptor/version pins so the refusal is
    # the cross-document comparison, not malformed descriptor handling.
    changed_descriptor = copy.deepcopy(f01)
    changed_descriptor["installation_version"] = "synthetic-other-v1"
    changed_raw = _encode(changed_descriptor)
    changed_pins = _pins(vector, f01, descriptor_raw)
    changed_pins["expected_installation_descriptor_sha256"] = _sha(changed_raw)
    changed_pins["expected_installation_version"] = changed_descriptor["installation_version"]
    error = _refuse(lambda: startup_closure.parse_static_python_startup_closure(
        _encode(vector), installation_descriptor_raw=changed_raw, **changed_pins,
    ))
    assert error.reason == "static_python_startup_closure_profile"


def test_decoded_bounds_and_wire_limit_refuse(vector, f01, descriptor_raw):
    # These payloads remain in memory and stay within the 256 KiB wire limit
    # unless the test specifically exercises that boundary.
    for value in (
        {"deep": [[[[[[[[[[[[[[0]]]]]]]]]]]]]]},
        {"large_text": "x" * (192 * 1024 + 1)},
        {"many_nodes": [0] * 8193},
    ):
        error = _refuse(lambda value=value: _parse(value, f01, descriptor_raw))
        assert error.reason == "static_python_startup_closure_bounds"

    over_limit = b" " * (256 * 1024 + 1)
    _refuse(lambda: _parse(vector, f01, descriptor_raw, raw=over_limit))

    crowded = _node_limit_vector(f01)
    crowded_raw = _encode(crowded)
    assert len(crowded_raw) < 256 * 1024
    error = _refuse(lambda: _parse(crowded, f01, descriptor_raw, raw=crowded_raw))
    assert error.reason == "static_python_startup_closure_bounds"


def test_parser_does_not_call_filesystem_process_network_or_environment_apis(
    vector, f01, descriptor_raw, monkeypatch,
):
    raw = _encode(vector)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("startup-closure parser must remain provider-free and in-memory")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(os, "open", forbidden)
    monkeypatch.setattr(os, "getenv", forbidden)
    monkeypatch.setattr(os, "environ", _ForbiddenEnvironment())
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    result = startup_closure.parse_static_python_startup_closure(
        raw,
        installation_descriptor_raw=descriptor_raw,
        **_pins(vector, f01, descriptor_raw, raw),
    )
    assert result.canonical_bytes == raw


class _ForbiddenEnvironment(dict):
    def __getitem__(self, _key):
        raise AssertionError("environment access is forbidden")

    def __contains__(self, _key):
        raise AssertionError("environment access is forbidden")

    def get(self, _key, _default=None):
        raise AssertionError("environment access is forbidden")


class _BytesSubclass(bytes):
    pass


class _StringSubclass(str):
    pass


@pytest.mark.parametrize("wrapper", [_BytesSubclass, _StringSubclass])
def test_subclassed_wire_and_pin_values_are_not_accepted(vector, f01, descriptor_raw, wrapper):
    pins = _pins(vector, f01, descriptor_raw)
    if wrapper is _BytesSubclass:
        with pytest.raises(startup_closure.StaticPythonStartupClosureError):
            startup_closure.parse_static_python_startup_closure(
                wrapper(_encode(vector)), installation_descriptor_raw=descriptor_raw, **pins,
            )
    else:
        pins["expected_installation_version"] = wrapper(pins["expected_installation_version"])
        with pytest.raises(startup_closure.StaticPythonStartupClosureError):
            startup_closure.parse_static_python_startup_closure(
                _encode(vector), installation_descriptor_raw=descriptor_raw, **pins,
            )
