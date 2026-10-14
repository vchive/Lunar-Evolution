"""Pure native-BRS child selection checks; no ledger, files, callbacks or workers."""

from __future__ import annotations

import json

import pytest

from lunar_evolution.rsi_python_brs_child_policy import (
    BRS_CHILD_POLICY_PROTOCOL,
    BRS_CHILD_POLICY_SCHEMA_VERSION,
    MAX_BRS_CHILD_AGGREGATE_BYTES,
    MAX_BRS_CHILD_ATTEMPTS,
    MAX_BRS_CHILD_CANDIDATES,
    MAX_BRS_CHILD_PREFLIGHT_BYTES,
    BRSChildPolicyError,
    BRSNativeChildPreflight,
    preflight_native_brs_child,
)

DIGEST = "1" * 64
ROOT = "2" * 64
RUN = "brs-run"


def _budget(*, practice_episodes=2, solver_invocations=2, consumed_episodes=1,
            consumed_solver=1):
    return {
        "planned": {
            "practice_rounds": 2,
            "target_attempts": 0,
            "practice_episodes": practice_episodes,
            "solver_invocations": solver_invocations,
            "unknown_retries": 2,
            "evaluator_invocations": 2,
            "verifier_invocations": 2,
            "transfer_invocations": 0,
        },
        "consumed": {
            "practice_rounds": 1,
            "target_attempts": 0,
            "practice_episodes": consumed_episodes,
            "solver_invocations": consumed_solver,
            "unknown_retries": 0,
            "evaluator_invocations": 1,
            "verifier_invocations": 1,
            "transfer_invocations": 0,
        },
    }


def _wire(*, executions=None, intents=None, **changes):
    intents = intents or [
        {"ordinal": 0, "episode_id": f"{RUN}-practice-3-0", "request_sha256": DIGEST},
        {"ordinal": 1, "episode_id": f"{RUN}-practice-3-1", "request_sha256": "3" * 64},
    ]
    value = {
        "schema_version": BRS_CHILD_POLICY_SCHEMA_VERSION,
        "protocol": BRS_CHILD_POLICY_PROTOCOL,
        "run_id": RUN,
        "mode": "brs",
        "wave": 3,
        "max_workers": 1,
        "root_snapshot_sha256": ROOT,
        "intents": intents,
        "executions": [f"{RUN}-practice-3-0"] if executions is None else executions,
        "budget": _budget(),
        "caps": {
            "attempts": 1,
            "candidates": 2,
            "checkpoint_bytes": 4096,
            "aggregate_bytes": 1024,
        },
    }
    for key, value_change in changes.items():
        value[key] = value_change
    return value


def test_preflight_selects_next_ordinal_as_detached_non_authority():
    value = _wire()
    preflight = preflight_native_brs_child(value)
    selection = preflight.select_next_pending()
    assert isinstance(preflight, BRSNativeChildPreflight)
    assert selection is not None
    assert selection.to_dict() == {
        "run_id": RUN,
        "wave": 3,
        "ordinal": 1,
        "episode_id": f"{RUN}-practice-3-1",
        "request_sha256": "3" * 64,
        "root_snapshot_sha256": ROOT,
        "authority": False,
    }
    value["intents"][1]["episode_id"] = "mutated-after-parse"
    assert selection.episode_id == f"{RUN}-practice-3-1"
    assert preflight_native_brs_child(preflight.to_dict()).select_next_pending() == selection


def test_preflight_returns_none_when_the_original_wave_is_complete():
    value = _wire(executions=[f"{RUN}-practice-3-0", f"{RUN}-practice-3-1"])
    value["budget"] = _budget(consumed_episodes=2, consumed_solver=2)
    value["caps"]["attempts"] = 2
    assert preflight_native_brs_child(value).select_next_pending() is None


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("mode", "drs"),
        ("max_workers", 2),
        ("root_snapshot_sha256", "0" * 64),
        ("executions", [f"{RUN}-practice-3-1", f"{RUN}-practice-3-0"]),
        ("executions", [f"{RUN}-practice-3-0", f"{RUN}-practice-3-0"]),
        ("executions", ["foreign-practice"]),
    ],
)
def test_old_mode_foreign_or_reordered_state_refuses_before_selection(field, bad):
    value = _wire(**{field: bad})
    with pytest.raises(BRSChildPolicyError, match="^rsi_python_brs_child_policy_"):
        preflight_native_brs_child(value)


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": 2},
        {"protocol": "lunar-rsi-python-brs-child-preflight-v0"},
        {"intents": [{"ordinal": 1, "episode_id": f"{RUN}-practice-3-0", "request_sha256": DIGEST}]},
        {"budget": _budget(practice_episodes=1)},
        {"budget": _budget(practice_episodes=1, consumed_episodes=2)},
        {"caps": {"attempts": MAX_BRS_CHILD_ATTEMPTS + 1, "candidates": 1,
                   "checkpoint_bytes": 1, "aggregate_bytes": 1}},
        {"caps": {"attempts": 1, "candidates": MAX_BRS_CHILD_CANDIDATES + 1,
                   "checkpoint_bytes": 1, "aggregate_bytes": 1}},
        {"caps": {"attempts": 1, "candidates": 1,
                   "checkpoint_bytes": MAX_BRS_CHILD_PREFLIGHT_BYTES + 1, "aggregate_bytes": 1}},
        {"caps": {"attempts": 1, "candidates": 1,
                   "checkpoint_bytes": 1, "aggregate_bytes": MAX_BRS_CHILD_AGGREGATE_BYTES + 1}},
    ],
)
def test_budget_ordinal_and_capacity_caps_are_fail_closed(change):
    value = _wire(**change)
    with pytest.raises(BRSChildPolicyError):
        preflight_native_brs_child(value)


def test_wire_is_canonical_bounded_and_duplicate_keys_are_rejected():
    value = _wire()
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    assert preflight_native_brs_child(raw).select_next_pending() is not None
    with pytest.raises(BRSChildPolicyError, match="noncanonical"):
        preflight_native_brs_child(json.dumps(value).encode())
    duplicate = b'{"schema_version":1,"schema_version":1}'
    with pytest.raises(BRSChildPolicyError, match="duplicate_key"):
        preflight_native_brs_child(duplicate)
    with pytest.raises(BRSChildPolicyError, match="bytes_exceeded"):
        preflight_native_brs_child(b" " * (MAX_BRS_CHILD_PREFLIGHT_BYTES + 1))


def test_mutable_subclasses_and_nested_depth_are_rejected_without_iteration():
    class HostileDict(dict):
        def items(self):
            raise AssertionError("caller mapping was iterated")

    value = HostileDict(_wire())
    with pytest.raises(BRSChildPolicyError, match="shape_invalid"):
        preflight_native_brs_child(value)
    nested = _wire()
    cursor = nested["intents"][0]
    for _ in range(40):
        cursor["nested"] = {}
        cursor = cursor["nested"]
    with pytest.raises(BRSChildPolicyError, match="shape_invalid"):
        preflight_native_brs_child(nested)


def test_pure_preflight_has_no_authority_or_external_effect_surface():
    preflight = preflight_native_brs_child(_wire())
    assert not hasattr(preflight, "ledger")
    assert not hasattr(preflight, "workspace")
    assert not hasattr(preflight, "claim")
    assert not hasattr(preflight, "token")
    assert preflight.select_next_pending().authority is False
