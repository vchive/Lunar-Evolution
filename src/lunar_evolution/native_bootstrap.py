"""Build and invoke the Lunar-owned native trusted bootstrap.

The build output is an installation artifact, never a checked-in binary.  The
artifact descriptor is produced from the actual output bytes and must be
selected by the caller's installation allowlist before a launch is admitted.
This module does not consume an attestation, publish registration, release a
gate, or perform process cleanup.
"""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import stat
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .producer_bootstrap import TrustedBootstrapDescriptor, TrustedBootstrapLaunch
from .producer_grant_anchors import HeldProducerGrantPlan, ProducerGrantError

_SOURCE = Path(__file__).with_name("native_bootstrap.c")
_MAX_BYTES = 8 * 1024 * 1024
_MAX_PATH_BYTES = 4096
_MAX_ARGC = 64
LINUX_CHILD_SUPERVISION = "linux-subreaper-v1"
LINUX_SUBREAPER_IMPLEMENTATION = "native-bootstrap-linux-subreaper-v1"
LINUX_INPUT_MUTATION_IMPLEMENTATION = "native-bootstrap-linux-input-mutation-v1"
LINUX_FD_HANDOFF_IMPLEMENTATION = "native-bootstrap-linux-fd-handoff-v1"
LINUX_FD_CONTROL_IMPLEMENTATION = "native-bootstrap-linux-fd-control-v1"
LINUX_GRANT_OBJECT_IMPLEMENTATION = "native-bootstrap-linux-grant-objects-v1"
LINUX_GRANT_OBJECT_BINDING = "linux-held-grants-v1"
LINUX_IPC_CONTROL_IMPLEMENTATION = "native-bootstrap-linux-ipc-control-v1"


