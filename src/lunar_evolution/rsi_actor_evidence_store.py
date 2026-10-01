"""Create-only full Actor clean-room evidence and a retry-safe local verifier wrapper."""

from __future__ import annotations

import hashlib
import math
import os
import secrets
import stat
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .candidate_evaluation_spec import canonical_json, strict_json
from .rsi_actor_verifier import ActorCleanRoomEvidence, AgentLoopCleanRoomVerifier, _relative
from .rsi_cleanroom import (
    MAX_DEPENDENCY_BYTES,
    MAX_SOURCE_BYTES,
    MAX_TASK_INPUT_BYTES,
    MAX_TIMEOUT_SECONDS,
    CleanRoomVerdict,
)
from .rsi_cleanroom_admission import CleanRoomAdmissionGate, CleanRoomAdmissionRequest
from .rsi_gateway import SolverRequest, SolverResult
from .rsi_identity import component_fingerprint
from .rsi_learning import PracticeEpisode, RSILearningError, VerifierCheck, VerifierDecision

MAX_ACTOR_EVIDENCE_BYTES = 1024 * 1024
_PROTOCOL = "lunar-rsi-actor-evidence-record-v1"
_CLAIM_PROTOCOL = "lunar-rsi-actor-verification-claim-v1"
_CONFIG_FIELDS = {
    "protocol", "workspace_root", "task_input_sha256", "task_input_size", "candidate_path",
    "dependency_paths", "contract_sha256", "environment_sha256", "evaluator_sha256",
    "live_evaluator_sha256", "timeout_seconds", "max_source_bytes", "max_dependency_bytes",
    "implementations",
}


class ActorEvidenceStoreError(RSILearningError):
    """Fixed public codes for durable evidence rejection and unknown verification."""


def _fail(code: str) -> None:
    raise ActorEvidenceStoreError("rsi_actor_evidence_" + code)


def _canonical(value: object) -> bytes:
    try:
        return canonical_json(value, maximum=MAX_ACTOR_EVIDENCE_BYTES)
    except ValueError as exc:
        raise ActorEvidenceStoreError("rsi_actor_evidence_invalid") from exc


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value, maximum=128 * 1024)).hexdigest()


def _pin(value: object) -> None:
    if type(value) is not str or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        _fail("pin_invalid")


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


@contextmanager
def _directory_chain(path: Path, *, create: bool = False):
    held = [(None, path.anchor, os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW))]
    try:
        for part in path.parts[1:]:
            parent = held[-1][2]
            try:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(part, 0o700, dir_fd=parent)
                except FileExistsError:
                    pass
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            held.append((parent, part, child))
        yield held[-1][2]
        for parent, name, descriptor in held:
            current = os.stat(name, dir_fd=parent, follow_symlinks=False)
            opened = os.fstat(descriptor)
            if (current.st_dev, current.st_ino, current.st_mode) != (
                opened.st_dev, opened.st_ino, opened.st_mode,
            ):
                _fail("directory_changed")
    except OSError as exc:
        raise ActorEvidenceStoreError("rsi_actor_evidence_storage_invalid") from exc
    finally:
        for _, _, descriptor in reversed(held):
            os.close(descriptor)


