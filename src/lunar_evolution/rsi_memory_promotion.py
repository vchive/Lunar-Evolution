"""Provider-free wiring between transfer regression and memory governance.

``TransferRegressionSuite`` owns the no/old/current-memory comparison while
``MemoryGovernanceStore`` owns the durable admission state machine.  This module is the
small, explicit boundary between them.  It deliberately performs no evaluation and never
mutates :class:`~lunar_evolution.rsi_gateway.RSIMemoryStore`.

An eligible transfer report can advance an existing ``shadow`` admission to ``approved``.
Callers may request activation as a second, explicit step; the adapter always appends the
``approved`` revision first, so a single practice or transfer pass can never jump directly to
``active``.  Rejected reports and malformed evidence fail before any governance write.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from .candidate_evaluation_spec import canonical_json
from .rsi_learning import EMPTY_MEMORY_SNAPSHOT_SHA256
from .rsi_memory_governance import (
    MemoryAdmissionRecord,
    MemoryGovernanceError,
    MemoryGovernanceStore,
)
from .rsi_transfer_regression import TransferRegressionReport


class MemoryPromotionError(MemoryGovernanceError):
    """Fixed-code failures at the transfer-report promotion boundary."""


def _receipt(value: object, name: str) -> str:
    if type(value) is not str or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise MemoryPromotionError(f"rsi_memory_promotion_{name}_invalid")
    return value


def _evidence(report: TransferRegressionReport) -> dict[str, Any]:
    """Validate and copy the only fields allowed to cross the promotion boundary."""
    if not isinstance(report, TransferRegressionReport):
        raise MemoryPromotionError("rsi_memory_promotion_report_invalid")
    payload = report.to_dict()
    report_digest = payload.pop("report_sha256", None)
    payload.pop("protocol", None)
    payload.pop("schema_version", None)
    try:
        expected_digest = hashlib.sha256(canonical_json(payload, maximum=128 * 1024)).hexdigest()
    except Exception as exc:
        raise MemoryPromotionError("rsi_memory_promotion_report_invalid") from exc
    if report_digest != expected_digest:
        raise MemoryPromotionError("rsi_memory_promotion_report_drift")
    if report.promotion_eligible is not True:
        # Keep the report inspectable to callers, but never allow a rejected report to write a
        # governance revision (in particular, never turn rejection into regression_passed=True).
        raise MemoryPromotionError("rsi_memory_promotion_report_rejected")
    evidence = report.promotion_evidence()
    if not isinstance(evidence, Mapping):
        raise MemoryPromotionError("rsi_memory_promotion_evidence_invalid")
    required = {"holdout_receipt_sha256", "baseline_receipt_sha256", "regression_passed"}
    if set(evidence) != required or evidence["regression_passed"] is not True:
        raise MemoryPromotionError("rsi_memory_promotion_regression_gate")
    return {
        "holdout_receipt_sha256": _receipt(evidence["holdout_receipt_sha256"], "holdout_receipt"),
        "baseline_receipt_sha256": _receipt(evidence["baseline_receipt_sha256"], "baseline_receipt"),
        "regression_passed": True,
    }


class MemoryPromotionAdapter:
    """Apply a transfer report to an existing memory admission.

    The adapter expects the caller to have completed the independent source/verifier and
    ``candidate -> shadow`` gates.  It accepts only a real ``TransferRegressionReport`` and
    delegates CAS, compatibility, revoke and lifecycle checks to ``MemoryGovernanceStore``.
    """

    def __init__(self, governance: MemoryGovernanceStore) -> None:
        if not isinstance(governance, MemoryGovernanceStore):
            raise MemoryPromotionError("rsi_memory_promotion_governance_invalid")
        self.governance = governance

    def approve(
        self,
        admission_id: str,
        report: TransferRegressionReport,
        *,
        expected_record_sha256: str,
        compatibility: Mapping[str, object] | None = None,
    ) -> MemoryAdmissionRecord:
        """Append ``shadow -> approved`` using the report's holdout/baseline evidence."""
        evidence = _evidence(report)
        current = self.governance.get(admission_id)
        if current is None:
            raise MemoryGovernanceError("rsi_memory_governance_missing")
        if current.record_sha256 != expected_record_sha256:
            raise MemoryGovernanceError("rsi_memory_governance_cas_conflict")
        if compatibility is None:
            compatibility = current.compatibility
        if (
            current.memory_snapshot_sha256 != report.current_memory_sha256
            or (current.parent_snapshot_sha256 or EMPTY_MEMORY_SNAPSHOT_SHA256) != report.old_memory_sha256
        ):
            raise MemoryPromotionError("rsi_memory_promotion_snapshot_drift")
        return self.governance.transition(
            admission_id,
            "approved",
            expected_record_sha256=expected_record_sha256,
            compatibility=compatibility,
            **evidence,
        )

    def activate(
        self,
        admission_id: str,
        report: TransferRegressionReport,
        *,
        expected_record_sha256: str,
        compatibility: Mapping[str, object] | None = None,
    ) -> MemoryAdmissionRecord:
        """Approve and then activate, retaining both durable lifecycle revisions.

        ``expected_record_sha256`` must point at the current ``shadow`` head.  The method never
        accepts an ``active`` target from a caller and therefore cannot skip the approved gate.
        """
        approved = self.approve(
            admission_id,
            report,
            expected_record_sha256=expected_record_sha256,
            compatibility=compatibility,
        )
        return self.governance.transition(
            admission_id,
            "active",
            expected_record_sha256=approved.record_sha256,
            compatibility=compatibility,
        )

    def promote(
        self,
        admission_id: str,
        report: TransferRegressionReport,
        *,
        expected_record_sha256: str,
        compatibility: Mapping[str, object] | None = None,
        activate: bool = False,
    ) -> MemoryAdmissionRecord:
        """Promote to ``approved`` or, when explicitly requested, through ``active``."""
        if type(activate) is not bool:
            raise MemoryPromotionError("rsi_memory_promotion_activate_invalid")
        if activate:
            return self.activate(
                admission_id,
                report,
                expected_record_sha256=expected_record_sha256,
                compatibility=compatibility,
            )
        return self.approve(
            admission_id,
            report,
            expected_record_sha256=expected_record_sha256,
            compatibility=compatibility,
        )


def promote_transfer_report(
    governance: MemoryGovernanceStore,
    admission_id: str,
    report: TransferRegressionReport,
    *,
    expected_record_sha256: str,
    compatibility: Mapping[str, object] | None = None,
    activate: bool = False,
) -> MemoryAdmissionRecord:
    """Functional convenience wrapper for :class:`MemoryPromotionAdapter`."""
    return MemoryPromotionAdapter(governance).promote(
        admission_id,
        report,
        expected_record_sha256=expected_record_sha256,
        compatibility=compatibility,
        activate=activate,
    )


__all__ = ["MemoryPromotionAdapter", "MemoryPromotionError", "promote_transfer_report"]
