"""Explicit frozen-transfer panels charged to their controller's durable run budget."""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from .rsi_gateway import SolverRequest
from .rsi_learning import RSILearningError
from .rsi_native import _PROTOCOL as _NATIVE_PROTOCOL
from .rsi_stage_accounting import (
    DurableSolverAccounting,
    DurableStageAccounting,
    digest,
    validate_evaluator_intent,
    validate_solver_history,
    validate_solver_state,
    validate_stage_history,
    validate_stage_state,
)
from .rsi_transfer import FrozenMemoryTransferBenchmark, _execution, _outcome, _read, _summary


def _fail():
    raise RSILearningError("rsi_transfer_checkpoint_invalid")


def validate_transfer_history(previous: Mapping, current: Mapping) -> None:
    """A later checkpoint cannot erase a panel or loosen its retained execution identity."""
    old, new = previous.get("transfer_panels", {}), current.get("transfer_panels", {})
    if previous.get("config", {}).get("enable_transfer_accounting") != current.get("config", {}).get("enable_transfer_accounting"):
        _fail()
    if not isinstance(old, Mapping) or not isinstance(new, Mapping):
        _fail()
    for name, before in old.items():
        after = new.get(name)
        if not isinstance(before, Mapping) or not isinstance(after, Mapping):
            _fail()
        if any(before.get(key) != after.get(key) for key in ("identity", "root")):
            _fail()
        validate_stage_history(before.get("stages"), after.get("stages"))
        validate_solver_history(before.get("solvers"), after.get("solvers"))
        if before.get("receipt_sha256") is not None and before["receipt_sha256"] != after.get("receipt_sha256"):
            _fail()


def _request(identity: Mapping, task: Mapping, arm: str) -> SolverRequest:
    memory = identity["baseline" if arm == "baseline" else "snapshot"]
    return SolverRequest.build(
        episode_id="transfer-" + digest({"comparison": identity, "task": task["task_id"], "arm": arm})[:32],
        contract_sha256=task["contract_sha256"], evaluator_sha256=task["evaluator_sha256"],
        environment_sha256=task["environment_sha256"], memory_snapshot_sha256=digest(memory),
        solver_id="native_population", budget=task["budget"],
        practice_charter={**task["charter"], "curriculum_enabled": False, "memory_write_enabled": False},
    )


def _verifier_fingerprint(task: Mapping, root: Path) -> str:
    workspace = root / "tasks" / task["task_id"]
    return digest({"protocol": _NATIVE_PROTOCOL, "role": "independent-verifier",
                   "profile": task["profile_sha256"], "workspace_root": str(workspace),
                   "verification_root": str(workspace / "verifications")})


def _validate_completed_panel(identity, root, payload, stage_rows) -> None:
    """Bind each terminal verifier charge to the exact frozen/baseline arm and decision."""
    tasks, rows = identity["tasks"], payload.get("rows")
    if not isinstance(rows, list) or len(rows) != len(tasks):
        _fail()
    for task, row in zip(tasks, rows, strict=True):
        if not isinstance(row, Mapping) or set(row) != {"task_id", "baseline", "frozen", "outcome"} or row["task_id"] != task["task_id"]:
            _fail()
        arms = []
        for name in ("baseline", "frozen"):
            arm = _execution(row[name])
            if (arm.request.to_dict() != _request(identity, task, name).to_dict()
                    or arm.episode.run_id != identity["comparison_id"]
                    or arm.verifier.verifier_fingerprint != _verifier_fingerprint(task, root)):
                _fail()
            owner = {"comparison_id": identity["comparison_id"], "task_id": task["task_id"], "arm": name}
            owned = [stage for stage in stage_rows if stage["identity"].get("owner") == owner]
            verifiers = [stage for stage in owned if stage["stage"] == "verifier"]
            if (len(verifiers) != 1
                    or verifiers[0]["evidence"] != {"receipt_sha256": arm.verifier.receipt_sha256}
                    or arm.verifier.receipt_sha256 != digest({
                        "request": arm.request.to_dict(), "result": arm.result.to_dict(),
                        "checks": [check.to_dict() for check in arm.verifier.checks], "outcome": arm.verifier.outcome,
                    })):
                _fail()
            evaluations = [stage for stage in owned if stage["stage"] == "evaluator"]
            expected = {arm.result.official_evaluation_receipt_sha256} - {None}
            expected.update(check.receipt_sha256 for check in arm.verifier.checks
                            if check.name in {"official_evaluator", "independent_rerun"} and check.receipt_sha256)
            observed = {stage["evidence"]["receipt_sha256"] for stage in evaluations if stage["evidence"] is not None}
            if not expected.issubset(observed) or (arm.passed and (observed != expected or any(stage["evidence"] is None for stage in evaluations))):
                _fail()
            arms.append(arm)
        if row["outcome"] != _outcome(*arms, task["direction"]):
            _fail()
    if payload.get("summary") != _summary(rows):
        _fail()


