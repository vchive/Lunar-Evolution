"""Private retained-context reader for an already registered BRS owner.

This is read-only evidence comparison, not a publication capability. The caller's
original preparation is never a source of owner authority or candidate drafts.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import fields
from pathlib import Path
from threading import Condition, RLock

from .algorithm import (
    AlgorithmProblemContract,
    ConstraintSpec,
    EvolutionSpec,
    InputSpec,
    MetricSpec,
    ObjectiveSpec,
    OutputSpec,
    SourceCheckSpec,
)
from .automatic_solve_lifecycle import (
    SolveExecutionBudgetExceeded,
    SolveExecutionCancelled,
    SolveExecutionControl,
)
from .candidate_bundle import CandidateSourceBundle, CandidateSourceFile
from .evolution import CandidateDraft
from .native_bootstrap import NativeBootstrapArtifact
from .native_trusted_output import NativeTrustedOutputPreparation
from .native_trusted_scheduler import (
    NativeTrustedProducerRecovery,
    NativeTrustedProducerRun,
    _NativeTrustedPythonProducerPreparation,
    _prepublication_control_pin,
    recover_native_trusted_producer,
)
from .producer_bootstrap import TrustedBootstrapDescriptor
from .producer_bundle_admission import ProducerBundleAdmissionItem, ProducerBundleAdmissionPlan
from .producer_bundle_handoff import BundleGroup, VerifiedProducerBundle
from .producer_bundle_population import ProducerBundleDraft
from .producer_handoff import ProducerMaterial, ProducerResultEnvelope
from .producer_launcher import ProducerLaunchAttestation, ProducerLaunchIntent
from .producer_process import (
    ProducerEnvelopeEvidence,
    ProducerExecutionReceipt,
    ProducerStreamEvidence,
)
from .python_producer_admission_handoff import (
    PythonProducerAdmissionHandoff,
    PythonProducerAdmissionHandoffFilePin,
    PythonProducerAdmissionHandoffSidecar,
    read_python_producer_admission_handoff_pinned,
)
from .rsi_brs_publication_lineage import _BRSLineageCheckpointOwner
from .rsi_gateway import SolverRequest
from .rsi_learning import RSILearningError
from .rsi_native_plan import NativeRSIExecutionPlan
from .rsi_python_brs_admission import BRSAdmissionChannel
from .rsi_python_brs_handoff import BRSSelectedChildHandoff
from .rsi_python_brs_publication_inputs import _request_from_native_preparation
from .rsi_python_brs_publication_mailbox import BRSOwnerPublicationRequest, _request
from .rsi_python_scheduler_inputs import _context

_DTOS = (
    AlgorithmProblemContract, ConstraintSpec, EvolutionSpec, InputSpec, MetricSpec,
    ObjectiveSpec, OutputSpec, SourceCheckSpec, CandidateSourceBundle, CandidateSourceFile,
    CandidateDraft, NativeBootstrapArtifact, TrustedBootstrapDescriptor, BundleGroup,
    ProducerLaunchIntent, ProducerLaunchAttestation, ProducerBundleAdmissionItem,
    ProducerBundleAdmissionPlan, ProducerBundleDraft, VerifiedProducerBundle, ProducerMaterial,
    ProducerResultEnvelope, ProducerEnvelopeEvidence, ProducerExecutionReceipt,
    ProducerStreamEvidence, PythonProducerAdmissionHandoff, PythonProducerAdmissionHandoffFilePin,
    PythonProducerAdmissionHandoffSidecar, NativeRSIExecutionPlan, SolverRequest,
    BRSSelectedChildHandoff, NativeTrustedOutputPreparation, NativeTrustedProducerRecovery,
)
_ORIGINAL_DTOS = _DTOS
_CONTROL_LOCK_TYPE = type(RLock())


def _fail(reason: str) -> None:
    raise RSILearningError("rsi_python_brs_publication_recovery_" + reason)


def _dto_policy() -> list[str]:
    if _DTOS is not _ORIGINAL_DTOS:
        _fail("dto_types_drift")
    return [kind.__module__ + "." + kind.__qualname__ for kind in _ORIGINAL_DTOS]


def _control_pin(control: SolveExecutionControl | None) -> tuple | None:
    if control is None:
        return None
    if type(control) is not SolveExecutionControl:
        _fail("control_invalid")
    values = object.__getattribute__(control, "__dict__")
    expected = {"timeout_seconds", "_clock", "started_at", "deadline", "_cancellation_callbacks",
                "_cancelled", "_observe_stage", "_lock"}
    if (type(values) is not dict or any(type(key) is not str for key in values)
            or set(values) != expected or type(control._cancelled) is not bool
            or type(control._lock) is not _CONTROL_LOCK_TYPE
            or type(control._cancellation_callbacks) is not list or not callable(control._clock)
            or (control._observe_stage is not None and not callable(control._observe_stage))
            or any(not callable(item) for item in control._cancellation_callbacks)):
        _fail("control_invalid")
    return _prepublication_control_pin(control)


def _copy(value: object, *, depth: int = 0, remaining: list[int] | None = None):
    """Copy only closed primitive/DTO shapes, without invoking caller serializers."""
    if remaining is None:
        remaining = [100_000, 64 * 1024 * 1024]
    remaining[0] -= 1
    if depth > 48 or remaining[0] < 0:
        _fail("shape_invalid")
    kind = type(value)
    if _DTOS is not _ORIGINAL_DTOS:
        _fail("dto_types_drift")
    if value is None or any(kind is scalar for scalar in (bool, int, str, bytes, float)):
        if kind is str or kind is bytes:
            remaining[1] -= len(value)
            if len(value) > 8 * 1024 * 1024 or remaining[1] < 0:
                _fail("shape_invalid")
        if kind is int and value.bit_length() > 4096:
            _fail("shape_invalid")
        if kind is float and not math.isfinite(value):
            _fail("shape_invalid")
        return value
    if kind is type(Path()):
        return Path(str(value))
    if kind is dict:
        if len(value) > 100_000 or any(type(key) is not str for key in value):
            _fail("shape_invalid")
        return {_copy(key, depth=depth + 1, remaining=remaining):
                _copy(item, depth=depth + 1, remaining=remaining) for key, item in value.items()}
    if kind is tuple or kind is list:
        if len(value) > 100_000:
            _fail("shape_invalid")
        return kind(_copy(item, depth=depth + 1, remaining=remaining) for item in value)
    if not any(kind is allowed for allowed in _ORIGINAL_DTOS):
        _fail("shape_invalid")
    declared = fields(kind)
    if any(not item.init for item in declared):
        _fail("shape_invalid")
    try:
        attributes = object.__getattribute__(value, "__dict__")
    except AttributeError:
        pass
    else:
        if (type(attributes) is not dict or any(type(key) is not str for key in attributes)
                or set(attributes) != {item.name for item in declared}):
            _fail("shape_invalid")
    return kind(**{item.name: _copy(object.__getattribute__(value, item.name), depth=depth + 1,
                                  remaining=remaining) for item in declared})


def _comparison_preparation(value: object) -> _NativeTrustedPythonProducerPreparation:
    """Ignore attempt, bundles and drafts supplied by the worker altogether."""
    if (type(value) is not _NativeTrustedPythonProducerPreparation
            or type(value.run) is not NativeTrustedProducerRun
            or type(value.run.output) is not NativeTrustedOutputPreparation):
        _fail("preparation_invalid")
    output = value.run.output
    consumed = {item.name: getattr(output, item.name) for item in fields(NativeTrustedOutputPreparation)
                if item.name not in {"bundles", "drafts"}}
    return _NativeTrustedPythonProducerPreparation(
        NativeTrustedProducerRun(None, _copy(value.run.receipt),
            NativeTrustedOutputPreparation(**_copy(consumed), bundles=(), drafts=()),
            publication=_copy(value.run.publication), status=_copy(value.run.status),
            deadline_scope=_copy(value.run.deadline_scope)),
        _copy(value.handoff),
    )


def _arguments(owner: _BRSLineageCheckpointOwner) -> dict:
    native, sidecar = _context(owner._native_inputs)
    if (sidecar != owner._sidecar or owner._native is None
            or owner._native_inputs.native_context is not owner._native):
        _fail("context_drift")
    return _copy({name: getattr(native, name) for name in (
        "workspace", "intent", "attestation", "artifact", "contract", "groups", "evaluator_kind",
        "evaluator_fingerprint", "runner_fingerprint", "dependency_sha256", "environment_sha256",
    )})


class _BRSRetainedNativePreparationReader:
    """One-shot read under the genuine original owner's unchanged new/before scope."""

    __slots__ = (
        "_arguments",
        "_cancelled",
        "_channel",
        "_condition",
        "_control",
        "_control_pin",
        "_handoff",
        "_head",
        "_original",
        "_owner",
        "_payload",
        "_phase",
        "_plan",
        "_request",
        "_request_reader",
        "_used",
    )

    def __init__(self, owner: _BRSLineageCheckpointOwner, *,
                 original_preparation: _NativeTrustedPythonProducerPreparation) -> None:
        if type(self) is not _BRSRetainedNativePreparationReader or type(owner) is not _BRSLineageCheckpointOwner:
            _fail("owner_invalid")
        self._owner, self._used = owner, False
        try:
            owner._check_owner()
            if owner._phase not in {"new", "before"} or owner._native is None:
                _fail("owner_phase_invalid")
            self._phase, self._head, self._payload = owner._phase, owner._head, owner._payload
            self._channel, self._condition = owner._channel, owner._channel._condition
            self._control, self._cancelled = owner._native.execution_control, owner._native.cancelled
            if self._control is not None and type(self._control) is not SolveExecutionControl:
                _fail("control_invalid")
            self._control_pin = _control_pin(self._control)
            self._arguments = _arguments(owner)
            self._plan, self._handoff = _copy(owner._plan), _copy(owner._handoff)
            self._original = _comparison_preparation(original_preparation)
            self._request_reader = _request
            self._request = self._project(self._original)
            self._check()
        except (SolveExecutionCancelled, SolveExecutionBudgetExceeded):
            raise
        except (ValueError, TypeError, AttributeError, OverflowError, RecursionError) as exc:
            raise RSILearningError("rsi_python_brs_publication_recovery_evidence_invalid") from exc

    def _scope(self, *, callbacks: bool = True) -> None:
        owner = self._owner
        if callbacks:
            owner._check_owner()
        else:
            # These original identity/ledger observers do not invoke gateway,
            # source, configuration or native execution-control callbacks.
            owner._identity()
            with owner._ledger.read_only_observations():
                owner._running()
                owner._controller._python_admission_active_brs_owner(owner._wave)
                owner._history()
        if (owner._phase != self._phase or owner._head != self._head or owner._payload != self._payload
                or _arguments(owner) != self._arguments or _copy(owner._plan) != self._plan
                or _copy(owner._handoff) != self._handoff
                or owner._native.execution_control is not self._control
                or owner._native.cancelled is not self._cancelled
                or _control_pin(self._control) != self._control_pin):
            _fail("owner_context_drift")
        if (type(owner._channel) is not BRSAdmissionChannel or owner._channel is not self._channel
                or type(self._condition) is not Condition or self._channel._condition is not self._condition):
            _fail("channel_drift")
        with self._condition:
            if (self._channel._closed is not False
                    or self._channel._handoff_mode is not True
                    or type(self._channel._selected_episode_id) is not str
                    or type(self._channel._selected_handoff_sha256) is not str
                    or self._channel._selected_episode_id != self._handoff.episode_id
                    or self._channel._selected_handoff_sha256 != self._handoff.sha256
                    or type(self._channel._consumed_handoff_nonces) is not set
                    or any(type(item) is not str for item in self._channel._consumed_handoff_nonces)
                    or self._channel._consumed_handoff_nonces != {self._handoff.lease_nonce}
                    or type(self._channel._completed_selected_episodes) is not set
                    or len(self._channel._completed_selected_episodes) != 0
                    or type(self._channel._requests) is not dict or len(self._channel._requests) != 0
                    or self._channel._servicing is not False
                    or type(self._channel._queue) is not deque or len(self._channel._queue) != 0):
                _fail("channel_closed_or_drifted")

    def _check(self) -> None:
        self._scope()
        try:
            if self._cancelled is not None:
                cancelled = self._cancelled()
                if type(cancelled) is not bool:
                    _fail("cancellation_invalid")
                if cancelled:
                    raise SolveExecutionCancelled("brs_native_preparation_read")
            if self._control is not None:
                SolveExecutionControl.check(self._control, "brs_native_preparation_read")
        except (SolveExecutionCancelled, SolveExecutionBudgetExceeded, RSILearningError):
            raise
        except Exception as exc:
            raise RSILearningError("rsi_python_brs_publication_recovery_control_unknown") from exc
        # Native cancellation/stage/clock callbacks run outside observation and
        # channel locks. Their return cannot refresh any captured owner context.
        self._scope(callbacks=False)

    def _project(self, value: _NativeTrustedPythonProducerPreparation) -> BRSOwnerPublicationRequest:
        return _request_from_native_preparation(
            value, self._handoff, native_plan=self._plan,
            expected_head_sha256=self._handoff.head_sha256,
            expected_state_sha256=self._handoff.state_sha256,
        )

    def recover(self, worker_request: BRSOwnerPublicationRequest) -> NativeTrustedProducerRecovery:
        """Reread original evidence; never adopt new pins, heads or execution authority."""
        if type(self) is not _BRSRetainedNativePreparationReader or self._used:
            _fail("reader_consumed")
        self._used = True
        try:
            if _request is not self._request_reader:
                _fail("request_reader_drift")
            supplied = _request(worker_request)
            if supplied != self._request:
                _fail("request_mismatch")
            self._check()
            pin = self._original.handoff.file_pin
            batch = self._arguments["workspace"] / "evolution/producer-batches" / self._plan.journal_id
            handoff = read_python_producer_admission_handoff_pinned(batch, expected_file_pin=pin)
            if handoff != self._original.handoff:
                _fail("handoff_drift")
            recovered = _copy(recover_native_trusted_producer(**self._arguments, require_broker=True))
            if type(recovered) is not NativeTrustedProducerRecovery or recovered.status != "recovered":
                _fail("recovered_state_invalid")
            if recovered.receipt != self._original.run.receipt:
                _fail("receipt_drift")
            prepared = _NativeTrustedPythonProducerPreparation(
                NativeTrustedProducerRun(None, recovered.receipt, recovered.output), handoff,
            )
            if self._project(prepared) != self._request:
                _fail("output_drift")
            repeated = read_python_producer_admission_handoff_pinned(batch, expected_file_pin=pin)
            if repeated != handoff:
                _fail("handoff_drift")
            self._check()
            return recovered
        except (SolveExecutionCancelled, SolveExecutionBudgetExceeded):
            raise
        except (ValueError, TypeError, AttributeError, OSError, OverflowError, RecursionError) as exc:
            raise RSILearningError("rsi_python_brs_publication_recovery_read_invalid") from exc
