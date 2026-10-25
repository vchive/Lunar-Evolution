"""Internal create-only complete Zig copy; observation never grants custody.

All payloads come from one checked held archive snapshot. Partial destinations
are retained on refusal. This module neither spawns processes nor enforces an
immutable interval, and is deliberately disconnected from the build launcher.
"""

from __future__ import annotations

import hashlib
import math
import os
import stat
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import NoReturn

try:
    import resource
except ImportError:  # pragma: no cover - unsupported platforms fail closed.
    resource = None

from tools.static_python_fixture import archive_observation as archives
from tools.static_python_fixture import candidate_build_source_observation as fd_observation
from tools.static_python_fixture import toolchain_tree_observation as trees
from tools.static_python_fixture.toolchain_observation import StaticPythonToolchainObservation

_CHUNK = 64 * 1024
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
_CLEANUP_NOTE = "static_python_toolchain_copy_cleanup_unknown"


class StaticPythonToolchainCopyError(ValueError):
    """A fixed refusal without paths or archive payloads."""

    def __init__(self, reason: str) -> None:
        self.reason = "static_python_toolchain_copy_" + reason
        super().__init__(self.reason)


def _fail(reason: str) -> NoReturn:
    raise StaticPythonToolchainCopyError(reason)


def _identity(info: os.stat_result) -> tuple[int, int, int]:
    return info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode)


def _directory_pin(info: os.stat_result) -> tuple[int, int, int]:
    if not stat.S_ISDIR(info.st_mode):
        _fail("identity_drift")
    return info.st_dev, info.st_ino, info.st_mode


class _Descriptors:
    """Best-effort original-identity ownership under no private FD rebinding."""

    def __init__(self) -> None:
        self._owned: dict[int, tuple[int, int, int] | None] = {}

    def own(self, fd: int) -> int:
        # Register before the first fstat, which itself can fail/interruption.
        self._owned[fd] = None
        self._owned[fd] = _identity(os.fstat(fd))
        return fd

    def info(self, fd: int) -> os.stat_result:
        info = os.fstat(fd)
        if self._owned.get(fd) != _identity(info):
            _fail("identity_drift")
        return info

    def close(self, fd: int, primary: BaseException | None = None) -> None:
        original = self._owned.pop(fd)  # Never retry an uncertain numeric close.
        try:
            if original is not None and _identity(os.fstat(fd)) != original:
                _fail("cleanup_unknown")  # Known foreign reuse is not closed.
            os.close(fd)
        except BaseException as exc:
            if primary is not None:
                primary.add_note(_CLEANUP_NOTE)
            else:
                raise StaticPythonToolchainCopyError("cleanup_unknown") from exc

    def cleanup(self, primary: BaseException | None) -> None:
        first = None
        for fd in reversed(tuple(self._owned)):
            try:
                self.close(fd, primary)
            except BaseException as exc:  # noqa: BLE001 - attempt every owned role.
                if first is None:
                    first = exc
        if first is not None:
            raise first


def _descriptor_preflight(path_depth: int) -> None:
    # Our held ancestry/root remains open while the existing observer acquires
    # its own ancestry plus two traversal handles. No FD is retained per file.
    needed = 2 * path_depth + 16
    if resource is None:
        _fail("resource_refused")
    try:
        soft, _hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        census = "/proc/self/fd" if sys.platform == "linux" else "/dev/fd"
        current = len(os.listdir(census))
        if soft != resource.RLIM_INFINITY and current + needed > soft:
            _fail("resource_refused")
    except (OSError, ValueError, OverflowError):
        raise StaticPythonToolchainCopyError("resource_refused") from None


