"""Finite direct-LLD wiring; transport doubles prove no real Zig acceptance."""

from __future__ import annotations

import json

import pytest

from lunar_evolution.static_python_producer_completion_source import (
    COMPLETION_LAUNCHER_PATH,
    FIXED_PRODUCER_LIFECYCLE_PROFILE,
)
from lunar_evolution.static_python_producer_envelope_source import (
    ENVELOPE_LAUNCHER_PATH,
    FIXED_PRODUCER_ENVELOPE_PROFILE,
)
from tests import test_static_python_dependency_profile_selection as selection_tests
from tests.test_static_python_link_dependency_capture import base_recipe, record, sha
from tests.test_static_python_standalone_linker import elf_header
from tools.static_python_rsi_fixture import build_dependency_consumer as consumer
from tools.static_python_rsi_fixture import concrete_recipe as concrete
from tools.static_python_rsi_fixture import link_dependency_capture as capture
from tools.static_python_rsi_fixture import podman_custody as custody
from tools.static_python_rsi_fixture import zig_lld_linker as direct
from tools.static_python_rsi_fixture.command_input_graph import (
    BuildCommandInputError,
    validate_dependency_command_graph,
    validate_dependency_command_graph_v4,
)
from tools.static_python_rsi_fixture.execution_backend import (
    INPUT_PROJECTION_V4,
    RECIPE_V3_SCHEMA,
    BuildExecutionError,
    BuildExecutionReport,
)
from tools.static_python_rsi_fixture.runtime_closure import canonical

concrete_inputs = selection_tests.concrete_inputs


def profile_bytes(zig=b"inert", *, crt_mode="crt1-crti-crtn",
                  archives=("libc.a", "libcompiler_rt.a")):
    names = ["crt1.o", *archives]
    if crt_mode == "crt1-crti-crtn":
        names += ["crti.o", "crtn.o"]
    return canonical({
        "schema": direct.PROFILE_SCHEMA, "target": "x86_64-linux-musl",
        "linker_execution": "static-x86_64-elf", "crt_mode": crt_mode,
        "archives": list(archives),
        "inputs": sorted([record("zig", zig, True),
                          *(record("zig-lld/support/" + name) for name in names)],
                         key=lambda row: row["path"]),
    })


def generate(monkeypatch, base, profile):
    monkeypatch.setattr(capture, "prepare_cpython_dependency_recipe", lambda *a, **kw: base)
    sources = json.loads(base.recipe_bytes)["inputs"]["source"]
    source_inventory = canonical(sources)
    return direct.prepare_cpython_zig_lld_link_recipe_v4(
        object(), zig_lld_profile_bytes=profile, expected_zig_lld_profile_sha256=sha(profile),
        source_inventory_bytes=source_inventory,
        expected_source_inventory_sha256=sha(source_inventory), zig_manifest_bytes=b"",
        configuration_header=b"", expected_configuration_sha256="",
    )


def validation(generated, profile):
    return {"expected_recipe_sha256": generated.sha256, "manifest_bytes": generated.manifest_bytes,
            "expected_manifest_sha256": sha(generated.manifest_bytes),
            "zig_lld_profile_bytes": profile, "expected_zig_lld_profile_sha256": sha(profile)}


@pytest.fixture
def vector(monkeypatch):
    base = base_recipe(sha(b"prep"), [record("unit.c")],
                       [record("lib/crt.o"), record("zig", executable=True)])
    profile = profile_bytes()
    return base, generate(monkeypatch, base, profile), profile


