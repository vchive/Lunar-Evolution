"""Bounded observation of a local static-Python archive.

This module is the first real-input gate for Feature189.  A path is opened once
through private directory descriptors, read into an immutable compressed-byte
snapshot, and then closed.  Tar/XZ parsing consumes only that snapshot; it never
reopens a path.  The parser intentionally accepts a small USTAR grammar and
rejects links, devices, sparse entries, PAX/GNU extensions and path
normalization.  Signature verification, extraction and publication are separate
gates and remain unperformed here.
"""

from __future__ import annotations

import hashlib
import json
import lzma
import math
import os
import stat
import sys
import tarfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from .profile import CPYTHON_ARCHIVE, ZIG_ARCHIVE
from .verified_inputs import (
    StaticPythonArchiveMember,
    StaticPythonExtractionManifest,
    validate_static_python_extraction_manifest,
)

ARCHIVE_OBSERVATION_SCHEMA = "lunar-static-python-archive-observation-v1"
MAX_COMPRESSED_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_XZ_MEMORY_BYTES = 256 * 1024 * 1024
MAX_TAR_STREAM_BYTES = 512 * 1024 * 1024
MAX_TAR_MEMBERS = 65_536
MAX_TAR_HEADER_BYTES = 512
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_TOTAL_FILE_BYTES = 1024 * 1024 * 1024
_READ_CHUNK = 64 * 1024
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


class StaticPythonArchiveObservationError(ValueError):
    """Fixed refusal code without caller paths or archive contents in messages."""

    def __init__(self, reason: str) -> None:
        self.reason = "static_python_archive_observation_" + reason
        super().__init__(self.reason)


def _fail(reason: str) -> NoReturn:
    raise StaticPythonArchiveObservationError(reason)


@dataclass(frozen=True, slots=True)
class ArchiveSourceIdentity:
    device: int
    inode: int
    size: int
    mode: int
    mtime_ns: int
    ctime_ns: int


@dataclass(frozen=True, slots=True)
class StaticPythonArchiveSnapshot:
    """The only bytes consumed by the tar observer after local acquisition."""

    archive: str
    root: str
    version: str
    expected_size: int
    expected_sha256: str
    archive_size: int
    archive_sha256: str
    compressed_bytes: bytes
    source_identity: ArchiveSourceIdentity | None
    profile_pin_verified: bool
    signature_verification: str
    snapshot_sha256: str


@dataclass(frozen=True, slots=True)
class StaticPythonArchiveObservation:
    """Actual member bytes and canonical metadata observed from one snapshot."""

    archive: str
    root: str
    version: str
    archive_sha256: str
    snapshot_sha256: str
    members: tuple[StaticPythonArchiveMember, ...]
    total_bytes: int
    manifest_json: bytes
    manifest_sha256: str
    metadata_validation: str
    source_preimages_checked: bool
    signature_verification: str

    def to_manifest(self) -> dict[str, object]:
        """Return a detached manifest projection for a later publication gate."""
        return {
            "schema": "lunar-static-python-extraction-manifest-v1",
            "archive": self.archive,
            "root": self.root,
            "archive_sha256": self.archive_sha256,
            "members": [
                {"path": item.path, "kind": item.kind, "size": item.size,
                 "mode": item.mode, "sha256": item.sha256}
                for item in self.members
            ],
        }


@dataclass(frozen=True, slots=True)
class _Profile:
    archive: str
    root: str
    version: str
    size: int
    sha256: str


_PROFILES = {
    "cpython": _Profile("cpython", CPYTHON_ARCHIVE["root"], "3.13.12",
                        CPYTHON_ARCHIVE["size"], CPYTHON_ARCHIVE["sha256"]),
    "zig": _Profile("zig", ZIG_ARCHIVE["root"], "0.16.0",
                    ZIG_ARCHIVE["size"], ZIG_ARCHIVE["sha256"]),
}


def _profile(archive: object) -> _Profile:
    if type(archive) is not str or archive not in _PROFILES:
        _fail("archive_invalid")
    return _PROFILES[archive]


