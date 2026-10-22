"""Independent synthetic RSI installation descriptions; no build/runtime acceptance.

Generated header, object and artifact records below are deliberately fictional.
They are metadata comparison vectors, never evidence of F01/F02 installation.
"""

from __future__ import annotations

import builtins
import copy
import hashlib
import json
import os
import re
import socket
import subprocess
import urllib.request
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from lunar_evolution import static_python_installation as original
from lunar_evolution import static_python_rsi_installation as installation

_ROOT = Path(__file__).resolve().parents[1]
_CLAIMS = (
    "configured_closure_verified", "compilation_performed", "freezer_performed",
    "runtime_execution_performed", "installation_accepted", "input_consumption_verified",
    "runtime_load_protection", "production_admission", "general_code_origin_protection",
)
_REASONS = {
    "invalid", "raw", "pin", "json", "duplicate_key", "structure", "canonical", "digest", "schema",
    "reviewed_inputs", "launch_policy", "launcher", "descriptor", "frozen_inventory",
    "main_header", "claims",
}
_PINS = (
    "expected_contract_sha256", "expected_descriptor_sha256", "expected_installation_version",
    "expected_artifact_sha256", "expected_frozen_inventory_sha256", "expected_main_header_sha256",
)
_DIGEST_PINS = tuple(key for key in _PINS if key != "expected_installation_version")


def _encode(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_encode(value)).hexdigest()


def _synthetic_digest(label: str) -> str:
    return hashlib.sha256(("synthetic metadata only: " + label).encode()).hexdigest()


def _rehash_descriptor(descriptor: dict) -> None:
    # Independently reproduce documented nested comparison manifests, not parser helpers.
    sections = {
        "patch_set_sha256": descriptor["source_provenance"]["patches"],
        "recipe_sha256": descriptor["recipe"],
        "toolchain_manifest_sha256": descriptor["toolchain"],
        "link_manifest_sha256": descriptor["recipe"]["link_inputs"],
        "initialization_profile_sha256": descriptor["initialization_profile"],
        "frozen_inventory_sha256": descriptor["frozen_modules"],
        "builtin_inventory_sha256": descriptor["builtin_modules"],
        "alias_inventory_sha256": descriptor["aliases"],
    }
    descriptor.update({key: _digest(value) for key, value in sections.items()})


@pytest.fixture(scope="module")
def reviewed_vector() -> dict:
    base_raw = (_ROOT / "tools/static_python_fixture/reviewed-build-inputs.json").read_bytes()
    overlay_raw = (_ROOT / "tools/static_python_rsi_fixture/reviewed-profile-overlay.json").read_bytes()
    assert (len(base_raw), hashlib.sha256(base_raw).hexdigest()) == (
        80050, "c305d56956b75eda286b0e630ceeeaa0f37db2e9f669879eb30a563f8dd2bb31",
    )
    assert (len(overlay_raw), hashlib.sha256(overlay_raw).hexdigest()) == (
        2456, "31e8e064dc5317b3297140f55f07e81ca1aa9c831a4e4bbbf46cc76db0667b8f",
    )
    base, overlay = json.loads(base_raw), json.loads(overlay_raw)
    descriptor = json.loads(
        (_ROOT / "specs/189-static-python-fixture/wire-v1-example.json").read_bytes(),
    )["descriptor"]
    tasks = {task["name"]: task for task in base["freeze_tasks"]}
    changes = {entry["section"]: entry["after"] for entry in overlay["substitutions"]}
    tasks["_lunar_static_main"] = changes["freeze_tasks"]
    for index, module in enumerate(descriptor["frozen_modules"]):
        task = tasks[module["name"]]
        module["source"] = {
            "path": task["source"], "size": task["source_size"], "sha256": task["source_sha256"],
        }
        module["generated"] = {
            "path": task["output"], "size": 128 + index,
            "sha256": _synthetic_digest("generated " + module["name"]),
        }
    launcher = changes["target_units"]
    object_record = {
        "path": launcher["object"], "size": 64,
        "sha256": _synthetic_digest("launcher object"),
    }
    descriptor["recipe"]["link_inputs"].append(copy.deepcopy(object_record))
    descriptor["recipe"]["link_inputs"].sort(key=lambda record: record["path"])
    descriptor["installation_version"] = "synthetic-rsi-metadata-v1"
    _rehash_descriptor(descriptor)
    return {
        "schema": "lunar-static-python-rsi-installation-contract-v1",
        "profile": "rsi-marker-launch-v1",
        "base_reviewed_inputs": overlay["base"],
        "reviewed_overlay": {"size": len(overlay_raw), "sha256": hashlib.sha256(overlay_raw).hexdigest()},
        "source_plan": overlay["source_plan"],
        "launch_policy": {
            "argc": 3, "marker": "--lunar-rsi-input-v1", "marker_index": 1,
            "manifest_digest_index": 2, "manifest_digest_syntax": "[0-9a-f]{64}",
            "frozen_entrypoint": "_rsi_launch", "baseline_case": "baseline",
            "environment_selector": False, "input_reads": [],
        },
        "launcher": {
            "source": {"path": launcher["source"], "size": launcher["source_size"],
                       "sha256": launcher["source_sha256"]},
            "object": object_record,
        },
        "descriptor": descriptor,
        "claims": dict.fromkeys(_CLAIMS, False),
    }


