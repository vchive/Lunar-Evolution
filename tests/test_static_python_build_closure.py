"""Focused tests for the detached F02 build-closure comparison."""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

from lunar_evolution import static_python_build_closure as closure


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _record(path: str, label: str, *, mode: int = 0o644, size: int = 8) -> dict:
    return {"path": path, "mode": mode, "size": size, "sha256": _sha(label)}


def _manifest(value: dict, field: str) -> str:
    projected = dict(value)
    projected.pop(field)
    return closure.canonical_sha256(projected)


def _vector() -> tuple[dict, bytes, dict]:
    source = {
        "source_tag": "v3.13.12", "source_commit": _sha("commit"),
        "source_git_tree": _sha("tree"), "source_archive_sha256": _sha("archive"),
        "source_tree_sha256": "0" * 64, "patch_set_sha256": _sha("patches"),
        "files": [_record("Include/Python.h", "Python.h"), _record("Python/frozen.c", "frozen")],
    }
    source["source_tree_sha256"] = _manifest(source, "source_tree_sha256")
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
    headers = []
    for index, name in enumerate((
        "_frozen_importlib", "_frozen_importlib_external", "_lunar_static_main", "abc",
        "codecs", "encodings", "encodings.aliases", "encodings.utf_8", "io",
    )):
        source_record = _record(f"Lib/{name.replace('.', '/')}.py", f"source-{name}")
        generated_record = _record(
            f"generated-sources/Python/frozen_modules/{name}.h", f"header-{name}", size=128 + index,
        )
        headers.append({
            "generator_id": name, "symbol": name.replace(".", "_"), "is_package": name == "encodings",
            "source": source_record, "generated": generated_record,
            "freezer": {"path": "Programs/_freeze_module", "recipe_sha256": _sha("freeze")},
        })
    frozen = {"inventory_sha256": "0" * 64, "headers": headers}
    frozen["inventory_sha256"] = _manifest(frozen, "inventory_sha256")
    categories = {
        "objects": [_record("Objects/abstract.o", "abstract"), _record("Python/frozen.o.new", "frozen-o")],
        "archives": [_record("libpython-core.a", "core", mode=0o644)],
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
    categories["manifest_sha256"] = _manifest(categories, "manifest_sha256")
    elf = {name: False for name in (
        "has_pt_interp", "has_dt_needed", "runtime_load_protection",
        "general_code_origin_protection", "production_admission",
    )}
    elf.update({
        "sha256": _sha("artifact"), "size": 4096, "osabi": 3, "entry_point": 4194304,
        "program_header_count": 3, "section_header_count": 4, "load_segment_count": 2,
        "executable_load_segment_count": 1, "dynamic_table_count": 0, "dynamic_entry_count": 0,
        "elf_class": 64, "byte_order": "little", "machine": "x86_64", "elf_type": "ET_EXEC",
        "artifact_sha256": _sha("artifact"), "artifact_size": 4096,
    })
    claims = {name: False for name in closure._CLAIMS}
    payload = {
        "schema": closure.BUILD_CLOSURE_SCHEMA, "installation_version": "synthetic-f02-v1",
        "source_identity": source, "toolchain_identity": toolchain, "frozen_headers": frozen,
        "link_closure": categories, "elf": elf, "claims": claims,
    }
    descriptor = {
        "installation_version": "synthetic-f02-v1", "source_tree_sha256": source["source_tree_sha256"],
        "source_archive_sha256": source["source_archive_sha256"], "artifact_sha256": elf["artifact_sha256"],
        "artifact_size": elf["artifact_size"], "elf_profile": {name: elf[name] for name in closure._ELF_FIELDS},
        "frozen_modules": [{"name": h["generator_id"], "source": h["source"], "generated": h["generated"]}
                           for h in headers],
        "recipe": {"link_inputs": [record for name in ("objects", "archives", "crt_objects", "libc_objects", "libm_objects")
                                     for record in categories[name]]},
    }
    descriptor_raw = json.dumps({"descriptor": descriptor}, sort_keys=True, separators=(",", ":")).encode()
    return payload, descriptor_raw, {
        "expected_contract_sha256": "", "expected_source_tree_sha256": source["source_tree_sha256"],
        "expected_toolchain_manifest_sha256": toolchain["manifest_sha256"],
        "expected_frozen_inventory_sha256": frozen["inventory_sha256"],
        "expected_link_manifest_sha256": categories["manifest_sha256"],
        "expected_artifact_sha256": elf["artifact_sha256"],
        "expected_installation_version": "synthetic-f02-v1", "installation_descriptor_raw": descriptor_raw,
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
    with pytest.raises(closure.StaticPythonBuildClosureError) as caught:
        _parse(payload, json.dumps(changed, sort_keys=True, separators=(",", ":")).encode(), pins)
    assert caught.value.reason.endswith("cross_field")


def test_pins_and_installation_descriptor_are_required_before_side_effects(monkeypatch):
    payload, descriptor, pins = _vector()
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()))
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()))
    result = _parse(payload, descriptor, pins)
    assert result.installation_version == "synthetic-f02-v1"
