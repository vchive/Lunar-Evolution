"""Original-ledger and immutable-file observations for private reserved BRS owners.

The returned prefix is descriptive. Its caller still needs the original selected
wave, running claim, native material checks and controller-held exclusive lease.
No root, descriptor, claim or publication is created by these readers.
"""
from __future__ import annotations

import hashlib
import json
from threading import get_ident

from . import producer_bundle_recovery as recovery
from . import rsi_publication_lineage as lineage
from .candidate_evaluation_spec import canonical_json, strict_json
from .producer_bundle_lineage import (
    MAX_LINEAGE_BATCHES,
    LineageSnapshotPin,
    ProducerLineageBeforeIntent,
    ProducerLineageStagedTransition,
    ProducerLineageTerminal,
    capture_lineage_snapshot_pin,
    lineage_directory,
    read_lineage_descriptor_pinned,
    verify_persisted_lineage_snapshot,
)
from .producer_bundle_lineage_v2 import (
    ProducerLineageBeforeIntentV2,
    read_lineage_v2_descriptor_pinned,
)
from .rsi_brs_lineage_prefix import BRSLineagePrefix, validate_brs_reserved_prefix
from .rsi_brs_reserved_ledger import read_reserved_brs_completion_ledger
from .rsi_gateway import SolverRequest
from .rsi_learning import MemorySnapshot, RSILearningError
from .rsi_store import RSILedger

_FIELD = "producer_publication_lineage"


def _fail(reason):
    raise RSILearningError("rsi_brs_reserved_owner_" + reason)


def _original(ledger, original_checkpoint):
    if (type(ledger) is not RSILedger or type(original_checkpoint) is not tuple
            or len(original_checkpoint) != 2 or type(original_checkpoint[0]) is not str
            or type(original_checkpoint[1]) is not bytes or len(original_checkpoint[1]) > 128 * 1024):
        _fail("original_invalid")
    original = strict_json(original_checkpoint[1], maximum=128 * 1024)
    if type(original) is not dict or canonical_json(original, maximum=128 * 1024) != original_checkpoint[1]:
        _fail("original_invalid")
    run_id = original.get("run_id")
    with ledger.read_only_observations():
        history = RSILedger.controller_checkpoint_history(ledger, run_id)
    if (sum((head, canonical_json(body, maximum=128 * 1024)) == original_checkpoint
            for head, body in history) != 1
            or original.get("mode") != "brs" or original.get("status") != "running"
            or type(original.get("plan")) is not dict or original["plan"].get("mode") != "brs"
            or type(original["plan"].get("max_workers")) is not int or original["plan"]["max_workers"] != 1
            or original["plan"].get("reserved_native_serial") is not True
            or type(original["plan"].get("wave")) is not int
            or type(original["plan"].get("practices")) is not list
            or not 1 <= len(original["plan"]["practices"]) <= 8
            or original.get("executions") != {} or original.get(_FIELD) is not None):
        _fail("original_invalid")
    episodes = tuple(f"{run_id}-practice-{original['plan']['wave']}-{ordinal}"
                     for ordinal in range(len(original["plan"]["practices"])))
    if type(original.get("intents")) is not dict or set(original["intents"]) != set(episodes):
        _fail("original_invalid")
    return original, episodes, history


def _descriptor(workspace, entry, kind):
    pin = LineageSnapshotPin.from_dict(entry[kind + "_file_pin"])
    if kind == "rejected" or kind == "before" and entry["ordinal"] > 0:
        observed = read_lineage_v2_descriptor_pinned(workspace, entry["journal_id"],
            kind="before-v2" if kind == "before" else kind, expected_file_pin=pin)
    else:
        observed = read_lineage_descriptor_pinned(workspace, entry["journal_id"], kind=kind, expected_file_pin=pin)
    if observed.to_dict() != entry[kind]:
        _fail("descriptor_drift")
    return {"descriptor": observed.to_dict(), "file_pin": pin.to_dict()}


def _materials(workspace, entry):
    """Inventory the original retained 0600 lineage/evidence pins, without refresh."""
    batch = workspace / "evolution/producer-batches" / entry["journal_id"]
    held = []
    for kind in ("before", "staged", "terminal", "rejected"):
        if kind + "_file_pin" in entry:
            pin = LineageSnapshotPin.from_dict(entry[kind + "_file_pin"])
            held.append((lineage_directory(workspace, entry["journal_id"]) / pin.name, pin))
    for name, wire in entry["snapshots"].items():
        pin = LineageSnapshotPin.from_dict(wire)
        if pin.name != name + ".snapshot":
            _fail("snapshot_invalid")
        held.append((lineage_directory(workspace, entry["journal_id"]) / pin.name, pin))
    for name, wire in entry["evidence_pins"].items():
        pin = LineageSnapshotPin.from_dict(wire)
        expected_name = "rejection-" + hashlib.sha256(name.encode()).hexdigest() if name.startswith("rejections/") else name
        if pin.name != expected_name:
            _fail("material_invalid")
        held.append((batch / name, pin))
    materials = []
    for path, pin in held:
        verify_persisted_lineage_snapshot(path, pin)
        if capture_lineage_snapshot_pin(path, name=pin.name) != pin:
            _fail("material_drift")
        materials.append({"relative_path": path.relative_to(workspace).as_posix(), "file_pin": pin.to_dict()})
    return tuple(materials)


def read_reserved_brs_prefix(ledger, workspace, *, original_checkpoint, expected_checkpoint_sha256):
    """Derive an entire settled prefix from real roots, ledger rows and original pins.

    An active suffix may exist in the current lineage, but it is never counted as
    settled without the original durable root execution. The whole-domain ledger
    scan includes that suffix and all untouched siblings.
    """
    if type(ledger) is not RSILedger:
        _fail("ledger_invalid")
    original = strict_json(original_checkpoint[1], maximum=128 * 1024) if (
        type(original_checkpoint) is tuple and len(original_checkpoint) == 2
        and type(original_checkpoint[1]) is bytes) else {}
    if type(original) is not dict:
        _fail("original_invalid")
    RSILedger._assert_controller_lock(ledger, original.get("run_id"))
    result = _observe_reserved_brs_prefix(ledger, workspace, original_checkpoint=original_checkpoint,
                                        expected_checkpoint_sha256=expected_checkpoint_sha256)
    RSILedger._assert_controller_lock(ledger, original.get("run_id"))
    return result


