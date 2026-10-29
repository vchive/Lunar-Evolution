"""Explicit VFS custody routing and original report-consumer cross-pins.

Only inert service/OCI vectors run; these tests do not claim Podman acceptance.
"""

from __future__ import annotations

import copy

import pytest

from tests.test_static_python_podman_vfs_root import CID, IMAGE, vfs_vector
from tests.test_static_python_source_data_backend import source_data_vector
from tools.static_python_rsi_fixture import podman_custody as custody
from tools.static_python_rsi_fixture import podman_vfs_root as vfs
from tools.static_python_rsi_fixture.execution_backend import BuildExecutionError
from tools.static_python_rsi_fixture.runtime_closure import canonical


@pytest.fixture
def vector(tmp_path, monkeypatch):
    original = source_data_vector(tmp_path, monkeypatch)
    vfs_base = tmp_path / "vfs"
    vfs_base.mkdir()
    data = vfs_vector(vfs_base)
    subject, _root, _current, _argv, _environment, spec, _readonly, _expected, _selected = original
    subject.vfs_roots = True
    spec["root"]["path"] = str(data.root)
    data.oci.write_bytes(canonical(spec))
    events = []

    def control(args, name, _root, _operations):
        events.append(name)
        if args[0] == "info":
            return canonical(data.info)
        assert args[0] == "inspect" and "{{json .ID}}" in args[4]
        assert "MergedDir" not in args[4]
        return canonical(data.selected)

    monkeypatch.setattr(subject, "_control", control)
    monkeypatch.setattr(subject, "_service_pid", lambda name, *_args: events.append(name) or 1234)
    data.service.verify = lambda: events.append("service-verify")
    data.service.close = lambda: events.append("service-close")
    data.service.pid = 1234
    monkeypatch.setattr(vfs, "ServiceRoot", lambda pid, checkpoint: data.service)
    from pathlib import Path

    monkeypatch.setattr(vfs, "mount_table", lambda _pid, _check: ("d" * 64, [Path("/")]))
    try:
        yield original, data, events
    finally:
        import os

        os.close(data.service.root_fd)


def observe(vector):
    original, _data, _events = vector
    subject, root, current, argv, environment, _spec, readonly, expected, _selected = original
    return subject._runtime_policy(CID, IMAGE, argv, environment, current, root, [], readonly,
                                   expected_view=expected)


def test_explicit_vfs_route_binds_service_root_before_original_runtime_policy(vector):
    result = observe(vector)
    _original, data, events = vector
    proof, view = result["root_acquisition"], result["execution_view"]
    assert proof["root"] == {"path": view["root"]["path"], "identity": view["root"]["identity"]}
    assert result["root_acquisition_sha256"] == custody._pin(canonical(proof))
    assert proof["root"]["path"] == str(data.root)
    assert events == ["vfs-service-before", "vfs-store-selection", "runtime-selection",
                      "service-verify", "vfs-service-after", "service-verify", "service-close"]
    assert result["root_readonly"] and result["fixed_seccomp_verified"]


@pytest.mark.parametrize("change", ["driver", "service-pid", "service-drift", "root-after-acquire",
                                    "workspace-after-acquire", "oci-location"])
def test_vfs_acquisition_failure_closes_original_service_and_never_falls_back(vector, monkeypatch, change):
    original, data, events = vector
    subject = original[0]
    if change == "driver":
        data.info["driver"] = "overlay"
    elif change == "service-pid":
        monkeypatch.setattr(subject, "_service_pid", lambda name, *_args: 1234 if name.endswith("before") else 1235)
    elif change == "service-drift":
        def drift():
            raise BuildExecutionError("custody_vfs_service_drift")

        data.service.verify = drift
    elif change in {"root-after-acquire", "workspace-after-acquire"}:
        original_acquire = vfs.acquire

        def replacement(*args, **kwargs):
            result = original_acquire(*args, **kwargs)
            path = data.root if change == "root-after-acquire" else original[6]["source"]
            path.rename(path.with_name(path.name + "-retained"))
            path.mkdir()
            return result

        monkeypatch.setattr(vfs, "acquire", replacement)
    else:
        data.selected["oci"] = str(data.oci.with_name("substitute.json"))
    with pytest.raises(BuildExecutionError, match="custody_(vfs|execution_view)"):
        observe(vector)
    assert events[-1] == "service-close"
    assert "start-attach" not in events
    assert events.count("runtime-selection") <= 1


