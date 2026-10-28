"""Source-data v4 parsing and actual local FD/OCI metadata refusal checks.

These tests do not execute Podman, CPython, a model, or a candidate program.
The OCI vectors exercise observation validation and confer no custody authority.
"""

from __future__ import annotations

import copy
import json
import time

import pytest

from tests.test_static_python_link_dependency_capture import base_recipe, instrument, record, sha
from tests.test_static_python_podman_custody import runtime_vector
from tests.test_static_python_podman_helper_inputs import _elf, _write
from tests.test_static_python_rsi_execution_backend_v2 import (
    inert_v2_tool as inert_v2_tool,  # noqa: PLC0414
)
from tests.test_static_python_rsi_execution_backend_v2 import (
    v2_fixture as v2_fixture,  # noqa: PLC0414
)
from tools.static_python_rsi_fixture import execution_backend as execution
from tools.static_python_rsi_fixture import podman_custody as custody
from tools.static_python_rsi_fixture.runtime_closure import canonical


def data_payload(preparation_sha256=None, *, monkeypatch=None):
    original = base_recipe(
        preparation_sha256 or sha(b"preparation"),
        [record("configure", b"#!/not-an-executor\n", True), record("unit.c", b"unit", True)],
        [record("lib/crt.o", b"crt"), record("zig", _elf(), True)],
    )
    if monkeypatch is not None:
        # Runner fixtures need the actual finite compiler/linker capture graph,
        # including each linker depfile argv and declared output.
        original = instrument(monkeypatch, original)
    value = json.loads(original.recipe_bytes)
    value.update(schema=execution.RECIPE_V4_SCHEMA, input_projection=execution.INPUT_PROJECTION_V4)
    return value


def checked(value, **options):
    raw = canonical(value)
    return execution._recipe(raw, sha(raw), **options)


def test_explicit_v4_keeps_every_original_source_pin_and_execute_bit():
    value = data_payload()
    original = copy.deepcopy(value["inputs"])
    parsed = checked(value, version4=True)
    assert parsed["inputs"] == original
    assert all(row["executable"] is True for row in parsed["inputs"]["source"])
    assert canonical(parsed) == canonical(value)


@pytest.mark.parametrize("mode", [{}, {"version3": True}, {"version3": True, "version4": True}])
def test_legacy_and_mixed_parsers_never_accept_v4_wire(mode):
    with pytest.raises(execution.BuildExecutionError, match="recipe_shape_invalid"):
        checked(data_payload(), **mode)


@pytest.mark.parametrize("change", ["projection", "missing", "extra", "v3", "v2"])
def test_v4_parser_requires_its_own_exact_schema_and_projection(change):
    value = data_payload()
    if change == "projection":
        value["input_projection"] = "source-data-vaguely"
    elif change == "missing":
        del value["input_projection"]
    elif change == "extra":
        value["authority"] = True
    else:
        value["schema"] = execution.RECIPE_V3_SCHEMA if change == "v3" else execution.RECIPE_V2_SCHEMA
    with pytest.raises(execution.BuildExecutionError, match="recipe_shape_invalid"):
        checked(value, version4=True)


@pytest.mark.parametrize("path", ["configure", "unit.c"])
def test_source_execute_bit_does_not_grant_v4_argv_zero(path):
    value = data_payload()
    value["stages"][0]["commands"][0]["argv"][0] = "@source/" + path
    with pytest.raises(execution.BuildExecutionError, match="executable_not_pinned"):
        checked(value, version4=True)


def source_data_vector(tmp_path, monkeypatch):
    subject, root, current, argv, environment, spec = runtime_vector(tmp_path, monkeypatch)
    subject.source_data, subject.snapshot_mounts = True, True
    readonly = {role: tmp_path / role for role in ("source", "toolchain", "work")}
    for role, path in readonly.items():
        path.mkdir()
        spec["mounts"].append({"destination": custody._GUEST[role], "source": str(path),
                               "type": "bind", "options": ["ro", "noexec" if role == "source" else "exec",
                                                            "nosuid", "nodev"]})
    merged = tmp_path / "original-merged"
    merged.mkdir()
    spec["root"]["path"] = str(merged)
    selected = {"image": "a" * 64, "oci": str(root / "config.json"), "hostname": "", "hosts": "",
                "resolver": "/unused/runtime/metadata/resolv.conf", "rootfs": str(merged)}
    monkeypatch.setattr(subject, "_control", lambda *_args: canonical(selected))
    expected = custody._source_data_mount_roots(readonly, current, lambda: None)
    return subject, root, current, argv, environment, spec, readonly, expected, selected


