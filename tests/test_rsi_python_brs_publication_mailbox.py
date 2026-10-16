"""Pure one-shot publication transport; no publication or execution authority."""

from __future__ import annotations

import hashlib
import json
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest

from lunar_evolution import producer_bundle_transaction
from lunar_evolution.python_producer_admission_handoff import (
    PYTHON_PRODUCER_ADMISSION_HANDOFF_FILE_PIN_PROTOCOL,
    PythonProducerAdmissionHandoffFilePin,
)
from lunar_evolution.rsi_python_brs_handoff import BRSSelectedChildHandoff
from lunar_evolution.rsi_python_brs_publication_mailbox import (
    MAX_BRS_PUBLICATION_MESSAGE_BYTES,
    BRSOwnerPublicationMailbox,
    BRSOwnerPublicationRequest,
    BRSOwnerPublicationResponse,
    RSIPythonBRSPublicationMailboxError,
    build_brs_owner_publication_request,
    build_brs_owner_publication_response,
)
from lunar_evolution.rsi_store import RSILedger

PREFIX = "rsi_python_brs_publication_mailbox_"
Error = RSIPythonBRSPublicationMailboxError


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _handoff():
    return BRSSelectedChildHandoff(
        run_id="mailbox-run", wave=0, ordinal=0,
        episode_id="mailbox-run-practice-0-0", request_sha256="1" * 64,
        root_snapshot_sha256="2" * 64, selection_sha256="3" * 64,
        controller_id="controller-fixture", ledger_id="ledger-fixture",
        workspace_id="workspace-fixture", sidecar_id="sidecar-fixture",
        owner_thread_id=threading.get_ident(), head_sha256="4" * 64,
        state_sha256="5" * 64, source_sha256="6" * 64,
        policy_sha256="7" * 64, execution_control_sha256="8" * 64,
        max_workers=1, lease_nonce="A" * 32,
    )


def _file_pin(handoff):
    # Inert canonical metadata only: parsing this does not create or observe a file.
    wire = {
        "run_id": handoff.run_id, "journal_id": "mailbox-journal",
        "parent_task_id": "parent", "task_id": "child",
        "handoff_sha256": "9" * 64, "raw_sha256": "a" * 64,
        "raw_size": 1024, "file_device": 1, "file_inode": 2,
        "file_mode": 0o600, "file_nlink": 1, "file_mtime_ns": 3,
        "file_ctime_ns": 4, "parent_device": 1, "parent_inode": 5,
        "schema_version": "1", "protocol": PYTHON_PRODUCER_ADMISSION_HANDOFF_FILE_PIN_PROTOCOL,
    }
    wire["pin_sha256"] = hashlib.sha256(_json(wire)).hexdigest()
    return PythonProducerAdmissionHandoffFilePin.from_dict(wire).to_dict()


def _wire(handoff, *, head=None, state=None):
    receipt = "b" * 64
    return {
        "native_plan_sha256": "a" * 64,
        "expected_head_sha256": handoff.head_sha256 if head is None else head,
        "expected_state_sha256": handoff.state_sha256 if state is None else state,
        "native_execution_receipt_sha256": receipt,
        "output": {
            "process_terminal_sha256": "c" * 64, "output_capture_sha256": "d" * 64,
            "envelope_bytes_sha256": "e" * 64, "execution_receipt_sha256": receipt,
            "admission_plan_sha256": "f" * 64, "request_coverage": "brokered_requests_only",
        },
        "python_handoff_file_pin": _file_pin(handoff),
    }


def _ready(handoff, **kwargs):
    return build_brs_owner_publication_request(handoff, _json(_wire(handoff, **kwargs)))


def _watchdog(callback=None):
    deadline = time.monotonic() + 10

    def check():
        if time.monotonic() >= deadline:
            raise AssertionError("mailbox fixture watchdog expired")
        if callback is not None:
            callback()

    return check


def _until(predicate):
    deadline = time.monotonic() + 5
    while not predicate():
        if time.monotonic() >= deadline:
            pytest.fail("mailbox fixture did not reach expected observation")
        threading.Event().wait(0.001)


@contextmanager
def _bound(*, handoff=None, **kwargs):
    selected = _handoff() if handoff is None else handoff
    with ThreadPoolExecutor(max_workers=1) as pool:
        worker = pool.submit(threading.get_ident).result(timeout=5)
        box = BRSOwnerPublicationMailbox(selected, worker_thread=worker, **kwargs)
        try:
            yield SimpleNamespace(handoff=selected, box=box, pool=pool, worker=worker)
        finally:
            box.close()


