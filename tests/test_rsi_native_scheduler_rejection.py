"""Inert scheduler rejection boundaries, with real DTOs, SQLite claims and P files.

Native recovery and already verified candidate observations are explicit unit
seams. These cases never certify native execution or owner/CAS integration.
"""

from __future__ import annotations

import itertools
import json
import os
import socket
import subprocess
from dataclasses import replace
from threading import RLock, local
from types import MappingProxyType, SimpleNamespace

import pytest
from test_rsi_native_rejection import digest, rejection_evidence

import lunar_evolution.rsi_native_scheduler as scheduler
from lunar_evolution.candidate_bundle import CandidateSourceBundle, CandidateSourceFile
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.evolution import CandidateDraft
from lunar_evolution.native_trusted_attempt import NativeTrustedAttemptObservation
from lunar_evolution.native_trusted_output import NativeTrustedOutputPreparation
from lunar_evolution.native_trusted_scheduler import (
    NativeTrustedProducerRecovery,
    NativeTrustedProducerRun,
)
from lunar_evolution.producer_bundle_admission import (
    ProducerBundleAdmissionItem,
    ProducerBundleAdmissionPlan,
)
from lunar_evolution.producer_bundle_handoff import VerifiedProducerBundle
from lunar_evolution.producer_bundle_lineage_v2 import ProducerLineageRejectedTerminalV2
from lunar_evolution.producer_bundle_population import ProducerBundleDraft
from lunar_evolution.producer_bundle_rejection import VerifiedProducerBundleRejection, _prepared
from lunar_evolution.producer_bundle_transaction import NativeProducerBundleTransactionResult
from lunar_evolution.producer_handoff import ProducerResultEnvelope
from lunar_evolution.producer_process import ProducerExecutionReceipt, ProducerStreamEvidence
from lunar_evolution.rsi_controller import RSILearningController
from lunar_evolution.rsi_learning import EMPTY_MEMORY_SNAPSHOT
from lunar_evolution.rsi_native_inputs import NativeRSIInputDescriptor
from lunar_evolution.rsi_native_provenance_names import NATIVE_RSI_PROVENANCE_NAMES
from lunar_evolution.rsi_native_rejection import (
    NATIVE_RSI_REJECTION_PROVENANCE_NAME,
    map_native_rejection_to_solver_result,
    persist_native_rsi_rejection_provenance,
    read_native_rsi_rejection_provenance,
)
from lunar_evolution.rsi_native_scheduler import (
    NativeRSISchedulerProvider,
    NativeRSISchedulerProviderError,
)
from lunar_evolution.rsi_store import RSILedger


