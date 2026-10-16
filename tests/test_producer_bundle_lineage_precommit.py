"""Opt-in transaction precommit seam keeps all legacy publication gates intact."""

from __future__ import annotations

import pytest
from test_producer_bundle_transaction_control import _call, _fixture, _prefix
from test_rsi_child_execution_flow import _inert_candidate_process

from lunar_evolution import candidate_evaluation, candidate_execution_runner
from lunar_evolution.producer_bundle_transaction import NativeProducerBundleTransactionError


@pytest.fixture(autouse=True)
def _no_processes(monkeypatch):
    import subprocess

    def forbidden(*_args, **_kwargs):
        pytest.fail("lineage tests must not launch processes")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(candidate_execution_runner, "_bounded_process_bytes", _inert_candidate_process)
    monkeypatch.setattr(candidate_evaluation, "_bounded_process_bytes", _inert_candidate_process)


@pytest.mark.parametrize("flag, owner", [(True, None), (False, object()), (1, None)])
def test_lineage_precommit_requires_explicit_paired_configuration(tmp_path, flag, owner):
    fixture = _fixture(tmp_path)
    context = fixture[0]
    prefix = _prefix(context)
    with pytest.raises(NativeProducerBundleTransactionError, match="multi_episode_configuration_invalid"):
        _call(fixture, None, producer_multi_episode_publication=flag, lineage_owner=owner)
    assert _prefix(context) == prefix


def test_naked_callback_never_grants_lineage_authority(tmp_path):
    fixture = _fixture(tmp_path)
    context = fixture[0]
    prefix = _prefix(context)
    called = []
    with pytest.raises(NativeProducerBundleTransactionError, match="multi_episode_configuration_invalid"):
        _call(fixture, None, producer_multi_episode_publication=True, lineage_owner=called.append)
    assert called == []
    assert _prefix(context) == prefix


def test_default_transaction_does_not_require_or_call_lineage_precommit(tmp_path):
    fixture = _fixture(tmp_path)
    result = _call(fixture, None)
    assert result.publication_status == "published"
