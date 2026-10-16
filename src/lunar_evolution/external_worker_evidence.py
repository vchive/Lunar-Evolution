"""Durable local worker lifecycle evidence built on RSI's hash-chain callback journal."""
from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .candidate_evaluation_spec import canonical_json
from .rsi_callbacks import DurableCallbackJournal
from .rsi_learning import RSILearningError
from .rsi_store import RSILedger

_SHA = re.compile(r"^[0-9a-f]{64}$")
_TERMINAL = frozenset({"failed", "timed_out", "cancelled", "abandoned"})
_MAX = 128 * 1024
_RECONCILIATION_SOURCE = "controller-observed-v1"


class ExternalWorkerEvidenceError(RSILearningError):
    """Fixed local worker evidence error codes."""


@dataclass(frozen=True, slots=True)
class ExternalWorkerTrustProfile:
    project_id: str
    project_version: str
    project_commit_sha256: str
    executable_sha256: str
    runtime_sha256: str
    dependency_sha256: str
    launch_intent_sha256: str
    parent_run_id: str
    task_id: str
    episode_id: str
    owner_token_sha256: str
    pid: int
    pgid: int
    process_start_identity: str
    workspace_device: int
    workspace_inode: int
    transport_device: int
    transport_inode: int
    journal_device: int
    journal_inode: int

    def __post_init__(self) -> None:
        for value, name in ((self.project_id, "project"), (self.project_version, "version"),
                            (self.parent_run_id, "parent_run"), (self.task_id, "task"),
                            (self.episode_id, "episode")):
            if type(value) is not str or not value or len(value) > 256 or any(c in value for c in "\x00\r\n"):
                raise ExternalWorkerEvidenceError(f"external_worker_{name}_invalid")
        for value, name in ((self.project_commit_sha256, "commit"), (self.executable_sha256, "executable"),
                            (self.runtime_sha256, "runtime"), (self.dependency_sha256, "dependency"),
                            (self.launch_intent_sha256, "intent"), (self.owner_token_sha256, "owner_token")):
            if type(value) is not str or _SHA.fullmatch(value) is None:
                raise ExternalWorkerEvidenceError(f"external_worker_{name}_invalid")
        if type(self.process_start_identity) is not str or not self.process_start_identity or len(self.process_start_identity) > 256:
            raise ExternalWorkerEvidenceError("external_worker_process_start_invalid")
        for value, name, minimum in ((self.pid, "pid", 1), (self.pgid, "pgid", 1),
                                     (self.workspace_device, "workspace_device", 0),
                                     (self.workspace_inode, "workspace_inode", 1),
                                     (self.transport_device, "transport_device", 0),
                                     (self.transport_inode, "transport_inode", 1),
                                     (self.journal_device, "journal_device", 0),
                                     (self.journal_inode, "journal_inode", 1)):
            if type(value) is not int or value < minimum:
                raise ExternalWorkerEvidenceError(f"external_worker_{name}_invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id, "project_version": self.project_version,
            "project_commit_sha256": self.project_commit_sha256, "executable_sha256": self.executable_sha256,
            "runtime_sha256": self.runtime_sha256, "dependency_sha256": self.dependency_sha256,
            "launch_intent_sha256": self.launch_intent_sha256, "parent_run_id": self.parent_run_id,
            "task_id": self.task_id, "episode_id": self.episode_id, "owner_token_sha256": self.owner_token_sha256,
            "pid": self.pid, "pgid": self.pgid, "process_start_identity": self.process_start_identity,
            "workspace": {"device": self.workspace_device, "inode": self.workspace_inode},
            "transport": {"device": self.transport_device, "inode": self.transport_inode},
            "journal": {"device": self.journal_device, "inode": self.journal_inode},
        }

    def digest(self) -> str:
        return hashlib.sha256(canonical_json(self.to_dict(), maximum=_MAX)).hexdigest()


@dataclass(frozen=True, slots=True)
class ExternalWorkerState:
    profile: ExternalWorkerTrustProfile
    status: str
    revision: int
    event: Mapping[str, Any]
    checkpoint_sha256: str