def read_reserved_brs_completion_prefix(ledger, workspace, *, original_checkpoint, expected_checkpoint_sha256):
    """Independent worker observations only; no owner, lease or selection is returned."""
    return _observe_reserved_brs_prefix(ledger, workspace, original_checkpoint=original_checkpoint,
                                       expected_checkpoint_sha256=expected_checkpoint_sha256)


def read_reserved_brs_finalization_prefix(ledger, workspace, *, original_checkpoint, expected_checkpoint_sha256):
    """Complete immutable attempt history, without live-child or selection authority."""
    if (type(ledger) is not RSILedger or type(original_checkpoint) is not tuple
            or len(original_checkpoint) != 2 or type(original_checkpoint[1]) is not bytes):
        _fail("original_invalid")
    original = strict_json(original_checkpoint[1], maximum=128 * 1024)
    if type(ledger) is not RSILedger or type(original) is not dict:
        _fail("original_invalid")
    RSILedger._assert_controller_lock(ledger, original.get("run_id"))
    result = _observe_reserved_brs_prefix(ledger, workspace, original_checkpoint=original_checkpoint,
        expected_checkpoint_sha256=expected_checkpoint_sha256, finalization=True)
    RSILedger._assert_controller_lock(ledger, original.get("run_id"))
    return result


def _observe_reserved_brs_prefix(ledger, workspace, *, original_checkpoint, expected_checkpoint_sha256,
                                 finalization=False):
    original, episodes, history = _original(ledger, original_checkpoint)
    workspace = recovery._workspace(workspace)
    observation = read_reserved_brs_completion_ledger(ledger, run_id=original["run_id"], episode_ids=episodes,
        expected_checkpoint_sha256=expected_checkpoint_sha256)
    current = strict_json(observation.checkpoint_bytes, maximum=128 * 1024)
    if finalization and (type(current.get("executions")) is not dict
                         or set(current["executions"]) != set(episodes)):
        _fail("finalization_incomplete")
    for key in ("run_id", "mode", "plan", "pins", "root_snapshot", "memory_snapshot", "intents", "budget_state",
                "producer_checkpoint_binding", "producer_brs_checkpoint_policy"):
        if finalization and key in {"memory_snapshot", "budget_state"}:
            continue
        if current.get(key) != original.get(key):
            _fail("original_drift")
    executions = current.get("executions")
    if type(executions) is not dict or set(executions) != set(episodes[:len(executions)]):
        _fail("noncontiguous_settlement")
    count, wire = len(executions), current.get(_FIELD)
    if wire is None:
        if count:
            _fail("lineage_missing")
        entries = []
    else:
        if (type(wire) is not dict or type(wire.get("batches")) is not list
                or not count <= len(wire["batches"]) <= min(count + 1, len(episodes))):
            _fail("lineage_invalid")
        entries = wire["batches"][:count]
    traces = observation.ledger_traces()
    requests = tuple(SolverRequest.from_dict(original["intents"][key]["request"]) for key in episodes)
    root_index = next(index for index, item in enumerate(history) if item[0] == original_checkpoint[0])
    prior_head, batches = original_checkpoint[0], []
    for ordinal, entry in enumerate(entries):
        key, request = episodes[ordinal], requests[ordinal]
        if (type(entry) is not dict or entry.get("ordinal") != ordinal or entry.get("episode_id") != key
                or entry.get("state") not in {"terminal", "rejected"}
                or traces[key]["claim"] is None or traces[key]["result"] != executions[key]["result"]
                or traces[key]["episode"] != executions[key]["episode"]):
            _fail("settled_association_drift")
        matches = [(index, head, body) for index, (head, body) in enumerate(history)
                   if index > root_index and key in body.get("executions", {})]
        if not matches:
            _fail("settlement_root_missing")
        index, head, body = matches[0]
        settled_wire = body.get(_FIELD)
        if (body["executions"] != {episode: executions[episode] for episode in episodes[:ordinal + 1]}
                or type(settled_wire) is not dict or settled_wire.get("batches") != entries[:ordinal + 1]):
            _fail("settlement_root_drift")
        for _later_head, later in history[index:]:
            if later.get("executions", {}).get(key) != executions[key]:
                _fail("settlement_execution_drift")
        outcome = "published" if entry["state"] == "terminal" else "all_rejected"
        before = _descriptor(workspace, entry, "before")
        terminal = _descriptor(workspace, entry, "terminal" if outcome == "published" else "rejected")
        staged = _descriptor(workspace, entry, "staged") if outcome == "published" else None
        batches.append({"ordinal": ordinal, "episode_id": key, "request_sha256": request.digest(),
            "native_plan_sha256": entry["native_plan_sha256"], "outcome": outcome,
            "execution_bytes": canonical_json(executions[key], maximum=128 * 1024),
            "entry_checkpoint_sha256": prior_head, "root_checkpoint": (head, body),
            "claim": traces[key]["claim"], "before": before, "staged": staged, "terminal": terminal,
            "snapshots": entry["snapshots"], "materials": _materials(workspace, entry)})
        root_index, prior_head = index, head
    prefix = validate_brs_reserved_prefix(run_id=original["run_id"], wave=original["plan"]["wave"],
        episode_ids=episodes, request_sha256s=tuple(request.digest() for request in requests),
        root_snapshot_sha256=MemorySnapshot.from_dict(original["root_snapshot"]).digest(),
        base_checkpoint_sha256=original_checkpoint[0], batches=tuple(batches))
    repeated = read_reserved_brs_completion_ledger(ledger, run_id=original["run_id"], episode_ids=episodes,
        expected_checkpoint_sha256=expected_checkpoint_sha256)
    if repeated != observation:
        _fail("observation_changed")
    return prefix, tuple(batches)


