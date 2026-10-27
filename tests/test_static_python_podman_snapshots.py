"""Real snapshot/readback and OCI refusal checks; no daemon or runtime execution."""

from __future__ import annotations

import json
import tarfile

import pytest

from tests.test_static_python_build_dependency_consumer import (
    build as build,  # noqa: PLC0414
)
from tests.test_static_python_build_dependency_consumer import (
    inert_dependency_tool as inert_dependency_tool,  # noqa: PLC0414
)
from tests.test_static_python_link_dependency_capture import record, sha
from tests.test_static_python_podman_custody import runtime_vector
from tools.static_python_rsi_fixture import execution_backend as execution
from tools.static_python_rsi_fixture import podman_custody as custody
from tools.static_python_rsi_fixture.runtime_closure import canonical


def test_full_cpython_scale_does_not_replay_the_toolchain_per_command():
    recipe = {"inputs": {"source": [], "toolchain": [{"size": 357913169}]},
              "stages": [{"commands": [{}] * 200}]}
    with pytest.raises(execution.BuildExecutionError, match="image_attempt_budget"):
        custody.validate_custody_image_budget(recipe)
    custody.validate_snapshot_budget(recipe)
    recipe["stages"][0]["commands"] *= 3
    with pytest.raises(execution.BuildExecutionError, match="snapshot_attempt_budget"):
        custody.validate_snapshot_budget(recipe)


def test_snapshot_input_bound_still_applies():
    recipe = {"inputs": {"source": [{"size": execution.MAX_INPUT_BYTES + 1}], "toolchain": []},
              "stages": [{"commands": [{}]}]}
    with pytest.raises(execution.BuildExecutionError, match="snapshot_attempt_budget"):
        custody.validate_snapshot_budget(recipe)


def test_prior_view_copies_only_original_verified_outputs(tmp_path):
    work, target = tmp_path / "work", tmp_path / "prior"
    work.mkdir()
    (work / "old.h").write_bytes(b"old")
    (work / "future.h").write_bytes(b"not yet observed")
    custody._prior_snapshot(work, target, [record("old.h", b"old")], lambda: None)
    (work / "old.h").write_bytes(b"host changed after snapshot")
    assert (target / "old.h").read_bytes() == b"old"
    assert not (target / "future.h").exists()
    assert (target / "old.h").stat().st_mode & 0o777 == 0o444


@pytest.mark.parametrize("change", ["wrong-bytes", "symlink"])
def test_prior_drift_is_refused_before_a_container_can_start(tmp_path, change):
    work = tmp_path / "work"
    work.mkdir()
    if change == "symlink":
        (work / "old.h").symlink_to("/etc/passwd")
    else:
        (work / "old.h").write_bytes(b"wrong")
    with pytest.raises(execution.BuildExecutionError):
        custody._prior_snapshot(work, tmp_path / "prior", [record("old.h", b"old")], lambda: None)


def snapshot_vector(tmp_path, monkeypatch):
    vector = runtime_vector(tmp_path, monkeypatch)
    subject, root, current, argv, environment, spec = vector
    readonly = {role: tmp_path / role for role in ("source", "toolchain", "work")}
    for role, path in readonly.items():
        path.mkdir()
        spec["mounts"].append({"destination": custody._GUEST[role], "source": str(path),
                               "type": "bind", "options": ["ro", "exec", "nosuid", "nodev"]})
    return subject, root, current, argv, environment, spec, readonly


def observe(vector):
    subject, root, current, argv, environment, spec, readonly = vector
    (root / "config.json").write_bytes(canonical(spec))
    return subject._runtime_policy("b" * 64, "a" * 64, argv, environment, current, root, [], readonly)


def test_actual_oci_requires_all_three_fixed_readonly_snapshot_mounts(tmp_path, monkeypatch):
    vector = snapshot_vector(tmp_path, monkeypatch)
    result = observe(vector)
    assert result["readonly_snapshots"] == {custody._GUEST[k]: str(p) for k, p in vector[-1].items()}
    args = custody._readonly_volumes(vector[-1])
    assert len(args) == 3 and all(arg.endswith(":ro,exec,nosuid,nodev") for arg in args)


def test_oci_default_exec_semantics_need_not_include_a_literal_option(tmp_path, monkeypatch):
    vector = snapshot_vector(tmp_path, monkeypatch)
    for row in vector[-2]["mounts"]:
        if row["destination"] in custody._GUEST.values():
            row["options"].remove("exec")
    assert len(observe(vector)["readonly_snapshots"]) == 3


