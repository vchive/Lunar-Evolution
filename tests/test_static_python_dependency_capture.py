"""Actual inert compiler depfile plus pinned comparison and refusal tests."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess

import pytest

from tools.static_python_rsi_fixture import dependency_capture as capture
from tools.static_python_rsi_fixture.concrete_recipe import ConcreteBuildRecipe
from tools.static_python_rsi_fixture.execution_backend import RECIPE_V3_SCHEMA
from tools.static_python_rsi_fixture.runtime_closure import canonical


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def record(path, raw=b"inert", executable=False):
    return {"path": path, "size": len(raw), "sha256": sha(raw), "executable": executable}


@pytest.fixture
def vector(monkeypatch):
    source_records = [record(name) for name in ("Include/Python.h", "unit.c")]
    tool_records = [record("lib/include/stdint.h"), record("zig", executable=True)]
    stages = []
    for stage, output in (("configure", "probe.o"), ("freeze", "header.h"),
                          ("compile", "target.o"), ("link", "image")):
        argv = ["@toolchain/zig", "cc"]
        if stage == "compile":
            argv += ["-c", "@source/unit.c", "-o", "@work/" + output]
        else:
            argv += ["-o", "@work/" + output]
        stages.append({"stage": stage, "commands": [{"argv": argv, "outputs": [
            {"path": output, "max_size": 10000, "executable": stage == "link"},
        ]}]})
    recipe = canonical({"schema": RECIPE_V3_SCHEMA, "preparation_sha256": sha(b"prep"),
                        "inputs": {"source": source_records, "toolchain": tool_records},
                        "environment": {}, "stages": stages})
    base = ConcreteBuildRecipe(recipe, (("generated.c", b"inert"),), b"base manifest")
    monkeypatch.setattr(capture, "prepare_cpython_build_recipe", lambda *a, **kw: base)
    generated = capture.prepare_cpython_dependency_recipe(
        object(), source_inventory_bytes=b"", expected_source_inventory_sha256="",
        zig_manifest_bytes=b"", configuration_header=b"", expected_configuration_sha256="",
    )
    roots = {"source_root": "/attempt/source", "toolchain_root": "/attempt/toolchain",
             "work_root": "/attempt/work"}
    dep_path = "dependencies/target.o.d"
    dep = (b"/attempt/work/target.o: /attempt/source/unit.c \\\n"
           b" /attempt/source/Include/Python.h /attempt/toolchain/lib/include/stdint.h \\\n"
           b" /attempt/work/header.h\n")
    outputs = [record(name, executable=name == "image")
               for name in ("probe.o", "header.h", "target.o", "image")]
    outputs.append(record(dep_path, dep))
    output_raw = canonical(sorted(outputs, key=lambda r: r["path"]))
    return base, generated, dict(
        expected_recipe_sha256=generated.sha256, output_inventory_bytes=output_raw,
        expected_output_inventory_sha256=sha(output_raw), dependency_artifacts={dep_path: dep},
        **roots,
    )


def compare(vector):
    _, generated, kwargs = vector
    return capture.compare_compiler_dependencies(generated.recipe_bytes, **kwargs)


def update_dep(vector, raw):
    _, _, kwargs = vector
    path = next(iter(kwargs["dependency_artifacts"]))
    kwargs["dependency_artifacts"][path] = raw
    inventory = json.loads(kwargs["output_inventory_bytes"])
    for item in inventory:
        if item["path"] == path:
            item.update(size=len(raw), sha256=sha(raw))
    kwargs["output_inventory_bytes"] = canonical(inventory)
    kwargs["expected_output_inventory_sha256"] = sha(kwargs["output_inventory_bytes"])


def test_instrumentation_is_explicit_and_keeps_base_unchanged(vector):
    base, generated, _ = vector
    original = json.loads(base.recipe_bytes)
    wire = json.loads(generated.recipe_bytes)
    command = wire["stages"][2]["commands"][0]
    assert command["argv"][-5:] == ["-MD", "-MF", "@work/dependencies/target.o.d",
                                     "-MQ", "@work/target.o"]
    assert "-MD" not in original["stages"][2]["commands"][0]["argv"]
    assert wire["stages"][:2] == original["stages"][:2]
    assert wire["stages"][3] == original["stages"][3]
    assert generated.sources == base.sources
    manifest = json.loads(generated.manifest_bytes)
    assert manifest["base_recipe_sha256"] == base.sha256
    assert manifest["system_headers_included"] is True
    assert manifest["build_performed"] is manifest["immutable_custody_verified"] is False


def test_full_depfile_matches_pinned_source_toolchain_and_prior_generated(vector):
    result = compare(vector).to_dict()
    assert result["compilations"][0]["dependencies"] == [
        "@source/Include/Python.h", "@source/unit.c",
        "@toolchain/lib/include/stdint.h", "@work/header.h",
    ]
    assert result["implicit_link_inputs_verified"] is False
    assert result["immutable_custody_verified"] is False
    assert result["production_admission"] is False
    detached = result["compilations"]
    detached.clear()
    assert compare(vector).to_dict()["compilations"]


@pytest.mark.parametrize("stage_index", [0, 1])
def test_configuration_and_freezer_compilation_also_capture_system_headers(vector, monkeypatch, stage_index):
    base = vector[0]
    wire = json.loads(base.recipe_bytes)
    command = wire["stages"][stage_index]["commands"][0]
    command["argv"][2:2] = ["-c", "@source/unit.c"]
    raw = canonical(wire)
    monkeypatch.setattr(capture, "prepare_cpython_build_recipe", lambda *a, **kw: ConcreteBuildRecipe(
        raw, base.sources, base.manifest_bytes,
    ))
    generated = capture.prepare_cpython_dependency_recipe(
        object(), source_inventory_bytes=b"", expected_source_inventory_sha256="",
        zig_manifest_bytes=b"", configuration_header=b"", expected_configuration_sha256="",
    )
    manifest = json.loads(generated.manifest_bytes)
    assert [item["stage"] for item in manifest["captures"]] == [wire["stages"][stage_index]["stage"], "compile"]
    captured = json.loads(generated.recipe_bytes)
    assert "-MD" in captured["stages"][stage_index]["commands"][0]["argv"]
    assert captured["stages"][3] == wire["stages"][3]


@pytest.mark.parametrize("replacement,reason", [
    (b"/usr/include/stdio.h", "external"),
    (b"/attempt/source/unknown.h", "unpinned"),
    (b"/attempt/work/image", "unpinned"),
    (b"/attempt/work/target.o", "unpinned"),
    (b"/attempt/source/../source/unit.c", "path"),
    (b"/attempt/source//unit.c", "path"),
])
def test_unpinned_external_future_or_self_inputs_refused(vector, replacement, reason):
    dep = next(iter(vector[2]["dependency_artifacts"].values()))
    update_dep(vector, dep.replace(b"/attempt/source/Include/Python.h", replacement))
    with pytest.raises(capture.CompilerDependencyError, match=reason):
        compare(vector)


@pytest.mark.parametrize("mutation", ["missing", "extra", "wrong_bytes", "inventory", "no_capture"])
def test_artifact_and_output_binding_refused(vector, mutation):
    _, generated, kwargs = vector
    if mutation == "missing":
        kwargs["dependency_artifacts"].clear()
    elif mutation == "extra":
        kwargs["dependency_artifacts"]["extra.d"] = b"x: y\n"
    elif mutation == "wrong_bytes":
        path = next(iter(kwargs["dependency_artifacts"]))
        kwargs["dependency_artifacts"][path] += b" "
    elif mutation == "inventory":
        records = json.loads(kwargs["output_inventory_bytes"])
        records = [r for r in records if r["path"] != "image"]
        kwargs["output_inventory_bytes"] = canonical(records)
        kwargs["expected_output_inventory_sha256"] = sha(kwargs["output_inventory_bytes"])
    else:
        wire = json.loads(generated.recipe_bytes)
        wire["stages"][2]["commands"][0]["argv"] = wire["stages"][2]["commands"][0]["argv"][:-5]
        raw = canonical(wire)
        kwargs["expected_recipe_sha256"] = sha(raw)
        vector = vector[0], ConcreteBuildRecipe(raw, generated.sources, generated.manifest_bytes), kwargs
    with pytest.raises(capture.CompilerDependencyError):
        compare(vector)


@pytest.mark.parametrize("dep,reason", [
    (b"/other.o: /attempt/source/unit.c\n", "target"),
    (b"/attempt/work/target.o: /attempt/source/Include/Python.h\n", "source_missing"),
])
def test_exact_target_and_original_translation_unit_required(vector, dep, reason):
    update_dep(vector, dep)
    with pytest.raises(capture.CompilerDependencyError, match=reason):
        compare(vector)


@pytest.mark.parametrize("root", ["relative", "/", "/attempt/source/", "/attempt/../source",
                                  "/attempt/work", "/attempt/work/nested"])
def test_roots_must_be_exact_disjoint_absolute_paths(vector, root):
    vector[2]["source_root"] = root
    with pytest.raises(capture.CompilerDependencyError, match="roots"):
        compare(vector)


@pytest.mark.parametrize("raw", [
    b"", b"a b: c\n", b"a: b\nc: d\n", b"a: $(shell bad)\n", b"a: b #comment\n",
    b"a: b b\n", b"a: " + bytes([92]), b"a: b\\z\n", b"a:\n", b"a: b\0\n", b"a: \xff\n",
])
def test_make_variables_extra_rules_and_malformed_inputs_refused(raw):
    with pytest.raises(capture.CompilerDependencyError):
        capture.parse_compiler_depfile(raw)


def test_make_escaping_and_crlf():
    assert capture.parse_compiler_depfile(b"a\\ b.o: x\\ y.h \\\r\n c\\#d.h e$$f.h g\\:h.h\r\n") == (
        "a b.o", ("x y.h", "c#d.h", "e$f.h", "g:h.h"),
    )


def test_invalid_encoding_does_not_retain_raw_input_in_exception_context():
    with pytest.raises(capture.CompilerDependencyError) as error:
        capture.parse_compiler_depfile(b"private-file-\xff: header\n")
    assert error.value.__context__ is None
    assert "private" not in repr(error.value)


def test_real_local_inert_compiler_depfile(tmp_path):
    compiler = shutil.which("cc")
    assert compiler is not None, "local C compiler required by the native fixture suite"
    source = tmp_path / "source with space.c"
    header = tmp_path / "header with space.h"
    target = tmp_path / "target with space.o"
    depfile = tmp_path / "target.d"
    source.write_text('#include "header with space.h"\nint inert(void) { return VALUE; }\n')
    header.write_text("#define VALUE 7\n")
    subprocess.run([compiler, "-c", str(source), "-o", str(target), "-MD", "-MF", str(depfile),
                    "-MQ", str(target)], check=True, capture_output=True, timeout=30)
    actual_target, dependencies = capture.parse_compiler_depfile(depfile.read_bytes())
    assert actual_target == str(target)
    assert str(source) in dependencies and str(header) in dependencies


def test_no_raw_path_or_dependency_prose_in_errors(vector):
    update_dep(vector, b"/attempt/work/target.o: /secret/private-token.h\n")
    with pytest.raises(capture.CompilerDependencyError) as error:
        compare(vector)
    assert str(error.value) == "compiler_dependency_dependency_external"
    assert "secret" not in repr(error.value)
