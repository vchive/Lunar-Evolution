"""Private first-ordinal native publication under the genuine original BRS owner.

This entry is not scheduler routing, a worker mutation facade or result settlement.
It reuses the native transaction kernel and the owner's existing registered scope;
no permit, second registry, replay or reconstructed authority is introduced.
"""

from __future__ import annotations

import json
import time
from threading import get_ident
from typing import Any

from . import _benchmark_files as _files
from .automatic_solve_lifecycle import SolveExecutionControl
from .native_trusted_scheduler import _NativeTrustedPythonProducerPreparation
from .producer_bundle_lineage import capture_lineage_snapshot_pin, verify_persisted_lineage_snapshot
from .producer_bundle_transaction import NativeProducerBundleTransactionResult
from .producer_process import parse_producer_execution_receipt
from .rsi_brs_publication_lineage import _BRSLineageCheckpointOwner
from .rsi_learning import RSILearningError
from .rsi_native_scheduler import NativeRSISchedulerContext
from .rsi_python_brs_publication_mailbox import BRSOwnerPublicationRequest


def _fail(reason: str) -> None:
    raise RSILearningError("rsi_python_brs_native_dispatch_" + reason)


def _original_control(owner: object) -> _BRSLineageCheckpointOwner:
    """Reject foreign owners and arbitrary clocks before any caller observation."""
    if type(owner) is not _BRSLineageCheckpointOwner:
        _fail("owner_invalid")
    # Genuine owners have slots. If a later exact-class implementation exposes
    # a dictionary, it still cannot shadow the original unbound methods.
    try:
        attributes = object.__getattribute__(owner, "__dict__")
    except AttributeError:
        attributes = None
    if attributes:
        _fail("owner_shadow_invalid")
    native = owner._native
    if type(native) is not NativeRSISchedulerContext:
        _fail("native_context_invalid")
    control = native.execution_control
    if (type(control) is not SolveExecutionControl or control is not owner._before_control
            or control._clock is not time.monotonic):
        _fail("monotonic_control_required")
    if _BRSLineageCheckpointOwner._before_control_state(owner) != owner._before_control_pin:
        _fail("control_drift")
    return owner


def _fixed_original_brs_owner(owner: object) -> None:
    owner = _original_control(owner)
    _BRSLineageCheckpointOwner._success_fixed(owner)
    _original_control(owner)


def _original_brs_numeric_tail(owner: object) -> None:
    """Only local original scope/channel checks after the retained numeric gate."""
    owner = _original_control(owner)
    controller, wave = owner._controller, owner._wave
    if (owner._poisoned or get_ident() != owner._thread
            or getattr(controller._python_admission_brs_local, "lineage_checkpoint_owner", None) is not owner
            or not wave.active or wave.owner_thread != owner._thread
            or controller._python_admission_brs_wave is not wave
            or controller.ledger is not owner._ledger or wave.ledger is not owner._ledger
            or not owner._ledger.controller_lock_held(owner._run_id)
            or wave.state is not owner._state or wave.checkpoint_sha256 != owner._head
            or wave.payload != owner._payload or wave.channel is not owner._channel
            or wave.selected_handoff is not owner._handoff or wave.selected_context is not owner._selected_context
            or wave.selected_worker_started is not True or wave.selected_return is not None
            or wave.selected_settlement_started is not False):
        _fail("owner_scope_drift")
    _BRSLineageCheckpointOwner._before_channel(owner)


def _call_original_brs_owner(owner: object, method: str, *args: object, **kwargs: object) -> Any:
    """Finite exact unbound dispatch; instance hooks and rejection are not grants."""
    _fixed_original_brs_owner(owner)
    if method not in {"validate_before", "retain_before", "retain_staged", "verify_precommit", "retain_terminal"}:
        _fail("method_invalid")
    if method == "retain_terminal" and (len(args) != 2 or args[1] is None):
        _fail("all_rejected_unsupported")
    return getattr(_BRSLineageCheckpointOwner, method)(owner, *args, **kwargs)


