"""Executable contracts for Feature 160 stage 1 durable RSI resume.

The current provider-free MVP has the append-only ledger and episode reconcile primitives, but it
does not yet expose the complete controller-level resume API.  The future-facing tests are marked
non-strict xfail so they document the required behavior without making the existing suite fail.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from lunar_evolution import RSILearningController, RSILearningError, RSILedger

HEX = "a" * 64


def _ledger(tmp_path: Path) -> RSILedger:
    return RSILedger(tmp_path / "rsi.sqlite3")


def _run_payload() -> dict[str, object]:
    return {
        "mode": "drs",
        "phase": "target",
        "contract_sha256": HEX,
        "evaluator_sha256": HEX,
        "environment_sha256": HEX,
        "memory_snapshot_sha256": HEX,
        "solver_id": "mock",
        "solver_fingerprint": HEX,
        "budget": {
            "max_depth": 3,
            "max_practice_episodes": 2,
            "max_target_attempts": 2,
            "deadline_at": "2099-01-01T00:00:00+00:00",
        },
        "consumed": {
            "depth": 0,
            "practice_episodes": 0,
            "target_attempts": 0,
        },
    }


def test_unknown_episode_is_quarantined_until_explicit_reconcile(tmp_path: Path) -> None:
    """The currently implemented ledger already enforces the most basic unknown gate."""

    ledger = _ledger(tmp_path)
    created = ledger.create_episode("unknown-episode", HEX, {"run_id": "run-1"})
    running = ledger.transition(
        "unknown-episode", state="running", expected_record_sha256=created.record_sha256
    )
    unknown = ledger.reconcile_worker(
        "unknown-episode", worker_state="unknown", expected_record_sha256=running.record_sha256
    )

    with pytest.raises(RSILearningError, match="rsi_state_transition_invalid"):
        ledger.transition(
            "unknown-episode", state="running", expected_record_sha256=unknown.record_sha256
        )


def test_resume_reuses_terminal_receipt_without_reexecution(tmp_path: Path) -> None:
    """A completed episode must be returned from its receipt, never executed a second time."""

    class CountingGateway:
        def __init__(self) -> None:
            self.calls = 0

        def rsi_fingerprint_config(self):
            return {"fixture": "counting"}

        def run(self, request):
            self.calls += 1
            digest = hashlib.sha256(request.digest().encode()).hexdigest()
            from lunar_evolution import SolverResult

            return SolverResult(
                request.episode_id,
                request.digest(),
                "completed",
                digest,
                digest,
                digest,
                digest,
                1.0,
                "fixture_completed",
            )

    gateway = CountingGateway()
    ledger = _ledger(tmp_path)
    controller = RSILearningController(
        gateway, ledger=ledger, target_judge=lambda _execution: (True, "accepted")
    )
    controller.run_drs(
        run_id="resume-terminal",
        contract_sha256=HEX,
        evaluator_sha256=HEX,
        environment_sha256=HEX,
        solver_id="mock",
        max_target_attempts=1,
    )
    resumed = controller.resume("resume-terminal")
    assert resumed.status == "completed"
    assert gateway.calls == 1


@pytest.mark.parametrize(
    "field",
    [
        "contract_sha256",
        "evaluator_sha256",
        "environment_sha256",
        "memory_snapshot_sha256",
        "solver_fingerprint",
    ],
)
def test_resume_rejects_fingerprint_drift(tmp_path: Path, field: str) -> None:
    """Changing any immutable run pin must fail before a solver call is made."""

    ledger = _ledger(tmp_path)
    payload = _run_payload()
    created = ledger.create_run("resume-drift", HEX, payload)
    ledger.transition("resume-drift", state="running", expected_record_sha256=created.record_sha256)
    observed = dict(payload)
    observed[field] = "b" * 64
    controller = RSILearningController(lambda _request: None, ledger=ledger)

    with pytest.raises(RSILearningError, match="rsi_resume_.*drift"):
        controller.resume("resume-drift", observed_fingerprints=observed)


def test_resume_cannot_expand_budget_or_reset_deadline(tmp_path: Path) -> None:
    """Resume accepts only the persisted remaining budget and absolute deadline."""

    ledger = _ledger(tmp_path)
    payload = _run_payload()
    payload["consumed"] = {"depth": 2, "practice_episodes": 2, "target_attempts": 1}
    created = ledger.create_run("resume-budget", HEX, payload)
    running = ledger.transition("resume-budget", state="running", expected_record_sha256=created.record_sha256)
    ledger.transition("resume-budget", state="paused", expected_record_sha256=running.record_sha256)
    controller = RSILearningController(lambda _request: None, ledger=ledger)

    with pytest.raises(RSILearningError, match="rsi_resume_budget_drift"):
        controller.resume(
            "resume-budget",
            budget_policy={
                "max_depth": 99,
                "max_practice_episodes": 99,
                "deadline_at": "2099-01-02T00:00:00+00:00",
            },
        )


def test_unknown_run_requires_reconcile_before_resume(tmp_path: Path) -> None:
    """An unknown run cannot launch practice or retry until reconcile settles it."""

    ledger = _ledger(tmp_path)
    created = ledger.create_run("resume-unknown", HEX, _run_payload())
    running = ledger.transition("resume-unknown", state="running", expected_record_sha256=created.record_sha256)
    unknown = ledger.transition("resume-unknown", state="unknown", expected_record_sha256=running.record_sha256)
    controller = RSILearningController(lambda _request: None, ledger=ledger)

    with pytest.raises(RSILearningError, match="rsi_unknown_reconcile_required"):
        controller.resume("resume-unknown")

    assert ledger.get("resume-unknown").record_sha256 == unknown.record_sha256


def test_resume_preserves_episode_identity_after_interruption(tmp_path: Path) -> None:
    """Recovery continues the original episode/request identity instead of creating a new target."""

    ledger = _ledger(tmp_path)
    payload = _run_payload()
    payload["current_episode_id"] = "target-0"
    created = ledger.create_run("resume-identity", HEX, payload)
    running = ledger.transition("resume-identity", state="running", expected_record_sha256=created.record_sha256)
    ledger.transition("resume-identity", state="paused", expected_record_sha256=running.record_sha256)
    controller = RSILearningController(lambda _request: None, ledger=ledger)

    resumed = controller.resume("resume-identity")
    assert resumed.current_episode_id == "target-0"