def validate_transfers(run) -> dict[str, int]:
    """Validate retained panel counters and bindings without constructing an execution backend."""
    totals = {"transfer": 0, "evaluator": 0, "verifier": 0, "solver_invocations": 0}
    panels = run.state.get("transfer_panels", {})
    if not isinstance(panels, Mapping):
        _fail()
    for comparison_id, entry in panels.items():
        if not isinstance(entry, Mapping) or set(entry) != {"identity", "root", "stages", "solvers", "receipt_sha256"}:
            _fail()
        identity = entry["identity"]
        if (not isinstance(identity, Mapping) or identity.get("comparison_id") != comparison_id
                or identity.get("accounting_binding") != {
                    "run_id": run.run_id, "ledger_path": str(run.ledger.database),
                }):
            _fail()
        if type(entry["root"]) is not str:
            _fail()
        root = Path(entry["root"])
        if not root.is_absolute() or root.is_symlink():
            _fail()
        stages = entry["stages"]
        solvers = entry["solvers"]
        counts = validate_stage_state(stages)
        solver_count = validate_solver_state(solvers)
        if counts["transfer"] not in {0, 1}:
            _fail()
        for name in totals:
            if name in counts:
                totals[name] += counts[name]
        # A pending panel may have fewer calls, but never more than its fixed arm count.
        if (solver_count != 2 * len(identity.get("tasks", ()))
                and (entry["receipt_sha256"] is not None
                     or solver_count > 2 * len(identity.get("tasks", ())))):
            _fail()
        totals["solver_invocations"] += solver_count
        intent = root / "intent.json"
        if intent.exists() or intent.is_symlink():
            if _read(intent) != identity:
                _fail()
        elif stages["invocations"] or entry["receipt_sha256"] is not None:
            _fail()
        tasks = identity.get("tasks")
        if not isinstance(tasks, list) or not tasks or any(not isinstance(task, dict) for task in tasks):
            _fail()
        known = {task.get("task_id"): task for task in tasks}
        if len(known) != len(tasks):
            _fail()
        expected_solver = set()
        for task in tasks:
            for arm in ("baseline", "frozen"):
                request = _request(identity, task, arm)
                expected_solver.add((task["task_id"], arm, request.episode_id, request.digest()))
        observed_solver = set()
        for solver_row in solvers["invocations"]:
            owner = solver_row["identity"]
            observed = (owner.get("task_id"), owner.get("arm"), owner.get("episode_id"), owner.get("request_sha256"))
            if (owner.get("comparison_id") != comparison_id or observed not in expected_solver):
                _fail()
            if observed in observed_solver:
                _fail()
            observed_solver.add(observed)
        transfer_row = None
        seen_verifiers = set()
        evaluator_counts = {}
        for row in stages["invocations"]:
            if row["stage"] == "transfer":
                if row["identity"] != {"comparison_id": comparison_id, "identity_sha256": digest(identity)}:
                    _fail()
                transfer_row = row
                continue
            if transfer_row is None:
                _fail()
            owner = row["identity"].get("owner")
            if (not isinstance(owner, Mapping) or set(owner) != {"comparison_id", "task_id", "arm"}
                    or owner["comparison_id"] != comparison_id or owner["task_id"] not in known
                    or owner["arm"] not in {"baseline", "frozen"}):
                _fail()
            if row["stage"] == "evaluator":
                validate_evaluator_intent(row, evaluator_sha256=known[owner["task_id"]]["evaluator_sha256"])
                owner_key = (owner["task_id"], owner["arm"])
                evaluator_counts[owner_key] = evaluator_counts.get(owner_key, 0) + 1
                if evaluator_counts[owner_key] > 2:
                    _fail()
            else:
                task = known[owner["task_id"]]
                request = _request(identity, task, owner["arm"])
                operation = row["identity"].get("operation")
                if operation != {"episode_id": request.episode_id, "request_sha256": request.digest(),
                                 "verifier_fingerprint": _verifier_fingerprint(task, root)}:
                    _fail()
                if request.episode_id in seen_verifiers:
                    _fail()
                seen_verifiers.add(request.episode_id)
        receipt = entry["receipt_sha256"]
        # A crash can leave the completed reservation durable before the caller saves its
        # returned result. Keep that uncertainty; only an explicit retained open can adopt it.
        if receipt is not None:
            if transfer_row is None or transfer_row["evidence"] != {"receipt_sha256": receipt}:
                _fail()
            payload = _read(root / "comparison.json")
            body = {key: value for key, value in payload.items() if key != "receipt_sha256"}
            if (payload.get("receipt_sha256") != receipt or digest(body) != receipt
                    or payload.get("intent_sha256") != digest(identity)):
                _fail()
            _validate_completed_panel(identity, root, payload, stages["invocations"])
            payload_results = {(row["task_id"], arm): _execution(row[arm]).result
                               for row in payload["rows"] for arm in ("baseline", "frozen")}
            for solver_row in solvers["invocations"]:
                owner = solver_row["identity"]
                result = payload_results[(owner["task_id"], owner["arm"])]
                if solver_row["result_sha256"] != digest(result.to_dict()):
                    _fail()
    return totals


