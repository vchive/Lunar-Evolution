"""Live completion gates over real SQLite histories and explicitly inert native doubles.

The fast fixture below doubles launch/native publication inspection only. It does
not claim natural provider acceptance; genuine original-owner coverage is separate.
"""

from __future__ import annotations

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest
import test_rsi_brs_rejected_lifecycle as lifecycle_fixture
import test_rsi_python_brs_publication_inputs as input_fixture
from test_native_trusted_scheduler import _context
from test_rsi_python_brs_publication_mailbox import _ready
from test_rsi_python_brs_result_delivery import _response, _transaction

import lunar_evolution.rsi_brs_native_completion as completion
from lunar_evolution import RSILedger
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.producer_bundle_handoff import BundleGroup
from lunar_evolution.rsi_brs_mailbox_evidence import (
    build_brs_mailbox_binding,
    build_brs_mailbox_observation,
)
from lunar_evolution.rsi_brs_native_process_evidence import PROTOCOL, ROLE
from lunar_evolution.rsi_brs_reconcile import FIELD, register_brs_selected_obligation
from lunar_evolution.rsi_learning import PracticeEpisode, RSILearningError
from lunar_evolution.rsi_native_gateway import NativeRSISolverGateway
from lunar_evolution.rsi_native_provenance import persist_native_rsi_provenance
from lunar_evolution.rsi_native_scheduler import (
    NativeRSISchedulerContext,
    NativeRSISchedulerProvider,
)
from lunar_evolution.rsi_python_brs_publication_mailbox import (
    BRSOwnerPublicationMailbox,
    build_brs_owner_publication_request,
)
from lunar_evolution.rsi_python_brs_terminal_lifecycle import (
    BINDING_PROTOCOL,
    brs_terminal_evidence_namespace,
    build_brs_terminal_observation,
    open_brs_terminal_lifecycle,
)

prepared = input_fixture.prepared
inert_only = lifecycle_fixture.inert_only
sealed_launch = lifecycle_fixture.sealed_launch
tmp_path = lifecycle_fixture.tmp_path
HEX = "a" * 64


def _seal(value, field):
    value[field] = hashlib.sha256(canonical_json({key: item for key, item in value.items()
                                               if key != field}, maximum=8 * 1024 * 1024)).hexdigest()
    return value


