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
from pathlib import Path
from typing import NoReturn

from . import _benchmark_files as _files
from .candidate_evaluation_spec import strict_json

LINEAGE_PROTOCOL = "lunar-producer-bundle-lineage-v1"
LINEAGE_SCHEMA_VERSION = "1"
MAX_LINEAGE_BATCHES = 8
MAX_LINEAGE_DESCRIPTOR_BYTES = 32 * 1024
MAX_LINEAGE_SNAPSHOT_BYTES = 16 * 1024 * 1024
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


@dataclass(frozen=True, slots=True)
class LineageSnapshotPin:
    """Independent bytes and inode/stat observation for one archive/state snapshot."""

    name: str
    sha256: str
    size: int
    device: int
    inode: int
    mode: int = 0o600
    nlink: int = 1
    mtime_ns: int = 0
    ctime_ns: int = 0

    def __post_init__(self) -> None:
        _id(self.name, "snapshot_name_invalid")
        _sha(self.sha256, "snapshot_digest_invalid")
        _int(self.size, "snapshot_size_invalid", maximum=MAX_LINEAGE_SNAPSHOT_BYTES)
        if self.size == 0:
            _fail("snapshot_size_invalid")
        _int(self.device, "snapshot_device_invalid")
        _int(self.inode, "snapshot_inode_invalid")
        if self.inode == 0:
            _fail("snapshot_inode_invalid")
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
                "device": self.device, "inode": self.inode, "mode": self.mode,
                "nlink": self.nlink, "mtime_ns": self.mtime_ns, "ctime_ns": self.ctime_ns}

    @classmethod
    def from_dict(cls, value: object) -> LineageSnapshotPin:
        return cls(**_fields(value, frozenset({"name", "sha256", "size", "device", "inode", "mode", "nlink", "mtime_ns", "ctime_ns"}), "snapshot_schema_invalid"))  # type: ignore[arg-type]


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
        if not isinstance(self.candidate_ids, tuple) or not self.candidate_ids or len(self.candidate_ids) > 32 or len(set(self.candidate_ids)) != len(self.candidate_ids): _fail("candidates_invalid")
        for value in self.candidate_ids: _id(value, "candidate_invalid")
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
    if isinstance(value, Mapping): raw = dict(value)
    elif isinstance(value, (bytes, str)):
        try: raw = strict_json(value if isinstance(value, bytes) else value.encode("utf-8"), MAX_LINEAGE_DESCRIPTOR_BYTES)
        except Exception as exc: raise ProducerBundleLineageError("json_invalid") from exc
    else:
        try: raw = strict_json(_files.read_regular_file(_files.absolute_path(value), MAX_LINEAGE_DESCRIPTOR_BYTES), MAX_LINEAGE_DESCRIPTOR_BYTES)
        except Exception as exc: raise ProducerBundleLineageError("read_invalid") from exc
    if not isinstance(raw, dict): _fail("schema_invalid")
    kind = raw.get("kind")
    if kind == "before": return ProducerLineageBeforeIntent.from_dict(raw)
    if kind == "staged": return ProducerLineageStagedTransition.from_dict(raw)
    if kind == "terminal": return ProducerLineageTerminal.from_dict(raw)
    _fail("kind_invalid")


def lineage_directory(workspace: str | Path, journal_id: str) -> Path:
    """Return only the system-derived lineage directory; caller cannot supply a sibling path."""
    root = _files.absolute_path(workspace)
    _id(journal_id, "journal_id_invalid")
    return root / "evolution" / "producer-batches" / journal_id / "lineage"


def capture_lineage_snapshot_pin(path: str | Path, *, name: str) -> LineageSnapshotPin:
    """Capture one bounded regular-file pin with before/read/after identity checks.

    This helper is read-only.  It is intended to run while the existing publication lock is
    held; it does not turn a current file into authority for a successor by itself.
    """
    _id(name, "snapshot_name_invalid")
    target = _files.absolute_path(path)
    try:
        before = target.lstat()
        if (not stat.S_ISREG(before.st_mode) or stat.S_IMODE(before.st_mode) != 0o600
                or before.st_nlink != 1 or before.st_size <= 0
                or before.st_size > MAX_LINEAGE_SNAPSHOT_BYTES):
            _fail("snapshot_identity_invalid")
        raw = _files.read_regular_file(target, MAX_LINEAGE_SNAPSHOT_BYTES)
        after = target.lstat()
        if (before.st_dev, before.st_ino, before.st_size, before.st_mode, before.st_nlink,
                before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_dev, after.st_ino, after.st_size, after.st_mode, after.st_nlink,
                after.st_mtime_ns, after.st_ctime_ns) or len(raw) != before.st_size:
            _fail("snapshot_identity_drift")
        return LineageSnapshotPin(
            name=name, sha256=hashlib.sha256(raw).hexdigest(), size=len(raw),
            device=before.st_dev, inode=before.st_ino, mode=stat.S_IMODE(before.st_mode),
            nlink=before.st_nlink, mtime_ns=before.st_mtime_ns, ctime_ns=before.st_ctime_ns,
        )
    except ProducerBundleLineageError:
        raise
    except (_files.BenchmarkFileError, OSError, ValueError) as exc:
        raise ProducerBundleLineageError("snapshot_read_invalid") from exc


