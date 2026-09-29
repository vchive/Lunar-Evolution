from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from lunar_evolution.automatic_solve_worker_binding import (
    AutomaticSolveWorkerBinding,
    AutomaticSolveWorkerBindingState,
    AutomaticSolveWorkerResultReference,
)
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
