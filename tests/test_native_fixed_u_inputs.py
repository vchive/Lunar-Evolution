"""Fixed-U input custody contracts, without installed execution authority.

Linux mechanism fixtures use real creator FDs, files, statx mounts and POSIX
ACLs. A user-owned fixture explicitly projects root metadata only at the input
security boundary and substitutes installed-profile acquisition. It is not an
installed root profile, actual credential drop or production acceptance.
"""
from __future__ import annotations

import copy
import errno
import json
import os
import pickle
import stat
import struct
import sys
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_openevolve_handoff import _contract
from test_producer_launch_inputs import _config
from test_rsi_native_inputs import _memory, _request

from lunar_evolution import native_fixed_u_inputs as fixed
from lunar_evolution import native_whole_scope as whole
from lunar_evolution import producer_launch_inputs as producer
from lunar_evolution import rsi_native_inputs as rsi
from lunar_evolution.native_bootstrap import build_native_bootstrap_artifact
from lunar_evolution.native_grant_inputs import NativeGrantInputError, original_native_grant_inputs
from lunar_evolution.producer_grant_anchors import ProducerGrantError, hold_producer_grants
from lunar_evolution.producer_launcher import (
    build_producer_launch_attestation,
    build_producer_launch_intent,
)

HEX = "a" * 64


@pytest.mark.parametrize("value", [0, 65534, True, {}, {"uid": 65534}, (), object(), SimpleNamespace(uid=65534)])
def test_numeric_credentials_and_detached_descriptions_never_select_profile(value):
    with pytest.raises(fixed.NativeFixedUInputError):
        fixed.checked_fixed_u_input_owner(value)
    with pytest.raises(fixed.NativeFixedUInputError):
        fixed.NativeFixedUInputOwner(value, object())


@pytest.mark.parametrize("kind", ["rsi", "producer"])
@pytest.mark.parametrize("value", [65534, {"candidate_uid": 65534}, SimpleNamespace(uid=65534)])
def test_public_preparation_refuses_fabricated_owner_before_creating_batch(tmp_path, kind, value):
    if kind == "rsi":
        memory = _memory()
        operation = lambda: rsi.prepare_native_rsi_inputs(
            tmp_path, journal_id="inert", request=_request(memory), memory=memory, fixed_u_owner=value,
        )
        error = rsi.NativeRSIInputError
    else:
        operation = lambda: producer.prepare_producer_launch_inputs(
            tmp_path, journal_id="inert", config=_config(), fixed_u_owner=value,
        )
        error = producer.ProducerLaunchInputError
    before = tuple(tmp_path.iterdir())
    with pytest.raises(error):
        operation()
    assert tuple(tmp_path.iterdir()) == before


def test_uninitialized_owner_and_foreign_parent_cannot_supply_original_custody():
    with pytest.raises(fixed.NativeFixedUInputError):
        fixed.checked_fixed_u_input_owner(object.__new__(fixed.NativeFixedUInputOwner))
    with pytest.raises(fixed.NativeFixedUInputError):
        fixed._acquire_fixed_u_input_owner(SimpleNamespace())


def _root_projection(info):
    return SimpleNamespace(**{name: getattr(info, name) for name in (
        "st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns",
    )}, st_uid=0, st_gid=0)