def _materialize_toolchain_copy(
    snapshot: archives.StaticPythonArchiveSnapshot,
    manifest: bytes,
    *,
    expected_manifest_sha256: str,
    destination_directory: str,
    deadline: float,
    monotonic: Callable[[], float] = time.monotonic,
) -> StaticPythonToolchainObservation:
    """Create and observe every member, preserving failures and exact modes.

    The absent destination leaf must have an euid-owned 0700 direct parent.
    Only a real acquired/profile-verified snapshot is accepted; tests replace
    installation profile pins explicitly instead of disabling these checks.
    """
    if type(deadline) is not float or not math.isfinite(deadline) or deadline <= 0:
        _fail("deadline_invalid")
    if not callable(monotonic):
        _fail("clock_invalid")

    def checkpoint() -> float:
        try:
            now = monotonic()
        except Exception:  # noqa: BLE001 - redact arbitrary caller-clock errors.
            raise StaticPythonToolchainCopyError("clock_invalid") from None
        if type(now) not in {int, float} or not math.isfinite(now):
            _fail("clock_invalid")
        if now >= deadline:
            _fail("wall_timeout")
        return now

    checkpoint()
    try:
        parts = fd_observation._path_parts(destination_directory)
    except fd_observation.CandidateBuildSourceObservationError:
        raise StaticPythonToolchainCopyError("destination_invalid") from None
    _descriptor_preflight(len(parts))
    checkpoint()
    try:
        checked = trees._manifest(manifest, expected_manifest_sha256)
    except (trees.StaticPythonToolchainTreeObservationError,
            trees.verified_inputs.StaticPythonVerifiedInputError):
        raise StaticPythonToolchainCopyError("manifest_invalid") from None
    entries = {}
    for member in checked.members:
        checkpoint()
        relative = "" if member.path == checked.root else member.path[len(checked.root) + 1:]
        entries[relative] = member
        if (member.kind == "directory" and member.mode != 0o755
                or member.kind == "file" and member.mode not in {0o644, 0o755}):
            _fail("unsupported_mode")
    directories = {path: item for path, item in entries.items() if item.kind == "directory"}
    files = {path: item for path, item in entries.items() if item.kind == "file"}
    if "" not in directories:
        _fail("manifest_invalid")
    children: dict[str, set[str]] = {path: set() for path in directories}
    for path in entries:
        checkpoint()
        if path and path.rpartition("/")[0] not in directories:
            _fail("manifest_parent_missing")
        if path:
            parent, _, name = path.rpartition("/")
            children[parent].add(name)
    try:
        observed, captured = archives._observe_archive_snapshot(
            snapshot, expected_manifest_sha256=expected_manifest_sha256,
            require_source_preimages=False, require_profile=True,
            checkpoint=checkpoint, capture_all_files=True,
        )
    except archives.StaticPythonArchiveObservationError as exc:
        if (exc.reason == "static_python_archive_observation_checkpoint_failed"
                and isinstance(exc.__cause__, (StaticPythonToolchainCopyError,
                                               KeyboardInterrupt, SystemExit))):
            raise exc.__cause__
        raise StaticPythonToolchainCopyError("archive_invalid") from None
    checkpoint()
    if (observed.manifest_json != manifest
            or observed.manifest_sha256 != expected_manifest_sha256):
        _fail("manifest_mismatch")
    if (type(captured) is not tuple
            or any(type(item) is not tuple or len(item) != 2
                   or type(item[0]) is not str or type(item[1]) is not bytes for item in captured)):
        _fail("payload_mismatch")
    payloads = dict(captured)
    if (len(payloads) != len(captured)
            or set(payloads) != {item.path for item in files.values()}):
        _fail("payload_mismatch")
    for member in files.values():
        checkpoint()
        raw = payloads[member.path]
        digest = hashlib.sha256()
        for offset in range(0, len(raw), _CHUNK):
            checkpoint()
            digest.update(raw[offset:offset + _CHUNK])
        if len(raw) != member.size or digest.hexdigest() != member.sha256:
            _fail("payload_mismatch")
    checkpoint()

    owner = _Descriptors()
    ancestry: list[tuple[int, str, int, tuple[int, int, int]]] = []
    directory_pins: dict[str, tuple[int, int, int]] = {}
    file_pins: dict[str, tuple[int, ...]] = {}
    root_fd = -1
    parent_fd = -1
    leaf = parts[-1]

    def guard(*, clock: bool = True) -> None:
        if clock:
            checkpoint()
        for parent, name, fd, pin in ancestry:
            if (_directory_pin(owner.info(fd)) != pin
                    or _directory_pin(os.stat(name, dir_fd=parent,
                                              follow_symlinks=False)) != pin):
                _fail("identity_drift")
        if parent_fd >= 0:
            parent_info = owner.info(parent_fd)
            if parent_info.st_uid != os.geteuid() or stat.S_IMODE(parent_info.st_mode) != 0o700:
                _fail("parent_not_private")
        if root_fd >= 0 and (
                _directory_pin(owner.info(root_fd)) != directory_pins[""]
                or _directory_pin(os.stat(leaf, dir_fd=parent_fd,
                                          follow_symlinks=False)) != directory_pins[""]):
            _fail("identity_drift")
        if clock:
            checkpoint()

    @contextmanager
    def directory(path: str, *, clock: bool = True) -> Iterator[int]:
        guard(clock=clock)
        current = owner.own(os.dup(root_fd))
        primary = None
        try:
            prefix = ""
            for component in path.split("/") if path else ():
                if clock:
                    checkpoint()
                prefix = prefix + "/" + component if prefix else component
                child = owner.own(os.open(component, _DIR_FLAGS, dir_fd=current))
                if (_directory_pin(owner.info(child)) != directory_pins[prefix]
                        or _directory_pin(os.stat(component, dir_fd=current,
                                                  follow_symlinks=False)) != directory_pins[prefix]):
                    _fail("identity_drift")
                previous, current = current, child
                owner.close(previous)
            yield current
        except BaseException as exc:
            primary = exc
            raise
        finally:
            owner.close(current, primary)

    def verify_files(
        *, clock: bool = True, final_checkpoint: Callable[[], None] | None = None,
    ) -> None:
        for path, pin in file_pins.items():
            if clock:
                checkpoint()
            if final_checkpoint is not None:
                final_checkpoint()
            parent, _, name = path.rpartition("/")
            with directory(parent, clock=clock) as fd:
                if fd_observation._stat_tuple(os.stat(name, dir_fd=fd,
                                                     follow_symlinks=False)) != pin:
                    _fail("identity_drift")

    primary = None
    try:
        current = owner.own(os.open("/", _DIR_FLAGS))
        for component in parts[:-1]:
            checkpoint()
            child = owner.own(os.open(component, _DIR_FLAGS, dir_fd=current))
            pin = _directory_pin(owner.info(child))
            ancestry.append((current, component, child, pin))
            current = child
        parent_fd = current
        guard()
        # mkdir is the only adoption boundary: every existing leaf refuses.
        try:
            os.mkdir(leaf, 0o700, dir_fd=parent_fd)
        except FileExistsError:
            raise StaticPythonToolchainCopyError("destination_exists") from None
        created = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
        directory_pins[""] = _directory_pin(created)
        root_fd = owner.own(os.open(leaf, _DIR_FLAGS, dir_fd=parent_fd))
        if _directory_pin(owner.info(root_fd)) != directory_pins[""]:
            _fail("identity_drift")
        os.fchmod(root_fd, 0o700)  # Explicit modes must not depend on umask.
        directory_pins[""] = _directory_pin(owner.info(root_fd))
        guard()
        ordered = sorted(directories, key=lambda path: (path.count("/"), path))
        for path in ordered:
            if not path:
                continue
            parent, _, name = path.rpartition("/")
            with directory(parent) as fd:
                os.mkdir(name, 0o700, dir_fd=fd)
                created = os.stat(name, dir_fd=fd, follow_symlinks=False)
                child = owner.own(os.open(name, _DIR_FLAGS, dir_fd=fd))
                error = None
                try:
                    if _directory_pin(owner.info(child)) != _directory_pin(created):
                        _fail("identity_drift")
                    os.fchmod(child, 0o700)
                    directory_pins[path] = _directory_pin(owner.info(child))
                except BaseException as exc:
                    error = exc
                    raise
                finally:
                    owner.close(child, error)
        for path, member in sorted(files.items()):
            parent, _, name = path.rpartition("/")
            with directory(parent) as fd:
                target = owner.own(os.open(name, _FILE_FLAGS, 0o600, dir_fd=fd))
                error = None
                try:
                    initial = owner.info(target)
                    if not stat.S_ISREG(initial.st_mode) or initial.st_nlink != 1 or initial.st_size:
                        _fail("identity_drift")
                    os.fchmod(target, 0o600)
                    raw = payloads[member.path]
                    offset = 0
                    while offset < len(raw):
                        guard()
                        block = raw[offset:offset + _CHUNK]
                        written = os.write(target, block)
                        checkpoint()
                        if type(written) is not int or not 0 < written <= len(block):
                            _fail("write_progress_invalid")
                        offset += written
                    after = owner.info(target)
                    if (after.st_nlink != 1 or after.st_size != member.size
                            or stat.S_IMODE(after.st_mode) != 0o600):
                        _fail("identity_drift")
                    os.fchmod(target, member.mode)
                    final = owner.info(target)
                    pin = fd_observation._stat_tuple(final)
                    if (final.st_nlink != 1 or stat.S_IMODE(final.st_mode) != member.mode
                            or fd_observation._stat_tuple(os.stat(
                                name, dir_fd=fd, follow_symlinks=False)) != pin):
                        _fail("identity_drift")
                    file_pins[path] = pin
                except BaseException as exc:
                    error = exc
                    raise
                finally:
                    owner.close(target, error)
        for path in reversed(ordered):
            with directory(path) as fd:
                os.fchmod(fd, directories[path].mode)
                directory_pins[path] = _directory_pin(owner.info(fd))
        verify_files()
        final_directory_pins = {}
        for path in ordered:
            with directory(path) as fd:
                final_directory_pins[path] = fd_observation._stat_tuple(owner.info(fd))
        guard()
        expected_root = fd_observation._stat_tuple(owner.info(root_fd))
        try:
            result = trees.observe_extracted_toolchain_tree(
                manifest, expected_manifest_sha256=expected_manifest_sha256,
                tree_directory=destination_directory, deadline=deadline, monotonic=monotonic,
            )
        except trees.StaticPythonToolchainTreeObservationError as exc:
            for reason in ("wall_timeout", "clock_invalid"):
                if exc.reason == "static_python_toolchain_tree_observation_" + reason:
                    raise StaticPythonToolchainCopyError(reason) from exc
            raise StaticPythonToolchainCopyError("observer_failed") from exc
        checkpoint()
        if (type(result) is not StaticPythonToolchainObservation
                or type(result.canonical_json) is not bytes
                or not 0 < len(result.canonical_json) <= trees.MAX_TOOLCHAIN_TREE_OBSERVATION_BYTES
                or hashlib.sha256(result.canonical_json).hexdigest() != result.observation_sha256):
            _fail("observer_failed")
        record = result.to_dict()
        if (result.manifest_json != manifest or result.manifest_sha256 != expected_manifest_sha256
                or record["tree_identity"] != dict(zip((
                    "device", "inode", "raw_mode", "nlink", "size", "mtime_ns", "ctime_ns",
                ), expected_root, strict=True))
                or type(record["claims"]) is not dict
                or set(record["claims"]) != set(trees._CLAIMS)
                or any(value is not False for value in record["claims"].values())):
            _fail("observer_failed")
        # Caller clocks can perform work: after the final callback recheck
        # original identities without another callback, then charge real time
        # for this sweep and cleanup to that original budget observation.
        final_started = time.perf_counter()
        final_now = checkpoint()

        def final_clock() -> float:
            elapsed = time.perf_counter() - final_started
            if not math.isfinite(elapsed) or elapsed < 0:
                _fail("clock_invalid")
            return final_now + elapsed

        def final_checkpoint() -> None:
            if final_clock() >= deadline:
                _fail("wall_timeout")

        verify_files(clock=False, final_checkpoint=final_checkpoint)
        for path in ordered:
            final_checkpoint()
            with directory(path, clock=False) as fd:
                expected = final_directory_pins[path]
                if fd_observation._stat_tuple(owner.info(fd)) != expected:
                    _fail("identity_drift")
                try:
                    fd_observation._list_children(
                        fd, children[path], deadline=deadline, monotonic=final_clock,
                        reason="directory_inventory_mismatch",
                    )
                except fd_observation.CandidateBuildSourceObservationError as exc:
                    if exc.reason == "static_python_candidate_source_observation_wall_timeout":
                        raise StaticPythonToolchainCopyError("wall_timeout") from exc
                    raise StaticPythonToolchainCopyError("identity_drift") from exc
                if fd_observation._stat_tuple(owner.info(fd)) != expected:
                    _fail("identity_drift")
            final_checkpoint()
        guard(clock=False)
        if fd_observation._stat_tuple(owner.info(root_fd)) != expected_root:
            _fail("identity_drift")
        owner.cleanup(None)
        final_checkpoint()
        return result
    except StaticPythonToolchainCopyError as exc:
        primary = exc
        raise
    except (OSError, KeyError, TypeError, ValueError, OverflowError) as exc:
        primary = StaticPythonToolchainCopyError("copy_failed")
        raise primary from exc
    except BaseException as exc:
        primary = exc
        raise
    finally:
        owner.cleanup(primary)


__all__ = ["StaticPythonToolchainCopyError"]
