"""Original RSI opt-in policy for bounded producer publication lineage.

The persisted policy is a mode and dependency contract, not an execution permit.
It does not relax the existing initial-only publication or current-head recovery
gates. Owner/CAS and independently held lineage evidence must be composed before
repeated publication can be enabled.
"""

from __future__ import annotations

import hashlib
import json
import stat
from dataclasses import replace
from pathlib import Path
from threading import get_ident
from typing import Any

from . import _benchmark_files as _files
from ._candidate_workspace_io import DirectoryChain
from .candidate_evaluation_spec import canonical_json
from .producer_bundle_lineage import (
    MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES,
    MAX_LINEAGE_BATCHES,
    MAX_LINEAGE_SNAPSHOT_BYTES,
    LineageSnapshotPin,
    ProducerLineageBeforeIntent,
    ProducerLineageStagedTransition,
    ProducerLineageTerminal,
    capture_lineage_snapshot_pin,
    lineage_directory,
    persist_lineage_bytes_snapshot,
    persist_lineage_descriptor,
    persist_lineage_snapshot,
    read_lineage_descriptor_pinned,
    verify_persisted_lineage_snapshot,
)
from .producer_bundle_lineage_v2 import (
    ProducerLineageBeforeIntentV2,
    ProducerLineageRejectedTerminalV2,
    persist_lineage_v2_descriptor,
    read_lineage_v2_descriptor_pinned,
)
from .rsi_budget import RSIRunBudget
from .rsi_gateway import SolverRequest
from .rsi_identity import component_fingerprint
from .rsi_learning import MemorySnapshot, RSILearningError
from .rsi_native_plan import NativeRSIExecutionPlan, NativeRSIExecutionPlanError
from .rsi_native_rejection import (
    NativeRSIRejectionEvidence,
    NativeRSIRejectionFilePin,
    RejectionLineageC1Binding,
    map_native_rejection_to_solver_result,
    read_native_rsi_rejection_provenance,
)

_PROTOCOL = "lunar-rsi-multi-episode-publication-v1"
_PROTOCOL_V2 = "lunar-rsi-multi-episode-publication-v2"
_FIELD = "producer_publication_lineage"
_MAX_CHECKPOINT_BYTES = 112 * 1024


def _fail(reason: str) -> None:
    raise RSILearningError("rsi_publication_lineage_" + reason)


def _raw(value: object) -> bytes:
    return canonical_json(value, maximum=_MAX_CHECKPOINT_BYTES)


def _copy(value: object) -> Any:
    return json.loads(_raw(value))


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _root_pin(path: Path) -> dict[str, Any]:
    chain = DirectoryChain(path, "rsi_publication_lineage_workspace_invalid")
    try:
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode):
            _fail("workspace_invalid")
        chain.check()
    finally:
        chain.close()
    return {"path": str(path), "device": info.st_dev, "inode": info.st_ino}


def _publication_shapes(*values: object) -> None:
    from .producer_bundle_admission import ProducerBundleAdmissionItem, ProducerBundleAdmissionPlan
    from .producer_bundle_publication import (
        ProducerBundlePublicationCandidate,
        ProducerBundlePublicationJournal,
    )
    from .producer_bundle_staging import ProducerBundlePublicationManifest
    from .producer_launcher import ProducerLaunchIntent
    from .python_producer_admission_handoff import PythonProducerAdmissionHandoffFilePin
    from .rsi_python_admission import validate_rsi_python_admission_shapes

    types = (ProducerBundleAdmissionItem, ProducerBundleAdmissionPlan, ProducerBundlePublicationCandidate,
             ProducerBundlePublicationJournal, ProducerBundlePublicationManifest,
             ProducerLaunchIntent, PythonProducerAdmissionHandoffFilePin)
    for value in values:
        validate_rsi_python_admission_shapes(value, dto_types=types)


def _require_marker_absent(workspace: Path) -> None:
    try:
        (workspace / "evolution/producer-publication.json").lstat()
    except FileNotFoundError:
        return
    _fail("publication_marker_exists")


def multi_episode_publication_policy(controller: Any) -> dict[str, Any] | None:
    """Reject mode drift before reading a run, workspace or producer artifact."""
    from .rsi_controller import RSILearningController

    known_rejection = controller._producer_known_rejection_mode()
    flag = controller.producer_multi_episode_publication
    if (type(flag) is not bool
            or flag is not controller._original_producer_multi_episode_publication):
        raise RSILearningError("rsi_producer_multi_episode_configuration_drift")
    if not flag:
        return None
    if type(controller) is not RSILearningController:
        raise RSILearningError("rsi_producer_multi_episode_configuration_invalid")
    if (controller.producer_child_execution is not True
            or controller._producer_child_execution_policy() is None):
        raise RSILearningError("rsi_producer_multi_episode_configuration_drift")
    from .producer_bundle_lineage import (
        MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES,
        MAX_LINEAGE_BATCHES,
        MAX_LINEAGE_DESCRIPTOR_BYTES,
        MAX_LINEAGE_SNAPSHOT_BYTES,
        LineageSnapshotPin,
        ProducerLineageBeforeIntent,
        ProducerLineageStagedTransition,
        ProducerLineageTerminal,
    )

    policy = {
        "protocol": "lunar-rsi-multi-episode-publication-v1",
        "production_admission": False,
        "mode": "drs",
        "iteration": 0,
        "max_batches": MAX_LINEAGE_BATCHES,
        "max_descriptor_bytes": MAX_LINEAGE_DESCRIPTOR_BYTES,
        "max_snapshot_bytes": MAX_LINEAGE_SNAPSHOT_BYTES,
        "max_aggregate_snapshot_bytes": MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES,
        "dependencies": {
            "policy": component_fingerprint(multi_episode_publication_policy),
            "snapshot_pin": component_fingerprint(LineageSnapshotPin, config={}),
            "before": component_fingerprint(ProducerLineageBeforeIntent, config={}),
            "staged": component_fingerprint(ProducerLineageStagedTransition, config={}),
            "terminal": component_fingerprint(ProducerLineageTerminal, config={}),
            "owner": component_fingerprint(RSIPublicationLineage, config={}),
            "owner_methods": {
                name: component_fingerprint(getattr(RSIPublicationLineage, name))
                for name in ("validate_launch", "validate_before", "retain_before", "acknowledge_prepared",
                             "retain_staged", "verify_precommit", "retain_terminal", "_check_owner", "_ack")
            },
            "owner_cas": component_fingerprint(acknowledge_publication_lineage_for_active_flow),
            "inspection": component_fingerprint(RSIPublicationLineageInspection, config={}),
            "module_sources": {
                name: _sha(_files.read_regular_file(Path(__file__).parent / name, 1024 * 1024))
                for name in (
                    "rsi_publication_lineage.py", "producer_bundle_lineage.py", "producer_bundle_transaction.py",
                    "producer_bundle_staging.py", "producer_bundle_recovery.py", "producer_bundle_admission.py",
                    "producer_bundle_preflight.py", "rsi_controller.py", "rsi_store.py", "rsi_python_admission.py",
                    "rsi_native_plan.py", "_candidate_workspace_io.py", "_benchmark_files.py", "evolution.py",
                    "rsi_native_retained.py", "rsi_native_scheduler.py", "rsi_producer_gateway.py",
                    "rsi_native_gateway.py", "rsi_child_gateway.py", "rsi_python_scheduler_inputs.py",
                    "rsi_python_publication.py", "rsi_producer_staging_capsule.py", "rsi_python_episode_inputs.py",
                    "rsi_producer_launch.py",
                )
            },
        },
    }
    if not known_rejection:
        return policy
    from .producer_bundle_rejection import _verify_terminal_batch_rejection_evidence
    from .rsi_native_gateway import NativeRSISolverGateway
    from .rsi_native_rejection import persist_native_rsi_rejection_provenance

    policy["protocol"] = _PROTOCOL_V2
    dependencies = policy["dependencies"]
    dependencies.update({
        "before_v2": component_fingerprint(ProducerLineageBeforeIntentV2, config={}),
        "rejected_v2": component_fingerprint(ProducerLineageRejectedTerminalV2, config={}),
        "rejection_pin": component_fingerprint(NativeRSIRejectionFilePin, config={}),
        "rejection_binding": component_fingerprint(RejectionLineageC1Binding, config={}),
        "rejection_evidence": component_fingerprint(NativeRSIRejectionEvidence, config={}),
        "rejection_verifier": component_fingerprint(_verify_terminal_batch_rejection_evidence),
        "rejection_persist": component_fingerprint(persist_native_rsi_rejection_provenance),
        "rejection_read": component_fingerprint(read_native_rsi_rejection_provenance),
        "rejection_mapper": component_fingerprint(map_native_rejection_to_solver_result),
        "inspection_v2": component_fingerprint(RSIPublicationLineageV2Inspection, config={}),
        "started_rejection_inspection": component_fingerprint(StartedRSIRejectionInspection, config={}),
        "mixed_history_reader": component_fingerprint(_V2LineageEvidenceReader, config={}),
        "controller_methods": {name: component_fingerprint(getattr(RSILearningController, name)) for name in (
            "_producer_known_rejection_mode", "_validate_native_rejection_reconciliation_checkpoint", "reconcile_native_rejection",
        )},
        "gateway_methods": {name: component_fingerprint(getattr(NativeRSISolverGateway, name))
                            for name in ("inspect_rejection", "restore_rejection")},
    })
    dependencies["owner_methods"].update({
        name: component_fingerprint(getattr(RSIPublicationLineage, name))
        for name in ("rejection_provenance_binding", "acknowledge_rejection_provenance",
                     "rejection_provenance_file_pin", "_retain_rejected_locked", "_projected_rejected_entry",
                     "_build_before_descriptor", "_retained_bytes")
    })
    dependencies["module_sources"].update({
        name: _sha(_files.read_regular_file(Path(__file__).parent / name, 1024 * 1024))
        for name in ("producer_bundle_lineage_v2.py", "producer_bundle_rejection.py", "rsi_native_rejection.py",
                     "rsi_native_provenance_names.py", "rsi_native_provenance.py", "rsi_native_failure.py")
    })
    return policy


