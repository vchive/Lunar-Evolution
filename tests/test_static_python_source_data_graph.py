"""Finite v4 data-source graphs and retained captures, without build authority."""

from __future__ import annotations

import json

import pytest

from tests.test_static_python_concrete_recipe import (
    concrete_inputs as concrete_inputs,  # noqa: PLC0414 - pytest fixture re-export
)
from tests.test_static_python_link_dependency_capture import base_recipe, instrument, record, sha
from tests.test_static_python_standalone_linker import generate, profile_bytes
from tools.static_python_rsi_fixture import concrete_recipe as concrete
from tools.static_python_rsi_fixture import dependency_capture as compiler
from tools.static_python_rsi_fixture import link_dependency_capture as capture
from tools.static_python_rsi_fixture import standalone_linker
from tools.static_python_rsi_fixture.command_input_graph import (
    BuildCommandInputError,
    validate_dependency_command_graph,
    validate_dependency_command_graph_v4,
)
from tools.static_python_rsi_fixture.execution_backend import (
    INPUT_PROJECTION_V4,
    RECIPE_V3_SCHEMA,
    RECIPE_V4_SCHEMA,
    BuildExecutionError,
    _recipe,
)
from tools.static_python_rsi_fixture.runtime_closure import canonical


def _arguments():
    return {"source_inventory_bytes": b"", "expected_source_inventory_sha256": sha(b"original inventory"),
            "zig_manifest_bytes": b"", "configuration_header": b"", "expected_configuration_sha256": ""}


def _validation(generated, profile=None):
    result = {"expected_recipe_sha256": generated.sha256, "manifest_bytes": generated.manifest_bytes,
              "expected_manifest_sha256": sha(generated.manifest_bytes)}
    if profile is not None:
        result.update(standalone_profile_bytes=profile, expected_standalone_profile_sha256=sha(profile))
    return result


@pytest.fixture
def vector(monkeypatch):
    source = [record("configure", b"#!/bin/sh\n", True), record("script.py", b"pass\n", True),
              record("unit.c", b"inert C data", True)]
    base = base_recipe(sha(b"prep"), source,
                       [record("lib/crt.o"), record("zig", executable=True)])
    legacy = instrument(monkeypatch, base)
    wire = json.loads(legacy.recipe_bytes)
    wire["stages"][1]["commands"].append({
        "argv": ["@work/bin/lunar-freeze-module", "inert_module", "@source/script.py",
                 "@work/generated-sources/Python/frozen_modules/inert_module.h"],
        "outputs": [{"path": "generated-sources/Python/frozen_modules/inert_module.h",
                     "max_size": 1024, "executable": False}],
    })
    # The original legacy generator has no native-freezer capture entry; the
    # finite graph still checks its exact prior executable and source data.
    legacy = concrete.ConcreteBuildRecipe(canonical(wire), (), legacy.manifest_bytes)
    monkeypatch.setattr(capture, "prepare_cpython_link_dependency_recipe", lambda *a, **kw: legacy)
    generated = capture.prepare_cpython_link_dependency_recipe_v4(object(), **_arguments())
    return legacy, generated


def test_explicit_successor_preserves_every_input_pin_xbit_and_command(vector):
    legacy, generated = vector
    before, after = json.loads(legacy.recipe_bytes), json.loads(generated.recipe_bytes)
    assert after == {**before, "schema": RECIPE_V4_SCHEMA, "input_projection": INPUT_PROJECTION_V4}
    assert all(row["executable"] for row in after["inputs"]["source"])
    parsed, compilations, links = capture.validate_dependency_capture_plan_v4(
        generated.recipe_bytes, **_validation(generated))
    validate_dependency_command_graph_v4(parsed)
    assert len(compilations) == 3 and len(links) == 2
    manifest = json.loads(generated.manifest_bytes)
    assert manifest["schema"] == capture.DATA_SOURCE_CAPTURE_SCHEMA
    assert manifest["base_recipe_sha256"] == legacy.sha256
    assert manifest["original_source_inventory_sha256"] == _arguments()["expected_source_inventory_sha256"]
    assert manifest["source_inventory_sha256"] == sha(canonical(after["inputs"]["source"]))
    assert manifest["toolchain_inventory_sha256"] == sha(canonical(after["inputs"]["toolchain"]))
    assert manifest["inputs_sha256"] == sha(canonical(after["inputs"]))
    assert all(manifest[key] is False for key in capture._FALSE_CLAIMS)


