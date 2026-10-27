"""Read-only pre-arm reconstruction against one original rejected-owner C2.

This semantic reader belongs outside both short observation/Condition locks. Its
caller must pin the reachable reader graph, bracket it with equal complete raw-row
captures and separately preserve C1/P/file/inode/deadline custody. The returned
immutable comparison data grants no ready, owner, ACK or execution authority.
Nothing here registers an admission, pins a reference, refreshes a head or poisons
an owner. Failure handling and the future one-shot ready scope belong to the caller.
"""

from __future__ import annotations

import json
from typing import NoReturn

from . import rsi_brs_rejection_ready_sync as sync
from .candidate_evaluation_spec import canonical_json
from .rsi_learning import RSILearningError

_MAX_REFERENCE_BYTES = 8 * 1024 * 1024
_MAX_EPISODES = 4096
# Explicit read-only self-dispatch edges. Worker/execution methods are outside this
# semantic reader; genuine inert fixtures may replace those separate boundaries.
_CONTROLLER_READERS = (
    "_python_admission_assert_brs_wave", "_python_admission_brs_observations",
    "_python_admission_evidence", "_python_admission_flow_payload", "_python_admission_inputs",
    "_python_admission_selected_brs_identity", "_python_admission_sidecar",
    "_validate_original_producer_checkpoint", "_validate_original_run_checkpoint_producer_binding",
    "_validate_python_admission_record_evidence", "_validate_python_admission_references",
    "_python_admission_existing_rejection_brs_ready",
)
_LEDGER_READERS = (
    "_assert_controller_lock", "_checkpoint_binding", "_checkpoint_digest", "_checkpoint_python_references",
    "_checkpoint_reference_rows_tx", "_connect", "_controller_checkpoint_history_tx", "_head",
    "_is_canonical_episode", "_native_claim_plan", "_native_claim_row", "_native_result_status",
    "_python_admission_row", "_python_admission_state_tx", "_row_to_record", "_row_to_record_cached",
    "_select_python_producer_checkpoint_tx", "_validate_python_producer_staging_history_tx",
    "controller_checkpoint", "controller_checkpoint_history", "controller_lock_held", "episode_result",
    "get", "get_episode", "get_run", "history", "inspect_native_episode_claim",
    "python_admission_record", "read_only_observations", "resolve_python_producer_checkpoint",
)


def _fail(reason: str) -> NoReturn:
    raise RSILearningError("rsi_brs_rejection_ready_reference_" + reason)


def _digest(value: object) -> str:
    if (type(value) is not str or len(value) != 64 or value == "0" * 64
            or any(character not in "0123456789abcdef" for character in value)):
        _fail("capture_invalid")
    return value


def _identifier(value: object) -> str:
    if (type(value) is not str or not 1 <= len(value) <= 128
            or value[0] not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
            or any(character not in
                   "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:-"
                   for character in value)):
        _fail("capture_invalid")
    return value


def _shadows(value: object, declared: type, readers: tuple[str, ...]) -> None:
    """Refuse instance replacements before canonical roots dispatch through self."""
    if type(value) is not declared:
        _fail("owner_invalid")
    namespace = object.__getattribute__(value, "__dict__")
    if type(namespace) is not dict or any(type(key) is not str for key in namespace):
        _fail("reader_shadow")
    if any(name in namespace for name in readers):
        _fail("reader_shadow")


