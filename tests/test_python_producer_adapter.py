from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_python_producer_admission_gate import (
    _chain,
    _installation_inputs,
    _static_binding_fixture,
)

from lunar_evolution.producer_handoff import ProducerResultEnvelope
from lunar_evolution.producer_launcher import build_producer_launch_attestation
from lunar_evolution.python_producer_adapter import (
    PythonProducerAdapterError,
    build_python_producer_adapter_envelope,
    parse_python_producer_adapter_envelope,
    verify_python_producer_adapter_envelope,
)
from lunar_evolution.python_producer_binding import build_python_producer_binding
from lunar_evolution.python_producer_lifecycle import (
    build_python_producer_terminal,
)


def _supported_chain(tmp_path: Path, producer="openevolve"):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "original").mkdir()
    original = _chain(tmp_path / "original")
    _binding, _sidecar, _handoff, terminal, observation, _receipt, _plan, _journal, result, _owner = original
    rebound = tmp_path / "rebound"
    rebound.mkdir(parents=True, exist_ok=True)
    manifest, tree, intent, _attestation, budget = _static_binding_fixture(rebound)
    intent = replace(intent, producer_id=producer, intent_sha256=None)
    intent = replace(intent, intent_sha256=intent.digest())
    attestation = build_producer_launch_attestation(intent, "nonce-1")
    binding = build_python_producer_binding(
        runtime_manifest=manifest, runtime_tree=tree, intent=intent, attestation=attestation,
        deadline_unix=4102444800.0, budget=budget,
    )
    terminal_values = terminal.to_dict()
    terminal_values.update(
        binding_sha256=binding.binding_sha256, run_id=binding.run_id,
        journal_id=binding.intent.journal_id, launch_id=binding.intent.launch_id,
        deadline_unix=binding.deadline_unix, terminal_sha256=None,
        executable_sha256=binding.interpreter.sha256, executable_size=binding.interpreter.size,
        executable_device=binding.interpreter.device, executable_inode=binding.interpreter.inode,
    )
    terminal = build_python_producer_terminal(**terminal_values)
    observation = replace(observation, binding_sha256=binding.binding_sha256, observation_sha256=None)
    observation = replace(observation, observation_sha256=observation.digest())
    result_values = result.to_dict()
    result_values.update(producer_id=producer, producer_run_id=binding.run_id)
    result = ProducerResultEnvelope.from_dict(result_values)
    return binding, terminal, observation, result


@pytest.mark.parametrize("producer", ["openevolve", "shinka"])
def test_adapter_binds_completed_local_evidence_and_round_trips(tmp_path: Path, producer) -> None:
    binding, terminal, observation, result = _supported_chain(tmp_path, producer)
    envelope = build_python_producer_adapter_envelope(
        binding, terminal, observation, result, **_installation_inputs(binding),
    )
    assert parse_python_producer_adapter_envelope(envelope.to_json()) == envelope
    assert envelope.to_dict()["producer_id"] == producer
    assert envelope.to_dict()["adapter_sha256"] == envelope.digest()
    assert verify_python_producer_adapter_envelope(
        binding, envelope.to_json(), **_installation_inputs(binding),
    ) == envelope
    assert envelope.production_admission is False


def test_adapter_rejects_binding_or_terminal_drift(tmp_path: Path) -> None:
    binding, terminal, observation, result = _supported_chain(tmp_path)
    terminal = _terminal(terminal, binding_sha256="f" * 64)
    with pytest.raises(PythonProducerAdapterError, match="binding_drift"):
        build_python_producer_adapter_envelope(
            binding, terminal, observation, result, **_installation_inputs(binding),
        )

    (tmp_path / "unsupported").mkdir()
    unsupported = _chain(tmp_path / "unsupported")
    with pytest.raises(PythonProducerAdapterError, match="producer_identity_drift"):
        build_python_producer_adapter_envelope(
            unsupported[0], unsupported[3], unsupported[4], unsupported[8],
            **_installation_inputs(unsupported[0]),
        )