def reserved_prefix_identity(owner):
    """Validate captured immutable prefix members before any foreign equality hook."""
    if type(owner._ordinal) is not int or not 0 <= owner._ordinal < MAX_LINEAGE_BATCHES:
        _fail("capture_drift")
    prefix = owner._reserved_prefix
    if prefix is None:
        if (owner._ordinal != 0 or owner._reserved_original_checkpoint is not None
                or owner._reserved_lineage_bytes is not None or owner._reserved_capture_bytes is not None):
            _fail("capture_drift")
        return
    if (type(prefix) is not BRSLineagePrefix or type(prefix.domain_bytes) is not bytes
            or type(prefix.canonical_bytes) is not bytes or type(prefix.batch_bytes) is not tuple
            or any(type(item) is not bytes for item in prefix.batch_bytes)
            or type(owner._ordinal) is not int or owner._ordinal != len(prefix.batch_bytes)
            or type(owner._reserved_capture_bytes) is not bytes
            or owner._reserved_capture_bytes != prefix.canonical_bytes
            or type(owner._reserved_original_checkpoint) is not tuple
            or len(owner._reserved_original_checkpoint) != 2
            or type(owner._reserved_original_checkpoint[0]) is not str
            or type(owner._reserved_original_checkpoint[1]) is not bytes
            or owner._reserved_lineage_bytes is not None and type(owner._reserved_lineage_bytes) is not bytes):
        _fail("capture_drift")


def reserved_before(owner, journal_id, archive, state):
    prefix = owner._reserved_prefix
    if prefix is None or owner._ordinal == 0:
        return ProducerLineageBeforeIntent(owner._run_id, journal_id, 0, None, None, archive, state)
    return ProducerLineageBeforeIntentV2(owner._run_id, journal_id, owner._ordinal,
        *prefix.previous_attempt, *(prefix.published_predecessor or (None, None, None)), archive, state)


def reserved_verify_before_links(owner, before, *, ordinal):
    if ordinal == 0:
        if (type(before) is not ProducerLineageBeforeIntent or before.predecessor_terminal_sha256 is not None
                or before.predecessor_lineage_sha256 is not None):
            _fail("predecessor_drift")
        return
    previous = published = None
    for raw in owner._reserved_prefix.batch_bytes[:ordinal]:
        item = json.loads(raw)
        terminal = item["terminal"]["descriptor"]
        previous = (terminal["journal_id"], item["outcome"],
            terminal["terminal_sha256"] if item["outcome"] == "published" else terminal["terminal_marker_sha256"],
            terminal["descriptor_sha256"])
        if item["outcome"] == "published":
            published = (previous[0], previous[2], previous[3])
    if (type(before) is not ProducerLineageBeforeIntentV2
            or (before.previous_attempt_journal_id, before.previous_attempt_outcome,
                before.previous_attempt_terminal_sha256, before.previous_attempt_lineage_sha256) != previous
            or (before.published_predecessor_journal_id, before.published_predecessor_terminal_sha256,
                before.published_predecessor_lineage_sha256) != (published or (None, None, None))):
        _fail("predecessor_drift")


def reserved_wire_scope(owner, wire, *, active=True):
    """Retain every original old batch, head and accumulated rejection index."""
    if owner._reserved_prefix is None:
        return
    reserved_prefix_identity(owner)
    old = (json.loads(owner._reserved_lineage_bytes) if owner._reserved_lineage_bytes is not None else
           {**owner._association, "batches": [], "head": None, "rejections": []})
    if (type(wire) is not dict or set(wire) != set(old)
            or any(wire.get(key) != value for key, value in owner._association.items())
            or type(wire.get("batches")) is not list
            or len(wire["batches"]) != owner._ordinal + int(active)
            or wire["batches"][:owner._ordinal] != old["batches"]
            or wire.get("rejections", [])[:len(old["rejections"])] != old["rejections"]):
        _fail("historical_prefix_drift")


def reserved_prefix_observe(owner):
    reserved_prefix_identity(owner)
    if owner._reserved_prefix is None:
        return
    observed, _batches = read_reserved_brs_prefix(owner._ledger, owner._workspace,
        original_checkpoint=owner._reserved_original_checkpoint, expected_checkpoint_sha256=owner._head)
    if observed != owner._reserved_prefix:
        _fail("prefix_observation_drift")


def _retained_observation_head(owner):
    """Return the durable head allowed during the owner's one CAS transition.

    ``pin_python_admission_record`` appends the reference map before the live
    owner adopts the returned head.  The prepared callback then re-enters the
    retained-prefix reader while the transition marker is held.  In that
    narrow window the old in-memory head is intentionally paired with the
    exact adjacent durable successor.  Accept only that one shape; every other
    mismatch continues to use the captured owner head and fails closed.
    """
    expected = owner._head
    wave = getattr(owner, "_wave", None)
    if wave is None:
        return expected
    if getattr(wave, "owner_thread", None) != get_ident():
        return expected
    history = owner._ledger.controller_checkpoint_history(owner._run_id)
    try:
        owner_pair = (owner._head, json.loads(owner._payload))
    except (TypeError, ValueError, json.JSONDecodeError):
        return expected
    # The durable pin is appended before the live wave adopts its new payload;
    # therefore ``wave.payload`` still names ``owner_pair`` while the durable
    # tail already contains the reference map.  Require exactly one owner pair
    # immediately before that tail and inspect only this adjacent CAS.
    if len(history) < 2 or history[-2] != owner_pair:
        return expected
    successor_head, successor_payload = history[-1]
    try:
        wave_payload = json.loads(wave.payload)
    except (TypeError, ValueError, json.JSONDecodeError):
        return expected
    # During the CAS the transition marker is set before the durable append and
    # cleared only after the wave adopts the successor.  The acknowledgement
    # then briefly runs with the marker cleared while the owner still retains
    # the old capture; accept that post-transition shape only when the live wave
    # points at this exact adjacent successor.
    transitioning = getattr(wave, "checkpoint_transition", False) is True
    if (not transitioning
            and (getattr(wave, "checkpoint_sha256", None) != successor_head
                 or wave_payload != successor_payload)):
        return expected
    if transitioning:
        # The owner holds the controller lease while its CAS transition is
        # marked.  An adjacent durable successor is therefore the owner’s own
        # write (it may change lineage, terminal evidence or references), and
        # the retained reader must validate that successor rather than the old
        # head.  The post-transition branch above remains stricter because the
        # marker has already been cleared.
        return successor_head
    previous, current = history[-2][1], history[-1][1]
    previous_keys, current_keys = set(previous), set(current)
    if (previous_keys - current_keys
            or current_keys - previous_keys not in (set(), {"python_admission_refs"})):
        return expected
    for key, value in previous.items():
        if key != "python_admission_refs" and current.get(key) != value:
            return expected
    previous_refs = previous.get("python_admission_refs", {})
    current_refs = current.get("python_admission_refs")
    if (not isinstance(previous_refs, dict) or not isinstance(current_refs, dict)
            or not set(previous_refs).issubset(current_refs)
            or any(current_refs[key] != value for key, value in previous_refs.items())
            or len(current_refs) != len(previous_refs) + 1):
        return expected
    return successor_head


