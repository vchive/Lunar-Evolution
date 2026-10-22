"""Natural local worker settlement and explicit independent recovery evidence.

The producer records below are deliberately inert pre-existing fixture records.
No producer, candidate, model or evaluator runs. The selected BRS worker itself
returns naturally through the actual controller and PracticeEpisodeRunner, which
persist the exact result and append its real terminal episode successors.
"""
from __future__ import annotations

import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from queue import Queue
from threading import Event, get_ident

import pytest
import test_rsi_brs_publication_lineage_owner as owner_fixture
import test_rsi_python_brs_native_dispatch as native_fixture
import test_rsi_python_brs_selected_service as selected
from test_rsi_python_admission import DIGEST, _plan, _rows

from lunar_evolution import RSILearningError, RSILedger
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.native_trusted_attempt import _terminal_receipt
from lunar_evolution.native_trusted_cleanup import _record
from lunar_evolution.native_trusted_output import prepare_native_trusted_output
from lunar_evolution.process_ownership import ProcessCleanupResult, ProcessCleanupStatus
from lunar_evolution.producer_bootstrap import build_trusted_bootstrap_launch
from lunar_evolution.producer_process import (
    _digest_without,
    _identity_digest,
    parse_producer_execution_receipt,
)
from lunar_evolution.python_producer_admission_anchor import (
    project_python_producer_admission_attempt_anchor,
)
from lunar_evolution.python_producer_admission_handoff import (
    PYTHON_PRODUCER_ADMISSION_HANDOFF_NAME,
    build_python_producer_admission_handoff,
    persist_python_producer_admission_handoff_pinned,
)
from lunar_evolution.rsi_brs_mailbox_evidence import inspect_brs_mailbox_evidence
from lunar_evolution.rsi_gateway import SolverResult
from lunar_evolution.rsi_python_brs_publication_mailbox import BRSOwnerPublicationMailbox

inert_only = native_fixture.inert_only
tmp_path = native_fixture.tmp_path


def _write_fixture(path, value):
    if path.exists():
        path.rename(path.with_name(path.name + ".terminal-fixture-original"))
    path.write_bytes(canonical_json(value))
    path.chmod(0o600)


