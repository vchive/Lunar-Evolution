"""Retained-profile ordering through the original inert custody lifecycle.

The recording store is a transport double, not raw-snapshot validation. Actual
VFS reads, OCI policy, pre-start checks and original failure cleanup stay active.
No Podman container or candidate program is executed by these tests.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

import pytest

from tests import test_static_python_source_data_vfs_custody as original_tests
from tests.test_static_python_podman_vfs_root import CID, IMAGE
from tools.static_python_rsi_fixture import podman_custody as custody
from tools.static_python_rsi_fixture import podman_vfs_root as vfs
from tools.static_python_rsi_fixture.execution_backend import BuildExecutionError
from tools.static_python_rsi_fixture.runtime_closure import canonical

original_vector = original_tests.vector
mount_table = vfs.mount_table
MOUNTINFO = b"1 0 0:1 / / rw - tmpfs tmpfs rw\n"


@dataclass
class Capture:
    subject: custody.PodmanCustody
    events: list
    records: list = field(default_factory=list)
    binding: dict | None = None
    failure: str | None = None
    expired: bool = False

    def record(self, role, phase, raw, identity=None):
        self.subject.checkpoint()
        self.events.append("capture-" + role + "-" + phase)
        self.records.append((role, phase, raw, copy.deepcopy(identity)))
        if self.failure == "record":
            raise BuildExecutionError("custody_vfs_snapshot_write")

    def complete(self, binding):
        self.subject.checkpoint()
        self.events.append("capture-complete")
        self.binding = dict(binding)
        if self.failure == "io":
            raise OSError("inert snapshot storage failure")
        if self.failure == "complete":
            raise BuildExecutionError("custody_vfs_snapshot_write")
        if self.failure == "deadline":
            self.expired = True
            self.subject.checkpoint()
        return {"path": "custody/compile-0/vfs-raw/manifest.json", "size": 123,
                "sha256": "e" * 64}


class Store:
    def __init__(self, capture):
        self.capture = capture
        self.commands = []

    def command(self, stage, index):
        self.capture.subject.checkpoint()
        self.commands.append((stage, index))
        self.capture.events.append("capture-command")
        return self.capture


@pytest.fixture
def vector(original_vector, monkeypatch):
    original, _data, events = original_vector
    subject = original[0]
    subject.vfs_retained = True
    capture = Capture(subject, events)
    subject.snapshot_store = Store(capture)
    monkeypatch.setattr(vfs, "mount_table", mount_table)
    monkeypatch.setattr(vfs, "_proc_bytes", lambda *_args, **_kwargs: MOUNTINFO)
    return original_vector, capture


def lifecycle(vector, monkeypatch):
    base, capture = vector
    original, data, events = base
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
    original_control = subject._control

    def checkpoint():
        if capture.expired:
            raise BuildExecutionError("deadline_expired")

    def control(args, name, root, operations):
        subject.checkpoint()
        if args[0] in {"create", "init", "wait", "inspect", "stop"} and name != "runtime-selection":
            events.append(name)
            if args[0] == "create":
                return (CID + "\n").encode()
            if args[0] == "wait":
                return b"0\n"
            if args[0] == "inspect":
                return canonical({"Status": "exited", "Running": False, "Pid": 0,
                                  "ExitCode": 0, "OOMKilled": False, "Error": ""})
            return b""
        return original_control(args, name, root, operations)

    def image(**options):
        options["observation"].update(image_id=IMAGE, input_layout=custody.SOURCE_DATA_VFS_RETAINED_BACKEND)
        return IMAGE, readonly

    def attach(args, **options):
        subject.checkpoint()
        assert args[-3:] == ["start", "--attach", CID]
        assert capture.binding is not None
        assert events[-1] == "capture-complete"
        events.append("start-attach")
        (current / "result.o").write_bytes(b"original completed output")
        options["evidence"].update(returncode=0, direct_child_reaped=True, logs={})

    monkeypatch.setattr(subject, "checkpoint", checkpoint)
    monkeypatch.setattr(subject, "_control", control)
    monkeypatch.setattr(subject, "_prepare_image", image)
    monkeypatch.setattr(custody, "_static_helper_inputs", lambda *_args, **_options: None)
    monkeypatch.setattr(custody, "_command", attach)
    work, logs = subject.destination / "retained-output", subject.destination / "logs"
    work.mkdir()
    logs.mkdir()
    evidence = {}

    def run():
        subject.run(["@toolchain/zig", "cc"], inputs={"source": [], "toolchain": [
            {"path": "zig", "executable": True}]}, snapshots=readonly, prior=[],
            outputs=[{"path": "result.o", "max_size": 64, "executable": False}], work=work,
            environment=environment, logs=logs, evidence=evidence, stage="compile", index=0)

    return run, evidence, work, stage_root, spec


def test_retained_lifecycle_completes_original_snapshots_before_start_and_promotes_after_exit(vector, monkeypatch):
    run, evidence, work, _root, _spec = lifecycle(vector, monkeypatch)
    run()
    base, capture = vector
    original, _data, events = base
    subject = original[0]
    observation = evidence["custody"]
    assert subject.snapshot_store.commands == [("compile", 0)]
    assert events.index("service-close") < events.index("capture-complete") < events.index("start-attach")
    assert events.index("start-attach") < events.index("wait") < events.index("state")
    assert capture.binding == {
        "recipe_sha256": subject.recipe_sha256, "stage": "compile", "index": 0,
        "container_id": CID, "image_id": IMAGE,
        "root_acquisition_sha256": observation["runtime_policy"]["root_acquisition_sha256"],
    }
    assert (work / "result.o").read_bytes() == b"original completed output"
    assert observation["schema"] == "lunar-podman-build-command-observation-v4"
    assert observation["input_layout"] == custody.SOURCE_DATA_VFS_RETAINED_BACKEND
    assert observation["snapshot_retention_profile"] == custody.VFS_RETENTION_PROFILE
    assert observation["vfs_snapshots"]["path"] == "custody/compile-0/vfs-raw/manifest.json"
    assert observation["original_container_exit_confirmed"] and evidence["status"] == "complete"
    assert all(observation[key] is False for key in (
        "installation_accepted", "production_admission", "online_publication",
        "immutable_custody_verified", "driver_inputs_verified", "configured_closure_verified"))


def test_retained_selection_records_original_info_and_inspect_buffers_without_requery(vector, monkeypatch):
    base, capture = vector
    original, data, events = base
    subject, root, current, argv, environment, _spec, readonly, expected, _selected = original
    info_raw = canonical(data.info) + b"  \n"
    selected_raw = b" " + canonical(data.selected)
    original_control = subject._control
    original_read = vfs.read_at
    reads = []

    def read(root_fd, path, maximum, checkpoint, **options):
        reads.append(path)
        return original_read(root_fd, path, maximum, checkpoint, **options)

    monkeypatch.setattr(vfs, "read_at", read)

    def control(args, name, *rest):
        if args[0] == "info":
            events.append(name)
            return info_raw
        if name == "runtime-selection":
            events.append(name)
            return selected_raw
        return original_control(args, name, *rest)

    monkeypatch.setattr(subject, "_control", control)
    subject._runtime_policy(CID, IMAGE, argv, environment, current, root, [], readonly,
                            expected_view=expected, snapshots=capture)
    assert [(role, phase, raw) for role, phase, raw, _identity in capture.records[:2]] == [
        ("info", "selection", info_raw), ("inspect", "selection", selected_raw)]
    assert events.count("vfs-store-selection") == events.count("runtime-selection") == 1
    # Retention consumes the original buffers; it adds no metadata-file query.
    assert reads.count(data.containers) == reads.count(data.layers) == 2
    assert reads.count(data.oci) == 1 and reads.count(root / "fixed-resolv.conf") == 2
    assert len(reads) == 7
    assert capture.binding is None


@pytest.mark.parametrize("failure", ["record", "complete", "io"])
def test_snapshot_storage_failure_keeps_partial_evidence_and_stops_original_container_before_start(
        vector, monkeypatch, failure):
    run, evidence, work, _root, _spec = lifecycle(vector, monkeypatch)
    _base, capture = vector
    capture.failure = failure
    expected = OSError if failure == "io" else BuildExecutionError
    with pytest.raises(expected):
        run()
    base, capture = vector
    _original, _data, events = base
    observation = evidence["custody"]
    assert "start-attach" not in events and "wait" not in events
    assert events[-2:] == ["failure-stop", "failure-state"]
    assert capture.records and evidence["status"] == "partial"
    assert observation["original_container_exit_confirmed"] is True
    assert "vfs_snapshots" not in observation
    assert not (work / "result.o").exists()
    assert observation["first_failure"] == (
        "OSError" if failure == "io" else "static_python_build_execution_custody_vfs_snapshot_write")


def test_snapshot_deadline_failure_does_not_grant_cleanup_extra_budget_or_start(vector, monkeypatch):
    run, evidence, work, _root, _spec = lifecycle(vector, monkeypatch)
    base, capture = vector
    capture.failure = "deadline"
    with pytest.raises(BuildExecutionError, match="deadline_expired"):
        run()
    _original, _data, events = base
    observation = evidence["custody"]
    assert capture.records and "capture-complete" in events
    assert "start-attach" not in events and "failure-stop" not in events
    assert observation["original_container_exit_confirmed"] is False
    assert observation["original_container_cleanup_unknown"] is True
    assert observation["first_failure"] == "static_python_build_execution_deadline_expired"
    assert "vfs_snapshots" not in observation and not (work / "result.o").exists()


@pytest.mark.parametrize("gate", ["runtime", "seccomp"])
def test_retention_never_replaces_original_prestart_runtime_or_seccomp_gate(vector, monkeypatch, gate):
    run, evidence, work, root, spec = lifecycle(vector, monkeypatch)
    base, capture = vector
    original, data, events = base
    subject = original[0]
    if gate == "runtime":
        spec["process"]["noNewPrivileges"] = False
        data.oci.write_bytes(canonical(spec))
    else:
        runtime_policy = subject._runtime_policy

        def changed(*args, **kwargs):
            policy = runtime_policy(*args, **kwargs)
            seccomp = root / "seccomp.json"
            seccomp.chmod(0o600)
            seccomp.write_bytes(b"{}\n")
            return policy

        monkeypatch.setattr(subject, "_runtime_policy", changed)
    with pytest.raises(BuildExecutionError, match="custody_runtime_"):
        run()
    assert capture.records and capture.binding is None
    assert "capture-complete" not in events and "start-attach" not in events
    assert evidence["status"] == "partial" and not (work / "result.o").exists()
    assert evidence["custody"]["original_container_exit_confirmed"] is True


@pytest.mark.parametrize("options", [
    {"vfs_retained": True},
    {"snapshot_mounts": True, "source_data": True, "vfs_retained": True},
    {"snapshot_mounts": True, "source_data": True, "vfs_roots": True, "vfs_retained": 1},
])
def test_snapshot_retention_requires_its_explicit_vfs_profile_before_store_creation(tmp_path, options):
    with pytest.raises(BuildExecutionError, match="custody_vfs_retention_mode"):
        custody.PodmanCustody(destination=tmp_path, prefix=["never-executed"], recipe_sha256="a" * 64,
                             checkpoint=lambda: None, **options)
    assert not (tmp_path / "custody").exists()


def retained_observation(vector):
    base, _capture = vector
    command, planned, inputs, workspace, recipe_sha, environment = original_tests.observation(base)
    value = command["custody"]
    value.update(schema="lunar-podman-build-command-observation-v4",
                 input_layout=custody.SOURCE_DATA_VFS_RETAINED_BACKEND,
                 snapshot_retention_profile=custody.VFS_RETENTION_PROFILE,
                 vfs_snapshots={"path": "custody/configure-0/vfs-raw/manifest.json", "size": 123,
                                "sha256": "e" * 64}, operations=[])
    return command, planned, inputs, workspace, recipe_sha, environment


def validate_retained(value, checkpoint=None):
    command, planned, inputs, workspace, recipe_sha, environment = value
    custody.validate_custody_observation_v4(command, planned, "configure", 0, recipe_sha, environment,
                                           inputs=inputs, prior=[], workspace=workspace, checkpoint=checkpoint)


def verifier_boundaries(monkeypatch, value, *, failure=None):
    from tools.static_python_rsi_fixture import podman_vfs_snapshots as snapshots

    events = []
    spec = {"original": "decoded OCI transport double"}
    original_v3 = custody.validate_custody_observation_v3
    command, _planned, _inputs, workspace, recipe_sha, _environment = value
    observation = command["custody"]
    expected_binding = {
        "recipe_sha256": recipe_sha, "stage": "configure", "index": 0,
        "container_id": CID, "image_id": IMAGE,
        "root_acquisition_sha256": observation["runtime_policy"]["root_acquisition_sha256"],
    }

    def verify(actual_workspace, pin, binding, proof, operations, checkpoint):
        events.append("verify")
        assert actual_workspace == workspace and pin is observation["vfs_snapshots"]
        assert binding == expected_binding
        assert proof is observation["runtime_policy"]["root_acquisition"]
        assert operations is observation["operations"] and callable(checkpoint)
        if failure == "verify":
            raise ValueError("snapshot_refused")
        return spec

    def replay(actual_spec, actual_value, actual_workspace, stage, index):
        events.append("replay")
        assert actual_spec is spec and actual_value is observation
        assert actual_workspace == workspace and (stage, index) == ("configure", 0)
        if failure == "replay":
            raise ValueError("runtime_replay_refused")

    def v3(actual_command, *args, **kwargs):
        events.append("v3")
        assert actual_command["custody"]["schema"] == "lunar-podman-build-command-observation-v3"
        assert actual_command["custody"]["input_layout"] == custody.SOURCE_DATA_VFS_BACKEND
        original_v3(actual_command, *args, **kwargs)

    monkeypatch.setattr(snapshots, "verify_snapshots", verify)
    monkeypatch.setattr(custody, "_retained_runtime_spec", replay)
    monkeypatch.setattr(custody, "validate_custody_observation_v3", v3)
    return events


def test_retained_validator_verifies_original_bytes_then_runtime_replay_then_original_v3_checks(vector, monkeypatch):
    value = retained_observation(vector)
    events = verifier_boundaries(monkeypatch, value)
    validate_retained(value)
    assert events == ["verify", "replay", "v3"]


@pytest.mark.parametrize("failure", ["verify", "replay"])
def test_retained_validator_cannot_skip_failed_raw_or_runtime_replay_gate(vector, monkeypatch, failure):
    value = retained_observation(vector)
    events = verifier_boundaries(monkeypatch, value, failure=failure)
    with pytest.raises(ValueError, match="refused"):
        validate_retained(value)
    assert events == (["verify"] if failure == "verify" else ["verify", "replay"])


@pytest.mark.parametrize("change", ["schema-v3", "schema-v2", "backend", "retention-profile"])
def test_retained_validator_refuses_old_or_mixed_observation_before_raw_readback(vector, monkeypatch, change):
    value = retained_observation(vector)
    events = verifier_boundaries(monkeypatch, value)
    observation = value[0]["custody"]
    if change.startswith("schema"):
        observation["schema"] = "lunar-podman-build-command-observation-" + change.split("-")[1]
    elif change == "backend":
        observation["input_layout"] = custody.SOURCE_DATA_VFS_BACKEND
    else:
        observation["snapshot_retention_profile"] = "caller-snapshot-profile"
    with pytest.raises(ValueError, match="observation_v4"):
        validate_retained(value)
    assert not events


@pytest.mark.parametrize("change", ["false-claim", "root-proof", "workspace"])
def test_successful_raw_transport_does_not_bypass_original_v3_authority_or_workspace_checks(
        vector, monkeypatch, change):
    value = retained_observation(vector)
    observation = value[0]["custody"]
    if change == "false-claim":
        observation["production_admission"] = True
    elif change == "root-proof":
        proof = observation["runtime_policy"]["root_acquisition"]
        proof["root"]["identity"]["inode"] += 1
        observation["runtime_policy"]["root_acquisition_sha256"] = custody._pin(canonical(proof))
    else:
        source = value[3] / "source"
        source.rename(source.with_name("retained-source"))
        source.mkdir()
    events = verifier_boundaries(monkeypatch, value)
    with pytest.raises(ValueError, match="observation"):
        validate_retained(value)
    assert events == ["verify", "replay", "v3"]
