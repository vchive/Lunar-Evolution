"""Provider-free RSI learning-mode quickstart."""

from __future__ import annotations

import json

from lunar_evolution import DeterministicMockSolver, RSILearningController

HEX = "a" * 64


class SequenceGateway:
    def __init__(self) -> None:
        self._statuses = ["completed", "completed", "completed"]

    def run(self, request):
        status = self._statuses.pop(0)
        return DeterministicMockSolver(terminal_status=status).run(request)


def target_judge(execution):
    # The first completed target is deliberately treated as a capability-gap failure so the
    # fixture exercises practice, memory promotion and the next target attempt.
    if execution.episode.episode_kind == "target" and execution.episode.wave == 0:
        return False, "fixture capability gap"
    return True, "fixture target accepted"


result = RSILearningController(SequenceGateway(), target_judge=target_judge).run_drs(
    run_id="quickstart-rsi",
    contract_sha256=HEX,
    evaluator_sha256=HEX,
    environment_sha256=HEX,
    solver_id="mock",
    max_practice_rounds=1,
    max_target_attempts=2,
)
print(
    json.dumps(
        {
            "run_id": result.run_id,
            "status": result.status,
            "target_attempts": len(result.target_attempts),
            "practice_episodes": len(result.practice_episodes),
            "memory_snapshot_sha256": result.memory_snapshot.digest(),
        },
        sort_keys=True,
    )
)
