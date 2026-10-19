"""Bounded descriptive progress for an already reserved BRS wave.

Inputs are detached original/current controller checkpoints and complete observed
attempt traces. This module performs no I/O, clock reads, reservation, claim,
callback or owner construction. A projection is never execution authority; the
controller must independently prove original history, prefix custody and liveness.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, NoReturn

from .candidate_evaluation_spec import canonical_json
from .rsi_budget import RSIRunBudget
from .rsi_gateway import SolverRequest, SolverResult
from .rsi_learning import (
    MemorySnapshot,
    PracticeEpisode,
    RSILearningError,
    VerifierCheck,
    VerifierDecision,
)
from .rsi_python_brs_child_policy import (
    MAX_BRS_CHILD_AGGREGATE_BYTES,
    MAX_BRS_CHILD_ATTEMPTS,
    MAX_BRS_CHILD_CANDIDATES,
    MAX_BRS_CHILD_PREFLIGHT_BYTES,
    MAX_BRS_CHILD_PREFLIGHT_DEPTH,
)

_MAX_CHECKPOINT_BYTES = 128 * 1024
_MAX_NODES = 32768
_MAX_MATERIALS = 1024
_SHA = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_TRACE_FIELDS = {"episode", "claim", "result", "material_sha256s", "reference_sha256", "obligation_sha256"}
_CLAIM_FIELDS = {"episode_id", "request_sha256", "plan_sha256", "status", "claim_sha256", "created_at"}
_PINS = ("contract_sha256", "evaluator_sha256", "environment_sha256", "solver_id")
_CHARGED = {"practice_rounds", "practice_episodes", "solver_invocations", "evaluator_invocations", "verifier_invocations"}


class BRSReservedWaveError(RSILearningError):
    """A fixed-code refusal at the detached reserved-wave boundary."""

    def __init__(self, code: str) -> None:
        super().__init__("rsi_brs_reserved_wave_" + code)


def _fail(code: str) -> NoReturn:
    raise BRSReservedWaveError(code)


def _sha(value: object) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None or value == "0" * 64:
        _fail("digest_invalid")
    return value


def _integer(value: object, maximum: int) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        _fail("capacity_invalid")
    return value


def _plain(value: object, depth: int = 0, nodes: list[int] | None = None) -> None:
    """Check exact builtins before serializers/parsers can invoke supplied hooks."""
    nodes = [0] if nodes is None else nodes
    nodes[0] += 1
    if depth > MAX_BRS_CHILD_PREFLIGHT_DEPTH or nodes[0] > _MAX_NODES:
        _fail("shape_exceeded")
    kind = type(value)
    if value is None or kind in {bool, int}:
        return
    if kind is str:
        if len(value) > _MAX_CHECKPOINT_BYTES:
            _fail("bytes_exceeded")
        return
    if kind is float:
        if not math.isfinite(value):
            _fail("shape_invalid")
        return
    if kind is dict:
        if any(type(key) is not str for key in value):
            _fail("shape_invalid")
        children = value.values()
    elif kind is list:
        children = value
    else:
        _fail("shape_invalid")
    for item in children:
        _plain(item, depth + 1, nodes)


def _raw(value: object, *, maximum: int = _MAX_CHECKPOINT_BYTES) -> bytes:
    _plain(value)
    try:
        return canonical_json(value, maximum=maximum)
    except (TypeError, ValueError, OverflowError, UnicodeError, RecursionError) as exc:
        raise BRSReservedWaveError("bytes_exceeded") from exc


def _digest(value: object) -> str:
    return hashlib.sha256(_raw(value)).hexdigest()


def _checkpoint(value: object) -> dict[str, Any]:
    if type(value) is not dict:
        _fail("checkpoint_invalid")
    return json.loads(_raw(value))


def _materials(value: object) -> int:
    if type(value) is not tuple or len(value) > _MAX_MATERIALS:
        _fail("material_invalid")
    identities, aggregate = set(), 0
    for item in value:
        if (type(item) is not tuple or len(item) != 2 or type(item[0]) is not str
                or not item[0] or len(item[0]) > 256 or item[0] in identities
                or any(char in item[0] for char in "\x00\r\n")):
            _fail("material_invalid")
        identities.add(item[0])
        aggregate += _integer(item[1], MAX_BRS_CHILD_AGGREGATE_BYTES)
    if aggregate > MAX_BRS_CHILD_AGGREGATE_BYTES:
        _fail("aggregate_exceeded")
    return aggregate


@dataclass(frozen=True, slots=True)
class BRSReservedChildSelection:
    """Original untouched request bytes; no claim, owner or dispatch capability."""

    run_id: str
    wave: int
    ordinal: int
    episode_id: str
    root_snapshot_sha256: str
    request_sha256: str
    original_state_sha256: str
    episode_bytes: bytes
    request_bytes: bytes
    budget_bytes: bytes
    deadline_unix: int | float | None


@dataclass(frozen=True, slots=True)
class BRSReservedWaveProjection:
    """Immutable description; completion never changes reservation accounting."""

    run_id: str
    wave: int
    root_snapshot_sha256: str
    original_state_sha256: str
    plan_sha256: str
    budget_bytes: bytes
    deadline_unix: int | float | None
    intents: tuple[tuple[str, bytes, bytes], ...]
    settled_prefix: tuple[tuple[str, str, str], ...]
    candidate_count: int
    retained_materials: tuple[tuple[str, int], ...]
    aggregate_bytes: int

    @property
    def reservation_count(self) -> int:
        return len(self.intents)

    @property
    def completion_count(self) -> int:
        return len(self.settled_prefix)

    @property
    def next_ordinal(self) -> int | None:
        return self.completion_count if self.completion_count < self.reservation_count else None

    @property
    def latest_published_predecessor(self) -> tuple[str, str, str] | None:
        return next((item for item in reversed(self.settled_prefix) if item[1] == "published"), None)

    @property
    def episode_ids(self) -> tuple[str, ...]:
        return tuple(item[0] for item in self.intents)

    @property
    def request_sha256s(self) -> tuple[str, ...]:
        return tuple(hashlib.sha256(item[2]).hexdigest() for item in self.intents)


def _original_inputs(original: dict[str, Any], state: dict[str, Any]) -> tuple[str, int, str, tuple]:
    required = {"run_id", "mode", "status", "plan", "pins", "root_snapshot", "memory_snapshot",
                "budget_state", "intents", "executions"}
    if not required.issubset(original) or not required.issubset(state):
        _fail("checkpoint_invalid")
    if (original["mode"] != "brs" or state["mode"] != "brs"
            or original["status"] != "running" or state["status"] != "running"):
        _fail("control_invalid")
    run_id, plan, pins = original["run_id"], original["plan"], original["pins"]
    if type(run_id) is not str or _ID.fullmatch(run_id) is None:
        _fail("identity_invalid")
    if (type(plan) is not dict or plan.get("mode") != "brs" or type(plan.get("max_workers")) is not int
            or plan["max_workers"] != 1 or type(plan.get("wave")) is not int or plan["wave"] < 0
            or type(plan.get("practices")) is not list
            or not 1 <= len(plan["practices"]) <= MAX_BRS_CHILD_ATTEMPTS
            or any(type(item) is not dict for item in plan["practices"])
            or type(pins) is not dict or not set(_PINS).issubset(pins)):
        _fail("plan_invalid")
    for key in ("run_id", "plan", "pins", "root_snapshot", "intents", "budget_state"):
        if _raw(original[key]) != _raw(state[key]):
            _fail("original_drift")
    for key in ("producer_checkpoint_binding", "producer_brs_checkpoint_policy"):
        if _raw(original.get(key)) != _raw(state.get(key)):
            _fail("original_drift")
    root = MemorySnapshot.from_dict(original["root_snapshot"]).digest()
    if any(_raw(item["memory_snapshot"]) != _raw(original["root_snapshot"]) for item in (original, state)):
        _fail("memory_drift")
    count, wave = len(plan["practices"]), plan["wave"]
    budget = RSIRunBudget.load(original["budget_state"]).to_dict()
    if any(used != (count if name in _CHARGED else 0) for name, used in budget["consumed"].items()):
        _fail("reservation_invalid")
    if (type(original["executions"]) is not dict or original["executions"]
            or any(type(original.get(key, {})) is not dict or original.get(key, {})
                   for key in ("python_admission_refs", "brs_reconcile_obligations"))):
        _fail("original_not_pre_dispatch")
    domain = tuple(f"{run_id}-practice-{wave}-{ordinal}" for ordinal in range(count))
    if type(original["intents"]) is not dict or set(original["intents"]) != set(domain):
        _fail("domain_invalid")
    intents = []
    for ordinal, key in enumerate(domain):
        intent = original["intents"][key]
        if type(intent) is not dict or set(intent) != {"episode", "request"}:
            _fail("intent_invalid")
        episode, request = PracticeEpisode.from_dict(intent["episode"]), SolverRequest.from_dict(intent["request"])
        charter = {**plan["practices"][ordinal], "decision_sha256": _digest(plan["practices"][ordinal])}
        if (episode.status != "planned" or episode.episode_kind != "practice" or episode.run_id != run_id
                or episode.episode_id != key or episode.ordinal != ordinal or episode.wave != wave
                or episode.parent_target_episode_id != f"{run_id}-target-seed"
                or request.episode_id != key or episode.memory_snapshot_sha256 != root
                or request.memory_snapshot_sha256 != root
                or any(getattr(episode, pin) != pins[pin] or getattr(request, pin) != pins[pin] for pin in _PINS)
                or _raw(dict(request.budget)) != _raw(budget["planned"])
                or _raw(dict(request.practice_charter)) != _raw(charter)):
            _fail("intent_identity_invalid")
        intents.append((key, _raw(intent["episode"]), _raw(intent["request"])))
    return run_id, wave, root, tuple(intents)


def _verifier(value: object) -> VerifierDecision:
    if type(value) is not dict or type(value.get("checks")) is not list:
        _fail("execution_invalid")
    try:
        parsed = {**value, "checks": tuple(VerifierCheck(**item) for item in value["checks"])}
        verifier = VerifierDecision(**parsed)
    except (TypeError, ValueError) as exc:
        raise BRSReservedWaveError("execution_invalid") from exc
    if _raw(verifier.to_dict()) != _raw(value):
        _fail("execution_invalid")
    return verifier


def _settled_execution(value: object, intent: tuple[str, bytes, bytes], outcome: str, digest: str) -> None:
    if type(value) is not dict or set(value) != {"episode", "request", "result", "verifier"}:
        _fail("execution_invalid")
    if _digest(value) != digest or _raw(value["request"]) != intent[2]:
        _fail("execution_mismatch")
    initial, episode = PracticeEpisode.from_dict(json.loads(intent[1])), PracticeEpisode.from_dict(value["episode"])
    request, result = SolverRequest.from_dict(value["request"]), SolverResult.from_dict(value["result"])
    verifier = _verifier(value["verifier"])
    if (any(getattr(episode, name) != getattr(initial, name) for name in (
            "episode_id", "run_id", "episode_kind", "wave", "ordinal", "parent_target_episode_id",
            "memory_snapshot_sha256", *_PINS))
            or episode.request_sha256 != request.digest() or result.request_sha256 != request.digest()
            or result.episode_id != intent[0] or verifier.episode_id != intent[0]
            or (episode.verifier is not None and episode.verifier != verifier)
            or any(getattr(episode, name) != getattr(result, name) for name in (
                "trace_digest", "candidate_source_sha256", "dependency_sha256", "trace_events", "actor_fingerprint"))
            or (outcome == "published" and (episode.verifier != verifier or any(
                getattr(episode, name) != getattr(result, name) for name in (
                    "candidate_receipt_sha256", "execution_receipt_sha256", "official_evaluation_receipt_sha256"))))
            or any(getattr(verifier, pin) not in {None, getattr(request, pin)} for pin in _PINS[:3])
            or any(getattr(verifier, pin) not in {None, getattr(result, pin)} for pin in (
                "candidate_receipt_sha256", "execution_receipt_sha256", "official_evaluation_receipt_sha256"))):
        _fail("execution_identity_invalid")
    # Native publication and the later RSI verifier decision are separate layers.
    # Every genuinely completed/attached outcome is already settled, including a
    # failed or unresolved RSI verification; it must not cause another dispatch.
    if outcome == "published" and (episode.status != "completed" or result.status != "completed"):
        _fail("outcome_invalid")
    if (outcome == "all_rejected" and (episode.status != "failed" or result.status != "failed"
                                      or verifier.outcome == "pass")):
        _fail("outcome_invalid")


def _trace(trace: object, key: str, execution: dict | None, reference: dict | None) -> None:
    if type(trace) is not dict or set(trace) != _TRACE_FIELDS:
        _fail("trace_invalid")
    materials = trace["material_sha256s"]
    if type(materials) is not list or len(materials) > _MAX_MATERIALS:
        _fail("trace_invalid")
    for digest in materials:
        _sha(digest)
    for name in ("reference_sha256", "obligation_sha256"):
        if trace[name] is not None:
            _sha(trace[name])
    if execution is None:
        if any(trace[name] is not None for name in _TRACE_FIELDS - {"material_sha256s"}) or materials or reference is not None:
            _fail("attempt_requires_reconcile")
        return
    if (trace["episode"] != execution["episode"] or trace["result"] != execution["result"]
            or trace["obligation_sha256"] is not None or not materials or reference is None
            or trace["reference_sha256"] != _digest(reference)):
        _fail("settled_trace_mismatch")
    claim = trace["claim"]
    if (type(claim) is not dict or set(claim) != _CLAIM_FIELDS or claim["episode_id"] != key
            or claim["request_sha256"] != _digest(execution["request"])
            or claim["status"] != execution["result"]["status"]
            or type(claim["created_at"]) is not str or not claim["created_at"].strip()):
        _fail("claim_invalid")
    plan_sha = _sha(claim["plan_sha256"])
    if _sha(claim["claim_sha256"]) != _digest({
        "protocol": "lunar-rsi-native-episode-claim-v1", "episode_id": key,
        "request_sha256": claim["request_sha256"], "plan_sha256": plan_sha,
    }):
        _fail("claim_invalid")
    if (type(reference.get("native_plan")) is not dict
            or reference["native_plan"].get("plan_sha256") != plan_sha
            or reference["native_plan"].get("request") != execution["request"]):
        _fail("reference_invalid")


def project_reserved_brs_wave(
    original: dict[str, object], state: dict[str, object], *,
    attempt_traces: dict[str, dict[str, object]],
    settled_prefix: tuple[tuple[str, str, str], ...],
    retained_materials: tuple[tuple[str, int], ...], candidate_count: int,
) -> BRSReservedWaveProjection:
    """Compare detached observations; do not infer custody or retry eligibility.

    ``original`` is the original full-reservation, pre-dispatch checkpoint.
    ``attempt_traces`` must cover *every* original episode with actual episode,
    claim and result wire records (or None), material digest inventory, retained
    reference digest and obligation digest. No Boolean all-clear is accepted.
    Prefix facts must come from independent proof and match execution bodies here.
    """
    try:
        initial, current, traces = _checkpoint(original), _checkpoint(state), _checkpoint(attempt_traces)
        run_id, wave, root, intents = _original_inputs(initial, current)
        domain = tuple(item[0] for item in intents)
        if (type(settled_prefix) is not tuple or len(settled_prefix) > len(domain)
                or any(type(item) is not tuple or len(item) != 3 for item in settled_prefix)):
            _fail("prefix_invalid")
        for ordinal, (key, outcome, digest) in enumerate(settled_prefix):
            if type(key) is not str or key != domain[ordinal] or type(outcome) is not str or outcome not in {"published", "all_rejected"}:
                _fail("prefix_invalid")
            _sha(digest)
        executions, refs = current["executions"], current.get("python_admission_refs", {})
        if (type(executions) is not dict or set(executions) != set(domain[:len(settled_prefix)])
                or type(refs) is not dict or set(refs) != set(executions) or set(traces) != set(domain)):
            _fail("domain_invalid")
        obligations = current.get("brs_reconcile_obligations", {})
        if type(obligations) is not dict or obligations:
            _fail("attempt_requires_reconcile")
        known_candidates = 0
        for ordinal, key in enumerate(domain):
            execution, reference = executions.get(key), refs.get(key)
            if ordinal < len(settled_prefix):
                _settled_execution(execution, intents[ordinal], *settled_prefix[ordinal][1:])
                if (type(reference) is not dict or type(reference.get("prepared_journal")) is not dict
                        or type(reference["prepared_journal"].get("candidates")) is not list):
                    _fail("reference_invalid")
                known_candidates += len(reference["prepared_journal"]["candidates"])
            _trace(traces[key], key, execution, reference)
        if _integer(candidate_count, MAX_BRS_CHILD_CANDIDATES) != known_candidates:
            _fail("candidate_count_mismatch")
        aggregate = _materials(retained_materials)
        if settled_prefix and not retained_materials:
            _fail("material_invalid")
        budget_bytes = _raw(initial["budget_state"])
        result = BRSReservedWaveProjection(
            run_id, wave, root, _digest(initial), _digest(initial["plan"]), budget_bytes,
            initial["budget_state"]["planned"]["deadline_unix"], intents, settled_prefix,
            candidate_count, retained_materials, aggregate,
        )
        _projection_bytes(result)
        return result
    except BRSReservedWaveError:
        raise
    except (RSILearningError, KeyError, TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise BRSReservedWaveError("observation_invalid") from exc


def _projection_bytes(value: BRSReservedWaveProjection) -> bytes:
    if type(value) is not BRSReservedWaveProjection:
        _fail("projection_invalid")
    for name in ("root_snapshot_sha256", "original_state_sha256", "plan_sha256"):
        _sha(getattr(value, name))
    if (type(value.run_id) is not str or _ID.fullmatch(value.run_id) is None
            or type(value.wave) is not int or value.wave < 0
            or type(value.intents) is not tuple or not 1 <= len(value.intents) <= MAX_BRS_CHILD_ATTEMPTS
            or type(value.settled_prefix) is not tuple or len(value.settled_prefix) > len(value.intents)
            or type(value.budget_bytes) is not bytes or len(value.budget_bytes) > _MAX_CHECKPOINT_BYTES):
        _fail("projection_invalid")
    payload = {
        "run_id": value.run_id, "wave": value.wave, "root_snapshot_sha256": value.root_snapshot_sha256,
        "original_state_sha256": value.original_state_sha256, "plan_sha256": value.plan_sha256,
        "budget": json.loads(value.budget_bytes), "deadline_unix": value.deadline_unix,
        "intents": [], "settled_prefix": [], "candidate_count": value.candidate_count,
        "retained_materials": [], "aggregate_bytes": value.aggregate_bytes,
    }
    budget = RSIRunBudget.load(payload["budget"]).to_dict()
    if _raw(budget) != value.budget_bytes or _raw(budget["planned"]["deadline_unix"]) != _raw(value.deadline_unix):
        _fail("projection_invalid")
    if any(used != (len(value.intents) if name in _CHARGED else 0) for name, used in budget["consumed"].items()):
        _fail("projection_invalid")
    _integer(value.candidate_count, MAX_BRS_CHILD_CANDIDATES)
    if type(value.aggregate_bytes) is not int or value.aggregate_bytes != _materials(value.retained_materials):
        _fail("projection_invalid")
    for ordinal, item in enumerate(value.intents):
        if (type(item) is not tuple or len(item) != 3 or type(item[0]) is not str
                or item[0] != f"{value.run_id}-practice-{value.wave}-{ordinal}"
                or type(item[1]) is not bytes or type(item[2]) is not bytes
                or len(item[1]) > _MAX_CHECKPOINT_BYTES or len(item[2]) > _MAX_CHECKPOINT_BYTES):
            _fail("projection_invalid")
        episode_raw, request_raw = json.loads(item[1]), json.loads(item[2])
        if _raw(episode_raw) != item[1] or _raw(request_raw) != item[2]:
            _fail("projection_invalid")
        episode, request = PracticeEpisode.from_dict(episode_raw), SolverRequest.from_dict(request_raw)
        if (episode.status != "planned" or episode.episode_kind != "practice"
                or episode.episode_id != item[0] or request.episode_id != item[0]
                or episode.run_id != value.run_id or episode.wave != value.wave or episode.ordinal != ordinal
                or episode.memory_snapshot_sha256 != value.root_snapshot_sha256
                or request.memory_snapshot_sha256 != value.root_snapshot_sha256
                or _raw(dict(request.budget)) != _raw(budget["planned"])
                or any(getattr(episode, pin) != getattr(request, pin) for pin in _PINS)):
            _fail("projection_invalid")
        payload["intents"].append({"episode_id": item[0], "episode": episode_raw, "request": request_raw})
    for ordinal, item in enumerate(value.settled_prefix):
        if (type(item) is not tuple or len(item) != 3 or type(item[0]) is not str
                or item[0] != value.intents[ordinal][0]
                or type(item[1]) is not str or item[1] not in {"published", "all_rejected"}):
            _fail("projection_invalid")
        _sha(item[2])
        payload["settled_prefix"].append(list(item))
    for item in value.retained_materials:
        payload["retained_materials"].append(list(item))
    return _raw(payload, maximum=MAX_BRS_CHILD_PREFLIGHT_BYTES)


def select_reserved_brs_child(projection: BRSReservedWaveProjection) -> BRSReservedChildSelection | None:
    """Describe the next untouched child without reserving or creating a claim."""
    try:
        _projection_bytes(projection)
        ordinal = projection.next_ordinal
        if ordinal is None:
            return None
        key, episode_bytes, request_bytes = projection.intents[ordinal]
        request = SolverRequest.from_dict(json.loads(request_bytes))
        episode = PracticeEpisode.from_dict(json.loads(episode_bytes))
        if (request.episode_id != key or episode.episode_id != key or episode.run_id != projection.run_id
                or episode.ordinal != ordinal or episode.wave != projection.wave
                or request.memory_snapshot_sha256 != projection.root_snapshot_sha256
                or episode.memory_snapshot_sha256 != projection.root_snapshot_sha256):
            _fail("projection_invalid")
        return BRSReservedChildSelection(
            projection.run_id, projection.wave, ordinal, key, projection.root_snapshot_sha256,
            request.digest(), projection.original_state_sha256, episode_bytes, request_bytes,
            projection.budget_bytes, projection.deadline_unix,
        )
    except BRSReservedWaveError:
        raise
    except (RSILearningError, KeyError, TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise BRSReservedWaveError("projection_invalid") from exc
