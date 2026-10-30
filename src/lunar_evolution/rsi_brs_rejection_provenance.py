"""Same original BRS owner C1/P/C2 custody; no dispatch or settlement."""

from __future__ import annotations

import json
import math
import time
from typing import Any

from . import _benchmark_files as _files
from . import rsi_publication_lineage as lineage
from .native_trusted_scheduler import recover_native_trusted_producer
from .producer_bundle_lineage import LineageSnapshotPin, verify_persisted_lineage_snapshot
from .producer_bundle_lineage_v2 import read_lineage_v2_descriptor_pinned
from .producer_bundle_publication import parse_producer_bundle_publication_journal
from .producer_bundle_rejection import _verify_terminal_batch_rejection_evidence
from .rsi_brs_rejection_c1 import (
    REJECTION_PROVENANCE_SCHEMA,
    rejected_c1_entry,  # noqa: F401 - retained policy identity alias.
    validate_rejected_provenance_transition,
)
from .rsi_brs_rejection_capacity import (
    retained_brs_c1_evidence_bytes,  # noqa: F401 - retained policy identity alias.
    retained_brs_c2_evidence_bytes,  # noqa: F401 - retained policy identity alias.
)
from .rsi_brs_rejection_owner import _rejection_retained_bytes, _rejection_terminal
from .rsi_learning import RSILearningError
from .rsi_native_rejection import (
    NATIVE_RSI_REJECTION_PROVENANCE_NAME,
    NativeRSIRejectionEvidence,
    NativeRSIRejectionFilePin,
    RejectionLineageC1Binding,
    _canonical,
    _dto_shape,
    persist_native_rsi_rejection_provenance,
    read_native_rsi_rejection_provenance,
)
from .rsi_native_scheduler import _read_ledger_identity
from .rsi_python_scheduler_inputs import validate_python_rsi_scheduler_inputs

_FIELD = "producer_publication_lineage"


def _fail(reason: str) -> None:
    raise RSILearningError("rsi_brs_rejection_provenance_" + reason)


def _owner(self) -> None:
    from .rsi_brs_publication_lineage import _BRSLineageCheckpointOwner

    if type(self) is not _BRSLineageCheckpointOwner:
        _fail("owner_invalid")


def _validate_c2(self, previous, current):
    if self._reserved_prefix is None:
        return validate_rejected_provenance_transition(previous, current)
    from .rsi_brs_reserved_rejection import validate_reserved_brs_c2_transition

    return validate_reserved_brs_c2_transition(previous, current, prefix=self._reserved_prefix,
        original_lineage_bytes=self._reserved_lineage_bytes, native_plan_sha256=self._plan.plan_sha256)


def _capture(self) -> tuple[dict[str, Any], dict[str, Any]]:
    """Use only the independently held successful original C1 capture."""
    if type(self._ordinal) is not int or not 0 <= self._ordinal < 8:
        _fail("original_ordinal_invalid")
    capture = self._rejection_c1_capture
    if (type(capture) is not tuple or len(capture) != 2 or type(capture[0]) is not str
            or type(capture[1]) is not bytes or self._phase not in {"rejected", "rejected-provenance"}):
        _fail("original_c1_required")
    state = json.loads(capture[1])
    if self._controller._python_admission_flow_payload(state) != capture[1]:
        _fail("original_c1_drift")
    wire = state.get(_FIELD)
    if type(wire) is not dict or type(wire.get("batches")) is not list or len(wire["batches"]) != self._ordinal + 1:
        _fail("original_c1_drift")
    entry = wire["batches"][self._ordinal]
    _rejection_terminal(self, entry)
    if (type(self._rejection_file_pin) is not LineageSnapshotPin
            or LineageSnapshotPin.from_dict(entry["rejected_file_pin"]) != self._rejection_file_pin
            or json.loads(self._policy_bytes).get("rejection_provenance_schema") != REJECTION_PROVENANCE_SCHEMA):
        _fail("original_c1_drift")
    current = (self._head, self._payload)
    if self._phase == "rejected":
        if current != capture or self._state != state or self._rejection_provenance_c2_capture is not None:
            _fail("original_c1_drift")
    else:
        c2 = self._rejection_provenance_c2_capture
        if (type(c2) is not tuple or len(c2) != 2 or type(c2[0]) is not str or type(c2[1]) is not bytes
                or current != c2 or self._controller._python_admission_flow_payload(self._state) != c2[1]):
            _fail("original_c2_drift")
        _validate_c2(self, wire, self._state.get(_FIELD))
        expected = lineage._publication_lineage_checkpoint_delta(capture[1], self._state[_FIELD])
        if self._controller._python_admission_flow_payload(expected) != c2[1]:
            _fail("original_c2_drift")
    return state, wire


