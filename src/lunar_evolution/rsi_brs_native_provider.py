"""Private preparation-only provider for an original reserved serial BRS child.

The ordinary gateway alone acquires the claim and publishes the mapped result.
This binding is transient, one-shot and available only on the original worker.
Its fixed completion callback reads the real owner publication; delivery values
never choose an outcome and no arbitrary publication callback is accepted.
"""

from __future__ import annotations

import inspect
import json
import math
import threading
import time

from .candidate_evaluation_spec import canonical_json
from .native_trusted_scheduler import _prepare_native_trusted_python_producer
from .rsi_brs_native_completion import (
    _BRSNativeCompletionPin,
    _observe,
    read_brs_live_published_completion,
    read_brs_live_published_provenance,
    read_brs_live_rejection_completion,
)
from .rsi_brs_preparation_exchange import _BRSNativePreparationExchange, _bytes
from .rsi_brs_serial_driver import (
    _BRSReservedChildScope,
    _BRSReservedSerialObservation,
    reserved_brs_staging_mode,
)
from .rsi_gateway import SolverRequest
from .rsi_learning import RSILearningError
from .rsi_native_gateway import NativeRSIExecutionConfig, NativeRSIReceiptBundle
from .rsi_native_inputs import NativeRSIInputDescriptor
from .rsi_native_plan import NativeRSIExecutionPlan
from .rsi_native_provenance import persist_native_rsi_provenance
from .rsi_native_rejection import NativeRSIRejectionEvidence
from .rsi_native_scheduler import (
    NativeRSISchedulerContext,
    NativeRSISchedulerProvider,
    _assert_plan_binding,
)
from .rsi_python_admission import validate_rsi_python_admission_shapes
from .rsi_python_brs_handoff import BRSSelectedChildHandoff
from .rsi_python_brs_publication_inputs import _request_from_native_preparation
from .rsi_python_brs_terminal_lifecycle import _BRSWorkerTerminalEndpoint
from .rsi_python_scheduler_inputs import _request_memory
from .rsi_store import NativeEpisodeClaim


def _fail(reason):
    raise RSILearningError("rsi_brs_native_provider_" + reason)


def _material(scope, handoff):
    if (type(scope) is not _BRSReservedChildScope or type(handoff) is not BRSSelectedChildHandoff
            or type(scope.observation) is not _BRSReservedSerialObservation
            or type(scope.request) is not SolverRequest
            or type(scope.preview_plan) is not NativeRSIExecutionPlan
            or type(scope.exchange) is not _BRSNativePreparationExchange
            or type(scope.owner_thread) is not int
            or type(scope.deadline) not in (int, float)
            or not math.isfinite(scope.deadline) or scope.deadline <= 0):
        _fail("scope_invalid")
    request, memory = _request_memory(scope.request, scope.memory)
    validate_rsi_python_admission_shapes(handoff, dto_types=(BRSSelectedChildHandoff,))
    selected = BRSSelectedChildHandoff(**BRSSelectedChildHandoff.to_dict(handoff))
    plan_bytes = _bytes(scope.preview_plan)
    plan = NativeRSIExecutionPlan.from_dict(NativeRSIExecutionPlan.to_dict(scope.preview_plan))
    if (selected.run_id != plan.run_id or selected.episode_id != request.episode_id
            or selected.request_sha256 != request.digest()
            or selected.root_snapshot_sha256 != memory.digest()
            or selected.max_workers != 1 or plan.request != request):
        _fail("scope_binding_invalid")
    return (_bytes(request), memory.to_bytes(), plan_bytes,
            canonical_json(BRSSelectedChildHandoff.to_dict(selected)))


