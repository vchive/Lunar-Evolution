from __future__ import annotations

import os
import struct
import sys
from contextlib import contextmanager

import pytest
from test_native_trusted_attempt import _attempt

from lunar_evolution.native_bootstrap import (
    LINUX_CHILD_SUPERVISION,
    LINUX_GRANT_OBJECT_BINDING,
    NativeBootstrapError,
    encode_native_bootstrap_control_v2,
    native_bootstrap_command,
)
from lunar_evolution.native_trusted_attempt import run_native_trusted_attempt
from lunar_evolution.producer_bootstrap import build_trusted_bootstrap_launch
from lunar_evolution.producer_grant_anchors import (
    ProducerGrantError,
    ProducerGrantExpectedBinding,
    ProducerGrantIdentity,
    ProducerGrantRequest,
    hold_producer_grants,
)


@pytest.fixture
def control_owner(tmp_path):
    _workspace, _producer, intent, attestation, artifact, _batch = _attempt(tmp_path)
    launch = build_trusted_bootstrap_launch(intent, attestation, artifact.descriptor)
    work, output, protected = tmp_path / "work", tmp_path / "output", tmp_path / "protected"
    work.mkdir(); output.mkdir(); protected.write_bytes(b"original")
    protected.chmod(0o400)
    pin = protected.stat(follow_symlinks=False)
    root_pin = tmp_path.stat(follow_symlinks=False)
    requests = (
        ProducerGrantRequest(str(work), "writable-directory"),
        ProducerGrantRequest(str(work), "cwd"),
        ProducerGrantRequest(str(output), "writable-directory"),
        ProducerGrantRequest(str(protected), "protected-file", ProducerGrantIdentity(pin.st_dev, pin.st_ino, "file")),
    )
    target = os.open(artifact.path, os.O_RDONLY)
    bootstrap = os.dup(target)
    try:
        with hold_producer_grants(requests, expected_bindings=(ProducerGrantExpectedBinding(
            str(tmp_path), ProducerGrantIdentity(root_pin.st_dev, root_pin.st_ino, "directory"),
        ),)) as owner:
            kwargs = {"launch": launch, "target_path": str(artifact.path), "target_argv": (str(artifact.path), "fixture"),
                      "target_cwd": work, "target_fd": target, "bootstrap_fd": bootstrap, "held_grants": owner}
            yield kwargs
    finally:
        os.close(target); os.close(bootstrap)


def _decode(data):
    cursor = 0

    def take(count):
        nonlocal cursor
        result = data[cursor:cursor + count]
        assert len(result) == count
        cursor += count
        return result

    def u32():
        return struct.unpack(">I", take(4))[0]

    def string():
        return take(u32()).decode("utf-8")

    assert take(8) == b"LNB1\x00\x02\x00\x00"
    hashes = tuple(take(64).decode("ascii") for _ in range(3))
    target, bootstrap, path, kind = u32(), u32(), string(), u32()
    nodes = []
    for _ in range(u32()):
        parent, node_kind = u32(), u32()
        device, inode = struct.unpack(">QQ", take(16))
        name = string()
        nodes.append((parent, node_kind, device, inode, name))
    grants = [tuple(u32() for _ in range(3)) for _ in range(u32())]
    cwd = u32()
    argv = tuple(string() for _ in range(u32()))
    assert cursor == len(data)
    return hashes, target, bootstrap, path, kind, nodes, grants, cwd, argv


def test_v2_encodes_original_graph_but_grants_only_exact_leaves(control_owner):
    data = encode_native_bootstrap_control_v2(**control_owner)
    hashes, target, bootstrap, path, kind, nodes, grants, cwd, argv = _decode(data)
    owner = control_owner["held_grants"]
    assert hashes == (control_owner["launch"].launch_sha256, control_owner["launch"].intent_sha256,
                      control_owner["launch"].target_executable_identity)
    assert (target, bootstrap, path, kind) == (control_owner["target_fd"], control_owner["bootstrap_fd"],
                                            control_owner["target_path"], 1)
    assert nodes[0][:2] == (0xffffffff, 1) and nodes[0][-1] == ""
    assert len(grants) == 3 and sorted(mask for _index, mask, _fd in grants) == [1, 4, 12]
    assert tuple(fd for _index, _mask, fd in grants) == owner.pass_fds
    assert grants[cwd][1] == 12
    assert argv == control_owner["target_argv"]
    for index, binding in enumerate(owner.binding_nodes):
        assert nodes[index] == (0xffffffff if binding.parent_index is None else binding.parent_index,
                               1 if binding.identity.kind == "directory" else 2,
                               binding.identity.device, binding.identity.inode, binding.name)
    assert len(nodes) > len(grants), "expected parents must confer no extra grants"