def _custody(self) -> tuple[Any, ...]:
    return (self._rejection_c1_capture, self._rejection_file_pin, self._rejection_ledger_identity,
            self._rejection_provenance_deadline, self._rejection_provenance_evidence,
            self._rejection_provenance_sha256, self._rejection_provenance_file_pin,
            self._rejection_provenance_c2_capture, self._ordinal, self._reserved_prefix,
            self._reserved_lineage_bytes, self._reserved_original_checkpoint, self._reserved_capture_bytes,
            self._reserved_scope, self._reserved_gateway, self._root_sidecar)


def _unchanged(self, held: tuple[Any, ...]) -> None:
    if any(current is not original for current, original in zip(_custody(self), held, strict=True)):
        _fail("custody_drift")
    _allowance(self)


def _allowance(self) -> None:
    active, deadline = self._retaining_rejection_provenance, self._rejection_provenance_deadline
    if (type(active) is not bool or self._retaining_rejection is not False
            or self._rejection_deadline is not None or self._retaining_before is not False
            or self._retaining_success is not None or self._success_deadline is not None):
        _fail("scope_drift")
    if active:
        if (self._phase != "rejected" or self._rejection_provenance_c2_capture is not None
                or type(deadline) is not float or not math.isfinite(deadline) or time.monotonic() >= deadline):
            _fail("allowance_exhausted")
    elif deadline is not None:
        _fail("scope_drift")
    if self._before_control_state() != self._before_control_pin:
        _fail("control_drift")
    if self._before_control is not None:
        with self._before_control._lock:
            if self._before_control._cancelled is not False:
                _fail("cancelled")
            if time.monotonic() >= self._before_control.deadline:
                _fail("allowance_exhausted")
    absolute = self._plan.deadline_unix
    if type(absolute) not in {int, float} or not math.isfinite(absolute) or time.time() >= absolute:
        _fail("allowance_exhausted")


def _control(self) -> None:
    held = _custody(self)
    started = time.monotonic()
    remaining = self._before_control_live()
    _unchanged(self, held)
    if remaining is not None and self._retaining_rejection_provenance:
        if type(remaining) not in {int, float} or not math.isfinite(remaining) or remaining <= 0:
            _fail("allowance_exhausted")
        self._rejection_provenance_deadline = min(self._rejection_provenance_deadline, started + remaining)
    _allowance(self)


def _policy_gate(self) -> None:
    """Check the finite live graph after observation seams, immediately before effects."""
    from .rsi_brs_publication_lineage import _policy

    if lineage._raw(_policy()) != self._policy_bytes:
        _fail("policy_drift")


def _ledger_identity(self) -> dict[str, Any]:
    held = self._rejection_ledger_identity
    if type(held) is not bytes or lineage._raw(_read_ledger_identity(self._ledger)) != held:
        _fail("ledger_inode_drift")
    return json.loads(held)


def _fixed(self, expected: dict[str, Any] | None = None) -> None:
    held = _custody(self)
    _allowance(self)
    self._identity()
    _capture(self)
    _ledger_identity(self)
    with self._ledger.read_only_observations():
        self._running()
        if expected is None:
            self._controller._python_admission_active_brs_owner(self._wave)
        self._history(self._state if expected is None else expected)
    self._before_channel()
    _unchanged(self, held)


def _postwrite_observe(self, expected: dict[str, Any]) -> None:
    """Observe durable C2 while retaining local C1; do not refresh any capture."""
    from .rsi_budget import RSIRunBudget
    from .rsi_controller import _record_digest
    from .rsi_fingerprint import RSIFingerprintContract, ensure_fingerprint_compatible

    held = _custody(self)
    self._identity()
    captured = json.loads(self._rejection_c1_capture[1])
    with self._ledger.read_only_observations():
        self._running()
        original = self._ledger.history(self._run_id)[0]
        actual, _ = self._controller._run_fingerprint(
            **captured["pins"], memory_snapshot_sha256=self._memory.digest(),
            mode=captured["mode"], plan=captured["plan"])
        _unchanged(self, held)
        ensure_fingerprint_compatible(
            RSIFingerprintContract.from_dict(original.payload["fingerprints"]["run_fingerprint"]), actual)
        run = self._ledger.get_run(self._run_id)
        self._controller._validate_original_run_checkpoint_producer_binding(run, expected)
        self._controller._validate_python_admission_references(self._run_id, expected)
        self._controller._validate_producer_staging(run, expected)
        self._history(expected)
    budget = RSIRunBudget.load(captured["budget_state"])
    budget.assert_matches(original.payload["budget"])
    budget.check()
    policy = {"plan": captured["plan"], "pins": captured["pins"], "planned": budget.to_dict()["planned"],
              "producer_checkpoint_binding": captured.get("producer_checkpoint_binding"),
              "solver_settings": actual.to_dict()["solver_settings"]}
    control = {"budget_state": budget.to_dict(), "status": captured["status"]}
    context = self._selected_context
    if (actual.digest() != context.source_sha256 or _record_digest(policy) != context.policy_sha256
            or _record_digest(control) != context.execution_control_sha256):
        _fail("source_drift")
    self._native_strategy()
    _unchanged(self, held)