class _LineageEvidenceReader:
    """Shared bounded observations; no execution, locking or CAS authority."""

    __slots__ = ()

    def _is_v2(self) -> bool:
        return self._association.get("protocol") == _PROTOCOL_V2

    def _validate_history(self, state: dict[str, Any]) -> None:
        if self._is_v2():
            return self._validate_history_v2(state)
        from .rsi_producer_staging_capsule import (
            retained_publication_evidence_bytes,
            retained_ready_capsule_bytes,
        )

        retained_publication_evidence_bytes(state)
        previous = None
        for _head, snapshot in self._ledger.controller_checkpoint_history(self._run_id):
            retained_publication_evidence_bytes(snapshot)
            total = retained_ready_capsule_bytes(snapshot)
            if total > MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES:
                _fail("capacity_exceeded")
            wire = snapshot.get(_FIELD)
            if wire is None:
                if previous is not None:
                    _fail("history_drift")
                continue
            if type(wire) is not dict or set(wire) != {*self._association, "batches", "head", "rejections"}:
                _fail("history_invalid")
            if any(wire[key] != value for key, value in self._association.items()):
                _fail("association_drift")
            if (type(wire["batches"]) is not list or len(wire["batches"]) > MAX_LINEAGE_BATCHES
                    or type(wire["rejections"]) is not list or len(wire["rejections"]) > MAX_LINEAGE_BATCHES):
                _fail("capacity_exceeded")
            if previous is None and (len(wire["batches"]) > 1 or (wire["batches"] and (
                type(wire["batches"][0]) is not dict or wire["batches"][0].get("state") != "before"
                or wire["batches"][0].get("evidence_pins") != {}
            ))):
                _fail("history_introduction_invalid")
            terminals = []
            for ordinal, entry in enumerate(wire["batches"]):
                if (type(entry) is not dict or type(entry.get("ordinal")) is not int
                        or entry["ordinal"] != ordinal or entry.get("state") not in {"before", "staged", "terminal"}
                        or entry.get("journal_id") != entry.get("before", {}).get("journal_id")
                        or entry.get("before", {}).get("run_id") != self._run_id):
                    _fail("history_invalid")
                self._validate_entry_shape(entry)
                if type(entry.get("snapshots")) is not dict:
                    _fail("history_invalid")
                total += sum(LineageSnapshotPin.from_dict(pin).size for pin in entry["snapshots"].values())
                if total > MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES:
                    _fail("capacity_exceeded")
                if entry["state"] == "terminal":
                    terminal = ProducerLineageTerminal.from_dict(entry["terminal"])
                    terminals.append(terminal)
                elif ordinal != len(wire["batches"]) - 1:
                    _fail("history_invalid")
            expected_head = None if not terminals else {
                "journal_id": terminals[-1].journal_id,
                "terminal_sha256": terminals[-1].terminal_sha256,
                "lineage_sha256": terminals[-1].digest(),
            }
            if wire["head"] != expected_head:
                _fail("history_head_invalid")
            if previous is not None:
                old = previous["batches"]
                new = wire["batches"]
                if len(new) < len(old) or len(new) > len(old) + 1:
                    _fail("history_drift")
                if len(new) == len(old) + 1 and (
                    type(new[-1]) is not dict or new[-1].get("state") != "before" or new[-1].get("evidence_pins") != {}
                ):
                    _fail("history_introduction_invalid")
                for index, entry in enumerate(old):
                    current = new[index]
                    if type(entry) is not dict or type(current) is not dict:
                        _fail("history_invalid")
                    for key, value in entry.items():
                        if key in {"snapshots", "evidence_pins"}:
                            if (type(current.get(key)) is not dict
                                    or any(current[key].get(name) != pin for name, pin in value.items())):
                                _fail("history_drift")
                        elif key != "state" and current.get(key) != value:
                            _fail("history_drift")
                    sequence = ("before", "staged", "terminal")
                    if (entry.get("state") not in sequence or current.get("state") not in sequence
                            or not 0 <= sequence.index(current["state"]) - sequence.index(entry["state"]) <= 1):
                        _fail("history_drift")
                    if (entry["state"] == "before" and current["state"] == "staged"
                            and set(entry["evidence_pins"]) != {"journal.prepared.json"}):
                        _fail("history_prepared_pin_missing")
                if wire["rejections"][:len(previous["rejections"])] != previous["rejections"]:
                    _fail("history_drift")
            previous = wire
        if (state.get(_FIELD) != previous
                or (previous is not None and any(batch.get("state") != "terminal"
                    for batch in previous["batches"][:-1]))):
            _fail("history_drift")

    def _validate_entry_shape(self, entry: dict[str, Any]) -> None:
        if self._is_v2():
            return self._validate_entry_shape_v2(entry)
        base = {
            "journal_id", "ordinal", "episode_id", "request_sha256", "memory_snapshot_sha256",
            "native_plan_sha256", "admission_plan", "prepared_journal", "before", "before_file_pin",
            "snapshots", "before_sources", "state", "evidence_pins",
        }
        staged_fields = {"staged", "staged_file_pin", "state_projection_sha256", "after_sources"}
        terminal_fields = {"terminal", "terminal_file_pin", "published_journal", "head_sources"}
        phase = entry.get("state")
        expected = base | (staged_fields if phase in {"staged", "terminal"} else set())
        expected |= terminal_fields if phase == "terminal" else set()
        snapshots = {"archive-before", "state-before"}
        if phase in {"staged", "terminal"}:
            snapshots |= {"archive-after", "state-after"}
        pins = {"journal.prepared.json"}
        if phase in {"staged", "terminal"}:
            pins |= {"journal.staged.json", "manifest.json", "preflight.json"}
        if phase == "terminal":
            pins |= {"journal.published.json", "terminal.json"}
        if (set(entry) != expected or type(entry.get("snapshots")) is not dict
                or set(entry["snapshots"]) != snapshots or type(entry.get("evidence_pins")) is not dict
                or (set(entry["evidence_pins"]) != pins and not (phase == "before" and not entry["evidence_pins"]))):
            _fail("history_phase_pins_invalid")
        for name, raw in entry["snapshots"].items():
            if LineageSnapshotPin.from_dict(raw).name != name + ".snapshot":
                _fail("history_phase_pins_invalid")
        for name, raw in entry["evidence_pins"].items():
            if LineageSnapshotPin.from_dict(raw).name != name:
                _fail("history_phase_pins_invalid")
        for kind in ("before", "staged", "terminal"):
            if kind + "_file_pin" in entry and LineageSnapshotPin.from_dict(entry[kind + "_file_pin"]).name != kind + ".json":
                _fail("history_phase_pins_invalid")
        self._validate_source_pin_maps(entry)

    def _verify_descriptor(self, entry: dict[str, Any], kind: str):
        pin = LineageSnapshotPin.from_dict(entry[kind + "_file_pin"])
        if self._is_v2() and kind in {"before", "rejected"}:
            observed = read_lineage_v2_descriptor_pinned(
                self._workspace, entry["journal_id"], kind="before-v2" if kind == "before" else "rejected",
                expected_file_pin=pin,
            )
            if observed.to_dict() != entry[kind]:
                _fail("descriptor_drift")
            return observed
        observed = read_lineage_descriptor_pinned(
            self._workspace, entry["journal_id"], kind=kind, expected_file_pin=pin,
        )
        if observed.to_dict() != entry[kind]:
            _fail("descriptor_drift")
        return observed

    def _snapshot_bytes(self, journal_id: str, pin_wire: object, *, name: str) -> bytes:
        pin = LineageSnapshotPin.from_dict(pin_wire)
        if pin.name != name + ".snapshot":
            _fail("snapshot_association_invalid")
        path = lineage_directory(self._workspace, journal_id) / (name + ".snapshot")
        verify_persisted_lineage_snapshot(path, pin)
        raw = _files.read_regular_file(path, MAX_LINEAGE_SNAPSHOT_BYTES)
        verify_persisted_lineage_snapshot(path, pin)
        return raw

    def _verify_terminal_entry(self, entry: dict[str, Any], *, ordinal: int,
                               previous: dict[str, Any] | None) -> tuple[bytes, bytes]:
        from . import producer_bundle_recovery as recovery
        from .producer_bundle_admission import parse_producer_bundle_admission_plan
        from .producer_bundle_publication import parse_producer_bundle_publication_journal

        if self._is_v2() and type(entry) is dict and entry.get("state") == "rejected":
            return self._verify_rejected_entry(entry, ordinal=ordinal, previous=previous)
        if type(entry) is not dict or entry.get("state") != "terminal" or entry.get("ordinal") != ordinal:
            _fail("pending_predecessor")
        self._validate_entry_shape(entry)
        before = self._verify_descriptor(entry, "before")
        staged = self._verify_descriptor(entry, "staged")
        terminal = self._verify_descriptor(entry, "terminal")
        before_type = ProducerLineageBeforeIntentV2 if self._is_v2() else ProducerLineageBeforeIntent
        if (type(before) is not before_type or type(staged) is not ProducerLineageStagedTransition
                or type(terminal) is not ProducerLineageTerminal or before.ordinal != ordinal
                or staged.ordinal != ordinal or terminal.ordinal != ordinal
                or before.run_id != self._run_id or staged.run_id != self._run_id
                or terminal.run_id != self._run_id
                or staged.before_sha256 != before.digest() or terminal.staged_sha256 != staged.digest()):
            _fail("chain_invalid")
        if self._is_v2():
            self._verify_before_predecessors_v2(before, previous)
        else:
            expected_terminal = previous["terminal"]["terminal_sha256"] if previous else None
            expected_lineage = previous["terminal"]["descriptor_sha256"] if previous else None
            if (before.predecessor_terminal_sha256 != expected_terminal
                    or before.predecessor_lineage_sha256 != expected_lineage):
                _fail("predecessor_mismatch")
        snapshots = entry["snapshots"]
        archive_before = self._snapshot_bytes(entry["journal_id"], snapshots["archive-before"], name="archive-before")
        state_before = self._snapshot_bytes(entry["journal_id"], snapshots["state-before"], name="state-before")
        archive_after = self._snapshot_bytes(entry["journal_id"], snapshots["archive-after"], name="archive-after")
        state_after = self._snapshot_bytes(entry["journal_id"], snapshots["state-after"], name="state-after")
        if (before.archive.to_dict() != snapshots["archive-before"]
                or before.state.to_dict() != snapshots["state-before"]
                or _sha(archive_after) != staged.archive_after_sha256
                or _sha(state_after) != staged.state_after_sha256
                or terminal.archive_after_sha256 != staged.archive_after_sha256
                or terminal.state_after_sha256 != staged.state_after_sha256):
            _fail("snapshot_drift")
        if previous is not None:
            old = previous["snapshots"]
            suffix = "before" if self._is_v2() and previous["state"] == "rejected" else "after"
            if (archive_before != self._snapshot_bytes(previous["journal_id"], old["archive-" + suffix], name="archive-" + suffix)
                    or state_before != self._snapshot_bytes(previous["journal_id"], old["state-" + suffix], name="state-" + suffix)):
                _fail("snapshot_continuity_drift")
            sources = previous["before_sources"] if suffix == "before" else previous["head_sources"]
            if entry["before_sources"] != sources:
                _fail("source_continuity_drift")
        journal = parse_producer_bundle_publication_journal(entry["published_journal"])
        prepared = parse_producer_bundle_publication_journal(entry["prepared_journal"])
        plan = parse_producer_bundle_admission_plan(entry["admission_plan"])
        if (prepared.state != "prepared" or prepared.journal_id != before.journal_id
                or prepared.run_id != self._run_id or prepared.admission_sha256 != plan.digest()
                or prepared.base_archive_sha256 != before.archive.sha256
                or prepared.base_state_sha256 != before.state.sha256
                or journal.journal_id != prepared.journal_id or journal.run_id != prepared.run_id
                or journal.task_id != entry["episode_id"] or prepared.task_id != entry["episode_id"]):
            _fail("prepared_association_drift")
        batch = recovery._batch(self._workspace, entry["journal_id"])
        if set(entry["evidence_pins"]) != {
            "journal.prepared.json", "journal.staged.json", "manifest.json", "preflight.json",
            "journal.published.json", "terminal.json",
        } or set(snapshots) != {"archive-before", "state-before", "archive-after", "state-after"}:
            _fail("evidence_pins_invalid")
        for name, held_pin in entry["evidence_pins"].items():
            verify_persisted_lineage_snapshot(batch / name, LineageSnapshotPin.from_dict(held_pin))
        durable = recovery._read_journal(batch / "journal.published.json")
        if durable != journal or journal.state != "published" or journal.admission_sha256 != plan.digest():
            _fail("published_journal_drift")
        if recovery._read_journal(batch / "journal.prepared.json").to_dict() != entry["prepared_journal"]:
            _fail("prepared_journal_drift")
        original_staged = recovery._read_journal(batch / "journal.staged.json")
        if original_staged.digest() != staged.journal_sha256:
            _fail("staged_journal_drift")
        preflight = recovery._read_json(batch / "preflight.json", 128 * 1024)
        preflight_sha = recovery._check_preflight(preflight, original_staged, plan)
        manifest_raw = recovery._read_json(batch / "manifest.json", 256 * 1024)
        manifest_sha, ids, _paths, files = recovery._manifest(manifest_raw, original_staged, preflight_sha)
        if manifest_sha != staged.manifest_sha256 or ids != staged.candidate_ids:
            _fail("manifest_drift")
        recovery._verify_python_handoff(batch, journal, plan)
        recovery._verify_manifest_files(self._workspace, batch, files, journal)
        observed = recovery._verify_terminal_batch_evidence(self._workspace, batch, journal, manifest_sha)
        if (observed.terminal_marker_sha256 != terminal.terminal_sha256
                or observed.archive_after_sha256 != _sha(archive_after)
                or observed.state_after_sha256 != _sha(state_after)):
            _fail("terminal_drift")
        self._verify_transition_projection(entry, archive_before, state_before, archive_after, state_after)
        recovery._verify_python_handoff(batch, journal, plan)
        for name, held_pin in entry["evidence_pins"].items():
            verify_persisted_lineage_snapshot(batch / name, LineageSnapshotPin.from_dict(held_pin))
        return archive_after, state_after

    def _validate_source_pin_maps(self, entry: dict[str, Any]) -> None:
        if self._is_v2():
            return self._validate_source_pin_maps_v2(entry)
        maps = ["before_sources"]
        if entry["state"] in {"staged", "terminal"}:
            maps.append("after_sources")
        if entry["state"] == "terminal":
            maps.append("head_sources")
        for field in maps:
            sources = entry.get(field)
            if type(sources) is not dict or set(sources) != {"archive", "state"}:
                _fail("source_pins_invalid")
            for name, raw in sources.items():
                if field == "before_sources" and name == "archive" and type(raw) is dict and raw.get("missing") is True:
                    if (entry["ordinal"] != 0 or set(raw) != {"missing", "parent"}
                            or raw["parent"] != _root_pin(self._workspace / "evolution")
                            or entry["snapshots"]["archive-before"]["size"] != 0
                            or entry["snapshots"]["archive-before"]["sha256"] != _sha(b"")):
                        _fail("source_pins_invalid")
                    continue
                pin = LineageSnapshotPin.from_dict(raw)
                suffix = "after" if field == "after_sources" else "before"
                snapshot_suffix = "before" if field == "before_sources" else "after"
                snapshot = LineageSnapshotPin.from_dict(entry["snapshots"][name + "-" + snapshot_suffix])
                if (pin.name != name + "-" + suffix or pin.sha256 != snapshot.sha256
                        or pin.size != snapshot.size):
                    _fail("source_pins_invalid")
        if entry["state"] == "terminal":
            for name in ("archive", "state"):
                source = LineageSnapshotPin.from_dict(entry["after_sources"][name])
                head = LineageSnapshotPin.from_dict(entry["head_sources"][name])
                if any(getattr(source, field) != getattr(head, field) for field in (
                    "device", "inode", "size", "mode", "nlink", "mtime_ns", "sha256",
                )):
                    _fail("source_pins_invalid")

    def _verify_durable_native_result(self, entry: dict[str, Any], request: SolverRequest,
                                      plan: NativeRSIExecutionPlan, result: Any) -> None:
        from .rsi_native_candidate import (
            NativeCandidateRecord,
            NativeEvaluationReceipt,
            NativeExecutionReceipt,
            NativePublicationReceipt,
            map_native_receipts_to_solver_result,
            select_native_candidate,
        )
        from .rsi_native_provenance import read_native_rsi_provenance

        batch = self._workspace / "evolution/producer-batches" / entry["journal_id"]
        saved = read_native_rsi_provenance(batch)
        provenance = dict(result.solver_provenance)
        journal = entry["published_journal"]
        if (saved["plan"] != plan.to_dict()
                or saved["publication_journal_sha256"] != journal["journal_sha256"]
                or saved["producer_execution_receipt_sha256"] != journal["native_execution_receipt_sha256"]
                or provenance.get("native_plan_sha256") != plan.plan_sha256
                or provenance.get("native_provenance_sha256") != saved["provenance_sha256"]):
            _fail("inspection_native_result_drift")
        bundle = saved["bundle"]
        candidate = NativeCandidateRecord.from_dict(bundle["candidate"])
        execution = NativeExecutionReceipt.from_dict(bundle["execution"])
        evaluation = NativeEvaluationReceipt.from_dict(bundle["evaluation"])
        publication = NativePublicationReceipt.from_dict(bundle["publication"])
        selected = [slot for slot in journal["candidates"] if slot["candidate_id"] == candidate.candidate_id]
        if (len(selected) != 1 or selected[0]["status"] != "admitted"
                or candidate.candidate_receipt_sha256 != selected[0]["preparation_receipt_sha256"]
                or execution.receipt_sha256 != selected[0]["execution_receipt_sha256"]
                or evaluation.receipt_sha256 != selected[0]["evaluation_receipt_sha256"]
                or publication.receipt_sha256 != selected[0]["publication_receipt_sha256"]):
            _fail("inspection_native_result_drift")
        expected = map_native_receipts_to_solver_result(
            request, select_native_candidate(request, [candidate]), execution, evaluation, publication,
        )
        expected = replace(expected, solver_provenance=tuple(sorted({
            **dict(expected.solver_provenance), "native_plan_sha256": plan.plan_sha256,
            "native_provenance_sha256": saved["provenance_sha256"],
        }.items())))
        if result != expected or read_native_rsi_provenance(batch) != saved:
            _fail("inspection_native_result_drift")

    def _verify_transition_projection(self, entry, archive_before, state_before, archive_after, state_after) -> None:
        # The native transaction already produces this projection. Verify every historical
        # prefix and exact addition again rather than accepting arbitrary appended rows.
        from .producer_bundle_transaction import _records_from_archive

        if not archive_after.startswith(archive_before):
            _fail("archive_prefix_drift")
        before_records = _records_from_archive(archive_before)
        after_records = _records_from_archive(archive_after)
        before_ids = tuple(item.candidate_id for item in before_records)
        after_ids = tuple(item.candidate_id for item in after_records)
        ids = tuple(entry["staged"]["candidate_ids"])
        if after_ids != (*before_ids, *ids):
            _fail("archive_additions_drift")
        base = json.loads(state_before)
        observed = json.loads(state_after)
        if (base.get("config") != self._strategy.config.to_dict()
                or base.get("candidate_integrity_authority") != self._strategy.integrity_authority.to_dict()
                or base.get("contract_sha256") != entry["published_journal"]["contract_sha256"]):
            _fail("native_configuration_drift")
        projection = _copy(base)
        previous_events = projection.get("producer_admissions", {"schema_version": "1", "events": []})
        projection["producer_admissions"] = {
            "schema_version": "1", "events": [*previous_events["events"], {"after_iteration": 0, "candidate_ids": list(ids)}],
        }
        active, best, migration, stagnation = self._strategy._reconstruct_population_projection(projection, after_records)
        expected = dict(base)
        expected.update(
            schema_version="1", strategy="population", status="running", iteration=0,
            contract_sha256=entry["published_journal"]["contract_sha256"], config=dict(base["config"]),
            active_ids={str(key): value for key, value in active.items()},
            producer_admissions=projection["producer_admissions"], best_candidate_id=best,
            rng_seed=base.get("rng_seed", base["config"].get("rng_seed")),
            last_migration_iteration=migration, stagnation=stagnation, error=None,
            candidate_integrity_schema_version="1", candidate_integrity_authority=base["candidate_integrity_authority"],
            candidate_archive_sha256=_sha(canonical_json(
                [item.to_dict() for item in after_records if "seed_handoff" not in item.metadata],
                maximum=16 * 1024 * 1024,
            )),
        )
        if observed != expected or _sha(state_after) != entry["state_projection_sha256"]:
            _fail("state_projection_drift")

    def _verify_chain(self, wire: dict[str, Any], archive: bytes, state_bytes: bytes, *,
                      precommit: tuple[Any, Any] | None = None) -> tuple[tuple[str, ...], ...]:
        from .producer_bundle_transaction import (
            _ensure_append_population_window,
            _records_from_archive,
        )

        marker_pin = None
        if precommit is not None:
            from .evolution import CandidateArchive, PopulationStrategy
            from .producer_bundle_lineage import ProducerBundleLineageError
            from .producer_bundle_publication import ProducerBundlePublicationJournal
            from .producer_bundle_staging import (
                _HELD_PUBLICATION_LOCKS,
                ProducerBundlePublicationManifest,
                ProducerBundlePublicationStagingError,
                _check_held_publication_lock,
                _load_marker,
                _marker_bytes,
                marker_payload,
            )

            if (type(self) is not RSIPublicationLineage or type(precommit) is not tuple
                    or len(precommit) != 2):
                _fail("precommit_state_invalid")
            staged, manifest = precommit
            _publication_shapes(staged, manifest)
            if (type(staged) is not ProducerBundlePublicationJournal
                    or type(manifest) is not ProducerBundlePublicationManifest
                    or self._phase != "staged" or self._prepared_ack is not True):
                _fail("precommit_state_invalid")
            held = _HELD_PUBLICATION_LOCKS.get()
            if not any(path.parent.parent == self._workspace for path, _fd, _info in held):
                _fail("publication_lock_required")
            _check_held_publication_lock()
            state = self._check_owner()
            current = self._wire(state)
            if type(current.get("batches")) is not list or not current["batches"]:
                _fail("precommit_association_invalid")
            entry = current["batches"][-1]
            if (entry["state"] != "staged" or staged.state != "publishing" or manifest.status != "staged"
                    or staged.journal_id != self._plan.journal_id or entry["journal_id"] != staged.journal_id
                    or staged.digest() != entry["staged"]["journal_sha256"]
                    or manifest.digest() != entry["staged"]["manifest_sha256"]
                    or manifest.journal_id != staged.journal_id or manifest.journal_sha256 != staged.digest()
                    or wire != {**current, "batches": current["batches"][:-1]}):
                _fail("precommit_association_invalid")
            original_strategy = self._strategy
            if (type(original_strategy) is not PopulationStrategy
                    or type(original_strategy.archive) is not CandidateArchive
                    or original_strategy is not self._gateway.producer_config.inputs.native_context.strategy
                    or original_strategy.context.workspace.expanduser().absolute() != self._workspace):
                _fail("precommit_strategy_invalid")
            marker_path = self._workspace / "evolution" / "producer-publication.json"
            expected_marker = _marker_bytes(marker_payload(
                journal_id=staged.journal_id, journal_sha256=staged.digest(),
                manifest_sha256=manifest.digest(), status="staged",
            ))
            try:
                marker_pin = capture_lineage_snapshot_pin(marker_path, name=marker_path.name)
                if _load_marker(marker_path)[1] != expected_marker:
                    _fail("precommit_marker_invalid")
                verify_persisted_lineage_snapshot(marker_path, marker_pin)
            except (ProducerBundleLineageError, ProducerBundlePublicationStagingError) as exc:
                raise RSILearningError("rsi_publication_lineage_precommit_marker_invalid") from exc
            # Only this held, original staged commit can inspect offspring history.
            # Do not alter the ordinary archive or expose/store an inspection object.
            inspection_archive = CandidateArchive.__new__(CandidateArchive)
            inspection_archive.workspace = self._workspace
            inspection_archive.root = self._workspace / "evolution"
            inspection_archive.candidates_root = inspection_archive.root / "candidates"
            inspection_archive.archive_path = inspection_archive.root / "archive.jsonl"
            inspection_archive.offspring_outcomes_path = inspection_archive.root / "offspring-outcomes.jsonl"
            inspection_archive.state_path = inspection_archive.root / "state.json"
            inspection_archive.read_only = True
            inspection_archive._producer_publication_inspection = True
            window_strategy = PopulationStrategy.__new__(PopulationStrategy)
            window_strategy.context = original_strategy.context
            window_strategy.config = original_strategy.config
            window_strategy.archive = inspection_archive
        else:
            window_strategy = self._strategy

        seen_journals: set[str] = set()
        seen_candidates: set[str] = set()
        prior_events = []
        previous = None
        published_head = None
        head_archive = head_state = None
        for ordinal, entry in enumerate(wire["batches"]):
            if entry["journal_id"] in seen_journals:
                _fail("duplicate_journal")
            seen_journals.add(entry["journal_id"])
            head_archive, head_state = self._verify_terminal_entry(entry, ordinal=ordinal, previous=previous)
            prefix_archive = self._snapshot_bytes(
                entry["journal_id"], entry["snapshots"]["archive-before"], name="archive-before",
            )
            prefix_state = self._snapshot_bytes(
                entry["journal_id"], entry["snapshots"]["state-before"], name="state-before",
            )
            _ensure_append_population_window(
                json.loads(prefix_state), _records_from_archive(prefix_archive), window_strategy,
                prior_events=tuple(prior_events),
            )
            rejected = self._is_v2() and entry["state"] == "rejected"
            ids = tuple(entry["rejected"]["candidate_ids"] if rejected else entry["staged"]["candidate_ids"])
            if seen_candidates.intersection(ids):
                _fail("duplicate_candidate")
            seen_candidates.update(ids)
            if not rejected:
                prior_events.append(ids)
                published_head = entry
            if self._is_v2():
                self._verify_entry_native_settlement(entry)
            previous = entry
        selected_head = published_head if self._is_v2() else previous
        expected_head = None if selected_head is None else {
            "journal_id": selected_head["journal_id"],
            "terminal_sha256": selected_head["terminal"]["terminal_sha256"],
            "lineage_sha256": selected_head["terminal"]["descriptor_sha256"],
        }
        if wire["head"] != expected_head:
            _fail("head_drift")
        if previous is not None and (archive != head_archive or state_bytes != head_state):
            _fail("current_head_drift")
        if previous is not None:
            sources = previous["before_sources"] if self._is_v2() and previous["state"] == "rejected" else previous["head_sources"]
            for name, pin in sources.items():
                extension = "jsonl" if name == "archive" else "json"
                path = self._workspace / "evolution" / f"{name}.{extension}"
                if self._is_v2() and pin.get("missing") is True:
                    if name != "archive" or _root_pin(path.parent) != pin["parent"]:
                        _fail("source_absence_drift")
                    try:
                        path.lstat()
                    except FileNotFoundError:
                        pass
                    else:
                        _fail("source_absence_drift")
                else:
                    verify_persisted_lineage_snapshot(path, LineageSnapshotPin.from_dict(pin))
        if marker_pin is not None:
            _check_held_publication_lock()
            self._check_owner()
            if (self._strategy is not original_strategy
                    or original_strategy is not self._gateway.producer_config.inputs.native_context.strategy
                    or original_strategy.context.workspace.expanduser().absolute() != self._workspace):
                _fail("precommit_strategy_invalid")
            try:
                if _load_marker(marker_path)[1] != expected_marker:
                    _fail("precommit_marker_invalid")
                verify_persisted_lineage_snapshot(marker_path, marker_pin)
            except (ProducerBundleLineageError, ProducerBundlePublicationStagingError) as exc:
                raise RSILearningError("rsi_publication_lineage_precommit_marker_invalid") from exc
        return tuple(prior_events)


