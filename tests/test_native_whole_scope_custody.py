"""Original-path custody contracts, without installed root-profile acceptance.

Linux fixtures use real files, directory FDs, inode links and statx mounts. Only
the fixture's root ownership/ancestor policy and installed owner acquisition are
projected. They cannot accept real credentials, cgroups, R durability or G1.
"""
from __future__ import annotations

import copy
import json
import os
import pickle
import stat
import struct
import sys
import time
from types import SimpleNamespace

import pytest

from lunar_evolution import native_whole_scope as whole
from lunar_evolution import native_whole_scope_custody as custody

LINUX = pytest.mark.skipif(sys.platform != "linux", reason="actual Linux statx/xattr mechanisms")


@pytest.mark.parametrize("value", [None, {}, object(), b"", "record"])
def test_detached_inputs_cannot_select_or_recover_a_live_scope(value):
    with pytest.raises(custody.NativeWholeScopeCustodyError, match="owner_invalid"):
        custody._acquire_whole_scope_custody(value)
    observed = custody.inspect_native_whole_scope_custody(value)
    assert observed["state"] == "unknown"
    assert observed["cleanup_status"] == "unknown"
    assert not observed["durable_acknowledgement_verified"]
    assert not observed["whole_group_cleanup_verified"]


def test_private_owner_requires_original_token():
    with pytest.raises(custody.NativeWholeScopeCustodyError, match="owner_invalid"):
        custody.NativeWholeScopeCustodyOwner(object(), object())


@pytest.mark.parametrize("raw", [b"", b"{}", b"{}\n", b"x" * 32769, b"null", b"[]", b"\xff"])
def test_malformed_reference_is_bounded_and_returns_fixed_unknown(raw, monkeypatch):
    monkeypatch.setattr(custody, "_open_chain", lambda *_a: pytest.fail("invalid reference opened files"))
    observed = custody.inspect_native_whole_scope_custody(custody.NativeWholeScopeCustodyReference(raw))
    assert observed["codes"] == ["native_whole_scope_custody_unknown"]
    assert "path" not in observed


@pytest.fixture
def original(tmp_path, monkeypatch):
    if sys.platform != "linux":
        pytest.skip("actual Linux statx/xattr mechanisms")
    # Project only root installation metadata at the fixture helper boundary.
    # Opened descriptors, bytes, mounts, names, inode drift and fd retirement
    # remain actual; this is not an installed-root/U-drop acceptance fixture.
    original_stat, original_fstat = os.stat, os.fstat
    ancestor_inodes = set()
    for path in (tmp_path, *tmp_path.parents):
        info = original_stat(path)
        ancestor_inodes.add((info.st_dev, info.st_ino))

    def projection(info):
        fields = {name: getattr(info, name) for name in (
            "st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_nlink", "st_size",
            "st_mtime_ns", "st_ctime_ns",
        )}
        fields.update(st_uid=0, st_gid=0)
        if (info.st_dev, info.st_ino) in ancestor_inodes:
            fields["st_mode"] &= ~0o022
        return SimpleNamespace(**fields)

    monkeypatch.setattr(whole.os, "stat", lambda *a, **k: projection(original_stat(*a, **k)))
    monkeypatch.setattr(whole.os, "fstat", lambda fd: projection(original_fstat(fd)))
    execution = tmp_path / "execution"
    execution.mkdir(mode=0o700)
    journal = "lunar-" + "a" * 64
    attempt = execution / journal
    attempt.mkdir(mode=0o700)
    owner = whole.NativeWholeScopeOwner(whole._TOKEN)
    owner._profile = {"paths": ("/unused", os.fspath(execution)), "uid": 65534,
                      "gid": 65534, "groups": (), "bootstrap_sha256": "b" * 64,
                      "supervisor_sha256": "c" * 64}
    owner._profile_sha256 = "d" * 64
    owner._deadline = time.monotonic_ns() + 20_000_000_000
    owner._preparation_key = "a" * 64
    parent = owner._own(os.open(attempt, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC))
    owner._published = (parent,)
    owner._publication_pins = ((whole._kernel_identity(parent), None),)
    monkeypatch.setattr(owner, "_check_published_grants", lambda: None)
    monkeypatch.setattr(owner, "_check_installation", lambda: None)
    child = owner.acquire_custody_owner()
    try:
        yield owner, child, attempt / custody._DIRECTORY
    finally:
        child.close()
        owner.close()


