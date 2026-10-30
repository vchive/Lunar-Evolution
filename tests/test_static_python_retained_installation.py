"""Synthetic retained histories, never CPython/custody/runtime acceptance.

The original custody observation validator is an explicit test double. The
original recipe/report parsers, real no-follow filesystem reads and expanded
installation checks remain active; no process or image is executed.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from lunar_evolution import static_python_fixed_profile as fixed
from tests.test_static_python_fixed_profile import _image, _vector
from tools.static_python_rsi_fixture import build_dependency_consumer as original
from tools.static_python_rsi_fixture import podman_custody as custody
from tools.static_python_rsi_fixture import retained_installation as candidate
from tools.static_python_rsi_fixture.execution_backend import (
    INPUT_PROJECTION_V4,
    RECIPE_V4_SCHEMA,
    BuildExecutionReport,
)
from tools.static_python_rsi_fixture.runtime_closure import canonical

BACKEND = "podman-snapshots-source-data-vfs-retained-v1"
PROFILE = "source-inventory-directories-v1"
FALSE = (
    "immutable_custody_verified", "driver_inputs_verified", "implicit_link_inputs_verified",
    "configured_closure_verified", "installation_accepted", "production_admission", "online_publication",
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def record(path, raw, executable=False):
    return {"path": path, "size": len(raw), "sha256": sha(raw), "executable": executable}


def write(root, path, raw, mode=0o600):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    target.chmod(mode)


@pytest.fixture
def history(tmp_path, monkeypatch, request):
    solver = getattr(request, "param", "openevolve")
    _unused, closure, _pins = _vector(solver, 93 if solver == "openevolve" else 103)
    sources, output_bytes = {}, {}

    def source(path):
        raw = sources.setdefault(path, ("synthetic unexecuted source:" + path).encode())
        return {"path": path, "size": len(raw), "sha256": sha(raw)}

    closure["sources"] = [source(row["path"]) for row in closure["sources"]]
    for unit in closure["frozen"] + closure["native_units"]:
        row = source(unit["source"])
        unit.update(source_size=row["size"], source_sha256=row["sha256"])
    for unit in closure["frozen"]:
        output_bytes[unit["output"]] = ("synthetic frozen header:" + unit["name"]).encode()
    for unit in closure["native_units"]:
        output_bytes["objects/" + unit["object"]] = ("synthetic object:" + unit["module"]).encode()
    sources["configuration/pyconfig.h"] = b"/* synthetic unaccepted pyconfig */\n"
    closure_raw = canonical(closure)
    sources["runtime/closure.json"] = closure_raw
    output_bytes["configuration/probe.o"] = b"synthetic probe object"
    output_bytes["bin/lunar-" + solver] = _image()
    source_rows = sorted([record(path, raw) for path, raw in sources.items()], key=lambda row: row["path"])
    tool_raw = b"synthetic never-executed tool"
    wire = {
        "schema": RECIPE_V4_SCHEMA, "input_projection": INPUT_PROJECTION_V4,
        "preparation_sha256": sha(b"synthetic unaccepted preparation"),
        "inputs": {"source": source_rows, "toolchain": [record("inert-tool", tool_raw, True)]},
        "environment": {"LANG": "C"}, "stages": [],
    }
    groups = (
        ("configure", ["configuration/probe.o"]),
        ("freeze", [unit["output"] for unit in closure["frozen"]]),
        ("compile", ["objects/" + unit["object"] for unit in closure["native_units"]]),
        ("link", ["bin/lunar-" + solver]),
    )
    stages = []
    for name, paths in groups:
        rows = [record(path, output_bytes[path], name == "link") for path in paths]
        planned = [{"path": row["path"], "max_size": len(output_bytes[row["path"]]) + 1024,
                    "executable": row["executable"]} for row in rows]
        wire["stages"].append({"stage": name, "commands": [
            {"argv": ["@toolchain/inert-tool"], "outputs": planned},
        ]})
        stages.append({"stage": name, "status": "complete", "commands": [
            {"index": 0, "status": "complete", "returncode": 0,
             "direct_child_reaped": True, "outputs": rows, "custody": {"synthetic": True}},
        ], "outputs": rows})
    workspace = tmp_path / "retained"
    controls = {"now": 10.0, "interrupt": False, "observations": 0}

    def custody_observation(command, planned, stage, index, recipe_sha256, environment, *,
                            inputs, prior, workspace, checkpoint=None):
        assert command["custody"] == {"synthetic": True}
        assert stage in {"configure", "freeze", "compile", "link"}
        assert index == 0 and inputs == wire["inputs"] and environment == wire["environment"]
        assert workspace == tmp_path / "retained"
        controls["observations"] += 1
        if checkpoint is not None:
            checkpoint()

    monkeypatch.setattr(custody, "validate_custody_observation_v4", custody_observation)
    recipe_raw = canonical(wire)
    report = BuildExecutionReport(sha(recipe_raw), tuple(name for name, _ in groups), tuple(stages), "complete", None)
    report_raw, outputs = original._report_outputs(
        report, wire, BACKEND, version4=True, workspace=workspace,
        checkpoint=lambda: None, vfs_roots=True, vfs_retained=True,
    )
    inventory_raw = canonical(outputs)
    common = {
        "recipe_sha256": sha(recipe_raw), "manifest_sha256": sha(b"synthetic pinned capture manifest"),
        "output_inventory_sha256": sha(inventory_raw), "input_projection": INPUT_PROJECTION_V4,
        "inputs_sha256": sha(canonical(wire["inputs"])),
    }
    compiler = {
        **common, **dict.fromkeys(FALSE, False),
        "schema": "lunar-cpython-compiler-dependency-comparison-v3",
        "dependency_path_profile": PROFILE, "compilations": [{"synthetic": True}],
        "source_directory_aliases": [],
    }
    linker = {
        **common, **dict.fromkeys(FALSE, False),
        "schema": "lunar-cpython-linker-dependency-comparison-v2", "links": [{"synthetic": True}],
    }
    dependency = {
        **common, **dict.fromkeys(FALSE, False),
        "schema": "lunar-actual-build-dependency-consumer-v5", "status": "compared",
        "custody_backend": BACKEND, "dependency_path_profile": PROFILE,
        "execution_report_sha256": sha(report_raw),
        "compiler_comparison_sha256": sha(canonical(compiler)),
        "linker_comparison_sha256": sha(canonical(linker)), "compilations": 1, "links": 1,
    }
    for path, raw in sources.items():
        write(workspace / "source", path, raw, 0o444)
    write(workspace / "toolchain", "inert-tool", tool_raw, 0o500)
    for row in outputs:
        write(workspace / "work", row["path"], output_bytes[row["path"]], 0o711 if row["executable"] else 0o600)
    for path, raw in {
        "report.json": report_raw, "dependency-output-inventory.json": inventory_raw,
        "dependency-report.json": canonical(dependency),
        "compiler-dependency-comparison.json": canonical(compiler),
        "linker-dependency-comparison.json": canonical(linker),
    }.items():
        write(workspace, path, raw)
    build = original.DependencyCheckedBuild(
        report, sha(canonical(dependency)), sha(canonical(compiler)), sha(canonical(linker)), sha(inventory_raw),
    )
    controls["observations"] = 0
    return {
        "build": build, "options": {
            "recipe_bytes": recipe_raw, "expected_recipe_sha256": sha(recipe_raw),
            "expected_manifest_sha256": common["manifest_sha256"],
            "expected_dependency_report_sha256": build.evidence_sha256,
            "runtime_closure": closure_raw, "expected_runtime_closure_sha256": sha(closure_raw),
            "expected_cpython_inventory_sha256": closure["cpython_inventory_sha256"],
            "expected_augmented_source_inventory_sha256": sha(canonical(source_rows)),
            "installation_version": "synthetic-retained-candidate-v1", "workspace": workspace,
            "deadline": 100.0, "monotonic": lambda: controls["now"],
            "interrupted": lambda: controls["interrupt"],
        }, "closure": closure, "wire": wire, "controls": controls, "sources": sources,
        "outputs": outputs, "output_bytes": output_bytes,
    }


def prepare(history, **overrides):
    return candidate.prepare_retained_fixed_installation_description(
        history["build"], **{**history["options"], **overrides})


def rewrite_history(history, name, change):
    root = history["options"]["workspace"]
    payload = json.loads((root / name).read_bytes())
    change(payload)
    raw = canonical(payload)
    write(root, name, raw)
    build = history["build"]
    if name in {"compiler-dependency-comparison.json", "linker-dependency-comparison.json"}:
        field = "compiler_comparison_sha256" if name.startswith("compiler") else "linker_comparison_sha256"
        history["build"] = replace(build, **{field: sha(raw)})
        rewrite_history(history, "dependency-report.json", lambda row: row.update({field: sha(raw)}))
    elif name == "dependency-report.json":
        history["build"] = replace(build, evidence_sha256=sha(raw))
        history["options"]["expected_dependency_report_sha256"] = sha(raw)


def refresh_report_bindings(history):
    """Re-sign synthetic originals, without changing the product's validators."""
    options, wire, build = history["options"], history["wire"], history["build"]
    root = options["workspace"]
    recipe_raw = canonical(wire)
    report = replace(build.execution_report, recipe_sha256=sha(recipe_raw))
    report_raw, outputs = original._report_outputs(
        report, wire, BACKEND, version4=True, workspace=root,
        checkpoint=lambda: None, vfs_roots=True, vfs_retained=True,
    )
    inventory_raw = canonical(outputs)
    common = {
        "recipe_sha256": sha(recipe_raw), "manifest_sha256": options["expected_manifest_sha256"],
        "output_inventory_sha256": sha(inventory_raw), "input_projection": INPUT_PROJECTION_V4,
        "inputs_sha256": sha(canonical(wire["inputs"])),
    }
    for name in ("compiler-dependency-comparison.json", "linker-dependency-comparison.json"):
        payload = json.loads((root / name).read_bytes())
        payload.update(common)
        write(root, name, canonical(payload))
    compiler_pin = sha((root / "compiler-dependency-comparison.json").read_bytes())
    linker_pin = sha((root / "linker-dependency-comparison.json").read_bytes())
    dependency = json.loads((root / "dependency-report.json").read_bytes())
    dependency.update(common, execution_report_sha256=sha(report_raw),
                      compiler_comparison_sha256=compiler_pin, linker_comparison_sha256=linker_pin)
    write(root, "dependency-report.json", canonical(dependency))
    write(root, "report.json", report_raw)
    write(root, "dependency-output-inventory.json", inventory_raw)
    history["build"] = original.DependencyCheckedBuild(
        report, sha(canonical(dependency)), compiler_pin, linker_pin, sha(inventory_raw))
    options.update(recipe_bytes=recipe_raw, expected_recipe_sha256=sha(recipe_raw),
                   expected_dependency_report_sha256=sha(canonical(dependency)),
                   expected_augmented_source_inventory_sha256=sha(canonical(wire["inputs"]["source"])))


