from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from test_python_producer_binding import _fixture

from lunar_evolution import (
    RSILearningController,
    RSILearningError,
    RSILedger,
    fixture_solver_gateway,
)
from lunar_evolution.python_producer_binding import build_python_producer_binding
from lunar_evolution.python_producer_binding_store import persist_python_producer_binding

DIGEST = "a" * 64


def _sidecar(tmp_path: Path):
    manifest, tree, intent, attestation, budget = _fixture(tmp_path)
    binding = build_python_producer_binding(
        runtime_manifest=manifest, runtime_tree=tree, intent=intent,
        attestation=attestation, deadline_unix=4102444800.0, budget=budget,
    )
    batch = tmp_path / "evolution" / "producer-batches" / binding.intent.journal_id
    batch.mkdir(parents=True)
    batch.chmod(0o700)
    return binding, persist_python_producer_binding(tmp_path, binding=binding)


def test_controller_checkpoint_retains_and_revalidates_producer_pin(tmp_path: Path) -> None:
    binding, sidecar = _sidecar(tmp_path)
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    controller = RSILearningController(
        fixture_solver_gateway("mock"), ledger=ledger,
        producer_sidecar=sidecar, producer_workspace=tmp_path,
    )
    result = controller.run_drs(
        run_id=binding.run_id, contract_sha256=DIGEST, evaluator_sha256=DIGEST,
        environment_sha256=DIGEST, solver_id="mock", max_practice_rounds=0,
    )
    assert result.status == "completed"
    checkpoint = ledger.controller_checkpoint(binding.run_id)
    assert checkpoint is not None
    assert checkpoint[1]["producer_checkpoint_binding"]["sidecar_pin"]["file_inode"] == sidecar.file_inode

    resumed = RSILearningController(
        fixture_solver_gateway("mock"), ledger=ledger,
        producer_sidecar=sidecar, producer_workspace=tmp_path,
    ).resume(binding.run_id)
    assert resumed.status == "completed"


def test_controller_resume_rejects_retained_pin_drift(tmp_path: Path) -> None:
    binding, sidecar = _sidecar(tmp_path)
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    RSILearningController(
        fixture_solver_gateway("mock"), ledger=ledger,
        producer_sidecar=sidecar, producer_workspace=tmp_path,
    ).run_drs(
        run_id=binding.run_id, contract_sha256=DIGEST, evaluator_sha256=DIGEST,
        environment_sha256=DIGEST, solver_id="mock", max_practice_rounds=0,
    )
    drifted = replace(sidecar, file_inode=sidecar.file_inode + 1)
    with pytest.raises(RSILearningError, match="producer_checkpoint"):
        RSILearningController(
            fixture_solver_gateway("mock"), ledger=ledger,
            producer_sidecar=drifted, producer_workspace=tmp_path,
        ).resume(binding.run_id)


def test_controller_without_producer_pin_keeps_existing_checkpoint_shape(tmp_path: Path) -> None:
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    result = RSILearningController(fixture_solver_gateway("mock"), ledger=ledger).run_drs(
        run_id="ordinary-rsi", contract_sha256=DIGEST, evaluator_sha256=DIGEST,
        environment_sha256=DIGEST, solver_id="mock", max_practice_rounds=0,
    )
    assert result.status == "completed"
    state = ledger.controller_checkpoint("ordinary-rsi")[1]
    assert "producer_checkpoint_binding" not in state


def test_fresh_producer_run_validates_sidecar_before_controller_checkpoint(tmp_path: Path) -> None:
    binding, sidecar = _sidecar(tmp_path)
    sidecar_path = tmp_path / "evolution" / "producer-batches" / binding.intent.journal_id / "python-producer-binding.json"
    sidecar_path.unlink()
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    controller = RSILearningController(
        fixture_solver_gateway("mock"), ledger=ledger,
        producer_sidecar=sidecar, producer_workspace=tmp_path,
    )

    with pytest.raises(RSILearningError, match="producer_checkpoint"):
        controller.run_drs(
            run_id=binding.run_id, contract_sha256=DIGEST, evaluator_sha256=DIGEST,
            environment_sha256=DIGEST, solver_id="mock", max_practice_rounds=0,
        )

    assert ledger.get_run(binding.run_id) is None
    assert ledger.controller_checkpoint(binding.run_id) is None
    with pytest.raises(RSILearningError, match="rsi_run_missing"):
        RSILearningController(fixture_solver_gateway("mock"), ledger=ledger).resume(binding.run_id)