@pytest.fixture(autouse=True)
def forbid_processes_and_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("scheduler unit rejection tests must not launch or connect")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def provider_fixture(tmp_path, monkeypatch):
    seed = rejection_evidence()
    plan, request = seed.plan, seed.plan.request
    ledger = RSILedger(tmp_path / "ledger.sqlite3")
    claim = ledger.claim_native_episode(request, plan_sha256=plan.plan_sha256)
    identity = scheduler._read_ledger_identity(ledger)
    evidence = replace(seed, ledger_identity=identity, claim=claim)
    batch = tmp_path / "evolution/producer-batches" / plan.journal_id
    batch.mkdir(parents=True)
    inputs = NativeRSIInputDescriptor(
        workspace=tmp_path, journal_id=plan.journal_id, inputs_path=batch / ".rsi-input",
        request_sha256=request.digest(), memory_snapshot_sha256=EMPTY_MEMORY_SNAPSHOT.digest(),
        manifest_sha256=plan.manifest_sha256, request_json=canonical_json(request.to_dict()),
        memory_json=canonical_json(EMPTY_MEMORY_SNAPSHOT.to_dict()), manifest_json=b"{}",
        deadline_unix=None, launch_binding_sha256=evidence.input_binding_sha256,
    )
    controller = RSILearningController.__new__(RSILearningController)
    # Match the constructor's inactive admission scopes at the publication guard.
    controller._python_admission_flow_local = local()
    controller._python_admission_brs_local = local()
    controller._python_admission_brs_wave = None
    controller._python_admission_brs_observation_lock = RLock()
    controller.producer_known_rejection = True
    controller.producer_multi_episode_publication = True
    controller.producer_child_execution = True
    controller.ledger = ledger
    controller.producer_workspace = tmp_path
    context = SimpleNamespace(
        workspace=tmp_path, intent=SimpleNamespace(journal_id=plan.journal_id),
        failure_ledger=ledger, evaluator_kind=plan.evaluator_kind,
        evaluator_fingerprint=plan.evaluator_fingerprint, runner_fingerprint=evidence.terminal.runner_fingerprint,
        dependency_sha256=evidence.terminal.dependency_sha256, environment_sha256=request.environment_sha256,
        attestation=object(), artifact=object(), contract=object(), groups=(),
        producer_root=tmp_path, broker_config=object(), strategy=object(), execution_control=None,
        cancelled=None, python_handoff_after_execution=lambda *_args: None,
    )
    provider = NativeRSISchedulerProvider.__new__(NativeRSISchedulerProvider)
    provider.context = context
    provider._failure_ledger_identity = MappingProxyType(identity)
    provider._python_admission_controller = controller
    provider._python_admission_replay_controller = None
    provider._live_rejection = None
    config = {"inert_original_context": "fixed"}
    provider.rsi_fingerprint_config = lambda: dict(config)
    provider._inputs = lambda *, require_unexpired: inputs
    monkeypatch.setattr(scheduler, "_assert_plan_binding", lambda *_args: None)
    return SimpleNamespace(
        provider=provider, evidence=evidence, request=request, plan=plan, ledger=ledger,
        batch=batch, inputs=inputs, config=config, controller=controller,
    )