def test_explicit_v4_preserves_original_zig_and_every_non_link_command(vector):
    base, generated, profile = vector
    before, after = json.loads(base.recipe_bytes), json.loads(generated.recipe_bytes)
    wire, compiler, linker = capture.validate_dependency_capture_plan_v4(
        generated.recipe_bytes, **validation(generated, profile))
    validate_dependency_command_graph_v4(wire)
    assert len(compiler) == 3 and len(linker) == 2
    assert [row for row in after["inputs"]["toolchain"] if row["path"] == "zig"] == [
        row for row in before["inputs"]["toolchain"] if row["path"] == "zig"]
    assert b"zig-lld" not in base.recipe_bytes and b"--dependency-file" not in base.recipe_bytes
    for old_stage, new_stage in zip(before["stages"], after["stages"], strict=True):
        for old, new in zip(old_stage["commands"], new_stage["commands"], strict=True):
            if old["argv"][:2] == ["@toolchain/zig", "cc"] and "-c" not in old["argv"]:
                assert new["argv"][:7] == ["@toolchain/zig", "ld.lld", "-m", "elf_x86_64",
                                          "-static", "--no-dynamic-linker", "-o"]
                assert new["outputs"][:-1] == old["outputs"]
                assert new["argv"][-2] == "--dependency-file"
            else:
                assert new == old
    manifest = json.loads(generated.manifest_bytes)
    assert manifest["link_mode"] == "zig-lld"
    assert manifest["zig_lld_profile_sha256"] == sha(profile)
    assert all(manifest[key] is False for key in capture._FALSE_CLAIMS)


def full_graph_profile(arguments):
    """Use the complete-graph fixture's explicit synthetic tool identity."""
    profile = json.loads(profile_bytes())
    original_zig = next(row for row in concrete.complete_zig_inventory(arguments["zig_manifest_bytes"])
                        if row["path"] == "zig")
    next(row for row in profile["inputs"] if row["path"] == "zig").update(original_zig)
    return canonical(profile)


@pytest.mark.parametrize("solver", ["openevolve", "shinka"])
@pytest.mark.parametrize("profile", [FIXED_PRODUCER_LIFECYCLE_PROFILE, FIXED_PRODUCER_ENVELOPE_PROFILE])
def test_complete_generator_graph_preserves_selected_producer_sources(concrete_inputs, solver, profile):
    # Only the shared fixture's tool inventory is synthetic. Neither the
    # compiler recipe emitter nor the new direct-link emitter is replaced.
    prep, arguments = concrete_inputs
    selection, sources = selection_tests._selection(prep, solver, profile)
    pinned = full_graph_profile(arguments)
    generated = direct.prepare_cpython_zig_lld_link_recipe_v4(
        prep, **arguments, **selection, zig_lld_profile_bytes=pinned,
        expected_zig_lld_profile_sha256=sha(pinned))
    wire, compiler, linker = capture.validate_dependency_capture_plan_v4(
        generated.recipe_bytes, **validation(generated, pinned))
    validate_dependency_command_graph_v4(wire)
    selected = ENVELOPE_LAUNCHER_PATH if profile == FIXED_PRODUCER_ENVELOPE_PROFILE else COMPLETION_LAUNCHER_PATH
    alternate = COMPLETION_LAUNCHER_PATH if profile == FIXED_PRODUCER_ENVELOPE_PROFILE else ENVELOPE_LAUNCHER_PATH
    compilations = [command for stage in wire["stages"] for command in stage["commands"]
                    if "-c" in command["argv"]]
    assert any("@source/" + selected in command["argv"] for command in compilations)
    assert not any("@source/" + alternate in command["argv"] for command in compilations)
    for path in (selected, "runtime/frozen_main.py", "producer/" + solver + "/lunar_fixed.py"):
        assert dict(generated.sources)[path] == sources[path]
    assert len(compiler) == len(compilations) and len(linker) == 2
    links = json.loads(generated.manifest_bytes)["links"]
    assert links[-1]["target"] == "@work/bin/lunar-" + solver
    assert all(json.loads(generated.manifest_bytes)[key] is False for key in capture._FALSE_CLAIMS)


def test_complete_generator_graph_omitted_and_none_keep_default_sources_identical(concrete_inputs):
    prep, arguments = concrete_inputs
    profile = full_graph_profile(arguments)
    options = {**arguments, "zig_lld_profile_bytes": profile,
               "expected_zig_lld_profile_sha256": sha(profile)}
    omitted = direct.prepare_cpython_zig_lld_link_recipe_v4(prep, **options)
    explicit_none = direct.prepare_cpython_zig_lld_link_recipe_v4(
        prep, **options, producer_lifecycle_profile=None)
    assert omitted == explicit_none
    assert b"@source/tools/static_python_rsi_fixture/assets/launcher.c" in omitted.recipe_bytes
    assert COMPLETION_LAUNCHER_PATH.encode() not in omitted.recipe_bytes
    assert ENVELOPE_LAUNCHER_PATH.encode() not in omitted.recipe_bytes


