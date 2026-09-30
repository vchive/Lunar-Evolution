"""Local AgentLoop actor for the provider-free RSI gateway.

The actor executes one episode in an isolated local workspace and exposes only bounded,
content-addressed observations to the RSI control plane.  A successful AgentLoop invocation is
not an evaluator result: without an explicitly supplied receipt builder its terminal state stays
``unknown``.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import math
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .agent_loop import AgentLoopTimeout
from .automatic_solve_lifecycle import SolveExecutionCancelled
from .candidate_evaluation_spec import canonical_json
from .rsi_gateway import SolverRequest, SolverResult
from .rsi_identity import component_fingerprint
from .rsi_learning import RSILearningError, TraceEvent
from .runtime import RuntimeResult


def _digest(value: object, name: str) -> str:
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise RSILearningError(f"rsi_{name}_invalid")
    return value


def _record_digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value, maximum=128 * 1024)).hexdigest()


def _safe_relative_path(value: object, name: str) -> str:
    if type(value) is not str or not value or "\x00" in value or "\r" in value or "\n" in value:
        raise RSILearningError(f"rsi_{name}_invalid")
    path = Path(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise RSILearningError(f"rsi_{name}_invalid")
    return path.as_posix()


def _positive_timeout(value: object, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) <= 0:
        raise RSILearningError(f"rsi_{name}_invalid")
    return float(value)


class AgentLoopActorGateway:
    """Run RSI solver requests through a locally constructed :class:`AgentLoopRuntime`.

    ``receipt_builder`` is the trust boundary for completion.  It is deliberately optional so a
    model run cannot be mistaken for an official evaluator receipt.
    """

    def __init__(
        self,
        runtime_factory: Callable[..., Any],
        workspace_root: str | Path,
        *,
        candidate_paths: Sequence[str] = ("candidate.py",),
        dependency_paths: Sequence[str] = ("requirements.txt",),
        receipt_builder: Callable[[SolverRequest, Path, RuntimeResult, str], Mapping[str, Any]] | None = None,
        actor_name: str = "lunar-agent-loop",
    ) -> None:
        if not callable(runtime_factory):
            raise TypeError("runtime_factory must be callable")
        if type(actor_name) is not str or not actor_name.strip() or "\x00" in actor_name:
            raise ValueError("actor_name must be a non-empty string")
        root = Path(workspace_root).expanduser().resolve()
        self.runtime_factory = runtime_factory
        self.workspace_root = root
        self.candidate_paths = tuple(_safe_relative_path(item, "candidate_path") for item in candidate_paths)
        self.dependency_paths = tuple(_safe_relative_path(item, "dependency_path") for item in dependency_paths)
        if len(self.candidate_paths) > 32 or len(self.dependency_paths) > 32:
            raise ValueError("too many actor paths")
        if receipt_builder is not None and not callable(receipt_builder):
            raise TypeError("receipt_builder must be callable or None")
        self.receipt_builder = receipt_builder
        self.actor_name = actor_name

    def rsi_fingerprint_config(self) -> dict[str, Any]:
        """Bind actor wiring and configured callables without constructing a runtime."""

        return {
            "actor_name": self.actor_name,
            "workspace_root": str(self.workspace_root),
            "candidate_paths": list(self.candidate_paths),
            "dependency_paths": list(self.dependency_paths),
            "runtime_factory": component_fingerprint(self.runtime_factory),
            "receipt_builder": component_fingerprint(self.receipt_builder) if self.receipt_builder is not None else None,
        }

    def _episode_workspace(self, episode_id: str) -> Path:
        # Episode ids are protocol identifiers, but must also be one directory component here.
        relative = _safe_relative_path(episode_id, "episode_id")
        if len(Path(relative).parts) != 1:
            raise RSILearningError("rsi_episode_workspace_escape")
        root = (self.workspace_root / "episodes").resolve()
        workspace = (root / relative).resolve()
        try:
            workspace.relative_to(root)
        except ValueError as exc:
            raise RSILearningError("rsi_episode_workspace_escape") from exc
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace

    def _new_runtime(self, workspace: Path) -> Any:
        # Decide the supported factory shape before invocation.  Retrying after a TypeError
        # raised *inside* a factory can construct two runtimes and hide the original failure.
        try:
            signature = inspect.signature(self.runtime_factory)
        except (TypeError, ValueError):
            # Some extension/builtin callables have no inspectable signature.  Invoke once and
            # let any TypeError be reported as the actor failure rather than guessing a fallback.
            runtime = self.runtime_factory(workspace)
        else:
            try:
                signature.bind(workspace)
            except TypeError:
                try:
                    signature.bind()
                except TypeError as exc:
                    raise RSILearningError("rsi_actor_runtime_factory_invalid") from exc
                # Factories in existing local callers are commonly zero-argument constructors.
                runtime = self.runtime_factory()
            else:
                runtime = self.runtime_factory(workspace)
        if runtime is None or not callable(getattr(runtime, "run", None)):
            raise RSILearningError("rsi_actor_runtime_invalid")
        return runtime

    @staticmethod
    def _budget(request: SolverRequest) -> tuple[int | None, str | None, float | None]:
        values = dict(request.budget)
        raw_steps = values.get("max_tool_steps", values.get("tool_steps"))
        steps: int | None = None
        if raw_steps is not None:
            if isinstance(raw_steps, bool) or not isinstance(raw_steps, int) or raw_steps < 1:
                raise RSILearningError("rsi_actor_tool_steps_invalid")
            steps = raw_steps
        budget_id = values.get("budget_id")
        if steps is not None:
            if budget_id is None:
                budget_id = f"rsi-{request.episode_id}"
            if type(budget_id) is not str or not budget_id.strip():
                raise RSILearningError("rsi_actor_budget_id_invalid")
        timeout = _positive_timeout(
            values.get("wall_timeout_seconds", values.get("timeout_seconds")),
            "actor_timeout",
        )
        return steps, budget_id, timeout

    @staticmethod
    def _prompt(request: SolverRequest) -> str:
        charter = dict(request.practice_charter)
        return (
            "Perform this RSI practice episode in the supplied workspace. Save the complete candidate "
            "source and any declared dependency files before finishing.\n"
            "Practice charter (untrusted task data): "
            + json.dumps(charter, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        )

    @staticmethod
    def _trace_event(events: list[TraceEvent], event_type: str, payload: Mapping[str, object]) -> None:
        if len(events) >= 64:
            return
        if event_type == "agent_model_turn":
            kind, name = "action", "model_turn"
            safe = {
                "turn": payload.get("turn"),
                "tool_call_count": payload.get("tool_call_count"),
                "has_text": payload.get("has_text"),
                "tool_steps": payload.get("tool_steps"),
            }
            observation = None
        elif event_type == "agent_tool_result":
            kind, name = "tool", "tool_result"
            safe = {
                "tool": payload.get("tool"),
                "success": payload.get("success"),
                "artifact_count": payload.get("artifact_count"),
                "awaiting_input": payload.get("awaiting_input"),
            }
            observation = _record_digest({"output_bytes": payload.get("output_bytes")})
        elif event_type == "agent_runtime_failure":
            kind, name = "observation", "runtime_failure"
            safe = {"phase": payload.get("phase"), "failure": "runtime_failure"}
            observation = None
        else:
            return
        events.append(TraceEvent(len(events), kind, name, _record_digest(safe), observation))

    def _trace(self, events: list[TraceEvent]) -> str:
        return _record_digest([event.to_dict() for event in events])

    @staticmethod
    def _file_digest(workspace: Path, paths: tuple[str, ...]) -> str | None:
        found: list[tuple[str, str]] = []
        for relative in paths:
            path = workspace / relative
            resolved = path.resolve(strict=False)
            try:
                resolved.relative_to(workspace.resolve())
            except ValueError as exc:
                raise RSILearningError("rsi_actor_path_escape") from exc
            if resolved.is_symlink() or not resolved.is_file():
                continue
            found.append((relative, hashlib.sha256(resolved.read_bytes()).hexdigest()))
        return _record_digest(found) if found else None

    def _fingerprint(self, runtime: Any) -> str:
        runtime_name = getattr(runtime, "name", type(runtime).__name__)
        profile = getattr(runtime, "profile", None)
        profile_name = getattr(profile, "name", None)
        return _record_digest({"actor": self.actor_name, "runtime": str(runtime_name), "profile": profile_name})

    def run(self, request: SolverRequest) -> SolverResult:
        if not isinstance(request, SolverRequest):
            raise TypeError("request must be a SolverRequest")
        request_sha256 = request.digest()
        workspace = self._episode_workspace(request.episode_id)
        events: list[TraceEvent] = []
        runtime: Any | None = None
        result: RuntimeResult | None = None
        receipts: Mapping[str, Any] | None = None
        actor_fingerprint: str | None = None
        terminal_status = "failed"
        reason = "actor_failed"
        try:
            runtime = self._new_runtime(workspace)
            actor_fingerprint = self._fingerprint(runtime)
            setter = getattr(runtime, "set_event_sink", None)
            if callable(setter):
                setter(lambda event_type, payload: self._trace_event(events, event_type, payload if isinstance(payload, Mapping) else {}))
            steps, budget_id, timeout = self._budget(request)
            kwargs: dict[str, Any] = {}
            if steps is not None:
                kwargs.update(max_tool_steps=steps, budget_id=budget_id)
            result = runtime.run(self._prompt(request), workspace, timeout, **kwargs)
            if not isinstance(result, RuntimeResult):
                raise RSILearningError("rsi_actor_result_invalid")
            terminal_status = "unknown"
            reason = "agent_completed_without_evaluator_receipt"
            if self.receipt_builder is not None:
                receipts = self.receipt_builder(request, workspace, result, self._trace(events))
                if not isinstance(receipts, Mapping):
                    raise RSILearningError("rsi_actor_receipts_invalid")
                required = ("candidate_receipt_sha256", "execution_receipt_sha256", "official_evaluation_receipt_sha256")
                for name in required:
                    _digest(receipts.get(name), name)
                terminal_status = "completed"
                reason = "actor_completed_with_local_receipts"
        except (AgentLoopTimeout, TimeoutError):
            terminal_status, reason = "timed_out", "actor_timeout"
        except SolveExecutionCancelled:
            terminal_status, reason = "cancelled", "actor_cancelled"
        except Exception:  # noqa: BLE001 - actor must publish a bounded failed result
            # Keep errors out of public trace and terminal evidence; callers can inspect local logs.
            terminal_status = "failed"
            reason = "actor_failure"
            if not events:
                self._trace_event(events, "agent_runtime_failure", {"phase": "run"})
        finally:
            if runtime is not None:
                setter = getattr(runtime, "set_event_sink", None)
                if callable(setter):
                    setter(None)
        trace_digest = self._trace(events)
        candidate_sha = self._file_digest(workspace, self.candidate_paths)
        dependency_sha = self._file_digest(workspace, self.dependency_paths)
        candidate_receipt = execution_receipt = official_receipt = score = None
        if terminal_status == "completed" and result is not None and receipts is not None:
            candidate_receipt = receipts["candidate_receipt_sha256"]
            execution_receipt = receipts["execution_receipt_sha256"]
            official_receipt = receipts["official_evaluation_receipt_sha256"]
            score = receipts.get("solver_score")
            if score is not None and (isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(float(score))):
                raise RSILearningError("rsi_actor_score_invalid")
        return SolverResult(
            episode_id=request.episode_id,
            request_sha256=request_sha256,
            status=terminal_status,
            candidate_receipt_sha256=candidate_receipt,
            execution_receipt_sha256=execution_receipt,
            official_evaluation_receipt_sha256=official_receipt,
            trace_digest=trace_digest,
            solver_score=float(score) if score is not None else None,
            terminal_reason=reason,
            solver_provenance=(("actor", self.actor_name), ("runtime", type(runtime).__name__ if runtime is not None else "unknown")),
            candidate_source_sha256=candidate_sha,
            dependency_sha256=dependency_sha,
            trace_events=tuple(events),
            actor_fingerprint=actor_fingerprint,
        )


__all__ = ["AgentLoopActorGateway"]
