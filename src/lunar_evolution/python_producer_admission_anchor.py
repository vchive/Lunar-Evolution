"""Durable identity for the first Python producer admission attempt.

The controller's producer checkpoint proves which binding was retained.  It does
not, by itself, prove which live-admission evidence was first registered.  This
module defines that separate, create-only projection.  It is intentionally
provider-free: constructing and parsing an anchor never starts a process or
turns an audit projection into production authority.
"""

from __future__ import annotations

import errno
import hashlib
import json
import math
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, NoReturn

from .python_producer_admission_handoff import (
    PythonProducerAdmissionHandoff,
    PythonProducerAdmissionHandoffError,
    parse_python_producer_admission_handoff,
)

PYTHON_PRODUCER_ADMISSION_ANCHOR_PROTOCOL = "lunar-python-producer-admission-attempt-anchor-v1"
PYTHON_PRODUCER_ADMISSION_ANCHOR_SCHEMA_VERSION = "1"
PYTHON_PRODUCER_ADMISSION_ANCHOR_NAME = "python-producer-admission-anchor.json"
MAX_PYTHON_PRODUCER_ADMISSION_ANCHOR_BYTES = 256 * 1024
PROTOCOL = PYTHON_PRODUCER_ADMISSION_ANCHOR_PROTOCOL
SCHEMA_VERSION = PYTHON_PRODUCER_ADMISSION_ANCHOR_SCHEMA_VERSION
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_FIELDS = frozenset({
    "schema_version", "protocol", "attempt_id", "run_id", "journal_id",
    "binding_sha256", "handoff_sha256", "terminal_sha256",
    "runtime_observation_sha256", "native_execution_receipt_sha256",
    "admission_plan_sha256", "fingerprints", "request_budget",
    "wall_timeout_seconds", "deadline_unix", "anchor_sha256",
})


class PythonProducerAdmissionAnchorError(ValueError):
    """Fixed-code parse or identity failure."""

    def __init__(self, code: str) -> None:
        self.code = "python_producer_admission_anchor_" + code
        super().__init__(self.code)


def _fail(code: str) -> NoReturn:
    raise PythonProducerAdmissionAnchorError(code)


def _digest(value: object, code: str = "digest_invalid") -> str:
    if type(value) is not str or _DIGEST.fullmatch(value) is None or value == "0" * 64:
        _fail(code)
    return value


def _identifier(value: object, code: str) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        _fail(code)
    return value


def _canonical(value: object) -> bytes:
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        raise PythonProducerAdmissionAnchorError("json_invalid") from exc
    if len(raw) > MAX_PYTHON_PRODUCER_ADMISSION_ANCHOR_BYTES:
        _fail("record_too_large")
    return raw


def _validate_fingerprints(value: object) -> dict[str, str]:
    if type(value) is not dict or not value or len(value) > 32:
        _fail("fingerprints_invalid")
    result: dict[str, str] = {}
    for key, item in value.items():
        if type(key) is not str or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]{0,63}", key):
            _fail("fingerprints_invalid")
        result[key] = _digest(item, "fingerprint_invalid")
    return result


def _validate_budget(value: object, *, name: str) -> int:
    if type(value) is not int or value < 1:
        _fail(name + "_invalid")
    return value


def _validate_positive_number(value: object, *, name: str) -> int | float:
    if type(value) not in {int, float}:
        _fail(name + "_invalid")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        _fail(name + "_invalid")
    if not finite or value <= 0:
        _fail(name + "_invalid")
    # Preserve the exact retained wire; rounding a deadline or clamping a duration
    # would turn the anchor into a different admission request.
    return value


