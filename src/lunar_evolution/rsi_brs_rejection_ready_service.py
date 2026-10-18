"""One original rejected owner stages one selected ready ACK before visibility.

Queue waiting holds only the original channel lock. Semantic reconstruction and
ACK construction run outside both short locks; the final fixed reader runs under
observation -> original channel lock. Failure never clears a published ACK prefix.
Nothing in this module registers a reference or grants result/dispatch authority.
"""

from __future__ import annotations

import _thread
import hashlib
import math
import time
from collections import deque
from threading import Condition
from types import GetSetDescriptorType, MemberDescriptorType

from . import rsi_brs_rejection_ready_ack as ack_graph
from . import rsi_brs_rejection_ready_channel as queued
from . import rsi_brs_rejection_ready_ledger as raw_ledger
from . import rsi_brs_rejection_ready_locks as locks
from . import rsi_brs_rejection_ready_reference as reference
from . import rsi_brs_rejection_ready_state as state
from . import rsi_brs_rejection_ready_sync as sync
from .rsi_learning import RSILearningError

_PENDING = queued._PENDING
_PENDING_SLOTS = tuple((name, vars(_PENDING)[name]) for name in queued._PENDING_FIELDS)
_MEMBER_SET = MemberDescriptorType.__set__
_ERROR_NEW = BaseException.__new__
_ERROR_DICT = vars(BaseException)["__dict__"]
_DICT_GET = GetSetDescriptorType.__get__
_DICT_SET = dict.__setitem__
_WAIT = Condition.wait
_NOTIFY_ALL = Condition.notify_all
_MONOTONIC = time.monotonic
_WALL_TIME = time.time
_FINITE = math.isfinite


def _fail(reason: str) -> None:
    message = "rsi_brs_rejection_ready_service_" + reason
    failure = _ERROR_NEW(RSILearningError, message)
    _DICT_SET(_DICT_GET(_ERROR_DICT, failure, RSILearningError), "code", message)
    raise failure


def _timeout(value: object) -> float:
    # Refuse foreign numeric conversion/equality before invoking either.
    if ((type(value) is not int and type(value) is not float)
            or not 0 < value <= 60 or not _FINITE(value)):
        _fail("timeout_invalid")
    return float(value)


def _set_pending(pending: object, name: str, value: object) -> None:
    # Bypass a changed application __setattr__; final policy guards declarations.
    for label, descriptor in _PENDING_SLOTS:
        if label == name:
            _MEMBER_SET(descriptor, pending, value)
            return
    _fail("pending_slot_invalid")


def _owner(owner: object) -> tuple:
    from .rsi_brs_publication_lineage import _BRSLineageCheckpointOwner

    if type(owner) is not _BRSLineageCheckpointOwner:
        _fail("owner_invalid")
    capture = owner._rejection_ready_capture
    if (type(capture) is not tuple or len(capture) != 6
            or owner._rejection_ready_capture_started is not True
            or owner._poisoned is not False or type(owner._phase) is not str
            or owner._phase != "rejected-provenance"
            or queued._caller_thread() != owner._thread):
        _fail("original_capture_required")
    held, rows, condition, scope, existing, payload = capture
    if (type(held) is not tuple or type(rows) is not tuple or type(condition) is not tuple
            or type(existing) is not tuple or len(existing) != 4 or type(payload) is not bytes):
        _fail("capture_invalid")
    queued._scope(scope)
    if (owner._channel is not held[3] or owner._before_channel_condition is not held[4]
            or owner._rejection_ready_sync_capture is not condition):
        _fail("capture_drift")
    locks.assert_rejection_ready_locks(owner._controller, owner._ledger, owner._before_control,
                                     owner._rejection_ready_locks_capture)
    sync.assert_ready_condition(owner._before_channel_condition, condition)
    return capture


