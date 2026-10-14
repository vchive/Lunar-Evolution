"""Canonical pure parsing retains refusal and public caller-DTO gates."""

from __future__ import annotations

import json
import socket
import subprocess
from pathlib import Path

import pytest
from test_python_producer_binding import _fixture

from lunar_evolution import producer_python_runtime_tree
from lunar_evolution import python_producer_binding as binding


def _wire(tmp_path):
    manifest, tree, intent, attestation, budget = _fixture(tmp_path)
    return binding.build_python_producer_binding(
        runtime_manifest=manifest, runtime_tree=tree, intent=intent,
        attestation=attestation, deadline_unix=4102444800.0, budget=budget,
    ).to_json()


@pytest.mark.parametrize("text", [False, True], ids=["bytes", "text"])
def test_detached_parser_roundtrip_has_no_filesystem_process_or_network_effects(
    tmp_path, monkeypatch, text,
):
    raw = _wire(tmp_path)
    expected = json.loads(raw)

    def forbidden(*_args, **_kwargs):
        pytest.fail("detached parser must remain pure")

    with monkeypatch.context() as patch:
        for method in ("open", "read_bytes", "write_bytes", "stat", "lstat", "mkdir"):
            patch.setattr(Path, method, forbidden)
        patch.setattr(subprocess, "Popen", forbidden)
        patch.setattr(subprocess, "run", forbidden)
        patch.setattr(socket.socket, "connect", forbidden)
        patch.setattr(socket.socket, "connect_ex", forbidden)
        patch.setattr(socket, "create_connection", forbidden)
        patch.setattr(producer_python_runtime_tree, "verify_python_runtime_tree_manifest", forbidden)
        parsed = binding.parse_python_producer_binding(raw.decode() if text else raw)
        assert parsed.to_json() == raw
        assert parsed.to_dict() == expected
        assert parsed.digest() == expected["binding_sha256"]


@pytest.mark.parametrize("text", [False, True], ids=["bytes", "text"])
@pytest.mark.parametrize("change,code", [
    ("whitespace", "noncanonical_json"),
    ("key_order", "noncanonical_json"),
    ("nested_duplicate", "duplicate_json_key"),
    ("binding_digest", "binding_digest_mismatch"),
    ("bool_budget", "request_budget_invalid"),
    ("bool_deadline", "deadline_invalid"),
])
def test_pure_parser_keeps_exact_byte_and_text_refusals(tmp_path, text, change, code):
    raw = _wire(tmp_path)
    payload = json.loads(raw)
    if change == "whitespace":
        raw = b" " + raw
    elif change == "key_order":
        payload = dict(reversed(tuple(payload.items())))
        raw = json.dumps(payload, separators=(",", ":")).encode()
    elif change == "nested_duplicate":
        digest = payload["runtime_manifest"]["manifest_sha256"]
        raw = raw.replace(
            b'"runtime_manifest":{',
            b'"runtime_manifest":{"manifest_sha256":"' + digest.encode() + b'",', 1,
        )
    else:
        field, value = {
            "binding_digest": ("binding_sha256", "1" * 64),
            "bool_budget": ("request_budget", True),
            "bool_deadline": ("deadline_unix", True),
        }[change]
        payload[field] = value
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(binding.PythonProducerBindingError) as caught:
        binding.parse_python_producer_binding(raw.decode() if text else raw)
    assert caught.value.code == "python_producer_binding_" + code


@pytest.mark.parametrize("method", ["to_dict", "to_json", "digest"])
def test_public_binding_serializers_reject_same_wire_callback_collection_before_callback(
    tmp_path, method,
):
    parsed = binding.parse_python_producer_binding(_wire(tmp_path))
    callbacks = []

    class SameItems(tuple):
        def __iter__(self):
            callbacks.append("iter")
            return super().__iter__()

        def __len__(self):
            callbacks.append("len")
            return super().__len__()

    original = parsed.runtime_manifest.files
    changed = SameItems(original)
    assert tuple.__len__(changed) == len(original)
    assert tuple(tuple.__iter__(changed)) == original
    object.__setattr__(parsed.runtime_manifest, "files", changed)
    with pytest.raises(binding.PythonProducerBindingError):
        getattr(parsed, method)()
    assert callbacks == []
