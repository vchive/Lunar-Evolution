"""Provider-free exact BRS owner-result delivery and one-shot settlement."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest
from test_rsi_python_brs_publication_mailbox import _handoff, _ready

from lunar_evolution.producer_bundle_publication import (
    ProducerBundlePublicationCandidate,
    ProducerBundlePublicationJournal,
)
from lunar_evolution.producer_bundle_transaction import NativeProducerBundleTransactionResult
from lunar_evolution.rsi_python_brs_publication_mailbox import build_brs_owner_publication_response
from lunar_evolution.rsi_python_brs_result_delivery import (
    BRSOwnerResultDeliveryError,
    build_brs_owner_result_payload,
    deliver_brs_owner_result,
)


def digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _request_and_handoff():
    handoff = _handoff()
    return _ready(handoff), handoff


def _journal(handoff, *, state="published"):
    candidate = ProducerBundlePublicationCandidate(
        candidate_id="candidate-1", bundle_id="bundle-1", bundle_sha256=digest("bundle"),
        parent_id=None, generation=0, iteration=0, island_id=0,
        preparation_receipt_sha256=digest("prepare"),
        execution_receipt_sha256=digest("execute"), evaluation_receipt_sha256=digest("evaluate"),
        publication_receipt_sha256=digest("publish") if state == "published" else None,
        status="admitted" if state == "published" else "rejected",
    )
    return ProducerBundlePublicationJournal(
        journal_id="mailbox-journal", run_id=handoff.run_id,
        parent_task_id="parent", task_id=handoff.episode_id,
        admission_sha256=digest("admission"), archive_prefix_sha256=digest("prefix"),
        base_archive_sha256=digest("archive"), base_state_sha256=digest("state"),
        contract_sha256=digest("contract"), evaluator_kind="local",
        evaluator_fingerprint=digest("evaluator"), runner_fingerprint=digest("runner"),
        dependency_sha256=digest("dependency"), environment_sha256=digest("environment"),
        budget_sha256=digest("budget"), strategy="population", population_config_sha256=digest("config"),
        num_islands=1, candidates=(candidate,), state=state, publication_phase="committed",
        terminal_marker_sha256=digest("marker"),
        archive_after_sha256=digest("archive") if state == "all_rejected" else digest("archive-after"),
        state_after_sha256=digest("state") if state == "all_rejected" else digest("state-after"),
        native_execution_receipt_sha256=digest("receipt"),
    )


def _transaction(handoff, *, state="published"):
    journal = _journal(handoff, state=state)
    return NativeProducerBundleTransactionResult(
        journal=journal, preflight=None, evaluations=(),
        admitted_candidate_ids=("candidate-1",) if state == "published" else (),
        rejected_candidate_ids=() if state == "published" else ("candidate-1",),
        artifacts=(), manifest=None,
        published_journal=journal if state == "published" else None,
        publication_status=state, terminal_journal=journal,
    )


def _response(result, request, handoff):
    payload = build_brs_owner_result_payload(result, request, handoff)
    return build_brs_owner_publication_response(request, payload)


def test_exact_owner_result_roundtrip_settles_once_without_authority_leak():
    request, handoff = _request_and_handoff()
    response = _response(_transaction(handoff), request, handoff)
    settlement = deliver_brs_owner_result(
        response, request, handoff,
        expected_native_plan_sha256="a" * 64,
        expected_journal_sha256=_journal(handoff).digest(),
    )
    observed = []
    assert settlement.status == "pending"
    assert settlement.settle(lambda value: observed.append(value) or "saved") == "saved"
    assert settlement.status == "settled"
    assert len(observed) == 1
    assert observed[0].run_id == handoff.run_id
    assert observed[0].episode_id == handoff.episode_id
    assert observed[0].publication_status == "published"
    with pytest.raises(BRSOwnerResultDeliveryError, match="settlement_unavailable"):
        settlement.settle(lambda _value: pytest.fail("duplicate settlement invoked"))


def test_all_rejected_result_is_delivered_as_terminal_observation():
    request, handoff = _request_and_handoff()
    response = _response(_transaction(handoff, state="all_rejected"), request, handoff)
    settlement = deliver_brs_owner_result(response, request, handoff)
    assert settlement.delivery.publication_status == "all_rejected"
    assert settlement.delivery.admitted_candidate_ids == ()


@pytest.mark.parametrize("changed", ["run_id", "episode_id", "handoff_sha256", "request_sha256"])
def test_response_identity_drift_refuses_before_settlement(changed):
    request, handoff = _request_and_handoff()
    response = _response(_transaction(handoff), request, handoff)
    value = "foreign-run" if changed == "run_id" else "foreign-episode" if changed == "episode_id" else "f" * 64
    object.__setattr__(response, changed, value)
    with pytest.raises(BRSOwnerResultDeliveryError, match="response_invalid"):
        deliver_brs_owner_result(response, request, handoff)


@pytest.mark.parametrize("kwargs,code", [
    ({"expected_native_plan_sha256": "b" * 64}, "preparation_mismatch"),
    ({"expected_journal_sha256": digest("different")}, "journal_mismatch"),
])
def test_preparation_or_journal_drift_refuses_without_callback(kwargs, code):
    request, handoff = _request_and_handoff()
    response = _response(_transaction(handoff), request, handoff)
    with pytest.raises(BRSOwnerResultDeliveryError, match=code):
        deliver_brs_owner_result(response, request, handoff, **kwargs)


def test_payload_binding_and_canonical_mutation_refuse_before_callback():
    request, handoff = _request_and_handoff()
    response = _response(_transaction(handoff), request, handoff)
    payload = json.loads(response.payload)
    payload["episode_id"] = "other-practice-0-0"
    forged = build_brs_owner_publication_response(
        request, json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
    )
    with pytest.raises(BRSOwnerResultDeliveryError, match="payload_binding_mismatch"):
        deliver_brs_owner_result(forged, request, handoff)


def test_callback_failure_becomes_unknown_and_is_never_retried():
    request, handoff = _request_and_handoff()
    response = _response(_transaction(handoff), request, handoff)
    settlement = deliver_brs_owner_result(response, request, handoff)
    calls = []

    def fail(value):
        calls.append(value)
        raise RuntimeError("worker write lost")

    with pytest.raises(BRSOwnerResultDeliveryError, match="settlement_unknown"):
        settlement.settle(fail)
    assert settlement.status == "unknown" and len(calls) == 1
    with pytest.raises(BRSOwnerResultDeliveryError, match="settlement_unavailable"):
        settlement.settle(fail)
    assert len(calls) == 1


def test_result_builder_refuses_foreign_transaction_and_cross_bound_request():
    request, handoff = _request_and_handoff()
    with pytest.raises(BRSOwnerResultDeliveryError, match="transaction_invalid"):
        build_brs_owner_result_payload(object(), request, handoff)
    foreign = replace(handoff, run_id="foreign-run", episode_id="foreign-run-practice-0-0")
    with pytest.raises(BRSOwnerResultDeliveryError, match="request_handoff_mismatch"):
        build_brs_owner_result_payload(_transaction(handoff), request, foreign)
