"""Strict projection from native trusted evidence to a Feature 156 receipt.

The projection is intentionally read-only.  It does not create ``execution-receipt.json`` or
authorize bundle publication.  It only constructs the formal receipt object after terminal,
stream, envelope, broker, cleanup, and target-execution evidence all verify against the same
registration and retained deadline.
"""

from __future__ import annotations

from pathlib import Path

from .native_bootstrap import NativeBootstrapArtifact
from .native_trusted_attempt import recover_native_trusted_attempt
from .native_trusted_capture import (
    NativeTrustedCaptureError,
    recover_native_trusted_output_capture,
)
from .native_trusted_cleanup import (
    NativeTrustedCleanupError,
    recover_native_trusted_cleanup,
)
from .native_trusted_streams import (
    NativeTrustedStreamError,
    recover_native_trusted_stream_capture,
)
from .producer_launcher import ProducerLaunchAttestation, ProducerLaunchIntent
from .producer_process import (
    ProducerEnvelopeEvidence,
    ProducerExecutionReceipt,
    ProducerProcessError,
    ProducerStreamEvidence,
    _identity_digest,
    _read_durable_json,
)


class NativeTrustedReceiptError(ValueError):
    """Fixed-code projection failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _batch(workspace: str | Path, intent: ProducerLaunchIntent) -> Path:
    return (
        Path(workspace).expanduser().absolute()
        / "evolution"
        / "producer-batches"
        / intent.journal_id
    )


def _registration(workspace: str | Path, intent: ProducerLaunchIntent) -> dict[str, object]:
    try:
        record = _read_durable_json(
            _batch(workspace, intent) / "process-registration.json",
            code="native_trusted_receipt_registration_invalid",
        )
    except ProducerProcessError as exc:
        raise NativeTrustedReceiptError("native_trusted_receipt_registration_invalid") from exc
    if (
        record.get("journal_id") != intent.journal_id
        or record.get("launch_id") != intent.launch_id
        or record.get("intent_sha256") != (intent.intent_sha256 or intent.digest())
        or not isinstance(record.get("registration_sha256"), str)
        or not isinstance(record.get("owner_identity"), dict)
        or record.get("owner_identity", {}).get("pid") != record.get("pid")
    ):
        raise NativeTrustedReceiptError("native_trusted_receipt_registration_invalid")
    return record


def _stream(value: object, name: str) -> ProducerStreamEvidence:
    if not isinstance(value, dict) or set(value) != {
        "stream", "bytes_observed", "sha256", "truncated", "capture_status",
    }:
        raise NativeTrustedReceiptError("native_trusted_receipt_stream_invalid")
    if (
        value.get("stream") != name
        or isinstance(value.get("bytes_observed"), bool)
        or not isinstance(value.get("bytes_observed"), int)
        or value["bytes_observed"] < 0
        or value.get("truncated") is not False
        or value.get("capture_status") != "complete"
    ):
        raise NativeTrustedReceiptError("native_trusted_receipt_stream_incomplete")
    try:
        return ProducerStreamEvidence(**value)
    except (TypeError, ValueError) as exc:
        raise NativeTrustedReceiptError("native_trusted_receipt_stream_invalid") from exc


def _envelope(value: object, intent: ProducerLaunchIntent) -> ProducerEnvelopeEvidence:
    if not isinstance(value, dict):
        raise NativeTrustedReceiptError("native_trusted_receipt_envelope_invalid")
    required = {"sha256", "bytes", "device", "inode", "mtime_ns", "ctime_ns"}
    if not required.issubset(value) or value.get("relative_path") != intent.envelope_path:
        raise NativeTrustedReceiptError("native_trusted_receipt_envelope_invalid")
    # Older native capture sidecars carried the stable stat tuple but not the two derived
    # identity digests.  Derive them from those exact bytes so the formal DTO remains bound
    # to the same before/after observation; newer sidecars may provide both explicitly.
    before = value.get("identity_before")
    after = value.get("identity_after")
    identity = {
        "device": value.get("device"), "inode": value.get("inode"),
        "size": value.get("bytes"), "mtime_ns": value.get("mtime_ns"),
        "ctime_ns": value.get("ctime_ns"),
    }
    if not isinstance(before, str):
        before = _identity_digest(identity)
    if not isinstance(after, str):
        after = _identity_digest(identity)
    if before != after:
        raise NativeTrustedReceiptError("native_trusted_receipt_envelope_changed")
    try:
        return ProducerEnvelopeEvidence(
            relative_path=intent.envelope_path,
            sha256=value["sha256"], bytes=value["bytes"], device=value["device"],
            inode=value["inode"], mtime_ns=value["mtime_ns"], ctime_ns=value["ctime_ns"],
            identity_before=before, identity_after=after, read_status="stable",
        )
    except (TypeError, ValueError, KeyError) as exc:
        raise NativeTrustedReceiptError("native_trusted_receipt_envelope_invalid") from exc


def build_native_trusted_execution_receipt(
    workspace: str | Path,
    *,
    intent: ProducerLaunchIntent,
    attestation: ProducerLaunchAttestation,
    artifact: NativeBootstrapArtifact,
    require_broker: bool = True,
) -> ProducerExecutionReceipt:
    """Build, but do not persist, one formal receipt from fully verified native evidence."""
    if not isinstance(intent, ProducerLaunchIntent) or not isinstance(attestation, ProducerLaunchAttestation):
        raise NativeTrustedReceiptError("native_trusted_receipt_context_invalid")
    if not isinstance(artifact, NativeBootstrapArtifact) or not isinstance(require_broker, bool):
        raise NativeTrustedReceiptError("native_trusted_receipt_context_invalid")
    try:
        terminal = recover_native_trusted_attempt(
            workspace, intent=intent, attestation=attestation, artifact=artifact,
        )
    except Exception as exc:  # native recovery already emits fixed local codes
        raise NativeTrustedReceiptError("native_trusted_receipt_terminal_invalid") from exc
    if terminal.get("process_status") != "exited_zero" or terminal.get("exit_code") != 0:
        raise NativeTrustedReceiptError("native_trusted_receipt_terminal_unpublishable")
    if not isinstance(terminal.get("stream_capture_sha256"), str):
        raise NativeTrustedReceiptError("native_trusted_receipt_stream_missing")
    registration = _registration(workspace, intent)
    batch = _batch(workspace, intent)
    try:
        streams = recover_native_trusted_stream_capture(batch, intent=intent, terminal=terminal)
    except NativeTrustedStreamError as exc:
        raise NativeTrustedReceiptError("native_trusted_receipt_stream_invalid") from exc
    try:
        capture = recover_native_trusted_output_capture(batch, intent=intent, terminal=terminal)
    except NativeTrustedCaptureError as exc:
        raise NativeTrustedReceiptError("native_trusted_receipt_output_invalid") from exc
    broker = capture.get("broker_evidence")
    if require_broker and (
        not isinstance(broker, dict)
        or broker.get("coverage") != "brokered_requests_only"
        or broker.get("complete") is not True
        or broker.get("declared_count_matches") is not True
    ):
        raise NativeTrustedReceiptError("native_trusted_receipt_broker_incomplete")
    try:
        cleanup = recover_native_trusted_cleanup(
            workspace, intent=intent, terminal=terminal,
        )
    except NativeTrustedCleanupError as exc:
        raise NativeTrustedReceiptError("native_trusted_receipt_cleanup_invalid") from exc
    stdout = _stream(streams["stdout_evidence"], "stdout")
    stderr = _stream(streams["stderr_evidence"], "stderr")
    envelope = _envelope(capture.get("envelope_evidence"), intent)
    target_binding = registration.get("target_execution_binding")
    if target_binding not in {"darwin-immutable-snapshot", "linux-sealed-memfd"}:
        raise NativeTrustedReceiptError("native_trusted_receipt_execution_binding_invalid")
    target_path = registration.get("target_execution_snapshot_relative_path")
    if target_binding == "linux-sealed-memfd" and target_path is not None:
        raise NativeTrustedReceiptError("native_trusted_receipt_execution_binding_invalid")
    if target_binding == "darwin-immutable-snapshot" and not isinstance(target_path, str):
        raise NativeTrustedReceiptError("native_trusted_receipt_execution_binding_invalid")
    try:
        owner = registration["owner_identity"]
        executable_identity = _identity_digest({
            "sha256": intent.executable_sha256, "size": intent.executable_size,
            "device": intent.executable_device, "inode": intent.executable_inode,
            "mtime_ns": intent.executable_mtime_ns, "ctime_ns": intent.executable_ctime_ns,
        })
        return ProducerExecutionReceipt(
            launch_id=intent.launch_id, journal_id=intent.journal_id, run_id=intent.run_id,
            parent_task_id=intent.parent_task_id, task_id=intent.task_id,
            intent_sha256=intent.intent_sha256 or intent.digest(),
            attestation_sha256=attestation.attestation_sha256 or attestation.digest(),
            consumption_sha256=str(registration["consumption_sha256"]),
            registration_sha256=str(registration["registration_sha256"]),
            executable_identity=executable_identity,
            pid=int(registration["pid"]), pgid=int(registration["pgid"]), owner_identity=owner,
            gate_released=True, request_timeout_seconds=intent.request_timeout_seconds,
            max_requests=intent.max_requests, output_max_bytes=intent.output_max_bytes,
            wall_timeout_seconds=intent.wall_timeout_seconds,
            request_count=int(capture["declared_requests"]), exit_code=0,
            stdout_evidence=stdout, stderr_evidence=stderr, envelope_evidence=envelope,
            cleanup_status=str(cleanup["cleanup_status"]), cleanup_sha256=str(cleanup["cleanup_sha256"]),
            execution_binding=target_binding,
            execution_snapshot_relative_path=target_path,
            execution_snapshot_sha256=str(registration["target_execution_snapshot_sha256"]),
            execution_snapshot_size=int(registration["target_execution_snapshot_size"]),
            status="completed", previous_receipt_sha256=str(registration["registration_sha256"]),
            trusted_execution={
                "terminal_sha256": terminal["terminal_sha256"],
                "stream_capture_sha256": streams["stream_capture_sha256"],
                "output_capture_sha256": capture["capture_sha256"],
                "cleanup_sha256": cleanup["cleanup_sha256"],
                "broker_coverage": "brokered_requests_only" if broker is not None else "none",
            },
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise NativeTrustedReceiptError("native_trusted_receipt_evidence_invalid") from exc


__all__ = ["NativeTrustedReceiptError", "build_native_trusted_execution_receipt"]
