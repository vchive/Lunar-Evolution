"""Bounded original-owner mailbox observations; never recovery authority.

These independent checkpoints describe historical observations. A published
response is not a worker receipt, and neither proves callback or process cleanup.
"""
from __future__ import annotations

import hashlib
import json
import math
import re

from .candidate_evaluation_spec import canonical_json
from .rsi_brs_native_process_evidence import parse_native_process_binding
from .rsi_brs_reconcile import BRSReconcileObligation
from .rsi_learning import RSILearningError
from .rsi_python_brs_handoff import BRSSelectedChildHandoff
from .rsi_python_brs_publication_mailbox import (
    BRSOwnerPublicationRequest,
    BRSOwnerPublicationResponse,
)

BINDING_PROTOCOL = "lunar-rsi-brs-mailbox-binding-v1"
OBSERVATION_PROTOCOL = "lunar-rsi-brs-mailbox-observation-v1"
STAGES = ("owner_capture", "request_observed", "response_generated", "transport_observed")
MAX_BRS_MAILBOX_EVIDENCE_BYTES = 512 * 1024
_SHA = re.compile(r"^[0-9a-f]{64}$")
_BINDING_FIELDS = frozenset({
    "protocol", "run_id", "episode_id", "obligation", "obligation_sha256",
    "handoff", "handoff_sha256", "selected_request_sha256", "native_plan_sha256",
    "native_claim_sha256", "run_record_sha256", "episode_record_sha256", "capture",
    "binding_sha256",
})
_OBSERVATION_FIELDS = frozenset({
    "protocol", "stage", "binding", "binding_sha256", "root_checkpoint_sha256",
    "mailbox_state", "mailbox_request_sha256", "request_payload_sha256",
    "response_sha256", "response_payload_sha256", "worker_receipt_observed",
    "callback_observation", "observation_sha256",
})
_MESSAGE_DIGESTS = (
    "mailbox_request_sha256", "request_payload_sha256", "response_sha256",
    "response_payload_sha256",
)


def _fail(code: str) -> None:
    raise RSILearningError("rsi_brs_mailbox_evidence_" + code)


def _sha(value: object) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None or value == "0" * 64:
        _fail("digest_invalid")
    return value


def _plain(value: object, depth: int = 0, remaining: list[int] | None = None):
    if remaining is None:
        remaining = [8192]
    remaining[0] -= 1
    if depth > 24 or remaining[0] < 0:
        _fail("shape_invalid")
    kind = type(value)
    if value is None or kind is bool:
        return value
    if kind is int and value.bit_length() <= 128:
        return value
    if kind is float and math.isfinite(value):
        return value
    if kind is str and len(value) <= MAX_BRS_MAILBOX_EVIDENCE_BYTES:
        return value
    if kind is dict and len(value) <= 64 and all(type(key) is str for key in value):
        return {key: _plain(item, depth + 1, remaining) for key, item in value.items()}
    if kind is list and len(value) <= 64:
        return [_plain(item, depth + 1, remaining) for item in value]
    _fail("shape_invalid")


def _clean(value: object) -> dict:
    clean = _plain(value)
    if type(clean) is not dict:
        _fail("shape_invalid")
    try:
        return json.loads(canonical_json(clean, maximum=MAX_BRS_MAILBOX_EVIDENCE_BYTES))
    except (TypeError, ValueError, UnicodeError, OverflowError) as exc:
        raise RSILearningError("rsi_brs_mailbox_evidence_shape_invalid") from exc


def _digest(value: dict, field: str) -> str:
    return hashlib.sha256(canonical_json(
        {name: item for name, item in value.items() if name != field},
        maximum=MAX_BRS_MAILBOX_EVIDENCE_BYTES,
    )).hexdigest()


