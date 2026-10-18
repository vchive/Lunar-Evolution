"""Read-only composition of independent original BRS terminal evidence.

Reports are detached observations, never capabilities. Only the controller's fresh
composition under its run lock may pass the derived evidence and source pins to
the existing atomic obligation consumer. No callback, publication or repair runs
here, and an originally unknown process capture is never backfilled.
"""
from __future__ import annotations

import hashlib
import json
import math
import re

from .candidate_evaluation_spec import canonical_json
from .rsi_brs_mailbox_evidence import inspect_brs_mailbox_evidence
from .rsi_brs_native_process_evidence import observe_native_process_binding
from .rsi_brs_reconcile import (
    FIELD,
    BRSReconcileEvidence,
    _validate_brs_episode_history,
    parse_brs_reconcile_obligations,
)
from .rsi_learning import PracticeEpisode, RSILearningError
from .rsi_python_brs_terminal_lifecycle import inspect_brs_worker_terminal_evidence

PROTOCOL = "lunar-rsi-brs-terminal-composition-v1"
MAX_BRS_TERMINAL_REPORT_BYTES = 8 * 1024 * 1024
_SHA = re.compile(r"^[0-9a-f]{64}$")
_PIN_FIELDS = frozenset({
    "root_checkpoint_sha256", "mailbox_checkpoint_sha256", "terminal_checkpoint_sha256",
    "run_record_sha256", "episode_record_sha256", "native_claim_sha256", "result_sha256",
    "obligation_sha256",
})
_REPORT_FIELDS = frozenset({
    "protocol", "run_id", "episode_id", "status", "reason", "source_pins",
    "mailbox_binding_sha256", "native_process_binding_sha256", "mailbox_observation",
    "callback_observation", "worker_terminal", "native_process_observation",
    "publication_sha256", "terminal_status", "evidence", "observation_sha256",
})
_TERMINAL_STATUSES = frozenset({"completed", "failed", "timed_out", "cancelled"})


def _fail(reason: str) -> None:
    raise RSILearningError("rsi_brs_terminal_evidence_" + reason)


def _plain(value: object, depth: int = 0, remaining: list[int] | None = None):
    if remaining is None:
        remaining = [65536]
    remaining[0] -= 1
    if depth > 32 or remaining[0] < 0:
        _fail("shape_invalid")
    kind = type(value)
    if value is None or kind is bool:
        return value
    if kind is int and value.bit_length() <= 128:
        return value
    if kind is float and math.isfinite(value):
        return value
    if kind is str and len(value) <= MAX_BRS_TERMINAL_REPORT_BYTES:
        return value
    if kind is dict and len(value) <= 256 and all(type(key) is str for key in value):
        return {key: _plain(item, depth + 1, remaining) for key, item in value.items()}
    if kind is list and len(value) <= 256:
        return [_plain(item, depth + 1, remaining) for item in value]
    _fail("shape_invalid")


def _clean(value: object) -> dict:
    clean = _plain(value)
    if type(clean) is not dict:
        _fail("shape_invalid")
    return json.loads(canonical_json(clean, maximum=MAX_BRS_TERMINAL_REPORT_BYTES))


def _digest(value: dict, field: str = "observation_sha256") -> str:
    return hashlib.sha256(canonical_json(
        {key: item for key, item in value.items() if key != field},
        maximum=MAX_BRS_TERMINAL_REPORT_BYTES,
    )).hexdigest()


def _sha(value: object) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        _fail("digest_invalid")
    return value


def _text(value: object) -> str:
    if type(value) is not str or not value or len(value) > 256 or any(c in value for c in "\x00\r\n"):
        _fail("identity_invalid")
    return value


def _pins(value: object) -> dict:
    clean = _clean(value)
    if set(clean) != _PIN_FIELDS:
        _fail("pins_invalid")
    for item in clean.values():
        if item is not None:
            _sha(item)
    return clean


def parse_brs_terminal_observation(value: object) -> dict:
    """Validate a bounded report; a valid self digest grants no authority."""
    clean = _clean(value)
    if set(clean) != _REPORT_FIELDS or clean["protocol"] != PROTOCOL:
        _fail("report_invalid")
    _text(clean["run_id"])
    _text(clean["episode_id"])
    _text(clean["reason"])
    _pins(clean["source_pins"])
    if (type(clean["status"]) is not str or clean["status"] not in {"unknown", "ready"}
            or type(clean["worker_terminal"]) is not bool
            or type(clean["callback_observation"]) is not str
            or clean["callback_observation"] not in {"unobserved", "started", "returned", "unknown"}):
        _fail("report_invalid")
    for field in ("mailbox_binding_sha256", "native_process_binding_sha256", "publication_sha256"):
        if clean[field] is not None:
            _sha(clean[field])
    if clean["terminal_status"] is not None and (
        type(clean["terminal_status"]) is not str or clean["terminal_status"] not in _TERMINAL_STATUSES
    ):
        _fail("report_invalid")
    for field in ("mailbox_observation", "native_process_observation"):
        if clean[field] is not None and type(clean[field]) is not dict:
            _fail("report_invalid")
    mailbox, process = clean["mailbox_observation"], clean["native_process_observation"]
    if mailbox is not None:
        if (set(mailbox) != {"status", "head", "terminal_evidence"}
                or type(mailbox["status"]) is not str
                or mailbox["status"] not in {"missing", "partial", "transport_observed"}
                or mailbox["terminal_evidence"] is not False):
            _fail("report_invalid")
        if mailbox["head"] is not None:
            _sha(mailbox["head"])
        if (mailbox["status"] == "missing") != (mailbox["head"] is None):
            _fail("report_invalid")
    if process is not None:
        if (set(process) != {"protocol", "role", "binding_sha256", "status", "process_state", "process_group",
                             "observed_owner_identity", "cleanup_confirmed", "reason", "observation_sha256"}
                or process["protocol"] != "lunar-rsi-brs-native-process-binding-v1:observation"
                or process["role"] != "native-producer-process"
                or process["binding_sha256"] != clean["native_process_binding_sha256"]
                or type(process["status"]) is not str or process["status"] not in {"unknown", "running", "exited", "drifted"}
                or type(process["process_state"]) is not str or process["process_state"] not in {"unknown", "running", "exited"}
                or type(process["process_group"]) is not str or process["process_group"] not in {"unknown", "present", "absent"}
                or type(process["cleanup_confirmed"]) is not bool
                or (process["observed_owner_identity"] is not None and type(process["observed_owner_identity"]) is not dict)
                or _sha(process["observation_sha256"]) != _digest(process)):
            _fail("report_invalid")
        _text(process["reason"])
    if clean["status"] == "ready":
        evidence = BRSReconcileEvidence.from_dict(clean["evidence"])
        if (not clean["worker_terminal"] or clean["callback_observation"] != "returned"
                or clean["terminal_status"] != evidence.terminal_status
                or evidence.process_state != "exited" or evidence.mailbox_state != "closed"
                or evidence.transaction_state != "terminal" or not evidence.controller_observed_terminal
                or not evidence.cleanup_confirmed
                or evidence.obligation_sha256 != clean["source_pins"]["obligation_sha256"]
                or evidence.native_claim_sha256 != clean["source_pins"]["native_claim_sha256"]
                or evidence.native_evidence_sha256 != clean["source_pins"]["native_claim_sha256"]
                or evidence.result_evidence_sha256 != clean["source_pins"]["result_sha256"]
                or evidence.mailbox_evidence_sha256 != clean["source_pins"]["terminal_checkpoint_sha256"]
                or any(clean[field] is None for field in (
                    "mailbox_binding_sha256", "native_process_binding_sha256", "publication_sha256",
                    "mailbox_observation", "native_process_observation",
                ))):
            _fail("report_invalid")
        if (any(item is None for item in clean["source_pins"].values())
                or mailbox["status"] != "transport_observed"
                or mailbox["head"] != clean["source_pins"]["mailbox_checkpoint_sha256"]
                or process["status"] != "exited" or process["process_state"] != "exited"
                or process["process_group"] != "absent" or process["observed_owner_identity"] is not None
                or process["cleanup_confirmed"] is not True
                or process["observation_sha256"] != evidence.process_evidence_sha256):
            _fail("report_invalid")
    elif clean["evidence"] is not None:
        _fail("report_invalid")
    if _sha(clean["observation_sha256"]) != _digest(clean):
        _fail("report_digest_invalid")
    return clean


