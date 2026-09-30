"""Same-attempt output capture for an isolated native producer."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import time
from collections.abc import Callable, Mapping
from pathlib import Path

from .producer_broker_ipc import ProducerBrokerObservation
from .producer_handoff import (
    MAX_PRODUCER_ENVELOPE_BYTES,
    PRODUCER_COMPLETED_STATUS,
    PRODUCER_MATERIAL_KIND,
    ProducerHandoffError,
    parse_producer_envelope,
)
from .producer_launcher import ProducerLaunchIntent
from .producer_process import (
    ProducerProcessError,
    _atomic_json,
    _digest_without,
    _held_directory,
    _identity_digest,
    _read_durable_json,
)
from .producer_request_transport import (
    HostRequestJournalIdentity,
    ProducerRequestTransportError,
    read_host_request_journal,
)

_PROTOCOL = "lunar-native-trusted-output-capture-v1"
_NAME = "native-trusted-output-capture.json"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ENVELOPE_EVIDENCE_FIELDS = frozenset(
    {
        "relative_path", "sha256", "bytes", "device", "inode", "mtime_ns", "ctime_ns",
        "identity_before", "identity_after", "read_status",
    }
)
_BROKER_EVIDENCE_FIELDS = frozenset(
    {
        "journal_relative_path", "journal_identity", "journal_sha256", "journal_bytes",
        "admitted_count", "complete", "declared_count_matches", "coverage",
    }
)


class NativeTrustedCaptureError(ValueError):
    """Fixed-code capture failure without producer-controlled content."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _check_deadline(deadline: float | None, monotonic: Callable[[], float]) -> None:
    if deadline is not None and monotonic() >= deadline:
        raise NativeTrustedCaptureError("native_trusted_capture_wall_timeout")


def _identity_value(info: os.stat_result) -> dict[str, int]:
    """Return the canonical stat tuple used by the native envelope DTO."""
    return {
        "device": info.st_dev,
        "inode": info.st_ino,
        "size": info.st_size,
        "mtime_ns": info.st_mtime_ns,
        "ctime_ns": info.st_ctime_ns,
    }


def _stable_bytes(
    path: Path, *, limit: int, deadline: float | None,
    monotonic: Callable[[], float],
) -> tuple[bytes, dict[str, object]]:
    try:
        with _held_directory(path.parent) as parent:
            _check_deadline(deadline, monotonic)
            before = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > limit:
                raise NativeTrustedCaptureError("native_trusted_capture_file_invalid")
            fd = os.open(
                path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                dir_fd=parent,
            )
            try:
                opened = os.fstat(fd)
                data = bytearray()
                while len(data) <= limit:
                    _check_deadline(deadline, monotonic)
                    part = os.read(fd, min(65536, limit + 1 - len(data)))
                    if not part:
                        break
                    data.extend(part)
                after = os.fstat(fd)
            finally:
                os.close(fd)
            current = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            identity = lambda info: (
                info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
                info.st_ctime_ns, info.st_nlink,
            )
            if (
                len(data) > limit or len(data) != before.st_size
                or identity(before) != identity(opened)
                or identity(before) != identity(after)
                or identity(before) != identity(current)
            ):
                raise NativeTrustedCaptureError("native_trusted_capture_file_changed")
            _check_deadline(deadline, monotonic)
    except NativeTrustedCaptureError:
        raise
    except (ProducerProcessError, OSError) as exc:
        raise NativeTrustedCaptureError("native_trusted_capture_file_invalid") from exc
    evidence: dict[str, object] = {
        "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
        "device": before.st_dev, "inode": before.st_ino,
        "mtime_ns": before.st_mtime_ns, "ctime_ns": before.st_ctime_ns,
        "identity_before": _identity_digest(_identity_value(before)),
        "identity_after": _identity_digest(_identity_value(after)),
        "read_status": "stable",
    }
    return bytes(data), evidence