class _BRSNativeProviderBinding:
    """An original owner-created binding, never reconstructible from saved evidence."""

    __slots__ = (
        "_child",
        "_claim",
        "_completion",
        "_config",
        "_context",
        "_controller",
        "_endpoint",
        "_handoff",
        "_inputs",
        "_material",
        "_original",
        "_pin",
        "_plan",
        "_provenance",
        "_provider",
        "_state",
        "_wave",
        "_worker",
    )

    def __init__(self, provider, controller, wave, scope, handoff, inputs, config, material):
        self._provider, self._controller, self._wave = provider, controller, wave
        self._child, self._handoff, self._context = scope, handoff, provider.context
        self._original = (provider, controller, wave, scope, handoff, provider.context)
        self._inputs, self._config, self._material = inputs, config, material
        self._state = "bound"
        self._worker = self._claim = self._plan = self._endpoint = None
        self._completion = self._pin = self._provenance = None

    def _fixed(self, request, plan):
        from .rsi_controller import RSILearningController, _PythonAdmissionBRSWave
        from .rsi_producer_gateway import PythonProducerRSISolverGateway

        if (type(self) is not _BRSNativeProviderBinding or type(self._original) is not tuple
                or len(self._original) != 6
                or any(left is not right for left, right in zip(self._original, (
                    self._provider, self._controller, self._wave, self._child,
                    self._handoff, self._context), strict=True))
                or type(self._provider) is not NativeRSISchedulerProvider
                or type(self._controller) is not RSILearningController
                or type(self._wave) is not _PythonAdmissionBRSWave
                or type(self._child) is not _BRSReservedChildScope
                or type(self._inputs) is not NativeRSIInputDescriptor
                or type(self._config) is not bytes or type(self._material) is not tuple
                or len(self._material) != 4 or any(type(value) is not bytes for value in self._material)
                or self._claim is not None and type(self._claim) is not NativeEpisodeClaim
                or self._worker is not None and type(self._worker) is not threading.Thread
                or self._plan is not None and self._plan is not plan
                or self._pin is not None and type(self._pin) is not _BRSNativeCompletionPin
                or self._completion is not None and type(self._completion) not in (
                    NativeRSIReceiptBundle, NativeRSIRejectionEvidence)
                or self._provenance is not None and (type(self._provenance) is not str
                    or len(self._provenance) != 64
                    or any(char not in "0123456789abcdef" for char in self._provenance))
                or type(self._context) is not NativeRSISchedulerContext
                or type(self._handoff) is not BRSSelectedChildHandoff
                or type(request) is not SolverRequest or request is not self._child.request
                or type(plan) is not NativeRSIExecutionPlan
                or self._provider._brs_native_binding is not self
                or self._provider.context is not self._context
                or self._provider._python_admission_controller is not self._controller
                or self._wave.reserved_scope is not self._child
                or self._wave.selected_handoff is not self._handoff
                or self._wave.controller is not self._controller
                or self._controller.ledger is not self._context.failure_ledger
                or self._wave.ledger is not self._controller.ledger
                or type(self._child.gateway) is not PythonProducerRSISolverGateway
                or type(self._child.gateway.config) is not NativeRSIExecutionConfig
                or self._child.gateway.config.receipt_provider is not self._provider
                or self._child.gateway.ledger is not self._controller.ledger
                or self._child.owner_thread != self._wave.owner_thread
                or not reserved_brs_staging_mode(self._wave.state)
                or self._controller.producer_known_rejection is not True
                or self._controller.producer_multi_episode_publication is not True
                or self._controller.producer_child_execution is not True
                or not any(value is not None for value in
                           NativeRSISchedulerContext._python_handoff_suppliers(self._context))
                or type(self._state) is not str or self._state == "unknown"):
            _fail("binding_invalid")
        if (_material(self._child, self._handoff) != self._material or _bytes(plan) != self._material[2]
                or self._child.exchange._request is not request
                or self._child.exchange._deadline != self._child.deadline
                or self._child.exchange._plan_sha256 != plan.plan_sha256):
            _fail("original_scope_drift")
        NativeRSISchedulerContext._assert_live_modules_sink(self._context)
        _BRSNativePreparationExchange._fixed(self._child.exchange)
        if self._endpoint is not None:
            if (type(self._endpoint) is not _BRSWorkerTerminalEndpoint
                    or self._endpoint._reserved_success is not True):
                _fail("original_endpoint_required")
            _BRSWorkerTerminalEndpoint._identity(self._endpoint)

    def _check(self, request, plan, *, before_claim=False, owner=False, hot=False):
        if type(hot) is not bool:
            _fail("check_invalid")
        _BRSNativeProviderBinding._fixed(self, request, plan)
        controller, wave, context = self._controller, self._wave, self._context
        if owner:
            if threading.get_ident() != self._child.owner_thread or self._state != "bound":
                _fail("original_owner_required")
            controller._python_admission_active_brs_owner(wave)
        else:
            if (threading.get_ident() == self._child.owner_thread
                    or self._worker is not None and threading.current_thread() is not self._worker):
                _fail("original_worker_required")
            if (hot and hasattr(controller, "_python_admission_active_brs_worker_hot")
                    and hasattr(controller, "_python_admission_brs_observation_lock")):
                controller._python_admission_active_brs_worker_hot(plan.run_id, request.episode_id)
            else:
                controller._python_admission_active_brs_worker(plan.run_id, request.episode_id)
        if not hot:
            # The selected handoff was fully fingerprinted at bind/claim.  Keep
            # ordinary preparation polls on the captured head/identity pins;
            # repeat the cold source gate only at a fresh claim or terminal
            # reobservation boundary where drift can change authority.
            terminal_gate = self._state in {"callback_returned", "returned"}
            if before_claim or terminal_gate:
                controller._python_admission_assert_selected_brs(wave, self._handoff)
            else:
                controller._python_admission_assert_selected_brs_cached(wave, self._handoff)
        if not owner and not hot:
            controller._python_admission_bridge_wait_check()
        if context.cancelled is not None and bool(context.cancelled()):
            _fail("cancelled")
        if context.execution_control is not None:
            context.execution_control.check("rsi_brs_native_provider")
        if time.monotonic() >= self._child.deadline:
            _fail("deadline_expired")
        if hot:
            # Waiting on the in-memory preparation exchange must not rescan the
            # staged runtime tree or recalculate the provider fingerprint. The
            # complete input/claim gate still runs immediately before offer,
            # endpoint transitions, callback delivery and reobservation. Keep
            # only identity, active-scope, cancellation and deadline checks so
            # stale waiters terminate promptly.
            _BRSNativePreparationExchange._fixed(self._child.exchange)
            return self._claim
        _BRSNativeProviderBinding._fixed(self, request, plan)
        inputs = NativeRSISchedulerProvider._inputs(self._provider, require_unexpired=False)
        live_config = canonical_json(NativeRSISchedulerProvider.rsi_fingerprint_config(self._provider))
        if inputs != self._inputs or live_config != self._config:
            _fail("input_drift")
        _assert_plan_binding(request, self._child.memory, plan, context, inputs)
        NativeRSISchedulerProvider.assert_rejection_ledger(self._provider, controller.ledger)
        with controller.ledger.read_only_observations():
            claim = controller.ledger.inspect_native_episode_claim(request, plan_sha256=plan.plan_sha256)
        if before_claim and not hot:
            if self._state != "bound" or claim is not None:
                _fail("fresh_claim_required")
        else:
            claim = NativeRSISchedulerProvider._failure_claim(
                self._provider, request, plan, live=True, expected=self._claim,
            )
        _BRSNativeProviderBinding._fixed(self, request, plan)
        return claim

    def _complete(self, _delivery):
        request, plan = self._child.request, self._plan
        if self._state != "running" or self._completion is not None:
            _fail("duplicate_callback")
        self._state = "callback"
        _BRSNativeProviderBinding._check(self, request, plan)
        journal = _observe(self._provider, request, plan)[4]
        if journal.state == "published":
            original = read_brs_live_published_completion(self._provider, request, plan)
            self._pin = original.pin
            self._provenance = persist_native_rsi_provenance(
                self._provider.provenance_batch, json.loads(original.provenance_bytes),
            )
            self._completion = read_brs_live_published_provenance(
                self._provider, request, plan, expected_pin=self._pin,
                expected_provenance_sha256=self._provenance,
            )
        elif journal.state == "all_rejected":
            self._completion, self._pin = read_brs_live_rejection_completion(self._provider, request, plan)
        else:
            _fail("known_terminal_required")
        _BRSNativeProviderBinding._check(self, request, plan)
        self._state = "callback_returned"
        return self._completion

    def _reobserve(self, request, plan):
        # The response path already ran the complete gate immediately after
        # mailbox delivery.  Keep this pre-read check to the captured identity
        # and live control pins; the final check below is the authoritative
        # terminal/source reobservation and must remain strict.  Avoiding a
        # duplicate runtime-manifest walk here keeps the owner free to join the
        # worker promptly after it has consumed the response.
        _BRSNativeProviderBinding._check(self, request, plan, hot=True)
        if self._state not in {"callback_returned", "returned"} or self._completion is None or self._pin is None:
            _fail("original_completion_required")
        if self._provenance is not None:
            value = read_brs_live_published_provenance(
                self._provider, request, plan, expected_pin=self._pin,
                expected_provenance_sha256=self._provenance,
            )
            if value != self._completion:
                _fail("completion_drift")
        else:
            value, pin = read_brs_live_rejection_completion(
                self._provider, request, plan, expected_pin=self._pin,
            )
            if (pin != self._pin or value.to_dict() != self._completion.to_dict()
                    or value.provenance_sha256 != self._completion.provenance_sha256
                    or value.provenance_file_pin != self._completion.provenance_file_pin):
                _fail("completion_drift")
        _BRSNativeProviderBinding._check(self, request, plan)
        return value

    def _run(self, request, plan):
        # Retain the original wakeup primitives before any external control or
        # preparation callback. A replaced child must not intercept cleanup.
        original = self._original
        exchange = (original[3].exchange if type(original) is tuple and len(original) == 6
                    and type(original[3]) is _BRSReservedChildScope else None)
        condition = (exchange._condition if type(exchange) is _BRSNativePreparationExchange
                     and type(exchange._scope) is tuple and len(exchange._scope) == 6
                     and type(exchange._condition) is threading.Condition
                     and exchange._scope[0] is exchange._condition else None)
        try:
            claim = _BRSNativeProviderBinding._check(self, request, plan)
            if self._state != "bound" or self._worker is not None:
                _fail("duplicate_dispatch")
            self._worker, self._claim, self._plan = threading.current_thread(), claim, plan
            self._state = "running"  # Consume before the only producer effect.
            context = self._context

            def check(_stage=None):
                _BRSNativeProviderBinding._check(self, request, plan)

            def hot_check(_stage=None):
                _BRSNativeProviderBinding._check(self, request, plan, hot=True)

            check()
            def prepublication_check(stage=None):
                # The entry callback runs after the binding's strict gate and
                # before any producer side effect.  It only needs the captured
                # handoff identity while the preparation path is in flight.  The
                # final prepublication callback is an explicit side-effect
                # boundary and must run the complete source/staging gate again.
                if stage == "native_producer_prepublication_return":
                    check()
                else:
                    hot_check()

            preparation = _prepare_native_trusted_python_producer(
                context.workspace, producer_root=context.producer_root, intent=context.intent,
                attestation=context.attestation, artifact=context.artifact, broker_config=context.broker_config,
                contract=context.contract, groups=context.groups, evaluator_kind=context.evaluator_kind,
                evaluator_fingerprint=context.evaluator_fingerprint, runner_fingerprint=context.runner_fingerprint,
                dependency_sha256=context.dependency_sha256, environment_sha256=context.environment_sha256,
                python_handoff_after_execution=context.python_handoff_after_execution,
                **({"python_handoff_after_native_execution": context.python_handoff_after_native_execution}
                   if getattr(context, "python_handoff_after_native_execution", None) is not None else {}),
                evidence_revalidator=prepublication_check, execution_control=context.execution_control,
                cancelled=context.cancelled, parent_deadline=self._child.deadline,
                **({"live_modules_sink": NativeRSISchedulerContext._assert_live_modules_sink(context)}
                   if context.live_modules_sink is not None else {}),
            )
            check()
            endpoint = _BRSNativePreparationExchange.offer_and_wait(
                self._child.exchange, preparation, request, plan, claim, check=check,
                hot_check=hot_check,
            )
            if type(endpoint) is not _BRSWorkerTerminalEndpoint or endpoint._reserved_success is not True:
                _fail("original_endpoint_required")
            self._endpoint = endpoint
            check()
            message = _request_from_native_preparation(preparation, self._handoff, native_plan=plan,
                expected_head_sha256=self._handoff.head_sha256,
                expected_state_sha256=self._handoff.state_sha256)
            receive = endpoint.receive_and_settle
            receive_kwargs = {
                "callback": lambda delivery: _BRSNativeProviderBinding._complete(self, delivery),
                "check": check,
            }
            # Keep compatibility with the inert provider fixtures that replace
            # this private method with the pre-hot-check four-argument seam.
            # The production endpoint exposes the optional wait_check keyword.
            if "wait_check" in inspect.signature(receive).parameters:
                receive_kwargs["wait_check"] = hot_check
            result = receive(message, **receive_kwargs)
            if (self._endpoint is not endpoint or self._state != "callback_returned"
                    or result is not self._completion or endpoint.status != "settled"):
                _fail("original_return_required")
            repeated = _BRSNativeProviderBinding._reobserve(self, request, plan)
            self._state = "returned"
            return repeated
        except BaseException:
            self._state = "unknown"
            if condition is not None:
                # The original worker may poison+wake its original exchange. It
                # cannot borrow the owner-only fail/attach/take capabilities.
                with condition:
                    exchange._failed = True
                    threading.Condition.notify_all(condition)
            raise


