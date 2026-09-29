"""Explicit active-memory target API is read-only and scope/pin bound."""

import hashlib
from dataclasses import dataclass, field, replace

import pytest

from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.rsi_controller import RSILearningController
from lunar_evolution.rsi_gateway import DeterministicMockSolver
from lunar_evolution.rsi_learning import MemoryItem, ReadOnlyMemorySnapshot, RSILearningError
from lunar_evolution.rsi_memory_governance import MemoryCompatibility, MemoryScope
from lunar_evolution.rsi_store import RSILedger

HEX = "a" * 64
CONTRACT = "b" * 64
EVALUATOR = "c" * 64
ENVIRONMENT = "d" * 64
SOLVER = "mock"
SOLVER_FINGERPRINT = hashlib.sha256(canonical_json({"solver_id": SOLVER, "settings": []})).hexdigest()
ACTOR = "f" * 64


@dataclass
class ActiveLedger:
    ledger: RSILedger
    items: list[MemoryItem]
    states: dict[str, str] = field(default_factory=dict)

    def active_memories(self, *, scope, compatibility):
        if scope != MemoryScope("sorting", "sorting", "sort") or compatibility != pins():
            return ()
        return tuple(
            item for item in self.items
            if self.states.get(item.memory_id, "active") == "active"
        )


class MemoryGateway:
    def __init__(self):
        self.calls = []
        self.delegate = DeterministicMockSolver()

    def fingerprint(self):
        return ACTOR

    def run(self, request):
        raise AssertionError("active target must use run_with_memory")

    def run_with_memory(self, request, memory):
        assert isinstance(memory, ReadOnlyMemorySnapshot)
        self.calls.append((request, memory))
        return self.delegate.run(request)


class PlainGateway(MemoryGateway):
    run_with_memory = None


def memory(*, memory_id="active-1", family="sorting", status="approved"):
    return MemoryItem(
        memory_id, family, "input is reversed", "sort input", "sorted", "integers",
        (CONTRACT,), (SOLVER,), "pass", "1" * 64, "source-episode", status=status,
    )


def pins():
    return MemoryCompatibility(CONTRACT, EVALUATOR, ENVIRONMENT, SOLVER, SOLVER_FINGERPRINT)


def make_controller(tmp_path, gateway, items):
    ledger = RSILedger(tmp_path / "rsi.db")
    governance = ActiveLedger(ledger, items)
    return RSILearningController(gateway, ledger=ledger, memory_governance=governance), governance


def test_active_snapshot_is_deterministic_and_scope_isolated(tmp_path):
    gateway = MemoryGateway()
    instance, governance = make_controller(tmp_path, gateway, [memory()])
    scope = MemoryScope("sorting", "sorting", "sort")
    selected = instance.active_snapshot(scope=scope, compatibility=pins())
    assert selected.items == (governance.items[0],)
    assert selected.digest == instance.active_snapshot(scope=scope, compatibility=pins()).digest
    assert instance.active_snapshot(
        scope=MemoryScope("other", "other-family", "other"), compatibility=pins()
    ).items == ()


def test_active_target_requires_explicit_memory_gateway_and_full_pins(tmp_path):
    instance, _governance = make_controller(tmp_path, PlainGateway(), [memory()])
    scope = MemoryScope("sorting", "sorting", "sort")
    with pytest.raises(RSILearningError, match="rsi_active_gateway_memory_api_required"):
        instance.run_active_target(
            run_id="active-run", target_id="active-target", scope=scope, compatibility=pins(),
            contract_sha256=CONTRACT, evaluator_sha256=EVALUATOR,
            environment_sha256=ENVIRONMENT, solver_id=SOLVER,
        )


