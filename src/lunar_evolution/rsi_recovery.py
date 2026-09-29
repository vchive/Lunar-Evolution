"""Durable RSI controller state machine independent of solver execution backends.

A launch intent is committed before calling the gateway. An intent without a terminal result is
uncertain work, never permission to launch again. Reconciliation supplies evidence for the same
immutable request, then resumes the original controller schedule.
"""

from __future__ import annotations

import hashlib
import inspect
import threading
import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any

from .candidate_evaluation_spec import canonical_json
from .rsi_budget import RSIRunBudget
from .rsi_gateway import RSIMemoryStore, SolverRequest, SolverResult
from .rsi_learning import (
    MemorySnapshot,
    PracticeEpisode,
    RSILearningError,
    VerifierCheck,
    VerifierDecision,
)
from .rsi_stage_accounting import (
    DurableStageAccounting,
    stage_accounting,
    validate_evaluator_intent,
    validate_stage_history,
    validate_stage_state,
)
from .rsi_usage import MAX_USAGE_VALUE, RSIUsageReceipt, aggregate_usage, usage_receipt_from


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value, maximum=8 * 1024 * 1024)).hexdigest()


def fingerprint(component: object) -> str:
    supplied = getattr(component, "fingerprint", None)
    if callable(supplied):
        result = supplied()
        if type(result) is not str or len(result) != 64 or any(c not in "0123456789abcdef" for c in result):
            raise RSILearningError("rsi_component_fingerprint_invalid")
        return result
    if inspect.isfunction(component):
        try:
            source = inspect.getsource(component)
        except (OSError, TypeError):
            source = None
        return digest({
            "function": f"{component.__module__}.{component.__qualname__}", "source": source,
            "bytecode": component.__code__.co_code.hex(),
            "constants": [repr(value) for value in component.__code__.co_consts],
            "defaults": component.__defaults__, "kwdefaults": component.__kwdefaults__,
            "closure": [cell.cell_contents for cell in (component.__closure__ or ())],
        })
    cls = type(component)
    try:
        source = inspect.getsource(cls)
    except (OSError, TypeError):
        source = cls.__qualname__
    return digest({"type": f"{cls.__module__}.{cls.__qualname__}", "source": source,
                   "template": getattr(component, "_template", None)})


