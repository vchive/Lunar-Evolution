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
    _request_memory,
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

    def bind_python_admission_child_controller(
        self, controller: Any, *, expected_checkpoint_sha256: str,
    ) -> None:
        """Bind a resolved child only inside its original DRS owner scope.

        This separate entry point preserves the ordinary binder's exact root
        gateway check. Binding does not claim or adopt a started attempt; only
        the adjacent controller continuation can execute a fresh child.
        """
        from .rsi_controller import RSILearningController

        self._assert_ledger()
        if type(controller) is not RSILearningController or controller.ledger is not self.ledger:
            _fail("child_controller_mismatch")
        run_id = self.producer_config.inputs.original_producer_checkpoint.run_id
        episode_id = self.producer_config.inputs.native_context.intent.task_id
        if not self.ledger.controller_lock_held(run_id):
            _fail("child_controller_lock_required")
        try:
            state, head = controller._python_admission_active_flow(run_id, episode_id)
            if state.get("mode") != "drs" or head != expected_checkpoint_sha256:
                _fail("child_controller_checkpoint_conflict")
            identity = state["producer_episode_staging"][episode_id]["identity"]
            request = SolverRequest.from_dict(identity["intent"]["request"])
            memory = MemorySnapshot.from_dict(identity["memory"])
            expected = resolve_python_producer_episode_gateway(
                controller, request, memory, expected_checkpoint_sha256=expected_checkpoint_sha256,
            )
            if (expected is controller.gateway
                    or expected.rsi_fingerprint_config() != self.rsi_fingerprint_config()):
                _fail("child_controller_context_mismatch")
            # Do not route this through the public root-only producer binder.
            # The original native provider binder still enforces one-way identity.
            controller._python_admission_active_flow(run_id, episode_id)
            NativeRSISolverGateway.bind_python_admission_controller(self, controller)
            self._assert_ledger()
            controller._python_admission_active_flow(run_id, episode_id)
        except PythonProducerRSIGatewayError:
            raise
        except (AttributeError, KeyError, IndexError, TypeError, ValueError, OSError, RSILearningError) as exc:
            raise PythonProducerRSIGatewayError("rsi_python_producer_gateway_child_controller_evidence_invalid") from exc


def resolve_python_producer_episode_gateway(
    controller: Any,
    request: SolverRequest,
    memory: MemorySnapshot,
    *,
    expected_checkpoint_sha256: str | None = None,
) -> Any:
    """Select a ready child's gateway for explicit execution or read-only recovery.

    Legacy controllers retain their original gateway. The opt-in path rereads
    retained root and child evidence, with the request's historical memory, and
    never rotates the controller's root or attaches a live provider controller.
    Started claims remain observations for the native recovery gate.
    """
    flag = getattr(controller, "producer_child_execution", False)
    if flag is False:
        if getattr(controller, "_original_producer_child_execution", False) is not False:
            _fail("episode_original_mode_mismatch")
        return controller.gateway
    from .rsi_controller import RSILearningController
    from .rsi_python_episode_inputs import resolve_python_rsi_episode_input_context

    if flag is not True or type(controller) is not RSILearningController:
        _fail("episode_controller_invalid")
    gateway = controller.gateway
    ledger = controller.ledger
    if (type(gateway) is not PythonProducerRSISolverGateway
            or gateway is not getattr(controller, "_original_producer_child_gateway", None)
            or type(ledger) is not RSILedger or gateway.ledger is not ledger):
        _fail("episode_root_gateway_mismatch")
    if controller.producer_stager is None or controller.producer_sidecar is None:
        _fail("episode_stager_required")
    if expected_checkpoint_sha256 is not None and (
        type(expected_checkpoint_sha256) is not str or len(expected_checkpoint_sha256) != 64
        or any(char not in "0123456789abcdef" for char in expected_checkpoint_sha256)
        or expected_checkpoint_sha256 == "0" * 64
    ):
        _fail("episode_checkpoint_invalid")
    try:
        # The existing pure gate precedes database/file reads and DTO serializers.
        request, memory = _request_memory(request, memory)
        gateway._assert_ledger()
        root_context = gateway.producer_config.inputs
        proof = PythonProducerCheckpointBinding.from_sidecar(controller.producer_sidecar)
        if (proof.to_json() != root_context.original_producer_checkpoint.to_json()
                or controller.producer_workspace is None
                or Path(controller.producer_workspace).expanduser().absolute()
                != Path(root_context.native_context.workspace).expanduser().absolute()):
            _fail("episode_root_context_mismatch")
        run_id = proof.run_id
        with ledger.read_only_observations():
            records = ledger.history(run_id)
            if (not records or records[0].kind != "run"
                    or records[0].payload.get("producer_child_execution") is not True):
                _fail("episode_original_mode_mismatch")
            checkpoint = ledger.controller_checkpoint(run_id)
            if checkpoint is None:
                _fail("episode_checkpoint_missing")
            head, state = checkpoint
            if expected_checkpoint_sha256 is not None and head != expected_checkpoint_sha256:
                _fail("episode_checkpoint_conflict")
            if (state.get("producer_child_execution") is not True
                    or state.get("run_id") != run_id or state.get("mode") != "drs"):
                _fail("episode_original_mode_mismatch")
            # The controller owns the complete durable policy/history check.
            controller._validate_producer_checkpoint(run_id, state)
            historical = controller._native_historical_memory(run_id, request)
            _request_memory(request, historical)
            if historical.to_dict() != memory.to_dict():
                _fail("episode_historical_memory_mismatch")
            context = resolve_python_rsi_episode_input_context(
                root_context, ledger, request, historical, expected_checkpoint_sha256=head,
            )
            child = PythonProducerRSISolverGateway(PythonProducerRSIExecutionConfig(
                gateway.producer_config.producer_id, ledger, context,
            ))
            child._plan(request, historical)
            gateway._assert_ledger()
            if (controller.gateway is not gateway or controller.ledger is not ledger
                    or ledger.controller_checkpoint(run_id) != checkpoint):
                _fail("episode_evidence_drift")
            controller._validate_producer_checkpoint(run_id, state)
            return child
    except PythonProducerRSIGatewayError:
        raise
    except (AttributeError, KeyError, IndexError, TypeError, ValueError, OSError, RSILearningError) as exc:
        raise PythonProducerRSIGatewayError("rsi_python_producer_gateway_episode_evidence_invalid") from exc


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
    "resolve_python_producer_episode_gateway",
]