def _ledger_terminal(snapshot: dict, obligation, binding: dict):
    """Verify the actual claim/result and append-only episode projection."""
    from .rsi_gateway import SolverRequest

    episode = _validate_brs_episode_history(obligation, snapshot["episode_history"])
    claim, saved = snapshot["native_claim"], snapshot["saved_result"]
    if claim is None or saved is None:
        return None
    request, result = saved
    origin = next((state for head, state in snapshot["roots"]
                   if head == obligation.controller_checkpoint_sha256), None)
    try:
        original = SolverRequest.from_dict(origin["intents"][obligation.episode_id]["request"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RSILearningError("rsi_brs_terminal_evidence_request_drift") from exc
    result_sha = hashlib.sha256(canonical_json(result.to_dict(), maximum=128 * 1024)).hexdigest()
    if (request != original or request.digest() != obligation.request_sha256
            or request.episode_id != obligation.episode_id
            or result.episode_id != obligation.episode_id or result.request_sha256 != request.digest()
            or result_sha != snapshot["pins"]["result_sha256"]
            or claim.claim_sha256 != binding["native_claim_sha256"]
            or claim.claim_sha256 != obligation.native_claim_sha256
            or claim.episode_id != obligation.episode_id or claim.request_sha256 != request.digest()
            or claim.plan_sha256 != obligation.native_plan_sha256 or claim.status != result.status):
        _fail("native_result_drift")
    if result.status not in _TERMINAL_STATUSES or episode.state not in _TERMINAL_STATUSES:
        return None
    durable = PracticeEpisode.from_dict(episode.payload)
    reasons = {result.terminal_reason} if result.terminal_reason else {
        "solver_" + result.status, "reconciled_worker_" + result.status,
    }
    if (episode.state != result.status or any(
        getattr(durable, name) != getattr(request, name) for name in (
            "contract_sha256", "evaluator_sha256", "environment_sha256", "memory_snapshot_sha256", "solver_id",
        )
    ) or any(getattr(durable, name) != getattr(result, name) for name in (
        "trace_digest", "candidate_source_sha256", "dependency_sha256", "trace_events", "actor_fingerprint",
    )) or (result.status == "completed" and any(
        getattr(durable, name) != getattr(result, name) for name in (
            "candidate_receipt_sha256", "execution_receipt_sha256", "official_evaluation_receipt_sha256",
        )
    )) or (result.status != "completed" and durable.terminal_reason not in reasons)):
        _fail("episode_result_drift")
    return claim, result, result_sha


def _rejected_publication(workspace, publication: dict, binding: dict, roots: list, *, ledger) -> str:
    """Reobserve original C1/P/C2 and rejection materials without repairing them."""
    from . import _benchmark_files as files
    from . import producer_bundle_recovery as recovery
    from .producer_bundle_admission import parse_producer_bundle_admission_plan
    from .producer_bundle_lineage import (
        MAX_LINEAGE_SNAPSHOT_BYTES,
        LineageSnapshotPin,
        lineage_directory,
        read_lineage_descriptor_pinned,
        verify_persisted_lineage_snapshot,
    )
    from .producer_bundle_lineage_v2 import read_lineage_v2_descriptor_pinned
    from .producer_bundle_publication import parse_producer_bundle_publication_journal
    from .producer_bundle_rejection import _verify_terminal_batch_rejection_evidence
    from .rsi_brs_rejection_c1 import (
        rejected_provenance_entry,
        validate_rejected_c1_transition,
        validate_rejected_provenance_transition,
    )
    from .rsi_brs_rejection_capacity import (
        retained_brs_c1_evidence_bytes,
        retained_brs_c2_evidence_bytes,
    )
    from .rsi_native_rejection import (
        NativeRSIRejectionFilePin,
        RejectionLineageC1Binding,
        read_native_rsi_rejection_provenance,
    )
    from .rsi_native_scheduler import _read_ledger_identity
    from .rsi_publication_lineage import _root_pin
    from .rsi_store import RSILedger

    if publication["manifest"] is not None or type(ledger) is not RSILedger:
        _fail("rejection_provenance_required")
    wire = publication["lineage"]
    entry = wire["batches"][0]
    rejected = rejected_provenance_entry(entry)
    journal = parse_producer_bundle_publication_journal(publication["journal"])
    prepared = parse_producer_bundle_publication_journal(entry["prepared_journal"])
    plan = parse_producer_bundle_admission_plan(entry["admission_plan"])
    if (journal.to_dict() != entry["rejected_journal"] or journal.state != "all_rejected"
            or journal.journal_id != entry["journal_id"] or journal.run_id != binding["run_id"]
            or journal.task_id != binding["episode_id"] or journal.admission_sha256 != plan.digest()
            or entry["episode_id"] != binding["episode_id"]
            or entry["request_sha256"] != binding["selected_request_sha256"]
            or entry["native_plan_sha256"] != binding["native_plan_sha256"] or wire["head"] is not None):
        _fail("rejection_journal_drift")
    root = recovery._workspace(workspace)
    batch = recovery._batch(root, journal.journal_id)
    reference = entry["rejection_provenance"]
    p_pin = NativeRSIRejectionFilePin.from_dict(reference["file_pin"])
    evidence = read_native_rsi_rejection_provenance(batch, expected_file_pin=p_pin)
    if (evidence.provenance_sha256 != reference["provenance_sha256"]
            or evidence.provenance_file_pin != p_pin or evidence.rejected != rejected
            or evidence.terminal != journal or evidence.plan.plan_sha256 != binding["native_plan_sha256"]
            or evidence.plan.request_sha256 != binding["selected_request_sha256"]
            or evidence.plan.memory_snapshot_sha256 != entry["memory_snapshot_sha256"]
            or evidence.claim.claim_sha256 != binding["native_claim_sha256"]
            or dict(evidence.ledger_identity) != _read_ledger_identity(ledger)):
        _fail("rejection_provenance_drift")

    # P names the original C1 head. Only its actual adjacent predecessor and C2
    # may establish the full-state deltas; equal later checkpoints are no substitute.
    matches = [index for index, (head, _state) in enumerate(roots)
               if head == evidence.lineage.checkpoint_sha256]
    if len(matches) != 1 or not 0 < matches[0] < len(roots) - 1:
        _fail("rejection_checkpoint_drift")
    index = matches[0]
    before_state, c1_state, c2_state = (roots[position][1] for position in (index - 1, index, index + 1))
    c1_wire = c1_state.get("producer_publication_lineage")
    validate_rejected_c1_transition(before_state.get("producer_publication_lineage"), c1_wire)
    validate_rejected_provenance_transition(c1_wire, wire)
    for previous, current, expected_wire in ((before_state, c1_state, c1_wire), (c1_state, c2_state, wire)):
        expected = {**previous, "producer_publication_lineage": expected_wire}
        if canonical_json(current, maximum=MAX_BRS_TERMINAL_REPORT_BYTES) != canonical_json(
            expected, maximum=MAX_BRS_TERMINAL_REPORT_BYTES,
        ):
            _fail("rejection_checkpoint_drift")
    if any(state.get("producer_publication_lineage") != wire for _head, state in roots[index + 1:]):
        _fail("rejection_checkpoint_drift")

    def verify_material_pins():
        before_pin = LineageSnapshotPin.from_dict(entry["before_file_pin"])
        before = read_lineage_descriptor_pinned(root, journal.journal_id, kind="before", expected_file_pin=before_pin)
        rejected_pin = LineageSnapshotPin.from_dict(entry["rejected_file_pin"])
        actual = read_lineage_v2_descriptor_pinned(root, journal.journal_id,
                                                 kind="rejected", expected_file_pin=rejected_pin)
        if before.to_dict() != entry["before"] or actual != rejected:
            _fail("rejection_descriptor_drift")
        for name, raw in entry["snapshots"].items():
            pin = LineageSnapshotPin.from_dict(raw)
            verify_persisted_lineage_snapshot(lineage_directory(root, journal.journal_id) / (name + ".snapshot"), pin)
        sources = entry["before_sources"]
        if type(sources) is not dict or set(sources) != {"archive", "state"}:
            _fail("publication_source_drift")
        for name, raw in sources.items():
            snapshot = LineageSnapshotPin.from_dict(entry["snapshots"][name + "-before"])
            path = batch.parent.parent / ("archive.jsonl" if name == "archive" else "state.json")
            if type(raw) is dict and raw.get("missing") is True:
                if (name != "archive" or set(raw) != {"missing", "parent"}
                        or raw["parent"] != _root_pin(path.parent) or snapshot.size != 0
                        or snapshot.sha256 != hashlib.sha256(b"").hexdigest()):
                    _fail("publication_source_drift")
                try:
                    path.lstat()
                except FileNotFoundError:
                    pass
                else:
                    _fail("publication_source_drift")
            else:
                pin = LineageSnapshotPin.from_dict(raw)
                if pin.name != name + "-before" or pin.sha256 != snapshot.sha256 or pin.size != snapshot.size:
                    _fail("publication_source_drift")
                verify_persisted_lineage_snapshot(path, pin)
        try:
            (batch.parent.parent / "producer-publication.json").lstat()
        except FileNotFoundError:
            pass
        else:
            _fail("rejection_publication_marker_drift")
        for name, raw in entry["evidence_pins"].items():
            verify_persisted_lineage_snapshot(batch / name, LineageSnapshotPin.from_dict(raw))

    verify_material_pins()
    if recovery._read_journal(batch / "journal.prepared.json") != prepared:
        _fail("rejection_material_drift")
    tables = {}
    for candidate_id in rejected.candidate_ids:
        path = batch / "rejections" / (candidate_id + ".json")
        value = json.loads(files.read_regular_file(path, MAX_LINEAGE_SNAPSHOT_BYTES))
        if type(value) is not dict or type(value.get("retained_evidence")) is not dict:
            _fail("rejection_material_drift")
        tables[candidate_id] = value["retained_evidence"]
    observed = _verify_terminal_batch_rejection_evidence(root, batch, prepared, terminal=journal)
    expected_lineage = RejectionLineageC1Binding(
        run_id=binding["run_id"], episode_id=binding["episode_id"], journal_id=journal.journal_id, ordinal=0,
        checkpoint_sha256=roots[index][0], rejected_sha256=rejected.digest(),
        retained_bytes=retained_brs_c1_evidence_bytes(c1_state, c1_wire, tables),
        **{name: getattr(rejected, name) for name in (
            "before_sha256", "prepared_journal_sha256", "terminal_journal_sha256", "rejection_manifest_sha256",
            "terminal_marker_sha256", "candidate_ids", "archive_sha256", "state_sha256")},
    )
    retained_brs_c2_evidence_bytes(c1_state, wire, tables)
    if (evidence.lineage != expected_lineage or observed.terminal != journal
            or observed.manifest_sha256 != rejected.rejection_manifest_sha256
            or observed.candidate_ids != rejected.candidate_ids
            or observed.execution_receipt_sha256s != evidence.execution_receipt_sha256s
            or observed.evaluation_receipt_sha256s != evidence.evaluation_receipt_sha256s
            or observed.retained_evidence_sha256s != evidence.retained_evidence_sha256s):
        _fail("rejection_material_drift")
    verify_material_pins()
    if (read_native_rsi_rejection_provenance(batch, expected_file_pin=p_pin) != evidence
            or dict(evidence.ledger_identity) != _read_ledger_identity(ledger)):
        _fail("rejection_provenance_drift")
    return journal.digest()


def _publication(workspace, publication: dict, binding: dict, roots: list, *, ledger=None) -> str:
    """Require the original first published or C1/P/C2 rejected batch."""
    from . import producer_bundle_recovery as recovery
    from .producer_bundle_admission import parse_producer_bundle_admission_plan
    from .producer_bundle_lineage import (
        LineageSnapshotPin,
        lineage_directory,
        read_lineage_descriptor_pinned,
        verify_persisted_lineage_snapshot,
    )
    from .producer_bundle_publication import parse_producer_bundle_publication_journal
    from .rsi_brs_publication_lineage import _policy
    from .rsi_publication_lineage import _root_pin

    wire = publication["lineage"]
    policy = _policy()
    if (any(state.get("producer_brs_checkpoint_policy") != policy for _head, state in roots)
            or type(wire) is not dict or wire.get("policy_sha256") != _digest(policy)):
        _fail("policy_drift")
    if (type(wire) is not dict or wire.get("protocol") != "lunar-rsi-brs-lineage-checkpoint-v1"
            or set(wire) != {"protocol", "run_id", "workspace", "run_request_sha256",
                             "root_proof_sha256", "policy_sha256", "max_batches", "batches", "head", "rejections"}
            or wire["run_id"] != binding["run_id"]
            or wire["workspace"] != _root_pin(recovery._workspace(workspace))
            or type(wire.get("batches")) is not list or len(wire["batches"]) != 1
            or roots[-1][1].get("producer_publication_lineage") != wire):
        _fail("publication_lineage_drift")
    journal = parse_producer_bundle_publication_journal(publication["journal"])
    if journal.state == "all_rejected":
        return _rejected_publication(workspace, publication, binding, roots, ledger=ledger)
    if wire["rejections"] != []:
        _fail("publication_lineage_drift")
    entry = wire["batches"][0]
    base_fields = {"journal_id", "ordinal", "episode_id", "request_sha256", "memory_snapshot_sha256",
                   "native_plan_sha256", "admission_plan", "prepared_journal", "before", "before_file_pin",
                   "snapshots", "before_sources", "state", "evidence_pins", "staged", "staged_file_pin",
                   "state_projection_sha256", "after_sources", "terminal", "terminal_file_pin",
                   "published_journal", "head_sources"}
    if (type(entry) is not dict or set(entry) != base_fields or entry["state"] != "terminal"
            or type(entry["ordinal"]) is not int or entry["ordinal"] != 0
            or entry["episode_id"] != binding["episode_id"]
            or entry["request_sha256"] != binding["selected_request_sha256"]
            or entry["native_plan_sha256"] != binding["native_plan_sha256"]):
        _fail("publication_entry_drift")
    journal = parse_producer_bundle_publication_journal(publication["journal"])
    prepared = parse_producer_bundle_publication_journal(entry["prepared_journal"])
    plan = parse_producer_bundle_admission_plan(entry["admission_plan"])
    if (journal.to_dict() != entry["published_journal"] or journal.state != "published"
            or journal.journal_id != entry["journal_id"] or journal.run_id != binding["run_id"]
            or journal.task_id != binding["episode_id"] or journal.admission_sha256 != plan.digest()
            or prepared.state != "prepared" or prepared.run_id != journal.run_id
            or prepared.task_id != journal.task_id or prepared.journal_id != journal.journal_id
            or prepared.admission_sha256 != plan.digest()):
        _fail("publication_journal_drift")
    batch = recovery._batch(recovery._workspace(workspace), journal.journal_id)
    descriptors = {}
    for kind in ("before", "staged", "terminal"):
        pin = LineageSnapshotPin.from_dict(entry[kind + "_file_pin"])
        if pin.name != kind + ".json":
            _fail("publication_pin_drift")
        observed = read_lineage_descriptor_pinned(workspace, journal.journal_id, kind=kind, expected_file_pin=pin)
        if (observed.to_dict() != entry[kind] or observed.run_id != binding["run_id"]
                or observed.journal_id != journal.journal_id or observed.ordinal != 0):
            _fail("publication_descriptor_drift")
        descriptors[kind] = observed
    before, staged, terminal = (descriptors[kind] for kind in ("before", "staged", "terminal"))
    if (before.predecessor_terminal_sha256 is not None or before.predecessor_lineage_sha256 is not None
            or staged.before_sha256 != before.digest() or terminal.staged_sha256 != staged.digest()
            or terminal.terminal_sha256 != journal.terminal_marker_sha256
            or staged.archive_after_sha256 != journal.archive_after_sha256
            or staged.state_after_sha256 != journal.state_after_sha256
            or terminal.archive_after_sha256 != staged.archive_after_sha256
            or terminal.state_after_sha256 != staged.state_after_sha256
            or prepared.base_archive_sha256 != before.archive.sha256
            or prepared.base_state_sha256 != before.state.sha256):
        _fail("publication_chain_drift")
    snapshots = entry["snapshots"]
    if (type(snapshots) is not dict or set(snapshots) != {
        "archive-before", "state-before", "archive-after", "state-after",
    } or type(entry["evidence_pins"]) is not dict or set(entry["evidence_pins"]) != {
        "journal.prepared.json", "journal.staged.json", "manifest.json", "preflight.json",
        "journal.published.json", "terminal.json",
    }):
        _fail("publication_pin_drift")
    for name, raw in snapshots.items():
        pin = LineageSnapshotPin.from_dict(raw)
        if pin.name != name + ".snapshot":
            _fail("publication_pin_drift")
        verify_persisted_lineage_snapshot(lineage_directory(workspace, journal.journal_id) / pin.name, pin)
    if (before.archive.to_dict() != snapshots["archive-before"]
            or before.state.to_dict() != snapshots["state-before"]
            or snapshots["archive-after"]["sha256"] != staged.archive_after_sha256
            or snapshots["state-after"]["sha256"] != staged.state_after_sha256):
        _fail("publication_snapshot_drift")
    sources = entry["before_sources"]
    if type(sources) is not dict or set(sources) != {"archive", "state"}:
        _fail("publication_source_drift")
    for name, raw in sources.items():
        snapshot = LineageSnapshotPin.from_dict(snapshots[name + "-before"])
        if name == "archive" and type(raw) is dict and raw.get("missing") is True:
            if (set(raw) != {"missing", "parent"} or raw["parent"] != _root_pin(batch.parent.parent)
                    or snapshot.size != 0 or snapshot.sha256 != hashlib.sha256(b"").hexdigest()):
                _fail("publication_source_drift")
        else:
            pin = LineageSnapshotPin.from_dict(raw)
            if pin.name != name + "-before" or pin.sha256 != snapshot.sha256 or pin.size != snapshot.size:
                _fail("publication_source_drift")
    for field, suffix in (("after_sources", "after"), ("head_sources", "before")):
        if type(entry[field]) is not dict or set(entry[field]) != {"archive", "state"}:
            _fail("publication_source_drift")
        for name, raw in entry[field].items():
            pin = LineageSnapshotPin.from_dict(raw)
            snapshot = LineageSnapshotPin.from_dict(snapshots[name + "-after"])
            if pin.name != name + "-" + suffix or pin.sha256 != snapshot.sha256 or pin.size != snapshot.size:
                _fail("publication_source_drift")
            if field == "head_sources":
                after = LineageSnapshotPin.from_dict(entry["after_sources"][name])
                if any(getattr(after, key) != getattr(pin, key) for key in (
                    "device", "inode", "size", "mode", "nlink", "mtime_ns", "sha256",
                )):
                    _fail("publication_source_drift")
                filename = "archive.jsonl" if name == "archive" else "state.json"
                verify_persisted_lineage_snapshot(batch.parent.parent / filename, pin)
    for name, raw in entry["evidence_pins"].items():
        pin = LineageSnapshotPin.from_dict(raw)
        if pin.name != name:
            _fail("publication_pin_drift")
        verify_persisted_lineage_snapshot(batch / name, pin)
    if (recovery._read_journal(batch / "journal.prepared.json") != prepared
            or recovery._read_journal(batch / "journal.staged.json").digest() != staged.journal_sha256
            or recovery._read_json(batch / "manifest.json", 256 * 1024) != publication["manifest"]):
        _fail("publication_material_drift")
    observed = recovery.resume_producer_bundle_publication(workspace, plan, journal)
    if (observed.status != "published" or observed.journal_sha256 != journal.digest()
            or observed.manifest_sha256 != staged.manifest_sha256
            or observed.candidate_ids != staged.candidate_ids):
        _fail("publication_terminal_drift")
    head = wire.get("head")
    if head != {"journal_id": journal.journal_id, "terminal_sha256": terminal.terminal_sha256,
                "lineage_sha256": terminal.digest()}:
        _fail("publication_head_drift")
    return journal.digest()


def _finish(ledger, run_id: str, episode_id: str, report: dict, pins: dict, evidence=None):
    if _pins(ledger.read_brs_terminal_evidence_snapshot(run_id, episode_id)["pins"]) != pins:
        _fail("inspection_drift")
    report["observation_sha256"] = _digest(report)
    return parse_brs_terminal_observation(report), evidence, dict(pins)


def _compose_brs_terminal_evidence(
    ledger, run_id: str, episode_id: str, *, workspace, native_plan,
    intent=None, attestation=None, artifact=None,
) -> tuple[dict, BRSReconcileEvidence | None, dict]:
    """Fresh independent reads; the caller must atomically recheck returned pins."""
    from .rsi_store import RSILedger

    if type(ledger) is not RSILedger:
        _fail("ledger_invalid")
    _text(run_id)
    _text(episode_id)
    snapshot = ledger.read_brs_terminal_evidence_snapshot(run_id, episode_id)
    pins = _pins(snapshot["pins"])
    roots = snapshot["roots"]
    obligation = parse_brs_reconcile_obligations(roots[-1][1].get(FIELD)).get(episode_id)
    if obligation is None:
        _fail("obligation_missing")
    report = {"protocol": PROTOCOL, "run_id": run_id, "episode_id": episode_id,
              "status": "unknown", "reason": "mailbox_missing", "source_pins": pins,
              "mailbox_binding_sha256": None, "native_process_binding_sha256": None,
              "mailbox_observation": None, "callback_observation": "unobserved",
              "worker_terminal": False, "native_process_observation": None,
              "publication_sha256": None, "terminal_status": None, "evidence": None}
    mailbox = inspect_brs_mailbox_evidence(ledger, run_id, episode_id)
    report["mailbox_observation"] = {
        "status": mailbox["status"], "head": mailbox["head"], "terminal_evidence": False,
    }
    if mailbox["binding"] is None:
        return _finish(ledger, run_id, episode_id, report, pins)
    binding = mailbox["binding"]
    report["mailbox_binding_sha256"] = binding["binding_sha256"]
    process = binding["capture"]["native_process"]
    report["native_process_binding_sha256"] = process["binding_sha256"]
    report["reason"] = "mailbox_partial"
    if mailbox["status"] != "transport_observed":
        return _finish(ledger, run_id, episode_id, report, pins)
    lifecycle = inspect_brs_worker_terminal_evidence(ledger, run_id, episode_id)
    if lifecycle["snapshot_pins"] != pins:
        _fail("inspection_drift")
    report["callback_observation"] = lifecycle["callback_observation"]
    report["worker_terminal"] = lifecycle["worker_terminal"]
    report["reason"] = "worker_terminal_missing"
    if lifecycle["binding"] is not None and lifecycle["binding"]["mailbox_binding"] != binding:
        _fail("worker_binding_drift")
    if not lifecycle["worker_terminal"] or lifecycle["callback_observation"] != "returned":
        return _finish(ledger, run_id, episode_id, report, pins)
    if lifecycle["records"][-1]["facts"]["future_outcome"] != "returned":
        report["reason"] = "worker_future_raised"
        return _finish(ledger, run_id, episode_id, report, pins)
    observed = observe_native_process_binding(
        process, workspace=workspace, native_plan=native_plan,
        intent=intent, attestation=attestation, artifact=artifact,
    )
    report["native_process_observation"] = observed
    if observed["status"] == "drifted":
        _fail("native_process_drift")
    report["reason"] = "native_process_unknown"
    if (observed["status"] != "exited" or observed["process_state"] != "exited"
            or observed["process_group"] != "absent" or observed["observed_owner_identity"] is not None
            or observed["cleanup_confirmed"] is not True):
        return _finish(ledger, run_id, episode_id, report, pins)
    publication = lifecycle["delivery"]["publication"]
    from .rsi_brs_publication_lineage import _policy

    policy = _policy()
    with ledger.read_only_observations():
        run_history = ledger.history(run_id)
    if not run_history or any(record.payload.get("producer_brs_checkpoint_policy") != policy for record in run_history):
        _fail("policy_drift")
    publication_reader = (_reserved_publication if roots[0][1].get("plan", {}).get(
        "reserved_native_serial") is True else _publication)
    try:
        report["publication_sha256"] = publication_reader(workspace, publication, binding, roots, ledger=ledger)
    except RSILearningError:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        raise RSILearningError("rsi_brs_terminal_evidence_publication_drift") from exc
    terminal = _ledger_terminal(snapshot, obligation, binding)
    report["reason"] = "durable_terminal_missing"
    if terminal is None:
        return _finish(ledger, run_id, episode_id, report, pins)
    claim, result, result_sha = terminal
    if publication["journal"]["state"] == "all_rejected" and result.status != "failed":
        _fail("rejection_result_drift")
    # Reobserve independently pinned files after the ledger projection checks.
    try:
        publication_sha = publication_reader(workspace, publication, binding, roots, ledger=ledger)
    except RSILearningError:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        raise RSILearningError("rsi_brs_terminal_evidence_publication_drift") from exc
    if publication_sha != report["publication_sha256"]:
        _fail("publication_drift")
    again = observe_native_process_binding(
        process, workspace=workspace, native_plan=native_plan,
        intent=intent, attestation=attestation, artifact=artifact,
    )
    if again != observed:
        _fail("native_process_drift")
    evidence = BRSReconcileEvidence(
        obligation_sha256=obligation.digest(), handoff_sha256=obligation.handoff_sha256,
        request_sha256=obligation.request_sha256, native_plan_sha256=obligation.native_plan_sha256,
        controller_checkpoint_sha256=obligation.controller_checkpoint_sha256,
        episode_record_sha256=obligation.episode_record_sha256,
        native_claim_sha256=obligation.native_claim_sha256, owner_result_sha256=obligation.owner_result_sha256,
        process_state="exited", process_evidence_sha256=observed["observation_sha256"],
        native_evidence_sha256=claim.claim_sha256, mailbox_evidence_sha256=lifecycle["head"],
        result_evidence_sha256=result_sha, mailbox_state="closed", transaction_state="terminal",
        terminal_status=result.status, controller_observed_terminal=True, cleanup_confirmed=True,
        reason="original-independent-terminal-evidence",
    )
    report.update(status="ready", reason="independent_terminal_verified", terminal_status=result.status,
                  evidence=evidence.to_dict())
    return _finish(ledger, run_id, episode_id, report, pins, evidence)


def inspect_brs_terminal_observation(
    ledger, run_id: str, episode_id: str, *, workspace, native_plan,
    intent=None, attestation=None, artifact=None,
) -> dict:
    """Return only detached read-only observations, never a consumption handle."""
    return _compose_brs_terminal_evidence(
        ledger, run_id, episode_id, workspace=workspace, native_plan=native_plan,
        intent=intent, attestation=attestation, artifact=artifact,
    )[0]


def _reserved_published_publication(workspace, publication, binding, roots, *, ledger,
                                    ordinal, prefix, original_lineage_bytes):
    """Reobserve a real published child under its independently derived prefix."""
    from . import producer_bundle_recovery as recovery
    from .producer_bundle_admission import parse_producer_bundle_admission_plan
    from .producer_bundle_lineage import (
        LineageSnapshotPin,
        lineage_directory,
        read_lineage_descriptor_pinned,
        verify_persisted_lineage_snapshot,
    )
    from .producer_bundle_publication import parse_producer_bundle_publication_journal
    from .rsi_brs_publication_lineage import _policy
    from .rsi_publication_lineage import _root_pin

    wire = publication["lineage"]
    policy = _policy()
    if (any(state.get("producer_brs_checkpoint_policy") != policy for _head, state in roots)
            or type(wire) is not dict or wire.get("policy_sha256") != _digest(policy)):
        _fail("policy_drift")
    if (type(wire) is not dict or wire.get("protocol") != "lunar-rsi-brs-lineage-checkpoint-v1"
            or set(wire) != {"protocol", "run_id", "workspace", "run_request_sha256",
                             "root_proof_sha256", "policy_sha256", "max_batches", "batches", "head", "rejections"}
            or wire["run_id"] != binding["run_id"]
            or wire["workspace"] != _root_pin(recovery._workspace(workspace))
            or type(wire.get("batches")) is not list or len(wire["batches"]) != ordinal + 1
            or roots[-1][1].get("producer_publication_lineage", {}).get("batches", [])[:ordinal + 1] != wire["batches"]):
        _fail("publication_lineage_drift")
    journal = parse_producer_bundle_publication_journal(publication["journal"])
    if journal.state != "published":
        _fail("publication_journal_drift")
    entry = wire["batches"][ordinal]
    base_fields = {"journal_id", "ordinal", "episode_id", "request_sha256", "memory_snapshot_sha256",
                   "native_plan_sha256", "admission_plan", "prepared_journal", "before", "before_file_pin",
                   "snapshots", "before_sources", "state", "evidence_pins", "staged", "staged_file_pin",
                   "state_projection_sha256", "after_sources", "terminal", "terminal_file_pin",
                   "published_journal", "head_sources"}
    if (type(entry) is not dict or set(entry) != base_fields or entry["state"] != "terminal"
            or type(entry["ordinal"]) is not int or entry["ordinal"] != ordinal
            or entry["episode_id"] != binding["episode_id"]
            or entry["request_sha256"] != binding["selected_request_sha256"]
            or entry["native_plan_sha256"] != binding["native_plan_sha256"]):
        _fail("publication_entry_drift")
    journal = parse_producer_bundle_publication_journal(publication["journal"])
    prepared = parse_producer_bundle_publication_journal(entry["prepared_journal"])
    plan = parse_producer_bundle_admission_plan(entry["admission_plan"])
    if (journal.to_dict() != entry["published_journal"] or journal.state != "published"
            or journal.journal_id != entry["journal_id"] or journal.run_id != binding["run_id"]
            or journal.task_id != binding["episode_id"] or journal.admission_sha256 != plan.digest()
            or prepared.state != "prepared" or prepared.run_id != journal.run_id
            or prepared.task_id != journal.task_id or prepared.journal_id != journal.journal_id
            or prepared.admission_sha256 != plan.digest()):
        _fail("publication_journal_drift")
    batch = recovery._batch(recovery._workspace(workspace), journal.journal_id)
    descriptors = {}
    for kind in ("before", "staged", "terminal"):
        pin = LineageSnapshotPin.from_dict(entry[kind + "_file_pin"])
        if pin.name != ("before-v2.json" if kind == "before" and ordinal else kind + ".json"):
            _fail("publication_pin_drift")
        if kind == "before" and ordinal:
            from .producer_bundle_lineage_v2 import read_lineage_v2_descriptor_pinned
            observed = read_lineage_v2_descriptor_pinned(workspace, journal.journal_id,
                kind="before-v2", expected_file_pin=pin)
        else:
            observed = read_lineage_descriptor_pinned(workspace, journal.journal_id, kind=kind, expected_file_pin=pin)
        if (observed.to_dict() != entry[kind] or observed.run_id != binding["run_id"]
                or observed.journal_id != journal.journal_id or observed.ordinal != ordinal):
            _fail("publication_descriptor_drift")
        descriptors[kind] = observed
    before, staged, terminal = (descriptors[kind] for kind in ("before", "staged", "terminal"))
    if ordinal:
        if ((before.previous_attempt_journal_id, before.previous_attempt_outcome,
             before.previous_attempt_terminal_sha256, before.previous_attempt_lineage_sha256) != prefix.previous_attempt
                or (before.published_predecessor_journal_id, before.published_predecessor_terminal_sha256,
                    before.published_predecessor_lineage_sha256) != (prefix.published_predecessor or (None, None, None))):
            _fail("publication_predecessor_drift")
    elif before.predecessor_terminal_sha256 is not None or before.predecessor_lineage_sha256 is not None:
        _fail("publication_predecessor_drift")
    if (staged.before_sha256 != before.digest() or terminal.staged_sha256 != staged.digest()
            or terminal.terminal_sha256 != journal.terminal_marker_sha256
            or staged.archive_after_sha256 != journal.archive_after_sha256
            or staged.state_after_sha256 != journal.state_after_sha256
            or terminal.archive_after_sha256 != staged.archive_after_sha256
            or terminal.state_after_sha256 != staged.state_after_sha256
            or prepared.base_archive_sha256 != before.archive.sha256
            or prepared.base_state_sha256 != before.state.sha256):
        _fail("publication_chain_drift")
    snapshots = entry["snapshots"]
    if (type(snapshots) is not dict or set(snapshots) != {
        "archive-before", "state-before", "archive-after", "state-after",
    } or type(entry["evidence_pins"]) is not dict or set(entry["evidence_pins"]) != {
        "journal.prepared.json", "journal.staged.json", "manifest.json", "preflight.json",
        "journal.published.json", "terminal.json",
    }):
        _fail("publication_pin_drift")
    for name, raw in snapshots.items():
        pin = LineageSnapshotPin.from_dict(raw)
        if pin.name != name + ".snapshot":
            _fail("publication_pin_drift")
        verify_persisted_lineage_snapshot(lineage_directory(workspace, journal.journal_id) / pin.name, pin)
    if (before.archive.to_dict() != snapshots["archive-before"]
            or before.state.to_dict() != snapshots["state-before"]
            or snapshots["archive-after"]["sha256"] != staged.archive_after_sha256
            or snapshots["state-after"]["sha256"] != staged.state_after_sha256):
        _fail("publication_snapshot_drift")
    sources = entry["before_sources"]
    if type(sources) is not dict or set(sources) != {"archive", "state"}:
        _fail("publication_source_drift")
    for name, raw in sources.items():
        snapshot = LineageSnapshotPin.from_dict(snapshots[name + "-before"])
        if name == "archive" and type(raw) is dict and raw.get("missing") is True:
            if (set(raw) != {"missing", "parent"} or raw["parent"] != _root_pin(batch.parent.parent)
                    or snapshot.size != 0 or snapshot.sha256 != hashlib.sha256(b"").hexdigest()):
                _fail("publication_source_drift")
        else:
            pin = LineageSnapshotPin.from_dict(raw)
            if pin.name != name + "-before" or pin.sha256 != snapshot.sha256 or pin.size != snapshot.size:
                _fail("publication_source_drift")
    for field, suffix in (("after_sources", "after"), ("head_sources", "before")):
        if type(entry[field]) is not dict or set(entry[field]) != {"archive", "state"}:
            _fail("publication_source_drift")
        for name, raw in entry[field].items():
            pin = LineageSnapshotPin.from_dict(raw)
            snapshot = LineageSnapshotPin.from_dict(snapshots[name + "-after"])
            if pin.name != name + "-" + suffix or pin.sha256 != snapshot.sha256 or pin.size != snapshot.size:
                _fail("publication_source_drift")
            if field == "head_sources":
                after = LineageSnapshotPin.from_dict(entry["after_sources"][name])
                if any(getattr(after, key) != getattr(pin, key) for key in (
                    "device", "inode", "size", "mode", "nlink", "mtime_ns", "sha256",
                )):
                    _fail("publication_source_drift")
                filename = "archive.jsonl" if name == "archive" else "state.json"
                if len(roots[-1][1]["producer_publication_lineage"]["batches"]) == ordinal + 1:
                    verify_persisted_lineage_snapshot(batch.parent.parent / filename, pin)
    for name, raw in entry["evidence_pins"].items():
        pin = LineageSnapshotPin.from_dict(raw)
        if pin.name != name:
            _fail("publication_pin_drift")
        verify_persisted_lineage_snapshot(batch / name, pin)
    if (recovery._read_journal(batch / "journal.prepared.json") != prepared
            or recovery._read_journal(batch / "journal.staged.json").digest() != staged.journal_sha256
            or recovery._read_json(batch / "manifest.json", 256 * 1024) != publication["manifest"]):
        _fail("publication_material_drift")
    preflight = recovery._read_json(batch / "preflight.json", 128 * 1024)
    staged_journal = recovery._read_journal(batch / "journal.staged.json")
    preflight_sha = recovery._check_preflight(preflight, staged_journal, plan)
    manifest_sha, ids, _paths, files = recovery._manifest(publication["manifest"], staged_journal, preflight_sha)
    recovery._verify_python_handoff(batch, journal, plan)
    recovery._verify_manifest_files(recovery._workspace(workspace), batch, files, journal)
    observed = recovery._verify_terminal_batch_evidence(recovery._workspace(workspace), batch, journal, manifest_sha)
    if (observed.terminal_marker_sha256 != terminal.terminal_sha256
            or manifest_sha != staged.manifest_sha256 or ids != staged.candidate_ids
            or observed.archive_after_sha256 != staged.archive_after_sha256
            or observed.state_after_sha256 != staged.state_after_sha256):
        _fail("publication_terminal_drift")
    head = wire.get("head")
    if head != {"journal_id": journal.journal_id, "terminal_sha256": terminal.terminal_sha256,
                "lineage_sha256": terminal.digest()}:
        _fail("publication_head_drift")
    return journal.digest()


def _reserved_publication_scope(workspace, publication, binding, roots, *, ledger):
    """Derive selected ancestry from the earliest real full reservation, read-only."""
    from .rsi_brs_lineage_prefix import validate_brs_reserved_prefix
    from .rsi_brs_reserved_owner import read_reserved_brs_completion_prefix
    from .rsi_brs_reserved_reservation import read_reserved_brs_completion_reservation
    from .rsi_store import RSILedger

    if type(ledger) is not RSILedger:
        _fail("reserved_ledger_invalid")
    publication, binding = _clean(publication), _clean(binding)
    if (type(binding.get("handoff")) is not dict or type(binding.get("run_id")) is not str
            or type(binding.get("episode_id")) is not str):
        _fail("reserved_selection_drift")
    if (type(roots) not in {tuple, list} or not roots
            or any(type(row) is not tuple or len(row) != 2 or type(row[0]) is not str
                   or type(row[1]) is not dict for row in roots)):
        _fail("reserved_roots_invalid")
    for _head, body in roots:
        _plain(body)
    with ledger.read_only_observations():
        actual_roots = RSILedger.controller_checkpoint_history(ledger, binding["run_id"])
    if canonical_json(list(actual_roots), maximum=8 * 1024 * 1024) != canonical_json(
            list(roots), maximum=8 * 1024 * 1024):
        _fail("reserved_roots_drift")
    current = actual_roots[-1][1]
    plan = current.get("plan")
    if (type(plan) is not dict or plan.get("reserved_native_serial") is not True
            or current.get("mode") != "brs" or plan.get("mode") != "brs"
            or type(plan.get("max_workers")) is not int or plan["max_workers"] != 1
            or type(plan.get("wave")) is not int or type(plan.get("practices")) is not list
            or not 1 <= len(plan["practices"]) <= 8):
        _fail("reserved_original_required")
    run_id = binding["run_id"]
    episodes = tuple(f"{run_id}-practice-{plan['wave']}-{ordinal}"
                     for ordinal in range(len(plan["practices"])))
    observed = read_reserved_brs_completion_reservation(ledger, run_id=run_id, episode_ids=episodes,
        expected_checkpoint_sha256=actual_roots[-1][0])
    original = (observed.original_checkpoint_sha256, observed.original_state_bytes)
    full, batches = read_reserved_brs_completion_prefix(ledger, workspace,
        original_checkpoint=original, expected_checkpoint_sha256=actual_roots[-1][0])
    ordinal = binding.get("handoff", {}).get("ordinal")
    domain = json.loads(full.domain_bytes)
    if (type(ordinal) is not int or not 0 <= ordinal < len(episodes)
            or ordinal > len(batches) or binding["episode_id"] != episodes[ordinal]
            or binding["selected_request_sha256"] != domain["request_sha256s"][ordinal]
            or binding["handoff"]["root_snapshot_sha256"] != domain["root_snapshot_sha256"]):
        _fail("reserved_selection_drift")
    domain["episode_ids"], domain["request_sha256s"] = tuple(domain["episode_ids"]), tuple(domain["request_sha256s"])
    prefix = validate_brs_reserved_prefix(**domain, batches=batches[:ordinal])
    original_wire = None if ordinal == 0 else batches[ordinal - 1]["root_checkpoint"][1]["producer_publication_lineage"]
    original_lineage_bytes = None if original_wire is None else canonical_json(original_wire, maximum=128 * 1024)
    wire = publication.get("lineage")
    actual_wire = current.get("producer_publication_lineage")
    if (type(wire) is not dict or type(actual_wire) is not dict
            or type(wire.get("batches")) is not list or len(wire["batches"]) != ordinal + 1
            or type(actual_wire.get("batches")) is not list
            or actual_wire["batches"][:ordinal + 1] != wire["batches"]
            or wire["batches"][:ordinal] != ([] if original_wire is None else original_wire["batches"])
            or any(wire.get(key) != actual_wire.get(key) for key in (
                "protocol", "run_id", "workspace", "run_request_sha256", "root_proof_sha256",
                "policy_sha256", "max_batches"))):
        _fail("reserved_publication_drift")
    active = wire["batches"][ordinal]
    if ordinal:
        expected_content = json.loads(prefix.canonical_bytes)["historical_poststate"]
        before_content = [[active["snapshots"][name]["sha256"], active["snapshots"][name]["size"]]
                          for name in ("archive-before", "state-before")]
        previous = original_wire["batches"][-1]
        previous_sources = previous["before_sources"] if previous["state"] == "rejected" else previous["head_sources"]
        if before_content != expected_content or active["before_sources"] != previous_sources:
            _fail("reserved_poststate_drift")
    old_index = [] if original_wire is None else original_wire["rejections"]
    expected_index = list(old_index)
    if active.get("state") == "rejected":
        from .producer_bundle_lineage_v2 import ProducerLineageRejectedTerminalV2
        rejected = ProducerLineageRejectedTerminalV2.from_dict(active["rejected"])
        expected_index.append({"ordinal": ordinal, "journal_id": rejected.journal_id,
                               "rejected_sha256": rejected.digest()})
    if wire.get("rejections") != expected_index:
        _fail("reserved_rejection_index_drift")
    return ordinal, prefix, original_lineage_bytes, observed


def _reserved_publication(workspace, publication, binding, roots, *, ledger):
    """Explicit private reader; the legacy first-batch API stays unchanged."""
    from .rsi_brs_rejection_provenance import verify_reserved_rejected_publication
    from .rsi_store import RSILedger

    if type(ledger) is not RSILedger:
        _fail("reserved_ledger_invalid")
    with ledger.read_only_observations():
        ordinal, prefix, original_lineage_bytes, observed = _reserved_publication_scope(
            workspace, publication, binding, roots, ledger=ledger)
        if publication["journal"]["state"] == "all_rejected":
            result = verify_reserved_rejected_publication(workspace, publication, binding, roots,
                ledger=ledger, ordinal=ordinal, prefix=prefix, original_lineage_bytes=original_lineage_bytes)
        else:
            result = _reserved_published_publication(workspace, publication, binding, roots,
                ledger=ledger, ordinal=ordinal, prefix=prefix, original_lineage_bytes=original_lineage_bytes)
        again = _reserved_publication_scope(workspace, publication, binding, roots, ledger=ledger)
        if again != (ordinal, prefix, original_lineage_bytes, observed):
            _fail("reserved_observation_changed")
        return result