def observed(vector):
    subject, root, current, argv, environment, spec, readonly, expected, _selected = vector
    (root / "config.json").write_bytes(canonical(spec))
    return subject._runtime_policy("b" * 64, "a" * 64, argv, environment, current, root, [], readonly,
                                   expected_view=expected)


def test_actual_v4_oci_view_binds_original_root_and_distinct_mount_objects(tmp_path, monkeypatch):
    vector = source_data_vector(tmp_path, monkeypatch)
    result = observed(vector)
    view = result["execution_view"]
    assert result["execution_view_sha256"] == sha(canonical(view))
    assert view["root"]["identity"]["inode"] == (tmp_path / "original-merged").stat().st_ino
    assert custody._execution_view_shape(view, result["readonly_snapshots"]) is True
    args = custody._readonly_volumes(vector[6], source_data=True)
    assert args[0].endswith(":/source:ro,noexec,nosuid,nodev")
    assert all(arg.endswith(":ro,exec,nosuid,nodev") for arg in args[1:])
    # Legacy mounts and source execute observations retain their old meaning.
    assert all(arg.endswith(":ro,exec,nosuid,nodev") for arg in custody._readonly_volumes(vector[6]))


@pytest.mark.parametrize("role", ["source", "toolchain", "work", "current_output"])
@pytest.mark.parametrize("change", ["mode", "source", "missing", "alias", "duplicate"])
def test_actual_v4_mount_drift_refuses_before_start(tmp_path, monkeypatch, role, change):
    vector = source_data_vector(tmp_path, monkeypatch)
    destination = custody.GUEST_CURRENT_ROOT if role == "current_output" else custody._GUEST[role]
    row = next(row for row in vector[5]["mounts"] if row["destination"] == destination)
    if change == "mode":
        bit = "noexec" if role in {"source", "current_output"} else "exec"
        row["options"].remove(bit)
        row["options"].append("exec" if bit == "noexec" else "noexec")
    elif change == "source":
        row["source"] = str(tmp_path / "unapproved-root")
    elif change == "missing":
        vector[5]["mounts"].remove(row)
    elif change == "alias":
        row["source"] = str(vector[6]["source"] if role != "source" else vector[6]["toolchain"])
    else:
        vector[5]["mounts"].append(copy.deepcopy(row))
    with pytest.raises(execution.BuildExecutionError, match="custody_(execution_view|runtime_)"):
        observed(vector)


@pytest.mark.parametrize("change", ["metadata", "oci", "symlink", "alias", "unknown-exec-alias"])
def test_v4_requires_actual_original_root_not_a_metadata_or_path_alias(tmp_path, monkeypatch, change):
    vector = source_data_vector(tmp_path, monkeypatch)
    if change == "metadata":
        vector[-1]["rootfs"] = str(vector[6]["source"])
    elif change == "oci":
        vector[5]["root"]["path"] = str(vector[6]["source"])
    elif change == "symlink":
        (tmp_path / "root-alias").symlink_to(tmp_path / "original-merged", target_is_directory=True)
        vector[5]["root"]["path"] = vector[-1]["rootfs"] = str(tmp_path / "root-alias")
    elif change == "alias":
        vector[5]["root"]["path"] = vector[-1]["rootfs"] = str(vector[6]["source"])
    else:
        vector[5]["mounts"].append({"destination": "/source-alias", "source": str(vector[6]["source"]),
                                   "type": "bind", "options": ["ro", "exec", "nosuid", "nodev"]})
    with pytest.raises((execution.BuildExecutionError, OSError)):
        observed(vector)


@pytest.mark.parametrize("change", ["replace", "symlink", "overlap"])
def test_mount_objects_must_remain_original_between_preparation_and_oci(tmp_path, monkeypatch, change):
    vector = source_data_vector(tmp_path, monkeypatch)
    source = vector[6]["source"]
    if change == "replace":
        source.rename(tmp_path / "retained-source")
        source.mkdir()
    elif change == "symlink":
        source.rmdir()
        source.symlink_to(vector[6]["toolchain"], target_is_directory=True)
    else:
        vector[6]["work"] = source / "nested"
        vector[6]["work"].mkdir()
    with pytest.raises((execution.BuildExecutionError, OSError)):
        observed(vector)