def _read(directory: int, name: str) -> bytes | None:
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    except FileNotFoundError:
        return None
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 < before.st_size <= MAX_ACTOR_EVIDENCE_BYTES:
            _fail("storage_invalid")
        remaining, chunks = before.st_size, []
        while remaining:
            chunk = os.read(descriptor, min(remaining, 65536))
            if not chunk:
                _fail("storage_invalid")
            remaining -= len(chunk)
            chunks.append(chunk)
        after = os.fstat(descriptor)
        named = os.stat(name, dir_fd=directory, follow_symlinks=False)
        if os.read(descriptor, 1) or _identity(before) != _identity(after) or _identity(after) != _identity(named):
            _fail("storage_changed")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _publish(directory: int, name: str, data: bytes) -> bool:
    temporary = ".actor-evidence-" + secrets.token_hex(16)
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
    try:
        position = 0
        while position < len(data):
            size = os.write(descriptor, data[position:])
            if size < 1:
                _fail("write_failed")
            position += size
        os.fsync(descriptor)
        opened = os.fstat(descriptor)
        named = os.stat(temporary, dir_fd=directory, follow_symlinks=False)
        if _identity(opened) != _identity(named) or opened.st_nlink != 1:
            _fail("storage_changed")
        try:
            os.link(temporary, name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
        except FileExistsError:
            return False
        os.unlink(temporary, dir_fd=directory)
        os.fsync(directory)
        return True
    finally:
        os.close(descriptor)
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass


def _binding_material(episode, request, result, verifier_config, verifier_fingerprint) -> dict[str, Any]:
    if not isinstance(episode, PracticeEpisode) or not isinstance(request, SolverRequest) or not isinstance(result, SolverResult):
        _fail("input_invalid")
    _pin(verifier_fingerprint)
    config = strict_json(_canonical(dict(verifier_config)), maximum=MAX_ACTOR_EVIDENCE_BYTES)
    if set(config) != _CONFIG_FIELDS or config["protocol"] != "rsi-actor-cleanroom-v1":
        _fail("configuration_incomplete")
    for field in ("contract_sha256", "environment_sha256", "evaluator_sha256", "live_evaluator_sha256", "task_input_sha256"):
        _pin(config[field])
    if (config["live_evaluator_sha256"] != config["evaluator_sha256"]
            or any(config[key] != getattr(request, key) for key in
                   ("contract_sha256", "environment_sha256", "evaluator_sha256"))):
        _fail("pin_drift")
    _relative(config["candidate_path"])
    dependencies = config["dependency_paths"]
    if (not isinstance(dependencies, list) or any(type(path) is not str for path in dependencies)
            or len(dependencies) > 32 or len(set(dependencies)) != len(dependencies)
            or config["candidate_path"] in dependencies):
        _fail("configuration_invalid")
    for path in dependencies:
        _relative(path)
    if (type(config["task_input_size"]) is not int or not 0 <= config["task_input_size"] <= MAX_TASK_INPUT_BYTES
            or config["max_source_bytes"] != MAX_SOURCE_BYTES or config["max_dependency_bytes"] != MAX_DEPENDENCY_BYTES
            or type(config["workspace_root"]) is not str or not Path(config["workspace_root"]).is_absolute()
            or not isinstance(config["implementations"], list) or not config["implementations"]):
        _fail("configuration_invalid")
    for implementation in config["implementations"]:
        _pin(implementation)
    timeout = config["timeout_seconds"]
    if type(timeout) not in {int, float} or not math.isfinite(timeout) or not 0 < timeout <= MAX_TIMEOUT_SECONDS:
        _fail("configuration_invalid")
    if (episode.episode_id != request.episode_id or result.episode_id != request.episode_id
            or episode.request_sha256 != request.digest() or result.request_sha256 != request.digest()
            or any(getattr(episode, key) != getattr(request, key) for key in (
                "contract_sha256", "evaluator_sha256", "environment_sha256", "solver_id", "memory_snapshot_sha256"))
            or any(getattr(episode, key) != getattr(result, key) for key in (
                "candidate_receipt_sha256", "execution_receipt_sha256", "official_evaluation_receipt_sha256",
                "actor_fingerprint", "candidate_source_sha256", "dependency_sha256", "trace_digest", "trace_events"))):
        _fail("input_drift")
    stable = episode.to_record_dict()
    for key in ("verifier", "previous_record_sha256", "record_sha256"):
        stable.pop(key)
    return {"episode": stable, "request": request.to_dict(), "result": result.to_dict(),
            "verifier_config": config, "verifier_fingerprint": verifier_fingerprint}


def _binding(episode, request, result, verifier_config, verifier_fingerprint) -> dict[str, Any]:
    try:
        return _binding_material(episode, request, result, verifier_config, verifier_fingerprint)
    except ActorEvidenceStoreError:
        raise
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
        raise ActorEvidenceStoreError("rsi_actor_evidence_input_invalid") from exc


def _validate(binding: Mapping[str, Any], decision: VerifierDecision, evidence: ActorCleanRoomEvidence) -> None:
    if not isinstance(decision, VerifierDecision) or not isinstance(evidence, ActorCleanRoomEvidence):
        _fail("evidence_invalid")
    request, result, config = binding["request"], binding["result"], binding["verifier_config"]
    for value in (evidence.candidate_manifest_sha256, evidence.dependency_manifest_sha256,
                  evidence.source_sha256, evidence.dependency_sha256):
        if value is not None:
            _pin(value)
    _pin(evidence.task_input_sha256)
    if (evidence.episode_id != request["episode_id"] or evidence.request_sha256 != _digest(request)
            or evidence.task_input_sha256 != config["task_input_sha256"]
            or type(evidence.reason) is not str or not evidence.reason or len(evidence.reason.encode()) > 512):
        _fail("evidence_drift")
    if evidence.source_sha256 is not None and evidence.candidate_manifest_sha256 != _digest([
        (config["candidate_path"], evidence.source_sha256),
    ]):
        _fail("source_drift")
    verdict = evidence.verdict
    if verdict is not None and not isinstance(verdict, CleanRoomVerdict):
        _fail("verdict_drift")
    outcome = verdict.outcome if verdict is not None else "unresolved"
    if verdict is not None:
        actor_digest = _digest({"request_sha256": evidence.request_sha256, "result_sha256": _digest(result),
                               "candidate_manifest_sha256": evidence.candidate_manifest_sha256,
                               "dependency_manifest_sha256": evidence.dependency_manifest_sha256})
        if (not isinstance(verdict, CleanRoomVerdict) or verdict.episode_id != evidence.episode_id
                or verdict.source_sha256 != evidence.source_sha256 or verdict.dependency_sha256 != evidence.dependency_sha256
                or verdict.task_input_sha256 != evidence.task_input_sha256 or verdict.evaluator_sha256 != config["evaluator_sha256"]
                or verdict.actor_evidence_sha256 != actor_digest
                or evidence.candidate_manifest_sha256 != result["candidate_source_sha256"]
                or evidence.dependency_manifest_sha256 != result["dependency_sha256"]
                or evidence.reason != (verdict.contamination_reason or "rsi_actor_cleanroom_" + verdict.outcome)
                or (verdict.outcome == "pass" and verdict.contamination_reason)):
            _fail("verdict_drift")
    lineage = {key: result[key] for key in (
        "candidate_receipt_sha256", "execution_receipt_sha256", "official_evaluation_receipt_sha256", "trace_digest",
    )}
    checks = (
        VerifierCheck("actor_cleanroom_evidence", outcome, evidence.digest()),
        VerifierCheck("cleanroom_evaluator", outcome, verdict.receipt_sha256 if verdict else evidence.digest()),
        VerifierCheck("official_evaluator", outcome, result["official_evaluation_receipt_sha256"] or _digest(lineage)),
    )
    receipt = _digest({"protocol": "rsi-actor-cleanroom-decision-v1", "evidence_sha256": evidence.digest(),
                       "actor_lineage_sha256": _digest(lineage), "outcome": outcome,
                       "verifier_fingerprint": binding["verifier_fingerprint"]})
    expected = VerifierDecision(
        request["episode_id"], outcome, receipt, evidence.reason, binding["verifier_fingerprint"], checks,
        contract_sha256=request["contract_sha256"], evaluator_sha256=request["evaluator_sha256"],
        environment_sha256=request["environment_sha256"], evidence_sha256=_digest(lineage),
        candidate_receipt_sha256=result["candidate_receipt_sha256"], execution_receipt_sha256=result["execution_receipt_sha256"],
        official_evaluation_receipt_sha256=result["official_evaluation_receipt_sha256"],
    )
    if decision != expected or (outcome == "pass" and (
        result["status"] != "completed" or binding["episode"]["status"] != "completed"
        or any(result[key] is None for key in lineage) or result["actor_fingerprint"] is None
    )):
        _fail("decision_drift")


@dataclass(frozen=True)
class StoredActorCleanRoomEvidence:
    decision: VerifierDecision
    evidence: ActorCleanRoomEvidence
    record_sha256: str
    _bytes: bytes

    def to_bytes(self) -> bytes:
        return self._bytes

    def to_dict(self) -> dict[str, Any]:
        return strict_json(self._bytes, maximum=MAX_ACTOR_EVIDENCE_BYTES)


def _record(binding: dict[str, Any], decision: VerifierDecision, evidence: ActorCleanRoomEvidence) -> StoredActorCleanRoomEvidence:
    try:
        _validate(binding, decision, evidence)
    except ActorEvidenceStoreError:
        raise
    except (TypeError, ValueError, AttributeError, KeyError, OverflowError, RecursionError) as exc:
        raise ActorEvidenceStoreError("rsi_actor_evidence_evidence_invalid") from exc
    content = {"protocol": _PROTOCOL, "binding": binding, "decision": decision.to_dict(),
               "evidence": evidence.to_dict(), "evidence_sha256": evidence.digest()}
    digest = hashlib.sha256(_canonical(content)).hexdigest()
    return StoredActorCleanRoomEvidence(decision, evidence, digest, _canonical({**content, "record_sha256": digest}))


def _decode(data: bytes, binding: dict[str, Any]) -> StoredActorCleanRoomEvidence:
    try:
        value = strict_json(data, maximum=MAX_ACTOR_EVIDENCE_BYTES)
        if (not isinstance(value, dict) or set(value) != {"protocol", "binding", "decision", "evidence", "evidence_sha256", "record_sha256"}
                or value["protocol"] != _PROTOCOL or value["binding"] != binding):
            _fail("identity_conflict")
        raw_decision = dict(value["decision"])
        raw_decision["checks"] = tuple(VerifierCheck(**check) for check in raw_decision["checks"])
        decision = VerifierDecision(**raw_decision)
        raw_evidence = dict(value["evidence"])
        if raw_evidence.pop("protocol") != "rsi-actor-cleanroom-evidence-v1":
            _fail("evidence_invalid")
        if raw_evidence["verdict"] is not None:
            raw_evidence["verdict"] = CleanRoomVerdict(**raw_evidence["verdict"])
        evidence = ActorCleanRoomEvidence(**raw_evidence)
        record = _record(binding, decision, evidence)
        if record.to_bytes() != data:
            _fail("record_invalid")
        return record
    except ActorEvidenceStoreError:
        raise
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
        raise ActorEvidenceStoreError("rsi_actor_evidence_record_invalid") from exc


class ActorCleanRoomEvidenceStore:
    """Bounded immutable sidecars under an identity-pinned no-follow directory."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().absolute()
        with _directory_chain(self.root, create=True) as directory:
            info = os.fstat(directory)
            self._identity = info.st_dev, info.st_ino

    @contextmanager
    def _directory(self):
        with _directory_chain(self.root) as directory:
            info = os.fstat(directory)
            if (info.st_dev, info.st_ino) != self._identity:
                _fail("directory_changed")
            yield directory

    def rsi_fingerprint_config(self) -> dict[str, Any]:
        return {"protocol": _PROTOCOL, "root": str(self.root), "device": self._identity[0],
                "inode": self._identity[1], "max_bytes": MAX_ACTOR_EVIDENCE_BYTES,
                "implementations": [component_fingerprint(getattr(helper, "__wrapped__", helper)) for helper in (
                    _canonical, _digest, _pin, _identity, _directory_chain, _read, _publish,
                    _binding_material, _binding, _validate, _record, _decode,
                    StoredActorCleanRoomEvidence, ActorCleanRoomEvidence, CleanRoomVerdict,
                    VerifierDecision, VerifierCheck,
                )]}

    @staticmethod
    def _name(episode_id: str, *, claim: bool = False) -> str:
        return hashlib.sha256(episode_id.encode()).hexdigest() + (".claim.json" if claim else ".json")

    def load(self, episode: PracticeEpisode, request: SolverRequest, result: SolverResult, *,
             verifier_config: Mapping[str, Any], verifier_fingerprint: str) -> StoredActorCleanRoomEvidence | None:
        binding = _binding(episode, request, result, verifier_config, verifier_fingerprint)
        with self._directory() as directory:
            data = _read(directory, self._name(episode.episode_id))
            record = _decode(data, binding) if data is not None else None
            if record is not None and episode.verifier is not None and episode.verifier != record.decision:
                _fail("decision_drift")
            return record

    def begin(self, episode: PracticeEpisode, request: SolverRequest, result: SolverResult, *,
              verifier_config: Mapping[str, Any], verifier_fingerprint: str) -> None:
        binding = _binding(episode, request, result, verifier_config, verifier_fingerprint)
        content = {"protocol": _CLAIM_PROTOCOL, "binding": binding}
        digest = hashlib.sha256(_canonical(content)).hexdigest()
        expected = _canonical({**content, "claim_sha256": digest})
        with self._directory() as directory:
            name = self._name(episode.episode_id, claim=True)
            if not _publish(directory, name, expected):
                if _read(directory, name) != expected:
                    _fail("identity_conflict")
                _fail("unknown_reconcile_required")
            if _read(directory, name) != expected:
                _fail("write_failed")

    def save(self, episode: PracticeEpisode, request: SolverRequest, result: SolverResult,
             decision: VerifierDecision, evidence: ActorCleanRoomEvidence, *,
             verifier_config: Mapping[str, Any], verifier_fingerprint: str) -> StoredActorCleanRoomEvidence:
        binding = _binding(episode, request, result, verifier_config, verifier_fingerprint)
        if episode.verifier is not None and episode.verifier != decision:
            _fail("decision_drift")
        record = _record(binding, decision, evidence)
        with self._directory() as directory:
            claim = _read(directory, self._name(episode.episode_id, claim=True))
            if claim is not None:
                content = {"protocol": _CLAIM_PROTOCOL, "binding": binding}
                expected = _canonical({**content, "claim_sha256": hashlib.sha256(_canonical(content)).hexdigest()})
                if claim != expected:
                    _fail("identity_conflict")
            name = self._name(episode.episode_id)
            existing = _read(directory, name)
            if existing is not None:
                if existing != record.to_bytes():
                    _fail("identity_conflict")
                return _decode(existing, binding)
            _publish(directory, name, record.to_bytes())
            observed = _read(directory, name)
            if observed != record.to_bytes():
                _fail("identity_conflict")
            return _decode(observed, binding)

    def admit(self, episode: PracticeEpisode, request: SolverRequest, result: SolverResult, *,
              verifier_config: Mapping[str, Any], verifier_fingerprint: str,
              admission: CleanRoomAdmissionRequest, gate: CleanRoomAdmissionGate):
        if not isinstance(admission, CleanRoomAdmissionRequest) or not isinstance(gate, CleanRoomAdmissionGate):
            _fail("admission_invalid")
        record = self.load(episode, request, result, verifier_config=verifier_config,
                           verifier_fingerprint=verifier_fingerprint)
        if record is None or record.decision.outcome != "pass" or record.evidence.verdict is None:
            _fail("admission_not_pass")
        evidence = record.evidence
        if (admission.contract_sha256 != request.contract_sha256 or admission.source_episode_id != request.episode_id
                or admission.expected_source_sha256 != evidence.source_sha256
                or admission.expected_dependency_sha256 != evidence.dependency_sha256
                or admission.expected_task_input_sha256 != evidence.task_input_sha256
                or admission.expected_evaluator_sha256 != request.evaluator_sha256):
            _fail("admission_pin_drift")
        return gate.admit(admission, evidence.verdict)


class DurableActorCleanRoomVerifier:
    """Persist full evidence before returning, and never retry an uncertain evaluation."""

    def __init__(self, bridge: AgentLoopCleanRoomVerifier, store: ActorCleanRoomEvidenceStore) -> None:
        if not isinstance(bridge, AgentLoopCleanRoomVerifier) or not isinstance(store, ActorCleanRoomEvidenceStore):
            _fail("configuration_invalid")
        self.bridge, self.store = bridge, store

    def rsi_fingerprint_config(self) -> dict[str, Any]:
        return {"protocol": "lunar-rsi-durable-actor-verifier-v1",
                "bridge_sha256": component_fingerprint(self.bridge),
                "store_sha256": component_fingerprint(self.store)}

    def verify(self, episode: PracticeEpisode, request: SolverRequest, result: SolverResult) -> VerifierDecision:
        return self.verify_with_evidence(episode, request, result)[0]

    def verify_with_evidence(self, episode: PracticeEpisode, request: SolverRequest, result: SolverResult):
        pins = {"verifier_config": self.bridge.rsi_fingerprint_config(),
                "verifier_fingerprint": component_fingerprint(self.bridge)}
        stored = self.store.load(episode, request, result, **pins)
        if stored is None:
            self.store.begin(episode, request, result, **pins)
            decision, evidence = self.bridge.verify_with_evidence(episode, request, result)
            stored = self.store.save(episode, request, result, decision, evidence, **pins)
        return stored.decision, stored.evidence


__all__ = [
    "MAX_ACTOR_EVIDENCE_BYTES",
    "ActorCleanRoomEvidenceStore",
    "ActorEvidenceStoreError",
    "DurableActorCleanRoomVerifier",
    "StoredActorCleanRoomEvidence",
]
