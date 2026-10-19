"""Passive comparison data for one selected queued ready message.

Nothing here arms or consumes a scope, moves a request, grants an owner, validates
admission semantics, or constructs/publishes an ACK. The caller independently owns
its original scope; a matching capsule is comparison data, never a permit. No DTO
serializer or caller callback runs while the held native condition lock is acquired.
"""

from __future__ import annotations

import re
from collections import deque
from threading import get_ident
from types import GetSetDescriptorType, MemberDescriptorType
from typing import NoReturn

from . import rsi_python_brs_admission as admission
from .rsi_brs_rejection_ready_sync import assert_ready_condition, capture_ready_condition
from .rsi_learning import RSILearningError
from .rsi_python_brs_child_policy import MAX_BRS_CHILD_ATTEMPTS

_CHANNEL = admission.BRSAdmissionChannel
_PENDING = admission._Pending
_READY = admission.BRSAdmissionReady
_MAX_PAYLOAD = admission.MAX_BRS_ADMISSION_BYTES
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_NONCE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
_CHANNEL_FIELDS = frozenset({
    "_run_id", "_episode_ids", "_owner_thread", "_condition", "_queue", "_requests",
    "_closed", "_servicing", "_handoff_mode", "_selected_episode_id",
    "_selected_handoff_sha256", "_consumed_handoff_nonces", "_completed_selected_episodes",
    "_rejection_ready_worker_guarded",
})
_PENDING_FIELDS = ("ready", "state", "binding_sha256", "ack", "ack_fields", "error", "cancelled")
_READY_FIELDS = ("run_id", "episode_id", "payload", "request_sha256")
_SLOT_TABLES = tuple((kind, tuple((name, vars(kind)[name]) for name in names))
                    for kind, names in ((_PENDING, _PENDING_FIELDS), (_READY, _READY_FIELDS)))
_CLASS_PATHS = tuple((kind, kind.__bases__, vars(kind).get("__getattribute__"),
                      vars(kind).get("__getattr__")) for kind in (_CHANNEL, _PENDING, _READY))
_CHANNEL_DICT = vars(_CHANNEL)["__dict__"]
_MEMBER_GET = MemberDescriptorType.__get__
_DICT_GET = GetSetDescriptorType.__get__

# run, selected episode, handoff digest, singleton nonce, complete episode domain, owner thread
_Scope = tuple[str, str, str, str, tuple[str, ...], int]
_ReadyFields = tuple[str, str, bytes, str]
# Scope, sync capsule, original object references, original ready primitive values.
_Capsule = tuple[_Scope, tuple, tuple, _ReadyFields]


def _fail(reason: str) -> NoReturn:
    raise RSILearningError("rsi_brs_rejection_ready_channel_" + reason)


def _thread_reader():
    native_ident = get_ident

    def read():
        if get_ident is not native_ident:
            _fail("thread_binding_drift")
        value = native_ident()
        if type(value) is not int or not 0 < value < 2**64:
            _fail("thread_binding_drift")
        return value

    return read


_caller_thread = _thread_reader()


def _classes() -> None:
    for name, original in (("BRSAdmissionChannel", _CHANNEL), ("_Pending", _PENDING),
                           ("BRSAdmissionReady", _READY)):
        if vars(admission).get(name) is not original:
            _fail("class_drift")
    for kind, bases, getattribute, getattr_ in _CLASS_PATHS:
        namespace = vars(kind)
        if (kind.__bases__ is not bases or namespace.get("__getattribute__") is not getattribute
                or namespace.get("__getattr__") is not getattr_):
            _fail("class_drift")
    if vars(_CHANNEL).get("__dict__") is not _CHANNEL_DICT:
        _fail("class_drift")
    for kind, members in _SLOT_TABLES:
        for name, descriptor in members:
            if type(descriptor) is not MemberDescriptorType or vars(kind).get(name) is not descriptor:
                _fail("class_drift")


def _slot(value: object, kind: type, name: str):
    # Invoke the independently held native descriptor, never a current property or
    # instance __getattribute__. _classes also refuses a drifted declaration.
    for declared, members in _SLOT_TABLES:
        if declared is kind:
            for field, descriptor in members:
                if field == name:
                    try:
                        return _MEMBER_GET(descriptor, value, kind)
                    except AttributeError:
                        _fail("state_invalid")
    _fail("class_drift")


def _scope(value: object) -> _Scope:
    if type(value) is not tuple or len(value) != 6:
        _fail("scope_invalid")
    run, selected, digest, nonce, episodes, owner = value
    for identifier in (run, selected):
        if type(identifier) is not str or _ID.fullmatch(identifier) is None:
            _fail("scope_invalid")
    if (type(digest) is not str or _SHA.fullmatch(digest) is None or digest == "0" * 64
            or type(nonce) is not str or _NONCE.fullmatch(nonce) is None
            or type(owner) is not int or not 0 < owner < 2**64
            or type(episodes) is not tuple or not 1 <= len(episodes) <= MAX_BRS_CHILD_ATTEMPTS):
        _fail("scope_invalid")
    for episode in episodes:
        if type(episode) is not str or _ID.fullmatch(episode) is None:
            _fail("scope_invalid")
    if len(set(episodes)) != len(episodes) or selected not in episodes:
        _fail("scope_invalid")
    return value


