"""Explicit WorkerService bridge for one lifecycle-enabled automatic solve.

The bridge is deliberately opt-in.  It admits one native Run through the durable binding
record, then delegates to :func:`continue_automatic_solve`; WorkerService remains an outer
observation and cancellation handle, never a second solver or delivery authority.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import replace
from typing import Any

from .agents import AgentRequest, AgentResult, ProcessObserver
from .automatic_solve_continuation import (
    AutomaticSolveContinuation,
    continue_automatic_solve,
)
from .automatic_solve_lifecycle import SolveExecutionControl, own_automatic_solve
from .automatic_solve_worker_binding import (
    AutomaticSolveWorkerBinding,
    AutomaticSolveWorkerBindingState,
    AutomaticSolveWorkerResultReference,
)
from .automatic_solve_worker_result import capture_native_result, validate_native_result
from .models import Worker, WorkerAttempt
from .worker_ownership import WorkerOwnerLock


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
        self._released = None
        self._guard = None
        self._cancelled = False
        self._worker_service = None
        self._worker_owner_id: str | None = None
        self._worker_id: str | None = None
        self._worker_attempt_id: str | None = None

    def admit(self, worker: Worker, attempt: WorkerAttempt, service_owner_id: str, *, prior=None, timeout=None) -> None:
        """Create the generation-zero binding before WorkerService releases execution."""
        if self._binding is not None:
            raise ValueError("automatic solve adapter is already admitted")
        budget_policy = {
            "native_request": self.continuation.request,
            "worker_active_timeout": timeout,
            "manifest_sha256": self.continuation.manifest_sha256,
        }
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
            budget_policy=budget_policy,
        )
        if prior is None:
            self._binding = self.controller.store.create_automatic_solve_worker_binding(binding)
        else:
            policy = json.loads(prior.normalized_policy())
            if policy.get("worker_active_timeout") != timeout:
                raise ValueError("automatic solve resume timeout changed")
            binding = replace(
                binding, generation=prior.generation + 1, prior_generation=prior.generation,
                contract_digest=prior.contract_digest, child_run_id=prior.child_run_id,
                budget_policy=policy,
            )
            self._binding = self.controller.store.resume_automatic_solve_worker_binding(prior, binding)
            if self._binding is None:
                raise ValueError("automatic solve resume lost its binding race")
        self._worker_id = worker.id
        self._worker_attempt_id = attempt.id

    def set_worker_context(self, service, owner_id: str | None = None, worker_id: str | None = None) -> None:
        self._worker_service = service
        self._worker_owner_id = owner_id
        if worker_id is not None:
            self._worker_id = worker_id

    def set_process_observer(self, observer: ProcessObserver | None) -> None:
        if observer is not None and not callable(observer):
            raise TypeError("process observer must be callable")
        self._observer = observer

    def set_continuation_guard(self, guard) -> None:
        if guard is not None and not callable(guard):
            raise TypeError("continuation guard must be callable")
        self._guard = guard

    def set_process_released(self, callback) -> None:
        if callback is not None and not callable(callback):
            raise TypeError("process released callback must be callable")
        # The adapter has no private subprocess of its own, but the native continuation may
        # launch one through the controller runtime.  Retain the WorkerService callback so the
        # controller's composable native scope can fan out exact release identity to the worker.
        self._released = callback

    def process_info(self) -> tuple[int | None, int | None]:
        return None, None

    def cancel(self) -> None:
        self._cancelled = True
        binding = self._binding
        if binding is None or self._worker_owner_id != binding.owner_id:
            return
        current = self.controller.store.get_automatic_solve_worker_binding(
            binding.binding_id, owner_id=binding.owner_id,
        )
        if current != binding or current.state.value in {"terminal", "superseded"}:
            return
        run = self.controller.store.get_run(self.continuation.run_id)
        if run is not None and run.status.value not in {"succeeded", "failed", "cancelled"}:
            self.controller.cancel(run.id)

    def _check(self) -> None:
        if self._cancelled:
            raise RuntimeError("automatic solve worker cancelled")
        if self._guard is not None:
            self._guard()

    def _control(self, request: AgentRequest) -> SolveExecutionControl | None:
        persisted = self.continuation.request.get("solve_wall_timeout")
        configured = request.timeout
        candidates = []
        if persisted is not None:
            candidates.append(persisted)
        if configured is not None:
            candidates.append(configured)
        if not candidates:
            return None
        if any(isinstance(item, bool) or not isinstance(item, (int, float)) or item <= 0 for item in candidates):
            raise ValueError("automatic solve worker timeout is invalid")
        return SolveExecutionControl(float(min(candidates)))

    def _validate_request(self, request: AgentRequest) -> None:
        binding = self._binding
        if binding is None or self._worker_id is None or self._worker_attempt_id is None:
            raise ValueError("automatic solve worker invocation requires explicit admission")
        if request.run_id != f"worker-run-{self._worker_id}" or request.task_id != self._worker_attempt_id:
            raise ValueError("automatic solve worker request identity changed")
        if request.role != "automatic-solve":
            raise ValueError("automatic solve worker role changed")
        if self._worker_service is None:
            raise ValueError("automatic solve worker service context is missing")
        expected = self._worker_service.workspace / "workers" / self._worker_id / self._worker_attempt_id
        if request.workspace != expected.resolve(strict=False):
            raise ValueError("automatic solve worker workspace changed")

    def _finish(self, payload: dict[str, object]) -> AgentResult:
        binding = self._binding
        if binding is None:
            raise ValueError("automatic solve worker was not admitted")
        run = self.controller.store.get_run(binding.run_id)
        status = payload.get("status")
        if run is None or status not in {"succeeded", "failed", "cancelled"} or status != run.status.value:
            raise AutomaticSolveRecoveryRequired("native automatic solve remains unresolved")
        observed_payload = _terminal_payload(self.controller, binding.run_id, payload)
        contract_digest = observed_payload.get("contract_digest")
        child_run_id = observed_payload.get("child_run_id")
        prospective = replace(
            binding,
            # A disappeared link is not permission to erase an already persisted pin.
            # Preserve the admission pin so the read-only reader rejects drift rather than
            # validating a temporarily unlinked view.
            contract_digest=(contract_digest if isinstance(contract_digest, str) else binding.contract_digest),
            child_run_id=(child_run_id if isinstance(child_run_id, str) else binding.child_run_id),
        )
        # Capture is read-only and must happen before publishing ACTIVE + child pins.  If native
        # evidence is incomplete, the durable binding stays at its prior state and is explicitly
        # recoverable instead of being left ACTIVE with a terminal run.
        try:
            selected = capture_native_result(self.controller, prospective)
        except Exception as exc:
            raise AutomaticSolveRecoveryRequired("native terminal evidence is incomplete") from exc
        observed = self.controller.store.compare_and_swap_automatic_solve_worker_binding(
            binding,
            state=AutomaticSolveWorkerBindingState.ACTIVE,
            contract_digest=prospective.contract_digest,
            child_run_id=prospective.child_run_id,
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
        self._validate_request(request)
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
            control = self._control(request)
            # Native orchestration owns the actual subprocess.  Compose its controller scope
            # with WorkerService callbacks so process registration and release are one exact
            # identity.  Lightweight unit fixtures may omit this optional seam because they do
            # not launch native work; production LocalController always supplies it.
            observe_scope = getattr(self.controller, "automatic_worker_observation", None)
            if not callable(observe_scope):
                raise AutomaticSolveRecoveryRequired(
                    "automatic solve worker observation seam is unavailable"
                )
            def outer_observe(_run_id, _attempt_id, pid, pgid):
                callback = self._observer
                if callback is None:
                    return True
                result = callback(pid, pgid)
                return result is not False

            def outer_release(_run_id, _attempt_id, pid, pgid):
                callback = self._released
                if callback is None:
                    return True
                callback(pid, pgid)
                # WorkerService's callback records cleanup failure on the execution and
                # intentionally returns no value.  Confirm the exact registration is gone
                # before allowing native cleanup to clear its row.
                service = self._worker_service
                try:
                    rows = service.store.list_worker_processes(
                        self._worker_id, self._worker_attempt_id, service.service_owner_id,
                    )
                except Exception:  # noqa: BLE001 - failed inspection is not release evidence
                    return False
                return not any(row.pid == pid and row.pgid == pgid for row in rows)

            def outer_guard():
                if self._guard is not None:
                    self._guard()

            observation = observe_scope(
                self.continuation.run_id, outer_observe, outer_release, outer_guard,
            )
            with observation:
                payload = continue_automatic_solve(
                    self.config,
                    self.controller,
                    self.continuation,
                    execution_control=control,
                    active_timeout=None if control is not None else request.timeout,
                )
            if not isinstance(payload, dict):
                raise AutomaticSolveRecoveryRequired("native continuation returned invalid evidence")
            latest = self.controller.store.get_run(binding.run_id)
            if latest is None:
                raise AutomaticSolveRecoveryRequired("native automatic solve run disappeared")
            if payload.get("status") == "awaiting_input":
                self.controller.store.compare_and_swap_automatic_solve_worker_binding(
                    active, state=AutomaticSolveWorkerBindingState.AWAITING_INPUT,
                    observation_reason="awaiting_input", stop_reason="awaiting_input",
                )
                raise AutomaticSolveAwaitingInput("native automatic solve awaits input")
            if payload.get("status") in {"succeeded", "failed", "cancelled"} and payload.get("status") != latest.status.value:
                raise AutomaticSolveRecoveryRequired("native continuation status changed during observation")
            return self._finish(payload)
        except AutomaticSolveAwaitingInput:
            raise
        except AutomaticSolveRecoveryRequired:
            # A terminal native Run may still be missing one piece of immutable evidence.  Keep
            # the binding explicitly recoverable; leaving it ACTIVE would make a later resume
            # indistinguishable from a live execution and would strand the generation.
            try:
                self.controller.store.compare_and_swap_automatic_solve_worker_binding(
                    self._binding,
                    state=AutomaticSolveWorkerBindingState.RECOVERY_REQUIRED,
                    observation_reason="native_result_incomplete",
                    stop_reason="recovery_required",
                )
            except Exception as _store_error:  # noqa: BLE001 - preserve typed recovery outcome
                del _store_error
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
            except Exception as _store_error:  # noqa: BLE001 - retain recovery-required state after a Store race
                del _store_error
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
                worker, attempt, self.controller.workers.service_owner_id, timeout=timeout,
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
        result = self.controller.store.get_automatic_solve_worker_result_reference(
            binding.binding_id, owner_id=owner_id, generation=binding.generation,
        )
        if result is None:
            return None
        return validate_native_result(self.controller, binding, result)

    def resume(self, owner_id: str, worker_id: str, continuation: AutomaticSolveContinuation, *, timeout=None):
        """Explicitly admit a fresh worker generation under both prior ownership locks."""
        bindings = self.controller.store.list_automatic_solve_worker_bindings(owner_id)
        prior = next((item for item in bindings if item.worker_id == worker_id), None)
        if prior is None:
            raise PermissionError("automatic solve worker is not owned by caller")
        if prior.state is AutomaticSolveWorkerBindingState.TERMINAL:
            return self.read(owner_id, worker_id)
        if prior.state not in {
            AutomaticSolveWorkerBindingState.AWAITING_INPUT,
            AutomaticSolveWorkerBindingState.RECOVERY_REQUIRED,
        }:
            raise AutomaticSolveRecoveryRequired("automatic solve binding is not eligible for resume")
        if (owner_id != continuation.run_id or continuation.run_id != prior.run_id
                or continuation.request_sha256 != prior.lifecycle_digest
                or continuation.runtime_fingerprint != prior.runtime_fingerprint
                or continuation.workspace != prior.workspace_identity):
            raise ValueError("automatic solve resume configuration changed")
        run = self.controller.store.get_run(prior.run_id)
        if run is None:
            raise ValueError("automatic solve run is missing")
        continuation.verify(self.controller, run)
        old_owner = WorkerOwnerLock.acquire(self.controller.store.database, prior.service_owner_id)
        if old_owner is None:
            raise AutomaticSolveRecoveryRequired("prior automatic solve worker owner is still live")
        try:
            with own_automatic_solve(run.id, run.workspace):
                from .automatic_solve_bundle import validate_automatic_preparation_recovery

                validate_automatic_preparation_recovery(self.controller.store, run.id)
                adapter = AutomaticSolveWorkerAdapter(self.config, self.controller, continuation)
                return self.controller.workers.dispatch_adapter(
                    owner_id, adapter, role="automatic-solve", prompt="continue persisted automatic solve",
                    description="native automatic solve bridge", timeout=timeout,
                    required_capabilities=("native-automatic-solve",),
                    before_start=lambda worker, attempt: adapter.admit(
                        worker, attempt, self.controller.workers.service_owner_id, prior=prior, timeout=timeout,
                    ),
                )
        finally:
            old_owner.close()


__all__ = [
    "AutomaticSolveAwaitingInput", "AutomaticSolveRecoveryRequired",
    "AutomaticSolveWorkerAdapter", "AutomaticSolveWorkerBridge",
]
