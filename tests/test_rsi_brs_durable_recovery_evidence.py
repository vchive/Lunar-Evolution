"""Genuine original owner/worker evidence, with inert native publication only."""
from __future__ import annotations

import hashlib
import json
from threading import Event
from types import FunctionType

import pytest
import test_rsi_python_brs_owner_bridge_reconcile as fixture
import test_rsi_python_brs_publication_mailbox as mailbox_fixture

from lunar_evolution import RSILearningError
from lunar_evolution import rsi_brs_publication_lineage as lineage
from lunar_evolution import rsi_python_brs_publication_mailbox as transport
from lunar_evolution import rsi_store as store
from lunar_evolution.rsi_brs_mailbox_evidence import STAGES, inspect_brs_mailbox_evidence
from lunar_evolution.rsi_brs_publication_lineage import _policy
from lunar_evolution.rsi_fingerprint import RSIFingerprintContract
from lunar_evolution.rsi_python_brs_owner_bridge import run_brs_owner_publication_mailbox
from lunar_evolution.rsi_store import RSILedger

inert_only = fixture.inert_only
tmp_path = fixture.tmp_path


def _observing_writer(self, binding, observation, *, expected_sha256):
    condition = globals().get("_BRS_EVIDENCE_CONDITION")
    if condition is not None:
        assert not condition._is_owned(), "evidence writer ran under mailbox condition"
    fault = observation["stage"] == globals().get("_BRS_EVIDENCE_FAILURE_STAGE")
    if fault and globals().get("_BRS_EVIDENCE_FAILURE_MODE") == "before":
        raise RuntimeError("fixture_evidence_append_unknown")
    head = globals()["_BRS_EVIDENCE_ORIGINAL_WRITER"](
        self, binding, observation, expected_sha256=expected_sha256,
    )
    if fault:
        if globals().get("_BRS_EVIDENCE_FAILURE_MODE") == "readback":
            return "a" * 64
        raise RuntimeError("fixture_evidence_append_unknown")
    return head


def _install_writer(monkeypatch, *, stage=None, mode=None):
    monkeypatch.setattr(store, "_BRS_EVIDENCE_ORIGINAL_WRITER", RSILedger.append_brs_mailbox_observation, raising=False)
    monkeypatch.setattr(store, "_BRS_EVIDENCE_FAILURE_STAGE", stage, raising=False)
    monkeypatch.setattr(store, "_BRS_EVIDENCE_FAILURE_MODE", mode, raising=False)
    writer = FunctionType(_observing_writer.__code__, vars(store), _observing_writer.__name__)
    monkeypatch.setattr(RSILedger, "append_brs_mailbox_observation", writer)


def test_policy_recovery_groups_round_trip_with_existing_fingerprint_limits():
    contract = RSIFingerprintContract.build(
        contract_sha256="a" * 64, evaluator_sha256="b" * 64,
        environment_sha256="c" * 64, memory_snapshot_sha256="d" * 64,
        solver_id="fixture", solver_settings={"producer_brs_checkpoint_policy": _policy()},
        actor_fingerprint="e" * 64, verifier_fingerprint="f" * 64,
        curriculum_fingerprint="1" * 64, target_judge_fingerprint="2" * 64,
    )
    assert RSIFingerprintContract.from_dict(contract.to_dict()).digest() == contract.digest()