@pytest.mark.parametrize("crt_mode", ["crt1", "crt1-crti-crtn"])
def test_declared_crt_modes_and_complete_finite_archive_selection(monkeypatch, crt_mode):
    base = base_recipe(sha(b"prep"), [record("unit.c")],
                       [record("lib/crt.o"), record("zig", executable=True)])
    profile = profile_bytes(crt_mode=crt_mode,
                            archives=("libc.a", "libzigc.a", "libubsan_rt.a", "libcompiler_rt.a"))
    generated = generate(monkeypatch, base, profile)
    capture.validate_dependency_capture_plan_v4(generated.recipe_bytes, **validation(generated, profile))


@pytest.mark.parametrize("mutation", ["extra_key", "target", "loader", "crt", "missing_archive",
                                     "namespace", "support_executable", "archive_order"])
def test_profile_cannot_extend_target_execution_support_or_namespace(vector, monkeypatch, mutation):
    base, _, raw = vector
    profile = json.loads(raw)
    if mutation == "extra_key":
        profile["authority"] = True
    elif mutation == "target":
        profile["target"] = "host"
    elif mutation == "loader":
        profile["linker_execution"] = "ambient-loader"
    elif mutation == "crt":
        profile["crt_mode"] = "discovered"
    elif mutation == "missing_archive":
        profile["archives"].remove("libc.a")
    elif mutation == "namespace":
        profile["inputs"][1]["path"] = "standalone-linker/support/libc.a"
        profile["inputs"].sort(key=lambda row: row["path"])
    elif mutation == "support_executable":
        profile["inputs"][-1]["executable"] = True
    else:
        profile["archives"].reverse()
    with pytest.raises(direct.ZigLLDLinkerError):
        generate(monkeypatch, base, canonical(profile))


@pytest.mark.parametrize("mutation", ["missing_profile", "missing_pin", "wrong_pin",
                                     "resigned_profile", "resigned_recipe"])
def test_recipe_self_consistency_cannot_supply_independent_profile(vector, mutation):
    _, generated, profile = vector
    kwargs = validation(generated, profile)
    raw = generated.recipe_bytes
    if mutation == "missing_profile":
        kwargs.pop("zig_lld_profile_bytes")
    elif mutation == "missing_pin":
        kwargs.pop("expected_zig_lld_profile_sha256")
    elif mutation == "wrong_pin":
        kwargs["expected_zig_lld_profile_sha256"] = sha(b"different")
    elif mutation == "resigned_profile":
        kwargs["zig_lld_profile_bytes"] = profile_bytes(zig=b"replacement")
        kwargs["expected_zig_lld_profile_sha256"] = sha(kwargs["zig_lld_profile_bytes"])
    else:
        wire = json.loads(raw)
        row = next(row for row in wire["inputs"]["toolchain"] if row["path"] == "zig")
        row.update(size=len(b"replacement"), sha256=sha(b"replacement"))
        raw = canonical(wire)
        manifest = json.loads(kwargs["manifest_bytes"])
        manifest["recipe_sha256"] = sha(raw)
        kwargs.update(expected_recipe_sha256=sha(raw), manifest_bytes=canonical(manifest),
                      expected_manifest_sha256=sha(canonical(manifest)))
    with pytest.raises(capture.LinkDependencyError):
        capture.validate_dependency_capture_plan_v4(raw, **kwargs)


@pytest.mark.parametrize("mutation", ["changed_bytes", "non_executable", "namespace_overlap"])
def test_generator_binds_existing_complete_inventory_zig_row(vector, monkeypatch, mutation):
    base, _, profile = vector
    wire = json.loads(base.recipe_bytes)
    if mutation == "namespace_overlap":
        wire["inputs"]["toolchain"].append(record("zig-lld/support/libc.a"))
        wire["inputs"]["toolchain"].sort(key=lambda row: row["path"])
    else:
        row = next(row for row in wire["inputs"]["toolchain"] if row["path"] == "zig")
        if mutation == "changed_bytes":
            row.update(size=len(b"changed"), sha256=sha(b"changed"))
        else:
            row["executable"] = False
    changed = type(base)(canonical(wire), base.sources, base.manifest_bytes)
    expected_error = BuildExecutionError if mutation == "non_executable" else direct.ZigLLDLinkerError
    with pytest.raises(expected_error):
        generate(monkeypatch, changed, profile)


