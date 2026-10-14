"""Original owner-scope gates, with process launch explicitly forbidden."""
from __future__ import annotations

import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from test_producer_python_runtime import _inventory
from test_rsi_child_execution_flow import _Crash, _successful_fixture
from test_rsi_producer_staging_controller import _run

from lunar_evolution import RSILearningController, RSILearningError, native_trusted_scheduler
from lunar_evolution.rsi_gateway import SolverRequest
from lunar_evolution.rsi_native_plan import NativeRSIExecutionPlan
from lunar_evolution.rsi_publication_lineage import RSIPublicationLineage


@pytest.fixture(autouse=True)
def _forbid_process(monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("subprocess forbidden"))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("subprocess forbidden"))


def _captured_owner(tmp_path, monkeypatch, operation=None):
    value, old, supplier, observation = _successful_fixture(tmp_path, monkeypatch)
    controller = RSILearningController(
        value.gateway, ledger=value.ledger, producer_sidecar=value.sidecar,
        producer_workspace=value.root, producer_stager=old.producer_stager,
        producer_child_execution=True, producer_multi_episode_publication=True,
    )
    observation.controller = controller
    captured = []

    def no_attempt(*args, **kwargs):
        owner = controller._python_admission_flow_local.publication_lineage_owner
        assert type(owner) is RSIPublicationLineage
        assert value.ledger.controller_lock_held(value.binding.run_id)
        assert owner._ledger is value.ledger and owner._gateway is value.gateway
        assert owner._workspace is controller.producer_workspace
        assert owner._sidecar is value.sidecar
        lease = controller._producer_publication_dispatch
        assert lease is owner._dispatch_lease
        assert lease[0] is controller._python_admission_flow_local.active.state
        assert lease[1].config.receipt_provider._python_admission_controller is controller
        assert lease[2] == owner._request and lease[4] == owner._plan
        captured.append(owner)
        if operation is not None:
            operation(owner, controller, value)
        raise _Crash()

    monkeypatch.setattr(native_trusted_scheduler, "run_native_trusted_attempt", no_attempt)
    with pytest.raises(_Crash):
        _run(controller, value)
    assert len(captured) == 1 and len(supplier.observations) == 1
    assert controller._producer_publication_dispatch is None
    return value, controller, captured[0]


def test_original_owner_is_bound_before_any_process_or_publication(tmp_path, monkeypatch):
    value, controller, owner = _captured_owner(tmp_path, monkeypatch)
    state = value.ledger.controller_checkpoint(value.binding.run_id)[1]
    assert state["producer_multi_episode_publication"] is True
    assert state["producer_child_execution"] is True
    assert state.get("producer_publication_lineage") is None
    assert owner._plan.request == owner._request
    assert owner._memory.digest() == owner._request.memory_snapshot_sha256
    assert owner._prepared is None
    assert [path.name for path in value.root.glob("evolution/producer-batches/*/lineage/*")] == ["rsi-ready.snapshot"]
    assert controller.gateway is value.gateway


def test_scope_exit_cannot_recreate_launch_authority(tmp_path, monkeypatch):
    value, _controller, owner = _captured_owner(tmp_path, monkeypatch)
    before = _inventory(value.root)
    with pytest.raises(RSILearningError):
        owner.validate_launch(workspace=value.root, intent=value.sidecar.binding.intent)
    assert _inventory(value.root) == before


def test_foreign_thread_cannot_use_original_owner(tmp_path, monkeypatch):
    def operation(owner, controller, value):
        before = _inventory(value.root)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(owner._check_owner)
            with pytest.raises(RSILearningError, match="owner_drift"):
                future.result()
        assert _inventory(value.root) == before
    _captured_owner(tmp_path, monkeypatch, operation)


@pytest.mark.parametrize("attribute", ["validate_before", "retain_before", "verify_precommit", "retain_terminal"])
def test_owner_does_not_accept_instance_callback_shadow(tmp_path, monkeypatch, attribute):
    def operation(owner, controller, value):
        with pytest.raises(AttributeError):
            setattr(owner, attribute, lambda *a, **k: None)
        assert not hasattr(owner, "__dict__")
        owner._check_owner()
    _captured_owner(tmp_path, monkeypatch, operation)


@pytest.mark.parametrize("field", ["gateway", "ledger", "producer_sidecar", "producer_workspace"])
def test_original_component_replacement_refuses_without_lineage_effects(tmp_path, monkeypatch, field):
    def operation(owner, controller, value):
        before = _inventory(value.root)
        original = getattr(controller, field)
        setattr(controller, field, object())
        try:
            with pytest.raises(RSILearningError, match="owner_drift"):
                owner._check_owner()
        finally:
            setattr(controller, field, original)
        assert _inventory(value.root) == before
        owner._check_owner()
    _captured_owner(tmp_path, monkeypatch, operation)


@pytest.mark.parametrize("flag,value", [
    ("producer_multi_episode_publication", False),
    ("producer_multi_episode_publication", 1),
    ("producer_child_execution", False),
])
def test_original_opt_in_cannot_change_in_live_owner(tmp_path, monkeypatch, flag, value):
    def operation(owner, controller, fixture):
        original = getattr(controller, flag)
        before = _inventory(fixture.root)
        setattr(controller, flag, value)
        try:
            with pytest.raises(RSILearningError):
                owner._check_owner()
        finally:
            setattr(controller, flag, original)
        assert _inventory(fixture.root) == before
    _captured_owner(tmp_path, monkeypatch, operation)