def _seed_original_native_records(value):
    """Seed independent process records before any owner/mailbox capture.

    Synthetic native execution is explicitly a fixture boundary, as in the
    retained-native reader fixture. Registration, cleanup, canonical durable file
    reads, byte/inode rechecks and OS signal-0 absence observations remain real.
    The large fixture PID denotes no process launched by this test.
    """
    native, batch = value.native, value.batch
    intent, attestation, descriptor = native.intent, native.attestation, native.artifact.descriptor
    launch = build_trusted_bootstrap_launch(intent, attestation, descriptor)
    pid = 1_000_000_007
    owner = ({"kind": "darwin-libproc-starttime-v1", "pid": pid, "start_sec": 123, "start_usec": 1}
             if sys.platform == "darwin" else
             {"kind": "linux-proc-starttime-v1", "pid": pid, "boot_id": "inert-terminal-fixture", "starttime_ticks": 123})
    mode = "darwin-immutable-snapshot" if sys.platform == "darwin" else "linux-sealed-memfd"
    lock = batch / "terminal-fixture-lock"
    lock.write_bytes(b"")
    identity = lock.stat()
    registration = {
        "schema_version": "1", "protocol": "lunar-producer-process-execution-v1",
        **{name: getattr(intent, name) for name in (
            "launch_id", "journal_id", "run_id", "parent_task_id", "task_id", "intent_sha256",
        )},
        "attestation_sha256": attestation.attestation_sha256, "consumption_sha256": DIGEST,
        "executable_identity": _identity_digest({
            "sha256": descriptor.bootstrap_sha256, "size": descriptor.size,
            "device": descriptor.device, "inode": descriptor.inode,
            "mtime_ns": descriptor.mtime_ns, "ctime_ns": descriptor.ctime_ns,
        }),
        "owner_identity": owner, "owner_identity_sha256": hashlib.sha256(canonical_json(owner)).hexdigest(),
        "execution_binding": mode,
        "execution_snapshot_relative_path": ".producer-snapshots/bootstrap" if sys.platform == "darwin" else None,
        "execution_snapshot_sha256": descriptor.bootstrap_sha256, "execution_snapshot_size": descriptor.size,
        "pid": pid, "pgid": pid, "recovery_lock_protocol": "journal-flock-v1",
        "recovery_lock_device": identity.st_dev, "recovery_lock_inode": identity.st_ino,
        "gate_protocol": launch.gate_protocol, "registered_at_unix_ns": 123,
        "launch_sha256": launch.digest(), "bootstrap_descriptor_sha256": descriptor.digest(),
        "target_executable_identity": launch.target_executable_identity,
        "target_execution_binding": mode,
        "target_execution_snapshot_relative_path": ".producer-snapshots/target" if sys.platform == "darwin" else None,
        "target_execution_snapshot_sha256": launch.target_executable_identity,
        "target_execution_snapshot_size": intent.executable_size,
    }
    registration["registration_sha256"] = _digest_without(registration, "registration_sha256")
    cleanup = _record(intent, registration["registration_sha256"], DIGEST,
                      ProcessCleanupResult("fixture", pid, pid, ProcessCleanupStatus.ALREADY_EXITED))
    terminal = _terminal_receipt(
        registration, handoff_sha256=DIGEST, evidence_sha256=DIGEST,
        gate_released=True, target_started=True, exit_code=0,
        cleanup_status=cleanup["cleanup_status"], deadline_sha256=DIGEST,
        stream_capture_sha256=DIGEST, cleanup_sha256=cleanup["cleanup_sha256"],
    )
    capture_path = batch / "native-trusted-output-capture.json"
    capture = json.loads(capture_path.read_bytes())
    capture["previous_receipt_sha256"] = terminal["terminal_sha256"]
    capture["capture_sha256"] = _digest_without(capture, "capture_sha256")
    _write_fixture(capture_path, capture)
    raw = value.preparation.run.receipt.to_dict()
    raw.update(registration_sha256=registration["registration_sha256"],
               previous_receipt_sha256=registration["registration_sha256"],
               pid=pid, pgid=pid, owner_identity=owner,
               cleanup_status=cleanup["cleanup_status"], cleanup_sha256=cleanup["cleanup_sha256"],
               execution_binding=mode,
               execution_snapshot_relative_path=registration["target_execution_snapshot_relative_path"],
               execution_snapshot_sha256=intent.executable_sha256,
               execution_snapshot_size=intent.executable_size)
    raw["trusted_execution"].update(
        terminal_sha256=terminal["terminal_sha256"], stream_capture_sha256=DIGEST,
        cleanup_sha256=cleanup["cleanup_sha256"], output_capture_sha256=capture["capture_sha256"],
    )
    raw["receipt_sha256"] = _digest_without(raw, "receipt_sha256")
    receipt = parse_producer_execution_receipt(raw)
    for name, record in (("process-registration.json", registration),
                         ("execution-receipt.json", receipt.to_dict()),
                         ("native-trusted-process-terminal.json", terminal),
                         ("native-trusted-cleanup.json", cleanup)):
        _write_fixture(batch / name, record)
    _write_fixture(value.workspace / "fixture-native-receipt-projection.json", receipt.to_dict())
    _write_fixture(value.workspace / "fixture-native-terminal-projection.json", terminal)
    output = prepare_native_trusted_output(
        **{name: getattr(native, name) for name in (
            "workspace", "intent", "attestation", "artifact", "contract", "groups", "evaluator_kind",
            "evaluator_fingerprint", "runner_fingerprint", "dependency_sha256", "environment_sha256",
        )}, require_same_attempt_capture=True, require_execution_receipt=True,
    )
    wire = value.handoff.to_dict()
    wire.pop("handoff_sha256")
    wire["native_execution_receipt_sha256"] = receipt.receipt_sha256
    value.handoff = build_python_producer_admission_handoff(**wire)
    path = batch / PYTHON_PRODUCER_ADMISSION_HANDOFF_NAME
    path.rename(path.with_name(path.name + ".terminal-fixture-original"))
    sidecar = persist_python_producer_admission_handoff_pinned(batch, handoff=value.handoff)
    value.pin = sidecar.file_pin
    value.journal = replace(value.journal, native_execution_receipt_sha256=receipt.receipt_sha256,
                            python_handoff_sha256=value.handoff.handoff_sha256,
                            python_handoff_file_pin=value.pin, journal_sha256=None)
    value.anchor = project_python_producer_admission_attempt_anchor(value.handoff)
    value.preparation = replace(value.preparation,
                                run=replace(value.preparation.run, receipt=receipt, output=output), handoff=sidecar)
    value.prepared_output = output