def reserved_history(owner, state=None):
    """Check real mixed history without changing the DRS or genesis contracts."""
    from .rsi_brs_reserved_rejection import (
        validate_reserved_brs_c1_transition,
        validate_reserved_brs_c2_transition,
        validate_reserved_brs_rejected_entry,
    )

    reserved_prefix_identity(owner)
    expected_head = owner._head
    history = owner._ledger.controller_checkpoint_history(owner._run_id)
    if state is not None:
        if (not history or history[-1][1] != state
                or history[-1][0] != owner._head and (len(history) < 2 or history[-2][0] != owner._head)):
            _fail("history_observation_head_drift")
        expected_head = history[-1][0]
    else:
        expected_head = _retained_observation_head(owner)
    observed, batches = read_reserved_brs_prefix(owner._ledger, owner._workspace,
        original_checkpoint=owner._reserved_original_checkpoint, expected_checkpoint_sha256=expected_head)
    if observed != owner._reserved_prefix:
        _fail("prefix_observation_drift")
    domain = strict_json(observed.domain_bytes, maximum=112 * 1024)
    domain["episode_ids"], domain["request_sha256s"] = tuple(domain["episode_ids"]), tuple(domain["request_sha256s"])
    prefixes = [validate_brs_reserved_prefix(**domain, batches=batches[:ordinal])
                for ordinal in range(owner._ordinal + 1)]
    previous, prior_settled = None, None
    for _head, snapshot in history:
        wire = snapshot.get(_FIELD)
        if wire is None:
            if previous is not None:
                _fail("history_drift")
            continue
        if (type(wire) is not dict or set(wire) != {*owner._association, "batches", "head", "rejections"}
                or any(wire[key] != value for key, value in owner._association.items())
                or type(wire["batches"]) is not list or not 1 <= len(wire["batches"]) <= owner._ordinal + 1):
            _fail("history_drift")
        ordinal = len(wire["batches"]) - 1
        entry = wire["batches"][ordinal]
        if type(entry) is not dict or entry.get("ordinal") != ordinal:
            _fail("history_drift")
        if previous is None or len(wire["batches"]) == len(previous["batches"]) + 1:
            if (entry.get("state") != "before" or entry.get("evidence_pins") != {}
                    or previous is not None and (wire["batches"][:-1] != previous["batches"]
                        or wire["head"] != previous["head"] or wire["rejections"] != previous["rejections"]
                        or previous["batches"][-1]["state"] not in {"terminal", "rejected"}
                        or previous["batches"][-1]["state"] == "rejected"
                           and previous["batches"][-1].get("rejection_provenance") is None)):
                _fail("history_introduction_drift")
            prior_settled = None if previous is None else canonical_json(previous, maximum=128 * 1024)
        elif len(wire["batches"]) != len(previous["batches"]):
            _fail("history_drift")
        elif wire != previous:
            old = previous["batches"][ordinal]
            if wire["batches"][:-1] != previous["batches"][:-1]:
                _fail("history_prefix_drift")
            if entry.get("state") == "rejected":
                method = validate_reserved_brs_c2_transition if old["state"] == "rejected" else validate_reserved_brs_c1_transition
                method(previous, wire, prefix=prefixes[ordinal], original_lineage_bytes=prior_settled,
                       native_plan_sha256=entry["native_plan_sha256"])
            else:
                phases = ("before", "staged", "terminal")
                if (old["state"] not in phases or entry.get("state") not in phases
                        or not 0 <= phases.index(entry["state"]) - phases.index(old["state"]) <= 1
                        or wire["rejections"] != previous["rejections"]):
                    _fail("history_delta_drift")
                for key, value in old.items():
                    if key in {"snapshots", "evidence_pins"}:
                        if any(entry.get(key, {}).get(name) != pin for name, pin in value.items()):
                            _fail("history_delta_drift")
                    elif key != "state" and entry.get(key) != value:
                        _fail("history_delta_drift")
                if old["state"] == "before" and entry["state"] == "staged" and set(old["evidence_pins"]) != {"journal.prepared.json"}:
                    _fail("history_prepared_pin_missing")
        if entry.get("state") == "rejected":
            validate_reserved_brs_rejected_entry(entry, prefix=prefixes[ordinal],
                native_plan_sha256=entry["native_plan_sha256"], with_provenance=entry.get("rejection_provenance") is not None)
        else:
            owner._validate_entry_shape(entry)
        terminal = entry.get("terminal")
        expected_head = (None if prefixes[ordinal].published_predecessor is None else
            dict(zip(("journal_id", "terminal_sha256", "lineage_sha256"), prefixes[ordinal].published_predecessor, strict=True)))
        if terminal is not None:
            expected_head = {"journal_id": entry["journal_id"], "terminal_sha256": terminal["terminal_sha256"],
                             "lineage_sha256": terminal["descriptor_sha256"]}
        if wire["head"] != expected_head:
            _fail("history_head_drift")
        previous = wire
    if (owner._state if state is None else state).get(_FIELD) != previous:
        _fail("history_drift")
    settled_wire = json.loads(owner._reserved_lineage_bytes) if owner._reserved_lineage_bytes is not None else None
    for ordinal in range(owner._ordinal):
        entry = settled_wire["batches"][ordinal]
        if entry["state"] == "terminal":
            owner._verify_terminal_entry(entry, ordinal=ordinal,
                previous=settled_wire["batches"][ordinal - 1] if ordinal else None)
            reserved_published_materials(owner, entry)
        else:
            from .rsi_brs_rejection_provenance import verify_reserved_rejected_history
            prior = None
            if ordinal:
                original_entries = settled_wire["batches"][:ordinal]
                prior_wire = next(body[_FIELD] for _head, body in history
                                  if type(body.get(_FIELD)) is dict and body[_FIELD]["batches"] == original_entries)
                prior = canonical_json(prior_wire, maximum=128 * 1024)
            verify_reserved_rejected_history(owner, entry, ordinal=ordinal,
                prefix=prefixes[ordinal], original_lineage_bytes=prior)


