"""Real owner, receipt/output and pinned handoff readers over inert fixture files.

Terminal reprojection/capture observations are explicitly bounded fixture doubles;
no native target, model, evaluator, transaction or publication is executed.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import FunctionType

import pytest
import test_rsi_brs_publication_lineage_owner as owner_fixture
import test_rsi_brs_staged_terminal_checkpoint as native_fixture
from test_producer_bundle_transaction import _formal_execution_receipt

from lunar_evolution import native_trusted_attempt as attempt_module
from lunar_evolution import native_trusted_output as output_module
from lunar_evolution import native_trusted_receipt as receipt_module
from lunar_evolution import producer_bundle_transaction as transaction
from lunar_evolution import rsi_python_brs_publication_recovery as recovery
from lunar_evolution.automatic_solve_lifecycle import (
    SolveExecutionBudgetExceeded,
    SolveExecutionCancelled,
    SolveExecutionControl,
)
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.native_trusted_capture import capture_native_trusted_output
from lunar_evolution.native_trusted_output import prepare_native_trusted_output
from lunar_evolution.native_trusted_scheduler import (
    NativeTrustedProducerRun,
    _NativeTrustedPythonProducerPreparation,
)
from lunar_evolution.producer_broker_ipc import ProducerBrokerObservation
from lunar_evolution.producer_bundle_intent import _intent_content
from lunar_evolution.producer_bundle_preflight import derive_producer_bundle_candidate_id
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
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_python_brs_publication_inputs import _request_from_native_preparation
from lunar_evolution.rsi_python_brs_publication_mailbox import build_brs_owner_publication_request

_BRS_NATIVE_READER_TERMINAL_HOOK = None


def _receipt_projection(workspace, **_kwargs):
    import json

    from lunar_evolution.producer_process import parse_producer_execution_receipt

    return parse_producer_execution_receipt(json.loads(
        (Path(workspace) / "fixture-native-receipt-projection.json").read_bytes()))


def _terminal_projection(workspace, **_kwargs):
    import json

    if _BRS_NATIVE_READER_TERMINAL_HOOK is not None:
        _BRS_NATIVE_READER_TERMINAL_HOOK()
    return json.loads((Path(workspace) / "fixture-native-terminal-projection.json").read_bytes())


@pytest.fixture
def tmp_path(tmp_path_factory):
    return tmp_path_factory.mktemp("r")


def _forbidden(*_args, **_kwargs):
    pytest.fail("retained reader fixture invoked execution/publication")


@pytest.fixture(autouse=True)
def inert_only(monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", _forbidden)
    monkeypatch.setattr(subprocess, "run", _forbidden)
    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    monkeypatch.setattr(socket, "create_connection", _forbidden)
    monkeypatch.setattr(transaction, "run_native_producer_bundle_publication_transaction", _forbidden)


class _Trap:
    def __iter__(self):
        _forbidden()

    def __eq__(self, _other):
        _forbidden()


def _setup(root, patch):
    # Install stable source-bound inert projections before create-run captures
    # the original BRS policy; changing a reader afterward correctly drifts.
    receipt_projection = FunctionType(_receipt_projection.__code__, vars(receipt_module),
                                      _receipt_projection.__name__)
    terminal_projection = FunctionType(_terminal_projection.__code__, vars(attempt_module),
                                       _terminal_projection.__name__)
    patch.setattr(attempt_module, "_BRS_NATIVE_READER_TERMINAL_HOOK", None, raising=False)
    patch.setattr(receipt_module, "build_native_trusted_execution_receipt", receipt_projection)
    patch.setattr(output_module, "recover_native_trusted_attempt", terminal_projection)
    patch.setattr(attempt_module, "recover_native_trusted_attempt", terminal_projection)
    patch.setattr(receipt_module, "recover_native_trusted_attempt", terminal_projection)
    value = native_fixture._native_setup(root, patch)
    native, intent = value.native, value.native.intent
    source = b"# inert candidate\n"
    output = value.batch / intent.output_directory
    output.mkdir(exist_ok=True)
    (output / "main.py").write_bytes(source)
    envelope = canonical_json({
        "schema_version": "1", "producer_id": intent.producer_id,
        "producer_fingerprint": intent.producer_fingerprint, "status": "completed",
        "contract_sha256": intent.contract_sha256, "budget": {"requests": 0},
        "materials": [{"kind": "candidate_source", "path": "main.py", "size": len(source),
                       "sha256": hashlib.sha256(source).hexdigest()}],
    })
    path = value.batch / intent.envelope_path
    path.write_bytes(envelope)
    journal_root = value.batch / ".host-request-journal"
    journal_root.mkdir(mode=0o700, exist_ok=True)
    journal_root.chmod(0o700)
    journal_path = journal_root / "requests"
    identity = HostRequestJournalIdentity(wall_deadline_ns=1, **{name: getattr(intent, name) for name in (
        "launch_id", "journal_id", "run_id", "parent_task_id", "task_id", "intent_sha256",
        "request_timeout_seconds", "max_requests")})
    with HostRequestJournal.create(journal_path, identity):
        pass
    broker = read_host_request_journal(journal_path, expected_identity=identity)
    capture = capture_native_trusted_output(value.batch, intent=intent, terminal_sha256="3" * 64,
        broker=ProducerBrokerObservation(broker.snapshot, journal_path, identity, broker.journal_sha256,
            broker.journal_bytes, True, "inert-fixture", broker.journal_file_identity),
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
    receipt_path = value.batch / "execution-receipt.json"
    receipt_path.write_bytes(canonical_json(receipt.to_dict()))
    receipt_path.chmod(0o600)
    terminal = {"protocol": "lunar-native-trusted-process-terminal-v1", "process_status": "exited_zero",
        "cleanup_status": "cleaned", "gate_released": True, "target_started": True,
        "terminal_sha256": receipt.trusted_execution["terminal_sha256"]}
    # Explicit independent fixture projections. Actual durable receipt readback,
    # capture/broker/material/bundle/draft readers remain unpatched.
    (value.workspace / "fixture-native-receipt-projection.json").write_bytes(canonical_json(receipt.to_dict()))
    (value.workspace / "fixture-native-terminal-projection.json").write_bytes(canonical_json(terminal))
    args = {name: getattr(native, name) for name in (
        "intent", "attestation", "artifact", "contract", "groups", "evaluator_kind",
        "evaluator_fingerprint", "runner_fingerprint", "dependency_sha256", "environment_sha256")}
    prepared_output = prepare_native_trusted_output(value.workspace, **args,
        require_same_attempt_capture=True, require_execution_receipt=True)
    value.admission = prepared_output.admission_plan
    handoff = value.handoff.to_dict()
    handoff.pop("handoff_sha256")
    handoff.update(native_execution_receipt_sha256=receipt.receipt_sha256,
        admission_plan_sha256=value.admission.digest(), envelope_sha256=prepared_output.envelope.envelope_sha256)
    value.handoff = build_python_producer_admission_handoff(**handoff)
    handoff_path = value.batch / PYTHON_PRODUCER_ADMISSION_HANDOFF_NAME
    handoff_path.rename(handoff_path.with_suffix(".reader-original"))
    sidecar = persist_python_producer_admission_handoff_pinned(value.batch, handoff=value.handoff)
    value.pin = sidecar.file_pin
    value.journal = replace(value.journal, admission_sha256=value.admission.digest(),
        native_execution_receipt_sha256=receipt.receipt_sha256,
        python_handoff_sha256=value.handoff.handoff_sha256, python_handoff_file_pin=value.pin,
        candidates=tuple(replace(candidate, bundle_id=item.bundle_id, bundle_sha256=item.bundle_sha256,
            candidate_id=derive_producer_bundle_candidate_id(value.journal.journal_id, index,
                item.bundle_id, item.bundle_sha256))
            for index, (candidate, item) in enumerate(zip(value.journal.candidates, value.admission.bundles))),
        journal_sha256=None)
    (value.batch / "journal.prepared.json").write_bytes(_intent_content(value.journal)[0])
    anchor_path = value.batch / "python-producer-admission-anchor.json"
    anchor_path.rename(anchor_path.with_suffix(".reader-original"))
    value.anchor = project_python_producer_admission_attempt_anchor(value.handoff)
    persist_python_producer_admission_attempt_anchor(value.batch, anchor=value.anchor)
    value.preparation = _NativeTrustedPythonProducerPreparation(
        NativeTrustedProducerRun(_Trap(), receipt, replace(prepared_output, drafts=_Trap(), bundles=_Trap())), sidecar)
    value.prepared_output = prepared_output
    return value


@contextmanager
def _waiting(tmp_path, monkeypatch):
    original = owner_fixture._setup

    def setup(root, patch):
        with monkeypatch.context() as nested:
            nested.setattr(owner_fixture, "_setup", original)
            return _setup(root, patch)

    monkeypatch.setattr(owner_fixture, "_setup", setup)
    with owner_fixture._waiting(tmp_path, monkeypatch) as value:
        value.request_message = _request_from_native_preparation(value.preparation, value.wave.selected_handoff,
            native_plan=value.plan, expected_head_sha256=value.wave.selected_handoff.head_sha256,
            expected_state_sha256=value.wave.selected_handoff.state_sha256)
        yield value


def _reader(value):
    return recovery._BRSRetainedNativePreparationReader(value.owner, original_preparation=value.preparation)


def _files(root):
    return {path: (path.read_bytes(), path.stat()) for path in root.rglob("*") if path.is_file()}


def test_genuine_original_owner_recovers_detached_native_output_without_writes(tmp_path, monkeypatch):
    with _waiting(tmp_path, monkeypatch) as value:
        reader = _reader(value)
        before, head, budget = _files(value.workspace), value.owner._head, dict(value.wave.budget_state)
        result = reader.recover(value.request_message)
        assert result.output.publication_eligible is False
        assert result.output.drafts[0].draft.source_files == {"main.py": "# inert candidate\n"}
        assert result.receipt == value.preparation.run.receipt
        assert result.receipt is not value.preparation.run.receipt
        assert result.output is not value.prepared_output
        assert value.owner._head == head and value.wave.budget_state == budget
        after = _files(value.workspace)
        assert before.keys() == after.keys()
        assert all(before[path][0] == after[path][0] for path in before)
        assert all((before[path][1].st_ino, before[path][1].st_mtime_ns, before[path][1].st_size)
                   == (after[path][1].st_ino, after[path][1].st_mtime_ns, after[path][1].st_size)
                   for path in before if not path.name.endswith("-shm"))
        with pytest.raises(RSILearningError, match="consumed"):
            reader.recover(value.request_message)


@pytest.mark.parametrize("mutation", ["receipt", "source", "capture", "broker-replace",
    "handoff-touch", "handoff-replace", "handoff-symlink"])
def test_original_evidence_drift_refuses_without_refresh_or_retry(tmp_path, monkeypatch, mutation):
    with _waiting(tmp_path, monkeypatch) as value:
        reader = _reader(value)
        handoff = value.batch / PYTHON_PRODUCER_ADMISSION_HANDOFF_NAME
        if mutation == "receipt":
            (value.batch / "execution-receipt.json").write_bytes(b"{}")
        elif mutation == "source":
            (value.batch / value.native.intent.output_directory / "main.py").write_bytes(b"# changed\n")
        elif mutation == "capture":
            (value.batch / "native-trusted-output-capture.json").write_bytes(b"{}")
        elif mutation == "broker-replace":
            broker = value.batch / ".host-request-journal/requests"
            saved = broker.with_suffix(".replacement")
            saved.write_bytes(broker.read_bytes())
            saved.chmod(0o600)
            broker.unlink()
            saved.rename(broker)
        elif mutation == "handoff-touch":
            info = handoff.stat()
            os.utime(handoff, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000))
        else:
            saved = handoff.with_suffix(".replacement")
            saved.write_bytes(handoff.read_bytes())
            saved.chmod(0o600)
            handoff.unlink()
            if mutation == "handoff-replace":
                saved.rename(handoff)
            else:
                handoff.symlink_to(saved.name)
        with pytest.raises(RSILearningError, match="read_invalid"):
            reader.recover(value.request_message)
        with pytest.raises(RSILearningError, match="consumed"):
            reader.recover(value.request_message)


def test_request_mismatch_refuses_before_native_or_handoff_reads(tmp_path, monkeypatch):
    with _waiting(tmp_path, monkeypatch) as value:
        reader = _reader(value)
        wire = json.loads(value.request_message.payload)
        wire["native_execution_receipt_sha256"] = "8" * 64
        wire["output"]["execution_receipt_sha256"] = "8" * 64
        message = build_brs_owner_publication_request(value.wave.selected_handoff, canonical_json(wire))
        monkeypatch.setattr(recovery, "recover_native_trusted_producer", _forbidden)
        monkeypatch.setattr(recovery, "read_python_producer_admission_handoff_pinned", _forbidden)
        with pytest.raises(RSILearningError, match="read_invalid"):
            reader.recover(message)


@pytest.mark.parametrize("moment", ["construct", "recover"])
def test_worker_thread_cannot_use_original_owner_reader(tmp_path, monkeypatch, moment):
    with _waiting(tmp_path, monkeypatch) as value:
        reader = _reader(value) if moment == "recover" else None
        with ThreadPoolExecutor(max_workers=1) as pool:
            operation = (lambda: _reader(value)) if reader is None else (lambda: reader.recover(value.request_message))
            with pytest.raises(RSILearningError):
                pool.submit(operation).result(timeout=10)


@pytest.mark.parametrize("field", ["_phase", "_head", "_payload"])
def test_constructor_captured_owner_scope_cannot_advance_during_read(tmp_path, monkeypatch, field):
    with _waiting(tmp_path, monkeypatch) as value:
        reader = _reader(value)
        original = getattr(value.owner, field)
        setattr(value.owner, field, "before" if field == "_phase" else "f" * 64 if field == "_head" else b"{}")
        try:
            with pytest.raises(RSILearningError):
                reader.recover(value.request_message)
        finally:
            setattr(value.owner, field, original)


def test_late_owner_control_failure_discards_recovered_output(tmp_path, monkeypatch):
    with _waiting(tmp_path, monkeypatch) as value:
        reader = _reader(value)
        monkeypatch.setattr(attempt_module, "_BRS_NATIVE_READER_TERMINAL_HOOK", value.wave.channel.close)
        with pytest.raises(RSILearningError):
            reader.recover(value.request_message)


@pytest.mark.parametrize("name", ["_selected_episode_id", "_selected_handoff_sha256", "_queue"])
def test_channel_shape_drift_refuses_without_foreign_callbacks(tmp_path, monkeypatch, name):
    with _waiting(tmp_path, monkeypatch) as value:
        reader = _reader(value)
        original = getattr(value.wave.channel, name)
        setattr(value.wave.channel, name, _Trap())
        try:
            with pytest.raises(RSILearningError):
                reader.recover(value.request_message)
        finally:
            setattr(value.wave.channel, name, original)


def test_comparison_receipt_is_frozen_without_reading_worker_drafts(tmp_path, monkeypatch):
    with _waiting(tmp_path, monkeypatch) as value:
        reader = _reader(value)
        value.preparation.run.receipt.owner_identity["pid"] = 999
        # Mutation of the caller's DTO cannot mutate the retained projection.
        assert reader._original.run.receipt.owner_identity["pid"] != 999
        assert reader.recover(value.request_message).receipt.owner_identity["pid"] != 999


def test_string_workspace_is_normalized_by_the_original_input_context(tmp_path, monkeypatch):
    with _waiting(tmp_path, monkeypatch) as value:
        object.__setattr__(value.native, "workspace", str(value.workspace))
        reader = _reader(value)
        assert type(reader._arguments["workspace"]) is type(value.workspace)
        assert reader.recover(value.request_message).status == "recovered"


@pytest.mark.parametrize("timing", ["before", "during"])
def test_current_native_cancellation_refuses_without_changing_deadline(tmp_path, monkeypatch, timing):
    with _waiting(tmp_path, monkeypatch) as value:
        control = SolveExecutionControl(600)
        object.__setattr__(value.native, "execution_control", control)
        reader = _reader(value)
        original = (control.started_at, control.deadline, control.timeout_seconds)
        if timing == "before":
            control.cancel()
        else:
            monkeypatch.setattr(attempt_module, "_BRS_NATIVE_READER_TERMINAL_HOOK", control.cancel)
        with pytest.raises(SolveExecutionCancelled):
            reader.recover(value.request_message)
        assert (control.started_at, control.deadline, control.timeout_seconds) == original


def test_expired_native_deadline_is_never_renewed(tmp_path, monkeypatch):
    with _waiting(tmp_path, monkeypatch) as value:
        now = [0.0]
        control = SolveExecutionControl(5, started_at=0.0, clock=lambda: now[0])
        object.__setattr__(value.native, "execution_control", control)
        reader = _reader(value)
        now[0] = 6.0
        with pytest.raises(SolveExecutionBudgetExceeded):
            reader.recover(value.request_message)
        assert control.deadline == 5.0


@pytest.mark.parametrize("change", ["deadline", "control-replaced", "cancelled-replaced", "callback-owner-drift"])
def test_original_control_pin_and_callback_scope_cannot_drift(tmp_path, monkeypatch, change):
    with _waiting(tmp_path, monkeypatch) as value:
        control = SolveExecutionControl(600)
        cancelled = lambda: False
        object.__setattr__(value.native, "execution_control", control)
        object.__setattr__(value.native, "cancelled", cancelled)
        if change == "callback-owner-drift":
            def drift():
                value.owner._phase = "before"
                return False
            object.__setattr__(value.native, "cancelled", drift)
        # Let the callback drift only after the constructor has retained scope.
        original_callback = value.native.cancelled
        if change == "callback-owner-drift":
            state = [False]
            def conditional_drift():
                if state[0]:
                    return original_callback()
                return False
            object.__setattr__(value.native, "cancelled", conditional_drift)
        reader = _reader(value)
        if change == "deadline":
            control.deadline += 1
        elif change == "control-replaced":
            object.__setattr__(value.native, "execution_control", SolveExecutionControl(600))
        elif change == "cancelled-replaced":
            object.__setattr__(value.native, "cancelled", lambda: False)
        else:
            state[0] = True
        with pytest.raises(RSILearningError):
            reader.recover(value.request_message)


@pytest.mark.parametrize("name", ["check", "is_cancelled", "_now"])
def test_control_method_shadow_refuses_before_invocation(tmp_path, monkeypatch, name):
    with _waiting(tmp_path, monkeypatch) as value:
        control = SolveExecutionControl(600)
        object.__setattr__(value.native, "execution_control", control)
        reader = _reader(value)
        control.cancel()
        setattr(control, name, _forbidden)
        with pytest.raises(RSILearningError):
            reader.recover(value.request_message)


@pytest.mark.parametrize("change", ["cancel", "timeout"])
def test_last_source_hook_cancellation_or_timeout_refuses(tmp_path, monkeypatch, change):
    with _waiting(tmp_path, monkeypatch) as value:
        now, armed = [0.0], [False]
        control = SolveExecutionControl(5, started_at=0.0, clock=lambda: now[0])
        object.__setattr__(value.native, "execution_control", control)
        original = value.gateway.rsi_fingerprint_config

        def hook():
            result = original()
            if armed[0]:
                if change == "cancel":
                    control.cancel()
                else:
                    now[0] = 6.0
            return result

        monkeypatch.setattr(value.gateway, "rsi_fingerprint_config", hook)
        reader = _reader(value)
        monkeypatch.setattr(attempt_module, "_BRS_NATIVE_READER_TERMINAL_HOOK", lambda: armed.__setitem__(0, True))
        with pytest.raises(SolveExecutionCancelled if change == "cancel" else SolveExecutionBudgetExceeded):
            reader.recover(value.request_message)


def test_foreign_metaclass_is_rejected_without_hash_or_equality_callbacks():
    class Meta(type):
        def __hash__(cls):
            _forbidden()
            return 0

        def __eq__(cls, _other):
            _forbidden()

    class Foreign(metaclass=Meta):
        pass

    with pytest.raises(RSILearningError, match="shape_invalid"):
        recovery._copy(Foreign())


def test_rebound_dto_allowlist_refuses_without_instantiating_new_type(tmp_path, monkeypatch):
    with _waiting(tmp_path, monkeypatch) as value:
        reader = _reader(value)
        monkeypatch.setattr(recovery, "_DTOS", (*recovery._DTOS, _Trap))
        with pytest.raises(RSILearningError):
            reader.recover(value.request_message)


@pytest.mark.parametrize("name", ["_context", "recover_native_trusted_producer"])
def test_same_code_different_globals_alias_refuses(tmp_path, monkeypatch, name):
    with _waiting(tmp_path, monkeypatch) as value:
        reader = _reader(value)
        original = getattr(recovery, name)
        clone = FunctionType(original.__code__, {**original.__globals__, "_fail": _forbidden},
                             original.__name__, original.__defaults__, original.__closure__)
        clone.__module__, clone.__qualname__ = original.__module__, original.__qualname__
        clone.__kwdefaults__ = original.__kwdefaults__
        monkeypatch.setattr(recovery, name, clone)
        with pytest.raises(RSILearningError):
            reader.recover(value.request_message)


@pytest.mark.parametrize("group", ["context", "scheduler", "receipt", "output", "handoff", "control"])
def test_simultaneously_rebound_canonical_entry_globals_refuse(tmp_path, monkeypatch, group):
    from lunar_evolution import native_trusted_scheduler as scheduler
    from lunar_evolution import python_producer_admission_handoff as handoff_module
    from lunar_evolution import rsi_python_scheduler_inputs as scheduler_inputs

    with _waiting(tmp_path, monkeypatch) as value:
        reader = _reader(value)
        if group == "context":
            bindings = ((scheduler_inputs, "_context"), (recovery, "_context"))
        elif group == "scheduler":
            bindings = ((scheduler, "recover_native_trusted_producer"),
                        (recovery, "recover_native_trusted_producer"))
        elif group == "receipt":
            bindings = ((receipt_module, "recover_native_trusted_execution_receipt"),
                        (scheduler, "recover_native_trusted_execution_receipt"),
                        (output_module, "recover_native_trusted_execution_receipt"))
        elif group == "output":
            bindings = ((output_module, "prepare_native_trusted_output"),
                        (scheduler, "prepare_native_trusted_output"))
        elif group == "handoff":
            bindings = ((handoff_module, "read_python_producer_admission_handoff_pinned"),
                        (recovery, "read_python_producer_admission_handoff_pinned"))
        else:
            bindings = ((SolveExecutionControl, "check"),)
        original = getattr(*bindings[0])
        clone = FunctionType(original.__code__, dict(original.__globals__), original.__name__,
                             original.__defaults__, original.__closure__)
        clone.__module__, clone.__qualname__ = original.__module__, original.__qualname__
        clone.__kwdefaults__ = original.__kwdefaults__
        for module, name in bindings:
            monkeypatch.setattr(module, name, clone)
        with pytest.raises(RSILearningError):
            reader.recover(value.request_message)


@pytest.mark.parametrize("name", ["_context", "_request_from_native_preparation",
    "recover_native_trusted_producer", "read_python_producer_admission_handoff_pinned", "_request"])
def test_rebound_live_reader_dependencies_refuse_before_invocation(tmp_path, monkeypatch, name):
    with _waiting(tmp_path, monkeypatch) as value:
        reader = _reader(value)
        monkeypatch.setattr(recovery, name, _forbidden)
        with pytest.raises(RSILearningError):
            reader.recover(value.request_message)


def test_self_consistent_replacement_receipt_cannot_replace_constructor_comparison(tmp_path, monkeypatch):
    with _waiting(tmp_path, monkeypatch) as value:
        reader = _reader(value)
        wire = value.preparation.run.receipt.to_dict()
        wire["owner_identity"]["start_time"] += 1
        wire["receipt_sha256"] = _digest_without(wire, "receipt_sha256")
        replacement = canonical_json(wire)
        (value.workspace / "fixture-native-receipt-projection.json").write_bytes(replacement)
        (value.batch / "execution-receipt.json").write_bytes(replacement)
        with pytest.raises(RSILearningError, match="read_invalid"):
            reader.recover(value.request_message)


@pytest.mark.parametrize("part", ["receipt", "plan", "output"])
def test_callback_or_shadow_in_consumed_evidence_refuses_without_invocation(tmp_path, monkeypatch, part):
    with _waiting(tmp_path, monkeypatch) as value:
        if part == "receipt":
            object.__setattr__(value.preparation.run.receipt, "owner_identity", _Trap())
        elif part == "plan":
            object.__setattr__(value.owner._plan.request, "__dataclass_fields__", _Trap())
        else:
            object.__setattr__(value.preparation.run.output.envelope, "budget", _Trap())
        with pytest.raises(RSILearningError):
            _reader(value)


@pytest.mark.parametrize("value", [object(), None])
def test_unregistered_or_duck_typed_owner_refuses(value):
    with pytest.raises(RSILearningError, match="owner_invalid"):
        recovery._BRSRetainedNativePreparationReader(value, original_preparation=object())
