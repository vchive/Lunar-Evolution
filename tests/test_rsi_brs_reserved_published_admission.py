"""Real one-worker transports; owner/root proof is explicitly doubled here.

These component tests create no publication, admission record or controller root.
Natural reserved-driver acceptance remains a separate gate.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from test_rsi_python_brs_result_delivery import _request_and_handoff, _response, _transaction
from test_rsi_python_brs_terminal_lifecycle import _ack, _wait_event

from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.rsi_brs_publication_lineage import _BRSLineageCheckpointOwner
from lunar_evolution.rsi_controller import RSILearningController
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_python_brs_admission import BRSAdmissionChannel
from lunar_evolution.rsi_python_brs_publication_mailbox import BRSOwnerPublicationMailbox
from lunar_evolution.rsi_python_brs_terminal_lifecycle import (
    BRSOwnerTerminalLifecycle,
    _BRSWorkerTerminalEndpoint,
    _PrimitiveExchange,
)

HEX = "a" * 64


def _component_session(monkeypatch, handoff, mailbox, exchange, channel, endpoint):
    """Double only original-owner/root checks; retain the real channel service."""
    observations = []
    owner = SimpleNamespace(
        _reserved_prefix=object(), _phase="terminal", _poisoned=False,
        _payload=canonical_json({"python_admission_refs": {handoff.episode_id: {"record_sha256": HEX}}}),
        _request=SimpleNamespace(episode_id=handoff.episode_id), _run_id=handoff.run_id,
        _plan=SimpleNamespace(journal_id="journal", to_dict=lambda: {"plan": "retained"}),
        _prepared=SimpleNamespace(to_dict=lambda: {"journal": "retained"}),
        _controller=object(), _channel=channel,
    )

    def record(run, episode, journal, *, expected_record_sha256):
        assert (run, episode, journal, expected_record_sha256) == (
            handoff.run_id, handoff.episode_id, "journal", HEX,
        )
        observations.append("retained-record-read")
        return SimpleNamespace(to_dict=lambda: {"admission_anchor": {"anchor_sha256": "b" * 64}})

    owner._ledger = SimpleNamespace(read_only_observations=lambda: nullcontext(), python_admission_record=record)
    session = BRSOwnerTerminalLifecycle.__new__(BRSOwnerTerminalLifecycle)
    session._owner, session._mailbox, session._exchange, session._endpoint = owner, mailbox, exchange, endpoint
    session._started, session._poisoned, session._result, session._published_admission = True, False, None, None
    monkeypatch.setattr(BRSOwnerTerminalLifecycle, "_fixed", lambda actual: observations.append("session-read"))
    monkeypatch.setattr(_BRSLineageCheckpointOwner, "_check_owner", lambda actual: observations.append("owner-read"))

    def empty(actual):
        assert actual is owner and channel._requests == {} and not channel._queue
        observations.append("original-empty-channel")

    monkeypatch.setattr(_BRSLineageCheckpointOwner, "_before_channel", empty)

    def existing(controller, actual, ready):
        assert controller is owner._controller and actual is owner
        assert not channel._condition._is_owned() and not exchange.condition._is_owned()
        assert ready.run_id == handoff.run_id and ready.episode_id == handoff.episode_id
        observations.append(("existing-admission-read", ready.payload, ready.request_sha256))
        return HEX

    monkeypatch.setattr(RSILearningController, "_python_admission_existing_published_brs_ready", existing)
    return session, owner, observations


def test_reserved_success_acks_existing_admission_on_original_worker_before_delivery(monkeypatch):
    request, handoff = _request_and_handoff()
    response = _response(_transaction(handoff), request, handoff)
    channel = BRSAdmissionChannel(handoff.run_id, (handoff.episode_id,))
    # This selects an inert transport binding only; no owner acceptance is claimed.
    channel._handoff_mode = True
    channel._selected_episode_id, channel._selected_handoff_sha256 = handoff.episode_id, handoff.sha256
    exchange, endpoints, callbacks = _PrimitiveExchange(time.monotonic() + 10), [], []
    received = threading.Event()

    def check():
        if exchange.admission_state == "received":
            received.set()

    with ThreadPoolExecutor(max_workers=1) as pool:
        worker_id = pool.submit(threading.get_ident).result(timeout=3)
        mailbox = BRSOwnerPublicationMailbox(handoff, worker_thread=worker_id)

        def worker():
            endpoint = _BRSWorkerTerminalEndpoint(mailbox, exchange, handoff.canonical_bytes, HEX,
                threading.get_ident(), id(threading.current_thread()), channel, _reserved_success=True)
            endpoints.append(endpoint)
            return endpoint.receive_and_settle(request, callback=lambda value: callbacks.append(value) or "saved",
                                               check=check)

        future = pool.submit(worker)
        try:
            with mailbox._condition:
                assert mailbox._condition.wait_for(lambda: mailbox._status == "queued", timeout=3)
            endpoint = endpoints[0]
            assert len(endpoint._scope) == 9 and endpoint._scope[-1] is True
            session, owner, observations = _component_session(monkeypatch, handoff, mailbox, exchange, channel, endpoint)
            assert session._service_published_admission(timeout=3) == HEX
            assert received.wait(3)
            reads = [item for item in observations if type(item) is tuple]
            assert len(reads) == 2 and reads[0] == reads[1]
            assert exchange.admission_kind == "published" and exchange.admission_state == "received"
            assert len(channel._requests) == 1 and not callbacks
            assert channel._requests[handoff.episode_id].ack_fields == exchange.admission_ack
            assert session._assert_published_admission() == HEX
            with pytest.raises(RSILearningError, match="published_admission_unavailable"):
                session._service_published_admission(timeout=0)
            assert mailbox.service(lambda _request: response.payload, check=lambda: None, timeout=3)
            for count, stage in enumerate(("delivery", "callback_started", "callback_finished"), 1):
                assert _wait_event(exchange, count)[0] == stage
                _ack(exchange, count)
            assert future.result(timeout=3) == "saved"
            assert callbacks[0].publication_status == "published" and len(callbacks) == 1
            assert endpoint.status == "settled" and owner._poisoned is session._poisoned is False
            assert len(channel._requests) == 1
        finally:
            exchange.fail()
            channel.close()
            mailbox.close()


@pytest.mark.parametrize("fault", ["no_offer", "rejection_kind"])
def test_reserved_success_never_calls_callback_without_its_published_receipt(monkeypatch, fault):
    request, handoff = _request_and_handoff()
    response = _response(_transaction(handoff), request, handoff)
    exchange, callbacks = _PrimitiveExchange(None), []
    endpoint = _BRSWorkerTerminalEndpoint(BRSOwnerPublicationMailbox.__new__(BRSOwnerPublicationMailbox),
        exchange, handoff.canonical_bytes, HEX, threading.get_ident(), id(threading.current_thread()),
        _reserved_success=True)
    if fault == "rejection_kind":
        exchange.admission_offer, exchange.admission_state, exchange.admission_kind = b"retained", "received", "rejection"
        exchange.admission_ack = (handoff.run_id, handoff.episode_id, HEX, HEX)
        endpoint._admission_offer, endpoint._admission_ack = exchange.admission_offer, exchange.admission_ack
        endpoint._admission_kind = "rejection"
    monkeypatch.setattr(BRSOwnerPublicationMailbox, "request", lambda *_args, **_kwargs: response)
    with pytest.raises(RSILearningError, match="admission_receipt_missing"):
        endpoint.receive_and_settle(request, callback=lambda value: callbacks.append(value), check=lambda: None)
    assert callbacks == [] and exchange.events == [] and exchange.failed is True
    assert endpoint.status == "unknown"


@pytest.mark.parametrize("reserved,guard", [(False, False), (True, True)])
def test_published_offer_never_uses_legacy_or_rejection_channel(monkeypatch, reserved, guard):
    import lunar_evolution.rsi_python_brs_terminal_lifecycle as lifecycle

    _request, handoff = _request_and_handoff()
    channel, exchange = BRSAdmissionChannel(handoff.run_id, (handoff.episode_id,)), _PrimitiveExchange(None)
    channel._rejection_ready_worker_guarded = guard
    exchange.admission_offer, exchange.admission_state, exchange.admission_kind = b"retained", "offered", "published"
    endpoint = _BRSWorkerTerminalEndpoint(BRSOwnerPublicationMailbox.__new__(BRSOwnerPublicationMailbox),
        exchange, handoff.canonical_bytes, HEX, threading.get_ident(), id(threading.current_thread()), channel,
        _reserved_success=reserved)
    monkeypatch.setattr(lifecycle, "build_brs_admission_ready", lambda *_args: pytest.fail("foreign ready built"))
    with pytest.raises(RSILearningError, match="admission_drift"):
        endpoint._wait_check(lambda: None)
    assert channel._requests == {} and exchange.admission_state == "offered"


def test_published_admission_timeout_poison_keeps_original_offer_and_creates_no_ack(monkeypatch):
    _request, handoff = _request_and_handoff()
    channel, exchange = BRSAdmissionChannel(handoff.run_id, (handoff.episode_id,)), _PrimitiveExchange(None)
    mailbox = BRSOwnerPublicationMailbox.__new__(BRSOwnerPublicationMailbox)
    endpoint = _BRSWorkerTerminalEndpoint(mailbox, exchange, handoff.canonical_bytes, HEX,
        threading.get_ident(), id(threading.current_thread()), channel, _reserved_success=True)
    session, owner, observations = _component_session(monkeypatch, handoff, mailbox, exchange, channel, endpoint)
    with pytest.raises(RSILearningError, match="published_admission_missing"):
        session._service_published_admission(timeout=0)
    assert session._published_admission[0] == "offered" and type(exchange.admission_offer) is bytes
    assert session._poisoned is owner._poisoned is exchange.failed is True
    assert channel._requests == {} and exchange.admission_ack is None
    assert len([item for item in observations if type(item) is tuple]) == 1


@pytest.mark.parametrize("fault", ["changed_record", "unknown_reader"])
def test_existing_admission_recheck_failure_wakes_original_worker_without_delivery(monkeypatch, fault):
    request, handoff = _request_and_handoff()
    channel = BRSAdmissionChannel(handoff.run_id, (handoff.episode_id,))
    exchange, endpoints, callbacks = _PrimitiveExchange(time.monotonic() + 10), [], []
    with ThreadPoolExecutor(max_workers=1) as pool:
        worker_id = pool.submit(threading.get_ident).result(timeout=3)
        mailbox = BRSOwnerPublicationMailbox(handoff, worker_thread=worker_id)

        def worker():
            endpoint = _BRSWorkerTerminalEndpoint(mailbox, exchange, handoff.canonical_bytes, HEX,
                threading.get_ident(), id(threading.current_thread()), channel, _reserved_success=True)
            endpoints.append(endpoint)
            return endpoint.receive_and_settle(request, callback=lambda value: callbacks.append(value), check=lambda: None)

        future = pool.submit(worker)
        try:
            with mailbox._condition:
                assert mailbox._condition.wait_for(lambda: mailbox._status == "queued", timeout=3)
            session, owner, _observations = _component_session(
                monkeypatch, handoff, mailbox, exchange, channel, endpoints[0])
            original, calls = RSILearningController._python_admission_existing_published_brs_ready, []

            def changing(*args):
                digest = original(*args)
                calls.append(digest)
                if len(calls) == 2:
                    if fault == "unknown_reader":
                        raise RuntimeError("original admission observation unknown")
                    return "c" * 64
                return digest

            monkeypatch.setattr(RSILearningController, "_python_admission_existing_published_brs_ready", changing)
            expected = RuntimeError if fault == "unknown_reader" else RSILearningError
            with pytest.raises(expected):
                session._service_published_admission(timeout=3)
            with pytest.raises(RSILearningError):
                future.result(timeout=3)
            assert calls == [HEX, HEX] and callbacks == [] and exchange.events == []
            assert session._poisoned is owner._poisoned is exchange.failed is True
            assert session._published_admission[0] == "offered" and exchange.admission_ack is None
            pending = channel._requests[handoff.episode_id]
            assert pending.ack is None and pending.error == "handler_failed"
            assert endpoints[0].status == "unknown"
        finally:
            exchange.fail()
            channel.close()
            mailbox.close()


@pytest.mark.parametrize("flag", [None, 1, "True"])
def test_reserved_endpoint_requires_exact_private_bool(flag):
    _request, handoff = _request_and_handoff()
    with pytest.raises(RSILearningError, match="worker_invalid"):
        _BRSWorkerTerminalEndpoint(BRSOwnerPublicationMailbox.__new__(BRSOwnerPublicationMailbox),
            _PrimitiveExchange(None), handoff.canonical_bytes, HEX, threading.get_ident(),
            id(threading.current_thread()), _reserved_success=flag)