def _submit(value, request=None, *, check=None):
    ready = _ready(value.handoff) if request is None else request
    return value.pool.submit(value.box.request, ready, check=_watchdog(check))


@pytest.fixture(autouse=True)
def no_process_ledger_or_publication(monkeypatch, tmp_path):
    def forbidden(*_args, **_kwargs):
        pytest.fail("pure mailbox reached process, ledger or native publication")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(RSILedger, "__init__", forbidden)
    monkeypatch.setattr(producer_bundle_transaction, "run_native_producer_bundle_publication_transaction", forbidden)
    yield
    assert list(tmp_path.iterdir()) == []


def test_builders_bind_exact_handoff_and_canonical_native_evidence_bytes():
    handoff = _handoff()
    request = _ready(handoff)
    assert type(request) is BRSOwnerPublicationRequest
    assert (request.run_id, request.episode_id, request.handoff_sha256) == (
        handoff.run_id, handoff.episode_id, handoff.sha256,
    )
    assert json.loads(request.payload) == _wire(handoff)
    response = build_brs_owner_publication_response(request, b'{"publication_status":"published"}')
    assert type(response) is BRSOwnerPublicationResponse
    assert (response.run_id, response.episode_id, response.handoff_sha256, response.request_sha256) == (
        request.run_id, request.episode_id, request.handoff_sha256, request.request_sha256,
    )
    assert request.request_sha256 != response.response_sha256
    assert replace(request) == request and replace(response) == response


@pytest.mark.parametrize("changed", ["native_plan", "head", "state", "receipt", "terminal", "capture", "envelope", "admission", "coverage", "receipt-link", "pin-run", "extra"])
def test_request_builder_refuses_missing_or_inconsistent_original_evidence(changed):
    handoff = _handoff()
    wire = _wire(handoff)
    if changed in {"native_plan", "head", "state", "receipt"}:
        key = {"native_plan": "native_plan_sha256", "head": "expected_head_sha256", "state": "expected_state_sha256", "receipt": "native_execution_receipt_sha256"}[changed]
        wire[key] = "0" * 64
    elif changed in {"terminal", "capture", "envelope", "admission"}:
        key = {"terminal": "process_terminal_sha256", "capture": "output_capture_sha256", "envelope": "envelope_bytes_sha256", "admission": "admission_plan_sha256"}[changed]
        wire["output"][key] = "0" * 64
    elif changed == "coverage":
        wire["output"]["request_coverage"] = "producer_declaration_only"
    elif changed == "receipt-link":
        wire["output"]["execution_receipt_sha256"] = "a" * 64
    elif changed == "pin-run":
        other = replace(handoff, run_id="other-run", episode_id="other-run-practice-0-0")
        wire["python_handoff_file_pin"] = _file_pin(other)
    else:
        wire["drafts"] = []
    with pytest.raises(Error, match=PREFIX):
        build_brs_owner_publication_request(handoff, _json(wire))


@pytest.mark.parametrize("raw", [b"{}\n", b"[]", b'{"a":1,"a":2}', b'{"a":NaN}', b"\xff", b'{"a": 1}', "{}", bytearray(b"{}")])
def test_response_transport_accepts_only_canonical_bounded_dictionary_bytes(raw):
    with pytest.raises(Error, match=PREFIX):
        build_brs_owner_publication_response(_ready(_handoff()), raw)


def test_payload_limit_and_depth_refuse_without_observing_caller_objects():
    request = _ready(_handoff())
    oversized = b'{"data":"' + b"x" * MAX_BRS_PUBLICATION_MESSAGE_BYTES + b'"}'
    with pytest.raises(Error, match=PREFIX):
        build_brs_owner_publication_response(request, oversized)
    nested = None
    for _ in range(50):
        nested = [nested]
    with pytest.raises(Error, match=PREFIX):
        build_brs_owner_publication_response(request, _json({"nested": nested}))

    class CallbackTrap:
        def __getattribute__(self, _name):
            pytest.fail("transport observed callback-bearing payload")

    with pytest.raises(Error, match=PREFIX):
        build_brs_owner_publication_response(request, CallbackTrap())


@pytest.mark.parametrize("worker", [0, -1, True, "worker", None])
def test_constructor_refuses_invalid_worker_identity(worker):
    with pytest.raises(Error, match=PREFIX):
        BRSOwnerPublicationMailbox(_handoff(), worker_thread=worker)


