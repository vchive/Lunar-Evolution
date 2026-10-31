"""Actual output role FDs exercise the finite original readback boundary.

No compiler, Podman, executable or runtime is started. Exact output equality
does not establish continuous protection or descendant/writer exclusion.
"""

from __future__ import annotations

import hashlib
import os
import stat
from contextlib import contextmanager

import pytest

from tools.static_python_rsi_fixture import podman_vfs_lifetime as lifetime
from tools.static_python_rsi_fixture import podman_vfs_snapshots as retained
from tools.static_python_rsi_fixture.execution_backend import MAX_OUTPUT_BYTES, BuildExecutionError
from tools.static_python_rsi_fixture.podman_worker_outputs import verify_worker_outputs

REFUSALS = (ValueError, OSError, BuildExecutionError)


def row(path, raw, *, executable=False):
    return {"path": path, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "executable": executable}


def write(root, path, raw, *, executable=False):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    target.chmod(0o500 if executable else 0o400)
    return target


@contextmanager
def held_root(root):
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        yield descriptor
    finally:
        os.close(descriptor)


@pytest.fixture
def output_tree(tmp_path):
    root = tmp_path / "original-output"
    root.mkdir()
    values = {"bin/lunar-shinka": (b"inert executable output", True),
              "link-dependencies/bin/lunar-shinka.d": (b"pinned depfile", False),
              "objects/unit.o": (b"output object is data at this boundary", False)}
    records = []
    for path, (raw, executable) in sorted(values.items()):
        write(root, path, raw, executable=executable)
        records.append(row(path, raw, executable=executable))
    return root, records


def observe(root, records, checkpoint=lambda: None):
    with held_root(root) as descriptor:
        return verify_worker_outputs(descriptor, records, checkpoint)


def test_complete_original_output_tree_reads_each_body_once_and_keeps_borrowed_fd(output_tree, monkeypatch):
    root, records = output_tree
    real_read = os.read
    read_bytes = {}

    def read(descriptor, maximum):
        block = real_read(descriptor, maximum)
        info = os.fstat(descriptor)
        if block and stat.S_ISREG(info.st_mode):
            read_bytes[info.st_ino] = read_bytes.get(info.st_ino, 0) + len(block)
        return block

    monkeypatch.setattr(lifetime.os, "read", read)
    with held_root(root) as descriptor:
        before = os.fstat(descriptor)
        summary = verify_worker_outputs(descriptor, records, lambda: None)
        after = os.fstat(descriptor)
    assert summary == {"inventory_sha256": retained._sha(retained._json(records)),
                       "file_count": 3, "directory_count": 5,
                       "total_bytes": sum(record["size"] for record in records)}
    assert read_bytes == {(root / record["path"]).stat().st_ino: record["size"] for record in records}
    assert (before.st_dev, before.st_ino) == (after.st_dev, after.st_ino)


def test_empty_output_inventory_requires_the_original_root_to_be_empty(tmp_path):
    assert observe(tmp_path, []) == {"inventory_sha256": retained._sha(retained._json([])),
                                     "file_count": 0, "directory_count": 1, "total_bytes": 0}
    (tmp_path / "unapproved-cache").mkdir()
    with pytest.raises(REFUSALS):
        observe(tmp_path, [])


@pytest.mark.parametrize("change", ["missing", "extra-file", "extra-directory", "bytes", "size",
                                    "added-execute-bit", "removed-execute-bit"])
def test_readback_refuses_incomplete_trees_and_output_pin_or_mode_changes(output_tree, change):
    root, records = output_tree
    target = root / "objects/unit.o"
    if change == "missing":
        target.unlink()
    elif change == "extra-file":
        write(root, "objects/undeclared.o", b"unapproved output")
    elif change == "extra-directory":
        (root / "objects/undeclared").mkdir()
    elif change in {"bytes", "size"}:
        original = target.read_bytes()
        target.chmod(0o600)
        target.write_bytes(b"x" * len(original) if change == "bytes" else original + b"x")
        target.chmod(0o400)
    elif change == "added-execute-bit":
        target.chmod(0o500)
    else:
        (root / "bin/lunar-shinka").chmod(0o400)
    with pytest.raises(REFUSALS):
        observe(root, records)


@pytest.mark.parametrize("change", ["leaf-symlink", "parent-symlink", "fifo", "directory-as-file",
                                    "outside-hardlink", "inside-hardlink"])