@pytest.mark.parametrize("entrypoint", ["resume", "run_drs"])
def test_run_record_retains_producer_pin_if_sidecar_disappears_before_checkpoint(
    tmp_path: Path, entrypoint: str,
) -> None:
    binding, sidecar = _sidecar(tmp_path)
    sidecar_path = tmp_path / "evolution" / "producer-batches" / binding.intent.journal_id / "python-producer-binding.json"
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    controller = RSILearningController(
        fixture_solver_gateway("mock"), ledger=ledger,
        producer_sidecar=sidecar, producer_workspace=tmp_path,
    )
    original_validate = controller._validate_producer_checkpoint
    validations = 0

    def remove_after_preflight(run_id, state):
        nonlocal validations
        original_validate(run_id, state)
        validations += 1
        if validations == 1:
            sidecar_path.unlink()

    controller._validate_producer_checkpoint = remove_after_preflight
    with pytest.raises(RSILearningError, match="producer_checkpoint"):
        controller.run_drs(
            run_id=binding.run_id, contract_sha256=DIGEST, evaluator_sha256=DIGEST,
            environment_sha256=DIGEST, solver_id="mock", max_practice_rounds=0,
        )

    run = ledger.get_run(binding.run_id)
    assert run is not None and run.state == "running"
    assert run.payload["producer_checkpoint_binding"]["run_id"] == binding.run_id
    assert ledger.controller_checkpoint(binding.run_id) is None
    assert ledger.episode_ids_for_run(binding.run_id) == ()

    replacement = RSILearningController(fixture_solver_gateway("mock"), ledger=ledger)
    with pytest.raises(RSILearningError, match="rsi_producer_checkpoint_sidecar_missing"):
        if entrypoint == "resume":
            replacement.resume(binding.run_id)
        else:
            replacement.run_drs(
                run_id=binding.run_id, contract_sha256=DIGEST, evaluator_sha256=DIGEST,
                environment_sha256=DIGEST, solver_id="mock", max_practice_rounds=0,
            )
    assert ledger.controller_checkpoint(binding.run_id) is None
    assert ledger.episode_ids_for_run(binding.run_id) == ()


def test_producer_run_recovers_missing_first_checkpoint_with_valid_sidecar(tmp_path: Path) -> None:
    binding, sidecar = _sidecar(tmp_path)
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    controller = RSILearningController(
        fixture_solver_gateway("mock"), ledger=ledger,
        producer_sidecar=sidecar, producer_workspace=tmp_path,
    )

    def interrupt_before_initial_checkpoint(_record, _state):
        raise RSILearningError("fixture_initial_checkpoint_interrupt")

    controller._save_flow = interrupt_before_initial_checkpoint
    with pytest.raises(RSILearningError, match="fixture_initial_checkpoint_interrupt"):
        controller.run_drs(
            run_id=binding.run_id, contract_sha256=DIGEST, evaluator_sha256=DIGEST,
            environment_sha256=DIGEST, solver_id="mock", max_practice_rounds=0,
        )
    assert ledger.controller_checkpoint(binding.run_id) is None
    assert ledger.episode_ids_for_run(binding.run_id) == ()
    original = ledger.get_run(binding.run_id)
    assert original is not None

    recovered = RSILearningController(
        fixture_solver_gateway("mock"), ledger=ledger,
        producer_sidecar=sidecar, producer_workspace=tmp_path,
    ).resume(binding.run_id)
    assert recovered.status == "completed"
    current = ledger.get_run(binding.run_id)
    checkpoint = ledger.controller_checkpoint(binding.run_id)[1]
    assert current.request_sha256 == original.request_sha256
    for key in ("producer_checkpoint_binding", "fingerprints", "budget"):
        assert current.payload[key] == original.payload[key]
    assert current.payload["budget_state"]["planned"] == original.payload["budget_state"]["planned"]
    assert checkpoint["producer_checkpoint_binding"] == original.payload["producer_checkpoint_binding"]
    assert checkpoint["budget_state"]["planned"] == original.payload["budget_state"]["planned"]
    assert len(recovered.target_attempts) == 1


