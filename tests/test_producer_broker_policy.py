"""The broker's host-only destination and headers are fixed at construction."""

from __future__ import annotations

import pytest

from lunar_evolution.producer_broker_ipc import ProducerBrokerConfig


def test_broker_config_copies_and_freezes_host_headers():
    headers = {"Authorization": "initial-secret"}
    config = ProducerBrokerConfig("http://127.0.0.1:1", headers)
    headers["Authorization"] = "changed-secret"
    headers["X-Extra"] = "unexpected"
    assert dict(config.headers) == {"Authorization": "initial-secret"}
    with pytest.raises(TypeError):
        config.headers["Authorization"] = "changed-secret"


def test_broker_config_rejects_endpoint_or_header_authority_override():
    with pytest.raises(ValueError, match="^controller_http_endpoint_invalid$"):
        ProducerBrokerConfig("http://user:pass@127.0.0.1:1", {"Authorization": "secret"})
    with pytest.raises(ValueError, match="^controller_http_headers_invalid$"):
        ProducerBrokerConfig("http://127.0.0.1:1", {"Host": "other.example"})
