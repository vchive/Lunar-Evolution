"""Official sources are inert fixtures; no upstream Python/C or process executes."""

from __future__ import annotations

import hashlib
import json
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

_FIXTURE = Path(__file__).parent / "fixtures/static_python_subprocess_source"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def subprocess_source():
    return (_FIXTURE / "Lib/subprocess.py.source").read_bytes()


def subprocess_edges(raw=None, *, module="subprocess", available=(), builtin=()):
    evidence = []
    edges = closure._imports(subprocess_source() if raw is None else raw, module, False,
                             set(available), set(builtin), [], [], platform_guards=evidence)
    return edges, evidence


def add_subprocess(args):
    args["cpython_sources"]["Lib/json/decoder.py"] = b"import subprocess\n"
    args["cpython_sources"]["Lib/subprocess.py"] = subprocess_source()
    for name in ("os", "locale", "signal", "threading", "warnings", "contextlib", "types", "selectors"):
        args["cpython_sources"]["Lib/" + name + ".py"] = b"pass\n"
    refresh_cpython_pin(args)


def test_complete_official_source_proves_only_actual_missing_msvcrt_branch():
    raw = subprocess_source()
    assert sha(raw) == closure._SUBPROCESS_SOURCE_SHA256
    edges, evidence = subprocess_edges()
    assert {"msvcrt", "_posixsubprocess", "fcntl", "select", "selectors", "pwd", "grp"} <= edges
    assert "_winapi" not in edges
    assert len(evidence) == 1
    assert evidence[0] == {
        "module": "subprocess", "module_source_sha256": sha(raw), "flag": "_mswindows",
        "value": False, "import": "msvcrt",
        "guard": "top-level-try-import-except-ModuleNotFoundError-false-else-true",
        "guard_lineno": 70, "binding_end_lineno": 75, "dynamic_reflection_verified": False,
    }


@pytest.mark.parametrize("raw", [
    b"_mswindows = False\nif _mswindows:\n    import _winapi\n",
    subprocess_source() + b"# source drift\n",
    subprocess_source().replace(b"except ModuleNotFoundError:", b"except ImportError:", 1),
])
def test_subprocess_branch_proof_requires_complete_original_source(raw):
    with pytest.raises(closure.RuntimeClosureError, match="subprocess_platform_source_drift"):
        subprocess_edges(raw)


@pytest.mark.parametrize("replacement", [
    b"import msvcrt as replacement", b"import nonexistent", b"_mswindows = True",
])
def test_repinning_synthetic_probe_cannot_bypass_guard_shape(monkeypatch, replacement):
    raw = subprocess_source().replace(b"import msvcrt", replacement, 1)
    monkeypatch.setattr(closure, "_SUBPROCESS_SOURCE_SHA256", sha(raw))
    with pytest.raises(closure.RuntimeClosureError, match="subprocess_platform_guard_invalid"):
        subprocess_edges(raw)


@pytest.mark.parametrize("change", [
    b"_mswindows = False\n", b"del _mswindows\n",
    b"def changed(_mswindows): pass\n", b"import sys as _mswindows\n",
])
def test_flag_rebinding_is_refused_even_with_a_synthetic_pin(monkeypatch, change):
    raw = subprocess_source() + change
    monkeypatch.setattr(closure, "_SUBPROCESS_SOURCE_SHA256", sha(raw))
    with pytest.raises(closure.RuntimeClosureError, match="subprocess_platform_guard_invalid"):
        subprocess_edges(raw)


@pytest.mark.parametrize("field", ["available", "builtin"])
def test_fake_msvcrt_source_or_builtin_invalidates_missing_module_proof(field):
    with pytest.raises(closure.RuntimeClosureError, match="subprocess_platform_module_conflict"):
        subprocess_edges(**{field: {"msvcrt"}})


