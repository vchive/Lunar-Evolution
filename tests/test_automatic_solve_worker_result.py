"""Provider-free, read-only native WorkerService result references."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_conversational_automatic_bundle import automatic_setup

from lunar_evolution import cli
from lunar_evolution.automatic_solve_worker_binding import (
    AutomaticSolveWorkerBinding,
    AutomaticSolveWorkerResultReference,
)
from lunar_evolution.automatic_solve_worker_result import (
    NativeResultReferenceError,
    capture_native_result,
    validate_native_result,
)
from lunar_evolution.cli import _compiler_fingerprint
from lunar_evolution.config import Config
from lunar_evolution.controller import LocalController
from lunar_evolution.runtime import MockRuntime
from lunar_evolution.store import Store


def _digest(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _binding(controller, run, *, child_id=None, contract_digest=None):
    store = controller.store
    requests = [event["payload"] for event in store.list_events(run.id) if event["type"] == "evolution_requested"]
    if not requests:
        request = {"automatic_lifecycle_version": 1, "bundle_mode": "compiled", "strategy": "population", "timeout": 3}
        store.append_event(run.id, "evolution_requested", request)
    else:
        assert len(requests) == 1
        request = requests[0]
    worker = store.create_worker(run.id, "solver", "native bridge", agent_type="fixture")
    attempt = store.start_worker_attempt(worker.id, run.id, "native bridge", service_owner_id="service-owner")
    return AutomaticSolveWorkerBinding(
        binding_id="automatic-binding-result", owner_id=run.id, run_id=run.id,
        workspace_identity=str(run.workspace), worker_id=worker.id, worker_attempt_id=attempt.id,
        service_owner_id="service-owner", lifecycle_digest=_digest(request),
        runtime_fingerprint=_compiler_fingerprint(controller.runtime), budget_policy=request,
        contract_digest=contract_digest, child_run_id=child_id,
    )


def _terminal(tmp_path, *, outcome="cancelled"):
    controller = LocalController(Config(tmp_path / "home"), MockRuntime())
    workspace = tmp_path / "run"
    workspace.mkdir()
    run = controller.store.create_run("cancel", workspace)
    binding = _binding(controller, run)
    if outcome == "failed":
        assert controller.store.fail_budget(run.id, "solve_wall_timeout", 3, 3, "expired")
    else:
        assert controller.store.cancel_run(run.id)
    return controller, controller.store.get_run(run.id), binding


def _completed(tmp_path, monkeypatch, capsys):
    runtime, args = automatic_setup(tmp_path, monkeypatch)
    assert cli.main(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "succeeded"
    store = Store(tmp_path / "home/state.db")
    controller = LocalController(Config(tmp_path / "home"), runtime, store=store)
    parent = store.get_run(payload["run_id"])
    child = store.get_run(payload["evolution"]["run_id"])
    binding = _binding(controller, parent, child_id=child.id, contract_digest=controller._algorithm_contract(parent).digest())
    assert parent.status.value == child.status.value == "succeeded"
    return controller, parent, child, binding, payload


def _snapshot(controller, parent, child=None):
    runs = (parent,) if child is None else (parent, child)
    files = {
        path.relative_to(parent.workspace).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in parent.workspace.rglob("*") if path.is_file()
    }
    return files, [(controller.store.list_events(run.id), controller.store.list_artifacts(run.id)) for run in runs]


def _forbid_work(monkeypatch, controller):
    def forbidden(*_args, **_kwargs):
        pytest.fail("read-only native evidence inspection attempted work")

    monkeypatch.setattr(controller.runtime, "run", forbidden)
    for name in ("run_evolution", "deliver_bundle_to_parent", "deliver", "cleanup_automatic_solve", "cancel"):
        monkeypatch.setattr(controller, name, forbidden)
    for name in ("add_artifact", "append_event", "commit_output_publication", "settle_run", "clear_attempt_process", "clear_worker_process"):
        monkeypatch.setattr(controller.store, name, forbidden)
    monkeypatch.setattr("lunar_evolution.output_publication._locked", forbidden)


def test_cancelled_native_result_is_bounded_and_read_only(tmp_path, monkeypatch):
    controller, run, binding = _terminal(tmp_path)
    before = _snapshot(controller, run)
    _forbid_work(monkeypatch, controller)
    reference = capture_native_result(controller, binding)
    assert reference["kind"] == "lunar-native-result-reference"
    assert reference["outcome"] == "cancelled"
    assert reference["native"]["delivery"] is None
    assert "inode" in reference["workspace"]
    assert len(json.dumps(reference).encode()) < 12 * 1024
    assert str(run.workspace) not in json.dumps(reference)
    assert validate_native_result(controller, binding, reference) == reference
    assert _snapshot(controller, run) == before


def test_failed_native_result_accepts_budget_terminal_without_delivery(tmp_path):
    controller, _run, binding = _terminal(tmp_path, outcome="failed")
    reference = capture_native_result(controller, binding)
    assert reference["outcome"] == "failed"
    assert reference["native"]["terminal_event"] == "budget_exceeded"
    assert reference["native"]["delivery"] is None


def test_successful_native_result_reopens_complete_automatic_delivery_read_only(tmp_path, monkeypatch, capsys):
    controller, parent, child, binding, _payload = _completed(tmp_path, monkeypatch, capsys)
    before = _snapshot(controller, parent, child)
    _forbid_work(monkeypatch, controller)
    reference = capture_native_result(controller, binding)
    assert reference["outcome"] == "succeeded"
    assert reference["native"]["child_run_id"] == child.id
    assert reference["native"]["delivery"]["outputs_count"] == 1
    assert validate_native_result(controller, binding, reference) == reference
    assert _snapshot(controller, parent, child) == before
    dto = AutomaticSolveWorkerResultReference(
        binding_id=binding.binding_id, generation=binding.generation,
        run_id=binding.run_id, worker_attempt_id=binding.worker_attempt_id,
        outcome="succeeded", reference=reference,
    )
    assert validate_native_result(controller, binding, dto) == reference


@pytest.mark.parametrize("changed", ["source", "receipt", "report", "copied_output", "parent_output", "terminal", "reverse", "contract", "missing_delivery"])
def test_successful_native_result_refuses_changed_evidence_read_only(tmp_path, monkeypatch, capsys, changed):
    controller, parent, child, binding, payload = _completed(tmp_path, monkeypatch, capsys)
    reference = capture_native_result(controller, binding)
    delivery = payload["evolution"]["materialization"]
    candidate = Path(child.workspace) / delivery["candidate_path"]
    if changed in {"source", "receipt", "report", "copied_output", "parent_output"}:
        target = {
            "source": candidate.parent / "helper.py",
            "receipt": candidate.parent / "receipt.json",
            "report": parent.workspace / delivery["evaluation_report_path"],
            "copied_output": parent.workspace / delivery["delivery_path"] / "output/result.json",
            "parent_output": parent.workspace / "output/result.json",
        }[changed]
        target.write_bytes(target.read_bytes() + b" ")
    elif changed == "missing_delivery":
        (parent.workspace / delivery["delivery_path"] / "delivery.json").unlink()
    else:
        with controller.store._connect() as connection:
            if changed == "terminal":
                connection.execute("DELETE FROM events WHERE run_id = ? AND type = 'bundle_candidate_delivered'", (parent.id,))
            elif changed == "reverse":
                connection.execute("DELETE FROM events WHERE run_id = ? AND type = 'evolution_parent_linked'", (child.id,))
            else:
                connection.execute("UPDATE runs SET current_plan_id = NULL WHERE id = ?", (parent.id,))
    before = _snapshot(controller, parent, child)
    _forbid_work(monkeypatch, controller)
    with pytest.raises(NativeResultReferenceError):
        validate_native_result(controller, binding, reference)
    assert _snapshot(controller, parent, child) == before


@pytest.mark.parametrize("cleanup", ["runner", "partial_runner", "attempt", "worker"])
def test_terminal_result_refuses_unreleased_processes_without_cleaning_them(tmp_path, monkeypatch, cleanup):
    controller, run, binding = _terminal(tmp_path)
    reference = capture_native_result(controller, binding)
    store = controller.store
    if cleanup == "worker":
        assert store.register_worker_process(binding.worker_id, binding.worker_attempt_id, binding.service_owner_id, 424242, 424242)
    elif cleanup == "attempt":
        task = store.list_tasks(run.id)[0]
        with store._connect() as connection:
            connection.execute(
                "INSERT INTO attempts(id, task_id, runtime, status, started_at, pid, pgid) VALUES(?, ?, ?, ?, ?, ?, ?)",
                ("old-attempt", task.id, "fixture", "cancelled", "old", 424242, None),
            )
    else:
        with store._connect() as connection:
            connection.execute("UPDATE runs SET runner_pid = ?, runner_pgid = ? WHERE id = ?",
                               (424242, None if cleanup == "partial_runner" else 424242, run.id))
    _forbid_work(monkeypatch, controller)
    with pytest.raises(NativeResultReferenceError, match="cleanup"):
        validate_native_result(controller, binding, reference)


@pytest.mark.parametrize("changed", ["runtime", "request", "duplicate_request", "lifecycle_type", "policy", "generation", "workspace_inode", "reference"])
def test_native_result_rejects_changed_pins(tmp_path, changed):
    controller, run, binding = _terminal(tmp_path)
    reference = capture_native_result(controller, binding)
    if changed == "runtime":
        controller.runtime = SimpleNamespace(name="changed-runtime")
    elif changed == "policy":
        binding = replace(binding, budget_policy={"timeout": 9})
    elif changed == "generation":
        binding = replace(binding, generation=1, prior_generation=0)
    elif changed == "workspace_inode":
        run.workspace.rename(run.workspace.with_name("old-workspace"))
        run.workspace.mkdir()
    elif changed == "reference":
        reference["native"]["terminal_event_sha256"] = "f" * 64
    else:
        request = json.loads(binding.budget_policy)
        if changed == "request":
            request["timeout"] = 9
        elif changed == "lifecycle_type":
            request["automatic_lifecycle_version"] = True
        if changed == "duplicate_request":
            controller.store.append_event(run.id, "evolution_requested", request)
        else:
            with controller.store._connect() as connection:
                connection.execute("UPDATE events SET payload = ? WHERE run_id = ? AND type = 'evolution_requested'",
                                   (json.dumps(request), run.id))
    with pytest.raises(NativeResultReferenceError):
        validate_native_result(controller, binding, reference)


def test_unverified_parent_success_cannot_become_worker_success(tmp_path):
    controller, run, binding = _terminal(tmp_path)
    with controller.store._connect() as connection:
        connection.execute("UPDATE runs SET status = 'succeeded' WHERE id = ?", (run.id,))
    controller.store.append_event(run.id, "run_succeeded", {})
    with pytest.raises(NativeResultReferenceError, match="delivery"):
        capture_native_result(controller, binding)


@pytest.mark.parametrize("damage", ["dto_bytes", "dto_outcome", "boolean_inode"])
def test_native_reference_rejects_mutated_dto_and_json_type_aliases(tmp_path, damage):
    controller, _run, binding = _terminal(tmp_path)
    payload = capture_native_result(controller, binding)
    if damage == "boolean_inode":
        payload["workspace"]["inode"] = True
        reference = payload
    else:
        reference = AutomaticSolveWorkerResultReference(
            binding_id=binding.binding_id, generation=binding.generation,
            run_id=binding.run_id, worker_attempt_id=binding.worker_attempt_id,
            outcome="failed" if damage == "dto_outcome" else "cancelled", reference=payload,
        )
        if damage == "dto_bytes":
            reference.reference["native"]["terminal_event_sha256"] = "a" * 64
    with pytest.raises(NativeResultReferenceError, match="reference"):
        validate_native_result(controller, binding, reference)


@pytest.mark.parametrize("link", [{}, {"evolution_run_id": None, "contract_sha256": "a" * 64, "strategy": "population"}])
def test_terminal_native_result_rejects_malformed_child_link(tmp_path, link):
    controller, run, binding = _terminal(tmp_path)
    controller.store.append_event(run.id, "evolution_linked", link)
    with pytest.raises(NativeResultReferenceError, match="child"):
        capture_native_result(controller, binding)


@pytest.mark.parametrize("outcome", ["failed", "cancelled"])
@pytest.mark.parametrize("damage", [None, "workspace", "terminal", "running", "cleanup"])
def test_non_success_terminal_result_checks_reciprocal_child_evidence(tmp_path, monkeypatch, capsys, outcome, damage):
    controller, parent, child, binding, _payload = _completed(tmp_path, monkeypatch, capsys)
    with controller.store._connect() as connection:
        connection.execute("UPDATE runs SET status = ? WHERE id = ?", (outcome, parent.id))
    controller.store.append_event(parent.id, "run_" + outcome, {})
    reference = capture_native_result(controller, binding)
    assert reference["native"]["child"]["status"] == "succeeded"
    assert reference["native"]["delivery"] is None
    if damage is None:
        _forbid_work(monkeypatch, controller)
        assert validate_native_result(controller, binding, reference) == reference
        return
    with controller.store._connect() as connection:
        if damage == "workspace":
            replacement = tmp_path / "different-child"
            replacement.mkdir()
            connection.execute("UPDATE runs SET workspace = ? WHERE id = ?", (str(replacement), child.id))
        elif damage == "terminal":
            connection.execute("DELETE FROM events WHERE run_id = ? AND type = 'run_succeeded'", (child.id,))
        elif damage == "running":
            connection.execute("UPDATE runs SET status = 'running' WHERE id = ?", (child.id,))
        else:
            connection.execute("UPDATE runs SET runner_pid = 424242 WHERE id = ?", (child.id,))
    _forbid_work(monkeypatch, controller)
    with pytest.raises(NativeResultReferenceError):
        validate_native_result(controller, binding, reference)


def test_terminal_reader_does_not_recreate_missing_publication_lock(tmp_path, monkeypatch, capsys):
    controller, parent, child, binding, _payload = _completed(tmp_path, monkeypatch, capsys)
    lock = parent.workspace / ".evolved-output-publications/.lock"
    lock.unlink()
    before = _snapshot(controller, parent, child)
    _forbid_work(monkeypatch, controller)
    assert capture_native_result(controller, binding)["outcome"] == "succeeded"
    assert not lock.exists()
    assert _snapshot(controller, parent, child) == before