def _observe(self, expected: dict[str, Any] | None = None) -> None:
    """Close source/control callbacks with a fresh complete owner observation."""
    self._before_unlocked()
    held = _custody(self)
    _allowance(self)
    if expected is None:
        self._check_owner()
    else:
        _postwrite_observe(self, expected)
    _unchanged(self, held)
    _control(self)
    _fixed(self, expected)


def _material_tables(self, entry: dict[str, Any], batch) -> dict[str, Any]:
    from .rsi_brs_rejection_owner import _read_rejection_tables

    if batch != self._workspace / "evolution/producer-batches" / entry["journal_id"]:
        _fail("material_domain_drift")
    return _read_rejection_tables(self, entry)


def _fresh(self) -> tuple[NativeRSIRejectionEvidence, dict[str, Any]]:
    """Rebuild evidence from original live native inputs, receipts and C1 files."""
    held = _custody(self)
    _allowance(self)
    state, wire = _capture(self)
    entry = wire["batches"][self._ordinal]
    rejected = _rejection_terminal(self, entry)
    batch = self._workspace / "evolution/producer-batches" / self._plan.journal_id
    self._native_strategy()
    inputs = validate_python_rsi_scheduler_inputs(self._native_inputs, self._request, self._memory,
                                                 require_unexpired=True)
    ledger_identity = _ledger_identity(self)
    if self._verify_descriptor(entry, "before").to_dict() != entry["before"]:
        _fail("descriptor_drift")
    if read_lineage_v2_descriptor_pinned(self._workspace, entry["journal_id"], kind="rejected",
                                       expected_file_pin=self._rejection_file_pin) != rejected:
        _fail("descriptor_drift")
    archive = self._snapshot_bytes(entry["journal_id"], entry["snapshots"]["archive-before"], name="archive-before")
    state_bytes = self._snapshot_bytes(entry["journal_id"], entry["snapshots"]["state-before"], name="state-before")
    self._live_before(archive, state_bytes)
    for name, raw in entry["evidence_pins"].items():
        verify_persisted_lineage_snapshot(batch / name, LineageSnapshotPin.from_dict(raw))
    tables = _material_tables(self, entry, batch)
    terminal = parse_producer_bundle_publication_journal(entry["rejected_journal"])
    if parse_producer_bundle_publication_journal(entry["prepared_journal"]) != self._prepared:
        _fail("prepared_drift")
    native = self._native
    recovered = recover_native_trusted_producer(self._workspace, require_broker=True,
        **{name: getattr(native, name) for name in (
            "intent", "attestation", "artifact", "contract", "groups", "evaluator_kind",
            "evaluator_fingerprint", "runner_fingerprint", "dependency_sha256", "environment_sha256")})
    if (recovered.output.admission_plan.to_dict() != entry["admission_plan"]
            or terminal.native_execution_receipt_sha256 != recovered.receipt.receipt_sha256
            or self._prepared.native_execution_receipt_sha256 != recovered.receipt.receipt_sha256
            or any(getattr(recovered.receipt, key) != getattr(self._plan, key) for key in (
                "run_id", "journal_id", "parent_task_id", "task_id", "launch_id", "intent_sha256", "attestation_sha256"))):
        _fail("producer_binding_drift")
    observed = _verify_terminal_batch_rejection_evidence(self._workspace, batch, self._prepared, terminal=terminal)
    if (observed.manifest_sha256 != rejected.rejection_manifest_sha256
            or observed.candidate_ids != rejected.candidate_ids or observed.terminal != terminal):
        _fail("native_rejection_drift")
    actual = _rejection_retained_bytes(self, state, wire, tables)
    binding = RejectionLineageC1Binding(
        run_id=self._run_id, episode_id=self._request.episode_id, journal_id=self._plan.journal_id, ordinal=self._ordinal,
        checkpoint_sha256=self._rejection_c1_capture[0], rejected_sha256=rejected.digest(), retained_bytes=actual,
        **{name: getattr(rejected, name) for name in (
            "before_sha256", "prepared_journal_sha256", "terminal_journal_sha256", "rejection_manifest_sha256",
            "terminal_marker_sha256", "candidate_ids", "archive_sha256", "state_sha256")})
    evidence = NativeRSIRejectionEvidence(
        plan=self._plan, input_binding_sha256=inputs.launch_binding_sha256, ledger_identity=ledger_identity,
        claim=self._claim, lineage=binding, rejected=rejected, terminal=terminal,
        producer_execution_receipt_sha256=recovered.receipt.receipt_sha256,
        producer_output_sha256=recovered.output.output_capture_sha256,
        execution_receipt_sha256s=observed.execution_receipt_sha256s,
        evaluation_receipt_sha256s=observed.evaluation_receipt_sha256s,
        retained_evidence_sha256s=observed.retained_evidence_sha256s)
    for name, raw in entry["evidence_pins"].items():
        verify_persisted_lineage_snapshot(batch / name, LineageSnapshotPin.from_dict(raw))
    if (inputs != validate_python_rsi_scheduler_inputs(self._native_inputs, self._request, self._memory,
                                                      require_unexpired=True)
            or _material_tables(self, entry, batch) != tables
            or read_lineage_v2_descriptor_pinned(self._workspace, entry["journal_id"], kind="rejected",
                                                expected_file_pin=self._rejection_file_pin) != rejected):
        _fail("material_drift")
    lineage.RSIPublicationLineage._verify_before_source_pins(self, entry)
    self._live_before(archive, state_bytes)
    _ledger_identity(self)
    _unchanged(self, held)
    if (self._rejection_provenance_evidence is not None
            and (type(self._rejection_provenance_evidence) is not bytes
                 or _canonical(evidence.to_dict()) != self._rejection_provenance_evidence)):
        _fail("evidence_drift")
    return evidence, tables


