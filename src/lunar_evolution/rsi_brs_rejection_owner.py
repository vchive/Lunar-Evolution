"""Original BRS rejection C1 retention and CAS; no reconstruction or execution."""

from __future__ import annotations

import json
import math
import time
from dataclasses import replace
from typing import Any

from . import _benchmark_files as _files
from . import producer_bundle_recovery as recovery
from . import rsi_publication_lineage as lineage
from .producer_bundle_lineage import (
    LineageSnapshotPin,
    capture_lineage_snapshot_pin,
    verify_persisted_lineage_snapshot,
)
from .producer_bundle_lineage_v2 import (
    ProducerLineageRejectedTerminalV2,
    persist_lineage_v2_descriptor,
    read_lineage_v2_descriptor_pinned,
)
from .producer_bundle_publication import parse_producer_bundle_publication_journal
from .rsi_learning import RSILearningError

_FIELD = "producer_publication_lineage"


def _fail(reason: str) -> None:
    raise RSILearningError("rsi_brs_publication_lineage_" + reason)


def _rejection_scope(self) -> None:
    if (self._retaining_rejection is not True or self._retaining_before is not False
            or self._retaining_success is not None or self._success_deadline is not None
            or self._phase != "prepared-evidence"):
        _fail("rejected_retention_scope_drift")

def _rejection_allowance(self) -> None:
    """Check only original cancellation pins and the bounded numeric allowance."""
    self._rejection_scope()
    if self._before_control_state() != self._before_control_pin:
        _fail("before_control_drift")
    if self._before_control is not None:
        with self._before_control._lock:
            if self._before_control._cancelled is not False:
                _fail("before_control_cancelled")
    if self._rejection_deadline is not None:
        if type(self._rejection_deadline) is not float or not math.isfinite(self._rejection_deadline):
            _fail("rejected_allowance_drift")
        if time.monotonic() >= self._rejection_deadline:
            _fail("rejected_allowance_exhausted")

def _rejection_cap_unchanged(self, allowance: float | None, file_pin: LineageSnapshotPin | None) -> None:
    """Preserve independently held original cap/pin objects across observations."""
    if ((allowance is not None and (type(allowance) is not float or not math.isfinite(allowance)))
            or (file_pin is not None and type(file_pin) is not LineageSnapshotPin)
            or self._rejection_deadline is not allowance or self._rejection_file_pin is not file_pin):
        _fail("rejected_allowance_drift")
    self._rejection_allowance()


def _rejection_control_live(self, started: float) -> None:
    allowance, file_pin = self._rejection_deadline, self._rejection_file_pin
    self._rejection_cap_unchanged(allowance, file_pin)
    remaining = self._before_control_live()
    self._rejection_scope()
    self._rejection_cap_unchanged(allowance, file_pin)
    if remaining is not None:
        deadline = started + remaining
        self._rejection_deadline = deadline if allowance is None else min(allowance, deadline)
    self._rejection_cap_unchanged(self._rejection_deadline, file_pin)

def _rejection_fixed(self) -> None:
    allowance, file_pin = self._rejection_deadline, self._rejection_file_pin
    self._rejection_cap_unchanged(allowance, file_pin)
    self._identity()
    with self._ledger.read_only_observations():
        self._running()
        self._controller._python_admission_active_brs_owner(self._wave)
        self._history()
    self._before_channel()
    self._rejection_cap_unchanged(allowance, file_pin)

def _rejection_observe(self) -> None:
    """Observe full original source/control hooks outside workspace locks."""
    self._before_unlocked()
    self._rejection_scope()
    allowance = self._rejection_deadline
    file_pin = self._rejection_file_pin
    started = time.monotonic()
    self._check_owner()
    self._rejection_scope()
    self._rejection_cap_unchanged(allowance, file_pin)
    self._rejection_control_live(started)
    self._rejection_fixed()

def _rejection_terminal(self, entry, *, with_provenance=False):
    """Use the explicitly retained reserved context or the unchanged genesis parser."""
    if self._reserved_prefix is not None:
        from .rsi_brs_reserved_owner import reserved_prefix_identity
        from .rsi_brs_reserved_rejection import validate_reserved_brs_rejected_entry

        reserved_prefix_identity(self)
        return validate_reserved_brs_rejected_entry(entry, prefix=self._reserved_prefix,
            native_plan_sha256=self._plan.plan_sha256, with_provenance=with_provenance)
    from .rsi_brs_rejection_c1 import rejected_c1_entry, rejected_provenance_entry

    return (rejected_provenance_entry if with_provenance else rejected_c1_entry)(entry)


