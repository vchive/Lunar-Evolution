"""Original-mode and reservation gates over inert bytes; no native execution."""

from __future__ import annotations

import socket
import subprocess
from copy import deepcopy

import pytest
from test_producer_python_runtime import _inventory
from test_rsi_multi_episode_policy import _interrupted_run
from test_rsi_producer_gateway import _fixture
from test_rsi_producer_staging_controller import ObservedAttestations

from lunar_evolution import RSILearningController, RSILearningError, fixture_solver_gateway
from lunar_evolution.rsi_budget import RSIRunBudget
from lunar_evolution.rsi_native_rejection import (
    NATIVE_RSI_REJECTION_PROVENANCE_NAME,
    NativeRSIRejectionFilePin,
)
from lunar_evolution.rsi_producer_launch import (
    PythonProducerEpisodeStager,
    PythonProducerEpisodeStagingConfig,
)
from lunar_evolution.rsi_publication_lineage import multi_episode_publication_policy


@pytest.fixture(autouse=True)
def no_execution(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("policy/reservation fixture attempted execution or network")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def _controller(value, *, rejection):
    supplier = ObservedAttestations(value.ledger)
    stager = PythonProducerEpisodeStager(PythonProducerEpisodeStagingConfig(
        workspace=value.root, root_sidecar=value.sidecar,
        artifact=value.native.artifact, attestation_supplier=supplier,
    ))
    controller = RSILearningController(
        value.gateway, ledger=value.ledger, producer_sidecar=value.sidecar,
        producer_workspace=value.root, producer_stager=stager,
        producer_child_execution=True, producer_multi_episode_publication=True,
        producer_known_rejection=rejection,
    )
    return controller, supplier


def _pin():
    # A strict inert pin for checkpoint-delta tests, never used as native proof.
    return NativeRSIRejectionFilePin(
        NATIVE_RSI_REJECTION_PROVENANCE_NAME, "c" * 64, 10, 1, 2, 1, 3,
    )


@pytest.mark.parametrize("flag", [None, 0, 1, "true", [], {}])
def test_invalid_rejection_flag_refuses_before_gateway_or_ledger_access(flag):
    with pytest.raises(RSILearningError, match="known_rejection_configuration_invalid"):
        RSILearningController(object(), producer_known_rejection=flag)


@pytest.mark.parametrize("execution,publication", [(False, False), (False, True), (True, False)])
def test_rejection_requires_both_original_child_modes(execution, publication):
    with pytest.raises(RSILearningError, match="known_rejection_configuration_invalid"):
        RSILearningController(object(), producer_known_rejection=True,
                              producer_child_execution=execution,
                              producer_multi_episode_publication=publication)


@pytest.mark.parametrize("rejection", [False, True])
def test_fresh_run_and_every_checkpoint_retain_original_mode(tmp_path, monkeypatch, rejection):
    value = _fixture(tmp_path, monkeypatch)
    controller, supplier = _controller(value, rejection=rejection)
    record = _interrupted_run(controller, value, monkeypatch)
    policy = multi_episode_publication_policy(controller)
    assert policy["protocol"] == "lunar-rsi-multi-episode-publication-v" + ("2" if rejection else "1")
    states = [record.payload, *[state for _, state in
              value.ledger.controller_checkpoint_history(value.binding.run_id)]]
    for state in states:
        if rejection:
            assert state["producer_known_rejection"] is True
        else:
            assert "producer_known_rejection" not in state
        assert state["producer_multi_episode_publication_policy"] == policy
    assert supplier.observations == []
    assert value.ledger.get_episode("run-1-target-0") is None


@pytest.mark.parametrize("original", [False, True])
def test_restart_cannot_add_or_remove_rejection_mode(tmp_path, monkeypatch, original):
    value = _fixture(tmp_path, monkeypatch)
    controller, _ = _controller(value, rejection=original)
    record = _interrupted_run(controller, value, monkeypatch)
    changed, _ = _controller(value, rejection=not original)
    history = value.ledger.controller_checkpoint_history(value.binding.run_id)
    before = _inventory(value.root)
    with pytest.raises(RSILearningError, match="known_rejection_original_mode_mismatch"):
        changed._validate_producer_staging(record, history[-1][1])
    assert value.ledger.controller_checkpoint_history(value.binding.run_id) == history
    assert _inventory(value.root) == before


@pytest.mark.parametrize("field,value", [
    ("producer_known_rejection", False), ("producer_known_rejection", 1),
    ("producer_child_execution", False), ("producer_multi_episode_publication", False),
])
def test_live_configuration_drift_refuses_before_resume_lock(tmp_path, monkeypatch, field, value):
    prepared = _fixture(tmp_path, monkeypatch)
    controller, _ = _controller(prepared, rejection=True)
    setattr(controller, field, value)
    monkeypatch.setattr(prepared.ledger, "controller_lock",
                        lambda *_: pytest.fail("configuration drift reached ledger lock"))
    with pytest.raises(RSILearningError, match="known_rejection_configuration_drift"):
        controller.resume("run-1")


def test_default_controller_cannot_register_rejection_before_ledger_access():
    controller = RSILearningController(fixture_solver_gateway("openevolve"))
    with pytest.raises(RSILearningError, match="rejection_opt_in_required"):
        controller.reconcile_native_rejection(
            "run-1", "episode", expected_checkpoint_sha256="a" * 64,
            expected_episode_record_sha256="b" * 64, expected_claim_sha256="c" * 64,
            expected_provenance_file_pin=_pin(),
        )


def test_brs_rejection_refuses_without_run_or_supplier(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    controller, supplier = _controller(value, rejection=True)
    with pytest.raises(RSILearningError, match="known_rejection_drs_required"):
        controller.run_brs(
            run_id=value.binding.run_id, contract_sha256=value.request.contract_sha256,
            evaluator_sha256=value.request.evaluator_sha256,
            environment_sha256=value.request.environment_sha256,
            solver_id=value.request.solver_id, practices=[], budget=dict(value.request.budget),
        )
    assert value.ledger.get_run(value.binding.run_id) is None
    assert supplier.observations == []


def _reservation_case(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    controller, _ = _controller(value, rejection=True)
    _interrupted_run(controller, value, monkeypatch)
    old, state = value.ledger.controller_checkpoint(value.binding.run_id)
    budget = RSIRunBudget.load(state["budget_state"])
    budget.reserve_unknown_reconcile_evidence()
    state["budget_state"] = budget.to_dict()
    episode = state["current_episode_id"]
    state["native_rejection_reconciliation_reservations"] = {episode: {
        "checkpoint_sha256": old, "episode_record_sha256": "a" * 64,
        "claim_sha256": "b" * 64, "provenance_file_pin": _pin().to_dict(),
    }}
    return value, controller, episode, old, state


def _validate(value, controller, episode, old, current):
    controller._validate_native_rejection_reconciliation_checkpoint(
        value.binding.run_id, episode, expected_checkpoint_sha256=old,
        current_checkpoint_sha256=current,
    )


def test_one_reserved_delta_is_readonly_repeatable_and_requires_held_lock(tmp_path, monkeypatch):
    value, controller, episode, old, state = _reservation_case(tmp_path, monkeypatch)
    with value.ledger.controller_lock(value.binding.run_id):
        current = value.ledger.write_controller_checkpoint(value.binding.run_id, state, expected_sha256=old)
        before = value.ledger.controller_checkpoint_history(value.binding.run_id)
        _validate(value, controller, episode, old, current)
        _validate(value, controller, episode, old, current)
        assert value.ledger.controller_checkpoint_history(value.binding.run_id) == before
    with pytest.raises(RSILearningError, match="controller_lock_required"):
        _validate(value, controller, episode, old, current)


@pytest.mark.parametrize("drift", ["phase", "double-budget", "extra-reservation", "other-cache", "bad-pin", "missing-reservation"])
def test_reservation_does_not_authorize_other_checkpoint_changes(tmp_path, monkeypatch, drift):
    value, controller, episode, old, state = _reservation_case(tmp_path, monkeypatch)
    if drift == "phase":
        state["phase"] = "foreign-progress"
    elif drift == "double-budget":
        state["budget_state"]["consumed"]["unknown_retries"] += 1
    elif drift == "extra-reservation":
        state["native_rejection_reconciliation_reservations"]["foreign"] = deepcopy(
            state["native_rejection_reconciliation_reservations"][episode])
    elif drift == "other-cache":
        state["executions"]["foreign"] = {}
    elif drift == "bad-pin":
        state["native_rejection_reconciliation_reservations"][episode]["provenance_file_pin"]["mode"] = 0o600
    else:
        del state["native_rejection_reconciliation_reservations"]
    with value.ledger.controller_lock(value.binding.run_id):
        current = value.ledger.write_controller_checkpoint(value.binding.run_id, state, expected_sha256=old)
        before = value.ledger.controller_checkpoint_history(value.binding.run_id)
        with pytest.raises(ValueError):
            _validate(value, controller, episode, old, current)
        assert value.ledger.controller_checkpoint_history(value.binding.run_id) == before
