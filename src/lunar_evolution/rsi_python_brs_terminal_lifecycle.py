"""Private original-owner receipt/callback observations, never terminal authority.

The selected worker only exchanges detached primitives with its original owner.
Only that owner can persist the independent side history and acknowledge a
callback attempt. Publication, episode/result and native-process evidence remain
separate legs; these observations never settle an episode or consume a fence.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor

from .candidate_evaluation_spec import canonical_json
from .rsi_brs_mailbox_evidence import (
    parse_brs_mailbox_binding,
    validate_brs_mailbox_history,
    validate_brs_mailbox_root_history,
)
from .rsi_learning import RSILearningError
from .rsi_python_brs_admission import (
    BRSAdmissionAck,
    BRSAdmissionChannel,
    build_brs_admission_ready,
)
from .rsi_python_brs_handoff import BRSSelectedChildHandoff
from .rsi_python_brs_publication_mailbox import (
    BRSOwnerPublicationMailbox,
    BRSOwnerPublicationRequest,
    BRSOwnerPublicationResponse,
)
from .rsi_python_brs_result_delivery import deliver_brs_owner_result

BINDING_PROTOCOL = "lunar-rsi-brs-terminal-binding-v1"
OBSERVATION_PROTOCOL = "lunar-rsi-brs-terminal-observation-v1"
STAGES = ("delivery", "callback_started", "callback_finished", "worker_terminal")
MAX_BRS_TERMINAL_EVIDENCE_BYTES = 8 * 1024 * 1024
_SHA = re.compile(r"^[0-9a-f]{64}$")
_BINDING_FIELDS = frozenset({"protocol", "mailbox_binding", "owner_thread_id", "worker_thread_id",
                             "future_id", "executor_id", "thread_id", "binding_sha256"})
_OBSERVATION_FIELDS = frozenset({"protocol", "stage", "binding", "binding_sha256",
                                 "root_checkpoint_sha256", "facts", "observation_sha256"})


def _fail(reason: str) -> None:
    raise RSILearningError("rsi_brs_terminal_" + reason)


def _plain(value: object, depth: int = 0, remaining: list[int] | None = None):
    if remaining is None:
        remaining = [32768]
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
    if kind is str and len(value) <= MAX_BRS_TERMINAL_EVIDENCE_BYTES:
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
    return json.loads(canonical_json(clean, maximum=MAX_BRS_TERMINAL_EVIDENCE_BYTES))


def _digest(value: dict, field: str) -> str:
    return hashlib.sha256(canonical_json(
        {key: item for key, item in value.items() if key != field},
        maximum=MAX_BRS_TERMINAL_EVIDENCE_BYTES,
    )).hexdigest()


def _sha(value: object) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None or value == "0" * 64:
        _fail("digest_invalid")
    return value


def parse_brs_terminal_binding(value: object) -> dict:
    clean = _clean(value)
    if set(clean) != _BINDING_FIELDS or clean["protocol"] != BINDING_PROTOCOL:
        _fail("binding_invalid")
    mailbox = parse_brs_mailbox_binding(clean["mailbox_binding"])
    owner, worker = clean["owner_thread_id"], clean["worker_thread_id"]
    if (type(owner) is not int or type(worker) is not int or min(owner, worker) <= 0
            or owner == worker or owner != mailbox["handoff"]["owner_thread_id"]):
        _fail("binding_invalid")
    for field, prefix in (("future_id", "future-"), ("executor_id", "executor-"), ("thread_id", "thread-")):
        name = clean[field]
        if type(name) is not str or re.fullmatch(prefix + r"[0-9a-f]{1,32}", name) is None:
            _fail("binding_invalid")
    if _sha(clean["binding_sha256"]) != _digest(clean, "binding_sha256"):
        _fail("binding_invalid")
    return clean


def brs_terminal_evidence_namespace(binding: object) -> str:
    return "rsi-brs-terminal:" + parse_brs_terminal_binding(binding)["mailbox_binding"]["obligation_sha256"]


def _messages(facts: dict, binding: dict):
    if set(facts) != {"request_fields", "response_fields", "publication"}:
        _fail("delivery_invalid")
    request, response = facts["request_fields"], facts["response_fields"]
    if (type(request) is not list or len(request) != 5 or any(type(item) is not str for item in request)
            or type(response) is not list or len(response) != 6 or any(type(item) is not str for item in response)):
        _fail("delivery_invalid")
    message = BRSOwnerPublicationRequest(*request[:3], request[3].encode("utf-8"), request[4])
    result = BRSOwnerPublicationResponse(*response[:4], response[4].encode("utf-8"), response[5])
    mailbox = binding["mailbox_binding"]
    handoff = BRSSelectedChildHandoff(**mailbox["handoff"])
    gate = deliver_brs_owner_result(result, message, handoff,
                                   expected_native_plan_sha256=mailbox["native_plan_sha256"])
    publication = facts["publication"]
    if type(publication) is not dict or set(publication) != {"lineage", "journal", "manifest"}:
        _fail("publication_invalid")
    from .producer_bundle_publication import ProducerBundlePublicationJournal

    journal = ProducerBundlePublicationJournal.from_dict(publication["journal"])
    lineage, manifest = publication["lineage"], publication["manifest"]
    if (journal.state not in {"published", "all_rejected"}
            or gate.delivery.publication_status != journal.state
            or gate.delivery.journal_sha256 != journal.digest()
            or journal.run_id != mailbox["run_id"] or journal.task_id != mailbox["episode_id"]
            or gate.delivery.terminal_marker_sha256 != journal.terminal_marker_sha256
            or gate.delivery.archive_after_sha256 != journal.archive_after_sha256
            or gate.delivery.state_after_sha256 != journal.state_after_sha256
            or gate.delivery.selected_request_sha256 != mailbox["selected_request_sha256"]
            or type(lineage) is not dict
            or type(lineage.get("batches")) is not list or len(lineage["batches"]) != 1
            or type(lineage["batches"][0]) is not dict):
        _fail("publication_invalid")
    if journal.state == "published":
        if (type(manifest) is not dict or manifest.get("journal_id") != journal.journal_id
                or manifest.get("archive_after_sha256") != journal.archive_after_sha256
                or manifest.get("state_after_sha256") != journal.state_after_sha256
                or manifest.get("manifest_sha256") != _digest(manifest, "manifest_sha256")
                or lineage["batches"][0].get("state") != "terminal"
                or type(lineage.get("head")) is not dict
                or lineage["head"].get("journal_id") != journal.journal_id
                or lineage["head"].get("terminal_sha256") != journal.terminal_marker_sha256):
            _fail("publication_invalid")
    else:
        from .rsi_brs_rejection_c1 import rejected_provenance_entry, rejected_provenance_index

        entry = lineage["batches"][0]
        rejected = rejected_provenance_entry(entry)
        if (manifest is not None or lineage.get("head") is not None
                or lineage.get("rejections") != rejected_provenance_index(entry)
                or entry["rejected_journal"] != journal.to_dict()
                or entry["request_sha256"] != mailbox["selected_request_sha256"]
                or entry["native_plan_sha256"] != mailbox["native_plan_sha256"]
                or (rejected.run_id, rejected.episode_id, rejected.journal_id) !=
                    (mailbox["run_id"], mailbox["episode_id"], journal.journal_id)):
            _fail("publication_invalid")
    return message, result


def parse_brs_terminal_observation(value: object) -> dict:
    clean = _clean(value)
    if set(clean) != _OBSERVATION_FIELDS or clean["protocol"] != OBSERVATION_PROTOCOL:
        _fail("observation_invalid")
    binding = parse_brs_terminal_binding(clean["binding"])
    if (clean["binding_sha256"] != binding["binding_sha256"]
            or _sha(clean["observation_sha256"]) != _digest(clean, "observation_sha256")):
        _fail("observation_invalid")
    _sha(clean["root_checkpoint_sha256"])
    stage, facts = clean["stage"], clean["facts"]
    if type(stage) is not str or stage not in STAGES or type(facts) is not dict:
        _fail("observation_invalid")
    if stage == "delivery":
        _messages(facts, binding)
    elif stage == "callback_started":
        if facts != {"attempt": 1} or type(facts.get("attempt")) is not int:
            _fail("callback_invalid")
    elif stage == "callback_finished":
        if (set(facts) != {"attempt", "outcome"} or type(facts["attempt"]) is not int
                or facts["attempt"] != 1 or type(facts["outcome"]) is not str
                or facts["outcome"] not in {"returned", "unknown"}):
            _fail("callback_invalid")
    elif (set(facts) != {"future_outcome", "executor_joined", "mailbox_closed", "worker_exited"}
          or type(facts["future_outcome"]) is not str or facts["future_outcome"] not in {"returned", "raised"}
          or any(facts[key] is not True for key in ("executor_joined", "mailbox_closed", "worker_exited"))):
        _fail("worker_invalid")
    return clean


def build_brs_terminal_observation(binding: object, *, stage: str,
                                   root_checkpoint_sha256: str, facts: dict) -> dict:
    binding = parse_brs_terminal_binding(binding)
    value = {"protocol": OBSERVATION_PROTOCOL, "stage": stage, "binding": binding,
             "binding_sha256": binding["binding_sha256"], "root_checkpoint_sha256": root_checkpoint_sha256,
             "facts": _clean(facts)}
    value["observation_sha256"] = _digest(value, "observation_sha256")
    return parse_brs_terminal_observation(value)


def validate_brs_terminal_history(history: object, *, binding: object = None) -> tuple | None:
    if type(history) not in {tuple, list} or len(history) > len(STAGES):
        _fail("history_invalid")
    fixed = None if binding is None else parse_brs_terminal_binding(binding)
    previous, seen = None, set()
    for index, pair in enumerate(history):
        if type(pair) not in {tuple, list} or len(pair) != 2:
            _fail("history_invalid")
        head, raw = pair
        _sha(head)
        record = parse_brs_terminal_observation(raw)
        if head in seen or record["stage"] != STAGES[index]:
            _fail("history_invalid")
        seen.add(head)
        if fixed is None:
            fixed = record["binding"]
        if record["binding"] != fixed:
            _fail("binding_drift")
        previous = (head, record)
    return previous


def inspect_brs_worker_terminal_evidence(ledger: object, run_id: str, episode_id: str) -> dict:
    """Read original durable facts coherently; no process/thread/callback execution."""
    from .rsi_store import RSILedger

    if type(ledger) is not RSILedger:
        _fail("ledger_invalid")
    snapshot = RSILedger.read_brs_terminal_evidence_snapshot(ledger, run_id, episode_id)
    roots, history = snapshot["roots"], snapshot["terminal_history"]
    from .rsi_brs_reconcile import FIELD, parse_brs_reconcile_obligations

    if not roots:
        _fail("root_missing")
    obligation = parse_brs_reconcile_obligations(roots[-1][1].get(FIELD)).get(episode_id)
    if obligation is None:
        _fail("obligation_missing")
    namespace = "rsi-brs-terminal:" + obligation.digest()
    result = {"status": "missing", "namespace": namespace, "head": None, "binding": None, "records": [],
              "delivery": None, "callback_observation": "unobserved", "worker_terminal": False,
              "terminal_evidence": False, "snapshot_pins": _clean(snapshot["pins"])}
    latest = validate_brs_terminal_history(history)
    if latest is None:
        return result
    binding = latest[1]["binding"]
    mailbox = binding["mailbox_binding"]
    if (mailbox["run_id"] != run_id or mailbox["episode_id"] != episode_id
            or mailbox["obligation"] != obligation.to_dict()):
        _fail("binding_drift")
    transport = snapshot["mailbox_history"]
    tail = validate_brs_mailbox_history(transport, binding=mailbox)
    if tail is None or len(transport) != 4:
        _fail("transport_incomplete")
    validate_brs_mailbox_root_history(roots, transport, binding=mailbox)
    records = [parse_brs_terminal_observation(raw) for _head, raw in history]
    indices = {head: index for index, (head, _state) in enumerate(roots)}
    previous = indices[transport[-1][1]["root_checkpoint_sha256"]]
    for record in records:
        current = indices.get(record["root_checkpoint_sha256"])
        if current is None or current < previous:
            _fail("root_drift")
        state = roots[current][1]
        if (state.get(FIELD, {}).get(episode_id) != obligation.to_dict()
                or state.get("producer_publication_lineage") != records[0]["facts"]["publication"]["lineage"]):
            _fail("root_drift")
        previous = current
    message, response = _messages(records[0]["facts"], binding)
    observed = tail[1]
    if (message.request_sha256 != observed["mailbox_request_sha256"]
            or hashlib.sha256(message.payload).hexdigest() != observed["request_payload_sha256"]
            or response.response_sha256 != observed["response_sha256"]
            or hashlib.sha256(response.payload).hexdigest() != observed["response_payload_sha256"]):
        _fail("transport_drift")
    callback = "unobserved" if len(records) == 1 else "started"
    if len(records) >= 3:
        callback = records[2]["facts"]["outcome"]
    result.update(status="worker_terminal" if len(records) == 4 else "partial", head=latest[0],
                  binding=binding, records=records, delivery=records[0]["facts"],
                  callback_observation=callback, worker_terminal=len(records) == 4)
    return _clean(result)


class _PrimitiveExchange:
    """Exact primitives under the condition; durable work remains with the owner."""

    __slots__ = ("acked", "admission_ack", "admission_offer", "admission_state", "condition", "deadline",
                 "entered", "events", "failed")

    def __init__(self, deadline: float | None) -> None:
        self.condition = threading.Condition()
        self.events = []
        self.acked = 0
        self.failed = False
        self.entered = False
        self.deadline = deadline
        self.admission_offer, self.admission_ack = None, None
        self.admission_state = "unused"

    def submit(self, event: tuple, check) -> None:
        if (type(event) is not tuple or not event or type(event[0]) is not str
                or event[0] not in STAGES[:3]):
            _fail("observation_drift")
        stage = event[0]
        if stage == "delivery":
            if (len(event) != 3 or type(event[1]) is not tuple or len(event[1]) != 5
                    or type(event[2]) is not tuple or len(event[2]) != 6
                    or any(type(item) is not (bytes if position == payload else str)
                           for values, payload in ((event[1], 3), (event[2], 4))
                           for position, item in enumerate(values))):
                _fail("observation_drift")
        elif ((stage == "callback_started" and len(event) != 1)
              or (stage == "callback_finished" and (len(event) != 2 or type(event[1]) is not str
                  or event[1] not in {"returned", "unknown"}))):
            _fail("observation_drift")
        if type(self.condition) is not threading.Condition or not callable(check):
            _fail("observation_drift")
        with self.condition:
            if (type(self.events) is not list or type(self.acked) is not int
                    or not 0 <= self.acked <= len(self.events) <= 3 or type(self.failed) is not bool):
                _fail("observation_drift")
            if self.failed or len(self.events) >= 3:
                _fail("worker_unavailable")
            self.events.append(event)
            position = len(self.events)
            self.condition.notify_all()
        while True:
            check()
            with self.condition:
                if self.failed:
                    _fail("callback_unknown")
                if self.acked >= position:
                    return
                if self.deadline is not None and time.monotonic() >= self.deadline:
                    self.failed = True
                    self.condition.notify_all()
                    _fail("callback_unknown")
                self.condition.wait(.05)

    def fail(self) -> None:
        with self.condition:
            self.failed = True
            self.condition.notify_all()


class _BRSWorkerTerminalEndpoint:
    __slots__ = ("_admission_ack", "_admission_channel", "_admission_condition", "_admission_offer", "_exchange",
                 "_handoff_bytes", "_mailbox", "_plan_sha256", "_scope", "_status", "_worker_object_id",
                 "_worker_thread")

    def __init__(self, mailbox, exchange, handoff_bytes, plan_sha256, worker_thread, worker_object_id,
                 admission_channel=None):
        if admission_channel is not None and type(admission_channel) is not BRSAdmissionChannel:
            _fail("worker_invalid")
        self._mailbox, self._exchange = mailbox, exchange
        self._handoff_bytes, self._plan_sha256 = handoff_bytes, plan_sha256
        self._worker_thread, self._status = worker_thread, "pending"
        self._worker_object_id = worker_object_id
        self._admission_channel = admission_channel
        self._admission_condition = None if admission_channel is None else admission_channel._condition
        self._admission_offer = self._admission_ack = None
        self._scope = (mailbox, exchange, handoff_bytes, plan_sha256, worker_thread, worker_object_id,
                       admission_channel, self._admission_condition)

    @property
    def status(self) -> str:
        return self._status

    def _identity(self):
        if (type(self) is not _BRSWorkerTerminalEndpoint or type(self._scope) is not tuple
                or len(self._scope) != 8 or type(self._mailbox) is not BRSOwnerPublicationMailbox
                or type(self._exchange) is not _PrimitiveExchange
                or self._scope[0] is not self._mailbox or self._scope[1] is not self._exchange
                or any(type(item) is not kind for item, kind in zip(
                    self._scope[2:6], (bytes, str, int, int), strict=True))
                or self._scope[2:6] != (self._handoff_bytes, self._plan_sha256,
                                        self._worker_thread, self._worker_object_id)
                or self._scope[6] is not self._admission_channel
                or self._scope[7] is not self._admission_condition
                or threading.get_ident() != self._worker_thread
                or id(threading.current_thread()) != self._worker_object_id):
            _fail("worker_invalid")
        channel, condition = self._scope[6:]
        if channel is None:
            if condition is not None:
                _fail("worker_invalid")
        elif (type(channel) is not BRSAdmissionChannel or type(condition) is not threading.Condition
                or channel._condition is not condition):
            _fail("worker_invalid")

    def _wait_check(self, check):
        # The original mailbox invokes this outside its condition. The original
        # budget callback also remains outside both transport conditions.
        check()
        _BRSWorkerTerminalEndpoint._identity(self)
        exchange, channel = self._exchange, self._admission_channel
        with exchange.condition:
            offer, status, ack = exchange.admission_offer, exchange.admission_state, exchange.admission_ack
            if exchange.failed or type(status) is not str:
                _fail("admission_unavailable")
            if offer is None:
                if (status != "unused" or ack is not None or self._admission_offer is not None
                        or self._admission_ack is not None):
                    _fail("admission_drift")
                return
            if type(offer) is not bytes or channel is None:
                _fail("admission_drift")
            if status == "received":
                if (self._admission_offer is not offer or self._admission_ack is not ack
                        or type(ack) is not tuple or len(ack) != 4
                        or any(type(item) is not str for item in ack)):
                    _fail("admission_drift")
                return
            if (status != "offered" or ack is not None or self._admission_offer is not None
                    or self._admission_ack is not None):
                _fail("admission_drift")
        with self._admission_condition:
            guarded = channel._rejection_ready_worker_guarded
            if type(guarded) is not bool or channel._closed:
                _fail("admission_unavailable")
            if guarded is False:
                return  # The owner must arm before any natural ready is built.
        with exchange.condition:
            if (exchange.failed or exchange.admission_offer is not offer
                    or exchange.admission_state != "offered" or exchange.admission_ack is not None):
                _fail("admission_drift")
            exchange.admission_state = "requested"
            self._admission_offer = offer
        handoff = BRSSelectedChildHandoff(**json.loads(self._handoff_bytes))
        ready = build_brs_admission_ready(handoff.run_id, handoff.episode_id, offer)
        # Do not pass this wrapper recursively: the admission request invokes
        # only the already-held original worker check while waiting for its ACK.
        acknowledgement = BRSAdmissionChannel.request(channel, ready, check=check)
        _BRSWorkerTerminalEndpoint._identity(self)
        if type(acknowledgement) is not BRSAdmissionAck:
            _fail("admission_drift")
        fields = (acknowledgement.run_id, acknowledgement.episode_id,
                  acknowledgement.request_sha256, acknowledgement.record_sha256)
        if (any(type(item) is not str for item in fields)
                or fields[:3] != (handoff.run_id, handoff.episode_id, ready.request_sha256)):
            _fail("admission_drift")
        with exchange.condition:
            if (exchange.failed or exchange.admission_offer is not offer
                    or exchange.admission_state != "requested" or exchange.admission_ack is not None):
                _fail("admission_drift")
            exchange.admission_ack, exchange.admission_state = fields, "received"
            self._admission_ack = fields
            exchange.condition.notify_all()

    def receive_and_settle(self, request: BRSOwnerPublicationRequest, *, callback, check):
        _BRSWorkerTerminalEndpoint._identity(self)
        if not callable(callback) or not callable(check):
            _fail("worker_invalid")
        if self._status != "pending":
            _fail("worker_unavailable")
        self._status = "inflight"
        exchange = self._exchange
        try:
            response = BRSOwnerPublicationMailbox.request(
                self._mailbox, request, check=lambda: _BRSWorkerTerminalEndpoint._wait_check(self, check),
            )
            handoff = BRSSelectedChildHandoff(**json.loads(self._handoff_bytes))
            gate = deliver_brs_owner_result(response, request, handoff,
                                           expected_native_plan_sha256=self._plan_sha256)
            with exchange.condition:
                if gate.delivery.publication_status == "all_rejected":
                    if (type(exchange.admission_offer) is not bytes
                            or self._admission_offer is not exchange.admission_offer
                            or exchange.admission_state != "received"
                            or self._admission_ack is not exchange.admission_ack):
                        _fail("admission_receipt_missing")
                elif (exchange.admission_offer is not None or exchange.admission_state != "unused"
                      or exchange.admission_ack is not None):
                    _fail("admission_drift")
            fields = ((request.run_id, request.episode_id, request.handoff_sha256,
                       request.payload, request.request_sha256),
                      (response.run_id, response.episode_id, response.handoff_sha256,
                       response.request_sha256, response.payload, response.response_sha256))
            self._exchange.submit(("delivery", *fields), check)

            def invoke(delivery):
                self._exchange.submit(("callback_started",), check)
                return callback(delivery)

            try:
                value = gate.settle(invoke)
            except BaseException:
                self._exchange.submit(("callback_finished", "unknown"), check)
                raise
            self._exchange.submit(("callback_finished", "returned"), check)
            self._status = "settled"
            return value
        except BaseException:
            self._status = "unknown"
            _PrimitiveExchange.fail(exchange)
            raise


class BRSOwnerTerminalLifecycle:
    """Ephemeral original session. Serialized records cannot reconstruct it."""

    __slots__ = (
        "_binding",
        "_endpoint",
        "_exchange",
        "_executor",
        "_future",
        "_head",
        "_history",
        "_mailbox",
        "_owner",
        "_poisoned",
        "_result",
        "_scope",
        "_started",
        "_thread",
    )

    @property
    def worker_endpoint(self) -> _BRSWorkerTerminalEndpoint:
        return self._endpoint

    def _fixed(self) -> None:
        from .rsi_brs_publication_lineage import _BRSLineageCheckpointOwner
        from .rsi_python_brs_native_dispatch import _original_control

        if type(self) is not BRSOwnerTerminalLifecycle or self._poisoned:
            _fail("session_unavailable")
        if (type(self._scope) is not tuple or len(self._scope) != 8
                or type(self._owner) is not _BRSLineageCheckpointOwner
                or type(self._mailbox) is not BRSOwnerPublicationMailbox
                or type(self._future) is not Future or type(self._executor) is not ThreadPoolExecutor
                or type(self._thread) is not threading.Thread
                or type(self._endpoint) is not _BRSWorkerTerminalEndpoint
                or type(self._exchange) is not _PrimitiveExchange
                or type(self._exchange.condition) is not threading.Condition
                or any(retained is not actual for retained, actual in zip(
                    self._scope, (self._owner, self._mailbox, self._future, self._executor,
                                  self._thread, self._endpoint, self._exchange, self._exchange.condition), strict=True))):
            _fail("session_drift")
        _original_control(self._owner)
        _BRSLineageCheckpointOwner._identity(self._owner)
        if (self._mailbox._owner_thread != self._owner._thread
                or self._mailbox._worker_thread != self._thread.ident
                or self._thread not in self._executor._threads
                or self._endpoint._mailbox is not self._mailbox or self._endpoint._exchange is not self._exchange
                or self._endpoint._worker_thread != self._thread.ident
                or self._endpoint._worker_object_id != id(self._thread)
                or self._endpoint._admission_channel is not self._owner._channel
                or self._endpoint._admission_condition is not self._owner._before_channel_condition
                or self._mailbox._terminal_lifecycle_opened is not True
                or self._executor._max_workers != 1):
            _fail("session_drift")

    def _append(self, stage: str, facts: dict) -> None:
        self._fixed()
        owner = self._owner
        namespace = brs_terminal_evidence_namespace(self._binding)
        record = build_brs_terminal_observation(
            self._binding, stage=stage, root_checkpoint_sha256=owner._head, facts=facts,
        )
        with owner._ledger.controller_lock(namespace):
            head = owner._ledger.append_brs_terminal_observation(self._binding, record, expected_sha256=self._head)
            history = owner._ledger.controller_checkpoint_history(namespace)
            if (history != [*self._history, (head, record)]
                    or owner._ledger.controller_checkpoint(owner._run_id) != (owner._head, owner._state)):
                _fail("readback_drift")
            self._fixed()
        self._head, self._history = head, history

    def _drain(self) -> bool:
        self._fixed()
        with self._exchange.condition:
            index = self._exchange.acked
            if (type(index) is not int or type(self._exchange.events) is not list
                    or not 0 <= index <= len(self._exchange.events) <= 3):
                _fail("observation_drift")
            if index == len(self._exchange.events):
                return False
            event = self._exchange.events[index]
        if (type(event) is not tuple or not event or type(event[0]) is not str
                or event[0] != STAGES[index]):
            _fail("observation_drift")
        stage = event[0]
        if stage == "delivery":
            if (len(event) != 3 or type(event[1]) is not tuple or len(event[1]) != 5
                    or type(event[2]) is not tuple or len(event[2]) != 6
                    or any(type(item) is not (bytes if position == payload else str)
                           for values, payload in ((event[1], 3), (event[2], 4))
                           for position, item in enumerate(values))):
                _fail("observation_drift")
            if self._result is None:
                _fail("delivery_unavailable")
            request, response = event[1:]
            transport = BRSOwnerPublicationMailbox._observation_snapshot(self._mailbox)
            if (transport != ("delivered", True, request, response)
                    or response[4] != self._result.response_payload):
                _fail("delivery_drift")
            transaction = self._result.transaction
            journal = (transaction.published_journal if transaction.publication_status == "published"
                       else transaction.terminal_journal)
            facts = {"request_fields": [*request[:3], request[3].decode("utf-8"), request[4]],
                     "response_fields": [*response[:4], response[4].decode("utf-8"), response[5]],
                     "publication": {"lineage": _clean(self._owner._state["producer_publication_lineage"]),
                                     "journal": journal.to_dict(),
                                     "manifest": (None if transaction.manifest is None
                                                  else transaction.manifest.to_dict())}}
        else:
            if ((stage == "callback_started" and len(event) != 1)
                    or (stage == "callback_finished" and (len(event) != 2
                        or type(event[1]) is not str or event[1] not in {"returned", "unknown"}))):
                _fail("observation_drift")
            facts = {"attempt": 1}
            if stage == "callback_finished":
                facts["outcome"] = event[1]
        self._append(stage, facts)
        with self._exchange.condition:
            if self._exchange.failed or self._exchange.acked != index or self._exchange.events[index] != event:
                _fail("observation_drift")
            self._exchange.acked += 1
            self._exchange.condition.notify_all()
        return True

    def _service_rejection_admission(self, *, timeout: float):
        """Offer original comparison bytes and consume the existing owner service once."""
        from .rsi_brs_publication_lineage import _BRSLineageCheckpointOwner

        self._fixed()
        owner, exchange = self._owner, self._exchange
        capture = owner._rejection_ready_capture
        if (self._started is not True or self._result is not None
                or owner._phase != "rejected-provenance" or type(capture) is not tuple
                or len(capture) != 6 or type(capture[5]) is not bytes
                or owner._rejection_ready_state != "unused"):
            _fail("admission_unavailable")
        payload = capture[5]
        try:
            with exchange.condition:
                if (exchange.failed or exchange.admission_state != "unused"
                        or exchange.admission_offer is not None or exchange.admission_ack is not None):
                    _fail("admission_unavailable")
                exchange.admission_offer, exchange.admission_state = payload, "offered"
                exchange.condition.notify_all()
            digest = _BRSLineageCheckpointOwner.service_rejection_ready(owner, timeout=timeout)
            self._fixed()
            if (owner._rejection_ready_capture is not capture or owner._rejection_ready_state != "committed"
                    or digest != capture[4][2]):
                _fail("admission_drift")
            with exchange.condition:
                if (exchange.failed or exchange.admission_offer is not payload
                        or type(exchange.admission_state) is not str
                        or exchange.admission_state not in {"requested", "received"}
                        or (exchange.admission_state == "received"
                            and exchange.admission_ack != owner._rejection_ready_ack_fields)):
                    _fail("admission_drift")
            return digest
        except BaseException:
            self._poisoned, owner._poisoned = True, True
            _PrimitiveExchange.fail(exchange)
            raise

    def serve(self, original_preparation, *, check, timeout: float = .05):
        """Run the old bridge, drain real worker events, and join the original executor."""
        from .rsi_python_brs_owner_bridge import run_brs_owner_publication_mailbox

        self._fixed()
        if self._started:
            _fail("session_unavailable")
        self._started = True
        owner, mailbox, _future, executor, _thread, _endpoint, exchange, _condition = self._scope
        try:
            self._result = run_brs_owner_publication_mailbox(
                self._owner, self._mailbox, original_preparation, check=check, timeout=timeout,
                _terminal_lifecycle=self,
            )
            value = {"protocol": BINDING_PROTOCOL,
                     "mailbox_binding": json.loads(self._owner._mailbox_binding_bytes),
                     "owner_thread_id": self._owner._thread, "worker_thread_id": self._thread.ident,
                     "future_id": f"future-{id(self._future):x}", "executor_id": f"executor-{id(self._executor):x}",
                     "thread_id": f"thread-{id(self._thread):x}"}
            value["binding_sha256"] = _digest(value, "binding_sha256")
            self._binding = parse_brs_terminal_binding(value)
            while not Future.done(self._future):
                check()
                if not self._drain():
                    with self._exchange.condition:
                        self._exchange.condition.wait(.05)
            while self._drain():
                pass
            BRSOwnerPublicationMailbox.close(self._mailbox)
            ThreadPoolExecutor.shutdown(self._executor, wait=True)
            if threading.Thread.is_alive(self._thread):
                _fail("worker_not_exited")
            if len(self._history) != 3:
                _fail("worker_observations_incomplete")
            outcome = "raised" if Future.exception(self._future) is not None else "returned"
            if outcome == "returned":
                from .rsi_controller import EpisodeExecution
                from .rsi_gateway import SolverRequest, SolverResult
                from .rsi_learning import PracticeEpisode
                from .rsi_store import RSILedger

                execution = Future.result(self._future)
                snapshot = RSILedger.read_brs_terminal_evidence_snapshot(
                    self._owner._ledger, self._owner._run_id, self._owner._request.episode_id,
                )
                saved, episodes, claim = snapshot["saved_result"], snapshot["episode_history"], snapshot["native_claim"]
                if (type(execution) is not EpisodeExecution or type(execution.request) is not SolverRequest
                        or type(execution.result) is not SolverResult or type(execution.episode) is not PracticeEpisode
                        or saved is None or not episodes or claim is None
                        or SolverRequest.to_dict(execution.request) != SolverRequest.to_dict(self._owner._request)
                        or SolverRequest.to_dict(execution.request) != SolverRequest.to_dict(saved[0])
                        or SolverResult.to_dict(execution.result) != SolverResult.to_dict(saved[1])
                        or PracticeEpisode.to_record_dict(execution.episode) != episodes[-1].payload
                        or execution.episode.status != execution.result.status
                        or claim.status != execution.result.status
                        or snapshot["pins"]["episode_record_sha256"] != episodes[-1].record_sha256
                        or snapshot["pins"]["native_claim_sha256"] != claim.claim_sha256
                        or snapshot["pins"]["result_sha256"] != hashlib.sha256(canonical_json(
                            SolverResult.to_dict(execution.result), maximum=128 * 1024)).hexdigest()):
                    _fail("worker_result_drift")
            self._append("worker_terminal", {"future_outcome": outcome,
                                              "executor_joined": True, "mailbox_closed": True, "worker_exited": True})
            if outcome == "raised":
                _fail("callback_unknown")
            return self._result
        except BaseException:
            self._poisoned = True
            owner._poisoned = True
            _PrimitiveExchange.fail(exchange)
            BRSOwnerPublicationMailbox.close(mailbox)
            ThreadPoolExecutor.shutdown(executor, wait=False)
            raise


def open_brs_terminal_lifecycle(owner: object, mailbox: object, *, future: object, executor: object):
    """Bind the one live original owner; workers receive no owner/ledger reference."""
    from .rsi_brs_publication_lineage import _BRSLineageCheckpointOwner
    from .rsi_python_brs_native_dispatch import _fixed_original_brs_owner
    from .rsi_python_brs_owner_bridge import _require_original_mailbox

    _fixed_original_brs_owner(owner)
    if (type(mailbox) is not BRSOwnerPublicationMailbox or type(future) is not Future
            or type(executor) is not ThreadPoolExecutor or executor._max_workers != 1
            or not Future.running(future) or executor._shutdown):
        _fail("session_invalid")
    _require_original_mailbox(owner, mailbox)
    if getattr(mailbox, "_terminal_lifecycle_opened", False) is not False:
        _fail("session_unavailable")
    threads = [thread for thread in executor._threads
               if type(thread) is threading.Thread and thread.ident == mailbox._worker_thread]
    if len(threads) != 1 or not threading.Thread.is_alive(threads[0]):
        _fail("worker_invalid")
    if type(owner) is not _BRSLineageCheckpointOwner:
        _fail("owner_invalid")
    session = BRSOwnerTerminalLifecycle.__new__(BRSOwnerTerminalLifecycle)
    session._owner, session._mailbox, session._future, session._executor = owner, mailbox, future, executor
    session._thread, session._exchange = threads[0], _PrimitiveExchange(owner._before_control.deadline)
    session._endpoint = _BRSWorkerTerminalEndpoint(
        mailbox, session._exchange, owner._handoff_bytes, owner._plan.plan_sha256,
        mailbox._worker_thread, id(threads[0]),
        owner._channel,
    )
    session._binding, session._head, session._history = None, None, []
    session._started, session._poisoned, session._result = False, False, None
    session._scope = (owner, mailbox, future, executor, threads[0], session._endpoint,
                      session._exchange, session._exchange.condition)
    mailbox._terminal_lifecycle_opened = True
    return session