def _capture(owner: object) -> tuple:
    from .producer_bundle_publication import ProducerBundlePublicationJournal
    from .rsi_brs_publication_lineage import _BRSLineageCheckpointOwner
    from .rsi_controller import RSILearningController, _PythonAdmissionBRSWave
    from .rsi_gateway import SolverRequest
    from .rsi_native_plan import NativeRSIExecutionPlan
    from .rsi_python_admission import parse_rsi_python_admission_references
    from .rsi_python_brs_admission import BRSAdmissionChannel
    from .rsi_store import RSILedger

    if (type(owner) is not _BRSLineageCheckpointOwner or owner._poisoned is not False
            or type(owner._phase) is not str or owner._phase != "rejected-provenance"
            or owner._retaining_rejection_provenance is not False):
        _fail("owner_invalid")
    controller, ledger, wave = owner._controller, owner._ledger, owner._wave
    _shadows(controller, RSILearningController, _CONTROLLER_READERS)
    _shadows(ledger, RSILedger, _LEDGER_READERS)
    if (type(wave) is not _PythonAdmissionBRSWave or type(owner._request) is not SolverRequest
            or type(owner._plan) is not NativeRSIExecutionPlan
            or type(owner._prepared) is not ProducerBundlePublicationJournal
            or type(owner._channel) is not BRSAdmissionChannel):
        _fail("owner_invalid")
    channel, condition = owner._channel, owner._before_channel_condition
    condition_pin = sync.capture_ready_condition(condition)
    namespace = object.__getattribute__(channel, "__dict__")
    if (type(namespace) is not dict or any(type(key) is not str for key in namespace)
            or namespace.get("_condition") is not condition):
        _fail("capture_invalid")
    c2 = owner._rejection_provenance_c2_capture
    if (type(c2) is not tuple or len(c2) != 2 or type(c2[1]) is not bytes
            or not c2[1] or len(c2[1]) > _MAX_REFERENCE_BYTES):
        _fail("capture_invalid")
    _digest(c2[0])
    run, episode = _identifier(owner._run_id), _identifier(owner._request.episode_id)
    _digest(owner._run_head)
    _digest(owner._episode_head)
    state = json.loads(c2[1])
    if type(state) is not dict or RSILearningController._python_admission_flow_payload(state) != c2[1]:
        _fail("capture_invalid")
    references = parse_rsi_python_admission_references(state.get("python_admission_refs", {}))
    if episode not in references:
        _fail("reference_missing")
    reference = references[episode]
    if (canonical_json(reference["native_plan"], maximum=_MAX_REFERENCE_BYTES)
            != canonical_json(owner._plan.to_dict(), maximum=_MAX_REFERENCE_BYTES)
            or canonical_json(reference["prepared_journal"], maximum=_MAX_REFERENCE_BYTES)
            != canonical_json(owner._prepared.to_dict(), maximum=_MAX_REFERENCE_BYTES)):
        _fail("reference_drift")
    episodes = wave.episode_ids
    if (type(episodes) is not tuple or not 1 <= len(episodes) <= _MAX_EPISODES):
        _fail("capture_invalid")
    for item in episodes:
        _identifier(item)
    if len(set(episodes)) != len(episodes) or episode not in episodes:
        _fail("capture_invalid")
    complete = tuple(sorted(set(episodes) | set(references)))
    if len(complete) > _MAX_EPISODES:
        _fail("capture_invalid")
    return (controller, ledger, wave, run, episode, owner._run_head, owner._episode_head,
            c2, owner._plan, owner._prepared, owner._request,
            canonical_json(reference, maximum=_MAX_REFERENCE_BYTES), complete, channel, condition, condition_pin)


def _check(owner: object, held: tuple) -> None:
    from .rsi_brs_publication_lineage import _BRSLineageCheckpointOwner
    from .rsi_controller import RSILearningController
    from .rsi_store import RSILedger

    (controller, ledger, wave, run, episode, run_head, episode_head, c2,
     plan, prepared, request, _reference, _episodes, channel, condition, condition_pin) = held
    if (type(owner) is not _BRSLineageCheckpointOwner or owner._poisoned is not False
            or type(owner._phase) is not str or owner._phase != "rejected-provenance"
            or owner._retaining_rejection_provenance is not False
            or owner._controller is not controller or owner._ledger is not ledger or owner._wave is not wave
            or owner._plan is not plan or owner._prepared is not prepared or owner._request is not request
            or owner._channel is not channel or owner._before_channel_condition is not condition
            or owner._rejection_provenance_c2_capture is not c2
            or type(owner._run_id) is not str or owner._run_id != run
            or type(owner._run_head) is not str or owner._run_head != run_head
            or type(owner._episode_head) is not str or owner._episode_head != episode_head
            or type(owner._head) is not str or owner._head != c2[0]
            or type(owner._payload) is not bytes or owner._payload != c2[1]):
        _fail("capture_drift")
    _shadows(controller, RSILearningController, _CONTROLLER_READERS)
    _shadows(ledger, RSILedger, _LEDGER_READERS)
    _BRSLineageCheckpointOwner._before_unlocked(owner)
    sync.assert_ready_condition(condition, condition_pin)
    _BRSLineageCheckpointOwner._identity(owner)
    sync.assert_ready_condition(condition, condition_pin)
    _BRSLineageCheckpointOwner._before_channel(owner)
    sync.assert_ready_condition(condition, condition_pin)
    with RSILedger.read_only_observations(ledger):
        _BRSLineageCheckpointOwner._running(owner)
        checkpoint = RSILedger.controller_checkpoint(ledger, run)
    if (type(checkpoint) is not tuple or len(checkpoint) != 2
            or type(checkpoint[0]) is not str or checkpoint[0] != c2[0]
            or RSILearningController._python_admission_flow_payload(checkpoint[1]) != c2[1]
            or RSILearningController._python_admission_flow_payload(owner._state) != c2[1]
            or type(request.episode_id) is not str or request.episode_id != episode):
        _fail("checkpoint_drift")
    # Dynamic semantic validation may not replace the original heads or object
    # captures, even if a replacement happens to be internally self-consistent.
    if (owner._controller is not controller or owner._ledger is not ledger or owner._wave is not wave
            or owner._plan is not plan or owner._prepared is not prepared or owner._request is not request
            or owner._channel is not channel or owner._before_channel_condition is not condition
            or owner._rejection_provenance_c2_capture is not c2 or owner._poisoned is not False
            or type(owner._phase) is not str or owner._phase != "rejected-provenance"
            or owner._retaining_rejection_provenance is not False
            or type(owner._run_head) is not str or owner._run_head != run_head
            or type(owner._episode_head) is not str or owner._episode_head != episode_head
            or type(owner._head) is not str or owner._head != c2[0]
            or type(owner._payload) is not bytes or owner._payload != c2[1]):
        _fail("capture_drift")
    _shadows(controller, RSILearningController, _CONTROLLER_READERS)
    _shadows(ledger, RSILedger, _LEDGER_READERS)
    sync.assert_ready_condition(condition, condition_pin)


