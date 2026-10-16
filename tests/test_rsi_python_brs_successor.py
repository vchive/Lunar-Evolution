"""Pure serial-successor tests; no ledger, files, callbacks, or workers."""

from __future__ import annotations

import pytest

from lunar_evolution.rsi_python_brs_child_policy import preflight_native_brs_child
from lunar_evolution.rsi_python_brs_successor import (
    BRSOrdinalCompletion,
    BRSOrdinalSuccessorError,
    advance_brs_ordinal,
)

DIGESTS = iter(f"{value:x}" * 64 for value in range(1, 20))
RUN = "successor-run"


def _budget(*, episodes: int = 3, used: int = 1) -> dict[str, dict[str, int | None]]:
    planned = {
        "practice_rounds": 3, "target_attempts": 0, "practice_episodes": episodes,
        "solver_invocations": episodes, "unknown_retries": 2,
        "evaluator_invocations": 3, "verifier_invocations": 3, "transfer_invocations": 0,
    }
    consumed = {
        "practice_rounds": 1, "target_attempts": 0, "practice_episodes": used,
        "solver_invocations": used, "unknown_retries": 0,
        "evaluator_invocations": 1, "verifier_invocations": 1, "transfer_invocations": 0,
    }
    return {"planned": planned, "consumed": consumed}


def _wire(executions=None, *, budget=None):
    requests = ["1" * 64, "2" * 64, "3" * 64]
    intents = [
        {"ordinal": ordinal, "episode_id": f"{RUN}-practice-4-{ordinal}", "request_sha256": request}
        for ordinal, request in enumerate(requests)
    ]
    return {
        "schema_version": 1,
        "protocol": "lunar-rsi-python-brs-child-preflight-v1",
        "run_id": RUN, "mode": "brs", "wave": 4, "max_workers": 1,
        "root_snapshot_sha256": "4" * 64,
        "intents": intents,
        "executions": [f"{RUN}-practice-4-0"] if executions is None else executions,
        "budget": _budget() if budget is None else budget,
        "caps": {"attempts": 1, "candidates": 3, "checkpoint_bytes": 4096, "aggregate_bytes": 8192},
    }


def _completion(ordinal: int = 1, *, outcome="completed", request=None):
    request = request or ("2" if ordinal == 1 else "3") * 64
    return BRSOrdinalCompletion(
        run_id=RUN, wave=4, ordinal=ordinal,
        episode_id=f"{RUN}-practice-4-{ordinal}", request_sha256=request,
        outcome=outcome, result_sha256="5" * 64, native_terminal_sha256="6" * 64,
        owner_lineage_ack_sha256="7" * 64, verified_head_sha256="8" * 64,
    )


def test_successor_advances_only_the_next_ordinal_and_preserves_m0():
    original = preflight_native_brs_child(_wire())
    result = advance_brs_ordinal(original, _completion())
    assert result.preflight.executions == (f"{RUN}-practice-4-0", f"{RUN}-practice-4-1")
    assert result.preflight.root_snapshot_sha256 == original.root_snapshot_sha256
    assert result.preflight.planned_budget == original.planned_budget
    assert dict(result.preflight.consumed_budget)["practice_episodes"] == 2
    assert result.next_selection is not None
    assert result.next_selection.ordinal == 2
    assert result.next_selection.request_sha256 == "3" * 64
    assert result.next_selection.authority is False


def test_rejected_child_can_advance_but_worker_result_cannot_replace_owner_ack():
    result = advance_brs_ordinal(preflight_native_brs_child(_wire()), _completion(outcome="rejected"))
    assert result.completion.outcome == "rejected"
    assert result.next_selection is not None and result.next_selection.ordinal == 2


@pytest.mark.parametrize(
    "completion",
    [
        _completion(ordinal=0),
        _completion(ordinal=2),
        _completion(request="f" * 64),
    ],
)
def test_mismatched_completion_refuses_before_sibling_selection(completion):
    with pytest.raises(BRSOrdinalSuccessorError, match="completion_mismatch"):
        advance_brs_ordinal(preflight_native_brs_child(_wire()), completion)


def test_complete_wave_has_no_successor_and_no_replay():
    wire = _wire(
        executions=[f"{RUN}-practice-4-0", f"{RUN}-practice-4-1", f"{RUN}-practice-4-2"],
        budget=_budget(used=3),
    )
    wire["caps"]["attempts"] = 3
    with pytest.raises(BRSOrdinalSuccessorError, match="wave_complete"):
        advance_brs_ordinal(preflight_native_brs_child(wire), _completion())


def test_budget_exhaustion_refuses_without_mutating_original():
    original = preflight_native_brs_child(_wire(budget=_budget(episodes=3, used=3)))
    with pytest.raises(BRSOrdinalSuccessorError, match="budget_exhausted"):
        advance_brs_ordinal(original, _completion())
    assert original.executions == (f"{RUN}-practice-4-0",)


@pytest.mark.parametrize("field", ["result_sha256", "native_terminal_sha256", "owner_lineage_ack_sha256", "verified_head_sha256"])
def test_missing_or_invalid_owner_evidence_refuses(field):
    value = _completion().to_dict()
    value[field] = "0" * 64
    with pytest.raises(BRSOrdinalSuccessorError, match=f"{field}_invalid"):
        BRSOrdinalCompletion(**value)