@pytest.mark.parametrize("entry", ["parser", "capture", "graph", "compiler"])
def test_old_public_entry_points_refuse_v4_instead_of_projecting_away_schema(vector, entry):
    _, generated = vector
    with pytest.raises((BuildExecutionError, BuildCommandInputError)):
        if entry == "parser":
            _recipe(generated.recipe_bytes, generated.sha256, version3=True)
        elif entry == "capture":
            capture.validate_dependency_capture_plan(generated.recipe_bytes, **_validation(generated))
        elif entry == "graph":
            validate_dependency_command_graph(json.loads(generated.recipe_bytes))
        else:
            compiler.compare_compiler_dependencies(
                generated.recipe_bytes, expected_recipe_sha256=generated.sha256,
                output_inventory_bytes=b"", expected_output_inventory_sha256=sha(b""),
                dependency_artifacts={}, source_root="/source", toolchain_root="/toolchain", work_root="/work")


@pytest.mark.parametrize("entry", ["capture", "graph"])
def test_v4_public_entry_points_refuse_legacy_recipe(vector, entry):
    legacy, generated = vector
    with pytest.raises((BuildExecutionError, BuildCommandInputError)):
        if entry == "capture":
            capture.validate_dependency_capture_plan_v4(legacy.recipe_bytes, **{
                **_validation(generated), "expected_recipe_sha256": legacy.sha256})
        else:
            validate_dependency_command_graph_v4(json.loads(legacy.recipe_bytes))


def test_legacy_finite_graph_still_refuses_executable_source_data(vector):
    legacy, _ = vector
    with pytest.raises(BuildCommandInputError, match="prior_input"):
        validate_dependency_command_graph(json.loads(legacy.recipe_bytes))


@pytest.mark.parametrize("path", ["configure", "script.py", "unit.c"])
def test_source_argv_zero_is_never_a_tool_even_when_original_executable_true(vector, path):
    _, generated = vector
    wire = json.loads(generated.recipe_bytes)
    wire["stages"][0]["commands"][0]["argv"][0] = "@source/" + path
    with pytest.raises(BuildCommandInputError, match="source_execution"):
        validate_dependency_command_graph_v4(wire)
    raw = canonical(wire)
    with pytest.raises(BuildExecutionError, match="executable_not_pinned"):
        _recipe(raw, sha(raw), version4=True)


@pytest.mark.parametrize("arguments", [
    ["-include", "@source/script.py"], ["-c", "-m"], ["--config=/ambient/driver"],
    ["-Xclang", "-load", "/ambient/plugin"], ["--sysroot=/ambient/root"],
])
def test_source_data_view_does_not_expand_original_compiler_grammar(vector, arguments):
    _, generated = vector
    wire = json.loads(generated.recipe_bytes)
    wire["stages"][0]["commands"][0]["argv"][2:2] = arguments
    with pytest.raises(BuildCommandInputError):
        validate_dependency_command_graph_v4(wire)


@pytest.mark.parametrize("mutation", ["self", "future", "tool_data", "extra_output", "freezer_script"])
def test_complete_prior_output_groups_and_original_executable_tool_roles_remain_required(vector, mutation):
    _, generated = vector
    wire = json.loads(generated.recipe_bytes)
    first = wire["stages"][0]["commands"][0]
    if mutation in {"self", "future"}:
        first["argv"][2:2] = ["-I", "@work-dir/" + ("dependencies" if mutation == "self" else "objects")]
    elif mutation == "tool_data":
        next(row for row in wire["inputs"]["toolchain"] if row["path"] == "zig")["executable"] = False
    elif mutation == "extra_output":
        first["outputs"].append({"path": "extra", "max_size": 10, "executable": False})
    else:
        wire["stages"][1]["commands"][-1]["argv"] += ["-c"]
    with pytest.raises(BuildCommandInputError):
        validate_dependency_command_graph_v4(wire)