class _V2LineageEvidenceReader(_LineageEvidenceReader):
    """Mixed attempted history; observations never acquire an execution continuation."""

    __slots__ = ()

    @staticmethod
    def _rejection_index(batches: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{"ordinal": entry["ordinal"], "journal_id": entry["journal_id"],
                 "rejected_sha256": entry["rejected"]["descriptor_sha256"]}
                for entry in batches if entry["state"] == "rejected"]

    @staticmethod
    def _previous_v2(previous: dict[str, Any] | None) -> dict[str, Any]:
        links = {name: None for name in (
            "previous_attempt_journal_id", "previous_attempt_outcome", "previous_attempt_terminal_sha256",
            "previous_attempt_lineage_sha256", "published_predecessor_journal_id",
            "published_predecessor_terminal_sha256", "published_predecessor_lineage_sha256",
        )}
        if previous is None:
            return links
        if previous.get("state") not in {"terminal", "rejected"}:
            _fail("pending_predecessor")
        published = previous["state"] == "terminal"
        terminal = previous["terminal"] if published else previous["rejected"]
        links.update(
            previous_attempt_journal_id=previous["journal_id"],
            previous_attempt_outcome="published" if published else "all_rejected",
            previous_attempt_terminal_sha256=terminal["terminal_sha256" if published else "terminal_journal_sha256"],
            previous_attempt_lineage_sha256=terminal["descriptor_sha256"],
        )
        if published:
            links.update(published_predecessor_journal_id=previous["journal_id"],
                         published_predecessor_terminal_sha256=terminal["terminal_sha256"],
                         published_predecessor_lineage_sha256=terminal["descriptor_sha256"])
        else:
            links.update({name: previous["before"][name] for name in links if name.startswith("published_")})
        return links

    def _verify_before_predecessors_v2(self, before: ProducerLineageBeforeIntentV2,
                                       previous: dict[str, Any] | None) -> None:
        if (type(before) is not ProducerLineageBeforeIntentV2
                or before.ordinal != (0 if previous is None else previous["ordinal"] + 1)
                or any(getattr(before, name) != value for name, value in self._previous_v2(previous).items())):
            _fail("predecessor_mismatch")

    def _validate_entry_shape_v2(self, entry: dict[str, Any]) -> None:
        from .rsi_producer_staging_capsule import _shape

        _shape(entry)
        if type(entry) is not dict:
            _fail("history_invalid")
        base = {"journal_id", "ordinal", "episode_id", "request_sha256", "memory_snapshot_sha256",
                "native_plan_sha256", "admission_plan", "prepared_journal", "before", "before_file_pin",
                "snapshots", "before_sources", "state", "evidence_pins"}
        phase = entry.get("state")
        staged_fields = {"staged", "staged_file_pin", "state_projection_sha256", "after_sources"}
        terminal_fields = {"terminal", "terminal_file_pin", "published_journal", "head_sources"}
        rejected_fields = {"rejected", "rejected_file_pin", "rejected_journal", "rejection_provenance"}
        expected = base | (staged_fields if phase in {"staged", "terminal"} else set())
        expected |= terminal_fields if phase == "terminal" else rejected_fields if phase == "rejected" else set()
        snapshots = {"archive-before", "state-before"}
        if phase in {"staged", "terminal"}:
            snapshots |= {"archive-after", "state-after"}
        pins = {"journal.prepared.json"}
        if phase in {"staged", "terminal"}:
            pins |= {"journal.staged.json", "manifest.json", "preflight.json"}
        if phase == "terminal":
            pins |= {"journal.published.json", "terminal.json"}
        if phase == "rejected":
            rejected = ProducerLineageRejectedTerminalV2.from_dict(entry.get("rejected"))
            pins |= {"journal.json", "rejections.json", *("rejections/" + item + ".json" for item in rejected.candidate_ids)}
            reference = entry["rejection_provenance"]
            if reference is not None:
                if (type(reference) is not dict or set(reference) != {"provenance_sha256", "file_pin"}
                        or type(reference["provenance_sha256"]) is not str
                        or len(reference["provenance_sha256"]) != 64
                        or any(c not in "0123456789abcdef" for c in reference["provenance_sha256"])):
                    _fail("rejection_provenance_invalid")
                NativeRSIRejectionFilePin.from_dict(reference["file_pin"])
        if (type(entry) is not dict or phase not in {"before", "staged", "terminal", "rejected"}
                or set(entry) != expected or type(entry.get("snapshots")) is not dict
                or set(entry["snapshots"]) != snapshots or type(entry.get("evidence_pins")) is not dict
                or (set(entry["evidence_pins"]) != pins and not (phase == "before" and not entry["evidence_pins"]))):
            _fail("history_phase_pins_invalid")
        before = ProducerLineageBeforeIntentV2.from_dict(entry["before"])
        if (before.run_id != self._run_id or before.journal_id != entry["journal_id"]
                or before.ordinal != entry["ordinal"] or before.archive.to_dict() != entry["snapshots"]["archive-before"]
                or before.state.to_dict() != entry["snapshots"]["state-before"]):
            _fail("history_invalid")
        for name, pin in entry["snapshots"].items():
            if LineageSnapshotPin.from_dict(pin).name != name + ".snapshot":
                _fail("history_phase_pins_invalid")
        for name, pin in entry["evidence_pins"].items():
            expected_name = "rejection-" + _sha(name.encode()) if name.startswith("rejections/") else name
            if LineageSnapshotPin.from_dict(pin).name != expected_name:
                _fail("history_phase_pins_invalid")
        for kind in ("before", "staged", "terminal", "rejected"):
            if kind + "_file_pin" in entry:
                name = "before-v2.json" if kind == "before" else kind + ".json"
                if LineageSnapshotPin.from_dict(entry[kind + "_file_pin"]).name != name:
                    _fail("history_phase_pins_invalid")
        self._validate_source_pin_maps_v2(entry)

    def _validate_source_pin_maps_v2(self, entry: dict[str, Any]) -> None:
        maps = ["before_sources"]
        if entry["state"] in {"staged", "terminal"}:
            maps.append("after_sources")
        if entry["state"] == "terminal":
            maps.append("head_sources")
        for field in maps:
            sources = entry.get(field)
            if type(sources) is not dict or set(sources) != {"archive", "state"}:
                _fail("source_pins_invalid")
            for name, raw in sources.items():
                if field == "before_sources" and name == "archive" and type(raw) is dict and raw.get("missing") is True:
                    if (set(raw) != {"missing", "parent"}
                            or entry["before"]["published_predecessor_journal_id"] is not None
                            or raw["parent"] != _root_pin(self._workspace / "evolution")
                            or entry["snapshots"]["archive-before"]["size"] != 0
                            or entry["snapshots"]["archive-before"]["sha256"] != _sha(b"")):
                        _fail("source_pins_invalid")
                    continue
                pin = LineageSnapshotPin.from_dict(raw)
                suffix = "after" if field == "after_sources" else "before"
                snapshot_suffix = "before" if field == "before_sources" else "after"
                snapshot = LineageSnapshotPin.from_dict(entry["snapshots"][name + "-" + snapshot_suffix])
                if pin.name != name + "-" + suffix or pin.sha256 != snapshot.sha256 or pin.size != snapshot.size:
                    _fail("source_pins_invalid")
        if entry["state"] == "terminal":
            for name in ("archive", "state"):
                source = LineageSnapshotPin.from_dict(entry["after_sources"][name])
                head = LineageSnapshotPin.from_dict(entry["head_sources"][name])
                if any(getattr(source, field) != getattr(head, field) for field in (
                    "device", "inode", "size", "mode", "nlink", "mtime_ns", "sha256",
                )):
                    _fail("source_pins_invalid")

    def _validate_history_v2(self, state: dict[str, Any]) -> None:
        from .rsi_producer_staging_capsule import retained_publication_evidence_bytes

        retained_publication_evidence_bytes(state)
        previous = None
        for _head, snapshot in self._ledger.controller_checkpoint_history(self._run_id):
            retained_publication_evidence_bytes(snapshot)
            wire = snapshot.get(_FIELD)
            if wire is None:
                if previous is not None:
                    _fail("history_drift")
                continue
            if (type(wire) is not dict or set(wire) != {*self._association, "batches", "head", "rejections"}
                    or any(wire[key] != value for key, value in self._association.items())
                    or type(wire["batches"]) is not list or len(wire["batches"]) > MAX_LINEAGE_BATCHES
                    or type(wire["rejections"]) is not list):
                _fail("history_invalid")
            if previous is None and (len(wire["batches"]) > 1 or (wire["batches"] and (
                    wire["batches"][0].get("state") != "before" or wire["batches"][0].get("evidence_pins") != {}))):
                _fail("history_introduction_invalid")
            published_head = None
            attempted = None
            seen_journals = set()
            for ordinal, entry in enumerate(wire["batches"]):
                self._validate_entry_shape_v2(entry)
                if entry["ordinal"] != ordinal or entry["journal_id"] in seen_journals:
                    _fail("history_invalid")
                seen_journals.add(entry["journal_id"])
                self._verify_before_predecessors_v2(ProducerLineageBeforeIntentV2.from_dict(entry["before"]), attempted)
                if entry["state"] == "terminal":
                    terminal = ProducerLineageTerminal.from_dict(entry["terminal"])
                    published_head = {"journal_id": terminal.journal_id, "terminal_sha256": terminal.terminal_sha256,
                                      "lineage_sha256": terminal.digest()}
                elif entry["state"] != "rejected" and ordinal != len(wire["batches"]) - 1:
                    _fail("history_invalid")
                attempted = entry
            if wire["head"] != published_head or wire["rejections"] != self._rejection_index(wire["batches"]):
                _fail("history_head_invalid")
            if previous is not None:
                old, new = previous["batches"], wire["batches"]
                if len(new) < len(old) or len(new) > len(old) + 1:
                    _fail("history_drift")
                if len(new) == len(old) + 1 and (
                    new[-1]["state"] != "before" or new[-1]["evidence_pins"] != {}
                    or any(entry["state"] not in {"terminal", "rejected"}
                           or (entry["state"] == "rejected" and entry["rejection_provenance"] is None) for entry in old)
                ):
                    _fail("history_introduction_invalid")
                for index, entry in enumerate(old):
                    current = new[index]
                    for key, value in entry.items():
                        if key in {"snapshots", "evidence_pins"}:
                            if any(current[key].get(name) != pin for name, pin in value.items()):
                                _fail("history_drift")
                        elif key == "rejection_provenance" and value is None:
                            continue
                        elif key != "state" and current.get(key) != value:
                            _fail("history_drift")
                    allowed = {"before": {"before", "staged", "rejected"}, "staged": {"staged", "terminal"},
                               "terminal": {"terminal"}, "rejected": {"rejected"}}
                    if current["state"] not in allowed[entry["state"]]:
                        _fail("history_drift")
                    if entry["state"] == "before" and current["state"] != "before" and set(entry["evidence_pins"]) != {"journal.prepared.json"}:
                        _fail("history_prepared_pin_missing")
                if wire["rejections"][:len(previous["rejections"])] != previous["rejections"]:
                    _fail("history_drift")
            previous = wire
        if state.get(_FIELD) != previous:
            _fail("history_drift")

    def _binding_for_rejected_entry(self, entry: dict[str, Any]) -> RejectionLineageC1Binding:
        from .rsi_producer_staging_capsule import retained_publication_evidence_bytes

        candidates = []
        prior = None
        for head, state in self._ledger.controller_checkpoint_history(self._run_id):
            batches = state.get(_FIELD, {}).get("batches", [])
            if len(batches) <= entry["ordinal"]:
                continue
            observed = batches[entry["ordinal"]]
            if observed["state"] == "rejected" and (prior is None or prior["state"] != "rejected"):
                if (prior is None or prior["state"] != "before" or observed["rejection_provenance"] is not None
                        or observed["rejected"] != entry["rejected"]):
                    _fail("rejection_c1_history_invalid")
                candidates.append((head, state))
            prior = observed
        if len(candidates) != 1:
            _fail("rejection_c1_history_invalid")
        head, state = candidates[0]
        rejected = ProducerLineageRejectedTerminalV2.from_dict(entry["rejected"])
        return RejectionLineageC1Binding(
            run_id=self._run_id, episode_id=entry["episode_id"], journal_id=entry["journal_id"], ordinal=entry["ordinal"],
            checkpoint_sha256=head, rejected_sha256=rejected.digest(), retained_bytes=retained_publication_evidence_bytes(state),
            **{name: getattr(rejected, name) for name in (
                "before_sha256", "prepared_journal_sha256", "terminal_journal_sha256", "rejection_manifest_sha256",
                "terminal_marker_sha256", "candidate_ids", "archive_sha256", "state_sha256",
            )},
        )

    def _rejection_pinned_evidence(self, entry: dict[str, Any]) -> NativeRSIRejectionEvidence:
        reference = entry["rejection_provenance"]
        if reference is None:
            _fail("rejection_c2_required")
        pin = NativeRSIRejectionFilePin.from_dict(reference["file_pin"])
        evidence = read_native_rsi_rejection_provenance(
            self._workspace / "evolution/producer-batches" / entry["journal_id"], expected_file_pin=pin,
        )
        if (evidence.provenance_sha256 != reference["provenance_sha256"]
                or evidence.lineage != self._binding_for_rejected_entry(entry)
                or evidence.rejected.to_dict() != entry["rejected"]
                or evidence.terminal.to_dict() != entry["rejected_journal"]
                or dict(evidence.ledger_identity) != self._gateway._ledger_identity):
            _fail("rejection_provenance_drift")
        return evidence

    def _entry_native_association(self, entry: dict[str, Any]) -> tuple[SolverRequest, NativeRSIExecutionPlan, Any, Any]:
        from .rsi_producer_staging_capsule import materialize_ready

        checkpoint = self._ledger.controller_checkpoint(self._run_id)
        if checkpoint is None:
            _fail("inspection_checkpoint_drift")
        state = checkpoint[1]
        intent = state.get("intents", {}).get(entry["episode_id"])
        ready = state.get("producer_episode_staging", {}).get(entry["episode_id"], {}).get("ready")
        reference = state.get("python_admission_refs", {}).get(entry["episode_id"])
        if type(intent) is not dict or type(ready) is not dict or type(reference) is not dict:
            _fail("inspection_child_association_invalid")
        ready = materialize_ready(ready, allow_capsule=True, expected_workspace=self._workspace,
                                  expected_journal_id=entry["journal_id"])
        request = SolverRequest.from_dict(intent["request"])
        plan = NativeRSIExecutionPlan.from_dict(ready["plan"])
        memory = self._controller._native_historical_memory(self._run_id, request)
        claim = self._ledger.inspect_native_episode_claim(request, plan_sha256=plan.plan_sha256)
        result = self._ledger.episode_result(entry["episode_id"])
        if (entry["request_sha256"] != request.digest() or entry["memory_snapshot_sha256"] != memory.digest()
                or plan.request != request or plan.memory_snapshot_sha256 != memory.digest()
                or entry["native_plan_sha256"] != plan.plan_sha256 or plan.journal_id != entry["journal_id"]
                or reference.get("native_plan") != plan.to_dict() or reference.get("prepared_journal") != entry["prepared_journal"]
                or claim is None):
            _fail("inspection_child_association_invalid")
        return request, plan, claim, result

    def _verify_entry_native_settlement(self, entry: dict[str, Any]) -> None:
        request, plan, claim, result = self._entry_native_association(entry)
        if entry["state"] == "terminal":
            if claim.status != "completed" or result is None or result[0] != request or result[1].status != "completed":
                _fail("pending_predecessor")
            self._verify_durable_native_result(entry, request, plan, result[1])
            return
        evidence = self._rejection_pinned_evidence(entry)
        if evidence.plan != plan or evidence.claim.claim_sha256 != claim.claim_sha256:
            _fail("rejection_claim_drift")
        if type(self) is StartedRSIRejectionInspection and entry["episode_id"] == self._request.episode_id:
            if claim != self._claim or claim.status != "started" or result is not None:
                _fail("inspection_started_claim_required")
            return
        if claim.status != "failed" or result is None or result[0] != request:
            _fail("pending_predecessor")
        if result[1] != map_native_rejection_to_solver_result(request, plan, evidence):
            _fail("inspection_native_result_drift")
        if self._rejection_pinned_evidence(entry) != evidence:
            _fail("rejection_provenance_drift")

    def _verify_rejected_entry(self, entry: dict[str, Any], *, ordinal: int,
                               previous: dict[str, Any] | None):
        from .producer_bundle_admission import parse_producer_bundle_admission_plan
        from .producer_bundle_publication import parse_producer_bundle_publication_journal
        from .producer_bundle_rejection import _verify_terminal_batch_rejection_evidence

        self._validate_entry_shape_v2(entry)
        before = self._verify_descriptor(entry, "before")
        rejected = self._verify_descriptor(entry, "rejected")
        self._verify_before_predecessors_v2(before, previous)
        if (rejected.ordinal != ordinal or rejected.run_id != self._run_id
                or rejected.journal_id != entry["journal_id"] or rejected.episode_id != entry["episode_id"]
                or rejected.before_sha256 != before.digest()):
            _fail("rejected_association_invalid")
        archive = self._snapshot_bytes(entry["journal_id"], entry["snapshots"]["archive-before"], name="archive-before")
        state_bytes = self._snapshot_bytes(entry["journal_id"], entry["snapshots"]["state-before"], name="state-before")
        if rejected.archive_sha256 != _sha(archive) or rejected.state_sha256 != _sha(state_bytes):
            _fail("snapshot_drift")
        if previous is not None:
            suffix = "before" if previous["state"] == "rejected" else "after"
            for name, raw in (("archive", archive), ("state", state_bytes)):
                if raw != self._snapshot_bytes(previous["journal_id"], previous["snapshots"][name + "-" + suffix], name=name + "-" + suffix):
                    _fail("snapshot_continuity_drift")
            sources = previous["before_sources"] if suffix == "before" else previous["head_sources"]
            if entry["before_sources"] != sources:
                _fail("source_continuity_drift")
        prepared = parse_producer_bundle_publication_journal(entry["prepared_journal"])
        terminal = parse_producer_bundle_publication_journal(entry["rejected_journal"])
        plan = parse_producer_bundle_admission_plan(entry["admission_plan"])
        if (prepared.digest() != rejected.prepared_journal_sha256 or terminal.digest() != rejected.terminal_journal_sha256
                or prepared.journal_id != before.journal_id or prepared.run_id != self._run_id
                or prepared.task_id != entry["episode_id"] or prepared.admission_sha256 != plan.digest()
                or prepared.base_archive_sha256 != before.archive.sha256 or prepared.base_state_sha256 != before.state.sha256):
            _fail("prepared_association_drift")
        batch = self._workspace / "evolution/producer-batches" / entry["journal_id"]
        for name, pin in entry["evidence_pins"].items():
            verify_persisted_lineage_snapshot(batch / name, LineageSnapshotPin.from_dict(pin))
        observed = _verify_terminal_batch_rejection_evidence(self._workspace, batch, prepared, terminal=terminal)
        if (observed.manifest_sha256 != rejected.rejection_manifest_sha256
                or observed.candidate_ids != rejected.candidate_ids
                or terminal.terminal_marker_sha256 != rejected.terminal_marker_sha256):
            _fail("rejected_evidence_drift")
        for name, pin in entry["evidence_pins"].items():
            verify_persisted_lineage_snapshot(batch / name, LineageSnapshotPin.from_dict(pin))
        self._verify_descriptor(entry, "before")
        self._verify_descriptor(entry, "rejected")
        self._snapshot_bytes(entry["journal_id"], entry["snapshots"]["archive-before"], name="archive-before")
        self._snapshot_bytes(entry["journal_id"], entry["snapshots"]["state-before"], name="state-before")
        return archive, state_bytes


