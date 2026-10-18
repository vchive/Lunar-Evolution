"""Controller wiring uses retained synthetic process observations, never real workers.

Native process/receipt observation and the lowest candidate/evaluator process
boundary are inert seams. Native output capture, prepared/admission/publication,
receipt mapping, RSI recover, result store and independent verifier stay real.
This accepts controller wiring only; bootstrap/source/lifecycle remains unaccepted.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import stat
import subprocess
import tempfile
import time
from dataclasses import replace
from pathlib import Path

import pytest
import test_rsi_python_scheduler_inputs as input_fixture
from test_bundle_population import build_context
from test_producer_bundle_transaction import (
    _formal_execution_receipt,
    _initialize_native_population,
)
from test_producer_python_runtime import _inventory
from test_rsi_producer_gateway import _fixture
from test_rsi_producer_staging_controller import ObservedAttestations, _run

from lunar_evolution import (
    RSILearningController,
    RSILearningError,
    candidate_evaluation,
    candidate_execution_runner,
    fixture_solver_gateway,
    native_trusted_output,
    native_trusted_scheduler,
)
from lunar_evolution.automatic_solve_lifecycle import SolveExecutionControl
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.evolution import PopulationStrategy
from lunar_evolution.native_trusted_attempt import NativeTrustedAttemptObservation
from lunar_evolution.native_trusted_capture import capture_native_trusted_output
from lunar_evolution.producer_broker_ipc import ProducerBrokerObservation
from lunar_evolution.producer_handoff import producer_materials_sha256
from lunar_evolution.producer_process import _digest_without, parse_producer_execution_receipt
from lunar_evolution.producer_request_transport import (
    HostRequestJournal,
    HostRequestJournalIdentity,
    read_host_request_journal,
)
from lunar_evolution.python_producer_admission_handoff import (
    build_python_producer_admission_handoff,
    persist_python_producer_admission_handoff_pinned,
)
from lunar_evolution.rsi_child_gateway import resolve_python_producer_episode_gateway
from lunar_evolution.rsi_gateway import SolverRequest
from lunar_evolution.rsi_learning import MemorySnapshot
from lunar_evolution.rsi_native_plan import NativeRSIExecutionPlan
from lunar_evolution.rsi_producer_gateway import (
    PythonProducerRSIExecutionConfig,
    PythonProducerRSISolverGateway,
)
from lunar_evolution.rsi_producer_launch import (
    PythonProducerEpisodeStager,
    PythonProducerEpisodeStagingConfig,
)
from lunar_evolution.rsi_python_scheduler_inputs import PythonRSISchedulerInputContext


class _Crash(BaseException):
    """Simulate owner-stack loss without allowing exception settlement."""


@pytest.fixture(autouse=True)
def _inert_process_boundary(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("child execution fixture must never launch a subprocess")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)


@pytest.fixture
def tmp_path():
    """Keep retained binding paths short without changing production wire caps."""
    # The binding deliberately retains absolute runtime paths.  The reserved
    # policy graph can therefore make the normal pytest base directory exceed
    # the unchanged 32 KiB staging limit.  Use a short real directory so this
    # fixture exercises the same cap without weakening it.  Avoid /tmp's
    # symlink on macOS because process-boundary readers reject symlink parents.
    parent = next(
        str(candidate)
        for candidate in (Path("/private/tmp"), Path("/var/tmp"), Path("/tmp"))
        if candidate.is_dir() and not candidate.is_symlink()
    )
    with tempfile.TemporaryDirectory(prefix="lce-", dir=parent) as directory:
        yield Path(directory)


def _controller(value, supplier=None, *, execution=True, gateway=None, stager=True):
    supplier = supplier or ObservedAttestations(value.ledger)
    configured = PythonProducerEpisodeStagingConfig(
        workspace=value.root, root_sidecar=value.sidecar,
        artifact=value.native.artifact, attestation_supplier=supplier,
    )
    controller = RSILearningController(
        gateway or value.gateway, ledger=value.ledger,
        producer_sidecar=value.sidecar, producer_workspace=value.root,
        producer_stager=PythonProducerEpisodeStager(configured) if stager else None,
        producer_child_execution=execution,
    )
    return controller, supplier


def _child(value):
    checkpoint = value.ledger.controller_checkpoint(value.binding.run_id)
    state = checkpoint[1]
    episode_id = state["current_episode_id"]
    entry = state["producer_episode_staging"][episode_id]
    request = SolverRequest.from_dict(entry["identity"]["intent"]["request"])
    memory = MemorySnapshot.from_dict(entry["identity"]["memory"])
    plan = NativeRSIExecutionPlan.from_dict(entry["ready"]["plan"])
    claim = value.ledger.inspect_native_episode_claim(request, plan_sha256=plan.plan_sha256)
    return state, entry, request, memory, plan, claim


def _claims(value):
    with sqlite3.connect(value.ledger.database) as connection:
        return connection.execute("SELECT episode_id FROM rsi_native_episode_claims").fetchall()


class _InertNativeObservation:
    """Retain synthetic observations with independent original inode/byte pins."""

    def __init__(self):
        self.pins = {}
        self.receipts = {}
        self.attempts = []
        self.controller = None
        self.handoffs = []

    def rsi_fingerprint_config(self):
        return {"fixture": "retained-inert-native-observation-v1"}

    def source_bytes(self, intent):
        return b"# Inert candidate source; never executed.\n"

    def _write(self, path, payload):
        raw = canonical_json(payload)
        with path.open("xb") as stream:
            stream.write(raw)
        path.chmod(0o600)
        self.pins[path] = (self._identity(path), raw)
        return payload

    @staticmethod
    def _identity(path):
        info = path.lstat()
        assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1
        return (
            info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns,
        )

    def _read(self, path):
        identity, raw = self.pins[path]
        assert self._identity(path) == identity
        assert path.read_bytes() == raw
        return json.loads(raw)

    def attempt(self, workspace, *, intent, attestation, **_kwargs):
        self.attempts.append(intent)
        assert self.controller.ledger.controller_lock_held(intent.run_id)
        assert self.controller.ledger.get_episode(intent.task_id).state == "running"
        batch = Path(workspace) / "evolution" / "producer-batches" / intent.journal_id
        output = batch / intent.output_directory
        (output / "solve").mkdir(parents=True)
        source = self.source_bytes(intent)
        (output / "solve/main.py").write_bytes(source)
        envelope = {
            "schema_version": "1", "producer_id": intent.producer_id,
            "producer_fingerprint": intent.producer_fingerprint,
            "status": "completed", "contract_sha256": intent.contract_sha256,
            "budget": {"requests": 0}, "materials": [{
                "kind": "candidate_source", "path": "solve/main.py", "size": len(source),
                "sha256": hashlib.sha256(source).hexdigest(),
            }],
        }
        self._write(batch / intent.envelope_path, envelope)
        terminal = {
            "protocol": "lunar-native-trusted-process-terminal-v1",
            "process_status": "exited_zero", "cleanup_status": "cleaned",
            "gate_released": True, "target_started": True, "exit_code": 0,
            "intent_sha256": intent.digest(), "attestation_sha256": attestation.digest(),
        }
        terminal["terminal_sha256"] = _digest_without(terminal, "terminal_sha256")
        self._write(batch / "native-trusted-process-terminal.json", terminal)
        broker_root = batch / ".host-request-journal"
        broker_root.mkdir(mode=0o700)
        identity = HostRequestJournalIdentity(wall_deadline_ns=time.monotonic_ns() + 10_000_000_000, **{
            field: getattr(intent, field) for field in (
                "launch_id", "journal_id", "run_id", "parent_task_id", "task_id",
                "intent_sha256", "request_timeout_seconds", "max_requests",
            )
        })
        with HostRequestJournal.create(broker_root / "requests", identity):
            pass
        retained = read_host_request_journal(broker_root / "requests", expected_identity=identity)
        broker = ProducerBrokerObservation(
            retained.snapshot, broker_root / "requests", identity,
            retained.journal_sha256, retained.journal_bytes, True, "inert-no-requests",
            retained.journal_file_identity,
        )
        capture = capture_native_trusted_output(
            batch, intent=intent, terminal_sha256=terminal["terminal_sha256"],
            broker=broker, deadline=time.monotonic() + 10,
        )
        receipt = _formal_execution_receipt(
            journal_id=intent.journal_id, run_id=intent.run_id,
            parent_task_id=intent.parent_task_id, task_id=intent.task_id,
        )
        receipt.update(**{
            field: getattr(intent, field) for field in (
                "launch_id", "request_timeout_seconds", "max_requests",
                "output_max_bytes", "wall_timeout_seconds",
            )
        }, intent_sha256=intent.digest(), attestation_sha256=attestation.digest())
        receipt["trusted_execution"].update(
            terminal_sha256=terminal["terminal_sha256"],
            output_capture_sha256=capture["capture_sha256"],
            broker_journal_identity=identity.to_dict(),
            broker_journal_sha256=retained.journal_sha256,
            broker_journal_bytes=retained.journal_bytes,
            broker_journal_file_identity=list(retained.journal_file_identity),
        )
        receipt["receipt_sha256"] = _digest_without(receipt, "receipt_sha256")
        self.receipts[intent.journal_id] = receipt
        return NativeTrustedAttemptObservation(
            launch_id=intent.launch_id, journal_id=intent.journal_id,
            status="recovery_required", reason="native_trusted_attempt_request_and_output_unverified",
            registration_sha256=receipt["registration_sha256"], gate_released=True,
            target_started=True, exit_code=0, cleanup_status="cleaned",
            terminal_sha256=terminal["terminal_sha256"], output_capture_sha256=capture["capture_sha256"],
        )

    def terminal(self, workspace, *, intent, attestation, **_kwargs):
        batch = Path(workspace) / "evolution" / "producer-batches" / intent.journal_id
        terminal = self._read(batch / "native-trusted-process-terminal.json")
        assert terminal["intent_sha256"] == intent.digest()
        assert terminal["attestation_sha256"] == attestation.digest()
        return terminal

    def persist_receipt(self, workspace, *, intent, attestation, **kwargs):
        self.terminal(workspace, intent=intent, attestation=attestation)
        batch = Path(workspace) / "evolution" / "producer-batches" / intent.journal_id
        self._write(batch / "execution-receipt.json", self.receipts[intent.journal_id])
        return self.recover_receipt(workspace, intent=intent, attestation=attestation, **kwargs)

    def recover_receipt(self, workspace, *, intent, attestation, **_kwargs):
        self.terminal(workspace, intent=intent, attestation=attestation)
        batch = Path(workspace) / "evolution" / "producer-batches" / intent.journal_id
        observed = self._read(batch / "execution-receipt.json")
        assert observed == self.receipts[intent.journal_id]
        assert observed["intent_sha256"] == intent.digest()
        assert observed["attestation_sha256"] == attestation.digest()
        return parse_producer_execution_receipt(observed)

    def __call__(self, receipt, output):
        controller = self.controller
        sidecar, proof = controller._python_admission_sidecar(receipt.run_id, receipt.task_id)
        binding = sidecar.binding
        fields = {
            "run_id": binding.run_id, "journal_id": binding.intent.journal_id,
            "parent_task_id": binding.parent_task_id, "task_id": binding.task_id,
            "binding_sha256": binding.binding_sha256, "sidecar_raw_sha256": sidecar.raw_sha256,
            "sidecar_pin_sha256": hashlib.sha256(canonical_json(dict(proof.sidecar_pin))).hexdigest(),
            "launch_intent_sha256": binding.intent_sha256,
            "attestation_sha256": binding.attestation_sha256,
            "runtime_manifest_sha256": binding.runtime_manifest_sha256,
            "runtime_tree_sha256": binding.runtime_tree_sha256,
            "executable_owner_sha256": "a" * 64,
            "native_execution_receipt_sha256": receipt.receipt_sha256,
            "terminal_sha256": output.process_terminal_sha256,
            "runtime_observation_sha256": "a" * 64,
            "broker_transcript_sha256": receipt.trusted_execution["broker_journal_sha256"],
            # Admission pins the semantic envelope digest.  The hash of the
            # retained output bytes is independent capture evidence and is
            # already carried by the native receipt; it must not be reused as
            # the envelope identity.
            "envelope_sha256": output.envelope.envelope_sha256,
            "materials_sha256": producer_materials_sha256(output.envelope),
            "contract_sha256": binding.contract_sha256,
            "evaluator_sha256": binding.evaluator_fingerprint,
            "runner_sha256": binding.intent.runner_fingerprint,
            "dependency_sha256": binding.dependency_sha256,
            "environment_sha256": binding.environment_sha256,
            "admission_plan_sha256": output.admission_plan.digest(),
            "request_budget": binding.request_budget,
            "wall_timeout_seconds": binding.wall_timeout_seconds,
            "deadline_unix": binding.deadline_unix,
        }
        handoff = build_python_producer_admission_handoff(**fields)
        batch = controller.producer_workspace / "evolution" / "producer-batches" / receipt.journal_id
        retained = persist_python_producer_admission_handoff_pinned(batch, handoff=handoff)
        assert retained.handoff.envelope_sha256 == output.envelope.envelope_sha256
        assert retained.handoff.materials_sha256 == producer_materials_sha256(output.envelope)
        self.handoffs.append(retained)
        return retained


def _inert_candidate_process(command, *, cwd, process_observer=None, process_released=None,
                             process_exit_observed=None, continuation_guard=None, **_kwargs):
    """Keep original runner/evaluator persistence around a never-started process."""
    if continuation_guard is not None:
        continuation_guard()
    if process_observer is not None:
        process_observer(4242, 4242)
    root = Path(cwd)
    if "evaluator.py" in command:
        assert json.loads((root / "output/result.json").read_bytes()) == {"value": 9}
        stdout = canonical_json({
            "schema_version": "1", "evaluator_id": "bundle-population-fixture",
            "validity": 1, "quality": 9.0, "combined_score": 9.0,
            "detailed_scores": {}, "error_info": [],
        })
    else:
        (root / "output").mkdir(exist_ok=True)
        (root / "output/result.json").write_bytes(canonical_json({"value": 9}))
        stdout = b""
    if process_exit_observed is not None:
        process_exit_observed(0)
    if process_released is not None:
        process_released(4242, 4242)
    if continuation_guard is not None:
        continuation_guard()
    return stdout, b"", "succeeded", 0, None


def _successful_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(candidate_execution_runner, "_bounded_process_bytes", _inert_candidate_process)
    monkeypatch.setattr(candidate_evaluation, "_bounded_process_bytes", _inert_candidate_process)
    context = build_context(tmp_path / "evaluation")
    original_python_fixture = input_fixture.python_fixture

    def python_fixture(root):
        manifest, tree, intent, attestation, budget = original_python_fixture(root)
        intent = replace(intent, **{
            field: getattr(context.config, field) for field in (
                "evaluator_kind", "evaluator_fingerprint", "runner_fingerprint",
                "dependency_sha256", "environment_sha256",
            )
        }, intent_sha256=None)
        intent = replace(intent, intent_sha256=intent.digest())
        return manifest, tree, intent, attestation, budget

    with monkeypatch.context() as patch:
        patch.setattr(input_fixture, "_contract", lambda: context.contract.to_dict())
        patch.setattr(input_fixture, "python_fixture", python_fixture)
        value = _fixture(tmp_path, monkeypatch)
    strategy = PopulationStrategy(replace(context, workspace=value.root))
    _initialize_native_population(strategy)
    observation = _InertNativeObservation()
    value.native = replace(value.native, strategy=strategy, python_handoff_after_execution=observation)
    value.context = PythonRSISchedulerInputContext(value.native, value.sidecar, value.proof)
    value.config = PythonProducerRSIExecutionConfig(value.request.solver_id, value.ledger, value.context)
    value.gateway = PythonProducerRSISolverGateway(value.config)
    monkeypatch.setattr(native_trusted_scheduler, "run_native_trusted_attempt", observation.attempt)
    monkeypatch.setattr(native_trusted_scheduler, "persist_native_trusted_execution_receipt", observation.persist_receipt)
    monkeypatch.setattr(native_trusted_scheduler, "recover_native_trusted_execution_receipt", observation.recover_receipt)
    monkeypatch.setattr(native_trusted_output, "recover_native_trusted_attempt", observation.terminal)
    monkeypatch.setattr(native_trusted_output, "recover_native_trusted_execution_receipt", observation.recover_receipt)
    controller, supplier = _controller(value)
    observation.controller = controller
    return value, controller, supplier, observation


def test_single_child_completes_original_publication_mapper_verifier_and_readonly_recovery(
    tmp_path, monkeypatch,
):
    value, controller, supplier, observation = _successful_fixture(tmp_path, monkeypatch)
    root_gateway, root_sidecar = controller.gateway, controller.producer_sidecar
    result = _run(controller, value)
    assert result.status == "completed"
    state, entry, request, _memory, _plan, claim = _child(value)
    assert entry["state"] == "ready"
    assert claim.status == "completed"
    episode = value.ledger.get_episode(request.episode_id)
    assert episode.state == "completed"
    assert episode.payload["verifier"]["outcome"] == "pass"
    saved_request, saved_result = value.ledger.episode_result(request.episode_id)
    assert saved_request == request and saved_result.status == "completed"
    assert saved_result.official_evaluation_receipt_sha256
    batch = value.root / "evolution" / "producer-batches" / entry["identity"]["journal_id"]
    assert (value.root / "evolution" / "producer-batches" / "journal-1" / "python-producer-binding.json").stat().st_size < 32 * 1024
    assert (batch / "python-producer-binding.json").stat().st_size < 32 * 1024
    publication = json.loads((batch / "journal.published.json").read_bytes())
    assert publication["state"] == "published"
    slot = publication["candidates"][0]
    evaluation_path = value.root / "evolution" / "candidates" / slot["candidate_id"] / "solve" / "evaluation-receipt.json"
    evaluation = json.loads(evaluation_path.read_bytes())
    assert evaluation["python_handoff_sha256"] == publication["python_handoff_sha256"]
    assert evaluation["receipt_sha256"] == slot["evaluation_receipt_sha256"]
    assert (batch / "journal.prepared.json").is_file()
    assert (batch / "python-producer-admission-anchor.json").is_file()
    assert len(observation.attempts) == len(observation.handoffs) == len(supplier.observations) == 1
    assert controller.gateway is root_gateway and controller.producer_sidecar is root_sidecar
    assert state["budget_state"]["consumed"]["solver_invocations"] == 1
    assert controller.producer_child_execution is True
    assert root_gateway.production_admission is False
    before = _inventory(value.root)
    history = value.ledger.controller_checkpoint_history(value.binding.run_id)
    restarted, _ = _controller(value, supplier)
    reopened = restarted.resume(value.binding.run_id)
    assert reopened == result
    assert value.ledger.controller_checkpoint_history(value.binding.run_id) == history
    assert _inventory(value.root) == before
    assert len(observation.attempts) == len(observation.handoffs) == len(supplier.observations) == 1
    handoff_path = batch / "python-producer-admission-handoff.json"
    handoff = json.loads(handoff_path.read_bytes())
    handoff["native_execution_receipt_sha256"] = "0" * 64
    handoff_path.write_bytes(canonical_json(handoff))
    after_manual_change = _inventory(value.root)
    run_history = value.ledger.history(value.binding.run_id)
    with pytest.raises(RSILearningError):
        restarted.resume(value.binding.run_id)
    assert _inventory(value.root) == after_manual_change
    assert value.ledger.history(value.binding.run_id) == run_history
    assert value.ledger.controller_checkpoint_history(value.binding.run_id) == history
    assert len(observation.attempts) == len(observation.handoffs) == len(supplier.observations) == 1


@pytest.mark.parametrize("result_is_durable", [False, True])
def test_publication_owner_loss_preserves_evidence_without_second_dispatch(
    tmp_path, monkeypatch, result_is_durable,
):
    value, controller, supplier, observation = _successful_fixture(tmp_path, monkeypatch)
    original_publish = value.ledger.publish_native_episode_result
    mapped_results = []

    def interrupted(request, **kwargs):
        mapped_results.append(kwargs["result"])
        if result_is_durable:
            original_publish(request, **kwargs)
        raise _Crash("actual publication is durable; owner settlement was interrupted")

    with monkeypatch.context() as patch:
        # Crash injection preserves the real mapper/publication and, for the
        # durable-result case, the original atomic result writer before exiting.
        patch.setattr(value.ledger, "publish_native_episode_result", interrupted)
        with pytest.raises(_Crash):
            _run(controller, value)
    state, entry, request, memory, plan, claim = _child(value)
    assert claim.status == ("completed" if result_is_durable else "started")
    assert value.ledger.get_episode(request.episode_id).state == "running"
    saved = value.ledger.episode_result(request.episode_id)
    assert saved == ((request, mapped_results[0]) if result_is_durable else None)
    batch = value.root / "evolution" / "producer-batches" / entry["identity"]["journal_id"]
    publication_bytes = (batch / "journal.published.json").read_bytes()
    assert json.loads(publication_bytes)["state"] == "published"
    assert (batch / "journal.prepared.json").is_file()
    assert (batch / "native-rsi.provenance.json").is_file()
    assert len(observation.attempts) == len(observation.handoffs) == len(supplier.observations) == 1
    consumed = dict(state["budget_state"]["consumed"])
    assert consumed["solver_invocations"] == 1
    restarted, _ = _controller(value, supplier)
    before = _inventory(value.root)
    history = value.ledger.controller_checkpoint_history(value.binding.run_id)
    run_history = value.ledger.history(value.binding.run_id)
    child = resolve_python_producer_episode_gateway(restarted, request, memory)
    bundle = child.config.receipt_provider.recover(request, plan)
    assert child._map_outcome(request, plan, bundle) == mapped_results[0]
    if result_is_durable:
        assert child.validate_replay(request, memory, saved[1]) == saved[1]
    else:
        with pytest.raises(RSILearningError, match="recovery_required"):
            child.validate_replay(request, memory, mapped_results[0])
    assert _inventory(value.root) == before
    assert value.ledger.controller_checkpoint_history(value.binding.run_id) == history
    assert value.ledger.history(value.binding.run_id) == run_history
    if not result_is_durable:
        with pytest.raises(RSILearningError, match="reconcile_required"):
            restarted.resume(value.binding.run_id)
        assert _inventory(value.root) == before
        assert value.ledger.controller_checkpoint_history(value.binding.run_id) == history
        assert value.ledger.history(value.binding.run_id) == run_history
        assert _child(value)[-1] == claim
    else:
        # RSI may finish its original settlement/verification from the durable
        # result. The native process and publication reader remain read-only.
        result = restarted.resume(value.binding.run_id)
        assert result.status == "completed"
        recovered_state, recovered_entry, *_ = _child(value)
        assert recovered_entry == entry
        assert recovered_state["budget_state"]["consumed"] == consumed
        assert value.ledger.get_episode(request.episode_id).payload["verifier"]["outcome"] == "pass"
        assert value.ledger.episode_result(request.episode_id) == saved
        settled_inventory = _inventory(value.root)
        settled_history = value.ledger.controller_checkpoint_history(value.binding.run_id)
        settled_run_history = value.ledger.history(value.binding.run_id)
        assert restarted.resume(value.binding.run_id) == result
        assert _inventory(value.root) == settled_inventory
        assert value.ledger.controller_checkpoint_history(value.binding.run_id) == settled_history
        assert value.ledger.history(value.binding.run_id) == settled_run_history
    assert (batch / "journal.published.json").read_bytes() == publication_bytes
    assert len(mapped_results) == len(observation.attempts) == len(observation.handoffs) == len(supplier.observations) == 1


@pytest.mark.parametrize("configuration", ["no-stager", "fixture-gateway"])
def test_execution_requires_exact_root_gateway_and_stager_before_any_effect(
    tmp_path, monkeypatch, configuration,
):
    value = _fixture(tmp_path, monkeypatch)
    before = _inventory(value.root)
    with pytest.raises(RSILearningError):
        _controller(
            value, stager=configuration != "no-stager",
            gateway=fixture_solver_gateway(value.request.solver_id)
            if configuration == "fixture-gateway" else None,
        )
    assert value.ledger.get_run(value.binding.run_id) is None
    assert _claims(value) == []
    assert _inventory(value.root) == before


def test_default_staging_mode_retains_dispatch_refusal(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    controller, supplier = _controller(value, execution=False)
    with pytest.raises(RSILearningError, match="dispatch_not_accepted"):
        _run(controller, value)
    state, entry, request, _memory, _plan, claim = _child(value)
    assert entry["state"] == "ready"
    assert claim is None
    assert value.ledger.get_episode(request.episode_id) is None
    assert state["budget_state"]["consumed"]["solver_invocations"] == 1
    assert len(supplier.observations) == 1


@pytest.mark.parametrize("stopped", ["cancelled", "expired"])
def test_original_child_control_stop_refuses_before_claim_and_running(tmp_path, monkeypatch, stopped):
    value = _fixture(tmp_path, monkeypatch)
    ticks = [100.0]
    control = SolveExecutionControl(20, clock=lambda: ticks[0])
    value.native = replace(value.native, execution_control=control)
    value.context = PythonRSISchedulerInputContext(value.native, value.sidecar, value.proof)
    value.config = PythonProducerRSIExecutionConfig(value.request.solver_id, value.ledger, value.context)
    value.gateway = PythonProducerRSISolverGateway(value.config)
    controller, supplier = _controller(value)
    if stopped == "cancelled":
        control.cancel()
    else:
        ticks[0] = control.deadline
    with pytest.raises(RSILearningError) as caught:
        _run(controller, value)
    codes = []
    cause = caught.value
    while cause is not None:
        codes.append(str(cause))
        cause = cause.__cause__
    assert "rsi_native_scheduler_preclaim_" + (
        "cancelled" if stopped == "cancelled" else "deadline_expired"
    ) in codes
    _state, entry, request, _memory, _plan, claim = _child(value)
    assert entry["state"] == "ready"
    assert claim is None and _claims(value) == []
    assert value.ledger.get_episode(request.episode_id) is None
    assert value.ledger.episode_result(request.episode_id) is None
    assert len(supplier.observations) == 1
    before = _inventory(value.root)
    history = value.ledger.controller_checkpoint_history(value.binding.run_id)
    restarted, _ = _controller(value, supplier)
    with pytest.raises(RSILearningError):
        restarted.resume(value.binding.run_id)
    assert _inventory(value.root) == before
    assert value.ledger.controller_checkpoint_history(value.binding.run_id) == history
    assert len(supplier.observations) == 1


def test_provider_interruption_retains_started_claim_and_never_relaunches(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    controller, supplier = _controller(value)
    root_gateway, root_sidecar = controller.gateway, controller.producer_sidecar
    root_inputs = root_gateway.producer_config.inputs
    attempts = []

    def interrupted(_workspace, **kwargs):
        attempts.append(kwargs["intent"])
        assert value.ledger.controller_lock_held(value.binding.run_id)
        episode = value.ledger.get_episode(kwargs["intent"].task_id)
        assert episode is not None and episode.state == "running"
        assert kwargs["intent"].journal_id != value.binding.intent.journal_id
        raise OSError("inert process observation lost before spawn")

    monkeypatch.setattr(native_trusted_scheduler, "run_native_trusted_attempt", interrupted)
    with pytest.raises(RSILearningError, match="attempt_unknown"):
        _run(controller, value)
    state, entry, request, _memory, _plan, claim = _child(value)
    assert entry["state"] == "ready"
    assert claim.status == "started"
    assert value.ledger.episode_result(request.episode_id) is None
    assert len(attempts) == len(supplier.observations) == 1
    assert state["budget_state"]["consumed"]["solver_invocations"] == 1
    assert controller.gateway is root_gateway
    assert controller.producer_sidecar is root_sidecar
    assert root_gateway.producer_config.inputs is root_inputs
    assert root_inputs.original_producer_checkpoint == value.proof
    history = value.ledger.history(value.binding.run_id)
    checkpoint_history = value.ledger.controller_checkpoint_history(value.binding.run_id)
    before = _inventory(value.root)
    restarted, _ = _controller(value, supplier)
    with pytest.raises(RSILearningError):
        restarted.resume(value.binding.run_id)
    assert value.ledger.controller_checkpoint_history(value.binding.run_id) == checkpoint_history
    assert value.ledger.history(value.binding.run_id) == history
    assert _inventory(value.root) == before
    assert _child(value)[-1] == claim
    assert len(attempts) == len(supplier.observations) == 1


def test_ready_readback_after_owner_loss_cannot_mint_a_claim(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    controller, supplier = _controller(value)
    claims = []

    def lose_owner_before_claim(*_args, **_kwargs):
        claims.append(True)
        raise _Crash("ready is durable, but owner continuation is gone")

    with monkeypatch.context() as patch:
        patch.setattr(value.ledger, "claim_native_episode", lose_owner_before_claim)
        with pytest.raises(_Crash):
            _run(controller, value)
    _state, entry, request, _memory, _plan, claim = _child(value)
    assert entry["state"] == "ready" and claim is None
    assert value.ledger.get_episode(request.episode_id) is None
    before = _inventory(value.root)
    history = value.ledger.controller_checkpoint_history(value.binding.run_id)
    restarted, _ = _controller(value, supplier)
    with pytest.raises(RSILearningError):
        restarted.resume(value.binding.run_id)
    assert _inventory(value.root) == before
    assert value.ledger.controller_checkpoint_history(value.binding.run_id) == history
    assert _child(value)[-1] is None
    assert len(claims) == len(supplier.observations) == 1


def test_started_claim_without_running_head_is_recovery_only(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    controller, supplier = _controller(value)
    running = []

    def lose_owner_before_running(_episode):
        running.append(True)
        raise _Crash("claim is durable, but running head was not written")

    with monkeypatch.context() as patch:
        patch.setattr(value.ledger, "create_episode_record", lose_owner_before_running)
        with pytest.raises(_Crash):
            _run(controller, value)
    state, _entry, request, _memory, _plan, claim = _child(value)
    assert claim.status == "started"
    assert value.ledger.get_episode(request.episode_id) is None
    assert value.ledger.episode_result(request.episode_id) is None
    before = _inventory(value.root)
    history = value.ledger.controller_checkpoint_history(value.binding.run_id)
    restarted, _ = _controller(value, supplier)
    with pytest.raises(RSILearningError):
        restarted.resume(value.binding.run_id)
    assert value.ledger.controller_checkpoint_history(value.binding.run_id) == history
    assert _inventory(value.root) == before
    assert _child(value)[-1] == claim
    assert state["budget_state"]["consumed"]["solver_invocations"] == 1
    assert len(running) == len(supplier.observations) == 1


@pytest.mark.parametrize("original_execution", [False, True])
def test_execution_policy_cannot_be_added_or_removed_on_resume(
    tmp_path, monkeypatch, original_execution,
):
    value = _fixture(tmp_path, monkeypatch)
    controller, supplier = _controller(value, execution=original_execution)
    if original_execution:
        def interrupted(*_args, **_kwargs):
            raise _Crash("inert process seam interruption")

        monkeypatch.setattr(native_trusted_scheduler, "run_native_trusted_attempt", interrupted)
        with pytest.raises(_Crash):
            _run(controller, value)
    else:
        with pytest.raises(RSILearningError, match="dispatch_not_accepted"):
            _run(controller, value)
    history = value.ledger.controller_checkpoint_history(value.binding.run_id)
    before = _inventory(value.root)
    changed, _ = _controller(value, supplier, execution=not original_execution)
    with pytest.raises(RSILearningError):
        changed.resume(value.binding.run_id)
    assert value.ledger.controller_checkpoint_history(value.binding.run_id) == history
    assert _inventory(value.root) == before
    assert len(supplier.observations) == 1