class NativeBootstrapError(ValueError):
    """Fixed-code failure while building or preparing the native artifact."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> None:
    raise NativeBootstrapError(code)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            while chunk := source.read(64 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise NativeBootstrapError("native_bootstrap_artifact_unreadable") from exc
    return digest.hexdigest()


def _identity(path: Path) -> dict[str, int | str]:
    try:
        before = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise NativeBootstrapError("native_bootstrap_artifact_unreadable") from exc
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not before.st_mode & 0o111:
        _fail("native_bootstrap_artifact_invalid")
    if before.st_size <= 0 or before.st_size > _MAX_BYTES:
        _fail("native_bootstrap_artifact_invalid")
    parent_fd = -1
    fd = -1
    try:
        parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent_fd)
    except OSError as exc:
        raise NativeBootstrapError("native_bootstrap_artifact_unreadable") from exc
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns) != (
            before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns
        ):
            _fail("native_bootstrap_artifact_changed")
        digest = hashlib.sha256()
        while chunk := os.read(fd, 64 * 1024):
            digest.update(chunk)
        after = os.fstat(fd)
        named = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as exc:
        raise NativeBootstrapError("native_bootstrap_artifact_unreadable") from exc
    finally:
        if fd >= 0:
            os.close(fd)
        if parent_fd >= 0:
            os.close(parent_fd)
    if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (
        before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns
    ) or (named.st_dev, named.st_ino, named.st_size, named.st_mtime_ns, named.st_ctime_ns) != (
        before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns
    ):
        _fail("native_bootstrap_artifact_changed")
    return {"sha256": digest.hexdigest(), "size": before.st_size, "device": before.st_dev,
            "inode": before.st_ino, "mtime_ns": before.st_mtime_ns, "ctime_ns": before.st_ctime_ns}


@dataclass(frozen=True, slots=True)
class NativeBootstrapArtifact:
    path: Path
    source_sha256: str
    artifact_sha256: str
    compiler: str
    platform_execution_mode: str
    allowlist_id: str
    descriptor: TrustedBootstrapDescriptor


def native_bootstrap_source_path() -> Path:
    """Return the checked-in native bootstrap source."""
    return _SOURCE


def _platform_mode() -> str:
    if sys_platform := platform.system().lower():
        if sys_platform == "darwin":
            return "darwin-immutable-snapshot"
        if sys_platform == "linux":
            return "linux-fd-bound"
    _fail("native_bootstrap_platform_unsupported")


def build_native_bootstrap_artifact(
    output_dir: str | Path,
    *,
    compiler: str | Path | None = None,
    allowlist_id: str = "lunar-native-bootstrap-v1",
    implementation_version: str | None = None,
) -> NativeBootstrapArtifact:
    """Compile one private native artifact and return its exact descriptor."""
    mode = _platform_mode()
    if implementation_version is None:
        implementation_version = (
            LINUX_IPC_CONTROL_IMPLEMENTATION if mode == "linux-fd-bound" else "native-bootstrap-v1"
        )
    if implementation_version in {
        LINUX_SUBREAPER_IMPLEMENTATION, LINUX_INPUT_MUTATION_IMPLEMENTATION, LINUX_FD_HANDOFF_IMPLEMENTATION,
        LINUX_FD_CONTROL_IMPLEMENTATION, LINUX_GRANT_OBJECT_IMPLEMENTATION, LINUX_IPC_CONTROL_IMPLEMENTATION,
    } and mode != "linux-fd-bound":
        _fail("native_bootstrap_child_supervision_unsupported")
    if not isinstance(allowlist_id, str) or not allowlist_id:
        _fail("native_bootstrap_allowlist_invalid")
    source = _SOURCE
    if not source.is_file():
        _fail("native_bootstrap_source_missing")
    source_sha = _sha256(source)
    root = Path(output_dir).expanduser().absolute()
    try:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not stat.S_ISDIR(root.stat(follow_symlinks=False).st_mode):
            _fail("native_bootstrap_output_invalid")
    except OSError as exc:
        raise NativeBootstrapError("native_bootstrap_output_invalid") from exc
    compiler_path = shutil.which(str(compiler)) if compiler is not None else (shutil.which("clang") or shutil.which("cc"))
    if compiler_path is None:
        _fail("native_bootstrap_compiler_missing")
    output = root / "lunar-trusted-bootstrap"
    if output.exists() or output.is_symlink():
        _fail("native_bootstrap_output_exists")
    try:
        linker_hardening = ["-Wl,-z,relro", "-Wl,-z,now"] if platform.system().lower() == "linux" else []
        subprocess.run(
            [compiler_path, "-std=c11", "-O2", "-fstack-protector-strong", "-D_FORTIFY_SOURCE=2",
             "-Wall", "-Wextra", "-Werror", "-Wno-deprecated-declarations", "-pthread", *linker_hardening,
             "-o", str(output), str(source)],
            check=True, stdin=subprocess.DEVNULL, capture_output=True,
            timeout=30, env={"PATH": os.defpath, "LANG": "C"},
        )
    except subprocess.TimeoutExpired as exc:
        raise NativeBootstrapError("native_bootstrap_build_timeout") from exc
    except (OSError, subprocess.CalledProcessError) as exc:
        raise NativeBootstrapError("native_bootstrap_build_failed") from exc
    try:
        output.chmod(0o700)
    except OSError as exc:
        raise NativeBootstrapError("native_bootstrap_artifact_invalid") from exc
    observed = _identity(output)
    descriptor = TrustedBootstrapDescriptor(
        implementation_version=implementation_version,
        bootstrap_sha256=str(observed["sha256"]), size=int(observed["size"]),
        device=int(observed["device"]), inode=int(observed["inode"]),
        mtime_ns=int(observed["mtime_ns"]), ctime_ns=int(observed["ctime_ns"]),
        allowlist_id=allowlist_id, platform_execution_mode=mode,
    )
    return NativeBootstrapArtifact(
        path=output, source_sha256=source_sha, artifact_sha256=str(observed["sha256"]),
        compiler=str(compiler_path), platform_execution_mode=mode,
        allowlist_id=allowlist_id, descriptor=descriptor,
    )


def load_native_bootstrap_artifact(
    path: str | Path,
    *,
    descriptor: TrustedBootstrapDescriptor,
    allowlist_id: str,
) -> NativeBootstrapArtifact:
    """Recheck an installation-owned artifact against its exact allowlist descriptor."""
    artifact = Path(path).expanduser().absolute()
    if descriptor.allowlist_id != allowlist_id or descriptor.platform_execution_mode != _platform_mode():
        _fail("native_bootstrap_allowlist_mismatch")
    observed = _identity(artifact)
    expected = {
        "sha256": descriptor.bootstrap_sha256, "size": descriptor.size,
        "device": descriptor.device, "inode": descriptor.inode,
        "mtime_ns": descriptor.mtime_ns, "ctime_ns": descriptor.ctime_ns,
    }
    if any(observed[key] != expected[key] for key in ("sha256", "size", "device", "inode", "mtime_ns", "ctime_ns")):
        _fail("native_bootstrap_artifact_changed")
    return NativeBootstrapArtifact(
        path=artifact, source_sha256="", artifact_sha256=str(observed["sha256"]), compiler="",
        platform_execution_mode=descriptor.platform_execution_mode, allowlist_id=allowlist_id,
        descriptor=descriptor,
    )


def _put_u32(value: int) -> bytes:
    if not isinstance(value, int) or value < 0 or value > 0xFFFFFFFF:
        _fail("native_bootstrap_control_invalid")
    return value.to_bytes(4, "big")


def _put_string(value: str, *, maximum: int) -> bytes:
    if not isinstance(value, str) or not value or "\x00" in value:
        _fail("native_bootstrap_control_invalid")
    encoded = value.encode("utf-8")
    if len(encoded) > maximum:
        _fail("native_bootstrap_control_invalid")
    return _put_u32(len(encoded)) + encoded


def encode_native_bootstrap_control(
    launch: TrustedBootstrapLaunch,
    *,
    target_path: str | Path,
    target_argv: Sequence[str],
    target_cwd: str | Path,
    target_fd: int | None = None,
    isolation_profile: str = "fixture-none",
    read_paths: Sequence[str | Path] = (),
    write_dirs: Sequence[str | Path] = (),
    isolation_policy: object | None = None,
) -> bytes:
    """Encode one bounded private control record for the native child."""
    if not isinstance(launch, TrustedBootstrapLaunch):
        _fail("native_bootstrap_launch_invalid")
    if isolation_policy is not None:
        profile = getattr(isolation_policy, "profile", None)
        policy_reads = getattr(isolation_policy, "read_paths", None)
        policy_writes = getattr(isolation_policy, "write_dirs", None)
        if not isinstance(profile, str) or policy_reads is None or policy_writes is None:
            _fail("native_bootstrap_isolation_invalid")
        isolation_profile = profile
        read_paths = tuple(policy_reads)
        write_dirs = tuple(policy_writes)
        validate = getattr(isolation_policy, "validate", None)
        if not callable(validate):
            _fail("native_bootstrap_isolation_invalid")
        try:
            validate()
        except Exception as exc:  # policy implementation maps to fixed validation codes
            raise NativeBootstrapError("native_bootstrap_isolation_invalid") from exc
    argv = tuple(target_argv)
    if not argv or len(argv) > _MAX_ARGC or any(not isinstance(item, str) or not item for item in argv):
        _fail("native_bootstrap_control_invalid")
    if target_fd is None:
        target_fd = -1
    if isinstance(target_fd, bool) or not isinstance(target_fd, int) or target_fd < -1 or target_fd > 1_000_000:
        _fail("native_bootstrap_control_invalid")
    path = str(Path(target_path).expanduser().absolute())
    cwd = str(Path(target_cwd).expanduser().absolute())
    if len(path.encode()) > _MAX_PATH_BYTES or len(cwd.encode()) > _MAX_PATH_BYTES:
        _fail("native_bootstrap_control_invalid")
    # Path-based launches must execute the same path whose bytes the native
    # child hashes.  Otherwise argv[0] could point at a different executable.
    if target_fd < 0:
        try:
            if str(Path(argv[0]).expanduser().absolute()) != path:
                _fail("native_bootstrap_target_binding_mismatch")
        except (OSError, RuntimeError):
            _fail("native_bootstrap_target_binding_mismatch")
    if not isinstance(isolation_profile, str) or "\x00" in isolation_profile or len(isolation_profile.encode()) > 32 * 1024:
        _fail("native_bootstrap_control_invalid")
    if len(read_paths) > 64 or len(write_dirs) > 16:
        _fail("native_bootstrap_control_invalid")
    result = bytearray(b"LNB1\x00\x01\x00\x00")
    result.extend(launch.launch_sha256.encode("ascii")); result.extend(launch.intent_sha256.encode("ascii"));
    result.extend(launch.target_executable_identity.encode("ascii"));
    result.extend((target_fd & 0xFFFFFFFF).to_bytes(4, "big"))
    result.extend(_put_string(path, maximum=_MAX_PATH_BYTES)); result.extend(_put_string(cwd, maximum=_MAX_PATH_BYTES));
    result.extend(_put_string(isolation_profile, maximum=32 * 1024)); result.extend(_put_u32(len(read_paths)))
    for item in read_paths: result.extend(_put_string(str(Path(item).expanduser().absolute()), maximum=_MAX_PATH_BYTES))
    result.extend(_put_u32(len(write_dirs)))
    for item in write_dirs: result.extend(_put_string(str(Path(item).expanduser().absolute()), maximum=_MAX_PATH_BYTES))
    result.extend(_put_u32(len(argv)))
    for item in argv: result.extend(_put_string(item, maximum=4096))
    if len(result) > 64 * 1024:
        _fail("native_bootstrap_control_too_large")
    return bytes(result)


def encode_native_bootstrap_control_v2(
    launch: TrustedBootstrapLaunch, *, target_path: str,
    target_argv: tuple[str, ...], target_cwd: str | Path,
    target_fd: int, bootstrap_fd: int, held_grants: HeldProducerGrantPlan,
    reserved_fds: tuple[int, ...] = (),
) -> bytes:
    """Encode original live Linux grants; detached observations cannot supply them."""
    if (type(held_grants) is not HeldProducerGrantPlan
            or not isinstance(launch, TrustedBootstrapLaunch)):
        _fail("native_bootstrap_grant_binding_invalid")
    if (type(target_fd) is not int or not 2 < target_fd <= 0x7fffffff
            or type(bootstrap_fd) is not int or not 2 < bootstrap_fd <= 0x7fffffff
            or target_fd == bootstrap_fd):
        _fail("native_bootstrap_fd_invalid")
    if (type(target_argv) is not tuple or not 1 <= len(target_argv) <= _MAX_ARGC
            or any(type(item) is not str or not item for item in target_argv)):
        _fail("native_bootstrap_control_invalid")
    if type(target_path) is not str or not target_path.startswith("/"):
        _fail("native_bootstrap_control_invalid")
    hashes = (launch.launch_sha256, launch.intent_sha256, launch.target_executable_identity)
    if any(type(value) is not str or len(value) != 64
           or any(char not in "0123456789abcdef" for char in value) for value in hashes):
        _fail("native_bootstrap_control_invalid")
    if (len(target_path) > _MAX_PATH_BYTES
            or any(len(item) > _MAX_PATH_BYTES for item in target_argv)
            or type(target_cwd) not in {str, type(Path())}):
        _fail("native_bootstrap_control_invalid")
    try:
        path_wire = _put_string(target_path, maximum=_MAX_PATH_BYTES)
        argv_wire = b"".join(_put_string(item, maximum=_MAX_PATH_BYTES) for item in target_argv)
    except UnicodeError as exc:
        raise NativeBootstrapError("native_bootstrap_control_invalid") from exc
    if type(reserved_fds) is not tuple or len(reserved_fds) > 254:
        _fail("native_bootstrap_fd_invalid")
    reserved = (*reserved_fds, target_fd, bootstrap_fd)
    try:
        held_grants.validate(reserved_fds=reserved)
        nodes = held_grants.binding_nodes
        anchors = held_grants.anchors
        if not 1 <= len(nodes) <= 256 or not 1 <= len(anchors) <= 81:
            _fail("native_bootstrap_control_invalid")
        cwd = str(target_cwd)
        cwd_indices = [i for i, anchor in enumerate(anchors) if "cwd" in anchor.record.roles]
        if len(cwd_indices) != 1 or anchors[cwd_indices[0]].record.path != cwd:
            _fail("native_bootstrap_cwd_binding_invalid")
        result = bytearray(b"LNB1\x00\x02\x00\x00")
        result.extend("".join(hashes).encode("ascii"))
        result.extend(_put_u32(target_fd)); result.extend(_put_u32(bootstrap_fd))
        result.extend(path_wire); result.extend(_put_u32(1)); result.extend(_put_u32(len(nodes)))
        positions: dict[str, int] = {}
        for index, node in enumerate(nodes):
            parent = node.parent_index
            if (index == 0 and (parent is not None or node.path != "/" or node.name != "")) or (
                index != 0 and (type(parent) is not int or not 0 <= parent < index)
            ):
                _fail("native_bootstrap_control_invalid")
            node.identity.validate()
            name = node.name.encode("utf-8")
            if len(name) > _MAX_PATH_BYTES or b"\x00" in name:
                _fail("native_bootstrap_control_invalid")
            if index and (not name or "/" in node.name or node.name in {".", ".."}):
                _fail("native_bootstrap_control_invalid")
            if node.path in positions:
                _fail("native_bootstrap_control_invalid")
            positions[node.path] = index
            result.extend(_put_u32(0xffffffff if parent is None else parent))
            result.extend(_put_u32(1 if node.identity.kind == "directory" else 2))
            result.extend(node.identity.device.to_bytes(8, "big"))
            result.extend(node.identity.inode.to_bytes(8, "big"))
            result.extend(_put_u32(len(name))); result.extend(name)
        result.extend(_put_u32(len(anchors)))
        role_bits = {"protected-file": 1, "readonly-directory": 2, "writable-directory": 4, "cwd": 8}
        for anchor in anchors:
            node_index = positions.get(anchor.record.path)
            mask = sum(role_bits[role] for role in anchor.record.roles)
            if node_index is None or mask not in {1, 2, 4, 12}:
                _fail("native_bootstrap_control_invalid")
            result.extend(_put_u32(node_index)); result.extend(_put_u32(mask))
            result.extend(_put_u32(anchor.fd))
        result.extend(_put_u32(cwd_indices[0])); result.extend(_put_u32(len(target_argv)))
        result.extend(argv_wire)
        if len(result) > 64 * 1024:
            _fail("native_bootstrap_control_too_large")
        held_grants.validate(reserved_fds=reserved)
        return bytes(result)
    except ProducerGrantError as exc:
        raise NativeBootstrapError("native_bootstrap_grant_binding_invalid") from exc


def native_bootstrap_command(
    artifact: NativeBootstrapArtifact | str | Path,
    *,
    control_fd: int,
    gate_fd: int,
    frame_fd: int,
    controller_lifeline_fd: int | None = None,
    deadline_monotonic_ns: int | None = None,
    child_supervision: str | None = None,
    grant_object_binding: str | None = None,
) -> tuple[str, ...]:
    """Build a guarded command; omitted lifeline/deadline are direct fixture interfaces."""
    executable = artifact.path if isinstance(artifact, NativeBootstrapArtifact) else Path(artifact)
    descriptors = (control_fd, gate_fd, frame_fd)
    if controller_lifeline_fd is not None:
        descriptors += (controller_lifeline_fd,)
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in descriptors):
        _fail("native_bootstrap_fd_invalid")
    if len(set(descriptors)) != len(descriptors):
        _fail("native_bootstrap_fd_invalid")
    if deadline_monotonic_ns is not None and (
        controller_lifeline_fd is None or type(deadline_monotonic_ns) is not int
        or deadline_monotonic_ns <= 0 or deadline_monotonic_ns > 0xFFFFFFFFFFFFFFFF
    ):
        _fail("native_bootstrap_deadline_invalid")
    if (
        child_supervision is None and isinstance(artifact, NativeBootstrapArtifact)
        and artifact.descriptor.implementation_version in {
            LINUX_SUBREAPER_IMPLEMENTATION, LINUX_INPUT_MUTATION_IMPLEMENTATION, LINUX_FD_HANDOFF_IMPLEMENTATION,
            LINUX_FD_CONTROL_IMPLEMENTATION, LINUX_GRANT_OBJECT_IMPLEMENTATION, LINUX_IPC_CONTROL_IMPLEMENTATION,
        }
        and controller_lifeline_fd is not None and deadline_monotonic_ns is not None
    ):
        child_supervision = LINUX_CHILD_SUPERVISION
    if child_supervision is not None:
        if child_supervision != LINUX_CHILD_SUPERVISION or (
            controller_lifeline_fd is None or deadline_monotonic_ns is None
        ):
            _fail("native_bootstrap_child_supervision_invalid")
        if platform.system().lower() != "linux":
            _fail("native_bootstrap_child_supervision_unsupported")
    if grant_object_binding is not None and (
        grant_object_binding != LINUX_GRANT_OBJECT_BINDING
        or child_supervision != LINUX_CHILD_SUPERVISION or platform.system().lower() != "linux"
    ):
        _fail("native_bootstrap_grant_binding_invalid")
    command = (str(executable), "--control-fd", str(control_fd), "--gate-fd", str(gate_fd), "--frame-fd", str(frame_fd))
    if controller_lifeline_fd is not None:
        command += ("--controller-lifeline-fd", str(controller_lifeline_fd))
    if deadline_monotonic_ns is not None:
        command += ("--deadline-monotonic-ns", str(deadline_monotonic_ns))
    if child_supervision is not None:
        command += ("--child-supervision", child_supervision)
    if grant_object_binding is not None:
        command += ("--grant-object-binding", grant_object_binding)
    return command


__all__ = [
    "LINUX_CHILD_SUPERVISION",
    "LINUX_FD_CONTROL_IMPLEMENTATION",
    "LINUX_FD_HANDOFF_IMPLEMENTATION",
    "LINUX_GRANT_OBJECT_BINDING",
    "LINUX_GRANT_OBJECT_IMPLEMENTATION",
    "LINUX_INPUT_MUTATION_IMPLEMENTATION",
    "LINUX_IPC_CONTROL_IMPLEMENTATION",
    "LINUX_SUBREAPER_IMPLEMENTATION",
    "NativeBootstrapArtifact",
    "NativeBootstrapError",
    "build_native_bootstrap_artifact",
    "encode_native_bootstrap_control",
    "encode_native_bootstrap_control_v2",
    "load_native_bootstrap_artifact",
    "native_bootstrap_command",
    "native_bootstrap_source_path",
]