def test_constructor_and_service_require_original_owner_thread():
    handoff = _handoff()
    with ThreadPoolExecutor(max_workers=1) as pool, pytest.raises(Error, match=PREFIX):
        pool.submit(BRSOwnerPublicationMailbox, handoff, worker_thread=threading.get_ident()).result(timeout=5)
    with pytest.raises(Error, match=PREFIX):
        BRSOwnerPublicationMailbox(handoff, worker_thread=threading.get_ident())
    with _bound() as value:
        with pytest.raises(Error, match=PREFIX):
            value.pool.submit(value.box.service, lambda _request: b"{}", check=lambda: None).result(timeout=5)
        assert value.box.status == "open"


@pytest.mark.parametrize("explicit", [False, True])
def test_exact_owner_capture_delivers_once_and_all_callbacks_run_outside_condition(explicit):
    pins = {"expected_head_sha256": "a" * 64, "expected_state_sha256": "b" * 64} if explicit else {}
    with _bound(**pins) as value:
        checks = []

        def outside(label):
            assert not value.box._condition._is_owned()
            checks.append((label, threading.get_ident()))

        request = _ready(value.handoff, head=pins.get("expected_head_sha256"), state=pins.get("expected_state_sha256"))
        future = _submit(value, request, check=lambda: outside("worker"))
        _until(lambda: value.box.status == "queued")

        def handler(observed):
            outside("handler")
            assert observed is not request and observed == request
            assert value.box.status == "inflight"
            return b'{"publication_status":"published"}'

        assert value.box.service(handler, check=lambda: outside("owner")) is True
        response = future.result(timeout=5)
        assert response == build_brs_owner_publication_response(request, b'{"publication_status":"published"}')
        assert value.box.status == "delivered"
        assert any(label == "worker" and thread == value.worker for label, thread in checks)
        assert all(thread == threading.get_ident() for label, thread in checks if label != "worker")
        with pytest.raises(Error, match=PREFIX):
            _submit(value, request).result(timeout=5)
        called = []
        assert value.box.service(lambda _request: called.append(True), check=lambda: None, timeout=0) is False
        assert called == []


@pytest.mark.parametrize("missing", ["expected_head_sha256", "expected_state_sha256"])
def test_explicit_capture_requires_both_original_owner_pins(missing):
    pins = {"expected_head_sha256": "a" * 64, "expected_state_sha256": "b" * 64}
    pins.pop(missing)
    with ThreadPoolExecutor(max_workers=1) as pool:
        worker = pool.submit(threading.get_ident).result(timeout=5)
        with pytest.raises(Error, match=PREFIX):
            BRSOwnerPublicationMailbox(_handoff(), worker_thread=worker, **pins)


@pytest.mark.parametrize("changed", ["head", "state", "handoff"])
def test_worker_cannot_refresh_or_replace_captured_owner_identity(changed):
    with _bound() as value:
        if changed == "handoff":
            request = _ready(replace(value.handoff, lease_nonce="B" * 32))
        else:
            request = _ready(value.handoff, **{changed: "a" * 64})
        with pytest.raises(Error, match=PREFIX):
            _submit(value, request).result(timeout=5)


def test_owner_and_foreign_worker_requests_refuse_before_guard_callbacks():
    with _bound() as value:
        request = _ready(value.handoff)
        called = []
        with pytest.raises(Error, match=PREFIX):
            value.box.request(request, check=lambda: called.append("owner"))
        with ThreadPoolExecutor(max_workers=1) as other, pytest.raises(Error, match=PREFIX):
            other.submit(value.box.request, request, check=lambda: called.append("foreign")).result(timeout=5)
        assert called == [] and value.box.status == "open"


def test_constructor_and_queue_detach_caller_held_frozen_values():
    with _bound() as value:
        request = _ready(value.handoff)
        original = replace(request)
        object.__setattr__(value.handoff, "head_sha256", "a" * 64)
        future = _submit(value, request)
        _until(lambda: value.box.status == "queued")
        object.__setattr__(request, "payload", b"{}")
        seen = []

        def handler(observed):
            seen.append(observed)
            assert observed == original
            return b"{}"

        assert value.box.service(handler, check=lambda: None)
        assert future.result(timeout=5).request_sha256 == original.request_sha256
        assert seen[0] is not request