@dataclass(frozen=True, slots=True)
class ExternalWorkerInspection:
    """Read-only, controller-verifiable projection of worker evidence.

    This projection deliberately contains no process liveness claim.  It only
    reports what is durably present in the local callback journal and whether
    the terminal evidence is quarantined.  Callers must still perform any
    platform-specific PID/PGID checks before trusting an external worker.
    """

    profile_sha256: str
    status: str
    quarantine: bool
    claim_checkpoint_sha256: str
    latest_checkpoint_sha256: str
    terminal_receipt_sha256: str | None
    controller_observed_terminal: bool | None
    cleanup_confirmed: bool | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_sha256": self.profile_sha256,
            "status": self.status,
            "quarantine": self.quarantine,
            "claim_checkpoint_sha256": self.claim_checkpoint_sha256,
            "latest_checkpoint_sha256": self.latest_checkpoint_sha256,
            "terminal_receipt_sha256": self.terminal_receipt_sha256,
            "controller_observed_terminal": self.controller_observed_terminal,
            "cleanup_confirmed": self.cleanup_confirmed,
        }


@dataclass(frozen=True, slots=True)
class ExternalWorkerReconcileEvidence:
    """Controller-owned evidence which settles one quarantined ``unknown`` worker.

    The evidence is deliberately narrower than a terminal receipt.  It must name the exact
    profile and unknown checkpoint being settled, and can only settle to a non-success terminal
    state after the controller has observed both the terminal process state and cleanup.  This is
    a local, provider-free binding; ``source`` identifies the protocol boundary but does not
    authenticate a remote operator or grant distributed ownership.
    """

    profile_sha256: str
    unknown_checkpoint_sha256: str
    status: str
    terminal_receipt_sha256: str
    controller_observed_terminal: bool
    cleanup_confirmed: bool
    source: str = _RECONCILIATION_SOURCE
    reason: str = "controller settled quarantined worker"

    def __post_init__(self) -> None:
        for value, name in ((self.profile_sha256, "profile"),
                            (self.unknown_checkpoint_sha256, "unknown_checkpoint"),
                            (self.terminal_receipt_sha256, "terminal_receipt")):
            if type(value) is not str or _SHA.fullmatch(value) is None:
                raise ExternalWorkerEvidenceError(f"external_worker_{name}_invalid")
        if self.status not in _TERMINAL:
            raise ExternalWorkerEvidenceError("external_worker_reconcile_state_invalid")
        if type(self.controller_observed_terminal) is not bool or type(self.cleanup_confirmed) is not bool:
            raise ExternalWorkerEvidenceError("external_worker_reconcile_observation_invalid")
        if self.controller_observed_terminal is not True or self.cleanup_confirmed is not True:
            raise ExternalWorkerEvidenceError("external_worker_reconcile_observation_invalid")
        if self.source != _RECONCILIATION_SOURCE:
            raise ExternalWorkerEvidenceError("external_worker_reconcile_source_invalid")
        if (type(self.reason) is not str or not self.reason.strip() or len(self.reason) > 512
                or any(char in self.reason for char in "\x00\r\n")):
            raise ExternalWorkerEvidenceError("external_worker_reconcile_reason_invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_sha256": self.profile_sha256,
            "unknown_checkpoint_sha256": self.unknown_checkpoint_sha256,
            "status": self.status,
            "terminal_receipt_sha256": self.terminal_receipt_sha256,
            "controller_observed_terminal": self.controller_observed_terminal,
            "cleanup_confirmed": self.cleanup_confirmed,
            "source": self.source,
            "reason": self.reason,
        }

    def digest(self) -> str:
        return hashlib.sha256(canonical_json(self.to_dict(), maximum=_MAX)).hexdigest()