def test_original_owner_four_stages_preserve_exact_payload_and_restart_fence(tmp_path, monkeypatch):
    _install_writer(monkeypatch)
    with fixture._mailbox_worker(tmp_path, monkeypatch) as (value, mailbox, responses):
        monkeypatch.setattr(store, "_BRS_EVIDENCE_CONDITION", mailbox._condition, raising=False)
        original_budget = value.owner._budget_bytes
        value.ready.set()
        result = run_brs_owner_publication_mailbox(
            value.owner, mailbox, value.preparation, check=lambda: None, timeout=10,
        )
        response = responses.get(timeout=10)
        assert not isinstance(response, BaseException)
        evidence = inspect_brs_mailbox_evidence(value.ledger, value.binding.run_id, value.episode_id)
        assert evidence["status"] == "transport_observed"
        records = evidence["records"]
        assert [record["stage"] for record in records] == list(STAGES)
        assert all(record["callback_observation"] == "unobserved" for record in records)
        assert type(records[-1]["worker_receipt_observed"]) is bool
        assert all(record["worker_receipt_observed"] is False for record in records[:-1])
        assert records[1]["mailbox_request_sha256"] == value.request_message.request_sha256
        assert records[1]["request_payload_sha256"] == hashlib.sha256(value.request_message.payload).hexdigest()
        assert records[2]["response_sha256"] == response.response_sha256
        assert records[2]["response_payload_sha256"] == hashlib.sha256(response.payload).hexdigest()
        assert result.response_payload == response.payload
        assert evidence["binding"]["selected_request_sha256"] == value.request.digest()
        assert evidence["binding"]["selected_request_sha256"] != records[1]["mailbox_request_sha256"]
        assert evidence["binding"]["capture"]["native_process"]["status"] == "unknown"
        assert evidence["binding"]["capture"]["native_process"]["references"] is None
        assert json.loads(value.owner._mailbox_history_bytes)[-1][0] == evidence["head"]
        assert value.owner._budget_bytes == original_budget
        assert value.ledger.episode_result(value.episode_id) is None
        assert fixture._retained(value).owner_result_sha256 is None

    rebuilt = RSILedger(value.ledger.database)
    before = value.ledger.database.read_bytes()
    assert inspect_brs_mailbox_evidence(rebuilt, value.binding.run_id, value.episode_id) == evidence
    assert value.ledger.database.read_bytes() == before
    with pytest.raises(RSILearningError, match="^rsi_brs_reconcile_required$"):
        value.controller.resume(value.binding.run_id)


def test_open_timeout_retains_capture_without_request_and_cannot_refresh_it(tmp_path, monkeypatch):
    with fixture.native_fixture._waiting(tmp_path, monkeypatch) as value:
        mailbox = fixture.BRSOwnerPublicationMailbox(value.wave.selected_handoff, worker_thread=value.worker_thread)
        try:
            with pytest.raises(RSILearningError, match="mailbox_not_served"):
                run_brs_owner_publication_mailbox(
                    value.owner, mailbox, value.preparation, check=lambda: None, timeout=0,
                )
            evidence = inspect_brs_mailbox_evidence(value.ledger, value.binding.run_id, value.episode_id)
            assert evidence["status"] == "partial"
            assert len(evidence["records"]) == 1
            capture = evidence["records"][0]
            assert capture["stage"] == "owner_capture" and capture["mailbox_state"] == "open"
            assert capture["mailbox_request_sha256"] is None
            before = value.ledger.controller_checkpoint_history(evidence["namespace"])
            with pytest.raises(RSILearningError):
                run_brs_owner_publication_mailbox(
                    value.owner, mailbox, value.preparation, check=lambda: None, timeout=0,
                )
            assert value.ledger.controller_checkpoint_history(evidence["namespace"]) == before
            assert value.ledger.episode_result(value.episode_id) is None
        finally:
            mailbox.close()


@pytest.mark.parametrize("stage", STAGES)
@pytest.mark.parametrize("mode", ("before", "after"))
def test_uncertain_append_poison_keeps_old_cursor_and_durable_prefix(tmp_path, monkeypatch, stage, mode):
    _install_writer(monkeypatch, stage=stage, mode=mode)
    with fixture._mailbox_worker(tmp_path, monkeypatch) as (value, mailbox, _responses):
        monkeypatch.setattr(store, "_BRS_EVIDENCE_CONDITION", mailbox._condition, raising=False)
        value.ready.set()
        with pytest.raises(RuntimeError, match="fixture_evidence_append_unknown"):
            run_brs_owner_publication_mailbox(
                value.owner, mailbox, value.preparation, check=lambda: None, timeout=10,
            )
        evidence = inspect_brs_mailbox_evidence(value.ledger, value.binding.run_id, value.episode_id)
        prior = list(STAGES).index(stage)
        assert len(evidence["records"]) == prior + int(mode == "after")
        assert len(json.loads(value.owner._mailbox_history_bytes)) == prior
        assert value.owner._poisoned is True
        assert fixture._retained(value).owner_result_sha256 is None
        assert value.ledger.episode_result(value.episode_id) is None
        before = value.ledger.controller_checkpoint_history(evidence["namespace"])
        with pytest.raises(RSILearningError):
            value.owner.retain_mailbox_observation("owner_capture", mailbox_state="open", worker_receipt_observed=False)
        assert value.ledger.controller_checkpoint_history(evidence["namespace"]) == before