def read_reserved_brs_material_tables(workspace, wire):
    """Read actual native tables without constructing or borrowing an owner."""
    from .rsi_brs_reserved_owner import read_reserved_published_materials
    from .rsi_python_admission import validate_rsi_python_admission_shapes

    validate_rsi_python_admission_shapes(wire)
    workspace = recovery._workspace(workspace)
    if (type(wire) is not dict or type(wire.get("batches")) is not list
            or not 1 <= len(wire["batches"]) <= 8):
        _fail("rejected_capacity_scope_invalid")
    rejected, published = {}, {}
    for entry in wire["batches"]:
        if type(entry) is not dict or type(entry.get("journal_id")) is not str:
            _fail("rejected_capacity_scope_invalid")
        if entry["journal_id"] in rejected or entry["journal_id"] in published:
            _fail("rejected_capacity_scope_invalid")
        if entry["state"] == "rejected":
            rejected[entry["journal_id"]] = _read_rejection_tables_at(workspace, entry)
        elif entry["state"] == "terminal":
            published[entry["journal_id"]] = read_reserved_published_materials(workspace, entry)
        else:
            _fail("rejected_capacity_scope_invalid")
    return rejected, published


def _reserved_material_tables(self, wire, active_tables=None):
    """Reobserve all native tables without dropping any historical wire entry."""
    rejected, published = read_reserved_brs_material_tables(self._workspace, wire)
    if active_tables is not None and rejected.get(self._plan.journal_id) != active_tables:
        _fail("rejected_material_drift")
    return rejected, published


def _rejection_retained_bytes(self, state, wire, tables, *, c2=False):
    from . import rsi_brs_rejection_capacity as capacity
    from .rsi_brs_reserved_owner import reserved_prefix_identity

    if type(self._ordinal) is not int or not 0 <= self._ordinal < 8:
        _fail("rejected_ordinal_invalid")
    reserved_prefix_identity(self)
    if self._reserved_prefix is None:
        counter = capacity.retained_brs_c2_evidence_bytes if c2 else capacity.retained_brs_c1_evidence_bytes
        return counter(state, wire, tables)
    rejected, published = _reserved_material_tables(self, wire, tables)
    counter = (capacity._retained_reserved_brs_c2_evidence_bytes if c2 else
               capacity._retained_reserved_brs_c1_evidence_bytes)
    return counter(state, wire, rejected, published, prefix=self._reserved_prefix,
        original_lineage_bytes=self._reserved_lineage_bytes, native_plan_sha256=self._plan.plan_sha256)


def _read_rejection_tables_at(workspace, entry):
    """Observe original pinned files; this reader grants no retention scope."""
    from .rsi_python_admission import validate_rsi_python_admission_shapes

    validate_rsi_python_admission_shapes(entry)
    rejected = ProducerLineageRejectedTerminalV2.from_dict(entry["rejected"])
    batch = recovery._batch(workspace, entry["journal_id"])
    tables = {}
    for candidate_id in rejected.candidate_ids:
        name = "rejections/" + candidate_id + ".json"
        pin = LineageSnapshotPin.from_dict(entry["evidence_pins"][name])
        verify_persisted_lineage_snapshot(batch / name, pin)
        value = json.loads(_files.read_regular_file(batch / name, lineage.MAX_LINEAGE_SNAPSHOT_BYTES))
        if type(value) is not dict or type(value.get("retained_evidence")) is not dict:
            _fail("rejected_material_invalid")
        tables[candidate_id] = value["retained_evidence"]
        verify_persisted_lineage_snapshot(batch / name, pin)
    return tables

def _read_rejection_tables(self, entry):
    return _read_rejection_tables_at(self._workspace, entry)



def _rejection_materials(self, entry: dict[str, Any]) -> dict[str, Any]:
    """Read immutable native tables inside this original C1 retention scope."""
    allowance, file_pin = self._rejection_deadline, self._rejection_file_pin
    self._rejection_cap_unchanged(allowance, file_pin)
    _rejection_terminal(self, entry)
    tables = _read_rejection_tables(self, entry)
    self._rejection_cap_unchanged(allowance, file_pin)
    return tables


def _rejection_capacity(self, wire: dict[str, Any], tables: dict[str, Any]) -> int:
    allowance, file_pin = self._rejection_deadline, self._rejection_file_pin
    self._rejection_cap_unchanged(allowance, file_pin)
    actual = _rejection_retained_bytes(self, self._state, wire, tables)
    projected = json.loads(lineage._raw(wire))
    maximum = 2**64 - 1
    pin = projected["batches"][self._ordinal]["rejected_file_pin"]
    pin.update({name: maximum for name in
                ("device", "inode", "parent_device", "parent_inode", "mtime_ns", "ctime_ns")})
    lineage._raw(lineage._publication_lineage_checkpoint_delta(self._payload, projected))
    self._rejection_cap_unchanged(allowance, file_pin)
    return actual