def native_fixture(fixture):
    """Strict detached snapshots; original native recovery is mocked separately."""
    seed, plan = fixture.evidence, fixture.plan
    stream = ProducerStreamEvidence("stdout", 0, digest("empty-stdout"), False, "complete")
    receipt = ProducerExecutionReceipt(
        **{name: getattr(plan, name) for name in (
            "launch_id", "journal_id", "run_id", "parent_task_id", "task_id",
            "intent_sha256", "attestation_sha256",
        )},
        consumption_sha256=digest("consumption"), registration_sha256=digest("registration"),
        executable_identity=digest("executable"), pid=1234, pgid=1234, owner_identity={"pid": 1234},
        gate_released=True, request_timeout_seconds=1, max_requests=1, output_max_bytes=4096,
        wall_timeout_seconds=1, request_count=0, exit_code=0, stdout_evidence=stream,
        stderr_evidence=replace(stream, stream="stderr"), envelope_evidence=None,
        cleanup_status="already_exited", cleanup_sha256=digest("cleanup"), execution_binding="linux-sealed-memfd",
        execution_snapshot_relative_path=None, execution_snapshot_sha256=digest("snapshot"),
        execution_snapshot_size=1, status="completed",
    )
    bundles, drafts, items = [], [], []
    for slot in seed.terminal.candidates:
        source = "def solve():\n    return 0\n"
        source_path = slot.bundle_id + "/main.py"
        bundle = CandidateSourceBundle(plan.request.contract_sha256, source_path, (
            CandidateSourceFile(source_path, len(source.encode()), digest(source)),
        ))
        bundles.append(VerifiedProducerBundle(slot.bundle_id, bundle, bundle.digest(), 1, len(source.encode()), digest("producer")))
        drafts.append(ProducerBundleDraft(
            slot.bundle_id, CandidateDraft.from_files({source_path: source}, source_path),
            bundle.digest(), digest("producer"),
        ))
        items.append(ProducerBundleAdmissionItem(
            slot.bundle_id, bundle.digest(), bundle.digest(), source_path, (source_path,), digest("producer"),
        ))
    admission = ProducerBundleAdmissionPlan(
        plan.request.contract_sha256, plan.evaluator_kind, plan.evaluator_fingerprint,
        seed.terminal.runner_fingerprint, seed.terminal.dependency_sha256,
        plan.request.environment_sha256, tuple(items),
    )
    terminal = replace(
        seed.terminal, admission_sha256=admission.digest(), native_execution_receipt_sha256=receipt.receipt_sha256,
        candidates=tuple(replace(slot, bundle_sha256=bundle.bundle_sha256)
                         for slot, bundle in zip(seed.terminal.candidates, bundles, strict=True)), journal_sha256=None,
    )
    prepared = _prepared(terminal)
    rejected = replace(seed.rejected, terminal_journal_sha256=terminal.digest(),
                       prepared_journal_sha256=prepared.digest(), descriptor_sha256=None)
    binding = replace(seed.lineage, rejected_sha256=rejected.digest(), terminal_journal_sha256=terminal.digest(),
                      prepared_journal_sha256=prepared.digest())
    evidence = replace(seed, terminal=terminal, rejected=rejected, lineage=binding,
                       producer_execution_receipt_sha256=receipt.receipt_sha256)
    fixture.evidence = evidence
    output = NativeTrustedOutputPreparation(
        digest("process-terminal"), seed.producer_output_sha256, digest("envelope-bytes"),
        ProducerResultEnvelope("1", "producer", digest("producer"), "completed", plan.request.contract_sha256,
                               {"max_requests": 1}, ()),
        tuple(bundles), tuple(drafts), admission, receipt.receipt_sha256, "brokered_requests_only",
    )
    recovery = NativeTrustedProducerRecovery(receipt, output)
    observation = VerifiedProducerBundleRejection(
        terminal, binding.rejection_manifest_sha256, binding.candidate_ids,
        evidence.execution_receipt_sha256s, evidence.evaluation_receipt_sha256s, evidence.retained_evidence_sha256s,
    )
    publication = NativeProducerBundleTransactionResult(
        prepared, None, (), (), binding.candidate_ids, (), None, None, "all_rejected", terminal,
    )
    run = NativeTrustedProducerRun(
        NativeTrustedAttemptObservation(plan.launch_id, plan.journal_id, "recovery_required", "fixture", None,
                                        True, True, 0, "already_exited"),
        receipt, output, publication, "all_rejected",
    )
    for name, journal in (("journal.prepared.json", prepared), ("journal.json", terminal)):
        (fixture.batch / name).write_text(json.dumps(journal.to_dict()))
    return recovery, observation, run


def native_seams(fixture, monkeypatch):
    recovery, observation, run = native_fixture(fixture)
    calls = []
    monkeypatch.setattr(scheduler, "recover_native_trusted_producer", lambda *_args, **kwargs: (
        calls.append(("native", kwargs["require_broker"])) or recovery
    ))
    monkeypatch.setattr(scheduler, "_verify_terminal_batch_rejection_evidence", lambda *_args, **kwargs: (
        calls.append(("candidates", kwargs["terminal"].digest())) or observation
    ))
    return recovery, observation, run, calls


def authority_seam(fixture, monkeypatch, authority_type, *, pin=None, acknowledge=None):
    authority = authority_type.__new__(authority_type)
    calls = []
    monkeypatch.setattr(authority_type, "rejection_provenance_binding", lambda self: (
        calls.append(("C1", self is authority)) or fixture.evidence.lineage
    ))
    monkeypatch.setattr(authority_type, "rejection_provenance_file_pin", lambda self: (
        calls.append(("C2", self is authority)) or pin[0]
    ))
    if acknowledge is not None:
        monkeypatch.setattr(authority_type, "acknowledge_rejection_provenance", acknowledge)
    return authority, calls


