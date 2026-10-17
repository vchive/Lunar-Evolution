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
    rejected_c1_entry,
    validate_rejected_provenance_transition,
)
from .rsi_brs_rejection_capacity import (
    retained_brs_c1_evidence_bytes,
    retained_brs_c2_evidence_bytes,
)
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


def _capture(self) -> tuple[dict[str, Any], dict[str, Any]]:
    """Use only the independently held successful original C1 capture."""
    capture = self._rejection_c1_capture
    if (type(capture) is not tuple or len(capture) != 2 or type(capture[0]) is not str
            or type(capture[1]) is not bytes or self._phase not in {"rejected", "rejected-provenance"}):
        _fail("original_c1_required")
    state = json.loads(capture[1])
    if self._controller._python_admission_flow_payload(state) != capture[1]:
        _fail("original_c1_drift")
    wire = state.get(_FIELD)
    if type(wire) is not dict or type(wire.get("batches")) is not list or len(wire["batches"]) != 1:
        _fail("original_c1_drift")
    entry = wire["batches"][0]
    rejected_c1_entry(entry)
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
        validate_rejected_provenance_transition(wire, self._state.get(_FIELD))
        expected = lineage._publication_lineage_checkpoint_delta(capture[1], self._state[_FIELD])
        if self._controller._python_admission_flow_payload(expected) != c2[1]:
            _fail("original_c2_drift")
    return state, wire


def _custody(self) -> tuple[Any, ...]:
    return (self._rejection_c1_capture, self._rejection_file_pin, self._rejection_ledger_identity,
            self._rejection_provenance_deadline, self._rejection_provenance_evidence,
            self._rejection_provenance_sha256, self._rejection_provenance_file_pin,
            self._rejection_provenance_c2_capture)


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
    tables = {}
    for candidate_id in rejected_c1_entry(entry).candidate_ids:
        name = "rejections/" + candidate_id + ".json"
        pin = LineageSnapshotPin.from_dict(entry["evidence_pins"][name])
        verify_persisted_lineage_snapshot(batch / name, pin)
        value = json.loads(_files.read_regular_file(batch / name, lineage.MAX_LINEAGE_SNAPSHOT_BYTES))
        if type(value) is not dict or type(value.get("retained_evidence")) is not dict:
            _fail("material_invalid")
        tables[candidate_id] = value["retained_evidence"]
        verify_persisted_lineage_snapshot(batch / name, pin)
    return tables


def _fresh(self) -> tuple[NativeRSIRejectionEvidence, dict[str, Any]]:
    """Rebuild evidence from original live native inputs, receipts and C1 files."""
    held = _custody(self)
    _allowance(self)
    state, wire = _capture(self)
    entry = wire["batches"][0]
    rejected = rejected_c1_entry(entry)
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
    actual = retained_brs_c1_evidence_bytes(state, wire, tables)
    binding = RejectionLineageC1Binding(
        run_id=self._run_id, episode_id=self._request.episode_id, journal_id=self._plan.journal_id, ordinal=0,
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
    wire["batches"][0]["rejection_provenance"] = {"provenance_sha256": digest, "file_pin": pin.to_dict()}
    validate_rejected_provenance_transition(state[_FIELD], wire)
    return wire


def _capacity(self, wire: dict[str, Any], tables: dict[str, Any]) -> None:
    state, _original = _capture(self)
    retained_brs_c2_evidence_bytes(state, wire, tables)
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
                "_controller_checkpoint_history_tx", "_checkpoint_python_references", "_checkpoint_digest",
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
        _fixed(self)
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
        _fixed(self)
        _fresh(self)
        _read_p(self)
        _policy_gate(self)
        held = _custody(self)
        head = self._ledger.write_controller_checkpoint(self._run_id, expected,
                                                       expected_sha256=self._rejection_c1_capture[0])
        _unchanged(self, held)
        _control(self)
        _readback(self, head, expected, payload)
        _observe(self, expected)
        _fixed(self, expected)
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
                    or self._controller.producer_sidecar is not self._sidecar):
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
        reference = self._state[_FIELD]["batches"][0]["rejection_provenance"]
        if reference != {"provenance_sha256": evidence.provenance_sha256,
                         "file_pin": self._rejection_provenance_file_pin.to_dict()}:
            _fail("original_p_drift")
        _policy_gate(self)
        _readback(self, self._head, self._state, self._payload, final=True)
        return self._rejection_provenance_file_pin
    except BaseException:
        self._poisoned = True
        raise
