"""Durable SQLite state for local runs.

The store deliberately exposes small operations instead of leaking SQL into the controller. Every
mutating operation emits an event, and event IDs are idempotency keys.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import uuid
from collections.abc import Mapping, Sequence
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .agents import AgentResult
from .algorithm import MAX_OUTPUTS, OutputSpec
from .automatic_solve_worker_binding import (
    AutomaticSolveWorkerBinding,
    AutomaticSolveWorkerBindingState,
    AutomaticSolveWorkerResultReference,
    binding_payload_equal,
)
from .budget import BudgetSpec
from .evaluator import validate_acceptance
from .models import (
    MAX_WORKER_DEPTH,
    Attempt,
    Run,
    RunStatus,
    Task,
    TaskStatus,
    Worker,
    WorkerAttempt,
    WorkerBinding,
    WorkerOutcome,
    WorkerPhase,
    WorkerProcess,
    WorkerResultEnvelope,
    WorkerStopReason,
)
from .policy import (
    PlanDocument,
    PlanPatch,
    PolicyDecision,
    apply_patch,
    validate_evidence,
    validate_reason,
)
from .routing import RouteDecision

_WORKER_RESULT_SCHEMA_VERSION = "lunar-worker-result-v1"
_MAX_WORKER_RESULT_ENVELOPE_BYTES = 2 * 1024 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    goal TEXT NOT NULL,
    status TEXT NOT NULL,
    workspace TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    runner_pid INTEGER,
    runner_pgid INTEGER,
    current_plan_id TEXT,
    current_plan_version INTEGER,
    route_domain TEXT,
    route_reason TEXT,
    route_confidence REAL,
    solver_profile TEXT,
    evaluator_profile TEXT,
    route_required_capabilities TEXT NOT NULL DEFAULT '[]',
    route_evidence TEXT NOT NULL DEFAULT '[]',
    budget TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id),
    parent_id TEXT REFERENCES tasks(id),
    title TEXT NOT NULL,
    prompt TEXT NOT NULL,
    state TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    result_path TEXT,
    last_error TEXT,
    dependencies TEXT NOT NULL DEFAULT '[]',
    acceptance TEXT,
    input_question TEXT,
    input_options TEXT NOT NULL DEFAULT '[]',
    input_answer_path TEXT,
    plan_task_id TEXT,
    orchestration INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS tasks_run_state_idx ON tasks(run_id, state, created_at);
CREATE TABLE IF NOT EXISTS attempts (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    runtime TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    heartbeat_at TEXT,
    error TEXT,
    pid INTEGER,
    pgid INTEGER
);
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id),
    task_id TEXT REFERENCES tasks(id),
    type TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_run_idx ON events(run_id, created_at);
CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id),
    task_id TEXT NOT NULL REFERENCES tasks(id),
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size INTEGER NOT NULL,
    kind TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workers (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    parent_worker_id TEXT REFERENCES workers(id),
    role TEXT NOT NULL,
    agent_type TEXT NOT NULL,
    description TEXT NOT NULL,
    depth INTEGER NOT NULL,
    phase TEXT NOT NULL,
    outcome TEXT,
    stop_reason TEXT,
    result TEXT,
    result_ref TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS workers_owner_idx ON workers(owner_id, created_at);
CREATE INDEX IF NOT EXISTS workers_parent_idx ON workers(parent_worker_id, created_at);
CREATE TABLE IF NOT EXISTS worker_attempts (
    id TEXT PRIMARY KEY,
    worker_id TEXT NOT NULL REFERENCES workers(id),
    prompt TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    outcome TEXT,
    result TEXT,
    error TEXT,
    service_owner_id TEXT
);
CREATE INDEX IF NOT EXISTS worker_attempts_worker_idx ON worker_attempts(worker_id, started_at);
CREATE TABLE IF NOT EXISTS worker_attempt_processes (
    attempt_id TEXT NOT NULL REFERENCES worker_attempts(id),
    pid INTEGER NOT NULL,
    pgid INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(attempt_id, pid, pgid)
);
CREATE TABLE IF NOT EXISTS worker_inputs (
    id TEXT PRIMARY KEY,
    worker_id TEXT NOT NULL REFERENCES workers(id),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS worker_events (
    id TEXT PRIMARY KEY,
    worker_id TEXT NOT NULL REFERENCES workers(id),
    type TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS worker_events_idx ON worker_events(worker_id, created_at);
CREATE TABLE IF NOT EXISTS worker_bindings (
    worker_id TEXT PRIMARY KEY REFERENCES workers(id),
    worker_attempt_id TEXT NOT NULL REFERENCES worker_attempts(id),
    run_id TEXT NOT NULL REFERENCES runs(id),
    task_id TEXT NOT NULL REFERENCES tasks(id),
    task_attempt_id TEXT NOT NULL REFERENCES attempts(id),
    service_owner_id TEXT NOT NULL,
    status TEXT NOT NULL,
    active_timeout REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS worker_bindings_attempt_idx
    ON worker_bindings(worker_attempt_id);
CREATE UNIQUE INDEX IF NOT EXISTS worker_bindings_task_attempt_idx
    ON worker_bindings(task_attempt_id);
CREATE INDEX IF NOT EXISTS worker_bindings_task_idx
    ON worker_bindings(run_id, task_id, status);
CREATE TABLE IF NOT EXISTS worker_attempt_results (
    worker_attempt_id TEXT PRIMARY KEY REFERENCES worker_attempts(id),
    worker_id TEXT NOT NULL REFERENCES workers(id),
    schema_version TEXT NOT NULL,
    payload TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS worker_attempt_results_worker_idx
    ON worker_attempt_results(worker_id, created_at);
CREATE TABLE IF NOT EXISTS automatic_solve_worker_bindings (
    binding_id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    run_id TEXT NOT NULL REFERENCES runs(id),
    workspace_identity TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    worker_attempt_id TEXT NOT NULL,
    service_owner_id TEXT NOT NULL,
    generation INTEGER NOT NULL,
    state TEXT NOT NULL,
    lifecycle_digest TEXT NOT NULL,
    runtime_fingerprint TEXT NOT NULL,
    budget_policy TEXT NOT NULL,
    contract_digest TEXT,
    child_run_id TEXT,
    prior_generation INTEGER,
    observation_reason TEXT,
    stop_reason TEXT,
    result_ref_digest TEXT,
    native_receipt_id TEXT,
    delivery_identity TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    schema_version TEXT NOT NULL DEFAULT '1'
);
CREATE UNIQUE INDEX IF NOT EXISTS automatic_solve_worker_generation_idx
    ON automatic_solve_worker_bindings(run_id, generation);
CREATE UNIQUE INDEX IF NOT EXISTS automatic_solve_worker_unresolved_idx
    ON automatic_solve_worker_bindings(run_id)
    WHERE state IN ('admitted', 'active', 'awaiting_input', 'recovery_required', 'unknown');
CREATE INDEX IF NOT EXISTS automatic_solve_worker_run_idx
    ON automatic_solve_worker_bindings(run_id, generation);
CREATE TABLE IF NOT EXISTS automatic_solve_worker_result_refs (
    binding_id TEXT NOT NULL REFERENCES automatic_solve_worker_bindings(binding_id),
    generation INTEGER NOT NULL,
    run_id TEXT NOT NULL REFERENCES runs(id),
    worker_attempt_id TEXT NOT NULL,
    outcome TEXT NOT NULL,
    reference TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    schema_version TEXT NOT NULL DEFAULT '1',
    PRIMARY KEY(binding_id, generation)
);
CREATE TABLE IF NOT EXISTS plan_revisions (
    plan_id TEXT NOT NULL,
    run_id TEXT NOT NULL REFERENCES runs(id),
    version INTEGER NOT NULL,
    parent_version INTEGER,
    document TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(run_id, version)
);
CREATE INDEX IF NOT EXISTS plan_revisions_run_idx ON plan_revisions(run_id, version);
CREATE TABLE IF NOT EXISTS policy_decisions (
    id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES runs(id),
    action TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS policy_decisions_run_idx ON policy_decisions(run_id, created_at);
"""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _has_input_question(value: object) -> bool:
    """Dependency waits and legacy blank questions are scheduler-owned, not user input."""
    return isinstance(value, str) and bool(value.strip())


