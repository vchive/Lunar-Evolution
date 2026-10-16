"""Lineage configuration refuses before native process or publication effects."""

from __future__ import annotations

import subprocess

import pytest
from test_native_trusted_scheduler import _call_context, _context

from lunar_evolution import native_trusted_scheduler
from lunar_evolution.native_trusted_scheduler import NativeTrustedSchedulerError


@pytest.fixture(autouse=True)
def _no_effects(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("invalid lineage configuration reached a side effect")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(native_trusted_scheduler, "run_native_trusted_attempt", forbidden)
    monkeypatch.setattr(native_trusted_scheduler, "run_native_producer_bundle_publication_transaction", forbidden)


@pytest.mark.parametrize("flag", [None, 0, 1, "true", [], {}])
def test_nonboolean_mode_refuses_before_launch(tmp_path, flag):
    context = _context(tmp_path)
    with pytest.raises(NativeTrustedSchedulerError, match="multi_episode_configuration_invalid"):
        _call_context(context, producer_multi_episode_publication=flag)
    assert not (tmp_path / "evolution").exists()


@pytest.mark.parametrize("flag,owner", [(True, None), (False, object()), (True, object())])
def test_missing_original_join_or_unpaired_owner_refuses_before_launch(tmp_path, flag, owner):
    context = _context(tmp_path)
    with pytest.raises(NativeTrustedSchedulerError, match="multi_episode_configuration_invalid"):
        _call_context(context, producer_multi_episode_publication=flag, lineage_owner=owner)
    assert not (tmp_path / "evolution").exists()
