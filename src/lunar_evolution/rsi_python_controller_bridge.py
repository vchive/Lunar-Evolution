"""Read-only controller to staged Python child scheduler composition."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from .python_producer_checkpoint import PythonProducerCheckpointBinding
from .rsi_gateway import SolverRequest
from .rsi_learning import MemorySnapshot, RSILearningError
from .rsi_native_plan import NativeRSIExecutionPlan
from .rsi_producer_gateway import (
    PythonProducerRSIExecutionConfig,
    PythonProducerRSIGatewayError,
    PythonProducerRSISolverGateway,
)
from .rsi_python_episode_inputs import resolve_python_rsi_episode_input_context
from .rsi_python_scheduler_inputs import PythonRSISchedulerInputContext
from .rsi_store import RSILedger


class PythonProducerControllerBridgeError(RSILearningError):
    """Fixed refusal codes for read-only controller child composition."""


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


__all__ = [
    "PythonProducerControllerBridgeError",
    "PythonProducerControllerChildPreview",
    "resolve_python_producer_controller_child_preview",
]
