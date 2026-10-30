"""Original waiting BRS owner C1 over complete inert native rejection records.

The candidate/evaluator process boundaries return explicit inert observations.
No candidate program, subprocess, model, network or producer is executed. Bundle
plans, recorded attempts, evaluation records, receipts, all-rejected finalization,
original owner, before/prepared evidence acknowledgement, file pins and SQLite
CAS/readback are real. Preparation uses the existing original-owner controller
pin method. The original inert worker keeps waiting on its ready event with a
started claim; no worker ready/ACK grants authority. Synthetic native producer
observations are retained before original capture.
"""

from __future__ import annotations

import hashlib
import json
import socket
import subprocess
import time
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from threading import Thread, get_ident
from types import FunctionType

import pytest
import test_rsi_brs_publication_lineage_owner as owner_fixture
import test_rsi_python_admission as admission_fixture
import test_rsi_python_brs_publication_recovery as retained_fixture
from test_bundle_population import build_context
from test_producer_bundle_transaction import _formal_execution_receipt
from test_rsi_child_execution_flow import _inert_candidate_process
from test_rsi_publication_lineage_rejection_owner import _inert_rejection_evaluator
from test_rsi_python_scheduler_inputs import _inert_bootstrap

from lunar_evolution import (
    DeterministicCurriculum,
    RSILearningController,
    RSILearningError,
    RSILedger,
    candidate_evaluation,
    candidate_execution_runner,
    native_trusted_attempt,
    native_trusted_output,
    native_trusted_receipt,
    producer_bundle_rejection,
)
from lunar_evolution import producer_bundle_staging as staging
from lunar_evolution import rsi_brs_native_process_evidence as process_evidence
from lunar_evolution import rsi_brs_publication_lineage as brs
from lunar_evolution.automatic_solve_lifecycle import (
    SolveExecutionBudgetExceeded,
    SolveExecutionCancelled,
    SolveExecutionControl,
)
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.evolution import PopulationStrategy
from lunar_evolution.native_trusted_capture import capture_native_trusted_output
from lunar_evolution.native_trusted_output import prepare_native_trusted_output
from lunar_evolution.producer_broker_ipc import ProducerBrokerConfig, ProducerBrokerObservation
from lunar_evolution.producer_bundle_control import native_producer_bundle_budget_sha256
from lunar_evolution.producer_bundle_handoff import BundleGroup
from lunar_evolution.producer_bundle_intent import _intent_content
from lunar_evolution.producer_bundle_lineage import (
    LineageSnapshotPin,
    ProducerLineageBeforeIntent,
    verify_persisted_lineage_snapshot,
)
from lunar_evolution.producer_bundle_lineage_v2 import ProducerLineageRejectedTerminalV2
from lunar_evolution.producer_bundle_preflight import (
    compute_archive_prefix_digest,
    derive_producer_bundle_candidate_id,
    preflight_producer_bundle_publication,
)
from lunar_evolution.producer_process import _digest_without, parse_producer_execution_receipt
from lunar_evolution.producer_request_transport import (
    HostRequestJournal,
    HostRequestJournalIdentity,
    read_host_request_journal,
)
from lunar_evolution.python_producer_admission_anchor import (
    persist_python_producer_admission_attempt_anchor,
    project_python_producer_admission_attempt_anchor,
)
from lunar_evolution.python_producer_admission_handoff import (
    PYTHON_PRODUCER_ADMISSION_HANDOFF_NAME,
    build_python_producer_admission_handoff,
    persist_python_producer_admission_handoff_pinned,
)
from lunar_evolution.rsi_native_scheduler import NativeRSISchedulerContext
from lunar_evolution.rsi_producer_gateway import PythonProducerRSIExecutionConfig
from lunar_evolution.rsi_python_scheduler_inputs import PythonRSISchedulerInputContext


@pytest.fixture
def tmp_path(tmp_path_factory):
    return tmp_path_factory.mktemp("c1")


def _forbidden(*_args, **_kwargs):
    pytest.fail("BRS rejection C1 fixture invoked external execution")


