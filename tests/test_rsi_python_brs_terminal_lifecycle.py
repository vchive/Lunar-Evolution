"""Private lifecycle components; synthetic messages never grant recovery authority."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace

import pytest
import test_rsi_brs_mailbox_evidence as mailbox_fixture
from test_rsi_python_brs_result_delivery import _request_and_handoff, _response, _transaction

from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_python_brs_admission import BRSAdmissionChannel
from lunar_evolution.rsi_python_brs_publication_mailbox import BRSOwnerPublicationMailbox
from lunar_evolution.rsi_python_brs_terminal_lifecycle import (
    BINDING_PROTOCOL,
    BRSOwnerTerminalLifecycle,
    _BRSWorkerTerminalEndpoint,
    _PrimitiveExchange,
    brs_terminal_evidence_namespace,
    build_brs_terminal_observation,
    inspect_brs_worker_terminal_evidence,
    parse_brs_terminal_binding,
    parse_brs_terminal_observation,
    validate_brs_terminal_history,
)

capture = mailbox_fixture.capture
HEX = "a" * 64


def _seal(value, field):
    value[field] = hashlib.sha256(canonical_json({key: item for key, item in value.items() if key != field})).hexdigest()
    return value


def _binding(value):
    owner = value.binding["handoff"]["owner_thread_id"]
    return _seal({"protocol": BINDING_PROTOCOL, "mailbox_binding": value.binding,
                  "owner_thread_id": owner, "worker_thread_id": owner + 1,
                  "future_id": "future-1", "executor_id": "executor-2", "thread_id": "thread-3"}, "binding_sha256")


def _delivery(value):
    request, handoff = value.mailbox_request, value.handoff
    transaction = _transaction(handoff)
    journal = transaction.published_journal
    response = _response(transaction, request, handoff)
    # Deliberately component-only publication. The full composer must still
    # independently validate real persisted lineage and filesystem material.
    manifest = _seal({"journal_id": journal.journal_id, "archive_after_sha256": journal.archive_after_sha256,
                      "state_after_sha256": journal.state_after_sha256}, "manifest_sha256")
    return {"request_fields": [request.run_id, request.episode_id, request.handoff_sha256,
                               request.payload.decode(), request.request_sha256],
            "response_fields": [response.run_id, response.episode_id, response.handoff_sha256,
                                response.request_sha256, response.payload.decode(), response.response_sha256],
            "publication": {"journal": journal.to_dict(), "manifest": manifest,
                            "lineage": {"batches": [{"state": "terminal"}],
                                        "head": {"journal_id": journal.journal_id,
                                                 "terminal_sha256": journal.terminal_marker_sha256}}}}


def test_exact_binding_and_component_history_are_observations_only(capture):
    binding = _binding(capture)
    facts = [_delivery(capture), {"attempt": 1}, {"attempt": 1, "outcome": "returned"},
             {"future_outcome": "returned", "executor_joined": True, "mailbox_closed": True, "worker_exited": True}]
    history = []
    for index, stage in enumerate(("delivery", "callback_started", "callback_finished", "worker_terminal")):
        record = build_brs_terminal_observation(binding, stage=stage, root_checkpoint_sha256=HEX, facts=facts[index])
        history.append((hashlib.sha256(stage.encode()).hexdigest(), record))
        assert validate_brs_terminal_history(history, binding=binding) == history[-1]
        assert "evidence" not in record
    assert brs_terminal_evidence_namespace(binding) == "rsi-brs-terminal:" + capture.binding["obligation_sha256"]
    assert capture.ledger.episode_result(capture.episode_id) is None
    assert capture.ledger.controller_brs_reconcile_obligations(capture.run_id)
    with pytest.raises(RSILearningError, match="history_invalid"):
        validate_brs_terminal_history(history[::-1])
    with pytest.raises(RSILearningError, match="history_invalid"):
        validate_brs_terminal_history([history[0], history[0]])


@pytest.mark.parametrize("fault", ["bool_thread", "same_thread", "object_id", "extra", "digest", "foreign_binding"])
def test_binding_refuses_rebound_or_malformed_identity(capture, fault):
    binding = _binding(capture)
    if fault == "bool_thread":
        binding["worker_thread_id"] = True
    elif fault == "same_thread":
        binding["worker_thread_id"] = binding["owner_thread_id"]
    elif fault == "object_id":
        binding["future_id"] = "future-gg"
    elif fault == "extra":
        binding["grant"] = True
    elif fault == "foreign_binding":
        binding["mailbox_binding"]["selected_request_sha256"] = "b" * 64
    else:
        binding["binding_sha256"] = "b" * 64
    if fault != "digest":
        _seal(binding, "binding_sha256")
    with pytest.raises(RSILearningError):
        parse_brs_terminal_binding(binding)


@pytest.mark.parametrize("fault", ["batch_hook", "manifest", "plan", "response_bytes"])
def test_delivery_revalidates_messages_and_publication_pins(capture, fault):
    facts = _delivery(capture)
    if fault == "batch_hook":
        facts["publication"]["lineage"]["batches"] = [None]
    elif fault == "manifest":
        facts["publication"]["manifest"]["journal_id"] = "other"
        _seal(facts["publication"]["manifest"], "manifest_sha256")
    elif fault == "plan":
        payload = json.loads(facts["request_fields"][3])
        payload["native_plan_sha256"] = "b" * 64
        facts["request_fields"][3] = canonical_json(payload).decode()
    else:
        facts["response_fields"][4] += " "
    with pytest.raises(RSILearningError):
        build_brs_terminal_observation(_binding(capture), stage="delivery", root_checkpoint_sha256=HEX, facts=facts)


@pytest.mark.parametrize("stage,facts", [
    ("callback_started", {"attempt": True}),
    ("callback_started", {"attempt": 2}),
    ("callback_finished", {"attempt": 1, "outcome": "retry"}),
    ("worker_terminal", {"future_outcome": "returned", "executor_joined": 1, "mailbox_closed": True,
                         "worker_exited": True}),
])
def test_exact_stage_facts_refuse_truthy_flags_and_retry(capture, stage, facts):
    with pytest.raises(RSILearningError):
        build_brs_terminal_observation(_binding(capture), stage=stage, root_checkpoint_sha256=HEX, facts=facts)


def test_parser_never_invokes_mapping_hooks(capture):
    class Hook(dict):
        def items(self):
            pytest.fail("foreign mapping hook ran")

    with pytest.raises(RSILearningError, match="shape_invalid"):
        parse_brs_terminal_binding(Hook(_binding(capture)))
    record = build_brs_terminal_observation(_binding(capture), stage="callback_started",
                                           root_checkpoint_sha256=HEX, facts={"attempt": 1})
    record["facts"] = Hook(record["facts"])
    with pytest.raises(RSILearningError, match="shape_invalid"):
        parse_brs_terminal_observation(record)


def _wait_event(exchange, count):
    with exchange.condition:
        assert exchange.condition.wait_for(lambda: len(exchange.events) == count, timeout=5)
        return exchange.events[-1]


def _ack(exchange, count):
    with exchange.condition:
        exchange.acked = count
        exchange.condition.notify_all()


@pytest.mark.parametrize("unknown", [False, True])
def test_endpoint_waits_each_owner_ack_and_never_retries_callback(monkeypatch, unknown):
    request, handoff = _request_and_handoff()
    response = _response(_transaction(handoff), request, handoff)
    mailbox = BRSOwnerPublicationMailbox.__new__(BRSOwnerPublicationMailbox)
    exchange, callbacks, endpoints = _PrimitiveExchange(time.monotonic() + 10), [], []
    monkeypatch.setattr(BRSOwnerPublicationMailbox, "request", lambda *_args, **_kwargs: response)

    def callback(delivery):
        callbacks.append(delivery)
        if unknown:
            raise RuntimeError("inert callback failed")
        return "runner-result"

    def worker():
        endpoint = _BRSWorkerTerminalEndpoint(mailbox, exchange, handoff.canonical_bytes, HEX,
                                               threading.get_ident(), id(threading.current_thread()))
        endpoints.append(endpoint)
        try:
            return endpoint.receive_and_settle(request, callback=callback, check=lambda: None)
        finally:
            with pytest.raises(RSILearningError, match="worker_unavailable"):
                endpoint.receive_and_settle(request, callback=callback, check=lambda: None)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(worker)
        assert _wait_event(exchange, 1)[0] == "delivery"
        assert not callbacks and not future.done()
        _ack(exchange, 1)
        assert _wait_event(exchange, 2) == ("callback_started",)
        assert not callbacks and not future.done()
        _ack(exchange, 2)
        assert _wait_event(exchange, 3) == ("callback_finished", "unknown" if unknown else "returned")
        assert len(callbacks) == 1 and not future.done()
        _ack(exchange, 3)
        if unknown:
            with pytest.raises(RSILearningError, match="settlement_unknown"):
                future.result(timeout=5)
        else:
            assert future.result(timeout=5) == "runner-result"
    assert len(callbacks) == 1
    assert endpoints[0].status == ("unknown" if unknown else "settled")


def test_callback_does_not_run_when_started_ack_fails(monkeypatch):
    request, handoff = _request_and_handoff()
    response = _response(_transaction(handoff), request, handoff)
    mailbox = BRSOwnerPublicationMailbox.__new__(BRSOwnerPublicationMailbox)
    exchange, calls = _PrimitiveExchange(time.monotonic() + 10), []
    monkeypatch.setattr(BRSOwnerPublicationMailbox, "request", lambda *_args, **_kwargs: response)

    def worker():
        endpoint = _BRSWorkerTerminalEndpoint(mailbox, exchange, handoff.canonical_bytes, HEX,
                                               threading.get_ident(), id(threading.current_thread()))
        return endpoint.receive_and_settle(request, callback=lambda value: calls.append(value), check=lambda: None)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(worker)
        _wait_event(exchange, 1)
        _ack(exchange, 1)
        _wait_event(exchange, 2)
        exchange.fail()
        with pytest.raises(RSILearningError):
            future.result(timeout=5)
    assert not calls and len(exchange.events) == 2


def test_endpoint_rejects_wrong_live_thread_object_before_transport(monkeypatch):
    request, handoff = _request_and_handoff()
    mailbox = BRSOwnerPublicationMailbox.__new__(BRSOwnerPublicationMailbox)
    monkeypatch.setattr(BRSOwnerPublicationMailbox, "request", lambda *_args, **_kwargs: pytest.fail("transport ran"))
    endpoint = _BRSWorkerTerminalEndpoint(mailbox, _PrimitiveExchange(None), handoff.canonical_bytes, HEX,
                                           threading.get_ident(), id(threading.current_thread()) + 1)
    with pytest.raises(RSILearningError, match="worker_invalid"):
        endpoint.receive_and_settle(request, callback=lambda value: value, check=lambda: None)


def test_exchange_expired_budget_cannot_be_acknowledged():
    exchange = _PrimitiveExchange(time.monotonic() - 1)
    with pytest.raises(RSILearningError, match="callback_unknown"):
        exchange.submit(("callback_started",), lambda: None)
    _ack(exchange, 1)
    with pytest.raises(RSILearningError, match="worker_unavailable"):
        exchange.submit(("callback_started",), lambda: None)


@pytest.mark.parametrize("event", [None, [], (), (object(),), ("callback_finished", 1),
                                  ("delivery", ("x",) * 5, ("x",) * 6), ("callback_started", "extra"),
                                  ("worker_terminal",)])
def test_exchange_rejects_foreign_events_before_queue_or_check(event):
    exchange = _PrimitiveExchange(time.monotonic() - 1)
    with pytest.raises(RSILearningError, match="observation_drift"):
        exchange.submit(event, lambda: pytest.fail("invalid event ran worker check"))
    assert exchange.events == [] and exchange.acked == 0


@pytest.mark.parametrize("event", [None, (), ("callback_started",), ("delivery", [], ()),
                                  ("delivery", ("x", "x", "x", object(), "x"), ("x",) * 6)])
def test_drain_refuses_nonprimitive_or_out_of_order_events_before_append(monkeypatch, event):
    session = BRSOwnerTerminalLifecycle.__new__(BRSOwnerTerminalLifecycle)
    session._exchange = _PrimitiveExchange(None)
    session._exchange.events.append(event)
    monkeypatch.setattr(BRSOwnerTerminalLifecycle, "_fixed", lambda _self: None)
    monkeypatch.setattr(BRSOwnerTerminalLifecycle, "_append", lambda *_args: pytest.fail("invalid event persisted"))
    with pytest.raises(RSILearningError):
        session._drain()
    assert session._exchange.acked == 0


def test_append_readback_failure_never_advances_local_cursor(capture, monkeypatch):
    binding = _binding(capture)
    session = BRSOwnerTerminalLifecycle.__new__(BRSOwnerTerminalLifecycle)
    session._binding, session._head, session._history = binding, None, []
    durable = []
    ledger = SimpleNamespace(
        controller_lock=lambda _namespace: nullcontext(),
        append_brs_terminal_observation=lambda _binding, record, **_kwargs: durable.append((HEX, record)) or HEX,
        controller_checkpoint_history=lambda _namespace: deepcopy(durable),
        controller_checkpoint=lambda _run_id: ("b" * 64, {}),
    )
    session._owner = SimpleNamespace(_ledger=ledger, _head=HEX, _state={}, _run_id=capture.run_id,
                                     _reserved_prefix=None)
    monkeypatch.setattr(BRSOwnerTerminalLifecycle, "_fixed", lambda _self: None)
    with pytest.raises(RSILearningError, match="readback_drift"):
        session._append("delivery", _delivery(capture))
    assert len(durable) == 1
    assert session._head is None and session._history == []


def test_readonly_reader_rejects_foreign_ledger_before_hooks():
    class Hook:
        def read_brs_terminal_evidence_snapshot(self, *_args):
            pytest.fail("foreign ledger hook ran")

    with pytest.raises(RSILearningError, match="ledger_invalid"):
        inspect_brs_worker_terminal_evidence(Hook(), "run", "episode")


def test_session_scope_rejects_foreign_exchange_before_condition_hook():
    from lunar_evolution.rsi_brs_publication_lineage import _BRSLineageCheckpointOwner

    class Hook:
        @property
        def condition(self):
            pytest.fail("foreign condition hook ran")

    session = BRSOwnerTerminalLifecycle.__new__(BRSOwnerTerminalLifecycle)
    session._owner = _BRSLineageCheckpointOwner.__new__(_BRSLineageCheckpointOwner)
    session._mailbox = BRSOwnerPublicationMailbox.__new__(BRSOwnerPublicationMailbox)
    session._future = Future()
    session._thread = threading.Thread()
    session._endpoint = _BRSWorkerTerminalEndpoint.__new__(_BRSWorkerTerminalEndpoint)
    session._exchange, session._poisoned = Hook(), False
    with ThreadPoolExecutor(max_workers=1) as pool:
        session._executor = pool
        session._scope = (session._owner, session._mailbox, session._future, pool,
                          session._thread, session._endpoint, session._exchange, None)
        with pytest.raises(RSILearningError, match="session_drift"):
            session._fixed()


def test_session_scope_refuses_replacement_before_owner_access(monkeypatch):
    import lunar_evolution.rsi_python_brs_native_dispatch as native
    from lunar_evolution.rsi_brs_publication_lineage import _BRSLineageCheckpointOwner

    session = BRSOwnerTerminalLifecycle.__new__(BRSOwnerTerminalLifecycle)
    session._owner = _BRSLineageCheckpointOwner.__new__(_BRSLineageCheckpointOwner)
    session._mailbox = BRSOwnerPublicationMailbox.__new__(BRSOwnerPublicationMailbox)
    session._future, session._thread = Future(), threading.Thread()
    session._endpoint = _BRSWorkerTerminalEndpoint.__new__(_BRSWorkerTerminalEndpoint)
    session._exchange, session._poisoned = _PrimitiveExchange(None), False
    monkeypatch.setattr(native, "_original_control", lambda *_args: pytest.fail("drifted owner observed"))
    with ThreadPoolExecutor(max_workers=1) as pool:
        session._executor = pool
        session._scope = (session._owner, session._mailbox, session._future, pool,
                          session._thread, session._endpoint, session._exchange, session._exchange.condition)
        session._future = Future()
        with pytest.raises(RSILearningError, match="session_drift"):
            session._fixed()


def test_failure_cleanup_uses_retained_original_scope(monkeypatch):
    import lunar_evolution.rsi_python_brs_owner_bridge as bridge

    class Hook:
        def __getattribute__(self, _name):
            pytest.fail("foreign replacement used during cleanup")

    session = BRSOwnerTerminalLifecycle.__new__(BRSOwnerTerminalLifecycle)
    owner = SimpleNamespace(_poisoned=False)
    mailbox = BRSOwnerPublicationMailbox.__new__(BRSOwnerPublicationMailbox)
    exchange, closed = _PrimitiveExchange(None), []
    monkeypatch.setattr(BRSOwnerTerminalLifecycle, "_fixed", lambda _self: None)
    monkeypatch.setattr(BRSOwnerPublicationMailbox, "close", lambda actual: closed.append(actual))

    def fail(*_args, **_kwargs):
        session._owner = session._mailbox = session._executor = session._exchange = Hook()
        raise RuntimeError("original operation failed")

    monkeypatch.setattr(bridge, "run_brs_owner_publication_mailbox", fail)
    with ThreadPoolExecutor(max_workers=1) as pool:
        session._owner, session._mailbox = owner, mailbox
        session._exchange, session._executor = exchange, pool
        session._started, session._poisoned = False, False
        session._scope = (owner, mailbox, Future(), pool, threading.Thread(), None, exchange, exchange.condition)
        with pytest.raises(RuntimeError, match="original operation failed"):
            session.serve(None, check=lambda: None)
        assert pool._shutdown is True
    assert owner._poisoned is session._poisoned is exchange.failed is True
    assert closed == [mailbox]


def test_original_mailbox_worker_performs_one_intermediate_ready_only_after_arm():
    """Real transport threads; this component fixture creates no owner authority."""
    request, handoff = _request_and_handoff()
    response = _response(_transaction(handoff, state="all_rejected"), request, handoff)
    channel = BRSAdmissionChannel(handoff.run_id, (handoff.episode_id,))
    exchange = _PrimitiveExchange(time.monotonic() + 10)
    payload = canonical_json({"native_plan": {}, "prepared_journal": {}, "expected_anchor_sha256": HEX})
    checked_before_arm, checked_after_receipt = threading.Event(), threading.Event()
    calls, endpoints = [], []
    unarmed_checks = 0

    def check():
        nonlocal unarmed_checks
        if exchange.admission_state == "received":
            checked_after_receipt.set()
        if exchange.admission_offer is payload and channel._rejection_ready_worker_guarded is False:
            unarmed_checks += 1
            if unarmed_checks >= 2:
                checked_before_arm.set()

    with ThreadPoolExecutor(max_workers=1) as pool:
        worker_thread = pool.submit(threading.get_ident).result(timeout=3)
        mailbox = BRSOwnerPublicationMailbox(handoff, worker_thread=worker_thread)

        def worker():
            endpoint = _BRSWorkerTerminalEndpoint(
                mailbox, exchange, handoff.canonical_bytes, HEX,
                threading.get_ident(), id(threading.current_thread()), channel,
            )
            endpoints.append(endpoint)
            return endpoint.receive_and_settle(
                request, callback=lambda delivery: calls.append(delivery) or "rejected-result", check=check,
            )

        future = pool.submit(worker)
        try:
            with mailbox._condition:
                while mailbox._status == "open":
                    assert mailbox._condition.wait(3)
            with exchange.condition:
                exchange.admission_offer, exchange.admission_state = payload, "offered"
                exchange.admission_kind = "rejection"
            assert checked_before_arm.wait(3)
            with channel._condition:
                assert not channel._queue and channel._requests == {}
                assert exchange.admission_state == "offered" and not calls
                channel._rejection_ready_worker_guarded = True
                channel._condition.notify_all()
            received_payloads = []
            assert channel.service(lambda ready: received_payloads.append(ready.payload) or HEX, timeout=3)
            with exchange.condition:
                while exchange.admission_state == "requested":
                    assert exchange.condition.wait(3)
                assert exchange.admission_state == "received" and exchange.admission_offer is payload
            assert checked_after_receipt.wait(3)
            assert received_payloads == [payload] and len(channel._requests) == 1 and not calls
            assert channel._requests[handoff.episode_id].ack_fields == exchange.admission_ack
            assert mailbox.service(lambda _request: response.payload, check=lambda: None, timeout=3)
            for count, stage in enumerate(("delivery", "callback_started", "callback_finished"), 1):
                assert _wait_event(exchange, count)[0] == stage
                _ack(exchange, count)
            assert future.result(timeout=3) == "rejected-result"
            assert len(calls) == 1 and calls[0].publication_status == "all_rejected"
            assert endpoints[0].status == "settled" and len(channel._requests) == 1
        finally:
            exchange.fail()
            channel.close()
            mailbox.close()


def test_rejected_mailbox_response_without_actual_admission_receipt_never_runs_callback(monkeypatch):
    request, handoff = _request_and_handoff()
    response = _response(_transaction(handoff, state="all_rejected"), request, handoff)
    mailbox = BRSOwnerPublicationMailbox.__new__(BRSOwnerPublicationMailbox)
    exchange, calls = _PrimitiveExchange(None), []
    monkeypatch.setattr(BRSOwnerPublicationMailbox, "request", lambda *_args, **_kwargs: response)
    endpoint = _BRSWorkerTerminalEndpoint(
        mailbox, exchange, handoff.canonical_bytes, HEX,
        threading.get_ident(), id(threading.current_thread()),
    )
    with pytest.raises(RSILearningError, match="admission_receipt_missing"):
        endpoint.receive_and_settle(request, callback=lambda value: calls.append(value), check=lambda: None)
    assert calls == [] and exchange.events == [] and exchange.failed is True
    assert endpoint.status == "unknown"


@pytest.mark.parametrize("guard", [False, None, 1, "True"])
def test_endpoint_never_builds_or_posts_ready_before_original_guard_is_true(monkeypatch, guard):
    import lunar_evolution.rsi_python_brs_terminal_lifecycle as lifecycle

    _request, handoff = _request_and_handoff()
    channel = BRSAdmissionChannel(handoff.run_id, (handoff.episode_id,))
    channel._rejection_ready_worker_guarded = guard
    exchange = _PrimitiveExchange(None)
    exchange.admission_offer, exchange.admission_state = b"original-comparison-bytes", "offered"
    exchange.admission_kind = "rejection"
    endpoint = _BRSWorkerTerminalEndpoint(
        BRSOwnerPublicationMailbox.__new__(BRSOwnerPublicationMailbox), exchange, handoff.canonical_bytes,
        HEX, threading.get_ident(), id(threading.current_thread()), channel,
    )
    monkeypatch.setattr(lifecycle, "build_brs_admission_ready", lambda *_args: pytest.fail("early ready built"))
    if guard is False:
        endpoint._wait_check(lambda: None)
    else:
        with pytest.raises(RSILearningError, match="admission_unavailable"):
            endpoint._wait_check(lambda: None)
    assert channel._requests == {} and exchange.admission_state == "offered"
    assert endpoint._admission_offer is None


def test_wait_check_rechecks_original_channel_identity_after_budget_callback():
    _request, handoff = _request_and_handoff()
    channel = BRSAdmissionChannel(handoff.run_id, (handoff.episode_id,))
    endpoint = _BRSWorkerTerminalEndpoint(
        BRSOwnerPublicationMailbox.__new__(BRSOwnerPublicationMailbox), _PrimitiveExchange(None),
        handoff.canonical_bytes, HEX, threading.get_ident(), id(threading.current_thread()), channel,
    )

    def drift():
        endpoint._admission_channel = BRSAdmissionChannel(handoff.run_id, (handoff.episode_id,))

    with pytest.raises(RSILearningError, match="worker_invalid"):
        endpoint._wait_check(drift)
    assert channel._requests == {}