def _checkpoint(checkpoint: Callable[[], None] | None) -> None:
    if checkpoint is not None:
        try:
            checkpoint()
        except StaticPythonArchiveObservationError:
            raise
        except BaseException as exc:
            raise StaticPythonArchiveObservationError("checkpoint_failed") from exc


def _identity(info: os.stat_result) -> ArchiveSourceIdentity:
    return ArchiveSourceIdentity(
        info.st_dev, info.st_ino, info.st_size, stat.S_IMODE(info.st_mode),
        info.st_mtime_ns, info.st_ctime_ns,
    )


def _same_identity(first: ArchiveSourceIdentity, info: os.stat_result) -> bool:
    return first == _identity(info)


def _open_parent(path: str, checkpoint: Callable[[], None] | None) -> tuple[int, str]:
    """Open every parent through O_NOFOLLOW descriptors; return parent/name."""
    if type(path) is not str or not path or len(path.encode("utf-8")) > 4096:
        _fail("path_invalid")
    absolute = path.startswith("/")
    components = path.split("/")[1:] if absolute else path.split("/")
    if (len(components) > 64 or any(part in {"", ".", ".."} for part in components)
            or "\x00" in path):
        _fail("path_invalid")
    _checkpoint(checkpoint)
    directory = os.open("/" if absolute else ".", _DIRECTORY_FLAGS)
    try:
        for component in components[:-1]:
            _checkpoint(checkpoint)
            child = os.open(component, _DIRECTORY_FLAGS, dir_fd=directory)
            previous = directory
            directory = child
            try:
                os.close(previous)
            except OSError as exc:
                # The previous descriptor's close state is unknown; do not
                # retry it. The new descriptor is still owned for cleanup.
                raise StaticPythonArchiveObservationError("cleanup_unknown") from exc
        return directory, components[-1]
    except BaseException:
        try:
            os.close(directory)
        except OSError:
            pass  # Preserve the primary refusal after attempting known cleanup.
        raise


def _read_fd(fd: int, size: int, checkpoint: Callable[[], None] | None) -> bytes:
    chunks: list[bytes] = []
    offset = 0
    while offset < size:
        _checkpoint(checkpoint)
        wanted = min(_READ_CHUNK, size - offset)
        chunk = os.pread(fd, wanted, offset)
        if type(chunk) is not bytes or not chunk or len(chunk) > wanted:
            _fail("archive_read_failed")
        chunks.append(chunk)
        offset += len(chunk)
        _checkpoint(checkpoint)
    _checkpoint(checkpoint)
    if os.pread(fd, 1, size):
        _fail("archive_size_drift")
    return b"".join(chunks)


def _snapshot_bytes(raw: object, profile: _Profile, *, require_profile: bool) -> StaticPythonArchiveSnapshot:
    if type(require_profile) is not bool:
        _fail("profile_flag_invalid")
    if type(raw) is not bytes:
        _fail("archive_bytes_invalid")
    if not 0 < len(raw) <= MAX_COMPRESSED_ARCHIVE_BYTES:
        _fail("archive_size_invalid")
    digest = hashlib.sha256(raw).hexdigest()
    pin_verified = len(raw) == profile.size and digest == profile.sha256
    if require_profile and not pin_verified:
        _fail("archive_pin_mismatch")
    return StaticPythonArchiveSnapshot(
        archive=profile.archive, root=profile.root, version=profile.version,
        expected_size=profile.size, expected_sha256=profile.sha256,
        archive_size=len(raw), archive_sha256=digest, compressed_bytes=raw,
        source_identity=None, profile_pin_verified=False,
        signature_verification="not-performed", snapshot_sha256=digest,
    )


def snapshot_archive_bytes(raw: bytes, archive: str, *, require_profile: bool = True) -> StaticPythonArchiveSnapshot:
    """Make an immutable snapshot from already supplied bytes; no I/O occurs.

    This seam may check the pin but does not establish path acquisition. It
    always carries ``profile_pin_verified=False``; only ``snapshot_archive``
    can return an acquired, profile-verified snapshot.
    """
    return _snapshot_bytes(raw, _profile(archive), require_profile=require_profile)