def _namespace(channel: object) -> dict:
    if type(channel) is not _CHANNEL:
        _fail("channel_invalid")
    _classes()
    namespace = _DICT_GET(_CHANNEL_DICT, channel, _CHANNEL)
    if (type(namespace) is not dict or len(namespace) != len(_CHANNEL_FIELDS)
            or any(type(key) is not str for key in namespace) or set(namespace) != _CHANNEL_FIELDS):
        _fail("channel_invalid")
    if type(namespace["_rejection_ready_worker_guarded"]) is not bool:
        _fail("channel_invalid")
    return namespace


def _ready_fields(fields: object, scope: _Scope) -> _ReadyFields:
    if type(fields) is not tuple or len(fields) != 4:
        _fail("state_invalid")
    run, episode, payload, digest = fields
    if (type(run) is not str or type(episode) is not str or type(payload) is not bytes
            or type(digest) is not str or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or digest == "0" * 64
            or not 0 < len(payload) <= _MAX_PAYLOAD):
        _fail("state_invalid")
    if (run, episode) != scope[:2]:
        _fail("state_invalid")
    return fields


def _observe(channel: object, scope: _Scope, condition: object,
             current_thread: int) -> tuple[tuple, _ReadyFields]:
    namespace = _namespace(channel)
    run, selected, digest, nonce, episodes, owner = scope
    if (namespace["_condition"] is not condition or current_thread != owner
            or type(namespace["_owner_thread"]) is not int or namespace["_owner_thread"] != owner
            or type(namespace["_run_id"]) is not str or namespace["_run_id"] != run
            or namespace["_closed"] is not False or namespace["_servicing"] is not False
            or namespace["_handoff_mode"] is not True
            or type(namespace["_selected_episode_id"]) is not str
            or namespace["_selected_episode_id"] != selected
            or type(namespace["_selected_handoff_sha256"]) is not str
            or namespace["_selected_handoff_sha256"] != digest):
        _fail("state_invalid")
    episode_set, nonces = namespace["_episode_ids"], namespace["_consumed_handoff_nonces"]
    completed, requests, queue = (namespace["_completed_selected_episodes"],
                                  namespace["_requests"], namespace["_queue"])
    if (type(episode_set) is not frozenset or len(episode_set) != len(episodes)
            or any(type(item) is not str for item in episode_set)
            or episode_set != frozenset(episodes)
            or type(nonces) is not set or len(nonces) != 1
            or any(type(item) is not str for item in nonces) or nonces != {nonce}
            or type(completed) is not set or completed
            or type(requests) is not dict or len(requests) != 1
            or any(type(key) is not str for key in requests)
            or type(queue) is not deque or queue.maxlen is not None or len(queue) != 1
            or selected not in requests):
        _fail("state_invalid")
    pending = requests[selected]
    if type(pending) is not _PENDING or queue[0] is not pending:
        _fail("state_invalid")
    state, binding = _slot(pending, _PENDING, "state"), _slot(pending, _PENDING, "binding_sha256")
    if (type(state) is not str or state != "queued" or type(binding) is not str or binding != digest
            or _slot(pending, _PENDING, "ack") is not None
            or _slot(pending, _PENDING, "ack_fields") is not None
            or _slot(pending, _PENDING, "error") is not None
            or _slot(pending, _PENDING, "cancelled") is not False):
        _fail("state_invalid")
    ready = _slot(pending, _PENDING, "ready")
    if type(ready) is not _READY:
        _fail("state_invalid")
    fields = _ready_fields(tuple(_slot(ready, _READY, name) for name in _READY_FIELDS), scope)
    _classes()
    return ((channel, condition, queue, requests, episode_set, nonces, completed, pending, ready), fields)


def capture_selected_ready_stage(channel: object, *, expected_scope: tuple) -> _Capsule:
    """Observe a selected queued request only; no arming, dequeue or ACK authority.

    expected_scope is the exact primitive tuple (run_id, selected_episode_id,
    handoff_sha256, lease_nonce, complete_episode_ids_tuple, owner_thread_id).
    Payload bytes are bounded comparison data; no canonical/semantic parsing occurs.
    """
    scope = _scope(expected_scope)
    current_thread = _caller_thread()
    condition = _namespace(channel)["_condition"]
    sync = capture_ready_condition(condition)
    assert_ready_condition(condition, sync)
    # The sync guard retains and verifies this original concrete native RLock.
    # Do not dispatch mutable Condition context methods after checking them.
    with sync[1]:
        assert_ready_condition(condition, sync)
        objects, fields = _observe(channel, scope, condition, current_thread)
        assert_ready_condition(condition, sync)
    return scope, sync, objects, fields


def assert_selected_ready_stage(channel: object, capsule: tuple) -> None:
    """Require the same original queued identities and primitive values; never refresh."""
    if type(capsule) is not tuple or len(capsule) != 4:
        _fail("capsule_invalid")
    scope, sync, original, fields = capsule
    scope = _scope(scope)
    _ready_fields(fields, scope)
    current_thread = _caller_thread()
    if type(original) is not tuple or len(original) != 9 or original[0] is not channel:
        _fail("capsule_invalid")
    _namespace(channel)
    condition = original[1]
    assert_ready_condition(condition, sync)
    with sync[1]:
        assert_ready_condition(condition, sync)
        current, observed = _observe(channel, scope, condition, current_thread)
        if any(actual is not retained for actual, retained in zip(current, original, strict=True)):
            _fail("identity_changed")
        if observed != fields:
            _fail("ready_changed")
        assert_ready_condition(condition, sync)


__all__ = ["assert_selected_ready_stage", "capture_selected_ready_stage"]