@pytest.fixture
def live(prepared, tmp_path, monkeypatch, request):
    """Actual running episode/claim, original fence and four mailbox observations."""
    worker_receipt_observed = getattr(request, "param", True)
    value = prepared
    request = value.plan.request
    plan = replace(value.plan, task_id=request.episode_id, plan_sha256=None)
    ledger = RSILedger(tmp_path / "completion.sqlite3")
    state = {"run_id": plan.run_id, "intents": {request.episode_id: {"request": request.to_dict()}}, FIELD: {}}
    created = ledger.create_run(plan.run_id, request.digest(), {"mode": "brs", "intents": state["intents"]})
    run = ledger.transition(plan.run_id, state="running", expected_record_sha256=created.record_sha256)
    episode = PracticeEpisode(request.episode_id, plan.run_id, request.contract_sha256,
                              request.evaluator_sha256, request.environment_sha256,
                              request.memory_snapshot_sha256, request.solver_id, "running",
                              request_sha256=request.digest(), wave=0, ordinal=0)
    row = ledger.create_episode_record(episode)
    with ledger.controller_lock(plan.run_id):
        root = ledger.write_controller_checkpoint(plan.run_id, state, expected_sha256=None)
    handoff = replace(value.handoff, head_sha256=root,
                      state_sha256=hashlib.sha256(canonical_json(state)).hexdigest())
    claim = ledger.claim_native_episode(request, plan_sha256=plan.plan_sha256)
    with ledger.controller_lock(plan.run_id):
        register_brs_selected_obligation(ledger, handoff, native_plan_sha256=plan.plan_sha256,
            controller_checkpoint_sha256=root, episode_record_sha256=row.record_sha256,
            expected_run_record_sha256=run.record_sha256, expected_native_claim_sha256=claim.claim_sha256)
    native = _seal({"protocol": PROTOCOL, "role": ROLE, "status": "unknown",
                    "reason": "native_context_unavailable", "native_plan_sha256": plan.plan_sha256,
                    "request_sha256": request.digest(), "workspace": None, "references": None,
                    "entries": {}}, "binding_sha256")
    obligation = ledger.controller_brs_reconcile_obligations(plan.run_id)[request.episode_id]
    from lunar_evolution.rsi_brs_reconcile import BRSReconcileObligation
    mailbox = build_brs_mailbox_binding(obligation=BRSReconcileObligation.from_dict(obligation),
        handoff=handoff, run_record_sha256=run.record_sha256, episode_record_sha256=row.record_sha256,
        native_process=native)
    message_wire = json.loads(_ready(handoff).payload)
    message_wire["native_plan_sha256"] = plan.plan_sha256
    message = build_brs_owner_publication_request(handoff, canonical_json(message_wire))
    transaction = _transaction(handoff)
    journal = replace(transaction.published_journal, journal_id=plan.journal_id,
                      parent_task_id=plan.parent_task_id, task_id=plan.task_id,
                      contract_sha256=request.contract_sha256, evaluator_fingerprint=request.evaluator_sha256,
                      environment_sha256=request.environment_sha256, journal_sha256=None)
    transaction = replace(transaction, journal=journal, terminal_journal=journal, published_journal=journal)
    response = _response(transaction, message, handoff)
    manifest = _seal({"journal_id": journal.journal_id, "archive_after_sha256": journal.archive_after_sha256,
                      "state_after_sha256": journal.state_after_sha256}, "manifest_sha256")
    lineage = {"batches": [{"state": "terminal"}],
               "head": {"journal_id": journal.journal_id, "terminal_sha256": journal.terminal_marker_sha256}}
    publication = {"lineage": lineage, "journal": journal.to_dict(), "manifest": manifest}
    with ledger.controller_lock(plan.run_id):
        head, current = ledger.controller_checkpoint(plan.run_id)
        head = ledger.write_controller_checkpoint(plan.run_id,
            {**current, "producer_publication_lineage": lineage}, expected_sha256=head)
        previous = None
        namespace = "rsi-brs-mailbox:" + mailbox["obligation_sha256"]
        with ledger.controller_lock(namespace):
            for index, stage in enumerate(("owner_capture", "request_observed", "response_generated", "transport_observed")):
                record = build_brs_mailbox_observation(mailbox, stage=stage, root_checkpoint_sha256=head,
                    mailbox_state=("open", "inflight", "inflight", "delivered")[index],
                    worker_receipt_observed=index == 3 and worker_receipt_observed, request=message if index else None,
                    response=response if index >= 2 else None)
                previous = ledger.append_brs_mailbox_observation(mailbox, record, expected_sha256=previous)
    native_root = tmp_path / "context"
    native_root.mkdir()
    native_context = _context(native_root)
    context = NativeRSISchedulerContext(value.workspace, native_root / "producer", native_context.intent,
        native_context.attestation, native_context.artifact, native_context.broker, native_context.contract,
        (BundleGroup("candidate", "main.py", ("main.py",)),), "local", HEX, HEX, HEX, HEX, object(),
        failure_ledger=ledger)
    provider = NativeRSISchedulerProvider(context)
    inputs = SimpleNamespace(launch_binding_sha256="b" * 64)
    # Explicit component doubles: no fake native proof is represented as genuine acceptance.
    monkeypatch.setattr(NativeRSISchedulerProvider, "_inputs", lambda *_a, **_k: inputs)
    monkeypatch.setattr(NativeRSISchedulerProvider, "rsi_fingerprint_config", lambda *_a: {"source": "original"})
    monkeypatch.setattr(completion, "_memory_from_request_inputs", lambda *_a: None)
    monkeypatch.setattr(completion, "_assert_plan_binding", lambda *_a: None)
    monkeypatch.setattr(completion, "_publication", lambda *_a, **_k: journal.digest())
    with ThreadPoolExecutor(max_workers=1) as pool:
        thread = pool.submit(threading.current_thread).result(timeout=2)
        binding = _seal({"protocol": BINDING_PROTOCOL, "mailbox_binding": mailbox,
                        "owner_thread_id": threading.get_ident(), "worker_thread_id": thread.ident,
                        "future_id": "future-1", "executor_id": f"executor-{id(pool):x}",
                        "thread_id": f"thread-{id(thread):x}"}, "binding_sha256")
        delivery = {"request_fields": [message.run_id, message.episode_id, message.handoff_sha256,
                                       message.payload.decode(), message.request_sha256],
                    "response_fields": [response.run_id, response.episode_id, response.handoff_sha256,
                                        response.request_sha256, response.payload.decode(), response.response_sha256],
                    "publication": publication}
        result = SimpleNamespace(provider=provider, plan=plan, request=request, ledger=ledger, pool=pool,
            binding=binding, delivery=delivery, inputs=inputs, head=head, terminal_head=None,
            namespace=brs_terminal_evidence_namespace(binding), journal=journal)
        _append_stage(result, "delivery", delivery)
        yield result