def snapshot_inert_archive_bytes(raw: bytes, archive: str) -> StaticPythonArchiveSnapshot:
    """Named test/fixture seam for local tar grammar tests with synthetic bytes."""
    return snapshot_archive_bytes(raw, archive, require_profile=False)


def snapshot_archive(
    path: str | Path,
    archive: str,
    *,
    deadline: float | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> StaticPythonArchiveSnapshot:
    """Acquire one fixed archive through O_NOFOLLOW parent and file descriptors."""
    profile = _profile(archive)
    if (type(deadline) not in {float, type(None)}
            or deadline is not None and (not math.isfinite(deadline) or deadline <= 0)):
        _fail("deadline_invalid")
    def check_deadline() -> None:
        current = monotonic()
        if type(current) not in {float, int} or not math.isfinite(current):
            _fail("clock_invalid")
        if deadline is not None and current >= deadline:
            _fail("wall_timeout")

    checkpoint = None if deadline is None else check_deadline
    parent = None
    fd = None
    try:
        try:
            if type(path) not in {str, type(Path())}:
                _fail("path_invalid")
            parent, name = _open_parent(str(path), checkpoint)
            _checkpoint(checkpoint)
            fd = os.open(name, _FILE_FLAGS, dir_fd=parent)
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode):
                _fail("archive_not_regular")
            if before.st_size != profile.size:
                _fail("archive_size_mismatch")
            original = _identity(before)
            named = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if not _same_identity(original, named):
                _fail("archive_identity_drift")
            raw = _read_fd(fd, profile.size, checkpoint)
            after = os.fstat(fd)
            named = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if not _same_identity(original, after) or not _same_identity(original, named):
                _fail("archive_identity_drift")
            digest = hashlib.sha256(raw).hexdigest()
            if digest != profile.sha256:
                _fail("archive_sha256_mismatch")
            snapshot = _snapshot_bytes(raw, profile, require_profile=True)
            return StaticPythonArchiveSnapshot(
                archive=snapshot.archive, root=snapshot.root, version=snapshot.version,
                expected_size=snapshot.expected_size, expected_sha256=snapshot.expected_sha256,
                archive_size=snapshot.archive_size, archive_sha256=snapshot.archive_sha256,
                compressed_bytes=snapshot.compressed_bytes, source_identity=original,
                profile_pin_verified=True,
                signature_verification=snapshot.signature_verification,
                snapshot_sha256=snapshot.snapshot_sha256,
            )
        except StaticPythonArchiveObservationError:
            raise
        except (OSError, ValueError, TypeError) as exc:
            raise StaticPythonArchiveObservationError("archive_read_failed") from exc
    finally:
        cleanup_error: OSError | None = None
        if fd is not None:
            try:
                os.close(fd)
            except OSError as exc:
                cleanup_error = exc
        if parent is not None:
            try:
                os.close(parent)
            except OSError as exc:
                if cleanup_error is None:
                    cleanup_error = exc
        # Keep the primary refusal if acquisition failed; surface cleanup only
        # after an otherwise successful acquisition.
        if cleanup_error is not None and sys.exc_info()[0] is None:
            raise StaticPythonArchiveObservationError("cleanup_unknown") from cleanup_error


def _decompress(snapshot: StaticPythonArchiveSnapshot) -> bytes:
    source = snapshot.compressed_bytes
    if len(source) > MAX_COMPRESSED_ARCHIVE_BYTES:
        _fail("compressed_budget_exceeded")
    decoder = lzma.LZMADecompressor(format=lzma.FORMAT_XZ, memlimit=MAX_XZ_MEMORY_BYTES)
    result = bytearray()
    for start in range(0, len(source), _READ_CHUNK):
        chunk = source[start:start + _READ_CHUNK]
        supplied_end = start + len(chunk)
        while True:
            try:
                output = decoder.decompress(chunk, max_length=_READ_CHUNK)
            except (lzma.LZMAError, EOFError) as exc:
                raise StaticPythonArchiveObservationError("xz_invalid") from exc
            result.extend(output)
            if len(result) > MAX_TAR_STREAM_BYTES:
                _fail("tar_stream_budget_exceeded")
            if decoder.eof:
                if decoder.unused_data or supplied_end < len(source):
                    _fail("xz_trailing_data")
                break
            elif decoder.needs_input:
                break
            else:
                # Drain output after max_length without advancing the input
                # cursor. Every EOF (including one reached while draining)
                # still checks unused bytes and later compressed chunks.
                chunk = b""
    if not decoder.eof:
        _fail("xz_truncated")
    return bytes(result)


