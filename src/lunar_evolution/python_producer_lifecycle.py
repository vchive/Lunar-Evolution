"""Pure Python producer terminal and runtime-observation lifecycle contracts.

Feature191's process launcher is intentionally not implemented here.  This module validates
detached, canonical observations and provides a small facade over the existing native recovery
reader.  It applies the same fail-closed rules used by the native lifecycle: a missing process or
cleanup record is ``unknown`` and can never be published; resume/reconcile only replays retained
records and never starts a process, spends a budget, or writes a second journal.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from .producer_process import (
    ProducerExecutionReceipt,
    ProducerProcessError,
    ProducerStreamEvidence,
    parse_producer_execution_receipt,
    recover_producer_process,
)
from .python_producer_binding import (
    PythonProducerBinding,
    PythonProducerBindingError,
    parse_python_producer_binding,
)

PYTHON_PRODUCER_TERMINAL_PROTOCOL = "lunar-python-producer-terminal-v1"
PYTHON_RUNTIME_OBSERVATION_PROTOCOL = "lunar-python-runtime-observation-v1"
PYTHON_PRODUCER_SCHEMA_VERSION = "1"
MAX_PYTHON_TERMINAL_BYTES = 256 * 1024
MAX_PYTHON_OBSERVATION_BYTES = 256 * 1024
MAX_PYTHON_SEQUENCE = 256
MAX_PYTHON_STRING_BYTES = 4096
MAX_PYTHON_PATH_BYTES = 4096

_SHA = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SAFE_TEXT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/+@=-]{0,4095}$")
_STATUSES = frozenset({"completed", "failed", "cancelled", "unknown"})
_CLEANUP = frozenset({"cleaned", "already_exited", "unknown", "missing"})
_TERMINAL_FIELDS = frozenset({
    "schema_version", "protocol", "binding_sha256", "run_id", "journal_id", "launch_id",
    "process_registration_sha256", "owner_identity_sha256", "executable_sha256", "executable_size",
    "executable_device", "executable_inode", "started_unix", "released_unix", "exited_unix",
    "deadline_unix", "status", "exit_code", "signal", "cleanup_status", "request_journal_sha256",
    "request_count", "stdout_sha256", "stderr_sha256", "publication_eligible", "terminal_sha256",
})
_OBSERVATION_FIELDS = frozenset({
    "schema_version", "protocol", "binding_sha256", "execution_performed", "version_major",
    "version_minor", "version_micro", "cache_tag", "abi_profile", "argv", "orig_argv", "flags",
    "filesystem_encoding", "filesystem_errors", "stdio_encoding", "stdio_errors", "sys_path",
    "startup_modules", "broker_transcript_sha256", "pycache_absent", "computation_sha256",
    "runtime_load_protection", "production_admission", "general_code_origin_protection",
    "observation_sha256",
})


class PythonProducerLifecycleError(ValueError):
    """Fixed-code rejection without producer-controlled paths or prose."""

    def __init__(self, code: str) -> None:
        self.code = "python_producer_lifecycle_" + code
        super().__init__(self.code)


def _fail(code: str) -> NoReturn:
    raise PythonProducerLifecycleError(code)


def _canonical(value: object, maximum: int) -> bytes:
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        raise PythonProducerLifecycleError("json_invalid") from exc
    if len(raw) > maximum:
        _fail("record_too_large")
    return raw


def _strict_json(value: bytes | str, maximum: int) -> tuple[object, bytes]:
    if type(value) not in {bytes, str}:
        _fail("json_invalid")
    try:
        raw = value if type(value) is bytes else value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise PythonProducerLifecycleError("json_invalid") from exc
    if len(raw) > maximum:
        _fail("record_too_large")

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in items:
            if key in result:
                _fail("duplicate_json_key")
            result[key] = item
        return result

    try:
        parsed = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=lambda _: _fail("json_invalid"))
    except PythonProducerLifecycleError:
        raise
    except (UnicodeDecodeError, TypeError, ValueError, RecursionError) as exc:
        raise PythonProducerLifecycleError("json_invalid") from exc
    if _canonical(parsed, maximum) != raw:
        _fail("noncanonical_json")
    return parsed, raw


def _object(value: object, fields: frozenset[str]) -> dict[str, Any]:
    if (type(value) is not dict or len(value) != len(fields)
            or any(type(key) is not str for key in value) or set(value) != fields):
        _fail("schema_invalid")
    return value


def _sha(value: object, code: str = "digest_invalid", *, allow_none: bool = False) -> str | None:
    if allow_none and value is None:
        return None
    if type(value) is not str or _SHA.fullmatch(value) is None or value == "0" * 64:
        _fail(code)
    return value


def _identifier(value: object, code: str = "identity_invalid") -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        _fail(code)
    return value


def _text(value: object, code: str = "text_invalid", *, empty: bool = False) -> str:
    if type(value) is not str or (not empty and not value) or len(value) > MAX_PYTHON_STRING_BYTES:
        _fail(code)
    try:
        if len(value.encode("utf-8")) > MAX_PYTHON_STRING_BYTES:
            _fail(code)
    except UnicodeEncodeError:
        _fail(code)
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        _fail(code)
    return value


def _safe_text(value: object, code: str = "text_invalid") -> str:
    if type(value) is not str or _SAFE_TEXT.fullmatch(value) is None:
        _fail(code)
    return value


def _integer(value: object, code: str, minimum: int = 0, maximum: int = 2**64 - 1, *, optional: bool = False) -> int | None:
    if optional and value is None:
        return None
    if type(value) is not int or not minimum <= value <= maximum:
        _fail(code)
    return value


def _timestamp(value: object, code: str, *, optional: bool = True) -> float | None:
    if optional and value is None:
        return None
    if type(value) not in {int, float} or isinstance(value, bool):
        _fail(code)
    try:
        result = float(value)
    except OverflowError:
        _fail(code)
    if not math.isfinite(result) or result < 0:
        _fail(code)
    return result


def _sequence(
    value: object, code: str, *, item: str = "text", maximum: int = MAX_PYTHON_SEQUENCE,
    wire: bool = True,
) -> tuple[str, ...]:
    if type(value) is not (list if wire else tuple) or not 0 <= len(value) <= maximum:
        _fail(code)
    result: list[str] = []
    for item_value in value:
        if item == "path":
            text = _text(item_value, code)
            if len(text.encode("utf-8")) > MAX_PYTHON_PATH_BYTES or text.startswith("/") or "\\" in text or "\x00" in text:
                _fail(code)
            result.append(text)
        else:
            result.append(_text(item_value, code))
    return tuple(result)


def _digest_without(value: Mapping[str, object], field: str, maximum: int) -> str:
    body = dict(value)
    body.pop(field, None)
    return hashlib.sha256(_canonical(body, maximum)).hexdigest()


def _expected_binding(value: str | PythonProducerBinding | Mapping[str, object]) -> tuple[str, float]:
    if type(value) is PythonProducerBinding:
        try:
            parsed = parse_python_producer_binding(value.to_json())
        except PythonProducerBindingError as exc:
            raise PythonProducerLifecycleError("binding_invalid") from exc
        return parsed.binding_sha256, float(parsed.deadline_unix)
    if type(value) is str:
        _sha(value)
        return value, math.nan
    if type(value) is dict:
        _object(value, frozenset({"binding_sha256", "deadline_unix"}))
        digest = value.get("binding_sha256")
        deadline = value.get("deadline_unix")
        _sha(digest)
        parsed = _timestamp(deadline, "deadline_invalid", optional=False)
        assert parsed is not None
        return digest, parsed
    _fail("binding_invalid")


@dataclass(frozen=True, slots=True)
class PythonProducerTerminal:
    """Digest-bound process terminal; no terminal grants publication by itself."""

    binding_sha256: str
    run_id: str
    journal_id: str
    launch_id: str
    process_registration_sha256: str | None
    owner_identity_sha256: str | None
    executable_sha256: str | None
    executable_size: int | None
    executable_device: int | None
    executable_inode: int | None
    started_unix: float | None
    released_unix: float | None
    exited_unix: float | None
    deadline_unix: float
    status: str
    exit_code: int | None
    signal: int | None
    cleanup_status: str
    request_journal_sha256: str | None
    request_count: int
    stdout_sha256: str
    stderr_sha256: str
    publication_eligible: bool = False
    terminal_sha256: str | None = None
    schema_version: str = PYTHON_PRODUCER_SCHEMA_VERSION
    protocol: str = PYTHON_PRODUCER_TERMINAL_PROTOCOL

    def __post_init__(self) -> None:
        if (type(self.schema_version) is not str or type(self.protocol) is not str
                or self.schema_version != PYTHON_PRODUCER_SCHEMA_VERSION or self.protocol != PYTHON_PRODUCER_TERMINAL_PROTOCOL):
            _fail("schema_invalid")
        _sha(self.binding_sha256)
        for value in (self.run_id, self.journal_id, self.launch_id):
            _identifier(value)
        for value in (self.process_registration_sha256, self.owner_identity_sha256, self.executable_sha256, self.request_journal_sha256):
            _sha(value, allow_none=True)
        for name in ("executable_size", "executable_device", "executable_inode"):
            _integer(getattr(self, name), f"{name}_invalid", optional=True)
        for name in ("started_unix", "released_unix", "exited_unix"):
            _timestamp(getattr(self, name), f"{name}_invalid")
        deadline = _timestamp(self.deadline_unix, "deadline_unix_invalid", optional=False)
        if deadline == 0:
            _fail("deadline_unix_invalid")
        if type(self.status) is not str or self.status not in _STATUSES:
            _fail("status_invalid")
        if type(self.cleanup_status) is not str or self.cleanup_status not in _CLEANUP:
            _fail("cleanup_status_invalid")
        _integer(self.exit_code, "exit_code_invalid", minimum=-2**31, maximum=2**31 - 1, optional=True)
        _integer(self.signal, "signal_invalid", minimum=1, maximum=255, optional=True)
        _integer(self.request_count, "request_count_invalid", maximum=10_000_000_000)
        _sha(self.stdout_sha256)
        _sha(self.stderr_sha256)
        if type(self.publication_eligible) is not bool:
            _fail("publication_flag_invalid")
        # This pure terminal has no envelope/evaluator/publication receipt and
        # therefore cannot assert publication authority, even for exit 0.
        if self.publication_eligible:
            _fail("unsupported_publication_claim")
        if (self.started_unix is not None and self.released_unix is not None
                and self.started_unix > self.released_unix) or (
                self.released_unix is not None and self.exited_unix is not None
                and self.released_unix > self.exited_unix):
            _fail("terminal_time_order_invalid")
        if self.status != "unknown":
            if any(value is None for value in (
                self.process_registration_sha256, self.owner_identity_sha256, self.executable_sha256,
                self.executable_size, self.executable_device, self.executable_inode,
                self.started_unix, self.released_unix, self.exited_unix, self.request_journal_sha256,
            )):
                _fail("terminal_evidence_missing")
            if self.executable_inode == 0 or self.executable_size == 0:
                _fail("terminal_executable_identity_invalid")
            if self.cleanup_status not in {"cleaned", "already_exited"}:
                _fail("terminal_cleanup_unverified")
            if self.exit_code is None and self.signal is None:
                _fail("terminal_exit_evidence_missing")
        if self.status == "unknown":
            if self.publication_eligible:
                _fail("unknown_publication_eligible")
        elif self.status == "completed":
            if self.exit_code != 0 or self.signal is not None or self.cleanup_status not in {"cleaned", "already_exited"}:
                _fail("completed_evidence_invalid")
            if any(value is None for value in (self.process_registration_sha256, self.owner_identity_sha256, self.executable_sha256, self.request_journal_sha256, self.exited_unix)):
                _fail("completed_evidence_missing")
            if self.exited_unix >= deadline:
                _fail("completed_deadline_exceeded")
        else:
            if self.publication_eligible:
                _fail("noncompleted_publication_eligible")
        if self.terminal_sha256 is not None:
            _sha(self.terminal_sha256)
            if self.terminal_sha256 != self._digest_unchecked():
                _fail("terminal_digest_mismatch")

    def _to_dict_unchecked(self, *, include_digest: bool = True) -> dict[str, object]:
        result: dict[str, object] = {
            "schema_version": self.schema_version, "protocol": self.protocol,
            "binding_sha256": self.binding_sha256, "run_id": self.run_id,
            "journal_id": self.journal_id, "launch_id": self.launch_id,
            "process_registration_sha256": self.process_registration_sha256,
            "owner_identity_sha256": self.owner_identity_sha256, "executable_sha256": self.executable_sha256,
            "executable_size": self.executable_size, "executable_device": self.executable_device,
            "executable_inode": self.executable_inode, "started_unix": self.started_unix,
            "released_unix": self.released_unix, "exited_unix": self.exited_unix,
            "deadline_unix": self.deadline_unix, "status": self.status, "exit_code": self.exit_code,
            "signal": self.signal, "cleanup_status": self.cleanup_status,
            "request_journal_sha256": self.request_journal_sha256, "request_count": self.request_count,
            "stdout_sha256": self.stdout_sha256, "stderr_sha256": self.stderr_sha256,
            "publication_eligible": self.publication_eligible,
        }
        if include_digest:
            result["terminal_sha256"] = self.terminal_sha256
        return result

    def _digest_unchecked(self) -> str:
        return _digest_without(self._to_dict_unchecked(include_digest=False), "terminal_sha256", MAX_PYTHON_TERMINAL_BYTES)

    def digest(self) -> str:
        self.__post_init__()
        return self._digest_unchecked()

    def to_dict(self) -> dict[str, object]:
        self.__post_init__()
        result = self._to_dict_unchecked()
        if result["terminal_sha256"] is None:
            result["terminal_sha256"] = self.digest()
        return result

    def to_json(self) -> bytes:
        return _canonical(self.to_dict(), MAX_PYTHON_TERMINAL_BYTES)


@dataclass(frozen=True, slots=True)
class PythonProducerRuntimeObservation:
    """Observed runtime facts emitted by the process; protection claims stay false."""

    binding_sha256: str
    execution_performed: bool
    version_major: int
    version_minor: int
    version_micro: int
    cache_tag: str
    abi_profile: str
    argv: tuple[str, ...]
    orig_argv: tuple[str, ...]
    flags: tuple[str, ...]
    filesystem_encoding: str
    filesystem_errors: str
    stdio_encoding: str
    stdio_errors: str
    sys_path: tuple[str, ...]
    startup_modules: tuple[str, ...]
    broker_transcript_sha256: str
    pycache_absent: bool
    computation_sha256: str
    runtime_load_protection: bool = False
    production_admission: bool = False
    general_code_origin_protection: bool = False
    observation_sha256: str | None = None
    schema_version: str = PYTHON_PRODUCER_SCHEMA_VERSION
    protocol: str = PYTHON_RUNTIME_OBSERVATION_PROTOCOL

    def __post_init__(self) -> None:
        if (type(self.schema_version) is not str or type(self.protocol) is not str
                or self.schema_version != PYTHON_PRODUCER_SCHEMA_VERSION or self.protocol != PYTHON_RUNTIME_OBSERVATION_PROTOCOL):
            _fail("schema_invalid")
        _sha(self.binding_sha256)
        if type(self.execution_performed) is not bool:
            _fail("execution_flag_invalid")
        for name in ("version_major", "version_minor", "version_micro"):
            _integer(getattr(self, name), f"{name}_invalid", maximum=999)
        for name in ("cache_tag", "abi_profile", "filesystem_encoding", "filesystem_errors", "stdio_encoding", "stdio_errors"):
            _text(getattr(self, name), f"{name}_invalid")
        _sequence(self.argv, "argv_invalid", wire=False)
        _sequence(self.orig_argv, "orig_argv_invalid", wire=False)
        _sequence(self.flags, "flags_invalid", wire=False)
        _sequence(self.sys_path, "sys_path_invalid", item="path", wire=False)
        _sequence(self.startup_modules, "startup_modules_invalid", wire=False)
        _sha(self.broker_transcript_sha256)
        _sha(self.computation_sha256)
        if type(self.pycache_absent) is not bool:
            _fail("pycache_flag_invalid")
        for name in ("runtime_load_protection", "production_admission", "general_code_origin_protection"):
            if getattr(self, name) is not False:
                _fail("unsupported_protection_claim")
        if self.execution_performed is not True:
            _fail("execution_not_observed")
        if self.observation_sha256 is not None:
            _sha(self.observation_sha256)
            if self.observation_sha256 != self._digest_unchecked():
                _fail("observation_digest_mismatch")

    def _to_dict_unchecked(self, *, include_digest: bool = True) -> dict[str, object]:
        result: dict[str, object] = {
            "schema_version": self.schema_version, "protocol": self.protocol,
            "binding_sha256": self.binding_sha256, "execution_performed": self.execution_performed,
            "version_major": self.version_major, "version_minor": self.version_minor,
            "version_micro": self.version_micro, "cache_tag": self.cache_tag,
            "abi_profile": self.abi_profile, "argv": list(self.argv), "orig_argv": list(self.orig_argv),
            "flags": list(self.flags), "filesystem_encoding": self.filesystem_encoding,
            "filesystem_errors": self.filesystem_errors, "stdio_encoding": self.stdio_encoding,
            "stdio_errors": self.stdio_errors, "sys_path": list(self.sys_path),
            "startup_modules": list(self.startup_modules), "broker_transcript_sha256": self.broker_transcript_sha256,
            "pycache_absent": self.pycache_absent, "computation_sha256": self.computation_sha256,
            "runtime_load_protection": self.runtime_load_protection,
            "production_admission": self.production_admission,
            "general_code_origin_protection": self.general_code_origin_protection,
        }
        if include_digest:
            result["observation_sha256"] = self.observation_sha256
        return result

    def _digest_unchecked(self) -> str:
        return _digest_without(self._to_dict_unchecked(include_digest=False), "observation_sha256", MAX_PYTHON_OBSERVATION_BYTES)

    def digest(self) -> str:
        self.__post_init__()
        return self._digest_unchecked()

    def to_dict(self) -> dict[str, object]:
        self.__post_init__()
        result = self._to_dict_unchecked()
        if result["observation_sha256"] is None:
            result["observation_sha256"] = self.digest()
        return result

    def to_json(self) -> bytes:
        return _canonical(self.to_dict(), MAX_PYTHON_OBSERVATION_BYTES)


def parse_python_producer_terminal(value: bytes | str | Mapping[str, object]) -> PythonProducerTerminal:
    if type(value) is dict:
        raw = value
    else:
        raw, _ = _strict_json(value, MAX_PYTHON_TERMINAL_BYTES)
    fields = _object(raw, _TERMINAL_FIELDS)
    _sha(fields["terminal_sha256"])
    try:
        return PythonProducerTerminal(
            schema_version=fields["schema_version"], protocol=fields["protocol"], binding_sha256=fields["binding_sha256"],
            run_id=fields["run_id"], journal_id=fields["journal_id"], launch_id=fields["launch_id"],
            process_registration_sha256=fields["process_registration_sha256"], owner_identity_sha256=fields["owner_identity_sha256"],
            executable_sha256=fields["executable_sha256"], executable_size=fields["executable_size"],
            executable_device=fields["executable_device"], executable_inode=fields["executable_inode"],
            started_unix=fields["started_unix"], released_unix=fields["released_unix"], exited_unix=fields["exited_unix"],
            deadline_unix=fields["deadline_unix"], status=fields["status"], exit_code=fields["exit_code"], signal=fields["signal"],
            cleanup_status=fields["cleanup_status"], request_journal_sha256=fields["request_journal_sha256"],
            request_count=fields["request_count"], stdout_sha256=fields["stdout_sha256"], stderr_sha256=fields["stderr_sha256"],
            publication_eligible=fields["publication_eligible"], terminal_sha256=fields["terminal_sha256"],
        )
    except PythonProducerLifecycleError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise PythonProducerLifecycleError("schema_invalid") from exc


def parse_python_producer_runtime_observation(value: bytes | str | Mapping[str, object]) -> PythonProducerRuntimeObservation:
    if type(value) is dict:
        raw = value
    else:
        raw, _ = _strict_json(value, MAX_PYTHON_OBSERVATION_BYTES)
    fields = _object(raw, _OBSERVATION_FIELDS)
    _sha(fields["observation_sha256"])
    try:
        return PythonProducerRuntimeObservation(
            schema_version=fields["schema_version"], protocol=fields["protocol"], binding_sha256=fields["binding_sha256"],
            execution_performed=fields["execution_performed"], version_major=fields["version_major"], version_minor=fields["version_minor"],
            version_micro=fields["version_micro"], cache_tag=fields["cache_tag"], abi_profile=fields["abi_profile"],
            argv=_sequence(fields["argv"], "argv_invalid"), orig_argv=_sequence(fields["orig_argv"], "orig_argv_invalid"), flags=_sequence(fields["flags"], "flags_invalid"),
            filesystem_encoding=fields["filesystem_encoding"], filesystem_errors=fields["filesystem_errors"],
            stdio_encoding=fields["stdio_encoding"], stdio_errors=fields["stdio_errors"], sys_path=_sequence(fields["sys_path"], "sys_path_invalid", item="path"),
            startup_modules=_sequence(fields["startup_modules"], "startup_modules_invalid"), broker_transcript_sha256=fields["broker_transcript_sha256"],
            pycache_absent=fields["pycache_absent"], computation_sha256=fields["computation_sha256"],
            runtime_load_protection=fields["runtime_load_protection"], production_admission=fields["production_admission"],
            general_code_origin_protection=fields["general_code_origin_protection"], observation_sha256=fields["observation_sha256"],
        )
    except PythonProducerLifecycleError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise PythonProducerLifecycleError("schema_invalid") from exc


def build_python_producer_terminal(**kwargs: Any) -> PythonProducerTerminal:
    """Construct one terminal and freeze its self-digest without any side effects."""
    item = PythonProducerTerminal(**kwargs)
    if item.terminal_sha256 is None:
        item = PythonProducerTerminal(**{**kwargs, "terminal_sha256": item._digest_unchecked()})
    return item


def build_python_producer_runtime_observation(**kwargs: Any) -> PythonProducerRuntimeObservation:
    """Construct one observed runtime record and freeze its self-digest."""
    item = PythonProducerRuntimeObservation(**kwargs)
    if item.observation_sha256 is None:
        item = PythonProducerRuntimeObservation(**{**kwargs, "observation_sha256": item._digest_unchecked()})
    return item


def bind_python_producer_receipt(
    binding: PythonProducerBinding, receipt: ProducerExecutionReceipt,
) -> PythonProducerTerminal:
    """Project the existing process receipt into this adapter's terminal view.

    The process receipt remains the sole durable process schema.  This projection copies only
    fields already verified by ``ProducerExecutionReceipt`` and deliberately never upgrades a
    missing/uncertain cleanup or request journal into a completed publication.
    """
    if type(binding) is not PythonProducerBinding:
        _fail("binding_invalid")
    if type(receipt) is not ProducerExecutionReceipt:
        _fail("receipt_invalid")
    expected_binding, _ = _expected_binding(binding)
    # The process builder may return a fresh DTO before its optional self field
    # is populated. Reparse its exact wire to validate that construction. An
    # already retained digest must still match and cannot be silently replaced.
    if receipt.receipt_sha256 is not None:
        _sha(receipt.receipt_sha256, "receipt_digest_invalid")
    if type(receipt.owner_identity) is not dict:
        _fail("receipt_owner_invalid")
    if type(receipt.stdout_evidence) is not ProducerStreamEvidence or type(receipt.stderr_evidence) is not ProducerStreamEvidence:
        _fail("receipt_stream_invalid")
    try:
        receipt = parse_producer_execution_receipt(receipt.to_dict())
    except (ProducerProcessError, TypeError, ValueError) as exc:
        raise PythonProducerLifecycleError("receipt_invalid") from exc
    if receipt.run_id != binding.run_id or receipt.journal_id != binding.intent.journal_id or receipt.launch_id != binding.intent.launch_id:
        _fail("receipt_identity_drift")
    if receipt.intent_sha256 != binding.intent_sha256 or receipt.attestation_sha256 != binding.attestation_sha256:
        _fail("receipt_binding_drift")
    if (receipt.parent_task_id != binding.parent_task_id or receipt.task_id != binding.task_id
            or receipt.execution_snapshot_sha256 != binding.interpreter_sha256
            or receipt.execution_snapshot_size != binding.interpreter.size
            or receipt.max_requests != binding.request_budget
            or receipt.request_timeout_seconds != binding.intent.request_timeout_seconds
            or receipt.output_max_bytes != binding.output_max_bytes
            or receipt.wall_timeout_seconds != binding.wall_timeout_seconds):
        _fail("receipt_binding_drift")
    try:
        owner_digest = hashlib.sha256(_canonical(dict(receipt.owner_identity), MAX_PYTHON_TERMINAL_BYTES)).hexdigest()
    except Exception as exc:
        raise PythonProducerLifecycleError("receipt_owner_invalid") from exc
    # Feature156's receipt intentionally does not carry wall-clock timestamps.  Keep this
    # projection unknown until a later observation supplies those fields; never fabricate them.
    # No receipt status supplies the missing wall-clock observation. Known
    # failure/cancellation also needs an observed terminal before reconciliation.
    status = "unknown"
    return build_python_producer_terminal(
        binding_sha256=expected_binding,
        run_id=receipt.run_id,
        journal_id=receipt.journal_id,
        launch_id=receipt.launch_id,
        process_registration_sha256=receipt.registration_sha256,
        owner_identity_sha256=owner_digest,
        executable_sha256=receipt.execution_snapshot_sha256,
        executable_size=receipt.execution_snapshot_size,
        executable_device=None,
        executable_inode=None,
        started_unix=None,
        released_unix=None,
        exited_unix=None,
        deadline_unix=binding.deadline_unix,
        status=status,
        exit_code=receipt.exit_code,
        signal=None,
        cleanup_status=receipt.cleanup_status if type(receipt.cleanup_status) is str and receipt.cleanup_status in _CLEANUP else "unknown",
        # Attestation consumption is not an authenticated broker request journal.
        request_journal_sha256=None,
        request_count=receipt.request_count or 0,
        stdout_sha256=receipt.stdout_evidence.sha256,
        stderr_sha256=receipt.stderr_evidence.sha256,
        publication_eligible=False,
    )


def recover_python_producer_terminal(
    workspace: str | Path,
    *,
    binding: PythonProducerBinding,
) -> PythonProducerTerminal:
    """Project one retained native process receipt into the Python terminal contract.

    Recovery delegates all durable file, ownership and journal checks to the existing native
    process recovery boundary.  A missing terminal or an explicit recovery receipt stays a
    refusal: this adapter never relaunches a producer, consumes an attestation, evaluates an
    envelope, or turns an ``unknown`` observation into success.  A complete native receipt is
    still projected as ``unknown`` until the separate wall-clock/runtime observation supplies the
    fields required by :func:`resume_python_producer_terminal` or reconciliation.
    """
    if type(binding) is not PythonProducerBinding:
        _fail("binding_invalid")
    if not isinstance(workspace, (str, Path)) or not workspace:
        _fail("workspace_invalid")
    try:
        observed = recover_producer_process(
            workspace, journal_id=binding.intent.journal_id, cleanup=False,
        )
    except ProducerProcessError as exc:
        # Native recovery exposes only fixed process codes.  Keep those details out of the
        # Python adapter wire while preserving the original exception as a diagnostic cause.
        raise PythonProducerLifecycleError("recovery_observation_invalid") from exc
    except (OSError, TypeError, ValueError) as exc:
        raise PythonProducerLifecycleError("recovery_observation_invalid") from exc
    if type(observed) is not dict:
        _fail("recovery_observation_invalid")
    status = observed.get("status")
    if status == "recovery_required":
        _fail("recovery_required")
    if status not in {"completed", "failed", "cancelled", "unknown"}:
        _fail("journal_mismatch")
    cleanup_status = observed.get("cleanup_status")
    if cleanup_status not in {"cleaned", "already_exited", "unknown", "missing"}:
        _fail("recovery_receipt_invalid")
    if cleanup_status in {"unknown", "missing"}:
        _fail("cleanup_unknown")
    try:
        receipt = parse_producer_execution_receipt(observed)
    except (ProducerProcessError, TypeError, ValueError) as exc:
        raise PythonProducerLifecycleError("recovery_receipt_invalid") from exc
    try:
        return bind_python_producer_receipt(binding, receipt)
    except PythonProducerLifecycleError:
        raise
    except (TypeError, ValueError) as exc:
        raise PythonProducerLifecycleError("recovery_binding_invalid") from exc


def _retained_terminal(value: object) -> PythonProducerTerminal:
    if type(value) is PythonProducerTerminal:
        # Frozen DTOs can still be changed via object.__setattr__. The retained
        # digest must be verified whenever a DTO is reused as lifecycle input.
        value.__post_init__()
        _sha(value.terminal_sha256)
        return value
    return parse_python_producer_terminal(value)


def _terminal_binding_pins(item: PythonProducerTerminal, binding: object) -> None:
    if type(binding) is not PythonProducerBinding:
        return
    expected = {
        "run_id": binding.run_id, "journal_id": binding.intent.journal_id,
        "launch_id": binding.intent.launch_id,
        "executable_sha256": binding.interpreter_sha256,
        "executable_size": binding.interpreter.size,
        "executable_device": binding.interpreter.device,
        "executable_inode": binding.interpreter.inode,
    }
    for name, pin in expected.items():
        value = getattr(item, name)
        if value is not None and value != pin:
            _fail("binding_identity_drift")
    if item.request_count > binding.request_budget:
        _fail("request_budget_exceeded")


def reconcile_python_producer_terminal(
    previous: PythonProducerTerminal | bytes | str | Mapping[str, object],
    observed: PythonProducerTerminal | bytes | str | Mapping[str, object],
    *, expected_binding: str | PythonProducerBinding | Mapping[str, object],
    expected_deadline_unix: float | None = None,
) -> PythonProducerTerminal:
    """Reconcile retained terminal evidence without I/O, mutation, retry or publication."""
    old = _retained_terminal(previous)
    new = _retained_terminal(observed)
    binding, bound_deadline = _expected_binding(expected_binding)
    if expected_deadline_unix is not None:
        parsed = _timestamp(expected_deadline_unix, "deadline_invalid", optional=False)
        assert parsed is not None
        if not math.isnan(bound_deadline) and parsed != bound_deadline:
            _fail("deadline_drift")
        bound_deadline = parsed
    for item in (old, new):
        if item.binding_sha256 != binding:
            _fail("binding_drift")
        if item.deadline_unix != bound_deadline and not math.isnan(bound_deadline):
            _fail("deadline_drift")
        if item.run_id != old.run_id or item.journal_id != old.journal_id or item.launch_id != old.launch_id:
            _fail("identity_drift")
        _terminal_binding_pins(item, expected_binding)
    if new.deadline_unix != old.deadline_unix:
        _fail("deadline_drift")
    if old.status in {"completed", "failed", "cancelled"}:
        if new != old:
            _fail("terminal_immutable")
        return old
    if old.status != "unknown":
        _fail("previous_status_invalid")
    if old.publication_eligible:
        _fail("unknown_publication_eligible")
    for name in (
        "process_registration_sha256", "owner_identity_sha256", "executable_sha256",
        "executable_size", "executable_device", "executable_inode", "request_journal_sha256",
        "started_unix", "released_unix", "exited_unix", "exit_code", "signal",
        "stdout_sha256", "stderr_sha256",
    ):
        pin = getattr(old, name)
        if pin is not None and getattr(new, name) != pin:
            _fail("retained_evidence_drift")
    if old.cleanup_status not in {"unknown", "missing"} and new.cleanup_status != old.cleanup_status:
        _fail("retained_evidence_drift")
    if new.request_count < old.request_count or (
            old.request_journal_sha256 is not None and new.request_count != old.request_count):
        _fail("request_count_drift")
    # Unknown can only be resolved by a terminal record with complete process/cleanup evidence.
    if new.status == "unknown":
        if new != old:
            _fail("unknown_conflict")
        return old
    if new.status == "completed":
        if new.cleanup_status not in {"cleaned", "already_exited"} or new.exit_code != 0:
            _fail("reconcile_evidence_missing")
    elif new.status in {"failed", "cancelled"} and (
            new.cleanup_status not in {"cleaned", "already_exited"}
            or new.process_registration_sha256 is None
            or new.owner_identity_sha256 is None
    ):
            _fail("reconcile_evidence_missing")
    return new


def resume_python_producer_terminal(
    terminal: PythonProducerTerminal | bytes | str | Mapping[str, object], *,
    expected_binding: str | PythonProducerBinding | Mapping[str, object], expected_deadline_unix: float | None = None,
) -> PythonProducerTerminal:
    """Validate a retained terminal for resume; unknown state remains reconcile-required."""
    item = _retained_terminal(terminal)
    binding, deadline = _expected_binding(expected_binding)
    if expected_deadline_unix is not None:
        parsed = _timestamp(expected_deadline_unix, "deadline_invalid", optional=False)
        assert parsed is not None
        if not math.isnan(deadline) and parsed != deadline:
            _fail("deadline_drift")
        deadline = parsed
    if item.binding_sha256 != binding:
        _fail("binding_drift")
    if not math.isnan(deadline) and item.deadline_unix != deadline:
        _fail("deadline_drift")
    _terminal_binding_pins(item, expected_binding)
    if item.status == "unknown":
        _fail("reconcile_required")
    return item


# Short aliases keep the adapter surface discoverable without colliding with the existing
# declaration-only ``producer_python_runtime.PythonRuntimeObservation``.
PythonRuntimeObservation = PythonProducerRuntimeObservation
parse_python_runtime_observation = parse_python_producer_runtime_observation

__all__ = [
    "PYTHON_PRODUCER_SCHEMA_VERSION",
    "PYTHON_PRODUCER_TERMINAL_PROTOCOL",
    "PYTHON_RUNTIME_OBSERVATION_PROTOCOL",
    "PythonProducerLifecycleError",
    "PythonProducerRuntimeObservation",
    "PythonProducerTerminal",
    "PythonRuntimeObservation",
    "bind_python_producer_receipt",
    "build_python_producer_runtime_observation",
    "build_python_producer_terminal",
    "parse_python_producer_runtime_observation",
    "parse_python_producer_terminal",
    "parse_python_runtime_observation",
    "reconcile_python_producer_terminal",
    "recover_python_producer_terminal",
    "resume_python_producer_terminal",
]
