"""One original rejected owner retains a read-only, pre-arm ready baseline.

This consumes a capture attempt, not a ready request. It neither arms the channel
nor permits an ACK. Later transport must independently validate the retained
baseline, active original pending request and complete final-reader graph.
"""

from __future__ import annotations

import hashlib
import json

from . import rsi_brs_rejection_provenance as provenance
from . import rsi_brs_rejection_ready_ledger as raw_ledger
from . import rsi_brs_rejection_ready_reference as reference
from . import rsi_brs_rejection_ready_sync as sync
from .candidate_evaluation_spec import canonical_json
from .rsi_learning import RSILearningError

_CAPTURES = (
    "_controller", "_wave", "_ledger", "_channel", "_before_channel_condition",
    "_handoff", "_selected_context", "_state", "_plan", "_request", "_memory",
    "_claim", "_prepared", "_native_inputs", "_native", "_before_control",
    "_before_cancelled", "_workspace", "_sidecar", "_rejection_c1_capture",
    "_rejection_provenance_c2_capture", "_rejection_file_pin", "_rejection_ledger_identity",
    "_rejection_provenance_evidence", "_rejection_provenance_sha256",
    "_rejection_provenance_file_pin", "_budget_bytes", "_handoff_bytes",
    "_selected_context_bytes", "_run_head", "_episode_head", "_head", "_payload", "_policy_bytes",
    "_rejection_ready_sync_capture",
)
_CONTROLLER_READERS = (*reference._CONTROLLER_READERS,
    "_python_admission_active_brs_owner", "_python_admission_assert_selected_brs",
    "_run_fingerprint", "_validate_producer_staging", "_producer_child_execution_policy",
    "_producer_known_rejection_mode", "_python_admission_brs_selected_pins",
    "_python_admission_brs_fixed_pins", "_validate_producer_checkpoint")


def _fail(reason: str) -> None:
    raise RSILearningError("rsi_brs_rejection_ready_owner_" + reason)


def _owner(owner) -> None:
    from .rsi_brs_publication_lineage import _BRSLineageCheckpointOwner

    if type(owner) is not _BRSLineageCheckpointOwner:
        _fail("owner_invalid")


def _custody(owner) -> tuple:
    return tuple(getattr(owner, name) for name in _CAPTURES)


def _assert_custody(owner, held: tuple) -> None:
    from .rsi_controller import RSILearningController
    from .rsi_store import RSILedger

    if (any(current is not original for current, original in zip(_custody(owner), held, strict=True))
            or type(owner._phase) is not str or owner._phase != "rejected-provenance"
            or owner._poisoned is not False
            or type(owner._policy_bytes) is not bytes or type(owner._payload) is not bytes
            or type(owner._head) is not str
            or owner._rejection_ready_capture_started is not True
            or owner._rejection_ready_capture is not None):
        _fail("custody_drift")
    reference._shadows(owner._controller, RSILearningController, _CONTROLLER_READERS)
    reference._shadows(owner._ledger, RSILedger, reference._LEDGER_READERS)
    provenance._allowance(owner)
    if RSILearningController._python_admission_flow_payload(owner._state) != owner._payload:
        _fail("original_c2_drift")


def _domain(owner) -> tuple[str, ...]:
    c2 = owner._rejection_provenance_c2_capture
    if (type(c2) is not tuple or len(c2) != 2 or type(c2[0]) is not str
            or type(c2[1]) is not bytes or type(owner._head) is not str
            or type(owner._payload) is not bytes or (owner._head, owner._payload) != c2):
        _fail("original_c2_required")
    state = json.loads(c2[1])
    refs = state.get("python_admission_refs")
    episodes = owner._wave.episode_ids
    if (type(refs) is not dict or len(refs) > 4096 or any(type(key) is not str for key in refs)
            or type(episodes) is not tuple or not 1 <= len(episodes) <= 4096
            or any(type(item) is not str for item in episodes)):
        _fail("episode_domain_invalid")
    return tuple(sorted(set(episodes) | set(refs)))


def _payload(owner, retained_record: bytes) -> bytes:
    retained = json.loads(retained_record)
    return canonical_json({"native_plan": owner._plan.to_dict(),
        "prepared_journal": owner._prepared.to_dict(),
        "expected_anchor_sha256": retained["admission_anchor"]["anchor_sha256"]})


def _empty(owner, condition_capture: tuple, held: tuple) -> None:
    _assert_custody(owner, held)
    sync.assert_ready_condition(owner._before_channel_condition, condition_capture)
    owner._before_channel()
    sync.assert_ready_condition(owner._before_channel_condition, condition_capture)


def _check_original(owner, condition_capture: tuple, held: tuple) -> None:
    # Old provenance checks deliberately retain their empty-channel requirement.
    # Check the independently retained native operations before they enter it.
    _empty(owner, condition_capture, held)
    provenance._observe(owner)
    _empty(owner, condition_capture, held)
    provenance._fresh(owner)
    provenance._read_p(owner)
    provenance._ledger_identity(owner)
    _empty(owner, condition_capture, held)


def retain_rejection_ready_capture(self) -> None:
    """Consume one pre-arm capture attempt on this exact original owner only."""
    from .rsi_brs_publication_lineage import _BRSLineageCheckpointOwner, _policy

    if type(self) is not _BRSLineageCheckpointOwner:
        raise RSILearningError("rsi_brs_rejection_ready_owner_owner_invalid")
    try:
        if self._poisoned is not False:
            _fail("owner_poisoned")
        if (type(self._policy_bytes) is not bytes or type(self._payload) is not bytes
                or type(self._head) is not str):
            _fail("capture_type_invalid")
        if canonical_json(_policy()) != self._policy_bytes:
            _fail("policy_drift")
        _owner(self)
        if (self._rejection_ready_capture_started is not False
                or self._rejection_ready_capture is not None or self._rejection_ready_sync_capture is not None):
            _fail("capture_already_consumed")
        self._rejection_ready_capture_started = True
        # Do not invoke the old Condition context before checking native custody.
        condition_capture = sync.capture_ready_condition(self._before_channel_condition)
        self._rejection_ready_sync_capture = condition_capture
        held = _custody(self)
        self._before_unlocked()
        _empty(self, condition_capture, held)
        domain = _domain(self)
        database = str(self._ledger.database)
        rows = raw_ledger.read_rejection_ready_rows(database, run_id=self._run_id, episode_ids=domain)
        _check_original(self, condition_capture, held)
        existing = reference.validate_existing_rejection_reference(self)
        if existing[3] != domain:
            _fail("episode_domain_drift")
        ready_payload = _payload(self, existing[1])
        handoff = json.loads(self._handoff_bytes)
        scope = (self._run_id, self._request.episode_id,
                 hashlib.sha256(self._handoff_bytes).hexdigest(),
                 handoff["lease_nonce"], self._wave.episode_ids, self._thread)
        # Bracket every complete semantic/material check with the original rows.
        _check_original(self, condition_capture, held)
        if canonical_json(_policy()) != self._policy_bytes:
            _fail("policy_drift")
        raw_ledger.assert_rejection_ready_rows(database, rows)
        provenance._ledger_identity(self)
        provenance._allowance(self)
        _empty(self, condition_capture, held)
        self._rejection_ready_capture = (held, rows, condition_capture, scope, existing, ready_payload)
    except BaseException:
        self._poisoned = True
        raise