@pytest.fixture
def vector(reviewed_vector: dict) -> dict:
    return copy.deepcopy(reviewed_vector)


def _pins(vector: dict, raw: bytes | None = None) -> dict:
    descriptor = vector["descriptor"]
    main = next(item for item in descriptor["frozen_modules"] if item["name"] == "_lunar_static_main")
    return {
        "expected_contract_sha256": hashlib.sha256(_encode(vector) if raw is None else raw).hexdigest(),
        "expected_descriptor_sha256": _digest(descriptor),
        "expected_installation_version": descriptor["installation_version"],
        "expected_artifact_sha256": descriptor["artifact_sha256"],
        "expected_frozen_inventory_sha256": descriptor["frozen_inventory_sha256"],
        "expected_main_header_sha256": main["generated"]["sha256"],
    }


def _parse(vector: dict, **overrides):
    pins = _pins(vector)
    pins.update(overrides)
    return installation.parse_static_python_rsi_installation_descriptor(_encode(vector), **pins)


def _refuse(operation, reason: str | None = None):
    with pytest.raises(installation.StaticPythonRSIInstallationError) as caught:
        operation()
    error = caught.value
    assert type(error.reason) is str
    assert error.reason.removeprefix("static_python_rsi_installation_") in _REASONS
    assert str(error) == error.reason
    assert error.args == (error.reason,)
    assert error.__cause__ is None
    assert error.__context__ is None
    if reason is not None:
        assert error.reason == "static_python_rsi_installation_" + reason
    return error


def _bomb(*_args, **_kwargs):
    raise AssertionError("caller callback or external operation must not run")


class _HostileBytes(bytes):
    __len__ = _bomb
    __bytes__ = _bomb
    __iter__ = _bomb
    __getitem__ = _bomb


class _HostileString(str):
    __len__ = _bomb
    __str__ = _bomb
    __iter__ = _bomb
    encode = _bomb


class _ForbiddenEnvironment(dict):
    __getitem__ = _bomb
    __iter__ = _bomb
    __contains__ = _bomb
    get = _bomb
    keys = _bomb
    items = _bomb
    values = _bomb


def test_synthetic_vector_preserves_old_parser_and_has_no_acceptance_claims(vector):
    raw = _encode(vector)
    result = _parse(vector)
    embedded = original.parse_static_python_installation_descriptor(
        _encode(vector["descriptor"]), **{key: value for key, value in _pins(vector).items()
                                       if key in {"expected_descriptor_sha256", "expected_installation_version",
                                                  "expected_artifact_sha256"}},
    )
    assert result.canonical_bytes == result.to_json() == raw
    assert type(result.to_json()) is bytes
    assert result.contract_sha256 == hashlib.sha256(raw).hexdigest()
    assert result.descriptor_sha256 == embedded.descriptor_sha256
    for pin, value in _pins(vector).items():
        assert getattr(result, pin.removeprefix("expected_")) == value
    assert result.to_dict() == vector
    assert len(vector["descriptor"]["frozen_modules"]) == 9
    assert all(value is False for value in result.to_dict()["claims"].values())
    assert all(vector["descriptor"][claim] is False for claim in (
        "execution_performed", "runtime_load_protection", "production_admission",
        "general_code_origin_protection",
    ))


