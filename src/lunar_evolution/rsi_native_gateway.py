"""Explicit composition facade for native RSI solver episodes.

This module joins the already validated native control-plane seams.  It intentionally does not
discover launch credentials, run an evaluator, or interpret producer output.  A caller supplies a
plan factory and a receipt provider; the provider must return the four request-bound records from
the same native attempt.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

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
    provenance_sha256: str | None = None

    def __post_init__(self) -> None:
        if self.provenance_sha256 is not None and (
            type(self.provenance_sha256) is not str or len(self.provenance_sha256) != 64
            or any(char not in "0123456789abcdef" for char in self.provenance_sha256)
        ):
            raise NativeRSISolverGatewayError("rsi_native_gateway_provenance_invalid")


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

    # Explicit capability consumed by ``PracticeEpisodeRunner``. Keeping this opt-in rather
    # than inspecting a callable signature preserves the legacy one-argument SolverGateway
    # protocol for all existing adapters.
    requires_memory_snapshot = True

    def __init__(self, config: NativeRSIExecutionConfig) -> None:
        if not isinstance(config, NativeRSIExecutionConfig):
            raise NativeRSISolverGatewayError("rsi_native_gateway_configuration_invalid")
        self.config = config

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
            identity = self.ledger.database.stat()
            plan_fingerprint = component_fingerprint(self.config.plan_factory)
            receipt_fingerprint = component_fingerprint(self.config.receipt_provider)
        except (OSError, RSIIdentityError) as exc:
            raise NativeRSISolverGatewayError("rsi_native_gateway_fingerprint_invalid") from exc
        return {
            "protocol": "lunar-native-rsi-gateway-v1",
            "ledger": {
                "database": str(self.ledger.database),
                "device": identity.st_dev,
                "inode": identity.st_ino,
            },
            "plan_factory_sha256": plan_fingerprint,
            "receipt_provider_sha256": receipt_fingerprint,
        }

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

    def _replay(self, request: SolverRequest, plan: NativeRSIExecutionPlan) -> SolverResult:
        saved = self.ledger.episode_result(request.episode_id)
        if saved is None or saved[0] != request:
            raise NativeRSISolverGatewayError("rsi_native_gateway_replay_missing")
        recovery = getattr(self.config.receipt_provider, "recover", None)
        if callable(recovery):
            try:
                bundle = recovery(request, plan)
                if not isinstance(bundle, NativeRSIReceiptBundle):
                    raise NativeRSISolverGatewayError("rsi_native_gateway_receipts_invalid")
                result = self._map_bundle(request, plan, bundle)
                if result != saved[1]:
                    raise NativeRSISolverGatewayError("rsi_native_gateway_replay_result_drift")
            except Exception as exc:
                raise NativeRSISolverGatewayError("rsi_native_gateway_replay_evidence_invalid") from exc
        return saved[1]

    @staticmethod
    def _map_bundle(
        request: SolverRequest, plan: NativeRSIExecutionPlan, bundle: NativeRSIReceiptBundle,
    ) -> SolverResult:
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
        except RSILearningError as exc:
            raise NativeRSISolverGatewayError("rsi_native_gateway_claim_invalid") from exc
        if claim is not None and claim.status != "started":
            return self._replay(request, plan)
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
            return self._replay(request, plan)
        try:
            bundle = self.config.receipt_provider(request, plan)
            if not isinstance(bundle, NativeRSIReceiptBundle):
                raise NativeRSISolverGatewayError("rsi_native_gateway_receipts_invalid")
            result = self._map_bundle(request, plan, bundle)
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