def test_source_scripts_remain_pinned_data_but_legacy_helper_gate_refuses_them(tmp_path):
    roots = {role: tmp_path / role for role in ("source", "toolchain", "work")}
    for root in roots.values():
        root.mkdir()
    inputs = {"source": [_write(roots["source"], "configure", b"#!/not-executed\n")],
              "toolchain": [_write(roots["toolchain"], "zig", _elf())]}
    before = (roots["source"] / "configure").read_bytes()
    custody._static_helper_inputs(inputs, roots, [], roots["work"], lambda: None, source_data=True)
    assert (roots["source"] / "configure").read_bytes() == before
    assert (roots["source"] / "configure").stat().st_mode & 0o777 == 0o555
    with pytest.raises(execution.BuildExecutionError, match="custody_static_executable"):
        custody._static_helper_inputs(inputs, roots, [], roots["work"], lambda: None)


@pytest.mark.parametrize("role", ["toolchain", "prior"])
@pytest.mark.parametrize("raw", [b"#!/implicit-interpreter\n", _elf(segments=(1, 3))])
def test_v4_implicit_tools_still_refuse_script_or_loader_inputs(tmp_path, role, raw):
    roots = {name: tmp_path / name for name in ("source", "toolchain", "work")}
    for root in roots.values():
        root.mkdir()
    inputs = {"source": [], "toolchain": [_write(roots["toolchain"], "zig", _elf())]}
    item = _write(roots["work" if role == "prior" else role], "implicit-helper", raw)
    prior = [item] if role == "prior" else []
    if role == "toolchain":
        inputs[role].append(item)
    with pytest.raises(execution.BuildExecutionError, match="custody_static_executable"):
        custody._static_helper_inputs(inputs, roots, prior, roots["work"], lambda: None, source_data=True)


@pytest.mark.parametrize("backend", [None, "podman", custody.SNAPSHOT_BACKEND, "host", True])
def test_v4_has_no_legacy_host_or_none_backend_fallback(v2_fixture, monkeypatch, backend):
    prep, source, tools, workspace, _payload = v2_fixture
    value = data_payload(prep.sha256)
    raw = canonical(value)
    monkeypatch.setattr(custody, "preflight_podman_custody", lambda: pytest.fail("preflight was touched"))
    with pytest.raises(execution.BuildExecutionError, match="custody_backend"):
        execution.run_pinned_build_v4(prep, recipe_bytes=raw, expected_recipe_sha256=sha(raw),
            source_root=source, toolchain_root=tools, workspace=workspace,
            deadline=time.monotonic() + 10, custody_backend=backend)
    assert not workspace.exists()


def test_v4_original_runner_copies_original_source_pins_then_persists_partial_report(v2_fixture, monkeypatch):
    prep, source, tools, workspace, _payload = v2_fixture
    value = data_payload(prep.sha256, monkeypatch=monkeypatch)
    for role, root in (("source", source), ("toolchain", tools)):
        for row in value["inputs"][role]:
            raw = {"configure": b"#!/not-an-executor\n", "unit.c": b"unit", "zig": _elf(), "lib/crt.o": b"crt"}[row["path"]]
            _write(root, row["path"], raw, executable=row["executable"])
    selected = []
    monkeypatch.setattr(custody, "preflight_podman_custody", lambda: ["not-executed"])

    def boundary(**kwargs):
        selected.append(kwargs)
        for row in value["inputs"]["source"]:
            assert execution._observe(kwargs["destination"] / "source", row["path"], 65536) == row
        raise execution.BuildExecutionError("selected_boundary")

    monkeypatch.setattr(custody, "PodmanCustody", boundary)
    raw = canonical(value)
    with pytest.raises(execution.BuildExecutionError, match="selected_boundary") as caught:
        execution.run_pinned_build_v4(prep, recipe_bytes=raw, expected_recipe_sha256=sha(raw),
            source_root=source, toolchain_root=tools, workspace=workspace, deadline=time.monotonic() + 10)
    assert len(selected) == 1 and selected[0]["snapshot_mounts"] is True and selected[0]["source_data"] is True
    persisted = json.loads((workspace / "report.json").read_bytes())
    assert persisted["schema"] == "lunar-static-python-build-execution-report-v4"
    assert persisted["input_projection"] == execution.INPUT_PROJECTION_V4
    assert caught.value.report.status == "partial" and persisted["completed_stages"] == []
    assert not any(persisted[name] for name in (
        "configured_closure_verified", "installation_accepted", "runtime_execution_performed",
        "production_admission", "immutable_custody_verified", "driver_inputs_verified",
        "implicit_link_inputs_verified", "online_publication"))