def test_independent_latest_checkpoint_cannot_refresh_original_owner(tmp_path, monkeypatch):
    def operation(owner, controller, value):
        head, state = value.ledger.controller_checkpoint(value.binding.run_id)
        state["unrelated_increment"] = "foreign CAS"
        replacement = value.ledger.write_controller_checkpoint(value.binding.run_id, state, expected_sha256=head)
        assert replacement != owner._head
        before = _inventory(value.root)
        with pytest.raises(RSILearningError, match="flow_stale"):
            owner._check_owner()
        assert owner._head == head
        assert _inventory(value.root) == before
    _captured_owner(tmp_path, monkeypatch, operation)


def test_same_scope_cannot_mint_second_owner(tmp_path, monkeypatch):
    def operation(owner, controller, value):
        before = _inventory(value.root)
        lease = owner._dispatch_lease
        with pytest.raises(RSILearningError, match="owner_already_created"):
            RSIPublicationLineage(controller, request=lease[2], memory=owner._memory, native_plan=lease[4])
        assert _inventory(value.root) == before
    _captured_owner(tmp_path, monkeypatch, operation)


@pytest.mark.parametrize("replacement", ["missing", "equal_tuple"])
def test_live_owner_requires_exact_fresh_dispatch_lease(tmp_path, monkeypatch, replacement):
    def operation(owner, controller, value):
        lease = owner._dispatch_lease
        before = _inventory(value.root)
        controller._producer_publication_dispatch = None if replacement == "missing" else (*lease,)
        try:
            with pytest.raises(RSILearningError, match="owner_drift"):
                owner._check_owner()
        finally:
            controller._producer_publication_dispatch = lease
        assert _inventory(value.root) == before
        owner._check_owner()
    _captured_owner(tmp_path, monkeypatch, operation)


@pytest.mark.parametrize("replacement", ["missing", "request_copy", "plan_copy", "foreign_provider"])
def test_owner_construction_requires_original_dispatch_inputs(tmp_path, monkeypatch, replacement):
    def operation(owner, controller, value):
        lease = owner._dispatch_lease
        request, plan = lease[2], lease[4]
        provider = lease[1].config.receipt_provider
        before = _inventory(value.root)
        if replacement == "missing":
            controller._producer_publication_dispatch = None
        elif replacement == "request_copy":
            request = SolverRequest.from_dict(request.to_dict())
            assert request == lease[2] and request is not lease[2]
        elif replacement == "plan_copy":
            plan = NativeRSIExecutionPlan.from_dict(plan.to_dict())
            assert plan == lease[4] and plan is not lease[4]
        else:
            provider._python_admission_controller = object()
        try:
            with pytest.raises(RSILearningError, match="dispatch_lease_invalid"):
                RSIPublicationLineage(controller, request=request, memory=owner._memory, native_plan=plan)
        finally:
            controller._producer_publication_dispatch = lease
            provider._python_admission_controller = controller
        assert _inventory(value.root) == before
        owner._check_owner()
    _captured_owner(tmp_path, monkeypatch, operation)


def test_foreign_provider_cannot_continue_original_owner(tmp_path, monkeypatch):
    def operation(owner, controller, value):
        provider = owner._dispatch_lease[1].config.receipt_provider
        before = _inventory(value.root)
        provider._python_admission_controller = object()
        try:
            with pytest.raises(RSILearningError, match="owner_drift"):
                owner._check_owner()
        finally:
            provider._python_admission_controller = controller
        assert _inventory(value.root) == before
    _captured_owner(tmp_path, monkeypatch, operation)


@pytest.mark.parametrize("kind", ["request", "memory", "plan"])
def test_live_original_dispatch_dtos_cannot_change_after_capture(tmp_path, monkeypatch, kind):
    def operation(owner, controller, value):
        lease = owner._dispatch_lease
        dto, field, changed = {
            "request": (lease[2], "episode_id", "foreign-episode"),
            "memory": (lease[3], "snapshot_id", "foreign-memory"),
            "plan": (lease[4], "launch_id", "foreign-launch"),
        }[kind]
        original = getattr(dto, field)
        before = _inventory(value.root)
        object.__setattr__(dto, field, changed)
        try:
            with pytest.raises(RSILearningError):
                owner._check_owner()
        finally:
            object.__setattr__(dto, field, original)
        assert _inventory(value.root) == before
        owner._check_owner()
    _captured_owner(tmp_path, monkeypatch, operation)


def test_launch_must_match_original_child_intent(tmp_path, monkeypatch):
    def operation(owner, controller, value):
        sidecar, _proof = controller._python_admission_sidecar(owner._plan.run_id, owner._request.episode_id)
        before = _inventory(value.root)
        changed = replace(sidecar.binding.intent, launch_id="foreign-launch", intent_sha256=None)
        with pytest.raises(RSILearningError, match="launch_mismatch"):
            owner.validate_launch(workspace=value.root, intent=changed)
        owner.validate_launch(workspace=value.root, intent=sidecar.binding.intent)
        assert _inventory(value.root) == before
    _captured_owner(tmp_path, monkeypatch, operation)


def test_capsule_ack_requires_its_internal_pending_increment(tmp_path, monkeypatch):
    def operation(owner, controller, value):
        before = _inventory(value.root)
        checkpoint = value.ledger.controller_checkpoint(value.binding.run_id)
        with pytest.raises(RSILearningError, match="acknowledgement_missing"):
            controller._ack_publication_lineage_for_active_flow(owner)
        assert value.ledger.controller_checkpoint(value.binding.run_id) == checkpoint
        assert _inventory(value.root) == before
    _captured_owner(tmp_path, monkeypatch, operation)