@contextmanager
def _natural_owner_waiting(root, patch, *, native_records=False, callback_unknown=False, future_unknown=False):
    """Replace only the old waiting fixture, preserving its inert native setup."""
    from lunar_evolution.rsi_brs_publication_lineage import _BRSLineageCheckpointOwner

    value = owner_fixture._setup(root, patch)
    if native_records:
        _seed_original_native_records(value)
    messages, ready = Queue(), Event()
    value.callback_calls = []

    def callback(delivery):
        value.callback_calls.append(delivery.to_dict())
        if callback_unknown:
            raise RuntimeError("inert_terminal_callback_unknown")
        return SolverResult(
            episode_id=value.request.episode_id, request_sha256=value.request.digest(), status="completed",
            candidate_receipt_sha256=DIGEST, execution_receipt_sha256=DIGEST,
            official_evaluation_receipt_sha256=DIGEST, trace_digest=DIGEST,
            solver_score=1.0, terminal_reason="inert-natural-terminal-worker",
        )

    def operation(request):
        plan = _plan(value.binding, request, value.controller.snapshot)
        plan = replace(plan, bootstrap_descriptor_sha256=value.native.artifact.descriptor.digest(),
                       bootstrap_artifact_sha256=value.native.artifact.artifact_sha256, plan_sha256=None)
        claim = value.ledger.claim_native_episode(request, plan_sha256=plan.plan_sha256)
        messages.put((request, plan, get_ident()))
        assert ready.wait(timeout=30), "original owner never released the inert worker"
        result = value.session.worker_endpoint.receive_and_settle(
            value.request_message, callback=callback, check=lambda: None,
        )
        value.ledger.publish_native_episode_result(
            request, plan_sha256=plan.plan_sha256, result=result, expected_claim=claim,
        )
        return result

    value.operation = operation
    with selected._wave(value) as wave:
        handoff = value.controller._python_admission_bind_selected_brs_handoff(wave)
        pool = ThreadPoolExecutor(max_workers=1)
        if future_unknown:
            def raise_after_natural_terminal():
                value.controller._execute_brs_intent(wave, wave.state, handoff.episode_id, handoff)
                raise RuntimeError("inert_future_raised_after_natural_terminal")

            future = pool.submit(raise_after_natural_terminal)
        else:
            future = pool.submit(value.controller._execute_brs_intent, wave, wave.state, handoff.episode_id, handoff)
        try:
            request, plan, worker_thread = messages.get(timeout=20)
            value.request, value.plan, value.worker_thread = request, plan, worker_thread
            value.ready, value.messages, value.future, value.pool = ready, messages, future, pool
            value.owner = _BRSLineageCheckpointOwner(
                value.controller, wave, request=request, memory=value.controller.snapshot, native_plan=plan,
            )
            value.wave = wave
            yield value
        finally:
            ready.set()
            if hasattr(value, "mailbox"):
                value.mailbox.close()
            wave.channel.close()
            pool.shutdown(wait=True)


@contextmanager
def _natural_worker(tmp_path, monkeypatch, *, native_records=False, callback_unknown=False, future_unknown=False):
    from lunar_evolution import native_trusted_attempt as attempt_module
    from lunar_evolution import native_trusted_output as output_module
    from lunar_evolution import native_trusted_receipt as receipt_module
    from lunar_evolution import rsi_brs_native_process_evidence as process_evidence
    from lunar_evolution.rsi_python_brs_terminal_lifecycle import open_brs_terminal_lifecycle

    def waiting(root, patch):
        return _natural_owner_waiting(root, patch, native_records=native_records,
                                      callback_unknown=callback_unknown, future_unknown=future_unknown)

    monkeypatch.setattr(owner_fixture, "_waiting", waiting)
    with native_fixture._waiting(tmp_path, monkeypatch) as value:
        value.mailbox = BRSOwnerPublicationMailbox(value.wave.selected_handoff, worker_thread=value.worker_thread)
        value.session = open_brs_terminal_lifecycle(
            value.owner, value.mailbox, future=value.future, executor=value.pool,
        )
        value.terminal_reader_projection = (
            (attempt_module, "recover_native_trusted_attempt", attempt_module.recover_native_trusted_attempt),
            (output_module, "recover_native_trusted_attempt", output_module.recover_native_trusted_attempt),
            (process_evidence, "recover_native_trusted_attempt", process_evidence.recover_native_trusted_attempt),
            (receipt_module, "recover_native_trusted_attempt", receipt_module.recover_native_trusted_attempt),
        )
        yield value


