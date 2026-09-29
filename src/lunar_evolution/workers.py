"""Provider-neutral, locally persisted worker sessions.

This layer is intentionally smaller than the task scheduler. It supplies the WebAgent-style
worker control plane (dispatch/send/list/wait/resume/cancel) while delegating execution to the
existing explicit AgentAdapter registry.
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from .agents import AgentAdapter, AgentRegistry, AgentRequest, AgentResult
from .models import (
    MAX_WORKER_DEPTH,
    Worker,
    WorkerAttempt,
    WorkerOutcome,
    WorkerPhase,
    WorkerStopReason,
)
from .process_ownership import ProcessCleanupStatus, RegisteredProcess, cleanup_registered_processes
from .store import Store
from .worker_ownership import WorkerOwnerLock

_MAX_INLINE_RESULT_BYTES = 64 * 1024
_MAX_ARTIFACT_READ_BYTES = 8 * 1024 * 1024
_RESULT_REF_PATTERN = re.compile(r"^worker-result-(worker-attempt-[0-9a-f]{32})-([0-9a-f]{64})$")


class _WorkerStopped(RuntimeError):
    pass


class _WorkerCleanupFailed(RuntimeError):
    pass


@dataclass
class _Execution:
    worker: Worker
    attempt_id: str
    adapter: AgentAdapter
    started: bool = False
    cleanup_failed: bool = False


def _is_timeout_error(error: BaseException) -> bool:
    """Recognize typed timeout causes without persisting provider or exception text."""
    current: BaseException | None = error
    seen: set[int] = set()
    for _ in range(8):
        if current is None or id(current) in seen:
            return False
        seen.add(id(current))
        if isinstance(current, TimeoutError) or type(current).__name__ == "TimeoutExpired":
            return True
        evidence = getattr(current, "evidence", None)
        if getattr(evidence, "reason", None) == "transport_timeout":
            return True
        current = current.__cause__ or current.__context__
    return False


def _failure_reason(error: BaseException) -> WorkerStopReason:
    typed = getattr(error, "worker_stop_reason", None)
    if typed is not None:
        try:
            return WorkerStopReason(typed)
        except (TypeError, ValueError):
            pass
    current = error
    for _ in range(8):
        if isinstance(current, _WorkerStopped):
            return WorkerStopReason.CANCELLED
        if isinstance(current, _WorkerCleanupFailed):
            return WorkerStopReason.PROCESS_CLEANUP
        current = current.__cause__ or current.__context__
        if current is None:
            break
    return WorkerStopReason.TIMEOUT if _is_timeout_error(error) else WorkerStopReason.RUNTIME_ERROR


class WorkerService:
    """Own worker execution handles and persist every lifecycle transition in ``Store``."""

    def __init__(
        self,
        store: Store,
        registry: AgentRegistry,
        workspace: str | Path,
        *,
        max_depth: int = 1,
        max_workers: int = 4,
    ) -> None:
        if isinstance(max_depth, bool) or not isinstance(max_depth, int) or max_depth < 0:
            raise ValueError("max_depth must be a non-negative integer")
        if max_depth > MAX_WORKER_DEPTH:
            raise ValueError(f"max_depth must be at most {MAX_WORKER_DEPTH}")
        if isinstance(max_workers, bool) or not isinstance(max_workers, int) or max_workers < 1:
            raise ValueError("max_workers must be a positive integer")
        if max_depth > 1 and max_workers < max_depth + 1:
            raise ValueError("recursive workers require max_workers >= max_depth + 1")
        self.store = store
        self.registry = registry
        self.workspace = Path(workspace).expanduser().resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.max_depth = max_depth
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="lunar-worker")
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._waiters: dict[str, int] = {}
        self._active: dict[str, _Execution] = {}
        self._futures: dict[str, Future[None]] = {}
        self.service_owner_id = "worker-owner-" + uuid.uuid4().hex
        self._owner_lock: WorkerOwnerLock | None = None
        self._closed = False

    def dispatch(
        self,
        owner_id: str,
        *,
        role: str = "worker",
        prompt: str,
        description: str | None = None,
        parent_worker_id: str | None = None,
        required_capabilities: Sequence[str] = (),
        preferred_adapter: str | None = None,
        timeout: float | None = None,
        before_start: Callable[[Worker, WorkerAttempt], None] | None = None,
    ) -> Worker:
        with self._lock:
            self._ensure_open()
            adapter = self.registry.create_execution_adapter(role, required_capabilities, preferred_adapter)
            worker = self.store.create_worker(
                owner_id, role, description or prompt[:512], parent_worker_id=parent_worker_id,
                agent_type=adapter.name, max_depth=self.max_depth,
                require_parent_running=parent_worker_id is not None,
            )
            try:
                return self._start(
                    worker, owner_id, prompt, required_capabilities, adapter, timeout,
                    before_start=before_start, require_parent_running=parent_worker_id is not None,
                    allow_stopped_resume=False,
                )
            except Exception:
                # Only close a child that lost the parent-running admission race. Other startup
                # failures intentionally remain idle so the existing owner-scoped reconcile path
                # can recover them.
                parent = self.store.get_worker(parent_worker_id) if parent_worker_id else None
                if parent_worker_id and (parent is None or parent.phase is not WorkerPhase.RUNNING):
                    with suppress(Exception):
                        self.store.cancel_worker_tree(worker.id, owner_id)
                raise

    def send(self, owner_id: str, worker_id: str, content: str) -> Worker:
        worker = self._owned(owner_id, worker_id)
        if worker.phase is not WorkerPhase.RUNNING:
            raise ValueError("worker is not running")
        self.store.append_worker_input(worker_id, owner_id, content)
        return self.store.get_worker(worker_id) or worker

    def list(self, owner_id: str, *, running_only: bool = False) -> list[Worker]:
        return self.store.list_workers(owner_id, phase=WorkerPhase.RUNNING if running_only else None)

    def wait(self, owner_id: str, worker_id: str, timeout: float | None = None) -> Worker:
        self._owned(owner_id, worker_id)
        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        with self._condition:
            self._waiters[worker_id] = self._waiters.get(worker_id, 0) + 1
            try:
                while True:
                    worker = self._owned(owner_id, worker_id)
                    if worker.phase is WorkerPhase.IDLE:
                        return worker
                    remaining = None if deadline is None else deadline - time.monotonic()
                    if remaining is not None and remaining <= 0:
                        return worker
                    # Other services can settle/cancel through the same Store without our
                    # in-process condition. Periodically re-read the durable authority.
                    self._condition.wait(min(remaining, 0.1) if remaining is not None else 0.1)
            finally:
                count = self._waiters.get(worker_id, 1) - 1
                if count:
                    self._waiters[worker_id] = count
                else:
                    self._waiters.pop(worker_id, None)

    def cancel(self, owner_id: str, worker_id: str) -> Worker:
        self._owned(owner_id, worker_id)
        with self._lock:
            ids = self.store.cancel_worker_tree(worker_id, owner_id)
            active = [item for item in self._active.values() if item.worker.id in ids
                      and not self._is_running(item)]
            attempts = [item for item in self.store.list_worker_owned_attempts(owner_id)
                        if item.worker_id in ids and item.status != "running"]
        for attempt in attempts:
            self._cleanup_attempt(attempt.worker_id, attempt.id, attempt.service_owner_id)
        for execution in active:
            if not execution.started:
                continue
            try:
                execution.adapter.cancel()
            except Exception:  # noqa: BLE001, S112 - cleanup continues for every owned adapter
                continue
        for attempt in attempts:
            self._cleanup_attempt(attempt.worker_id, attempt.id, attempt.service_owner_id)
        with self._condition:
            self._condition.notify_all()
        return self.store.get_worker(worker_id)  # type: ignore[return-value]

    def resume(
        self,
        owner_id: str,
        worker_id: str,
        *,
        prompt: str | None = None,
        required_capabilities: Sequence[str] = (),
        preferred_adapter: str | None = None,
        timeout: float | None = None,
    ) -> Worker:
        with self._lock:
            self._ensure_open()
            worker = self._owned(owner_id, worker_id)
            if worker.phase is WorkerPhase.RUNNING:
                raise ValueError("worker is already running")
            adapter = self.registry.create_execution_adapter(worker.role, required_capabilities, preferred_adapter)
            queued = self.store.list_worker_input_records(worker_id)
            prior = self.store.list_worker_attempts(worker_id, owner_id)
            effective = prompt or (prior[-1].prompt if prior else worker.description)
            if queued:
                effective = effective + "\n\nFollow-up input:\n" + "\n\n".join(content for _, content in queued)
            return self._start(
                worker, owner_id, effective, required_capabilities, adapter, timeout,
                input_ids=[identity for identity, _ in queued],
                reject_cancelled_parent=worker.parent_worker_id is not None,
                allow_stopped_resume=True,
            )

    def reconcile(self, owner_id: str) -> int:
        """Reconcile this caller's abandoned service attempts, never a live/unknown owner."""
        changed = 0
        for attempt in self.store.list_worker_owned_attempts(owner_id):
            try:
                lock = WorkerOwnerLock.acquire(self.store.database, attempt.service_owner_id)
            except (OSError, ValueError):
                continue  # Missing/unsafe ownership evidence does not prove interruption.
            if lock is None:
                continue
            try:
                if self._cleanup_attempt(attempt.worker_id, attempt.id, attempt.service_owner_id):
                    changed += self.store.reconcile_workers(
                        owner_id=owner_id, service_owner_id=attempt.service_owner_id,
                        worker_id=attempt.worker_id, attempt_id=attempt.id,
                    )
            finally:
                lock.close()
        with self._condition:
            self._condition.notify_all()
        return changed

    def read_result(self, owner_id: str, worker_id: str) -> str | None:
        """Read and verify a large result artifact owned by the caller."""
        worker = self._owned(owner_id, worker_id)
        if worker.result_ref is None:
            return worker.result
        match = _RESULT_REF_PATTERN.fullmatch(worker.result_ref)
        if match is None:
            raise ValueError("worker result reference is invalid")
        attempt_id, expected_digest = match.groups()
        if not any(attempt.id == attempt_id for attempt in self.store.list_worker_attempts(worker_id, owner_id)):
            raise ValueError("worker result attempt is unknown")
        path = self.workspace / "workers" / worker.id / attempt_id / "result.txt"
        resolved = path.resolve(strict=False)
        artifact_root = (self.workspace / "workers").resolve(strict=False)
        try:
            resolved.relative_to(artifact_root)
        except ValueError as exc:
            raise ValueError("worker result artifact escapes workspace") from exc
        if path.is_symlink() or not path.is_file():
            raise ValueError("worker result artifact is missing")
        raw = path.read_bytes()
        if len(raw) > _MAX_ARTIFACT_READ_BYTES:
            raise ValueError("worker result artifact exceeds the read limit")
        if hashlib.sha256(raw).hexdigest() != expected_digest:
            raise ValueError("worker result artifact integrity check failed")
        return raw.decode("utf-8")

    def read_result_envelope(self, owner_id: str, worker_id: str) -> AgentResult:
        """Read the complete durable ``AgentResult`` for an idle owned worker."""
        worker = self._owned(owner_id, worker_id)
        if worker.phase is WorkerPhase.RUNNING:
            raise ValueError("worker result is not settled")
        envelope = self.store.get_worker_result(worker_id, owner_id=owner_id)
        if envelope is None:
            raise ValueError("worker result envelope is missing")
        return envelope.to_agent_result()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            active = list(self._active.values())
        for execution in active:
            # An old cancelled attempt may coexist with an explicit continuation owned by
            # another service. Closing this service must never cancel that new attempt.
            try:
                self.store.settle_worker(
                    execution.worker.id, execution.attempt_id, WorkerOutcome.STOPPED,
                    reason=WorkerStopReason.CANCELLED,
                )
            except Exception:  # noqa: BLE001, S110 - a Store failure must not skip local cleanup
                pass
            if execution.started:
                try:
                    execution.adapter.cancel()
                except Exception:  # noqa: BLE001, S110 - finish cleanup of every owned attempt
                    pass
            self._cleanup_attempt(execution.worker.id, execution.attempt_id, self.service_owner_id)
        # Queued attempts drain through the stop guard, so their exact ownership is released.
        self._executor.shutdown(wait=False)

    def _start(
        self,
        worker: Worker,
        owner_id: str,
        prompt: str,
        required_capabilities: Sequence[str],
        adapter: AgentAdapter,
        timeout: float | None,
        *,
        input_ids: Sequence[str] = (),
        before_start: Callable[[Worker, WorkerAttempt], None] | None = None,
        require_parent_running: bool = False,
        reject_cancelled_parent: bool = False,
        allow_stopped_resume: bool = True,
    ) -> Worker:
        with self._lock:
            self._ensure_open()
            if self._owner_lock is None:
                self._owner_lock = WorkerOwnerLock.acquire(
                    self.store.database, self.service_owner_id, create=True,
                )
                if self._owner_lock is None:
                    raise ValueError("worker execution owner is busy")
            attempt = None
            try:
                attempt = self.store.start_worker_attempt(
                    worker.id, owner_id, prompt, service_owner_id=self.service_owner_id,
                    input_ids=input_ids, require_parent_running=require_parent_running,
                    reject_cancelled_parent=reject_cancelled_parent,
                    allow_stopped_resume=allow_stopped_resume,
                )
                execution = _Execution(worker, attempt.id, adapter)
                self._active[attempt.id] = execution
                if before_start is not None:
                    before_start(worker, attempt)
                self._futures[attempt.id] = self._executor.submit(
                    self._execute, execution, prompt, required_capabilities, timeout
                )
            except Exception:
                if attempt is not None:
                    self._active.pop(attempt.id, None)
                try:
                    if attempt is not None:
                        self.store.settle_worker(worker.id, attempt.id, WorkerOutcome.FAILURE,
                                                 reason=WorkerStopReason.RUNTIME_ERROR)
                finally:
                    self._release_idle_owner()
                raise
        return self.store.get_worker(worker.id)  # type: ignore[return-value]

    def dispatch_adapter(
        self,
        owner_id: str,
        adapter: AgentAdapter,
        *,
        prompt: str,
        role: str = "worker",
        description: str | None = None,
        parent_worker_id: str | None = None,
        required_capabilities: Sequence[str] = (),
        timeout: float | None = None,
        before_start: Callable[[Worker, WorkerAttempt], None] | None = None,
    ) -> Worker:
        """Dispatch an explicitly constructed adapter through the normal attempt boundary.

        This is the narrow extension used by native lifecycle bridges.  It does not register
        the adapter globally and therefore cannot be selected or resumed by the generic worker
        API.  The same attempt ownership, process observation and cleanup path is retained.
        """
        if not isinstance(adapter, AgentAdapter):
            # Protocols marked runtime-checkable are intentionally used here so custom bridge
            # adapters receive the same lifecycle validation as registry-created instances.
            raise TypeError("adapter does not implement the AgentAdapter lifecycle")
        with self._lock:
            self._ensure_open()
            worker = self.store.create_worker(
                owner_id, role, description or prompt[:512], parent_worker_id=parent_worker_id,
                agent_type=adapter.name, max_depth=self.max_depth,
                require_parent_running=parent_worker_id is not None,
            )
            try:
                return self._start(
                    worker, owner_id, prompt, required_capabilities, adapter, timeout,
                    before_start=before_start, require_parent_running=parent_worker_id is not None,
                    allow_stopped_resume=False,
                )
            except Exception:
                parent = self.store.get_worker(parent_worker_id) if parent_worker_id else None
                if parent_worker_id and (parent is None or parent.phase is not WorkerPhase.RUNNING):
                    with suppress(Exception):
                        self.store.cancel_worker_tree(worker.id, owner_id)
                raise

    def _execute(
        self,
        execution: _Execution,
        prompt: str,
        required_capabilities: Sequence[str],
        timeout: float | None,
    ) -> None:
        worker, attempt_id, adapter = execution.worker, execution.attempt_id, execution.adapter

        def guard() -> None:
            if self._closed or not self._is_running(execution):
                raise _WorkerStopped("worker attempt stopped")
            if execution.cleanup_failed:
                raise _WorkerCleanupFailed("worker process cleanup failed")

        def observe(pid: int, pgid: int | None) -> None:
            try:
                if pgid is None or not self.store.register_worker_process(
                    worker.id, attempt_id, self.service_owner_id, pid, pgid,
                ):
                    raise _WorkerCleanupFailed("worker process registration failed")
                if self._closed or not self._is_running(execution):
                    self._cleanup_attempt(worker.id, attempt_id, self.service_owner_id)
                    raise _WorkerStopped("worker launch cancelled")
            except Exception as exc:
                # Some legacy runtimes treat observer failures as optional metadata.
                # Stop this exact adapter before returning, and retain a failure flag so
                # swallowing the callback exception cannot turn the attempt into success.
                if not isinstance(exc, _WorkerStopped):
                    execution.cleanup_failed = True
                try:
                    adapter.cancel()
                except Exception:  # noqa: BLE001, S110 - preserve the ownership failure
                    pass
                raise

        def released(pid: int, pgid: int | None) -> None:
            if pgid is not None and not self._cleanup_attempt(
                worker.id, attempt_id, self.service_owner_id, identity=(pid, pgid),
            ):
                execution.cleanup_failed = True

        try:
            with self._lock:
                guard()
                execution.started = True
            root = self.workspace / "workers" / worker.id / attempt_id
            root.mkdir(parents=True, exist_ok=True)
            adapter.set_process_observer(observe)
            for name, callback in (("set_continuation_guard", guard), ("set_process_released", released)):
                setter = getattr(adapter, name, None)
                if callable(setter):
                    setter(callback)
            set_worker_context = getattr(adapter, "set_worker_context", None)
            if callable(set_worker_context):
                set_worker_context(self, worker.owner_id, worker.id)
            request = AgentRequest(
                run_id=f"worker-run-{worker.id}", task_id=attempt_id, role=worker.role,
                prompt=prompt, required_capabilities=tuple(required_capabilities), workspace=root, timeout=timeout,
            )
            guard()
            result: AgentResult = adapter.run(request)
            guard()
            if not self._cleanup_attempt(worker.id, attempt_id, self.service_owner_id):
                raise _WorkerCleanupFailed("worker process cleanup failed")
            outcome = WorkerOutcome.SUCCESS if result.status == "succeeded" else WorkerOutcome.STOPPED if result.status == "cancelled" else WorkerOutcome.FAILURE
            reason = WorkerStopReason.CANCELLED if result.status == "cancelled" else WorkerStopReason.RUNTIME_ERROR if result.status == "failed" else None
            result_ref = None
            encoded_result = result.text.encode("utf-8")
            if len(encoded_result) > _MAX_INLINE_RESULT_BYTES:
                (root / "result.txt").write_bytes(encoded_result)
                result_ref = f"worker-result-{attempt_id}-{hashlib.sha256(encoded_result).hexdigest()}"
            self.store.persist_worker_result(
                worker.id,
                attempt_id,
                result,
                artifact_manifest=self._artifact_manifest(root, result.artifacts),
            )
            with self._condition:
                delivery = "waiter" if self._waiters.get(worker.id, 0) else "notification"
                self.store.settle_worker(
                    worker.id, attempt_id, outcome, result=result.text,
                    result_ref=result_ref, reason=reason, delivery=delivery,
                )
        except Exception as exc:  # noqa: BLE001 - persist a safe typed failure for every adapter error
            reason = (
                WorkerStopReason.CANCELLED if self._closed else
                WorkerStopReason.PROCESS_CLEANUP if execution.cleanup_failed else _failure_reason(exc)
            )
            outcome = WorkerOutcome.STOPPED if reason in {
                WorkerStopReason.CANCELLED, WorkerStopReason.AWAITING_INPUT,
                WorkerStopReason.RECOVERY_REQUIRED,
            } else WorkerOutcome.FAILURE
            fallback = AgentResult(
                adapter_name=adapter.name,
                role=worker.role,
                status="cancelled" if outcome is WorkerOutcome.STOPPED else "failed",
                text="",
                error=reason.value,
            )
            try:
                self.store.persist_worker_result(worker.id, attempt_id, fallback)
            except Exception:  # noqa: BLE001, S110 - terminal settlement remains authoritative
                pass
            self.store.settle_worker(worker.id, attempt_id, outcome, reason=reason)
        finally:
            try:
                self._cleanup_attempt(worker.id, attempt_id, self.service_owner_id)
            finally:
                for name in ("set_process_observer", "set_continuation_guard", "set_process_released"):
                    setter = getattr(adapter, name, None)
                    if callable(setter):
                        try:
                            setter(None)
                        except Exception:  # noqa: BLE001, S110 - cleanup must reach every owned handle
                            pass
                set_worker_context = getattr(adapter, "set_worker_context", None)
                if callable(set_worker_context):
                    try:
                        set_worker_context(None)
                    except Exception:  # noqa: BLE001, S110 - clear opt-in tools before reuse
                        pass
                with self._condition:
                    self._active.pop(attempt_id, None)
                    self._futures.pop(attempt_id, None)
                    self._release_idle_owner()
                    self._condition.notify_all()

    def _is_running(self, execution: _Execution) -> bool:
        attempt = self.store.get_worker_attempt(
            execution.worker.id, execution.attempt_id, service_owner_id=self.service_owner_id,
        )
        return attempt is not None and attempt.status == "running"

    def _cleanup_attempt(self, worker_id, attempt_id, service_owner_id, *, identity=None) -> bool:
        try:
            registrations = self.store.list_worker_processes(worker_id, attempt_id, service_owner_id)
        except Exception:  # noqa: BLE001 - inability to inspect ownership is not release evidence
            return False
        if identity is not None:
            registrations = [reg for reg in registrations if (reg.pid, reg.pgid) == identity]
        targets = [RegisteredProcess(
            reg.pid, reg.pgid,
            owner_check=lambda reg=reg: reg in self.store.list_worker_processes(
                worker_id, attempt_id, service_owner_id,
            ),
            label=attempt_id,
        ) for reg in registrations]
        for reg, result in zip(registrations, cleanup_registered_processes(targets), strict=True):
            if result.status in {ProcessCleanupStatus.CLEANED, ProcessCleanupStatus.ALREADY_EXITED}:
                try:
                    self.store.clear_worker_process(worker_id, attempt_id, service_owner_id, reg.pid, reg.pgid)
                except Exception:  # noqa: BLE001, S110 - retain failed registration and continue fan-out
                    pass
        try:
            remaining = self.store.list_worker_processes(worker_id, attempt_id, service_owner_id)
        except Exception:  # noqa: BLE001 - a later inspection cannot fabricate confirmed cleanup
            return False
        return not any(identity is None or (reg.pid, reg.pgid) == identity for reg in remaining)

    @staticmethod
    def _artifact_manifest(root: Path, artifacts: Sequence[str]) -> tuple[dict[str, object], ...]:
        """Capture bounded file observations without making result persistence depend on files."""
        manifest: list[dict[str, object]] = []
        for relative in artifacts:
            path = root / relative
            item: dict[str, object] = {"path": relative}
            try:
                resolved = path.resolve(strict=False)
                resolved.relative_to(root.resolve(strict=False))
                info = path.stat()
                if path.is_symlink() or not path.is_file() or info.st_size > _MAX_ARTIFACT_READ_BYTES:
                    raise ValueError("artifact is not a bounded regular file")
                content = path.read_bytes()
                item["size"] = len(content)
                item["sha256"] = hashlib.sha256(content).hexdigest()
            except (OSError, ValueError):
                # The envelope remains durable; the consumer's materialization step rejects
                # missing, escaped, symlinked, or changed files using this manifest.
                item["size"] = None
                item["sha256"] = None
            manifest.append(item)
        return tuple(manifest)

    def _ensure_open(self) -> None:
        if self._closed:
            raise ValueError("worker service is closed")

    def _release_idle_owner(self) -> None:
        if not self._active and self._owner_lock is not None:
            self._owner_lock.close()
            self._owner_lock = None

    def _owned(self, owner_id: str, worker_id: str) -> Worker:
        worker = self.store.get_worker(worker_id)
        if worker is None:
            raise ValueError(f"unknown worker: {worker_id}")
        if worker.owner_id != owner_id:
            raise PermissionError("worker is not owned by caller")
        return worker
