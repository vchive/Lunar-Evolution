"""Small domain types shared by the controller and storage layers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .budget import BudgetSpec

# Worker-tool traversal is deliberately bounded.  This is a protocol limit rather than a
# database migration so every local service agrees on the maximum recursive depth.
MAX_WORKER_DEPTH = 32


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_INPUT = "awaiting_input"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    WAITING = "waiting"
    BLOCKED = "blocked"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"
    UNCERTAIN = "uncertain"


class WorkerPhase(StrEnum):
    """Activity state of a delegated worker, independent from its last outcome."""

    RUNNING = "running"
    IDLE = "idle"


class WorkerOutcome(StrEnum):
    """Durable outcome of the most recent worker attempt."""

    SUCCESS = "success"
    FAILURE = "failure"
    STOPPED = "stopped"
    LOST = "lost"


class WorkerStopReason(StrEnum):
    CANCELLED = "cancelled"
    PARENT_CANCELLED = "parent_cancelled"
    TIMEOUT = "timeout"
    RUNTIME_ERROR = "runtime_error"
    PROCESS_CLEANUP = "process_cleanup"
    RESTART = "restart"
    AWAITING_INPUT = "awaiting_input"
    RECOVERY_REQUIRED = "recovery_required"


@dataclass(frozen=True)
class Worker:
    id: str
    owner_id: str
    parent_worker_id: str | None
    role: str
    agent_type: str
    description: str
    depth: int
    phase: WorkerPhase
    outcome: WorkerOutcome | None
    stop_reason: WorkerStopReason | None
    result: str | None
    result_ref: str | None
    last_error: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class WorkerAttempt:
    id: str
    worker_id: str
    prompt: str
    status: str
    started_at: str
    finished_at: str | None
    outcome: WorkerOutcome | None
    result: str | None
    error: str | None
    service_owner_id: str | None = None


@dataclass(frozen=True)
class WorkerProcess:
    """One process group registered to an exact worker execution owner."""

    worker_id: str
    attempt_id: str
    service_owner_id: str
    pid: int
    pgid: int


@dataclass(frozen=True)
class WorkerBinding:
    """Durable association between one worker attempt and one scheduler task attempt."""

    worker_id: str
    worker_attempt_id: str
    run_id: str
    task_id: str
    task_attempt_id: str
    service_owner_id: str
    status: str
    active_timeout: float | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class WorkerResultEnvelope:
    """Versioned, integrity-checked projection of one worker ``AgentResult``.

    The raw JSON is kept in the Store so a result can be reconstructed after a process restart.
    ``artifact_manifest`` is deliberately separate from ``AgentResult.artifacts``: it records
    the bounded file observations made by the worker service without changing the adapter API.
    """

    worker_id: str
    worker_attempt_id: str
    schema_version: str
    adapter_name: str
    role: str
    status: str
    text: str
    error: str | None
    metadata: dict[str, object]
    artifacts: tuple[str, ...]
    artifact_manifest: tuple[dict[str, object], ...]
    sha256: str
    size: int
    created_at: str

    def to_agent_result(self):
        """Rebuild an ``AgentResult`` while keeping the model module dependency-light."""
        from .agents import AgentResult

        return AgentResult(
            adapter_name=self.adapter_name,
            role=self.role,
            status=self.status,
            text=self.text,
            error=self.error,
            metadata=dict(self.metadata),
            artifacts=tuple(self.artifacts),
        )

    @property
    def result(self):
        return self.to_agent_result()


@dataclass(frozen=True)
class Run:
    id: str
    goal: str
    status: RunStatus
    workspace: Path
    created_at: str
    updated_at: str
    runner_pid: int | None = None
    runner_pgid: int | None = None
    current_plan_id: str | None = None
    current_plan_version: int | None = None
    route_domain: str | None = None
    route_reason: str | None = None
    route_confidence: float | None = None
    solver_profile: str | None = None
    evaluator_profile: str | None = None
    route_required_capabilities: tuple[str, ...] = ()
    route_evidence: tuple[str, ...] = ()
    budget: BudgetSpec | None = None


@dataclass(frozen=True)
class Task:
    id: str
    run_id: str
    title: str
    prompt: str
    state: TaskStatus
    attempts: int
    result_path: Path | None
    last_error: str | None
    created_at: str
    updated_at: str
    dependencies: tuple[str, ...] = ()
    acceptance: str | None = None
    input_question: str | None = None
    input_options: tuple[str, ...] = ()
    input_answer_path: Path | None = None
    plan_task_id: str | None = None
    orchestration: bool = False


@dataclass(frozen=True)
class Attempt:
    id: str
    task_id: str
    runtime: str
    status: str
    started_at: str
    finished_at: str | None
    error: str | None
    pid: int | None = None
    pgid: int | None = None
