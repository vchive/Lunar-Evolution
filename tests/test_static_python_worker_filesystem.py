"""Actual bounded FD data walks with explicitly doubled OCI mount selection.

Kernel directories here are ordinary temporary directories. Passing their fixed
selection exercises the helper's exclusion grammar, not real mount acquisition,
immutable inputs, original execution or runtime acceptance.
"""

from __future__ import annotations

import copy
import hashlib
import os
from contextlib import contextmanager

import pytest

from tools.static_python_rsi_fixture import podman_worker_filesystem as filesystem
from tools.static_python_rsi_fixture.execution_backend import BuildExecutionError

_CONTAINER_RAW = b"trusted original container metadata\n"
_FIXED = {
    "etc/hosts": b"", "etc/hostname": b"", "etc/resolv.conf": b"",
    "etc/passwd": b"root:x:0:0:root:/tmp/home:/nonexistent\n", "etc/group": b"root:x:0:\n",
}
_REFUSALS = (ValueError, OSError, BuildExecutionError)


def output(path):
    return {"path": path, "max_size": 4096, "executable": False}


def metadata(path, raw):
    roles = {"/etc/resolv.conf": "fixed empty resolver data", "/etc/passwd": "fixed account data",
             "/etc/group": "fixed account data", "/run/.containerenv": "trusted runtime-generated container metadata"}
    return {"path": path, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "role": roles[path]}


def populate_guest(root, outputs=None, kernel_mounts=None, runtime_metadata=None):
    """Populate a synthetic guest without changing existing input-role contents.

    Return the three helper keyword arguments. A supplied containerenv pin must
    describe this fixture's fixed _CONTAINER_RAW; arbitrary data is never learned
    from the tree. Root integration tests can use the defaults and add their own
    separately bound metadata explicitly.
    """
    outputs = copy.deepcopy([] if outputs is None else outputs)
    kernel_mounts = copy.deepcopy([] if kernel_mounts is None else kernel_mounts)
    runtime_metadata = copy.deepcopy([] if runtime_metadata is None else runtime_metadata)
    root.mkdir(exist_ok=True)
    for name in ("source", "toolchain", "work", "out", "etc", "run", "proc", "dev"):
        (root / name).mkdir(mode=0o755, exist_ok=True)
    for name in ("etc", "run", "proc", "dev"):
        (root / name).chmod(0o755)
    (root / "tmp").mkdir(mode=0o700, exist_ok=True)
    (root / "tmp").chmod(0o700)
    selected = {row["path"] for row in runtime_metadata}
    for name, raw in _FIXED.items():
        path = root / name
        if path.exists():
            assert path.read_bytes() == raw
        else:
            path.write_bytes(raw)
        path.chmod(0o644 if "/" + name in selected else 0o444)
    if "/run/.containerenv" in selected:
        assert next(row for row in runtime_metadata if row["path"] == "/run/.containerenv") == metadata(
            "/run/.containerenv", _CONTAINER_RAW)
        (root / "run/.containerenv").write_bytes(_CONTAINER_RAW)
        (root / "run/.containerenv").chmod(0o644)
    for row in kernel_mounts:
        path = root
        for part in row["destination"].removeprefix("/").split("/"):
            path = path / part
            path.mkdir(mode=0o755, exist_ok=True)
    for row in outputs:
        path = root / "out"
        for part in row["path"].split("/")[:-1]:
            path = path / part
            path.mkdir(mode=0o700, exist_ok=True)
            path.chmod(0o700)
    return {"outputs": outputs, "kernel_mounts": kernel_mounts, "runtime_metadata": runtime_metadata}


@contextmanager
def held_root(root):
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        yield fd
    finally:
        os.close(fd)


@pytest.fixture
def guest(tmp_path):
    root = tmp_path / "initialized-worker"
    options = populate_guest(root, outputs=[output("objects/unit.o"), output("dependencies/objects/unit.o.d")])
    return root, options


def verify(root, options, checkpoint=lambda: None):
    with held_root(root) as fd:
        return filesystem.verify_worker_filesystem(fd, **options, checkpoint=checkpoint)


def test_fixed_image_metadata_and_exact_precreated_output_directories_pass(guest):
    root, options = guest
    assert verify(root, options) is None
    assert not (root / "out/objects/unit.o").exists()


def test_empty_output_vocabulary_requires_empty_current_output_view(tmp_path):
    root = tmp_path / "empty-output"
    options = populate_guest(root)
    assert verify(root, options) is None
    (root / "out/unknown").mkdir()
    with pytest.raises(_REFUSALS):
        verify(root, options)


def test_every_fixed_data_file_uses_one_bounded_original_fd_stream(guest, monkeypatch):
    root, options = guest
    real_read, counts = os.read, {}

    def read(fd, count):
        raw = real_read(fd, count)
        if raw:
            inode = os.fstat(fd).st_ino
            counts[inode] = counts.get(inode, 0) + len(raw)
        return raw

    monkeypatch.setattr(filesystem.os, "read", read)
    verify(root, options)
    assert counts == {(root / name).stat().st_ino: len(raw) for name, raw in _FIXED.items() if raw}


