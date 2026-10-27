"""Opt-in local assignment journal for authenticated external-worker receipts.

Only one host owns this ledger. Registration records a trusted controller's
assignment; it neither launches work nor publishes a native result. An uncertain
assignment or settlement is a permanent recovery gate in this API, never a lease
expiry or permission to retry remote work.
"""

from __future__ import annotations

import re
from typing import Any

from .external_worker_origin import (
    WorkerOriginContext,
    WorkerOriginKey,
    WorkerOriginRegistry,
    new_worker_origin_challenge,
    verify_worker_origin,
)
from .rsi_callbacks import DurableCallbackJournal
from .rsi_gateway import SolverRequest
from .rsi_store import NativeEpisodeClaim, RSILedger

_SCOPE = "external-worker-assignment-v1"
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_REASON = re.compile(r"[a-z][a-z0-9_]{0,127}\Z")
_IDENTITY = ("worker_id", "host_id", "host_boot_id", "key_id")
_OWNER = ("controller_id", "run_id", "task_id", "episode_id")
_DIGESTS = (
    "request_sha256", "plan_sha256", "claim_sha256",
    "controller_checkpoint_sha256", "profile_sha256",
)
_BINDING_FIELDS = {"schema_version", *_IDENTITY, *_OWNER, *_DIGESTS}


class WorkerAssignmentError(ValueError):
    """Fixed rejection codes without receipt or secret contents."""


def _sha(value: object) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        raise WorkerAssignmentError("worker_assignment_digest_invalid")
    return value


def _context(binding: dict[str, Any], challenge: str) -> WorkerOriginContext:
    return WorkerOriginContext(
        **{name: binding[name] for name in _OWNER}, context_kind="native-claim",
        context_sha256=binding["claim_sha256"], controller_challenge=challenge,
        assignment_generation=1,
    )


def _validate_binding(binding: object) -> None:
    if (
        type(binding) is not dict or set(binding) != _BINDING_FIELDS
        or binding["schema_version"] != "1"
    ):
        raise WorkerAssignmentError("worker_assignment_binding_invalid")
    _context(binding, "0" * 64)
    for name in _DIGESTS:
        _sha(binding[name])
    # Reuse the public identity validator without retaining or exporting a key.
    WorkerOriginKey(**{name: binding[name] for name in _IDENTITY}, secret_key=b"\0" * 32)


def _validate_assignment_result(binding: dict[str, Any], result: object) -> None:
    if type(result) is not dict or set(result) != {"context"}:
        raise WorkerAssignmentError("worker_assignment_result_invalid")
    context = WorkerOriginContext.from_dict(result["context"])
    if context != _context(binding, context.controller_challenge):
        raise WorkerAssignmentError("worker_assignment_context_drift")


def _validate_settlement_result(assignment: dict[str, Any], result: object) -> None:
    if type(result) is not dict:
        raise WorkerAssignmentError("worker_assignment_settlement_invalid")
    if result.get("assignment_checkpoint_sha256") != assignment["assignment_checkpoint_sha256"]:
        raise WorkerAssignmentError("worker_assignment_settlement_drift")
    if result.get("outcome") == "unknown":
        if (
            set(result) != {"outcome", "assignment_checkpoint_sha256", "reason_code"}
            or type(result["reason_code"]) is not str
            or _REASON.fullmatch(result["reason_code"]) is None
        ):
            raise WorkerAssignmentError("worker_assignment_reason_invalid")
        return
    if result.get("outcome") != "receipt_authenticated" or set(result) != {
        "outcome", "assignment_checkpoint_sha256", "verified_origin",
    }:
        raise WorkerAssignmentError("worker_assignment_settlement_invalid")
    origin = result["verified_origin"]
    expected = {
        **assignment["context"],
        **{name: assignment["binding"][name] for name in (*_IDENTITY, "profile_sha256")},
    }
    if type(origin) is not dict or set(origin) != {*expected, "receipt_sha256", "wire_sha256"}:
        raise WorkerAssignmentError("worker_assignment_settlement_invalid")
    if any(origin[name] != value for name, value in expected.items()):
        raise WorkerAssignmentError("worker_assignment_settlement_drift")
    _sha(origin["receipt_sha256"])
    _sha(origin["wire_sha256"])