class RSIPublicationLineage(_V2LineageEvidenceReader):
    """One original DRS owner's ephemeral publication/CAS continuation.

    Construction requires the current controller scope. Retained descriptors are
    observations rather than reusable execution permits; recovery cannot recreate
    this object from their files. No method acquires the controller lock.
    """

    __slots__ = (
        "_admission_plan",
        "_association",
        "_claim",
        "_context",
        "_controller",
        "_dispatch_lease",
        "_episode_head",
        "_gateway",
        "_head",
        "_ledger",
        "_memory",
        "_native_configuration",
        "_payload",
        "_pending_wire",
        "_phase",
        "_plan",
        "_poisoned",
        "_policy",
        "_prepared",
        "_prepared_ack",
        "_request",
        "_run_head",
        "_run_id",
        "_sidecar",
        "_strategy",
        "_terminal_evidence_sha256",
        "_thread",
        "_workspace",
    )

    def __init__(self, controller: Any, *, request: SolverRequest,
                 memory: MemorySnapshot, native_plan: NativeRSIExecutionPlan) -> None:
        from .rsi_controller import RSILearningController, _PythonAdmissionFlowContext
        from .rsi_native_scheduler import NativeRSISchedulerProvider
        from .rsi_producer_gateway import PythonProducerRSISolverGateway
        from .rsi_python_scheduler_inputs import _request_memory
        from .rsi_store import RSILedger

        if type(self) is not RSIPublicationLineage or type(controller) is not RSILearningController:
            _fail("owner_invalid")
        if type(controller.ledger) is not RSILedger:
            _fail("ledger_invalid")
        policy = multi_episode_publication_policy(controller)
        if policy is None:
            _fail("opt_in_required")
        lease = controller._producer_publication_dispatch
        if (type(lease) is not tuple or len(lease) != 5
                or request is not lease[2] or native_plan is not lease[4]
                or type(lease[1]) is not PythonProducerRSISolverGateway
                or lease[1] is controller.gateway or lease[1].ledger is not controller.ledger
                or type(lease[1].config.receipt_provider) is not NativeRSISchedulerProvider
                or lease[1].config.receipt_provider._python_admission_controller is not controller):
            _fail("dispatch_lease_invalid")
        parsed_request, parsed_memory = _request_memory(request, memory)
        _lease_request, lease_memory = _request_memory(lease[2], lease[3])
        if lease_memory.to_bytes() != parsed_memory.to_bytes():
            _fail("dispatch_memory_mismatch")
        if type(native_plan) is not NativeRSIExecutionPlan:
            _fail("plan_invalid")
        from .rsi_python_admission import validate_rsi_python_admission_shapes

        validate_rsi_python_admission_shapes(native_plan, dto_types=(NativeRSIExecutionPlan, SolverRequest))
        plan = NativeRSIExecutionPlan.from_dict(native_plan.to_dict())
        if (plan != native_plan or plan.request != parsed_request
                or plan.memory_snapshot_sha256 != parsed_memory.digest()):
            _fail("plan_mismatch")
        state, head = controller._python_admission_active_flow(plan.run_id, parsed_request.episode_id)
        context = controller._python_admission_flow_local.active
        if (type(context) is not _PythonAdmissionFlowContext or state.get("mode") != "drs"
                or state.get("producer_multi_episode_publication") is not True
                or state.get("producer_child_execution") is not True or lease[0] is not state):
            _fail("scope_invalid")
        if (policy["protocol"] == _PROTOCOL_V2
                and state.get("producer_known_rejection") is not True):
            _fail("scope_invalid")
        existing = getattr(controller._python_admission_flow_local, "publication_lineage_owner", None)
        if type(existing) is RSIPublicationLineage and existing._context is context:
            _fail("owner_already_created")
        self._controller, self._ledger, self._gateway = controller, context.ledger, controller.gateway
        self._dispatch_lease = lease
        self._workspace, self._sidecar, self._thread = context.workspace, context.sidecar, get_ident()
        self._context, self._head, self._payload = context, head, context.payload
        self._request, self._memory, self._plan = parsed_request, parsed_memory, plan
        self._run_id = plan.run_id
        self._policy = _raw(policy)
        with self._ledger.read_only_observations():
            run = self._ledger.get_run(plan.run_id)
            original = self._ledger.history(plan.run_id)[0]
            claim = self._ledger.inspect_native_episode_claim(request, plan_sha256=plan.plan_sha256)
            episode = self._ledger.get_episode(request.episode_id)
        if run is None or run.state != "running":
            _fail("run_invalid")
        if (claim is None or claim.status != "started" or episode is None or episode.state != "running"
                or episode.request_sha256 != parsed_request.digest()):
            _fail("dispatch_claim_invalid")
        self._claim, self._episode_head = claim, episode.record_sha256
        self._run_head = run.record_sha256
        self._association = {
            "protocol": policy["protocol"], "run_id": plan.run_id,
            "workspace": _root_pin(self._workspace),
            "run_request_sha256": original.request_sha256,
            "root_proof_sha256": _sha(_raw(original.payload.get("producer_checkpoint_binding"))),
            "policy_sha256": _sha(self._policy), "max_batches": MAX_LINEAGE_BATCHES,
        }
        self._prepared = self._admission_plan = self._strategy = self._native_configuration = None
        self._phase, self._pending_wire, self._poisoned, self._prepared_ack = "new", None, False, False
        self._terminal_evidence_sha256 = None
        self._check_owner(registered=False)
        controller._python_admission_flow_local.publication_lineage_owner = self

    def _check_owner(self, *, registered: bool = True, check_budget: bool = True) -> dict[str, Any]:
        from .rsi_controller import RSILearningController
        from .rsi_native_scheduler import NativeRSISchedulerProvider
        from .rsi_producer_gateway import PythonProducerRSISolverGateway
        from .rsi_python_admission import validate_rsi_python_admission_shapes
        from .rsi_python_scheduler_inputs import _request_memory

        controller = self._controller
        if (type(self) is not RSIPublicationLineage or self._poisoned
                or type(controller) is not RSILearningController or get_ident() != self._thread
                or controller.ledger is not self._ledger or controller.gateway is not self._gateway
                or controller.producer_workspace is not self._workspace
                or controller.producer_sidecar is not self._sidecar
                or controller._producer_publication_dispatch is not self._dispatch_lease
                or type(self._dispatch_lease[1]) is not PythonProducerRSISolverGateway
                or self._dispatch_lease[1].ledger is not self._ledger
                or type(self._dispatch_lease[1].config.receipt_provider) is not NativeRSISchedulerProvider
                or self._dispatch_lease[1].config.receipt_provider._python_admission_controller is not controller
                or type(self._gateway) is not PythonProducerRSISolverGateway
                or self._gateway.ledger is not self._ledger
                or (registered and getattr(controller._python_admission_flow_local,
                                           "publication_lineage_owner", None) is not self)):
            _fail("owner_drift")
        if _raw(multi_episode_publication_policy(controller)) != self._policy:
            _fail("policy_drift")
        request, memory = _request_memory(self._dispatch_lease[2], self._dispatch_lease[3])
        validate_rsi_python_admission_shapes(
            self._dispatch_lease[4], dto_types=(NativeRSIExecutionPlan, SolverRequest),
        )
        try:
            plan = NativeRSIExecutionPlan.from_dict(self._dispatch_lease[4].to_dict())
        except NativeRSIExecutionPlanError as exc:
            raise RSILearningError("rsi_publication_lineage_dispatch_inputs_drift") from exc
        if (request != self._request or memory.to_bytes() != self._memory.to_bytes()
                or plan != self._plan):
            _fail("dispatch_inputs_drift")
        state, head = controller._python_admission_active_flow(self._plan.run_id, self._request.episode_id)
        if (controller._python_admission_flow_local.active is not self._context
                or head != self._head or self._context.payload != self._payload
                or state is not self._context.state or self._dispatch_lease[0] is not state
                or _root_pin(self._workspace) != self._association["workspace"]):
            _fail("checkpoint_drift")
        intent = state.get("intents", {}).get(self._request.episode_id)
        ready = state.get("producer_episode_staging", {}).get(self._request.episode_id, {}).get("ready")
        self._validate_history(state)
        from .rsi_producer_staging_capsule import materialize_ready

        if type(ready) is dict:
            ready = materialize_ready(
                ready, allow_capsule=state.get("producer_multi_episode_publication") is True,
                expected_workspace=self._workspace, expected_journal_id=self._plan.journal_id,
            )
        if (type(intent) is not dict or intent.get("request") != self._request.to_dict()
                or self._plan.memory_snapshot_sha256 != self._memory.digest()
                or type(ready) is not dict or ready.get("plan") != self._plan.to_dict()):
            _fail("request_memory_drift")
        with self._ledger.read_only_observations():
            self._gateway._assert_ledger()
            self._dispatch_lease[1]._assert_ledger()
            run = self._ledger.get_run(self._plan.run_id)
            if run is None or run.state != "running" or run.record_sha256 != self._run_head:
                _fail("run_drift")
            claim = self._ledger.inspect_native_episode_claim(self._request, plan_sha256=self._plan.plan_sha256)
            episode = self._ledger.get_episode(self._request.episode_id)
            if (claim != self._claim or claim.status != "started" or episode is None
                    or episode.state != "running" or episode.record_sha256 != self._episode_head
                    or episode.request_sha256 != self._request.digest()):
                _fail("dispatch_claim_drift")
            controller._validate_run_checkpoint_producer_binding(run, state)
            original = self._ledger.history(self._plan.run_id)[0]
            if (original.request_sha256 != self._association["run_request_sha256"]
                    or _sha(_raw(original.payload.get("producer_checkpoint_binding")))
                    != self._association["root_proof_sha256"]):
                _fail("root_proof_drift")
            latest = self._ledger.controller_checkpoint(self._plan.run_id)
            if latest is None or latest[0] != self._head or controller._python_admission_flow_payload(latest[1]) != self._payload:
                _fail("checkpoint_drift")
        if check_budget:
            RSIRunBudget.load(state["budget_state"]).check()
        return state

    def validate_launch(self, *, workspace: str | Path, intent: Any) -> None:
        from .producer_launcher import ProducerLaunchIntent

        _publication_shapes(intent)
        self._check_owner()
        sidecar, _proof = self._controller._python_admission_sidecar(self._plan.run_id, self._request.episode_id)
        if (type(workspace) not in {str, type(self._workspace)}
                or Path(workspace).expanduser().absolute() != self._workspace
                or type(intent) is not ProducerLaunchIntent or intent != sidecar.binding.intent
                or intent.intent_sha256 != self._plan.intent_sha256
                or intent.launch_id != self._plan.launch_id
                or (intent.run_id, intent.journal_id, intent.parent_task_id, intent.task_id)
                != (self._plan.run_id, self._plan.journal_id, self._plan.parent_task_id, self._plan.task_id)):
            _fail("launch_mismatch")
        self._check_owner()

    def _wire(self, state: dict[str, Any]) -> dict[str, Any]:
        current = state.get(_FIELD)
        if current is None:
            return {**_copy(self._association), "batches": [], "head": None, "rejections": []}
        return _copy(current)

    def validate_before(self, journal: Any, base_archive: bytes, base_state_bytes: bytes,
                        strategy: Any, *, admission_plan: Any = None) -> tuple[tuple[str, ...], ...]:
        from .evolution import PopulationStrategy
        from .producer_bundle_admission import (
            ProducerBundleAdmissionPlan,
            parse_producer_bundle_admission_plan,
        )
        from .producer_bundle_publication import (
            ProducerBundlePublicationJournal,
            parse_producer_bundle_publication_journal,
        )

        _publication_shapes(journal, admission_plan)
        state = self._check_owner()
        if type(journal) is not ProducerBundlePublicationJournal or type(strategy) is not PopulationStrategy:
            _fail("native_inputs_invalid")
        if type(base_archive) is not bytes or type(base_state_bytes) is not bytes:
            _fail("snapshot_invalid")
        parsed = parse_producer_bundle_publication_journal(journal.to_dict())
        if (parsed != journal or journal.state != "prepared" or journal.run_id != self._plan.run_id
                or journal.journal_id != self._plan.journal_id or journal.task_id != self._plan.task_id
                or journal.parent_task_id != self._plan.parent_task_id
                or journal.base_archive_sha256 != _sha(base_archive) or journal.base_state_sha256 != _sha(base_state_bytes)
                or strategy.context.workspace.expanduser().absolute() != self._workspace
                or strategy is not self._gateway.producer_config.inputs.native_context.strategy):
            _fail("native_inputs_mismatch")
        if admission_plan is not None:
            if type(admission_plan) is not ProducerBundleAdmissionPlan:
                _fail("admission_plan_invalid")
            admission_plan = parse_producer_bundle_admission_plan(admission_plan.to_dict())
            if self._admission_plan is not None and admission_plan != self._admission_plan:
                _fail("admission_plan_drift")
        else:
            admission_plan = self._admission_plan
        if admission_plan is None or admission_plan.digest() != journal.admission_sha256:
            _fail("admission_plan_mismatch")
        if self._prepared is not None and self._prepared != journal:
            _fail("prepared_journal_drift")
        if self._strategy is not None and strategy is not self._strategy:
            _fail("strategy_drift")
        native_config = _raw({"authority": strategy.integrity_authority.to_dict(), "config": json.loads(base_state_bytes)["config"]})
        if self._native_configuration is not None and native_config != self._native_configuration:
            _fail("native_configuration_drift")
        self._strategy = strategy
        wire = self._wire(state)
        completed = wire["batches"]
        if self._phase in {"before", "staged"}:
            if not completed or completed[-1]["journal_id"] != journal.journal_id:
                _fail("own_batch_missing")
            completed = completed[:-1]
            wire = {**wire, "batches": completed}
        if len(completed) >= MAX_LINEAGE_BATCHES or any(x["journal_id"] == journal.journal_id for x in completed):
            _fail("capacity_exceeded")
        self._verify_live_bytes(base_archive, base_state_bytes)
        _require_marker_absent(self._workspace)
        events = self._verify_chain(wire, base_archive, base_state_bytes)
        strategy._validate_candidate_integrity_state(json.loads(base_state_bytes))
        strategy._active(json.loads(base_state_bytes))
        self._check_owner()
        self._prepared, self._admission_plan, self._strategy = journal, admission_plan, strategy
        self._native_configuration = native_config
        return events

    def _verify_live_bytes(self, archive: bytes, state_bytes: bytes) -> None:
        path = self._workspace / "evolution/archive.jsonl"
        try:
            info = path.lstat()
        except FileNotFoundError:
            if archive:
                _fail("current_head_drift")
        else:
            if not stat.S_ISREG(info.st_mode) or _files.read_regular_file(path, MAX_LINEAGE_SNAPSHOT_BYTES) != archive:
                _fail("current_head_drift")
        if _files.read_regular_file(self._workspace / "evolution/state.json", MAX_LINEAGE_SNAPSHOT_BYTES) != state_bytes:
            _fail("current_head_drift")
        if _root_pin(self._workspace) != self._association["workspace"]:
            _fail("workspace_drift")

    def _retain_snapshot(self, journal_id: str, name: str, raw: bytes, *, source: Path | None, total: int):
        if source is None:
            path, pin = persist_lineage_bytes_snapshot(
                self._workspace, journal_id, name=name, raw=raw, expected_sha256=_sha(raw), retained_bytes=total,
            )
        else:
            source_pin = capture_lineage_snapshot_pin(source, name=name)
            if source_pin.sha256 != _sha(raw) or source_pin.size != len(raw):
                _fail("snapshot_source_drift")
            path, pin = persist_lineage_snapshot(
                self._workspace, journal_id, name=name, source=source, expected_pin=source_pin, retained_bytes=total,
            )
        if _files.read_regular_file(path, MAX_LINEAGE_SNAPSHOT_BYTES) != raw:
            _fail("snapshot_copy_drift")
        verify_persisted_lineage_snapshot(path, pin)
        return pin, source_pin if source is not None else None

    def _capacity_check(self, wire: dict[str, Any]) -> None:
        expected = json.loads(self._payload)
        expected[_FIELD] = wire
        try:
            _raw(expected)
        except (ValueError, TypeError) as exc:
            raise RSILearningError("rsi_publication_lineage_capacity_exceeded") from exc

    def _build_before_descriptor(self, journal_id: str, ordinal: int, head: dict[str, Any] | None,
                                 archive_pin: LineageSnapshotPin, state_pin: LineageSnapshotPin):
        if not self._is_v2():
            return ProducerLineageBeforeIntent(self._plan.run_id, journal_id, ordinal,
                head["terminal_sha256"] if head else None, head["lineage_sha256"] if head else None,
                archive_pin, state_pin)
        wire = self._wire(self._check_owner(check_budget=False))
        previous = wire["batches"][ordinal - 1] if ordinal else None
        return ProducerLineageBeforeIntentV2(
            run_id=self._plan.run_id, journal_id=journal_id, ordinal=ordinal,
            archive=archive_pin, state=state_pin, **self._previous_v2(previous),
        )

    def _projected_entry(self, journal: Any, ordinal: int, head: dict[str, Any] | None) -> dict[str, Any]:
        """Upper-bound complete held pins and terminal wire before any create.

        Synthetic values here are only a serialization capacity measurement.
        They never reach a file, checkpoint, verifier, or authority comparison.
        """
        def pin(name):
            maximum = 2**64 - 1
            return LineageSnapshotPin(name, "f" * 64, MAX_LINEAGE_SNAPSHOT_BYTES,
                                      maximum, maximum, maximum, maximum,
                                      mtime_ns=maximum, ctime_ns=maximum).to_dict()

        before = self._build_before_descriptor(
            journal.journal_id, ordinal, head,
            LineageSnapshotPin.from_dict(pin("archive-before.snapshot")),
            LineageSnapshotPin.from_dict(pin("state-before.snapshot")),
        )
        ids = tuple(item.candidate_id for item in journal.candidates)
        staged = ProducerLineageStagedTransition(
            self._plan.run_id, journal.journal_id, ordinal, before.digest(), "f" * 64, "f" * 64,
            "f" * 64, "f" * 64, ids,
        )
        terminal = ProducerLineageTerminal(self._plan.run_id, journal.journal_id, ordinal,
                                          staged.digest(), "f" * 64, "f" * 64, "f" * 64)
        published = _copy(journal.to_dict())
        published.update(state="published", publication_phase="committed", terminal_marker_sha256="f" * 64,
                         archive_after_sha256="f" * 64, state_after_sha256="f" * 64)
        for candidate in published["candidates"]:
            candidate.update(execution_receipt_sha256="f" * 64, evaluation_receipt_sha256="f" * 64,
                             publication_receipt_sha256="f" * 64, status="admitted")
        return {
            "journal_id": journal.journal_id, "ordinal": ordinal, "episode_id": self._request.episode_id,
            "request_sha256": self._request.digest(), "memory_snapshot_sha256": self._memory.digest(),
            "native_plan_sha256": self._plan.plan_sha256, "admission_plan": self._admission_plan.to_dict(),
            "prepared_journal": journal.to_dict(), "before": before.to_dict(),
            "before_file_pin": pin("before-v2.json" if self._is_v2() else "before.json"),
            "staged": staged.to_dict(), "staged_file_pin": pin("staged.json"),
            "terminal": terminal.to_dict(), "terminal_file_pin": pin("terminal.json"),
            "published_journal": published, "state_projection_sha256": "f" * 64, "state": "terminal",
            "snapshots": {name: pin(name + ".snapshot") for name in (
                "archive-before", "state-before", "archive-after", "state-after",
            )},
            "before_sources": {"archive": pin("archive-before"), "state": pin("state-before")},
            "after_sources": {"archive": pin("archive-after"), "state": pin("state-after")},
            "head_sources": {"archive": pin("archive-before"), "state": pin("state-before")},
            "evidence_pins": {name: pin(name) for name in (
                "journal.prepared.json", "journal.staged.json", "manifest.json", "preflight.json", "journal.published.json", "terminal.json",
            )},
        }

    def _projected_rejected_entry(self, journal: Any, ordinal: int, head: dict[str, Any] | None) -> dict[str, Any]:
        """Complete C2 capacity measurement only; never persisted or accepted as evidence."""
        from .rsi_native_provenance_names import NATIVE_RSI_REJECTION_PROVENANCE_NAME
        from .rsi_native_rejection import MAX_NATIVE_RSI_REJECTION_PROVENANCE_BYTES

        entry = self._projected_entry(journal, ordinal, head)
        for name in ("staged", "staged_file_pin", "state_projection_sha256", "after_sources",
                     "terminal", "terminal_file_pin", "published_journal", "head_sources"):
            entry.pop(name)
        entry["snapshots"] = {name: pin for name, pin in entry["snapshots"].items() if name.endswith("before")}
        maximum = 2**64 - 1
        def pin(name):
            return LineageSnapshotPin(name, "f" * 64, MAX_LINEAGE_SNAPSHOT_BYTES, maximum, maximum,
                maximum, maximum, mtime_ns=maximum, ctime_ns=maximum).to_dict()
        ids = tuple(candidate.candidate_id for candidate in journal.candidates)
        terminal = _copy(journal.to_dict())
        terminal.update(state="all_rejected", publication_phase="committed", terminal_marker_sha256="f" * 64,
                        archive_after_sha256=journal.base_archive_sha256, state_after_sha256=journal.base_state_sha256)
        for candidate in terminal["candidates"]:
            candidate.update(status="rejected", execution_receipt_sha256="f" * 64,
                             evaluation_receipt_sha256="f" * 64, publication_receipt_sha256=None)
        rejected = ProducerLineageRejectedTerminalV2(
            run_id=self._run_id, journal_id=journal.journal_id, episode_id=self._request.episode_id, ordinal=ordinal,
            before_sha256=entry["before"]["descriptor_sha256"], prepared_journal_sha256=journal.digest(),
            terminal_journal_sha256="f" * 64, rejection_manifest_sha256="f" * 64, terminal_marker_sha256="f" * 64,
            candidate_ids=ids, archive_sha256=entry["before"]["archive"]["sha256"],
            state_sha256=entry["before"]["state"]["sha256"],
        )
        entry.update(state="rejected", rejected=rejected.to_dict(), rejected_file_pin=pin("rejected.json"),
                     rejected_journal=terminal,
                     evidence_pins={name: pin("rejection-" + _sha(name.encode()) if name.startswith("rejections/") else name)
                         for name in ("journal.prepared.json", "journal.json", "rejections.json",
                                      *("rejections/" + item + ".json" for item in ids))},
                     rejection_provenance={"provenance_sha256": "f" * 64, "file_pin": NativeRSIRejectionFilePin(
                         NATIVE_RSI_REJECTION_PROVENANCE_NAME, "f" * 64, MAX_NATIVE_RSI_REJECTION_PROVENANCE_BYTES,
                         maximum, maximum, maximum, maximum, mtime_ns=maximum, ctime_ns=maximum,
                     ).to_dict()})
        return entry

    def _publication_checkpoint(self, _stage: str) -> None:
        self._check_owner()

    def _terminal_checkpoint(self, _stage: str) -> None:
        self._check_owner(check_budget=False)

    def _verify_before_source_pins(self, entry: dict[str, Any]) -> None:
        for name, held in entry["before_sources"].items():
            extension = "jsonl" if name == "archive" else "json"
            path = self._workspace / "evolution" / f"{name}.{extension}"
            if held.get("missing") is True:
                if (set(held) != {"missing", "parent"} or name != "archive"
                        or _root_pin(path.parent) != held["parent"]):
                    _fail("source_absence_drift")
                try:
                    path.lstat()
                except FileNotFoundError:
                    pass
                else:
                    _fail("source_absence_drift")
            else:
                verify_persisted_lineage_snapshot(path, LineageSnapshotPin.from_dict(held))

    def _verify_after_source_pins(self, entry: dict[str, Any]) -> None:
        batch = self._workspace / "evolution/producer-batches" / entry["journal_id"]
        for name, held in entry["after_sources"].items():
            extension = "jsonl" if name == "archive" else "json"
            verify_persisted_lineage_snapshot(batch / "stage" / f"{name}.{extension}", LineageSnapshotPin.from_dict(held))

    @staticmethod
    def _retained_bytes(wire: dict[str, Any], state: dict[str, Any] | None = None) -> int:
        from .rsi_producer_staging_capsule import (
            retained_publication_evidence_bytes,
            retained_ready_capsule_bytes,
        )

        if wire.get("protocol") == _PROTOCOL_V2:
            return retained_publication_evidence_bytes({**({} if state is None else state),
                "producer_multi_episode_publication": True, "producer_known_rejection": True, _FIELD: wire})
        total = 0 if state is None else retained_ready_capsule_bytes(state)
        total += sum(pin["size"] for entry in wire["batches"] for pin in entry["snapshots"].values())
        if total > MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES:
            _fail("capacity_exceeded")
        return total

    def _ack(self, wire: dict[str, Any]) -> None:
        terminal_evidence = self._is_v2() and self._terminal_evidence_sha256 is not None
        if terminal_evidence and (not wire["batches"] or wire["batches"][-1]["state"] != "rejected"
                or wire["batches"][-1]["rejected"]["terminal_journal_sha256"] != self._terminal_evidence_sha256
                or self._phase not in {"before", "rejected", "rejected-provenance"}):
            _fail("terminal_evidence_ack_invalid")
        self._check_owner(check_budget=self._phase != "staged" and not terminal_evidence)
        self._pending_wire = _raw(wire)
        try:
            self._controller._ack_publication_lineage_for_active_flow(self)
        except BaseException:
            self._poisoned = True
            raise
        finally:
            self._pending_wire = None

    def retain_before(self, journal: Any, base_archive: bytes, base_state_bytes: bytes) -> None:
        from .producer_bundle_staging import _locked

        _publication_shapes(journal)
        if type(base_archive) is not bytes or type(base_state_bytes) is not bytes:
            _fail("snapshot_invalid")
        self._check_owner()
        with _locked(self._workspace, checkpoint=self._publication_checkpoint):
            self._retain_before_locked(journal, base_archive, base_state_bytes)

    def _retain_before_locked(self, journal: Any, base_archive: bytes, base_state_bytes: bytes) -> None:
        if self._phase != "new" or self._prepared != journal:
            _fail("before_state_invalid")
        state = self._check_owner()
        wire = self._wire(state)
        self.validate_before(journal, base_archive, base_state_bytes, self._strategy)
        projected = _copy(wire)
        projected["batches"].append(self._projected_entry(journal, len(wire["batches"]), wire["head"]))
        projected["head"] = {"journal_id": journal.journal_id, "terminal_sha256": "f" * 64, "lineage_sha256": "f" * 64}
        self._capacity_check(projected)
        if self._is_v2():
            rejected_projected = _copy(wire)
            rejected_projected["batches"].append(self._projected_rejected_entry(journal, len(wire["batches"]), wire["head"]))
            rejected_projected["rejections"] = self._rejection_index(rejected_projected["batches"])
            self._capacity_check(rejected_projected)
        total = self._retained_bytes(wire, state)
        if total + len(base_archive) + len(base_state_bytes) > MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES:
            _fail("capacity_exceeded")
        self._verify_live_bytes(base_archive, base_state_bytes)
        journal_id = journal.journal_id
        archive_path = self._workspace / "evolution/archive.jsonl"
        archive_pin, original_archive = self._retain_snapshot(journal_id, "archive-before", base_archive,
                                                             source=archive_path if archive_path.exists() else None, total=total)
        state_pin, original_state = self._retain_snapshot(journal_id, "state-before", base_state_bytes,
                                                         source=self._workspace / "evolution/state.json", total=total + archive_pin.size)
        head = wire["head"]
        before = self._build_before_descriptor(
            journal_id, len(wire["batches"]), head,
            archive_pin, state_pin,
        )
        if self._is_v2():
            _path, pin = persist_lineage_v2_descriptor(self._workspace, before)
        else:
            _path, pin = persist_lineage_descriptor(self._workspace, before)
        entry = {
            "journal_id": journal_id, "ordinal": before.ordinal, "episode_id": self._request.episode_id,
            "request_sha256": self._request.digest(), "memory_snapshot_sha256": self._memory.digest(),
            "native_plan_sha256": self._plan.plan_sha256, "admission_plan": self._admission_plan.to_dict(),
            "prepared_journal": journal.to_dict(), "before": before.to_dict(), "before_file_pin": pin.to_dict(),
            "snapshots": {"archive-before": archive_pin.to_dict(), "state-before": state_pin.to_dict()},
            "before_sources": {"archive": original_archive.to_dict() if original_archive else {
                "missing": True, "parent": _root_pin(archive_path.parent),
            }, "state": original_state.to_dict()},
            "state": "before",
            "evidence_pins": {},
        }
        wire["batches"].append(entry)
        self._verify_live_bytes(base_archive, base_state_bytes)
        self._ack(wire)
        self._phase = "before"

    def acknowledge_prepared(self, journal: Any, record_sha256: str) -> None:
        from .rsi_controller import _PythonAdmissionFlowContext

        _publication_shapes(journal, record_sha256)
        if (type(record_sha256) is not str or len(record_sha256) != 64
                or any(char not in "0123456789abcdef" for char in record_sha256)):
            _fail("prepared_reference_invalid")
        if self._phase != "before" or self._prepared_ack or journal != self._prepared:
            _fail("prepared_ack_invalid")
        controller = self._controller
        context = getattr(controller._python_admission_flow_local, "active", None)
        if (type(context) is not _PythonAdmissionFlowContext or context.state is not self._context.state
                or context.ledger is not self._ledger or context.workspace is not self._workspace
                or context.sidecar is not self._sidecar or context.owner_thread != self._thread
                or (context.run_id, context.episode_id) != (self._plan.run_id, self._request.episode_id)):
            _fail("prepared_ack_invalid")
        old = json.loads(self._payload)
        current = json.loads(context.payload)
        refs = current.get("python_admission_refs", {})
        reference = refs.get(self._request.episode_id)
        if (type(reference) is not dict or reference.get("record_sha256") != record_sha256
                or reference.get("native_plan") != self._plan.to_dict()
                or reference.get("prepared_journal") != journal.to_dict()
                or self._request.episode_id in old.get("python_admission_refs", {})):
            _fail("prepared_reference_invalid")
        expected = _copy(old)
        expected["python_admission_refs"] = old.get("python_admission_refs", {}) | {self._request.episode_id: reference}
        if expected != current or context.payload != controller._python_admission_flow_payload(current):
            _fail("prepared_ack_delta_invalid")
        history = self._ledger.controller_checkpoint_history(self._plan.run_id)
        position = [i for i, (head, _state) in enumerate(history) if head == self._head]
        if (len(position) != 1 or position[0] != len(history) - 2
                or history[-1][0] != context.checkpoint_sha256 or history[-1][1] != current):
            _fail("prepared_ack_revision_invalid")
        with self._ledger.read_only_observations():
            retained = self._ledger.python_admission_record(
                self._plan.run_id, self._request.episode_id, journal.journal_id,
                expected_record_sha256=record_sha256,
            )
            if retained.native_plan_sha256 != self._plan.plan_sha256:
                _fail("prepared_reference_invalid")
            controller._validate_python_admission_references(self._plan.run_id, current)
        self._context, self._head, self._payload = context, context.checkpoint_sha256, context.payload
        self._check_owner()
        from . import producer_bundle_recovery as recovery

        batch = self._workspace / "evolution/producer-batches" / journal.journal_id
        path = batch / "journal.prepared.json"
        if recovery._read_journal(path) != journal:
            _fail("prepared_journal_drift")
        held = capture_lineage_snapshot_pin(path, name="journal.prepared.json")
        recovery._verify_python_handoff(batch, journal, self._admission_plan)
        if recovery._read_journal(path) != journal:
            _fail("prepared_journal_drift")
        verify_persisted_lineage_snapshot(path, held)
        wire = self._wire(self._check_owner())
        entry = wire["batches"][-1]
        if entry["journal_id"] != journal.journal_id or entry["evidence_pins"]:
            _fail("prepared_ack_invalid")
        entry["evidence_pins"] = {"journal.prepared.json": held.to_dict()}
        self._ack(wire)
        self._prepared_ack = True

    def retain_staged(self, staged: Any, manifest: Any) -> None:
        from .producer_bundle_staging import _locked

        _publication_shapes(staged, manifest)
        self._check_owner()
        with _locked(self._workspace, checkpoint=self._publication_checkpoint):
            self._retain_staged_locked(staged, manifest)

    def _retain_staged_locked(self, staged: Any, manifest: Any) -> None:
        from .producer_bundle_staging import ProducerBundlePublicationManifest

        if self._phase != "before" or not self._prepared_ack or type(manifest) is not ProducerBundlePublicationManifest:
            _fail("staged_state_invalid")
        state = self._check_owner()
        wire = self._wire(state)
        entry = wire["batches"][-1]
        projected = _copy(wire)
        projected["batches"][-1] = self._projected_entry(self._prepared, entry["ordinal"], wire["head"])
        projected["head"] = {"journal_id": staged.journal_id, "terminal_sha256": "f" * 64, "lineage_sha256": "f" * 64}
        self._capacity_check(projected)
        self._verify_before_source_pins(entry)
        if (staged.journal_id != self._plan.journal_id or staged.state != "publishing"
                or manifest.journal_id != staged.journal_id or manifest.journal_sha256 != staged.digest()
                or manifest.base_archive_sha256 != self._prepared.base_archive_sha256
                or manifest.base_state_sha256 != self._prepared.base_state_sha256):
            _fail("staged_association_invalid")
        batch = self._workspace / "evolution/producer-batches" / staged.journal_id
        archive = _files.read_regular_file(batch / "stage/archive.jsonl", MAX_LINEAGE_SNAPSHOT_BYTES)
        state_bytes = _files.read_regular_file(batch / "stage/state.json", MAX_LINEAGE_SNAPSHOT_BYTES)
        if _sha(archive) != manifest.archive_after_sha256 or _sha(state_bytes) != manifest.state_after_sha256:
            _fail("staged_snapshot_drift")
        total = self._retained_bytes(wire, state)
        archive_pin, original_archive = self._retain_snapshot(staged.journal_id, "archive-after", archive,
                                                             source=batch / "stage/archive.jsonl", total=total)
        state_pin, original_state = self._retain_snapshot(staged.journal_id, "state-after", state_bytes,
                                                         source=batch / "stage/state.json", total=total + archive_pin.size)
        descriptor = ProducerLineageStagedTransition(
            self._plan.run_id, staged.journal_id, entry["ordinal"], entry["before"]["descriptor_sha256"],
            staged.digest(), manifest.digest(), manifest.archive_after_sha256, manifest.state_after_sha256,
            manifest.candidate_ids,
        )
        _path, pin = persist_lineage_descriptor(self._workspace, descriptor)
        entry.update(staged=descriptor.to_dict(), staged_file_pin=pin.to_dict(), state="staged",
                     state_projection_sha256=_sha(state_bytes),
                     after_sources={"archive": original_archive.to_dict(), "state": original_state.to_dict()})
        entry["snapshots"].update({"archive-after": archive_pin.to_dict(), "state-after": state_pin.to_dict()})
        for name in ("journal.staged.json", "manifest.json", "preflight.json"):
            entry["evidence_pins"][name] = capture_lineage_snapshot_pin(batch / name, name=name).to_dict()
        self._verify_before_source_pins(entry)
        self._verify_after_source_pins(entry)
        self._ack(wire)
        self._phase = "staged"

    def verify_precommit(self, staged: Any, manifest: Any) -> None:
        from .producer_bundle_staging import _HELD_PUBLICATION_LOCKS, _check_held_publication_lock

        _publication_shapes(staged, manifest)
        if self._phase != "staged" or not self._prepared_ack:
            _fail("precommit_state_invalid")
        held = _HELD_PUBLICATION_LOCKS.get()
        if not any(path.parent.parent == self._workspace for path, _fd, _info in held):
            _fail("publication_lock_required")
        _check_held_publication_lock()
        state = self._check_owner()
        wire = self._wire(state)
        entry = wire["batches"][-1]
        before = self._verify_descriptor(entry, "before")
        transition = self._verify_descriptor(entry, "staged")
        if (staged.journal_id != self._plan.journal_id or staged.digest() != transition.journal_sha256
                or manifest.digest() != transition.manifest_sha256):
            _fail("precommit_association_invalid")
        snapshots = entry["snapshots"]
        self._verify_before_source_pins(entry)
        self._verify_after_source_pins(entry)
        archive = self._snapshot_bytes(staged.journal_id, snapshots["archive-before"], name="archive-before")
        state_bytes = self._snapshot_bytes(staged.journal_id, snapshots["state-before"], name="state-before")
        self._verify_live_bytes(archive, state_bytes)
        chain = {**wire, "batches": wire["batches"][:-1]}
        self._verify_chain(chain, archive, state_bytes, precommit=(staged, manifest))
        batch = self._workspace / "evolution/producer-batches" / staged.journal_id
        for name in ("archive", "state"):
            extension = "jsonl" if name == "archive" else "json"
            retained = self._snapshot_bytes(staged.journal_id, snapshots[name + "-after"], name=name + "-after")
            if _files.read_regular_file(batch / "stage" / f"{name}.{extension}", MAX_LINEAGE_SNAPSHOT_BYTES) != retained:
                _fail("staged_snapshot_drift")
        if before.archive.sha256 != self._prepared.base_archive_sha256 or before.state.sha256 != self._prepared.base_state_sha256:
            _fail("precommit_prefix_drift")
        for name, held_pin in entry["evidence_pins"].items():
            verify_persisted_lineage_snapshot(batch / name, LineageSnapshotPin.from_dict(held_pin))
        self._check_owner()

    def retain_terminal(self, published: Any, manifest: Any) -> None:
        from .producer_bundle_staging import _locked

        _publication_shapes(published, manifest)
        self._check_owner(check_budget=False)
        with _locked(self._workspace, checkpoint=self._terminal_checkpoint):
            self._retain_terminal_locked(published, manifest)

    def _retain_terminal_locked(self, published: Any, manifest: Any) -> None:
        from . import producer_bundle_recovery as recovery

        if manifest is None:
            if self._is_v2():
                return self._retain_rejected_locked(published)
            _fail("all_rejected_not_yet_supported")
        if self._phase != "staged":
            _fail("terminal_state_invalid")
        state = self._check_owner(check_budget=False)
        wire = self._wire(state)
        entry = wire["batches"][-1]
        projected = _copy(wire)
        projected["batches"][-1] = self._projected_entry(self._prepared, entry["ordinal"], wire["head"])
        projected["head"] = {"journal_id": published.journal_id, "terminal_sha256": "f" * 64, "lineage_sha256": "f" * 64}
        self._capacity_check(projected)
        if published.journal_id != self._plan.journal_id or published.state != "published":
            _fail("terminal_association_invalid")
        result = recovery.resume_producer_bundle_publication(self._workspace, self._admission_plan, published)
        if result.status != "published" or result.manifest_sha256 != manifest.digest():
            _fail("terminal_association_invalid")
        transition = self._verify_descriptor(entry, "staged")
        if (published.archive_after_sha256 != transition.archive_after_sha256
                or published.state_after_sha256 != transition.state_after_sha256
                or tuple(item.candidate_id for item in published.candidates if item.status == "admitted") != transition.candidate_ids):
            _fail("terminal_association_invalid")
        terminal = ProducerLineageTerminal(
            self._plan.run_id, published.journal_id, entry["ordinal"], transition.digest(),
            published.terminal_marker_sha256, transition.archive_after_sha256, transition.state_after_sha256,
        )
        _path, pin = persist_lineage_descriptor(self._workspace, terminal)
        batch = self._workspace / "evolution/producer-batches" / published.journal_id
        entry.update(terminal=terminal.to_dict(), terminal_file_pin=pin.to_dict(),
                     published_journal=published.to_dict(), state="terminal")
        for name in ("journal.published.json", "terminal.json"):
            entry["evidence_pins"][name] = capture_lineage_snapshot_pin(batch / name, name=name).to_dict()
        entry["head_sources"] = {
            name: capture_lineage_snapshot_pin(
                self._workspace / "evolution" / (name + (".jsonl" if name == "archive" else ".json")),
                name=name + "-before",
            ).to_dict() for name in ("archive", "state")
        }
        wire["head"] = {"journal_id": published.journal_id, "terminal_sha256": terminal.terminal_sha256,
                        "lineage_sha256": terminal.digest()}
        self._ack(wire)
        self._phase = "terminal"

    def _retain_rejected_locked(self, terminal: Any) -> None:
        from .producer_bundle_publication import ProducerBundlePublicationJournal
        from .producer_bundle_rejection import _verify_terminal_batch_rejection_evidence
        from .rsi_native_rejection import MAX_NATIVE_RSI_REJECTION_PROVENANCE_BYTES

        if (not self._is_v2() or self._phase != "before" or not self._prepared_ack
                or type(terminal) is not ProducerBundlePublicationJournal
                or terminal.journal_id != self._plan.journal_id or terminal.state != "all_rejected"):
            _fail("rejected_state_invalid")
        state = self._check_owner(check_budget=False)
        wire = self._wire(state)
        entry = wire["batches"][-1]
        if entry["state"] != "before" or entry["journal_id"] != terminal.journal_id:
            _fail("rejected_association_invalid")
        projected = _copy(wire)
        projected["batches"][-1] = self._projected_rejected_entry(self._prepared, entry["ordinal"], wire["head"])
        projected["rejections"] = self._rejection_index(projected["batches"])
        self._capacity_check(projected)
        self._verify_before_source_pins(entry)
        before = self._verify_descriptor(entry, "before")
        archive = self._snapshot_bytes(entry["journal_id"], entry["snapshots"]["archive-before"], name="archive-before")
        state_bytes = self._snapshot_bytes(entry["journal_id"], entry["snapshots"]["state-before"], name="state-before")
        self._verify_live_bytes(archive, state_bytes)
        _require_marker_absent(self._workspace)
        batch = self._workspace / "evolution/producer-batches" / terminal.journal_id
        verify_persisted_lineage_snapshot(batch / "journal.prepared.json",
                                         LineageSnapshotPin.from_dict(entry["evidence_pins"]["journal.prepared.json"]))
        observed = _verify_terminal_batch_rejection_evidence(self._workspace, batch, self._prepared, terminal=terminal)
        pins = {name: capture_lineage_snapshot_pin(batch / name,
                name="rejection-" + _sha(name.encode()) if name.startswith("rejections/") else name).to_dict()
                for name in ("journal.json", "rejections.json",
                             *("rejections/" + item + ".json" for item in observed.candidate_ids))}
        if _verify_terminal_batch_rejection_evidence(self._workspace, batch, self._prepared, terminal=terminal) != observed:
            _fail("rejected_evidence_drift")
        for name, pin in pins.items():
            verify_persisted_lineage_snapshot(batch / name, LineageSnapshotPin.from_dict(pin))
        rejected = ProducerLineageRejectedTerminalV2(
            run_id=self._run_id, journal_id=terminal.journal_id, episode_id=self._request.episode_id,
            ordinal=entry["ordinal"], before_sha256=before.digest(), prepared_journal_sha256=self._prepared.digest(),
            terminal_journal_sha256=terminal.digest(), rejection_manifest_sha256=observed.manifest_sha256,
            terminal_marker_sha256=terminal.terminal_marker_sha256, candidate_ids=observed.candidate_ids,
            archive_sha256=_sha(archive), state_sha256=_sha(state_bytes),
        )
        total = self._retained_bytes(wire, state) + sum(pin["size"] for pin in pins.values())
        if total + len(_raw(rejected.to_dict())) + MAX_NATIVE_RSI_REJECTION_PROVENANCE_BYTES > MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES:
            _fail("capacity_exceeded")
        self._verify_before_source_pins(entry)
        self._check_owner(check_budget=False)
        _path, file_pin = persist_lineage_v2_descriptor(self._workspace, rejected)
        entry.update(state="rejected", rejected=rejected.to_dict(), rejected_file_pin=file_pin.to_dict(),
                     rejected_journal=terminal.to_dict(), rejection_provenance=None)
        entry["evidence_pins"].update(pins)
        wire["rejections"] = self._rejection_index(wire["batches"])
        self._verify_rejected_entry(entry, ordinal=entry["ordinal"],
                                    previous=wire["batches"][-2] if len(wire["batches"]) > 1 else None)
        self._verify_before_source_pins(entry)
        self._verify_live_bytes(archive, state_bytes)
        self._terminal_evidence_sha256 = terminal.digest()
        self._ack(wire)
        self._phase = "rejected"

    def rejection_provenance_binding(self) -> RejectionLineageC1Binding:
        """Read the original C1 observation under the still-live original owner."""
        if type(self) is not RSIPublicationLineage:
            _fail("owner_invalid")
        if not self._is_v2() or self._phase not in {"rejected", "rejected-provenance"}:
            _fail("rejection_c1_required")
        state = self._check_owner(check_budget=False)
        wire = self._wire(state)
        entry = wire["batches"][-1]
        if entry["state"] != "rejected" or entry["journal_id"] != self._plan.journal_id:
            _fail("rejected_association_invalid")
        self._verify_rejected_entry(entry, ordinal=entry["ordinal"],
                                    previous=wire["batches"][-2] if len(wire["batches"]) > 1 else None)
        self._verify_before_source_pins(entry)
        binding = self._binding_for_rejected_entry(entry)
        if self._phase == "rejected" and binding.checkpoint_sha256 != self._head:
            _fail("rejection_c1_adjacency_drift")
        if self._phase == "rejected-provenance":
            self._rejection_pinned_evidence(entry)
        self._check_owner(check_budget=False)
        return binding

    def rejection_provenance_file_pin(self) -> NativeRSIRejectionFilePin:
        if type(self) is not RSIPublicationLineage:
            _fail("owner_invalid")
        if not self._is_v2() or self._phase != "rejected-provenance":
            _fail("rejection_c2_required")
        state = self._check_owner(check_budget=False)
        entry = self._wire(state)["batches"][-1]
        self.rejection_provenance_binding()
        evidence = self._rejection_pinned_evidence(entry)
        pin = NativeRSIRejectionFilePin.from_dict(entry["rejection_provenance"]["file_pin"])
        if evidence.provenance_file_pin != pin:
            _fail("rejection_provenance_drift")
        self._check_owner(check_budget=False)
        return pin

    def acknowledge_rejection_provenance(self, evidence: NativeRSIRejectionEvidence,
                                         file_pin: NativeRSIRejectionFilePin) -> None:
        from .producer_bundle_staging import _locked

        if type(self) is not RSIPublicationLineage:
            _fail("owner_invalid")
        if (not self._is_v2() or self._phase != "rejected"
                or type(evidence) is not NativeRSIRejectionEvidence or type(file_pin) is not NativeRSIRejectionFilePin):
            _fail("rejection_ack_invalid")
        # Exact DTO revalidation precedes all path/lock I/O and caller-controlled methods.
        from .rsi_native_rejection import _dto_shape

        _dto_shape(evidence)
        _dto_shape(file_pin)
        evidence = NativeRSIRejectionEvidence.from_dict(evidence.to_dict(), provenance_sha256=evidence.provenance_sha256,
                                                      provenance_file_pin=file_pin)
        self._check_owner(check_budget=False)
        with _locked(self._workspace, checkpoint=self._terminal_checkpoint):
            state = self._check_owner(check_budget=False)
            binding = self.rejection_provenance_binding()
            wire = self._wire(state)
            entry = wire["batches"][-1]
            if (entry["rejection_provenance"] is not None or evidence.lineage != binding
                    or evidence.plan != self._plan or evidence.claim != self._claim
                    or evidence.provenance_file_pin != file_pin or evidence.provenance_sha256 is None
                    or dict(evidence.ledger_identity) != self._gateway._ledger_identity):
                _fail("rejection_ack_association_invalid")
            observed = read_native_rsi_rejection_provenance(
                self._workspace / "evolution/producer-batches" / entry["journal_id"], expected_file_pin=file_pin,
            )
            if observed != evidence:
                _fail("rejection_provenance_drift")
            entry["rejection_provenance"] = {"provenance_sha256": evidence.provenance_sha256, "file_pin": file_pin.to_dict()}
            self._capacity_check(wire)
            self._retained_bytes(wire, state)
            self._verify_before_source_pins(entry)
            if self._rejection_pinned_evidence(entry) != evidence:
                _fail("rejection_provenance_drift")
            self._check_owner(check_budget=False)
            self._ack(wire)
            self._phase = "rejected-provenance"
            if self._rejection_pinned_evidence(entry) != evidence:
                _fail("rejection_provenance_drift")
            self._check_owner(check_budget=False)


