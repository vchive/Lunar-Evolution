"""Official socket/types sources remain inert data; no upstream code executes."""

from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path

import pytest
from test_static_python_concrete_recipe import (
    concrete_inputs as concrete_inputs,  # noqa: PLC0414 - pytest fixture re-export
)
from test_static_python_fixed_runtime_closure import (
    closure_inputs as closure_inputs,  # noqa: PLC0414 - pytest fixture re-export
)
from test_static_python_fixed_runtime_closure import refresh_cpython_pin

from tools.static_python_rsi_fixture import concrete_recipe as concrete
from tools.static_python_rsi_fixture import runtime_closure as closure
from tools.static_python_rsi_fixture.build_driver import _preparation_wire

_FIXTURE = Path(__file__).parent / "fixtures/static_python_socket_source"
_TYPES_SHA256 = "877abbfdfce63bbdb27c5e57e2cabb48a8e8394dfad734fefd7dd9cfde01d6f3"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def fixture(path):
    return (_FIXTURE / (path + ".source")).read_bytes()


def test_capsule_type_is_a_real_lazy_attribute_dependency_not_an_eager_import():
    raw = fixture("Lib/types.py")
    assert sha(raw) == _TYPES_SHA256
    tree = ast.parse(raw)
    getter = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                  and node.name == "__getattr__")
    branch = getter.body[0]
    assert isinstance(branch, ast.If)
    assert branch.test.comparators[0].value == "CapsuleType"
    assert isinstance(branch.body[0], ast.Import)
    assert branch.body[0].names[0].name == "_socket"
    assert ast.unparse(branch.body[1].value) == "type(_socket.CAPI)"
    assert not any(isinstance(node, ast.Import) and any(alias.name == "_socket"
                   for alias in node.names) for node in tree.body)
    edges = closure._imports(raw, "types", False, set(), {"_socket"}, [], [])
    assert "_socket" in edges
    assert "_socket" not in closure._ABSENT
    assert "_ssl" in closure._ABSENT


def test_direct_quoted_and_clinic_inputs_are_complete_official_source_pins():
    paths = set(closure._SOCKET_INPUTS)
    for path, (size, digest) in closure._SOCKET_INPUTS.items():
        raw = fixture(path)
        assert (len(raw), sha(raw)) == (size, digest)
    for source in ("Modules/socketmodule.c", "Modules/clinic/socketmodule.c.h"):
        names = re.findall(rb'^\s*#\s*include\s*"([^"\n]+)"', fixture(source), re.MULTILINE)
        for name in names:
            value = name.decode("ascii")
            candidates = {"Modules/" + value, "Include/" + value, "Include/internal/" + value}
            assert len(candidates & paths) == 1
    assert {"Modules/getaddrinfo.c", "Modules/getnameinfo.c"} <= paths


def test_closure_retains_real_native_capsule_provider_and_unchanged_types(closure_inputs):
    args = closure_inputs
    args["cpython_sources"].update({
        "Lib/json/decoder.py": b"from types import CapsuleType\n",
        "Lib/types.py": fixture("Lib/types.py"),
        "Lib/functools.py": b"pass\n",
        "Lib/_collections_abc.py": b"pass\n",
    })
    refresh_cpython_pin(args)
    before = dict(args["cpython_sources"])
    result = closure.prepare_fixed_runtime_closure(**args)
    facts = json.loads(result.wire_bytes)
    assert args["cpython_sources"] == before
    units = [unit for unit in facts["native_units"] if unit["module"] == "_socket"]
    size, digest = closure._SOCKET_INPUTS["Modules/socketmodule.c"]
    assert units == [{"module": "_socket", "source": "Modules/socketmodule.c",
                      "object": "Modules/socketmodule.o", "source_size": size,
                      "source_sha256": digest, "extra_flags": []}]
    assert "_socket" not in facts["guarded_absent_imports"]
    frozen = {item["name"]: item for item in facts["frozen"]}
    assert frozen["types"]["source_sha256"] == _TYPES_SHA256
    assert "_socket" not in frozen
    assert "_ssl" not in {unit["module"] for unit in facts["native_units"]}
    assert b'{"_socket", PyInit__socket},' in dict(result.sources)["runtime/Modules/config.c"]
    assert {item["source"] for item in facts["native_header_inputs"]
            if item["module"] == "_socket"} == {
        path for path in closure._SOCKET_INPUTS if path.endswith(".h")
    }
    assert facts["runtime_execution_performed"] is False
    assert facts["dynamic_import_closure_verified"] is False
    assert facts["production_admission"] is False
    assert "configuration/pyconfig.h" not in dict(result.sources)