def parse_brs_mailbox_binding(value: object) -> dict:
    """Detach and validate a fixed original binding without filesystem observations."""
    clean = _clean(value)
    if set(clean) != _BINDING_FIELDS or clean["protocol"] != BINDING_PROTOCOL:
        _fail("binding_invalid")
    try:
        obligation = BRSReconcileObligation.from_dict(clean["obligation"])
        handoff = BRSSelectedChildHandoff(**clean["handoff"])
        native = parse_native_process_binding(clean["capture"]["native_process"])
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise RSILearningError("rsi_brs_mailbox_evidence_binding_invalid") from exc
    for name in ("obligation_sha256", "handoff_sha256", "selected_request_sha256",
                 "native_plan_sha256", "native_claim_sha256", "run_record_sha256",
                 "episode_record_sha256", "binding_sha256"):
        _sha(clean[name])
    if (type(clean["capture"]) is not dict or set(clean["capture"]) != {"native_process"}
            or obligation.phase != "selected" or obligation.owner_result_sha256 is not None
            or obligation.native_claim_sha256 is None
            or clean["run_id"] != obligation.run_id or clean["episode_id"] != obligation.episode_id
            or clean["obligation_sha256"] != obligation.digest()
            or clean["handoff_sha256"] != handoff.sha256
            or clean["handoff_sha256"] != obligation.handoff_sha256
            or (handoff.run_id, handoff.episode_id, handoff.request_sha256, handoff.head_sha256) != (
                obligation.run_id, obligation.episode_id, obligation.request_sha256,
                obligation.controller_checkpoint_sha256,
            ) or clean["selected_request_sha256"] != obligation.request_sha256
            or clean["native_plan_sha256"] != obligation.native_plan_sha256
            or clean["native_claim_sha256"] != obligation.native_claim_sha256
            or clean["episode_record_sha256"] != obligation.episode_record_sha256
            or native["native_plan_sha256"] != obligation.native_plan_sha256
            or native["request_sha256"] != obligation.request_sha256
            or clean["binding_sha256"] != _digest(clean, "binding_sha256")):
        _fail("binding_invalid")
    return clean


def build_brs_mailbox_binding(
    *, obligation: BRSReconcileObligation, handoff: BRSSelectedChildHandoff,
    run_record_sha256: str, episode_record_sha256: str, native_process: dict,
) -> dict:
    if type(obligation) is not BRSReconcileObligation or type(handoff) is not BRSSelectedChildHandoff:
        _fail("binding_invalid")
    value = {
        "protocol": BINDING_PROTOCOL, "run_id": obligation.run_id,
        "episode_id": obligation.episode_id, "obligation": obligation.to_dict(),
        "obligation_sha256": obligation.digest(), "handoff": handoff.to_dict(),
        "handoff_sha256": handoff.sha256, "selected_request_sha256": obligation.request_sha256,
        "native_plan_sha256": obligation.native_plan_sha256,
        "native_claim_sha256": obligation.native_claim_sha256,
        "run_record_sha256": run_record_sha256, "episode_record_sha256": episode_record_sha256,
        "capture": {"native_process": parse_native_process_binding(native_process)},
    }
    value["binding_sha256"] = _digest(value, "binding_sha256")
    return parse_brs_mailbox_binding(value)


def brs_mailbox_evidence_namespace(binding: object) -> str:
    """One namespace per original obligation, including unknown process captures."""
    return "rsi-brs-mailbox:" + parse_brs_mailbox_binding(binding)["obligation_sha256"]


def parse_brs_mailbox_observation(value: object) -> dict:
    clean = _clean(value)
    if (set(clean) != _OBSERVATION_FIELDS or clean["protocol"] != OBSERVATION_PROTOCOL
            or type(clean["stage"]) is not str or clean["stage"] not in STAGES
            or type(clean["worker_receipt_observed"]) is not bool
            or clean["callback_observation"] != "unobserved"):
        _fail("observation_invalid")
    binding = parse_brs_mailbox_binding(clean["binding"])
    _sha(clean["root_checkpoint_sha256"])
    _sha(clean["observation_sha256"])
    if (clean["binding_sha256"] != binding["binding_sha256"]
            or clean["observation_sha256"] != _digest(clean, "observation_sha256")):
        _fail("observation_invalid")
    for field in _MESSAGE_DIGESTS:
        if clean[field] is not None:
            _sha(clean[field])
    request = clean["mailbox_request_sha256"] is not None
    response = clean["response_sha256"] is not None
    if (request != (clean["request_payload_sha256"] is not None)
            or response != (clean["response_payload_sha256"] is not None)):
        _fail("observation_invalid")
    stage = clean["stage"]
    state = clean["mailbox_state"]
    if type(state) is not str:
        _fail("observation_invalid")
    if stage == "owner_capture":
        valid = state in {"open", "queued"} and not response and not clean["worker_receipt_observed"]
        if request != (state == "queued"):
            valid = False
    elif stage == "request_observed":
        valid = state == "inflight" and request and not response and not clean["worker_receipt_observed"]
    elif stage == "response_generated":
        valid = state == "inflight" and request and response and not clean["worker_receipt_observed"]
    else:
        valid = state in {"delivered", "abandoned"} and request and response
        if clean["worker_receipt_observed"] and state != "delivered":
            valid = False
    if not valid:
        _fail("observation_invalid")
    return clean