class ExternalWorkerAssignments:
    """Single-authority, once-only registration and origin receipt consumption."""

    def __init__(
        self, ledger: RSILedger, *, controller_id: str, run_id: str, task_id: str,
        registry: WorkerOriginRegistry,
    ) -> None:
        if not isinstance(ledger, RSILedger) or type(registry) is not WorkerOriginRegistry:
            raise WorkerAssignmentError("worker_assignment_authority_invalid")
        WorkerOriginContext(controller_id, run_id, task_id, "validation", "native-claim", "0" * 64, "0" * 64, 1)
        self.ledger = ledger
        self.journal = DurableCallbackJournal(ledger)
        self.controller_id = controller_id
        self.run_id = run_id
        self.task_id = task_id
        self.registry = registry

    @staticmethod
    def _ids(episode_id: str) -> tuple[str, str, str]:
        WorkerOriginContext("validation", "validation", "validation", episode_id, "native-claim", "0" * 64, "0" * 64, 1)
        digest = DurableCallbackJournal.digest({"episode_id": episode_id})
        return "assignment:" + digest, "settlement:" + digest, "external-worker-guard:" + digest

    def _guard(self, expected: str, request: SolverRequest, plan_sha256: str) -> NativeEpisodeClaim:
        _sha(expected)
        _sha(plan_sha256)
        if not self.ledger.controller_lock_held(self.run_id):
            raise WorkerAssignmentError("worker_assignment_controller_lock_required")
        current = self.ledger.controller_checkpoint(self.run_id)
        if current is None or current[0] != expected:
            raise WorkerAssignmentError("worker_assignment_controller_checkpoint_conflict")
        claim = self.ledger.inspect_native_episode_claim(request, plan_sha256=plan_sha256)
        if claim is None or claim.status != "started":
            raise WorkerAssignmentError("worker_assignment_started_claim_required")
        return claim

    def inspect(self, episode_id: str) -> dict[str, Any] | None:
        """Read retained intent/context/outcome; never reserve or consume anything."""
        assignment_id, settlement_id, _guard_id = self._ids(episode_id)
        entry = self.journal.inspect(_SCOPE, assignment_id)
        if entry is None:
            return None
        digest, state = entry
        binding = state["binding"]
        _validate_binding(binding)
        if any(binding[name] != value for name, value in {
            "controller_id": self.controller_id, "run_id": self.run_id,
            "task_id": self.task_id, "episode_id": episode_id,
        }.items()):
            raise WorkerAssignmentError("worker_assignment_owner_drift")
        snapshot = {
            "status": "preparing", "assignment_checkpoint_sha256": digest,
            "binding": binding, "context": None,
            "settlement_checkpoint_sha256": None, "settlement": None,
        }
        settled = self.journal.inspect(_SCOPE, settlement_id)
        if state["status"] == "started":
            if settled is not None:
                raise WorkerAssignmentError("worker_assignment_settlement_without_assignment")
            return snapshot
        _validate_assignment_result(binding, state["result"])
        snapshot.update(status="assigned", context=state["result"]["context"])
        if settled is not None:
            settled_digest, settled_state = settled
            settled_binding = settled_state["binding"]
            if (
                set(settled_binding) != {"assignment_checkpoint_sha256", "controller_checkpoint_sha256"}
                or settled_binding["assignment_checkpoint_sha256"] != digest
            ):
                raise WorkerAssignmentError("worker_assignment_settlement_drift")
            _sha(settled_binding["controller_checkpoint_sha256"])
            snapshot.update(
                status="settlement_recovery_required", settlement_checkpoint_sha256=settled_digest,
            )
            if settled_state["status"] == "completed":
                _validate_settlement_result(snapshot, settled_state["result"])
                snapshot.update(
                    status=settled_state["result"]["outcome"], settlement=settled_state["result"],
                )
        return snapshot

    def reserve_assignment(
        self, request: SolverRequest, *, plan_sha256: str, profile_sha256: str,
        worker: WorkerOriginKey, expected_native_claim: NativeEpisodeClaim,
        expected_controller_checkpoint_sha256: str,
    ) -> dict[str, Any]:
        """Persist one original assignment, with no launch or delivery side effect."""
        _sha(profile_sha256)
        if type(worker) is not WorkerOriginKey or type(expected_native_claim) is not NativeEpisodeClaim:
            raise WorkerAssignmentError("worker_assignment_identity_invalid")
        worker.__post_init__()
        if worker.revoked:
            raise WorkerAssignmentError("worker_assignment_worker_revoked")
        identity = {name: getattr(worker, name) for name in _IDENTITY}
        if self.registry.worker_identity(worker.worker_id) != identity:
            raise WorkerAssignmentError("worker_assignment_worker_drift")
        assignment_id, _settlement_id, guard_id = self._ids(request.episode_id)
        claim = self._guard(expected_controller_checkpoint_sha256, request, plan_sha256)
        if claim != expected_native_claim:
            raise WorkerAssignmentError("worker_assignment_native_claim_drift")
        binding = {
            "schema_version": "1", "controller_id": self.controller_id,
            "run_id": self.run_id, "task_id": self.task_id, "episode_id": request.episode_id,
            "request_sha256": request.digest(), "plan_sha256": plan_sha256,
            "claim_sha256": claim.claim_sha256,
            "controller_checkpoint_sha256": expected_controller_checkpoint_sha256,
            "profile_sha256": profile_sha256,
            **identity,
        }
        _validate_binding(binding)

        def before() -> None:
            if self._guard(expected_controller_checkpoint_sha256, request, plan_sha256) != expected_native_claim:
                raise WorkerAssignmentError("worker_assignment_native_claim_drift")

        with self.ledger.controller_lock(guard_id):
            if self.journal.inspect(_SCOPE, assignment_id) is not None:
                raise WorkerAssignmentError("worker_assignment_already_reserved")
            self.journal.invoke(
                _SCOPE, assignment_id, binding=binding,
                call=lambda: {"context": _context(binding, new_worker_origin_challenge()).to_dict()},
                validate=lambda result: _validate_assignment_result(binding, result), before_call=before,
            )
            return self.inspect(request.episode_id)

    def _active(
        self, request: SolverRequest, *, plan_sha256: str,
        expected_controller_checkpoint_sha256: str,
    ) -> dict[str, Any]:
        claim = self._guard(expected_controller_checkpoint_sha256, request, plan_sha256)
        assignment = self.inspect(request.episode_id)
        if assignment is None or assignment["status"] != "assigned":
            raise WorkerAssignmentError("worker_assignment_recovery_or_settlement_gate")
        binding = assignment["binding"]
        if (
            binding["request_sha256"] != request.digest() or binding["plan_sha256"] != plan_sha256
            or binding["claim_sha256"] != claim.claim_sha256
        ):
            raise WorkerAssignmentError("worker_assignment_native_claim_drift")
        return assignment

    def _settle(
        self, assignment: dict[str, Any], result: dict[str, Any], *, request: SolverRequest,
        plan_sha256: str, expected_controller_checkpoint_sha256: str,
    ) -> dict[str, Any]:
        _assignment_id, settlement_id, _guard_id = self._ids(request.episode_id)
        return self.journal.invoke(
            _SCOPE, settlement_id,
            binding={
                "assignment_checkpoint_sha256": assignment["assignment_checkpoint_sha256"],
                "controller_checkpoint_sha256": expected_controller_checkpoint_sha256,
            },
            call=lambda: result,
            validate=lambda value: _validate_settlement_result(assignment, value),
            before_call=lambda: self._active(
                request, plan_sha256=plan_sha256,
                expected_controller_checkpoint_sha256=expected_controller_checkpoint_sha256,
            ),
        )

    def record_origin_receipt(
        self, request: SolverRequest, *, plan_sha256: str,
        expected_controller_checkpoint_sha256: str, raw: bytes, receipt: bytes,
    ) -> dict[str, Any]:
        """Authenticate original bytes and consume once; never accept native results."""
        self._guard(expected_controller_checkpoint_sha256, request, plan_sha256)
        _assignment_id, _settlement_id, guard_id = self._ids(request.episode_id)
        with self.ledger.controller_lock(guard_id):
            assignment = self._active(
                request, plan_sha256=plan_sha256,
                expected_controller_checkpoint_sha256=expected_controller_checkpoint_sha256,
            )
            verified = verify_worker_origin(
                raw, registry=self.registry,
                expected_context=WorkerOriginContext.from_dict(assignment["context"]),
                expected_profile_sha256=assignment["binding"]["profile_sha256"], receipt=receipt,
            )
            if any(getattr(verified, name) != assignment["binding"][name] for name in _IDENTITY):
                raise WorkerAssignmentError("worker_assignment_worker_drift")
            return self._settle(
                assignment, {
                    "outcome": "receipt_authenticated",
                    "assignment_checkpoint_sha256": assignment["assignment_checkpoint_sha256"],
                    "verified_origin": verified.to_dict(),
                }, request=request, plan_sha256=plan_sha256,
                expected_controller_checkpoint_sha256=expected_controller_checkpoint_sha256,
            )

    def mark_unknown(
        self, request: SolverRequest, *, plan_sha256: str,
        expected_controller_checkpoint_sha256: str, reason_code: str,
    ) -> dict[str, Any]:
        """Fence uncertainty once; no timer or disconnected transport can reassign it."""
        if type(reason_code) is not str or _REASON.fullmatch(reason_code) is None:
            raise WorkerAssignmentError("worker_assignment_reason_invalid")
        self._guard(expected_controller_checkpoint_sha256, request, plan_sha256)
        _assignment_id, _settlement_id, guard_id = self._ids(request.episode_id)
        with self.ledger.controller_lock(guard_id):
            assignment = self._active(
                request, plan_sha256=plan_sha256,
                expected_controller_checkpoint_sha256=expected_controller_checkpoint_sha256,
            )
            return self._settle(
                assignment, {
                    "outcome": "unknown",
                    "assignment_checkpoint_sha256": assignment["assignment_checkpoint_sha256"],
                    "reason_code": reason_code,
                }, request=request, plan_sha256=plan_sha256,
                expected_controller_checkpoint_sha256=expected_controller_checkpoint_sha256,
            )