@pytest.mark.parametrize("completed", [False, True])
@pytest.mark.parametrize("mutation", ["drop", "replace"])
def test_resume_rejects_checkpoint_that_changes_run_producer_binding(
    tmp_path: Path, completed: bool, mutation: str,
) -> None:
    binding, sidecar = _sidecar(tmp_path)
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    controller = RSILearningController(
        fixture_solver_gateway("mock"), ledger=ledger,
        producer_sidecar=sidecar, producer_workspace=tmp_path,
    )
    if not completed:
        original_save = controller._save_flow

        def interrupt_after_initial_checkpoint(record, state):
            original_save(record, state)
            raise RSILearningError("fixture_initial_checkpoint_interrupt")

        controller._save_flow = interrupt_after_initial_checkpoint

    def run():
        return controller.run_drs(
            run_id=binding.run_id, contract_sha256=DIGEST, evaluator_sha256=DIGEST,
            environment_sha256=DIGEST, solver_id="mock", max_practice_rounds=0,
        )

    if completed:
        assert run().status == "completed"
    else:
        with pytest.raises(RSILearningError, match="fixture_initial_checkpoint_interrupt"):
            run()
    checkpoint = ledger.controller_checkpoint(binding.run_id)
    assert checkpoint is not None
    corrupted = dict(checkpoint[1])
    if mutation == "drop":
        del corrupted["producer_checkpoint_binding"]
    else:
        corrupted["producer_checkpoint_binding"] = {"run_id": "unrelated-run"}
    with ledger.controller_lock(binding.run_id):
        ledger.write_controller_checkpoint(binding.run_id, corrupted, expected_sha256=checkpoint[0])

    with pytest.raises(RSILearningError, match="rsi_resume_checkpoint_corrupt"):
        RSILearningController(fixture_solver_gateway("mock"), ledger=ledger).resume(binding.run_id)


def test_unbound_run_cannot_acquire_producer_proof_during_reconstruction(tmp_path: Path) -> None:
    binding, sidecar = _sidecar(tmp_path)
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    controller = RSILearningController(fixture_solver_gateway("mock"), ledger=ledger)

    def interrupt_before_initial_checkpoint(_record, _state):
        raise RSILearningError("fixture_initial_checkpoint_interrupt")

    controller._save_flow = interrupt_before_initial_checkpoint
    with pytest.raises(RSILearningError, match="fixture_initial_checkpoint_interrupt"):
        controller.run_drs(
            run_id=binding.run_id, contract_sha256=DIGEST, evaluator_sha256=DIGEST,
            environment_sha256=DIGEST, solver_id="mock", max_practice_rounds=0,
        )
    original = ledger.get_run(binding.run_id)
    assert "producer_checkpoint_binding" not in original.payload

    with pytest.raises(RSILearningError, match="rsi_producer_checkpoint_missing"):
        RSILearningController(
            fixture_solver_gateway("mock"), ledger=ledger,
            producer_sidecar=sidecar, producer_workspace=tmp_path,
        ).resume(binding.run_id)
    assert ledger.get_run(binding.run_id) == original
    assert ledger.controller_checkpoint(binding.run_id) is None
    assert ledger.episode_ids_for_run(binding.run_id) == ()


