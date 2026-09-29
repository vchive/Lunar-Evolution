from __future__ import annotations

import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from lunar_evolution.automatic_solve_worker_binding import (
    AutomaticSolveWorkerBinding,
    AutomaticSolveWorkerBindingState,
    AutomaticSolveWorkerResultReference,
)
from lunar_evolution.models import WorkerOutcome
from lunar_evolution.store import Store


def _fixture(tmp_path):
    store = Store(tmp_path / "state.db")
    store.initialize()
    run = store.create_run("automatic bridge", tmp_path / "run")
    request = {"bundle_mode": "compiled", "automatic_lifecycle_version": 1}
    store.append_event(run.id, "evolution_requested", request)
    lifecycle = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    worker = store.create_worker(run.id, "solver", "automatic bridge", agent_type="fixture")
    attempt = store.start_worker_attempt(worker.id, run.id, "automatic bridge", service_owner_id="service-owner")
    binding = AutomaticSolveWorkerBinding(
        binding_id="automatic-binding-1", owner_id=run.id, run_id=run.id,
        workspace_identity=str(run.workspace), worker_id=worker.id, worker_attempt_id=attempt.id,
        service_owner_id="service-owner", lifecycle_digest=lifecycle,
        runtime_fingerprint="a" * 64, budget_policy={"active_seconds": 5},
    )
    return store, run, worker, attempt, binding


def test_admission_is_create_only_and_idempotent(tmp_path):
    store, run, _worker, _attempt, binding = _fixture(tmp_path)
    assert store.create_automatic_solve_worker_binding(binding) == store.create_automatic_solve_worker_binding(binding)
    assert store.list_automatic_solve_worker_bindings(run.id, run_id=run.id)[0].binding_id == binding.binding_id
    drift = AutomaticSolveWorkerBinding(
        **{**binding.to_dict(), "runtime_fingerprint": "b" * 64}
    )
    with pytest.raises(ValueError, match="admission drift"):
        store.create_automatic_solve_worker_binding(drift)


def test_cas_rejects_stale_generation_and_terminal_is_frozen(tmp_path):
    store, _run, _worker, _attempt, binding = _fixture(tmp_path)
    admitted = store.create_automatic_solve_worker_binding(binding)
    active = store.compare_and_swap_automatic_solve_worker_binding(
        admitted, state=AutomaticSolveWorkerBindingState.ACTIVE,
    )
    assert active is not None and active.state is AutomaticSolveWorkerBindingState.ACTIVE
    stale = store.compare_and_swap_automatic_solve_worker_binding(
        admitted, state=AutomaticSolveWorkerBindingState.UNKNOWN,
    )
    assert stale is None
    terminal = store.compare_and_swap_automatic_solve_worker_binding(
        active, state=AutomaticSolveWorkerBindingState.UNKNOWN,
    )
    assert terminal is not None
    with pytest.raises(ValueError, match="native recovery"):
        store.compare_and_swap_automatic_solve_worker_binding(
            terminal, state=AutomaticSolveWorkerBindingState.TERMINAL,
        )


def test_result_reference_is_bound_to_exact_generation_and_digest(tmp_path):
    store, run, _worker, attempt, binding = _fixture(tmp_path)
    admitted = store.create_automatic_solve_worker_binding(binding)
    store.cancel_run(run.id)
    reference = AutomaticSolveWorkerResultReference(
        binding_id=binding.binding_id, generation=0, run_id=run.id,
        worker_attempt_id=attempt.id, outcome="cancelled",
        reference={"native_receipt_id": "receipt-1"},
    )
    stored = store.create_automatic_solve_worker_result_reference(admitted, reference)
    assert stored is not None
    terminal = store.get_automatic_solve_worker_binding(binding.binding_id, owner_id=run.id)
    with pytest.raises(ValueError, match="immutable"):
        store.compare_and_swap_automatic_solve_worker_binding(
            terminal, state=AutomaticSolveWorkerBindingState.TERMINAL,
            observation_reason="changed",
        )
    assert store.create_automatic_solve_worker_result_reference(admitted, reference) == stored
    assert store.get_automatic_solve_worker_result_reference(
        binding.binding_id, owner_id=run.id, generation=0,
    ) == stored
    mutated = dict(reference.reference)
    mutated["native_receipt_id"] = "receipt-2"
    with pytest.raises(ValueError, match="digest"):
        store.create_automatic_solve_worker_result_reference(admitted, AutomaticSolveWorkerResultReference(
            binding_id=binding.binding_id, generation=0, run_id=run.id,
            worker_attempt_id=attempt.id, outcome="cancelled", reference=mutated,
            sha256=reference.sha256,
        ))


