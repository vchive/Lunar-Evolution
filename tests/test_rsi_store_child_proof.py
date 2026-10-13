"""Store-side selection of one staged DRS child proof with root retention."""

from __future__ import annotations

import pytest
from test_rsi_producer_launch import _ready

import lunar_evolution.rsi_producer_launch as producer_launch
from lunar_evolution import RSILearningError
from lunar_evolution.python_producer_checkpoint import PythonProducerCheckpointBinding


def _store_ready(tmp_path, monkeypatch):
    # PR89's fixture binding is larger than its conservative staging cap on this
    # host; widen only the local fixture so the store resolver can be exercised.
    monkeypatch.setattr(producer_launch, "MAX_STAGING_BINDING_BYTES", 64 * 1024)
    return _ready(tmp_path, monkeypatch)


def test_store_selects_ready_child_proof_in_one_read_transaction(tmp_path, monkeypatch):
    value, _, _, state, entry = _store_ready(tmp_path, monkeypatch)
    episode_id = state["current_episode_id"]

    root, selected = value.ledger.resolve_python_producer_checkpoint(
        value.binding.run_id, episode_id,
    )
    expected_root = PythonProducerCheckpointBinding.from_dict(
        value.ledger.history(value.binding.run_id)[0].payload["producer_checkpoint_binding"],
    )
    expected_child = PythonProducerCheckpointBinding.from_dict(entry["ready"]["producer_checkpoint"])

    assert root == expected_root
    assert selected == expected_child
    assert selected != root
    assert state["producer_checkpoint_binding"] == root.to_dict()


def test_store_child_selection_requires_the_same_checkpoint_head(tmp_path, monkeypatch):
    value, _, _, state, _ = _store_ready(tmp_path, monkeypatch)
    episode_id = state["current_episode_id"]
    with pytest.raises(RSILearningError, match="checkpoint_conflict"):
        value.ledger.resolve_python_producer_checkpoint(
            value.binding.run_id, episode_id, expected_checkpoint_sha256="a" * 64,
        )


def test_store_child_selection_rejects_non_ready_entry(tmp_path, monkeypatch):
    value, _, _, state, _ = _store_ready(tmp_path, monkeypatch)
    episode_id = state["current_episode_id"]
    malformed = dict(state)
    malformed["producer_episode_staging"] = {
        episode_id: dict(malformed["producer_episode_staging"][episode_id], state="preparing"),
    }
    root = PythonProducerCheckpointBinding.from_dict(state["producer_checkpoint_binding"])
    with pytest.raises(RSILearningError, match="child_proof_not_ready"):
        value.ledger._select_python_producer_checkpoint_tx(
            malformed, run_id=value.binding.run_id, episode_id=episode_id, root=root,
        )