@pytest.mark.parametrize("options", [
    {"vfs_roots": True}, {"snapshot_mounts": True, "vfs_roots": True},
    {"snapshot_mounts": True, "source_data": True, "vfs_roots": 1},
])
def test_vfs_mode_requires_explicit_source_data_and_snapshot_profile(tmp_path, options):
    with pytest.raises(BuildExecutionError, match="custody_vfs_mode"):
        custody.PodmanCustody(destination=tmp_path, prefix=["never-executed"], recipe_sha256="a" * 64,
                             checkpoint=lambda: None, **options)


def observation(vector):
    policy = observe(vector)
    original, _data, _events = vector
    subject, _root, _current, _argv, environment, _spec, _readonly, _expected, _selected = original
    inputs = {"source": [], "toolchain": []}
    planned = {"argv": ["@toolchain/zig", "cc"], "outputs": []}
    value = {
        "schema": "lunar-podman-build-command-observation-v3",
        "recipe_sha256": subject.recipe_sha256, "stage": "configure", "index": 0,
        "original_argv_sha256": custody._pin(canonical(planned["argv"])),
        "executed_argv": ["/toolchain/zig", "cc"],
        "executed_environment": custody._guest_build_environment(environment),
        "guest_roots": {**custody._GUEST, "current_output": custody.GUEST_CURRENT_ROOT},
        "input_layout": custody.SOURCE_DATA_VFS_BACKEND, "readback_outputs": [],
        "original_container_exit_confirmed": True, "container_creation_unknown": False,
        "seccomp_sha256": custody._pin(canonical(custody._SECCOMP)), "container_id": CID, "image_id": IMAGE,
        "root_acquisition_profile": "podman-vfs-root-v1", "runtime_policy": policy,
        "input_projection": custody.INPUT_PROJECTION_V4,
        "input_inventories_sha256": custody._pin(canonical(inputs)),
        "source_inventory_sha256": custody._pin(canonical(inputs["source"])),
        "toolchain_inventory_sha256": custody._pin(canonical(inputs["toolchain"])),
        "prior_inventory_sha256": custody._pin(canonical([])),
        "original_container_state": {"Status": "exited", "Running": False, "Pid": 0,
                                     "ExitCode": 0, "OOMKilled": False, "Error": ""},
    }
    value.update(dict.fromkeys(("configured_closure_verified", "implicit_link_inputs_verified", "online_publication",
        "complete_namespace_disappearance_verified", "immutable_custody_verified", "driver_inputs_verified",
        "installation_accepted", "production_admission", "aggregate_output_hard_quota_verified"), False))
    command = {"custody": value, "outputs": [], "direct_child_role": "original-podman-attach-client",
               "descendant_cleanup_verified": False}
    # Reconstruct the exact persisted runner workspace roots required by v2.
    workspace = subject.destination
    for role in ("source", "toolchain"):
        old = original[6][role]
        old.rename(workspace / role)
    command_root = workspace / "custody/configure-0"
    original[6]["work"].rename(command_root / "prior")
    for row in policy["execution_view"]["mounts"]:
        if row["role"] == "current_output":
            continue
        path = workspace / row["role"] if row["role"] != "work" else command_root / "prior"
        row["source"] = str(path)
        row["identity"] = custody._directory_identity(path, lambda: None)
        policy["readonly_snapshots"][row["destination"]] = str(path)
    policy["execution_view_sha256"] = custody._pin(canonical(policy["execution_view"]))
    return command, planned, inputs, workspace, subject.recipe_sha256, environment


def validate(vector):
    command, planned, inputs, workspace, recipe_sha, environment = vector
    custody.validate_custody_observation_v3(command, planned, "configure", 0, recipe_sha, environment,
                                           inputs=inputs, prior=[], workspace=workspace)