def _append_stage(value, stage, facts):
    record = build_brs_terminal_observation(value.binding, stage=stage,
        root_checkpoint_sha256=value.head, facts=facts)
    with value.ledger.controller_lock(value.plan.run_id), value.ledger.controller_lock(value.namespace):
        value.terminal_head = value.ledger.append_brs_terminal_observation(value.binding, record,
                                                                         expected_sha256=value.terminal_head)


def _observe(value, **kwargs):
    return value.pool.submit(completion._observe, value.provider, value.request, value.plan, **kwargs).result(timeout=3)


@pytest.mark.parametrize("live", [False, True], indirect=True)
def test_actual_durable_stage_two_and_three_share_only_original_completion_pin(live):
    with pytest.raises(RSILearningError, match="callback_gate_required"):
        _observe(live)
    _append_stage(live, "callback_started", {"attempt": 1})
    before = _observe(live)
    _append_stage(live, "callback_finished", {"attempt": 1, "outcome": "returned"})
    after = _observe(live, expected_pin=before[-1])
    assert after[-1] == before[-1]
    assert live.ledger.episode_result(live.request.episode_id) is None
    assert live.ledger.get_episode(live.request.episode_id).state == "running"


def test_unknown_callback_can_never_supply_second_read(live):
    _append_stage(live, "callback_started", {"attempt": 1})
    pin = _observe(live)[-1]
    _append_stage(live, "callback_finished", {"attempt": 1, "outcome": "unknown"})
    with pytest.raises(RSILearningError, match="callback_gate_required"):
        _observe(live, expected_pin=pin)


def test_owner_thread_cannot_adopt_worker_completion(live):
    _append_stage(live, "callback_started", {"attempt": 1})
    with pytest.raises(RSILearningError, match="original_worker_required"):
        completion._observe(live.provider, live.request, live.plan)


def test_changed_original_provider_source_fingerprint_refuses_second_read(live, monkeypatch):
    _append_stage(live, "callback_started", {"attempt": 1})
    pin = _observe(live)[-1]
    monkeypatch.setattr(NativeRSISchedulerProvider, "rsi_fingerprint_config", lambda *_a: {"source": "changed"})
    with pytest.raises(RSILearningError, match="original_pin_drift"):
        _observe(live, expected_pin=pin)


def test_changed_current_c2_root_cannot_refresh_original_pin(live):
    _append_stage(live, "callback_started", {"attempt": 1})
    pin = _observe(live)[-1]
    with live.ledger.controller_lock(live.plan.run_id):
        head, state = live.ledger.controller_checkpoint(live.plan.run_id)
        live.ledger.write_controller_checkpoint(live.plan.run_id, {**state, "foreign_progress": True},
                                                expected_sha256=head)
    with pytest.raises(RSILearningError, match="original_pin_drift"):
        _observe(live, expected_pin=pin)


def test_wrong_claim_plan_never_enters_native_publication_reader(live, monkeypatch):
    _append_stage(live, "callback_started", {"attempt": 1})
    with live.ledger._connect() as connection:
        connection.execute("UPDATE rsi_native_episode_claims SET plan_sha256 = ? WHERE episode_id = ?",
                           ("c" * 64, live.request.episode_id))
    monkeypatch.setattr(completion, "_publication", lambda *_a, **_k: pytest.fail("foreign claim reached native reader"))
    with pytest.raises(RSILearningError):
        _observe(live)


