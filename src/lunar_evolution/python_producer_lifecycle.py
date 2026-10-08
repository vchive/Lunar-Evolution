"""Pure Python producer terminal and runtime-observation lifecycle contracts.

Feature191's process launcher is intentionally not implemented here.  This module only
validates detached, canonical observations and applies the same fail-closed rules used by the
native lifecycle: a missing process or cleanup record is ``unknown`` and can never be published;
resume/reconcile only replays retained records and never starts a process, spends a budget, or
writes a journal.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, NoReturn

from .producer_process import ProducerExecutionReceipt
from .python_producer_binding import PythonProducerBinding

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
    raw = value if type(value) is bytes else value.encode("utf-8")
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
    if type(value) is not dict or set(value) != fields:
        _fail("schema_invalid")
    return value


def _sha(value: object, code: str = "digest_invalid", *, allow_none: bool = False) -> str | None:
    if allow_none and value is None:
        return None
    if type(value) is not str or _SHA.fullmatch(value) is None:
        _fail(code)
    return value


def _identifier(value: object, code: str = "identity_invalid") -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        _fail(code)
    return value


def _text(value: object, code: str = "text_invalid", *, empty: bool = False) -> str:
    if type(value) is not str or (not empty and not value) or len(value.encode("utf-8")) > MAX_PYTHON_STRING_BYTES:
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
    result = float(value)
    if not math.isfinite(result) or result < 0:
        _fail(code)
    return result


def _sequence(value: object, code: str, *, item: str = "text", maximum: int = MAX_PYTHON_SEQUENCE) -> tuple[str, ...]:
    if type(value) is not list or not 0 <= len(value) <= maximum:
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
    if isinstance(value, PythonProducerBinding):
        return value.binding_sha256 or value.digest(), float(value.deadline_unix)
    if type(value) is str:
        _sha(value)
        return value, math.nan
    if isinstance(value, Mapping):
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
        if self.schema_version != PYTHON_PRODUCER_SCHEMA_VERSION or self.protocol != PYTHON_PRODUCER_TERMINAL_PROTOCOL:
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
        _timestamp(self.deadline_unix, "deadline_unix_invalid", optional=False)
        if self.status not in _STATUSES:
            _fail("status_invalid")
        if self.cleanup_status not in _CLEANUP:
            _fail("cleanup_status_invalid")
        _integer(self.exit_code, "exit_code_invalid", minimum=-2**31, maximum=2**31 - 1, optional=True)
        _integer(self.signal, "signal_invalid", minimum=1, maximum=255, optional=True)
        _integer(self.request_count, "request_count_invalid", maximum=10_000_000_000)
        _sha(self.stdout_sha256)
        _sha(self.stderr_sha256)
        if type(self.publication_eligible) is not bool:
            _fail("publication_flag_invalid")
        if self.status == "unknown":
            if self.publication_eligible:
                _fail("unknown_publication_eligible")
        elif self.status == "completed":
            if self.exit_code != 0 or self.signal is not None or self.cleanup_status not in {"cleaned", "already_exited"}:
                _fail("completed_evidence_invalid")
            if any(value is None for value in (self.process_registration_sha256, self.owner_identity_sha256, self.executable_sha256, self.request_journal_sha256, self.exited_unix)):
                _fail("completed_evidence_missing")
            if not self.publication_eligible:
                # A verified terminal is still safe to retain without publishing; callers may
                # require the flag only after observing an envelope and local exact evaluation.
                pass
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
        if self.schema_version != PYTHON_PRODUCER_SCHEMA_VERSION or self.protocol != PYTHON_RUNTIME_OBSERVATION_PROTOCOL:
            _fail("schema_invalid")
        _sha(self.binding_sha256)
        if type(self.execution_performed) is not bool:
            _fail("execution_flag_invalid")
        for name in ("version_major", "version_minor", "version_micro"):
            _integer(getattr(self, name), f"{name}_invalid", maximum=999)
        for name in ("cache_tag", "abi_profile", "filesystem_encoding", "filesystem_errors", "stdio_encoding", "stdio_errors"):
            _text(getattr(self, name), f"{name}_invalid")
        _sequence(list(self.argv), "argv_invalid")
        _sequence(list(self.orig_argv), "orig_argv_invalid")
        _sequence(list(self.flags), "flags_invalid")
        _sequence(list(self.sys_path), "sys_path_invalid", item="path")
        _sequence(list(self.startup_modules), "startup_modules_invalid")
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
    if isinstance(value, Mapping):
        raw = dict(value)
    else:
        raw, _ = _strict_json(value, MAX_PYTHON_TERMINAL_BYTES)
    fields = _object(raw, _TERMINAL_FIELDS)
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
    if isinstance(value, Mapping):
        raw = dict(value)
    else:
        raw, _ = _strict_json(value, MAX_PYTHON_OBSERVATION_BYTES)
    fields = _object(raw, _OBSERVATION_FIELDS)
    try:
        return PythonProducerRuntimeObservation(
            schema_version=fields["schema_version"], protocol=fields["protocol"], binding_sha256=fields["binding_sha256"],
            execution_performed=fields["execution_performed"], version_major=fields["version_major"], version_minor=fields["version_minor"],
            version_micro=fields["version_micro"], cache_tag=fields["cache_tag"], abi_profile=fields["abi_profile"],
            argv=tuple(fields["argv"]), orig_argv=tuple(fields["orig_argv"]), flags=tuple(fields["flags"]),
            filesystem_encoding=fields["filesystem_encoding"], filesystem_errors=fields["filesystem_errors"],
            stdio_encoding=fields["stdio_encoding"], stdio_errors=fields["stdio_errors"], sys_path=tuple(fields["sys_path"]),
            startup_modules=tuple(fields["startup_modules"]), broker_transcript_sha256=fields["broker_transcript_sha256"],
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
    if not isinstance(binding, PythonProducerBinding):
        _fail("binding_invalid")
    if not isinstance(receipt, ProducerExecutionReceipt):
        _fail("receipt_invalid")
    expected_binding = binding.binding_sha256 or binding.digest()
    if receipt.run_id != binding.run_id or receipt.journal_id != binding.intent.journal_id or receipt.launch_id != binding.intent.launch_id:
        _fail("receipt_identity_drift")
    if receipt.intent_sha256 != binding.intent_sha256 or receipt.attestation_sha256 != binding.attestation_sha256:
        _fail("receipt_binding_drift")
    try:
        owner_digest = hashlib.sha256(_canonical(dict(receipt.owner_identity), MAX_PYTHON_TERMINAL_BYTES)).hexdigest()
    except Exception as exc:
        raise PythonProducerLifecycleError("receipt_owner_invalid") from exc
    status = receipt.status if receipt.status in _STATUSES else "unknown"
    # A process-only receipt cannot assert publication.  If any terminal or cleanup evidence is
    # absent, retain unknown so reconciliation is required before any future admission.
    if status == "recovery_required" or receipt.request_count is None or receipt.cleanup_status not in {"cleaned", "already_exited"}:
        status = "unknown"
    if status == "completed" and (receipt.exit_code != 0 or receipt.cleanup_status not in {"cleaned", "already_exited"}):
        status = "unknown"
    # Feature156's receipt intentionally does not carry wall-clock timestamps.  Keep this
    # projection unknown until a later observation supplies those fields; never fabricate them.
    if status == "completed":
        status = "unknown"
    return build_python_producer_terminal(
        binding_sha256=expected_binding,
        run_id=receipt.run_id,
        journal_id=receipt.journal_id,
        launch_id=receipt.launch_id,
        process_registration_sha256=receipt.registration_sha256,
        owner_identity_sha256=owner_digest,
        executable_sha256=receipt.executable_identity,
        executable_size=None,
        executable_device=None,
        executable_inode=None,
        started_unix=None,
        released_unix=None,
        exited_unix=None,
        deadline_unix=binding.deadline_unix,
        status=status,
        exit_code=receipt.exit_code if status != "unknown" else None,
        signal=None,
        cleanup_status=receipt.cleanup_status if status != "unknown" else "unknown",
        request_journal_sha256=receipt.consumption_sha256 if receipt.request_count is not None else None,
        request_count=receipt.request_count or 0,
        stdout_sha256=receipt.stdout_evidence.sha256,
        stderr_sha256=receipt.stderr_evidence.sha256,
        publication_eligible=False,
    )


def reconcile_python_producer_terminal(
    previous: PythonProducerTerminal | bytes | str | Mapping[str, object],
    observed: PythonProducerTerminal | bytes | str | Mapping[str, object],
    *, expected_binding: str | PythonProducerBinding | Mapping[str, object],
    expected_deadline_unix: float | None = None,
) -> PythonProducerTerminal:
    """Reconcile retained terminal evidence without I/O, mutation, retry or publication."""
    old = previous if isinstance(previous, PythonProducerTerminal) else parse_python_producer_terminal(previous)
    new = observed if isinstance(observed, PythonProducerTerminal) else parse_python_producer_terminal(observed)
    binding, bound_deadline = _expected_binding(expected_binding)
    if expected_deadline_unix is not None:
        parsed = _timestamp(expected_deadline_unix, "deadline_invalid", optional=False)
        assert parsed is not None
        bound_deadline = parsed
    for item in (old, new):
        if item.binding_sha256 != binding:
            _fail("binding_drift")
        if item.deadline_unix != bound_deadline and not math.isnan(bound_deadline):
            _fail("deadline_drift")
        if item.run_id != old.run_id or item.journal_id != old.journal_id or item.launch_id != old.launch_id:
            _fail("identity_drift")
    if old.status in {"completed", "failed", "cancelled"}:
        if new != old:
            _fail("terminal_immutable")
        return old
    if old.status != "unknown":
        _fail("previous_status_invalid")
    if old.publication_eligible:
        _fail("unknown_publication_eligible")
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
    item = terminal if isinstance(terminal, PythonProducerTerminal) else parse_python_producer_terminal(terminal)
    binding, deadline = _expected_binding(expected_binding)
    if expected_deadline_unix is not None:
        parsed = _timestamp(expected_deadline_unix, "deadline_invalid", optional=False)
        assert parsed is not None
        deadline = parsed
    if item.binding_sha256 != binding:
        _fail("binding_drift")
    if not math.isnan(deadline) and item.deadline_unix != deadline:
        _fail("deadline_drift")
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
    "resume_python_producer_terminal",
]