def test_v3_consumer_validates_root_proof_and_retains_original_four_workspace_checks(vector):
    value = observation(vector)
    validate(value)
    with pytest.raises(ValueError, match="observation_v2"):
        custody.validate_custody_observation_v2(value[0], value[1], "configure", 0, value[4], value[5],
                                               inputs=value[2], prior=[], workspace=value[3])


@pytest.mark.parametrize("change", ["schema", "backend", "profile", "digest", "container", "image",
                                    "root", "proof-shape", "false-claim", "workspace", "ancillary", "mount-table"])
def test_v3_consumer_rejects_drift_even_with_self_consistent_proof_digest(vector, change):
    value = observation(vector)
    command = value[0]
    observation_value = command["custody"]
    policy = observation_value["runtime_policy"]
    proof = policy["root_acquisition"]
    if change == "schema":
        observation_value["schema"] = "lunar-podman-build-command-observation-v2"
    elif change == "backend":
        observation_value["input_layout"] = custody.SOURCE_DATA_BACKEND
    elif change == "profile":
        observation_value["root_acquisition_profile"] = "caller-root"
    elif change == "digest":
        policy["root_acquisition_sha256"] = "d" * 64
    elif change == "container":
        proof["container_id"] = "d" * 64
    elif change == "image":
        proof["image_id"] = "d" * 64
    elif change == "root":
        proof["root"]["identity"]["inode"] += 1
    elif change == "proof-shape":
        proof["accepted"] = True
    elif change == "false-claim":
        observation_value["production_admission"] = True
    elif change == "ancillary":
        proof["ancillary_mounts"][0]["sha256"] = "d" * 64
    elif change == "mount-table":
        proof["mount_tables"]["service_sha256"] = True
    else:
        path = value[3] / "source"
        path.rename(path.with_name("retained-source"))
        path.mkdir()
    if change != "digest":
        policy["root_acquisition_sha256"] = custody._pin(canonical(proof))
    with pytest.raises(ValueError, match="observation"):
        validate(value)


@pytest.mark.parametrize("change", ["identity", "bytes"])
def test_service_private_ancillary_file_alias_refuses_before_runtime_start(vector, monkeypatch, change):
    original, data, events = vector
    resolver = original[1] / "fixed-resolv.conf"
    if change == "identity":
        actual = vfs.file_identity_at

        def alias(root_fd, path, *args):
            result = actual(root_fd, path, *args)
            if root_fd == data.service.root_fd and path == resolver:
                result["inode"] += 1
            return result

        monkeypatch.setattr(vfs, "file_identity_at", alias)
    else:
        actual = vfs.read_at

        def alias(root_fd, path, *args):
            if root_fd == data.service.root_fd and path == resolver:
                return b"x"
            return actual(root_fd, path, *args)

        monkeypatch.setattr(vfs, "read_at", alias)
    with pytest.raises(BuildExecutionError, match="custody_vfs_namespace_view"):
        observe(vector)
    assert events[-1] == "service-close" and "start-attach" not in events


def test_ancillary_drift_after_service_acquisition_refuses_before_start(vector, monkeypatch):
    original, data, events = vector
    path = data.oci.parent / ".containerenv"
    path.write_bytes(b"original")
    original[5]["mounts"].append({"destination": "/run/.containerenv", "source": str(path), "type": "bind",
                                   "options": ["ro", "noexec", "nosuid", "nodev"]})
    data.oci.write_bytes(canonical(original[5]))
    selection = original[0]._vfs_selection

    def changed(*args, **options):
        result = selection(*args, **options)
        path.write_bytes(b"changed")
        return result

    monkeypatch.setattr(original[0], "_vfs_selection", changed)
    with pytest.raises(BuildExecutionError, match="custody_vfs_namespace_view"):
        observe(vector)
    assert "start-attach" not in events


