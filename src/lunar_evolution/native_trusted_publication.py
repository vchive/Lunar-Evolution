"""Restricted offline bridge from native trusted evidence to Feature 153.

The native trusted preparation receipt is intentionally not a publication authority. This module
adds one explicit, caller-owned offline-import authority which binds the complete
launch/attempt/capture/preparation evidence and a secret token. It does not claim complete
egress authority: there is no production mode in this module.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .algorithm import AlgorithmProblemContract
from .native_bootstrap import NativeBootstrapArtifact
from .native_trusted_preparation import (
    NativeTrustedPreparation,
    NativeTrustedPreparationError,
    recover_native_trusted_preparation,
)
from .producer_bundle_handoff import BundleGroup
from .producer_launcher import (
    ProducerLaunchAttestation,
    ProducerLaunchIntent,
    verify_producer_launch_attestation,
)
from .producer_process import ProducerProcessError, _read_durable_json

_PROTOCOL = "lunar-native-trusted-publication-authority-v2"
_SCHEMA = "1"
_SCOPE = "offline_import"
_MARKER = "native-trusted-publication-authority-consumed.json"
_PREPARATION_NAME = "native-trusted-preparation.json"
_SHA = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_MAX_TOKEN_BYTES = 4096


class NativeTrustedPublicationError(ValueError):
    """Fixed-code failure before or during the restricted publication bridge."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, OverflowError, RecursionError) as exc:
        raise NativeTrustedPublicationError("native_trusted_publication_canonical_invalid") from exc


def _sha(value: object, code: str = "native_trusted_publication_digest_invalid") -> str:
    if not isinstance(value, str) or _SHA.fullmatch(value) is None:
        raise NativeTrustedPublicationError(code)
    return value


def _id(value: object, code: str = "native_trusted_publication_identifier_invalid") -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise NativeTrustedPublicationError(code)
    return value


def _token_hash(token: object) -> str:
    if not isinstance(token, str) or not token or "\x00" in token:
        raise NativeTrustedPublicationError("native_trusted_publication_token_invalid")
    try:
        raw = token.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise NativeTrustedPublicationError("native_trusted_publication_token_invalid") from exc
    if len(raw) > _MAX_TOKEN_BYTES:
        raise NativeTrustedPublicationError("native_trusted_publication_token_invalid")
    return hashlib.sha256(raw).hexdigest()


def _digest_body(body: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical(dict(body))).hexdigest()


def _read_preparation_record(preparation: NativeTrustedPreparation) -> dict[str, object]:
    if (
        not isinstance(preparation, NativeTrustedPreparation)
        or preparation.receipt_path.name != _PREPARATION_NAME
        or not preparation.receipt_path.is_absolute()
        or preparation.receipt_sha256 != _sha(preparation.receipt_sha256)
    ):
        raise NativeTrustedPublicationError("native_trusted_publication_preparation_invalid")
    try:
        record = _read_durable_json(
            preparation.receipt_path, code="native_trusted_publication_preparation_invalid",
        )
    except ProducerProcessError as exc:
        raise NativeTrustedPublicationError("native_trusted_publication_preparation_invalid") from exc
    if not isinstance(record, dict):
        raise NativeTrustedPublicationError("native_trusted_publication_preparation_invalid")
    digest = record.get("receipt_sha256")
    body = {key: value for key, value in record.items() if key != "receipt_sha256"}
    if digest != preparation.receipt_sha256 or digest != _digest_body(body):
        raise NativeTrustedPublicationError("native_trusted_publication_preparation_invalid")
    return record


def _capture_record(preparation: NativeTrustedPreparation) -> dict[str, object]:
    path = preparation.receipt_path.parent / "native-trusted-output-capture.json"
    try:
        record = _read_durable_json(path, code="native_trusted_publication_capture_invalid")
    except ProducerProcessError as exc:
        raise NativeTrustedPublicationError("native_trusted_publication_capture_invalid") from exc
    if not isinstance(record, dict) or not isinstance(record.get("capture_sha256"), str):
        raise NativeTrustedPublicationError("native_trusted_publication_capture_invalid")
    return record