class ExternalWorkerEvidenceStore:
    """Append-only worker claim, heartbeat and terminal receipts in the RSI ledger."""

    def __init__(self, ledger: RSILedger, *, scope_id: str) -> None:
        if not isinstance(ledger, RSILedger):
            raise ExternalWorkerEvidenceError("external_worker_ledger_invalid")
        if type(scope_id) is not str or not scope_id or len(scope_id) > 256:
            raise ExternalWorkerEvidenceError("external_worker_scope_invalid")
        self.ledger = ledger
        self.scope_id = scope_id
        self.journal = DurableCallbackJournal(ledger)

    def _binding(self, profile: ExternalWorkerTrustProfile) -> dict[str, Any]:
        if not isinstance(profile, ExternalWorkerTrustProfile):
            raise ExternalWorkerEvidenceError("external_worker_profile_invalid")
        return {"protocol": "lunar-external-worker-evidence-v1", "scope_id": self.scope_id,
                "profile": profile.to_dict(), "profile_sha256": profile.digest()}

    def claim(self, profile: ExternalWorkerTrustProfile, *, heartbeat_sha256: str) -> ExternalWorkerState:
        if type(heartbeat_sha256) is not str or _SHA.fullmatch(heartbeat_sha256) is None:
            raise ExternalWorkerEvidenceError("external_worker_heartbeat_invalid")
        binding = self._binding(profile)
        event = {"kind": "claim", "heartbeat_sha256": heartbeat_sha256,
                 "owner_token_sha256": profile.owner_token_sha256}
        result = self.journal.invoke(
            self.scope_id, profile.episode_id + ":claim", binding=binding,
            call=lambda: {"status": "running", "event": event},
            validate=lambda value: self._validate_event(binding, "running", value),
        )
        checkpoint = self.journal.inspect(self.scope_id, profile.episode_id + ":claim")
        if checkpoint is None:
            raise ExternalWorkerEvidenceError("external_worker_claim_missing")
        return ExternalWorkerState(profile, result["status"], 0, result["event"], checkpoint[0])

    @staticmethod
    def _validate_event(binding: Mapping[str, Any], status: str, value: Mapping[str, Any]) -> None:
        if type(value) is not dict or set(value) != {"status", "event"} or value["status"] != status or type(value["event"]) is not dict:
            raise ExternalWorkerEvidenceError("external_worker_receipt_invalid")
        event = value["event"]
        if event.get("owner_token_sha256") != binding["profile"]["owner_token_sha256"]:
            raise ExternalWorkerEvidenceError("external_worker_owner_mismatch")
        if status == "completed" and (event.get("controller_observed_terminal") is not True or event.get("cleanup_confirmed") is not True):
            raise ExternalWorkerEvidenceError("external_worker_success_unobserved")
        if status == "unknown" and event.get("evaluator_authority") is not None:
            raise ExternalWorkerEvidenceError("external_worker_unknown_authority")

    def _state(self, profile: ExternalWorkerTrustProfile) -> tuple[str, dict[str, Any]]:
        found = self.journal.inspect(self.scope_id, profile.episode_id + ":claim")
        if found is None:
            raise ExternalWorkerEvidenceError("external_worker_claim_missing")
        digest, state = found
        binding = self._binding(profile)
        if self.journal.digest(state["binding"]) != self.journal.digest(binding):
            raise ExternalWorkerEvidenceError("external_worker_profile_drift")
        if state["status"] == "started":
            return digest, {"status": "running", "event": {"kind": "claim"}}
        result = state["result"]
        self._validate_event(binding, result["status"], result)
        terminal = self.journal.inspect(self.scope_id, profile.episode_id + ":terminal")
        if terminal is not None and terminal[1]["status"] == "completed":
            terminal_result = terminal[1]["result"]
            self._validate_event(binding, terminal_result["status"], terminal_result)
            if terminal_result["status"] == "unknown":
                # A quarantined terminal can only leave quarantine through the separate,
                # controller-owned reconciliation callback.  The original unknown callback is
                # retained as the parent checkpoint and is never rewritten in place.
                reconciliation = self.journal.inspect(
                    self.scope_id, profile.episode_id + ":unknown-reconcile"
                )
                if reconciliation is not None:
                    reconcile_digest, reconcile_state = reconciliation
                    if reconcile_state["status"] != "completed":
                        raise ExternalWorkerEvidenceError("external_worker_reconcile_required")
                    reconcile_result = reconcile_state["result"]
                    reconcile_binding = {
                        **binding,
                        "unknown_checkpoint_sha256": terminal[0],
                        "unknown_terminal_receipt_sha256": terminal_result["event"].get(
                            "terminal_receipt_sha256"
                        ),
                        "evidence_sha256": reconcile_result["event"].get("evidence_sha256"),
                    }
                    if self.journal.digest(reconcile_state["binding"]) != self.journal.digest(
                        reconcile_binding
                    ):
                        raise ExternalWorkerEvidenceError("external_worker_reconcile_binding_drift")
                    self._validate_reconciliation_event(
                        reconcile_binding, reconcile_result
                    )
                    return reconcile_digest, reconcile_result
            return terminal[0], terminal_result
        return digest, result

    @staticmethod
    def _validate_reconciliation_event(
        binding: Mapping[str, Any], value: Mapping[str, Any]
    ) -> None:
        if type(value) is not dict or set(value) != {"status", "event"}:
            raise ExternalWorkerEvidenceError("external_worker_receipt_invalid")
        status, event = value["status"], value["event"]
        if status not in _TERMINAL or type(event) is not dict:
            raise ExternalWorkerEvidenceError("external_worker_reconcile_state_invalid")
        if event.get("kind") != "unknown-reconcile":
            raise ExternalWorkerEvidenceError("external_worker_reconcile_event_invalid")
        if event.get("owner_token_sha256") != binding["profile"]["owner_token_sha256"]:
            raise ExternalWorkerEvidenceError("external_worker_owner_mismatch")
        if event.get("status") != status:
            raise ExternalWorkerEvidenceError("external_worker_reconcile_state_invalid")
        if event.get("controller_observed_terminal") is not True or event.get("cleanup_confirmed") is not True:
            raise ExternalWorkerEvidenceError("external_worker_reconcile_observation_invalid")
        if event.get("unknown_checkpoint_sha256") != binding.get("unknown_checkpoint_sha256"):
            raise ExternalWorkerEvidenceError("external_worker_reconcile_checkpoint_conflict")
        if event.get("unknown_terminal_receipt_sha256") != binding.get("unknown_terminal_receipt_sha256"):
            raise ExternalWorkerEvidenceError("external_worker_reconcile_checkpoint_conflict")
        if _SHA.fullmatch(event.get("terminal_receipt_sha256", "")) is None:
            raise ExternalWorkerEvidenceError("external_worker_terminal_receipt_invalid")
        if _SHA.fullmatch(event.get("evidence_sha256", "")) is None:
            raise ExternalWorkerEvidenceError("external_worker_reconcile_evidence_invalid")
        if type(event.get("reason")) is not str or not event["reason"]:
            raise ExternalWorkerEvidenceError("external_worker_reconcile_reason_invalid")

    def heartbeat(self, profile: ExternalWorkerTrustProfile, *, checkpoint_sha256: str,
                  heartbeat_sha256: str) -> ExternalWorkerState:
        current_sha, current = self._state(profile)
        if current["status"] != "running":
            raise ExternalWorkerEvidenceError("external_worker_not_running")
        if checkpoint_sha256 != current_sha or type(heartbeat_sha256) is not str or _SHA.fullmatch(heartbeat_sha256) is None:
            raise ExternalWorkerEvidenceError("external_worker_heartbeat_conflict")
        # Each heartbeat has its own callback ID, so journal history is create-only and replayable.
        binding = {**self._binding(profile), "parent_checkpoint_sha256": current_sha}
        callback = profile.episode_id + ":heartbeat:" + heartbeat_sha256
        event = {"kind": "heartbeat", "heartbeat_sha256": heartbeat_sha256,
                 "parent_checkpoint_sha256": current_sha, "owner_token_sha256": profile.owner_token_sha256}
        result = self.journal.invoke(self.scope_id, callback, binding=binding,
                                     call=lambda: {"status": "running", "event": event},
                                     validate=lambda value: self._validate_event(self._binding(profile), "running", value))
        found = self.journal.inspect(self.scope_id, callback)
        assert found is not None
        return ExternalWorkerState(profile, result["status"], 1, result["event"], found[0])

    def settle(self, profile: ExternalWorkerTrustProfile, *, checkpoint_sha256: str,
               status: str, terminal_receipt_sha256: str, controller_observed_terminal: bool,
               cleanup_confirmed: bool) -> ExternalWorkerState:
        if status not in {*_TERMINAL, "unknown"}:
            raise ExternalWorkerEvidenceError("external_worker_terminal_state_invalid")
        current_sha, current = self._state(profile)
        if current["status"] != "running" or checkpoint_sha256 != current_sha:
            raise ExternalWorkerEvidenceError("external_worker_terminal_conflict")
        if type(terminal_receipt_sha256) is not str or _SHA.fullmatch(terminal_receipt_sha256) is None:
            raise ExternalWorkerEvidenceError("external_worker_terminal_receipt_invalid")
        if status in _TERMINAL and (controller_observed_terminal is not True or cleanup_confirmed is not True):
            raise ExternalWorkerEvidenceError("external_worker_cleanup_unconfirmed")
        if status == "unknown" and (controller_observed_terminal or cleanup_confirmed):
            raise ExternalWorkerEvidenceError("external_worker_unknown_claim_invalid")
        binding = {**self._binding(profile), "parent_checkpoint_sha256": current_sha,
                   "terminal_receipt_sha256": terminal_receipt_sha256}
        callback = profile.episode_id + ":terminal"
        event = {"status": status, "terminal_receipt_sha256": terminal_receipt_sha256,
                 "controller_observed_terminal": controller_observed_terminal,
                 "cleanup_confirmed": cleanup_confirmed, "owner_token_sha256": profile.owner_token_sha256}
        result = self.journal.invoke(self.scope_id, callback, binding=binding,
                                     call=lambda: {"status": status, "event": event},
                                     validate=lambda value: self._validate_event(self._binding(profile), status, value))
        found = self.journal.inspect(self.scope_id, callback)
        assert found is not None
        return ExternalWorkerState(profile, result["status"], 2, result["event"], found[0])

    def reconcile_unknown(
        self, profile: ExternalWorkerTrustProfile, *, evidence: ExternalWorkerReconcileEvidence
    ) -> ExternalWorkerState:
        """Settle an ``unknown`` terminal using an exact controller-owned evidence record.

        This operation appends a new callback after the original unknown terminal.  It never
        overwrites or reuses the unknown callback, cannot produce ``completed``, and is idempotent
        only for the exact same evidence binding.  The method is intentionally local: the source
        marker is a protocol boundary and does not claim remote authentication.
        """
        if not isinstance(profile, ExternalWorkerTrustProfile):
            raise ExternalWorkerEvidenceError("external_worker_profile_invalid")
        if not isinstance(evidence, ExternalWorkerReconcileEvidence):
            raise ExternalWorkerEvidenceError("external_worker_reconcile_evidence_invalid")
        if evidence.profile_sha256 != profile.digest():
            raise ExternalWorkerEvidenceError("external_worker_reconcile_profile_drift")
        current_sha, current = self._state(profile)
        if current["status"] in _TERMINAL:
            replay = self.journal.inspect(self.scope_id, profile.episode_id + ":unknown-reconcile")
            if replay is None or replay[1]["status"] != "completed":
                raise ExternalWorkerEvidenceError("external_worker_reconcile_not_required")
            event = replay[1]["result"].get("event", {})
            if event.get("evidence_sha256") != evidence.digest():
                raise ExternalWorkerEvidenceError("external_worker_reconcile_conflict")
            return ExternalWorkerState(profile, current["status"], 3, current["event"], current_sha)
        if current["status"] != "unknown":
            raise ExternalWorkerEvidenceError("external_worker_reconcile_not_required")
        terminal = self.journal.inspect(self.scope_id, profile.episode_id + ":terminal")
        if terminal is None or terminal[1]["status"] != "completed":
            raise ExternalWorkerEvidenceError("external_worker_terminal_corrupt")
        terminal_result = terminal[1]["result"]
        self._validate_event(self._binding(profile), terminal_result["status"], terminal_result)
        if terminal_result["status"] != "unknown" or current_sha != terminal[0]:
            raise ExternalWorkerEvidenceError("external_worker_reconcile_not_required")
        if evidence.unknown_checkpoint_sha256 != terminal[0]:
            raise ExternalWorkerEvidenceError("external_worker_reconcile_checkpoint_conflict")
        if evidence.terminal_receipt_sha256 == terminal_result["event"].get("terminal_receipt_sha256"):
            raise ExternalWorkerEvidenceError("external_worker_reconcile_receipt_conflict")
        binding = {
            **self._binding(profile),
            "unknown_checkpoint_sha256": terminal[0],
            "unknown_terminal_receipt_sha256": terminal_result["event"].get(
                "terminal_receipt_sha256"
            ),
            "evidence_sha256": evidence.digest(),
        }
        event = {
            "kind": "unknown-reconcile",
            "status": evidence.status,
            "terminal_receipt_sha256": evidence.terminal_receipt_sha256,
            "unknown_checkpoint_sha256": terminal[0],
            "unknown_terminal_receipt_sha256": terminal_result["event"].get(
                "terminal_receipt_sha256"
            ),
            "evidence_sha256": evidence.digest(),
            "controller_observed_terminal": True,
            "cleanup_confirmed": True,
            "owner_token_sha256": profile.owner_token_sha256,
            "reason": evidence.reason,
        }
        result = self.journal.invoke(
            self.scope_id,
            profile.episode_id + ":unknown-reconcile",
            binding=binding,
            call=lambda: {"status": evidence.status, "event": event},
            validate=lambda value: self._validate_reconciliation_event(binding, value),
        )
        found = self.journal.inspect(self.scope_id, profile.episode_id + ":unknown-reconcile")
        if found is None:
            raise ExternalWorkerEvidenceError("external_worker_reconcile_missing")
        return ExternalWorkerState(profile, result["status"], 3, result["event"], found[0])

    def inspect(self, profile: ExternalWorkerTrustProfile) -> ExternalWorkerState:
        _digest, current = self._state(profile)
        return ExternalWorkerState(profile, current["status"], 0, current["event"], _digest)

    def inspect_verified(self, profile: ExternalWorkerTrustProfile) -> ExternalWorkerInspection:
        """Inspect all local worker evidence without writing or relaunching.

        Unlike :meth:`inspect`, this returns a stable diagnostic projection for
        operators and tests.  It validates the claim and any heartbeat/terminal
        records through the callback journal, then marks ``unknown`` terminal
        evidence as quarantined.  A missing claim remains an error because no
        worker identity can be established from an unclaimed episode.
        """
        if not isinstance(profile, ExternalWorkerTrustProfile):
            raise ExternalWorkerEvidenceError("external_worker_profile_invalid")
        claim = self.journal.inspect(self.scope_id, profile.episode_id + ":claim")
        if claim is None:
            raise ExternalWorkerEvidenceError("external_worker_claim_missing")
        claim_digest, claim_state = claim
        binding = self._binding(profile)
        if self.journal.digest(claim_state["binding"]) != self.journal.digest(binding):
            raise ExternalWorkerEvidenceError("external_worker_profile_drift")
        if claim_state["status"] == "completed":
            claim_result = claim_state["result"]
            self._validate_event(binding, claim_result["status"], claim_result)
        latest_digest, current = self._state(profile)
        status = current["status"]
        event: Mapping[str, Any] = current["event"] if status != "running" else {}
        return ExternalWorkerInspection(
            profile_sha256=profile.digest(),
            status=status,
            quarantine=status == "unknown",
            claim_checkpoint_sha256=claim_digest,
            latest_checkpoint_sha256=latest_digest,
            terminal_receipt_sha256=event.get("terminal_receipt_sha256"),
            controller_observed_terminal=event.get("controller_observed_terminal"),
            cleanup_confirmed=event.get("cleanup_confirmed"),
        )

    def reconcile_status(self, profile: ExternalWorkerTrustProfile) -> str:
        """Return a read-only reconciliation classification.

        ``unknown`` is intentionally reported as ``quarantined`` and never
        converted into a successful state by this method.
        """
        inspection = self.inspect_verified(profile)
        if inspection.quarantine:
            return "quarantined"
        if inspection.status == "running":
            return "needs_terminal_observation"
        if inspection.status in _TERMINAL and inspection.controller_observed_terminal and inspection.cleanup_confirmed:
            return "terminal_verified"
        return "unresolved"


__all__ = [
    "ExternalWorkerEvidenceError", "ExternalWorkerEvidenceStore", "ExternalWorkerInspection",
    "ExternalWorkerReconcileEvidence", "ExternalWorkerState", "ExternalWorkerTrustProfile",
]