@pytest.mark.parametrize("fault", ["provider-subclass", "request-method", "request-subclass", "pin-equality"])
def test_reader_input_shapes_refuse_foreign_hooks(live, monkeypatch, fault):
    _append_stage(live, "callback_started", {"attempt": 1})
    calls = []

    def forbidden(*_a, **_k):
        calls.append(fault)
        pytest.fail("foreign completion input hook executed")

    options = {}
    if fault == "provider-subclass":
        class Provider(NativeRSISchedulerProvider):
            _inputs = forbidden
        live.provider = Provider(live.provider.context)
    elif fault == "request-method":
        object.__setattr__(live.request, "digest", forbidden)
    elif fault == "request-subclass":
        class Request(type(live.request)):
            to_dict = forbidden
            digest = forbidden
        polluted = object.__new__(Request)
        polluted.__dict__.update(live.request.__dict__)
        object.__setattr__(live.plan, "request", polluted)
    else:
        class Comparison(bytes):
            __eq__ = forbidden
        options["expected_pin"] = completion._BRSNativeCompletionPin(Comparison(b"foreign"))
    with pytest.raises(RSILearningError):
        _observe(live, **options)
    assert calls == []


@pytest.mark.parametrize("replacement", ["same-bytes", "self-consistent"])
def test_success_provenance_is_read_only_missing_replaced_or_conflicting(live, monkeypatch, replacement):
    _append_stage(live, "callback_started", {"attempt": 1})
    # This test exercises real create-only provenance bytes/inode/exclusivity,
    # independently of the native candidate reader's own acceptance inventory.
    from test_rsi_native_provenance import payload

    from lunar_evolution.rsi_native_candidate import (
        NativeCandidateRecord,
        NativeEvaluationReceipt,
        NativeExecutionReceipt,
        NativePublicationReceipt,
    )
    from lunar_evolution.rsi_native_gateway import NativeRSIReceiptBundle
    wire = payload()
    bundle = NativeRSIReceiptBundle(*(kind.from_dict(wire["bundle"][name]) for kind, name in (
        (NativeCandidateRecord, "candidate"), (NativeExecutionReceipt, "execution"),
        (NativeEvaluationReceipt, "evaluation"), (NativePublicationReceipt, "publication"))))
    pin = _observe(live)[-1]
    observed = completion._BRSPublishedNativeCompletion(bundle, canonical_json(wire), pin)
    monkeypatch.setattr(completion, "read_brs_live_published_completion", lambda *_a, **_k: observed)
    batch = live.provider.provenance_batch
    batch.mkdir(parents=True, exist_ok=True)
    with pytest.raises(ValueError):
        completion.read_brs_live_published_provenance(live.provider, live.request, live.plan,
            expected_pin=pin, expected_provenance_sha256="e" * 64)
    original_digest = persist_native_rsi_provenance(batch, wire)
    saved = completion.read_brs_live_published_provenance(live.provider, live.request, live.plan,
        expected_pin=pin, expected_provenance_sha256=original_digest)
    assert saved.provenance_sha256 is not None
    path = batch / "native-rsi.provenance.json"
    original = path.read_bytes()
    changed_wire = {**wire, "input_binding_sha256": "f" * 64}
    with monkeypatch.context() as changed:
        changed.setattr(completion, "read_brs_live_published_completion", lambda *_a, **_k:
                        replace(observed, provenance_bytes=canonical_json(changed_wire)))
        with pytest.raises(RSILearningError, match="published_provenance_drift"):
            completion.read_brs_live_published_provenance(live.provider, live.request, live.plan,
                expected_pin=pin, expected_provenance_sha256=original_digest)
    assert path.read_bytes() == original
    path.rename(path.with_suffix(".original"))
    path.write_bytes(original)
    if replacement == "self-consistent":
        value = json.loads(original)
        info = path.stat()
        value["file_identity"] = {"device": info.st_dev, "inode": info.st_ino}
        value.pop("provenance_sha256")
        value["provenance_sha256"] = hashlib.sha256(canonical_json(value)).hexdigest()
        path.write_bytes(canonical_json(value))
    path.chmod(0o400)
    if replacement == "self-consistent":
        assert completion.read_native_rsi_provenance(batch)["provenance_sha256"] != original_digest
    with pytest.raises((ValueError, RSILearningError)):
        completion.read_brs_live_published_provenance(live.provider, live.request, live.plan,
            expected_pin=pin, expected_provenance_sha256=original_digest)


