"""Fail-closed host isolation policy for trusted producer target execution.

The policy is consumed by the native trusted bootstrap immediately before target
``exec``.  It is deliberately platform-specific: Darwin uses a deny-default
sandbox profile; Linux requires Landlock plus a seccomp network/process filter.
Unsupported platforms cannot produce a policy.  This module never claims that
an arbitrary already-running producer was isolated.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

_MAX_PROFILE_BYTES = 32 * 1024
_MAX_PATHS = 64
_MAX_WRITE_DIRS = 16
_MAX_PATH_BYTES = 4096


class ProducerIsolationError(ValueError):
    """Fixed-code error while preparing a native isolation policy."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> None:
    raise ProducerIsolationError(code)


def _path(value: str | Path, *, directory: bool | None = None) -> str:
    if isinstance(value, Path):
        candidate = value
    elif isinstance(value, str):
        candidate = Path(value)
    else:
        _fail("producer_isolation_path_invalid")
    if not candidate.is_absolute() or "\x00" in str(candidate):
        _fail("producer_isolation_path_invalid")
    try:
        # resolve(strict=True) makes the policy bind to the currently observed
        # object rather than an attacker-controlled parent symlink.
        resolved = candidate.resolve(strict=True)
        info = os.stat(resolved, follow_symlinks=False)
    except (OSError, RuntimeError) as exc:
        raise ProducerIsolationError("producer_isolation_path_unavailable") from exc
    if stat.S_ISLNK(info.st_mode) or info.st_nlink < 1:
        _fail("producer_isolation_path_invalid")
    if directory is True and not stat.S_ISDIR(info.st_mode):
        _fail("producer_isolation_directory_invalid")
    if directory is False and not stat.S_ISREG(info.st_mode):
        _fail("producer_isolation_file_invalid")
    value = str(resolved)
    if len(value.encode()) > _MAX_PATH_BYTES:
        _fail("producer_isolation_path_too_long")
    return value


def _quote_sbpl(value: str) -> str:
    if any(char in value for char in ("\x00", "\n", "\r")):
        _fail("producer_isolation_profile_invalid")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        raise ProducerIsolationError("producer_isolation_canonical_invalid") from exc


@dataclass(frozen=True, slots=True)
class ProducerIsolationPolicy:
    """Exact native isolation input and its self-authenticating digest."""

    platform: str
    profile: str
    read_paths: tuple[str, ...]
    write_dirs: tuple[str, ...]
    policy_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "platform": self.platform,
            "profile": self.profile,
            "read_paths": list(self.read_paths),
            "write_dirs": list(self.write_dirs),
            "policy_sha256": self.policy_sha256,
        }

    def validate(self) -> None:
        if self.platform not in {"darwin-sandbox-v1", "linux-landlock-seccomp-v1"}:
            _fail("producer_isolation_platform_unsupported")
        if type(self.profile) is not str or not self.profile or len(self.profile.encode()) > _MAX_PROFILE_BYTES:
            _fail("producer_isolation_profile_invalid")
        if len(self.read_paths) > _MAX_PATHS or len(self.write_dirs) > _MAX_WRITE_DIRS:
            _fail("producer_isolation_path_count_invalid")
        if tuple(sorted(set(self.read_paths))) != self.read_paths:
            _fail("producer_isolation_paths_not_canonical")
        if tuple(sorted(set(self.write_dirs))) != self.write_dirs:
            _fail("producer_isolation_paths_not_canonical")
        expected = hashlib.sha256(_canonical({
            "platform": self.platform, "profile": self.profile,
            "read_paths": list(self.read_paths), "write_dirs": list(self.write_dirs),
        })).hexdigest()
        if self.policy_sha256 != expected:
            _fail("producer_isolation_digest_mismatch")


def build_producer_isolation_policy(
    *, read_paths: tuple[str | Path, ...] | list[str | Path] = (),
    write_dirs: tuple[str | Path, ...] | list[str | Path] = (),
    platform: str | None = None,
) -> ProducerIsolationPolicy:
    """Build a strict policy; all paths are canonical absolute regular objects."""
    selected = platform or ("darwin-sandbox-v1" if sys.platform == "darwin" else
                            "linux-landlock-seccomp-v1" if sys.platform.startswith("linux") else "unsupported")
    if selected == "darwin-sandbox-v1":
        read = tuple(sorted({_path(item) for item in read_paths}))
        writes = tuple(sorted({_path(item, directory=True) for item in write_dirs}))
        lines = ["(version 1)", "(deny default)",
                 "(allow signal (target self))", "(allow sysctl-read)",
                 # Darwin dyld's ignition loader opens the root directory while
                 # discovering the shared cache.  This literal grants only the
                 # root directory itself, never reads of arbitrary descendants.
                 "(allow file-read-data (literal \"/\"))",
                 # System runtime objects needed by dyld and shebang interpreters.
                 # They contain no producer credentials and remain read-only.
                 "(allow file-read* (subpath \"/usr/lib\"))",
                 "(allow file-read* (subpath \"/System/Library\"))",
                 "(allow file-read* (subpath \"/usr/bin\"))",
                 "(allow file-read* (subpath \"/bin\"))",
                 "(deny network*)"]
        for item in read:
            lines.append(f"(allow file-read* (literal {_quote_sbpl(item)}))")
            lines.append(f"(allow process-exec (literal {_quote_sbpl(item)}))")
            # A literal file cannot be traversed without directory lookup on its
            # ancestors.  Allow exact ancestor directories only.
            parent = Path(item).parent
            while parent != parent.parent:
                lines.append(f"(allow file-read-metadata (literal {_quote_sbpl(str(parent))}))")
                parent = parent.parent
        for item in writes:
            lines.append(f"(allow file-read* (subpath {_quote_sbpl(item)}))")
            lines.append(f"(allow file-write* (subpath {_quote_sbpl(item)}))")
        profile = "\n".join(lines) + "\n"
    elif selected == "linux-landlock-seccomp-v1":
        read = tuple(sorted({_path(item) for item in read_paths}))
        writes = tuple(sorted({_path(item, directory=True) for item in write_dirs}))
        profile = "linux-landlock-seccomp-v1"
    else:
        _fail("producer_isolation_platform_unsupported")
    if len(profile.encode()) > _MAX_PROFILE_BYTES:
        _fail("producer_isolation_profile_too_large")
    digest = hashlib.sha256(_canonical({
        "platform": selected, "profile": profile,
        "read_paths": list(read), "write_dirs": list(writes),
    })).hexdigest()
    policy = ProducerIsolationPolicy(selected, profile, read, writes, digest)
    policy.validate()
    return policy


__all__ = ["ProducerIsolationError", "ProducerIsolationPolicy", "build_producer_isolation_policy"]