def test_metadata_uses_original_fixed_or_independently_supplied_pins(tmp_path):
    root = tmp_path / "metadata"
    rows = [metadata("/etc/resolv.conf", b""), metadata("/etc/passwd", _FIXED["etc/passwd"]),
            metadata("/etc/group", _FIXED["etc/group"]), metadata("/run/.containerenv", _CONTAINER_RAW)]
    options = populate_guest(root, runtime_metadata=rows)
    verify(root, options)
    (root / "run/.containerenv").write_bytes(b"X" * len(_CONTAINER_RAW))
    with pytest.raises(_REFUSALS):
        verify(root, options)


def test_input_role_trees_are_left_for_the_existing_original_inventory_gate(guest):
    root, options = guest
    (root / "source/source-data").write_bytes(b"separately pinned source")
    (root / "toolchain/resource").write_bytes(b"separately pinned resource")
    (root / "work/prior").write_bytes(b"separately pinned prior")
    verify(root, options)


def test_only_declared_fixed_kernel_subtrees_are_excluded(tmp_path):
    root = tmp_path / "kernel-selection-double"
    kernels = [{"destination": path, "type": kind} for path, kind in (
        ("/proc", "proc"), ("/dev", "tmpfs"), ("/dev/pts", "devpts"),
        ("/dev/mqueue", "mqueue"), ("/dev/shm", "tmpfs"),
        ("/sys", "sysfs"), ("/sys/fs/cgroup", "cgroup"),
    )]
    options = populate_guest(root, kernel_mounts=kernels)
    for name in ("proc", "dev", "sys"):
        (root / name / "kernel-data-double").write_bytes(b"not an ordinary data-route proof")
    verify(root, options)


def test_fixed_nested_kernel_mount_does_not_exclude_its_unmounted_parent_data(tmp_path):
    root = tmp_path / "nested-kernel-double"
    options = populate_guest(root, kernel_mounts=[{"destination": "/dev/shm", "type": "tmpfs"}])
    (root / "dev/shm/kernel-data-double").write_bytes(b"excluded kernel content")
    verify(root, options)
    (root / "dev/unapproved").write_bytes(b"not a kernel boundary")
    with pytest.raises(_REFUSALS):
        verify(root, options)


@pytest.mark.parametrize("name", ["driver.cfg", "etc/clang.cfg", "etc/unknown-directory", "run/unapproved",
                                  "tmp/.cache", "out/unknown", "proc/unapproved", "dev/unapproved"])
def test_extra_data_config_directory_and_unmounted_kernel_entries_refuse(guest, name):
    root, options = guest
    (root / name).mkdir() if name.endswith("directory") else (root / name).write_bytes(b"unapproved")
    with pytest.raises(_REFUSALS):
        verify(root, options)


def test_sys_directory_requires_original_fixed_sys_mount_selection(guest):
    root, options = guest
    (root / "sys").mkdir()
    with pytest.raises(_REFUSALS):
        verify(root, options)


@pytest.mark.parametrize("name", ["source", "etc", "tmp", "out/objects", "etc/passwd"])
def test_symlinks_never_supply_role_directory_or_metadata_nodes(guest, tmp_path, name):
    root, options = guest
    path = root / name
    target = tmp_path / "substituted"
    path.rename(target)
    path.symlink_to(target)
    with pytest.raises(_REFUSALS):
        verify(root, options)


@pytest.mark.parametrize("name,mode", [("etc/passwd", 0o744), ("etc/group", 0o4444),
                                      ("etc/hosts", 0o644), ("etc", 0o700),
                                      ("tmp", 0o755), ("out/objects", 0o755)])
def test_fixed_file_and_prepared_directory_modes_refuse_drift(guest, name, mode):
    root, options = guest
    (root / name).chmod(mode)
    with pytest.raises(_REFUSALS):
        verify(root, options)


def test_fixed_metadata_hardlink_refuses_even_with_identical_empty_bytes(guest):
    root, options = guest
    (root / "etc/hostname").unlink()
    os.link(root / "etc/hosts", root / "etc/hostname")
    with pytest.raises(_REFUSALS):
        verify(root, options)


@pytest.mark.parametrize("name,raw", [("etc/passwd", b"X" * len(_FIXED["etc/passwd"])),
                                     ("etc/hostname", b"unapproved-host"),
                                     ("etc/resolv.conf", b"unapproved-resolver")])
def test_original_metadata_bytes_and_sizes_refuse_changes(guest, name, raw):
    root, options = guest
    (root / name).chmod(0o644)
    (root / name).write_bytes(raw)
    (root / name).chmod(0o444)
    with pytest.raises(_REFUSALS):
        verify(root, options)


