"""Original lifetime integration with inert process owners and actual file FDs.

No container, compiler, model or solver is started; the checked original
boundaries do not provide immutable backing or accepted runtime authority.
"""

from __future__ import annotations

import copy

import pytest

from tests import test_static_python_rsi_vfs_lifetime as lifecycle
from tests import test_static_python_worker_input_view as inputs
from tests.test_static_python_worker_filesystem import populate_guest
from tools.static_python_rsi_fixture import podman_vfs_lifetime as lifetime
from tools.static_python_rsi_fixture import podman_vfs_snapshots as retained
from tools.static_python_rsi_fixture.execution_backend import BuildExecutionError

worker_owner_vector = inputs.worker_owner_vector
original_vector = lifecycle.original_vector
retained_vector = lifecycle.retained_vector
service_root_double = lifecycle.service_root_double
OUTPUTS = [{"path": "objects/result.o", "max_size": 64, "executable": False}]
ARGV = ["@toolchain/zig", "cc", "-c", "@source/unit.c", "-o", "@work/objects/result.o"]


def bind_original(vector):
    source, prior = inputs.worker_inventories(vector)
    configuration = populate_guest(vector.root, outputs=copy.deepcopy(OUTPUTS))
    owner = vector.create()
    owner._bind_worker_inputs(source, prior, argv=list(ARGV))
    owner._bind_worker_filesystem(**configuration)
    return owner, configuration


@pytest.mark.parametrize("moment", ["initialized", "before-start"])
@pytest.mark.parametrize("change", ["non-init", "thread-leader", "host-view"])
def test_original_worker_status_refuses_before_dispatch(worker_owner_vector, monkeypatch, moment, change):
    vector = worker_owner_vector
    original = lifetime._proc_read

    def proc_read(pid, name, maximum, checkpoint):
        raw = original(pid, name, maximum, checkpoint)
        if name == "status":
            if change == "non-init":
                return raw.replace(b"\t1\n", b"\t2\n")
            if change == "thread-leader":
                return raw.replace(f"Tgid:\t{pid}\n".encode(), b"Tgid:\t999\n")
            return raw.replace(f"NSpid:\t{pid}\t1".encode(), f"NSpid:\t{pid}".encode())
        return raw

    owner = None
    if moment == "before-start":
        owner, _configuration = bind_original(vector)
    monkeypatch.setattr(lifetime, "_proc_read", proc_read)
    with pytest.raises(ValueError, match="^podman_worker_init$"):
        vector.create() if owner is None else owner.before_start()
    assert not (vector.destination / "custody/compile-0/vfs-lifetime/manifest.json").exists()
    assert len(vector.capture.phases) == (0 if moment == "initialized" else 1)


def test_original_full_policy_is_frozen_and_checked_before_start(worker_owner_vector):
    vector = worker_owner_vector
    owner, configuration = bind_original(vector)
    configuration["outputs"][0]["path"] = "ambient/changed.o"
    configuration["kernel_mounts"].append({"destination": "/sys", "type": "sysfs"})
    owner.before_start()
    assert owner.phase == 2
    assert vector.state.events.count("worker-status") == 2
    assert vector.capture.input_view["claims"] == lifetime.CLAIMS
    assert all(value is False for value in lifetime.CLAIMS.values())


@pytest.mark.parametrize("extra", ["etc/clang.cfg", "run/driver-helper", "tmp/cache", "out/unapproved"])
def test_original_prestart_refuses_ambient_guest_data(worker_owner_vector, extra):
    vector = worker_owner_vector
    owner, _configuration = bind_original(vector)
    (vector.root / extra).write_bytes(b"unregistered input")
    with pytest.raises((ValueError, BuildExecutionError)):
        owner.before_start()
    assert owner.phase == 1 and vector.capture.input_view is None


def test_production_argv_cannot_skip_original_filesystem_binding(worker_owner_vector):
    vector = worker_owner_vector
    source, prior = inputs.worker_inventories(vector)
    owner = vector.create()
    owner._bind_worker_inputs(source, prior, argv=list(ARGV))
    with pytest.raises(ValueError, match="^podman_vfs_lifetime$"):
        owner.before_start()
    assert owner.phase == 1


@pytest.mark.parametrize("action", ["before-inputs", "rebind", "after-start", "after-close"])
def test_filesystem_binding_belongs_to_original_prestart_owner(worker_owner_vector, action):
    vector = worker_owner_vector
    if action == "before-inputs":
        configuration = populate_guest(vector.root, outputs=copy.deepcopy(OUTPUTS))
        owner = vector.create()
    else:
        owner, configuration = bind_original(vector)
        if action == "after-start":
            owner.before_start()
        elif action == "after-close":
            owner.close()
    with pytest.raises(ValueError, match="^podman_vfs_lifetime$"):
        owner._bind_worker_filesystem(**configuration)


def advance_to_readback(vector):
    owner, _configuration = bind_original(vector)
    owner.before_start()
    (vector.root / "out/objects/result.o").write_bytes(b"obj")
    vector.state.exited, vector.state.worker_visible = True, False
    attach = {"status": "complete", "returncode": 0, "direct_child_reaped": True}
    owner.observe_original_exit(attach, b"0\n", retained._json(lifecycle.TERMINAL))
    owner.before_readback()
    return owner, [inputs.row("objects/result.o", b"obj")]