@pytest.mark.parametrize("digest", [None, True, "f" * 63, "g" * 64, b"f" * 64])
def test_original_p_digest_is_required_before_native_or_file_observation(monkeypatch, digest):
    def forbidden(*_a, **_k):
        pytest.fail("invalid original P digest reached a native observer")

    monkeypatch.setattr(completion, "read_brs_live_published_completion", forbidden)
    monkeypatch.setattr(completion, "read_native_rsi_provenance", forbidden)
    with pytest.raises(RSILearningError, match="published_provenance_pin_invalid"):
        completion.read_brs_live_published_provenance(object(), object(), object(), expected_pin=object(),
            expected_provenance_sha256=digest)


@pytest.fixture
def rejection_components(live, monkeypatch):
    """Real P bytes/file pins; explicit doubles only for upstream native observation."""
    from test_rsi_native_rejection import rejection_evidence

    from lunar_evolution.rsi_native_rejection import persist_native_rsi_rejection_provenance

    evidence = replace(rejection_evidence(count=1), ledger_identity=live.provider._failure_ledger_identity)
    batch = live.provider.provenance_batch
    batch.mkdir(parents=True, exist_ok=True)
    _digest_value, file_pin = persist_native_rsi_rejection_provenance(batch, evidence, retained_bytes=0)
    saved = completion.read_native_rsi_rejection_provenance(batch, expected_file_pin=file_pin)
    pin = completion._BRSNativeCompletionPin(b"original-component-pin")
    inputs = SimpleNamespace(launch_binding_sha256=saved.input_binding_sha256)
    snapshot = {"native_claim": saved.claim, "pins": {"original": True}, "roots": ["original"]}
    publication = {"lineage": {"batches": [{"episode_id": saved.plan.request.episode_id,
        "journal_id": saved.plan.journal_id, "rejection_provenance": {
            "file_pin": file_pin.to_dict(), "provenance_sha256": saved.provenance_sha256}}]}}
    observation = SimpleNamespace(terminal=saved.terminal,
        execution_receipt_sha256s=saved.execution_receipt_sha256s,
        evaluation_receipt_sha256s=saved.evaluation_receipt_sha256s,
        retained_evidence_sha256s=saved.retained_evidence_sha256s)
    recovery = SimpleNamespace(receipt=SimpleNamespace(receipt_sha256=saved.producer_execution_receipt_sha256),
                               output=SimpleNamespace(output_capture_sha256=saved.producer_output_sha256))
    monkeypatch.setattr(completion, "_observe", lambda *_a, **_k:
                        (inputs, {}, snapshot, publication, saved.terminal, pin))
    monkeypatch.setattr(NativeRSISchedulerProvider, "_native_rejection_snapshot",
                        lambda *_a, **_k: (recovery, observation))
    return SimpleNamespace(provider=live.provider, evidence=saved, pin=pin, file_pin=file_pin,
        inputs=inputs, snapshot=snapshot, observation=observation, recovery=recovery, batch=batch)


def _read_rejection_components(value):
    return completion.read_brs_live_rejection_completion(value.provider, value.evidence.plan.request,
        value.evidence.plan, expected_pin=value.pin)