def _rejected_entry(self, wire: object, *, fixed: bool = False) -> dict[str, Any]:
    from .producer_bundle_rejection import _verify_terminal_batch_rejection_evidence
    from .rsi_brs_rejection_c1 import (
        REJECTION_SCHEMA,
        validate_rejected_c1_transition,
    )
    from .rsi_python_admission import validate_rsi_python_admission_shapes

    allowance, file_pin = self._rejection_deadline, self._rejection_file_pin
    self._rejection_cap_unchanged(allowance, file_pin)
    validate_rsi_python_admission_shapes(wire)
    if type(fixed) is not bool:
        _fail("rejected_invalid")
    if fixed:
        self._strategy_identity()
    else:
        self._native_strategy()
    self._rejection_cap_unchanged(allowance, file_pin)
    if (self._native is None or self._plan.task_id != self._request.episode_id
            or json.loads(self._policy_bytes).get("rejection_schema") != REJECTION_SCHEMA
            or type(file_pin) is not LineageSnapshotPin):
        _fail("rejected_original_retention_required")
    detached = json.loads(lineage._raw(wire))
    original = json.loads(self._payload).get(_FIELD)
    if self._reserved_prefix is None:
        validate_rejected_c1_transition(original, detached)
    else:
        from .rsi_brs_reserved_rejection import validate_reserved_brs_c1_transition

        validate_reserved_brs_c1_transition(original, detached, prefix=self._reserved_prefix,
            original_lineage_bytes=self._reserved_lineage_bytes, native_plan_sha256=self._plan.plan_sha256)
    if original != self._state.get(_FIELD):
        _fail("rejected_delta_invalid")
    self._before_entry(original)
    entry = detached["batches"][self._ordinal]
    rejected = _rejection_terminal(self, entry)
    if (LineageSnapshotPin.from_dict(entry["rejected_file_pin"]) != file_pin
            or parse_producer_bundle_publication_journal(entry["prepared_journal"]) != self._prepared):
        _fail("rejected_original_retention_required")
    observed_descriptor = read_lineage_v2_descriptor_pinned(self._workspace, entry["journal_id"],
        kind="rejected", expected_file_pin=file_pin)
    if observed_descriptor != rejected:
        _fail("rejected_descriptor_drift")
    archive = self._snapshot_bytes(entry["journal_id"], entry["snapshots"]["archive-before"], name="archive-before")
    state_bytes = self._snapshot_bytes(entry["journal_id"], entry["snapshots"]["state-before"], name="state-before")
    self._live_before(archive, state_bytes)
    batch = recovery._batch(self._workspace, self._plan.journal_id)
    for name, raw in entry["evidence_pins"].items():
        verify_persisted_lineage_snapshot(batch / name, LineageSnapshotPin.from_dict(raw))
    tables = self._rejection_materials(entry)
    terminal = parse_producer_bundle_publication_journal(entry["rejected_journal"])
    observed = _verify_terminal_batch_rejection_evidence(self._workspace, batch, self._prepared, terminal=terminal)
    self._rejection_cap_unchanged(allowance, file_pin)
    if (observed.terminal != terminal or observed.candidate_ids != rejected.candidate_ids
            or observed.manifest_sha256 != rejected.rejection_manifest_sha256
            or observed.terminal.digest() != rejected.terminal_journal_sha256
            or observed.terminal.terminal_marker_sha256 != rejected.terminal_marker_sha256
            or self._rejection_materials(entry) != tables):
        _fail("rejected_evidence_drift")
    for name, raw in entry["evidence_pins"].items():
        verify_persisted_lineage_snapshot(batch / name, LineageSnapshotPin.from_dict(raw))
    self._rejection_capacity(detached, tables)
    lineage.RSIPublicationLineage._verify_before_source_pins(self, entry)
    self._live_before(archive, state_bytes)
    if read_lineage_v2_descriptor_pinned(self._workspace, entry["journal_id"],
            kind="rejected", expected_file_pin=file_pin) != rejected:
        _fail("rejected_descriptor_drift")
    self._rejection_cap_unchanged(allowance, file_pin)
    return detached

