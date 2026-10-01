from __future__ import annotations

from pathlib import Path

import pytest

from lunar_evolution.rsi_actor import AgentLoopActorGateway
from lunar_evolution.rsi_adapters import fixture_solver_gateway
from lunar_evolution.rsi_identity import RSIIdentityError, component_fingerprint


def _threshold_judge(threshold: float):
    def judge(value):
        return value >= threshold

    return judge


def _mutable_judge(settings):
    def judge(value):
        return value >= settings["threshold"]

    return judge


class BoundJudge:
    def __init__(self, threshold: float) -> None:
        self.threshold = threshold
        self.calls = 0

    def judge(self, value):
        self.calls += 1
        return value >= self.threshold


class ConfiguredBoundJudge(BoundJudge):
    def rsi_fingerprint_config(self):
        return {"threshold": self.threshold}


def _runtime_factory(workspace):
    del workspace
    raise AssertionError("fingerprint must not construct a runtime")


def _other_runtime_factory(workspace):
    del workspace
    raise AssertionError("different runtime implementation")


def _receipt_builder(request, workspace, result, trace):
    del request, workspace, result, trace
    return {"evaluator": "one"}


def _other_receipt_builder(request, workspace, result, trace):
    del request, workspace, result, trace
    return {"evaluator": "two"}


def test_immutable_closure_value_drift_changes_identity() -> None:
    assert component_fingerprint(_threshold_judge(0.5)) == component_fingerprint(_threshold_judge(0.5))
    assert component_fingerprint(_threshold_judge(0.5)) != component_fingerprint(_threshold_judge(0.9))


def test_mutable_closure_requires_explicit_projection_hook() -> None:
    settings = {"threshold": 0.5, "calls": 0}
    judge = _mutable_judge(settings)
    with pytest.raises(RSIIdentityError, match="rsi_identity_config_hook_required"):
        component_fingerprint(judge)

    judge.rsi_fingerprint_config = lambda: {"threshold": settings["threshold"]}
    baseline = component_fingerprint(judge)
    settings["calls"] += 1
    assert baseline == component_fingerprint(judge)
    settings["threshold"] = 0.9
    assert baseline != component_fingerprint(judge)


def test_live_default_and_keyword_default_drift_changes_identity() -> None:
    def judge(value, threshold=0.5, *, ceiling=1.0):
        return threshold <= value <= ceiling

    first = component_fingerprint(judge)
    judge.__defaults__ = (0.9,)
    second = component_fingerprint(judge)
    assert first != second
    judge.__kwdefaults__ = {"ceiling": 2.0}
    assert second != component_fingerprint(judge)


@pytest.mark.parametrize("keyword", [False, True])
def test_mutable_defaults_fail_closed_without_hook(keyword: bool) -> None:
    def judge(value, threshold=0.5, *, settings=None):
        return value, threshold, settings

    if keyword:
        judge.__kwdefaults__ = {"settings": {"threshold": 0.5}}
    else:
        judge.__defaults__ = ([0.5],)
    with pytest.raises(RSIIdentityError, match="rsi_identity_config_hook_required"):
        component_fingerprint(judge)
    judge.fingerprint_config = lambda: {"threshold": 0.5}
    assert component_fingerprint(judge)


def test_bound_method_binds_owner_configuration_and_excludes_runtime_counter() -> None:
    with pytest.raises(RSIIdentityError, match="rsi_identity_config_hook_required"):
        component_fingerprint(BoundJudge(0.5).judge)
    owner = ConfiguredBoundJudge(0.5)
    first = component_fingerprint(owner.judge)
    assert owner.judge(1.0)
    assert first == component_fingerprint(owner.judge)
    owner.threshold = 0.9
    assert first != component_fingerprint(owner.judge)


def test_generated_nested_code_is_part_of_identity() -> None:
    def generated(constant: int):
        namespace: dict[str, object] = {"__name__": "identity_fixture"}
        exec(  # noqa: S102 - fixed local fixture exercises generated code without source files
            compile(f"def solve():\n    return lambda: {constant}\n", "<generated-rsi>", "exec"), namespace,
        )
        return namespace["solve"]

    assert component_fingerprint(generated(1)) != component_fingerprint(generated(2))


def test_provider_free_gateway_binds_actual_fixture_configuration() -> None:
    baseline = component_fingerprint(fixture_solver_gateway("shinka", provenance={"seed": 1}))
    assert baseline != component_fingerprint(fixture_solver_gateway("shinka", provenance={"seed": 2}))
    assert baseline != component_fingerprint(
        fixture_solver_gateway("shinka", terminal_status="failed", provenance={"seed": 1})
    )


def test_actor_binds_runtime_receipt_builder_and_workspace(tmp_path: Path) -> None:
    def actor(factory=_runtime_factory, receipts=_receipt_builder, workspace=tmp_path):
        return AgentLoopActorGateway(factory, workspace, receipt_builder=receipts)

    baseline = component_fingerprint(actor())
    assert baseline == component_fingerprint(actor())
    assert baseline != component_fingerprint(actor(factory=_other_runtime_factory))
    assert baseline != component_fingerprint(actor(receipts=_other_receipt_builder))
    assert baseline != component_fingerprint(actor(workspace=tmp_path / "other"))


def test_actor_rejects_unidentified_runtime_factory_closure(tmp_path: Path) -> None:
    settings = {"model": "configured-model"}

    def factory(workspace):
        return workspace, settings["model"]

    actor = AgentLoopActorGateway(factory, tmp_path)
    with pytest.raises(RSIIdentityError, match="rsi_identity_config_hook_required"):
        component_fingerprint(actor)
    factory.rsi_fingerprint_config = lambda: dict(settings)
    first = component_fingerprint(actor)
    settings["model"] = "different-model"
    assert first != component_fingerprint(actor)
