"""Build the finite Linux scope helper without installing or executing it.

The actual installed profile must separately pin this artifact and the native
bootstrap. A successful developer build grants no deployment or runtime claim.
"""
from __future__ import annotations

import hashlib
import os
import platform
import shutil
import stat
import subprocess
import sys
from pathlib import Path

from .native_bootstrap import (
    NativeBootstrapArtifact,
    NativeBootstrapError,
    _identity,
    load_native_bootstrap_artifact,
)
from .producer_bootstrap import TrustedBootstrapDescriptor

WHOLE_SCOPE_IMPLEMENTATION = "native-whole-scope-v1"
WHOLE_SCOPE_ALLOWLIST = "lunar-native-whole-scope-v1"
_SOURCE_NAMES = (
    "native_whole_scope.c",
    "native_whole_scope_protocol.h",
    "native_whole_scope_platform.h",
)


def native_whole_scope_source_paths() -> tuple[Path, ...]:
    """Return every source whose bytes define the installed helper artifact."""
    return tuple(Path(__file__).with_name(name) for name in _SOURCE_NAMES)


def _platform() -> None:
    if (platform.system() != "Linux" or platform.machine().lower() not in {"x86_64", "amd64"}
            or sys.byteorder != "little"):
        raise NativeBootstrapError("native_whole_scope_platform_unsupported")


def _source_pin() -> str:
    digest = hashlib.sha256()
    try:
        for path in native_whole_scope_source_paths():
            raw = path.read_bytes()
            digest.update(len(path.name).to_bytes(4, "big"))
            digest.update(path.name.encode("ascii"))
            digest.update(len(raw).to_bytes(8, "big"))
            digest.update(raw)
    except OSError as exc:
        raise NativeBootstrapError("native_whole_scope_source_unavailable") from exc
    return digest.hexdigest()


def build_native_whole_scope_artifact(
    output_dir: str | Path,
    *,
    compiler: str | Path | None = None,
    allowlist_id: str = WHOLE_SCOPE_ALLOWLIST,
) -> NativeBootstrapArtifact:
    """Compile the explicit scope helper; no account, ACL or scope is changed."""
    _platform()
    if type(allowlist_id) is not str or not allowlist_id:
        raise NativeBootstrapError("native_whole_scope_allowlist_invalid")
    before = _source_pin()
    root = Path(output_dir).expanduser().absolute()
    try:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = root.stat(follow_symlinks=False)
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o700):
            raise NativeBootstrapError("native_whole_scope_output_invalid")
    except OSError as exc:
        raise NativeBootstrapError("native_whole_scope_output_invalid") from exc
    executable = root / "lunar-whole-scope"
    if executable.exists() or executable.is_symlink():
        raise NativeBootstrapError("native_whole_scope_output_exists")
    selected = (shutil.which(str(compiler)) if compiler is not None
                else shutil.which("clang") or shutil.which("cc"))
    if selected is None:
        raise NativeBootstrapError("native_whole_scope_compiler_missing")
    try:
        subprocess.run(
            [selected, "-std=c11", "-O2", "-fstack-protector-strong", "-D_FORTIFY_SOURCE=2",
             "-Wall", "-Wextra", "-Werror", "-Wl,-z,relro", "-Wl,-z,now",
             "-o", str(executable), str(native_whole_scope_source_paths()[0])],
            check=True, stdin=subprocess.DEVNULL, capture_output=True,
            timeout=30, env={"PATH": os.defpath, "LANG": "C"},
        )
    except subprocess.TimeoutExpired as exc:
        raise NativeBootstrapError("native_whole_scope_build_timeout") from exc
    except (OSError, subprocess.CalledProcessError) as exc:
        raise NativeBootstrapError("native_whole_scope_build_failed") from exc
    if _source_pin() != before:
        raise NativeBootstrapError("native_whole_scope_source_changed")
    try:
        executable.chmod(0o700)
        observed = _identity(executable)
    except OSError as exc:
        raise NativeBootstrapError("native_whole_scope_artifact_invalid") from exc
    descriptor = TrustedBootstrapDescriptor(
        implementation_version=WHOLE_SCOPE_IMPLEMENTATION,
        bootstrap_sha256=str(observed["sha256"]), size=int(observed["size"]),
        device=int(observed["device"]), inode=int(observed["inode"]),
        mtime_ns=int(observed["mtime_ns"]), ctime_ns=int(observed["ctime_ns"]),
        allowlist_id=allowlist_id, platform_execution_mode="linux-fd-bound",
    )
    return NativeBootstrapArtifact(
        path=executable, source_sha256=before, artifact_sha256=str(observed["sha256"]),
        compiler=selected, platform_execution_mode="linux-fd-bound",
        allowlist_id=allowlist_id, descriptor=descriptor,
    )


def load_native_whole_scope_artifact(
    path: str | Path, *, descriptor: TrustedBootstrapDescriptor, allowlist_id: str,
) -> NativeBootstrapArtifact:
    """Compare an installed exact artifact; this does not acquire a live owner."""
    _platform()
    if descriptor.implementation_version != WHOLE_SCOPE_IMPLEMENTATION:
        raise NativeBootstrapError("native_whole_scope_implementation_invalid")
    return load_native_bootstrap_artifact(path, descriptor=descriptor, allowlist_id=allowlist_id)
