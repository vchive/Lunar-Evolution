"""Private opt-in custody dispatch for the original v3 execution loop.

The trusted local Podman/crun/image custodian and pinned tools are the TCB.
This is not hostile-host protection, an accepted installation or complete driver
closure. The current-output bind has per-file RLIMIT_FSIZE and bounded post-exit
validation, not an aggregate disk hard quota against hostile output production.
Every command receives a complete independently copied read-only image; only
its fresh current-output bind and ephemeral scratch are writable. Prior outputs
never enter that bind. No caller image, helper, command callback or retry exists.
"""

from __future__ import annotations

import errno
import hashlib
import io
import json
import os
import re
import stat
import struct
import sys
import tarfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tools.static_python_rsi_fixture.execution_backend import (
    MAX_INPUT_BYTES,
    MAX_LOG_BYTES,
    MAX_OUTPUT_BYTES,
    _command,
    _fail,
    _observe,
    _open_beneath,
    _prepare_v2_outputs,
)

GUEST_SOURCE_ROOT = "/source"
GUEST_TOOLCHAIN_ROOT = "/toolchain"
GUEST_PRIOR_ROOT = "/work"
GUEST_CURRENT_ROOT = "/out"
_GUEST = {"source": GUEST_SOURCE_ROOT, "toolchain": GUEST_TOOLCHAIN_ROOT,
          "work": GUEST_PRIOR_ROOT}
_ID = re.compile(r"[a-f0-9]{64}\Z")
_MAX_IMAGE_BYTES = MAX_INPUT_BYTES + 128 * 1024 * 1024
_MAX_OCI_BYTES = 1024 * 1024
MAX_CUMULATIVE_IMAGE_BYTES = 8 * 1024**3
MAX_CUSTODY_COMMANDS = 32
SNAPSHOT_BACKEND = "podman-snapshots-v1"
MAX_SNAPSHOT_COMMANDS = 512
_PASSWD = b"root:x:0:0:root:/tmp/home:/nonexistent\n"
_GROUP = b"root:x:0:\n"
# These are per-container restrictions, never a host policy modification.
_NAMESPACE_FLAGS = (0x80, 0x20000, 0x2000000, 0x4000000, 0x8000000,
                    0x10000000, 0x20000000, 0x40000000)
_SECCOMP = {
    "defaultAction": "SCMP_ACT_ALLOW",
    "architectures": ["SCMP_ARCH_X86_64"],
    "syscalls": [
        {"names": ["unshare", "setns", "mount", "umount", "umount2", "pivot_root", "chroot",
                   "fsopen", "fsconfig", "fsmount", "fspick", "open_tree", "move_mount", "mount_setattr",
                   "ptrace", "process_vm_writev", "pidfd_getfd", "init_module", "finit_module",
                   "delete_module", "kexec_load", "kexec_file_load", "bpf", "perf_event_open"],
         "action": "SCMP_ACT_ERRNO", "errnoRet": 1},
        {"names": ["clone3"], "action": "SCMP_ACT_ERRNO", "errnoRet": 38},
        *({"names": ["clone"], "action": "SCMP_ACT_ERRNO", "errnoRet": 1,
           "args": [{"index": 0, "value": bit, "valueTwo": bit, "op": "SCMP_CMP_MASKED_EQ"}]}
          for bit in _NAMESPACE_FLAGS),
    ],
}


def _guest_build_environment(environment: dict[str, str]) -> dict[str, str]:
    """Executor-owned paths are fixed to this command's pinned guest image."""
    result = dict(environment)
    result.update(PATH=GUEST_TOOLCHAIN_ROOT + "/bin", HOME="/tmp/home", TMPDIR="/tmp",
                  HOSTNAME="lunar-build", container="podman",
                  ZIG_GLOBAL_CACHE_DIR="/tmp/zig-global", ZIG_LOCAL_CACHE_DIR="/tmp/zig-local",
                  ZIG_LIB_DIR=GUEST_TOOLCHAIN_ROOT + "/lib")
    return result


def _pin(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def preflight_podman_custody() -> list[str]:
    """Select only this uid's existing local rootless service, before mutation."""
    if sys.platform != "linux" or os.uname().machine != "x86_64":
        _fail("custody_platform")
    executable = Path("/usr/bin/podman")
    try:
        info = executable.lstat()
    except OSError:
        _fail("custody_podman_installation")
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
            or info.st_mode & 0o022 or not info.st_mode & 0o111):
        _fail("custody_podman_installation")
    socket = Path(f"/run/user/{os.geteuid()}/podman/podman.sock")
    try:
        info = socket.lstat()
    except OSError:
        _fail("custody_service")
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid():
        _fail("custody_service")
    return [str(executable), "--remote", "--url", "unix://" + str(socket)]