@pytest.mark.parametrize("mutation", ["checkpoint_injection", "run_payload_drop"])
def test_resume_keeps_original_run_producer_identity(tmp_path: Path, mutation: str) -> None:
    binding, sidecar = _sidecar(tmp_path)
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    controller = RSILearningController(
        fixture_solver_gateway("mock"), ledger=ledger,
        **({"producer_sidecar": sidecar, "producer_workspace": tmp_path}
           if mutation == "run_payload_drop" else {}),
    )
    original_save = controller._save_flow

    def interrupt_after_initial_checkpoint(record, state):
        original_save(record, state)
        raise RSILearningError("fixture_initial_checkpoint_interrupt")

    controller._save_flow = interrupt_after_initial_checkpoint
    with pytest.raises(RSILearningError, match="fixture_initial_checkpoint_interrupt"):
        controller.run_drs(
            run_id=binding.run_id, contract_sha256=DIGEST, evaluator_sha256=DIGEST,
            environment_sha256=DIGEST, solver_id="mock", max_practice_rounds=0,
        )
    checkpoint = ledger.controller_checkpoint(binding.run_id)
    run = ledger.get_run(binding.run_id)
    changed = dict(checkpoint[1])
    with ledger.controller_lock(binding.run_id):
        if mutation == "checkpoint_injection":
            pin_controller = RSILearningController(
                fixture_solver_gateway("mock"), ledger=ledger,
                producer_sidecar=sidecar, producer_workspace=tmp_path,
            )
            changed["producer_checkpoint_binding"] = pin_controller._producer_checkpoint_state(run_id=binding.run_id)
        else:
            # A later valid journal revision must not erase the original request proof.
            ledger.transition(
                binding.run_id, state="paused", expected_record_sha256=run.record_sha256,
                payload_patch={"producer_checkpoint_binding": None},
            )
            del changed["producer_checkpoint_binding"]
        ledger.write_controller_checkpoint(binding.run_id, changed, expected_sha256=checkpoint[0])
    before = ledger.controller_checkpoint(binding.run_id)

    with pytest.raises(RSILearningError, match="rsi_resume_checkpoint_corrupt"):
        RSILearningController(
            fixture_solver_gateway("mock"), ledger=ledger,
            **({"producer_sidecar": sidecar, "producer_workspace": tmp_path}
               if mutation == "checkpoint_injection" else {}),
        ).resume(binding.run_id)
    assert ledger.controller_checkpoint(binding.run_id) == before


def test_producer_bound_legacy_checkpoint_fails_closed_without_sidecar_proof(tmp_path: Path) -> None:
    binding, sidecar = _sidecar(tmp_path)
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    controller = RSILearningController(
        fixture_solver_gateway("mock"), ledger=ledger,
        producer_sidecar=sidecar, producer_workspace=tmp_path,
    )
    with ledger.controller_lock(binding.run_id):
        record = controller._start_run(
            run_id=binding.run_id, mode="drs", contract_sha256=DIGEST,
            evaluator_sha256=DIGEST, environment_sha256=DIGEST, solver_id="mock",
            budget={"max_target_attempts": 1, "max_practice_rounds": 0},
        )
        assert record is not None
        ledger.write_controller_checkpoint(
            binding.run_id, {"schema_version": "1"}, expected_sha256=None,
        )

    with pytest.raises(RSILearningError, match="producer_checkpoint"):
        RSILearningController(
            fixture_solver_gateway("mock"), ledger=ledger,
            producer_sidecar=sidecar, producer_workspace=tmp_path,
        ).resume(binding.run_id)


class _DriftAfterFirstDispatchGateway:
    def __init__(self, sidecar_path: Path) -> None:
        self.sidecar_path = sidecar_path
        self.calls = 0
        self.delegate = fixture_solver_gateway("mock")

    def rsi_fingerprint_config(self):
        return {"fixture": "producer-sidecar-drift"}

    def run(self, request):
        self.calls += 1
        result = self.delegate.run(request)
        if self.calls == 1:
            self.sidecar_path.unlink()
        return result