def test_prestart_metadata_comparator_rejects_duplicate_same_hash_rows():
    proof = {"ancillary_mounts": [{"destination": "/etc/resolv.conf", "size": 0, "sha256": "a" * 64}]}
    row = {"path": "/etc/resolv.conf", "size": 0, "sha256": "a" * 64}
    assert custody._vfs_metadata_matches(proof, [row])
    assert not custody._vfs_metadata_matches(proof, [row, row])


def test_legacy_merged_dir_route_is_unchanged_and_never_selects_vfs(tmp_path, monkeypatch):
    vector = source_data_vector(tmp_path, monkeypatch)
    subject, root, current, argv, environment, spec, readonly, expected, _selected = vector
    assert subject.vfs_roots is False
    (root / "config.json").write_bytes(canonical(spec))
    calls = []
    original = subject._control

    def control(args, *rest):
        calls.append(args)
        return original(args, *rest)

    monkeypatch.setattr(subject, "_control", control)
    result = subject._runtime_policy(CID, IMAGE, argv, environment, current, root, [], readonly,
                                     expected_view=expected)
    assert "MergedDir" in calls[0][4]
    assert "root_acquisition" not in result


def test_original_custody_run_uses_vfs_observation_and_promotes_only_after_original_exit(vector, monkeypatch):
    original, data, events = vector
    subject, _root, _current, _argv, environment, spec, readonly, _expected, _selected = original
    stage_root = subject.root / "compile-0"
    current = stage_root / "current"
    spec = copy.deepcopy(spec)
    spec["process"]["env"] = [key + "=" + value for key, value in
                               custody._guest_build_environment(environment).items()]
    for row in spec["mounts"]:
        if row["destination"] == "/out":
            row["source"] = str(current)
        elif row["destination"] == "/etc/resolv.conf":
            row["source"] = str(stage_root / "fixed-resolv.conf")
    data.oci.write_bytes(canonical(spec))
    control = subject._control

    def lifecycle(args, name, root, operations):
        if args[0] in {"create", "init", "wait", "inspect"} and name != "runtime-selection":
            events.append(name)
            if args[0] == "create":
                assert "--volume=" + str(readonly["source"]) + ":/source:ro,noexec,nosuid,nodev" in args
                return (CID + "\n").encode()
            if args[0] == "wait":
                return b"0\n"
            if args[0] == "inspect":
                return canonical({"Status": "exited", "Running": False, "Pid": 0,
                                  "ExitCode": 0, "OOMKilled": False, "Error": ""})
            return b""
        return control(args, name, root, operations)

    def image(**options):
        options["observation"].update(image_id=IMAGE, input_layout=custody.SOURCE_DATA_VFS_BACKEND)
        return IMAGE, readonly

    def attach(args, **options):
        assert args[-3:] == ["start", "--attach", CID]
        events.append("start-attach")
        (current / "result.o").write_bytes(b"original completed output")
        options["evidence"].update(returncode=0, direct_child_reaped=True, logs={})

    monkeypatch.setattr(subject, "_control", lifecycle)
    monkeypatch.setattr(subject, "_prepare_image", image)
    monkeypatch.setattr(custody, "_static_helper_inputs", lambda *_args, **_options: None)
    monkeypatch.setattr(custody, "_command", attach)
    work, logs = subject.destination / "retained-output", subject.destination / "logs"
    work.mkdir()
    logs.mkdir()
    evidence = {}
    subject.run(["@toolchain/zig", "cc"], inputs={"source": [], "toolchain": [
        {"path": "zig", "executable": True}]}, snapshots=readonly, prior=[],
        outputs=[{"path": "result.o", "max_size": 64, "executable": False}], work=work,
        environment=environment, logs=logs, evidence=evidence, stage="compile", index=0)
    assert events.index("service-close") < events.index("start-attach") < events.index("wait")
    assert (work / "result.o").read_bytes() == b"original completed output"
    observation_value = evidence["custody"]
    assert observation_value["schema"] == "lunar-podman-build-command-observation-v3"
    assert observation_value["input_layout"] == custody.SOURCE_DATA_VFS_BACKEND
    assert evidence["status"] == "complete" and observation_value["original_container_exit_confirmed"]
    assert not observation_value["production_admission"]