def _empty_transport(owner: object, capture: tuple, original: tuple | None = None) -> tuple:
    """Check armed-empty without weakening the old provenance empty observer."""
    channel = owner._channel
    scope, condition = capture[3], capture[2]
    sync.assert_ready_condition(owner._before_channel_condition, condition)
    namespace = queued._namespace(channel)
    run, selected, digest, nonce, episodes, thread = scope
    if (namespace["_condition"] is not condition[0] or namespace["_closed"] is not False
            or namespace["_servicing"] is not False or namespace["_handoff_mode"] is not True
            or namespace["_rejection_ready_worker_guarded"] is not (original is not None)
            or type(namespace["_owner_thread"]) is not int or namespace["_owner_thread"] != thread
            or type(namespace["_run_id"]) is not str or namespace["_run_id"] != run
            or type(namespace["_selected_episode_id"]) is not str
            or namespace["_selected_episode_id"] != selected
            or type(namespace["_selected_handoff_sha256"]) is not str
            or namespace["_selected_handoff_sha256"] != digest):
        _fail("empty_transport_drift")
    queue, requests, domain, nonces, completed = (namespace[name] for name in (
        "_queue", "_requests", "_episode_ids", "_consumed_handoff_nonces", "_completed_selected_episodes"))
    if (type(queue) is not deque or queue.maxlen is not None or len(queue) != 0
            or type(requests) is not dict or len(requests) != 0
            or type(domain) is not frozenset or any(type(value) is not str for value in domain)
            or domain != frozenset(episodes) or type(nonces) is not set or len(nonces) != 1
            or any(type(value) is not str for value in nonces) or nonces != {nonce}
            or type(completed) is not set or len(completed) != 0):
        _fail("empty_transport_drift")
    objects = channel, condition[0], queue, requests, domain, nonces, completed
    if original is not None and any(value is not held for value, held in zip(objects, original, strict=True)):
        _fail("transport_identity_drift")
    return objects


def _remaining(expiry: float, unix_deadlines: tuple, monotonic_deadlines: tuple) -> float:
    monotonic_now, unix_now = _MONOTONIC(), _WALL_TIME()
    remaining = expiry - monotonic_now
    for deadline in unix_deadlines:
        if (type(deadline) is not int and type(deadline) is not float) or not _FINITE(deadline):
            _fail("deadline_invalid")
        remaining = min(remaining, deadline - unix_now)
    for deadline in monotonic_deadlines:
        if (type(deadline) is not int and type(deadline) is not float) or not _FINITE(deadline):
            _fail("deadline_invalid")
        remaining = min(remaining, deadline - monotonic_now)
    if remaining <= 0:
        _fail("queue_timeout")
    return remaining


