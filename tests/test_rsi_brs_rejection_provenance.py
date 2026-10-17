"""Same original waiting owner C1/P/C2; no ready, dispatch or settlement."""

from __future__ import annotations

import stat
from copy import deepcopy
from dataclasses import replace
from threading import Thread

import pytest
import test_rsi_brs_rejection_c1 as c1

from lunar_evolution import (
    DeterministicCurriculum,
    RSILearningController,
    rsi_native_inputs,
    rsi_native_scheduler,
)
from lunar_evolution import rsi_brs_publication_lineage as brs
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.producer_launcher import build_producer_launch_attestation
from lunar_evolution.rsi_budget import RSIRunBudget
from lunar_evolution.rsi_identity import component_fingerprint
from lunar_evolution.rsi_learning import PracticeEpisode, RSILearningError
from lunar_evolution.rsi_native_plan import NativeRSIExecutionPlan
from lunar_evolution.rsi_native_rejection import (
    NATIVE_RSI_REJECTION_PROVENANCE_NAME,
    NativeRSIRejectionFilePin,
    read_native_rsi_rejection_provenance,
)

inert_only = c1.inert_only
tmp_path = c1.tmp_path
_FIELD = "producer_publication_lineage"


@pytest.fixture(autouse=True)
def sealed_launch(monkeypatch):
    """Seal actual local request/memory/launch files before the original capture.

    The bootstrap is inert data checked by the real artifact reader. Nothing
    executes it, and no launch-input validator or original owner is replaced.
    """
    setup = c1._native_setup
    runtime = c1.admission_fixture._fixture
    bootstrap = c1._inert_bootstrap
    held = {}

    def native_setup(root, patch, *, count, context, original_owner_setup):
        def sealed(path):
            manifest, tree, intent, _attestation, budget = runtime(path)
            intent = replace(intent, contract_sha256=context.contract.digest(),
                task_id=intent.run_id + "-practice-0-0", producer_id="openevolve",
                **{name: getattr(context.config, name) for name in (
                    "evaluator_kind", "evaluator_fingerprint", "runner_fingerprint",
                    "dependency_sha256", "environment_sha256")}, intent_sha256=None)
            controller = RSILearningController(c1.admission_fixture._NoSolverGateway())
            pins = {"contract_sha256": context.contract.digest(),
                    "evaluator_sha256": context.config.evaluator_fingerprint,
                    "environment_sha256": context.config.environment_sha256, "solver_id": "native"}
            target_id = intent.run_id + "-target-seed"
            target = controller._target_episode(intent.run_id, target_id, pins, 0)
            decision = DeterministicCurriculum().choose(target=target, diagnosis="gap-0", wave=0, ordinal=0)
            episode = PracticeEpisode(intent.task_id, intent.run_id, pins["contract_sha256"],
                pins["evaluator_sha256"], pins["environment_sha256"], controller.snapshot.digest(),
                pins["solver_id"], "planned", episode_kind="practice", wave=0, ordinal=0,
                parent_target_episode_id=target_id)
            request = controller._request(episode,
                budget=RSIRunBudget.create({"deadline_unix": c1.admission_fixture.DEADLINE,
                    "max_practice_rounds": 2, "max_target_attempts": 1}).to_dict()["planned"],
                charter={**decision.to_dict(), "decision_sha256": decision.digest()})
            inputs = rsi_native_inputs.prepare_native_rsi_inputs(path, journal_id=intent.journal_id,
                request=request, memory=controller.snapshot)
            argv = intent.argv + inputs.argv_fragment
            intent = replace(intent, argv=argv, argv_sha256=c1._sha(canonical_json(list(argv))), intent_sha256=None)
            intent = replace(intent, intent_sha256=intent.digest())
            attestation = build_producer_launch_attestation(intent, "late-admission-once")
            artifact = bootstrap(path)
            inputs = rsi_native_inputs.bind_native_rsi_launch(path, intent=intent,
                attestation=attestation, artifact=artifact, inputs=inputs)
            held.update(inputs=inputs, artifact=artifact)
            return manifest, tree, intent, attestation, budget

        patch.setattr(c1.admission_fixture, "_fixture", sealed)
        patch.setattr(c1, "_inert_bootstrap", lambda _root: held["artifact"])
        return setup(root, patch, count=count, context=context, original_owner_setup=original_owner_setup)

    def native_plan(binding, request, memory):
        return NativeRSIExecutionPlan.from_native_inputs(request=request, memory=memory,
            inputs=held["inputs"], intent=binding.intent, attestation=binding.attestation,
            artifact=held["artifact"], candidate_selector_id="native-selector-v1",
            candidate_selector_sha256=component_fingerprint(rsi_native_scheduler.select_native_candidate),
            evaluator_kind=binding.evaluator_kind, evaluator_fingerprint=binding.evaluator_fingerprint)

    monkeypatch.setattr(c1, "_native_setup", native_setup)
    monkeypatch.setattr(c1.owner_fixture, "_plan", native_plan)