@pytest.mark.parametrize("stage", ("owner_capture", "response_generated"))
def test_wrong_append_head_keeps_actual_record_but_never_acknowledges_cursor(tmp_path, monkeypatch, stage):
    _install_writer(monkeypatch, stage=stage, mode="readback")
    with fixture._mailbox_worker(tmp_path, monkeypatch) as (value, mailbox, _responses):
        value.ready.set()
        with pytest.raises(RSILearningError, match="mailbox_observation_readback_invalid"):
            run_brs_owner_publication_mailbox(
                value.owner, mailbox, value.preparation, check=lambda: None, timeout=10,
            )
        evidence = inspect_brs_mailbox_evidence(value.ledger, value.binding.run_id, value.episode_id)
        prior = list(STAGES).index(stage)
        assert len(evidence["records"]) == prior + 1
        assert len(json.loads(value.owner._mailbox_history_bytes)) == prior
        assert value.owner._poisoned is True
        assert fixture._retained(value).owner_result_sha256 is None


def _late_readback(self, namespace, expected, binding):
    globals()["_BRS_EVIDENCE_ORIGINAL_READBACK"](self, namespace, expected, binding)
    if len(expected) != 1:
        return
    counts = globals()["_BRS_EVIDENCE_READBACK_COUNTS"]
    counts.append(1)
    if len(counts) != 2:
        return
    fault = globals()["_BRS_EVIDENCE_READBACK_FAULT"]
    if fault == "cancel":
        self._before_control.cancel()
    elif fault == "close":
        self._channel.close()
    else:
        self._before_control.deadline = 0.0


@pytest.mark.parametrize("fault", ("cancel", "close", "deadline"))
def test_final_readback_control_change_preserves_old_cursor(tmp_path, monkeypatch, fault):
    monkeypatch.setattr(lineage, "_BRS_EVIDENCE_ORIGINAL_READBACK", lineage._BRSLineageCheckpointOwner._mailbox_readback, raising=False)
    monkeypatch.setattr(lineage, "_BRS_EVIDENCE_READBACK_COUNTS", [], raising=False)
    monkeypatch.setattr(lineage, "_BRS_EVIDENCE_READBACK_FAULT", fault, raising=False)
    method = FunctionType(_late_readback.__code__, vars(lineage), _late_readback.__name__)
    monkeypatch.setattr(lineage._BRSLineageCheckpointOwner, "_mailbox_readback", method)
    with fixture._mailbox_worker(tmp_path, monkeypatch) as (value, mailbox, _responses):
        value.ready.set()
        with pytest.raises(RSILearningError):
            run_brs_owner_publication_mailbox(
                value.owner, mailbox, value.preparation, check=lambda: None, timeout=10,
            )
        evidence = inspect_brs_mailbox_evidence(value.ledger, value.binding.run_id, value.episode_id)
        assert [record["stage"] for record in evidence["records"]] == ["owner_capture"]
        assert json.loads(value.owner._mailbox_history_bytes) == []
        assert value.owner._mailbox_binding_bytes is None
        assert value.owner._poisoned is True
        assert fixture._retained(value).owner_result_sha256 is None


def _receipt_snapshot(self):
    snapshot = globals()["_BRS_EVIDENCE_ORIGINAL_SNAPSHOT"](self)
    if snapshot[0] == "delivered":
        assert globals()["_BRS_EVIDENCE_WORKER_RECEIPT"].wait(10)
        snapshot = globals()["_BRS_EVIDENCE_ORIGINAL_SNAPSHOT"](self)
    return snapshot


def test_worker_actual_dto_receipt_is_observed_without_claiming_callback_completion(tmp_path, monkeypatch):
    received = Event()
    monkeypatch.setattr(transport, "_BRS_EVIDENCE_ORIGINAL_SNAPSHOT", transport.BRSOwnerPublicationMailbox._observation_snapshot, raising=False)
    monkeypatch.setattr(transport, "_BRS_EVIDENCE_WORKER_RECEIPT", received, raising=False)
    snapshot = FunctionType(_receipt_snapshot.__code__, vars(transport), _receipt_snapshot.__name__)
    monkeypatch.setattr(transport.BRSOwnerPublicationMailbox, "_observation_snapshot", snapshot)
    with fixture._mailbox_worker(tmp_path, monkeypatch, on_response=lambda *_args: received.set()) as (value, mailbox, responses):
        value.ready.set()
        run_brs_owner_publication_mailbox(value.owner, mailbox, value.preparation, check=lambda: None, timeout=10)
        assert not isinstance(responses.get(timeout=10), BaseException)
        evidence = inspect_brs_mailbox_evidence(value.ledger, value.binding.run_id, value.episode_id)
        assert evidence["records"][-1]["worker_receipt_observed"] is True
        assert evidence["records"][-1]["callback_observation"] == "unobserved"
        assert value.ledger.episode_result(value.episode_id) is None