def retain_rejected_terminal(self, terminal: Any) -> None:
    """Retain original verified all-rejected C1; never dispatch, settle or add provenance."""
    from .producer_bundle_publication import ProducerBundlePublicationJournal
    from .producer_bundle_rejection import _verify_terminal_batch_rejection_evidence
    from .rsi_brs_publication_lineage import _BRSLineageCheckpointOwner
    from .rsi_brs_rejection_c1 import REJECTION_SCHEMA

    if type(self) is not _BRSLineageCheckpointOwner:
        _fail("owner_invalid")
    try:
        self._before_unlocked()
        lineage._publication_shapes(terminal)
        if (type(terminal) is not ProducerBundlePublicationJournal or terminal.state != "all_rejected"
                or terminal.journal_id != self._plan.journal_id or self._phase != "prepared-evidence"
                or self._retaining_rejection is not False or self._rejection_deadline is not None
                or self._rejection_file_pin is not None or self._retaining_before is not False
                or self._retaining_success is not None or self._success_deadline is not None
                or json.loads(self._policy_bytes).get("rejection_schema") != REJECTION_SCHEMA
                or self._native is None or self._plan.task_id != self._request.episode_id
                or self._rejection_c1_capture is not None or self._retaining_rejection_provenance is not False
                or self._rejection_provenance_file_pin is not None):
            _fail("rejected_retention_unavailable")
        self._retaining_rejection = True
        self._rejection_observe()
        allowance, original_pin = self._rejection_deadline, self._rejection_file_pin
        self._rejection_cap_unchanged(allowance, original_pin)
        wire = self._before_entry(json.loads(self._payload)[_FIELD])
        entry = wire["batches"][self._ordinal]
        if set(entry["evidence_pins"]) != {"journal.prepared.json"}:
            _fail("rejected_prepared_evidence_required")
        before = self._verify_descriptor(entry, "before")
        archive = self._snapshot_bytes(entry["journal_id"], entry["snapshots"]["archive-before"], name="archive-before")
        state_bytes = self._snapshot_bytes(entry["journal_id"], entry["snapshots"]["state-before"], name="state-before")
        self._live_before(archive, state_bytes)
        batch = recovery._batch(self._workspace, self._plan.journal_id)
        observed = _verify_terminal_batch_rejection_evidence(self._workspace, batch, self._prepared, terminal=terminal)
        self._rejection_cap_unchanged(allowance, original_pin)
        names = ("journal.json", "rejections.json", *("rejections/" + item + ".json" for item in observed.candidate_ids))
        pins = {name: capture_lineage_snapshot_pin(batch / name,
            name="rejection-" + lineage._sha(name.encode()) if name.startswith("rejections/") else name).to_dict()
            for name in names}
        if _verify_terminal_batch_rejection_evidence(
                self._workspace, batch, self._prepared, terminal=terminal) != observed:
            _fail("rejected_evidence_drift")
        self._rejection_cap_unchanged(allowance, original_pin)
        rejected = ProducerLineageRejectedTerminalV2(self._run_id, self._plan.journal_id,
            self._request.episode_id, self._ordinal, before.digest(), self._prepared.digest(), terminal.digest(),
            observed.manifest_sha256, terminal.terminal_marker_sha256, observed.candidate_ids,
            lineage._sha(archive), lineage._sha(state_bytes))
        maximum = 2**64 - 1
        capacity_pin = replace(LineageSnapshotPin.from_dict(entry["before_file_pin"]),
            name="rejected.json", sha256=lineage._sha(rejected.to_json()), size=len(rejected.to_json()),
            **{name: maximum for name in ("device", "inode", "parent_device", "parent_inode", "mtime_ns", "ctime_ns")})
        entry.update(state="rejected", rejection_schema=REJECTION_SCHEMA, rejected=rejected.to_dict(),
            rejected_file_pin=capacity_pin.to_dict(), rejected_journal=terminal.to_dict(), rejection_provenance=None)
        entry["evidence_pins"].update(pins)
        wire["rejections"] = [*wire["rejections"], {"ordinal": self._ordinal,
            "journal_id": rejected.journal_id, "rejected_sha256": rejected.digest()}]
        tables = self._rejection_materials(entry)
        self._rejection_capacity(wire, tables)
        self._rejection_cap_unchanged(allowance, original_pin)
        self._rejection_observe()
        allowance, original_pin = self._rejection_deadline, self._rejection_file_pin
        self._rejection_cap_unchanged(allowance, original_pin)
        lineage.RSIPublicationLineage._verify_before_source_pins(self, entry)
        for name, raw in entry["evidence_pins"].items():
            verify_persisted_lineage_snapshot(batch / name, LineageSnapshotPin.from_dict(raw))
        if (_verify_terminal_batch_rejection_evidence(
                self._workspace, batch, self._prepared, terminal=terminal) != observed
                or self._rejection_materials(entry) != tables):
            _fail("rejected_evidence_drift")
        self._rejection_cap_unchanged(allowance, original_pin)
        self._live_before(archive, state_bytes)
        self._rejection_fixed()
        self._rejection_cap_unchanged(allowance, original_pin)
        _path, pin = persist_lineage_v2_descriptor(self._workspace, rejected)
        self._rejection_cap_unchanged(allowance, original_pin)
        if (type(pin) is not LineageSnapshotPin or read_lineage_v2_descriptor_pinned(
                self._workspace, self._plan.journal_id, kind="rejected", expected_file_pin=pin) != rejected):
            _fail("rejected_descriptor_drift")
        self._rejection_cap_unchanged(allowance, original_pin)
        self._rejection_file_pin = pin
        entry["rejected_file_pin"] = pin.to_dict()
        _BRSLineageCheckpointOwner.checkpoint_rejected(self, wire)
    except BaseException:
        self._poisoned = True
        raise
    finally:
        self._retaining_rejection = False
        self._rejection_deadline = None