def _validate_preparation_shape(
    preparation: NativeTrustedPreparation,
    intent: ProducerLaunchIntent,
    attestation: ProducerLaunchAttestation,
) -> tuple[dict[str, object], dict[str, object]]:
    record = _read_preparation_record(preparation)
    capture = _capture_record(preparation)
    if (
        preparation.publication_eligible is not False
        or preparation.output.publication_eligible is not False
        or preparation.output.request_coverage != "brokered_requests_only"
        or not isinstance(preparation.output.output_capture_sha256, str)
        or _SHA.fullmatch(preparation.output.output_capture_sha256) is None
    ):
        raise NativeTrustedPublicationError("native_trusted_publication_evidence_incomplete")
    try:
        verify_producer_launch_attestation(intent, attestation)
    except Exception as exc:
        raise NativeTrustedPublicationError("native_trusted_publication_attestation_invalid") from exc
    required = (
        "launch_id", "journal_id", "run_id", "parent_task_id", "task_id", "intent_sha256",
    )
    if any(record.get(name) != getattr(intent, name) for name in required):
        raise NativeTrustedPublicationError("native_trusted_publication_binding_mismatch")
    if record.get("attestation_sha256") != attestation.attestation_sha256:
        raise NativeTrustedPublicationError("native_trusted_publication_binding_mismatch")
    if record.get("process_terminal_sha256") != preparation.output.process_terminal_sha256:
        raise NativeTrustedPublicationError("native_trusted_publication_binding_mismatch")
    if record.get("output_capture_sha256") != preparation.output.output_capture_sha256:
        raise NativeTrustedPublicationError("native_trusted_publication_binding_mismatch")
    if record.get("envelope_bytes_sha256") != preparation.output.envelope_bytes_sha256:
        raise NativeTrustedPublicationError("native_trusted_publication_binding_mismatch")
    if record.get("admission_plan_sha256") != preparation.output.admission_plan.digest():
        raise NativeTrustedPublicationError("native_trusted_publication_binding_mismatch")
    if (
        capture.get("launch_id") != intent.launch_id
        or capture.get("journal_id") != intent.journal_id
        or capture.get("run_id") != intent.run_id
        or capture.get("parent_task_id") != intent.parent_task_id
        or capture.get("task_id") != intent.task_id
        or capture.get("intent_sha256") != intent.intent_sha256
        or capture.get("previous_receipt_sha256") != preparation.output.process_terminal_sha256
        or capture.get("capture_sha256") != preparation.output.output_capture_sha256
        or capture.get("publication_eligible") is not False
    ):
        raise NativeTrustedPublicationError("native_trusted_publication_capture_mismatch")
    broker = capture.get("broker_evidence")
    if (
        not isinstance(broker, dict)
        or broker.get("complete") is not True
        or broker.get("declared_count_matches") is not True
        or broker.get("coverage") != "brokered_requests_only"
    ):
        raise NativeTrustedPublicationError("native_trusted_publication_broker_incomplete")
    if record.get("broker_evidence_sha256") != hashlib.sha256(_canonical(broker)).hexdigest():
        raise NativeTrustedPublicationError("native_trusted_publication_broker_mismatch")
    return record, capture


@dataclass(frozen=True, slots=True)
class NativeTrustedPublicationAuthority:
    """One-shot, field-bound authority for the restricted offline import bridge."""

    authority_id: str
    launch_id: str
    journal_id: str
    run_id: str
    parent_task_id: str
    task_id: str
    attestation_sha256: str
    preparation_sha256: str
    intent_sha256: str
    process_terminal_sha256: str
    output_capture_sha256: str
    envelope_bytes_sha256: str
    admission_plan_sha256: str
    broker_evidence_sha256: str
    executable_sha256: str
    executable_size: int
    executable_device: int
    executable_inode: int
    executable_mtime_ns: int
    executable_ctime_ns: int
    token_sha256: str
    nonce: str
    authority_sha256: str
    scope: str = _SCOPE
    schema_version: str = _SCHEMA
    protocol: str = _PROTOCOL

    def __post_init__(self) -> None:
        for value in (
            self.authority_id, self.launch_id, self.journal_id, self.run_id,
            self.parent_task_id, self.task_id, self.nonce,
        ):
            _id(value)
        for value in (
            self.attestation_sha256, self.preparation_sha256, self.intent_sha256,
            self.process_terminal_sha256, self.output_capture_sha256,
            self.envelope_bytes_sha256, self.admission_plan_sha256,
            self.broker_evidence_sha256, self.executable_sha256, self.token_sha256,
        ):
            _sha(value)
        if self.scope != _SCOPE or self.schema_version != _SCHEMA or self.protocol != _PROTOCOL:
            raise NativeTrustedPublicationError("native_trusted_publication_scope_invalid")
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in (
                self.executable_size, self.executable_device, self.executable_inode,
                self.executable_mtime_ns, self.executable_ctime_ns,
            )
        ):
            raise NativeTrustedPublicationError("native_trusted_publication_execution_identity_invalid")
        if self.authority_sha256 != self.digest():
            raise NativeTrustedPublicationError("native_trusted_publication_authority_digest_mismatch")

    def _body(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version, "protocol": self.protocol, "scope": self.scope,
            "authority_id": self.authority_id, "launch_id": self.launch_id,
            "journal_id": self.journal_id, "run_id": self.run_id,
            "parent_task_id": self.parent_task_id, "task_id": self.task_id,
            "attestation_sha256": self.attestation_sha256,
            "preparation_sha256": self.preparation_sha256, "intent_sha256": self.intent_sha256,
            "process_terminal_sha256": self.process_terminal_sha256,
            "output_capture_sha256": self.output_capture_sha256,
            "envelope_bytes_sha256": self.envelope_bytes_sha256,
            "admission_plan_sha256": self.admission_plan_sha256,
            "broker_evidence_sha256": self.broker_evidence_sha256,
            "executable_sha256": self.executable_sha256, "executable_size": self.executable_size,
            "executable_device": self.executable_device, "executable_inode": self.executable_inode,
            "executable_mtime_ns": self.executable_mtime_ns, "executable_ctime_ns": self.executable_ctime_ns,
            "token_sha256": self.token_sha256, "nonce": self.nonce,
        }

    def digest(self) -> str:
        return _digest_body(self._body())

    def to_dict(self) -> dict[str, object]:
        return {**self._body(), "authority_sha256": self.authority_sha256}


