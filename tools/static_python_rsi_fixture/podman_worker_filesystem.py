"""Finite pre-start closure of an original worker's non-input data namespace.

The caller supplies only the original already-verified OCI kernel mount rows and
metadata pins. Kernel trees and the three separately verified input roles remain
explicit exclusions. This bounded FD walk is not continuous input protection or
a proof of every driver read, inherited descriptor, or descendant lifetime.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
from collections.abc import Callable

from tools.static_python_rsi_fixture.execution_backend import MAX_OUTPUT_BYTES, _path

_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")
_MAX_ENTRIES = 8192
_KERNEL = {
    "/proc": "proc", "/dev": "tmpfs", "/sys": "sysfs", "/dev/pts": "devpts",
    "/dev/mqueue": "mqueue", "/sys/fs/cgroup": "cgroup", "/dev/shm": "tmpfs",
}
_METADATA_ROLES = {
    "/etc/resolv.conf": "fixed empty resolver data",
    "/etc/passwd": "fixed account data", "/etc/group": "fixed account data",
    "/run/.containerenv": "trusted runtime-generated container metadata",
}
# The source-owned image producer emits these exact bytes; no worker read is
# permitted to supply a replacement expected digest.
_FIXED_FILES = {
    "/etc/hosts": b"", "/etc/hostname": b"", "/etc/resolv.conf": b"",
    "/etc/passwd": b"root:x:0:0:root:/tmp/home:/nonexistent\n",
    "/etc/group": b"root:x:0:\n",
}


class _WorkerFilesystemError(ValueError):
    code = "podman_worker_filesystem"


def _refuse() -> None:
    raise _WorkerFilesystemError("podman_worker_filesystem")


def _identity(info: os.stat_result) -> tuple:
    return tuple(getattr(info, name) for name in (
        "st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_nlink", "st_size",
        "st_mtime_ns", "st_ctime_ns",
    ))


def _tree(outputs: object, runtime_metadata: object, kernel_mounts: object,
          checkpoint: Callable[[], None]) -> dict:
    """Build a fixed vocabulary before touching the borrowed original root."""
    if (type(outputs) is not list or len(outputs) > 1024
            or type(runtime_metadata) is not list or len(runtime_metadata) > 4
            or type(kernel_mounts) is not list or len(kernel_mounts) > len(_KERNEL)):
        _refuse()
    targets = set()
    for row in outputs:
        checkpoint()
        if (type(row) is not dict or set(row) != {"path", "max_size", "executable"}
                or type(row["max_size"]) is not int or not 0 < row["max_size"] <= MAX_OUTPUT_BYTES
                or type(row["executable"]) is not bool):
            _refuse()
        path = _path(row["path"])
        if path in targets:
            _refuse()
        targets.add(path)
    for path in targets:
        checkpoint()
        parts = path.split("/")
        if any("/".join(parts[:end]) in targets for end in range(1, len(parts))):
            _refuse()

    metadata = {}
    for row in runtime_metadata:
        checkpoint()
        if (type(row) is not dict or set(row) != {"path", "size", "sha256", "role"}
                or type(row["path"]) is not str or row["path"] not in _METADATA_ROLES
                or row["role"] != _METADATA_ROLES[row["path"]]
                or type(row["size"]) is not int or not 0 <= row["size"] <= 16384
                or type(row["sha256"]) is not str or _DIGEST.fullmatch(row["sha256"]) is None
                or row["path"] in metadata):
            _refuse()
        if row["path"] in _FIXED_FILES:
            raw = _FIXED_FILES[row["path"]]
            if row["size"] != len(raw) or row["sha256"] != hashlib.sha256(raw).hexdigest():
                _refuse()
        metadata[row["path"]] = row

    kernels = set()
    for row in kernel_mounts:
        checkpoint()
        if (type(row) is not dict or set(row) != {"destination", "type"}
                or type(row["destination"]) is not str or row["destination"] not in _KERNEL
                or row["type"] != _KERNEL[row["destination"]]
                or row["destination"] in kernels):
            _refuse()
        kernels.add(row["destination"])
    if "/sys/fs/cgroup" in kernels and "/sys" not in kernels:
        _refuse()

    # Nodes are (kind, child vocabulary or file pin, exact mode or None).
    tree = {name: ("opaque", None, None) for name in ("source", "toolchain", "work")}
    tree.update({name: ("directory", {}, 0o755) for name in ("etc", "run", "proc", "dev")})
    # The fixed image producer includes these empty directories. An engine may
    # copy them into /tmp's fresh tmpfs or leave that mount completely empty.
    tree["tmp"] = ("directory", {
        name: ("optional-directory", {}, 0o755) for name in ("home", "zig-global", "zig-local")
    }, 0o700)
    tree["out"] = ("directory", {}, None)
    entries = len(tree) + len(tree["tmp"][1])

    def directory(parts: list[str], *, mode: int | None = 0o755) -> dict | None:
        nonlocal entries
        node = tree
        for index, part in enumerate(parts):
            checkpoint()
            if part not in node:
                entries += 1
                if entries > _MAX_ENTRIES:
                    _refuse()
                node[part] = ("directory", {}, mode)
            kind, children, _expected_mode = node[part]
            if kind == "opaque":
                return None
            if kind != "directory":
                _refuse()
            if index == len(parts) - 1:
                return node
            node = children
        _refuse()

    for destination in sorted(kernels, key=lambda value: (value.count("/"), value)):
        parts = destination.removeprefix("/").split("/")
        parent = directory(parts)
        if parent is not None:
            parent[parts[-1]] = ("opaque", None, None)

    for path, raw in _FIXED_FILES.items():
        checkpoint()
        override = metadata.get(path)
        tree["etc"][1][path.rsplit("/", 1)[1]] = (
            "file", {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()},
            None if override is not None else 0o444,
        )
        entries += 1
    if "/proc" in kernels:
        # Some supported engines install this fixed kernel route themselves.
        # Its absence remains valid; no discovered target supplies authority.
        tree["etc"][1]["mtab"] = ("optional-runtime-link", "/proc/mounts", 0o777)
        entries += 1
    if "/run/.containerenv" in metadata:
        row = metadata["/run/.containerenv"]
        tree["run"][1][".containerenv"] = ("file", {"size": row["size"], "sha256": row["sha256"]}, None)
        entries += 1
    for path in sorted(targets):
        node = tree["out"][1]
        for part in path.split("/")[:-1]:
            checkpoint()
            if part not in node:
                entries += 1
                if entries > _MAX_ENTRIES:
                    _refuse()
                node[part] = ("directory", {}, 0o700)
            node = node[part][1]
    return tree


def verify_worker_filesystem(root_fd: int, *, outputs: list[dict], runtime_metadata: list[dict],
                             kernel_mounts: list[dict], checkpoint: Callable[[], None]) -> None:
    """Refuse unknown data routes in the initialized original worker's view.

    The caller owns the original root FD and the verified OCI selection. This
    function owns only its nested no-follow descriptors and returns no authority
    or receipt. Input-role contents remain the existing complete inventory walk's
    responsibility. Declared kernel subtrees are deliberately not inspected.
    """
    if type(root_fd) is not int or root_fd < 0 or not callable(checkpoint):
        _refuse()
    checkpoint()
    expected = _tree(outputs, runtime_metadata, kernel_mounts, checkpoint)
    entries = 0

    def read_file(descriptor: int, pin: dict, original: os.stat_result) -> None:
        if original.st_size != pin["size"] or original.st_nlink != 1:
            _refuse()
        digest, count = hashlib.sha256(), 0
        while True:
            checkpoint()
            block = os.read(descriptor, min(65536, pin["size"] + 1 - count))
            checkpoint()
            if not block:
                break
            count += len(block)
            if count > pin["size"]:
                _refuse()
            digest.update(block)
        if count != pin["size"] or digest.hexdigest() != pin["sha256"]:
            _refuse()

    def read_runtime_link(descriptor: int, name: str, target: str,
                          named: os.stat_result, mode: int) -> None:
        # O_PATH must be checked only for this Linux-specific optional node.
        # Platforms without it can still collect and inspect link-free trees.
        path_flag = getattr(os, "O_PATH", None)
        if (type(path_flag) is not int or path_flag <= 0
                or not stat.S_ISLNK(named.st_mode) or stat.S_IMODE(named.st_mode) != mode
                or named.st_nlink != 1 or named.st_size != len(target.encode("ascii"))):
            _refuse()
        flags = path_flag | os.O_NOFOLLOW | os.O_CLOEXEC
        child = os.open(name, flags, dir_fd=descriptor)
        try:
            checkpoint()
            original = os.fstat(child)
            if _identity(original) != _identity(named):
                _refuse()
            # Empty-path readlinkat reads the held symlink itself. It never
            # traverses /proc or opens the target through the client namespace.
            if os.readlink("", dir_fd=child) != target:
                _refuse()
            checkpoint()
            if (_identity(os.fstat(child)) != _identity(original)
                    or _identity(os.stat(name, dir_fd=descriptor, follow_symlinks=False)) != _identity(original)
                    or os.readlink(name, dir_fd=descriptor) != target):
                _refuse()
            checkpoint()
            reopened = os.open(name, flags, dir_fd=descriptor)
            try:
                if (_identity(os.fstat(reopened)) != _identity(original)
                        or os.readlink("", dir_fd=reopened) != target
                        or _identity(os.fstat(child)) != _identity(original)
                        or _identity(os.stat(name, dir_fd=descriptor, follow_symlinks=False)) != _identity(original)):
                    _refuse()
            finally:
                os.close(reopened)
        finally:
            os.close(child)

    def walk(descriptor: int, vocabulary: dict) -> None:
        nonlocal entries
        checkpoint()
        before = os.fstat(descriptor)
        if not stat.S_ISDIR(before.st_mode):
            _refuse()
        names = set()
        with os.scandir(descriptor) as iterator:
            for entry in iterator:
                checkpoint()
                entries += 1
                if entries > _MAX_ENTRIES or entry.name in names or entry.name not in vocabulary:
                    _refuse()
                names.add(entry.name)
        required = {name for name, node in vocabulary.items()
                    if node[0] not in {"optional-runtime-link", "optional-directory"}}
        if not required <= names:
            _refuse()
        for name in sorted(names):
            checkpoint()
            kind, value, mode = vocabulary[name]
            named = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if kind == "optional-runtime-link":
                read_runtime_link(descriptor, name, value, named, mode)
                continue
            directory = kind != "file"
            if (not (stat.S_ISDIR(named.st_mode) if directory else stat.S_ISREG(named.st_mode))
                    or mode is not None and stat.S_IMODE(named.st_mode) != mode
                    or not directory and (named.st_nlink != 1 or named.st_mode & 0o7111)):
                _refuse()
            child = os.open(name, _DIRECTORY if directory else _FILE, dir_fd=descriptor)
            try:
                original = os.fstat(child)
                if _identity(original) != _identity(named):
                    _refuse()
                if kind in {"directory", "optional-directory"}:
                    walk(child, value)
                elif kind == "file":
                    read_file(child, value, original)
                if _identity(os.fstat(child)) != _identity(original):
                    _refuse()
                reopened = os.open(name, _DIRECTORY if directory else _FILE, dir_fd=descriptor)
                try:
                    if _identity(os.fstat(reopened)) != _identity(original):
                        _refuse()
                finally:
                    os.close(reopened)
            finally:
                os.close(child)
        if _identity(os.fstat(descriptor)) != _identity(before):
            _refuse()

    walk(root_fd, expected)
    checkpoint()
