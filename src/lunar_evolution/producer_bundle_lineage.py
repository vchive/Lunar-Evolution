"""Bounded, opt-in lineage evidence for same-workspace producer batches.

This module is deliberately a data/evidence boundary.  It does not enable repeated
publication and is not consulted by the legacy transaction or recovery paths.  The
sidecars are create-only files under a system-derived batch directory; their own
digests never replace the independently retained snapshot pins.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PosixPath, WindowsPath
from typing import NoReturn

from . import _benchmark_files as _files
from ._candidate_workspace_io import DirectoryChain
from .candidate_evaluation_spec import strict_json
from .candidate_workspace_plan import CandidateWorkspaceError

LINEAGE_PROTOCOL = "lunar-producer-bundle-lineage-v1"
LINEAGE_SCHEMA_VERSION = "1"
MAX_LINEAGE_BATCHES = 8
MAX_LINEAGE_DESCRIPTOR_BYTES = 32 * 1024
MAX_LINEAGE_SNAPSHOT_BYTES = 16 * 1024 * 1024
MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES = 64 * 1024 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class ProducerBundleLineageError(ValueError):
    """Fixed-code refusal for lineage evidence, without filesystem side effects."""

    def __init__(self, code: str) -> None:
        self.code = "producer_bundle_lineage_" + code
        super().__init__(self.code)


def _fail(code: str) -> NoReturn:
    raise ProducerBundleLineageError(code)


def _canonical(value: object) -> bytes:
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        raise ProducerBundleLineageError("canonical_invalid") from exc
    if len(raw) > MAX_LINEAGE_DESCRIPTOR_BYTES:
        _fail("descriptor_too_large")
    return raw


def _sha(value: object, code: str = "digest_invalid") -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        _fail(code)
    return value


def _id(value: object, code: str = "identity_invalid") -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        _fail(code)
    return value


def _int(value: object, code: str, *, maximum: int = 2**64 - 1) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        _fail(code)
    return value


def _fields(value: object, expected: frozenset[str], code: str) -> dict[str, object]:
    if type(value) is not dict or set(value) != expected:
        _fail(code)
    return value


def _absolute_path(value: object) -> Path:
    if type(value) not in {str, Path, PosixPath, WindowsPath}:
        _fail("path_invalid")
    try:
        return _files.absolute_path(value)
    except _files.BenchmarkFileError as exc:
        raise ProducerBundleLineageError("path_invalid") from exc


@dataclass(frozen=True, slots=True)
class LineageSnapshotPin:
    """Independent bytes and inode/stat observation for one archive/state snapshot."""

    name: str
    sha256: str
    size: int
    device: int
    inode: int
    parent_device: int
    parent_inode: int
    mode: int = 0o600
    nlink: int = 1
    mtime_ns: int = 0
    ctime_ns: int = 0

    def __post_init__(self) -> None:
        _id(self.name, "snapshot_name_invalid")
        _sha(self.sha256, "snapshot_digest_invalid")
        _int(self.size, "snapshot_size_invalid", maximum=MAX_LINEAGE_SNAPSHOT_BYTES)
        _int(self.device, "snapshot_device_invalid")
        _int(self.inode, "snapshot_inode_invalid")
        if self.inode == 0:
            _fail("snapshot_inode_invalid")
        _int(self.parent_device, "snapshot_parent_device_invalid")
        _int(self.parent_inode, "snapshot_parent_inode_invalid")
        if self.parent_inode == 0:
            _fail("snapshot_parent_inode_invalid")
        _int(self.mode, "snapshot_mode_invalid", maximum=0o7777)
        if self.mode != 0o600:
            _fail("snapshot_mode_invalid")
        if self.nlink != 1:
            _fail("snapshot_nlink_invalid")
        _int(self.nlink, "snapshot_nlink_invalid")
        _int(self.mtime_ns, "snapshot_mtime_invalid")
        _int(self.ctime_ns, "snapshot_ctime_invalid")

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "sha256": self.sha256, "size": self.size,
                "device": self.device, "inode": self.inode, "parent_device": self.parent_device,
                "parent_inode": self.parent_inode, "mode": self.mode,
                "nlink": self.nlink, "mtime_ns": self.mtime_ns, "ctime_ns": self.ctime_ns}

    @classmethod
    def from_dict(cls, value: object) -> LineageSnapshotPin:
        return cls(**_fields(value, frozenset({"name", "sha256", "size", "device", "inode", "parent_device", "parent_inode", "mode", "nlink", "mtime_ns", "ctime_ns"}), "snapshot_schema_invalid"))  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class ProducerLineageBeforeIntent:
    run_id: str
    journal_id: str
    ordinal: int
    predecessor_terminal_sha256: str | None
    predecessor_lineage_sha256: str | None
    archive: LineageSnapshotPin
    state: LineageSnapshotPin
    descriptor_sha256: str | None = None
    kind: str = "before"
    schema_version: str = LINEAGE_SCHEMA_VERSION
    protocol: str = LINEAGE_PROTOCOL

    def __post_init__(self) -> None:
        _id(self.run_id); _id(self.journal_id); _int(self.ordinal, "ordinal_invalid", maximum=MAX_LINEAGE_BATCHES - 1)
        if type(self.archive) is not LineageSnapshotPin or type(self.state) is not LineageSnapshotPin:
            _fail("snapshot_pin_invalid")
        for value in (self.predecessor_terminal_sha256, self.predecessor_lineage_sha256):
            if value is not None: _sha(value, "predecessor_digest_invalid")
        if self.kind != "before" or self.schema_version != LINEAGE_SCHEMA_VERSION or self.protocol != LINEAGE_PROTOCOL:
            _fail("schema_invalid")
        if self.ordinal == 0 and (self.predecessor_terminal_sha256 is not None or self.predecessor_lineage_sha256 is not None):
            _fail("genesis_predecessor_invalid")
        if self.ordinal > 0 and (self.predecessor_terminal_sha256 is None or self.predecessor_lineage_sha256 is None):
            _fail("predecessor_missing")
        expected = hashlib.sha256(_canonical(self._payload())).hexdigest()
        if self.descriptor_sha256 is None:
            object.__setattr__(self, "descriptor_sha256", expected)
        elif _sha(self.descriptor_sha256, "descriptor_digest_invalid") != expected:
            _fail("descriptor_digest_mismatch")

    def _payload(self) -> dict[str, object]:
        return {"schema_version": self.schema_version, "protocol": self.protocol, "kind": self.kind,
                "run_id": self.run_id, "journal_id": self.journal_id, "ordinal": self.ordinal,
                "predecessor_terminal_sha256": self.predecessor_terminal_sha256,
                "predecessor_lineage_sha256": self.predecessor_lineage_sha256,
                "archive": self.archive.to_dict(), "state": self.state.to_dict()}

    def to_dict(self) -> dict[str, object]:
        payload = self._payload()
        payload["descriptor_sha256"] = self.descriptor_sha256 or hashlib.sha256(_canonical(payload)).hexdigest()
        return payload

    def to_json(self) -> bytes:
        return _canonical(self.to_dict())

    def digest(self) -> str:
        return self.descriptor_sha256 or hashlib.sha256(_canonical(self._payload())).hexdigest()

    @classmethod
    def from_dict(cls, value: object) -> ProducerLineageBeforeIntent:
        raw = dict(_fields(value, frozenset({"schema_version", "protocol", "kind", "run_id", "journal_id", "ordinal", "predecessor_terminal_sha256", "predecessor_lineage_sha256", "archive", "state", "descriptor_sha256"}), "before_schema_invalid"))
        given = _sha(raw["descriptor_sha256"], "descriptor_digest_invalid")
        body = dict(raw); body.pop("descriptor_sha256")
        if hashlib.sha256(_canonical(body)).hexdigest() != given: _fail("descriptor_digest_mismatch")
        raw["archive"] = LineageSnapshotPin.from_dict(raw["archive"])
        raw["state"] = LineageSnapshotPin.from_dict(raw["state"])
        return cls(**raw)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class ProducerLineageStagedTransition:
    run_id: str
    journal_id: str
    ordinal: int
    before_sha256: str
    journal_sha256: str
    manifest_sha256: str
    archive_after_sha256: str
    state_after_sha256: str
    candidate_ids: tuple[str, ...]
    descriptor_sha256: str | None = None
    kind: str = "staged"
    schema_version: str = LINEAGE_SCHEMA_VERSION
    protocol: str = LINEAGE_PROTOCOL

    def __post_init__(self) -> None:
        _id(self.run_id); _id(self.journal_id); _int(self.ordinal, "ordinal_invalid", maximum=MAX_LINEAGE_BATCHES - 1)
        for value in (self.before_sha256, self.journal_sha256, self.manifest_sha256, self.archive_after_sha256, self.state_after_sha256): _sha(value)
        if self.kind != "staged" or self.schema_version != LINEAGE_SCHEMA_VERSION or self.protocol != LINEAGE_PROTOCOL: _fail("schema_invalid")
        if type(self.candidate_ids) is not tuple or not self.candidate_ids or len(self.candidate_ids) > 32: _fail("candidates_invalid")
        for value in self.candidate_ids: _id(value, "candidate_invalid")
        if len(set(self.candidate_ids)) != len(self.candidate_ids): _fail("candidates_invalid")
        expected = hashlib.sha256(_canonical(self._payload())).hexdigest()
        if self.descriptor_sha256 is None:
            object.__setattr__(self, "descriptor_sha256", expected)
        elif _sha(self.descriptor_sha256, "descriptor_digest_invalid") != expected:
            _fail("descriptor_digest_mismatch")

    def _payload(self) -> dict[str, object]:
        return {"schema_version": self.schema_version, "protocol": self.protocol, "kind": self.kind,
                "run_id": self.run_id, "journal_id": self.journal_id, "ordinal": self.ordinal,
                "before_sha256": self.before_sha256, "journal_sha256": self.journal_sha256,
                "manifest_sha256": self.manifest_sha256, "archive_after_sha256": self.archive_after_sha256,
                "state_after_sha256": self.state_after_sha256, "candidate_ids": list(self.candidate_ids)}

    def to_dict(self) -> dict[str, object]:
        payload = self._payload(); payload["descriptor_sha256"] = self.descriptor_sha256 or hashlib.sha256(_canonical(payload)).hexdigest(); return payload

    def to_json(self) -> bytes:
        return _canonical(self.to_dict())

    def digest(self) -> str:
        return self.descriptor_sha256 or hashlib.sha256(_canonical(self._payload())).hexdigest()

    @classmethod
    def from_dict(cls, value: object) -> ProducerLineageStagedTransition:
        raw = dict(_fields(value, frozenset({"schema_version", "protocol", "kind", "run_id", "journal_id", "ordinal", "before_sha256", "journal_sha256", "manifest_sha256", "archive_after_sha256", "state_after_sha256", "candidate_ids", "descriptor_sha256"}), "staged_schema_invalid"))
        given = _sha(raw["descriptor_sha256"], "descriptor_digest_invalid"); body = dict(raw); body.pop("descriptor_sha256")
        if hashlib.sha256(_canonical(body)).hexdigest() != given: _fail("descriptor_digest_mismatch")
        ids = raw["candidate_ids"]
        if not isinstance(ids, list): _fail("candidates_invalid")
        raw["candidate_ids"] = tuple(ids)
        return cls(**raw)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class ProducerLineageTerminal:
    run_id: str
    journal_id: str
    ordinal: int
    staged_sha256: str
    terminal_sha256: str
    archive_after_sha256: str
    state_after_sha256: str
    descriptor_sha256: str | None = None
    kind: str = "terminal"
    schema_version: str = LINEAGE_SCHEMA_VERSION
    protocol: str = LINEAGE_PROTOCOL

    def __post_init__(self) -> None:
        _id(self.run_id); _id(self.journal_id); _int(self.ordinal, "ordinal_invalid", maximum=MAX_LINEAGE_BATCHES - 1)
        for value in (self.staged_sha256, self.terminal_sha256, self.archive_after_sha256, self.state_after_sha256): _sha(value)
        if self.kind != "terminal" or self.schema_version != LINEAGE_SCHEMA_VERSION or self.protocol != LINEAGE_PROTOCOL: _fail("schema_invalid")
        expected = hashlib.sha256(_canonical(self._payload())).hexdigest()
        if self.descriptor_sha256 is None:
            object.__setattr__(self, "descriptor_sha256", expected)
        elif _sha(self.descriptor_sha256, "descriptor_digest_invalid") != expected:
            _fail("descriptor_digest_mismatch")

    def _payload(self) -> dict[str, object]:
        return {"schema_version": self.schema_version, "protocol": self.protocol, "kind": self.kind,
                "run_id": self.run_id, "journal_id": self.journal_id, "ordinal": self.ordinal,
                "staged_sha256": self.staged_sha256, "terminal_sha256": self.terminal_sha256,
                "archive_after_sha256": self.archive_after_sha256, "state_after_sha256": self.state_after_sha256}

    def to_dict(self) -> dict[str, object]:
        payload = self._payload(); payload["descriptor_sha256"] = self.descriptor_sha256 or hashlib.sha256(_canonical(payload)).hexdigest(); return payload

    def to_json(self) -> bytes:
        return _canonical(self.to_dict())

    def digest(self) -> str:
        return self.descriptor_sha256 or hashlib.sha256(_canonical(self._payload())).hexdigest()

    @classmethod
    def from_dict(cls, value: object) -> ProducerLineageTerminal:
        raw = dict(_fields(value, frozenset({"schema_version", "protocol", "kind", "run_id", "journal_id", "ordinal", "staged_sha256", "terminal_sha256", "archive_after_sha256", "state_after_sha256", "descriptor_sha256"}), "terminal_schema_invalid"))
        given = _sha(raw["descriptor_sha256"], "descriptor_digest_invalid"); body = dict(raw); body.pop("descriptor_sha256")
        if hashlib.sha256(_canonical(body)).hexdigest() != given: _fail("descriptor_digest_mismatch")
        return cls(**raw)  # type: ignore[arg-type]


def parse_lineage_descriptor(value: Mapping[str, object] | bytes | str | os.PathLike[str]) -> ProducerLineageBeforeIntent | ProducerLineageStagedTransition | ProducerLineageTerminal:
    encoded = None
    if type(value) is dict:
        _plain_json(value)
        raw = value
    elif type(value) in {bytes, str}:
        try:
            encoded = value if type(value) is bytes else value.encode("utf-8")
            raw = strict_json(encoded, MAX_LINEAGE_DESCRIPTOR_BYTES)
        except Exception as exc: raise ProducerBundleLineageError("json_invalid") from exc
    else:
        if type(value) not in {Path, PosixPath, WindowsPath}:
            _fail("schema_invalid")
        try:
            encoded = _files.read_regular_file(_absolute_path(value), MAX_LINEAGE_DESCRIPTOR_BYTES)
            raw = strict_json(encoded, MAX_LINEAGE_DESCRIPTOR_BYTES)
        except Exception as exc: raise ProducerBundleLineageError("read_invalid") from exc
    if not isinstance(raw, dict): _fail("schema_invalid")
    if encoded is not None and encoded != _canonical(raw):
        _fail("descriptor_noncanonical")
    kind = raw.get("kind")
    if kind == "before": return ProducerLineageBeforeIntent.from_dict(raw)
    if kind == "staged": return ProducerLineageStagedTransition.from_dict(raw)
    if kind == "terminal": return ProducerLineageTerminal.from_dict(raw)
    _fail("kind_invalid")


def _plain_json(value: object, *, depth: int = 0) -> None:
    if depth > 6:
        _fail("descriptor_too_deep")
    if type(value) is dict:
        if len(value) > 32 or any(type(key) is not str for key in value):
            _fail("schema_invalid")
        for item in value.values():
            _plain_json(item, depth=depth + 1)
    elif type(value) is list:
        if len(value) > 32:
            _fail("schema_invalid")
        for item in value:
            _plain_json(item, depth=depth + 1)
    elif value is not None and type(value) not in {str, int}:
        _fail("schema_invalid")


def lineage_directory(workspace: str | Path, journal_id: str) -> Path:
    """Return only the system-derived lineage directory; caller cannot supply a sibling path."""
    _id(journal_id, "journal_id_invalid")
    root = _absolute_path(workspace)
    return root / "evolution" / "producer-batches" / journal_id / "lineage"


def _stat_tuple(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_size, stat.S_IMODE(info.st_mode),
            info.st_nlink, info.st_mtime_ns, info.st_ctime_ns)


def _observe_file(path: Path, *, name: str, maximum: int,
                  expected_pin: LineageSnapshotPin | None = None) -> tuple[bytes, LineageSnapshotPin]:
    if expected_pin is not None:
        if type(expected_pin) is not LineageSnapshotPin:
            _fail("snapshot_pin_invalid")
        expected_pin = LineageSnapshotPin.from_dict(expected_pin.to_dict())
    chain = None
    descriptor = -1
    try:
        chain = DirectoryChain(path.parent, "producer_bundle_lineage_path_invalid")
        parent = os.fstat(chain.fd)
        before = os.stat(path.name, dir_fd=chain.fd, follow_symlinks=False)
        if (not stat.S_ISREG(before.st_mode) or stat.S_IMODE(before.st_mode) != 0o600
                or before.st_nlink != 1 or before.st_size > maximum):
            _fail("snapshot_identity_invalid")
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                             dir_fd=chain.fd)
        if _stat_tuple(before) != _stat_tuple(os.fstat(descriptor)):
            _fail("snapshot_identity_drift")
        chunks: list[bytes] = []
        remaining = maximum + 1
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk); remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > maximum:
            _fail("snapshot_too_large")
        after = os.fstat(descriptor)
        named = os.stat(path.name, dir_fd=chain.fd, follow_symlinks=False)
        if (_stat_tuple(before) != _stat_tuple(after) or _stat_tuple(after) != _stat_tuple(named)
                or len(raw) != named.st_size):
            _fail("snapshot_identity_drift")
        chain.check()
        pin = LineageSnapshotPin(name=name, sha256=hashlib.sha256(raw).hexdigest(), size=len(raw),
                                device=named.st_dev, inode=named.st_ino, mode=stat.S_IMODE(named.st_mode),
                                parent_device=parent.st_dev, parent_inode=parent.st_ino,
                                nlink=named.st_nlink, mtime_ns=named.st_mtime_ns, ctime_ns=named.st_ctime_ns)
        if expected_pin is not None and pin != expected_pin:
            _fail("snapshot_pin_drift")
        return raw, pin
    except ProducerBundleLineageError:
        raise
    except (CandidateWorkspaceError, OSError, ValueError) as exc:
        raise ProducerBundleLineageError("snapshot_read_invalid") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if chain is not None:
            chain.close()


def capture_lineage_snapshot_pin(path: str | Path, *, name: str) -> LineageSnapshotPin:
    """Read-only observation; it is not a grant to admit a successor batch."""
    _id(name, "snapshot_name_invalid")
    return _observe_file(_absolute_path(path), name=name, maximum=MAX_LINEAGE_SNAPSHOT_BYTES)[1]


def verify_lineage_snapshot_pin(path: str | Path, pin: LineageSnapshotPin) -> None:
    """Require independently held exact bytes, inode, mode, link count and timestamps."""
    if type(pin) is not LineageSnapshotPin:
        _fail("snapshot_pin_invalid")
    _observe_file(_absolute_path(path), name=pin.name, maximum=MAX_LINEAGE_SNAPSHOT_BYTES, expected_pin=pin)


def _create_lineage_file(workspace: str | Path, journal_id: str, *, filename: str, raw: bytes,
                         expected_file_pin: LineageSnapshotPin | None = None) -> tuple[Path, LineageSnapshotPin]:
    batch = lineage_directory(workspace, journal_id).parent
    path = batch / "lineage" / filename
    if expected_file_pin is not None:
        if type(expected_file_pin) is not LineageSnapshotPin:
            _fail("snapshot_pin_invalid")
        expected_file_pin = LineageSnapshotPin.from_dict(expected_file_pin.to_dict())
    batch_chain = chain = None
    descriptor = -1
    try:
        # Only the lineage leaf may be created. Original workspace and batch must exist.
        batch_chain = DirectoryChain(batch, "producer_bundle_lineage_path_invalid")
        if expected_file_pin is not None:
            if type(expected_file_pin) is not LineageSnapshotPin:
                _fail("snapshot_pin_invalid")
            existing, pin = _observe_file(path, name=filename, maximum=MAX_LINEAGE_SNAPSHOT_BYTES,
                                         expected_pin=expected_file_pin)
            if existing != raw:
                _fail("descriptor_conflict")
            batch_chain.check()
            return path, pin
        try:
            os.mkdir("lineage", mode=0o700, dir_fd=batch_chain.fd)
            os.fsync(batch_chain.fd)
        except FileExistsError:
            pass
        batch_chain.check()
        chain = DirectoryChain(path.parent, "producer_bundle_lineage_path_invalid")
        try:
            os.stat(filename, dir_fd=chain.fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            _fail("original_file_pin_required")
        descriptor = os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                             0o600, dir_fd=chain.fd)
        created = os.fstat(descriptor)
        view = memoryview(raw)
        while view:
            chain.check(); batch_chain.check()
            count = os.write(descriptor, view)
            if count <= 0:
                _fail("write_failed")
            view = view[count:]
        os.fsync(descriptor)
        final = os.fstat(descriptor)
        named = os.stat(filename, dir_fd=chain.fd, follow_symlinks=False)
        if ((created.st_dev, created.st_ino) != (final.st_dev, final.st_ino)
                or _stat_tuple(final) != _stat_tuple(named) or not stat.S_ISREG(final.st_mode)
                or stat.S_IMODE(final.st_mode) != 0o600 or final.st_nlink != 1 or final.st_size != len(raw)):
            _fail("snapshot_identity_drift")
        chain.check(); batch_chain.check(); os.fsync(chain.fd)
        retained_parent = os.fstat(chain.fd)
        observed, pin = _observe_file(path, name=filename, maximum=MAX_LINEAGE_SNAPSHOT_BYTES)
        if (observed != raw
                or (pin.device, pin.inode, pin.size, pin.mode, pin.nlink, pin.mtime_ns, pin.ctime_ns)
                != _stat_tuple(final)
                or (pin.parent_device, pin.parent_inode)
                != (retained_parent.st_dev, retained_parent.st_ino)
                or _stat_tuple(os.fstat(descriptor)) != _stat_tuple(final)
                or _stat_tuple(os.stat(filename, dir_fd=chain.fd, follow_symlinks=False))
                != _stat_tuple(final)):
            _fail("snapshot_identity_drift")
        chain.check(); batch_chain.check()
        return path, pin
    except ProducerBundleLineageError:
        raise
    except (CandidateWorkspaceError, OSError, ValueError) as exc:
        raise ProducerBundleLineageError("write_failed") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if chain is not None:
            chain.close()
        if batch_chain is not None:
            batch_chain.close()


def persist_lineage_snapshot(workspace: str | Path, journal_id: str, *, name: str, source: str | Path,
                             expected_pin: LineageSnapshotPin,
                             expected_file_pin: LineageSnapshotPin | None = None,
                             retained_bytes: int = 0) -> tuple[Path, LineageSnapshotPin]:
    """Copy independently pinned source bytes; return the destination's original file pin."""
    _id(journal_id, "journal_id_invalid"); _id(name, "snapshot_name_invalid")
    if type(expected_pin) is not LineageSnapshotPin or expected_pin.name != name:
        _fail("snapshot_pin_invalid")
    expected_pin = LineageSnapshotPin.from_dict(expected_pin.to_dict())
    _int(retained_bytes, "snapshot_aggregate_invalid", maximum=MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES)
    if retained_bytes + expected_pin.size > MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES:
        _fail("snapshot_aggregate_invalid")
    raw, _ = _observe_file(_absolute_path(source), name=name, maximum=MAX_LINEAGE_SNAPSHOT_BYTES,
                          expected_pin=expected_pin)
    result = _create_lineage_file(workspace, journal_id, filename=f"{name}.snapshot", raw=raw,
                                  expected_file_pin=expected_file_pin)
    verify_lineage_snapshot_pin(source, expected_pin)
    return result