@dataclass(frozen=True, slots=True)
class PythonProducerAdmissionAttemptAnchor:
    """Immutable first-registration proof for one live producer admission.

    The anchor includes every digest and launch limit needed to compare a later
    runtime/handoff observation with the original attempt.  ``anchor_sha256``
    covers all other fields and is never recomputed from a later observation.
    """

    attempt_id: str
    run_id: str
    journal_id: str
    binding_sha256: str
    handoff_sha256: str
    terminal_sha256: str
    runtime_observation_sha256: str
    native_execution_receipt_sha256: str
    admission_plan_sha256: str
    fingerprints: Mapping[str, str]
    request_budget: int
    wall_timeout_seconds: int | float
    deadline_unix: int | float
    anchor_sha256: str | None = None
    schema_version: str = SCHEMA_VERSION
    protocol: str = PROTOCOL

    def __post_init__(self) -> None:
        if (type(self.schema_version) is not str or type(self.protocol) is not str
                or self.schema_version != SCHEMA_VERSION or self.protocol != PROTOCOL):
            _fail("schema_invalid")
        _identifier(self.attempt_id, "attempt_id_invalid")
        _identifier(self.run_id, "run_id_invalid")
        _identifier(self.journal_id, "journal_id_invalid")
        for field in (
            "binding_sha256", "handoff_sha256", "terminal_sha256",
            "runtime_observation_sha256", "native_execution_receipt_sha256",
            "admission_plan_sha256",
        ):
            _digest(getattr(self, field), field + "_invalid")
        _validate_fingerprints(self.fingerprints)
        _validate_budget(self.request_budget, name="request_budget")
        _validate_positive_number(self.wall_timeout_seconds, name="wall_timeout_seconds")
        _validate_positive_number(self.deadline_unix, name="deadline_unix")
        if self.anchor_sha256 is not None:
            _digest(self.anchor_sha256, "anchor_digest_invalid")

    def _body(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "protocol": self.protocol,
            "attempt_id": self.attempt_id,
            "run_id": self.run_id,
            "journal_id": self.journal_id,
            "binding_sha256": self.binding_sha256,
            "handoff_sha256": self.handoff_sha256,
            "terminal_sha256": self.terminal_sha256,
            "runtime_observation_sha256": self.runtime_observation_sha256,
            "native_execution_receipt_sha256": self.native_execution_receipt_sha256,
            "admission_plan_sha256": self.admission_plan_sha256,
            "fingerprints": dict(self.fingerprints),
            "request_budget": self.request_budget,
            "wall_timeout_seconds": self.wall_timeout_seconds,
            "deadline_unix": self.deadline_unix,
        }

    def digest(self) -> str:
        self.__post_init__()
        return hashlib.sha256(_canonical(self._body())).hexdigest()

    def to_dict(self) -> dict[str, object]:
        self.__post_init__()
        digest = self.digest()
        if self.anchor_sha256 is not None and self.anchor_sha256 != digest:
            _fail("anchor_digest_mismatch")
        return self._body() | {"anchor_sha256": digest}

    def to_json(self) -> bytes:
        return _canonical(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> PythonProducerAdmissionAttemptAnchor:
        if type(value) is not dict or set(value) != _FIELDS:
            _fail("schema_invalid")
        _digest(value["anchor_sha256"], "anchor_digest_invalid")
        result = cls(
            attempt_id=value["attempt_id"], run_id=value["run_id"], journal_id=value["journal_id"],
            binding_sha256=value["binding_sha256"], handoff_sha256=value["handoff_sha256"],
            terminal_sha256=value["terminal_sha256"], runtime_observation_sha256=value["runtime_observation_sha256"],
            native_execution_receipt_sha256=value["native_execution_receipt_sha256"],
            admission_plan_sha256=value["admission_plan_sha256"], fingerprints=value["fingerprints"],
            request_budget=value["request_budget"], wall_timeout_seconds=value["wall_timeout_seconds"],
            deadline_unix=value["deadline_unix"], anchor_sha256=value["anchor_sha256"],
            schema_version=value["schema_version"], protocol=value["protocol"],
        )
        if result.anchor_sha256 != result.digest():
            _fail("anchor_digest_mismatch")
        return result

    @classmethod
    def from_json(cls, value: bytes | str) -> PythonProducerAdmissionAttemptAnchor:
        if type(value) not in {bytes, str}:
            _fail("json_invalid")
        try:
            encoded = value if type(value) is bytes else value.encode("utf-8")
            if len(encoded) > MAX_PYTHON_PRODUCER_ADMISSION_ANCHOR_BYTES:
                _fail("record_too_large")

            def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
                result: dict[str, object] = {}
                for key, item in items:
                    if key in result:
                        _fail("duplicate_json_key")
                    result[key] = item
                return result

            raw = json.loads(encoded.decode("utf-8"), object_pairs_hook=pairs,
                             parse_constant=lambda _: _fail("json_invalid"))
        except PythonProducerAdmissionAnchorError:
            raise
        except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
            raise PythonProducerAdmissionAnchorError("json_invalid") from exc
        result = cls.from_dict(raw)
        if result.to_json() != encoded:
            _fail("noncanonical_json")
        return result

    def matches(self, other: PythonProducerAdmissionAttemptAnchor) -> bool:
        """Compare all retained fields, including the immutable digest."""
        return type(other) is type(self) and self.to_dict() == other.to_dict()


def build_python_producer_admission_attempt_anchor(**kwargs: Any) -> PythonProducerAdmissionAttemptAnchor:
    """Build an anchor while deriving its canonical digest once."""
    anchor = PythonProducerAdmissionAttemptAnchor(**kwargs)
    return replace(anchor, anchor_sha256=anchor.digest())


def project_python_producer_admission_attempt_anchor(
    handoff: PythonProducerAdmissionHandoff,
) -> PythonProducerAdmissionAttemptAnchor:
    """Derive expected content from an already independently pinned handoff.

    This pure projection grants no authority and never registers an attempt.
    Reparse the exact DTO so deliberate mutation cannot refresh retained proof.
    """
    if type(handoff) is not PythonProducerAdmissionHandoff:
        _fail("handoff_invalid")
    try:
        retained = parse_python_producer_admission_handoff(handoff)
    except (PythonProducerAdmissionHandoffError, TypeError, ValueError) as exc:
        raise PythonProducerAdmissionAnchorError("handoff_invalid") from exc
    return build_python_producer_admission_attempt_anchor(
        attempt_id="attempt-" + retained.handoff_sha256[:32],
        run_id=retained.run_id,
        journal_id=retained.journal_id,
        binding_sha256=retained.binding_sha256,
        handoff_sha256=retained.handoff_sha256,
        terminal_sha256=retained.terminal_sha256,
        runtime_observation_sha256=retained.runtime_observation_sha256,
        native_execution_receipt_sha256=retained.native_execution_receipt_sha256,
        admission_plan_sha256=retained.admission_plan_sha256,
        fingerprints={
            "contract": retained.contract_sha256,
            "evaluator": retained.evaluator_sha256,
            "runner": retained.runner_sha256,
            "dependency": retained.dependency_sha256,
            "environment": retained.environment_sha256,
        },
        request_budget=retained.request_budget,
        wall_timeout_seconds=retained.wall_timeout_seconds,
        deadline_unix=retained.deadline_unix,
    )


def parse_python_producer_admission_attempt_anchor(
    value: PythonProducerAdmissionAttemptAnchor | Mapping[str, Any] | bytes | str,
) -> PythonProducerAdmissionAttemptAnchor:
    if type(value) is PythonProducerAdmissionAttemptAnchor:
        _digest(value.anchor_sha256, "anchor_digest_invalid")
        return PythonProducerAdmissionAttemptAnchor.from_dict(value.to_dict())
    if type(value) is dict:
        return PythonProducerAdmissionAttemptAnchor.from_dict(value)
    return PythonProducerAdmissionAttemptAnchor.from_json(value)


def verify_python_producer_admission_attempt_anchor(
    anchor: PythonProducerAdmissionAttemptAnchor | Mapping[str, Any] | bytes | str,
    expected: PythonProducerAdmissionAttemptAnchor | Mapping[str, Any] | bytes | str,
) -> PythonProducerAdmissionAttemptAnchor:
    """Reparse and compare a retained anchor with a later observation.

    This helper is deliberately strict: a later observation cannot replace a
    field or refresh a digest.  Callers that need to accept a new attempt must
    create a new anchor with a new ``attempt_id``.
    """
    observed = parse_python_producer_admission_attempt_anchor(anchor)
    retained = parse_python_producer_admission_attempt_anchor(expected)
    if not observed.matches(retained):
        _fail("drift")
    return retained


def _anchor_path(path: str | os.PathLike[str]) -> tuple[str, str]:
    try:
        value = os.fspath(path)
    except TypeError as exc:
        raise PythonProducerAdmissionAnchorError("path_invalid") from exc
    if not isinstance(value, str) or "\x00" in value:
        _fail("path_invalid")
    # Directory callers use the protocol's fixed filename. Explicit JSON paths remain supported.
    if os.path.basename(value) != PYTHON_PRODUCER_ADMISSION_ANCHOR_NAME and not value.endswith(".json"):
        value = os.path.join(value, PYTHON_PRODUCER_ADMISSION_ANCHOR_NAME)
    parent = os.path.dirname(os.path.abspath(value))
    name = os.path.basename(value)
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        _fail("path_invalid")
    return parent, name


def _read_anchor_bytes(parent: str, name: str) -> bytes:
    from pathlib import Path

    from ._candidate_workspace_io import DirectoryChain
    from .candidate_workspace_plan import CandidateWorkspaceError

    def file_stat(info: os.stat_result) -> tuple[int, ...]:
        # Reads may update atime. Every other identity/content/permission field
        # remains fixed throughout this observation.
        return (
            info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_uid, info.st_gid, info.st_size, info.st_mtime_ns, info.st_ctime_ns,
        )

    def regular(info: os.stat_result) -> None:
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1:
            _fail("file_identity_invalid")
        if info.st_size > MAX_PYTHON_PRODUCER_ADMISSION_ANCHOR_BYTES:
            _fail("record_too_large")

    chain = None
    descriptor = -1
    try:
        chain = DirectoryChain(Path(parent), "python_producer_admission_anchor_file_identity_invalid")
        before = os.stat(name, dir_fd=chain.fd, follow_symlinks=False)
        regular(before)
        # A raced FIFO must fail without waiting for a writer to open it.
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=chain.fd)
        info = os.fstat(descriptor)
        regular(info)
        if file_stat(before) != file_stat(info):
            _fail("file_identity_drift")
        raw = bytearray()
        while len(raw) <= MAX_PYTHON_PRODUCER_ADMISSION_ANCHOR_BYTES:
            chunk = os.read(descriptor, min(64 * 1024, MAX_PYTHON_PRODUCER_ADMISSION_ANCHOR_BYTES + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
        if len(raw) != info.st_size or len(raw) > MAX_PYTHON_PRODUCER_ADMISSION_ANCHOR_BYTES:
            _fail("file_identity_drift")
        post = os.fstat(descriptor)
        named = os.stat(name, dir_fd=chain.fd, follow_symlinks=False)
        if file_stat(post) != file_stat(info) or file_stat(named) != file_stat(info):
            _fail("file_identity_drift")
        chain.check()
        return bytes(raw)
    except FileNotFoundError as exc:
        raise PythonProducerAdmissionAnchorError("missing") from exc
    except PythonProducerAdmissionAnchorError:
        raise
    except CandidateWorkspaceError as exc:
        raise PythonProducerAdmissionAnchorError("file_identity_invalid") from exc
    except OSError as exc:
        raise PythonProducerAdmissionAnchorError("file_identity_invalid" if exc.errno in {errno.ELOOP, errno.ENOTDIR} else "read_invalid") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if chain is not None:
            chain.close()


def read_python_producer_admission_attempt_anchor(
    path: str | os.PathLike[str],
    *, expected_anchor_sha256: str | None = None,
) -> PythonProducerAdmissionAttemptAnchor:
    """Read the retained first-attempt anchor without refreshing or replacing it."""
    if expected_anchor_sha256 is not None:
        _digest(expected_anchor_sha256, "expected_digest_invalid")
    parent, name = _anchor_path(path)
    raw = _read_anchor_bytes(parent, name)
    parsed = PythonProducerAdmissionAttemptAnchor.from_json(raw)
    if expected_anchor_sha256 is not None and parsed.anchor_sha256 != expected_anchor_sha256:
        _fail("anchor_digest_mismatch")
    return parsed


def persist_python_producer_admission_attempt_anchor(
    path: str | os.PathLike[str], *, anchor: PythonProducerAdmissionAttemptAnchor | Mapping[str, Any],
) -> PythonProducerAdmissionAttemptAnchor:
    """Create one anchor exactly once, or replay byte-identical retained evidence."""
    from pathlib import Path

    from ._candidate_workspace_io import DirectoryChain
    from .candidate_workspace_plan import CandidateWorkspaceError

    def file_stat(info: os.stat_result) -> tuple[int, ...]:
        return (
            info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_uid, info.st_gid, info.st_size, info.st_mtime_ns, info.st_ctime_ns,
        )

    def regular(info: os.stat_result) -> None:
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1:
            _fail("file_identity_invalid")
        if info.st_size > MAX_PYTHON_PRODUCER_ADMISSION_ANCHOR_BYTES:
            _fail("record_too_large")

    parsed = parse_python_producer_admission_attempt_anchor(anchor)
    raw = parsed.to_json()
    if len(raw) > MAX_PYTHON_PRODUCER_ADMISSION_ANCHOR_BYTES:
        _fail("record_too_large")
    parent, name = _anchor_path(path)
    chain = None
    descriptor = -1
    try:
        chain = DirectoryChain(Path(parent), "python_producer_admission_anchor_file_identity_invalid")
        try:
            before = os.stat(name, dir_fd=chain.fd, follow_symlinks=False)
        except FileNotFoundError:
            before = None
        if before is None:
            # Read back through this same newly created descriptor. Closing and
            # reopening the path would adopt a replacement inode after a write.
            descriptor = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, 0o600, dir_fd=chain.fd)
            os.fchmod(descriptor, 0o600)
            created = os.fstat(descriptor)
            regular(created)
            if file_stat(os.stat(name, dir_fd=chain.fd, follow_symlinks=False)) != file_stat(created):
                _fail("file_identity_drift")
            view = memoryview(raw)
            while view:
                count = os.write(descriptor, view)
                if type(count) is not int or count <= 0 or count > len(view):
                    _fail("write_unknown")
                view = view[count:]
            os.fsync(descriptor)
            info = os.fstat(descriptor)
            regular(info)
            if (info.st_dev, info.st_ino, info.st_size) != (created.st_dev, created.st_ino, len(raw)):
                _fail("file_identity_drift")
            if file_stat(os.stat(name, dir_fd=chain.fd, follow_symlinks=False)) != file_stat(info):
                _fail("file_identity_drift")
            chain.check()
            os.fsync(chain.fd)
            os.lseek(descriptor, 0, os.SEEK_SET)
        else:
            regular(before)
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=chain.fd)
            info = os.fstat(descriptor)
            regular(info)
            if file_stat(before) != file_stat(info):
                _fail("file_identity_drift")
        observed = bytearray()
        while len(observed) <= MAX_PYTHON_PRODUCER_ADMISSION_ANCHOR_BYTES:
            chunk = os.read(descriptor, min(64 * 1024, MAX_PYTHON_PRODUCER_ADMISSION_ANCHOR_BYTES + 1 - len(observed)))
            if not chunk:
                break
            observed.extend(chunk)
        post = os.fstat(descriptor)
        named = os.stat(name, dir_fd=chain.fd, follow_symlinks=False)
        if (len(observed) != info.st_size or len(observed) > MAX_PYTHON_PRODUCER_ADMISSION_ANCHOR_BYTES
                or file_stat(post) != file_stat(info) or file_stat(named) != file_stat(info)):
            _fail("file_identity_drift")
        chain.check()
        if bytes(observed) != raw:
            _fail("file_identity_drift" if before is None else "already_exists")
        return PythonProducerAdmissionAttemptAnchor.from_json(bytes(observed))
    except FileExistsError as exc:
        # This creator did not own the exclusive descriptor. Even equal bytes
        # cannot turn a competing creation into its original write observation.
        raise PythonProducerAdmissionAnchorError("already_exists") from exc
    except PythonProducerAdmissionAnchorError:
        raise
    except CandidateWorkspaceError as exc:
        raise PythonProducerAdmissionAnchorError("file_identity_invalid") from exc
    except OSError as exc:
        raise PythonProducerAdmissionAnchorError("write_unknown") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if chain is not None:
            chain.close()


__all__ = [
    "MAX_PYTHON_PRODUCER_ADMISSION_ANCHOR_BYTES",
    "PROTOCOL",
    "PYTHON_PRODUCER_ADMISSION_ANCHOR_NAME",
    "PYTHON_PRODUCER_ADMISSION_ANCHOR_PROTOCOL",
    "PYTHON_PRODUCER_ADMISSION_ANCHOR_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "PythonProducerAdmissionAnchorError",
    "PythonProducerAdmissionAttemptAnchor",
    "build_python_producer_admission_attempt_anchor",
    "parse_python_producer_admission_attempt_anchor",
    "persist_python_producer_admission_attempt_anchor",
    "project_python_producer_admission_attempt_anchor",
    "read_python_producer_admission_attempt_anchor",
    "verify_python_producer_admission_attempt_anchor",
]
