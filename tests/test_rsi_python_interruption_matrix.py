"""Read-only interruption acceptance across actual local controller and journal files."""

from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_python_producer_recovery import _binding, _receipt
from test_python_producer_recovery_anchor import _durable_snapshot
from test_rsi_controller_callbacks import (
    PINS,
    CallbackCrash,
    Curriculum,
    Gateway,
    Judge,
    Verifier,
)
from test_rsi_producer_checkpoint_binding import _sidecar
from test_rsi_python_admission import DEADLINE, DIGEST, OTHER, _files, _rows
from test_rsi_python_publication import _call, _fixture, _publish_files

from lunar_evolution import (
    RSILearningController,
    RSILearningError,
    RSILedger,
    bundle_evolution,
    producer_process,
)
from lunar_evolution import producer_bundle_staging as staging
from lunar_evolution import rsi_python_publication as publication
from lunar_evolution.python_producer_checkpoint import PythonProducerCheckpointBinding
from lunar_evolution.python_producer_lifecycle import (
    PythonProducerLifecycleError,
    recover_python_producer_terminal,
    resume_python_producer_terminal,
)
from lunar_evolution.rsi_callbacks import DurableCallbackJournal


@pytest.fixture(autouse=True)
def _inert_only(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("interruption matrix reached a process, cleanup or evaluator")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(producer_process, "run_producer_process", forbidden)
    monkeypatch.setattr(producer_process, "cleanup_registered_process", forbidden)
    monkeypatch.setattr(bundle_evolution, "evaluate_candidate_execution", forbidden)
    monkeypatch.setattr(
        bundle_evolution.MultiFileCandidatePipeline, "evaluate_draft_non_publishing", forbidden,
    )


def _reopen(value):
    return RSILearningController(
        value.gateway, ledger=RSILedger(value.ledger.database),
        producer_sidecar=value.sidecar, producer_workspace=value.workspace,
    )


@pytest.mark.parametrize("entry", ["resume", "expired_resume", "same_run"])
def test_interrupted_dispatch_retains_pinned_admission_without_budget_or_deadline_refresh(
    tmp_path, entry,
):
    # This fixture interrupted the inert gateway after intent/running-head persistence,
    # then pinned actual prepared handoff/anchor evidence. No process was launched.
    value = _fixture(tmp_path)
    checkpoint = value.ledger.controller_checkpoint(value.binding.run_id)
    assert value.ledger.get_episode(value.episode_id).state == "running"
    assert value.ledger.episode_result(value.episode_id) is None
    assert checkpoint[1]["budget_state"]["consumed"]["solver_invocations"] == 1
    assert checkpoint[1]["budget_state"]["planned"]["deadline_unix"] == DEADLINE
    assert value.record.production_admission is False
    before = (_rows(value), _files(value))

    for _ in range(2):
        restarted = _reopen(value)
        with pytest.raises(RSILearningError, match="^rsi_resume_recovery_required$"):
            if entry == "same_run":
                restarted.run_drs(
                    run_id=value.binding.run_id, contract_sha256=DIGEST,
                    evaluator_sha256=DIGEST, environment_sha256=DIGEST, solver_id="native",
                    max_practice_rounds=0, budget={"deadline_unix": DEADLINE},
                )
            else:
                restarted.resume(
                    value.binding.run_id, **({"now": DEADLINE + 1} if entry == "expired_resume"
                                             else {}),
                )
        assert value.gateway.calls == 1
        assert (_rows(value), _files(value)) == before
        assert value.ledger.controller_checkpoint(value.binding.run_id) == checkpoint


@pytest.mark.parametrize("stage", ["verifier", "judge", "curriculum"])
@pytest.mark.parametrize("entry", ["resume", "same_run"])
def test_producer_bound_callback_interruption_quarantines_reopened_controller(tmp_path, stage, entry):
    binding, sidecar = _sidecar(tmp_path)
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    gateway = Gateway()
    verifier, judge, curriculum = (
        Verifier(crash=stage == "verifier"), Judge(crash=stage == "judge"),
        Curriculum(crash=stage == "curriculum"),
    )
    value = SimpleNamespace(workspace=tmp_path, ledger=ledger)
    arguments = {
        "run_id": binding.run_id, **PINS, "max_practice_rounds": 1, "max_target_attempts": 2,
        "budget": {"deadline_unix": binding.deadline_unix, "max_unknown_retries": 1},
    }

    def controller():
        return RSILearningController(
            gateway, ledger=RSILedger(ledger.database), producer_sidecar=sidecar,
            producer_workspace=tmp_path, verifier=verifier, target_judge=judge,
            curriculum=curriculum,
        )

    with pytest.raises(CallbackCrash, match=stage + "_response_lost"):
        controller().run_drs(**arguments)
    suffix = "practice-0-0" if stage == "curriculum" else "target-0"
    callback_id = stage + ":" + binding.run_id + "-" + suffix
    callback = controller().callback_checkpoint(binding.run_id, callback_id)
    assert callback[1]["status"] == "started"
    callback_history = ledger.controller_checkpoint_history(
        DurableCallbackJournal.identity(binding.run_id, callback_id),
    )
    checkpoint = ledger.controller_checkpoint(binding.run_id)
    assert checkpoint[1]["budget_state"]["consumed"]["unknown_retries"] == 0
    assert checkpoint[1]["budget_state"]["planned"]["deadline_unix"] == binding.deadline_unix
    calls = tuple(tuple(component.calls) for component in (gateway, verifier, judge, curriculum))
    before = (_rows(value), _files(value))

    for _ in range(2):
        with pytest.raises(RSILearningError, match="callback.*reconcile_required"):
            if entry == "resume":
                controller().resume(binding.run_id, now=binding.deadline_unix + 1)
            else:
                controller().run_drs(**arguments)
        assert tuple(tuple(c.calls) for c in (gateway, verifier, judge, curriculum)) == calls
        assert (_rows(value), _files(value)) == before
        assert ledger.controller_checkpoint(binding.run_id) == checkpoint
        assert ledger.controller_checkpoint_history(
            DurableCallbackJournal.identity(binding.run_id, callback_id),
        ) == callback_history


def _process_files(workspace, binding):
    """Persist coherent inert native claim/registration/terminal wires; never launch."""
    batch = workspace / "evolution" / "producer-batches" / binding.intent.journal_id
    receipt = _receipt(binding)
    identity = {key: getattr(receipt, key) for key in (
        "launch_id", "journal_id", "run_id", "parent_task_id", "task_id", "intent_sha256",
        "attestation_sha256", "executable_identity",
    )}
    claim = {
        "schema_version": "1", "protocol": producer_process.PRODUCER_PROCESS_PROTOCOL,
        **identity, "nonce": "inert-retained-once",
    }
    claim["consumption_sha256"] = producer_process._digest_without(claim, "consumption_sha256")
    registration = {
        **claim, **{key: getattr(receipt, key) for key in (
            "execution_binding", "execution_snapshot_relative_path", "execution_snapshot_sha256",
            "execution_snapshot_size", "pid", "pgid", "owner_identity",
        )}, "owner_identity_sha256": producer_process._sha(dict(receipt.owner_identity)),
    }
    registration["registration_sha256"] = producer_process._digest_without(
        registration, "registration_sha256",
    )
    receipt = replace(
        receipt, consumption_sha256=claim["consumption_sha256"],
        registration_sha256=registration["registration_sha256"],
        previous_receipt_sha256=registration["registration_sha256"], receipt_sha256=None,
    )
    for name, wire in (
        ("attestation-consumption.json", claim), ("process-registration.json", registration),
        ("execution-receipt.json", receipt.to_dict()),
    ):
        producer_process._atomic_json(batch / name, wire, exclusive=True)
    return batch


@pytest.mark.parametrize("window,error", [
    ("claim_only", "recovery_required"),
    ("registration_only", "recovery_required"),
    ("unknown_terminal", "recovery_observation_invalid"),
    ("journal_mismatch", "recovery_observation_invalid"),
    ("cleanup_unknown", "cleanup_unknown"),
    ("complete_receipt_without_runtime", None),
])
def test_actual_process_journal_recovery_never_repairs_or_upgrades_incomplete_python_attempt(
    tmp_path, window, error,
):
    binding, sidecar = _binding(tmp_path)
    checkpoint = PythonProducerCheckpointBinding.from_sidecar(sidecar)
    batch = _process_files(tmp_path, binding)
    terminal_path = batch / "execution-receipt.json"
    if window in {"claim_only", "registration_only"}:
        terminal_path.unlink()
        if window == "claim_only":
            (batch / "process-registration.json").unlink()
    elif window != "complete_receipt_without_runtime":
        raw = json.loads(terminal_path.read_bytes())
        raw.update({
            "unknown_terminal": {"status": "unknown"},
            "journal_mismatch": {"journal_id": "foreign-journal"},
            "cleanup_unknown": {"cleanup_status": "unknown", "cleanup_sha256": None},
        }[window])
        raw["receipt_sha256"] = producer_process._digest_without(raw, "receipt_sha256")
        terminal_path.write_bytes(producer_process._canonical(raw))
    before = _durable_snapshot(tmp_path)
    original = (binding.to_json(), checkpoint.to_json())

    for _ in range(2):
        if error is not None:
            with pytest.raises(PythonProducerLifecycleError,
                               match="^python_producer_lifecycle_" + error + "$"):
                recover_python_producer_terminal(
                    tmp_path, binding=binding, sidecar=sidecar, checkpoint=checkpoint,
                )
        else:
            terminal = recover_python_producer_terminal(
                tmp_path, binding=binding, sidecar=sidecar, checkpoint=checkpoint,
            )
            assert terminal.status == "unknown"
            assert terminal.deadline_unix == binding.deadline_unix
            assert terminal.publication_eligible is False
            with pytest.raises(PythonProducerLifecycleError, match="reconcile_required"):
                resume_python_producer_terminal(terminal, expected_binding=binding)
        assert _durable_snapshot(tmp_path) == before
        assert (binding.to_json(), checkpoint.to_json()) == original
        assert not (batch / "recovery-receipt.json").exists()


@pytest.mark.parametrize("window,error", [
    ("prepared_without_projection", "recovery_journal_invalid"),
    ("malformed_projection", "recovery_journal_invalid"),
    ("unknown_journal", "recovery_unknown_terminal"),
    ("journal_mismatch", "recovery_journal_mismatch"),
    ("published_missing_staged", "recovery_manifest_mismatch"),
    ("published_malformed_staged", "recovery_journal_invalid"),
    ("published_missing_terminal", "recovery_missing"),
    ("published_terminal_mismatch", "recovery_terminal_mismatch"),
    ("after_materials_before_terminal", "recovery_unknown_terminal"),
])
def test_reopened_controller_publication_recovery_preserves_first_interruption_and_all_effects(
    tmp_path, monkeypatch, window, error,
):
    value = _fixture(tmp_path)
    if window == "malformed_projection":
        (value.batch / "journal.json").write_bytes(b'{"interrupted":')
    elif window in {"unknown_journal", "journal_mismatch"}:
        changed = replace(
            value.journal, journal_sha256=None,
            **({"state": "unknown", "publication_phase": "recovery_required"}
               if window == "unknown_journal" else {"environment_sha256": OTHER}),
        )
        (value.batch / "journal.json").write_bytes(producer_process._canonical(changed.to_dict()))
    elif window == "after_materials_before_terminal":
        original_write = staging._write_new

        def interrupt(path, *args, **kwargs):
            if path.name == "terminal.json":
                raise OSError("inert terminal persistence interruption")
            return original_write(path, *args, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(staging, "_write_new", interrupt)
            with pytest.raises(staging.ProducerBundlePublicationStagingError,
                               match="commit_unknown"):
                _publish_files(value)
        assert json.loads((value.workspace / "evolution/producer-publication.json").read_bytes())[
            "status"
        ] == "unknown"
        assert value.journal.candidates[0].candidate_id in json.loads(
            (value.workspace / "evolution/state.json").read_bytes(),
        )["active_ids"]["0"]
        assert (value.workspace / "evolution/archive.jsonl").read_bytes()
        assert not (value.batch / "terminal.json").exists()
    elif window.startswith("published_"):
        _publish_files(value)
        path = value.batch / ("journal.staged.json" if window.endswith("staged")
                              else "terminal.json")
        if "missing" in window:
            path.unlink()
        elif window == "published_malformed_staged":
            path.write_bytes(b'{"interrupted":')
        else:
            terminal = json.loads(path.read_bytes())
            terminal["journal_id"] = "foreign-journal"
            path.write_bytes(producer_process._canonical(terminal))
    before = (_rows(value), _files(value))
    checkpoint = value.ledger.controller_checkpoint(value.binding.run_id)

    for _ in range(2):
        value.controller = _reopen(value)
        with pytest.raises(publication.RSIPythonPublicationError) as caught:
            _call(value)
        assert caught.value.code == "rsi_python_publication_" + error
        assert (_rows(value), _files(value)) == before
        assert value.ledger.controller_checkpoint(value.binding.run_id) == checkpoint
        assert value.gateway.calls == 1
        assert value.record.production_admission is False