@pytest.mark.parametrize("mutation", ["basename", "subcommand", "search", "response",
                                     "joined_depfile", "missing_crt", "extra_archive"])
def test_profile_requires_only_fixed_subcommand_and_exact_direct_link_grammar(vector, mutation):
    _, generated, profile = vector
    wire = json.loads(generated.recipe_bytes)
    command = wire["stages"][1]["commands"][1]
    if mutation == "basename":
        command["argv"][:2] = ["@toolchain/ld.lld"]
    elif mutation == "subcommand":
        command["argv"][1] = "lld-link"
    elif mutation == "search":
        command["argv"].insert(-2, "-L/usr/lib")
    elif mutation == "response":
        command["argv"].insert(-2, "@toolchain/zig-lld/support/args.rsp")
    elif mutation == "joined_depfile":
        command["argv"][-2:] = ["--dependency-file=" + command["argv"][-1]]
    elif mutation == "missing_crt":
        command["argv"].remove("@toolchain/zig-lld/support/crti.o")
    else:
        command["argv"].insert(command["argv"].index("--end-group"), "@toolchain/lib/crt.o")
    with pytest.raises(direct.ZigLLDLinkerError):
        direct.validate_zig_lld_recipe_profile(wire, profile_bytes=profile,
                                              expected_profile_sha256=sha(profile))


def test_legacy_validator_cannot_upgrade_direct_lld_recipe(vector, tmp_path):
    _, generated, profile = vector
    with pytest.raises(BuildExecutionError):
        capture.validate_dependency_capture_plan(
            generated.recipe_bytes, expected_recipe_sha256=generated.sha256,
            manifest_bytes=generated.manifest_bytes,
            expected_manifest_sha256=sha(generated.manifest_bytes))
    legacy_wire = json.loads(generated.recipe_bytes)
    legacy_wire["schema"] = RECIPE_V3_SCHEMA
    del legacy_wire["input_projection"]
    with pytest.raises(BuildCommandInputError):
        validate_dependency_command_graph(legacy_wire)
    with pytest.raises(TypeError):
        consumer.run_dependency_checked_build(
            object(), recipe_bytes=generated.recipe_bytes, **validation(generated, profile),
            source_root=tmp_path / "source", toolchain_root=tmp_path / "tools",
            workspace=tmp_path / "attempt", deadline=100.0)


def lld_depfile(target, paths):
    """Actual LLD continuation/blank-line/complete-phony-rule output shape."""
    return (target + ": \\\n " + " \\\n ".join(paths) + "\n"
            + "".join("\n" + path + ":\n" for path in paths)).encode()


def comparison_vector(generated, profile):
    wire, manifest = json.loads(generated.recipe_bytes), json.loads(generated.manifest_bytes)
    artifacts = {}
    for link in manifest["links"]:
        paths = [ref.replace("@work/", "/attempt/work/").replace("@toolchain/", "/attempt/toolchain/")
                 for ref in link["explicit_inputs"]]
        artifacts[link["depfile"]] = lld_depfile(
            link["target"].replace("@work/", "/attempt/work/"), paths)
    outputs = [record(out["path"], artifacts.get(out["path"], b"output"), out["executable"])
               for stage in wire["stages"] for command in stage["commands"] for out in command["outputs"]]
    inventory = canonical(sorted(outputs, key=lambda row: row["path"]))
    return {**validation(generated, profile), "output_inventory_bytes": inventory,
            "expected_output_inventory_sha256": sha(inventory), "dependency_artifacts": artifacts,
            "source_root": "/attempt/source", "toolchain_root": "/attempt/toolchain", "work_root": "/attempt/work"}


def test_original_comparator_requires_both_genuine_exact_link_sets(vector):
    _, generated, profile = vector
    result = capture.compare_linker_dependencies_v4(
        generated.recipe_bytes, **comparison_vector(generated, profile)).to_dict()
    assert len(result["links"]) == 2
    assert all(result[key] is False for key in capture._FALSE_CLAIMS)