def reserved_validate_entry_shape(owner, entry):
    """Published/before shape with the existing v1 genesis and v2 suffix name."""
    if owner._reserved_prefix is None:
        return lineage._LineageEvidenceReader._validate_entry_shape(owner, entry)
    from .rsi_brs_rejection_c1 import _BASE_FIELDS

    phase = entry.get("state")
    expected = set(_BASE_FIELDS)
    snapshots, pins = {"archive-before", "state-before"}, {"journal.prepared.json"}
    if phase in {"staged", "terminal"}:
        expected |= {"staged", "staged_file_pin", "state_projection_sha256", "after_sources"}
        snapshots |= {"archive-after", "state-after"}
        pins |= {"journal.staged.json", "manifest.json", "preflight.json"}
    if phase == "terminal":
        expected |= {"terminal", "terminal_file_pin", "published_journal", "head_sources"}
        pins |= {"journal.published.json", "terminal.json"}
    if (phase not in {"before", "staged", "terminal"} or set(entry) != expected
            or type(entry.get("snapshots")) is not dict or set(entry["snapshots"]) != snapshots
            or type(entry.get("evidence_pins")) is not dict
            or set(entry["evidence_pins"]) != pins and not (phase == "before" and entry["evidence_pins"] == {})):
        _fail("entry_shape_invalid")
    for name, pin in entry["snapshots"].items():
        if LineageSnapshotPin.from_dict(pin).name != name + ".snapshot":
            _fail("entry_shape_invalid")
    for name, pin in entry["evidence_pins"].items():
        if LineageSnapshotPin.from_dict(pin).name != name:
            _fail("entry_shape_invalid")
    for kind in ("before", "staged", "terminal"):
        if kind + "_file_pin" in entry:
            expected_name = "before-v2.json" if kind == "before" and entry["ordinal"] else kind + ".json"
            if LineageSnapshotPin.from_dict(entry[kind + "_file_pin"]).name != expected_name:
                _fail("entry_shape_invalid")
    owner._validate_source_pin_maps(entry)


def reserved_verify_descriptor(owner, entry, kind):
    if owner._reserved_prefix is None:
        return lineage._LineageEvidenceReader._verify_descriptor(owner, entry, kind)
    _descriptor(owner._workspace, entry, kind)
    cls = ProducerLineageBeforeIntentV2 if kind == "before" and entry["ordinal"] else None
    if cls is not None:
        return cls.from_dict(entry[kind])
    # Reuse the canonical reader directly; do not switch a global DRS version bit.
    return (read_lineage_v2_descriptor_pinned(owner._workspace, entry["journal_id"], kind=kind,
            expected_file_pin=LineageSnapshotPin.from_dict(entry[kind + "_file_pin"])) if kind == "rejected" else
        read_lineage_descriptor_pinned(owner._workspace, entry["journal_id"], kind=kind,
            expected_file_pin=LineageSnapshotPin.from_dict(entry[kind + "_file_pin"])))


def reserved_verify_terminal_entry(self, entry: dict, *, ordinal: int,
                           previous: dict | None) -> tuple[bytes, bytes]:
    from . import producer_bundle_recovery as recovery
    from .producer_bundle_admission import parse_producer_bundle_admission_plan
    from .producer_bundle_publication import parse_producer_bundle_publication_journal

    if self._reserved_prefix is None:
        return lineage._LineageEvidenceReader._verify_terminal_entry(self, entry, ordinal=ordinal, previous=previous)
    if type(entry) is not dict or entry.get("state") != "terminal" or entry.get("ordinal") != ordinal:
        _fail("pending_predecessor")
    self._validate_entry_shape(entry)
    before = self._verify_descriptor(entry, "before")
    staged = self._verify_descriptor(entry, "staged")
    terminal = self._verify_descriptor(entry, "terminal")
    before_type = ProducerLineageBeforeIntentV2 if ordinal else ProducerLineageBeforeIntent
    if (type(before) is not before_type or type(staged) is not ProducerLineageStagedTransition
            or type(terminal) is not ProducerLineageTerminal or before.ordinal != ordinal
            or staged.ordinal != ordinal or terminal.ordinal != ordinal
            or before.run_id != self._run_id or staged.run_id != self._run_id
            or terminal.run_id != self._run_id
            or staged.before_sha256 != before.digest() or terminal.staged_sha256 != staged.digest()):
        _fail("chain_invalid")
    reserved_verify_before_links(self, before, ordinal=ordinal)
    snapshots = entry["snapshots"]
    archive_before = self._snapshot_bytes(entry["journal_id"], snapshots["archive-before"], name="archive-before")
    state_before = self._snapshot_bytes(entry["journal_id"], snapshots["state-before"], name="state-before")
    archive_after = self._snapshot_bytes(entry["journal_id"], snapshots["archive-after"], name="archive-after")
    state_after = self._snapshot_bytes(entry["journal_id"], snapshots["state-after"], name="state-after")
    if (before.archive.to_dict() != snapshots["archive-before"]
            or before.state.to_dict() != snapshots["state-before"]
            or lineage._sha(archive_after) != staged.archive_after_sha256
            or lineage._sha(state_after) != staged.state_after_sha256
            or terminal.archive_after_sha256 != staged.archive_after_sha256
            or terminal.state_after_sha256 != staged.state_after_sha256):
        _fail("snapshot_drift")
    if previous is not None:
        old = previous["snapshots"]
        suffix = "before" if previous["state"] == "rejected" else "after"
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
            or observed.archive_after_sha256 != lineage._sha(archive_after)
            or observed.state_after_sha256 != lineage._sha(state_after)):
        _fail("terminal_drift")
    self._verify_transition_projection(entry, archive_before, state_before, archive_after, state_after)
    recovery._verify_python_handoff(batch, journal, plan)
    for name, held_pin in entry["evidence_pins"].items():
        verify_persisted_lineage_snapshot(batch / name, LineageSnapshotPin.from_dict(held_pin))
    return archive_after, state_after



def reserved_validate_source_pin_maps(self, entry: dict) -> None:
    if self._reserved_prefix is None:
        return lineage._LineageEvidenceReader._validate_source_pin_maps(self, entry)
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
                        or raw["parent"] != lineage._root_pin(self._workspace / "evolution")
                        or entry["snapshots"]["archive-before"]["size"] != 0
                        or entry["snapshots"]["archive-before"]["sha256"] != lineage._sha(b"")):
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


def reserved_published_materials(owner, entry):
    """Read original published manifest files and its retained native inventory."""
    return read_reserved_published_materials(owner._workspace, entry)


