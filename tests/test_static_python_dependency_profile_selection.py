"""Explicit source selection through dependency recipes; no runtime acceptance.

Pure cases use the complete real generator graph. Actual-process cases explicitly
project that selected graph to a tiny inert build, retaining the selected source
bytes and original dependency wrappers/runner/consumer, not compiling CPython.
"""

from __future__ import annotations

import json
import shutil
import time

import pytest
import test_static_python_completion_build_selection as completion_tests
import test_static_python_envelope_build_selection as envelope_tests
import test_static_python_standalone_linker as standalone_tests
import test_static_python_zig_support as support_tests

from lunar_evolution.static_python_producer_completion_source import (
    COMPLETION_LAUNCHER_PATH,
    FIXED_PRODUCER_LIFECYCLE_PROFILE,
)
from lunar_evolution.static_python_producer_envelope_source import (
    ENVELOPE_LAUNCHER_PATH,
    FIXED_PRODUCER_ENVELOPE_PROFILE,
)
from tests.test_static_python_link_dependency_capture import base_recipe, record, sha
from tools.static_python_rsi_fixture import build_dependency_consumer as consumer
from tools.static_python_rsi_fixture import concrete_recipe as concrete
from tools.static_python_rsi_fixture import dependency_capture as compiler
from tools.static_python_rsi_fixture import link_dependency_capture as linker
from tools.static_python_rsi_fixture import standalone_linker as standalone
from tools.static_python_rsi_fixture import zig_support as support
from tools.static_python_rsi_fixture.command_input_graph import validate_dependency_command_graph
from tools.static_python_rsi_fixture.runtime_closure import canonical

concrete_inputs = completion_tests.concrete_inputs
inert_support_tool = support_tests.inert_support_tool
_KINDS = ("compiler", "linker", "standalone", "support")
_PROFILES = (FIXED_PRODUCER_LIFECYCLE_PROFILE, FIXED_PRODUCER_ENVELOPE_PROFILE)
_GENERATORS = {
    "compiler": compiler.prepare_cpython_dependency_recipe,
    "linker": linker.prepare_cpython_link_dependency_recipe,
    "standalone": standalone.prepare_cpython_standalone_link_recipe,
    "support": support.prepare_cpython_explicit_support_recipe,
}


def _synthetic_support(prep, tools):
    """An all-false fixture observation for pure graph tests, never executed."""
    files = tuple(("lunar-support/" + name, ("inert-" + name).encode())
                  for name in sorted(support._SUPPORT_NAMES))
    facts = {
        "schema": support._BUNDLE_SCHEMA, "target": "x86_64-linux-musl",
        "preparation_sha256": prep.sha256, "zig_inventory_sha256": sha(canonical(tools)),
        "support": [{**record(path, raw), "generated_cache_path": "o/" + path.rsplit("/", 1)[1]}
                    for path, raw in files],
        "seed_executed": False, **support._FALSE,
    }
    for name in ("seed_recipe_sha256", "seed_report_sha256", "seed_depfile_sha256",
                 "cache_inventory_sha256"):
        facts[name] = sha(b"synthetic unaccepted observation")
    return support.ZigSupportBundle(canonical(facts), files)


def _extras(kind, prep, arguments):
    if kind == "standalone":
        profile = standalone_tests.profile_bytes()
        return {"standalone_profile_bytes": profile,
                "expected_standalone_profile_sha256": sha(profile)}
    if kind == "support":
        tools = concrete.complete_zig_inventory(arguments["zig_manifest_bytes"])
        return {"support_bundle": _synthetic_support(prep, tools)}
    return {}


def _generate(kind, prep, arguments, **selection):
    return _GENERATORS[kind](prep, **arguments, **_extras(kind, prep, arguments), **selection)


def _selection(prep, solver, profile):
    prepare = (envelope_tests._envelope_closure if profile == FIXED_PRODUCER_ENVELOPE_PROFILE
               else completion_tests._completion_closure)
    facts, sources = prepare(prep, solver)
    return {"runtime_closure": completion_tests._closure(facts, sources),
            "producer_lifecycle_profile": profile}, sources


@pytest.mark.parametrize("kind", _KINDS)
def test_omitted_and_explicit_none_keep_identical_recipe_source_and_manifest_bytes(
    concrete_inputs, kind,
):
    prep, arguments = concrete_inputs
    omitted = _generate(kind, prep, arguments)
    explicit_none = _generate(kind, prep, arguments, producer_lifecycle_profile=None)
    assert omitted == explicit_none
    assert b'"producer_lifecycle_profile"' not in omitted.manifest_bytes
    assert b"@source/tools/static_python_rsi_fixture/assets/launcher.c" in omitted.recipe_bytes
    assert ENVELOPE_LAUNCHER_PATH.encode() not in omitted.recipe_bytes
    assert COMPLETION_LAUNCHER_PATH.encode() not in omitted.recipe_bytes


