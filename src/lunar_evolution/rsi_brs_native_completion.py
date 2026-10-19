"""Read genuine native completion during one original BRS worker callback.

Only original durable mailbox/terminal records select the publication. Neither a
delivered result nor a caller receipt is accepted as an outcome. These functions
never publish provenance, native results, checkpoints or recovery decisions.
"""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass, fields, replace

from .candidate_evaluation_spec import canonical_json
from .producer_bundle_publication import parse_producer_bundle_publication_journal
from .rsi_brs_reconcile import BRSReconcileObligation, _validate_brs_episode_history
from .rsi_brs_serial_driver import reserved_brs_staging_mode
from .rsi_brs_terminal_evidence import _publication, _reserved_publication
from .rsi_gateway import SolverRequest
from .rsi_learning import RSILearningError
from .rsi_native_gateway import NativeRSIReceiptBundle
from .rsi_native_plan import NativeRSIExecutionPlan
from .rsi_native_provenance import MAX_NATIVE_RSI_PROVENANCE_BYTES, read_native_rsi_provenance
from .rsi_native_rejection import (
    NativeRSIRejectionEvidence,
    NativeRSIRejectionFilePin,
    read_native_rsi_rejection_provenance,
)
from .rsi_native_scheduler import (
    NativeRSISchedulerContext,
    NativeRSISchedulerProvider,
    _assert_plan_binding,
    _memory_from_request_inputs,
    _preparation_receipt,
    _provenance_payload,
    _read_retained,
    _rejected_descriptor,
    _retained_bundle,
)
from .rsi_python_admission import validate_rsi_python_admission_shapes
from .rsi_python_brs_terminal_lifecycle import inspect_brs_worker_terminal_evidence
from .rsi_store import NativeEpisodeClaim, RSILedger

_MAX_BYTES = 8 * 1024 * 1024


def _fail(reason):
    raise RSILearningError("rsi_brs_native_completion_" + reason)


def _digest(value):
    return hashlib.sha256(canonical_json(value, maximum=_MAX_BYTES)).hexdigest()


@dataclass(frozen=True, slots=True)
class _BRSNativeCompletionPin:
    """Immutable comparison facts only; every reader independently reobserves."""

    comparison_bytes: bytes


@dataclass(frozen=True, slots=True)
class _BRSPublishedNativeCompletion:
    bundle: NativeRSIReceiptBundle
    provenance_bytes: bytes
    pin: _BRSNativeCompletionPin