def verify_persisted_lineage_snapshot(path: str | Path, pin: LineageSnapshotPin) -> None:
    """Validate the independently held destination pin, including its inode and stat."""
    verify_lineage_snapshot_pin(path, pin)


def persist_lineage_bytes_snapshot(
    workspace: str | Path, journal_id: str, *, name: str, raw: bytes,
    expected_sha256: str, retained_bytes: int = 0,
    expected_file_pin: LineageSnapshotPin | None = None,
) -> tuple[Path, LineageSnapshotPin]:
    """Retain exact caller-verified bytes, including an explicit empty genesis archive.

    This evidence helper does not observe absence or confer source authority.  The original
    owner must separately retain its verified live source or missing-archive association.
    Only the derived immutable snapshot is created; live archive/state files are untouched.
    """
    _id(journal_id, "journal_id_invalid"); _id(name, "snapshot_name_invalid")
    _sha(expected_sha256, "snapshot_digest_invalid")
    if type(raw) is not bytes or len(raw) > MAX_LINEAGE_SNAPSHOT_BYTES:
        _fail("snapshot_too_large")
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        _fail("snapshot_pin_drift")
    _int(retained_bytes, "snapshot_aggregate_invalid", maximum=MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES)
    if retained_bytes + len(raw) > MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES:
        _fail("snapshot_aggregate_invalid")
    return _create_lineage_file(workspace, journal_id, filename=f"{name}.snapshot", raw=raw,
                                expected_file_pin=expected_file_pin)



