"""Provider-free bridge from a local AgentLoop Actor to an independent process verifier."""

from __future__ import annotations

import hashlib
import inspect
import math
import os
import stat
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .candidate_evaluation_spec import canonical_json
from .rsi_actor import AgentLoopActorGateway
from .rsi_cleanroom import (
    MAX_DEPENDENCY_BYTES,
    MAX_SOURCE_BYTES,
    MAX_TASK_INPUT_BYTES,
    MAX_TIMEOUT_SECONDS,
    CandidateArtifact,
    CleanRoomProcessVerifier,
    CleanRoomVerdict,
    CleanRoomVerificationRequest,
    CleanRoomVerifier,
    _dependency_digest,
    _is_importable_fixture,
)
from .rsi_gateway import SolverRequest, SolverResult
from .rsi_identity import component_fingerprint
from .rsi_learning import PracticeEpisode, RSILearningError, VerifierCheck, VerifierDecision


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value, maximum=128 * 1024)).hexdigest()


def _pin(value: object, name: str) -> str:
    if type(value) is not str or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise RSILearningError(f"rsi_actor_cleanroom_{name}_invalid")
    return value


def _relative(value: object) -> str:
    if type(value) is not str or not value or any(char in value for char in "\x00\r\n\\"):
        raise RSILearningError("rsi_actor_cleanroom_path_invalid")
    path = PurePosixPath(value)
    if (path.is_absolute() or not path.parts or path.as_posix() != value or len(value.encode("utf-8")) > 512
            or any(part in {"", ".", ".."} for part in path.parts)):
        raise RSILearningError("rsi_actor_cleanroom_path_invalid")
    return value


def _open_directory(path: str | Path, *, dir_fd: int | None = None) -> int:
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dir_fd)


def _require_path_identity(path: str | Path, descriptor: int, *, dir_fd: int | None = None) -> None:
    opened = os.fstat(descriptor)
    current = os.stat(path, dir_fd=dir_fd, follow_symlinks=False)
    if (opened.st_dev, opened.st_ino, stat.S_IFMT(opened.st_mode)) != (
        current.st_dev, current.st_ino, stat.S_IFMT(current.st_mode)
    ):
        raise RSILearningError("rsi_actor_cleanroom_artifact_drift")
    if stat.S_ISREG(opened.st_mode) and any(getattr(opened, name) != getattr(current, name) for name in
                                          ("st_size", "st_mtime_ns", "st_ctime_ns")):
        raise RSILearningError("rsi_actor_cleanroom_artifact_drift")


def _read_artifact(workspace_fd: int, relative: str, maximum: int) -> bytes:
    """Read every path component beneath a pinned workspace without following symlinks."""
    parts = PurePosixPath(relative).parts
    directory = os.dup(workspace_fd)
    parents: list[tuple[int, str, int]] = []
    try:
        for part in parts[:-1]:
            child = _open_directory(part, dir_fd=directory)
            parents.append((directory, part, child))
            directory = child
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode) or not 0 <= before.st_size <= maximum:
                raise RSILearningError("rsi_actor_cleanroom_artifact_invalid")
            chunks: list[bytes] = []
            remaining = before.st_size
            while remaining:
                chunk = os.read(descriptor, min(remaining, 1024 * 1024))
                if not chunk:
                    raise RSILearningError("rsi_actor_cleanroom_artifact_invalid")
                chunks.append(chunk)
                remaining -= len(chunk)
            after = os.fstat(descriptor)
            if os.read(descriptor, 1) or any(getattr(before, name) != getattr(after, name) for name in
                                          ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")):
                raise RSILearningError("rsi_actor_cleanroom_artifact_drift")
            _require_path_identity(parts[-1], descriptor, dir_fd=directory)
            for parent, name, child in reversed(parents):
                _require_path_identity(name, child, dir_fd=parent)
            return b"".join(chunks)
        finally:
            os.close(descriptor)
    finally:
        os.close(directory)
        for parent, _, _ in reversed(parents):
            os.close(parent)


@dataclass(frozen=True)
class ActorCleanRoomEvidence:
    """Explicit immutable provenance; raw digests and Actor manifest digests remain distinct."""

    episode_id: str
    request_sha256: str
    candidate_manifest_sha256: str | None
    dependency_manifest_sha256: str | None
    source_sha256: str | None
    dependency_sha256: str | None
    task_input_sha256: str
    reason: str
    verdict: CleanRoomVerdict | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"protocol": "rsi-actor-cleanroom-evidence-v1", **asdict(self)}

    def digest(self) -> str:
        return _digest(self.to_dict())


