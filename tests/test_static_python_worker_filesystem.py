"""Actual bounded FD data walks with explicitly doubled OCI mount selection.

Kernel directories here are ordinary temporary directories. Passing their fixed
selection exercises the helper's exclusion grammar, not real mount acquisition,
immutable inputs, original execution or runtime acceptance.
"""

from __future__ import annotations

import copy
import errno
import hashlib
import os
import stat
import sys
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


@pytest.fixture
def proc_mtab_guest(tmp_path):
    """Require real Linux held-symlink FD semantics, never a doubled O_PATH."""
    path_flag = getattr(os, "O_PATH", None)
    if sys.platform != "linux" or type(path_flag) is not int or path_flag <= 0:
        pytest.skip("actual Linux O_PATH symlink descriptors unavailable")
    root = tmp_path / "proc-mtab-worker"
    options = populate_guest(root, kernel_mounts=[{"destination": "/proc", "type": "proc"}])
    path = root / "etc/mtab"
    path.symlink_to("/proc/mounts")
    descriptor = None
    try:
        descriptor = os.open(path, path_flag | os.O_NOFOLLOW | os.O_CLOEXEC)
        assert stat.S_ISLNK(os.fstat(descriptor).st_mode)
        assert os.readlink("", dir_fd=descriptor) == "/proc/mounts"
    except OSError as error:
        if error.errno not in {errno.ENOSYS, errno.EINVAL, errno.ENOTSUP}:
            raise
        pytest.skip(f"kernel held-symlink readlink unavailable: errno {error.errno}")
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return root, options


def test_optional_runtime_mtab_holds_original_link_without_opening_target(proc_mtab_guest, monkeypatch):
    root, options = proc_mtab_guest
    real_open, real_close, real_read, real_readlink = os.open, os.close, os.read, os.readlink
    active, link_flags, link_reads = set(), [], []

    def open_file(name, flags, *args, **kwargs):
        descriptor = real_open(name, flags, *args, **kwargs)
        active.add(descriptor)
        if name == "mtab":
            link_flags.append(flags)
            assert stat.S_ISLNK(os.fstat(descriptor).st_mode)
            assert not os.get_inheritable(descriptor)
        return descriptor

    def close_file(descriptor):
        active.discard(descriptor)
        return real_close(descriptor)

    def read_file(descriptor, count):
        assert not stat.S_ISLNK(os.fstat(descriptor).st_mode)
        return real_read(descriptor, count)

    def readlink(name, **kwargs):
        link_reads.append(name)
        return real_readlink(name, **kwargs)

    with held_root(root) as descriptor:
        monkeypatch.setattr(filesystem.os, "open", open_file)
        monkeypatch.setattr(filesystem.os, "close", close_file)
        monkeypatch.setattr(filesystem.os, "read", read_file)
        monkeypatch.setattr(filesystem.os, "readlink", readlink)
        filesystem.verify_worker_filesystem(descriptor, **options, checkpoint=lambda: None)
        os.fstat(descriptor)
        assert active == set()
    assert len(link_flags) == 2
    assert all(flags & os.O_PATH and flags & os.O_NOFOLLOW and flags & os.O_CLOEXEC for flags in link_flags)
    assert link_reads == ["", "mtab", ""]


def test_selected_proc_still_allows_absent_runtime_mtab(proc_mtab_guest):
    root, options = proc_mtab_guest
    (root / "etc/mtab").unlink()
    verify(root, options)


@pytest.mark.parametrize("missing", ["etc/hosts", "etc/passwd"])
def test_optional_runtime_link_never_makes_fixed_metadata_optional(proc_mtab_guest, missing):
    root, options = proc_mtab_guest
    (root / missing).unlink()
    with pytest.raises(_REFUSALS):
        verify(root, options)


@pytest.mark.parametrize("kernels", [[], [{"destination": "/dev", "type": "tmpfs"}]],
                         ids=["unselected-proc", "other-kernel-only"])
