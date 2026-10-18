"""Complete-wave memory finalization and read-only replay for private native BRS.

These observations never select a child. Scheduling evidence remains tied to the
original immutable attempts while the existing plan-ordered memory flow may
advance effective memory after the last exact root settlement.
"""
from __future__ import annotations

from .candidate_evaluation_spec import canonical_json, strict_json
from .rsi_learning import MemorySnapshot, RSILearningError


def _fail(reason):
    raise RSILearningError("rsi_brs_reserved_finalization_" + reason)


def validate_reserved_brs_finalization_history(controller, record, history, domain):
    """Check only existing finalization deltas, including original memory records.

    No result, callback, verifier or memory generation is rerun. The prefix and
    terminal observers independently prove the executions supplied in these
    actual hash-chained roots.
    """
    from .rsi_controller import RSILearningController
    from .rsi_store import RSIRecord

    if (type(controller) is not RSILearningController or type(record) is not RSIRecord
            or type(history) is not list or not history or type(domain) is not tuple
            or not domain or len(set(domain)) != len(domain)):
        _fail("history_invalid")
    complete = [(index, head, body) for index, (head, body) in enumerate(history)
                if type(body.get("executions")) is dict and set(body["executions"]) == set(domain)]
    if not complete:
        _fail("incomplete")
    index, _head, scheduling = complete[0]
    if (scheduling.get("phase") != "evaluated" or scheduling.get("status") != "running"
            or scheduling.get("current_episode_id") != domain[-1]
            or scheduling.get("memory_snapshot") != scheduling.get("root_snapshot")
            or scheduling.get("generations") or scheduling.get("brs_reconcile_obligations")):
        _fail("scheduling_root_invalid")
    governed = bool(controller.generation_regression_tasks)
    mutable = {"phase", "status", "current_episode_id", "memory_snapshot", "generations"}
    if governed:
        mutable.update({"budget_state", "external_budget_reservations"})
    immutable = {key: value for key, value in scheduling.items() if key not in mutable}
    executions = {key: controller._deserialize_execution(scheduling["executions"][key]) for key in domain}
    decisions = {key: controller._decision_from_dict(wire)
                 for key, wire in zip(domain, scheduling["plan"]["practices"], strict=True)}
    eligible = tuple(key for key in domain if executions[key].passed)
    memory = MemorySnapshot.from_dict(scheduling["root_snapshot"])
    if any(item.memory_id == "memory-" + key for item in memory.items for key in eligible):
        _fail("source_memory_conflict")
    promoted, cursor, terminal = [], -1, False
    previous = scheduling
    if governed:
        from .rsi_brs_serial_budget import validate_reserved_brs_finalization_budget

        validate_reserved_brs_finalization_budget(controller, scheduling, history)
        controller._check_generation_history(record)
    for _head, body in history[index + 1:]:
        if ({key: value for key, value in body.items() if key not in mutable} != immutable
                or terminal or body.get("phase") not in {"commit", "committed", "generation_pending", "terminal"}
                or body.get("status") not in {"running", "completed"}):
            _fail("root_delta_invalid")
        phase, key = body["phase"], body.get("current_episode_id")
        if phase == "terminal":
            if (body["status"] != "completed" or key != previous.get("current_episode_id")
                    or body["memory_snapshot"] != previous["memory_snapshot"]
                    or body.get("generations", {}) != previous.get("generations", {})):
                _fail("terminal_delta_invalid")
            terminal = True
        else:
            if body["status"] != "running" or key not in eligible:
                _fail("commit_source_invalid")
            ordinal = eligible.index(key)
            if ordinal < cursor or ordinal > cursor + 1:
                _fail("commit_order_invalid")
            if ordinal > cursor:
                if cursor >= 0 and not _completed(previous, eligible[cursor], governed):
                    _fail("commit_order_invalid")
                if phase != "commit":
                    _fail("commit_phase_invalid")
                cursor = ordinal
            elif previous.get("phase") == "committed" or previous.get("phase") == "generation_pending":
                # A pending governed generation may be resumed using its exact
                # existing candidate; committed entries are already idempotent.
                if not (governed and previous.get("phase") == "generation_pending"):
                    _fail("commit_phase_invalid")
        observed = MemorySnapshot.from_dict(body["memory_snapshot"])
        if governed:
            old_entries, entries = previous.get("generations", {}), body.get("generations", {})
            changed = tuple(item for item in set(old_entries) | set(entries)
                            if old_entries.get(item) != entries.get(item))
            if any(item != key for item in changed) or len(changed) > 1:
                _fail("generation_order_invalid")
            if changed:
                if key not in old_entries:
                    if phase != "commit" or entries[key]["status"] != "pending":
                        _fail("generation_delta_invalid")
                elif (phase != "committed" or old_entries[key]["status"] != "pending"
                      or entries[key]["status"] not in {"active", "rejected"}):
                    _fail("generation_delta_invalid")
            if phase != "terminal" and phase == "committed" and not _completed(body, key, True):
                _fail("generation_incomplete")
        else:
            if body.get("generations") or phase == "generation_pending":
                _fail("unexpected_generation")
            if observed != memory:
                if phase != "committed" or key in promoted:
                    _fail("memory_delta_invalid")
                item = controller._memory_item(executions[key], decisions[key])
                expected = MemorySnapshot("snapshot-" + item.memory_id, memory.digest(), memory.items + (item,))
                saved = controller.ledger.get("memory:" + expected.snapshot_id)
                if observed != expected or saved is None or saved.kind != "memory" or saved.payload != expected.to_dict():
                    _fail("memory_delta_invalid")
                promoted.append(key)
                memory = expected
            elif phase == "committed":
                _fail("memory_delta_missing")
        previous = body
    current = history[-1][1]
    if terminal and any(not _completed(current, key, governed) for key in eligible):
        _fail("terminal_incomplete")
    return scheduling


