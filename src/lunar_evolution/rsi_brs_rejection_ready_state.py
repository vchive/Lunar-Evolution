"""Passive checks of the original queued capsule after transport transitions.

These readers neither perform a transition nor grant service/ACK authority. They
accept only a previously retained queued capsule, never capture a later baseline.
The owner must separately validate admission, physical evidence and deadlines.
"""

from __future__ import annotations

import builtins
import dataclasses
import types
from collections import deque

from . import rsi_brs_rejection_ready_ack as ack_graph
from . import rsi_brs_rejection_ready_channel as queued
from . import rsi_brs_rejection_ready_sync as sync
from .rsi_learning import RSILearningError


def _build_observers():
    kind, length, namespace_of, pairs = type, len, vars, zip
    some, plain_tuple, plain_str, plain_int = any, tuple, str, int
    plain_dict, plain_set, frozen_set, queue_type = dict, set, frozenset, deque
    error, function_type, member_type = RSILearningError, types.FunctionType, types.MemberDescriptorType
    module_type, mapping_type = types.ModuleType, types.MappingProxyType
    value_error, attribute_error = ValueError, AttributeError
    error_new = BaseException.__new__
    error_dictionary = namespace_of(BaseException)["__dict__"]
    dictionary_get, dictionary_set = types.GetSetDescriptorType.__get__, dict.__setitem__
    names = ("_fail", "_classes", "_slot", "_scope", "_namespace", "_ready_fields", "_caller_thread")
    helpers = tuple(namespace_of(queued)[name] for name in names)
    functions = (*helpers, sync.assert_ready_condition, ack_graph.assert_rejection_ready_ack,
                 ack_graph.assert_rejection_ready_ack_graph)
    pins = tuple((fn, fn.__code__, fn.__defaults__, fn.__kwdefaults__,
                  tuple((fn.__kwdefaults__ or {}).items()), fn.__closure__,
                  tuple(cell.cell_contents for cell in (fn.__closure__ or ())),
                  fn.__dict__, tuple(fn.__dict__.items()), fn.__annotations__,
                  tuple(fn.__annotations__.items()), fn.__name__, fn.__qualname__, fn.__module__, fn.__doc__)
                 for fn in functions)
    helper_namespace = namespace_of(queued)
    helper_aliases = tuple(helper_namespace.items())
    module_names = ((queued, helper_namespace), (sync, namespace_of(sync)),
                    (ack_graph, namespace_of(ack_graph)),
                    (dataclasses, namespace_of(dataclasses)), (builtins, namespace_of(builtins)),
                    (types, namespace_of(types)))
    builtin_namespace = namespace_of(builtins)
    builtin_names = ("type", "len", "vars", "zip", "any", "tuple", "str", "int", "dict", "set",
                     "frozenset", "getattr", "AttributeError", "ValueError")
    builtin_values = tuple((name, builtin_namespace[name]) for name in builtin_names)
    builtin_domains = tuple((fn.__globals__, fn.__globals__["__builtins__"], fn.__builtins__)
                            for fn in functions)
    channel_type, pending_type, ready_type = queued._CHANNEL, queued._PENDING, queued._READY
    (_fail, classes, slot, scope_shape, channel_namespace, ready_shape, caller_thread) = helpers
    assert_sync, assert_ack = sync.assert_ready_condition, ack_graph.assert_rejection_ready_ack
    assert_ack_graph = ack_graph.assert_rejection_ready_ack_graph
    member_get, descriptors = types.MemberDescriptorType.__get__, tuple(
        (name, namespace_of(pending_type)[name]) for name in queued._PENDING_FIELDS)
    # Slot declarations and lookup paths are independent of the slot values.
    # Retain the finite original transport declarations and their dataclass
    # metadata; a matching reconstructed class or field is never a baseline.
    declarations = (channel_type, pending_type, ready_type)
    class_pins = plain_tuple((declared, declared.__bases__, declared.__mro__,
                             plain_tuple(namespace_of(declared).items())) for declared in declarations)
    field_type = dataclasses.Field
    metadata_descriptor = namespace_of(field_type)["metadata"]
    field_slots = plain_tuple((name, namespace_of(field_type)[name])
                              for name in field_type.__slots__)
    dataclass_pins = []
    for declared in (pending_type, ready_type):
        namespace = namespace_of(declared)
        table, annotations = namespace["__dataclass_fields__"], namespace["__annotations__"]
        field_pins = plain_tuple((name, field, plain_tuple(
            (descriptor, member_get(descriptor, field, field_type))
            for _label, descriptor in field_slots),
            plain_tuple(field.metadata.items())) for name, field in table.items())
        parameters = namespace["__dataclass_params__"]
        parameter_type = kind(parameters)
        parameter_pins = plain_tuple((namespace_of(parameter_type)[name],
                                       member_get(namespace_of(parameter_type)[name],
                                                  parameters, parameter_type))
                                      for name in parameter_type.__slots__)
        dataclass_pins.append((table, field_pins, annotations, plain_tuple(annotations.items()),
                               parameters, parameter_type, parameter_pins))
    dataclass_pins = plain_tuple(dataclass_pins)
    max_keys = 16384
    missing = object()

    def fail():
        # Detection itself must not dispatch a changed application exception
        # initializer, __setattr__ or attribute reader.
        message = "rsi_brs_rejection_ready_state_invalid"
        refusal = error_new(error, message)
        dictionary_set(dictionary_get(error_dictionary, refusal, error), "code", message)
        raise refusal

    def guard():
        # Held primitives check key types before any dictionary lookup/comparison.
        for module, namespace in module_names:
            if (kind(module) is not module_type or namespace_of(module) is not namespace
                    or length(namespace) > max_keys
                    or some(kind(key) is not plain_str for key in namespace)):
                fail()
        if length(helper_namespace) != length(helper_aliases):
            fail()
        for name, original in helper_aliases:
            if helper_namespace.get(name, missing) is not original:
                fail()
        if namespace_of(sync).get("assert_ready_condition") is not assert_sync:
            fail()
        if (namespace_of(ack_graph).get("assert_rejection_ready_ack") is not assert_ack
                or namespace_of(ack_graph).get("assert_rejection_ready_ack_graph") is not assert_ack_graph):
            fail()
        for name, original in builtin_values:
            if builtin_namespace.get(name, missing) is not original:
                fail()
        for namespace, original, domain in builtin_domains:
            if (namespace.get("__builtins__", missing) is not original
                    or kind(domain) is not plain_dict or length(domain) > max_keys
                    or some(kind(key) is not plain_str for key in domain)):
                fail()
            for name, value in builtin_values:
                if namespace.get(name, value) is not value or domain.get(name, missing) is not value:
                    fail()
        for pin in pins:
            (fn, code, defaults, kwdefaults, kwitems, closure, captures, attributes, attritems,
             annotations, annotationitems, label, qualname, module_name, doc) = pin
            if (kind(fn) is not function_type or fn.__code__ is not code
                    or fn.__defaults__ is not defaults or fn.__kwdefaults__ is not kwdefaults
                    or fn.__closure__ is not closure or fn.__dict__ is not attributes
                    or fn.__annotations__ is not annotations):
                fail()
            for mapping, entries in ((kwdefaults, kwitems), (attributes, attritems),
                                     (annotations, annotationitems)):
                if mapping is None:
                    continue
                if (kind(mapping) is not plain_dict or length(mapping) != length(entries)
                        or some(kind(key) is not plain_str for key in mapping)):
                    fail()
                for key, value in entries:
                    if mapping.get(key, missing) is not value:
                        fail()
            for cell, original in pairs(closure or (), captures, strict=True):
                try:
                    if cell.cell_contents is not original:
                        fail()
                except value_error:
                    fail()
            for value, original in ((fn.__name__, label), (fn.__qualname__, qualname),
                                    (fn.__module__, module_name), (fn.__doc__, doc)):
                if kind(value) is not kind(original) or value != original:
                    fail()
        for declared, bases, mro, members in class_pins:
            if (kind(declared) is not kind or declared.__bases__ is not bases
                    or declared.__mro__ is not mro):
                fail()
            namespace = namespace_of(declared)
            if (length(namespace) != length(members)
                    or some(kind(key) is not plain_str for key in namespace)):
                fail()
            for name, original in members:
                if namespace.get(name, missing) is not original:
                    fail()
        for table, fields, annotations, labels, parameters, parameter_type, parameter_pins in dataclass_pins:
            if (kind(table) is not plain_dict or length(table) != length(fields)
                    or some(kind(key) is not plain_str for key in table)
                    or kind(annotations) is not plain_dict or length(annotations) != length(labels)
                    or some(kind(key) is not plain_str for key in annotations)
                    or kind(parameters) is not parameter_type):
                fail()
            for name, original in labels:
                if annotations.get(name, missing) is not original:
                    fail()
            for name, field, values, metadata in fields:
                if table.get(name, missing) is not field or kind(field) is not field_type:
                    fail()
                for descriptor, original in values:
                    if member_get(descriptor, field, field_type) is not original:
                        fail()
                value = member_get(metadata_descriptor, field, field_type)
                if (kind(value) is not mapping_type or length(value) != length(metadata)
                        or some(kind(key) is not plain_str for key in value)):
                    fail()
                for label, original in metadata:
                    if value.get(label, missing) is not original:
                        fail()
            for descriptor, original in parameter_pins:
                if member_get(descriptor, parameters, parameter_type) is not original:
                    fail()
        # Original queued helpers have their own refusal paths. Prove their
        # shared exception graph before allowing either validation or refusal.
        try:
            assert_ack_graph()
        except error:
            fail()
        classes()
        for name, descriptor in descriptors:
            if (kind(descriptor) is not member_type
                    or namespace_of(pending_type).get(name, missing) is not descriptor):
                fail()

    def pending_slot(pending, name):
        for field, descriptor in descriptors:
            if field == name:
                try:
                    return member_get(descriptor, pending, pending_type)
                except attribute_error:
                    fail()
        fail()

    def observe(channel, capsule, committed, ack, ack_fields):
        guard()
        if (kind(channel) is not channel_type or kind(capsule) is not plain_tuple
                or length(capsule) != 4):
            fail()
        scope, condition_capture, objects, fields = capsule
        scope_shape(scope)
        ready_shape(fields, scope)
        if (kind(objects) is not plain_tuple or length(objects) != 9 or objects[0] is not channel
                or caller_thread() != scope[5]):
            fail()
        condition = objects[1]
        assert_sync(condition, condition_capture)
        with condition_capture[1]:
            assert_sync(condition, condition_capture)
            namespace = channel_namespace(channel)
            run, selected, digest, nonce, episodes, owner = scope
            if (namespace["_condition"] is not condition or namespace["_closed"] is not False
                    or namespace["_servicing"] is not (not committed)
                    or kind(namespace["_run_id"]) is not plain_str or namespace["_run_id"] != run
                    or kind(namespace["_owner_thread"]) is not plain_int or namespace["_owner_thread"] != owner
                    or namespace["_handoff_mode"] is not True
                    or kind(namespace["_selected_episode_id"]) is not plain_str
                    or namespace["_selected_episode_id"] != selected
                    or kind(namespace["_selected_handoff_sha256"]) is not plain_str
                    or namespace["_selected_handoff_sha256"] != digest):
                fail()
            queue, requests, episode_set, nonces, completed = (namespace[name] for name in (
                "_queue", "_requests", "_episode_ids", "_consumed_handoff_nonces",
                "_completed_selected_episodes"))
            if (kind(queue) is not queue_type or queue.maxlen is not None or length(queue) != 0
                    or kind(requests) is not plain_dict or length(requests) != 1
                    or some(kind(key) is not plain_str for key in requests)
                    or kind(episode_set) is not frozen_set
                    or some(kind(value) is not plain_str for value in episode_set)
                    or episode_set != frozen_set(episodes)
                    or kind(nonces) is not plain_set or length(nonces) != 1
                    or some(kind(value) is not plain_str for value in nonces) or nonces != {nonce}
                    or kind(completed) is not plain_set or length(completed) != 0
                    or selected not in requests):
                fail()
            pending = requests[selected]
            if kind(pending) is not pending_type:
                fail()
            ready = pending_slot(pending, "ready")
            if kind(ready) is not ready_type:
                fail()
            current = (channel, condition, queue, requests, episode_set, nonces, completed, pending, ready)
            if some(value is not original for value, original in pairs(current, objects, strict=True)):
                fail()
            observed = plain_tuple(slot(ready, ready_type, name) for name in (
                "run_id", "episode_id", "payload", "request_sha256"))
            ready_shape(observed, scope)
            if observed != fields:
                fail()
            state, binding = pending_slot(pending, "state"), pending_slot(pending, "binding_sha256")
            if (kind(state) is not plain_str or state != ("done" if committed else "inflight")
                    or kind(binding) is not plain_str or binding != digest
                    or pending_slot(pending, "cancelled") is not False
                    or pending_slot(pending, "error") is not None):
                fail()
            if committed:
                if (kind(ack_fields) is not plain_tuple or length(ack_fields) != 4
                        or some(kind(value) is not plain_str for value in ack_fields)
                        or ack_fields[:3] != (fields[0], fields[1], fields[3])
                        or pending_slot(pending, "ack") is not ack
                        or pending_slot(pending, "ack_fields") is not ack_fields):
                    fail()
                assert_ack(ack, ack_fields)
            elif pending_slot(pending, "ack") is not None or pending_slot(pending, "ack_fields") is not None:
                fail()
            assert_sync(condition, condition_capture)

    def assert_selected_ready_inflight(channel: object, capsule: tuple) -> None:
        """Check the original dequeued pending, without clearing or acknowledging it."""
        observe(channel, capsule, False, None, None)

    def assert_selected_ready_committed(channel: object, capsule: tuple,
                                        ack: object, ack_fields: tuple) -> None:
        """Check retained ACK evidence; this does not prove actual worker receipt."""
        observe(channel, capsule, True, ack, ack_fields)

    # The enclosing capture policy independently pins the code, closure and
    # metadata of these finite local readers before any owner effect. Comparison
    # capsules and this declaration alone grant no transition permission.
    functions = (fail, guard, pending_slot, observe,
                 assert_selected_ready_inflight, assert_selected_ready_committed)
    return assert_selected_ready_inflight, assert_selected_ready_committed, functions


(assert_selected_ready_inflight, assert_selected_ready_committed,
 _STATE_FUNCTIONS) = _build_observers()
