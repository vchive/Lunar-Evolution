"""Opt-in transaction precommit seam keeps all legacy publication gates intact."""

from __future__ import annotations

import pytest
from test_producer_bundle_transaction_control import _call, _fixture, _prefix

from lunar_evolution.producer_bundle_transaction import NativeProducerBundleTransactionError


@pytest.mark.parametrize("flag, hook", [(True, None), (False, lambda _journal: None), (1, None)])
def test_lineage_precommit_requires_explicit_paired_configuration(tmp_path, flag, hook):
    fixture = _fixture(tmp_path)
    context = fixture[0]
    prefix = _prefix(context)
    with pytest.raises(NativeProducerBundleTransactionError, match="multi_episode_configuration_invalid"):
        _call(fixture, None, producer_multi_episode_publication=flag, lineage_precommit=hook)
    assert _prefix(context) == prefix


def test_opt_in_precommit_refusal_preserves_staging_without_commit(tmp_path):
    fixture = _fixture(tmp_path)
    context, _strategy, _drafts, _plan, journal_id = fixture
    prefix = _prefix(context)
    observed = []

    def refuse(journal):
        observed.append(journal)
        raise NativeProducerBundleTransactionError("lineage_test_stale_cas")

    with pytest.raises(NativeProducerBundleTransactionError, match="lineage_test_stale_cas"):
        _call(fixture, None, producer_multi_episode_publication=True, lineage_precommit=refuse)
    assert len(observed) == 1
    assert observed[0].state == "publishing"
    assert _prefix(context) == prefix
    batch = context.workspace / "evolution" / "producer-batches" / journal_id
    assert (batch / "manifest.json").exists()
    assert not (batch / "terminal.json").exists()


def test_default_transaction_does_not_require_or_call_lineage_precommit(tmp_path):
    fixture = _fixture(tmp_path)
    result = _call(fixture, None)
    assert result.publication_status == "published"