def validate_custody_image_budget(recipe: dict) -> None:
    """Refuse full-tree replay that already exceeds this first backend's bound."""
    commands = sum(len(stage["commands"]) for stage in recipe["stages"])
    base = sum(record["size"] for rows in recipe["inputs"].values() for record in rows)
    if commands > MAX_CUSTODY_COMMANDS or commands * base > MAX_CUMULATIVE_IMAGE_BYTES:
        _fail("custody_image_attempt_budget")
    names = [role + "/" + record["path"] for role, rows in recipe["inputs"].items() for record in rows]
    names.extend("work/" + output["path"] for stage in recipe["stages"]
                 for command in stage["commands"] for output in command["outputs"])
    names.extend({"/".join(name.split("/")[:index]) for name in tuple(names)
                  for index in range(1, len(name.split("/")))})
    for name in names:
        try:
            tarfile.TarInfo(name).tobuf(format=tarfile.USTAR_FORMAT)
        except (ValueError, UnicodeError):
            _fail("custody_image_path")


def validate_snapshot_budget(recipe: dict) -> None:
    """Bound the new layout without charging N copies of the fixed toolchain."""
    commands = sum(len(stage["commands"]) for stage in recipe["stages"])
    base = sum(record["size"] for rows in recipe["inputs"].values() for record in rows)
    if not 0 < commands <= MAX_SNAPSHOT_COMMANDS or base > MAX_INPUT_BYTES:
        _fail("custody_snapshot_attempt_budget")


def _prior_snapshot(work: Path, root: Path, prior: list[dict],
                    checkpoint: Callable[[], None]) -> None:
    """Copy only verified prior outputs; never expose the live work directory."""
    root.mkdir(mode=0o700)
    for record in prior:
        checkpoint()
        try:
            observed = _observe(work, record["path"], MAX_OUTPUT_BYTES,
                                destination=root / record["path"],
                                executable=record["executable"], checkpoint=checkpoint)
            if observed != record:
                _fail("custody_prior_pin")
            (root / record["path"]).chmod(0o555 if record["executable"] else 0o444)
            if _observe(root, record["path"], MAX_OUTPUT_BYTES, checkpoint=checkpoint) != record:
                _fail("custody_prior_pin")
        except OSError as error:
            # Missing/replaced path components are the same pin refusal as
            # changed bytes. Keep resource and other I/O failures distinct.
            if error.errno not in {errno.ELOOP, errno.ENOTDIR, errno.ENOENT}:
                raise
            _fail("custody_prior_pin")


def _readonly_volumes(roots: dict[str, Path]) -> list[str]:
    if set(roots) != set(_GUEST):
        _fail("custody_snapshot_roots")
    result = []
    for role, guest in _GUEST.items():
        path = roots[role]
        if (not path.is_absolute() or path.resolve() != path or not path.is_dir()
                or any(char in str(path) for char in ":\n\r\x00")):
            _fail("custody_snapshot_roots")
        # The generated freezer and Zig must execute; all three inputs are RO.
        result.append("--volume=" + str(path) + ":" + guest + ":ro,exec,nosuid,nodev")
    return result


def expand_custody_reference(arg: str, *, current: set[str], prior: set[str]) -> str:
    """Lower exact current outputs separately; directory inputs see prior only."""
    if not arg.startswith("@"):
        return arg
    role, relative = arg[1:].split("/", 1)
    if role == "work":
        if relative in current:
            return GUEST_CURRENT_ROOT + "/" + relative
        if relative not in prior:
            _fail("custody_work_reference")
        return GUEST_PRIOR_ROOT + "/" + relative
    if role == "work-dir":
        if not any(path.startswith(relative + "/") for path in prior):
            _fail("custody_directory_reference")
        return GUEST_PRIOR_ROOT + "/" + relative
    return _GUEST[role.removesuffix("-dir")] + "/" + relative


def _read_bounded(root: Path, name: str, maximum: int, checkpoint: Callable[[], None]) -> bytes:
    fd = _open_beneath(root, name)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
            _fail("custody_control_bounds")
        blocks, count = [], 0
        while True:
            checkpoint()
            block = os.read(fd, min(65536, maximum + 1 - count))
            if not block:
                break
            blocks.append(block)
            count += len(block)
            if count > maximum:
                _fail("custody_control_bounds")
        after = os.fstat(fd)
        if (count != info.st_size
                or (info.st_dev, info.st_ino, info.st_mtime_ns, info.st_ctime_ns)
                != (after.st_dev, after.st_ino, after.st_mtime_ns, after.st_ctime_ns)):
            _fail("custody_control_drift")
        return b"".join(blocks)
    finally:
        os.close(fd)


