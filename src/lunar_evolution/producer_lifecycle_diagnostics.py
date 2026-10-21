"""Read-only owner/lifecycle acceptance diagnostics.

The producer process runner already records a durable registration, terminal receipt, and
recovery receipt.  This module gives the P1 acceptance work a small, path-free projection for
those observations.  It deliberately consumes detached phase observations only: it never starts
or signals a process, replays a producer, or grants runtime/publication authority.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any, NoReturn

from .candidate_evaluation_spec import canonical_json

PRODUCER_LIFECYCLE_DIAGNOSTIC_PROTOCOL = "lunar-producer-lifecycle-diagnostic-v1"
PRODUCER_LIFECYCLE_DIAGNOSTIC_SCHEMA_VERSION = "1"
MAX_PRODUCER_LIFECYCLE_DIAGNOSTIC_BYTES = 64 * 1024

LIFECYCLE_PHASES = (
    "startup",
    "cancellation",
    "timeout",
    "parent_loss",
    "cleanup",
    "restart_recovery",
)

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_OUTCOMES = frozenset({"completed", "failed", "cancelled", "timeout", "unknown"})
_PHASE_FIELDS = frozenset({
    "outcome", "owner_verified", "terminal_persisted", "cleanup_verified",
    "recovery_read_only", "relaunch_performed", "execution_performed",
})
_REPORT_FIELDS = frozenset({
    "schema_version", "protocol", "phase_observations", "phase_status", "missing_phases",
    "status", "evidence_scope", "execution_performed", "production_admission",
    "online_publication", "diagnostic_sha256",
})
_PHASE_REASONS = frozenset({
    "owner_and_terminal_bound", "owner_or_terminal_missing",
    "cancelled_with_verified_cleanup", "cancel_or_cleanup_evidence_missing",
    "deadline_with_verified_cleanup", "deadline_cleanup_uncertainty_preserved",
    "deadline_or_terminal_evidence_missing", "parent_loss_requires_read_only_reconcile",
    "parent_loss_recovery_evidence_missing", "owner_checked_cleanup",
    "owner_or_cleanup_evidence_missing", "restart_is_read_only_without_relaunch",
    "restart_recovery_boundary_missing", "evidence_missing",
})


class ProducerLifecycleDiagnosticError(ValueError):
    """Fixed-code diagnostic refusal without paths, PIDs, or process output."""

    def __init__(self, code: str) -> None:
        self.code = "producer_lifecycle_diagnostic_" + code
        super().__init__(self.code)


def _fail(code: str) -> NoReturn:
    raise ProducerLifecycleDiagnosticError(code)


def _canonical(value: object) -> bytes:
    try:
        return canonical_json(value, maximum=MAX_PRODUCER_LIFECYCLE_DIAGNOSTIC_BYTES)
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        raise ProducerLifecycleDiagnosticError("json_invalid") from exc


def _digest_without(value: Mapping[str, object], field: str) -> str:
    body = dict(value)
    body.pop(field, None)
    return hashlib.sha256(_canonical(body)).hexdigest()


def _digest(value: object) -> str:
    if type(value) is not str or _DIGEST.fullmatch(value) is None or value == "0" * 64:
        _fail("digest_invalid")
    return value


def _phase(value: object) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _PHASE_FIELDS:
        _fail("phase_schema_invalid")
    if type(value["outcome"]) is not str or value["outcome"] not in _OUTCOMES:
        _fail("phase_outcome_invalid")
    for field in (
        "owner_verified", "terminal_persisted", "cleanup_verified", "recovery_read_only",
        "relaunch_performed", "execution_performed",
    ):
        if type(value[field]) is not bool:
            _fail("phase_boolean_invalid")
    return value


def _phase_acceptance(name: str, observation: Mapping[str, object]) -> tuple[bool, str]:
    """Return whether one phase has the evidence required by the offline gate.

    ``unknown`` is an accepted *lifecycle outcome* for timeout and parent-loss cases when it is
    durably preserved and no relaunch occurred.  It is never treated as successful execution.
    """
    outcome = observation["outcome"]
    owner = observation["owner_verified"]
    terminal = observation["terminal_persisted"]
    cleanup = observation["cleanup_verified"]
    read_only = observation["recovery_read_only"]
    relaunched = observation["relaunch_performed"]

    if name == "startup":
        if owner and terminal and not relaunched:
            return True, "owner_and_terminal_bound"
        return False, "owner_or_terminal_missing"
    if name == "cancellation":
        if outcome == "cancelled" and owner and terminal and cleanup and not relaunched:
            return True, "cancelled_with_verified_cleanup"
        return False, "cancel_or_cleanup_evidence_missing"
    if name == "timeout":
        if outcome in {"timeout", "unknown"} and owner and terminal and not relaunched:
            if cleanup:
                return True, "deadline_with_verified_cleanup"
            return True, "deadline_cleanup_uncertainty_preserved"
        return False, "deadline_or_terminal_evidence_missing"
    if name == "parent_loss":
        if outcome == "unknown" and owner and read_only and not relaunched:
            return True, "parent_loss_requires_read_only_reconcile"
        return False, "parent_loss_recovery_evidence_missing"
    if name == "cleanup":
        if owner and cleanup and not relaunched:
            return True, "owner_checked_cleanup"
        return False, "owner_or_cleanup_evidence_missing"
    if name == "restart_recovery":
        if read_only and not relaunched and (terminal or outcome == "unknown"):
            return True, "restart_is_read_only_without_relaunch"
        return False, "restart_recovery_boundary_missing"
    _fail("phase_unknown")


def build_producer_lifecycle_diagnostic(
    observations: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    """Build a bounded, path-free projection of retained lifecycle phase observations.

    Missing phases remain ``blocked``.  A report with every phase accepted is only an
    ``offline_verified`` diagnostic; the two authority flags are always false.
    """
    if type(observations) is not dict:
        _fail("observations_invalid")
    unknown = set(observations).difference(LIFECYCLE_PHASES)
    if unknown:
        _fail("phase_unknown")
    parsed: dict[str, dict[str, Any]] = {}
    phase_status: dict[str, dict[str, str]] = {}
    missing: list[str] = []
    execution_performed = False
    for name in LIFECYCLE_PHASES:
        raw = observations.get(name)
        if raw is None:
            missing.append(name)
            phase_status[name] = {"status": "blocked", "reason": "evidence_missing"}
            continue
        item = _phase(raw)
        parsed[name] = dict(item)
        execution_performed = execution_performed or item["execution_performed"]
        accepted, reason = _phase_acceptance(name, item)
        phase_status[name] = {"status": "verified" if accepted else "blocked", "reason": reason}
    status = "offline_verified" if not missing and all(
        item["status"] == "verified" for item in phase_status.values()
    ) else "blocked"
    report: dict[str, object] = {
        "schema_version": PRODUCER_LIFECYCLE_DIAGNOSTIC_SCHEMA_VERSION,
        "protocol": PRODUCER_LIFECYCLE_DIAGNOSTIC_PROTOCOL,
        "phase_observations": parsed,
        "phase_status": phase_status,
        "missing_phases": missing,
        "status": status,
        "evidence_scope": "retained_process_lifecycle",
        "execution_performed": execution_performed,
        "production_admission": False,
        "online_publication": False,
        "diagnostic_sha256": "",
    }
    report["diagnostic_sha256"] = _digest_without(report, "diagnostic_sha256")
    return report


def parse_producer_lifecycle_diagnostic(value: object) -> dict[str, object]:
    """Validate a detached report and return a plain copy suitable for inspection."""
    if type(value) is not dict or set(value) != _REPORT_FIELDS:
        _fail("report_schema_invalid")
    _digest(value["diagnostic_sha256"])
    if value["diagnostic_sha256"] != _digest_without(value, "diagnostic_sha256"):
        _fail("report_digest_mismatch")
    if value["schema_version"] != PRODUCER_LIFECYCLE_DIAGNOSTIC_SCHEMA_VERSION:
        _fail("report_schema_invalid")
    if value["protocol"] != PRODUCER_LIFECYCLE_DIAGNOSTIC_PROTOCOL:
        _fail("report_protocol_invalid")
    if value["evidence_scope"] != "retained_process_lifecycle":
        _fail("report_scope_invalid")
    if type(value["phase_observations"]) is not dict or type(value["phase_status"]) is not dict:
        _fail("report_phase_invalid")
    if set(value["phase_observations"]).difference(LIFECYCLE_PHASES):
        _fail("report_phase_invalid")
    if set(value["phase_status"]) != set(LIFECYCLE_PHASES):
        _fail("report_phase_invalid")
    for name, item in value["phase_observations"].items():
        _phase(item)
        status = value["phase_status"][name]
        if type(status) is not dict or set(status) != {"status", "reason"}:
            _fail("report_phase_invalid")
        expected_accepted, expected_reason = _phase_acceptance(name, item)
        expected = {
            "status": "verified" if expected_accepted else "blocked",
            "reason": expected_reason,
        }
        if status != expected or status["reason"] not in _PHASE_REASONS:
            _fail("report_phase_invalid")
    for name in set(LIFECYCLE_PHASES).difference(value["phase_observations"]):
        status = value["phase_status"][name]
        if type(status) is not dict or set(status) != {"status", "reason"}:
            _fail("report_phase_invalid")
        if status != {"status": "blocked", "reason": "evidence_missing"}:
            _fail("report_phase_invalid")
    missing = value["missing_phases"]
    if (type(missing) is not list or len(missing) != len(set(missing))
            or any(phase not in LIFECYCLE_PHASES for phase in missing)
            or set(missing) != set(LIFECYCLE_PHASES).difference(value["phase_observations"])):
        _fail("report_phase_invalid")
    if value["status"] not in {"offline_verified", "blocked"}:
        _fail("report_status_invalid")
    expected_status = "offline_verified" if not missing and all(
        value["phase_status"][phase]["status"] == "verified" for phase in LIFECYCLE_PHASES
    ) else "blocked"
    if value["status"] != expected_status:
        _fail("report_status_invalid")
    if type(value["execution_performed"]) is not bool:
        _fail("report_execution_invalid")
    if value["execution_performed"] != any(
        item["execution_performed"] for item in value["phase_observations"].values()
    ):
        _fail("report_execution_invalid")
    if value["production_admission"] is not False or value["online_publication"] is not False:
        _fail("report_authority_invalid")
    return dict(value)


__all__ = [
    "LIFECYCLE_PHASES",
    "MAX_PRODUCER_LIFECYCLE_DIAGNOSTIC_BYTES",
    "PRODUCER_LIFECYCLE_DIAGNOSTIC_PROTOCOL",
    "PRODUCER_LIFECYCLE_DIAGNOSTIC_SCHEMA_VERSION",
    "ProducerLifecycleDiagnosticError",
    "build_producer_lifecycle_diagnostic",
    "parse_producer_lifecycle_diagnostic",
]
