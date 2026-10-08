"""Feature191 binding checks over inert, provider-free runtime material."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_producer_python_runtime import _build, _tree
from test_producer_python_runtime_tree import build as build_tree

from lunar_evolution import producer_python_runtime_tree
from lunar_evolution import python_producer_binding as binding
from lunar_evolution.producer_launcher import (
    build_producer_launch_attestation,
    build_producer_launch_intent,
)
from lunar_evolution.rsi_budget import RSIRunBudget

DIGEST = "a" * 64


def _fixture(tmp_path: Path):
    source = _tree(tmp_path)
    manifest = _build(source)
    tree = build_tree(type("Tree", (), {"original": manifest, "target": source.target})())
    runtime_root = source.roots["runtime"]
    intent = build_producer_launch_intent(
        producer_root=runtime_root, launch_id="launch-1", journal_id="journal-1", run_id="run-1",
        parent_task_id="parent-1", task_id="task-1", contract_sha256=DIGEST,
        evaluator_kind="local", evaluator_fingerprint=DIGEST, runner_fingerprint=DIGEST,
        generator_fingerprint=DIGEST, dependency_sha256=DIGEST, environment_sha256=DIGEST,
        producer_id="fixture", producer_fingerprint=DIGEST, executable_relative="bin/python",
        argv=("bin/python", "-I", "-S", "-B", "fixture"), working_directory="work",
        output_directory="output", request_timeout_seconds=5, max_requests=3,
        output_max_bytes=4096, wall_timeout_seconds=10,
    )
    # The generic launch builder uses a producer-root label.  Feature191 binds
    # that label to the manifest's runtime root before release.
    intent = replace(intent, executable_root_label="runtime", intent_sha256=None)
    intent = replace(intent, intent_sha256=intent.digest())
    attestation = build_producer_launch_attestation(intent, "nonce-1")
    budget = RSIRunBudget.create({"deadline_unix": 4102444800.0, "max_solver_invocations": 3})
    return manifest, tree, intent, attestation, budget


def test_binding_roundtrip_rechecks_runtime_and_durable_deadline(tmp_path: Path) -> None:
    manifest, tree, intent, attestation, budget = _fixture(tmp_path)
    item = binding.build_python_producer_binding(
        runtime_manifest=manifest, runtime_tree=tree, intent=intent, attestation=attestation,
        deadline_unix=4102444800.0, budget=budget, fixture_case="baseline",
    )
    assert item.binding_sha256 == item.digest()
    assert item.runtime_manifest_sha256 == manifest.manifest_sha256
    assert item.runtime_tree_sha256 == tree.tree_sha256
    assert binding.parse_python_producer_binding(item.to_json()) == item


def test_binding_refuses_deadline_refresh_and_runtime_tree_drift(tmp_path: Path) -> None:
    manifest, tree, intent, attestation, budget = _fixture(tmp_path)
    with pytest.raises(binding.PythonProducerBindingError, match="budget_deadline_mismatch"):
        binding.build_python_producer_binding(
            runtime_manifest=manifest, runtime_tree=tree, intent=intent, attestation=attestation,
            deadline_unix=4102444801.0, budget=budget,
        )
    # A tampered frozen DTO is caught by the reparse gate, before lifecycle effects.
    object.__setattr__(tree, "tree_sha256", "b" * 64)
    with pytest.raises(binding.PythonProducerBindingError):
        binding.build_python_producer_binding(
            runtime_manifest=manifest, runtime_tree=tree, intent=intent, attestation=attestation,
            deadline_unix=4102444800.0, budget=budget,
        )


def test_binding_rejects_duplicate_or_unknown_wire_fields(tmp_path: Path) -> None:
    manifest, tree, intent, attestation, budget = _fixture(tmp_path)
    item = binding.build_python_producer_binding(
        runtime_manifest=manifest, runtime_tree=tree, intent=intent, attestation=attestation,
        deadline_unix=4102444800.0, budget=budget,
    )
    raw = item.to_json()
    with pytest.raises(binding.PythonProducerBindingError, match="duplicate_json_key"):
        binding.parse_python_producer_binding(raw[:-1] + b',"fixture_case":"baseline"}')
    payload = json.loads(raw)
    payload["unknown"] = True
    with pytest.raises(binding.PythonProducerBindingError, match="schema_invalid"):
        binding.parse_python_producer_binding(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def test_binding_does_not_execute_runtime_or_filesystem_on_parse(tmp_path: Path, monkeypatch) -> None:
    manifest, tree, intent, attestation, budget = _fixture(tmp_path)
    item = binding.build_python_producer_binding(
        runtime_manifest=manifest, runtime_tree=tree, intent=intent, attestation=attestation,
        deadline_unix=4102444800.0, budget=budget,
    )
    monkeypatch.setattr(producer_python_runtime_tree, "verify_python_runtime_tree_manifest", lambda *_a, **_k: pytest.fail("filesystem verification"))
    assert binding.parse_python_producer_binding(item.to_json()).binding_sha256 == item.binding_sha256


def test_binding_requires_digest_and_validates_mapping_budget_checkpoint(tmp_path: Path) -> None:
    manifest, tree, intent, attestation, budget = _fixture(tmp_path)
    item = binding.build_python_producer_binding(
        runtime_manifest=manifest, runtime_tree=tree, intent=intent, attestation=attestation,
        deadline_unix=4102444800.0, budget=budget,
    )
    payload = item.to_dict()
    payload["binding_sha256"] = None
    with pytest.raises(binding.PythonProducerBindingError, match="binding_digest_invalid"):
        binding.parse_python_producer_binding(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    payload["binding_sha256"] = "0" * 64
    with pytest.raises(binding.PythonProducerBindingError, match="binding_digest_invalid"):
        binding.parse_python_producer_binding(json.dumps(payload, sort_keys=True, separators=(",", ":")))

    mapping = budget.to_dict()
    assert binding.build_python_producer_binding(
        runtime_manifest=manifest, runtime_tree=tree, intent=intent, attestation=attestation,
        deadline_unix=4102444800.0, budget=mapping,
    ) == item
    mapping["consumed"]["solver_invocations"] = 1
    with pytest.raises(binding.PythonProducerBindingError, match="budget_invalid|budget_checkpoint"):
        binding.build_python_producer_binding(
            runtime_manifest=manifest, runtime_tree=tree, intent=intent, attestation=attestation,
            deadline_unix=4102444800.0, budget=mapping,
        )
