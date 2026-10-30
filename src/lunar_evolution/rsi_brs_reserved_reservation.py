"""Read the original full reservation from an observed controller journal.

The earliest full reservation is derived from the same bounded ledger snapshot as
the current attempt traces. A caller cannot nominate a later checkpoint as a new
budget baseline. These facts grant no dispatch, owner or reconciliation authority.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .candidate_evaluation_spec import canonical_json, strict_json
from .rsi_brs_reserved_ledger import (
    BRSReservedLedgerObservation,
    _rows,
    read_reserved_brs_completion_ledger,
)
from .rsi_brs_reserved_wave import project_reserved_brs_wave
from .rsi_budget import RSIRunBudget
from .rsi_learning import RSILearningError
from .rsi_store import RSILedger

_MAX_BYTES = 128 * 1024
_CHARGED = {"practice_rounds", "practice_episodes", "solver_invocations",
            "evaluator_invocations", "verifier_invocations"}
_FIXED = ("run_id", "mode", "plan", "pins", "root_snapshot", "memory_snapshot",
          "producer_checkpoint_binding", "producer_brs_checkpoint_policy",
          "producer_child_execution", "producer_child_execution_policy",
          "producer_multi_episode_publication", "producer_multi_episode_publication_policy",
          "producer_known_rejection", "producer_staging_policy")


def _fail(code: str) -> None:
    raise RSILearningError("rsi_brs_reserved_reservation_" + code)


def _raw(value) -> bytes:
    return canonical_json(value, maximum=_MAX_BYTES)


@dataclass(frozen=True, slots=True)
class BRSReservedReservationObservation:
    """Actual journal head and state digest are intentionally separate facts."""

    ledger: BRSReservedLedgerObservation
    original_checkpoint_sha256: str
    original_state_sha256: str
    original_state_bytes: bytes

    def original_state(self) -> dict:
        return strict_json(self.original_state_bytes, maximum=_MAX_BYTES)


def read_reserved_brs_reservation(
    ledger: RSILedger, *, run_id: str, episode_ids: tuple[str, ...],
    expected_checkpoint_sha256: str,
) -> BRSReservedReservationObservation:
    """Observe the original complete reservation under the existing run lease."""
    if type(ledger) is not RSILedger:
        _fail("ledger_invalid")
    RSILedger._assert_controller_lock(ledger, run_id)
    result = _observe_reserved_brs_reservation(ledger, run_id=run_id, episode_ids=episode_ids,
        expected_checkpoint_sha256=expected_checkpoint_sha256)
    RSILedger._assert_controller_lock(ledger, run_id)
    return result


def read_reserved_brs_completion_reservation(
    ledger: RSILedger, *, run_id: str, episode_ids: tuple[str, ...],
    expected_checkpoint_sha256: str,
) -> BRSReservedReservationObservation:
    """Read-only worker evidence of reservation; never a selection or owner grant."""
    return _observe_reserved_brs_reservation(ledger, run_id=run_id, episode_ids=episode_ids,
        expected_checkpoint_sha256=expected_checkpoint_sha256)


def read_reserved_brs_finalization_reservation(
    ledger: RSILedger, *, run_id: str, episode_ids: tuple[str, ...],
    expected_checkpoint_sha256: str,
) -> BRSReservedReservationObservation:
    """Descriptive complete-wave history; never usable for another live selection.

    Effective memory and terminal status may change only after every original
    execution exists. The separate finalization validator proves those deltas;
    live and worker-completion readers retain their original strict M0 gate.
    """
    if type(ledger) is not RSILedger:
        _fail("ledger_invalid")
    RSILedger._assert_controller_lock(ledger, run_id)
    result = _observe_reserved_brs_reservation(ledger, run_id=run_id, episode_ids=episode_ids,
        expected_checkpoint_sha256=expected_checkpoint_sha256, finalization=True)
    if set(strict_json(result.ledger.checkpoint_bytes, maximum=_MAX_BYTES)["executions"]) != set(episode_ids):
        _fail("finalization_incomplete")
    RSILedger._assert_controller_lock(ledger, run_id)
    return result


def _observe_reserved_brs_reservation(
    ledger: RSILedger, *, run_id: str, episode_ids: tuple[str, ...],
    expected_checkpoint_sha256: str, finalization: bool = False,
) -> BRSReservedReservationObservation:
    """Derive the first complete reservation, without changing progress or budget.

    All pre-dispatch journal states must retain
    the original plan/policy/M0/deadline and monotonically reserve its ordered
    intents. Every later checkpoint retains that exact full reservation. Attempt
    traces, including orphan admissions and historical fences, remain available
    in ``ledger``; none is discarded as part of finding the baseline.
    """
    observation = read_reserved_brs_completion_ledger(
        ledger, run_id=run_id, episode_ids=episode_ids,
        expected_checkpoint_sha256=expected_checkpoint_sha256,
    )
    try:
        rows = _rows(observation.raw_snapshot)["rsi_controller_journal"]
        states = tuple(strict_json(row["payload"], maximum=_MAX_BYTES) for row in rows)
        first = states[0]
        planned = RSIRunBudget.load(first["budget_state"]).to_dict()["planned"]
        run = next(row for row in _rows(observation.raw_snapshot)["rsi_records"]
                   if row["logical_id"] == run_id and row["revision"] == 0)
        run_state = strict_json(run["payload"], maximum=_MAX_BYTES)
        if (run_state.get("mode") != "brs" or run_state.get("plan") != first.get("plan")
                or run_state.get("memory_snapshot") != first.get("root_snapshot")
                or any(run_state.get(key) != first.get("pins", {}).get(key) for key in (
                    "contract_sha256", "evaluator_sha256", "environment_sha256", "solver_id"))
                or run_state.get("budget_state") != first.get("budget_state")
                or any(_raw(run_state.get(key)) != _raw(first.get(key)) for key in _FIXED
                       if key.startswith("producer_"))):
            _fail("run_origin_drift")
        previous_count, original_index, scheduling_complete = 0, None, False
        # These bytes belong only to the freshly decoded first state in this
        # history walk. Freeze each field at its original first comparison,
        # after the current value is encoded, to retain refusal/short-circuit
        # order. Every later state's value is still encoded independently.
        first_fixed_bytes: dict[str, bytes] = {}

        def original_fixed_bytes(key: str) -> bytes:
            if key not in first_fixed_bytes:
                first_fixed_bytes[key] = _raw(first.get(key))
            return first_fixed_bytes[key]

        for index, state in enumerate(states):
            if (state.get("status") != "running"
                    and not (finalization and scheduling_complete and state.get("status") == "completed")):
                _fail("control_changed")
            if any(type(state.get(key, {})) is not dict for key in (
                "executions", "python_admission_refs", "brs_reconcile_obligations",
            )):
                _fail("attempt_shape_invalid")
            if any(_raw(state.get(key)) != original_fixed_bytes(key) for key in _FIXED
                   if not (finalization and scheduling_complete and key == "memory_snapshot")):
                _fail("original_drift")
            if scheduling_complete and set(state["executions"]) != set(episode_ids):
                _fail("finalization_incomplete")
            intents = state.get("intents")
            if type(intents) is not dict:
                _fail("intent_drift")
            count = len(intents)
            if (set(intents) != set(episode_ids[:count]) or count < previous_count
                    or (index == 0 and count != 0) or count > previous_count + 1
                    or count > len(episode_ids)):
                _fail("reservation_order_drift")
            budget = RSIRunBudget.load(state["budget_state"]).to_dict()
            extra = {name: 0 for name in budget["consumed"]}
            events = state.get("external_budget_reservations", {})
            if events:
                if not (finalization and scheduling_complete and type(events) is dict):
                    _fail("budget_drift")
                # These are only descriptive totals. Finalization independently
                # joins each receipt to its original generation/campaign binding.
                for event in events.values():
                    if type(event) is not dict or event.get("kind") not in {"trial", "reconcile"}:
                        _fail("budget_drift")
                    for name in (("transfer_invocations", "evaluator_invocations")
                                 if event["kind"] == "trial" else ("unknown_retries",)):
                        extra[name] += 1
            if (_raw(budget["planned"]) != _raw(planned)
                    or any(value != (count if name in _CHARGED else 0) + extra[name]
                           for name, value in budget["consumed"].items())):
                _fail("budget_drift")
            if index and any(_raw(intents[key]) != _raw(states[index - 1]["intents"][key])
                             for key in states[index - 1]["intents"]):
                _fail("intent_drift")
            if original_index is None:
                if any(state.get(key, {}) for key in (
                    "executions", "python_admission_refs", "brs_reconcile_obligations",
                )):
                    _fail("attempt_before_reservation")
                if count == len(episode_ids):
                    original_index = index
            if (finalization and original_index is not None
                    and set(state["executions"]) == set(episode_ids)):
                scheduling_complete = True
            previous_count = count
        if original_index is None:
            _fail("full_reservation_required")
        original = states[original_index]
        # Reuse the exact real controller/request/budget shape gate, with no
        # invented terminal facts. Empty traces here validate the original state
        # only, and are never substituted for the current ledger observations.
        traces = {key: {"episode": None, "claim": None, "result": None,
                        "material_sha256s": [], "reference_sha256": None,
                        "obligation_sha256": None} for key in episode_ids}
        project_reserved_brs_wave(
            original, original, attempt_traces=traces, settled_prefix=(),
            retained_materials=(), candidate_count=0,
        )
        raw = _raw(original)
        result = BRSReservedReservationObservation(
            observation, rows[original_index]["checkpoint_sha256"],
            hashlib.sha256(raw).hexdigest(), raw,
        )
        repeated = read_reserved_brs_completion_ledger(ledger, run_id=run_id, episode_ids=episode_ids,
            expected_checkpoint_sha256=expected_checkpoint_sha256)
        if repeated != observation:
            _fail("observation_changed")
        return result
    except RSILearningError:
        raise
    except (KeyError, TypeError, ValueError, StopIteration, OverflowError, RecursionError) as exc:
        raise RSILearningError("rsi_brs_reserved_reservation_history_invalid") from exc