@pytest.mark.parametrize("history", ["openevolve", "shinka"], indirect=True)
def test_complete_actual_records_map_to_existing_expanded_candidate_without_authority(history):
    result = prepare(history)
    value = result.to_dict()
    closure = history["closure"]
    assert value["profile_version"] == "fixed-" + closure["solver"] + "-v1"
    assert len(value["frozen_modules"]) == len(closure["frozen"])
    assert len(value["native_units"]) == len(closure["native_units"])
    assert [row["generator_id"] for row in value["frozen_modules"]] == [row["generator_id"] for row in closure["frozen"]]
    assert all(row["generated"]["sha256"] == sha(history["output_bytes"][row["generated"]["path"]])
               for row in value["frozen_modules"])
    assert value["image"]["mode"] == 0o711  # Actually observed, never inferred0755.
    assert value["image"]["sha256"] == sha(_image())
    assert all(flag is False for flag in value["claims"].values())
    assert result.production_admission is False and result.online_publication is False
    assert type(result) is not fixed.FixedPythonInstallation
    assert result.cpython_inventory_sha256 != result.augmented_source_inventory_sha256
    assert value["source_inventory_sha256"] == result.cpython_inventory_sha256
    assert result.sha256 == sha(result.candidate_bytes)
    assert not result.candidate_bytes.endswith(b"\n")
    assert history["controls"]["observations"] == 4
    with pytest.raises(FrozenInstanceError):
        result.candidate_bytes = b"changed"
    value["claims"]["production_admission"] = True
    assert result.to_dict()["claims"]["production_admission"] is False