def build_native_trusted_publication_authority(
    preparation: NativeTrustedPreparation,
    *,
    intent: ProducerLaunchIntent,
    attestation: ProducerLaunchAttestation,
    token: str,
    nonce: str,
) -> NativeTrustedPublicationAuthority:
    """Build an explicit offline-import authority without persisting the token."""
    if not isinstance(intent, ProducerLaunchIntent) or not isinstance(attestation, ProducerLaunchAttestation):
        raise NativeTrustedPublicationError("native_trusted_publication_input_invalid")
    _id(nonce, "native_trusted_publication_nonce_invalid")
    record, _capture = _validate_preparation_shape(preparation, intent, attestation)
    token_sha256 = _token_hash(token)
    values: dict[str, object] = {
        "launch_id": intent.launch_id, "journal_id": intent.journal_id, "run_id": intent.run_id,
        "parent_task_id": intent.parent_task_id, "task_id": intent.task_id,
        "attestation_sha256": attestation.attestation_sha256,
        "preparation_sha256": preparation.receipt_sha256, "intent_sha256": intent.intent_sha256,
        "process_terminal_sha256": preparation.output.process_terminal_sha256,
        "output_capture_sha256": preparation.output.output_capture_sha256,
        "envelope_bytes_sha256": preparation.output.envelope_bytes_sha256,
        "admission_plan_sha256": preparation.output.admission_plan.digest(),
        "broker_evidence_sha256": record["broker_evidence_sha256"],
        "executable_sha256": attestation.executable_sha256, "executable_size": attestation.executable_size,
        "executable_device": attestation.executable_device, "executable_inode": attestation.executable_inode,
        "executable_mtime_ns": attestation.executable_mtime_ns, "executable_ctime_ns": attestation.executable_ctime_ns,
        "token_sha256": token_sha256, "nonce": nonce,
    }
    if any(not isinstance(value, str) for key, value in values.items() if key.endswith("sha256")):
        raise NativeTrustedPublicationError("native_trusted_publication_evidence_incomplete")
    authority_id = hashlib.sha256(
        _canonical({"scope": _SCOPE, "preparation_sha256": preparation.receipt_sha256,
                    "token_sha256": token_sha256, "nonce": nonce})
    ).hexdigest()
    body = {
        "schema_version": _SCHEMA, "protocol": _PROTOCOL, "scope": _SCOPE,
        "authority_id": authority_id, **values,
    }
    return NativeTrustedPublicationAuthority(
        **values, authority_id=authority_id, authority_sha256=_digest_body(body),
    )


def _marker_path(workspace: str | Path, authority: NativeTrustedPublicationAuthority) -> Path:
    root = Path(workspace).expanduser().absolute()
    batch = root / "evolution" / "producer-batches" / authority.journal_id
    if not batch.is_dir() or batch.is_symlink() or batch.parent.is_symlink():
        raise NativeTrustedPublicationError("native_trusted_publication_batch_invalid")
    path = batch / _MARKER
    if path.is_symlink():
        raise NativeTrustedPublicationError("native_trusted_publication_authority_replay")
    return path


def _check_token(authority: NativeTrustedPublicationAuthority, token: str) -> None:
    if _token_hash(token) != authority.token_sha256:
        raise NativeTrustedPublicationError("native_trusted_publication_token_mismatch")


def _assert_unconsumed(workspace: str | Path, authority: NativeTrustedPublicationAuthority) -> Path:
    path = _marker_path(workspace, authority)
    if not path.exists():
        return path
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise NativeTrustedPublicationError("native_trusted_publication_authority_replay") from exc
    if not isinstance(stored, dict) or stored.get("authority_sha256") != authority.authority_sha256:
        raise NativeTrustedPublicationError("native_trusted_publication_authority_replay")
    raise NativeTrustedPublicationError("native_trusted_publication_authority_replay")