@pytest.mark.parametrize("names", [()] + [(name,) for name in NATIVE_RSI_PROVENANCE_NAMES])
def test_three_kind_inventory_preserves_default_and_exact_names(tmp_path, names):
    batch = tmp_path / "evolution/producer-batches/journal"
    batch.mkdir(parents=True)
    provider = NativeRSISchedulerProvider.__new__(NativeRSISchedulerProvider)
    provider.context = SimpleNamespace(workspace=tmp_path, intent=SimpleNamespace(journal_id="journal"))
    for name in names:
        (batch / name).write_bytes(b'{"partial":')
    expected = "rejection" if NATIVE_RSI_REJECTION_PROVENANCE_NAME in names else (
        "failure" if scheduler.NATIVE_RSI_FAILURE_PROVENANCE_NAME in names else "success"
    )
    assert provider._provenance_kind() == expected


@pytest.mark.parametrize("pair", list(itertools.combinations(NATIVE_RSI_PROVENANCE_NAMES, 2)))
@pytest.mark.parametrize("kind", ["partial", "symlink"])
def test_three_kind_inventory_refuses_every_pair_without_adopting(tmp_path, pair, kind):
    batch = tmp_path / "evolution/producer-batches/journal"
    batch.mkdir(parents=True)
    provider = NativeRSISchedulerProvider.__new__(NativeRSISchedulerProvider)
    provider.context = SimpleNamespace(workspace=tmp_path, intent=SimpleNamespace(journal_id="journal"))
    for name in pair:
        if kind == "partial":
            (batch / name).write_bytes(b"partial")
        else:
            (batch / name).symlink_to("missing-target")
    before = {p.name: p.lstat() for p in batch.iterdir()}
    with pytest.raises(NativeRSISchedulerProviderError, match="conflicting_provenance"):
        provider._provenance_kind()
    assert {p.name: p.lstat() for p in batch.iterdir()} == before


def test_explicit_original_rejection_ledger_pin_is_required(tmp_path, monkeypatch):
    fixture = provider_fixture(tmp_path, monkeypatch)
    fixture.provider.assert_rejection_ledger(fixture.ledger)
    other = RSILedger(tmp_path / "other.sqlite3")
    with pytest.raises(NativeRSISchedulerProviderError, match="rejection_ledger_missing"):
        fixture.provider.assert_rejection_ledger(other)
    original = fixture.ledger.database
    original.rename(tmp_path / "retained-original.sqlite3")
    replacement = RSILedger(original)
    with pytest.raises(NativeRSISchedulerProviderError, match="failure_ledger_changed"):
        fixture.provider.assert_rejection_ledger(fixture.ledger)
    assert replacement.database.exists()


def test_started_rejection_ordinary_recovery_refuses_without_readback(tmp_path, monkeypatch):
    fixture = provider_fixture(tmp_path, monkeypatch)
    (fixture.batch / NATIVE_RSI_REJECTION_PROVENANCE_NAME).write_bytes(b"partial")
    touched = []
    monkeypatch.setattr(scheduler, "read_native_rsi_rejection_provenance", lambda *_args, **_kwargs: touched.append("P"))
    with pytest.raises(NativeRSISchedulerProviderError, match="rejection_claim_missing"):
        fixture.provider.recover(fixture.request, fixture.plan)
    assert touched == []


def test_snapshot_reconstructs_original_receipt_output_and_ordered_all_candidates(tmp_path, monkeypatch):
    fixture = provider_fixture(tmp_path, monkeypatch)
    recovery, observation, run, calls = native_seams(fixture, monkeypatch)
    actual = fixture.provider._native_rejection_snapshot(fixture.plan, fixture.evidence.lineage, live_run=run)
    assert actual == (recovery, observation)
    assert [call[0] for call in calls] == ["native", "candidates", "native", "candidates"]
    assert all(call[1] is True for call in calls if call[0] == "native")
    assert len(actual[1].candidate_ids) == 2


