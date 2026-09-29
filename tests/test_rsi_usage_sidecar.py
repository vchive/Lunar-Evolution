import pytest

from lunar_evolution.rsi_controller import RSILearningController
from lunar_evolution.rsi_gateway import DeterministicMockSolver
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_store import RSILedger
from lunar_evolution.rsi_usage import RSIUsageReceipt

HEX = "a" * 64
PINS = {"contract_sha256": HEX, "evaluator_sha256": HEX, "environment_sha256": HEX, "solver_id": "mock"}


class UsageGateway:
    def __init__(self, *, telemetry_for: str = "all", invalid: bool = False, mismatch: bool = False,
                 crash: bool = False):
        self.telemetry_for = telemetry_for
        self.invalid = invalid
        self.mismatch = mismatch
        self.crash = crash
        self.requests = []

    def fingerprint(self):
        return "b" * 64

    def run(self, request):
        self.requests.append(request)
        if self.crash:
            raise RuntimeError("gateway should not be called")
        return DeterministicMockSolver().run(request)

    def usage_receipt(self, request, result, wall_elapsed_ms):
        del result
        if self.invalid:
            return {"request": request.episode_id}
        if self.telemetry_for != "all" and self.telemetry_for not in request.episode_id:
            return None
        return RSIUsageReceipt.observed(
            request_count=1, wall_elapsed_ms=wall_elapsed_ms + int(self.mismatch),
        )


def judge_after_practice(execution):
    return execution.episode.wave > 0, "fixture gap"


def controller(tmp_path, gateway, **kwargs):
    return RSILearningController(gateway, ledger=RSILedger(tmp_path / "rsi.sqlite3"), **kwargs)


def test_usage_sidecars_are_durable_and_not_replayed_on_resume(tmp_path):
    gateway = UsageGateway()
    first = controller(tmp_path, gateway, target_judge=judge_after_practice)
    result = first.run_drs(run_id="sidecar", **PINS, max_practice_rounds=1, max_target_attempts=2)
    checkpoint = first.ledger.controller_checkpoint("sidecar")[1]
    assert all(entry["usage"] is not None for entry in checkpoint["episodes"].values())
    assert checkpoint["usage_state"]["aggregate"]["request_count"] == 3

    resumed_gateway = UsageGateway(crash=True)
    resumed = controller(tmp_path, resumed_gateway, target_judge=judge_after_practice).resume(run_id="sidecar")
    assert resumed == result
    assert resumed_gateway.requests == []


def test_partial_usage_keeps_unknown_counters_but_observes_controller_wall_time(tmp_path):
    gateway = UsageGateway(telemetry_for="practice")
    result = controller(tmp_path, gateway, target_judge=judge_after_practice).run_drs(
        run_id="partial-sidecar", **PINS, max_practice_rounds=1, max_target_attempts=2,
    )
    assert result.status == "completed"
    aggregate = controller(tmp_path, UsageGateway()).ledger.controller_checkpoint("partial-sidecar")[1][
        "usage_state"
    ]["aggregate"]
    assert aggregate["request_count"] is None
    assert aggregate["wall_elapsed_ms"] >= 0


@pytest.mark.parametrize(
    ("gateway", "error"),
    [(UsageGateway(invalid=True), "rsi_usage_provider_invalid"),
     (UsageGateway(mismatch=True), "rsi_usage_wall_elapsed_mismatch")],
)
def test_invalid_usage_provider_fails_closed_before_result_checkpoint(tmp_path, gateway, error):
    with pytest.raises(RSILearningError, match=error):
        controller(tmp_path, gateway).run_drs(
            run_id="invalid-sidecar", **PINS, max_practice_rounds=0, max_target_attempts=1,
        )
    checkpoint = controller(tmp_path, UsageGateway()).ledger.controller_checkpoint("invalid-sidecar")[1]
    entry = checkpoint["episodes"]["invalid-sidecar-target-0"]
    assert entry["stage"] == "launched"
    assert entry["result"] is None
    assert entry["usage"] is None


def test_tampered_usage_sidecar_blocks_resume(tmp_path):
    first = controller(tmp_path, UsageGateway())
    first.run_drs(run_id="tampered-sidecar", **PINS, max_practice_rounds=0, max_target_attempts=1)
    version, checkpoint = first.ledger.controller_checkpoint("tampered-sidecar")
    checkpoint["episodes"]["tampered-sidecar-target-0"]["usage"]["wall_elapsed_ms"] += 1
    with first.ledger.controller_lock("tampered-sidecar"):
        first.ledger.write_controller_checkpoint("tampered-sidecar", checkpoint, expected_sha256=version)
    with pytest.raises(RSILearningError, match="rsi_usage_"):
        controller(tmp_path, UsageGateway(crash=True)).resume(run_id="tampered-sidecar")


def test_external_reconciliation_does_not_reuse_unknown_provider_usage(tmp_path):
    class UnknownGateway(UsageGateway):
        def run(self, request):
            self.requests.append(request)
            return DeterministicMockSolver(terminal_status="unknown").run(request)

    first_gateway = UnknownGateway()
    first = controller(tmp_path, first_gateway)
    assert first.run_drs(
        run_id="reconciled-sidecar", **PINS, max_practice_rounds=0, max_target_attempts=1,
    ).status == "unknown"
    checkpoint = first.ledger.controller_checkpoint("reconciled-sidecar")[1]
    entry = checkpoint["episodes"]["reconciled-sidecar-target-0"]
    assert entry["usage"] is not None
    request = first_gateway.requests[0]
    head = first.ledger.get(request.episode_id)

    result = first.reconcile_episode(
        run_id="reconciled-sidecar", episode_id=request.episode_id,
        result=DeterministicMockSolver(terminal_status="failed").run(request),
        expected_record_sha256=head.record_sha256,
    )
    assert result.status == "failed"
    checkpoint = first.ledger.controller_checkpoint("reconciled-sidecar")[1]
    entry = checkpoint["episodes"]["reconciled-sidecar-target-0"]
    assert entry["usage"] is entry["usage_digest"] is entry["usage_binding"] is None
    assert checkpoint["usage_state"]["aggregate"]["request_count"] is None