def test_runtime_mtab_requires_original_proc_mount_selection(guest, kernels):
    root, options = guest
    options["kernel_mounts"] = kernels
    (root / "etc/mtab").symlink_to("/proc/mounts")
    with pytest.raises(_REFUSALS):
        verify(root, options)


@pytest.mark.parametrize("target", ["/proc/mountz", "/proc/self/mounts", "proc/mounts", "../proc/mounts",
                                   "/proc/../etc/passwd", "/proc/mounts/", "/proc/mount\n",
                                   "/proc/mounts" + "x" * 128],
                         ids=["same-size-wrong-target", "other-proc-file", "relative", "escape", "unnormalized",
                              "trailing-slash", "control-byte", "over-bound"])
def test_runtime_mtab_never_accepts_another_target(proc_mtab_guest, target):
    root, options = proc_mtab_guest
    path = root / "etc/mtab"
    path.unlink()
    path.symlink_to(target)
    with pytest.raises(_REFUSALS):
        verify(root, options)


@pytest.mark.parametrize("name", ["etc/another-mtab", "run/mtab", "tmp/mtab", "out/mtab"])
def test_fixed_runtime_link_never_approves_extra_symlinks(proc_mtab_guest, name):
    root, options = proc_mtab_guest
    (root / name).symlink_to("/proc/mounts")
    with pytest.raises(_REFUSALS):
        verify(root, options)


@pytest.mark.parametrize("kind", ["regular-file", "directory"])
def test_runtime_mtab_must_be_a_symlink(proc_mtab_guest, kind):
    root, options = proc_mtab_guest
    path = root / "etc/mtab"
    path.unlink()
    path.mkdir() if kind == "directory" else path.write_bytes(b"/proc/mounts")
    with pytest.raises(_REFUSALS):
        verify(root, options)


def test_hardlinked_runtime_symlink_refuses_even_with_exact_target(proc_mtab_guest):
    root, options = proc_mtab_guest
    path = root / "etc/mtab"
    os.link(path, root.parent / "second-link-name", follow_symlinks=False)
    assert path.lstat().st_nlink == 2
    with pytest.raises(_REFUSALS):
        verify(root, options)


def test_runtime_link_mode_guard_refuses_a_nonfixed_named_observation(proc_mtab_guest, monkeypatch):
    root, options = proc_mtab_guest
    real_stat = os.stat

    def named_stat(name, *args, **kwargs):
        observed = real_stat(name, *args, **kwargs)
        if name == "mtab" and kwargs.get("follow_symlinks") is False:
            # Linux links have immutable 0777 permissions. This isolated
            # observation fault checks refusal, not another accepted mode.
            fields = list(observed)
            fields[stat.ST_MODE] = stat.S_IFLNK | 0o700
            return os.stat_result(fields)
        return observed

    monkeypatch.setattr(filesystem.os, "stat", named_stat)
    with pytest.raises(_REFUSALS):
        verify(root, options)


@pytest.mark.parametrize("capability", [None, 0, True], ids=["missing", "zero", "bool"])
def test_present_runtime_link_refuses_without_actual_path_fd_capability(guest, monkeypatch, capability):
    root, options = guest
    options["kernel_mounts"] = [{"destination": "/proc", "type": "proc"}]
    (root / "etc/mtab").symlink_to("/proc/mounts")
    if capability is None:
        monkeypatch.delattr(filesystem.os, "O_PATH", raising=False)
    else:
        monkeypatch.setattr(filesystem.os, "O_PATH", capability, raising=False)
    monkeypatch.setattr(filesystem.os, "readlink", lambda *_args, **_kwargs: pytest.fail("read unheld link"))
    with pytest.raises(_REFUSALS):
        verify(root, options)