@pytest.fixture(autouse=True)
def inert_only(monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", _forbidden)
    monkeypatch.setattr(subprocess, "run", _forbidden)
    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    monkeypatch.setattr(socket, "create_connection", _forbidden)
    monkeypatch.setattr(candidate_execution_runner, "_bounded_process_bytes", _inert_candidate_process)
    monkeypatch.setattr(candidate_evaluation, "_bounded_process_bytes", _inert_rejection_evaluator)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _native_material_snapshot(value):
    """Observe unchanged original evidence, excluding the C1-created descriptor."""
    observed = {}
    for path in (value.workspace / "evolution").rglob("*"):
        if not path.is_file() or path == value.batch / "lineage/rejected.json":
            continue
        info = path.stat()
        observed[path.relative_to(value.workspace).as_posix()] = (
            _sha(path.read_bytes()), info.st_mode, info.st_dev, info.st_ino,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns,
        )
    return observed


def _unlocked_cancelled():
    assert not staging._HELD_PUBLICATION_LOCKS.get()
    return False


def _selected_fixture(root, monkeypatch, context):
    """Keep the original selected fixture graph, with actual pipeline authorities."""
    selected = owner_fixture.selected
    root.mkdir(parents=True, exist_ok=True)
    value = admission_fixture._setup(root)
    value.owner_thread, value.events, value.operation = get_ident(), [], None

    class InertGateway:
        calls = 0
        fingerprint = "brs-original-rejection-c1-inert"

        def rsi_fingerprint_config(self):
            assert not staging._HELD_PUBLICATION_LOCKS.get()
            assert not value.controller._python_admission_brs_observation_lock._is_owned()
            return {"fixture": self.fingerprint}

        def run(self, request):
            self.calls += 1
            assert get_ident() != value.owner_thread
            assert not value.ledger.controller_lock_held(value.binding.run_id)
            value.events.append(("gateway", get_ident(), request.episode_id))
            assert value.operation is not None
            return value.operation(request)

    value.ledger = RSILedger(root / "selected-service.sqlite3")
    value.gateway = InertGateway()
    value.controller = RSILearningController(value.gateway, ledger=value.ledger,
        producer_sidecar=value.sidecar, producer_workspace=value.workspace)
    pins = {"contract_sha256": context.contract.digest(),
            "evaluator_sha256": context.config.evaluator_fingerprint,
            "environment_sha256": context.config.environment_sha256, "solver_id": "native"}
    target = value.controller._target_episode(value.binding.run_id, value.binding.run_id + "-target-seed", pins, 0)
    practices = [DeterministicCurriculum().choose(target=target, diagnosis=f"gap-{i}", wave=0, ordinal=i)
                 for i in range(2)]

    def capture(_state, _episode_id):
        raise selected._PreparationCaptured()

    with monkeypatch.context() as capture_patch:
        capture_patch.setattr(value.controller, "_execute_intent", capture)
        with pytest.raises(selected._PreparationCaptured):
            value.controller.run_brs(run_id=value.binding.run_id, **pins,
                practices=practices, max_workers=1, budget={"deadline_unix": value.binding.deadline_unix})
    value.episode_id = value.binding.run_id + "-practice-0-0"
    value.sibling_id = value.binding.run_id + "-practice-0-1"
    value.state = value.ledger.controller_checkpoint(value.binding.run_id)[1]
    return value


def _native_setup(root, patch, *, count, context, original_owner_setup):
    original_runtime = admission_fixture._fixture

    def bound(path):
        manifest, tree, intent, attestation, budget = original_runtime(path)
        intent = replace(intent, contract_sha256=context.contract.digest(),
            task_id=intent.run_id + "-practice-0-0", producer_id="openevolve",
            **{name: getattr(context.config, name) for name in (
                "evaluator_kind", "evaluator_fingerprint", "runner_fingerprint",
                "dependency_sha256", "environment_sha256")}, intent_sha256=None)
        return manifest, tree, replace(intent, intent_sha256=intent.digest()), attestation, budget

    patch.setattr(admission_fixture, "_fixture", bound)
    patch.setattr(admission_fixture, "DIGEST", context.contract.digest())
    patch.setattr(owner_fixture, "DIGEST", context.contract.digest())
    patch.setattr(owner_fixture.selected, "_fixture",
                  lambda path, monkeypatch: _selected_fixture(path, monkeypatch, context))
    value = original_owner_setup(root, patch)
    state = root / "evolution/state.json"
    # Replace the generic owner's deliberately incomplete placeholder before a
    # genuine population strategy inspects this original, not-yet-selected root.
    state.write_bytes(canonical_json({"strategy": "population", "config": context.config.to_dict()}))
    strategy = PopulationStrategy(replace(context, workspace=root))
    active_ids = {str(i): [] for i in range(strategy.config.num_islands)}
    state.write_bytes(canonical_json(strategy._state_payload("running", 0, active_ids=active_ids,
        stagnation=0, best_candidate_id=None, rng_seed=strategy.config.rng_seed,
        last_migration_iteration=0, error=None)))
    state.chmod(0o600)
    control = SolveExecutionControl(600, cancellation_callbacks=(_unlocked_cancelled,))
    groups = tuple(BundleGroup(f"bundle-{i + 1}", f"candidate-{i + 1}.py", (f"candidate-{i + 1}.py",))
                   for i in range(count))
    native = NativeRSISchedulerContext(workspace=root,
        producer_root=next(Path(item.path) for item in value.binding.runtime_manifest.roots
                           if item.label == value.binding.interpreter.root_label),
        intent=value.binding.intent, attestation=value.binding.attestation, artifact=_inert_bootstrap(root),
        broker_config=ProducerBrokerConfig("http://127.0.0.1:9/unused", {}), contract=context.contract,
        groups=groups, evaluator_kind=value.binding.evaluator_kind,
        evaluator_fingerprint=value.binding.evaluator_fingerprint,
        runner_fingerprint=value.binding.intent.runner_fingerprint,
        dependency_sha256=value.binding.dependency_sha256,
        environment_sha256=value.binding.environment_sha256,
        strategy=strategy, failure_ledger=value.ledger, execution_control=control,
        cancelled=_unlocked_cancelled, python_handoff_after_execution=_forbidden)
    value.gateway.producer_config = PythonProducerRSIExecutionConfig("openevolve", value.ledger,
        PythonRSISchedulerInputContext(native, value.sidecar, value.proof))
    value.native, value.strategy, value.control = native, strategy, control
    intent = native.intent
    output = value.batch / intent.output_directory
    output.mkdir()
    materials = []
    for group in groups:
        source = b"# inert candidate, never executed\n"
        (output / group.entrypoint).write_bytes(source)
        materials.append({"kind": "candidate_source", "path": group.entrypoint,
                          "size": len(source), "sha256": _sha(source)})
    (value.batch / intent.envelope_path).write_bytes(canonical_json({
        "schema_version": "1", "producer_id": intent.producer_id,
        "producer_fingerprint": intent.producer_fingerprint, "status": "completed",
        "contract_sha256": intent.contract_sha256, "budget": {"requests": 0}, "materials": materials}))
    broker_root = value.batch / ".host-request-journal"
    broker_root.mkdir(mode=0o700)
    identity = HostRequestJournalIdentity(wall_deadline_ns=1, **{name: getattr(intent, name) for name in (
        "launch_id", "journal_id", "run_id", "parent_task_id", "task_id", "intent_sha256",
        "request_timeout_seconds", "max_requests")})
    with HostRequestJournal.create(broker_root / "requests", identity):
        pass
    broker = read_host_request_journal(broker_root / "requests", expected_identity=identity)
    capture = capture_native_trusted_output(value.batch, intent=intent, terminal_sha256="3" * 64,
        broker=ProducerBrokerObservation(broker.snapshot, broker_root / "requests", identity,
            broker.journal_sha256, broker.journal_bytes, True, "inert-fixture", broker.journal_file_identity),
        deadline=time.monotonic() + 20)
    raw = _formal_execution_receipt(journal_id=intent.journal_id, run_id=intent.run_id,
        parent_task_id=intent.parent_task_id, task_id=intent.task_id)
    raw.update(launch_id=intent.launch_id, intent_sha256=intent.digest(),
        attestation_sha256=native.attestation.digest(), max_requests=intent.max_requests,
        request_timeout_seconds=intent.request_timeout_seconds,
        output_max_bytes=intent.output_max_bytes, wall_timeout_seconds=intent.wall_timeout_seconds)
    raw["trusted_execution"].update(output_capture_sha256=capture["capture_sha256"],
        broker_journal_identity=identity.to_dict(), broker_journal_sha256=broker.journal_sha256,
        broker_journal_bytes=broker.journal_bytes, broker_journal_file_identity=list(broker.journal_file_identity))
    raw["envelope_evidence"] = capture["envelope_evidence"]
    raw["receipt_sha256"] = _digest_without(raw, "receipt_sha256")
    receipt = parse_producer_execution_receipt(raw)
    (value.batch / "execution-receipt.json").write_bytes(canonical_json(receipt.to_dict()))
    (value.batch / "execution-receipt.json").chmod(0o600)
    terminal = {"protocol": "lunar-native-trusted-process-terminal-v1", "process_status": "exited_zero",
        "cleanup_status": "cleaned", "gate_released": True, "target_started": True,
        "terminal_sha256": receipt.trusted_execution["terminal_sha256"]}
    (root / "fixture-native-receipt-projection.json").write_bytes(canonical_json(receipt.to_dict()))
    (root / "fixture-native-terminal-projection.json").write_bytes(canonical_json(terminal))
    args = {name: getattr(native, name) for name in (
        "intent", "attestation", "artifact", "contract", "groups", "evaluator_kind",
        "evaluator_fingerprint", "runner_fingerprint", "dependency_sha256", "environment_sha256")}
    prepared = prepare_native_trusted_output(root, **args,
        require_same_attempt_capture=True, require_execution_receipt=True)
    value.admission = prepared.admission_plan
    handoff = value.handoff.to_dict()
    handoff.pop("handoff_sha256")
    handoff.update(native_execution_receipt_sha256=receipt.receipt_sha256,
        admission_plan_sha256=value.admission.digest(), envelope_sha256=prepared.envelope.envelope_sha256)
    value.handoff = build_python_producer_admission_handoff(**handoff)
    sidecar_path = value.batch / PYTHON_PRODUCER_ADMISSION_HANDOFF_NAME
    sidecar_path.rename(sidecar_path.with_suffix(".before-c1-fixture"))
    value.pin = persist_python_producer_admission_handoff_pinned(value.batch, handoff=value.handoff).file_pin
    value.journal = replace(value.journal, admission_sha256=value.admission.digest(),
        evaluator_kind=context.config.evaluator_kind,
        native_execution_receipt_sha256=receipt.receipt_sha256,
        python_handoff_sha256=value.handoff.handoff_sha256, python_handoff_file_pin=value.pin,
        base_archive_sha256=_sha(b""), base_state_sha256=_sha(state.read_bytes()),
        population_config_sha256=_sha(canonical_json(strategy.config.to_dict())),
        num_islands=strategy.config.num_islands,
        archive_prefix_sha256=compute_archive_prefix_digest(_sha(b""), _sha(state.read_bytes()),
            strategy_config_sha256=_sha(canonical_json(strategy.config.to_dict())),
            active_ids_sha256=_sha(canonical_json(active_ids))),
        budget_sha256=native_producer_bundle_budget_sha256(strategy, control),
        candidates=tuple(replace(value.journal.candidates[0], bundle_id=item.bundle_id,
            bundle_sha256=item.bundle_sha256, island_id=i % strategy.config.num_islands,
            # Use the native transaction's preparation binding for this actual
            # prepared admission item; a generic placeholder receipt is shared.
            preparation_receipt_sha256=_sha(canonical_json({
                "plan_sha256": value.admission.digest(), "bundle_id": item.bundle_id, "ordinal": i})),
            candidate_id=derive_producer_bundle_candidate_id(value.journal.journal_id, i, item.bundle_id, item.bundle_sha256))
            for i, item in enumerate(value.admission.bundles)), journal_sha256=None)
    (value.batch / "journal.prepared.json").write_bytes(_intent_content(value.journal)[0])
    anchor = value.batch / "python-producer-admission-anchor.json"
    anchor.rename(anchor.with_suffix(".before-c1-fixture"))
    value.anchor = project_python_producer_admission_attempt_anchor(value.handoff)
    persist_python_producer_admission_attempt_anchor(value.batch, anchor=value.anchor)
    value.prepared_output = prepared
    return value


@contextmanager
def _waiting(tmp_path, monkeypatch, *, count=1, acknowledge=True):
    context = build_context(tmp_path / "pipeline")
    original_plan = owner_fixture._plan

    def native_plan(binding, request, memory):
        return replace(original_plan(binding, request, memory),
                       evaluator_kind=context.config.evaluator_kind, plan_sha256=None)

    monkeypatch.setattr(owner_fixture, "_plan", native_plan)
    receipt_projection = FunctionType(retained_fixture._receipt_projection.__code__, vars(native_trusted_receipt),
                                      retained_fixture._receipt_projection.__name__)
    terminal_projection = FunctionType(retained_fixture._terminal_projection.__code__, vars(native_trusted_attempt),
                                       retained_fixture._terminal_projection.__name__)
    monkeypatch.setattr(native_trusted_attempt, "_BRS_NATIVE_READER_TERMINAL_HOOK", None, raising=False)
    monkeypatch.setattr(native_trusted_receipt, "build_native_trusted_execution_receipt", receipt_projection)
    for module in (native_trusted_attempt, native_trusted_output, native_trusted_receipt, process_evidence):
        monkeypatch.setattr(module, "recover_native_trusted_attempt", terminal_projection)
    original = owner_fixture._setup
    monkeypatch.setattr(owner_fixture, "_setup", lambda root, patch: _native_setup(
        root, patch, count=count, context=context, original_owner_setup=original))
    with owner_fixture._waiting(tmp_path, monkeypatch) as value:
        before_state = (value.workspace / "evolution/state.json").read_bytes()
        value.owner.validate_before(value.journal, b"", before_state, value.strategy,
                                    admission_plan=value.admission)
        value.owner.retain_before(value.journal, b"", before_state)
        if acknowledge:
            acknowledgement = value.controller._pin_python_admission_for_original_brs_owner(
                value.owner, expected_anchor_sha256=value.anchor.anchor_sha256)
            value.owner.acknowledge_prepared(value.journal, acknowledgement)
        value.preflight = preflight_producer_bundle_publication(value.workspace, value.admission, value.journal)
        evaluations = tuple(value.strategy.context.bundle_pipeline.evaluate_draft_non_publishing(
            value.strategy, draft.draft, journal_id=value.journal.journal_id, ordinal=ordinal,
            journal_candidate=candidate, admission_plan=value.admission, journal_sha256=value.journal.digest())
            for ordinal, (draft, candidate) in enumerate(zip(value.prepared_output.drafts, value.journal.candidates, strict=True)))
        value.terminal = producer_bundle_rejection.finalize_producer_bundle_all_rejected(
            value.workspace, value.journal, value.preflight, evaluations, authority=value.strategy.integrity_authority)
        yield value


def _quiet(value):
    assert value.ledger.get_run(value.binding.run_id).state == "running"
    assert value.ledger.get_episode(value.episode_id).state == "running"
    assert value.ledger.inspect_native_episode_claim(value.request, plan_sha256=value.plan.plan_sha256).status == "started"
    assert value.ledger.episode_result(value.episode_id) is None
    assert value.wave.state["executions"] == {}
    assert not (value.workspace / "evolution/producer-publication.json").exists()
    for name in ("stage", "manifest.json", "journal.staged.json", "journal.published.json", "terminal.json"):
        assert not (value.batch / name).exists()
    assert not value.wave.channel._requests and not value.wave.channel._queue
    assert value.messages.empty()
    assert not value.ready.is_set()


@pytest.mark.parametrize("count", [1, 2])
def test_real_native_rejection_fixture_has_complete_ordered_material(tmp_path, monkeypatch, count):
    with _waiting(tmp_path, monkeypatch, count=count) as value:
        observed = producer_bundle_rejection._verify_terminal_batch_rejection_evidence(
            value.workspace, value.batch, value.journal, terminal=value.terminal)
        assert observed.candidate_ids == tuple(candidate.candidate_id for candidate in value.journal.candidates)
        assert len(observed.candidate_ids) == count
        assert observed.manifest_sha256 == _sha((value.batch / "rejections.json").read_bytes())
        assert observed.manifest_sha256 != value.terminal.terminal_marker_sha256
        assert value.owner._phase == "prepared-evidence" and not value.owner._poisoned
        assert not (value.batch / "lineage/rejected.json").exists()
        _quiet(value)


@pytest.mark.parametrize("count", [1, 2])
def test_original_owner_c1_retains_rejection_without_settlement_or_publication(tmp_path, monkeypatch, count):
    with _waiting(tmp_path, monkeypatch, count=count) as value:
        before = owner_fixture._capture(value)
        run_history = value.ledger.history(value.binding.run_id)
        episode = value.ledger.get_episode(value.episode_id)
        claim = value.ledger.inspect_native_episode_claim(value.request, plan_sha256=value.plan.plan_sha256)
        archive_state = (value.workspace / "evolution/state.json").read_bytes()
        value.owner.retain_rejected_terminal(value.terminal)
        actual = value.wave.state["producer_publication_lineage"]
        entry = actual["batches"][0]
        original = before[2]["producer_publication_lineage"]["batches"][0]
        assert entry["state"] == "rejected" and entry["rejection_schema"] == "lunar-rsi-brs-rejection-c1-v1"
        assert entry["rejection_provenance"] is None and actual["head"] is None
        assert entry["before"] == original["before"] and entry["before_file_pin"] == original["before_file_pin"]
        assert entry["snapshots"] == original["snapshots"] and len(entry["snapshots"]) == 2
        assert entry["before_sources"] == original["before_sources"]
        assert entry["rejected_journal"] == value.terminal.to_dict()
        descriptor = entry["rejected"]
        normalized = ProducerLineageRejectedTerminalV2.from_dict(descriptor)
        assert descriptor["candidate_ids"] == [item.candidate_id for item in value.journal.candidates]
        assert descriptor["rejection_manifest_sha256"] == _sha((value.batch / "rejections.json").read_bytes())
        assert descriptor["terminal_marker_sha256"] == value.terminal.terminal_marker_sha256
        assert actual["rejections"] == [{"ordinal": 0, "journal_id": value.journal.journal_id,
                                         "rejected_sha256": descriptor["descriptor_sha256"]}]
        descriptor_path = value.batch / "lineage/rejected.json"
        assert descriptor_path.read_bytes() == normalized.to_json()
        descriptor_pin = LineageSnapshotPin.from_dict(entry["rejected_file_pin"])
        verify_persisted_lineage_snapshot(descriptor_path, descriptor_pin)
        assert descriptor_pin.sha256 == _sha(descriptor_path.read_bytes())
        assert descriptor_pin.inode == descriptor_path.stat().st_ino
        expected_pins = {"journal.prepared.json", "journal.json", "rejections.json",
                         *("rejections/" + item.candidate_id + ".json" for item in value.journal.candidates)}
        assert set(entry["evidence_pins"]) == expected_pins
        for name, pin in entry["evidence_pins"].items():
            verify_persisted_lineage_snapshot(value.batch / name, LineageSnapshotPin.from_dict(pin))
        assert value.wave.state == before[2] | {"producer_publication_lineage": actual}
        assert value.owner._head == value.wave.checkpoint_sha256 != before[0]
        assert value.ledger.controller_checkpoint(value.binding.run_id) == (value.owner._head, value.wave.state)
        assert value.owner._phase == "rejected" and not value.owner._poisoned
        assert value.ledger.history(value.binding.run_id) == run_history
        assert value.ledger.get_episode(value.episode_id) == episode
        assert value.ledger.inspect_native_episode_claim(value.request, plan_sha256=value.plan.plan_sha256) == claim
        assert (value.workspace / "evolution/state.json").read_bytes() == archive_state
        assert value.controller.producer_multi_episode_publication is False
        assert value.controller.producer_known_rejection is False
        _quiet(value)


@pytest.mark.parametrize("fault", ["foreign", "subclass", "thread", "lock", "no-ack", "phase", "source", "nonce", "budget", "head", "plan"])
def test_c1_refuses_missing_original_authority_before_descriptor(tmp_path, monkeypatch, fault):
    with _waiting(tmp_path, monkeypatch, acknowledge=fault != "no-ack") as value:
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
            value.owner._phase = "staged"
        elif fault == "source":
            value.gateway.fingerprint = "foreign"
        elif fault == "nonce":
            object.__setattr__(value.wave.selected_handoff, "lease_nonce", "Z" * 32)
        elif fault == "budget":
            value.wave.budget_state["planned"]["deadline_unix"] += 1
        elif fault == "head":
            value.ledger.write_controller_checkpoint(value.binding.run_id, deepcopy(value.wave.state),
                expected_sha256=value.owner._head)
        elif fault == "plan":
            object.__setattr__(value.plan, "task_id", "foreign-task")
        before = owner_fixture._capture(value)
        history = value.ledger.controller_checkpoint_history(value.binding.run_id)
        if fault == "thread":
            errors = []
            def invoke():
                try:
                    value.owner.retain_rejected_terminal(value.terminal)
                except RSILearningError as exc:
                    errors.append(exc)
            thread = Thread(target=invoke)
            thread.start()
            thread.join(15)
            assert not thread.is_alive() and len(errors) == 1
        else:
            with pytest.raises((RSILearningError, ValueError)):
                brs._BRSLineageCheckpointOwner.retain_rejected_terminal(owner, value.terminal)
        owner_fixture._unchanged(value, before)
        assert value.ledger.controller_checkpoint_history(value.binding.run_id) == history
        assert not (value.batch / "lineage/rejected.json").exists()
        assert value.ledger.episode_result(value.episode_id) is None


@pytest.mark.parametrize("fault", ["prepared-inode", "handoff-inode", "before-inode", "snapshot-inode",
                                  "candidate-record-inode", "missing-record", "terminal-bytes", "manifest-bytes",
                                  "live-prefix", "staged-marker", "final-candidate", "prepared-terminal"])
def test_c1_refuses_missing_or_drifted_native_material_without_creating_descriptor(tmp_path, monkeypatch, fault):
    with _waiting(tmp_path, monkeypatch) as value:
        candidate = value.terminal.candidates[0].candidate_id
        if fault.endswith("inode"):
            path = {
                "prepared-inode": value.batch / "journal.prepared.json",
                "handoff-inode": value.batch / PYTHON_PRODUCER_ADMISSION_HANDOFF_NAME,
                "before-inode": value.batch / "lineage/before.json",
                "snapshot-inode": value.batch / "lineage/state-before.snapshot",
                "candidate-record-inode": value.batch / "rejections" / (candidate + ".json"),
            }[fault]
            raw, mode = path.read_bytes(), path.stat().st_mode & 0o777
            path.rename(path.with_suffix(path.suffix + ".original"))
            path.write_bytes(raw)
            path.chmod(mode)
        elif fault == "missing-record":
            path = value.batch / "rejections" / (candidate + ".json")
            path.rename(path.with_suffix(".missing"))
        elif fault == "terminal-bytes":
            path = value.batch / "journal.json"
            changed = json.loads(path.read_bytes())
            changed["terminal_marker_sha256"] = "e" * 64
            path.write_bytes(canonical_json(changed))
        elif fault == "manifest-bytes":
            path = value.batch / "rejections.json"
            path.write_bytes(path.read_bytes() + b"\n")
        elif fault == "live-prefix":
            path = value.workspace / "evolution/state.json"
            path.write_bytes(path.read_bytes() + b"\n")
        elif fault == "staged-marker":
            (value.workspace / "evolution/producer-publication.json").write_bytes(b"{}")
        elif fault == "final-candidate":
            (value.workspace / "evolution/candidates" / candidate).mkdir(parents=True)
        before = owner_fixture._capture(value)
        history = value.ledger.controller_checkpoint_history(value.binding.run_id)
        with pytest.raises((RSILearningError, ValueError)):
            value.owner.retain_rejected_terminal(value.journal if fault == "prepared-terminal" else value.terminal)
        owner_fixture._unchanged(value, before)
        assert value.ledger.controller_checkpoint_history(value.binding.run_id) == history
        assert value.owner._poisoned
        assert not (value.batch / "lineage/rejected.json").exists()
        assert value.ledger.episode_result(value.episode_id) is None


@pytest.mark.parametrize("existing", [b"", b"{}", b'{"kind":"rejected"}', "matching"])
def test_c1_never_adopts_existing_or_partial_descriptor(tmp_path, monkeypatch, existing):
    with _waiting(tmp_path, monkeypatch) as value:
        if existing == "matching":
            original = ProducerLineageBeforeIntent.from_dict(
                value.wave.state["producer_publication_lineage"]["batches"][0]["before"])
            existing = ProducerLineageRejectedTerminalV2(value.binding.run_id, value.journal.journal_id,
                value.episode_id, 0, original.digest(), value.journal.digest(), value.terminal.digest(),
                _sha((value.batch / "rejections.json").read_bytes()), value.terminal.terminal_marker_sha256,
                tuple(item.candidate_id for item in value.journal.candidates),
                original.archive.sha256, original.state.sha256).to_json()
        path = value.batch / "lineage/rejected.json"
        path.write_bytes(existing)
        path.chmod(0o600)
        before = owner_fixture._capture(value)
        original_inode = path.stat().st_ino
        with pytest.raises((RSILearningError, ValueError)):
            value.owner.retain_rejected_terminal(value.terminal)
        owner_fixture._unchanged(value, before)
        assert path.read_bytes() == existing and path.stat().st_ino == original_inode
        assert value.owner._poisoned
        assert value.ledger.episode_result(value.episode_id) is None


@pytest.mark.parametrize("fault", ["cas", "after-write", "missing-readback", "wrong-readback", "late-revision", "returned-late-revision",
                                  "post-source", "post-native-inode", "post-descriptor-inode", "post-cancel", "post-expire"])
def test_uncertain_c1_write_retains_files_original_cursors_and_no_retry(tmp_path, monkeypatch, fault):
    with _waiting(tmp_path, monkeypatch) as value:
        before = owner_fixture._capture(value)
        write, read = value.ledger.write_controller_checkpoint, value.ledger.controller_checkpoint
        calls, durable = [], []

        def observed(run_id, state, *, expected_sha256):
            assert get_ident() == value.owner_thread
            assert not staging._HELD_PUBLICATION_LOCKS.get()
            calls.append((expected_sha256, deepcopy(state)))
            if fault == "cas":
                raise RSILearningError("fixture_c1_cas_failed")
            head = write(run_id, state, expected_sha256=expected_sha256)
            durable.append((head, deepcopy(state)))
            if fault == "after-write":
                raise RSILearningError("fixture_c1_write_ack_lost")
            if fault in {"late-revision", "returned-late-revision"}:
                latest = write(run_id, deepcopy(state), expected_sha256=head)
                durable.append((latest, deepcopy(state)))
                if fault == "returned-late-revision":
                    return latest
            elif fault == "post-source":
                value.gateway.fingerprint = "foreign-after-write"
            elif fault in {"post-native-inode", "post-descriptor-inode"}:
                path = value.batch / ("rejections.json" if fault == "post-native-inode" else "lineage/rejected.json")
                raw = path.read_bytes()
                path.rename(path.with_suffix(".held-original"))
                path.write_bytes(raw)
                path.chmod(0o600)
            elif fault == "post-cancel":
                value.control.cancel()
            elif fault == "post-expire":
                value.control.deadline = time.monotonic() - 1
            return head

        def invalid(run_id):
            if durable and fault == "missing-readback":
                return None
            if durable and fault == "wrong-readback":
                return durable[-1][0], {"wrong": True}
            return read(run_id)

        monkeypatch.setattr(value.ledger, "write_controller_checkpoint", observed)
        monkeypatch.setattr(value.ledger, "controller_checkpoint", invalid)
        with pytest.raises((RSILearningError, ValueError, SolveExecutionCancelled, SolveExecutionBudgetExceeded)):
            value.owner.retain_rejected_terminal(value.terminal)
        owner_fixture._unchanged(value, before)
        assert len(calls) == 1 and value.owner._poisoned
        path = value.batch / "lineage/rejected.json"
        retained = path.read_bytes()
        assert json.loads(retained)["kind"] == "rejected"
        assert value.owner._phase == "prepared-evidence"
        assert value.owner._head == before[0]
        assert read(value.binding.run_id) == (durable[-1] if durable else (before[0], before[2]))
        with pytest.raises((RSILearningError, ValueError)):
            value.owner.retain_rejected_terminal(value.terminal)
        assert len(calls) == 1 and path.read_bytes() == retained
        assert value.ledger.episode_result(value.episode_id) is None


@pytest.mark.parametrize("fault", ["source", "native-context", "retained-file-inode", "candidate-record-inode",
                                  "manifest-inode", "descriptor-inode", "deadline-nan", "deadline-inf",
                                  "deadline-later", "equal-filepin-replacement", "final-reader-shadow"])
def test_first_c1_readback_drift_never_advances_original_capture(tmp_path, monkeypatch, fault):
    with _waiting(tmp_path, monkeypatch) as value:
        before = owner_fixture._capture(value)
        write, read = value.ledger.write_controller_checkpoint, value.ledger.controller_checkpoint
        durable, injected = [], []
        if fault == "final-reader-shadow":
            original_source = value.gateway.rsi_fingerprint_config()
            original_material = _native_material_snapshot(value)

        def observed(run_id, state, *, expected_sha256):
            head = write(run_id, state, expected_sha256=expected_sha256)
            durable.append((head, deepcopy(state)))
            return head

        def first_readback(run_id):
            actual = read(run_id)
            if durable and not injected:
                injected.append(fault)
                if fault == "source":
                    value.gateway.fingerprint = "foreign-on-first-c1-readback"
                elif fault == "native-context":
                    object.__setattr__(value.native, "strategy", object())
                elif fault.startswith("deadline-"):
                    value.owner._rejection_deadline = {
                        "deadline-nan": float("nan"), "deadline-inf": float("inf"),
                        "deadline-later": value.owner._rejection_deadline + 60,
                    }[fault]
                elif fault == "equal-filepin-replacement":
                    value.owner._rejection_file_pin = replace(value.owner._rejection_file_pin)
                elif fault == "final-reader-shadow":
                    # Leave source and native material intact. The retained
                    # instance observer alone must fail the final canonical gate.
                    pass
                else:
                    candidate = value.terminal.candidates[0].candidate_id
                    record = value.batch / "rejections" / (candidate + ".json")
                    if fault == "retained-file-inode":
                        table = json.loads(record.read_bytes())["retained_evidence"]["entries"]
                        entry = next(item for item in table if item["kind"] == "file" and item["path"].endswith("/plan.json"))
                        path = value.workspace / entry["path"]
                    else:
                        path = {"candidate-record-inode": record,
                                "manifest-inode": value.batch / "rejections.json",
                                "descriptor-inode": value.batch / "lineage/rejected.json"}[fault]
                    raw, mode = path.read_bytes(), path.stat().st_mode & 0o777
                    path.rename(path.with_suffix(path.suffix + ".before-readback"))
                    path.write_bytes(raw)
                    path.chmod(mode)
            return actual

        monkeypatch.setattr(value.ledger, "write_controller_checkpoint", observed)
        monkeypatch.setattr(value.ledger, "controller_checkpoint", first_readback)
        with pytest.raises((RSILearningError, ValueError, SolveExecutionCancelled,
                            SolveExecutionBudgetExceeded)) as refused:
            value.owner.retain_rejected_terminal(value.terminal)
        if fault == "final-reader-shadow":
            assert str(refused.value) == "rsi_brs_publication_lineage_rejected_final_reader_drift"
            assert value.gateway.rsi_fingerprint_config() == original_source
            assert _native_material_snapshot(value) == original_material
        assert injected == [fault] and len(durable) == 1
        owner_fixture._unchanged(value, before)
        assert value.owner._poisoned and value.owner._phase == "prepared-evidence"
        assert read(value.binding.run_id) == durable[0]
        assert (value.batch / "lineage/rejected.json").is_file()
        assert value.ledger.episode_result(value.episode_id) is None


def test_rejected_wire_and_repeated_c1_cannot_grant_owner_scope(tmp_path, monkeypatch):
    with _waiting(tmp_path, monkeypatch) as value:
        before = owner_fixture._capture(value)
        wire = deepcopy(value.wave.state["producer_publication_lineage"])
        with pytest.raises((RSILearningError, ValueError)):
            value.owner.checkpoint_rejected(wire)
        owner_fixture._unchanged(value, before)
        assert not (value.batch / "lineage/rejected.json").exists()
        assert value.owner._poisoned


def test_successful_c1_cannot_repeat_retain_or_checkpoint(tmp_path, monkeypatch):
    with _waiting(tmp_path, monkeypatch) as value:
        value.owner.retain_rejected_terminal(value.terminal)
        before = owner_fixture._capture(value)
        history = value.ledger.controller_checkpoint_history(value.binding.run_id)
        for operation in (lambda: value.owner.retain_rejected_terminal(value.terminal),
                          lambda: value.owner.checkpoint_rejected(deepcopy(value.wave.state["producer_publication_lineage"]))):
            with pytest.raises((RSILearningError, ValueError)):
                operation()
            owner_fixture._unchanged(value, before)
            assert value.ledger.controller_checkpoint_history(value.binding.run_id) == history
        _quiet(value)


def test_final_c1_readback_refuses_history_observer_shadow_before_invocation(tmp_path, monkeypatch):
    from lunar_evolution.rsi_brs_rejection_owner import _rejection_final_readback

    with _waiting(tmp_path, monkeypatch) as value:
        before = owner_fixture._capture(value)
        calls = []

        def replacement(*_args, **_kwargs):
            calls.append("unexpected-instance-reader")
            raise AssertionError("final C1 readback invoked a shadow")

        with monkeypatch.context() as changed:
            changed.setattr(value.ledger, "_controller_checkpoint_history_observation_tx", replacement)
            with pytest.raises(RSILearningError, match="^rsi_brs_publication_lineage_rejected_final_reader_drift$"):
                _rejection_final_readback(value.owner, "a" * 64, {}, b"{}")
        assert calls == []
        owner_fixture._unchanged(value, before)
        _quiet(value)