@pytest.mark.parametrize("pin", [
    "expected_recipe_sha256", "expected_manifest_sha256", "expected_dependency_report_sha256",
    "expected_runtime_closure_sha256", "expected_cpython_inventory_sha256",
    "expected_augmented_source_inventory_sha256",
])
def test_each_independent_input_pin_mismatch_refuses(history, pin):
    with pytest.raises(candidate.RetainedInstallationDescriptionError):
        prepare(history, **{pin: sha(b"unrelated independent input")})


@pytest.mark.parametrize("value", [None, True, "0" * 64, "f" * 64, "A" * 64, "bad"])
def test_invalid_pin_refuses_before_filesystem_callback(history, monkeypatch, value):
    def forbidden(*_args, **_kwargs):
        pytest.fail("filesystem/control callback must follow preflight")
    monkeypatch.setattr(candidate, "_open_beneath", forbidden)
    with pytest.raises(candidate.RetainedInstallationDescriptionError, match="_pin$"):
        prepare(history, expected_recipe_sha256=value, monotonic=forbidden)


@pytest.mark.parametrize("field", ["recipe_bytes", "runtime_closure"])
@pytest.mark.parametrize("value", [b"", bytearray(b"not exact bytes"), "not bytes", b"x" * (16 * 1024 * 1024 + 1)])
def test_raw_bounds_precede_callbacks(history, field, value):
    def forbidden():
        pytest.fail("raw preflight must precede callbacks")
    with pytest.raises(candidate.RetainedInstallationDescriptionError, match="_raw$"):
        prepare(history, **{field: value}, monotonic=forbidden)