def _terminal(item, **updates):
    value = replace(item, **updates, terminal_sha256=None)
    return replace(value, terminal_sha256=value.digest())


def _observation(item, **updates):
    value = replace(item, **updates, observation_sha256=None)
    return replace(value, observation_sha256=value.digest())


def _resign(value):
    value.pop("adapter_sha256", None)
    value["adapter_sha256"] = hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    return value


@pytest.mark.parametrize("field,value,reason", [
    ("producer_run_id", "different", "result_run_drift"),
    ("producer_run_id", None, "result_run_drift"),
    ("producer_fingerprint", "f" * 64, "producer_fingerprint_drift"),
    ("contract_sha256", "f" * 64, "contract_drift"),
    ("budget", {"requests": 2}, "result_request_count_drift"),
    ("budget", {"requests": True}, "result_request_count_drift"),
    ("budget", {}, "result_request_count_drift"),
    ("status", "unknown", "result_not_completed"),
    ("status", "failed", "result_not_completed"),
    ("status", "cancelled", "result_not_completed"),
])
def test_adapter_rejects_result_drift(tmp_path, field, value, reason):
    binding, terminal, observation, result = _supported_chain(tmp_path)
    if field == "budget" and (value == {"requests": True} or value == {}):
        # The result parser itself refuses booleans as numeric budget values.
        object.__setattr__(result, field, value)
        reason = "result_invalid"
    else:
        result = replace(result, **{field: value})
    with pytest.raises(PythonProducerAdapterError, match=reason):
        build_python_producer_adapter_envelope(
            binding, terminal, observation, result, **_installation_inputs(binding),
        )


@pytest.mark.parametrize("field,value,reason", [
    ("run_id", "different", "terminal_identity_drift"),
    ("journal_id", "different", "terminal_identity_drift"),
    ("launch_id", "different", "terminal_identity_drift"),
    ("deadline_unix", 4102444801.0, "deadline_drift"),
    ("request_count", 4, "request_budget_exceeded"),
    ("executable_sha256", "f" * 64, "executable_identity_drift"),
    ("executable_size", 900, "executable_identity_drift"),
    ("executable_device", 900, "executable_identity_drift"),
    ("executable_inode", 900, "executable_identity_drift"),
    ("status", "unknown", "terminal_not_completed"),
    ("status", "failed", "terminal_not_completed"),
    ("status", "cancelled", "terminal_not_completed"),
])
def test_adapter_rejects_terminal_drift(tmp_path, field, value, reason):
    binding, terminal, observation, result = _supported_chain(tmp_path)
    terminal = _terminal(terminal, **{field: value})
    with pytest.raises(PythonProducerAdapterError, match=reason):
        build_python_producer_adapter_envelope(
            binding, terminal, observation, result, **_installation_inputs(binding),
        )


@pytest.mark.parametrize("field,value", [
    ("version_major", 4), ("version_minor", 11), ("cache_tag", "cpython-311"),
    ("abi_profile", "cp313-free-threaded"), ("flags", ("-I", "-B")),
    ("argv", ("different.py",)), ("orig_argv", ("different.py",)), ("pycache_absent", False),
])
def test_adapter_rejects_runtime_target_drift(tmp_path, field, value):
    binding, terminal, observation, result = _supported_chain(tmp_path)
    observation = _observation(observation, **{field: value})
    with pytest.raises(PythonProducerAdapterError, match="runtime_target_drift"):
        build_python_producer_adapter_envelope(
            binding, terminal, observation, result, **_installation_inputs(binding),
        )


