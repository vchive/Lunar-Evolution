"""Focused tests for the detached F02 build-closure comparison."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import socket
import subprocess
import urllib.request
from pathlib import Path

import pytest
from test_static_python_rsi_installation_contract import _rehash_descriptor, reviewed_vector

from lunar_evolution import static_python_build_closure as closure
from lunar_evolution import static_python_rsi_installation as installation


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _record(path: str, label: str, *, mode: int = 0o644, size: int = 8) -> dict:
    return {"path": path, "mode": mode, "size": size, "sha256": _sha(label)}


def _manifest(value: dict, field: str) -> str:
    projected = dict(value)
    projected.pop(field)
    return hashlib.sha256(_encode(projected)).hexdigest()


def _encode(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode()


def _installation_pins(wrapper: dict) -> dict:
    descriptor = wrapper["descriptor"]
    main = next(h for h in descriptor["frozen_modules"] if h["name"] == "_lunar_static_main")
    return {
        "expected_installation_contract_sha256": hashlib.sha256(_encode(wrapper)).hexdigest(),
        "expected_installation_descriptor_sha256": hashlib.sha256(_encode(descriptor)).hexdigest(),
        "expected_installation_frozen_inventory_sha256": descriptor["frozen_inventory_sha256"],
        "expected_main_header_sha256": main["generated"]["sha256"],
    }


def _vector() -> tuple[dict, bytes, dict]:
    # Reuse the complete independently constructed reviewed F01 wire, including
    # its unchanged original installation parser. Generated records are still
    # synthetic: this establishes composition of contracts, never a build.
    wrapper = reviewed_vector.__wrapped__()
    descriptor = wrapper["descriptor"]
    provenance = descriptor["source_provenance"]
    source = {name: provenance[name] for name in (
        "source_tag", "source_commit", "source_git_tree", "source_archive_sha256", "source_tree_sha256",
    )}
    source.update(patch_set_sha256=descriptor["patch_set_sha256"], files=[
        _record("Include/Python.h", "Python.h"), _record("Python/frozen.c", "frozen"),
    ])
    toolchain = {
        "target_triple": "x86_64-linux-musl",
        "compiler": {"path": "zig/zig", "version": "0.16.0", "sha256": _sha("cc")},
        "linker": {"path": "zig/zig", "version": "0.16.0", "sha256": _sha("ld")},
        "archiver": {"path": "zig/zig", "version": "0.16.0", "sha256": _sha("ar")},
        "sysroot": {"path": "zig/libc", "version": "musl-1.2.5", "sha256": _sha("sysroot")},
        "libc": {"path": "zig/libc/musl", "version": "1.2.5", "sha256": _sha("libc")},
        "compiler_support": {"path": "zig/lib", "version": "llvm-21", "sha256": _sha("support")},
        "manifest_sha256": "0" * 64,
    }
    toolchain["manifest_sha256"] = _manifest(toolchain, "manifest_sha256")
    generators = {
        "_frozen_importlib": ("importlib._bootstrap", "_Py_M__importlib__bootstrap"),
        "_frozen_importlib_external": ("importlib._bootstrap_external", "_Py_M__importlib__bootstrap_external"),
        "_lunar_static_main": ("_lunar_static_main", "_Py_M___lunar_static_main"),
        "abc": ("abc", "_Py_M__abc"), "codecs": ("codecs", "_Py_M__codecs"),
        "encodings": ("encodings", "_Py_M__encodings"),
        "encodings.aliases": ("encodings.aliases", "_Py_M__encodings_aliases"),
        "encodings.utf_8": ("encodings.utf_8", "_Py_M__encodings_utf_8"),
        "io": ("io", "_Py_M__io"),
    }
    headers = []
    for module in descriptor["frozen_modules"]:
        generator, symbol = generators[module["name"]]
        headers.append({
            "generator_id": generator, "symbol": symbol, "is_package": module["is_package"],
            "source": {**module["source"], "mode": 0o644},
            "generated": {**module["generated"], "mode": 0o644},
            "freezer": {"path": "Programs/_freeze_module", "recipe_sha256": _sha("freeze")},
        })
    frozen = {"inventory_sha256": "0" * 64, "headers": headers}
    frozen["inventory_sha256"] = _manifest(frozen, "inventory_sha256")
    categories = {
        "objects": [{**r, "mode": 0o644} for r in descriptor["recipe"]["link_inputs"]],
        "archives": [_record("libpython-core.a", "core")],
        "crt_objects": [_record("crt/crt1.o", "crt")],
        "libc_objects": [_record("libc/libc.a", "libc")],
        "libm_objects": [_record("libm/libm.a", "libm")],
        "compile_flags": ["-fno-strict-aliasing", "-ffreestanding"],
        "link_flags": ["-static", "-Wl,--gc-sections"],
        "generated_config": _record("generated/pyconfig.h", "config"),
        "module_config": _record("generated/moduleconfig.h", "module-config"),
        "link_map": _record("generated/lunar.map", "map"),
        "excluded_stock_objects": [
            "Modules/getpath.o", "Programs/_bootstrap_python.o", "Programs/python.o", "Python/frozen.o",
        ],
        "manifest_sha256": "0" * 64,
    }
    # The F01 recipe independently pins these configuration outputs.  Keep
    # the F02 records aligned so the vector exercises the positive binding
    # path; dedicated mutations below prove drift is refused.
    categories["generated_config"]["sha256"] = descriptor["recipe"]["generated_config_sha256"]
    categories["module_config"]["sha256"] = descriptor["recipe"]["module_config_sha256"]
    categories["link_map"]["sha256"] = descriptor["recipe"]["link_map_sha256"]
    for name in ("archives", "crt_objects", "libc_objects", "libm_objects"):
        descriptor["recipe"]["link_inputs"].extend(
            {key: r[key] for key in ("path", "size", "sha256")} for r in categories[name]
        )
    descriptor["recipe"]["link_inputs"].sort(key=lambda r: r["path"])
    _rehash_descriptor(descriptor)
    categories["manifest_sha256"] = _manifest(categories, "manifest_sha256")
    elf = dict(descriptor["elf_profile"], artifact_sha256=descriptor["artifact_sha256"],
               artifact_size=descriptor["artifact_size"])
    payload = {
        "schema": closure.BUILD_CLOSURE_SCHEMA, "installation_version": descriptor["installation_version"],
        "source_identity": source, "toolchain_identity": toolchain, "frozen_headers": frozen,
        "link_closure": categories, "elf": elf, "claims": dict.fromkeys(closure._CLAIMS, False),
    }
    descriptor_raw = _encode(wrapper)
    return payload, descriptor_raw, {
        "expected_contract_sha256": "", "expected_source_tree_sha256": source["source_tree_sha256"],
        "expected_toolchain_manifest_sha256": toolchain["manifest_sha256"],
        "expected_frozen_inventory_sha256": frozen["inventory_sha256"],
        "expected_link_manifest_sha256": categories["manifest_sha256"],
        "expected_artifact_sha256": elf["artifact_sha256"],
        "expected_installation_version": descriptor["installation_version"],
        "installation_descriptor_raw": descriptor_raw, **_installation_pins(wrapper),
    }


def _parse(payload: dict, descriptor_raw: bytes, pins: dict):
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    args = dict(pins)
    args["installation_descriptor_raw"] = descriptor_raw
    args["expected_contract_sha256"] = hashlib.sha256(raw).hexdigest()
    return closure.parse_static_python_build_closure(raw, **args)


def test_valid_vector_returns_immutable_dto():
    payload, descriptor, pins = _vector()
    result = _parse(payload, descriptor, pins)
    assert result.frozen_slots == tuple(closure._FROZEN)
    assert result.to_json() == json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(AttributeError):
        result.artifact_sha256 = "x"  # type: ignore[misc]


@pytest.mark.parametrize("mutation,reason", [
    (lambda p: p["source_identity"].update(source_tree_sha256=_sha("drift")), "source_pin"),
    (lambda p: p["claims"].update(compilation_performed=True), "claims"),
    (lambda p: (p["link_closure"]["objects"].append(copy.deepcopy(p["link_closure"]["objects"][0])),
                p["link_closure"]["objects"].sort(key=lambda item: item["path"])), "duplicate_object"),
    (lambda p: (p["link_closure"]["objects"].append(_record("Python/frozen.o", "stock")),
                p["link_closure"]["objects"].sort(key=lambda item: item["path"])), "stock_objects"),
    (lambda p: p["frozen_headers"]["headers"].pop(), "frozen_inventory"),
    (lambda p: p["elf"].update(has_pt_interp=True), "elf"),
])
def test_mutations_refuse(mutation, reason):
    payload, descriptor, pins = _vector()
    mutation(payload)
    with pytest.raises(closure.StaticPythonBuildClosureError) as caught:
        _parse(payload, descriptor, pins)
    assert caught.value.reason == "static_python_build_closure_" + reason


def test_duplicate_json_key_and_noncanonical_refuse():
    payload, _descriptor, pins = _vector()
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).replace(
        '"schema":', '"schema":', 1,
    )
    duplicate = (raw[:-1] + ',"schema":"' + closure.BUILD_CLOSURE_SCHEMA + '"}').encode()
    pins = dict(pins, expected_contract_sha256=hashlib.sha256(duplicate).hexdigest())
    with pytest.raises(closure.StaticPythonBuildClosureError) as caught:
        closure.parse_static_python_build_closure(duplicate, **pins)
    assert caught.value.reason.endswith("duplicate_key")


def test_descriptor_cross_field_drift_refuses():
    payload, descriptor, pins = _vector()
    changed = json.loads(descriptor.decode())
    changed["descriptor"]["artifact_size"] += 1
    changed["descriptor"]["elf_profile"]["size"] += 1
    pins.update(_installation_pins(changed))
    with pytest.raises(closure.StaticPythonBuildClosureError) as caught:
        _parse(payload, json.dumps(changed, sort_keys=True, separators=(",", ":")).encode(), pins)
    assert caught.value.reason.endswith("cross_field")


@pytest.mark.parametrize("field", [
    "generated_config_sha256", "module_config_sha256", "link_map_sha256",
])
def test_configuration_artifact_digest_is_bound_to_f01_recipe(field):
    payload, descriptor, pins = _vector()
    changed = json.loads(descriptor.decode())
    changed["descriptor"]["recipe"][field] = _sha("configuration drift")
    _rehash_descriptor(changed["descriptor"])
    changed_raw = _encode(changed)
    pins.update(_installation_pins(changed))
    _refuse(lambda: _parse(payload, changed_raw, pins), "cross_field")


def test_pins_and_installation_descriptor_are_required_before_side_effects(monkeypatch):
    payload, descriptor, pins = _vector()
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()))
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()))
    result = _parse(payload, descriptor, pins)
    assert result.installation_version == "synthetic-rsi-metadata-v1"


def _refuse(operation, reason=None):
    with pytest.raises(closure.StaticPythonBuildClosureError) as caught:
        operation()
    error = caught.value
    assert error.reason.removeprefix("static_python_build_closure_") in closure._REASONS
    assert error.args == (error.reason,)
    assert error.__cause__ is None
    assert error.__context__ is None
    if reason is not None:
        assert error.reason == "static_python_build_closure_" + reason
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


class _HostileDict(dict):
    __iter__ = _bomb
    keys = _bomb
    items = _bomb
    values = _bomb


def _resign_section(payload, pins, section, field, pin):
    payload[section][field] = _manifest(payload[section], field)
    pins[pin] = payload[section][field]


def test_complete_f01_composes_with_real_git_ids_and_reviewed_freeze_identity():
    payload, raw, pins = _vector()
    f01 = installation.parse_static_python_rsi_installation_descriptor(
        raw, expected_contract_sha256=pins["expected_installation_contract_sha256"],
        expected_descriptor_sha256=pins["expected_installation_descriptor_sha256"],
        expected_installation_version=pins["expected_installation_version"],
        expected_artifact_sha256=pins["expected_artifact_sha256"],
        expected_frozen_inventory_sha256=pins["expected_installation_frozen_inventory_sha256"],
        expected_main_header_sha256=pins["expected_main_header_sha256"],
    )
    result = _parse(payload, raw, pins)
    assert result.installation_version == f01.installation_version
    assert len(payload["source_identity"]["source_commit"]) == 40
    assert len(payload["source_identity"]["source_git_tree"]) == 40
    assert payload["source_identity"]["source_tree_sha256"] != _manifest(
        payload["source_identity"], "source_tree_sha256",
    )
    assert [h["generator_id"] for h in payload["frozen_headers"]["headers"][:2]] == [
        "importlib._bootstrap", "importlib._bootstrap_external",
    ]
    assert all(not value for value in result.to_dict()["claims"].values())
    assert json.loads(raw)["descriptor"]["production_admission"] is False


@pytest.mark.parametrize("pin", closure._PIN_FIELDS)
def test_each_external_digest_pin_is_independent_and_required(pin):
    payload, raw, pins = _vector()
    pins[pin] = _sha("different independent pin")
    # _parse deliberately supplies the current F02 contract pin, so exercise
    # that pin directly as well as the independently retained F01 pins.
    if pin == "expected_contract_sha256":
        _refuse(lambda: closure.parse_static_python_build_closure(_encode(payload), **pins))
    else:
        _refuse(lambda: _parse(payload, raw, pins))
    pins.pop(pin)
    with pytest.raises(TypeError):
        closure.parse_static_python_build_closure(_encode(payload), **pins)


@pytest.mark.parametrize("pin", (*closure._PIN_FIELDS, "expected_installation_version"))
@pytest.mark.parametrize("bad", [None, True, b"caller secret",
                                 pytest.param(_HostileString("caller-secret"), id="hostile-string")])
def test_pin_types_refuse_before_hash_parse_or_f01_delegation(monkeypatch, pin, bad):
    payload, _, pins = _vector()
    raw = _encode(payload)
    pins["expected_contract_sha256"] = hashlib.sha256(raw).hexdigest()
    pins[pin] = bad
    monkeypatch.setattr(closure.json, "loads", _bomb)
    monkeypatch.setattr(closure.hashlib, "sha256", _bomb)
    monkeypatch.setattr(closure, "parse_static_python_rsi_installation_descriptor", _bomb)
    _refuse(lambda: closure.parse_static_python_build_closure(raw, **pins), "pin")


@pytest.mark.parametrize("bad", [None, True, "secret", bytearray(b"{}"),
                                 pytest.param(_HostileBytes(b"caller secret"), id="hostile-bytes"),
                                 b"", b" " * (384 * 1024 + 1)])
def test_installation_wire_type_and_bounds_precede_parsing(monkeypatch, bad):
    payload, _, pins = _vector()
    raw = _encode(payload)
    pins["expected_contract_sha256"] = hashlib.sha256(raw).hexdigest()
    pins["installation_descriptor_raw"] = bad
    monkeypatch.setattr(closure.json, "loads", _bomb)
    monkeypatch.setattr(closure.hashlib, "sha256", _bomb)
    monkeypatch.setattr(closure, "parse_static_python_rsi_installation_descriptor", _bomb)
    _refuse(lambda: closure.parse_static_python_build_closure(raw, **pins), "installation_descriptor")


@pytest.mark.parametrize("mutant", ["partial-wrapper", "bare-descriptor", "frozen-scalar",
                                    "recipe-scalar", "bool-elf", "bool-file", "unknown-field"])
def test_invalid_f01_refuses_even_when_caller_pins_are_resigned(mutant):
    payload, raw, pins = _vector()
    wrapper = json.loads(raw)
    if mutant == "partial-wrapper":
        wrapper = {"descriptor": wrapper["descriptor"]}
    elif mutant == "bare-descriptor":
        wrapper = wrapper["descriptor"]
    elif mutant == "frozen-scalar":
        wrapper["descriptor"]["frozen_modules"][0] = 1
    elif mutant == "recipe-scalar":
        wrapper["descriptor"]["recipe"] = 1
    elif mutant == "bool-elf":
        payload["elf"]["entry_point"] = 1
        wrapper["descriptor"]["elf_profile"]["entry_point"] = True
    elif mutant == "bool-file":
        payload["frozen_headers"]["headers"][0]["generated"]["size"] = 1
        wrapper["descriptor"]["frozen_modules"][0]["generated"]["size"] = True
        _rehash_descriptor(wrapper["descriptor"])
        _resign_section(payload, pins, "frozen_headers", "inventory_sha256", "expected_frozen_inventory_sha256")
    else:
        wrapper["caller-secret"] = "private operator material"
    raw = _encode(wrapper)
    if mutant not in {"partial-wrapper", "bare-descriptor", "frozen-scalar", "recipe-scalar"}:
        pins.update(_installation_pins(wrapper))
    pins["expected_installation_contract_sha256"] = hashlib.sha256(raw).hexdigest()
    _refuse(lambda: _parse(payload, raw, pins), "installation_descriptor")


@pytest.mark.parametrize("mutation", [
    lambda w: w["descriptor"]["frozen_modules"][0]["source"].update(size=True),
    lambda w: w["descriptor"]["frozen_modules"][0]["generated"].update(size=True),
    lambda w: w["descriptor"]["elf_profile"].update(program_header_count=True),
])
def test_descriptor_bools_cannot_equal_integer_one(mutation):
    payload, raw, pins = _vector()
    wrapper = json.loads(raw)
    # Former ordinary != comparisons accepted bool as int 1. Validating the
    # complete F01 descriptor now refuses the type, even after digest updates.
    payload["frozen_headers"]["headers"][0]["source"]["size"] = 1
    payload["frozen_headers"]["headers"][0]["generated"]["size"] = 1
    mutation(wrapper)
    _rehash_descriptor(wrapper["descriptor"])
    pins.update(_installation_pins(wrapper))
    _resign_section(payload, pins, "frozen_headers", "inventory_sha256", "expected_frozen_inventory_sha256")
    _refuse(lambda: _parse(payload, _encode(wrapper), pins), "installation_descriptor")


@pytest.mark.parametrize("raw", [b"{", b"\xff", b"null", b"[]", b'{"caller-secret":NaN}',
                                 b'{"caller-secret":1,"caller-secret":2}',
                                 b'{"outer":{"caller-secret":1,"caller-secret":2}}',
                                 b'{"caller-secret":"\\ud800"}',
                                 b'{"extra":' + b'[' * 50 + b'1' + b']' * 50 + b'}'])
def test_malformed_f01_json_nesting_and_duplicates_have_context_free_errors(raw):
    payload, _, pins = _vector()
    pins["expected_installation_contract_sha256"] = hashlib.sha256(raw).hexdigest()
    _refuse(lambda: _parse(payload, raw, pins), "installation_descriptor")


@pytest.mark.parametrize("encoding", ["indent", "unsorted", "trailing", "escaped"])
def test_noncanonical_f01_is_never_repaired(encoding):
    payload, raw, pins = _vector()
    wrapper = json.loads(raw)
    if encoding == "indent":
        raw = json.dumps(wrapper, sort_keys=True, indent=2).encode()
    elif encoding == "unsorted":
        wrapper = {key: wrapper[key] for key in reversed(wrapper)}
        raw = json.dumps(wrapper, separators=(",", ":")).encode()
    elif encoding == "trailing":
        raw += b"\n"
    else:
        raw = raw.replace(b'"rsi-marker-launch-v1"', b'"\\u0072si-marker-launch-v1"')
    pins["expected_installation_contract_sha256"] = hashlib.sha256(raw).hexdigest()
    _refuse(lambda: _parse(payload, raw, pins), "installation_descriptor")


@pytest.mark.parametrize("field,bad", [
    ("sha256", "not-a-sha"), ("sha256", _sha("different ELF")), ("elf_class", 32),
    ("machine", "arm"), ("byte_order", "big"), ("elf_type", "ET_DYN"), ("osabi", 2),
    ("entry_point", -1), ("entry_point", 0), ("entry_point", 2**64),
    ("program_header_count", 0), ("program_header_count", 257),
    ("section_header_count", -1), ("section_header_count", 4097),
    ("load_segment_count", -5), ("load_segment_count", 2),
    ("executable_load_segment_count", 0), ("executable_load_segment_count", 2),
    ("dynamic_table_count", -1), ("dynamic_table_count", 4353),
    ("dynamic_entry_count", 1), ("dynamic_entry_count", 4097),
])
def test_strict_elf_profile_rejects_matching_invalid_descriptor_fields(field, bad):
    payload, raw, pins = _vector()
    wrapper = json.loads(raw)
    payload["elf"][field] = bad
    wrapper["descriptor"]["elf_profile"][field] = bad
    pins.update(_installation_pins(wrapper))
    _refuse(lambda: _parse(payload, _encode(wrapper), pins), "elf")


def test_dynamic_tables_require_a_positive_entry_count():
    payload, raw, pins = _vector()
    payload["elf"].update(dynamic_table_count=1, dynamic_entry_count=0)
    _refuse(lambda: _parse(payload, raw, pins), "elf")


@pytest.mark.parametrize("field", closure._ELF_FIELDS)
def test_every_elf_field_keeps_its_exact_builtin_type(field):
    payload, raw, pins = _vector()
    current = payload["elf"][field]
    payload["elf"][field] = 0 if type(current) is bool else True
    _refuse(lambda: _parse(payload, raw, pins), "elf")


@pytest.mark.parametrize("index", range(9))
@pytest.mark.parametrize("field", ["symbol", "is_package", "generated_path"])
def test_every_reviewed_freeze_identity_refuses_resigned_drift(index, field):
    payload, raw, pins = _vector()
    header = payload["frozen_headers"]["headers"][index]
    if field == "symbol":
        header["symbol"] = "different_symbol"
    elif field == "is_package":
        header["is_package"] = not header["is_package"]
    else:
        header["generated"]["path"] = "generated-sources/Python/frozen_modules/wrong.h"
    _resign_section(payload, pins, "frozen_headers", "inventory_sha256", "expected_frozen_inventory_sha256")
    _refuse(lambda: _parse(payload, raw, pins), "frozen_header")


@pytest.mark.parametrize("field", ["source_commit", "source_git_tree"])
@pytest.mark.parametrize("bad", [_sha("fake sha256 git id"), "0" * 40, "f" * 40, "A" * 40, True])
def test_git_object_ids_are_exact_lowercase_sha1_ids(field, bad):
    payload, raw, pins = _vector()
    payload["source_identity"][field] = bad
    _refuse(lambda: _parse(payload, raw, pins), "source")


@pytest.mark.parametrize("field", ["source_commit", "source_git_tree", "source_archive_sha256",
                                  "patch_set_sha256", "source_tree_sha256"])
def test_source_identity_must_match_validated_f01(field):
    payload, raw, pins = _vector()
    payload["source_identity"][field] = "a" * (40 if field in {"source_commit", "source_git_tree"} else 64)
    if field == "source_tree_sha256":
        pins["expected_source_tree_sha256"] = payload["source_identity"][field]
    _refuse(lambda: _parse(payload, raw, pins), "cross_field")


def test_frozen_records_must_match_validated_f01_after_inventory_resigning():
    payload, raw, pins = _vector()
    payload["frozen_headers"]["headers"][0]["generated"]["sha256"] = _sha("drift")
    _resign_section(payload, pins, "frozen_headers", "inventory_sha256", "expected_frozen_inventory_sha256")
    _refuse(lambda: _parse(payload, raw, pins), "cross_field")


def test_f01_delegate_errors_are_fixed_and_context_free(monkeypatch):
    payload, raw, pins = _vector()

    def fail(*_args, **_kwargs):
        error = installation.StaticPythonRSIInstallationError("json")
        error.args = ("private caller /secret/key",)
        raise error

    monkeypatch.setattr(closure, "parse_static_python_rsi_installation_descriptor", fail)
    error = _refuse(lambda: _parse(payload, raw, pins), "installation_descriptor")
    assert "secret" not in repr(error)


@pytest.mark.parametrize("value", [object(), _HostileDict(secret="private material"),
                                   pytest.param(_HostileString("caller secret"), id="hostile-string"),
                                   "\ud800", float("nan"),
                                   "s" * (closure._MAX_TEXT_BYTES + 1),
                                   [[[[[[[[[[[[[[[[[[1]]]]]]]]]]]]]]]]]],
                                   [1] * (closure._MAX_NODES + 1)])
def test_public_canonical_hash_errors_are_fixed_without_caller_context(value):
    _refuse(lambda: closure.canonical_sha256(value), "canonical")


def test_error_constructor_does_not_reveal_unrecognized_reason():
    error = closure.StaticPythonBuildClosureError("private-caller-credentials")
    assert str(error) == "static_python_build_closure_invalid"


def test_public_canonical_hash_preserves_exact_integer_precision():
    first = {"nested": [False, "value", 2**53]}
    second = {"nested": [False, "value", 2**53 + 1]}
    assert closure.canonical_sha256(first) == hashlib.sha256(_encode(first)).hexdigest()
    assert closure.canonical_sha256(second) == hashlib.sha256(_encode(second)).hexdigest()
    assert closure.canonical_sha256(first) != closure.canonical_sha256(second)


def test_elf_entrypoint_preserves_large_integer_precision_across_f01():
    payload, raw, pins = _vector()
    wrapper = json.loads(raw)
    payload["elf"]["entry_point"] = 2**53 + 1
    wrapper["descriptor"]["elf_profile"]["entry_point"] = 2**53 + 1
    pins.update(_installation_pins(wrapper))
    raw = _encode(wrapper)
    assert _parse(payload, raw, pins).to_dict()["elf"]["entry_point"] == 2**53 + 1
    payload["elf"]["entry_point"] = 2**53
    _refuse(lambda: _parse(payload, raw, pins), "cross_field")


@pytest.mark.parametrize("raw", [b"{", b"\xff", b"null", b"[]", b"true", b"1",
                                 b'{"caller-secret":1.0}', b'{"caller-secret":NaN}',
                                 b'{"caller-secret":"\\ud800"}',
                                 b'{"extra":' + b'[' * 50 + b'1' + b']' * 50 + b'}'])
def test_malformed_closure_errors_are_context_free(raw):
    _, _, pins = _vector()
    pins["expected_contract_sha256"] = hashlib.sha256(raw).hexdigest()
    _refuse(lambda: closure.parse_static_python_build_closure(raw, **pins))


@pytest.mark.parametrize("bad", [None, True, "caller-secret", bytearray(b"{}"),
                                 pytest.param(_HostileBytes(b"secret"), id="hostile-bytes"),
                                 b"", b" " * (512 * 1024 + 1)])
def test_closure_wire_preflight_refuses_before_any_parser_or_hash(monkeypatch, bad):
    payload, _, pins = _vector()
    pins["expected_contract_sha256"] = hashlib.sha256(_encode(payload)).hexdigest()
    monkeypatch.setattr(closure.json, "loads", _bomb)
    monkeypatch.setattr(closure.hashlib, "sha256", _bomb)
    monkeypatch.setattr(closure, "parse_static_python_rsi_installation_descriptor", _bomb)
    _refuse(lambda: closure.parse_static_python_build_closure(bad, **pins), "raw")


class _ForbiddenEnvironment(dict):
    __getitem__ = _bomb
    __iter__ = _bomb
    __contains__ = _bomb
    get = _bomb
    keys = _bomb
    items = _bomb
    values = _bomb


def test_composed_success_and_refusal_have_no_external_effects(monkeypatch):
    payload, raw, pins = _vector()
    with monkeypatch.context() as patch:
        patch.setattr("builtins.open", _bomb)
        for method in ("open", "read_bytes", "write_bytes", "stat"):
            patch.setattr(Path, method, _bomb)
        patch.setattr(os, "getenv", _bomb)
        patch.setattr(os, "environ", _ForbiddenEnvironment())
        patch.setattr(socket, "socket", _bomb)
        patch.setattr(socket, "getaddrinfo", _bomb)
        patch.setattr(subprocess, "run", _bomb)
        patch.setattr(subprocess, "Popen", _bomb)
        patch.setattr(subprocess, "check_output", _bomb)
        patch.setattr(urllib.request, "urlopen", _bomb)
        result = _parse(payload, raw, pins)
        assert result.to_dict()["claims"]["production_admission"] is False
        _refuse(lambda: _parse(payload, raw, {**pins, "expected_main_header_sha256": _sha("drift")}))
