"""Pure owner/worker handoff gates; no controller, ledger, files or workers."""

from __future__ import annotations

import json
from dataclasses import replace
from threading import get_ident

import pytest

from lunar_evolution.rsi_python_brs_child_policy import (
    BRS_CHILD_POLICY_PROTOCOL,
    BRS_CHILD_POLICY_SCHEMA_VERSION,
    BRSChildPolicyError,
    BRSNativeChildPreflight,
    preflight_native_brs_child,
)
from lunar_evolution.rsi_python_brs_handoff import (
    HANDOFF_PROTOCOL,
    BRSChildHandoffContext,
    BRSChildHandoffError,
    BRSSelectedChildHandoff,
    validate_brs_child_handoff,
)

RUN = "handoff-run"
ROOT = "1" * 64
DIGEST0 = "2" * 64
DIGEST1 = "3" * 64


class _CallbackTrap:
    def __init__(self):
        self.calls = 0

    def __eq__(self, _other):
        self.calls += 1
        raise AssertionError("equality callback executed")

    def __str__(self):
        self.calls += 1
        raise AssertionError("string callback executed")

    def __format__(self, _format_spec):
        self.calls += 1
        raise AssertionError("format callback executed")


CONTEXT = BRSChildHandoffContext(
    controller_id="controller-1",
    ledger_id="ledger-1",
    workspace_id="workspace-1",
    sidecar_id="sidecar-1",
    owner_thread_id=get_ident(),
    head_sha256="4" * 64,
    state_sha256="5" * 64,
    source_sha256="6" * 64,
    policy_sha256="7" * 64,
    execution_control_sha256="8" * 64,
)


def _budget():
    names = (
        "practice_rounds", "target_attempts", "practice_episodes", "solver_invocations",
        "unknown_retries", "evaluator_invocations", "verifier_invocations", "transfer_invocations",
    )
    return {
        "planned": {name: (2 if name != "transfer_invocations" else 0) for name in names},
        "consumed": {name: (1 if name in {"practice_episodes", "solver_invocations"} else 0)
                     for name in names},
    }


def _wire(*, wave=2, executions=None):
    return {
        "schema_version": BRS_CHILD_POLICY_SCHEMA_VERSION,
        "protocol": BRS_CHILD_POLICY_PROTOCOL,
        "run_id": RUN,
        "mode": "brs",
        "wave": wave,
        "max_workers": 1,
        "root_snapshot_sha256": ROOT,
        "intents": [
            {"ordinal": 0, "episode_id": f"{RUN}-practice-{wave}-0", "request_sha256": DIGEST0},
            {"ordinal": 1, "episode_id": f"{RUN}-practice-{wave}-1", "request_sha256": DIGEST1},
        ],
        "executions": [f"{RUN}-practice-{wave}-0"] if executions is None else executions,
        "budget": _budget(),
        "caps": {"attempts": 1, "candidates": 1, "checkpoint_bytes": 4096, "aggregate_bytes": 2048},
    }


def _preflight(value=None) -> BRSNativeChildPreflight:
    return preflight_native_brs_child(_wire() if value is None else value)


def _handoff(*, selection=None, nonce="A" * 32):
    selection = _preflight().select_next_pending() if selection is None else selection
    return BRSSelectedChildHandoff.from_selection(selection, CONTEXT, lease_nonce=nonce)


def _validate(handoff=None, *, preflight=None, current=CONTEXT, consumed=()):
    return validate_brs_child_handoff(
        _handoff() if handoff is None else handoff,
        _preflight() if preflight is None else preflight,
        current,
        consumed_nonces=consumed,
    )


def test_handoff_is_canonical_detached_and_bound_to_preflight_selection():
    preflight = _preflight()
    selection = preflight.select_next_pending()
    handoff = _handoff(selection=selection)
    wire = json.loads(handoff.canonical_bytes)
    assert wire["protocol"] == HANDOFF_PROTOCOL
    assert wire["run_id"] == RUN
    assert wire["wave"] == 2
    assert wire["ordinal"] == 1
    assert wire["episode_id"] == f"{RUN}-practice-2-1"
    assert wire["request_sha256"] == DIGEST1
    assert wire["root_snapshot_sha256"] == ROOT
    assert wire["max_workers"] == 1
    assert set(wire) == {
        "protocol", "run_id", "wave", "ordinal", "episode_id", "request_sha256",
        "root_snapshot_sha256", "selection_sha256", "controller_id", "ledger_id",
        "workspace_id", "sidecar_id", "owner_thread_id", "head_sha256", "state_sha256",
        "source_sha256", "policy_sha256", "execution_control_sha256", "max_workers", "lease_nonce",
    }
    assert _validate(handoff, preflight=preflight) == handoff.sha256
    assert not hasattr(handoff, "controller")
    assert not hasattr(handoff, "ledger")
    assert not hasattr(handoff, "callback")
    assert not hasattr(handoff, "claim")
    assert not hasattr(handoff, "path")