def test_result_reference_rejects_cross_generation_reuse(tmp_path):
    store, run, _worker, attempt, binding = _fixture(tmp_path)
    admitted = store.create_automatic_solve_worker_binding(binding)
    store.cancel_run(run.id)
    reference = AutomaticSolveWorkerResultReference(
        binding_id=binding.binding_id, generation=1, run_id=run.id,
        worker_attempt_id=attempt.id, outcome="cancelled", reference={"ok": True},
    )
    with pytest.raises(ValueError, match="owner mismatch"):
        store.create_automatic_solve_worker_result_reference(admitted, reference)


@pytest.mark.parametrize("terminalizer", ["cancel", "settle_failed", "settle_succeeded"])
def test_terminal_native_run_rejects_nonterminal_binding_observation(tmp_path, terminalizer):
    store, run, _worker, _attempt, binding = _fixture(tmp_path)
    admitted = store.create_automatic_solve_worker_binding(binding)
    if terminalizer == "cancel":
        store.cancel_run(run.id)
    else:
        task = store.list_tasks(run.id)[0]
        attempt = store.claim_task(task.id, "fixture")
        assert attempt is not None
        if terminalizer == "settle_failed":
            store.finish_task(task.id, attempt.id, False, error="fixture")
        else:
            store.finish_task(task.id, attempt.id, True)
        store.settle_run(run.id)
    assert store.get_run(run.id).status.value in {"cancelled", "failed", "succeeded"}
    with pytest.raises(ValueError, match="not eligible for admission"):
        store.create_automatic_solve_worker_binding(binding)
    with pytest.raises(ValueError, match="activate after terminal"):
        store.compare_and_swap_automatic_solve_worker_binding(
            admitted, state=AutomaticSolveWorkerBindingState.ACTIVE,
        )


def test_existing_active_binding_can_record_final_pins_without_reactivation(tmp_path):
    store, run, _worker, _attempt, binding = _fixture(tmp_path)
    admitted = store.create_automatic_solve_worker_binding(binding)
    active = store.compare_and_swap_automatic_solve_worker_binding(
        admitted, state=AutomaticSolveWorkerBindingState.ACTIVE,
    )
    store.cancel_run(run.id)
    observed = store.compare_and_swap_automatic_solve_worker_binding(
        active, state=AutomaticSolveWorkerBindingState.ACTIVE,
    )
    assert observed.state is AutomaticSolveWorkerBindingState.ACTIVE
    assert observed.generation == active.generation


def test_unknown_observation_is_retained_after_terminal_run(tmp_path):
    store, run, _worker, _attempt, binding = _fixture(tmp_path)
    admitted = store.create_automatic_solve_worker_binding(binding)
    store.cancel_run(run.id)
    unknown = store.compare_and_swap_automatic_solve_worker_binding(
        admitted, state=AutomaticSolveWorkerBindingState.UNKNOWN,
    )
    assert unknown is not None and unknown.state is AutomaticSolveWorkerBindingState.UNKNOWN


def test_existing_admission_rechecks_live_attempt_on_idempotent_replay(tmp_path):
    store, _run, worker, attempt, binding = _fixture(tmp_path)
    store.create_automatic_solve_worker_binding(binding)
    store.settle_worker(worker.id, attempt.id, WorkerOutcome.FAILURE)
    with pytest.raises(ValueError, match="no longer active"):
        store.create_automatic_solve_worker_binding(binding)


@pytest.mark.parametrize("field,value", [
    ("owner_id", "different-owner"), ("worker_attempt_id", "missing-attempt"),
    ("service_owner_id", "different-service"), ("worker_id", "missing-worker"),
])
def test_admission_requires_exact_running_worker_owner(tmp_path, field, value):
    store, _run, _worker, _attempt, binding = _fixture(tmp_path)
    with pytest.raises(ValueError, match="reciprocal"):
        store.create_automatic_solve_worker_binding(replace(binding, **{field: value}))
    assert store.list_automatic_solve_worker_bindings(binding.owner_id) == []