def _path(value):
    return value.batch / NATIVE_RSI_REJECTION_PROVENANCE_NAME


def _original_files(value):
    return {name: record for name, record in c1._native_material_snapshot(value).items()
            if not name.endswith("/" + NATIVE_RSI_REJECTION_PROVENANCE_NAME)}


@pytest.mark.parametrize("count", [1, 2])
def test_original_owner_retains_c1_p_c2_without_settling_or_releasing_worker(tmp_path, monkeypatch, count):
    with c1._waiting(tmp_path, monkeypatch, count=count) as value:
        value.owner.retain_rejected_terminal(value.terminal)
        captured = c1.owner_fixture._capture(value)
        original_files = _original_files(value)
        run = value.ledger.get_run(value.binding.run_id)
        episode = value.ledger.get_episode(value.episode_id)
        claim = value.ledger.inspect_native_episode_claim(value.request, plan_sha256=value.plan.plan_sha256)
        binding = value.owner.rejection_provenance_binding()
        assert binding.checkpoint_sha256 == captured[0]
        assert binding.candidate_ids == tuple(item.candidate_id for item in value.terminal.candidates)

        value.owner.retain_rejection_provenance()

        state = value.wave.state
        wire = state[_FIELD]
        entry = wire["batches"][0]
        reference = entry["rejection_provenance"]
        pin = value.owner.rejection_provenance_file_pin()
        assert type(pin) is NativeRSIRejectionFilePin
        assert reference == {"provenance_sha256": reference["provenance_sha256"], "file_pin": pin.to_dict()}
        evidence = read_native_rsi_rejection_provenance(_path(value).parent, expected_file_pin=pin)
        assert evidence.lineage == binding
        assert evidence.provenance_sha256 == reference["provenance_sha256"]
        assert evidence.provenance_file_pin == pin
        assert evidence.plan == value.plan and evidence.claim == claim
        assert evidence.terminal == value.terminal
        assert pin.sha256 == c1._sha(_path(value).read_bytes())
        assert pin.sha256 != evidence.provenance_sha256
        info = _path(value).stat()
        assert (stat.S_IMODE(info.st_mode), info.st_nlink, info.st_ino) == (0o400, 1, pin.inode)
        expected = deepcopy(captured[2])
        expected[_FIELD]["batches"][0]["rejection_provenance"] = reference
        assert state == expected
        assert wire["head"] is None
        assert value.owner._phase == "rejected-provenance" and not value.owner._poisoned
        assert value.owner._head == value.wave.checkpoint_sha256 != captured[0]
        assert value.ledger.controller_checkpoint(value.binding.run_id) == (value.owner._head, state)
        history = value.ledger.controller_checkpoint_history(value.binding.run_id)
        assert history[-2:] == [(captured[0], captured[2]), (value.owner._head, state)]
        assert _original_files(value) == original_files
        assert value.ledger.get_run(value.binding.run_id) == run
        assert value.ledger.get_episode(value.episode_id) == episode
        assert value.ledger.inspect_native_episode_claim(value.request, plan_sha256=value.plan.plan_sha256) == claim
        c1._quiet(value)