@pytest.mark.parametrize("mutation", ["missing", "extra_pinned", "external", "future", "target"])
def test_resigned_depfile_cannot_add_remove_or_redirect_actual_link_inputs(vector, mutation):
    _, generated, profile = vector
    kwargs = comparison_vector(generated, profile)
    path = next(iter(kwargs["dependency_artifacts"]))
    target, dependencies = capture.parse_linker_depfile(kwargs["dependency_artifacts"][path])
    dependencies = list(dependencies)
    if mutation == "missing":
        dependencies.remove("/attempt/toolchain/zig-lld/support/libc.a")
    elif mutation == "target":
        target = "/attempt/work/bin/other"
    else:
        extra = {"extra_pinned": "/attempt/toolchain/lib/crt.o", "external": "/usr/lib/private.a",
                 "future": "/attempt/work/bin/lunar-openevolve"}[mutation]
        dependencies.append(extra)
    raw = lld_depfile(target, dependencies)
    kwargs["dependency_artifacts"][path] = raw
    rows = json.loads(kwargs["output_inventory_bytes"])
    next(row for row in rows if row["path"] == path).update(size=len(raw), sha256=sha(raw))
    kwargs.update(output_inventory_bytes=canonical(rows), expected_output_inventory_sha256=sha(canonical(rows)))
    with pytest.raises(capture.LinkDependencyError):
        capture.compare_linker_dependencies_v4(generated.recipe_bytes, **kwargs)


@pytest.mark.parametrize("zig", [b"not-elf", elf_header(2), elf_header(3)])
def test_original_zig_static_gate_refuses_invalid_or_dynamic_inputs(tmp_path, zig):
    profile = profile_bytes(zig)
    path = tmp_path / "zig"
    path.write_bytes(zig)
    path.chmod(0o700)
    with pytest.raises(BuildExecutionError):
        direct.verify_zig_lld_linker_input(
            profile, expected_profile_sha256=sha(profile), toolchain_root=tmp_path, checkpoint=lambda: None)


@pytest.mark.parametrize("zig", [b"not-elf", elf_header(2), elf_header(3)])
def test_consumer_checks_same_pinned_zig_static_gate_before_any_runner(tmp_path, monkeypatch, zig):
    base = base_recipe(sha(b"prep"), [record("unit.c")],
                       [record("lib/crt.o"), record("zig", zig, True)])
    profile = profile_bytes(zig)
    generated = generate(monkeypatch, base, profile)
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "zig").write_bytes(zig)
    (tools / "zig").chmod(0o500)

    def no_dispatch(*args, **kwargs):
        pytest.fail("static format refusal must precede the original runner")

    monkeypatch.setattr(consumer, "run_pinned_build_v4", no_dispatch)
    workspace = tmp_path / "attempt"
    with pytest.raises(consumer.BuildDependencyError, match="execution_failed") as failure:
        consumer.run_dependency_checked_build_v4(
            object(), recipe_bytes=generated.recipe_bytes, **validation(generated, profile),
            source_root=tmp_path / "source", toolchain_root=tools, workspace=workspace,
            monotonic=lambda: 10.0, deadline=100.0)
    assert failure.value.execution_report is None
    assert not workspace.exists()


def test_original_zig_pin_is_read_before_and_after_static_gate(tmp_path, monkeypatch):
    zig = elf_header(1)
    profile = profile_bytes(zig)
    path = tmp_path / "zig"
    path.write_bytes(zig)
    path.chmod(0o700)
    original = custody._static_executable
    calls = []

    def drift(root, row, checkpoint):
        calls.append(row["path"])
        original(root, row, checkpoint)
        path.write_bytes(zig + b"changed after structural gate")

    monkeypatch.setattr(custody, "_static_executable", drift)
    path.write_bytes(zig + b"changed before structural gate")
    with pytest.raises(consumer.BuildDependencyError, match="file_pin"):
        direct.verify_zig_lld_linker_input(
            profile, expected_profile_sha256=sha(profile), toolchain_root=tmp_path, checkpoint=lambda: None)
    assert calls == []
    path.write_bytes(zig)
    with pytest.raises(consumer.BuildDependencyError, match="file_pin"):
        direct.verify_zig_lld_linker_input(
            profile, expected_profile_sha256=sha(profile), toolchain_root=tmp_path, checkpoint=lambda: None)
    assert calls == ["zig"]