def _rejection_readback(self, head: str, expected: dict[str, Any], payload: bytes) -> None:
    """Require exactly one adjacent C1 checkpoint, without adopting any later head."""
    allowance, file_pin = self._rejection_deadline, self._rejection_file_pin
    self._rejection_cap_unchanged(allowance, file_pin)
    with self._ledger.read_only_observations():
        history = self._ledger.controller_checkpoint_history(self._run_id)
        if (type(head) is not str or head == self._head or len(history) < 2
                or history[-2] != (self._head, json.loads(self._payload))
                or history[-1] != (head, expected)):
            _fail("rejected_readback_invalid")
        observed = self._ledger.controller_checkpoint(self._run_id)
        lineage._validate_publication_lineage_checkpoint_readback(expected_head=head, expected_payload=payload,
            observed_head=None if observed is None else observed[0],
            observed_payload=None if observed is None else self._controller._python_admission_flow_payload(observed[1]))
        self._running()
        self._history(expected)
    self._rejection_cap_unchanged(allowance, file_pin)


def _rejection_readback_observe(self, expected: dict[str, Any]) -> None:
    """Repeat original source/configuration observations with durable new/local old."""
    from .rsi_budget import RSIRunBudget
    from .rsi_controller import _record_digest
    from .rsi_fingerprint import RSIFingerprintContract, ensure_fingerprint_compatible

    self._before_unlocked()
    allowance, file_pin = self._rejection_deadline, self._rejection_file_pin
    self._rejection_cap_unchanged(allowance, file_pin)
    started = time.monotonic()
    self._identity()
    captured = json.loads(self._payload)
    with self._ledger.read_only_observations():
        self._running()
        original = self._ledger.history(self._run_id)[0]
        actual, _ = self._controller._run_fingerprint(
            **captured["pins"], memory_snapshot_sha256=self._memory.digest(),
            mode=captured["mode"], plan=captured["plan"])
        self._rejection_cap_unchanged(allowance, file_pin)
        ensure_fingerprint_compatible(
            RSIFingerprintContract.from_dict(original.payload["fingerprints"]["run_fingerprint"]), actual)
        run = self._ledger.get_run(self._run_id)
        self._controller._validate_original_run_checkpoint_producer_binding(run, expected)
        self._controller._validate_python_admission_references(self._run_id, expected)
        self._controller._validate_producer_staging(run, expected)
        self._history(expected)
    self._rejection_cap_unchanged(allowance, file_pin)
    budget = RSIRunBudget.load(captured["budget_state"])
    budget.assert_matches(original.payload["budget"])
    budget.check()
    policy = {
        "plan": captured["plan"], "pins": captured["pins"], "planned": budget.to_dict()["planned"],
        "producer_checkpoint_binding": captured.get("producer_checkpoint_binding"),
        "solver_settings": actual.to_dict()["solver_settings"],
    }
    control = {"budget_state": budget.to_dict(), "status": captured["status"]}
    context = self._selected_context
    if (actual.digest() != context.source_sha256 or _record_digest(policy) != context.policy_sha256
            or _record_digest(control) != context.execution_control_sha256):
        _fail("rejected_readback_authority_drift")
    self._identity()
    self._native_strategy()
    self._before_channel()
    self._rejection_cap_unchanged(allowance, file_pin)
    self._rejection_control_live(started)