def test_result_is_frozen_slots_and_each_dictionary_access_is_detached(vector):
    result = _parse(vector)
    assert not hasattr(result, "__dict__")
    with pytest.raises(FrozenInstanceError):
        result.canonical_bytes = b"replacement"
    with pytest.raises((AttributeError, TypeError)):
        result.other = "replacement"
    detached = result.to_dict()
    detached["descriptor"]["frozen_modules"].clear()
    detached["claims"]["installation_accepted"] = True
    vector["launcher"]["object"]["size"] = 999
    assert len(result.to_dict()["descriptor"]["frozen_modules"]) == 9
    assert result.to_dict()["claims"]["installation_accepted"] is False
    assert result.to_dict()["launcher"]["object"]["size"] == 64


@pytest.mark.parametrize("key", _PINS)
def test_every_external_pin_is_independent_and_mandatory(vector, key):
    mismatch = "different-synthetic-v1" if key == "expected_installation_version" else "a" * 64
    _refuse(lambda: _parse(vector, **{key: mismatch}))
    pins = _pins(vector)
    pins.pop(key)
    with pytest.raises(TypeError):
        installation.parse_static_python_rsi_installation_descriptor(_encode(vector), **pins)


@pytest.mark.parametrize("key", _PINS)
@pytest.mark.parametrize("bad", [None, True, b"caller material",
                                 pytest.param(_HostileString("sensitive-caller-value"), id="hostile-string")])
def test_pin_types_refuse_before_parser_hash_or_delegate(vector, monkeypatch, key, bad):
    raw, pins = _encode(vector), _pins(vector)
    pins[key] = bad
    with monkeypatch.context() as patch:
        patch.setattr(installation.json, "loads", _bomb)
        patch.setattr(installation.hashlib, "sha256", _bomb)
        patch.setattr(original, "parse_static_python_installation_descriptor", _bomb)
        patch.setattr(installation, "parse_static_python_installation_descriptor", _bomb)
        _refuse(lambda: installation.parse_static_python_rsi_installation_descriptor(raw, **pins), "pin")


@pytest.mark.parametrize("key", _DIGEST_PINS)
@pytest.mark.parametrize("bad", ["0" * 64, "f" * 64, "A" * 64, "a" * 63, "a" * 65, "../secret"])
def test_digest_pin_syntax_and_sentinels_refuse(vector, monkeypatch, key, bad):
    raw, pins = _encode(vector), _pins(vector)
    pins[key] = bad
    with monkeypatch.context() as patch:
        patch.setattr(installation.json, "loads", _bomb)
        patch.setattr(installation.hashlib, "sha256", _bomb)
        _refuse(lambda: installation.parse_static_python_rsi_installation_descriptor(raw, **pins), "pin")


@pytest.mark.parametrize("bad", ["", "a" * 129, "é", "x/y", " x", "x\n", "x\x00", "\ud800"])
def test_version_pin_is_a_bounded_ascii_label(vector, bad):
    _refuse(lambda: _parse(vector, expected_installation_version=bad), "pin")


@pytest.mark.parametrize("raw", [None, "caller secret", bytearray(b"{}"), memoryview(b"{}"),
                                 pytest.param(_HostileBytes(b"sensitive"), id="hostile-bytes"),
                                 b"", pytest.param(b" " * (384 * 1024 + 1), id="oversize")])
def test_raw_exact_type_and_bounds_precede_hash_and_parser(vector, monkeypatch, raw):
    pins = _pins(vector)
    assert installation.MAX_CONTRACT_BYTES == 384 * 1024
    with monkeypatch.context() as patch:
        patch.setattr(installation.json, "loads", _bomb)
        patch.setattr(installation.hashlib, "sha256", _bomb)
        patch.setattr(original, "parse_static_python_installation_descriptor", _bomb)
        patch.setattr(installation, "parse_static_python_installation_descriptor", _bomb)
        _refuse(lambda: installation.parse_static_python_rsi_installation_descriptor(raw, **pins), "raw")


@pytest.mark.parametrize("raw", [
    b"\xff", b"{", b"null", b"[]", b"1", b"true", b'{"schema":null}',
    b'{"schema":1.0}', b'{"schema":NaN}', b'{"schema":Infinity}',
    b'{"schema":-Infinity}', b'{"schema":"\\ud800"}',
    b'{"secret-caller-key":1,"secret-caller-key":2}',
    b'{"outer":{"secret-caller-key":1,"secret-caller-key":2}}',
])
def test_invalid_json_and_duplicate_nested_keys_have_fixed_disclosure_free_errors(vector, raw):
    pins = _pins(vector, raw)
    error = _refuse(lambda: installation.parse_static_python_rsi_installation_descriptor(raw, **pins))
    assert "secret-caller" not in str(error)
    assert "secret-caller" not in repr(error)