def verify_lineage_snapshot_pin(path: str | Path, pin: LineageSnapshotPin) -> None:
    """Re-read a retained snapshot and reject any byte or inode/stat drift."""
    if not isinstance(pin, LineageSnapshotPin):
        _fail("snapshot_pin_invalid")
    observed = capture_lineage_snapshot_pin(path, name=pin.name)
    if observed != pin:
        _fail("snapshot_pin_drift")


def persist_lineage_snapshot(
    workspace: str | Path,
    journal_id: str,
    *,
    name: str,
    source: str | Path,
    expected_pin: LineageSnapshotPin | None = None,
) -> tuple[Path, LineageSnapshotPin]:
    """Retain an immutable snapshot copy and its independent source pin.

    The source is observed before and after the bounded read.  The destination is a
    create-only regular file under the derived lineage directory; retries require exact
    bytes and metadata.  This is evidence retention only and never advances publication.
    """
    _id(journal_id, "journal_id_invalid")
    _id(name, "snapshot_name_invalid")
    pin = capture_lineage_snapshot_pin(source, name=name) if expected_pin is None else expected_pin
    if expected_pin is not None:
        verify_lineage_snapshot_pin(source, expected_pin)
    raw = _files.read_regular_file(_files.absolute_path(source), MAX_LINEAGE_SNAPSHOT_BYTES)
    if hashlib.sha256(raw).hexdigest() != pin.sha256 or len(raw) != pin.size:
        _fail("snapshot_pin_drift")
    destination = lineage_directory(workspace, journal_id) / f"{name}.snapshot"
    try:
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if destination.exists():
            current = _files.read_regular_file(_files.absolute_path(destination), MAX_LINEAGE_SNAPSHOT_BYTES)
            if current != raw:
                _fail("snapshot_conflict")
            return destination, pin
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            view = memoryview(raw)
            while view:
                count = os.write(descriptor, view)
                if count <= 0:
                    _fail("snapshot_write_failed")
                view = view[count:]
            os.fsync(descriptor)
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size != len(raw):
                _fail("snapshot_pin_invalid")
        finally:
            os.close(descriptor)
        return destination, pin
    except ProducerBundleLineageError:
        raise
    except (_files.BenchmarkFileError, OSError, ValueError) as exc:
        raise ProducerBundleLineageError("snapshot_write_failed") from exc


def verify_persisted_lineage_snapshot(path: str | Path, pin: LineageSnapshotPin) -> None:
    """Verify a retained snapshot's bytes and strict regular-file metadata."""
    if not isinstance(pin, LineageSnapshotPin):
        _fail("snapshot_pin_invalid")
    try:
        info = _files.absolute_path(path).lstat()
        if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_nlink != 1 or info.st_size != pin.size):
            _fail("snapshot_pin_drift")
        raw = _files.read_regular_file(_files.absolute_path(path), MAX_LINEAGE_SNAPSHOT_BYTES)
        if hashlib.sha256(raw).hexdigest() != pin.sha256:
            _fail("snapshot_pin_drift")
    except ProducerBundleLineageError:
        raise
    except (_files.BenchmarkFileError, OSError, ValueError) as exc:
        raise ProducerBundleLineageError("snapshot_read_invalid") from exc