@pytest.mark.parametrize("change", [
    lambda build: replace(build, production_admission=True),
    lambda build: replace(build, immutable_custody_verified=True),
    lambda build: replace(build, execution_report=replace(build.execution_report, status="failed", reason="deadline")),
    lambda build: replace(build, execution_report=replace(build.execution_report, status="unknown", reason="unknown")),
    lambda build: replace(build, execution_report=replace(build.execution_report, completed_stages=("configure",))),
])
def test_original_failure_unknown_and_changed_claims_never_become_candidates(history, change):
    history["build"] = change(history["build"])
    with pytest.raises(candidate.RetainedInstallationDescriptionError):
        prepare(history)


@pytest.mark.parametrize("name", [
    "report.json", "dependency-output-inventory.json", "dependency-report.json",
    "compiler-dependency-comparison.json", "linker-dependency-comparison.json",
])
def test_every_persisted_history_file_is_bound_and_not_regenerated(history, name):
    path = history["options"]["workspace"] / name
    original_bytes = path.read_bytes()
    path.write_bytes(original_bytes + b" ")
    with pytest.raises(candidate.RetainedInstallationDescriptionError):
        prepare(history)
    assert path.read_bytes() == original_bytes + b" "


@pytest.mark.parametrize("change", [
    lambda row: row.update(schema="lunar-actual-build-dependency-consumer-v4"),
    lambda row: row.update(custody_backend="podman-snapshots-source-data-vfs-v1"),
    lambda row: row.update(dependency_path_profile="caller-normalizer"),
    lambda row: row.update(status="unknown"),
    lambda row: row.update(installation_accepted=True),
    lambda row: row.update(immutable_custody_verified=0),
    lambda row: row.update(compilations=True),
    lambda row: row.update(links=0),
    lambda row: row.update(extra="unknown field"),
])
def test_resigned_dependency_report_cannot_change_fixed_history_semantics(history, change):
    rewrite_history(history, "dependency-report.json", change)
    with pytest.raises(candidate.RetainedInstallationDescriptionError, match="_dependency_report$"):
        prepare(history)