def read_reserved_published_materials(workspace, entry):
    """Read a published inventory without constructing or accepting an owner."""
    return _read_reserved_success_materials(workspace, entry, published=True)


def _read_reserved_success_materials(workspace, entry, *, published):
    """Preserve real native modes and inode pins for staged or published material."""
    from .producer_bundle_admission import parse_producer_bundle_admission_plan
    from .producer_bundle_receipts import _retained_entry, verify_native_retained_evidence

    workspace = recovery._workspace(workspace)
    batch = recovery._batch(workspace, entry["journal_id"])
    staged = recovery._read_journal(batch / "journal.staged.json")
    journal = recovery._read_journal(batch / "journal.published.json") if published else staged
    plan = parse_producer_bundle_admission_plan(entry["admission_plan"])
    preflight = recovery._read_json(batch / "preflight.json", 128 * 1024)
    preflight_sha = recovery._check_preflight(preflight, staged, plan)
    manifest = recovery._read_json(batch / "manifest.json", 256 * 1024)
    manifest_sha, _ids, _paths, files = recovery._manifest(manifest, staged, preflight_sha)
    if ((published and journal.to_dict() != entry["published_journal"])
            or manifest_sha != entry["staged"]["manifest_sha256"]):
        _fail("published_material_association_drift")
    recovery._verify_manifest_files(workspace, batch, files, journal)
    result = {}
    for candidate_id, material in files.items():
        staged_root = batch / "stage/candidates" / candidate_id
        root = (recovery._path(workspace, f"stage/candidates/{candidate_id}", directory=batch)
                if staged_root.exists() else recovery._path(workspace, f"evolution/candidates/{candidate_id}"))
        for descriptor in material["paths"]:
            relative = descriptor["path"].removeprefix(f"stage/candidates/{candidate_id}/")
            path = recovery._path(workspace, relative, directory=root)
            actual = _retained_entry(path, workspace)
            if (actual["size"] != descriptor["size"] or actual["sha256"] != descriptor["sha256"]
                    or any(name not in descriptor or actual[name] != descriptor[name]
                           for name in ("device", "inode", "mtime_ns", "ctime_ns"))):
                _fail("published_material_pin_drift")
            result[actual["path"]] = {key: value for key, value in actual.items() if key != "path"}
        retained = material.get("retained_evidence")
        if retained is None:
            _fail("published_native_inventory_missing")
        path = recovery._path(workspace, retained["path"], directory=root)
        table = verify_native_retained_evidence(workspace, recovery._read_json(path, 64 * 1024))
        for item in table["entries"]:
            if item["kind"] != "file":
                continue
            record = {key: value for key, value in item.items() if key != "path"}
            if item["path"] in result and result[item["path"]] != record:
                _fail("published_material_alias_drift")
            result[item["path"]] = record
    recovery._verify_manifest_files(workspace, batch, files, journal)
    return result