class RSIPublicationLineageInspection(_LineageEvidenceReader):
    """Read one durable child through its original held, complete publication chain.

    This object has no launch, ownership, checkpoint acknowledgment or mutation
    method. Construction observes a terminal native result in the original RSI
    ledger; neither filesystem discovery nor the ephemeral execution capsule is
    used to establish its selected child association.
    """

    __slots__ = (
        "_association", "_claim", "_controller", "_episode_head", "_gateway",
        "_head", "_ledger", "_memory", "_payload", "_plan", "_policy", "_request",
        "_result", "_run_head", "_run_id", "_sidecar", "_strategy", "_thread", "_workspace",
    )

    def __init__(self, controller: Any, *, request: SolverRequest,
                 memory: MemorySnapshot, native_plan: NativeRSIExecutionPlan) -> None:
        from .evolution import PopulationStrategy
        from .rsi_controller import RSILearningController
        from .rsi_producer_gateway import PythonProducerRSISolverGateway
        from .rsi_python_admission import validate_rsi_python_admission_shapes
        from .rsi_python_scheduler_inputs import _request_memory
        from .rsi_store import RSILedger

        if (type(self) is not RSIPublicationLineageInspection
                or type(controller) is not RSILearningController
                or type(controller.ledger) is not RSILedger
                or type(controller.gateway) is not PythonProducerRSISolverGateway
                or controller.gateway.ledger is not controller.ledger
                or type(native_plan) is not NativeRSIExecutionPlan):
            _fail("inspection_invalid")
        policy = multi_episode_publication_policy(controller)
        if policy is None:
            _fail("opt_in_required")
        if policy["protocol"] != _PROTOCOL:
            _fail("v2_inspection_required")
        parsed_request, parsed_memory = _request_memory(request, memory)
        validate_rsi_python_admission_shapes(native_plan, dto_types=(NativeRSIExecutionPlan, SolverRequest))
        plan = NativeRSIExecutionPlan.from_dict(native_plan.to_dict())
        if plan != native_plan or plan.request != parsed_request or plan.memory_snapshot_sha256 != parsed_memory.digest():
            _fail("inspection_plan_mismatch")
        self._controller, self._ledger, self._gateway = controller, controller.ledger, controller.gateway
        self._workspace, self._sidecar = controller.producer_workspace, controller.producer_sidecar
        self._strategy = self._gateway.producer_config.inputs.native_context.strategy
        if (type(self._strategy) is not PopulationStrategy
                or self._strategy.context.workspace.expanduser().absolute() != self._workspace):
            _fail("inspection_strategy_invalid")
        self._thread, self._run_id = get_ident(), plan.run_id
        self._request, self._memory, self._plan, self._policy = parsed_request, parsed_memory, plan, _raw(policy)
        with self._ledger.read_only_observations():
            self._gateway._assert_ledger()
            run = self._ledger.get_run(plan.run_id)
            history = self._ledger.history(plan.run_id)
            checkpoint = self._ledger.controller_checkpoint(plan.run_id)
            claim = self._ledger.inspect_native_episode_claim(parsed_request, plan_sha256=plan.plan_sha256)
            result = self._ledger.episode_result(parsed_request.episode_id)
            episode = self._ledger.get_episode(parsed_request.episode_id)
        if (run is None or not history or checkpoint is None or claim is None or claim.status != "completed"
                or result is None or result[0] != parsed_request or result[1].status != "completed"
                or episode is None or episode.request_sha256 != parsed_request.digest()):
            _fail("inspection_durable_result_required")
        self._run_head, self._head, self._payload = run.record_sha256, checkpoint[0], _raw(checkpoint[1])
        self._claim, self._result, self._episode_head = claim, result, episode.record_sha256
        self._association = {
            "protocol": _PROTOCOL, "run_id": plan.run_id, "workspace": _root_pin(self._workspace),
            "run_request_sha256": history[0].request_sha256,
            "root_proof_sha256": _sha(_raw(history[0].payload.get("producer_checkpoint_binding"))),
            "policy_sha256": _sha(self._policy), "max_batches": MAX_LINEAGE_BATCHES,
        }
        self._check()

    def _check(self) -> dict[str, Any]:
        from .rsi_controller import RSILearningController
        from .rsi_producer_gateway import PythonProducerRSISolverGateway

        controller = self._controller
        if (type(self) is not RSIPublicationLineageInspection or get_ident() != self._thread
                or type(controller) is not RSILearningController
                or controller.ledger is not self._ledger or controller.gateway is not self._gateway
                or type(self._gateway) is not PythonProducerRSISolverGateway
                or self._gateway.ledger is not self._ledger
                or controller.producer_workspace is not self._workspace
                or controller.producer_sidecar is not self._sidecar
                or self._gateway.producer_config.inputs.native_context.strategy is not self._strategy):
            _fail("inspection_owner_drift")
        if (_raw(multi_episode_publication_policy(controller)) != self._policy
                or _root_pin(self._workspace) != self._association["workspace"]):
            _fail("inspection_policy_drift")
        with self._ledger.read_only_observations():
            self._gateway._assert_ledger()
            run = self._ledger.get_run(self._run_id)
            checkpoint = self._ledger.controller_checkpoint(self._run_id)
            original = self._ledger.history(self._run_id)[0]
            episode = self._ledger.get_episode(self._request.episode_id)
            claim = self._ledger.inspect_native_episode_claim(self._request, plan_sha256=self._plan.plan_sha256)
            result = self._ledger.episode_result(self._request.episode_id)
            if (run is None or run.record_sha256 != self._run_head or checkpoint is None
                    or checkpoint[0] != self._head or _raw(checkpoint[1]) != self._payload
                    or original.request_sha256 != self._association["run_request_sha256"]
                    or _sha(_raw(original.payload.get("producer_checkpoint_binding")))
                    != self._association["root_proof_sha256"]
                    or episode is None or episode.record_sha256 != self._episode_head
                    or claim != self._claim or result != self._result):
                _fail("inspection_checkpoint_drift")
            state = checkpoint[1]
            controller._validate_run_checkpoint_producer_binding(run, state)
            controller._validate_resume_identity(run, None, None)
            if controller._native_historical_memory(self._run_id, self._request).to_bytes() != self._memory.to_bytes():
                _fail("inspection_memory_drift")
            self._validate_history(state)
            wire = state.get(_FIELD)
            if (type(wire) is not dict or not wire["batches"] or wire["rejections"]
                    or any(entry.get("state") != "terminal" for entry in wire["batches"])):
                _fail("inspection_terminal_chain_required")
            selected = []
            for entry in wire["batches"]:
                episode_id = entry["episode_id"]
                intent = state.get("intents", {}).get(episode_id)
                ready = state.get("producer_episode_staging", {}).get(episode_id, {}).get("ready")
                reference = state.get("python_admission_refs", {}).get(episode_id)
                if type(intent) is not dict or type(ready) is not dict or type(reference) is not dict:
                    _fail("inspection_child_association_invalid")
                from .rsi_producer_staging_capsule import materialize_ready

                ready = materialize_ready(
                    ready, allow_capsule=state.get("producer_multi_episode_publication") is True,
                    expected_workspace=self._workspace, expected_journal_id=entry["journal_id"],
                )
                request = SolverRequest.from_dict(intent["request"])
                plan = NativeRSIExecutionPlan.from_dict(ready["plan"])
                memory = controller._native_historical_memory(self._run_id, request)
                claim = self._ledger.inspect_native_episode_claim(request, plan_sha256=plan.plan_sha256)
                result = self._ledger.episode_result(episode_id)
                if (entry["request_sha256"] != request.digest() or plan.request != request
                        or entry["memory_snapshot_sha256"] != memory.digest()
                        or entry["native_plan_sha256"] != plan.plan_sha256
                        or reference["native_plan"] != plan.to_dict()
                        or reference["prepared_journal"] != entry["prepared_journal"]
                        or plan.journal_id != entry["journal_id"] or claim is None or claim.status != "completed"
                        or result is None or result[0] != request or result[1].status != "completed"):
                    _fail("inspection_child_association_invalid")
                self._verify_durable_native_result(entry, request, plan, result[1])
                if episode_id == self._request.episode_id:
                    if plan != self._plan or request != self._request:
                        _fail("inspection_selected_child_mismatch")
                    selected.append(entry)
            if len(selected) != 1:
                _fail("inspection_selected_child_missing")
            _require_marker_absent(self._workspace)
            latest = self._ledger.controller_checkpoint(self._run_id)
            if latest is None or latest[0] != self._head or _raw(latest[1]) != self._payload:
                _fail("inspection_checkpoint_drift")
        return state

    def inspect(self, workspace: str | Path, admission_plan: Any, published_journal: Any):
        """Verify the held full chain/current head and return this child's evidence."""
        from . import producer_bundle_recovery as recovery
        from .producer_bundle_admission import (
            ProducerBundleAdmissionPlan,
            parse_producer_bundle_admission_plan,
        )
        from .producer_bundle_publication import (
            ProducerBundlePublicationJournal,
            parse_producer_bundle_publication_journal,
        )

        _publication_shapes(admission_plan, published_journal)
        if (type(self) is not RSIPublicationLineageInspection
                or type(workspace) not in {str, type(self._workspace)}
                or Path(workspace).expanduser().absolute() != self._workspace
                or type(admission_plan) is not ProducerBundleAdmissionPlan
                or type(published_journal) is not ProducerBundlePublicationJournal):
            _fail("inspection_inputs_invalid")
        plan = parse_producer_bundle_admission_plan(admission_plan.to_dict())
        journal = parse_producer_bundle_publication_journal(published_journal.to_dict())
        state = self._check()
        wire = state[_FIELD]
        selected = next(entry for entry in wire["batches"] if entry["episode_id"] == self._request.episode_id)
        if (plan.to_dict() != selected["admission_plan"] or journal.to_dict() != selected["published_journal"]
                or journal.journal_id != self._plan.journal_id or journal.state != "published"):
            _fail("inspection_inputs_mismatch")
        archive = _files.read_regular_file(self._workspace / "evolution/archive.jsonl", MAX_LINEAGE_SNAPSHOT_BYTES)
        current_state = _files.read_regular_file(self._workspace / "evolution/state.json", MAX_LINEAGE_SNAPSHOT_BYTES)
        self._verify_chain(wire, archive, current_state)
        self._strategy._validate_candidate_integrity_state(json.loads(current_state))
        self._strategy._active(json.loads(current_state))
        batch = recovery._batch(self._workspace, journal.journal_id)
        staged = recovery._read_journal(batch / "journal.staged.json")
        preflight = recovery._read_json(batch / "preflight.json", 128 * 1024)
        preflight_sha = recovery._check_preflight(preflight, staged, plan)
        manifest = recovery._read_json(batch / "manifest.json", 256 * 1024)
        manifest_sha, ids, _paths, files = recovery._manifest(manifest, staged, preflight_sha)
        checked = recovery._verify_manifest_files(self._workspace, batch, files, journal)
        self._check()
        # Observe all originally pinned snapshots, materials and the live head again.
        self._verify_chain(wire, archive, current_state)
        self._check()
        return recovery.ProducerBundleRecoveryResult("published", journal.digest(), manifest_sha, preflight_sha, ids, checked)


