"""Independent controller boundary tests; staged inert bytes are never launched."""

from __future__ import annotations

import hashlib
import sqlite3
from copy import deepcopy
from dataclasses import replace

import pytest
from test_producer_python_runtime import _inventory
from test_rsi_producer_gateway import _fixture

from lunar_evolution import RSILearningController, RSILearningError, fixture_solver_gateway
from lunar_evolution.producer_launcher import build_producer_launch_attestation
from lunar_evolution.rsi_producer_launch import (
    PythonProducerEpisodeStager,
    PythonProducerEpisodeStagingConfig,
)
from lunar_evolution.rsi_store import RSILedger


class ObservedAttestations:
    """Explicit fixture authority, with a stable config separate from observations."""

    def __init__(self, ledger, *, failure=False):
        self.ledger = ledger
        self.failure = failure
        self.observations = []

    def rsi_fingerprint_config(self):
        return {"fixture": "controller-staging-v1", "failure": self.failure}

    def __call__(self, intent):
        checkpoint = self.ledger.controller_checkpoint(intent.run_id)
        assert checkpoint is not None
        state = checkpoint[1]
        episode_id = state["current_episode_id"]
        assert episode_id in state["intents"]
        assert state["producer_episode_staging"][episode_id]["state"] == "preparing"
        assert self.ledger.get_episode(episode_id) is None
        self.observations.append((intent, checkpoint))
        if self.failure:
            raise RuntimeError("fixture staged-input interruption")
        nonce = "fixture-" + hashlib.sha256(intent.launch_id.encode()).hexdigest()[:32]
        return build_producer_launch_attestation(intent, nonce)


class ConflictingCheckpointAttestations(ObservedAttestations):
    def rsi_fingerprint_config(self):
        return {"fixture": "controller-staging-conflicting-checkpoint-v1"}

    def __call__(self, intent):
        attestation = super().__call__(intent)
        head, state = self.ledger.controller_checkpoint(intent.run_id)
        conflicting = deepcopy(state)
        conflicting["external_observation"] = "retained conflict fixture"
        self.ledger.write_controller_checkpoint(intent.run_id, conflicting, expected_sha256=head)
        self.conflicting_head = self.ledger.controller_checkpoint(intent.run_id)
        return attestation


def _controller(value, supplier, *, ledger=None, config=None):
    configured = config or PythonProducerEpisodeStagingConfig(
        workspace=value.root, root_sidecar=value.sidecar,
        artifact=value.native.artifact, attestation_supplier=supplier,
    )
    return RSILearningController(
        fixture_solver_gateway(value.request.solver_id), ledger=ledger or value.ledger,
        producer_sidecar=value.sidecar, producer_workspace=value.root,
        producer_stager=PythonProducerEpisodeStager(configured),
    )


def _run(controller, value):
    return controller.run_drs(
        run_id=value.binding.run_id,
        contract_sha256=value.request.contract_sha256,
        evaluator_sha256=value.request.evaluator_sha256,
        environment_sha256=value.request.environment_sha256,
        solver_id=value.request.solver_id,
        max_practice_rounds=0, max_target_attempts=1,
        budget=dict(value.request.budget),
    )


def _assert_no_dispatch(value, state):
    episode_id = state["current_episode_id"]
    assert value.ledger.get_episode(episode_id) is None
    assert value.ledger.episode_result(episode_id) is None
    with sqlite3.connect(value.ledger.database) as connection:
        assert connection.execute(
            "SELECT episode_id FROM rsi_native_episode_claims WHERE episode_id = ?",
            (episode_id,),
        ).fetchall() == []
    for path in value.root.rglob("*"):
        assert path.name not in {
            "process-registration.json", "attestation-consumption.json",
            "journal.prepared.json", "python-producer-admission-handoff.json",
        }