def _consume(path: Path, authority: NativeTrustedPublicationAuthority, publication_status: str) -> Path:
    if publication_status not in {"published", "all_rejected"}:
        raise NativeTrustedPublicationError("native_trusted_publication_terminal_invalid")
    value = {**authority.to_dict(), "status": "consumed", "publication_status": publication_status}
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(_canonical(value).decode("utf-8"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise NativeTrustedPublicationError("native_trusted_publication_authority_replay") from exc
    except OSError as exc:
        raise NativeTrustedPublicationError("native_trusted_publication_authority_write_unknown") from exc
    return path


def run_native_trusted_output_publication_transaction(
    workspace: str | Path,
    strategy: Any,
    *,
    intent: ProducerLaunchIntent,
    attestation: ProducerLaunchAttestation,
    artifact: NativeBootstrapArtifact,
    contract: AlgorithmProblemContract,
    groups: tuple[BundleGroup, ...] | list[BundleGroup],
    preparation_receipt_sha256: str,
    publication_authority: NativeTrustedPublicationAuthority,
    authority_token: str,
    journal_id: str,
    budget_sha256: str | None = None,
    execution_control: Any = None,
) -> Any:
    """Run Feature 153 for one exact preparation, then consume the authority terminally.

    This is explicitly offline_import. It never upgrades brokered request evidence to
    complete egress authority and has no production acceptance mode.
    """
    if not isinstance(publication_authority, NativeTrustedPublicationAuthority):
        raise NativeTrustedPublicationError("native_trusted_publication_authority_invalid")
    if publication_authority.scope != _SCOPE or journal_id != intent.journal_id:
        raise NativeTrustedPublicationError("native_trusted_publication_binding_mismatch")
    _check_token(publication_authority, authority_token)
    if publication_authority.journal_id != journal_id:
        raise NativeTrustedPublicationError("native_trusted_publication_binding_mismatch")
    try:
        verify_producer_launch_attestation(intent, attestation)
        preparation = recover_native_trusted_preparation(
            workspace, intent=intent, attestation=attestation, artifact=artifact,
            contract=contract, groups=tuple(groups), expected_receipt_sha256=preparation_receipt_sha256,
        )
        _validate_preparation_shape(preparation, intent, attestation)
    except NativeTrustedPreparationError as exc:
        raise NativeTrustedPublicationError("native_trusted_publication_preparation_unverified") from exc
    except NativeTrustedPublicationError:
        raise
    except Exception as exc:
        raise NativeTrustedPublicationError("native_trusted_publication_evidence_unverified") from exc
    fields = {
        "launch_id": intent.launch_id, "journal_id": intent.journal_id, "run_id": intent.run_id,
        "parent_task_id": intent.parent_task_id, "task_id": intent.task_id,
        "attestation_sha256": attestation.attestation_sha256,
        "preparation_sha256": preparation.receipt_sha256, "intent_sha256": intent.intent_sha256,
        "process_terminal_sha256": preparation.output.process_terminal_sha256,
        "output_capture_sha256": preparation.output.output_capture_sha256,
        "envelope_bytes_sha256": preparation.output.envelope_bytes_sha256,
        "admission_plan_sha256": preparation.output.admission_plan.digest(),
        "executable_sha256": attestation.executable_sha256, "executable_size": attestation.executable_size,
        "executable_device": attestation.executable_device, "executable_inode": attestation.executable_inode,
        "executable_mtime_ns": attestation.executable_mtime_ns, "executable_ctime_ns": attestation.executable_ctime_ns,
    }
    if any(getattr(publication_authority, key) != value for key, value in fields.items()):
        raise NativeTrustedPublicationError("native_trusted_publication_authority_mismatch")
    marker = _assert_unconsumed(workspace, publication_authority)
    from .producer_bundle_transaction import run_native_producer_bundle_publication_transaction
    try:
        result = run_native_producer_bundle_publication_transaction(
            workspace, strategy, preparation.output.drafts, preparation.output.admission_plan,
            journal_id=journal_id, run_id=intent.run_id, parent_task_id=intent.parent_task_id,
            task_id=intent.task_id, budget_sha256=budget_sha256, execution_control=execution_control,
        )
    except Exception as exc:
        raise NativeTrustedPublicationError("native_trusted_publication_transaction_failed") from exc
    _consume(marker, publication_authority, result.publication_status)
    return result


# Compatibility spelling used by early Feature 159 callers.
run_native_trusted_publication_transaction = run_native_trusted_output_publication_transaction


__all__ = [
    "NativeTrustedPublicationAuthority", "NativeTrustedPublicationError",
    "build_native_trusted_publication_authority", "run_native_trusted_output_publication_transaction",
    "run_native_trusted_publication_transaction",
]