@pytest.mark.parametrize("field", ["receipt", "output", "terminal", "rejected_ids", "admitted_ids", "manifest", "status"])
def test_snapshot_refuses_live_native_projection_drift(tmp_path, monkeypatch, field):
    fixture = provider_fixture(tmp_path, monkeypatch)
    _recovery, _observation, run, _calls = native_seams(fixture, monkeypatch)
    if field == "receipt":
        run = replace(run, receipt=replace(run.receipt, request_count=1, receipt_sha256=None))
    elif field == "output":
        run = replace(run, output=replace(run.output, output_capture_sha256=digest("different-output")))
    else:
        publication = run.publication
        if field == "terminal":
            publication = replace(publication, terminal_journal=replace(
                publication.terminal_journal, terminal_marker_sha256=digest("different-marker"), journal_sha256=None,
            ))
        elif field == "rejected_ids":
            publication = replace(publication, rejected_candidate_ids=tuple(reversed(publication.rejected_candidate_ids)))
        elif field == "admitted_ids":
            publication = replace(publication, admitted_candidate_ids=("candidate-0",))
        elif field == "manifest":
            publication = replace(publication, manifest=object())
        elif field == "status":
            run = replace(run, status="published")
        run = replace(run, publication=publication)
    with pytest.raises(NativeRSISchedulerProviderError, match="rejection_run_changed"):
        fixture.provider._native_rejection_snapshot(fixture.plan, fixture.evidence.lineage, live_run=run)


def test_live_same_owner_c1_p_c2_and_repeat_are_readonly_after_ack(tmp_path, monkeypatch):
    from lunar_evolution.rsi_publication_lineage import RSIPublicationLineage

    fixture = provider_fixture(tmp_path, monkeypatch)
    _recovery, _observation, run, calls = native_seams(fixture, monkeypatch)
    pins, acks = [], []

    def acknowledge(self, evidence, pin):
        acks.append((self is owner, evidence.provenance_file_pin == pin))
        pins.append(pin)

    owner, owner_calls = authority_seam(fixture, monkeypatch, RSIPublicationLineage, pin=pins, acknowledge=acknowledge)
    result = fixture.provider._persist_live_rejection(
        fixture.request, fixture.plan, fixture.inputs, run=run, owner=owner,
        claim=fixture.evidence.claim, config=fixture.config,
    )
    assert acks == [(True, True)]
    assert owner_calls and all(call[1] for call in owner_calls)
    assert result.to_dict() == fixture.evidence.to_dict()
    assert len(calls) == 8
    assert fixture.ledger.inspect_native_episode_claim(fixture.request, plan_sha256=fixture.plan.plan_sha256).status == "started"
    before = (fixture.batch / NATIVE_RSI_REJECTION_PROVENANCE_NAME).stat()
    assert fixture.provider.recover_live_rejection(fixture.request, fixture.plan) == result
    assert (fixture.batch / NATIVE_RSI_REJECTION_PROVENANCE_NAME).stat() == before
    fixture.provider._live_rejection = None
    with pytest.raises(NativeRSISchedulerProviderError, match="rejection_live_owner_missing"):
        fixture.provider.recover_live_rejection(fixture.request, fixture.plan)


def test_orphan_p_is_retained_and_never_acknowledged(tmp_path, monkeypatch):
    from lunar_evolution.rsi_publication_lineage import RSIPublicationLineage

    fixture = provider_fixture(tmp_path, monkeypatch)
    _recovery, _observation, run, _calls = native_seams(fixture, monkeypatch)
    path = fixture.batch / NATIVE_RSI_REJECTION_PROVENANCE_NAME
    path.write_bytes(b"orphan")
    acks = []
    owner, _ = authority_seam(fixture, monkeypatch, RSIPublicationLineage, pin=[],
                              acknowledge=lambda *_args: acks.append("ack"))
    with pytest.raises(NativeRSISchedulerProviderError, match="rejection_provenance_invalid"):
        fixture.provider._persist_live_rejection(
            fixture.request, fixture.plan, fixture.inputs, run=run, owner=owner,
            claim=fixture.evidence.claim, config=fixture.config,
        )
    assert acks == [] and path.read_bytes() == b"orphan"
    assert fixture.provider._live_rejection is None