@pytest.mark.parametrize("path", list(closure._SOCKET_INPUTS))
@pytest.mark.parametrize("mutation", ["missing", "drift"])
def test_real_socket_c_and_every_direct_input_remain_required(closure_inputs, path, mutation):
    if mutation == "missing":
        del closure_inputs["cpython_sources"][path]
    else:
        closure_inputs["cpython_sources"][path] += b"/* drift */\n"
    refresh_cpython_pin(closure_inputs)
    # Python.h/fileutils/modsupport are also original subprocess dependencies.
    code = "posixsubprocess_input_pin_mismatch" if path in closure._POSIXSUBPROCESS_INPUTS else "socket_input_pin_mismatch"
    with pytest.raises(closure.RuntimeClosureError, match=code):
        closure.prepare_fixed_runtime_closure(**closure_inputs)


@pytest.mark.parametrize("path,before,after", [
    ("Modules/socketmodule.c", b"PyInit__socket(void)", b"PyInit__replacement(void)"),
    ("Modules/socketmodule.c", b"PyObject *capsule = PyCapsule_New(capi,", b"PyObject *capsule = FakeCapsule_New(capi,"),
    ("Modules/socketmodule.c", b"PyModule_Add(m, PySocket_CAPI_NAME, capsule)", b"PyModule_Add(m, Fake_CAPI_NAME, capsule)"),
    ("Modules/socketmodule.h", b'#define PySocket_MODULE_NAME    "_socket"', b'#define PySocket_MODULE_NAME    "replacement"'),
    ("Modules/clinic/socketmodule.c.h", b"return_value = sock_initobj_impl(", b"return_value = fake_initobj_impl("),
])
def test_real_initializer_capsule_and_clinic_anchors_are_verified(closure_inputs, monkeypatch, path, before, after):
    original = closure_inputs["cpython_sources"][path]
    assert before in original
    raw = original.replace(before, after, 1)
    closure_inputs["cpython_sources"][path] = raw
    monkeypatch.setitem(closure._SOCKET_INPUTS, path, (len(raw), sha(raw)))
    refresh_cpython_pin(closure_inputs)
    with pytest.raises(closure.RuntimeClosureError, match="socket_initializer_invalid"):
        closure.prepare_fixed_runtime_closure(**closure_inputs)


def socket_recipe_input(concrete_inputs):
    prep, args = concrete_inputs
    plan = _preparation_wire(prep)["candidate_build_inputs"]
    generated = {
        "runtime/Modules/config.c": b"/* synthetic source-only table, never compiled */\n",
        "runtime/Python/frozen.c": b"/* synthetic frozen table */\n",
        "runtime/Python/stdlib_module_names.h": b"/* synthetic names */\n",
        "runtime/frozen_main.py": b"def _rsi_launch(x): pass\n",
    }
    tasks = [dict(item) for item in plan["freeze_tasks"]]
    tasks[-1].update(source="runtime/frozen_main.py", source_size=len(generated["runtime/frozen_main.py"]),
                     source_sha256=sha(generated["runtime/frozen_main.py"]))
    size, digest = closure._SOCKET_INPUTS["Modules/socketmodule.c"]
    facts = {
        "schema": "lunar-fixed-python-runtime-source-closure-v1", "solver": "openevolve",
        "production_admission": False, "runtime_execution_performed": False,
        "native_units": [{"module": "_socket", "source": "Modules/socketmodule.c",
                          "object": "Modules/socketmodule.o", "source_size": size,
                          "source_sha256": digest, "extra_flags": []}],
        "frozen": tasks, "sources": [{"path": path, "size": len(raw), "sha256": sha(raw)}
                                     for path, raw in sorted(generated.items())],
    }
    entries = {item["path"]: item for item in json.loads(args["source_inventory_bytes"])}
    for path, (size, digest) in closure._SOCKET_INPUTS.items():
        entries[path] = {"path": path, "size": size, "sha256": digest, "executable": False}
    # Explicit inert inventory input for the existing native include-directory
    # graph. This is synthetic recipe validation, never an accepted C header.
    entries["Modules/_hacl/include/fixture.h"] = {
        "path": "Modules/_hacl/include/fixture.h", "size": 1,
        "sha256": sha(b"x"), "executable": False,
    }
    args["source_inventory_bytes"] = closure.canonical([entries[path] for path in sorted(entries)])
    args["expected_source_inventory_sha256"] = sha(args["source_inventory_bytes"])
    value = closure.FixedRuntimeClosure(closure.canonical(facts), tuple(sorted(generated.items())))
    return prep, args, value


