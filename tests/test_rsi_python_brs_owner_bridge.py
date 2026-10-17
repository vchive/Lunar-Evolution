"""Provider-free contract tests for the private BRS owner/mailbox composition."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from test_rsi_python_brs_publication_mailbox import _handoff, _ready

from lunar_evolution import rsi_python_brs_owner_bridge as bridge
from lunar_evolution.native_trusted_scheduler import _NativeTrustedPythonProducerPreparation
from lunar_evolution.producer_bundle_transaction import NativeProducerBundleTransactionResult
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

    def response_payload(result, request, selected_handoff):
        payload_calls.append((result, request, selected_handoff))
        return b'{"status":"published"}'

    monkeypatch.setattr(bridge, "_response_payload", response_payload)
    owner = SimpleNamespace(_handoff=handoff, _handoff_bytes=handoff.canonical_bytes)

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