def test_precreated_output_targets_must_not_exist_before_dispatch(guest):
    root, options = guest
    (root / "out/objects/unit.o").write_bytes(b"not an original command output")
    with pytest.raises(_REFUSALS):
        verify(root, options)


def test_missing_expected_directory_or_metadata_refuses(guest):
    root, options = guest
    (root / "etc/hosts").unlink()
    with pytest.raises(_REFUSALS):
        verify(root, options)


@pytest.mark.parametrize("kernel_rows", [
    [{"destination": "/source", "type": "tmpfs"}],
    [{"destination": "/proc", "type": "bind"}],
    [{"destination": "/sys/fs/cgroup", "type": "cgroup"}],
    [{"destination": "/proc", "type": "proc"}] * 2,
    [{"destination": "/dev", "type": "tmpfs", "approved": True}],
], ids=["input-role", "wrong-type", "missing-sys", "duplicate", "unknown-field"])
def test_unapproved_kernel_exclusions_refuse_before_any_directory_walk(guest, monkeypatch, kernel_rows):
    root, options = guest
    options["kernel_mounts"] = kernel_rows
    monkeypatch.setattr(filesystem.os, "scandir", lambda *_: pytest.fail("walked invalid kernel selection"))
    with pytest.raises(_REFUSALS):
        verify(root, options)


@pytest.mark.parametrize("change", ["unknown-path", "wrong-role", "wrong-fixed-pin", "duplicate", "size-bool", "extra-field"])
def test_metadata_selection_cannot_approve_discovered_data(guest, monkeypatch, change):
    root, options = guest
    row = metadata("/etc/passwd", _FIXED["etc/passwd"])
    options["runtime_metadata"] = [row]
    if change == "unknown-path":
        row["path"] = "/etc/clang.cfg"
    elif change == "wrong-role":
        row["role"] = "caller approved"
    elif change == "wrong-fixed-pin":
        row["sha256"] = "a" * 64
    elif change == "duplicate":
        options["runtime_metadata"].append(row.copy())
    elif change == "size-bool":
        row["size"] = True
    else:
        row["approved"] = True
    monkeypatch.setattr(filesystem.os, "scandir", lambda *_: pytest.fail("walked invalid metadata selection"))
    with pytest.raises(_REFUSALS):
        verify(root, options)


@pytest.mark.parametrize("targets", [[output("../outside.o")], [output("a.o"), output("a.o")],
                                   [output("a.o"), output("a.o/nested.o")]])
def test_bad_duplicate_or_overlapping_output_specs_refuse_before_walk(guest, monkeypatch, targets):
    root, options = guest
    options["outputs"] = targets
    monkeypatch.setattr(filesystem.os, "scandir", lambda *_: pytest.fail("walked invalid output vocabulary"))
    with pytest.raises(_REFUSALS):
        verify(root, options)


def test_output_directory_vocabulary_retains_existing_8192_node_bound(guest, monkeypatch):
    root, options = guest
    options["outputs"] = [output("unit" + str(index) + "/" + "a/" * 100 + "unit.o") for index in range(100)]
    monkeypatch.setattr(filesystem.os, "scandir", lambda *_: pytest.fail("walked over-budget output vocabulary"))
    with pytest.raises(_REFUSALS):
        verify(root, options)


def test_same_byte_name_replacement_during_original_read_refuses_and_closes_nested_fds(guest, monkeypatch):
    root, options = guest
    path = root / "etc/passwd"
    inode = path.stat().st_ino
    real_read, real_open, real_close = os.read, os.open, os.close
    active, replaced = set(), False

    def open_file(*args, **kwargs):
        fd = real_open(*args, **kwargs)
        active.add(fd)
        return fd

    def close_file(fd):
        active.discard(fd)
        return real_close(fd)

    def read(fd, count):
        nonlocal replaced
        raw = real_read(fd, count)
        if raw and os.fstat(fd).st_ino == inode and not replaced:
            replaced = True
            path.unlink()
            path.write_bytes(_FIXED["etc/passwd"])
            path.chmod(0o444)
        return raw

    with held_root(root) as fd:
        monkeypatch.setattr(filesystem.os, "open", open_file)
        monkeypatch.setattr(filesystem.os, "close", close_file)
        monkeypatch.setattr(filesystem.os, "read", read)
        with pytest.raises(_REFUSALS):
            filesystem.verify_worker_filesystem(fd, **options, checkpoint=lambda: None)
        os.fstat(fd)
        assert replaced and active == set()


@pytest.mark.parametrize("signal", [RuntimeError("original control deadline"), KeyboardInterrupt()])
def test_original_control_exceptions_are_preserved_without_retry(guest, signal):
    root, options = guest
    checkpoints = 0

    def checkpoint():
        nonlocal checkpoints
        checkpoints += 1
        if checkpoints == 40:
            raise signal

    with pytest.raises(type(signal)) as failure:
        verify(root, options, checkpoint)
    assert failure.value is signal and checkpoints == 40
