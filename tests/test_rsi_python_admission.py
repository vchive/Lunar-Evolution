"""Late RSI evidence registration over inert local files, without a producer launch."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections import UserDict
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_python_producer_binding import _fixture
from test_python_producer_recovery_anchor import _durable_snapshot

from lunar_evolution import RSILearningController, RSILearningError, RSILedger
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.producer_bundle_intent import _intent_content
from lunar_evolution.producer_bundle_publication import (
    ProducerBundlePublicationCandidate,
    build_producer_bundle_publication_journal,
)
from lunar_evolution.producer_launcher import build_producer_launch_attestation
from lunar_evolution.python_producer_admission_anchor import (
    persist_python_producer_admission_attempt_anchor,
    project_python_producer_admission_attempt_anchor,
)
from lunar_evolution.python_producer_admission_handoff import (
    build_python_producer_admission_handoff,
    persist_python_producer_admission_handoff_pinned,
)
from lunar_evolution.python_producer_binding import build_python_producer_binding
from lunar_evolution.python_producer_binding_store import persist_python_producer_binding
from lunar_evolution.python_producer_checkpoint import PythonProducerCheckpointBinding
from lunar_evolution.rsi_budget import RSIRunBudget
from lunar_evolution.rsi_gateway import SolverRequest, SolverResult
from lunar_evolution.rsi_learning import PracticeEpisode
from lunar_evolution.rsi_native_plan import NativeRSIExecutionPlan
from lunar_evolution.rsi_python_admission import (
    MAX_RSI_PYTHON_ADMISSION_BYTES,
    RSIPythonAdmissionError,
    RSIPythonAdmissionRecord,
    parse_rsi_python_admission_record,
)

DIGEST = "a" * 64
OTHER = "b" * 64
DEADLINE = 4102444800.125


class _DispatchInterrupted(BaseException):
    pass


class _NoSolverGateway:
    def __init__(self):
        self.calls = 0

    def rsi_fingerprint_config(self):
        return {"fixture": "late-python-admission-no-solver"}

    def run(self, request):
        # The original controller writes its intent and running episode first.
        # No solver, model, evaluator or native process is invoked by this gateway.
        self.calls += 1
        raise _DispatchInterrupted()


def _plan(binding, request, memory):
    return NativeRSIExecutionPlan.build(
        request=request, memory_snapshot=memory,
        journal_id=binding.intent.journal_id, launch_id=binding.intent.launch_id,
        run_id=binding.run_id, parent_task_id=binding.parent_task_id,
        task_id=binding.task_id, intent_sha256=binding.intent_sha256,
        attestation_sha256=binding.attestation_sha256,
        bootstrap_descriptor_sha256=DIGEST, bootstrap_artifact_sha256=DIGEST,
        manifest_sha256=DIGEST, candidate_selector_sha256=DIGEST,
        evaluator_kind="local", evaluator_fingerprint=binding.evaluator_fingerprint,
        deadline_unix=binding.deadline_unix,
    )


def _setup(tmp_path: Path, *, originally_bound: bool = True):
    manifest, tree, intent, _attestation, _budget = _fixture(tmp_path)
    binding = build_python_producer_binding(
        runtime_manifest=manifest, runtime_tree=tree, intent=intent,
        attestation=build_producer_launch_attestation(intent, "late-admission-once"),
        deadline_unix=DEADLINE,
        budget=RSIRunBudget.create({"deadline_unix": DEADLINE, "max_solver_invocations": 3}),
    )
    batch = tmp_path / "evolution/producer-batches" / intent.journal_id
    # A stricter fixture may have already sealed create-only native inputs in
    # this batch before constructing the launch intent and original sidecar.
    batch.mkdir(parents=True, mode=0o700, exist_ok=True)
    sidecar = persist_python_producer_binding(tmp_path, binding=binding)
    proof = PythonProducerCheckpointBinding.from_sidecar(sidecar)
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    gateway = _NoSolverGateway()
    controller = RSILearningController(
        gateway, ledger=ledger,
        **({"producer_sidecar": sidecar, "producer_workspace": tmp_path}
           if originally_bound else {}),
    )
    with pytest.raises(_DispatchInterrupted):
        controller.run_drs(
            run_id=binding.run_id, contract_sha256=DIGEST, evaluator_sha256=DIGEST,
            environment_sha256=DIGEST, solver_id="native",
            max_practice_rounds=0, budget={"deadline_unix": DEADLINE},
        )
    episode_id = binding.run_id + "-target-0"
    checkpoint = ledger.controller_checkpoint(binding.run_id)
    request = SolverRequest.from_dict(checkpoint[1]["intents"][episode_id]["request"])
    plan = _plan(binding, request, controller.snapshot)
    claim = ledger.claim_native_episode(request, plan_sha256=plan.plan_sha256)
    handoff = build_python_producer_admission_handoff(
        run_id=binding.run_id, journal_id=intent.journal_id,
        parent_task_id=binding.parent_task_id, task_id=binding.task_id,
        binding_sha256=binding.binding_sha256, sidecar_raw_sha256=sidecar.raw_sha256,
        sidecar_pin_sha256=hashlib.sha256(canonical_json(dict(proof.sidecar_pin))).hexdigest(),
        launch_intent_sha256=binding.intent_sha256, attestation_sha256=binding.attestation_sha256,
        runtime_manifest_sha256=binding.runtime_manifest_sha256,
        runtime_tree_sha256=binding.runtime_tree_sha256,
        executable_owner_sha256=DIGEST, native_execution_receipt_sha256=DIGEST,
        terminal_sha256=DIGEST, runtime_observation_sha256=DIGEST,
        broker_transcript_sha256=DIGEST, envelope_sha256=DIGEST, materials_sha256=DIGEST,
        contract_sha256=binding.contract_sha256, evaluator_sha256=binding.evaluator_fingerprint,
        runner_sha256=binding.intent.runner_fingerprint,
        dependency_sha256=binding.dependency_sha256, environment_sha256=binding.environment_sha256,
        admission_plan_sha256=OTHER, request_budget=binding.request_budget,
        wall_timeout_seconds=binding.wall_timeout_seconds, deadline_unix=binding.deadline_unix,
    )
    pinned = persist_python_producer_admission_handoff_pinned(batch, handoff=handoff)
    candidate = ProducerBundlePublicationCandidate(
        candidate_id="candidate-1", bundle_id="bundle-1", bundle_sha256=DIGEST,
        parent_id=None, generation=0, iteration=0, island_id=0,
        preparation_receipt_sha256=DIGEST,
    )
    journal = build_producer_bundle_publication_journal(
        journal_id=intent.journal_id, run_id=binding.run_id,
        parent_task_id=binding.parent_task_id, task_id=binding.task_id,
        admission_sha256=OTHER, archive_prefix_sha256=DIGEST,
        base_archive_sha256=DIGEST, base_state_sha256=DIGEST,
        contract_sha256=binding.contract_sha256, evaluator_kind="local",
        evaluator_fingerprint=binding.evaluator_fingerprint,
        runner_fingerprint=binding.intent.runner_fingerprint,
        dependency_sha256=binding.dependency_sha256,
        environment_sha256=binding.environment_sha256, budget_sha256=DIGEST,
        strategy="population", population_config_sha256=DIGEST, num_islands=1,
        candidates=(candidate,), native_execution_receipt_sha256=DIGEST,
        python_handoff_sha256=handoff.handoff_sha256, python_handoff_file_pin=pinned.file_pin,
    )
    (batch / "journal.prepared.json").write_bytes(_intent_content(journal)[0])
    (batch / "journal.prepared.json").chmod(0o600)
    anchor = project_python_producer_admission_attempt_anchor(handoff)
    persist_python_producer_admission_attempt_anchor(batch, anchor=anchor)
    if not originally_bound:
        controller = RSILearningController(
            gateway, ledger=ledger, producer_sidecar=sidecar, producer_workspace=tmp_path,
        )
    assert gateway.calls == 1
    assert ledger.get_episode(episode_id).state == "running"
    return SimpleNamespace(
        workspace=tmp_path, batch=batch, binding=binding, sidecar=sidecar,
        proof=proof, ledger=ledger, gateway=gateway, controller=controller,
        episode_id=episode_id, request=request, plan=plan, claim=claim,
        handoff=handoff, pin=pinned.file_pin, journal=journal, anchor=anchor,
    )


def _register(value, **changes):
    arguments = {"native_plan": value.plan, "prepared_journal": value.journal,
                 "expected_anchor_sha256": value.anchor.anchor_sha256, **changes}
    return value.controller.register_python_admission(
        value.binding.run_id, value.episode_id, **arguments,
    )


def _validate(value, record, **changes):
    arguments = {"native_plan": value.plan, "prepared_journal": value.journal,
                 "expected_anchor_sha256": value.anchor.anchor_sha256,
                 "expected_record_sha256": record.record_sha256, **changes}
    return value.controller.validate_python_admission(
        value.binding.run_id, value.episode_id, **arguments,
    )


def _rows(value, *, include_admission=True):
    with sqlite3.connect(value.ledger.database) as connection:
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name",
        ).fetchall()
        return {
            name: connection.execute('SELECT * FROM "' + name + '" ORDER BY rowid').fetchall()
            for (name,) in tables if include_admission or name != "rsi_python_admissions"
        }


def _files(value):
    database = value.ledger.database.relative_to(value.workspace)
    # SQLite's connection lifecycle may replace WAL/SHM metadata even for reads.
    # SQL row snapshots independently cover all durable ledger bytes/timestamps.
    # Exclude before touching metadata: a sidecar can vanish after enumeration.
    return _durable_snapshot(
        value.workspace,
        exclude=lambda name: name == database or (
            name.parent == database.parent and name.name.startswith(database.name + "-")
        ),
    )


def _assert_no_effect(value, operation, *, match=None):
    rows, files, calls = _rows(value), _files(value), value.gateway.calls
    with pytest.raises(RSILearningError, match=match) as caught:
        operation()
    assert _rows(value) == rows
    assert _files(value) == files
    assert value.gateway.calls == calls
    return caught.value


def _checkpoint_change(value, mutate):
    current, state = value.ledger.controller_checkpoint(value.binding.run_id)
    state = deepcopy(state)
    mutate(state)
    with value.ledger.controller_lock(value.binding.run_id):
        value.ledger.write_controller_checkpoint(value.binding.run_id, state, expected_sha256=current)


def _run_state(value, state):
    current = value.ledger.get_run(value.binding.run_id)
    value.ledger.transition(
        value.binding.run_id, state=state, expected_record_sha256=current.record_sha256,
    )
    _checkpoint_change(value, lambda wire: wire.update(status=state))


def test_original_wires_and_budget_are_unchanged_by_late_registration(tmp_path):
    value = _setup(tmp_path)
    original_rows, files = _rows(value, include_admission=False), _files(value)
    checkpoint = value.ledger.controller_checkpoint(value.binding.run_id)
    run_history = value.ledger.history(value.binding.run_id)
    plan_wire = canonical_json(value.plan.to_dict())
    record = _register(value)
    assert type(record) is RSIPythonAdmissionRecord
    assert record.production_admission is False
    assert record.original_run_request_sha256 == run_history[0].request_sha256
    assert record.original_run_record_sha256 == run_history[0].record_sha256
    assert record.episode_request_sha256 == value.request.digest()
    assert record.native_claim_sha256 == value.claim.claim_sha256
    assert record.native_plan_sha256 == value.plan.plan_sha256
    assert record.prepared_journal_sha256 == value.journal.journal_sha256
    assert record.admission_anchor == value.anchor.to_dict()
    assert record.handoff_file_pin == value.pin.to_dict()
    assert record.admission_anchor["admission_plan_sha256"] != value.plan.plan_sha256
    assert record.admission_anchor["wall_timeout_seconds"] == value.binding.wall_timeout_seconds
    assert record.admission_anchor["deadline_unix"] == DEADLINE
    assert record.record_sha256 == record.digest()
    assert _rows(value, include_admission=False) == original_rows
    assert _files(value) == files
    assert value.ledger.controller_checkpoint(value.binding.run_id) == checkpoint
    assert value.ledger.history(value.binding.run_id) == run_history
    assert canonical_json(value.plan.to_dict()) == plan_wire
    assert value.gateway.calls == 1


def test_exact_replay_and_explicit_validation_write_nothing(tmp_path):
    value = _setup(tmp_path)
    record = _register(value)
    rows, files = _rows(value), _files(value)
    assert _register(value) == record
    assert _validate(value, record) == record
    assert _rows(value) == rows  # Includes created_at and the entire original ledger.
    assert _files(value) == files
    assert value.gateway.calls == 1


@pytest.mark.parametrize("state", ["completed", "failed", "cancelled", "unknown", "budget_exhausted"])
def test_retained_record_is_readable_after_terminal_or_unknown(tmp_path, state):
    value = _setup(tmp_path)
    record = _register(value)
    _run_state(value, state)
    rows, files = _rows(value), _files(value)
    assert _validate(value, record) == record
    assert _register(value) == record
    assert _rows(value) == rows
    assert _files(value) == files


@pytest.mark.parametrize("state", ["completed", "failed", "cancelled", "unknown", "budget_exhausted"])
def test_terminal_or_unknown_run_cannot_backfill_missing_record(tmp_path, state):
    value = _setup(tmp_path)
    _run_state(value, state)
    _assert_no_effect(value, lambda: _register(value))


def test_unbound_original_run_cannot_acquire_post_execution_proof(tmp_path):
    value = _setup(tmp_path, originally_bound=False)
    assert "producer_checkpoint_binding" not in value.ledger.history(value.binding.run_id)[0].payload
    _assert_no_effect(value, lambda: _register(value))


def test_coherently_resigned_proof_cannot_keep_old_original_request_digest(tmp_path):
    value = _setup(tmp_path)
    original_request = value.ledger.history(value.binding.run_id)[0].request_sha256
    path = value.batch / "python-producer-binding.json"
    path.rename(value.batch / "retained-old-binding.json")
    value.sidecar = persist_python_producer_binding(value.workspace, binding=value.binding)
    value.controller.producer_sidecar = value.sidecar
    value.proof = PythonProducerCheckpointBinding.from_sidecar(value.sidecar)
    proof_wire = value.proof.to_dict()

    # Re-sign all trusted record and checkpoint chains consistently.  The original
    # pre-execution request digest is deliberately retained, so its payload drift
    # must still refuse even though every latest DTO and file is internally valid.
    with sqlite3.connect(value.ledger.database) as connection:
        connection.row_factory = sqlite3.Row
        runs = connection.execute(
            "SELECT * FROM rsi_records WHERE logical_id=? ORDER BY revision", (value.binding.run_id,),
        ).fetchall()
        parent = None
        for row in runs:
            payload = json.loads(row["payload"])
            payload["producer_checkpoint_binding"] = proof_wire
            digest = value.ledger._record_digest(
                logical_id=row["logical_id"], revision=row["revision"], kind=row["kind"],
                state=row["state"], request_sha256=row["request_sha256"],
                parent_record_sha256=parent, payload=payload,
            )
            connection.execute(
                "UPDATE rsi_records SET payload=?,parent_record_sha256=?,record_sha256=? "
                "WHERE logical_id=? AND revision=?",
                (json.dumps(payload, sort_keys=True), parent, digest, row["logical_id"], row["revision"]),
            )
            parent = digest
        checkpoints = connection.execute(
            "SELECT * FROM rsi_controller_journal WHERE run_id=? ORDER BY revision", (value.binding.run_id,),
        ).fetchall()
        parent = None
        for row in checkpoints:
            payload = json.loads(row["payload"])
            payload["producer_checkpoint_binding"] = proof_wire
            digest = value.ledger._checkpoint_digest(value.binding.run_id, row["revision"], parent, payload)
            connection.execute(
                "UPDATE rsi_controller_journal SET payload=?,parent_sha256=?,checkpoint_sha256=? "
                "WHERE run_id=? AND revision=?",
                (json.dumps(payload, sort_keys=True), parent, digest, value.binding.run_id, row["revision"]),
            )
            parent = digest

    handoff_wire = value.handoff.to_dict()
    del handoff_wire["handoff_sha256"]
    handoff_wire["sidecar_pin_sha256"] = hashlib.sha256(canonical_json(dict(value.proof.sidecar_pin))).hexdigest()
    value.handoff = build_python_producer_admission_handoff(handoff_wire)
    (value.batch / "python-producer-admission-handoff.json").rename(value.batch / "retained-old-handoff.json")
    value.pin = persist_python_producer_admission_handoff_pinned(value.batch, handoff=value.handoff).file_pin
    value.journal = replace(value.journal, python_handoff_sha256=value.handoff.handoff_sha256,
                            python_handoff_file_pin=value.pin, journal_sha256=None)
    value.journal = replace(value.journal, journal_sha256=value.journal.digest())
    (value.batch / "journal.prepared.json").write_bytes(_intent_content(value.journal)[0])
    value.anchor = project_python_producer_admission_attempt_anchor(value.handoff)
    (value.batch / "python-producer-admission-anchor.json").write_bytes(value.anchor.to_json())
    assert value.ledger.history(value.binding.run_id)[0].request_sha256 == original_request
    _assert_no_effect(value, lambda: _register(value), match="original_request_drift")


@pytest.mark.parametrize("raw", ["[]", "null", '"wrong"', "{"])
def test_corrupt_checkpoint_returns_fixed_refusal_without_admission_write(tmp_path, raw):
    value = _setup(tmp_path)
    with sqlite3.connect(value.ledger.database) as connection:
        connection.execute(
            "UPDATE rsi_controller_journal SET payload=? WHERE run_id=? "
            "AND revision=(SELECT MAX(revision) FROM rsi_controller_journal WHERE run_id=?)",
            (raw, value.binding.run_id, value.binding.run_id),
        )
    _assert_no_effect(value, lambda: _register(value), match="rsi_python_admission_evidence_invalid")


@pytest.mark.parametrize("mutation", ["drop-proof", "drift-proof", "drop-intent", "request", "memory", "episode"])
def test_checkpoint_original_proof_and_episode_attribution_cannot_drift(tmp_path, mutation):
    value = _setup(tmp_path)

    def mutate(state):
        if mutation == "drop-proof":
            del state["producer_checkpoint_binding"]
        elif mutation == "drift-proof":
            state["producer_checkpoint_binding"]["sidecar_pin"]["file_inode"] += 1
        elif mutation == "drop-intent":
            del state["intents"][value.episode_id]
        elif mutation == "request":
            state["intents"][value.episode_id]["request"]["budget"]["deadline_unix"] += 1
        elif mutation == "memory":
            state["intents"][value.episode_id]["episode"]["memory_snapshot_sha256"] = OTHER
        else:
            state["intents"][value.episode_id]["episode"]["run_id"] = "foreign-run"

    _checkpoint_change(value, mutate)
    _assert_no_effect(value, lambda: _register(value))


@pytest.mark.parametrize("field", ["deadline_unix", "max_solver_invocations", "max_target_attempts"])
@pytest.mark.parametrize("location", ["checkpoint", "current-run"])
def test_original_planned_budget_cannot_change_before_first_registration(tmp_path, field, location):
    value = _setup(tmp_path)
    original = value.ledger.history(value.binding.run_id)[0]

    def changed_budget(wire):
        changed = deepcopy(wire)
        previous = changed["planned"][field]
        changed["planned"][field] = 4 if previous is None else previous + 1
        if field != "deadline_unix":
            counter = {"max_solver_invocations": "solver_invocations", "max_target_attempts": "target_attempts"}[field]
            changed["remaining"][counter] = changed["planned"][field] - changed["consumed"][counter]
        # This is a valid complete accounting snapshot, not a broken self-digest.
        assert RSIRunBudget.load(changed).to_dict() == changed
        return changed

    if location == "checkpoint":
        _checkpoint_change(value, lambda state: state.update(budget_state=changed_budget(state["budget_state"])))
    else:
        latest = value.ledger.get_run(value.binding.run_id)
        value.ledger.transition(
            value.binding.run_id, state="running", expected_record_sha256=latest.record_sha256,
            payload_patch={"budget_state": changed_budget(latest.payload["budget_state"])},
        )
    assert value.ledger.history(value.binding.run_id)[0] == original
    error = _assert_no_effect(value, lambda: _register(value), match="rsi_python_admission")
    codes = []
    while error is not None:
        codes.append(str(error))
        error = error.__cause__
    assert any("budget" in code or "deadline" in code for code in codes)


@pytest.mark.parametrize("missing", ["episode", "claim"])
def test_required_episode_and_native_claim_are_not_recreated(tmp_path, missing):
    value = _setup(tmp_path)
    with sqlite3.connect(value.ledger.database) as connection:
        if missing == "episode":
            connection.execute("DELETE FROM rsi_records WHERE logical_id=?", (value.episode_id,))
        else:
            connection.execute("DELETE FROM rsi_native_episode_claims WHERE episode_id=?", (value.episode_id,))
    _assert_no_effect(value, lambda: _register(value))


@pytest.mark.parametrize("field", [
    "run_id", "journal_id", "launch_id", "parent_task_id", "task_id",
    "intent_sha256", "attestation_sha256", "deadline_unix", "evaluator_fingerprint",
])
def test_resigned_native_plan_cannot_replace_original_claim(tmp_path, field):
    value = _setup(tmp_path)
    original = getattr(value.plan, field)
    changed = replace(value.plan, **{field: original + 1 if field == "deadline_unix"
                      else OTHER if field.endswith("sha256") or field == "evaluator_fingerprint"
                      else "foreign-id"}, plan_sha256=None)
    changed = replace(changed, plan_sha256=changed.digest())
    _assert_no_effect(value, lambda: _register(value, native_plan=changed))


@pytest.mark.parametrize("field", ["intent_sha256", "attestation_sha256", "launch_id", "deadline_unix"])
def test_self_consistent_changed_claim_and_plan_still_need_original_binding(tmp_path, field):
    value = _setup(tmp_path)
    original = getattr(value.plan, field)
    changed = replace(value.plan, **{field: original + 1 if field == "deadline_unix"
                      else OTHER if field.endswith("sha256") else "changed-launch"}, plan_sha256=None)
    changed = replace(changed, plan_sha256=changed.digest())
    claim_sha256 = value.ledger._native_claim_digest(value.episode_id, value.request.digest(), changed.plan_sha256)
    with sqlite3.connect(value.ledger.database) as connection:
        connection.execute(
            "UPDATE rsi_native_episode_claims SET plan_sha256=?,claim_sha256=? WHERE episode_id=?",
            (changed.plan_sha256, claim_sha256, value.episode_id),
        )
    _assert_no_effect(value, lambda: _register(value, native_plan=changed))


@pytest.mark.parametrize("field", [
    "run_id", "journal_id", "parent_task_id", "task_id", "admission_sha256",
    "contract_sha256", "evaluator_fingerprint", "runner_fingerprint",
    "dependency_sha256", "environment_sha256", "native_execution_receipt_sha256",
    "python_handoff_sha256", "python_handoff_file_pin",
])
def test_resigned_prepared_journal_drift_refuses_without_effects(tmp_path, field):
    value = _setup(tmp_path)
    replacement = (None if field == "python_handoff_file_pin" else "foreign-id"
                   if field.endswith("_id") else DIGEST if getattr(value.journal, field) == OTHER else OTHER)
    updates = {field: replacement}
    if field in {"run_id", "journal_id", "parent_task_id", "task_id", "python_handoff_sha256"}:
        # Keep the changed journal internally consistent so refusal also checks
        # independently retained handoff/binding/prepared authority.
        pin = value.pin.to_dict()
        pin["handoff_sha256" if field == "python_handoff_sha256" else field] = replacement
        pin["pin_sha256"] = hashlib.sha256(canonical_json({
            name: item for name, item in pin.items() if name != "pin_sha256"
        })).hexdigest()
        updates["python_handoff_file_pin"] = type(value.pin).from_dict(pin)
    changed = replace(value.journal, **updates, journal_sha256=None)
    changed = replace(changed, journal_sha256=changed.digest())
    _assert_no_effect(value, lambda: _register(value, prepared_journal=changed))


@pytest.mark.parametrize("missing", [
    "python-producer-binding.json", "python-producer-admission-handoff.json",
    "python-producer-admission-anchor.json", "journal.prepared.json",
])
def test_missing_retained_file_is_not_regenerated(tmp_path, missing):
    value = _setup(tmp_path)
    (value.batch / missing).unlink()
    _assert_no_effect(value, lambda: _register(value))
    assert not (value.batch / missing).exists()


@pytest.mark.parametrize("name", ["python-producer-binding.json", "python-producer-admission-handoff.json"])
def test_same_bytes_replacement_does_not_refresh_original_inode_pin(tmp_path, name):
    value = _setup(tmp_path)
    path = value.batch / name
    replacement = value.batch / "replacement.json"
    replacement.write_bytes(path.read_bytes())
    replacement.chmod(0o600)
    assert replacement.stat().st_ino != path.stat().st_ino
    os.replace(replacement, path)
    _assert_no_effect(value, lambda: _register(value))


@pytest.mark.parametrize("field", ["request_budget", "wall_timeout_seconds", "deadline_unix", "fingerprints"])
def test_self_consistent_content_anchor_drift_is_not_adopted(tmp_path, field):
    value = _setup(tmp_path)
    changed = replace(value.anchor, **{
        field: {**value.anchor.fingerprints, "contract": OTHER} if field == "fingerprints"
        else getattr(value.anchor, field) + 1,
    }, anchor_sha256=None)
    (value.batch / "python-producer-admission-anchor.json").write_bytes(changed.to_json())
    _assert_no_effect(value, lambda: _register(value, expected_anchor_sha256=changed.digest()))


@pytest.mark.parametrize("which", ["anchor", "record"])
def test_expected_content_digest_is_an_independent_replay_gate(tmp_path, which):
    value = _setup(tmp_path)
    record = _register(value)
    arguments = {"expected_anchor_sha256" if which == "anchor" else "expected_record_sha256": OTHER}
    _assert_no_effect(value, lambda: _validate(value, record, **arguments))


def test_explicit_validation_does_not_create_missing_record(tmp_path):
    value = _setup(tmp_path)
    _assert_no_effect(value, lambda: value.controller.validate_python_admission(
        value.binding.run_id, value.episode_id, native_plan=value.plan,
        prepared_journal=value.journal, expected_anchor_sha256=value.anchor.anchor_sha256,
        expected_record_sha256=OTHER,
    ))


@pytest.mark.parametrize("entrypoint", ["register", "validate"])
def test_foreign_controller_lock_conflict_refuses_without_ledger_or_budget_write(tmp_path, entrypoint):
    value = _setup(tmp_path)
    record = _register(value) if entrypoint == "validate" else None
    foreign = RSILedger(value.ledger.database)
    with foreign.controller_lock(value.binding.run_id):
        _assert_no_effect(value, lambda: _register(value) if entrypoint == "register" else _validate(value, record))


@pytest.mark.parametrize("entrypoint", ["register", "validate"])
def test_original_thread_controller_lock_can_be_reused_without_reacquisition(tmp_path, entrypoint):
    value = _setup(tmp_path)
    record = _register(value)
    rows, files = _rows(value), _files(value)
    with value.ledger.controller_lock(value.binding.run_id):
        observed = _register(value) if entrypoint == "register" else _validate(value, record)
        assert value.ledger.controller_lock_held(value.binding.run_id)
        assert observed == record
    assert _rows(value) == rows
    assert _files(value) == files


def test_one_original_attempt_cannot_belong_to_two_episodes(tmp_path):
    value = _setup(tmp_path)
    first = _register(value)
    original_id = value.episode_id
    value.episode_id = "second-episode"
    value.request = replace(value.request, episode_id=value.episode_id)
    checkpoint = value.ledger.controller_checkpoint(value.binding.run_id)[1]
    planned = replace(PracticeEpisode.from_dict(checkpoint["intents"][original_id]["episode"]),
                      episode_id=value.episode_id)
    _checkpoint_change(value, lambda state: state["intents"].update({
        value.episode_id: {"episode": planned.to_record_dict(), "request": value.request.to_dict()},
    }))
    value.ledger.create_episode_record(planned.transition("running", request_sha256=value.request.digest()))
    value.plan = _plan(value.binding, value.request, value.controller.snapshot)
    value.ledger.claim_native_episode(value.request, plan_sha256=value.plan.plan_sha256)
    _assert_no_effect(value, lambda: _register(value), match="attempt_conflict")
    assert value.ledger.python_admission_record(
        value.binding.run_id, original_id, value.journal.journal_id,
    ) == first


@pytest.mark.parametrize("drift", ["sidecar", "handoff", "anchor", "prepared"])
def test_evidence_drift_during_anchor_reads_prevents_any_registration(tmp_path, monkeypatch, drift):
    from lunar_evolution import python_producer_admission_anchor as anchors

    value = _setup(tmp_path)
    original = anchors.read_python_producer_admission_attempt_anchor
    injected = {}

    def read(*args, **kwargs):
        result = original(*args, **kwargs)
        if not injected:
            if drift in {"sidecar", "handoff"}:
                name = "python-producer-binding.json" if drift == "sidecar" else "python-producer-admission-handoff.json"
                path = value.batch / name
                replacement = value.batch / "read-race.json"
                replacement.write_bytes(path.read_bytes())
                replacement.chmod(0o600)
                os.replace(replacement, path)
            elif drift == "anchor":
                changed = replace(value.anchor, request_budget=value.anchor.request_budget + 1, anchor_sha256=None)
                (value.batch / "python-producer-admission-anchor.json").write_bytes(changed.to_json())
            else:
                changed = replace(value.journal, archive_prefix_sha256=OTHER, journal_sha256=None)
                (value.batch / "journal.prepared.json").write_bytes(_intent_content(changed)[0])
            injected.update(rows=_rows(value), files=_files(value))
        return result

    monkeypatch.setattr(anchors, "read_python_producer_admission_attempt_anchor", read)
    with pytest.raises(RSILearningError):
        _register(value)
    assert injected
    assert _rows(value) == injected["rows"]
    assert _files(value) == injected["files"]
    assert value.gateway.calls == 1


def test_database_compare_and_swap_uses_original_retained_heads(tmp_path, monkeypatch):
    value = _setup(tmp_path)
    original = value.ledger.register_python_admission_record
    retained = {}

    def raced(record, **kwargs):
        _checkpoint_change_unlocked(value, lambda state: state.update(phase="changed-by-fixture"))
        retained["rows"] = _rows(value)
        return original(record, **kwargs)

    monkeypatch.setattr(value.ledger, "register_python_admission_record", raced)
    with pytest.raises(RSILearningError):
        _register(value)
    assert _rows(value) == retained["rows"]
    assert value.gateway.calls == 1


def test_unknown_return_after_committed_write_retains_record_for_explicit_inspection(tmp_path, monkeypatch):
    value = _setup(tmp_path)
    original_rows, files = _rows(value, include_admission=False), _files(value)
    original = value.ledger.register_python_admission_record
    retained = {}

    def interrupted_return(record, **kwargs):
        retained["record"] = original(record, **kwargs)
        raise RSILearningError("fixture_write_return_unknown")

    with monkeypatch.context() as patch:
        patch.setattr(value.ledger, "register_python_admission_record", interrupted_return)
        with pytest.raises(RSILearningError, match="fixture_write_return_unknown"):
            _register(value)
    assert _rows(value, include_admission=False) == original_rows
    assert _files(value) == files
    rows = _rows(value)
    assert _validate(value, retained["record"]) == retained["record"]
    assert _register(value) == retained["record"]
    assert _rows(value) == rows
    assert _files(value) == files
    assert value.gateway.calls == 1


@pytest.mark.parametrize("column,content", [
    ("payload", "{"), ("record_sha256", OTHER), ("attempt_id", "foreign-attempt"),
])
def test_existing_corrupt_row_is_never_repaired_or_replaced(tmp_path, column, content):
    value = _setup(tmp_path)
    record = _register(value)
    with sqlite3.connect(value.ledger.database) as connection:
        connection.execute(
            "UPDATE rsi_python_admissions SET " + column + "=? WHERE run_id=?",
            (content, value.binding.run_id),
        )
    _assert_no_effect(value, lambda: _register(value))
    _assert_no_effect(value, lambda: _validate(value, record))


def _checkpoint_change_unlocked(value, mutate):
    current, state = value.ledger.controller_checkpoint(value.binding.run_id)
    mutate(state)
    value.ledger.write_controller_checkpoint(value.binding.run_id, state, expected_sha256=current)


@pytest.mark.parametrize("field", ["native_plan", "prepared_journal"])
def test_mutated_dto_and_callback_collections_refuse_before_callbacks(tmp_path, field):
    value = _setup(tmp_path)
    callbacks = []

    class Forbidden:
        def __iter__(self):
            pytest.fail("untrusted collection iteration")

        def __len__(self):
            callbacks.append("len")
            raise AssertionError("untrusted collection length")

        def to_dict(self):
            pytest.fail("untrusted serialization")

    if field == "native_plan":
        object.__setattr__(value.plan.request, "budget", Forbidden())
    else:
        object.__setattr__(value.journal, "candidates", Forbidden())
    _assert_no_effect(value, lambda: _register(value))
    assert callbacks == []  # A wrapped AssertionError must not hide callback execution.


def test_admission_record_canonical_roundtrip_is_independent_of_ledger(tmp_path, monkeypatch):
    value = _setup(tmp_path)
    record = _register(value)
    monkeypatch.setattr(value.ledger, "_connect", lambda: pytest.fail("DTO parser performed I/O"))
    assert parse_rsi_python_admission_record(record.to_json()) == record
    assert parse_rsi_python_admission_record(record.to_dict()) == record
    assert parse_rsi_python_admission_record(record) == record
    assert record.to_json() == canonical_json(record.to_dict())


def test_detached_record_preserves_fractional_original_anchor_values(tmp_path):
    value = _setup(tmp_path)
    record = _register(value)
    # A detached DTO can retain independently supplied fractional observations;
    # this does not alter the older integer-timeout binding or register that DTO.
    anchor = replace(value.anchor, wall_timeout_seconds=0.375, anchor_sha256=None)
    changed = replace(record, admission_anchor=anchor.to_dict(), record_sha256=None)
    changed = replace(changed, record_sha256=changed.digest())
    parsed = parse_rsi_python_admission_record(changed.to_json())
    assert parsed.admission_anchor["wall_timeout_seconds"] == 0.375
    assert parsed.admission_anchor["deadline_unix"] == DEADLINE
    assert parsed.to_json() == changed.to_json()


@pytest.mark.parametrize("field,value", [
    ("production_admission", True), ("schema_version", False), ("protocol", "foreign"),
    ("record_sha256", None), ("record_sha256", "0" * 64),
    ("native_claim_sha256", "0" * 64), ("episode_request_sha256", False),
    ("original_run_request_sha256", "bad"),
])
def test_parser_refuses_stale_mutated_admission_dto(tmp_path, field, value):
    prepared = _setup(tmp_path)
    record = _register(prepared)
    object.__setattr__(record, field, value)
    with pytest.raises(RSIPythonAdmissionError):
        parse_rsi_python_admission_record(record)


@pytest.mark.parametrize("mutation", ["digest", "extra", "missing", "duplicate", "noncanonical", "nan"])
def test_strict_record_wire_rejects_ambiguity_and_unretained_changes(tmp_path, mutation):
    value = _setup(tmp_path)
    record = _register(value)
    wire = record.to_dict()
    if mutation == "digest":
        wire["native_plan_sha256"] = OTHER
    elif mutation == "extra":
        wire["extra"] = 1
    elif mutation == "missing":
        del wire["producer_checkpoint_sha256"]
    elif mutation == "duplicate":
        wire = record.to_json()[:-1] + b',"production_admission":false}'
    elif mutation == "noncanonical":
        wire = json.dumps(wire)
    else:
        wire = b'{"value":NaN}'
    with pytest.raises(RSIPythonAdmissionError):
        parse_rsi_python_admission_record(wire)


@pytest.mark.parametrize("nested", ["root", "admission_anchor", "handoff_file_pin"])
def test_record_parser_refuses_callback_mapping_without_invoking_it(tmp_path, nested):
    value = _setup(tmp_path)
    wire = _register(value).to_dict()

    class Trap(UserDict):
        def __iter__(self):
            pytest.fail("callback mapping iteration")

        def items(self):
            pytest.fail("callback mapping items")

    if nested == "root":
        wire = Trap(wire)
    else:
        wire[nested] = Trap(wire[nested])
    with pytest.raises(RSIPythonAdmissionError):
        parse_rsi_python_admission_record(wire)


def test_record_wire_bound_is_checked_before_parsing():
    with pytest.raises(RSIPythonAdmissionError, match="record_too_large"):
        parse_rsi_python_admission_record(b" " * (MAX_RSI_PYTHON_ADMISSION_BYTES + 1))


def test_record_parser_rejects_dict_subclass_before_callbacks():
    class Trap(dict):
        def __iter__(self):
            pytest.fail("subclass was iterated")

        def items(self):
            pytest.fail("subclass items were read")

    with pytest.raises(RSIPythonAdmissionError):
        parse_rsi_python_admission_record(Trap())


@pytest.mark.parametrize("resource", ["run", "episode"])
@pytest.mark.parametrize("entrypoint", ["register", "validate"])
@pytest.mark.parametrize("boundary", ["controller", "ledger"])
def test_malformed_current_payload_returns_fixed_error_without_side_effects(
    tmp_path, resource, entrypoint, boundary,
):
    value = _setup(tmp_path)
    record = _register(value)
    run_head = value.ledger.get_run(value.binding.run_id).record_sha256
    episode_head = value.ledger.get_episode(value.episode_id).record_sha256
    checkpoint_head = value.ledger.controller_checkpoint(value.binding.run_id)[0]
    logical_id = value.binding.run_id if resource == "run" else value.episode_id
    with sqlite3.connect(value.ledger.database) as connection:
        connection.execute(
            "UPDATE rsi_records SET payload=? WHERE logical_id=? AND revision="
            "(SELECT MAX(revision) FROM rsi_records WHERE logical_id=?)",
            ("{", logical_id, logical_id),
        )
    if boundary == "controller":
        operation = lambda: _register(value) if entrypoint == "register" else _validate(value, record)
        _assert_no_effect(value, operation, match="^rsi_python_admission_")
    elif entrypoint == "validate":
        _assert_no_effect(value, lambda: value.ledger.python_admission_record(
            value.binding.run_id, value.episode_id, value.journal.journal_id,
            expected_record_sha256=record.record_sha256,
        ), match="^rsi_python_admission_")
    else:
        with value.ledger.controller_lock(value.binding.run_id):
            _assert_no_effect(value, lambda: value.ledger.register_python_admission_record(
                record, expected_run_record_sha256=run_head,
                expected_checkpoint_sha256=checkpoint_head,
                expected_episode_record_sha256=episode_head,
            ), match="^rsi_python_admission_")


@pytest.mark.parametrize("resource", ["episode", "native-result"])
@pytest.mark.parametrize("status", ["completed", "failed", "unknown"])
@pytest.mark.parametrize("retained", [False, True], ids=["missing-record", "retained-record"])
def test_episode_and_native_terminal_states_never_backfill_late_record(
    tmp_path, resource, status, retained,
):
    value = _setup(tmp_path)
    record = _register(value) if retained else None
    if resource == "episode":
        head = value.ledger.get_episode(value.episode_id)
        running = PracticeEpisode.from_dict(head.payload)
        extra = ({"candidate_receipt_sha256": DIGEST, "execution_receipt_sha256": DIGEST,
                  "official_evaluation_receipt_sha256": DIGEST, "trace_digest": DIGEST}
                 if status == "completed" else {"terminal_reason": "fixture-terminal"})
        terminal = running.transition(status, **extra)
        value.ledger.append_episode_record(terminal, expected_record_sha256=head.record_sha256)
        assert value.ledger.get_episode(value.episode_id).state == status
        assert value.ledger.inspect_native_episode_claim(value.request, plan_sha256=value.plan.plan_sha256).status == "started"
    else:
        result = SolverResult(
            episode_id=value.episode_id, request_sha256=value.request.digest(), status=status,
            candidate_receipt_sha256=DIGEST if status == "completed" else None,
            execution_receipt_sha256=DIGEST if status == "completed" else None,
            official_evaluation_receipt_sha256=DIGEST if status == "completed" else None,
            trace_digest=DIGEST, terminal_reason="fixture-terminal",
        )
        claim = value.ledger.publish_native_episode_result(
            value.request, plan_sha256=value.plan.plan_sha256, result=result,
            expected_claim=value.claim,
        )
        assert claim.status == status
        assert value.ledger.get_episode(value.episode_id).state == "running"
    # Neither a run-level nor a checkpoint-level terminal shortcut can explain
    # this refusal.  The legitimate terminal state is confined to the attempt.
    assert value.ledger.get_run(value.binding.run_id).state == "running"
    assert value.ledger.controller_checkpoint(value.binding.run_id)[1]["status"] == "running"
    if not retained:
        _assert_no_effect(value, lambda: _register(value), match="^rsi_python_admission_")
    else:
        rows, files = _rows(value), _files(value)
        assert _validate(value, record) == record
        assert _register(value) == record
        assert _rows(value) == rows
        assert _files(value) == files
    assert value.gateway.calls == 1