def test_msvcrt_must_remain_deliberately_absent_from_the_fixed_profile(monkeypatch):
    monkeypatch.setattr(closure, "_ABSENT", closure._ABSENT - {"msvcrt"})
    with pytest.raises(closure.RuntimeClosureError, match="subprocess_platform_module_conflict"):
        subprocess_edges()


def test_flag_spelling_in_other_module_never_grants_platform_proof():
    with pytest.raises(closure.RuntimeClosureError, match="unguarded_absent_import"):
        subprocess_edges(module="unreviewed_module")


def test_complete_closure_retains_actual_posix_native_unit_and_raw_python_source(closure_inputs):
    add_subprocess(closure_inputs)
    original = dict(closure_inputs["cpython_sources"])
    result = closure.prepare_fixed_runtime_closure(**closure_inputs)
    facts = json.loads(result.wire_bytes)
    assert closure_inputs["cpython_sources"] == original
    unit = [item for item in facts["native_units"] if item["module"] == "_posixsubprocess"]
    assert len(unit) == 1 and unit[0]["source"] == "Modules/_posixsubprocess.c"
    assert unit[0]["source_sha256"] == closure._POSIXSUBPROCESS_INPUTS[unit[0]["source"]][1]
    assert "_posixsubprocess" not in facts["guarded_absent_imports"]
    assert {item["source"] for item in facts["native_header_inputs"]
            if item["module"] == "_posixsubprocess"} == {
        path for path in closure._POSIXSUBPROCESS_INPUTS if path.endswith(".h")
    }
    frozen = {item["name"]: item for item in facts["frozen"]}
    assert frozen["subprocess"]["source_sha256"] == sha(subprocess_source())
    assert b'{"_posixsubprocess", PyInit__posixsubprocess},' in dict(result.sources)["runtime/Modules/config.c"]
    assert "_winapi" not in frozen and "msvcrt" in facts["guarded_absent_imports"]
    assert len(facts["fixed_platform_guards"]) == 1
    assert facts["runtime_execution_performed"] is False
    assert facts["production_admission"] is False
    assert facts["dynamic_import_closure_verified"] is False
    assert "configuration/pyconfig.h" not in dict(result.sources)


def test_complete_available_source_inventory_refuses_a_fake_msvcrt(closure_inputs):
    add_subprocess(closure_inputs)
    closure_inputs["cpython_sources"]["Lib/msvcrt.py"] = b"pass\n"
    refresh_cpython_pin(closure_inputs)
    with pytest.raises(closure.RuntimeClosureError, match="subprocess_platform_module_conflict"):
        closure.prepare_fixed_runtime_closure(**closure_inputs)


@pytest.mark.parametrize("path", list(closure._POSIXSUBPROCESS_INPUTS))
@pytest.mark.parametrize("mutation", ["missing", "drift"])
def test_native_source_and_every_direct_header_remain_required(closure_inputs, path, mutation):
    if mutation == "missing":
        del closure_inputs["cpython_sources"][path]
    else:
        closure_inputs["cpython_sources"][path] += b"/* drift */\n"
    refresh_cpython_pin(closure_inputs)
    with pytest.raises(closure.RuntimeClosureError, match="posixsubprocess_input_pin_mismatch"):
        closure.prepare_fixed_runtime_closure(**closure_inputs)


@pytest.mark.parametrize("path,before,after", [
    ("Modules/_posixsubprocess.c", b"PyInit__posixsubprocess(void)", b"PyInit__replacement(void)"),
    ("Modules/_posixsubprocess.c", b'.m_name = "_posixsubprocess",', b'.m_name = "replacement",'),
    ("Modules/clinic/_posixsubprocess.c.h", b"#define SUBPROCESS_FORK_EXEC_METHODDEF", b"#define REPLACED_METHODDEF"),
])
def test_native_initializer_and_clinic_relationships_are_explicit(closure_inputs, monkeypatch, path, before, after):
    raw = closure_inputs["cpython_sources"][path].replace(before, after, 1)
    closure_inputs["cpython_sources"][path] = raw
    monkeypatch.setitem(closure._POSIXSUBPROCESS_INPUTS, path, (len(raw), sha(raw)))
    refresh_cpython_pin(closure_inputs)
    with pytest.raises(closure.RuntimeClosureError, match="posixsubprocess_initializer_invalid"):
        closure.prepare_fixed_runtime_closure(**closure_inputs)