@pytest.mark.parametrize("field,value", [
    ("workspace_identity", "/different-workspace"), ("lifecycle_digest", "b" * 64),
    ("contract_digest", "b" * 64), ("child_run_id", "unbound-child"),
])
def test_admission_rejects_native_pin_drift(tmp_path, field, value):
    store, _run, _worker, _attempt, binding = _fixture(tmp_path)
    with pytest.raises(ValueError):
        store.create_automatic_solve_worker_binding(replace(binding, **{field: value}))
    assert store.list_automatic_solve_worker_bindings(binding.owner_id) == []


def test_concurrent_run_admissions_have_exactly_one_winner(tmp_path):
    store, run, _worker, _attempt, first = _fixture(tmp_path)
    worker = store.create_worker(run.id, "solver", "second bridge", agent_type="fixture")
    attempt = store.start_worker_attempt(worker.id, run.id, "second", service_owner_id="other-service")
    second = replace(first, binding_id="automatic-binding-2", worker_id=worker.id,
                     worker_attempt_id=attempt.id, service_owner_id="other-service")

    def admit(binding):
        try:
            return store.create_automatic_solve_worker_binding(binding)
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(admit, (first, second)))
    assert sum(result is not None for result in results) == 1
    assert len(store.list_automatic_solve_worker_bindings(run.id)) == 1


def test_unknown_binding_never_reopens_through_cas_or_new_admission(tmp_path):
    store, _run, _worker, _attempt, binding = _fixture(tmp_path)
    admitted = store.create_automatic_solve_worker_binding(binding)
    unknown = store.compare_and_swap_automatic_solve_worker_binding(
        admitted, state=AutomaticSolveWorkerBindingState.UNKNOWN,
    )
    with pytest.raises(ValueError, match="native recovery"):
        store.compare_and_swap_automatic_solve_worker_binding(
            unknown, state=AutomaticSolveWorkerBindingState.ACTIVE,
        )
    with pytest.raises(ValueError, match="initial admission"):
        store.create_automatic_solve_worker_binding(replace(binding, generation=1, prior_generation=0))


def _prepare_resume(store, run, worker, attempt, binding, *, state=AutomaticSolveWorkerBindingState.RECOVERY_REQUIRED):
    admitted = store.create_automatic_solve_worker_binding(binding)
    observed = store.compare_and_swap_automatic_solve_worker_binding(admitted, state=state)
    assert observed is not None
    store.settle_worker(worker.id, attempt.id, WorkerOutcome.LOST)
    next_worker = store.create_worker(run.id, "solver", "resumed bridge", agent_type="fixture")
    next_attempt = store.start_worker_attempt(
        next_worker.id, run.id, "resumed bridge", service_owner_id="new-service-owner",
    )
    next_binding = replace(
        binding,
        binding_id="automatic-binding-2",
        worker_id=next_worker.id,
        worker_attempt_id=next_attempt.id,
        service_owner_id="new-service-owner",
        generation=1,
        prior_generation=0,
    )
    return observed, next_binding


def test_resume_admits_new_generation_and_supersedes_old_append_only(tmp_path):
    store, run, worker, attempt, binding = _fixture(tmp_path)
    expected, next_binding = _prepare_resume(store, run, worker, attempt, binding)
    resumed = store.resume_automatic_solve_worker_binding(expected, next_binding)
    assert resumed is not None
    assert resumed.generation == 1
    assert resumed.prior_generation == 0
    assert resumed.state is AutomaticSolveWorkerBindingState.ADMITTED
    old = store.get_automatic_solve_worker_binding(binding.binding_id, owner_id=run.id)
    assert old is not None and old.state is AutomaticSolveWorkerBindingState.SUPERSEDED
    assert replace(old, state=expected.state, updated_at=expected.updated_at) == expected
    assert store.compare_and_swap_automatic_solve_worker_binding(
        expected, state=expected.state, observation_reason="late old observation",
    ) is None
    with pytest.raises(ValueError, match="superseded"):
        store.compare_and_swap_automatic_solve_worker_binding(
            old, state=old.state,
        )
    with pytest.raises(ValueError, match="explicit native bridge resume"):
        store.start_worker_attempt(worker.id, run.id, "must remain fenced", service_owner_id="service-owner")
    assert store.resume_automatic_solve_worker_binding(expected, next_binding) is None