def _published_file_snapshot(path):
    info = path.stat()
    # Reading original P may advance atime. All content/identity and modification
    # metadata remain pinned, including nanosecond mtime and ctime.
    identity = (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_uid,
                info.st_gid, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    return identity, path.read_bytes()


def test_rejection_second_read_reconstructs_the_original_receipts_and_preserves_p(rejection_components):
    value = rejection_components
    path = value.batch / value.file_pin.name
    before = path.stat(), path.read_bytes()
    assert _read_rejection_components(value) == (value.evidence, value.pin)
    assert _read_rejection_components(value) == (value.evidence, value.pin)
    assert (path.stat(), path.read_bytes()) == before


@pytest.mark.parametrize("fault", ["missing", "same-bytes-new-inode", "input", "claim", "native-output"])
def test_rejection_second_read_refuses_changed_p_and_native_association(rejection_components, fault):
    value = rejection_components
    _read_rejection_components(value)
    path = value.batch / value.file_pin.name
    if fault in {"missing", "same-bytes-new-inode"}:
        raw = path.read_bytes()
        path.rename(path.with_suffix(".original"))
        if fault != "missing":
            path.write_bytes(raw)
            path.chmod(0o400)
    elif fault == "input":
        value.inputs.launch_binding_sha256 = "f" * 64
    elif fault == "claim":
        value.snapshot["native_claim"] = replace(value.evidence.claim, created_at="2026-10-15T00:00:00Z")
    else:
        value.recovery.output.output_capture_sha256 = "f" * 64
    with pytest.raises((RSILearningError, ValueError)):
        _read_rejection_components(value)


@contextmanager
def _genuine_reader(root, patch, *, outcome="all_rejected", rewrite_success_p=False):
    """Use original worker, native readers, publication and callback observations.

    Candidate/evaluator processes and the native process result retain the same
    explicit inert boundaries as the rejected lifecycle inventory. Claim/result
    plumbing here is a fixture operation, not ordinary native gateway acceptance.
    """
    f = lifecycle_fixture
    assert outcome in {"all_rejected", "published"}
    if outcome == "published":
        patch.setattr(f.rejection_fixture.candidate_evaluation, "_bounded_process_bytes",
                      f.rejection_fixture._inert_candidate_process)
    context = f.build_context(root / "pipeline")
    original_setup, original_plan = f.owner_fixture._setup, f.owner_fixture._plan

    def plan(binding, request, memory):
        return replace(original_plan(binding, request, memory),
                       evaluator_kind=context.config.evaluator_kind, plan_sha256=None)

    patch.setattr(f.owner_fixture, "_plan", plan)
    receipt_reader = f.FunctionType(f.retained_fixture._receipt_projection.__code__,
                                   vars(f.receipt_module), "_receipt_projection")
    terminal_reader = f.FunctionType(f.retained_fixture._terminal_projection.__code__,
                                    vars(f.attempt_module), "_terminal_projection")
    patch.setattr(f.attempt_module, "_BRS_NATIVE_READER_TERMINAL_HOOK", None, raising=False)
    patch.setattr(f.receipt_module, "build_native_trusted_execution_receipt", receipt_reader)
    for module in (f.attempt_module, f.output_module, f.receipt_module, f.process_module):
        patch.setattr(module, "recover_native_trusted_attempt", terminal_reader)
    value = f.rejection_fixture._native_setup(
        root, patch, count=1, context=context, original_owner_setup=original_setup,
    )
    receipt = f.parse_producer_execution_receipt(json.loads((value.batch / "execution-receipt.json").read_bytes()))
    value.preparation = f._NativeTrustedPythonProducerPreparation(
        f.NativeTrustedProducerRun(f.retained_fixture._Trap(), receipt,
            replace(value.prepared_output, drafts=f.retained_fixture._Trap(), bundles=f.retained_fixture._Trap())),
        f.PythonProducerAdmissionHandoffSidecar(value.handoff, value.pin),
    )
    f.terminal_fixture._seed_original_native_records(value)
    registration = json.loads((value.batch / "process-registration.json").read_bytes())
    relative = registration["target_execution_snapshot_relative_path"]
    if relative is not None:
        target = value.batch / relative
        target.parent.mkdir(mode=0o700)
        target.write_bytes((value.native.producer_root / value.native.intent.executable_relative).read_bytes())
        target.chmod(0o500)
    for name in ("journal.prepared.json", "python-producer-admission-anchor.json"):
        path = value.batch / name
        path.rename(path.with_name(name + ".reader-input"))
    # Freeze the real provider and callback before the original live capture.
    value.provider = NativeRSISchedulerProvider(value.native)
    messages, release, abort = f.Queue(), f.Event(), f.Event()
    value.observations = []

    def callback(delivery):
        assert delivery.publication_status == outcome
        try:
            if outcome == "all_rejected":
                evidence, pin = completion.read_brs_live_rejection_completion(value.provider, value.request, value.plan)
            else:
                observed = completion.read_brs_live_published_completion(value.provider, value.request, value.plan)
                batch = value.provider.provenance_batch
                path = batch / "native-rsi.provenance.json"
                assert not path.exists()
                # This fixture's fixed callback is the sole writer. The product
                # completion readers stay read-only, including their stage-3 read.
                original_digest = persist_native_rsi_provenance(batch, json.loads(observed.provenance_bytes))
                evidence = completion.read_brs_live_published_provenance(
                    value.provider, value.request, value.plan, expected_pin=observed.pin,
                    expected_provenance_sha256=original_digest,
                )
                assert evidence.provenance_sha256 == original_digest
                value.success_file = _published_file_snapshot(path)
                pin = observed.pin
        except BaseException as exc:
            value.reader_error = exc
            raise
        value.observations.append((evidence, pin))
        if outcome == "published":
            return NativeRSISolverGateway._map_bundle(value.request, value.plan, evidence)
        return f.SolverResult(
            episode_id=value.request.episode_id, request_sha256=value.request.digest(),
            status="failed", terminal_reason="inert-native-all-rejected",
            candidate_receipt_sha256=None, execution_receipt_sha256=None,
            official_evaluation_receipt_sha256=None, trace_digest=delivery.payload_sha256,
        )

    def operation(request):
        native_plan = f.owner_fixture._plan(value.binding, request, value.controller.snapshot)
        native_plan = replace(native_plan, bootstrap_descriptor_sha256=value.native.artifact.descriptor.digest(),
                              bootstrap_artifact_sha256=value.native.artifact.artifact_sha256, plan_sha256=None)
        claim = value.ledger.claim_native_episode(request, plan_sha256=native_plan.plan_sha256)
        messages.put((request, native_plan, threading.get_ident()))
        assert release.wait(timeout=30), "original reader owner never released worker"
        if abort.is_set():
            raise f.owner_fixture._StopWorker()
        result = value.session.worker_endpoint.receive_and_settle(value.request_message, callback=callback,
                                                                  check=lambda: None)
        try:
            if outcome == "all_rejected":
                evidence, pin = completion.read_brs_live_rejection_completion(
                    value.provider, request, native_plan, expected_pin=value.observations[0][1],
                )
            else:
                pin = value.observations[0][1]
                if rewrite_success_p:
                    path = value.provider.provenance_batch / "native-rsi.provenance.json"
                    wire = json.loads(path.read_bytes())
                    path.rename(path.with_suffix(".original-stage2"))
                    path.write_bytes(b"")
                    info = path.stat()
                    wire["file_identity"] = {"device": info.st_dev, "inode": info.st_ino}
                    wire.pop("provenance_sha256")
                    wire["provenance_sha256"] = hashlib.sha256(canonical_json(wire)).hexdigest()
                    path.write_bytes(canonical_json(wire))
                    path.chmod(0o400)
                    assert completion.read_native_rsi_provenance(value.provider.provenance_batch) == wire
                    assert wire["provenance_sha256"] != value.observations[0][0].provenance_sha256
                evidence = completion.read_brs_live_published_provenance(
                    value.provider, request, native_plan, expected_pin=pin,
                    expected_provenance_sha256=value.observations[0][0].provenance_sha256,
                )
                assert evidence == value.observations[0][0]
                path = value.provider.provenance_batch / "native-rsi.provenance.json"
                assert _published_file_snapshot(path) == value.success_file
        except BaseException as exc:
            value.reader_error = exc
            raise
        value.observations.append((evidence, pin))
        value.ledger.publish_native_episode_result(request, plan_sha256=native_plan.plan_sha256,
                                                   result=result, expected_claim=claim)
        return result

    value.operation = operation
    with f.selected_fixture._wave(value) as wave:
        handoff = value.controller._python_admission_bind_selected_brs_handoff(wave)
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(value.controller._execute_brs_intent, wave, wave.state, handoff.episode_id, handoff)
        try:
            request, native_plan, worker_thread = messages.get(timeout=20)
            value.request, value.plan, value.worker_thread = request, native_plan, worker_thread
            value.ready, value.future, value.pool, value.wave = release, future, pool, wave
            value.owner = f._BRSLineageCheckpointOwner(value.controller, wave, request=request,
                memory=value.controller.snapshot, native_plan=native_plan)
            value.request_message = f._request_from_native_preparation(value.preparation, handoff,
                native_plan=native_plan, expected_head_sha256=handoff.head_sha256,
                expected_state_sha256=handoff.state_sha256)
            value.mailbox = BRSOwnerPublicationMailbox(handoff, worker_thread=worker_thread)
            value.session = open_brs_terminal_lifecycle(value.owner, value.mailbox, future=future, executor=pool)
            yield value
        finally:
            abort.set()
            release.set()
            if hasattr(value, "session"):
                value.session._exchange.fail()
            if hasattr(value, "mailbox"):
                value.mailbox.close()
            wave.channel.close()
            pool.shutdown(wait=True)


def test_genuine_c1_p_c2_reader_reobserves_stage_two_and_three_without_owner_transfer(tmp_path, monkeypatch):
    with _genuine_reader(tmp_path, monkeypatch) as value:
        value.ready.set()
        try:
            transaction = value.session.serve(value.preparation, check=lambda: None, timeout=30)
        except BaseException:
            if hasattr(value, "reader_error"):
                raise value.reader_error
            raise
        execution = value.future.result(timeout=20)
        assert transaction.transaction.publication_status == "all_rejected"
        assert execution.result.status == "failed"
        assert len(value.observations) == 2
        assert value.observations[0] == value.observations[1]
        assert value.observations[0][0].plan == value.plan
        assert value.provider._live_rejection is None


def test_genuine_published_reader_retains_original_p_and_bundle_across_stage_two_and_three(tmp_path, monkeypatch):
    from lunar_evolution.rsi_brs_reserved_owner import read_reserved_published_materials

    with _genuine_reader(tmp_path, monkeypatch, outcome="published") as value:
        value.ready.set()
        try:
            transaction = value.session.serve(value.preparation, check=lambda: None, timeout=30)
        except BaseException:
            if hasattr(value, "reader_error"):
                raise value.reader_error
            raise
        execution = value.future.result(timeout=20)
        assert transaction.transaction.publication_status == "published"
        assert execution.result.status == "completed"
        assert len(value.observations) == 2
        assert value.observations[0] == value.observations[1]
        bundle = value.observations[0][0]
        assert dict(execution.result.solver_provenance)["native_provenance_sha256"] == bundle.provenance_sha256
        path = value.provider.provenance_batch / "native-rsi.provenance.json"
        assert _published_file_snapshot(path) == value.success_file
        assert value.provider._live_rejection is None
        assert value.ledger.get_episode(value.sibling_id) is None
        published = value.owner._state["producer_publication_lineage"]["batches"][0]
        assert read_reserved_published_materials(value.native.workspace, published)


def test_genuine_stage_three_refuses_rehashed_replacement_p_without_result_or_retry(tmp_path, monkeypatch):
    with _genuine_reader(tmp_path, monkeypatch, outcome="published", rewrite_success_p=True) as value:
        value.ready.set()
        with pytest.raises(RSILearningError, match="callback_unknown"):
            value.session.serve(value.preparation, check=lambda: None, timeout=30)
        assert str(value.reader_error) == "rsi_brs_native_completion_published_provenance_drift"
        assert len(value.observations) == 1
        assert value.ledger.episode_result(value.request.episode_id) is None
        assert value.ledger.get_episode(value.request.episode_id).state == "running"
        assert value.ledger.inspect_native_episode_claim(value.request, plan_sha256=value.plan.plan_sha256).status == "started"
        before = value.ledger.controller_checkpoint_history(value.plan.run_id)
        with pytest.raises(RSILearningError):
            value.session.serve(value.preparation, check=lambda: None, timeout=30)
        assert value.ledger.controller_checkpoint_history(value.plan.run_id) == before
