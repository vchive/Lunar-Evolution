"""Provider-free local handoff record for Python producer admission.

This module deliberately stops before evaluation and publication.  It defines one bounded,
canonical record which joins already verified evidence, persists that record create-only, and
offers read-only prepare/reconcile/replay gates.  A handoff is evidence/provenance; constructing,
reading, or replaying it never starts a producer, calls an evaluator, consumes a budget, or
updates an existing journal or transaction.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from ._candidate_workspace_io import DirectoryChain
from .candidate_workspace_plan import CandidateWorkspaceError

PYTHON_PRODUCER_ADMISSION_HANDOFF_PROTOCOL = "lunar-python-producer-admission-handoff-v1"
PYTHON_PRODUCER_ADMISSION_HANDOFF_SCHEMA_VERSION = "1"
PYTHON_PRODUCER_ADMISSION_HANDOFF_NAME = "python-producer-admission-handoff.json"
MAX_PYTHON_PRODUCER_ADMISSION_HANDOFF_BYTES = 256 * 1024

HANDOFF_STATE_PREPARED = "prepared"
HANDOFF_STATE_EVALUATING = "evaluating"
HANDOFF_STATE_STAGED = "staged"
HANDOFF_STATE_UNKNOWN = "unknown"
HANDOFF_STATE_PUBLISHED = "published"
HANDOFF_STATE_REJECTED = "rejected"
HANDOFF_STATES = frozenset(
    {
        HANDOFF_STATE_PREPARED,
        HANDOFF_STATE_EVALUATING,
        HANDOFF_STATE_STAGED,
        HANDOFF_STATE_UNKNOWN,
        HANDOFF_STATE_PUBLISHED,
        HANDOFF_STATE_REJECTED,
    }
)
_TERMINAL_REPLAY_STATES = frozenset({HANDOFF_STATE_PUBLISHED, HANDOFF_STATE_REJECTED})
_RECONCILABLE_STATES = frozenset(
    {HANDOFF_STATE_UNKNOWN, HANDOFF_STATE_PUBLISHED, HANDOFF_STATE_REJECTED}
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_CREDENTIAL = re.compile(
    r"(?i)(?:sk-[A-Za-z0-9_-]{8,}|bearer\s+[A-Za-z0-9._-]{8,}|"
    r"api[_-]?key\s*[:=]\s*\S+|(?:password|secret|access[_-]?token)\s*[:=]\s*\S+)"
)


class PythonProducerAdmissionHandoffError(ValueError):
    """Fixed-code refusal at the provider-free handoff boundary."""

    def __init__(self, code: str) -> None:
        self.code = "python_producer_admission_handoff_" + code
        super().__init__(self.code)


def _fail(code: str) -> NoReturn:
    raise PythonProducerAdmissionHandoffError(code)


def _canonical(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        raise PythonProducerAdmissionHandoffError("canonical_invalid") from exc
    if len(encoded) > MAX_PYTHON_PRODUCER_ADMISSION_HANDOFF_BYTES:
        _fail("record_too_large")
    return encoded


def _pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            _fail("duplicate_json_key")
        result[key] = value
    return result


def _strict_json(value: bytes | str | bytearray) -> tuple[object, bytes]:
    if type(value) is str:
        try:
            raw = value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise PythonProducerAdmissionHandoffError("json_invalid") from exc
    elif type(value) in {bytes, bytearray}:
        raw = bytes(value)
    else:
        _fail("json_invalid")
    if len(raw) > MAX_PYTHON_PRODUCER_ADMISSION_HANDOFF_BYTES:
        _fail("record_too_large")
    try:
        parsed = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_constant=lambda _value: _fail("json_invalid"),
        )
    except PythonProducerAdmissionHandoffError:
        raise
    except (UnicodeDecodeError, TypeError, ValueError, RecursionError) as exc:
        raise PythonProducerAdmissionHandoffError("json_invalid") from exc
    return parsed, raw


def _sha(value: object, code: str = "digest_invalid") -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None or value == "0" * 64:
        _fail(code)
    return value


def _identifier(value: object, code: str = "identity_invalid") -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None or _CREDENTIAL.search(value):
        _fail(code)
    return value


def _positive_int(value: object, code: str) -> int:
    if type(value) is not int or value < 1:
        _fail(code)
    return value


def _positive_number(value: object, code: str) -> float:
    if type(value) not in {int, float} or isinstance(value, bool):
        _fail(code)
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        _fail(code)
    if not math.isfinite(result) or result <= 0:
        _fail(code)
    return result


_FIELDS = frozenset(
    {
        "schema_version",
        "protocol",
        "run_id",
        "journal_id",
        "parent_task_id",
        "task_id",
        "binding_sha256",
        "sidecar_raw_sha256",
        "sidecar_pin_sha256",
        "launch_intent_sha256",
        "attestation_sha256",
        "runtime_manifest_sha256",
        "runtime_tree_sha256",
        "executable_owner_sha256",
        "native_execution_receipt_sha256",
        "terminal_sha256",
        "runtime_observation_sha256",
        "broker_transcript_sha256",
        "envelope_sha256",
        "materials_sha256",
        "contract_sha256",
        "evaluator_sha256",
        "runner_sha256",
        "dependency_sha256",
        "environment_sha256",
        "admission_plan_sha256",
        "request_budget",
        "wall_timeout_seconds",
        "deadline_unix",
        "state",
        "handoff_sha256",
    }
)
_DIGEST_FIELDS = frozenset(_FIELDS - {
    "schema_version", "protocol", "run_id", "journal_id", "parent_task_id", "task_id",
    "request_budget", "wall_timeout_seconds", "deadline_unix", "state", "handoff_sha256",
})


@dataclass(frozen=True, slots=True)
class PythonProducerAdmissionHandoff:
    """Canonical, digest-bound evidence projection for one local admission attempt."""

    schema_version: str
    protocol: str
    run_id: str
    journal_id: str
    parent_task_id: str
    task_id: str
    binding_sha256: str
    sidecar_raw_sha256: str
    sidecar_pin_sha256: str
    launch_intent_sha256: str
    attestation_sha256: str
    runtime_manifest_sha256: str
    runtime_tree_sha256: str
    executable_owner_sha256: str
    native_execution_receipt_sha256: str
    terminal_sha256: str
    runtime_observation_sha256: str
    broker_transcript_sha256: str
    envelope_sha256: str
    materials_sha256: str
    contract_sha256: str
    evaluator_sha256: str
    runner_sha256: str
    dependency_sha256: str
    environment_sha256: str
    admission_plan_sha256: str
    request_budget: int
    wall_timeout_seconds: float
    deadline_unix: float
    state: str
    handoff_sha256: str

    def __post_init__(self) -> None:
        _validate_payload(self.to_dict(), check_digest=True)

    @property
    def digest(self) -> str:
        """Return the self-digest (an alias useful to generic handoff callers)."""

        return self.handoff_sha256

    def to_dict(self) -> dict[str, object]:
        return {
            field: getattr(self, field)
            for field in _FIELD_ORDER
        }

    def to_json(self) -> bytes:
        return _canonical(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> PythonProducerAdmissionHandoff:
        return parse_python_producer_admission_handoff(value)


_FIELD_ORDER = (
    "schema_version", "protocol", "run_id", "journal_id", "parent_task_id", "task_id",
    "binding_sha256", "sidecar_raw_sha256", "sidecar_pin_sha256", "launch_intent_sha256",
    "attestation_sha256", "runtime_manifest_sha256", "runtime_tree_sha256",
    "executable_owner_sha256", "native_execution_receipt_sha256", "terminal_sha256",
    "runtime_observation_sha256", "broker_transcript_sha256", "envelope_sha256",
    "materials_sha256", "contract_sha256", "evaluator_sha256", "runner_sha256",
    "dependency_sha256", "environment_sha256", "admission_plan_sha256", "request_budget",
    "wall_timeout_seconds", "deadline_unix", "state", "handoff_sha256",
)


def _validate_payload(value: object, *, check_digest: bool) -> dict[str, object]:
    if type(value) is not dict or set(value) != _FIELDS:
        _fail("schema_invalid")
    if value["schema_version"] != PYTHON_PRODUCER_ADMISSION_HANDOFF_SCHEMA_VERSION:
        _fail("schema_invalid")
    if value["protocol"] != PYTHON_PRODUCER_ADMISSION_HANDOFF_PROTOCOL:
        _fail("protocol_invalid")
    for field in ("run_id", "journal_id", "parent_task_id", "task_id"):
        _identifier(value[field], "identity_invalid")
    for field in _DIGEST_FIELDS:
        _sha(value[field], "digest_invalid")
    _positive_int(value["request_budget"], "request_budget_invalid")
    _positive_number(value["wall_timeout_seconds"], "wall_timeout_invalid")
    _positive_number(value["deadline_unix"], "deadline_invalid")
    if type(value["state"]) is not str or value["state"] not in HANDOFF_STATES:
        _fail("state_invalid")
    if check_digest:
        _sha(value["handoff_sha256"], "digest_invalid")
        expected = hashlib.sha256(
            _canonical({key: value[key] for key in _FIELD_ORDER if key != "handoff_sha256"})
        ).hexdigest()
        if value["handoff_sha256"] != expected:
            _fail("digest_mismatch")
    return value


def _detach(value: Mapping[str, object]) -> dict[str, object]:
    try:
        detached = json.loads(_canonical(dict(value)))
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise PythonProducerAdmissionHandoffError("schema_invalid") from exc
    if type(detached) is not dict:
        _fail("schema_invalid")
    return detached


def parse_python_producer_admission_handoff(
    value: PythonProducerAdmissionHandoff | Mapping[str, object] | str | bytes | bytearray,
) -> PythonProducerAdmissionHandoff:
    """Parse one canonical handoff without granting evaluation or publication authority."""

    encoded: bytes | None = None
    if isinstance(value, PythonProducerAdmissionHandoff):
        # Frozen dataclasses can still be deliberately altered with object.__setattr__ at an
        # untrusted boundary.  Reparse the detached projection instead of trusting the instance.
        try:
            parsed = _detach(value.to_dict())
        except PythonProducerAdmissionHandoffError:
            raise
        except Exception as exc:
            raise PythonProducerAdmissionHandoffError("schema_invalid") from exc
    elif type(value) in {str, bytes, bytearray}:
        parsed, encoded = _strict_json(value)  # type: ignore[arg-type]
    elif isinstance(value, Mapping):
        parsed = _detach(value)
    else:
        _fail("schema_invalid")
    if encoded is not None and _canonical(parsed) != encoded:
        _fail("noncanonical")
    raw = _validate_payload(parsed, check_digest=True)
    try:
        return PythonProducerAdmissionHandoff(**{field: raw[field] for field in _FIELD_ORDER})
    except PythonProducerAdmissionHandoffError:
        raise
    except (TypeError, ValueError) as exc:
        raise PythonProducerAdmissionHandoffError("schema_invalid") from exc


def build_python_producer_admission_handoff(
    payload: Mapping[str, object] | PythonProducerAdmissionHandoff | None = None,
    **fields: object,
) -> PythonProducerAdmissionHandoff:
    """Build a prepared handoff from already verified, digest-only evidence.

    ``schema_version``, ``protocol``, ``state`` and the self-digest may be omitted by callers;
    the builder supplies their fixed defaults.  All other fields are required and are validated
    before the canonical self-digest is computed.  The function performs no I/O.
    """

    if isinstance(payload, PythonProducerAdmissionHandoff):
        if fields:
            _fail("schema_invalid")
        return parse_python_producer_admission_handoff(payload)
    if payload is not None and not isinstance(payload, Mapping):
        _fail("schema_invalid")
    if payload is not None and fields:
        merged = dict(payload)
        overlap = set(merged).intersection(fields)
        if overlap:
            _fail("schema_invalid")
        merged.update(fields)
    else:
        merged = dict(payload) if payload is not None else dict(fields)
    merged.setdefault("schema_version", PYTHON_PRODUCER_ADMISSION_HANDOFF_SCHEMA_VERSION)
    merged.setdefault("protocol", PYTHON_PRODUCER_ADMISSION_HANDOFF_PROTOCOL)
    merged.setdefault("state", HANDOFF_STATE_PREPARED)
    if "handoff_sha256" in merged:
        # An existing digest is retained evidence, never permission to silently re-sign drift.
        return parse_python_producer_admission_handoff(merged)
    _validate_payload({**merged, "handoff_sha256": "0" * 64}, check_digest=False)
    body = {field: merged[field] for field in _FIELD_ORDER if field != "handoff_sha256"}
    merged["handoff_sha256"] = hashlib.sha256(_canonical(body)).hexdigest()
    return parse_python_producer_admission_handoff(merged)


def prepare_python_producer_admission_handoff(
    value: PythonProducerAdmissionHandoff | Mapping[str, object] | str | bytes | bytearray,
) -> PythonProducerAdmissionHandoff:
    """Validate a prepared handoff without evaluating, publishing, or changing its state."""

    if isinstance(value, Mapping):
        # A supplied self-digest is an assertion and must be verified; only a digest-less
        # builder payload receives the fixed defaults and a newly computed digest.
        handoff = (
            parse_python_producer_admission_handoff(value)
            if "handoff_sha256" in value
            else build_python_producer_admission_handoff(value)
        )
    else:
        handoff = parse_python_producer_admission_handoff(value)
    if handoff.state != HANDOFF_STATE_PREPARED:
        _fail("prepare_state_invalid")
    return handoff


def reconcile_python_producer_admission_handoff(
    value: PythonProducerAdmissionHandoff | Mapping[str, object] | str | bytes | bytearray,
) -> PythonProducerAdmissionHandoff:
    """Re-read a durable handoff projection without retrying work or consuming budget."""

    handoff = parse_python_producer_admission_handoff(value)
    if handoff.state not in _RECONCILABLE_STATES:
        _fail("reconcile_state_invalid")
    return handoff


def replay_python_producer_admission_handoff(
    value: PythonProducerAdmissionHandoff | Mapping[str, object] | str | bytes | bytearray,
) -> PythonProducerAdmissionHandoff:
    """Replay only a terminal handoff; no producer/evaluator/publication side effect occurs."""

    handoff = parse_python_producer_admission_handoff(value)
    if handoff.state not in _TERMINAL_REPLAY_STATES:
        _fail("replay_state_invalid")
    return handoff


def _path(value: str | os.PathLike[str]) -> Path:
    try:
        result = Path(value).expanduser()
        if (".." in result.parts or "\x00" in str(result) or len(result.parts) > 128
                or len(str(result).encode("utf-8")) > 4096):
            _fail("path_invalid")
        result = result.absolute()
    except PythonProducerAdmissionHandoffError:
        raise
    except (TypeError, ValueError, OSError, UnicodeError, RuntimeError) as exc:
        raise PythonProducerAdmissionHandoffError("path_invalid") from exc
    # Directory callers use the fixed batch filename; explicit .json paths remain supported.
    if result.name != PYTHON_PRODUCER_ADMISSION_HANDOFF_NAME and result.suffix != ".json":
        result = result / PYTHON_PRODUCER_ADMISSION_HANDOFF_NAME
    return result


def _metadata(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns,
        info.st_mode, info.st_nlink,
    )


def _directory(path: Path) -> DirectoryChain:
    try:
        return DirectoryChain(path.parent, "python_producer_admission_handoff_parent_invalid")
    except (CandidateWorkspaceError, OSError, ValueError) as exc:
        raise PythonProducerAdmissionHandoffError("parent_invalid") from exc


def _check_directory(chain: DirectoryChain) -> None:
    try:
        chain.check()
    except (CandidateWorkspaceError, OSError, ValueError) as exc:
        raise PythonProducerAdmissionHandoffError("parent_changed") from exc


def _read_file(
    chain: DirectoryChain, name: str, *, expected_inode: tuple[int, int] | None = None,
) -> bytes:
    """Read bounded bytes through one no-follow FD and recheck every held directory."""
    descriptor = -1
    try:
        _check_directory(chain)
        before = os.stat(name, dir_fd=chain.fd, follow_symlinks=False)
        if (not stat.S_ISREG(before.st_mode) or stat.S_IMODE(before.st_mode) != 0o600
                or before.st_nlink != 1):
            _fail("file_identity_invalid")
        if expected_inode is not None and (before.st_dev, before.st_ino) != expected_inode:
            _fail("file_identity_drift")
        if before.st_size > MAX_PYTHON_PRODUCER_ADMISSION_HANDOFF_BYTES:
            _fail("record_too_large")
        descriptor = os.open(
            name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
            dir_fd=chain.fd,
        )
        opened = os.fstat(descriptor)
        if _metadata(opened) != _metadata(before):
            _fail("file_identity_drift")
        raw = bytearray()
        while len(raw) <= MAX_PYTHON_PRODUCER_ADMISSION_HANDOFF_BYTES:
            chunk = os.read(
                descriptor,
                min(64 * 1024, MAX_PYTHON_PRODUCER_ADMISSION_HANDOFF_BYTES + 1 - len(raw)),
            )
            if not chunk:
                break
            raw.extend(chunk)
        if len(raw) > MAX_PYTHON_PRODUCER_ADMISSION_HANDOFF_BYTES:
            _fail("record_too_large")
        after = os.fstat(descriptor)
        named = os.stat(name, dir_fd=chain.fd, follow_symlinks=False)
        if (_metadata(before) != _metadata(after) or _metadata(after) != _metadata(named)
                or len(raw) != before.st_size):
            _fail("file_identity_drift")
        _check_directory(chain)
        return bytes(raw)
    except FileNotFoundError as exc:
        raise PythonProducerAdmissionHandoffError("missing") from exc
    except PythonProducerAdmissionHandoffError:
        raise
    except (OSError, ValueError) as exc:
        raise PythonProducerAdmissionHandoffError("read_invalid") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _read_path(path: Path) -> bytes:
    chain = _directory(path)
    try:
        return _read_file(chain, path.name)
    finally:
        chain.close()


def read_python_producer_admission_handoff(
    path: str | os.PathLike[str],
    *,
    expected_handoff_sha256: str | None = None,
) -> PythonProducerAdmissionHandoff:
    """Read exact canonical bytes through held no-follow directories; never modify them."""

    if expected_handoff_sha256 is not None:
        _sha(expected_handoff_sha256, "expected_digest_invalid")
    parsed = parse_python_producer_admission_handoff(_read_path(_path(path)))
    if expected_handoff_sha256 is not None and parsed.handoff_sha256 != expected_handoff_sha256:
        _fail("digest_mismatch")
    return parsed


def persist_python_producer_admission_handoff(
    path: str | os.PathLike[str],
    *,
    handoff: PythonProducerAdmissionHandoff | Mapping[str, object],
) -> PythonProducerAdmissionHandoff:
    """Create one handoff through a held parent FD and replay only exact existing bytes.

    The caller owns the existing parent directory.  All ancestors are opened no-follow and
    rechecked before acknowledgement.  Once the exclusive file is created, any write or identity
    failure retains its unknown bytes for inspection.  No failure unlinks a name or deletes a
    competing inode, and a retry cannot overwrite that retained evidence.
    """

    if isinstance(handoff, Mapping):
        parsed = (
            parse_python_producer_admission_handoff(handoff)
            if "handoff_sha256" in handoff
            else build_python_producer_admission_handoff(handoff)
        )
    else:
        parsed = parse_python_producer_admission_handoff(handoff)
    destination = _path(path)
    raw = parsed.to_json()
    chain = _directory(destination)
    descriptor = -1
    try:
        _check_directory(chain)
        try:
            descriptor = os.open(
                destination.name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600, dir_fd=chain.fd,
            )
        except FileExistsError:
            observed_raw = _read_file(chain, destination.name)
            observed = parse_python_producer_admission_handoff(observed_raw)
            if observed_raw != raw:
                _fail("already_exists")
            return observed
        created = os.fstat(descriptor)
        inode = (created.st_dev, created.st_ino)
        if (not stat.S_ISREG(created.st_mode) or stat.S_IMODE(created.st_mode) != 0o600
                or created.st_nlink != 1):
            _fail("file_identity_drift")
        offset = 0
        while offset < len(raw):
            count = os.write(descriptor, raw[offset:])
            if count <= 0:
                _fail("write_unknown")
            offset += count
        os.fsync(descriptor)
        written = os.fstat(descriptor)
        named = os.stat(destination.name, dir_fd=chain.fd, follow_symlinks=False)
        if ((written.st_dev, written.st_ino) != inode or _metadata(written) != _metadata(named)
                or not stat.S_ISREG(written.st_mode) or stat.S_IMODE(written.st_mode) != 0o600
                or written.st_nlink != 1 or written.st_size != len(raw)):
            _fail("file_identity_drift")
        _check_directory(chain)
        os.fsync(chain.fd)
        reread = _read_file(chain, destination.name, expected_inode=inode)
        if reread != raw:
            _fail("file_identity_drift")
        return parse_python_producer_admission_handoff(reread)
    except PythonProducerAdmissionHandoffError:
        raise
    except (OSError, ValueError) as exc:
        raise PythonProducerAdmissionHandoffError("write_unknown") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        chain.close()


def replay_python_producer_admission_handoff_file(
    path: str | os.PathLike[str],
    *,
    expected_handoff_sha256: str | None = None,
) -> PythonProducerAdmissionHandoff:
    """Read a persisted handoff and apply the terminal replay state gate."""

    return replay_python_producer_admission_handoff(
        read_python_producer_admission_handoff(
            path, expected_handoff_sha256=expected_handoff_sha256,
        )
    )


__all__ = [
    "HANDOFF_STATE_EVALUATING", "HANDOFF_STATE_PREPARED", "HANDOFF_STATE_PUBLISHED",
    "HANDOFF_STATE_REJECTED", "HANDOFF_STATE_STAGED", "HANDOFF_STATE_UNKNOWN",
    "MAX_PYTHON_PRODUCER_ADMISSION_HANDOFF_BYTES", "PYTHON_PRODUCER_ADMISSION_HANDOFF_NAME",
    "PYTHON_PRODUCER_ADMISSION_HANDOFF_PROTOCOL", "PYTHON_PRODUCER_ADMISSION_HANDOFF_SCHEMA_VERSION",
    "PythonProducerAdmissionHandoff", "PythonProducerAdmissionHandoffError",
    "build_python_producer_admission_handoff", "parse_python_producer_admission_handoff",
    "persist_python_producer_admission_handoff", "prepare_python_producer_admission_handoff",
    "read_python_producer_admission_handoff", "reconcile_python_producer_admission_handoff",
    "replay_python_producer_admission_handoff", "replay_python_producer_admission_handoff_file",
]
