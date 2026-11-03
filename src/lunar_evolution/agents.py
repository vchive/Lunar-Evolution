"""Runtime-neutral local Agent adapters.

The control plane owns task state; this module only defines how an explicitly selected worker is
invoked.  Nothing here searches PATH, a user's home directory, or a remote service.
"""

from __future__ import annotations

import inspect
import json
import math
import os
import re
import shlex
import signal
import subprocess
import threading
import time
import weakref
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic
from typing import Protocol, runtime_checkable

from .runtime import (
    MODEL_FAILURE_REASONS,
    ModelFailureEvidence,
    ModelRequestFailure,
    Runtime,
    RuntimeResult,
)

MAX_PROMPT_BYTES = 64 * 1024
MAX_TEXT_BYTES = 1024 * 1024
MAX_METADATA_BYTES = 16 * 1024
MAX_METADATA_ITEMS = 64
MAX_ARTIFACTS = 64
MAX_ARTIFACT_PATH_BYTES = 512
MAX_TIMEOUT_SECONDS = 24 * 60 * 60
MAX_CANDIDATE_TOOL_STEPS = 200
BUNDLE_RESPONSE_PROTOCOL = "lunar-evolution-bundle-generation-v1"
CANDIDATE_DIAGNOSTIC_PHASES = frozenset({"model_turn", "tool", "tool_batch", "response", "run"})
DEFAULT_RUNTIME_CAPABILITIES = (
    "read_files",
    "write_files",
    "run_tests",
    "write_artifacts",
    "analyze_data",
    "gather_sources",
)
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
_SECRET_TEXT = re.compile(
    r"(?i)(?:sk-[A-Za-z0-9_-]{12,}|bearer\s+[A-Za-z0-9._-]{12,}|"
    r"api[_-]?key\s*[:=]\s*\S+)"
)


class AgentError(RuntimeError):
    """Base class for bounded Agent adapter failures."""


class AgentSelectionError(AgentError):
    """No explicitly registered adapter satisfies a role/capability request."""


class AgentInvocationError(AgentError):
    """An adapter could not start, complete, or normalize a worker invocation."""

    def __init__(self, message: str, *, candidate_diagnostic: Mapping[str, object] | None = None) -> None:
        super().__init__(message)
        self.candidate_diagnostic = dict(candidate_diagnostic) if isinstance(candidate_diagnostic, Mapping) else None


@dataclass(frozen=True, slots=True)
class CandidateGenerationBudget:
    """Authority-bound budget for one candidate-generation request."""

    budget_id: str
    max_tool_steps: int
    timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "budget_id", _bounded_text(self.budget_id, "budget_id", 256, allow_empty=False))
        if isinstance(self.max_tool_steps, bool) or not isinstance(self.max_tool_steps, int):
            raise TypeError("max_tool_steps must be an integer")
        if not 1 <= self.max_tool_steps <= MAX_CANDIDATE_TOOL_STEPS:
            raise ValueError(
                f"max_tool_steps must be between 1 and {MAX_CANDIDATE_TOOL_STEPS}"
            )
        if self.timeout_seconds is not None:
            if (isinstance(self.timeout_seconds, bool)
                    or not isinstance(self.timeout_seconds, (int, float))
                    or not math.isfinite(float(self.timeout_seconds))
                    or self.timeout_seconds <= 0
                    or self.timeout_seconds > MAX_TIMEOUT_SECONDS):
                raise ValueError(
                    f"timeout_seconds must be between 0 and {MAX_TIMEOUT_SECONDS} seconds"
                )
            object.__setattr__(self, "timeout_seconds", float(self.timeout_seconds))

    def to_dict(self) -> dict[str, object]:
        return {
            "budget_id": self.budget_id,
            "max_tool_steps": self.max_tool_steps,
            "timeout_seconds": self.timeout_seconds,
        }


@dataclass(frozen=True, slots=True)
class CandidateGenerationDiagnostic:
    """Safe completion projection for a candidate-generation budget."""

    budget_id: str
    max_tool_steps: int
    tool_steps_used: int
    tool_steps_remaining: int
    attempted_tool_calls: int | None
    completion: bool
    reason: str
    phase: str
    schema_version: str = "1"
    stage: str = "candidate_generation"
    outcome: str | None = None
    elapsed_ms: int | None = None
    timeout_ms: int | None = None
    failure_cause: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "budget_id", _bounded_text(self.budget_id, "budget_id", 256, allow_empty=False))
        if isinstance(self.max_tool_steps, bool) or not isinstance(self.max_tool_steps, int) or not 1 <= self.max_tool_steps <= MAX_CANDIDATE_TOOL_STEPS:
            raise ValueError("invalid candidate diagnostic max_tool_steps")
        for value, label in ((self.tool_steps_used, "tool_steps_used"),
                             (self.tool_steps_remaining, "tool_steps_remaining")):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"invalid candidate diagnostic {label}")
        if self.attempted_tool_calls is not None and (
            isinstance(self.attempted_tool_calls, bool)
            or not isinstance(self.attempted_tool_calls, int)
            or self.attempted_tool_calls < 0
        ):
            raise ValueError("invalid candidate diagnostic attempted_tool_calls")
        if not isinstance(self.completion, bool):
            raise TypeError("invalid candidate diagnostic completion")
        if self.schema_version != "1":
            raise ValueError("invalid candidate diagnostic schema_version")
        if self.stage != "candidate_generation":
            raise ValueError("invalid candidate diagnostic stage")
        outcome = self.outcome or _candidate_outcome(self.reason)
        if outcome not in {
            "running", "completed", "tool_step_limit_reached", "tool_execution_failed",
            "timed_out", "cancelled", "empty_final_response", "malformed_candidate", "worker_failed",
        }:
            raise ValueError("invalid candidate diagnostic reason")
        object.__setattr__(self, "outcome", outcome)
        if self.elapsed_ms is not None and (
            isinstance(self.elapsed_ms, bool) or not isinstance(self.elapsed_ms, int) or self.elapsed_ms < 0
        ):
            raise ValueError("invalid candidate diagnostic elapsed_ms")
        if self.timeout_ms is not None and (
            isinstance(self.timeout_ms, bool) or not isinstance(self.timeout_ms, int) or self.timeout_ms <= 0
        ):
            raise ValueError("invalid candidate diagnostic timeout_ms")
        if type(self.phase) is not str or self.phase not in CANDIDATE_DIAGNOSTIC_PHASES:
            raise ValueError("invalid candidate diagnostic phase")
        if self.failure_cause is not None and (
            type(self.failure_cause) is not str or self.failure_cause not in MODEL_FAILURE_REASONS
            or self.completion or self.reason == "running"
        ):
            raise ValueError("invalid candidate diagnostic failure_cause")

    def to_dict(self) -> dict[str, object]:
        value = {
            "schema_version": self.schema_version,
            "budget_id": self.budget_id,
            "stage": self.stage,
            "outcome": self.outcome,
            "max_tool_steps": self.max_tool_steps,
            "tool_steps_used": self.tool_steps_used,
            "tool_steps_remaining": self.tool_steps_remaining,
            "attempted_tool_calls": self.attempted_tool_calls,
            "completion": self.completion,
            "reason": self.reason,
            "phase": self.phase,
            "elapsed_ms": self.elapsed_ms,
            "timeout_ms": self.timeout_ms,
        }
        if self.failure_cause is not None:
            value["failure_cause"] = self.failure_cause
        return value


