"""Small, local tools exposed to the Build agent loop.

Tools receive a task workspace rather than the process working directory. Every filesystem operation
is resolved and checked before it is performed; command execution is opt-in and never uses a shell.
"""

from __future__ import annotations

import codecs
import json
import math
import os
import shlex
import sqlite3
import stat
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

from .memory import MemoryStore


class ToolError(ValueError):
    """A tool request is invalid or violates the local policy."""


@dataclass(frozen=True)
class ToolResult:
    output: str
    success: bool = True
    artifacts: tuple[str, ...] = ()
    awaiting_input: bool = False
    input_question: str | None = None
    input_options: tuple[str, ...] = ()


class LocalToolRegistry:
    """Registry for confined filesystem tools and an optional command tool."""

    def __init__(
        self,
        allow_exec: bool = False,
        command_timeout: float = 30.0,
        max_output_bytes: int = 20_000,
        memory: MemoryStore | None = None,
        memory_scope: str = "global",
        redactions: tuple[str, ...] = (),
        command_environment: dict[str, str] | None = None,
    ) -> None:
        if command_timeout <= 0:
            raise ValueError("command_timeout must be positive")
        if max_output_bytes <= 0:
            raise ValueError("max_output_bytes must be positive")
        self.allow_exec = allow_exec
        self.command_timeout = command_timeout
        self.max_output_bytes = max_output_bytes
        self.memory = memory
        self.memory_scope = memory_scope
        self.redactions = tuple(secret for secret in redactions if secret)
        self.command_environment = (
            None if command_environment is None else dict(command_environment)
        )
        self._execution_deadline: ContextVar[float | None] = ContextVar(
            "lunar_tool_execution_deadline", default=None
        )
        self._process_observer: Callable[[int, int | None], None] | None = None
        self._process_released: Callable[[int, int | None], None] | None = None
        # Worker tools are opt-in.  A normal AgentLoop never receives a WorkerService or
        # exposes these schemas; WorkerService installs the context only for an executing
        # worker attempt and clears it before releasing the attempt.
        self._worker_service = None
        self._worker_owner_id: str | None = None
        self._worker_parent_id: str | None = None
        self._continuation_guard: Callable[[], None] | None = None

    def set_process_observer(self, observer: Callable[[int, int | None], None] | None) -> None:
        self._process_observer = observer

    def set_process_released(self, released: Callable[[int, int | None], None] | None) -> None:
        self._process_released = released

    def set_continuation_guard(self, guard: Callable[[], None] | None) -> None:
        """Install the parent-attempt guard used by bounded worker waits."""
        if guard is not None and not callable(guard):
            raise TypeError("continuation guard must be callable or None")
        self._continuation_guard = guard

    def set_worker_context(
        self, service=None, owner_id: str | None = None, parent_worker_id: str | None = None,
    ) -> None:
        """Enable worker tools for one running worker attempt.

        The service is deliberately duck-typed here to keep the confined local-tool layer
        independent from the scheduler module and its Store import graph.
        """
        if service is None:
            if owner_id is not None or parent_worker_id is not None:
                raise ValueError("worker identity requires a WorkerService")
            self._worker_service = None
            self._worker_owner_id = None
            self._worker_parent_id = None
            return
        if not isinstance(owner_id, str) or not owner_id.strip():
            raise ValueError("worker owner identity must be non-empty")
        if parent_worker_id is not None and (
            not isinstance(parent_worker_id, str) or not parent_worker_id.strip()
        ):
            raise ValueError("parent worker identity must be non-empty")
        required_methods = ("dispatch", "wait", "cancel", "read_result_envelope")
        if any(not callable(getattr(service, name, None)) for name in required_methods):
            raise TypeError("worker service does not implement the local worker tool contract")
        if getattr(service, "store", None) is None:
            raise TypeError("worker service does not implement the local worker tool contract")
        self._worker_service = service
        self._worker_owner_id = owner_id
        self._worker_parent_id = parent_worker_id

    @contextmanager
    def execution_deadline(self, deadline: float) -> Iterator[None]:
        """Bind an internal invocation deadline without mutating registry configuration."""
        if (
            isinstance(deadline, bool) or not isinstance(deadline, (int, float))
            or not math.isfinite(deadline)
        ):
            raise ValueError("execution deadline must be finite")
        current = self._execution_deadline.get()
        token = self._execution_deadline.set(min(current, deadline) if current is not None else deadline)
        try:
            yield
        finally:
            self._execution_deadline.reset(token)

    def set_memory_scope(self, scope: str) -> None:
        """Set the default scope used by memory tools for the active task."""
        self.memory_scope = scope

    def schemas(self) -> tuple[dict[str, object], ...]:
        schemas: list[dict[str, object]] = [
            self._schema(
                "read_file",
                "Read a UTF-8 text file from the task workspace.",
                {
                    "path": {
                        "type": "string",
                        "description": (
                            "Path to a UTF-8 text file inside the task workspace; prefer a relative "
                            f"path. Preview uses at most the first {self.max_output_bytes} bytes, "
                            "plus a truncation marker if larger. A UTF-8 character split by the "
                            "cutoff is omitted. Repeating a call does not retrieve another page."
                        ),
                    }
                },
                ["path"],
            ),
            self._schema(
                "write_file",
                "Write UTF-8 text to a file in the task workspace and return its artifact path.",
                {
                    "path": {
                        "type": "string",
                        "description": (
                            "Destination inside the task workspace; prefer a relative path. "
                            "Creates missing parent directories and atomically replaces one file "
                            "after writing complete content."
                        ),
                    },
                    "content": {
                        "type": "string",
                        "description": "Complete replacement text, at most 1,000,000 UTF-8 bytes.",
                    },
                },
                ["path", "content"],
            ),
            self._schema(
                "list_dir",
                "List entries in a task workspace directory.",
                {
                    "path": {
                        "type": "string",
                        "description": (
                            "Directory inside the task workspace. Omit or use . for its root; "
                            "lists immediate entries only."
                        ),
                    }
                },
                [],
            ),
            self._schema(
                "ask_user",
                "Pause this session and ask the user or parent Agent for a bounded answer.",
                {
                    "question": {
                        "type": "string",
                        "description": (
                            "Non-empty question for the user or parent Agent, at most 8,000 "
                            "UTF-8 bytes. Pauses the session until an answer is supplied."
                        ),
                    },
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Optional answer choices: at most 10 non-empty strings, each at most "
                            "200 UTF-8 bytes. Omit for a free-text question."
                        ),
                    },
                },
                ["question"],
            ),
        ]
        if self.memory is not None:
            schemas.extend(
                (
                    self._schema(
                        "recall_memory",
                        "Recall relevant durable notes from this agent's local memory.",
                        {
                            "query": {
                                "type": "string",
                                "description": (
                                    "Search words for notes in the active scope and global scope. "
                                    "An empty string retrieves recent notes."
                                ),
                            },
                            "limit": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 20,
                                "description": "Maximum notes to return, from 1 through 20; default 8.",
                            },
                        },
                        ["query"],
                    ),
                    self._schema(
                        "remember_memory",
                        "Store a concise fact, preference, decision, or progress note for later runs.",
                        {
                            "content": {
                                "type": "string",
                                "description": (
                                    "Non-empty durable fact, preference, decision, or progress note, "
                                    "at most 20,000 UTF-8 bytes. Do not include credentials."
                                ),
                            },
                            "kind": {
                                "type": "string",
                                "description": "Short note category; defaults to note.",
                            },
                            "tags": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Optional string tags used for bounded lexical recall.",
                            },
                            "scope": {
                                "type": "string",
                                "description": (
                                    "Omit to use the active scope (the run when attached, otherwise "
                                    "global). Use global explicitly to share across runs. Other "
                                    "scopes outside global or the active run are rejected."
                                ),
                            },
                        },
                        ["content"],
                    ),
                )
            )
        if self.allow_exec:
            schemas.append(
                self._schema(
                    "run_command",
                    "Run a bounded command without a shell in the task workspace.",
                    {
                        "command": {
                            "oneOf": [
                                {"type": "string"},
                                {"type": "array", "items": {"type": "string"}},
                            ],
                            "description": (
                                "Runs without a shell in the task workspace. Prefer an argv array, "
                                'e.g. ["python3", "-u", "solve.py"]. Do not encode the array as a string. '
                                "A string is split into arguments; "
                                "pipes, redirects, wildcards and environment variables are not expanded. "
                                f"Timeout: at most {self.command_timeout:g} seconds, further limited "
                                "by a profiled invocation's remaining time. Stops on timeout or "
                                f"more than {self.max_output_bytes} bytes in either output stream."
                            ),
                        },
                    },
                    ["command"],
                )
            )
        if self._worker_service is not None:
            schemas.extend(
                (
                    self._schema(
                        "spawn_worker",
                        "Start one bounded child worker owned by this worker attempt.",
                        {
                            "prompt": {"type": "string", "description": "Non-empty child task prompt."},
                            "role": {"type": "string", "description": "Child role; defaults to worker."},
                            "required_capabilities": {
                                "type": "array", "items": {"type": "string"},
                                "description": "Optional capability names.",
                            },
                            "preferred_adapter": {"type": "string"},
                            "timeout": {"type": "number", "minimum": 0.001},
                        },
                        ["prompt"],
                    ),
                    self._schema(
                        "wait_worker",
                        "Wait for a child worker for a bounded time and return its state.",
                        {
                            "worker_id": {"type": "string"},
                            "timeout": {"type": "number", "minimum": 0},
                        },
                        ["worker_id"],
                    ),
                    self._schema(
                        "cancel_worker",
                        "Cancel one owned child worker and its descendants.",
                        {"worker_id": {"type": "string"}},
                        ["worker_id"],
                    ),
                    self._schema(
                        "read_worker_result",
                        "Read a settled child worker result envelope with bounded text.",
                        {"worker_id": {"type": "string"}},
                        ["worker_id"],
                    ),
                )
            )
        return tuple(schemas)

    @staticmethod
    def _schema(
        name: str,
        description: str,
        properties: dict[str, object],
        required: list[str],
    ) -> dict[str, object]:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {"type": "object", "properties": properties, "required": required},
            },
        }

    def execute(self, name: str, arguments: dict[str, object], workspace: Path) -> ToolResult:
        try:
            if name == "read_file":
                return self._read_file(arguments, workspace)
            if name == "write_file":
                return self._write_file(arguments, workspace)
            if name == "list_dir":
                return self._list_dir(arguments, workspace)
            if name == "ask_user":
                return self._ask_user(arguments)
            if name == "recall_memory":
                return self._recall_memory(arguments)
            if name == "remember_memory":
                return self._remember_memory(arguments)
            if name == "run_command":
                return self._run_command(arguments, workspace)
            if name == "spawn_worker":
                return self._spawn_worker(arguments)
            if name == "wait_worker":
                return self._wait_worker(arguments)
            if name == "cancel_worker":
                return self._cancel_worker(arguments)
            if name == "read_worker_result":
                return self._read_worker_result(arguments)
            raise ToolError(f"unknown tool: {name}")
        except (OSError, sqlite3.Error, ToolError, TypeError, ValueError, RuntimeError) as exc:
            return ToolResult(output=f"tool_error: {type(exc).__name__}: {exc}", success=False)

    def _require_worker_context(self):
        if self._worker_service is None or self._worker_owner_id is None:
            raise ToolError("worker tools are unavailable in this AgentLoop")
        return self._worker_service, self._worker_owner_id

    def _worker_id(self, arguments: dict[str, object]) -> str:
        worker_id = arguments.get("worker_id")
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise ToolError("worker_id must be a non-empty string")
        service, owner_id = self._require_worker_context()
        if self._worker_parent_id is None:
            raise ToolError("worker parent context is missing")
        current = service.store.get_worker(worker_id)
        visited: set[str] = set()
        max_hops = getattr(service, "max_depth", 32) + 1
        while current is not None and current.id not in visited and len(visited) <= max_hops:
            if current.owner_id != owner_id:
                raise ToolError("worker is owned by another caller")
            if current.parent_worker_id == self._worker_parent_id:
                return worker_id
            visited.add(current.id)
            if current.parent_worker_id is None:
                break
            current = service.store.get_worker(current.parent_worker_id)
        raise ToolError("worker is outside the current worker subtree")

    @staticmethod
    def _worker_payload(worker) -> dict[str, object]:
        return {
            "worker_id": worker.id,
            "parent_worker_id": worker.parent_worker_id,
            "role": worker.role,
            "agent_type": worker.agent_type,
            "depth": worker.depth,
            "phase": worker.phase.value,
            "outcome": worker.outcome.value if worker.outcome is not None else None,
            "stop_reason": worker.stop_reason.value if worker.stop_reason is not None else None,
            "result_ref": worker.result_ref,
        }

    def _spawn_worker(self, arguments: dict[str, object]) -> ToolResult:
        service, owner_id = self._require_worker_context()
        prompt = arguments.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip() or "\x00" in prompt:
            raise ToolError("prompt must be non-empty and NUL-free")
        if len(prompt.encode("utf-8")) > 64 * 1024:
            raise ToolError("prompt exceeds 65536 bytes")
        role = arguments.get("role", "worker")
        if not isinstance(role, str) or not role.strip():
            raise ToolError("role must be a non-empty string")
        capabilities = arguments.get("required_capabilities", ())
        if not isinstance(capabilities, (list, tuple)) or any(
            not isinstance(item, str) or not item.strip() for item in capabilities
        ) or len(capabilities) > 16:
            raise ToolError("required_capabilities must contain at most 16 strings")
        preferred = arguments.get("preferred_adapter")
        if preferred is not None and (not isinstance(preferred, str) or not preferred.strip()):
            raise ToolError("preferred_adapter must be a non-empty string")
        timeout = arguments.get("timeout")
        if timeout is not None and (
            isinstance(timeout, bool) or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout) or timeout <= 0 or timeout > 24 * 60 * 60
        ):
            raise ToolError("timeout must be between 0 and 86400 seconds")
        worker = service.dispatch(
            owner_id,
            role=role,
            prompt=prompt,
            parent_worker_id=self._worker_parent_id,
            required_capabilities=tuple(capabilities),
            preferred_adapter=preferred,
            timeout=timeout,
        )
        return ToolResult(json.dumps(self._worker_payload(worker), sort_keys=True))

    def _wait_worker(self, arguments: dict[str, object]) -> ToolResult:
        service, owner_id = self._require_worker_context()
        worker_id = self._worker_id(arguments)
        timeout = arguments.get("timeout", 30.0)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout < 0:
            raise ToolError("timeout must be a non-negative finite number")
        timeout = min(float(timeout), 300.0)
        deadline = time.monotonic() + timeout
        execution_deadline = self._execution_deadline.get()
        if execution_deadline is not None:
            deadline = min(deadline, execution_deadline)
        while True:
            if self._continuation_guard is not None:
                self._continuation_guard()
            remaining = deadline - time.monotonic()
            worker = service.wait(owner_id, worker_id, timeout=min(0.1, max(0.0, remaining)))
            if worker.phase.value == "idle" or remaining <= 0:
                return ToolResult(json.dumps(self._worker_payload(worker), sort_keys=True))

    def _cancel_worker(self, arguments: dict[str, object]) -> ToolResult:
        service, owner_id = self._require_worker_context()
        worker = service.cancel(owner_id, self._worker_id(arguments))
        return ToolResult(json.dumps(self._worker_payload(worker), sort_keys=True))

    def _read_worker_result(self, arguments: dict[str, object]) -> ToolResult:
        service, owner_id = self._require_worker_context()
        result = service.read_result_envelope(owner_id, self._worker_id(arguments))
        text = result.text
        raw = text.encode("utf-8")
        truncated = len(raw) > self.max_output_bytes
        if truncated:
            text = raw[: self.max_output_bytes].decode("utf-8", errors="ignore")
        payload = {
            "adapter_name": result.adapter_name,
            "role": result.role,
            "status": result.status,
            "text": text,
            "truncated": truncated,
            "artifacts": list(result.artifacts),
            "metadata": dict(result.metadata),
            "error": result.error,
        }
        return ToolResult(json.dumps(payload, ensure_ascii=False, sort_keys=True))

    def _safe_path(self, workspace: Path, value: object) -> Path:
        if not isinstance(value, str) or not value.strip():
            raise ToolError("path must be a non-empty string")
        root = workspace.resolve()
        candidate = (root / value).resolve(strict=False)
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ToolError(f"path escapes task workspace: {value}") from exc
        return candidate

    def _read_file(self, arguments: dict[str, object], workspace: Path) -> ToolResult:
        path = self._safe_path(workspace, arguments.get("path"))
        if not path.is_file():
            raise ToolError(f"file does not exist: {arguments.get('path')}")
        raw = path.read_bytes()
        truncated = len(raw) > self.max_output_bytes
        if truncated:
            raw = raw[: self.max_output_bytes]
            suffix = "\n[tool output truncated]"
        else:
            suffix = ""
        try:
            # Only a truncated preview may omit an incomplete trailing character; EOF stays strict.
            decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
            output = decoder.decode(raw, final=not truncated)
        except UnicodeDecodeError as exc:
            raise ToolError("file is not valid UTF-8 text") from exc
        return ToolResult(output + suffix)

    def _write_file(self, arguments: dict[str, object], workspace: Path) -> ToolResult:
        path = self._safe_path(workspace, arguments.get("path"))
        content = arguments.get("content")
        if not isinstance(content, str):
            raise ToolError("content must be a string")
        encoded = content.encode("utf-8")
        if len(encoded) > 1_000_000:
            raise ToolError("content exceeds 1 MiB")
        path.parent.mkdir(parents=True, exist_ok=True)
        mode = stat.S_IMODE(path.stat().st_mode) if path.is_file() else None
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=path.parent, prefix=".lunar-write-", suffix=".tmp", delete=False,
            ) as stream:
                temporary = Path(stream.name)
                stream.write(encoded)
                stream.flush()
                if mode is not None:
                    temporary.chmod(mode)
                os.fsync(stream.fileno())
            # Publish only complete content; a failed write must leave the incumbent intact.
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    # Cleanup failure must not obscure the original publication failure.
                    pass
        relative = path.relative_to(workspace.resolve()).as_posix()
        return ToolResult(output=f"wrote {relative}", artifacts=(relative,))

    def _list_dir(self, arguments: dict[str, object], workspace: Path) -> ToolResult:
        path = self._safe_path(workspace, arguments.get("path", "."))
        if not path.is_dir():
            raise ToolError(f"directory does not exist: {arguments.get('path', '.')}")
        entries = []
        for entry in sorted(path.iterdir(), key=lambda item: item.name):
            entries.append({"name": entry.name, "type": "directory" if entry.is_dir() else "file"})
        return ToolResult(json.dumps(entries, ensure_ascii=False))

    def _ask_user(self, arguments: dict[str, object]) -> ToolResult:
        question = arguments.get("question")
        if not isinstance(question, str) or not question.strip():
            raise ToolError("question must be a non-empty string")
        question = question.strip()
        if len(question.encode("utf-8")) > 8_000:
            raise ToolError("question exceeds 8 KiB")
        options = arguments.get("options", [])
        if not isinstance(options, list) or any(
            not isinstance(option, str) or not option.strip() for option in options
        ):
            raise ToolError("options must be a string array")
        if len(options) > 10 or any(len(option.encode("utf-8")) > 200 for option in options):
            raise ToolError("options exceed the input limit")
        normalized_options = [option.strip() for option in options]
        payload = {"status": "awaiting_input", "question": question, "options": normalized_options}
        return ToolResult(
            self._bounded_text(json.dumps(payload, ensure_ascii=False)),
            awaiting_input=True,
            input_question=question,
            input_options=tuple(normalized_options),
        )

    def _recall_memory(self, arguments: dict[str, object]) -> ToolResult:
        if self.memory is None:
            raise ToolError("memory tools are unavailable")
        query = arguments.get("query")
        if not isinstance(query, str):
            raise ToolError("query must be a string")
        limit = arguments.get("limit", 8)
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise ToolError("limit must be an integer")
        limit = max(1, min(limit, 20))
        scopes = (self.memory_scope, "global") if self.memory_scope != "global" else ("global",)
        entries = self.memory.recall(query, scopes=scopes, limit=limit)
        payload = [
            {
                "id": entry.id,
                "scope": entry.scope,
                "kind": entry.kind,
                "content": entry.content,
                "tags": list(entry.tags),
            }
            for entry in entries
        ]
        return ToolResult(self._bounded_text(json.dumps(payload, ensure_ascii=False)))

    def _remember_memory(self, arguments: dict[str, object]) -> ToolResult:
        if self.memory is None:
            raise ToolError("memory tools are unavailable")
        content = arguments.get("content")
        if not isinstance(content, str):
            raise ToolError("content must be a string")
        content = self._redact(content)
        kind = arguments.get("kind", "note")
        if not isinstance(kind, str):
            raise ToolError("kind must be a string")
        tags = arguments.get("tags", [])
        if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
            raise ToolError("tags must be a string array")
        scope = arguments.get("scope", self.memory_scope)
        if not isinstance(scope, str) or not scope.strip():
            raise ToolError("scope must be a non-empty string")
        # A model can opt into global memory explicitly, but arbitrary namespaces are disallowed
        # so one task cannot silently read or mutate another task's private scope.
        if scope != "global" and scope != self.memory_scope:
            raise ToolError("scope must be global or the active run scope")
        entry = self.memory.remember(
            content,
            scope=scope,
            kind=kind,
            tags=tags,
            source="agent-tool",
        )
        return ToolResult(f"remembered {entry.id} in {entry.scope}")

    def _redact(self, value: str) -> str:
        for secret in self.redactions:
            value = value.replace(secret, "[REDACTED]")
        return value

    def _run_command(self, arguments: dict[str, object], workspace: Path) -> ToolResult:
        if not self.allow_exec:
            raise ToolError("run_command is disabled; pass --allow-exec to enable it")
        command = arguments.get("command")
        if isinstance(command, str):
            if command.lstrip().startswith("["):
                try:
                    decoded = json.loads(command)
                except (ValueError, RecursionError):
                    decoded = None
                if isinstance(decoded, list):
                    raise ToolError(
                        "Pass the argv array directly, without enclosing the entire array in a "
                        'string, e.g. {"command": ["python3", "--version"]}, or provide an '
                        "ordinary command string."
                    )
            command = shlex.split(command)
        if not isinstance(command, list) or not command or any(not isinstance(item, str) for item in command):
            raise ToolError("command must be a non-empty string or string array")
        timeout = self.command_timeout
        deadline = self._execution_deadline.get()
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ToolError("command deadline expired before launch")
            timeout = min(timeout, remaining)
        from .candidate_execution_runner import _bounded_process_bytes

        stdout, stderr, status, returncode, error = _bounded_process_bytes(
            command, cwd=str(workspace),
            environment=(dict(os.environ) if self.command_environment is None else self.command_environment),
            timeout=timeout, output_limit=self.max_output_bytes, capture_limit=self.max_output_bytes,
            process_observer=self._process_observer, process_released=self._process_released,
        )
        if status == "timed_out":
            return ToolResult(
                output=f"command timed out after {timeout:g}s\n{self._bounded_text(stdout + stderr)}",
                success=False,
            )
        output = f"exit_code={returncode}\nstdout:\n{self._bounded_text(stdout)}"
        if stderr:
            output += f"\nstderr:\n{self._bounded_text(stderr)}"
        if error and status != "succeeded":
            output += f"\nerror={error}"
        return ToolResult(output=output, success=status == "succeeded")

    def _bounded_text(self, value: str | bytes) -> str:
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        if len(value) <= self.max_output_bytes:
            return value
        return value[: self.max_output_bytes] + "\n[tool output truncated]"