def validate_existing_rejection_reference(owner: object) -> tuple[bytes, bytes, str, tuple[str, ...]]:
    """Revalidate the selected existing record using original run/episode/C2 heads.

    The tuple contains canonical selected reference bytes, canonical record bytes,
    its original record digest and the complete wave plus held-reference episode
    domain. It is comparison data for a future pre-arm gate, never a ready permit.
    """
    from .rsi_controller import RSILearningController
    from .rsi_python_admission import (
        RSIPythonAdmissionRecord,
        validate_rsi_python_admission_reference_record,
    )
    from .rsi_store import RSILedger

    held = _capture(owner)
    _check(owner, held)
    (controller, ledger, _wave, run, episode, run_head, episode_head, c2,
     plan, prepared, _request, reference_bytes, episodes, _channel, _condition, _condition_pin) = held
    reference = json.loads(reference_bytes)
    digest = reference["record_sha256"]
    with RSILedger.read_only_observations(ledger):
        original = RSILedger.python_admission_record(
            ledger, run, episode, reference["journal_id"], expected_record_sha256=digest,
            expected_run_record_sha256=run_head, expected_checkpoint_sha256=c2[0],
            expected_episode_record_sha256=episode_head,
        )
    if type(original) is not RSIPythonAdmissionRecord:
        _fail("record_invalid")
    record_bytes = RSIPythonAdmissionRecord.to_json(original)
    anchor = original.admission_anchor["anchor_sha256"]
    with RSILedger.read_only_observations(ledger):
        parsed_plan, parsed_journal, binding = RSILearningController._python_admission_inputs(
            controller, plan, prepared, anchor,
        )
        rebuilt, observed_run, observed_checkpoint, observed_episode = (
            RSILearningController._python_admission_evidence(
                controller, run, episode, parsed_plan, parsed_journal, binding, anchor,
            )
        )
        for observed, expected in ((observed_run, run_head), (observed_checkpoint, c2[0]),
                                   (observed_episode, episode_head)):
            if type(observed) is not str or observed != expected:
                _fail("evidence_head_drift")
        current = RSILedger.python_admission_record(
            ledger, run, episode, reference["journal_id"], expected_record_sha256=digest,
            expected_run_record_sha256=run_head, expected_checkpoint_sha256=c2[0],
            expected_episode_record_sha256=episode_head,
        )
        if (type(rebuilt) is not RSIPythonAdmissionRecord or type(current) is not RSIPythonAdmissionRecord
                or RSIPythonAdmissionRecord.to_json(rebuilt) != record_bytes
                or RSIPythonAdmissionRecord.to_json(current) != record_bytes):
            _fail("record_drift")
        checked = validate_rsi_python_admission_reference_record(
            reference, current, run_id=run, episode_id=episode,
        )
        if canonical_json(checked, maximum=_MAX_REFERENCE_BYTES) != reference_bytes:
            _fail("reference_drift")
        RSILearningController._validate_python_admission_references(controller, run, json.loads(c2[1]))
    _check(owner, held)
    return reference_bytes, record_bytes, digest, episodes