def _completed(state, key, governed):
    if governed:
        entry = state.get("generations", {}).get(key)
        return type(entry) is dict and entry.get("status") in {"active", "rejected"}
    return any(item.memory_id == "memory-" + key
               for item in MemorySnapshot.from_dict(state["memory_snapshot"]).items)


def read_reserved_brs_finalization(controller, record, state):
    """Reobserve complete scheduling, original terminal proof and finalization tail."""
    from .rsi_brs_publication_lineage import _policy, _validate_persisted_policy
    from .rsi_brs_rejection_owner import read_reserved_brs_material_inventory
    from .rsi_brs_reserved_ledger import assert_reserved_brs_ledger
    from .rsi_brs_reserved_owner import read_reserved_brs_finalization_prefix
    from .rsi_brs_reserved_reservation import read_reserved_brs_finalization_reservation
    from .rsi_brs_serial_driver import (
        read_reserved_brs_settled_terminal,
        reserved_brs_staging_mode,
    )
    from .rsi_controller import RSILearningController
    from .rsi_python_admission import RSIPythonAdmissionRecord
    from .rsi_store import RSILedger, RSIRecord

    if (type(controller) is not RSILearningController or type(controller.ledger) is not RSILedger
            or type(record) is not RSIRecord or not reserved_brs_staging_mode(state)):
        _fail("original_scope_required")
    ledger, run_id = controller.ledger, state["run_id"]
    ledger._assert_controller_lock(run_id)
    if (record is None or record.kind != "run" or record.logical_id != run_id
            or record.state not in {"running", "completed"} or ledger.get_run(run_id) != record
            or record.state == "completed" and state.get("status") != "completed"):
        _fail("run_state_invalid")
    checkpoint = ledger.controller_checkpoint(run_id)
    payload = canonical_json(state, maximum=128 * 1024)
    if checkpoint is None or canonical_json(checkpoint[1], maximum=128 * 1024) != payload:
        _fail("checkpoint_conflict")
    _validate_persisted_policy(controller, run_id=run_id, state=state, expected=_policy())
    domain = tuple(f"{run_id}-practice-{state['plan']['wave']}-{index}"
                   for index in range(len(state["plan"]["practices"])))
    reservation = read_reserved_brs_finalization_reservation(ledger, run_id=run_id,
        episode_ids=domain, expected_checkpoint_sha256=checkpoint[0])
    prefix, batches = read_reserved_brs_finalization_prefix(ledger, controller.producer_workspace,
        original_checkpoint=(reservation.original_checkpoint_sha256, reservation.original_state_bytes),
        expected_checkpoint_sha256=checkpoint[0])
    if len(prefix.settled_prefix) != len(domain):
        _fail("incomplete")
    roots = ledger.controller_checkpoint_history(run_id)
    validate_reserved_brs_finalization_history(controller, record, roots, domain)
    traces, refs = reservation.ledger.ledger_traces(), state.get("python_admission_refs", {})
    terminal = tuple((key, read_reserved_brs_settled_terminal(
        ledger, reservation, key, traces[key], refs[key], state["executions"][key])) for key in domain)
    wire = state.get("producer_publication_lineage")
    inventory = read_reserved_brs_material_inventory(controller.producer_workspace, wire, prefix_batches=batches)
    if any(traces[key]["reconciliation_rows"] or traces[key]["obligation_sha256"]
           or len(traces[key]["admission_rows"]) != 1 for key in domain):
        _fail("attempt_drift")
    for key in domain:
        row, ref = traces[key]["admission_rows"][0], refs[key]
        admission = RSIPythonAdmissionRecord.from_dict(strict_json(row["payload"], maximum=128 * 1024))
        if (row["record_sha256"] != ref.get("record_sha256") or row["run_id"] != run_id
                or row["episode_id"] != key or row["journal_id"] != ref.get("journal_id")
                or admission.digest() != row["record_sha256"]):
            _fail("admission_drift")
    controller._validate_resume_identity(record, None, None)
    controller._validate_run_checkpoint_producer_binding(record, state)
    controller._check_budget_history(record)
    if record.state == "completed":
        result = controller._flow_result(state)
        expected = {"target_attempt_count": len(result.target_attempts),
                    "practice_episode_count": len(result.practice_episodes),
                    "memory_snapshot_sha256": result.memory_snapshot.digest(),
                    "phase": "terminal", "current_episode_id": result.current_episode_id,
                    "target_attempts": [controller._serialize_execution(item) for item in result.target_attempts],
                    "practice_episodes": [controller._serialize_execution(item) for item in result.practice_episodes],
                    "memory_snapshot": result.memory_snapshot.to_dict(), "budget_state": state["budget_state"]}
        if any(record.payload.get(key) != value for key, value in expected.items()):
            _fail("run_result_drift")
    if (ledger.controller_checkpoint_history(run_id) != roots
            or read_reserved_brs_material_inventory(controller.producer_workspace, wire,
                                                   prefix_batches=batches) != inventory):
        _fail("observation_changed")
    for key, captured in terminal:
        if read_reserved_brs_settled_terminal(
                ledger, reservation, key, traces[key], refs[key], state["executions"][key]) != captured:
            _fail("terminal_drift")
    assert_reserved_brs_ledger(ledger, reservation.ledger)
    if canonical_json(state, maximum=128 * 1024) != payload:
        _fail("checkpoint_conflict")
    return domain


def finalize_reserved_brs_serial(controller, record, state):
    """Resume only existing plan-order memory commits; completed replay is read-only."""
    domain = read_reserved_brs_finalization(controller, record, state)
    from .rsi_gateway import RSIMemoryStore

    controller.memory_store = RSIMemoryStore(MemorySnapshot.from_dict(state["memory_snapshot"]))
    if state["status"] != "completed":
        parent = MemorySnapshot.from_dict(state["root_snapshot"]).digest()
        for key, wire in zip(domain, state["plan"]["practices"], strict=True):
            controller._commit_flow(record, state, controller._deserialize_execution(state["executions"][key]),
                                    controller._decision_from_dict(wire), frozen_parent=parent)
        result = controller._finish_flow(record, state, "completed")
        read_reserved_brs_finalization(controller, controller.ledger.get_run(state["run_id"]), state)
        return result
    result = controller._flow_result(state)
    latest = controller.ledger.get_run(state["run_id"])
    if latest is None:
        _fail("run_missing")
    if latest.state != "completed":
        if latest.state != "running":
            _fail("run_state_invalid")
        controller._finish_run(latest, result, budget_state=state["budget_state"])
        read_reserved_brs_finalization(controller, controller.ledger.get_run(state["run_id"]), state)
    return result