class Store:
    def __init__(self, database: str | Path) -> None:
        self.database = Path(database).expanduser().resolve()

    def _connect(self) -> sqlite3.Connection:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection, table: str, column: str, declaration: str
    ) -> None:
        columns = {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(SCHEMA)
            self._migrate_plan_revision_key(connection)
            connection.execute(
                "CREATE INDEX IF NOT EXISTS plan_revisions_plan_idx ON plan_revisions(plan_id, version)"
            )
            # Keep upgrades compatible with the P1 database created before plans and detached
            # process metadata existed. SQLite has no IF NOT EXISTS form for ADD COLUMN.
            self._ensure_column(connection, "runs", "runner_pid", "INTEGER")
            self._ensure_column(connection, "runs", "runner_pgid", "INTEGER")
            self._ensure_column(connection, "runs", "current_plan_id", "TEXT")
            self._ensure_column(connection, "runs", "current_plan_version", "INTEGER")
            self._ensure_column(connection, "runs", "route_domain", "TEXT")
            self._ensure_column(connection, "runs", "route_reason", "TEXT")
            self._ensure_column(connection, "runs", "route_confidence", "REAL")
            self._ensure_column(connection, "runs", "solver_profile", "TEXT")
            self._ensure_column(connection, "runs", "evaluator_profile", "TEXT")
            self._ensure_column(connection, "runs", "route_required_capabilities", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(connection, "runs", "route_evidence", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(connection, "runs", "budget", "TEXT NOT NULL DEFAULT '{}'")
            self._ensure_column(connection, "tasks", "dependencies", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(connection, "tasks", "acceptance", "TEXT")
            self._ensure_column(connection, "tasks", "input_question", "TEXT")
            self._ensure_column(connection, "tasks", "input_options", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(connection, "tasks", "input_answer_path", "TEXT")
            self._ensure_column(connection, "tasks", "plan_task_id", "TEXT")
            self._ensure_column(connection, "tasks", "orchestration", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "attempts", "pid", "INTEGER")
            self._ensure_column(connection, "attempts", "pgid", "INTEGER")
            self._ensure_column(connection, "workers", "result_ref", "TEXT")
            self._ensure_column(connection, "worker_attempts", "service_owner_id", "TEXT")
            self._ensure_column(connection, "automatic_solve_worker_bindings", "schema_version", "TEXT NOT NULL DEFAULT '1'")
            self._ensure_column(connection, "automatic_solve_worker_result_refs", "schema_version", "TEXT NOT NULL DEFAULT '1'")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS worker_attempts_owner_idx "
                "ON worker_attempts(service_owner_id, status)"
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(?, ?)",
                (1, utc_now()),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(?, ?)",
                (2, utc_now()),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(?, ?)",
                (3, utc_now()),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(?, ?)",
                (4, utc_now()),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(?, ?)",
                (5, utc_now()),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(?, ?)",
                (6, utc_now()),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(?, ?)",
                (7, utc_now()),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(?, ?)",
                (8, utc_now()),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(?, ?)",
                (9, utc_now()),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(?, ?)",
                (10, utc_now()),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(?, ?)",
                (11, utc_now()),
            )

    @staticmethod
    def _migrate_plan_revision_key(connection: sqlite3.Connection) -> None:
        """Upgrade the first feature-006 table, whose key was plan_id/version.

        Plan IDs are stable within a run but callers may intentionally reuse a plan template in
        another run.  Keying revisions by run/version prevents unrelated runs from colliding while
        retaining the plan ID as an indexed lookup/reference field.
        """
        indexes = connection.execute("PRAGMA index_list(plan_revisions)").fetchall()
        primary_columns: list[str] = []
        for index in indexes:
            if index[2]:  # unique; the autoindex for a PRIMARY KEY is unique
                columns = connection.execute(f"PRAGMA index_info({index[1]})").fetchall()
                primary_columns = [column[2] for column in columns]
                if primary_columns:
                    break
        if primary_columns != ["run_id", "version"]:
            connection.execute("ALTER TABLE plan_revisions RENAME TO plan_revisions_legacy")
            connection.execute(
                """CREATE TABLE plan_revisions (
                    plan_id TEXT NOT NULL,
                    run_id TEXT NOT NULL REFERENCES runs(id),
                    version INTEGER NOT NULL,
                    parent_version INTEGER,
                    document TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(run_id, version)
                )"""
            )
            connection.execute(
                "INSERT INTO plan_revisions(plan_id, run_id, version, parent_version, document, created_at) "
                "SELECT plan_id, run_id, version, parent_version, document, created_at FROM plan_revisions_legacy"
            )
            connection.execute("DROP TABLE plan_revisions_legacy")
            connection.execute("CREATE INDEX IF NOT EXISTS plan_revisions_run_idx ON plan_revisions(run_id, version)")
            connection.execute("CREATE INDEX IF NOT EXISTS plan_revisions_plan_idx ON plan_revisions(plan_id, version)")

    def create_run(
        self,
        goal: str,
        workspace: str | Path | None = None,
        tasks: list[dict[str, Any]] | None = None,
        route: RouteDecision | None = None,
    ) -> Run:
        goal = goal.strip()
        if not goal:
            raise ValueError("goal must not be empty")
        run_id = uuid.uuid4().hex
        timestamp = utc_now()
        workspace_path = (
            Path(workspace).expanduser().resolve()
            if workspace is not None
            else (self.database.parent / "runs" / run_id).resolve()
        )
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO runs(id, goal, status, workspace, created_at, updated_at, route_domain, route_reason, route_confidence, solver_profile, evaluator_profile, route_required_capabilities, route_evidence, budget) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, goal, RunStatus.PENDING.value, str(workspace_path), timestamp, timestamp,
                 route.domain if route else None, route.reason if route else None,
                 route.confidence if route else None, route.solver_profile if route else None,
                 route.evaluator_profile if route else None,
                 json.dumps(list(route.required_capabilities) if route else []),
                 json.dumps(list(route.evidence) if route else []),
                 json.dumps(route.budget.to_dict() if route else BudgetSpec().to_dict())),
            )
            plan_tasks = tasks if tasks is not None else [
                {
                    "id": f"task-{uuid.uuid4().hex[:12]}",
                    "title": "Execute user goal",
                    "prompt": goal,
                    "depends_on": [],
                    "acceptance": None,
                }
            ]
            normalized = self._validate_plan_tasks(plan_tasks)
            existing_ids = {
                row["id"]
                for row in connection.execute(
                    f"SELECT id FROM tasks WHERE id IN ({','.join('?' for _ in normalized)})",
                    [item["id"] for item in normalized],
                ).fetchall()
            }
            id_map: dict[str, str] = {}
            reserved = set(existing_ids)
            for item in normalized:
                candidate = item["id"]
                if candidate in reserved:
                    suffix = 1
                    candidate = f"{run_id[:8]}-{item['id']}"
                    while candidate in reserved:
                        suffix += 1
                        candidate = f"{run_id[:8]}-{item['id']}-{suffix}"
                id_map[item["id"]] = candidate
                reserved.add(candidate)
            normalized = [
                {
                    **item,
                    "id": id_map[item["id"]],
                    "depends_on": [id_map[dependency] for dependency in item["depends_on"]],
                }
                for item in normalized
            ]
            for item in normalized:
                state = TaskStatus.READY.value if not item["depends_on"] else TaskStatus.WAITING.value
                connection.execute(
                    "INSERT INTO tasks(id, run_id, title, prompt, state, dependencies, acceptance, created_at, updated_at) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        item["id"],
                        run_id,
                        item["title"],
                        item["prompt"],
                        state,
                        json.dumps(item["depends_on"]),
                        item["acceptance"],
                        timestamp,
                        timestamp,
                    ),
                )
            self._append_event(
                connection,
                run_id,
                None,
                "run_created",
                {"goal": goal, "task_count": len(normalized), **({"route": route.to_dict()} if route else {})},
            )
            if route is not None:
                self._append_event(connection, run_id, None, "route_selected", route.to_dict())
            for item in normalized:
                self._append_event(
                    connection,
                    run_id,
                    item["id"],
                    "task_created",
                    {
                        "title": item["title"],
                        "dependencies": item["depends_on"],
                        "acceptance": item["acceptance"],
                    },
                )
        return self.get_run(run_id)  # type: ignore[return-value]

    def create_run_with_plan(
        self, document: PlanDocument, decision: PolicyDecision | None = None, workspace: str | Path | None = None,
        route: RouteDecision | None = None,
    ) -> Run:
        """Create a run, first plan revision, tasks, and decision in one transaction."""
        if document.version != 1 or document.parent_version is not None:
            raise ValueError("a new planned run must start at version 1")
        if decision is not None:
            if decision.action != "execute_plan":
                raise ValueError("a planned run requires an execute_plan decision")
            if (decision.plan_id, decision.plan_version) != (document.plan_id, document.version):
                raise ValueError("execute_plan decision does not reference the supplied plan revision")
        timestamp = utc_now()
        run_id = uuid.uuid4().hex
        workspace_path = Path(workspace).expanduser().resolve() if workspace is not None else (self.database.parent / "runs" / run_id).resolve()
        task_items = [task.to_dict() for task in document.tasks]
        normalized = self._validate_plan_tasks(task_items)
        id_map = {item["id"]: f"{run_id[:8]}-{item['id']}" for item in normalized}
        normalized = [{**item, "id": id_map[item["id"]], "plan_task_id": item["id"], "depends_on": [id_map[dependency] for dependency in item["depends_on"]]} for item in normalized]
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO runs(id, goal, status, workspace, created_at, updated_at, current_plan_id, current_plan_version, route_domain, route_reason, route_confidence, solver_profile, evaluator_profile, route_required_capabilities, route_evidence, budget) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, document.goal, RunStatus.PENDING.value, str(workspace_path), timestamp, timestamp, document.plan_id, 1,
                 route.domain if route else None, route.reason if route else None, route.confidence if route else None,
                 route.solver_profile if route else None, route.evaluator_profile if route else None,
                 json.dumps(list(route.required_capabilities) if route else []),
                 json.dumps(list(route.evidence) if route else []), json.dumps(route.budget.to_dict() if route else BudgetSpec().to_dict())),
            )
            for item in normalized:
                state = TaskStatus.READY.value if not item["depends_on"] else TaskStatus.WAITING.value
                connection.execute(
                    "INSERT INTO tasks(id, run_id, title, prompt, state, dependencies, acceptance, plan_task_id, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (item["id"], run_id, item["title"], item["prompt"], state, json.dumps(item["depends_on"]), item["acceptance"], item["plan_task_id"], timestamp, timestamp),
                )
            connection.execute(
                "INSERT INTO plan_revisions(plan_id, run_id, version, parent_version, document, created_at) VALUES(?, ?, ?, ?, ?, ?)",
                (document.plan_id, run_id, document.version, document.parent_version, json.dumps(document.to_dict(), ensure_ascii=False, sort_keys=True), timestamp),
            )
            self._append_event(
                connection,
                run_id,
                None,
                "run_created",
                {"goal": document.goal, "task_count": len(normalized), "plan_id": document.plan_id, **({"route": route.to_dict()} if route else {})},
            )
            if route is not None:
                self._append_event(connection, run_id, None, "route_selected", route.to_dict())
            self._append_event(connection, run_id, None, "plan_created", {"plan_id": document.plan_id, "version": 1})
            for item in normalized:
                self._append_event(connection, run_id, item["id"], "task_created", {"title": item["title"], "dependencies": item["depends_on"], "acceptance": item["acceptance"]})
            if decision is not None:
                self._insert_decision(connection, run_id, decision)
        Path(workspace_path).mkdir(parents=True, exist_ok=True)
        return self.get_run(run_id)  # type: ignore[return-value]

    def attach_plan_to_run(
        self,
        run_id: str,
        document: PlanDocument,
        decision: PolicyDecision | None = None,
    ) -> bool:
        """Promote an intake run to a version-one plan without changing its run ID.

        Conversational intake deliberately starts with one durable compiler task so a clarification
        can pause and resume through the normal input lifecycle.  Once compilation succeeds this
        additive transaction installs the immutable plan revision and generated DAG alongside the
        completed intake task.  It does not alter the existing schema or rewrite prior events.
        """
        if not isinstance(document, PlanDocument):
            raise TypeError("document must be a PlanDocument")
        if document.version != 1 or document.parent_version is not None:
            raise ValueError("an attached plan must start at version 1")
        if decision is not None:
            if decision.action != "execute_plan":
                raise ValueError("an attached plan requires an execute_plan decision")
            if (decision.plan_id, decision.plan_version) != (document.plan_id, document.version):
                raise ValueError("execute_plan decision does not reference the attached plan")
        timestamp = utc_now()
        normalized = self._validate_plan_tasks([task.to_dict() for task in document.tasks])
        with self._connect() as connection:
            run = connection.execute(
                "SELECT current_plan_id, current_plan_version, status FROM runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if run is None:
                raise ValueError(f"unknown run: {run_id}")
            if run["current_plan_id"] is not None:
                if run["current_plan_id"] == document.plan_id and run["current_plan_version"] == 1:
                    return False
                raise ValueError("run already has a plan")
            existing_ids = {
                row["id"]
                for row in connection.execute("SELECT id FROM tasks WHERE run_id = ?", (run_id,)).fetchall()
            }
            id_map: dict[str, str] = {}
            for item in normalized:
                candidate = f"{run_id[:8]}-{item['id']}"
                suffix = 1
                while candidate in existing_ids or candidate in id_map.values():
                    suffix += 1
                    candidate = f"{run_id[:8]}-{item['id']}-{suffix}"
                id_map[item["id"]] = candidate
            connection.execute(
                "UPDATE runs SET current_plan_id = ?, current_plan_version = ?, budget = ?, updated_at = ? WHERE id = ?",
                (document.plan_id, document.version, json.dumps(document.budget.to_dict()), timestamp, run_id),
            )
            connection.execute(
                "INSERT INTO plan_revisions(plan_id, run_id, version, parent_version, document, created_at) VALUES(?, ?, ?, ?, ?, ?)",
                (
                    document.plan_id,
                    run_id,
                    document.version,
                    document.parent_version,
                    json.dumps(document.to_dict(), ensure_ascii=False, sort_keys=True),
                    timestamp,
                ),
            )
            self._append_event(
                connection,
                run_id,
                None,
                "plan_created",
                {"plan_id": document.plan_id, "version": document.version, "source": "conversational_intake"},
            )
            for item in normalized:
                physical_id = id_map[item["id"]]
                dependencies = [id_map[dependency] for dependency in item["depends_on"]]
                state = TaskStatus.READY.value if not dependencies else TaskStatus.WAITING.value
                connection.execute(
                    "INSERT INTO tasks(id, run_id, title, prompt, state, dependencies, acceptance, plan_task_id, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        physical_id,
                        run_id,
                        item["title"],
                        item["prompt"],
                        state,
                        json.dumps(dependencies),
                        item["acceptance"],
                        item["id"],
                        timestamp,
                        timestamp,
                    ),
                )
                self._append_event(
                    connection,
                    run_id,
                    physical_id,
                    "task_created",
                    {
                        "title": item["title"],
                        "dependencies": dependencies,
                        "acceptance": item["acceptance"],
                        "plan_task_id": item["id"],
                    },
                )
            if decision is not None:
                self._insert_decision(connection, run_id, decision)
        return True

    def _insert_decision(self, connection: sqlite3.Connection, run_id: str | None, decision: PolicyDecision, decision_id: str | None = None) -> str:
        decision_id = decision_id or f"decision-{uuid.uuid4().hex}"
        connection.execute(
            "INSERT OR IGNORE INTO policy_decisions(id, run_id, action, payload, created_at) VALUES(?, ?, ?, ?, ?)",
            (decision_id, run_id, decision.action, json.dumps(decision.to_dict(), ensure_ascii=False, sort_keys=True), utc_now()),
        )
        if run_id is not None:
            self._append_event(connection, run_id, None, "policy_decision", {"decision_id": decision_id, **decision.to_dict()}, event_id=f"event-{decision_id}")
        return decision_id

    def record_decision(self, decision: PolicyDecision, run_id: str | None = None, decision_id: str | None = None) -> str:
        with self._connect() as connection:
            return self._insert_decision(connection, run_id, decision, decision_id)

    def get_current_plan(self, run_id: str) -> PlanDocument | None:
        with self._connect() as connection:
            row = connection.execute("SELECT current_plan_id, current_plan_version FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None or not row["current_plan_id"] or row["current_plan_version"] is None:
                return None
            revision = connection.execute(
                "SELECT document FROM plan_revisions WHERE run_id = ? AND plan_id = ? AND version = ?",
                (run_id, row["current_plan_id"], row["current_plan_version"]),
            ).fetchone()
        return PlanDocument.from_dict(json.loads(revision["document"])) if revision else None

    def list_plan_revisions(self, run_id: str) -> list[PlanDocument]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT document FROM plan_revisions WHERE run_id = ? ORDER BY version", (run_id,)
            ).fetchall()
        return [PlanDocument.from_dict(json.loads(row["document"])) for row in rows]

    def list_decisions(self, run_id: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as connection:
            if run_id is None:
                rows = connection.execute("SELECT id, run_id, action, payload, created_at FROM policy_decisions ORDER BY created_at").fetchall()
            else:
                rows = connection.execute("SELECT id, run_id, action, payload, created_at FROM policy_decisions WHERE run_id = ? ORDER BY created_at", (run_id,)).fetchall()
        return [{"id": row["id"], "run_id": row["run_id"], "action": row["action"], "payload": json.loads(row["payload"]), "created_at": row["created_at"]} for row in rows]

    def commit_plan_revision(
        self,
        run_id: str,
        document: PlanDocument,
        reason: str,
        evidence: tuple[str, ...] = (),
        *,
        action: str = "patch_plan",
    ) -> PlanDocument:
        """Commit an already validated revision and synchronize not-yet-run scheduler tasks."""
        reason = validate_reason(reason)
        evidence = validate_evidence(list(evidence))
        with self._connect() as connection:
            run = connection.execute("SELECT current_plan_id, current_plan_version, status FROM runs WHERE id = ?", (run_id,)).fetchone()
            if run is None:
                raise ValueError(f"unknown run: {run_id}")
            if run["current_plan_id"] != document.plan_id or run["current_plan_version"] != document.parent_version:
                raise ValueError("plan revision parent does not match current version")
            if document.parent_version is None or document.version != document.parent_version + 1:
                raise ValueError("plan revision version must increment the current version by one")
            if run["status"] in {RunStatus.RUNNING.value, RunStatus.AWAITING_INPUT.value, RunStatus.CANCELLED.value}:
                raise ValueError("cannot revise a plan while the run is active")
            existing_rows = connection.execute("SELECT * FROM tasks WHERE run_id = ?", (run_id,)).fetchall()
            existing = {row["plan_task_id"] or row["id"]: row for row in existing_rows}
            desired = {task.id: task for task in document.tasks}
            for task_id, row in existing.items():
                if task_id not in desired:
                    if row["state"] == TaskStatus.SUCCEEDED.value:
                        raise ValueError("completed tasks must remain in a plan revision")
                    if row["state"] not in {TaskStatus.SUPERSEDED.value, TaskStatus.CANCELLED.value}:
                        connection.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?", (TaskStatus.SUPERSEDED.value, utc_now(), row["id"]))
            for task_id, task in desired.items():
                if task_id in existing:
                    row = existing[task_id]
                    physical_dependencies = [existing[dep]["id"] if dep in existing else f"{run_id[:8]}-{dep}" for dep in task.depends_on]
                    acceptance = json.dumps(task.acceptance, ensure_ascii=False, sort_keys=True) if isinstance(task.acceptance, dict) else task.acceptance
                    if row["state"] == TaskStatus.SUCCEEDED.value:
                        if (row["title"], row["prompt"], row["dependencies"], row["acceptance"]) != (task.title, task.prompt, json.dumps(physical_dependencies), acceptance):
                            raise ValueError("completed task definitions are immutable across revisions")
                    else:
                        state = TaskStatus.READY.value if not task.depends_on else TaskStatus.WAITING.value
                        connection.execute("UPDATE tasks SET title = ?, prompt = ?, state = ?, attempts = 0, result_path = NULL, last_error = NULL, dependencies = ?, acceptance = ?, updated_at = ? WHERE id = ?", (task.title, task.prompt, state, json.dumps(physical_dependencies), acceptance, utc_now(), row["id"]))
                else:
                    state = TaskStatus.READY.value if not task.depends_on else TaskStatus.WAITING.value
                    physical_id = f"{run_id[:8]}-{task_id}"
                    physical_dependencies = [existing[dep]["id"] if dep in existing else f"{run_id[:8]}-{dep}" for dep in task.depends_on]
                    connection.execute("INSERT INTO tasks(id, run_id, title, prompt, state, dependencies, acceptance, plan_task_id, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (physical_id, run_id, task.title, task.prompt, state, json.dumps(physical_dependencies), json.dumps(task.acceptance, ensure_ascii=False) if isinstance(task.acceptance, dict) else task.acceptance, task_id, utc_now(), utc_now()))
            connection.execute("INSERT INTO plan_revisions(plan_id, run_id, version, parent_version, document, created_at) VALUES(?, ?, ?, ?, ?, ?)", (document.plan_id, run_id, document.version, document.parent_version, json.dumps(document.to_dict(), ensure_ascii=False, sort_keys=True), utc_now()))
            connection.execute("UPDATE runs SET current_plan_id = ?, current_plan_version = ?, budget = ?, updated_at = ? WHERE id = ?", (document.plan_id, document.version, json.dumps(document.budget.to_dict()), utc_now(), run_id))
            connection.execute("UPDATE runs SET status = ?, updated_at = ? WHERE id = ?", (RunStatus.PENDING.value, utc_now(), run_id))
            self._append_event(connection, run_id, None, "plan_revision_created", {"plan_id": document.plan_id, "version": document.version, "parent_version": document.parent_version, "reason": reason, "evidence": list(evidence)})
            self._insert_decision(
                connection,
                run_id,
                PolicyDecision(
                    action,  # type: ignore[arg-type]
                    reason,
                    1.0,
                    plan_id=document.plan_id,
                    plan_version=document.version,
                    evidence=evidence,
                ),
            )
        return document

    def patch_plan(self, run_id: str, patch: PlanPatch) -> PlanDocument:
        current = self.get_current_plan(run_id)
        if current is None:
            raise ValueError("run has no current plan")
        document = apply_patch(current, patch)
        return self.commit_plan_revision(run_id, document, patch.reason, patch.evidence, action="patch_plan")

    @staticmethod
    def _validate_plan_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not tasks:
            raise ValueError("plan must contain at least one task")
        normalized: list[dict[str, Any]] = []
        ids: set[str] = set()
        for index, raw in enumerate(tasks):
            if not isinstance(raw, dict):
                raise TypeError(f"plan task {index} must be an object")
            task_id = str(raw.get("id", "")).strip()
            title = str(raw.get("title", task_id)).strip()
            prompt = str(raw.get("prompt", "")).strip()
            if not task_id or not prompt:
                raise ValueError(f"plan task {index} requires non-empty id and prompt")
            if task_id in {".", ".."} or Path(task_id).name != task_id or "\\" in task_id:
                raise ValueError(f"plan task id is not a safe path segment: {task_id!r}")
            if task_id in ids:
                raise ValueError(f"plan contains duplicate task id: {task_id}")
            ids.add(task_id)
            dependencies = raw.get("depends_on", raw.get("dependencies", []))
            if dependencies is None:
                dependencies = []
            if not isinstance(dependencies, list) or any(not isinstance(dep, str) for dep in dependencies):
                raise ValueError(f"dependencies for task {task_id} must be a string array")
            dependencies = [dep.strip() for dep in dependencies]
            if any(not dep for dep in dependencies):
                raise ValueError(f"dependencies for task {task_id} cannot contain empty IDs")
            acceptance = raw.get("acceptance")
            if acceptance is not None and not isinstance(acceptance, (str, dict)):
                raise ValueError(f"acceptance for task {task_id} must be a string or object")
            validate_acceptance(acceptance)
            normalized.append(
                {
                    "id": task_id,
                    "title": title or task_id,
                    "prompt": prompt,
                    "depends_on": dependencies,
                    "acceptance": json.dumps(acceptance, ensure_ascii=False, sort_keys=True)
                    if isinstance(acceptance, dict)
                    else acceptance,
                }
            )
        for item in normalized:
            unknown = set(item["depends_on"]) - ids
            if unknown:
                raise ValueError(
                    f"task {item['id']} references unknown dependencies: {', '.join(sorted(unknown))}"
                )
            if item["id"] in item["depends_on"]:
                raise ValueError(f"task {item['id']} cannot depend on itself")
        graph = {item["id"]: item["depends_on"] for item in normalized}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> None:
            if node in visiting:
                raise ValueError("plan dependencies contain a cycle")
            if node in visited:
                return
            visiting.add(node)
            for dependency in graph[node]:
                visit(dependency)
            visiting.remove(node)
            visited.add(node)

        for node in graph:
            visit(node)
        return normalized

    def get_run(self, run_id: str) -> Run | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        return Run(
            id=row["id"],
            goal=row["goal"],
            status=RunStatus(row["status"]),
            workspace=Path(row["workspace"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            runner_pid=row["runner_pid"],
            runner_pgid=row["runner_pgid"],
            current_plan_id=row["current_plan_id"],
            current_plan_version=row["current_plan_version"],
            route_domain=row["route_domain"],
            route_reason=row["route_reason"],
            route_confidence=row["route_confidence"],
            solver_profile=row["solver_profile"],
            evaluator_profile=row["evaluator_profile"],
            route_required_capabilities=tuple(json.loads(row["route_required_capabilities"] or "[]")),
            route_evidence=tuple(json.loads(row["route_evidence"] or "[]")),
            budget=BudgetSpec.from_dict(json.loads(row["budget"] or "{}")),
        )

    def get_run_by_workspace(self, workspace: str | Path) -> Run | None:
        """Return the newest run owning one canonical absolute workspace, if any."""
        normalized = str(Path(workspace).expanduser().resolve(strict=False))
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM runs WHERE workspace = ? ORDER BY created_at DESC LIMIT 1",
                (normalized,),
            ).fetchone()
        if row is None:
            return None
        return Run(
            id=row["id"],
            goal=row["goal"],
            status=RunStatus(row["status"]),
            workspace=Path(row["workspace"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            runner_pid=row["runner_pid"],
            runner_pgid=row["runner_pgid"],
            current_plan_id=row["current_plan_id"],
            current_plan_version=row["current_plan_version"],
            route_domain=row["route_domain"],
            route_reason=row["route_reason"],
            route_confidence=row["route_confidence"],
            solver_profile=row["solver_profile"],
            evaluator_profile=row["evaluator_profile"],
            route_required_capabilities=tuple(json.loads(row["route_required_capabilities"] or "[]")),
            route_evidence=tuple(json.loads(row["route_evidence"] or "[]")),
            budget=BudgetSpec.from_dict(json.loads(row["budget"] or "{}")),
        )

    def get_task(self, task_id: str) -> Task | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return self._task_from_row(row) if row else None

    def list_tasks(self, run_id: str) -> list[Task]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM tasks WHERE run_id = ? ORDER BY created_at, id", (run_id,)
            ).fetchall()
        return [self._task_from_row(row) for row in rows]

    def set_runner_process(self, run_id: str, pid: int | None, pgid: int | None) -> bool:
        """Persist the detached controller identity used by ``cancel``."""
        with self._connect() as connection:
            changed = connection.execute(
                "UPDATE runs SET runner_pid = ?, runner_pgid = ?, updated_at = ? WHERE id = ?",
                (pid, pgid, utc_now(), run_id),
            ).rowcount
        return changed == 1

    def claim_runner_process(self, run_id: str, pid: int, pgid: int) -> bool:
        """Register one admitted detached runner without replacing another owner.

        Callers hold the run's workspace execution lock and first resolve any stale
        process registrations. This conditional write also rejects cancellation or a
        terminal/waiting transition that won the race with process launch.
        """
        if any(type(value) is not int or value <= 1 for value in (pid, pgid)):
            raise ValueError("runner PID and PGID must be integers above 1")
        with self._connect() as connection:
            changed = connection.execute(
                "UPDATE runs SET runner_pid = ?, runner_pgid = ?, updated_at = ? "
                "WHERE id = ? AND runner_pid IS NULL AND runner_pgid IS NULL "
                "AND status IN (?, ?)",
                (pid, pgid, utc_now(), run_id, RunStatus.PENDING.value, RunStatus.RUNNING.value),
            ).rowcount
        return changed == 1

    def clear_runner_process(
        self, run_id: str, pid: int | None = None, pgid: int | None = None,
    ) -> bool:
        with self._connect() as connection:
            if pid is None:
                changed = connection.execute(
                    "UPDATE runs SET runner_pid = NULL, runner_pgid = NULL, updated_at = ? WHERE id = ?",
                    (utc_now(), run_id),
                ).rowcount
            elif pgid is not None:
                changed = connection.execute(
                    "UPDATE runs SET runner_pid = NULL, runner_pgid = NULL, updated_at = ? "
                    "WHERE id = ? AND runner_pid = ? AND runner_pgid = ?",
                    (utc_now(), run_id, pid, pgid),
                ).rowcount
            else:
                changed = connection.execute(
                    "UPDATE runs SET runner_pid = NULL, runner_pgid = NULL, updated_at = ? "
                    "WHERE id = ? AND runner_pid = ?",
                    (utc_now(), run_id, pid),
                ).rowcount
        return changed == 1

    def dependency_artifacts(self, task_id: str) -> list[dict[str, Any]]:
        """Return verified predecessor artifacts in deterministic order."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT run_id, dependencies FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            if row is None:
                raise ValueError(f"unknown task: {task_id}")
            dependencies = json.loads(row["dependencies"] or "[]")
            if not dependencies:
                return []
            placeholders = ",".join("?" for _ in dependencies)
            rows = connection.execute(
                f"SELECT id, result_path FROM tasks WHERE run_id = ? AND id IN ({placeholders}) "
                "AND state = ?",
                [row["run_id"], *dependencies, TaskStatus.SUCCEEDED.value],
            ).fetchall()
            by_id = {item["id"]: item for item in rows}
            artifacts: list[dict[str, Any]] = []
            for dependency in dependencies:
                predecessor = by_id.get(dependency)
                if predecessor is None:
                    continue
                artifact_rows = connection.execute(
                    "SELECT path, sha256, size, kind FROM artifacts WHERE run_id = ? AND task_id = ? "
                    "ORDER BY created_at, id",
                    (row["run_id"], dependency),
                ).fetchall()
                for artifact in artifact_rows:
                    artifacts.append(
                        {
                            "task_id": dependency,
                            "path": artifact["path"],
                            "sha256": artifact["sha256"],
                            "size": artifact["size"],
                            "kind": artifact["kind"],
                        }
                    )
                if not artifact_rows and predecessor["result_path"]:
                    artifacts.append({"task_id": dependency, "path": predecessor["result_path"]})
            return artifacts

    def next_task(self, run_id: str) -> Task | None:
        with self._connect() as connection:
            # Promote dependency-free work and block work whose verified prerequisites can no
            # longer succeed. This is intentionally done in the same transaction as the claim
            # lookup so two local controllers cannot observe stale readiness.
            pending = connection.execute(
                "SELECT id, dependencies, state, input_question FROM tasks "
                "WHERE run_id = ? AND state IN (?, ?)",
                (run_id, TaskStatus.PENDING.value, TaskStatus.WAITING.value),
            ).fetchall()
            for row in pending:
                # WAITING is also used for dependency edges. A task with an input question is
                # paused by the session and must remain untouched until ``answer`` is called.
                if row["state"] == TaskStatus.WAITING.value and _has_input_question(row["input_question"]):
                    continue
                dependencies = json.loads(row["dependencies"] or "[]")
                if not dependencies:
                    if row["state"] != TaskStatus.READY.value:
                        changed = connection.execute(
                            "UPDATE tasks SET state = ?, updated_at = ? WHERE id = ? AND state IN (?, ?)",
                            (TaskStatus.READY.value, utc_now(), row["id"], TaskStatus.PENDING.value, TaskStatus.WAITING.value),
                        ).rowcount
                        if changed:
                            self._append_event(connection, run_id, row["id"], "task_ready", {})
                    continue
                placeholders = ",".join("?" for _ in dependencies)
                states = connection.execute(
                    f"SELECT id, state FROM tasks WHERE run_id = ? AND id IN ({placeholders})",
                    [run_id, *dependencies],
                ).fetchall()
                dependency_states = {item["id"]: item["state"] for item in states}
                if any(
                    dependency_states.get(dep)
                    in {
                        TaskStatus.FAILED.value,
                        TaskStatus.BLOCKED.value,
                        TaskStatus.CANCELLED.value,
                        TaskStatus.SUPERSEDED.value,
                    }
                    for dep in dependencies
                ):
                    changed = connection.execute(
                        "UPDATE tasks SET state = ?, last_error = ?, updated_at = ? "
                        "WHERE id = ? AND state IN (?, ?)",
                        (
                            TaskStatus.BLOCKED.value,
                            "blocked because a dependency did not succeed",
                            utc_now(),
                            row["id"],
                            TaskStatus.PENDING.value,
                            TaskStatus.WAITING.value,
                        ),
                    ).rowcount
                    if changed:
                        self._append_event(
                            connection,
                            run_id,
                            row["id"],
                            "task_blocked",
                            {"dependencies": dependencies},
                        )
                elif all(dependency_states.get(dep) == TaskStatus.SUCCEEDED.value for dep in dependencies):
                    changed = connection.execute(
                        "UPDATE tasks SET state = ?, updated_at = ? WHERE id = ? AND state IN (?, ?)",
                        (
                            TaskStatus.READY.value,
                            utc_now(),
                            row["id"],
                            TaskStatus.PENDING.value,
                            TaskStatus.WAITING.value,
                        ),
                    ).rowcount
                    if changed:
                        self._append_event(
                            connection,
                            run_id,
                            row["id"],
                            "task_ready",
                            {"dependencies": dependencies},
                        )
            row = connection.execute(
                "SELECT * FROM tasks WHERE run_id = ? AND state IN (?, ?) "
                "AND orchestration = 0 "
                "ORDER BY created_at, id LIMIT 1",
                (
                    run_id,
                    TaskStatus.READY.value,
                    TaskStatus.UNCERTAIN.value,
                ),
            ).fetchone()
        return self._task_from_row(row) if row else None

    def claim_task(
        self, task_id: str, runtime: str, *, allow_orchestration: bool = False,
    ) -> Attempt | None:
        attempt_id = f"attempt-{uuid.uuid4().hex}"
        timestamp = utc_now()
        with self._connect() as connection:
            updated = connection.execute(
                "UPDATE tasks SET state = ?, attempts = attempts + 1, updated_at = ? "
                "WHERE id = ? AND state IN (?, ?, ?) "
                "AND (orchestration = 0 OR ? = 1)",
                (
                    TaskStatus.RUNNING.value,
                    timestamp,
                    task_id,
                    TaskStatus.PENDING.value,
                    TaskStatus.READY.value,
                    TaskStatus.UNCERTAIN.value,
                    int(allow_orchestration),
                ),
            ).rowcount
            if updated != 1:
                return None
            task = connection.execute("SELECT run_id, attempts FROM tasks WHERE id = ?", (task_id,)).fetchone()
            connection.execute(
                "UPDATE runs SET status = ?, updated_at = ? WHERE id = ? AND status = ?",
                (RunStatus.RUNNING.value, timestamp, task["run_id"], RunStatus.PENDING.value),
            )
            connection.execute(
                "INSERT INTO attempts(id, task_id, runtime, status, started_at, heartbeat_at) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                (attempt_id, task_id, runtime, "running", timestamp, timestamp),
            )
            self._append_event(
                connection,
                task["run_id"],
                task_id,
                "task_claimed",
                {"attempt_id": attempt_id, "runtime": runtime, "attempt": task["attempts"]},
            )
            row = connection.execute("SELECT * FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
        return self._attempt_from_row(row)

    def ensure_orchestration_task(
        self, run_id: str, *, title: str, prompt: str,
    ) -> Task:
        """Create or reuse the durable task coordinating an automatic solve handoff.

        Orchestration tasks are intentionally outside the ordinary scheduler DAG.  They keep the
        parent run active while a linked evolution child and its delivery are in progress, and
        callers must explicitly claim them with ``allow_orchestration=True``.
        """
        if not isinstance(title, str) or not title.strip():
            raise ValueError("orchestration task title must be non-empty")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("orchestration task prompt must be non-empty")
        timestamp = utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute("SELECT id, status FROM runs WHERE id = ?", (run_id,)).fetchone()
            if run is None:
                raise ValueError(f"unknown run: {run_id}")
            existing = connection.execute(
                "SELECT * FROM tasks WHERE run_id = ? AND orchestration = 1 "
                "ORDER BY created_at, id LIMIT 1",
                (run_id,),
            ).fetchone()
            if existing is not None:
                return self._task_from_row(existing)
            if run["status"] in {
                RunStatus.SUCCEEDED.value, RunStatus.FAILED.value, RunStatus.CANCELLED.value,
            }:
                raise ValueError("cannot add orchestration to a terminal run")
            task_id = f"orchestration-{uuid.uuid4().hex}"
            connection.execute(
                "INSERT INTO tasks(id, run_id, title, prompt, state, dependencies, acceptance, "
                "orchestration, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    task_id,
                    run_id,
                    title.strip(),
                    prompt.strip(),
                    TaskStatus.READY.value,
                    "[]",
                    None,
                    1,
                    timestamp,
                    timestamp,
                ),
            )
            self._append_event(
                connection,
                run_id,
                task_id,
                "task_created",
                {"title": title.strip(), "orchestration": True},
            )
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return self._task_from_row(row)  # type: ignore[arg-type]

    def active_attempt(self, task_id: str) -> Attempt | None:
        """Return the currently running attempt for a task, if one exists."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM attempts WHERE task_id = ? AND status = ? "
                "ORDER BY started_at DESC, id DESC LIMIT 1",
                (task_id, "running"),
            ).fetchone()
        return self._attempt_from_row(row) if row else None

    def claim_orchestration_task(self, task_id: str, runtime: str) -> Attempt | None:
        """Claim one automatic-solve orchestration task explicitly."""
        task = self.get_task(task_id)
        if task is None or not task.orchestration:
            raise ValueError("task is not an orchestration task")
        active = self.active_attempt(task_id)
        if active is not None:
            return active
        return self.claim_task(task_id, runtime, allow_orchestration=True)

    def await_input(
        self,
        task_id: str,
        attempt_id: str,
        request_path: str,
        question: str,
        options: list[str] | tuple[str, ...] = (),
    ) -> bool:
        """Pause a running task until a user/parent Agent supplies an answer."""
        if not question.strip() or len(question.encode("utf-8")) > 8_000:
            raise ValueError("input question must be non-empty and at most 8 KiB")
        if len(options) > 10 or any(len(str(option).encode("utf-8")) > 200 for option in options):
            raise ValueError("input options exceed the limit")
        request = Path(request_path)
        if request.is_absolute() or ".." in request.parts:
            raise ValueError("input request path must be run-relative")
        timestamp = utc_now()
        normalized_options = [str(option) for option in options]
        with self._connect() as connection:
            task = connection.execute(
                "SELECT run_id FROM tasks WHERE id = ? AND state = ?",
                (task_id, TaskStatus.RUNNING.value),
            ).fetchone()
            if task is None:
                return False
            updated = connection.execute(
                "UPDATE tasks SET state = ?, input_question = ?, input_options = ?, "
                "input_answer_path = NULL, last_error = NULL, updated_at = ? "
                "WHERE id = ? AND state = ?",
                (
                    TaskStatus.WAITING.value,
                    question,
                    json.dumps(normalized_options, ensure_ascii=False),
                    timestamp,
                    task_id,
                    TaskStatus.RUNNING.value,
                ),
            ).rowcount
            if updated != 1:
                return False
            connection.execute(
                "UPDATE attempts SET status = ?, finished_at = ?, heartbeat_at = ?, error = NULL "
                "WHERE id = ? AND status = ?",
                ("awaiting_input", timestamp, timestamp, attempt_id, "running"),
            )
            connection.execute(
                "UPDATE runs SET status = ?, updated_at = ? WHERE id = ? AND status != ?",
                (RunStatus.AWAITING_INPUT.value, timestamp, task["run_id"], RunStatus.CANCELLED.value),
            )
            self._append_event(
                connection,
                task["run_id"],
                task_id,
                "input_required",
                {
                    "attempt_id": attempt_id,
                    "request_path": request_path,
                    "question_bytes": len(question.encode("utf-8")),
                    "options_count": len(normalized_options),
                },
            )
        return True

    def pending_input(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = self._pending_input_row(connection, run_id)
        if row is None:
            return None
        return {
            "run_id": run_id,
            "task_id": row["id"],
            "question": row["input_question"],
            "options": json.loads(row["input_options"] or "[]"),
            "request_path": self._input_request_path(run_id, row["id"]),
            "answer_path": row["input_answer_path"],
        }

    def answer_input(self, run_id: str, answer_path: str) -> str | None:
        """Attach an answer to a real question; dependency waits cannot be answered."""
        path = Path(answer_path)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("input answer path must be run-relative")
        timestamp = utc_now()
        with self._connect() as connection:
            row = self._pending_input_row(connection, run_id)
            if row is None:
                return None
            task_id = row["id"]
            updated = connection.execute(
                "UPDATE tasks SET state = ?, input_answer_path = ?, updated_at = ? "
                "WHERE id = ? AND state = ? AND input_question = ?",
                (TaskStatus.READY.value, answer_path, timestamp, task_id,
                 TaskStatus.WAITING.value, row["input_question"]),
            ).rowcount
            if updated != 1:
                return None
            connection.execute(
                "UPDATE runs SET status = ?, updated_at = ? WHERE id = ? AND status = ?",
                (RunStatus.PENDING.value, timestamp, run_id, RunStatus.AWAITING_INPUT.value),
            )
            self._append_event(
                connection,
                run_id,
                task_id,
                "input_answered",
                {"answer_path": answer_path},
            )
        return task_id

    @staticmethod
    def _pending_input_row(connection: sqlite3.Connection, run_id: str) -> sqlite3.Row | None:
        rows = connection.execute(
            "SELECT id, input_question, input_options, input_answer_path FROM tasks "
            "WHERE run_id = ? AND state = ? ORDER BY created_at, id",
            (run_id, TaskStatus.WAITING.value),
        )
        return next((row for row in rows if _has_input_question(row["input_question"])), None)

    def _input_request_path(self, run_id: str, task_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT path FROM artifacts WHERE run_id = ? AND task_id = ? AND kind = ? "
                "ORDER BY created_at DESC, id DESC LIMIT 1",
                (run_id, task_id, "input"),
            ).fetchone()
        return row["path"] if row else None

    def finish_task(
        self,
        task_id: str,
        attempt_id: str,
        success: bool,
        result_path: str | None = None,
        error: str | None = None,
    ) -> bool:
        timestamp = utc_now()
        new_state = TaskStatus.SUCCEEDED.value if success else TaskStatus.FAILED.value
        attempt_state = "succeeded" if success else "failed"
        with self._connect() as connection:
            task = connection.execute("SELECT run_id, state FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if task is None:
                raise ValueError(f"unknown task: {task_id}")
            updated = connection.execute(
                "UPDATE tasks SET state = ?, result_path = ?, last_error = ?, updated_at = ? "
                "WHERE id = ? AND state = ?",
                (new_state, result_path, error, timestamp, task_id, TaskStatus.RUNNING.value),
            ).rowcount
            if updated != 1:
                return False
            connection.execute(
                "UPDATE attempts SET status = ?, finished_at = ?, heartbeat_at = ?, error = ? WHERE id = ?",
                (attempt_state, timestamp, timestamp, error, attempt_id),
            )
            self._append_event(
                connection,
                task["run_id"],
                task_id,
                "task_succeeded" if success else "task_failed",
                {"attempt_id": attempt_id, "result_path": result_path, "error": error},
            )
        return True

    def retry_task(self, task_id: str, attempt_id: str, error: str) -> bool:
        timestamp = utc_now()
        with self._connect() as connection:
            task = connection.execute("SELECT run_id, state FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if task is None:
                raise ValueError(f"unknown task: {task_id}")
            updated = connection.execute(
                "UPDATE tasks SET state = ?, last_error = ?, updated_at = ? "
                "WHERE id = ? AND state = ?",
                (TaskStatus.READY.value, error, timestamp, task_id, TaskStatus.RUNNING.value),
            ).rowcount
            if updated != 1:
                return False
            connection.execute(
                "UPDATE attempts SET status = ?, finished_at = ?, heartbeat_at = ?, error = ? WHERE id = ?",
                ("failed", timestamp, timestamp, error, attempt_id),
            )
            self._append_event(
                connection,
                task["run_id"],
                task_id,
                "task_retry_scheduled",
                {"attempt_id": attempt_id, "error": error},
            )
        return True

    def supersede_pending_tasks(self, run_id: str, reason: str) -> int:
        """Mark unstarted tasks as superseded and retain an audit event for each one.

        This is used by an explicit orchestration handoff (for example, conversational intake to
        evolution) when a generated plan is intentionally replaced before any of its work starts.
        Running or uncertain tasks are never touched; callers must recover or finish those through
        the normal lifecycle instead.
        """
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("supersede reason must be non-empty")
        reason = reason.strip()[-2_000:]
        timestamp = utc_now()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id FROM tasks WHERE run_id = ? AND plan_task_id IS NOT NULL "
                "AND state IN (?, ?, ?)",
                (
                    run_id,
                    TaskStatus.PENDING.value,
                    TaskStatus.READY.value,
                    TaskStatus.WAITING.value,
                ),
            ).fetchall()
            for row in rows:
                changed = connection.execute(
                    "UPDATE tasks SET state = ?, last_error = ?, updated_at = ? "
                    "WHERE id = ? AND plan_task_id IS NOT NULL AND state IN (?, ?, ?)",
                    (
                        TaskStatus.SUPERSEDED.value,
                        reason,
                        timestamp,
                        row["id"],
                        TaskStatus.PENDING.value,
                        TaskStatus.READY.value,
                        TaskStatus.WAITING.value,
                    ),
                ).rowcount
                if changed:
                    self._append_event(
                        connection,
                        run_id,
                        row["id"],
                        "task_superseded",
                        {"reason": reason},
                    )
        return len(rows)

    def set_attempt_process(self, attempt_id: str, pid: int | None, pgid: int | None) -> bool:
        with self._connect() as connection:
            changed = connection.execute(
                "UPDATE attempts SET pid = ?, pgid = ?, heartbeat_at = ? WHERE id = ?",
                (pid, pgid, utc_now(), attempt_id),
            ).rowcount
        return changed == 1

    def get_attempt(self, attempt_id: str) -> Attempt | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
        return self._attempt_from_row(row) if row else None

    def clear_attempt_process(
        self, attempt_id: str, pid: int | None = None, pgid: int | None = None,
    ) -> bool:
        with self._connect() as connection:
            if pid is None:
                changed = connection.execute(
                    "UPDATE attempts SET pid = NULL, pgid = NULL, heartbeat_at = ? WHERE id = ?",
                    (utc_now(), attempt_id),
                ).rowcount
            elif pgid is not None:
                changed = connection.execute(
                    "UPDATE attempts SET pid = NULL, pgid = NULL, heartbeat_at = ? "
                    "WHERE id = ? AND pid = ? AND pgid = ?",
                    (utc_now(), attempt_id, pid, pgid),
                ).rowcount
            else:
                changed = connection.execute(
                    "UPDATE attempts SET pid = NULL, pgid = NULL, heartbeat_at = ? "
                    "WHERE id = ? AND pid = ?",
                    (utc_now(), attempt_id, pid),
                ).rowcount
        return changed == 1

    def list_attempt_processes(self, run_id: str) -> list[dict[str, object]]:
        """Return retained process registrations, including incomplete identities.

        Recovery must see partial registrations so it can refuse unsafe admission;
        cancellation callers still require a complete verified identity before signalling.
        """
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT attempts.id, attempts.task_id, attempts.pid, attempts.pgid "
                "FROM attempts JOIN tasks ON tasks.id = attempts.task_id "
                "WHERE tasks.run_id = ? "
                "AND (attempts.pid IS NOT NULL OR attempts.pgid IS NOT NULL) "
                "ORDER BY attempts.started_at, attempts.id",
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def recover_running(self, run_id: str) -> int:
        timestamp = utc_now()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id FROM tasks WHERE run_id = ? AND state = ?",
                (run_id, TaskStatus.RUNNING.value),
            ).fetchall()
            for row in rows:
                task_id = row["id"]
                connection.execute(
                    "UPDATE tasks SET state = ?, updated_at = ?, last_error = ? WHERE id = ?",
                    (
                        TaskStatus.UNCERTAIN.value,
                        timestamp,
                        "controller restarted while task was running",
                        task_id,
                    ),
                )
                connection.execute(
                    "UPDATE attempts SET status = ?, heartbeat_at = ?, error = ? "
                    "WHERE task_id = ? AND status = ?",
                    (
                        "uncertain",
                        timestamp,
                        "controller restarted before attempt completed",
                        task_id,
                        "running",
                    ),
                )
                self._append_event(
                    connection,
                    run_id,
                    task_id,
                    "task_recovered",
                    {"reason": "controller_restart"},
                )
        return len(rows)

    def settle_run(self, run_id: str) -> Run | None:
        timestamp = utc_now()
        with self._connect() as connection:
            # Read task states and commit the derived run state under one writer lock. A
            # concurrent budget failure must not be overwritten using a stale task snapshot.
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
            if current is None:
                return None
            if current["status"] == RunStatus.FAILED.value and connection.execute(
                "SELECT 1 FROM events WHERE id = ? AND run_id = ? AND type = 'budget_exceeded'",
                (f"event-budget-solve_wall_timeout-{run_id}", run_id),
            ).fetchone() is not None:
                return self.get_run(run_id)
            rows = connection.execute(
                "SELECT state, input_question FROM tasks WHERE run_id = ?", (run_id,),
            ).fetchall()
            if not rows:
                return self.get_run(run_id)
            states = {row["state"] for row in rows}
            if TaskStatus.FAILED.value in states or TaskStatus.BLOCKED.value in states:
                status = RunStatus.FAILED.value
            elif states and states.issubset({TaskStatus.SUCCEEDED.value, TaskStatus.SUPERSEDED.value}) and TaskStatus.SUCCEEDED.value in states:
                status = RunStatus.SUCCEEDED.value
            elif any(row["state"] == TaskStatus.WAITING.value
                     and _has_input_question(row["input_question"]) for row in rows):
                status = RunStatus.AWAITING_INPUT.value
            elif TaskStatus.CANCELLED.value in states:
                status = RunStatus.CANCELLED.value
            else:
                status = RunStatus.RUNNING.value
            connection.execute(
                "UPDATE runs SET status = ?, updated_at = ? WHERE id = ? AND status != ?",
                (status, timestamp, run_id, RunStatus.CANCELLED.value),
            )
            if (
                status in {RunStatus.SUCCEEDED.value, RunStatus.FAILED.value}
                and current["status"] != status
            ):
                self._append_event(connection, run_id, None, f"run_{status}", {})
        return self.get_run(run_id)

    def cancel_run(self, run_id: str) -> bool:
        timestamp = utc_now()
        with self._connect() as connection:
            run = connection.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
            if run is None:
                return False
            changed = connection.execute(
                "UPDATE runs SET status = ?, updated_at = ? WHERE id = ? AND status NOT IN (?, ?, ?)",
                (
                    RunStatus.CANCELLED.value,
                    timestamp,
                    run_id,
                    RunStatus.SUCCEEDED.value,
                    RunStatus.FAILED.value,
                    RunStatus.CANCELLED.value,
                ),
            ).rowcount
            if not changed:
                return False
            task_rows = connection.execute(
                "SELECT id FROM tasks WHERE run_id = ? AND state NOT IN (?, ?, ?, ?)",
                (
                    run_id,
                    TaskStatus.SUCCEEDED.value,
                    TaskStatus.FAILED.value,
                    TaskStatus.CANCELLED.value,
                    TaskStatus.SUPERSEDED.value,
                ),
            ).fetchall()
            changed_tasks = connection.execute(
                "UPDATE tasks SET state = ?, updated_at = ? WHERE run_id = ? AND state NOT IN (?, ?, ?, ?)",
                (
                    TaskStatus.CANCELLED.value,
                    timestamp,
                    run_id,
                    TaskStatus.SUCCEEDED.value,
                    TaskStatus.FAILED.value,
                    TaskStatus.CANCELLED.value,
                    TaskStatus.SUPERSEDED.value,
                ),
            ).rowcount
            connection.execute(
                "UPDATE attempts SET status = ?, finished_at = ? WHERE task_id IN "
                "(SELECT id FROM tasks WHERE run_id = ?) AND status = ?",
                ("cancelled", timestamp, run_id, "running"),
            )
            self._append_event(connection, run_id, None, "run_cancelled", {})
            if changed_tasks:
                for row in task_rows:
                    self._append_event(
                        connection,
                        run_id,
                        row["id"],
                        "task_cancelled",
                        {"reason": "run_cancelled"},
                    )
        return True

    def add_artifact(
        self,
        run_id: str,
        task_id: str,
        path: str,
        sha256: str,
        size: int,
        kind: str = "result",
        *,
        artifact_id: str | None = None,
    ) -> str:
        artifact_id = artifact_id or f"artifact-{uuid.uuid4().hex}"
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO artifacts(id, run_id, task_id, path, sha256, size, kind, created_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                (artifact_id, run_id, task_id, path, sha256, size, kind, utc_now()),
            )
            self._append_event(
                connection,
                run_id,
                task_id,
                "artifact_recorded",
                {"artifact_id": artifact_id, "path": path, "sha256": sha256, "size": size},
            )
        return artifact_id

    @staticmethod
    def _output_publication_manifest(
        run_id: str,
        evolution_run_id: str,
        outputs: list[dict[str, Any]],
        journal_sha256: str,
    ) -> list[dict[str, Any]]:
        """Validate and detach the journal projection without touching output files."""
        error = "output_publication_ledger_mismatch"
        if (
            any(not isinstance(value, str) or not value or "\0" in value
                for value in (run_id, evolution_run_id))
            or not isinstance(journal_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", journal_sha256) is None
            or not isinstance(outputs, list)
            or not 1 <= len(outputs) <= MAX_OUTPUTS
        ):
            raise ValueError(error)
        keys = {"artifact_id", "path", "format", "fields", "required", "size", "sha256"}
        paths: set[str] = set()
        ids: set[str] = set()
        for item in outputs:
            if not isinstance(item, dict) or set(item) != keys:
                raise ValueError(error)
            artifact_id, digest, size = item["artifact_id"], item["sha256"], item["size"]
            if (
                not isinstance(artifact_id, str) or not artifact_id or "\0" in artifact_id
                or not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None
                or type(size) is not int or not 0 <= size <= 256 * 1024
            ):
                raise ValueError(error)
            try:
                metadata = {key: item[key] for key in ("path", "format", "fields", "required")}
                spec = OutputSpec.from_dict(metadata)
                if spec.to_dict() != metadata:
                    raise ValueError(error)
            except (TypeError, ValueError):
                raise ValueError(error) from None
            if spec.path in paths or artifact_id in ids:
                raise ValueError(error)
            paths.add(spec.path)
            ids.add(artifact_id)
        return json.loads(json.dumps(outputs, allow_nan=False))

    @staticmethod
    def _output_publication_artifact_id(run_id: str, evolution_run_id: str, path: str) -> str:
        return "artifact-output-publication-" + hashlib.sha256(
            f"{run_id}\0{evolution_run_id}\0{path}".encode()
        ).hexdigest()

    @staticmethod
    def _output_publication_event_payload(raw: str) -> dict[str, Any]:
        def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("output_publication_ledger_mismatch")
                result[key] = value
            return result

        def reject_number(value: str) -> Any:
            raise ValueError("output_publication_ledger_mismatch")

        payload = json.loads(
            raw, object_pairs_hook=unique_object,
            parse_constant=reject_number, parse_float=reject_number,
        )
        if not isinstance(payload, dict):
            raise TypeError("output_publication_ledger_mismatch")
        return payload

    def _inspect_output_publication(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        evolution_run_id: str,
        outputs: list[dict[str, Any]],
        journal_sha256: str,
        task_id: str | None = None,
    ) -> tuple[bool, list[dict[str, Any]]]:
        """Inspect the complete batch in the caller's one SQLite snapshot."""
        error = "output_publication_ledger_mismatch"
        if connection.execute("SELECT 1 FROM runs WHERE id = ?", (run_id,)).fetchone() is None:
            raise ValueError(error)
        task_ids = {
            row["id"] for row in connection.execute("SELECT id FROM tasks WHERE run_id = ?", (run_id,))
        }
        if task_id is not None and task_id not in task_ids:
            raise ValueError(error)
        suffix = hashlib.sha256(f"{run_id}\0{evolution_run_id}".encode()).hexdigest()
        expected_events = {
            "event-evolved-outputs-promoted-" + suffix: (
                "evolved_outputs_promoted", {"evolution_run_id": evolution_run_id, "outputs": outputs},
            ),
            "event-output-publication-committed-" + suffix: (
                "output_publication_committed",
                {"evolution_run_id": evolution_run_id, "journal_sha256": journal_sha256},
            ),
        }
        event_rows = connection.execute(
            "SELECT id, run_id, task_id, type, payload FROM events WHERE id IN (?, ?) "
            "OR (run_id = ? AND type IN (?, ?))",
            (*expected_events, run_id, "evolved_outputs_promoted", "output_publication_committed"),
        ).fetchall()
        matching_events: list[tuple[sqlite3.Row, dict[str, Any]]] = []
        for row in event_rows:
            payload = self._output_publication_event_payload(row["payload"])
            if row["id"] in expected_events or payload.get("evolution_run_id") == evolution_run_id:
                matching_events.append((row, payload))
        committed = bool(matching_events)
        if committed:
            if len(matching_events) != 2:
                raise ValueError(error)
            owner = matching_events[0][0]["task_id"]
            if owner not in task_ids or (task_id is not None and owner != task_id):
                raise ValueError(error)
            for row, payload in matching_events:
                expected = expected_events.get(row["id"])
                if (
                    expected is None or row["run_id"] != run_id or row["task_id"] != owner
                    or row["type"] != expected[0]
                    or json.dumps(payload, sort_keys=True) != json.dumps(expected[1], sort_keys=True)
                ):
                    raise ValueError(error)
            task_id = owner

        artifact_events = connection.execute(
            "SELECT id, run_id, task_id, type, payload FROM events "
            "WHERE run_id = ? AND type = 'artifact_recorded'", (run_id,),
        ).fetchall()
        parsed_artifact_events = [
            (row, self._output_publication_event_payload(row["payload"])) for row in artifact_events
        ]
        missing: list[dict[str, Any]] = []
        for item in outputs:
            reserved_id = self._output_publication_artifact_id(run_id, evolution_run_id, item["path"])
            rows = connection.execute(
                "SELECT id, run_id, task_id, path, sha256, size, kind FROM artifacts "
                "WHERE id = ? OR (run_id = ? AND path = ? AND kind = 'output')",
                (item["artifact_id"], run_id, item["path"]),
            ).fetchall()
            if not rows:
                if committed or item["artifact_id"] != reserved_id:
                    raise ValueError(error)
                missing.append(item)
            elif len(rows) != 1:
                raise ValueError(error)
            else:
                row = rows[0]
                if (
                    row["id"] != item["artifact_id"] or row["run_id"] != run_id
                    or row["task_id"] not in task_ids or row["kind"] != "output"
                    or row["path"] != item["path"] or row["sha256"] != item["sha256"]
                    or type(row["size"]) is not int or row["size"] != item["size"]
                    or (item["artifact_id"] == reserved_id
                        and (not committed or row["task_id"] != task_id))
                ):
                    raise ValueError(error)
            if item["artifact_id"] == reserved_id:
                records = [
                    (row, payload) for row, payload in parsed_artifact_events
                    if payload.get("artifact_id") == reserved_id
                ]
                expected_payload = {
                    key: item[key] for key in ("artifact_id", "path", "sha256", "size")
                }
                if (not committed and records) or (committed and (
                    len(records) != 1 or records[0][0]["task_id"] != task_id
                    or json.dumps(records[0][1], sort_keys=True)
                    != json.dumps(expected_payload, sort_keys=True)
                )):
                    raise ValueError(error)
        return committed, missing

    def has_output_publication(self, run_id: str, evolution_run_id: str) -> bool:
        """Detect commit evidence when its journal is missing, without treating it as valid.

        A matching reserved event ID is evidence even if its type or owner was corrupted. This
        probe must never downgrade a recorded publication to a legacy journal-free output.
        """
        try:
            if any(
                not isinstance(value, str) or not value or "\0" in value
                for value in (run_id, evolution_run_id)
            ):
                raise ValueError("output_publication_ledger_mismatch")
            event_id = "event-output-publication-committed-" + hashlib.sha256(
                f"{run_id}\0{evolution_run_id}".encode()
            ).hexdigest()
            with closing(sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True, timeout=30)) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("BEGIN")
                rows = connection.execute(
                    "SELECT id, payload FROM events WHERE id = ? "
                    "OR (run_id = ? AND type = 'output_publication_committed')",
                    (event_id, run_id),
                ).fetchall()
                if any(row["id"] == event_id for row in rows):
                    return True
                found = False
                for row in rows:
                    payload = self._output_publication_event_payload(row["payload"])
                    if (
                        set(payload) != {"evolution_run_id", "journal_sha256"}
                        or not isinstance(payload["evolution_run_id"], str)
                        or not payload["evolution_run_id"] or "\0" in payload["evolution_run_id"]
                        or not isinstance(payload["journal_sha256"], str)
                        or re.fullmatch(r"[0-9a-f]{64}", payload["journal_sha256"]) is None
                    ):
                        raise ValueError("output_publication_ledger_mismatch")
                    found = found or payload["evolution_run_id"] == evolution_run_id
                return found
        except Exception:  # noqa: BLE001 - an unreadable ledger cannot prove journal-free history.
            raise ValueError("output_publication_ledger_mismatch") from None

    def output_publication_committed(
        self,
        run_id: str,
        evolution_run_id: str,
        outputs: list[dict[str, Any]],
        *,
        owner_task_id: str,
        journal_sha256: str,
    ) -> bool:
        """Read exact commit evidence without creating a database or output files."""
        try:
            manifest = self._output_publication_manifest(run_id, evolution_run_id, outputs, journal_sha256)
            if not isinstance(owner_task_id, str) or not owner_task_id:
                raise ValueError("output_publication_ledger_mismatch")
            with closing(sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True, timeout=30)) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("BEGIN")
                return self._inspect_output_publication(
                    connection, run_id, evolution_run_id, manifest, journal_sha256,
                    task_id=owner_task_id,
                )[0]
        except Exception:  # noqa: BLE001 - recovery must expose only a safe, fail-closed code.
            raise ValueError("output_publication_ledger_mismatch") from None

    def commit_output_publication(
        self,
        run_id: str,
        task_id: str,
        evolution_run_id: str,
        outputs: list[dict[str, Any]],
        *,
        journal_sha256: str,
        max_artifact_bytes: int,
    ) -> None:
        """Commit every output row and its evidence together, or roll back the whole batch."""
        safe_errors = {
            "output_publication_ledger_mismatch", "output_publication_budget_exceeded",
            "output_publication_parent_terminal",
        }
        try:
            manifest = self._output_publication_manifest(run_id, evolution_run_id, outputs, journal_sha256)
            if not isinstance(task_id, str) or not task_id:
                raise ValueError("output_publication_ledger_mismatch")
            if type(max_artifact_bytes) is not int or max_artifact_bytes < 1:
                raise ValueError("output_publication_budget_exceeded")
            with closing(self._connect()) as connection, connection:
                connection.execute("PRAGMA synchronous = FULL")
                connection.execute("BEGIN IMMEDIATE")
                committed, missing = self._inspect_output_publication(
                    connection, run_id, evolution_run_id, manifest, journal_sha256, task_id,
                )
                if committed:
                    return
                parent = connection.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
                if parent is not None and parent["status"] in {RunStatus.FAILED.value, RunStatus.CANCELLED.value}:
                    # Only new automatic handoffs keep parent terminal state authoritative
                    # through delivery. Legacy publication retains its existing semantics.
                    requests = connection.execute(
                        "SELECT payload FROM events WHERE run_id = ? AND type = 'evolution_requested'",
                        (run_id,),
                    )
                    for row in requests:
                        request = json.loads(row["payload"])
                        if (isinstance(request, dict) and request.get("bundle_mode") == "compiled"
                                and request.get("automatic_lifecycle_version") == 1):
                            raise ValueError("output_publication_parent_terminal")
                sizes = [row["size"] for row in connection.execute(
                    "SELECT size FROM artifacts WHERE run_id = ?", (run_id,),
                )]
                if any(type(size) is not int or size < 0 for size in sizes):
                    raise ValueError("output_publication_ledger_mismatch")
                if sum(sizes) + sum(item["size"] for item in missing) > max_artifact_bytes:
                    raise ValueError("output_publication_budget_exceeded")
                for item in missing:
                    connection.execute(
                        "INSERT INTO artifacts(id, run_id, task_id, path, sha256, size, kind, created_at) "
                        "VALUES(?, ?, ?, ?, ?, ?, 'output', ?)",
                        (item["artifact_id"], run_id, task_id, item["path"], item["sha256"], item["size"], utc_now()),
                    )
                    if not self._append_event(
                        connection, run_id, task_id, "artifact_recorded",
                        {key: item[key] for key in ("artifact_id", "path", "sha256", "size")},
                    ):
                        raise ValueError("output_publication_ledger_mismatch")
                suffix = hashlib.sha256(f"{run_id}\0{evolution_run_id}".encode()).hexdigest()
                for event_type, event_id, payload in (
                    ("evolved_outputs_promoted", "event-evolved-outputs-promoted-" + suffix,
                     {"evolution_run_id": evolution_run_id, "outputs": manifest}),
                    ("output_publication_committed", "event-output-publication-committed-" + suffix,
                     {"evolution_run_id": evolution_run_id, "journal_sha256": journal_sha256}),
                ):
                    if not self._append_event(connection, run_id, task_id, event_type, payload, event_id):
                        raise ValueError("output_publication_ledger_mismatch")
        except Exception as exc:  # noqa: BLE001 - rollback also covers injected/storage failures.
            code = str(exc) if isinstance(exc, ValueError) and str(exc) in safe_errors else "output_publication_commit_failed"
            raise ValueError(code) from None

    @staticmethod
    def _materialization_publication_json(raw: str | bytes) -> dict[str, Any]:
        """Strict event JSON, including finite floating-point validation measurements."""
        def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("materialization_publication_ledger_mismatch")
                result[key] = value
            return result

        def reject_constant(value: str) -> Any:
            raise ValueError("materialization_publication_ledger_mismatch")

        result = json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant)
        if not isinstance(result, dict):
            raise TypeError("materialization_publication_ledger_mismatch")
        # json.loads accepts an overflowing exponent as inf. Canonical encoding rejects that
        # case while preserving ordinary finite floats in validation details.
        json.dumps(result, allow_nan=False)
        return result

    @staticmethod
    def _materialization_publication_suffix(parent_id: str, child_id: str) -> str:
        if parent_id == child_id or any(
            not isinstance(value, str) or not value or "\0" in value
            for value in (parent_id, child_id)
        ):
            raise ValueError("materialization_publication_ledger_mismatch")
        return hashlib.sha256(f"{parent_id}\0{child_id}".encode()).hexdigest()

    def _materialization_publication_manifest(
        self, parent_id: str, child_id: str, task_id: str,
        payload: dict[str, Any], journal_sha256: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        error = "materialization_publication_ledger_mismatch"
        suffix = self._materialization_publication_suffix(parent_id, child_id)
        keys = {
            "schema_version", "status", "parent_run_id", "evolution_run_id",
            "contract_sha256", "candidate_id", "candidate_path", "candidate_sha256",
            "attempt_path", "execution", "validation", "outputs", "error",
        }
        if (
            not isinstance(task_id, str) or not task_id or "\0" in task_id
            or not isinstance(journal_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", journal_sha256) is None
            or not isinstance(payload, dict) or set(payload) != keys
            or payload["schema_version"] != "1" or payload["status"] not in {"succeeded", "failed"}
            or payload["parent_run_id"] != parent_id or payload["evolution_run_id"] != child_id
            or not isinstance(payload["execution"], dict) or not isinstance(payload["validation"], dict)
            or not isinstance(payload["outputs"], list)
            or (payload["error"] is not None and not isinstance(payload["error"], str))
        ):
            raise ValueError(error)
        if any(
            not isinstance(payload[key], str) or re.fullmatch(r"[0-9a-f]{64}", payload[key]) is None
            for key in ("contract_sha256", "candidate_sha256")
        ) or not isinstance(payload["candidate_id"], str) or re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", payload["candidate_id"]
        ) is None:
            raise ValueError(error)
        for key in ("candidate_path", "attempt_path"):
            value = payload[key]
            if (
                not isinstance(value, str) or not value or "\0" in value or "\\" in value
                or Path(value).is_absolute() or Path(value).as_posix() != value
                or any(part in {"", ".", ".."} for part in value.split("/"))
            ):
                raise ValueError(error)
        if payload["attempt_path"] != (
            f"evolution/materialization/{payload['candidate_id']}-{payload['candidate_sha256'][:12]}"
        ):
            raise ValueError(error)
        content = (json.dumps(
            payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False,
        ) + "\n").encode("utf-8")
        if len(content) > 64 * 1024:
            raise ValueError(error)
        detached = self._materialization_publication_json(content)
        identity = {
            "parent_run_id": parent_id, "evolution_run_id": child_id,
            "owner_task_id": task_id, "journal_sha256": journal_sha256,
            "artifact_id": "artifact-materialization-publication-" + suffix,
            "path": "evolution/materialization/result.json",
            "sha256": hashlib.sha256(content).hexdigest(), "size": len(content),
        }
        return detached, identity

    @staticmethod
    def _materialization_publication_events(
        parent_id: str, child_id: str, task_id: str,
        payload: dict[str, Any], identity: dict[str, Any],
    ) -> dict[str, tuple[str, str | None, str, dict[str, Any]]]:
        suffix = hashlib.sha256(f"{parent_id}\0{child_id}".encode()).hexdigest()
        parent_payload = {
            key: payload[key] for key in (
                "status", "evolution_run_id", "contract_sha256", "candidate_id",
                "candidate_path", "candidate_sha256", "attempt_path", "execution",
                "validation", "outputs", "error",
            )
        }
        return {
            "event-materialization-publication-prepared-" + suffix: (
                child_id, task_id, "materialization_publication_prepared", identity,
            ),
            "event-materialization-artifact-recorded-" + suffix: (
                child_id, task_id, "artifact_recorded",
                {key: identity[key] for key in ("artifact_id", "path", "sha256", "size")},
            ),
            "event-evolved-materialization-" + suffix: (
                parent_id, None, "evolved_candidate_materialized", parent_payload,
            ),
            "event-materialization-publication-committed-" + suffix: (
                child_id, task_id, "materialization_publication_committed", identity,
            ),
        }

    def _inspect_materialization_publication(
        self, connection: sqlite3.Connection, parent_id: str, child_id: str, task_id: str,
        payload: dict[str, Any], identity: dict[str, Any],
    ) -> str:
        error = "materialization_publication_ledger_mismatch"
        runs = connection.execute("SELECT id FROM runs WHERE id IN (?, ?)", (parent_id, child_id)).fetchall()
        tasks = connection.execute("SELECT id FROM tasks WHERE run_id = ?", (child_id,)).fetchall()
        if len(runs) != 2 or len(tasks) != 1 or tasks[0]["id"] != task_id:
            raise ValueError(error)
        expected = self._materialization_publication_events(parent_id, child_id, task_id, payload, identity)
        rows = connection.execute(
            "SELECT id, run_id, task_id, type, payload FROM events WHERE id IN (?, ?, ?, ?) "
            "OR (run_id = ? AND type IN ('materialization_publication_prepared', "
            "'materialization_publication_committed', 'artifact_recorded')) "
            "OR (run_id = ? AND type = 'evolved_candidate_materialized')",
            (*expected, child_id, parent_id),
        ).fetchall()
        matching: dict[str, sqlite3.Row] = {}
        for row in rows:
            event_payload = self._materialization_publication_json(row["payload"])
            relevant = (
                row["id"] in expected
                or row["type"] in {"materialization_publication_prepared", "materialization_publication_committed"}
                or (row["type"] == "artifact_recorded" and (
                    event_payload.get("artifact_id") == identity["artifact_id"]
                    or event_payload.get("path") == identity["path"]
                ))
                or (row["type"] == "evolved_candidate_materialized"
                    and event_payload.get("evolution_run_id") == child_id)
            )
            if not relevant:
                continue
            wanted = expected.get(row["id"])
            if (
                wanted is None or (row["run_id"], row["task_id"], row["type"]) != wanted[:3]
                or json.dumps(event_payload, sort_keys=True, allow_nan=False)
                != json.dumps(wanted[3], sort_keys=True, allow_nan=False)
            ):
                raise ValueError(error)
            matching[row["id"]] = row
        artifacts = connection.execute(
            "SELECT id, run_id, task_id, path, sha256, size, kind FROM artifacts WHERE id = ? "
            "OR (run_id = ? AND (path = ? OR kind = 'evolved_materialization'))",
            (identity["artifact_id"], child_id, identity["path"]),
        ).fetchall()
        prepared_id = next(iter(expected))
        if prepared_id not in matching:
            if matching or artifacts:
                raise ValueError(error)
            return "absent"
        if len(matching) == 1 and not artifacts:
            return "prepared"
        if len(matching) != 4 or len(artifacts) != 1:
            raise ValueError(error)
        artifact = artifacts[0]
        if (
            artifact["id"] != identity["artifact_id"] or artifact["run_id"] != child_id
            or artifact["task_id"] != task_id or artifact["path"] != identity["path"]
            or artifact["kind"] != "evolved_materialization"
            or artifact["sha256"] != identity["sha256"] or type(artifact["size"]) is not int
            or artifact["size"] != identity["size"]
        ):
            raise ValueError(error)
        return "committed"

    def has_materialization_publication(self, parent_id: str, child_id: str) -> bool:
        """Detect modern evidence without requiring or creating a result journal."""
        try:
            suffix = self._materialization_publication_suffix(parent_id, child_id)
            artifact_id = "artifact-materialization-publication-" + suffix
            event_ids = tuple(prefix + suffix for prefix in (
                "event-materialization-publication-prepared-",
                "event-materialization-publication-committed-",
                "event-materialization-artifact-recorded-",
            ))
            with closing(sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True, timeout=30)) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("BEGIN")
                if connection.execute("SELECT 1 FROM artifacts WHERE id = ?", (artifact_id,)).fetchone():
                    return True
                rows = connection.execute(
                    "SELECT id, type, payload FROM events WHERE id IN (?, ?, ?) "
                    "OR (run_id = ? AND type IN ('materialization_publication_prepared', "
                    "'materialization_publication_committed', 'artifact_recorded'))",
                    (*event_ids, child_id),
                ).fetchall()
                if any(row["id"] in event_ids for row in rows):
                    return True
                found = False
                for row in rows:
                    value = self._materialization_publication_json(row["payload"])
                    if row["type"] in {"materialization_publication_prepared", "materialization_publication_committed"}:
                        # This child has modern preparation/commit evidence even if its embedded
                        # identity is corrupt; absence must not authorize a legacy downgrade.
                        found = True
                    elif value.get("artifact_id") == artifact_id:
                        found = True
                return found
        except Exception:  # noqa: BLE001 - missing/unreadable state is not proof of legacy history.
            raise ValueError("materialization_publication_ledger_mismatch") from None

    def materialization_publication_status(
        self, parent_id: str, child_id: str, task_id: str, payload: dict[str, Any], *, journal_sha256: str,
    ) -> str:
        """Inspect preparation and the complete terminal batch in one read-only snapshot."""
        try:
            result, identity = self._materialization_publication_manifest(
                parent_id, child_id, task_id, payload, journal_sha256,
            )
            with closing(sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True, timeout=30)) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("BEGIN")
                return self._inspect_materialization_publication(
                    connection, parent_id, child_id, task_id, result, identity,
                )
        except Exception:  # noqa: BLE001 - expose only a safe integrity error at recovery boundaries.
            raise ValueError("materialization_publication_ledger_mismatch") from None

    @staticmethod
    def _materialization_publication_budget(
        connection: sqlite3.Connection, child_id: str, marker_size: int, maximum: int,
    ) -> None:
        if type(maximum) is not int or maximum < 1:
            raise ValueError("materialization_publication_budget_exceeded")
        sizes = [row["size"] for row in connection.execute("SELECT size FROM artifacts WHERE run_id = ?", (child_id,))]
        if any(type(size) is not int or size < 0 for size in sizes):
            raise ValueError("materialization_publication_ledger_mismatch")
        if sum(sizes) + marker_size > maximum:
            raise ValueError("materialization_publication_budget_exceeded")

    def _write_materialization_publication(
        self, parent_id: str, child_id: str, task_id: str, payload: dict[str, Any], *,
        journal_sha256: str, max_artifact_bytes: int, commit: bool,
    ) -> None:
        safe_errors = {"materialization_publication_ledger_mismatch", "materialization_publication_budget_exceeded"}
        try:
            result, identity = self._materialization_publication_manifest(
                parent_id, child_id, task_id, payload, journal_sha256,
            )
            expected = self._materialization_publication_events(parent_id, child_id, task_id, result, identity)
            with closing(self._connect()) as connection, connection:
                connection.execute("PRAGMA synchronous = FULL")
                connection.execute("BEGIN IMMEDIATE")
                status = self._inspect_materialization_publication(
                    connection, parent_id, child_id, task_id, result, identity,
                )
                if status == "committed":
                    return
                if commit and status != "prepared":
                    raise ValueError("materialization_publication_ledger_mismatch")
                self._materialization_publication_budget(
                    connection, child_id, identity["size"], max_artifact_bytes,
                )
                if not commit:
                    if status == "prepared":
                        return
                    event_id = next(iter(expected))
                    run_id, owner_id, event_type, event_payload = expected[event_id]
                    if not self._append_event(connection, run_id, owner_id, event_type, event_payload, event_id):
                        raise ValueError("materialization_publication_ledger_mismatch")
                    return
                connection.execute(
                    "INSERT INTO artifacts(id, run_id, task_id, path, sha256, size, kind, created_at) "
                    "VALUES(?, ?, ?, ?, ?, ?, 'evolved_materialization', ?)",
                    (identity["artifact_id"], child_id, task_id, identity["path"], identity["sha256"], identity["size"], utc_now()),
                )
                # Preserve the old parent event shape while publishing every new terminal row
                # and acknowledgement in this single transaction.
                for event_id, (run_id, owner_id, event_type, event_payload) in expected.items():
                    if event_type == "materialization_publication_prepared":
                        continue
                    if not self._append_event(connection, run_id, owner_id, event_type, event_payload, event_id):
                        raise ValueError("materialization_publication_ledger_mismatch")
        except Exception as exc:  # noqa: BLE001 - transaction rollback includes storage/injected faults.
            if isinstance(exc, ValueError) and str(exc) in safe_errors:
                code = str(exc)
            elif isinstance(exc, (TypeError, ValueError, RecursionError)):
                code = "materialization_publication_ledger_mismatch"
            else:
                code = "materialization_publication_commit_failed"
            raise ValueError(code) from None

    def prepare_materialization_publication(
        self, parent_id: str, child_id: str, task_id: str, payload: dict[str, Any], *,
        journal_sha256: str, max_artifact_bytes: int,
    ) -> None:
        """Durably authorize only an exactly identified, wholly absent terminal batch."""
        self._write_materialization_publication(
            parent_id, child_id, task_id, payload, journal_sha256=journal_sha256,
            max_artifact_bytes=max_artifact_bytes, commit=False,
        )

    def commit_materialization_publication(
        self, parent_id: str, child_id: str, task_id: str, payload: dict[str, Any], *,
        journal_sha256: str, max_artifact_bytes: int,
    ) -> None:
        """Commit the prepared marker artifact and all terminal events atomically."""
        self._write_materialization_publication(
            parent_id, child_id, task_id, payload, journal_sha256=journal_sha256,
            max_artifact_bytes=max_artifact_bytes, commit=True,
        )

    @staticmethod
    def _materialization_launch_id(parent_id: str, child_id: str) -> str:
        if parent_id == child_id or any(
            not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value) is None
            for value in (parent_id, child_id)
        ):
            raise ValueError("materialization_launch_ledger_mismatch")
        return "event-materialization-launch-intended-" + hashlib.sha256(
            f"{parent_id}\0{child_id}".encode()
        ).hexdigest()

    def _materialization_launch_manifest(
        self, parent_id: str, child_id: str, task_id: str, intent: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        error = "materialization_launch_ledger_mismatch"
        event_id = self._materialization_launch_id(parent_id, child_id)
        keys = {
            "schema_version", "parent_run_id", "evolution_run_id", "task_id",
            "contract_sha256", "strategy", "candidate_id", "candidate_path",
            "candidate_sha256", "attempt_path", "runner_sha256", "timeout_seconds",
        }
        if (
            not isinstance(task_id, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", task_id) is None
            or not isinstance(intent, dict) or set(intent) != keys
            or intent["schema_version"] != "1" or intent["parent_run_id"] != parent_id
            or intent["evolution_run_id"] != child_id or intent["task_id"] != task_id
            or intent["strategy"] not in ("population", "openevolve")
            or not isinstance(intent["candidate_id"], str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", intent["candidate_id"]) is None
            or any(not isinstance(intent[key], str) or re.fullmatch(r"[0-9a-f]{64}", intent[key]) is None
                   for key in ("contract_sha256", "candidate_sha256", "runner_sha256"))
        ):
            raise ValueError(error)
        timeout = intent["timeout_seconds"]
        if type(timeout) not in (int, float) or not 0 < timeout <= 86_400 or not math.isfinite(timeout):
            raise ValueError(error)
        for key in ("candidate_path", "attempt_path"):
            value = intent[key]
            if (
                not isinstance(value, str) or not value or "\0" in value or "\\" in value
                or Path(value).is_absolute() or Path(value).as_posix() != value
                or any(part in {"", ".", ".."} for part in value.split("/"))
            ):
                raise ValueError(error)
        if intent["attempt_path"] != (
            f"evolution/materialization/{intent['candidate_id']}-{intent['candidate_sha256'][:12]}"
        ):
            raise ValueError(error)
        content = (json.dumps(
            intent, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False,
        ) + "\n").encode("utf-8")
        if len(content) > 8192:
            raise ValueError(error)
        return event_id, {
            "parent_run_id": parent_id, "evolution_run_id": child_id,
            "intent_path": "evolution/materialization/launch-intent.json",
            "intent_sha256": hashlib.sha256(content).hexdigest(), "intent_size": len(content),
        }

    def _inspect_materialization_launch(
        self, connection: sqlite3.Connection, parent_id: str, child_id: str, task_id: str,
        event_id: str, payload: dict[str, Any],
    ) -> bool:
        error = "materialization_launch_ledger_mismatch"
        runs = connection.execute("SELECT id FROM runs WHERE id IN (?, ?)", (parent_id, child_id)).fetchall()
        tasks = connection.execute("SELECT id FROM tasks WHERE run_id = ?", (child_id,)).fetchall()
        if len(runs) != 2 or len(tasks) != 1 or tasks[0]["id"] != task_id:
            raise ValueError(error)
        rows = connection.execute(
            "SELECT id, run_id, task_id, type, payload FROM events WHERE id = ? "
            "OR (run_id = ? AND type = 'materialization_launch_intended')",
            (event_id, child_id),
        ).fetchall()
        if not rows:
            return False
        if len(rows) != 1:
            raise ValueError(error)
        row = rows[0]
        stored = self._materialization_publication_json(row["payload"])
        if (
            row["id"] != event_id or row["run_id"] != child_id or row["task_id"] != task_id
            or row["type"] != "materialization_launch_intended"
            or json.dumps(stored, sort_keys=True, allow_nan=False) != json.dumps(payload, sort_keys=True, allow_nan=False)
        ):
            raise ValueError(error)
        return True

    def has_materialization_launch_intent(self, parent_id: str, child_id: str) -> bool:
        """Observe any modern launch evidence, including damaged event ownership or type."""
        try:
            event_id = self._materialization_launch_id(parent_id, child_id)
            with closing(sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True, timeout=30)) as connection:
                connection.execute("BEGIN")
                return connection.execute(
                    "SELECT 1 FROM events WHERE id = ? "
                    "OR (run_id = ? AND type = 'materialization_launch_intended') LIMIT 1",
                    (event_id, child_id),
                ).fetchone() is not None
        except Exception:  # noqa: BLE001 - an unreadable ledger cannot prove launch never happened.
            raise ValueError("materialization_launch_ledger_mismatch") from None

    def materialization_launch_intent_recorded(
        self, parent_id: str, child_id: str, task_id: str, intent: dict[str, Any],
    ) -> bool:
        """Check exact launch evidence in a single read-only database snapshot."""
        try:
            event_id, payload = self._materialization_launch_manifest(parent_id, child_id, task_id, intent)
            with closing(sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True, timeout=30)) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("BEGIN")
                return self._inspect_materialization_launch(
                    connection, parent_id, child_id, task_id, event_id, payload,
                )
        except Exception:  # noqa: BLE001 - keep replay failure diagnostics bounded and safe.
            raise ValueError("materialization_launch_ledger_mismatch") from None

    def record_materialization_launch_intent(
        self, parent_id: str, child_id: str, task_id: str, intent: dict[str, Any],
    ) -> None:
        """Durably register one exact launch intent; replay does not authorize execution."""
        try:
            event_id, payload = self._materialization_launch_manifest(parent_id, child_id, task_id, intent)
            with closing(self._connect()) as connection, connection:
                connection.execute("PRAGMA synchronous = FULL")
                connection.execute("BEGIN IMMEDIATE")
                if self._inspect_materialization_launch(connection, parent_id, child_id, task_id, event_id, payload):
                    return
                if not self._append_event(
                    connection, child_id, task_id, "materialization_launch_intended", payload, event_id,
                ):
                    raise ValueError("materialization_launch_ledger_mismatch")
        except Exception as exc:  # noqa: BLE001 - failed writes roll back with no sensitive diagnostics.
            code = (
                "materialization_launch_ledger_mismatch"
                if isinstance(exc, (ValueError, TypeError, RecursionError))
                else "materialization_launch_commit_failed"
            )
            raise ValueError(code) from None

    def _materialization_execution_manifest(
        self, parent_id: str, child_id: str, task_id: str, intent: dict[str, Any],
        execution: dict[str, Any], journal_sha256: str,
    ) -> tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]]:
        from .evolution import CandidateExecution, EvolutionError

        error = "materialization_execution_ledger_mismatch"
        launch_event_id, launch_payload = self._materialization_launch_manifest(parent_id, child_id, task_id, intent)
        if not isinstance(journal_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", journal_sha256) is None:
            raise ValueError(error)
        try:
            if not isinstance(execution, dict):
                raise TypeError(error)
            normalized = CandidateExecution.from_dict(execution).to_dict()
            if any(Path(path).as_posix() != path or any(part in {"", ".", ".."} for part in path.split("/"))
                   for path in normalized["artifacts"]):
                raise ValueError(error)
            content = (json.dumps(execution, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
            canonical = (json.dumps(normalized, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
            if len(content) > 64 * 1024 or content != canonical:
                raise ValueError(error)
        except (TypeError, ValueError, RecursionError, EvolutionError):
            raise ValueError(error) from None
        suffix = hashlib.sha256(f"{parent_id}\0{child_id}".encode()).hexdigest()
        identity = {
            "parent_run_id": parent_id, "evolution_run_id": child_id, "owner_task_id": task_id,
            "journal_sha256": journal_sha256, "launch_intent_sha256": launch_payload["intent_sha256"],
            "artifact_id": "artifact-materialization-execution-" + suffix,
            "path": intent["attempt_path"] + "/execution.json",
            "sha256": hashlib.sha256(content).hexdigest(), "size": len(content),
        }
        return launch_event_id, launch_payload, normalized, identity

    @staticmethod
    def _materialization_execution_events(
        parent_id: str, child_id: str, task_id: str, intent: dict[str, Any],
        execution: dict[str, Any], identity: dict[str, Any], *, attestation_sha256: str | None = None,
    ) -> dict[str, tuple[str, dict[str, Any]]]:
        suffix = hashlib.sha256(f"{parent_id}\0{child_id}".encode()).hexdigest()
        executed_suffix = hashlib.sha256(f"{parent_id}\0{child_id}\0{intent['candidate_sha256']}".encode()).hexdigest()
        return {
            "event-materialization-execution-prepared-" + suffix: (
                "materialization_execution_prepared",
                identity if attestation_sha256 is None else {**identity, "attestation_sha256": attestation_sha256},
            ),
            "event-materialization-execution-artifact-recorded-" + suffix: (
                "artifact_recorded", {key: identity[key] for key in ("artifact_id", "path", "sha256", "size")},
            ),
            "event-evolved-candidate-executed-" + executed_suffix: (
                "evolved_candidate_executed", {
                    "candidate_id": intent["candidate_id"], "candidate_sha256": intent["candidate_sha256"],
                    "status": execution["status"], "exit_code": execution["exit_code"],
                    "duration_ms": execution["duration_ms"], "evidence_path": identity["path"],
                },
            ),
            "event-materialization-execution-committed-" + suffix: ("materialization_execution_committed", identity),
        }

    def _reject_materialization_execution_downstream(
        self, connection: sqlite3.Connection, parent_id: str, child_id: str,
    ) -> None:
        """A later publication proves this execution batch must not be rebuilt."""
        error = "materialization_execution_ledger_mismatch"
        suffix = hashlib.sha256(f"{parent_id}\0{child_id}".encode()).hexdigest()
        terminal_id = "artifact-materialization-publication-" + suffix
        marker = "evolution/materialization/result.json"
        ids = tuple(prefix + suffix for prefix in (
            "event-evolved-outputs-promoted-", "event-output-publication-committed-",
            "event-evolved-materialization-", "event-materialization-publication-prepared-",
            "event-materialization-publication-committed-", "event-materialization-artifact-recorded-",
            "event-materialization-delivery-prepared-",
        ))
        rows = connection.execute(
            "SELECT id, run_id, type, payload FROM events WHERE id IN (?, ?, ?, ?, ?, ?, ?) "
            "OR (run_id = ? AND type IN ('materialization_publication_prepared', "
            "'materialization_publication_committed', 'materialization_delivery_prepared', 'artifact_recorded')) "
            "OR (run_id = ? AND type IN ('evolved_outputs_promoted', 'output_publication_committed', "
            "'evolved_candidate_materialized', 'artifact_recorded'))",
            (*ids, child_id, parent_id),
        ).fetchall()
        for row in rows:
            if row["id"] in ids or (row["run_id"] == child_id and row["type"] in {
                "materialization_publication_prepared", "materialization_publication_committed",
                "materialization_delivery_prepared",
            }):
                raise ValueError(error)
            value = self._materialization_publication_json(row["payload"])
            if row["type"] == "artifact_recorded":
                path = value.get("path")
                if row["run_id"] == child_id and (
                    path == marker or value.get("artifact_id") == terminal_id
                    or (isinstance(path, str) and path.startswith("output/"))
                ):
                    raise ValueError(error)
                if row["run_id"] == parent_id and isinstance(path, str) and value.get("artifact_id") == (
                    self._output_publication_artifact_id(parent_id, child_id, path)
                ):
                    raise ValueError(error)
            elif value.get("evolution_run_id") == child_id:
                raise ValueError(error)
        artifacts = connection.execute(
            "SELECT id, run_id, kind, path FROM artifacts WHERE id = ? "
            "OR (run_id = ? AND (kind IN ('output', 'evolved_materialization') OR path = ? OR path LIKE 'output/%')) "
            "OR run_id = ?", (terminal_id, child_id, marker, parent_id),
        ).fetchall()
        for row in artifacts:
            if row["id"] == terminal_id or row["run_id"] == child_id or row["id"] == (
                self._output_publication_artifact_id(parent_id, child_id, row["path"])
            ):
                raise ValueError(error)

    def _inspect_materialization_execution(
        self, connection: sqlite3.Connection, parent_id: str, child_id: str, task_id: str,
        intent: dict[str, Any], execution: dict[str, Any], identity: dict[str, Any],
        launch_event_id: str, launch_payload: dict[str, Any],
    ) -> str:
        error = "materialization_execution_ledger_mismatch"
        if not self._inspect_materialization_launch(connection, parent_id, child_id, task_id, launch_event_id, launch_payload):
            raise ValueError(error)
        attested = self._inspect_materialization_execution_attestation(
            connection, parent_id, child_id, task_id, intent, execution, identity,
        )
        expected = self._materialization_execution_events(
            parent_id, child_id, task_id, intent, execution, identity,
            attestation_sha256=None if attested is None else attested[1]["receipt_sha256"],
        )
        rows = connection.execute(
            "SELECT id, run_id, task_id, type, payload FROM events WHERE id IN (?, ?, ?, ?) "
            "OR (run_id = ? AND type IN ('materialization_execution_prepared', "
            "'materialization_execution_committed', 'evolved_candidate_executed', 'artifact_recorded'))",
            (*expected, child_id),
        ).fetchall()
        matching: set[str] = set()
        for row in rows:
            value = self._materialization_publication_json(row["payload"])
            relevant = row["id"] in expected or row["type"] in {
                "materialization_execution_prepared", "materialization_execution_committed", "evolved_candidate_executed",
            } or value.get("artifact_id") == identity["artifact_id"] or value.get("path") == identity["path"]
            if not relevant:
                continue
            wanted = expected.get(row["id"])
            if (
                wanted is None or row["run_id"] != child_id or row["task_id"] != task_id or row["type"] != wanted[0]
                or json.dumps(value, sort_keys=True, allow_nan=False) != json.dumps(wanted[1], sort_keys=True, allow_nan=False)
            ):
                raise ValueError(error)
            matching.add(row["id"])
        artifacts = connection.execute(
            "SELECT id, run_id, task_id, path, sha256, size, kind FROM artifacts WHERE id = ? "
            "OR (run_id = ? AND (path = ? OR kind = 'evolved_candidate_execution'))",
            (identity["artifact_id"], child_id, identity["path"]),
        ).fetchall()
        prepared = next(iter(expected))
        if prepared not in matching:
            if matching or artifacts or attested is not None:
                raise ValueError(error)
            self._reject_materialization_execution_downstream(connection, parent_id, child_id)
            return "absent"
        if len(matching) == 1 and not artifacts:
            self._reject_materialization_execution_downstream(connection, parent_id, child_id)
            return "prepared"
        if len(matching) != 4 or len(artifacts) != 1:
            raise ValueError(error)
        row = artifacts[0]
        if (
            row["id"] != identity["artifact_id"] or row["run_id"] != child_id or row["task_id"] != task_id
            or row["kind"] != "evolved_candidate_execution" or row["path"] != identity["path"]
            or row["sha256"] != identity["sha256"] or type(row["size"]) is not int or row["size"] != identity["size"]
        ):
            raise ValueError(error)
        return "committed"

    def _materialization_delivery_manifest(
        self, parent_id: str, child_id: str, task_id: str, intent: dict[str, Any],
        execution: dict[str, Any], plan: dict[str, Any],
    ) -> tuple[str, dict[str, Any], dict[str, Any], dict[str, Any], str, dict[str, Any]]:
        error = "materialization_delivery_ledger_mismatch"
        keys = {
            "schema_version", "parent_run_id", "evolution_run_id", "task_id",
            "launch_intent_sha256", "execution_journal_sha256", "execution_sha256", "result", "outputs",
        }
        if (
            not isinstance(plan, dict) or set(plan) != keys or plan["schema_version"] != "1"
            or plan["parent_run_id"] != parent_id or plan["evolution_run_id"] != child_id
            or plan["task_id"] != task_id or not isinstance(plan["outputs"], list)
            or len(plan["outputs"]) > MAX_OUTPUTS
        ):
            raise ValueError(error)
        launch_id, launch, normalized, execution_identity = self._materialization_execution_manifest(
            parent_id, child_id, task_id, intent, execution, plan["execution_journal_sha256"],
        )
        if (
            plan["launch_intent_sha256"] != launch["intent_sha256"]
            or plan["execution_sha256"] != execution_identity["sha256"]
        ):
            raise ValueError(error)
        result, _ = self._materialization_publication_manifest(
            parent_id, child_id, task_id, plan["result"], plan["execution_journal_sha256"],
        )
        expected_execution = {
            "status": normalized["status"], "exit_code": normalized["exit_code"],
            "duration_ms": normalized["duration_ms"], "evidence_path": execution_identity["path"],
        }
        validation = result["validation"]
        if (
            any(result[key] != intent[key] for key in (
                "contract_sha256", "candidate_id", "candidate_path", "candidate_sha256", "attempt_path",
            ))
            or result["outputs"] != []
            or json.dumps(result["execution"], sort_keys=True, allow_nan=False) != json.dumps(
                expected_execution, sort_keys=True, allow_nan=False,
            )
            or set(validation) != {"passed", "evidence", "reason", "details"}
            or type(validation["passed"]) is not bool or not isinstance(validation["evidence"], list)
            or any(not isinstance(item, str) for item in validation["evidence"])
            or not isinstance(validation["reason"], str) or not isinstance(validation["details"], dict)
        ):
            raise ValueError(error)
        if result["status"] == "succeeded":
            if normalized["status"] != "succeeded" or not validation["passed"] or result["error"] is not None:
                raise ValueError(error)
        elif plan["outputs"] or not isinstance(result["error"], str) or not result["error"]:
            raise ValueError(error)
        paths: set[str] = set()
        for item in plan["outputs"]:
            if not isinstance(item, dict) or set(item) != {"path", "format", "fields", "required", "size", "sha256"}:
                raise ValueError(error)
            if (
                type(item["size"]) is not int or not 0 <= item["size"] <= 256 * 1024
                or not isinstance(item["sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is None
            ):
                raise ValueError(error)
            metadata = {key: item[key] for key in ("path", "format", "fields", "required")}
            spec = OutputSpec.from_dict(metadata)
            if spec.to_dict() != metadata or spec.path in paths:
                raise ValueError(error)
            paths.add(spec.path)
        content = (json.dumps(plan, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
        if len(content) > 64 * 1024:
            raise ValueError(error)
        suffix = hashlib.sha256(f"{parent_id}\0{child_id}".encode()).hexdigest()
        event_id = "event-materialization-delivery-prepared-" + suffix
        payload = {
            "parent_run_id": parent_id, "evolution_run_id": child_id, "owner_task_id": task_id,
            "plan_path": "evolution/materialization/.delivery-publication/plan.json",
            "plan_sha256": hashlib.sha256(content).hexdigest(), "plan_size": len(content),
            "execution_journal_sha256": plan["execution_journal_sha256"],
            "execution_sha256": execution_identity["sha256"],
        }
        return launch_id, launch, normalized, execution_identity, event_id, payload

    def _inspect_materialization_delivery(
        self, connection: sqlite3.Connection, parent_id: str, child_id: str, task_id: str,
        intent: dict[str, Any], execution: dict[str, Any], execution_identity: dict[str, Any],
        launch_id: str, launch: dict[str, Any], event_id: str, payload: dict[str, Any],
    ) -> bool:
        error = "materialization_delivery_ledger_mismatch"
        if self._inspect_materialization_execution(
            connection, parent_id, child_id, task_id, intent, execution, execution_identity, launch_id, launch,
        ) != "committed":
            raise ValueError(error)
        rows = connection.execute(
            "SELECT id, run_id, task_id, type, payload FROM events WHERE id = ? "
            "OR (run_id = ? AND type = 'materialization_delivery_prepared')", (event_id, child_id),
        ).fetchall()
        if not rows:
            self._reject_materialization_execution_downstream(connection, parent_id, child_id)
            return False
        if len(rows) != 1:
            raise ValueError(error)
        row = rows[0]
        stored = self._materialization_publication_json(row["payload"])
        if (
            row["id"] != event_id or row["run_id"] != child_id or row["task_id"] != task_id
            or row["type"] != "materialization_delivery_prepared"
            or json.dumps(stored, sort_keys=True, allow_nan=False) != json.dumps(payload, sort_keys=True, allow_nan=False)
        ):
            raise ValueError(error)
        return True

    def has_materialization_delivery(self, parent_id: str, child_id: str) -> bool:
        """Recognize only modern delivery evidence, including damaged reserved event IDs."""
        try:
            self._materialization_launch_id(parent_id, child_id)
            suffix = hashlib.sha256(f"{parent_id}\0{child_id}".encode()).hexdigest()
            event_id = "event-materialization-delivery-prepared-" + suffix
            with closing(sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True, timeout=30)) as connection:
                connection.execute("BEGIN")
                return connection.execute(
                    "SELECT 1 FROM events WHERE id = ? "
                    "OR (run_id = ? AND type = 'materialization_delivery_prepared') LIMIT 1", (event_id, child_id),
                ).fetchone() is not None
        except Exception:  # noqa: BLE001 - unreadable state cannot prove absence of delivery.
            raise ValueError("materialization_delivery_ledger_mismatch") from None

    def materialization_delivery_recorded(
        self, parent_id: str, child_id: str, task_id: str, intent: dict[str, Any],
        execution: dict[str, Any], plan: dict[str, Any],
    ) -> bool:
        """Verify the exact plan and its complete launch/execution authority in one snapshot."""
        try:
            launch_id, launch, normalized, identity, event_id, payload = self._materialization_delivery_manifest(
                parent_id, child_id, task_id, intent, execution, plan,
            )
            with closing(sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True, timeout=30)) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("BEGIN")
                return self._inspect_materialization_delivery(
                    connection, parent_id, child_id, task_id, intent, normalized, identity,
                    launch_id, launch, event_id, payload,
                )
        except Exception:  # noqa: BLE001 - replay errors never include private ledger diagnostics.
            raise ValueError("materialization_delivery_ledger_mismatch") from None

    def record_materialization_delivery(
        self, parent_id: str, child_id: str, task_id: str, intent: dict[str, Any],
        execution: dict[str, Any], plan: dict[str, Any],
    ) -> None:
        """Durably bind the immutable delivery plan before any output or terminal publication."""
        try:
            launch_id, launch, normalized, identity, event_id, payload = self._materialization_delivery_manifest(
                parent_id, child_id, task_id, intent, execution, plan,
            )
            with closing(self._connect()) as connection, connection:
                connection.execute("PRAGMA synchronous = FULL")
                connection.execute("BEGIN IMMEDIATE")
                if self._inspect_materialization_delivery(
                    connection, parent_id, child_id, task_id, intent, normalized, identity,
                    launch_id, launch, event_id, payload,
                ):
                    return
                if not self._append_event(
                    connection, child_id, task_id, "materialization_delivery_prepared", payload, event_id,
                ):
                    raise ValueError("materialization_delivery_ledger_mismatch")
        except Exception as exc:  # noqa: BLE001 - failed writes roll back without exposing storage diagnostics.
            code = (
                "materialization_delivery_ledger_mismatch"
                if isinstance(exc, (ValueError, TypeError, RecursionError))
                else "materialization_delivery_commit_failed"
            )
            raise ValueError(code) from None

    def has_materialization_execution(self, parent_id: str, child_id: str) -> bool:
        """Probe only modern execution identities, preserving ordinary legacy replay."""
        try:
            self._materialization_launch_id(parent_id, child_id)
            suffix = hashlib.sha256(f"{parent_id}\0{child_id}".encode()).hexdigest()
            artifact_id = "artifact-materialization-execution-" + suffix
            ids = tuple(prefix + suffix for prefix in (
                "event-materialization-execution-prepared-", "event-materialization-execution-artifact-recorded-",
                "event-materialization-execution-committed-", "event-materialization-execution-attested-",
            ))
            with closing(sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True, timeout=30)) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("BEGIN")
                if connection.execute("SELECT 1 FROM artifacts WHERE id = ?", (artifact_id,)).fetchone():
                    return True
                rows = connection.execute(
                    "SELECT id, type, payload FROM events WHERE id IN (?, ?, ?, ?) OR (run_id = ? "
                    "AND type IN ('materialization_execution_prepared', 'materialization_execution_committed', "
                    "'materialization_execution_attested', 'artifact_recorded'))",
                    (*ids, child_id),
                ).fetchall()
                for row in rows:
                    if row["id"] in ids or row["type"] in {
                        "materialization_execution_prepared", "materialization_execution_committed",
                        "materialization_execution_attested",
                    }:
                        return True
                    if self._materialization_publication_json(row["payload"]).get("artifact_id") == artifact_id:
                        return True
                return False
        except Exception:  # noqa: BLE001 - unreadable state cannot authorize a legacy downgrade.
            raise ValueError("materialization_execution_ledger_mismatch") from None

    def materialization_execution_status(
        self, parent_id: str, child_id: str, task_id: str, intent: dict[str, Any], execution: dict[str, Any], *,
        journal_sha256: str, attestation: dict[str, Any] | None = None,
    ) -> str:
        """Read exact launch, preparation and batch identity in one SQLite snapshot."""
        try:
            launch_id, launch, result, identity = self._materialization_execution_manifest(
                parent_id, child_id, task_id, intent, execution, journal_sha256,
            )
            with closing(sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True, timeout=30)) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("BEGIN")
                status = self._inspect_materialization_execution(
                    connection, parent_id, child_id, task_id, intent, result, identity, launch_id, launch,
                )
                found = self._inspect_materialization_execution_attestation(
                    connection, parent_id, child_id, task_id, intent, result, identity,
                    attestation=attestation, require_supplied=True,
                )
                if status != "absent" and attestation is not None and found is None:
                    raise ValueError("materialization_execution_ledger_mismatch")
                return status
        except Exception:  # noqa: BLE001 - exact read failures expose only a safe integrity code.
            raise ValueError("materialization_execution_ledger_mismatch") from None

    def _write_materialization_execution(
        self, parent_id: str, child_id: str, task_id: str, intent: dict[str, Any], execution: dict[str, Any], *,
        journal_sha256: str, max_artifact_bytes: int, commit: bool, attestation: dict[str, Any] | None = None,
    ) -> None:
        try:
            if isinstance(attestation, dict):
                attestation = dict(attestation)
            launch_id, launch, result, identity = self._materialization_execution_manifest(
                parent_id, child_id, task_id, intent, execution, journal_sha256,
            )
            receipt = None if attestation is None else self._materialization_execution_attestation_manifest(
                parent_id, child_id, task_id, intent, result, identity, attestation,
            )
            expected = self._materialization_execution_events(
                parent_id, child_id, task_id, intent, result, identity,
                attestation_sha256=None if receipt is None else receipt[1]["receipt_sha256"],
            )
            with closing(self._connect()) as connection, connection:
                connection.execute("PRAGMA synchronous = FULL")
                connection.execute("BEGIN IMMEDIATE")
                status = self._inspect_materialization_execution(
                    connection, parent_id, child_id, task_id, intent, result, identity, launch_id, launch,
                )
                found = self._inspect_materialization_execution_attestation(
                    connection, parent_id, child_id, task_id, intent, result, identity,
                    attestation=attestation, require_supplied=True,
                )
                if status != "absent" and attestation is not None and found is None:
                    raise ValueError("materialization_execution_ledger_mismatch")
                if status == "committed":
                    return
                if commit and status != "prepared":
                    raise ValueError("materialization_execution_ledger_mismatch")
                if type(max_artifact_bytes) is not int or max_artifact_bytes < 1:
                    raise ValueError("materialization_execution_budget_exceeded")
                sizes = [row["size"] for row in connection.execute("SELECT size FROM artifacts WHERE run_id = ?", (child_id,))]
                if any(type(size) is not int or size < 0 for size in sizes):
                    raise ValueError("materialization_execution_ledger_mismatch")
                if sum(sizes) + identity["size"] > max_artifact_bytes:
                    raise ValueError("materialization_execution_budget_exceeded")
                if not commit:
                    if status == "prepared":
                        return
                    event_id = next(iter(expected))
                    kind, payload = expected[event_id]
                    if not self._append_event(connection, child_id, task_id, kind, payload, event_id):
                        raise ValueError("materialization_execution_ledger_mismatch")
                    if receipt is not None and not self._append_event(
                        connection, child_id, task_id, "materialization_execution_attested", receipt[1], receipt[0],
                    ):
                        raise ValueError("materialization_execution_ledger_mismatch")
                    return
                connection.execute(
                    "INSERT INTO artifacts(id,run_id,task_id,path,sha256,size,kind,created_at) "
                    "VALUES(?,?,?,?,?,?,'evolved_candidate_execution',?)",
                    (identity["artifact_id"], child_id, task_id, identity["path"], identity["sha256"], identity["size"], utc_now()),
                )
                for event_id, (kind, payload) in expected.items():
                    if kind == "materialization_execution_prepared":
                        continue
                    if not self._append_event(connection, child_id, task_id, kind, payload, event_id):
                        raise ValueError("materialization_execution_ledger_mismatch")
        except Exception as exc:  # noqa: BLE001 - every failed write rolls back, including injected faults.
            if isinstance(exc, ValueError) and str(exc) == "materialization_execution_budget_exceeded":
                code = str(exc)
            elif isinstance(exc, (TypeError, ValueError, RecursionError)):
                code = "materialization_execution_ledger_mismatch"
            else:
                code = "materialization_execution_commit_failed"
            raise ValueError(code) from None

    def prepare_materialization_execution(
        self, parent_id: str, child_id: str, task_id: str, intent: dict[str, Any], execution: dict[str, Any], *,
        journal_sha256: str, max_artifact_bytes: int, attestation: dict[str, Any] | None = None,
    ) -> None:
        """Durably prepare a wholly absent execution batch after exact launch authorization."""
        self._write_materialization_execution(
            parent_id, child_id, task_id, intent, execution, journal_sha256=journal_sha256,
            max_artifact_bytes=max_artifact_bytes, commit=False, attestation=attestation,
        )

    def commit_materialization_execution(
        self, parent_id: str, child_id: str, task_id: str, intent: dict[str, Any], execution: dict[str, Any], *,
        journal_sha256: str, max_artifact_bytes: int, attestation: dict[str, Any] | None = None,
    ) -> None:
        """Atomically register the prepared execution artifact and its complete event batch."""
        self._write_materialization_execution(
            parent_id, child_id, task_id, intent, execution, journal_sha256=journal_sha256,
            max_artifact_bytes=max_artifact_bytes, commit=True, attestation=attestation,
        )

    def _materialization_execution_attestation_manifest(
        self, parent_id: str, child_id: str, task_id: str, intent: dict[str, Any],
        execution: dict[str, Any], identity: dict[str, Any], attestation: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        """Bind one operator receipt to the canonical execution and exact journal."""
        error = "materialization_execution_ledger_mismatch"
        keys = {
            "schema_version", "parent_run_id", "evolution_run_id", "task_id", "launch_intent_sha256",
            "candidate_id", "candidate_sha256", "attempt_path", "execution_path",
            "execution_sha256", "execution_size", "device", "inode", "nonce",
        }
        if not isinstance(attestation, dict) or set(attestation) != keys:
            raise ValueError(error)
        expected = {
            "schema_version": "1", "parent_run_id": parent_id, "evolution_run_id": child_id,
            "task_id": task_id, "launch_intent_sha256": identity["launch_intent_sha256"],
            "candidate_id": intent["candidate_id"], "candidate_sha256": intent["candidate_sha256"],
            "attempt_path": intent["attempt_path"], "execution_path": identity["path"],
            "execution_sha256": identity["sha256"], "execution_size": identity["size"],
        }
        if (
            any(type(attestation[key]) is not type(value) or attestation[key] != value for key, value in expected.items())
            or any(type(attestation[key]) is not int or not 0 <= attestation[key] < 2**64 for key in ("device", "inode"))
            or not isinstance(attestation["nonce"], str)
            or re.fullmatch(r"[A-Za-z0-9._~-]{32,128}", attestation["nonce"]) is None
        ):
            raise ValueError(error)
        content = (json.dumps(attestation, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
        if len(content) > 16 * 1024:
            raise ValueError(error)
        suffix = hashlib.sha256(f"{parent_id}\0{child_id}".encode()).hexdigest()
        payload = {
            **attestation, "receipt_sha256": hashlib.sha256(content).hexdigest(),
            "journal_sha256": identity["journal_sha256"],
        }
        return "event-materialization-execution-attested-" + suffix, payload

    def _inspect_materialization_execution_attestation(
        self, connection: sqlite3.Connection, parent_id: str, child_id: str, task_id: str,
        intent: dict[str, Any], execution: dict[str, Any], identity: dict[str, Any],
        *, attestation: dict[str, Any] | None = None, require_supplied: bool = False,
    ) -> tuple[str, dict[str, Any]] | None:
        """Inspect the current pair and global nonce owners in the caller's snapshot."""
        error = "materialization_execution_ledger_mismatch"
        prefix = "event-materialization-execution-attested-"
        pair_id = prefix + hashlib.sha256(f"{parent_id}\0{child_id}".encode()).hexdigest()
        wanted = None if attestation is None else self._materialization_execution_attestation_manifest(
            parent_id, child_id, task_id, intent, execution, identity, attestation,
        )
        rows = connection.execute(
            "SELECT id, run_id, task_id, type, payload FROM events WHERE id LIKE ? "
            "OR type = 'materialization_execution_attested'", (prefix + "%",),
        ).fetchall()
        parsed = []
        unknown_nonce = False
        for row in rows:
            try:
                value = self._materialization_publication_json(row["payload"])
                parsed.append((row, value))
                nonce = value.get("nonce")
                if not isinstance(nonce, str) or re.fullmatch(r"[A-Za-z0-9._~-]{32,128}", nonce) is None:
                    unknown_nonce = True
            except (TypeError, ValueError, RecursionError):
                if row["id"] == pair_id or row["run_id"] == child_id:
                    raise ValueError(error) from None
                unknown_nonce = True
        relevant = [(row, value) for row, value in parsed if row["id"] == pair_id
                    or row["run_id"] == child_id or value.get("evolution_run_id") == child_id]
        if len(relevant) > 1:
            raise ValueError(error)
        found = None
        if relevant:
            row, value = relevant[0]
            receipt = {key: item for key, item in value.items() if key not in {"receipt_sha256", "journal_sha256"}}
            found = self._materialization_execution_attestation_manifest(
                parent_id, child_id, task_id, intent, execution, identity, receipt,
            )
            if (
                row["id"] != found[0] or row["run_id"] != child_id or row["task_id"] != task_id
                or row["type"] != "materialization_execution_attested"
                or json.dumps(value, sort_keys=True, allow_nan=False) != json.dumps(found[1], sort_keys=True, allow_nan=False)
                or (require_supplied and wanted != found)
            ):
                raise ValueError(error)
        nonce = wanted[1]["nonce"] if wanted is not None else found[1]["nonce"] if found is not None else None
        if nonce is not None and (
            unknown_nonce or any(row["id"] != pair_id and value.get("nonce") == nonce for row, value in parsed)
        ):
            raise ValueError(error)
        return found

    def materialization_execution_attestation_recorded(
        self, parent_id: str, child_id: str, task_id: str, intent: dict[str, Any],
        execution: dict[str, Any], attestation: dict[str, Any], *, journal_sha256: str,
        require_no_downstream: bool = False,
    ) -> bool:
        """Read exact receipt and launch/execution authority without opening a writer."""
        try:
            launch_id, launch, result, identity = self._materialization_execution_manifest(
                parent_id, child_id, task_id, intent, execution, journal_sha256,
            )
            self._materialization_execution_attestation_manifest(
                parent_id, child_id, task_id, intent, result, identity, attestation,
            )
            with closing(sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True, timeout=30)) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("BEGIN")
                if require_no_downstream:
                    self._reject_materialization_execution_downstream(connection, parent_id, child_id)
                status = self._inspect_materialization_execution(
                    connection, parent_id, child_id, task_id, intent, result, identity, launch_id, launch,
                )
                found = self._inspect_materialization_execution_attestation(
                    connection, parent_id, child_id, task_id, intent, result, identity,
                    attestation=attestation, require_supplied=True,
                )
                if status != "absent" and found is None:
                    raise ValueError("materialization_execution_ledger_mismatch")
                return found is not None
        except Exception:  # noqa: BLE001 - probe failures expose no receipt or ledger contents.
            raise ValueError("materialization_execution_ledger_mismatch") from None

    def has_materialization_execution_attestation(self, parent_id: str, child_id: str) -> bool:
        """Recognize current-pair attestation evidence, including damaged reserved IDs."""
        try:
            self._materialization_launch_id(parent_id, child_id)
            suffix = hashlib.sha256(f"{parent_id}\0{child_id}".encode()).hexdigest()
            event_id = "event-materialization-execution-attested-" + suffix
            with closing(sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True, timeout=30)) as connection:
                connection.execute("BEGIN")
                return connection.execute(
                    "SELECT 1 FROM events WHERE id = ? "
                    "OR (run_id = ? AND type = 'materialization_execution_attested') LIMIT 1", (event_id, child_id),
                ).fetchone() is not None
        except Exception:  # noqa: BLE001 - unavailable state cannot authorize an evidence downgrade.
            raise ValueError("materialization_execution_ledger_mismatch") from None

    def discard_attempt_outputs(
        self,
        run_id: str,
        task_id: str,
        attempt_id: str,
        output_artifact_ids: Sequence[str] = (),
    ) -> list[str]:
        """Remove late attempt metadata while retaining the prompt and audit event."""
        prefix = f"tasks/{task_id}/{attempt_id}/"
        with self._connect() as connection:
            output_clause = ""
            args: list[object] = [run_id, task_id, prefix + "%", "result", "runtime"]
            if output_artifact_ids:
                placeholders = ", ".join("?" for _ in output_artifact_ids)
                output_clause = f" OR (kind = 'output' AND id IN ({placeholders}))"
                args.extend(output_artifact_ids)
            rows = connection.execute(
                "SELECT path FROM artifacts WHERE run_id = ? AND task_id = ? AND "
                f"(path LIKE ? AND kind IN (?, ?)){output_clause}",
                args,
            ).fetchall()
            delete_args = list(args)
            connection.execute(
                "DELETE FROM artifacts WHERE run_id = ? AND task_id = ? AND "
                f"(path LIKE ? AND kind IN (?, ?)){output_clause}",
                delete_args,
            )
        return [row["path"] for row in rows]

    def list_artifacts(self, run_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, task_id, path, sha256, size, kind, created_at FROM artifacts "
                "WHERE run_id = ? ORDER BY created_at, id",
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_events(self, run_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, task_id, type, payload, created_at FROM events "
                "WHERE run_id = ? ORDER BY created_at, id",
                (run_id,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "task_id": row["task_id"],
                "type": row["type"],
                "payload": json.loads(row["payload"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def append_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        task_id: str | None = None,
        event_id: str | None = None,
    ) -> bool:
        with self._connect() as connection:
            return self._append_event(connection, run_id, task_id, event_type, payload, event_id)

    def append_candidate_generation_event(
        self,
        run_id: str,
        task_id: str,
        payload: Mapping[str, Any],
    ) -> bool:
        """Atomically append one validated candidate-generation receipt.

        The event id is derived from the controller-owned run/task/budget identity.  A replay
        with the same canonical payload is idempotent; a second payload for the same budget is
        rejected so a later audit cannot silently choose between competing generation outcomes.
        """
        from .candidate_generation_receipt import (
            CandidateGenerationReceiptError,
            build_candidate_generation_receipt,
            generation_event_id,
        )

        try:
            receipt = build_candidate_generation_receipt(payload, run_id=run_id, task_id=task_id)
            event_id = generation_event_id(receipt)
        except CandidateGenerationReceiptError as exc:
            raise ValueError(f"invalid candidate-generation receipt: {exc}") from exc
        with self._connect() as connection:
            task = connection.execute(
                "SELECT run_id FROM tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
            if task is None or task["run_id"] != run_id:
                raise ValueError("candidate-generation task is not bound to run")
            existing = connection.execute(
                "SELECT run_id, task_id, type, payload FROM events WHERE id = ?",
                (event_id,),
            ).fetchone()
            if existing is not None:
                try:
                    existing_payload = json.loads(existing["payload"])
                except (TypeError, json.JSONDecodeError) as exc:
                    raise ValueError("candidate-generation event payload is corrupt") from exc
                if (
                    existing["run_id"] == run_id
                    and existing["task_id"] == task_id
                    and existing["type"] == "agent_candidate_generation"
                    and existing_payload == receipt
                ):
                    return False
                raise ValueError("candidate-generation event identity conflict")
            rows = connection.execute(
                "SELECT id, payload FROM events WHERE run_id = ? AND task_id = ? "
                "AND type = ?",
                (run_id, task_id, "agent_candidate_generation"),
            ).fetchall()
            for row in rows:
                try:
                    prior = json.loads(row["payload"])
                except (TypeError, json.JSONDecodeError) as exc:
                    raise ValueError("candidate-generation event payload is corrupt") from exc
                if isinstance(prior, dict) and prior.get("budget_id") == receipt["budget_id"]:
                    raise ValueError("candidate-generation budget already has a different receipt")
            return self._append_event(
                connection,
                run_id,
                task_id,
                "agent_candidate_generation",
                receipt,
                event_id,
            )

    def fail_budget(self, run_id: str, limit: str, actual: float, maximum: float, reason: str) -> bool:
        """Record a fail-closed budget violation and transition unfinished work to failed."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None or row["status"] in {RunStatus.SUCCEEDED.value, RunStatus.CANCELLED.value}:
                return False
            if limit == "solve_wall_timeout" and row["status"] == RunStatus.FAILED.value:
                return False
            timestamp = utc_now()
            connection.execute(
                "UPDATE runs SET status = ?, updated_at = ? WHERE id = ? AND status != ?",
                (RunStatus.FAILED.value, timestamp, run_id, RunStatus.CANCELLED.value),
            )
            connection.execute(
                "UPDATE tasks SET state = ?, last_error = ?, updated_at = ? WHERE run_id = ? AND state IN (?, ?, ?, ?)",
                (TaskStatus.BLOCKED.value, reason, timestamp, run_id, TaskStatus.PENDING.value, TaskStatus.READY.value, TaskStatus.WAITING.value, TaskStatus.RUNNING.value),
            )
            connection.execute(
                "UPDATE attempts SET status = ?, finished_at = ?, heartbeat_at = ?, error = ? WHERE task_id IN (SELECT id FROM tasks WHERE run_id = ?) AND status = ?",
                ("failed", timestamp, timestamp, reason, run_id, "running"),
            )
            if limit == "solve_wall_timeout":
                connection.execute(
                    "UPDATE tasks SET state = ?, last_error = ?, updated_at = ? "
                    "WHERE run_id = ? AND orchestration = 1 AND state IN (?, ?, ?, ?, ?, ?)",
                    (TaskStatus.FAILED.value, reason, timestamp, run_id,
                     TaskStatus.BLOCKED.value, TaskStatus.PENDING.value, TaskStatus.READY.value,
                     TaskStatus.WAITING.value, TaskStatus.RUNNING.value, TaskStatus.UNCERTAIN.value),
                )
            return self._append_event(
                connection, run_id, None, "budget_exceeded",
                {"limit": limit, "actual": actual, "maximum": maximum, "reason": reason},
                event_id=f"event-budget-{limit}-{run_id}",
            )

    # Worker records are deliberately separate from task rows. A task is a scheduler unit; a
    # worker is an owned, resumable conversation. These methods keep the ownership checks inside
    # the store so callers cannot accidentally perform a side effect before authorization.
    def create_worker(
        self,
        owner_id: str,
        role: str,
        description: str,
        *,
        parent_worker_id: str | None = None,
        agent_type: str = "runtime",
        max_depth: int = 1,
        require_parent_running: bool = False,
    ) -> Worker:
        if not owner_id.strip() or not role.strip() or not description.strip():
            raise ValueError("worker owner, role, and description must be non-empty")
        if len(description.encode("utf-8")) > 8_000:
            raise ValueError("worker description exceeds 8 KiB")
        if isinstance(max_depth, bool) or not isinstance(max_depth, int) or max_depth < 0:
            raise ValueError("max_depth must be a non-negative integer")
        if max_depth > MAX_WORKER_DEPTH:
            raise ValueError(f"worker maximum depth must be at most {MAX_WORKER_DEPTH}")
        if not isinstance(require_parent_running, bool):
            raise TypeError("require_parent_running must be a boolean")
        worker_id = f"worker-{uuid.uuid4().hex}"
        timestamp = utc_now()
        with self._connect() as connection:
            # Parent admission is a check-then-insert operation.  Serialize the read with
            # cancellation and other worker-tree mutations so a child cannot observe a running
            # parent and commit after that parent has been stopped by another Store connection.
            connection.execute("BEGIN IMMEDIATE")
            depth = 0
            if parent_worker_id is not None:
                parent = connection.execute(
                    "SELECT owner_id, depth, phase FROM workers WHERE id = ?", (parent_worker_id,)
                ).fetchone()
                if parent is None:
                    raise ValueError("unknown parent worker")
                if parent["owner_id"] != owner_id:
                    raise PermissionError("parent worker is owned by another caller")
                if require_parent_running and parent["phase"] != WorkerPhase.RUNNING.value:
                    raise ValueError("parent worker is not running")
                depth = int(parent["depth"]) + 1
            if depth > max_depth:
                raise ValueError("worker maximum depth exceeded")
            connection.execute(
                "INSERT INTO workers(id, owner_id, parent_worker_id, role, agent_type, description, depth, phase, created_at, updated_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (worker_id, owner_id, parent_worker_id, role, agent_type, description, depth,
                 WorkerPhase.IDLE.value, timestamp, timestamp),
            )
            self._append_worker_event(
                connection, worker_id, "worker_created",
                {"phase": WorkerPhase.IDLE.value, "depth": depth},
            )
        return self.get_worker(worker_id)  # type: ignore[return-value]

    def get_worker(self, worker_id: str) -> Worker | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM workers WHERE id = ?", (worker_id,)).fetchone()
        return self._worker_from_row(row) if row else None

    def create_automatic_solve_worker_binding(
        self, binding: AutomaticSolveWorkerBinding,
    ) -> AutomaticSolveWorkerBinding:
        """Create an initial bridge admission before the worker executor is released.

        This operation checks only durable admission identities.  The library bridge must still
        acquire automatic workspace ownership before work.  Later-generation resumption is
        deliberately unavailable until native cleanup and recovery authority have been checked.
        """
        if not isinstance(binding, AutomaticSolveWorkerBinding):
            raise TypeError("binding must be an AutomaticSolveWorkerBinding")
        if (binding.state is not AutomaticSolveWorkerBindingState.ADMITTED or binding.generation != 0
                or binding.prior_generation is not None or any(value is not None for value in (
                    binding.observation_reason, binding.stop_reason, binding.result_ref_digest,
                    binding.native_receipt_id, binding.delivery_identity,
                ))):
            raise ValueError("automatic solve binding requires initial admission")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM automatic_solve_worker_bindings WHERE binding_id = ?", (binding.binding_id,),
            ).fetchone()
            if existing is not None:
                current = self._automatic_solve_worker_binding_from_row(existing)
                if not binding_payload_equal(current, binding):
                    raise ValueError("automatic solve binding admission drift")
                self._validate_automatic_solve_worker_pins(connection, current)
                return current
            if connection.execute(
                "SELECT 1 FROM automatic_solve_worker_bindings WHERE run_id = ? OR worker_attempt_id = ?",
                (binding.run_id, binding.worker_attempt_id),
            ).fetchone() is not None:
                raise ValueError("automatic solve already has a worker binding")
            worker = connection.execute("SELECT * FROM workers WHERE id = ?", (binding.worker_id,)).fetchone()
            attempt = connection.execute(
                "SELECT * FROM worker_attempts WHERE id = ?", (binding.worker_attempt_id,),
            ).fetchone()
            if (worker is None or attempt is None or worker["owner_id"] != binding.owner_id
                    or worker["phase"] != WorkerPhase.RUNNING.value
                    or attempt["worker_id"] != binding.worker_id
                    or attempt["service_owner_id"] != binding.service_owner_id
                    or attempt["status"] != "running"):
                raise ValueError("automatic solve worker attempt is not an active reciprocal owner")
            if connection.execute(
                "SELECT 1 FROM worker_bindings WHERE worker_attempt_id = ?", (binding.worker_attempt_id,),
            ).fetchone() is not None:
                raise ValueError("automatic solve worker attempt already owns a task binding")
            run = self._validate_automatic_solve_worker_pins(connection, binding)
            if run["status"] not in {RunStatus.PENDING.value, RunStatus.RUNNING.value}:
                raise ValueError("automatic solve run is not eligible for admission")
            timestamp = utc_now()
            binding = replace(binding, created_at=timestamp, updated_at=timestamp)
            values = binding.to_dict()
            connection.execute(
                f"INSERT INTO automatic_solve_worker_bindings({','.join(values)}) "
                f"VALUES({','.join('?' for _ in values)})", tuple(values.values()),
            )
            self._append_event(connection, binding.run_id, None, "automatic_solve_worker_admitted", {
                "binding_id": binding.binding_id, "generation": binding.generation,
                "worker_id": binding.worker_id, "worker_attempt_id": binding.worker_attempt_id,
            })
        return binding

    def get_automatic_solve_worker_binding(
        self, binding_id: str, *, owner_id: str,
    ) -> AutomaticSolveWorkerBinding | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM automatic_solve_worker_bindings WHERE binding_id = ?", (binding_id,),
            ).fetchone()
        if row is None:
            return None
        binding = self._automatic_solve_worker_binding_from_row(row)
        if binding.owner_id != owner_id:
            raise PermissionError("automatic solve binding is owned by another caller")
        return binding

    def list_automatic_solve_worker_bindings(
        self, owner_id: str, *, run_id: str | None = None,
    ) -> list[AutomaticSolveWorkerBinding]:
        query = "SELECT * FROM automatic_solve_worker_bindings WHERE owner_id = ?"
        values: list[object] = [owner_id]
        if run_id is not None:
            query += " AND run_id = ?"
            values.append(run_id)
        with self._connect() as connection:
            rows = connection.execute(query + " ORDER BY run_id, generation", values).fetchall()
        return [self._automatic_solve_worker_binding_from_row(row) for row in rows]

    def compare_and_swap_automatic_solve_worker_binding(
        self, expected: AutomaticSolveWorkerBinding, *, state: AutomaticSolveWorkerBindingState,
        contract_digest: str | None = None, child_run_id: str | None = None,
        observation_reason: str | None = None, stop_reason: str | None = None,
    ) -> AutomaticSolveWorkerBinding | None:
        """Update only the exact retained generation; pins bind one way and never drift.

        ``None`` means the caller's observation lost a race.  This method neither starts nor
        settles a worker, reconciles unknown execution, nor authorizes a later generation.
        Terminal result-reference settlement is intentionally a separate create-only operation.
        """
        if not isinstance(expected, AutomaticSolveWorkerBinding):
            raise TypeError("expected must be an AutomaticSolveWorkerBinding")
        state = AutomaticSolveWorkerBindingState(state)
        allowed = {
            AutomaticSolveWorkerBindingState.ADMITTED: {AutomaticSolveWorkerBindingState.ACTIVE,
                AutomaticSolveWorkerBindingState.AWAITING_INPUT, AutomaticSolveWorkerBindingState.RECOVERY_REQUIRED,
                AutomaticSolveWorkerBindingState.UNKNOWN},
            AutomaticSolveWorkerBindingState.ACTIVE: {AutomaticSolveWorkerBindingState.AWAITING_INPUT,
                AutomaticSolveWorkerBindingState.RECOVERY_REQUIRED, AutomaticSolveWorkerBindingState.UNKNOWN},
        }
        if expected.state is AutomaticSolveWorkerBindingState.TERMINAL:
            raise ValueError("terminal automatic solve binding is immutable")
        if state != expected.state and state not in allowed.get(expected.state, set()):
            raise ValueError("automatic solve binding transition requires native recovery")
        for old, new in ((expected.contract_digest, contract_digest), (expected.child_run_id, child_run_id)):
            if old is not None and new is not None and old != new:
                raise ValueError("automatic solve binding pin drift")
        updated = replace(
            expected, state=state, contract_digest=contract_digest or expected.contract_digest,
            child_run_id=child_run_id or expected.child_run_id, observation_reason=observation_reason,
            stop_reason=stop_reason,
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if not self._automatic_solve_worker_binding_matches(connection, expected):
                return None
            self._validate_automatic_solve_worker_attempt(connection, expected)
            self._validate_automatic_solve_worker_pins(connection, updated)
            updated = replace(updated, updated_at=utc_now())
            connection.execute(
                "UPDATE automatic_solve_worker_bindings SET state = ?, contract_digest = ?, child_run_id = ?, "
                "observation_reason = ?, stop_reason = ?, updated_at = ? WHERE binding_id = ? AND generation = ?",
                (updated.state.value, updated.contract_digest, updated.child_run_id, updated.observation_reason,
                 updated.stop_reason, updated.updated_at, updated.binding_id, updated.generation),
            )
            self._append_event(connection, updated.run_id, None, "automatic_solve_worker_observed", {
                "binding_id": updated.binding_id, "generation": updated.generation,
                "state": updated.state.value, "reason": updated.observation_reason,
            })
        return updated

    def create_automatic_solve_worker_result_reference(
        self, expected: AutomaticSolveWorkerBinding, reference: AutomaticSolveWorkerResultReference,
    ) -> AutomaticSolveWorkerResultReference | None:
        """Retain one exact terminal reference, without granting native publication authority.

        The future bridge reader must independently validate native artifact/receipt bytes.
        A matching Store record alone is never proof of native success or permission to rerun.
        """
        if not isinstance(expected, AutomaticSolveWorkerBinding) or not isinstance(reference, AutomaticSolveWorkerResultReference):
            raise TypeError("automatic solve binding and result reference DTOs required")
        # Rebuild the value from its current mapping to catch mutation after DTO construction.
        validated_reference = AutomaticSolveWorkerResultReference(
            binding_id=reference.binding_id, generation=reference.generation,
            run_id=reference.run_id, worker_attempt_id=reference.worker_attempt_id,
            outcome=reference.outcome, reference=dict(reference.reference),
            sha256=reference.sha256, created_at=reference.created_at,
        )
        if validated_reference.sha256 != reference.sha256:
            raise ValueError("automatic solve result reference was mutated")
        reference = validated_reference
        if (reference.binding_id, reference.generation, reference.run_id, reference.worker_attempt_id) != (
            expected.binding_id, expected.generation, expected.run_id, expected.worker_attempt_id,
        ):
            raise ValueError("automatic solve result reference owner mismatch")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM automatic_solve_worker_result_refs WHERE binding_id = ? AND generation = ?",
                (reference.binding_id, reference.generation),
            ).fetchone()
            if existing is not None:
                retained = self._automatic_solve_worker_result_from_row(existing)
                if replace(retained, created_at="") != replace(reference, created_at=""):
                    raise ValueError("automatic solve result reference already exists")
                current_row = connection.execute(
                    "SELECT * FROM automatic_solve_worker_bindings WHERE binding_id = ?", (expected.binding_id,),
                ).fetchone()
                current = self._automatic_solve_worker_binding_from_row(current_row)
                if not binding_payload_equal(current, expected) or current.result_ref_digest != retained.sha256:
                    raise ValueError("automatic solve result reference binding mismatch")
                self._validate_automatic_solve_worker_pins(connection, current)
                return retained
            if not self._automatic_solve_worker_binding_matches(connection, expected):
                return None
            self._validate_automatic_solve_worker_attempt(connection, expected)
            if expected.state not in {AutomaticSolveWorkerBindingState.ADMITTED, AutomaticSolveWorkerBindingState.ACTIVE}:
                raise ValueError("automatic solve result requires active native observation")
            run = self._validate_automatic_solve_worker_pins(connection, expected)
            if run["status"] != reference.outcome:
                raise ValueError("automatic solve result outcome disagrees with native run")
            if reference.outcome == "succeeded" and (expected.contract_digest is None or expected.child_run_id is None):
                raise ValueError("automatic solve success requires bound contract and child")
            reference = replace(reference, created_at=utc_now())
            connection.execute(
                "INSERT INTO automatic_solve_worker_result_refs(binding_id, generation, run_id, worker_attempt_id, "
                "outcome, reference, sha256, created_at, schema_version) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (reference.binding_id, reference.generation, reference.run_id, reference.worker_attempt_id,
                 reference.outcome, json.dumps(reference.reference, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
                 reference.sha256, reference.created_at, reference.schema_version),
            )
            connection.execute(
                "UPDATE automatic_solve_worker_bindings SET state = ?, result_ref_digest = ?, updated_at = ? "
                "WHERE binding_id = ? AND generation = ?",
                (AutomaticSolveWorkerBindingState.TERMINAL.value, reference.sha256, reference.created_at,
                 reference.binding_id, reference.generation),
            )
            self._append_event(connection, expected.run_id, None, "automatic_solve_worker_result_observed", {
                "binding_id": expected.binding_id, "generation": expected.generation,
                "outcome": reference.outcome, "reference_sha256": reference.sha256,
            })
        return reference

    def get_automatic_solve_worker_result_reference(
        self, binding_id: str, *, owner_id: str, generation: int,
    ) -> AutomaticSolveWorkerResultReference | None:
        binding = self.get_automatic_solve_worker_binding(binding_id, owner_id=owner_id)
        if binding is None or binding.generation != generation:
            return None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM automatic_solve_worker_result_refs WHERE binding_id = ? AND generation = ?",
                (binding_id, generation),
            ).fetchone()
        if row is None:
            if binding.result_ref_digest is not None:
                raise ValueError("automatic solve result reference is missing")
            return None
        reference = self._automatic_solve_worker_result_from_row(row)
        if (binding.state is not AutomaticSolveWorkerBindingState.TERMINAL
                or reference.sha256 != binding.result_ref_digest
                or (reference.run_id, reference.worker_attempt_id) != (binding.run_id, binding.worker_attempt_id)):
            raise ValueError("automatic solve result reference binding mismatch")
        return reference

    @staticmethod
    def _automatic_solve_worker_binding_from_row(row) -> AutomaticSolveWorkerBinding:
        return AutomaticSolveWorkerBinding(**dict(row))

    @staticmethod
    def _automatic_solve_worker_result_from_row(row) -> AutomaticSolveWorkerResultReference:
        values = dict(row)
        values["reference"] = json.loads(values["reference"])
        return AutomaticSolveWorkerResultReference(**values)

    def _automatic_solve_worker_binding_matches(self, connection, expected) -> bool:
        row = connection.execute(
            "SELECT * FROM automatic_solve_worker_bindings WHERE binding_id = ?", (expected.binding_id,),
        ).fetchone()
        return row is not None and self._automatic_solve_worker_binding_from_row(row) == expected

    @staticmethod
    def _validate_automatic_solve_worker_attempt(connection, binding) -> None:
        attempt = connection.execute(
            "SELECT a.worker_id, a.service_owner_id, a.status, w.owner_id, w.phase "
            "FROM worker_attempts a JOIN workers w ON w.id = a.worker_id WHERE a.id = ?",
            (binding.worker_attempt_id,),
        ).fetchone()
        if (attempt is None or attempt["worker_id"] != binding.worker_id
                or attempt["service_owner_id"] != binding.service_owner_id
                or attempt["owner_id"] != binding.owner_id or attempt["status"] != "running"
                or attempt["phase"] != WorkerPhase.RUNNING.value):
            raise ValueError("automatic solve worker attempt ownership is no longer active")

    @staticmethod
    def _validate_automatic_solve_worker_pins(connection, binding):
        run = connection.execute("SELECT * FROM runs WHERE id = ?", (binding.run_id,)).fetchone()
        if run is None or run["workspace"] != binding.workspace_identity:
            raise ValueError("automatic solve workspace identity drift")
        requests = connection.execute(
            "SELECT payload FROM events WHERE run_id = ? AND type = 'evolution_requested'", (binding.run_id,),
        ).fetchall()
        if len(requests) != 1:
            raise ValueError("automatic solve lifecycle request is missing or ambiguous")
        request = json.loads(requests[0]["payload"])
        if (not isinstance(request, dict) or request.get("bundle_mode") != "compiled"
                or type(request.get("automatic_lifecycle_version")) is not int
                or request["automatic_lifecycle_version"] != 1):
            raise ValueError("automatic solve lifecycle is not enabled")
        digest = hashlib.sha256(json.dumps(request, ensure_ascii=False, sort_keys=True,
                                           separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        if digest != binding.lifecycle_digest:
            raise ValueError("automatic solve lifecycle request drift")
        if binding.contract_digest is not None:
            plan = connection.execute(
                "SELECT document FROM plan_revisions WHERE run_id = ? AND plan_id = ? AND version = ?",
                (binding.run_id, run["current_plan_id"], run["current_plan_version"]),
            ).fetchone()
            if plan is None:
                raise ValueError("automatic solve accepted contract is missing")
            from .algorithm import AlgorithmProblemContract
            document = PlanDocument.from_dict(json.loads(plan["document"]))
            if (document.algorithm_problem is None
                    or AlgorithmProblemContract.from_dict(document.algorithm_problem).digest() != binding.contract_digest):
                raise ValueError("automatic solve accepted contract drift")
        if binding.child_run_id is not None:
            if binding.contract_digest is None or binding.child_run_id == binding.run_id:
                raise ValueError("automatic solve child requires accepted contract")
            child = connection.execute("SELECT id FROM runs WHERE id = ?", (binding.child_run_id,)).fetchone()
            forward = connection.execute(
                "SELECT payload FROM events WHERE run_id = ? AND type = 'evolution_linked'", (binding.run_id,),
            ).fetchall()
            reverse = connection.execute(
                "SELECT payload FROM events WHERE run_id = ? AND type = 'evolution_parent_linked'", (binding.child_run_id,),
            ).fetchall()
            if (child is None or [json.loads(row["payload"]) for row in forward] != [{
                "evolution_run_id": binding.child_run_id, "contract_sha256": binding.contract_digest,
                "strategy": "population",
            }] or [json.loads(row["payload"]) for row in reverse] != [{
                "parent_run_id": binding.run_id, "contract_sha256": binding.contract_digest,
            }]):
                raise ValueError("automatic solve reciprocal child link drift")
        return run

    def bind_worker(
        self,
        *,
        worker_id: str,
        worker_attempt_id: str,
        run_id: str,
        task_id: str,
        task_attempt_id: str,
        service_owner_id: str,
        active_timeout: float | None = None,
    ) -> WorkerBinding:
        """Atomically bind a started worker attempt to one claimed scheduler attempt.

        The worker executor must not be released until this operation succeeds.  The checks are
        repeated inside one SQLite transaction so a caller cannot bind a worker to a different
        run, task, or attempt after it has been claimed.
        """
        if not all(isinstance(value, str) and value.strip() for value in (
            worker_id, worker_attempt_id, run_id, task_id, task_attempt_id, service_owner_id,
        )):
            raise ValueError("worker binding identities must be non-empty strings")
        if active_timeout is not None:
            if isinstance(active_timeout, bool) or not isinstance(active_timeout, (int, float)):
                raise ValueError("active timeout must be numeric")
            if not math.isfinite(active_timeout) or active_timeout <= 0 or active_timeout > 24 * 60 * 60:
                raise ValueError("active timeout must be between 0 and 86400 seconds")
        timestamp = utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute(
                "SELECT 1 FROM worker_bindings WHERE worker_id = ?", (worker_id,),
            ).fetchone() is not None:
                raise ValueError("worker already has a binding")
            if connection.execute(
                "SELECT 1 FROM automatic_solve_worker_bindings WHERE worker_attempt_id = ?",
                (worker_attempt_id,),
            ).fetchone() is not None:
                raise ValueError("worker attempt already has an automatic solve binding")
            worker = connection.execute(
                "SELECT id FROM workers WHERE id = ?", (worker_id,),
            ).fetchone()
            attempt = connection.execute(
                "SELECT id, worker_id, service_owner_id, status FROM worker_attempts WHERE id = ?",
                (worker_attempt_id,),
            ).fetchone()
            task = connection.execute(
                "SELECT id, run_id, state FROM tasks WHERE id = ?", (task_id,),
            ).fetchone()
            task_attempt = connection.execute(
                "SELECT id, task_id, status FROM attempts WHERE id = ?", (task_attempt_id,),
            ).fetchone()
            run = connection.execute(
                "SELECT id FROM runs WHERE id = ?", (run_id,),
            ).fetchone()
            if worker is None or attempt is None or task is None or task_attempt is None or run is None:
                raise ValueError("worker binding references an unknown record")
            if (
                attempt["worker_id"] != worker_id
                or attempt["service_owner_id"] != service_owner_id
                or attempt["status"] != "running"
                or task["run_id"] != run_id
                or task["state"] != TaskStatus.RUNNING.value
                or task_attempt["task_id"] != task_id
                or task_attempt["status"] != "running"
            ):
                raise ValueError("worker binding records are not an active reciprocal pair")
            connection.execute(
                "INSERT INTO worker_bindings(worker_id, worker_attempt_id, run_id, task_id, task_attempt_id, "
                "service_owner_id, status, active_timeout, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (worker_id, worker_attempt_id, run_id, task_id, task_attempt_id, service_owner_id,
                 "active", active_timeout, timestamp, timestamp),
            )
            row = connection.execute(
                "SELECT * FROM worker_bindings WHERE worker_id = ?", (worker_id,),
            ).fetchone()
        return self._worker_binding_from_row(row)  # type: ignore[arg-type]

    def get_worker_binding(self, worker_id: str) -> WorkerBinding | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM worker_bindings WHERE worker_id = ?", (worker_id,),
            ).fetchone()
        return self._worker_binding_from_row(row) if row else None

    def list_worker_bindings(self, run_id: str | None = None, *, status: str | None = None) -> list[WorkerBinding]:
        query = "SELECT * FROM worker_bindings WHERE 1 = 1"
        args: list[object] = []
        if run_id is not None:
            query += " AND run_id = ?"
            args.append(run_id)
        if status is not None:
            query += " AND status = ?"
            args.append(status)
        query += " ORDER BY created_at, worker_id"
        with self._connect() as connection:
            rows = connection.execute(query, args).fetchall()
        return [self._worker_binding_from_row(row) for row in rows]

    def settle_worker_binding(self, worker_id: str, status: str) -> bool:
        if status not in {"active", "settled", "discarded", "lost"}:
            raise ValueError("invalid worker binding status")
        with self._connect() as connection:
            changed = connection.execute(
                "UPDATE worker_bindings SET status = ?, updated_at = ? WHERE worker_id = ? AND status IN (?, ?)",
                (status, utc_now(), worker_id, "active", "delivering"),
            ).rowcount
        return changed == 1

    def claim_worker_binding_delivery(
        self,
        *,
        worker_id: str,
        worker_attempt_id: str,
        run_id: str,
        task_id: str,
        task_attempt_id: str,
    ) -> bool:
        """Reserve one active binding for result materialization.

        A worker may be observed by more than one foreground process after it becomes idle.
        Reserving the binding before writing task artifacts keeps only one observer responsible
        for staging and committing the result; later observers can return the committed envelope
        without creating duplicate ledger rows.
        """
        timestamp = utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            changed = connection.execute(
                "UPDATE worker_bindings SET status = ?, updated_at = ? "
                "WHERE worker_id = ? AND worker_attempt_id = ? AND run_id = ? AND task_id = ? "
                "AND task_attempt_id = ? AND status = ?",
                (
                    "delivering", timestamp, worker_id, worker_attempt_id, run_id, task_id,
                    task_attempt_id, "active",
                ),
            ).rowcount
        return changed == 1

    def recover_worker_binding_delivery(
        self, *, worker_id: str, worker_attempt_id: str, stale_after: float,
    ) -> bool:
        """Re-open a delivery reservation only after its owner lease is stale.

        The caller must already hold the binding's delivery liveness lock.  The timestamp
        guard keeps a live observer's ``delivering`` reservation from being stolen merely
        because a second observer arrived.
        """
        if isinstance(stale_after, bool) or not isinstance(stale_after, (int, float)) or stale_after <= 0:
            raise ValueError("stale_after must be a positive number")
        now = datetime.now(UTC)
        cutoff = now.timestamp() - float(stale_after)
        timestamp = now.isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT updated_at FROM worker_bindings WHERE worker_id = ? AND worker_attempt_id = ? "
                "AND status = ?",
                (worker_id, worker_attempt_id, "delivering"),
            ).fetchone()
            if row is None:
                return False
            try:
                parsed = datetime.fromisoformat(row["updated_at"])
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=UTC)
                updated = parsed.timestamp()
            except (TypeError, ValueError, OverflowError):
                return False
            if updated > cutoff:
                return False
            return connection.execute(
                "UPDATE worker_bindings SET status = ?, updated_at = ? "
                "WHERE worker_id = ? AND worker_attempt_id = ? AND status = ? AND updated_at = ?",
                ("active", timestamp, worker_id, worker_attempt_id, "delivering", row["updated_at"]),
            ).rowcount == 1

    def complete_worker_binding(
        self,
        *,
        worker_id: str,
        worker_attempt_id: str,
        run_id: str,
        task_id: str,
        task_attempt_id: str,
        outcome: str,
        result_path: str | None,
        error: str | None,
        agent_event_type: str,
        agent_payload: Mapping[str, Any],
        evaluation_payload: Mapping[str, Any],
    ) -> bool:
        """Atomically deliver one finished worker result to its exact active task binding.

        Result files are staged by the controller before this call.  This is the single durable
        delivery point: cancellation, recovery, or a stale binding makes the transaction a
        no-op, allowing the caller to discard staged output instead of publishing it late.
        """
        transitions = {
            "succeeded": (TaskStatus.SUCCEEDED.value, "succeeded", "task_succeeded"),
            "failed": (TaskStatus.FAILED.value, "failed", "task_failed"),
            "retry": (TaskStatus.READY.value, "failed", "task_retry_scheduled"),
        }
        if outcome not in transitions:
            raise ValueError("invalid worker binding completion outcome")
        if agent_event_type not in {"agent_finished", "agent_failed"}:
            raise ValueError("invalid worker binding agent event type")
        if not all(isinstance(value, str) and value for value in (
            worker_id, worker_attempt_id, run_id, task_id, task_attempt_id,
        )):
            raise ValueError("worker binding completion identities must be non-empty strings")
        task_state, attempt_state, task_event_type = transitions[outcome]
        timestamp = utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            binding = connection.execute(
                "SELECT * FROM worker_bindings WHERE worker_id = ?",
                (worker_id,),
            ).fetchone()
            task = connection.execute(
                "SELECT run_id, state FROM tasks WHERE id = ?", (task_id,),
            ).fetchone()
            task_attempt = connection.execute(
                "SELECT task_id, status FROM attempts WHERE id = ?", (task_attempt_id,),
            ).fetchone()
            worker_attempt = connection.execute(
                "SELECT worker_id, status, service_owner_id FROM worker_attempts WHERE id = ?",
                (worker_attempt_id,),
            ).fetchone()
            worker = connection.execute(
                "SELECT owner_id, phase FROM workers WHERE id = ?", (worker_id,),
            ).fetchone()
            run = connection.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
            if (
                binding is None
                or task is None
                or task_attempt is None
                or worker_attempt is None
                or worker is None
                or run is None
                or binding["worker_attempt_id"] != worker_attempt_id
                or binding["run_id"] != run_id
                or binding["task_id"] != task_id
                or binding["task_attempt_id"] != task_attempt_id
                or binding["status"] not in {"active", "delivering"}
                or task["run_id"] != run_id
                or task["state"] != TaskStatus.RUNNING.value
                or task_attempt["task_id"] != task_id
                or task_attempt["status"] != "running"
                or worker_attempt["worker_id"] != worker_id
                or worker_attempt["status"] != "finished"
                or worker_attempt["service_owner_id"] != binding["service_owner_id"]
                or worker["owner_id"] != run_id
                or worker["phase"] != WorkerPhase.IDLE.value
                or run["status"] in {
                    RunStatus.SUCCEEDED.value,
                    RunStatus.FAILED.value,
                    RunStatus.CANCELLED.value,
                }
            ):
                return False
            updated_task = connection.execute(
                "UPDATE tasks SET state = ?, result_path = ?, last_error = ?, updated_at = ? "
                "WHERE id = ? AND state = ?",
                (task_state, result_path, error, timestamp, task_id, TaskStatus.RUNNING.value),
            ).rowcount
            updated_attempt = connection.execute(
                "UPDATE attempts SET status = ?, finished_at = ?, heartbeat_at = ?, error = ? "
                "WHERE id = ? AND task_id = ? AND status = ?",
                (attempt_state, timestamp, timestamp, error, task_attempt_id, task_id, "running"),
            ).rowcount
            updated_binding = connection.execute(
                "UPDATE worker_bindings SET status = ?, updated_at = ? "
                "WHERE worker_id = ? AND status IN (?, ?)",
                ("settled", timestamp, worker_id, "active", "delivering"),
            ).rowcount
            if updated_task != 1 or updated_attempt != 1 or updated_binding != 1:
                raise RuntimeError("worker binding completion lost its transaction guard")
            self._append_event(connection, run_id, task_id, agent_event_type, dict(agent_payload))
            self._append_event(connection, run_id, task_id, "task_evaluated", dict(evaluation_payload))
            if outcome == "retry":
                self._append_event(
                    connection, run_id, task_id, task_event_type,
                    {"attempt_id": task_attempt_id, "error": error},
                )
            else:
                self._append_event(
                    connection, run_id, task_id, task_event_type,
                    {"attempt_id": task_attempt_id, "result_path": result_path, "error": error},
                )
            # Keep the one-task foreground delegate linearizable with cancellation: once the
            # delivery commits the resulting run terminal state is committed in the same lock.
            rows = connection.execute(
                "SELECT state, input_question FROM tasks WHERE run_id = ?", (run_id,),
            ).fetchall()
            states = {row["state"] for row in rows}
            if TaskStatus.FAILED.value in states or TaskStatus.BLOCKED.value in states:
                run_state = RunStatus.FAILED.value
            elif (states and states.issubset({TaskStatus.SUCCEEDED.value, TaskStatus.SUPERSEDED.value})
                  and TaskStatus.SUCCEEDED.value in states):
                run_state = RunStatus.SUCCEEDED.value
            elif any(row["state"] == TaskStatus.WAITING.value
                     and _has_input_question(row["input_question"]) for row in rows):
                run_state = RunStatus.AWAITING_INPUT.value
            elif TaskStatus.CANCELLED.value in states:
                run_state = RunStatus.CANCELLED.value
            else:
                run_state = RunStatus.RUNNING.value
            connection.execute(
                "UPDATE runs SET status = ?, updated_at = ? WHERE id = ? AND status != ?",
                (run_state, timestamp, run_id, RunStatus.CANCELLED.value),
            )
            if run_state in {RunStatus.SUCCEEDED.value, RunStatus.FAILED.value}:
                self._append_event(connection, run_id, None, f"run_{run_state}", {})
        return True

    def persist_worker_result(
        self,
        worker_id: str,
        worker_attempt_id: str,
        result: AgentResult,
        *,
        artifact_manifest: Sequence[Mapping[str, object]] = (),
    ) -> WorkerResultEnvelope:
        """Persist one complete adapter result with a canonical JSON integrity digest.

        The operation is idempotent for the same attempt.  A different result for an already
        persisted attempt is rejected, so a late callback cannot replace the durable envelope.
        """
        if not isinstance(result, AgentResult):
            raise TypeError("worker result must be an AgentResult")
        payload = self._worker_result_payload(result, artifact_manifest)
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(encoded) > _MAX_WORKER_RESULT_ENVELOPE_BYTES:
            raise ValueError("worker result envelope exceeds the size limit")
        digest = hashlib.sha256(encoded).hexdigest()
        timestamp = utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            attempt = connection.execute(
                "SELECT worker_id FROM worker_attempts WHERE id = ?", (worker_attempt_id,),
            ).fetchone()
            if attempt is None or attempt["worker_id"] != worker_id:
                raise ValueError("worker result references an unknown attempt")
            existing = connection.execute(
                "SELECT * FROM worker_attempt_results WHERE worker_attempt_id = ?",
                (worker_attempt_id,),
            ).fetchone()
            if existing is None:
                connection.execute(
                    "INSERT INTO worker_attempt_results(worker_attempt_id, worker_id, schema_version, payload, sha256, size, created_at) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?)",
                    (worker_attempt_id, worker_id, _WORKER_RESULT_SCHEMA_VERSION,
                     encoded.decode("utf-8"), digest, len(encoded), timestamp),
                )
                self._append_worker_event(
                    connection,
                    worker_id,
                    "worker_result_persisted",
                    {"sha256": digest, "size": len(encoded)},
                    worker_attempt_id,
                )
            elif existing["sha256"] != digest or existing["payload"] != encoded.decode("utf-8"):
                raise ValueError("worker result envelope already exists with different content")
            row = connection.execute(
                "SELECT * FROM worker_attempt_results WHERE worker_attempt_id = ?",
                (worker_attempt_id,),
            ).fetchone()
        return self._worker_result_from_row(row)  # type: ignore[arg-type]

    def get_worker_result(
        self,
        worker_id: str,
        worker_attempt_id: str | None = None,
        *,
        owner_id: str | None = None,
    ) -> WorkerResultEnvelope | None:
        """Read and verify a durable result envelope for an owned worker attempt."""
        query = (
            "SELECT r.* FROM worker_attempt_results r JOIN workers w ON w.id = r.worker_id "
            "WHERE r.worker_id = ?"
        )
        args: list[object] = [worker_id]
        if worker_attempt_id is not None:
            query += " AND r.worker_attempt_id = ?"
            args.append(worker_attempt_id)
        if owner_id is not None:
            query += " AND w.owner_id = ?"
            args.append(owner_id)
        query += " ORDER BY r.created_at DESC LIMIT 1"
        with self._connect() as connection:
            row = connection.execute(query, args).fetchone()
        return self._worker_result_from_row(row) if row else None

    def list_worker_results(
        self,
        worker_id: str,
        *,
        owner_id: str | None = None,
    ) -> list[WorkerResultEnvelope]:
        query = (
            "SELECT r.* FROM worker_attempt_results r JOIN workers w ON w.id = r.worker_id "
            "WHERE r.worker_id = ?"
        )
        args: list[object] = [worker_id]
        if owner_id is not None:
            query += " AND w.owner_id = ?"
            args.append(owner_id)
        query += " ORDER BY r.created_at, r.worker_attempt_id"
        with self._connect() as connection:
            rows = connection.execute(query, args).fetchall()
        return [self._worker_result_from_row(row) for row in rows]

    def list_workers(self, owner_id: str, *, phase: WorkerPhase | None = None) -> list[Worker]:
        query = "SELECT * FROM workers WHERE owner_id = ?"
        args: list[object] = [owner_id]
        if phase is not None:
            query += " AND phase = ?"
            args.append(phase.value)
        query += " ORDER BY created_at, id"
        with self._connect() as connection:
            rows = connection.execute(query, args).fetchall()
        return [self._worker_from_row(row) for row in rows]

    def list_worker_children(self, worker_id: str) -> list[Worker]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM workers WHERE parent_worker_id = ? ORDER BY created_at, id",
                (worker_id,),
            ).fetchall()
        return [self._worker_from_row(row) for row in rows]

    def start_worker_attempt(
        self,
        worker_id: str,
        owner_id: str,
        prompt: str,
        *,
        service_owner_id: str | None = None,
        input_ids: Sequence[str] = (),
        require_parent_running: bool = False,
        reject_cancelled_parent: bool = False,
        allow_stopped_resume: bool = True,
    ) -> WorkerAttempt:
        if not prompt.strip() or len(prompt.encode("utf-8")) > 64 * 1024:
            raise ValueError("worker prompt must be non-empty and at most 64 KiB")
        if service_owner_id is not None and (
            not isinstance(service_owner_id, str)
            or not service_owner_id.strip()
            or len(service_owner_id) > 128
        ):
            raise ValueError("worker service owner must be a non-empty bounded identifier")
        if (not isinstance(require_parent_running, bool)
                or not isinstance(reject_cancelled_parent, bool)
                or not isinstance(allow_stopped_resume, bool)):
            raise TypeError("worker attempt policy flags must be booleans")
        if isinstance(input_ids, (str, bytes)):
            raise TypeError("worker input identities must be a sequence of strings")
        consumed_ids = tuple(input_ids)
        if any(not isinstance(item, str) or not item for item in consumed_ids):
            raise ValueError("worker input identities must be non-empty strings")
        if len(consumed_ids) != len(set(consumed_ids)):
            raise ValueError("worker input identities must be unique")
        attempt_id = f"worker-attempt-{uuid.uuid4().hex}"
        timestamp = utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            worker = connection.execute(
                "SELECT * FROM workers WHERE id = ? AND owner_id = ?", (worker_id, owner_id)
            ).fetchone()
            if worker is None:
                raise PermissionError("worker is not owned by caller")
            if worker["phase"] == WorkerPhase.RUNNING.value:
                raise ValueError("worker is already running")
            if connection.execute(
                "SELECT 1 FROM automatic_solve_worker_bindings WHERE worker_id = ?", (worker_id,),
            ).fetchone() is not None:
                raise ValueError("automatic solve worker requires explicit native bridge resume")
            if not allow_stopped_resume and worker["stop_reason"] is not None:
                raise ValueError("worker was stopped before its attempt could start")
            if require_parent_running:
                parent_id = worker["parent_worker_id"]
                if parent_id is None:
                    raise ValueError("worker parent is required")
                parent = connection.execute(
                    "SELECT owner_id, phase FROM workers WHERE id = ?", (parent_id,)
                ).fetchone()
                if parent is None or parent["owner_id"] != owner_id:
                    raise PermissionError("worker parent is not owned by caller")
                if parent["phase"] != WorkerPhase.RUNNING.value:
                    raise ValueError("parent worker is not running")
            elif reject_cancelled_parent and worker["parent_worker_id"] is not None:
                parent = connection.execute(
                    "SELECT owner_id, stop_reason FROM workers WHERE id = ?",
                    (worker["parent_worker_id"],),
                ).fetchone()
                if parent is None or parent["owner_id"] != owner_id:
                    raise PermissionError("worker parent is not owned by caller")
                if parent["stop_reason"] in {
                    WorkerStopReason.CANCELLED.value,
                    WorkerStopReason.PARENT_CANCELLED.value,
                }:
                    raise ValueError("parent worker was cancelled")
            if connection.execute(
                "SELECT 1 FROM worker_attempts a WHERE a.worker_id = ? AND "
                "(a.status = 'running' OR EXISTS (SELECT 1 FROM worker_attempt_processes p "
                "WHERE p.attempt_id = a.id)) LIMIT 1",
                (worker_id,),
            ).fetchone():
                raise ValueError("worker still has an active attempt or retained process ownership")
            if consumed_ids:
                current_ids = {
                    row["id"] for row in connection.execute(
                        "SELECT id FROM worker_inputs WHERE worker_id = ?", (worker_id,),
                    ).fetchall()
                }
                if not set(consumed_ids).issubset(current_ids):
                    raise ValueError("worker input identities changed before attempt start")
            connection.execute(
                "INSERT INTO worker_attempts(id, worker_id, prompt, status, started_at, service_owner_id) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                (attempt_id, worker_id, prompt, "running", timestamp, service_owner_id),
            )
            connection.executemany(
                "DELETE FROM worker_inputs WHERE worker_id = ? AND id = ?",
                [(worker_id, input_id) for input_id in consumed_ids],
            )
            connection.execute(
                "UPDATE workers SET phase = ?, stop_reason = NULL, last_error = NULL, updated_at = ? WHERE id = ?",
                (WorkerPhase.RUNNING.value, timestamp, worker_id),
            )
            self._append_worker_event(connection, worker_id, "worker_started", {"phase": "running"}, attempt_id)
            row = connection.execute("SELECT * FROM worker_attempts WHERE id = ?", (attempt_id,)).fetchone()
        return self._worker_attempt_from_row(row)  # type: ignore[arg-type]

    def get_worker_attempt(
        self,
        worker_id: str,
        attempt_id: str,
        *,
        owner_id: str | None = None,
        service_owner_id: str | None = None,
    ) -> WorkerAttempt | None:
        query = (
            "SELECT a.* FROM worker_attempts a JOIN workers w ON w.id = a.worker_id "
            "WHERE a.worker_id = ? AND a.id = ?"
        )
        args: list[object] = [worker_id, attempt_id]
        if owner_id is not None:
            query += " AND w.owner_id = ?"
            args.append(owner_id)
        if service_owner_id is not None:
            query += " AND a.service_owner_id = ?"
            args.append(service_owner_id)
        with self._connect() as connection:
            row = connection.execute(query, args).fetchone()
        return self._worker_attempt_from_row(row) if row else None

    def list_worker_owned_attempts(self, owner_id: str) -> list[WorkerAttempt]:
        """Find scoped recovery candidates without claiming that any owner has died.

        Legacy attempts have no service owner and therefore no verifiable liveness authority.
        Terminal attempts remain visible while they retain process cleanup obligations.
        """
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT a.* FROM worker_attempts a JOIN workers w ON w.id = a.worker_id "
                "WHERE w.owner_id = ? AND a.service_owner_id IS NOT NULL AND "
                "(a.status = 'running' OR EXISTS (SELECT 1 FROM worker_attempt_processes p "
                "WHERE p.attempt_id = a.id)) ORDER BY a.started_at, a.id",
                (owner_id,),
            ).fetchall()
        return [self._worker_attempt_from_row(row) for row in rows]

    def register_worker_process(
        self, worker_id: str, attempt_id: str, service_owner_id: str, pid: int, pgid: int,
    ) -> bool:
        """Retain one exact execution's process until its cleanup is verified.

        A launch racing with cancellation can arrive after terminal settlement. Registering it
        still matters: the execution owner must clean the process before releasing its lock.
        """
        if any(isinstance(value, bool) or not isinstance(value, int) or value <= 1 for value in (pid, pgid)):
            raise ValueError("worker process identifiers must be integers greater than one")
        with self._connect() as connection:
            inserted = connection.execute(
                "INSERT INTO worker_attempt_processes(attempt_id, pid, pgid, created_at) "
                "SELECT id, ?, ?, ? FROM worker_attempts "
                "WHERE worker_id = ? AND id = ? AND service_owner_id = ? "
                "ON CONFLICT(attempt_id, pid, pgid) DO UPDATE SET created_at = worker_attempt_processes.created_at",
                (pid, pgid, utc_now(), worker_id, attempt_id, service_owner_id),
            ).rowcount
        return inserted == 1

    def list_worker_processes(
        self, worker_id: str, attempt_id: str, service_owner_id: str,
    ) -> list[WorkerProcess]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT a.worker_id, a.id AS attempt_id, a.service_owner_id, p.pid, p.pgid "
                "FROM worker_attempt_processes p JOIN worker_attempts a ON a.id = p.attempt_id "
                "WHERE a.worker_id = ? AND a.id = ? AND a.service_owner_id = ? "
                "ORDER BY p.created_at, p.pid, p.pgid",
                (worker_id, attempt_id, service_owner_id),
            ).fetchall()
        return [WorkerProcess(**dict(row)) for row in rows]

    def clear_worker_process(
        self, worker_id: str, attempt_id: str, service_owner_id: str, pid: int, pgid: int,
    ) -> bool:
        with self._connect() as connection:
            deleted = connection.execute(
                "DELETE FROM worker_attempt_processes WHERE attempt_id = ? AND pid = ? AND pgid = ? "
                "AND EXISTS (SELECT 1 FROM worker_attempts a WHERE a.id = attempt_id "
                "AND a.worker_id = ? AND a.service_owner_id = ?)",
                (attempt_id, pid, pgid, worker_id, service_owner_id),
            ).rowcount
        return deleted == 1

    def append_worker_input(self, worker_id: str, owner_id: str, content: str) -> bool:
        if not content.strip() or len(content.encode("utf-8")) > 16 * 1024:
            raise ValueError("worker input must be non-empty and at most 16 KiB")
        timestamp = utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT id, phase FROM workers WHERE id = ? AND owner_id = ?", (worker_id, owner_id)
            ).fetchone()
            if row is None:
                raise PermissionError("worker is not owned by caller")
            if row["phase"] != WorkerPhase.RUNNING.value:
                raise ValueError("worker is not running")
            input_id = f"worker-input-{uuid.uuid4().hex}"
            connection.execute(
                "INSERT INTO worker_inputs(id, worker_id, content, created_at) VALUES(?, ?, ?, ?)",
                (input_id, worker_id, content, timestamp),
            )
            self._append_worker_event(connection, worker_id, "worker_input", {"input_id": input_id})
        return True

    def list_worker_attempts(self, worker_id: str, owner_id: str | None = None) -> list[WorkerAttempt]:
        with self._connect() as connection:
            if owner_id is None:
                rows = connection.execute(
                    "SELECT a.* FROM worker_attempts a WHERE a.worker_id = ? ORDER BY a.started_at, a.id",
                    (worker_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT a.* FROM worker_attempts a JOIN workers w ON w.id = a.worker_id WHERE a.worker_id = ? AND w.owner_id = ? ORDER BY a.started_at, a.id",
                    (worker_id, owner_id),
                ).fetchall()
        return [self._worker_attempt_from_row(row) for row in rows]

    def list_worker_inputs(self, worker_id: str, *, consume: bool = False) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, content FROM worker_inputs WHERE worker_id = ? ORDER BY created_at, id",
                (worker_id,),
            ).fetchall()
            values = [row["content"] for row in rows]
            if consume and rows:
                connection.executemany("DELETE FROM worker_inputs WHERE id = ?", [(row["id"],) for row in rows])
        return values

    def list_worker_input_records(self, worker_id: str) -> list[tuple[str, str]]:
        """Snapshot message identities so resumption only consumes incorporated inputs."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, content FROM worker_inputs WHERE worker_id = ? ORDER BY created_at, id",
                (worker_id,),
            ).fetchall()
        return [(row["id"], row["content"]) for row in rows]

    def consume_worker_inputs(self, worker_id: str, owner_id: str, input_ids: Sequence[str]) -> int:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute(
                "SELECT 1 FROM workers WHERE id = ? AND owner_id = ?", (worker_id, owner_id),
            ).fetchone() is None:
                raise PermissionError("worker is not owned by caller")
            deleted = connection.executemany(
                "DELETE FROM worker_inputs WHERE id = ? AND worker_id = ?",
                [(input_id, worker_id) for input_id in input_ids],
            ).rowcount
        return deleted

    def settle_worker(
        self,
        worker_id: str,
        attempt_id: str,
        outcome: WorkerOutcome,
        *,
        result: str | None = None,
        result_ref: str | None = None,
        reason: WorkerStopReason | None = None,
        delivery: str | None = None,
    ) -> Worker | None:
        if result is not None and len(result.encode("utf-8")) > 64 * 1024:
            result = result.encode("utf-8")[-(64 * 1024):].decode("utf-8", errors="ignore")
        if result_ref is not None and (
            not isinstance(result_ref, str)
            or re.fullmatch(r"worker-result-worker-attempt-[0-9a-f]{32}-[0-9a-f]{64}", result_ref) is None
        ):
            raise ValueError("result_ref must be a bounded worker result reference")
        if delivery not in {None, "waiter", "notification"}:
            raise ValueError("delivery must be waiter, notification, or None")
        timestamp = utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            attempt = connection.execute(
                "SELECT worker_id, status FROM worker_attempts WHERE id = ?", (attempt_id,)
            ).fetchone()
            if attempt is None or attempt["worker_id"] != worker_id:
                return None
            if attempt["status"] != "running":
                return self._worker_from_row(
                    connection.execute("SELECT * FROM workers WHERE id = ?", (worker_id,)).fetchone()
                )
            error = reason.value if reason is not None else None
            connection.execute(
                "UPDATE worker_attempts SET status = ?, finished_at = ?, outcome = ?, result = ?, error = ? WHERE id = ? AND status = ?",
                ("finished", timestamp, outcome.value, result, error, attempt_id, "running"),
            )
            connection.execute(
                "UPDATE workers SET phase = ?, outcome = ?, stop_reason = ?, result = ?, result_ref = ?, last_error = ?, updated_at = ? WHERE id = ?",
                (WorkerPhase.IDLE.value, outcome.value, reason.value if reason else None, result, result_ref, error, timestamp, worker_id),
            )
            self._append_worker_event(
                connection, worker_id, "worker_settled",
                {"phase": "idle", "outcome": outcome.value, **({"reason": reason.value} if reason else {})},
                attempt_id,
            )
            if delivery is not None:
                self._append_worker_event(
                    connection,
                    worker_id,
                    "worker_result_delivered" if delivery == "waiter" else "worker_notification",
                    {"delivery": delivery, "outcome": outcome.value},
                    attempt_id,
                )
            row = connection.execute("SELECT * FROM workers WHERE id = ?", (worker_id,)).fetchone()
        return self._worker_from_row(row) if row else None

    def cancel_worker_tree(self, worker_id: str, owner_id: str) -> list[str]:
        timestamp = utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            root = connection.execute(
                "SELECT id FROM workers WHERE id = ? AND owner_id = ?", (worker_id, owner_id)
            ).fetchone()
            if root is None:
                raise PermissionError("worker is not owned by caller")
            ids: list[str] = []
            frontier = [worker_id]
            while frontier:
                current = frontier.pop()
                ids.append(current)
                children = connection.execute(
                    "SELECT id FROM workers WHERE parent_worker_id = ? AND owner_id = ?", (current, owner_id)
                ).fetchall()
                frontier.extend(row["id"] for row in children)
            for index, current in enumerate(ids):
                connection.execute(
                    "UPDATE worker_attempts SET status = ?, finished_at = ?, outcome = ?, error = ? WHERE worker_id = ? AND status = ?",
                    (
                        "finished",
                        timestamp,
                        WorkerOutcome.STOPPED.value,
                        (WorkerStopReason.CANCELLED if index == 0 else WorkerStopReason.PARENT_CANCELLED).value,
                        current,
                        "running",
                    ),
                )
                connection.execute(
                    "UPDATE workers SET phase = ?, outcome = ?, stop_reason = ?, updated_at = ? "
                    "WHERE id = ? AND (phase = ? OR (phase = ? AND outcome IS NULL))",
                    (
                        WorkerPhase.IDLE.value,
                        WorkerOutcome.STOPPED.value,
                        (WorkerStopReason.CANCELLED if index == 0 else WorkerStopReason.PARENT_CANCELLED).value,
                        timestamp,
                        current,
                        WorkerPhase.RUNNING.value,
                        WorkerPhase.IDLE.value,
                    ),
                )
                if connection.execute(
                    "SELECT changes()"
                ).fetchone()[0]:
                    reason = WorkerStopReason.CANCELLED if index == 0 else WorkerStopReason.PARENT_CANCELLED
                    self._append_worker_event(
                        connection,
                        current,
                        "worker_cancelled",
                        {"outcome": "stopped", "reason": reason.value},
                    )
        return ids

    def reconcile_workers(
        self,
        *,
        owner_id: str | None = None,
        service_owner_id: str | None = None,
        worker_id: str | None = None,
        attempt_id: str | None = None,
    ) -> int:
        """Settle one verified abandoned owner scope, after process cleanup.

        The caller must hold the service owner's liveness lock while calling this operation.
        Merely opening a Store or discovering a candidate is never evidence of owner death.
        Omitted scopes intentionally preserve legacy calls as read-only no-ops.
        """
        if not all((owner_id, service_owner_id, worker_id, attempt_id)):
            return 0
        timestamp = utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            changed = connection.execute(
                "UPDATE worker_attempts SET status = ?, finished_at = ?, outcome = ?, error = ? "
                "WHERE id = ? AND worker_id = ? AND service_owner_id = ? AND status = ? "
                "AND EXISTS (SELECT 1 FROM workers w WHERE w.id = worker_id "
                "AND w.owner_id = ? AND w.phase = ?) "
                "AND NOT EXISTS (SELECT 1 FROM worker_attempt_processes p WHERE p.attempt_id = worker_attempts.id) "
                "AND NOT EXISTS (SELECT 1 FROM worker_attempts other WHERE other.worker_id = worker_attempts.worker_id "
                "AND other.id != worker_attempts.id AND other.status = ?)",
                (
                    "finished", timestamp, WorkerOutcome.LOST.value, WorkerStopReason.RESTART.value,
                    attempt_id, worker_id, service_owner_id, "running", owner_id,
                    WorkerPhase.RUNNING.value, "running",
                ),
            ).rowcount
            if changed != 1:
                return 0
            connection.execute(
                "UPDATE workers SET phase = ?, outcome = ?, stop_reason = ?, last_error = ?, updated_at = ? "
                "WHERE id = ? AND owner_id = ? AND phase = ?",
                (
                    WorkerPhase.IDLE.value, WorkerOutcome.LOST.value, WorkerStopReason.RESTART.value,
                    "controller restarted before worker completed", timestamp, worker_id, owner_id,
                    WorkerPhase.RUNNING.value,
                ),
            )
            # A delegated task binding is part of this exact worker attempt's durable
            # ownership record.  Recover it in the same transaction so callers never
            # observe a lost worker paired with a still-active binding.
            connection.execute(
                "UPDATE worker_bindings SET status = ?, updated_at = ? "
                "WHERE worker_id = ? AND worker_attempt_id = ? AND service_owner_id = ? "
                "AND status IN (?, ?)",
                ("lost", timestamp, worker_id, attempt_id, service_owner_id, "active", "delivering"),
            )
            self._append_worker_event(
                connection, worker_id, "worker_lost", {"outcome": "lost", "reason": "restart"}, attempt_id,
            )
        return 1

    def list_worker_events(self, worker_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT id, type, payload, created_at FROM worker_events WHERE worker_id = ? ORDER BY created_at, id", (worker_id,)).fetchall()
        return [{"id": row["id"], "type": row["type"], "payload": json.loads(row["payload"]), "created_at": row["created_at"]} for row in rows]

    @staticmethod
    def _append_worker_event(connection: sqlite3.Connection, worker_id: str, event_type: str, payload: dict[str, Any], identity: str | None = None) -> bool:
        event_id = f"worker-event-{event_type}-{identity or uuid.uuid4().hex}"
        return connection.execute(
            "INSERT OR IGNORE INTO worker_events(id, worker_id, type, payload, created_at) VALUES(?, ?, ?, ?, ?)",
            (event_id, worker_id, event_type, json.dumps(payload, sort_keys=True), utc_now()),
        ).rowcount == 1

    @staticmethod
    def _worker_from_row(row: sqlite3.Row | None) -> Worker | None:
        if row is None:
            return None
        return Worker(
            id=row["id"], owner_id=row["owner_id"], parent_worker_id=row["parent_worker_id"],
            role=row["role"], agent_type=row["agent_type"], description=row["description"],
            depth=row["depth"], phase=WorkerPhase(row["phase"]),
            outcome=WorkerOutcome(row["outcome"]) if row["outcome"] else None,
            stop_reason=WorkerStopReason(row["stop_reason"]) if row["stop_reason"] else None,
            result=row["result"], last_error=row["last_error"], created_at=row["created_at"], updated_at=row["updated_at"],
            result_ref=row["result_ref"],
        )

    @staticmethod
    def _worker_attempt_from_row(row: sqlite3.Row) -> WorkerAttempt:
        return WorkerAttempt(
            id=row["id"], worker_id=row["worker_id"], prompt=row["prompt"], status=row["status"],
            started_at=row["started_at"], finished_at=row["finished_at"],
            outcome=WorkerOutcome(row["outcome"]) if row["outcome"] else None,
            result=row["result"], error=row["error"],
            service_owner_id=row["service_owner_id"],
        )

    @staticmethod
    def _worker_binding_from_row(row: sqlite3.Row) -> WorkerBinding:
        return WorkerBinding(
            worker_id=row["worker_id"], worker_attempt_id=row["worker_attempt_id"],
            run_id=row["run_id"], task_id=row["task_id"], task_attempt_id=row["task_attempt_id"],
            service_owner_id=row["service_owner_id"], status=row["status"],
            active_timeout=row["active_timeout"], created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _worker_result_payload(
        result: AgentResult,
        artifact_manifest: Sequence[Mapping[str, object]],
    ) -> dict[str, object]:
        if isinstance(artifact_manifest, (str, bytes)):
            raise TypeError("artifact manifest must be a sequence of objects")
        supplied = tuple(artifact_manifest)
        if not supplied and result.artifacts:
            supplied = tuple({"path": path} for path in result.artifacts)
        manifest: list[dict[str, object]] = []
        seen: set[str] = set()
        for item in supplied:
            if not isinstance(item, Mapping):
                raise TypeError("artifact manifest entries must be objects")
            if set(item) - {"path", "size", "sha256"}:
                raise ValueError("artifact manifest contains unsupported fields")
            path = item.get("path")
            size = item.get("size")
            digest = item.get("sha256")
            if not isinstance(path, str) or not path or path in seen:
                raise ValueError("artifact manifest contains an invalid or duplicate path")
            if "\\" in path or Path(path).is_absolute() or any(part in {".", ".."} for part in Path(path).parts):
                raise ValueError("artifact manifest paths must be run-relative")
            if size is not None and (isinstance(size, bool) or not isinstance(size, int) or size < 0):
                raise ValueError("artifact manifest size is invalid")
            if digest is not None and (not isinstance(digest, str) or _SHA256.fullmatch(digest) is None):
                raise ValueError("artifact manifest digest is invalid")
            seen.add(path)
            entry: dict[str, object] = {"path": path}
            if size is not None:
                entry["size"] = size
            if digest is not None:
                entry["sha256"] = digest
            manifest.append(entry)
        if tuple(item["path"] for item in manifest) != result.artifacts:
            raise ValueError("artifact manifest must match declared result artifacts")
        return {
            "schema_version": _WORKER_RESULT_SCHEMA_VERSION,
            "adapter_name": result.adapter_name,
            "role": result.role,
            "status": result.status,
            "text": result.text,
            "error": result.error,
            "metadata": dict(result.metadata),
            "artifacts": list(result.artifacts),
            "artifact_manifest": manifest,
        }

    @staticmethod
    def _worker_result_from_row(row: sqlite3.Row) -> WorkerResultEnvelope:
        payload = row["payload"]
        if (
            not isinstance(payload, str)
            or row["schema_version"] != _WORKER_RESULT_SCHEMA_VERSION
            or not isinstance(row["sha256"], str)
            or _SHA256.fullmatch(row["sha256"]) is None
            or not isinstance(row["size"], int)
            or row["size"] < 0
            or row["size"] != len(payload.encode("utf-8"))
            or row["size"] > _MAX_WORKER_RESULT_ENVELOPE_BYTES
            or hashlib.sha256(payload.encode("utf-8")).hexdigest() != row["sha256"]
        ):
            raise ValueError("worker result envelope integrity check failed")
        try:
            value = json.loads(payload)
        except (TypeError, ValueError) as exc:
            raise ValueError("worker result envelope is not valid JSON") from exc
        if not isinstance(value, dict) or value.get("schema_version") != _WORKER_RESULT_SCHEMA_VERSION:
            raise ValueError("worker result envelope schema is invalid")
        artifacts = value.get("artifacts")
        manifest = value.get("artifact_manifest")
        if not isinstance(artifacts, list) or any(not isinstance(item, str) for item in artifacts):
            raise ValueError("worker result envelope artifacts are invalid")
        if not isinstance(manifest, list) or any(not isinstance(item, dict) for item in manifest):
            raise ValueError("worker result envelope manifest is invalid")
        if tuple(item.get("path") for item in manifest) != tuple(artifacts):
            raise ValueError("worker result envelope manifest does not match artifacts")
        # AgentResult performs the full bounded identity, metadata, path, and status checks.
        try:
            result = AgentResult(
                adapter_name=value["adapter_name"], role=value["role"], status=value["status"],
                text=value["text"], error=value.get("error"), metadata=value.get("metadata", {}),
                artifacts=tuple(artifacts),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("worker result envelope result is invalid") from exc
        normalized_payload = Store._worker_result_payload(result, manifest)
        normalized = json.dumps(normalized_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if normalized != payload:
            raise ValueError("worker result envelope JSON is not canonical")
        return WorkerResultEnvelope(
            worker_id=row["worker_id"], worker_attempt_id=row["worker_attempt_id"],
            schema_version=row["schema_version"], adapter_name=result.adapter_name, role=result.role,
            status=result.status, text=result.text, error=result.error, metadata=dict(result.metadata),
            artifacts=result.artifacts, artifact_manifest=tuple(dict(item) for item in manifest),
            sha256=row["sha256"], size=row["size"], created_at=row["created_at"],
        )

    @staticmethod
    def _append_event(
        connection: sqlite3.Connection,
        run_id: str,
        task_id: str | None,
        event_type: str,
        payload: dict[str, Any],
        event_id: str | None = None,
    ) -> bool:
        event_id = event_id or f"event-{uuid.uuid4().hex}"
        inserted = connection.execute(
            "INSERT OR IGNORE INTO events(id, run_id, task_id, type, payload, created_at) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            (event_id, run_id, task_id, event_type, json.dumps(payload, sort_keys=True), utc_now()),
        ).rowcount
        return inserted == 1

    @staticmethod
    def _task_from_row(row: sqlite3.Row) -> Task:
        result_path = Path(row["result_path"]) if row["result_path"] else None
        return Task(
            id=row["id"],
            run_id=row["run_id"],
            title=row["title"],
            prompt=row["prompt"],
            state=TaskStatus(row["state"]),
            attempts=row["attempts"],
            result_path=result_path,
            last_error=row["last_error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            dependencies=tuple(json.loads(row["dependencies"] or "[]")),
            acceptance=row["acceptance"],
            input_question=row["input_question"],
            input_options=tuple(json.loads(row["input_options"] or "[]")),
            input_answer_path=Path(row["input_answer_path"]) if row["input_answer_path"] else None,
            plan_task_id=row["plan_task_id"],
            orchestration=bool(row["orchestration"]) if "orchestration" in row.keys() else False,  # noqa: SIM118 - sqlite rows contain values.
        )

    @staticmethod
    def _attempt_from_row(row: sqlite3.Row) -> Attempt:
        return Attempt(
            id=row["id"],
            task_id=row["task_id"],
            runtime=row["runtime"],
            status=row["status"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            error=row["error"],
            pid=row["pid"],
            pgid=row["pgid"],
        )