@pytest.mark.parametrize("field,value", [
    ("target_fd", True), ("target_fd", 2), ("target_fd", 2**31), ("bootstrap_fd", None),
    ("target_argv", ["fixture"]), ("target_argv", ()), ("target_argv", ("fixture", "")),
    ("target_argv", ("fixture", "x" * 4097)), ("target_path", "relative"),
    ("target_path", "/bad\x00path"), ("reserved_fds", []),
    ("target_path", "/bad\ud800"), ("target_argv", ("fixture", "\ud800")),
    ("reserved_fds", (3,) * 255), ("target_cwd", object()),
])
def test_v2_refuses_invalid_wire_proposals(control_owner, field, value):
    control_owner[field] = value
    with pytest.raises(NativeBootstrapError):
        encode_native_bootstrap_control_v2(**control_owner)


def test_v2_refuses_total_frame_overflow(control_owner):
    control_owner["target_argv"] = ("a" * 4096,) * 64
    with pytest.raises(NativeBootstrapError, match="native_bootstrap_control_too_large"):
        encode_native_bootstrap_control_v2(**control_owner)


@pytest.mark.parametrize("role", ["target", "bootstrap", "channel"])
def test_v2_refuses_live_grant_reserved_alias(control_owner, role):
    borrowed = control_owner["held_grants"].pass_fds[0]
    if role == "channel":
        control_owner["reserved_fds"] = (borrowed,)
    else:
        control_owner[role + "_fd"] = borrowed
    with pytest.raises(NativeBootstrapError, match="native_bootstrap_grant_binding_invalid"):
        encode_native_bootstrap_control_v2(**control_owner)


def test_v2_requires_original_held_cwd(control_owner):
    control_owner["target_cwd"] = "/"
    with pytest.raises(NativeBootstrapError, match="native_bootstrap_cwd_binding_invalid"):
        encode_native_bootstrap_control_v2(**control_owner)


@pytest.mark.parametrize("replacement", ["manifest", "closed", "substituted"])
def test_v2_cannot_upgrade_detached_closed_or_substituted_objects(control_owner, replacement):
    owner = control_owner["held_grants"]
    if replacement == "manifest":
        control_owner["held_grants"] = owner.manifest
    elif replacement == "closed":
        requests = tuple(ProducerGrantRequest(record.path, role, record.identity if role == "protected-file" else None)
                         for record in owner.manifest.records for role in record.roles)
        with hold_producer_grants(requests) as expired:
            pass
        control_owner["held_grants"] = expired
    else:
        work = control_owner["target_cwd"]
        work.rename(work.with_name("old-work"))
        work.mkdir()
    try:
        with pytest.raises(NativeBootstrapError, match="native_bootstrap_grant_binding_invalid"):
            encode_native_bootstrap_control_v2(**control_owner)
    finally:
        if replacement == "substituted":
            work.rmdir()
            work.with_name("old-work").rename(work)


@pytest.mark.parametrize("binding", ["", "linux-held-grants-v2", True, 1])
def test_command_refuses_unknown_grant_binding(monkeypatch, binding):
    monkeypatch.setattr("lunar_evolution.native_bootstrap.platform.system", lambda: "Linux")
    with pytest.raises(NativeBootstrapError, match="native_bootstrap_grant_binding_invalid"):
        native_bootstrap_command("fixture", control_fd=3, gate_fd=4, frame_fd=5,
                                 controller_lifeline_fd=6, deadline_monotonic_ns=123,
                                 child_supervision=LINUX_CHILD_SUPERVISION, grant_object_binding=binding)


def test_command_grant_binding_requires_complete_linux_guard(monkeypatch):
    monkeypatch.setattr("lunar_evolution.native_bootstrap.platform.system", lambda: "Linux")
    with pytest.raises(NativeBootstrapError, match="native_bootstrap_grant_binding_invalid"):
        native_bootstrap_command("fixture", control_fd=3, gate_fd=4, frame_fd=5,
                                 grant_object_binding=LINUX_GRANT_OBJECT_BINDING)
    command = native_bootstrap_command("fixture", control_fd=3, gate_fd=4, frame_fd=5,
                                       controller_lifeline_fd=6, deadline_monotonic_ns=123,
                                       child_supervision=LINUX_CHILD_SUPERVISION,
                                       grant_object_binding=LINUX_GRANT_OBJECT_BINDING)
    assert command[-2:] == ("--grant-object-binding", LINUX_GRANT_OBJECT_BINDING)