@pytest.mark.parametrize("mutation,reason", [
    ("result", "nested_invalid"), ("terminal", "nested_invalid"),
    ("observation", "nested_invalid"), ("claim", "unsupported_admission_claim"),
    ("digest_none", "adapter_digest_invalid"), ("digest_zero", "adapter_digest_invalid"),
    ("unknown_field", "schema_invalid"), ("missing_field", "schema_invalid"),
])
def test_adapter_parser_rejects_resigned_invalid_nested_wire(tmp_path, mutation, reason):
    chain = _supported_chain(tmp_path)
    value = build_python_producer_adapter_envelope(*chain, **_installation_inputs(chain[0])).to_dict()
    if mutation in {"result", "terminal", "observation"}:
        value[mutation]["schema_version"] = "invalid"
    elif mutation == "claim":
        value["production_admission"] = True
    elif mutation == "unknown_field":
        value["unknown"] = True
    elif mutation == "missing_field":
        del value["runtime_tree_sha256"]
    _resign(value)
    if mutation.startswith("digest_"):
        value["adapter_sha256"] = None if mutation == "digest_none" else "0" * 64
    with pytest.raises(PythonProducerAdapterError, match=reason):
        parse_python_producer_adapter_envelope(value)


@pytest.mark.parametrize("field", ["binding_sha256", "intent_sha256", "attestation_sha256",
                                   "runtime_manifest_sha256", "runtime_tree_sha256"])
def test_adapter_verify_refuses_resigned_binding_pin_drift(tmp_path, field):
    binding, terminal, observation, result = _supported_chain(tmp_path)
    value = build_python_producer_adapter_envelope(
        binding, terminal, observation, result, **_installation_inputs(binding),
    ).to_dict()
    value[field] = "f" * 64
    _resign(value)
    with pytest.raises(PythonProducerAdapterError, match="binding_drift"):
        verify_python_producer_adapter_envelope(binding, value, **_installation_inputs(binding))


def test_adapter_parser_refuses_stale_nested_dto_and_missing_digest(tmp_path):
    chain = _supported_chain(tmp_path)
    envelope = build_python_producer_adapter_envelope(*chain, **_installation_inputs(chain[0]))
    with pytest.raises(PythonProducerAdapterError, match="adapter_digest_invalid"):
        parse_python_producer_adapter_envelope(replace(envelope, adapter_sha256=None))
    object.__setattr__(envelope.result, "budget", {"requests": -1})
    with pytest.raises(PythonProducerAdapterError, match="result_invalid"):
        parse_python_producer_adapter_envelope(envelope)


def test_adapter_is_callback_free_and_has_no_admission_api(tmp_path, monkeypatch):
    import os
    import subprocess

    import lunar_evolution
    import lunar_evolution.python_producer_adapter as adapter

    chain = _supported_chain(tmp_path)
    for module, name in [(os, "open"), (subprocess, "Popen")]:
        monkeypatch.setattr(module, name, lambda *_a, **_k: pytest.fail("side effect"))
    envelope = build_python_producer_adapter_envelope(*chain, **_installation_inputs(chain[0]))
    assert verify_python_producer_adapter_envelope(chain[0], envelope, **_installation_inputs(chain[0])).production_admission is False
    assert not hasattr(adapter, "admit_python_producer_result")
    assert not hasattr(lunar_evolution, "admit_python_producer_result")

    class Forbidden(dict):
        def items(self):
            pytest.fail("callback mapping inspected")

    with pytest.raises(PythonProducerAdapterError, match="json_invalid"):
        parse_python_producer_adapter_envelope(Forbidden(envelope.to_dict()))
    object.__setattr__(envelope.result, "budget", Forbidden({"requests": 1}))
    with pytest.raises(PythonProducerAdapterError, match="result_invalid"):
        parse_python_producer_adapter_envelope(envelope)


def test_adapter_refuses_duplicate_noncanonical_and_oversize_wire(tmp_path):
    from lunar_evolution.python_producer_adapter import MAX_PYTHON_PRODUCER_ADAPTER_BYTES

    chain = _supported_chain(tmp_path)
    envelope = build_python_producer_adapter_envelope(*chain, **_installation_inputs(chain[0]))
    wire = envelope.to_json()
    for value, code in [
        (wire[:-1] + b',"producer_id":"shinka"}', "duplicate_json_key"),
        (wire + b"\n", "noncanonical_json"),
        (b" " * (MAX_PYTHON_PRODUCER_ADAPTER_BYTES + 1), "record_too_large"),
    ]:
        with pytest.raises(PythonProducerAdapterError, match=code):
            parse_python_producer_adapter_envelope(value)
