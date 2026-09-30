"""Fail-closed bridge from a clean-room verdict to memory governance.

The clean-room verifier deliberately remains independent from the controller and from the
durable memory admission store.  This module is the narrow boundary between those two
authorities: it checks the immutable verdict against caller-owned artifact pins, then appends
only the ``observed -> verified`` governance revisions.  Candidate/shadow/holdout promotion is
left to :mod:`rsi_memory_promotion`.

The operation is retry-safe.  Replaying the same admission after a process interruption returns
the existing verified head; a different verdict or provenance for the same admission id fails
closed instead of silently reusing the old evidence.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .rsi_cleanroom import CleanRoomVerdict
from .rsi_memory_governance import (
    MemoryAdmissionRecord,
    MemoryGovernanceError,
    MemoryGovernanceStore,
)


class CleanRoomAdmissionError(MemoryGovernanceError):
    """Fixed-code errors raised at the clean-room admission boundary."""


def _digest(value: object, name: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if (
        type(value) is not str
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise CleanRoomAdmissionError(f"rsi_cleanroom_admission_{name}_invalid")
    return value


def _identifier(value: object, name: str) -> str:
    if type(value) is not str or not value.strip() or any(char in value for char in "\x00\r\n"):
        raise CleanRoomAdmissionError(f"rsi_cleanroom_admission_{name}_invalid")
    return value


def _mapping(value: Mapping[str, object], name: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise CleanRoomAdmissionError(f"rsi_cleanroom_admission_{name}_invalid")
    # MemoryGovernanceStore performs the canonical bounded JSON validation.  Copy here so a
    # caller cannot mutate a mapping between request validation and the governance write.
    return dict(value)


@dataclass(frozen=True)
class CleanRoomAdmissionRequest:
    """Caller-owned identity and provenance pins for one memory admission."""

    admission_id: str
    memory_snapshot_sha256: str
    memory_item_sha256: str
    source_episode_id: str
    parent_snapshot_sha256: str | None
    scope: str
    compatibility: Mapping[str, object]
    contract_sha256: str
    expected_source_sha256: str
    expected_dependency_sha256: str
    expected_task_input_sha256: str
    expected_evaluator_sha256: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.admission_id, "admission_id"),
            (self.source_episode_id, "source_episode_id"),
            (self.scope, "scope"),
        ):
            _identifier(value, name)
        for value, name in (
            (self.memory_snapshot_sha256, "memory_snapshot_sha256"),
            (self.memory_item_sha256, "memory_item_sha256"),
            (self.contract_sha256, "contract_sha256"),
            (self.expected_source_sha256, "expected_source_sha256"),
            (self.expected_dependency_sha256, "expected_dependency_sha256"),
            (self.expected_task_input_sha256, "expected_task_input_sha256"),
            (self.expected_evaluator_sha256, "expected_evaluator_sha256"),
        ):
            _digest(value, name)
        _digest(self.parent_snapshot_sha256, "parent_snapshot_sha256", optional=True)
        object.__setattr__(self, "compatibility", _mapping(self.compatibility, "compatibility"))


class CleanRoomAdmissionGate:
    """Admit one independent clean-room pass into the durable governance lifecycle."""

    def __init__(self, governance: MemoryGovernanceStore) -> None:
        if not isinstance(governance, MemoryGovernanceStore):
            raise CleanRoomAdmissionError("rsi_cleanroom_admission_governance_invalid")
        self.governance = governance

    @staticmethod
    def _validate_verdict(request: CleanRoomAdmissionRequest, verdict: CleanRoomVerdict) -> None:
        if not isinstance(verdict, CleanRoomVerdict):
            raise CleanRoomAdmissionError("rsi_cleanroom_admission_verdict_invalid")
        if verdict.outcome != "pass" or verdict.contamination_reason:
            raise CleanRoomAdmissionError("rsi_cleanroom_admission_verdict_not_pass")
        expected = {
            "episode_id": request.source_episode_id,
            "source_sha256": request.expected_source_sha256,
            "dependency_sha256": request.expected_dependency_sha256,
            "task_input_sha256": request.expected_task_input_sha256,
            "evaluator_sha256": request.expected_evaluator_sha256,
        }
        if any(getattr(verdict, key) != value for key, value in expected.items()):
            raise CleanRoomAdmissionError("rsi_cleanroom_admission_provenance_drift")
        _digest(verdict.receipt_sha256, "verdict_receipt_sha256")

    @staticmethod
    def _same_identity(
        current: MemoryAdmissionRecord,
        request: CleanRoomAdmissionRequest,
        verdict: CleanRoomVerdict,
    ) -> bool:
        return (
            current.memory_snapshot_sha256 == request.memory_snapshot_sha256
            and current.memory_item_sha256 == request.memory_item_sha256
            and current.source_episode_id == request.source_episode_id
            and current.parent_snapshot_sha256 == request.parent_snapshot_sha256
            and current.scope == request.scope
            and dict(current.compatibility) == dict(request.compatibility)
            and current.verifier_receipt_sha256 in {None, verdict.receipt_sha256}
            and current.episode_outcome == "pass"
        )

    def admit(
        self, request: CleanRoomAdmissionRequest, verdict: CleanRoomVerdict
    ) -> MemoryAdmissionRecord:
        """Create or replay the ``observed -> verified`` admission for a clean-room pass.

        No memory snapshot is mutated and no promotion beyond ``verified`` is performed.  A
        caller must provide artifact pins independently of the actor's score; the verdict is
        accepted only when every pin matches exactly.
        """

        if not isinstance(request, CleanRoomAdmissionRequest):
            raise CleanRoomAdmissionError("rsi_cleanroom_admission_request_invalid")
        self._validate_verdict(request, verdict)
        observed = MemoryAdmissionRecord(
            admission_id=request.admission_id,
            memory_snapshot_sha256=request.memory_snapshot_sha256,
            memory_item_sha256=request.memory_item_sha256,
            source_episode_id=request.source_episode_id,
            verifier_receipt_sha256=None,
            parent_snapshot_sha256=request.parent_snapshot_sha256,
            scope=request.scope,
            compatibility=request.compatibility,
            episode_outcome="pass",
        )
        current = self.governance.get(request.admission_id)
        if current is None:
            try:
                current = self.governance.create(observed)
            except MemoryGovernanceError as exc:
                # Another local controller can win the create race.  Re-read only for the
                # exact admission id; a different identity must still be rejected below.
                if exc.code != "rsi_memory_governance_exists":
                    raise
                current = self.governance.get(request.admission_id)
                if current is None:
                    raise
        if current is None or not self._same_identity(current, request, verdict):
            raise CleanRoomAdmissionError("rsi_cleanroom_admission_identity_conflict")
        if current.state == "verified":
            return current
        if current.state != "observed":
            raise CleanRoomAdmissionError("rsi_cleanroom_admission_state_conflict")
        try:
            return self.governance.transition(
                request.admission_id,
                "verified",
                expected_record_sha256=current.record_sha256,
                verifier_receipt_sha256=verdict.receipt_sha256,
                episode_outcome="pass",
            )
        except MemoryGovernanceError:
            # A concurrent identical transition is replay-safe; inspect the resulting head and
            # return it only when its complete identity still matches this request.
            latest = self.governance.get(request.admission_id)
            if (
                latest is not None
                and latest.state == "verified"
                and self._same_identity(latest, request, verdict)
            ):
                return latest
            raise


def admit_cleanroom_verdict(
    governance: MemoryGovernanceStore,
    request: CleanRoomAdmissionRequest,
    verdict: CleanRoomVerdict,
) -> MemoryAdmissionRecord:
    """Functional wrapper for :class:`CleanRoomAdmissionGate`."""

    return CleanRoomAdmissionGate(governance).admit(request, verdict)


__all__ = [
    "CleanRoomAdmissionError",
    "CleanRoomAdmissionGate",
    "CleanRoomAdmissionRequest",
    "admit_cleanroom_verdict",
]