def _raw_path(tar_bytes: bytes, member: tarfile.TarInfo) -> str:
    offset = member.offset
    if type(offset) is not int or offset < 0 or offset + MAX_TAR_HEADER_BYTES > len(tar_bytes):
        _fail("tar_header_invalid")
    header = tar_bytes[offset:offset + MAX_TAR_HEADER_BYTES]
    # USTAR magic/version is deliberately narrower than tarfile's default
    # GNU/PAX-compatible reader.
    if header[257:263] != b"ustar\x00" or header[263:265] != b"00":
        _fail("tar_grammar_unsupported")
    name_raw = _zero_terminated_field(header, 0, 100)
    prefix_raw = _zero_terminated_field(header, 345, 500)
    try:
        name = name_raw.decode("utf-8")
        prefix = prefix_raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StaticPythonArchiveObservationError("member_path_invalid") from exc
    combined = f"{prefix}/{name}" if prefix else name
    if member.name != combined and not (
        member.isdir() and combined.endswith("/") and combined.count("/") == member.name.count("/") + 1
        and combined[:-1] == member.name
    ):
        _fail("member_path_normalized")
    return combined


def _zero_terminated_field(header: bytes, start: int, end: int) -> bytes:
    field = header[start:end]
    nul = field.find(b"\0")
    if nul < 0:
        return field
    if any(field[nul + 1:]):
        _fail("tar_text_unsupported")
    return field[:nul]


def _canonical_member_path(raw: str, root: str, *, directory: bool) -> str:
    if directory and raw.endswith("/"):
        raw = raw[:-1]
    if not raw or raw.startswith("/") or "\\" in raw or "//" in raw or "\x00" in raw:
        _fail("member_path_invalid")
    parts = raw.split("/")
    if parts[0] != root or len(parts) > 64 or any(part in {"", ".", ".."} for part in parts):
        _fail("member_path_invalid")
    if any(any(ord(char) < 0x20 or 0x7F <= ord(char) <= 0x9F for char in part) for part in parts):
        _fail("member_path_invalid")
    if any(":" in part for part in parts):
        _fail("member_path_invalid")
    return "/".join(parts)


def _tar_header(tar_bytes: bytes, cursor: int) -> tarfile.TarInfo:
    """Validate raw USTAR grammar before any library extension processing."""
    header = tar_bytes[cursor:cursor + 512]
    if len(header) != 512:
        _fail("tar_header_invalid")
    if header[257:263] != b"ustar\x00" or header[263:265] != b"00":
        _fail("tar_grammar_unsupported")
    if header[156:157] not in {b"0", b"5"}:
        _fail("member_type_unsupported")
    for start, end in ((0, 100), (157, 257), (265, 297), (297, 329), (345, 500)):
        field = header[start:end]
        if b"\0" in field and any(field[field.index(b"\0"):]):
            _fail("tar_text_unsupported")
    if any(header[500:512]):
        _fail("tar_grammar_unsupported")
    # USTAR octal fields only: tarfile also accepts GNU base-256 fields, which
    # would silently expand this deliberately small grammar.
    for start, end in ((100, 108), (108, 116), (116, 124), (124, 136), (136, 148),
                       (148, 156), (329, 337), (337, 345)):
        raw = header[start:end].lstrip(b" ")
        digit_count = 0
        while digit_count < len(raw) and raw[digit_count] in b"01234567":
            digit_count += 1
        if (not digit_count and start not in {329, 337}
                or any(char not in b"\0 " for char in raw[digit_count:])):
            _fail("tar_numeric_unsupported")
    try:
        member = tarfile.TarInfo.frombuf(header, "utf-8", "strict")
    except (tarfile.TarError, UnicodeError, ValueError) as exc:
        raise StaticPythonArchiveObservationError("tar_invalid") from exc
    member.offset = cursor
    member.offset_data = cursor + 512
    return member