@pytest.mark.parametrize("kind", _KINDS)
@pytest.mark.parametrize("profile", _PROFILES)
@pytest.mark.parametrize("solver", ("openevolve", "shinka"))
def test_real_successor_generators_preserve_exact_explicit_profile_and_base_pins(
    concrete_inputs, kind, profile, solver,
):
    prep, arguments = concrete_inputs
    selection, sources = _selection(prep, solver, profile)
    selected = _generate(kind, prep, arguments, **selection)
    wire = json.loads(selected.recipe_bytes)
    launcher = ENVELOPE_LAUNCHER_PATH if profile == FIXED_PRODUCER_ENVELOPE_PROFILE else COMPLETION_LAUNCHER_PATH
    alternate = COMPLETION_LAUNCHER_PATH if profile == FIXED_PRODUCER_ENVELOPE_PROFILE else ENVELOPE_LAUNCHER_PATH
    compilations = [command for stage in wire["stages"] for command in stage["commands"]
                    if "-c" in command["argv"]]
    assert any("@source/" + launcher in command["argv"] for command in compilations)
    assert not any("@source/" + alternate in command["argv"] for command in compilations)
    for command in compilations:
        assert command["argv"][-5:-3] == ["-MD", "-MF"]
    for path in (launcher, "runtime/frozen_main.py", "producer/" + solver + "/lunar_fixed.py"):
        assert dict(selected.sources)[path] == sources[path]
    if kind == "compiler":
        base = concrete.prepare_cpython_build_recipe(prep, **arguments, **selection)
    else:
        base_kind = "linker" if kind == "support" else "compiler"
        base = _generate(base_kind, prep, arguments, **selection)
        extras = _extras(kind, prep, arguments)
        profile_args = extras if kind == "standalone" else {}
        parsed, compile_paths, link_paths = linker.validate_dependency_capture_plan(
            selected.recipe_bytes, expected_recipe_sha256=selected.sha256,
            manifest_bytes=selected.manifest_bytes, expected_manifest_sha256=sha(selected.manifest_bytes),
            **profile_args,
        )
        validate_dependency_command_graph(parsed)
        assert len(compile_paths) == len(compilations) and len(link_paths) == 2
    manifest = json.loads(selected.manifest_bytes)
    assert manifest["base_recipe_sha256"] == base.sha256
    assert manifest["base_manifest_sha256"] == sha(base.manifest_bytes)
    assert manifest["production_admission"] is manifest["configured_closure_verified"] is False
    assert manifest["immutable_custody_verified"] is False


@pytest.mark.parametrize("kind", _KINDS)
@pytest.mark.parametrize("fault", ("missing_profile", "wrong_profile", "resigned_source"))
def test_all_successor_apis_retain_original_v2_source_refusal_without_fallback(
    concrete_inputs, kind, fault,
):
    prep, arguments = concrete_inputs
    facts, sources = envelope_tests._envelope_closure(prep, "openevolve")
    profile = FIXED_PRODUCER_ENVELOPE_PROFILE
    if fault == "missing_profile":
        profile, reason = None, "envelope_profile_required"
    elif fault == "wrong_profile":
        profile, reason = FIXED_PRODUCER_LIFECYCLE_PROFILE, "completion_profile_mismatch|completion_source_drift"
    else:
        raw = sources[ENVELOPE_LAUNCHER_PATH]
        sources[ENVELOPE_LAUNCHER_PATH] = bytes([raw[0] ^ 1]) + raw[1:]
        envelope_tests._resign_tasks(facts, sources)
        reason = "envelope_source_drift"
    with pytest.raises(concrete.ConcreteRecipeError, match=reason):
        _generate(kind, prep, arguments, runtime_closure=completion_tests._closure(facts, sources),
                  producer_lifecycle_profile=profile)