def bind_brs_native_provider(provider, *, controller, wave, scope, handoff):
    """Bind only the exact original owner-selected child before any claim exists."""
    from .rsi_controller import RSILearningController, _PythonAdmissionBRSWave
    from .rsi_producer_gateway import PythonProducerRSISolverGateway

    if (type(provider) is not NativeRSISchedulerProvider
            or type(controller) is not RSILearningController
            or type(wave) is not _PythonAdmissionBRSWave or type(scope) is not _BRSReservedChildScope
            or type(handoff) is not BRSSelectedChildHandoff
            or type(scope.gateway) is not PythonProducerRSISolverGateway
            or type(scope.gateway.config) is not NativeRSIExecutionConfig
            or type(scope.owner_thread) is not int
            or type(provider.context) is not NativeRSISchedulerContext
            or provider._brs_native_binding is not None
            or provider._python_admission_controller is not controller
            or wave.reserved_scope is not scope or wave.selected_handoff is not handoff
            or wave.controller is not controller or wave.ledger is not controller.ledger
            or provider.context.failure_ledger is not controller.ledger
            or scope.gateway.config.receipt_provider is not provider
            or scope.gateway.ledger is not controller.ledger
            or scope.owner_thread != wave.owner_thread
            or controller.producer_known_rejection is not True
            or controller.producer_multi_episode_publication is not True
            or controller.producer_child_execution is not True
            or not reserved_brs_staging_mode(wave.state)
            or threading.get_ident() != scope.owner_thread):
        _fail("binding_invalid")
    material = _material(scope, handoff)
    controller._python_admission_active_brs_owner(wave)
    controller._python_admission_assert_selected_brs(wave, handoff)
    provider.validate_preclaim(scope.request, scope.preview_plan, claim_ledger=controller.ledger)
    inputs = NativeRSISchedulerProvider._inputs(provider, require_unexpired=True)
    config = canonical_json(NativeRSISchedulerProvider.rsi_fingerprint_config(provider))
    binding = _BRSNativeProviderBinding(provider, controller, wave, scope, handoff, inputs, config, material)
    provider._brs_native_binding = binding
    try:
        _BRSNativeProviderBinding._check(binding, scope.request, scope.preview_plan, before_claim=True, owner=True)
    except BaseException:
        binding._state = "unknown"
        _BRSNativePreparationExchange.fail(scope.exchange)
        raise
    return binding