@pytest.mark.skipif(sys.platform != "linux", reason="actual Linux original-grant integration")
def test_formal_grants_exist_before_persist_and_remain_held_through_cleanup(tmp_path, monkeypatch):
    import lunar_evolution.native_trusted_attempt as runner

    workspace, producer, intent, attestation, artifact, batch = _attempt(tmp_path)
    hold, persist, spawn, cleanup = runner.hold_producer_grants, runner._persist_deadline, runner.subprocess.Popen, runner._cleanup
    seen = {}

    @contextmanager
    def checked_hold(*args, **kwargs):
        assert not (batch / "native-trusted-attempt-deadline.json").exists()
        with hold(*args, **kwargs) as owner:
            seen["owner"] = owner
            seen["fds"] = owner.pass_fds
            yield owner

    def checked_persist(*args, **kwargs):
        seen["owner"].validate()
        assert (batch / "work").is_dir() and (batch / "output").is_dir()
        return persist(*args, **kwargs)

    class CheckedSpawn(spawn):
        def __init__(self, *args, **kwargs):
            seen["owner"].validate()
            assert kwargs["cwd"] == "/"
            assert set(seen["fds"]) <= set(kwargs["pass_fds"])
            assert LINUX_GRANT_OBJECT_BINDING in args[0]
            super().__init__(*args, **kwargs)

    def checked_cleanup(*args, **kwargs):
        seen["owner"].validate()
        seen["cleaned"] = True
        return cleanup(*args, **kwargs)

    monkeypatch.setattr(runner, "hold_producer_grants", checked_hold)
    monkeypatch.setattr(runner, "_persist_deadline", checked_persist)
    monkeypatch.setattr(runner.subprocess, "Popen", CheckedSpawn)
    monkeypatch.setattr(runner, "_cleanup", checked_cleanup)
    result = run_native_trusted_attempt(workspace, producer_root=producer, intent=intent, attestation=attestation, artifact=artifact)
    assert result.target_started and result.exit_code == 0 and seen["cleaned"]
    for fd in seen["fds"]:
        with pytest.raises(OSError):
            os.fstat(fd)


@pytest.mark.skipif(sys.platform != "linux", reason="actual Linux original-grant integration")
def test_formal_pre_persist_original_grant_drift_does_not_consume_attestation(tmp_path, monkeypatch):
    import lunar_evolution.native_trusted_attempt as runner

    workspace, producer, intent, attestation, artifact, batch = _attempt(tmp_path)
    hold = runner.hold_producer_grants

    @contextmanager
    def changed_owner(*args, **kwargs):
        with hold(*args, **kwargs) as owner:
            (batch / "work").rename(batch / "original-work")
            (batch / "work").mkdir()
            yield owner

    def forbidden(*args, **kwargs):
        pytest.fail("original-grant drift must precede persistence, nonce consumption and spawn")

    monkeypatch.setattr(runner, "hold_producer_grants", changed_owner)
    for name in ("_persist_deadline", "consume_trusted_bootstrap_attestation", "subprocess.Popen"):
        monkeypatch.setattr("lunar_evolution.native_trusted_attempt." + name, forbidden)
    with pytest.raises(runner.NativeTrustedAttemptError, match="native_trusted_attempt_grant_objects_changed"):
        run_native_trusted_attempt(workspace, producer_root=producer, intent=intent, attestation=attestation, artifact=artifact)
    assert not (batch / "native-trusted-attempt-deadline.json").exists()


@pytest.mark.skipif(sys.platform != "linux", reason="actual Linux original-grant integration")
def test_formal_post_claim_grant_failure_retains_unknown_and_closes_owned_fds(tmp_path, monkeypatch):
    import lunar_evolution.native_trusted_attempt as runner

    workspace, producer, intent, attestation, artifact, batch = _attempt(tmp_path)
    seen = {}
    hold = runner.hold_producer_grants

    @contextmanager
    def checked_hold(*args, **kwargs):
        with hold(*args, **kwargs) as owner:
            seen["fds"] = owner.pass_fds
            yield owner

    def fail_grant(*args, **kwargs):
        assert (batch / "native-trusted-attempt-deadline.json").is_file()
        raise ProducerGrantError("producer_grant_object_changed")

    monkeypatch.setattr(runner, "hold_producer_grants", checked_hold)
    monkeypatch.setattr(runner.subprocess, "Popen", fail_grant)
    result = run_native_trusted_attempt(workspace, producer_root=producer, intent=intent, attestation=attestation, artifact=artifact)
    assert result.status == "recovery_required" and result.reason == "native_trusted_attempt_grant_objects_changed"
    assert not result.gate_released and not result.target_started and result.terminal_sha256 is None
    assert not (batch / "process-registration.json").exists()
    for fd in seen["fds"]:
        with pytest.raises(OSError):
            os.fstat(fd)