def initialize_reserved_owner(self, controller, wave, *, request, memory, native_plan, reserved):
    from threading import get_ident

    from .rsi_brs_publication_lineage import (
        _PROTOCOL,
        _BRSLineageCheckpointOwner,
        _native_snapshot,
        _policy,
    )
    from .rsi_controller import RSILearningController, _PythonAdmissionBRSWave
    from .rsi_native_plan import NativeRSIExecutionPlan
    from .rsi_python_admission import validate_rsi_python_admission_shapes
    from .rsi_python_brs_handoff import BRSChildHandoffContext, BRSSelectedChildHandoff
    from .rsi_python_scheduler_inputs import _request_memory
    from .rsi_store import RSILedger

    if (type(self) is not _BRSLineageCheckpointOwner or type(controller) is not RSILearningController
            or type(wave) is not _PythonAdmissionBRSWave or type(controller.ledger) is not RSILedger):
        _fail("owner_invalid")
    controller._python_admission_assert_brs_wave(wave, owner=True)
    handoff, context = wave.selected_handoff, wave.selected_context
    if type(handoff) is not BRSSelectedChildHandoff or type(context) is not BRSChildHandoffContext:
        _fail("selection_required")
    controller._python_admission_selected_brs_identity(wave, handoff)
    parsed_request, parsed_memory = _request_memory(request, memory)
    validate_rsi_python_admission_shapes(native_plan, dto_types=(NativeRSIExecutionPlan, SolverRequest))
    if type(native_plan) is not NativeRSIExecutionPlan:
        _fail("plan_invalid")
    plan = NativeRSIExecutionPlan.from_dict(NativeRSIExecutionPlan.to_dict(native_plan))
    self._ordinal = 0
    self._reserved_prefix = self._reserved_lineage_bytes = self._reserved_original_checkpoint = None
    self._reserved_capture_bytes = None
    self._reserved_scope = self._reserved_gateway = None
    if reserved is not None:
        original_checkpoint, prefix, prefix_batches = reserved
        observed, observed_batches = read_reserved_brs_prefix(
            controller.ledger, wave.workspace, original_checkpoint=original_checkpoint,
            expected_checkpoint_sha256=wave.checkpoint_sha256)
        domain = strict_json(observed.domain_bytes, maximum=112 * 1024)
        domain["episode_ids"], domain["request_sha256s"] = tuple(domain["episode_ids"]), tuple(domain["request_sha256s"])
        supplied = validate_brs_reserved_prefix(**domain, batches=prefix_batches)
        if (type(prefix) is not type(observed) or type(prefix.canonical_bytes) is not bytes
                or type(prefix.domain_bytes) is not bytes or type(prefix.batch_bytes) is not tuple
                or any(type(item) is not bytes for item in prefix.batch_bytes)
                or prefix != observed or supplied != observed or type(prefix_batches) is not tuple
                or prefix_batches != observed_batches or handoff.ordinal != len(observed.batch_bytes)
                or wave.state.get(_FIELD) is not None and len(wave.state[_FIELD]["batches"]) != handoff.ordinal
                or handoff.episode_id != domain["episode_ids"][handoff.ordinal]
                or handoff.request_sha256 != domain["request_sha256s"][handoff.ordinal]
                or handoff.root_snapshot_sha256 != domain["root_snapshot_sha256"]):
            _fail("reserved_prefix_invalid")
        from .rsi_brs_serial_driver import _BRSReservedChildScope
        from .rsi_producer_gateway import PythonProducerRSISolverGateway

        scope = wave.reserved_scope
        if (type(scope) is not _BRSReservedChildScope
                or type(scope.gateway) is not PythonProducerRSISolverGateway
                or type(scope.request) is not SolverRequest or type(scope.memory) is not MemorySnapshot
                or type(scope.preview_plan) is not NativeRSIExecutionPlan
                or scope.request != parsed_request or scope.memory != parsed_memory
                or scope.preview_plan != plan or scope.owner_thread != get_ident()):
            _fail("reserved_scope_drift")
        self._reserved_scope, self._reserved_gateway = scope, scope.gateway
        self._ordinal, self._reserved_prefix = handoff.ordinal, observed
        self._reserved_original_checkpoint = original_checkpoint
        self._reserved_capture_bytes = observed.canonical_bytes
        self._reserved_lineage_bytes = (None if wave.state.get(_FIELD) is None else
                                         canonical_json(wave.state[_FIELD], maximum=128 * 1024))
    if (plan.request != parsed_request or plan.memory_snapshot_sha256 != parsed_memory.digest()
            or parsed_request.digest() != handoff.request_sha256 or plan.run_id != wave.run_id
            or parsed_memory.digest() != handoff.root_snapshot_sha256
            or reserved is None and handoff.ordinal != 0):
        _fail("inputs_invalid")
    previous = getattr(controller._python_admission_brs_local, "lineage_checkpoint_owner", None)
    if type(previous) is _BRSLineageCheckpointOwner and previous._wave is wave:
        _fail("owner_already_created")
    self._controller, self._wave, self._state = controller, wave, wave.state
    self._ledger, self._gateway = controller.ledger, controller.gateway
    self._workspace, self._sidecar, self._thread = wave.workspace, wave.sidecar, get_ident()
    self._root_sidecar = wave.sidecar
    self._channel, self._handoff, self._selected_context = wave.channel, handoff, context
    self._before_channel_condition = self._channel._condition
    self._budget_bytes = controller._python_admission_flow_payload(wave.budget_state)
    self._handoff_bytes = BRSSelectedChildHandoff.canonical_bytes.fget(handoff)
    self._selected_context_bytes = canonical_json(BRSChildHandoffContext.to_dict(context))
    self._provided_request, self._provided_memory, self._provided_plan = request, memory, native_plan
    self._request, self._memory, self._plan = parsed_request, parsed_memory, plan
    self._run_id, self._head, self._payload = plan.run_id, wave.checkpoint_sha256, wave.payload
    self._policy_bytes = lineage._raw(_policy())
    with self._ledger.read_only_observations():
        original = self._ledger.history(self._run_id)[0]
        run = self._ledger.get_run(self._run_id)
        claim = self._ledger.inspect_native_episode_claim(parsed_request, plan_sha256=plan.plan_sha256)
        episode = self._ledger.get_episode(parsed_request.episode_id)
        result = self._ledger.episode_result(parsed_request.episode_id)
    if (run is None or run.state != "running" or episode is None or episode.state != "running"
            or claim is None or claim.status != "started" or result is not None
            or episode.request_sha256 != parsed_request.digest()):
        _fail("running_claim_required")
    self._run_head, self._claim, self._episode_head = run.record_sha256, claim, episode.record_sha256
    self._association = {
        "protocol": _PROTOCOL, "run_id": self._run_id, "workspace": lineage._root_pin(self._workspace),
        "run_request_sha256": original.request_sha256,
        "root_proof_sha256": lineage._sha(lineage._raw(original.payload.get("producer_checkpoint_binding"))),
        "policy_sha256": lineage._sha(self._policy_bytes), "max_batches": MAX_LINEAGE_BATCHES,
    }
    native_gateway = self._gateway if reserved is None else self._reserved_gateway
    config = getattr(native_gateway, "producer_config", None)
    self._native_config = config
    self._native_inputs = self._native = self._strategy = None
    self._strategy_context = self._strategy_config = self._strategy_authority = None
    self._strategy_archive = self._strategy_contract = None
    self._strategy_bytes = None
    if config is not None:
        from .evolution import (
            CandidateIntegrityAuthority,
            EvolutionConfig,
            EvolutionContext,
            PopulationStrategy,
        )
        from .rsi_native_scheduler import NativeRSISchedulerContext
        from .rsi_producer_gateway import PythonProducerRSIExecutionConfig
        from .rsi_python_scheduler_inputs import PythonRSISchedulerInputContext

        if (type(config) is not PythonProducerRSIExecutionConfig or config.ledger is not self._ledger
                or type(config.inputs) is not PythonRSISchedulerInputContext
                or type(config.inputs.native_context) is not NativeRSISchedulerContext
                or type(config.inputs.native_context.strategy) is not PopulationStrategy):
            _fail("native_strategy_invalid")
        self._native_inputs, self._native = config.inputs, config.inputs.native_context
        if reserved is not None:
            from .rsi_python_scheduler_inputs import _context
            _native_copy, self._sidecar = _context(self._native_inputs)
        self._strategy = self._native.strategy
        self._strategy_context, self._strategy_config = self._strategy.context, self._strategy.config
        self._strategy_authority = self._strategy.integrity_authority
        if (type(self._strategy_context) is not EvolutionContext
                or type(self._strategy_config) is not EvolutionConfig
                or type(self._strategy_authority) is not CandidateIntegrityAuthority):
            _fail("native_strategy_invalid")
        self._strategy_archive, self._strategy_contract = self._strategy.archive, self._strategy_context.contract
        self._strategy_bytes = _native_snapshot(
            self._strategy_config, self._strategy_authority, self._strategy_contract,
        )
    self._phase, self._poisoned, self._prepared, self._before_bytes = "new", False, None, None
    self._reconcile_registration_started = False
    self._mailbox_binding_bytes = None
    self._mailbox_capture_started = False
    self._mailbox_history_bytes = b"[]"
    self._validated_before, self._retaining_before, self._retaining_success = None, False, None
    self._success_deadline = None
    self._retaining_rejection, self._rejection_deadline, self._rejection_file_pin = False, None, None
    self._rejection_c1_capture = self._rejection_provenance_c2_capture = None
    self._retaining_rejection_provenance = False
    self._rejection_provenance_deadline = self._rejection_provenance_file_pin = None
    self._rejection_provenance_evidence = self._rejection_provenance_sha256 = None
    self._rejection_ready_capture_started, self._rejection_ready_capture = False, None
    self._rejection_ready_state, self._rejection_ready_stage = "unused", None
    self._rejection_ready_ack, self._rejection_ready_ack_fields = None, None
    self._rejection_ready_commit_started, self._rejection_ready_final_capture = False, None
    self._rejection_ready_locks_capture = None
    self._rejection_ready_sync_capture = None
    from .rsi_native_scheduler import _read_ledger_identity
    self._rejection_ledger_identity = (None if self._native is None else
                                       lineage._raw(_read_ledger_identity(self._ledger)))
    self._before_control = None if self._native is None else self._native.execution_control
    self._before_cancelled = None if self._native is None else self._native.cancelled
    self._before_control_pin = self._before_control_state()
    self._check_owner(registered=False)
    if self._reserved_prefix is None and self._state.get(_FIELD) is not None:
        _fail("fresh_lineage_required")
    controller._python_admission_brs_local.lineage_checkpoint_owner = self