def _candidate_outcome(reason: str) -> str:
    return {
        "tool_failed": "tool_execution_failed",
        "timeout": "timed_out",
        "empty_response": "empty_final_response",
    }.get(reason, reason)


def candidate_model_failure_cause(error: object) -> str | None:
    """Project only the direct, repository-owned failure's fixed model cause."""
    if type(error) is not ModelRequestFailure:
        return None
    evidence = getattr(error, "evidence", None)
    if type(evidence) is not ModelFailureEvidence:
        return None
    reason = getattr(evidence, "reason", None)
    return reason if type(reason) is str and reason in MODEL_FAILURE_REASONS else None


def candidate_failure_reason(error: BaseException) -> str:
    """Classify only typed/local failure boundaries; never inspect arbitrary prose."""
    if isinstance(error, TimeoutError):
        return "timeout"
    if type(error).__name__ in {"CancelledError", "CancellationError"}:
        return "cancelled"
    if candidate_model_failure_cause(error) == "transport_timeout":
        return "timeout"
    return "worker_failed"


def _bounded_text(value: object, label: str, maximum: int, *, allow_empty: bool = True) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    if "\x00" in value:
        raise ValueError(f"{label} must not contain NUL bytes")
    if not allow_empty and not value.strip():
        raise ValueError(f"{label} must not be empty")
    if len(value.encode("utf-8")) > maximum:
        raise ValueError(f"{label} exceeds {maximum} bytes")
    return value


def _safe_event_text(value: str, maximum: int = 512) -> str:
    """Bound and redact scalar text before it crosses the durable event boundary."""
    redacted = _SECRET_TEXT.sub("[REDACTED]", value)
    encoded = redacted.encode("utf-8")
    if len(encoded) <= maximum:
        return redacted
    suffix = "\n[truncated]"
    budget = max(1, maximum - len(suffix.encode("utf-8")))
    return encoded[:budget].decode("utf-8", errors="ignore") + suffix


def _safe_event_error(error: object) -> str:
    return _safe_event_text(" ".join(str(error).split()), 512)


def _token(value: object, label: str) -> str:
    if not isinstance(value, str) or not _TOKEN.fullmatch(value):
        raise ValueError(f"{label} must be a non-empty safe token")
    return value


def _tokens(values: Sequence[str] | set[str] | frozenset[str], label: str) -> frozenset[str]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{label} must be a sequence of strings")
    if len(values) > MAX_METADATA_ITEMS:
        raise ValueError(f"{label} contains too many entries")
    result = frozenset(_token(item, f"{label} entry") for item in values)
    if len(result) != len(values):
        raise ValueError(f"{label} contains duplicate entries")
    return result


