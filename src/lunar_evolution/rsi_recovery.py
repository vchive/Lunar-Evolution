"""Durable RSI controller state machine independent of solver execution backends.

A launch intent is committed before calling the gateway. An intent without a terminal result is
uncertain work, never permission to launch again. Reconciliation supplies evidence for the same
immutable request, then resumes the original controller schedule.
"""
from __future__ import annotations

import hashlib
import inspect
import threading
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any

from .candidate_evaluation_spec import canonical_json
from .rsi_gateway import RSIMemoryStore, SolverRequest, SolverResult
from .rsi_learning import (
    MemorySnapshot,
    PracticeEpisode,
    RSILearningError,
    VerifierCheck,
    VerifierDecision,
)


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

    def _save(self) -> None:
        self.version = self.ledger.write_controller_checkpoint(
            self.run_id, self.state, expected_sha256=self.version,
        )

    def _config(self, mode: str, values: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "mode": mode, **dict(values),
            "solver_settings": dict(self.controller.solver_settings),
            "actor_fingerprint": self.controller.actor_fingerprint,
            "gateway_fingerprint": fingerprint(self.controller.gateway),
            "verifier_fingerprint": fingerprint(self.controller.verifier),
            "curriculum_fingerprint": fingerprint(self.controller.curriculum),
            "curriculum_history_fingerprint": (
                self.controller.curriculum.history_fingerprint()
                if callable(getattr(self.controller.curriculum, "history_fingerprint", None)) else None
            ),
            "target_judge_fingerprint": fingerprint(self.controller.target_judge),
        }

    def _check_components(self, expected: Mapping[str, Any] | None = None) -> None:
        config = self.state["config"]
        current = self._config(config["mode"], {})
        for key in ("solver_settings", "actor_fingerprint", "gateway_fingerprint",
                    "verifier_fingerprint", "curriculum_fingerprint", "curriculum_history_fingerprint", "target_judge_fingerprint"):
            if current[key] != config[key]:
                raise RSILearningError(f"rsi_resume_{key}_drift")
        for key, value in (expected or {}).items():
            if value is not None and config.get(key) != value:
                raise RSILearningError(f"rsi_resume_{key}_drift")
        snapshot = MemorySnapshot.from_dict(self.state["memory_snapshot"])
        initial = MemorySnapshot.from_dict(self.state["initial_memory_snapshot"])
        supplied = self.controller.snapshot.digest()
        if supplied not in {initial.digest(), snapshot.digest()} and self.controller._explicit_memory_store:
            raise RSILearningError("rsi_resume_memory_snapshot_drift")
        self.controller.memory_store = RSIMemoryStore(snapshot)
        durable_episode_ids = set(self.ledger.episode_ids_for_run(self.run_id))
        checkpoint_episode_ids = set(self.state["episodes"])
        planned_without_ledger = {
            episode_id for episode_id, entry in self.state["episodes"].items()
            if entry.get("stage") == "planned" and episode_id not in durable_episode_ids
        }
        if durable_episode_ids - checkpoint_episode_ids or checkpoint_episode_ids - durable_episode_ids - planned_without_ledger:
            raise RSILearningError("rsi_resume_episode_checkpoint_gap")
        for entry in self.state["episodes"].values():
            self._check_episode_checkpoint_shape(entry)
            request = SolverRequest.from_dict(entry["request"])
            episode = PracticeEpisode.from_dict(entry["running_episode"])
            if entry["stage"] == "planned" and self.ledger.get(request.episode_id) is not None:
                raise RSILearningError("rsi_resume_episode_stage_invalid")
            if (request.digest() != episode.request_sha256
                    or episode.run_id != self.run_id
                    or request.solver_id != config["solver_id"]
                    or dict(request.solver_settings) != config["solver_settings"]):
                raise RSILearningError("rsi_resume_request_drift")
            for name in ("contract_sha256", "evaluator_sha256", "environment_sha256"):
                if getattr(request, name) != config[name] or getattr(episode, name) != config[name]:
                    raise RSILearningError(f"rsi_resume_{name}_drift")
            if entry.get("result") is not None:
                result = SolverResult.from_dict(entry["result"])
                self._check_result(request, result)
                if entry.get("episode") is not None:
                    episode = PracticeEpisode.from_dict(entry["episode"])
                    if (episode.request_sha256 != result.request_sha256
                            or episode.episode_id != result.episode_id or episode.status != result.status
                            or episode.trace_events != result.trace_events
                            or episode.run_id != self.run_id
                            or episode.memory_snapshot_sha256 != request.memory_snapshot_sha256
                            or episode.solver_fingerprint != digest({"solver_id": request.solver_id,
                                                                     "settings": request.solver_settings})):
                        raise RSILearningError("rsi_resume_episode_result_mismatch")
                    for name in (
                        "candidate_receipt_sha256", "execution_receipt_sha256",
                        "official_evaluation_receipt_sha256", "trace_digest",
                        "candidate_source_sha256", "dependency_sha256", "actor_fingerprint",
                    ):
                        if getattr(episode, name) != getattr(result, name):
                            raise RSILearningError("rsi_resume_episode_result_mismatch")
        self._validate_memory()

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
                raw = (self.state["config"]["practices"][episode.ordinal]
                       if self.state["config"]["mode"] == "brs" else self.state["decisions"][episode_id])
                decision = CurriculumDecision(**{**raw, "compatible_solvers": tuple(raw["compatible_solvers"])})
                frozen = initial.digest() if self.state["config"]["mode"] == "brs" else None
                rebuilt = self.controller._commit(
                    EpisodeExecution(episode, request, result, episode.verifier), decision,
                    expected_episode_snapshot_sha256=frozen, source_snapshot_sha256=frozen,
                )
                stored = ledger.get(f"memory:{rebuilt.snapshot_id}")
                if (stored is None or stored.kind != "memory" or stored.state != "approved"
                        or stored.payload != rebuilt.to_dict() or stored.request_sha256 != rebuilt.digest()):
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
                if hasattr(self.controller.gateway, "runtime_factory") and config["actor_fingerprint"] is None:
                    raise RSILearningError("rsi_actor_fingerprint_required")
                snapshot = self.controller.snapshot.to_dict()
                self.state = {
                    "schema_version": "1", "run_id": self.run_id, "config": config,
                    "initial_memory_snapshot": snapshot, "memory_snapshot": snapshot,
                    "episodes": {}, "decisions": {}, "commits": [], "status": "running",
                    "quarantined": [], "reconciliation_ready": False,
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

    def _episode(self, episode_id: str, kind: str, wave: int, ordinal: int,
                 parent: str | None, charter: Mapping[str, Any] | None = None):
        with self.mutex:
            if episode_id not in self.state["episodes"]:
                config = self.state["config"]
                snapshot = (MemorySnapshot.from_dict(self.state["initial_memory_snapshot"])
                            if config["mode"] == "brs" else self.controller.snapshot)
                episode = PracticeEpisode(
                    episode_id, self.run_id, config["contract_sha256"], config["evaluator_sha256"],
                    config["environment_sha256"], snapshot.digest(), config["solver_id"], "planned",
                    episode_kind=kind, wave=wave, ordinal=ordinal, parent_target_episode_id=parent,
                )
                request = SolverRequest.build(
                    episode_id=episode_id, contract_sha256=episode.contract_sha256,
                    evaluator_sha256=episode.evaluator_sha256, environment_sha256=episode.environment_sha256,
                    memory_snapshot_sha256=episode.memory_snapshot_sha256, solver_id=episode.solver_id,
                    solver_settings=config["solver_settings"], budget=config["budget"], practice_charter=charter,
                )
                running = episode.transition("running", request_sha256=request.digest())
                self.state["episodes"][episode_id] = {
                    "request": request.to_dict(), "running_episode": running.to_record_dict(),
                    "stage": "planned", "result": None, "episode": None,
                }
                self._save()
            entry = self.state["episodes"][episode_id]
            request = SolverRequest.from_dict(entry["request"])
            running = PracticeEpisode.from_dict(entry["running_episode"])
            if entry["stage"] == "planned":
                # A checkpoint cannot erase an earlier launch already recorded in the ledger.
                # This also protects an episode omitted from an otherwise valid checkpoint.
                if self.ledger.get(request.episode_id) is not None:
                    raise RSILearningError("rsi_resume_episode_stage_invalid")
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
            result = self.controller.gateway.run(request)
            self._check_result(request, result)
            with self.mutex:
                entry["result"] = result.to_dict()
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

    def _materialize(self, entry: dict[str, Any]):
        from .rsi_controller import EpisodeExecution
        request = SolverRequest.from_dict(entry["request"])
        result = SolverResult.from_dict(entry["result"])
        self._check_result(request, result)
        if entry.get("episode") is not None:
            episode = PracticeEpisode.from_dict(entry["episode"])
            self._append_if_needed(episode)
        else:
            parent = PracticeEpisode.from_dict(entry.get("reconciliation_parent") or entry["running_episode"])
            evidence = {
                "trace_digest": result.trace_digest, "trace_events": result.trace_events,
                "candidate_source_sha256": result.candidate_source_sha256,
                "dependency_sha256": result.dependency_sha256,
                "actor_fingerprint": result.actor_fingerprint,
                "solver_fingerprint": digest({"solver_id": request.solver_id, "settings": request.solver_settings}),
            }
            if result.status == "completed":
                evidence.update(candidate_receipt_sha256=result.candidate_receipt_sha256,
                                execution_receipt_sha256=result.execution_receipt_sha256,
                                official_evaluation_receipt_sha256=result.official_evaluation_receipt_sha256)
            else:
                evidence["terminal_reason"] = result.terminal_reason or f"solver_{result.status}"
            if parent.status == "unknown":
                if result.status == "completed":
                    evidence["terminal_reason"] = None
                episode = replace(parent, status=result.status, previous_record_sha256=parent.digest(), **evidence)
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
            if recovered.previous_record_sha256 == episode.record_sha256 and recovered.verifier is not None:
                episode = recovered
                entry["episode"] = episode.to_record_dict()
                self._save()
        if episode.status == "completed" and episode.verifier is None:
            retained = entry.get("verifier_decision")
            if retained is None:
                decision = self.controller.verifier.verify(episode, request, result)
                entry["verifier_decision"] = decision.to_dict()
                self._save()
            else:
                decision = VerifierDecision(**{
                    **retained, "checks": tuple(VerifierCheck(**check) for check in retained["checks"]),
                })
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
            if entry.get("diagnostic_verifier") is None:
                decision = self.controller.verifier.verify(episode, request, result)
                entry["diagnostic_verifier"] = decision.to_dict()
                self._save()
            else:
                raw = entry["diagnostic_verifier"]
                decision = VerifierDecision(**{
                    **raw, "checks": tuple(VerifierCheck(**check) for check in raw["checks"]),
                })
        entry["stage"] = "settled" if result.status != "unknown" else "unknown"
        return EpisodeExecution(episode, request, result, decision)

    def _observed_curriculum(self, *, before: tuple[int, int] | None = None):
        """Rebuild a policy from its pinned initial history and settled prior practices.

        The controller retains the initial immutable policy. Replaying evidence into a fresh
        policy makes reconciliation replace an uncertain observation instead of appending a
        conflicting history item, and makes crash recovery independent of Python object state.
        """
        from .rsi_controller import CurriculumDecision
        policy = self.controller.curriculum
        if not callable(getattr(policy, "observe", None)):
            return policy
        entries = sorted(self.state["episodes"].values(), key=lambda item: (
            item["running_episode"]["wave"], item["running_episode"]["ordinal"],
            item["running_episode"]["episode_id"],
        ))
        for entry in entries:
            episode = entry["running_episode"]
            position = (episode["wave"], episode["ordinal"])
            if (episode["episode_kind"] != "practice" or entry["result"] is None
                    or (before is not None and position >= before)):
                continue
            execution = self._materialize(entry)
            raw = (self.state["config"]["practices"][episode["ordinal"]]
                   if self.state["config"]["mode"] == "brs"
                   else self.state["decisions"][episode["episode_id"]])
            decision = CurriculumDecision(**{**raw, "compatible_solvers": tuple(raw["compatible_solvers"])})
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
            snapshot = self.controller._commit(execution, decision,
                                               expected_episode_snapshot_sha256=frozen,
                                               source_snapshot_sha256=frozen)
        finally:
            self.controller.ledger = ledger
            self.controller.memory_store = RSIMemoryStore(parent)
        old = self.ledger.get(f"memory:{snapshot.snapshot_id}")
        if old is None:
            self.ledger.create_memory_snapshot(snapshot)
        elif old.payload != snapshot.to_dict() or old.request_sha256 != snapshot.digest():
            raise RSILearningError("rsi_memory_parent_conflict")
        self.state["memory_snapshot"] = snapshot.to_dict()
        self.state["commits"].append(episode_id)
        self._save()
        self.controller.memory_store = RSIMemoryStore(snapshot)

    def _executions(self):
        results = []
        for entry in self.state["episodes"].values():
            if entry["result"] is not None:
                results.append(self._materialize(entry))
        return results

    def _finish(self, status: str):
        from .rsi_controller import LearningRunResult
        self.state["status"] = status
        self._save()
        results = self._executions()
        targets = tuple(sorted((e for e in results if e.episode.episode_kind == "target"),
                               key=lambda e: e.episode.wave))
        practices = tuple(sorted((e for e in results if e.episode.episode_kind == "practice"),
                                 key=lambda e: (e.episode.wave, e.episode.ordinal)))
        policy = self._observed_curriculum()
        history_pin = getattr(policy, "history_fingerprint", None)
        if callable(history_pin):
            self.state["curriculum_history_sha256"] = history_pin()
            self._save()
        head = self.ledger.get(self.run_id)
        if head.state != status:
            self.ledger.transition(self.run_id, state=status, expected_record_sha256=head.record_sha256,
                                   payload_patch={"memory_snapshot_sha256": self.controller.snapshot.digest(),
                                                  "target_attempts": len(targets), "practice_episodes": len(practices)})
        return LearningRunResult(self.run_id, status, self.controller.snapshot, targets, practices)

    def _continue(self):
        if self.state["status"] in {"completed", "failed", "cancelled"}:
            return self._finish(self.state["status"])
        unresolved = any(
            entry["stage"] != "planned" and
            (entry["result"] is None or entry["result"]["status"] == "unknown")
            for entry in self.state["episodes"].values()
        )
        if unresolved:
            return self._finish("unknown")
        head = self.ledger.get(self.run_id)
        if head.state == "unknown":
            if not self.state["reconciliation_ready"]:
                return self._finish("unknown")
            self.ledger.resume_reconciled_run(self.run_id, expected_record_sha256=head.record_sha256)
        if self.state["config"]["mode"] == "brs":
            return self._brs()
        return self._drs()

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
            canonical = PracticeEpisode.from_dict(head.payload)
            if canonical.status != head.state:
                raise RSILearningError("rsi_episode_ledger_state_mismatch")
            entry["reconciliation_parent"] = canonical.to_record_dict()
            entry["result"] = result.to_dict()
            entry["episode"] = None
            entry.pop("diagnostic_verifier", None)
            entry.pop("verifier_decision", None)
            entry.pop("target_judgment", None)
            self.state["reconciliation_ready"] = True
            self._save()
            self._materialize(entry)
            return self._continue()
