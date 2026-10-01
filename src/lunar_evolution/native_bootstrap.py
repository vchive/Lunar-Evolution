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

_SOURCE = Path(__file__).with_name("native_bootstrap.c")
_MAX_BYTES = 8 * 1024 * 1024
_MAX_PATH_BYTES = 4096
_MAX_ARGC = 64


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
    implementation_version: str = "native-bootstrap-v1",
) -> NativeBootstrapArtifact:
    """Compile one private native artifact and return its exact descriptor."""
    mode = _platform_mode()
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


def native_bootstrap_command(
    artifact: NativeBootstrapArtifact | str | Path,
    *,
    control_fd: int,
    gate_fd: int,
    frame_fd: int,
    controller_lifeline_fd: int | None = None,
) -> tuple[str, ...]:
    """Build a guarded command; omitting the lifeline is for direct fixtures only."""
    executable = artifact.path if isinstance(artifact, NativeBootstrapArtifact) else Path(artifact)
    descriptors = (control_fd, gate_fd, frame_fd)
    if controller_lifeline_fd is not None:
        descriptors += (controller_lifeline_fd,)
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in descriptors):
        _fail("native_bootstrap_fd_invalid")
    if controller_lifeline_fd is not None and controller_lifeline_fd in descriptors[:3]:
        _fail("native_bootstrap_fd_invalid")
    command = (str(executable), "--control-fd", str(control_fd), "--gate-fd", str(gate_fd), "--frame-fd", str(frame_fd))
    if controller_lifeline_fd is not None:
        command += ("--controller-lifeline-fd", str(controller_lifeline_fd))
    return command


__all__ = [
    "NativeBootstrapArtifact", "NativeBootstrapError", "build_native_bootstrap_artifact",
    "encode_native_bootstrap_control", "load_native_bootstrap_artifact", "native_bootstrap_command",
    "native_bootstrap_source_path",
]