def precommit_lineage_cas(
    *,
    producer_multi_episode_publication: bool,
    before: ProducerLineageBeforeIntent,
    staged: ProducerLineageStagedTransition,
    expected_run_id: str,
    expected_journal_id: str,
    expected_ordinal: int,
    expected_predecessor_terminal_sha256: str | None,
    expected_predecessor_lineage_sha256: str | None,
) -> str:
    """Validate the opt-in precommit lineage CAS tuple without touching legacy paths.

    The returned digest is a checkpoint value for a caller-owned CAS.  This helper has
    no controller or publication-lock side effects and refuses unless the new explicit
    boolean is exactly true.
    """
    if producer_multi_episode_publication is not True:
        _fail("multi_episode_opt_in_required")
    if type(expected_run_id) is not str or type(expected_journal_id) is not str:
        _fail("association_invalid")
    if before.run_id != expected_run_id or staged.run_id != expected_run_id or before.journal_id != expected_journal_id or staged.journal_id != expected_journal_id:
        _fail("association_invalid")
    if before.ordinal != expected_ordinal or staged.ordinal != expected_ordinal:
        _fail("ordinal_invalid")
    if before.predecessor_terminal_sha256 != expected_predecessor_terminal_sha256 or before.predecessor_lineage_sha256 != expected_predecessor_lineage_sha256:
        _fail("predecessor_mismatch")
    if staged.before_sha256 != before.digest():
        _fail("transition_mismatch")
    return hashlib.sha256(_canonical({"before": before.digest(), "staged": staged.digest(), "ordinal": expected_ordinal})).hexdigest()


def persist_lineage_descriptor(workspace: str | Path, descriptor: object) -> Path:
    """Create a descriptor once, preserving byte-identical retries and refusing replacement."""
    if not isinstance(descriptor, (ProducerLineageBeforeIntent, ProducerLineageStagedTransition, ProducerLineageTerminal)):
        _fail("descriptor_invalid")
    encoded = _canonical(descriptor.to_dict())
    path = lineage_directory(workspace, descriptor.journal_id) / f"{descriptor.kind}.json"
    try:
        root = _files.absolute_path(workspace)
        current = root
        relative = path.parent.relative_to(root)
        # Check existing components before ``mkdir`` so an attacker cannot make a
        # system-derived component redirect the create-only sidecar write.
        for part in relative.parts:
            candidate = current / part
            try:
                info = candidate.lstat()
            except FileNotFoundError:
                break
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                _fail("path_invalid")
            current = candidate
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        current = root
        for part in relative.parts:
            current = current / part
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                _fail("path_invalid")
        if path.exists():
            existing = _files.read_regular_file(_files.absolute_path(path), MAX_LINEAGE_DESCRIPTOR_BYTES)
            if existing != encoded: _fail("descriptor_conflict")
            return path
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
        fd = os.open(path, flags, 0o600)
        try:
            view = memoryview(encoded)
            while view:
                count = os.write(fd, view)
                if count <= 0:
                    _fail("write_failed")
                view = view[count:]
            os.fsync(fd)
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size != len(encoded): _fail("descriptor_pin_invalid")
        finally: os.close(fd)
        return path
    except ProducerBundleLineageError:
        raise
    except (OSError, ValueError) as exc:
        raise ProducerBundleLineageError("write_failed") from exc


def read_lineage_chain(workspace: str | Path, journal_ids: Sequence[str], *, run_id: str, max_batches: int = MAX_LINEAGE_BATCHES) -> tuple[ProducerLineageBeforeIntent, ...]:
    """Read a complete, ordered, terminally acknowledged chain without side effects."""
    if type(max_batches) is not int or not 1 <= max_batches <= MAX_LINEAGE_BATCHES: _fail("capacity_invalid")
    if not isinstance(journal_ids, Sequence) or isinstance(journal_ids, (str, bytes)) or not 1 <= len(journal_ids) <= max_batches: _fail("chain_invalid")
    _id(run_id, "run_id_invalid")
    result: list[ProducerLineageBeforeIntent] = []
    previous_terminal = previous_lineage = None
    seen: set[str] = set()
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
        if staged.before_sha256 != before.descriptor_sha256 or terminal.staged_sha256 != staged.descriptor_sha256: _fail("transition_mismatch")
        if terminal.archive_after_sha256 != staged.archive_after_sha256 or terminal.state_after_sha256 != staged.state_after_sha256: _fail("terminal_mismatch")
        previous_terminal, previous_lineage = terminal.terminal_sha256, terminal.descriptor_sha256
        result.append(before)
    return tuple(result)


__all__ = [
    "LINEAGE_PROTOCOL",
    "LINEAGE_SCHEMA_VERSION",
    "MAX_LINEAGE_BATCHES",
    "MAX_LINEAGE_DESCRIPTOR_BYTES",
    "LineageSnapshotPin",
    "ProducerBundleLineageError",
    "ProducerLineageBeforeIntent",
    "ProducerLineageStagedTransition",
    "ProducerLineageTerminal",
    "capture_lineage_snapshot_pin",
    "lineage_directory",
    "parse_lineage_descriptor",
    "persist_lineage_descriptor",
    "persist_lineage_snapshot",
    "precommit_lineage_cas",
    "read_lineage_chain",
    "verify_lineage_snapshot_pin",
    "verify_persisted_lineage_snapshot",
]