@pytest.fixture
def original_fixture(tmp_path, monkeypatch):
    if sys.platform != "linux":
        pytest.skip("actual Linux POSIX ACL/statx mechanism fixture")
    workspace = tmp_path / "workspace"
    execution = workspace / "evolution" / "producer-batches"
    execution.mkdir(parents=True)
    journal = "lunar-" + "1" * 64
    attempt = execution / journal
    attempt.mkdir(mode=0o700)
    for name in ("work", "output"):
        (attempt / name).mkdir(mode=0o700)
    uid = 65533 if os.getuid() == 65534 else 65534
    attempt_fd = os.open(attempt, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        # Actual publisher's owner-rwx/U-search shape; no acquisition is claimed.
        raw = struct.pack("<I", 2) + b"".join(struct.pack("<HHI", *entry) for entry in (
            (1, 7, 2**32 - 1), (2, 1, uid), (4, 0, 2**32 - 1),
            (16, 1, 2**32 - 1), (32, 0, 2**32 - 1),
        ))
        try:
            os.setxattr(attempt_fd, fixed._ACCESS, raw, flags=os.XATTR_CREATE)
        except OSError as exc:
            if exc.errno in (errno.ENOTSUP, errno.EOPNOTSUPP):
                pytest.skip("fixture filesystem lacks Linux POSIX ACL support")
            raise
        scope = whole.NativeWholeScopeOwner(whole._TOKEN)
        published_attempt = scope._own(attempt_fd)
        attempt_fd = None
        scope._execution_fd = scope._own(os.open(execution, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC))
        scope._published = (published_attempt, *(
            scope._own(os.open(attempt / name, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC))
            for name in ("work", "output")
        ))
        scope._preparation_key = "1" * 64
        scope._deadline = time.monotonic_ns() + 600_000_000_000
        scope._publication_pins = tuple((whole._kernel_identity(fd), raw if index == 0 else None)
                                         for index, fd in enumerate(scope._published))
        identity = whole._kernel_identity(scope._execution_fd)
        namespaces = tuple((info.st_dev, info.st_ino) for info in (
            os.stat("/proc/self/ns/" + name) for name in ("user", "pid", "mnt", "cgroup")
        ))
        scope._profile = {"uid": uid, "gid": uid, "groups": (), "namespaces": namespaces,
                          "paths": ("/fixture/not-a-delegation", str(execution)),
                          "identities": (identity, identity)}
        scope._profile_sha256 = HEX

        def installation_fixture_only():
            if scope._closed:
                raise whole.NativeWholeScopeError("owner_invalid")

        scope._check_installation = installation_fixture_only
        if os.geteuid() != 0 or os.getegid() != 0:
            # Keep actual ACL/mode/inode/timestamps/mount and FD operations.
            # Only the explicitly absent installed root owner is projected.
            actual_info = fixed._info
            local_os = SimpleNamespace(**vars(os))
            local_os.fstat = lambda fd: _root_projection(os.fstat(fd))
            local_os.stat = lambda *args, **kwargs: _root_projection(os.stat(*args, **kwargs))
            monkeypatch.setattr(fixed, "os", local_os)
            monkeypatch.setattr(fixed, "_info", lambda info: actual_info(_root_projection(info)))
        owner = scope.acquire_fixed_u_input_owner()
        yield SimpleNamespace(workspace=workspace, execution=execution, batch=attempt, scope=scope, owner=owner)
    finally:
        if attempt_fd is not None:
            os.close(attempt_fd)
        if "scope" in locals():
            scope.close()
        # Restore private fixture write permission only after original closure.
        for name in (".rsi-input", ".producer-input", "retained-old-input"):
            path = attempt / name
            if path.is_dir():
                path.chmod(0o700)


def _prepare(scene, kind):
    if kind == "rsi":
        memory = _memory()
        return rsi.prepare_native_rsi_inputs(
            scene.workspace, journal_id=scene.scope.journal_id,
            request=_request(memory), memory=memory, fixed_u_owner=scene.owner,
        )
    return producer.prepare_producer_launch_inputs(
        scene.workspace, journal_id=scene.scope.journal_id, config=_config(), fixed_u_owner=scene.owner,
    )


@pytest.fixture(scope="module")
def native_artifact(tmp_path_factory):
    return build_native_bootstrap_artifact(tmp_path_factory.mktemp("fixed-u-input-bootstrap"))


def _bound(scene, kind, artifact):
    descriptor = _prepare(scene, kind)
    source = scene.workspace / "producer"
    source.mkdir()
    (source / "target").write_bytes(b"inert attested input target; never executed\n")
    (source / "target").chmod(0o700)
    contract = HEX if kind == "rsi" else _contract().digest()
    intent = build_producer_launch_intent(
        producer_root=source, launch_id="fixed-input-launch", journal_id=scene.scope.journal_id,
        run_id="fixed-input-run", parent_task_id="fixed-input-parent", task_id="fixed-input-task",
        contract_sha256=contract, evaluator_kind="local", evaluator_fingerprint=HEX,
        runner_fingerprint=HEX, generator_fingerprint=HEX, dependency_sha256=HEX,
        environment_sha256=HEX, producer_id="inert-fixture", producer_fingerprint=HEX,
        executable_relative="target", argv=("target", *descriptor.argv_fragment),
        working_directory="work", output_directory="output", request_timeout_seconds=1,
        max_requests=1, output_max_bytes=4096, wall_timeout_seconds=8,
    )
    attestation = build_producer_launch_attestation(intent, "fixed-input-fixture-once")
    bind = rsi.bind_native_rsi_launch if kind == "rsi" else producer.bind_producer_launch_inputs
    bound = bind(scene.workspace, intent=intent, attestation=attestation, artifact=artifact,
                 inputs=descriptor, fixed_u_owner=scene.owner)
    validate = rsi.validate_native_rsi_launch_inputs if kind == "rsi" else producer.validate_producer_launch_inputs
    return bound, lambda **kwargs: validate(
        scene.workspace, intent=intent, attestation=attestation, artifact=artifact, **kwargs,
    )


@pytest.mark.parametrize("kind", ["rsi", "producer"])
def test_fixed_profile_full_python_binding_and_original_data_only_grants(original_fixture, native_artifact, kind):
    scene = original_fixture
    bound, validate = _bound(scene, kind, native_artifact)
    value = json.loads(bound.manifest_json)
    assert value["schema_version"] == "2"
    assert value["input_security"] == scene.owner.security_binding
    assert value["input_security"]["profile"] == fixed.FIXED_U_INPUT_PROFILE
    assert bound.argv_fragment == (
        rsi.NATIVE_RSI_INPUT_MARKER if kind == "rsi" else producer.PRODUCER_LAUNCH_INPUT_MARKER,
        bound.manifest_sha256,
    )
    assert stat.S_IMODE(bound.inputs_path.stat().st_mode) == 0o550
    assert os.getxattr(bound.inputs_path, fixed._ACCESS) == fixed._acl(scene.scope._profile["uid"], 5)
    assert stat.S_IMODE((bound.inputs_path / "manifest.json").stat().st_mode) == 0o400
    with pytest.raises(OSError) as missing:
        os.getxattr(bound.inputs_path / "manifest.json", fixed._ACCESS)
    assert missing.value.errno == errno.ENODATA
    for path in bound.read_paths:
        assert path.name != "manifest.json"
        assert stat.S_IMODE(path.stat().st_mode) == 0o440
        assert os.getxattr(path, fixed._ACCESS) == fixed._acl(scene.scope._profile["uid"], 4)
    before = {path.name: (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_ctime_ns)
              for path in bound.inputs_path.iterdir()}
    assert validate(fixed_u_owner=scene.owner, require_unexpired=True) == bound
    assert before == {path.name: (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_ctime_ns)
                      for path in bound.inputs_path.iterdir()}
    proposals = original_native_grant_inputs(bound, fixed_u_owner=scene.owner)
    assert {Path(item.path).name for item in proposals.requests} == {path.name for path in bound.read_paths}
    with hold_producer_grants(proposals.requests, expected_bindings=proposals.expected_bindings) as grants:
        grants.validate_protected_materials(proposals.materials, fixed_u_owner=scene.owner)
        with pytest.raises(ProducerGrantError):
            grants.validate_protected_materials(proposals.materials)
    with pytest.raises(NativeGrantInputError):
        original_native_grant_inputs(bound)
    with pytest.raises((rsi.NativeRSIInputError, producer.ProducerLaunchInputError)):
        validate()
    assert not hasattr(scene.owner, "pass_fds")
    assert not (scene.batch / "process-registration.json").exists()


@pytest.mark.parametrize("operation", [copy.copy, copy.deepcopy, pickle.dumps])
def test_original_owner_cannot_be_copied_or_serialized(original_fixture, operation):
    with pytest.raises(fixed.NativeFixedUInputError):
        operation(original_fixture.owner)


def test_same_numeric_fields_do_not_recreate_child_owner(original_fixture):
    scene = original_fixture
    duplicate = object.__new__(fixed.NativeFixedUInputOwner)
    for name in fixed.NativeFixedUInputOwner.__slots__:
        setattr(duplicate, name, getattr(scene.owner, name))
    with pytest.raises(fixed.NativeFixedUInputError):
        fixed.checked_fixed_u_input_owner(duplicate)
    with pytest.raises(fixed.NativeFixedUInputError):
        scene.scope.acquire_fixed_u_input_owner()


@pytest.mark.parametrize("fault", ["data-write", "file-replacement", "directory-replacement", "extra-file",
                                    "access-acl", "default-acl", "namespace", "profile", "mount", "deadline-renewal"])
def test_original_material_or_security_drift_refuses_without_refresh(original_fixture, monkeypatch, fault):
    scene = original_fixture
    descriptor = _prepare(scene, "producer")
    path = descriptor.config_path
    original_manifest = descriptor.manifest_json
    if fault == "data-write":
        assert os.pwrite(scene.owner._records["config.json"]["fd"], b"!", 0) == 1
    elif fault == "file-replacement":
        descriptor.inputs_path.chmod(0o700)
        raw = path.read_bytes()
        path.unlink()
        path.write_bytes(raw)
        path.chmod(0o440)
        descriptor.inputs_path.chmod(0o550)
    elif fault == "directory-replacement":
        descriptor.inputs_path.rename(scene.batch / "retained-old-input")
        descriptor.inputs_path.mkdir(mode=0o550)
    elif fault == "extra-file":
        descriptor.inputs_path.chmod(0o700)
        (descriptor.inputs_path / "unexpected.json").write_bytes(b"{}")
        descriptor.inputs_path.chmod(0o550)
    elif fault == "access-acl":
        uid = scene.scope._profile["uid"]
        entries = [(1, 4, 2**32 - 1), *((2, 4, item) for item in sorted((uid, uid - 1))),
                   (4, 0, 2**32 - 1), (16, 4, 2**32 - 1), (32, 0, 2**32 - 1)]
        os.setxattr(path, fixed._ACCESS, struct.pack("<I", 2) + b"".join(
            struct.pack("<HHI", *entry) for entry in entries))
        assert stat.S_IMODE(path.stat().st_mode) == 0o440
    elif fault == "default-acl":
        os.setxattr(descriptor.inputs_path, fixed._DEFAULT, fixed._acl(scene.scope._profile["uid"], 5))
    elif fault == "namespace":
        values = scene.scope._profile["namespaces"]
        scene.scope._profile["namespaces"] = ((values[0][0], values[0][1] + 1), *values[1:])
    elif fault == "profile":
        scene.scope._profile_sha256 = "b" * 64
    elif fault == "mount":
        actual = whole._mount_id
        monkeypatch.setattr(whole, "_mount_id", lambda fd, name=b"": actual(fd, name) + 1)
    elif fault == "deadline-renewal":
        scene.scope._deadline = scene.owner._deadline + 1
    with pytest.raises((fixed.NativeFixedUInputError, whole.NativeWholeScopeError)):
        fixed.checked_fixed_u_input_owner(scene.owner, require_unexpired=False)
    assert descriptor.manifest_json == original_manifest


@pytest.mark.parametrize("kind", ["rsi", "producer"])
def test_expiry_allows_only_original_pin_diagnostics(original_fixture, native_artifact, kind):
    scene = original_fixture
    descriptor, validate = _bound(scene, kind, native_artifact)
    scene.scope._deadline = time.monotonic_ns() - 1
    assert validate(fixed_u_owner=scene.owner, require_unexpired=False) == descriptor
    with pytest.raises((rsi.NativeRSIInputError, producer.ProducerLaunchInputError)):
        validate(fixed_u_owner=scene.owner, require_unexpired=True)
    with pytest.raises((rsi.NativeRSIInputError, producer.ProducerLaunchInputError)):
        _prepare(scene, kind)
    assert scene.owner.binding(require_unexpired=False)["deadline_monotonic_ns"] == scene.owner._deadline


def test_partial_create_is_retained_and_original_descriptors_close(original_fixture, monkeypatch):
    scene = original_fixture
    actual = fixed.os.write
    calls = []

    def fail_manifest(fd, data):
        calls.append(fd)
        if len(calls) == 2:
            raise OSError(errno.ENOSPC, "fixture interrupted manifest write")
        return actual(fd, data)

    monkeypatch.setattr(fixed.os, "write", fail_manifest)
    with pytest.raises(producer.ProducerLaunchInputError):
        _prepare(scene, "producer")
    assert (scene.batch / ".producer-input" / "config.json").is_file()
    assert (scene.batch / ".producer-input" / "manifest.json").is_file()
    with pytest.raises(producer.ProducerLaunchInputError):
        _prepare(scene, "producer")
    original_fds = [record["fd"] for record in scene.owner._records.values()]
    scene.owner.close()
    for fd in original_fds:
        with pytest.raises(OSError) as closed:
            os.fstat(fd)
        assert closed.value.errno == errno.EBADF
    with pytest.raises(fixed.NativeFixedUInputError):
        fixed.checked_fixed_u_input_owner(scene.owner, require_unexpired=False)


def test_detached_input_dto_cannot_replace_original_bytes(original_fixture):
    scene = original_fixture
    descriptor = _prepare(scene, "producer")
    forged = replace(descriptor, config_json=descriptor.config_json + b" ")
    with pytest.raises(NativeGrantInputError):
        original_native_grant_inputs(forged, fixed_u_owner=scene.owner)