def test_ready_is_durable_before_any_episode_or_claim_and_resume_is_read_only(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    supplier = ObservedAttestations(value.ledger)
    controller = _controller(value, supplier)
    with pytest.raises(RSILearningError, match="dispatch_not_accepted"):
        _run(controller, value)
    checkpoint = value.ledger.controller_checkpoint(value.binding.run_id)
    state = checkpoint[1]
    original = value.ledger.history(value.binding.run_id)[0]
    assert len(supplier.observations) == 1
    assert state["producer_checkpoint_binding"] == original.payload["producer_checkpoint_binding"]
    assert state["producer_episode_staging"][state["current_episode_id"]]["state"] == "ready"
    _assert_no_dispatch(value, state)
    before = _inventory(value.root)
    run_history = value.ledger.history(value.binding.run_id)
    checkpoint_history = value.ledger.controller_checkpoint_history(value.binding.run_id)
    reopened = RSILedger(value.ledger.database)
    restarted = _controller(value, supplier, ledger=reopened)
    with pytest.raises(RSILearningError, match="dispatch_not_accepted"):
        restarted.resume(value.binding.run_id)
    assert len(supplier.observations) == 1
    assert _inventory(value.root) == before
    assert reopened.history(value.binding.run_id) == run_history
    assert reopened.controller_checkpoint_history(value.binding.run_id) == checkpoint_history
    assert reopened.controller_checkpoint(value.binding.run_id)[1]["budget_state"] == state["budget_state"]


def test_staging_failure_preserves_original_reservation_and_never_calls_supplier_again(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    supplier = ObservedAttestations(value.ledger, failure=True)
    result = _run(_controller(value, supplier), value)
    assert result.status == "unknown"
    state = value.ledger.controller_checkpoint(value.binding.run_id)[1]
    assert len(supplier.observations) == 1
    assert state["producer_episode_staging"][state["current_episode_id"]]["state"] == "unknown"
    assert state["budget_state"]["consumed"]["solver_invocations"] == 1
    _assert_no_dispatch(value, state)
    before = _inventory(value.root)
    checkpoint_history = value.ledger.controller_checkpoint_history(value.binding.run_id)
    with pytest.raises(RSILearningError, match="unknown_reconcile_required"):
        _controller(value, supplier, ledger=RSILedger(value.ledger.database)).resume(value.binding.run_id)
    assert len(supplier.observations) == 1
    assert _inventory(value.root) == before
    assert value.ledger.controller_checkpoint_history(value.binding.run_id) == checkpoint_history


def test_ready_checkpoint_interruption_cannot_adopt_sidecar_from_disk(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    supplier = ObservedAttestations(value.ledger)
    controller = _controller(value, supplier)
    original_write = value.ledger.write_controller_checkpoint

    def interrupt_ready(run_id, state, **kwargs):
        entries = state.get("producer_episode_staging", {})
        if any(entry["state"] == "ready" for entry in entries.values()):
            raise RuntimeError("fixture ready CAS interruption")
        return original_write(run_id, state, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(value.ledger, "write_controller_checkpoint", interrupt_ready)
        try:
            result = _run(controller, value)
        except RSILearningError:
            pass
        else:
            assert result.status == "unknown"
    state = value.ledger.controller_checkpoint(value.binding.run_id)[1]
    entry = state["producer_episode_staging"][state["current_episode_id"]]
    assert entry["state"] in {"preparing", "unknown"}
    assert len(supplier.observations) == 1
    sidecars = list(value.root.rglob("python-producer-binding.json"))
    assert len(sidecars) == 2  # Root plus the unacknowledged create-only child.
    _assert_no_dispatch(value, state)
    before = _inventory(value.root)
    with pytest.raises(RSILearningError, match="unknown_reconcile_required"):
        _controller(value, supplier, ledger=RSILedger(value.ledger.database)).resume(value.binding.run_id)
    assert len(supplier.observations) == 1
    assert _inventory(value.root) == before


def test_original_run_cannot_gain_staging_policy_on_resume(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    plain = RSILearningController(
        fixture_solver_gateway(value.request.solver_id), ledger=value.ledger,
        producer_sidecar=value.sidecar, producer_workspace=value.root,
    )
    assert _run(plain, value).status == "completed"
    before = _inventory(value.root)
    history = value.ledger.history(value.binding.run_id)
    supplier = ObservedAttestations(value.ledger)
    with pytest.raises(RSILearningError):
        _controller(value, supplier).resume(value.binding.run_id)
    assert supplier.observations == []
    assert value.ledger.history(value.binding.run_id) == history
    assert _inventory(value.root) == before


def test_brs_staging_opt_in_refuses_before_creating_a_run(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    supplier = ObservedAttestations(value.ledger)
    before = _inventory(value.root)
    with pytest.raises(RSILearningError):
        _controller(value, supplier).run_brs(
            run_id=value.binding.run_id,
            contract_sha256=value.request.contract_sha256,
            evaluator_sha256=value.request.evaluator_sha256,
            environment_sha256=value.request.environment_sha256,
            solver_id=value.request.solver_id,
            practices=(),
            budget=dict(value.request.budget),
        )
    assert value.ledger.get_run(value.binding.run_id) is None
    assert supplier.observations == []
    assert _inventory(value.root) == before


def test_reconfigured_policy_cannot_restage_a_ready_episode(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    supplier = ObservedAttestations(value.ledger)
    configured = PythonProducerEpisodeStagingConfig(
        workspace=value.root, root_sidecar=value.sidecar,
        artifact=value.native.artifact, attestation_supplier=supplier,
    )
    with pytest.raises(RSILearningError, match="dispatch_not_accepted"):
        _run(_controller(value, supplier, config=configured), value)
    before = _inventory(value.root)
    checkpoint_history = value.ledger.controller_checkpoint_history(value.binding.run_id)
    changed = replace(configured, max_episodes=configured.max_episodes - 1)
    with pytest.raises(RSILearningError):
        _controller(value, supplier, config=changed).resume(value.binding.run_id)
    assert len(supplier.observations) == 1
    assert value.ledger.controller_checkpoint_history(value.binding.run_id) == checkpoint_history
    assert _inventory(value.root) == before


def test_unrelated_checkpoint_change_is_not_adopted_for_unknown_settlement(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    supplier = ConflictingCheckpointAttestations(value.ledger)
    with pytest.raises(RSILearningError, match="checkpoint_conflict"):
        _run(_controller(value, supplier), value)
    assert len(supplier.observations) == 1
    assert value.ledger.controller_checkpoint(value.binding.run_id) == supplier.conflicting_head
    state = supplier.conflicting_head[1]
    assert state["producer_episode_staging"][state["current_episode_id"]]["state"] == "preparing"
    assert value.ledger.get_run(value.binding.run_id).state == "running"
    assert state["budget_state"]["consumed"]["solver_invocations"] == 1
    _assert_no_dispatch(value, state)


def test_failed_unknown_checkpoint_write_keeps_original_preparing_obligation(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    supplier = ObservedAttestations(value.ledger, failure=True)
    original_write = value.ledger.write_controller_checkpoint

    def refuse_unknown(run_id, state, **kwargs):
        if any(entry["state"] == "unknown" for entry in state.get("producer_episode_staging", {}).values()):
            raise OSError("fixture unknown checkpoint write failure")
        return original_write(run_id, state, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(value.ledger, "write_controller_checkpoint", refuse_unknown)
        with pytest.raises(RSILearningError):
            _run(_controller(value, supplier), value)
    state = value.ledger.controller_checkpoint(value.binding.run_id)[1]
    assert state["producer_episode_staging"][state["current_episode_id"]]["state"] == "preparing"
    assert value.ledger.get_run(value.binding.run_id).state == "running"
    assert state["budget_state"]["consumed"]["solver_invocations"] == 1
    assert len(supplier.observations) == 1
    before = _inventory(value.root)
    history = value.ledger.controller_checkpoint_history(value.binding.run_id)
    with pytest.raises(RSILearningError, match="unknown_reconcile_required"):
        _controller(value, supplier, ledger=RSILedger(value.ledger.database)).resume(value.binding.run_id)
    assert len(supplier.observations) == 1
    assert _inventory(value.root) == before
    assert value.ledger.controller_checkpoint_history(value.binding.run_id) == history