@pytest.mark.parametrize("name", ["compiler-dependency-comparison.json", "linker-dependency-comparison.json"])
@pytest.mark.parametrize("field,value", [
    ("schema", "old-schema"), ("inputs_sha256", "a" * 64),
    ("output_inventory_sha256", "b" * 64), ("production_admission", True),
])
def test_resigned_comparison_stays_bound_to_original_inventory_and_false_claims(history, name, field, value):
    rewrite_history(history, name, lambda row: row.update({field: value}))
    with pytest.raises(candidate.RetainedInstallationDescriptionError, match="_comparison$"):
        prepare(history)


@pytest.mark.parametrize("role,path", [
    ("source", "configuration/pyconfig.h"), ("source", "runtime/closure.json"),
    ("source", "runtime/frozen_main.py"), ("toolchain", "inert-tool"),
    ("work", "configuration/probe.o"), ("work", "bin/lunar-openevolve"),
    ("work", "generated-sources/Python/frozen_modules/abc.h"), ("work", "objects/Modules/native_0.o"),
])
def test_actual_retained_input_output_drift_refuses(history, role, path):
    target = history["options"]["workspace"] / role / path
    target.chmod(0o700)
    target.write_bytes(b"changed actual bytes")
    with pytest.raises(candidate.RetainedInstallationDescriptionError):
        prepare(history)


@pytest.mark.parametrize("role,path", [
    ("source", "runtime/closure.json"), ("work", "bin/lunar-openevolve"),
    ("work", "generated-sources/Python/frozen_modules/abc.h"),
])
def test_symlink_with_equal_bytes_is_not_a_retained_regular_file(history, role, path):
    root = history["options"]["workspace"]
    target = root / role / path
    raw = target.read_bytes()
    external = root.parent / "external"
    external.write_bytes(raw)
    target.unlink()
    target.symlink_to(external)
    with pytest.raises(candidate.RetainedInstallationDescriptionError):
        prepare(history)


def test_symlink_in_parent_components_refuses_without_following(history):
    root = history["options"]["workspace"]
    moved = root / "old-work"
    (root / "work").rename(moved)
    (root / "work").symlink_to(moved, target_is_directory=True)
    with pytest.raises(candidate.RetainedInstallationDescriptionError):
        prepare(history)


@pytest.mark.parametrize("mode", [0o600, 0o4711, 0o2711])
def test_invalid_actual_image_modes_refuse_without_execution(history, mode):
    (history["options"]["workspace"] / "work/bin/lunar-openevolve").chmod(mode)
    with pytest.raises(candidate.RetainedInstallationDescriptionError):
        prepare(history)


@pytest.mark.parametrize("control,value,reason", [
    ("now", 100.0, "deadline"), ("now", 101.0, "deadline"),
    ("now", float("nan"), "control"), ("now", True, "control"),
    ("interrupt", True, "interrupted"), ("interrupt", 1, "control"),
])
def test_original_absolute_deadline_and_interruption_are_preserved(history, control, value, reason):
    history["controls"][control] = value
    with pytest.raises(candidate.RetainedInstallationDescriptionError, match="_" + reason + "$"):
        prepare(history)