@pytest.mark.parametrize("change", ["bytes", "extra", "missing", "xbit"])
def test_original_output_group_must_match_copied_pins_before_receipt(worker_owner_vector, change):
    vector = worker_owner_vector
    owner, copied = advance_to_readback(vector)
    target = vector.root / "out/objects/result.o"
    if change == "bytes":
        target.write_bytes(b"bad")
    elif change == "extra":
        (target.parent / "late.o").write_bytes(b"late")
    elif change == "missing":
        target.unlink()
    else:
        target.chmod(0o700)
    with pytest.raises((ValueError, OSError, BuildExecutionError)):
        owner.finish_readback(copied, {**vector.binding, "vfs_snapshots": vector.vfs_pin})
    assert owner.phase == 4 and not vector.capture.completed
    assert vector.state.events.count("worker-status") == 2


def test_original_terminal_state_cannot_replace_the_same_pidfd_terminal(worker_owner_vector):
    vector = worker_owner_vector
    owner, _configuration = bind_original(vector)
    owner.before_start()
    attach = {"status": "complete", "returncode": 0, "direct_child_reaped": True}
    with pytest.raises(ValueError, match="^podman_vfs_lifetime$"):
        owner.observe_original_exit(attach, b"0\n", retained._json(lifecycle.TERMINAL))
    assert owner.phase == 2


def test_original_boundary_success_keeps_existing_wire_and_does_not_query_exited_pid(worker_owner_vector):
    vector = worker_owner_vector
    owner, copied = advance_to_readback(vector)
    pin = owner.finish_readback(copied, {**vector.binding, "vfs_snapshots": vector.vfs_pin})
    value = retained._decode((vector.destination / pin["path"]).read_bytes())
    assert value["schema"] == lifetime.WORKER_INPUT_SCHEMA
    assert {row["role"] for row in value["records"]} == {
        "state", "worker-stat", "worker-mountinfo", "attach", "wait", "mountinfo-service", "mountinfo-client"}
    assert all(value is False for value in value["claims"].values())
    assert vector.state.events.count("worker-status") == 2 and owner.phase == 5


@pytest.mark.parametrize("change", ["caller-pins", "verified-pins", "returned-summary", "after-check"])
def test_output_receipt_cannot_bind_a_vector_changed_after_its_readback(
        worker_owner_vector, monkeypatch, change):
    from tools.static_python_rsi_fixture import podman_worker_outputs

    vector = worker_owner_vector
    owner, copied = advance_to_readback(vector)
    original = podman_worker_outputs.verify_worker_outputs
    verified = False

    def verify(fd, records, checkpoint):
        nonlocal verified
        summary = original(fd, records, checkpoint)
        verified = True
        if change == "caller-pins":
            copied[0]["sha256"] = "a" * 64
        elif change == "verified-pins":
            records[0]["sha256"] = "a" * 64
        elif change == "returned-summary":
            summary["inventory_sha256"] = "a" * 64
        return summary

    original_check = owner._check

    def check(*, live):
        original_check(live=live)
        if verified and change == "after-check":
            copied[0]["sha256"] = "a" * 64

    monkeypatch.setattr(podman_worker_outputs, "verify_worker_outputs", verify)
    monkeypatch.setattr(owner, "_check", check)
    with pytest.raises(ValueError, match="^podman_vfs_lifetime$"):
        owner.finish_readback(copied, {**vector.binding, "vfs_snapshots": vector.vfs_pin})
    assert not vector.capture.completed and owner.phase == 4


def test_original_runner_forwards_its_checked_policy_and_outputs_before_dispatch(retained_vector, monkeypatch):
    run, evidence, _work, events, owners = lifecycle.original_runner(retained_vector, monkeypatch)
    subject = retained_vector[0][0][0]
    subject.vfs_worker_input_view = True
    select_capture = subject.snapshot_store._lifetime
    forwarded = []

    def capture(stage, index, *, worker_input_view):
        assert worker_input_view is True
        return select_capture(stage, index)

    def bind_inputs(_owner, inputs, prior, *, argv):
        assert argv == ["@toolchain/zig", "cc"] and prior == []
        events.append("bound-inputs")

    def bind_filesystem(owner, outputs, *, runtime_metadata, kernel_mounts):
        assert owner is owners[0] and events[-1] == "bound-inputs"
        forwarded.append({"outputs": outputs, "runtime_metadata": runtime_metadata, "kernel_mounts": kernel_mounts})
        raise BuildExecutionError("inert_original_filesystem_bound")

    monkeypatch.setattr(subject.snapshot_store, "_lifetime", capture)
    monkeypatch.setattr(lifetime._VfsExecutionLifetime, "_bind_worker_inputs", bind_inputs, raising=False)
    monkeypatch.setattr(lifetime._VfsExecutionLifetime, "_bind_worker_filesystem", bind_filesystem, raising=False)
    with pytest.raises(BuildExecutionError, match="inert_original_filesystem_bound"):
        run()
    assert len(forwarded) == 1
    assert forwarded[0]["outputs"] == [{"path": "result.o", "max_size": 64, "executable": False}]
    assert forwarded[0]["runtime_metadata"] == evidence["custody"]["runtime_policy"]["runtime_metadata"]
    assert {row["destination"] for row in forwarded[0]["kernel_mounts"]} <= {
        "/proc", "/dev", "/sys", "/dev/pts", "/dev/mqueue", "/sys/fs/cgroup", "/dev/shm"}
    assert "start-attach" not in events and evidence["status"] == "partial"