def test_readback_uses_nofollow_regular_single_link_original_objects(output_tree, tmp_path, change):
    root, records = output_tree
    target = root / "objects/unit.o"
    raw = target.read_bytes()
    if change == "parent-symlink":
        outside = tmp_path / "moved-output-directory"
        target.parent.rename(outside)
        target.parent.symlink_to(outside, target_is_directory=True)
    elif change in {"outside-hardlink", "inside-hardlink"}:
        alias = tmp_path / "outside.o" if change == "outside-hardlink" else root / "objects/alias.o"
        os.link(target, alias)
        if change == "inside-hardlink":
            records.append(row("objects/alias.o", raw))
            records.sort(key=lambda record: record["path"])
    else:
        target.unlink()
        if change == "leaf-symlink":
            outside = tmp_path / "outside.o"
            outside.write_bytes(raw)
            target.symlink_to(outside)
        elif change == "fifo":
            os.mkfifo(target)
        else:
            target.mkdir()
    with pytest.raises(REFUSALS):
        observe(root, records)


@pytest.mark.parametrize("change", ["same-bytes-file-replacement", "same-bytes-parent-replacement",
                                    "owner-write-permission", "remove-read-permission", "new-output"])
def test_original_held_and_named_output_identity_and_permissions_survive_body_read(
        output_tree, tmp_path, monkeypatch, change):
    root, records = output_tree
    target = root / "objects/unit.o"
    original_inode, original_raw = target.stat().st_ino, target.read_bytes()
    real_read = os.read
    changed = False

    def read(descriptor, maximum):
        nonlocal changed
        block = real_read(descriptor, maximum)
        if block and not changed and os.fstat(descriptor).st_ino == original_inode:
            changed = True
            if change == "same-bytes-file-replacement":
                target.unlink()
                write(root, "objects/unit.o", original_raw)
            elif change == "same-bytes-parent-replacement":
                target.parent.rename(tmp_path / "original-output-parent")
                write(root, "objects/unit.o", original_raw)
            elif change == "owner-write-permission":
                target.chmod(0o600)
            elif change == "remove-read-permission":
                target.chmod(0)
            else:
                write(root, "objects/late-output.o", b"appeared during original readback")
        return block

    monkeypatch.setattr(lifetime.os, "read", read)
    with pytest.raises(REFUSALS):
        observe(root, records)
    assert changed
    if change.startswith("same-bytes-"):
        assert target.read_bytes() == original_raw and target.stat().st_ino != original_inode


def test_output_size_limit_refuses_sparse_oversize_before_traversal_or_body_read(tmp_path, monkeypatch):
    target = tmp_path / "oversize-output"
    size = MAX_OUTPUT_BYTES + 1
    with target.open("wb") as stream:
        stream.truncate(size)
    records = [{**row(target.name, b""), "size": size}]
    monkeypatch.setattr(lifetime.os, "scandir", lambda *_args: pytest.fail("walked oversized output"))
    monkeypatch.setattr(lifetime.os, "read", lambda *_args: pytest.fail("read oversized output"))
    with pytest.raises(ValueError, match="^podman_vfs_lifetime$"):
        observe(tmp_path, records)


@pytest.mark.parametrize("change", ["duplicate", "bool-size", "integer-mode", "dotdot", "unknown-field"])
def test_invalid_copied_output_pins_refuse_before_filesystem_walk(output_tree, monkeypatch, change):
    root, original = output_tree
    records = [dict(record) for record in original]
    if change == "duplicate":
        records.append(dict(records[0]))
    elif change == "bool-size":
        records[0]["size"] = True
    elif change == "integer-mode":
        records[0]["executable"] = 1
    elif change == "dotdot":
        records[0]["path"] = "../outside"
    else:
        records[0]["accepted"] = True
    monkeypatch.setattr(lifetime.os, "scandir", lambda *_args: pytest.fail("walked invalid output pins"))
    with pytest.raises(REFUSALS):
        observe(root, records)


@pytest.mark.parametrize("moment", ["before-walk", "after-first-read"])
@pytest.mark.parametrize("error", [RuntimeError("original deadline"), KeyboardInterrupt("original cancellation")])
def test_original_control_failure_propagates_and_leaves_the_borrowed_output_fd_open(
        output_tree, monkeypatch, moment, error):
    root, records = output_tree
    real_read = os.read
    body_read = False

    def read(descriptor, maximum):
        nonlocal body_read
        block = real_read(descriptor, maximum)
        body_read |= bool(block)
        return block

    def checkpoint():
        if moment == "before-walk" or body_read:
            raise error

    monkeypatch.setattr(lifetime.os, "read", read)
    with held_root(root) as descriptor:
        before = os.fstat(descriptor)
        with pytest.raises(type(error)) as caught:
            verify_worker_outputs(descriptor, records, checkpoint)
        after = os.fstat(descriptor)
    assert caught.value is error
    assert body_read is (moment == "after-first-read")
    assert (before.st_dev, before.st_ino) == (after.st_dev, after.st_ino)


def test_closed_original_output_descriptor_is_not_replaced_by_a_host_path(output_tree):
    root, records = output_tree
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    os.close(descriptor)
    with pytest.raises(REFUSALS):
        verify_worker_outputs(descriptor, records, lambda: None)