def build_brs_mailbox_observation(
    binding: object, *, stage: str, root_checkpoint_sha256: str, mailbox_state: str,
    worker_receipt_observed: bool, request: BRSOwnerPublicationRequest | None = None,
    response: BRSOwnerPublicationResponse | None = None,
) -> dict:
    binding = parse_brs_mailbox_binding(binding)
    if request is not None:
        if type(request) is not BRSOwnerPublicationRequest:
            _fail("request_invalid")
        request = BRSOwnerPublicationRequest(
            request.run_id, request.episode_id, request.handoff_sha256,
            request.payload, request.request_sha256,
        )
        if (request.run_id, request.episode_id, request.handoff_sha256) != (
            binding["run_id"], binding["episode_id"], binding["handoff_sha256"],
        ):
            _fail("request_invalid")
        payload = json.loads(request.payload)
        if (payload["native_plan_sha256"] != binding["native_plan_sha256"]
                or (payload["expected_head_sha256"], payload["expected_state_sha256"]) != (
                    binding["handoff"]["head_sha256"], binding["handoff"]["state_sha256"],
                )):
            _fail("request_invalid")
    if response is not None:
        if type(response) is not BRSOwnerPublicationResponse or request is None:
            _fail("response_invalid")
        response = BRSOwnerPublicationResponse(
            response.run_id, response.episode_id, response.handoff_sha256,
            response.request_sha256, response.payload, response.response_sha256,
        )
        if (response.run_id, response.episode_id, response.handoff_sha256,
                response.request_sha256) != (
                request.run_id, request.episode_id, request.handoff_sha256, request.request_sha256,
        ):
            _fail("response_invalid")
    value = {
        "protocol": OBSERVATION_PROTOCOL, "stage": stage, "binding": binding,
        "binding_sha256": binding["binding_sha256"],
        "root_checkpoint_sha256": root_checkpoint_sha256, "mailbox_state": mailbox_state,
        "mailbox_request_sha256": None if request is None else request.request_sha256,
        "request_payload_sha256": None if request is None else hashlib.sha256(request.payload).hexdigest(),
        "response_sha256": None if response is None else response.response_sha256,
        "response_payload_sha256": None if response is None else hashlib.sha256(response.payload).hexdigest(),
        "worker_receipt_observed": worker_receipt_observed, "callback_observation": "unobserved",
    }
    value["observation_sha256"] = _digest(value, "observation_sha256")
    return parse_brs_mailbox_observation(value)


def validate_brs_mailbox_history(history: object, *, binding: object = None) -> tuple | None:
    """Validate up to four adjacent events; a missing suffix remains unknown."""
    if type(history) not in {tuple, list} or len(history) > len(STAGES):
        _fail("history_invalid")
    expected_binding = None if binding is None else parse_brs_mailbox_binding(binding)
    previous = None
    seen = set()
    for index, entry in enumerate(history):
        if type(entry) not in {tuple, list} or len(entry) != 2:
            _fail("history_invalid")
        head, raw = entry
        _sha(head)
        if head in seen:
            _fail("history_invalid")
        seen.add(head)
        record = parse_brs_mailbox_observation(raw)
        if record["stage"] != STAGES[index]:
            _fail("history_invalid")
        if expected_binding is None:
            expected_binding = record["binding"]
        if record["binding"] != expected_binding:
            _fail("binding_drift")
        if previous is not None:
            for field in _MESSAGE_DIGESTS:
                if previous[field] is not None and record[field] != previous[field]:
                    _fail("history_invalid")
        previous = record
    return None if previous is None else (history[-1][0], previous)