@pytest.mark.parametrize("fault", ["foreign", "subclass", "thread", "lock", "phase", "source", "nonce", "head", "plan"])
def test_provenance_refuses_missing_original_owner_authority_before_p(tmp_path, monkeypatch, fault):
    with c1._waiting(tmp_path, monkeypatch) as value:
        value.owner.retain_rejected_terminal(value.terminal)
        owner = value.owner
        if fault == "foreign":
            owner = object()
        elif fault == "subclass":
            class Subclass(brs._BRSLineageCheckpointOwner):
                pass
            owner = object.__new__(Subclass)
        elif fault == "lock":
            monkeypatch.setattr(value.ledger, "controller_lock_held", lambda _run_id: False)
        elif fault == "phase":
            value.owner._phase = "prepared-evidence"
        elif fault == "source":
            value.gateway.fingerprint = "foreign"
        elif fault == "nonce":
            object.__setattr__(value.wave.selected_handoff, "lease_nonce", "Z" * 32)
        elif fault == "head":
            value.ledger.write_controller_checkpoint(value.binding.run_id, deepcopy(value.wave.state),
                                                    expected_sha256=value.owner._head)
        elif fault == "plan":
            object.__setattr__(value.plan, "task_id", "foreign-task")
        captured = c1.owner_fixture._capture(value)
        history = value.ledger.controller_checkpoint_history(value.binding.run_id)
        if fault == "thread":
            errors = []
            def invoke():
                try:
                    value.owner.retain_rejection_provenance()
                except (RSILearningError, ValueError) as exc:
                    errors.append(exc)
            thread = Thread(target=invoke)
            thread.start()
            thread.join(15)
            assert not thread.is_alive() and len(errors) == 1
        else:
            with pytest.raises((RSILearningError, ValueError)):
                brs._BRSLineageCheckpointOwner.retain_rejection_provenance(owner)
        c1.owner_fixture._unchanged(value, captured)
        assert value.ledger.controller_checkpoint_history(value.binding.run_id) == history
        assert not _path(value).exists()


@pytest.mark.parametrize("name", ["lineage/rejected.json", "journal.prepared.json", "rejections.json"])
def test_provenance_refuses_same_bytes_under_a_replacement_inode(tmp_path, monkeypatch, name):
    with c1._waiting(tmp_path, monkeypatch) as value:
        value.owner.retain_rejected_terminal(value.terminal)
        captured = c1.owner_fixture._capture(value)
        path = value.batch / name
        raw, mode = path.read_bytes(), stat.S_IMODE(path.stat().st_mode)
        path.rename(path.with_suffix(path.suffix + ".original"))
        path.write_bytes(raw)
        path.chmod(mode)
        with pytest.raises((RSILearningError, ValueError)):
            value.owner.retain_rejection_provenance()
        c1.owner_fixture._unchanged(value, captured)
        assert not _path(value).exists() and value.owner._poisoned


@pytest.mark.parametrize("existing", [b"", b"{}", "symlink", "hardlink"])
def test_provenance_never_adopts_an_existing_or_partial_p(tmp_path, monkeypatch, existing):
    with c1._waiting(tmp_path, monkeypatch) as value:
        value.owner.retain_rejected_terminal(value.terminal)
        captured = c1.owner_fixture._capture(value)
        path = _path(value)
        if existing in ("symlink", "hardlink"):
            target = value.workspace / "existing-p"
            target.write_bytes(b"{}")
            target.chmod(0o400)
            if existing == "symlink":
                path.symlink_to(target)
            else:
                path.hardlink_to(target)
        else:
            path.write_bytes(existing)
            path.chmod(0o400)
        info = path.lstat()
        with pytest.raises((RSILearningError, ValueError)):
            value.owner.retain_rejection_provenance()
        c1.owner_fixture._unchanged(value, captured)
        assert path.lstat().st_ino == info.st_ino
        assert value.owner._poisoned


