"""Original mode/history policy tests; no producer process is dispatched."""

from __future__ import annotations

import tempfile
from copy import deepcopy
from pathlib import Path

import pytest
from test_producer_python_runtime import _inventory
from test_rsi_producer_gateway import _fixture as _gateway_fixture
from test_rsi_producer_staging_controller import ObservedAttestations, _run

from lunar_evolution import RSILearningController, RSILearningError, fixture_solver_gateway
from lunar_evolution.rsi_producer_launch import (
    PythonProducerEpisodeStager,
    PythonProducerEpisodeStagingConfig,
)
from lunar_evolution.rsi_publication_lineage import multi_episode_publication_policy


class _OwnerLoss(BaseException):
    pass


def _fixture(tmp_path, monkeypatch):
    """Use a short real parent for the unchanged 32 KiB binding wire cap."""
    candidate = tmp_path
    if len(str(candidate)) > 96:
        parent = next(
            str(path)
            for path in (Path("/private/tmp"), Path("/var/tmp"), Path("/tmp"))
            if path.is_dir() and not path.is_symlink()
        )
        candidate = Path(tempfile.mkdtemp(prefix="lce-mep-policy-", dir=parent))
    return _gateway_fixture(candidate, monkeypatch)


def _controller(value, *, publication=False, execution=True):
    supplier = ObservedAttestations(value.ledger)
    stager = PythonProducerEpisodeStager(PythonProducerEpisodeStagingConfig(
        workspace=value.root, root_sidecar=value.sidecar,
        artifact=value.native.artifact, attestation_supplier=supplier,
    ))
    controller = RSILearningController(
        value.gateway, ledger=value.ledger,
        producer_sidecar=value.sidecar, producer_workspace=value.root,
        producer_stager=stager, producer_child_execution=execution,
        producer_multi_episode_publication=publication,
    )
    return controller, supplier


def _interrupted_run(controller, value, monkeypatch):
    def interrupted(*_args, **_kwargs):
        raise _OwnerLoss("stop before staging or native dispatch")

    monkeypatch.setattr(controller, "_execute_intent", interrupted)
    with pytest.raises(_OwnerLoss):
        _run(controller, value)
    return value.ledger.get_run(value.binding.run_id)


@pytest.mark.parametrize("flag", [None, 0, 1, "true", [], {}])
def test_nonboolean_publication_mode_refuses_without_creating_a_run(tmp_path, monkeypatch, flag):
    value = _fixture(tmp_path, monkeypatch)
    before = _inventory(value.root)
    with pytest.raises(RSILearningError, match="multi_episode_configuration_invalid"):
        _controller(value, publication=flag)
    assert value.ledger.get_run(value.binding.run_id) is None
    assert _inventory(value.root) == before


def test_publication_mode_requires_original_child_execution(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    with pytest.raises(RSILearningError, match="multi_episode_configuration_invalid"):
        _controller(value, publication=True, execution=False)
    assert value.ledger.get_run(value.binding.run_id) is None


def test_default_and_legacy_subclass_omit_new_wire_fields(tmp_path, monkeypatch):
    class LegacyController(RSILearningController):
        pass

    legacy = LegacyController(fixture_solver_gateway("openevolve"))
    assert multi_episode_publication_policy(legacy) is None
    value = _fixture(tmp_path, monkeypatch)
    controller, supplier = _controller(value)
    record = _interrupted_run(controller, value, monkeypatch)
    assert "producer_multi_episode_publication" not in record.payload
    for _head, state in value.ledger.controller_checkpoint_history(value.binding.run_id):
        assert "producer_multi_episode_publication" not in state
        assert "producer_multi_episode_publication_policy" not in state
    assert supplier.observations == []


def test_original_run_and_all_checkpoints_retain_policy_without_launch(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    controller, supplier = _controller(value, publication=True)
    record = _interrupted_run(controller, value, monkeypatch)
    expected = multi_episode_publication_policy(controller)
    assert expected["mode"] == "drs" and expected["production_admission"] is False
    for state in [record.payload, *[state for _head, state in
                  value.ledger.controller_checkpoint_history(value.binding.run_id)]]:
        assert state["producer_multi_episode_publication"] is True
        assert state["producer_multi_episode_publication_policy"] == expected
    assert supplier.observations == []
    assert value.ledger.get_episode("run-1-target-0") is None


@pytest.mark.parametrize("original", [False, True])
def test_addition_or_removal_on_restart_refuses_readonly(tmp_path, monkeypatch, original):
    value = _fixture(tmp_path, monkeypatch)
    controller, _supplier = _controller(value, publication=original)
    record = _interrupted_run(controller, value, monkeypatch)
    changed, _supplier = _controller(value, publication=not original)
    before = _inventory(value.root)
    history = value.ledger.controller_checkpoint_history(value.binding.run_id)
    with pytest.raises(RSILearningError, match="multi_episode_original_mode_mismatch"):
        changed._validate_producer_staging(record, history[-1][1])
    with pytest.raises(RSILearningError):
        changed.resume(value.binding.run_id)
    assert value.ledger.controller_checkpoint_history(value.binding.run_id) == history
    assert _inventory(value.root) == before


@pytest.mark.parametrize("flag", [False, 1, None])
def test_in_process_mode_drift_refuses_before_evidence_io(tmp_path, monkeypatch, flag):
    value = _fixture(tmp_path, monkeypatch)
    controller, _supplier = _controller(value, publication=True)
    controller.producer_multi_episode_publication = flag
    before = _inventory(value.root)
    with pytest.raises(RSILearningError, match="multi_episode_configuration_drift"):
        multi_episode_publication_policy(controller)
    assert _inventory(value.root) == before


def test_intermediate_bad_policy_cannot_be_hidden_by_corrected_head(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    controller, _supplier = _controller(value, publication=True)
    record = _interrupted_run(controller, value, monkeypatch)
    head, state = value.ledger.controller_checkpoint(value.binding.run_id)
    bad = deepcopy(state)
    bad["producer_multi_episode_publication_policy"]["max_batches"] = 1
    with value.ledger.controller_lock(value.binding.run_id):
        bad_head = value.ledger.write_controller_checkpoint(value.binding.run_id, bad, expected_sha256=head)
        value.ledger.write_controller_checkpoint(value.binding.run_id, state, expected_sha256=bad_head)
    history = value.ledger.controller_checkpoint_history(value.binding.run_id)
    before = _inventory(value.root)
    with pytest.raises(RSILearningError, match="multi_episode_original_mode_mismatch"):
        controller._validate_producer_staging(record, state)
    assert value.ledger.controller_checkpoint_history(value.binding.run_id) == history
    assert _inventory(value.root) == before


def test_brs_still_refuses_before_run_creation(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    controller, supplier = _controller(value, publication=True)
    with pytest.raises(RSILearningError):
        controller.run_brs(
            run_id=value.binding.run_id, contract_sha256=value.request.contract_sha256,
            evaluator_sha256=value.request.evaluator_sha256,
            environment_sha256=value.request.environment_sha256,
            solver_id=value.request.solver_id, practices=[],
            budget=dict(value.request.budget),
        )
    assert value.ledger.get_run(value.binding.run_id) is None
    assert supplier.observations == []