@pytest.mark.parametrize("suffix", [b" ", b"\n", b"\x00"])
def test_noncanonical_wire_is_not_repaired_even_when_outer_pin_matches(vector, suffix):
    raw = _encode(vector) + suffix
    _refuse(lambda: installation.parse_static_python_rsi_installation_descriptor(raw, **_pins(vector, raw)))


def test_key_reordering_and_ascii_escaping_are_not_canonicalized_into_acceptance(vector):
    raw = json.dumps(vector, separators=(",", ":")).encode()
    assert raw != _encode(vector)
    _refuse(lambda: installation.parse_static_python_rsi_installation_descriptor(raw, **_pins(vector, raw)), "canonical")
    escaped = _encode(vector).replace(b'"lunar-static-python-rsi-installation-contract-v1"',
                                      b'"\\u006cunar-static-python-rsi-installation-contract-v1"')
    assert json.loads(escaped) == vector
    _refuse(lambda: installation.parse_static_python_rsi_installation_descriptor(
        escaped, **_pins(vector, escaped),
    ), "canonical")


@pytest.mark.parametrize("payload", [
    {"extra": [[[[[[[[[[[[[[[[[1]]]]]]]]]]]]]]]]]},
    {"extra": [True] * 17000},
    {"extra": "s" * (256 * 1024 + 1)},
])
def test_decoded_depth_node_and_utf8_text_limits_are_bounded(vector, payload):
    raw = _encode(payload)
    assert len(raw) < installation.MAX_CONTRACT_BYTES
    _refuse(lambda: installation.parse_static_python_rsi_installation_descriptor(raw, **_pins(vector, raw)), "structure")


@pytest.mark.parametrize("key", ["schema", "profile", "base_reviewed_inputs", "reviewed_overlay",
                                 "source_plan", "launch_policy", "launcher", "descriptor", "claims"])
def test_exact_wrapper_fields_cannot_be_omitted_or_extended(vector, key):
    vector.pop(key)
    raw = _encode(vector)
    pins = _pins_from_original_for_raw(raw)
    _refuse(lambda: installation.parse_static_python_rsi_installation_descriptor(raw, **pins))


def _pins_from_original_for_raw(raw: bytes) -> dict:
    # A malformed wrapper has no descriptor to derive: these caller pins remain independently valid.
    return dict(zip(_PINS, (hashlib.sha256(raw).hexdigest(), "b" * 64, "synthetic-v1", "c" * 64,
                           "d" * 64, "e" * 64), strict=True))


def test_unknown_wrapper_fields_refuse_resigned_bytes(vector):
    vector["private-caller-material"] = "never disclose this value"
    error = _refuse(lambda: _parse(vector), "schema")
    assert "private-caller" not in str(error)


@pytest.mark.parametrize("key", ["base_reviewed_inputs", "reviewed_overlay", "source_plan"])
@pytest.mark.parametrize("field,value", [("size", True), ("size", 1), ("sha256", "a" * 64)])
def test_reviewed_input_records_are_exact_even_after_resigning(vector, key, field, value):
    vector[key][field] = value
    _refuse(lambda: _parse(vector))


@pytest.mark.parametrize("field,value", [
    ("argc", True), ("argc", 2), ("marker", "--other"), ("marker_index", False),
    ("manifest_digest_index", 1), ("manifest_digest_syntax", "[A-F0-9]{64}"),
    ("frozen_entrypoint", "__main__"), ("baseline_case", "mutant"),
    ("environment_selector", True), ("environment_selector", 0), ("input_reads", ["secret"]),
])
def test_os_launch_policy_is_fixed_and_separate_from_python_argv(vector, field, value):
    vector["launch_policy"][field] = value
    _refuse(lambda: _parse(vector), "launch_policy")


def test_python_initialization_argv_cannot_be_rewritten_to_os_marker_argv(vector):
    vector["descriptor"]["initialization_profile"]["config"]["argv"] = [
        "lunar-static-python-fixture", "--lunar-rsi-input-v1", "a" * 64,
    ]
    _rehash_descriptor(vector["descriptor"])
    _refuse(lambda: _parse(vector), "descriptor")