def _register(owner, child, path):
    descriptor = child._borrow_for_start()
    assert descriptor == child._directory
    owner._binding = owner._core(launch="1" * 64, intent="2" * 64, target="3" * 64,
                                 deadline_ns=owner._deadline)
    owner._scope = whole._IDENTITY.pack(31, 41, 51, 0, 0, stat.S_IFDIR | 0o700, 0)
    owner._target_pid = 123
    publications = b"".join(whole._PUBLICATION.pack(71, 81 + i, 12, 15, 16, b"e" * 64 + b"\0")
                            for i in range(3))
    registration = (whole._HEADER.pack(0x3151574C, 1, 14, 1, 0, 0) + owner._binding
                    + owner._scope + struct.pack("<Q", owner._target_pid) + publications)
    for name, raw in zip(custody._NAMES, (registration, b""), strict=True):
        fd = os.open(path / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
        try:
            os.write(fd, raw)
        finally:
            os.close(fd)
    # This fixture models the original S registration ACK boundary. No real R
    # fsync/ACK or actual scope completion is asserted by the fixture.
    child._bind_registration(publications)
    return registration


def _terminal(path, registration):
    raw = bytearray(registration)
    struct.pack_into("<II", raw, 8, 15, 2)
    with (path / custody._NAMES[1]).open("wb") as stream:
        stream.write(raw)


@LINUX
def test_explicit_original_directory_has_no_candidate_grant_or_inheritance(original):
    owner, child, path = original
    assert owner.original_custody_owner is child
    assert stat.S_IMODE(path.stat().st_mode) == 0o700
    assert not os.get_inheritable(child._directory)
    assert child._directory not in owner._published
    assert custody._names(child._directory) == ()


@LINUX
@pytest.mark.parametrize("clone", [copy.copy, copy.deepcopy, pickle.dumps])
def test_original_child_rejects_copies_and_serialization(original, clone):
    with pytest.raises(custody.NativeWholeScopeCustodyError, match="owner_invalid"):
        clone(original[1])


@LINUX
def test_acquisition_is_once_only_and_before_channels_or_frozen_intent(original):
    owner, _child, _path = original
    with pytest.raises(custody.NativeWholeScopeCustodyError, match="owner_invalid"):
        owner.acquire_custody_owner()
    owner._custody_owner = None
    for field, value in (("_channels_prepared", True), ("_final_intent", "f" * 64)):
        setattr(owner, field, value)
        with pytest.raises(custody.NativeWholeScopeCustodyError, match="owner_invalid"):
            owner.acquire_custody_owner()
        setattr(owner, field, False if field == "_channels_prepared" else None)
    # Restore the actual child so its original descriptors are retired.
    owner._custody_owner = _child


@LINUX
def test_normal_records_are_consumed_but_recovery_never_grants_cleanup(original):
    owner, child, path = original
    registration = _register(owner, child, path)
    child._check_registration()
    reference = child.reference
    prefix = custody.inspect_native_whole_scope_custody(reference)
    assert prefix["state"] == "registration_prefix_observed"
    assert prefix["registration_record_observed"] and not prefix["terminal_record_observed"]
    _terminal(path, registration)
    child._check_registration(terminal=True)
    terminal = custody.inspect_native_whole_scope_custody(reference)
    assert terminal["state"] == "terminal_record_observed"
    assert terminal["terminal_record_observed"]
    assert terminal["cleanup_status"] == "unknown"
    assert all(terminal[name] is False for name in (
        "durable_acknowledgement_verified", "native_success", "whole_group_cleanup_verified",
        "original_quiescence_observed", "production_admission", "publication_authority", "online_publication",
    ))
    assert "path" not in terminal and "target_pid" not in terminal


@LINUX
def test_post_expiry_original_prefix_remains_read_only_and_cannot_relaunch(original, monkeypatch):
    owner, child, path = original
    _register(owner, child, path)
    reference = child.reference
    monkeypatch.setattr(whole.time, "monotonic_ns", lambda: owner._deadline + 1)
    assert child.reference is reference
    with pytest.raises(whole.NativeWholeScopeError, match="deadline_exceeded"):
        child._check_registration()
    with pytest.raises(whole.NativeWholeScopeError, match="deadline_exceeded"):
        child._borrow_for_start()
    before = {name: (path / name).read_bytes() for name in custody._NAMES}
    assert custody.inspect_native_whole_scope_custody(reference)["state"] == "registration_prefix_observed"
    assert {name: (path / name).read_bytes() for name in custody._NAMES} == before


@LINUX
@pytest.mark.parametrize("fault", ["replace", "symlink", "extra", "partial", "wrong-bytes", "mode", "hardlink"])
def test_record_replacement_shape_partial_and_metadata_drift_stay_unknown(original, fault):
    owner, child, path = original
    _register(owner, child, path)
    reference = child.reference
    record = path / custody._NAMES[0]
    if fault == "replace":
        data = record.read_bytes()
        record.unlink()
        record.write_bytes(data)
        record.chmod(0o600)
    elif fault == "symlink":
        record.rename(path / "original")
        record.symlink_to(path / "original")
    elif fault == "extra":
        (path / "unexpected").write_bytes(b"x")
    elif fault == "partial":
        (path / custody._NAMES[1]).write_bytes(b"partial")
    elif fault == "wrong-bytes":
        record.write_bytes(b"z" * whole._MESSAGE_SIZE)
    elif fault == "mode":
        record.chmod(0o640)
    else:
        os.link(record, path.parent / "alias")
    assert custody.inspect_native_whole_scope_custody(reference)["state"] == "unknown"
    with pytest.raises((custody.NativeWholeScopeCustodyError, OSError)):
        child._check_registration()


@LINUX
@pytest.mark.parametrize("fault", ["directory-replace", "directory-mode", "origin", "renew-deadline", "detached"])
def test_original_directory_owner_binding_and_deadline_cannot_drift(original, fault):
    owner, child, path = original
    _register(owner, child, path)
    if fault == "directory-replace":
        path.rename(path.with_name("retained-original"))
        path.mkdir(mode=0o700)
    elif fault == "directory-mode":
        path.chmod(0o755)
    elif fault == "origin":
        owner._profile_sha256 = "f" * 64
    elif fault == "renew-deadline":
        owner._deadline += 1
    else:
        owner._custody_owner = None
    with pytest.raises(custody.NativeWholeScopeCustodyError):
        child._check_registration()
    owner._custody_owner = child


@LINUX
def test_missing_terminal_and_early_terminal_do_not_satisfy_wrong_gate(original):
    owner, child, path = original
    registration = _register(owner, child, path)
    with pytest.raises(custody.NativeWholeScopeCustodyError, match="terminal_unknown"):
        child._check_registration(terminal=True)
    _terminal(path, registration)
    with pytest.raises(custody.NativeWholeScopeCustodyError, match="record_changed"):
        child._check_registration()


@LINUX
def test_read_only_reader_detects_drift_between_original_reads(original, monkeypatch):
    owner, child, path = original
    _register(owner, child, path)
    reference = child.reference
    read = custody._read_records
    calls = []

    def mutate_after_read(fd):
        result = read(fd)
        calls.append(fd)
        if len(calls) == 1:
            (path / custody._NAMES[1]).write_bytes(b"partial")
        return result

    monkeypatch.setattr(custody, "_read_records", mutate_after_read)
    assert custody.inspect_native_whole_scope_custody(reference)["state"] == "unknown"


@LINUX
def test_reference_binding_drift_is_not_loaded_from_current_records(original):
    owner, child, path = original
    _register(owner, child, path)
    value = json.loads(child.reference.canonical_bytes)
    raw = bytearray.fromhex(value["registration"])
    # Change an actual launch digest byte, preserving valid wire structure.
    # Searching hex text for ASCII digest letters can silently mutate nothing.
    offset = whole._HEADER.size + 8
    assert raw[offset] == ord("1")
    raw[offset] = ord("2")
    value["registration"] = raw.hex()
    assert value["registration"] != json.loads(child.reference.canonical_bytes)["registration"]
    altered = custody.NativeWholeScopeCustodyReference(custody._json(value))
    assert custody.inspect_native_whole_scope_custody(altered)["state"] == "unknown"


@LINUX
def test_closed_original_retires_directory_fds_and_retained_reference_is_diagnostic(original):
    owner, child, path = original
    _register(owner, child, path)
    reference = child.reference
    descriptors = [child._directory, *child._chain]
    child.close()
    child.close()
    for fd in descriptors:
        with pytest.raises(OSError):
            os.fstat(fd)
    with pytest.raises(custody.NativeWholeScopeCustodyError, match="owner_invalid"):
        _ = child.reference
    assert custody.inspect_native_whole_scope_custody(reference)["cleanup_status"] == "unknown"