@pytest.mark.parametrize("role", ["source", "toolchain", "work"])
@pytest.mark.parametrize("change", ["rw", "source", "missing", "alias", "noexec"])
def test_readonly_input_mount_drift_is_refused_before_start(tmp_path, monkeypatch, role, change):
    vector = snapshot_vector(tmp_path, monkeypatch)
    spec = vector[-2]
    row = next(row for row in spec["mounts"] if row["destination"] == custody._GUEST[role])
    if change == "rw":
        row["options"].remove("ro")
        row["options"].append("rw")
    elif change == "source":
        row["source"] = "/ambient/unpinned"
    elif change == "missing":
        spec["mounts"].remove(row)
    elif change == "alias":
        row["source"] = str(vector[2])
    else:
        row["options"].remove("exec")
        row["options"].append("noexec")
    with pytest.raises(execution.BuildExecutionError, match="custody_runtime_"):
        observe(vector)


def test_one_empty_base_image_is_reused_with_fresh_prior_copies(tmp_path, monkeypatch):
    destination = tmp_path / "attempt"
    destination.mkdir()
    snapshots = {role: tmp_path / role for role in ("source", "toolchain")}
    for path in snapshots.values():
        path.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    (work / "a.o").write_bytes(b"object")
    subject = custody.PodmanCustody(destination=destination, prefix=["not-executed"],
        recipe_sha256=sha(b"recipe"), checkpoint=lambda: None, snapshot_mounts=True)
    calls = []

    def control(argv, *args):
        calls.append(argv)
        return b"a" * 64 + b"\n"

    monkeypatch.setattr(subject, "_control", control)
    observations = []
    for i in range(2):
        root = subject.root / str(i)
        root.mkdir()
        observation = {}
        image, readonly = subject._prepare_image(root=root, inputs={"source": [], "toolchain": []},
            snapshots=snapshots, prior=[record("a.o", b"object")], work=work,
            observation=observation, operations=[])
        assert image == "a" * 64
        assert readonly["work"] == root / "prior" and readonly["work"] != work
        assert (readonly["work"] / "a.o").read_bytes() == b"object"
        observations.append(observation)
    assert len(calls) == 1 and calls[0][0] == "import"
    assert [row["base_image_reused"] for row in observations] == [False, True]
    with tarfile.open(subject.root / "0/input.tar") as archive:
        assert not any(member.isfile() and member.name.startswith(("source/", "toolchain/", "work/"))
                       for member in archive)
    (subject.root / "0/input.tar").write_bytes(b"changed image archive")
    third = subject.root / "2"
    third.mkdir()
    with pytest.raises(execution.BuildExecutionError, match="image_drift"):
        subject._prepare_image(root=third, inputs={"source": [], "toolchain": []}, snapshots=snapshots,
            prior=[], work=work, observation={}, operations=[])


def test_cumulative_prior_copy_bound_is_enforced_before_copying(tmp_path):
    destination = tmp_path / "attempt"
    destination.mkdir()
    subject = custody.PodmanCustody(destination=destination, prefix=["not-executed"],
        recipe_sha256=sha(b"recipe"), checkpoint=lambda: None, snapshot_mounts=True)
    subject.image_bytes = custody.MAX_CUMULATIVE_IMAGE_BYTES
    with pytest.raises(execution.BuildExecutionError, match="image_attempt_budget"):
        subject._prepare_image(root=tmp_path / "unused", inputs={}, snapshots={},
            prior=[{"size": 1}], work=tmp_path, observation={}, operations=[])
    assert not (tmp_path / "unused").exists()


def test_original_executor_selects_snapshots_after_its_original_input_pins(build, monkeypatch):
    preparation, options = build()
    monkeypatch.setattr(custody, "preflight_podman_custody", lambda: ["not-executed"])
    selected = []

    def selected_boundary(**kwargs):
        selected.append(kwargs["snapshot_mounts"])
        # All original staging/readback completed before this constructor.
        assert (kwargs["destination"] / "toolchain/zig").is_file()
        raise execution.BuildExecutionError("test_selected_boundary")

    monkeypatch.setattr(custody, "PodmanCustody", selected_boundary)
    dispatch = {key: value for key, value in options.items() if key not in {
        "manifest_bytes", "expected_manifest_sha256"}}
    with pytest.raises(execution.BuildExecutionError, match="test_selected_boundary") as failure:
        execution.run_pinned_build_v3(preparation, **dispatch, custody_backend=custody.SNAPSHOT_BACKEND)
    report = failure.value.report
    assert selected == [True] and report.status == "partial"
    assert report.reason == "test_selected_boundary"
    assert json.loads((options["workspace"] / "report.json").read_bytes())["completed_stages"] == []