class _AdmissionDriftController(RSILearningController):
    def __init__(self, *args, sidecar_path: Path, **kwargs):
        super().__init__(*args, **kwargs)
        self._sidecar_path_for_test = sidecar_path
        self._admission_calls = 0

    def _check_memory_admission(self, request, *, parent_run_id=None):
        super()._check_memory_admission(request, parent_run_id=parent_run_id)
        self._admission_calls += 1
        if self._admission_calls == 2:
            self._sidecar_path_for_test.unlink()


def test_producer_drift_after_admission_blocks_before_running_dispatch(tmp_path: Path) -> None:
    binding, sidecar = _sidecar(tmp_path)
    sidecar_path = tmp_path / "evolution" / "producer-batches" / binding.intent.journal_id / "python-producer-binding.json"
    gateway = _DriftAfterFirstDispatchGateway(sidecar_path)
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    controller = _AdmissionDriftController(
        gateway, ledger=ledger, producer_sidecar=sidecar, producer_workspace=tmp_path,
        sidecar_path=sidecar_path,
    )

    with pytest.raises(RSILearningError, match="producer_checkpoint"):
        controller.run_drs(
            run_id=binding.run_id, contract_sha256=DIGEST, evaluator_sha256=DIGEST,
            environment_sha256=DIGEST, solver_id="mock", max_practice_rounds=0,
        )

    assert controller._admission_calls == 2
    assert gateway.calls == 0
    assert ledger.get_episode(f"{binding.run_id}-target-0") is None


def test_producer_drift_inside_target_callback_blocks_callback_publication(tmp_path: Path) -> None:
    binding, sidecar = _sidecar(tmp_path)
    sidecar_path = tmp_path / "evolution" / "producer-batches" / binding.intent.journal_id / "python-producer-binding.json"
    ledger = RSILedger(tmp_path / "rsi.sqlite3")

    class DriftJudge:
        def rsi_fingerprint_config(self):
            return {"fixture": "producer-callback-drift"}

        def __call__(self, _execution):
            sidecar_path.unlink()
            return False, "fixture gap"

    controller = RSILearningController(
        fixture_solver_gateway("mock"), ledger=ledger, target_judge=DriftJudge(),
        producer_sidecar=sidecar, producer_workspace=tmp_path,
    )
    with pytest.raises(RSILearningError, match="producer_checkpoint"):
        controller.run_drs(
            run_id=binding.run_id, contract_sha256=DIGEST, evaluator_sha256=DIGEST,
            environment_sha256=DIGEST, solver_id="mock", max_practice_rounds=0,
        )

    callback = controller.callback_checkpoint(binding.run_id, f"judge:{binding.run_id}-target-0")
    assert callback is not None
    assert callback[1]["status"] == "started"


def test_producer_sidecar_drift_between_episodes_blocks_next_dispatch(tmp_path: Path) -> None:
    binding, sidecar = _sidecar(tmp_path)
    sidecar_path = tmp_path / "evolution" / "producer-batches" / binding.intent.journal_id / "python-producer-binding.json"
    gateway = _DriftAfterFirstDispatchGateway(sidecar_path)
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    controller = RSILearningController(
        gateway, ledger=ledger, target_judge=lambda _execution: (False, "gap"),
        producer_sidecar=sidecar, producer_workspace=tmp_path,
    )

    with pytest.raises(RSILearningError, match="producer_checkpoint"):
        controller.run_drs(
            run_id=binding.run_id, contract_sha256=DIGEST, evaluator_sha256=DIGEST,
            environment_sha256=DIGEST, solver_id="mock", max_practice_rounds=1,
            max_target_attempts=2,
        )

    assert gateway.calls == 1


