"""One original native worker's preparation handover; no publication authority.

This ephemeral transport never creates a claim, result, checkpoint or owner. Its
caller must independently observe the started claim and create the original
terminal lifecycle. Budget/cancellation checks execute outside its Condition.
"""

from __future__ import annotations

import math
import re
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, fields

from .candidate_evaluation_spec import canonical_json
from .native_trusted_output import NativeTrustedOutputPreparation
from .native_trusted_scheduler import (
    NativeTrustedProducerRun,
    _NativeTrustedPythonProducerPreparation,
)
from .producer_bundle_admission import ProducerBundleAdmissionItem, ProducerBundleAdmissionPlan
from .producer_handoff import ProducerMaterial, ProducerResultEnvelope
from .producer_process import (
    ProducerEnvelopeEvidence,
    ProducerExecutionReceipt,
    ProducerStreamEvidence,
)
from .python_producer_admission_handoff import (
    PythonProducerAdmissionHandoff,
    PythonProducerAdmissionHandoffFilePin,
    PythonProducerAdmissionHandoffSidecar,
)
from .rsi_gateway import SolverRequest
from .rsi_learning import RSILearningError
from .rsi_native_plan import NativeRSIExecutionPlan
from .rsi_python_brs_handoff import BRSSelectedChildHandoff
from .rsi_python_brs_publication_mailbox import BRSOwnerPublicationMailbox
from .rsi_python_brs_terminal_lifecycle import _BRSWorkerTerminalEndpoint, _PrimitiveExchange
from .rsi_store import NativeEpisodeClaim, RSILedger

_MAX_BYTES = 1024 * 1024  # ephemeral comparison only; no persisted record ceiling changes
_DTOS = (SolverRequest, NativeEpisodeClaim, NativeRSIExecutionPlan, ProducerExecutionReceipt,
         ProducerStreamEvidence, ProducerEnvelopeEvidence, ProducerBundleAdmissionPlan,
         ProducerBundleAdmissionItem, ProducerResultEnvelope, ProducerMaterial,
         PythonProducerAdmissionHandoff, PythonProducerAdmissionHandoffFilePin,
         PythonProducerAdmissionHandoffSidecar)


def _fail(code: str) -> None:
    raise RSILearningError("rsi_brs_preparation_" + code)


def _plain(value, remaining, depth=0):
    remaining[0] -= 1
    if depth > 48 or remaining[0] < 0:
        _fail("shape_invalid")
    kind = type(value)
    if value is None or kind is bool:
        return value
    if kind is int and value.bit_length() <= 128:
        return value
    if kind is float and math.isfinite(value):
        return value
    if kind is str:
        remaining[1] -= len(value)
        if remaining[1] < 0:
            _fail("shape_invalid")
        return value
    if kind in _DTOS:
        names = tuple(field.name for field in fields(kind))
        # Non-slotted DTOs may shadow dataclass metadata or serializer methods.
        try:
            attrs = object.__getattribute__(value, "__dict__")
        except AttributeError:
            pass
        else:
            if type(attrs) is not dict or set(attrs) != set(names):
                _fail("shape_invalid")
        return {name: _plain(getattr(value, name), remaining, depth + 1) for name in names}
    if kind is dict and len(value) <= 2048 and all(type(key) is str for key in value):
        return {_plain(key, remaining, depth + 1): _plain(item, remaining, depth + 1)
                for key, item in value.items()}
    if kind in (tuple, list) and len(value) <= 2048:
        return [_plain(item, remaining, depth + 1) for item in value]
    _fail("shape_invalid")


def _bytes(value):
    return canonical_json(_plain(value, [32768, _MAX_BYTES]), maximum=_MAX_BYTES)


def _preparation_bytes(preparation, request, plan, claim):
    if (type(preparation) is not _NativeTrustedPythonProducerPreparation
            or type(preparation.run) is not NativeTrustedProducerRun
            or type(preparation.run.output) is not NativeTrustedOutputPreparation
            or type(preparation.handoff) is not PythonProducerAdmissionHandoffSidecar
            or type(request) is not SolverRequest or type(plan) is not NativeRSIExecutionPlan
            or type(claim) is not NativeEpisodeClaim):
        _fail("shape_invalid")
    run, output = preparation.run, preparation.run.output
    # Deliberately exclude unused attempt/draft/bundle objects. The owner rereads
    # retained files independently; none of those worker objects is an input grant.
    values = {name: getattr(output, name) for name in (
        "process_terminal_sha256", "output_capture_sha256", "envelope_bytes_sha256",
        "execution_receipt_sha256", "request_coverage", "publication_eligible",
    )}
    raw = _bytes((request, plan, claim, run.status, run.publication, run.deadline_scope,
                  run.receipt, output.admission_plan, output.envelope, values, preparation.handoff))
    parsed = NativeRSIExecutionPlan.from_dict(NativeRSIExecutionPlan.to_dict(plan))
    if (run.status != "prepared" or run.publication is not None
            or type(run.deadline_scope) is not str
            or run.deadline_scope not in {"native_attempt_only", "caller_lifecycle"}
            or output.publication_eligible is not False
            or output.request_coverage != "brokered_requests_only"
            or type(run.receipt) is not ProducerExecutionReceipt
            or type(output.admission_plan) is not ProducerBundleAdmissionPlan
            or type(output.envelope) is not ProducerResultEnvelope
            or type(preparation.handoff.handoff) is not PythonProducerAdmissionHandoff
            or type(preparation.handoff.file_pin) is not PythonProducerAdmissionHandoffFilePin
            or any(type(getattr(claim, field.name)) is not str for field in fields(NativeEpisodeClaim))
            or claim.status != "started" or not claim.created_at
            or parsed.request_sha256 != SolverRequest.digest(request)
            or (claim.episode_id, claim.request_sha256, claim.plan_sha256) !=
                (request.episode_id, parsed.request_sha256, parsed.plan_sha256)
            or claim.claim_sha256 != RSILedger._native_claim_digest(
                claim.episode_id, claim.request_sha256, claim.plan_sha256)):
        _fail("association_invalid")
    return raw


