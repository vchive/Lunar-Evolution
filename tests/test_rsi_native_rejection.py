"""Pure rejection wire associations; no producer, ledger or settlement is invoked."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import fields, replace
from types import MappingProxyType

import pytest

from lunar_evolution.producer_bundle_lineage_v2 import ProducerLineageRejectedTerminalV2
from lunar_evolution.producer_bundle_publication import (
    ProducerBundlePublicationCandidate,
    ProducerBundlePublicationJournal,
)
from lunar_evolution.rsi_gateway import SolverRequest
from lunar_evolution.rsi_learning import EMPTY_MEMORY_SNAPSHOT
from lunar_evolution.rsi_native_plan import NativeRSIExecutionPlan
from lunar_evolution.rsi_native_rejection import (
    NativeRSIRejectionError,
    NativeRSIRejectionEvidence,
    RejectionLineageC1Binding,
    map_native_rejection_to_solver_result,
)
from lunar_evolution.rsi_store import NativeEpisodeClaim, RSILedger


def digest(label):
    return hashlib.sha256(label.encode()).hexdigest()


def rejection_evidence(*, count=2, retained_bytes=0):
    request = SolverRequest.build(
        episode_id="episode", solver_id="native_population", contract_sha256=digest("contract"),
        evaluator_sha256=digest("evaluator"), environment_sha256=digest("environment"),
        memory_snapshot_sha256=EMPTY_MEMORY_SNAPSHOT.digest(),
    )
    plan = NativeRSIExecutionPlan.build(
        request=request, memory_snapshot=EMPTY_MEMORY_SNAPSHOT, journal_id="journal", launch_id="launch",
        run_id="run", parent_task_id="parent", task_id="episode", candidate_selector_id="selector",
        evaluator_kind="local", evaluator_fingerprint=request.evaluator_sha256,
        **{name: digest(name) for name in (
            "intent_sha256", "attestation_sha256", "bootstrap_descriptor_sha256",
            "bootstrap_artifact_sha256", "manifest_sha256", "candidate_selector_sha256",
        )},
    )
    candidates = tuple(ProducerBundlePublicationCandidate(
        candidate_id=f"candidate-{i}", bundle_id=f"bundle-{i}", bundle_sha256=digest(f"bundle-{i}"),
        parent_id=None, generation=0, iteration=0, island_id=0,
        preparation_receipt_sha256=digest(f"prepare-{i}"), execution_receipt_sha256=digest(f"execute-{i}"),
        evaluation_receipt_sha256=digest(f"evaluate-{i}"), publication_receipt_sha256=None, status="rejected",
    ) for i in range(count))
    terminal = ProducerBundlePublicationJournal(
        journal_id=plan.journal_id, run_id=plan.run_id, parent_task_id=plan.parent_task_id, task_id=plan.task_id,
        admission_sha256=digest("admission"), archive_prefix_sha256=digest("prefix"),
        base_archive_sha256=digest("archive"), base_state_sha256=digest("state"),
        contract_sha256=request.contract_sha256, evaluator_kind=plan.evaluator_kind,
        evaluator_fingerprint=plan.evaluator_fingerprint, runner_fingerprint=digest("runner"),
        dependency_sha256=digest("dependencies"), environment_sha256=request.environment_sha256,
        budget_sha256=digest("budget"), strategy="population", population_config_sha256=digest("config"),
        num_islands=1, candidates=candidates, state="all_rejected", publication_phase="committed",
        terminal_marker_sha256=digest("marker"), archive_after_sha256=digest("archive"),
        state_after_sha256=digest("state"), native_execution_receipt_sha256=digest("producer-execution"),
    )
    rejected = ProducerLineageRejectedTerminalV2(
        run_id=plan.run_id, journal_id=plan.journal_id, episode_id=request.episode_id, ordinal=0,
        before_sha256=digest("before"), prepared_journal_sha256=digest("prepared"),
        terminal_journal_sha256=terminal.digest(), rejection_manifest_sha256=digest("raw-manifest"),
        terminal_marker_sha256=terminal.terminal_marker_sha256,
        candidate_ids=tuple(c.candidate_id for c in candidates), archive_sha256=terminal.base_archive_sha256,
        state_sha256=terminal.base_state_sha256,
    )
    lineage = RejectionLineageC1Binding(
        run_id=plan.run_id, episode_id=request.episode_id, journal_id=plan.journal_id, ordinal=0,
        checkpoint_sha256=digest("checkpoint-c1"), rejected_sha256=rejected.digest(),
        retained_bytes=retained_bytes, **{name: getattr(rejected, name) for name in (
            "before_sha256", "prepared_journal_sha256", "terminal_journal_sha256", "rejection_manifest_sha256",
            "terminal_marker_sha256", "candidate_ids", "archive_sha256", "state_sha256",
        )},
    )
    claim = NativeEpisodeClaim(request.episode_id, request.digest(), plan.plan_sha256, "started",
                               RSILedger._native_claim_digest(request.episode_id, request.digest(), plan.plan_sha256),
                               "2026-10-14T00:00:00Z")
    return NativeRSIRejectionEvidence(
        plan=plan, input_binding_sha256=digest("input"), ledger_identity={"database": "/inert/ledger", "device": 1, "inode": 2},
        claim=claim, lineage=lineage, rejected=rejected, terminal=terminal,
        producer_execution_receipt_sha256=terminal.native_execution_receipt_sha256,
        producer_output_sha256=digest("captured-output"),
        execution_receipt_sha256s=tuple(c.execution_receipt_sha256 for c in candidates),
        evaluation_receipt_sha256s=tuple(c.evaluation_receipt_sha256 for c in candidates),
        retained_evidence_sha256s=tuple(digest(f"retained-{i}") for i in range(count)),
    )


def test_pure_roundtrip_is_detached_and_does_not_grant_result_authority():
    evidence = rejection_evidence()
    wire = evidence.to_dict()
    assert NativeRSIRejectionEvidence.from_dict(wire) == evidence
    wire["lineage"]["candidate_ids"].reverse()
    assert evidence.lineage.candidate_ids == ("candidate-0", "candidate-1")
    with pytest.raises(TypeError):
        evidence.ledger_identity["inode"] = 7
    with pytest.raises(NativeRSIRejectionError, match="provenance_missing"):
        map_native_rejection_to_solver_result(evidence.plan.request, evidence.plan, evidence)


@pytest.mark.parametrize("field,value", [
    ("input_binding_sha256", "bad"), ("producer_execution_receipt_sha256", digest("different")),
    ("producer_output_sha256", False), ("execution_receipt_sha256s", (digest("one"),)),
    ("evaluation_receipt_sha256s", (digest("a"), digest("b"))),
    ("retained_evidence_sha256s", [digest("a"), digest("b")]),
])
def test_exact_constructor_rejects_invalid_associations(field, value):
    with pytest.raises(NativeRSIRejectionError):
        replace(rejection_evidence(), **{field: value})


@pytest.mark.parametrize("mutation", ["schema", "extra", "claim", "ledger", "c1", "order", "terminal", "manifest", "subclass-value"])
def test_strict_wire_refuses_shape_type_order_and_crossbound_data(mutation):
    wire = rejection_evidence().to_dict()
    if mutation == "schema":
        wire["schema_version"] = 2
    elif mutation == "extra":
        wire["publication_receipt"] = "invented"
    elif mutation == "claim":
        wire["claim"]["status"] = "failed"
    elif mutation == "ledger":
        wire["ledger_identity"]["inode"] = True
    elif mutation == "c1":
        wire["lineage"]["rejected_sha256"] = digest("other")
    elif mutation == "order":
        wire["execution_receipt_sha256s"].reverse()
    elif mutation == "terminal":
        wire["terminal"]["task_id"] = "another"
    elif mutation == "manifest":
        wire["lineage"]["rejection_manifest_sha256"] = wire["lineage"]["terminal_marker_sha256"]
    else:
        class Digest(str):
            pass
        wire["input_binding_sha256"] = Digest(wire["input_binding_sha256"])
    with pytest.raises(NativeRSIRejectionError):
        NativeRSIRejectionEvidence.from_dict(wire)


@pytest.mark.parametrize("field,value", [("ordinal", True), ("ordinal", 8), ("retained_bytes", -1),
                                          ("candidate_ids", ("same", "same")), ("checkpoint_sha256", "bad")])
def test_c1_strict_constructor_and_wire(field, value):
    with pytest.raises(NativeRSIRejectionError):
        replace(rejection_evidence().lineage, **{field: value})
    wire = deepcopy(rejection_evidence().lineage.to_dict())
    wire["extra"] = "authority"
    with pytest.raises(NativeRSIRejectionError):
        RejectionLineageC1Binding.from_dict(wire)


def test_evidence_and_plan_subclasses_cannot_bypass_exact_boundary():
    class Evidence(NativeRSIRejectionEvidence):
        pass
    original = rejection_evidence()
    with pytest.raises(NativeRSIRejectionError, match="dto_invalid"):
        Evidence(**{field: getattr(original, field) for field in original.__dataclass_fields__})
    tampered = replace(original)
    object.__setattr__(tampered.claim, "status", "failed")
    with pytest.raises(NativeRSIRejectionError, match="claim_mismatch"):
        NativeRSIRejectionEvidence.from_dict(tampered.to_dict())


def test_readback_digest_and_pin_must_be_paired():
    with pytest.raises(NativeRSIRejectionError, match="provenance_pair_invalid"):
        replace(rejection_evidence(), provenance_sha256=digest("orphan"))


def polluted_evidence(mutation, callbacks):
    """Inject inert callback traps after ordinary trusted fixture construction."""
    evidence = rejection_evidence()

    def forbidden(*_args, **_kwargs):
        callbacks.append(mutation)
        raise AssertionError("untrusted callback ran")

    if mutation in {"request-subclass", "candidate-subclass"}:
        dto = evidence.plan.request if mutation == "request-subclass" else evidence.terminal.candidates[0]
        polluted_type = type("CallbackDTO", (type(dto),), {
            "to_dict": forbidden, "digest": forbidden, "__eq__": forbidden,
        })
        polluted = object.__new__(polluted_type)
        for field in fields(type(dto)):
            object.__setattr__(polluted, field.name, getattr(dto, field.name))
        if mutation == "request-subclass":
            object.__setattr__(evidence.plan, "request", polluted)
        else:
            object.__setattr__(evidence.terminal, "candidates", (polluted, *evidence.terminal.candidates[1:]))
    elif mutation in {"request-extra-method", "claim-extra-method"}:
        dto = evidence.plan.request if mutation == "request-extra-method" else evidence.claim
        object.__setattr__(dto, "to_dict", forbidden)
        object.__setattr__(dto, "digest", forbidden)
    elif mutation in {"settings-mapping", "ledger-proxy-mapping"}:
        class CallbackMapping(Mapping):
            __getitem__ = forbidden
            __iter__ = forbidden
            __len__ = forbidden
        polluted = CallbackMapping()
        if mutation == "settings-mapping":
            object.__setattr__(evidence.plan.request, "solver_settings", (("value", polluted),))
        else:
            object.__setattr__(evidence, "ledger_identity", MappingProxyType(polluted))
    elif mutation in {"settings-dict", "settings-list", "settings-str"}:
        builtin = {"settings-dict": dict, "settings-list": list, "settings-str": str}[mutation]
        callback_type = type("CallbackBuiltin", (builtin,), {
            "__iter__": forbidden, "__str__": forbidden, "__len__": forbidden,
        })
        polluted = callback_type()
        object.__setattr__(evidence.plan.request, "solver_settings", (("value", polluted),))
    elif mutation == "c1-tuple":
        class CallbackTuple(tuple):
            __iter__ = forbidden
        object.__setattr__(evidence.lineage, "candidate_ids", CallbackTuple(evidence.lineage.candidate_ids))
    else:
        raise AssertionError(mutation)
    return evidence


CALLBACK_MUTATIONS = (
    "request-subclass", "candidate-subclass", "request-extra-method", "claim-extra-method",
    "settings-mapping", "ledger-proxy-mapping", "settings-dict", "settings-list",
    "settings-str", "c1-tuple",
)


@pytest.mark.parametrize("mutation", CALLBACK_MUTATIONS)
def test_nested_dto_shape_refuses_callbacks_before_constructor_serializer_and_mapper(mutation):
    callbacks = []
    evidence = polluted_evidence(mutation, callbacks)
    with pytest.raises(NativeRSIRejectionError, match="shape_invalid"):
        replace(evidence)
    with pytest.raises(NativeRSIRejectionError, match="shape_invalid"):
        evidence.to_dict()
    with pytest.raises(NativeRSIRejectionError, match="shape_invalid"):
        map_native_rejection_to_solver_result(evidence.plan.request, evidence.plan, evidence)
    assert callbacks == []


@pytest.mark.parametrize("parser", ["evidence", "c1", "pin"])
def test_raw_shape_precedes_hashing_custom_wire_keys(parser):
    from lunar_evolution.rsi_native_rejection import NativeRSIRejectionFilePin

    callbacks = []
    class CallbackKey(str):
        def __hash__(self):
            callbacks.append("hash")
            return str.__hash__(self)
    value = {CallbackKey("schema_version"): "2"}
    callbacks.clear()
    parser_type = {"evidence": NativeRSIRejectionEvidence, "c1": RejectionLineageC1Binding,
                   "pin": NativeRSIRejectionFilePin}[parser]
    with pytest.raises(NativeRSIRejectionError, match="shape_invalid"):
        parser_type.from_dict(value)
    assert callbacks == []


def test_nested_shape_cycles_and_depth_are_bounded_without_callbacks():
    for nested in ([], {"value": []}):
        nested.append(nested) if type(nested) is list else nested["value"].append(nested)
        evidence = rejection_evidence()
        object.__setattr__(evidence.plan.request, "solver_settings", (("cycle", nested),))
        with pytest.raises(NativeRSIRejectionError, match="shape_invalid"):
            evidence.to_dict()