def _abandoned_snapshot(self):
    snapshot = globals()["_BRS_EVIDENCE_ORIGINAL_SNAPSHOT"](self)
    if snapshot[0] in {"delivered", "abandoned"}:
        error = globals()["_BRS_EVIDENCE_WORKER_ERRORS"].get(timeout=10)
        assert isinstance(error, RuntimeError)
        snapshot = globals()["_BRS_EVIDENCE_ORIGINAL_SNAPSHOT"](self)
    return snapshot


def test_worker_abandon_after_delivery_preserves_generated_response_without_receipt(tmp_path, monkeypatch):
    monkeypatch.setattr(transport, "_BRS_EVIDENCE_ORIGINAL_SNAPSHOT", transport.BRSOwnerPublicationMailbox._observation_snapshot, raising=False)
    snapshot = FunctionType(_abandoned_snapshot.__code__, vars(transport), _abandoned_snapshot.__name__)
    monkeypatch.setattr(transport.BRSOwnerPublicationMailbox, "_observation_snapshot", snapshot)

    def reject_response(_value, mailbox):
        if mailbox.status == "delivered":
            raise RuntimeError("fixture_worker_did_not_take_dto")

    with fixture._mailbox_worker(tmp_path, monkeypatch, worker_check=reject_response) as (value, mailbox, responses):
        monkeypatch.setattr(transport, "_BRS_EVIDENCE_WORKER_ERRORS", responses, raising=False)
        value.ready.set()
        result = run_brs_owner_publication_mailbox(value.owner, mailbox, value.preparation, check=lambda: None, timeout=10)
        assert result.worker_receipt_observed is False
        with pytest.raises(RSILearningError, match="^rsi_python_brs_owner_bridge_worker_receipt_unknown$"):
            _ = result.transaction
        evidence = inspect_brs_mailbox_evidence(value.ledger, value.binding.run_id, value.episode_id)
        generated, observed = evidence["records"][-2:]
        assert observed["stage"] == "transport_observed" and observed["mailbox_state"] == "abandoned"
        assert observed["worker_receipt_observed"] is False
        assert observed["response_sha256"] == generated["response_sha256"]
        assert observed["response_payload_sha256"] == hashlib.sha256(result.response_payload).hexdigest()
        assert observed["callback_observation"] == "unobserved"
        assert value.ledger.episode_result(value.episode_id) is None
        assert fixture._retained(value).owner_result_sha256 is None


def test_request_slot_getters_and_response_validation_run_outside_mailbox_condition(monkeypatch):
    with mailbox_fixture._bound() as value:
        request = mailbox_fixture._ready(value.handoff)
        descriptor = vars(transport.BRSOwnerPublicationRequest)["payload"]
        original = transport.BRSOwnerPublicationResponse.__post_init__
        observations = []

        def payload(item):
            assert not value.box._condition._is_owned()
            observations.append("request-payload")
            return descriptor.__get__(item, type(item))

        def validate(item):
            assert not value.box._condition._is_owned()
            observations.append("response-validation")
            original(item)

        monkeypatch.setattr(transport.BRSOwnerPublicationRequest, "payload", property(payload, descriptor.__set__))
        monkeypatch.setattr(transport.BRSOwnerPublicationResponse, "__post_init__", validate)
        future = mailbox_fixture._submit(value, request)
        mailbox_fixture._until(lambda: value.box.status == "queued")
        snapshot = value.box._observation_snapshot()
        assert snapshot[0] == "queued" and snapshot[2][3] == request.payload
        assert value.box.service(lambda _request: b'{"fixture":true}', check=lambda: None)
        assert future.result(timeout=10).payload == b'{"fixture":true}'
        assert "request-payload" in observations and observations.count("response-validation") >= 2
