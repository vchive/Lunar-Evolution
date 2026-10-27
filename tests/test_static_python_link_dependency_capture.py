"""Finite recipe/output comparisons; no configured CPython build or admission."""

from __future__ import annotations

import hashlib
import json

import pytest

from tools.static_python_rsi_fixture import link_dependency_capture as capture
from tools.static_python_rsi_fixture.concrete_recipe import ConcreteBuildRecipe
from tools.static_python_rsi_fixture.dependency_capture import MAX_DEPFILE_BYTES
from tools.static_python_rsi_fixture.execution_backend import RECIPE_V3_SCHEMA
from tools.static_python_rsi_fixture.runtime_closure import canonical


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def record(path, raw=b"inert", executable=False):
    return {"path": path, "size": len(raw), "sha256": sha(raw), "executable": executable}


def base_recipe(preparation_sha256, source_records, tool_records):
    """Test-only small graph with the same fixed link command/capture contracts."""
    def output(path, executable=False):
        return {"path": path, "max_size": MAX_DEPFILE_BYTES, "executable": executable}

    def compile_command(target):
        dep = "dependencies/" + target + ".d"
        return {"argv": ["@toolchain/zig", "cc", "-c", "@source/unit.c", "-o", "@work/" + target,
                         "-MD", "-MF", "@work/" + dep, "-MQ", "@work/" + target],
                "outputs": [output(target), output(dep)]}

    def link_command(target, inputs):
        return {"argv": ["@toolchain/zig", "cc", "-target", "x86_64-linux-musl", "--zig-lib-dir",
                         "@toolchain-dir/lib", "-static", "-o", "@work/" + target,
                         *("@work/" + item for item in inputs), "-lm", "-lpthread", "-lc"],
                "outputs": [output(target, True)]}

    wire = {"schema": RECIPE_V3_SCHEMA, "preparation_sha256": preparation_sha256,
            "inputs": {"source": source_records, "toolchain": tool_records}, "environment": {},
            "stages": [
                {"stage": "configure", "commands": [compile_command("probe.o")]},
                {"stage": "freeze", "commands": [compile_command("objects/freezer.o"),
                    link_command("bin/lunar-freeze-module", ["objects/freezer.o"])]},
                {"stage": "compile", "commands": [compile_command("objects/target.o")]},
                {"stage": "link", "commands": [
                    {"argv": ["@toolchain/zig", "ar", "rcsD", "@work/libraries/python.a",
                              "@work/objects/freezer.o"], "outputs": [output("libraries/python.a")]},
                    link_command("bin/lunar-openevolve", ["objects/target.o", "libraries/python.a"])]},
            ]}
    return ConcreteBuildRecipe(canonical(wire), (), b"synthetic compiler recipe manifest")


def instrument(monkeypatch, base):
    monkeypatch.setattr(capture, "prepare_cpython_dependency_recipe", lambda *a, **kw: base)
    return capture.prepare_cpython_link_dependency_recipe(
        object(), source_inventory_bytes=b"", expected_source_inventory_sha256="",
        zig_manifest_bytes=b"", configuration_header=b"", expected_configuration_sha256="",
    )


@pytest.fixture
def vector(monkeypatch):
    base = base_recipe(sha(b"prep"), [record("unit.c")],
                       [record("lib/crt.o"), record("zig", executable=True)])
    generated = instrument(monkeypatch, base)
    wire = json.loads(generated.recipe_bytes)
    manifest = json.loads(generated.manifest_bytes)
    artifacts = {}
    for link in manifest["links"]:
        paths = ["/attempt/work/" + p.removeprefix("@work/") for p in link["explicit_inputs"]]
        paths.append("/attempt/toolchain/lib/crt.o")
        raw = ("/attempt/work/" + link["target"].removeprefix("@work/") + ": "
               + " ".join(paths) + "\n").encode()
        artifacts[link["depfile"]] = raw
    outputs = [record(out["path"], artifacts.get(out["path"], b"output"), out["executable"])
               for stage in wire["stages"] for command in stage["commands"] for out in command["outputs"]]
    raw = canonical(sorted(outputs, key=lambda out: out["path"]))
    kwargs = {"expected_recipe_sha256": generated.sha256, "manifest_bytes": generated.manifest_bytes,
              "expected_manifest_sha256": sha(generated.manifest_bytes), "output_inventory_bytes": raw,
              "expected_output_inventory_sha256": sha(raw), "dependency_artifacts": artifacts,
              "source_root": "/attempt/source", "toolchain_root": "/attempt/toolchain",
              "work_root": "/attempt/work"}
    return base, generated, kwargs


def compare(vector):
    return capture.compare_linker_dependencies(vector[1].recipe_bytes, **vector[2]).to_dict()


def update_artifact(vector, raw):
    kwargs = vector[2]
    path = next(iter(kwargs["dependency_artifacts"]))
    kwargs["dependency_artifacts"][path] = raw
    rows = json.loads(kwargs["output_inventory_bytes"])
    for row in rows:
        if row["path"] == path:
            row.update(size=len(raw), sha256=sha(raw))
    kwargs["output_inventory_bytes"] = canonical(rows)
    kwargs["expected_output_inventory_sha256"] = sha(kwargs["output_inventory_bytes"])


