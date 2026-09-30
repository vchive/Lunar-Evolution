"""A small local clean-room verifier for RSI candidate artifacts.

The clean-room verifier is deliberately independent from the actor's reported score and
receipts.  It materializes a candidate from immutable bytes (or a safely opened source path)
into a fresh private directory, recomputes all content and evaluator identities, and invokes a
caller supplied *trusted evaluator wrapper*.  The wrapper receives only the public candidate
workspace and task input; verifier-private data and actor evidence are never placed in that
workspace or in the evaluation context.

This module is a reusable boundary, rather than a controller integration.  A controller may
persist :class:`CleanRoomVerdict` and use a passing verdict as one input to its memory gate.
Arbitrary Python evaluators cannot be forcibly killed by this process, so the timeout is a
fail-closed observation bound.  Production adapters should run the wrapper in a separate process
when a hard kill boundary is required.
"""

from __future__ import annotations

import hashlib
import math
import os
import shutil
import stat
import tempfile
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from .candidate_evaluation_spec import canonical_json
from .rsi_identity import component_fingerprint

CleanRoomOutcome = Literal["pass", "fail", "unresolved"]

MAX_SOURCE_BYTES = 4 * 1024 * 1024
MAX_DEPENDENCY_BYTES = 16 * 1024 * 1024
MAX_TASK_INPUT_BYTES = 16 * 1024 * 1024
MAX_EVIDENCE_BYTES = 128 * 1024
MAX_EPISODE_ID_BYTES = 256
MAX_TIMEOUT_SECONDS = 300.0
MAX_DEPENDENCIES = 128


class CleanRoomError(ValueError):
    """Stable, fail-closed input error for the clean-room boundary."""

    _CODES = frozenset(
        {
            "invalid",
            "episode_id_invalid",
            "digest_invalid",
            "source_invalid",
            "source_path_invalid",
            "dependency_invalid",
            "dependency_path_invalid",
            "task_input_invalid",
            "evaluator_invalid",
            "evidence_invalid",
            "timeout_invalid",
            "private_input_invalid",
        }
    )

    def __init__(self, code: str) -> None:
        normalized = code if code in self._CODES else "invalid"
        self.code = f"rsi_cleanroom_{normalized}"
        super().__init__(self.code)


def _fail(code: str) -> None:
    raise CleanRoomError(code)


def _digest(value: object, name: str = "digest") -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        _fail("digest_invalid" if name == "digest" else f"{name}_invalid")
    return value


def _id(value: object) -> str:
    if type(value) is not str or not value.strip() or "\x00" in value:
        _fail("episode_id_invalid")
    if len(value.encode("utf-8")) > MAX_EPISODE_ID_BYTES:
        _fail("episode_id_invalid")
    return value


def _bytes(value: object, name: str, maximum: int) -> bytes:
    if isinstance(value, bytearray):
        value = bytes(value)
    if type(value) is not bytes or len(value) > maximum:
        _fail(name)
    return value


def _safe_dependency_name(value: object) -> str:
    if type(value) is not str or not value or "\x00" in value or "\\" in value:
        _fail("dependency_path_invalid")
    path = PurePosixPath(value)
    if (path.is_absolute() or not path.parts or path.as_posix() != value
            or any(part in {"", ".", ".."} for part in path.parts)):
        _fail("dependency_path_invalid")
    return value


def _canonical_digest(value: object, maximum: int = MAX_EVIDENCE_BYTES) -> str:
    try:
        return hashlib.sha256(canonical_json(value, maximum=maximum)).hexdigest()
    except Exception as exc:  # canonical_json intentionally exposes no implementation details.
        raise CleanRoomError("evidence_invalid") from exc


def _mapping_tuple(value: object, name: str) -> tuple[tuple[str, Any], ...]:
    if not isinstance(value, Mapping) or len(value) > 128:
        _fail(name)
    pairs: list[tuple[str, Any]] = []
    for key, item in value.items():
        if type(key) is not str or not key or "\x00" in key:
            _fail(name)
        # Validate and freeze the JSON projection now.  We deliberately do not retain arbitrary
        # objects supplied by the actor or evaluator.
        try:
            canonical_json(item, maximum=MAX_EVIDENCE_BYTES)
        except Exception as exc:
            raise CleanRoomError(name) from exc
        pairs.append((key, item))
    pairs.sort(key=lambda pair: pair[0])
    return tuple(pairs)