def test_recipe_retains_real_socket_unit_and_no_extra_libs_or_execution_claim(concrete_inputs):
    prep, args, value = socket_recipe_input(concrete_inputs)
    result = concrete.prepare_cpython_build_recipe(prep, **args, runtime_closure=value)
    commands = [command for stage in json.loads(result.recipe_bytes)["stages"] for command in stage["commands"]]
    assert any("@source/Modules/socketmodule.c" in command["argv"] for command in commands)
    assert not any(arg in {"-lssl", "-lcrypto", "-lnsl", "-lresolv"} for command in commands for arg in command["argv"])
    facts = json.loads(result.manifest_bytes)
    assert facts["build_performed"] is False
    assert facts["production_admission"] is False
    assert facts["configured_closure_verified"] is False
    assert dict(result.sources)["configuration/pyconfig.h"] == args["configuration_header"]


@pytest.mark.parametrize("path", list(closure._SOCKET_INPUTS))
@pytest.mark.parametrize("mutation", ["missing", "digest", "size", "executable"])
def test_recipe_independently_rejects_every_socket_direct_input_drift(concrete_inputs, path, mutation):
    prep, args, value = socket_recipe_input(concrete_inputs)
    records = json.loads(args["source_inventory_bytes"])
    entry = next(item for item in records if item["path"] == path)
    if mutation == "missing":
        records.remove(entry)
    elif mutation == "digest":
        entry["sha256"] = sha(b"fake input")
    elif mutation == "size":
        entry["size"] += 1
    else:
        entry["executable"] = True
    args["source_inventory_bytes"] = closure.canonical(records)
    args["expected_source_inventory_sha256"] = sha(args["source_inventory_bytes"])
    with pytest.raises(concrete.ConcreteRecipeError, match="socket_input_pin_mismatch"):
        concrete.prepare_cpython_build_recipe(prep, **args, runtime_closure=value)


@pytest.mark.parametrize("mutation", ["source", "object", "source_size", "source_sha256", "extra_flags", "duplicate"])
def test_recipe_independently_rejects_resigned_socket_unit_substitution(concrete_inputs, mutation):
    prep, args, value = socket_recipe_input(concrete_inputs)
    facts = json.loads(value.wire_bytes)
    unit = facts["native_units"][0]
    if mutation == "source_size":
        unit[mutation] += 1
    elif mutation == "extra_flags":
        unit[mutation] = ["-DHOST_NETWORK=1"]
    elif mutation == "duplicate":
        facts["native_units"].append(unit.copy())
    else:
        unit[mutation] = "0" * 64 if mutation == "source_sha256" else "Modules/replacement.c"
    value = closure.FixedRuntimeClosure(closure.canonical(facts), value.sources)
    with pytest.raises(concrete.ConcreteRecipeError, match="socket_input_pin_mismatch"):
        concrete.prepare_cpython_build_recipe(prep, **args, runtime_closure=value)