def _member_bytes(tar_bytes: bytes, member: tarfile.TarInfo) -> str:
    if member.offset_data < 0 or member.offset_data + member.size > len(tar_bytes):
        _fail("member_bounds_invalid")
    digest = hashlib.sha256()
    count = 0
    while count < member.size:
        wanted = min(_READ_CHUNK, member.size - count)
        chunk = tar_bytes[member.offset_data + count:member.offset_data + count + wanted]
        if type(chunk) is not bytes or not chunk:
            _fail("member_size_drift")
        count += len(chunk)
        digest.update(chunk)
    if count != member.size:
        _fail("member_size_drift")
    return digest.hexdigest()


def observe_archive_snapshot(
    snapshot: StaticPythonArchiveSnapshot,
    *,
    expected_manifest_sha256: str | None = None,
    require_source_preimages: bool = False,
    require_profile: bool = True,
) -> StaticPythonArchiveObservation:
    """Observe actual member bytes from one immutable snapshot.

    A profile-verified observation invokes the existing metadata validator as a
    second layer. Inert snapshots may exercise tar grammar with
    ``require_profile=False``; their metadata status remains explicitly skipped.
    """
    if type(snapshot) is not StaticPythonArchiveSnapshot:
        _fail("snapshot_invalid")
    if type(require_profile) is not bool:
        _fail("profile_flag_invalid")
    if type(snapshot.profile_pin_verified) is not bool:
        _fail("snapshot_profile_drift")
    if (type(snapshot.signature_verification) is not str
            or snapshot.signature_verification != "not-performed"):
        _fail("signature_status_invalid")
    profile = _profile(snapshot.archive)
    if (any(type(value) is not str for value in (
            snapshot.root, snapshot.version, snapshot.expected_sha256,
            snapshot.archive_sha256, snapshot.snapshot_sha256))
            or type(snapshot.expected_size) is not int
            or type(snapshot.archive_size) is not int
            or type(snapshot.compressed_bytes) is not bytes
            or not 0 < len(snapshot.compressed_bytes) <= MAX_COMPRESSED_ARCHIVE_BYTES
            or snapshot.archive_size != len(snapshot.compressed_bytes)
            or snapshot.archive_sha256 != hashlib.sha256(snapshot.compressed_bytes).hexdigest()
            or snapshot.snapshot_sha256 != snapshot.archive_sha256):
        _fail("snapshot_integrity_invalid")
    source = snapshot.source_identity
    if source is not None and (
            type(source) is not ArchiveSourceIdentity
            or any(type(value) is not int for value in (
                source.device, source.inode, source.size, source.mode, source.mtime_ns,
                source.ctime_ns))
            or min(source.device, source.inode, source.size) < 0
            or source.size != snapshot.archive_size or source.mode & ~0o777):
        _fail("snapshot_integrity_invalid")
    if (snapshot.root != profile.root or snapshot.version != profile.version
            or snapshot.expected_size != profile.size
            or snapshot.expected_sha256 != profile.sha256):
        _fail("snapshot_profile_drift")
    if require_profile and (
            not snapshot.profile_pin_verified
            or type(snapshot.source_identity) is not ArchiveSourceIdentity
            or snapshot.archive_size != profile.size
            or snapshot.archive_sha256 != profile.sha256):
        _fail("archive_pin_mismatch")
    if type(require_source_preimages) is not bool:
        _fail("source_preimages_flag_invalid")
    tar_bytes = _decompress(snapshot)
    if len(tar_bytes) < 1024:
        _fail("tar_end_marker_missing")
    members: list[StaticPythonArchiveMember] = []
    paths: set[str] = set()
    total = 0
    cursor = 0
    while cursor + 512 <= len(tar_bytes):
        if tar_bytes[cursor:cursor + 512] == bytes(512):
            break
        if len(members) >= MAX_TAR_MEMBERS:
            _fail("member_count_exceeded")
        member = _tar_header(tar_bytes, cursor)
        raw_path = _raw_path(tar_bytes, member)
        is_dir = member.type == tarfile.DIRTYPE
        if type(member.mode) is not int or member.mode & ~0o777:
            _fail("member_mode_invalid")
        path = _canonical_member_path(raw_path, snapshot.root, directory=is_dir)
        if path in paths:
            _fail("member_duplicate_path")
        paths.add(path)
        if is_dir:
            if member.size != 0:
                _fail("directory_size_invalid")
            digest = None
        else:
            if member.size < 0 or member.size > MAX_FILE_BYTES:
                _fail("member_size_invalid")
            digest = _member_bytes(tar_bytes, member)
            total += member.size
            if total > MAX_TOTAL_FILE_BYTES:
                _fail("total_byte_budget_exceeded")
        members.append(StaticPythonArchiveMember(path, "directory" if is_dir else "file",
                                                 member.size, member.mode, digest))
        cursor = ((member.offset_data + member.size + 511) // 512) * 512
    remainder = tar_bytes[cursor:]
    if len(remainder) < 1024 or len(remainder) % 512 or any(remainder):
        _fail("tar_end_marker_invalid")
    if not members or not any(item.path == snapshot.root and item.kind == "directory" for item in members):
        _fail("root_directory_missing")
    by_path = {item.path: item for item in members}
    for path in by_path:
        parent = path.rpartition("/")[0]
        while parent:
            if parent in by_path and by_path[parent].kind != "directory":
                _fail("file_directory_collision")
            parent = parent.rpartition("/")[0]
    ordered = tuple(sorted(members, key=lambda item: item.path))
    manifest = {
        "schema": "lunar-static-python-extraction-manifest-v1", "archive": snapshot.archive,
        "root": snapshot.root, "archive_sha256": snapshot.archive_sha256,
        "members": [{"path": item.path, "kind": item.kind, "size": item.size,
                      "mode": item.mode, "sha256": item.sha256} for item in ordered],
    }
    manifest_json = json.dumps(manifest, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False, allow_nan=False).encode("utf-8")
    manifest_sha256 = hashlib.sha256(manifest_json).hexdigest()
    metadata_status = "skipped-inert-profile"
    source_checked = False
    if require_profile:
        if expected_manifest_sha256 is None:
            _fail("manifest_pin_required")
        try:
            validated: StaticPythonExtractionManifest = validate_static_python_extraction_manifest(
                manifest, expected_sha256=expected_manifest_sha256,
                require_source_preimages=require_source_preimages,
            )
        except Exception as exc:
            if isinstance(exc, StaticPythonArchiveObservationError):
                raise
            raise StaticPythonArchiveObservationError("metadata_manifest_invalid") from exc
        metadata_status = "validated"
        source_checked = validated.source_preimages_checked
    elif require_source_preimages:
        _fail("source_preimages_require_profile")
    return StaticPythonArchiveObservation(
        archive=snapshot.archive, root=snapshot.root, version=snapshot.version,
        archive_sha256=snapshot.archive_sha256, snapshot_sha256=snapshot.snapshot_sha256,
        members=ordered, total_bytes=total, manifest_json=manifest_json,
        manifest_sha256=manifest_sha256, metadata_validation=metadata_status,
        source_preimages_checked=source_checked,
        signature_verification=snapshot.signature_verification,
    )


__all__ = [
    "ARCHIVE_OBSERVATION_SCHEMA",
    "MAX_COMPRESSED_ARCHIVE_BYTES",
    "MAX_FILE_BYTES",
    "MAX_TAR_MEMBERS",
    "MAX_TAR_STREAM_BYTES",
    "MAX_TOTAL_FILE_BYTES",
    "MAX_XZ_MEMORY_BYTES",
    "ArchiveSourceIdentity",
    "StaticPythonArchiveObservation",
    "StaticPythonArchiveObservationError",
    "StaticPythonArchiveSnapshot",
    "observe_archive_snapshot",
    "snapshot_archive",
    "snapshot_archive_bytes",
    "snapshot_inert_archive_bytes",
]