def _read_nofollow(path: Path, maximum: int) -> bytes:
    """Read one regular file without following a final symlink."""

    if "\x00" in str(path):
        _fail("source_path_invalid")
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags | nofollow)
    except (OSError, ValueError) as exc:
        raise CleanRoomError("source_path_invalid") from exc
    try:
        initial = os.fstat(fd)
        if not stat.S_ISREG(initial.st_mode):
            _fail("source_path_invalid")
        if initial.st_size < 0 or initial.st_size > maximum:
            _fail("source_invalid")
        chunks: list[bytes] = []
        remaining = initial.st_size
        while remaining:
            chunk = os.read(fd, min(1024 * 1024, remaining))
            if not chunk:
                _fail("source_invalid")
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        final = os.fstat(fd)
        identity = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if (len(content) != initial.st_size or os.read(fd, 1)
                or any(getattr(initial, key) != getattr(final, key) for key in identity)):
            _fail("source_invalid")
        return content
    finally:
        os.close(fd)


@dataclass(frozen=True)
class CandidateArtifact:
    """Immutable candidate source and dependency material.

    Exactly one of ``source`` and ``source_path`` must be supplied.  A path is read once with
    ``O_NOFOLLOW`` and copied into the clean-room workspace; the evaluator never receives the
    actor's original path.  ``expected_*`` pins are optional and, when present, are compared to
    freshly computed digests before evaluation.
    """

    source: bytes | bytearray | None = None
    source_path: str | os.PathLike[str] | None = None
    dependencies: Mapping[str, bytes | bytearray] | Sequence[tuple[str, bytes | bytearray]] = field(
        default_factory=dict
    )
    expected_source_sha256: str | None = None
    expected_dependency_sha256: str | None = None

    def __post_init__(self) -> None:
        has_bytes = self.source is not None
        has_path = self.source_path is not None
        if has_bytes == has_path:
            _fail("source_invalid")
        if has_bytes:
            object.__setattr__(self, "source", _bytes(self.source, "source_invalid", MAX_SOURCE_BYTES))
        else:
            if not isinstance(self.source_path, (str, os.PathLike)):
                _fail("source_path_invalid")
            path = os.fspath(self.source_path)
            if type(path) is not str or not path or "\x00" in path:
                _fail("source_path_invalid")
            object.__setattr__(self, "source_path", path)

        if isinstance(self.dependencies, Mapping):
            items = list(self.dependencies.items())
        elif isinstance(self.dependencies, (tuple, list)):
            items = list(self.dependencies)
        else:
            _fail("dependency_invalid")
        if len(items) > MAX_DEPENDENCIES:
            _fail("dependency_invalid")
        normalized: list[tuple[str, bytes]] = []
        seen: set[str] = set()
        total = 0
        for item in items:
            if not isinstance(item, (tuple, list)) or len(item) != 2:
                _fail("dependency_invalid")
            name = _safe_dependency_name(item[0])
            if name in seen:
                _fail("dependency_invalid")
            data = _bytes(item[1], "dependency_invalid", MAX_DEPENDENCY_BYTES)
            total += len(data)
            if total > MAX_DEPENDENCY_BYTES:
                _fail("dependency_invalid")
            seen.add(name)
            normalized.append((name, data))
        normalized.sort(key=lambda item: item[0])
        object.__setattr__(self, "dependencies", tuple(normalized))
        if self.expected_source_sha256 is not None:
            _digest(self.expected_source_sha256, "source_sha256")
        if self.expected_dependency_sha256 is not None:
            _digest(self.expected_dependency_sha256, "dependency_sha256")

    @property
    def source_bytes(self) -> bytes:
        if self.source is not None:
            return self.source
        return _read_nofollow(Path(self.source_path), MAX_SOURCE_BYTES)

    @property
    def dependency_bytes(self) -> tuple[tuple[str, bytes], ...]:
        return self.dependencies


@dataclass(frozen=True)
class CleanRoomContext:
    """Public evaluator context; it intentionally has no verifier-private input field."""

    workspace: Path
    source_path: Path
    dependency_dir: Path
    task_input: bytes
    task_input_sha256: str
    source_sha256: str
    dependency_sha256: str
    evaluator_sha256: str
    contract_sha256: str
    actor_evidence_sha256: str


