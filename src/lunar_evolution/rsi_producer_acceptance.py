"""Provider-free composition of retained producer lifecycle evidence.

This module deliberately stops at a detached acceptance envelope.  It joins the existing
project profile preflight, retained Python terminal check, and optional retained replay summary;
it never launches a producer/evaluator, opens an RSI ledger, or grants production authority.
The resulting envelope is always ``blocked`` until the separate sealed-runtime and Linux
acceptance gates have been independently completed.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, NoReturn

from .candidate_evaluation_spec import canonical_json

PRODUCER_ACCEPTANCE_PROTOCOL = "lunar-rsi-producer-acceptance-envelope-v1"
PRODUCER_ACCEPTANCE_SCHEMA_VERSION = "1"
MAX_PRODUCER_ACCEPTANCE_BYTES = 32 * 1024

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_PROFILE_PROTOCOL = "lunar-rsi-project-lifecycle-profile-v1"
_TERMINAL_SCOPE = "retained_python_terminal"
_REPLAY_SCOPE = "retained_local_comparison"
_TERMINAL_STATES = frozenset({"completed", "failed", "cancelled", "unknown"})
_REPLAY_STATES = frozenset({"completed", "unknown", "drifted"})
_REPLAY_FIELDS = frozenset({"status", "evidence_scope", "read_only", "production_admission"})
_FIELDS = frozenset({
    "schema_version", "protocol", "profile_sha256", "producer_id", "project_id",
    "terminal_sha256", "terminal_status", "replay_status", "replay_evidence_scope",
    "status", "reason", "missing_gates", "execution_performed", "evaluator_invoked",
    "production_admission", "online_publication", "envelope_sha256",
})


class ProducerAcceptanceEnvelopeError(ValueError):
    """Fixed-code refusal without paths, process output, or provider text."""

    def __init__(self, code: str) -> None:
        self.code = "rsi_producer_acceptance_" + code
        super().__init__(self.code)


def _fail(code: str) -> NoReturn:
    raise ProducerAcceptanceEnvelopeError(code)


def _digest(value: object, code: str = "digest_invalid") -> str:
    if type(value) is not str or _DIGEST.fullmatch(value) is None or value == "0" * 64:
        _fail(code)
    return value


def _identifier(value: object, code: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        _fail(code)
    return value


def _mapping(value: object, code: str) -> dict[str, Any]:
    if type(value) is not dict:
        _fail(code)
    return value


def _canonical(value: object) -> bytes:
    try:
        return canonical_json(value, maximum=MAX_PRODUCER_ACCEPTANCE_BYTES)
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        raise ProducerAcceptanceEnvelopeError("json_invalid") from exc


def _digest_without(value: Mapping[str, object], field: str) -> str:
    body = dict(value)
    body.pop(field, None)
    return hashlib.sha256(_canonical(body)).hexdigest()


def _validate_profile(value: object) -> dict[str, Any]:
    profile = _mapping(value, "profile_invalid")
    required = {
        "status", "reason", "protocol", "schema_version", "profile_sha256", "producer_id",
        "project_id", "entrypoint", "launch_mode", "cancel_mode", "resume_mode",
        "missing_gates", "execution_performed", "evaluator_invoked", "production_admission",
        "online_publication", "evidence_scope",
    }
    if set(profile) != required:
        _fail("profile_invalid")
    if (profile["status"] != "blocked" or profile["reason"] != "runtime_acceptance_required"
            or profile["protocol"] != _PROFILE_PROTOCOL or profile["schema_version"] != "1"):
        _fail("profile_unaccepted")
    _digest(profile["profile_sha256"], "profile_digest_invalid")
    _identifier(profile["producer_id"], "producer_invalid")
    _identifier(profile["project_id"], "project_invalid")
    if (type(profile["entrypoint"]) is not str or not profile["entrypoint"]
            or profile["entrypoint"].startswith("/") or "\\" in profile["entrypoint"]):
        _fail("profile_entrypoint_invalid")
    if (profile["launch_mode"] != "native_bootstrap" or profile["cancel_mode"] != "owner_group"
            or profile["resume_mode"] != "retained_read_only"
            or profile["evidence_scope"] != "detached_profile_preflight"):
        _fail("profile_contract_invalid")
    if type(profile["missing_gates"]) is not list or not profile["missing_gates"] or any(
        type(item) is not str or not item for item in profile["missing_gates"]
    ):
        _fail("profile_gates_invalid")
    for field in ("execution_performed", "evaluator_invoked", "production_admission", "online_publication"):
        if profile[field] is not False:
            _fail("profile_authority_invalid")
    return profile


def _validate_terminal(value: object) -> dict[str, Any]:
    terminal = _mapping(value, "terminal_invalid")
    required = {
        "status", "reason", "terminal_sha256", "binding_sha256", "run_id", "journal_id",
        "launch_id", "cleanup_status", "request_count", "reconcile_required", "read_only",
        "evidence_scope", "production_admission", "online_publication",
    }
    if set(terminal) != required:
        _fail("terminal_invalid")
    if terminal["status"] not in _TERMINAL_STATES:
        _fail("terminal_status_invalid")
    _digest(terminal["terminal_sha256"], "terminal_digest_invalid")
    _digest(terminal["binding_sha256"], "binding_digest_invalid")
    for field in ("run_id", "journal_id", "launch_id"):
        _identifier(terminal[field], "terminal_identity_invalid")
    if type(terminal["cleanup_status"]) is not str or not terminal["cleanup_status"]:
        _fail("terminal_cleanup_invalid")
    if type(terminal["request_count"]) is not int or terminal["request_count"] < 0:
        _fail("terminal_request_count_invalid")
    if terminal["reconcile_required"] is not (terminal["status"] == "unknown"):
        _fail("terminal_reconcile_invalid")
    if terminal["read_only"] is not True or terminal["evidence_scope"] != _TERMINAL_SCOPE:
        _fail("terminal_scope_invalid")
    if terminal["production_admission"] is not False or terminal["online_publication"] is not False:
        _fail("terminal_authority_invalid")
    return terminal


def _validate_replay(value: object | None) -> tuple[str | None, str | None]:
    if value is None:
        return None, None
    replay = _mapping(value, "replay_invalid")
    # This is an untrusted detached report.  Keep its wire deliberately closed so
    # future fields cannot smuggle an unreviewed authority or path-bearing value
    # into the acceptance envelope.  The report is only a four-field projection;
    # richer producer material belongs in the separately pinned replay source.
    if set(replay) != _REPLAY_FIELDS:
        _fail("replay_invalid")
    if type(replay["status"]) is not str or replay["status"] not in _REPLAY_STATES:
        _fail("replay_status_invalid")
    if type(replay["evidence_scope"]) is not str or replay["evidence_scope"] != _REPLAY_SCOPE:
        _fail("replay_scope_invalid")
    if replay["read_only"] is not True:
        _fail("replay_scope_invalid")
    if replay["production_admission"] is not False:
        _fail("replay_authority_invalid")
    return replay["status"], replay["evidence_scope"]


@dataclass(frozen=True, slots=True)
class ProducerAcceptanceEnvelope:
    """Path-free snapshot of retained lifecycle evidence; never an admission decision."""

    profile_sha256: str
    producer_id: str
    project_id: str
    terminal_sha256: str
    terminal_status: str
    replay_status: str | None
    replay_evidence_scope: str | None
    missing_gates: tuple[str, ...]
    envelope_sha256: str | None = None
    schema_version: str = PRODUCER_ACCEPTANCE_SCHEMA_VERSION
    protocol: str = PRODUCER_ACCEPTANCE_PROTOCOL
    status: str = "blocked"
    reason: str = "runtime_acceptance_required"
    execution_performed: bool = False
    evaluator_invoked: bool = False
    production_admission: bool = False
    online_publication: bool = False

    def __post_init__(self) -> None:
        if self.schema_version != PRODUCER_ACCEPTANCE_SCHEMA_VERSION or self.protocol != PRODUCER_ACCEPTANCE_PROTOCOL:
            _fail("schema_invalid")
        _digest(self.profile_sha256, "profile_digest_invalid")
        _identifier(self.producer_id, "producer_invalid")
        _identifier(self.project_id, "project_invalid")
        _digest(self.terminal_sha256, "terminal_digest_invalid")
        if self.terminal_status not in _TERMINAL_STATES:
            _fail("terminal_status_invalid")
        if self.replay_status is not None and self.replay_status not in _REPLAY_STATES:
            _fail("replay_status_invalid")
        if self.replay_status is None and self.replay_evidence_scope is not None:
            _fail("replay_scope_invalid")
        if self.replay_status is not None and self.replay_evidence_scope != _REPLAY_SCOPE:
            _fail("replay_scope_invalid")
        if (self.status != "blocked" or self.reason != "runtime_acceptance_required"
                or type(self.missing_gates) is not tuple or not self.missing_gates
                or any(type(item) is not str or not item for item in self.missing_gates)):
            _fail("status_invalid")
        if any(getattr(self, field) is not False for field in (
            "execution_performed", "evaluator_invoked", "production_admission", "online_publication",
        )):
            _fail("authority_invalid")
        if self.envelope_sha256 is not None:
            _digest(self.envelope_sha256, "envelope_digest_invalid")
            if self.envelope_sha256 != self.digest():
                _fail("envelope_digest_mismatch")

    def _wire(self, *, include_digest: bool = True) -> dict[str, Any]:
        body: dict[str, Any] = {
            "schema_version": self.schema_version, "protocol": self.protocol,
            "profile_sha256": self.profile_sha256, "producer_id": self.producer_id,
            "project_id": self.project_id, "terminal_sha256": self.terminal_sha256,
            "terminal_status": self.terminal_status, "replay_status": self.replay_status,
            "replay_evidence_scope": self.replay_evidence_scope, "status": self.status,
            "reason": self.reason, "missing_gates": list(self.missing_gates),
            "execution_performed": self.execution_performed, "evaluator_invoked": self.evaluator_invoked,
            "production_admission": self.production_admission, "online_publication": self.online_publication,
        }
        if include_digest:
            body["envelope_sha256"] = self.envelope_sha256
        return body

    def digest(self) -> str:
        return _digest_without(self._wire(include_digest=False), "envelope_sha256")

    def to_dict(self) -> dict[str, Any]:
        self.__post_init__()
        return {**self._wire(), "envelope_sha256": self.envelope_sha256 or self.digest()}

    def to_json(self) -> bytes:
        return _canonical(self.to_dict())

    @classmethod
    def from_dict(cls, value: object) -> ProducerAcceptanceEnvelope:
        raw = _mapping(value, "envelope_invalid")
        if set(raw) != _FIELDS:
            _fail("envelope_schema_invalid")
        try:
            if type(raw["missing_gates"]) is not list:
                _fail("envelope_schema_invalid")
            return cls(
                profile_sha256=raw["profile_sha256"], producer_id=raw["producer_id"],
                project_id=raw["project_id"], terminal_sha256=raw["terminal_sha256"],
                terminal_status=raw["terminal_status"], replay_status=raw["replay_status"],
                replay_evidence_scope=raw["replay_evidence_scope"],
                missing_gates=tuple(raw["missing_gates"]),
                envelope_sha256=raw["envelope_sha256"], schema_version=raw["schema_version"],
                protocol=raw["protocol"], status=raw["status"], reason=raw["reason"],
                execution_performed=raw["execution_performed"], evaluator_invoked=raw["evaluator_invoked"],
                production_admission=raw["production_admission"], online_publication=raw["online_publication"],
            )
        except ProducerAcceptanceEnvelopeError:
            raise
        except (TypeError, ValueError, KeyError, RecursionError):
            _fail("envelope_invalid")


def build_producer_acceptance_envelope(
    profile: Mapping[str, object], terminal: Mapping[str, object], replay: Mapping[str, object] | None = None,
) -> ProducerAcceptanceEnvelope:
    """Compose existing detached reports into a blocked, path-free acceptance envelope."""
    profile_value = _validate_profile(profile)
    terminal_value = _validate_terminal(terminal)
    replay_status, replay_scope = _validate_replay(replay)
    missing = list(dict.fromkeys(str(item) for item in profile_value["missing_gates"]))
    if terminal_value["status"] == "unknown":
        missing.append("terminal_reconcile")
    if replay_status != "completed":
        missing.append("retained_replay_completed")
    item = ProducerAcceptanceEnvelope(
        profile_sha256=profile_value["profile_sha256"], producer_id=profile_value["producer_id"],
        project_id=profile_value["project_id"], terminal_sha256=terminal_value["terminal_sha256"],
        terminal_status=terminal_value["status"], replay_status=replay_status,
        replay_evidence_scope=replay_scope, missing_gates=tuple(dict.fromkeys(missing)),
    )
    return ProducerAcceptanceEnvelope.from_dict(item.to_dict())


__all__ = [
    "MAX_PRODUCER_ACCEPTANCE_BYTES", "PRODUCER_ACCEPTANCE_PROTOCOL",
    "PRODUCER_ACCEPTANCE_SCHEMA_VERSION", "ProducerAcceptanceEnvelope",
    "ProducerAcceptanceEnvelopeError", "build_producer_acceptance_envelope",
]