@pytest.mark.parametrize("field,value", [("path", "other-launcher.c"), ("size", 1741),
                                        ("size", True), ("sha256", "a" * 64)])
def test_launcher_source_is_the_complete_reviewed_record(vector, field, value):
    vector["launcher"]["source"][field] = value
    _refuse(lambda: _parse(vector), "launcher")


@pytest.mark.parametrize("change", ["missing", "duplicate", "digest", "size", "path"])
def test_complete_launcher_object_occurs_once_and_matches_link_input(vector, change):
    inputs = vector["descriptor"]["recipe"]["link_inputs"]
    item = next(record for record in inputs if record["path"] == "installation-owned-launcher.o")
    if change == "missing":
        inputs.remove(item)
    elif change == "duplicate":
        inputs.insert(inputs.index(item), copy.deepcopy(item))
    elif change == "digest":
        item["sha256"] = "a" * 64
    elif change == "size":
        item["size"] += 1
    else:
        vector["launcher"]["object"]["path"] = "other-launcher.o"
    _rehash_descriptor(vector["descriptor"])
    _refuse(lambda: _parse(vector))


@pytest.mark.parametrize("index", range(9))
def test_each_frozen_source_is_reviewed_even_with_matching_new_manifest_and_pins(vector, index):
    vector["descriptor"]["frozen_modules"][index]["source"]["sha256"] = "a" * 64
    _rehash_descriptor(vector["descriptor"])
    _refuse(lambda: _parse(vector), "frozen_inventory")


@pytest.mark.parametrize("index", range(9))
def test_each_generated_path_must_match_reviewed_freeze_task(vector, index):
    vector["descriptor"]["frozen_modules"][index]["generated"]["path"] = "arbitrary/header.h"
    _rehash_descriptor(vector["descriptor"])
    _refuse(lambda: _parse(vector), "frozen_inventory")


@pytest.mark.parametrize("change", ["old-main", "source-path", "source-size", "missing-module",
                                     "pending-header", "zero-header", "sentinel-header"])
def test_incomplete_pending_and_old_main_inventories_refuse(vector, change):
    pins = _pins(vector)
    modules = vector["descriptor"]["frozen_modules"]
    main = next(record for record in modules if record["name"] == "_lunar_static_main")
    if change == "old-main":
        main["source"].update(size=6794, sha256="6e6a9e661f50dc1baf5b1e6e1f2a717468f1351d7fc6d534ecae125717e0695d")
    elif change == "source-path":
        main["source"]["path"] = "source/old-main.py"
    elif change == "source-size":
        main["source"]["size"] = 7226
    elif change == "missing-module":
        modules.pop()
    elif change == "pending-header":
        main["generated"] = {"state": "pending-freezer"}
    elif change == "zero-header":
        main["generated"]["size"] = 0
    else:
        main["generated"]["sha256"] = "0" * 64
    _rehash_descriptor(vector["descriptor"])
    raw = _encode(vector)
    pins.update(expected_contract_sha256=hashlib.sha256(raw).hexdigest(),
                expected_descriptor_sha256=_digest(vector["descriptor"]),
                expected_frozen_inventory_sha256=vector["descriptor"]["frozen_inventory_sha256"])
    expected = "descriptor" if change in {
        "missing-module", "pending-header", "zero-header", "sentinel-header",
    } else "frozen_inventory"
    _refuse(lambda: installation.parse_static_python_rsi_installation_descriptor(raw, **pins), expected)


def test_main_header_and_inventory_require_separate_external_comparisons(vector):
    old = _pins(vector)
    main = next(record for record in vector["descriptor"]["frozen_modules"]
                if record["name"] == "_lunar_static_main")
    main["generated"]["sha256"] = _synthetic_digest("different header")
    _rehash_descriptor(vector["descriptor"])
    _refuse(lambda: _parse(vector, expected_main_header_sha256=old["expected_main_header_sha256"]))
    _refuse(lambda: _parse(vector, expected_frozen_inventory_sha256=old["expected_frozen_inventory_sha256"]))
    # Matching fictional pins may accept description only; no bytes/build were verified.
    assert _parse(vector).to_dict()["claims"]["installation_accepted"] is False