def reserved_strategy_scope(owner):
    """Keep the root gateway fixed while pinning the actual private child context."""
    if owner._reserved_prefix is None:
        if owner._reserved_scope is not None or owner._reserved_gateway is not None:
            _fail("reserved_scope_drift")
        return owner._gateway
    from .rsi_brs_serial_driver import _BRSReservedChildScope
    from .rsi_native_plan import NativeRSIExecutionPlan
    from .rsi_producer_gateway import PythonProducerRSISolverGateway

    scope = owner._reserved_scope
    if (owner._wave.sidecar is not owner._root_sidecar
            or owner._controller.producer_sidecar is not owner._root_sidecar):
        _fail("reserved_scope_drift")
    if (type(scope) is not _BRSReservedChildScope or owner._wave.reserved_scope is not scope
            or type(owner._reserved_gateway) is not PythonProducerRSISolverGateway
            or type(scope.request) is not SolverRequest or type(scope.memory) is not MemorySnapshot
            or type(scope.preview_plan) is not NativeRSIExecutionPlan
            or type(scope.owner_thread) is not int
            or scope.gateway is not owner._reserved_gateway or scope.request != owner._request
            or scope.memory != owner._memory or scope.preview_plan != owner._plan
            or scope.owner_thread != owner._thread):
        _fail("reserved_scope_drift")
    return owner._reserved_gateway


def reserved_retained_bytes(owner, wire, state):
    """Bound prefix metadata, P, native files and active success before new creates.

    New active descriptor/snapshot pins can be capacity placeholders. Their sizes
    are counted as new paths, never accepted as physical identity observations.
    Every settled prefix observation remains a genuine independent physical read.
    """
    if owner._reserved_prefix is None:
        return lineage.RSIPublicationLineage._retained_bytes(wire, state)
    from .producer_bundle_lineage import MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES
    from .rsi_brs_rejection_capacity import _add_material, _pin_record
    from .rsi_brs_rejection_owner import read_reserved_brs_material_inventory
    from .rsi_producer_staging_capsule import READY_CAPSULE_PROTOCOL, retained_ready_capsule_bytes

    reserved_prefix_identity(owner)
    retained_ready_capsule_bytes(state)
    # Reobserve the entire real prefix around its filesystem inventory.
    expected_head = _retained_observation_head(owner)
    prefix, batches = read_reserved_brs_prefix(owner._ledger, owner._workspace,
        original_checkpoint=owner._reserved_original_checkpoint, expected_checkpoint_sha256=expected_head)
    if prefix != owner._reserved_prefix:
        _fail("prefix_drift")
    old_wire = None if owner._reserved_lineage_bytes is None else json.loads(owner._reserved_lineage_bytes)
    observations, _episode_materials = read_reserved_brs_material_inventory(
        owner._workspace, old_wire, prefix_batches=batches)
    materials, identities, total = {}, {}, 0
    for path, record in observations:
        total += _add_material(materials, identities, path, record)
    for staging in state.get("producer_episode_staging", {}).values():
        ready = staging.get("ready")
        if type(ready) is dict and ready.get("protocol") == READY_CAPSULE_PROTOCOL:
            path = "evolution/producer-batches/" + ready["journal_id"] + "/lineage/rsi-ready.snapshot"
            total += _add_material(materials, identities, path,
                                   _pin_record(ready["file_pin"], name="rsi-ready.snapshot"))
    if type(wire) is not dict or type(wire.get("batches")) is not list:
        _fail("capacity_wire_invalid")
    if len(wire["batches"]) == owner._ordinal + 1:
        reserved_wire_scope(owner, wire)
        active = wire["batches"][owner._ordinal]
        base = "evolution/producer-batches/" + active["journal_id"] + "/"
        pending = {}
        for name, raw in active["snapshots"].items():
            pending[base + "lineage/" + name + ".snapshot"] = raw["size"]
        for kind in ("before", "staged", "terminal"):
            if kind + "_file_pin" in active:
                name = "before-v2.json" if kind == "before" and owner._ordinal else kind + ".json"
                pending[base + "lineage/" + name] = active[kind + "_file_pin"]["size"]
        # Once the active batch has reached staged/terminal, the retained native
        # reader below observes these evidence files physically and adds their
        # exact pins.  Keep them as placeholders only before that material is
        # present; counting the same journal.prepared.json (and then rejecting
        # its intentional overlap) would make a valid published child fail the
        # capacity gate.
        if active["state"] not in {"staged", "terminal"}:
            for name, raw in active["evidence_pins"].items():
                pending[base + name] = raw["size"]
        for path, size in pending.items():
            if type(size) is not int or size < 0 or path in materials:
                _fail("capacity_material_invalid")
            total += size
        if active["state"] in {"staged", "terminal"}:
            for path, record in _read_reserved_success_materials(owner._workspace, active,
                    published=active["state"] == "terminal").items():
                if path in pending:
                    _fail("capacity_material_alias")
                total += _add_material(materials, identities, path, record)
    elif (len(wire["batches"]) != owner._ordinal
            or canonical_json(wire, maximum=128 * 1024) !=
               (owner._reserved_lineage_bytes or canonical_json(wire, maximum=128 * 1024))):
        _fail("capacity_wire_invalid")
    if total > MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES:
        _fail("capacity_exceeded")
    again, again_batches = read_reserved_brs_prefix(owner._ledger, owner._workspace,
        original_checkpoint=owner._reserved_original_checkpoint, expected_checkpoint_sha256=expected_head)
    if again != prefix or again_batches != batches:
        _fail("observation_changed")
    return total