def test_runtime_link_replacement_between_named_stat_and_first_open_refuses(proc_mtab_guest, monkeypatch):
    root, options = proc_mtab_guest
    path, real_open, replaced = root / "etc/mtab", os.open, False

    def open_file(name, *args, **kwargs):
        nonlocal replaced
        if name == "mtab" and not replaced:
            replaced = True
            path.rename(root.parent / "old-runtime-link")
            path.symlink_to("/proc/mounts")
        return real_open(name, *args, **kwargs)

    monkeypatch.setattr(filesystem.os, "open", open_file)
    with pytest.raises(_REFUSALS):
        verify(root, options)
    assert replaced


@pytest.mark.parametrize("change", ["replace-name", "held-metadata"])
def test_runtime_link_name_and_held_identity_drift_refuse_and_close_fds(proc_mtab_guest, monkeypatch, change):
    root, options = proc_mtab_guest
    path = root / "etc/mtab"
    real_open, real_close, real_readlink = os.open, os.close, os.readlink
    active, changed = set(), False

    def open_file(*args, **kwargs):
        descriptor = real_open(*args, **kwargs)
        active.add(descriptor)
        return descriptor

    def close_file(descriptor):
        active.discard(descriptor)
        return real_close(descriptor)

    def readlink(name, **kwargs):
        nonlocal changed
        result = real_readlink(name, **kwargs)
        if name == "" and not changed:
            changed = True
            if change == "replace-name":
                path.rename(root.parent / "retained-held-link")
                path.symlink_to("/proc/mounts")
            else:
                before = path.lstat()
                os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000), follow_symlinks=False)
        return result

    with held_root(root) as descriptor:
        monkeypatch.setattr(filesystem.os, "open", open_file)
        monkeypatch.setattr(filesystem.os, "close", close_file)
        monkeypatch.setattr(filesystem.os, "readlink", readlink)
        with pytest.raises(_REFUSALS):
            filesystem.verify_worker_filesystem(descriptor, **options, checkpoint=lambda: None)
        os.fstat(descriptor)
        assert changed and active == set()


def test_runtime_link_replacement_at_second_nofollow_open_refuses(proc_mtab_guest, monkeypatch):
    root, options = proc_mtab_guest
    path, real_open, count = root / "etc/mtab", os.open, 0

    def open_file(name, *args, **kwargs):
        nonlocal count
        if name == "mtab":
            count += 1
            if count == 2:
                path.rename(root.parent / "retained-original-link")
                path.symlink_to("/proc/mounts")
        return real_open(name, *args, **kwargs)

    monkeypatch.setattr(filesystem.os, "open", open_file)
    with pytest.raises(_REFUSALS):
        verify(root, options)
    assert count == 2


@pytest.mark.parametrize("signal", [RuntimeError("original link deadline"), KeyboardInterrupt()])
def test_runtime_link_control_exceptions_close_held_fds_without_retry(proc_mtab_guest, monkeypatch, signal):
    root, options = proc_mtab_guest
    real_open, real_close = os.open, os.close
    active, armed, checkpoints = set(), False, 0

    def open_file(name, *args, **kwargs):
        nonlocal armed
        descriptor = real_open(name, *args, **kwargs)
        active.add(descriptor)
        if name == "mtab":
            armed = True
        return descriptor

    def close_file(descriptor):
        active.discard(descriptor)
        return real_close(descriptor)

    def checkpoint():
        nonlocal checkpoints
        if armed:
            checkpoints += 1
            raise signal

    with held_root(root) as descriptor:
        monkeypatch.setattr(filesystem.os, "open", open_file)
        monkeypatch.setattr(filesystem.os, "close", close_file)
        with pytest.raises(type(signal)) as failure:
            filesystem.verify_worker_filesystem(descriptor, **options, checkpoint=checkpoint)
        os.fstat(descriptor)
        assert failure.value is signal and checkpoints == 1 and active == set()


@pytest.mark.parametrize("names", [(), ("home",), ("zig-global",), ("zig-local",),
                                  ("home", "zig-global"), ("home", "zig-local"),
                                  ("zig-global", "zig-local"), ("home", "zig-global", "zig-local")],
                         ids=["empty", "home", "global", "local", "home-global",
                              "home-local", "global-local", "all-three"])