def _artifact_path(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("artifact paths must be strings")
    if not value or "\x00" in value or "\\" in value:
        raise ValueError("artifact path is invalid")
    path = Path(value)
    windows_absolute = bool(re.match(r"^[A-Za-z]:[/\\]", value))
    if path.is_absolute() or windows_absolute or "." in path.parts or ".." in path.parts:
        raise ValueError(f"artifact path must be run-relative: {value!r}")
    normalized = path.as_posix()
    if not normalized or len(normalized.encode("utf-8")) > MAX_ARTIFACT_PATH_BYTES:
        raise ValueError("artifact path is empty or too long")
    return normalized


def _metadata(value: Mapping[str, object] | None) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError("metadata must be an object")
    if len(value) > MAX_METADATA_ITEMS:
        raise ValueError("metadata contains too many entries")
    result: dict[str, object] = {}
    for key, item in value.items():
        safe_key = _token(key, "metadata key")
        if not isinstance(item, (str, int, float, bool)) and item is not None:
            raise ValueError("metadata values must be scalar")
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError("metadata float values must be finite")
        if isinstance(item, str):
            _bounded_text(item, f"metadata value for {safe_key}", 2_000)
        result[safe_key] = item
    try:
        encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError("metadata is not JSON serializable") from exc
    if len(encoded.encode("utf-8")) > MAX_METADATA_BYTES:
        raise ValueError(f"metadata exceeds {MAX_METADATA_BYTES} bytes")
    return result


@dataclass(frozen=True, slots=True)
class AgentRequest:
    """Bounded immutable input sent to one selected Agent worker."""

    run_id: str
    task_id: str
    role: str
    prompt: str
    required_capabilities: tuple[str, ...] = ()
    workspace: Path = field(default_factory=Path.cwd)
    timeout: float | None = None
    candidate_budget: CandidateGenerationBudget | None = None
    response_protocol: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _bounded_text(self.run_id, "run_id", 256, allow_empty=False))
        object.__setattr__(self, "task_id", _bounded_text(self.task_id, "task_id", 256, allow_empty=False))
        object.__setattr__(self, "role", _token(self.role, "role"))
        object.__setattr__(self, "prompt", _bounded_text(self.prompt, "prompt", MAX_PROMPT_BYTES, allow_empty=False))
        capabilities = _tokens(self.required_capabilities, "required_capabilities")
        object.__setattr__(self, "required_capabilities", tuple(sorted(capabilities)))
        workspace = Path(self.workspace).expanduser()
        if not workspace.is_absolute():
            raise ValueError("workspace must be an absolute path")
        if "\x00" in str(workspace):
            raise ValueError("workspace must not contain NUL bytes")
        object.__setattr__(self, "workspace", workspace.resolve(strict=False))
        if self.timeout is not None:
            if isinstance(self.timeout, bool) or not isinstance(self.timeout, (int, float)):
                raise ValueError("timeout must be a positive number")
            if self.timeout <= 0 or self.timeout > MAX_TIMEOUT_SECONDS:
                raise ValueError(f"timeout must be between 0 and {MAX_TIMEOUT_SECONDS} seconds")
            object.__setattr__(self, "timeout", float(self.timeout))
        if self.candidate_budget is not None and not isinstance(
            self.candidate_budget, CandidateGenerationBudget
        ):
            raise TypeError("candidate_budget must be a CandidateGenerationBudget or None")
        if self.response_protocol is not None and (
            type(self.response_protocol) is not str or self.response_protocol != BUNDLE_RESPONSE_PROTOCOL
        ):
            raise ValueError("unsupported Agent response_protocol")

    def to_dict(self) -> dict[str, object]:
        value = {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "role": self.role,
            "prompt": self.prompt,
            "required_capabilities": list(self.required_capabilities),
            "workspace": str(self.workspace),
            "timeout": self.timeout,
        }
        if self.candidate_budget is not None:
            value["candidate_budget"] = self.candidate_budget.to_dict()
        if self.response_protocol is not None:
            value["response_protocol"] = self.response_protocol
        return value


@dataclass(frozen=True, slots=True)
class AgentResult:
    """Bounded normalized output returned by an Agent adapter."""

    adapter_name: str
    role: str
    text: str
    artifacts: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)
    status: str = "succeeded"
    error: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "adapter_name", _token(self.adapter_name, "adapter_name"))
        object.__setattr__(self, "role", _token(self.role, "role"))
        status = _token(self.status, "status")
        if status not in {"succeeded", "failed", "cancelled"}:
            raise ValueError("status must be succeeded, failed, or cancelled")
        object.__setattr__(self, "status", status)
        text = _bounded_text(self.text, "text", MAX_TEXT_BYTES)
        if status == "succeeded" and not text.strip():
            raise ValueError("successful Agent results require non-empty text")
        object.__setattr__(self, "text", text)
        if len(self.artifacts) > MAX_ARTIFACTS:
            raise ValueError("too many artifacts")
        normalized = tuple(_artifact_path(item) for item in self.artifacts)
        if len(set(normalized)) != len(normalized):
            raise ValueError("artifacts contain duplicate paths")
        object.__setattr__(self, "artifacts", normalized)
        object.__setattr__(self, "metadata", _metadata(self.metadata))
        if self.error is not None:
            object.__setattr__(self, "error", _bounded_text(self.error, "error", 8_000, allow_empty=False))
        if status in {"failed", "cancelled"} and not self.error:
            raise ValueError(f"{status} Agent results require an error")
        if status == "succeeded" and self.error is not None:
            raise ValueError("successful Agent results must not contain an error")

    def to_dict(self) -> dict[str, object]:
        return {
            "adapter_name": self.adapter_name,
            "role": self.role,
            "status": self.status,
            "text": self.text,
            "artifacts": list(self.artifacts),
            "metadata": dict(self.metadata),
            "error": self.error,
        }


ProcessObserver = Callable[[int, int | None], None]


@runtime_checkable
class AgentAdapter(Protocol):
    """Small lifecycle contract implemented by explicit local workers."""

    name: str
    roles: frozenset[str]
    capabilities: frozenset[str]

    def run(self, request: AgentRequest) -> AgentResult:
        ...

    def cancel(self) -> None:
        ...

    def process_info(self) -> tuple[int | None, int | None]:
        ...

    def set_process_observer(self, observer: ProcessObserver | None) -> None:
        ...