def _observe(provider, request, plan, expected_pin=None):
    if (type(provider) is not NativeRSISchedulerProvider or type(request) is not SolverRequest
            or type(plan) is not NativeRSIExecutionPlan or type(plan.request) is not SolverRequest
            or expected_pin is not None and type(expected_pin) is not _BRSNativeCompletionPin):
        _fail("input_invalid")
    for value in (request, plan.request):
        attrs = object.__getattribute__(value, "__dict__")
        if type(attrs) is not dict or set(attrs) != {field.name for field in fields(SolverRequest)}:
            _fail("input_invalid")
    validate_rsi_python_admission_shapes((request, plan), dto_types=(SolverRequest, NativeRSIExecutionPlan))
    NativeRSIExecutionPlan.from_dict(NativeRSIExecutionPlan.to_dict(plan))
    context = provider.context
    if type(context) is not NativeRSISchedulerContext:
        _fail("input_invalid")
    ledger = context.failure_ledger
    NativeRSISchedulerProvider.assert_rejection_ledger(provider, ledger)
    inputs = NativeRSISchedulerProvider._inputs(provider, require_unexpired=False)
    _assert_plan_binding(request, _memory_from_request_inputs(inputs, request), plan, context, inputs)
    config = NativeRSISchedulerProvider.rsi_fingerprint_config(provider)
    with ledger.read_only_observations():
        snapshot = RSILedger.read_brs_terminal_evidence_snapshot(ledger, plan.run_id, request.episode_id)
        lifecycle = inspect_brs_worker_terminal_evidence(ledger, plan.run_id, request.episode_id)
    if lifecycle["snapshot_pins"] != snapshot["pins"]:
        _fail("snapshot_drift")
    records = lifecycle["records"]
    # The owner can durably observe transport before the worker acknowledges
    # receipt. Original delivery + callback_started prove the later receive;
    # the earlier transport flag alone is neither completion nor refusal.
    if (lifecycle["status"] != "partial" or lifecycle["worker_terminal"] is not False
            or len(snapshot["mailbox_history"]) != 4
            or len(records) not in {2, 3}
            or records[1]["stage"] != "callback_started"
            or (len(records) == 2 and lifecycle["callback_observation"] != "started")
            or (len(records) == 3 and (records[2]["stage"] != "callback_finished"
                                      or records[2]["facts"]["outcome"] != "returned"
                                      or lifecycle["callback_observation"] != "returned"))):
        _fail("callback_gate_required")
    binding = lifecycle["binding"]
    mailbox = binding["mailbox_binding"]
    if (binding["worker_thread_id"] != threading.get_ident()
            or binding["thread_id"] != f"thread-{id(threading.current_thread()):x}"):
        _fail("original_worker_required")
    claim = snapshot["native_claim"]
    episode = _validate_brs_episode_history(BRSReconcileObligation.from_dict(mailbox["obligation"]),
                                           snapshot["episode_history"])
    if (type(claim) is not NativeEpisodeClaim or claim.status != "started"
            or episode.state != "running"
            or snapshot["saved_result"] is not None
            or (claim.episode_id, claim.request_sha256, claim.plan_sha256, claim.claim_sha256) !=
                (request.episode_id, plan.request_sha256, plan.plan_sha256, mailbox["native_claim_sha256"])
            or (mailbox["run_id"], mailbox["episode_id"], mailbox["selected_request_sha256"],
                mailbox["native_plan_sha256"]) !=
                (plan.run_id, request.episode_id, request.digest(), plan.plan_sha256)):
        _fail("claim_binding_drift")
    publication = lifecycle["delivery"]["publication"]
    journal = parse_producer_bundle_publication_journal(publication["journal"])
    reader = (_reserved_publication if reserved_brs_staging_mode(snapshot["roots"][0][1])
              else _publication)
    publication_sha = reader(context.workspace, publication, mailbox, snapshot["roots"], ledger=ledger)
    if (publication_sha != journal.digest() or journal.journal_id != plan.journal_id
            or journal.run_id != plan.run_id or journal.task_id != plan.task_id
            or journal.parent_task_id != plan.parent_task_id):
        _fail("publication_binding_drift")
    NativeRSISchedulerProvider.assert_rejection_ledger(provider, ledger)
    pin = _BRSNativeCompletionPin(canonical_json({
        "root_checkpoint_sha256": snapshot["roots"][-1][0],
        "native_claim": NativeEpisodeClaim.to_dict(claim),
        "terminal_binding_sha256": binding["binding_sha256"],
        "mailbox_binding_sha256": mailbox["binding_sha256"],
        "obligation_sha256": mailbox["obligation_sha256"],
        "delivery_sha256": _digest(lifecycle["delivery"]),
        "publication_journal_sha256": publication_sha,
        "input_binding_sha256": inputs.launch_binding_sha256,
        "provider_configuration_sha256": _digest(config),
    }, maximum=128 * 1024))
    if expected_pin is not None and (type(expected_pin.comparison_bytes) is not bytes
                                    or pin.comparison_bytes != expected_pin.comparison_bytes):
        _fail("original_pin_drift")
    return inputs, config, snapshot, publication, journal, pin


def _unchanged(provider, request, plan, before):
    inputs, config, snapshot, _publication_wire, _journal, pin = before
    after = _observe(provider, request, plan, pin)
    if (after[0] != inputs or after[1] != config or after[2]["pins"] != snapshot["pins"]
            or after[2]["roots"] != snapshot["roots"]):
        _fail("observation_changed")


def read_brs_live_published_completion(provider, request, plan, *, expected_pin=None):
    """Reconstruct one native published bundle and an unpersisted provenance payload."""
    before = _observe(provider, request, plan, expected_pin)
    inputs, _config, _snapshot, _wire, journal, pin = before
    admitted = tuple(item for item in journal.candidates if item.status == "admitted")
    if journal.state != "published" or len(admitted) != 1:
        _fail("published_candidate_required")
    candidate = admitted[0]
    evidence = _read_retained(provider.context, candidate_id=candidate.candidate_id,
                              journal_sha256=journal.digest(),
                              producer_receipt_sha256=journal.native_execution_receipt_sha256)
    bundle = _retained_bundle(request, evidence, _preparation_receipt(provider.context, evidence))
    payload = canonical_json(_provenance_payload(plan, inputs, evidence, bundle),
                             maximum=MAX_NATIVE_RSI_PROVENANCE_BYTES)
    _unchanged(provider, request, plan, before)
    return _BRSPublishedNativeCompletion(bundle, payload, pin)