@pytest.mark.parametrize("solver", ("openevolve", "shinka"))
def test_v2_selection_reaches_actual_original_consumer_with_explicit_inert_projection(
    concrete_inputs, inert_support_tool, monkeypatch, tmp_path, solver,
):
    prep, arguments = concrete_inputs
    tools = tmp_path / "actual-tools"
    (tools / "lib").mkdir(parents=True)
    (tools / "lib/mode").write_bytes(b"normal")
    shutil.copyfile(inert_support_tool, tools / "zig")
    (tools / "zig").chmod(0o700)
    tool_records = [record("lib/mode", b"normal"), record("zig", inert_support_tool.read_bytes(), True)]
    monkeypatch.setattr(concrete, "complete_zig_inventory", lambda _raw: tool_records)
    monkeypatch.setattr(support, "complete_zig_inventory", lambda _raw: tool_records)
    deadline = time.monotonic() + 30
    bundle = support.run_zig_support_preparation(
        prep, zig_manifest_bytes=arguments["zig_manifest_bytes"], toolchain_root=tools,
        workspace=tmp_path / "actual-support", deadline=deadline,
    )
    selection, closure_sources = _selection(prep, solver, FIXED_PRODUCER_ENVELOPE_PROFILE)
    calls = []
    original = concrete.prepare_cpython_build_recipe

    def select_then_project(preparation, **kwargs):
        # Execute the real source/closure/profile gate before replacing only the
        # large CPython graph with a declared test-only, executable inert graph.
        full = original(preparation, **kwargs)
        assert kwargs["producer_lifecycle_profile"] == FIXED_PRODUCER_ENVELOPE_PROFILE
        full_wire = json.loads(full.recipe_bytes)
        assert any("@source/" + ENVELOPE_LAUNCHER_PATH in command["argv"]
                   for stage in full_wire["stages"] for command in stage["commands"])
        paths = (ENVELOPE_LAUNCHER_PATH, "producer/" + solver + "/lunar_fixed.py", "runtime/frozen_main.py")
        selected_sources = tuple(sorted((path, dict(full.sources)[path]) for path in paths))
        tiny = json.loads(base_recipe(
            preparation.sha256, [record(path, raw) for path, raw in selected_sources], tool_records,
        ).recipe_bytes)
        for stage in tiny["stages"]:
            for command in stage["commands"]:
                if "-c" in command["argv"]:
                    command["argv"] = [argument if argument != "@source/unit.c"
                                       else "@source/" + ENVELOPE_LAUNCHER_PATH
                                       for argument in command["argv"][:-5]]
                    command["outputs"].pop()
        if solver == "shinka":
            link = tiny["stages"][-1]["commands"][-1]
            link["argv"][link["argv"].index("-o") + 1] = "@work/bin/lunar-shinka"
            link["outputs"][0]["path"] = "bin/lunar-shinka"
        manifest = canonical({"schema": "test-only-selected-source-inert-projection-v1",
                              "full_recipe_sha256": full.sha256,
                              "full_manifest_sha256": sha(full.manifest_bytes),
                              "build_performed": False, "production_admission": False})
        projected = concrete.ConcreteBuildRecipe(canonical(tiny), selected_sources, manifest)
        calls.append((full, projected))
        return projected

    monkeypatch.setattr(compiler, "prepare_cpython_build_recipe", select_then_project)
    build = support.prepare_cpython_explicit_support_recipe(
        prep, **arguments, support_bundle=bundle, **selection,
    )
    assert len(calls) == 1
    source_root = tmp_path / "actual-source"
    for path, raw in build.sources:
        assert raw == closure_sources[path]
        target = source_root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    for path, raw in build.toolchain_additions:
        target = tools / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    runner = consumer.run_pinned_build_v3
    dispatched = []

    def observe_runner(*args, **kwargs):
        dispatched.append(kwargs)
        return runner(*args, **kwargs)

    monkeypatch.setattr(consumer, "run_pinned_build_v3", observe_runner)
    result = consumer.run_dependency_checked_build(
        prep, recipe_bytes=build.recipe_bytes, expected_recipe_sha256=build.sha256,
        manifest_bytes=build.manifest_bytes, expected_manifest_sha256=sha(build.manifest_bytes),
        source_root=source_root, toolchain_root=tools, workspace=tmp_path / "actual-build",
        deadline=deadline,
    )
    assert len(dispatched) == 1
    assert dispatched[0]["recipe_bytes"] == build.recipe_bytes
    assert dispatched[0]["deadline"] == deadline
    assert result.execution_report.status == "complete"
    assert result.execution_report.completed_stages == ("configure", "freeze", "compile", "link")
    assert result.production_admission is result.installation_accepted is result.online_publication is False
    assert result.immutable_custody_verified is result.driver_inputs_verified is False
    retained = tmp_path / "actual-build"
    assert len(json.loads((retained / "compiler-dependency-comparison.json").read_bytes())["compilations"]) == 3
    assert len(json.loads((retained / "linker-dependency-comparison.json").read_bytes())["links"]) == 2