def _take_ready(owner: object, capture: tuple, expiry: float,
                unix_deadlines: tuple, monotonic_deadlines: tuple) -> tuple:
    condition, scope = capture[2], capture[3]
    channel = owner._channel
    # Hold the independent checker before arming. A worker's check callback can
    # run while wait releases the condition; it cannot supply a later baseline.
    functions = _SERVICE_FUNCTIONS
    guard, refusal = functions[2], functions[0]
    kind, length, some, pairs, plain_tuple = type, len, any, zip, tuple
    plain_dict, plain_str, native_error, value_error = dict, str, RSILearningError, ValueError
    native_new, dictionary_get, dictionary_set = _ERROR_NEW, _DICT_GET, _DICT_SET
    error_dictionary = _ERROR_DICT
    guard_pins = plain_tuple((function, function.__code__, function.__globals__, function.__builtins__,
                              function.__defaults__, function.__kwdefaults__,
                              plain_tuple((function.__kwdefaults__ or {}).items()), function.__closure__,
                              plain_tuple(cell.cell_contents for cell in function.__closure__ or ()),
                              function.__dict__, plain_tuple(function.__dict__.items()),
                              function.__annotations__, plain_tuple(function.__annotations__.items()),
                              function.__name__, function.__qualname__, function.__module__, function.__doc__)
                             for function in (guard, refusal))
    wait, notify_all, remaining_reader = _WAIT, _NOTIFY_ALL, _remaining
    with condition[1]:
        # Empty must still hold atomically with arming; an early ready refuses.
        original = _empty_transport(owner, capture)
        owner._rejection_ready_state = "armed"
        queued._namespace(channel)["_rejection_ready_worker_guarded"] = True
        notify_all(condition[0])
        while True:
            # Bootstrap before invoking even a reader after a worker callback.
            # Detection itself uses held C allocation and native descriptors.
            invalid = False
            for pin in guard_pins:
                (function, code, domain, builtin_domain, defaults, kwdefaults, kwitems, closure, captures,
                 attributes, attritems, annotations, annotationitems, name, qualname, module, doc) = pin
                if (function.__code__ is not code or function.__globals__ is not domain
                        or function.__builtins__ is not builtin_domain or function.__defaults__ is not defaults
                        or function.__kwdefaults__ is not kwdefaults or function.__closure__ is not closure
                        or function.__dict__ is not attributes or function.__annotations__ is not annotations):
                    invalid = True
                    break
                for mapping, entries in ((kwdefaults, kwitems), (attributes, attritems),
                                         (annotations, annotationitems)):
                    if mapping is not None and (kind(mapping) is not plain_dict
                            or length(mapping) != length(entries)
                            or some(kind(key) is not plain_str for key in mapping)
                            or some(mapping.get(key) is not value for key, value in entries)):
                        invalid = True
                        break
                try:
                    if some(cell.cell_contents is not value
                            for cell, value in pairs(closure or (), captures, strict=True)):
                        invalid = True
                except value_error:
                    invalid = True
                for value, held_value in ((function.__name__, name), (function.__qualname__, qualname),
                                          (function.__module__, module), (function.__doc__, doc)):
                    if kind(value) is not kind(held_value) or value != held_value:
                        invalid = True
            if invalid:
                message = "rsi_brs_rejection_ready_service_graph_drift"
                error = native_new(native_error, message)
                dictionary_set(dictionary_get(error_dictionary, error, native_error), "code", message)
                raise error
            guard()
            sync.assert_ready_condition(condition[0], condition)
            namespace = queued._namespace(channel)
            queue = namespace["_queue"]
            if type(queue) is not deque or queue is not original[2]:
                _fail("transport_identity_drift")
            if len(queue) == 0:
                _empty_transport(owner, capture, original)
                remaining = remaining_reader(expiry, unix_deadlines, monotonic_deadlines)
                wait(condition[0], remaining)
                continue
            # Observe the original natural queued request without adopting a
            # replacement Condition or container as a new baseline.
            objects, fields = queued._observe(channel, scope, condition[0], queued._caller_thread())
            if any(value is not held for value, held in zip(objects[:7], original, strict=True)):
                _fail("transport_identity_drift")
            remaining_reader(expiry, unix_deadlines, monotonic_deadlines)
            capsule = scope, condition, objects, fields
            owner._rejection_ready_stage = capsule
            pending = objects[7]
            if deque.popleft(queue) is not pending:
                _fail("pending_identity_drift")
            _set_pending(pending, "state", "inflight")
            namespace["_servicing"] = True
            owner._rejection_ready_state = "inflight"
            return capsule


def validate_active_ready(owner: object, ready: object) -> tuple:
    """Bind the controller semantic reader to this exact active original ready."""
    capture = _owner(owner)
    capsule = owner._rejection_ready_stage
    if (type(owner._rejection_ready_state) is not str or owner._rejection_ready_state != "inflight"
            or type(capsule) is not tuple or len(capsule) != 4
            or type(capsule[2]) is not tuple or len(capsule[2]) != 9
            or capsule[2][8] is not ready or capsule[0] is not capture[3]
            or capsule[1] is not capture[2]):
        _fail("active_ready_required")
    state.assert_selected_ready_inflight(owner._channel, capsule)
    run, episode, payload, request_digest = capsule[3]
    expected = hashlib.sha256(b"lunar-rsi-python-brs-ready-v1\0" + run.encode("utf-8")
                              + b"\0" + episode.encode("utf-8") + b"\0" + payload).hexdigest()
    if payload != capture[5] or request_digest != expected:
        _fail("ready_payload_drift")
    return capture


