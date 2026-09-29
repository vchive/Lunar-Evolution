"""Explicit WorkerService bridge for one lifecycle-enabled automatic solve.

The bridge is deliberately opt-in.  It admits one native Run through the durable binding
record, then delegates to :func:`continue_automatic_solve`; WorkerService remains an outer
observation and cancellation handle, never a second solver or delivery authority.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

from .agents import AgentAdapter, AgentRequest, AgentResult, ProcessObserver
from .automatic_solve_continuation import (
    AutomaticSolveContinuation,
    continue_automatic_solve,
)
from .automatic_solve_lifecycle import SolveExecutionControl
from .automatic_solve_worker_binding import (
    AutomaticSolveWorkerBinding,
    AutomaticSolveWorkerBindingState,
    AutomaticSolveWorkerResultReference,
)
from .models import Worker, WorkerAttempt


class AutomaticSolveAwaitingInput(RuntimeError):
    """The native Run is suspended on its persisted user-input contract."""

    worker_stop_reason = "awaiting_input"


class AutomaticSolveRecoveryRequired(RuntimeError):
    """Native evidence is incomplete and must be reconciled before another execution."""

    worker_stop_reason = "recovery_required"


def _digest(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _terminal_payload(controller: Any, run_id: str, payload: dict[str, object]) -> dict[str, object]:
    """Keep a result reference bounded and independent of arbitrary native output text."""
    events = controller.store.list_events(run_id)
    child_id = None
    contract_digest = None
    for event in events:
        if event.get("type") == "evolution_linked" and isinstance(event.get("payload"), dict):
            link = event["payload"]
            child_id = link.get("evolution_run_id")
            contract_digest = link.get("contract_sha256")
    selected = {
        "run_id": run_id,
        "status": payload.get("status"),
        "child_run_id": child_id,
        "contract_digest": contract_digest,
        "payload_sha256": _digest(payload),
    }
    return selected


class AutomaticSolveWorkerAdapter:
    """Fresh per-attempt adapter for an already captured native continuation."""

    name = "automatic-solve"
    roles = frozenset({"automatic-solve", "solver", "worker"})
    capabilities = frozenset({"native-automatic-solve"})

    def __init__(self, config: Any, controller: Any, continuation: AutomaticSolveContinuation) -> None:
        if not isinstance(continuation, AutomaticSolveContinuation):
            raise TypeError("continuation must be AutomaticSolveContinuation")
        self.config = config
        self.controller = controller
        self.continuation = continuation
        self._binding: AutomaticSolveWorkerBinding | None = None
        self._observer: ProcessObserver | None = None
        self._guard = None
        self._cancelled = False

    def admit(self, worker: Worker, attempt: WorkerAttempt, service_owner_id: str) -> None:
        """Create the generation-zero binding before WorkerService releases execution."""
        if self._binding is not None:
            raise ValueError("automatic solve adapter is already admitted")
        binding = AutomaticSolveWorkerBinding(
            binding_id="automatic-binding-" + uuid.uuid4().hex,
            owner_id=worker.owner_id,
            run_id=self.continuation.run_id,
            workspace_identity=self.continuation.workspace,
            worker_id=worker.id,
            worker_attempt_id=attempt.id,
            service_owner_id=service_owner_id,
            lifecycle_digest=self.continuation.request_sha256,
            runtime_fingerprint=self.continuation.runtime_fingerprint,
            budget_policy=self.continuation.request,
        )
        self._binding = self.controller.store.create_automatic_solve_worker_binding(binding)

    def set_process_observer(self, observer: ProcessObserver | None) -> None:
        if observer is not None and not callable(observer):
            raise TypeError("process observer must be callable")
        self._observer = observer

    def set_continuation_guard(self, guard) -> None:
        if guard is not None and not callable(guard):
            raise TypeError("continuation guard must be callable")
        self._guard = guard

    def set_process_released(self, _callback) -> None:
        # Native continuation installs its own observer at the controller boundary.  The outer
        # adapter has no private subprocess and therefore has nothing else to release.
        return None

    def process_info(self) -> tuple[int | None, int | None]:
        return None, None

    def cancel(self) -> None:
        self._cancelled = True
        run = self.controller.store.get_run(self.continuation.run_id)
        if run is not None and run.status.value not in {"succeeded", "failed", "cancelled"}:
            self.controller.cancel(run.id)

    def _check(self) -> None:
        if self._cancelled:
            raise RuntimeError("automatic solve worker cancelled")
        if self._guard is not None:
            self._guard()

    def _control(self, request: AgentRequest) -> SolveExecutionControl:
        persisted = self.continuation.request.get("solve_wall_timeout")
        timeout = request.timeout if request.timeout is not None else persisted
        if timeout is None:
            timeout = self.continuation.request.get("timeout", 900.0)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError("automatic solve worker timeout is invalid")
        return SolveExecutionControl(float(timeout))

    def _finish(self, payload: dict[str, object]) -> AgentResult:
        binding = self._binding
        if binding is None:
            raise ValueError("automatic solve worker was not admitted")
        run = self.controller.store.get_run(binding.run_id)
        status = payload.get("status")
        if run is None or status not in {"succeeded", "failed", "cancelled"}:
            raise AutomaticSolveRecoveryRequired("native automatic solve remains unresolved")
        selected = _terminal_payload(self.controller, binding.run_id, payload)
        contract_digest = selected.get("contract_digest")
        child_run_id = selected.get("child_run_id")
        observed = self.controller.store.compare_and_swap_automatic_solve_worker_binding(
            binding,
            state=AutomaticSolveWorkerBindingState.ACTIVE,
            contract_digest=contract_digest if isinstance(contract_digest, str) else None,
            child_run_id=child_run_id if isinstance(child_run_id, str) else None,
        )
        if observed is None:
            raise AutomaticSolveRecoveryRequired("automatic solve binding was superseded")
        self._binding = observed
        reference = AutomaticSolveWorkerResultReference(
            binding_id=observed.binding_id,
            generation=observed.generation,
            run_id=observed.run_id,
            worker_attempt_id=observed.worker_attempt_id,
            outcome=str(status),
            reference=selected,
        )
        retained = self.controller.store.create_automatic_solve_worker_result_reference(observed, reference)
        if retained is None:
            raise AutomaticSolveRecoveryRequired("automatic solve result reference lost its admission race")
        text = json.dumps(selected, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return AgentResult(
            adapter_name=self.name,
            role="automatic-solve",
            status="succeeded" if status == "succeeded" else "failed" if status == "failed" else "cancelled",
            text=text,
            metadata={"binding_id": retained.binding_id, "generation": retained.generation,
                      "result_ref_sha256": retained.sha256},
            error=None if status == "succeeded" else str(status),
        )

    def run(self, request: AgentRequest) -> AgentResult:
        self._check()
        binding = self._binding
        if binding is None:
            raise ValueError("automatic solve worker invocation requires explicit admission")
        active = self.controller.store.compare_and_swap_automatic_solve_worker_binding(
            binding, state=AutomaticSolveWorkerBindingState.ACTIVE,
        )
        if active is None:
            raise AutomaticSolveRecoveryRequired("automatic solve binding admission was lost")
        self._binding = active
        try:
            payload = continue_automatic_solve(
                self.config,
                self.controller,
                self.continuation,
                execution_control=self._control(request),
            )
            if not isinstance(payload, dict):
                raise AutomaticSolveRecoveryRequired("native continuation returned invalid evidence")
            if payload.get("status") == "awaiting_input":
                self.controller.store.compare_and_swap_automatic_solve_worker_binding(
                    active, state=AutomaticSolveWorkerBindingState.AWAITING_INPUT,
                    observation_reason="awaiting_input", stop_reason="awaiting_input",
                )
                raise AutomaticSolveAwaitingInput("native automatic solve awaits input")
            return self._finish(payload)
        except (AutomaticSolveAwaitingInput, AutomaticSolveRecoveryRequired):
            raise
        except Exception as exc:
            current = self.controller.store.get_run(binding.run_id)
            if current is not None and current.status.value in {"succeeded", "failed", "cancelled"}:
                return self._finish({"status": current.status.value})
            try:
                self.controller.store.compare_and_swap_automatic_solve_worker_binding(
                    active, state=AutomaticSolveWorkerBindingState.RECOVERY_REQUIRED,
                    observation_reason="continuation_error", stop_reason="recovery_required",
                )
            except Exception:
                pass
            raise AutomaticSolveRecoveryRequired("native automatic solve requires recovery") from exc


class AutomaticSolveWorkerBridge:
    """Small explicit API; generic WorkerService resume cannot bypass native bindings."""

    def __init__(self, config: Any, controller: Any) -> None:
        self.config = config
        self.controller = controller

    def dispatch(self, owner_id: str, continuation: AutomaticSolveContinuation, *, timeout: float | None = None):
        if owner_id != continuation.run_id:
            raise PermissionError("automatic solve owner must be the native Run owner")
        adapter = AutomaticSolveWorkerAdapter(self.config, self.controller, continuation)
        return self.controller.workers.dispatch_adapter(
            owner_id,
            adapter,
            role="automatic-solve",
            prompt="continue persisted automatic solve",
            description="native automatic solve bridge",
            required_capabilities=("native-automatic-solve",),
            timeout=timeout,
            before_start=lambda worker, attempt: adapter.admit(
                worker, attempt, self.controller.workers.service_owner_id,
            ),
        )

    def read(self, owner_id: str, worker_id: str):
        worker = self.controller.store.get_worker(worker_id)
        if worker is None or worker.owner_id != owner_id:
            raise PermissionError("automatic solve worker is not owned by caller")
        bindings = self.controller.store.list_automatic_solve_worker_bindings(owner_id)
        binding = next((item for item in bindings if item.worker_id == worker_id), None)
        if binding is None:
            raise ValueError("automatic solve worker binding is missing")
        return self.controller.store.get_automatic_solve_worker_result_reference(
            binding.binding_id, owner_id=owner_id, generation=binding.generation,
        )


__all__ = [
    "AutomaticSolveAwaitingInput", "AutomaticSolveRecoveryRequired",
    "AutomaticSolveWorkerAdapter", "AutomaticSolveWorkerBridge",
]