def _wire(self, digest: str, pin: NativeRSIRejectionFilePin) -> dict[str, Any]:
    state, original = _capture(self)
    wire = json.loads(lineage._raw(original))
    wire["batches"][self._ordinal]["rejection_provenance"] = {"provenance_sha256": digest, "file_pin": pin.to_dict()}
    _validate_c2(self, state[_FIELD], wire)
    return wire


def _capacity(self, wire: dict[str, Any], tables: dict[str, Any]) -> None:
    state, _original = _capture(self)
    _rejection_retained_bytes(self, state, wire, tables, c2=True)
    lineage._raw(lineage._publication_lineage_checkpoint_delta(self._rejection_c1_capture[1], wire))


def _preflight(self, evidence: NativeRSIRejectionEvidence, tables: dict[str, Any]) -> None:
    maximum = 2**64 - 1
    worst = _canonical({**evidence.to_dict(), "file_identity": {"device": maximum, "inode": maximum},
                        "provenance_sha256": "f" * 64})
    pin = NativeRSIRejectionFilePin(name=NATIVE_RSI_REJECTION_PROVENANCE_NAME,
        sha256="f" * 64, size=len(worst), mode=0o400, nlink=1,
        **{name: maximum for name in ("device", "inode", "parent_device", "parent_inode", "mtime_ns", "ctime_ns")})
    _capacity(self, _wire(self, "f" * 64, pin), tables)


def _read_p(self) -> NativeRSIRejectionEvidence:
    held = _custody(self)
    pin, digest, raw = (self._rejection_provenance_file_pin, self._rejection_provenance_sha256,
                        self._rejection_provenance_evidence)
    if type(pin) is not NativeRSIRejectionFilePin or type(digest) is not str or type(raw) is not bytes:
        _fail("original_p_required")
    _dto_shape(pin)
    expected = NativeRSIRejectionEvidence.from_dict(json.loads(raw), provenance_sha256=digest, provenance_file_pin=pin)
    observed = read_native_rsi_rejection_provenance(
        self._workspace / "evolution/producer-batches" / self._plan.journal_id, expected_file_pin=pin)
    if type(observed) is not NativeRSIRejectionEvidence:
        _fail("provenance_drift")
    _dto_shape(observed)
    reparsed = NativeRSIRejectionEvidence.from_dict(observed.to_dict(), provenance_sha256=observed.provenance_sha256,
                                                  provenance_file_pin=observed.provenance_file_pin)
    if reparsed != expected or _canonical(observed.to_dict()) != raw:
        _fail("provenance_drift")
    _unchanged(self, held)
    return expected


def _readback(self, head: str, expected: dict[str, Any], payload: bytes, *, final: bool = False) -> None:
    from .rsi_controller import RSILearningController
    from .rsi_store import RSILedger

    held = _custody(self)
    _allowance(self)
    if final:
        for instance, expected_type, names in (
            (self._ledger, RSILedger, (
                "read_only_observations", "controller_checkpoint", "controller_checkpoint_history", "_connect",
                "_controller_checkpoint_history_tx", "_controller_checkpoint_history_observation_tx",
                "_checkpoint_python_references", "_checkpoint_digest",
                "_checkpoint_reference_rows_tx", "_python_admission_row", "controller_lock_held", "_assert_controller_lock")),
            (self._controller, RSILearningController, (
                "_python_admission_flow_payload", "_python_admission_assert_brs_wave", "_python_admission_brs_observations")),
        ):
            if type(instance) is not expected_type:
                _fail("final_reader_drift")
            attrs = object.__getattribute__(instance, "__dict__")
            if type(attrs) is not dict or any(name in attrs for name in names):
                _fail("final_reader_drift")
        with RSILedger.read_only_observations(self._ledger):
            history = RSILedger.controller_checkpoint_history(self._ledger, self._run_id)
    else:
        with self._ledger.read_only_observations():
            history = self._ledger.controller_checkpoint_history(self._run_id)
            observed = self._ledger.controller_checkpoint(self._run_id)
            lineage._validate_publication_lineage_checkpoint_readback(expected_head=head, expected_payload=payload,
                observed_head=None if observed is None else observed[0],
                observed_payload=None if observed is None else self._controller._python_admission_flow_payload(observed[1]))
            self._running()
            self._history(expected)
    c1 = self._rejection_c1_capture
    if (type(head) is not str or head == c1[0] or len(history) < 2
            or history[-2] != (c1[0], json.loads(c1[1])) or history[-1] != (head, expected)):
        _fail("readback_drift")
    lineage._validate_publication_lineage_checkpoint_readback(expected_head=head, expected_payload=payload,
        observed_head=history[-1][0], observed_payload=RSILearningController._python_admission_flow_payload(history[-1][1]))
    _unchanged(self, held)