def test_resume_rejects_late_old_result_reference(tmp_path):
    store, run, worker, attempt, binding = _fixture(tmp_path)
    expected, next_binding = _prepare_resume(store, run, worker, attempt, binding)
    assert store.resume_automatic_solve_worker_binding(expected, next_binding) is not None
    reference = AutomaticSolveWorkerResultReference(
        binding.binding_id, 0, run.id, attempt.id, "failed", {"late": True},
    )
    assert store.create_automatic_solve_worker_result_reference(expected, reference) is None


@pytest.mark.parametrize("field", [
    "owner_id", "run_id", "workspace_identity", "lifecycle_digest", "runtime_fingerprint",
    "budget_policy", "contract_digest", "child_run_id",
])
def test_resume_rejects_pin_drift(tmp_path, field):
    store, run, worker, attempt, binding = _fixture(tmp_path)
    expected, next_binding = _prepare_resume(store, run, worker, attempt, binding)
    value = {
        "owner_id": "other-owner",
        "run_id": "other-run",
        "workspace_identity": "/other-workspace",
        "lifecycle_digest": "b" * 64,
        "runtime_fingerprint": "b" * 64,
        "budget_policy": {"active_seconds": 9},
        "contract_digest": "b" * 64,
        "child_run_id": "other-child",
    }[field]
    with pytest.raises(ValueError, match="pin drift"):
        store.resume_automatic_solve_worker_binding(expected, replace(next_binding, **{field: value}))


@pytest.mark.parametrize("kind", ["runner", "runner_pid_only", "runner_pgid_only", "attempt", "attempt_pid_only", "attempt_pgid_only"])
def test_resume_requires_quiescent_native_registration(tmp_path, kind):
    store, run, worker, attempt, binding = _fixture(tmp_path)
    expected, next_binding = _prepare_resume(store, run, worker, attempt, binding)
    pid, pgid = (None if kind.endswith("pgid_only") else 5001), (None if kind.endswith("pid_only") else 5001)
    if kind.startswith("runner"):
        store.set_runner_process(run.id, pid, pgid)
    else:
        task = store.list_tasks(run.id)[0]
        native_attempt = store.claim_task(task.id, "fixture")
        assert native_attempt is not None
        store.finish_task(task.id, native_attempt.id, False)
        store.set_attempt_process(native_attempt.id, pid, pgid)
    with pytest.raises(ValueError, match="still registered"):
        store.resume_automatic_solve_worker_binding(expected, next_binding)
    assert store.get_automatic_solve_worker_binding(expected.binding_id, owner_id=run.id) == expected


def test_resume_requires_no_pending_native_input(tmp_path):
    store, run, worker, attempt, binding = _fixture(tmp_path)
    expected, next_binding = _prepare_resume(store, run, worker, attempt, binding)
    task = store.list_tasks(run.id)[0]
    native_attempt = store.claim_task(task.id, "fixture")
    assert native_attempt is not None
    assert store.await_input(
        task.id, native_attempt.id, "input.json", "choose a continuation", ["yes", "no"],
    )
    with pytest.raises(ValueError, match="not eligible"):
        store.resume_automatic_solve_worker_binding(expected, next_binding)
    # An inconsistent parent status cannot hide an unanswered task question.
    with store._connect() as connection:
        connection.execute("UPDATE runs SET status = 'pending' WHERE id = ?", (run.id,))
    with pytest.raises(ValueError, match="pending input"):
        store.resume_automatic_solve_worker_binding(expected, next_binding)
    assert store.answer_input(run.id, "answer.json") == task.id
    assert store.resume_automatic_solve_worker_binding(expected, next_binding) is not None


