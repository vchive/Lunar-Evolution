"""Execution boundary for local Lunar Evolution runtimes.

The module intentionally contains no Hermes/OpenCode/Codex discovery. A runtime is either a
repository-owned deterministic mock, an explicitly configured subprocess, or an explicitly
configured OpenAI-compatible HTTP endpoint.
"""

from __future__ import annotations

import json
import math
import os
import re
import shlex
import signal
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen

from .http_transport import TransportFailure, TransportObservation, exchange, validate_timeout

MAX_ENVELOPE_ARTIFACTS = 32
MAX_ENVELOPE_BYTES = 256 * 1024
MAX_ENVELOPE_METADATA = 16
MAX_ENVELOPE_METADATA_BYTES = 2_000
_SECRET_RE = re.compile(
    r"(?i)(?:sk-[A-Za-z0-9_-]{12,}|bearer\s+[A-Za-z0-9._-]{12,}|api[_-]?key\s*[:=]\s*\S+)"
)


@dataclass(frozen=True)
class RuntimeResult:
    text: str
    artifacts: tuple[str, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, object]


@dataclass(frozen=True)
class ModelTurn:
    text: str
    tool_calls: tuple[ToolCall, ...] = ()
    response_model: str | None = None
    usage: dict[str, int] | None = None


class Runtime(Protocol):
    name: str

    def run(self, prompt: str, workspace: Path, timeout: float | None = None) -> RuntimeResult:
        """Execute one bounded task inside ``workspace``."""

    def cancel(self) -> None:
        """Request cancellation of the active invocation, when supported."""

    def process_info(self) -> tuple[int | None, int | None]:
        """Return local PID/PGID for detached cancellation, or ``(None, None)``."""

    def set_process_observer(
        self, observer: Callable[[int, int | None], None] | None
    ) -> None:
        """Observe a spawned local process, if the adapter supports one."""


class RuntimeExecutionError(RuntimeError):
    """A runtime returned a non-successful or unusable result."""


MODEL_FAILURE_REASONS = frozenset({
    "http_error", "transport_timeout", "transport_error", "invalid_json",
    "invalid_response_shape", "empty_response", "invalid_tool_calls",
    "invalid_model_identity", "invalid_usage",
})


@dataclass(frozen=True)
class ModelFailureEvidence:
    """Fixed observations of an existing rejection, never provider prose or root cause."""

    reason: str
    response_status: int | None


MAX_REQUEST_OBSERVATION_MS = 10**12


@dataclass(frozen=True)
class ModelRequestObservation:
    """Local failed-request phase and elapsed time, not a transport deadline guarantee."""

    phase: str
    elapsed_ms: int
    request_timeout_ms: int | None


class ModelRequestFailure(RuntimeExecutionError):
    """A terminal model failure carrying an optional, independently validated projection."""

    def __init__(self, message: str, reason: str, response_status: int | None = None) -> None:
        super().__init__(message)
        self.evidence = ModelFailureEvidence(reason, response_status)
        self.observation: ModelRequestObservation | None = None
        self.transport_observation: TransportObservation | None = None


def _request_clock() -> float | None:
    try:
        return monotonic()
    except Exception:  # noqa: BLE001 - observing time cannot change request execution
        return None


def _transport_detail(value: object) -> TransportObservation | None:
    try:
        observation = value.observation
        return observation if type(observation) is TransportObservation else None
    except Exception:  # noqa: BLE001 - optional evidence must not mask the HTTP outcome
        return None


def _request_observation(
    phase: str, started: float | None, timeout: float | None,
) -> ModelRequestObservation | None:
    try:
        ended = monotonic()
        if any(type(value) not in (int, float) or not math.isfinite(value)
               for value in (started, ended)) or ended < started:
            return None
        elapsed_ms = math.floor((ended - started) * 1000)
        if timeout is None:
            timeout_ms = None
        elif type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            return None
        else:
            timeout_ms = math.floor(timeout * 1000)
        if any(value is not None and not 0 <= value <= MAX_REQUEST_OBSERVATION_MS
               for value in (elapsed_ms, timeout_ms)):
            return None
        return ModelRequestObservation(phase, elapsed_ms, timeout_ms)
    except Exception:  # noqa: BLE001 - invalid clock/projection must preserve the original failure
        return None