def test_failed_owner_ack_keeps_original_p_and_started_claim(tmp_path, monkeypatch):
    from lunar_evolution.rsi_publication_lineage import RSIPublicationLineage

    fixture = provider_fixture(tmp_path, monkeypatch)
    _recovery, _observation, run, _calls = native_seams(fixture, monkeypatch)
    pins = []

    def refusal(_owner, _evidence, pin):
        pins.append(pin)
        raise ValueError("inert CAS refusal")

    owner, _ = authority_seam(fixture, monkeypatch, RSIPublicationLineage, pin=pins, acknowledge=refusal)
    with pytest.raises(NativeRSISchedulerProviderError, match="rejection_provenance_invalid"):
        fixture.provider._persist_live_rejection(
            fixture.request, fixture.plan, fixture.inputs, run=run, owner=owner,
            claim=fixture.evidence.claim, config=fixture.config,
        )
    assert read_native_rsi_rejection_provenance(fixture.batch, expected_file_pin=pins[0]).plan == fixture.plan
    assert fixture.provider._live_rejection is None
    assert fixture.ledger.inspect_native_episode_claim(fixture.request, plan_sha256=fixture.plan.plan_sha256).status == "started"


@pytest.mark.parametrize("kind", ["callback", "terminal", "subclass"])
def test_explicit_started_route_refuses_other_inspectors_before_io(tmp_path, monkeypatch, kind):
    from lunar_evolution.rsi_publication_lineage import (
        RSIPublicationLineageV2Inspection,
        StartedRSIRejectionInspection,
    )

    fixture = provider_fixture(tmp_path, monkeypatch)
    touched = []
    fixture.provider._inputs = lambda **_kwargs: touched.append("inputs")
    if kind == "callback":
        inspection = SimpleNamespace(inspect_rejection=lambda *_args: touched.append("callback"))
    elif kind == "terminal":
        inspection = RSIPublicationLineageV2Inspection.__new__(RSIPublicationLineageV2Inspection)
    else:
        class Subclass(StartedRSIRejectionInspection):
            pass

        inspection = Subclass.__new__(Subclass)
    with pytest.raises(NativeRSISchedulerProviderError, match="rejection_inspection_invalid"):
        fixture.provider.recover_rejection(fixture.request, fixture.plan, inspection=inspection)
    assert touched == []


@pytest.mark.parametrize("terminal", [False, True])
def test_sealed_started_and_terminal_routes_revalidate_original_c2_pin(tmp_path, monkeypatch, terminal):
    from lunar_evolution.rsi_publication_lineage import (
        RSIPublicationLineageV2Inspection,
        StartedRSIRejectionInspection,
    )

    fixture = provider_fixture(tmp_path, monkeypatch)
    recovery, observation, _run, _calls = native_seams(fixture, monkeypatch)
    _digest, pin = persist_native_rsi_rejection_provenance(fixture.batch, fixture.evidence, retained_bytes=0)
    inspection_type = RSIPublicationLineageV2Inspection if terminal else StartedRSIRejectionInspection
    inspection, held_calls = authority_seam(fixture, monkeypatch, inspection_type, pin=[pin])
    monkeypatch.setattr(inspection_type, "inspect_rejection", lambda *_args: observation)
    if terminal:
        saved = read_native_rsi_rejection_provenance(fixture.batch, expected_file_pin=pin)
        mapped = map_native_rejection_to_solver_result(fixture.request, fixture.plan, saved)
        fixture.ledger.publish_native_episode_result(
            fixture.request, plan_sha256=fixture.plan.plan_sha256, result=mapped, expected_claim=fixture.evidence.claim,
        )
        fixture.provider._retained_lineage_options = lambda *_args: {"lineage_inspection": inspection}
        result = fixture.provider.recover(fixture.request, fixture.plan)
    else:
        result = fixture.provider.recover_rejection(fixture.request, fixture.plan, inspection=inspection)
    assert result.provenance_file_pin == pin and result.producer_execution_receipt_sha256 == recovery.receipt.receipt_sha256
    assert len(held_calls) >= 6
    assert fixture.provider._live_rejection is None
    retained = fixture.batch / "original-P"
    os.rename(fixture.batch / NATIVE_RSI_REJECTION_PROVENANCE_NAME, retained)
    (fixture.batch / NATIVE_RSI_REJECTION_PROVENANCE_NAME).write_bytes(retained.read_bytes())
    (fixture.batch / NATIVE_RSI_REJECTION_PROVENANCE_NAME).chmod(0o400)
    with pytest.raises(NativeRSISchedulerProviderError, match="rejection_provenance_invalid"):
        fixture.provider._read_rejection(fixture.request, fixture.plan, fixture.inputs, authority=inspection, live=not terminal)
    assert retained.exists()