def test_handler_cannot_mutate_delivery_identity_or_leak_its_exception_to_worker():
    with _bound() as value:
        future = _submit(value)
        _until(lambda: value.box.status == "queued")

        def handler(request):
            object.__setattr__(request, "handoff_sha256", "a" * 64)
            return b"{}"

        with pytest.raises(Error, match=PREFIX):
            value.box.service(handler, check=lambda: None)
        with pytest.raises(Error, match=PREFIX):
            future.result(timeout=5)
        assert value.box.status == "abandoned"
        with pytest.raises(Error, match=PREFIX):
            _submit(value).result(timeout=5)


def test_private_handler_failure_is_sanitized_and_cannot_reenter_after_queue_consumption():
    with _bound() as value:
        future = _submit(value)
        _until(lambda: value.box.status == "queued")

        def handler(_request):
            raise RuntimeError("private producer path / secret detail")

        with pytest.raises((RuntimeError, Error)):
            value.box.service(handler, check=lambda: None)
        with pytest.raises(Error, match=PREFIX) as caught:
            future.result(timeout=5)
        assert "private producer" not in str(caught.value)
        assert "secret detail" not in str(caught.value)
        assert value.box.status == "abandoned"
        with pytest.raises(Error, match=PREFIX):
            _submit(value).result(timeout=5)


def test_handler_reentrant_service_refuses_without_duplicate_handler_execution():
    with _bound() as value:
        future = _submit(value)
        _until(lambda: value.box.status == "queued")
        calls = []

        def handler(_request):
            calls.append("outer")
            with pytest.raises(Error, match=PREFIX):
                value.box.service(lambda _ready: calls.append("nested"), check=lambda: None)
            return b"{}"

        assert value.box.service(handler, check=lambda: None)
        assert future.result(timeout=5).payload == b"{}" and calls == ["outer"]


class _Cancelled(Exception):
    pass


def test_worker_cancellation_after_queue_wakes_and_burns_original_request():
    with _bound() as value:
        cancel = threading.Event()

        def check():
            if cancel.is_set():
                raise _Cancelled("fixture cancellation")

        future = _submit(value, check=check)
        _until(lambda: value.box.status == "queued")
        cancel.set()
        with pytest.raises(_Cancelled):
            future.result(timeout=5)
        assert value.box.status == "abandoned"
        with pytest.raises(Error, match=PREFIX):
            _submit(value).result(timeout=5)
        calls = []
        assert value.box.service(lambda _request: calls.append(True), check=lambda: None, timeout=0) is False
        assert calls == []


@pytest.mark.parametrize("stop", ["cancel", "close"])
def test_inflight_result_with_lost_ack_stays_unknown_and_never_delivers_or_retries(stop):
    with _bound() as value:
        cancel = threading.Event()

        def check():
            if cancel.is_set():
                raise _Cancelled("fixture cancellation")

        future = _submit(value, check=check)
        _until(lambda: value.box.status == "queued")
        calls = []

        def handler(_request):
            calls.append("one-native-transaction-placeholder")
            if stop == "cancel":
                cancel.set()
                with pytest.raises(_Cancelled):
                    future.result(timeout=5)
            else:
                with ThreadPoolExecutor(max_workers=1) as closer:
                    closer.submit(value.box.close).result(timeout=5)
                with pytest.raises(Error, match=PREFIX):
                    future.result(timeout=5)
            return b'{"publication_status":"published"}'

        with pytest.raises(Error, match=PREFIX + "delivery_unknown$"):
            value.box.service(handler, check=lambda: None)
        assert calls == ["one-native-transaction-placeholder"]
        assert value.box.status in {"abandoned", "closed"}
        with pytest.raises(Error, match=PREFIX):
            _submit(value).result(timeout=5)


def test_close_wakes_queued_worker_and_remains_idempotent_without_handler():
    with _bound() as value:
        future = _submit(value)
        _until(lambda: value.box.status == "queued")
        value.box.close()
        value.box.close()
        with pytest.raises(Error, match=PREFIX):
            future.result(timeout=5)
        assert value.box.status in {"closed", "abandoned"}
        called = []
        assert value.box.service(lambda _request: called.append(True), check=lambda: None, timeout=0) is False
        assert called == []


def test_owner_guard_observing_cancelled_worker_cannot_then_invoke_handler():
    with _bound() as value:
        cancel = threading.Event()

        def worker_check():
            if cancel.is_set():
                raise _Cancelled("fixture cancellation")

        future = _submit(value, check=worker_check)
        _until(lambda: value.box.status == "queued")
        calls = []

        def owner_check():
            assert not value.box._condition._is_owned()
            cancel.set()
            with pytest.raises(_Cancelled):
                future.result(timeout=5)

        with pytest.raises(Error, match=PREFIX + "delivery_unknown$"):
            value.box.service(lambda _request: calls.append("handler"), check=owner_check)
        assert calls == [] and value.box.status == "abandoned"