@pytest.mark.parametrize("field,value", [
    ("generation", 2), ("prior_generation", None),
    ("state", AutomaticSolveWorkerBindingState.ACTIVE),
    ("observation_reason", "premature"), ("stop_reason", "premature"),
    ("result_ref_digest", "b" * 64), ("native_receipt_id", "receipt"),
    ("delivery_identity", "delivery"),
])
def test_resume_requires_next_generation_admission_shape(tmp_path, field, value):
    store, run, worker, attempt, binding = _fixture(tmp_path)
    expected, next_binding = _prepare_resume(store, run, worker, attempt, binding)
    with pytest.raises(ValueError):
        store.resume_automatic_solve_worker_binding(expected, replace(next_binding, **{field: value}))
    assert store.list_automatic_solve_worker_bindings(run.id) == [expected]


@pytest.mark.parametrize("field", ["binding_id", "worker_id", "worker_attempt_id"])
def test_resume_requires_fresh_binding_and_worker(tmp_path, field):
    store, run, worker, attempt, binding = _fixture(tmp_path)
    expected, next_binding = _prepare_resume(store, run, worker, attempt, binding)
    with pytest.raises(ValueError, match="requires a new"):
        store.resume_automatic_solve_worker_binding(
            expected, replace(next_binding, **{field: getattr(expected, field)}),
        )


@pytest.mark.parametrize("status", ["awaiting_input", "succeeded", "failed", "cancelled"])
def test_resume_rejects_ineligible_native_run(tmp_path, status):
    store, run, worker, attempt, binding = _fixture(tmp_path)
    expected, next_binding = _prepare_resume(store, run, worker, attempt, binding)
    with store._connect() as connection:
        connection.execute("UPDATE runs SET status = ? WHERE id = ?", (status, run.id))
    with pytest.raises(ValueError, match="not eligible"):
        store.resume_automatic_solve_worker_binding(expected, next_binding)


@pytest.mark.parametrize("damage", ["old_owner", "old_service", "old_running", "old_unfinished", "new_owner", "new_service", "new_settled"])
def test_resume_rechecks_both_worker_owners_and_settlement(tmp_path, damage):
    store, run, worker, attempt, binding = _fixture(tmp_path)
    expected, next_binding = _prepare_resume(store, run, worker, attempt, binding)
    with store._connect() as connection:
        if damage == "old_owner":
            connection.execute("UPDATE workers SET owner_id = 'other' WHERE id = ?", (worker.id,))
        elif damage == "old_service":
            connection.execute("UPDATE worker_attempts SET service_owner_id = 'other' WHERE id = ?", (attempt.id,))
        elif damage == "old_running":
            connection.execute("UPDATE worker_attempts SET status = 'running' WHERE id = ?", (attempt.id,))
        elif damage == "old_unfinished":
            connection.execute("UPDATE worker_attempts SET finished_at = NULL WHERE id = ?", (attempt.id,))
        elif damage == "new_owner":
            connection.execute("UPDATE workers SET owner_id = 'other' WHERE id = ?", (next_binding.worker_id,))
        elif damage == "new_service":
            connection.execute(
                "UPDATE worker_attempts SET service_owner_id = 'other' WHERE id = ?", (next_binding.worker_attempt_id,),
            )
        else:
            connection.execute(
                "UPDATE worker_attempts SET status = 'finished' WHERE id = ?", (next_binding.worker_attempt_id,),
            )
    with pytest.raises(ValueError, match="not settled|no longer active"):
        store.resume_automatic_solve_worker_binding(expected, next_binding)


def test_resume_rejects_retained_old_worker_process(tmp_path):
    store, run, worker, attempt, binding = _fixture(tmp_path)
    expected, next_binding = _prepare_resume(store, run, worker, attempt, binding)
    assert store.register_worker_process(worker.id, attempt.id, binding.service_owner_id, 5001, 5001)
    with pytest.raises(ValueError, match="active attempt or process"):
        store.resume_automatic_solve_worker_binding(expected, next_binding)
    assert store.clear_worker_process(worker.id, attempt.id, binding.service_owner_id, 5001, 5001)
    assert store.resume_automatic_solve_worker_binding(expected, next_binding) is not None