def _validate_envelope_evidence(
    value: object, intent: ProducerLaunchIntent,
) -> None:
    """Validate the exact stable envelope evidence schema during recovery."""
    if not isinstance(value, dict) or set(value) != _ENVELOPE_EVIDENCE_FIELDS:
        raise NativeTrustedCaptureError("native_trusted_capture_receipt_invalid")
    if value.get("relative_path") != intent.envelope_path:
        raise NativeTrustedCaptureError("native_trusted_capture_receipt_invalid")
    for field in ("sha256", "identity_before", "identity_after"):
        if type(value.get(field)) is not str or _SHA256.fullmatch(value[field]) is None:
            raise NativeTrustedCaptureError("native_trusted_capture_receipt_invalid")
    if value.get("read_status") != "stable":
        raise NativeTrustedCaptureError("native_trusted_capture_receipt_invalid")
    for field in ("bytes", "device", "inode", "mtime_ns", "ctime_ns"):
        item = value.get(field)
        if type(item) is not int or item < 0:
            raise NativeTrustedCaptureError("native_trusted_capture_receipt_invalid")
    limit = min(intent.output_max_bytes, MAX_PRODUCER_ENVELOPE_BYTES)
    if value["bytes"] > limit:
        raise NativeTrustedCaptureError("native_trusted_capture_receipt_invalid")
    identity = {
        "device": value["device"], "inode": value["inode"], "size": value["bytes"],
        "mtime_ns": value["mtime_ns"], "ctime_ns": value["ctime_ns"],
    }
    expected_identity = _identity_digest(identity)
    if value["identity_before"] != expected_identity or value["identity_after"] != expected_identity:
        raise NativeTrustedCaptureError("native_trusted_capture_receipt_invalid")


def _validate_broker_evidence_shape(value: object) -> dict[str, object]:
    """Validate the bounded host-journal projection before replaying its bytes."""
    if not isinstance(value, dict) or set(value) != _BROKER_EVIDENCE_FIELDS:
        raise NativeTrustedCaptureError("native_trusted_capture_broker_invalid")
    if value.get("journal_relative_path") != ".host-request-journal/requests":
        raise NativeTrustedCaptureError("native_trusted_capture_broker_invalid")
    if type(value.get("journal_sha256")) is not str or _SHA256.fullmatch(value["journal_sha256"]) is None:
        raise NativeTrustedCaptureError("native_trusted_capture_broker_invalid")
    for field in ("journal_bytes", "admitted_count"):
        item = value.get(field)
        if type(item) is not int or item < 0:
            raise NativeTrustedCaptureError("native_trusted_capture_broker_invalid")
    if type(value.get("complete")) is not bool or type(value.get("declared_count_matches")) is not bool:
        raise NativeTrustedCaptureError("native_trusted_capture_broker_invalid")
    if value.get("coverage") != "brokered_requests_only":
        raise NativeTrustedCaptureError("native_trusted_capture_broker_invalid")
    return value


def _validate_broker_identity(
    value: object, intent: ProducerLaunchIntent,
) -> HostRequestJournalIdentity:
    if not isinstance(value, dict):
        raise NativeTrustedCaptureError("native_trusted_capture_broker_invalid")
    try:
        identity = HostRequestJournalIdentity(**value)
    except (TypeError, ValueError, ProducerRequestTransportError) as exc:
        raise NativeTrustedCaptureError("native_trusted_capture_broker_invalid") from exc
    # HostRequestJournalIdentity has one optional field, but recovery must still
    # bind the canonical representation byte-for-byte to the receipt projection.
    if identity.to_dict() != value:
        raise NativeTrustedCaptureError("native_trusted_capture_broker_invalid")
    if (
        identity.launch_id != intent.launch_id
        or identity.journal_id != intent.journal_id
        or identity.run_id != intent.run_id
        or identity.parent_task_id != intent.parent_task_id
        or identity.task_id != intent.task_id
        or identity.intent_sha256 != intent.intent_sha256
        or identity.max_requests != intent.max_requests
        or identity.request_timeout_seconds != intent.request_timeout_seconds
    ):
        raise NativeTrustedCaptureError("native_trusted_capture_broker_invalid")
    return identity


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise NativeTrustedCaptureError("native_trusted_capture_envelope_invalid")
        value[key] = item
    return value


def _reject_constant(_: str) -> None:
    raise NativeTrustedCaptureError("native_trusted_capture_envelope_invalid")


