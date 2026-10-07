"""Explicit composition facade for native RSI solver episodes.

This module joins the already validated native control-plane seams.  It intentionally does not
discover launch credentials, run an evaluator, or interpret producer output.  A caller supplies a
plan factory and a receipt provider; the provider must return the four request-bound records from
the same native attempt.
"""

from __future__ import annotations

import stat
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from .official_evaluator_evidence import (
    OfficialEvaluationReceipt,
    verify_official_evaluation,
)
from .rsi_gateway import SolverRequest, SolverResult
from .rsi_identity import RSIIdentityError, component_fingerprint
from .rsi_learning import MemorySnapshot, RSILearningError
from .rsi_native_candidate import (
    NativeCandidateRecord,
    NativeEvaluationReceipt,
    NativeExecutionReceipt,
    NativePublicationReceipt,
    map_native_receipts_to_solver_result,
    select_native_candidate,
)
from .rsi_native_failure import NativeRSIFailureEvidence, map_native_failure_to_solver_result
from .rsi_native_plan import NativeRSIExecutionPlan
from .rsi_store import NativeEpisodeClaim, RSILedger


class NativeRSISolverGatewayError(RSILearningError):
    """Fixed refusal codes for native gateway composition and recovery."""


@dataclass(frozen=True, slots=True)
class NativeRSIReceiptBundle:
    """Same-run candidate and independent execution/evaluation/publication evidence."""

    candidate: NativeCandidateRecord
    execution: NativeExecutionReceipt
    evaluation: NativeEvaluationReceipt
    publication: NativePublicationReceipt
    provenance_sha256: str | None = None
    worker_terminal_status: str | None = None
    official_evaluator_receipt: OfficialEvaluationReceipt | None = None

    def __post_init__(self) -> None:
        if self.provenance_sha256 is not None and (
            type(self.provenance_sha256) is not str or len(self.provenance_sha256) != 64
            or any(char not in "0123456789abcdef" for char in self.provenance_sha256)
        ):
            raise NativeRSISolverGatewayError("rsi_native_gateway_provenance_invalid")
        if self.worker_terminal_status is not None and self.worker_terminal_status not in {
            "completed", "failed", "timed_out", "cancelled", "abandoned", "unknown",
        }:
            raise NativeRSISolverGatewayError("rsi_native_gateway_worker_status_invalid")
        if self.official_evaluator_receipt is not None and not isinstance(
            self.official_evaluator_receipt, OfficialEvaluationReceipt,
        ):
            raise NativeRSISolverGatewayError("rsi_native_gateway_evaluator_receipt_invalid")


@dataclass(frozen=True, slots=True)
class NativeRSIExecutionConfig:
    """Immutable dependencies required to compose one native gateway.

    ``plan_factory`` rebuilds the frozen plan on every call, including replay and recovery checks.
    It must be pure and read-only: it cannot stage inputs, consume an attestation, or launch work.
    ``receipt_provider`` is invoked only after a new claim is acquired; scheduler integration and
    reading same-attempt evidence remain its caller-owned responsibilities. Both dependencies are
    explicit so the facade cannot accidentally reuse an unbound legacy producer receipt.
    """

    ledger: RSILedger
    plan_factory: Callable[[SolverRequest, MemorySnapshot], NativeRSIExecutionPlan]
    receipt_provider: Callable[[SolverRequest, NativeRSIExecutionPlan], NativeRSIReceiptBundle | NativeRSIFailureEvidence]

    def __post_init__(self) -> None:
        if not isinstance(self.ledger, RSILedger):
            raise NativeRSISolverGatewayError("rsi_native_gateway_ledger_invalid")
        if not callable(self.plan_factory) or not callable(self.receipt_provider):
            raise NativeRSISolverGatewayError("rsi_native_gateway_factory_invalid")


