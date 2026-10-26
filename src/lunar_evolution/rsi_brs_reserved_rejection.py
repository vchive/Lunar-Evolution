"""Pure private C1/C2 comparisons over an original reserved-wave prefix.

These comparisons neither observe files nor authorize an owner. The caller must
independently retain and reobserve all original root, native and material sources.
Legacy first-ordinal C1/C2 readers retain their existing strict contract.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import fields

from .candidate_evaluation_spec import canonical_json, strict_json
from .producer_bundle_lineage import (
    MAX_LINEAGE_BATCHES,
    MAX_LINEAGE_DESCRIPTOR_BYTES,
    LineageSnapshotPin,
    ProducerLineageBeforeIntent,
    ProducerLineageTerminal,
)
from .producer_bundle_lineage_v2 import (
    ProducerLineageBeforeIntentV2,
    ProducerLineageRejectedTerminalV2,
)
from .producer_bundle_publication import parse_producer_bundle_publication_journal
from .rsi_brs_lineage_prefix import MAX_BRS_PREFIX_BYTES, BRSLineagePrefix
from .rsi_brs_rejection_c1 import (
    _BASE_FIELDS,
    _BRS_PROTOCOL,
    _PROVENANCE_FIELDS,
    _REJECTED_FIELDS,
    REJECTION_SCHEMA,
)
from .rsi_learning import RSILearningError
from .rsi_native_rejection import NativeRSIRejectionFilePin

MAX_RESERVED_REJECTION_BYTES = 128 * 1024
_SHA = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_ASSOCIATION_FIELDS = frozenset({"protocol", "run_id", "workspace", "run_request_sha256",
                                "root_proof_sha256", "policy_sha256", "max_batches"})
_PUBLISHED_FIELDS = _BASE_FIELDS | frozenset({"staged", "staged_file_pin", "state_projection_sha256",
                                           "after_sources", "terminal", "terminal_file_pin",
                                           "published_journal", "head_sources"})
_PREFIX_FIELDS = frozenset({"domain", "batches", "tail_checkpoint_sha256", "previous_attempt",
                          "published_predecessor", "historical_poststate", "candidate_count", "retained_material_bytes"})
_DOMAIN_FIELDS = frozenset({"run_id", "wave", "episode_ids", "request_sha256s", "root_snapshot_sha256",
                          "base_checkpoint_sha256"})


def _fail(code):
    raise RSILearningError("rsi_brs_reserved_rejection_" + code)


def _plain(value, depth=0, remaining=None):
    if remaining is None:
        remaining = [32768]
    remaining[0] -= 1
    if depth > 32 or remaining[0] < 0:
        _fail("shape_invalid")
    kind = type(value)
    if value is None or kind is bool or (kind is int and value.bit_length() <= 128):
        return
    if kind is float and math.isfinite(value):
        return
    if kind is str and len(value) <= MAX_RESERVED_REJECTION_BYTES:
        return
    if kind is dict and len(value) <= 512 and all(type(key) is str for key in value):
        for item in value.values():
            _plain(item, depth + 1, remaining)
        return
    if kind is list and len(value) <= 512:
        for item in value:
            _plain(item, depth + 1, remaining)
        return
    _fail("shape_invalid")


def _raw(value, maximum=MAX_RESERVED_REJECTION_BYTES):
    _plain(value)
    try:
        return canonical_json(value, maximum=maximum)
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise RSILearningError("rsi_brs_reserved_rejection_capacity_or_encoding_invalid") from exc


def _decode(value, maximum=MAX_RESERVED_REJECTION_BYTES):
    if type(value) is not bytes or len(value) > maximum:
        _fail("bytes_invalid")
    try:
        decoded = strict_json(value, maximum=maximum)
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise RSILearningError("rsi_brs_reserved_rejection_bytes_invalid") from exc
    if _raw(decoded, maximum) != value:
        _fail("noncanonical_bytes")
    return decoded


def _sha(value):
    if type(value) is not str or _SHA.fullmatch(value) is None:
        _fail("digest_invalid")
    return value


def _pin(value):
    _plain(value)
    if type(value) is not dict or set(value) != {field.name for field in fields(LineageSnapshotPin)}:
        _fail("pin_invalid")
    return LineageSnapshotPin.from_dict(value)


def _descriptor(body, pin, cls):
    _raw(body, MAX_LINEAGE_DESCRIPTOR_BYTES)
    parsed, held = cls.from_dict(body), _pin(pin)
    raw = parsed.to_json()
    if (held.name != parsed.kind + ".json" or held.size != len(raw)
            or held.sha256 != hashlib.sha256(raw).hexdigest()):
        _fail("descriptor_pin_drift")
    return parsed


def _prefix(prefix):
    """Detach bounded facts before any comparison; this does not authenticate them."""
    if (type(prefix) is not BRSLineagePrefix or type(prefix.domain_bytes) is not bytes
            or type(prefix.canonical_bytes) is not bytes or type(prefix.batch_bytes) is not tuple
            or len(prefix.batch_bytes) >= MAX_LINEAGE_BATCHES
            or any(type(item) is not bytes or len(item) > MAX_BRS_PREFIX_BYTES for item in prefix.batch_bytes)):
        _fail("prefix_invalid")
    domain = _decode(prefix.domain_bytes, MAX_BRS_PREFIX_BYTES)
    projection = _decode(prefix.canonical_bytes, MAX_BRS_PREFIX_BYTES)
    if (type(domain) is not dict or set(domain) != _DOMAIN_FIELDS
            or type(projection) is not dict or set(projection) != _PREFIX_FIELDS
            or projection["domain"] != domain or type(projection["batches"]) is not list
            or type(domain["run_id"]) is not str or _ID.fullmatch(domain["run_id"]) is None
            or type(domain["wave"]) is not int or not 0 <= domain["wave"] < 2**64
            or type(domain["episode_ids"]) is not list or type(domain["request_sha256s"]) is not list
            or not 1 <= len(domain["episode_ids"]) <= MAX_LINEAGE_BATCHES
            or len(domain["episode_ids"]) != len(domain["request_sha256s"])
            or len(prefix.batch_bytes) >= len(domain["episode_ids"])
            or len(projection["batches"]) != len(prefix.batch_bytes)):
        _fail("prefix_invalid")
    _sha(domain["root_snapshot_sha256"])
    _sha(domain["base_checkpoint_sha256"])
    for ordinal, (episode, request) in enumerate(zip(domain["episode_ids"], domain["request_sha256s"], strict=True)):
        if type(episode) is not str or episode != f"{domain['run_id']}-practice-{domain['wave']}-{ordinal}":
            _fail("prefix_invalid")
        _sha(request)
    previous = published = poststate = None
    candidates, journals, index = set(), set(), []
    for ordinal, (raw, observed) in enumerate(zip(prefix.batch_bytes, projection["batches"], strict=True)):
        item = _decode(raw, MAX_BRS_PREFIX_BYTES)
        if (type(item) is not dict or item != observed or type(item.get("ordinal")) is not int
                or item["ordinal"] != ordinal or item.get("episode_id") != domain["episode_ids"][ordinal]
                or item.get("request_sha256") != domain["request_sha256s"][ordinal]
                or item.get("outcome") not in {"published", "all_rejected"}):
            _fail("prefix_invalid")
        before = item["before"]
        before = _descriptor(before["descriptor"], before["file_pin"],
                             ProducerLineageBeforeIntent if ordinal == 0 else ProducerLineageBeforeIntentV2)
        terminal = item["terminal"]
        terminal = _descriptor(terminal["descriptor"], terminal["file_pin"],
                               ProducerLineageTerminal if item["outcome"] == "published" else ProducerLineageRejectedTerminalV2)
        if (before.run_id != domain["run_id"] or terminal.run_id != domain["run_id"]
                or before.ordinal != ordinal or terminal.ordinal != ordinal
                or before.journal_id != terminal.journal_id or terminal.journal_id in journals):
            _fail("prefix_invalid")
        journals.add(terminal.journal_id)
        if ordinal:
            _predecessors(before, previous, published)
        if candidates.intersection(getattr(terminal, "candidate_ids", ())):
            _fail("prefix_invalid")
        ids = (item["staged"]["descriptor"]["candidate_ids"] if item["outcome"] == "published"
               else list(terminal.candidate_ids))
        if type(ids) is not list or any(type(cid) is not str for cid in ids) or candidates.intersection(ids):
            _fail("prefix_invalid")
        candidates.update(ids)
        marker = terminal.terminal_sha256 if item["outcome"] == "published" else terminal.terminal_marker_sha256
        previous = [terminal.journal_id, item["outcome"], marker, terminal.digest()]
        if item["outcome"] == "published":
            published = [terminal.journal_id, marker, terminal.digest()]
        else:
            index.append({"ordinal": ordinal, "journal_id": terminal.journal_id, "rejected_sha256": terminal.digest()})
        suffix = "after" if item["outcome"] == "published" else "before"
        poststate = [[_pin(item["snapshots"][name + "-" + suffix]).sha256,
                      _pin(item["snapshots"][name + "-" + suffix]).size] for name in ("archive", "state")]
    if (projection["previous_attempt"] != previous or projection["published_predecessor"] != published
            or projection["historical_poststate"] != poststate
            or type(projection["candidate_count"]) is not int or projection["candidate_count"] != len(candidates)
            or len(candidates) > 32):
        _fail("prefix_invalid")
    return domain, projection, journals, candidates, index


def _predecessors(before, previous, published):
    attempted = [before.previous_attempt_journal_id, before.previous_attempt_outcome,
                 before.previous_attempt_terminal_sha256, before.previous_attempt_lineage_sha256]
    latest = [before.published_predecessor_journal_id, before.published_predecessor_terminal_sha256,
              before.published_predecessor_lineage_sha256]
    if attempted != previous or latest != (published if published is not None else [None, None, None]):
        _fail("predecessor_drift")


def _entry(entry, prefix, plan, with_provenance):
    return _entry_from_prefix(entry, _prefix(prefix), plan, with_provenance)


def _entry_from_prefix(entry, parsed_prefix, plan, with_provenance):
    domain, projection, journals, candidates, _index = parsed_prefix
    ordinal = len(projection["batches"])
    _sha(plan)
    _raw(entry)
    if (type(with_provenance) is not bool or type(entry) is not dict
            or set(entry) != _BASE_FIELDS | _REJECTED_FIELDS
            or entry.get("state") != "rejected" or entry.get("rejection_schema") != REJECTION_SCHEMA
            or type(entry.get("ordinal")) is not int or entry["ordinal"] != ordinal
            or entry.get("episode_id") != domain["episode_ids"][ordinal]
            or entry.get("request_sha256") != domain["request_sha256s"][ordinal]
            or entry.get("memory_snapshot_sha256") != domain["root_snapshot_sha256"]
            or entry.get("native_plan_sha256") != plan
            or type(entry.get("snapshots")) is not dict
            or set(entry["snapshots"]) != {"archive-before", "state-before"}
            or type(entry.get("prepared_journal")) is not dict or type(entry.get("rejected_journal")) is not dict
            or type(entry.get("evidence_pins")) is not dict):
        _fail("entry_invalid")
    reference = entry["rejection_provenance"]
    if with_provenance:
        if type(reference) is not dict or set(reference) != _PROVENANCE_FIELDS:
            _fail("provenance_invalid")
        _sha(reference["provenance_sha256"])
        NativeRSIRejectionFilePin.from_dict(reference["file_pin"])
    elif reference is not None:
        _fail("provenance_invalid")
    before = _descriptor(entry["before"], entry["before_file_pin"],
                         ProducerLineageBeforeIntent if ordinal == 0 else ProducerLineageBeforeIntentV2)
    rejected = _descriptor(entry["rejected"], entry["rejected_file_pin"], ProducerLineageRejectedTerminalV2)
    prepared = parse_producer_bundle_publication_journal(entry["prepared_journal"])
    terminal = parse_producer_bundle_publication_journal(entry["rejected_journal"])
    if (prepared.state != "prepared" or terminal.state != "all_rejected"
            or (rejected.run_id, rejected.journal_id, rejected.episode_id, rejected.ordinal) !=
                (domain["run_id"], entry["journal_id"], domain["episode_ids"][ordinal], ordinal)
            or entry["journal_id"] in journals
            or (prepared.run_id, prepared.journal_id, prepared.task_id) !=
                (rejected.run_id, rejected.journal_id, rejected.episode_id)
            or (terminal.run_id, terminal.journal_id, terminal.task_id) !=
                (prepared.run_id, prepared.journal_id, prepared.task_id)
            or (before.run_id, before.journal_id, before.ordinal) !=
                (rejected.run_id, rejected.journal_id, ordinal)
            or rejected.before_sha256 != before.digest()
            or rejected.prepared_journal_sha256 != prepared.digest()
            or rejected.terminal_journal_sha256 != terminal.digest()
            or rejected.terminal_marker_sha256 != terminal.terminal_marker_sha256
            or rejected.candidate_ids != tuple(item.candidate_id for item in prepared.candidates)
            or rejected.candidate_ids != tuple(item.candidate_id for item in terminal.candidates)
            or candidates.intersection(rejected.candidate_ids) or len(candidates) + len(rejected.candidate_ids) > 32
            or (rejected.archive_sha256, rejected.state_sha256) != (before.archive.sha256, before.state.sha256)
            or (prepared.base_archive_sha256, prepared.base_state_sha256) != (before.archive.sha256, before.state.sha256)
            or (terminal.archive_after_sha256, terminal.state_after_sha256) != (before.archive.sha256, before.state.sha256)):
        _fail("association_drift")
    if ordinal:
        _predecessors(before, projection["previous_attempt"], projection["published_predecessor"])
    elif before.predecessor_terminal_sha256 is not None or before.predecessor_lineage_sha256 is not None:
        _fail("predecessor_drift")
    snapshots = [_pin(entry["snapshots"][name + "-before"]) for name in ("archive", "state")]
    if (before.archive != snapshots[0] or before.state != snapshots[1]
            or any(pin.name != name + "-before.snapshot" for name, pin in zip(("archive", "state"), snapshots, strict=True))
            or (ordinal and [[pin.sha256, pin.size] for pin in snapshots] != projection["historical_poststate"])):
        _fail("snapshot_drift")
    names = {"journal.prepared.json", "journal.json", "rejections.json",
             *("rejections/" + candidate for candidate in rejected.candidate_ids)}
    names = {name + ".json" if name.startswith("rejections/") else name for name in names}
    if set(entry["evidence_pins"]) != names:
        _fail("pins_invalid")
    for name, pin in entry["evidence_pins"].items():
        expected = "rejection-" + hashlib.sha256(name.encode()).hexdigest() if name.startswith("rejections/") else name
        if _pin(pin).name != expected:
            _fail("pins_invalid")
    return rejected


def validate_reserved_brs_rejected_entry(entry, *, prefix: BRSLineagePrefix, native_plan_sha256: str,
                                         with_provenance: bool = False) -> ProducerLineageRejectedTerminalV2:
    """Compare the actual selected ordinal; P is parsed only, never authenticated."""
    try:
        return _entry(entry, prefix, native_plan_sha256, with_provenance)
    except RSILearningError:
        raise
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
        raise RSILearningError("rsi_brs_reserved_rejection_entry_invalid") from exc


def _wire(value, domain, count):
    _raw(value)
    if (type(value) is not dict or set(value) != _ASSOCIATION_FIELDS | {"batches", "head", "rejections"}
            or value["protocol"] != _BRS_PROTOCOL or value["run_id"] != domain["run_id"]
            or type(value["max_batches"]) is not int or value["max_batches"] != MAX_LINEAGE_BATCHES
            or type(value["batches"]) is not list or len(value["batches"]) != count
            or type(value["rejections"]) is not list):
        _fail("wire_invalid")
    for name in ("run_request_sha256", "root_proof_sha256", "policy_sha256"):
        _sha(value[name])
    workspace = value["workspace"]
    if (type(workspace) is not dict or set(workspace) != {"path", "device", "inode"}
            or type(workspace["path"]) is not str or not workspace["path"]
            or type(workspace["device"]) is not int or not 0 <= workspace["device"] < 2**64
            or type(workspace["inode"]) is not int or not 0 < workspace["inode"] < 2**64):
        _fail("wire_invalid")
    return value


def _transition_scope(previous, current, prefix, original_lineage_bytes):
    return _transition_scope_from_prefix(previous, current, _prefix(prefix), original_lineage_bytes)


def _transition_scope_from_prefix(previous, current, parsed_prefix, original_lineage_bytes):
    domain, facts, _journals, _candidates, index = parsed_prefix
    count = len(facts["batches"])
    previous, current = _wire(previous, domain, count + 1), _wire(current, domain, count + 1)
    published = facts["published_predecessor"]
    head = (dict(zip(("journal_id", "terminal_sha256", "lineage_sha256"), published, strict=True))
            if published is not None else None)
    if previous["head"] != head or current["head"] != head:
        _fail("head_drift")
    if any(previous[key] != current[key] for key in _ASSOCIATION_FIELDS):
        _fail("association_drift")
    if count == 0:
        if original_lineage_bytes is not None:
            _fail("original_prefix_invalid")
        return previous["batches"][0], current["batches"][0], index
    original = _wire(_decode(original_lineage_bytes), domain, count)
    if (original["head"] != head or original["rejections"] != index
            or any(original[key] != current[key] for key in _ASSOCIATION_FIELDS)
            or _raw(previous["batches"][:count]) != _raw(original["batches"])
            or _raw(current["batches"][:count]) != _raw(original["batches"])):
        _fail("original_prefix_drift")
    for actual, observed in zip(original["batches"], facts["batches"], strict=True):
        outcome = observed["outcome"]
        kind = "terminal" if outcome == "published" else "rejected"
        if (type(actual) is not dict or set(actual) != (_PUBLISHED_FIELDS if outcome == "published"
                                                      else _BASE_FIELDS | _REJECTED_FIELDS)
                or any(actual.get(key) != observed.get(key) for key in (
                    "ordinal", "episode_id", "request_sha256", "native_plan_sha256", "snapshots"))
                or actual.get("memory_snapshot_sha256") != domain["root_snapshot_sha256"]
                or actual.get("state") != kind or actual.get("before") != observed["before"]["descriptor"]
                or actual.get("before_file_pin") != observed["before"]["file_pin"]
                or actual.get(kind) != observed["terminal"]["descriptor"]
                or actual.get(kind + "_file_pin") != observed["terminal"]["file_pin"]
                or actual.get("journal_id") != observed["terminal"]["descriptor"]["journal_id"]):
            _fail("original_prefix_drift")
        if outcome == "published":
            if (actual["staged"] != observed["staged"]["descriptor"]
                    or actual["staged_file_pin"] != observed["staged"]["file_pin"]):
                _fail("original_prefix_drift")
        else:
            reference = actual["rejection_provenance"]
            if (actual["rejection_schema"] != REJECTION_SCHEMA or type(reference) is not dict
                    or set(reference) != _PROVENANCE_FIELDS):
                _fail("original_prefix_drift")
            _sha(reference["provenance_sha256"])
            NativeRSIRejectionFilePin.from_dict(reference["file_pin"])
    return previous["batches"][count], current["batches"][count], index


def _validated_entry_from_prefix(entry, parsed_prefix, plan, with_provenance):
    # Keep the standalone entry validator's error boundary when sharing parsed
    # facts inside a transition; parser errors must not become C1/C2 errors.
    try:
        return _entry_from_prefix(entry, parsed_prefix, plan, with_provenance)
    except RSILearningError:
        raise
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
        raise RSILearningError("rsi_brs_reserved_rejection_entry_invalid") from exc


def _transition(previous, current, *, prefix, original_lineage_bytes, native_plan_sha256, c2):
    # All facts are detached by this operation's fresh bounded parser. Reuse
    # only on this stack: standalone entry/scope calls still parse for themselves.
    parsed_prefix = _prefix(prefix)
    before, after, index = _transition_scope_from_prefix(
        previous, current, parsed_prefix, original_lineage_bytes,
    )
    rejected = _validated_entry_from_prefix(after, parsed_prefix, native_plan_sha256, c2)
    expected_index = [*index, {"ordinal": rejected.ordinal, "journal_id": rejected.journal_id,
                             "rejected_sha256": rejected.digest()}]
    if c2:
        _validated_entry_from_prefix(before, parsed_prefix, native_plan_sha256, False)
        if previous["rejections"] != expected_index or current["rejections"] != expected_index:
            _fail("rejection_index_drift")
        if any(after[key] != value for key, value in before.items() if key != "rejection_provenance"):
            _fail("c2_delta_invalid")
    else:
        if (type(before) is not dict or set(before) != _BASE_FIELDS or before.get("state") != "before"
                or type(before.get("evidence_pins")) is not dict
                or set(before["evidence_pins"]) != {"journal.prepared.json"}
                or previous["rejections"] != index or current["rejections"] != expected_index):
            _fail("c1_delta_invalid")
        for key, value in before.items():
            if key == "evidence_pins":
                if after[key]["journal.prepared.json"] != value["journal.prepared.json"]:
                    _fail("c1_delta_invalid")
            elif key != "state" and after[key] != value:
                _fail("c1_delta_invalid")


def validate_reserved_brs_c1_transition(previous, current, *, prefix: BRSLineagePrefix,
                                        original_lineage_bytes: bytes | None, native_plan_sha256: str) -> None:
    """Require exact retained history plus only the selected before-to-C1 delta."""
    try:
        _transition(previous, current, prefix=prefix, original_lineage_bytes=original_lineage_bytes,
                    native_plan_sha256=native_plan_sha256, c2=False)
    except RSILearningError:
        raise
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
        raise RSILearningError("rsi_brs_reserved_rejection_c1_invalid") from exc


def validate_reserved_brs_c2_transition(previous, current, *, prefix: BRSLineagePrefix,
                                        original_lineage_bytes: bytes | None, native_plan_sha256: str) -> None:
    """Require only the selected original null-to-present P reference delta."""
    try:
        _transition(previous, current, prefix=prefix, original_lineage_bytes=original_lineage_bytes,
                    native_plan_sha256=native_plan_sha256, c2=True)
    except RSILearningError:
        raise
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
        raise RSILearningError("rsi_brs_reserved_rejection_c2_invalid") from exc