def _rejection_final_readback(self, head: str, expected: dict[str, Any], payload: bytes) -> None:
    """Use only the canonical read graph after the final source/material observation."""
    from .rsi_brs_publication_lineage import _BRSLineageCheckpointOwner
    from .rsi_controller import RSILearningController
    from .rsi_store import RSILedger

    # Earlier readbacks deliberately exercise the live observation seams. No
    # instance callback may run after the final material/source verification.
    if type(self) is not _BRSLineageCheckpointOwner:
        _fail("owner_invalid")
    for instance, expected_type, names in (
        (self._ledger, RSILedger, (
            "read_only_observations", "controller_checkpoint", "controller_checkpoint_history", "_connect",
            "_controller_checkpoint_history_tx", "_checkpoint_python_references", "_checkpoint_digest",
            "_checkpoint_reference_rows_tx", "_python_admission_row", "controller_lock_held", "_assert_controller_lock",
        )),
        (self._controller, RSILearningController, (
            "_python_admission_flow_payload", "_python_admission_assert_brs_wave", "_python_admission_brs_observations",
        )),
    ):
        if type(instance) is not expected_type:
            _fail("rejected_final_reader_drift")
        attributes = object.__getattribute__(instance, "__dict__")
        if type(attributes) is not dict or any(name in attributes for name in names):
            _fail("rejected_final_reader_drift")
    allowance, file_pin = self._rejection_deadline, self._rejection_file_pin
    self._rejection_cap_unchanged(allowance, file_pin)
    with RSILedger.read_only_observations(self._ledger):
        history = RSILedger.controller_checkpoint_history(self._ledger, self._run_id)
    if (type(head) is not str or head == self._head or len(history) < 2
            or history[-2] != (self._head, json.loads(self._payload)) or history[-1] != (head, expected)):
        _fail("rejected_readback_invalid")
    lineage._validate_publication_lineage_checkpoint_readback(expected_head=head, expected_payload=payload,
        observed_head=history[-1][0],
        observed_payload=RSILearningController._python_admission_flow_payload(history[-1][1]))
    self._rejection_cap_unchanged(allowance, file_pin)


def checkpoint_rejected(self, wire: object) -> str:
    """CAS only the original retain operation's pinned, adjacent rejected C1."""
    from .rsi_brs_publication_lineage import _BRSLineageCheckpointOwner

    if type(self) is not _BRSLineageCheckpointOwner:
        _fail("owner_invalid")
    try:
        self._rejection_observe()
        detached = self._rejected_entry(wire)
        expected = lineage._publication_lineage_checkpoint_delta(self._payload, detached)
        payload = self._controller._python_admission_flow_payload(expected)
        self._rejection_observe()
        self._rejected_entry(detached)
        self._rejection_control_live(time.monotonic())
        self._rejection_fixed()
        self._rejected_entry(detached, fixed=True)
        self._rejection_fixed()
        allowance, file_pin = self._rejection_deadline, self._rejection_file_pin
        self._rejection_cap_unchanged(allowance, file_pin)
        # The root checkpoint append precedes adoption of the matching in-memory
        # wave head. Mark that narrow transition so a worker cannot treat the
        # old head as a stable authority while this owner is publishing C1.
        with self._controller._python_admission_brs_checkpoint_transition(self._wave):
            head = self._ledger.write_controller_checkpoint(self._run_id, expected, expected_sha256=self._head)
            self._rejection_cap_unchanged(allowance, file_pin)
            self._rejection_control_live(time.monotonic())
            self._rejection_readback(head, expected, payload)
            self._rejection_readback_observe(expected)
            self._rejected_entry(detached, fixed=True)
            self._rejection_final_readback(head, expected, payload)
            allowance, file_pin = self._rejection_deadline, self._rejection_file_pin
            self._rejection_cap_unchanged(allowance, file_pin)
            self._before_channel()
            # No callback, source/configuration hook or latest-head adoption in this tail.
            with self._controller._python_admission_brs_observations(), self._before_channel_condition:
                self._controller._python_admission_assert_brs_wave(self._wave, owner=True)
                self._rejection_cap_unchanged(allowance, file_pin)
                self._before_channel()
                if (self._wave.state is not self._state or self._wave.selected_handoff is not self._handoff
                        or self._wave.selected_context is not self._selected_context
                        or self._wave.checkpoint_sha256 != self._head or self._wave.payload != self._payload
                        or self._controller.ledger is not self._ledger or self._controller.gateway is not self._gateway
                        or self._controller.producer_workspace is not self._workspace
                        or self._controller.producer_sidecar is not self._root_sidecar
                        or self._rejection_c1_capture is not None):
                    _fail("owner_drift")
                self._state[_FIELD] = json.loads(lineage._raw(detached))
                self._wave.checkpoint_sha256, self._wave.payload = head, payload
                self._head, self._payload = head, payload
                self._rejection_c1_capture = (head, payload)
                self._phase = "rejected"
        return head
    except BaseException:
        self._poisoned = True
        raise