def test_active_target_sends_readonly_snapshot_and_reverifies(tmp_path):
    gateway = MemoryGateway()
    instance, governance = make_controller(tmp_path, gateway, [memory()])
    scope = MemoryScope("sorting", "sorting", "sort")
    result = instance.run_active_target(
        run_id="active-run", target_id="active-target", scope=scope, compatibility=pins(),
        contract_sha256=CONTRACT, evaluator_sha256=EVALUATOR,
        environment_sha256=ENVIRONMENT, solver_id=SOLVER,
    )
    assert result.passed
    assert len(gateway.calls) == 1
    request, supplied = gateway.calls[0]
    assert request.memory_snapshot_sha256 == supplied.digest
    with pytest.raises(AttributeError):
        supplied.items = ()
    assert instance.snapshot.items == ()
    assert governance.items[0].status == "approved"


@pytest.mark.parametrize("terminal", ["revoked", "quarantined"])
def test_revoked_or_quarantined_active_memory_is_never_sent(tmp_path, terminal):
    gateway = MemoryGateway()
    item = memory()
    instance, governance = make_controller(tmp_path, gateway, [item])
    governance.states[item.memory_id] = terminal
    scope = MemoryScope("sorting", "sorting", "sort")
    with pytest.raises(RSILearningError, match="rsi_active_memory_unavailable"):
        instance.run_active_target(
            run_id="active-run", target_id="active-target", scope=scope, compatibility=pins(),
            contract_sha256=CONTRACT, evaluator_sha256=EVALUATOR,
            environment_sha256=ENVIRONMENT, solver_id=SOLVER,
        )
    assert gateway.calls == []


@pytest.mark.parametrize("field_name", ["contract_sha256", "evaluator_sha256", "environment_sha256", "solver_id", "solver_fingerprint"])
def test_active_target_rejects_compatibility_drift_before_launch(tmp_path, field_name):
    gateway = MemoryGateway()
    instance, _governance = make_controller(tmp_path, gateway, [memory()])
    drifted = replace(pins(), **{field_name: "other" if field_name == "solver_id" else "9" * 64})
    with pytest.raises(RSILearningError, match="rsi_active_memory_compatibility_mismatch"):
        instance.run_active_target(
            run_id="active-run", target_id="active-target", scope=MemoryScope("sorting", "sorting", "sort"),
            compatibility=drifted, contract_sha256=CONTRACT, evaluator_sha256=EVALUATOR,
            environment_sha256=ENVIRONMENT, solver_id=SOLVER,
        )
    assert gateway.calls == []


def test_active_target_rechecks_after_episode_intent_before_dispatch(tmp_path, monkeypatch):
    gateway = MemoryGateway()
    item = memory()
    instance, governance = make_controller(tmp_path, gateway, [item])
    create = instance.ledger.create_episode_record

    def revoke_after_intent(episode):
        record = create(episode)
        governance.states[item.memory_id] = "revoked"
        return record

    monkeypatch.setattr(instance.ledger, "create_episode_record", revoke_after_intent)
    with pytest.raises(RSILearningError, match="rsi_active_memory_changed_before_launch"):
        instance.run_active_target(
            run_id="active-run", target_id="active-target", scope=MemoryScope("sorting", "sorting", "sort"),
            compatibility=pins(), contract_sha256=CONTRACT, evaluator_sha256=EVALUATOR,
            environment_sha256=ENVIRONMENT, solver_id=SOLVER,
        )
    assert gateway.calls == []
    assert instance.ledger.get("active-target").state == "running"


def test_active_target_cannot_repeat_through_another_run(tmp_path):
    gateway = MemoryGateway()
    instance, _governance = make_controller(tmp_path, gateway, [memory()])
    values = {
        "target_id": "active-target", "scope": MemoryScope("sorting", "sorting", "sort"),
        "compatibility": pins(), "contract_sha256": CONTRACT, "evaluator_sha256": EVALUATOR,
        "environment_sha256": ENVIRONMENT, "solver_id": SOLVER,
    }
    instance.run_active_target(run_id="first", **values)
    with pytest.raises(RSILearningError, match="rsi_active_target_already_started"):
        instance.run_active_target(run_id="second", **values)
    assert len(gateway.calls) == 1