@pytest.mark.parametrize("key", [
    "schema", "recipe_sha256", "base_recipe_sha256", "source_inventory_sha256",
    "toolchain_inventory_sha256", "inputs_sha256", "input_projection", "link_mode",
    "compilations", "links", "driver_inputs_verified", "extra_key",
])
def test_resigned_capture_manifest_cannot_replace_bound_recipe_inputs_or_plan(vector, key):
    _, generated = vector
    facts = json.loads(generated.manifest_bytes)
    if key == "extra_key":
        facts[key] = False
    elif key == "driver_inputs_verified":
        facts[key] = True
    elif key in {"compilations", "links"}:
        facts[key][0]["command_index"] = True
    else:
        facts[key] = sha(b"replaced")
    raw = canonical(facts)
    with pytest.raises(capture.LinkDependencyError, match="manifest"):
        capture.validate_dependency_capture_plan_v4(generated.recipe_bytes, **{
            **_validation(generated), "manifest_bytes": raw, "expected_manifest_sha256": sha(raw)})


def _comparison(generated):
    wire, manifest = json.loads(generated.recipe_bytes), json.loads(generated.manifest_bytes)
    compiler_artifacts = {row["depfile"]: (row["target"].replace("@work/", "/attempt/work/")
        + ": " + row["source"].replace("@source/", "/attempt/source/") + "\n").encode()
        for row in manifest["compilations"]}
    linker_artifacts = {row["depfile"]: (row["target"].replace("@work/", "/attempt/work/")
        + ": " + " ".join(ref.replace("@work/", "/attempt/work/").replace(
            "@toolchain/", "/attempt/toolchain/") for ref in row["explicit_inputs"]) + "\n").encode()
        for row in manifest["links"]}
    artifacts = {**compiler_artifacts, **linker_artifacts}
    outputs = [record(out["path"], artifacts.get(out["path"], b"output"), out["executable"])
               for stage in wire["stages"] for command in stage["commands"] for out in command["outputs"]]
    raw = canonical(sorted(outputs, key=lambda row: row["path"]))
    kwargs = {**_validation(generated), "output_inventory_bytes": raw,
              "expected_output_inventory_sha256": sha(raw), "source_root": "/attempt/source",
              "toolchain_root": "/attempt/toolchain", "work_root": "/attempt/work"}
    return kwargs, compiler_artifacts, linker_artifacts


def test_v4_comparisons_share_original_byte_and_complete_prior_output_logic(vector):
    _, generated = vector
    kwargs, compiler_artifacts, linker_artifacts = _comparison(generated)
    left = compiler.compare_compiler_dependencies_v4(
        generated.recipe_bytes, **kwargs, dependency_artifacts=compiler_artifacts).to_dict()
    right = capture.compare_linker_dependencies_v4(
        generated.recipe_bytes, **kwargs, dependency_artifacts=linker_artifacts).to_dict()
    assert len(left["compilations"]) == 3 and len(right["links"]) == 2
    for facts in (left, right):
        assert facts["input_projection"] == INPUT_PROJECTION_V4
        assert facts["inputs_sha256"] == json.loads(generated.manifest_bytes)["inputs_sha256"]
        assert facts["manifest_sha256"] == sha(generated.manifest_bytes)
        assert facts["production_admission"] is False
        assert b"/attempt" not in canonical(facts)