@dataclass(frozen=True)
class CleanRoomEvaluation:
    """Strict evaluator return envelope.

    ``evidence`` is a bounded JSON-compatible object or bytes.  A score or actor receipt is not
    interpreted by this class; the only authority is the pass/fail outcome after its evidence is
    hashed and bound to this clean-room request.
    """

    outcome: Literal["pass", "fail"]
    evidence: bytes | Mapping[str, Any]
    receipt_sha256: str | None = None


@dataclass(frozen=True)
class CleanRoomVerificationRequest:
    """Immutable clean-room verification input."""

    episode_id: str
    candidate: CandidateArtifact
    contract_sha256: str
    task_input: bytes | bytearray
    task_input_sha256: str
    evaluator: Callable[[CleanRoomContext], object]
    evaluator_sha256: str
    actor_evidence: Mapping[str, Any] = field(default_factory=dict)
    timeout_seconds: float = 30.0
    private_input_sha256: str | None = None

    def __post_init__(self) -> None:
        _id(self.episode_id)
        if not isinstance(self.candidate, CandidateArtifact):
            _fail("source_invalid")
        _digest(self.contract_sha256)
        object.__setattr__(
            self, "task_input", _bytes(self.task_input, "task_input_invalid", MAX_TASK_INPUT_BYTES)
        )
        _digest(self.task_input_sha256, "task_input_sha256")
        if hashlib.sha256(self.task_input).hexdigest() != self.task_input_sha256:
            _fail("task_input_invalid")
        if not callable(self.evaluator):
            _fail("evaluator_invalid")
        _digest(self.evaluator_sha256, "evaluator_sha256")
        object.__setattr__(self, "actor_evidence", _mapping_tuple(self.actor_evidence, "evidence_invalid"))
        if isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, (int, float)):
            _fail("timeout_invalid")
        timeout = float(self.timeout_seconds)
        if not math.isfinite(timeout) or not 0 < timeout <= MAX_TIMEOUT_SECONDS:
            _fail("timeout_invalid")
        object.__setattr__(self, "timeout_seconds", timeout)
        if self.private_input_sha256 is not None:
            _digest(self.private_input_sha256, "private_input_sha256")

    @property
    def actor_evidence_sha256(self) -> str:
        return _canonical_digest(dict(self.actor_evidence))


# A short alias is useful to adapters that already call this object a verification request.
VerificationRequest = CleanRoomVerificationRequest


@dataclass(frozen=True)
class CleanRoomVerdict:
    """Immutable clean-room result suitable for durable receipt storage."""

    episode_id: str
    outcome: CleanRoomOutcome
    source_sha256: str
    dependency_sha256: str
    task_input_sha256: str
    evaluator_sha256: str
    evidence_sha256: str
    receipt_sha256: str
    contamination_reason: str = ""
    actor_evidence_sha256: str = ""

    def __post_init__(self) -> None:
        _id(self.episode_id)
        if self.outcome not in {"pass", "fail", "unresolved"}:
            _fail("invalid")
        for name in (
            "source_sha256",
            "dependency_sha256",
            "task_input_sha256",
            "evaluator_sha256",
            "evidence_sha256",
            "receipt_sha256",
        ):
            _digest(getattr(self, name))
        if self.actor_evidence_sha256:
            _digest(self.actor_evidence_sha256)
        if type(self.contamination_reason) is not str or len(self.contamination_reason) > 512:
            _fail("invalid")