def persist_lineage_descriptor(workspace: str | Path, descriptor: object, *,
                               expected_file_pin: LineageSnapshotPin | None = None) -> tuple[Path, LineageSnapshotPin]:
    """Create a strict descriptor; exact replay requires its independently held file pin."""
    if type(descriptor) not in {ProducerLineageBeforeIntent, ProducerLineageStagedTransition, ProducerLineageTerminal}:
        _fail("descriptor_invalid")
    normalized = parse_lineage_descriptor(descriptor.to_dict())
    if normalized != descriptor:
        _fail("descriptor_invalid")
    return _create_lineage_file(workspace, descriptor.journal_id, filename=f"{descriptor.kind}.json",
                                raw=descriptor.to_json(), expected_file_pin=expected_file_pin)


def read_lineage_descriptor_pinned(
    workspace: str | Path, journal_id: str, *, kind: str, expected_file_pin: LineageSnapshotPin,
) -> ProducerLineageBeforeIntent | ProducerLineageStagedTransition | ProducerLineageTerminal:
    """Read only the system-derived descriptor, comparing the original independent pin."""
    if type(kind) is not str or kind not in {"before", "staged", "terminal"}:
        _fail("kind_invalid")
    if type(expected_file_pin) is not LineageSnapshotPin:
        _fail("snapshot_pin_invalid")
    path = lineage_directory(workspace, journal_id) / f"{kind}.json"
    raw, _ = _observe_file(path, name=path.name, maximum=MAX_LINEAGE_DESCRIPTOR_BYTES,
                          expected_pin=expected_file_pin)
    descriptor = parse_lineage_descriptor(raw)
    if descriptor.journal_id != journal_id or descriptor.kind != kind:
        _fail("association_invalid")
    return descriptor


