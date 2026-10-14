"""Bounded in-process prepared-evidence messages for a single original BRS wave.

This channel neither reads evidence nor grants launch or evaluation authority. Workers
submit immutable canonical bytes; only the configured owner runs the durable handler.
Cancellation never undoes a handler which has already started.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import time
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
            pending = self._requests.get(episode_id)
            if (pending is None or pending.state != "done" or pending.ack is None
                    or pending.cancelled or pending.error is not None
                    or pending.binding_sha256 != self._selected_handoff_sha256
                    or self._servicing or self._queue):
                _fail("handoff_not_acknowledged")
            self._completed_selected_episodes.add(episode_id)
            self._selected_episode_id = None
            self._selected_handoff_sha256 = None
            self._condition.notify_all()

    def request(self, ready: BRSAdmissionReady, *, check: Callable[[], None]) -> BRSAdmissionAck:
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
                        ack = pending.ack
                        ack.__post_init__()
                        if (ack.run_id, ack.episode_id, ack.request_sha256) != (
                                detached.run_id, detached.episode_id, detached.request_sha256):
                            _fail("ack_mismatch")
                        return ack
                    if self._closed:
                        _fail("closed")
                    self._condition.wait(_POLL_SECONDS)
        except BaseException:
            with self._condition:
                pending.cancelled = True
                if pending.state == "queued":
                    self._queue.remove(pending)
                    pending.state = "cancelled"
                self._condition.notify_all()
            raise

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