class _V2InspectionBase(_V2LineageEvidenceReader):
    """Held read-only observations; terminal and started contracts stay exact and separate."""

    __slots__ = (
        "_association",
        "_claim",
        "_controller",
        "_episode_head",
        "_expected_checkpoint_sha256",
        "_expected_provenance_file_pin",
        "_gateway",
        "_head",
        "_ledger",
        "_memory",
        "_payload",
        "_plan",
        "_policy",
        "_request",
        "_result",
        "_run_head",
        "_run_id",
        "_sidecar",
        "_strategy",
        "_thread",
        "_workspace",
    )

    def _initialize(self, controller: Any, *, request: SolverRequest,
                    memory: MemorySnapshot, native_plan: NativeRSIExecutionPlan,
                    expected_checkpoint_sha256: str | None = None,
                    expected_episode_record_sha256: str | None = None,
                    expected_claim_sha256: str | None = None,
                    expected_provenance_file_pin: NativeRSIRejectionFilePin | None = None) -> None:
        from .evolution import PopulationStrategy
        from .rsi_controller import RSILearningController
        from .rsi_producer_gateway import PythonProducerRSISolverGateway
        from .rsi_python_admission import validate_rsi_python_admission_shapes
        from .rsi_python_scheduler_inputs import _request_memory
        from .rsi_store import RSILedger

        if (type(self) not in {RSIPublicationLineageV2Inspection, StartedRSIRejectionInspection}
                or type(controller) is not RSILearningController or type(controller.ledger) is not RSILedger
                or type(controller.gateway) is not PythonProducerRSISolverGateway
                or controller.gateway.ledger is not controller.ledger or type(native_plan) is not NativeRSIExecutionPlan):
            _fail("inspection_invalid")
        from .rsi_native_rejection import _dto_shape

        _dto_shape(native_plan)
        started = type(self) is StartedRSIRejectionInspection
        if started:
            if (type(expected_provenance_file_pin) is not NativeRSIRejectionFilePin
                    or any(type(value) is not str or len(value) != 64
                           or any(c not in "0123456789abcdef" for c in value) for value in (
                               expected_checkpoint_sha256, expected_episode_record_sha256, expected_claim_sha256))):
                _fail("inspection_expected_pins_invalid")
            _dto_shape(expected_provenance_file_pin)
            expected_provenance_file_pin = NativeRSIRejectionFilePin.from_dict(expected_provenance_file_pin.to_dict())
            if not controller.ledger.controller_lock_held(native_plan.run_id):
                _fail("inspection_controller_lock_required")
        policy = multi_episode_publication_policy(controller)
        if policy is None or policy["protocol"] != _PROTOCOL_V2:
            _fail("v2_opt_in_required")
        parsed_request, parsed_memory = _request_memory(request, memory)
        validate_rsi_python_admission_shapes(native_plan, dto_types=(NativeRSIExecutionPlan, SolverRequest))
        plan = NativeRSIExecutionPlan.from_dict(native_plan.to_dict())
        if plan != native_plan or plan.request != parsed_request or plan.memory_snapshot_sha256 != parsed_memory.digest():
            _fail("inspection_plan_mismatch")
        self._controller, self._ledger, self._gateway = controller, controller.ledger, controller.gateway
        self._workspace, self._sidecar = controller.producer_workspace, controller.producer_sidecar
        self._strategy = self._gateway.producer_config.inputs.native_context.strategy
        if (type(self._strategy) is not PopulationStrategy
                or self._strategy.context.workspace.expanduser().absolute() != self._workspace):
            _fail("inspection_strategy_invalid")
        self._thread, self._run_id = get_ident(), plan.run_id
        self._request, self._memory, self._plan, self._policy = parsed_request, parsed_memory, plan, _raw(policy)
        self._expected_checkpoint_sha256 = expected_checkpoint_sha256
        self._expected_provenance_file_pin = expected_provenance_file_pin
        with self._ledger.read_only_observations():
            self._gateway._assert_ledger()
            run = self._ledger.get_run(plan.run_id)
            history = self._ledger.history(plan.run_id)
            checkpoint = self._ledger.controller_checkpoint(plan.run_id)
            claim = self._ledger.inspect_native_episode_claim(parsed_request, plan_sha256=plan.plan_sha256)
            result = self._ledger.episode_result(parsed_request.episode_id)
            episode = self._ledger.get_episode(parsed_request.episode_id)
        if run is None or not history or checkpoint is None or claim is None or episode is None:
            _fail("inspection_durable_result_required")
        if episode.request_sha256 != parsed_request.digest():
            _fail("inspection_child_association_invalid")
        if started:
            if (claim.status != "started" or result is not None
                    or episode.record_sha256 != expected_episode_record_sha256
                    or claim.claim_sha256 != expected_claim_sha256):
                _fail("inspection_started_claim_required")
        elif (claim.status not in {"completed", "failed"} or result is None or result[0] != parsed_request
              or result[1].status != claim.status):
            _fail("inspection_durable_result_required")
        self._run_head, self._head, self._payload = run.record_sha256, checkpoint[0], _raw(checkpoint[1])
        self._claim, self._result, self._episode_head = claim, result, episode.record_sha256
        self._association = {
            "protocol": _PROTOCOL_V2, "run_id": plan.run_id, "workspace": _root_pin(self._workspace),
            "run_request_sha256": history[0].request_sha256,
            "root_proof_sha256": _sha(_raw(history[0].payload.get("producer_checkpoint_binding"))),
            "policy_sha256": _sha(self._policy), "max_batches": MAX_LINEAGE_BATCHES,
        }
        self._check()

    def _check(self) -> dict[str, Any]:
        from .rsi_controller import RSILearningController
        from .rsi_producer_gateway import PythonProducerRSISolverGateway

        controller = self._controller
        if (type(self) not in {RSIPublicationLineageV2Inspection, StartedRSIRejectionInspection}
                or get_ident() != self._thread or type(controller) is not RSILearningController
                or controller.ledger is not self._ledger or controller.gateway is not self._gateway
                or type(self._gateway) is not PythonProducerRSISolverGateway or self._gateway.ledger is not self._ledger
                or controller.producer_workspace is not self._workspace or controller.producer_sidecar is not self._sidecar
                or self._gateway.producer_config.inputs.native_context.strategy is not self._strategy):
            _fail("inspection_owner_drift")
        if (_raw(multi_episode_publication_policy(controller)) != self._policy
                or _root_pin(self._workspace) != self._association["workspace"]):
            _fail("inspection_policy_drift")
        started = type(self) is StartedRSIRejectionInspection
        if started:
            controller._validate_native_rejection_reconciliation_checkpoint(
                self._run_id, self._request.episode_id, expected_checkpoint_sha256=self._expected_checkpoint_sha256,
                current_checkpoint_sha256=self._head,
            )
        with self._ledger.read_only_observations():
            self._gateway._assert_ledger()
            run = self._ledger.get_run(self._run_id)
            checkpoint = self._ledger.controller_checkpoint(self._run_id)
            original = self._ledger.history(self._run_id)[0]
            episode = self._ledger.get_episode(self._request.episode_id)
            claim = self._ledger.inspect_native_episode_claim(self._request, plan_sha256=self._plan.plan_sha256)
            result = self._ledger.episode_result(self._request.episode_id)
            if (run is None or run.record_sha256 != self._run_head or checkpoint is None
                    or checkpoint[0] != self._head or _raw(checkpoint[1]) != self._payload
                    or original.request_sha256 != self._association["run_request_sha256"]
                    or _sha(_raw(original.payload.get("producer_checkpoint_binding"))) != self._association["root_proof_sha256"]
                    or episode is None or episode.record_sha256 != self._episode_head or claim != self._claim or result != self._result):
                _fail("inspection_checkpoint_drift")
            state = checkpoint[1]
            controller._validate_run_checkpoint_producer_binding(run, state)
            controller._validate_resume_identity(run, None, None)
            if (state.get("mode") != "drs" or state.get("producer_known_rejection") is not True
                    or controller._native_historical_memory(self._run_id, self._request).to_bytes() != self._memory.to_bytes()):
                _fail("inspection_memory_drift")
            self._validate_history_v2(state)
            wire = state.get(_FIELD)
            if (type(wire) is not dict or not wire["batches"]
                    or any(entry["state"] not in {"terminal", "rejected"}
                           or (entry["state"] == "rejected" and entry["rejection_provenance"] is None) for entry in wire["batches"])):
                _fail("inspection_terminal_chain_required")
            selected = [entry for entry in wire["batches"] if entry["episode_id"] == self._request.episode_id]
            if len(selected) != 1:
                _fail("inspection_selected_child_missing")
            entry = selected[0]
            if (entry["request_sha256"] != self._request.digest() or entry["native_plan_sha256"] != self._plan.plan_sha256
                    or entry["memory_snapshot_sha256"] != self._memory.digest() or entry["journal_id"] != self._plan.journal_id):
                _fail("inspection_selected_child_mismatch")
            if started and (entry is not wire["batches"][-1] or entry["state"] != "rejected"
                            or NativeRSIRejectionFilePin.from_dict(entry["rejection_provenance"]["file_pin"])
                            != self._expected_provenance_file_pin):
                _fail("inspection_c2_pin_mismatch")
            for retained in wire["batches"]:
                self._verify_entry_native_settlement(retained)
            _require_marker_absent(self._workspace)
            latest = self._ledger.controller_checkpoint(self._run_id)
            if latest is None or latest[0] != self._head or _raw(latest[1]) != self._payload:
                _fail("inspection_checkpoint_drift")
        if started:
            controller._validate_native_rejection_reconciliation_checkpoint(
                self._run_id, self._request.episode_id, expected_checkpoint_sha256=self._expected_checkpoint_sha256,
                current_checkpoint_sha256=self._head,
            )
        return state

    def _live_population(self, wire: dict[str, Any]) -> tuple[bytes, bytes]:
        path = self._workspace / "evolution/archive.jsonl"
        try:
            path.lstat()
        except FileNotFoundError:
            if wire["head"] is not None:
                _fail("current_head_drift")
            archive = b""
        else:
            archive = _files.read_regular_file(path, MAX_LINEAGE_SNAPSHOT_BYTES)
        state_bytes = _files.read_regular_file(self._workspace / "evolution/state.json", MAX_LINEAGE_SNAPSHOT_BYTES)
        return archive, state_bytes

    def rejection_provenance_binding(self) -> RejectionLineageC1Binding:
        state = self._check()
        entry = next(entry for entry in state[_FIELD]["batches"] if entry["episode_id"] == self._request.episode_id)
        if entry["state"] != "rejected":
            _fail("rejection_c2_required")
        binding = self._binding_for_rejected_entry(entry)
        if self._rejection_pinned_evidence(entry).lineage != binding:
            _fail("rejection_provenance_drift")
        self._check()
        return binding

    def rejection_provenance_file_pin(self) -> NativeRSIRejectionFilePin:
        state = self._check()
        entry = next(entry for entry in state[_FIELD]["batches"] if entry["episode_id"] == self._request.episode_id)
        if entry["state"] != "rejected" or entry["rejection_provenance"] is None:
            _fail("rejection_c2_required")
        pin = NativeRSIRejectionFilePin.from_dict(entry["rejection_provenance"]["file_pin"])
        if self._rejection_pinned_evidence(entry).provenance_file_pin != pin:
            _fail("rejection_provenance_drift")
        self._check()
        return pin

    def inspect_rejection(self, workspace: str | Path, admission_plan: Any, terminal: Any):
        from .producer_bundle_admission import (
            ProducerBundleAdmissionPlan,
            parse_producer_bundle_admission_plan,
        )
        from .producer_bundle_publication import (
            ProducerBundlePublicationJournal,
            parse_producer_bundle_publication_journal,
        )
        from .producer_bundle_rejection import _verify_terminal_batch_rejection_evidence

        _publication_shapes(admission_plan, terminal)
        if (type(self) not in {RSIPublicationLineageV2Inspection, StartedRSIRejectionInspection}
                or type(workspace) not in {str, type(self._workspace)}
                or Path(workspace).expanduser().absolute() != self._workspace
                or type(admission_plan) is not ProducerBundleAdmissionPlan or type(terminal) is not ProducerBundlePublicationJournal):
            _fail("inspection_inputs_invalid")
        plan = parse_producer_bundle_admission_plan(admission_plan.to_dict())
        terminal = parse_producer_bundle_publication_journal(terminal.to_dict())
        wire = self._check()[_FIELD]
        entry = next(entry for entry in wire["batches"] if entry["episode_id"] == self._request.episode_id)
        if entry["state"] != "rejected" or plan.to_dict() != entry["admission_plan"] or terminal.to_dict() != entry["rejected_journal"]:
            _fail("inspection_inputs_mismatch")
        archive, current_state = self._live_population(wire)
        self._verify_chain(wire, archive, current_state)
        from .producer_bundle_publication import parse_producer_bundle_publication_journal

        prepared = parse_producer_bundle_publication_journal(entry["prepared_journal"])
        observed = _verify_terminal_batch_rejection_evidence(
            self._workspace, self._workspace / "evolution/producer-batches" / entry["journal_id"], prepared, terminal=terminal,
        )
        self._check()
        self._verify_chain(wire, archive, current_state)
        self._check()
        return observed