def test_resume_rejects_new_attempt_already_bound_to_a_task(tmp_path):
    store, run, worker, attempt, binding = _fixture(tmp_path)
    expected, next_binding = _prepare_resume(store, run, worker, attempt, binding)
    task = store.list_tasks(run.id)[0]
    native_attempt = store.claim_task(task.id, "fixture")
    assert native_attempt is not None
    store.bind_worker(
        worker_id=next_binding.worker_id, worker_attempt_id=next_binding.worker_attempt_id,
        run_id=run.id, task_id=task.id, task_attempt_id=native_attempt.id,
        service_owner_id=next_binding.service_owner_id,
    )
    with pytest.raises(ValueError, match="task binding"):
        store.resume_automatic_solve_worker_binding(expected, next_binding)


def _link_native_child(store, run, tmp_path):
    from test_conversational import _contract

    from lunar_evolution.conversational import build_algorithm_plan

    contract = _contract()
    store.attach_plan_to_run(run.id, build_algorithm_plan(run.goal, contract))
    child = store.create_run("native child", tmp_path / "child")
    store.append_event(run.id, "evolution_linked", {
        "evolution_run_id": child.id, "contract_sha256": contract.digest(), "strategy": "population",
    })
    store.append_event(child.id, "evolution_parent_linked", {
        "parent_run_id": run.id, "contract_sha256": contract.digest(),
    })
    return child, contract.digest()


@pytest.mark.parametrize("status", ["pending", "running", "succeeded", "failed", "cancelled"])
def test_resume_preserves_bound_child_and_accepts_terminal_child(tmp_path, status):
    store, run, worker, attempt, binding = _fixture(tmp_path)
    child, digest = _link_native_child(store, run, tmp_path)
    binding = replace(binding, contract_digest=digest, child_run_id=child.id)
    expected, next_binding = _prepare_resume(store, run, worker, attempt, binding)
    with store._connect() as connection:
        connection.execute("UPDATE runs SET status = ? WHERE id = ?", (status, child.id))
    resumed = store.resume_automatic_solve_worker_binding(expected, next_binding)
    assert resumed is not None
    assert (resumed.child_run_id, resumed.contract_digest) == (child.id, digest)


@pytest.mark.parametrize("pinned", [False, True])
@pytest.mark.parametrize("registration", ["runner", "partial_runner", "attempt", "input"])
def test_resume_checks_native_child_obligations_even_without_retained_pin(tmp_path, pinned, registration):
    store, run, worker, attempt, binding = _fixture(tmp_path)
    child, digest = _link_native_child(store, run, tmp_path)
    if pinned:
        binding = replace(binding, contract_digest=digest, child_run_id=child.id)
    expected, next_binding = _prepare_resume(store, run, worker, attempt, binding)
    if registration in {"runner", "partial_runner"}:
        store.set_runner_process(child.id, 5001, 5001 if registration == "runner" else None)
    else:
        task = store.list_tasks(child.id)[0]
        native_attempt = store.claim_task(task.id, "fixture")
        assert native_attempt is not None
        if registration == "attempt":
            store.set_attempt_process(native_attempt.id, None, 5001)
        else:
            store.await_input(task.id, native_attempt.id, "question.json", "Continue?")
    with pytest.raises(ValueError, match="registered|pending input"):
        store.resume_automatic_solve_worker_binding(expected, next_binding)
    assert store.list_automatic_solve_worker_bindings(run.id) == [expected]


@pytest.mark.parametrize("damage", ["none", "reciprocal", "contract", "duplicate"])
def test_resume_validates_unpinned_child_links_without_mutating_old_pins(tmp_path, damage):
    store, run, worker, attempt, binding = _fixture(tmp_path)
    expected, next_binding = _prepare_resume(store, run, worker, attempt, binding)
    child, digest = _link_native_child(store, run, tmp_path)
    if damage == "reciprocal":
        with store._connect() as connection:
            connection.execute(
                "DELETE FROM events WHERE run_id = ? AND type = 'evolution_parent_linked'", (child.id,),
            )
    elif damage == "contract":
        with store._connect() as connection:
            connection.execute(
                "UPDATE events SET payload = ? WHERE run_id = ? AND type = 'evolution_linked'",
                (json.dumps({"evolution_run_id": child.id, "contract_sha256": "b" * 64,
                             "strategy": "population"}), run.id),
            )
    elif damage == "duplicate":
        store.append_event(run.id, "evolution_linked", {
            "evolution_run_id": child.id, "contract_sha256": digest, "strategy": "population",
        })
    expected_error = {"none": "pin recovery", "reciprocal": "reciprocal", "contract": "contract drift", "duplicate": "ambiguous"}[damage]
    with pytest.raises(ValueError, match=expected_error):
        store.resume_automatic_solve_worker_binding(expected, next_binding)
    retained = store.get_automatic_solve_worker_binding(expected.binding_id, owner_id=run.id)
    assert retained == expected
    assert retained.contract_digest is retained.child_run_id is None