def _run_original_brs_native_publication(
    owner: object, worker_request: BRSOwnerPublicationRequest, *,
    original_preparation: _NativeTrustedPythonProducerPreparation,
) -> NativeProducerBundleTransactionResult:
    """Run one native success while the original selected worker remains waiting."""
    from . import rsi_python_brs_publication_recovery as reader_module
    from .native_trusted_scheduler import recover_native_trusted_producer
    from .producer_bundle_transaction import (
        _admission_attempt_anchor,
        _run_bound_native_producer_bundle_publication_transaction,
    )
    from .python_producer_admission_handoff import read_python_producer_admission_handoff_pinned
    from .rsi_controller import RSILearningController

    owner = _original_control(owner)
    try:
        _BRSLineageCheckpointOwner._before_unlocked(owner)
        if (owner._phase != "new" or owner._retaining_before is not False
                or owner._retaining_success is not None or owner._success_deadline is not None
                or owner._plan.task_id != owner._request.episode_id):
            _fail("initial_owner_required")
        _fixed_original_brs_owner(owner)
        reader = reader_module._BRSRetainedNativePreparationReader(
            owner, original_preparation=original_preparation,
        )
        recovered = reader_module._BRSRetainedNativePreparationReader.recover(reader, worker_request)
        arguments, original = reader._arguments, reader._original
        batch = owner._workspace / "evolution/producer-batches" / owner._plan.journal_id
        receipt_path = batch / "execution-receipt.json"
        # This is an entry observation of an already verified original receipt,
        # not a replacement for the creator's historical handoff/capture pins.
        receipt_pin = capture_lineage_snapshot_pin(receipt_path, name="execution-receipt.json")
        verify_persisted_lineage_snapshot(receipt_path, receipt_pin)
        receipt = parse_producer_execution_receipt(json.loads(_files.read_regular_file(receipt_path, 256 * 1024)))
        verify_persisted_lineage_snapshot(receipt_path, receipt_pin)
        if receipt != recovered.receipt:
            _fail("receipt_drift")
        _fixed_original_brs_owner(owner)

        def observe(_stage: str) -> None:
            _BRSLineageCheckpointOwner._success_observe(owner)
            if reader_module._arguments(owner) != arguments:
                _fail("native_arguments_drift")
            _fixed_original_brs_owner(owner)
            current = reader_module._copy(recover_native_trusted_producer(**arguments, require_broker=True))
            if current != recovered:
                _fail("native_evidence_drift")
            verify_persisted_lineage_snapshot(receipt_path, receipt_pin)
            handoff = read_python_producer_admission_handoff_pinned(batch, expected_file_pin=original.handoff.file_pin)
            if handoff != original.handoff:
                _fail("handoff_drift")
            _fixed_original_brs_owner(owner)

        def prepared(journal: object) -> None:
            _fixed_original_brs_owner(owner)
            anchor = _admission_attempt_anchor(original.handoff.handoff)
            reference = RSILearningController._pin_python_admission_for_original_brs_owner(
                owner._controller, owner, expected_anchor_sha256=anchor.anchor_sha256,
            )
            _BRSLineageCheckpointOwner.acknowledge_prepared(owner, journal, reference)

        result = _run_bound_native_producer_bundle_publication_transaction(
            owner._workspace, owner._strategy, recovered.output.drafts, recovered.output.admission_plan,
            journal_id=owner._plan.journal_id, run_id=owner._run_id,
            parent_task_id=owner._plan.parent_task_id, task_id=owner._plan.task_id,
            native_execution_receipt_sha256=recovered.receipt.receipt_sha256,
            python_handoff_sha256=original.handoff.handoff.handoff_sha256,
            python_handoff_file_pin=original.handoff.file_pin,
            execution_control=owner._before_control, evidence_revalidator=observe,
            prepared_observer=prepared, lineage_owner=owner, _original_brs_owner=owner,
            _original_brs_receipt_pin=receipt_pin,
        )
        if (result.publication_status != "published" or not result.admitted_candidate_ids
                or owner._phase != "terminal"):
            _fail("success_required")
        _fixed_original_brs_owner(owner)
        return result
    except BaseException:
        owner._poisoned = True
        raise