@dataclass(frozen=True, slots=True)
class _BRSNativePreparationOffer:
    request: SolverRequest
    plan: NativeRSIExecutionPlan
    claim: NativeEpisodeClaim
    preparation: _NativeTrustedPythonProducerPreparation
    thread: threading.Thread
    comparison_bytes: bytes


class _BRSNativePreparationExchange:
    """One offer/take/endpoint handback for one exact natural running worker."""

    __slots__ = ("_attachment", "_condition", "_deadline", "_endpoint", "_endpoint_scope", "_executor",
                 "_failed", "_future", "_offer", "_offer_scope", "_owner", "_plan_sha256", "_request",
                 "_request_bytes", "_scope", "_state")

    def __init__(self, request: SolverRequest, *, expected_plan_sha256: str, deadline: float):
        if (type(request) is not SolverRequest or type(expected_plan_sha256) is not str
                or re.fullmatch(r"[0-9a-f]{64}", expected_plan_sha256) is None
                or expected_plan_sha256 == "0" * 64 or type(deadline) not in (int, float)
                or not math.isfinite(deadline) or deadline <= 0):
            _fail("scope_invalid")
        self._request_bytes = _bytes(request)
        SolverRequest.from_dict(SolverRequest.to_dict(request))
        self._condition = threading.Condition()
        self._request, self._plan_sha256, self._deadline = request, expected_plan_sha256, deadline
        self._owner = threading.current_thread()
        self._scope = (self._condition, request, self._request_bytes, expected_plan_sha256, deadline, self._owner)
        self._future = self._executor = self._offer = self._endpoint = None
        self._attachment = self._offer_scope = self._endpoint_scope = None
        self._state, self._failed = "unused", False

    def _fixed(self, *, owner=False):
        if (type(self) is not _BRSNativePreparationExchange or type(self._scope) is not tuple
                or len(self._scope) != 6 or type(self._condition) is not threading.Condition
                or self._scope[0] is not self._condition or self._scope[1] is not self._request
                or self._scope[2] is not self._request_bytes
                or type(self._scope[3]) is not str or type(self._plan_sha256) is not str
                or self._scope[3] != self._plan_sha256
                or type(self._scope[4]) not in (int, float) or type(self._deadline) not in (int, float)
                or self._scope[4] != self._deadline
                or self._scope[5] is not self._owner
                or type(self._state) is not str or type(self._failed) is not bool
                or (self._attachment is not None and (type(self._attachment) is not tuple
                    or len(self._attachment) != 2 or self._attachment[0] is not self._future
                    or self._attachment[1] is not self._executor))
                or (owner and threading.current_thread() is not self._owner)
                or _bytes(self._request) != self._request_bytes):
            _fail("scope_drift")

    def _poison(self):
        with self._condition:
            self._failed = True
            self._condition.notify_all()

    def _check(self, check, *, owner=False):
        self._fixed(owner=owner)
        if not callable(check):
            _fail("check_invalid")
        check()
        self._fixed(owner=owner)
        with self._condition:
            if self._failed:
                _fail("unavailable")
            if time.monotonic() >= self._deadline:
                _fail("expired")

    def attach_worker(self, future: Future, executor: ThreadPoolExecutor):
        try:
            self._fixed(owner=True)
            if (type(future) is not Future or type(executor) is not ThreadPoolExecutor
                    or executor._max_workers != 1 or not future.running() or future.done()):
                _fail("worker_invalid")
            with self._condition:
                if self._failed or self._future is not None or self._executor is not None:
                    _fail("duplicate_worker")
                self._future, self._executor = future, executor
                self._attachment = (future, executor)
                self._condition.notify_all()
        except BaseException:
            self._poison()
            raise

    def _original_offer(self):
        offer = self._offer
        if (type(offer) is not _BRSNativePreparationOffer or offer is not self._offer_scope
                or type(offer.thread) is not threading.Thread
                or type(offer.plan) is not NativeRSIExecutionPlan or type(offer.request) is not SolverRequest
                or type(offer.claim) is not NativeEpisodeClaim
                or type(offer.preparation) is not _NativeTrustedPythonProducerPreparation
                or type(offer.comparison_bytes) is not bytes
                or offer.request is not self._request or offer.plan.plan_sha256 != self._plan_sha256
                or type(self._future) is not Future or type(self._executor) is not ThreadPoolExecutor
                or self._executor._max_workers != 1 or offer.thread not in self._executor._threads
                or offer.thread is self._owner or not offer.thread.is_alive()
                or not self._future.running() or self._future.done()
                or _preparation_bytes(offer.preparation, offer.request, offer.plan, offer.claim)
                    != offer.comparison_bytes):
            _fail("offer_drift")
        return offer

    def offer_and_wait(self, preparation, request, plan, claim, *, check):
        try:
            self._fixed()
            if request is not self._request or threading.current_thread() is self._owner:
                _fail("worker_invalid")
            raw = _preparation_bytes(preparation, request, plan, claim)
            if plan.plan_sha256 != self._plan_sha256:
                _fail("association_invalid")
            self._check(check)
            offer = _BRSNativePreparationOffer(request, plan, claim, preparation, threading.current_thread(), raw)
            with self._condition:
                if self._state != "unused" or self._offer is not None:
                    _fail("duplicate_offer")
                self._offer, self._state = offer, "offered"
                self._offer_scope = offer
                self._condition.notify_all()
            while True:
                self._check(check)
                self._original_offer_if_attached(offer)
                with self._condition:
                    if self._state == "endpoint_bound":
                        endpoint = self._endpoint
                        if endpoint is not self._endpoint_scope:
                            _fail("endpoint_invalid")
                        self._state = "consumed"
                        self._condition.notify_all()
                        break
                    if self._state not in {"offered", "taken"}:
                        _fail("state_invalid")
                    self._condition.wait(.05)
            _BRSWorkerTerminalEndpoint._identity(endpoint)
            return endpoint
        except BaseException:
            self._poison()
            raise

    def _original_offer_if_attached(self, offer):
        with self._condition:
            attached = self._future is not None
        if attached and self._original_offer() is not offer:
            _fail("offer_drift")

    def take(self, *, check) -> _BRSNativePreparationOffer:
        try:
            while True:
                self._check(check, owner=True)
                with self._condition:
                    state, offer, future = self._state, self._offer, self._future
                if state == "offered":
                    self._original_offer()
                    with self._condition:
                        if self._failed or self._state != "offered" or self._offer is not offer:
                            _fail("state_invalid")
                        self._state = "taken"
                        return offer
                if state != "unused" or (future is not None and future.done()):
                    _fail("take_invalid")
                with self._condition:
                    self._condition.wait(.05)
        except BaseException:
            self._poison()
            raise

    def return_endpoint(self, offer, endpoint):
        try:
            self._fixed(owner=True)
            if time.monotonic() >= self._deadline:
                _fail("expired")
            original = self._original_offer()
            if offer is not original or type(endpoint) is not _BRSWorkerTerminalEndpoint:
                _fail("endpoint_invalid")
            if (endpoint._worker_thread != offer.thread.ident or endpoint._worker_object_id != id(offer.thread)
                    or endpoint._plan_sha256 != self._plan_sha256 or endpoint._status != "pending"
                    or type(endpoint._mailbox) is not BRSOwnerPublicationMailbox
                    or endpoint._mailbox._owner_thread != self._owner.ident
                    or endpoint._mailbox._worker_thread != offer.thread.ident
                    or type(endpoint._exchange) is not _PrimitiveExchange
                    or type(endpoint._handoff_bytes) is not bytes
                    or type(endpoint._scope) is not tuple or len(endpoint._scope) != 8
                    or endpoint._scope[0] is not endpoint._mailbox
                    or endpoint._scope[1] is not endpoint._exchange
                    or endpoint._scope[2] is not endpoint._handoff_bytes
                    or endpoint._scope[3:6] != (self._plan_sha256, offer.thread.ident, id(offer.thread))
                    or endpoint._scope[6] is not endpoint._admission_channel
                    or endpoint._scope[7] is not endpoint._admission_condition):
                _fail("endpoint_invalid")
            from .candidate_evaluation_spec import strict_json

            handoff = BRSSelectedChildHandoff(**strict_json(endpoint._handoff_bytes, maximum=128 * 1024))
            if ((handoff.run_id, handoff.episode_id, handoff.request_sha256, handoff.root_snapshot_sha256,
                 handoff.owner_thread_id) !=
                    (offer.plan.run_id, offer.request.episode_id, offer.plan.request_sha256,
                     offer.plan.memory_snapshot_sha256, self._owner.ident)
                    or endpoint._mailbox._identity != (handoff.run_id, handoff.episode_id, handoff.sha256)):
                _fail("endpoint_invalid")
            with self._condition:
                if self._failed or self._state != "taken" or self._endpoint is not None:
                    _fail("duplicate_endpoint")
                self._endpoint, self._state = endpoint, "endpoint_bound"
                self._endpoint_scope = endpoint
                self._condition.notify_all()
        except BaseException:
            self._poison()
            raise

    def fail(self):
        self._fixed(owner=True)
        self._poison()