def test_fixed_empty_temporary_directories_allow_every_optional_subset(guest, names):
    root, options = guest
    for name in names:
        (root / "tmp" / name).mkdir(mode=0o755)
    verify(root, options)
    assert (root / "tmp").stat().st_mode & 0o7777 == 0o700


@pytest.mark.parametrize("name", ["home", "zig-global", "zig-local"])
@pytest.mark.parametrize("change", ["nonempty-file", "nonempty-directory", "regular-file",
                                   "symlink", "wrong-mode", "hardlinked-file"])
def test_fixed_temporary_directories_refuse_nonempty_or_changed_nodes(guest, name, change):
    root, options = guest
    path = root / "tmp" / name
    if change == "regular-file":
        path.write_bytes(b"unapproved temporary data")
    elif change == "symlink":
        path.symlink_to(root / "etc")
    elif change == "hardlinked-file":
        original = root.parent / "independently-held-data"
        original.write_bytes(b"unapproved temporary data")
        os.link(original, path)
        assert path.stat().st_nlink == 2
    else:
        path.mkdir(mode=0o755)
        if change == "nonempty-file":
            (path / "unapproved").write_bytes(b"unapproved temporary data")
        elif change == "nonempty-directory":
            (path / "unapproved").mkdir()
        else:
            path.chmod(0o700)
    with pytest.raises(_REFUSALS):
        verify(root, options)


def test_optional_temporary_directories_never_make_other_required_nodes_optional(guest):
    root, options = guest
    for name in ("home", "zig-global", "zig-local"):
        (root / "tmp" / name).mkdir(mode=0o755)
    (root / "etc/hosts").unlink()
    with pytest.raises(_REFUSALS):
        verify(root, options)


def test_optional_directory_replacement_at_original_reopen_refuses(guest, monkeypatch):
    root, options = guest
    path, real_open, count = root / "tmp/home", os.open, 0
    path.mkdir(mode=0o755)

    def open_file(name, *args, **kwargs):
        nonlocal count
        if name == "home":
            count += 1
            if count == 2:
                path.rename(root.parent / "retained-original-home")
                path.mkdir(mode=0o755)
        return real_open(name, *args, **kwargs)

    monkeypatch.setattr(filesystem.os, "open", open_file)
    with pytest.raises(_REFUSALS):
        verify(root, options)
    assert count == 2


@pytest.mark.parametrize("signal", [RuntimeError("original temporary directory deadline"), KeyboardInterrupt()])
def test_optional_directory_control_exceptions_close_original_fds_without_retry(guest, monkeypatch, signal):
    root, options = guest
    (root / "tmp/home").mkdir(mode=0o755)
    real_open, real_close = os.open, os.close
    active, armed, checkpoints = set(), False, 0

    def open_file(name, *args, **kwargs):
        nonlocal armed
        descriptor = real_open(name, *args, **kwargs)
        active.add(descriptor)
        if name == "home":
            armed = True
        return descriptor

    def close_file(descriptor):
        active.discard(descriptor)
        return real_close(descriptor)

    def checkpoint():
        nonlocal checkpoints
        if armed:
            checkpoints += 1
            raise signal

    with held_root(root) as descriptor:
        monkeypatch.setattr(filesystem.os, "open", open_file)
        monkeypatch.setattr(filesystem.os, "close", close_file)
        with pytest.raises(type(signal)) as failure:
            filesystem.verify_worker_filesystem(descriptor, **options, checkpoint=checkpoint)
        os.fstat(descriptor)
        assert failure.value is signal and checkpoints == 1 and active == set()


def test_worker_filesystem_refusal_retains_constant_value_error_diagnostic():
    with pytest.raises(ValueError) as failure:
        filesystem._refuse()
    assert type(failure.value) is filesystem._WorkerFilesystemError
    assert failure.value.code == str(failure.value) == "podman_worker_filesystem"
    assert failure.value.args == ("podman_worker_filesystem",)
