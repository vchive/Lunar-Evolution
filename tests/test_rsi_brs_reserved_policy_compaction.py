"""Complete original BRS identities fit the existing record limits."""
from __future__ import annotations

import re

import pytest
from test_rsi_brs_reserved_inputs import _setup, inert_only  # noqa: F401

from lunar_evolution import rsi_brs_publication_lineage as publication
from lunar_evolution import rsi_brs_rejection_owner as rejection
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.rsi_learning import RSILearningError


def test_large_finite_subgraphs_use_canonical_digests_and_keep_the_original_gates():
    policy = publication._policy()
    assert policy == publication._policy()
    assert policy["production_admission"] is False and policy["online_publication"] is False
    assert policy["max_workers"] == 1 and policy["max_batches"] == 8
    for name in ("rejection_c1", "owner_result_delivery", "retained_native_reader", "module_sources", "methods"):
        assert re.fullmatch(r"[0-9a-f]{64}", policy["dependencies"][name])
    assert len(canonical_json(policy)) < 24 * 1024


def test_compaction_keeps_the_live_rejection_code_drift_gate(monkeypatch):
    publication._policy()
    function = rejection.retain_rejected_terminal
    monkeypatch.setattr(function, "__code__", function.__code__.replace(co_name="foreign"))
    with pytest.raises(RSILearningError, match="policy_drift"):
        publication._policy()


def test_natural_original_run_and_reserved_checkpoint_fit_unchanged_caps(tmp_path, monkeypatch):
    value = _setup(tmp_path, monkeypatch)
    run = value.ledger.get_run(value.binding.run_id)
    checkpoint = value.ledger.controller_checkpoint(value.binding.run_id)
    assert run is not None and checkpoint is not None
    policy = run.payload["producer_brs_checkpoint_policy"]
    assert run.payload["fingerprints"]["run_fingerprint"]["solver_settings"][
        "producer_brs_checkpoint_policy"] == policy
    run_size = len(canonical_json(run.payload, maximum=128 * 1024))
    checkpoint_size = len(canonical_json(checkpoint[1], maximum=128 * 1024))
    print({"policy_bytes": len(canonical_json(policy)), "original_run_payload_bytes": run_size,
           "reserved_checkpoint_bytes": checkpoint_size, "cap_bytes": 128 * 1024})
    assert len(value.state["intents"]) == 2
    assert all(value.ledger.get_episode(key) is None for key in value.ids)