def _history(self, state: dict[str, Any] | None = None) -> None:
    if self._reserved_prefix is not None:
        from .rsi_brs_reserved_owner import reserved_history

        return reserved_history(self, state)
    from .rsi_brs_rejection_c1 import (
        REJECTION_PROVENANCE_SCHEMA,
        REJECTION_SCHEMA,
        rejected_c1_entry,
        rejected_c1_index,
        rejected_provenance_entry,
        rejected_provenance_index,
        validate_rejected_c1_transition,
        validate_rejected_provenance_transition,
    )

    # The DRS history reader requires its public opt-in. Use the same strict
    # single-batch progression with BRS's existing pure capacity accounting;
    # never manufacture that DRS flag in real or synthetic state.
    previous = None
    for _head, snapshot in self._ledger.controller_checkpoint_history(self._run_id):
        wire = snapshot.get(_FIELD)
        if wire is None:
            if previous is not None:
                _fail("history_drift")
            continue
        if (type(wire) is not dict or set(wire) != {*self._association, "batches", "head", "rejections"}
                or any(wire[key] != item for key, item in self._association.items())
                or type(wire["batches"]) is not list or len(wire["batches"]) != 1):
            _fail("history_drift")
        entry = wire["batches"][0]
        if type(entry) is not dict or entry.get("state") not in {"before", "staged", "terminal", "rejected"}:
            _fail("history_drift")
        if entry["state"] == "rejected":
            if json.loads(self._policy_bytes).get("rejection_schema") != REJECTION_SCHEMA:
                _fail("rejected_policy_required")
            if entry.get("rejection_provenance") is None:
                rejected_c1_entry(entry)
                index = rejected_c1_index(entry)
            else:
                if json.loads(self._policy_bytes).get("rejection_provenance_schema") != REJECTION_PROVENANCE_SCHEMA:
                    _fail("rejected_provenance_policy_required")
                rejected_provenance_entry(entry)
                index = rejected_provenance_index(entry)
            if wire["head"] is not None or wire["rejections"] != index:
                _fail("history_drift")
        else:
            if wire["rejections"] != []:
                _fail("history_drift")
            self._validate_entry_shape(entry)
            lineage.RSIPublicationLineage._retained_bytes(wire, snapshot)
        terminal = entry.get("terminal")
        expected_head = None if terminal is None else {
            "journal_id": entry["journal_id"], "terminal_sha256": terminal["terminal_sha256"],
            "lineage_sha256": terminal["descriptor_sha256"],
        }
        if wire["head"] != expected_head:
            _fail("history_drift")
        if previous is None:
            if entry["state"] != "before" or entry["evidence_pins"] != {}:
                _fail("history_drift")
        else:
            old = previous["batches"][0]
            if entry["state"] == "rejected":
                if old["state"] == "rejected":
                    if wire != previous:
                        validate_rejected_provenance_transition(previous, wire)
                else:
                    validate_rejected_c1_transition(previous, wire)
                previous = wire
                continue
            if old["state"] == "rejected":
                _fail("history_drift")
            phases = ("before", "staged", "terminal")
            if not 0 <= phases.index(entry["state"]) - phases.index(old["state"]) <= 1:
                _fail("history_drift")
            for key, item in old.items():
                if key in {"snapshots", "evidence_pins"}:
                    if any(entry[key].get(name) != pin for name, pin in item.items()):
                        _fail("history_drift")
                elif key != "state" and entry.get(key) != item:
                    _fail("history_drift")
            if (old["state"] == "before" and entry["state"] == "staged"
                    and set(old["evidence_pins"]) != {"journal.prepared.json"}):
                _fail("history_drift")
        previous = wire
    if (self._state if state is None else state).get(_FIELD) != previous:
        _fail("history_drift")