class AgentLoopCleanRoomVerifier:
    """Verify a completed local Actor result using immutable bytes in a fresh spawn process."""

    def __init__(
        self, workspace_root: str | Path, *, task_input: bytes | bytearray,
        evaluator: Callable[..., object], evaluator_sha256: str, contract_sha256: str,
        environment_sha256: str, candidate_path: str = "candidate.py",
        dependency_paths: Sequence[str] = ("requirements.txt",), timeout_seconds: float = 30.0,
    ) -> None:
        if not inspect.isfunction(evaluator) or evaluator.__qualname__ != evaluator.__name__ or not _is_importable_fixture(evaluator):
            raise RSILearningError("rsi_actor_cleanroom_evaluator_not_importable")
        if not isinstance(task_input, (bytes, bytearray)) or len(task_input) > MAX_TASK_INPUT_BYTES:
            raise RSILearningError("rsi_actor_cleanroom_task_input_invalid")
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not math.isfinite(float(timeout_seconds)) or not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS:
            raise RSILearningError("rsi_actor_cleanroom_timeout_invalid")
        if not isinstance(dependency_paths, (tuple, list)) or len(dependency_paths) > 32:
            raise RSILearningError("rsi_actor_cleanroom_dependencies_invalid")
        self.workspace_root = Path(workspace_root).expanduser().absolute()
        self.task_input = bytes(task_input)
        self.task_input_sha256 = hashlib.sha256(self.task_input).hexdigest()
        self.evaluator = evaluator
        self.evaluator_sha256 = _pin(evaluator_sha256, "evaluator_sha256")
        self.contract_sha256 = _pin(contract_sha256, "contract_sha256")
        self.environment_sha256 = _pin(environment_sha256, "environment_sha256")
        self.candidate_path = _relative(candidate_path)
        self.dependency_paths = tuple(_relative(path) for path in dependency_paths)
        if len(set(self.dependency_paths)) != len(self.dependency_paths) or self.candidate_path in self.dependency_paths:
            raise RSILearningError("rsi_actor_cleanroom_dependencies_invalid")
        self.timeout_seconds = float(timeout_seconds)
        if component_fingerprint(self.evaluator) != self.evaluator_sha256:
            raise RSILearningError("rsi_actor_cleanroom_evaluator_pin_mismatch")
        self._configured_fingerprint = component_fingerprint(self)

    def rsi_fingerprint_config(self) -> dict[str, Any]:
        return {
            "protocol": "rsi-actor-cleanroom-v1", "workspace_root": str(self.workspace_root),
            "task_input_sha256": hashlib.sha256(self.task_input).hexdigest(), "task_input_size": len(self.task_input),
            "candidate_path": self.candidate_path, "dependency_paths": list(self.dependency_paths),
            "contract_sha256": self.contract_sha256, "environment_sha256": self.environment_sha256,
            "evaluator_sha256": self.evaluator_sha256, "live_evaluator_sha256": component_fingerprint(self.evaluator),
            "timeout_seconds": self.timeout_seconds, "max_source_bytes": MAX_SOURCE_BYTES,
            "max_dependency_bytes": MAX_DEPENDENCY_BYTES,
            "implementations": [component_fingerprint(helper) for helper in (
                _relative, _open_directory, _require_path_identity, _read_artifact, _dependency_digest,
                AgentLoopActorGateway._file_digest, CleanRoomVerifier, CleanRoomProcessVerifier,
            )],
        }

    def _read_material(self, episode_id: str) -> tuple[bytes, tuple[tuple[str, bytes], ...]]:
        identifier = _relative(episode_id)
        if len(PurePosixPath(identifier).parts) != 1:
            raise RSILearningError("rsi_actor_cleanroom_episode_path_invalid")
        root = _open_directory(self.workspace_root)
        episodes = workspace = None
        try:
            episodes = _open_directory("episodes", dir_fd=root)
            workspace = _open_directory(identifier, dir_fd=episodes)
            source = _read_artifact(workspace, self.candidate_path, MAX_SOURCE_BYTES)
            dependencies: list[tuple[str, bytes]] = []
            remaining = MAX_DEPENDENCY_BYTES
            for path in self.dependency_paths:
                data = _read_artifact(workspace, path, remaining)
                remaining -= len(data)
                dependencies.append((path, data))
            _require_path_identity(identifier, workspace, dir_fd=episodes)
            _require_path_identity("episodes", episodes, dir_fd=root)
            _require_path_identity(self.workspace_root, root)
            return source, tuple(dependencies)
        finally:
            if workspace is not None:
                os.close(workspace)
            if episodes is not None:
                os.close(episodes)
            os.close(root)

    def _preflight(self, episode: PracticeEpisode, request: SolverRequest, result: SolverResult) -> None:
        if episode.status != "completed" or result.status != "completed":
            raise RSILearningError("rsi_actor_cleanroom_worker_not_completed")
        if (result.episode_id != episode.episode_id or request.episode_id != episode.episode_id
                or result.request_sha256 != request.digest() or episode.request_sha256 != request.digest()
                or episode.solver_id != request.solver_id
                or episode.memory_snapshot_sha256 != request.memory_snapshot_sha256):
            raise RSILearningError("rsi_actor_cleanroom_request_identity_mismatch")
        for key in ("contract_sha256", "evaluator_sha256", "environment_sha256"):
            if getattr(episode, key) != getattr(self, key) or getattr(request, key) != getattr(self, key):
                raise RSILearningError("rsi_actor_cleanroom_pin_drift")
        for key in ("candidate_receipt_sha256", "execution_receipt_sha256", "official_evaluation_receipt_sha256"):
            if getattr(result, key) is None or getattr(episode, key) != getattr(result, key):
                raise RSILearningError("rsi_actor_cleanroom_receipt_missing_or_drifted")
        if result.actor_fingerprint is None or result.candidate_source_sha256 is None or any(
            getattr(episode, key) != getattr(result, key) for key in
            ("actor_fingerprint", "candidate_source_sha256", "dependency_sha256", "trace_digest", "trace_events")
        ):
            raise RSILearningError("rsi_actor_cleanroom_actor_provenance_drift")
        if (hashlib.sha256(self.task_input).hexdigest() != self.task_input_sha256
                or component_fingerprint(self.evaluator) != self.evaluator_sha256):
            raise RSILearningError("rsi_actor_cleanroom_evaluator_or_task_drift")

    def verify(self, episode: PracticeEpisode, request: SolverRequest, result: SolverResult) -> VerifierDecision:
        return self.verify_with_evidence(episode, request, result)[0]

    def verify_with_evidence(
        self, episode: PracticeEpisode, request: SolverRequest, result: SolverResult,
    ) -> tuple[VerifierDecision, ActorCleanRoomEvidence]:
        if not isinstance(episode, PracticeEpisode) or not isinstance(request, SolverRequest) or not isinstance(result, SolverResult):
            raise TypeError("actor clean-room verification requires typed episode, request and result")
        verdict = None
        candidate_manifest = dependency_manifest = source_digest = dependency_digest = None
        fingerprint = self._configured_fingerprint
        reason = "rsi_actor_cleanroom_unresolved"
        try:
            fingerprint = component_fingerprint(self)
            self._preflight(episode, request, result)
            source, dependencies = self._read_material(episode.episode_id)
            source_digest = hashlib.sha256(source).hexdigest()
            candidate_manifest = _digest([(self.candidate_path, source_digest)])
            dependency_manifest = _digest([(path, hashlib.sha256(data).hexdigest()) for path, data in dependencies]) if dependencies else None
            dependency_digest = _dependency_digest(tuple(sorted(dependencies)))
            if candidate_manifest != result.candidate_source_sha256 or dependency_manifest != result.dependency_sha256:
                raise RSILearningError("rsi_actor_cleanroom_artifact_manifest_drift")
            verification = CleanRoomVerificationRequest(
                episode_id=episode.episode_id,
                candidate=CandidateArtifact(source=source, dependencies=dependencies,
                                            expected_source_sha256=source_digest, expected_dependency_sha256=dependency_digest),
                contract_sha256=self.contract_sha256, task_input=self.task_input,
                task_input_sha256=self.task_input_sha256, evaluator=self.evaluator,
                evaluator_sha256=self.evaluator_sha256, timeout_seconds=self.timeout_seconds,
                actor_evidence={"request_sha256": request.digest(), "result_sha256": _digest(result.to_dict()),
                                "candidate_manifest_sha256": candidate_manifest, "dependency_manifest_sha256": dependency_manifest},
            )
            observed = CleanRoomProcessVerifier().verify(verification)
            if (not isinstance(observed, CleanRoomVerdict)
                    or observed.episode_id != episode.episode_id
                    or observed.source_sha256 != source_digest or observed.dependency_sha256 != dependency_digest
                    or observed.task_input_sha256 != self.task_input_sha256
                    or observed.evaluator_sha256 != self.evaluator_sha256
                    or observed.actor_evidence_sha256 != verification.actor_evidence_sha256
                    or (observed.outcome == "pass" and observed.contamination_reason)):
                raise RSILearningError("rsi_actor_cleanroom_verdict_binding_drift")
            verdict = observed
            reason = verdict.contamination_reason or f"rsi_actor_cleanroom_{verdict.outcome}"
        except RSILearningError as exc:
            reason = str(exc)
        except (OSError, ValueError, TypeError, OverflowError, RecursionError):
            reason = "rsi_actor_cleanroom_artifact_or_identity_invalid"
        outcome = verdict.outcome if verdict is not None else "unresolved"
        evidence = ActorCleanRoomEvidence(
            episode.episode_id, request.digest(), candidate_manifest, dependency_manifest,
            source_digest, dependency_digest, self.task_input_sha256, reason, verdict,
        )
        lineage = {key: getattr(result, key) for key in (
            "candidate_receipt_sha256", "execution_receipt_sha256", "official_evaluation_receipt_sha256", "trace_digest",
        )}
        checks = (
            VerifierCheck("actor_cleanroom_evidence", outcome, evidence.digest()),
            VerifierCheck("cleanroom_evaluator", outcome, verdict.receipt_sha256 if verdict is not None else evidence.digest()),
            VerifierCheck("official_evaluator", "pass" if outcome == "pass" else outcome,
                          result.official_evaluation_receipt_sha256 or _digest(lineage)),
        )
        receipt = _digest({"protocol": "rsi-actor-cleanroom-decision-v1", "evidence_sha256": evidence.digest(),
                           "actor_lineage_sha256": _digest(lineage), "outcome": outcome, "verifier_fingerprint": fingerprint})
        decision = VerifierDecision(
            episode.episode_id, outcome, receipt, reason, fingerprint, checks,
            contract_sha256=request.contract_sha256, evaluator_sha256=request.evaluator_sha256,
            environment_sha256=request.environment_sha256, evidence_sha256=_digest(lineage),
            candidate_receipt_sha256=result.candidate_receipt_sha256,
            execution_receipt_sha256=result.execution_receipt_sha256,
            official_evaluation_receipt_sha256=result.official_evaluation_receipt_sha256,
        )
        return decision, evidence


__all__ = ["ActorCleanRoomEvidence", "AgentLoopCleanRoomVerifier"]
