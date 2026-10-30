"""Bounded local JSONL conversation history for long-running sessions."""

from __future__ import annotations

import json
import os
import stat
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, BinaryIO


class SessionTranscript:
    """Persist recent model messages without allowing unbounded or credential-bearing history."""

    def __init__(
        self,
        path: str | Path,
        *,
        max_messages: int = 80,
        max_message_bytes: int = 12_000,
        max_total_bytes: int = 1_000_000,
        redactions: tuple[str, ...] = (),
        confined_workspace: str | Path | None = None,
    ) -> None:
        if max_messages < 1 or max_message_bytes < 256 or max_total_bytes < max_message_bytes:
            raise ValueError("invalid transcript bounds")
        self._confined_workspace = (
            Path(confined_workspace).expanduser().absolute()
            if confined_workspace is not None else None
        )
        if self._confined_workspace is None:
            self.path = Path(path).expanduser().resolve()
        else:
            supplied = Path(path).expanduser()
            if ".." in supplied.parts or ".." in self._confined_workspace.parts:
                raise ValueError("confined transcript paths must not contain '..'")
            self.path = supplied if supplied.is_absolute() else self._confined_workspace / supplied
            try:
                relative = self.path.relative_to(self._confined_workspace)
            except ValueError as exc:
                raise ValueError("transcript must be inside its confined workspace") from exc
            if not relative.parts:
                raise ValueError("confined transcript must name a file")
            self._validate_confined_path()
        self.max_messages = max_messages
        self.max_message_bytes = max_message_bytes
        self.max_total_bytes = max_total_bytes
        self.redactions = tuple(secret for secret in redactions if secret)

    def create_fresh(self) -> None:
        """Reserve an empty confined history without replaying an existing file."""
        if self._confined_workspace is None:
            raise ValueError("fresh transcript requires a confined workspace")
        with self._confined_parent(create=True) as parent:
            descriptor = os.open(
                self.path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600, dir_fd=parent,
            )
            os.close(descriptor)

    def _read_tail(self, stream: BinaryIO) -> bytes:
        observed = os.fstat(stream.fileno())
        if not stat.S_ISREG(observed.st_mode):
            raise ValueError("transcript must be a regular file")
        limit = self.max_total_bytes * 2
        stream.seek(max(0, observed.st_size - limit))
        return stream.read(limit)

    def load(self) -> list[dict[str, object]]:
        if self._confined_workspace is not None:
            self._validate_confined_path()
            try:
                with self._confined_parent() as parent:
                    descriptor = os.open(
                        self.path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent,
                    )
                    with os.fdopen(descriptor, "rb") as stream:
                        raw = self._read_tail(stream)
            except FileNotFoundError:
                return []
        else:
            if not self.path.is_file():
                return []
            try:
                with self.path.open("rb") as stream:
                    raw = self._read_tail(stream)
            except OSError:
                return []
        messages: list[dict[str, object]] = []
        for line in raw.decode("utf-8", errors="replace").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict) and isinstance(item.get("role"), str):
                messages.append(item)
        return messages[-self.max_messages :]

    def append(self, message: dict[str, object]) -> None:
        self._validate_confined_path()
        normalized = self._normalize(message)
        messages = self.load()
        messages.append(normalized)
        messages = self._compact(messages)
        payload = "".join(
            json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n"
            for item in messages
        )
        if self._confined_workspace is not None:
            self._append_confined(payload)
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(payload, encoding="utf-8")
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def _validate_confined_path(self) -> None:
        root = self._confined_workspace
        if root is None:
            return
        current = root
        for component in (None, *self.path.relative_to(root).parts):
            if component is not None:
                current = current / component
            try:
                mode = current.lstat().st_mode
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(mode):
                raise ValueError("confined transcript path must not contain a symlink")
            if current == self.path:
                if not stat.S_ISREG(mode):
                    raise ValueError("confined transcript must be a regular file")
            elif not stat.S_ISDIR(mode):
                raise ValueError("confined transcript parent must be a directory")

    @contextmanager
    def _confined_parent(self, *, create: bool = False):
        """Anchor all confined I/O to directories opened without following symlinks."""
        root = self._confined_workspace
        assert root is not None
        self._validate_confined_path()
        if create:
            root.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for component in self.path.relative_to(root).parts[:-1]:
                if create:
                    try:
                        os.mkdir(component, mode=0o700, dir_fd=descriptor)
                    except FileExistsError:
                        pass
                child = os.open(
                    component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor,
                )
                os.close(descriptor)
                descriptor = child
            yield descriptor
        finally:
            os.close(descriptor)

    def _append_confined(self, payload: str) -> None:
        with self._confined_parent(create=True) as parent:
            temporary = f".{self.path.name}.{uuid.uuid4().hex}.tmp"
            descriptor = os.open(
                temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600, dir_fd=parent,
            )
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    stream.write(payload)
                self._validate_confined_path()
                os.replace(temporary, self.path.name, src_dir_fd=parent, dst_dir_fd=parent)
            finally:
                try:
                    os.unlink(temporary, dir_fd=parent)
                except FileNotFoundError:
                    pass

    def _normalize(self, message: dict[str, object]) -> dict[str, object]:
        value = self._redact_value(message)
        if not isinstance(value, dict) or not isinstance(value.get("role"), str):
            raise TypeError("transcript message requires a role")
        return value

    def _redact_value(self, value: Any, depth: int = 0) -> Any:
        if depth > 8:
            return "[transcript value omitted]"
        if isinstance(value, str):
            for secret in self.redactions:
                value = value.replace(secret, "[REDACTED]")
            encoded = value.encode("utf-8")
            if len(encoded) <= self.max_message_bytes:
                return value
            suffix = "\n[truncated]"
            budget = max(1, self.max_message_bytes - len(suffix.encode("utf-8")))
            return encoded[:budget].decode("utf-8", errors="ignore") + suffix
        if isinstance(value, dict):
            return {str(key): self._redact_value(item, depth + 1) for key, item in value.items()}
        if isinstance(value, list):
            return [self._redact_value(item, depth + 1) for item in value[:40]]
        return value

    def _compact(self, messages: list[dict[str, object]]) -> list[dict[str, object]]:
        messages = messages[-self.max_messages :]
        while messages and self._encoded_size(messages) > self.max_total_bytes:
            messages.pop(0)
        # A single structured message can still exceed the file cap due to nested values. Replace
        # its content with a bounded marker rather than violating the total-size contract.
        if messages and self._encoded_size(messages) > self.max_total_bytes:
            messages[-1] = {
                "role": messages[-1].get("role", "system"),
                "content": "[transcript message omitted: size limit]",
            }
        return messages

    @staticmethod
    def _encoded_size(messages: list[dict[str, object]]) -> int:
        return sum(
            len(json.dumps(item, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) + 1
            for item in messages
        )