def _make_failure_handler(owner: object, condition_capture: tuple):
    """Retain native failure operations before any unlocked semantic callback."""
    kind, some, length = type, any, len
    dictionary_set = dict.__setitem__
    member_get, member_set = MemberDescriptorType.__get__, MemberDescriptorType.__set__
    owner_type = kind(owner)
    owner_slots = vars(owner_type)
    phase_slot, poison_slot = owner_slots.get("_rejection_ready_state"), owner_slots.get("_poisoned")
    owner_namespace = None
    if kind(phase_slot) is not MemberDescriptorType or kind(poison_slot) is not MemberDescriptorType:
        # Internal transport fixtures use a concrete native SimpleNamespace;
        # production entry has already required the exact slotted owner class.
        owner_namespace = object.__getattribute__(owner, "__dict__")
        if kind(owner_namespace) is not dict or some(kind(key) is not str for key in owner_namespace):
            _fail("failure_owner_invalid")
    channel = owner._channel
    namespace = _DICT_GET(queued._CHANNEL_DICT, channel, queued._CHANNEL)
    native_lock, waiters = condition_capture[1:3]
    waiter_type, waiter_release = _thread.LockType, vars(_thread.LockType)["release"]
    queue_pop = deque.popleft
    runtime_error, attribute_error = RuntimeError, AttributeError
    pending_type = _PENDING
    error_slot = next(descriptor for name, descriptor in _PENDING_SLOTS if name == "error")
    plain_string = str

    def fail(capsule):
        # No application helper, mutable exception initializer, Condition method
        # or user callback is reachable from this permanent-failure path.
        if owner_namespace is None:
            member_set(phase_slot, owner, "failed")
            member_set(poison_slot, owner, True)
        elif not some(kind(key) is not plain_string for key in owner_namespace):
            dictionary_set(owner_namespace, "_rejection_ready_state", "failed")
            dictionary_set(owner_namespace, "_poisoned", True)
        with native_lock:
            if some(kind(key) is not plain_string for key in namespace):
                return
            dictionary_set(namespace, "_servicing", False)
            dictionary_set(namespace, "_closed", True)
            if capsule is not None:
                pending = capsule[2][7]
                try:
                    error = member_get(error_slot, pending, pending_type)
                except attribute_error:
                    error = None
                if error is None:
                    member_set(error_slot, pending, "handler_failed")
            # Release only the retained original native waiters. Never call a
            # changed Condition.notify helper during an already failing scope.
            if length(waiters) > 4096 or some(kind(waiter) is not waiter_type for waiter in waiters):
                return
            while waiters:
                waiter = queue_pop(waiters)
                try:
                    waiter_release(waiter)
                except runtime_error:
                    pass  # The waiter may have timed out immediately before close.

    return fail


def _preserve_failure(owner: object, condition_capture: tuple, capsule: tuple | None) -> None:
    """Native close without clearing any original queue/pending/ACK evidence."""
    _make_failure_handler(owner, condition_capture)(capsule)


