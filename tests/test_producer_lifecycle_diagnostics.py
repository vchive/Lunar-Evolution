"""Focused read-only owner/lifecycle acceptance diagnostics."""
from __future__ import annotations

from copy import deepcopy

import pytest

from lunar_evolution.producer_lifecycle_diagnostics import (
    LIFECYCLE_PHASES,
    ProducerLifecycleDiagnosticError,
    _digest_without,
    build_producer_lifecycle_diagnostic,
    parse_producer_lifecycle_diagnostic,
)


def _phase(outcome: str = "completed", **overrides: bool) -> dict[str, object]:
    value: dict[str, object] = {
        "outcome": outcome,
        "owner_verified": True,
        "terminal_persisted": True,
        "cleanup_verified": True,
        "recovery_read_only": True,
        "relaunch_performed": False,
        "execution_performed": False,
    }
    value.update(overrides)
    return value


def _complete() -> dict[str, dict[str, object]]:
    return {
        "startup": _phase(),
        "cancellation": _phase("cancelled"),
        "timeout": _phase("timeout"),
        "parent_loss": _phase("unknown", terminal_persisted=False),
        "cleanup": _phase(),
        "restart_recovery": _phase("unknown", terminal_persisted=False),
    }


def test_complete_matrix_is_offline_verified_but_never_authority() -> None:
    report = build_producer_lifecycle_diagnostic(_complete())
    assert report["status"] == "offline_verified"
    assert report["missing_phases"] == []
    assert report["production_admission"] is False
    assert report["online_publication"] is False
    assert parse_producer_lifecycle_diagnostic(report) == report
    assert all(report["phase_status"][phase]["status"] == "verified" for phase in LIFECYCLE_PHASES)


def test_missing_phase_is_blocked_without_inventing_evidence() -> None:
    observations = _complete()
    del observations["parent_loss"]
    report = build_producer_lifecycle_diagnostic(observations)
    assert report["status"] == "blocked"
    assert report["missing_phases"] == ["parent_loss"]
    assert report["phase_status"]["parent_loss"] == {
        "status": "blocked", "reason": "evidence_missing",
    }


def test_timeout_cleanup_uncertainty_remains_an_accepted_unknown_outcome() -> None:
    observations = _complete()
    observations["timeout"] = _phase(
        "unknown", cleanup_verified=False, terminal_persisted=True,
    )
    report = build_producer_lifecycle_diagnostic(observations)
    assert report["phase_status"]["timeout"] == {
        "status": "verified", "reason": "deadline_cleanup_uncertainty_preserved",
    }


@pytest.mark.parametrize(
    ("phase", "changes"),
    [
        ("cancellation", {"cleanup_verified": False}),
        ("parent_loss", {"recovery_read_only": False}),
        ("restart_recovery", {"relaunch_performed": True}),
    ],
)
def test_owner_lifecycle_gate_blocks_unsafe_phase(
    phase: str, changes: dict[str, object],
) -> None:
    observations = _complete()
    observations[phase] = {**observations[phase], **changes}
    report = build_producer_lifecycle_diagnostic(observations)
    assert report["status"] == "blocked"
    assert report["phase_status"][phase]["status"] == "blocked"


def test_parser_rejects_digest_drift_and_extra_phase() -> None:
    report = build_producer_lifecycle_diagnostic(_complete())
    tampered = deepcopy(report)
    tampered["phase_observations"]["startup"]["owner_verified"] = False
    with pytest.raises(ProducerLifecycleDiagnosticError, match="report_digest_mismatch"):
        parse_producer_lifecycle_diagnostic(tampered)

    with pytest.raises(ProducerLifecycleDiagnosticError, match="phase_unknown"):
        build_producer_lifecycle_diagnostic({**_complete(), "worker": _phase()})


def test_parser_rejects_nested_phase_status_schema_drift() -> None:
    report = build_producer_lifecycle_diagnostic(_complete())
    tampered = deepcopy(report)
    tampered["phase_status"]["startup"] = {"status": "verified", "reason": "caller_text"}
    tampered["diagnostic_sha256"] = _digest_without(tampered, "diagnostic_sha256")
    with pytest.raises(ProducerLifecycleDiagnosticError, match="report_phase_invalid"):
        parse_producer_lifecycle_diagnostic(tampered)


def test_execution_flag_is_observational_and_does_not_open_authority() -> None:
    observations = _complete()
    observations["startup"] = _phase(execution_performed=True)
    report = build_producer_lifecycle_diagnostic(observations)
    assert report["execution_performed"] is True
    assert report["production_admission"] is False
    assert report["online_publication"] is False