def test_resume_rejects_unpinned_native_child_link(tmp_path):
    store, run, worker, attempt, binding = _fixture(tmp_path)
    expected, next_binding = _prepare_resume(store, run, worker, attempt, binding)
    child = store.create_run("native child", tmp_path / "child")
    store.append_event(run.id, "evolution_linked", {
        "evolution_run_id": child.id, "contract_sha256": "a" * 64, "strategy": "population",
    })
    with pytest.raises(ValueError, match="accepted contract|child link"):
        store.resume_automatic_solve_worker_binding(expected, next_binding)


def test_resume_rejects_malformed_native_child_link(tmp_path):
    store, run, worker, attempt, binding = _fixture(tmp_path)
    expected, next_binding = _prepare_resume(store, run, worker, attempt, binding)
    child = store.create_run("native child", tmp_path / "child")
    store.append_event(run.id, "evolution_linked", {"evolution_run_id": child.id})
    with pytest.raises(ValueError, match="child link"):
        store.resume_automatic_solve_worker_binding(expected, next_binding)


@pytest.mark.parametrize("damage", ["workspace", "lifecycle"])
def test_resume_rechecks_retained_native_pins(tmp_path, damage):
    store, run, worker, attempt, binding = _fixture(tmp_path)
    expected, next_binding = _prepare_resume(store, run, worker, attempt, binding)
    with store._connect() as connection:
        if damage == "workspace":
            connection.execute("UPDATE runs SET workspace = '/changed' WHERE id = ?", (run.id,))
        else:
            request = {"bundle_mode": "compiled", "automatic_lifecycle_version": 1, "changed": True}
            connection.execute(
                "UPDATE events SET payload = ? WHERE run_id = ? AND type = 'evolution_requested'",
                (json.dumps(request), run.id),
            )
    with pytest.raises(ValueError, match="drift"):
        store.resume_automatic_solve_worker_binding(expected, next_binding)


def test_resume_rolls_back_supersession_if_insertion_fails(tmp_path):
    store, run, worker, attempt, binding = _fixture(tmp_path)
    expected, next_binding = _prepare_resume(store, run, worker, attempt, binding)
    with store._connect() as connection:
        connection.execute(
            "CREATE TRIGGER reject_resume BEFORE INSERT ON automatic_solve_worker_bindings "
            "WHEN NEW.generation > 0 BEGIN SELECT RAISE(ABORT, 'injected insert failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="injected insert failure"):
        store.resume_automatic_solve_worker_binding(expected, next_binding)
    assert store.list_automatic_solve_worker_bindings(run.id) == [expected]
    assert not any(event["type"] == "automatic_solve_worker_resumed" for event in store.list_events(run.id))


@pytest.mark.parametrize("state", [
    AutomaticSolveWorkerBindingState.ADMITTED,
    AutomaticSolveWorkerBindingState.ACTIVE,
    AutomaticSolveWorkerBindingState.UNKNOWN,
    AutomaticSolveWorkerBindingState.TERMINAL,
    AutomaticSolveWorkerBindingState.SUPERSEDED,
])
def test_resume_rejects_unresolved_or_frozen_states(tmp_path, state):
    store, _run, _worker, _attempt, binding = _fixture(tmp_path)
    admitted = store.create_automatic_solve_worker_binding(binding)
    with pytest.raises(ValueError, match="not resumable"):
        store.resume_automatic_solve_worker_binding(
            replace(admitted, state=state), replace(binding, generation=1, prior_generation=0),
        )


def test_concurrent_resumes_have_one_winner(tmp_path):
    store, run, worker, attempt, binding = _fixture(tmp_path)
    expected = store.create_automatic_solve_worker_binding(binding)
    expected = store.compare_and_swap_automatic_solve_worker_binding(
        expected, state=AutomaticSolveWorkerBindingState.RECOVERY_REQUIRED,
    )
    assert expected is not None
    store.settle_worker(worker.id, attempt.id, WorkerOutcome.LOST)
    workers = [store.create_worker(run.id, "solver", f"resume-{index}", agent_type="fixture") for index in range(2)]
    attempts = [
        store.start_worker_attempt(item.id, run.id, f"resume-{index}", service_owner_id=f"resume-service-{index}")
        for index, item in enumerate(workers)
    ]
    bindings = [
        replace(binding, binding_id=f"automatic-binding-{index + 2}", worker_id=item.id,
                worker_attempt_id=attempt_item.id, service_owner_id=f"resume-service-{index}",
                generation=1, prior_generation=0)
        for index, (item, attempt_item) in enumerate(zip(workers, attempts))
    ]

    def resume(candidate):
        return Store(store.database).resume_automatic_solve_worker_binding(expected, candidate)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(resume, bindings))
    assert sum(result is not None for result in results) == 1
    assert len(store.list_automatic_solve_worker_bindings(run.id)) == 2


