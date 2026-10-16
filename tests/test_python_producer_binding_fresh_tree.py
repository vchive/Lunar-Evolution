"""Parser-local tree reuse preserves wire refusals and public caller-DTO gates."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest
from test_python_producer_binding_parser_normalization import _wire

from lunar_evolution import python_producer_binding as binding
from lunar_evolution.producer_launcher import build_producer_launch_attestation


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _resign(payload):
    body = {key: value for key, value in payload.items() if key != "binding_sha256"}
    payload["binding_sha256"] = hashlib.sha256(_canonical(body)).hexdigest()
    return _canonical(payload)


@pytest.mark.parametrize("text", [False, True], ids=["bytes", "text"])
@pytest.mark.parametrize("fixture_case", ["baseline", "loader-negative"])
def test_fresh_tree_binding_keeps_exact_roundtrip_and_public_reconstruction(
    tmp_path, text, fixture_case,
):
    payload = json.loads(_wire(tmp_path))
    payload["fixture_case"] = fixture_case
    payload["deadline_unix"] += 0.125
    raw = _resign(payload)
    parsed = binding.parse_python_producer_binding(raw.decode() if text else raw)
    assert type(parsed) is binding.PythonProducerBinding
    assert parsed.to_json() == raw
    assert parsed.to_dict() == payload
    assert parsed.digest() == payload["binding_sha256"]
    assert replace(parsed) == parsed
    assert parsed.runtime_tree.declared_manifest == parsed.runtime_manifest
    assert parsed.runtime_tree.declared_manifest is not parsed.runtime_manifest


@pytest.mark.parametrize("text", [False, True], ids=["bytes", "text"])
@pytest.mark.parametrize("mutation,code", [
    ("tree_digest_and_budget", "schema_invalid"),
    ("tree_order_and_binding_digest", "schema_invalid"),
    ("tree_capability_and_fixture", "schema_invalid"),
    ("tree_membership", "schema_invalid"),
    ("tree_manifest_and_request", "runtime_tree_manifest_mismatch"),
    ("attestation_and_request", "attestation_intent_mismatch"),
    ("request_output_and_digest", "request_budget_mismatch"),
    ("output_wall_and_digest", "output_budget_mismatch"),
    ("wall_deadline_and_digest", "wall_timeout_mismatch"),
    ("deadline_and_digest", "deadline_wall_timeout_invalid"),
    ("intent_stat_bound_and_request", "intent_shape_invalid"),
    ("interpreter_identity_and_digest", "interpreter_identity_mismatch"),
])
def test_fresh_tree_binding_preserves_multiple_fault_refusal_order(tmp_path, text, mutation, code):
    raw = _wire(tmp_path)
    payload = json.loads(raw)
    if mutation.startswith("tree_"):
        tree = payload["runtime_tree"]
        if mutation == "tree_digest_and_budget":
            tree["tree_sha256"] = "1" * 64
            payload["request_budget"] = True
        elif mutation == "tree_order_and_binding_digest":
            tree["directories"].reverse()
        elif mutation == "tree_capability_and_fixture":
            tree["execution_performed"] = True
            payload["fixture_case"] = "unknown"
        elif mutation == "tree_membership":
            directory = next(item for item in tree["directories"] if item["children"])
            directory["children"].append(directory["children"][0])
        else:
            other = tmp_path / "other"
            other.mkdir()
            payload["runtime_manifest"] = json.loads(_wire(other))["runtime_manifest"]
            payload["request_budget"] += 1
    elif mutation == "attestation_and_request":
        other = tmp_path / "other"
        other.mkdir()
        payload["attestation"] = json.loads(_wire(other))["attestation"]
        payload["request_budget"] += 1
    elif mutation == "request_output_and_digest":
        payload["request_budget"] += 1
        payload["output_max_bytes"] += 1
    elif mutation == "output_wall_and_digest":
        payload["output_max_bytes"] += 1
        payload["wall_timeout_seconds"] += 1
    elif mutation == "wall_deadline_and_digest":
        payload["wall_timeout_seconds"] += 1
        payload["deadline_unix"] = 1
    elif mutation == "deadline_and_digest":
        payload["deadline_unix"] = 1
    else:
        original = binding.parse_python_producer_binding(raw)
        field = ("executable_device" if mutation == "intent_stat_bound_and_request"
                 else "executable_inode")
        value = 2**64 if field == "executable_device" else original.intent.executable_inode + 1
        intent = replace(original.intent, **{field: value}, intent_sha256=None)
        intent = replace(intent, intent_sha256=intent.digest())
        payload["intent"] = intent.to_dict()
        payload["attestation"] = build_producer_launch_attestation(intent, "other-once").to_dict()
        if mutation == "intent_stat_bound_and_request":
            payload["request_budget"] += 1
    # Keep the outer digest wrong as a later, simultaneous fault. Earlier
    # tree/launch/join refusals must still win before the final digest gate.
    payload["binding_sha256"] = "2" * 64
    raw = _canonical(payload)
    with pytest.raises(binding.PythonProducerBindingError) as caught:
        binding.parse_python_producer_binding(raw.decode() if text else raw)
    assert caught.value.code == "python_producer_binding_" + code


@pytest.mark.parametrize("gate", ["constructor", "post_init", "to_dict", "to_json", "digest"])
@pytest.mark.parametrize("field", ["directories", "declared_files", "tree_digest"])
def test_public_binding_gates_revalidate_mutated_tree_before_callback(tmp_path, gate, field):
    parsed = binding.parse_python_producer_binding(_wire(tmp_path))
    callbacks = []

    class SameItems(tuple):
        def __iter__(self):
            callbacks.append("iter")
            return super().__iter__()

        def __len__(self):
            callbacks.append("len")
            return super().__len__()

    tree = parsed.runtime_tree
    if field == "tree_digest":
        object.__setattr__(tree, "tree_sha256", "1" * 64)
    else:
        subject, name = (tree, "directories") if field == "directories" else (
            tree.declared_manifest, "files",
        )
        original = getattr(subject, name)
        changed = SameItems(original)
        assert tuple(tuple.__iter__(changed)) == original
        object.__setattr__(subject, name, changed)
    with pytest.raises(binding.PythonProducerBindingError) as caught:
        if gate == "constructor":
            replace(parsed)
        else:
            getattr(parsed, "__post_init__" if gate == "post_init" else gate)()
    assert caught.value.code == "python_producer_binding_runtime_tree_invalid"
    assert callbacks == []


@pytest.mark.parametrize("text", [False, True], ids=["bytes", "text"])
def test_fresh_tree_binding_keeps_raw_capacity_refusal(text):
    raw = b" " * (binding.MAX_PYTHON_PRODUCER_BINDING_BYTES + 1)
    with pytest.raises(binding.PythonProducerBindingError) as caught:
        binding.parse_python_producer_binding(raw.decode() if text else raw)
    assert caught.value.code == "python_producer_binding_binding_too_large"


@pytest.mark.parametrize("text", [False, True], ids=["bytes", "text"])
def test_fresh_tree_binding_rejects_deep_array_outside_schema(text):
    # Decoder recursion behavior differs across supported Python versions. This
    # array is outside the binding schema even when the decoder accepts it; its
    # nesting is not a portable parser depth limit.
    raw = b"[" * 2000 + b"0" + b"]" * 2000
    with pytest.raises(binding.PythonProducerBindingError) as caught:
        binding.parse_python_producer_binding(raw.decode() if text else raw)
    assert caught.value.code in {
        "python_producer_binding_json_invalid",
        "python_producer_binding_schema_invalid",
    }


@pytest.mark.parametrize("text", [False, True], ids=["bytes", "text"])
def test_fresh_tree_binding_maps_decoder_recursion_error_to_json_invalid(monkeypatch, text):
    raw, calls = b"{}", []
    failure = RecursionError("inert decoder refusal")

    def exhausted(value, **_kwargs):
        calls.append(value)
        raise failure

    # json is a shared module: restore its decoder before pytest emits reports.
    with monkeypatch.context() as decoder_patch:
        decoder_patch.setattr(binding.json, "loads", exhausted)
        with pytest.raises(binding.PythonProducerBindingError) as caught:
            binding.parse_python_producer_binding(raw.decode() if text else raw)
    assert calls == [raw.decode()]
    assert caught.value.code == "python_producer_binding_json_invalid"
    assert caught.value.__cause__ is failure