def _output_evidence(
    batch: Path, intent: ProducerLaunchIntent, *, deadline: float | None,
    monotonic: Callable[[], float],
) -> tuple[dict[str, object], list[dict[str, object]], int]:
    output = batch / intent.output_directory
    envelope_path = batch / intent.envelope_path
    raw, envelope_evidence = _stable_bytes(
        envelope_path, limit=min(intent.output_max_bytes, MAX_PRODUCER_ENVELOPE_BYTES),
        deadline=deadline, monotonic=monotonic,
    )
    envelope_evidence = {
        "relative_path": intent.envelope_path,
        **envelope_evidence,
    }
    try:
        envelope = parse_producer_envelope(json.loads(
            raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant,
        ))
    except (ProducerHandoffError, ValueError, UnicodeError, TypeError, RecursionError) as exc:
        raise NativeTrustedCaptureError("native_trusted_capture_envelope_invalid") from exc
    declared = envelope.budget.get("requests")
    if (
        envelope.producer_id != intent.producer_id
        or envelope.producer_fingerprint != intent.producer_fingerprint
        or envelope.contract_sha256 != intent.contract_sha256
        or envelope.status != PRODUCER_COMPLETED_STATUS
        or not envelope.materials
        or any(material.kind != PRODUCER_MATERIAL_KIND for material in envelope.materials)
        or type(declared) is not int or declared > intent.max_requests
    ):
        raise NativeTrustedCaptureError("native_trusted_capture_envelope_mismatch")
    total = len(raw)
    materials: list[dict[str, object]] = []
    for material in envelope.materials:
        path = output.joinpath(*material.path.split("/"))
        content, evidence = _stable_bytes(
            path, limit=min(material.size, intent.output_max_bytes),
            deadline=deadline, monotonic=monotonic,
        )
        total += len(content)
        if (
            len(content) != material.size or evidence["sha256"] != material.sha256
            or total > intent.output_max_bytes
        ):
            raise NativeTrustedCaptureError("native_trusted_capture_material_mismatch")
        materials.append({"path": material.path, **evidence})
    _check_deadline(deadline, monotonic)
    return envelope_evidence, materials, declared


def capture_native_trusted_output(
    batch: Path, *, intent: ProducerLaunchIntent, terminal_sha256: str,
    broker: ProducerBrokerObservation | None, deadline: float,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, object]:
    """Persist output and broker bytes before the original attempt deadline."""
    if (
        type(intent) is not ProducerLaunchIntent
        or type(terminal_sha256) is not str
        or _SHA256.fullmatch(terminal_sha256) is None
        or broker is not None and type(broker) is not ProducerBrokerObservation
    ):
        raise NativeTrustedCaptureError("native_trusted_capture_context_invalid")
    envelope, materials, declared = _output_evidence(
        batch, intent, deadline=deadline, monotonic=monotonic,
    )
    broker_evidence: dict[str, object] | None = None
    if broker is not None:
        try:
            recovered = read_host_request_journal(
                broker.journal_path, expected_identity=broker.journal_identity,
                deadline=deadline, monotonic=monotonic,
            )
        except ProducerRequestTransportError as exc:
            raise NativeTrustedCaptureError("native_trusted_capture_broker_invalid") from exc
        if (
            broker.journal_path != batch / ".host-request-journal" / "requests"
            or recovered.snapshot != broker.snapshot
            or recovered.journal_sha256 != broker.journal_sha256
            or recovered.journal_bytes != broker.journal_bytes
            or recovered.snapshot.coverage != "brokered_requests_only"
        ):
            raise NativeTrustedCaptureError("native_trusted_capture_broker_invalid")
        broker_evidence = {
            "journal_relative_path": ".host-request-journal/requests",
            "journal_identity": broker.journal_identity.to_dict(),
            "journal_sha256": recovered.journal_sha256,
            "journal_bytes": recovered.journal_bytes,
            "admitted_count": recovered.snapshot.admitted_count,
            # ``complete`` is only host-observed coverage.  A declaration/count
            # mismatch is retained as diagnostic evidence but cannot be called
            # complete, even when the broker itself reached a clean terminal.
            "complete": (
                broker.complete
                and recovered.snapshot.coverage == "brokered_requests_only"
                and not recovered.uncertain_request_ids
                and declared == recovered.snapshot.admitted_count
            ),
            "declared_count_matches": declared == recovered.snapshot.admitted_count,
            "coverage": recovered.snapshot.coverage,
        }
    receipt: dict[str, object] = {
        "schema_version": "1", "protocol": _PROTOCOL,
        "launch_id": intent.launch_id, "journal_id": intent.journal_id,
        "run_id": intent.run_id, "parent_task_id": intent.parent_task_id,
        "task_id": intent.task_id, "intent_sha256": intent.intent_sha256,
        "previous_receipt_sha256": terminal_sha256,
        "envelope_relative_path": intent.envelope_path,
        "envelope_evidence": envelope, "materials": materials,
        "declared_requests": declared, "broker_evidence": broker_evidence,
        "publication_eligible": False,
    }
    receipt["capture_sha256"] = _digest_without(receipt, "capture_sha256")
    _check_deadline(deadline, monotonic)
    try:
        _atomic_json(batch / _NAME, receipt, exclusive=True)
        stored = _read_durable_json(
            batch / _NAME, code="native_trusted_capture_receipt_invalid",
        )
    except ProducerProcessError as exc:
        raise NativeTrustedCaptureError("native_trusted_capture_receipt_write_unknown") from exc
    _check_deadline(deadline, monotonic)
    if stored != receipt:
        raise NativeTrustedCaptureError("native_trusted_capture_receipt_write_unknown")
    return receipt