def assert_brs_native_provider_binding(provider, request, plan, *, before_claim=False):
    """Return None only for an unbound provider; never fall back after binding."""
    if type(provider) is not NativeRSISchedulerProvider or type(before_claim) is not bool:
        _fail("binding_invalid")
    binding = provider._brs_native_binding
    if binding is None:
        return None
    if type(binding) is not _BRSNativeProviderBinding or binding._provider is not provider:
        _fail("binding_invalid")
    _BRSNativeProviderBinding._check(binding, request, plan, before_claim=before_claim)
    return binding


def recover_brs_native_rejection(provider, request, plan):
    """Repeat the original BRS proof without borrowing a DRS live owner."""
    binding = assert_brs_native_provider_binding(provider, request, plan)
    if (binding is None or binding._state != "returned" or binding._provenance is not None
            or provider._live_rejection is not None):
        _fail("original_rejection_required")
    return _BRSNativeProviderBinding._reobserve(binding, request, plan)


def run_brs_native_provider(provider, request, plan):
    """Enter once; any original dispatch refusal poisons its retained binding."""
    if type(provider) is not NativeRSISchedulerProvider:
        _fail("binding_invalid")
    binding = provider._brs_native_binding
    if type(binding) is not _BRSNativeProviderBinding or binding._provider is not provider:
        _fail("binding_invalid")
    return _BRSNativeProviderBinding._run(binding, request, plan)