@pytest.fixture
def transport(tmp_path, monkeypatch):
    """Only runner/OCI observations are doubles; all FD/depfile reads are real."""
    zig, source_raw = elf_header(1), b"inert source data"
    profile = profile_bytes(zig)
    source_records = [record("unit.c", source_raw, True)]
    tools = [record("lib/crt.o"), record("zig", zig, True)]
    base = base_recipe(sha(b"prep"), source_records, tools)
    generated = generate(monkeypatch, base, profile)
    wire, manifest = json.loads(generated.recipe_bytes), json.loads(generated.manifest_bytes)
    source, toolchain, workspace = tmp_path / "source", tmp_path / "tools", tmp_path / "attempt"
    source.mkdir()
    (source / "unit.c").write_bytes(source_raw)
    (source / "unit.c").chmod(0o500)
    for row in wire["inputs"]["toolchain"]:
        target = toolchain / row["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(zig if row["path"] == "zig" else b"inert")
        target.chmod(0o500 if row["executable"] else 0o400)
    controls = {"now": 10.0, "interrupt": False, "calls": 0, "drift": None, "backend": custody.SOURCE_DATA_BACKEND}
    observed = []

    def fake_observation(command, planned, stage, index, recipe_sha256, environment, *,
                         inputs, prior, workspace, checkpoint=None):
        assert command["custody"] == {"test_only_observation": True}
        assert recipe_sha256 == generated.sha256 and inputs == wire["inputs"]
        assert workspace == tmp_path / "attempt" and environment == wire["environment"]
        if checkpoint is not None:
            checkpoint()
        observed.append((stage, index, [dict(row) for row in prior]))

    for name in ("validate_custody_observation_v2", "validate_custody_observation_v3", "validate_custody_observation_v4"):
        monkeypatch.setattr(custody, name, fake_observation)

    def runner(preparation, **options):
        controls["calls"] += 1
        assert options["deadline"] == 100.0 and options["monotonic"] is kwargs["monotonic"]
        assert options["interrupted"] is kwargs["interrupted"]
        assert options["custody_backend"] == controls["backend"]
        for role, original_root in (("source", source), ("toolchain", toolchain)):
            for row in wire["inputs"][role]:
                target = workspace / role / row["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((original_root / row["path"]).read_bytes())
                target.chmod(0o555 if row["executable"] else 0o444)
        artifacts = {}
        for item in manifest["compilations"]:
            artifacts[item["depfile"]] = (
                "/out/" + item["target"].removeprefix("@work/") + ": /source/unit.c\n").encode()
        for item in manifest["links"]:
            paths = [ref.replace("@work/", "/work/").replace("@toolchain/", "/toolchain/")
                     for ref in item["explicit_inputs"]]
            artifacts[item["depfile"]] = (
                "/out/" + item["target"].removeprefix("@work/") + ": " + " ".join(paths) + "\n").encode()
        stages = []
        for group in wire["stages"]:
            commands, group_outputs = [], []
            for index, command in enumerate(group["commands"]):
                outputs = []
                for row in command["outputs"]:
                    raw = artifacts.get(row["path"], b"inert output")
                    target = workspace / "work" / row["path"]
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(raw)
                    target.chmod(0o700 if row["executable"] else 0o600)
                    outputs.append(record(row["path"], raw, row["executable"]))
                group_outputs.extend(outputs)
                commands.append({"index": index, "status": "complete", "returncode": 0,
                                 "direct_child_reaped": True, "outputs": outputs,
                                 "custody": {"test_only_observation": True}})
            stages.append({"stage": group["stage"], "status": "complete",
                           "commands": commands, "outputs": group_outputs})
        report = BuildExecutionReport(
            recipe_sha256=generated.sha256, completed_stages=("configure", "freeze", "compile", "link"),
            stage_evidence=tuple(stages), status="complete", reason=None,
        )
        backend = controls["backend"]
        version = 4 if backend == custody.SOURCE_DATA_BACKEND else 5 if backend.endswith("vfs-v1") else 6
        value = {"schema": "lunar-static-python-build-execution-report-v" + str(version),
                 "recipe_sha256": generated.sha256, "completed_stages": list(report.completed_stages),
                 "stage_evidence": stages, "status": "complete", "reason": None,
                 "configured_closure_verified": False, "installation_accepted": False,
                 "runtime_execution_performed": False, "production_admission": False,
                 "input_projection": INPUT_PROJECTION_V4, "immutable_custody_verified": False,
                 "driver_inputs_verified": False, "implicit_link_inputs_verified": False, "online_publication": False}
        if version != 4:
            value["custody_backend"] = backend
        (workspace / "report.json").write_bytes(canonical(value))
        if controls["drift"] == "report":
            value["input_projection"] = "unreviewed"
            (workspace / "report.json").write_bytes(canonical(value))
        elif controls["drift"] == "output":
            (workspace / "work/objects/target.o").write_bytes(b"replaced")
        elif controls["drift"] == "zig":
            (toolchain / "zig").chmod(0o700)
            (toolchain / "zig").write_bytes(b"replacement")
            (toolchain / "zig").chmod(0o500)
        elif controls["drift"] == "deadline":
            controls["now"] = 100.0
        elif controls["drift"] == "interrupt":
            controls["interrupt"] = True
        return report

    for name in ("run_pinned_build_v4", "run_pinned_build_v4_vfs", "run_pinned_build_v4_vfs_retained"):
        monkeypatch.setattr(consumer, name, runner)
    kwargs = {"recipe_bytes": generated.recipe_bytes, **validation(generated, profile),
              "source_root": source, "toolchain_root": toolchain, "workspace": workspace,
              "deadline": 100.0, "monotonic": lambda: controls["now"], "interrupted": lambda: controls["interrupt"]}
    return kwargs, wire, controls, observed


@pytest.mark.parametrize("api,backend,version", [
    (consumer.run_dependency_checked_build_v4, custody.SOURCE_DATA_BACKEND, 2),
    (consumer.run_dependency_checked_build_v4_vfs, "podman-snapshots-source-data-vfs-v1", 3),
    (consumer.run_dependency_checked_build_v4_vfs_retained, "podman-snapshots-source-data-vfs-retained-v1", 4),
])
def test_three_v4_consumers_transport_profile_through_original_single_runner(transport, api, backend, version):
    kwargs, wire, controls, observed = transport
    controls["backend"] = backend
    result = api(object(), **kwargs)
    evidence = json.loads((kwargs["workspace"] / "dependency-report.json").read_bytes())
    assert controls["calls"] == 1
    assert evidence["schema"] == "lunar-actual-build-dependency-consumer-v" + str(version)
    assert evidence["inputs_sha256"] == sha(canonical(wire["inputs"]))
    assert evidence["execution_report_sha256"] == sha((kwargs["workspace"] / "report.json").read_bytes())
    assert evidence["compilations"] == 3 and evidence["links"] == 2
    prior = []
    for stage in result.execution_report.stage_evidence:
        for command in stage["commands"]:
            observed_stage, index, inputs = observed.pop(0)
            assert (observed_stage, index, inputs) == (stage["stage"], command["index"], prior)
            prior = [*prior, *command["outputs"]]
    assert not observed
    assert all(evidence[key] is False for key in (
        "immutable_custody_verified", "driver_inputs_verified", "implicit_link_inputs_verified",
        "installation_accepted", "production_admission", "online_publication"))


@pytest.mark.parametrize("drift,reason", [("report", "file_pin"), ("output", "file_pin"),
                                         ("zig", "file_pin"), ("deadline", "deadline_expired"),
                                         ("interrupt", "interrupted")])
def test_readback_or_control_failure_retains_original_report_without_retry(transport, drift, reason):
    kwargs, _, controls, _ = transport
    controls["drift"] = drift
    with pytest.raises(consumer.BuildDependencyError, match=reason) as failure:
        consumer.run_dependency_checked_build_v4(object(), **kwargs)
    assert controls["calls"] == 1 and failure.value.execution_report.status == "complete"
    assert (kwargs["workspace"] / "report.json").is_file()
    assert not (kwargs["workspace"] / "dependency-report.json").exists()