def read_lineage_chain(workspace: str | Path, journal_ids: Sequence[str], *, run_id: str, max_batches: int = MAX_LINEAGE_BATCHES) -> tuple[ProducerLineageBeforeIntent, ...]:
    """Inspect descriptor associations only; this cannot authorize recovery or publication."""
    if type(max_batches) is not int or not 1 <= max_batches <= MAX_LINEAGE_BATCHES: _fail("capacity_invalid")
    if type(journal_ids) not in {tuple, list} or not 1 <= len(journal_ids) <= max_batches: _fail("chain_invalid")
    _id(run_id, "run_id_invalid")
    result: list[ProducerLineageBeforeIntent] = []
    previous_terminal = previous_lineage = None
    previous_archive = previous_state = None
    seen: set[str] = set()
    seen_candidates: set[str] = set()
    for ordinal, journal_id in enumerate(journal_ids):
        _id(journal_id, "journal_id_invalid")
        if journal_id in seen: _fail("duplicate_journal")
        seen.add(journal_id)
        base = lineage_directory(workspace, journal_id)
        before = parse_lineage_descriptor(base / "before.json")
        staged = parse_lineage_descriptor(base / "staged.json")
        terminal = parse_lineage_descriptor(base / "terminal.json")
        if not isinstance(before, ProducerLineageBeforeIntent) or not isinstance(staged, ProducerLineageStagedTransition) or not isinstance(terminal, ProducerLineageTerminal): _fail("chain_invalid")
        if before.run_id != run_id or staged.run_id != run_id or terminal.run_id != run_id or before.journal_id != journal_id or staged.journal_id != journal_id or terminal.journal_id != journal_id: _fail("association_invalid")
        if before.ordinal != ordinal or staged.ordinal != ordinal or terminal.ordinal != ordinal: _fail("ordinal_invalid")
        if before.predecessor_terminal_sha256 != previous_terminal or before.predecessor_lineage_sha256 != previous_lineage: _fail("predecessor_mismatch")
        if ordinal and (before.archive.sha256 != previous_archive or before.state.sha256 != previous_state):
            _fail("snapshot_continuity_mismatch")
        if staged.before_sha256 != before.descriptor_sha256 or terminal.staged_sha256 != staged.descriptor_sha256: _fail("transition_mismatch")
        if terminal.archive_after_sha256 != staged.archive_after_sha256 or terminal.state_after_sha256 != staged.state_after_sha256: _fail("terminal_mismatch")
        if seen_candidates.intersection(staged.candidate_ids):
            _fail("duplicate_candidate")
        seen_candidates.update(staged.candidate_ids)
        previous_terminal, previous_lineage = terminal.terminal_sha256, terminal.descriptor_sha256
        previous_archive, previous_state = terminal.archive_after_sha256, terminal.state_after_sha256
        result.append(before)
    return tuple(result)


__all__ = [
    "LINEAGE_PROTOCOL",
    "LINEAGE_SCHEMA_VERSION",
    "MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES",
    "MAX_LINEAGE_BATCHES",
    "MAX_LINEAGE_DESCRIPTOR_BYTES",
    "MAX_LINEAGE_SNAPSHOT_BYTES",
    "LineageSnapshotPin",
    "ProducerBundleLineageError",
    "ProducerLineageBeforeIntent",
    "ProducerLineageStagedTransition",
    "ProducerLineageTerminal",
    "capture_lineage_snapshot_pin",
    "lineage_directory",
    "parse_lineage_descriptor",
    "persist_lineage_bytes_snapshot",
    "persist_lineage_descriptor",
    "persist_lineage_snapshot",
    "read_lineage_chain",
    "read_lineage_descriptor_pinned",
    "verify_lineage_snapshot_pin",
    "verify_persisted_lineage_snapshot",
]