@pytest.mark.parametrize("fault", ["cas", "after-write", "late-revision", "source-after-write", "p-after-write"])
def test_uncertain_c2_retains_p_and_old_capture_without_retry(tmp_path, monkeypatch, fault):
    with c1._waiting(tmp_path, monkeypatch) as value:
        value.owner.retain_rejected_terminal(value.terminal)
        captured = c1.owner_fixture._capture(value)
        write = value.ledger.write_controller_checkpoint
        writes = []
        def injected(run_id, expected, *, expected_sha256):
            writes.append(expected)
            assert _path(value).exists()
            if fault == "cas":
                raise RSILearningError("fixture_c2_cas_unknown")
            head = write(run_id, expected, expected_sha256=expected_sha256)
            if fault == "after-write":
                raise RSILearningError("fixture_c2_after_write_unknown")
            if fault == "late-revision":
                write(run_id, deepcopy(expected), expected_sha256=head)
            elif fault == "source-after-write":
                value.gateway.fingerprint = "changed-after-c2"
            elif fault == "p-after-write":
                path = _path(value)
                path.chmod(0o600)
                path.write_bytes(path.read_bytes() + b"\n")
                path.chmod(0o400)
            return head
        monkeypatch.setattr(value.ledger, "write_controller_checkpoint", injected)
        with pytest.raises((RSILearningError, ValueError)):
            value.owner.retain_rejection_provenance()
        assert len(writes) == 1 and _path(value).exists()
        c1.owner_fixture._unchanged(value, captured)
        assert value.owner._poisoned
        durable = value.ledger.controller_checkpoint(value.binding.run_id)
        if fault == "cas":
            assert durable == (captured[0], captured[2])
        else:
            assert durable[1] == writes[0]
        raw, inode = _path(value).read_bytes(), _path(value).stat().st_ino
        with pytest.raises((RSILearningError, ValueError)):
            value.owner.retain_rejection_provenance()
        assert len(writes) == 1
        assert (_path(value).read_bytes(), _path(value).stat().st_ino) == (raw, inode)


def test_external_dto_and_duplicate_calls_do_not_open_a_provenance_scope(tmp_path, monkeypatch):
    with c1._waiting(tmp_path, monkeypatch) as value:
        value.owner.retain_rejected_terminal(value.terminal)
        captured = c1.owner_fixture._capture(value)
        with pytest.raises((RSILearningError, ValueError)):
            value.owner.acknowledge_rejection_provenance(object(), object())
        c1.owner_fixture._unchanged(value, captured)
        assert not _path(value).exists()


def test_successful_provenance_cannot_be_repeated_or_acknowledged_externally(tmp_path, monkeypatch):
    with c1._waiting(tmp_path, monkeypatch) as value:
        value.owner.retain_rejected_terminal(value.terminal)
        value.owner.retain_rejection_provenance()
        pin = value.owner.rejection_provenance_file_pin()
        evidence = read_native_rsi_rejection_provenance(value.batch, expected_file_pin=pin)
        captured = c1.owner_fixture._capture(value)
        raw = _path(value).read_bytes()
        with pytest.raises((RSILearningError, ValueError)):
            value.owner.acknowledge_rejection_provenance(evidence, pin)
        c1.owner_fixture._unchanged(value, captured)
        assert _path(value).read_bytes() == raw
        with pytest.raises((RSILearningError, ValueError)):
            value.owner.retain_rejection_provenance()
        c1.owner_fixture._unchanged(value, captured)
        assert _path(value).read_bytes() == raw