def _static_executable(root: Path, record: dict, checkpoint: Callable[[], None]) -> None:
    """Compare actual pinned helper bytes and refuse external loader inputs.

    This is a finite ELF loader gate, not a complete driver-read observer or an
    immutable acquisition. Every later input-image operation still does its own
    original readback; a successful check grants no build/runtime authority.
    """
    checkpoint()
    fd = _open_beneath(root, record["path"])
    try:
        before = os.fstat(fd)
        identity = (before.st_dev, before.st_ino, before.st_mode, before.st_nlink,
                    before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        if (not stat.S_ISREG(before.st_mode) or record["executable"] is not True
                or not before.st_mode & 0o111 or before.st_size != record["size"]
                or not 64 <= before.st_size <= MAX_INPUT_BYTES):
            _fail("custody_static_executable")
        checkpoint()
        header = os.read(fd, 64)
        if len(header) != 64:
            _fail("custody_static_executable")
        (ident, kind, machine, version, entry_point, offset, _sections, flags,
         header_size, entry, count, _section_size, _section_count, _section_names) = struct.unpack(
            "<16sHHIQQQIHHHHHH", header)
        if (ident[:7] != b"\x7fELF\x02\x01\x01" or ident[7] not in {0, 3}
                or ident[8:] != b"\0" * 8 or kind != 2 or machine != 62 or version != 1
                or flags != 0 or header_size != 64 or not entry_point
                or entry != 56 or not 0 < count <= 1024 or offset < 64
                or offset + entry * count > record["size"]):
            _fail("custody_static_executable")
        entry_covered = False
        for index in range(count):
            checkpoint()
            row = os.pread(fd, entry, offset + index * entry)
            if len(row) != entry:
                _fail("custody_static_executable")
            segment, permissions, file_offset, address, _physical, size, memory_size, alignment = struct.unpack(
                "<IIQQQQQQ", row)
            if (segment in {2, 3} or file_offset + size > record["size"]
                    or address + memory_size > 2**64 - 1
                    or alignment not in {0, 1} and alignment & (alignment - 1)):
                _fail("custody_static_executable")
            if segment == 1:
                if (size > memory_size or permissions & ~7
                        or alignment > 1 and file_offset % alignment != address % alignment):
                    _fail("custody_static_executable")
                if permissions & 1 and address <= entry_point < address + size:
                    entry_covered = True
        if not entry_covered:
            _fail("custody_static_executable")
        # Header inspection alone must not approve different bytes with the
        # same length. Hash the same original FD and recheck the original name.
        digest, observed = hashlib.sha256(), 0
        os.lseek(fd, 0, os.SEEK_SET)
        while True:
            checkpoint()
            raw = os.read(fd, 65536)
            checkpoint()
            if not raw:
                break
            observed += len(raw)
            if observed > record["size"]:
                _fail("custody_input_pin")
            digest.update(raw)
        after = os.fstat(fd)
        if (observed != record["size"] or digest.hexdigest() != record["sha256"]
                or identity != (after.st_dev, after.st_ino, after.st_mode, after.st_nlink,
                                after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            _fail("custody_input_pin")
        repeated = _open_beneath(root, record["path"])
        try:
            after = os.fstat(repeated)
            if identity != (after.st_dev, after.st_ino, after.st_mode, after.st_nlink,
                            after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                _fail("custody_input_pin")
        finally:
            os.close(repeated)
        checkpoint()
    finally:
        os.close(fd)


def _static_helper_inputs(inputs: dict[str, list[dict]], snapshots: dict[str, Path],
                          prior: list[dict], work: Path, checkpoint: Callable[[], None]) -> None:
    """Refuse implicit helper loaders before any command's daemon operation.

    All executable files in the original finite input view matter, including
    helpers absent from the command's explicit argv and earlier generated tools.
    Nothing is cached across commands or learned from current filesystem bytes.
    """
    for role in ("source", "toolchain"):
        for record in inputs[role]:
            checkpoint()
            if record["executable"]:
                _static_executable(snapshots[role], record, checkpoint)
    for record in prior:
        checkpoint()
        if record["executable"]:
            _static_executable(work, record, checkpoint)


class _PinnedReader(io.RawIOBase):
    def __init__(self, fd: int, record: dict, checkpoint: Callable[[], None]):
        self.fd, self.record, self.checkpoint = fd, record, checkpoint
        self.before = os.fstat(fd)
        self.count, self.digest = 0, hashlib.sha256()
        if (not stat.S_ISREG(self.before.st_mode) or self.before.st_size != record["size"]
                or bool(self.before.st_mode & 0o111) is not record["executable"]):
            _fail("custody_input_pin")

    def read(self, size: int = -1) -> bytes:
        self.checkpoint()
        if size < 0 or size > 65536:
            size = 65536
        raw = os.read(self.fd, size)
        self.checkpoint()
        self.count += len(raw)
        if self.count > self.record["size"]:
            _fail("custody_input_pin")
        self.digest.update(raw)
        return raw

    def verify(self) -> None:
        self.checkpoint()
        after = os.fstat(self.fd)
        if (self.count != self.record["size"] or self.digest.hexdigest() != self.record["sha256"]
                or (self.before.st_dev, self.before.st_ino, self.before.st_size,
                    self.before.st_mtime_ns, self.before.st_ctime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            _fail("custody_input_pin")


def _image_archive(path: Path, inputs: dict[str, list[dict]], snapshots: dict[str, Path],
                   prior: list[dict], work: Path, checkpoint: Callable[[], None]) -> dict:
    groups = [(role, snapshots[role], inputs[role]) for role in ("source", "toolchain")]
    groups.append(("work", work, prior))
    if sum(record["size"] for _, _, rows in groups for record in rows) > MAX_INPUT_BYTES:
        _fail("custody_image_budget")
    directories = {"source", "toolchain", "work", "out", "tmp", "tmp/home",
                   "tmp/zig-global", "tmp/zig-local", "etc", "proc", "dev", "run"}
    for role, _, records in groups:
        for record in records:
            parts = (role + "/" + record["path"]).split("/")
            directories.update("/".join(parts[:index]) for index in range(1, len(parts)))
    with path.open("xb") as stream, tarfile.open(fileobj=stream, mode="w",
                                                format=tarfile.USTAR_FORMAT) as archive:
        for name in sorted(directories, key=lambda value: (value.count("/"), value)):
            checkpoint()
            entry = tarfile.TarInfo(name)
            entry.type, entry.mode = tarfile.DIRTYPE, 0o755
            archive.addfile(entry)
        for name, raw in (("etc/hosts", b""), ("etc/hostname", b""), ("etc/resolv.conf", b""),
                          ("etc/passwd", _PASSWD), ("etc/group", _GROUP)):
            entry = tarfile.TarInfo(name)
            entry.mode, entry.size = 0o444, len(raw)
            archive.addfile(entry, io.BytesIO(raw))
        for role, root, records in groups:
            for record in records:
                checkpoint()
                fd = _open_beneath(root, record["path"])
                try:
                    reader = _PinnedReader(fd, record, checkpoint)
                    entry = tarfile.TarInfo(role + "/" + record["path"])
                    entry.mode = 0o555 if record["executable"] else 0o444
                    entry.size = record["size"]
                    archive.addfile(entry, reader)
                    reader.verify()
                finally:
                    os.close(fd)
        stream.flush()
        os.fsync(stream.fileno())
    return _observe(path.parent, path.name, _MAX_IMAGE_BYTES, checkpoint=checkpoint)


def _scan_outputs(root: Path, outputs: list[dict], checkpoint: Callable[[], None]) -> None:
    expected = {record["path"]: record for record in outputs}
    found: set[str] = set()
    pending = [""]
    entries = 0
    while pending:
        checkpoint()
        relative = pending.pop()
        directory = root / relative
        with os.scandir(directory) as iterator:
            for entry in iterator:
                checkpoint()
                entries += 1
                if entries > 8192:
                    _fail("custody_output_budget")
                name = (relative + "/" if relative else "") + entry.name
                if entry.is_dir(follow_symlinks=False):
                    if not any(path.startswith(name + "/") for path in expected):
                        _fail("custody_undeclared_output")
                    pending.append(name)
                elif entry.is_file(follow_symlinks=False) and name in expected:
                    found.add(name)
                else:
                    _fail("custody_undeclared_output")
    if found != set(expected):
        _fail("custody_output_group")


class PodmanCustody:
    """Owned by one original runner attempt; never a public build executor."""

    def __init__(self, *, destination: Path, prefix: list[str], recipe_sha256: str,
                 checkpoint: Callable[[], None], snapshot_mounts: bool = False):
        self.destination, self.prefix = destination, prefix
        self.recipe_sha256, self.checkpoint = recipe_sha256, checkpoint
        self.image_bytes = 0
        if type(snapshot_mounts) is not bool:
            _fail("custody_snapshot_mode")
        self.snapshot_mounts = snapshot_mounts
        self.base_image: tuple[str, Path, dict] | None = None
        self.root = destination / "custody"
        self.root.mkdir()
        self.environment = {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C",
                            "HOME": str(destination / "work" / ".home")}

    def _control(self, argv: list[str], name: str, root: Path, operations: list[dict]) -> bytes:
        self.checkpoint()
        logs = root / name
        logs.mkdir()
        evidence: dict[str, Any] = {"operation": name}
        operations.append(evidence)
        _command(self.prefix + argv, work=root, environment=self.environment,
                 logs=logs, checkpoint=self.checkpoint, evidence=evidence)
        raw = _read_bounded(logs, "stdout.log", MAX_LOG_BYTES, self.checkpoint)
        if len(raw) != evidence["logs"]["stdout"]["size"] or _pin(raw) != evidence["logs"]["stdout"]["sha256"]:
            _fail("custody_control_drift")
        return raw

    def _state(self, container: str, name: str, root: Path, operations: list[dict]) -> dict:
        raw = self._control(["inspect", "--type", "container", "--format",
                             '{{json .State}}', container], name, root, operations)
        value = json.loads(raw)
        if type(value) is not dict:
            _fail("custody_state")
        return {key: value.get(key) for key in ("Status", "Running", "Pid", "ExitCode", "OOMKilled", "Error")}

    def _runtime_policy(self, container: str, image: str, executed: list[str],
                        environment: dict[str, str], current: Path, root: Path,
                        operations: list[dict], readonly: dict[str, Path] | None = None) -> dict:
        template = ('{"image":{{json .Image}},"oci":{{json .OCIConfigPath}},'
                    '"resolver":{{json .ResolvConfPath}},"hostname":{{json .HostnamePath}},'
                    '"hosts":{{json .HostsPath}}}')
        selected = json.loads(self._control(
            ["inspect", "--type", "container", "--format", template, container],
            "runtime-selection", root, operations,
        ))
        if (selected["image"].removeprefix("sha256:") != image
                or any(selected[key] for key in ("hostname", "hosts"))):
            _fail("custody_runtime_selection")
        # Podman may retain a generated ResolvConfPath in its metadata even
        # when the user mount overrides it. Only the actual OCI mount source
        # below grants access; no ambient resolver is accepted or copied.
        path = Path(selected["oci"])
        if not path.is_absolute() or path != path.absolute() or ".." in path.parts:
            _fail("custody_runtime_selection")
        raw = _read_bounded(path.parent, path.name, _MAX_OCI_BYTES, self.checkpoint)
        spec = json.loads(raw)
        process = spec["process"]
        caps = process.get("capabilities", {})
        namespaces = spec["linux"]["namespaces"]
        if (spec["root"].get("readonly") is not True or process.get("noNewPrivileges") is not True
                or type(caps) is not dict or any(value for value in caps.values())
                or process["args"] != executed or process["cwd"] != GUEST_CURRENT_ROOT
                or sorted(process["env"]) != sorted(key + "=" + value for key, value in environment.items())
                or any(not any(row.get("type") == kind and not row.get("path") for row in namespaces)
                       for kind in ("pid", "network", "ipc", "uts", "mount"))):
            _fail("custody_runtime_policy")
        seccomp = spec["linux"].get("seccomp", {})
        if (seccomp.get("defaultAction") != _SECCOMP["defaultAction"]
                or seccomp.get("architectures") != _SECCOMP["architectures"]
                or seccomp.get("syscalls") != _SECCOMP["syscalls"]):
            _fail("custody_runtime_seccomp")
        resources = spec["linux"]["resources"]
        cpu = resources["cpu"]
        if (not 0 < resources["memory"]["limit"] <= 2 * 1024**3
                or not 0 < resources["pids"]["limit"] <= 256
                or not 0 < cpu["quota"] <= 2 * cpu["period"]):
            _fail("custody_runtime_resources")
        limits = {row["type"]: row for row in process["rlimits"]}
        if any(limits.get(kind, {}).get(field) != bound
               for kind, bound in (("RLIMIT_CORE", 0), ("RLIMIT_FSIZE", MAX_OUTPUT_BYTES))
               for field in ("soft", "hard")):
            _fail("custody_runtime_resources")
        seen, metadata = set(), []
        protected = {} if readonly is None else {_GUEST[role]: str(path) for role, path in readonly.items()}
        if readonly is not None and set(readonly) != set(_GUEST):
            _fail("custody_runtime_snapshot")
        kernel = {"/proc": "proc", "/dev": "tmpfs", "/sys": "sysfs", "/dev/pts": "devpts",
                  "/dev/mqueue": "mqueue", "/sys/fs/cgroup": "cgroup"}
        for mount in spec["mounts"]:
            self.checkpoint()
            target, source, kind = mount["destination"], mount["source"], mount["type"]
            raw_options = mount.get("options", [])
            if type(raw_options) is not list or any(type(option) is not str for option in raw_options):
                _fail("custody_runtime_mount")
            keys = [option.split("=", 1)[0] for option in raw_options]
            options = set(raw_options)
            if (len(set(keys)) != len(keys)
                    or any({left, right} <= options for left, right in (
                        ("ro", "rw"), ("exec", "noexec"), ("suid", "nosuid"), ("dev", "nodev")))):
                _fail("custody_runtime_mount")
            if target in seen:
                _fail("custody_runtime_mount")
            seen.add(target)
            if target in protected:
                if (source != protected[target] or kind != "bind"
                        or not {"ro", "nosuid", "nodev"} <= options or "noexec" in options):
                    _fail("custody_runtime_snapshot")
            elif target == GUEST_CURRENT_ROOT:
                if (source != str(current) or kind != "bind"
                        or not {"rw", "noexec", "nosuid", "nodev"} <= options):
                    _fail("custody_runtime_mount")
            elif target == "/tmp":
                if kind != "tmpfs" or not {"rw", "noexec", "nosuid", "nodev", "size=268435456"} <= options:
                    _fail("custody_runtime_mount")
            elif target == "/etc/resolv.conf":
                expected = root / "fixed-resolv.conf"
                if (source != str(expected) or kind != "bind"
                        or not {"ro", "noexec", "nosuid", "nodev"} <= options
                        or _read_bounded(root, expected.name, 1, self.checkpoint) != b""):
                    _fail("custody_runtime_metadata")
                metadata.append({"path": target, "size": 0, "sha256": _pin(b""),
                                 "role": "fixed empty resolver data"})
            elif target == "/dev/shm":
                if (kind != "tmpfs"
                        or not {"ro", "noexec", "nosuid", "nodev", "size=65536"} <= options):
                    _fail("custody_runtime_metadata")
            elif target in kernel:
                # /dev's fixed rootless tmpfs uses strictatime and read-only.
                if ((kind != kernel[target] or not {"nosuid", "noexec"} <= options)
                        and (target != "/dev" or kind != "tmpfs" or not {"nosuid", "ro"} <= options)):
                    _fail("custody_runtime_mount")
                if target in {"/dev", "/sys", "/sys/fs/cgroup"} and "ro" not in options:
                    _fail("custody_runtime_mount")
            elif target in {"/run/.containerenv", "/etc/passwd", "/etc/group"}:
                original = Path(source)
                if (kind != "bind" or container not in original.parts or "userdata" not in original.parts
                        or not {"ro", "noexec", "nosuid", "nodev"} <= options):
                    _fail("custody_runtime_metadata")
                data = _read_bounded(original.parent, original.name, 16384, self.checkpoint)
                if (target in {"/etc/passwd", "/etc/group"}
                        and data != (_PASSWD if target == "/etc/passwd" else _GROUP)):
                    _fail("custody_runtime_metadata")
                metadata.append({"path": target, "size": len(data), "sha256": _pin(data),
                                 "role": "fixed account data" if target.startswith("/etc/") else
                                 "trusted runtime-generated container metadata"})
            else:
                _fail("custody_runtime_mount")
        if not {GUEST_CURRENT_ROOT, "/tmp", "/etc/resolv.conf", "/dev/shm", *protected} <= seen:
            _fail("custody_runtime_mount")
        return {"oci_sha256": _pin(raw), "root_readonly": True, "capabilities_zero": True,
                "no_new_privileges": True, "private_namespaces": True,
                "fixed_seccomp_verified": True, "runtime_metadata": metadata,
                "readonly_snapshots": protected}

    def _prepare_image(self, *, root: Path, inputs: dict[str, list[dict]],
                       snapshots: dict[str, Path], prior: list[dict], work: Path,
                       observation: dict, operations: list[dict]) -> tuple[str, dict[str, Path] | None]:
        readonly = None
        if self.snapshot_mounts:
            size = sum(record["size"] for record in prior)
            if self.image_bytes + size > MAX_CUMULATIVE_IMAGE_BYTES:
                _fail("custody_image_attempt_budget")
            _prior_snapshot(work, root / "prior", prior, self.checkpoint)
            self.image_bytes += size
            readonly = {**snapshots, "work": root / "prior"}
            _readonly_volumes(readonly)
        if self.snapshot_mounts and self.base_image is not None:
            image, archive, pin = self.base_image
            if _observe(archive.parent, archive.name, _MAX_IMAGE_BYTES, checkpoint=self.checkpoint) != pin:
                _fail("custody_image_drift")
            observation["image_archive"] = pin
            observation["base_image_reused"] = True
        else:
            archive = root / "input.tar"
            data_bytes = 0 if self.snapshot_mounts else sum(record["size"] for rows in inputs.values() for record in rows)
            data_bytes += 0 if self.snapshot_mounts else sum(record["size"] for record in prior)
            if self.image_bytes + data_bytes > MAX_CUMULATIVE_IMAGE_BYTES:
                _fail("custody_image_attempt_budget")
            pin = _image_archive(archive, {"source": [], "toolchain": []} if self.snapshot_mounts else inputs,
                                 snapshots, [] if self.snapshot_mounts else prior, work, self.checkpoint)
            self.image_bytes += pin["size"]
            if self.image_bytes > MAX_CUMULATIVE_IMAGE_BYTES:
                _fail("custody_image_attempt_budget")
            image = self._control(["import", "--arch", "amd64", "--os", "linux", str(archive)],
                                  "import", root, operations).decode("ascii").strip().removeprefix("sha256:")
            if _ID.fullmatch(image) is None:
                _fail("custody_image_identity")
            if _observe(root, "input.tar", _MAX_IMAGE_BYTES, checkpoint=self.checkpoint) != pin:
                _fail("custody_image_drift")
            observation["image_archive"] = pin
            if self.snapshot_mounts:
                self.base_image = (image, archive, pin)
                observation["base_image_reused"] = False
        observation["cumulative_image_bytes"] = self.image_bytes
        observation["image_id"] = image
        observation["input_layout"] = SNAPSHOT_BACKEND if self.snapshot_mounts else "copied-image-v1"
        return image, readonly

    def run(self, argv: list[str], *, inputs: dict[str, list[dict]], snapshots: dict[str, Path],
            prior: list[dict], outputs: list[dict], work: Path, environment: dict[str, str],
            logs: Path, evidence: dict[str, Any], stage: str, index: int) -> None:
        _static_helper_inputs(inputs, snapshots, prior, work, self.checkpoint)
        root = self.root / (stage + "-" + str(index))
        root.mkdir()
        current = root / "current"
        current.mkdir()
        _prepare_v2_outputs(current, outputs, self.checkpoint)
        current_paths = {record["path"] for record in outputs}
        prior_paths = {record["path"] for record in prior}
        if current_paths & prior_paths:
            _fail("custody_output_overlap")
        executed = [expand_custody_reference(arg, current=current_paths, prior=prior_paths) for arg in argv]
        origin_role, origin_path = argv[0][1:].split("/", 1)
        executable = next(record for record in (prior if origin_role == "work" else inputs[origin_role])
                          if record["path"] == origin_path)
        if executable["executable"] is not True:
            _fail("custody_static_executable")
        observation: dict[str, Any] = {
            "schema": "lunar-podman-build-command-observation-v1",
            "recipe_sha256": self.recipe_sha256, "stage": stage, "index": index,
            "original_argv_sha256": _pin(_json(argv)), "executed_argv": executed,
            "guest_roots": {**_GUEST, "current_output": GUEST_CURRENT_ROOT},
            "tcb": "trusted host and existing local rootless Podman/crun/image custodian",
            "original_container_exit_confirmed": False, "complete_namespace_disappearance_verified": False,
            "immutable_custody_verified": False, "driver_inputs_verified": False,
            "installation_accepted": False, "production_admission": False,
            "aggregate_output_hard_quota_verified": False, "operations": [],
        }
        evidence.update(status="partial", returncode=None, direct_child_reaped=False,
                        descendant_cleanup_verified=False, custody=observation)
        operations = observation["operations"]
        container = None
        try:
            image, readonly = self._prepare_image(root=root, inputs=inputs, snapshots=snapshots,
                prior=prior, work=work, observation=observation, operations=operations)
            target = str(current)
            if any(char in target for char in ":\n\r\x00"):
                _fail("custody_mount_path")
            guest_environment = _guest_build_environment(environment)
            observation["executed_environment"] = guest_environment
            seccomp_path = root / "seccomp.json"
            with seccomp_path.open("xb") as stream:
                stream.write(_json(_SECCOMP))
                stream.flush()
                os.fsync(stream.fileno())
            seccomp_path.chmod(0o444)
            resolver_path = root / "fixed-resolv.conf"
            with resolver_path.open("xb") as stream:
                stream.flush()
                os.fsync(stream.fileno())
            resolver_path.chmod(0o444)
            observation["seccomp_sha256"] = _pin(_json(_SECCOMP))
            create = ["create", "--pull=never", "--network=none", "--pid=private", "--ipc=private",
                      "--uts=private", "--read-only", "--read-only-tmpfs=false", "--cap-drop=ALL",
                      "--security-opt=no-new-privileges", "--security-opt=seccomp=" + str(seccomp_path),
                      "--user=0:0", "--workdir=" + GUEST_CURRENT_ROOT,
                      "--http-proxy=false", "--no-hosts", "--no-hostname", "--hostname=lunar-build",
                      "--unsetenv-all", "--systemd=false", "--sdnotify=ignore", "--no-healthcheck",
                      "--restart=no", "--pids-limit=256", "--memory=2g", "--cpus=2",
                      "--ulimit=core=0:0", "--ulimit=fsize=" + str(MAX_OUTPUT_BYTES) + ":" + str(MAX_OUTPUT_BYTES),
                      "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=268435456,mode=0700",
                      "--tmpfs=/dev/shm:ro,noexec,nosuid,nodev,size=65536,mode=1777",
                      "--volume=" + str(resolver_path) + ":/etc/resolv.conf:ro,noexec,nosuid,nodev",
                      "--volume=" + target + ":" + GUEST_CURRENT_ROOT + ":rw,noexec,nosuid,nodev",
                      "--entrypoint=" + executed[0]]
            if readonly is not None:
                create.extend(_readonly_volumes(readonly))
            create.extend("--env=" + key + "=" + value for key, value in sorted(guest_environment.items()))
            observation["container_creation_unknown"] = True
            container = self._control(create + ["sha256:" + image, *executed[1:]],
                                      "create", root, operations).decode("ascii").strip()
            if _ID.fullmatch(container) is None:
                container = None
                _fail("custody_container_identity_unknown")
            observation["container_id"] = container
            observation["container_creation_unknown"] = False
            self._control(["init", container], "init", root, operations)
            observation["runtime_policy"] = self._runtime_policy(
                container, image, executed, guest_environment, current, root, operations,
                readonly,
            )
            if _read_bounded(root, "seccomp.json", _MAX_OCI_BYTES, self.checkpoint) != _json(_SECCOMP):
                _fail("custody_runtime_seccomp")
            attach: dict[str, Any] = {}
            operations.append({"operation": "start-attach", "evidence": attach})
            _command(self.prefix + ["start", "--attach", container], work=root,
                     environment=self.environment, logs=logs, checkpoint=self.checkpoint, evidence=attach)
            evidence.update({key: attach[key] for key in ("returncode", "direct_child_reaped", "logs")})
            evidence["direct_child_role"] = "original-podman-attach-client"
            wait = self._control(["wait", "--condition=exited", container], "wait", root, operations)
            state = self._state(container, "state", root, operations)
            observation["original_container_state"] = state
            if (wait.strip() != b"0" or state["Running"] is not False or state["Pid"] != 0
                    or state["ExitCode"] != 0 or state["OOMKilled"] is not False):
                _fail("custody_original_exit")
            observation["original_container_exit_confirmed"] = True
            _scan_outputs(current, outputs, self.checkpoint)
            copied = []
            for output in outputs:
                self.checkpoint()
                observed = _observe(current, output["path"], output["max_size"],
                                    destination=work / output["path"], executable=output["executable"],
                                    checkpoint=self.checkpoint)
                (work / output["path"]).chmod(0o555 if output["executable"] else 0o444)
                if _observe(work, output["path"], output["max_size"], checkpoint=self.checkpoint) != observed:
                    _fail("custody_output_readback")
                copied.append(observed)
            observation["readback_outputs"] = copied
            evidence["status"] = "complete"
        except BaseException as error:
            observation["first_failure"] = getattr(error, "code", type(error).__name__)
            # No replacement attempt and no extra cleanup deadline. If the
            # original budget is exhausted, this may correctly remain unknown.
            if container is not None and observation["original_container_exit_confirmed"] is not True:
                try:
                    self._control(["stop", "--time=0", container], "failure-stop", root, operations)
                    state = self._state(container, "failure-state", root, operations)
                    observation["failure_original_container_state"] = state
                    observation["original_container_exit_confirmed"] = (
                        state["Running"] is False and state["Pid"] == 0
                    )
                except BaseException:  # noqa: BLE001 - retain the original failure, never retry cleanup
                    observation["original_container_cleanup_unknown"] = True
            raise


def _json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                       allow_nan=False) + "\n").encode("ascii")


def validate_custody_observation(command: dict, planned: dict, stage: str, index: int,
                                 recipe_sha256: str, environment: dict[str, str],
                                 backend: str = "podman") -> None:
    """Check the original runner's added observations without granting custody."""
    value = command.get("custody")
    current = {record["path"] for record in planned["outputs"]}
    executed = []
    for arg in planned["argv"]:
        if not arg.startswith("@"):
            executed.append(arg)
            continue
        role, relative = arg[1:].split("/", 1)
        root = GUEST_CURRENT_ROOT if role == "work" and relative in current else _GUEST[role.removesuffix("-dir")]
        executed.append(root + "/" + relative)
    expected_environment = _guest_build_environment(environment)
    invalid = type(value) is not dict
    if not invalid:
        invalid = (
            value.get("schema") != "lunar-podman-build-command-observation-v1"
            or value.get("recipe_sha256") != recipe_sha256 or value.get("stage") != stage
            or value.get("index") != index or value.get("original_argv_sha256") != _pin(_json(planned["argv"]))
            or value.get("executed_argv") != executed or value.get("executed_environment") != expected_environment
            or value.get("guest_roots") != {**_GUEST, "current_output": GUEST_CURRENT_ROOT}
            or value.get("input_layout") != (SNAPSHOT_BACKEND if backend == SNAPSHOT_BACKEND else "copied-image-v1")
            or value.get("readback_outputs") != command["outputs"]
            or value.get("original_container_exit_confirmed") is not True
            or value.get("container_creation_unknown") is not False
            or value.get("seccomp_sha256") != _pin(_json(_SECCOMP))
            or command.get("direct_child_role") != "original-podman-attach-client"
            or command.get("descendant_cleanup_verified") is not False
            or any(value.get(key) is not False for key in (
                "complete_namespace_disappearance_verified", "immutable_custody_verified",
                "driver_inputs_verified", "installation_accepted", "production_admission",
                "aggregate_output_hard_quota_verified"))
            or any(type(value.get(key)) is not str or _ID.fullmatch(value[key]) is None
                   for key in ("container_id", "image_id"))
        )
    if not invalid:
        state = value.get("original_container_state", {})
        policy = value.get("runtime_policy", {})
        invalid = (
            state.get("Status") != "exited" or state.get("Running") is not False or state.get("Pid") != 0
            or state.get("ExitCode") != 0 or state.get("OOMKilled") is not False or bool(state.get("Error"))
            or any(policy.get(key) is not True for key in (
                "root_readonly", "capabilities_zero", "no_new_privileges", "private_namespaces",
                "fixed_seccomp_verified"))
            or type(policy.get("oci_sha256")) is not str or _ID.fullmatch(policy["oci_sha256"]) is None
        )
        if backend == SNAPSHOT_BACKEND:
            mounts = policy.get("readonly_snapshots")
            invalid = invalid or type(mounts) is not dict or set(mounts) != set(_GUEST.values())
            if not invalid:
                invalid = any(type(path) is not str or not Path(path).is_absolute() for path in mounts.values())
    if invalid:
        raise ValueError("podman_custody_original_observation")