def compare_transfer(run, *, benchmark, comparison_id, tasks, snapshot):
    """Run one explicit post-learning panel; an existing entry only permits a retained open."""
    if not isinstance(benchmark, FrozenMemoryTransferBenchmark):
        raise RSILearningError("rsi_transfer_benchmark_invalid")
    tasks = tuple(tasks)
    binding = {"run_id": run.run_id, "ledger_path": str(run.ledger.database)}
    identity = benchmark.comparison_identity(comparison_id=comparison_id, tasks=tasks,
                                              snapshot=snapshot, accounting_binding=binding)
    with run.ledger.controller_lock(run.run_id):
        run._load()
        if run.state["status"] != "completed":
            raise RSILearningError("rsi_transfer_learning_run_incomplete")
        if run.state["config"].get("enable_transfer_accounting") is not True:
            raise RSILearningError("rsi_budget_transfer_accounting_unavailable")
        panels = run.state.setdefault("transfer_panels", {})
        entry = panels.get(comparison_id)
        read_only = entry is not None
        root = benchmark.workspace_root / "comparisons" / comparison_id
        if entry is None:
            # Pre-existing panels were not authorized by this run. Never adopt their costs
            # after execution, nor allow deleted retained files to authorize a new launch.
            if root.exists() or root.is_symlink():
                raise RSILearningError("rsi_transfer_unbound_panel")
            entry = {"identity": identity, "root": str(root),
                     "stages": {"invocations": []}, "solvers": {"invocations": []},
                     "receipt_sha256": None}
            panels[comparison_id] = entry
            run._save()
        elif entry["identity"] != identity or entry["root"] != str(root):
            raise RSILearningError("rsi_transfer_comparison_identity_changed")
        accounting = DurableStageAccounting(entry["stages"], run.state["budget_state"],
                                             run._save, lock=run.mutex)
        solver_accounting = DurableSolverAccounting(entry["solvers"], run.state["budget_state"],
                                                    run._save, lock=run.mutex)
        run.ledger._assert_controller_lock(run.run_id)
        result = benchmark.compare(comparison_id=comparison_id, tasks=tasks, snapshot=snapshot,
                                   accounting=accounting, solver_accounting=solver_accounting,
                                   accounting_binding=binding, read_only=read_only)
        if result.status == "completed":
            if entry["receipt_sha256"] not in {None, result.receipt_sha256}:
                _fail()
            if entry["receipt_sha256"] is None:
                entry["receipt_sha256"] = result.receipt_sha256
                run._save()
        return result