@pytest.mark.parametrize("kind", ["missing_group_member", "unknown_dependency", "current_dependency", "artifact_drift"])
def test_v4_compiler_readback_rejects_partial_group_or_current_unpinned_input(vector, kind):
    _, generated = vector
    kwargs, artifacts, _ = _comparison(generated)
    rows = json.loads(kwargs["output_inventory_bytes"])
    path = next(iter(artifacts))
    if kind == "missing_group_member":
        rows = [row for row in rows if row["path"] != "probe.o"]
    elif kind == "artifact_drift":
        artifacts[path] += b" "
    else:
        dependency = "/attempt/source/unknown.h" if kind == "unknown_dependency" else "/attempt/work/probe.o"
        artifacts[path] = artifacts[path].rstrip(b"\n") + b" " + dependency.encode() + b"\n"
        next(row for row in rows if row["path"] == path).update(size=len(artifacts[path]), sha256=sha(artifacts[path]))
    raw = canonical(rows)
    kwargs.update(output_inventory_bytes=raw, expected_output_inventory_sha256=sha(raw))
    with pytest.raises(compiler.CompilerDependencyError):
        compiler.compare_compiler_dependencies_v4(generated.recipe_bytes, **kwargs, dependency_artifacts=artifacts)


def test_actual_concrete_successor_preserves_original_script_xbits_and_overlay_binding(concrete_inputs):
    preparation, options = concrete_inputs
    original = json.loads(options["source_inventory_bytes"])
    for row in original:
        if row["path"] in {"Lib/abc.py", "Programs/_freeze_module.c"}:
            row["executable"] = True
    original.append(record("configure", b"#!/bin/sh\n", True))
    original.sort(key=lambda row: row["path"])
    options["source_inventory_bytes"] = canonical(original)
    options["expected_source_inventory_sha256"] = sha(options["source_inventory_bytes"])
    legacy = concrete.prepare_cpython_build_recipe(preparation, **options)
    successor = concrete.prepare_cpython_build_recipe_v4(preparation, **options)
    assert json.loads(successor.recipe_bytes)["inputs"] == json.loads(legacy.recipe_bytes)["inputs"]
    assert json.loads(successor.manifest_bytes)["original_source_inventory_sha256"] == (
        options["expected_source_inventory_sha256"])
    captured = capture.prepare_cpython_link_dependency_recipe_v4(preparation, **options)
    wire, _, _ = capture.validate_dependency_capture_plan_v4(captured.recipe_bytes, **_validation(captured))
    pins = {row["path"]: row for row in wire["inputs"]["source"]}
    for row in original:
        if row["path"] not in dict(captured.sources):
            assert pins[row["path"]] == row
    assert all(pins[path]["executable"] for path in ("configure", "Lib/abc.py", "Programs/_freeze_module.c"))


def test_standalone_successor_binds_original_profile_and_does_not_expand_commands(monkeypatch):
    base = base_recipe(sha(b"prep"), [record("unit.c", executable=True)],
                       [record("lib/crt.o"), record("zig", executable=True)])
    profile = profile_bytes()
    legacy = generate(monkeypatch, base, profile)
    monkeypatch.setattr(standalone_linker, "prepare_cpython_standalone_link_recipe", lambda *a, **kw: legacy)
    generated = standalone_linker.prepare_cpython_standalone_link_recipe_v4(
        object(), standalone_profile_bytes=profile, expected_standalone_profile_sha256=sha(profile), **_arguments())
    wire, _, _ = capture.validate_dependency_capture_plan_v4(generated.recipe_bytes, **_validation(generated, profile))
    assert wire["stages"] == json.loads(legacy.recipe_bytes)["stages"]
    assert json.loads(generated.manifest_bytes)["standalone_profile_sha256"] == sha(profile)
    with pytest.raises(capture.LinkDependencyError):
        capture.validate_dependency_capture_plan_v4(generated.recipe_bytes, **_validation(generated))
    altered = profile_bytes(linker=b"replacement")
    with pytest.raises(capture.LinkDependencyError):
        capture.validate_dependency_capture_plan_v4(generated.recipe_bytes, **_validation(generated, altered))


def test_legacy_recipe_schema_is_unchanged_by_successor_generation(vector):
    legacy, generated = vector
    assert json.loads(legacy.recipe_bytes)["schema"] == RECIPE_V3_SCHEMA
    assert "input_projection" not in json.loads(legacy.recipe_bytes)
    assert generated.sha256 != legacy.sha256