def test_rejected_descriptor_uses_complete_original_binding():
    evidence = rejection_evidence()
    assert scheduler._rejected_descriptor(evidence.lineage) == evidence.rejected
    assert type(scheduler._rejected_descriptor(evidence.lineage)) is ProducerLineageRejectedTerminalV2
    with pytest.raises(NativeRSISchedulerProviderError, match="rejection_lineage_changed"):
        scheduler._rejected_descriptor(replace(evidence.lineage, rejected_sha256=digest("wrong")))


def test_callback_polluted_live_native_output_is_refused_without_invocation(tmp_path, monkeypatch):
    fixture = provider_fixture(tmp_path, monkeypatch)
    _recovery, _observation, run, _calls = native_seams(fixture, monkeypatch)
    touched = []

    class Callback:
        def __eq__(self, _other):
            touched.append("equality")
            raise AssertionError("callback equality")

    output = replace(run.output, bundles=(Callback(),))
    with pytest.raises(ValueError, match="shape_invalid"):
        fixture.provider._native_rejection_snapshot(fixture.plan, fixture.evidence.lineage, live_run=replace(run, output=output))
    assert touched == []


@pytest.mark.parametrize("enabled", [False, True])
def test_dispatch_routes_opted_in_all_rejected_before_success_receipts(tmp_path, monkeypatch, enabled):
    from lunar_evolution.rsi_publication_lineage import RSIPublicationLineage

    fixture = provider_fixture(tmp_path, monkeypatch)
    _recovery, _observation, run, _calls = native_seams(fixture, monkeypatch)
    fixture.controller.producer_known_rejection = enabled
    pins = []
    owner, _ = authority_seam(
        fixture, monkeypatch, RSIPublicationLineage, pin=pins,
        acknowledge=lambda _owner, _evidence, pin: pins.append(pin),
    )
    seen = []
    fixture.provider._python_publication_join = lambda *_args: {
        "lineage_owner": owner, "evidence_revalidator": lambda stage: seen.append(stage),
    }
    monkeypatch.setattr(scheduler, "run_native_trusted_producer_outcome", lambda *_args, **_kwargs: run)
    if enabled:
        def forbidden(*_args):
            pytest.fail("rejection may not enter successful receipt construction")

        monkeypatch.setattr(scheduler, "_build_receipts", forbidden)
        result = fixture.provider(fixture.request, fixture.plan)
        assert result.terminal.state == "all_rejected" and result.provenance_file_pin == pins[0]
    else:
        with pytest.raises(NativeRSISchedulerProviderError, match="publication_incomplete"):
            fixture.provider(fixture.request, fixture.plan)
        assert not pins and not (fixture.batch / NATIVE_RSI_REJECTION_PROVENANCE_NAME).exists()
    assert seen == ["rsi_native_python_scheduler_return"]


@pytest.mark.parametrize("drift", ["native_output", "candidate_evidence"])
def test_reconstruction_detects_repeated_native_evidence_drift(tmp_path, monkeypatch, drift):
    fixture = provider_fixture(tmp_path, monkeypatch)
    recovery, observation, _run, _calls = native_seams(fixture, monkeypatch)
    if drift == "native_output":
        readings = iter((recovery, replace(recovery, output=replace(
            recovery.output, output_capture_sha256=digest("replaced-capture"),
        ))))
        monkeypatch.setattr(scheduler, "recover_native_trusted_producer", lambda *_args, **_kwargs: next(readings))
    else:
        readings = iter((observation, replace(observation, retained_evidence_sha256s=(digest("changed"), digest("other")))))
        monkeypatch.setattr(scheduler, "_verify_terminal_batch_rejection_evidence", lambda *_args, **_kwargs: next(readings))
    with pytest.raises(NativeRSISchedulerProviderError, match="rejection_native_changed"):
        fixture.provider._native_rejection_snapshot(fixture.plan, fixture.evidence.lineage)