def test_owner_response_created_but_worker_check_refusal_cannot_undo_or_retry_handler():
    with _bound() as value:
        blocked = threading.Event()
        release = threading.Event()

        def worker_check():
            assert not value.box._condition._is_owned()
            if value.box.status == "queued" and not blocked.is_set():
                blocked.set()
                assert release.wait(5)
                raise _Cancelled("post-response cancellation")

        future = _submit(value, check=worker_check)
        assert blocked.wait(5)
        calls = []
        assert value.box.service(lambda _request: calls.append("transaction") or b"{}", check=lambda: None)
        try:
            assert value.box.status == "delivered" and not future.done()
        finally:
            release.set()
        with pytest.raises(_Cancelled):
            future.result(timeout=5)
        assert calls == ["transaction"] and value.box.status == "abandoned"
        with pytest.raises(Error, match=PREFIX):
            _submit(value).result(timeout=5)


def test_close_after_owner_response_before_worker_acceptance_refuses_delivery():
    with _bound() as value:
        blocked = threading.Event()
        release = threading.Event()

        def worker_check():
            assert not value.box._condition._is_owned()
            if value.box.status == "queued" and not blocked.is_set():
                blocked.set()
                assert release.wait(5)

        future = _submit(value, check=worker_check)
        assert blocked.wait(5)
        assert value.box.service(lambda _request: b"{}", check=lambda: None)
        try:
            assert value.box.status == "delivered" and not future.done()
            value.box.close()
        finally:
            release.set()
        with pytest.raises(Error, match=PREFIX):
            future.result(timeout=5)


def test_close_after_actual_worker_acceptance_preserves_history_without_retry():
    with _bound() as value:
        future = _submit(value)
        _until(lambda: value.box.status == "queued")
        assert value.box.service(lambda _request: b"{}", check=lambda: None)
        accepted = future.result(timeout=5)
        value.box.close()
        value.box.close()
        assert value.box.status == "delivered" and accepted.payload == b"{}"
        with pytest.raises(Error, match=PREFIX):
            _submit(value).result(timeout=5)


@pytest.mark.parametrize("field", ["run_id", "episode_id", "handoff_sha256", "payload", "request_sha256"])
def test_missing_request_slot_is_a_fixed_refusal(field):
    request = _ready(_handoff())
    object.__delattr__(request, field)
    with pytest.raises(Error, match=PREFIX):
        build_brs_owner_publication_response(request, b"{}")


@pytest.mark.parametrize("field", ["run_id", "source_sha256", "owner_thread_id", "max_workers"])
def test_malformed_handoff_refuses_without_caller_callbacks(field):
    handoff = _handoff()
    payload = _json(_wire(handoff))
    calls = []

    class CallbackTrap:
        def __eq__(self, _other):
            calls.append("eq")
            raise AssertionError("handoff equality callback")

        def __hash__(self):
            calls.append("hash")
            raise AssertionError("handoff hash callback")

        def __str__(self):
            calls.append("str")
            raise AssertionError("handoff string callback")

    object.__setattr__(handoff, field, CallbackTrap())
    with pytest.raises(Error, match=PREFIX):
        build_brs_owner_publication_request(handoff, payload)
    assert calls == []


def test_missing_handoff_slot_is_a_fixed_refusal():
    handoff = _handoff()
    payload = _json(_wire(handoff))
    object.__delattr__(handoff, "source_sha256")
    with pytest.raises(Error, match=PREFIX):
        build_brs_owner_publication_request(handoff, payload)


def test_distinct_request_response_domains_bind_original_nonce_and_bytes():
    handoff = _handoff()
    original = _ready(handoff)
    other = _ready(replace(handoff, lease_nonce="B" * 32))
    assert original.payload == other.payload
    assert original.request_sha256 != other.request_sha256
    first = build_brs_owner_publication_response(original, b"{}")
    second = build_brs_owner_publication_response(other, b"{}")
    assert first.response_sha256 != second.response_sha256
    with pytest.raises(Error, match=PREFIX):
        replace(first, request_sha256=other.request_sha256)
    with pytest.raises(Error, match=PREFIX):
        replace(original, handoff_sha256=other.handoff_sha256)