def inspect_brs_mailbox_evidence(ledger: object, run_id: str, episode_id: str) -> dict:
    """Read an existing rebuilt ledger without initialization or process observation."""
    from .rsi_brs_reconcile import FIELD, parse_brs_reconcile_obligations
    from .rsi_gateway import SolverRequest
    from .rsi_store import RSILedger

    if type(ledger) is not RSILedger:
        _fail("ledger_invalid")
    with ledger.read_only_observations():
        roots = ledger.controller_checkpoint_history(run_id)
        if not roots:
            _fail("root_missing")
        original = next((parse_brs_reconcile_obligations(state.get(FIELD)).get(episode_id)
                         for _head, state in roots if episode_id in state.get(FIELD, {})), None)
        obligation = parse_brs_reconcile_obligations(roots[-1][1].get(FIELD)).get(episode_id)
        if original is None or obligation is None:
            _fail("obligation_missing")
        if original.to_dict() != obligation.to_dict():
            _fail("obligation_drift")
        namespace = "rsi-brs-mailbox:" + obligation.digest()
        history = ledger.controller_checkpoint_history(namespace)
        latest = validate_brs_mailbox_history(history)
        if latest is None:
            return {"status": "missing", "namespace": namespace, "head": None,
                    "binding": None, "records": [], "callback_observation": "unobserved",
                    "native_process_observation": "unobserved", "terminal_evidence": False}
        binding = latest[1]["binding"]
        if binding["obligation"] != obligation.to_dict() or binding["run_id"] != run_id:
            _fail("binding_drift")
        validate_brs_mailbox_root_history(roots, history, binding=binding)
        for logical_id, key, kind in ((run_id, "run_record_sha256", "run"),
                                      (episode_id, "episode_record_sha256", "episode")):
            captured = next((record for record in ledger.history(logical_id)
                             if record.record_sha256 == binding[key]), None)
            if captured is None or captured.kind != kind or captured.state != "running":
                _fail("binding_drift")
            if kind == "episode" and (captured.payload.get("run_id") != run_id
                                       or captured.request_sha256 != binding["selected_request_sha256"]):
                _fail("binding_drift")
        origin = next(state for head, state in roots
                      if head == obligation.controller_checkpoint_sha256)
        try:
            request = SolverRequest.from_dict(origin["intents"][episode_id]["request"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RSILearningError("rsi_brs_mailbox_evidence_binding_drift") from exc
        if request.episode_id != episode_id or request.digest() != binding["selected_request_sha256"]:
            _fail("binding_drift")
        claim = ledger.inspect_native_episode_claim(request, plan_sha256=binding["native_plan_sha256"])
        if claim is None or claim.claim_sha256 != binding["native_claim_sha256"]:
            _fail("native_claim_drift")
        # Reading uses several existing read-only ledger APIs. Detect an append
        # during inspection rather than combine root/side facts from two epochs.
        if (ledger.controller_checkpoint(run_id) != roots[-1]
                or ledger.controller_checkpoint(namespace) != latest):
            _fail("inspection_drift")
        return {"status": "transport_observed" if len(history) == 4 else "partial",
                "namespace": namespace, "head": latest[0], "binding": binding,
                "records": [parse_brs_mailbox_observation(record) for _head, record in history],
                "callback_observation": "unobserved", "native_process_observation": "unobserved",
                "terminal_evidence": False}


def validate_brs_mailbox_root_history(roots: list, history: list, *, binding: object) -> None:
    """Require original capture and nondecreasing root ancestors for each event."""
    from .rsi_brs_reconcile import FIELD

    binding = parse_brs_mailbox_binding(binding)
    indices = {head: index for index, (head, _state) in enumerate(roots)}
    origin = binding["obligation"]["controller_checkpoint_sha256"]
    if origin not in indices:
        _fail("root_drift")
    original_state = roots[indices[origin]][1]
    if hashlib.sha256(canonical_json(original_state, maximum=8 * 1024 * 1024)).hexdigest() != binding["handoff"]["state_sha256"]:
        _fail("root_drift")
    previous = indices[origin]
    for _head, record in history:
        root = record["root_checkpoint_sha256"]
        index = indices.get(root, -1)
        if index <= indices[origin] or index < previous:
            _fail("root_drift")
        if any(state.get(FIELD, {}).get(binding["episode_id"]) != binding["obligation"]
               for _digest, state in roots[indices[origin] + 1:index + 1]):
            _fail("root_drift")
        previous = index
    if any(state.get(FIELD, {}).get(binding["episode_id"]) != binding["obligation"]
           for _head, state in roots[indices[origin] + 1:]):
        _fail("root_drift")
