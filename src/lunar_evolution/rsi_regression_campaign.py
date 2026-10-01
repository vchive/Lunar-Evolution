"""Durable local holdout trials with conservative, immutable budget reservations."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from contextlib import nullcontext
from typing import Any

from .candidate_evaluation_spec import canonical_json
from .rsi_budget import RSIRunBudget
from .rsi_callbacks import DurableCallbackJournal
from .rsi_identity import RSIIdentityError, component_fingerprint
from .rsi_learning import EMPTY_MEMORY_SNAPSHOT, MemorySnapshot, RSILearningError
from .rsi_parent_budget import ParentRunBudget
from .rsi_store import RSILedger
from .rsi_transfer_regression import (
    RegressionPolicy,
    TransferObservation,
    TransferRegressionReport,
    TransferRegressionSuite,
    TransferTask,
)

MAX_REGRESSION_TRIALS = 1024


def _runner_digest(runner: object) -> str:
    try:
        return component_fingerprint(runner)
    except RSIIdentityError as exc:
        raise RSILearningError("rsi_regression_runner_fingerprint_invalid") from exc


class DurableRegressionCampaign:
    """Compose a frozen regression suite with the existing callback and budget protocols.

    Callback code is trusted local code. Started calls without a result are quarantined;
    this object neither retries them nor authenticates an external completion receipt.
    """

    def __init__(self, ledger: RSILedger) -> None:
        self.ledger = ledger
        self.callbacks = DurableCallbackJournal(ledger)

    @staticmethod
    def scope(admission_id: str) -> str:
        if type(admission_id) is not str or not admission_id.strip() or any(
            char in admission_id for char in "\x00\r\n"
        ):
            raise RSILearningError("rsi_regression_admission_invalid")
        return "rsi-regression:" + DurableCallbackJournal.digest({"admission_id": admission_id})

    @staticmethod
    def _trials(intent: Mapping[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        count = 3 * intent["policy"]["repetitions"] * len(intent["manifest"])
        if count > MAX_REGRESSION_TRIALS:
            raise RSILearningError("rsi_regression_trial_limit")
        intent_sha256 = DurableCallbackJournal.digest(intent)
        trials = []
        for arm in ("no_memory", "old_memory", "current_memory"):
            for repetition in range(intent["policy"]["repetitions"]):
                for index, task in enumerate(intent["manifest"]):
                    callback_id = f"trial:{arm}:{repetition}:{index}"
                    trials.append((callback_id, {
                        "intent_sha256": intent_sha256,
                        "arm": arm, "task": task, "repetition": repetition,
                        "memory_snapshot_sha256": intent["memories"][arm],
                    }))
        return trials

    @staticmethod
    def _validate_result(result: Mapping[str, Any]) -> None:
        try:
            parsed = TransferRegressionSuite._normalise_observation(result)
            if parsed.to_dict() != result:
                raise ValueError("noncanonical observation")
        except (TypeError, ValueError, RSILearningError) as exc:
            raise RSILearningError("rsi_regression_observation_invalid") from exc

    def _load(self, scope: str) -> tuple[str, dict[str, Any]] | None:
        history = self.ledger.controller_checkpoint_history(scope)
        previous: dict[str, Any] | None = None
        for _digest, state in history:
            try:
                if set(state) != {
                    "protocol", "intent", "intent_sha256", "budget_state", "reservations",
                    "phase", "report_sha256", "reconciliations",
                } or state["protocol"] not in {"rsi-regression-campaign-v1", "rsi-regression-campaign-v2"}:
                    raise ValueError("shape")
                intent = state["intent"]
                fields = {
                    "admission_id", "initial_record_sha256", "manifest", "policy", "memories",
                    "controller_pins", "runner_fingerprint", "planned_budget",
                }
                if state["protocol"] == "rsi-regression-campaign-v2":
                    fields.add("parent_budget")
                    if not isinstance(intent.get("parent_budget"), dict):
                        raise ValueError("parent budget")
                if set(intent) != fields or self.scope(intent["admission_id"]) != scope:
                    raise ValueError("intent")
                if state["intent_sha256"] != DurableCallbackJournal.digest(intent):
                    raise ValueError("digest")
                policy = RegressionPolicy(**intent["policy"])
                tasks = tuple(TransferTask(**task) for task in intent["manifest"])
                if (policy.to_dict() != intent["policy"] or [task.to_dict() for task in tasks] != intent["manifest"]
                        or type(intent["memories"]) is not dict or type(intent["controller_pins"]) is not dict):
                    raise ValueError("noncanonical intent")
                TransferRegressionSuite._validate_tasks(tasks, policy)
                for value in (*intent["memories"].values(), intent["runner_fingerprint"], intent["initial_record_sha256"]):
                    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                        raise ValueError("pin")
                if set(intent["memories"]) != {"no_memory", "old_memory", "current_memory"}:
                    raise ValueError("memories")
                budget = RSIRunBudget.load(state["budget_state"])
                if budget.to_dict()["planned"] != intent["planned_budget"]:
                    raise ValueError("budget drift")
                reservations = state["reservations"]
                expected = [callback for callback, _binding in self._trials(intent)]
                if type(reservations) is not list or reservations != expected[:len(reservations)]:
                    raise ValueError("reservation order")
                consumed = budget.to_dict()["consumed"]
                reconciliations = state["reconciliations"]
                if type(reconciliations) is not dict or any(
                    callback_id not in reservations or type(pin) is not str or len(pin) != 64
                    or any(c not in "0123456789abcdef" for c in pin)
                    for callback_id, pin in reconciliations.items()
                ):
                    raise ValueError("reconciliation")
                expected_counts = {
                    "transfer_invocations": len(reservations), "evaluator_invocations": len(reservations),
                    "unknown_retries": len(reconciliations),
                }
                if any(used != expected_counts.get(counter, 0) for counter, used in consumed.items()):
                    raise ValueError("counter binding")
                if state["phase"] not in {"running", "terminal", "budget_exhausted"}:
                    raise ValueError("phase")
                report = state["report_sha256"]
                if state["phase"] == "terminal":
                    if len(reservations) != len(expected) or type(report) is not str or len(report) != 64 or any(
                        c not in "0123456789abcdef" for c in report
                    ):
                        raise ValueError("terminal")
                elif report is not None:
                    raise ValueError("report")
                if previous is None:
                    if reservations or reconciliations or state["phase"] != "running":
                        raise ValueError("initial")
                elif (
                    previous["phase"] != "running" or previous["intent"] != intent
                    or reservations[:len(previous["reservations"])] != previous["reservations"]
                    or len(reservations) - len(previous["reservations"]) not in {0, 1}
                    or any(reconciliations.get(key) != pin for key, pin in previous["reconciliations"].items())
                    or len(reconciliations) - len(previous["reconciliations"]) not in {0, 1}
                ):
                    raise ValueError("transition")
                previous = state
            except (KeyError, TypeError, ValueError, RSILearningError) as exc:
                raise RSILearningError("rsi_regression_checkpoint_corrupt") from exc
        return history[-1] if history else None

    def inspect(self, admission_id: str) -> tuple[str, dict[str, Any]] | None:
        return self._load(self.scope(admission_id))

    def reconcile_trial(
        self, admission_id: str, callback_id: str, *, expected_checkpoint_sha256: str,
        result: Mapping[str, Any], evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Register an observed result without rerunning a trial or refunding its charge."""
        scope = self.scope(admission_id)
        initial = self._load(scope)
        parent = None
        if initial is not None and "parent_budget" in initial[1]["intent"]:
            parent = ParentRunBudget(self.ledger, initial[1]["intent"]["parent_budget"]["run_id"])
        with (parent.guard() if parent is not None else nullcontext()), self.ledger.controller_lock(scope):
            checkpoint = self._load(scope)
            if checkpoint is None:
                raise RSILearningError("rsi_regression_not_started")
            campaign_digest, state = checkpoint
            bindings = dict(self._trials(state["intent"]))
            if callback_id not in state["reservations"] or callback_id not in bindings:
                raise RSILearningError("rsi_regression_trial_not_reserved")
            callback = self.callbacks.inspect(scope, callback_id)
            if callback is None:
                raise RSILearningError("rsi_callback_not_started")
            callback_digest, callback_state = callback
            if type(expected_checkpoint_sha256) is not str or len(expected_checkpoint_sha256) != 64 or expected_checkpoint_sha256 not in {
                callback_digest, callback_state["started_checkpoint_sha256"],
            }:
                raise RSILearningError("rsi_callback_checkpoint_conflict")
            if callback_state["binding"] != bindings[callback_id]:
                raise RSILearningError("rsi_callback_binding_drift")
            if callback_state["status"] == "completed" and callback_state["reconciliation"] is None:
                raise RSILearningError("rsi_callback_reconcile_conflict")
            self._validate_result(result)
            clean_evidence = self.callbacks.validate_evidence(bindings[callback_id], result, evidence)
            reservation_pin = self.callbacks.digest({"result": dict(result), "evidence": clean_evidence})
            reservations = state["reconciliations"]
            if callback_id in reservations:
                if reservations[callback_id] != reservation_pin:
                    raise RSILearningError("rsi_callback_reconcile_conflict")
            else:
                if state["phase"] != "running":
                    raise RSILearningError("rsi_regression_reconcile_not_required")
                run_budget = RSIRunBudget.load(state["budget_state"])
                run_budget.reserve_unknown_reconcile_evidence()
                if parent is not None:
                    if parent.identity() != state["intent"]["parent_budget"]:
                        raise RSILearningError("rsi_parent_budget_identity_drift")
                    parent.reserve(scope, callback_id, {"result": dict(result), "evidence": clean_evidence}, reconcile=True)
                reservations[callback_id] = reservation_pin
                state["budget_state"] = run_budget.to_dict()
                self.ledger.write_controller_checkpoint(scope, state, expected_sha256=campaign_digest)
            return self.callbacks.reconcile(
                scope, callback_id, expected_checkpoint_sha256=expected_checkpoint_sha256,
                binding=bindings[callback_id], result=result, evidence=clean_evidence,
                validate=self._validate_result,
            )

    def run(
        self, *, admission_id: str, initial_record_sha256: str,
        tasks: Sequence[TransferTask], old_memory: MemorySnapshot, current_memory: MemorySnapshot,
        policy: RegressionPolicy, runner: Callable[..., Any], controller_pins: Mapping[str, Any],
        check_components: Callable[[], None], budget: Mapping[str, Any] | None = None,
        parent_budget: ParentRunBudget | None = None,
    ) -> TransferRegressionReport:
        if parent_budget is not None and (not isinstance(parent_budget, ParentRunBudget) or parent_budget.ledger is not self.ledger):
            raise RSILearningError("rsi_parent_budget_ledger_mismatch")
        scope = self.scope(admission_id)
        policy = RegressionPolicy(**policy.to_dict())
        manifest = tuple(TransferTask(**task.to_dict()) for task in TransferRegressionSuite._validate_tasks(tasks, policy))
        if 3 * policy.repetitions * len(manifest) > MAX_REGRESSION_TRIALS:
            raise RSILearningError("rsi_regression_trial_limit")
        runner_pin = _runner_digest(runner)
        planned_budget = RSIRunBudget.create(budget)
        intent = {
            "admission_id": admission_id, "initial_record_sha256": initial_record_sha256,
            "manifest": [task.to_dict() for task in manifest], "policy": policy.to_dict(),
            "memories": {"no_memory": EMPTY_MEMORY_SNAPSHOT.digest(),
                         "old_memory": old_memory.digest(), "current_memory": current_memory.digest()},
            "controller_pins": dict(controller_pins), "runner_fingerprint": runner_pin,
            "planned_budget": planned_budget.to_dict()["planned"],
        }
        if parent_budget is not None:
            intent["parent_budget"] = parent_budget.identity()
        intent_sha256 = DurableCallbackJournal.digest(intent)
        # Store immutable JSON projections, never nested caller-owned aliases.
        intent = json.loads(canonical_json(intent, maximum=1024 * 1024))
        controller_pin_digest = DurableCallbackJournal.digest(intent["controller_pins"])
        with (parent_budget.guard() if parent_budget is not None else nullcontext()), self.ledger.controller_lock(scope):
            previous = self._load(scope)
            if previous is None:
                checkpoint_sha256 = None
                state = {
                    "protocol": "rsi-regression-campaign-v2" if parent_budget is not None else "rsi-regression-campaign-v1", "intent": intent,
                    "intent_sha256": intent_sha256, "budget_state": planned_budget.to_dict(),
                    "reservations": [], "reconciliations": {}, "phase": "running", "report_sha256": None,
                }
            else:
                checkpoint_sha256, state = previous
                if state["intent_sha256"] != intent_sha256:
                    raise RSILearningError("rsi_regression_intent_drift")
            run_budget = RSIRunBudget.load(state["budget_state"])

            def checkpoint() -> None:
                nonlocal checkpoint_sha256
                state["budget_state"] = run_budget.to_dict()
                checkpoint_sha256 = self.ledger.write_controller_checkpoint(
                    scope, state, expected_sha256=checkpoint_sha256,
                )

            if previous is None:
                checkpoint()
            if state["phase"] == "budget_exhausted":
                raise RSILearningError("rsi_budget_exhausted")
            trial_bindings = self._trials(intent)
            position = 0

            def check_live_components() -> None:
                check_components()
                if DurableCallbackJournal.digest(dict(controller_pins)) != controller_pin_digest:
                    raise RSILearningError("rsi_regression_controller_drift")

            def trial(task: TransferTask, memory: MemorySnapshot, repetition: int) -> TransferObservation:
                nonlocal position
                callback_id, binding = trial_bindings[position]
                position += 1
                if (
                    task.to_dict() != binding["task"] or repetition != binding["repetition"]
                    or memory.digest() != binding["memory_snapshot_sha256"]
                ):
                    raise RSILearningError("rsi_regression_trial_drift")
                check_live_components()
                if _runner_digest(runner) != runner_pin:
                    raise RSILearningError("rsi_regression_runner_drift")

                def reserve() -> None:
                    if state["phase"] != "running":
                        raise RSILearningError("rsi_regression_checkpoint_corrupt")
                    try:
                        run_budget.check()
                        if parent_budget is not None:
                            parent_budget.check_dispatch()
                        if callback_id not in state["reservations"]:
                            run_budget.check(counter="transfer_invocations")
                            run_budget.check(counter="evaluator_invocations")
                            if parent_budget is not None:
                                if parent_budget.identity() != intent["parent_budget"]:
                                    raise RSILearningError("rsi_parent_budget_identity_drift")
                                parent_budget.reserve(scope, callback_id, binding)
                            run_budget.reserve_stages(("transfer", "evaluator"))
                            state["reservations"].append(callback_id)
                            checkpoint()
                    except RSILearningError as exc:
                        if str(exc) == "rsi_budget_exhausted":
                            state["phase"] = "budget_exhausted"
                            checkpoint()
                        raise

                def call() -> Mapping[str, Any]:
                    try:
                        run_budget.check()
                        if parent_budget is not None:
                            parent_budget.check_dispatch()
                    except RSILearningError as exc:
                        if str(exc) == "rsi_budget_exhausted":
                            state["phase"] = "budget_exhausted"
                            checkpoint()
                        raise
                    observed = TransferRegressionSuite._normalise_observation(runner(task, memory, repetition))
                    check_live_components()
                    if _runner_digest(runner) != runner_pin:
                        raise RSILearningError("rsi_regression_runner_drift")
                    if (task.to_dict() != binding["task"] or policy.to_dict() != intent["policy"]
                            or memory.digest() != binding["memory_snapshot_sha256"]):
                        raise RSILearningError("rsi_regression_trial_drift")
                    return observed.to_dict()

                cached = self.callbacks.inspect(scope, callback_id)
                if cached is not None and callback_id not in state["reservations"]:
                    raise RSILearningError("rsi_regression_checkpoint_corrupt")
                if state["phase"] == "terminal" and (cached is None or cached[1]["status"] != "completed"):
                    raise RSILearningError("rsi_regression_checkpoint_corrupt")
                value = self.callbacks.invoke(
                    scope, callback_id, binding=binding, call=call,
                    validate=self._validate_result, before_call=reserve,
                )
                return TransferRegressionSuite._normalise_observation(value)

            report = TransferRegressionSuite(policy=policy).run(
                manifest, old_memory=old_memory, current_memory=current_memory, runner=trial,
            )
            check_live_components()
            if state["phase"] == "terminal":
                if report.report_sha256 != state["report_sha256"]:
                    raise RSILearningError("rsi_regression_report_drift")
                return report
            try:
                run_budget.check()
                if parent_budget is not None:
                    parent_budget.check_dispatch()
            except RSILearningError as exc:
                if str(exc) == "rsi_budget_exhausted":
                    state["phase"] = "budget_exhausted"
                    checkpoint()
                raise
            state.update(phase="terminal", report_sha256=report.report_sha256)
            checkpoint()
            return report