def test_late_deadline_expiry_is_not_refreshed(history, monkeypatch):
    original_read = candidate._read_pin
    reads = []

    def expire_after_output(root, row, checkpoint, **kwargs):
        result = original_read(root, row, checkpoint, **kwargs)
        reads.append(row["path"])
        if row["path"] == "bin/lunar-openevolve":
            history["controls"]["now"] = 100.0
        return result

    monkeypatch.setattr(candidate, "_read_pin", expire_after_output)
    with pytest.raises(candidate.RetainedInstallationDescriptionError, match="_deadline$"):
        prepare(history)
    assert "bin/lunar-openevolve" in reads


def test_custody_refusal_is_never_skipped_or_replaced_with_candidate_claims(history, monkeypatch):
    def refuse(*_args, **_kwargs):
        raise ValueError("PRIVATE PATH should not escape")
    monkeypatch.setattr(custody, "validate_custody_observation_v4", refuse)
    with pytest.raises(candidate.RetainedInstallationDescriptionError) as error:
        prepare(history)
    assert "PRIVATE" not in str(error.value)
    assert error.value.__cause__ is None and error.value.__context__ is None


def test_candidate_preparation_neither_executes_nor_writes_or_reads_environment(history, monkeypatch):
    import subprocess

    def forbidden(*_args, **_kwargs):
        pytest.fail("candidate preparation must not execute, write or select environment")
    root = history["options"]["workspace"]
    before = {str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mode)
              for path in root.rglob("*") if path.is_file()}
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(os, "getenv", forbidden)
    monkeypatch.setattr(os, "write", forbidden)
    monkeypatch.setattr(Path, "write_bytes", forbidden)
    monkeypatch.setattr(original, "_write_once", forbidden)
    result = prepare(history)
    after = {str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mode)
             for path in root.rglob("*") if path.is_file()}
    assert before == after and result.production_admission is False


def test_cpython_and_augmented_inventory_pins_cannot_be_swapped(history):
    options = history["options"]
    with pytest.raises(candidate.RetainedInstallationDescriptionError, match="_augmented_source_inventory$"):
        prepare(history, expected_augmented_source_inventory_sha256=options["expected_cpython_inventory_sha256"])
    with pytest.raises(candidate.RetainedInstallationDescriptionError, match="_cpython_inventory$"):
        prepare(history, expected_cpython_inventory_sha256=options["expected_augmented_source_inventory_sha256"])


@pytest.mark.parametrize("path", [
    "generated-sources/Python/frozen_modules/abc.h", "objects/Modules/native_0.o",
])
def test_resigned_complete_report_cannot_omit_a_required_header_or_native_object(history, path):
    wire = history["wire"]
    report_stages = copy.deepcopy(history["build"].execution_report.stage_evidence)
    for group in wire["stages"]:
        for command in group["commands"]:
            command["outputs"] = [row for row in command["outputs"] if row["path"] != path]
    for group in report_stages:
        group["outputs"] = [row for row in group["outputs"] if row["path"] != path]
        for command in group["commands"]:
            command["outputs"] = [row for row in command["outputs"] if row["path"] != path]
    history["build"] = replace(history["build"], execution_report=replace(
        history["build"].execution_report, stage_evidence=report_stages))
    refresh_report_bindings(history)
    with pytest.raises(candidate.RetainedInstallationDescriptionError, match="_generated$"):
        prepare(history)


@pytest.mark.parametrize("kind", ["header", "object"])
def test_resigned_source_output_byte_reuse_refuses(history, kind):
    unit = history["closure"]["frozen" if kind == "header" else "native_units"][0]
    path = unit["output"] if kind == "header" else "objects/" + unit["object"]
    source_raw = history["sources"][unit["source"]]
    write(history["options"]["workspace"] / "work", path, source_raw)
    stages = copy.deepcopy(history["build"].execution_report.stage_evidence)
    for group in stages:
        for row in group["outputs"]:
            if row["path"] == path:
                row.update(size=len(source_raw), sha256=sha(source_raw))
        for command in group["commands"]:
            for row in command["outputs"]:
                if row["path"] == path:
                    row.update(size=len(source_raw), sha256=sha(source_raw))
    history["build"] = replace(history["build"], execution_report=replace(
        history["build"].execution_report, stage_evidence=stages))
    refresh_report_bindings(history)
    with pytest.raises(candidate.RetainedInstallationDescriptionError):
        prepare(history)