class RSIPublicationLineageV2Inspection(_V2InspectionBase):
    """Terminal-only mixed P/R history; no owner, launch or acknowledgment API."""

    __slots__ = ()

    def __init__(self, controller: Any, *, request: SolverRequest,
                 memory: MemorySnapshot, native_plan: NativeRSIExecutionPlan) -> None:
        self._initialize(controller, request=request, memory=memory, native_plan=native_plan)

    def inspect(self, workspace: str | Path, admission_plan: Any, published_journal: Any):
        from . import producer_bundle_recovery as recovery
        from .producer_bundle_admission import (
            ProducerBundleAdmissionPlan,
            parse_producer_bundle_admission_plan,
        )
        from .producer_bundle_publication import (
            ProducerBundlePublicationJournal,
            parse_producer_bundle_publication_journal,
        )

        _publication_shapes(admission_plan, published_journal)
        if (type(self) is not RSIPublicationLineageV2Inspection or type(workspace) not in {str, type(self._workspace)}
                or Path(workspace).expanduser().absolute() != self._workspace
                or type(admission_plan) is not ProducerBundleAdmissionPlan or type(published_journal) is not ProducerBundlePublicationJournal):
            _fail("inspection_inputs_invalid")
        plan = parse_producer_bundle_admission_plan(admission_plan.to_dict())
        journal = parse_producer_bundle_publication_journal(published_journal.to_dict())
        wire = self._check()[_FIELD]
        selected = next(entry for entry in wire["batches"] if entry["episode_id"] == self._request.episode_id)
        if (selected["state"] != "terminal" or plan.to_dict() != selected["admission_plan"]
                or journal.to_dict() != selected["published_journal"] or journal.state != "published"):
            _fail("inspection_inputs_mismatch")
        archive, current_state = self._live_population(wire)
        self._verify_chain(wire, archive, current_state)
        self._strategy._validate_candidate_integrity_state(json.loads(current_state))
        self._strategy._active(json.loads(current_state))
        batch = recovery._batch(self._workspace, journal.journal_id)
        staged = recovery._read_journal(batch / "journal.staged.json")
        preflight = recovery._read_json(batch / "preflight.json", 128 * 1024)
        preflight_sha = recovery._check_preflight(preflight, staged, plan)
        manifest = recovery._read_json(batch / "manifest.json", 256 * 1024)
        manifest_sha, ids, _paths, files = recovery._manifest(manifest, staged, preflight_sha)
        checked = recovery._verify_manifest_files(self._workspace, batch, files, journal)
        self._check()
        self._verify_chain(wire, archive, current_state)
        self._check()
        return recovery.ProducerBundleRecoveryResult("published", journal.digest(), manifest_sha, preflight_sha, ids, checked)


