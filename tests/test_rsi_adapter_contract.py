from __future__ import annotations

import hashlib

import pytest

from lunar_evolution.rsi_adapter_contract import (
    AdapterCapability,
    AdapterContractHarness,
    AdapterLifecycle,
    AdapterPins,
    AdapterRequest,
    fixture_capability,
    validate_lifecycle,
)
from lunar_evolution.rsi_adapters import fixture_solver_gateway
from lunar_evolution.rsi_gateway import DeterministicMockSolver, SolverRequest
from lunar_evolution.rsi_learning import RSILearningError


def digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def request(solver_id: str = "mock", *, deadline_at: float | None = None) -> SolverRequest:
    return SolverRequest.build(
        episode_id="episode-contract",
        contract_sha256=digest("contract"),
        evaluator_sha256=digest("evaluator"),
        environment_sha256=digest("environment"),
        memory_snapshot_sha256=digest("memory"),
        solver_id=solver_id,
        solver_settings={"iterations": 1},
        budget={"candidate_attempts": 2},
    )


def test_provider_free_mock_follows_contract_lifecycle() -> None:
    solver_request = request()
    harness = AdapterContractHarness(DeterministicMockSolver(), capability=fixture_capability("fixture"))
    result = harness.run(solver_request)
    assert result.status == "completed"
    assert result.receipt.request_sha256 == solver_request.digest()
    assert result.ownership.memory_write_enabled is False
    assert result.lifecycle == tuple(stage.value for stage in AdapterLifecycle if stage != AdapterLifecycle.RECOVER)


def test_provider_free_named_solver_fixture_is_declaration_only() -> None:
    capability = fixture_capability("openevolve")
    assert capability.fixture is True
    assert capability.provider_free is True
    assert capability.memory_write is False
    assert capability.solver_id == "openevolve"


def test_implicit_capability_uses_fixture_factory() -> None:
    class NamedGateway:
        solver_id = "fixture"

        def run(self, solver_request):
            return DeterministicMockSolver().run(solver_request)

    capability = validate_lifecycle(NamedGateway())
    assert capability.fixture is True
    assert capability.solver_id == "fixture"


def test_named_hooks_receive_request_and_zero_arg_hooks_remain_zero_arg() -> None:
    seen: list[object] = []

    class HookGateway:
        def register(self, request=None):
            seen.append(request)

        def preflight(self):
            seen.append("zero")

        def run(self, solver_request):
            return DeterministicMockSolver().run(solver_request)

    result = AdapterContractHarness(HookGateway(), capability=fixture_capability("fixture")).run(request())
    assert result.status == "completed"
    assert isinstance(seen[0], AdapterRequest)
    assert seen[1] == "zero"


def test_provider_free_gateway_uses_same_receipt_boundary() -> None:
    solver_request = request("shinka")
    gateway = fixture_solver_gateway("shinka")
    harness = AdapterContractHarness(gateway, capability=fixture_capability("shinka"))
    result = harness.run(solver_request)
    assert result.status == "completed"
    assert result.receipt.official_evaluation_receipt_sha256 is not None


def test_deadline_and_cancel_are_unified_terminal_statuses() -> None:
    solver_request = request()
    deadline = AdapterContractHarness(DeterministicMockSolver(), capability=fixture_capability("fixture"), clock=lambda: 5.0)
    timed_out = deadline.run(AdapterRequest.from_solver_request(solver_request, deadline_at=5.0))
    assert timed_out.status == "timed_out"
    cancelled = deadline.run(solver_request, cancel=True)
    assert cancelled.status == "cancelled"


def test_unknown_result_is_preserved_and_recovery_is_called() -> None:
    calls: list[str] = []

    class UnknownGateway:
        def run(self, solver_request: SolverRequest):
            calls.append("execute")
            return DeterministicMockSolver(terminal_status="unknown").run(solver_request)

        def recover(self, _request, _result):
            calls.append("recover")

        def close(self, _request, _result):
            calls.append("close")

    result = AdapterContractHarness(UnknownGateway(), capability=fixture_capability("fixture")).run(request())
    assert result.status == "unknown"
    assert calls == ["execute", "recover", "close"]


def test_execute_exception_invokes_recovery_before_close() -> None:
    calls: list[str] = []

    class FailingGateway:
        def run(self, _solver_request):
            calls.append("execute")
            raise RuntimeError("worker failed")

        def recover(self, _request, result):
            calls.append(f"recover:{result.status}")

        def close(self, _request, result):
            calls.append(f"close:{result.status}")

    result = AdapterContractHarness(FailingGateway(), capability=fixture_capability("fixture")).run(request())
    assert result.status == "failed"
    assert calls == ["execute", "recover:failed", "close:failed"]


def test_close_failure_is_best_effort_and_not_retried() -> None:
    calls: list[str] = []

    class ClosingGateway:
        def run(self, solver_request):
            return DeterministicMockSolver().run(solver_request)

        def close(self, _request, _result):
            calls.append("close")
            raise OSError("cleanup failed")

    result = AdapterContractHarness(ClosingGateway(), capability=fixture_capability("fixture")).run(request())
    assert result.status == "completed"
    assert calls == ["close"]


def test_adapter_memory_write_authority_is_rejected() -> None:
    class UnsafeGateway:
        def run(self, solver_request):
            return DeterministicMockSolver().run(solver_request)

        def commit_memory(self, *_args):
            return None

    with pytest.raises(RSILearningError, match="memory_write_forbidden"):
        validate_lifecycle(UnsafeGateway(), AdapterCapability.for_fixture("fixture"))


def test_pin_mismatch_result_is_rejected() -> None:
    class WrongGateway:
        def run(self, solver_request):
            result = DeterministicMockSolver().run(solver_request)
            return result.__class__(
                episode_id=result.episode_id,
                request_sha256=digest("other-request"),
                status=result.status,
                candidate_receipt_sha256=result.candidate_receipt_sha256,
                execution_receipt_sha256=result.execution_receipt_sha256,
                official_evaluation_receipt_sha256=result.official_evaluation_receipt_sha256,
                trace_digest=result.trace_digest,
            )

    result = AdapterContractHarness(WrongGateway(), capability=fixture_capability("fixture")).run(request())
    assert result.status == "failed"
    assert result.receipt.terminal_reason == "contract_failed"


def test_request_pins_are_content_addressed() -> None:
    solver_request = request()
    wrapped = AdapterRequest.from_solver_request(solver_request, deadline_at=12.0)
    assert wrapped.pins == AdapterPins.from_solver_request(solver_request)
    assert wrapped.request_sha256 == solver_request.digest()
    assert wrapped.to_solver_request().digest() == solver_request.digest()


def test_invalid_capability_cannot_enable_memory_write() -> None:
    with pytest.raises(RSILearningError, match="memory_write_forbidden"):
        AdapterCapability("fixture", memory_write=True)
