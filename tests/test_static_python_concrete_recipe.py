"""Concrete recipe source graph tests; no upstream function/build is executed."""

from __future__ import annotations

import hashlib
import json

import pytest

from tools.static_python_rsi_fixture import concrete_recipe as concrete
from tools.static_python_rsi_fixture import recipe
from tools.static_python_rsi_fixture.build_driver import _preparation_wire
from tools.static_python_rsi_fixture.execution_backend import (
    RECIPE_V3_SCHEMA,
    BuildExecutionError,
    _recipe,
)
from tools.static_python_rsi_fixture.installation_profile import prepare_rsi_installation_profile
from tools.static_python_rsi_fixture.runtime_closure import FixedRuntimeClosure, canonical


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def concrete_inputs(tmp_path, monkeypatch):
    path = recipe.emit_rsi_launch_source_plan(tmp_path / "plan")
    prep = prepare_rsi_installation_profile(
        reviewed_build_inputs=(recipe._ROOT / "tools/static_python_fixture/reviewed-build-inputs.json").read_bytes(),
        reviewed_overlay=(recipe._ROOT / "tools/static_python_rsi_fixture/reviewed-profile-overlay.json").read_bytes(),
        source_plan=path.read_bytes(), expected_source_plan_sha256=sha(path.read_bytes()),
        source_assets={p.name: p.read_bytes() for p in (path.parent / "assets").iterdir()},
    )
    plan = _preparation_wire(prep)["candidate_build_inputs"]
    records = {}
    for item in plan["shared_units"] + plan["freezer_units"] + plan["target_units"] + plan["freeze_tasks"]:
        records[item["source"]] = {"path": item["source"], "size": item["source_size"],
                                   "sha256": item["source_sha256"], "executable": False}
    for name in ("Include/Python.h", "Include/internal/pycore_import.h",
                 "Include/internal/mimalloc/mimalloc.h", "assets/lunar_fixture_profile.h"):
        records[name] = {"path": name, "size": 1, "sha256": sha(b"x"), "executable": False}
    inventory = canonical([records[n] for n in sorted(records)])
    # The command generator is tested with an explicit synthetic tool identity;
    # public full-inventory projection is exercised independently below.
    monkeypatch.setattr(concrete, "complete_zig_inventory", lambda _: sorted([
        {"path": "zig", "size": 4, "sha256": sha(b"inert"), "executable": True},
        {"path": "lib/include/stdint.h", "size": 1, "sha256": sha(b"x"), "executable": False},
    ], key=lambda record: record["path"]))
    config = b"/* synthetic configuration; not an accepted pyconfig.h */\n"
    return prep, {"source_inventory_bytes": inventory,
                  "expected_source_inventory_sha256": sha(inventory), "zig_manifest_bytes": b"inert",
                  "configuration_header": config, "expected_configuration_sha256": sha(config)}


def test_concrete_graph_builds_same_source_freezer_and_nine_jobs(concrete_inputs):
    prep, args = concrete_inputs
    result = concrete.prepare_cpython_build_recipe(prep, **args)
    wire = json.loads(result.recipe_bytes)
    assert wire["schema"] == RECIPE_V3_SCHEMA
    assert _recipe(result.recipe_bytes, result.sha256, version3=True) == wire
    stages = {stage["stage"]: stage["commands"] for stage in wire["stages"]}
    commands = [c for group in stages.values() for c in group]
    assert all(c["argv"][0] in {"@toolchain/zig", "@work/bin/lunar-freeze-module"} for c in commands)
    frozen = [c for c in stages["freeze"] if c["argv"][0] == "@work/bin/lunar-freeze-module"]
    assert len(frozen) == 9
    assert frozen[0]["argv"][1] == "importlib._bootstrap"
    assert frozen[-1]["argv"][1] == "_lunar_static_main"
    first_freezer = next(i for i, c in enumerate(stages["freeze"])
                         if c["outputs"][0]["path"] == "bin/lunar-freeze-module")
    assert all(c["argv"][0] == "@toolchain/zig" for c in stages["freeze"][:first_freezer + 1])
    assert any("@source/Programs/_freeze_module.c" in c["argv"] for c in stages["freeze"])
    assert len(stages["compile"]) == 4
    assert stages["link"][0]["argv"][:3] == ["@toolchain/zig", "ar", "rcsD"]
    assert "-static" in stages["link"][-1]["argv"]
    assert not any("python" == arg or arg.endswith("/python") or arg in {"sh", "make", "configure"}
                   for c in commands for arg in c["argv"])
    facts = json.loads(result.manifest_bytes)
    assert facts["solver"] == "marker-fixture"
    assert facts["core_objects"] == 162 and facts["freezer_objects"] == 2
    assert facts["build_performed"] is False and facts["production_admission"] is False
    assert facts["autoconf_executed"] is False


