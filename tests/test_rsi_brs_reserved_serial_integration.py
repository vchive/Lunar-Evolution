"""Natural private serial children over explicit inert process observations.

Only a controlled Python fixture interpreter is started. No producer, candidate,
evaluator, model or network operation is executed; those boundaries are doubled. The actual gateway claims/results,
native preparation, original owner, publication, worker ACK, settlement and
retirement are composed by the private serial driver.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import FunctionType

import pytest
import test_rsi_child_execution_flow as child_fixture
from test_rsi_publication_lineage_rejection_owner import _inert_rejection_evaluator

from lunar_evolution import (
    DeterministicCurriculum,
    RSILearningController,
    candidate_evaluation,
    native_trusted_attempt,
    native_trusted_output,
    native_trusted_receipt,
    native_trusted_scheduler,
)
from lunar_evolution import rsi_brs_native_process_evidence as process_evidence
from lunar_evolution.automatic_solve_lifecycle import SolveExecutionControl
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.native_trusted_attempt import (
    NativeTrustedAttemptObservation,
    _terminal_receipt,
)
from lunar_evolution.native_trusted_capture import capture_native_trusted_output
from lunar_evolution.native_trusted_cleanup import _record
from lunar_evolution.process_ownership import ProcessCleanupResult, ProcessCleanupStatus
from lunar_evolution.producer_bootstrap import build_trusted_bootstrap_launch
from lunar_evolution.producer_broker_ipc import ProducerBrokerObservation
from lunar_evolution.producer_process import _digest_without, _identity_digest
from lunar_evolution.producer_request_transport import (
    HostRequestJournal,
    HostRequestJournalIdentity,
    read_host_request_journal,
)
from lunar_evolution.rsi_brs_serial_driver import drive_reserved_brs_native_serial
from lunar_evolution.rsi_learning import PracticeEpisode
from lunar_evolution.rsi_producer_gateway import (
    PythonProducerRSIExecutionConfig,
    PythonProducerRSISolverGateway,
)
from lunar_evolution.rsi_python_scheduler_inputs import PythonRSISchedulerInputContext

HEX = "a" * 64
_SERIAL_FLOW_SECONDS = 600
# The host limit also covers imports, synthetic fixture preparation and final
# source/read-only checks outside the original flow deadline. This is a finite
# allowance, not a measured overhead or an extension of any production budget.
_SERIAL_HARNESS_ALLOWANCE_SECONDS = 300


def _forbidden(*_args, **_kwargs):
    pytest.fail("serial integration fixture attempted external execution")


def _install_inert_guards(monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", _forbidden)
    monkeypatch.setattr(subprocess, "run", _forbidden)
    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    monkeypatch.setattr(socket, "create_connection", _forbidden)


@pytest.fixture
def tmp_path():
    # Runtime manifests retain absolute source paths.  The ordinary pytest
    # base path is long enough to push this inert fixture's otherwise small
    # binding over the unchanged 32 KiB staging cap.  Keep the fixture's
    # synthetic toolchain in a short, private directory instead of weakening
    # the production wire limit or dropping manifest evidence.
    # macOS exposes /tmp as a symlink, which the no-follow process-boundary
    # checks intentionally reject.  Use its real short parent there while
    # retaining /tmp on Linux.
    temporary_parent = next(
        str(candidate) for candidate in (Path("/private/tmp"), Path("/tmp"), Path("/var/tmp"))
        if candidate.is_dir() and not candidate.is_symlink()
    )
    with tempfile.TemporaryDirectory(prefix="lrsi-", dir=temporary_parent) as directory:
        yield Path(directory)


class _SerialNativeObservation(child_fixture._InertNativeObservation):
    """Retain complete synthetic process records before original-owner capture."""

    def __init__(self, outcomes):
        super().__init__()
        self.outcomes = outcomes

    def rsi_fingerprint_config(self):
        return {"fixture": "reserved-serial-inert-native-v1", "outcomes": self.outcomes}

    def attempt(self, workspace, *, intent, attestation, artifact, **_kwargs):
        ledger = self.controller.ledger
        assert not ledger.controller_lock_held(intent.run_id)
        assert ledger.get_episode(intent.task_id).state == "running"
        ordinal = int(intent.task_id.rsplit("-", 1)[1])
        assert len(self.attempts) == ordinal
        self.attempts.append(intent)
        batch = Path(workspace) / "evolution/producer-batches" / intent.journal_id
        output = batch / intent.output_directory
        (output / "solve").mkdir(parents=True)
        source = self.source_bytes(intent)
        (output / "solve/main.py").write_bytes(source)
        from lunar_evolution.producer_handoff import parse_producer_envelope

        envelope = parse_producer_envelope({
            "schema_version": "1", "producer_id": intent.producer_id,
            "producer_fingerprint": intent.producer_fingerprint,
            "status": "completed", "contract_sha256": intent.contract_sha256,
            "budget": {"requests": 0}, "materials": [{
                "kind": "candidate_source", "path": "solve/main.py", "size": len(source),
                "sha256": hashlib.sha256(source).hexdigest(),
            }],
        })
        # Persist the parser's canonical projection so the retained byte pin and
        # the envelope's semantic digest refer to the same evidence.
        self._write(batch / intent.envelope_path, envelope.to_dict())
        launch = build_trusted_bootstrap_launch(intent, attestation, artifact.descriptor)
        descriptor = artifact.descriptor
        pid = 1_000_000_007
        owner = ({"kind": "darwin-libproc-starttime-v1", "pid": pid, "start_sec": 123, "start_usec": 1}
                 if sys.platform == "darwin" else
                 {"kind": "linux-proc-starttime-v1", "pid": pid,
                  "boot_id": "inert-serial-fixture", "starttime_ticks": 123})
        mode = "darwin-immutable-snapshot" if sys.platform == "darwin" else "linux-sealed-memfd"
        lock = batch / "terminal-fixture-lock"
        lock.write_bytes(b"")
        lock_info = lock.stat()
        registration = {
            "schema_version": "1", "protocol": "lunar-producer-process-execution-v1",
            **{name: getattr(intent, name) for name in (
                "launch_id", "journal_id", "run_id", "parent_task_id", "task_id", "intent_sha256")},
            "attestation_sha256": attestation.attestation_sha256, "consumption_sha256": HEX,
            "executable_identity": _identity_digest({
                "sha256": descriptor.bootstrap_sha256, "size": descriptor.size,
                "device": descriptor.device, "inode": descriptor.inode,
                "mtime_ns": descriptor.mtime_ns, "ctime_ns": descriptor.ctime_ns}),
            "owner_identity": owner, "owner_identity_sha256": hashlib.sha256(canonical_json(owner)).hexdigest(),
            "execution_binding": mode,
            "execution_snapshot_relative_path": ".producer-snapshots/bootstrap" if sys.platform == "darwin" else None,
            "execution_snapshot_sha256": descriptor.bootstrap_sha256, "execution_snapshot_size": descriptor.size,
            "pid": pid, "pgid": pid, "recovery_lock_protocol": "journal-flock-v1",
            "recovery_lock_device": lock_info.st_dev, "recovery_lock_inode": lock_info.st_ino,
            "gate_protocol": launch.gate_protocol, "registered_at_unix_ns": 123,
            "launch_sha256": launch.digest(), "bootstrap_descriptor_sha256": descriptor.digest(),
            "target_executable_identity": launch.target_executable_identity, "target_execution_binding": mode,
            "target_execution_snapshot_relative_path": ".producer-snapshots/target" if sys.platform == "darwin" else None,
            "target_execution_snapshot_sha256": launch.target_executable_identity,
            "target_execution_snapshot_size": intent.executable_size,
        }
        registration["registration_sha256"] = _digest_without(registration, "registration_sha256")
        cleanup = _record(intent, registration["registration_sha256"], HEX,
                          ProcessCleanupResult("fixture", pid, pid, ProcessCleanupStatus.ALREADY_EXITED))
        terminal = _terminal_receipt(
            registration, handoff_sha256=HEX, evidence_sha256=HEX, gate_released=True,
            target_started=True, exit_code=0, cleanup_status=cleanup["cleanup_status"],
            deadline_sha256=HEX, stream_capture_sha256=HEX, cleanup_sha256=cleanup["cleanup_sha256"],
        )
        for name, record in (("process-registration.json", registration),
                             ("native-trusted-cleanup.json", cleanup),
                             ("native-trusted-process-terminal.json", terminal)):
            self._write(batch / name, record)
        if sys.platform == "darwin":
            target = batch / registration["target_execution_snapshot_relative_path"]
            target.parent.mkdir(mode=0o700)
            target.write_bytes((self.controller.gateway.producer_config.inputs.native_context.producer_root
                                / intent.executable_relative).read_bytes())
            target.chmod(0o500)
        broker_root = batch / ".host-request-journal"
        broker_root.mkdir(mode=0o700)
        identity = HostRequestJournalIdentity(wall_deadline_ns=1, **{
            name: getattr(intent, name) for name in (
                "launch_id", "journal_id", "run_id", "parent_task_id", "task_id",
                "intent_sha256", "request_timeout_seconds", "max_requests")})
        with HostRequestJournal.create(broker_root / "requests", identity):
            pass
        retained = read_host_request_journal(broker_root / "requests", expected_identity=identity)
        capture = capture_native_trusted_output(batch, intent=intent, terminal_sha256=terminal["terminal_sha256"],
            broker=ProducerBrokerObservation(retained.snapshot, broker_root / "requests", identity,
                retained.journal_sha256, retained.journal_bytes, True, "inert-no-requests",
                retained.journal_file_identity), deadline=time.monotonic() + 20)
        receipt = child_fixture._formal_execution_receipt(journal_id=intent.journal_id,
            run_id=intent.run_id, parent_task_id=intent.parent_task_id, task_id=intent.task_id)
        receipt.update(**{name: getattr(intent, name) for name in (
            "launch_id", "request_timeout_seconds", "max_requests", "output_max_bytes", "wall_timeout_seconds")},
            intent_sha256=intent.digest(), attestation_sha256=attestation.digest(),
            registration_sha256=registration["registration_sha256"],
            previous_receipt_sha256=registration["registration_sha256"], pid=pid, pgid=pid,
            owner_identity=owner, cleanup_status=cleanup["cleanup_status"], cleanup_sha256=cleanup["cleanup_sha256"],
            execution_binding=mode, execution_snapshot_relative_path=registration["target_execution_snapshot_relative_path"],
            execution_snapshot_sha256=intent.executable_sha256, execution_snapshot_size=intent.executable_size)
        receipt["trusted_execution"].update(
            terminal_sha256=terminal["terminal_sha256"], stream_capture_sha256=HEX,
            cleanup_sha256=cleanup["cleanup_sha256"], output_capture_sha256=capture["capture_sha256"],
            broker_journal_identity=identity.to_dict(), broker_journal_sha256=retained.journal_sha256,
            broker_journal_bytes=retained.journal_bytes,
            broker_journal_file_identity=list(retained.journal_file_identity))
        receipt["envelope_evidence"] = capture["envelope_evidence"]
        receipt["receipt_sha256"] = _digest_without(receipt, "receipt_sha256")
        self.receipts[intent.journal_id] = receipt
        return NativeTrustedAttemptObservation(
            launch_id=intent.launch_id, journal_id=intent.journal_id, status="recovery_required",
            reason="native_trusted_attempt_request_and_output_unverified",
            registration_sha256=registration["registration_sha256"], gate_released=True,
            target_started=True, exit_code=0, cleanup_status=cleanup["cleanup_status"],
            terminal_sha256=terminal["terminal_sha256"], output_capture_sha256=capture["capture_sha256"])

    def terminal(self, workspace, *, intent, attestation, **_kwargs):
        terminal = self._read(Path(workspace) / "evolution/producer-batches" / intent.journal_id
                              / "native-trusted-process-terminal.json")
        assert terminal["intent_sha256"] == intent.digest()
        assert terminal["attestation_sha256"] == attestation.digest()
        return terminal


def _receipt_projection(workspace, *, intent, **_kwargs):
    import json
    from pathlib import Path

    from lunar_evolution.producer_process import parse_producer_execution_receipt

    return parse_producer_execution_receipt(json.loads((Path(workspace) / "evolution/producer-batches"
                                                       / intent.journal_id / "execution-receipt.json").read_bytes()))


def _terminal_projection(workspace, *, intent, **_kwargs):
    import json
    from pathlib import Path

    return json.loads((Path(workspace) / "evolution/producer-batches" / intent.journal_id
                       / "native-trusted-process-terminal.json").read_bytes())


def _setup(root, patch, outcomes):
    original_receipt_reader = native_trusted_receipt.recover_native_trusted_execution_receipt
    value, _unused_controller, supplier, _unused_observation = child_fixture._successful_fixture(root, patch)
    observation = _SerialNativeObservation(outcomes)
    control = SolveExecutionControl(_SERIAL_FLOW_SECONDS)
    value.native = replace(value.native, execution_control=control, python_handoff_after_execution=observation)
    value.context = PythonRSISchedulerInputContext(value.native, value.sidecar, value.proof)
    value.config = PythonProducerRSIExecutionConfig(value.request.solver_id, value.ledger, value.context)
    value.gateway = PythonProducerRSISolverGateway(value.config)
    controller = RSILearningController(value.gateway, ledger=value.ledger,
        producer_sidecar=value.sidecar, producer_workspace=value.root,
        producer_child_execution=True, producer_multi_episode_publication=True, producer_known_rejection=True,
        producer_stager=child_fixture.PythonProducerEpisodeStager(child_fixture.PythonProducerEpisodeStagingConfig(
            workspace=value.root, root_sidecar=value.sidecar, artifact=value.native.artifact,
            attestation_supplier=supplier)))
    observation.controller = controller
    patch.setattr(native_trusted_scheduler, "run_native_trusted_attempt", observation.attempt)
    patch.setattr(native_trusted_scheduler, "persist_native_trusted_execution_receipt", observation.persist_receipt)
    patch.setattr(native_trusted_scheduler, "recover_native_trusted_execution_receipt", original_receipt_reader)
    terminal_reader = FunctionType(_terminal_projection.__code__, vars(native_trusted_attempt), "_terminal_projection")
    receipt_reader = FunctionType(_receipt_projection.__code__, vars(native_trusted_receipt), "_receipt_projection")
    for module in (native_trusted_attempt, native_trusted_output, native_trusted_receipt, process_evidence):
        patch.setattr(module, "recover_native_trusted_attempt", terminal_reader)
        if hasattr(module, "recover_native_trusted_execution_receipt"):
            patch.setattr(module, "recover_native_trusted_execution_receipt", original_receipt_reader)
    patch.setattr(native_trusted_receipt, "build_native_trusted_execution_receipt", receipt_reader)

    def evaluator(command, *, cwd, **kwargs):
        # The serial driver has exactly one producer/evaluator in flight.
        # This changes only the explicitly inert evaluator process response.
        ordinal = len(observation.attempts) - 1
        assert int(observation.attempts[ordinal].task_id.rsplit("-", 1)[1]) == ordinal
        function = (_inert_rejection_evaluator if outcomes[ordinal] == "rejected"
                    else child_fixture._inert_candidate_process)
        return function(command, cwd=cwd, **kwargs)

    patch.setattr(candidate_evaluation, "_bounded_process_bytes", evaluator)
    run_id = value.binding.run_id
    pins = {name: getattr(value.request, name) for name in (
        "contract_sha256", "evaluator_sha256", "environment_sha256", "solver_id")}
    target = controller._target_episode(run_id, run_id + "-target", pins, 0)
    decisions = [DeterministicCurriculum().choose(target=target, diagnosis="inert serial gap", wave=0, ordinal=i)
                 for i in range(len(outcomes))]
    plan = {"mode": "brs", "wave": 0, "max_workers": 1, "reserved_native_serial": True,
            "practices": [item.to_dict() for item in decisions]}
    budget = {**dict(value.request.budget), "max_practice_rounds": len(outcomes),
        "max_practice_episodes": len(outcomes), "max_solver_invocations": len(outcomes),
        "max_evaluator_invocations": len(outcomes), "max_verifier_invocations": len(outcomes)}
    with value.ledger.controller_lock(run_id):
        record = controller._start_run(run_id=run_id, mode="brs", plan=plan, budget=budget,
            producer_checkpoint_binding=value.proof.to_dict(), **pins)
        state = controller._flow_state(record, run_id=run_id, plan=plan, pins=pins, budget=budget)
        controller._save_flow(record, state)
        for ordinal, decision in enumerate(decisions):
            episode = PracticeEpisode(f"{run_id}-practice-0-{ordinal}", run_id, pins["contract_sha256"],
                pins["evaluator_sha256"], pins["environment_sha256"], controller.snapshot.digest(),
                pins["solver_id"], "planned", wave=0, ordinal=ordinal,
                parent_target_episode_id=run_id + "-target-seed")
            request = controller._request(episode, budget=state["budget_state"]["planned"],
                charter={**decision.to_dict(), "decision_sha256": decision.digest()})
            controller._prepare_intent(record, state, episode, request)
    value.controller, value.observation, value.supplier = controller, observation, supplier
    value.record, value.state = record, state
    return value


def _exercise_natural_case(tmp_path, monkeypatch, outcomes):
    value = _setup(tmp_path, monkeypatch, outcomes)
    initial = deepcopy(value.state)
    root_gateway, root_sidecar = value.controller.gateway, value.controller.producer_sidecar
    from lunar_evolution.rsi_brs_serial_driver import read_reserved_brs_serial_observation

    with value.ledger.controller_lock(value.binding.run_id):
        read_reserved_brs_serial_observation(value.controller, value.state)
    with value.ledger.controller_lock(value.binding.run_id):
        result = drive_reserved_brs_native_serial(value.controller, value.record, value.state)
    assert result.status == "completed"
    assert len(result.practice_episodes) == len(outcomes)
    _head, state = value.ledger.controller_checkpoint(value.binding.run_id)
    assert state["root_snapshot"] == initial["root_snapshot"]
    assert state["budget_state"] == initial["budget_state"]
    assert value.controller.gateway is root_gateway and value.controller.producer_sidecar is root_sidecar
    assert value.ledger.controller_brs_reconcile_obligations(value.binding.run_id) == {}
    assert len(value.observation.attempts) == len(outcomes)
    assert len(value.observation.handoffs) == len(outcomes)
    assert len(value.supplier.observations) == len(outcomes)
    expected_lineage_states = ["terminal" if outcome == "published" else "rejected" for outcome in outcomes]
    assert [entry["state"] for entry in state["producer_publication_lineage"]["batches"]] == expected_lineage_states

    # A completed wave is a read-only resume.  It must not mint another native
    # attempt, handoff, attestation, checkpoint, or child result.
    history = value.ledger.controller_checkpoint_history(value.binding.run_id)
    attempts = tuple(item.journal_id for item in value.observation.attempts)
    handoffs = tuple(item.handoff.handoff_sha256 for item in value.observation.handoffs)
    supplier_observations = len(value.supplier.observations)
    resumed = value.controller.resume(value.binding.run_id)
    assert resumed == result
    assert value.ledger.controller_checkpoint_history(value.binding.run_id) == history
    assert tuple(item.journal_id for item in value.observation.attempts) == attempts
    assert tuple(item.handoff.handoff_sha256 for item in value.observation.handoffs) == handoffs
    assert len(value.supplier.observations) == supplier_observations


@pytest.mark.parametrize("outcomes", [
    # Keep both terminal classes adjacent to exercise rejection retention and
    # published-head carry-forward independently of the runner implementation.
    pytest.param(("rejected", "rejected"), id="rejected-rejected"),
    pytest.param(("published", "published"), id="published-published"),
    pytest.param(("published", "rejected"), id="published-rejected"),
    # A three-child wave proves the serial driver does not accidentally stop
    # after the first C1/C2 pair and that the retained prefix remains ordered.
    pytest.param(("rejected", "published", "rejected"), id="three-child-mixed"),
])
def test_natural_reserved_children_complete_in_original_order(tmp_path, outcomes):
    # The exact reserved graph is a process-lifetime capture, including the
    # explicitly inert attempt/receipt aliases. Each case needs its own original
    # capture; never reset a warm graph, original closure, latch or outer capture.
    source = Path(__file__).resolve().parents[1] / "src"
    tests = Path(__file__).resolve().parent
    expected = {path.relative_to(source).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(source.rglob("*.py"))}
    graph = sys.modules.get("lunar_evolution.rsi_brs_reserved_policy")
    owner = sys.modules.get("lunar_evolution.rsi_brs_publication_lineage")
    held_project = getattr(graph, "_PROJECT", None)
    held_capture = getattr(owner, "_ORIGINAL_RESERVED_PROJECT_CAPTURE", None)
    script = r'''
import hashlib
import json
from pathlib import Path
import sys

source = Path(sys.argv[1]).resolve(strict=True)
tests = Path(sys.argv[2]).resolve(strict=True)
work = Path(sys.argv[3]).resolve(strict=True)
outcomes = tuple(json.loads(sys.argv[4]))
expected = json.loads(sys.argv[5])
assert outcomes in {
    ("rejected", "rejected"), ("published", "published"),
    ("published", "rejected"), ("rejected", "published", "rejected"),
}
sys.path[:0] = [str(source), str(tests)]

def no_execution(event, args):
    if event in {"subprocess.Popen", "os.system", "os.posix_spawn", "os.fork", "socket.connect"}:
        raise AssertionError("inert serial child attempted execution or network: " + event)

sys.addaudithook(no_execution)

import pytest
import test_rsi_brs_reserved_serial_integration as fixture

def check_sources():
    count = 0
    for name, module in tuple(sys.modules.items()):
        if name != "lunar_evolution" and not name.startswith("lunar_evolution."):
            continue
        path = Path(module.__file__).resolve(strict=True)
        relative = path.relative_to(source).as_posix()
        assert relative in expected and hashlib.sha256(path.read_bytes()).hexdigest() == expected[relative]
        count += 1
    assert count > 0

check_sources()
with pytest.MonkeyPatch.context() as patch:
    fixture._install_inert_guards(patch)
    fixture._exercise_natural_case(work, patch, outcomes)
check_sources()
print(json.dumps({"outcomes": list(outcomes), "status": "completed"}, sort_keys=True))
'''
    completed = subprocess.run(
        [sys.executable, "-I", "-B", "-c", script, str(source), str(tests), str(tmp_path),
         json.dumps(outcomes), json.dumps(expected, sort_keys=True)],
        cwd=tmp_path, env={"PATH": os.defpath, "LC_ALL": "C"},
        capture_output=True, text=True,
        timeout=_SERIAL_FLOW_SECONDS + _SERIAL_HARNESS_ALLOWANCE_SECONDS, check=False,
    )
    assert completed.returncode == 0, (completed.stdout + completed.stderr)[-16_000:]
    assert json.loads(completed.stdout) == {"outcomes": list(outcomes), "status": "completed"}
    assert getattr(graph, "_PROJECT", None) is held_project
    assert getattr(owner, "_ORIGINAL_RESERVED_PROJECT_CAPTURE", None) is held_capture