def recover_native_trusted_output_capture(
    batch: Path, *, intent: ProducerLaunchIntent, terminal: Mapping[str, object],
) -> dict[str, object]:
    """Recheck durable bytes without granting publication authority."""
    if (
        type(intent) is not ProducerLaunchIntent or not isinstance(terminal, Mapping)
        or terminal.get("protocol") != "lunar-native-trusted-process-terminal-v1"
        or terminal.get("process_status") != "exited_zero"
        or terminal.get("gate_released") is not True
        or terminal.get("target_started") is not True
        or terminal.get("cleanup_status") not in {"cleaned", "already_exited"}
        or type(terminal.get("terminal_sha256")) is not str
        or _SHA256.fullmatch(terminal["terminal_sha256"]) is None
    ):
        raise NativeTrustedCaptureError("native_trusted_capture_terminal_invalid")
    try:
        receipt = _read_durable_json(batch / _NAME, code="native_trusted_capture_receipt_invalid")
    except ProducerProcessError as exc:
        raise NativeTrustedCaptureError("native_trusted_capture_receipt_invalid") from exc
    expected = {
        "schema_version", "protocol", "launch_id", "journal_id", "run_id",
        "parent_task_id", "task_id", "intent_sha256", "previous_receipt_sha256",
        "envelope_relative_path", "envelope_evidence", "materials",
        "declared_requests", "broker_evidence", "publication_eligible", "capture_sha256",
    }
    if (
        set(receipt) != expected or receipt.get("schema_version") != "1"
        or receipt.get("protocol") != _PROTOCOL
        or any(receipt.get(key) != getattr(intent, key) for key in (
            "launch_id", "journal_id", "run_id", "parent_task_id", "task_id", "intent_sha256",
        ))
        or receipt.get("previous_receipt_sha256") != terminal.get("terminal_sha256")
        or receipt.get("envelope_relative_path") != intent.envelope_path
        or receipt.get("publication_eligible") is not False
        or receipt.get("capture_sha256") != _digest_without(receipt, "capture_sha256")
    ):
        raise NativeTrustedCaptureError("native_trusted_capture_receipt_invalid")
    _validate_envelope_evidence(receipt.get("envelope_evidence"), intent)
    envelope, materials, declared = _output_evidence(
        batch, intent, deadline=None, monotonic=time.monotonic,
    )
    if (
        receipt["envelope_evidence"] != envelope
        or receipt["materials"] != materials
        or receipt["declared_requests"] != declared
    ):
        raise NativeTrustedCaptureError("native_trusted_capture_output_changed")
    broker = receipt["broker_evidence"]
    if broker is not None:
        broker = _validate_broker_evidence_shape(broker)
        try:
            identity = _validate_broker_identity(broker["journal_identity"], intent)
            recovered = read_host_request_journal(
                batch / ".host-request-journal" / "requests", expected_identity=identity,
            )
        except (KeyError, TypeError, ValueError, ProducerRequestTransportError) as exc:
            raise NativeTrustedCaptureError("native_trusted_capture_broker_invalid") from exc
        if (
            recovered.snapshot.coverage != "brokered_requests_only"
            or broker.get("journal_sha256") != recovered.journal_sha256
            or broker.get("journal_bytes") != recovered.journal_bytes
            or broker.get("admitted_count") != recovered.snapshot.admitted_count
            or (broker["complete"] and (
                not recovered.snapshot.within_broker_limits
                or recovered.uncertain_request_ids
                or broker.get("declared_count_matches") is not True
            ))
            or broker.get("declared_count_matches") != (declared == recovered.snapshot.admitted_count)
        ):
            raise NativeTrustedCaptureError("native_trusted_capture_broker_invalid")
    return receipt


__all__ = [
    "NativeTrustedCaptureError", "capture_native_trusted_output",
    "recover_native_trusted_output_capture",
]