@pytest.mark.parametrize("claim", _CLAIMS)
@pytest.mark.parametrize("value", [True, 0])
def test_all_preparation_claims_must_be_exact_false(vector, claim, value):
    vector["claims"][claim] = value
    _refuse(lambda: _parse(vector), "claims")


def test_old_parser_does_not_accept_the_new_wrapper_protocol(vector):
    with pytest.raises(original.StaticPythonInstallationError):
        original.parse_static_python_installation_descriptor(
            _encode(vector), expected_descriptor_sha256=_digest(vector),
            expected_installation_version="synthetic-rsi-metadata-v1",
            expected_artifact_sha256=vector["descriptor"]["artifact_sha256"],
        )


def test_delegate_errors_do_not_retain_sensitive_context(vector, monkeypatch):
    def fail(*_args, **_kwargs):
        error = original.StaticPythonInstallationError("json")
        error.args = ("sensitive caller path /private/operator/key",)
        raise error

    monkeypatch.setattr(installation, "parse_static_python_installation_descriptor", fail)
    error = _refuse(lambda: _parse(vector), "descriptor")
    assert "sensitive" not in repr(error)
    assert "/private/" not in str(error)


def test_error_constructor_cannot_expose_unknown_reason_material():
    error = installation.StaticPythonRSIInstallationError("private-caller-credentials")
    assert re.fullmatch(r"static_python_rsi_installation_[a-z_]+", str(error))
    assert "private-caller" not in str(error)
    assert error.reason.removeprefix("static_python_rsi_installation_") in _REASONS


def test_exact_raw_maximum_reaches_json_validation_before_hash(vector, monkeypatch):
    raw = b" " * installation.MAX_CONTRACT_BYTES
    pins = _pins(vector, raw)
    monkeypatch.setattr(installation.hashlib, "sha256", _bomb)
    _refuse(lambda: installation.parse_static_python_rsi_installation_descriptor(raw, **pins), "json")


def test_launcher_object_is_a_positive_bounded_complete_record(vector):
    for field, bad in (("size", 0), ("size", True), ("size", 1024 * 1024 * 1024 + 1),
                       ("sha256", "0" * 64), ("sha256", "A" * 64), ("path", "")):
        changed = copy.deepcopy(vector)
        changed["launcher"]["object"][field] = bad
        _refuse(lambda changed=changed: _parse(changed))
    vector["launcher"]["object"]["state"] = "pending-compile"
    _refuse(lambda: _parse(vector))


def test_schema_profile_and_claim_field_sets_remain_exact(vector):
    for field, bad in (("schema", "lunar-static-python-installation-v1"),
                       ("profile", "ordinary-fixture-v1")):
        changed = copy.deepcopy(vector)
        changed[field] = bad
        _refuse(lambda changed=changed: _parse(changed), "schema")
    changed = copy.deepcopy(vector)
    changed["claims"].pop("installation_accepted")
    _refuse(lambda: _parse(changed))
    vector["claims"]["source_object_correspondence_verified"] = False
    _refuse(lambda: _parse(vector))


def test_success_and_refusal_have_no_filesystem_environment_network_or_process_effects(vector, monkeypatch):
    raw, pins = _encode(vector), _pins(vector)
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "tools" or name.startswith("tools."):
            _bomb()
        return original_import(name, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", _bomb)
        patch.setattr(builtins, "__import__", guarded_import)
        patch.setattr(Path, "open", _bomb)
        patch.setattr(Path, "read_bytes", _bomb)
        patch.setattr(Path, "write_bytes", _bomb)
        patch.setattr(Path, "stat", _bomb)
        patch.setattr(os, "getenv", _bomb)
        patch.setattr(os, "environ", _ForbiddenEnvironment())
        patch.setattr(socket, "socket", _bomb)
        patch.setattr(socket, "getaddrinfo", _bomb)
        patch.setattr(subprocess, "run", _bomb)
        patch.setattr(subprocess, "Popen", _bomb)
        patch.setattr(subprocess, "check_output", _bomb)
        patch.setattr(urllib.request, "urlopen", _bomb)
        result = installation.parse_static_python_rsi_installation_descriptor(raw, **pins)
        assert result.contract_sha256 == pins["expected_contract_sha256"]
        _refuse(lambda: installation.parse_static_python_rsi_installation_descriptor(
            raw, **{**pins, "expected_contract_sha256": "a" * 64},
        ))
