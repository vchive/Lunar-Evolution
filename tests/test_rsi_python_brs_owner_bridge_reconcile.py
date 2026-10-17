"""Private mailbox composition registers a genuine owner fence before service.

The original inert selected worker creates its claim on its first gateway call.
Only its publication transport is released here; subprocesses, providers and real
evaluators are forbidden. The successful path uses the existing inert evaluation
boundary and the real publication transaction, without claiming process cleanup.
"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from queue import Queue
from threading import Event, get_ident
from types import FunctionType

import pytest
import test_rsi_brs_publication_lineage_owner as owner_fixture
import test_rsi_python_brs_native_dispatch as native_fixture
from test_rsi_python_admission import OTHER, _rows

from lunar_evolution import RSILearningError
from lunar_evolution import rsi_python_brs_native_dispatch as native_dispatch
from lunar_evolution import rsi_python_brs_owner_bridge as bridge
from lunar_evolution.rsi_brs_reconcile import FIELD, BRSReconcileObligation
from lunar_evolution.rsi_python_brs_publication_mailbox import BRSOwnerPublicationMailbox

inert_only = native_fixture.inert_only
tmp_path = native_fixture.tmp_path


@contextmanager
def _mailbox_worker(tmp_path, monkeypatch, *, validity=1, on_response=None):
    class PublicationReady(Event):
        publication = None

        def wait(self, timeout=None):
            released = super().wait(timeout)
            if released and self.publication is not None:
                try:
                    self.publication()
                finally:
                    # Keep the original episode/claim running after publication.
                    # Transport completion is not solver/process terminal evidence.
                    raise owner_fixture._StopWorker()
            return released

    monkeypatch.setattr(owner_fixture, "Event", PublicationReady)
    with native_fixture._waiting(tmp_path, monkeypatch, validity=validity) as value:
        responses = Queue()
        mailbox = BRSOwnerPublicationMailbox(value.wave.selected_handoff, worker_thread=value.worker_thread)

        def request():
            assert get_ident() == value.worker_thread
            try:
                response = mailbox.request(value.request_message, check=lambda: None)
                if on_response is not None:
                    on_response(value, response)
                responses.put(response)
            except BaseException as exc:
                responses.put(exc)
                raise

        value.ready.publication = request
        try:
            yield value, mailbox, responses
        finally:
            mailbox.close()


def _retained(value):
    records = value.ledger.controller_brs_reconcile_obligations(value.binding.run_id)
    assert set(records) == {value.episode_id}
    obligation = BRSReconcileObligation.from_dict(records[value.episode_id])
    assert obligation.handoff_sha256 == value.wave.selected_handoff.sha256
    assert obligation.controller_checkpoint_sha256 == value.wave.selected_handoff.head_sha256
    assert obligation.native_claim_sha256 == value.owner._claim.claim_sha256
    return obligation


def _observing_dispatch(owner, request, *, original_preparation):
    from copy import deepcopy

    from lunar_evolution.rsi_brs_reconcile import FIELD
    from lunar_evolution.rsi_python_brs_native_dispatch import _run_original_brs_native_publication

    obligations = owner._ledger.controller_brs_reconcile_obligations(owner._run_id)
    assert set(obligations) == {owner._request.episode_id}
    assert owner._wave.state[FIELD] == obligations
    globals()["_BRS_BRIDGE_DISPATCH_OBSERVATIONS"].append((owner._head, deepcopy(obligations)))
    return _run_original_brs_native_publication(owner, request, original_preparation=original_preparation)


def test_mailbox_publication_sees_durable_fence_and_success_never_consumes_it(tmp_path, monkeypatch):
    observed = []
    dispatch = FunctionType(_observing_dispatch.__code__, vars(native_dispatch), _observing_dispatch.__name__)

    # Install the observing wrapper before the original source/policy capture.
    monkeypatch.setattr(native_dispatch, "_BRS_BRIDGE_DISPATCH_OBSERVATIONS", observed, raising=False)
    monkeypatch.setattr(bridge, "_run_original_brs_native_publication", dispatch)
    with _mailbox_worker(tmp_path, monkeypatch) as (value, mailbox, responses):
        history = value.ledger.controller_checkpoint_history(value.binding.run_id)
        budget = deepcopy(value.wave.state["budget_state"])
        value.ready.set()
        result = bridge.run_brs_owner_publication_mailbox(
            value.owner, mailbox, value.preparation, check=lambda: None, timeout=10,
        )
        response = responses.get(timeout=10)
        assert not isinstance(response, BaseException)
        assert result.transaction.publication_status == "published"
        assert response.payload == result.response_payload
        assert len(observed) == 1 and observed[0][0] != history[-1][0]
        after = value.ledger.controller_checkpoint_history(value.binding.run_id)
        assert after[:len(history)] == history
        assert after[len(history)][0] == observed[0][0]
        assert after[len(history)][1] == history[-1][1] | {FIELD: observed[0][1]}
        obligation = _retained(value)
        assert obligation.to_dict() == observed[0][1][value.episode_id]
        assert value.owner._phase == "terminal"
        assert value.wave.state["budget_state"] == budget
        assert value.ledger.get_episode(value.episode_id).state == "running"
        assert value.ledger.inspect_native_episode_claim(
            value.request, plan_sha256=value.plan.plan_sha256,
        ).status == "started"
        assert value.ledger.episode_result(value.episode_id) is None
        assert value.ledger.get_episode(value.sibling_id) is None
        assert mailbox.status == "delivered"

    before = value.ledger.controller_checkpoint_history(value.binding.run_id)
    with pytest.raises(RSILearningError, match="^rsi_brs_reconcile_required$"):
        value.controller.resume(value.binding.run_id)
    assert value.ledger.controller_checkpoint_history(value.binding.run_id) == before


def test_empty_mailbox_timeout_still_retains_original_obligation_and_cannot_retry(tmp_path, monkeypatch):
    with native_fixture._waiting(tmp_path, monkeypatch) as value:
        mailbox = BRSOwnerPublicationMailbox(value.wave.selected_handoff, worker_thread=value.worker_thread)
        try:
            with pytest.raises(RSILearningError, match="^rsi_python_brs_owner_bridge_mailbox_not_served$"):
                bridge.run_brs_owner_publication_mailbox(
                    value.owner, mailbox, value.preparation, check=lambda: None, timeout=0,
                )
            _retained(value)
            before = value.ledger.controller_checkpoint_history(value.binding.run_id), _rows(value)
            with pytest.raises(RSILearningError, match="^rsi_brs_publication_lineage_"):
                bridge.run_brs_owner_publication_mailbox(
                    value.owner, mailbox, value.preparation, check=lambda: None, timeout=0,
                )
            assert (value.ledger.controller_checkpoint_history(value.binding.run_id), _rows(value)) == before
            assert not (value.batch / "journal.prepared.json").exists()
        finally:
            mailbox.close()


def test_queued_mailbox_check_failure_keeps_registered_fence_without_dispatch(tmp_path, monkeypatch):
    with _mailbox_worker(tmp_path, monkeypatch) as (value, mailbox, responses):
        value.ready.set()

        def check():
            _retained(value)
            raise RuntimeError("fixture_mailbox_check_unknown")

        with pytest.raises(RuntimeError, match="fixture_mailbox_check_unknown"):
            bridge.run_brs_owner_publication_mailbox(
                value.owner, mailbox, value.preparation, check=check, timeout=10,
            )
        _retained(value)
        assert isinstance(responses.get(timeout=10), RSILearningError)
        assert mailbox.status == "abandoned"
        assert not (value.batch / "journal.prepared.json").exists()
        assert value.ledger.episode_result(value.episode_id) is None
        before = value.ledger.controller_checkpoint_history(value.binding.run_id), _rows(value)
        with pytest.raises(RSILearningError, match="^rsi_python_brs_owner_bridge_mailbox_unavailable$"):
            bridge.run_brs_owner_publication_mailbox(
                value.owner, mailbox, value.preparation, check=lambda: None,
            )
        assert (value.ledger.controller_checkpoint_history(value.binding.run_id), _rows(value)) == before


def test_foreign_mailbox_captures_and_original_control_drift_refuse_before_registration(tmp_path, monkeypatch):
    with native_fixture._waiting(tmp_path, monkeypatch) as value:
        before = value.ledger.controller_checkpoint_history(value.binding.run_id), _rows(value)
        handoff = value.wave.selected_handoff
        faults = {
            "run": ("_identity", ("foreign-run", value.episode_id, handoff.sha256)),
            "episode": ("_identity", (value.binding.run_id, value.sibling_id, handoff.sha256)),
            "handoff": ("_identity", (value.binding.run_id, value.episode_id, OTHER)),
            "head": ("_expected_head", OTHER),
            "state": ("_expected_state", OTHER),
            "thread": ("_owner_thread", value.worker_thread),
        }
        for field, replacement in faults.values():
            mailbox = BRSOwnerPublicationMailbox(handoff, worker_thread=value.worker_thread)
            setattr(mailbox, field, replacement)
            try:
                with pytest.raises(RSILearningError, match="^rsi_python_brs_owner_bridge_mailbox_binding_invalid$"):
                    bridge.run_brs_owner_publication_mailbox(
                        value.owner, mailbox, value.preparation, check=lambda: None, timeout=0,
                    )
                assert (value.ledger.controller_checkpoint_history(value.binding.run_id), _rows(value)) == before
            finally:
                mailbox.close()
        value.control.deadline += 1
        mailbox = BRSOwnerPublicationMailbox(handoff, worker_thread=value.worker_thread)
        try:
            with pytest.raises(RSILearningError, match="control_drift"):
                bridge.run_brs_owner_publication_mailbox(
                    value.owner, mailbox, value.preparation, check=lambda: None, timeout=0,
                )
            assert (value.ledger.controller_checkpoint_history(value.binding.run_id), _rows(value)) == before
            assert not value.ledger.controller_brs_reconcile_obligations(value.binding.run_id)
        finally:
            mailbox.close()