def test_late_image_mode_drift_refuses_even_when_executable_boolean_stays_true(history, monkeypatch):
    original_verify = fixed.verify_fixed_python_image

    def change_mode(*args, **kwargs):
        result = original_verify(*args, **kwargs)
        (history["options"]["workspace"] / "work/bin/lunar-openevolve").chmod(0o755)
        return result

    monkeypatch.setattr(fixed, "verify_fixed_python_image", change_mode)
    with pytest.raises(candidate.RetainedInstallationDescriptionError, match="_image$"):
        prepare(history)


def test_mode_and_bytes_are_read_from_the_same_held_image_fd(history, monkeypatch):
    original_fstat = os.fstat
    image_path = history["options"]["workspace"] / "work/bin/lunar-openevolve"
    target_ino = image_path.stat().st_ino
    seen = {"image": 0, "changed": False}
    original_read = candidate._read

    def replace_on_image_read(root, path, digest, checkpoint, **kwargs):
        if path != "bin/lunar-openevolve":
            return original_read(root, path, digest, checkpoint, **kwargs)

        def replace_after_open(fd):
            info = original_fstat(fd)
            if info.st_ino == target_ino and not seen["changed"]:
                seen["changed"] = True
                raw = image_path.read_bytes()
                image_path.rename(image_path.with_name("previous-image"))
                image_path.write_bytes(raw)
                image_path.chmod(0o711)
            return info

        with monkeypatch.context() as scope:
            scope.setattr(os, "fstat", replace_after_open)
            return original_read(root, path, digest, checkpoint, **kwargs)

    monkeypatch.setattr(candidate, "_read", replace_on_image_read)
    with pytest.raises(candidate.RetainedInstallationDescriptionError, match="_file$"):
        prepare(history)
    assert seen["changed"] is True


@pytest.mark.parametrize("mutation", ["zero", "executable"])
def test_resigned_header_requires_positive_nonexecutable_actual_output(history, mutation):
    path = "generated-sources/Python/frozen_modules/abc.h"
    report_stages = copy.deepcopy(history["build"].execution_report.stage_evidence)
    for group in report_stages:
        for row in group["outputs"] + [row for command in group["commands"] for row in command["outputs"]]:
            if row["path"] == path:
                if mutation == "zero":
                    row.update(size=0, sha256=sha(b""))
                else:
                    row["executable"] = True
    if mutation == "executable":
        for group in history["wire"]["stages"]:
            for command in group["commands"]:
                for row in command["outputs"]:
                    if row["path"] == path:
                        row["executable"] = True
    history["build"] = replace(history["build"], execution_report=replace(
        history["build"].execution_report, stage_evidence=report_stages))
    refresh_report_bindings(history)
    with pytest.raises(candidate.RetainedInstallationDescriptionError, match="_generated$"):
        prepare(history)


def test_duplicate_recipe_output_refuses_before_historical_output_projection(history):
    wire = history["wire"]
    group = wire["stages"][1]
    group["commands"][0]["outputs"].append(group["commands"][0]["outputs"][0].copy())
    raw = canonical(wire)
    with pytest.raises(candidate.RetainedInstallationDescriptionError):
        prepare(history, recipe_bytes=raw, expected_recipe_sha256=sha(raw))


def test_resigned_closure_cannot_select_other_solver_image(history):
    closure = copy.deepcopy(history["closure"])
    closure["solver"] = "shinka"
    raw = canonical(closure)
    with pytest.raises(candidate.RetainedInstallationDescriptionError, match="_image$"):
        prepare(history, runtime_closure=raw, expected_runtime_closure_sha256=sha(raw))