def rejection_provenance_binding(self) -> RejectionLineageC1Binding:
    """Read original C1 data; never open a provenance scope or grant a permit."""
    _owner(self)
    try:
        _observe(self)
        evidence, _tables = _fresh(self)
        _observe(self)
        if self._phase == "rejected-provenance":
            _read_p(self)
        return evidence.lineage
    except BaseException:
        self._poisoned = True
        raise


def retain_rejection_provenance(self) -> None:
    """Create P once, hold its original publishing pin, and acknowledge C2."""
    from .rsi_brs_publication_lineage import _BRSLineageCheckpointOwner

    _owner(self)
    try:
        self._before_unlocked()
        if (self._phase != "rejected" or self._retaining_rejection_provenance is not False
                or self._rejection_provenance_deadline is not None or self._rejection_provenance_file_pin is not None
                or self._rejection_provenance_evidence is not None or self._rejection_provenance_sha256 is not None
                or self._rejection_provenance_c2_capture is not None):
            _fail("retention_unavailable")
        _capture(self)
        self._identity()
        held = _custody(self)
        started = time.monotonic()
        remaining = self._before_control_live()
        _unchanged(self, held)
        absolute = self._plan.deadline_unix - time.time()
        if type(absolute) is not float or not math.isfinite(absolute) or absolute <= 0:
            _fail("allowance_exhausted")
        if remaining is not None:
            if type(remaining) not in {int, float} or not math.isfinite(remaining) or remaining <= 0:
                _fail("allowance_exhausted")
            absolute = min(absolute, remaining)
        self._rejection_provenance_deadline = float(started + absolute)
        self._retaining_rejection_provenance = True
        _observe(self)
        evidence, tables = _fresh(self)
        self._rejection_provenance_evidence = _canonical(evidence.to_dict())
        _preflight(self, evidence, tables)
        _observe(self)
        _fresh(self)
        _policy_gate(self)
        held = _custody(self)
        digest, pin = persist_native_rsi_rejection_provenance(
            self._workspace / "evolution/producer-batches" / self._plan.journal_id,
            evidence, retained_bytes=evidence.lineage.retained_bytes)
        _unchanged(self, held)
        if type(digest) is not str or type(pin) is not NativeRSIRejectionFilePin:
            _fail("original_p_required")
        _dto_shape(pin)
        self._rejection_provenance_sha256, self._rejection_provenance_file_pin = digest, pin
        readback = _read_p(self)
        _BRSLineageCheckpointOwner.acknowledge_rejection_provenance(self, readback, pin)
    except BaseException:
        self._poisoned = True
        raise
    finally:
        self._retaining_rejection_provenance = False
        self._rejection_provenance_deadline = None


def acknowledge_rejection_provenance(self, evidence: NativeRSIRejectionEvidence,
                                     file_pin: NativeRSIRejectionFilePin) -> None:
    """CAS only inside this original owner's active create-only retain scope."""
    from .rsi_controller import RSILearningController

    _owner(self)
    try:
        self._before_unlocked()
        if (self._retaining_rejection_provenance is not True or self._phase != "rejected"
                or file_pin is not self._rejection_provenance_file_pin
                or type(evidence) is not NativeRSIRejectionEvidence or type(file_pin) is not NativeRSIRejectionFilePin):
            _fail("original_scope_required")
        _dto_shape(evidence)
        _dto_shape(file_pin)
        _observe(self)
        fresh, tables = _fresh(self)
        observed = _read_p(self)
        if (evidence != observed or _canonical(evidence.to_dict()) != self._rejection_provenance_evidence
                or evidence.lineage != fresh.lineage):
            _fail("ack_evidence_drift")
        wire = _wire(self, self._rejection_provenance_sha256, file_pin)
        _capacity(self, wire, tables)
        expected = lineage._publication_lineage_checkpoint_delta(self._rejection_c1_capture[1], wire)
        payload = self._controller._python_admission_flow_payload(expected)
        _observe(self)
        _fresh(self)
        _read_p(self)
        _policy_gate(self)
        held = _custody(self)
        # This C2 append has the same write-then-adopt gap as C1. Keep the
        # controller's transition marker live until the owner has installed the
        # matching in-memory head and state under the observation lock.
        with RSILearningController._python_admission_brs_checkpoint_transition(self._controller, self._wave):
            head = self._ledger.write_controller_checkpoint(self._run_id, expected,
                                                            expected_sha256=self._rejection_c1_capture[0])
            _unchanged(self, held)
            _control(self)
            _readback(self, head, expected, payload)
            _observe(self, expected)
            _fresh(self)
            _read_p(self)
            _policy_gate(self)
            _readback(self, head, expected, payload, final=True)
            held = _custody(self)
            # No callback or source/configuration hook follows the final material gate.
            with RSILearningController._python_admission_brs_observations(self._controller), self._before_channel_condition:
                RSILearningController._python_admission_assert_brs_wave(self._controller, self._wave, owner=True)
                _unchanged(self, held)
                self._before_channel()
                if (self._wave.state is not self._state or self._wave.selected_handoff is not self._handoff
                        or self._wave.selected_context is not self._selected_context
                        or (self._head, self._payload) != self._rejection_c1_capture
                        or self._wave.checkpoint_sha256 != self._head or self._wave.payload != self._payload
                        or self._controller.ledger is not self._ledger or self._controller.gateway is not self._gateway
                        or self._controller.producer_workspace is not self._workspace
                        or self._controller.producer_sidecar is not self._root_sidecar):
                    _fail("owner_drift")
                self._state[_FIELD] = json.loads(lineage._raw(wire))
                self._head, self._payload = head, payload
                self._wave.checkpoint_sha256, self._wave.payload = head, payload
                self._rejection_provenance_c2_capture = (head, payload)
                self._phase = "rejected-provenance"
    except BaseException:
        self._poisoned = True
        raise