def _active_reference_check(owner: object, ready: object) -> tuple:
    """Validate a live staged request without invoking the old empty-channel gate."""
    from . import rsi_brs_rejection_ready_owner as ready_owner
    from .rsi_brs_publication_lineage import _BRSLineageCheckpointOwner
    from .rsi_brs_rejection_ready_service import validate_active_ready
    from .rsi_controller import RSILearningController
    from .rsi_store import RSILedger

    capture = validate_active_ready(owner, ready)
    if any(value is not original for value, original in zip(
            ready_owner._custody(owner), capture[0], strict=True)):
        _fail("capture_drift")
    _shadows(owner._controller, RSILearningController, _CONTROLLER_READERS)
    _shadows(owner._ledger, RSILedger, _LEDGER_READERS)
    _BRSLineageCheckpointOwner._before_unlocked(owner)
    _BRSLineageCheckpointOwner._before_control_live(owner)
    _BRSLineageCheckpointOwner._identity(owner)
    with RSILedger.read_only_observations(owner._ledger):
        _BRSLineageCheckpointOwner._running(owner)
    if (owner._rejection_ready_capture is not capture
            or any(value is not original for value, original in zip(
                ready_owner._custody(owner), capture[0], strict=True))):
        _fail("capture_drift")
    validate_active_ready(owner, ready)
    return capture


def validate_active_rejection_reference(owner: object, ready: object) -> str:
    """Rebuild only the original admission bound to the active natural pending.

    Dynamic semantic observations run outside the final short locks. The service
    still compares the complete original raw rows and physical evidence before
    making an ACK visible; this function never registers or pins a reference.
    """
    from .rsi_controller import RSILearningController
    from .rsi_python_admission import (
        RSIPythonAdmissionRecord,
        validate_rsi_python_admission_reference_record,
    )
    from .rsi_store import RSILedger

    capture = _active_reference_check(owner, ready)
    reference_bytes, record_bytes, digest, _episodes = capture[4]
    selected = json.loads(reference_bytes)
    controller, ledger = owner._controller, owner._ledger
    run, episode = capture[3][:2]
    run_head, episode_head = owner._run_head, owner._episode_head
    c2 = owner._rejection_provenance_c2_capture
    with RSILedger.read_only_observations(ledger):
        original = RSILedger.python_admission_record(
            ledger, run, episode, selected["journal_id"], expected_record_sha256=digest,
            expected_run_record_sha256=run_head, expected_checkpoint_sha256=c2[0],
            expected_episode_record_sha256=episode_head,
        )
        if type(original) is not RSIPythonAdmissionRecord or RSIPythonAdmissionRecord.to_json(original) != record_bytes:
            _fail("record_drift")
        anchor = original.admission_anchor["anchor_sha256"]
        plan, journal, binding = RSILearningController._python_admission_inputs(
            controller, owner._plan, owner._prepared, anchor)
        rebuilt, observed_run, observed_checkpoint, observed_episode = (
            RSILearningController._python_admission_evidence(controller, run, episode, plan, journal, binding, anchor)
        )
        for observed, expected in ((observed_run, run_head), (observed_checkpoint, c2[0]),
                                   (observed_episode, episode_head)):
            if type(observed) is not str or observed != expected:
                _fail("evidence_head_drift")
        current = RSILedger.python_admission_record(
            ledger, run, episode, selected["journal_id"], expected_record_sha256=digest,
            expected_run_record_sha256=run_head, expected_checkpoint_sha256=c2[0],
            expected_episode_record_sha256=episode_head,
        )
        if (type(rebuilt) is not RSIPythonAdmissionRecord or type(current) is not RSIPythonAdmissionRecord
                or RSIPythonAdmissionRecord.to_json(rebuilt) != record_bytes
                or RSIPythonAdmissionRecord.to_json(current) != record_bytes):
            _fail("record_drift")
        checked = validate_rsi_python_admission_reference_record(selected, current, run_id=run, episode_id=episode)
        if canonical_json(checked, maximum=_MAX_REFERENCE_BYTES) != reference_bytes:
            _fail("reference_drift")
        RSILearningController._validate_python_admission_references(controller, run, json.loads(c2[1]))
    if _active_reference_check(owner, ready) is not capture:
        _fail("capture_drift")
    return digest


__all__ = ["validate_active_rejection_reference", "validate_existing_rejection_reference"]
