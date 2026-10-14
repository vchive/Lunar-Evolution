"""Controller to staged Python child observation and explicit claim composition."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from .python_producer_checkpoint import PythonProducerCheckpointBinding
from .rsi_gateway import SolverRequest
from .rsi_learning import MemorySnapshot, RSILearningError
from .rsi_native_plan import NativeRSIExecutionPlan
from .rsi_native_scheduler import NativeRSISchedulerProvider
from .rsi_producer_gateway import (
    PythonProducerRSIExecutionConfig,
    PythonProducerRSIGatewayError,
    PythonProducerRSISolverGateway,
)
from .rsi_python_admission import validate_rsi_python_admission_shapes
from .rsi_python_episode_inputs import resolve_python_rsi_episode_input_context
from .rsi_python_scheduler_inputs import (
    PythonRSISchedulerInputContext,
    PythonRSISchedulerPlanFactory,
    validate_python_rsi_scheduler_inputs,
)
from .rsi_store import NativeEpisodeClaim, RSILedger


class PythonProducerControllerBridgeError(RSILearningError):
    """Fixed refusal codes for explicit controller child composition."""


def _fail(reason: str) -> NoReturn:
    raise PythonProducerControllerBridgeError("rsi_python_controller_bridge_" + reason)


@dataclass(frozen=True, slots=True)
class PythonProducerControllerChildPreview:
    """Detached child inputs and plan; no object here grants launch authority."""

    run_id: str
    episode_id: str
    checkpoint_sha256: str
    producer_id: str
    context: PythonRSISchedulerInputContext
    plan: NativeRSIExecutionPlan

    def __post_init__(self) -> None:
        if type(self.run_id) is not str or not self.run_id:
            _fail("run_id_invalid")
        if type(self.episode_id) is not str or not self.episode_id:
            _fail("episode_id_invalid")
        if (type(self.checkpoint_sha256) is not str or len(self.checkpoint_sha256) != 64
                or any(char not in "0123456789abcdef" for char in self.checkpoint_sha256)):
            _fail("checkpoint_invalid")
        if type(self.producer_id) is not str or self.producer_id not in {"openevolve", "shinka"}:
            _fail("producer_invalid")
        if type(self.context) is not PythonRSISchedulerInputContext:
            _fail("context_invalid")
        if type(self.plan) is not NativeRSIExecutionPlan:
            _fail("plan_invalid")


def _path(value: object) -> Path:
    if not isinstance(value, (str, Path)):
        _fail("workspace_invalid")
    try:
        return Path(value).expanduser().absolute()
    except (OSError, TypeError, ValueError) as exc:
        raise PythonProducerControllerBridgeError(
            "rsi_python_controller_bridge_workspace_invalid",
        ) from exc


def resolve_python_producer_controller_child_preview(
    controller: Any,
    *,
    run_id: str,
    episode_id: str,
    request: SolverRequest,
    memory: MemorySnapshot,
    expected_checkpoint_sha256: str,
) -> PythonProducerControllerChildPreview:
    """Join one ready DRS child to its read-only scheduler plan.

    The controller lock is deliberately required rather than acquired here. This keeps
    the bridge from creating lock files or silently widening a caller's mutation scope;
    controller dispatch remains the owner of that scope.
    """
    from .rsi_controller import RSILearningController

    if type(controller) is not RSILearningController:
        _fail("controller_invalid")
    if type(run_id) is not str or not run_id:
        _fail("run_id_invalid")
    if type(episode_id) is not str or not episode_id:
        _fail("episode_id_invalid")
    if type(request) is not SolverRequest or type(memory) is not MemorySnapshot:
        _fail("request_memory_invalid")
    if type(controller.ledger) is not RSILedger:
        _fail("ledger_invalid")
    ledger = controller.ledger
    if not ledger.controller_lock_held(run_id):
        _fail("controller_lock_required")
    if (type(expected_checkpoint_sha256) is not str or len(expected_checkpoint_sha256) != 64
            or any(char not in "0123456789abcdef" for char in expected_checkpoint_sha256)
            or expected_checkpoint_sha256 == "0" * 64):
        _fail("checkpoint_invalid")
    gateway = controller.gateway
    if type(gateway) is not PythonProducerRSISolverGateway:
        _fail("gateway_invalid")
    if gateway.ledger is not ledger:
        _fail("gateway_ledger_mismatch")
    if controller.producer_stager is None or controller.producer_sidecar is None:
        _fail("producer_stager_required")
    try:
        gateway._assert_ledger()
        root_context = gateway.producer_config.inputs
        root_proof = PythonProducerCheckpointBinding.from_sidecar(controller.producer_sidecar)
        if (root_proof.to_json() != root_context.original_producer_checkpoint.to_json()
                or _path(controller.producer_workspace) != _path(root_context.native_context.workspace)):
            _fail("root_context_mismatch")
        with ledger.read_only_observations():
            checkpoint = ledger.controller_checkpoint(run_id)
            if checkpoint is None or checkpoint[0] != expected_checkpoint_sha256:
                _fail("checkpoint_conflict")
            state = checkpoint[1]
            if state.get("mode") != "drs" or state.get("run_id") != run_id:
                _fail("mode_invalid")
            if state.get("current_episode_id") != episode_id:
                _fail("episode_owner_mismatch")
            entry = state.get("producer_episode_staging", {}).get(episode_id)
            if type(entry) is not dict or entry.get("state") != "ready":
                _fail("child_not_ready")
            ready = entry.get("ready")
            if type(ready) is not dict or type(ready.get("plan")) is not dict:
                _fail("ready_invalid")
            controller.producer_stager.validate_state(controller, state)
            controller._validate_producer_checkpoint(run_id, state)
            context = resolve_python_rsi_episode_input_context(
                root_context, ledger, request, memory,
                expected_checkpoint_sha256=expected_checkpoint_sha256,
            )
            config = PythonProducerRSIExecutionConfig(
                context.producer_sidecar.binding.producer_id, ledger, context,
            )
            child_gateway = PythonProducerRSISolverGateway(config)
            plan = child_gateway._plan(request, memory)
            if plan.to_dict() != ready["plan"]:
                _fail("ready_plan_drift")
            # Preserve the controller's existing recovery gate and its stable public refusal
            # code before asking the scheduler to perform its deeper input/deadline checks.
            if ledger.inspect_native_episode_claim(request, plan_sha256=plan.plan_sha256) is not None:
                _fail("episode_claim_exists")
            provider = child_gateway.config.receipt_provider
            if type(provider) is not NativeRSISchedulerProvider:
                _fail("scheduler_provider_invalid")
            # Bind the immutable child preview to the actual scheduler/native-claim preflight.
            # This only rereads sealed inputs and the controller ledger; it never creates a
            # claim, consumes an attestation, launches a process, or invokes a producer.
            provider.validate_preclaim(request, plan, claim_ledger=ledger)
            latest = ledger.controller_checkpoint(run_id)
            if latest is None or latest[0] != expected_checkpoint_sha256 or latest[1] != state:
                _fail("checkpoint_drift")
            if ledger.get_episode(episode_id) is not None:
                _fail("episode_already_started")
            if ledger.episode_result(episode_id) is not None:
                _fail("episode_already_terminal")
            if ledger.inspect_native_episode_claim(request, plan_sha256=plan.plan_sha256) is not None:
                _fail("episode_claim_exists")
            return PythonProducerControllerChildPreview(
                run_id, episode_id, expected_checkpoint_sha256,
                config.producer_id, context, plan,
            )
    except PythonProducerControllerBridgeError:
        raise
    except PythonProducerRSIGatewayError as exc:
        raise PythonProducerControllerBridgeError("gateway_plan_invalid") from exc
    except (AttributeError, KeyError, IndexError, TypeError, ValueError, OSError, RSILearningError) as exc:
        raise PythonProducerControllerBridgeError("evidence_invalid") from exc


def claim_python_producer_controller_child(
    controller: Any,
    preview: PythonProducerControllerChildPreview,
    *,
    request: SolverRequest,
    memory: MemorySnapshot,
) -> NativeEpisodeClaim:
    """Explicitly consume a ready preview into the existing once-only native claim.

    The caller must hold the original controller lock. This experimental API is never
    called by default dispatch or resume and does not execute the producer. The preview
    is only a comparison pin: fresh child proof and launch inputs are resolved under
    the lock, and its execution hooks are never adopted. The checkpoint CAS and claim
    insert share the existing ledger transaction. Any post-claim uncertainty retains
    the started claim for recovery; it never rolls back or renews an attempt.
    """
    from .rsi_controller import RSILearningController

    if type(controller) is not RSILearningController:
        _fail("controller_invalid")
    if type(controller.ledger) is not RSILedger:
        _fail("ledger_invalid")
    if type(preview) is not PythonProducerControllerChildPreview:
        _fail("preview_invalid")
    preview.__post_init__()
    ledger = controller.ledger
    if not ledger.controller_lock_held(preview.run_id):
        _fail("controller_lock_required")
    try:
        # Reuse the pure admission shape gate before any plan serializer or nested DTO
        # comparison. A caller-modified preview cannot run serializer/property hooks.
        validate_rsi_python_admission_shapes(
            preview.plan, dto_types=(NativeRSIExecutionPlan, SolverRequest),
        )
        supplied_plan = NativeRSIExecutionPlan.from_dict(preview.plan.to_dict())
        supplied_context = PythonRSISchedulerPlanFactory(preview.context).rsi_fingerprint_config()
        current = resolve_python_producer_controller_child_preview(
            controller, run_id=preview.run_id, episode_id=preview.episode_id,
            request=request, memory=memory, expected_checkpoint_sha256=preview.checkpoint_sha256,
        )
        if (preview.producer_id != current.producer_id
                or supplied_plan.to_dict() != current.plan.to_dict()
                or supplied_context != PythonRSISchedulerPlanFactory(
                    current.context,
                ).rsi_fingerprint_config()):
            _fail("preview_drift")
        # Keep all observations read-only until this single atomic claim operation.
        # The rebuilt plan retains a detached, parsed request. Never let a caller alias
        # provide different request bytes to the ledger after the input gate completed.
        claim = ledger.claim_native_episode(
            current.plan.request, plan_sha256=current.plan.plan_sha256,
            controller_run_id=preview.run_id,
            expected_controller_checkpoint_sha256=preview.checkpoint_sha256,
        )
        with ledger.read_only_observations():
            if not ledger.controller_lock_held(preview.run_id):
                _fail("controller_lock_required")
            controller.gateway._assert_ledger()
            checkpoint = ledger.controller_checkpoint(preview.run_id)
            if checkpoint is None or checkpoint[0] != preview.checkpoint_sha256:
                _fail("checkpoint_drift")
            controller._validate_producer_checkpoint(preview.run_id, checkpoint[1])
            validate_python_rsi_scheduler_inputs(
                current.context, request, memory, require_unexpired=True,
            )
            if ledger.inspect_native_episode_claim(
                request, plan_sha256=current.plan.plan_sha256,
            ) != claim or claim.status != "started":
                _fail("claim_drift")
            if ledger.get_episode(preview.episode_id) is not None:
                _fail("episode_already_started")
            controller.gateway._assert_ledger()
            latest = ledger.controller_checkpoint(preview.run_id)
            if latest != checkpoint:
                _fail("checkpoint_drift")
        return claim
    except PythonProducerControllerBridgeError:
        raise
    except (AttributeError, KeyError, IndexError, TypeError, ValueError, OSError, RSILearningError) as exc:
        raise PythonProducerControllerBridgeError("rsi_python_controller_bridge_claim_refused") from exc


__all__ = [
    "PythonProducerControllerBridgeError",
    "PythonProducerControllerChildPreview",
    "claim_python_producer_controller_child",
    "resolve_python_producer_controller_child_preview",
]