def service_rejection_ready(self, *, timeout: float) -> str:
    """Consume one staged-ACK scope on the exact original rejected owner only."""
    from . import rsi_brs_rejection_ready_final as final
    from .candidate_evaluation_spec import canonical_json
    from .rsi_brs_publication_lineage import _BRSLineageCheckpointOwner, _policy
    from .rsi_controller import RSILearningController

    if type(self) is not _BRSLineageCheckpointOwner:
        _fail("owner_invalid")
    capture = _owner(self)
    base_exception = BaseException
    condition = capture[2]
    capsule = None
    preserve_failure = _make_failure_handler(self, condition)
    try:
        duration = _timeout(timeout)
        if (type(self._rejection_ready_state) is not str or self._rejection_ready_state != "unused"
                or self._rejection_ready_stage is not None or self._rejection_ready_ack is not None
                or self._rejection_ready_ack_fields is not None
                or self._rejection_ready_commit_started is not False):
            _fail("scope_consumed")
        _BRSLineageCheckpointOwner._before_unlocked(self)
        _BRSLineageCheckpointOwner._before_channel(self)
        if canonical_json(_policy()) != self._policy_bytes:
            _fail("policy_drift")
        existing = reference.validate_existing_rejection_reference(self)
        if existing != capture[4] or self._rejection_ready_capture is not capture:
            _fail("existing_reference_drift")
        raw_ledger.assert_rejection_ready_rows(str(self._ledger.database), capture[1])
        if canonical_json(_policy()) != self._policy_bytes:
            _fail("policy_drift")
        unix_deadlines, monotonic_deadlines = final.rejection_ready_deadlines(
            self._rejection_ready_final_capture)
        # Only queue waiting consumes this timeout. The independently retained
        # original deadlines still cap validation and commit on either side.
        expiry = _MONOTONIC() + duration
        capsule = _take_ready(self, capture, expiry, unix_deadlines, monotonic_deadlines)
        ready = capsule[2][8]
        validate_active_ready(self, ready)
        # This canonical controller root independently reconstructs admission
        # evidence but never registers, pins, charges or accepts a fresh reference.
        digest = RSILearningController._python_admission_existing_rejection_brs_ready(self._controller, self, ready)
        validate_active_ready(self, ready)
        if type(digest) is not str or digest != capture[4][2]:
            _fail("existing_record_drift")
        fields = capsule[3][0], capsule[3][1], capsule[3][3], digest
        ack = ack_graph.build_rejection_ready_ack(fields)
        self._rejection_ready_ack, self._rejection_ready_ack_fields = ack, fields
        if canonical_json(_policy()) != self._policy_bytes:
            _fail("policy_drift")
        # Only fixed observation and transport readers follow the last dynamic
        # policy/source check. Workers cannot see staged owner-local values.
        observation = self._rejection_ready_locks_capture[3]
        member_set, notify_all = _MEMBER_SET, _NOTIFY_ALL
        state_slot = next(descriptor for name, descriptor in _PENDING_SLOTS if name == "state")
        ack_slot = next(descriptor for name, descriptor in _PENDING_SLOTS if name == "ack")
        fields_slot = next(descriptor for name, descriptor in _PENDING_SLOTS if name == "ack_fields")
        with observation, condition[1]:
            state.assert_selected_ready_inflight(self._channel, capsule)
            ack_graph.assert_rejection_ready_ack(ack, fields)
            namespace = queued._namespace(self._channel)
            pending = capsule[2][7]
            final.assert_rejection_ready_final(self, self._rejection_ready_final_capture)
            # No callback/DTO observer is permitted beyond this point. Keep the
            # marker before the first ACK assignment and never roll back a prefix.
            self._rejection_ready_commit_started = True
            member_set(state_slot, pending, "done")
            member_set(ack_slot, pending, ack)
            member_set(fields_slot, pending, fields)
            self._rejection_ready_state = "committed"
            namespace["_servicing"] = False
            notify_all(condition[0])
        return digest
    except base_exception:
        # This path never calls the generic service or close, both of which can
        # clear queued/ACK evidence. A failed scope is permanently consumed.
        preserve_failure(capsule)
        raise


