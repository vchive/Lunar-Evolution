"""Explicit composition facade for native RSI solver episodes.

This module joins the already validated native control-plane seams.  It intentionally does not
discover launch credentials, run an evaluator, or interpret producer output.  A caller supplies a
plan factory and a receipt provider; the provider must return the four request-bound records from
the same native attempt.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .rsi_gateway import SolverRequest, SolverResult
from .rsi_learning import MemorySnapshot, RSILearningError
from .rsi_native_candidate import (
    NativeCandidateRecord,
    NativeEvaluationReceipt,
    NativeExecutionReceipt,
    NativePublicationReceipt,
    map_native_receipts_to_solver_result,
    select_native_candidate,
)
from .rsi_native_plan import NativeRSIExecutionPlan
from .rsi_store import RSILedger


class NativeRSISolverGatewayError(RSILearningError):
    """Fixed refusal codes for native gateway composition and recovery."""


@dataclass(frozen=True, slots=True)
class NativeRSIReceiptBundle:
    """Same-run candidate and independent execution/evaluation/publication evidence."""

    candidate: NativeCandidateRecord
    execution: NativeExecutionReceipt
    evaluation: NativeEvaluationReceipt
    publication: NativePublicationReceipt


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
    receipt_provider: Callable[[SolverRequest, NativeRSIExecutionPlan], NativeRSIReceiptBundle]

    def __post_init__(self) -> None:
        if not isinstance(self.ledger, RSILedger):
            raise NativeRSISolverGatewayError("rsi_native_gateway_ledger_invalid")
        if not callable(self.plan_factory) or not callable(self.receipt_provider):
            raise NativeRSISolverGatewayError("rsi_native_gateway_factory_invalid")


class NativeRSISolverGateway:
    """Durable native RSI gateway with strict claim, replay and receipt binding."""

    def __init__(self, config: NativeRSIExecutionConfig) -> None:
        if not isinstance(config, NativeRSIExecutionConfig):
            raise NativeRSISolverGatewayError("rsi_native_gateway_configuration_invalid")
        self.config = config

    @property
    def ledger(self) -> RSILedger:
        return self.config.ledger

    def _plan(self, request: SolverRequest, memory: MemorySnapshot) -> NativeRSIExecutionPlan:
        if not isinstance(request, SolverRequest) or not isinstance(memory, MemorySnapshot):
            raise NativeRSISolverGatewayError("rsi_native_gateway_input_invalid")
        if memory.digest() != request.memory_snapshot_sha256:
            raise NativeRSISolverGatewayError("rsi_native_gateway_memory_binding_mismatch")
        try:
            plan = self.config.plan_factory(request, memory)
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

    def _replay(self, request: SolverRequest) -> SolverResult:
        saved = self.ledger.episode_result(request.episode_id)
        if saved is None or saved[0] != request:
            raise NativeRSISolverGatewayError("rsi_native_gateway_replay_missing")
        return saved[1]

    def run(self, request: SolverRequest, memory: MemorySnapshot) -> SolverResult:
        """Claim, execute through an injected provider, map, and durably publish one result.

        A completed result is replayed without invoking the provider. A started claim raises a
        recovery error and never relaunches. This overload is intentionally separate from the
        legacy ``SolverGateway.run(request)`` protocol until the controller can own memory input.
        """
        plan = self._plan(request, memory)
        try:
            claim = self.ledger.inspect_native_episode_claim(request, plan_sha256=plan.plan_sha256)
        except RSILearningError as exc:
            raise NativeRSISolverGatewayError("rsi_native_gateway_claim_invalid") from exc
        if claim is not None and claim.status != "started":
            return self._replay(request)
        if claim is not None:
            raise NativeRSISolverGatewayError("rsi_native_gateway_recovery_required")
        try:
            claim = self.ledger.claim_native_episode(request, plan_sha256=plan.plan_sha256)
        except RSILearningError as exc:
            if str(exc) == "rsi_native_episode_recovery_required":
                raise NativeRSISolverGatewayError("rsi_native_gateway_recovery_required") from exc
            raise NativeRSISolverGatewayError("rsi_native_gateway_claim_failed") from exc
        if claim.status != "started":
            # Another controller may have published after our initial read. Acquiring an
            # existing terminal claim grants replay authority only, never a second execution.
            return self._replay(request)
        try:
            bundle = self.config.receipt_provider(request, plan)
            if not isinstance(bundle, NativeRSIReceiptBundle):
                raise NativeRSISolverGatewayError("rsi_native_gateway_receipts_invalid")
            selection = select_native_candidate(request, [bundle.candidate])
            result = map_native_receipts_to_solver_result(
                request, selection, bundle.execution, bundle.evaluation, bundle.publication,
            )
            self.ledger.publish_native_episode_result(
                request, plan_sha256=plan.plan_sha256, result=result,
            )
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
