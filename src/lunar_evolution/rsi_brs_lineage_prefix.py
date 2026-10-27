"""Pure bounded comparisons for original reserved-wave lineage observations.

All inputs are observations supplied by the original controller's readers. This
module performs no filesystem/ledger observation and grants no live authority.
Historical snapshot content is compared separately from its retained inode pin.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, fields

from .candidate_evaluation_spec import canonical_json, strict_json
from .producer_bundle_lineage import (
    MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES,
    MAX_LINEAGE_BATCHES,
    MAX_LINEAGE_DESCRIPTOR_BYTES,
    LineageSnapshotPin,
    ProducerLineageBeforeIntent,
    ProducerLineageStagedTransition,
    ProducerLineageTerminal,
)
from .producer_bundle_lineage_v2 import (
    ProducerLineageBeforeIntentV2,
    ProducerLineageRejectedTerminalV2,
)
from .rsi_gateway import SolverRequest, SolverResult
from .rsi_learning import (
    MemorySnapshot,
    PracticeEpisode,
    RSILearningError,
    VerifierCheck,
    VerifierDecision,
)

MAX_BRS_PREFIX_BYTES = 112 * 1024
MAX_BRS_ROOT_BYTES = 128 * 1024
MAX_BRS_PREFIX_CANDIDATES = 32
_SHA = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_BATCH_FIELDS = frozenset({
    "ordinal", "episode_id", "request_sha256", "native_plan_sha256", "outcome",
    "execution_bytes", "entry_checkpoint_sha256", "root_checkpoint", "claim",
    "before", "staged", "terminal", "snapshots", "materials",
})
_CLAIM_FIELDS = frozenset({"episode_id", "request_sha256", "plan_sha256", "status", "claim_sha256", "created_at"})


def _fail(code: str) -> None:
    raise RSILearningError("rsi_brs_reserved_prefix_" + code)


def _sha(value: object) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        _fail("digest_invalid")
    return value


def _id(value: object) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        _fail("identity_invalid")
    return value


def _plain(value: object, depth: int = 0, remaining: list[int] | None = None) -> None:
    if remaining is None:
        remaining = [32768]
    remaining[0] -= 1
    if depth > 32 or remaining[0] < 0:
        _fail("shape_invalid")
    kind = type(value)
    if value is None or kind is bool:
        return
    if kind is int and value.bit_length() <= 128:
        return
    if kind is float and math.isfinite(value):
        return
    if kind is str and len(value) <= MAX_BRS_ROOT_BYTES:
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


def _canonical(value: object, maximum: int = MAX_BRS_PREFIX_BYTES) -> bytes:
    _plain(value)
    try:
        return canonical_json(value, maximum=maximum)
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise RSILearningError("rsi_brs_reserved_prefix_capacity_exhausted") from exc


def _digest(value: object, maximum: int = MAX_BRS_PREFIX_BYTES) -> str:
    return hashlib.sha256(_canonical(value, maximum)).hexdigest()


def _pin(raw: object) -> dict:
    _plain(raw)
    if type(raw) is not dict or set(raw) != {field.name for field in fields(LineageSnapshotPin)}:
        _fail("material_pin_invalid")
    try:
        pin = LineageSnapshotPin.from_dict(raw)
    except (TypeError, ValueError) as exc:
        raise RSILearningError("rsi_brs_reserved_prefix_material_pin_invalid") from exc
    return pin.to_dict()


def _descriptor(raw: object, cls: type):
    if type(raw) is not dict or set(raw) != {"descriptor", "file_pin"}:
        _fail("descriptor_invalid")
    _plain(raw)
    body, pin = raw["descriptor"], _pin(raw["file_pin"])
    encoded = _canonical(body, MAX_LINEAGE_DESCRIPTOR_BYTES)
    try:
        parsed = cls.from_dict(body)
    except (TypeError, ValueError) as exc:
        raise RSILearningError("rsi_brs_reserved_prefix_descriptor_invalid") from exc
    if (pin["name"] != parsed.kind + ".json" or pin["sha256"] != hashlib.sha256(encoded).hexdigest()
            or pin["size"] != len(encoded)):
        _fail("descriptor_pin_drift")
    return parsed, {"descriptor": body, "file_pin": pin}


def _execution(raw: object, *, run_id: str, wave: int, ordinal: int,
               episode_id: str, request_sha256: str, memory: str, outcome: str):
    if type(raw) is not bytes or len(raw) > MAX_BRS_ROOT_BYTES:
        _fail("execution_invalid")
    try:
        value = strict_json(raw, maximum=MAX_BRS_ROOT_BYTES)
        _plain(value)
        if type(value) is not dict or set(value) != {"episode", "request", "result", "verifier"}:
            _fail("execution_invalid")
        if _canonical(value, MAX_BRS_ROOT_BYTES) != raw:
            _fail("execution_noncanonical")
        episode = PracticeEpisode.from_dict(value["episode"])
        request, result = SolverRequest.from_dict(value["request"]), SolverResult.from_dict(value["result"])
        wire = value["verifier"]
        if type(wire) is not dict or set(wire) != {field.name for field in fields(VerifierDecision)}:
            _fail("execution_invalid")
        checks = tuple(VerifierCheck(**item) for item in wire["checks"])
        verifier = VerifierDecision(**{**wire, "checks": checks})
        clean = {"episode": episode.to_record_dict(), "request": request.to_dict(),
                 "result": result.to_dict(), "verifier": verifier.to_dict()}
        terminal_status = "completed" if outcome == "published" else "failed"
        if (clean != value or episode.run_id != run_id
                or episode.episode_kind != "practice" or episode.wave != wave or episode.ordinal != ordinal
                or any(item != episode_id for item in (episode.episode_id, request.episode_id,
                                                       result.episode_id, verifier.episode_id))
                or any(item != request_sha256 for item in (request.digest(), episode.request_sha256,
                                                          result.request_sha256))
                or episode.status != terminal_status or result.status != terminal_status
                or request.memory_snapshot_sha256 != memory
                or any(getattr(episode, key) != getattr(request, key) for key in (
                    "contract_sha256", "evaluator_sha256", "environment_sha256", "memory_snapshot_sha256", "solver_id"))
                or (episode.verifier is not None and episode.verifier != verifier)
                or (outcome == "published" and (episode.verifier != verifier or any(
                    getattr(episode, key) != getattr(result, key) for key in (
                        "candidate_receipt_sha256", "execution_receipt_sha256", "official_evaluation_receipt_sha256"))))
                or (outcome == "all_rejected" and verifier.outcome == "pass")
                or any(getattr(episode, key) != getattr(result, key) for key in (
                    "trace_digest", "candidate_source_sha256", "dependency_sha256", "trace_events", "actor_fingerprint"))
                or any(getattr(verifier, key) not in {None, getattr(request, key)} for key in (
                    "contract_sha256", "evaluator_sha256", "environment_sha256"))
                or any(getattr(verifier, key) not in {None, getattr(result, key)} for key in (
                    "candidate_receipt_sha256", "execution_receipt_sha256", "official_evaluation_receipt_sha256"))):
            _fail("execution_association_drift")
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
        raise RSILearningError("rsi_brs_reserved_prefix_execution_invalid") from exc
    return value, terminal_status


def _root(raw, *, run_id, episode_ids, ordinal, execution, memory, prior_executions):
    if type(raw) is not tuple or len(raw) != 2:
        _fail("root_observation_invalid")
    head, state = _sha(raw[0]), raw[1]
    payload = _canonical(state, MAX_BRS_ROOT_BYTES)
    if (type(state) is not dict or state.get("run_id") != run_id or state.get("mode") != "brs"
            or state.get("status") != "running" or state.get("phase") != "evaluated"
            or state.get("current_episode_id") != episode_ids[ordinal]
            or type(state.get("executions")) is not dict
            or set(state["executions"]) != set(episode_ids[:ordinal + 1])
            or any(_canonical(state["executions"][key], MAX_BRS_ROOT_BYTES) != _canonical(value, MAX_BRS_ROOT_BYTES)
                   for key, value in prior_executions.items())
            or _canonical(state["executions"][episode_ids[ordinal]], MAX_BRS_ROOT_BYTES) != _canonical(
                execution, MAX_BRS_ROOT_BYTES)):
        _fail("root_execution_drift")
    try:
        if (MemorySnapshot.from_dict(state["root_snapshot"]).digest() != memory
                or state["intents"][episode_ids[ordinal]]["request"] != execution["request"]):
            _fail("root_execution_drift")
    except (TypeError, ValueError, KeyError) as exc:
        raise RSILearningError("rsi_brs_reserved_prefix_root_execution_drift") from exc
    return head, hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class BRSLineagePrefix:
    """Immutable comparison facts; neither independent evidence nor permission."""

    domain_bytes: bytes
    batch_bytes: tuple[bytes, ...]
    canonical_bytes: bytes

    @property
    def settled_prefix(self) -> tuple[tuple[str, str, str], ...]:
        return tuple((item["episode_id"], item["outcome"], item["execution_sha256"])
                     for item in json.loads(self.canonical_bytes)["batches"])

    @property
    def tail_checkpoint_sha256(self) -> str:
        return json.loads(self.canonical_bytes)["tail_checkpoint_sha256"]

    @property
    def previous_attempt(self) -> tuple[str, str, str, str] | None:
        value = json.loads(self.canonical_bytes)["previous_attempt"]
        return tuple(value) if value is not None else None

    @property
    def published_predecessor(self) -> tuple[str, str, str] | None:
        value = json.loads(self.canonical_bytes)["published_predecessor"]
        return tuple(value) if value is not None else None

    def digest(self) -> str:
        return hashlib.sha256(self.canonical_bytes).hexdigest()


def validate_brs_reserved_prefix(
    *, run_id: str, wave: int, episode_ids: tuple[str, ...], request_sha256s: tuple[str, ...],
    root_snapshot_sha256: str, base_checkpoint_sha256: str, batches: tuple[dict, ...],
) -> BRSLineagePrefix:
    """Compare a whole original domain against a contiguous observed prefix.

    Each batch carries the actual settled root payload and canonical execution
    bytes. Only their computed digests enter the compact historical projection.
    The caller must independently observe and authenticate every original source.
    """
    return _validate_brs_reserved_prefix_walk(
        run_id=run_id, wave=wave, episode_ids=episode_ids, request_sha256s=request_sha256s,
        root_snapshot_sha256=root_snapshot_sha256, base_checkpoint_sha256=base_checkpoint_sha256,
        batches=batches, collect_prefixes=False,
    )[-1]


def _validate_brs_reserved_prefixes(
    *, run_id: str, wave: int, episode_ids: tuple[str, ...], request_sha256s: tuple[str, ...],
    root_snapshot_sha256: str, base_checkpoint_sha256: str, batches: tuple[dict, ...],
) -> tuple[BRSLineagePrefix, ...]:
    """Derive every prefix in one pure walk of the same fresh observations.

    This replaces repeated normalization of slices, not any physical reading or
    owner validation. Each prefix is independently encoded and bounded in its
    original order, including the empty prefix before the first batch.
    """
    return _validate_brs_reserved_prefix_walk(
        run_id=run_id, wave=wave, episode_ids=episode_ids, request_sha256s=request_sha256s,
        root_snapshot_sha256=root_snapshot_sha256, base_checkpoint_sha256=base_checkpoint_sha256,
        batches=batches, collect_prefixes=True,
    )


def _project_brs_reserved_prefix(
    domain, normalized, tail, previous, published, poststate, candidates, total,
) -> BRSLineagePrefix:
    """Encode one complete bounded immutable result, with no retained context."""
    projection = {"domain": domain, "batches": normalized, "tail_checkpoint_sha256": tail,
                  "previous_attempt": list(previous) if previous else None,
                  "published_predecessor": list(published) if published else None,
                  "historical_poststate": [list(item) for item in poststate] if poststate else None,
                  "candidate_count": len(candidates), "retained_material_bytes": total}
    return BRSLineagePrefix(_canonical(domain), tuple(_canonical(item) for item in normalized), _canonical(projection))


def _validate_brs_reserved_prefix_walk(
    *, run_id: str, wave: int, episode_ids: tuple[str, ...], request_sha256s: tuple[str, ...],
    root_snapshot_sha256: str, base_checkpoint_sha256: str, batches: tuple[dict, ...],
    collect_prefixes: bool,
) -> tuple[BRSLineagePrefix, ...]:
    """Normalize the finite observed batch domain once, preserving check order."""
    _id(run_id)
    if type(wave) is not int or not 0 <= wave < 2**64:
        _fail("wave_invalid")
    if (type(episode_ids) is not tuple or type(request_sha256s) is not tuple
            or not 1 <= len(episode_ids) <= MAX_LINEAGE_BATCHES or len(episode_ids) != len(request_sha256s)
            or type(batches) is not tuple or len(batches) > len(episode_ids)):
        _fail("domain_invalid")
    for ordinal, (episode_id, request_digest) in enumerate(zip(episode_ids, request_sha256s, strict=True)):
        if _id(episode_id) != f"{run_id}-practice-{wave}-{ordinal}":
            _fail("domain_invalid")
        _sha(request_digest)
    domain = {"run_id": run_id, "wave": wave, "episode_ids": list(episode_ids),
              "request_sha256s": list(request_sha256s), "root_snapshot_sha256": _sha(root_snapshot_sha256),
              "base_checkpoint_sha256": _sha(base_checkpoint_sha256)}
    normalized, journals, candidates, materials, inodes = [], set(), set(), {}, {}
    previous = published = poststate = None
    tail, total, heads = base_checkpoint_sha256, 0, {base_checkpoint_sha256}
    prefixes = []
    if collect_prefixes:
        prefixes.append(_project_brs_reserved_prefix(
            domain, normalized, tail, previous, published, poststate, candidates, total,
        ))
    for ordinal, raw in enumerate(batches):
        if type(raw) is not dict or set(raw) != _BATCH_FIELDS:
            _fail("batch_invalid")
        episode_id, request_digest = episode_ids[ordinal], request_sha256s[ordinal]
        outcome = raw["outcome"]
        if (type(raw["ordinal"]) is not int or raw["ordinal"] != ordinal
                or type(raw["episode_id"]) is not str or raw["episode_id"] != episode_id
                or type(raw["request_sha256"]) is not str or raw["request_sha256"] != request_digest
                or type(outcome) is not str or outcome not in {"published", "all_rejected"}
                or _sha(raw["entry_checkpoint_sha256"]) != tail):
            _fail("batch_association_drift")
        execution, status = _execution(raw["execution_bytes"], run_id=run_id, wave=wave, ordinal=ordinal, episode_id=episode_id,
                                       request_sha256=request_digest, memory=root_snapshot_sha256, outcome=outcome)
        root_head, root_digest = _root(raw["root_checkpoint"], run_id=run_id, episode_ids=episode_ids,
                                       ordinal=ordinal, execution=execution, memory=root_snapshot_sha256,
                                       prior_executions={item["episode_id"]: item["execution"] for item in normalized})
        if root_head in heads:
            _fail("root_append_missing")
        heads.add(root_head)
        claim = raw["claim"]
        _plain(claim)
        if type(claim) is not dict or set(claim) != _CLAIM_FIELDS:
            _fail("claim_invalid")
        plan = _sha(raw["native_plan_sha256"])
        claim_digest = _digest({"protocol": "lunar-rsi-native-episode-claim-v1", "episode_id": episode_id,
                                "request_sha256": request_digest, "plan_sha256": plan})
        if (claim["episode_id"] != episode_id or claim["request_sha256"] != request_digest
                or claim["plan_sha256"] != plan or claim["status"] != status
                or _sha(claim["claim_sha256"]) != claim_digest
                or type(claim["created_at"]) is not str or not claim["created_at"]):
            _fail("claim_association_drift")
        before, before_wire = _descriptor(raw["before"], ProducerLineageBeforeIntent if ordinal == 0
                                           else ProducerLineageBeforeIntentV2)
        journal = before.journal_id
        if before.run_id != run_id or type(before.ordinal) is not int or before.ordinal != ordinal or journal in journals:
            _fail("descriptor_association_drift")
        journals.add(journal)
        if ordinal:
            attempted = (before.previous_attempt_journal_id, before.previous_attempt_outcome,
                         before.previous_attempt_terminal_sha256, before.previous_attempt_lineage_sha256)
            latest = (before.published_predecessor_journal_id, before.published_predecessor_terminal_sha256,
                      before.published_predecessor_lineage_sha256)
            if attempted != previous or latest != (published if published is not None else (None, None, None)):
                _fail("predecessor_drift")
        snapshots = raw["snapshots"]
        expected = {"archive-before", "state-before"}
        if outcome == "published":
            expected |= {"archive-after", "state-after"}
        if type(snapshots) is not dict or set(snapshots) != expected:
            _fail("snapshots_invalid")
        snapshots = {name: _pin(value) for name, value in snapshots.items()}
        if any(pin["name"] != name + ".snapshot" for name, pin in snapshots.items()):
            _fail("snapshots_invalid")
        if before.archive.to_dict() != snapshots["archive-before"] or before.state.to_dict() != snapshots["state-before"]:
            _fail("snapshot_descriptor_drift")
        before_content = tuple((snapshots[name]["sha256"], snapshots[name]["size"])
                               for name in ("archive-before", "state-before"))
        if poststate is not None and before_content != poststate:
            _fail("historical_poststate_drift")
        terminal_cls = ProducerLineageTerminal if outcome == "published" else ProducerLineageRejectedTerminalV2
        terminal, terminal_wire = _descriptor(raw["terminal"], terminal_cls)
        descriptors = [before_wire, terminal_wire]
        staged_wire = None
        if outcome == "published":
            staged, staged_wire = _descriptor(raw["staged"], ProducerLineageStagedTransition)
            descriptors.append(staged_wire)
            if (staged.run_id != run_id or staged.journal_id != journal or type(staged.ordinal) is not int
                    or staged.ordinal != ordinal or staged.before_sha256 != before.digest()
                    or terminal.staged_sha256 != staged.digest()):
                _fail("published_chain_drift")
            ids = staged.candidate_ids
            poststate = tuple((snapshots[name + "-after"]["sha256"], snapshots[name + "-after"]["size"])
                              for name in ("archive", "state"))
            if any(getattr(item, name + "_after_sha256") != poststate[index][0]
                   for item in (staged, terminal) for index, name in enumerate(("archive", "state"))):
                _fail("published_poststate_drift")
        else:
            if (raw["staged"] is not None or terminal.episode_id != episode_id
                    or terminal.before_sha256 != before.digest()
                    or (terminal.archive_sha256, terminal.state_sha256) != tuple(item[0] for item in before_content)):
                _fail("rejected_chain_drift")
            ids, poststate = terminal.candidate_ids, before_content
        if (terminal.run_id != run_id or terminal.journal_id != journal
                or type(terminal.ordinal) is not int or terminal.ordinal != ordinal):
            _fail("descriptor_association_drift")
        if candidates.intersection(ids) or len(candidates) + len(ids) > MAX_BRS_PREFIX_CANDIDATES:
            _fail("candidate_capacity_or_duplicate")
        candidates.update(ids)
        rows = raw["materials"]
        if type(rows) is not tuple or len(rows) > 512:
            _fail("materials_invalid")
        observed = {}
        for row in rows:
            if type(row) is not dict or set(row) != {"relative_path", "file_pin"}:
                _fail("materials_invalid")
            path, pin = row["relative_path"], _pin(row["file_pin"])
            # Evidence files under a rejection batch are physically retained at
            # ``rejections/<candidate>.json``.  Their pin names cannot contain a
            # slash, so the owner records a deterministic, collision-resistant
            # pin name instead of the nested relative path.  Keep that mapping
            # exact; every other material still uses the physical basename as
            # its pin name.  This preserves the path/inode contract without
            # pretending the hashed pin is a second physical file.
            batch_prefix = f"evolution/producer-batches/{journal}/"
            relative = path[len(batch_prefix):] if type(path) is str and path.startswith(batch_prefix) else None
            expected_name = path.split("/")[-1] if type(path) is str else None
            if type(relative) is str and relative.startswith("rejections/"):
                # A path in this namespace must be one of the terminal's
                # exact candidate files; never fall back to basename matching
                # for unknown, nested or non-JSON rejection paths.
                expected_name = None
                if relative.endswith(".json") and relative.count("/") == 1:
                    candidate = relative[len("rejections/"):-len(".json")]
                    if candidate in ids:
                        expected_name = "rejection-" + hashlib.sha256(relative.encode()).hexdigest()
            if (type(path) is not str or len(path) > 1024 or any(part in {"", ".", ".."} for part in path.split("/"))
                    or any(char in path for char in "\\\x00\r\n")
                    or pin["name"] != expected_name or path in observed):
                _fail("material_path_invalid")
            observed[path] = pin
            physical = (pin["device"], pin["inode"])
            if (path in materials and materials[path] != pin) or (physical in inodes and inodes[physical] != path):
                _fail("historical_material_drift")
            if path not in materials:
                total += pin["size"]
                if total > MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES:
                    _fail("material_capacity_exhausted")
                materials[path], inodes[physical] = pin, path
        directory = f"evolution/producer-batches/{journal}/lineage/"
        for pin in [*(item["file_pin"] for item in descriptors), *snapshots.values()]:
            if observed.get(directory + pin["name"]) != pin:
                _fail("original_material_missing")
        terminal_marker = terminal.terminal_sha256 if outcome == "published" else terminal.terminal_marker_sha256
        previous = (journal, outcome, terminal_marker, terminal.digest())
        if outcome == "published":
            published = (journal, terminal_marker, terminal.digest())
        tail = root_head
        normalized.append({"ordinal": ordinal, "episode_id": episode_id, "request_sha256": request_digest,
                           "native_plan_sha256": plan, "outcome": outcome, "execution": execution,
                           "execution_sha256": hashlib.sha256(raw["execution_bytes"]).hexdigest(),
                           "entry_checkpoint_sha256": raw["entry_checkpoint_sha256"], "root_checkpoint_sha256": root_head,
                           "root_payload_sha256": root_digest, "claim": claim, "before": before_wire,
                           "staged": staged_wire, "terminal": terminal_wire, "snapshots": snapshots,
                           "materials": [{"relative_path": path, "file_pin": pin} for path, pin in observed.items()]})
        if collect_prefixes:
            # Emit and bound this exact prefix before looking at the next batch.
            # Only expensive normalization of the same prior observations is
            # shared; every prefix still has its original complete encoding.
            prefixes.append(_project_brs_reserved_prefix(
                domain, normalized, tail, previous, published, poststate, candidates, total,
            ))
    if collect_prefixes:
        return tuple(prefixes)
    return (_project_brs_reserved_prefix(
        domain, normalized, tail, previous, published, poststate, candidates, total,
    ),)


def validate_brs_reserved_append(prefix: BRSLineagePrefix, *, batches: tuple[dict, ...]) -> BRSLineagePrefix:
    """Recompare retained observations and exactly one append; never refresh pins."""
    if (type(prefix) is not BRSLineagePrefix or type(prefix.domain_bytes) is not bytes
            or type(prefix.batch_bytes) is not tuple or type(prefix.canonical_bytes) is not bytes
            or len(prefix.domain_bytes) > MAX_BRS_PREFIX_BYTES or len(prefix.canonical_bytes) > MAX_BRS_PREFIX_BYTES
            or len(prefix.batch_bytes) > MAX_LINEAGE_BATCHES
            or any(type(item) is not bytes or len(item) > MAX_BRS_PREFIX_BYTES for item in prefix.batch_bytes)
            or type(batches) is not tuple or len(batches) != len(prefix.batch_bytes) + 1):
        _fail("append_invalid")
    try:
        domain = strict_json(prefix.domain_bytes, maximum=MAX_BRS_PREFIX_BYTES)
        _plain(domain)
        domain = {**domain, "episode_ids": tuple(domain["episode_ids"]),
                  "request_sha256s": tuple(domain["request_sha256s"])}
        old = validate_brs_reserved_prefix(**domain, batches=batches[:-1])
    except (TypeError, ValueError, KeyError) as exc:
        raise RSILearningError("rsi_brs_reserved_prefix_append_invalid") from exc
    if old != prefix:
        _fail("historical_prefix_drift")
    result = validate_brs_reserved_prefix(**domain, batches=batches)
    if result.batch_bytes[:-1] != prefix.batch_bytes:
        _fail("historical_prefix_drift")
    return result
