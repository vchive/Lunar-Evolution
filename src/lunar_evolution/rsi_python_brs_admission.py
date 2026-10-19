"""Bounded in-process prepared-evidence messages for a single original BRS wave.

This channel neither reads evidence nor grants launch or evaluation authority. Workers
submit immutable canonical bytes; only the configured owner runs the durable handler.
Cancellation never undoes a handler which has already started.
"""

from __future__ import annotations

import _thread
import builtins
import dataclasses
import hashlib
import json
import math
import re
import sys
import threading
import time
import types
from collections import deque
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from typing import NoReturn

from .rsi_learning import RSILearningError
from .rsi_python_brs_child_policy import BRSNativeChildPreflight
from .rsi_python_brs_handoff import (
    BRSChildHandoffContext,
    BRSSelectedChildHandoff,
    validate_brs_child_handoff,
)

MAX_BRS_ADMISSION_BYTES = 8 * 1024 * 1024
_POLL_SECONDS = 0.05
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_PAYLOAD_FIELDS = {"native_plan", "prepared_journal", "expected_anchor_sha256"}


class RSIPythonBRSAdmissionError(RSILearningError):
    """A fixed-code refusal containing no worker prose or filesystem paths."""

    def __init__(self, code: str) -> None:
        super().__init__("rsi_python_brs_admission_" + code)


def _fail(code: str) -> NoReturn:
    raise RSIPythonBRSAdmissionError(code)


def _identity(value: object) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        _fail("identity_invalid")
    return value


def _sha(value: object) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None or value == "0" * 64:
        _fail("digest_invalid")
    return value


def _json_shape(value: object, depth: int = 0) -> None:
    if depth > 48:
        _fail("shape_invalid")
    kind = type(value)
    if value is None or kind in {str, int, bool}:
        return
    if kind is float and math.isfinite(value):
        return
    if kind is dict:
        if any(type(key) is not str for key in value):
            _fail("shape_invalid")
        children = value.values()
    elif kind is list:
        children = value
    else:
        _fail("shape_invalid")
    for child in children:
        _json_shape(child, depth + 1)