@pytest.mark.parametrize("field", ["source_inventory_bytes", "configuration_header"])
def test_independent_source_and_configuration_pins_required(concrete_inputs, field):
    prep, args = concrete_inputs
    args[field] += b" "
    with pytest.raises(concrete.ConcreteRecipeError, match="input_pin_mismatch"):
        concrete.prepare_cpython_build_recipe(prep, **args)


def test_resigned_translation_unit_mutation_refuses(concrete_inputs):
    prep, args = concrete_inputs
    records = json.loads(args["source_inventory_bytes"])
    record = next(r for r in records if r["path"] == "Programs/_freeze_module.c")
    record["sha256"] = sha(b"different C source")
    args["source_inventory_bytes"] = canonical(records)
    args["expected_source_inventory_sha256"] = sha(args["source_inventory_bytes"])
    with pytest.raises(concrete.ConcreteRecipeError, match="translation_unit_pin_mismatch"):
        concrete.prepare_cpython_build_recipe(prep, **args)


def test_resigned_freeze_source_mutation_refuses(concrete_inputs):
    prep, args = concrete_inputs
    records = json.loads(args["source_inventory_bytes"])
    next(r for r in records if r["path"] == "Lib/abc.py")["sha256"] = sha(b"different Python source")
    args["source_inventory_bytes"] = canonical(records)
    args["expected_source_inventory_sha256"] = sha(args["source_inventory_bytes"])
    with pytest.raises(concrete.ConcreteRecipeError, match="freezer_source_pin_mismatch"):
        concrete.prepare_cpython_build_recipe(prep, **args)


@pytest.mark.parametrize("mutation", ["duplicate", "unsorted", "path", "bool_size", "extra_field"])
def test_strict_source_inventory(concrete_inputs, mutation):
    prep, args = concrete_inputs
    records = json.loads(args["source_inventory_bytes"])
    if mutation == "duplicate":
        records.insert(0, records[0].copy())
    elif mutation == "unsorted":
        records.reverse()
    elif mutation == "path":
        records[0]["path"] = "../escape"
    elif mutation == "bool_size":
        records[0]["size"] = True
    else:
        records[0]["ambient"] = True
    args["source_inventory_bytes"] = canonical(records)
    args["expected_source_inventory_sha256"] = sha(args["source_inventory_bytes"])
    with pytest.raises(concrete.ConcreteRecipeError):
        concrete.prepare_cpython_build_recipe(prep, **args)


def test_configured_header_is_explicit_input_and_configure_probe_is_not_acceptance(concrete_inputs):
    prep, args = concrete_inputs
    result = concrete.prepare_cpython_build_recipe(prep, **args)
    generated = dict(result.sources)
    assert generated["configuration/pyconfig.h"] == args["configuration_header"]
    assert b"dynamic_loader_refused" in generated["configuration/probe.c"]
    wire = json.loads(result.recipe_bytes)
    probe = wire["stages"][0]["commands"][0]
    assert probe["argv"][0] == "@toolchain/zig" and "-c" in probe["argv"]
    assert "@source/configuration/probe.c" in probe["argv"]
    assert json.loads(result.manifest_bytes)["configured_closure_verified"] is False


def test_reviewed_mimalloc_and_semantic_flags_cover_every_compilation_role(concrete_inputs):
    prep, args = concrete_inputs
    result = concrete.prepare_cpython_build_recipe(prep, **args)
    wire = json.loads(result.recipe_bytes)
    compilations = [command["argv"] for stage in wire["stages"] for command in stage["commands"]
                    if "-c" in command["argv"]]
    assert {stage["stage"] for stage in wire["stages"]
            if any("-c" in command["argv"] for command in stage["commands"])} == {
                "configure", "freeze", "compile",
            }
    assert any("-DPy_BUILD_CORE_BUILTIN" in argv for argv in compilations)
    for argv in compilations:
        assert {"-fno-strict-overflow", "-fvisibility=hidden",
                "-Werror=implicit-function-declaration"}.issubset(argv)
        assert any(argv[index:index + 2] == ["-I", "@source-dir/Include/internal/mimalloc"]
                   for index in range(len(argv) - 1))
    sources = [argv[argv.index("-c") + 1] for argv in compilations]
    assert sources.count("@source/Objects/obmalloc.c") == 1
    assert not any(source.startswith("@source/Objects/mimalloc/") for source in sources)
    assert dict(result.sources)["configuration/pyconfig.h"] == args["configuration_header"]
    assert json.loads(result.manifest_bytes)["configured_closure_verified"] is False


