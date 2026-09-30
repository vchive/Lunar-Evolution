from __future__ import annotations

import os
import time

import pytest

from lunar_evolution.producer_broker_ipc import (
    ProducerBrokerIpcError,
    brokered_producer_post,
)


@pytest.mark.parametrize("value", ["-1", "0", "not-a-fd"])
def test_target_sdk_rejects_non_pipe_descriptor_handoff(monkeypatch, value):
    monkeypatch.setenv("LUNAR_PRODUCER_RESPONSE_FD", value)
    monkeypatch.setenv("LUNAR_PRODUCER_REQUEST_FD", value)
    with pytest.raises(ProducerBrokerIpcError) as failure:
        brokered_producer_post(
            "request-001", b"payload", deadline_ns=time.monotonic_ns() + 1_000_000_000,
        )
    assert failure.value.code == "producer_broker_pipe_invalid"


def test_target_sdk_rejects_regular_file_as_request_channel(tmp_path, monkeypatch):
    path = tmp_path / "channel"
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        monkeypatch.setenv("LUNAR_PRODUCER_RESPONSE_FD", str(fd))
        monkeypatch.setenv("LUNAR_PRODUCER_REQUEST_FD", str(fd))
        with pytest.raises(ProducerBrokerIpcError) as failure:
            brokered_producer_post(
                "request-001", b"payload", deadline_ns=time.monotonic_ns() + 1_000_000_000,
            )
        assert failure.value.code == "producer_broker_pipe_invalid"
    finally:
        os.close(fd)


def test_target_sdk_rejects_same_pipe_for_request_and_response(monkeypatch):
    read_fd, write_fd = os.pipe()
    try:
        monkeypatch.setenv("LUNAR_PRODUCER_RESPONSE_FD", str(read_fd))
        monkeypatch.setenv("LUNAR_PRODUCER_REQUEST_FD", str(read_fd))
        with pytest.raises(ProducerBrokerIpcError) as failure:
            brokered_producer_post(
                "request-001", b"payload", deadline_ns=time.monotonic_ns() + 1_000_000_000,
            )
        assert failure.value.code == "producer_broker_pipe_invalid"
    finally:
        os.close(read_fd)
        os.close(write_fd)