class RuntimeAgentAdapter:
    """Expose an existing Runtime through the role-bearing Agent contract."""

    def __init__(
        self,
        runtime: Runtime,
        *,
        name: str | None = None,
        roles: Sequence[str] = ("worker", "solver", "general"),
        capabilities: Sequence[str] = DEFAULT_RUNTIME_CAPABILITIES,
        runtime_factory: Callable[[], Runtime] | None = None,
    ) -> None:
        if runtime_factory is not None and not callable(runtime_factory):
            raise TypeError("runtime_factory must be callable or None")
        self.runtime = runtime
        self.runtime_factory = runtime_factory
        self.name = _token(name or getattr(runtime, "name", "runtime"), "adapter name")
        self.roles = _tokens(roles, "roles")
        self.capabilities = _tokens(capabilities, "capabilities")
        self._event_sink: Callable[[str, dict[str, object]], None] | None = None
        self._continuation_guard: Callable[[], None] | None = None

    def set_continuation_guard(self, guard: Callable[[], None] | None) -> None:
        """Check attempt authority locally and inside runtimes supporting tool continuations."""
        if guard is not None and not callable(guard):
            raise TypeError("continuation guard must be callable or None")
        self._continuation_guard = guard
        setter = getattr(self.runtime, "set_continuation_guard", None)
        if callable(setter):
            setter(guard)

    def set_active_continuation_guard(self, guard: Callable[[], None] | None) -> None:
        """Forward polling-safe checks separately from between-stage cleanup guards."""
        if guard is not None and not callable(guard):
            raise TypeError("active continuation guard must be callable or None")
        setter = getattr(self.runtime, "set_active_continuation_guard", None)
        if callable(setter):
            setter(guard)

    def set_process_released(self, released: ProcessObserver | None) -> None:
        """Forward verified process-release observations when the runtime supports them."""
        if released is not None and not callable(released):
            raise TypeError("process release observer must be callable or None")
        setter = getattr(self.runtime, "set_process_released", None)
        if callable(setter):
            setter(released)

    def set_worker_context(
        self, service=None, owner_id: str | None = None, parent_worker_id: str | None = None,
    ) -> None:
        """Forward the opt-in WorkerService tool context into the wrapped runtime."""
        setter = getattr(self.runtime, "set_worker_context", None)
        if callable(setter):
            setter(service, owner_id, parent_worker_id)

    def _check_continuation(self) -> None:
        if self._continuation_guard is not None:
            self._continuation_guard()

    def set_event_sink(
        self, sink: Callable[[str, dict[str, object]], None] | None
    ) -> None:
        """Forward bounded runtime lifecycle events to an owning evolution observer."""
        if sink is not None and not callable(sink):
            raise TypeError("event sink must be callable or None")
        self._event_sink = sink

    def run(self, request: AgentRequest) -> AgentResult:
        if not isinstance(request, AgentRequest):
            raise TypeError("request must be an AgentRequest")
        self._check_continuation()
        previous_diagnostic = (
            self._runtime_candidate_diagnostic() if request.candidate_budget is not None else None
        )
        invocation_diagnostic: dict[str, object] | None = None
        set_runtime_event_sink = getattr(self.runtime, "set_event_sink", None)
        runtime_event_sink: Callable[[str, dict[str, object]], None] | None = None
        runtime_event_emitted = False
        if callable(set_runtime_event_sink):
            def forward_runtime_event(event_type: str, payload: dict[str, object]) -> None:
                nonlocal runtime_event_emitted, invocation_diagnostic
                runtime_event_emitted = True
                if event_type == "agent_candidate_generation" and request.candidate_budget is not None:
                    # Runtime completion is not parser acceptance. Hold observations until the
                    # invocation ends; failure emits once and success only supplies result metadata.
                    invocation_diagnostic = dict(payload) if isinstance(payload, Mapping) else None
                    return
                self._forward_event(request, event_type, payload)

            runtime_event_sink = forward_runtime_event
            set_runtime_event_sink(runtime_event_sink)
        try:
            set_context = getattr(self.runtime, "set_context", None)
            if callable(set_context):
                set_context(request.run_id, request.task_id, request.prompt)
            set_session_path = getattr(self.runtime, "set_session_path", None)
            if callable(set_session_path):
                set_session_path(request.workspace / "session-transcript.jsonl")
            runtime_timeout = request.timeout
            budget = request.candidate_budget
            if budget is not None and budget.timeout_seconds is not None:
                runtime_timeout = (
                    budget.timeout_seconds
                    if runtime_timeout is None
                    else min(runtime_timeout, budget.timeout_seconds)
                )
            runtime_run = self.runtime.run
            kwargs: dict[str, object] = {}
            if budget is not None or request.response_protocol is not None:
                try:
                    parameters = inspect.signature(runtime_run).parameters
                except (TypeError, ValueError):
                    parameters = {}
            if budget is not None:
                accepts_kwargs = any(
                    parameter.kind is inspect.Parameter.VAR_KEYWORD
                    for parameter in parameters.values()
                )
                if "max_tool_steps" not in parameters and not accepts_kwargs:
                    raise AgentInvocationError(
                        "runtime does not support candidate tool-step budgets"
                    )
                kwargs["max_tool_steps"] = budget.max_tool_steps
                kwargs["budget_id"] = budget.budget_id
            if request.response_protocol is not None:
                parameter = parameters.get("response_protocol")
                if parameter is not None and parameter.kind in {
                    inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY,
                }:
                    kwargs["response_protocol"] = request.response_protocol
            self._check_continuation()
            result = runtime_run(request.prompt, request.workspace, runtime_timeout, **kwargs)
            self._check_continuation()
        except Exception as exc:
            diagnostic = self._invocation_candidate_diagnostic(
                request, invocation_diagnostic, previous_diagnostic, completed=False,
            )
            if diagnostic is None and request.candidate_budget is not None:
                reason = candidate_failure_reason(exc)
                diagnostic = {
                    "schema_version": "1", "stage": "candidate_generation",
                    "budget_id": request.candidate_budget.budget_id,
                    "max_tool_steps": request.candidate_budget.max_tool_steps,
                    "tool_steps_used": None, "tool_steps_remaining": None,
                    "attempted_tool_calls": None, "completion": False,
                    "reason": reason, "outcome": _candidate_outcome(reason), "phase": "run",
                }
            if diagnostic is not None:
                # External diagnostic mappings can describe counts/phases, but only the
                # direct owned exception can establish a typed model failure cause.
                cause = candidate_model_failure_cause(exc)
                diagnostic.pop("failure_cause", None)
                if cause is not None:
                    diagnostic["failure_cause"] = cause
                self._forward_event(request, "agent_candidate_generation", diagnostic)
            if not runtime_event_emitted:
                self._forward_event(
                    request,
                    "agent_runtime_failure",
                    {"phase": "run", "error": _safe_event_error(exc)},
                )
            if isinstance(exc, AgentError):
                if diagnostic is not None:
                    exc.candidate_diagnostic = dict(diagnostic)
                raise
            raise AgentInvocationError(
                _bounded_error(str(exc)), candidate_diagnostic=diagnostic,
            ) from exc
        finally:
            if runtime_event_sink is not None:
                # A Runtime instance may be reused by a caller; never leave an old evolution
                # observer attached to a later role or run.
                set_runtime_event_sink(None)
        if not isinstance(result, RuntimeResult):
            raise AgentInvocationError("runtime returned an invalid result")
        try:
            declared_artifacts = list(result.artifacts)
            session_path = getattr(self.runtime, "session_path", None)
            if callable(session_path):
                transcript = session_path()
                if transcript is not None and Path(transcript).is_file():
                    raw_transcript = Path(transcript).expanduser()
                    if raw_transcript.is_symlink():
                        raise AgentInvocationError("runtime session artifact must not be a symlink")
                    resolved = raw_transcript.resolve(strict=False)
                    try:
                        relative = resolved.relative_to(request.workspace.resolve())
                    except ValueError as exc:
                        raise AgentInvocationError("runtime session artifact escapes workspace") from exc
                    if relative.as_posix() not in declared_artifacts:
                        declared_artifacts.append(relative.as_posix())
            metadata = {**result.metadata, "runtime": self.name}
            diagnostic = self._invocation_candidate_diagnostic(
                request, invocation_diagnostic, previous_diagnostic, completed=True,
            )
            if diagnostic is not None:
                for key, value in diagnostic.items():
                    if isinstance(key, str) and isinstance(value, (str, int, float, bool)):
                        metadata[f"candidate_{key}"] = str(value).lower() if isinstance(value, bool) else str(value)
            return AgentResult(
                adapter_name=self.name,
                role=request.role,
                text=result.text,
                artifacts=tuple(declared_artifacts),
                metadata=metadata,
            )
        except (TypeError, ValueError) as exc:
            raise AgentInvocationError(_bounded_error(str(exc))) from exc

    def _runtime_candidate_diagnostic(self) -> dict[str, object] | None:
        """Snapshot optional observations without letting a diagnostic getter mask execution."""
        try:
            diagnostic = getattr(self.runtime, "last_candidate_diagnostic", None)
            if callable(diagnostic):
                diagnostic = diagnostic()
            return dict(diagnostic) if isinstance(diagnostic, Mapping) else None
        except Exception:  # noqa: BLE001 - diagnostics are never execution authority
            return None

    def _invocation_candidate_diagnostic(
        self, request: AgentRequest, emitted: dict[str, object] | None,
        previous: dict[str, object] | None, *, completed: bool,
    ) -> dict[str, object] | None:
        budget = request.candidate_budget
        if budget is None:
            return None
        observed = emitted
        if observed is None:
            observed = self._runtime_candidate_diagnostic()
            if observed == previous:
                return None
        try:
            diagnostic = CandidateGenerationDiagnostic(**observed)
            if (
                diagnostic.budget_id != budget.budget_id
                or diagnostic.completion is not completed
                or diagnostic.outcome != _candidate_outcome(diagnostic.reason)
                or diagnostic.reason == "running"
                or (diagnostic.reason == "completed") is not completed
                or diagnostic.max_tool_steps > budget.max_tool_steps
                or diagnostic.tool_steps_used + diagnostic.tool_steps_remaining != diagnostic.max_tool_steps
            ):
                return None
            return diagnostic.to_dict()
        except (TypeError, ValueError):
            return None

    def _forward_event(
        self, request: AgentRequest, event_type: str, payload: Mapping[str, object]
    ) -> None:
        if self._event_sink is None:
            return
        bounded: dict[str, object] = {}
        if event_type == "agent_candidate_generation":
            # The controller supplies the authoritative run/task binding.  Adapter-local
            # request IDs are workspace-derived and must not cross that boundary.
            pass
        else:
            bounded.update({
                "adapter": self.name,
                "role": request.role,
                "run_id": request.run_id,
                "task_id": request.task_id,
            })
        if request.candidate_budget is not None:
            bounded["budget_id"] = request.candidate_budget.budget_id
            bounded["max_tool_steps"] = request.candidate_budget.max_tool_steps
        if isinstance(payload, Mapping):
            for key, value in list(payload.items())[:16]:
                if not isinstance(key, str) or not _TOKEN.fullmatch(key):
                    continue
                if isinstance(value, (bool, int, float)) or value is None:
                    bounded[key] = value
                elif isinstance(value, str):
                    bounded[key] = _safe_event_text(value)
        self._event_sink(event_type, bounded)

    def cancel(self) -> None:
        self.runtime.cancel()

    def process_info(self) -> tuple[int | None, int | None]:
        return self.runtime.process_info()

    def set_process_observer(self, observer: ProcessObserver | None) -> None:
        self.runtime.set_process_observer(observer)