class NativeRSISolverGateway:
    """Durable native RSI gateway with strict claim, replay and receipt binding."""

    # Explicit capability consumed by ``PracticeEpisodeRunner``. Keeping this opt-in rather
    # than inspecting a callable signature preserves the legacy one-argument SolverGateway
    # protocol for all existing adapters.
    requires_memory_snapshot = True

    def __init__(self, config: NativeRSIExecutionConfig) -> None:
        if not isinstance(config, NativeRSIExecutionConfig):
            raise NativeRSISolverGatewayError("rsi_native_gateway_configuration_invalid")
        self.config = config
        try:
            info = self.ledger.database.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise OSError("invalid ledger path")
            self._ledger_identity = {
                "database": str(self.ledger.database.absolute()),
                "device": info.st_dev, "inode": info.st_ino,
            }
        except OSError as exc:
            raise NativeRSISolverGatewayError("rsi_native_gateway_ledger_invalid") from exc

    def _assert_ledger(self) -> None:
        """Check the prepared database before any callback or SQLite operation."""
        try:
            info = self.ledger.database.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                    {"database": str(self.ledger.database.absolute()),
                     "device": info.st_dev, "inode": info.st_ino} != self._ledger_identity):
                raise OSError("ledger replaced")
            check = getattr(self.config.receipt_provider, "assert_failure_ledger", None)
            if callable(check):
                check(self.ledger)
        except Exception as exc:
            raise NativeRSISolverGatewayError("rsi_native_gateway_ledger_changed") from exc

    @property
    def ledger(self) -> RSILedger:
        return self.config.ledger

    def rsi_fingerprint_config(self) -> dict[str, Any]:
        """Expose stable native wiring identity without hashing mutable runtime state.

        The controller persists this projection as part of the run identity.  It binds the
        durable ledger identity and the executable plan/receipt dependencies, while deliberately
        excluding counters, caches, and in-flight receipt state.  ``component_fingerprint``
        rejects mutable callable captures unless the callable provides an explicit stable config,
        so a gateway cannot silently resume with an unpinned provider.
        """
        try:
            self._assert_ledger()
            plan_fingerprint = component_fingerprint(self.config.plan_factory)
            receipt_fingerprint = component_fingerprint(self.config.receipt_provider)
        except (OSError, RSIIdentityError) as exc:
            raise NativeRSISolverGatewayError("rsi_native_gateway_fingerprint_invalid") from exc
        return {
            "protocol": "lunar-native-rsi-gateway-v1",
            "ledger": dict(self._ledger_identity),
            "plan_factory_sha256": plan_fingerprint,
            "receipt_provider_sha256": receipt_fingerprint,
        }

    def _plan(self, request: SolverRequest, memory: MemorySnapshot) -> NativeRSIExecutionPlan:
        self._assert_ledger()
        if not isinstance(request, SolverRequest) or not isinstance(memory, MemorySnapshot):
            raise NativeRSISolverGatewayError("rsi_native_gateway_input_invalid")
        if memory.digest() != request.memory_snapshot_sha256:
            raise NativeRSISolverGatewayError("rsi_native_gateway_memory_binding_mismatch")
        try:
            plan = self.config.plan_factory(request, memory)
            self._assert_ledger()
        except NativeRSISolverGatewayError:
            raise
        except Exception as exc:
            raise NativeRSISolverGatewayError("rsi_native_gateway_plan_failed") from exc
        if not isinstance(plan, NativeRSIExecutionPlan):
            raise NativeRSISolverGatewayError("rsi_native_gateway_plan_invalid")
        try:
            plan.assert_request_memory(request, memory)
        except Exception as exc:
            raise NativeRSISolverGatewayError("rsi_native_gateway_plan_binding_mismatch") from exc
        return plan

    def _replay(self, request: SolverRequest, plan: NativeRSIExecutionPlan) -> SolverResult:
        self._assert_ledger()
        saved = self.ledger.episode_result(request.episode_id)
        self._assert_ledger()
        if saved is None or saved[0] != request:
            raise NativeRSISolverGatewayError("rsi_native_gateway_replay_missing")
        recovery = getattr(self.config.receipt_provider, "recover", None)
        if saved[1].status in {"failed", "cancelled"} and not callable(recovery):
            raise NativeRSISolverGatewayError("rsi_native_gateway_failure_reader_required")
        if callable(recovery):
            try:
                bundle = recovery(request, plan)
                self._assert_ledger()
                result = self._map_outcome(request, plan, bundle)
                if result != saved[1]:
                    raise NativeRSISolverGatewayError("rsi_native_gateway_replay_result_drift")
            except Exception as exc:
                raise NativeRSISolverGatewayError("rsi_native_gateway_replay_evidence_invalid") from exc
        return saved[1]

    def _map_outcome(
        self, request: SolverRequest, plan: NativeRSIExecutionPlan,
        evidence: NativeRSIReceiptBundle | NativeRSIFailureEvidence,
        *, expected_claim: NativeEpisodeClaim | None = None,
    ) -> SolverResult:
        if isinstance(evidence, NativeRSIReceiptBundle):
            return self._map_bundle(request, plan, evidence)
        if not isinstance(evidence, NativeRSIFailureEvidence):
            raise NativeRSISolverGatewayError("rsi_native_gateway_receipts_invalid")
        self._assert_ledger()
        if not callable(getattr(self.config.receipt_provider, "assert_failure_ledger", None)):
            raise NativeRSISolverGatewayError("rsi_native_gateway_failure_ledger_required")
        if dict(evidence.ledger_identity) != self._ledger_identity:
            raise NativeRSISolverGatewayError("rsi_native_gateway_failure_ledger_mismatch")
        if expected_claim is not None and replace(expected_claim, status="started") != evidence.claim:
            raise NativeRSISolverGatewayError("rsi_native_gateway_failure_claim_mismatch")
        claim = self.ledger.inspect_native_episode_claim(request, plan_sha256=plan.plan_sha256)
        self._assert_ledger()
        if (claim is None or claim.status not in {"started", "failed", "cancelled"} or
                replace(claim, status="started") != evidence.claim):
            raise NativeRSISolverGatewayError("rsi_native_gateway_failure_claim_mismatch")
        return map_native_failure_to_solver_result(request, plan, evidence)

    def _read_failure(
        self, request: SolverRequest, memory: MemorySnapshot, *,
        expected_claim_sha256: str, expected_provenance_sha256: str,
    ) -> tuple[NativeRSIExecutionPlan, SolverResult, NativeEpisodeClaim]:
        """Inspect an independently pinned failure without publishing a result."""
        for digest in (expected_claim_sha256, expected_provenance_sha256):
            if (type(digest) is not str or len(digest) != 64 or
                    any(char not in "0123456789abcdef" for char in digest)):
                raise NativeRSISolverGatewayError("rsi_native_gateway_failure_pin_invalid")
        plan = self._plan(request, memory)
        claim = self.ledger.inspect_native_episode_claim(request, plan_sha256=plan.plan_sha256)
        self._assert_ledger()
        if (claim is None or claim.claim_sha256 != expected_claim_sha256 or
                claim.status not in {"started", "failed", "cancelled"}):
            raise NativeRSISolverGatewayError("rsi_native_gateway_failure_claim_mismatch")
        recovery = getattr(self.config.receipt_provider, "recover", None)
        if not callable(recovery):
            raise NativeRSISolverGatewayError("rsi_native_gateway_failure_reader_required")
        evidence = recovery(request, plan)
        self._assert_ledger()
        if (not isinstance(evidence, NativeRSIFailureEvidence) or
                evidence.provenance_sha256 != expected_provenance_sha256 or
                evidence.claim_sha256 != expected_claim_sha256):
            raise NativeRSISolverGatewayError("rsi_native_gateway_failure_proof_mismatch")
        result = self._map_outcome(request, plan, evidence, expected_claim=claim)
        saved = self.ledger.episode_result(request.episode_id)
        self._assert_ledger()
        if saved is not None and saved != (request, result):
            raise NativeRSISolverGatewayError("rsi_native_gateway_failure_result_conflict")
        # Re-read after callback and result inspection, retaining the original proof pin.
        repeated = recovery(request, plan)
        self._assert_ledger()
        if (not isinstance(repeated, NativeRSIFailureEvidence) or
                repeated.to_dict() != evidence.to_dict() or
                repeated.provenance_sha256 != expected_provenance_sha256 or
                self._map_outcome(request, plan, repeated, expected_claim=claim) != result):
            raise NativeRSISolverGatewayError("rsi_native_gateway_failure_proof_changed")
        return plan, result, claim

    def inspect_failure(
        self, request: SolverRequest, memory: MemorySnapshot, *,
        expected_claim_sha256: str, expected_provenance_sha256: str,
    ) -> SolverResult:
        """Read-only preflight for a controller's evidence budget reservation."""
        return self._read_failure(
            request, memory, expected_claim_sha256=expected_claim_sha256,
            expected_provenance_sha256=expected_provenance_sha256,
        )[1]

    def restore_failure(
        self, request: SolverRequest, memory: MemorySnapshot, *,
        expected_claim_sha256: str, expected_provenance_sha256: str,
        before_publish: Callable[[], None] | None = None,
    ) -> SolverResult:
        """Register existing failure proof only; a pending run still never relaunches."""
        if before_publish is not None and not callable(before_publish):
            raise NativeRSISolverGatewayError("rsi_native_gateway_failure_guard_invalid")
        plan, result, claim = self._read_failure(
            request, memory, expected_claim_sha256=expected_claim_sha256,
            expected_provenance_sha256=expected_provenance_sha256,
        )
        self._assert_ledger()
        if before_publish is not None:
            before_publish()
            self._assert_ledger()
        self.ledger.publish_native_episode_result(
            request, plan_sha256=plan.plan_sha256, result=result, expected_claim=claim,
        )
        self._assert_ledger()
        if self._replay(request, plan) != result:
            raise NativeRSISolverGatewayError("rsi_native_gateway_failure_result_conflict")
        return result

    @staticmethod
    def _map_bundle(
        request: SolverRequest, plan: NativeRSIExecutionPlan, bundle: NativeRSIReceiptBundle,
    ) -> SolverResult:
        if bundle.worker_terminal_status != "completed":
            raise NativeRSISolverGatewayError("rsi_native_gateway_worker_evidence_incomplete")
        if bundle.official_evaluator_receipt is None:
            raise NativeRSISolverGatewayError("rsi_native_gateway_official_evaluator_missing")
        try:
            verify_official_evaluation(
                bundle.official_evaluator_receipt,
                request_sha256=request.digest(), contract_sha256=request.contract_sha256,
                evaluator_sha256=request.evaluator_sha256,
                candidate_source_sha256=bundle.candidate.candidate_source_sha256,
                execution_receipt_sha256=bundle.execution.receipt_sha256,
                publication_receipt_sha256=bundle.publication.receipt_sha256,
            )
        except Exception as exc:
            raise NativeRSISolverGatewayError("rsi_native_gateway_official_evaluator_invalid") from exc
        result = map_native_receipts_to_solver_result(
            request, select_native_candidate(request, [bundle.candidate]),
            bundle.execution, bundle.evaluation, bundle.publication,
        )
        if bundle.provenance_sha256 is not None:
            result = replace(result, solver_provenance=tuple(sorted({
                **dict(result.solver_provenance),
                "native_provenance_sha256": bundle.provenance_sha256,
                "native_plan_sha256": plan.plan_sha256,
            }.items())))
        return result

    def validate_replay(
        self, request: SolverRequest, memory: MemorySnapshot, result: SolverResult,
    ) -> SolverResult:
        """Inspect a completed native episode and original artifacts without claiming or launch.

        Controllers use this entry before returning their cached executions. The historical
        approved snapshot is mandatory; current controller memory cannot replace that input.
        """
        plan = self._plan(request, memory)
        try:
            claim = self.ledger.inspect_native_episode_claim(request, plan_sha256=plan.plan_sha256)
            self._assert_ledger()
            if claim is None or claim.status == "started":
                raise NativeRSISolverGatewayError("rsi_native_gateway_recovery_required")
            saved = self._replay(request, plan)
            if saved != result:
                raise NativeRSISolverGatewayError("rsi_native_gateway_replay_result_drift")
            return saved
        except NativeRSISolverGatewayError:
            raise
        except Exception as exc:
            raise NativeRSISolverGatewayError("rsi_native_gateway_replay_evidence_invalid") from exc

    def run(self, request: SolverRequest, memory: MemorySnapshot) -> SolverResult:
        """Claim, execute through an injected provider, map, and durably publish one result.

        A completed result is replayed without invoking the provider. A started claim raises a
        recovery error and never relaunches. This overload is intentionally separate from the
        legacy ``SolverGateway.run(request)`` protocol until the controller can own memory input.
        """
        plan = self._plan(request, memory)
        try:
            claim = self.ledger.inspect_native_episode_claim(request, plan_sha256=plan.plan_sha256)
            self._assert_ledger()
        except RSILearningError as exc:
            raise NativeRSISolverGatewayError("rsi_native_gateway_claim_invalid") from exc
        if claim is not None and claim.status != "started":
            return self._replay(request, plan)
        if claim is not None:
            raise NativeRSISolverGatewayError("rsi_native_gateway_recovery_required")
        try:
            claim = self.ledger.claim_native_episode(request, plan_sha256=plan.plan_sha256)
            self._assert_ledger()
        except RSILearningError as exc:
            if str(exc) == "rsi_native_episode_recovery_required":
                raise NativeRSISolverGatewayError("rsi_native_gateway_recovery_required") from exc
            raise NativeRSISolverGatewayError("rsi_native_gateway_claim_failed") from exc
        if claim.status != "started":
            # Another controller may have published after our initial read. Acquiring an
            # existing terminal claim grants replay authority only, never a second execution.
            return self._replay(request, plan)
        try:
            bundle = self.config.receipt_provider(request, plan)
            self._assert_ledger()
            result = self._map_outcome(request, plan, bundle, expected_claim=claim)
            if isinstance(bundle, NativeRSIFailureEvidence):
                recovery = getattr(self.config.receipt_provider, "recover", None)
                if not callable(recovery):
                    raise NativeRSISolverGatewayError("rsi_native_gateway_failure_reader_required")
                repeated = recovery(request, plan)
                self._assert_ledger()
                if (not isinstance(repeated, NativeRSIFailureEvidence) or
                        repeated.to_dict() != bundle.to_dict() or
                        repeated.provenance_sha256 != bundle.provenance_sha256 or
                        self._map_outcome(request, plan, repeated, expected_claim=claim) != result):
                    raise NativeRSISolverGatewayError("rsi_native_gateway_failure_proof_changed")
            failure_claim = {"expected_claim": claim} if isinstance(bundle, NativeRSIFailureEvidence) else {}
            self.ledger.publish_native_episode_result(
                request, plan_sha256=plan.plan_sha256, result=result, **failure_claim,
            )
            self._assert_ledger()
            return result
        except NativeRSISolverGatewayError:
            raise
        except Exception as exc:
            # The claim remains started. Unknown or incomplete evidence must be reconciled; it
            # is never converted into a terminal result and never retried automatically.
            raise NativeRSISolverGatewayError("rsi_native_gateway_attempt_unknown") from exc


__all__ = [
    "NativeRSIExecutionConfig", "NativeRSIReceiptBundle", "NativeRSISolverGateway",
    "NativeRSISolverGatewayError",
]