def rejection_provenance_file_pin(self) -> NativeRSIRejectionFilePin:
    """Return only the independently held original P pin after confirmed C2."""
    _owner(self)
    try:
        if self._phase != "rejected-provenance" or self._retaining_rejection_provenance is not False:
            _fail("original_c2_required")
        _observe(self)
        _observe(self)
        _fresh(self)
        evidence = _read_p(self)
        reference = self._state[_FIELD]["batches"][self._ordinal]["rejection_provenance"]
        if reference != {"provenance_sha256": evidence.provenance_sha256,
                         "file_pin": self._rejection_provenance_file_pin.to_dict()}:
            _fail("original_p_drift")
        _policy_gate(self)
        _readback(self, self._head, self._state, self._payload, final=True)
        return self._rejection_provenance_file_pin
    except BaseException:
        self._poisoned = True
        raise


def _verify_reserved_rejected_materials(workspace, entry, *, ledger, roots, ordinal, prefix,
                                        original_lineage_bytes):
    """Reobserve settled C1/P/C2 and native receipts without requiring old live heads.

    A later successful batch may replace archive/state source inodes. Historical
    immutable snapshots and the actual adjacent ledger roots remain mandatory.
    """
    from . import producer_bundle_recovery as recovery
    from .producer_bundle_admission import parse_producer_bundle_admission_plan
    from .rsi_brs_lineage_prefix import BRSLineagePrefix
    from .rsi_brs_rejection_capacity import (
        _retained_reserved_brs_c1_c2_evidence_bytes,
    )
    from .rsi_brs_rejection_owner import (
        _read_rejection_tables_at,
        read_reserved_brs_material_tables,
    )
    from .rsi_brs_reserved_owner import _descriptor
    from .rsi_brs_reserved_rejection import (
        validate_reserved_brs_c1_transition,
        validate_reserved_brs_c2_transition,
        validate_reserved_brs_rejected_entry,
    )
    from .rsi_python_admission import validate_rsi_python_admission_shapes
    from .rsi_store import RSILedger

    if (type(ordinal) is not int or not 0 <= ordinal < 8 or type(ledger) is not RSILedger
            or type(prefix) is not BRSLineagePrefix or type(entry) is not dict
            or original_lineage_bytes is not None and type(original_lineage_bytes) is not bytes):
        _fail("historical_ordinal_drift")
    validate_rsi_python_admission_shapes(entry)
    if type(roots) is not list or not 1 <= len(roots) <= 4096:
        _fail("historical_root_snapshot_drift")
    for row in roots:
        if type(row) is not tuple or len(row) != 2 or type(row[0]) is not str or type(row[1]) is not dict:
            _fail("historical_root_snapshot_drift")
        validate_rsi_python_admission_shapes(row[1])
    workspace = recovery._workspace(workspace)
    if ordinal != len(prefix.batch_bytes) or entry.get("ordinal") != ordinal:
        _fail("historical_ordinal_drift")
    options = {"prefix": prefix, "original_lineage_bytes": original_lineage_bytes,
               "native_plan_sha256": entry["native_plan_sha256"]}
    rejected = validate_reserved_brs_rejected_entry(entry, prefix=prefix,
        native_plan_sha256=entry["native_plan_sha256"], with_provenance=True)
    reference = entry["rejection_provenance"]
    p_pin = NativeRSIRejectionFilePin.from_dict(reference["file_pin"])
    batch = recovery._batch(workspace, entry["journal_id"])
    evidence = read_native_rsi_rejection_provenance(batch, expected_file_pin=p_pin)
    prepared = parse_producer_bundle_publication_journal(entry["prepared_journal"])
    terminal = parse_producer_bundle_publication_journal(entry["rejected_journal"])
    plan = parse_producer_bundle_admission_plan(entry["admission_plan"])
    claim = RSILedger.inspect_native_episode_claim(ledger, evidence.plan.request,
                                                  plan_sha256=evidence.plan.plan_sha256)
    if (evidence.provenance_sha256 != reference["provenance_sha256"] or evidence.provenance_file_pin != p_pin
            or evidence.rejected != rejected or evidence.terminal != terminal
            or evidence.plan.plan_sha256 != entry["native_plan_sha256"]
            or evidence.plan.request_sha256 != entry["request_sha256"]
            or evidence.plan.memory_snapshot_sha256 != entry["memory_snapshot_sha256"]
            or evidence.plan.run_id != rejected.run_id or evidence.plan.journal_id != entry["journal_id"]
            or evidence.plan.request.episode_id != entry["episode_id"]
            or claim is None or claim.claim_sha256 != evidence.claim.claim_sha256
            or claim.created_at != evidence.claim.created_at
            or dict(evidence.ledger_identity) != _read_ledger_identity(ledger)
            or terminal.admission_sha256 != plan.digest() or prepared.admission_sha256 != plan.digest()):
        _fail("historical_provenance_drift")
    history = RSILedger.controller_checkpoint_history(ledger, rejected.run_id)
    if roots != history:
        _fail("historical_root_snapshot_drift")
    matches = [index for index, (head, _body) in enumerate(history)
               if head == evidence.lineage.checkpoint_sha256]
    if len(matches) != 1 or not 0 < matches[0] < len(history) - 1:
        _fail("historical_checkpoint_drift")
    index = matches[0]
    before_state, c1_state, c2_state = (history[item][1] for item in (index - 1, index, index + 1))
    c1_wire, c2_wire = c1_state.get(_FIELD), c2_state.get(_FIELD)
    validate_reserved_brs_c1_transition(before_state.get(_FIELD), c1_wire, **options)
    validate_reserved_brs_c2_transition(c1_wire, c2_wire, **options)
    if (c2_wire["batches"][ordinal] != entry
            or any(body.get(_FIELD, {}).get("batches", [])[:ordinal + 1] != c2_wire["batches"]
                   for _head, body in history[index + 1:])):
        _fail("historical_entry_drift")
    for previous, current, wire in ((before_state, c1_state, c1_wire), (c1_state, c2_state, c2_wire)):
        if _canonical({**previous, _FIELD: wire}) != \
                _canonical(current):
            _fail("historical_checkpoint_delta_drift")

    def observe():
        if (_descriptor(workspace, entry, "before")["descriptor"] != entry["before"]
                or read_lineage_v2_descriptor_pinned(workspace, entry["journal_id"], kind="rejected",
                    expected_file_pin=LineageSnapshotPin.from_dict(entry["rejected_file_pin"])) != rejected):
            _fail("historical_descriptor_drift")
        for name, raw in entry["evidence_pins"].items():
            verify_persisted_lineage_snapshot(batch / name, LineageSnapshotPin.from_dict(raw))
        recovery._verify_python_handoff(batch, prepared, plan)
        recovery._verify_python_handoff(batch, terminal, plan)
        if recovery._read_journal(batch / "journal.prepared.json") != prepared:
            _fail("historical_prepared_drift")
        result = []
        for name in ("archive-before", "state-before"):
            pin = LineageSnapshotPin.from_dict(entry["snapshots"][name])
            path = batch / "lineage" / (name + ".snapshot")
            verify_persisted_lineage_snapshot(path, pin)
            result.append(_files.read_regular_file(path, lineage.MAX_LINEAGE_SNAPSHOT_BYTES))
            verify_persisted_lineage_snapshot(path, pin)
        return tuple(result)

    archive, state_bytes = observe()
    observed = _verify_terminal_batch_rejection_evidence(workspace, batch, prepared, terminal=terminal)
    tables = _read_rejection_tables_at(workspace, entry)
    all_rejected, all_published = read_reserved_brs_material_tables(workspace, c1_wire)
    actual, _c2_actual = _retained_reserved_brs_c1_c2_evidence_bytes(
        c1_state, c1_wire, c2_wire, all_rejected, all_published, **options)
    binding = RejectionLineageC1Binding(run_id=rejected.run_id, episode_id=entry["episode_id"],
        journal_id=entry["journal_id"], ordinal=ordinal, checkpoint_sha256=history[index][0],
        rejected_sha256=rejected.digest(), retained_bytes=actual,
        **{name: getattr(rejected, name) for name in (
            "before_sha256", "prepared_journal_sha256", "terminal_journal_sha256", "rejection_manifest_sha256",
            "terminal_marker_sha256", "candidate_ids", "archive_sha256", "state_sha256")})
    if (evidence.lineage != binding or observed.terminal != terminal
            or observed.manifest_sha256 != rejected.rejection_manifest_sha256
            or observed.candidate_ids != rejected.candidate_ids
            or observed.execution_receipt_sha256s != evidence.execution_receipt_sha256s
            or observed.evaluation_receipt_sha256s != evidence.evaluation_receipt_sha256s
            or observed.retained_evidence_sha256s != evidence.retained_evidence_sha256s
            or _read_rejection_tables_at(workspace, entry) != tables or observe() != (archive, state_bytes)
            or read_native_rsi_rejection_provenance(batch, expected_file_pin=p_pin) != evidence
            or dict(evidence.ledger_identity) != _read_ledger_identity(ledger)):
        _fail("historical_native_material_drift")
    if RSILedger.controller_checkpoint_history(ledger, rejected.run_id) != history:
        _fail("historical_root_snapshot_drift")
    return archive, state_bytes, evidence, terminal


