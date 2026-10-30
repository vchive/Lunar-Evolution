"""Synthetic expanded inventory descriptions, not configure/build/runtime evidence."""

from __future__ import annotations

import copy
import hashlib
import json
import struct
from dataclasses import FrozenInstanceError, replace

import pytest

from lunar_evolution import static_python_fixed_profile as profile
from lunar_evolution.static_python_installation import (
    _CONFIG,
    _PRECONFIG,
    STATIC_PYTHON_FROZEN_NAMES,
)


def _sha(value: bytes | str) -> str:
    return hashlib.sha256(value.encode() if type(value) is str else value).hexdigest()


def _raw(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _closure_raw(value: dict) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


def _record(path: str, label: str, size: int = 17) -> dict:
    return {"path": path, "size": size, "sha256": _sha(label)}


def _image() -> bytes:
    """Only a synthetic bounded ELF format vector; never a CPython image."""
    data = bytearray(512)
    struct.pack_into("<16sHHIQQQIHHHHHH", data, 0,
                     b"\x7fELF\x02\x01\x01" + b"\0" * 9,
                     2, 62, 1, 0x400080, 64, 0, 0, 64, 56, 1, 0, 0, 0)
    struct.pack_into("<IIQQQQQQ", data, 64, 1, 5, 0, 0x400000, 0, 512, 512, 4096)
    return bytes(data)


def _vector(solver: str = "openevolve", count: int = 93) -> tuple[dict, dict, dict]:
    # Deliberately synthetic source/header/object digests, never actual build output.
    names = sorted((*STATIC_PYTHON_FROZEN_NAMES,
                    *(f"synthetic_module_{index:03d}" for index in range(count - 9))))
    units = [{"name": name, "generator_id": name, "package": False,
              "source": f"Lib/{name}.py", "source_size": 17,
              "source_sha256": _sha("source:" + name),
              "output": f"generated-sources/Python/frozen_modules/{name}.h"} for name in names]
    main = next(unit for unit in units if unit["name"] == "_lunar_static_main")
    main["source"] = "runtime/frozen_main.py"
    native = [{"module": f"native_{index:03d}", "source": f"Modules/native_{index}.c",
               "source_size": 17, "source_sha256": _sha(f"native-source:{index}"),
               "object": f"Modules/native_{index}.o", "extra_flags": []}
              for index in range(33 if solver == "openevolve" else 43)]
    if solver == "shinka":
        native[-1]["module"] = "sqlite-library"
    closure = {name: [] for name in profile._CLOSURE_FIELDS}
    closure.update({
        "schema": "lunar-fixed-python-runtime-source-closure-v1", "solver": solver,
        "cpython_inventory_sha256": _sha("synthetic-source-inventory"),
        "producer_manifest_sha256": profile._PRODUCERS[solver],
        "sqlite_inventory_sha256": _sha("synthetic-sqlite") if solver == "shinka" else None,
        "frozen": units, "native_units": native,
        "sources": sorted([
            _record("runtime/Modules/config.c", "synthetic-builtin-table"),
            _record("runtime/Python/frozen.c", "synthetic-frozen-table"),
            _record("runtime/Python/stdlib_module_names.h", "synthetic-stdlib-table"),
            _record("runtime/frozen_main.py", "source:_lunar_static_main"),
        ], key=lambda record: record["path"]),
        "dynamic_import_closure_verified": False, "runtime_execution_performed": False,
        "production_admission": False,
    })
    frozen = [{"name": unit["name"], "generator_id": unit["generator_id"],
               "package": unit["package"], "source": {"path": unit["source"], "size": 17,
                                                         "sha256": unit["source_sha256"]},
               "generated": _record(unit["output"], "header:" + unit["name"])} for unit in units]
    objects = [{"module": unit["module"], "source": {"path": unit["source"], "size": 17,
                                                      "sha256": unit["source_sha256"]},
                "object": _record("objects/" + unit["object"], "object:" + unit["object"]),
                "extra_flags": []} for unit in native]
    description = {
        "schema": profile.FIXED_INSTALLATION_SCHEMA, "profile_version": f"fixed-{solver}-v1",
        "installation_version": "synthetic-unaccepted-v1", "runtime_closure_sha256": _sha(_closure_raw(closure)),
        "source_inventory_sha256": closure["cpython_inventory_sha256"],
        "configuration": _record("configuration/pyconfig.h", "synthetic-unaccepted-configuration"),
        "image": {"path": "bin/lunar-" + solver, "size": 512, "sha256": _sha(_image()), "mode": 0o755},
        "frozen_modules": frozen, "native_units": objects,
        "initialization": copy.deepcopy({"preconfig": _PRECONFIG, "config": _CONFIG}),
        "claims": {name: False for name in profile._CLAIMS},
    }
    return description, closure, _pins(description, closure)


def _pins(description: dict, closure: dict) -> dict:
    return {
        "expected_installation_sha256": _sha(_raw(description)),
        "expected_installation_version": description["installation_version"],
        "expected_runtime_closure_sha256": _sha(_closure_raw(closure)),
        "expected_source_inventory_sha256": description["source_inventory_sha256"],
        "expected_configuration_sha256": description["configuration"]["sha256"],
        "expected_artifact_sha256": description["image"]["sha256"],
        "expected_frozen_inventory_sha256": _sha(_raw(description["frozen_modules"])),
        "expected_native_inventory_sha256": _sha(_raw(description["native_units"])),
    }


def _parse(description: dict, closure: dict, pins: dict):
    return profile.parse_fixed_python_installation(_raw(description), runtime_closure=_closure_raw(closure), **pins)


def _startup(installed):
    description = installed.to_dict()
    image = description["image"]
    marker = _sha("input-marker")
    payload = {
        "schema": "lunar-static-python-runtime-startup-v1",
        "installation_version": installed.installation_version,
        "build_closure_sha256": _sha("synthetic-build-description"),
        "binding_sha256": _sha("synthetic-binding"), "launch_intent_sha256": _sha("synthetic-intent"),
        "fixture_case": "baseline", "argv": [image["path"], "--lunar-rsi-input-v1", marker],
        "marker": {"name": "--lunar-rsi-input-v1", "value": marker},
        "startup": {"exit_code": 0, "module": "_lunar_static_main", "callable": "_rsi_launch",
                    "stdout_sha256": _sha("stdout"), "stderr_sha256": _sha("stderr")},
        "loader": {"pt_interp": False, "dt_needed": False, "dependencies": [],
                   "sealed_material_sha256": _sha("synthetic-sealed-material")},
        "owner": {"device": 19, "inode": 77, "mode": image["mode"],
                  "executable": {key: image[key] for key in ("path", "size", "sha256")}},
        "lifecycle": {"events": ["started", "exited"], "terminal": "exited"},
        "claims": {name: False for name in ("startup_performed", "loader_negative_verified",
                                           "owner_verified", "production_admission")},
    }
    modules = [{"name": "__main__", "origin": "interpreter", "canonical_name": "__main__"},
               {"name": "_lunar_static_main", "origin": "frozen", "canonical_name": "_lunar_static_main"},
               {"name": "sys", "origin": "built-in", "canonical_name": "sys"},
               {"name": "synthetic_module_000", "origin": "frozen", "canonical_name": "synthetic_module_000"}]
    return payload, sorted(modules, key=lambda m: m["name"])


def _compare(installed, startup, modules, **overrides):
    raw, inventory = _raw(startup), _raw(modules)
    pins = {
        "expected_installation_sha256": installed.installation_sha256,
        "expected_startup_sha256": _sha(raw), "expected_module_inventory_sha256": _sha(inventory),
        "expected_build_closure_sha256": startup["build_closure_sha256"],
        "expected_binding_sha256": startup["binding_sha256"],
        "expected_launch_intent_sha256": startup["launch_intent_sha256"],
        "expected_sealed_material_sha256": startup["loader"]["sealed_material_sha256"],
        **overrides,
    }
    return profile.compare_fixed_python_startup(installed, raw, inventory, **pins)


@pytest.mark.parametrize("solver,count,native_count", [("openevolve", 93, 33), ("shinka", 103, 43)])
def test_expanded_inventory_reaches_original_startup_without_nine_module_parser(solver, count, native_count, monkeypatch):
    description, closure, pins = _vector(solver, count)

    def old_parser_forbidden(*_args, **_kwargs):
        pytest.fail("expanded profile must not use the old nine-module parser")

    from lunar_evolution import static_python_installation as old
    monkeypatch.setattr(old, "parse_static_python_installation_descriptor", old_parser_forbidden)
    installed = _parse(description, closure, pins)
    assert len(installed.frozen_names) == count
    assert len(installed.to_dict()["native_units"]) == native_count
    assert "sqlite-library" not in installed.builtin_names
    assert all(value is False for value in installed.to_dict()["claims"].values())
    observed = profile.verify_fixed_python_image(installed, _image(), expected_installation_sha256=installed.installation_sha256)
    assert observed.sha256 == installed.artifact_sha256 and observed.production_admission is False
    startup, modules = _startup(installed)
    combined = _compare(installed, startup, modules)
    assert combined.installation == installed
    assert combined.startup.terminal == "exited"
    assert len(json.loads(combined.module_inventory_bytes)) == 4
    with pytest.raises(FrozenInstanceError):
        installed.profile_version = "changed"
    detached = installed.to_dict()
    detached["claims"]["production_admission"] = True
    assert installed.to_dict() == description


@pytest.mark.parametrize("pin", [
    "expected_installation_sha256", "expected_runtime_closure_sha256",
    "expected_source_inventory_sha256", "expected_configuration_sha256",
    "expected_artifact_sha256", "expected_frozen_inventory_sha256", "expected_native_inventory_sha256",
])
def test_every_independent_pin_disagreement_refuses(pin):
    description, closure, pins = _vector()
    pins[pin] = _sha("independent-drift")
    with pytest.raises(profile.FixedPythonProfileError):
        _parse(description, closure, pins)


@pytest.mark.parametrize("change", [
    lambda d: d.update(profile_version="fixed-shinka-v1"),
    lambda d: d["frozen_modules"].pop(),
    lambda d: d["frozen_modules"].append(d["frozen_modules"][-1]),
    lambda d: d["frozen_modules"][0]["source"].update(sha256=_sha("drift")),
    lambda d: d["frozen_modules"][0].update(package=0),
    lambda d: d["frozen_modules"][0]["generated"].update(path="wrong/header.h"),
    lambda d: d["frozen_modules"][0]["generated"].update(sha256=d["frozen_modules"][0]["source"]["sha256"]),
    lambda d: d["native_units"].pop(),
    lambda d: d["native_units"][0]["object"].update(path="wrong/object.o"),
    lambda d: d["native_units"][0].update(extra_flags=["-DUNREVIEWED=1"]),
    lambda d: d["configuration"].update(path="host/pyconfig.h"),
    lambda d: d["image"].update(mode=0o4755),
    lambda d: d["image"].update(mode=True),
    lambda d: d["image"].update(path="bin/host-python"),
    lambda d: d["initialization"]["config"].update(use_environment=True),
    lambda d: d["initialization"]["config"].update(site_import=1),
    lambda d: d["claims"].update(production_admission=True),
    lambda d: d.update(extra="unreviewed"),
])
def test_resigned_description_mutants_do_not_change_pinned_source_profile(change):
    description, closure, _ = _vector()
    change(description)
    with pytest.raises(profile.FixedPythonProfileError):
        _parse(description, closure, _pins(description, closure))


@pytest.mark.parametrize("raw", [b"", b"{}\n", b'{"schema":1,"schema":2}', b'{"x":NaN}', b'{"x":1.0}', b'{"x":"\xed\xa0\x80"}'])
def test_malformed_json_is_fixed_context_free_refusal(raw):
    _description, closure, pins = _vector()
    pins["expected_installation_sha256"] = _sha(raw)
    with pytest.raises(profile.FixedPythonProfileError) as caught:
        profile.parse_fixed_python_installation(raw, runtime_closure=_closure_raw(closure), **pins)
    assert caught.value.__context__ is None
    assert str(caught.value).startswith("static_python_fixed_profile_")


def test_same_digest_does_not_make_wrong_image_or_forged_dto_usable():
    description, closure, pins = _vector()
    installed = _parse(description, closure, pins)
    forged = replace(installed, frozen_names=("unreviewed",))
    for candidate, image in [(installed, _image()[:-1]), (forged, _image())]:
        with pytest.raises(profile.FixedPythonProfileError):
            profile.verify_fixed_python_image(candidate, image, expected_installation_sha256=installed.installation_sha256)
    invalid = b"not an ELF image".ljust(512, b"\0")
    description["image"]["sha256"] = _sha(invalid)
    installed = _parse(description, closure, _pins(description, closure))
    with pytest.raises(profile.FixedPythonProfileError, match="_elf$"):
        profile.verify_fixed_python_image(installed, invalid, expected_installation_sha256=installed.installation_sha256)


def test_empty_package_source_and_registered_alias_keep_their_exact_module_origins():
    description, closure, _ = _vector()
    item, unit = description["frozen_modules"][-1], closure["frozen"][-1]
    item["package"] = unit["package"] = True
    item["source"].update(size=0, sha256=_sha(b""))
    unit.update(source_size=0, source_sha256=_sha(b""))
    closure["runtime_module_aliases"] = [{"name": "synthetic.alias", "parent_module": "abc",
                                           "source_module": "synthetic_module_000"}]
    description["runtime_closure_sha256"] = _sha(_closure_raw(closure))
    installed = _parse(description, closure, _pins(description, closure))
    startup, modules = _startup(installed)
    modules.append({"name": "synthetic.alias", "origin": "frozen",
                    "canonical_name": "synthetic_module_000"})
    modules.sort(key=lambda module: module["name"])
    assert _compare(installed, startup, modules).installation == installed


@pytest.mark.parametrize("field", ["frozen", "native_units"])
def test_resigned_source_description_still_refuses_duplicate_inventory_identities(field):
    description, closure, _ = _vector()
    if field == "frozen":
        closure[field][1] = copy.deepcopy(closure[field][0])
        description["frozen_modules"][1] = copy.deepcopy(description["frozen_modules"][0])
    else:
        closure[field][1] = copy.deepcopy(closure[field][0])
        description[field][1] = copy.deepcopy(description[field][0])
    description["runtime_closure_sha256"] = _sha(_closure_raw(closure))
    with pytest.raises(profile.FixedPythonProfileError):
        _parse(description, closure, _pins(description, closure))


@pytest.mark.parametrize("change", [
    lambda s, m: s.update(installation_version="different-version"),
    lambda s, m: s["owner"]["executable"].update(sha256=_sha("wrong-image")),
    lambda s, m: s["owner"].update(mode=0o700),
    lambda s, m: s["claims"].update(owner_verified=True),
    lambda s, m: m[0].update(origin="source"),
    lambda s, m: m[0].update(canonical_name="unreviewed"),
    lambda s, m: m.append({"name": "unreviewed", "origin": "frozen", "canonical_name": "unreviewed"}),
    lambda s, m: m.append(m[-1]),
    lambda s, m: m.reverse(),
])
def test_startup_cannot_swap_image_profile_owner_or_module_origins(change):
    description, closure, pins = _vector()
    installed = _parse(description, closure, pins)
    startup, modules = _startup(installed)
    change(startup, modules)
    with pytest.raises(profile.FixedPythonProfileError):
        _compare(installed, startup, modules)


@pytest.mark.parametrize("pin", [
    "expected_installation_sha256", "expected_startup_sha256", "expected_module_inventory_sha256",
    "expected_build_closure_sha256", "expected_binding_sha256", "expected_launch_intent_sha256",
    "expected_sealed_material_sha256",
])
def test_startup_independent_pins_are_all_required(pin):
    description, closure, pins = _vector()
    installed = _parse(description, closure, pins)
    startup, modules = _startup(installed)
    with pytest.raises(profile.FixedPythonProfileError):
        _compare(installed, startup, modules, **{pin: _sha("drift")})
