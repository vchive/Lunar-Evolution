"""Focused provider-free F04 cross-pin/result projection tests."""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

from lunar_evolution import static_python_input_result as contract


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _vector() -> tuple[dict, dict[str, object]]:
    pins = {name: _sha(name) for name in (
        "startup_sha256", "build_closure_sha256", "binding_sha256", "launch_intent_sha256",
        "manifest_sha256", "report_sha256", "request_sha256", "memory_sha256",
    )}
    payload = {
        "schema": contract.INPUT_RESULT_SCHEMA,
        **pins,
        "input_report_schema": contract.INPUT_REPORT_SCHEMA,
        "request_size": 32,
        "memory_size": 24,
        "computed": 285,
        "claims": {name: False for name in contract._CLAIMS},
    }
    return payload, {
        "expected_startup_sha256": pins["startup_sha256"],
        "expected_build_closure_sha256": pins["build_closure_sha256"],
        "expected_binding_sha256": pins["binding_sha256"],
        "expected_launch_intent_sha256": pins["launch_intent_sha256"],
        "expected_manifest_sha256": pins["manifest_sha256"],
        "expected_report_sha256": pins["report_sha256"],
        "expected_request_sha256": pins["request_sha256"],
        "expected_memory_sha256": pins["memory_sha256"],
        "expected_request_size": 32,
        "expected_memory_size": 24,
    }


def _parse(payload: dict, pins: dict[str, object]):
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return contract.parse_static_python_input_result(raw, **pins)


def test_valid_projection_is_canonical_and_immutable():
    payload, pins = _vector()
    result = _parse(payload, pins)
    assert result.to_dict() == payload
    assert result.computed == 285
    assert result.request_size == 32
    with pytest.raises(AttributeError):
        result.computed = 1  # type: ignore[misc]
    assert not any(hasattr(result, name) for name in ("request", "memory", "result", "accepted"))


@pytest.mark.parametrize("field,reason", [
    ("startup_sha256", "cross_pin"), ("report_sha256", "cross_pin"),
    ("input_report_schema", "report_schema"), ("request_size", "input_size"),
    ("computed", "computed"),
])
def test_cross_pin_and_shape_mutations_refuse(field: str, reason: str):
    payload, pins = _vector()
    payload[field] = _sha("drift") if field.endswith("sha256") else (
        "other-report" if field == "input_report_schema" else 1
    )
    with pytest.raises(contract.StaticPythonInputResultError) as caught:
        _parse(payload, pins)
    assert caught.value.reason == "static_python_input_result_" + reason


def test_true_claim_and_duplicate_or_noncanonical_bytes_refuse():
    payload, pins = _vector()
    payload["claims"]["production_admission"] = True
    with pytest.raises(contract.StaticPythonInputResultError) as caught:
        _parse(payload, pins)
    assert caught.value.reason.endswith("claims")

    payload, _ = _vector()
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    duplicate = (canonical[:-1] + ',"schema":"' + contract.INPUT_RESULT_SCHEMA + '"}').encode()
    with pytest.raises(contract.StaticPythonInputResultError) as caught:
        contract.parse_static_python_input_result(duplicate, **pins)
    assert caught.value.reason.endswith("duplicate_key")

    with pytest.raises(contract.StaticPythonInputResultError) as caught:
        contract.parse_static_python_input_result(json.dumps(payload, indent=2).encode(), **pins)
    assert caught.value.reason.endswith("canonical")


def test_bounds_pins_and_external_effects_are_refused_or_absent(monkeypatch):
    payload, pins = _vector()
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()))
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()))
    assert _parse(payload, pins).manifest_sha256 == pins["expected_manifest_sha256"]
    with pytest.raises(contract.StaticPythonInputResultError) as caught:
        contract.parse_static_python_input_result(b"{}", **pins)
    assert caught.value.reason.endswith("schema")

    oversized = b"{" + b"x" * contract.MAX_INPUT_RESULT_BYTES
    with pytest.raises(contract.StaticPythonInputResultError) as caught:
        contract.parse_static_python_input_result(oversized, **pins)
    assert caught.value.reason.endswith("raw")


def test_error_does_not_retain_malformed_input():
    payload, pins = _vector()
    payload["claims"] = {"raw-secret": "never"}
    with pytest.raises(contract.StaticPythonInputResultError) as caught:
        _parse(copy.deepcopy(payload), pins)
    assert str(caught.value) == "static_python_input_result_claims"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize("side", ["request", "memory"])
@pytest.mark.parametrize("value", [True, False, 1.0, "1"])
def test_size_must_be_an_exact_integer_even_when_equal_to_pin(side, value):
    payload, pins = _vector()
    payload[side + "_size"] = value
    pins["expected_" + side + "_size"] = 1
    reason = "json" if type(value) is float else "input_size"
    with pytest.raises(contract.StaticPythonInputResultError, match="_" + reason + "$"):
        _parse(payload, pins)


def test_json_failure_has_no_retained_decode_context():
    _, pins = _vector()
    with pytest.raises(contract.StaticPythonInputResultError) as caught:
        contract.parse_static_python_input_result(b'{"private":"never",', **pins)
    assert str(caught.value) == "static_python_input_result_json"
    assert caught.value.__cause__ is caught.value.__context__ is None