def _dependency_digest(dependencies: Sequence[tuple[str, bytes]]) -> str:
    manifest = [
        {"path": name, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
        for name, data in dependencies
    ]
    return _canonical_digest(manifest)


def _parse_evaluation(value: object) -> tuple[CleanRoomEvaluation | None, str | None]:
    if isinstance(value, CleanRoomEvaluation):
        candidate = value
    elif isinstance(value, Mapping):
        # Exact fields prevent an actor's solver_score or receipt from being silently treated as
        # independent evidence.  The wrapper may put arbitrary bounded details inside evidence.
        allowed = {"outcome", "evidence", "receipt_sha256"}
        if set(value) - allowed or "outcome" not in value or "evidence" not in value:
            return None, "untrusted_evidence"
        candidate = CleanRoomEvaluation(value["outcome"], value["evidence"], value.get("receipt_sha256"))
    else:
        return None, "untrusted_evidence"
    if candidate.outcome not in {"pass", "fail"}:
        return None, "untrusted_evidence"
    if type(candidate.evidence) is bytes:
        if len(candidate.evidence) > MAX_EVIDENCE_BYTES:
            return None, "untrusted_evidence"
    elif isinstance(candidate.evidence, Mapping):
        try:
            canonical_json(candidate.evidence, maximum=MAX_EVIDENCE_BYTES)
        except (TypeError, ValueError, OverflowError, RecursionError):
            return None, "untrusted_evidence"
    else:
        return None, "untrusted_evidence"
    if candidate.receipt_sha256 is not None:
        try:
            _digest(candidate.receipt_sha256)
        except CleanRoomError:
            return None, "untrusted_evidence"
    return candidate, None


class CleanRoomVerifier:
    """Run one bounded, provider-free clean-room verification."""

    def verify(self, request: CleanRoomVerificationRequest) -> CleanRoomVerdict:
        if not isinstance(request, CleanRoomVerificationRequest):
            raise CleanRoomError("invalid")
        try:
            source = request.candidate.source_bytes
            source_digest = hashlib.sha256(source).hexdigest()
            dependency_digest = _dependency_digest(request.candidate.dependency_bytes)
            if (
                request.candidate.expected_source_sha256 is not None
                and source_digest != request.candidate.expected_source_sha256
            ):
                return self._unresolved(request, source_digest, dependency_digest, "source_digest_mismatch")
            if (
                request.candidate.expected_dependency_sha256 is not None
                and dependency_digest != request.candidate.expected_dependency_sha256
            ):
                return self._unresolved(request, source_digest, dependency_digest, "dependency_digest_mismatch")
        except CleanRoomError as exc:
            return self._unresolved(request, "0" * 64, "0" * 64, exc.code.removeprefix("rsi_cleanroom_"))

        # Recompute the evaluator's code/config identity; a caller-supplied pin is only accepted
        # when it matches the live callable.
        try:
            actual_evaluator_digest = component_fingerprint(request.evaluator)
        except (TypeError, ValueError, OSError, OverflowError, RecursionError):
            return self._unresolved(request, source_digest, dependency_digest, "evaluator_identity_unavailable")
        if actual_evaluator_digest != request.evaluator_sha256:
            return self._unresolved(request, source_digest, dependency_digest, "evaluator_fingerprint_mismatch")

        workspace = Path(tempfile.mkdtemp(prefix="lunar-rsi-cleanroom-"))
        try:
            os.chmod(workspace, 0o700)
            source_path = workspace / "candidate" / "source.bin"
            dependency_dir = workspace / "candidate" / "dependencies"
            input_dir = workspace / "input"
            source_path.parent.mkdir(mode=0o700)
            dependency_dir.mkdir(mode=0o700)
            input_dir.mkdir(mode=0o700)
            source_path.write_bytes(source)
            source_path.chmod(0o400)
            for name, data in request.candidate.dependency_bytes:
                destination = dependency_dir / name
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                destination.write_bytes(data)
                destination.chmod(0o400)
            # Public task input is available for deterministic evaluation.  No verifier-private
            # input is written here; private_input_sha256 is metadata only.
            public_input_path = input_dir / "task.bin"
            public_input_path.write_bytes(request.task_input)
            public_input_path.chmod(0o400)
            context = CleanRoomContext(
                workspace=workspace,
                source_path=source_path,
                dependency_dir=dependency_dir,
                task_input=request.task_input,
                task_input_sha256=request.task_input_sha256,
                source_sha256=source_digest,
                dependency_sha256=dependency_digest,
                evaluator_sha256=request.evaluator_sha256,
                contract_sha256=request.contract_sha256,
                actor_evidence_sha256=request.actor_evidence_sha256,
            )
            evaluation, reason = self._run_evaluator(request.evaluator, context, request.timeout_seconds)
            # A candidate/evaluator must not rewrite the material that was bound before launch.
            if (
                _read_nofollow(source_path, MAX_SOURCE_BYTES) != source
                or _read_nofollow(public_input_path, MAX_TASK_INPUT_BYTES) != request.task_input
                or _dependency_digest(
                    tuple((name, _read_nofollow(dependency_dir / name, MAX_DEPENDENCY_BYTES))
                          for name, _ in request.candidate.dependency_bytes)
                )
                != dependency_digest
            ):
                reason = "candidate_workspace_mutated"
                evaluation = None
            evidence_payload: object = {
                "episode_id": request.episode_id,
                "contract_sha256": request.contract_sha256,
                "private_input_sha256": request.private_input_sha256,
                "source_sha256": source_digest,
                "dependency_sha256": dependency_digest,
                "task_input_sha256": request.task_input_sha256,
                "evaluator_sha256": request.evaluator_sha256,
                "actor_evidence_sha256": request.actor_evidence_sha256,
                "outcome": evaluation.outcome if evaluation is not None else None,
                "evidence": self._evidence_material(evaluation.evidence) if evaluation is not None else None,
                "reason": reason,
            }
            if evaluation is not None and evaluation.receipt_sha256 is not None:
                expected = _canonical_digest(
                    {"outcome": evaluation.outcome, "evidence": self._evidence_material(evaluation.evidence)}
                )
                if evaluation.receipt_sha256 != expected:
                    reason = "evaluator_receipt_mismatch"
                    evaluation = None
                    evidence_payload["outcome"] = None
                    evidence_payload["evidence"] = None
                    evidence_payload["reason"] = reason
            evidence_digest = _canonical_digest(evidence_payload)
            receipt_digest = _canonical_digest({"kind": "clean-room-verdict", **evidence_payload})
            outcome: CleanRoomOutcome = evaluation.outcome if evaluation is not None else "unresolved"
            if reason:
                outcome = "unresolved"
            return CleanRoomVerdict(
                request.episode_id,
                outcome,
                source_digest,
                dependency_digest,
                request.task_input_sha256,
                request.evaluator_sha256,
                evidence_digest,
                receipt_digest,
                reason or "",
                request.actor_evidence_sha256,
            )
        except (CleanRoomError, OSError, RuntimeError) as exc:
            return self._unresolved(request, source_digest, dependency_digest, self._reason(exc))
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    @staticmethod
    def _evidence_material(evidence: bytes | Mapping[str, Any]) -> object:
        return {"bytes_sha256": hashlib.sha256(evidence).hexdigest(), "size": len(evidence)} if type(evidence) is bytes else evidence

    @staticmethod
    def _run_evaluator(
        evaluator: Callable[[CleanRoomContext], object],
        context: CleanRoomContext,
        timeout_seconds: float,
    ) -> tuple[CleanRoomEvaluation | None, str | None]:
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lunar-cleanroom")
        future = executor.submit(evaluator, context)
        try:
            value = future.result(timeout=timeout_seconds)
        except FutureTimeoutError:
            future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
            return None, "evaluator_timeout"
        except Exception:  # noqa: BLE001 - evaluator failures are intentionally sanitized.
            executor.shutdown(wait=False, cancel_futures=True)
            return None, "evaluator_exception"
        else:
            executor.shutdown(wait=True, cancel_futures=True)
        return _parse_evaluation(value)

    @staticmethod
    def _reason(exc: BaseException) -> str:
        if isinstance(exc, CleanRoomError):
            return exc.code.removeprefix("rsi_cleanroom_")
        return "cleanroom_error"

    @staticmethod
    def _unresolved(
        request: CleanRoomVerificationRequest,
        source_digest: str,
        dependency_digest: str,
        reason: str,
    ) -> CleanRoomVerdict:
        evidence_digest = _canonical_digest(
            {
                "episode_id": request.episode_id,
                "contract_sha256": request.contract_sha256,
                "private_input_sha256": request.private_input_sha256,
                "source_sha256": source_digest,
                "dependency_sha256": dependency_digest,
                "task_input_sha256": request.task_input_sha256,
                "evaluator_sha256": request.evaluator_sha256,
                "reason": reason,
            }
        )
        receipt_digest = _canonical_digest(
            {"kind": "clean-room-verdict", "evidence_sha256": evidence_digest, "outcome": "unresolved"}
        )
        return CleanRoomVerdict(
            request.episode_id,
            "unresolved",
            source_digest,
            dependency_digest,
            request.task_input_sha256,
            request.evaluator_sha256,
            evidence_digest,
            receipt_digest,
            reason,
            request.actor_evidence_sha256,
        )


__all__ = [
    "CandidateArtifact",
    "CleanRoomContext",
    "CleanRoomError",
    "CleanRoomEvaluation",
    "CleanRoomVerdict",
    "CleanRoomVerificationRequest",
    "CleanRoomVerifier",
    "VerificationRequest",
]