def read_brs_live_published_provenance(provider, request, plan, *, expected_pin, expected_provenance_sha256):
    """Read original success P under the fixed callback's retained publishing digest.

    P already embeds its publishing inode in its digest. Keep that original
    writer-returned digest across calls rather than adopting rehashed P bytes.
    """
    if (type(expected_provenance_sha256) is not str or len(expected_provenance_sha256) != 64
            or any(char not in "0123456789abcdef" for char in expected_provenance_sha256)):
        _fail("published_provenance_pin_invalid")
    observed = read_brs_live_published_completion(provider, request, plan, expected_pin=expected_pin)
    saved = read_native_rsi_provenance(provider.provenance_batch)
    if saved["provenance_sha256"] != expected_provenance_sha256:
        _fail("published_provenance_drift")
    payload = {key: value for key, value in saved.items() if key not in {"file_identity", "provenance_sha256"}}
    if canonical_json(payload, maximum=MAX_NATIVE_RSI_PROVENANCE_BYTES) != observed.provenance_bytes:
        _fail("published_provenance_drift")
    repeated = read_brs_live_published_completion(provider, request, plan, expected_pin=observed.pin)
    if (repeated.provenance_bytes != observed.provenance_bytes or repeated.bundle != observed.bundle
            or read_native_rsi_provenance(provider.provenance_batch) != saved):
        _fail("published_provenance_changed")
    return replace(observed.bundle, provenance_sha256=saved["provenance_sha256"])


def read_brs_live_rejection_completion(provider, request, plan, *, expected_pin=None):
    """Reobserve original C1/P/C2, native output and every rejected receipt separately."""
    before = _observe(provider, request, plan, expected_pin)
    inputs, _config, snapshot, publication, journal, pin = before
    if journal.state != "all_rejected":
        _fail("rejected_terminal_required")
    entries = [entry for entry in publication["lineage"]["batches"]
               if entry["episode_id"] == request.episode_id and entry["journal_id"] == plan.journal_id]
    if len(entries) != 1:
        _fail("rejected_entry_required")
    reference = entries[0]["rejection_provenance"]
    file_pin = NativeRSIRejectionFilePin.from_dict(reference["file_pin"])
    saved = read_native_rsi_rejection_provenance(provider.provenance_batch, expected_file_pin=file_pin)
    if (saved.plan != plan or saved.input_binding_sha256 != inputs.launch_binding_sha256
            or dict(saved.ledger_identity) != provider._failure_ledger_identity
            or saved.claim != snapshot["native_claim"] or saved.terminal != journal
            or saved.provenance_sha256 != reference["provenance_sha256"]):
        _fail("rejected_provenance_drift")
    recovery, observation = NativeRSISchedulerProvider._native_rejection_snapshot(provider, plan, saved.lineage)
    reconstructed = NativeRSIRejectionEvidence(
        plan=plan, input_binding_sha256=inputs.launch_binding_sha256,
        ledger_identity=provider._failure_ledger_identity, claim=saved.claim,
        lineage=saved.lineage, rejected=_rejected_descriptor(saved.lineage), terminal=observation.terminal,
        producer_execution_receipt_sha256=recovery.receipt.receipt_sha256,
        producer_output_sha256=recovery.output.output_capture_sha256,
        execution_receipt_sha256s=observation.execution_receipt_sha256s,
        evaluation_receipt_sha256s=observation.evaluation_receipt_sha256s,
        retained_evidence_sha256s=observation.retained_evidence_sha256s,
    )
    if (reconstructed.to_dict() != saved.to_dict()
            or read_native_rsi_rejection_provenance(provider.provenance_batch, expected_file_pin=file_pin) != saved):
        _fail("rejected_provenance_changed")
    _unchanged(provider, request, plan, before)
    return saved, pin