class StartedRSIRejectionInspection(_V2InspectionBase):
    """C2-only explicit reconcile observation with separately pinned current CAS."""

    __slots__ = ()

    def __init__(self, controller: Any, *, request: SolverRequest,
                 memory: MemorySnapshot, native_plan: NativeRSIExecutionPlan,
                 expected_checkpoint_sha256: str, expected_episode_record_sha256: str,
                 expected_claim_sha256: str, expected_provenance_file_pin: NativeRSIRejectionFilePin) -> None:
        self._initialize(controller, request=request, memory=memory, native_plan=native_plan,
                         expected_checkpoint_sha256=expected_checkpoint_sha256,
                         expected_episode_record_sha256=expected_episode_record_sha256,
                         expected_claim_sha256=expected_claim_sha256,
                         expected_provenance_file_pin=expected_provenance_file_pin)


def _publication_lineage_checkpoint_delta(
    captured_payload: bytes, wire: dict[str, Any],
) -> dict[str, Any]:
    """Build one bounded lineage delta; this pure helper grants no owner authority.

    Refactoring this source changes the original publication policy fingerprint.
    Persisted policies still require their original implementation; this helper
    does not migrate an old policy or adopt a newer checkpoint.
    """
    expected = json.loads(captured_payload)
    expected[_FIELD] = wire
    try:
        _raw(expected)
    except (ValueError, TypeError) as exc:
        raise RSILearningError("rsi_publication_lineage_capacity_exceeded") from exc
    return expected


def _validate_publication_lineage_checkpoint_readback(
    *, expected_head: str, expected_payload: bytes,
    observed_head: str | None, observed_payload: bytes | None,
) -> None:
    """Compare already-observed bytes without reading or refreshing owner state."""
    if observed_head != expected_head or observed_payload != expected_payload:
        _fail("acknowledgement_readback_invalid")


def acknowledge_publication_lineage_for_active_flow(controller: Any, owner: RSIPublicationLineage) -> str:
    """Write and acknowledge only the capsule's exact adjacent lineage increment."""
    if type(owner) is not RSIPublicationLineage or controller is not owner._controller:
        _fail("owner_invalid")
    if not owner._is_v2():
        state = owner._check_owner(check_budget=owner._phase != "staged")
    if type(owner._pending_wire) is not bytes:
        _fail("acknowledgement_missing")
    wire = json.loads(owner._pending_wire)
    terminal_evidence = owner._is_v2() and owner._terminal_evidence_sha256 is not None
    if terminal_evidence and (not wire["batches"] or wire["batches"][-1]["state"] != "rejected"
            or wire["batches"][-1]["rejected"]["terminal_journal_sha256"] != owner._terminal_evidence_sha256
            or owner._phase not in {"before", "rejected", "rejected-provenance"}):
        _fail("terminal_evidence_ack_invalid")
    if owner._is_v2():
        state = owner._check_owner(check_budget=owner._phase != "staged" and not terminal_evidence)
    context = owner._context
    expected = _publication_lineage_checkpoint_delta(context.payload, wire)
    payload = controller._python_admission_flow_payload(expected)
    # State, sidecar and source checks above precede this original compare-and-swap.
    head = owner._ledger.write_controller_checkpoint(owner._plan.run_id, expected, expected_sha256=owner._head)
    with owner._ledger.read_only_observations():
        observed = owner._ledger.controller_checkpoint(owner._plan.run_id)
        observed_head = None if observed is None else observed[0]
        observed_payload = None
        if observed is not None and observed_head == head:
            observed_payload = controller._python_admission_flow_payload(observed[1])
        _validate_publication_lineage_checkpoint_readback(
            expected_head=head, expected_payload=payload,
            observed_head=observed_head, observed_payload=observed_payload,
        )
        controller._python_admission_assert_flow_context(context, owner._plan.run_id, owner._request.episode_id)
        controller._validate_original_run_checkpoint_producer_binding(owner._ledger.get_run(owner._plan.run_id), expected)
    acknowledged = replace(context, checkpoint_sha256=head, payload=payload)
    state[_FIELD] = wire
    controller._python_admission_flow_local.active = acknowledged
    owner._context, owner._head, owner._payload = acknowledged, head, payload
    return head