@contextmanager
def _retained_terminal_projection(value, monkeypatch):
    """Keep the source-bound fixture readers active after the owner has drained."""
    with monkeypatch.context() as patch:
        for module, name, projection in value.terminal_reader_projection:
            patch.setattr(module, name, projection)
        yield


def _context(value):
    return {"workspace": value.workspace, "native_plan": value.plan,
            **{name: getattr(value.native, name) for name in ("intent", "attestation", "artifact")}}


def _assert_natural_terminal(value):
    execution = value.future.result(timeout=20)
    assert execution.episode.status == execution.result.status == "completed"
    history = value.ledger.history(value.episode_id)
    assert [record.state for record in history] == ["running", "completed", "completed"]
    assert history[-1].payload == execution.episode.to_record_dict()
    assert history[-1].parent_record_sha256 == history[-2].record_sha256
    assert value.ledger.episode_result(value.episode_id) == (execution.request, execution.result)
    assert value.ledger.inspect_native_episode_claim(
        execution.request, plan_sha256=value.plan.plan_sha256,
    ).status == "completed"
    assert len(value.callback_calls) == value.gateway.calls == 1
    assert value.ledger.get_episode(value.sibling_id) is None
    assert not any(thread.is_alive() for thread in value.pool._threads)
    return execution


def test_natural_terminal_without_original_native_capture_remains_fenced(tmp_path, monkeypatch):
    from lunar_evolution.rsi_brs_terminal_evidence import inspect_brs_terminal_observation

    with _natural_worker(tmp_path, monkeypatch) as value:
        budget = deepcopy(value.wave.state["budget_state"])
        value.ready.set()
        value.session.serve(value.preparation, check=lambda: None, timeout=10)
        _assert_natural_terminal(value)
    report = inspect_brs_mailbox_evidence(value.ledger, value.binding.run_id, value.episode_id)
    assert report["binding"]["capture"]["native_process"]["status"] == "unknown"
    before = _rows(value)
    observed = inspect_brs_terminal_observation(value.ledger, value.binding.run_id, value.episode_id, **_context(value))
    assert observed["status"] == "unknown"
    result = value.controller.reconcile_brs_terminal(value.binding.run_id, value.episode_id, **_context(value))
    assert result["consumption"] is None
    assert _rows(value) == before
    assert value.ledger.controller_brs_reconcile_obligations(value.binding.run_id)
    assert value.wave.state["budget_state"] == budget


def test_natural_terminal_exact_independent_evidence_only_explicitly_consumes(tmp_path, monkeypatch):
    from lunar_evolution.rsi_brs_terminal_evidence import inspect_brs_terminal_observation

    with _natural_worker(tmp_path, monkeypatch, native_records=True) as value:
        value.ready.set()
        value.session.serve(value.preparation, check=lambda: None, timeout=10)
        _assert_natural_terminal(value)
    with _retained_terminal_projection(value, monkeypatch):
        mailbox = inspect_brs_mailbox_evidence(value.ledger, value.binding.run_id, value.episode_id)
        assert mailbox["binding"]["capture"]["native_process"]["status"] == "captured"
        rebuilt = RSILedger(value.ledger.database)
        before = _rows(value)
        observed = inspect_brs_terminal_observation(
            rebuilt, value.binding.run_id, value.episode_id, **_context(value),
        )
        assert observed["status"] == "ready", observed
        assert _rows(value) == before
        assert value.ledger.controller_brs_reconcile_obligations(value.binding.run_id)
        result = value.controller.reconcile_brs_terminal(
            value.binding.run_id, value.episode_id, **_context(value),
        )
        assert result["observation"]["status"] == "ready"
        assert result["consumption"].consumed is True
        assert result["consumption"].decision.outcome == "already_terminal"
        assert value.ledger.controller_brs_reconcile_obligations(value.binding.run_id) == {}
        assert value.gateway.calls == 1


def test_callback_unknown_never_retries_or_fabricates_terminal_result(tmp_path, monkeypatch):
    with _natural_worker(tmp_path, monkeypatch, native_records=True, callback_unknown=True) as value:
        value.ready.set()
        with pytest.raises((RSILearningError, RuntimeError)) as raised:
            value.session.serve(value.preparation, check=lambda: None, timeout=10)
        assert value.future.done(), repr(raised.value)
        assert value.ledger.get_episode(value.episode_id).state == "running"
        assert value.ledger.episode_result(value.episode_id) is None
        assert len(value.callback_calls) == value.gateway.calls == 1
        before = _rows(value)
        with pytest.raises(RSILearningError):
            value.session.serve(value.preparation, check=lambda: None, timeout=10)
        assert _rows(value) == before
        assert len(value.callback_calls) == value.gateway.calls == 1
        assert value.ledger.controller_brs_reconcile_obligations(value.binding.run_id)


