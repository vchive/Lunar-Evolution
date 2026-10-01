"""Charge holdout side effects to an existing durable learning run without refreshing limits."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import nullcontext
from typing import Any

from .rsi_budget import RSIRunBudget
from .rsi_callbacks import DurableCallbackJournal
from .rsi_learning import RSILearningError
from .rsi_store import RSILedger


class ParentRunBudget:
    def __init__(self, ledger: RSILedger, run_id: str) -> None:
        if type(run_id) is not str or not run_id.strip() or any(c in run_id for c in "\x00\r\n"):
            raise RSILearningError("rsi_parent_budget_identity_invalid")
        self.ledger, self.run_id = ledger, run_id

    def guard(self):
        return nullcontext() if self.ledger.controller_lock_held(self.run_id) else self.ledger.controller_lock(self.run_id)

    def _load(self) -> tuple[Any, str, dict[str, Any]]:
        history = self.ledger.history(self.run_id)
        journal = self.ledger.controller_checkpoint_history(self.run_id)
        if not history or history[-1].kind != "run" or not journal:
            raise RSILearningError("rsi_parent_budget_missing")
        try:
            initial = RSIRunBudget.load(history[0].payload["budget_state"])
        except (KeyError, TypeError, ValueError, RSILearningError) as exc:
            raise RSILearningError("rsi_parent_budget_checkpoint_corrupt") from exc
        previous_budget = initial.to_dict()
        previous_events: dict[str, Any] = {}
        for _digest, state in journal:
            try:
                if state["schema_version"] != "2" or state["run_id"] != self.run_id:
                    raise ValueError("legacy parent")
                budget = RSIRunBudget.load(state["budget_state"]).to_dict()
                events = state.get("external_budget_reservations", {})
                if not isinstance(events, dict) or budget["planned"] != initial.to_dict()["planned"]:
                    raise ValueError("planned drift")
                if any(budget["consumed"][key] < value for key, value in previous_budget["consumed"].items()):
                    raise ValueError("counter rollback")
                if any(events.get(key) != value for key, value in previous_events.items()):
                    raise ValueError("receipt rollback")
                totals = {"transfer_invocations": 0, "evaluator_invocations": 0, "unknown_retries": 0}
                for event_id, receipt in events.items():
                    if (type(event_id) is not str or len(event_id) != 64 or any(c not in "0123456789abcdef" for c in event_id)
                            or set(receipt) != {"binding_sha256", "kind"}
                            or type(receipt["binding_sha256"]) is not str or len(receipt["binding_sha256"]) != 64
                            or any(c not in "0123456789abcdef" for c in receipt["binding_sha256"])
                            or receipt["kind"] not in {"trial", "reconcile"}):
                        raise ValueError("receipt")
                    if receipt["kind"] == "trial":
                        totals["transfer_invocations"] += 1
                        totals["evaluator_invocations"] += 1
                    else:
                        totals["unknown_retries"] += 1
                if any(budget["consumed"][key] < value for key, value in totals.items()):
                    raise ValueError("underaccounting")
                added = {"transfer_invocations": 0, "evaluator_invocations": 0, "unknown_retries": 0}
                for event_id, receipt in events.items():
                    if event_id not in previous_events:
                        for counter in (("unknown_retries",) if receipt["kind"] == "reconcile" else ("transfer_invocations", "evaluator_invocations")):
                            added[counter] += 1
                if any(budget["consumed"][key] - previous_budget["consumed"][key] < value for key, value in added.items()):
                    raise ValueError("unaccounted append")
                previous_budget, previous_events = budget, events
            except (KeyError, TypeError, ValueError, RSILearningError) as exc:
                raise RSILearningError("rsi_parent_budget_checkpoint_corrupt") from exc
        return history[-1], journal[-1][0], journal[-1][1]

    def validate_history(self) -> None:
        """Read-only shared check for controller resume and external budget consumers."""
        with self.guard():
            self._load()

    def identity(self) -> dict[str, Any]:
        with self.guard():
            head, _digest, state = self._load()
            identity = self.ledger.database.stat()
            return {
                "run_id": self.run_id, "request_sha256": head.request_sha256,
                "ledger": str(self.ledger.database), "device": identity.st_dev, "inode": identity.st_ino,
                "planned_budget": RSIRunBudget.load(state["budget_state"]).to_dict()["planned"],
            }

    def reserve(self, scope: str, callback_id: str, binding: Mapping[str, Any], *, reconcile: bool = False) -> None:
        event_id = DurableCallbackJournal.digest({"scope": scope, "callback_id": callback_id, "reconcile": reconcile})
        receipt = {"binding_sha256": DurableCallbackJournal.digest(dict(binding)), "kind": "reconcile" if reconcile else "trial"}
        with self.guard():
            head, digest, state = self._load()
            events = state.setdefault("external_budget_reservations", {})
            if event_id in events:
                if events[event_id] != receipt:
                    raise RSILearningError("rsi_parent_budget_reservation_drift")
                return
            if not reconcile and (head.state in {"unknown", "cancelled", "budget_exhausted"} or state["status"] in {"unknown", "cancelled", "budget_exhausted"}):
                raise RSILearningError("rsi_parent_budget_unavailable")
            budget = RSIRunBudget.load(state["budget_state"])
            if reconcile:
                budget.reserve_unknown_reconcile_evidence()
            else:
                budget.reserve_stages(("transfer", "evaluator"))
            events[event_id] = receipt
            state["budget_state"] = budget.to_dict()
            self.ledger.write_controller_checkpoint(self.run_id, state, expected_sha256=digest)

    def check_dispatch(self) -> None:
        with self.guard():
            head, _digest, state = self._load()
            if head.state in {"unknown", "cancelled", "budget_exhausted"} or state["status"] in {"unknown", "cancelled", "budget_exhausted"}:
                raise RSILearningError("rsi_parent_budget_unavailable")
            RSIRunBudget.load(state["budget_state"]).check()

    @staticmethod
    def synchronize(state: dict[str, Any], persisted: Mapping[str, Any]) -> None:
        """Merge external charges into a still-live controller state without losing new work."""
        prior_events = persisted.get("external_budget_reservations", {})
        local_events = state.get("external_budget_reservations", {})
        if any(prior_events.get(key) != value for key, value in local_events.items()):
            raise RSILearningError("rsi_parent_budget_reservation_drift")
        if prior_events == local_events:
            return
        local = RSIRunBudget.load(state["budget_state"]).to_dict()
        remote = RSIRunBudget.load(persisted["budget_state"]).to_dict()
        if local["planned"] != remote["planned"]:
            raise RSILearningError("rsi_parent_budget_checkpoint_corrupt")
        for event_id, receipt in prior_events.items():
            if event_id in local_events:
                continue
            counters: Sequence[str] = ("unknown_retries",) if receipt["kind"] == "reconcile" else ("transfer_invocations", "evaluator_invocations")
            for counter in counters:
                local["consumed"][counter] += 1
        local["remaining"] = {
            counter: None if remote["planned"]["max_" + counter] is None else remote["planned"]["max_" + counter] - used
            for counter, used in local["consumed"].items()
        }
        state["budget_state"] = RSIRunBudget.load(local).to_dict()
        state["external_budget_reservations"] = dict(prior_events)