def _build_service_entry(implementation):
    """Hold the refusal/bootstrap graph before any mutable service helper runs."""
    import builtins
    import types

    kind, length, namespace_of, some, plain_tuple, pairs = type, len, vars, any, tuple, zip
    plain_dict, plain_str, function_type = dict, str, types.FunctionType
    error_type, native_new, value_error = RSILearningError, BaseException.__new__, ValueError
    dictionary = namespace_of(BaseException)["__dict__"]
    dictionary_get, dictionary_set = GetSetDescriptorType.__get__, dict.__setitem__
    own = globals()
    dependencies = (queued, ack_graph, raw_ledger, locks, reference, state, sync, hashlib, math, time)
    namespaces = plain_tuple((namespace_of(module), plain_tuple(namespace_of(module).items()))
                             for module in dependencies)
    builtins_namespace = namespace_of(builtins)
    builtin_values = plain_tuple((name, builtins_namespace[name]) for name in (
        "type", "len", "any", "tuple", "dict", "float", "str", "int", "min", "next", "zip",
        "vars", "getattr", "BaseException"))
    missing = object()
    own_entries = ()
    pins = ()

    def refuse():
        message = "rsi_brs_rejection_ready_service_graph_drift"
        failure = native_new(error_type, message)
        dictionary_set(dictionary_get(dictionary, failure, error_type), "code", message)
        raise failure

    def pack(function):
        return (function, function.__code__, function.__globals__, function.__defaults__,
                function.__kwdefaults__, plain_tuple((function.__kwdefaults__ or {}).items()),
                function.__closure__, plain_tuple(cell.cell_contents for cell in (function.__closure__ or ())),
                function.__dict__, plain_tuple(function.__dict__.items()),
                function.__annotations__, plain_tuple(function.__annotations__.items()),
                function.__name__, function.__qualname__, function.__module__, function.__doc__)

    def guard():
        for namespace, entries in (*namespaces, (own, own_entries)):
            if (kind(namespace) is not plain_dict or length(namespace) != length(entries)
                    or some(kind(key) is not plain_str for key in namespace)):
                refuse()
            for name, original in entries:
                if namespace.get(name, missing) is not original:
                    refuse()
        for name, original in builtin_values:
            if builtins_namespace.get(name, missing) is not original:
                refuse()
        for pin in pins:
            (function, code, namespace, defaults, kwdefaults, kwitems, closure, captures,
             attributes, attritems, annotations, annotationitems, name, qualname, module, doc) = pin
            if (kind(function) is not function_type or function.__code__ is not code
                    or function.__globals__ is not namespace or function.__defaults__ is not defaults
                    or function.__kwdefaults__ is not kwdefaults or function.__closure__ is not closure
                    or function.__dict__ is not attributes or function.__annotations__ is not annotations):
                refuse()
            for mapping, entries in ((kwdefaults, kwitems), (attributes, attritems),
                                     (annotations, annotationitems)):
                if mapping is None:
                    continue
                if (kind(mapping) is not plain_dict or length(mapping) != length(entries)
                        or some(kind(key) is not plain_str for key in mapping)):
                    refuse()
                for label, original in entries:
                    if mapping.get(label, missing) is not original:
                        refuse()
            for cell, original in pairs(closure or (), captures, strict=True):
                try:
                    if cell.cell_contents is not original:
                        refuse()
                except value_error:
                    refuse()
            for value, original in ((function.__name__, name), (function.__qualname__, qualname),
                                    (function.__module__, module), (function.__doc__, doc)):
                if kind(value) is not kind(original) or value != original:
                    refuse()
        # Shared application exception and transport declarations are independently
        # checked before _owner may enter their ordinary refusal paths.
        ack_graph.assert_rejection_ready_ack_graph()

    guard_code = guard.__code__
    guard_closure, guard_defaults = guard.__closure__, guard.__defaults__
    guard_attributes, guard_annotations = guard.__dict__, guard.__annotations__
    guard_captures = ()
    refuse_code, refuse_closure = refuse.__code__, refuse.__closure__
    refuse_captures = plain_tuple(cell.cell_contents for cell in (refuse_closure or ()))

    def service_rejection_ready(self, *, timeout: float) -> str:
        if (refuse.__code__ is not refuse_code or refuse.__closure__ is not refuse_closure
                or some(cell.cell_contents is not original
                        for cell, original in pairs(refuse_closure or (), refuse_captures, strict=True))):
            message = "rsi_brs_rejection_ready_service_graph_drift"
            failure = native_new(error_type, message)
            dictionary_set(dictionary_get(dictionary, failure, error_type), "code", message)
            raise failure
        if (guard.__code__ is not guard_code or guard.__closure__ is not guard_closure
                or guard.__defaults__ is not guard_defaults or guard.__kwdefaults__ is not None
                or guard.__dict__ is not guard_attributes or guard.__annotations__ is not guard_annotations
                or length(guard_attributes) != 0 or length(guard_annotations) != 0
                or some(cell.cell_contents is not original
                        for cell, original in pairs(guard_closure or (), guard_captures, strict=True))):
            refuse()
        guard()
        return implementation(self, timeout=timeout)

    functions = refuse, pack, guard, implementation, service_rejection_ready
    pins = plain_tuple(pack(function) for function in (
        refuse, pack, implementation,
        *(value for _name, value in plain_tuple(own.items()) if kind(value) is function_type),
        *(value for namespace, _entries in namespaces
          for _name, value in plain_tuple(namespace.items()) if kind(value) is function_type),
    ))
    own_entries = plain_tuple((name, service_rejection_ready if name == "service_rejection_ready" else value)
                              for name, value in own.items()) + (("_SERVICE_FUNCTIONS", functions),)
    guard_captures = plain_tuple(cell.cell_contents for cell in (guard_closure or ()))
    return service_rejection_ready, functions


service_rejection_ready, _SERVICE_FUNCTIONS = _build_service_entry(service_rejection_ready)
