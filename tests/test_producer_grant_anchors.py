"""Inert host grant ownership and drift fixtures; no target or provider execution."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import stat
from dataclasses import replace
from pathlib import Path

import pytest

import lunar_evolution.producer_grant_anchors as grants
from lunar_evolution.producer_grant_anchors import (
    ProducerGrantError,
    ProducerGrantIdentity,
    ProducerGrantManifest,
    ProducerGrantRequest,
    hold_producer_grants,
)


def _identity(path):
    info = path.lstat()
    kind = "directory" if stat.S_ISDIR(info.st_mode) else "file"
    return ProducerGrantIdentity(info.st_dev, info.st_ino, kind)


def _request(path, role, *, expected=False):
    return ProducerGrantRequest(str(path), role, _identity(path) if expected else None)


def _file(tmp_path, name="input.json"):
    path = tmp_path.resolve() / name
    path.write_bytes(b"inert original input")
    return path


def _directory(tmp_path, name="work"):
    path = tmp_path.resolve() / name
    path.mkdir()
    return path


def _held(requests):
    return hold_producer_grants(tuple(requests))


def _refused(requests, *, reason=None):
    with pytest.raises(ProducerGrantError) as error, hold_producer_grants(requests):
        pytest.fail("invalid grant request acquired an owner")
    assert error.value.code.startswith("producer_grant_")
    assert str(error.value) == error.value.code
    if reason is not None:
        assert error.value.code == "producer_grant_" + reason
    return error.value


def _fd_closed(fd):
    try:
        os.fstat(fd)
    except OSError as error:
        assert error.errno == errno.EBADF
        return True
    return False


def _watch_acquisition(monkeypatch):
    original_open = os.open
    opened = []

    def watched(*args, **kwargs):
        fd = original_open(*args, **kwargs)
        opened.append(fd)
        return fd

    monkeypatch.setattr(grants.os, "open", watched)
    return opened, original_open


def _forbid_filesystem(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("request validation must precede filesystem I/O")

    monkeypatch.setattr(grants.os, "open", forbidden)
    monkeypatch.setattr(grants.os, "stat", forbidden)


def test_original_input_runtime_and_write_cwd_merge_are_live_and_detached(tmp_path):
    source = _file(tmp_path)
    runtime = _directory(tmp_path, "runtime")
    work = _directory(tmp_path)
    requests = (
        _request(work, "cwd", expected=True),
        _request(source, "protected-file", expected=True),
        _request(runtime, "readonly-directory"),
        _request(work, "writable-directory"),
    )
    with hold_producer_grants(requests) as plan:
        plan.validate(reserved_fds=(0, 1, 2))
        anchors = plan.anchors
        assert len(anchors) == 3
        assert tuple(anchor.record.path for anchor in anchors) == tuple(
            sorted((str(source), str(runtime), str(work)))
        )
        assert plan.pass_fds == tuple(anchor.fd for anchor in anchors)
        assert len(set(plan.pass_fds)) == 3
        for anchor in anchors:
            assert anchor.record.identity == _identity(Path(anchor.record.path))
            assert anchor.fd > 2
            assert os.get_inheritable(anchor.fd) is False
        work_anchor = next(anchor for anchor in anchors if anchor.record.path == str(work))
        assert work_anchor.record.roles == ("cwd", "writable-directory")
        manifest = plan.manifest
        detached = manifest.to_dict()
        assert detached["schema_version"] == "1"
        assert detached["scope"] == "host-held-grant-anchors"
        assert detached["execution_enforced"] is False
        assert set(detached) == {"schema_version", "scope", "execution_enforced", "records", "manifest_sha256"}
        assert all(set(record) == {"path", "roles", "identity"} for record in detached["records"])
        payload = {key: value for key, value in detached.items() if key != "manifest_sha256"}
        assert manifest.manifest_sha256 == hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()
        detached["records"][0]["roles"].append("forged")
        assert manifest.to_dict() != detached
    assert all(_fd_closed(anchor.fd) for anchor in anchors)
    # The manifest stays usable as observation after live ownership ends.
    manifest.validate()
    assert manifest.to_dict()["execution_enforced"] is False
    for access in (lambda: plan.validate(), lambda: plan.anchors, lambda: plan.pass_fds, lambda: plan.manifest):
        with pytest.raises(ProducerGrantError, match="producer_grant_owner_closed"):
            access()


def test_request_order_does_not_change_manifest_or_original_identity(tmp_path):
    left = _directory(tmp_path, "a")
    right = _directory(tmp_path, "b")
    requests = (_request(left, "writable-directory"), _request(right, "readonly-directory"))
    with hold_producer_grants(requests) as first, hold_producer_grants(requests[::-1]) as second:
        assert first.manifest == second.manifest
        assert set(first.pass_fds).isdisjoint(second.pass_fds)
        assert tuple(anchor.record for anchor in first.anchors) == tuple(anchor.record for anchor in second.anchors)


def test_directory_changes_preserve_identity_and_output_writes(tmp_path):
    work = _directory(tmp_path)
    with _held((_request(work, "writable-directory"), _request(work, "cwd"))) as plan:
        original = plan.manifest
        (work / "ordinary-output").write_bytes(b"candidate fixture")
        (work / "nested").mkdir()
        plan.validate()
        assert plan.manifest == original
    assert (work / "ordinary-output").read_bytes() == b"candidate fixture"


def test_contents_and_modes_are_explicitly_outside_object_identity_claim(tmp_path):
    source = _file(tmp_path)
    with _held((_request(source, "protected-file", expected=True),)) as plan:
        original = plan.manifest
        source.write_bytes(b"changed same inode")
        source.chmod(0o600)
        plan.validate()
        assert plan.manifest == original
        assert plan.manifest.to_dict()["execution_enforced"] is False


def test_writable_nested_directories_remain_usable_without_readonly_conflict(tmp_path):
    work = _directory(tmp_path)
    output = work / "output"
    output.mkdir()
    with _held((_request(work, "writable-directory"), _request(output, "writable-directory"), _request(work, "cwd"))) as plan:
        assert len(plan.anchors) == 2
        (output / "ok").write_bytes(b"inert")
        plan.validate()


@pytest.mark.parametrize("value", [(), [], None, object(), (object(),)], ids=["empty", "list", "none", "object", "wrong-element"])
def test_exact_bounded_request_tuple_is_required_before_io(monkeypatch, value):
    _forbid_filesystem(monkeypatch)
    _refused(value, reason="requests_invalid")


@pytest.mark.parametrize("path", [
    "relative", "", "/x/", "//x", "/x//y", "/x/./y", "/x/../y", "/x\x00y", "/\ud800",
    "/" + "a" * 4096, "/" + "界" * 1400, "/" + "/".join(["a"] * 65),
    Path("/path"), None, 5,
], ids=["relative", "empty", "trailing", "double-root", "empty-component", "dot", "parent", "nul", "surrogate", "byte-limit", "utf8-limit", "depth-limit", "path-object", "none", "integer"])
def test_noncanonical_and_oversized_paths_refuse_before_io(monkeypatch, path):
    _forbid_filesystem(monkeypatch)
    _refused((ProducerGrantRequest(path, "readonly-directory"),), reason="path_invalid")


@pytest.mark.parametrize("role", ["unknown", "protected-file", None, True])
def test_unknown_roles_and_missing_protected_pin_refuse_before_io(monkeypatch, role):
    _forbid_filesystem(monkeypatch)
    _refused((ProducerGrantRequest("/inert", role),), reason="expected_identity_required" if role == "protected-file" else "role_invalid")


@pytest.mark.parametrize("changes", [
    {"device": -1}, {"device": True}, {"device": 1 << 64}, {"device": "1"},
    {"inode": 0}, {"inode": -1}, {"inode": True}, {"inode": 1 << 64},
    {"kind": "symlink"}, {"kind": None}, {"kind": True},
])
def test_identity_rejects_invalid_types_and_unsigned_ranges_before_io(monkeypatch, changes):
    _forbid_filesystem(monkeypatch)
    identity = ProducerGrantIdentity(**{"device": 1, "inode": 1, "kind": "file", **changes})
    _refused((ProducerGrantRequest("/inert", "protected-file", identity),), reason="identity_invalid")


@pytest.mark.parametrize("role,kind", [("protected-file", "directory"), ("readonly-directory", "file"), ("writable-directory", "file"), ("cwd", "file")])
def test_expected_kind_must_match_role_before_io(monkeypatch, role, kind):
    _forbid_filesystem(monkeypatch)
    identity = ProducerGrantIdentity(1, 1, kind)
    _refused((ProducerGrantRequest("/inert", role, identity),), reason="object_kind_invalid")


@pytest.mark.parametrize("role", ["writable-directory", "cwd"])
def test_root_cannot_be_writable_or_cwd(monkeypatch, role):
    _forbid_filesystem(monkeypatch)
    _refused((ProducerGrantRequest("/", role),), reason="root_write_invalid")


def test_cwd_requires_the_exact_writable_directory_request(monkeypatch):
    _forbid_filesystem(monkeypatch)
    _refused((ProducerGrantRequest("/inert/child", "cwd"), ProducerGrantRequest("/inert", "writable-directory")), reason="cwd_write_required")


def test_duplicate_path_role_and_conflicting_original_expectations_refuse_before_io(monkeypatch):
    _forbid_filesystem(monkeypatch)
    request = ProducerGrantRequest("/inert", "readonly-directory")
    _refused((request, request), reason="duplicate_role")
    _refused((ProducerGrantRequest("/inert", "writable-directory", ProducerGrantIdentity(1, 1, "directory")), ProducerGrantRequest("/inert", "cwd", ProducerGrantIdentity(1, 2, "directory"))), reason="expected_identity_conflict")


@pytest.mark.parametrize("readonly,write,role", [
    ("/inert/input", "/inert", "protected-file"),
    ("/inert/ro", "/inert", "readonly-directory"),
    ("/inert", "/inert/child", "readonly-directory"),
    ("/inert", "/inert", "readonly-directory"),
])
def test_protected_and_readonly_write_overlap_refuses_before_io(monkeypatch, readonly, write, role):
    _forbid_filesystem(monkeypatch)
    expected = ProducerGrantIdentity(1, 1, "file") if role == "protected-file" else None
    _refused((ProducerGrantRequest(readonly, role, expected), ProducerGrantRequest(write, "writable-directory")), reason="write_overlap")


@pytest.mark.parametrize("role,count", [("readonly-directory", 65), ("writable-directory", 17), ("cwd", 2)])
def test_role_request_limits_refuse_before_io(monkeypatch, role, count):
    _forbid_filesystem(monkeypatch)
    requests = tuple(ProducerGrantRequest(f"/inert/{index}", role) for index in range(count))
    _refused(requests, reason="request_count_invalid")


def test_total_request_and_aggregate_path_byte_limits_refuse_before_io(monkeypatch):
    _forbid_filesystem(monkeypatch)
    _refused(tuple(ProducerGrantRequest(f"/inert/{index}", "readonly-directory") for index in range(82)), reason="requests_invalid")
    # Each path is independently canonical and <4096 bytes, with total >65536.
    requests = tuple(ProducerGrantRequest("/" + str(index) + "a" * 3500, "readonly-directory") for index in range(20))
    _refused(requests, reason="request_count_invalid")


@pytest.mark.parametrize("role", ["protected-file", "readonly-directory", "writable-directory"])
def test_missing_leaf_refuses_and_closes_every_acquired_ancestor(tmp_path, monkeypatch, role):
    path = tmp_path.resolve() / "missing"
    expected = ProducerGrantIdentity(1, 1, "file") if role == "protected-file" else None
    opened, _ = _watch_acquisition(monkeypatch)
    _refused((ProducerGrantRequest(str(path), role, expected),), reason="object_unavailable")
    assert opened and all(_fd_closed(fd) for fd in opened)


@pytest.mark.parametrize("role,is_directory", [("protected-file", True), ("readonly-directory", False), ("writable-directory", False)])
def test_wrong_real_object_kind_refuses_without_leaking_ancestors(tmp_path, monkeypatch, role, is_directory):
    path = _directory(tmp_path) if is_directory else _file(tmp_path)
    expected = ProducerGrantIdentity(path.stat().st_dev, path.stat().st_ino, "file") if role == "protected-file" else None
    opened, _ = _watch_acquisition(monkeypatch)
    _refused((ProducerGrantRequest(str(path), role, expected),), reason="object_kind_invalid")
    assert all(_fd_closed(fd) for fd in opened)


def test_fifo_is_refused_before_opening_special_leaf(tmp_path, monkeypatch):
    path = tmp_path.resolve() / "private-fifo"
    os.mkfifo(path, 0o600)
    opened, _ = _watch_acquisition(monkeypatch)
    expected = ProducerGrantIdentity(path.stat().st_dev, path.stat().st_ino, "file")
    _refused((ProducerGrantRequest(str(path), "protected-file", expected),), reason="object_kind_invalid")
    assert all(_fd_closed(fd) for fd in opened)


@pytest.mark.parametrize("mutation", ["inode", "device"])
def test_original_expected_identity_cannot_be_refreshed_from_current_path(tmp_path, monkeypatch, mutation):
    path = _file(tmp_path)
    original = _identity(path)
    if mutation == "inode":
        replacement = _file(tmp_path, "replacement")
        replacement.replace(path)
        assert _identity(path) != original
    else:
        original = replace(original, device=original.device + 1)
    opened, _ = _watch_acquisition(monkeypatch)
    _refused((ProducerGrantRequest(str(path), "protected-file", original),), reason="expected_identity_mismatch")
    assert all(_fd_closed(fd) for fd in opened)


@pytest.mark.parametrize("location", ["leaf", "ancestor"])
def test_symlink_components_are_never_resolved_into_authorized_objects(tmp_path, monkeypatch, location):
    target = _directory(tmp_path, "target")
    (target / "input").write_bytes(b"inert")
    link = tmp_path.resolve() / "link"
    link.symlink_to(target, target_is_directory=True)
    path = link if location == "leaf" else link / "input"
    role = "readonly-directory" if location == "leaf" else "protected-file"
    expected = None if location == "leaf" else _identity(target / "input")
    opened, _ = _watch_acquisition(monkeypatch)
    _refused((ProducerGrantRequest(str(path), role, expected),), reason="object_kind_invalid")
    assert all(_fd_closed(fd) for fd in opened)


def test_protected_hardlinks_refuse_at_acquisition_and_during_revalidation(tmp_path):
    source = _file(tmp_path)
    requests = (_request(source, "protected-file", expected=True),)
    alias = source.parent / "alias"
    os.link(source, alias)
    _refused(requests, reason="protected_links_invalid")
    alias.unlink()
    with pytest.raises(ProducerGrantError, match="producer_grant_protected_links_invalid"), hold_producer_grants(requests) as plan:
        fd = plan.anchors[0].fd
        os.link(source, alias)
        with pytest.raises(ProducerGrantError, match="producer_grant_protected_links_invalid"):
            plan.validate()
    assert _fd_closed(fd)


@pytest.mark.parametrize("location,substitution", [("leaf", "inode"), ("leaf", "symlink"), ("ancestor", "inode"), ("ancestor", "symlink"), ("cwd", "inode")])
def test_live_original_objects_and_parent_bindings_detect_replacement(tmp_path, monkeypatch, location, substitution):
    parent = _directory(tmp_path, "parent")
    leaf = parent / "work"
    leaf.mkdir()
    requests = (_request(leaf, "writable-directory"),)
    if location == "cwd":
        requests += (_request(leaf, "cwd"),)
    opened, _ = _watch_acquisition(monkeypatch)
    with pytest.raises(ProducerGrantError), hold_producer_grants(requests) as plan:
        old = plan.manifest
        displaced = leaf if location in {"leaf", "cwd"} else parent
        backup = displaced.with_name(displaced.name + "-original")
        displaced.rename(backup)
        if substitution == "symlink":
            displaced.symlink_to(backup, target_is_directory=True)
        else:
            displaced.mkdir()
            if location == "ancestor":
                (displaced / "work").mkdir()
        if location in {"leaf", "cwd"}:
            assert _identity(backup).inode == next(
                record.identity.inode for record in old.records if record.path == str(leaf)
            )
        for access in (lambda: plan.validate(), lambda: plan.anchors, lambda: plan.pass_fds, lambda: plan.manifest):
            with pytest.raises(ProducerGrantError):
                access()
    assert all(_fd_closed(fd) for fd in opened)


def test_body_exception_survives_exit_drift_and_all_owner_fds_close(tmp_path, monkeypatch):
    work = _directory(tmp_path)
    opened, _ = _watch_acquisition(monkeypatch)
    sentinel = RuntimeError("disposable fixture body failure")
    with pytest.raises(RuntimeError) as error, _held((_request(work, "writable-directory"),)):
        work.rename(work.with_name("displaced"))
        work.mkdir()
        raise sentinel
    assert error.value is sentinel
    assert all(_fd_closed(fd) for fd in opened)


@pytest.mark.parametrize("kind", ["file", "directory"])
def test_reserved_leaf_descriptor_conflicts_are_refused_without_losing_owner(tmp_path, kind):
    path = _file(tmp_path) if kind == "file" else _directory(tmp_path)
    role = "protected-file" if kind == "file" else "writable-directory"
    with _held((_request(path, role, expected=kind == "file"),)) as plan:
        leaf = plan.pass_fds[0]
        with pytest.raises(ProducerGrantError, match="producer_grant_fd_alias"):
            plan.validate(reserved_fds=(leaf,))
        plan.validate(reserved_fds=(0, 1, 2))
        assert plan.pass_fds == (leaf,)


@pytest.mark.parametrize("reserved", [[3], None, (True,), (-1,), (1 << 31,), tuple(range(257))])
def test_reserved_descriptor_input_has_strict_finite_tuple_contract(tmp_path, reserved):
    work = _directory(tmp_path)
    with _held((_request(work, "writable-directory"),)) as plan:
        with pytest.raises(ProducerGrantError, match="producer_grant_reserved_fds_invalid"):
            plan.validate(reserved_fds=reserved)
        plan.validate()


def test_closed_leaf_fd_is_not_reacquired_and_other_original_fds_close(tmp_path, monkeypatch):
    work = _directory(tmp_path)
    opened, _ = _watch_acquisition(monkeypatch)
    with pytest.raises(ProducerGrantError, match="producer_grant_object_unavailable"), _held((_request(work, "writable-directory"),)) as plan:
        leaf = plan.pass_fds[0]
        os.close(leaf)
        with pytest.raises(ProducerGrantError, match="producer_grant_object_unavailable"):
            plan.validate()
    assert all(_fd_closed(fd) for fd in opened)


def test_reused_descriptor_is_rejected_without_closing_unrelated_object(tmp_path, monkeypatch):
    work = _directory(tmp_path)
    unrelated = _file(tmp_path, "unrelated")
    opened, original_open = _watch_acquisition(monkeypatch)
    unrelated_fd = None
    try:
        with pytest.raises(ProducerGrantError), _held((_request(work, "writable-directory"),)) as plan:
            leaf = plan.pass_fds[0]
            os.close(leaf)
            unrelated_fd = original_open(unrelated, os.O_RDONLY | os.O_CLOEXEC)
            assert unrelated_fd == leaf
            with pytest.raises(ProducerGrantError):
                plan.validate()
        assert os.fstat(unrelated_fd).st_ino == unrelated.stat().st_ino
        assert os.read(unrelated_fd, 5) == b"inert"
        assert all(_fd_closed(fd) for fd in opened if fd != unrelated_fd)
    finally:
        if unrelated_fd is not None and not _fd_closed(unrelated_fd):
            os.close(unrelated_fd)


def test_partial_open_failure_closes_every_previously_acquired_owner_fd(tmp_path, monkeypatch):
    work = _directory(tmp_path)
    original_open = os.open
    opened = []

    def failed(*args, **kwargs):
        if len(opened) == 3:
            raise OSError(errno.EMFILE, "inert acquisition fault")
        fd = original_open(*args, **kwargs)
        opened.append(fd)
        return fd

    monkeypatch.setattr(grants.os, "open", failed)
    _refused((_request(work, "writable-directory"),), reason="object_unavailable")
    assert len(opened) == 3
    assert all(_fd_closed(fd) for fd in opened)


def test_object_substitution_between_stat_and_open_closes_actual_opened_object(tmp_path, monkeypatch):
    work = _directory(tmp_path)
    original_open = os.open
    opened = []
    swapped = False

    def swapped_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if path == work.name and not swapped:
            swapped = True
            work.rename(work.with_name("original-work"))
            work.mkdir()
        fd = original_open(path, flags, *args, **kwargs)
        opened.append(fd)
        return fd

    monkeypatch.setattr(grants.os, "open", swapped_open)
    _refused((_request(work, "writable-directory"),), reason="object_changed")
    assert swapped
    assert all(_fd_closed(fd) for fd in opened)


def test_maximum_path_depth_is_supported_and_distinct_node_budget_is_bounded(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    path = root
    for _ in range(64 - len(root.parts[1:])):
        path /= "d"
        path.mkdir()
    with _held((_request(path, "readonly-directory"),)) as plan:
        assert plan.anchors[0].record.path == str(path)
    paths = []
    for branch in range(6):
        node = root / f"branch-{branch}"
        node.mkdir()
        for _ in range(44):
            node /= "node"
            node.mkdir()
        paths.append(node)
    opened, _ = _watch_acquisition(monkeypatch)
    _refused(tuple(_request(node, "readonly-directory") for node in paths), reason="node_count_invalid")
    assert len(opened) == 256
    assert all(_fd_closed(fd) for fd in opened)


def test_maximum_role_counts_keep_merged_cwd_and_only_leaf_pass_fds(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    reads = [_directory(root, f"read-{index}") for index in range(64)]
    writes = [_directory(root, f"write-{index}") for index in range(16)]
    requests = tuple(_request(path, "readonly-directory") for path in reads)
    requests += tuple(_request(path, "writable-directory") for path in writes)
    requests += (_request(writes[0], "cwd"),)
    opened, _ = _watch_acquisition(monkeypatch)
    with hold_producer_grants(requests) as plan:
        assert len(plan.anchors) == 80
        assert len(plan.pass_fds) == 80
        assert len(opened) > len(plan.pass_fds)
        assert set(plan.pass_fds) < set(opened)
        plan.validate()
    assert all(_fd_closed(fd) for fd in opened)


def test_forged_detached_manifest_cannot_change_digest_or_observation_scope(tmp_path):
    work = _directory(tmp_path)
    with _held((_request(work, "writable-directory"),)) as plan:
        manifest = plan.manifest
    with pytest.raises(ProducerGrantError, match="producer_grant_manifest_digest_mismatch"):
        replace(manifest, manifest_sha256="0" * 64).validate()
    wire = manifest.to_dict()
    wire["records"][0]["identity"]["inode"] += 1
    assert manifest.to_dict() != wire
    assert ProducerGrantManifest(manifest.records, manifest.manifest_sha256).to_dict()["execution_enforced"] is False


@pytest.mark.parametrize("substitution", ["inode", "symlink"])
def test_live_protected_file_replacement_never_refreshes_grant(tmp_path, monkeypatch, substitution):
    source = _file(tmp_path)
    requests = (_request(source, "protected-file", expected=True),)
    opened, _ = _watch_acquisition(monkeypatch)
    with pytest.raises(ProducerGrantError), hold_producer_grants(requests) as plan:
        original = plan.manifest
        displaced = source.with_name("original-input")
        source.rename(displaced)
        if substitution == "symlink":
            source.symlink_to(displaced)
        else:
            source.write_bytes(b"replacement input")
        assert _identity(displaced) == original.records[0].identity
        with pytest.raises(ProducerGrantError):
            plan.validate()
    assert all(_fd_closed(fd) for fd in opened)


def test_distinct_paths_naming_same_original_object_are_rejected(tmp_path, monkeypatch):
    source = _file(tmp_path)
    alias = source.with_name("other-name")
    os.link(source, alias)
    original = _identity(source)
    opened, _ = _watch_acquisition(monkeypatch)
    _refused((ProducerGrantRequest(str(source), "protected-file", original),
              ProducerGrantRequest(str(alias), "protected-file", original)), reason="object_alias")
    assert all(_fd_closed(fd) for fd in opened)


def test_first_post_open_fstat_failure_cannot_lose_new_fd_ownership(tmp_path, monkeypatch):
    work = _directory(tmp_path)
    opened, _ = _watch_acquisition(monkeypatch)
    original_fstat = os.fstat
    faulted = False

    def failed(fd):
        nonlocal faulted
        if not faulted:
            faulted = True
            raise OSError(errno.EIO, "inert initial identity fault")
        return original_fstat(fd)

    monkeypatch.setattr(grants.os, "fstat", failed)
    _refused((_request(work, "writable-directory"),), reason="object_unavailable")
    assert faulted and opened
    assert all(_fd_closed(fd) for fd in opened)


@pytest.mark.parametrize("body_error", [False, True])
def test_close_failure_keeps_original_body_error_and_finishes_other_cleanup(tmp_path, monkeypatch, body_error):
    work = _directory(tmp_path)
    opened, _ = _watch_acquisition(monkeypatch)
    original_close = os.close
    sentinel = RuntimeError("inert body exception")
    faulted = False

    def failed(fd):
        nonlocal faulted
        original_close(fd)
        if not faulted:
            faulted = True
            raise OSError(errno.EIO, "inert close acknowledgment fault")

    monkeypatch.setattr(grants.os, "close", failed)
    error_type = RuntimeError if body_error else ProducerGrantError
    with pytest.raises(error_type) as error, _held((_request(work, "writable-directory"),)):
        if body_error:
            raise sentinel
    if body_error:
        assert error.value is sentinel
    else:
        assert error.value.code == "producer_grant_fd_close_failed"
    assert faulted and all(_fd_closed(fd) for fd in opened)
