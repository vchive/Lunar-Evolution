"""Read-only validation of governed BRS side-effect budget receipts.

The original BRS reservation charges the fixed wave budget (one charge per
reserved episode).  A governed generation may subsequently run a local
regression campaign.  Those trial and explicit-reconcile charges are recorded
in the parent journal as immutable receipts.  This module joins every receipt
back to the real generation, campaign and callback journals before accepting
the resulting counters.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .rsi_budget import RSIRunBudget
from .rsi_callbacks import DurableCallbackJournal
from .rsi_learning import RSILearningError
from .rsi_regression_campaign import DurableRegressionCampaign

_COUNTERS = (
    "practice_rounds", "target_attempts", "practice_episodes", "solver_invocations",
    "unknown_retries", "evaluator_invocations", "verifier_invocations", "transfer_invocations",
)
_BASE_COUNTERS = ("practice_rounds", "practice_episodes", "solver_invocations",
                  "evaluator_invocations", "verifier_invocations")


def _fail(reason: str) -> None:
    raise RSILearningError("rsi_brs_reserved_finalization_budget_" + reason)


def _digest(value: object) -> str:
    return DurableCallbackJournal.digest(value)


def _event_id(scope: str, callback_id: str, reconcile: bool) -> str:
    return _digest({"scope": scope, "callback_id": callback_id, "reconcile": reconcile})


def _hex(value: object) -> bool:
    return (type(value) is str and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def _receipt_shape(event_id: object, receipt: object) -> bool:
    return (_hex(event_id) and isinstance(receipt, Mapping)
            and set(receipt) == {"binding_sha256", "kind"}
            and _hex(receipt.get("binding_sha256"))
            and receipt.get("kind") in {"trial", "reconcile"})


def _campaign_receipts(controller: Any, generation_ids: set[str]) -> dict[str, dict[str, str]]:
    """Derive receipt identities from the actual coordinator/campaign journals."""
    coordinator = getattr(controller, "memory_admission_gate", None)
    if coordinator is None or not hasattr(coordinator, "inspect"):
        _fail("coordinator_missing")
    expected: dict[str, dict[str, str]] = {}
    for generation_id in sorted(generation_ids):
        try:
            checkpoint = coordinator.inspect(generation_id)
        except Exception as exc:  # the coordinator must reject malformed history
            raise RSILearningError("rsi_brs_reserved_finalization_budget_generation_invalid") from exc
        if checkpoint is None:
            _fail("generation_missing")
        _generation_head, generation_state = checkpoint
        try:
            request = coordinator._request(generation_state)
            # Importing the concrete runner here avoids a controller import cycle.
            from .rsi_generation_campaign import GenerationCampaignRunner

            admission_id = GenerationCampaignRunner.admission_id(request)
            campaign = DurableRegressionCampaign(controller.ledger)
            loaded = campaign._load(campaign.scope(admission_id))
        except (KeyError, TypeError, ValueError, RSILearningError) as exc:
            raise RSILearningError("rsi_brs_reserved_finalization_budget_campaign_invalid") from exc
        if loaded is None:
            continue
        _campaign_head, campaign_state = loaded
        intent = campaign_state.get("intent")
        if not isinstance(intent, Mapping):
            _fail("campaign_invalid")
        try:
            bindings = dict(campaign._trials(intent))
            reservations = campaign_state["reservations"]
            reconciliations = campaign_state["reconciliations"]
            if (type(reservations) is not list or type(reconciliations) is not dict
                    or len(set(reservations)) != len(reservations)):
                raise ValueError("reservation shape")
            scope = campaign.scope(admission_id)
            for callback_id in reservations:
                if callback_id not in bindings:
                    raise ValueError("foreign callback")
                callback = campaign.callbacks.inspect(scope, callback_id)
                if callback is None:
                    raise ValueError("callback missing")
                _callback_head, callback_state = callback
                binding = bindings[callback_id]
                event_id = _event_id(scope, callback_id, False)
                expected[event_id] = {
                    "binding_sha256": _digest(binding), "kind": "trial",
                }
                if callback_state["status"] == "completed" and callback_state["reconciliation"] is not None:
                    evidence = callback_state["reconciliation"]
                    reconcile_binding = {"result": callback_state["result"], "evidence": evidence}
                    if reconciliations.get(callback_id) != _digest(reconcile_binding):
                        raise ValueError("reconciliation binding")
                    reconcile_id = _event_id(scope, callback_id, True)
                    expected[reconcile_id] = {
                        "binding_sha256": _digest(reconcile_binding), "kind": "reconcile",
                    }
            if any(callback_id not in reservations for callback_id in reconciliations):
                raise ValueError("foreign reconciliation")
            if campaign_state["phase"] == "terminal" and len(reservations) != len(bindings):
                raise ValueError("terminal campaign incomplete")
        except (KeyError, TypeError, ValueError, RSILearningError) as exc:
            raise RSILearningError("rsi_brs_reserved_finalization_budget_campaign_invalid") from exc
    return expected


def validate_reserved_brs_finalization_budget(controller, scheduling, history) -> None:
    """Validate governed budget counters and receipts without mutating state.

    ``scheduling`` is the first complete original reservation root.  Its fixed
    N episode charges and planned deadline are immutable.  Later roots may add
    only receipts that can be independently observed in the genuine
    coordinator, generation campaign and callback journals.
    """
    if (controller is None or not isinstance(scheduling, Mapping)
            or type(history) is not list or not history):
        _fail("input_invalid")
    try:
        schedule_index = next(index for index, (_head, body) in enumerate(history)
                              if body == scheduling)
    except StopIteration:
        _fail("scheduling_missing")
    try:
        original = RSIRunBudget.load(scheduling["budget_state"]).to_dict()
        domain = tuple(scheduling["executions"])
        if not domain or len(set(domain)) != len(domain):
            raise ValueError("domain")
        n = len(domain)
        # The complete reservation itself must contain exactly the fixed base N
        # charges; transfer and reconcile counters start at zero.
        consumed = original["consumed"]
        for counter in _COUNTERS:
            expected = n if counter in _BASE_COUNTERS else 0
            if consumed[counter] != expected:
                raise ValueError("base counters")
        planned = original["planned"]
        expected_events: dict[str, dict[str, str]] = {}
        seen_generation_ids: set[str] = set()
        previous_events: dict[str, dict[str, str]] = {}
        previous_generations: dict[str, str] = {}
        original_executions = {
            key: controller._deserialize_execution(wire)
            for key, wire in scheduling["executions"].items()
        }
        from .rsi_controller import _record_digest

        for _head, body in history[schedule_index:]:
            state_budget = RSIRunBudget.load(body["budget_state"]).to_dict()
            if state_budget["planned"] != planned:
                raise ValueError("planned drift")
            events = body.get("external_budget_reservations", {})
            if not isinstance(events, dict):
                raise TypeError("receipt shape")
            generations = body.get("generations", {})
            if not isinstance(generations, dict):
                raise TypeError("generation shape")
            if not set(previous_generations).issubset(generations):
                raise ValueError("generation rollback")
            for key, entry in generations.items():
                if key not in domain:
                    raise ValueError("foreign generation")
                if key not in original_executions or not original_executions[key].passed:
                    raise ValueError("failed generation")
                if (not isinstance(entry, Mapping) or type(entry.get("generation_id")) is not str
                        or not entry["generation_id"].strip()):
                    raise ValueError("generation entry")
                expected_generation_id = "controller-generation:" + _record_digest(
                    {"run": scheduling["run_id"], "episode": key},
                )
                if entry["generation_id"] != expected_generation_id:
                    raise ValueError("generation identity")
                if key in previous_generations and previous_generations[key] != entry["generation_id"]:
                    raise ValueError("generation identity drift")
                previous_generations[key] = entry["generation_id"]
                seen_generation_ids.add(entry["generation_id"])
            # Gather from all generation journals seen so far.  This allows a
            # pending/reconciled generation to contribute receipts before its
            # final admission status is written to the parent root.
            expected_events = _campaign_receipts(controller, seen_generation_ids)
            for event_id, receipt in events.items():
                if not _receipt_shape(event_id, receipt) or expected_events.get(event_id) != receipt:
                    raise ValueError("foreign receipt")
            totals = {counter: 0 for counter in _COUNTERS}
            for receipt in events.values():
                if receipt["kind"] == "trial":
                    totals["transfer_invocations"] += 1
                    totals["evaluator_invocations"] += 1
                else:
                    totals["unknown_retries"] += 1
            for counter in _COUNTERS:
                expected = (n if counter in _BASE_COUNTERS else 0) + totals[counter]
                if state_budget["consumed"].get(counter) != expected:
                    raise ValueError("counter mismatch")
            # A receipt is append-only; a later root cannot erase one while
            # retaining a hash-valid checkpoint.
            if not set(previous_events).issubset(events):
                raise ValueError("receipt rollback")
            previous_events = dict(events)
        if set(previous_events) != set(expected_events):
            raise ValueError("missing receipt")
        # A completed governed generation must account for every actual trial;
        # an unfinished generation may legitimately retain started callbacks.
    except RSILearningError:
        raise
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise RSILearningError("rsi_brs_reserved_finalization_budget_invalid") from exc


__all__ = ["validate_reserved_brs_finalization_budget"]