def read_reserved_brs_material_inventory(workspace, wire, *, prefix_batches):
    """Independently read physical prefix material; this grants no owner authority.

    Returns ``(observations, episode_sha256s)``. Observations are ordered
    ``(workspace_relative_path, record)`` pairs retaining complete comparable
    physical identity; directories have size/sha256 None. The caller must retain
    and recheck the original ledger observation around this filesystem reader.
    ``prefix_batches`` must come from that independent original-ledger reader,
    never a filtered/synthesized claim or material-absence trace.
    """
    from .producer_bundle_lineage import MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES
    from .producer_bundle_rejection import _verify_terminal_batch_rejection_evidence
    from .rsi_brs_rejection_capacity import _OBSERVATION_FIELDS, _add_material, _pin_record
    from .rsi_brs_reserved_owner import read_reserved_published_materials
    from .rsi_native_rejection import (
        NativeRSIRejectionFilePin,
        read_native_rsi_rejection_provenance,
    )
    from .rsi_python_admission import validate_rsi_python_admission_shapes

    workspace = recovery._workspace(workspace)
    if type(prefix_batches) is not tuple or len(prefix_batches) > 8:
        _fail("material_prefix_invalid")
    if wire is None:
        if prefix_batches:
            _fail("material_prefix_invalid")
        return (), {}
    validate_rsi_python_admission_shapes(wire)
    if (type(wire) is not dict or wire.get("protocol") != "lunar-rsi-brs-lineage-checkpoint-v1"
            or type(wire.get("workspace")) is not dict or wire["workspace"].get("path") != str(workspace)
            or type(wire.get("batches")) is not list or len(wire["batches"]) != len(prefix_batches)):
        _fail("material_prefix_invalid")
    records, identities, episode_digests = {}, {}, {}
    total = 0
    for ordinal, (entry, prefix_batch) in enumerate(zip(wire["batches"], prefix_batches, strict=True)):
        if (type(entry) is not dict or type(prefix_batch) is not dict
                or type(entry.get("ordinal")) is not int or entry["ordinal"] != ordinal
                or entry.get("episode_id") != prefix_batch.get("episode_id")
                or entry.get("native_plan_sha256") != prefix_batch.get("native_plan_sha256")
                or entry.get("state") != ("terminal" if prefix_batch.get("outcome") == "published" else "rejected")
                or entry.get("snapshots") != prefix_batch.get("snapshots")):
            _fail("material_prefix_drift")
        base = "evolution/producer-batches/" + entry["journal_id"] + "/"
        batch = recovery._batch(workspace, entry["journal_id"])
        held, per_episode = [], set()

        def add(path, record, per_episode=per_episode):
            nonlocal total
            total += _add_material(records, identities, path, record)
            if record["kind"] == "file":
                per_episode.add(record["sha256"])
            if total > MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES:
                _fail("material_aggregate_exhausted")

        for kind in ("before", "staged", "terminal", "rejected"):
            field = kind + "_file_pin"
            if field in entry:
                raw = entry[field]
                name = "before-v2.json" if kind == "before" and ordinal else kind + ".json"
                held.append((base + "lineage/" + name, raw, name))
        for name, raw in entry["snapshots"].items():
            held.append((base + "lineage/" + name + ".snapshot", raw, name + ".snapshot"))
        for name, raw in entry["evidence_pins"].items():
            pin_name = "rejection-" + lineage._sha(name.encode()) if name.startswith("rejections/") else name
            held.append((base + name, raw, pin_name))
        for path, raw, name in held:
            pin = LineageSnapshotPin.from_dict(raw)
            verify_persisted_lineage_snapshot(workspace / path, pin)
            add(path, _pin_record(raw, name=name))
        if entry["state"] == "rejected":
            reference = entry.get("rejection_provenance")
            if type(reference) is not dict:
                _fail("material_provenance_missing")
            pin = NativeRSIRejectionFilePin.from_dict(reference["file_pin"])
            evidence = read_native_rsi_rejection_provenance(batch, expected_file_pin=pin)
            rejected = ProducerLineageRejectedTerminalV2.from_dict(entry["rejected"])
            prepared = parse_producer_bundle_publication_journal(entry["prepared_journal"])
            terminal = parse_producer_bundle_publication_journal(entry["rejected_journal"])
            observed = _verify_terminal_batch_rejection_evidence(workspace, batch, prepared, terminal=terminal)
            if (evidence.provenance_sha256 != reference.get("provenance_sha256")
                    or evidence.rejected != rejected or evidence.terminal != terminal
                    or evidence.plan.plan_sha256 != entry["native_plan_sha256"]
                    or evidence.plan.request_sha256 != entry["request_sha256"]
                    or evidence.lineage.ordinal != ordinal or observed.terminal != terminal
                    or observed.manifest_sha256 != rejected.rejection_manifest_sha256
                    or observed.execution_receipt_sha256s != evidence.execution_receipt_sha256s
                    or observed.evaluation_receipt_sha256s != evidence.evaluation_receipt_sha256s
                    or observed.retained_evidence_sha256s != evidence.retained_evidence_sha256s):
                _fail("material_rejection_drift")
            for table in _read_rejection_tables_at(workspace, entry).values():
                for item in table["entries"]:
                    add(item["path"], {key: value for key, value in item.items() if key != "path"})
            add(base + pin.name, {"kind": "file", **{name: getattr(pin, name) for name in _OBSERVATION_FIELDS}})
            if read_native_rsi_rejection_provenance(batch, expected_file_pin=pin) != evidence:
                _fail("material_provenance_drift")
        else:
            for path, record in read_reserved_published_materials(workspace, entry).items():
                add(path, record)
        for path, raw, _name in held:
            verify_persisted_lineage_snapshot(workspace / path, LineageSnapshotPin.from_dict(raw))
        episode_digests[entry["episode_id"]] = tuple(sorted(per_episode))
    return tuple((path, dict(record)) for path, record in sorted(records.items())), episode_digests