def _payload(raw: object) -> bytes:
    if type(raw) is not bytes:
        _fail("payload_invalid")
    if len(raw) > MAX_BRS_ADMISSION_BYTES:
        _fail("payload_too_large")

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in items:
            if key in result:
                _fail("duplicate_json_key")
            result[key] = item
        return result

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                           parse_constant=lambda _value: _fail("payload_invalid"))
        _json_shape(value)
        if (type(value) is not dict or set(value) != _PAYLOAD_FIELDS
                or type(value["native_plan"]) is not dict
                or type(value["prepared_journal"]) is not dict):
            _fail("payload_shape_invalid")
        _sha(value["expected_anchor_sha256"])
        canonical = json.dumps(value, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (UnicodeError, TypeError, ValueError, OverflowError, RecursionError) as exc:
        if isinstance(exc, RSIPythonBRSAdmissionError):
            raise
        raise RSIPythonBRSAdmissionError("payload_invalid") from exc
    if canonical != raw:
        _fail("payload_noncanonical")
    return raw


def _request_digest(run_id: str, episode_id: str, payload: bytes) -> str:
    # IDs cannot contain NUL, so this domain-separated framing is unambiguous.
    return hashlib.sha256(b"lunar-rsi-python-brs-ready-v1\0" + run_id.encode("utf-8")
                          + b"\0" + episode_id.encode("utf-8") + b"\0" + payload).hexdigest()


@dataclass(frozen=True, slots=True)
class BRSAdmissionReady:
    run_id: str
    episode_id: str
    payload: bytes
    request_sha256: str

    def __post_init__(self) -> None:
        _identity(self.run_id)
        _identity(self.episode_id)
        _payload(self.payload)
        if _sha(self.request_sha256) != _request_digest(self.run_id, self.episode_id, self.payload):
            _fail("request_digest_mismatch")


@dataclass(frozen=True, slots=True)
class BRSAdmissionAck:
    run_id: str
    episode_id: str
    request_sha256: str
    record_sha256: str

    def __post_init__(self) -> None:
        _identity(self.run_id)
        _identity(self.episode_id)
        _sha(self.request_sha256)
        _sha(self.record_sha256)


def build_brs_admission_ready(run_id: str, episode_id: str, payload: bytes) -> BRSAdmissionReady:
    _identity(run_id)
    _identity(episode_id)
    _payload(payload)
    return BRSAdmissionReady(run_id, episode_id, payload,
                             _request_digest(run_id, episode_id, payload))


@dataclass(eq=False, slots=True)
class _Pending:
    ready: BRSAdmissionReady
    state: str = "queued"
    binding_sha256: str | None = None
    ack: BRSAdmissionAck | None = None
    ack_fields: tuple[str, str, str, str] | None = None
    error: str | None = None
    cancelled: bool = False


class BRSAdmissionChannel:
    """One request per dispatched episode, serviced exclusively by the owner thread.

    ``check`` is the original worker budget/control check and may raise to cancel a
    wait. Neither callback runs under the condition lock. The owner must close this
    channel before waiting for executor shutdown, including on handler failure.
    """

    def __init__(self, run_id: str, episode_ids: tuple[str, ...] | list[str], *,
                 owner_thread: int | None = None) -> None:
        self._run_id = _identity(run_id)
        if type(episode_ids) not in {tuple, list} or not episode_ids:
            _fail("wave_invalid")
        for episode_id in episode_ids:
            _identity(episode_id)
        if len(set(episode_ids)) != len(episode_ids):
            _fail("wave_invalid")
        if owner_thread is None:
            owner_thread = threading.get_ident()
        if type(owner_thread) is not int or owner_thread <= 0:
            _fail("owner_invalid")
        self._episode_ids = frozenset(episode_ids)
        self._owner_thread = owner_thread
        self._condition = threading.Condition()
        self._queue: deque[_Pending] = deque()
        self._requests: dict[str, _Pending] = {}
        self._closed = False
        self._servicing = False
        self._handoff_mode = False
        self._selected_episode_id: str | None = None
        self._selected_handoff_sha256: str | None = None
        self._consumed_handoff_nonces: set[str] = set()
        self._completed_selected_episodes: set[str] = set()
        # The staged owner enables this once under the original condition. It
        # remains set after commit/failure; it is a worker guard, not a permit.
        self._rejection_ready_worker_guarded = False

    def _available(self, ready: BRSAdmissionReady) -> None:
        if self._closed:
            _fail("closed")
        if ready.run_id != self._run_id or ready.episode_id not in self._episode_ids:
            _fail("wave_mismatch")
        if self._handoff_mode:
            if self._selected_episode_id is None:
                _fail("no_selected_child")
            if ready.episode_id != self._selected_episode_id:
                _fail("selected_episode_mismatch")
        if ready.episode_id in self._requests:
            _fail("duplicate_request")

    def bind_selected_handoff(
        self,
        handoff: BRSSelectedChildHandoff,
        preflight: BRSNativeChildPreflight,
        current: BRSChildHandoffContext,
    ) -> str:
        """Atomically consume one nonce and bind the next selected ordinal.

        This method is owner-thread-only. The channel condition protects nonce
        consumption and selected-episode binding as one in-memory transition; the
        caller remains responsible for invoking it from its controller-owner scope.
        """
        if threading.get_ident() != self._owner_thread:
            _fail("handoff_owner_required")
        if (type(handoff) is not BRSSelectedChildHandoff
                or type(preflight) is not BRSNativeChildPreflight
                or type(current) is not BRSChildHandoffContext):
            _fail("handoff_invalid")
        with self._condition:
            if self._closed:
                _fail("closed")
            if (self._selected_episode_id is not None or self._servicing or self._queue
                    or any(
                        episode_id not in self._completed_selected_episodes
                        or pending.state != "done" or pending.ack is None
                        for episode_id, pending in self._requests.items()
                    )):
                _fail("handoff_busy")
            # Snapshot before validation. The caller may retain and mutate a frozen
            # DTO with object.__setattr__; every gate and state transition must use
            # the same strict primitive-only value.
            detached_handoff = BRSSelectedChildHandoff(**handoff.to_dict())
            nonce_digest = validate_brs_child_handoff(
                detached_handoff, preflight, current,
                consumed_nonces=tuple(self._consumed_handoff_nonces),
            )
            if (detached_handoff.episode_id in self._completed_selected_episodes
                    or detached_handoff.episode_id in self._requests):
                _fail("handoff_episode_replayed")
            if (detached_handoff.run_id != self._run_id
                    or detached_handoff.episode_id not in self._episode_ids):
                _fail("wave_mismatch")
            self._consumed_handoff_nonces.add(detached_handoff.lease_nonce)
            self._selected_episode_id = detached_handoff.episode_id
            self._selected_handoff_sha256 = nonce_digest
            self._handoff_mode = True
            return nonce_digest

    def complete_selected_handoff(self, episode_id: str) -> None:
        """Retire an acknowledged binding; caller must first observe its future outcome."""
        if threading.get_ident() != self._owner_thread:
            _fail("handoff_owner_required")
        if type(episode_id) is not str:
            _fail("handoff_episode_invalid")
        with self._condition:
            if self._closed:
                _fail("closed")
            if self._selected_episode_id != episode_id:
                _fail("selected_episode_mismatch")
            if (type(self._requests) is not dict
                    or any(type(key) is not str for key in self._requests)):
                _fail("ack_invalid")
            pending = self._requests.get(episode_id)
            if (type(pending) is not _Pending
                    or type(pending.state) is not str or pending.state != "done"
                    or pending.ack is None
                    or type(pending.cancelled) is not bool or pending.cancelled
                    or (pending.error is not None and type(pending.error) is not str)
                    or pending.error is not None
                    or (pending.binding_sha256 is not None and type(pending.binding_sha256) is not str)
                    or pending.binding_sha256 != self._selected_handoff_sha256
                    or type(self._servicing) is not bool or self._servicing
                    or type(self._queue) is not deque or self._queue):
                _fail("handoff_not_acknowledged")
            if type(pending.ready) is not BRSAdmissionReady:
                _fail("ack_invalid")
            ready = pending.ready
            if (type(ready.run_id) is not str or ready.run_id != self._run_id
                    or type(ready.episode_id) is not str or ready.episode_id != episode_id
                    or type(ready.request_sha256) is not str):
                _fail("ack_mismatch")
            if type(pending.ack) is not BRSAdmissionAck:
                _fail("ack_invalid")
            ack = BRSAdmissionAck(pending.ack.run_id, pending.ack.episode_id,
                                  pending.ack.request_sha256, pending.ack.record_sha256)
            fields = (ack.run_id, ack.episode_id, ack.request_sha256, ack.record_sha256)
            if (type(pending.ack_fields) is not tuple or len(pending.ack_fields) != 4
                    or any(type(value) is not str for value in pending.ack_fields)
                    or fields != pending.ack_fields
                    or fields[:3] != (ready.run_id, ready.episode_id, ready.request_sha256)):
                _fail("ack_mismatch")
            self._completed_selected_episodes.add(episode_id)
            self._selected_episode_id = None
            self._selected_handoff_sha256 = None
            self._condition.notify_all()

    def assert_selected_handoff_acknowledged(self, episode_id: str) -> tuple[str, str, str, str]:
        """Check the selected request's retained ACK without retiring the binding.

        The owner uses this immediately before accepting a worker result.  It is a
        read-only channel check: it does not mark the handoff complete, refresh any
        identity, or grant publication authority.
        """
        if threading.get_ident() != self._owner_thread:
            _fail("handoff_owner_required")
        if type(episode_id) is not str:
            _fail("handoff_episode_invalid")
        with self._condition:
            if self._closed:
                _fail("closed")
            if self._selected_episode_id != episode_id:
                _fail("selected_episode_mismatch")
            if (type(self._requests) is not dict
                    or any(type(key) is not str for key in self._requests)):
                _fail("ack_invalid")
            pending = self._requests.get(episode_id)
            if (type(pending) is not _Pending
                    or type(pending.state) is not str or pending.state != "done"
                    or pending.ack is None
                    or type(pending.cancelled) is not bool or pending.cancelled
                    or (pending.error is not None and type(pending.error) is not str)
                    or pending.error is not None
                    or (pending.binding_sha256 is not None and type(pending.binding_sha256) is not str)
                    or pending.binding_sha256 != self._selected_handoff_sha256
                    or type(self._servicing) is not bool or self._servicing
                    or type(self._queue) is not deque or self._queue):
                _fail("handoff_not_acknowledged")
            if type(pending.ready) is not BRSAdmissionReady:
                _fail("ack_invalid")
            ready = pending.ready
            if (type(ready.run_id) is not str or ready.run_id != self._run_id
                    or type(ready.episode_id) is not str or ready.episode_id != episode_id
                    or type(ready.request_sha256) is not str):
                _fail("ack_mismatch")
            if type(pending.ack) is not BRSAdmissionAck:
                _fail("ack_invalid")
            ack = BRSAdmissionAck(pending.ack.run_id, pending.ack.episode_id,
                                  pending.ack.request_sha256, pending.ack.record_sha256)
            fields = (ack.run_id, ack.episode_id, ack.request_sha256, ack.record_sha256)
            if (type(pending.ack_fields) is not tuple or len(pending.ack_fields) != 4
                    or any(type(value) is not str for value in pending.ack_fields)
                    or fields != pending.ack_fields
                    or fields[:3] != (ready.run_id, ready.episode_id, ready.request_sha256)):
                _fail("ack_mismatch")
            return fields

    def request(self, ready: BRSAdmissionReady, *, check: Callable[[], None]) -> BRSAdmissionAck:
        worker_guard_pin = _REJECTION_READY_WORKER_ACK_PIN
        native_type, native_len, native_any, native_zip = type, len, any, zip
        native_bool, native_str, native_dict, native_value_error = bool, str, dict, ValueError
        native_base_exception = BaseException
        native_error, native_error_new = RSILearningError, BaseException.__new__
        # Retain refusal operations before the first external budget callback.
        # A changed Pending declaration must not intercept guarded cleanup.
        native_member_get, native_member_set = types.MemberDescriptorType.__get__, types.MemberDescriptorType.__set__
        native_dictionary_get, native_dictionary_set = types.GetSetDescriptorType.__get__, dict.__setitem__
        original_pending_type = _Pending
        pending_members = vars(original_pending_type)
        cancelled_slot, error_slot = pending_members["cancelled"], pending_members["error"]
        original_namespace = native_dictionary_get(vars(BRSAdmissionChannel)["__dict__"], self, BRSAdmissionChannel)
        original_condition = original_namespace["_condition"]
        condition_namespace = object.__getattribute__(original_condition, "__dict__")
        original_lock, original_waiters = condition_namespace["_lock"], condition_namespace["_waiters"]
        native_waiter_type, native_waiter_release = _thread.LockType, vars(_thread.LockType)["release"]
        native_queue_pop, native_runtime_error = deque.popleft, RuntimeError
        worker_guarded = self._rejection_ready_worker_guarded
        if native_type(worker_guarded) is not native_bool:
            raise native_error_new(native_error, "rsi_brs_rejection_ready_worker_scope_invalid")

        def preserve_guarded_failure(pending):
            # Keep exactly the published prefix; close and wake using only held
            # slots, the original dictionary/native lock and original waiters.
            with original_lock:
                native_member_set(cancelled_slot, pending, True)
                if native_member_get(error_slot, pending, original_pending_type) is None:
                    native_member_set(error_slot, pending, "worker_refused")
                if not native_any(native_type(key) is not native_str for key in original_namespace):
                    native_dictionary_set(original_namespace, "_closed", True)
                    native_dictionary_set(original_namespace, "_servicing", False)
                if (native_len(original_waiters) > 4096
                        or native_any(native_type(waiter) is not native_waiter_type for waiter in original_waiters)):
                    return
                while original_waiters:
                    waiter = native_queue_pop(original_waiters)
                    try:
                        native_waiter_release(waiter)
                    except native_runtime_error:
                        pass
        if type(ready) is not BRSAdmissionReady:
            _fail("ready_invalid")
        ready.__post_init__()
        if threading.get_ident() == self._owner_thread:
            _fail("request_on_owner")
        if not callable(check):
            _fail("check_invalid")
        # Detach from caller-held DTOs, including frozen objects mutated via object.__setattr__.
        detached = build_brs_admission_ready(ready.run_id, ready.episode_id, ready.payload)
        with self._condition:
            self._available(detached)
        check()
        with self._condition:
            self._available(detached)
            enqueued_guarded = self._rejection_ready_worker_guarded
            if (native_type(enqueued_guarded) is not native_bool
                    or worker_guarded and enqueued_guarded is not True):
                raise native_error_new(native_error, "rsi_brs_rejection_ready_worker_scope_invalid")
            # The first callback may overlap owner arming while the queue is
            # still empty. Retain the enabled scope at the actual enqueue.
            worker_guarded = enqueued_guarded
            pending = _Pending(
                detached,
                binding_sha256=self._selected_handoff_sha256 if self._handoff_mode else None,
            )
            self._requests[detached.episode_id] = pending
            self._queue.append(pending)
            self._condition.notify_all()
        try:
            while True:
                check()
                with self._condition:
                    if pending.error is not None:
                        _fail(pending.error)
                    if pending.ack is not None:
                        guarded = self._rejection_ready_worker_guarded
                        if (native_type(guarded) is not native_bool
                                or worker_guarded and guarded is not True):
                            raise native_error_new(native_error, "rsi_brs_rejection_ready_worker_scope_invalid")
                        if guarded:
                            worker_guarded = True
                            # check() runs outside the condition and may change
                            # constructor/helper code. Validate the original
                            # import-time guard itself before calling it.
                            (guard, code, namespace, domain, defaults, kwdefaults, kwitems,
                             closure, captures, attributes, attritems, annotations, annotationitems,
                             name, qualname, module, doc) = worker_guard_pin
                            if (guard.__code__ is not code or guard.__globals__ is not namespace
                                    or guard.__builtins__ is not domain or guard.__defaults__ is not defaults
                                    or guard.__kwdefaults__ is not kwdefaults or guard.__closure__ is not closure
                                    or guard.__dict__ is not attributes or guard.__annotations__ is not annotations):
                                raise native_error_new(native_error, "rsi_brs_rejection_ready_worker_guard_drift")
                            for mapping, entries in ((kwdefaults, kwitems), (attributes, attritems),
                                                     (annotations, annotationitems)):
                                if mapping is None:
                                    continue
                                if (native_type(mapping) is not native_dict or native_len(mapping) != native_len(entries)
                                        or native_any(native_type(key) is not native_str for key in mapping)
                                        or native_any(mapping.get(key) is not value for key, value in entries)):
                                    raise native_error_new(native_error, "rsi_brs_rejection_ready_worker_guard_drift")
                            for cell, value in native_zip(closure or (), captures):
                                try:
                                    if cell.cell_contents is not value:
                                        raise native_error_new(native_error, "rsi_brs_rejection_ready_worker_guard_drift")
                                except native_value_error:
                                    raise native_error_new(native_error, "rsi_brs_rejection_ready_worker_guard_drift") from None
                            for value, original in ((guard.__name__, name), (guard.__qualname__, qualname),
                                                    (guard.__module__, module), (guard.__doc__, doc)):
                                if native_type(value) is not native_type(original) or value != original:
                                    raise native_error_new(native_error, "rsi_brs_rejection_ready_worker_guard_drift")
                            guard()
                            # An ACK object alone is only a published prefix.
                            # Require the complete original transport commit
                            # before constructing a caller-visible copy.
                            if (native_type(pending) is not _Pending
                                    or native_type(pending.state) is not native_str or pending.state != "done"
                                    or self._servicing is not False or self._closed is not False
                                    or pending.cancelled is not False
                                    or native_type(pending.ack_fields) is not tuple
                                    or native_len(pending.ack_fields) != 4
                                    or native_any(native_type(value) is not native_str for value in pending.ack_fields)
                                    or native_type(pending.ack) is not BRSAdmissionAck
                                    or pending.ack_fields != (
                                        pending.ack.run_id, pending.ack.episode_id,
                                        pending.ack.request_sha256, pending.ack.record_sha256)):
                                raise native_error_new(native_error, "rsi_brs_rejection_ready_worker_commit_incomplete")
                        if type(pending.ack) is not BRSAdmissionAck:
                            _fail("ack_invalid")
                        # Retain the owner ACK separately from the caller's return
                        # value; frozen DTOs can still be mutated with object.__setattr__.
                        ack = BRSAdmissionAck(pending.ack.run_id, pending.ack.episode_id,
                                              pending.ack.request_sha256, pending.ack.record_sha256)
                        if (ack.run_id, ack.episode_id, ack.request_sha256) != (
                                detached.run_id, detached.episode_id, detached.request_sha256):
                            _fail("ack_mismatch")
                        return ack
                    if self._closed:
                        _fail("closed")
                    self._condition.wait(_POLL_SECONDS)
        except native_base_exception:
            if worker_guarded:
                preserve_guarded_failure(pending)
                raise
            with self._condition:
                pending.cancelled = True
                if pending.state == "queued":
                    self._queue.remove(pending)
                    pending.state = "cancelled"
                self._condition.notify_all()
            raise

    def _service_selected_rejection_ready(self, owner, *, timeout: float) -> str:
        """Delegate one original-owner staged scope; no caller handler or ACK."""
        from .rsi_brs_publication_lineage import _BRSLineageCheckpointOwner

        if (type(self) is not BRSAdmissionChannel or type(owner) is not _BRSLineageCheckpointOwner
                or owner._channel is not self or type(self._owner_thread) is not int
                or type(owner._thread) is not int or owner._thread != self._owner_thread
                or threading.get_ident() != self._owner_thread):
            _fail("service_owner_required")
        from .rsi_brs_rejection_ready_service import service_rejection_ready

        return service_rejection_ready(owner, timeout=timeout)

    def service(self, handler: Callable[[BRSAdmissionReady], str], *, timeout: float = 0.05,
                observation_scope: Callable[[], AbstractContextManager[None]] | None = None) -> bool:
        if threading.get_ident() != self._owner_thread:
            _fail("service_owner_required")
        if not callable(handler):
            _fail("handler_invalid")
        if observation_scope is not None and not callable(observation_scope):
            _fail("observation_scope_invalid")
        if (type(timeout) not in {int, float} or timeout < 0 or timeout > 60
                or not math.isfinite(timeout)):
            _fail("timeout_invalid")
        deadline = time.monotonic() + timeout
        with self._condition:
            if self._servicing:
                _fail("service_reentrant")
            while not self._queue:
                remaining = deadline - time.monotonic()
                if self._closed or remaining <= 0:
                    return False
                self._condition.wait(remaining)
            pending = self._queue.popleft()
            pending.state = "inflight"
            self._servicing = True
        ready = pending.ready
        original = (ready.run_id, ready.episode_id, ready.payload, ready.request_sha256)
        try:
            # Trusted owner scope keeps atomic pin, precise in-memory acknowledgement
            # and dispatch under one observation lock. The queue wait never holds it.
            with observation_scope() if observation_scope is not None else nullcontext():
                ready.__post_init__()
                record_sha256 = handler(ready)
                ready.__post_init__()
                if (ready.run_id, ready.episode_id, ready.payload, ready.request_sha256) != original:
                    _fail("request_mutated")
                ack = BRSAdmissionAck(ready.run_id, ready.episode_id,
                                      ready.request_sha256, record_sha256)
                with self._condition:
                    pending.state = "done"
                    ack_failed = pending.cancelled or pending.error is not None or self._closed
                    if not ack_failed:
                        pending.ack = ack
                        pending.ack_fields = (ack.run_id, ack.episode_id,
                                              ack.request_sha256, ack.record_sha256)
                    else:
                        pending.error = pending.error or "ack_invalid"
                    self._condition.notify_all()
                if ack_failed:
                    # Raise before leaving the owner scope so the owner can restore
                    # its old in-memory head while retaining the durable obligation.
                    _fail("ack_invalid")
        except BaseException:
            with self._condition:
                pending.state = "done"
                pending.error = pending.error or "handler_failed"
                pending.ack = None
                self._servicing = False
                self._condition.notify_all()
            raise
        with self._condition:
            self._servicing = False
            self._condition.notify_all()
        return True

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._queue.clear()
            for pending in self._requests.values():
                if pending.ack is None:
                    pending.error = pending.error or "closed"
                    if pending.state == "queued":
                        pending.state = "cancelled"
            self._condition.notify_all()


def _build_rejection_ready_worker_ack_guard():
    """Hold the worker's original ACK graph before any staged callback runs."""
    kind, length, namespace_of, some, pairs = type, len, vars, any, zip
    plain_dict, plain_str = dict, str
    function_type, module_type = types.FunctionType, types.ModuleType
    value_error = ValueError
    error_type, error_new = RSILearningError, BaseException.__new__
    own_namespace, builtin_namespace, registry = globals(), vars(builtins), sys.modules
    prefix, missing, max_keys = "rsi_brs_rejection_ready_worker_ack_graph_drift", object(), 16384
    ack_type, error_class = BRSAdmissionAck, RSIPythonBRSAdmissionError
    classes = (ack_type, _Pending, BRSAdmissionChannel, error_class, error_type, dataclasses.Field)
    class_pins = tuple((declared, declared.__bases__, declared.__mro__, tuple(vars(declared).items()))
                       for declared in classes)
    fields = vars(ack_type)["__dataclass_fields__"]
    field_type = dataclasses.Field
    member_get = types.MemberDescriptorType.__get__
    field_slots = tuple(vars(field_type)[name] for name in field_type.__slots__)
    field_pins = tuple((name, field, tuple((descriptor, member_get(descriptor, field, field_type))
                                          for descriptor in field_slots), tuple(field.metadata.items()))
                       for name, field in fields.items())
    parameters = vars(ack_type)["__dataclass_params__"]
    parameter_type = kind(parameters)
    parameter_pins = tuple((vars(parameter_type)[name], member_get(vars(parameter_type)[name],
                                                                 parameters, parameter_type))
                           for name in parameter_type.__slots__)
    metadata_descriptor = vars(field_type)["metadata"]
    patterns = tuple((pattern, pattern.pattern, pattern.flags) for pattern in (_ID, _SHA))

    def pack(function):
        return (function, function.__code__, function.__globals__, function.__builtins__,
                function.__defaults__, function.__kwdefaults__, tuple((function.__kwdefaults__ or {}).items()),
                function.__closure__, tuple(cell.cell_contents for cell in (function.__closure__ or ())),
                function.__dict__, tuple(function.__dict__.items()), function.__annotations__,
                tuple(function.__annotations__.items()), function.__name__, function.__qualname__,
                function.__module__, function.__doc__)

    pins = tuple(pack(function) for function in (
        ack_type.__init__, ack_type.__post_init__, _identity, _sha, _fail,
        error_class.__init__, error_type.__init__, BRSAdmissionChannel.request))
    builtin_names = ("type", "len", "vars", "any", "zip", "dict", "str", "tuple", "set", "object",
                     "super", "ValueError", "BaseException", "AttributeError", "isinstance", "callable",
                     "bool", "bytes", "int", "float")
    builtin_pins = tuple((name, builtin_namespace[name]) for name in builtin_names)
    learning_module = registry[error_type.__module__]
    own_module = registry[__name__]
    modules = tuple((module, vars(module)) for module in (
        own_module, learning_module, _thread, builtins, dataclasses, re, sys, types))
    registered = tuple((module.__name__, module) for module, _namespace in modules)
    aliases = tuple((name, own_namespace[name]) for name in (
        "BRSAdmissionAck", "RSIPythonBRSAdmissionError", "RSILearningError", "_identity", "_sha", "_fail",
        "_ID", "_SHA", "_Pending", "BRSAdmissionChannel", "_thread", "builtins", "dataclasses", "re", "sys", "types"))
    native_pins = (
        (object, "__new__", object.__new__), (object, "__setattr__", object.__setattr__),
        (object, "__getattribute__", object.__getattribute__), (type, "__call__", type.__call__),
        (type, "__getattribute__", type.__getattribute__),
        (types.MemberDescriptorType, "__get__", member_get),
        (types.CellType, "cell_contents", vars(types.CellType)["cell_contents"]),
        (re.Pattern, "fullmatch", vars(re.Pattern)["fullmatch"]),
        (re.Pattern, "pattern", vars(re.Pattern)["pattern"]),
        (re.Pattern, "flags", vars(re.Pattern)["flags"]),
    )

    def guard():
        if (length(own_namespace) > max_keys
                or some(kind(key) is not plain_str for key in own_namespace)):
            raise error_new(error_type, prefix)
        for name, original in aliases:
            if own_namespace.get(name, missing) is not original:
                raise error_new(error_type, prefix)
        if own_namespace.get("_assert_rejection_ready_worker_ack_graph", missing) is not guard:
            raise error_new(error_type, prefix)
        for module, namespace in modules:
            if (kind(module) is not module_type or namespace_of(module) is not namespace
                    or length(namespace) > max_keys or some(kind(key) is not plain_str for key in namespace)):
                raise error_new(error_type, prefix)
        if (namespace_of(sys).get("modules", missing) is not registry or kind(registry) is not plain_dict
                or length(registry) > max_keys or some(kind(key) is not plain_str for key in registry)):
            raise error_new(error_type, prefix)
        for name, module in registered:
            if registry.get(name, missing) is not module:
                raise error_new(error_type, prefix)
        for name, original in builtin_pins:
            if builtin_namespace.get(name, missing) is not original:
                raise error_new(error_type, prefix)
        for declaration, name, original in native_pins:
            if namespace_of(declaration).get(name, missing) is not original:
                raise error_new(error_type, prefix)
        for declared, bases, mro, members in class_pins:
            current = namespace_of(declared)
            if (declared.__bases__ is not bases or declared.__mro__ is not mro
                    or length(current) != length(members)
                    or some(kind(key) is not plain_str for key in current)):
                raise error_new(error_type, prefix)
            for name, original in members:
                if current.get(name, missing) is not original:
                    raise error_new(error_type, prefix)
        for pin in pins:
            (function, code, namespace, domain, defaults, kwdefaults, kwitems, closure, captures,
             attributes, attritems, annotations, annotationitems, name, qualname, module, doc) = pin
            if (kind(function) is not function_type or function.__code__ is not code
                    or function.__globals__ is not namespace or function.__builtins__ is not domain
                    or function.__defaults__ is not defaults or function.__kwdefaults__ is not kwdefaults
                    or function.__closure__ is not closure or function.__dict__ is not attributes
                    or function.__annotations__ is not annotations
                    or kind(domain) is not plain_dict or length(domain) > max_keys
                    or some(kind(key) is not plain_str for key in domain)):
                raise error_new(error_type, prefix)
            for field, original in builtin_pins:
                if namespace.get(field, original) is not original or domain.get(field, missing) is not original:
                    raise error_new(error_type, prefix)
            for mapping, entries in ((kwdefaults, kwitems), (attributes, attritems),
                                     (annotations, annotationitems)):
                if mapping is None:
                    continue
                if (kind(mapping) is not plain_dict or length(mapping) != length(entries)
                        or some(kind(key) is not plain_str for key in mapping)):
                    raise error_new(error_type, prefix)
                for field, original in entries:
                    if mapping.get(field, missing) is not original:
                        raise error_new(error_type, prefix)
            for cell, original in pairs(closure or (), captures):
                try:
                    if cell.cell_contents is not original:
                        raise error_new(error_type, prefix)
                except value_error:
                    raise error_new(error_type, prefix) from None
            for value, original in ((function.__name__, name), (function.__qualname__, qualname),
                                    (function.__module__, module), (function.__doc__, doc)):
                if kind(value) is not kind(original) or value != original:
                    raise error_new(error_type, prefix)
        if (kind(fields) is not plain_dict or length(fields) != length(field_pins)
                or some(kind(key) is not plain_str for key in fields)):
            raise error_new(error_type, prefix)
        for name, field, values, metadata in field_pins:
            if fields.get(name, missing) is not field or kind(field) is not field_type:
                raise error_new(error_type, prefix)
            for descriptor, original in values:
                if member_get(descriptor, field, field_type) is not original:
                    raise error_new(error_type, prefix)
            current = member_get(metadata_descriptor, field, field_type)
            if (length(current) != length(metadata) or some(kind(key) is not plain_str for key in current)):
                raise error_new(error_type, prefix)
            for key, original in metadata:
                if current.get(key, missing) is not original:
                    raise error_new(error_type, prefix)
        for descriptor, original in parameter_pins:
            if member_get(descriptor, parameters, parameter_type) is not original:
                raise error_new(error_type, prefix)
        for pattern, text, flags in patterns:
            if pattern.pattern != text or pattern.flags != flags:
                raise error_new(error_type, prefix)

    return guard, pack(guard)


(_assert_rejection_ready_worker_ack_graph,
 _REJECTION_READY_WORKER_ACK_PIN) = _build_rejection_ready_worker_ack_guard()
