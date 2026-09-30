"""Bounded, concurrent stdout/stderr evidence for native trusted attempts.

The native bootstrap process is intentionally kept separate from the formal
``execution-receipt.json`` path.  This module only drains the two inherited
pipes and records a create-only, publication-ineligible sidecar.  The reader
does not relaunch a process or infer publication authority from the sidecar.
"""

from __future__ import annotations

import hashlib
import os
import re
import selectors
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .producer_launcher import ProducerLaunchIntent
from .producer_process import (
    ProducerProcessError,
    ProducerStreamEvidence,
    _atomic_json,
    _digest_without,
    _read_durable_json,
)

_PROTOCOL = "lunar-native-trusted-stream-capture-v1"
_NAME = "native-trusted-stream-capture.json"
_MAX_CAPTURE_CHUNK = 65536
_STREAMS = ("stdout", "stderr")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class NativeTrustedStreamError(ValueError):
    """Fixed-code stream evidence failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class NativeTrustedStreamObservation:
    stdout_evidence: ProducerStreamEvidence
    stderr_evidence: ProducerStreamEvidence
    complete: bool
    reason: str | None = None

    @property
    def evidence(self) -> tuple[ProducerStreamEvidence, ProducerStreamEvidence]:
        return self.stdout_evidence, self.stderr_evidence


def _empty(name: str) -> ProducerStreamEvidence:
    return ProducerStreamEvidence(
        stream=name,
        bytes_observed=0,
        sha256=hashlib.sha256(b"").hexdigest(),
        truncated=False,
        capture_status="complete",
    )


def _evidence(name: str, state: dict[str, Any]) -> ProducerStreamEvidence:
    status = str(state["status"])
    if status == "complete" and bool(state["truncated"]):
        status = "limit_exceeded"
    return ProducerStreamEvidence(
        stream=name,
        bytes_observed=int(state["bytes"]),
        sha256=state["hash"].hexdigest(),
        truncated=bool(state["truncated"]),
        capture_status=status,
    )


class NativeTrustedStreamCapture:
    """Drain both child pipes in one helper thread without unbounded buffering.

    The caller starts this immediately after ``Popen`` and can continue to
    consume bootstrap control frames while the helper drains stdout/stderr.
    Only the first ``limit`` bytes of each stream are hashed; the observed
    count saturates at ``limit + 1`` when a stream overflows.
    """

    def __init__(
        self,
        process: subprocess.Popen[bytes],
        *,
        limit: int,
        deadline: float,
        monotonic: Any = time.monotonic,
    ) -> None:
        if not isinstance(process, subprocess.Popen):
            raise NativeTrustedStreamError("native_trusted_stream_context_invalid")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise NativeTrustedStreamError("native_trusted_stream_limit_invalid")
        if not isinstance(deadline, (int, float)) or isinstance(deadline, bool):
            raise NativeTrustedStreamError("native_trusted_stream_context_invalid")
        if not callable(monotonic):
            raise NativeTrustedStreamError("native_trusted_stream_context_invalid")
        self.process = process
        self.limit = limit
        self.deadline = float(deadline)
        self.monotonic = monotonic
        self._states: dict[str, dict[str, Any]] = {
            name: {"bytes": 0, "hash": hashlib.sha256(), "truncated": False, "status": "complete"}
            for name in _STREAMS
        }
        self._error: str | None = None
        self._complete = False
        self._done = threading.Event()
        self._started = False
        self._thread: threading.Thread | None = None

    def start(self) -> NativeTrustedStreamCapture:
        if self._started:
            raise NativeTrustedStreamError("native_trusted_stream_already_started")
        self._started = True
        self._thread = threading.Thread(target=self._run, name="lunar-native-stream-capture", daemon=True)
        self._thread.start()
        return self

    def _run(self) -> None:
        selector = selectors.DefaultSelector()
        registered: dict[Any, str] = {}
        try:
            for name, stream in (("stdout", self.process.stdout), ("stderr", self.process.stderr)):
                if stream is None:
                    continue
                try:
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, selectors.EVENT_READ, name)
                    registered[stream] = name
                except OSError as exc:
                    self._error = "native_trusted_stream_register_unknown"
                    raise NativeTrustedStreamError(self._error) from exc
            while registered:
                remaining = self.deadline - float(self.monotonic())
                if remaining <= 0:
                    self._error = "native_trusted_stream_wall_timeout"
                    for state in self._states.values():
                        state["status"] = "deadline_exceeded"
                    break
                try:
                    events = selector.select(min(0.05, remaining))
                except OSError as exc:
                    self._error = "native_trusted_stream_read_unknown"
                    for state in self._states.values():
                        state["status"] = "unknown"
                    raise NativeTrustedStreamError(self._error) from exc
                for key, _ in events:
                    stream = key.fileobj
                    name = key.data
                    try:
                        chunk = os.read(stream.fileno(), _MAX_CAPTURE_CHUNK)
                    except OSError as exc:
                        self._error = "native_trusted_stream_read_unknown"
                        self._states[name]["status"] = "unknown"
                        raise NativeTrustedStreamError(self._error) from exc
                    if not chunk:
                        selector.unregister(stream)
                        registered.pop(stream, None)
                        continue
                    state = self._states[name]
                    prior = int(state["bytes"])
                    retained = max(0, min(len(chunk), self.limit - prior))
                    if retained:
                        state["hash"].update(chunk[:retained])
                    observed = prior + len(chunk)
                    state["bytes"] = min(self.limit + 1, observed)
                    if observed > self.limit:
                        state["truncated"] = True
            else:
                self._complete = self._error is None
        except NativeTrustedStreamError:
            pass
        finally:
            for stream in tuple(registered):
                try:
                    selector.unregister(stream)
                except (KeyError, OSError):
                    pass
            selector.close()
            self._done.set()

    def finish(self, *, deadline: float | None = None) -> NativeTrustedStreamObservation:
        if not self._started:
            raise NativeTrustedStreamError("native_trusted_stream_not_started")
        assert self._thread is not None
        remaining = None
        if deadline is not None:
            remaining = max(0.0, float(deadline) - float(self.monotonic()))
        self._thread.join(remaining)
        if self._thread.is_alive():
            self._error = self._error or "native_trusted_stream_wall_timeout"
            for state in self._states.values():
                if state["status"] == "complete":
                    state["status"] = "deadline_exceeded"
        return NativeTrustedStreamObservation(
            stdout_evidence=_evidence("stdout", self._states["stdout"]),
            stderr_evidence=_evidence("stderr", self._states["stderr"]),
            complete=self._complete and not self._thread.is_alive(),
            reason=self._error,
        )


def start_native_trusted_stream_capture(
    process: subprocess.Popen[bytes], *, limit: int, deadline: float,
    monotonic: Any = time.monotonic,
) -> NativeTrustedStreamCapture:
    return NativeTrustedStreamCapture(
        process, limit=limit, deadline=deadline, monotonic=monotonic,
    ).start()


def _stream_dict(evidence: ProducerStreamEvidence) -> dict[str, object]:
    return evidence.to_dict()


def persist_native_trusted_stream_capture(
    batch: str | Path, *, intent: ProducerLaunchIntent,
    attestation_sha256: str, registration_sha256: str, deadline_sha256: str,
    observation: NativeTrustedStreamObservation,
) -> dict[str, object]:
    """Persist a create-only stream projection; never makes it publishable."""
    if not isinstance(intent, ProducerLaunchIntent) or not isinstance(observation, NativeTrustedStreamObservation):
        raise NativeTrustedStreamError("native_trusted_stream_context_invalid")
    if not isinstance(attestation_sha256, str) or _SHA256.fullmatch(attestation_sha256) is None:
        raise NativeTrustedStreamError("native_trusted_stream_context_invalid")
    if not isinstance(registration_sha256, str) or _SHA256.fullmatch(registration_sha256) is None:
        raise NativeTrustedStreamError("native_trusted_stream_context_invalid")
    if not isinstance(deadline_sha256, str) or _SHA256.fullmatch(deadline_sha256) is None:
        raise NativeTrustedStreamError("native_trusted_stream_context_invalid")
    if not observation.complete:
        raise NativeTrustedStreamError("native_trusted_stream_capture_incomplete")
    record: dict[str, object] = {
        "schema_version": "1", "protocol": _PROTOCOL,
        "launch_id": intent.launch_id, "journal_id": intent.journal_id,
        "run_id": intent.run_id, "parent_task_id": intent.parent_task_id,
        "task_id": intent.task_id, "intent_sha256": intent.intent_sha256,
        "attestation_sha256": attestation_sha256,
        "registration_sha256": registration_sha256,
        "deadline_sha256": deadline_sha256,
        "output_max_bytes": intent.output_max_bytes,
        "stdout_evidence": _stream_dict(observation.stdout_evidence),
        "stderr_evidence": _stream_dict(observation.stderr_evidence),
        "capture_complete": True, "capture_reason": observation.reason,
        "publication_eligible": False,
    }
    record["stream_capture_sha256"] = _digest_without(record, "stream_capture_sha256")
    path = Path(batch) / _NAME
    try:
        _atomic_json(path, record, exclusive=True)
        stored = _read_durable_json(path, code="native_trusted_stream_write_unknown")
    except ProducerProcessError as exc:
        raise NativeTrustedStreamError("native_trusted_stream_write_unknown") from exc
    if stored != record:
        raise NativeTrustedStreamError("native_trusted_stream_write_unknown")
    return record


def recover_native_trusted_stream_capture(
    batch: str | Path, *, intent: ProducerLaunchIntent,
    terminal: dict[str, object],
) -> dict[str, object]:
    """Validate a stream sidecar and its binding to the supplied attempt."""
    if not isinstance(intent, ProducerLaunchIntent) or not isinstance(terminal, dict):
        raise NativeTrustedStreamError("native_trusted_stream_context_invalid")
    try:
        record = _read_durable_json(Path(batch) / _NAME, code="native_trusted_stream_invalid")
    except ProducerProcessError as exc:
        raise NativeTrustedStreamError("native_trusted_stream_invalid") from exc
    expected = {
        "schema_version", "protocol", "launch_id", "journal_id", "run_id",
        "parent_task_id", "task_id", "intent_sha256", "attestation_sha256",
        "registration_sha256", "deadline_sha256", "output_max_bytes",
        "stdout_evidence", "stderr_evidence", "capture_complete", "capture_reason",
        "publication_eligible", "stream_capture_sha256",
    }
    if set(record) != expected or record.get("schema_version") != "1" or record.get("protocol") != _PROTOCOL:
        raise NativeTrustedStreamError("native_trusted_stream_invalid")
    for key in ("launch_id", "journal_id", "run_id", "parent_task_id", "task_id", "intent_sha256"):
        if record.get(key) != getattr(intent, key):
            raise NativeTrustedStreamError("native_trusted_stream_binding_mismatch")
    if (
        record.get("publication_eligible") is not False
        or record.get("capture_complete") is not True
        or record.get("output_max_bytes") != intent.output_max_bytes
        or record.get("stream_capture_sha256") != _digest_without(record, "stream_capture_sha256")
        or record.get("attestation_sha256") != terminal.get("attestation_sha256")
        or record.get("registration_sha256") != terminal.get("registration_sha256")
        or record.get("deadline_sha256") != terminal.get("deadline_sha256")
        or terminal.get("stream_capture_sha256") != record.get("stream_capture_sha256")
    ):
        raise NativeTrustedStreamError("native_trusted_stream_invalid")
    for key in ("attestation_sha256", "registration_sha256", "deadline_sha256", "stream_capture_sha256"):
        if not isinstance(record.get(key), str) or _SHA256.fullmatch(record[key]) is None:
            raise NativeTrustedStreamError("native_trusted_stream_invalid")
    for name in _STREAMS:
        item = record.get(f"{name}_evidence")
        if not isinstance(item, dict) or set(item) != {"stream", "bytes_observed", "sha256", "truncated", "capture_status"}:
            raise NativeTrustedStreamError("native_trusted_stream_invalid")
        if (
            item.get("stream") != name
            or not isinstance(item.get("bytes_observed"), int)
            or isinstance(item.get("bytes_observed"), bool)
            or item["bytes_observed"] < 0
            or item["bytes_observed"] > intent.output_max_bytes + 1
            or not isinstance(item.get("sha256"), str)
            or _SHA256.fullmatch(item["sha256"]) is None
            or type(item.get("truncated")) is not bool
            or item.get("capture_status") not in {"complete", "limit_exceeded"}
        ):
            raise NativeTrustedStreamError("native_trusted_stream_invalid")
    return record


__all__ = [
    "NativeTrustedStreamCapture", "NativeTrustedStreamError", "NativeTrustedStreamObservation",
    "persist_native_trusted_stream_capture", "recover_native_trusted_stream_capture",
    "start_native_trusted_stream_capture",
]