@pytest.mark.parametrize("stage", ["before-handler", "after-handler"])
def test_owner_guard_failure_wakes_worker_with_fixed_refusal_without_repair(stage):
    with _bound() as value:
        future = _submit(value)
        _until(lambda: value.box.status == "queued")
        guard_calls = []
        handler_calls = []

        def guard():
            assert not value.box._condition._is_owned()
            guard_calls.append(True)
            if len(guard_calls) == (1 if stage == "before-handler" else 2):
                raise _Cancelled("private original owner detail")

        with pytest.raises(_Cancelled):
            value.box.service(lambda _request: handler_calls.append(True) or b"{}", check=guard)
        with pytest.raises(Error, match=PREFIX) as caught:
            future.result(timeout=5)
        assert "private original" not in str(caught.value)
        assert handler_calls == ([] if stage == "before-handler" else [True])
        assert value.box.status == "abandoned"
        with pytest.raises(Error, match=PREFIX):
            _submit(value).result(timeout=5)


@pytest.mark.parametrize("payload", [b"[]", b"{}\n", b'{"a":1,"a":2}', None])
def test_invalid_handler_response_burns_request_without_worker_delivery(payload):
    with _bound() as value:
        future = _submit(value)
        _until(lambda: value.box.status == "queued")
        with pytest.raises(Error, match=PREFIX):
            value.box.service(lambda _request: payload, check=lambda: None)
        with pytest.raises(Error, match=PREFIX):
            future.result(timeout=5)
        assert value.box.status == "abandoned"


class _CallbackTimeout(int):
    def __float__(self):
        pytest.fail("timeout subclass float callback")

    def __lt__(self, _other):
        pytest.fail("timeout subclass comparison callback")

    def __gt__(self, _other):
        pytest.fail("timeout subclass comparison callback")


@pytest.mark.parametrize("timeout", [-1, 61, 10**1000, float("nan"), float("inf"), True, None, _CallbackTimeout(1)])
def test_invalid_service_timeout_never_calls_handler_or_guard(timeout):
    with _bound() as value:
        calls = []
        with pytest.raises(Error, match=PREFIX + "timeout_invalid$"):
            value.box.service(lambda _request: calls.append("handler"), check=lambda: calls.append("guard"), timeout=timeout)
        assert calls == [] and value.box.status == "open"


def test_idle_zero_timeout_and_open_close_create_no_request_or_handler_effects():
    with _bound() as value:
        calls = []
        assert value.box.service(lambda _request: calls.append("handler"), check=lambda: calls.append("guard"), timeout=0) is False
        assert calls == [] and value.box.status == "open"
        value.box.close()
        value.box.close()
        assert value.box.status == "closed"


def test_initial_worker_guard_cannot_recursively_submit_or_run_nested_check():
    with _bound() as value:
        calls = []
        request = _ready(value.handoff)

        def check():
            assert not value.box._condition._is_owned()
            if value.box.status == "open":
                calls.append("initial")
                with pytest.raises(Error, match=PREFIX):
                    value.box.request(request, check=lambda: calls.append("nested-check"))

        future = _submit(value, request, check=check)
        _until(lambda: value.box.status == "queued")
        assert value.box.service(lambda _request: b"{}", check=lambda: None)
        assert future.result(timeout=5).payload == b"{}"
        assert calls == ["initial"]


def test_owner_initial_guard_close_wakes_worker_before_handler_can_run():
    with _bound() as value:
        future = _submit(value)
        _until(lambda: value.box.status == "queued")
        calls = []

        def check():
            assert not value.box._condition._is_owned()
            value.box.close()

        with pytest.raises(Error, match=PREFIX + "delivery_unknown$"):
            value.box.service(lambda _request: calls.append("handler"), check=check)
        with pytest.raises(Error, match=PREFIX):
            future.result(timeout=5)
        assert calls == [] and value.box.status == "abandoned"


def test_initial_worker_check_failure_before_enqueue_leaves_original_empty_mailbox():
    with _bound() as value:
        def stop_before_queue():
            assert not value.box._condition._is_owned()
            raise _Cancelled("initial non-enqueued check")

        with pytest.raises(_Cancelled):
            _submit(value, check=stop_before_queue).result(timeout=5)
        assert value.box.status == "open"
        future = _submit(value)
        _until(lambda: value.box.status == "queued")
        assert value.box.service(lambda _request: b"{}", check=lambda: None)
        assert future.result(timeout=5).payload == b"{}"