def custody_observation_vector(tmp_path, monkeypatch):
    vector = source_data_vector(tmp_path, monkeypatch)
    subject, root, current, _argv, environment, spec, readonly, _expected, _selected = vector
    # The retained role paths must be the original runner's actual layout.
    for role in ("source", "toolchain"):
        destination = subject.destination / role
        readonly[role].rename(destination)
        readonly[role] = destination
    readonly["work"].rename(root / "prior")
    readonly["work"] = root / "prior"
    for mount in spec["mounts"]:
        for role, path in readonly.items():
            if mount["destination"] == custody._GUEST[role]:
                mount["source"] = str(path)
    mutable = list(vector)
    mutable[7] = custody._source_data_mount_roots(readonly, current, lambda: None)
    policy = observed(tuple(mutable))
    planned = {"argv": ["@toolchain/zig", "cc"], "outputs": []}
    inputs = {"source": [record("configure", b"script", True)],
              "toolchain": [record("zig", _elf(), True)]}
    value = {
        "schema": "lunar-podman-build-command-observation-v2", "recipe_sha256": sha(b"recipe"),
        "stage": "configure", "index": 0, "original_argv_sha256": sha(canonical(planned["argv"])),
        "executed_argv": ["/toolchain/zig", "cc"],
        "executed_environment": custody._guest_build_environment(environment),
        "guest_roots": {**custody._GUEST, "current_output": "/out"},
        "input_layout": custody.SOURCE_DATA_BACKEND, "input_projection": execution.INPUT_PROJECTION_V4,
        "input_inventories_sha256": sha(canonical(inputs)),
        "source_inventory_sha256": sha(canonical(inputs["source"])),
        "toolchain_inventory_sha256": sha(canonical(inputs["toolchain"])),
        "prior_inventory_sha256": sha(canonical([])), "readback_outputs": [],
        "original_container_exit_confirmed": True, "container_creation_unknown": False,
        "seccomp_sha256": sha(canonical(custody._SECCOMP)),
        "container_id": "b" * 64, "image_id": "a" * 64, "runtime_policy": policy,
        "original_container_state": {"Status": "exited", "Running": False, "Pid": 0,
                                     "ExitCode": 0, "OOMKilled": False, "Error": ""},
    }
    for name in ("complete_namespace_disappearance_verified", "immutable_custody_verified",
                 "driver_inputs_verified", "installation_accepted", "production_admission",
                 "aggregate_output_hard_quota_verified", "configured_closure_verified",
                 "implicit_link_inputs_verified", "online_publication"):
        value[name] = False
    command = {"custody": value, "outputs": [], "direct_child_role": "original-podman-attach-client",
               "descendant_cleanup_verified": False}
    return subject, command, planned, inputs, environment


def validate_vector(vector):
    subject, command, planned, inputs, environment = vector
    custody.validate_custody_observation_v2(command, planned, "configure", 0, sha(b"recipe"),
        environment, inputs=inputs, prior=[], workspace=subject.destination)


def test_v2_detached_observation_binds_actual_original_workspace_roles(tmp_path, monkeypatch):
    vector = custody_observation_vector(tmp_path, monkeypatch)
    validate_vector(vector)
    with pytest.raises(ValueError, match="podman_custody_original_observation"):
        custody.validate_custody_observation(vector[1], vector[2], "configure", 0, sha(b"recipe"),
                                            vector[-1], custody.SNAPSHOT_BACKEND)


@pytest.mark.parametrize("change", ["inventory", "prior", "hash", "projection", "authority", "schema",
                                    "source-exec", "mount-replacement", "directory-replacement"])