def test_reads_require_owner_and_detect_result_tampering(tmp_path):
    store, run, _worker, attempt, binding = _fixture(tmp_path)
    admitted = store.create_automatic_solve_worker_binding(binding)
    with pytest.raises(PermissionError):
        store.get_automatic_solve_worker_binding(binding.binding_id, owner_id="other")
    store.cancel_run(run.id)
    reference = AutomaticSolveWorkerResultReference(
        binding.binding_id, 0, run.id, attempt.id, "cancelled", {"receipt": "a" * 64},
    )
    store.create_automatic_solve_worker_result_reference(admitted, reference)
    with store._connect() as connection:
        connection.execute("UPDATE automatic_solve_worker_result_refs SET reference = ?", ('{"receipt":"tampered"}',))
    with pytest.raises(ValueError, match="digest"):
        store.get_automatic_solve_worker_result_reference(binding.binding_id, owner_id=run.id, generation=0)


def test_result_mapping_mutation_after_dto_creation_is_rejected(tmp_path):
    store, run, _worker, attempt, binding = _fixture(tmp_path)
    admitted = store.create_automatic_solve_worker_binding(binding)
    store.cancel_run(run.id)
    reference = AutomaticSolveWorkerResultReference(
        binding.binding_id, 0, run.id, attempt.id, "cancelled", {"receipt": "a" * 64},
    )
    reference.reference["receipt"] = "b" * 64
    with pytest.raises(ValueError, match="digest"):
        store.create_automatic_solve_worker_result_reference(admitted, reference)


@pytest.mark.parametrize("policy", ['{"limit":1,"limit":2}', '{"inner":{"limit":1,"limit":2}}', '{"limit":NaN}'])
def test_budget_policy_is_strict_json(tmp_path, policy):
    _store, _run, _worker, _attempt, binding = _fixture(tmp_path)
    with pytest.raises(ValueError, match="budget policy"):
        replace(binding, budget_policy=policy)


def test_result_digest_includes_every_owner_field():
    reference = AutomaticSolveWorkerResultReference("binding", 0, "run", "attempt", "cancelled", {"receipt": "a"})
    for name, value in (("binding_id", "other"), ("generation", 1), ("run_id", "other"),
                        ("worker_attempt_id", "other"), ("outcome", "failed")):
        with pytest.raises(ValueError, match="digest"):
            replace(reference, **{name: value})


def test_existing_database_migration_preserves_worker_tables(tmp_path):
    store, run, worker, _attempt, _binding = _fixture(tmp_path)
    with store._connect() as connection:
        connection.execute("DROP TABLE automatic_solve_worker_result_refs")
        connection.execute("DROP TABLE automatic_solve_worker_bindings")
        connection.execute("DELETE FROM schema_migrations WHERE version = 11")
    store.initialize()
    store.initialize()
    assert store.get_run(run.id) == run
    assert store.get_worker(worker.id).id == worker.id
    assert store.list_automatic_solve_worker_bindings(run.id) == []
    with store._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM schema_migrations WHERE version = 11").fetchone()[0] == 1