class DurableLearningRun:
    def __init__(self, controller: Any, run_id: str) -> None:
        if controller.ledger is None:
            raise RSILearningError("rsi_resume_requires_ledger")
        self.controller = controller
        self.ledger = controller.ledger
        self.run_id = run_id
        self.version: str | None = None
        self.state: dict[str, Any] = {}
        self.mutex = threading.RLock()
        self.validated_evidence: set[str] = set()
        self._wall_checkpoint_ns = time.monotonic_ns()

    def _save(self) -> None:
        usage = self.state.get("usage_state")
        if not isinstance(usage, dict):
            raise RSILearningError("rsi_usage_checkpoint_invalid")
        elapsed_ns = time.monotonic_ns() - self._wall_checkpoint_ns
        elapsed_ms = max(0, elapsed_ns // 1_000_000)
        previous = usage.get("controller_wall_elapsed_ms")
        if type(previous) is not int or previous < 0 or previous > MAX_USAGE_VALUE - elapsed_ms:
            raise RSILearningError("rsi_usage_checkpoint_invalid")
        usage["controller_wall_elapsed_ms"] = previous + elapsed_ms
        self._refresh_run_usage()
        try:
            self.version = self.ledger.write_controller_checkpoint(
                self.run_id, self.state, expected_sha256=self.version,
            )
        except Exception:
            usage["controller_wall_elapsed_ms"] = previous
            self._refresh_run_usage()
            raise
        self._wall_checkpoint_ns = time.monotonic_ns()

    def _refresh_run_usage(self) -> None:
        usage = self.state.get("usage_state")
        if not isinstance(usage, dict):
            raise RSILearningError("rsi_usage_checkpoint_invalid")
        elapsed = usage.get("controller_wall_elapsed_ms")
        if type(elapsed) is not int or elapsed < 0 or elapsed > MAX_USAGE_VALUE:
            raise RSILearningError("rsi_usage_checkpoint_invalid")
        receipts: list[RSIUsageReceipt | None] = []
        for entry in self.state.get("episodes", {}).values():
            sidecar = entry.get("usage")
            receipts.append(RSIUsageReceipt.from_dict(sidecar) if sidecar is not None else None)
        usage["aggregate"] = aggregate_usage(receipts, wall_elapsed_ms=elapsed).to_dict()

    def _usage_binding(self, request: SolverRequest, result: Mapping[str, Any], usage: Mapping[str, Any]) -> str:
        return digest({
            "request_sha256": request.digest(),
            "result_sha256": digest(result),
            "usage": dict(usage),
        })

    def _check_usage_checkpoint(self, entry: Mapping[str, Any], request: SolverRequest) -> None:
        if "usage" not in entry or "usage_digest" not in entry or "usage_binding" not in entry:
            raise RSILearningError("rsi_usage_checkpoint_invalid")
        sidecar = entry["usage"]
        usage_digest = entry["usage_digest"]
        binding = entry["usage_binding"]
        if sidecar is None:
            if usage_digest is not None or binding is not None:
                raise RSILearningError("rsi_usage_checkpoint_invalid")
            return
        result = entry.get("result")
        if not isinstance(result, Mapping) or type(binding) is not str:
            raise RSILearningError("rsi_usage_checkpoint_invalid")
        receipt = RSIUsageReceipt.from_dict(sidecar)
        if usage_digest != digest(receipt.to_dict()):
            raise RSILearningError("rsi_usage_checkpoint_invalid")
        if binding != self._usage_binding(request, result, receipt.to_dict()):
            raise RSILearningError("rsi_usage_checkpoint_invalid")

    def _check_run_usage_checkpoint(self) -> None:
        usage = self.state.get("usage_state")
        if not isinstance(usage, Mapping) or set(usage) != {"controller_wall_elapsed_ms", "aggregate"}:
            raise RSILearningError("rsi_usage_checkpoint_invalid")
        elapsed = usage["controller_wall_elapsed_ms"]
        if type(elapsed) is not int or elapsed < 0 or elapsed > MAX_USAGE_VALUE:
            raise RSILearningError("rsi_usage_checkpoint_invalid")
        receipts: list[RSIUsageReceipt | None] = []
        for entry in self.state["episodes"].values():
            sidecar = entry.get("usage")
            receipts.append(RSIUsageReceipt.from_dict(sidecar) if sidecar is not None else None)
        expected = aggregate_usage(receipts, wall_elapsed_ms=elapsed).to_dict()
        if usage["aggregate"] != expected:
            raise RSILearningError("rsi_usage_checkpoint_invalid")

    def _config(self, mode: str, values: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "mode": mode,
            **dict(values),
            "solver_settings": dict(self.controller.solver_settings),
            "actor_fingerprint": self.controller.actor_fingerprint,
            "gateway_fingerprint": fingerprint(self.controller.gateway),
            "verifier_fingerprint": fingerprint(self.controller.verifier),
            "curriculum_fingerprint": fingerprint(self.controller.curriculum),
            "curriculum_history_fingerprint": (
                self.controller.curriculum.history_fingerprint()
                if callable(getattr(self.controller.curriculum, "history_fingerprint", None))
                else None
            ),
            "target_judge_fingerprint": fingerprint(self.controller.target_judge),
            "memory_policy": (
                "candidate_only"
                if self.controller.memory_governance is not None
                else "verifier_snapshot"
            ),
        }

    def _check_components(self, expected: Mapping[str, Any] | None = None) -> None:
        self._check_checkpoint_history()
        config = self.state["config"]
        budget = RSIRunBudget.load(self.state.get("budget_state"))
        budget.assert_matches(config.get("budget"))
        self._check_stage_support(budget)
        current = self._config(config["mode"], {})
        for key in (
            "solver_settings",
            "actor_fingerprint",
            "gateway_fingerprint",
            "verifier_fingerprint",
            "curriculum_fingerprint",
            "curriculum_history_fingerprint",
            "target_judge_fingerprint",
            "memory_policy",
        ):
            if current[key] != config[key]:
                raise RSILearningError(f"rsi_resume_{key}_drift")
        for key, value in (expected or {}).items():
            if value is not None and config.get(key) != value:
                raise RSILearningError(f"rsi_resume_{key}_drift")
        snapshot = MemorySnapshot.from_dict(self.state["memory_snapshot"])
        initial = MemorySnapshot.from_dict(self.state["initial_memory_snapshot"])
        if config["memory_policy"] == "candidate_only" and (snapshot.items or initial.items):
            raise RSILearningError("rsi_memory_trusted_promotion_unavailable")
        supplied = self.controller.snapshot.digest()
        if (
            supplied not in {initial.digest(), snapshot.digest()}
            and self.controller._explicit_memory_store
        ):
            raise RSILearningError("rsi_resume_memory_snapshot_drift")
        self.controller.memory_store = RSIMemoryStore(snapshot)
        durable_episode_ids = set(self.ledger.episode_ids_for_run(self.run_id))
        checkpoint_episode_ids = set(self.state["episodes"])
        planned_without_ledger = {
            episode_id
            for episode_id, entry in self.state["episodes"].items()
            if entry.get("stage") == "planned" and episode_id not in durable_episode_ids
        }
        if (
            durable_episode_ids - checkpoint_episode_ids
            or checkpoint_episode_ids - durable_episode_ids - planned_without_ledger
        ):
            raise RSILearningError("rsi_resume_episode_checkpoint_gap")
        for episode_id, entry in self.state["episodes"].items():
            self._check_episode_checkpoint_shape(entry)
            request = SolverRequest.from_dict(entry["request"])
            self._check_usage_checkpoint(entry, request)
            if type(entry.get("budget_reserved")) is not bool:
                raise RSILearningError("rsi_budget_checkpoint_invalid")
            episode = PracticeEpisode.from_dict(entry["running_episode"])
            depth, ancestry = self._episode_lineage(episode_id, entry)
            if entry.get("depth") != depth or entry.get("ancestry") != list(ancestry):
                raise RSILearningError("rsi_budget_checkpoint_invalid")
            if entry["stage"] == "planned" and self.ledger.get(request.episode_id) is not None:
                raise RSILearningError("rsi_resume_episode_stage_invalid")
            if (
                request.digest() != episode.request_sha256
                or episode.run_id != self.run_id
                or request.solver_id != config["solver_id"]
                or dict(request.solver_settings) != config["solver_settings"]
            ):
                raise RSILearningError("rsi_resume_request_drift")
            for name in ("contract_sha256", "evaluator_sha256", "environment_sha256"):
                if getattr(request, name) != config[name] or getattr(episode, name) != config[name]:
                    raise RSILearningError(f"rsi_resume_{name}_drift")
            if entry.get("result") is not None:
                result = SolverResult.from_dict(entry["result"])
                self._check_result(request, result)
                if entry.get("episode") is not None:
                    episode = PracticeEpisode.from_dict(entry["episode"])
                    if (
                        episode.request_sha256 != result.request_sha256
                        or episode.episode_id != result.episode_id
                        or episode.status != result.status
                        or episode.trace_events != result.trace_events
                        or episode.run_id != self.run_id
                        or episode.memory_snapshot_sha256 != request.memory_snapshot_sha256
                        or episode.solver_fingerprint
                        != digest(
                            {"solver_id": request.solver_id, "settings": request.solver_settings}
                        )
                    ):
                        raise RSILearningError("rsi_resume_episode_result_mismatch")
                    for name in (
                        "candidate_receipt_sha256",
                        "execution_receipt_sha256",
                        "official_evaluation_receipt_sha256",
                        "trace_digest",
                        "candidate_source_sha256",
                        "dependency_sha256",
                        "actor_fingerprint",
                    ):
                        if getattr(episode, name) != getattr(result, name):
                            raise RSILearningError("rsi_resume_episode_result_mismatch")
            self._check_reconciliation_checkpoint(entry, request)
            self._check_verifier_reservations(entry, request)
        stage_counts = self._check_external_stages()
        from .rsi_shared_transfer import validate_transfers
        transfer_counts = validate_transfers(self)
        for name in stage_counts:
            stage_counts[name] += transfer_counts[name]
        reserved = [entry for entry in self.state["episodes"].values() if entry["budget_reserved"]]
        practices = [
            entry
            for entry in reserved
            if PracticeEpisode.from_dict(entry["running_episode"]).episode_kind == "practice"
        ]
        reconciliations = [
            entry
            for entry in self.state["episodes"].values()
            if entry.get("reconciliation") is not None
        ]
        consumed = budget.state["consumed"]
        if (
            consumed["solver_invocations"] != len(reserved) + transfer_counts["solver_invocations"]
            or consumed["practice_episodes"] != len(practices)
            or consumed["unknown_retries"] != len(reconciliations)
            or consumed["verifier_invocations"]
            != sum(len(entry["verifier_invocations"]) for entry in self.state["episodes"].values())
            + transfer_counts["verifier"]
            or consumed["evaluator_invocations"] != stage_counts["evaluator"]
            or consumed["transfer_invocations"] != stage_counts["transfer"]
        ):
            raise RSILearningError("rsi_budget_checkpoint_invalid")
        self._check_run_usage_checkpoint()
        self._validate_memory()

    def _check_checkpoint_history(self) -> None:
        """Reject checkpoint rewrites that erase durable stage reservations or counters."""
        history = self.ledger.controller_checkpoint_history(self.run_id)
        if not history or history[-1][0] != self.version:
            raise RSILearningError("rsi_controller_checkpoint_invalid")
        previous: Mapping[str, Any] | None = None
        for _, current in history:
            if not isinstance(current, Mapping):
                raise RSILearningError("rsi_controller_checkpoint_invalid")
            if previous is not None:
                from .rsi_shared_transfer import validate_transfer_history
                validate_transfer_history(previous, current)
                validate_stage_history(previous.get("stage_accounting"), current.get("stage_accounting"))
                previous_episodes = previous.get("episodes", {})
                current_episodes = current.get("episodes", {})
                if not isinstance(previous_episodes, Mapping) or not isinstance(current_episodes, Mapping):
                    raise RSILearningError("rsi_controller_checkpoint_invalid")
                for episode_id, old_entry in previous_episodes.items():
                    if not isinstance(old_entry, Mapping):
                        raise RSILearningError("rsi_controller_checkpoint_invalid")
                    old_intents = old_entry.get("verifier_invocations")
                    if old_intents is None:
                        continue  # pre-stage-counter checkpoints are migrated by RSIRunBudget.load
                    if not isinstance(old_intents, list):
                        raise RSILearningError("rsi_budget_checkpoint_invalid")
                    new_entry = current_episodes.get(episode_id)
                    if not isinstance(new_entry, Mapping):
                        if old_intents:
                            raise RSILearningError("rsi_resume_episode_checkpoint_gap")
                        continue
                    new_intents = new_entry.get("verifier_invocations")
                    if not isinstance(new_intents, list) or len(new_intents) < len(old_intents):
                        raise RSILearningError("rsi_budget_checkpoint_invalid")
                    for old_intent, new_intent in zip(old_intents, new_intents):
                        if not isinstance(old_intent, Mapping) or not isinstance(new_intent, Mapping):
                            raise RSILearningError("rsi_budget_checkpoint_invalid")
                        identity = (
                            "request_sha256", "result_sha256", "episode_record_sha256",
                            "verifier_fingerprint", "decision_kind",
                        )
                        if any(old_intent.get(name) != new_intent.get(name) for name in identity):
                            raise RSILearningError("rsi_budget_checkpoint_invalid")
                        for field in ("decision", "reconciliation"):
                            old_value = old_intent.get(field)
                            new_value = new_intent.get(field)
                            if old_value is not None and new_value != old_value:
                                raise RSILearningError("rsi_budget_checkpoint_invalid")
                old_budget = previous.get("budget_state")
                new_budget = current.get("budget_state")
                if isinstance(old_budget, Mapping) and isinstance(new_budget, Mapping):
                    old_planned = old_budget.get("planned")
                    new_planned = new_budget.get("planned")
                    if (isinstance(old_planned, Mapping) and isinstance(new_planned, Mapping)
                            and old_planned != new_planned):
                        raise RSILearningError("rsi_budget_checkpoint_invalid")
                    old_consumed = old_budget.get("consumed")
                    new_consumed = new_budget.get("consumed")
                    if isinstance(old_consumed, Mapping) and isinstance(new_consumed, Mapping):
                        for name, old_value in old_consumed.items():
                            new_value = new_consumed.get(name)
                            if type(old_value) is int and (type(new_value) is not int or new_value < old_value):
                                raise RSILearningError("rsi_budget_checkpoint_invalid")
            previous = current

    def _check_stage_support(self, budget: RSIRunBudget, config: Mapping | None = None) -> None:
        # Only adapters declaring the pre-execution hook can accept finite evaluator limits.
        if budget.state["planned"]["max_evaluator_invocations"] is not None:
            for component in (self.controller.gateway, self.controller.verifier):
                if "evaluator" not in getattr(component, "stage_budget_accounting", ()):
                    raise RSILearningError("rsi_budget_evaluator_accounting_unavailable")
        # DRS/BRS itself has no implicit transfer phase. Transfer budgets are accepted only
        # by the explicit controller.compare_transfer API, so a run cannot accidentally spend
        # transfer quota in a normal learning loop.
        configured = self.state.get("config", {}) if config is None else config
        if (budget.state["planned"]["max_transfer_invocations"] is not None
                and configured.get("enable_transfer_accounting") is not True):
            raise RSILearningError("rsi_budget_transfer_accounting_unavailable")

    def _stage_scope(self, request: SolverRequest, phase: str):
        accounting = DurableStageAccounting(
            self.state.setdefault("stage_accounting", {"invocations": []}),
            self.state["budget_state"], self._save, lock=self.mutex,
        )
        return stage_accounting(accounting, {
            "run_id": self.run_id, "episode_id": request.episode_id,
            "request_sha256": request.digest(), "phase": phase,
        })

    def _check_external_stages(self) -> dict[str, int]:
        state = self.state.get("stage_accounting", {"invocations": []})
        counts = validate_stage_state(state)
        if counts["verifier"] or counts["transfer"]:
            raise RSILearningError("rsi_stage_checkpoint_invalid")
        for row in state["invocations"]:
            owner = row["identity"].get("owner")
            if not isinstance(owner, Mapping) or set(owner) != {
                "run_id", "episode_id", "request_sha256", "phase",
            } or owner["run_id"] != self.run_id or owner["phase"] not in {"gateway", "verifier"}:
                raise RSILearningError("rsi_stage_checkpoint_invalid")
            entry = self.state["episodes"].get(owner["episode_id"])
            if entry is None or owner["request_sha256"] != digest(entry["request"]):
                raise RSILearningError("rsi_stage_checkpoint_invalid")
            if owner["phase"] == "verifier" and not entry["verifier_invocations"]:
                raise RSILearningError("rsi_stage_checkpoint_invalid")
            validate_evaluator_intent(row, evaluator_sha256=self.state["config"]["evaluator_sha256"])
            if row["evidence"] is not None and entry.get("result") is not None:
                result = entry["result"]
                if owner["phase"] == "gateway" and result["status"] == "completed" and (
                    row["evidence"]["receipt_sha256"] != result["official_evaluation_receipt_sha256"]
                ):
                    raise RSILearningError("rsi_stage_evaluator_binding_invalid")
        return counts

    @staticmethod
    def _verifier_decision(raw: Mapping[str, Any]) -> VerifierDecision:
        return VerifierDecision(
            **{
                **raw,
                "checks": tuple(VerifierCheck(**check) for check in raw["checks"]),
            }
        )

    def _check_verifier_reservations(
        self, entry: Mapping[str, Any], request: SolverRequest
    ) -> None:
        reservations = entry.get("verifier_invocations")
        if not isinstance(reservations, list):
            raise RSILearningError("rsi_budget_checkpoint_invalid")
        results = {}
        if entry.get("result") is not None:
            results[digest(entry["result"])] = SolverResult.from_dict(entry["result"])
        reconciliation = entry.get("reconciliation")
        if reconciliation is not None and reconciliation["prior_result"] is not None:
            prior = reconciliation["prior_result"]
            results[digest(prior)] = SolverResult.from_dict(prior)
        history = self.ledger.history(request.episode_id)
        seen = set()
        current = self._current_verifier_intent(entry)
        for intent in reservations:
            if not isinstance(intent, Mapping) or set(intent) != {
                "request_sha256",
                "result_sha256",
                "episode_record_sha256",
                "verifier_fingerprint",
                "decision_kind",
                "decision",
                "reconciliation",
            }:
                raise RSILearningError("rsi_budget_checkpoint_invalid")
            result_digest = intent["result_sha256"]
            if (
                type(result_digest) is not str
                or result_digest in seen
                or result_digest not in results
            ):
                raise RSILearningError("rsi_budget_checkpoint_invalid")
            seen.add(result_digest)
            result = results[result_digest]
            canonical = next(
                (
                    row
                    for row in history
                    if row.payload.get("record_sha256") == intent["episode_record_sha256"]
                ),
                None,
            )
            if canonical is None:
                raise RSILearningError("rsi_budget_checkpoint_invalid")
            episode = PracticeEpisode.from_dict(canonical.payload)
            if (
                intent["request_sha256"] != request.digest()
                or intent["verifier_fingerprint"] != self.state["config"]["verifier_fingerprint"]
                or episode.request_sha256 != request.digest()
                or episode.episode_id != request.episode_id
                or episode.status != result.status
                or episode.verifier is not None
                or intent["decision_kind"]
                != ("completion" if result.status == "completed" else "diagnostic")
            ):
                raise RSILearningError("rsi_budget_checkpoint_invalid")
            for name in (
                "candidate_receipt_sha256",
                "execution_receipt_sha256",
                "official_evaluation_receipt_sha256",
                "trace_digest",
                "trace_events",
                "candidate_source_sha256",
                "dependency_sha256",
                "actor_fingerprint",
            ):
                if getattr(episode, name) != getattr(result, name):
                    raise RSILearningError("rsi_budget_checkpoint_invalid")
            if intent["decision"] is not None:
                try:
                    decision = self._verifier_decision(intent["decision"])
                except (RSILearningError, KeyError, TypeError) as exc:
                    raise RSILearningError("rsi_budget_checkpoint_invalid") from exc
                if decision.episode_id != request.episode_id:
                    raise RSILearningError("rsi_budget_checkpoint_invalid")
            reconciliation = intent["reconciliation"]
            if reconciliation is not None:
                if (
                    not isinstance(reconciliation, Mapping)
                    or set(reconciliation)
                    != {
                        "expected_record_sha256",
                        "intent_sha256",
                        "decision_sha256",
                    }
                    or intent["decision"] is None
                ):
                    raise RSILearningError("rsi_budget_checkpoint_invalid")
                pending = {**intent, "decision": None, "reconciliation": None}
                if (
                    reconciliation["intent_sha256"] != digest(pending)
                    or reconciliation["decision_sha256"] != digest(intent["decision"])
                    or not any(
                        row.record_sha256 == reconciliation["expected_record_sha256"]
                        and row.payload.get("record_sha256") == intent["episode_record_sha256"]
                        for row in history
                    )
                ):
                    raise RSILearningError("rsi_budget_checkpoint_invalid")
            if intent is current:
                key = (
                    "verifier_decision"
                    if intent["decision_kind"] == "completion"
                    else "diagnostic_verifier"
                )
                if entry.get(key) != intent["decision"]:
                    raise RSILearningError("rsi_budget_checkpoint_invalid")
        for key in ("verifier_decision", "diagnostic_verifier"):
            if entry.get(key) is not None and (
                current is None or current["decision"] != entry[key]
            ):
                raise RSILearningError("rsi_budget_checkpoint_invalid")
        raw_episode = entry.get("episode")
        if (
            raw_episode is not None
            and raw_episode.get("verifier") is not None
            and (current is None or current["decision"] != raw_episode["verifier"])
        ):
            raise RSILearningError("rsi_budget_checkpoint_invalid")
        if history and results:
            canonical = PracticeEpisode.from_dict(history[-1].payload)
            if canonical.verifier is not None and (
                current is None or current["decision"] != canonical.verifier.to_dict()
            ):
                raise RSILearningError("rsi_budget_checkpoint_invalid")

    @staticmethod
    def _current_verifier_intent(entry: Mapping[str, Any]) -> dict[str, Any] | None:
        result = entry.get("result")
        if result is None:
            return None
        result_digest = digest(result)
        for intent in entry.get("verifier_invocations", []):
            if isinstance(intent, dict) and intent.get("result_sha256") == result_digest:
                return intent
        return None

    def _verify(
        self,
        entry: dict[str, Any],
        episode: PracticeEpisode,
        request: SolverRequest,
        result: SolverResult,
        *,
        allow_invocation: bool,
    ) -> VerifierDecision | None:
        intent = self._current_verifier_intent(entry)
        if intent is not None:
            # An intent without a retained decision may already have executed. Resume must
            # quarantine it; only a saved decision grants permission to continue.
            return (
                None if intent["decision"] is None else self._verifier_decision(intent["decision"])
            )
        if not allow_invocation:
            return None
        budget = RSIRunBudget.load(self.state["budget_state"])
        budget.reserve_stage("verifier")
        self.state["budget_state"] = budget.state
        intent = {
            "request_sha256": request.digest(),
            "result_sha256": digest(result.to_dict()),
            "episode_record_sha256": episode.record_sha256,
            "verifier_fingerprint": self.state["config"]["verifier_fingerprint"],
            "decision_kind": "completion" if episode.status == "completed" else "diagnostic",
            "decision": None,
            "reconciliation": None,
        }
        entry["verifier_invocations"].append(intent)
        self._save()
        self.ledger._assert_controller_lock(self.run_id)
        with self._stage_scope(request, "verifier"):
            decision = self.controller.verifier.verify(episode, request, result)
        intent["decision"] = decision.to_dict()
        key = (
            "verifier_decision"
            if intent["decision_kind"] == "completion"
            else "diagnostic_verifier"
        )
        entry[key] = intent["decision"]
        self._save()
        return decision

    def reconcile_verifier(
        self,
        episode_id: str,
        decision: VerifierDecision,
        *,
        expected_record_sha256: str,
        expected_intent_sha256: str,
    ):
        """Adopt an independently reopened decision without executing the verifier again."""
        with self.ledger.controller_lock(self.run_id):
            self._load()
            entry = self.state["episodes"].get(episode_id)
            if entry is None:
                raise RSILearningError("rsi_reconcile_episode_missing")
            head = self.ledger.get(episode_id)
            if head is None or head.record_sha256 != expected_record_sha256:
                raise RSILearningError("rsi_record_parent_conflict")
            intent = self._current_verifier_intent(entry)
            if intent is None:
                raise RSILearningError("rsi_verifier_reconcile_intent_missing")
            if not isinstance(decision, VerifierDecision):
                raise RSILearningError("rsi_verifier_reconcile_decision_invalid")
            pending_intent = {**intent, "decision": None, "reconciliation": None}
            intent_pin = (
                intent["reconciliation"]["intent_sha256"]
                if intent["reconciliation"] is not None
                else digest(pending_intent)
            )
            if intent_pin != expected_intent_sha256:
                raise RSILearningError("rsi_verifier_reconcile_intent_conflict")
            if intent["decision"] is not None:
                if intent["decision"] != decision.to_dict():
                    raise RSILearningError("rsi_verifier_reconcile_decision_conflict")
                return self._continue()
            if self.state["status"] in {"completed", "failed", "cancelled", "budget_exhausted"}:
                raise RSILearningError("rsi_verifier_reconcile_state_invalid")
            request = SolverRequest.from_dict(entry["request"])
            result = SolverResult.from_dict(entry["result"])
            episode = PracticeEpisode.from_dict(entry["episode"])
            if (
                decision.episode_id != episode_id
                or episode.record_sha256 != intent["episode_record_sha256"]
                or head.payload != episode.to_record_dict()
            ):
                raise RSILearningError("rsi_verifier_reconcile_decision_invalid")
            for name in (
                "contract_sha256",
                "evaluator_sha256",
                "environment_sha256",
                "candidate_receipt_sha256",
                "execution_receipt_sha256",
                "official_evaluation_receipt_sha256",
            ):
                if getattr(decision, name) != getattr(episode, name):
                    raise RSILearningError("rsi_verifier_reconcile_decision_invalid")
            validate = getattr(self.controller.verifier, "validate_retained", None)
            if not callable(validate):
                raise RSILearningError("rsi_verifier_reconcile_validation_unavailable")
            validate(episode, request, result, decision)
            intent["reconciliation"] = {
                "expected_record_sha256": expected_record_sha256,
                "intent_sha256": expected_intent_sha256,
                "decision_sha256": digest(decision.to_dict()),
            }
            intent["decision"] = decision.to_dict()
            key = (
                "verifier_decision"
                if intent["decision_kind"] == "completion"
                else "diagnostic_verifier"
            )
            entry[key] = intent["decision"]
            self.state["reconciliation_ready"] = True
            self._save()
            self._materialize(entry, allow_verifier=False)
            return self._continue()

    def _check_reconciliation_checkpoint(self, entry: Mapping[str, Any], request: SolverRequest) -> None:
        """Bind an unknown-retry reservation to its original record and terminal evidence."""
        reconciliation = entry.get("reconciliation")
        if reconciliation is None:
            return
        if not isinstance(reconciliation, Mapping) or set(reconciliation) != {
            "expected_record_sha256", "prior_result", "terminal_result_sha256",
        }:
            raise RSILearningError("rsi_budget_checkpoint_invalid")
        expected = reconciliation["expected_record_sha256"]
        if type(expected) is not str or len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
            raise RSILearningError("rsi_budget_checkpoint_invalid")
        parent = entry.get("reconciliation_parent")
        if not isinstance(parent, Mapping):
            raise RSILearningError("rsi_budget_checkpoint_invalid")
        original = PracticeEpisode.from_dict(parent)
        if original.status not in {"running", "unknown"}:
            raise RSILearningError("rsi_budget_checkpoint_invalid")
        if not any(
            record.record_sha256 == expected and record.payload == dict(parent)
            for record in self.ledger.history(request.episode_id)
        ):
            raise RSILearningError("rsi_budget_checkpoint_invalid")
        prior = reconciliation["prior_result"]
        if prior is None:
            if original.status != "running":
                raise RSILearningError("rsi_budget_checkpoint_invalid")
        else:
            prior_result = SolverResult.from_dict(prior)
            self._check_result(request, prior_result)
            if prior_result.status != "unknown" or original.status != "unknown":
                raise RSILearningError("rsi_budget_checkpoint_invalid")
        result = entry.get("result")
        if not isinstance(result, Mapping) or digest(result) != reconciliation["terminal_result_sha256"]:
            raise RSILearningError("rsi_budget_checkpoint_invalid")
        terminal = SolverResult.from_dict(result)
        self._check_result(request, terminal)
        if terminal.status not in {"completed", "failed", "timed_out", "abandoned", "cancelled"}:
            raise RSILearningError("rsi_budget_checkpoint_invalid")

    def _episode_lineage(self, episode_id: str, entry: Mapping[str, Any]) -> tuple[int, tuple[str, ...]]:
        seen: list[str] = [episode_id]
        parent = PracticeEpisode.from_dict(entry["running_episode"]).parent_target_episode_id
        while parent is not None:
            # BRS has no target execution: each independent practice is rooted at this fixed
            # synthetic target.  It is the only parent that may be absent from the episode map.
            if (self.state["config"]["mode"] == "brs"
                    and parent == f"{self.run_id}-target-seed"):
                seen.append(parent)
                return len(seen) - 1, tuple(reversed(seen))
            if parent in seen or parent not in self.state["episodes"]:
                raise RSILearningError("rsi_budget_depth_cycle")
            seen.append(parent)
            parent = PracticeEpisode.from_dict(self.state["episodes"][parent]["running_episode"]).parent_target_episode_id
        return len(seen) - 1, tuple(reversed(seen))

    @staticmethod
    def _check_episode_checkpoint_shape(entry: Mapping[str, Any]) -> None:
        """Keep checkpoint stage labels from weakening the unknown gate.

        A launch intent is allowed to retain a result while recovery is between the result write
        and episode materialization.  Other combinations are impossible in a controller-produced
        checkpoint and must fail closed instead of allowing a forged ``planned`` entry to launch
        again.
        """
        if not isinstance(entry, Mapping):
            raise RSILearningError("rsi_resume_episode_stage_invalid")
        stage = entry.get("stage")
        if stage not in {"planned", "launched", "unknown", "settled"}:
            raise RSILearningError("rsi_resume_episode_stage_invalid")
        raw_result = entry.get("result")
        raw_episode = entry.get("episode")
        if stage == "planned" and (raw_result is not None or raw_episode is not None):
            raise RSILearningError("rsi_resume_episode_stage_invalid")
        if raw_result is None:
            if stage in {"unknown", "settled"} or raw_episode is not None:
                raise RSILearningError("rsi_resume_episode_stage_invalid")
            return
        if not isinstance(raw_result, Mapping):
            raise RSILearningError("rsi_resume_episode_stage_invalid")
        status = raw_result.get("status")
        if stage == "unknown" and status != "unknown":
            raise RSILearningError("rsi_resume_episode_stage_invalid")
        if stage == "settled" and status == "unknown":
            raise RSILearningError("rsi_resume_episode_stage_invalid")
        if raw_episode is None:
            if stage == "settled":
                raise RSILearningError("rsi_resume_episode_stage_invalid")
            return
        if not isinstance(raw_episode, Mapping) or raw_episode.get("status") != status:
            raise RSILearningError("rsi_resume_episode_stage_invalid")

    def _validate_memory(self) -> None:
        """Rebuild the committed chain using verified episodes and compare each durable snapshot."""
        from .rsi_controller import CurriculumDecision, EpisodeExecution

        committed = self.state["commits"]
        if len(set(committed)) != len(committed):
            raise RSILearningError("rsi_memory_commit_duplicate")
        governance = self.controller.memory_governance
        candidate_digests = self.state.get("candidate_record_digests")
        if governance is not None:
            if not isinstance(candidate_digests, dict) or set(candidate_digests) != set(committed):
                raise RSILearningError("rsi_memory_candidate_checkpoint_invalid")
            retained = governance.inspect_records(self.ledger, require_journal=True)
        elif candidate_digests not in (None, {}):
            raise RSILearningError("rsi_memory_candidate_checkpoint_invalid")
        initial = MemorySnapshot.from_dict(self.state["initial_memory_snapshot"])
        final = self.controller.memory_store
        ledger = self.controller.ledger
        self.controller.memory_store = RSIMemoryStore(initial)
        self.controller.ledger = None
        try:
            for episode_id in committed:
                entry = self.state["episodes"].get(episode_id)
                if entry is None or entry.get("episode") is None or entry.get("result") is None:
                    raise RSILearningError("rsi_memory_commit_evidence_missing")
                episode = PracticeEpisode.from_dict(entry["episode"])
                request = SolverRequest.from_dict(entry["request"])
                result = SolverResult.from_dict(entry["result"])
                if episode.verifier is None or episode.verifier.outcome != "pass":
                    raise RSILearningError("rsi_memory_commit_not_approved")
                raw = (
                    self.state["config"]["practices"][episode.ordinal]
                    if self.state["config"]["mode"] == "brs"
                    else self.state["decisions"][episode_id]
                )
                decision = CurriculumDecision(
                    **{**raw, "compatible_solvers": tuple(raw["compatible_solvers"])}
                )
                execution = EpisodeExecution(episode, request, result, episode.verifier)
                if governance is not None:
                    proposal = self.controller._candidate_proposal(execution, decision)
                    expected = governance.preview_nomination(**proposal)
                    history = tuple(
                        record
                        for record in retained
                        if record.authority.memory_id == proposal["memory"].memory_id
                    )
                    candidate = expected[-1]
                    if candidate_digests[episode_id] != candidate.digest() or tuple(
                        record.digest() for record in history[:3]
                    ) != tuple(record.digest() for record in expected):
                        raise RSILearningError("rsi_memory_candidate_evidence_missing")
                    continue
                frozen = initial.digest() if self.state["config"]["mode"] == "brs" else None
                rebuilt = self.controller._commit(
                    execution,
                    decision,
                    expected_episode_snapshot_sha256=frozen,
                    source_snapshot_sha256=frozen,
                )
                stored = ledger.get(f"memory:{rebuilt.snapshot_id}")
                if (
                    stored is None
                    or stored.kind != "memory"
                    or stored.state != "approved"
                    or stored.payload != rebuilt.to_dict()
                    or stored.request_sha256 != rebuilt.digest()
                ):
                    raise RSILearningError("rsi_memory_snapshot_evidence_mismatch")
            if self.controller.snapshot.digest() != final.snapshot.digest():
                raise RSILearningError("rsi_memory_snapshot_lineage_mismatch")
        finally:
            self.controller.memory_store = final
            self.controller.ledger = ledger

    def _load(self) -> None:
        checkpoint = self.ledger.controller_checkpoint(self.run_id)
        if checkpoint is None:
            raise RSILearningError("rsi_controller_checkpoint_missing")
        self.version, self.state = checkpoint
        if self.state.get("schema_version") != "1" or self.state.get("run_id") != self.run_id:
            raise RSILearningError("rsi_controller_checkpoint_invalid")
        self._check_components()

    def start(self, mode: str, values: Mapping[str, Any]):
        with self.ledger.controller_lock(self.run_id):
            config = self._config(mode, values)
            if self.ledger.controller_checkpoint(self.run_id) is not None:
                self._load()
                if self.state["config"] != config:
                    raise RSILearningError("rsi_resume_configuration_drift")
            else:
                if self.ledger.get(self.run_id) is not None:
                    raise RSILearningError("rsi_legacy_run_not_resumable")
                if (
                    hasattr(self.controller.gateway, "runtime_factory")
                    and config["actor_fingerprint"] is None
                ):
                    raise RSILearningError("rsi_actor_fingerprint_required")
                snapshot = self.controller.snapshot.to_dict()
                budget = RSIRunBudget.create(config["budget"])
                self._check_stage_support(budget, config)
                self.state = {
                    "schema_version": "1",
                    "run_id": self.run_id,
                    "config": config,
                    "initial_memory_snapshot": snapshot,
                    "memory_snapshot": snapshot,
                    "episodes": {},
                    "decisions": {},
                    "commits": [],
                    "status": "running",
                    "candidate_record_digests": {},
                    "quarantined": [],
                    "reconciliation_ready": False,
                    "budget_state": budget.state,
                    "stage_accounting": {"invocations": []},
                    "usage_state": {
                        "controller_wall_elapsed_ms": 0,
                        "aggregate": RSIUsageReceipt.observed(
                            request_count=None,
                            wall_elapsed_ms=0,
                        ).to_dict(),
                    },
                }
                self._save()
            self._ensure_run_record()
            return self._continue()

    def resume(self, expected: Mapping[str, Any] | None = None):
        with self.ledger.controller_lock(self.run_id):
            self._load()
            self._check_components(expected)
            self._ensure_run_record()
            return self._continue()

    def _ensure_run_record(self) -> None:
        head = self.ledger.get(self.run_id)
        config = self.state["config"]
        identity = digest({"run_id": self.run_id, "config": config,
                           "initial_memory_snapshot": self.state["initial_memory_snapshot"]})
        if head is None:
            head = self.ledger.create_run(self.run_id, identity, config)
        if head.kind != "run" or head.request_sha256 != identity:
            raise RSILearningError("rsi_controller_run_identity_drift")
        if head.state == "created":
            self.ledger.transition(self.run_id, state="running", expected_record_sha256=head.record_sha256)

    def _check_result(self, request: SolverRequest, result: SolverResult) -> None:
        if result.episode_id != request.episode_id or result.request_sha256 != request.digest():
            raise RSILearningError("rsi_solver_result_identity_mismatch")
        if result.status == "completed" and any(value is None for value in (
            result.candidate_receipt_sha256, result.execution_receipt_sha256,
            result.official_evaluation_receipt_sha256,
        )):
            raise RSILearningError("rsi_completed_evidence_missing")
        expected = self.state["config"]["actor_fingerprint"]
        if expected is not None and result.actor_fingerprint != expected:
            raise RSILearningError("rsi_resume_actor_fingerprint_drift")

    def _episode(
        self,
        episode_id: str,
        kind: str,
        wave: int,
        ordinal: int,
        parent: str | None,
        charter: Mapping[str, Any] | None = None,
    ):
        with self.mutex:
            if episode_id not in self.state["episodes"]:
                config = self.state["config"]
                snapshot = (
                    MemorySnapshot.from_dict(self.state["initial_memory_snapshot"])
                    if config["mode"] == "brs"
                    else self.controller.snapshot
                )
                episode = PracticeEpisode(
                    episode_id,
                    self.run_id,
                    config["contract_sha256"],
                    config["evaluator_sha256"],
                    config["environment_sha256"],
                    snapshot.digest(),
                    config["solver_id"],
                    "planned",
                    episode_kind=kind,
                    wave=wave,
                    ordinal=ordinal,
                    parent_target_episode_id=parent,
                )
                request = SolverRequest.build(
                    episode_id=episode_id,
                    contract_sha256=episode.contract_sha256,
                    evaluator_sha256=episode.evaluator_sha256,
                    environment_sha256=episode.environment_sha256,
                    memory_snapshot_sha256=episode.memory_snapshot_sha256,
                    solver_id=episode.solver_id,
                    solver_settings=config["solver_settings"],
                    budget=config["budget"],
                    practice_charter=charter,
                )
                running = episode.transition("running", request_sha256=request.digest())
                self.state["episodes"][episode_id] = {
                    "request": request.to_dict(),
                    "running_episode": running.to_record_dict(),
                    "stage": "planned",
                    "result": None,
                    "episode": None,
                    "depth": 0,
                    "ancestry": [episode_id],
                    "budget_reserved": False,
                    "reconciliation": None,
                    "verifier_invocations": [],
                    "usage": None,
                    "usage_digest": None,
                    "usage_binding": None,
                }
                depth, ancestry = self._episode_lineage(
                    episode_id, self.state["episodes"][episode_id]
                )
                self.state["episodes"][episode_id]["depth"] = depth
                self.state["episodes"][episode_id]["ancestry"] = list(ancestry)
                budget = RSIRunBudget.load(self.state["budget_state"])
                budget.reserve_launch(episode_kind=kind, depth=depth, ancestry=ancestry)
                self.state["budget_state"] = budget.state
                self.state["episodes"][episode_id]["budget_reserved"] = True
                self._save()
            entry = self.state["episodes"][episode_id]
            request = SolverRequest.from_dict(entry["request"])
            running = PracticeEpisode.from_dict(entry["running_episode"])
            if entry["stage"] == "planned":
                # A checkpoint cannot erase an earlier launch already recorded in the ledger.
                # This also protects an episode omitted from an otherwise valid checkpoint.
                if self.ledger.get(request.episode_id) is not None:
                    raise RSILearningError("rsi_resume_episode_stage_invalid")
                if not entry["budget_reserved"]:
                    budget = RSIRunBudget.load(self.state["budget_state"])
                    budget.reserve_launch(
                        episode_kind=kind,
                        depth=entry["depth"],
                        ancestry=tuple(entry["ancestry"]),
                    )
                    self.state["budget_state"] = budget.state
                    entry["budget_reserved"] = True
                # After this durable write even a crash before gateway.run is ambiguous.
                entry["stage"] = "launched"
                self._save()
                self._ensure_episode(running)
                launch = True
            else:
                launch = False
                self._ensure_episode(running)
        if launch:
            self.ledger._assert_controller_lock(self.run_id)
            started_ns = time.monotonic_ns()
            with self._stage_scope(request, "gateway"):
                result = self.controller.gateway.run(request)
            wall_elapsed_ms = max(0, (time.monotonic_ns() - started_ns) // 1_000_000)
            self._check_result(request, result)
            receipt = usage_receipt_from(
                self.controller.gateway,
                request,
                result,
                wall_elapsed_ms=wall_elapsed_ms,
            )
            with self.mutex:
                entry["result"] = result.to_dict()
                entry["usage"] = receipt.to_dict() if receipt is not None else None
                entry["usage_digest"] = (
                    digest(entry["usage"]) if entry["usage"] is not None else None
                )
                entry["usage_binding"] = (
                    self._usage_binding(request, entry["result"], entry["usage"])
                    if entry["usage"] is not None
                    else None
                )
                self._save()
        with self.mutex:
            if entry["result"] is None:
                return None
            return self._materialize(entry)

    def _ensure_episode(self, running: PracticeEpisode) -> None:
        head = self.ledger.get(running.episode_id)
        if head is None:
            self.ledger.create_episode_record(running)
            return
        first = self.ledger.history(running.episode_id)[0]
        if first.payload != running.to_record_dict() or first.request_sha256 != running.request_sha256:
            raise RSILearningError("rsi_resume_episode_identity_drift")

    def _append_if_needed(self, episode: PracticeEpisode) -> None:
        head = self.ledger.get(episode.episode_id)
        if head is None:
            raise RSILearningError("rsi_record_missing")
        existing = PracticeEpisode.from_dict(head.payload)
        if head.state != existing.status:
            raise RSILearningError("rsi_episode_ledger_state_mismatch")
        if existing.record_sha256 == episode.record_sha256:
            return
        if (episode.status == "completed" and episode.verifier is None
                and existing.status == "completed" and existing.verifier is not None
                and existing.previous_record_sha256 == episode.record_sha256
                and episode.attach_verifier(existing.verifier).record_sha256 == existing.record_sha256):
            return
        if any(row.payload == episode.to_record_dict() for row in self.ledger.history(episode.episode_id)):
            raise RSILearningError("rsi_episode_ledger_head_conflict")
        self.ledger.append_episode_record(episode, expected_record_sha256=head.record_sha256)

    def _materialize(self, entry: dict[str, Any], *, allow_verifier: bool = True):
        from .rsi_controller import EpisodeExecution

        request = SolverRequest.from_dict(entry["request"])
        result = SolverResult.from_dict(entry["result"])
        self._check_result(request, result)
        if entry.get("episode") is not None:
            episode = PracticeEpisode.from_dict(entry["episode"])
            self._append_if_needed(episode)
        else:
            parent = PracticeEpisode.from_dict(
                entry.get("reconciliation_parent") or entry["running_episode"]
            )
            evidence = {
                "trace_digest": result.trace_digest,
                "trace_events": result.trace_events,
                "candidate_source_sha256": result.candidate_source_sha256,
                "dependency_sha256": result.dependency_sha256,
                "actor_fingerprint": result.actor_fingerprint,
                "solver_fingerprint": digest(
                    {"solver_id": request.solver_id, "settings": request.solver_settings}
                ),
            }
            if result.status == "completed":
                evidence.update(
                    candidate_receipt_sha256=result.candidate_receipt_sha256,
                    execution_receipt_sha256=result.execution_receipt_sha256,
                    official_evaluation_receipt_sha256=result.official_evaluation_receipt_sha256,
                )
            else:
                evidence["terminal_reason"] = result.terminal_reason or f"solver_{result.status}"
            if parent.status == "unknown":
                if result.status == "completed":
                    evidence["terminal_reason"] = None
                episode = replace(
                    parent, status=result.status, previous_record_sha256=parent.digest(), **evidence
                )
                episode.to_record_dict()
            else:
                episode = parent.transition(result.status, **evidence)
            self._append_if_needed(episode)
            entry["episode"] = episode.to_record_dict()
            self._save()
        if episode.status == "completed" and episode.verifier is None:
            # An interrupted checkpoint write may lag the canonical verifier append.
            head = self.ledger.get(episode.episode_id)
            recovered = PracticeEpisode.from_dict(head.payload)
            if (
                recovered.previous_record_sha256 == episode.record_sha256
                and recovered.verifier is not None
            ):
                episode = recovered
                entry["episode"] = episode.to_record_dict()
                self._save()
        if episode.status == "completed" and episode.verifier is None:
            decision = self._verify(
                entry, episode, request, result, allow_invocation=allow_verifier
            )
            if decision is None:
                return None
            episode = episode.attach_verifier(decision)
            self._append_if_needed(episode)
            entry["episode"] = episode.to_record_dict()
            self._save()
        decision = episode.verifier
        if decision is not None:
            validate = getattr(self.controller.verifier, "validate_retained", None)
            if callable(validate) and episode.record_sha256 not in self.validated_evidence:
                validate(episode, request, result, decision)
                self.validated_evidence.add(episode.record_sha256)
        if decision is None:
            decision = self._verify(
                entry, episode, request, result, allow_invocation=allow_verifier
            )
            if decision is None:
                return None
        entry["stage"] = "settled" if result.status != "unknown" else "unknown"
        return EpisodeExecution(episode, request, result, decision)

    def _observed_curriculum(
        self, *, before: tuple[int, int] | None = None, allow_verifier: bool = True
    ):
        """Rebuild a policy from its pinned initial history and settled prior practices.

        The controller retains the initial immutable policy. Replaying evidence into a fresh
        policy makes reconciliation replace an uncertain observation instead of appending a
        conflicting history item, and makes crash recovery independent of Python object state.
        """
        from .rsi_controller import CurriculumDecision

        policy = self.controller.curriculum
        if not callable(getattr(policy, "observe", None)):
            return policy
        entries = sorted(
            self.state["episodes"].values(),
            key=lambda item: (
                item["running_episode"]["wave"],
                item["running_episode"]["ordinal"],
                item["running_episode"]["episode_id"],
            ),
        )
        for entry in entries:
            episode = entry["running_episode"]
            position = (episode["wave"], episode["ordinal"])
            if (
                episode["episode_kind"] != "practice"
                or entry["result"] is None
                or (before is not None and position >= before)
            ):
                continue
            execution = self._materialize(entry, allow_verifier=allow_verifier)
            if execution is None:
                continue
            raw = (
                self.state["config"]["practices"][episode["ordinal"]]
                if self.state["config"]["mode"] == "brs"
                else self.state["decisions"][episode["episode_id"]]
            )
            decision = CurriculumDecision(
                **{**raw, "compatible_solvers": tuple(raw["compatible_solvers"])}
            )
            policy = policy.observe(decision=decision, execution=execution)
        return policy

    def _decision(self, key: str, target: Any, diagnosis: str, wave: int, ordinal: int):
        from .rsi_controller import CurriculumDecision
        stored = self.state["decisions"].get(key)
        if stored is None:
            policy = self._observed_curriculum(before=(wave, ordinal))
            decision = policy.choose(target=target, diagnosis=diagnosis, wave=wave, ordinal=ordinal)
            self.state["decisions"][key] = decision.to_dict()
            self._save()
            return decision
        return CurriculumDecision(**{**stored, "compatible_solvers": tuple(stored["compatible_solvers"])})

    def _commit(self, execution: Any, decision: Any, *, frozen: str | None = None) -> None:
        episode_id = execution.episode.episode_id
        if episode_id in self.state["commits"] or not execution.passed:
            return
        parent = self.controller.snapshot
        self.controller.memory_store = RSIMemoryStore(parent)
        ledger = self.controller.ledger
        self.controller.ledger = None
        try:
            snapshot = self.controller._commit(
                execution,
                decision,
                expected_episode_snapshot_sha256=frozen,
                source_snapshot_sha256=frozen,
            )
        finally:
            self.controller.ledger = ledger
            self.controller.memory_store = RSIMemoryStore(parent)
        old = self.ledger.get(f"memory:{snapshot.snapshot_id}")
        if old is None:
            self.ledger.create_memory_snapshot(snapshot)
        elif old.payload != snapshot.to_dict() or old.request_sha256 != snapshot.digest():
            raise RSILearningError("rsi_memory_parent_conflict")
        self.state["memory_snapshot"] = snapshot.to_dict()
        if self.controller.memory_governance is not None:
            expected = self.controller.memory_governance.preview_nomination(
                **self.controller._candidate_proposal(execution, decision)
            )
            self.state["candidate_record_digests"][episode_id] = expected[-1].digest()
        self.state["commits"].append(episode_id)
        self._save()
        self.controller.memory_store = RSIMemoryStore(snapshot)

    def _executions(self, *, allow_verifier: bool = True):
        results = []
        for entry in self.state["episodes"].values():
            if entry["result"] is not None:
                execution = self._materialize(entry, allow_verifier=allow_verifier)
                if execution is not None:
                    results.append(execution)
        return results

    def _finish(self, status: str):
        from .rsi_controller import LearningRunResult

        self.state["status"] = status
        self._save()
        results = self._executions(allow_verifier=False)
        targets = tuple(
            sorted(
                (e for e in results if e.episode.episode_kind == "target"),
                key=lambda e: e.episode.wave,
            )
        )
        practices = tuple(
            sorted(
                (e for e in results if e.episode.episode_kind == "practice"),
                key=lambda e: (e.episode.wave, e.episode.ordinal),
            )
        )
        policy = self._observed_curriculum(allow_verifier=False)
        history_pin = getattr(policy, "history_fingerprint", None)
        if callable(history_pin):
            self.state["curriculum_history_sha256"] = history_pin()
            self._save()
        head = self.ledger.get(self.run_id)
        if head.state != status:
            self.ledger.transition(
                self.run_id,
                state=status,
                expected_record_sha256=head.record_sha256,
                payload_patch={
                    "memory_snapshot_sha256": self.controller.snapshot.digest(),
                    "target_attempts": len(targets),
                    "practice_episodes": len(practices),
                },
            )
        return LearningRunResult(self.run_id, status, self.controller.snapshot, targets, practices)

    def _continue(self):
        if self.state["status"] in {"completed", "failed", "cancelled", "budget_exhausted"}:
            return self._finish(self.state["status"])
        unresolved = any(
            entry["stage"] != "planned"
            and (
                entry["result"] is None
                or entry["result"]["status"] == "unknown"
                or (
                    self._current_verifier_intent(entry) is not None
                    and self._current_verifier_intent(entry)["decision"] is None
                )
            )
            for entry in self.state["episodes"].values()
        )
        if unresolved:
            return self._finish("unknown")
        head = self.ledger.get(self.run_id)
        if head.state == "unknown":
            if not self.state["reconciliation_ready"]:
                return self._finish("unknown")
            self.ledger.resume_reconciled_run(
                self.run_id, expected_record_sha256=head.record_sha256
            )
        try:
            if self.state["config"]["mode"] == "brs":
                return self._brs()
            return self._drs()
        except RSILearningError as exc:
            if exc.code == "rsi_budget_exhausted":
                return self._finish("budget_exhausted")
            raise

    def _drs(self):
        config = self.state["config"]
        for attempt in range(config["max_target_attempts"]):
            target_id = f"{self.run_id}-target-{attempt}"
            target = self._episode(target_id, "target", attempt, 0, None)
            if target is None:
                return self._finish("unknown")
            entry = self.state["episodes"][target_id]
            if entry.get("target_judgment") is None:
                accepted, diagnosis = self.controller.target_judge(target)
                if type(accepted) is not bool or type(diagnosis) is not str:
                    raise RSILearningError("rsi_target_judgment_invalid")
                entry["target_judgment"] = [accepted, diagnosis]
                self._save()
            else:
                accepted, diagnosis = entry["target_judgment"]
            if accepted and target.passed:
                return self._finish("completed")
            if target.result.status in {"unknown", "timed_out", "abandoned", "cancelled"}:
                return self._finish("unknown" if target.result.status == "unknown" else "failed")
            if attempt >= config["max_practice_rounds"]:
                break
            practice_id = f"{self.run_id}-practice-{attempt}-0"
            decision = self._decision(practice_id, target.episode, diagnosis, attempt, 0)
            practice = self._episode(practice_id, "practice", attempt, 0, target_id,
                                     {**decision.to_dict(), "decision_sha256": decision.digest()})
            if practice is None:
                return self._finish("unknown")
            if practice.result.status in {"unknown", "timed_out", "abandoned", "cancelled"}:
                return self._finish("unknown" if practice.result.status == "unknown" else "failed")
            self._commit(practice, decision)
        return self._finish("failed")

    def _brs(self):
        from .rsi_controller import CurriculumDecision
        config = self.state["config"]
        decisions = [CurriculumDecision(**{**raw, "compatible_solvers": tuple(raw["compatible_solvers"])})
                     for raw in config["practices"]]
        wave = config["wave"]
        def execute(pair):
            ordinal, decision = pair
            return self._episode(f"{self.run_id}-practice-{wave}-{ordinal}", "practice", wave, ordinal,
                                 f"{self.run_id}-target-seed",
                                 {**decision.to_dict(), "decision_sha256": decision.digest()})
        with ThreadPoolExecutor(max_workers=config["max_workers"] or max(1, len(decisions))) as pool:
            results = list(pool.map(execute, enumerate(decisions)))
        uncertain = [ordinal for ordinal, result in enumerate(results)
                     if result is None or result.result.status in {"unknown", "timed_out", "abandoned", "cancelled"}]
        if uncertain:
            self.state["quarantined"] = [result.episode.episode_id for result in results
                                         if result is not None and result.passed]
            return self._finish("unknown" if any(results[i] is None or results[i].result.status == "unknown"
                                                 for i in uncertain) else "failed")
        frozen = MemorySnapshot.from_dict(self.state["initial_memory_snapshot"]).digest()
        for result, decision in zip(results, decisions):
            if result.episode.memory_snapshot_sha256 != frozen:
                raise RSILearningError("rsi_brs_snapshot_changed")
            self._commit(result, decision, frozen=frozen)
        self.state["quarantined"] = []
        return self._finish("completed")

    def reconcile(self, episode_id: str, result: SolverResult, expected_record_sha256: str):
        with self.ledger.controller_lock(self.run_id):
            self._load()
            entry = self.state["episodes"].get(episode_id)
            if entry is None:
                raise RSILearningError("rsi_reconcile_episode_missing")
            head = self.ledger.get(episode_id)
            if head is None or head.record_sha256 != expected_record_sha256:
                raise RSILearningError("rsi_record_parent_conflict")
            request = SolverRequest.from_dict(entry["request"])
            self._check_result(request, result)
            if result.status not in {"completed", "failed", "timed_out", "abandoned", "cancelled"}:
                raise RSILearningError("rsi_reconcile_terminal_evidence_required")
            old = entry.get("result")
            if old is not None and old["status"] != "unknown":
                if old != result.to_dict():
                    raise RSILearningError("rsi_reconcile_terminal_result_conflict")
                return self._continue()
            if head.state not in {"running", "unknown"}:
                raise RSILearningError("rsi_reconcile_state_invalid")
            budget = RSIRunBudget.load(self.state["budget_state"])
            try:
                budget.reserve_unknown_reconcile()
            except RSILearningError as exc:
                if exc.code == "rsi_budget_exhausted":
                    return self._finish("budget_exhausted")
                raise
            self.state["budget_state"] = budget.state
            canonical = PracticeEpisode.from_dict(head.payload)
            if canonical.status != head.state:
                raise RSILearningError("rsi_episode_ledger_state_mismatch")
            if old is not None and old["status"] != "unknown":
                raise RSILearningError("rsi_reconcile_terminal_result_conflict")
            entry["reconciliation_parent"] = canonical.to_record_dict()
            entry["reconciliation"] = {
                "expected_record_sha256": expected_record_sha256,
                "prior_result": old,
                "terminal_result_sha256": digest(result.to_dict()),
            }
            entry["result"] = result.to_dict()
            entry["stage"] = "launched"
            # External reconciliation supplies terminal solver evidence but no trustworthy
            # provider meter, so it cannot inherit usage observed for the prior unknown result.
            entry["usage"] = None
            entry["usage_digest"] = None
            entry["usage_binding"] = None
            entry["episode"] = None
            entry.pop("diagnostic_verifier", None)
            entry.pop("verifier_decision", None)
            entry.pop("target_judgment", None)
            self.state["reconciliation_ready"] = True
            self._save()
            try:
                self._materialize(entry)
            except RSILearningError as exc:
                if exc.code == "rsi_budget_exhausted":
                    return self._finish("budget_exhausted")
                raise
            return self._continue()