def verify_reserved_rejected_history(self, entry, *, ordinal, prefix, original_lineage_bytes, roots=None):
    """Validate immutable historical material without reusing old live source heads."""
    from .rsi_store import RSILedger

    if roots is None:
        roots = RSILedger.controller_checkpoint_history(self._ledger, self._run_id)
    archive, state, _evidence, _terminal = _verify_reserved_rejected_materials(self._workspace, entry,
        ledger=self._ledger, roots=roots,
        ordinal=ordinal, prefix=prefix, original_lineage_bytes=original_lineage_bytes)
    return archive, state


def verify_reserved_rejected_publication(workspace, publication, binding, roots, *, ledger, ordinal,
                                         prefix, original_lineage_bytes):
    """Read a genuine selected reserved rejection without constructing any owner."""
    from .rsi_store import RSILedger

    if type(ledger) is not RSILedger:
        _fail("historical_ledger_invalid")
    with RSILedger.read_only_observations(ledger):
        return _verify_reserved_rejected_publication(workspace, publication, binding, roots,
            ledger=ledger, ordinal=ordinal, prefix=prefix, original_lineage_bytes=original_lineage_bytes)


def _verify_reserved_rejected_publication(workspace, publication, binding, roots, *, ledger, ordinal,
                                          prefix, original_lineage_bytes):
    from . import producer_bundle_recovery as recovery
    from .rsi_python_admission import validate_rsi_python_admission_shapes

    validate_rsi_python_admission_shapes(publication)
    validate_rsi_python_admission_shapes(binding)
    if (type(ordinal) is not int or not 0 <= ordinal < 8 or type(publication) is not dict
            or type(binding) is not dict
            or publication.get("manifest") is not None or type(publication.get("lineage")) is not dict
            or type(publication["lineage"].get("batches")) is not list
            or len(publication["lineage"]["batches"]) != ordinal + 1):
        _fail("historical_publication_invalid")
    wire = publication["lineage"]
    entry = wire["batches"][ordinal]
    archive, state, evidence, terminal = _verify_reserved_rejected_materials(workspace, entry,
        ledger=ledger, roots=roots, ordinal=ordinal, prefix=prefix, original_lineage_bytes=original_lineage_bytes)
    c1_index = next(index for index, (head, _body) in enumerate(roots)
                    if head == evidence.lineage.checkpoint_sha256)
    if (wire != roots[c1_index + 1][1].get(_FIELD)
            or terminal.to_dict() != publication.get("journal")
            or evidence.plan.run_id != binding.get("run_id")
            or entry["episode_id"] != binding.get("episode_id")
            or entry["request_sha256"] != binding.get("selected_request_sha256")
            or entry["native_plan_sha256"] != binding.get("native_plan_sha256")
            or evidence.claim.claim_sha256 != binding.get("native_claim_sha256")):
        _fail("historical_publication_binding_drift")
    # A selected latest suffix still names the live untouched prepublication
    # sources. Historical closed entries may have later successful successors.
    later_append = any(type(body.get(_FIELD)) is dict
        and len(body[_FIELD].get("batches", [])) > ordinal + 1 for _head, body in roots)
    if not later_append:
        root = recovery._workspace(workspace)
        for name, raw in entry["before_sources"].items():
            path = root / "evolution" / ("archive.jsonl" if name == "archive" else "state.json")
            if type(raw) is dict and raw.get("missing") is True:
                if (set(raw) != {"missing", "parent"} or name != "archive"
                        or raw["parent"] != lineage._root_pin(path.parent) or archive != b""):
                    _fail("historical_live_source_drift")
                try:
                    path.lstat()
                except FileNotFoundError:
                    pass
                else:
                    _fail("historical_live_source_drift")
            else:
                verify_persisted_lineage_snapshot(path, LineageSnapshotPin.from_dict(raw))
        if (lineage._sha(archive) != evidence.rejected.archive_sha256
                or lineage._sha(state) != evidence.rejected.state_sha256):
            _fail("historical_live_source_drift")
    return terminal.digest()