def _observed_response_status(value: object) -> int | None:
    return value if type(value) is int and 100 <= value <= 599 else None


def _transport_failure_reason(error: BaseException) -> str:
    current: BaseException | None = error
    seen: set[int] = set()
    for _ in range(8):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        if isinstance(current, TimeoutError):
            return "transport_timeout"
        # Only urllib's concrete error has a known reason field. Never interpret string reasons
        # or look for arbitrary provider exception attributes.
        try:
            reason = current.reason if type(current) is URLError else None
            current = reason if isinstance(reason, BaseException) else current.__cause__
        except Exception:  # noqa: BLE001 - diagnostic inspection must not mask a transport error
            break
    return "transport_error"


class MockRuntime:
    """Deterministic runtime used for smoke runs and controller tests."""

    name = "mock"

    def run(self, prompt: str, workspace: Path, timeout: float | None = None) -> RuntimeResult:
        del timeout
        workspace.mkdir(parents=True, exist_ok=True)
        excerpt = " ".join(prompt.strip().split())[:240]
        # Keep runtime-backed evolution smoke tests deterministic. The role bridges still parse
        # these responses through CandidateDraft/EvaluationReport, so this fixture does not bypass
        # the production validity boundary.
        if "Return exactly one JSON EvaluationReport object" in prompt:
            return RuntimeResult(
                text=json.dumps(
                    {
                        "schema_version": "1",
                        "evaluator_id": "repository-mock",
                        "validity": 1,
                        "quality": 1.0,
                        "combined_score": 1.0,
                        "detailed_scores": {},
                        "error_info": [],
                    }
                ),
                metadata={"provider": "repository-mock"},
            )
        if "You are the solver in a bounded local algorithm-evolution run." in prompt:
            return RuntimeResult(
                text="def solve():\n    return 0\n",
                metadata={"provider": "repository-mock"},
            )
        # Keep the repository-owned smoke runtime useful for the strict specialist role DAG.
        # These fixtures are emitted only when the task prompt explicitly declares the role path;
        # ordinary generic runs remain text-only and therefore exercise the legacy contract.
        if "data/processed/data-profile.json" in prompt:
            profile = workspace / "data" / "processed" / "data-profile.json"
            profile.parent.mkdir(parents=True, exist_ok=True)
            profile.write_text(
                json.dumps(
                    {
                        "schema_version": "1",
                        "inputs": [
                            {
                                "path": "data/raw/input.json",
                                "format": "json",
                                "row_count": 0,
                                "columns": [],
                                "issues": ["mock runtime did not receive a staged input file"],
                            }
                        ],
                        "notes": "deterministic repository mock profile",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        if "solve/problem-formulation.md" in prompt:
            formulation = workspace / "solve" / "problem-formulation.md"
            formulation.parent.mkdir(parents=True, exist_ok=True)
            formulation.write_text(
                "# Mock formulation\n\nThe validated contract remains authoritative.\n",
                encoding="utf-8",
            )
        if "evaluate/evaluation.json" in prompt:
            report = workspace / "evaluate" / "evaluation.json"
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(
                json.dumps(
                    {
                        "schema_version": "1",
                        "evaluator_id": "repository-mock",
                        "validity": 1,
                        "quality": 1.0,
                        "combined_score": 1.0,
                        "detailed_scores": {},
                        "error_info": [],
                    }
                ),
                encoding="utf-8",
            )
        if "evaluate/review.md" in prompt:
            review = workspace / "evaluate" / "review.md"
            review.parent.mkdir(parents=True, exist_ok=True)
            review.write_text(
                "# Mock review\n\nEvidence is bounded and locally verified.\n",
                encoding="utf-8",
            )
        return RuntimeResult(
            text=f"Mock runtime completed the task: {excerpt}",
            metadata={"provider": "repository-mock"},
        )

    def cancel(self) -> None:
        return None

    def process_info(self) -> tuple[int | None, int | None]:
        return (None, None)

    def set_process_observer(
        self, observer: Callable[[int, int | None], None] | None
    ) -> None:
        del observer


class SubprocessRuntime:
    """Run an explicitly configured command, without searching agent-specific global state."""

    name = "subprocess"

    def __init__(self, command: str | list[str] | tuple[str, ...] | None = None) -> None:
        configured = command if command is not None else os.environ.get("LUNAR_EVOLUTION_RUNTIME_COMMAND")
        if isinstance(configured, str):
            self.command = tuple(shlex.split(configured))
        elif configured:
            self.command = tuple(configured)
        else:
            self.command = ()
        if not self.command:
            raise ValueError(
                "subprocess runtime requires LUNAR_EVOLUTION_RUNTIME_COMMAND or an explicit command"
            )
        self._process: subprocess.Popen[str] | None = None
        self._process_observer: Callable[[int, int | None], None] | None = None
        self._process_released: Callable[[int, int | None], None] | None = None
        self._process_pgid: int | None = None

    def set_process_observer(
        self, observer: Callable[[int, int | None], None] | None
    ) -> None:
        self._process_observer = observer

    def set_process_released(
        self, released: Callable[[int, int | None], None] | None
    ) -> None:
        self._process_released = released

    @staticmethod
    def _cleanup_owned_process(process: subprocess.Popen[str], pgid: int) -> bool:
        """Bound cleanup to the private session created for this exact Popen invocation."""
        if pgid != process.pid or pgid <= 1 or pgid == os.getpgrp():
            return False

        def alive() -> bool:
            try:
                os.killpg(pgid, 0)
                return True
            except ProcessLookupError:
                return False

        try:
            for sig in (signal.SIGTERM, signal.SIGKILL):
                if not alive():
                    process.poll()
                    return True
                # A live leader must still belong to its original private group. Once this
                # invocation reaps its leader, the retained group may contain its descendants.
                try:
                    if os.getpgid(process.pid) != pgid:
                        return False
                except ProcessLookupError:
                    if process.poll() is None:
                        # Another thread may have reaped the leader while still holding
                        # Popen's wait lock, before publishing its return code. Only a new
                        # observation that this exact group is absent confirms cleanup.
                        return not alive()
                try:
                    os.killpg(pgid, sig)
                except ProcessLookupError:
                    process.poll()
                    return True
                deadline = monotonic() + 0.25
                last_probe_denied = False
                while monotonic() < deadline:
                    process.poll()
                    try:
                        if not alive():
                            return True
                        last_probe_denied = False
                    except PermissionError:
                        # A terminating group can briefly deny a probe. Keep this unknown
                        # within the existing wait window; it grants no signal authority.
                        last_probe_denied = True
                    time.sleep(0.01)
                if last_probe_denied:
                    return False
            process.poll()
            return not alive()
        except OSError:
            return False

    def _communicate_owned(
        self, process: subprocess.Popen[str], prompt: str, timeout: float | None, pgid: int,
    ) -> tuple[str, str]:
        deadline = None if timeout is None else monotonic() + timeout
        first = True
        while True:
            remaining = None if deadline is None else deadline - monotonic()
            if remaining is not None and remaining <= 0:
                raise subprocess.TimeoutExpired(self.command, timeout)
            try:
                result = process.communicate(
                    input=prompt if first else None,
                    timeout=0.05 if remaining is None else min(0.05, remaining),
                )
                return result
            except subprocess.TimeoutExpired:
                first = False
                if process.poll() is not None:
                    # Descendants can keep inherited pipes open after the leader exits.
                    self._cleanup_owned_process(process, pgid)
                    return process.communicate(timeout=0.25)

    def run(self, prompt: str, workspace: Path, timeout: float | None = None) -> RuntimeResult:
        workspace.mkdir(parents=True, exist_ok=True)
        process: subprocess.Popen[str] | None = None
        observer, released = self._process_observer, self._process_released
        pgid: int | None = None
        cleaned = True
        try:
            process = subprocess.Popen(
                self.command,
                cwd=workspace,
                text=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                **({"start_new_session": True} if observer is not None else {}),
            )
            self._process = process
            if observer is not None:
                # Successful start_new_session makes the child its own process-group leader.
                pgid = process.pid
                self._process_pgid = pgid
                try:
                    observer(process.pid, pgid)
                except Exception as observer_error:  # noqa: BLE001 - metadata must not break execution
                    del observer_error
            stdout, stderr = (
                self._communicate_owned(process, prompt, timeout, pgid)
                if pgid is not None else process.communicate(input=prompt, timeout=timeout)
            )
        except subprocess.TimeoutExpired as exc:
            if process is not None:
                if pgid is not None:
                    self._cleanup_owned_process(process, pgid)
                else:
                    process.kill()
                    process.communicate()
            raise RuntimeExecutionError(f"runtime timed out after {timeout}s") from exc
        except OSError as exc:
            raise RuntimeExecutionError(f"could not start runtime: {exc}") from exc
        finally:
            if process is not None and pgid is not None:
                cleaned = self._cleanup_owned_process(process, pgid)
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None:
                        try:
                            stream.close()
                        except OSError:
                            pass
                if cleaned and released is not None:
                    try:
                        released(process.pid, pgid)
                    except Exception as release_error:  # noqa: BLE001 - metadata preserves outcome
                        del release_error
            self._process = None
            self._process_pgid = None
        if not cleaned:
            raise RuntimeExecutionError("runtime process cleanup could not be confirmed")
        if process.returncode != 0:
            detail = stderr.strip()[-2000:]
            suffix = f": {detail}" if detail else ""
            raise RuntimeExecutionError(
                f"runtime exited with code {process.returncode}{suffix}"
            )
        output = stdout.strip()
        if not output:
            raise RuntimeExecutionError("runtime returned empty stdout")
        return RuntimeResult(
            text=output,
            metadata={"provider": "explicit-subprocess", "command": self.command[0]},
        )

    def cancel(self) -> None:
        process, pgid = self._process, self._process_pgid
        if process is not None:
            if pgid is not None:
                self._cleanup_owned_process(process, pgid)
            elif process.poll() is None:
                process.terminate()

    def process_info(self) -> tuple[int | None, int | None]:
        process = self._process
        if process is None or process.poll() is not None:
            return (None, None)
        try:
            return (process.pid, os.getpgid(process.pid))
        except OSError:
            return (process.pid, None)


class OpenAICompatibleRuntime:
    """Call an explicitly configured OpenAI-compatible chat endpoint.

    This adapter intentionally uses only the standard library. It works with local Ollama/vLLM/
    LM Studio servers as well as hosted gateways, while keeping endpoint and credential discovery
    explicit and independent from Hermes/OpenCode/Codex.
    """

    name = "openai-compatible"

    def __init__(
        self,
        endpoint: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        configured_endpoint = endpoint or os.environ.get("LUNAR_EVOLUTION_MODEL_ENDPOINT")
        if not configured_endpoint or not configured_endpoint.strip():
            raise ValueError(
                "openai-compatible runtime requires --endpoint or LUNAR_EVOLUTION_MODEL_ENDPOINT"
            )
        parsed = urlparse(configured_endpoint.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("model endpoint must be an absolute http(s) URL")
        self.endpoint = self._chat_endpoint(configured_endpoint.strip())
        self.model = (model or os.environ.get("LUNAR_EVOLUTION_MODEL") or "local").strip()
        if not self.model:
            raise ValueError("model must not be empty")
        self.api_key = api_key if api_key is not None else os.environ.get("LUNAR_EVOLUTION_API_KEY")

    @staticmethod
    def _chat_endpoint(endpoint: str) -> str:
        parsed = urlparse(endpoint)
        path = parsed.path.rstrip("/")
        if path.endswith("/chat/completions"):
            return endpoint
        updated = parsed._replace(path=f"{path}/chat/completions")
        return urlunparse(updated)

    def run(self, prompt: str, workspace: Path, timeout: float | None = None) -> RuntimeResult:
        workspace.mkdir(parents=True, exist_ok=True)
        turn = self.complete(
            [{"role": "user", "content": prompt}],
            tools=(),
            timeout=timeout,
        )
        if turn.tool_calls:
            raise RuntimeExecutionError(
                "model returned tool calls; use --agent-loop for tool execution"
            )
        if not turn.text:
            raise RuntimeExecutionError("model endpoint returned empty content")
        text, artifacts, envelope_metadata = self._materialize_artifact_envelope(turn.text, workspace)
        telemetry_metadata: dict[str, str] = {}
        if turn.response_model:
            telemetry_metadata["response_model"] = turn.response_model
        if turn.usage:
            telemetry_metadata.update({key: str(value) for key, value in turn.usage.items()})
        return RuntimeResult(
            text=text,
            artifacts=artifacts,
            metadata={
                "provider": "openai-compatible",
                "model": self.model,
                **telemetry_metadata,
                **envelope_metadata,
            },
        )

    def _materialize_artifact_envelope(
        self, text: str, workspace: Path
    ) -> tuple[str, tuple[str, ...], dict[str, str]]:
        """Decode an optional one-shot ``{text, artifacts}`` response and write confined files."""
        try:
            payload = json.loads(text)
        except (TypeError, json.JSONDecodeError):
            return text, (), {}
        if not isinstance(payload, dict) or "artifacts" not in payload:
            return text, (), {}
        if set(payload) - {"text", "artifacts", "metadata"}:
            raise RuntimeExecutionError("artifact envelope contains unknown fields")
        envelope_text = payload.get("text")
        if not isinstance(envelope_text, str):
            raise RuntimeExecutionError("artifact envelope text must be a string")
        raw_artifacts = payload.get("artifacts")
        if not isinstance(raw_artifacts, list) or len(raw_artifacts) > MAX_ENVELOPE_ARTIFACTS:
            raise RuntimeExecutionError(
                f"artifact envelope must contain at most {MAX_ENVELOPE_ARTIFACTS} files"
            )
        root = workspace.expanduser()
        if root.exists() and root.is_symlink():
            raise RuntimeExecutionError("artifact envelope workspace must not be a symlink")
        root = root.resolve(strict=False)
        root.mkdir(parents=True, exist_ok=True)
        entries: list[tuple[str, Path, bytes]] = []
        seen: set[str] = set()
        total_bytes = 0
        for item in raw_artifacts:
            if not isinstance(item, dict) or set(item) != {"path", "content"}:
                raise RuntimeExecutionError("artifact envelope entries require path and content")
            relative = item["path"]
            content = item["content"]
            if not isinstance(relative, str) or not relative.strip():
                raise RuntimeExecutionError("artifact envelope path must be non-empty")
            if (
                "\\" in relative
                or "\x00" in relative
                or Path(relative).is_absolute()
                or any(part in {"", ".", ".."} for part in relative.split("/"))
            ):
                raise RuntimeExecutionError("artifact envelope paths must be portable relative paths")
            if relative in seen:
                raise RuntimeExecutionError(f"artifact envelope contains duplicate path: {relative}")
            seen.add(relative)
            if not isinstance(content, str):
                raise RuntimeExecutionError("artifact envelope content must be a string")
            encoded = content.encode("utf-8")
            total_bytes += len(encoded)
            if total_bytes > MAX_ENVELOPE_BYTES:
                raise RuntimeExecutionError(
                    f"artifact envelope exceeds {MAX_ENVELOPE_BYTES} bytes"
                )
            raw = root / relative
            if self._path_has_symlink(root, raw):
                raise RuntimeExecutionError(f"artifact envelope path is symlinked: {relative}")
            resolved = raw.resolve(strict=False)
            try:
                resolved.relative_to(root)
            except ValueError as exc:
                raise RuntimeExecutionError(
                    f"artifact envelope path escapes the workspace: {relative}"
                ) from exc
            entries.append((relative, resolved, encoded))
        raw_metadata = payload.get("metadata", {})
        if raw_metadata is None:
            raw_metadata = {}
        if not isinstance(raw_metadata, dict) or len(raw_metadata) > MAX_ENVELOPE_METADATA:
            raise RuntimeExecutionError("artifact envelope metadata must be a bounded string object")
        metadata: dict[str, str] = {}
        for key, value in raw_metadata.items():
            if (
                not isinstance(key, str)
                or not key.strip()
                or key in {"provider", "model", "artifact_envelope"}
                or not isinstance(value, str)
                or len(value.encode("utf-8")) > MAX_ENVELOPE_METADATA_BYTES
                or _SECRET_RE.search(value)
            ):
                raise RuntimeExecutionError("artifact envelope metadata is invalid")
            metadata[f"envelope_{key}"] = value
        for relative, target, encoded in entries:
            if self._path_has_symlink(root, target):
                raise RuntimeExecutionError(f"artifact envelope path is symlinked: {relative}")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and target.is_symlink():
                raise RuntimeExecutionError(f"artifact envelope path is symlinked: {relative}")
            temporary = target.with_name(f".{target.name}.tmp")
            temporary.write_bytes(encoded)
            temporary.replace(target)
        if entries:
            metadata["artifact_envelope"] = "true"
        return envelope_text, tuple(relative for relative, _, _ in entries), metadata

    @staticmethod
    def _path_has_symlink(root: Path, path: Path) -> bool:
        current = path
        while True:
            if current.exists() and current.is_symlink():
                return True
            if current == root:
                return False
            if current.parent == current:
                return True
            current = current.parent

    def complete(
        self,
        messages: list[dict[str, object]],
        tools: tuple[dict[str, object], ...] = (),
        timeout: float | None = None,
    ) -> ModelTurn:
        """Request one model turn, preserving structured tool calls for the agent loop."""
        if timeout is not None:
            validate_timeout(timeout)
        from .acceptance_request_budget import active_request_budget

        budget = active_request_budget()
        if budget is not None:
            budget.begin()
        try:
            turn = self._complete(messages, tools, timeout, bounded=timeout is not None)
        except BaseException:
            if budget is not None:
                budget.fail()
            raise
        if budget is not None:
            budget.finish(turn.usage)
        return turn

    def _complete_direct(self, messages, tools=(), timeout=None) -> ModelTurn:
        """Explicit same-process seam for deterministic transport/exception contract tests."""
        return self._complete(messages, tools, timeout, bounded=False)

    def _complete(self, messages, tools, timeout, *, bounded) -> ModelTurn:
        body = json.dumps(
            {
                "model": self.model,
                "messages": messages,
                "stream": False,
                **({"tools": list(tools)} if tools else {}),
            },
            ensure_ascii=False,
        ).encode("utf-8")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "lunar-evolution/0.1",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(self.endpoint, data=body, headers=headers, method="POST")
        observed_status = None
        phase = "open_response"
        transport_observation = None
        started = _request_clock()
        try:
            try:
                if bounded:
                    try:
                        response = exchange(request, timeout)
                    except TransportFailure as failure:
                        phase, observed_status = failure.phase, failure.status
                        transport_observation = _transport_detail(failure)
                        if failure.cause == "http_error":
                            cause = HTTPError("", failure.status, "HTTP request failed", {}, None)
                            detail = self._redact(failure.body.decode("utf-8", errors="replace"))
                            suffix = f": {detail}" if detail else ""
                            message = f"model endpoint returned HTTP {failure.status}{suffix}"
                        else:
                            cause = {
                                "timeout": TimeoutError("HTTP transport deadline exceeded"),
                                "cause_timeout": TimeoutError("HTTP transport timed out"),
                                "url_timeout": URLError(TimeoutError("HTTP transport timed out")),
                                "url_error": URLError("HTTP transport failed"),
                            }.get(failure.cause, OSError("HTTP transport failed"))
                            message = "could not reach model endpoint: HTTP transport failed"
                        raise ModelRequestFailure(message, failure.reason, failure.status) from cause
                    status, raw = response.status, response.body
                    transport_observation = _transport_detail(response)
                    observed_status = _observed_response_status(status)
                else:
                    with urlopen(request, timeout=timeout) as response:
                        status = response.getcode()
                        observed_status = _observed_response_status(status)
                        phase = "read_response_body"
                        raw = response.read(8 * 1024 * 1024)
            except HTTPError as exc:
                # This records entry into existing error-body handling, not its success or cause.
                phase = "read_http_error_body"
                detail = self._redact(self._read_error_body(exc))
                suffix = f": {detail}" if detail else ""
                raise ModelRequestFailure(
                    f"model endpoint returned HTTP {exc.code}{suffix}", "http_error",
                    _observed_response_status(exc.code),
                ) from exc
            except (TimeoutError, URLError, OSError) as exc:
                detail = self._redact(str(exc))
                raise ModelRequestFailure(
                    f"could not reach model endpoint: {detail}", _transport_failure_reason(exc),
                    observed_status,
                ) from exc
            phase = "validate_response"
            if status < 200 or status >= 300:
                raise ModelRequestFailure(
                    f"model endpoint returned HTTP {status}", "http_error", observed_status,
                )
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ModelRequestFailure(
                    "model endpoint returned malformed JSON", "invalid_json", observed_status,
                ) from exc
            text, tool_calls = self._extract_turn(payload, response_status=observed_status)
            if not text and not tool_calls:
                raise ModelRequestFailure(
                    "model endpoint returned empty content", self._empty_response_reason(payload),
                    observed_status,
                )
            response_model = payload.get("model")
            if response_model is not None and (
                not isinstance(response_model, str)
                or not response_model.strip()
                or len(response_model.encode("utf-8")) > 512
                or "\x00" in response_model
            ):
                raise ModelRequestFailure(
                    "model endpoint returned an invalid model identity", "invalid_model_identity",
                    observed_status,
                )
            usage = self._parse_usage(payload.get("usage"), response_status=observed_status)
            return ModelTurn(
                text=text,
                tool_calls=tool_calls,
                response_model=response_model.strip() if isinstance(response_model, str) else None,
                usage=usage,
            )
        except ModelRequestFailure as exc:
            if type(exc) is ModelRequestFailure:
                exc.transport_observation = transport_observation
                try:
                    exc.observation = _request_observation(phase, started, timeout)
                except Exception:  # noqa: BLE001, S110 - preserve error without logging request data
                    pass
            raise

    def cancel(self) -> None:
        # urllib does not expose a portable cancellation handle. Detached cancellation terminates
        # the controller process group; synchronous callers can only mark the run cancelled.
        return None

    def process_info(self) -> tuple[int | None, int | None]:
        return (None, None)

    def set_process_observer(
        self, observer: Callable[[int, int | None], None] | None
    ) -> None:
        del observer

    def _read_error_body(self, error: HTTPError) -> str:
        try:
            return error.read(2_000).decode("utf-8", errors="replace")
        except OSError:
            return ""

    def _redact(self, detail: str) -> str:
        if self.api_key:
            detail = detail.replace(self.api_key, "[REDACTED]")
        return detail[-2_000:]

    @staticmethod
    def _extract_turn(
        payload: object, *, response_status: int | None = None,
    ) -> tuple[str, tuple[ToolCall, ...]]:
        if not isinstance(payload, dict):
            return "", ()
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            choice = choices[0]
            if isinstance(choice, dict):
                text = ""
                message = choice.get("message")
                if isinstance(message, dict):
                    text = OpenAICompatibleRuntime._content_to_text(message.get("content"))
                    return text, OpenAICompatibleRuntime._parse_tool_calls(
                        message.get("tool_calls"), response_status=response_status,
                    )
                text = OpenAICompatibleRuntime._content_to_text(choice.get("text"))
                if text:
                    return text, ()
        message = payload.get("message")
        if isinstance(message, dict):
            content = OpenAICompatibleRuntime._content_to_text(message.get("content"))
            if content:
                return content, OpenAICompatibleRuntime._parse_tool_calls(
                    message.get("tool_calls"), response_status=response_status,
                )
        return OpenAICompatibleRuntime._content_to_text(payload.get("response")), ()

    @staticmethod
    def _empty_response_reason(payload: object) -> str:
        """Observe only an already rejected empty result; never participate in acceptance."""
        if isinstance(payload, dict):
            choices = payload.get("choices")
            if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                message = choices[0].get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    return ("empty_response" if content is None or isinstance(content, (str, list))
                            else "invalid_response_shape")
                if isinstance(choices[0].get("text"), (str, list)):
                    return "empty_response"
            message = payload.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if content is None or isinstance(content, (str, list)):
                    return "empty_response"
            if "response" in payload and (
                payload["response"] is None or isinstance(payload["response"], (str, list))
            ):
                return "empty_response"
        return "invalid_response_shape"

    @staticmethod
    def _extract_text(payload: object) -> str:
        """Compatibility helper for callers of the original one-shot adapter."""
        return OpenAICompatibleRuntime._extract_turn(payload)[0]

    @staticmethod
    def _parse_usage(raw: object, *, response_status: int | None = None) -> dict[str, int] | None:
        if raw is None:
            return None
        if not isinstance(raw, dict):
            raise ModelRequestFailure(
                "model endpoint returned malformed usage", "invalid_usage", response_status,
            )
        aliases = (
            ("input_tokens", "prompt_tokens"),
            ("output_tokens", "completion_tokens"),
            ("total_tokens", "total_tokens"),
        )
        values: dict[str, int] = {}
        for normalized, source in aliases:
            value = raw.get(source, raw.get(normalized))
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ModelRequestFailure(
                    "model endpoint returned malformed usage", "invalid_usage", response_status,
                )
            values[normalized] = value
        if values["input_tokens"] + values["output_tokens"] != values["total_tokens"]:
            raise ModelRequestFailure(
                "model endpoint returned inconsistent usage", "invalid_usage", response_status,
            )
        return values

    @staticmethod
    def _parse_tool_calls(raw: object, *, response_status: int | None = None) -> tuple[ToolCall, ...]:
        if raw is None:
            return ()
        if not isinstance(raw, list):
            raise ModelRequestFailure(
                "model returned malformed tool calls", "invalid_tool_calls", response_status,
            )
        calls: list[ToolCall] = []
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                raise ModelRequestFailure(
                    "model returned malformed tool call", "invalid_tool_calls", response_status,
                )
            function = item.get("function")
            if not isinstance(function, dict) or not isinstance(function.get("name"), str):
                raise ModelRequestFailure(
                    "model returned a tool call without a function name", "invalid_tool_calls",
                    response_status,
                )
            raw_arguments = function.get("arguments", {})
            if isinstance(raw_arguments, str):
                try:
                    raw_arguments = json.loads(raw_arguments)
                except json.JSONDecodeError as exc:
                    raise ModelRequestFailure(
                        "model returned malformed tool arguments", "invalid_tool_calls", response_status,
                    ) from exc
            if not isinstance(raw_arguments, dict):
                raise ModelRequestFailure(
                    "model tool arguments must be a JSON object", "invalid_tool_calls", response_status,
                )
            call_id = item.get("id")
            calls.append(
                ToolCall(
                    id=call_id if isinstance(call_id, str) and call_id else f"call-{index + 1}",
                    name=function["name"],
                    arguments=raw_arguments,
                )
            )
        return tuple(calls)

    @staticmethod
    def _content_to_text(content: object) -> str:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = [
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and isinstance(item.get("text"), str)
            ]
            return "".join(parts).strip()
        return ""


def build_runtime(
    name: str,
    command: str | Sequence[str] | None = None,
    endpoint: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
) -> Runtime:
    if name == "mock":
        return MockRuntime()
    if name == "subprocess":
        return SubprocessRuntime(command)
    if name == "openai-compatible":
        return OpenAICompatibleRuntime(endpoint, model, api_key)
    raise ValueError(f"unknown runtime {name!r}; choose mock, subprocess, or openai-compatible")