def test_explicit_consume_rechecks_root_pins_after_fresh_composition(tmp_path, monkeypatch):
    with _natural_worker(tmp_path, monkeypatch, native_records=True) as value:
        value.ready.set()
        value.session.serve(value.preparation, check=lambda: None, timeout=10)
        _assert_natural_terminal(value)
    with _retained_terminal_projection(value, monkeypatch):
        original = value.ledger._consume_brs_reconcile_obligation
        observed = []

        def racing_consume(run_id, episode_id, evidence, *, expected_pins=None, settled_execution=None):
            assert expected_pins is not None
            head, state = value.ledger.controller_checkpoint(run_id)
            assert expected_pins["root_checkpoint_sha256"] == head
            observed.append(deepcopy(expected_pins))
            # A legitimate adjacent root append between the independent read and
            # consume must invalidate that read, even when its payload is equal.
            value.ledger.write_controller_checkpoint(run_id, state, expected_sha256=head)
            return original(run_id, episode_id, evidence, expected_pins=expected_pins,
                            settled_execution=settled_execution)

        monkeypatch.setattr(value.ledger, "_consume_brs_reconcile_obligation", racing_consume)
        before = value.ledger.controller_brs_reconcile_obligations(value.binding.run_id)
        with pytest.raises(RSILearningError, match="^rsi_brs_terminal_consume_drift$"):
            value.controller.reconcile_brs_terminal(
                value.binding.run_id, value.episode_id, **_context(value),
            )
        assert len(observed) == 1
        assert value.ledger.controller_brs_reconcile_obligations(value.binding.run_id) == before
        assert value.gateway.calls == 1


def test_natural_terminal_native_file_replacement_cannot_refresh_original_capture(tmp_path, monkeypatch):
    with _natural_worker(tmp_path, monkeypatch, native_records=True) as value:
        value.ready.set()
        value.session.serve(value.preparation, check=lambda: None, timeout=10)
        _assert_natural_terminal(value)
    with _retained_terminal_projection(value, monkeypatch):
        original = inspect_brs_mailbox_evidence(
            value.ledger, value.binding.run_id, value.episode_id,
        )["binding"]["capture"]["native_process"]
        path = value.batch / "native-trusted-cleanup.json"
        raw, inode = path.read_bytes(), path.stat().st_ino
        path.rename(path.with_name(path.name + ".replacement-original"))
        path.write_bytes(raw)
        path.chmod(0o600)
        assert path.stat().st_ino != inode
        before = _rows(value)
        with pytest.raises(RSILearningError, match="^rsi_brs_terminal_evidence_native_process_drift$"):
            value.controller.reconcile_brs_terminal(
                value.binding.run_id, value.episode_id, **_context(value),
            )
        assert _rows(value) == before
        assert inspect_brs_mailbox_evidence(
            value.ledger, value.binding.run_id, value.episode_id,
        )["binding"]["capture"]["native_process"] == original
        assert value.ledger.controller_brs_reconcile_obligations(value.binding.run_id)
    assert value.gateway.calls == 1


def test_future_raised_after_natural_terminal_keeps_fence(tmp_path, monkeypatch):
    with _natural_worker(tmp_path, monkeypatch, native_records=True, future_unknown=True) as value:
        value.ready.set()
        with pytest.raises(RSILearningError, match="unknown"):
            value.session.serve(value.preparation, check=lambda: None, timeout=10)
        assert value.future.done()
        with pytest.raises(RuntimeError, match="inert_future_raised_after_natural_terminal"):
            value.future.result(timeout=20)
        saved = value.ledger.episode_result(value.episode_id)
        assert saved is not None and saved[0] == value.request and saved[1].status == "completed"
        assert [record.state for record in value.ledger.history(value.episode_id)] == [
            "running", "completed", "completed",
        ]
        assert len(value.callback_calls) == value.gateway.calls == 1
    before = _rows(value)
    result = value.controller.reconcile_brs_terminal(value.binding.run_id, value.episode_id, **_context(value))
    assert result["observation"]["status"] != "ready"
    assert result["consumption"] is None
    assert _rows(value) == before
    assert value.ledger.controller_brs_reconcile_obligations(value.binding.run_id)
