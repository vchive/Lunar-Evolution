"""Explicit single-episode Python producer composition over the native gateway.

The caller owns the original, pre-staged launch context and once-only attestation.
This facade neither stages a new episode nor authenticates an upstream project. It
joins the existing Python input gate, native claims, scheduler, prepared admission
and retained recovery without granting production runtime acceptance.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from .candidate_evaluation_spec import canonical_json
from .python_producer_checkpoint import PythonProducerCheckpointBinding
from .rsi_gateway import SolverRequest, SolverResult
from .rsi_identity import component_fingerprint
from .rsi_learning import MemorySnapshot, RSILearningError
from .rsi_native_gateway import NativeRSIExecutionConfig, NativeRSISolverGateway
from .rsi_native_plan import NativeRSIExecutionPlan
from .rsi_native_scheduler import NativeRSISchedulerProvider, make_native_rsi_scheduler_provider
from .rsi_python_scheduler_inputs import (
    PythonRSISchedulerInputContext,
    PythonRSISchedulerPlanFactory,
)
from .rsi_store import RSILedger


class PythonProducerRSIGatewayError(RSILearningError):
    """Fixed refusals for an explicitly supplied local producer composition."""


def _fail(reason: str) -> NoReturn:
    raise PythonProducerRSIGatewayError("rsi_python_producer_gateway_" + reason)


@dataclass(frozen=True, slots=True)
class PythonProducerRSIExecutionConfig:
    """One independently pinned episode, using the controller's existing ledger.

    A producer id is the caller's label, not proof of project authenticity. The
    Python context carries the original checkpoint and sidecar; it must include
    the existing late handoff supplier and use this ledger for native failures.
    """

    producer_id: str
    ledger: RSILedger
    inputs: PythonRSISchedulerInputContext

    def __post_init__(self) -> None:
        if type(self.producer_id) is not str or self.producer_id not in {"openevolve", "shinka"}:
            _fail("producer_invalid")
        if type(self.ledger) is not RSILedger:
            _fail("ledger_invalid")
        if type(self.inputs) is not PythonRSISchedulerInputContext:
            _fail("inputs_invalid")
        # The existing pure shape/reparse gate must precede nested attribute
        # access; a mutated sidecar must not run caller-supplied properties.
        PythonRSISchedulerPlanFactory(self.inputs)
        native = self.inputs.native_context
        if (self.inputs.producer_sidecar.binding.producer_id != self.producer_id
                or native.intent.producer_id != self.producer_id):
            _fail("producer_binding_mismatch")
        if native.failure_ledger is not self.ledger:
            _fail("failure_ledger_mismatch")
        if native.python_handoff_after_execution is None:
            _fail("handoff_supplier_required")


class PythonProducerRSISolverGateway(NativeRSISolverGateway):
    """Compose a single pre-staged producer attempt and its read-only recovery.

    ``run`` and ``validate_replay`` retain the native memory-aware signatures.
    No new claims, receipt formats, admission rows or recovery policy are added.
    An interrupted attempt remains started/unknown and cannot be relaunched.
    This is an experimental Python API, not the production CLI or a complete
    multi-episode campaign. Every capability claim keeps production false.
    """

    production_admission = False
    single_episode = True

    def __init__(self, config: PythonProducerRSIExecutionConfig) -> None:
        if type(config) is not PythonProducerRSIExecutionConfig:
            _fail("configuration_invalid")
        config.__post_init__()
        self.producer_config = config
        self._original_producer_config = config
        factory = PythonRSISchedulerPlanFactory(config.inputs)
        provider = make_native_rsi_scheduler_provider(config.inputs.native_context)
        execution = NativeRSIExecutionConfig(config.ledger, factory, provider)
        self._original_execution_config = execution
        self._original_wiring = self._wiring(execution)
        super().__init__(execution)

    def _wiring(self, execution: NativeRSIExecutionConfig) -> bytes:
        config = self.producer_config
        config.__post_init__()
        try:
            return canonical_json({
                "protocol": "lunar-python-producer-rsi-gateway-v1",
                "producer_id": config.producer_id,
                "single_episode": True,
                "production_admission": False,
                "code_dependencies": {
                    "native_gateway": component_fingerprint(NativeRSISolverGateway, config={}),
                    "native_configuration": component_fingerprint(NativeRSIExecutionConfig, config={}),
                    "producer_configuration": component_fingerprint(PythonProducerRSIExecutionConfig, config={}),
                    "scheduler": component_fingerprint(NativeRSISchedulerProvider, config={}),
                    "scheduler_factory": component_fingerprint(make_native_rsi_scheduler_provider),
                },
                "plan": execution.plan_factory.rsi_fingerprint_config(),
                "scheduler": execution.receipt_provider.rsi_fingerprint_config(),
            }, maximum=4 * 1024 * 1024)
        except PythonProducerRSIGatewayError:
            raise
        except (ValueError, TypeError, AttributeError, OSError, RecursionError, OverflowError):
            _fail("wiring_invalid")

    def _assert_ledger(self) -> None:
        # Check object association before the parent inspects any provider hook.
        if (self.producer_config is not self._original_producer_config
                or self.config is not self._original_execution_config
                or self.config.ledger is not self.producer_config.ledger):
            _fail("configuration_drift")
        if self._wiring(self.config) != self._original_wiring:
            _fail("wiring_drift")
        super()._assert_ledger()

    def rsi_fingerprint_config(self) -> dict[str, Any]:
        native = super().rsi_fingerprint_config()
        return {
            "protocol": "lunar-python-producer-rsi-gateway-v1",
            "producer_id": self.producer_config.producer_id,
            "single_episode": True,
            "production_admission": False,
            "wiring_sha256": hashlib.sha256(self._original_wiring).hexdigest(),
            "native": native,
        }

    def _plan(self, request: SolverRequest, memory: MemorySnapshot) -> NativeRSIExecutionPlan:
        self._assert_ledger()
        if type(request) is not SolverRequest or request.solver_id != self.producer_config.producer_id:
            _fail("request_producer_mismatch")
        return super()._plan(request, memory)

    def run(self, request: SolverRequest, memory: MemorySnapshot) -> SolverResult:
        """Refuse missing fresh-attempt controller wiring before acquiring a claim.

        Existing started and terminal claims retain the original native recovery
        and replay behavior, including read-only replay without a live controller.
        This preflight inspects a claim but never creates or settles one.
        """
        plan = self._plan(request, memory)
        claim = self.ledger.inspect_native_episode_claim(request, plan_sha256=plan.plan_sha256)
        self._assert_ledger()
        if claim is None:
            controller = self.config.receipt_provider._python_admission_controller
            if controller is None:
                _fail("controller_required")
            self.bind_python_admission_controller(controller)
        return super().run(request, memory)

    def bind_python_admission_controller(self, controller: Any) -> None:
        """Require the exact controller ledger, workspace and original proof.

        The existing scheduler later verifies the owning DRS/BRS scope and pins
        only at the durable prepared boundary. Binding here has no launch effect.
        """
        self._assert_ledger()
        inputs = self.producer_config.inputs
        if (getattr(controller, "ledger", None) is not self.ledger
                or getattr(controller, "gateway", None) is not self):
            _fail("controller_mismatch")
        try:
            workspace = getattr(controller, "producer_workspace", None)
            sidecar = getattr(controller, "producer_sidecar", None)
            if (not isinstance(workspace, (str, Path))
                    or Path(workspace).expanduser().absolute()
                    != Path(inputs.native_context.workspace).expanduser().absolute()):
                _fail("controller_workspace_mismatch")
            proof = PythonProducerCheckpointBinding.from_sidecar(sidecar)
            if proof.to_json() != inputs.original_producer_checkpoint.to_json():
                _fail("controller_proof_mismatch")
        except PythonProducerRSIGatewayError:
            raise
        except (ValueError, TypeError, AttributeError, OSError, RecursionError, OverflowError):
            _fail("controller_proof_invalid")
        super().bind_python_admission_controller(controller)
        self._assert_ledger()


def require_fixture_rsi_cli(solver_execution: object) -> None:
    """Refuse unavailable production CLI before contract, ledger or fixture I/O.

    There is no accepted runtime or safe per-episode launch-config loader yet.
    The explicit native opt-in must therefore never silently select a fixture.
    """
    if type(solver_execution) is not str or solver_execution not in {"fixture", "native-producer"}:
        _fail("cli_execution_invalid")
    if solver_execution == "native-producer":
        _fail("cli_accepted_runtime_required")


__all__ = [
    "PythonProducerRSIExecutionConfig", "PythonProducerRSIGatewayError",
    "PythonProducerRSISolverGateway", "require_fixture_rsi_cli",
]
