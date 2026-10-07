"""Strict process-only failure evidence, with no execution or publication authority.

The frozen DTO is a serialization boundary, not a filesystem verdict. The live builder uses
the attempt's independently captured broker pins. Recovery reuses only those retained pins and
revalidates the original native chain before and after reading the closed broker journal.
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .candidate_evaluation_spec import canonical_json, strict_json
from .native_bootstrap import NativeBootstrapArtifact, load_native_bootstrap_artifact
from .native_deadline_binding import (
    NATIVE_CONSUMPTION_PROTOCOL,
    verify_native_deadline_record_binding,
)
from .native_trusted_attempt import (
    NativeTrustedAttemptObservation,
    _terminal_receipt,
    _verify_deadline_record,
    recover_native_trusted_attempt,
)
from .native_trusted_cleanup import _FIELDS as _CLEANUP_FIELDS
from .native_trusted_cleanup import recover_native_trusted_cleanup
from .native_trusted_streams import recover_native_trusted_stream_capture
from .producer_bootstrap import (
    TrustedBootstrapDescriptor,
    TrustedBootstrapLaunch,
    _parse_trusted_bootstrap_consumption,
    build_trusted_bootstrap_launch,
    parse_trusted_bootstrap_evidence,
    verify_trusted_bootstrap_process_registration,
)
from .producer_broker_ipc import ProducerBrokerObservation, recover_producer_broker_observation
from .producer_launcher import MAX_OUTPUT_BYTES, ProducerLaunchAttestation, ProducerLaunchIntent
from .producer_process import (
    ProducerStreamEvidence,
    _digest_without,
    _read_durable_json,
    _safe_root,
)
from .producer_request_transport import (
    MAX_HOST_REQUEST_JOURNAL_BYTES,
    HostRequestJournalIdentity,
    HostRequestSnapshot,
)
from .trusted_bootstrap_handoff import parse_trusted_bootstrap_process_registration_handoff
from .trusted_worker_evidence import verify_trusted_worker_evidence

NATIVE_TRUSTED_FAILURE_PROTOCOL = "lunar-native-trusted-producer-failure-v1"
MAX_NATIVE_TRUSTED_FAILURE_BYTES = 2 * 1024 * 1024
_FIELDS = {
    "schema_version", "protocol", "status", "receipt_scope", "publication_eligible", "launch",
    "descriptor", "consumption", "registration", "handoff", "bootstrap_evidence",
    "deadline_record", "terminal_record", "cleanup_record", "stream_capture", "broker",
    "failure_sha256",
}
_BROKER_FIELDS = {
    "journal_relative_path", "journal_identity", "journal_sha256", "journal_bytes",
    "journal_file_identity", "snapshot", "complete",
}
_SNAPSHOT_FIELDS = {
    "events", "admitted_count", "active_count", "request_timeout_seconds", "max_requests",
    "coverage", "clock_source",
}
_STREAM_CAPTURE_FIELDS = {
    "schema_version", "protocol", "launch_id", "journal_id", "run_id", "parent_task_id",
    "task_id", "intent_sha256", "attestation_sha256", "registration_sha256", "deadline_sha256",
    "output_max_bytes", "stdout_evidence", "stderr_evidence", "capture_complete", "capture_reason",
    "publication_eligible", "stream_capture_sha256",
}
_STREAM_FIELDS = {"stream", "bytes_observed", "sha256", "truncated", "capture_status"}
_READ_SECONDS = 5


class NativeTrustedFailureError(ValueError):
    """Fixed refusal codes; never include paths, provider prose or credentials."""

    def __init__(self, code: str) -> None:
        self.code = "native_trusted_failure_" + code
        super().__init__(self.code)


def _fail(code: str) -> None:
    raise NativeTrustedFailureError(code)


def _canonical(value: object) -> bytes:
    return canonical_json(value, maximum=MAX_NATIVE_TRUSTED_FAILURE_BYTES)


def _sha(value: object) -> str:
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        _fail("wire_invalid")
    return value


def _hashed_record(value: object, field: str) -> dict[str, Any]:
    if type(value) is not dict or _sha(value.get(field)) != _digest_without(value, field):
        _fail("wire_invalid")
    return value


def _snapshot(snapshot: HostRequestSnapshot) -> dict[str, Any]:
    value = asdict(snapshot)
    value["events"] = list(value["events"])
    return value


def _validate_broker(value: object, launch: TrustedBootstrapLaunch) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _BROKER_FIELDS:
        _fail("wire_invalid")
    if value["journal_relative_path"] != ".host-request-journal/requests" or value["complete"] is not True:
        _fail("broker_unsettled")
    identity = HostRequestJournalIdentity(**value["journal_identity"])
    if identity.to_dict() != value["journal_identity"] or identity.wall_deadline_ns is None:
        _fail("wire_invalid")
    if any(getattr(identity, field) != getattr(launch, field) for field in (
        "launch_id", "journal_id", "run_id", "parent_task_id", "task_id", "intent_sha256",
    )):
        _fail("binding_invalid")
    _sha(value["journal_sha256"])
    size = value["journal_bytes"]
    file_identity = value["journal_file_identity"]
    if (type(size) is not int or not 1 <= size <= MAX_HOST_REQUEST_JOURNAL_BYTES
            or type(file_identity) is not dict or set(file_identity) != {"device", "inode"}
            or any(type(item) is not int or item < 0 for item in file_identity.values())):
        _fail("wire_invalid")
    snapshot = value["snapshot"]
    if type(snapshot) is not dict or set(snapshot) != _SNAPSHOT_FIELDS:
        _fail("wire_invalid")
    count = snapshot["admitted_count"]
    events = snapshot["events"]
    if (type(count) is not int or not 0 <= count <= identity.max_requests
            or type(snapshot["active_count"]) is not int or snapshot["active_count"] != 0
            or snapshot["request_timeout_seconds"] != identity.request_timeout_seconds
            or type(snapshot["request_timeout_seconds"]) is not int
            or snapshot["max_requests"] != identity.max_requests or type(snapshot["max_requests"]) is not int
            or snapshot["coverage"] != "brokered_requests_only"
            or snapshot["clock_source"] != "controller_monotonic"
            or type(events) is not list or len(events) != count):
        _fail("broker_unsettled")
    seen: set[str] = set()
    for ordinal, event in enumerate(events, 1):
        if (type(event) is not dict or set(event) != {"sequence", "request_id", "status", "duration_ms"}
                or type(event["sequence"]) is not int or event["sequence"] != ordinal
                or type(event["request_id"]) is not str
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", event["request_id"]) is None
                or event["request_id"] in seen or event["status"] not in {"completed", "failed", "cancelled"}
                or type(event["duration_ms"]) is not int
                or not 0 <= event["duration_ms"] <= identity.request_timeout_seconds * 1000):
            _fail("broker_unsettled")
        seen.add(event["request_id"])
    return value


def _validate_wire(value: object) -> dict[str, Any]:
    """Strict detached wire checks; the builder/reader supplies independent FS authority."""
    if type(value) is not dict or set(value) != _FIELDS:
        _fail("wire_invalid")
    if (value["schema_version"] != "1" or value["protocol"] != NATIVE_TRUSTED_FAILURE_PROTOCOL
            or value["status"] not in {"failed", "cancelled"}
            or value["receipt_scope"] != "process_only" or value["publication_eligible"] is not False):
        _fail("wire_invalid")
    if _sha(value["failure_sha256"]) != hashlib.sha256(_canonical({
        key: item for key, item in value.items() if key != "failure_sha256"
    })).hexdigest():
        _fail("digest_invalid")
    launch = TrustedBootstrapLaunch(**value["launch"])
    descriptor = TrustedBootstrapDescriptor(**value["descriptor"])
    if launch.to_dict() != value["launch"] or descriptor.to_dict() != value["descriptor"]:
        _fail("wire_invalid")
    registration = verify_trusted_bootstrap_process_registration(launch, descriptor, value["registration"])
    claim = _parse_trusted_bootstrap_consumption(value["consumption"])
    _hashed_record(claim, "consumption_sha256")
    if (claim["protocol"] != NATIVE_CONSUMPTION_PROTOCOL or claim["schema_version"] != "2"
            or claim["consumption_sha256"] != registration["consumption_sha256"]
            or claim["consumption_id"] != launch.launch_id or claim["nonce"] != launch.gate_nonce
            or any(claim[field] != getattr(launch, field) for field in (
                "launch_id", "journal_id", "run_id", "parent_task_id", "task_id",
                "intent_sha256", "attestation_sha256",
            ))):
        _fail("binding_invalid")
    handoff = parse_trusted_bootstrap_process_registration_handoff(value["handoff"])
    for field, expected in (
        ("launch_sha256", launch.digest()), ("descriptor_sha256", descriptor.digest()),
        ("intent_sha256", launch.intent_sha256), ("attestation_sha256", launch.attestation_sha256),
        ("consumption_sha256", claim["consumption_sha256"]),
        ("registration_sha256", registration["registration_sha256"]),
        ("pid", registration["pid"]), ("pgid", registration["pgid"]),
        ("bootstrap_execution_binding", registration["execution_binding"]),
        ("bootstrap_snapshot_relative_path", registration["execution_snapshot_relative_path"]),
        ("bootstrap_snapshot_sha256", registration["execution_snapshot_sha256"]),
        ("bootstrap_snapshot_size", registration["execution_snapshot_size"]),
        ("target_execution_binding", registration["target_execution_binding"]),
        ("target_snapshot_relative_path", registration["target_execution_snapshot_relative_path"]),
        ("target_snapshot_sha256", registration["target_execution_snapshot_sha256"]),
        ("target_snapshot_size", registration["target_execution_snapshot_size"]),
    ):
        if handoff[field] != expected:
            _fail("binding_invalid")
    evidence = parse_trusted_bootstrap_evidence(value["bootstrap_evidence"])
    if (evidence.launch_sha256 != launch.digest()
            or evidence.registration_sha256 != registration["registration_sha256"]
            or (evidence.target_pgid is not None and evidence.target_pgid != registration["pgid"])
            or evidence.status not in ({"passed"} if value["status"] == "failed" else {"passed", "unknown"})):
        _fail("binding_invalid")
    deadline = _verify_deadline_record(value["deadline_record"], registration)
    verify_native_deadline_record_binding(deadline, claim["deadline_binding"])
    terminal = _hashed_record(value["terminal_record"], "terminal_sha256")
    exit_code = terminal.get("exit_code")
    cancelled = value["status"] == "cancelled"
    if (cancelled and exit_code is not None) or (not cancelled and (
        type(exit_code) is not int or not -255 <= exit_code <= 255 or exit_code == 0
    )):
        _fail("wire_invalid")
    cleanup = _hashed_record(value["cleanup_record"], "cleanup_sha256")
    if (set(cleanup) != _CLEANUP_FIELDS or cleanup["schema_version"] != "1"
            or cleanup["protocol"] != "lunar-native-trusted-cleanup-v1"
            or cleanup["publication_eligible"] is not False or cleanup["alive_after"] is not False
            or cleanup["cleanup_status"] not in {"cleaned", "already_exited"}
            or any(type(cleanup[key]) is not bool for key in ("term_sent", "kill_sent", "alive_after"))
            or any(cleanup[field] != registration[field] for field in (
                "launch_id", "journal_id", "run_id", "parent_task_id", "task_id", "intent_sha256",
                "registration_sha256", "pid", "pgid",
            )) or cleanup["deadline_sha256"] != deadline["deadline_sha256"]):
        _fail("binding_invalid")
    expected = _terminal_receipt(
        registration, handoff_sha256=handoff["handoff_sha256"], evidence_sha256=evidence.evidence_sha256,
        gate_released=True, target_started=True, exit_code=exit_code, cleanup_status=cleanup["cleanup_status"],
        deadline_sha256=deadline["deadline_sha256"], cancelled=cancelled,
        stream_capture_sha256=terminal.get("stream_capture_sha256"), cleanup_sha256=cleanup["cleanup_sha256"],
    )
    if terminal != expected:
        _fail("binding_invalid")
    streams = value["stream_capture"]
    if terminal["stream_capture_sha256"] is None:
        if streams is not None:
            _fail("binding_invalid")
    else:
        _hashed_record(streams, "stream_capture_sha256")
        limit = streams.get("output_max_bytes")
        if (set(streams) != _STREAM_CAPTURE_FIELDS or streams["schema_version"] != "1"
                or streams["protocol"] != "lunar-native-trusted-stream-capture-v1"
                or type(limit) is not int or not 1 <= limit <= MAX_OUTPUT_BYTES
                or any(streams[field] != terminal[field] for field in (
                    "launch_id", "journal_id", "run_id", "parent_task_id", "task_id", "intent_sha256",
                    "attestation_sha256", "registration_sha256", "deadline_sha256",
                )) or streams["stream_capture_sha256"] != terminal["stream_capture_sha256"]
                or streams.get("publication_eligible") is not False or streams.get("capture_complete") is not True
                or streams.get("capture_reason") is not None):
            _fail("binding_invalid")
        for name in ("stdout", "stderr"):
            item = streams[name + "_evidence"]
            if type(item) is not dict or set(item) != _STREAM_FIELDS:
                _fail("wire_invalid")
            stream = ProducerStreamEvidence(**item)
            if (stream.stream != name or type(stream.bytes_observed) is not int
                    or not 0 <= stream.bytes_observed <= limit + 1 or type(stream.truncated) is not bool
                    or stream.capture_status not in {"complete", "limit_exceeded"}):
                _fail("wire_invalid")
            _sha(stream.sha256)
    _validate_broker(value["broker"], launch)
    return value


@dataclass(frozen=True, slots=True)
class NativeTrustedProducerFailure:
    """Immutable canonical evidence. Construction is not a filesystem proof."""

    _wire: bytes

    def __post_init__(self) -> None:
        try:
            if type(self._wire) is not bytes:
                _fail("wire_invalid")
            value = _validate_wire(strict_json(self._wire, maximum=MAX_NATIVE_TRUSTED_FAILURE_BYTES))
            if _canonical(value) != self._wire:
                _fail("wire_invalid")
        except NativeTrustedFailureError:
            raise
        except Exception as exc:
            raise NativeTrustedFailureError("wire_invalid") from exc

    @classmethod
    def from_dict(cls, value: object) -> NativeTrustedProducerFailure:
        try:
            return cls(_canonical(value))
        except NativeTrustedFailureError:
            raise
        except Exception as exc:
            raise NativeTrustedFailureError("wire_invalid") from exc

    def to_dict(self) -> dict[str, Any]:
        return strict_json(self._wire, maximum=MAX_NATIVE_TRUSTED_FAILURE_BYTES)

    @property
    def status(self) -> str:
        return self.to_dict()["status"]

    @property
    def terminal_record(self) -> dict[str, Any]:
        return self.to_dict()["terminal_record"]

    @property
    def terminal_sha256(self) -> str:
        return self.terminal_record["terminal_sha256"]

    @property
    def exit_code(self) -> int | None:
        return self.terminal_record["exit_code"]

    def digest(self) -> str:
        return self.to_dict()["failure_sha256"]


def _records(
    workspace: str | Path, *, intent: ProducerLaunchIntent, attestation: ProducerLaunchAttestation,
    artifact: NativeBootstrapArtifact,
) -> tuple[Path, dict[str, Any]]:
    if (not isinstance(intent, ProducerLaunchIntent) or not isinstance(attestation, ProducerLaunchAttestation)
            or not isinstance(artifact, NativeBootstrapArtifact)):
        _fail("context_invalid")
    installed = load_native_bootstrap_artifact(
        artifact.path, descriptor=artifact.descriptor, allowlist_id=artifact.allowlist_id,
    )
    if installed.artifact_sha256 != artifact.artifact_sha256:
        _fail("context_invalid")
    root = _safe_root(workspace)
    batch = root / "evolution" / "producer-batches" / intent.journal_id
    launch = build_trusted_bootstrap_launch(intent, attestation, installed.descriptor)
    terminal = recover_native_trusted_attempt(
        root, intent=intent, attestation=attestation, artifact=installed, cleanup=False,
    )
    if terminal.get("process_status") not in {"exited_nonzero", "cancelled"}:
        _fail("terminal_unknown")
    records = {
        name: _read_durable_json(batch / path, code="native_trusted_failure_records_invalid")
        for name, path in (
            ("consumption", "attestation-consumption.json"), ("registration", "process-registration.json"),
            ("handoff", "trusted-bootstrap-handoff.json"), ("bootstrap_evidence", "trusted-bootstrap-evidence.json"),
            ("deadline_record", "native-trusted-attempt-deadline.json"),
        )
    }
    if records["consumption"].get("protocol") != NATIVE_CONSUMPTION_PROTOCOL:
        _fail("deadline_unanchored")
    cleanup = recover_native_trusted_cleanup(root, intent=intent, terminal=terminal)
    streams = (recover_native_trusted_stream_capture(batch, intent=intent, terminal=terminal)
               if terminal.get("stream_capture_sha256") is not None else None)
    verified = verify_trusted_worker_evidence(
        launch=launch, descriptor=installed.descriptor, intent=intent, attestation=attestation,
        consumption=records["consumption"], registration=records["registration"], handoff=records["handoff"],
        evidence=records["bootstrap_evidence"], terminal=terminal, deadline=records["deadline_record"], cleanup=cleanup,
    )
    if verified.status != "trusted_failed" or verified.terminal_sha256 != terminal.get("terminal_sha256"):
        _fail("records_invalid")
    return batch, {
        **records, "launch": launch.to_dict(), "descriptor": installed.descriptor.to_dict(),
        "terminal_record": terminal, "cleanup_record": cleanup, "stream_capture": streams,
    }


def _closed_broker(batch: Path, pin: dict[str, Any], intent: ProducerLaunchIntent) -> dict[str, Any]:
    identity = HostRequestJournalIdentity(**pin["journal_identity"])
    if (identity.request_timeout_seconds != intent.request_timeout_seconds
            or identity.max_requests != intent.max_requests
            or pin["journal_relative_path"] != ".host-request-journal/requests"):
        _fail("broker_invalid")
    file_identity = pin["journal_file_identity"]
    recovered = recover_producer_broker_observation(
        batch / pin["journal_relative_path"], identity=identity,
        # Read-work bound only: this never changes the retained execution deadline or calls I/O.
        deadline_ns=time.monotonic_ns() + _READ_SECONDS * 1_000_000_000,
        expected_journal_sha256=pin["journal_sha256"], expected_journal_bytes=pin["journal_bytes"],
        expected_journal_file_identity=(file_identity["device"], file_identity["inode"]),
    )
    if not recovered.complete:
        _fail("broker_unsettled")
    return {**pin, "complete": True, "snapshot": _snapshot(recovered.snapshot)}


def build_native_trusted_failure(
    workspace: str | Path, *, intent: ProducerLaunchIntent, attestation: ProducerLaunchAttestation,
    artifact: NativeBootstrapArtifact, attempt: NativeTrustedAttemptObservation,
) -> NativeTrustedProducerFailure:
    """Build a failure only from the live attempt's original independent broker pin."""
    try:
        if not isinstance(attempt, NativeTrustedAttemptObservation):
            _fail("attempt_invalid")
        original = attempt.broker_observation
        if not isinstance(original, ProducerBrokerObservation) or original.journal_file_identity is None:
            _fail("broker_pin_missing")
        batch, before = _records(workspace, intent=intent, attestation=attestation, artifact=artifact)
        terminal = before["terminal_record"]
        if (attempt.launch_id != intent.launch_id or attempt.journal_id != intent.journal_id
                or attempt.registration_sha256 != before["registration"]["registration_sha256"]
                or attempt.terminal_sha256 != terminal["terminal_sha256"]
                or attempt.gate_released is not True or attempt.target_started is not True
                or attempt.exit_code != terminal["exit_code"] or attempt.cleanup_status != terminal["cleanup_status"]
                or original.journal_path != batch / ".host-request-journal" / "requests"):
            _fail("attempt_drift")
        pin = {
            "journal_relative_path": ".host-request-journal/requests",
            "journal_identity": original.journal_identity.to_dict(),
            "journal_sha256": original.journal_sha256, "journal_bytes": original.journal_bytes,
            "journal_file_identity": dict(zip(("device", "inode"), original.journal_file_identity, strict=True)),
        }
        broker = _closed_broker(batch, pin, intent)
        if broker["snapshot"] != _snapshot(original.snapshot):
            _fail("broker_drift")
        _batch, after = _records(workspace, intent=intent, attestation=attestation, artifact=artifact)
        if after != before or _closed_broker(batch, pin, intent) != broker:
            _fail("records_changed")
        payload = {
            "schema_version": "1", "protocol": NATIVE_TRUSTED_FAILURE_PROTOCOL,
            "status": "cancelled" if terminal["process_status"] == "cancelled" else "failed",
            "receipt_scope": "process_only", "publication_eligible": False, **before, "broker": broker,
        }
        payload["failure_sha256"] = hashlib.sha256(_canonical(payload)).hexdigest()
        return NativeTrustedProducerFailure.from_dict(payload)
    except NativeTrustedFailureError:
        raise
    except Exception as exc:
        raise NativeTrustedFailureError("evidence_invalid") from exc