def test_direct_episode_resume_rechecks_producer_sidecar(tmp_path: Path) -> None:
    binding, sidecar = _sidecar(tmp_path)
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    controller = RSILearningController(
        fixture_solver_gateway("mock"), ledger=ledger,
        producer_sidecar=sidecar, producer_workspace=tmp_path,
    )
    result = controller.run_drs(
        run_id=binding.run_id, contract_sha256=DIGEST, evaluator_sha256=DIGEST,
        environment_sha256=DIGEST, solver_id="mock", max_practice_rounds=0,
    )
    execution = result.target_attempts[0]
    head = ledger.get_episode(execution.episode.episode_id)
    assert head is not None
    sidecar_path = tmp_path / "evolution" / "producer-batches" / binding.intent.journal_id / "python-producer-binding.json"
    sidecar_path.unlink()

    resumed = RSILearningController(
        fixture_solver_gateway("mock"), ledger=ledger,
        producer_sidecar=sidecar, producer_workspace=tmp_path,
    )
    with pytest.raises(RSILearningError, match="producer_checkpoint"):
        resumed._resume_episode_execution(head, request_hint=execution.request)


def test_unchanged_checkpoint_save_still_revalidates_sidecar(tmp_path: Path) -> None:
    binding, sidecar = _sidecar(tmp_path)
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    controller = RSILearningController(
        fixture_solver_gateway("mock"), ledger=ledger,
        producer_sidecar=sidecar, producer_workspace=tmp_path,
    )
    controller.run_drs(
        run_id=binding.run_id, contract_sha256=DIGEST, evaluator_sha256=DIGEST,
        environment_sha256=DIGEST, solver_id="mock", max_practice_rounds=0,
    )
    record = ledger.get_run(binding.run_id)
    checkpoint = ledger.controller_checkpoint(binding.run_id)
    assert record is not None and checkpoint is not None
    sidecar_path = tmp_path / "evolution" / "producer-batches" / binding.intent.journal_id / "python-producer-binding.json"
    sidecar_path.unlink()

    with pytest.raises(RSILearningError, match="producer_checkpoint"):
        controller._save_flow(record, checkpoint[1])


class _TerminalSidecarDriftController(RSILearningController):
    def __init__(self, *args, sidecar_path: Path, **kwargs):
        super().__init__(*args, **kwargs)
        self._sidecar_path_for_test = sidecar_path

    def _save_flow(self, record, state):
        super()._save_flow(record, state)
        if state.get("phase") == "terminal":
            self._sidecar_path_for_test.unlink()


def test_terminal_run_publication_stops_after_sidecar_drift(tmp_path: Path) -> None:
    binding, sidecar = _sidecar(tmp_path)
    sidecar_path = tmp_path / "evolution" / "producer-batches" / binding.intent.journal_id / "python-producer-binding.json"
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    controller = _TerminalSidecarDriftController(
        fixture_solver_gateway("mock"), ledger=ledger,
        producer_sidecar=sidecar, producer_workspace=tmp_path,
        sidecar_path=sidecar_path,
    )

    with pytest.raises(RSILearningError, match="producer_checkpoint"):
        controller.run_drs(
            run_id=binding.run_id, contract_sha256=DIGEST, evaluator_sha256=DIGEST,
            environment_sha256=DIGEST, solver_id="mock", max_practice_rounds=0,
        )

    run = ledger.get_run(binding.run_id)
    assert run is not None
    assert run.state == "running"


def test_terminal_settlement_rechecks_latest_run_producer_identity(tmp_path: Path) -> None:
    binding, sidecar = _sidecar(tmp_path)
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    controller = RSILearningController(
        fixture_solver_gateway("mock"), ledger=ledger,
        producer_sidecar=sidecar, producer_workspace=tmp_path,
    )
    original_save = controller._save_flow

    def change_run_after_terminal_checkpoint(record, state):
        original_save(record, state)
        if state["phase"] == "terminal":
            ledger.transition(
                binding.run_id, state="paused", expected_record_sha256=record.record_sha256,
                payload_patch={"producer_checkpoint_binding": None},
            )

    controller._save_flow = change_run_after_terminal_checkpoint
    with pytest.raises(RSILearningError, match="rsi_resume_checkpoint_corrupt"):
        controller.run_drs(
            run_id=binding.run_id, contract_sha256=DIGEST, evaluator_sha256=DIGEST,
            environment_sha256=DIGEST, solver_id="mock", max_practice_rounds=0,
        )
    assert ledger.get_run(binding.run_id).state == "paused"