def test_replaced_v2_observation_never_grants_original_roles(tmp_path, monkeypatch, change):
    vector = custody_observation_vector(tmp_path, monkeypatch)
    value = vector[1]["custody"]
    policy = value["runtime_policy"]
    if change == "inventory":
        value["source_inventory_sha256"] = sha(b"other-inventory")
    elif change == "prior":
        value["prior_inventory_sha256"] = sha(canonical([record("future-tool", b"future", True)]))
    elif change == "hash":
        policy["execution_view_sha256"] = sha(b"other-view")
    elif change == "projection":
        value["input_projection"] = "legacy"
    elif change == "authority":
        value["production_admission"] = True
    elif change == "schema":
        value["schema"] = "lunar-podman-build-command-observation-v1"
    elif change == "source-exec":
        policy["execution_view"]["mounts"][0]["options"].remove("noexec")
        policy["execution_view"]["mounts"][0]["options"].append("exec")
        policy["execution_view"]["mounts"][0]["options"].sort()
        policy["execution_view_sha256"] = sha(canonical(policy["execution_view"]))
    elif change == "mount-replacement":
        other = tmp_path / "substitute-source"
        other.mkdir()
        policy["readonly_snapshots"]["/source"] = str(other)
        policy["execution_view"]["mounts"][0].update(
            source=str(other), identity=custody._directory_identity(other, lambda: None))
        policy["execution_view_sha256"] = sha(canonical(policy["execution_view"]))
        assert custody._execution_view_shape(policy["execution_view"], policy["readonly_snapshots"])
    else:
        original = vector[0].destination / "source"
        original.rename(vector[0].destination / "retained-source")
        original.mkdir()
    with pytest.raises(ValueError, match="podman_custody_original_observation"):
        validate_vector(vector)


@pytest.mark.parametrize("stop", ["deadline", "interrupted"])
def test_v4_keeps_original_absolute_budget_and_cancellation_before_workspace(v2_fixture, monkeypatch, stop):
    prep, source, tools, workspace, _payload = v2_fixture
    raw = canonical(data_payload(prep.sha256, monkeypatch=monkeypatch))
    monkeypatch.setattr(custody, "preflight_podman_custody", lambda: ["not-executed"])
    options = {"deadline": time.monotonic() - 1 if stop == "deadline" else time.monotonic() + 10,
               "interrupted": (lambda: True) if stop == "interrupted" else None}
    with pytest.raises(execution.BuildExecutionError, match="deadline_expired" if stop == "deadline" else "interrupted"):
        execution.run_pinned_build_v4(prep, recipe_bytes=raw, expected_recipe_sha256=sha(raw),
            source_root=source, toolchain_root=tools, workspace=workspace, **options)
    assert not workspace.exists()


@pytest.mark.parametrize("role", ["toolchain", "prior"])
def test_v4_run_rechecks_implicit_native_helpers_on_each_command_before_image(tmp_path, monkeypatch, role):
    destination = tmp_path / "attempt"
    destination.mkdir()
    roots = {name: tmp_path / name for name in ("source", "toolchain", "work")}
    for root in roots.values():
        root.mkdir()
    inputs = {"source": [_write(roots["source"], "configure", b"#!/not-executed\n")],
              "toolchain": [_write(roots["toolchain"], "zig", _elf())]}
    target = roots["work" if role == "prior" else role]
    implicit = _write(target, "implicit", _elf())
    prior = [implicit] if role == "prior" else []
    if role == "toolchain":
        inputs["toolchain"].append(implicit)
    subject = custody.PodmanCustody(destination=destination, prefix=["not-executed"],
        recipe_sha256=sha(b"recipe"), checkpoint=lambda: None, snapshot_mounts=True, source_data=True)
    images = []

    class Boundary(BaseException):
        pass

    def image(**_kwargs):
        images.append(None)
        raise Boundary

    monkeypatch.setattr(subject, "_prepare_image", image)
    options = {"inputs": inputs, "snapshots": {role: roots[role] for role in ("source", "toolchain")},
               "prior": prior, "outputs": [], "work": roots["work"], "environment": {},
               "logs": subject.root, "evidence": {}, "stage": "configure"}
    with pytest.raises(Boundary):
        subject.run(["@toolchain/zig", "cc"], index=0, **options)
    assert len(images) == 1
    (target / "implicit").chmod(0o755)
    (target / "implicit").write_bytes(b"#!/a-new-loader\n")
    with pytest.raises(execution.BuildExecutionError, match="custody_static_executable"):
        subject.run(["@toolchain/zig", "cc"], index=1, **options)
    assert len(images) == 1 and not (subject.root / "configure-1").exists()
    with pytest.raises(execution.BuildExecutionError, match="custody_source_execution"):
        subject.run(["@source/configure"], index=2, **options)
    assert not (subject.root / "configure-2").exists()