class CommandAgentAdapter:
    """Invoke an explicitly configured executable using one JSON stdin/stdout exchange."""

    def __init__(
        self,
        command: str | Sequence[str],
        roles: Sequence[str] = ("worker", "solver", "general"),
        capabilities: Sequence[str] = (),
        *,
        name: str = "command",
        max_output_bytes: int = MAX_TEXT_BYTES,
    ) -> None:
        if isinstance(command, str):
            # A string is accepted only as one executable token; callers that need arguments can
            # pass a sequence or use the CLI's explicit shell-like parser.
            command = (command,)
        if not command or isinstance(command, (bytes, bytearray)):
            raise ValueError("command must not be empty")
        normalized = tuple(str(item) for item in command)
        if any(not item or "\x00" in item for item in normalized):
            raise ValueError("command arguments must be non-empty and NUL-free")
        executable = Path(normalized[0]).expanduser()
        if not executable.is_absolute() or not executable.is_file() or not os.access(executable, os.X_OK):
            raise ValueError("command must start with an existing absolute executable path")
        if isinstance(max_output_bytes, bool) or not isinstance(max_output_bytes, int) or max_output_bytes < 1:
            raise ValueError("max_output_bytes must be a positive integer")
        self.command = normalized
        self.name = _token(name, "adapter name")
        self.roles = _tokens(roles, "roles")
        self.capabilities = _tokens(capabilities, "capabilities")
        self.max_output_bytes = max_output_bytes
        self._process: subprocess.Popen[bytes] | None = None
        self._observer: ProcessObserver | None = None
        self._process_released: ProcessObserver | None = None
        self._active_process_released: ProcessObserver | None = None
        self._continuation_guard: Callable[[], None] | None = None
        self._run_lock = threading.Lock()

    def set_continuation_guard(self, guard: Callable[[], None] | None) -> None:
        if guard is not None and not callable(guard):
            raise TypeError("continuation guard must be callable or None")
        self._continuation_guard = guard

    def _check_continuation(self) -> None:
        if self._continuation_guard is not None:
            self._continuation_guard()

    @classmethod
    def from_shell_like(
        cls,
        command: str,
        *,
        name: str = "command",
        roles: Sequence[str] = ("worker", "solver", "general"),
        capabilities: Sequence[str] = (),
        max_output_bytes: int = MAX_TEXT_BYTES,
    ) -> CommandAgentAdapter:
        try:
            parts = tuple(shlex.split(command))
        except ValueError as exc:
            raise ValueError(f"command is not valid shell-like argument text: {exc}") from exc
        return cls(parts, roles, capabilities, name=name, max_output_bytes=max_output_bytes)

    def set_process_observer(self, observer: ProcessObserver | None) -> None:
        self._observer = observer

    def set_process_released(self, released: ProcessObserver | None) -> None:
        if released is not None and not callable(released):
            raise TypeError("process release observer must be callable or None")
        self._process_released = released

    def process_info(self) -> tuple[int | None, int | None]:
        process = self._process
        if process is None:
            return (None, None)
        # Retain the original session identity until cleanup confirms the whole group has
        # exited. A reaped leader alone is not evidence that its descendants have exited.
        return (process.pid, process.pid)

    @staticmethod
    def _cleanup_owned_process(process: subprocess.Popen[bytes]) -> bool:
        """Bound cleanup to the private group created by this exact Popen invocation."""
        pgid = process.pid
        if pgid <= 1 or pgid == os.getpgrp():
            return False

        def alive() -> bool:
            try:
                os.killpg(pgid, 0)
                return True
            except ProcessLookupError:
                return False
            except PermissionError:
                # Some systems briefly report EPERM between SIGTERM and reaping. It does
                # not prove absence; keep checking within the same bounded grace period.
                return True

        try:
            for sig in (signal.SIGTERM, signal.SIGKILL):
                if not alive():
                    process.poll()
                    return True
                try:
                    if os.getpgid(process.pid) != pgid:
                        return False
                except ProcessLookupError:
                    # The group may retain descendants after this Popen leader was reaped.
                    if process.poll() is None:
                        return False
                try:
                    os.killpg(pgid, sig)
                except ProcessLookupError:
                    process.poll()
                    return True
                deadline = monotonic() + 0.25
                while monotonic() < deadline:
                    process.poll()
                    if not alive():
                        return True
                    time.sleep(0.01)
            process.poll()
            return not alive()
        except OSError:
            return False

    def _communicate_owned(
        self, process: subprocess.Popen[bytes], payload: bytes, timeout: float | None,
    ) -> tuple[bytes, bytes]:
        deadline = None if timeout is None else monotonic() + timeout
        first = True
        while True:
            self._check_continuation()
            remaining = None if deadline is None else deadline - monotonic()
            if remaining is not None and remaining <= 0:
                raise subprocess.TimeoutExpired(self.command, timeout)
            try:
                return process.communicate(
                    input=payload if first else None,
                    timeout=0.05 if remaining is None else min(0.05, remaining),
                )
            except subprocess.TimeoutExpired:
                first = False
                if process.poll() is not None:
                    # An exited leader can leave descendants holding stdout/stderr open.
                    # Close their private group before waiting for the remaining pipe bytes.
                    if not self._cleanup_owned_process(process):
                        raise AgentInvocationError("agent process cleanup could not be confirmed")
                    return process.communicate(timeout=0.25)

    def _release_owned_process(self, process: subprocess.Popen[bytes]) -> None:
        # The callback belongs to the original invocation even if a legacy caller configures
        # a different observer before retrying cleanup. A failed callback retains the handle.
        if self._active_process_released is not None:
            self._active_process_released(process.pid, process.pid)
        if self._process is process:
            self._process = None
            self._active_process_released = None

    def run(self, request: AgentRequest) -> AgentResult:
        if not self._run_lock.acquire(blocking=False):
            raise AgentInvocationError("command adapter already has an active invocation")
        try:
            return self._run(request)
        finally:
            self._run_lock.release()

    def _run(self, request: AgentRequest) -> AgentResult:
        if not isinstance(request, AgentRequest):
            raise TypeError("request must be an AgentRequest")
        self._check_continuation()
        retained = self._process
        if retained is not None:
            if not self._cleanup_owned_process(retained):
                raise AgentInvocationError("agent process cleanup could not be confirmed")
            self._release_owned_process(retained)
        request.workspace.mkdir(parents=True, exist_ok=True)
        process: subprocess.Popen[bytes] | None = None
        released = self._process_released
        try:
            self._check_continuation()
            process = subprocess.Popen(
                self.command,
                cwd=request.workspace,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            self._process = process
            self._active_process_released = released
            if self._observer is not None:
                # start_new_session assigns a dedicated group with the child's PID even if
                # the short-lived group leader exits before its observer runs.
                self._observer(process.pid, process.pid)
            self._check_continuation()
            payload = json.dumps(request.to_dict(), ensure_ascii=False, sort_keys=True).encode("utf-8")
            stdout, stderr = self._communicate_owned(process, payload, request.timeout)
        except subprocess.TimeoutExpired as exc:
            raise AgentInvocationError(
                f"agent {self.name} timed out after {request.timeout}s"
            ) from exc
        except OSError as exc:
            raise AgentInvocationError(_bounded_error(f"could not start agent: {exc}")) from exc
        finally:
            if process is not None:
                cleaned = self._cleanup_owned_process(process)
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None:
                        try:
                            stream.close()
                        except OSError:
                            pass
                if cleaned:
                    self._release_owned_process(process)
                else:
                    # Keep the handle available for a later cleanup retry. The owner must
                    # retain its durable registration instead of accepting a successful result.
                    raise AgentInvocationError("agent process cleanup could not be confirmed")
        self._check_continuation()
        if len(stdout) > self.max_output_bytes:
            raise AgentInvocationError(f"agent stdout exceeds {self.max_output_bytes} bytes")
        if len(stderr) > 16_000:
            raise AgentInvocationError("agent stderr exceeds 16000 bytes")
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()[-2_000:]
            suffix = f": {detail}" if detail else ""
            raise AgentInvocationError(
                f"agent exited with code {process.returncode}{suffix}"
            )
        try:
            output = stdout.decode("utf-8").strip()
        except UnicodeDecodeError as exc:
            raise AgentInvocationError("agent stdout is not valid UTF-8") from exc
        if not output:
            raise AgentInvocationError("agent returned empty stdout")
        return self._normalize_output(output, request)

    def cancel(self) -> None:
        process = self._process
        if process is not None and not self._cleanup_owned_process(process):
            raise AgentInvocationError("agent process cleanup could not be confirmed")

    def _normalize_output(self, output: str, request: AgentRequest) -> AgentResult:
        payload: object
        if output[:1] in {"{", "["}:
            try:
                payload = json.loads(output)
            except json.JSONDecodeError as exc:
                raise AgentInvocationError("agent stdout contains malformed JSON") from exc
            if not isinstance(payload, dict):
                raise AgentInvocationError("agent JSON response must be an object")
        else:
            payload = {"status": "succeeded", "text": output}
        assert isinstance(payload, dict)
        raw_status = payload.get("status")
        raw_error = payload.get("error")
        status = raw_status if raw_status is not None else ("failed" if raw_error else "succeeded")
        if "text" in payload:
            text = payload["text"]
        elif "result" in payload:
            text = payload["result"]
        elif "files" in payload:
            # Bundle generation validates the complete object itself. Preserve its original
            # JSON so duplicate fields and mixed single-/multi-file shapes cannot be erased
            # by adapter normalization before the bundle parser sees them.
            text = output
        elif "source" in payload:
            # Preserve optional candidate filename/metadata for AgentCandidateGenerator while
            # keeping the shared AgentResult text contract unchanged.
            text = json.dumps(
                {
                    "source": payload["source"],
                    **({"filename": payload["filename"]} if "filename" in payload else {}),
                    **({"metadata": payload["metadata"]} if "metadata" in payload else {}),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        else:
            text = ""
        artifacts = payload.get("artifacts", ())
        metadata = payload.get("metadata", {})
        if not isinstance(status, str):
            raise AgentInvocationError("agent response status must be a string")
        if not isinstance(text, str):
            raise AgentInvocationError("agent response text must be a string")
        if not isinstance(artifacts, (list, tuple)):
            raise AgentInvocationError("agent response artifacts must be an array")
        if raw_error is not None and not isinstance(raw_error, str):
            raise AgentInvocationError("agent response error must be a string")
        if not isinstance(metadata, Mapping):
            raise AgentInvocationError("agent response metadata must be an object")
        try:
            return AgentResult(
                adapter_name=self.name,
                role=request.role,
                text=text,
                artifacts=tuple(artifacts),
                metadata={**dict(metadata), "command": self.command[0]},
                status=status,
                error=raw_error,
            )
        except (TypeError, ValueError) as exc:
            raise AgentInvocationError(_bounded_error(str(exc))) from exc


class AgentRegistry:
    """Explicit deterministic registry of local Agent adapter configurations.

    ``select`` retains the existing direct-invocation contract. Concurrent worker attempts
    instead use ``create_execution_adapter``: registered instances are configuration prototypes,
    and each attempt owns its adapter, runtime, cancellation state, and observers.
    """

    def __init__(self, adapters: Sequence[AgentAdapter] = ()) -> None:
        self._adapters: dict[str, AgentAdapter] = {}
        self._execution_factories: dict[str, Callable[[], AgentAdapter]] = {}
        self._execution_lock = threading.RLock()
        self._issued_objects: weakref.WeakValueDictionary[int, object] = weakref.WeakValueDictionary()
        # Some third-party adapters use slots without weak-reference support. Retaining them
        # is necessary to reject a factory that returns the same execution object again.
        self._retained_objects: dict[int, object] = {}
        for adapter in adapters:
            self.register(adapter)

    def register(
        self,
        adapter: AgentAdapter,
        *,
        execution_factory: Callable[[], AgentAdapter] | None = None,
    ) -> AgentAdapter:
        """Register a prototype and, for custom adapters, an explicit fresh-instance factory.

        Factories must construct all mutable execution state independently; a shallow copy or
        a new wrapper around shared cancellation, process, or session state is not sufficient.
        """
        if execution_factory is not None and not callable(execution_factory):
            raise TypeError("execution_factory must be callable or None")
        name = _token(getattr(adapter, "name", None), "adapter name")
        roles = _tokens(getattr(adapter, "roles", ()), "roles")
        capabilities = _tokens(getattr(adapter, "capabilities", ()), "capabilities")
        required_methods = ("run", "cancel", "process_info", "set_process_observer")
        if any(not callable(getattr(adapter, method, None)) for method in required_methods):
            raise TypeError("adapter does not implement the AgentAdapter lifecycle")
        if name in self._adapters:
            raise ValueError(f"duplicate adapter name: {name}")
        # Validate declarations even when an adapter supplied mutable sets.
        try:
            adapter.roles = roles
            adapter.capabilities = capabilities
        except (AttributeError, TypeError):
            pass
        with self._execution_lock:
            if name in self._adapters:
                raise ValueError(f"duplicate adapter name: {name}")
            self._adapters[name] = adapter
            if execution_factory is not None:
                self._execution_factories[name] = execution_factory
        return adapter

    def get(self, name: str) -> AgentAdapter | None:
        return self._adapters.get(name)

    @property
    def adapters(self) -> tuple[AgentAdapter, ...]:
        """Return registered adapters in deterministic name order."""
        return tuple(self._adapters[name] for name in sorted(self._adapters))

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))

    def select(
        self,
        role: str,
        required_capabilities: Sequence[str] = (),
        preferred: str | None = None,
    ) -> AgentAdapter:
        role = _token(role, "role")
        required = _tokens(required_capabilities, "required_capabilities")

        def compatible(adapter: AgentAdapter) -> bool:
            return role in frozenset(adapter.roles) and required.issubset(
                frozenset(adapter.capabilities)
            )

        if preferred is not None:
            preferred_name = _token(preferred, "preferred adapter")
            adapter = self._adapters.get(preferred_name)
            if adapter is None:
                raise AgentSelectionError(f"preferred adapter is not registered: {preferred_name}")
            if not compatible(adapter):
                missing = sorted(required - frozenset(adapter.capabilities))
                reason = f"missing capabilities: {', '.join(missing)}" if missing else "role mismatch"
                raise AgentSelectionError(
                    f"preferred adapter {preferred_name} is incompatible ({reason})"
                )
            return adapter
        candidates = [adapter for adapter in self._adapters.values() if compatible(adapter)]
        if not candidates:
            requested = ", ".join(sorted(required)) or "none"
            raise AgentSelectionError(
                f"no registered adapter supports role {role!r} and capabilities {requested}"
            )
        return min(candidates, key=lambda item: (item.name, item.__class__.__name__))

    def create_execution_adapter(
        self,
        role: str,
        required_capabilities: Sequence[str] = (),
        preferred: str | None = None,
    ) -> AgentAdapter:
        """Select an adapter and allocate a fresh, exclusively owned execution instance.

        Built-in commands are reconstructed from immutable configuration. Runtime adapters
        require an explicit runtime factory, because runtimes can contain locks, sessions,
        model clients, and cancellation events that cannot safely be copied. Custom adapter
        types, including subclasses of built-ins, require ``register(execution_factory=...)``.
        """
        with self._execution_lock:
            selected = self.select(role, required_capabilities, preferred)
            factory = self._execution_factories.get(selected.name)
            if factory is not None:
                try:
                    execution = factory()
                except Exception as exc:
                    raise AgentInvocationError("execution adapter factory failed") from exc
            elif type(selected) is CommandAgentAdapter:
                execution = CommandAgentAdapter(
                    selected.command,
                    roles=tuple(selected.roles),
                    capabilities=tuple(selected.capabilities),
                    name=selected.name,
                    max_output_bytes=selected.max_output_bytes,
                )
            elif type(selected) is RuntimeAgentAdapter:
                if selected.runtime_factory is None:
                    raise AgentInvocationError(
                        f"adapter {selected.name} requires an independent runtime_factory"
                    )
                try:
                    runtime = selected.runtime_factory()
                except Exception as exc:
                    raise AgentInvocationError("execution runtime factory failed") from exc
                execution = RuntimeAgentAdapter(
                    runtime,
                    name=selected.name,
                    roles=tuple(selected.roles),
                    capabilities=tuple(selected.capabilities),
                    runtime_factory=selected.runtime_factory,
                )
            else:
                raise AgentInvocationError(
                    f"adapter {selected.name} requires an independent execution_factory"
                )
            self._validate_execution_adapter(selected, execution)
            return execution

    def _validate_execution_adapter(
        self, prototype: AgentAdapter, execution: AgentAdapter,
    ) -> None:
        required_methods = ("run", "cancel", "process_info", "set_process_observer")
        if any(not callable(getattr(execution, method, None)) for method in required_methods):
            raise AgentInvocationError("execution factory returned an invalid adapter")
        try:
            declarations_match = (
                execution.name == prototype.name
                and _tokens(execution.roles, "roles") == frozenset(prototype.roles)
                and _tokens(execution.capabilities, "capabilities") == frozenset(prototype.capabilities)
            )
        except (AttributeError, TypeError, ValueError) as exc:
            raise AgentInvocationError("execution factory returned invalid adapter declarations") from exc
        if not declarations_match:
            raise AgentInvocationError("execution factory changed adapter declarations")

        objects: list[object] = [execution]
        registered_objects: list[object] = list(self._adapters.values())
        registered_objects.extend(
            adapter.runtime for adapter in self._adapters.values()
            if isinstance(adapter, RuntimeAgentAdapter)
        )
        if isinstance(execution, RuntimeAgentAdapter):
            runtime = execution.runtime
            if any(not callable(getattr(runtime, method, None)) for method in required_methods):
                raise AgentInvocationError("execution runtime factory returned an invalid runtime")
            objects.append(runtime)
        for item in objects:
            if any(item is registered for registered in registered_objects):
                raise AgentInvocationError("execution factory reused a registered adapter or runtime")
            if (self._issued_objects.get(id(item)) is item
                    or self._retained_objects.get(id(item)) is item):
                raise AgentInvocationError("execution factory reused a prior adapter or runtime")
        for item in objects:
            try:
                self._issued_objects[id(item)] = item
            except TypeError:
                self._retained_objects[id(item)] = item


def _bounded_error(value: object) -> str:
    text = " ".join(str(value).split()).strip() or "agent invocation failed"
    return text[-8_000:]


__all__ = [
    "AgentAdapter",
    "AgentError",
    "AgentInvocationError",
    "AgentRegistry",
    "AgentRequest",
    "AgentResult",
    "AgentSelectionError",
    "CandidateGenerationBudget",
    "CandidateGenerationDiagnostic",
    "CommandAgentAdapter",
    "RuntimeAgentAdapter",
]
