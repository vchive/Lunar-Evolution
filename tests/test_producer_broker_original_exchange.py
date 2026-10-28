from __future__ import annotations

import base64
import copy
import dataclasses
import json
import os
import time

import pytest
from test_producer_launcher import _intent

import lunar_evolution.producer_broker_ipc as ipc
from lunar_evolution.http_transport import TransportResponse


def _serve(tmp_path, monkeypatch, *, retain=True, status=200, write_failure=False, request_id="req-1"):
    _, intent = _intent(tmp_path)
    calls = []
    response = TransportResponse(status, b"original bounded reply")

    class Handle:
        def wait(self, _timeout):
            return "completed"

        def cancel(self):
            pytest.fail("fixture request completed without cancellation")

        def result(self):
            return response

    class Transport:
        def __init__(self, *, fixed_destination):
            assert fixed_destination is True

        def start(self, admission, payload):
            calls.append((admission, payload))
            return Handle()

    monkeypatch.setattr(ipc, "ControllerHttpTransport", Transport)
    if write_failure:
        def failed_write(*_args, **_kwargs):
            raise ipc.ProducerBrokerIpcError("producer_broker_response_pipe_closed")

        monkeypatch.setattr(ipc, "_write_line", failed_write)
    request_read, request_write = os.pipe()
    response_read, response_write = os.pipe()
    body = b"original request body"
    frame = ipc._encode({
        "protocol": "lunar-producer-broker-ipc-v1", "request_id": request_id,
        "body_base64": base64.b64encode(body).decode("ascii"),
    }, limit=ipc._MAX_FRAME_BYTES)
    deadline_ns = time.monotonic_ns() + 10_000_000_000
    try:
        os.write(request_write, frame)
        os.close(request_write)
        request_write = -1
        observation = ipc.serve_producer_broker(
            request_read, response_write, intent=intent,
            journal_dir=tmp_path / "journal",
            config=ipc.ProducerBrokerConfig("http://fixture", {}), deadline_ns=deadline_ns,
            **({"retain_original_exchange": retain} if retain is not None else {}),
        )
        os.close(response_write)
        response_write = -1
        returned = os.read(response_read, ipc._MAX_RESPONSE_FRAME_BYTES)
    finally:
        for fd in (request_read, request_write, response_read, response_write):
            if fd >= 0:
                os.close(fd)
    return observation, calls, response, deadline_ns, returned


def test_original_exchange_retains_actual_call_material_without_journal_or_export_leak(tmp_path, monkeypatch):
    observed, calls, response, deadline_ns, returned = _serve(tmp_path, monkeypatch)
    pin = ipc._original_broker_exchange_pin(observed)
    assert pin is not None and len(calls) == 1
    assert pin[2] is calls[0][1].body and pin[4] is response.body
    assert pin[3] == id(pin[2]) and pin[5] == id(pin[4])
    assert pin[6:9] == ("req-1", 200, deadline_ns)
    assert observed.snapshot.events[0].request_id == "req-1"
    assert json.loads(returned)["body_base64"] == base64.b64encode(pin[4]).decode("ascii")
    assert "_original_exchange_acquisition" not in dataclasses.asdict(observed)
    journal = observed.journal_path.read_bytes()
    assert pin[2] not in journal and pin[4] not in journal
    assert ipc._original_broker_exchange_pin(observed) == pin


@pytest.mark.parametrize("retain", [False, None])
def test_original_exchange_is_default_off(tmp_path, monkeypatch, retain):
    observed, *_ = _serve(tmp_path, monkeypatch, retain=retain)
    assert observed.complete
    assert ipc._original_broker_exchange_pin(observed) is None


@pytest.mark.parametrize("case", ["copy", "replace", "public", "recovery"])
def test_detached_or_recovered_observation_cannot_recreate_exchange(tmp_path, monkeypatch, case):
    observed, *_ = _serve(tmp_path, monkeypatch)
    if case == "copy":
        detached = copy.copy(observed)
        if getattr(detached, "_original_exchange_acquisition", None) is None:
            assert ipc._original_broker_exchange_pin(detached) is None
        else:
            with pytest.raises(ipc.ProducerBrokerIpcError, match="exchange_changed"):
                ipc._original_broker_exchange_pin(detached)
        return
    if case == "replace":
        detached = dataclasses.replace(observed)
    elif case == "public":
        detached = ipc.ProducerBrokerObservation(**{
            field.name: getattr(observed, field.name) for field in dataclasses.fields(observed)
        })
    else:
        detached = ipc.recover_producer_broker_observation(
            observed.journal_path, identity=observed.journal_identity,
            deadline_ns=time.monotonic_ns() + 2_000_000_000,
            expected_journal_sha256=observed.journal_sha256,
            expected_journal_bytes=observed.journal_bytes,
            expected_journal_file_identity=observed.journal_file_identity,
        )
    assert ipc._original_broker_exchange_pin(detached) is None


def test_private_acquisition_cannot_be_constructed_or_copied(tmp_path, monkeypatch):
    observed, *_ = _serve(tmp_path, monkeypatch)
    acquired = ipc._original_broker_exchange_pin(observed)[0]
    for operation in (ipc._ProducerBrokerExchangeAcquisition, lambda: copy.copy(acquired),
                      lambda: copy.deepcopy(acquired)):
        with pytest.raises(ipc.ProducerBrokerIpcError):
            operation()


@pytest.mark.parametrize("field", ["snapshot", "journal_identity", "journal_path"])
def test_same_value_replacement_of_original_objects_refuses(tmp_path, monkeypatch, field):
    observed, *_ = _serve(tmp_path, monkeypatch)
    value = getattr(observed, field)
    replacement = type(value)(str(value)) if field == "journal_path" else dataclasses.replace(value)
    assert replacement == value and replacement is not value
    object.__setattr__(observed, field, replacement)
    with pytest.raises(ipc.ProducerBrokerIpcError, match="exchange_changed"):
        ipc._original_broker_exchange_pin(observed)


def test_helper_code_drift_refuses_retained_exchange(tmp_path, monkeypatch):
    observed, *_ = _serve(tmp_path, monkeypatch)
    monkeypatch.setattr(ipc, "_body", lambda *_args, **_kwargs: b"substituted")
    with pytest.raises(ipc.ProducerBrokerIpcError, match="exchange_changed"):
        ipc._original_broker_exchange_pin(observed)


@pytest.mark.parametrize("changes", [
    {"write_failure": True}, {"status": 500}, {"request_id": "req-2"},
])
def test_only_original_successful_req1_delivered_response_can_be_retained(tmp_path, monkeypatch, changes):
    observed, *_ = _serve(tmp_path, monkeypatch, **changes)
    assert ipc._original_broker_exchange_pin(observed) is None