def test_nonce_is_fresh_and_gate_refuses_a_consumed_nonce():
    selection = _preflight().select_next_pending()
    first = BRSSelectedChildHandoff.from_selection(selection, CONTEXT)
    second = BRSSelectedChildHandoff.from_selection(selection, CONTEXT)
    assert first.lease_nonce != second.lease_nonce
    assert _validate(first) == first.sha256
    with pytest.raises(BRSChildHandoffError, match="handoff_nonce_replayed"):
        _validate(first, consumed=(first.lease_nonce,))


def test_gate_rejects_owner_thread_drift_and_malformed_nonce_state():
    handoff = _handoff()
    wrong_thread_context = replace(CONTEXT, owner_thread_id=CONTEXT.owner_thread_id + 1)
    wrong_thread_handoff = BRSSelectedChildHandoff.from_selection(
        _preflight().select_next_pending(), wrong_thread_context, lease_nonce="B" * 32,
    )
    with pytest.raises(BRSChildHandoffError, match="handoff_owner_thread_drift"):
        _validate(wrong_thread_handoff)
    with pytest.raises(BRSChildHandoffError, match="handoff_nonce_state_invalid"):
        _validate(handoff, consumed=[handoff.lease_nonce])


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("controller_id", "controller-2"),
        ("ledger_id", "ledger-2"),
        ("workspace_id", "workspace-2"),
        ("sidecar_id", "sidecar-2"),
        ("head_sha256", "9" * 64),
        ("state_sha256", "a" * 64),
        ("source_sha256", "b" * 64),
        ("policy_sha256", "c" * 64),
        ("execution_control_sha256", "d" * 64),
    ],
)
def test_gate_rejects_owner_head_state_source_policy_and_control_drift(field, value):
    handoff = _handoff()
    current = replace(CONTEXT, **{field: value})
    with pytest.raises(BRSChildHandoffError, match="handoff_owner_or_fingerprint_drift"):
        _validate(handoff, current=current)


def test_handoff_and_context_refuse_parallel_worker_width():
    with pytest.raises(BRSChildHandoffError, match="handoff_max_workers_invalid"):
        replace(CONTEXT, max_workers=2)
    with pytest.raises(BRSChildHandoffError, match="handoff_max_workers_invalid"):
        replace(_handoff(), max_workers=2)


def test_gate_rejects_selection_or_preflight_drift_and_exhausted_wave():
    handoff = _handoff()
    different_wave = _preflight(_wire(wave=3))
    with pytest.raises(BRSChildHandoffError, match="handoff_selection_drift"):
        _validate(handoff, preflight=different_wave)
    complete = _wire(executions=[f"{RUN}-practice-2-0", f"{RUN}-practice-2-1"])
    complete["budget"]["consumed"]["practice_episodes"] = 2
    complete["budget"]["consumed"]["solver_invocations"] = 2
    complete["caps"]["attempts"] = 2
    complete = _preflight(complete)
    with pytest.raises(BRSChildHandoffError, match="handoff_selection_exhausted"):
        _validate(handoff, preflight=complete)


def test_gate_accepts_only_exact_builtin_handoff_and_context_values():
    class HandoffChild(BRSSelectedChildHandoff):
        pass

    with pytest.raises(BRSChildHandoffError, match="handoff_shape_invalid"):
        validate_brs_child_handoff(HandoffChild(**_handoff().to_dict()), _preflight(), CONTEXT)
    with pytest.raises(BRSChildHandoffError, match="handoff_context_invalid"):
        validate_brs_child_handoff(_handoff(), _preflight(), object())


def test_preflight_input_remains_the_existing_pure_budget_selection_gate():
    bad = _wire()
    bad["max_workers"] = 2
    with pytest.raises(BRSChildPolicyError, match="max_workers_invalid"):
        preflight_native_brs_child(bad)


@pytest.mark.parametrize("field", ["protocol", "episode_id", "owner_thread_id", "lease_nonce", "request_sha256"])
def test_injected_handoff_fields_are_rejected_before_callbacks(field):
    handoff = _handoff()
    trap = _CallbackTrap()
    object.__setattr__(handoff, field, trap)
    with pytest.raises(BRSChildHandoffError):
        _validate(handoff)
    assert trap.calls == 0


def test_injected_context_field_is_rejected_before_callbacks():
    current = CONTEXT
    trap = _CallbackTrap()
    object.__setattr__(current, "controller_id", trap)
    try:
        with pytest.raises(BRSChildHandoffError):
            _validate(current=current)
        assert trap.calls == 0
    finally:
        object.__setattr__(current, "controller_id", "controller-1")


def test_injected_consumed_nonce_is_rejected_without_equality_callback():
    handoff = _handoff()
    trap = _CallbackTrap()
    with pytest.raises(BRSChildHandoffError, match="handoff_nonce_state_invalid"):
        _validate(handoff, consumed=(trap,))
    assert trap.calls == 0


def test_nonce_size_bounds_are_preserved():
    selection = _preflight().select_next_pending()
    accepted = BRSSelectedChildHandoff.from_selection(selection, CONTEXT, lease_nonce="N" * 128)
    assert len(accepted.lease_nonce) == 128
    for nonce in ("N" * 31, "N" * 129):
        with pytest.raises(BRSChildHandoffError, match="handoff_lease_nonce_invalid"):
            BRSSelectedChildHandoff.from_selection(selection, CONTEXT, lease_nonce=nonce)