def recover_native_trusted_failure(
    workspace: str | Path, *, intent: ProducerLaunchIntent, attestation: ProducerLaunchAttestation,
    artifact: NativeBootstrapArtifact, expected: NativeTrustedProducerFailure,
) -> NativeTrustedProducerFailure:
    """Revalidate only retained proof; never rebuild a lost pin, launch, clean up or signal."""
    try:
        if not isinstance(expected, NativeTrustedProducerFailure):
            _fail("expected_invalid")
        saved = expected.to_dict()
        batch, before = _records(workspace, intent=intent, attestation=attestation, artifact=artifact)
        if any(saved[field] != record for field, record in before.items()):
            _fail("records_drift")
        broker = _closed_broker(batch, saved["broker"], intent)
        if broker != saved["broker"]:
            _fail("broker_drift")
        _batch, after = _records(workspace, intent=intent, attestation=attestation, artifact=artifact)
        if after != before or _closed_broker(batch, saved["broker"], intent) != broker:
            _fail("records_changed")
        return expected
    except NativeTrustedFailureError:
        raise
    except Exception as exc:
        raise NativeTrustedFailureError("evidence_invalid") from exc


__all__ = [
    "MAX_NATIVE_TRUSTED_FAILURE_BYTES", "NATIVE_TRUSTED_FAILURE_PROTOCOL", "NativeTrustedFailureError",
    "NativeTrustedProducerFailure", "build_native_trusted_failure", "recover_native_trusted_failure",
]