def test_missing_declared_mimalloc_header_subtree_refuses_before_execution(concrete_inputs):
    prep, args = concrete_inputs
    records = [record for record in json.loads(args["source_inventory_bytes"])
               if not record["path"].startswith("Include/internal/mimalloc/")]
    args["source_inventory_bytes"] = canonical(records)
    args["expected_source_inventory_sha256"] = sha(args["source_inventory_bytes"])
    with pytest.raises(BuildExecutionError, match="directory_reference_not_available"):
        concrete.prepare_cpython_build_recipe(prep, **args)


@pytest.mark.parametrize("private_sink", [False, True])
def test_runtime_closure_is_explicit_new_solver_main_and_tables(concrete_inputs, private_sink):
    from lunar_evolution.static_python_fixed_live_modules import FIXED_LIVE_SINK_LAUNCHER_PATH
    from tools.static_python_rsi_fixture.live_module_source import prepare_fixed_live_sink_launcher

    prep, args = concrete_inputs
    plan = _preparation_wire(prep)["candidate_build_inputs"]
    generated = {
        "runtime/Modules/config.c": b"/* synthetic table */\n",
        "runtime/Python/frozen.c": b"/* synthetic frozen table */\n",
        "runtime/Python/stdlib_module_names.h": b"/* synthetic names */\n",
        "runtime/frozen_main.py": b"def _rsi_launch(x): pass\n",
    }
    if private_sink:
        generated[FIXED_LIVE_SINK_LAUNCHER_PATH] = prepare_fixed_live_sink_launcher()
    tasks = [dict(t) for t in plan["freeze_tasks"]]
    tasks[-1].update(source="runtime/frozen_main.py", source_size=len(generated["runtime/frozen_main.py"]),
                     source_sha256=sha(generated["runtime/frozen_main.py"]))
    facts = {"schema": "lunar-fixed-python-runtime-source-closure-v1", "solver": "openevolve",
             "production_admission": False, "runtime_execution_performed": False,
             "native_units": [], "frozen": tasks,
             "sources": [{"path": path, "size": len(raw), "sha256": sha(raw)}
                         for path, raw in sorted(generated.items())]}
    closure = FixedRuntimeClosure(canonical(facts), tuple(sorted(generated.items())))
    result = concrete.prepare_cpython_build_recipe(prep, **args, runtime_closure=closure)
    wire = json.loads(result.recipe_bytes)
    assert wire["stages"][-1]["commands"][-1]["outputs"][0]["path"] == "bin/lunar-openevolve"
    assert dict(result.sources)["Python/stdlib_module_names.h"] == generated["runtime/Python/stdlib_module_names.h"]
    assert json.loads(result.manifest_bytes)["runtime_closure_sha256"] == closure.sha256
    compile_commands = next(stage["commands"] for stage in wire["stages"] if stage["stage"] == "compile")
    selected = "@source/" + FIXED_LIVE_SINK_LAUNCHER_PATH
    assert any(selected in command["argv"] for command in compile_commands) is private_sink
    original_launcher = "@source/tools/static_python_rsi_fixture/assets/launcher.c"
    assert any(original_launcher in command["argv"] for command in compile_commands) is not private_sink


@pytest.fixture
def synthetic_zig_manifest(monkeypatch):
    members = [{"kind": "file", "mode": 0o755, "path": concrete.ZIG_ROOT + "/zig",
                "size": 357913169 - 19545, "sha256": sha(b"inert") }]
    members += [{"kind": "file", "mode": 0o644, "path": concrete.ZIG_ROOT + f"/lib/file-{i:05d}",
                 "size": 1, "sha256": sha(b"x")} for i in range(19545)]
    facts = {"schema": "lunar-static-python-extraction-manifest-v1", "archive": "zig",
             "archive_sha256": concrete.ZIG_ARCHIVE_SHA256, "root": concrete.ZIG_ROOT,
             "members": members}
    raw = canonical(facts)
    monkeypatch.setattr(concrete, "ZIG_MANIFEST_SHA256", sha(raw))
    monkeypatch.setattr(concrete, "ZIG_MANIFEST_BYTES", len(raw))
    return facts, raw


def test_complete_zig_inventory_never_truncates_19546_files(synthetic_zig_manifest):
    _, raw = synthetic_zig_manifest
    result = concrete.complete_zig_inventory(raw)
    assert len(result) == 19546 and sum(r["size"] for r in result) == 357913169
    assert [r["path"] for r in result if r["executable"]] == ["zig"]


def test_resigned_truncated_zig_manifest_refuses(synthetic_zig_manifest, monkeypatch):
    facts, _ = synthetic_zig_manifest
    facts["members"].pop()
    raw = canonical(facts)
    monkeypatch.setattr(concrete, "ZIG_MANIFEST_SHA256", sha(raw))
    monkeypatch.setattr(concrete, "ZIG_MANIFEST_BYTES", len(raw))
    with pytest.raises(concrete.ConcreteRecipeError, match="zig_inventory_incomplete"):
        concrete.complete_zig_inventory(raw)
