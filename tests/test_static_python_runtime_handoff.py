"""Focused provider-free F05 runtime/post-execution handoff tests."""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

from lunar_evolution import static_python_runtime_handoff as contract


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _vector() -> tuple[dict, dict[str, object]]:
    pins = {name: _sha(name) for name in (
        "startup_sha256", "input_result_sha256", "terminal_sha256", "handoff_sha256",
        "binding_sha256", "launch_intent_sha256", "result_sha256",
        "publication_intent_sha256",
    )}
    payload = {
        "schema": contract.RUNTIME_HANDOFF_SCHEMA,
        **pins,
        "request_budget": 8,
        "request_count": 3,
        "wall_timeout_seconds": 30.0,
        "deadline_unix": 2_000_000_000.0,
        "terminal_state": "completed",
        "cleanup_status": "already_exited",
        "publication_state": "prepared",
        "claims": {name: False for name in contract._CLAIMS},
    }
    return payload, {
        "expected_startup_sha256": pins["startup_sha256"],
        "expected_input_result_sha256": pins["input_result_sha256"],
        "expected_terminal_sha256": pins["terminal_sha256"],
        "expected_handoff_sha256": pins["handoff_sha256"],
        "expected_binding_sha256": pins["binding_sha256"],
        "expected_launch_intent_sha256": pins["launch_intent_sha256"],
        "expected_result_sha256": pins["result_sha256"],
        "expected_publication_intent_sha256": pins["publication_intent_sha256"],
        "expected_request_budget": 8,
        "expected_request_count": 3,
        "expected_wall_timeout_seconds": 30.0,
        "expected_deadline_unix": 2_000_000_000.0,
    }


def _parse(payload: dict, pins: dict[str, object]):
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return contract.parse_static_python_runtime_handoff(raw, **pins)


def test_valid_runtime_handoff_is_canonical_and_immutable():
    payload, pins = _vector()
    result = _parse(payload, pins)
    assert result.to_dict() == payload
    assert result.terminal_state == "completed"
    assert result.publication_state == "prepared"
    assert result.request_count == 3
    with pytest.raises(AttributeError):
        result.request_count = 4  # type: ignore[misc]
    assert not any(hasattr(result, name) for name in ("process", "result", "evaluator", "owner"))


@pytest.mark.parametrize("field,reason", [
    ("startup_sha256", "cross_pin"),
    ("input_result_sha256", "cross_pin"),
    ("terminal_sha256", "cross_pin"),
    ("publication_intent_sha256", "cross_pin"),
    ("request_count", "budget"),
    ("terminal_state", "state"),
])
def test_cross_pin_budget_and_terminal_mutations_refuse(field: str, reason: str):
    payload, pins = _vector()
    payload[field] = _sha("drift") if field.endswith("sha256") else (
        99 if field == "request_count" else "not-a-state"
    )
    with pytest.raises(contract.StaticPythonRuntimeHandoffError) as caught:
        _parse(payload, pins)
    assert caught.value.reason == "static_python_runtime_handoff_" + reason


def test_claims_publication_and_cleanup_mutations_refuse():
    payload, pins = _vector()
    payload["claims"]["publication_ready"] = True
    with pytest.raises(contract.StaticPythonRuntimeHandoffError) as caught:
        _parse(payload, pins)
    assert caught.value.reason.endswith("claims")

    payload, pins = _vector()
    payload["terminal_state"] = "failed"
    with pytest.raises(contract.StaticPythonRuntimeHandoffError) as caught:
        _parse(payload, pins)
    assert caught.value.reason.endswith("publication_state")

    payload, pins = _vector()
    payload["cleanup_status"] = "leaked"
    with pytest.raises(contract.StaticPythonRuntimeHandoffError) as caught:
        _parse(payload, pins)
    assert caught.value.reason.endswith("cleanup")


def test_duplicate_noncanonical_bounds_and_side_effects_refuse(monkeypatch):
    payload, pins = _vector()
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()))
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()))
    assert _parse(payload, pins).handoff_sha256 == pins["expected_handoff_sha256"]

    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    duplicate = (canonical[:-1] + ',"schema":"' + contract.RUNTIME_HANDOFF_SCHEMA + '"}').encode()
    with pytest.raises(contract.StaticPythonRuntimeHandoffError) as caught:
        contract.parse_static_python_runtime_handoff(duplicate, **pins)
    assert caught.value.reason.endswith("duplicate_key")

    with pytest.raises(contract.StaticPythonRuntimeHandoffError) as caught:
        contract.parse_static_python_runtime_handoff(json.dumps(payload, indent=2).encode(), **pins)
    assert caught.value.reason.endswith("canonical")

    oversized = b"{" + b"x" * contract.MAX_RUNTIME_HANDOFF_BYTES
    with pytest.raises(contract.StaticPythonRuntimeHandoffError) as caught:
        contract.parse_static_python_runtime_handoff(oversized, **pins)
    assert caught.value.reason.endswith("raw")


def test_error_does_not_retain_malformed_input():
    payload, pins = _vector()
    payload["claims"] = {"secret": "never"}
    with pytest.raises(contract.StaticPythonRuntimeHandoffError) as caught:
        _parse(copy.deepcopy(payload), pins)
    assert str(caught.value) == "static_python_runtime_handoff_claims"
    assert caught.value.__cause__ is None
