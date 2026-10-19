"""Provider-free contract tests for the private BRS owner/mailbox composition."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_rsi_python_brs_publication_mailbox import _handoff, _ready

from lunar_evolution import rsi_python_brs_owner_bridge as bridge
from lunar_evolution.native_trusted_scheduler import _NativeTrustedPythonProducerPreparation
from lunar_evolution.producer_bundle_transaction import NativeProducerBundleTransactionResult
from lunar_evolution.rsi_controller import RSILearningController, _PythonAdmissionBRSWave
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_python_brs_publication_mailbox import BRSOwnerPublicationMailbox


def test_owner_bridge_serves_one_detached_request_and_keeps_summary_non_authorizing(monkeypatch):
    handoff = _handoff()
    preparation = object.__new__(_NativeTrustedPythonProducerPreparation)
    journal = object()
    transaction = NativeProducerBundleTransactionResult(
        journal=journal, preflight=None, evaluations=(), admitted_candidate_ids=("candidate-1",),
        rejected_candidate_ids=(), artifacts=(), manifest=None, published_journal=None,
        publication_status="published",
    )
    calls = []
    # Transport-only test: genuine owner/capture/ledger acceptance is exercised
    # separately with the real waiting-worker fixture. No fake owner is accepted
    # by the product gates here; every owner-specific seam is explicitly doubled.
    monkeypatch.setattr(bridge, "_original_control", lambda owner: owner)
    monkeypatch.setattr(bridge, "_require_disabled_policy", lambda owner: None)
    monkeypatch.setattr(bridge, "_require_original_mailbox", lambda owner, mailbox: None)
    monkeypatch.setattr(bridge._BRSLineageCheckpointOwner, "retain_reconcile_obligation", lambda owner: "a" * 64)
    monkeypatch.setattr(bridge._BRSLineageCheckpointOwner, "_success_fixed", lambda owner: None)
    monkeypatch.setattr(bridge, "_run_original_brs_native_publication",
                        lambda owner, request, *, original_preparation: calls.append(
                            (owner, request, original_preparation)) or transaction)
    payload_calls = []
    observations = []

    def retain_observation(owner, stage, *, mailbox_state, worker_receipt_observed,
                           request=None, response=None):
        # This transport double records arguments only. Genuine durable writes,
        # original-owner acceptance and recovery fences have separate fixtures.
        assert not mailbox._condition._is_owned()
        observations.append((owner, stage, mailbox_state, worker_receipt_observed, request, response))
        return "b" * 64

    monkeypatch.setattr(bridge._BRSLineageCheckpointOwner, "retain_mailbox_observation", retain_observation)

    def response_payload(result, request, selected_handoff):
        payload_calls.append((result, request, selected_handoff))
        return b'{"status":"published"}'

    monkeypatch.setattr(bridge, "_response_payload", response_payload)
    owner = SimpleNamespace(_handoff=handoff, _handoff_bytes=handoff.canonical_bytes,
                            _rejection_ready_state="unused", _reserved_prefix=None)

    with ThreadPoolExecutor(max_workers=1) as pool:
        worker = pool.submit(threading.get_ident).result(timeout=5)
        mailbox = BRSOwnerPublicationMailbox(handoff, worker_thread=worker)
        try:
            pending = pool.submit(mailbox.request, _ready(handoff), check=lambda: None)
            result = bridge.run_brs_owner_publication_mailbox(
                owner, mailbox, preparation, check=lambda: None, timeout=5,
            )
            response = pending.result(timeout=5)
        finally:
            mailbox.close()

    assert result.transaction is transaction
    assert result.response_payload == b'{"status":"published"}'
    assert response.payload == result.response_payload
    assert len(calls) == 1 and calls[0][2] is preparation
    assert len(payload_calls) == 1 and payload_calls[0][0] is transaction
    assert payload_calls[0][1] == _ready(handoff) and payload_calls[0][2] == handoff
    assert mailbox.status == "delivered"
    assert [entry[1] for entry in observations] == [
        "owner_capture", "request_observed", "response_generated", "transport_observed",
    ]
    assert all(entry[0] is owner for entry in observations)
    captured, requested, generated, transported = observations
    assert captured[2] in {"open", "queued"} and captured[3] is False and captured[5] is None
    assert (captured[4] is None) == (captured[2] == "open")
    if captured[4] is not None:
        assert captured[4] == _ready(handoff)
    assert requested[2:4] == ("inflight", False) and requested[5] is None
    assert requested[4] == _ready(handoff)
    assert generated[2:4] == ("inflight", False)
    assert generated[4] == requested[4] and generated[5] == response
    assert transported[2] == "delivered" and type(transported[3]) is bool
    assert transported[4:] == generated[4:]
    # The mailbox envelope digest binds its DTO; the selected SolverRequest
    # digest remains a separate domain. Neither supplies a SolverResult digest.
    assert response.request_sha256 == requested[4].request_sha256
    assert requested[4].request_sha256 != handoff.request_sha256
    assert not hasattr(response, "owner_result_sha256")
    assert not hasattr(response, "transaction")
    assert vars(owner) == {"_handoff": handoff, "_handoff_bytes": handoff.canonical_bytes,
                           "_rejection_ready_state": "unused", "_reserved_prefix": None}


@pytest.mark.parametrize("field", ["mailbox", "preparation"])
def test_owner_bridge_refuses_wrong_contract_before_owner_or_worker_effect(monkeypatch, field):
    handoff = _handoff()
    preparation = object.__new__(_NativeTrustedPythonProducerPreparation)
    mailbox = object() if field == "mailbox" else BRSOwnerPublicationMailbox(
        handoff, worker_thread=threading.get_ident() + 1,
    )
    if field == "preparation":
        # The mailbox is intentionally never submitted; this checks the preparation
        # contract before the owner control hook or any transaction callback.
        preparation = object()
    owner_calls = []
    monkeypatch.setattr(bridge, "_original_control", lambda owner: owner_calls.append(owner))
    with pytest.raises(RSILearningError, match="rsi_python_brs_owner_bridge_"):
        bridge.run_brs_owner_publication_mailbox(
            object(), mailbox, preparation, check=lambda: None,
        )
    assert owner_calls == []


def test_full_gate_nested_scope_refuses_foreign_wave_or_handoff():
    controller = object.__new__(RSILearningController)
    controller._python_admission_brs_local = threading.local()

    def wave():
        return _PythonAdmissionBRSWave(
            controller, {}, "run", (), object(), Path("."), object(), threading.get_ident(),
            "h", b"{}", None, {},
        )

    outer_wave = wave()
    foreign_wave = wave()
    handoff = object()
    with controller._python_admission_brs_full_gate_scope(outer_wave, handoff):
        with pytest.raises(RSILearningError, match="rsi_python_brs_admission_scope_invalid"), \
                controller._python_admission_brs_full_gate_scope(foreign_wave, handoff):
            pass
        with pytest.raises(RSILearningError, match="rsi_python_brs_admission_scope_invalid"), \
                controller._python_admission_brs_full_gate_scope(outer_wave, object()):
            pass
    assert getattr(controller._python_admission_brs_local, "full_gate_scope", None) is None