def test_successor_keeps_base_and_compiler_captures_unchanged(vector):
    base, generated, _ = vector
    assert b"--dependency-file" not in base.recipe_bytes
    manifest = json.loads(generated.manifest_bytes)
    assert len(manifest["compilations"]) == 3 and len(manifest["links"]) == 2
    assert manifest["base_recipe_sha256"] == base.sha256
    before, after = json.loads(base.recipe_bytes), json.loads(generated.recipe_bytes)
    for group0, group1 in zip(before["stages"], after["stages"], strict=True):
        for command0, command1 in zip(group0["commands"], group1["commands"], strict=True):
            if command1["argv"][-4:-1] == ["-Xlinker", "--dependency-file", "-Xlinker"]:
                assert command1["argv"][:-4] == command0["argv"]
                assert command1["outputs"][:-1] == command0["outputs"]
            else:
                assert command0 == command1
    assert manifest["immutable_custody_verified"] is manifest["production_admission"] is False


def test_implicit_pinned_crt_is_compared_but_no_driver_or_custody_authority(vector):
    result = compare(vector)
    assert len(result["links"]) == 2
    assert all("@toolchain/lib/crt.o" in link["dependencies"] for link in result["links"])
    assert result["implicit_link_inputs_verified"] is result["driver_inputs_verified"] is False
    assert result["production_admission"] is result["online_publication"] is False
    assert b"/attempt" not in canonical(result)


@pytest.mark.parametrize("replacement,reason", [
    (b"/usr/lib/crt1.o", "external"),
    (b"/attempt/toolchain/lib/unknown.a", "unpinned"),
    (b"/attempt/work/.zig-global-cache/compiler_rt.a", "unpinned"),
    (b"/attempt/work/bin/lunar-openevolve", "unpinned"),
    (b"/attempt/work/bin/lunar-freeze-module", "unpinned"),
    (b"/attempt/toolchain/../toolchain/lib/crt.o", "path"),
    (b"/attempt/toolchain-lookalike/lib/crt.o", "external"),
])
def test_unknown_ambient_cache_self_and_future_inputs_refuse(vector, replacement, reason):
    raw = next(iter(vector[2]["dependency_artifacts"].values()))
    update_artifact(vector, raw.replace(b"/attempt/toolchain/lib/crt.o", replacement))
    with pytest.raises(capture.LinkDependencyError, match=reason):
        compare(vector)


def test_missing_explicit_object_refuses_even_with_resigned_artifact(vector):
    update_artifact(vector, b"/attempt/work/bin/lunar-freeze-module: /attempt/toolchain/lib/crt.o\n")
    with pytest.raises(capture.LinkDependencyError, match="explicit_input_missing"):
        compare(vector)


@pytest.mark.parametrize("mutation", ["depfile_bytes", "missing_artifact", "extra_artifact", "missing_output",
                                     "manifest_capture", "bool_index", "false_claim", "capture_flag"])
def test_exact_manifest_output_and_original_report_pins_are_required(vector, mutation):
    _, generated, kwargs = vector
    if mutation == "depfile_bytes":
        kwargs["dependency_artifacts"][next(iter(kwargs["dependency_artifacts"]))] += b" "
    elif mutation == "missing_artifact":
        kwargs["dependency_artifacts"].pop(next(iter(kwargs["dependency_artifacts"])))
    elif mutation == "extra_artifact":
        kwargs["dependency_artifacts"]["extra.d"] = b"x: y\n"
    elif mutation == "missing_output":
        rows = json.loads(kwargs["output_inventory_bytes"])[1:]
        kwargs["output_inventory_bytes"] = canonical(rows)
        kwargs["expected_output_inventory_sha256"] = sha(kwargs["output_inventory_bytes"])
    elif mutation in {"manifest_capture", "bool_index", "false_claim"}:
        wire = json.loads(kwargs["manifest_bytes"])
        if mutation == "manifest_capture":
            wire["links"][0]["command_index"] += 1
        elif mutation == "bool_index":
            wire["links"][0]["command_index"] = True
        else:
            wire["driver_inputs_verified"] = True
        kwargs["manifest_bytes"] = canonical(wire)
        kwargs["expected_manifest_sha256"] = sha(kwargs["manifest_bytes"])
    else:
        wire = json.loads(generated.recipe_bytes)
        wire["stages"][1]["commands"][1]["argv"][-3] = "--not-a-dependency-file"
        raw = canonical(wire)
        vector = vector[0], ConcreteBuildRecipe(raw, (), b""), kwargs
        kwargs["expected_recipe_sha256"] = sha(raw)
    with pytest.raises(capture.LinkDependencyError):
        compare(vector)


def test_lld_empty_prerequisite_rules_and_make_escaping():
    assert capture.parse_linker_depfile(
        b"a\\ b: x\\ y.o \\\n z.a\n\nx\\ y.o:\nz.a:\n",
    ) == ("a b", ("x y.o", "z.a"))


@pytest.mark.parametrize("raw", [b"", b"a: b\nc: d\n", b"a: b\nb: c\n", b"a: b c\nb:\n",
                                  b"a: b\nb:\nb:\n", b"a: b\nother:\n", b"a: $(BAD)\n",
                                  b"a: \xff\n", b"a: b #private\n"])
def test_malformed_or_incomplete_phony_rules_refuse_without_disclosing_prose(raw):
    with pytest.raises(capture.LinkDependencyError) as error:
        capture.parse_linker_depfile(raw)
    assert error.value.__context__ is None
    assert "private" not in repr(error.value)