@pytest.mark.parametrize("drift", ["context", "inputs", "controller"])
def test_live_pre_p_drift_retains_started_claim_and_creates_no_p(tmp_path, monkeypatch, drift):
    from lunar_evolution.rsi_publication_lineage import RSIPublicationLineage

    fixture = provider_fixture(tmp_path, monkeypatch)
    _recovery, _observation, run, _calls = native_seams(fixture, monkeypatch)
    owner, _ = authority_seam(fixture, monkeypatch, RSIPublicationLineage, pin=[], acknowledge=lambda *_args: None)
    original = scheduler._verify_terminal_batch_rejection_evidence

    def change(*args, **kwargs):
        value = original(*args, **kwargs)
        if drift == "context":
            fixture.config["mutated"] = True
        elif drift == "inputs":
            fixture.provider._inputs = lambda **_kwargs: replace(fixture.inputs, launch_binding_sha256=digest("changed"))
        else:
            fixture.provider._python_admission_controller = object()
        return value

    monkeypatch.setattr(scheduler, "_verify_terminal_batch_rejection_evidence", change)
    original_config = dict(fixture.config)
    with pytest.raises(NativeRSISchedulerProviderError, match="rejection_input_changed"):
        fixture.provider._persist_live_rejection(
            fixture.request, fixture.plan, fixture.inputs, run=run, owner=owner,
            claim=fixture.evidence.claim, config=original_config,
        )
    assert not (fixture.batch / NATIVE_RSI_REJECTION_PROVENANCE_NAME).exists()
    assert fixture.provider._live_rejection is None
    assert fixture.ledger.inspect_native_episode_claim(fixture.request, plan_sha256=fixture.plan.plan_sha256).status == "started"


@pytest.mark.parametrize("kind", ["callback", "started", "subclass"])
def test_success_retained_reader_refuses_nonterminal_inspector_before_workspace_io(tmp_path, monkeypatch, kind):
    from test_rsi_python_scheduler_inputs import _setup

    import lunar_evolution.rsi_native_retained as retained
    from lunar_evolution.rsi_publication_lineage import (
        RSIPublicationLineageV2Inspection,
        StartedRSIRejectionInspection,
    )

    value = _setup(tmp_path / "inert")
    if kind == "callback":
        inspection = SimpleNamespace(inspect=lambda *_args: pytest.fail("callback inspector"))
    elif kind == "started":
        inspection = StartedRSIRejectionInspection.__new__(StartedRSIRejectionInspection)
    else:
        class Subclass(RSIPublicationLineageV2Inspection):
            pass

        inspection = Subclass.__new__(Subclass)
    touched = []
    monkeypatch.setattr(retained, "_workspace_identity", lambda *_args: touched.append("workspace"))
    native = value.native
    with pytest.raises(retained.NativeRetainedEvidenceError, match="lineage_inspection_invalid"):
        retained.read_native_retained_candidate(
            native.workspace, candidate_id="candidate", expected_journal_sha256=digest("journal"),
            expected_producer_execution_receipt_sha256=digest("receipt"), intent=native.intent,
            attestation=native.attestation, artifact=native.artifact, contract=native.contract,
            groups=native.groups, evaluator_kind=native.evaluator_kind,
            evaluator_fingerprint=native.evaluator_fingerprint, runner_fingerprint=native.runner_fingerprint,
            dependency_sha256=native.dependency_sha256, environment_sha256=native.environment_sha256,
            lineage_inspection=inspection,
        )
    assert touched == []