def native_recipe_input(concrete_inputs):
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
    size, digest = closure._POSIXSUBPROCESS_INPUTS["Modules/_posixsubprocess.c"]
    facts = {
        "schema": "lunar-fixed-python-runtime-source-closure-v1", "solver": "openevolve",
        "production_admission": False, "runtime_execution_performed": False,
        "native_units": [{"module": "_posixsubprocess", "source": "Modules/_posixsubprocess.c",
                          "object": "Modules/_posixsubprocess.o", "source_size": size,
                          "source_sha256": digest, "extra_flags": []}],
        "frozen": tasks, "sources": [{"path": path, "size": len(raw), "sha256": sha(raw)}
                                     for path, raw in sorted(generated.items())],
    }
    entries = {item["path"]: item for item in json.loads(args["source_inventory_bytes"])}
    for path, (size, digest) in closure._POSIXSUBPROCESS_INPUTS.items():
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


def test_recipe_retains_real_posix_unit_and_false_build_claims(concrete_inputs):
    prep, args, value = native_recipe_input(concrete_inputs)
    result = concrete.prepare_cpython_build_recipe(prep, **args, runtime_closure=value)
    commands = [command for stage in json.loads(result.recipe_bytes)["stages"] for command in stage["commands"]]
    assert any("@source/Modules/_posixsubprocess.c" in command["argv"] for command in commands)
    facts = json.loads(result.manifest_bytes)
    assert facts["build_performed"] is False and facts["production_admission"] is False
    assert facts["configured_closure_verified"] is False


@pytest.mark.parametrize("mutation", ["missing", "digest", "size", "executable"])
def test_recipe_independently_rejects_native_clinic_header_drift(concrete_inputs, mutation):
    prep, args, value = native_recipe_input(concrete_inputs)
    records = json.loads(args["source_inventory_bytes"])
    entry = next(item for item in records if item["path"] == "Modules/clinic/_posixsubprocess.c.h")
    if mutation == "missing":
        records.remove(entry)
    elif mutation == "digest":
        entry["sha256"] = sha(b"fake header")
    elif mutation == "size":
        entry["size"] += 1
    else:
        entry["executable"] = True
    args["source_inventory_bytes"] = closure.canonical(records)
    args["expected_source_inventory_sha256"] = sha(args["source_inventory_bytes"])
    with pytest.raises(concrete.ConcreteRecipeError, match="posixsubprocess_input_pin_mismatch"):
        concrete.prepare_cpython_build_recipe(prep, **args, runtime_closure=value)


@pytest.mark.parametrize("mutation", ["source", "object", "source_size", "source_sha256", "extra_flags", "duplicate"])
def test_recipe_independently_rejects_resigned_posix_unit_substitution(concrete_inputs, mutation):
    prep, args, value = native_recipe_input(concrete_inputs)
    facts = json.loads(value.wire_bytes)
    unit = facts["native_units"][0]
    if mutation == "source_size":
        unit[mutation] += 1
    elif mutation == "extra_flags":
        unit[mutation] = ["-DHOST_OVERRIDE=1"]
    elif mutation == "duplicate":
        facts["native_units"].append(unit.copy())
    else:
        unit[mutation] = "0" * 64 if mutation == "source_sha256" else "Modules/replacement.c"
    value = closure.FixedRuntimeClosure(closure.canonical(facts), value.sources)
    with pytest.raises(concrete.ConcreteRecipeError, match="posixsubprocess_input_pin_mismatch"):
        concrete.prepare_cpython_build_recipe(prep, **args, runtime_closure=value)
