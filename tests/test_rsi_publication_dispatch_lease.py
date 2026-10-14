"""The original dispatch stack must bind a lease before the first owner capture."""

from __future__ import annotations

import sqlite3
import subprocess

import pytest
from test_rsi_child_execution_flow import _successful_fixture
from test_rsi_multi_episode_policy import _controller
from test_rsi_producer_staging_controller import _run

from lunar_evolution import RSILearningError
from lunar_evolution.rsi_gateway import SolverRequest
from lunar_evolution.rsi_native_scheduler import NativeRSISchedulerProvider
from lunar_evolution.rsi_producer_staging_capsule import materialize_ready


@pytest.fixture(autouse=True)
def _no_subprocess(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("dispatch lease regression must never launch a subprocess")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)


@pytest.mark.parametrize("replacement", ["missing", "equal_tuple"])
def test_original_lease_cannot_change_before_first_owner_capture(tmp_path, monkeypatch, replacement):
    value, _old, _supplier, observation = _successful_fixture(tmp_path, monkeypatch)
    controller, _supplier = _controller(value, publication=True)
    observation.controller = controller
    original_join = NativeRSISchedulerProvider._python_publication_join
    seen = []

    def changed_join(provider, request, plan, inputs):
        assert provider._python_admission_controller is controller
        lease = controller._producer_publication_dispatch
        context = controller._python_admission_flow_local.active
        assert type(lease) is tuple and context.publication_dispatch_lease is lease
        assert getattr(controller._python_admission_flow_local, "publication_lineage_owner", None) is None
        changed = None if replacement == "missing" else (*lease,)
        assert changed is not lease
        controller._producer_publication_dispatch = changed
        seen.append(replacement)
        return original_join(provider, request, plan, inputs)

    monkeypatch.setattr(NativeRSISchedulerProvider, "_python_publication_join", changed_join)
    with pytest.raises(RSILearningError, match="attempt_unknown") as caught:
        _run(controller, value)
    assert seen == [replacement]
    causes = []
    error = caught.value
    while error is not None:
        causes.append(str(error))
        error = error.__cause__
    assert any("dispatch_lease_invalid" in text or "publication_dispatch_invalid" in text for text in causes)
    assert observation.attempts == observation.handoffs == []
    state = value.ledger.controller_checkpoint(value.binding.run_id)[1]
    entry = state["producer_episode_staging"]["run-1-target-0"]
    ready = materialize_ready(entry["ready"], allow_capsule=True,
                              expected_workspace=value.root,
                              expected_journal_id=entry["identity"]["journal_id"])
    with sqlite3.connect(value.ledger.database) as connection:
        claims = connection.execute("SELECT episode_id FROM rsi_native_episode_claims").fetchall()
    assert claims == [("run-1-target-0",)]
    request = SolverRequest.from_dict(ready["plan"]["request"])
    assert value.ledger.inspect_native_episode_claim(request, plan_sha256=ready["plan"]["plan_sha256"]).status == "started"
    assert [path.name for path in value.root.glob("evolution/producer-batches/*/lineage/*")] == ["rsi-ready.snapshot"]
    assert controller._producer_publication_dispatch is None
    assert controller._python_admission_flow_local.active is None
